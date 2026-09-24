"""Grouping uses the real mod-list signals without changing load order."""

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QPoint, QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QDrag, QFont
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLabel,
)
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
from app.views.mods_panel import ModListItemInner, ModListWidget, ModsPanel


def synthetic_item(path: str, list_type: str) -> CustomListWidgetItem:
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
        list_type=list_type,
    )
    item = CustomListWidgetItem()
    item.setData(Qt.ItemDataRole.UserRole, data, avoid_emit=True)
    item.setData(Qt.ItemDataRole.SizeHintRole, QSize(600, 24), avoid_emit=True)
    return item


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
        panel.inactive_mods_list.addItem(synthetic_item(path, "Inactive"))
    QApplication.processEvents()
    yield panel
    panel._sort_debounce_timer.stop()
    panel.deleteLater()
    QApplication.processEvents()


def grouped_set(panel: ModsPanel) -> tuple[ModCollectionsController, str, list[str]]:
    controller = panel.collections_controller
    paths = list(controller.items(controller.inactive_list))
    key = controller.create("set", "Translations", paths[:2], [])
    return controller, key, paths


def append_synthetic_mod(
    panel: ModsPanel, path: str, active: bool, index: int | None = None
) -> None:
    """Simulate the list insertion following a filesystem creation event."""
    source = panel.active_mods_list if active else panel.inactive_mods_list
    item = synthetic_item(path, source.list_type)
    if index is None:
        source.addItem(item)
    else:
        source.insertItem(index, item)


def extend_synthetic_mods(panel: ModsPanel) -> None:
    """Add enough members to exercise expanded rows beyond the old clipping limit."""
    for row in range(4, 8):
        path = f"/synthetic/mod-{row}"
        panel.metadata_controller.mods_metadata[path] = AboutXmlMod(
            name=f"Mod {row}: 日本語 translation and additional content",
            package_id=CaseInsensitiveStr(f"example.mod{row}"),
            _mod_path=Path(path),
            _mod_type=ModType.LOCAL,
        )
        append_synthetic_mod(panel, path, False)


