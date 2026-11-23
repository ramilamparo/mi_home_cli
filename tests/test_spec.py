"""Spec parsing and value conversion."""
import pytest

from mi_home_cli.core.spec import (
    DeviceSpec,
    format_value,
    parse_value,
    unit_symbol,
    urn_name,
)
from mi_home_cli.errors import AmbiguousReference, InvalidValue, SpecNotFound

INSTANCE = {
    "type": "urn:miot-spec-v2:device:air-purifier:0000A007:xiaomi-ma6:1",
    "description": "Air Purifier",
    "services": [
        {
            "iid": 2,
            "type": "urn:miot-spec-v2:service:air-purifier:00007811:x:1",
            "properties": [
                {
                    "iid": 1,
                    "type": "urn:miot-spec-v2:property:on:00000006:x:1",
                    "format": "bool",
                    "access": ["read", "write", "notify"],
                },
                {
                    "iid": 3,
                    "type": "urn:miot-spec-v2:property:mode:00000008:x:1",
                    "description": "Mode",
                    "format": "uint8",
                    "access": ["read", "write"],
                    "value-list": [
                        {"value": 0, "description": "Auto"},
                        {"value": 3, "description": "Sleep"},
                    ],
                },
                {
                    "iid": 4,
                    "type": "urn:miot-spec-v2:property:fault:00000009:x:1",
                    "format": "uint8",
                    "access": ["read"],
                },
            ],
            "actions": [
                {
                    "iid": 1,
                    "type": "urn:miot-spec-v2:action:toggle:00002811:x:1",
                    "description": "Toggle",
                    "in": [3],
                }
            ],
            "events": [
                {
                    "iid": 1,
                    "type": "urn:miot-spec-v2:event:low-battery:0000200x:x:1",
                    "description": "Low Battery",
                }
            ],
        },
        {
            "iid": 6,
            "type": "urn:miot-spec-v2:service:screen:00007806:x:1",
            "properties": [
                {
                    "iid": 1,
                    "type": "urn:miot-spec-v2:property:on:00000006:x:1",
                    "format": "bool",
                    "access": ["read", "write"],
                },
                {
                    "iid": 2,
                    "type": "urn:miot-spec-v2:property:brightness:0000000D:x:1",
                    "format": "uint8",
                    "access": ["read", "write"],
                    "unit": "percentage",
                    "value-range": [1, 100, 1],
                },
            ],
        },
    ],
}

TRANSLATIONS = {
    "service:002:property:003": "Operating Mode",
    "service:002:property:003:valuelist:000": "Automatic",
    "service:002:property:003:valuelist:001": "Sleeping",
    "service:002:action:001": "Toggle Power",
}


@pytest.fixture()
def spec() -> DeviceSpec:
    return DeviceSpec(INSTANCE["type"], INSTANCE, TRANSLATIONS)


def test_urn_name():
    assert urn_name("urn:miot-spec-v2:property:brightness:0000000D:x:1") == "brightness"


def test_parses_services_properties_actions_events(spec: DeviceSpec):
    assert spec.name == "air-purifier"
    assert len(spec.properties) == 5
    assert len(spec.actions) == 1 and len(spec.events) == 1
    prop = spec.find_property("2.3")
    assert prop.full_name == "air-purifier.mode"
    assert prop.access_text() == "rw"
    assert prop.readable and prop.writable and not prop.notifiable


def test_applies_translations(spec: DeviceSpec):
    prop = spec.find_property("2.3")
    assert prop.description == "Operating Mode"
    assert [item.description for item in prop.value_list] == ["Automatic", "Sleeping"]
    assert spec.find_action("2.1").description == "Toggle Power"


def test_find_property_by_full_name_and_bare_name(spec: DeviceSpec):
    assert spec.find_property("screen.brightness").ref == "6.2"
    assert spec.find_property("brightness").ref == "6.2"
    assert spec.find_property("Operating Mode").ref == "2.3"


def test_bare_name_prefers_primary_service(spec: DeviceSpec):
    """`on` exists on both the main body and the screen; the device type is air-purifier, so the main one is taken."""
    assert spec.find_property("on").ref == "2.1"
    assert spec.find_property("screen.on").ref == "6.1"


def test_ambiguous_reference_raises(spec: DeviceSpec):
    # the case of two services both called x: build a spec without a main-service
    # preference
    instance = {**INSTANCE, "type": "urn:miot-spec-v2:device:gateway:0:x:1"}
    other = DeviceSpec(instance["type"], instance, {})
    with pytest.raises(AmbiguousReference):
        other.find_property("on")


def test_unknown_property(spec: DeviceSpec):
    with pytest.raises(SpecNotFound):
        spec.find_property("nope")
    with pytest.raises(SpecNotFound):
        spec.find_property("9.9")


def test_parse_bool_accepts_common_words(spec: DeviceSpec):
    prop = spec.find_property("2.1")
    for word in ("on", "true", "1", "yes"):
        assert parse_value(prop, word) is True
    for word in ("off", "false", "0", "no"):
        assert parse_value(prop, word) is False
    with pytest.raises(InvalidValue):
        parse_value(prop, "maybe")


def test_parse_enum_by_description_or_value(spec: DeviceSpec):
    prop = spec.find_property("2.3")
    assert parse_value(prop, "Sleeping") == 3
    assert parse_value(prop, "Sleep") == 3  # the instance's original text is accepted too
    assert parse_value(prop, "3") == 3
    with pytest.raises(InvalidValue):
        parse_value(prop, "berserk")


