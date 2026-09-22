from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QDialog, QWidget

from app.services.mod_list_parser import ParsedModList
from app.views.main_content_panel import MainContent
from app.views.merge_preview_dialog import MergePreviewDialog


@contextmanager
def patch_merge_inputs(
    imported_active: list[str],
    result: QDialog.DialogCode = QDialog.DialogCode.Accepted,
) -> Generator[None]:
    parsed = ParsedModList(
        package_ids=["author.mod"],
        game_version=None,
        known_expansions=[],
        source_format="mods_config_xml",
    )
    with (
        patch(
            "app.views.main_content_panel.dialogue.show_dialogue_file",
            return_value="/fake/mods.xml",
        ),
        patch("app.views.main_content_panel.parse_mod_list_file", return_value=parsed),
        patch.object(MergePreviewDialog, "exec", return_value=result),
    ):
        yield


def make_main_content() -> MagicMock:
    content = MagicMock()
    content.mods_panel.active_mods_list.paths = ["uuid-a", "uuid-b"]
    content.metadata_controller.get_mods_from_list.return_value = (
        ["uuid-b", "uuid-c"],
        [],
        {},
        [],
    )
    content.metadata_controller.mods_metadata = {
        "uuid-a": MagicMock(),
        "uuid-b": MagicMock(),
        "uuid-c": MagicMock(),
    }
    content.main_layout_frame = QWidget()
    return content


def test_merge_appends_new_mods_and_sorts(qtbot: Any) -> None:
    content = make_main_content()
    qtbot.addWidget(content.main_layout_frame)
    with patch_merge_inputs(["uuid-b", "uuid-c"]):
        MainContent._do_merge_list_file_xml(content)
    content._insert_data_into_lists.assert_called_once_with(
        ["uuid-a", "uuid-b", "uuid-c"], []
    )
    content._do_sort.assert_called_once()


def test_merge_preview_cancel_keeps_lists_unchanged(qtbot: Any) -> None:
    content = make_main_content()
    qtbot.addWidget(content.main_layout_frame)
    with patch_merge_inputs(["uuid-c"], result=QDialog.DialogCode.Rejected):
        MainContent._do_merge_list_file_xml(content)
    content._insert_data_into_lists.assert_not_called()
    content._do_sort.assert_not_called()
