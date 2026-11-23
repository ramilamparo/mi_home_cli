"""Offline tests of QR-code login: the whole HTTP chain is replayed with httpx.MockTransport."""
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from mi_home_cli.core import const
from mi_home_cli.core.oauth import state_for_device
from mi_home_cli.core.qrlogin import QrChallenge, QrLoginClient, render_qr
from mi_home_cli.errors import CloudError, MiCliError, NetworkError

REDIRECT = const.redirect_url("1234567890")
DEVICE_ID = "ha.abcdef0123456789abcdef0123456789"
STATE = state_for_device(DEVICE_ID)

# The minimal usable response of serviceLogin?_json=true (real responses have more
# fields).
SERVICE_LOGIN = {
    "code": 70016,  # not logged in, normal
    "description": "login verification failed",
    "_sign": "2&V1_oauth2.0&SIGN=",
    "sid": "oauth2.0",
    "qs": "%3Fcallback%3Dxxx",
    "callback": "https://account.xiaomi.com/sts/oauth?sign=x&followup=y&sid=oauth2.0",
    "serviceParam": '{"checkSafePhone":false}',
}
LOGIN_URL = "https://sgp.account.xiaomi.com/longPolling/login?ticket=lp_abc&dc=sgp"
LP_URL = "https://sgp.lp.account.xiaomi.com/lp/s?k=lp_abc"
LONG_POLLING = {
    "code": 0,
    "result": "ok",
    "loginUrl": LOGIN_URL,
    "lp": LP_URL,
    "qr": "https://account.xiaomi.com/pass/qr/login?ticket=lp_abc",
    "timeout": 300,
}
# Redirect chain after confirmation: sts → authorize → redirect_uri?code=...
STS_LOCATION = "https://account.xiaomi.com/sts?ticket=abc&followup=z"
AUTHORIZE_BACK = "https://account.xiaomi.com/oauth2/authorize?resume=1"
FINAL_REDIRECT = f"{REDIRECT}?code=THE-CODE&state={STATE}"


def _client(handler) -> httpx.Client:
    # Mirror real usage: redirects are not followed automatically, we parse each hop
    # ourselves.
    return httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )


def _qr(handler) -> QrLoginClient:
    return QrLoginClient(
        redirect_url=REDIRECT,
        device_id=DEVICE_ID,
        state=STATE,
        client=_client(handler),
    )


def test_start_reuses_persistent_web_device_id():
    """The preset web deviceId is sent as a cookie, so Xiaomi treats it as the same device."""
    seen_cookies = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_cookies.append(request.headers.get("cookie", ""))
        path = request.url.path
        if path == "/oauth2/authorize":
            return httpx.Response(
                302, headers={"location": "https://account.xiaomi.com/pass/serviceLogin"}
            )
        if path == "/pass/serviceLogin":
            return httpx.Response(200, json=SERVICE_LOGIN)
        if path == "/longPolling/loginUrl":
            return httpx.Response(200, json=LONG_POLLING)
        raise AssertionError(path)

    client = QrLoginClient(
        redirect_url=REDIRECT,
        device_id=DEVICE_ID,
        state=STATE,
        web_device_id="wb_fixed-device-123",
        client=_client(handler),
    )
    with client:
        client.start()
    # the serviceLogin / longPolling hops all carried the fixed deviceId
    assert any("deviceId=wb_fixed-device-123" in c for c in seen_cookies)


def test_default_user_agent_identifies_tool_not_browser():
    # the default device name is the tool name, not a browser (so the Xiaomi account
    # does not fill up with Chrome entries)
    assert const.WEB_USER_AGENT.startswith("mi-home-cli/")
    assert "Chrome" not in const.WEB_USER_AGENT


