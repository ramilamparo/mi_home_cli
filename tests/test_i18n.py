"""i18n 层：语言选择、英文目录的完整性、英文输出。"""
import ast
import inspect
import json
import os
import re
import string
import subprocess
import sys
from pathlib import Path

import pytest

from mi_home_cli import i18n, render
from mi_home_cli.i18n import detect_lang, t
from mi_home_cli.i18n_en import CATALOG

SRC = Path(__file__).resolve().parents[1] / "src" / "mi_home_cli"
CJK = re.compile(r"[　-〿一-鿿＀-￯]")

# 不是界面文案、而是用来匹配用户输入 / spec 取值的中文数据，不需要译文
DATA_WORDS = {
    "红", "红色", "绿", "绿色", "蓝", "蓝色", "白", "白色", "黄", "黄色",
    "橙", "橙色", "紫", "紫色", "粉", "粉色", "青", "青色", "暖", "暖色",
    "上升", "下降", "暂停", "停止",
}


def _env(tmp_path, **extra):
    """一个不受本机配置和 locale 影响的环境。"""
    return {"MI_HOME_CONFIG_DIR": str(tmp_path), **extra}


# ---- 语言选择 ---------------------------------------------------------------

def test_mi_lang_wins_over_config_and_locale(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"lang": "zh"}))
    assert detect_lang(_env(tmp_path, MI_LANG="en", LANG="zh_CN.UTF-8")) == "en"
    assert detect_lang(_env(tmp_path, MI_LANG="zh", LANG="en_US.UTF-8")) == "zh"
    assert detect_lang(_env(tmp_path, MI_LANG="zh-CN", LANG="en_US.UTF-8")) == "zh"


def test_config_wins_over_locale(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"lang": "en"}))
    assert detect_lang(_env(tmp_path, LANG="zh_CN.UTF-8")) == "en"
    (tmp_path / "config.json").write_text(json.dumps({"lang": "zh"}))
    assert detect_lang(_env(tmp_path, LANG="en_US.UTF-8")) == "zh"


def test_invalid_mi_lang_and_config_are_ignored(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"lang": "klingon"}))
    assert detect_lang(_env(tmp_path, MI_LANG="fr", LANG="zh_CN.UTF-8")) == "zh"
    (tmp_path / "config.json").write_text("{not json")
    assert detect_lang(_env(tmp_path, LANG="zh_CN.UTF-8")) == "zh"


@pytest.mark.parametrize(
    "env, expected",
    [
        # 没设 MI_LANG、没有 lang 配置时由系统 locale 决定
        ({"LANG": "zh_CN.UTF-8"}, "zh"),
        ({"LANG": "zh_TW"}, "zh"),
        ({"LANG": "en_US.UTF-8"}, "en"),
        ({"LANG": "en_GB.UTF-8"}, "en"),
        ({"LANG": "ja_JP.UTF-8"}, "en"),
        ({"LANG": "C"}, "en"),
        ({"LANG": "POSIX"}, "en"),
        ({"LANG": "C.UTF-8"}, "en"),
        ({}, "en"),
        # POSIX 优先级：LC_ALL > LC_MESSAGES > LANG
        ({"LC_ALL": "zh_CN.UTF-8", "LC_MESSAGES": "en_US.UTF-8", "LANG": "en_US.UTF-8"}, "zh"),
        ({"LC_ALL": "en_US.UTF-8", "LC_MESSAGES": "zh_CN.UTF-8", "LANG": "zh_CN.UTF-8"}, "en"),
        ({"LC_ALL": "C", "LANG": "zh_CN.UTF-8"}, "en"),
        ({"LC_MESSAGES": "zh_CN.UTF-8", "LANG": "en_US.UTF-8"}, "zh"),
        ({"LC_MESSAGES": "en_US.UTF-8", "LANG": "zh_CN.UTF-8"}, "en"),
        # 空串等于没设，继续往下看
        ({"LC_ALL": "", "LC_MESSAGES": "", "LANG": "zh_CN.UTF-8"}, "zh"),
    ],
)
def test_locale_precedence(tmp_path, env, expected):
    assert detect_lang(_env(tmp_path, **env)) == expected


