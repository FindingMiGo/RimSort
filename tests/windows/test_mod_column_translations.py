from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QApplication

from app.windows.base_mods_panel import BaseModsPanel
from app.windows.missing_mods_panel import MissingModsPrompt


@pytest.fixture
def japanese_columns(qapp: QApplication) -> Iterator[list[str]]:
    translator = QTranslator()
    catalog = Path(__file__).parents[2] / "locales" / "ja_JP.qm"
    assert translator.load(str(catalog))
    qapp.installTranslator(translator)
    columns = [
        "名前",
        "作者",
        "パッケージID",
        "公開ファイルID",
        "対応バージョン",
        "MODダウンロード日時",
        "Workshop更新日時",
        "入手元",
        "パス",
        "Workshopページ",
    ]
    try:
        yield columns
    finally:
        qapp.removeTranslator(translator)


def test_inherited_columns_use_base_translation_context(
    japanese_columns: list[str],
) -> None:
    panel = MissingModsPrompt.__new__(MissingModsPrompt)
    assert panel._get_standard_mod_columns() == japanese_columns


def test_missing_mod_columns_are_translated(japanese_columns: list[str]) -> None:
    # Stop at the base constructor, before metadata loading or showing a window.
    with (
        patch.object(
            BaseModsPanel, "__init__", side_effect=RuntimeError("stop")
        ) as init,
        pytest.raises(RuntimeError, match="stop"),
    ):
        MissingModsPrompt([], MagicMock())
    columns = init.call_args.kwargs["additional_columns"]
    assert columns[:3] == [japanese_columns[i] for i in (0, 2, 4)]
    assert columns[4:] == [japanese_columns[i] for i in (3, 9)]