def test_custom_user_agent_is_sent():
    """A custom user_agent is sent as the UA header and decides the device name Xiaomi shows."""
    seen_ua = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_ua.append(request.headers.get("user-agent", ""))
        if request.url.path == "/oauth2/authorize":
            return httpx.Response(
                302, headers={"location": "https://account.xiaomi.com/pass/serviceLogin"}
            )
        if request.url.path == "/pass/serviceLogin":
            return httpx.Response(200, json=SERVICE_LOGIN)
        if request.url.path == "/longPolling/loginUrl":
            return httpx.Response(200, json=LONG_POLLING)
        raise AssertionError(request.url.path)

    # with an injected client the test sets the UA itself; this verifies the "sent as
    # the UA header" path
    client = QrLoginClient(
        redirect_url=REDIRECT,
        device_id=DEVICE_ID,
        state=STATE,
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
            headers={"User-Agent": "MyLaptop"},
        ),
    )
    with client:
        client.start()
    assert seen_ua and all(ua == "MyLaptop" for ua in seen_ua)


def test_start_builds_challenge():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/oauth2/authorize":
            return httpx.Response(
                302, headers={"location": "https://account.xiaomi.com/pass/serviceLogin?sid=oauth2.0"}
            )
        if path == "/pass/serviceLogin":
            assert request.url.params.get("_json") == "true"
            return httpx.Response(200, json=SERVICE_LOGIN)
        if path == "/longPolling/loginUrl":
            # the login parameters from serviceLogin must be passed on unchanged
            assert request.url.params["_sign"] == SERVICE_LOGIN["_sign"]
            assert request.url.params["sid"] == "oauth2.0"
            assert request.url.params["callback"] == SERVICE_LOGIN["callback"]
            return httpx.Response(200, json=LONG_POLLING)
        raise AssertionError(f"unexpected request: {path}")

    with _qr(handler) as client:
        challenge = client.start()
    assert challenge.login_url == LOGIN_URL
    assert challenge.lp_url == LP_URL
    assert challenge.timeout == 300


def test_start_strips_json_prefix():
    import json as _json

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/oauth2/authorize":
            return httpx.Response(302, headers={"location": "https://account.xiaomi.com/pass/serviceLogin"})
        if path == "/pass/serviceLogin":
            # passport often puts an anti-hijacking prefix before the JSON
            body = const.XIAOMI_JSON_PREFIX + _json.dumps(SERVICE_LOGIN)
            return httpx.Response(200, text=body)
        if path == "/longPolling/loginUrl":
            return httpx.Response(200, text=const.XIAOMI_JSON_PREFIX + _json.dumps(LONG_POLLING))
        raise AssertionError(path)

    with _qr(handler) as client:
        challenge = client.start()
    assert challenge.login_url == LOGIN_URL


def test_start_missing_login_redirect():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="just a page, no redirect")

    with _qr(handler) as client:
        with pytest.raises(CloudError) as excinfo:
            client.start()
    assert "login page" in str(excinfo.value)


def test_start_missing_sign_field():
    incomplete = {k: v for k, v in SERVICE_LOGIN.items() if k != "_sign"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/authorize":
            return httpx.Response(302, headers={"location": "https://account.xiaomi.com/pass/serviceLogin"})
        if request.url.path == "/pass/serviceLogin":
            return httpx.Response(200, json=incomplete)
        raise AssertionError(request.url.path)

    with _qr(handler) as client:
        with pytest.raises(CloudError) as excinfo:
            client.start()
    assert "_sign" in str(excinfo.value)


def _challenge() -> QrChallenge:
    return QrChallenge(
        login_url=LOGIN_URL, lp_url=LP_URL, qr_image_url="", timeout=300
    )


def test_poll_returns_location_on_confirm():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "location": STS_LOCATION})

    with _qr(handler) as client:
        location = client.poll(_challenge(), deadline=_deadline(), poll_interval=0)
    assert location == STS_LOCATION


def test_poll_waits_through_intermediate_state():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            # scanned but not confirmed: code=0 but no location yet
            return httpx.Response(200, json={"code": 0, "result": "ok"})
        return httpx.Response(200, json={"code": 0, "location": STS_LOCATION})

    with _qr(handler) as client:
        location = client.poll(_challenge(), deadline=_deadline(), poll_interval=0)
    assert location == STS_LOCATION
    assert calls["n"] == 2


