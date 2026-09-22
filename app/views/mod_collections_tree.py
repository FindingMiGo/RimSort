"""Render and filter the collection hierarchy without changing mod state."""

from collections.abc import Callable, Iterator

from PySide6.QtCore import QCoreApplication, QItemSelectionModel, QSignalBlocker, Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator

from app.models.mod_collections import ModCollections, ModCollectionsSnapshot

translate = QCoreApplication.translate


class ModCollectionsTree(QTreeWidget):
    def __init__(self) -> None:
        super().__init__()
        self.snapshot = ModCollectionsSnapshot()
        self._query = ""
        self._active_only = False
        self.setHeaderLabels(
            [
                translate("ModCollectionsPanel", "Folder / set / mod"),
                translate("ModCollectionsPanel", "Active / total"),
                translate("ModCollectionsPanel", "Load position"),
            ]
        )
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setToolTip(
            translate(
                "ModCollectionsPanel",
                "Checkboxes enable or disable all members, including hidden members. Sorting changes load positions, not membership.",
            )
        )

    def nodes(self) -> Iterator[QTreeWidgetItem]:
        iterator = QTreeWidgetItemIterator(self)
        while (node := iterator.value()) is not None:
            yield node
            iterator += 1

    @staticmethod
    def identity(node: QTreeWidgetItem) -> tuple[str, str]:
        kind, key = node.data(0, Qt.ItemDataRole.UserRole)
        return kind, key

    def rebuild(
        self,
        collections: ModCollections,
        snapshot: ModCollectionsSnapshot,
        mod_name: Callable[[str], str],
    ) -> None:
        state = {
            self.identity(node): (node.isExpanded(), node.isSelected())
            for node in self.nodes()
        }
        current = self.currentItem()
        current_id = self.identity(current) if current else None
        scroll = self.verticalScrollBar().value(), self.horizontalScrollBar().value()
        self.snapshot = snapshot
        with QSignalBlocker(self):
            self.clear()
            folders = {
                key: self._add_node(
                    self, "folder", key, folder.name, collections.members("folder", key)
                )
                for key, folder in collections.folders.items()
            }
            for key, group in collections.sets.items():
                node = self._add_node(
                    folders.get(group.folder, self),
                    "set",
                    key,
                    group.name,
                    group.members,
                )
                self._add_mods(node, group.members, mod_name)
            for key, folder in collections.folders.items():
                self._add_mods(folders[key], folder.members, mod_name)
            labels = collections.labels()
            ungrouped = [
                path
                for path in (*snapshot.active, *snapshot.inactive)
                if path not in labels
            ]
            if ungrouped:
                node = QTreeWidgetItem(
                    self, [translate("ModCollectionsPanel", "Ungrouped")]
                )
                node.setData(0, Qt.ItemDataRole.UserRole, ("ungrouped", ""))
                self._add_mods(node, ungrouped, mod_name)
            for node in self.nodes():
                identity = self.identity(node)
                expanded, selected = state.get(identity, (False, False))
                node.setExpanded(expanded)
                if identity == current_id:
                    self.setCurrentItem(
                        node, 0, QItemSelectionModel.SelectionFlag.NoUpdate
                    )
                node.setSelected(selected)
            self.apply_filters(self._query, self._active_only)
            self.resizeColumnToContents(1)
            self.resizeColumnToContents(2)
            self.verticalScrollBar().setValue(scroll[0])
            self.horizontalScrollBar().setValue(scroll[1])

    def _add_node(
        self,
        parent: QTreeWidget | QTreeWidgetItem,
        kind: str,
        key: str,
        name: str,
        paths: list[str],
    ) -> QTreeWidgetItem:
        count = sum(path in self.snapshot.positions for path in paths)
        node = QTreeWidgetItem(parent, [name, f"{count}/{len(paths)}", ""])
        node.setData(0, Qt.ItemDataRole.UserRole, (kind, key))
        node.setFlags(node.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        state = Qt.CheckState.Unchecked
        if paths and count == len(paths):
            state = Qt.CheckState.Checked
        elif count:
            state = Qt.CheckState.PartiallyChecked
        node.setCheckState(0, state)
        return node

    def _add_mods(
        self, parent: QTreeWidgetItem, paths: list[str], mod_name: Callable[[str], str]
    ) -> None:
        for path in paths:
            node = self._add_node(parent, "mod", path, mod_name(path), [path])
            installed = path in self.snapshot.installed
            node.setText(
                1,
                "" if installed else translate("ModCollectionsPanel", "Not installed"),
            )
            position = self.snapshot.positions.get(path)
            node.setText(2, f"#{position}" if position else "—")
            node.setToolTip(0, path)
            if not installed:
                node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)

    def apply_filters(self, query: str, active_only: bool) -> None:
        self._query = query.casefold().strip()
        self._active_only = active_only
        for index in range(self.topLevelItemCount()):
            node = self.topLevelItem(index)
            if node is not None:
                self._filter_node(node)

    def _filter_node(
        self, node: QTreeWidgetItem, ancestor_matches: bool = False
    ) -> bool:
        matches = (
            ancestor_matches
            or not self._query
            or self._query in node.text(0).casefold()
        )
        children_visible = False
        for index in range(node.childCount()):
            child = node.child(index)
            if child is not None:
                children_visible = self._filter_node(child, matches) or children_visible
        kind, key = self.identity(node)
        active = key in self.snapshot.positions if kind == "mod" else children_visible
        visible = (matches or children_visible) and (not self._active_only or active)
        node.setHidden(not visible)
        if self._query and children_visible:
            node.setExpanded(True)
        return visible
