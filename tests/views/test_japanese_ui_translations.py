from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QApplication, QLabel, QMenu

from app.views.deletion_menu import ModDeletionMenu
from app.views.mod_info_panel import ModInfoPanel
from app.windows.missing_mod_properties_panel import MissingModPropertiesPanel


@pytest.fixture(autouse=True)
def japanese_catalog(qapp: QApplication) -> Iterator[None]:
    translator = QTranslator()
    assert translator.load(str(Path(__file__).parents[2] / "locales" / "ja_JP.qm"))
    qapp.installTranslator(translator)
    try:
        yield
    finally:
        qapp.removeTranslator(translator)


@pytest.mark.parametrize("count", [1, 3])
def test_deletion_confirmation_translates_before_inserting_count(count: int) -> None:
    menu = ModDeletionMenu.__new__(ModDeletionMenu)
    QMenu.__init__(menu)
    menu.get_selected_mod_metadata = lambda: [{}] * count
    with patch.object(menu, "_perform_deletion_operation") as perform:
        menu.delete_mod_completely()
    text = perform.call_args.kwargs["confirmation_text"]
    assert str(count) in text
    assert "削除" in text
    assert "selected" not in text
    assert "{" not in text


def test_missing_mod_warning_translates_before_inserting_mod_names() -> None:
    panel = MissingModPropertiesPanel.__new__(MissingModPropertiesPanel)
    with patch.object(panel, "_show_message") as message:
        panel._show_no_valid_packageids_warning(["Example Mod"])
    title, text, severity = message.call_args.args
    assert title == "追加できません"
    assert "パッケージID" in text
    assert "Example Mod" in text
    assert severity == "warning"


def test_mod_info_missing_timestamp_is_translated() -> None:
    panel = ModInfoPanel.__new__(ModInfoPanel)
    label = QLabel()
    panel._set_timestamp_info(None, label, "test")
    assert label.text() == "情報なし"
