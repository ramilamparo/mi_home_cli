"""Device resolution: whether the CLI is pleasant to use depends on this."""
import pytest

from mi_home_cli.core.registry import Registry
from mi_home_cli.errors import AmbiguousReference, DeviceNotFound

DATA = {
    "uid": "1",
    "synced_at": 1700000000,
    "homes": [
        {"home_id": "h1", "home_name": "My Home", "rooms": []},
        {"home_id": "h2", "home_name": "Old Home", "rooms": []},
    ],
    "devices": {
        "100": {
            "did": "100", "name": "Living Room Ceiling Light", "model": "yeelink.light.ml13",
            "urn": "urn:1", "online": True, "home_id": "h1", "home_name": "My Home",
            "room_id": "r1", "room_name": "Living Room",
        },
        "200": {
            "did": "200", "name": "Bedroom Ceiling Light", "model": "yeelink.light.ml13",
            "urn": "urn:1", "online": False, "home_id": "h1", "home_name": "My Home",
            "room_id": "r2", "room_name": "Bedroom",
        },
        "300": {
            "did": "300", "name": "Air Purifier", "model": "xiaomi.airp.ma6",
            "urn": "urn:2", "online": True, "home_id": "h1", "home_name": "My Home",
            "room_id": "r1", "room_name": "Living Room",
        },
    },
}


@pytest.fixture()
def registry() -> Registry:
    return Registry(DATA, {"ap": "300"})


def test_resolve_by_did(registry: Registry):
    assert registry.resolve("200").name == "Bedroom Ceiling Light"


def test_resolve_by_alias(registry: Registry):
    device = registry.resolve("ap")
    assert device.did == "300"
    assert device.label == "ap"  # an alias is shown when there is one


def test_resolve_by_exact_name(registry: Registry):
    assert registry.resolve("Living Room Ceiling Light").did == "100"


def test_resolve_by_room_slash_name(registry: Registry):
    assert registry.resolve("Bedroom/Bedroom Ceiling Light").did == "200"


def test_resolve_by_substring(registry: Registry):
    assert registry.resolve("Purifier").did == "300"


def test_resolve_by_model(registry: Registry):
    assert registry.resolve("xiaomi.airp").did == "300"


def test_ambiguous_lists_candidates(registry: Registry):
    with pytest.raises(AmbiguousReference) as excinfo:
        registry.resolve("Ceiling Light")
    message = str(excinfo.value)
    assert "Living Room Ceiling Light" in message and "Bedroom Ceiling Light" in message
    assert excinfo.value.exit_code == 4


def test_filters_narrow_ambiguity(registry: Registry):
    assert registry.resolve("Ceiling Light", room="Living Room").did == "100"


def test_unknown_device(registry: Registry):
    with pytest.raises(DeviceNotFound) as excinfo:
        registry.resolve("Washing Machine")
    assert excinfo.value.exit_code == 3


def test_exact_name_beats_substring():
    """When one name is a prefix of another, the exact match wins and no ambiguity is reported."""
    data = {
        **DATA,
        "devices": {
            "1": {"did": "1", "name": "Light", "model": "m", "urn": "u", "online": True},
            "2": {"did": "2", "name": "Light Strip", "model": "m", "urn": "u", "online": True},
        },
    }
    assert Registry(data).resolve("Light").did == "1"


def test_filter_by_online_and_search(registry: Registry):
    assert [d.did for d in registry.filter(online=False)] == ["200"]
    assert {d.did for d in registry.filter(search="Light")} == {"100", "200"}
    assert [d.did for d in registry.filter(room="Living Room", model="airp")] == ["300"]


def test_find_home_by_name_and_id(registry: Registry):
    assert registry.find_home("My Home")["home_id"] == "h1"
    assert registry.find_home("h2")["home_name"] == "Old Home"
    assert registry.find_home("Old")["home_id"] == "h2"


def test_find_home_unknown(registry: Registry):
    with pytest.raises(DeviceNotFound):
        registry.find_home("Someone Elses Home")


def test_find_home_ambiguous():
    data = {
        **DATA,
        "homes": [
            {"home_id": "h1", "home_name": "My Home One", "rooms": []},
            {"home_id": "h2", "home_name": "My Home Two", "rooms": []},
        ],
    }
    with pytest.raises(AmbiguousReference):
        Registry(data).find_home("My Home")


def test_filter_by_home_id_is_exact(registry: Registry):
    """Filtering is by id, so renaming the home does not affect it."""
    assert len(registry.filter(home_id="h1")) == 3
    assert registry.filter(home_id="h2") == []


def test_default_home_scope_removes_ambiguity():
    """Two homes each have a light of the same name; limiting to one home removes the ambiguity."""
    data = {
        **DATA,
        "devices": {
            "1": {
                "did": "1", "name": "Desk Lamp", "model": "m", "urn": "u",
                "online": True, "home_id": "h1", "home_name": "My Home",
            },
            "2": {
                "did": "2", "name": "Desk Lamp", "model": "m", "urn": "u",
                "online": True, "home_id": "h2", "home_name": "Old Home",
            },
        },
    }
    registry = Registry(data)
    with pytest.raises(AmbiguousReference):
        registry.resolve("Desk Lamp")
    assert registry.resolve("Desk Lamp", home_id="h1").did == "1"


def test_connect_type_zero_survives():
    """The connect_type of a WiFi device connected directly is 0 and must not be swallowed by something like `or -1` —

    that would wrongly mark every WiFi device as not supporting direct LAN control.
    """
    from mi_home_cli.core.channel import lan_capable
    from mi_home_cli.core.registry import Device

    device = Device.load(
        {"did": "1", "name": "Light", "model": "m", "urn": "u", "online": True,
         "connect_type": 0, "token": "a" * 32}
    )
    assert device.connect_type == 0
    assert lan_capable(device)

    mesh = Device.load(
        {"did": "2", "name": "Light", "model": "m", "urn": "u", "online": True,
         "connect_type": 16, "token": "a" * 32}
    )
    assert not lan_capable(mesh)

    no_token = Device.load(
        {"did": "3", "name": "Light", "model": "m", "urn": "u", "online": True,
         "connect_type": 0}
    )
    assert not lan_capable(no_token)

    missing = Device.load({"did": "4", "name": "Light", "model": "m", "urn": "u"})
    assert missing.connect_type == -1


def test_json_shape_is_script_friendly(registry: Registry):
    """The JSON for scripts/agents uses identifier keys and raw types.

    The table's "Name" and "Online: yes" are for people; as JSON keys and values they
    are awkward.
    """
    device = registry.resolve("300")
    data = device.to_json()
    assert data["did"] == "300"
    assert data["name"] == "Air Purifier"
    assert data["alias"] == "ap"
    assert data["online"] is True  # a boolean is a boolean, not "yes"
    assert data["room"] == "Living Room"
    assert data["connect_type"] == -1
    # empty values are null rather than "-", which is easier to test for
    assert registry.resolve("100").to_json()["alias"] is None
