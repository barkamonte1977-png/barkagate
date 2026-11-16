"""HTTP fetching with SSRF protection.

Only public (globally routable) addresses are contacted. The hostname is
resolved once per hop, every resolved address must be public, and the
connection is pinned to the checked address (no DNS-rebinding window).
Every redirect hop is checked again.
"""

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

MAX_REDIRECTS = 5
MAX_BODY = 512 * 1024
TIMEOUT = 15


class BlockedAddress(Exception):
    """Raised when a URL resolves to a non-public address."""


@dataclass
class Response:
    url: str
    status: int
    headers: dict
    body: bytes
    redirects: list = field(default_factory=list)


def _resolve(host, port, allow_private):
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise OSError(f"DNS lookup failed for {host}: {exc}") from exc
    addrs = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if not allow_private and not ip.is_global:
            raise BlockedAddress(f"{host} resolves to non-public address {ip}")
        addrs.append(str(ip))
    if not addrs:
        raise OSError(f"No addresses for {host}")
    return addrs[0]


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, ip, host, port, timeout, context):
        super().__init__(host, port, timeout=timeout, context=context)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, ip, host, port, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


def _one(url, user_agent, timeout, allow_private, ssl_context):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parts.scheme!r}")
    if not parts.hostname:
        raise ValueError(f"URL has no host: {url}")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    ip = _resolve(parts.hostname, port, allow_private)
    if parts.scheme == "https":
        conn = _PinnedHTTPS(ip, parts.hostname, port, timeout,
                            ssl_context or ssl.create_default_context())
    else:
        conn = _PinnedHTTP(ip, parts.hostname, port, timeout)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    try:
        conn.request("GET", path, headers={
            "User-Agent": user_agent,
            "Accept": "text/html,text/plain,*/*;q=0.8",
            "Accept-Encoding": "identity",
            "Connection": "close",
        })
        resp = conn.getresponse()
        body = resp.read(MAX_BODY)
        headers = {k.lower(): v for k, v in resp.getheaders()}
        return resp.status, headers, body
    finally:
        conn.close()


def fetch(url, user_agent, *, timeout=TIMEOUT, allow_private=False, ssl_context=None):
    """GET `url` following up to MAX_REDIRECTS redirects, each one SSRF-checked.

    `allow_private` exists for offline tests only; the CLI never sets it.
    """
    redirects = []
    for _ in range(MAX_REDIRECTS + 1):
        status, headers, body = _one(url, user_agent, timeout, allow_private, ssl_context)
        if status in (301, 302, 303, 307, 308) and headers.get("location"):
            redirects.append(url)
            url = urljoin(url, headers["location"])
            continue
        return Response(url, status, headers, body, redirects)
    raise OSError(f"Too many redirects (>{MAX_REDIRECTS})")
