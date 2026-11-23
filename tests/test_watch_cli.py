"""End-to-end wiring of `mi watch` (without a real broker).

A fake MQTT client pushes messages in; device resolution, spec descriptions, output
formats and exit conditions are verified.
"""
import json
import time

import pytest
from typer.testing import CliRunner

from mi_home_cli.cli.app import app
from mi_home_cli.store import AuthData, Profile

SPEC_INSTANCE = {
    "type": "urn:miot-spec-v2:device:light:0000A001:x:1",
    "description": "Light",
    "services": [
        {
            "iid": 2,
            "type": "urn:miot-spec-v2:service:light:00007802:x:1",
            "properties": [
                {
                    "iid": 1,
                    "type": "urn:miot-spec-v2:property:on:00000006:x:1",
                    "description": "Switch Status",
                    "format": "bool",
                    "access": ["read", "write", "notify"],
                },
                {
                    "iid": 2,
                    "type": "urn:miot-spec-v2:property:brightness:0000000D:x:1",
                    "description": "Brightness",
                    "format": "uint8",
                    "access": ["read", "write", "notify"],
                    "unit": "percentage",
                    "value-range": [1, 100, 1],
                },
            ],
            "events": [
                {
                    "iid": 1,
                    "type": "urn:miot-spec-v2:event:low-battery:00000001:x:1",
                    "description": "Low Battery",
                }
            ],
        }
    ],
}

URN = SPEC_INSTANCE["type"]
MESSAGES = [
    ("device/d1/up/properties_changed/2/1", b'{"params":{"siid":2,"piid":1,"value":true}}'),
    ("device/d1/up/properties_changed/2/2", b'{"params":{"siid":2,"piid":2,"value":60}}'),
    ("device/d1/up/properties_changed/2/2", b'{"params":{"siid":2,"piid":2,"value":80}}'),
    ("device/d1/up/event_occured/2/1", b'{"params":{"siid":2,"eiid":1,"arguments":[]}}'),
    ("device/d1/state/online", b'{"device_id":"d1","event":"offline"}'),
]


class FakeClient:
    """Pushes all preset messages as soon as it is connected."""

    def __init__(self, *args, **kwargs):
        self.subscribed = []

    def tls_set(self, **kwargs):
        pass

    def tls_set_context(self, context):
        pass

    def enable_logger(self, logger=None):
        pass

    def username_pw_set(self, username, password):
        pass

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)

    def connect(self, *args):
        pass

    def loop_start(self):
        self.on_connect(self, None, None, None)
        for topic, payload in MESSAGES:
            message = type("M", (), {"topic": topic, "payload": payload})()
            self.on_message(self, None, message)

    def loop_stop(self):
        pass

    def disconnect(self):
        pass


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MI_HOME_CONFIG_DIR", str(tmp_path))
    profile = Profile("default", root=tmp_path)
    profile.write_auth(
        AuthData("AT", "RT", "cn", "ha.abc", int(time.time()), 10**9)
    )
    profile.write_devices(
        {
            "uid": "1",
            "synced_at": int(time.time()),
            "homes": [{"home_id": "h1", "home_name": "My Home", "rooms": []}],
            "devices": {
                "d1": {
                    "did": "d1", "name": "Living Room Light", "model": "x.light.v1",
                    "urn": URN, "online": True, "home_id": "h1",
                    "home_name": "My Home", "room_id": "r1", "room_name": "Living Room",
                }
            },
        }
    )
    profile.spec_dir.mkdir(parents=True, exist_ok=True)
    # preset the spec cache so the test never touches the network
    (profile.spec_dir / (URN.replace(":", "_") + ".json")).write_text(
        json.dumps(
            {
                "urn": URN,
                "fetched_at": int(time.time()),
                "instance": SPEC_INSTANCE,
                "translations": {},
            }
        ),
        encoding="utf-8",
    )
    import mi_home_cli.core.mqtt as module

    monkeypatch.setattr(module.mqtt, "Client", FakeClient)
    return tmp_path


def test_watch_streams_json_lines(env):
    result = CliRunner().invoke(
        app, ["-o", "json", "watch", "Living Room Light", "--exit-after", "5"]
    )
    assert result.exit_code == 0, result.output
    lines = [
        json.loads(line)
        for line in result.output.splitlines()
        if line.startswith("{")
    ]
    assert len(lines) == 5
    assert lines[0] == {
        **lines[0],
        "kind": "prop",
        "property": "light.on",
        "value": True,
        "old": None,
        "did": "d1",
        "device": "Living Room Light",
    }
    # the third one is the second change of the same property and must carry the
    # previous value
    assert (lines[2]["property"], lines[2]["old"], lines[2]["value"]) == (
        "light.brightness", 60, 80,
    )
    assert lines[3]["kind"] == "event" and lines[3]["event"] == "light.low-battery"
    assert lines[4] == {**lines[4], "kind": "state", "state": "offline"}


