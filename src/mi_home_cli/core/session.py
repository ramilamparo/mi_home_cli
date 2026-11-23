"""A session with login state: automatic token renewal + authenticated API calls."""
from __future__ import annotations

from typing import Any

import httpx

from ..errors import CloudError, NetworkError, NotAuthenticated
from ..store import AuthData, Profile
from . import const
from .oauth import OAuthClient


class Session:
    """The runtime session of one profile.

    The token is only refreshed when needed; a successful refresh is persisted
    immediately, so the next run does not refresh again.
    """

    def __init__(
        self,
        profile: Profile,
        *,
        region: str | None = None,
        timeout: float = const.HTTP_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self.profile = profile
        self._auth: AuthData | None = None
        self._region_override = region
        self._timeout = timeout
        self._client = client or httpx.Client(
            timeout=timeout, headers={"User-Agent": const.USER_AGENT}
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def auth(self) -> AuthData:
        if self._auth is None:
            self._auth = self.profile.require_auth()
        return self._auth

    @property
    def region(self) -> str:
        return self._region_override or self.auth.region

    def refresh_token(self, *, force: bool = False) -> AuthData:
        """Refresh the access_token when needed (or when forced)."""
        auth = self.auth
        if not force and not auth.needs_refresh:
            return auth
        with OAuthClient(
            auth.region,
            redirect_url=self.profile.identity(auth.region).redirect_url,
            timeout=self._timeout,
            client=self._client,
        ) as client:
            token = client.refresh(auth.refresh_token)
        refreshed = token.to_auth(
            auth.region, auth.device_id, uid=auth.uid, nickname=auth.nickname
        )
        self.profile.write_auth(refreshed)
        self._auth = refreshed
        return refreshed

    def access_token(self) -> str:
        auth = self.auth
        if auth.expired and not auth.refresh_token:
            raise NotAuthenticated("The access_token has expired and there is no "
                                   "refresh_token")
        if auth.needs_refresh:
            auth = self.refresh_token()
        return auth.access_token

    @property
    def _headers(self) -> dict[str, str]:
        # Note there is no space after Bearer: that is how this Mi Home API validates
        # it, and adding a space gives 401.
        return {
            "Host": const.api_host(self.region),
            "X-Client-BizId": "haapi",
            "X-Client-AppId": const.CLIENT_ID,
            "Content-Type": "application/json",
            "Authorization": f"Bearer{self.access_token()}",
            "User-Agent": const.USER_AGENT,
        }

    def _request(
        self, method: str, path: str, *, params: dict | None = None,
        json_body: dict | None = None, retry_on_401: bool = True,
    ) -> dict[str, Any]:
        url = f"{const.api_base_url(self.region)}{path}"
        try:
            response = self._client.request(
                method, url, params=params, json=json_body, headers=self._headers
            )
        except httpx.HTTPError as err:
            raise NetworkError(f"Request to {path} failed: {err}") from err
        if response.status_code == 401 and retry_on_401:
            # The token may have been revoked early on the server side; force one
            # refresh and retry.
            self.refresh_token(force=True)
            return self._request(
                method, path, params=params, json_body=json_body,
                retry_on_401=False,
            )
        if response.status_code == 401:
            raise NotAuthenticated("The cloud returned 401; the login is no longer "
                                   "valid")
        if response.status_code != 200:
            raise CloudError(
                f"{path} returned HTTP {response.status_code}",
                code=response.status_code,
            )
        try:
            res_obj = response.json()
        except ValueError as err:
            raise CloudError(f"{path} response is not valid JSON") from err
        if res_obj.get("code") != 0:
            raise CloudError(
                f"{path} returned code={res_obj.get('code')}: "
                f"{res_obj.get('message') or ''}",
                code=res_obj.get("code"),
            )
        return res_obj

    def api_get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def api_post(self, path: str, data: dict | None = None) -> dict[str, Any]:
        return self._request("POST", path, json_body=data)

    def user_profile(self) -> dict[str, Any]:
        with OAuthClient(
            self.region,
            redirect_url=self.profile.identity(self.region).redirect_url,
            timeout=self._timeout,
            client=self._client,
        ) as client:
            return client.user_profile(self.access_token())
