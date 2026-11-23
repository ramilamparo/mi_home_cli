"""Data assembly of the cloud API."""
import httpx
import pytest

from mi_home_cli.core.cloud import CloudApi
from mi_home_cli.core.session import Session
from mi_home_cli.store import AuthData, Profile

HOME_RESULT = {
    "code": 0,
    "result": {
        "homelist": [
            {
                "id": 111, "name": "My Home", "uid": 999, "dids": ["d-home"],
                "roomlist": [
                    {"id": 11, "name": "Living Room", "dids": ["d1"]},
                    {"id": 12, "name": "Bedroom", "dids": ["d2", "d2.s1"]},
                ],
            }
        ],
        "share_home_list": [
            {"id": 222, "name": "Friend Home", "uid": 888, "dids": [], "roomlist": []}
        ],
    },
}


def _device(did, name, **extra):
    return {
        "did": did, "name": name, "model": "vendor.light.v1",
        "spec_type": "urn:x", "isOnline": True, **extra,
    }


def _session(profile: Profile, handler) -> Session:
    profile.write_auth(
        AuthData("AT", "RT", "cn", "ha.abc", 1700000000, 10**9)
    )
    return Session(profile, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_fetch_homes_flattens_rooms(profile: Profile):
    with _session(profile, lambda r: httpx.Response(200, json=HOME_RESULT)) as s:
        homes = CloudApi(s).fetch_homes()
    assert homes["uid"] == "999"
    assert [h["home_name"] for h in homes["homes"]] == ["My Home", "Friend Home"]
    assert homes["homes"][0]["shared"] is False
    assert homes["homes"][1]["shared"] is True
    assert [r["room_name"] for r in homes["homes"][0]["rooms"]] == ["Living Room", "Bedroom"]


def test_device_list_page_follows_pagination(profile: Profile):
    pages = [
        {
            "code": 0,
            "result": {
                "list": [_device("d1", "Light One")],
                "has_more": True,
                "next_start_did": "d1",
            },
        },
        {"code": 0, "result": {"list": [_device("d2", "Light Two")], "has_more": False}},
    ]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=pages[len(calls) - 1])

    with _session(profile, handler) as s:
        devices = CloudApi(s).fetch_device_details(["d1", "d2"])
    assert sorted(devices) == ["d1", "d2"]
    assert len(calls) == 2


def test_fetch_all_merges_placement_and_folds_sub_devices(profile: Profile):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/homeroom/gethome"):
            return httpx.Response(200, json=HOME_RESULT)
        body = request.read().decode()
        if '"dids": []' in body.replace("\n", ""):  # the call that looks up individually shared devices
            return httpx.Response(200, json={"code": 0, "result": {"list": []}})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "result": {
                    "list": [
                        _device("d1", "Living Room Light"),
                        _device("d2", "Gateway"),
                        _device("d2.s1", "Sub Device"),
                        _device("d-home", "No Room Device"),
                    ]
                },
            },
        )

    with _session(profile, handler) as s:
        data = CloudApi(s).fetch_all()

    devices = data["devices"]
    assert devices["d1"]["room_name"] == "Living Room"
    assert devices["d1"]["home_name"] == "My Home"
    # devices directly under the home have no room
    assert devices["d-home"]["room_name"] == ""
    # sub-devices are folded into their parent and do not appear separately in the list
    assert "d2.s1" not in devices
    assert devices["d2"]["sub_devices"]["s1"]["name"] == "Sub Device"


def test_ignores_miwifi_devices(profile: Profile):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "result": {"list": [_device("miwifi.1", "Router"), _device("d1", "Light")]},
            },
        )

    with _session(profile, handler) as s:
        devices = CloudApi(s).fetch_device_details(["miwifi.1", "d1"])
    assert list(devices) == ["d1"]


def test_get_props_is_chunked(profile: Profile):
    sizes = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        sizes.append(len(_json.loads(request.read())["params"]))
        return httpx.Response(200, json={"code": 0, "result": []})

    params = [{"did": "d", "siid": 1, "piid": i} for i in range(210)]
    with _session(profile, handler) as s:
        CloudApi(s).get_props(params)
    assert sizes == [150, 60]


def test_action_sends_bare_value_list(profile: Profile):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen.update(_json.loads(request.read())["params"])
        return httpx.Response(200, json={"code": 0, "result": {"code": 0}})

    with _session(profile, handler) as s:
        CloudApi(s).call_action("d1", 2, 1, [5, "x"])
    # this API wants an array of values, not {piid, value}
    assert seen == {"did": "d1", "siid": 2, "aiid": 1, "in": [5, "x"]}


def test_set_result_code_1_is_accepted_not_failure():
    """Some devices (e.g. dwdz.switch.sw0a01) answer code=1 to every write while the operation actually succeeds.

    In testing: reading the current value gives code=0, writing the same value back
    gives code=1, and the device state is fine; treating every non-zero code as a
    failure would make all write operations report an error.
    """
    from mi_home_cli.cli.prop import ACCEPTED_CODES, _explain_code

    assert 0 in ACCEPTED_CODES and 1 in ACCEPTED_CODES
    assert -704010000 not in ACCEPTED_CODES
    assert _explain_code(1) == "accepted"
    assert "failed" in _explain_code(-704220025) or "not writable" in _explain_code(-704220025)
