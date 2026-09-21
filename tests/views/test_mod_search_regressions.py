"""Search changes must be applied to both mod lists immediately."""

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from app.models.metadata.metadata_structure import AboutXmlMod, CaseInsensitiveStr
from app.models.settings import Settings
from app.utils.custom_list_widget_item import CustomListWidgetItem
from app.utils.custom_list_widget_item_metadata import CustomListWidgetItemMetadata
from app.views.mods_panel import ModsPanel


@pytest.fixture(params=["Active", "Inactive"])
def search_case(
    request: pytest.FixtureRequest, qtbot: QtBot
) -> tuple[ModsPanel, str, list[CustomListWidgetItem]]:
    settings = Settings()
    settings.include_mod_notes_in_mod_name_filter = False
    metadata = MagicMock()
    metadata.mods_metadata = {}
    for name, author, pfid in (
        ("Alpha", "Beta", "111"),
        ("Beta", "Alpha", "222"),
        ("Gamma", "Other", None),
    ):
        mod = AboutXmlMod(
            name=name,
            authors=[author],
            package_id=CaseInsensitiveStr(name.lower()),
            supported_versions={"1.6"},
        )
        mod.__dict__["published_file_id"] = pfid
        metadata.mods_metadata[f"/synthetic/{name}"] = mod
    metadata.get_mod.side_effect = metadata.mods_metadata.get
    panel = ModsPanel(settings, metadata)
    qtbot.addWidget(panel)
    list_type = str(request.param)
    mod_list = (
        panel.active_mods_list if list_type == "Active" else panel.inactive_mods_list
    )
    mod_list.check_widgets_visible = MagicMock()  # type: ignore[method-assign]
    items = []
    for path in metadata.mods_metadata:
        data = object.__new__(CustomListWidgetItemMetadata)
        data.__dict__.update(path=path, filtered=False, invalid=False, mod_tags=[])
        item = CustomListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, data, avoid_emit=True)
        mod_list.addItem(item)
        items.append(item)
    mod_list.paths = list(metadata.mods_metadata)
    return panel, list_type, items


def test_workshop_id_search_and_clear(
    search_case: tuple[ModsPanel, str, list[CustomListWidgetItem]],
) -> None:
    panel, list_type, items = search_case
    selector = (
        panel.active_mods_search_filter
        if list_type == "Active"
        else panel.inactive_mods_search_filter
    )
    selector.setCurrentText(panel.tr("PublishedFileId"))
    for query, hidden in (
        ("111", [False, True, True]),
        ("22", [True, False, True]),
        ("999", [True, True, True]),
        ("", [False, False, False]),
    ):
        panel.signal_search_and_filters(list_type, query)
        assert [item.isHidden() for item in items] == hidden


def test_changing_search_field_reapplies_current_text(
    search_case: tuple[ModsPanel, str, list[CustomListWidgetItem]],
) -> None:
    panel, list_type, items = search_case
    selector = getattr(panel, f"{list_type.lower()}_mods_search_filter")
    search = getattr(panel, f"{list_type.lower()}_mods_search")
    search.setText("Alpha")
    assert [item.isHidden() for item in items] == [False, True, True]
    selector.setCurrentText(panel.tr("Author(s)"))
    assert [item.isHidden() for item in items] == [True, False, True]
    selector.setCurrentText(panel.tr("PublishedFileId"))
    assert all(item.isHidden() for item in items)
    search.clear()
    assert not any(item.isHidden() for item in items)


@pytest.mark.parametrize("field", ["Name", "Author(s)", "PackageId", "Version"])
def test_highlight_search_recomputes_matches_and_clear(
    search_case: tuple[ModsPanel, str, list[CustomListWidgetItem]], field: str
) -> None:
    panel, list_type, items = search_case
    setattr(panel, f"{list_type.lower()}_mods_search_filter_state", False)
    selector = getattr(panel, f"{list_type.lower()}_mods_search_filter")
    selector.setCurrentText(panel.tr(field))
    for query, expected in (
        ("missing", [True] * 3),
        (
            "1.6" if field == "Version" else "Alpha",
            [False] * 3
            if field == "Version"
            else [True, False, True]
            if field == "Author(s)"
            else [False, True, True],
        ),
        ("", [False] * 3),
    ):
        panel.signal_search_and_filters(list_type, query)
        assert [
            item.data(Qt.ItemDataRole.UserRole)["filtered"] for item in items
        ] == expected
        assert not any(item.isHidden() for item in items)


def test_highlight_recomputes_source_and_tag_filters(
    search_case: tuple[ModsPanel, str, list[CustomListWidgetItem]],
) -> None:
    panel, list_type, items = search_case
    setattr(panel, f"{list_type.lower()}_mods_search_filter_state", False)
    filters = getattr(panel, f"{list_type.lower()}_filter_button").filter_panel
    filters._source_checkboxes["local"].setChecked(False)
    assert all(item.data(Qt.ItemDataRole.UserRole)["filtered"] for item in items)
    filters._source_checkboxes["local"].setChecked(True)
    assert not any(item.data(Qt.ItemDataRole.UserRole)["filtered"] for item in items)
    items[0].data(Qt.ItemDataRole.UserRole)["mod_tags"] = ["keep"]
    filters.set_available_tags(["keep"])
    filters._tag_chips["keep"].set_active(True)
    filters.filters_changed.emit()
    panel.signal_search_and_filters(list_type, "missing")
    panel.signal_search_and_filters(list_type, "")
    assert [item.data(Qt.ItemDataRole.UserRole)["filtered"] for item in items] == [
        False,
        True,
        True,
    ]
    filters.clear()
    assert not any(item.data(Qt.ItemDataRole.UserRole)["filtered"] for item in items)
