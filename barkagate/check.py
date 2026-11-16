"""Core check logic: robots.txt + live HTTP probe per bot."""

from dataclasses import asdict, dataclass
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from . import robots
from .bots import BOTS
from .fetch import BlockedAddress, fetch

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
BLOCK_STATUSES = {401, 403, 406, 429, 451, 503}
CHALLENGE_MARKERS = (b"cf-chl", b"challenge-platform", b"captcha", b"Just a moment")


@dataclass
class BotResult:
    bot: str
    vendor: str
    kind: str
    robots_allowed: bool
    robots_rule: Optional[str]
    http_status: Optional[int]
    http_verdict: str          # ok | blocked | challenge | error | skipped
    http_note: str
    verdict: str               # OK | BLOCKED | NOTE

    def to_dict(self):
        return asdict(self)


def _http_verdict(resp, baseline_status):
    if resp is None:
        return "error"
    if resp.headers.get("cf-mitigated") == "challenge":
        return "challenge"
    body = resp.body[:65536]
    if resp.status in (403, 503) and any(m in body for m in CHALLENGE_MARKERS):
        return "challenge"
    if resp.status >= 400 and (baseline_status is None or baseline_status < 400):
        return "blocked"
    return "ok"


def run(url, bots=None, *, fetcher=fetch, **fetch_kw):
    """Check `url` for every bot. Returns a dict with baseline, robots info and results."""
    bots = bots or BOTS
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))

    # RFC 9309: 4xx = everything allowed; 5xx / unreachable = treat as fully disallowed.
    robots_status, robots_note, groups = None, "", []
    try:
        r = fetcher(robots_url, BROWSER_UA, **fetch_kw)
        robots_status = r.status
        if r.status == 200:
            groups = robots.parse(r.body.decode("utf-8", "replace"))
        elif r.status >= 500:
            robots_note = "robots.txt returned 5xx: crawlers treat the site as fully disallowed"
            groups = robots.parse("User-agent: *\nDisallow: /")
        else:
            robots_note = f"robots.txt returned {r.status}: everything allowed"
    except BlockedAddress:
        raise
    except OSError as exc:
        robots_note = f"robots.txt unreachable ({exc}): crawlers treat the site as disallowed"
        groups = robots.parse("User-agent: *\nDisallow: /")

    baseline_status, baseline_error = None, None
    try:
        baseline_status = fetcher(url, BROWSER_UA, **fetch_kw).status
    except BlockedAddress:
        raise
    except OSError as exc:
        baseline_error = str(exc)

    results = []
    for bot in bots:
        allowed, rule = robots.evaluate(groups, bot.name, path)
        status, hv, note = None, "skipped", ""
        if bot.ua is None:
            note = "robots.txt control token only (no own HTTP user-agent)"
        else:
            resp = None
            try:
                resp = fetcher(url, bot.ua, **fetch_kw)
                status = resp.status
            except BlockedAddress:
                raise
            except OSError as exc:
                note = f"request failed: {exc}"
            hv = _http_verdict(resp, baseline_status)
            if hv == "error" and baseline_error:
                note = "site unreachable for normal browsers too"
            elif not note and not bot.ua_published:
                note = "token-based user-agent (vendor publishes token only)"
        blocked = (not allowed) or hv in ("blocked", "challenge") or (
            hv == "error" and not baseline_error)
        if bot.kind == "training":
            verdict = "NOTE" if blocked else "OK"
        else:
            verdict = "BLOCKED" if blocked else "OK"
        results.append(BotResult(bot.name, bot.vendor, bot.kind, allowed, rule,
                                 status, hv, note, verdict))
    return {
        "url": url,
        "robots_url": robots_url,
        "robots_status": robots_status,
        "robots_note": robots_note,
        "baseline_status": baseline_status,
        "baseline_error": baseline_error,
        "results": results,
    }