def test_watch_table_output_translates_names(env):
    result = CliRunner().invoke(app, ["watch", "Living Room Light", "--exit-after", "3"])
    assert result.exit_code == 0, result.output
    assert "Switch Status" in result.output  # the description from the spec
    assert "60% → 80%" in result.output  # old value → new value, with the unit
    assert "3 message(s) in total" in result.output


def test_watch_prop_filter(env):
    result = CliRunner().invoke(
        app, ["-o", "plain", "watch", "Living Room Light", "--prop", "brightness", "--exit-after", "2"]
    )
    assert result.exit_code == 0, result.output
    assert "Brightness" in result.output
    assert "Switch Status" not in result.output


def test_watch_can_skip_events_and_state(env):
    result = CliRunner().invoke(
        app, ["watch", "Living Room Light", "--no-events", "--no-state", "--exit-after", "3"]
    )
    assert result.exit_code == 0, result.output
    # only properties are subscribed, not events or online state
    assert "device/d1/up/event_occured/#" not in result.output


def test_watch_unknown_device(env):
    """The error itself carries the exit code, and main() exits with it."""
    from mi_home_cli.errors import DeviceNotFound

    result = CliRunner().invoke(app, ["watch", "No Such Light", "--exit-after", "1"])
    assert isinstance(result.exception, DeviceNotFound)
    assert result.exception.exit_code == 3


REPEATS = [
    ("device/d1/up/properties_changed/2/2", b'{"params":{"siid":2,"piid":2,"value":60}}'),
    ("device/d1/up/properties_changed/2/2", b'{"params":{"siid":2,"piid":2,"value":60}}'),
    ("device/d1/up/properties_changed/2/2", b'{"params":{"siid":2,"piid":2,"value":80}}'),
]


def test_repeated_values_are_skipped_by_default(env, monkeypatch):
    """Devices periodically re-report the same value; on real hardware half of 26 messages were "1 → 1" noise."""
    import mi_home_cli.core.mqtt as module

    monkeypatch.setattr(module.mqtt, "Client", _client_replaying(REPEATS))
    result = CliRunner().invoke(
        app, ["-o", "plain", "watch", "Living Room Light", "--exit-after", "2"]
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if "Brightness" in line]
    assert len(lines) == 2  # 60 and 80; the repeated 60 in between is skipped
    assert "1 more report(s) with unchanged values were skipped" in result.output


def test_all_updates_keeps_repeats(env, monkeypatch):
    import mi_home_cli.core.mqtt as module

    monkeypatch.setattr(module.mqtt, "Client", _client_replaying(REPEATS))
    result = CliRunner().invoke(
        app,
        ["-o", "plain", "watch", "Living Room Light", "--all-updates", "--exit-after", "3"],
    )
    assert result.exit_code == 0, result.output
    assert len([x for x in result.output.splitlines() if "Brightness" in x]) == 3


def _client_replaying(messages):
    class Replay(FakeClient):
        def loop_start(self):
            self.on_connect(self, None, None, None)
            for topic, payload in messages:
                self.on_message(
                    self, None, type("M", (), {"topic": topic, "payload": payload})()
                )

    return Replay


def test_write_flags_work_after_subcommand(env):
    """`mi set light on=true --dry-run` is what anyone and any agent would naturally write.

    In testing an agent wrote exactly that, while --dry-run could only go before the
    subcommand at the time, so it sent the real write straight out.
    """
    result = CliRunner().invoke(
        app, ["set", "Living Room Light", "brightness=60", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output

    # the semantic commands and on/off must have it too
    assert "--dry-run" in CliRunner().invoke(app, ["light", "--help"]).output
    assert "--verify" in CliRunner().invoke(app, ["on", "--help"]).output
    assert "--dry-run" in CliRunner().invoke(app, ["action", "--help"]).output


def test_on_off_toggle_support_dry_run(env):
    """An agent wanted to rehearse `mi off lamp` first and found that only mi set supported --dry-run.

    The write switches must be consistent, or an agent falls back to sending the real
    command directly.
    """
    for command in ("on", "off", "toggle"):
        result = CliRunner().invoke(app, [command, "Living Room Light", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "dry-run" in result.output
        assert "light.on" in result.output
