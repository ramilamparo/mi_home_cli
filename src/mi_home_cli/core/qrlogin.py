"""Xiaomi account QR-code login (QR scan login).

**No headless browser is introduced**; the whole flow of "a browser opens the
authorization page and is redirected to the login page" is reproduced with plain API
calls, ending up with exactly the same authorization `code` as a browser login,
which is then handed to the existing `OAuthClient.exchange_code` for the token
exchange — scanning is just another way of "getting the code", and the second half
is identical to `mi auth login`.

The redirect chain (found by analysing the authorization page's redirects):

  1. GET `oauth2/authorize` (`skip_confirm=true`) → 302 to `pass/serviceLogin`;
  2. GET `serviceLogin?_json=true` → get `_sign` / `sid` / `qs` / `callback` /
     `serviceParam` (when not logged in the response has `code=70016`, "login
     verification failed", which is the normal state);
  3. GET `longPolling/loginUrl` (with the parameters of the previous step) → get
     `loginUrl` (the address encoded into the QR code for the user to scan), `lp`
     (the long-polling address) and `qr` (a server-rendered QR code image, as a
     fallback);
  4. render `loginUrl` as a QR code in the terminal; the user scans it with a Xiaomi
     app ("Profile → Scan") and confirms the login on the phone;
  5. long-poll `lp`, which hangs until the phone confirms and then returns a
     `location`;
  6. follow the redirect chain of `location` carrying the cookies collected along
     the way; on reaching `redirect_uri` (that `homeassistant.local` is most likely
     unreachable, so it is only parsed, not actually requested) take `code` and
     `state` from the query;
  7. hand `code` to `OAuthClient.exchange_code`.

Cookies are kept by one and the same `httpx.Client` throughout (cookies such as
`deviceId` are set in step 2 and must be carried in every later step).
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from ..errors import CloudError, MiCliError, NetworkError
from .callback import CallbackResult, parse_pasted
from .oauth import build_auth_url
from . import const

# How long a single long-polling request may hang; when it runs out without a result it
# is re-sent (the overall limit is controlled by deadline).
_LP_POLL_TIMEOUT = 30.0
# Maximum number of hops followed in the redirect chain, to avoid spinning in abnormal
# cases.
_MAX_REDIRECTS = 10
# The code serviceLogin returns when not logged in; a normal state, not an error.
_NOT_LOGGED_IN = 70016


@dataclass
class QrChallenge:
    """The "waiting to be scanned" state of one QR-code login."""

    login_url: str  # the address encoded into the QR code for the user to scan
    lp_url: str  # the long-polling address
    qr_image_url: str  # URL of the server-rendered QR code image (fallback when segno is missing)
    timeout: int  # QR code validity given by the server (seconds)


def _strip_prefix(text: str) -> str:
    text = text.lstrip()
    if text.startswith(const.XIAOMI_JSON_PREFIX):
        text = text[len(const.XIAOMI_JSON_PREFIX):]
    return text


def render_qr(data: str) -> str | None:
    """Render content as a terminal QR code string.

    Each character cell stacks two vertical modules using the upper half block `▀`
    (halving the height and making the whole thing compact enough to fit on one screen,
    which is crucial for being scannable): **the upper module is drawn in the foreground
    colour and the lower module is left to the background colour**. The lower half is
    filled by the background colour, which also covers the line-spacing gap — so even in
    terminals with a line-height no stripes open up between half blocks (the old
    approach used the three glyphs `█▀▄` and frayed as soon as line spacing grew).
    Foreground/background are given explicitly as black and white, so neither dark nor
    light themes invert it. 0 = light (white), 1 = dark (black).

    It is still limited by the aspect ratio of terminal character cells: in most
    terminals "height ≈ 2 × width", which makes modules nearly square; with the odd font
    or renderer that is close to square, modules come out flattened, but filled as solid
    blocks by the background colour they are at least clean and scannable.

    When the content is so long that the QR code is wider than the terminal's columns,
    None is returned — better not to draw at all than to let it wrap and break (a broken
    QR code cannot be scanned at all); the caller falls back to giving the link. `segno`
    is a direct dependency and can normally always be imported; if the environment has
    stripped it, None is returned as well.
    """
    try:
        import segno
    except ImportError:
        return None

    # error='m': about 15% error correction, so the QR code still scans when the
    # terminal font stretches it slightly.
    matrix = [list(row) for row in segno.make(data, error="m").matrix_iter(
        scale=1, border=4
    )]
    # Each module takes 1 column; wider than the terminal it would wrap and break, so
    # give up and let the caller give the link.
    columns = shutil.get_terminal_size((80, 24)).columns
    if len(matrix[0]) > columns:
        return None
    if len(matrix) % 2:  # pad with one all-light row so rows pair up
        matrix.append([0] * len(matrix[0]))

    reset = "\x1b[0m"
    lines = []
    for top, bottom in zip(matrix[0::2], matrix[1::2]):
        parts: list[str] = []
        prev = None
        for t, b in zip(top, bottom):
            # foreground = upper module, background = lower module; dark = black
            # (30/40), light = white (37/47).
            color = f"\x1b[{'30' if t else '37'};{'40' if b else '47'}m"
            if color != prev:
                parts.append(color)
                prev = color
            parts.append("▀")  # ▀ upper half block
        lines.append("".join(parts) + reset)
    return "\n".join(lines)


class QrLoginClient:
    """The three steps of QR-code login: `start` (get the QR code) → `poll` (wait for confirmation) → `resolve_code`.

    The HTTP client can be injected, which makes offline testing easy; when none is
    injected, a client with cookies is created.
    """

    def __init__(
        self,
        *,
        redirect_url: str,
        device_id: str,
        state: str,
        web_device_id: str | None = None,
        user_agent: str | None = None,
        timeout: float = const.HTTP_TIMEOUT,
        client: httpx.Client | None = None,
        trace: Callable[[str], None] | None = None,
    ) -> None:
        self.redirect_url = redirect_url
        self.device_id = device_id
        self.state = state
        self._trace = trace
        # The name shown under Xiaomi's "logged-in devices" is parsed from this User-
        # Agent and can be customised.
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": user_agent or const.WEB_USER_AGENT},
        )
        self._owns_client = client is None
        if web_device_id:
            # Preset a stable web deviceId; the server reuses it as is (in testing
            # Set-Cookie echoes the same value), so every scan is the same device under
            # Xiaomi's "logged-in devices" and the list does not keep growing.
            self._client.cookies.set(
                "deviceId", web_device_id, domain=const.ACCOUNT_HOST, path="/"
            )
            self._client.cookies.set(
                "pass_ua", "web", domain=const.ACCOUNT_HOST, path="/"
            )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "QrLoginClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, url: str, *, timeout: float | None = None) -> httpx.Response:
        if self._trace:
            self._trace(f"GET {url}")
        try:
            if timeout is None:
                response = self._client.get(url)
            else:
                response = self._client.get(url, timeout=timeout)
        except httpx.HTTPError as err:
            raise NetworkError(f"Connecting to {urlparse(url).netloc} failed: {err}") from err
        if self._trace:
            self._trace(f"<- HTTP {response.status_code}")
        return response

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            obj = json.loads(_strip_prefix(response.text))
        except ValueError as err:
            raise CloudError(
                f"The account API response is not valid JSON: {response.text[:200]}"
            ) from err
        if not isinstance(obj, dict):
            raise CloudError("The account API returned an unexpected structure")
        return obj

    def start(self, *, skip_confirm: bool = True) -> QrChallenge:
        """Go through authorize → serviceLogin → longPolling and get the QR code and the long-polling address."""
        authorize = build_auth_url(
            redirect_url=self.redirect_url,
            device_id=self.device_id,
            state=self.state,
            skip_confirm=skip_confirm,
        )
        login_page = self._get(authorize).headers.get("location")
        if not login_page:
            raise CloudError(
                "The authorization page did not redirect to the login page",
                hint="Xiaomi may have changed the login flow; use `mi auth login` "
                     "(browser / paste) instead",
            )

        sep = "&" if "?" in login_page else "?"
        service = self._json(self._get(login_page + sep + "_json=true"))
        # code=70016 when not logged in is normal; what this step wants are the login
        # parameters inside, not a login result.
        code = service.get("code")
        if code not in (None, 0, _NOT_LOGGED_IN):
            raise CloudError(
                "Failed to get the login parameters: "
                f"{service.get('description') or service.get('desc') or code}",
                code=code,
            )
        missing = [
            key
            for key in ("_sign", "sid", "qs", "callback", "serviceParam")
            if not service.get(key)
        ]
        if missing:
            raise CloudError(
                f"The login page response is missing fields: {', '.join(missing)}",
                hint="Xiaomi may have changed the login flow; use `mi auth login` "
                     "instead",
            )

        lp_params = {
            "_group": "DEFAULT",
            "_qrsize": "240",
            "qs": service["qs"],
            "bizDeviceType": "",
            "callback": service["callback"],
            "_hasLogo": "false",
            "theme": "",
            "sid": service["sid"],
            "needTheme": "false",
            "showActiveX": "false",
            "serviceParam": service["serviceParam"],
            "_locale": "zh_CN",
            "_sign": service["_sign"],
            "_dc": str(int(time.time() * 1000)),
        }
        obj = self._json(
            self._get(f"{const.LONG_POLLING_URL}?{urlencode(lp_params)}")
        )
        if obj.get("code") != 0 or not obj.get("loginUrl") or not obj.get("lp"):
            raise CloudError(
                "Failed to get the QR code: "
                f"{obj.get('description') or obj.get('desc') or obj.get('code')}",
                code=obj.get("code"),
            )
        return QrChallenge(
            login_url=obj["loginUrl"],
            lp_url=obj["lp"],
            qr_image_url=obj.get("qr", ""),
            timeout=int(obj.get("timeout", 300)),
        )

    def poll(
        self,
        challenge: QrChallenge,
        *,
        deadline: float,
        poll_interval: float = 1.0,
    ) -> str:
        """Long-poll for the phone's confirmation and return the `location` given after it. Raises on timeout.

        `lp` hangs until confirmation or a server-side timeout; when it has hung for our
        per-request limit it is re-sent, until `deadline`. When the phone has scanned but
        not yet confirmed, the server may first return an intermediate response without
        `location`; keep waiting then.
        """
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MiCliError(
                    "QR login timed out (the QR code has expired)",
                    hint="Run `mi auth login --scan` again",
                )
            try:
                response = self._client.get(
                    challenge.lp_url, timeout=min(remaining, _LP_POLL_TIMEOUT)
                )
            except httpx.ReadTimeout:
                continue  # a single request ran out, re-send
            except httpx.HTTPError as err:
                raise NetworkError(f"Long polling failed: {err}") from err

            obj = self._json(response)
            code = obj.get("code")
            location = obj.get("location")
            if code == 0 and location:
                return location
            if code in (0, None, _NOT_LOGGED_IN):
                # An intermediate state such as "scanned but not confirmed"; take a
                # breath and keep waiting (avoids spinning when it returns immediately).
                if poll_interval:
                    time.sleep(poll_interval)
                continue
            raise CloudError(
                f"QR login failed: {obj.get('description') or obj.get('desc') or code}",
                code=code,
            )

    def resolve_code(self, location: str) -> CallbackResult:
        """Follow the redirect chain after confirmation and take `code` / `state` on reaching `redirect_uri`."""
        url = location
        for _ in range(_MAX_REDIRECTS):
            host = urlparse(url).hostname
            if host == const.REDIRECT_HOST:
                # This machine is most likely unreachable; do not actually request it, parse
                # code/state straight from the URL. Reuses the parsing of the paste path
                # (including the state check).
                return parse_pasted(url, expected_state=self.state)
            response = self._get(url)
            nxt = response.headers.get("location")
            if not nxt:
                raise CloudError(
                    "The redirect chain stopped before reaching the callback URL; you "
                    "may need to confirm the authorization on your phone",
                    code=response.status_code,
                    hint="Tap \"Agree / Authorize\" on your phone and retry, or use "
                         "`mi auth login` instead",
                )
            url = urljoin(url, nxt)
        raise CloudError("Too many redirects; could not obtain an authorization code")