def test_config_dir_follows_xdg(tmp_path):
    root = tmp_path / "mi-home-cli"
    root.mkdir()
    (root / "config.json").write_text(json.dumps({"lang": "zh"}))
    env = {"XDG_CONFIG_HOME": str(tmp_path), "LANG": "en_US.UTF-8"}
    assert detect_lang(env) == "zh"


# ---- t() --------------------------------------------------------------------

def test_t_returns_source_in_chinese():
    assert t("未登录或登录已失效") == "未登录或登录已失效"
    assert t("未知配置项 `{key}`", key="x") == "未知配置项 `x`"


def test_t_translates_and_formats_in_english():
    i18n.set_lang("en")
    assert t("未登录或登录已失效") == "Not logged in, or the login has expired"
    assert t("未知配置项 `{key}`", key="x") == "Unknown config key `x`"
    assert t("偏差 {skew:.0f} 秒", skew=1.6) == "skew 2 s"


def test_t_falls_back_to_source_when_untranslated():
    i18n.set_lang("en")
    assert t("这句话没有译文 {x}", x=1) == "这句话没有译文 1"


def test_set_lang_rejects_unknown():
    with pytest.raises(ValueError):
        i18n.set_lang("fr")


# ---- 目录完整性 ----------------------------------------------------------------

def _source_messages() -> dict[str, str]:
    """包里所有界面文案：t("...") 的字面量，以及没包 t() 的中文常量（列名等）。"""
    found: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        if path.name.startswith("i18n"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                ):
                    skip.add(body[0].value)  # docstring
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "t"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                found.setdefault(node.args[0].value, f"{path.name}:{node.lineno}")
                skip.add(node.args[0])
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node not in skip
                and CJK.search(node.value)
                and node.value not in DATA_WORDS
            ):
                found.setdefault(node.value, f"{path.name}:{node.lineno}")
    return found


def _command_docs() -> dict[str, str]:
    from mi_home_cli.cli.app import app

    found: dict[str, str] = {}

    def walk(typer_app) -> None:
        for command in typer_app.registered_commands:
            doc = getattr(command.callback, "__doc__", None)
            if doc and (command.help is None or CJK.search(str(command.help))):
                found.setdefault(inspect.cleandoc(doc), command.callback.__name__)
        for group in typer_app.registered_groups:
            walk(group.typer_instance)

    walk(app)
    return found


def _fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def test_every_message_has_an_english_translation():
    messages = {**_source_messages(), **_command_docs()}
    assert len(messages) > 400
    missing = {where: text for text, where in messages.items() if text not in CATALOG}
    assert not missing, f"missing English translations: {missing}"


def test_translations_are_english_and_keep_placeholders():
    for source, english in CATALOG.items():
        assert not CJK.search(english), f"CJK left in translation of {source!r}"
        if "{" in source:
            assert _fields(source) == _fields(english), source


def test_catalog_has_no_stale_entries():
    messages = {**_source_messages(), **_command_docs()}
    stale = [key for key in CATALOG if key not in messages]
    assert not stale, f"catalog entries no longer used: {stale}"


# ---- 输出 -------------------------------------------------------------------

def test_output_keys_follow_language(capsys):
    rows = [{"检查项": "x", "结果": "OK", "说明": "y", "id": 1}]
    render.output(rows, render.OutputFormat.json)
    assert json.loads(capsys.readouterr().out) == rows

    i18n.set_lang("en")
    render.output(rows, render.OutputFormat.json, columns=["检查项", "结果", "说明"])
    assert json.loads(capsys.readouterr().out) == [
        {"Check": "x", "Result": "OK", "Description": "y", "id": 1}
    ]
    # 调用方手里的行不能被改掉：命令里还要按中文键取值
    assert "检查项" in rows[0]


