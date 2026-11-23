"""界面文案的多语言支持（零依赖）。

源码里的中文原文就是消息 id：`t("中文原文", name=value)`。中文环境下原样返回，
英文环境下去 `i18n_en.CATALOG` 里查译文，查不到就退回中文原文。

语言的决定顺序：

1. 环境变量 `MI_LANG`（`en` / `zh`）
2. 配置文件里的 `lang`（`mi config set lang en`）
3. 系统 locale：`LC_ALL` > `LC_MESSAGES` > `LANG`，`zh*` 是中文，其余
   （包括没设、`C`、`POSIX`）都是英文

typer 的 help 文案在 import 时就求值了，所以语言在第一次调用 `t()` 时确定并缓存，
这个模块也不能依赖包里的其他模块（否则会循环 import）。
"""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any, Mapping

ENV_LANG = "MI_LANG"
LANGUAGES = ("zh", "en")
_LOCALE_VARS = ("LC_ALL", "LC_MESSAGES", "LANG")

_lang: str | None = None
_catalog: Mapping[str, str] | None = None


def normalize(value: Any) -> str | None:
    """把 `en_US.UTF-8` / `zh-CN` / `EN` 这类写法归一成 `en` / `zh`；不认识返回 None。"""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text.startswith("zh"):
        return "zh"
    if text.startswith("en"):
        return "en"
    return None


def _config_lang(environ: Mapping[str, str]) -> str | None:
    # 目录规则与 store.config_dir() 保持一致；这里不能 import store（循环依赖）。
    override = environ.get("MI_HOME_CONFIG_DIR")
    if override:
        root = Path(override).expanduser()
    elif environ.get("XDG_CONFIG_HOME"):
        root = Path(environ["XDG_CONFIG_HOME"]).expanduser() / "mi-home-cli"
    else:
        root = Path.home() / ".config" / "mi-home-cli"
    try:
        with (root / "config.json").open(encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, ValueError, RuntimeError):
        return None
    return normalize(data.get("lang")) if isinstance(data, dict) else None


def _locale_lang(environ: Mapping[str, str]) -> str:
    # POSIX 的优先级：第一个非空的变量说了算。
    for name in _LOCALE_VARS:
        value = environ.get(name)
        if value:
            return "zh" if value.strip().lower().startswith("zh") else "en"
    return "en"


def detect_lang(environ: Mapping[str, str] | None = None) -> str:
    """按 MI_LANG > 配置文件 > 系统 locale 的顺序决定语言。"""
    env = os.environ if environ is None else environ
    return (
        normalize(env.get(ENV_LANG))
        or _config_lang(env)
        or _locale_lang(env)
    )


def get_lang() -> str:
    global _lang
    if _lang is None:
        _lang = detect_lang()
    return _lang


def set_lang(lang: str | None) -> None:
    """强制指定语言；传 None 则下次调用时重新探测。主要给测试用。"""
    global _lang
    if lang is not None and lang not in LANGUAGES:
        raise ValueError(f"unsupported language: {lang}")
    _lang = lang


def _english() -> Mapping[str, str]:
    global _catalog
    if _catalog is None:
        from .i18n_en import CATALOG

        _catalog = CATALOG
    return _catalog


def t(message: str, /, **kwargs: Any) -> str:
    """翻译一条界面文案。带关键字参数时按 `str.format` 填进去。"""
    if get_lang() == "en":
        message = _english().get(message, message)
    return message.format(**kwargs) if kwargs else message


def localize_keys(data: Any) -> Any:
    """把输出行里的中文列名换成当前语言（只动最外层 dict / list[dict] 的键）。

    命令内部一律用中文列名当键，展示前再统一翻译，这样按键取值的逻辑不受语言影响。
    """
    if get_lang() == "zh":
        return data
    if isinstance(data, dict):
        return {t(key) if isinstance(key, str) else key: value for key, value in data.items()}
    if isinstance(data, list):
        return [
            {t(key) if isinstance(key, str) else key: value for key, value in row.items()}
            if isinstance(row, dict)
            else row
            for row in data
        ]
    return data


def localize_typer(app: Any) -> None:
    """命令的 help 取自函数 docstring，这里把它们换成当前语言。"""
    if get_lang() == "zh":
        return
    for command in app.registered_commands:
        doc = getattr(command.callback, "__doc__", None)
        if command.help is None and doc:
            command.help = t(inspect.cleandoc(doc))
    for group in app.registered_groups:
        if group.typer_instance is not None:
            localize_typer(group.typer_instance)
