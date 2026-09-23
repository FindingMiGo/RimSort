"""Grouping uses the real mod-list signals without changing load order."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QInputDialog, QTreeWidgetItem
from pytestqt.qtbot import QtBot

from app.models.instance import Instance
from app.models.metadata.metadata_structure import (
    AboutXmlMod,
    CaseInsensitiveStr,
    ModType,
)
from app.models.settings import Settings
from app.utils.custom_list_widget_item import CustomListWidgetItem
from app.utils.custom_list_widget_item_metadata import CustomListWidgetItemMetadata
from app.utils.event_bus import EventBus
from app.views.mod_collections_panel import ModCollectionsPanel
from app.views.mods_panel import ModListItemInner, ModsPanel


@pytest.fixture
def collections_panel(qtbot: QtBot) -> ModsPanel:
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
    return panel


def grouped_view(panel: ModsPanel) -> tuple[ModCollectionsPanel, str, list[str]]:
    view = panel.collections_panel
    controller = view.controller
    paths = list(controller.items(controller.inactive_list))
    key = controller.create("set", "Translations", paths[:2], [])
    return view, key, paths


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
    parent = source.item(0)
    parent_data = parent.data(Qt.ItemDataRole.UserRole)
    assert parent_data["path"] == paths[1]
    assert parent_data.__dict__["collection_set_key"] == key
    assert parent_data.__dict__["collection_parent"]
    assert parent_data.__dict__["collection_collapsed"]
    assert source.item(1).isHidden()
    assert not source.item(2).isHidden()
    assert [path for path in source.paths if not path.startswith("__divider__")] == [
        paths[1],
        paths[0],
        paths[2],
        paths[3],
    ]

    source.toggle_collection_set(key)
    assert not source.item(1).isHidden()
    assert source.item(1).text().startswith("Mod ")
    QApplication.processEvents()
    parent_widget = source.itemWidget(source.item(0))
    assert isinstance(parent_widget, ModListItemInner)
    assert parent_widget.list_item_name == controller.mod_name(paths[1])
    child_widget = source.itemWidget(source.item(1))
    assert isinstance(child_widget, ModListItemInner)
    assert child_widget.list_item_name == controller.mod_name(paths[0])
    assert source.itemWidget(source.item(1)) is not None
    assert source.item(1).text() == ""

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


def test_split_set_is_rejoined_in_dependency_order(
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

    assert controller.active_list.paths[:2] == controller.collections.members(
        "set", key
    )


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
