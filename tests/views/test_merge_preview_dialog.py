from typing import Any
from unittest.mock import MagicMock

from app.views.merge_preview_dialog import MergePreviewDialog


def test_merge_preview_sections_and_button(qtbot: Any) -> None:
    controller = MagicMock()
    controller.get_mod.return_value.name = "Example Mod"
    controller.get_mod.return_value.package_id = "author.example"
    dialog = MergePreviewDialog(
        new_mods=["uuid-a"],
        already_present=["uuid-b"],
        missing_packageids=["missing.mod"],
        metadata_controller=controller,
    )
    qtbot.addWidget(dialog)
    assert dialog.new_section.list_widget.count() == 1
    assert dialog.already_present_section.list_widget.count() == 1
    assert dialog.missing_section.list_widget.count() == 1
    assert dialog.merge_button.isEnabled()


def test_merge_button_disabled_without_new_mods(qtbot: Any) -> None:
    dialog = MergePreviewDialog(
        new_mods=[],
        already_present=[],
        missing_packageids=[],
        metadata_controller=MagicMock(),
    )
    qtbot.addWidget(dialog)
    assert not dialog.merge_button.isEnabled()
    assert dialog.missing_section.isHidden()
