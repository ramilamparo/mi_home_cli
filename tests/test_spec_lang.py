"""spec 描述的语言跟着界面语言走（数据来自同一份缓存，不重新拉取）。"""
import json
import time

import httpx
import pytest

from mi_home_cli import i18n, render
from mi_home_cli.core.semantic import enum_value
from mi_home_cli.core.spec import SpecStore, format_value, parse_value, spec_lang

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
    "zh_cn": {
        "service:002:property:001": "开关",
        "service:002:property:002": "模式",
        "service:002:property:002:valuelist:000": "直吹风",
        "service:002:property:002:valuelist:001": "自然风",
        "service:002:property:003": "左右摆风",
        "service:002:action:001": "开关状态切换",
        "service:002:event:001": "童锁触发",
    },
    # 故意缺了 property:003 和 valuelist:001：要退回 instance 自带的英文描述
    "en": {
        "service:002:property:001": "Power",
        "service:002:property:002": "Fan Mode",
        "service:002:property:002:valuelist:000": "Direct Breeze",
        "service:002:action:001": "Toggle Power",
        "service:002:event:001": "Child Lock Triggered",
    },
}


def _offline(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"spec 不该重新拉取：{request.url}")


@pytest.fixture()
def store(profile):
    """缓存里放一份带 zh_cn 和 en 的 spec；任何网络请求都算失败。"""
    made = SpecStore(profile, client=httpx.Client(transport=httpx.MockTransport(_offline)))
    path = made._cache_path(URN)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "urn": URN,
                "fetched_at": int(time.time()),
                "instance": INSTANCE,
                "translations": TRANSLATIONS,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    made.close()

    def build() -> SpecStore:
        return SpecStore(
            profile, client=httpx.Client(transport=httpx.MockTransport(_offline))
        )

    return build


def test_spec_lang_follows_ui_language():
    assert spec_lang() == "zh_cn"
    i18n.set_lang("en")
    assert spec_lang() == "en"


def test_explicit_lang_still_wins(store, profile):
    i18n.set_lang("en")
    explicit = SpecStore(
        profile,
        lang="zh_cn",
        client=httpx.Client(transport=httpx.MockTransport(_offline)),
    )
    assert explicit.get(URN).find_property("mode").description == "模式"


def test_chinese_ui_keeps_chinese_descriptions(store):
    spec = store().get(URN)
    assert spec.find_property("on").description == "开关"
    mode = spec.find_property("mode")
    assert mode.description == "模式"
    assert [item.description for item in mode.value_list] == ["直吹风", "自然风"]
    assert spec.find_property("horizontal-swing").description == "左右摆风"
    assert spec.actions[0].description == "开关状态切换"
    assert spec.events[0].description == "童锁触发"
    assert format_value(mode, 0) == "直吹风(0)"


def test_english_ui_gets_english_descriptions(store):
    i18n.set_lang("en")
    spec = store().get(URN)
    assert spec.find_property("on").description == "Power"
    mode = spec.find_property("mode")
    assert mode.description == "Fan Mode"
    assert mode.value_list[0].description == "Direct Breeze"
    assert spec.actions[0].description == "Toggle Power"
    assert spec.events[0].description == "Child Lock Triggered"
    assert format_value(mode, 0) == "Direct Breeze(0)"
    assert format_value(spec.find_property("on"), True) == "on"


def test_english_ui_falls_back_to_instance_description(store):
    i18n.set_lang("en")
    spec = store().get(URN)
    # 这两条 en 里没有，用 instance 自带的英文，而不是中文翻译
    assert spec.find_property("horizontal-swing").description == "Horizontal Swing"
    assert spec.find_property("mode").value_list[1].description == "Natural Wind"


def test_names_resolve_in_the_ui_language(store):
    # 中文界面：按中文描述写枚举值
    spec = store().get(URN)
    mode = spec.find_property("fan.mode")
    assert parse_value(mode, "直吹风") == 0
    assert parse_value(mode, "自然风") == 1
    assert enum_value(mode, "直吹") == 0

    # 英文界面：按英文描述写，属性引用方式不变
    i18n.set_lang("en")
    spec = store().get(URN)
    mode = spec.find_property("fan.mode")
    assert spec.find_property("mode") is mode
    assert parse_value(mode, "Direct Breeze") == 0
    assert parse_value(mode, "natural wind") == 1
    assert enum_value(mode, "direct") == 0
    assert enum_value(mode, "natural") == 1


def test_same_cache_file_serves_both_languages(store):
    path = store()._cache_path(URN)
    before = path.read_bytes()
    assert store().get(URN).find_property("on").description == "开关"
    i18n.set_lang("en")
    assert store().get(URN).find_property("on").description == "Power"
    assert path.read_bytes() == before


# ---- 输出键：只翻译列名，不翻译数据 ---------------------------------------------

def test_data_keys_are_not_translated(capsys):
    # "模式" "开" "设备" 都在英文目录里（帮助文案 / 列名），但这里它们是数据
    data = {"模式": "日光(2)", "开": "on", "设备": "x"}
    i18n.set_lang("en")
    render.output(data, render.OutputFormat.json, data_keys=True)
    assert json.loads(capsys.readouterr().out) == data

    # 没标记的 dict 仍按列名翻译
    render.output({"设备": "x"}, render.OutputFormat.json)
    assert json.loads(capsys.readouterr().out) == {"Device": "x"}


def test_data_keys_unchanged_in_chinese(capsys):
    data = {"模式": "日光(2)", "设备": "x"}
    render.output(data, render.OutputFormat.json, data_keys=True)
    assert json.loads(capsys.readouterr().out) == data
    render.output(data, render.OutputFormat.json)
    assert json.loads(capsys.readouterr().out) == data


def test_status_view_keeps_spec_descriptions_as_keys(store, profile, monkeypatch, capsys):
    """`mi light/fan <设备>` 的状态视图以 spec 描述为键，不能被当成列名翻译。"""
    from types import SimpleNamespace

    from mi_home_cli.cli import semantic as semantic_cli

    # 显式取中文描述：其中 "模式" 同时是英文目录里的键
    spec = SpecStore(
        profile,
        lang="zh_cn",
        client=httpx.Client(transport=httpx.MockTransport(_offline)),
    ).get(URN)

    class FakeChannel:
        def get_props(self, params):
            values = {1: True, 2: 0, 3: False}
            return [{**p, "code": 0, "value": values[p["piid"]]} for p in params]

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    app_ctx = SimpleNamespace(
        session=lambda: FakeSession(), output=render.OutputFormat.json
    )
    device = SimpleNamespace(did="1", label="fan", location="room")
    monkeypatch.setattr(semantic_cli, "_channel", lambda *a, **k: FakeChannel())

    i18n.set_lang("en")
    semantic_cli._show_status(app_ctx, device, spec, "fan", None)
    shown = json.loads(capsys.readouterr().out)
    assert "模式" in shown and "Mode" not in shown
    assert shown["模式"] == "直吹风(0)"
