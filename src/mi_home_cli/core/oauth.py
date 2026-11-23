"""The Xiaomi account OAuth2 authorization code flow.

Flow:
  1. open account.xiaomi.com/oauth2/authorize (with redirect_uri / client_id /
     device_id / state); the user logs in and authorizes in the browser;
  2. the browser is redirected to redirect_uri?code=...&state=...;
  3. take the code to {api_host}/app/v2/ha/oauth/get_token and exchange it for an
     access_token;
  4. before it expires, renew through the same endpoint with the refresh_token.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from ..errors import CloudError, NetworkError
from ..store import AuthData
from . import const


@dataclass
class TokenResult:
    access_token: str
    refresh_token: str
    expires_in: int
    obtained_at: int

    def to_auth(
        self, region: str, device_id: str, *, uid: str | None = None,
        nickname: str | None = None,
    ) -> AuthData:
        return AuthData(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            region=region,
            device_id=device_id,
            obtained_at=self.obtained_at,
            expires_in=self.expires_in,
            uid=uid,
            nickname=nickname,
        )


def new_state() -> str:
    return secrets.token_hex(16)


def state_for_device(device_id: str) -> str:
    """Generate state with the algorithm of the Home Assistant Xiaomi Home integration.

    state itself is only used to check that a callback belongs to this login; Xiaomi
    does not ask for it again at token exchange. The same algorithm is kept purely to
    take the variable "differs from HA" out of troubleshooting.
    """
    return hashlib.sha1(f"d={device_id}".encode("utf-8")).hexdigest()


def build_auth_url(
    *,
    redirect_url: str,
    device_id: str,
    state: str,
    scope: list[str] | None = None,
    skip_confirm: bool = False,
) -> str:
    """Build the authorization page URL.

    skip_confirm=False means the consent page is shown every time, which is safer for a
    CLI (the user can see what is being authorized) at the cost of one more click.
    """
    params: dict[str, Any] = {
        "redirect_uri": redirect_url,
        "client_id": const.CLIENT_ID,
        "response_type": "code",
        "device_id": device_id,
        "state": state,
        "skip_confirm": "true" if skip_confirm else "false",
    }
    if scope:
        params["scope"] = " ".join(scope)
    return f"{const.OAUTH_AUTH_URL}?{urlencode(params)}"


def _unwrap_error(res_obj: dict[str, Any]) -> CloudError:
    """Turn Xiaomi's nested error structure into one plain sentence.

    Shaped like: {"code":-6,"message":"{\"error\":96013,
                  \"error_description\":\"invalid authorization code\"}"}
    """
    code = res_obj.get("code")
    detail: dict[str, Any] = {}
    result = res_obj.get("result")
    if isinstance(result, dict):
        detail = result
    else:
        message = res_obj.get("message")
        if isinstance(message, str):
            try:
                parsed = json.loads(message)
                if isinstance(parsed, dict):
                    detail = parsed
            except json.JSONDecodeError:
                pass
    description = detail.get("error_description") or res_obj.get("message")
    inner = detail.get("error")
    hint = None
    if inner == 96013:
        hint = "The authorization code is invalid or already used; run `mi auth login` again"
    elif inner == 96002:
        hint = (
            "The token exchange parameters differ from the ones used to authorize "
            "(redirect_uri / client_id / device_id must all be identical); use -v to "
            "see the request actually sent"
        )
    elif code == 401 or inner == 401:
        hint = "The credentials are no longer valid; run `mi auth login` again"
    text = f"Failed to get a token (code={code}"
    if inner is not None:
        text += f", error={inner}"
    text += f"): {description}"
    return CloudError(text, code=code, description=str(description), hint=hint)


class OAuthClient:
    """Obtaining and refreshing tokens."""

    def __init__(
        self,
        region: str = const.DEFAULT_REGION,
        *,
        redirect_url: str,
        timeout: float = const.HTTP_TIMEOUT,
        client: httpx.Client | None = None,
        trace: Callable[[str], None] | None = None,
    ) -> None:
        self.region = region
        self.redirect_url = redirect_url
        self._timeout = timeout
        self._trace = trace
        self._client = client or httpx.Client(
            timeout=timeout, headers={"User-Agent": const.USER_AGENT}
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "OAuthClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get_token(self, data: dict[str, Any]) -> TokenResult:
        url = f"{const.api_base_url(self.region)}/app/v2/ha/oauth/get_token"
        payload = json.dumps(data)
        if self._trace:
            self._trace(f"GET {url}?data={payload}")
        try:
            response = self._client.get(
                url,
                params={"data": payload},
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as err:
            raise NetworkError(f"Connecting to {url} failed: {err}") from err
        if response.status_code == 401:
            raise CloudError(
                "Failed to get a token: unauthorized (401)",
                code=401,
                hint="Run `mi auth login` again",
            )
        if response.status_code != 200:
            raise CloudError(
                f"Failed to get a token: HTTP {response.status_code}",
                code=response.status_code,
            )
        if self._trace:
            self._trace(f"<- HTTP {response.status_code} {response.text[:500]}")
        try:
            res_obj = response.json()
        except ValueError as err:
            raise CloudError(f"The response is not valid JSON: {response.text[:200]}") from err
        if res_obj.get("code") != 0 or "result" not in res_obj:
            raise _unwrap_error(res_obj)
        result = res_obj["result"]
        missing = [
            key
            for key in ("access_token", "refresh_token", "expires_in")
            if key not in result
        ]
        if missing:
            raise CloudError(f"The response is missing fields: {', '.join(missing)}")
        return TokenResult(
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
            expires_in=int(result["expires_in"]),
            obtained_at=int(time.time()),
        )

    def exchange_code(self, code: str, device_id: str) -> TokenResult:
        return self._get_token(
            {
                "client_id": int(const.CLIENT_ID),
                "redirect_uri": self.redirect_url,
                "code": code,
                "device_id": device_id,
            }
        )

    def refresh(self, refresh_token: str) -> TokenResult:
        return self._get_token(
            {
                "client_id": int(const.CLIENT_ID),
                "redirect_uri": self.redirect_url,
                "refresh_token": refresh_token,
            }
        )

    def user_profile(self, access_token: str) -> dict[str, Any]:
        """Basic info such as the account nickname, used by `mi auth whoami`."""
        try:
            response = self._client.get(
                const.USER_PROFILE_URL,
                params={"clientId": const.CLIENT_ID, "token": access_token},
            )
        except httpx.HTTPError as err:
            raise NetworkError(f"Failed to get account info: {err}") from err
        try:
            res_obj = response.json()
        except ValueError as err:
            raise CloudError("The account info response is not valid JSON") from err
        if res_obj.get("code") != 0 or "data" not in res_obj:
            raise CloudError(
                f"Failed to get account info: {res_obj.get('description') or res_obj}",
                code=res_obj.get("code"),
            )
        return res_obj["data"]
