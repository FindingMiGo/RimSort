"""Scroll regression checks and an opt-in benchmark using synthetic mod data."""

import cProfile
import json
import os
import tempfile
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QContextMenuEvent, QResizeEvent
from PySide6.QtWidgets import QApplication, QMenu

from app.models.metadata.metadata_structure import AboutXmlMod, ModType
from app.models.settings import Settings
from app.utils.custom_list_widget_item import CustomListWidgetItem
from app.utils.custom_list_widget_item_metadata import CustomListWidgetItemMetadata
from app.views.mods_panel import ModListItemInner, ModListWidget


def make_scroll_list(qtbot: Any, count: int, tags: bool) -> ModListWidget:
    settings = MagicMock(spec=Settings)
    settings.mod_type_filter = False
    settings.show_save_comparison_indicators = False
    settings.mod_list_updated_indicator = False
    settings.mod_list_startup_impact = False
    settings.text_editor_location = ""
    controller = MagicMock()
    mods = {
        f"/synthetic/mod-{row}": AboutXmlMod(
            name=f"Mod {row}: 日本語 translation and additional content",
            _mod_path=Path(f"/synthetic/mod-{row}"),
            _mod_type=ModType.LOCAL,
        )
        for row in range(count)
    }
    controller.get_mod.side_effect = mods.get
    controller.mods_metadata = mods
    widget = ModListWidget("Inactive", settings, controller)
    qtbot.addWidget(widget)
    widget.show_tags = tags
    widget.setStyleSheet(
        (Path(__file__).parents[2] / "themes/Modern/style.qss").read_text()
    )
    widget.resize(640, 600)
    for row in range(count):
        data = object.__new__(CustomListWidgetItemMetadata)
        data.__dict__.update(
            path=f"/synthetic/mod-{row}",
            errors_warnings="",
            errors="",
            warnings="",
            filtered=False,
            invalid=False,
            mismatch=False,
            alternative=False,
            mod_color=None,
            mod_tags=["framework", "quality of life", "日本語翻訳"],
            show_tags=tags,
            list_type="Inactive",
        )
        item = CustomListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, data, avoid_emit=True)
        item.setData(Qt.ItemDataRole.SizeHintRole, QSize(600, 24), avoid_emit=True)
        widget.addItem(item)
    widget.show()
    QApplication.processEvents()
    return widget


@pytest.mark.parametrize("tags", [False, True])
def test_cached_tags_used_when_scrolling(qtbot: Any, tags: bool) -> None:
    with patch("app.views.mods_panel.auxdb_get_mod_tags", return_value=[]) as reads:
        widget = make_scroll_list(qtbot, 80, tags)
        for position in (30, 60, 0, 30, 60, 0):
            widget.verticalScrollBar().setValue(position)
            QApplication.processEvents()
        reads.assert_not_called()
        row_widget = widget.itemWidget(widget.item(0))
        assert row_widget is not None
        assert "日本語翻訳" in row_widget.toolTip()


def test_tag_edits_refresh_row_and_tooltip(qtbot: Any) -> None:
    with patch("app.views.mods_panel.auxdb_get_mod_tags", return_value=[]) as reads:
        widget = make_scroll_list(qtbot, 1, True)
        row_widget = widget.itemWidget(widget.item(0))
        assert isinstance(row_widget, ModListItemInner)
        for tags in (["new tag"], []):
            reads.return_value = tags
            widget.refresh_mod_tags_for_uuid("/synthetic/mod-0")
            assert row_widget.mod_tags_label.isHidden() == (not tags)
            assert "日本語翻訳" not in row_widget.toolTip()
            assert ("new tag" in row_widget.toolTip()) == bool(tags)


def test_unchanged_tags_do_not_restart_layout(qtbot: Any) -> None:
    with patch("app.views.mods_panel.auxdb_get_mod_tags", return_value=[]):
        widget = make_scroll_list(qtbot, 1, True)
        row = widget.itemWidget(widget.item(0))
        assert isinstance(row, ModListItemInner)
        tags = widget.item(0).data(Qt.ItemDataRole.UserRole)["mod_tags"]
        with patch.object(row, "_resize_text_after_icon_toggle") as resize:
            row.set_tags_visible(True, tags)
            resize.assert_not_called()
            row.set_tags_visible(False, tags)
            resize.assert_called_once()
        event = QResizeEvent(row.size(), row.size())
        row.resizeEvent(event)
        with patch.object(row.main_label, "setText") as set_text:
            row.resizeEvent(event)
            set_text.assert_not_called()


