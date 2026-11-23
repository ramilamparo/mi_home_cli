"""Control channels: cloud / LAN / auto.

Commands above do not care which path is taken; they only call
get_props / set_props / call_action.
"""
from __future__ import annotations

import time
from typing import Any, Protocol

from ..errors import DeviceOffline, MiCliError
from ..store import Profile
from .cloud import CloudApi
from .lan import Endpoint, LanDevice, discover, ping
from .registry import Device
from .session import Session

# Only devices connected directly to the router can use the LAN; those joining
# through a gateway (Bluetooth Mesh / ZigBee) cannot. The values come from
# upstream's handling of connect_type (the cloud's pid field).
LAN_CAPABLE_TYPES = frozenset({0, 8, 12, 23})
# For how long a cached IP is tried directly; beyond that it counts as stale (the device
# may have changed IP)
LAN_CACHE_TTL = 24 * 3600
# When a device cannot do the job over the LAN (e.g. old firmware that does not
# know get_properties), remember it; for this long auto mode goes straight to
# the cloud and does not waste an attempt on every command. A firmware upgrade
# may add support, so the mark expires; `mi lan discover` clears it as well.
LAN_FAILURE_TTL = 7 * 24 * 3600


class DeviceChannel(Protocol):
    name: str

    def get_props(self, params: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def set_props(self, params: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def call_action(
        self, did: str, siid: int, aiid: int, values: list[Any]
    ) -> dict[str, Any]: ...


class CloudChannel:
    """Through the Mi Home cloud."""

    name = "cloud"

    def __init__(self, api: CloudApi) -> None:
        self._api = api

    def get_props(self, params: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._api.get_props(params)

    def set_props(self, params: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._api.set_props(params)

    def call_action(
        self, did: str, siid: int, aiid: int, values: list[Any]
    ) -> dict[str, Any]:
        return self._api.call_action(did, siid, aiid, values)


class AutoChannel:
    """LAN first, falling back to the cloud on failure.

    "The device can be found" is not the same as "the device is willing to work over
    the LAN" — in testing some devices handshake fine yet answer get_properties with
    user ack timeout. So the fallback has to happen on every call; falling back only at
    the locating stage is not enough.
    """

    name = "auto"

    def __init__(
        self,
        lan: "LanChannel",
        cloud: CloudChannel,
        on_note: Any = None,
        on_failure: Any = None,
    ) -> None:
        self._lan: LanChannel | None = lan
        self._cloud = cloud
        self._on_note = on_note
        self._on_failure = on_failure

    def _run(self, action: str, call):
        if self._lan is not None:
            try:
                return call(self._lan)
            except MiCliError as err:
                # Do not try the LAN again for this device in this run, and record it in
                # the cache so later commands do not try in vain either
                self._lan = None
                if self._on_failure:
                    self._on_failure(err.message)
                if self._on_note:
                    self._on_note(
                        f"[dim]LAN {action} failed ({err.message}), falling back to "
                        "the cloud[/dim]"
                    )
        return call(self._cloud)

    def get_props(self, params: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._run("read", lambda channel: channel.get_props(params))

    def set_props(self, params: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._run("write", lambda channel: channel.set_props(params))

    def call_action(
        self, did: str, siid: int, aiid: int, values: list[Any]
    ) -> dict[str, Any]:
        return self._run(
            "action call", lambda channel: channel.call_action(did, siid, aiid, values)
        )


class LanChannel:
    """Directly to the device."""

    name = "lan"

    def __init__(self, device: LanDevice) -> None:
        self._device = device

    @property
    def endpoint(self) -> Endpoint:
        return self._device.endpoint

    def get_props(self, params: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._device.get_props(params)

    def set_props(self, params: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._device.set_props(params)

    def call_action(
        self, did: str, siid: int, aiid: int, values: list[Any]
    ) -> dict[str, Any]:
        return self._device.call_action(did, siid, aiid, values)


def record_lan_failure(profile: Profile, did: str, reason: str) -> None:
    cache = profile.read_lan()
    entry = cache.setdefault(did, {})
    entry["failed_at"] = int(time.time())
    entry["reason"] = reason
    profile.write_lan(cache)


def lan_failure(profile: Profile, did: str) -> tuple[int, str] | None:
    """Time and reason of this device's most recent failed LAN call; None if there is none or it has expired."""
    entry = profile.read_lan().get(did) or {}
    failed_at = entry.get("failed_at")
    if not failed_at or time.time() - failed_at > LAN_FAILURE_TTL:
        return None
    return int(failed_at), str(entry.get("reason", ""))


def clear_lan_failures(profile: Profile) -> None:
    cache = profile.read_lan()
    for entry in cache.values():
        entry.pop("failed_at", None)
        entry.pop("reason", None)
    profile.write_lan(cache)


def lan_capable(device: Device) -> bool:
    return bool(device.token) and device.connect_type in LAN_CAPABLE_TYPES


def locate(
    profile: Profile, device: Device, *, rediscover: bool = True
) -> Endpoint | None:
    """Find the device's address on the LAN.

    Try the cached IP first (one unicast hello, tens of milliseconds); if that fails,
    do a broadcast scan.
    """
    cache = profile.read_lan()
    entry = cache.get(device.did)
    if entry and time.time() - entry.get("seen_at", 0) < LAN_CACHE_TTL:
        endpoint = ping(entry["ip"])
        if endpoint and endpoint.did == device.did:
            return endpoint
    if not rediscover:
        return None
    found = discover()
    if found:
        cache.update(
            {
                did: {"ip": item.ip, "seen_at": int(time.time())}
                for did, item in found.items()
            }
        )
        profile.write_lan(cache)
    return found.get(device.did)


def open_device_channel(
    session: Session,
    profile: Profile,
    device: Device,
    *,
    mode: str = "cloud",
    on_note: Any = None,
) -> DeviceChannel:
    """Pick a channel according to --channel.

    auto: go direct when possible and silently fall back to the cloud whenever any step
    does not hold — falling back is the norm and should not be noisy.
    lan: LAN only; when it does not work, raise an error that says clearly why.
    """
    cloud = CloudChannel(CloudApi(session))
    if mode == "cloud":
        return cloud

    if not lan_capable(device):
        reason = (
            "no LAN token"
            if not device.token
            else f"connect_type={device.connect_type}: the device is not connected to "
                 "the router directly (Bluetooth Mesh / ZigBee go through a gateway)"
        )
        if mode == "lan":
            raise MiCliError(f"{device.label} cannot be controlled over the LAN: "
                             f"{reason}")
        return cloud

    failure = lan_failure(profile, device.did)
    if failure and mode == "auto":
        # Tried before and this device cannot do the job over the LAN; do not waste
        # another round trip
        if on_note:
            on_note(f"[dim]Skipping the LAN (last failure: {failure[1]}), using the "
                    "cloud[/dim]")
        return cloud

    endpoint = locate(profile, device)
    if endpoint is None:
        if mode == "lan":
            raise DeviceOffline(
                f"Not found on the LAN: {device.label}",
                hint="Make sure you are on the same subnet and the device is online; "
                     "`mi lan discover` shows what can be found",
            )
        return cloud

    if on_note:
        on_note(f"[dim]Direct LAN {endpoint.ip} ({endpoint.elapsed_ms:.0f}ms)[/dim]")
    lan = LanChannel(LanDevice(device.did, device.token or "", endpoint))
    if mode == "lan":
        return lan
    return AutoChannel(
        lan,
        cloud,
        on_note=on_note,
        on_failure=lambda reason: record_lan_failure(profile, device.did, reason),
    )
