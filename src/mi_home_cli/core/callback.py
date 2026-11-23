"""Receiving the OAuth callback.

Xiaomi only accepts a redirect_uri whose host is homeassistant.local:8123 (see
const.py), so to get the code automatically two things must hold at once:

  1. the browser resolves homeassistant.local to the machine running the CLI;
  2. port 8123 on that machine is listened on by us.

There are three ways to satisfy condition 1: the machine already has a hosts entry,
there is an mDNS responder on the LAN (we can advertise one ourselves with
zeroconf), or the user adds a hosts entry by hand. When none of them holds, fall
back to having the user paste the URL from the browser's address bar — that path is
always available.
"""
from __future__ import annotations

import queue
import socket
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..errors import UsageError
from . import const

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:system-ui,-apple-system,"PingFang SC",sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;
background:#f6f7f9;color:#222}}div{{text-align:center}}
h1{{font-size:20px;margin:0 0 8px}}p{{color:#666;margin:0}}</style></head>
<body><div><h1>{title}</h1><p>{body}</p></div></body></html>
"""


@dataclass
class CallbackResult:
    code: str
    state: str | None
    source: str  # "server" or "paste"


class _Handler(BaseHTTPRequestHandler):
    server_version = "mi-home-cli"
    result_queue: "queue.Queue[CallbackResult]"

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler convention)
        params = parse_qs(urlparse(self.path).query)
        code = (params.get("code") or [None])[0]
        state = (params.get("state") or [None])[0]
        if code:
            self.result_queue.put(
                CallbackResult(code=code, state=state, source="server")
            )
            self._respond(200, "Login successful", "You can close this page and return to the "
                                       "terminal.")
        else:
            error = (params.get("error") or ["missing code parameter"])[0]
            self._respond(400, "Login failed", str(error))

    def _respond(self, status: int, title: str, body: str) -> None:
        payload = _PAGE.format(title=title, body=body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:
        """By default an access log goes to stderr; the CLI does not need it."""


class CallbackServer:
    """Listen on 8123 and wait for one callback."""

    def __init__(
        self, result_queue: "queue.Queue[object]",
        bind_host: str = "0.0.0.0",
        port: int = const.REDIRECT_PORT,
    ) -> None:
        handler = type("_BoundHandler", (_Handler,), {"result_queue": result_queue})
        self._httpd = HTTPServer((bind_host, port), handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="mi-oauth-callback", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def __enter__(self) -> "CallbackServer":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def port_available(port: int = const.REDIRECT_PORT, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def resolve_redirect_host(host: str = const.REDIRECT_HOST) -> list[str]:
    """The addresses homeassistant.local currently resolves to (an empty list if it does not resolve)."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    return sorted({info[4][0] for info in infos})


def local_ips() -> list[str]:
    """This machine's outward-facing IPs, used to tell whether homeassistant.local points at itself."""
    ips: set[str] = {"127.0.0.1"}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # No packet is actually sent; this only makes the kernel pick the default
            # egress address.
            sock.connect(("223.5.5.5", 53))
            ips.add(sock.getsockname()[0])
    except OSError:
        pass
    try:
        ips.update(
            info[4][0]
            for info in socket.getaddrinfo(socket.gethostname(), None)
        )
    except socket.gaierror:
        pass
    return sorted(ips)


class MdnsPublisher:
    """Advertise homeassistant.local as this machine's address (needs the optional dependency zeroconf).

    If there is already a real Home Assistant on the LAN the name collides; give up then
    and let the user paste.
    """

    def __init__(self, address: str) -> None:
        self._address = address
        self._zeroconf: Any = None
        self._info: Any = None

    def start(self) -> str | None:
        """Returns None on success, the reason on failure."""
        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            return "zeroconf is not installed (uv sync --extra mdns)"
        try:
            self._zeroconf = Zeroconf()
            self._info = ServiceInfo(
                "_http._tcp.local.",
                "mi-home-cli._http._tcp.local.",
                addresses=[socket.inet_aton(self._address)],
                port=const.REDIRECT_PORT,
                server=f"{const.REDIRECT_HOST}.",
            )
            self._zeroconf.register_service(self._info)
        except Exception as err:  # zeroconf raises a mixed bag of exception types
            self.close()
            return f"Failed to register mDNS: {err}"
        return None

    def close(self) -> None:
        try:
            if self._zeroconf and self._info:
                self._zeroconf.unregister_service(self._info)
        except Exception:
            pass
        try:
            if self._zeroconf:
                self._zeroconf.close()
        except Exception:
            pass
        self._zeroconf = None
        self._info = None


def parse_pasted(text: str, *, expected_state: str | None = None) -> CallbackResult:
    """Parse what the user pasted back.

    Three forms are supported:
      * a full URL: http://homeassistant.local:8123/...?code=xxx&state=yyy
      * just the query: code=xxx&state=yyy or ?code=xxx&state=yyy
      * just the code: xxx
    """
    text = text.strip().strip('"').strip("'")
    if not text:
        raise UsageError("Nothing was entered")

    query = ""
    if "://" in text:
        query = urlparse(text).query
    elif text.startswith("?"):
        query = text[1:]
    elif "code=" in text:
        query = text.lstrip("?")

    if query:
        params = parse_qs(query)
        error = (params.get("error") or params.get("error_description") or [None])[0]
        code = (params.get("code") or [None])[0]
        state = (params.get("state") or [None])[0]
        if not code:
            raise UsageError(
                f"This text has no code parameter: {error or text[:80]}",
            )
    else:
        if any(char in text for char in " \t\n"):
            raise UsageError("Unrecognized input; paste the complete redirect URL")
        code, state = text, None

    if expected_state and state and state != expected_state:
        raise UsageError(
            "state mismatch: this is not the callback of this login; run `mi auth "
            "login` again"
        )
    return CallbackResult(code=code, state=state, source="paste")
