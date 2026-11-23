"""The CLI is English only: no translation layer, no locale dependence."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from mi_home_cli.core.registry import Registry
from mi_home_cli.core.semantic import enum_value
from mi_home_cli.core.spec import SpecStore, format_value, parse_value
from mi_home_cli.errors import InvalidValue

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# CJK punctuation, CJK ideographs, full-width forms; written as escapes so this
# file itself stays ASCII
CJK = re.compile("[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]")


def test_no_cjk_characters_in_src():
    hits = []
    for path in sorted(SRC.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if CJK.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{number}")
    assert not hits, f"CJK characters found in: {hits}"


# ---- spec text is always English ---------------------------------------------

URN = "urn:miot-spec-v2:device:fan:0000A005:demo-fan:1"

INSTANCE = {
    "type": URN,
    "description": "Fan",
    "services": [
        {
            "iid": 2,
            "type": "urn:miot-spec-v2:service:fan:00007808:demo-fan:1",
            "properties": [
                {
                    "iid": 1,
                    "type": "urn:miot-spec-v2:property:on:00000006:demo-fan:1",
                    "description": "Switch Status",
                    "format": "bool",
                    "access": ["read", "write", "notify"],
                },
                {
                    "iid": 2,
                    "type": "urn:miot-spec-v2:property:mode:00000008:demo-fan:1",
                    "description": "Mode",
                    "format": "uint8",
                    "access": ["read", "write", "notify"],
                    "value-list": [
                        {"value": 0, "description": "Straight Wind"},
                        {"value": 1, "description": "Natural Wind"},
                    ],
                },
                {
                    "iid": 3,
                    "type": "urn:miot-spec-v2:property:horizontal-swing:00000017:demo-fan:1",
                    "description": "Horizontal Swing",
                    "format": "bool",
                    "access": ["read", "write"],
                },
            ],
            "actions": [
                {
                    "iid": 1,
                    "type": "urn:miot-spec-v2:action:toggle:00002811:demo-fan:1",
                    "description": "Toggle",
                    "in": [],
                }
            ],
            "events": [
                {
                    "iid": 1,
                    "type": "urn:miot-spec-v2:event:child-lock-trigger:0000501B:demo-fan:1",
                    "description": "Child Lock Trigger",
                }
            ],
        }
    ],
}

TRANSLATIONS = {
    # what a real cache also holds: the zh_cn translations (escaped CJK text)
    "zh_cn": {
        "service:002:property:001": "\u5f00\u5173",
        "service:002:property:002": "\u6a21\u5f0f",
        "service:002:property:002:valuelist:000": "\u76f4\u5439\u98ce",
        "service:002:property:002:valuelist:001": "\u81ea\u7136\u98ce",
        "service:002:property:003": "\u5de6\u53f3\u6446\u98ce",
        "service:002:action:001": "\u5f00\u5173\u72b6\u6001\u5207\u6362",
        "service:002:event:001": "\u7ae5\u9501\u89e6\u53d1",
    },
    # property:003 and valuelist:001 are deliberately missing: they must fall
    # back to the instance's own description
    "en": {
        "service:002:property:001": "Power",
        "service:002:property:002": "Fan Mode",
        "service:002:property:002:valuelist:000": "Direct Breeze",
        "service:002:action:001": "Toggle Power",
        "service:002:event:001": "Child Lock Triggered",
    },
}


def _offline(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"the spec must not be refetched: {request.url}")


@pytest.fixture()
def spec(profile):
    """A spec served from a cache that holds both zh_cn and en; any request fails."""
    store = SpecStore(profile, client=httpx.Client(transport=httpx.MockTransport(_offline)))
    path = store._cache_path(URN)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "urn": URN,
        "fetched_at": int(time.time()),
        "instance": INSTANCE,
        "translations": TRANSLATIONS,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    loaded = store.get(URN)
    assert path.read_bytes() == before  # the cache file is not rewritten
    return loaded


def test_spec_descriptions_are_english(spec):
    assert spec.find_property("on").description == "Power"
    mode = spec.find_property("mode")
    assert mode.description == "Fan Mode"
    assert mode.value_list[0].description == "Direct Breeze"
    assert spec.actions[0].description == "Toggle Power"
    assert spec.events[0].description == "Child Lock Triggered"
    assert format_value(mode, 0) == "Direct Breeze(0)"
    assert format_value(spec.find_property("on"), True) == "on"
    for item in [*spec.properties, *spec.actions, *spec.events]:
        assert not CJK.search(item.description)


def test_spec_falls_back_to_instance_description(spec):
    assert spec.find_property("horizontal-swing").description == "Horizontal Swing"
    assert spec.find_property("mode").value_list[1].description == "Natural Wind"


def test_enum_names_resolve_in_english(spec):
    mode = spec.find_property("fan.mode")
    assert spec.find_property("mode") is mode
    assert parse_value(mode, "Direct Breeze") == 0
    assert parse_value(mode, "natural wind") == 1
    assert enum_value(mode, "direct") == 0
    assert enum_value(mode, "natural") == 1


def test_chinese_input_aliases_are_gone(spec):
    power = spec.find_property("on")
    for word in ("\u5f00", "\u5173", "\u662f", "\u5426", "\u6253\u5f00", "\u5173\u95ed"):
        with pytest.raises(InvalidValue):
            parse_value(power, word)

    from mi_home_cli.core.semantic import NAMED_COLORS, parse_color

    assert all(name.isascii() for name in NAMED_COLORS)
    with pytest.raises(InvalidValue):
        parse_color("\u7ea2")


# ---- user data may still be non-ASCII ----------------------------------------

def test_non_ascii_device_name_still_resolves():
    name = "\u5ba2\u5385\u706f"  # a CJK device name, as users in China have them
    room = "\u5ba2\u5385"
    data = {
        "homes": [],
        "devices": {
            "1": {
                "did": "1", "name": name, "model": "m", "urn": "u", "online": True,
                "room_name": room,
            },
            "2": {"did": "2", "name": "Desk Lamp", "model": "m", "urn": "u", "online": True},
        },
    }
    registry = Registry(data)
    assert registry.resolve(name).did == "1"
    assert registry.resolve(name[-1]).did == "1"  # substring
    assert registry.resolve(f"{room}/{name}").did == "1"


# ---- the CLI itself ----------------------------------------------------------

def _run(args, config_dir, **env):
    full_env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE", "XDG_CONFIG_HOME")
    }
    full_env.update(
        MI_HOME_CONFIG_DIR=str(config_dir),
        PYTHONPATH=str(SRC),
        PYTHONIOENCODING="utf-8",
        COLUMNS="200",
        NO_COLOR="1",
        **env,
    )
    return subprocess.run(
        [sys.executable, "-m", "mi_home_cli.cli.app", *args],
        capture_output=True, text=True, encoding="utf-8", env=full_env, timeout=120,
    )


def test_output_does_not_depend_on_locale(tmp_path):
    english = _run(["--help"], tmp_path, LANG="en_GB.UTF-8")
    chinese = _run(["--help"], tmp_path, LANG="zh_CN.UTF-8", LC_ALL="zh_CN.UTF-8")
    assert english.returncode == chinese.returncode == 0
    assert english.stdout == chinese.stdout
    assert "Control Xiaomi Home" in english.stdout
    assert not CJK.search(english.stdout)

    keys_en = _run(["-o", "json", "config", "list"], tmp_path, LANG="en_GB.UTF-8")
    keys_zh = _run(["-o", "json", "config", "list"], tmp_path, LANG="zh_CN.UTF-8")
    assert keys_en.stdout == keys_zh.stdout
    assert set(json.loads(keys_en.stdout)[0]) == {"Key", "Value", "Description"}


def test_not_logged_in_exit_code_and_message(tmp_path):
    result = _run(["auth", "status"], tmp_path)
    assert result.returncode == 10
    assert "Profile `default` is not logged in" in result.stderr
    assert "Hint: Run `mi auth login` to log in again" in result.stderr


def test_lang_is_not_a_config_key(tmp_path):
    result = _run(["config", "set", "lang", "en"], tmp_path)
    assert result.returncode == 2
    assert "Unknown config key `lang`" in result.stderr
    assert not (tmp_path / "config.json").exists()


def test_leftover_lang_in_config_is_harmless(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"lang": "zh", "output": "json"}))
    listed = _run(["config", "list"], tmp_path)
    assert listed.returncode == 0, listed.stderr
    rows = json.loads(listed.stdout)
    assert "lang" not in {row["Key"] for row in rows}
    assert _run(["--help"], tmp_path).returncode == 0
    assert _run(["auth", "status"], tmp_path).returncode == 10
