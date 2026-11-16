"""Registry of crawlers BarkaGate checks.

Every entry was checked against the vendor's own documentation (2026-11-16).
`ua` is the vendor-published HTTP user-agent where one is published. When a
vendor only documents the robots.txt token (ua_published=False), BarkaGate
sends a minimal user-agent containing that token, which is what most WAF/CDN
rules match on.

Kinds:
  search    - indexes pages so they can be cited in AI/web search answers
  user      - fetches a page live because a user asked the assistant
  training  - collects data for model training (reported, never an "error")
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Bot:
    name: str            # robots.txt token
    vendor: str
    kind: str            # search | user | training
    ua: Optional[str]    # HTTP user-agent to send; None = robots.txt-only token
    ua_published: bool   # True if `ua` is the vendor-published string
    docs: str            # vendor documentation used for verification
    ip_list: Optional[str] = None


def _token_ua(token: str) -> str:
    return f"Mozilla/5.0 (compatible; {token}/1.0)"


_OPENAI = "https://developers.openai.com/api/docs/bots"
_ANTHROPIC = ("https://support.claude.com/en/articles/8896518-does-anthropic-crawl-"
              "data-from-the-web-and-how-can-site-owners-block-the-crawler")
_PPLX = "https://docs.perplexity.ai/guides/bots"
_GOOGLE = "https://developers.google.com/search/docs/crawling-indexing/google-common-crawlers"
_APPLE = "https://support.apple.com/en-us/119829"

BOTS = [
    # --- search / citation crawlers --------------------------------------
    Bot("OAI-SearchBot", "OpenAI", "search",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
        "OAI-SearchBot/1.4; +https://openai.com/searchbot",
        True, _OPENAI, "https://openai.com/searchbot.json"),
    Bot("Claude-SearchBot", "Anthropic", "search", _token_ua("Claude-SearchBot"),
        False, _ANTHROPIC, "https://claude.com/crawling/bots.json"),
    Bot("PerplexityBot", "Perplexity", "search",
        "Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
        True, _PPLX, "https://www.perplexity.ai/perplexitybot.json"),
    Bot("Googlebot", "Google", "search",
        "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36 "
        "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        True, _GOOGLE),
    Bot("Bingbot", "Microsoft", "search", _token_ua("bingbot"), False,
        "https://www.bing.com/webmasters/help/which-crawlers-does-bing-use-8c184ec0"),
    Bot("Applebot", "Apple", "search",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15 "
        "(Applebot/0.1; +http://www.apple.com/go/applebot)",
        True, _APPLE, "http://search.developer.apple.com/applebot.json"),
    # --- user-triggered fetchers -----------------------------------------
    Bot("ChatGPT-User", "OpenAI", "user",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
        "ChatGPT-User/1.0; +https://openai.com/bot",
        True, _OPENAI, "https://openai.com/chatgpt-user.json"),
    Bot("Claude-User", "Anthropic", "user", _token_ua("Claude-User"),
        False, _ANTHROPIC, "https://claude.com/crawling/bots.json"),
    Bot("Perplexity-User", "Perplexity", "user",
        "Mozilla/5.0 (compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)",
        True, _PPLX, "https://www.perplexity.ai/perplexity-user.json"),
    # --- training crawlers / opt-out tokens (reported, not errors) -------
    Bot("GPTBot", "OpenAI", "training",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
        "GPTBot/1.4; +https://openai.com/gptbot",
        True, _OPENAI, "https://openai.com/gptbot.json"),
    Bot("ClaudeBot", "Anthropic", "training", _token_ua("ClaudeBot"),
        False, _ANTHROPIC, "https://claude.com/crawling/bots.json"),
    Bot("CCBot", "Common Crawl", "training",
        "CCBot/2.0 (https://commoncrawl.org/faq/)", True,
        "https://commoncrawl.org/ccbot", "https://index.commoncrawl.org/ccbot.json"),
    # robots.txt-only control tokens: no own HTTP user-agent per vendor docs
    Bot("Google-Extended", "Google", "training", None, False, _GOOGLE),
    Bot("Applebot-Extended", "Apple", "training", None, False, _APPLE),
]


def by_name(names):
    wanted = {n.lower() for n in names}
    found = [b for b in BOTS if b.name.lower() in wanted]
    missing = wanted - {b.name.lower() for b in found}
    if missing:
        raise KeyError(", ".join(sorted(missing)))
    return found