def test_collection_labels_refresh_visible_and_lazy_rows(qtbot: Any) -> None:
    with patch("app.views.mods_panel.auxdb_get_mod_tags", return_value=[]) as reads:
        widget = make_scroll_list(qtbot, 80, True)
        items = {f"/synthetic/mod-{index}": widget.item(index) for index in (0, 79)}
        assert widget.itemWidget(widget.item(79)) is None
        labels = {
            "/synthetic/mod-0": "Gameplay / Set",
            "/synthetic/mod-79": "Translations",
        }
        widget.update_collection_labels(labels, items)
        for position in (widget.verticalScrollBar().maximum(), 0):
            widget.verticalScrollBar().setValue(position)
            QApplication.processEvents()
        for path, item in items.items():
            row = widget.itemWidget(item)
            assert isinstance(row, ModListItemInner)
            assert row.list_item_name == f"{row.base_mod_name} [{labels[path]}]"
            assert row.main_label.toolTip() == row.list_item_name

        widget.update_collection_labels({}, items)
        for item in items.values():
            row = widget.itemWidget(item)
            assert isinstance(row, ModListItemInner)
            assert row.list_item_name == row.base_mod_name
            assert row.main_label.toolTip() == row.base_mod_name
        reads.assert_not_called()


@pytest.mark.parametrize("divider", [False, True])
@pytest.mark.parametrize("child", [False, True])
def test_context_menu_from_viewport(qtbot: Any, divider: bool, child: bool) -> None:
    with patch("app.views.mods_panel.auxdb_get_mod_tags", return_value=[]):
        widget = make_scroll_list(qtbot, 2, True)
        if divider:
            widget.add_divider(0, "Section")
            QApplication.processEvents()
        widget.setCurrentRow(0)
        position = widget.visualItemRect(widget.item(0)).center()
        receiver = widget.viewport()
        if child and not divider:
            row = widget.itemWidget(widget.item(0))
            assert isinstance(row, ModListItemInner)
            receiver = row.mod_tags_label
        global_position = widget.viewport().mapToGlobal(position)
        event = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse,
            receiver.mapFromGlobal(global_position),
            global_position,
        )
        with patch.object(QMenu, "exec_", return_value=None) as menu:
            QApplication.sendEvent(receiver, event)
            menu.assert_called_once()
        assert event.isAccepted()


@pytest.mark.skipif(
    not os.getenv("RIMSORT_SCROLL_BENCHMARK"), reason="opt-in scroll benchmark"
)
@pytest.mark.parametrize("tags", [False, True])
def test_scroll_benchmark(qtbot: Any, tags: bool) -> None:
    count = int(os.getenv("RIMSORT_SCROLL_ROWS", "1000"))
    with patch(
        "app.views.mods_panel.auxdb_get_mod_tags",
        return_value=["framework", "quality of life", "日本語翻訳"],
    ) as reads:
        widget = make_scroll_list(qtbot, count, tags)
        bar = widget.verticalScrollBar()
        for phase in ("first", "return", "repeat"):
            reads.reset_mock()
            times = []
            profile = (
                cProfile.Profile() if os.getenv("RIMSORT_SCROLL_PROFILE") else None
            )
            if profile is not None:
                profile.enable()
            positions = list(range(0, bar.maximum() + 1, 10))
            positions.append(bar.maximum())
            if phase == "return":
                positions.reverse()
            for position in positions:
                start = perf_counter()
                bar.setValue(position)
                QApplication.processEvents()
                times.append((perf_counter() - start) * 1000)
            if profile is not None:
                profile.disable()
                profile.dump_stats(
                    str(
                        Path(tempfile.gettempdir())
                        / f"rimsort-scroll-{tags}-{phase}.prof"
                    )
                )
            print(
                json.dumps(
                    {
                        "tags": tags,
                        "phase": phase,
                        "rows": count,
                        "median_ms": round(median(times), 3),
                        "p95_ms": round(sorted(times)[int(len(times) * 0.95)], 3),
                        "max_ms": round(max(times), 3),
                        "tag_reads": reads.call_count,
                        "widgets": len(widget.get_all_loaded_mod_list_items()),
                    }
                )
            )
