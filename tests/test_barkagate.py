"""Offline tests: a local HTTP server stands in for a real website."""

import io
import json
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from barkagate import cli, fetch, robots
from barkagate.bots import BOTS, by_name
from barkagate.check import run

ROBOTS = """
User-agent: *
Disallow: /private/

User-agent: GPTBot
User-agent: CCBot
Disallow: /

User-agent: OAI-SearchBot
Disallow: /shop/
Allow: /shop/public$
"""


class Handler(BaseHTTPRequestHandler):
    robots_body = ROBOTS
    robots_status = 200

    def log_message(self, *a):
        pass

    def _send(self, status, body=b"<html>hi</html>", headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        ua = self.headers.get("User-Agent", "")
        if self.path == "/robots.txt":
            return self._send(self.robots_status, self.robots_body.encode())
        if self.path == "/redirect":
            return self._send(301, b"", {"Location": "/"})
        if self.path == "/loop":
            return self._send(302, b"", {"Location": "/loop"})
        if self.path == "/escape":
            port = self.server.server_address[1]
            return self._send(302, b"", {"Location": f"http://127.0.0.1:{port}/"})
        if "PerplexityBot" in ua:
            return self._send(403, b"Forbidden")
        if "Claude-User" in ua:
            return self._send(403, b"<title>Just a moment...</title>", {"cf-mitigated": "challenge"})
        return self._send(200)


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        Handler.robots_body, Handler.robots_status = ROBOTS, 200

    def check(self, path="/"):
        report = run(self.base + path, allow_private=True, timeout=5)
        return report, {r.bot: r for r in report["results"]}


class RobotsTests(unittest.TestCase):
    def setUp(self):
        self.g = robots.parse(ROBOTS)

    def test_specific_group_beats_star(self):
        self.assertFalse(robots.evaluate(self.g, "GPTBot", "/")[0])
        self.assertFalse(robots.evaluate(self.g, "ccbot", "/x")[0])  # case-insensitive
        self.assertTrue(robots.evaluate(self.g, "ClaudeBot", "/")[0])
        self.assertFalse(robots.evaluate(self.g, "ClaudeBot", "/private/a")[0])

    def test_specific_group_does_not_inherit_star(self):
        # OAI-SearchBot has its own group, so the * group's /private/ rule does not apply
        self.assertTrue(robots.evaluate(self.g, "OAI-SearchBot", "/private/a")[0])

    def test_longest_match_and_end_anchor(self):
        self.assertFalse(robots.evaluate(self.g, "OAI-SearchBot", "/shop/x")[0])
        self.assertTrue(robots.evaluate(self.g, "OAI-SearchBot", "/shop/public")[0])
        self.assertFalse(robots.evaluate(self.g, "OAI-SearchBot", "/shop/public/2")[0])

    def test_wildcard_and_tie(self):
        g = robots.parse("User-agent: *\nDisallow: /*.pdf$\nAllow: /a\nDisallow: /a\n")
        self.assertFalse(robots.evaluate(g, "x", "/docs/file.pdf")[0])
        self.assertTrue(robots.evaluate(g, "x", "/docs/file.pdf?v=1")[0])
        self.assertTrue(robots.evaluate(g, "x", "/a")[0])  # Allow wins ties

    def test_empty_disallow_and_comments(self):
        g = robots.parse("# hi\nUser-agent: *\nDisallow:   # nothing\n")
        self.assertEqual(robots.evaluate(g, "GPTBot", "/"), (True, None))


class RegistryTests(unittest.TestCase):
    def test_registry_sane(self):
        names = [b.name for b in BOTS]
        self.assertEqual(len(names), len(set(names)))
        for b in BOTS:
            self.assertIn(b.kind, ("search", "user", "training"))
            self.assertTrue(b.docs.startswith("https://"))
            if b.ua is not None:
                self.assertIn(b.name.lower(), b.ua.lower())
        for required in ("OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "Claude-User",
                         "PerplexityBot", "Perplexity-User", "Googlebot", "Bingbot",
                         "Applebot", "GPTBot", "ClaudeBot", "CCBot", "Google-Extended"):
            self.assertIn(required, names)

    def test_by_name(self):
        self.assertEqual([b.name for b in by_name(["gptbot"])], ["GPTBot"])
        with self.assertRaises(KeyError):
            by_name(["NoSuchBot"])


class CheckTests(ServerCase):
    def test_verdicts(self):
        report, r = self.check("/")
        self.assertEqual(report["baseline_status"], 200)
        self.assertEqual(r["Googlebot"].verdict, "OK")
        self.assertEqual(r["PerplexityBot"].http_verdict, "blocked")
        self.assertEqual(r["PerplexityBot"].verdict, "BLOCKED")
        self.assertEqual(r["Claude-User"].http_verdict, "challenge")
        self.assertEqual(r["GPTBot"].verdict, "NOTE")          # training: not an error
        self.assertFalse(r["GPTBot"].robots_allowed)
        self.assertEqual(r["Google-Extended"].http_verdict, "skipped")

    def test_robots_path_rules(self):
        _, r = self.check("/shop/x")
        self.assertEqual(r["OAI-SearchBot"].verdict, "BLOCKED")
        self.assertIn("Disallow: /shop/", r["OAI-SearchBot"].robots_rule)

    def test_robots_404_allows_all(self):
        Handler.robots_status = 404
        report, r = self.check("/")
        self.assertIn("everything allowed", report["robots_note"])
        self.assertEqual(r["GPTBot"].verdict, "OK")

    def test_robots_5xx_disallows_all(self):
        Handler.robots_status = 500
        _, r = self.check("/")
        self.assertEqual(r["Googlebot"].verdict, "BLOCKED")

    def test_redirect_followed(self):
        res = fetch.fetch(self.base + "/redirect", "x", allow_private=True, timeout=5)
        self.assertEqual(res.status, 200)
        self.assertEqual(len(res.redirects), 1)

    def test_redirect_loop(self):
        with self.assertRaises(OSError):
            fetch.fetch(self.base + "/loop", "x", allow_private=True, timeout=5)


class SSRFTests(ServerCase):
    def test_private_refused(self):
        for url in ("http://127.0.0.1/", "http://10.0.0.1/", "http://169.254.169.254/",
                    "http://[::1]/", "http://localhost/"):
            with self.assertRaises(fetch.BlockedAddress, msg=url):
                fetch.fetch(url, "x", timeout=2)

    def test_bad_scheme(self):
        with self.assertRaises(ValueError):
            fetch.fetch("file:///etc/passwd", "x")

    def test_redirect_to_private_refused(self):
        """First hop is treated as public; the redirect to 127.0.0.1 must be refused."""
        real = fetch._resolve

        def fake_resolve(host, port, allow_private):
            if host == "public.example":
                return "127.0.0.1"
            return real(host, port, allow_private)

        port = self.srv.server_address[1]
        with mock.patch.object(fetch, "_resolve", fake_resolve):
            with self.assertRaises(fetch.BlockedAddress):
                fetch.fetch(f"http://public.example:{port}/escape", "x", timeout=5)

    def test_cli_refuses_private(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["http://127.0.0.1/"]), 2)


