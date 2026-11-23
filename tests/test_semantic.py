"""The mapping layer of the semantic commands."""
import pytest

from mi_home_cli.core.semantic import (
    Planner,
    enum_value,
    format_color,
    parse_color,
)
from mi_home_cli.core.spec import DeviceSpec
from mi_home_cli.errors import InvalidValue, SpecNotFound


def _spec(device_type: str, services: list[dict]) -> DeviceSpec:
    instance = {
        "type": f"urn:miot-spec-v2:device:{device_type}:0000A001:x:1",
        "description": device_type,
        "services": services,
    }
    return DeviceSpec(instance["type"], instance, {})


def _prop(iid, name, fmt="uint8", access=("read", "write"), **extra):
    return {
        "iid": iid,
        "type": f"urn:miot-spec-v2:property:{name}:00000001:x:1",
        "description": name,
        "format": fmt,
        "access": list(access),
        **extra,
    }


LIGHT = _spec(
    "light",
    [
        {
            "iid": 2,
            "type": "urn:miot-spec-v2:service:light:00007802:x:1",
            "properties": [
                _prop(1, "on", "bool"),
                _prop(2, "brightness", "uint8", **{"value-range": [1, 100, 1]}),
                _prop(3, "color-temperature", "uint16", **{"value-range": [2700, 6500, 1]}),
                _prop(4, "color", "uint32", **{"value-range": [0, 16777215, 1]}),
            ],
        },
        {
            "iid": 6,
            "type": "urn:miot-spec-v2:service:indicator-light:00007803:x:1",
            "properties": [_prop(1, "on", "bool")],
        },
    ],
)

COVER = _spec(
    "curtain",
    [
        {
            "iid": 2,
            "type": "urn:miot-spec-v2:service:curtain:00007816:x:1",
            "properties": [
                _prop(
                    1,
                    "motor-control",
                    "uint8",
                    **{
                        "value-list": [
                            {"value": 0, "description": "Pause"},
                            {"value": 1, "description": "Open"},
                            {"value": 2, "description": "Close"},
                        ]
                    },
                ),
                _prop(2, "target-position", "uint8", **{"value-range": [0, 100, 1]}),
                _prop(3, "current-position", "uint8", access=("read",)),
            ],
        }
    ],
)


def test_parse_color_hex_and_names():
    assert parse_color("#ff8800") == 0xFF8800
    assert parse_color("ff8800") == 0xFF8800
    assert parse_color("red") == 0xFF0000
    assert parse_color("BLUE") == 0x0000FF


def test_parse_color_rejects_garbage():
    with pytest.raises(InvalidValue):
        parse_color("reddish-purple-ish")
    with pytest.raises(InvalidValue):
        parse_color("#fff")


def test_format_color():
    assert format_color(0xFF8800) == "#ff8800"


def test_by_name_prefers_primary_service():
    """A light has two `on` properties (main body and indicator light); the semantic commands must pick the main one."""
    assert LIGHT.by_name("on", writable=True).siid == 2


def test_by_name_respects_access_filter():
    assert COVER.by_name("current-position", writable=True) is None
    assert COVER.by_name("current-position", readable=True).ref == "2.3"


def test_by_name_falls_back_through_candidates():
    # falls back to speed-level when fan-level does not exist
    spec = _spec(
        "fan",
        [
            {
                "iid": 2,
                "type": "urn:miot-spec-v2:service:fan:00007808:x:1",
                "properties": [_prop(5, "speed-level")],
            }
        ],
    )
    assert spec.by_name("fan-level", "speed-level", writable=True).ref == "2.5"


def test_planner_builds_params_with_on_first():
    planner = Planner(LIGHT, "Desk Lamp")
    planner.add_parsed("--brightness", ("brightness",), "60")
    planner.add_raw("--on/--off", ("on",), True)
    params = planner.params("d1")
    # on comes first: power up before adjusting parameters
    assert [(p["siid"], p["piid"], p["value"]) for p in params] == [
        (2, 1, True),
        (2, 2, 60),
    ]


def test_planner_validates_values():
    planner = Planner(LIGHT, "Desk Lamp")
    with pytest.raises(InvalidValue):
        planner.add_parsed("--brightness", ("brightness",), "300")


def test_planner_reports_unsupported_option():
    planner = Planner(COVER, "Curtain")
    with pytest.raises(SpecNotFound) as excinfo:
        planner.add_parsed("--brightness", ("brightness",), "60")
    assert "does not support --brightness" in str(excinfo.value)
    assert excinfo.value.hint  # must tell the user where to see what is supported


def test_enum_value_matches_keywords():
    prop = COVER.by_name("motor-control", writable=True)
    assert enum_value(prop, "open") == 1
    assert enum_value(prop, "close") == 2
    assert enum_value(prop, "pause") == 0
    assert enum_value(prop, "nonexistent") is None


def test_planner_enum_missing_raises():
    spec = _spec(
        "curtain",
        [
            {
                "iid": 2,
                "type": "urn:miot-spec-v2:service:curtain:00007816:x:1",
                "properties": [
                    _prop(
                        1,
                        "motor-control",
                        "uint8",
                        **{"value-list": [{"value": 0, "description": "Open"}]},
                    )
                ],
            }
        ],
    )
    planner = Planner(spec, "Curtain")
    with pytest.raises(SpecNotFound):
        planner.add_enum("--close", ("motor-control",), "close")
