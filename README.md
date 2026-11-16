# BarkaGate

**Can ChatGPT, Claude, Perplexity, Google and Apple actually reach your site?**

BarkaGate checks two things for every major AI crawler:

1. **robots.txt**: is the bot allowed on this page? (RFC 9309 rules: longest match, `*` and `$` wildcards)
2. **The real HTTP response**: does your firewall, CDN or bot protection answer the bot's user-agent with `403`, `429` or a challenge page while normal browsers get `200`?

Many sites block AI search bots without knowing it, usually through a CDN "block AI bots" toggle. Then they never show up in AI answers.

BarkaGate keeps **search/answer bots** (which can cite you) apart from **training crawlers** (which collect model-training data). Blocking training crawlers is a legitimate choice, so it is reported as information, not as an error.

## Get started in 1 minute

```bash
pip install .            # Python 3.10+, no dependencies
barkagate https://example.com/
```

Or without installing: `python -m barkagate https://example.com/`

Options:

| Flag | Meaning |
|---|---|
| `--json` | machine-readable output |
| `--bots Googlebot,GPTBot` | check only some bots |
| `--list-bots` | show every bot, its type and the vendor doc it was checked against |
| `--strict-training` | also fail when training crawlers are blocked |
| `--timeout 15` | seconds per request |

Exit codes: `0` = all search/user bots get through, `1` = at least one is blocked, `2` = error / could not check.

## Example output

```
BarkaGate 0.1.0 - https://example.com/
robots.txt: https://example.com/robots.txt (status 200)
Normal browser: 200

Bot                Type           robots.txt             HTTP           Result
-----------------  -------------  ---------------------  -------------  -------
OAI-SearchBot      AI/web search  allowed                200 ok         OK
Claude-SearchBot   AI/web search  allowed                200 ok         OK
PerplexityBot      AI/web search  allowed                403 blocked    BLOCKED
Googlebot          AI/web search  allowed                200 ok         OK
Bingbot            AI/web search  allowed                200 ok         OK
Applebot           AI/web search  allowed                200 ok         OK
ChatGPT-User       user fetch     allowed                200 ok         OK
Claude-User        user fetch     allowed                403 challenge  BLOCKED
Perplexity-User    user fetch     allowed                200 ok         OK
GPTBot             training       blocked (Disallow: /)  200 ok         NOTE
ClaudeBot          training       allowed                200 ok         OK
CCBot              training       blocked (Disallow: /)  200 ok         NOTE
Google-Extended    training       allowed                n/a            OK
Applebot-Extended  training       allowed                n/a            OK

BLOCKED for AI search/answers: PerplexityBot, Claude-User
Training crawlers opted out (informational): GPTBot, CCBot
```

## GitHub Action

```yaml
- uses: OWNER/barkagate@v0   # replace OWNER once published
  with:
    url: https://example.com/
    # bots: "OAI-SearchBot,Claude-SearchBot,PerplexityBot"
    # strict-training: "true"
```

The job fails when an AI search or answer bot is blocked.

## Bots and sources

Every bot name and user-agent comes from the vendor's own documentation (run `barkagate --list-bots` to see the source URL for each).

- OpenAI: OAI-SearchBot, ChatGPT-User, GPTBot
- Anthropic: Claude-SearchBot, Claude-User, ClaudeBot
- Perplexity: PerplexityBot, Perplexity-User
- Google: Googlebot, Google-Extended
- Microsoft: Bingbot
- Apple: Applebot, Applebot-Extended
- Common Crawl: CCBot

Some vendors publish only the robots.txt token, not a full user-agent string (Anthropic's bots and Bingbot). For those, BarkaGate sends a minimal user-agent that contains the token, which is what WAF/CDN rules usually match. `Google-Extended` and `Applebot-Extended` are robots.txt control tokens with no user-agent of their own, so only robots.txt is checked for them.

**Limits:** BarkaGate sends requests from your own IP. Some firewalls verify bots by IP or reverse DNS, so a real crawler may get a different answer than BarkaGate does. A `200` here means "not blocked by user-agent". User-triggered fetchers (ChatGPT-User, Perplexity-User) may ignore robots.txt, according to their vendors.

## Safety

BarkaGate only contacts public internet addresses. Private, loopback, link-local and cloud-metadata addresses are refused, every redirect is checked again, and connections are pinned to the checked IP.

## Development

```bash
python -m unittest discover -s tests -v   # offline; uses a local test server
```

## License

MIT. See [LICENSE](LICENSE).

---

Part of the Barka toolkit by Barkamonte – https://barkamonte.com