def drop_on_representative(source: ModListWidget, parent: CustomListWidgetItem) -> None:
    """Drop the current selection on the main row, not the expanded child area."""
    rect = source.visualItemRect(parent)
    base_height = parent.data(Qt.ItemDataRole.UserRole).__dict__.get(
        "collection_base_height", rect.height()
    )
    position = rect.center()
    position.setY(rect.top() + base_height // 2)
    event = MagicMock()
    event.source.return_value = source
    event.position.return_value = QPointF(position)
    source.dropEvent(event)
    event.setDropAction.assert_called_once_with(Qt.DropAction.CopyAction)
    event.accept.assert_called_once_with()
    QApplication.processEvents()


def activate_three(
    panel: ModsPanel,
) -> tuple[ModCollectionsController, list[str], ModListWidget]:
    controller = panel.collections_controller
    paths = list(controller.items(controller.inactive_list))[:3]
    controller.set_enabled(paths, True)
    QApplication.processEvents()
    return controller, paths, panel.active_mods_list


def child_labels(
    source: ModListWidget, parent: CustomListWidgetItem
) -> tuple[ModListItemInner, list[QLabel]]:
    widget = source.itemWidget(parent)
    assert isinstance(widget, ModListItemInner)
    labels = []
    for index in range(widget.collection_children_layout.count()):
        layout_item = widget.collection_children_layout.itemAt(index)
        assert layout_item is not None
        label = layout_item.widget()
        assert isinstance(label, QLabel)
        labels.append(label)
    return widget, labels


def native_drag(
    qtbot: QtBot,
    source: ModListWidget,
    source_item: CustomListWidgetItem,
    target: ModListWidget,
    target_position: QPoint,
) -> None:
    """Run Qt's native drag loop, including startDrag's source-row cleanup."""
    timers: list[QTimer] = []

    def schedule(delay: int, callback: Callable[[], None]) -> None:
        timer = QTimer(source)
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timers.append(timer)
        timer.start(delay)

    try:
        QTest.mousePress(
            source.viewport(),
            Qt.MouseButton.LeftButton,
            pos=source.visualItemRect(source_item).center(),
        )
        schedule(100, lambda: QTest.mouseMove(target.viewport(), target_position))
        schedule(
            200,
            lambda: QTest.mouseRelease(
                target.viewport(), Qt.MouseButton.LeftButton, pos=target_position
            ),
        )
        schedule(2000, QDrag.cancel)
        source.startDrag(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)
        qtbot.wait(100)
    finally:
        for timer in timers:
            timer.stop()
        QDrag.cancel()


@pytest.mark.skipif(
    os.environ.get("RIMSORT_NATIVE_DRAG_TESTS") != "1",
    reason="Opt-in native Qt drag test; run with xcb under xvfb-run",
)
@pytest.mark.parametrize("list_type", ["Active", "Inactive"])
@pytest.mark.parametrize("expanded", [False, True])
def test_native_set_drop_preserves_all_load_order_rows(
    collections_panel: ModsPanel, qtbot: QtBot, list_type: str, expanded: bool
) -> None:
    if QApplication.platformName() != "xcb":
        pytest.skip("Requires the xcb drag event loop (offscreen does not support it)")
    panel = collections_panel
    extend_synthetic_mods(panel)
    QApplication.processEvents()
    controller = panel.collections_controller
    paths = list(controller.items(controller.inactive_list))
    source = controller.inactive_list
    if list_type == "Active":
        controller.set_enabled(paths, True)
        source = controller.active_list
    panel.resize(1200, 700)
    panel.show()
    qtbot.waitExposed(panel)
    qtbot.wait(200)
    original_paths = source.get_all_mod_paths()
    parent = controller.items(source)[paths[0]]
    base_height = parent.sizeHint().height()
    drop = QSignalSpy(source.create_set_from_drop_signal)
    removed = QSignalSpy(source.model().rowsRemoved)
    key = ""
    for index, path in enumerate(paths[1:], start=1):
        rect = source.visualItemRect(parent)
        position = rect.center()
        position.setY(rect.top() + base_height // 2)
        native_drag(qtbot, source, controller.items(source)[path], source, position)
        assert drop.count() == index
        assert source.get_all_mod_paths() == original_paths
        assert removed.count() == 0
        key = controller.collections.set_for(paths[0])
        assert controller.collections.sets[key].members == paths[: index + 1]
        if index == 1 and expanded:
            source.toggle_collection_set(key)
            QApplication.processEvents()
        assert len(child_labels(source, parent)[1]) == (index if expanded else 0)

    if not expanded:
        source.toggle_collection_set(key)
    QApplication.processEvents()
    widget, labels = child_labels(source, parent)
    assert len(labels) == 7
    assert source.visualItemRect(parent).height() == base_height + 7 * 24
    assert all(
        label.mapTo(widget, label.rect().bottomLeft()).y() < widget.height()
        for label in labels
    )
    source.toggle_collection_set(key)
    QApplication.processEvents()
    assert source.visualItemRect(parent).height() == base_height
    source.toggle_collection_set(key)
    QApplication.processEvents()
    assert len(child_labels(source, parent)[1]) == 7
    search = (
        panel.active_mods_search
        if list_type == "Active"
        else panel.inactive_mods_search
    )
    search.setText("Mod 7")
    QApplication.processEvents()
    assert not parent.isHidden()
    assert len(child_labels(source, parent)[1]) == 7
    assert source.get_all_mod_paths() == original_paths


@pytest.mark.skipif(
    os.environ.get("RIMSORT_NATIVE_DRAG_TESTS") != "1",
    reason="Opt-in native Qt drag test; run with xcb under xvfb-run",
)
def test_native_reorder_and_cross_list_drop_still_move_rows(
    collections_panel: ModsPanel, qtbot: QtBot
) -> None:
    if QApplication.platformName() != "xcb":
        pytest.skip("Requires the xcb drag event loop (offscreen does not support it)")
    panel = collections_panel
    controller, paths, active = activate_three(panel)
    panel.resize(1200, 700)
    panel.show()
    qtbot.waitExposed(panel)
    qtbot.wait(200)
    first = controller.items(active)[paths[0]]
    last = controller.items(active)[paths[-1]]
    position = active.visualItemRect(last).bottomLeft() + QPoint(100, 10)
    native_drag(qtbot, active, first, active, position)
    assert active.get_all_mod_paths() == [*paths[1:], paths[0]]
    assert not controller.collections.sets

    inactive = controller.inactive_list
    inactive_paths = inactive.get_all_mod_paths()
    native_drag(qtbot, active, first, inactive, QPoint(100, 150))
    assert active.get_all_mod_paths() == paths[1:]
    assert inactive.get_all_mod_paths() == [*inactive_paths, paths[0]]
    assert active.paths == active.get_all_mod_paths()
    assert inactive.paths == inactive.get_all_mod_paths()


@contextmanager
def mock_mod_creation(panel: ModsPanel) -> Iterator[tuple[MagicMock, MagicMock]]:
    with (
        patch.object(
            panel.active_mods_list,
            "append_new_item",
            side_effect=lambda path, index=None: append_synthetic_mod(
                panel, path, True, index
            ),
        ) as append_active,
        patch.object(
            panel.inactive_mods_list,
            "append_new_item",
            side_effect=lambda path: append_synthetic_mod(panel, path, False),
        ) as append_inactive,
    ):
        yield append_active, append_inactive


def missing_active_child(
    panel: ModsPanel,
) -> tuple[ModCollectionsController, list[str], str]:
    controller, paths, _ = activate_three(panel)
    key = controller.create("set", "Paired", paths, [])
    panel.on_mod_deleted(paths[1])
    QApplication.processEvents()
    return controller, paths, key


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


def test_drop_mod_onto_mod_creates_and_extends_set(
    collections_panel: ModsPanel,
) -> None:
    source = collections_panel.inactive_mods_list
    controller = collections_panel.collections_controller
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
    controller, key, paths = grouped_set(panel)
    source = controller.inactive_list
    source.toggle_collection_set(key)
    QApplication.processEvents()
    parent = controller.items(source)[paths[0]]
    original_widget, original_labels = child_labels(source, parent)
    expanded_height = parent.sizeHint().height()

    controller.refresh()
    QApplication.processEvents()
    refreshed_widget, refreshed_labels = child_labels(source, parent)
    assert refreshed_widget is original_widget
    assert refreshed_labels == original_labels
    assert parent.sizeHint().height() == expanded_height

    controller.assign([paths[2]], "set", key)
    QApplication.processEvents()

    parent = controller.items(source)[paths[0]]
    widget, labels = child_labels(source, parent)
    assert widget is original_widget
    assert labels[0] is original_labels[0]
    assert len(labels) == 2
    assert parent.sizeHint().height() == expanded_height + 24
    last_label = labels[-1]
    assert (
        last_label.mapTo(widget, last_label.rect().bottomLeft()).y() < widget.height()
    )


def test_adding_inactive_mod_to_active_set_shows_second_child(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    panel.show()
    controller, key, paths = grouped_set(panel)
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
    widget, labels = child_labels(active, parent)
    assert len(labels) == 2
    last_label = labels[-1]
    assert controller.mod_name(paths[2]) in last_label.text()
    assert (
        last_label.mapTo(widget, last_label.rect().bottomLeft()).y() < widget.height()
    )


def test_adding_active_mod_to_inactive_set_disables_it(
    collections_panel: ModsPanel,
) -> None:
    controller, key, paths = grouped_set(collections_panel)
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
    controller, paths, active = activate_three(panel)
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
    _, labels = child_labels(active, parent)
    assert len(labels) == 2
    assert controller.mod_name(paths[1]) in labels[0].text()
    assert controller.mod_name(paths[2]) in labels[1].text()


def test_second_active_drop_keeps_previously_selected_child_first(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    panel.show()
    controller, paths, active = activate_three(panel)
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
    widget, labels = child_labels(active, parent)
    assert len(labels) == 2
    assert controller.mod_name(paths[2]) in labels[0].text()
    assert controller.mod_name(paths[1]) in labels[1].text()
    assert labels[1].mapTo(widget, labels[1].rect().bottomLeft()).y() < widget.height()


def test_eight_member_active_set_keeps_every_child_visible(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    panel.show()
    extend_synthetic_mods(panel)
    QApplication.processEvents()
    controller = panel.collections_controller
    paths = list(controller.items(controller.inactive_list))
    controller.set_enabled(paths, True)
    QApplication.processEvents()
    active = panel.active_mods_list
    representative = controller.items(active)[paths[0]]
    key = ""
    for index, path in enumerate(paths[1:], start=1):
        active.clearSelection()
        controller.items(active)[path].setSelected(True)
        representative.setSelected(True)
        active.scrollToItem(representative)
        QApplication.processEvents()
        drop_on_representative(active, representative)
        if not key:
            key = controller.collections.set_for(paths[0])
            active.toggle_collection_set(key)
            QApplication.processEvents()
        assert controller.collections.sets[key].members == paths[: index + 1]
        parent = controller.items(active)[paths[0]]
        widget, labels = child_labels(active, parent)
        assert len(labels) == index
        for member_path, label in zip(paths[1 : index + 1], labels):
            assert controller.mod_name(member_path) in label.text()
            assert label.mapTo(widget, label.rect().bottomLeft()).y() < widget.height()

    # Filtering on a single member must not remove the other members from an
    # expanded set.  They have no independent visible rows to search for.
    panel.active_mods_search.setText("Mod 7")
    QApplication.processEvents()
    parent = controller.items(active)[paths[0]]
    assert not parent.isHidden()
    widget, labels = child_labels(active, parent)
    assert len(labels) == 7
    assert all(
        controller.mod_name(path) in label.text()
        for path, label in zip(paths[1:], labels)
    )

    panel.active_mods_search.setText("Mod 1")
    QApplication.processEvents()
    widget, labels = child_labels(active, parent)
    assert len(labels) == 7
    assert controller.mod_name(paths[1]) in labels[0].text()


def test_expanded_active_set_with_rimpy_font_and_long_list_has_visible_rows(
    collections_panel: ModsPanel,
    qtbot: QtBot,
) -> None:
    panel = collections_panel
    panel.resize(1500, 850)
    panel.setFont(QFont("Yu Gothic UI", 12))
    stylesheet = Path("themes/RimPy/style.qss").read_text(encoding="utf-8")
    panel.setStyleSheet(stylesheet)
    panel.show()
    metadata = panel.metadata_controller
    extend_synthetic_mods(panel)
    for row in range(397):
        path = f"/synthetic/background-{row}"
        metadata.mods_metadata[path] = AboutXmlMod(
            name=f"Background Mod {row}",
            package_id=CaseInsensitiveStr(f"example.background{row}"),
            _mod_path=Path(path),
            _mod_type=ModType.LOCAL,
        )
        append_synthetic_mod(panel, path, True)
    QApplication.processEvents()
    controller = panel.collections_controller
    paths = [f"/synthetic/mod-{row}" for row in range(8)]
    controller.set_enabled(paths, True)
    QApplication.processEvents()
    active = panel.active_mods_list
    parent = controller.items(active)[paths[0]]
    active.scrollToItem(parent)
    active.check_widgets_visible()
    qtbot.waitUntil(
        lambda: isinstance(active.itemWidget(parent), ModListItemInner), timeout=2000
    )
    key = ""
    base_height = parent.sizeHint().height()
    for index, path in enumerate(paths[1:], start=1):
        active.clearSelection()
        controller.items(active)[path].setSelected(True)
        parent.setSelected(True)
        QApplication.processEvents()
        drop_on_representative(active, parent)
        if not key:
            key = controller.collections.set_for(paths[0])
            active.toggle_collection_set(key)
        widget, labels = child_labels(active, parent)
        assert len(labels) == index
        assert widget.collection_children_widget.height() == index * 24
        row_rect = active.visualItemRect(parent)
        assert row_rect.height() >= widget.height()
        assert row_rect.height() >= widget.sizeHint().height()
        assert row_rect.height() == base_height + index * 24
        for member_path, label in zip(paths[1 : index + 1], labels):
            assert controller.mod_name(member_path) in label.text()
            assert label.mapTo(widget, label.rect().bottomLeft()).y() < widget.height()

    # Re-rendering after an add must not leave the expanded height cached
    # when the set is collapsed, nor lose any children on the next opening.
    active.toggle_collection_set(key)
    QApplication.processEvents()
    assert active.visualItemRect(parent).height() == base_height
    active.toggle_collection_set(key)
    QApplication.processEvents()
    widget, labels = child_labels(active, parent)
    assert len(labels) == 7
    assert widget.collection_children_widget.height() == 7 * 24
    assert active.visualItemRect(parent).height() == base_height + 7 * 24


def test_opening_set_without_search_does_not_scroll_representative_to_top(
    collections_panel: ModsPanel,
    qtbot: QtBot,
) -> None:
    panel = collections_panel
    panel.resize(1500, 850)
    panel.show()
    metadata = panel.metadata_controller
    for row in range(100):
        path = f"/synthetic/background-{row}"
        metadata.mods_metadata[path] = AboutXmlMod(
            name=f"Background Mod {row}",
            package_id=CaseInsensitiveStr(f"example.background{row}"),
            _mod_path=Path(path),
            _mod_type=ModType.LOCAL,
        )
        append_synthetic_mod(panel, path, True, row if row < 50 else None)
    QApplication.processEvents()
    controller = panel.collections_controller
    paths = [f"/synthetic/mod-{row}" for row in range(3)]
    controller.set_enabled(paths, True)
    QApplication.processEvents()
    active = panel.active_mods_list
    key = controller.create("set", "Representative", paths, [])
    parent = controller.items(active)[paths[0]]
    active.scrollToItem(parent, QAbstractItemView.ScrollHint.PositionAtCenter)
    active.check_widgets_visible()
    qtbot.waitUntil(
        lambda: isinstance(active.itemWidget(parent), ModListItemInner), timeout=2000
    )
    QApplication.processEvents()
    before = active.verticalScrollBar().value()
    assert before > 0
    assert active.visualItemRect(parent).top() > 0

    active.toggle_collection_set(key)
    QApplication.processEvents()

    assert active.verticalScrollBar().value() == before
    assert active.visualItemRect(parent).top() > 0
    assert len(child_labels(active, parent)[1]) == 2


def test_active_set_survives_representative_deletion_and_recreation(
    collections_panel: ModsPanel,
    qtbot: QtBot,
) -> None:
    panel = collections_panel
    controller, paths, active = activate_three(panel)
    items = controller.items(active)
    items[paths[1]].setSelected(True)
    items[paths[2]].setSelected(True)
    assert active._request_set_from_drop(items[paths[0]])
    QApplication.processEvents()
    key = controller.collections.set_for(paths[0])

    panel.on_mod_deleted(paths[0])
    QApplication.processEvents()
    fallback = controller.items(active)[paths[1]]
    qtbot.waitUntil(
        lambda: fallback.data(Qt.ItemDataRole.UserRole).__dict__["collection_parent"]
    )
    assert controller.items(active)[paths[2]].isHidden()

    with mock_mod_creation(panel) as (append_active, append_inactive):
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
    controller, paths, key = missing_active_child(panel)

    with mock_mod_creation(panel) as (append_active, append_inactive):
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
    controller, paths, key = missing_active_child(panel)
    controller.set_enabled(controller.collections.members("set", key), False)
    QApplication.processEvents()

    with mock_mod_creation(panel) as (append_active, append_inactive):
        panel.on_mod_created(paths[1])
        append_active.assert_not_called()
        append_inactive.assert_called_once_with(paths[1])
    QApplication.processEvents()
    assert set(controller.items(panel.inactive_mods_list)) >= set(paths)


def test_expanding_unloaded_set_reserves_child_rows(
    collections_panel: ModsPanel,
) -> None:
    controller = collections_panel.collections_controller
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
    controller, key, paths = grouped_set(collections_panel)
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
    controller, key, paths = grouped_set(collections_panel)
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


def test_drop_on_expanded_representative_adds_member(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    panel.show()
    controller = panel.collections_controller
    paths = list(controller.items(controller.inactive_list))
    controller.set_enabled(paths, True)
    QApplication.processEvents()
    source = controller.active_list
    key = controller.create("set", "Translations", paths[:3], [])
    source.toggle_collection_set(key)
    QApplication.processEvents()
    parent = controller.items(source)[paths[0]]
    newcomer = controller.items(source)[paths[3]]
    rect = source.visualItemRect(parent)
    base_height = parent.data(Qt.ItemDataRole.UserRole).__dict__[
        "collection_base_height"
    ]
    position = rect.center()
    position.setY(rect.top() + base_height // 2)
    assert source._drop_position_is_on_item(parent, position)

    newcomer.setSelected(True)
    parent.setSelected(True)
    event = MagicMock()
    event.source.return_value = source
    event.position.return_value = QPointF(position)
    source.dropEvent(event)
    QApplication.processEvents()

    assert controller.collections.sets[key].members == paths
    event.setDropAction.assert_called_once_with(Qt.DropAction.CopyAction)
    event.accept.assert_called_once_with()


def test_batch_activation_preserves_order_and_set_membership(
    collections_panel: ModsPanel,
) -> None:
    controller = collections_panel.collections_controller
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
    assert controller.active_list._collection_child_summaries(group)[0][0] == (
        f"#3 {controller.mod_name(paths[1])}"
    )
    controller.set_enabled([paths[1]], False)
    QApplication.processEvents()
    assert paths[0] in controller.items(controller.active_list)
    assert paths[1] not in controller.items(controller.active_list)
    assert controller.collections.sets[group].members == paths[:2]
    controller.set_enabled(controller.collections.members("folder", folder), False)
    QApplication.processEvents()
    assert list(controller.items(controller.active_list)) == [paths[3]]
    assert len(controller.items(controller.inactive_list)) == 3
    assert len(set(controller.items(controller.inactive_list))) == 3
    assert collections_panel.active_mods_label.text() == "Active [1]"
    assert collections_panel.inactive_mods_label.text() == "Inactive [3]"


@pytest.mark.parametrize("enable", [False, True])
@pytest.mark.parametrize("highlight", [False, True])
@pytest.mark.parametrize("grouped", [False, True])
@pytest.mark.parametrize("target_search", ["", "Mod 1"])
def test_move_replaces_source_filter_state(
    collections_panel: ModsPanel,
    enable: bool,
    highlight: bool,
    grouped: bool,
    target_search: str,
) -> None:
    panel = collections_panel
    controller = panel.collections_controller
    paths = list(controller.items(controller.inactive_list))
    if not enable:
        controller.set_enabled(paths, True)
        QApplication.processEvents()
    source = controller.inactive_list if enable else controller.active_list
    target = controller.active_list if enable else controller.inactive_list
    source_type = source.list_type
    source_search = panel.inactive_mods_search if enable else panel.active_mods_search
    target_search_widget = (
        panel.active_mods_search if enable else panel.inactive_mods_search
    )
    target_label = panel.active_mods_label if enable else panel.inactive_mods_label
    if grouped:
        controller.create("set", "Pair", paths[:2], [])
    if highlight:
        panel.signal_search_mode_filter(source_type)
    source_search.setText("Mod 0")
    target_search_widget.setText(target_search)
    moving = controller.items(source)[paths[1]]
    data = moving.data(Qt.ItemDataRole.UserRole)
    assert data["filtered"] or data.__dict__["counted_as_filtered"]

    controller.set_enabled(paths[:2], enable)
    QApplication.processEvents()

    for item in controller.items(target).values():
        data = item.data(Qt.ItemDataRole.UserRole)
        filtered = bool(target_search) and data["path"] != paths[1]
        assert not data["filtered"]
        assert data.__dict__["hidden_by_filter"] == (filtered and not grouped)
        assert data.__dict__["counted_as_filtered"] == filtered
        assert item.isHidden() == (
            data.__dict__.get("collection_child", False) or (filtered and not grouped)
        )
    count = "1/2" if target_search else "2"
    assert target_label.text() == f"{target.list_type} [{count}]"
    assert controller.items(source).keys() == dict.fromkeys(paths[2:]).keys()


def test_missing_members_and_organization_do_not_change_order(
    collections_panel: ModsPanel,
) -> None:
    controller = collections_panel.collections_controller
    source = controller.inactive_list
    original = list(controller.items(source))
    key = controller.collections.create("set", "Optional")
    controller.assign([original[0], "/missing"], "set", key)
    assert list(controller.items(source)) == original
    controller.set_enabled(controller.collections.members("set", key), True)
    QApplication.processEvents()
    assert controller.collections.members("set", key) == [original[0], "/missing"]
    assert list(controller.items(controller.active_list)) == original[:1]
    controller.delete("set", key)
    assert list(controller.items(controller.active_list)) == original[:1]
    assert list(controller.items(source)) == original[1:]


def test_reordering_and_instance_switch_preserve_separate_groups(
    collections_panel: ModsPanel,
) -> None:
    controller, key, paths = grouped_set(collections_panel)
    controller.set_enabled(paths, True)
    QApplication.processEvents()
    active = controller.active_list
    item = active.item(0)
    active.paths.remove(paths[0])
    active.takeItem(0)
    active.addItem(item)
    QApplication.processEvents()
    assert list(controller.items(active)) == paths[1:] + paths[:1]
    assert active._collection_child_summaries(key)[0][0] == (
        f"#1 {controller.mod_name(paths[1])}"
    )
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
    controller = collections_panel.collections_controller
    key = controller.collections.create("set", "Empty")
    folder = controller.collections.create("folder", "Folder")
    controller.move_set(key, folder)
    assert controller.collections.sets[key].folder == folder
    assert controller.collections.members("folder", folder) == []
    controller.move_set(key, "")
    assert controller.collections.sets[key].folder == ""


def test_group_operations_save_once_and_activation_does_not_save_settings(
    collections_panel: ModsPanel,
) -> None:
    controller = collections_panel.collections_controller
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
    controller, key, paths = grouped_set(collections_panel)
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
    controller = collections_panel.collections_controller
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
    controller, _key, paths = grouped_set(collections_panel)
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
    controller, _key, paths = grouped_set(panel)
    source = controller.inactive_list
    parent = controller.items(source)[paths[0]]
    widget = source.itemWidget(parent)

    assert not parent.isHidden()
    assert isinstance(widget, ModListItemInner)
    assert widget.collection_children_layout.count() == 1
    child_layout_item = widget.collection_children_layout.itemAt(0)
    assert child_layout_item is not None
    child_label = child_layout_item.widget()
    assert isinstance(child_label, QLabel)
    assert controller.mod_name(paths[1]) in child_label.text()


def test_highlight_search_exposes_matching_set_child(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    controller, _key, paths = grouped_set(panel)
    panel.inactive_mods_search_filter_state = False
    panel.inactive_mods_search_filter.setCurrentText(panel.tr("Name"))

    panel.signal_search_and_filters("Inactive", "Mod 1")

    parent = controller.items(controller.inactive_list)[paths[0]]
    widget = controller.inactive_list.itemWidget(parent)
    assert not parent.isHidden()
    assert isinstance(widget, ModListItemInner)
    assert widget.collection_children_layout.count() == 1


def test_count_does_not_treat_set_children_as_filtered(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    grouped_set(panel)

    panel.update_count("Inactive")

    assert panel.inactive_mods_label.text().endswith("[4]")


def test_error_filter_reveals_set_child_and_survives_search_change(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    controller, _key, paths = grouped_set(panel)
    controller.set_enabled(paths[:2], True)
    QApplication.processEvents()
    source = panel.active_mods_list
    items = controller.items(source)
    child_data = items[paths[1]].data(Qt.ItemDataRole.UserRole)
    child_data["errors"] = "Dependency error"
    child_data["errors_warnings"] = "Dependency error"
    panel_controller = ModsPanelController(panel, panel.settings)
    panel.errors_text.clicked.emit()

    parent = items[paths[0]]
    assert panel_controller.errors_label_active
    assert source.summary_filter == "errors"
    assert not parent.isHidden()
    widget = source.itemWidget(parent)
    assert isinstance(widget, ModListItemInner)
    assert widget.collection_children_layout.count() == 1
    panel.update_count("Active")
    assert panel.active_mods_label.text().endswith("[1/2]")

    panel.active_mods_search.setText("Mod 1")
    assert panel_controller.errors_label_active
    assert not parent.isHidden()
    panel.errors_text.clicked.emit()
    assert source.summary_filter is None


def test_error_filter_keeps_every_member_of_matching_active_set(
    collections_panel: ModsPanel,
) -> None:
    panel = collections_panel
    panel.show()
    controller, paths, source = activate_three(panel)
    key = controller.create("set", "Translations", paths, [])
    source.toggle_collection_set(key)
    items = controller.items(source)
    child_data = items[paths[2]].data(Qt.ItemDataRole.UserRole)
    child_data["errors"] = "Dependency error"
    child_data["errors_warnings"] = "Dependency error"

    source.summary_filter = "errors"
    panel.signal_search_and_filters("Active", "")
    parent = items[paths[0]]
    assert not parent.isHidden()
    _widget, labels = child_labels(source, parent)
    assert len(labels) == 2
    assert all(
        controller.mod_name(path) in label.text()
        for path, label in zip(paths[1:], labels)
    )

    # A set is one visible unit: the name match and the error may belong to
    # different members of that same unit.
    panel.active_mods_search.setText("Mod 1")
    QApplication.processEvents()
    assert not parent.isHidden()
    _widget, labels = child_labels(source, parent)
    assert len(labels) == 2


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


def test_dividers_are_excluded_from_group_actions_and_load_positions(
    collections_panel: ModsPanel,
) -> None:
    controller, key, paths = grouped_set(collections_panel)
    controller.set_enabled(paths[:2], True)
    QApplication.processEvents()
    controller.active_list.add_divider(1, "Section")
    QApplication.processEvents()
    assert controller.active_list._collection_child_summaries(key)[0][0] == (
        f"#2 {controller.mod_name(paths[1])}"
    )
    controller.set_enabled(controller.collections.members("set", key), False)
    QApplication.processEvents()
    assert controller.items(controller.active_list) == {}
    assert controller.active_list.count() == 1
    assert len(controller.active_list.paths) == 1
    assert collections_panel.active_mods_label.text() == "Active [0]"


def test_batch_preserves_existing_list_update_state(
    collections_panel: ModsPanel,
) -> None:
    controller = collections_panel.collections_controller
    paths = list(controller.items(controller.inactive_list))
    controller.active_list.setUpdatesEnabled(False)
    controller.set_enabled(paths[:2], True)
    QApplication.processEvents()
    assert not controller.active_list.updatesEnabled()
    assert controller.inactive_list.updatesEnabled()
    assert controller.active_list.paths == paths[:2]


def test_batch_emits_one_update_per_list_and_restores_removal_handler(
    collections_panel: ModsPanel,
) -> None:
    controller = collections_panel.collections_controller
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