def test_error_messages_in_english():
    from mi_home_cli.core.spec import Property, parse_value
    from mi_home_cli.errors import InvalidValue

    prop = Property(
        siid=2, piid=1, service="light", name="on", description="Switch",
        format="bool", access=["read", "write"],
    )
    i18n.set_lang("en")
    with pytest.raises(InvalidValue) as caught:
        parse_value(prop, "maybe")
    assert not CJK.search(caught.value.message + (caught.value.hint or ""))
    assert "boolean" in caught.value.message


def _run(args, tmp_path, **env):
    full_env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("MI_LANG", "LC_ALL", "LC_MESSAGES", "LANG", "XDG_CONFIG_HOME")
    }
    full_env.update(
        MI_HOME_CONFIG_DIR=str(tmp_path),
        PYTHONPATH=str(SRC.parent),
        PYTHONIOENCODING="utf-8",
        COLUMNS="200",
        NO_COLOR="1",
        **env,
    )
    return subprocess.run(
        [sys.executable, "-m", "mi_home_cli.cli.app", *args],
        capture_output=True, text=True, encoding="utf-8", env=full_env, timeout=120,
    )


@pytest.mark.parametrize(
    "args",
    [
        ["--help"], ["auth", "--help"], ["auth", "login", "--help"],
        ["device", "--help"], ["device", "list", "--help"], ["home", "--help"],
        ["config", "--help"], ["lan", "--help"], ["spec", "--help"],
        ["get", "--help"], ["set", "--help"], ["watch", "--help"],
        ["light", "--help"], ["cover", "--help"], ["profile", "--help"],
    ],
)
def test_help_is_english(tmp_path, args):
    result = _run(args, tmp_path, MI_LANG="en")
    assert result.returncode == 0, result.stderr
    assert not CJK.search(result.stdout), result.stdout


def test_help_language_follows_locale(tmp_path):
    english = _run(["--help"], tmp_path, LANG="en_US.UTF-8")
    assert "Control Xiaomi Home" in english.stdout
    assert not CJK.search(english.stdout)

    chinese = _run(["--help"], tmp_path, LANG="zh_CN.UTF-8")
    assert "命令行控制米家设备" in chinese.stdout
    assert "登录与凭据管理" in chinese.stdout

    unset = _run(["--help"], tmp_path)
    assert "Control Xiaomi Home" in unset.stdout

    # LC_ALL 压过 LANG
    forced = _run(["--help"], tmp_path, LC_ALL="zh_CN.UTF-8", LANG="en_US.UTF-8")
    assert "命令行控制米家设备" in forced.stdout


def test_auth_status_not_logged_in_english(tmp_path):
    result = _run(["auth", "status"], tmp_path, MI_LANG="en")
    assert result.returncode == 10
    assert "is not logged in" in result.stderr
    assert "Hint: Run `mi auth login` to log in again" in result.stderr
    assert not CJK.search(result.stderr)


def test_config_lang_roundtrip(tmp_path):
    result = _run(["config", "set", "lang", "EN"], tmp_path, MI_LANG="zh")
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "config.json").read_text())["lang"] == "en"

    # 之后不设 MI_LANG，配置里的 lang 压过 locale
    listed = _run(["config", "list", "-o", "json"], tmp_path, LANG="zh_CN.UTF-8")
    assert listed.returncode == 0, listed.stderr
    rows = json.loads(listed.stdout)
    assert {"Key", "Value", "Description"} <= set(rows[0])
    assert any(row["Key"] == "lang" and row["Value"] == "en" for row in rows)

    bad = _run(["config", "set", "lang", "fr"], tmp_path, MI_LANG="en")
    assert bad.returncode == 2
    assert "Unknown language `fr`" in bad.stderr
