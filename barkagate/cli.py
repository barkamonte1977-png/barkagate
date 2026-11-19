"""Command-line interface.

Exit codes: 0 = all search/user bots can reach the page,
            1 = at least one search/user bot is blocked,
            2 = usage error or the site could not be checked.
Training crawlers are reported but never cause a non-zero exit
(unless --strict-training is given).
"""

import argparse
import json
import os
import sys

from . import TOOL_NAME, __version__
from .bots import BOTS, by_name
from .check import run
from .fetch import BlockedAddress

FIX_URL = "https://barkamonte.com/seo/?utm_source=barkagate"
FIX_LINE = f"Found problems? We fix them: {FIX_URL}"


def quiet_env():
    """BARKA_QUIET=1 (any non-empty value except 0/false/no) hides the fix-it line."""
    return os.environ.get("BARKA_QUIET", "").strip().lower() not in ("", "0", "false", "no")


KIND_LABEL = {"search": "AI/web search", "user": "user fetch", "training": "training"}


def _color(enabled):
    def paint(text, code):
        return f"\033[{code}m{text}\033[0m" if enabled else text
    return paint


def render_table(report, color=False, promo=True):
    paint = _color(color)
    rows = []
    for r in report["results"]:
        robots_col = "allowed" if r.robots_allowed else f"blocked ({r.robots_rule})"
        if r.http_verdict == "skipped":
            http_col = "n/a"
        elif r.http_status is None:
            http_col = r.http_verdict
        else:
            http_col = f"{r.http_status} {r.http_verdict}"
        rows.append((r.bot, KIND_LABEL[r.kind], robots_col, http_col, r.verdict))
    head = ("Bot", "Type", "robots.txt", "HTTP", "Result")
    widths = [max(len(str(x)) for x in col) for col in zip(head, *rows)]
    fmt = "  ".join("{:<%d}" % w for w in widths)
    out = [f"{TOOL_NAME} {__version__} - {report['url']}",
           f"robots.txt: {report['robots_url']} (status {report['robots_status']})"]
    if report["robots_note"]:
        out.append(f"  note: {report['robots_note']}")
    base = report["baseline_status"] if report["baseline_error"] is None else report["baseline_error"]
    out.append(f"Normal browser: {base}")
    out.append("")
    out.append(fmt.format(*head).rstrip())
    out.append(fmt.format(*("-" * w for w in widths)))
    colors = {"OK": "32", "BLOCKED": "31", "NOTE": "33"}
    for row in rows:
        line = fmt.format(*row).rstrip()
        verdict = row[-1]
        out.append(line[: -len(verdict)] + paint(verdict, colors[verdict])
                   if line.endswith(verdict) else line)
    blocked = [r.bot for r in report["results"] if r.verdict == "BLOCKED"]
    noted = [r.bot for r in report["results"] if r.verdict == "NOTE"]
    out.append("")
    if blocked:
        out.append(paint(f"BLOCKED for AI search/answers: {', '.join(blocked)}", "31"))
    else:
        out.append(paint("All AI search and user-fetch bots can reach this page.", "32"))
    if noted:
        out.append(f"Training crawlers opted out (informational): {', '.join(noted)}")
    if blocked and promo:
        out.append("")
        out.append(FIX_LINE)
    return "\n".join(out)


def to_json(report):
    data = dict(report)
    data["results"] = [r.to_dict() for r in report["results"]]
    data["tool"] = {"name": TOOL_NAME, "version": __version__}
    return json.dumps(data, indent=2)


def exit_code(report, strict_training=False):
    if report["baseline_error"] and all(r.http_verdict in ("error", "skipped")
                                        for r in report["results"]):
        return 2
    bad = {"BLOCKED", "NOTE"} if strict_training else {"BLOCKED"}
    return 1 if any(r.verdict in bad for r in report["results"]) else 0


def main(argv=None, *, _fetch_kw=None):
    p = argparse.ArgumentParser(
        prog=TOOL_NAME.lower(),
        description="Check whether AI crawlers can reach a page (robots.txt + real HTTP response).")
    p.add_argument("url", nargs="?", help="page to check, e.g. https://example.com/")
    p.add_argument("--json", action="store_true", help="print machine-readable JSON")
    p.add_argument("--bots", help="comma-separated subset of bots to check")
    p.add_argument("--list-bots", action="store_true", help="list known bots and exit")
    p.add_argument("--strict-training", action="store_true",
                   help="also fail (exit 1) when training crawlers are blocked")
    p.add_argument("--timeout", type=float, default=15, help="seconds per request (default 15)")
    p.add_argument("--no-color", action="store_true", help="disable colored output")
    p.add_argument("--quiet", action="store_true",
                   help="hide the 'we fix them' line (or set BARKA_QUIET=1)")
    p.add_argument("--version", action="version", version=f"{TOOL_NAME} {__version__}")
    args = p.parse_args(argv)

    if args.list_bots:
        for b in BOTS:
            ua = "robots.txt token only" if b.ua is None else (
                "published UA" if b.ua_published else "token-based UA")
            print(f"{b.name:<18} {b.vendor:<13} {KIND_LABEL[b.kind]:<14} {ua:<22} {b.docs}")
        return 0
    if not args.url:
        p.error("url is required")

    try:
        bots = by_name(args.bots.split(",")) if args.bots else BOTS
    except KeyError as exc:
        print(f"Unknown bot(s): {exc}. Use --list-bots.", file=sys.stderr)
        return 2

    kw = {"timeout": args.timeout, **(_fetch_kw or {})}
    try:
        report = run(args.url, bots, **kw)
    except BlockedAddress as exc:
        print(f"Refused: {exc} (only public addresses are checked)", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(to_json(report))
    else:
        color = (not args.no_color and sys.stdout.isatty()
                 and os.environ.get("NO_COLOR") is None)
        print(render_table(report, color=color,
                           promo=not (args.quiet or quiet_env())))
    return exit_code(report, args.strict_training)


if __name__ == "__main__":
    sys.exit(main())
