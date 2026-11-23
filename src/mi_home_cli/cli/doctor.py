"""`mi doctor`: environment self-check for login."""
from __future__ import annotations

import socket
import ssl
import time
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
import typer

from .. import render
from ..render import OutputFormat
from ..core import const
from ..core.callback import local_ips, port_available, resolve_redirect_host
from ..store import file_is_private
from .context import AppContext, pick_output

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

# Colours are only added in the table; json/yaml/plain output must not contain rich
# markup.
_COLORS = {OK: "green", WARN: "yellow", FAIL: "red"}


def _check_reachable(url: str, timeout: float) -> tuple[str, str]:
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=False)
    except httpx.HTTPError as err:
        return FAIL, f"{type(err).__name__}: {err}"
    return OK, f"HTTP {response.status_code}"


# Fake-IP ranges of proxies such as Clash / Surge. A hostname resolving into these means
# the traffic is taken over by a proxy.
_FAKE_IP_PREFIXES = ("198.18.", "198.19.", "240.", "28.")


def _check_broker(host: str, port: int, timeout: float) -> tuple[str, str]:
    """MQTT has to get past both TCP and TLS; test them separately — the two point troubleshooting in completely different directions."""
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, port)})
    except socket.gaierror as err:
        return FAIL, f"DNS resolution failed: {err}"
    fake = [ip for ip in addresses if ip.startswith(_FAKE_IP_PREFIXES)]

    started = time.time()
    try:
        with socket.create_connection((host, port), timeout=min(timeout, 5)) as raw:
            elapsed = (time.time() - started) * 1000
            from ..core.mqtt import ssl_contexts

            note = ""
            for index, context in enumerate(ssl_contexts()):
                try:
                    with context.wrap_socket(raw, server_hostname=host):
                        pass
                    note = " (using certifi's CA bundle)" if index else ""
                    break
                except ssl.SSLCertVerificationError as err:
                    verify_error = err
                    # Switching CA bundles needs a new connection; this socket cannot be
                    # reused after a failed wrap
                    raw.close()
                    try:
                        raw = socket.create_connection(
                            (host, port), timeout=min(timeout, 5)
                        )
                    except OSError:
                        break
                except ssl.SSLError as err:
                    return FAIL, f"TLS handshake failed: {err}"
            else:
                detail = (
                    f"TCP OK ({elapsed:.0f}ms) but certificate verification failed: "
                    f"{verify_error.verify_message or verify_error}"
                )
                if fake:
                    detail += f"; the host resolves to {fake[0]}, a proxy fake-IP: add a direct rule for it"
                return FAIL, detail
    except socket.timeout:
        return FAIL, "connection timed out; this port is probably blocked outbound (mi watch will not work)"
    except OSError as err:
        return FAIL, f"{type(err).__name__}: {err}"

    detail = f"TCP + TLS both OK ({elapsed:.0f}ms){note}"
    if fake:
        detail += f"; note it resolves to {fake[0]}, traffic goes through a proxy"
    return OK, detail


def _check_clock(timeout: float) -> tuple[str, str]:
    """Too much clock skew breaks OAuth and the token validity checks."""
    try:
        response = httpx.get(
            "https://account.xiaomi.com/", timeout=timeout, follow_redirects=False
        )
        server_date = response.headers.get("date")
        if not server_date:
            return WARN, "the response has no Date header"
        skew = time.time() - parsedate_to_datetime(server_date).timestamp()
    except (httpx.HTTPError, ValueError, TypeError) as err:
        return WARN, f"cannot tell: {err}"
    if abs(skew) > 300:
        return FAIL, f"The local clock differs from the server by {skew:.0f} seconds"
    return OK, f"skew {skew:.0f} s"


def run(ctx: typer.Context, output=None) -> None:
    app_ctx: AppContext = ctx.obj
    timeout = app_ctx.timeout
    rows: list[dict[str, Any]] = []

    def add(item: str, status: str, detail: str) -> None:
        rows.append({"Check": item, "Result": status, "Description": detail})

    # 1. Config directory and permissions
    profile = app_ctx.profile
    if profile.auth_path.exists():
        private = file_is_private(profile.auth_path)
        add(
            "Credential file permissions",
            OK if private else FAIL,
            str(profile.auth_path) + ("" if private else ", readable by other users; "
                                                         "chmod 600 recommended"),
        )
    else:
        add("Credential file", WARN, f"not logged in ({profile.auth_path} does not exist)")

    # 2. Login state
    auth = profile.read_auth()
    if auth:
        left = auth.expires_at - time.time()
        add(
            "Login state",
            OK if left > 0 else FAIL,
            f"{auth.nickname or '?'} / {auth.region} / {max(int(left), 0)} s left",
        )

    # 3. Callback path: port + hostname resolution
    free = port_available(const.REDIRECT_PORT)
    add(
        f"Port {const.REDIRECT_PORT}",
        OK if free else WARN,
        "available" if free else "in use; login is only possible by pasting",
    )
    resolved = resolve_redirect_host()
    mine = set(local_ips())
    if not resolved:
        add(
            f"{const.REDIRECT_HOST} resolution",
            WARN,
            "does not resolve; login will try mDNS and otherwise fall back to pasting",
        )
    elif set(resolved) & mine:
        add(f"{const.REDIRECT_HOST} resolution", OK, "points at this machine ("
                                             f"{', '.join(resolved)})")
    else:
        add(
            f"{const.REDIRECT_HOST} resolution",
            WARN,
            f"points at {', '.join(resolved)}, not this machine; the callback will "
            "land on that machine",
        )

    try:
        import zeroconf  # noqa: F401

        add("zeroconf", OK, "installed; mDNS can be advertised automatically")
    except ImportError:
        add(
            "zeroconf",
            WARN,
            "not installed; installing it improves the automatic callback success "
            "rate: uv sync --extra mdns",
        )

    # 4. Network connectivity
    status, detail = _check_reachable("https://account.xiaomi.com/", timeout)
    add("account.xiaomi.com", status, detail)
    region = app_ctx.resolved_region()
    status, detail = _check_reachable(f"https://{const.api_host(region)}/", timeout)
    add(f"{const.api_host(region)}", status, detail)

    # 5. MQTT broker (used by mi watch)
    from ..core.mqtt import BROKER_PORT, broker_host

    host = broker_host(region)
    status, detail = _check_broker(host, BROKER_PORT, timeout)
    add(f"{host}:{BROKER_PORT}", status, detail)

    # 6. Clock
    status, detail = _check_clock(timeout)
    add("System clock", status, detail)

    fmt = pick_output(app_ctx, output)
    display = rows
    if fmt is OutputFormat.table:
        display = [
            {**row, "Result": f"[{_COLORS[row['Result']]}]{row['Result']}[/]"}
            for row in rows
        ]
    render.output(display, fmt, columns=["Check", "Result", "Description"])
    if any(row["Result"] == FAIL for row in rows):
        raise typer.Exit(code=1)


def dns_hint() -> str:
    """The hosts-file fallback shown to the user."""
    ip = next((item for item in local_ips() if item != "127.0.0.1"), "127.0.0.1")
    return f"{ip}\t{const.REDIRECT_HOST}"


def resolve_debug() -> dict[str, Any]:
    return {
        "resolved": resolve_redirect_host(),
        "local_ips": local_ips(),
        "hostname": socket.gethostname(),
    }
