"""User-defined organization, independent of load order and dependencies."""

from uuid import uuid4

import msgspec


class ModSet(msgspec.Struct):
    name: str
    members: list[str] = msgspec.field(default_factory=list)
    folder: str = ""


class ModFolder(msgspec.Struct):
    name: str
    members: list[str] = msgspec.field(default_factory=list)


class ModCollections(msgspec.Struct):
    sets: dict[str, ModSet] = msgspec.field(default_factory=dict)
    folders: dict[str, ModFolder] = msgspec.field(default_factory=dict)

    @staticmethod
    def _name(name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Collection names must not be empty")
        return name

    def group(self, kind: str, key: str) -> ModSet | ModFolder:
        if kind == "set":
            return self.sets[key]
        if kind == "folder":
            return self.folders[key]
        raise ValueError("Unknown collection kind")

    def create(self, kind: str, name: str) -> str:
        name = self._name(name)
        key = str(uuid4())
        if kind == "set":
            self.sets[key] = ModSet(name)
        elif kind == "folder":
            self.folders[key] = ModFolder(name)
        else:
            raise ValueError("Unknown collection kind")
        return key

    def rename(self, kind: str, key: str, name: str) -> None:
        group = self.group(kind, key)
        group.name = self._name(name)

    def set_for(self, path: str) -> str:
        return next(
            (key for key, group in self.sets.items() if path in group.members), ""
        )

    def members(self, kind: str, key: str) -> list[str]:
        if kind == "mod":
            return [key]
        group = self.group(kind, key)
        paths = list(group.members)
        if isinstance(group, ModFolder):
            for member_set in self.sets.values():
                if member_set.folder == key:
                    paths.extend(member_set.members)
        return list(dict.fromkeys(paths))

    def detach(self, paths: list[str]) -> None:
        selected = set(paths)
        groups: list[ModSet | ModFolder] = [*self.sets.values(), *self.folders.values()]
        for group in groups:
            group.members = [path for path in group.members if path not in selected]

    def assign_set(self, paths: list[str], key: str) -> None:
        group = self.sets[key]
        existing = set(group.members)
        new_paths = [path for path in dict.fromkeys(paths) if path not in existing]
        self.detach(new_paths)
        group.members.extend(new_paths)

    def _validate_folder(self, key: str) -> None:
        if key and key not in self.folders:
            raise KeyError(key)

    def move_set(self, key: str, folder: str) -> None:
        group = self.sets[key]
        self._validate_folder(folder)
        group.folder = folder

    def move_to_folder(self, paths: list[str], key: str) -> None:
        self._validate_folder(key)
        owners = {path: group for group in self.sets.values() for path in group.members}
        standalone = []
        for path in dict.fromkeys(paths):
            group = owners.get(path)
            if group is not None:
                group.folder = key
            else:
                standalone.append(path)
        self.detach(standalone)
        if key:
            self.folders[key].members.extend(standalone)

    def delete(self, kind: str, key: str) -> None:
        group = self.group(kind, key)
        if isinstance(group, ModSet):
            del self.sets[key]
            if group.folder in self.folders:
                self.folders[group.folder].members.extend(group.members)
        else:
            del self.folders[key]
            for member_set in self.sets.values():
                if member_set.folder == key:
                    member_set.folder = ""

    def labels(self) -> dict[str, str]:
        result = {
            path: folder.name
            for folder in self.folders.values()
            for path in folder.members
        }
        for group in self.sets.values():
            folder = self.folders.get(group.folder)
            label = f"{folder.name} / {group.name}" if folder else group.name
            result.update(dict.fromkeys(group.members, label))
        return result
