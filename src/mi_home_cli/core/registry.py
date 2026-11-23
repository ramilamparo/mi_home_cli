"""The device list cache, and resolving "a plain phrase → a specific device".

Whether the CLI is pleasant to use depends almost entirely on this: users should
not have to remember dids.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..errors import AmbiguousReference, DeviceNotFound
from ..store import Profile


@dataclass
class Device:
    did: str
    name: str
    model: str
    urn: str
    online: bool
    home_id: str = ""
    home_name: str = ""
    room_id: str = ""
    room_name: str = ""
    token: str | None = None
    local_ip: str | None = None
    connect_type: int = -1
    manufacturer: str = ""
    fw_version: str | None = None
    parent_id: str | None = None
    sub_devices: dict[str, Any] = field(default_factory=dict)
    alias: str | None = None

    @property
    def label(self) -> str:
        return self.alias or self.name

    @property
    def location(self) -> str:
        if self.room_name:
            return f"{self.home_name}/{self.room_name}"
        return self.home_name or "-"

    def summary(self, *, wide: bool = False) -> dict[str, Any]:
        row: dict[str, Any] = {
            "Name": self.label,
            "Home": self.home_name or "-",
            "Room": self.room_name or "-",
            "Model": self.model,
            "Online": "yes" if self.online else "no",
        }
        if wide:
            row.update(
                {
                    "did": self.did,
                    "IP": self.local_ip or "-",
                    "Firmware": self.fw_version or "-",
                }
            )
        return row

    def detail(self) -> dict[str, Any]:
        data = {
            "Name": self.name,
            "Alias": self.alias or "-",
            "did": self.did,
            "Model": self.model,
            "urn": self.urn,
            "Manufacturer": self.manufacturer,
            "Home": self.home_name or "-",
            "Room": self.room_name or "-",
            "Online": "yes" if self.online else "no",
            "LAN IP": self.local_ip or "-",
            "Firmware version": self.fw_version or "-",
        }
        if self.sub_devices:
            data["Sub-device"] = ", ".join(self.sub_devices)
        return data

    def to_json(self) -> dict[str, Any]:
        """The structure for scripts and agents.

        The table headers are for people and awkward as JSON keys — the field names here
        are stable identifiers, and values keep their raw types (a boolean is a boolean,
        not "yes" / "no").
        """
        data: dict[str, Any] = {
            "did": self.did,
            "name": self.name,
            "alias": self.alias,
            "model": self.model,
            "urn": self.urn,
            "manufacturer": self.manufacturer,
            "home": self.home_name or None,
            "home_id": self.home_id or None,
            "room": self.room_name or None,
            "room_id": self.room_id or None,
            "online": self.online,
            "local_ip": self.local_ip,
            "fw_version": self.fw_version,
            "connect_type": self.connect_type,
        }
        if self.sub_devices:
            data["sub_devices"] = sorted(self.sub_devices)
        return data

    @staticmethod
    def load(data: dict[str, Any], alias: str | None = None) -> "Device":
        return Device(
            did=data["did"],
            name=data.get("name", ""),
            model=data.get("model", ""),
            urn=data.get("urn", ""),
            online=bool(data.get("online", False)),
            home_id=str(data.get("home_id", "")),
            home_name=data.get("home_name", "") or "",
            room_id=str(data.get("room_id", "")),
            room_name=data.get("room_name", "") or "",
            token=data.get("token"),
            local_ip=data.get("local_ip"),
            # This cannot be written as `x or -1`: the connect_type of a WiFi device
            # connected directly is 0, which `or` would swallow as falsy, wrongly
            # concluding that direct LAN control is impossible
            connect_type=(
                int(data["connect_type"])
                if data.get("connect_type") is not None
                else -1
            ),
            manufacturer=data.get("manufacturer", ""),
            fw_version=data.get("fw_version"),
            parent_id=data.get("parent_id"),
            sub_devices=data.get("sub_devices") or {},
            alias=alias,
        )


class Registry:
    """A snapshot of one profile's device list."""

    def __init__(
        self,
        data: dict[str, Any],
        aliases: dict[str, str] | None = None,
    ) -> None:
        self.uid: str | None = data.get("uid")
        self.synced_at: int = int(data.get("synced_at", 0))
        self.homes: list[dict[str, Any]] = data.get("homes") or []
        by_did = {did: name for name, did in (aliases or {}).items()}
        self.devices: list[Device] = [
            Device.load(item, alias=by_did.get(did))
            for did, item in (data.get("devices") or {}).items()
        ]
        self.devices.sort(key=lambda d: (d.home_name, d.room_name, d.name))

    @property
    def age(self) -> int:
        return int(time.time()) - self.synced_at

    @staticmethod
    def read(profile: Profile) -> "Registry | None":
        from ..store import _read_json  # internal helper, permissions are all handled over there

        data = _read_json(profile.devices_path)
        if not data:
            return None
        return Registry(data, profile.read_aliases())

    @staticmethod
    def write(profile: Profile, data: dict[str, Any]) -> "Registry":
        payload = {**data, "synced_at": int(time.time())}
        profile.write_devices(payload)
        return Registry(payload, profile.read_aliases())

    # ---------- filtering ----------

    def filter(
        self,
        *,
        home: str | None = None,
        home_id: str | None = None,
        room: str | None = None,
        model: str | None = None,
        online: bool | None = None,
        search: str | None = None,
    ) -> list[Device]:
        def match(device: Device) -> bool:
            if home_id and device.home_id != home_id:
                return False
            if home and home.lower() not in device.home_name.lower():
                return False
            if room and room.lower() not in device.room_name.lower():
                return False
            if model and model.lower() not in device.model.lower():
                return False
            if online is not None and device.online != online:
                return False
            if search:
                haystack = f"{device.label} {device.name} {device.model}".lower()
                if search.lower() not in haystack:
                    return False
            return True

        return [device for device in self.devices if match(device)]

    # ---------- resolution ----------

    def find_home(self, ref: str) -> dict[str, Any]:
        """Find a home by name or home_id."""
        lowered = ref.strip().lower()
        stages = [
            [h for h in self.homes if str(h["home_id"]) == ref.strip()],
            [h for h in self.homes if h["home_name"].lower() == lowered],
            [h for h in self.homes if lowered in h["home_name"].lower()],
        ]
        for candidates in stages:
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                raise AmbiguousReference(
                    f"`{ref}` matches several homes: "
                    + ", ".join(h["home_name"] for h in candidates)
                )
        raise DeviceNotFound(
            f"Home `{ref}` not found",
            hint="See the available homes with `mi home list`",
        )

    def resolve(self, ref: str, **filters: Any) -> Device:
        """Turn what the user wrote into one specific device.

        Matching goes from most to least precise; once a level hits, lower levels are not
        searched. Several hits on the same level are reported as ambiguous, with the
        candidates listed for the user to pick from.
        """
        pool = self.filter(**filters)
        if not pool:
            raise DeviceNotFound("No devices match the current filters")
        needle = ref.strip()
        lowered = needle.lower()

        stages: list[list[Device]] = [
            [d for d in pool if d.did == needle],
            [d for d in pool if d.alias and d.alias.lower() == lowered],
            [d for d in pool if d.name.lower() == lowered],
            [
                d
                for d in pool
                if "/" in needle
                and f"{d.room_name}/{d.name}".lower() == lowered
            ],
            [d for d in pool if lowered in d.name.lower()],
            [d for d in pool if lowered in d.model.lower()],
        ]
        for candidates in stages:
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                raise AmbiguousReference(
                    f"`{ref}` matches {len(candidates)} devices:\n"
                    + "\n".join(
                        f"  {d.location} / {d.label} ({d.model}, did {d.did})"
                        for d in candidates[:10]
                    )
                    + ("\n  …" if len(candidates) > 10 else ""),
                    hint="Use the full name, an alias or the did, or narrow it down "
                         "with --home / --room",
                )
        raise DeviceNotFound(
            f"Device `{ref}` not found",
            hint="See the available devices with `mi device list`, or refresh the "
                 "cache with `mi device sync`",
        )