def test_poll_reports_error_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 70003, "desc": "QR code expired"})

    with _qr(handler) as client:
        with pytest.raises(CloudError) as excinfo:
            client.poll(_challenge(), deadline=_deadline(), poll_interval=0)
    assert "QR code expired" in str(excinfo.value)


def test_poll_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        # stays in the intermediate state until the deadline
        return httpx.Response(200, json={"code": 0})

    with _qr(handler) as client:
        with pytest.raises(MiCliError) as excinfo:
            # the deadline has already passed, so poll times out as soon as it starts
            client.poll(_challenge(), deadline=0.0, poll_interval=0)
    assert "timed out" in str(excinfo.value)


def test_resolve_code_follows_chain_to_redirect():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "account.xiaomi.com" and request.url.path == "/sts":
            return httpx.Response(302, headers={"location": AUTHORIZE_BACK})
        if request.url.path == "/oauth2/authorize":
            return httpx.Response(302, headers={"location": FINAL_REDIRECT})
        raise AssertionError(f"must not request {request.url}")

    with _qr(handler) as client:
        result = client.resolve_code(STS_LOCATION)
    assert result.code == "THE-CODE"
    assert result.state == STATE


def test_resolve_code_does_not_request_redirect_host():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.path == "/sts":
            return httpx.Response(302, headers={"location": FINAL_REDIRECT})
        raise AssertionError(f"must not request {request.url}")

    with _qr(handler) as client:
        client.resolve_code(STS_LOCATION)
    # the homeassistant.local hop is only parsed, not actually requested
    assert const.REDIRECT_HOST not in seen


def test_resolve_code_rejects_state_mismatch():
    bad = f"{REDIRECT}?code=X&state=WRONG"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sts":
            return httpx.Response(302, headers={"location": bad})
        raise AssertionError(request.url)

    with _qr(handler) as client:
        with pytest.raises(MiCliError) as excinfo:
            client.resolve_code(STS_LOCATION)
    assert "state" in str(excinfo.value)


def test_resolve_code_dead_ends_without_code():
    def handler(request: httpx.Request) -> httpx.Response:
        # stops at a page that does not redirect any further (e.g. a consent page that
        # needs confirming on the phone)
        return httpx.Response(200, text="<html>consent</html>")

    with _qr(handler) as client:
        with pytest.raises(CloudError) as excinfo:
            client.resolve_code(STS_LOCATION)
    assert "phone" in str(excinfo.value)


def test_network_error_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with _qr(handler) as client:
        with pytest.raises(NetworkError):
            client.start()


def test_render_qr_returns_scannable_block():
    out = render_qr("https://example.com/scan")
    # segno is a dependency, so drawing should work
    assert out is not None
    # upper half block ▀, foreground = upper module / background = lower module,
    # explicit black and white (no inversion)
    assert "▀" in out
    # dark modules use black (30/40), light modules white (37/47); all four combinations
    # can occur
    assert "\x1b[30;40m" in out or "\x1b[30;47m" in out
    assert "\x1b[37;47m" in out or "\x1b[37;40m" in out
    # half blocks halve the height: visible module columns per line ≈ lines * 2 (a QR
    # code is a square matrix)
    import re

    lines = out.splitlines()
    cols = {len(re.sub(r"\x1b\[[0-9;]*m", "", ln)) for ln in lines}
    assert len(cols) == 1  # every line has the same width
    width = cols.pop()
    assert abs(width - len(lines) * 2) <= 2


def test_render_qr_returns_none_when_too_wide(monkeypatch):
    import os

    # the terminal has only 10 columns, so the QR code is bound to be too wide → better
    # not to draw (it would wrap, break and not scan)
    monkeypatch.setattr(
        "shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((10, 24))
    )
    assert render_qr("https://example.com/some/long/enough/scan/url") is None


def test_render_qr_ok_when_wide_enough(monkeypatch):
    import os

    monkeypatch.setattr(
        "shutil.get_terminal_size", lambda fallback=(80, 24): os.terminal_size((200, 50))
    )
    assert render_qr("https://example.com/scan") is not None


def _deadline() -> float:
    import time

    return time.monotonic() + 30
