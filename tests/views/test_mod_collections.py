"""Grouping uses the real mod-list signals without changing load order."""

from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QInputDialog, QLabel, QTreeWidgetItem
from pytestqt.qtbot import QtBot

from app.controllers.mod_collections_controller import ModCollectionsController
from app.controllers.mods_panel_controller import ModsPanelController
from app.models.instance import Instance
from app.models.metadata.metadata_structure import (
    AboutXmlMod,
    CaseInsensitiveStr,
    ModType,
)
from app.models.mod_collections import ModCollections
from app.models.settings import Settings
from app.sort.mod_sorting import ModsPanelSortKey
from app.utils.custom_list_widget_item import CustomListWidgetItem
from app.utils.custom_list_widget_item_metadata import CustomListWidgetItemMetadata
from app.utils.event_bus import EventBus
from app.views.mod_collections_panel import ModCollectionsPanel
from app.views.mods_panel import ModListItemInner, ModsPanel


@pytest.fixture
def collections_panel(qtbot: QtBot, fresh_event_bus: None) -> Iterator[ModsPanel]:
    settings = Settings()
    settings.show_save_comparison_indicators = False
    settings.mod_list_updated_indicator = False
    settings.mod_list_startup_impact = False
    metadata = MagicMock()
    metadata.settings = settings
    metadata.mods_metadata = {
        f"/synthetic/mod-{row}": AboutXmlMod(
            name=f"Mod {row}: 日本語 translation and additional content",
            package_id=CaseInsensitiveStr(f"example.mod{row}"),
            _mod_path=Path(f"/synthetic/mod-{row}"),
            _mod_type=ModType.LOCAL,
        )
        for row in range(4)
    }
    metadata.get_mod.side_effect = metadata.mods_metadata.get
    metadata.is_version_mismatch.return_value = False
    panel = ModsPanel(settings, metadata)
    qtbot.addWidget(panel)
    settings.save = MagicMock()  # type: ignore[method-assign]
    # Bypass the database-backed metadata constructor, keeping real Qt lists,
    # widgets, list-update signals and warning/count recalculation connected.
    for path in metadata.mods_metadata:
        data = object.__new__(CustomListWidgetItemMetadata)
        data.__dict__.update(
            path=path,
            errors_warnings="",
            errors="",
            warnings="",
            warning_toggled=False,
            filtered=False,
            hidden_by_filter=False,
            invalid=False,
            mismatch=False,
            alternative=False,
            mod_color=None,
            mod_tags=[],
            show_tags=False,
            list_type="Inactive",
        )
        item = CustomListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, data, avoid_emit=True)
        item.setData(Qt.ItemDataRole.SizeHintRole, QSize(600, 24), avoid_emit=True)
        panel.inactive_mods_list.addItem(item)
    QApplication.processEvents()
    yield panel
    panel._sort_debounce_timer.stop()
    panel.deleteLater()
    QApplication.processEvents()


def grouped_view(panel: ModsPanel) -> tuple[ModCollectionsPanel, str, list[str]]:
    view = panel.collections_panel
    controller = view.controller
    paths = list(controller.items(controller.inactive_list))
    key = controller.create("set", "Translations", paths[:2], [])
    return view, key, paths


def append_synthetic_mod(
    panel: ModsPanel, path: str, active: bool, index: int | None = None
) -> None:
    """Simulate the list insertion following a filesystem creation event."""
    source = panel.active_mods_list if active else panel.inactive_mods_list
    data = object.__new__(CustomListWidgetItemMetadata)
    data.__dict__.update(
        path=path,
        errors_warnings="",
        errors="",
        warnings="",
        warning_toggled=False,
        filtered=False,
        hidden_by_filter=False,
        invalid=False,
        mismatch=False,
        alternative=False,
        mod_color=None,
        mod_tags=[],
        show_tags=False,
        list_type=source.list_type,
    )
    item = CustomListWidgetItem()
    item.setData(Qt.ItemDataRole.UserRole, data, avoid_emit=True)
    item.setData(Qt.ItemDataRole.SizeHintRole, QSize(600, 24), avoid_emit=True)
    if index is None:
        source.addItem(item)
    else:
        source.insertItem(index, item)


def test_renamed_translation_folder_rebinds_saved_set_member() -> None:
    collections = ModCollections()
    key = collections.create("set", "[RH2] Faction: Militaires Sans Frontieres")
    base = r"C:\Steam\workshop\3207066520"
    old_translation = (
        "C:\\RimWorld\\Mods\\[RH2] Faction\uf03a Militaires Sans Frontieres JP"
    )
    translation = r"C:\RimWorld\Mods\[RH2] Faction_ Militaires Sans Frontieres JP"
    collections.sets[key].members = [base, old_translation]

    assert ModCollectionsController._repair_renamed_members(
        collections, {base, translation}
    )
    assert collections.sets[key].members == [base, translation]
    assert not ModCollectionsController._repair_renamed_members(
        collections, {base, translation}
    )


def test_renamed_member_does_not_steal_another_set_member() -> None:
    collections = ModCollections()
    old_key = collections.create("set", "Old set")
    other_key = collections.create("set", "Other set")
    old_path = "C:\\Mods\\[RH2] Faction\uf03a JP"
    new_path = r"C:\Mods\[RH2] Faction_ JP"
    collections.sets[old_key].members = [old_path]
    collections.sets[other_key].members = [new_path]

    assert not ModCollectionsController._repair_renamed_members(collections, {new_path})
    assert collections.sets[old_key].members == [old_path]


