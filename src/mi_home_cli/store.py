"""Local storage of configuration and credentials.

For the directory layout see docs/design.md §3.1. Files containing secrets are
always 0600 and directories 0700.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core import const
from .core.const import DEFAULT_REGION, TOKEN_REFRESH_RATIO
from .errors import MiCliError, NotAuthenticated

ENV_CONFIG_DIR = "MI_HOME_CONFIG_DIR"
APP_DIR_NAME = "mi-home-cli"


def config_dir() -> Path:
    """The config root directory; can be overridden with MI_HOME_CONFIG_DIR."""
    override = os.environ.get(ENV_CONFIG_DIR)
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base).expanduser() / APP_DIR_NAME
    return Path.home() / ".config" / APP_DIR_NAME


def _write_private_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Create the file with 0600 before writing, so its content is never briefly
    # readable.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError) as err:
        raise MiCliError(f"Failed to read {path}: {err}") from err


def file_is_private(path: Path) -> bool:
    """Whether only the owner can read and write the file."""
    if not path.exists():
        return True
    mode = path.stat().st_mode
    return not mode & (stat.S_IRWXG | stat.S_IRWXO)


@dataclass
class AuthData:
    """The login state of one profile."""

    access_token: str
    refresh_token: str
    region: str
    device_id: str
    obtained_at: int
    expires_in: int
    uid: str | None = None
    nickname: str | None = None

    @property
    def expires_at(self) -> int:
        return self.obtained_at + self.expires_in

    @property
    def refresh_at(self) -> int:
        """From this point in time on it should be refreshed."""
        return self.obtained_at + int(self.expires_in * TOKEN_REFRESH_RATIO)

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def needs_refresh(self) -> bool:
        return time.time() >= self.refresh_at

    def dump(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "region": self.region,
            "device_id": self.device_id,
            "obtained_at": self.obtained_at,
            "expires_in": self.expires_in,
            "uid": self.uid,
            "nickname": self.nickname,
        }

    @staticmethod
    def load(data: dict[str, Any]) -> "AuthData":
        try:
            return AuthData(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                region=data.get("region", DEFAULT_REGION),
                device_id=data.get("device_id", ""),
                obtained_at=int(data.get("obtained_at", 0)),
                expires_in=int(data.get("expires_in", 0)),
                uid=data.get("uid"),
                nickname=data.get("nickname"),
            )
        except KeyError as err:
            raise NotAuthenticated(f"The login data is incomplete: missing {err}") from err


@dataclass
class Identity:
    """The three values that must stay consistent throughout one login.

    Whatever is used for authorization must be used for the token exchange; the server
    compares them, and a mismatch returns 96002 invalid request.
    """

    install_id: str
    webhook_id: str
    device_id: str
    redirect_url: str


@dataclass
class Profile:
    """One account/region configuration."""

    name: str
    root: Path = field(default_factory=config_dir)

    @property
    def path(self) -> Path:
        return self.root / "profiles" / self.name

    @property
    def auth_path(self) -> Path:
        return self.path / "auth.json"

    @property
    def devices_path(self) -> Path:
        return self.path / "devices.json"

    @property
    def spec_dir(self) -> Path:
        return self.path / "spec"

    @property
    def aliases_path(self) -> Path:
        return self.path / "aliases.json"

    def write_devices(self, data: dict[str, Any]) -> None:
        # The device list contains LAN tokens; treat it like credentials
        _write_private_json(self.devices_path, data)

    @property
    def lan_path(self) -> Path:
        return self.path / "lan.json"

    def read_lan(self) -> dict[str, Any]:
        return _read_json(self.lan_path) or {}

    def write_lan(self, data: dict[str, Any]) -> None:
        _write_private_json(self.lan_path, data)

    def read_aliases(self) -> dict[str, str]:
        return _read_json(self.aliases_path) or {}

    def write_aliases(self, aliases: dict[str, str]) -> None:
        _write_private_json(self.aliases_path, aliases)

    def exists(self) -> bool:
        return self.auth_path.exists()

    def read_auth(self) -> AuthData | None:
        data = _read_json(self.auth_path)
        if data is None:
            return None
        return AuthData.load(data)

    def require_auth(self) -> AuthData:
        auth = self.read_auth()
        if auth is None:
            raise NotAuthenticated(f"Profile `{self.name}` is not logged in")
        return auth

    def write_auth(self, auth: AuthData) -> None:
        _write_private_json(self.auth_path, auth.dump())

    def clear_auth(self) -> None:
        self.auth_path.unlink(missing_ok=True)

    def purge(self) -> None:
        import shutil

        if self.path.exists():
            shutil.rmtree(self.path)

    @property
    def identity_path(self) -> Path:
        return self.path / "identity.json"

    @property
    def pending_path(self) -> Path:
        return self.path / "pending.json"

    def identity(self, region: str) -> "Identity":
        """This machine's identity towards Xiaomi's OAuth, generated on first use and then fixed.

        The shape is copied from the Home Assistant Xiaomi Home integration: webhook_id is
        a random 64-bit integer and device_id is `ha.` plus 32 hex chars. Changing the
        device_id does not affect whether login works, but it leaves one more device record
        on Xiaomi's side, so it is persisted.
        """
        data = _read_json(self.identity_path) or {}
        install_id = data.get("install_id") or uuid.uuid4().hex
        webhook_id = data.get("webhook_id") or str(secrets.randbits(64))
        if data.get("install_id") != install_id or data.get(
            "webhook_id"
        ) != webhook_id:
            _write_private_json(
                self.identity_path,
                {"install_id": install_id, "webhook_id": webhook_id},
            )
        digest = hashlib.sha256(
            f"{install_id}.{webhook_id}.{region}".encode("utf-8")
        ).hexdigest()[:32]
        return Identity(
            install_id=install_id,
            webhook_id=webhook_id,
            device_id=f"{const.DEVICE_ID_PREFIX}{digest}",
            redirect_url=const.redirect_url(webhook_id),
        )

    def write_pending(self, data: dict[str, Any]) -> None:
        """Remember the parameters of this login, so `mi auth exchange` can retry with the same ones."""
        _write_private_json(self.pending_path, data)

    def read_pending(self) -> dict[str, Any] | None:
        return _read_json(self.pending_path)

    def clear_pending(self) -> None:
        self.pending_path.unlink(missing_ok=True)

    @property
    def scan_device_path(self) -> Path:
        return self.path / "scan_device.json"

    def web_device_id(self) -> str:
        """The stable web `deviceId` reused by QR-code login; generated once and then fixed.

        On first access the Xiaomi account login page issues a random `deviceId` and
        registers a web device under "logged-in devices" according to it (shown as Chrome,
        based on the browser UA). A new `deviceId` on every scan would keep adding more;
        keeping it fixed and sending it every time makes Xiaomi treat it as the same device
        and add no new one.
        """
        data = _read_json(self.scan_device_path) or {}
        device = data.get("device_id")
        if not device:
            device = f"wb_{uuid.uuid4()}"
            _write_private_json(self.scan_device_path, {"device_id": device})
        return device


def list_profiles(root: Path | None = None) -> list[str]:
    base = (root or config_dir()) / "profiles"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def read_config(root: Path | None = None) -> dict[str, Any]:
    return _read_json((root or config_dir()) / "config.json") or {}


def write_config(data: dict[str, Any], root: Path | None = None) -> None:
    _write_private_json((root or config_dir()) / "config.json", data)
