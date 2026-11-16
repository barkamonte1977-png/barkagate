"""Minimal RFC 9309 robots.txt evaluator (longest match wins, Allow wins ties,
`*` and `$` wildcards, group selection by product token)."""

import re
from urllib.parse import unquote


def parse(text):
    """Return list of groups: (set_of_agents_lowercase, [(allow: bool, pattern)])."""
    groups, agents, rules, last_was_agent = [], set(), [], False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = (p.strip() for p in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not last_was_agent and (agents or rules):
                groups.append((agents, rules))
                agents, rules = set(), []
            agents.add(val.lower())
            last_was_agent = True
        elif key in ("allow", "disallow"):
            last_was_agent = False
            if agents and (val or key == "disallow"):
                if val:
                    rules.append((key == "allow", val))
    if agents:
        groups.append((agents, rules))
    return groups


def _rules_for(groups, token):
    token = token.lower()
    matched = [r for a, r in groups if token in a]
    if not matched:
        matched = [r for a, r in groups if "*" in a]
    return [rule for rs in matched for rule in rs]


def _pattern_regex(pattern):
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    rx = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.compile(rx + ("$" if anchored else ""))


def evaluate(groups, token, path):
    """Return (allowed: bool, matching_rule or None)."""
    path = unquote(path or "/")
    best = None
    for allow, pattern in _rules_for(groups, token):
        if _pattern_regex(unquote(pattern)).match(path):
            key = (len(pattern), allow)
            if best is None or key > best[0]:
                best = (key, allow, pattern)
    if best is None:
        return True, None
    return best[1], ("Allow: " if best[1] else "Disallow: ") + best[2]