class CLITests(ServerCase):
    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(list(args), _fetch_kw={"allow_private": True})
        return code, buf.getvalue()

    def test_table_and_exit_code(self):
        code, out = self.run_cli(self.base + "/", "--no-color", "--timeout", "5")
        self.assertEqual(code, 1)
        self.assertIn("PerplexityBot", out)
        self.assertIn("BLOCKED for AI search/answers", out)
        self.assertIn("Training crawlers opted out", out)

    def test_json_and_subset_ok(self):
        code, out = self.run_cli(self.base + "/", "--json", "--bots", "Googlebot,GPTBot")
        self.assertEqual(code, 0)  # GPTBot blocked, but training doesn't fail by default
        data = json.loads(out)
        self.assertEqual([r["bot"] for r in data["results"]], ["Googlebot", "GPTBot"])
        self.assertEqual(data["tool"]["name"], "BarkaGate")

    def test_fix_line_only_when_blocked(self):
        with mock.patch.dict("os.environ", {"BARKA_QUIET": ""}):
            _, out = self.run_cli(self.base + "/", "--no-color", "--timeout", "5")
            self.assertIn(cli.FIX_LINE, out)
            self.assertIn("utm_source=barkagate", out)
            _, out = self.run_cli(self.base + "/", "--bots", "Googlebot", "--timeout", "5")
            self.assertNotIn(cli.FIX_LINE, out)          # nothing blocked: no line
            _, out = self.run_cli(self.base + "/", "--json", "--timeout", "5")
            self.assertNotIn("We fix them", out)         # never in JSON

    def test_fix_line_can_be_turned_off(self):
        _, out = self.run_cli(self.base + "/", "--quiet", "--timeout", "5")
        self.assertNotIn(cli.FIX_LINE, out)
        with mock.patch.dict("os.environ", {"BARKA_QUIET": "1"}):
            _, out = self.run_cli(self.base + "/", "--timeout", "5")
        self.assertNotIn(cli.FIX_LINE, out)
        with mock.patch.dict("os.environ", {"BARKA_QUIET": "0"}):
            _, out = self.run_cli(self.base + "/", "--timeout", "5")
        self.assertIn(cli.FIX_LINE, out)

    def test_strict_training(self):
        code, _ = self.run_cli(self.base + "/", "--bots", "GPTBot", "--strict-training")
        self.assertEqual(code, 1)

    def test_unknown_bot(self):
        with mock.patch("sys.stderr", io.StringIO()):
            code, _ = self.run_cli(self.base + "/", "--bots", "Nope")
        self.assertEqual(code, 2)

    def test_list_bots(self):
        code, out = self.run_cli("--list-bots")
        self.assertEqual(code, 0)
        self.assertIn("Claude-SearchBot", out)


if __name__ == "__main__":
    unittest.main()
