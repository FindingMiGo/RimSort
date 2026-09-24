"""Coordinate collection persistence and the authoritative mod lists."""

import typing
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from app.controllers.metadata_controller import MetadataController
from app.models.mod_collections import ModCollections
from app.models.settings import Settings
from app.utils.custom_list_widget_item import CustomListWidgetItem
from app.utils.event_bus import EventBus

if typing.TYPE_CHECKING:
    from app.views.mods_panel import ModListWidget


class ModCollectionsController(QObject):
    changed = Signal()

    def __init__(
        self,
        settings: Settings,
        metadata: MetadataController,
        active_list: "ModListWidget",
        inactive_list: "ModListWidget",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.metadata = metadata
        self.active_list = active_list
        self.inactive_list = inactive_list
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)
        for source in (active_list, inactive_list):
            source.list_update_signal.connect(self.schedule_refresh)
            source.model().rowsMoved.connect(self.schedule_refresh)
            source.create_set_from_drop_signal.connect(self.create_set_from_drop)
            source.rename_collection_set_signal.connect(
                lambda key, name: self.rename("set", key, name)
            )
            source.delete_collection_set_signal.connect(
                lambda key: self.delete("set", key)
            )
            source.set_collection_enabled_signal.connect(
                lambda key, enabled: self.set_enabled(
                    self.collections.members("set", key), enabled
                )
            )
        EventBus().settings_have_changed.connect(self.schedule_refresh)
        self.schedule_refresh()

    @property
    def collections(self) -> ModCollections:
        return self.settings.instances[self.settings.current_instance].mod_collections

    @staticmethod
    def items(source: "ModListWidget") -> dict[str, CustomListWidgetItem]:
        return {
            item.data(Qt.ItemDataRole.UserRole)["path"]: item
            for item in source.get_all_mod_list_items()
        }

    def mod_name(self, path: str) -> str:
        mod = self.metadata.get_mod(path)
        return str(mod.name) if mod and mod.name else Path(path).name

    def schedule_refresh(self, *_args: object) -> None:
        self.timer.start(0)

    def refresh(self) -> None:
        self.timer.stop()
        list_items = [
            (source, self.items(source))
            for source in (self.active_list, self.inactive_list)
        ]
        available_paths = {path for _, items in list_items for path in items}
        if self._repair_renamed_members(self.collections, available_paths):
            self.settings.save()
        set_members = {
            path for group in self.collections.sets.values() for path in group.members
        }
        labels = {
            path: label
            for path, label in self.collections.labels().items()
            if path not in set_members
        }
        for source, items in list_items:
            source.update_collection_labels(labels, items)
        for source in (self.active_list, self.inactive_list):
            source.apply_collection_sets(self.collections)
        self.changed.emit()

    @staticmethod
    def _repair_renamed_members(
        collections: ModCollections, available_paths: set[str]
    ) -> bool:
        """Rebind Windows-invalid colon names renamed with an underscore."""
        changed = False
        member_owners = {
            path: key
            for key, group in collections.sets.items()
            for path in group.members
        }
        for key, group in collections.sets.items():
            group_changed = False
            for index, path in enumerate(group.members):
                if path in available_paths or "\uf03a" not in path:
                    continue
                candidate = path.replace("\uf03a", "_")
                if (
                    candidate in available_paths
                    and member_owners.get(candidate, key) == key
                ):
                    group.members[index] = candidate
                    member_owners[candidate] = key
                    group_changed = True
                    changed = True
            if group_changed:
                group.members = list(dict.fromkeys(group.members))
        return changed

    def _save(self) -> None:
        self.settings.save()
        self.refresh()

    def create(
        self, kind: str, name: str, paths: list[str], selected_sets: list[str]
    ) -> str:
        key = self.collections.create(kind, name)
        self.assign(paths, kind, key, selected_sets)
        return key

    def assign(
        self,
        paths: list[str],
        kind: str,
        key: str,
        selected_sets: list[str] | None = None,
    ) -> None:
        collections = self.collections
        collections.group(kind, key)
        if kind == "set":
            collections.assign_set(paths, key)
            members = collections.sets[key].members
            if members:
                active_paths = self.items(self.active_list)
                inactive_paths = self.items(self.inactive_list)
                representative = members[0]
                if representative in active_paths:
                    misplaced = [path for path in members if path in inactive_paths]
                    enabled = True
                elif representative in inactive_paths:
                    misplaced = [path for path in members if path in active_paths]
                    enabled = False
                else:
                    misplaced = []
                    enabled = False
                if misplaced:
                    self.settings.save()
                    self.set_enabled(misplaced, enabled)
                    return
        else:
            collections.move_to_folder(paths, key)
            for set_key in selected_sets or []:
                collections.move_set(set_key, key)
        self._save()

    def create_set_from_drop(self, paths: list[str], target_path: str) -> None:
        """Create a set, or add dropped mods to the target mod's existing set."""
        key = self.collections.set_for(target_path)
        if key:
            self.assign(paths, "set", key)
            return
        self.create(
            "set",
            self.mod_name(target_path),
            [target_path, *paths],
            [],
        )

    def detach(self, paths: list[str]) -> None:
        self.collections.detach(paths)
        self._save()

    def rename(self, kind: str, key: str, name: str) -> None:
        self.collections.rename(kind, key, name)
        self._save()

    def delete(self, kind: str, key: str) -> None:
        self.collections.delete(kind, key)
        self._save()

    def move_set(self, key: str, folder: str) -> None:
        self.collections.move_set(key, folder)
        self._save()

    def set_enabled(self, paths: list[str], enabled: bool) -> None:
        source, target = (
            (self.inactive_list, self.active_list)
            if enabled
            else (self.active_list, self.inactive_list)
        )
        requested = set(paths)
        moving = [
            item for path, item in self.items(source).items() if path in requested
        ]
        if moving:
            updates = source.updatesEnabled(), target.updatesEnabled()
            source.setUpdatesEnabled(False)
            target.setUpdatesEnabled(False)
            # Keep Qt's model notifications, but replace per-row application
            # updates with one notification after the complete batch.
            source.model().rowsAboutToBeRemoved.disconnect(source.handle_rows_removed)
            try:
                for item in moving:
                    path = item.data(Qt.ItemDataRole.UserRole)["path"]
                    if path in source.paths:
                        source.paths.remove(path)
                    source.takeItem(source.row(item))
                    target.addItem(item)
            finally:
                source.model().rowsAboutToBeRemoved.connect(
                    source.handle_rows_removed, Qt.ConnectionType.QueuedConnection
                )
                source.setUpdatesEnabled(updates[0])
                target.setUpdatesEnabled(updates[1])
            source.list_update_signal.emit(str(source.count()))
        self.schedule_refresh()