def first_group(view: ModCollectionsPanel) -> QTreeWidgetItem:
    node = view.tree.topLevelItem(0)
    assert node is not None
    return node


def test_drop_mod_onto_mod_creates_and_extends_set(
    collections_panel: ModsPanel,
) -> None:
    source = collections_panel.inactive_mods_list
    controller = collections_panel.collections_panel.controller
    paths = list(controller.items(source))
    original_order = list(source.paths)

    source.item(0).setSelected(True)
    assert source._request_set_from_drop(source.item(1))

    key = controller.collections.set_for(paths[1])
    assert key
    assert controller.collections.sets[key].name == controller.mod_name(paths[1])
    assert controller.collections.sets[key].members == [paths[1], paths[0]]
    assert original_order == paths
    parent = controller.items(source)[paths[1]]
    parent_data = parent.data(Qt.ItemDataRole.UserRole)
    assert parent_data["path"] == paths[1]
    assert parent_data.__dict__["collection_set_key"] == key
    assert parent_data.__dict__["collection_parent"]
    assert parent_data.__dict__["collection_collapsed"]
    assert source.item(0).isHidden()
    assert not source.item(1).isHidden()
    assert not source.item(2).isHidden()
    assert [path for path in source.paths if not path.startswith("__divider__")] == [
        paths[0],
        paths[1],
        paths[2],
        paths[3],
    ]

    collapsed_height = source.visualItemRect(parent).height()
    source.toggle_collection_set(key)
    assert source.item(0).isHidden()
    QApplication.processEvents()
    assert source.visualItemRect(parent).height() >= collapsed_height + 24
    parent_widget = source.itemWidget(source.item(1))
    assert isinstance(parent_widget, ModListItemInner)
    assert parent_widget.list_item_name == controller.mod_name(paths[1])
    assert not parent_widget.collection_children_widget.isHidden()
    assert parent_widget.collection_children_layout.count() == 1
    child_layout_item = parent_widget.collection_children_layout.itemAt(0)
    assert child_layout_item is not None
    child_label = child_layout_item.widget()
    assert isinstance(child_label, QLabel)
    assert child_label.text() == f"↳ #1 {controller.mod_name(paths[0])}"
    child_data = source.item(0).data(Qt.ItemDataRole.UserRole)
    child_data["warnings"] = "Load-order warning"
    child_data["errors_warnings"] = "Load-order warning"
    source.refresh_collection_summaries()
    refreshed_child = parent_widget.collection_children_layout.itemAt(0)
    assert refreshed_child is not None
    refreshed_label = refreshed_child.widget()
    assert isinstance(refreshed_label, QLabel)
    assert refreshed_label.text() == f"↳ #1 ⚠ {controller.mod_name(paths[0])}"
    assert refreshed_label.toolTip() == "Load-order warning"

    source.toggle_collection_set(key)
    QApplication.processEvents()
    assert source.visualItemRect(parent).height() == collapsed_height

    source.clearSelection()
    parent.setSelected(True)
    source.set_collection_enabled_signal.disconnect()
    move = QSignalSpy(source.set_collection_enabled_signal)
    source.mod_double_clicked(parent)
    assert move.count() == 1
    assert move.at(0) == [key, True]

    source.clearSelection()
    items = controller.items(source)
    items[paths[2]].setSelected(True)
    assert source._request_set_from_drop(items[paths[1]])
    assert controller.collections.sets[key].members == [paths[1], paths[0], paths[2]]


def test_drop_requires_a_different_selected_mod(collections_panel: ModsPanel) -> None:
    source = collections_panel.inactive_mods_list
    source.item(0).setSelected(True)
    assert not source._request_set_from_drop(source.item(0))