def test_parse_number_checks_range(spec: DeviceSpec):
    prop = spec.find_property("screen.brightness")
    assert parse_value(prop, "60") == 60
    with pytest.raises(InvalidValue):
        parse_value(prop, "300")
    with pytest.raises(InvalidValue):
        parse_value(prop, "abc")


def test_format_value(spec: DeviceSpec):
    assert format_value(spec.find_property("2.1"), True) == "on"
    assert format_value(spec.find_property("2.3"), 3) == "Sleeping(3)"
    assert format_value(spec.find_property("screen.brightness"), 60) == "60%"
    assert format_value(spec.find_property("2.4"), None) == "-"


def test_unit_symbol():
    assert unit_symbol("percentage") == "%"
    assert unit_symbol("kelvin") == "K"
    assert unit_symbol("none") == ""
    assert unit_symbol(None) == ""
    assert unit_symbol("weird-unit") == "weird-unit"


def test_range_text(spec: DeviceSpec):
    assert spec.find_property("screen.brightness").range_text() == "1~100 step 1"
    assert spec.find_property("2.3").range_text() == "0=Automatic 3=Sleeping"
    assert spec.find_property("2.1").range_text() == "-"


def test_verify_after_write_reports_actual_values(monkeypatch, spec):
    """Read back after writing: the device's real state counts, not just the return code."""
    from mi_home_cli.cli.prop import verify_after_write

    prop = spec.find_property("screen.brightness")
    calls = []

    class FakeApi:
        def get_props(self, params):
            calls.append(params)
            # still the old value the first time, caught up the second time — simulates
            # a reporting delay
            value = 30 if len(calls) == 1 else 60
            return [{"siid": 6, "piid": 2, "value": value, "code": 0}]

    monkeypatch.setattr("time.sleep", lambda _: None)
    actual = verify_after_write(FakeApi(), "d1", [(prop, 60)], delay=0)
    assert actual[(6, 2)] == 60
    assert len(calls) == 2  # mismatch the first time, retried once


def test_verify_skips_unreadable_properties(monkeypatch, spec):
    from mi_home_cli.cli.prop import verify_after_write

    write_only = spec.find_property("2.3")
    write_only.access = ["write"]

    class Boom:
        def get_props(self, params):
            raise AssertionError("must not send a read request for a write-only property")

    monkeypatch.setattr("time.sleep", lambda _: None)
    assert verify_after_write(Boom(), "d1", [(write_only, 3)], delay=0) == {}


def test_float_is_shown_with_significant_digits(spec):
    """A device reports a temperature as 23.700001; showing that as is is ugly and looks like false precision.

    Significant digits rather than fixed decimals: 2 fixed decimals would round
    0.019 mg/m³ to 0.02.
    """
    from mi_home_cli.core.spec import Property, format_value

    temperature = Property(
        siid=3, piid=2, name="temperature", description="Temperature", format="float",
        access=["read"], service="environment", unit="celsius",
    )
    assert format_value(temperature, 23.700001) == "23.7℃"
    assert format_value(temperature, 57.0) == "57℃"

    hcho = Property(
        siid=3, piid=6, name="hcho-density", description="Formaldehyde", format="float",
        access=["read"], service="environment", unit="mg/m3",
    )
    assert format_value(hcho, 0.019) == "0.019 mg/m³"


def test_action_output_gets_property_names():
    """An action returns a list of bare values, which only make sense with property names attached.

    Typical case: a camera with official streaming, whose start-rtsp-stream returns
    [address, snapshot address, expiry time].
    """
    from mi_home_cli.cli.prop import describe_action_output

    instance = {
        "type": "urn:miot-spec-v2:device:camera:0000A01C:x:1",
        "description": "Camera",
        "services": [
            {
                "iid": 3,
                "type": "urn:miot-spec-v2:service:camera-stream-for-amazon-alexa:1:x:1",
                "properties": [
                    {
                        "iid": 7,
                        "type": "urn:miot-spec-v2:property:stream-address:1:x:1",
                        "description": "Stream Address",
                        "format": "string",
                        "access": [],
                    },
                    {
                        "iid": 9,
                        "type": "urn:miot-spec-v2:property:expiration-time:1:x:1",
                        "description": "Expiration Time",
                        "format": "string",
                        "access": [],
                    },
                ],
                "actions": [
                    {
                        "iid": 1,
                        "type": "urn:miot-spec-v2:action:start-rtsp-stream:1:x:1",
                        "description": "Start RTSP Stream",
                        "in": [],
                        "out": [7, 9],
                    }
                ],
            }
        ],
    }
    spec = DeviceSpec(instance["type"], instance, {})
    action = spec.find_action("start-rtsp-stream")

    # array of bare values: names are attached in the order of out
    assert describe_action_output(spec, action, ["rtsp://x", "2026-08-20"]) == {
        "stream-address": "rtsp://x",
        "expiration-time": "2026-08-20",
    }
    # the {piid, value} form is accepted too
    assert describe_action_output(
        spec, action, [{"piid": 7, "value": "rtsp://y"}]
    ) == {"stream-address": "rtsp://y"}
    # if the counts do not line up, hand it out as is; do not guess
    assert describe_action_output(spec, action, [1, 2, 3]) == [1, 2, 3]
    assert describe_action_output(spec, action, []) == "-"
