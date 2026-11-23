import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# 现有用例断言的是中文文案，而 typer 的 help 在 import 时就按当前语言求值了，
# 所以在 import 包之前就把语言钉成中文；英文相关的用例见 test_i18n.py。
os.environ["MI_LANG"] = "zh"

from mi_home_cli.store import Profile  # noqa: E402


@pytest.fixture()
def profile(tmp_path: Path) -> Profile:
    return Profile("default", root=tmp_path)


@pytest.fixture(autouse=True)
def _pin_lang():
    """每个用例都从中文开始，用例里切过语言也不会漏到下一个。"""
    from mi_home_cli import i18n

    i18n.set_lang("zh")
    yield
    i18n.set_lang("zh")
