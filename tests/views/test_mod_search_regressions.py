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
