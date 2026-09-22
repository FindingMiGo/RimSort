"""Virtual organization of mods; the existing lists remain the load-order authority."""

from PySide6.QtCore import QCoreApplication, QPoint, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMenu,
    QPushButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.controllers.mod_collections_controller import ModCollectionsController
from app.views.mod_collections_tree import ModCollectionsTree

translate = QCoreApplication.translate


class ModCollectionsPanel(QWidget):
    def __init__(
        self, controller: ModCollectionsController, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._tree_dirty = True
        controller.changed.connect(self._on_collections_changed)
        controller.set_created_from_drop.connect(self.show_dropped_set)
        self.mode = QComboBox()
        self.mode.addItems(
            [
                translate("ModCollectionsPanel", "Load order"),
                translate("ModCollectionsPanel", "Folders and sets"),
            ]
        )
        self.mode.currentIndexChanged.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            translate("ModCollectionsPanel", "Search folders, sets and mods")
        )
        self.active_only = QCheckBox(translate("ModCollectionsPanel", "Active only"))
        filters.addWidget(self.search)
        filters.addWidget(self.active_only)
        layout.addLayout(filters)
        self.tree = ModCollectionsTree()
        self.tree.customContextMenuRequested.connect(self.context_menu)
        self.tree.itemChanged.connect(self.toggle_item)
        layout.addWidget(self.tree)
        buttons = QHBoxLayout()
        for label, kind in (
            (translate("ModCollectionsPanel", "New folder"), "folder"),
            (translate("ModCollectionsPanel", "New set"), "set"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda checked=False, kind=kind: self.create_group(kind)
            )
            buttons.addWidget(button)
        organize = QPushButton(
            translate("ModCollectionsPanel", "Organize selected mods")
        )
        organize.clicked.connect(self.organize_menu)
        buttons.addWidget(organize)
        layout.addLayout(buttons)
        # This button also works with selections in the ordinary load-order lists.
        self.organize_button = QPushButton(
            translate("ModCollectionsPanel", "Organize selected mods")
        )
        self.organize_button.clicked.connect(self.organize_menu)
        self.search.textChanged.connect(self.apply_filters)
        self.active_only.toggled.connect(self.apply_filters)

    def _on_collections_changed(self) -> None:
        self._tree_dirty = True
        self.refresh()

    def refresh(self, *_args: object) -> None:
        if self.mode.currentIndex() == 1 and self._tree_dirty:
            self.tree.rebuild(
                self.controller.collections,
                self.controller.snapshot,
                self.controller.mod_name,
            )
            self._tree_dirty = False

    def apply_filters(self, *_args: object) -> None:
        self.tree.apply_filters(self.search.text(), self.active_only.isChecked())

    def show_dropped_set(self, key: str) -> None:
        """Reveal a drop-created set as a collapsed parent in the tree."""
        self.mode.setCurrentIndex(1)
        self._tree_dirty = True
        self.refresh()
        for node in self.tree.nodes():
            if self.tree.identity(node) == ("set", key):
                self.tree.setCurrentItem(node)
                node.setSelected(True)
                node.setExpanded(False)
                self.tree.scrollToItem(node)
                break

    def selected_paths(self) -> list[str]:
        paths = []
        if self.mode.currentIndex() == 1:
            for node in self.tree.selectedItems():
                kind, key = node.data(0, Qt.ItemDataRole.UserRole)
                if kind != "ungrouped":
                    paths.extend(self.controller.collections.members(kind, key))
        paths.extend(
            self.controller.selected_paths(include_active=self.mode.currentIndex() == 0)
        )
        return list(dict.fromkeys(paths))

    def create_group(self, kind: str) -> None:
        name, accepted = QInputDialog.getText(
            self,
            translate("ModCollectionsPanel", "Create folder or set"),
            translate("ModCollectionsPanel", "Name:"),
        )
        if not accepted or not name.strip():
            return
        paths = self.selected_paths()
        self.controller.create(kind, name, paths, self.selected_sets())
        self.mode.setCurrentIndex(1)

    def organize_menu(self) -> None:
        menu = QMenu(self)
        paths = self.selected_paths()
        create_set = menu.addAction(translate("ModCollectionsPanel", "New set"))
        create_set.triggered.connect(lambda: self.create_group("set"))
        create_folder = menu.addAction(translate("ModCollectionsPanel", "New folder"))
        create_folder.triggered.connect(lambda: self.create_group("folder"))
        for kind, groups, title in (
            (
                "set",
                self.controller.collections.sets,
                translate("ModCollectionsPanel", "Add to set"),
            ),
            (
                "folder",
                self.controller.collections.folders,
                translate("ModCollectionsPanel", "Move to folder"),
            ),
        ):
            submenu = menu.addMenu(title)
            submenu.setEnabled(bool(paths))
            for key, group in groups.items():
                action = submenu.addAction(group.name)
                action.triggered.connect(
                    lambda checked=False, kind=kind, key=key: self.assign(
                        paths, kind, key
                    )
                )
        detach = menu.addAction(
            translate("ModCollectionsPanel", "Remove selected mods from groups")
        )
        detach.setEnabled(bool(paths))
        detach.triggered.connect(lambda: self.controller.detach(paths))
        try:
            menu.exec(
                self.organize_button.mapToGlobal(
                    self.organize_button.rect().bottomLeft()
                )
            )
        finally:
            menu.deleteLater()

    def assign(self, paths: list[str], kind: str, key: str) -> None:
        self.controller.assign(paths, kind, key, self.selected_sets())

    def selected_sets(self) -> list[str]:
        if self.mode.currentIndex() != 1:
            return []
        return [
            key
            for node in self.tree.selectedItems()
            for kind, key in [node.data(0, Qt.ItemDataRole.UserRole)]
            if kind == "set"
        ]

    def context_menu(self, position: QPoint) -> None:
        node = self.tree.itemAt(position)
        if node is None:
            return
        kind, key = node.data(0, Qt.ItemDataRole.UserRole)
        if kind == "ungrouped":
            return
        if not node.isSelected():
            self.tree.clearSelection()
            node.setSelected(True)
        menu = QMenu(self)
        paths = self.controller.collections.members(kind, key)
        for label, enabled in (
            (translate("ModCollectionsPanel", "Enable all members"), True),
            (translate("ModCollectionsPanel", "Disable all members"), False),
        ):
            menu.addAction(label).triggered.connect(
                lambda checked=False, enabled=enabled: self.controller.set_enabled(
                    paths, enabled
                )
            )
        menu.addAction(
            translate("ModCollectionsPanel", "Organize selected mods")
        ).triggered.connect(self.organize_menu)
        if kind == "set":
            submenu = menu.addMenu(translate("ModCollectionsPanel", "Move to folder"))
            destinations = [("", translate("ModCollectionsPanel", "No folder"))]
            destinations.extend(
                (key, folder.name)
                for key, folder in self.controller.collections.folders.items()
            )
            for folder_key, name in destinations:
                submenu.addAction(name).triggered.connect(
                    lambda checked=False, folder_key=folder_key: (
                        self.controller.move_set(key, folder_key)
                    )
                )
        if kind in ("set", "folder"):
            menu.addAction(
                translate("ModCollectionsPanel", "Rename")
            ).triggered.connect(lambda: self.rename(kind, key))
            menu.addAction(
                translate("ModCollectionsPanel", "Delete group (keep mods)")
            ).triggered.connect(lambda: self.controller.delete(kind, key))
        try:
            menu.exec(
                self.tree.viewport().mapToGlobal(
                    self.tree.visualItemRect(node).bottomLeft()
                )
            )
        finally:
            menu.deleteLater()

    def rename(self, kind: str, key: str) -> None:
        group = self.controller.collections.group(kind, key)
        name, accepted = QInputDialog.getText(
            self,
            translate("ModCollectionsPanel", "Rename"),
            translate("ModCollectionsPanel", "Name:"),
            text=group.name,
        )
        if accepted and name.strip():
            self.controller.rename(kind, key, name)

    def toggle_item(self, node: QTreeWidgetItem, column: int) -> None:
        if column == 0:
            kind, key = node.data(0, Qt.ItemDataRole.UserRole)
            if kind != "ungrouped":
                self.controller.set_enabled(
                    self.controller.collections.members(kind, key),
                    node.checkState(0) != Qt.CheckState.Unchecked,
                )