def test_adding_to_expanded_set_keeps_all_child_rows_visible(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    panel.show()
    view, key, paths = grouped_view(panel)
    source = view.controller.inactive_list
    source.toggle_collection_set(key)
    QApplication.processEvents()

    view.controller.assign([paths[2]], "set", key)
    QApplication.processEvents()

    parent = view.controller.items(source)[paths[0]]
    widget = source.itemWidget(parent)
    assert isinstance(widget, ModListItemInner)
    assert widget.collection_children_layout.count() == 2
    last_layout_item = widget.collection_children_layout.itemAt(1)
    assert last_layout_item is not None
    last_label = last_layout_item.widget()
    assert isinstance(last_label, QLabel)
    assert (
        last_label.mapTo(widget, last_label.rect().bottomLeft()).y() < widget.height()
    )


def test_adding_inactive_mod_to_active_set_shows_second_child(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    panel.show()
    view, key, paths = grouped_view(panel)
    controller = view.controller
    controller.set_enabled(paths[:2], True)
    QApplication.processEvents()
    active = controller.active_list
    active.toggle_collection_set(key)

    controller.assign([paths[2]], "set", key)
    QApplication.processEvents()

    assert paths[2] in controller.items(active)
    assert paths[2] not in controller.items(controller.inactive_list)
    assert active.paths == active.get_all_mod_paths()
    parent = controller.items(active)[paths[0]]
    widget = active.itemWidget(parent)
    assert isinstance(widget, ModListItemInner)
    assert widget.collection_children_layout.count() == 2
    last_layout_item = widget.collection_children_layout.itemAt(1)
    assert last_layout_item is not None
    last_label = last_layout_item.widget()
    assert isinstance(last_label, QLabel)
    assert controller.mod_name(paths[2]) in last_label.text()
    assert (
        last_label.mapTo(widget, last_label.rect().bottomLeft()).y() < widget.height()
    )


def test_adding_active_mod_to_inactive_set_disables_it(
    collections_panel: ModsPanel,
) -> None:
    view, key, paths = grouped_view(collections_panel)
    controller = view.controller
    controller.set_enabled([paths[2]], True)
    QApplication.processEvents()

    controller.assign([paths[2]], "set", key)
    QApplication.processEvents()

    assert paths[2] in controller.items(controller.inactive_list)
    assert paths[2] not in controller.items(controller.active_list)


def test_second_active_drop_keeps_first_set_child_visible(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    panel.show()
    controller = panel.collections_panel.controller
    paths = list(controller.items(controller.inactive_list))
    controller.set_enabled(paths[:3], True)
    QApplication.processEvents()
    active = controller.active_list
    items = controller.items(active)
    items[paths[1]].setSelected(True)
    assert active._request_set_from_drop(items[paths[0]])
    key = controller.collections.set_for(paths[0])
    active.toggle_collection_set(key)
    QApplication.processEvents()

    active.clearSelection()
    items[paths[2]].setSelected(True)
    assert active._request_set_from_drop(items[paths[0]])
    QApplication.processEvents()

    assert controller.collections.sets[key].members == paths[:3]
    parent = controller.items(active)[paths[0]]
    widget = active.itemWidget(parent)
    assert isinstance(widget, ModListItemInner)
    assert widget.collection_children_layout.count() == 2
    first = widget.collection_children_layout.itemAt(0)
    second = widget.collection_children_layout.itemAt(1)
    assert first is not None and second is not None
    first_label, second_label = first.widget(), second.widget()
    assert isinstance(first_label, QLabel) and isinstance(second_label, QLabel)
    assert controller.mod_name(paths[1]) in first_label.text()
    assert controller.mod_name(paths[2]) in second_label.text()


def test_second_active_drop_keeps_previously_selected_child_first(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    panel.show()
    controller = panel.collections_panel.controller
    paths = list(controller.items(controller.inactive_list))
    controller.set_enabled(paths[:3], True)
    QApplication.processEvents()
    active = controller.active_list
    items = controller.items(active)
    items[paths[2]].setSelected(True)
    assert active._request_set_from_drop(items[paths[0]])
    key = controller.collections.set_for(paths[0])
    active.toggle_collection_set(key)
    QApplication.processEvents()

    items[paths[1]].setSelected(True)
    drop = QSignalSpy(active.create_set_from_drop_signal)
    assert active._request_set_from_drop(items[paths[0]])
    assert drop.count() == 1
    assert drop.at(0) == [[paths[1]], paths[0]]
    QApplication.processEvents()

    assert controller.collections.sets[key].members == [
        paths[0],
        paths[2],
        paths[1],
    ]
    parent = controller.items(active)[paths[0]]
    widget = active.itemWidget(parent)
    assert isinstance(widget, ModListItemInner)
    assert widget.collection_children_layout.count() == 2
    first = widget.collection_children_layout.itemAt(0)
    second = widget.collection_children_layout.itemAt(1)
    assert first is not None and second is not None
    first_label, second_label = first.widget(), second.widget()
    assert isinstance(first_label, QLabel) and isinstance(second_label, QLabel)
    assert controller.mod_name(paths[2]) in first_label.text()
    assert controller.mod_name(paths[1]) in second_label.text()
    assert (
        second_label.mapTo(widget, second_label.rect().bottomLeft()).y()
        < widget.height()
    )


def test_active_set_survives_representative_deletion_and_recreation(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    controller = panel.collections_panel.controller
    paths = list(controller.items(controller.inactive_list))[:3]
    controller.set_enabled(paths, True)
    QApplication.processEvents()
    active = panel.active_mods_list
    items = controller.items(active)
    items[paths[1]].setSelected(True)
    items[paths[2]].setSelected(True)
    assert active._request_set_from_drop(items[paths[0]])
    QApplication.processEvents()
    key = controller.collections.set_for(paths[0])

    panel.on_mod_deleted(paths[0])
    QApplication.processEvents()
    fallback = controller.items(active)[paths[1]]
    assert fallback.data(Qt.ItemDataRole.UserRole).__dict__["collection_parent"]
    assert controller.items(active)[paths[2]].isHidden()

    with (
        patch.object(
            active,
            "append_new_item",
            side_effect=lambda path, index: append_synthetic_mod(
                panel, path, True, index
            ),
        ) as append_active,
        patch.object(panel.inactive_mods_list, "append_new_item") as append_inactive,
    ):
        panel.on_mod_created(paths[0])
        append_active.assert_called_once_with(paths[0], 0)
        append_inactive.assert_not_called()
    QApplication.processEvents()
    restored = controller.items(active)[paths[0]]
    assert restored.data(Qt.ItemDataRole.UserRole).__dict__["collection_parent"]
    assert controller.collections.sets[key].members == paths


def test_recreated_active_child_rejoins_set_and_new_mod_stays_inactive(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    controller = panel.collections_panel.controller
    paths = list(controller.items(controller.inactive_list))[:3]
    controller.set_enabled(paths, True)
    QApplication.processEvents()
    key = controller.create("set", "Paired", paths, [])
    panel.on_mod_deleted(paths[1])
    QApplication.processEvents()

    with (
        patch.object(
            panel.active_mods_list,
            "append_new_item",
            side_effect=lambda path, index: append_synthetic_mod(
                panel, path, True, index
            ),
        ) as append_active,
        patch.object(
            panel.inactive_mods_list,
            "append_new_item",
            side_effect=lambda path: append_synthetic_mod(panel, path, False),
        ) as append_inactive,
    ):
        panel.on_mod_created(paths[1])
        panel.on_mod_created("/synthetic/new")
        panel.on_mod_created(paths[1])
        append_active.assert_called_once_with(paths[1], 1)
        append_inactive.assert_called_once_with("/synthetic/new")
    QApplication.processEvents()
    assert list(controller.items(panel.active_mods_list)) == paths
    assert len(controller.items(panel.inactive_mods_list)) == 2
    assert controller.collections.sets[key].members == paths
    assert controller.items(panel.active_mods_list)[paths[1]].isHidden()


def test_recreated_child_follows_set_disabled_while_it_was_missing(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    controller = panel.collections_panel.controller
    paths = list(controller.items(controller.inactive_list))[:3]
    controller.set_enabled(paths, True)
    QApplication.processEvents()
    key = controller.create("set", "Paired", paths, [])
    panel.on_mod_deleted(paths[1])
    QApplication.processEvents()
    controller.set_enabled(controller.collections.members("set", key), False)
    QApplication.processEvents()

    with (
        patch.object(panel.active_mods_list, "append_new_item") as append_active,
        patch.object(
            panel.inactive_mods_list,
            "append_new_item",
            side_effect=lambda path: append_synthetic_mod(panel, path, False),
        ) as append_inactive,
    ):
        panel.on_mod_created(paths[1])
        append_active.assert_not_called()
        append_inactive.assert_called_once_with(paths[1])
    QApplication.processEvents()
    assert set(controller.items(panel.inactive_mods_list)) >= set(paths)


def test_expanding_unloaded_set_reserves_child_rows(
    collections_panel: ModsPanel,
) -> None:
    controller = collections_panel.collections_panel.controller
    source = controller.inactive_list
    paths = list(controller.items(source))
    key = controller.create("set", "Translations", paths[:3], [])
    parent = controller.items(source)[paths[0]]
    source._visible_widget_timer.stop()
    source._visible_widget_queue.clear()
    source.removeItemWidget(parent)
    assert source.itemWidget(parent) is None
    collapsed_height = parent.sizeHint().height()

    source.toggle_collection_set(key)
    assert parent.sizeHint().height() == collapsed_height + 48

    source.create_widget_for_item(parent)
    widget = source.itemWidget(parent)
    assert isinstance(widget, ModListItemInner)
    assert widget.collection_children_layout.count() == 2
    assert parent.sizeHint().height() == collapsed_height + 48


def test_deleting_set_clears_parent_toggle_and_child_indent(
    collections_panel: ModsPanel,
) -> None:
    view, key, paths = grouped_view(collections_panel)
    controller = view.controller
    source = controller.inactive_list
    source.toggle_collection_set(key)
    QApplication.processEvents()
    parent_widget = source.itemWidget(source.item(0))
    child_widget = source.itemWidget(source.item(1))
    assert isinstance(parent_widget, ModListItemInner)
    assert isinstance(child_widget, ModListItemInner)
    assert not parent_widget.collection_toggle_button.isHidden()
    assert not parent_widget.collection_children_widget.isHidden()
    assert source.item(1).isHidden()

    controller.delete("set", key)

    assert parent_widget.collection_toggle_button.isHidden()
    assert parent_widget._collection_set_key == ""
    assert parent_widget.collection_children_widget.isHidden()
    assert not source.item(1).isHidden()
    assert set(controller.items(source)) == set(paths)


def test_double_clicking_representative_activates_whole_set(
    collections_panel: ModsPanel,
) -> None:
    view, key, paths = grouped_view(collections_panel)
    controller = view.controller
    source = controller.inactive_list
    parent = source.item(0)

    source.mod_double_clicked(parent)
    QApplication.processEvents()

    assert controller.active_list.paths[:2] == controller.collections.members(
        "set", key
    )
    assert set(controller.items(source)) == set(paths[2:])


def test_drop_center_targets_mod_but_row_edges_reorder(
    collections_panel: ModsPanel,
) -> None:
    source = collections_panel.inactive_mods_list
    item = source.item(1)
    rect = source.visualItemRect(item)
    assert source._drop_position_is_on_item(item, rect.center())
    assert not source._drop_position_is_on_item(item, rect.topLeft())
    assert not source._drop_position_is_on_item(item, rect.bottomLeft())


def test_batch_activation_preserves_order_and_tree_membership(
    collections_panel: ModsPanel,
) -> None:
    view = collections_panel.collections_panel
    controller = view.controller
    paths = list(controller.items(controller.inactive_list))
    group = controller.collections.create("set", "Translations")
    folder = controller.collections.create("folder", "Series")
    controller.assign(paths[:2], "set", group)
    controller.assign([paths[0], paths[2]], "folder", folder)
    controller.set_enabled([paths[3], paths[0]], True)
    QApplication.processEvents()
    before = list(controller.items(controller.active_list))
    assert before == [paths[0], paths[3]]
    controller.set_enabled(controller.collections.members("folder", folder), True)
    QApplication.processEvents()
    assert set(controller.items(controller.active_list)) == set(before + paths[1:3])
    assert collections_panel.active_mods_label.text() == "Active [4]"
    assert collections_panel.inactive_mods_label.text() == "Inactive [0]"
    view.mode.setCurrentIndex(1)
    node = first_group(view)
    assert node.text(0) == "Series"
    assert node.text(1) == "3/3"
    set_node = node.child(0)
    assert set_node is not None
    assert set_node.text(0) == "Translations"
    member = set_node.child(1)
    assert member is not None
    assert member.text(2) == "#3"
    # An individual checkbox changes only that member.
    member.setCheckState(0, Qt.CheckState.Unchecked)
    QApplication.processEvents()
    assert paths[0] in controller.items(controller.active_list)
    assert paths[1] not in controller.items(controller.active_list)
    assert controller.collections.sets[group].members == paths[:2]
    view.active_only.setChecked(True)
    view.search.setText("Translations")
    QApplication.processEvents()
    # Filtering does not restrict a folder's batch operation.
    controller.set_enabled(controller.collections.members("folder", folder), False)
    QApplication.processEvents()
    assert list(controller.items(controller.active_list)) == [paths[3]]
    assert len(controller.items(controller.inactive_list)) == 3
    assert len(set(controller.items(controller.inactive_list))) == 3
    assert collections_panel.active_mods_label.text() == "Active [1]"
    assert collections_panel.inactive_mods_label.text() == "Inactive [3]"


def test_missing_members_and_organization_do_not_change_order(
    collections_panel: ModsPanel,
) -> None:
    view = collections_panel.collections_panel
    controller = view.controller
    source = controller.inactive_list
    original = list(controller.items(source))
    key = controller.collections.create("set", "Optional")
    controller.assign([original[0], "/missing"], "set", key)
    assert list(controller.items(source)) == original
    view.mode.setCurrentIndex(1)
    controller.set_enabled(controller.collections.members("set", key), True)
    QApplication.processEvents()
    node = first_group(view)
    assert node.text(1) == "1/2"
    missing = node.child(1)
    assert missing is not None
    assert missing.text(1) == "Not installed"
    assert not missing.flags() & Qt.ItemFlag.ItemIsUserCheckable
    controller.delete("set", key)
    assert list(controller.items(controller.active_list)) == original[:1]
    assert list(controller.items(source)) == original[1:]


def test_reordering_and_instance_switch_preserve_separate_groups(
    collections_panel: ModsPanel,
) -> None:
    view, key, paths = grouped_view(collections_panel)
    controller = view.controller
    controller.set_enabled(paths, True)
    QApplication.processEvents()
    active = controller.active_list
    item = active.item(0)
    active.paths.remove(paths[0])
    active.takeItem(0)
    active.addItem(item)
    QApplication.processEvents()
    view.mode.setCurrentIndex(1)
    node = first_group(view)
    member = node.child(0)
    assert member is not None
    assert member.text(2) == "#4"
    assert controller.collections.sets[key].members == paths[:2]
    previous = controller.settings.current_instance
    controller.settings.instances["another"] = Instance()
    controller.settings.current_instance = "another"
    EventBus().settings_have_changed.emit()
    QApplication.processEvents()
    assert controller.collections.sets == {}
    data = controller.items(active)[paths[0]].data(Qt.ItemDataRole.UserRole)
    assert data.__dict__.get("collection_name", "") == ""
    controller.settings.current_instance = previous
    EventBus().settings_have_changed.emit()
    QApplication.processEvents()
    assert controller.collections.sets[key].members == paths[:2]
    assert data.__dict__.get("collection_name", "") == ""


def test_empty_set_can_move_between_folders(collections_panel: ModsPanel) -> None:
    view = collections_panel.collections_panel
    controller = view.controller
    key = controller.collections.create("set", "Empty")
    folder = controller.collections.create("folder", "Folder")
    controller.move_set(key, folder)
    view.mode.setCurrentIndex(1)
    node = first_group(view)
    child = node.child(0)
    assert child is not None
    assert child.text(0) == "Empty"
    assert child.text(1) == "0/0"
    controller.move_set(key, "")
    assert view.tree.topLevelItemCount() == 3


def test_search_filters_existing_nodes_without_reloading_metadata(
    collections_panel: ModsPanel,
    qtbot: QtBot,
) -> None:
    view, _key, paths = grouped_view(collections_panel)
    controller = view.controller
    controller.set_enabled(paths[:1], True)
    QApplication.processEvents()
    view.mode.setCurrentIndex(1)
    node = first_group(view)
    member = node.child(1)
    assert member is not None
    node.setSelected(True)
    controller.refresh()
    node = first_group(view)
    member = node.child(1)
    assert member is not None
    metadata = collections_panel.metadata_controller
    get_mod = metadata.get_mod
    assert isinstance(get_mod, MagicMock)
    qtbot.waitUntil(
        lambda: (
            not collections_panel.active_mods_list._visible_widget_queue
            and not collections_panel.inactive_mods_list._visible_widget_queue
        ),
        timeout=1000,
    )
    get_mod.reset_mock()
    view.search.setText("translations")
    view.active_only.setChecked(True)
    QApplication.processEvents()
    assert view.tree.topLevelItem(0) is node
    assert node.child(1) is member
    assert node.isSelected()
    assert member.isHidden()
    assert node.text(1) == "1/2"
    get_mod.assert_not_called()
    view.search.clear()
    view.active_only.setChecked(False)
    QApplication.processEvents()
    assert view.tree.topLevelItem(0) is node
    assert not member.isHidden()
    assert node.isSelected()


def test_refresh_preserves_tree_selection_and_collapsed_groups(
    collections_panel: ModsPanel,
) -> None:
    view, key, _paths = grouped_view(collections_panel)
    controller = view.controller
    view.mode.setCurrentIndex(1)
    node = first_group(view)
    node.setExpanded(False)
    node.setSelected(True)
    controller.refresh()
    refreshed = view.tree.topLevelItem(0)
    assert refreshed is not None
    assert not refreshed.isExpanded()
    assert refreshed.isSelected()
    assert refreshed.data(0, Qt.ItemDataRole.UserRole) == ("set", key)


def test_group_operations_save_once_and_activation_does_not_save_settings(
    collections_panel: ModsPanel,
) -> None:
    controller = collections_panel.collections_panel.controller
    save = controller.settings.save
    assert isinstance(save, MagicMock)
    paths = list(controller.items(controller.inactive_list))
    key = controller.collections.create("set", "Set")
    folder = controller.collections.create("folder", "Folder")
    operations: tuple[Callable[[], None], ...] = (
        lambda: controller.assign(paths[:2], "set", key),
        lambda: controller.move_set(key, folder),
        lambda: controller.rename("set", key, "Renamed"),
        lambda: controller.assign(paths[2:3], "folder", folder),
        lambda: controller.detach(paths[2:3]),
        lambda: controller.delete("set", key),
        lambda: controller.delete("folder", folder),
    )
    for operation in operations:
        save.reset_mock()
        operation()
        save.assert_called_once_with()
        assert set(controller.items(controller.inactive_list)) == set(paths)
        assert controller.active_list.paths == []
    save.reset_mock()
    controller.set_enabled(paths[:2], True)
    QApplication.processEvents()
    controller.refresh()
    save.assert_not_called()


def test_split_set_preserves_independent_activation_order(
    collections_panel: ModsPanel,
) -> None:
    view, key, paths = grouped_view(collections_panel)
    controller = view.controller
    controller.set_enabled([paths[1]], True)
    QApplication.processEvents()
    active_child = controller.items(controller.active_list)[paths[1]]
    inactive_parent = controller.items(controller.inactive_list)[paths[0]]
    assert (
        active_child.data(Qt.ItemDataRole.UserRole).__dict__["collection_set_key"]
        == key
    )
    assert (
        inactive_parent.data(Qt.ItemDataRole.UserRole).__dict__["collection_set_key"]
        == key
    )
    controller.set_enabled([paths[0]], True)
    QApplication.processEvents()

    assert controller.active_list.paths[:2] == [paths[1], paths[0]]
    assert controller.collections.members("set", key) == paths[:2]


def test_set_rendering_keeps_load_order_warning_based_on_real_positions(
    collections_panel: ModsPanel,
) -> None:
    controller = collections_panel.collections_panel.controller
    source = controller.inactive_list
    paths = list(source.paths)
    first = controller.metadata.mods_metadata[paths[0]]
    second = controller.metadata.mods_metadata[paths[1]]
    assert isinstance(first, AboutXmlMod)
    assert isinstance(second, AboutXmlMod)
    first.about_rules.load_after.add(second.package_id)
    first.clear_cache()

    controller.create("set", str(second.name), [paths[1], paths[0]], [])

    assert source.paths == paths
    load_before, load_after = source._check_load_order_violations(
        first,
        {str(first.package_id): paths[0], str(second.package_id): paths[1]},
        source.paths.index(paths[0]),
    )
    assert load_before == set()
    assert load_after == {str(second.package_id)}


def test_name_search_reveals_matching_child_through_representative(
    collections_panel: ModsPanel,
) -> None:
    view, _key, paths = grouped_view(collections_panel)
    controller = view.controller
    source = controller.inactive_list
    panel = collections_panel
    panel.inactive_mods_search_filter.setCurrentText(panel.tr("Name"))

    panel.signal_search_and_filters("Inactive", "Mod 1")

    parent = controller.items(source)[paths[0]]
    child = controller.items(source)[paths[1]]
    assert not parent.isHidden()
    assert child.isHidden()
    parent_widget = source.itemWidget(parent)
    assert isinstance(parent_widget, ModListItemInner)
    assert not parent_widget.collection_children_widget.isHidden()
    child_layout_item = parent_widget.collection_children_layout.itemAt(0)
    assert child_layout_item is not None
    child_label = child_layout_item.widget()
    assert isinstance(child_label, QLabel)
    assert controller.mod_name(paths[1]) in child_label.text()

    panel.signal_search_and_filters("Inactive", "")

    assert not parent.isHidden()
    assert child.isHidden()
    assert parent_widget.collection_children_widget.isHidden()


def test_search_survives_set_creation(collections_panel: ModsPanel) -> None:
    panel = collections_panel
    panel.inactive_mods_search_filter.setCurrentText(panel.tr("Name"))
    panel.inactive_mods_search.setText("Mod 1")
    view, _key, paths = grouped_view(panel)
    source = view.controller.inactive_list
    parent = view.controller.items(source)[paths[0]]
    widget = source.itemWidget(parent)

    assert not parent.isHidden()
    assert isinstance(widget, ModListItemInner)
    assert widget.collection_children_layout.count() == 1
    child_layout_item = widget.collection_children_layout.itemAt(0)
    assert child_layout_item is not None
    child_label = child_layout_item.widget()
    assert isinstance(child_label, QLabel)
    assert view.controller.mod_name(paths[1]) in child_label.text()


def test_highlight_search_exposes_matching_set_child(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    view, _key, paths = grouped_view(panel)
    panel.inactive_mods_search_filter_state = False
    panel.inactive_mods_search_filter.setCurrentText(panel.tr("Name"))

    panel.signal_search_and_filters("Inactive", "Mod 1")

    parent = view.controller.items(view.controller.inactive_list)[paths[0]]
    widget = view.controller.inactive_list.itemWidget(parent)
    assert not parent.isHidden()
    assert isinstance(widget, ModListItemInner)
    assert widget.collection_children_layout.count() == 1


def test_count_does_not_treat_set_children_as_filtered(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    grouped_view(panel)

    panel.update_count("Inactive")

    assert panel.inactive_mods_label.text().endswith("[4]")


def test_error_filter_reveals_set_child_and_survives_search_change(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    view, _key, paths = grouped_view(panel)
    view.controller.set_enabled(paths[:2], True)
    QApplication.processEvents()
    source = panel.active_mods_list
    items = view.controller.items(source)
    child_data = items[paths[1]].data(Qt.ItemDataRole.UserRole)
    child_data["errors"] = "Dependency error"
    child_data["errors_warnings"] = "Dependency error"
    controller = ModsPanelController(panel, panel.settings)
    panel.errors_text.clicked.emit()

    parent = items[paths[0]]
    assert controller.errors_label_active
    assert source.summary_filter == "errors"
    assert not parent.isHidden()
    widget = source.itemWidget(parent)
    assert isinstance(widget, ModListItemInner)
    assert widget.collection_children_layout.count() == 1
    panel.update_count("Active")
    assert panel.active_mods_label.text().endswith("[1/2]")

    panel.active_mods_search.setText("Mod 1")
    assert controller.errors_label_active
    assert not parent.isHidden()
    panel.errors_text.clicked.emit()
    assert source.summary_filter is None


def test_debounced_sort_uses_live_paths(collections_panel: ModsPanel) -> None:
    panel = collections_panel
    source = panel.inactive_mods_list
    source.recreate_mod_list_and_sort = MagicMock()  # type: ignore[method-assign]
    panel._pending_sort_params = ("Inactive", panel._text_to_sort_key("Name"), False)
    source.paths = ["/synthetic/stale"]

    panel._execute_pending_sort()

    assert (
        source.recreate_mod_list_and_sort.call_args.args[1]
        == source.get_all_mod_paths()
    )


def test_folder_size_sort_cancels_pending_sort_and_reuses_running_worker(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    panel._pending_sort_params = ("Inactive", ModsPanelSortKey.MODNAME, False)
    panel._sort_debounce_timer.start(1000)
    index = panel.inactive_mods_sort_combobox.findData(ModsPanelSortKey.FOLDER_SIZE)
    assert index >= 0

    with (
        patch("app.views.mods_panel.QThread") as thread_type,
        patch("app.views.mods_panel.FolderSizeWorker"),
    ):
        panel.inactive_mods_sort_combobox.setCurrentIndex(index)
        panel.on_inactive_mods_sort_changed(
            panel.inactive_mods_sort_combobox.currentText()
        )
        assert not panel._sort_debounce_timer.isActive()
        assert panel._pending_sort_params is None
        thread_type.assert_called_once()

    if panel._size_progress_dialog is not None:
        panel._size_progress_dialog.close()
    panel._size_thread = None
    panel._size_worker = None
    QApplication.restoreOverrideCursor()


def test_folder_size_sort_restarts_after_mod_added_during_calculation(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    index = panel.inactive_mods_sort_combobox.findData(ModsPanelSortKey.FOLDER_SIZE)
    assert index >= 0

    with (
        patch("app.views.mods_panel.QThread") as thread_type,
        patch("app.views.mods_panel.FolderSizeWorker"),
    ):
        panel.inactive_mods_sort_combobox.setCurrentIndex(index)
        old_paths = panel._size_current_uuids.copy()
        append_synthetic_mod(panel, "/synthetic/arrived", False)
        panel._on_folder_size_finished(dict.fromkeys(old_paths, 1))
        QApplication.processEvents()
        assert thread_type.call_count == 2
        assert "/synthetic/arrived" in panel._size_current_uuids

    if panel._size_progress_dialog is not None:
        panel._size_progress_dialog.close()
    panel._size_thread = None
    panel._size_worker = None
    QApplication.restoreOverrideCursor()


def test_sort_preserves_divider_metadata(collections_panel: ModsPanel) -> None:
    source = collections_panel.inactive_mods_list
    source.add_divider(1, "Section")
    paths = source.get_all_mod_paths()
    dividers = source.get_dividers_data()

    with (
        patch("app.views.mods_panel.sort_paths", return_value=paths),
        patch.object(source, "recreate_mod_list") as rebuild,
        patch.object(source, "restore_dividers") as restore,
    ):
        source.recreate_mod_list_and_sort(
            "Inactive", paths, collections_panel._text_to_sort_key("Name")
        )

    rebuild.assert_called_once()
    restore.assert_called_once_with(dividers)


def test_folder_size_result_does_not_restore_removed_rows(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    source = panel.inactive_mods_list
    live_paths = source.paths.copy()
    panel._size_current_uuids = [*live_paths, "/synthetic/removed"]

    panel._on_folder_size_finished({path: 1 for path in panel._size_current_uuids})

    assert source.paths == live_paths
    assert source.count() == len(live_paths)


def test_create_group_uses_real_list_selection_and_saves_once(
    collections_panel: ModsPanel,
) -> None:
    view = collections_panel.collections_panel
    controller = view.controller
    paths = list(controller.items(controller.inactive_list))
    for path in paths[:2]:
        controller.items(controller.inactive_list)[path].setSelected(True)
    with patch.object(QInputDialog, "getText", return_value=(" Translations ", True)):
        view.create_group("set")
    group = next(iter(controller.collections.sets.values()))
    assert group.name == "Translations"
    assert group.members == paths[:2]
    save = controller.settings.save
    assert isinstance(save, MagicMock)
    save.assert_called_once_with()
    assert set(controller.items(controller.inactive_list)) == set(paths)
    assert controller.active_list.paths == []
    assert view.mode.currentIndex() == 1


def test_dividers_are_excluded_from_group_actions_and_load_positions(
    collections_panel: ModsPanel,
) -> None:
    view, key, paths = grouped_view(collections_panel)
    controller = view.controller
    controller.set_enabled(paths[:2], True)
    QApplication.processEvents()
    controller.active_list.add_divider(1, "Section")
    QApplication.processEvents()
    view.mode.setCurrentIndex(1)
    node = first_group(view)
    first = node.child(0)
    second = node.child(1)
    assert first is not None and second is not None
    assert first.text(2) == "#1"
    assert second.text(2) == "#2"
    controller.set_enabled(controller.collections.members("set", key), False)
    QApplication.processEvents()
    assert controller.items(controller.active_list) == {}
    assert controller.active_list.count() == 1
    assert len(controller.active_list.paths) == 1
    assert collections_panel.active_mods_label.text() == "Active [0]"


def test_batch_preserves_existing_list_update_state(
    collections_panel: ModsPanel,
) -> None:
    controller = collections_panel.collections_panel.controller
    paths = list(controller.items(controller.inactive_list))
    controller.active_list.setUpdatesEnabled(False)
    controller.set_enabled(paths[:2], True)
    QApplication.processEvents()
    assert not controller.active_list.updatesEnabled()
    assert controller.inactive_list.updatesEnabled()
    assert controller.active_list.paths == paths[:2]


def test_refresh_restores_multiple_selections_and_current_item(
    collections_panel: ModsPanel,
) -> None:
    view, key, paths = grouped_view(collections_panel)
    controller = view.controller
    view.mode.setCurrentIndex(1)
    node = first_group(view)
    first = node.child(0)
    second = node.child(1)
    assert first is not None and second is not None
    view.tree.setCurrentItem(second)
    for item in (node, first, second):
        item.setSelected(True)
    controller.refresh()
    assert {
        item.data(0, Qt.ItemDataRole.UserRole) for item in view.tree.selectedItems()
    } == {("set", key), ("mod", paths[0]), ("mod", paths[1])}
    current = view.tree.currentItem()
    assert current is not None
    assert current.data(0, Qt.ItemDataRole.UserRole) == ("mod", paths[1])


def test_batch_emits_one_update_per_list_and_restores_removal_handler(
    collections_panel: ModsPanel,
) -> None:
    controller = collections_panel.collections_panel.controller
    source, target = controller.inactive_list, controller.active_list
    paths = list(controller.items(source))
    source_updates = QSignalSpy(source.list_update_signal)
    target_updates = QSignalSpy(target.list_update_signal)
    controller.set_enabled(paths[:3], True)
    QApplication.processEvents()
    assert source_updates.count() == 1
    assert target_updates.count() == 1
    assert source.paths == paths[3:]
    assert target.paths == paths[:3]
    # Ordinary list removals must still notify the panel after a batch.
    source.takeItem(0)
    source.paths.remove(paths[3])
    QApplication.processEvents()
    assert source_updates.count() == 2
    assert collections_panel.inactive_mods_label.text() == "Inactive [0]"
