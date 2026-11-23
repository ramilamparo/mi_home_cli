"""Mi Home cloud API: homes, rooms, the device list, and property reads/writes.

The API paths and fields come from observing the public behaviour of the Home
Assistant Xiaomi Home integration; they are not a contract Xiaomi promises to
outsiders. All URLs are concentrated here, so an API change only touches this file.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from ..errors import CloudError
from .session import Session

# Maximum number of dids in one device_list_page request
DIDS_PER_REQUEST = 150
# Maximum number of properties read in one prop/get
PROPS_PER_REQUEST = 150

# These devices define a spec but are not actually usable; skip them just like upstream
_IGNORED_DID_PREFIXES = ("miwifi.",)
# A did shaped like 600123456.s2 is a sub-device
_SUB_DEVICE_RE = re.compile(r"\.s\d+$")


def _chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index:index + size]


class CloudApi:
    """A thin wrapper that only arranges the cloud's data structures into a convenient shape."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ---------- homes / rooms ----------

    def fetch_homes(self) -> dict[str, Any]:
        """Homes, rooms, and the list of dids in each room."""
        res = self.session.api_post(
            "/app/v2/homeroom/gethome",
            {
                "limit": 150,
                "fetch_share": True,
                "fetch_share_dev": True,
                "plat_form": 0,
                "app_ver": 9,
            },
        ).get("result")
        if not isinstance(res, dict):
            raise CloudError("The gethome response has no result")

        uid: str | None = None
        homes: list[dict[str, Any]] = []
        for source, shared in (("homelist", False), ("share_home_list", True)):
            for home in res.get(source) or []:
                if "id" not in home or "name" not in home:
                    continue
                if uid is None and not shared and home.get("uid"):
                    uid = str(home["uid"])
                rooms = [
                    {
                        "room_id": str(room["id"]),
                        "room_name": room.get("name", ""),
                        "dids": room.get("dids") or [],
                    }
                    for room in home.get("roomlist") or []
                    if "id" in room
                ]
                homes.append(
                    {
                        "home_id": str(home["id"]),
                        "home_name": home["name"],
                        "uid": str(home.get("uid") or ""),
                        "shared": shared,
                        "address": home.get("address"),
                        # Devices that belong to no room hang directly under the home
                        "dids": home.get("dids") or [],
                        "rooms": rooms,
                    }
                )
        return {"uid": uid, "homes": homes}

    # ---------- devices ----------

    def _device_list_page(
        self, dids: list[str], start_did: str | None = None
    ) -> dict[str, dict[str, Any]]:
        data: dict[str, Any] = {
            "limit": 200,
            "get_split_device": True,
            "get_third_device": True,
            "dids": dids,
        }
        if start_did:
            data["start_did"] = start_did
        res = self.session.api_post("/app/v2/home/device_list_page", data).get(
            "result"
        )
        if not isinstance(res, dict):
            raise CloudError("The device_list_page response has no result")

        devices: dict[str, dict[str, Any]] = {}
        for item in res.get("list") or []:
            did, name = item.get("did"), item.get("name")
            model, urn = item.get("model"), item.get("spec_type")
            if not did or not name or not model or not urn:
                continue
            if did.startswith(_IGNORED_DID_PREFIXES):
                continue
            devices[did] = {
                "did": did,
                "name": name,
                "model": model,
                "urn": urn,
                "manufacturer": model.split(".")[0],
                "online": bool(item.get("isOnline", False)),
                "token": item.get("token"),
                "local_ip": item.get("local_ip"),
                "ssid": item.get("ssid"),
                "rssi": item.get("rssi"),
                "connect_type": item.get("pid", -1),
                "parent_id": item.get("parent_id"),
                "owner": item.get("owner"),
                "fw_version": (item.get("extra") or {}).get("fw_version"),
            }

        next_start = res.get("next_start_did")
        if res.get("has_more") and next_start:
            devices.update(self._device_list_page(dids, start_did=next_start))
        return devices

    def fetch_device_details(self, dids: list[str]) -> dict[str, dict[str, Any]]:
        devices: dict[str, dict[str, Any]] = {}
        for chunk in _chunked(dids, DIDS_PER_REQUEST):
            devices.update(self._device_list_page(chunk))
        return devices

    def fetch_shared_devices(self) -> dict[str, dict[str, Any]]:
        """Devices that were shared individually and belong to no home."""
        result: dict[str, dict[str, Any]] = {}
        for did, device in self._device_list_page([]).items():
            owner = device.get("owner")
            if isinstance(owner, dict) and "userid" in owner:
                result[did] = device
        return result

    def fetch_all(self) -> dict[str, Any]:
        """Fetch everything in one go: homes, rooms, devices, and merge the membership info into the devices."""
        home_info = self.fetch_homes()
        placement: dict[str, dict[str, Any]] = {}
        for home in home_info["homes"]:
            base = {
                "home_id": home["home_id"],
                "home_name": home["home_name"],
                "room_id": "",
                "room_name": "",
            }
            for did in home["dids"]:
                placement[did] = dict(base)
            for room in home["rooms"]:
                for did in room["dids"]:
                    placement[did] = {
                        **base,
                        "room_id": room["room_id"],
                        "room_name": room["room_name"],
                    }

        devices = self.fetch_device_details(sorted(placement))
        for did, info in devices.items():
            info.update(placement.get(did, {}))

        shared = self.fetch_shared_devices()
        homes = list(home_info["homes"])
        if shared:
            for did, info in shared.items():
                if did in devices:
                    continue
                owner = info.get("owner") or {}
                owner_name = owner.get("nickname") or "Shared devices"
                info.update(
                    {
                        "home_id": f"shared:{owner.get('userid', '')}",
                        "home_name": owner_name,
                        "room_id": "",
                        "room_name": "",
                    }
                )
                devices[did] = info
            owners = {
                info["home_id"]: info["home_name"]
                for info in devices.values()
                if str(info.get("home_id", "")).startswith("shared:")
            }
            homes.extend(
                {
                    "home_id": home_id,
                    "home_name": name,
                    "uid": home_id.split(":", 1)[1],
                    "shared": True,
                    "address": None,
                    "dids": [],
                    "rooms": [],
                }
                for home_id, name in sorted(owners.items())
            )

        # Sub-devices (did with a .sN suffix) hang under their parent device and do not
        # appear separately in the list
        for did in list(devices):
            match = _SUB_DEVICE_RE.search(did)
            if not match:
                continue
            parent_did = did[: match.start()]
            if parent_did in devices:
                child = devices.pop(did)
                devices[parent_did].setdefault("sub_devices", {})[
                    match.group()[1:]
                ] = child

        return {"uid": home_info["uid"], "homes": homes, "devices": devices}

    # ---------- properties / actions ----------

    def get_props(self, params: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """params: [{"did":..., "siid":..., "piid":...}, ...]"""
        results: list[dict[str, Any]] = []
        for index in range(0, len(params), PROPS_PER_REQUEST):
            chunk = params[index:index + PROPS_PER_REQUEST]
            res = self.session.api_post(
                "/app/v2/miotspec/prop/get",
                {"datasource": 1, "params": chunk},
            )
            results.extend(res.get("result") or [])
        return results

    def set_props(self, params: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """params: [{"did":..., "siid":..., "piid":..., "value":...}, ...]"""
        res = self.session.api_post(
            "/app/v2/miotspec/prop/set", {"params": params}
        )
        return res.get("result") or []

    def call_action(
        self, did: str, siid: int, aiid: int, values: list[Any]
    ) -> dict[str, Any]:
        # Note: `in` of this API is an array of values, not an array of {piid, value}
        res = self.session.api_post(
            "/app/v2/miotspec/action",
            {"params": {"did": did, "siid": siid, "aiid": aiid, "in": values}},
        )
        return res.get("result") or {}
