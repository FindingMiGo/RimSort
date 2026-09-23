"""Collection membership is independent of mod metadata and activation."""

from collections.abc import Callable

import msgspec
import pytest

from app.models.instance import Instance
from app.models.mod_collections import ModCollections, ModFolder, ModSet


@pytest.fixture
def collections() -> ModCollections:
    return ModCollections(
        sets={
            "first": ModSet("Main and translation", ["main", "translation"], "series"),
            "second": ModSet("Other mods", ["addon"]),
            "empty": ModSet("Empty"),
        },
        folders={
            "series": ModFolder("Series", ["standalone"]),
            "themes": ModFolder("Themes"),
        },
    )


@pytest.mark.parametrize("kind", ["set", "folder"])
def test_create_and_rename_normalize_names(kind: str) -> None:
    groups = ModCollections()
    key = groups.create(kind, "  New group  ")
    group = groups.group(kind, key)
    assert group.name == "New group"
    groups.rename(kind, key, "  Renamed  ")
    assert groups.group(kind, key) is group
    assert group.name == "Renamed"


def test_assign_set_keeps_one_membership(collections: ModCollections) -> None:
    collections.assign_set(
        ["translation", "standalone", "unrelated", "translation"], "second"
    )
    assert collections.sets["first"].members == ["main"]
    assert collections.folders["series"].members == []
    assert collections.sets["second"].members == [
        "addon",
        "translation",
        "standalone",
        "unrelated",
    ]
    assert collections.set_for("translation") == "second"
    assert collections.set_for("missing") == ""
    assert collections.labels()["main"] == "Series / Main and translation"


def test_adding_to_set_preserves_existing_representative_and_children(
    collections: ModCollections,
) -> None:
    collections.assign_set(["main", "addon", "translation"], "first")

    assert collections.sets["first"].members == ["main", "translation", "addon"]
    assert collections.sets["second"].members == []


def test_folder_moves_include_whole_sets(collections: ModCollections) -> None:
    collections.move_to_folder(
        ["translation", "standalone", "main", "standalone"], "themes"
    )
    assert collections.sets["first"].folder == "themes"
    assert collections.folders["series"].members == []
    assert collections.members("folder", "themes") == [
        "standalone",
        "main",
        "translation",
    ]
    assert collections.members("set", "first") == ["main", "translation"]
    assert collections.members("mod", "standalone") == ["standalone"]
    assert collections.labels()["translation"] == "Themes / Main and translation"
    collections.move_to_folder(["translation", "standalone"], "")
    assert collections.sets["first"].folder == ""
    assert collections.folders["themes"].members == []


def test_empty_set_moves_without_members(collections: ModCollections) -> None:
    collections.move_set("empty", "series")
    assert collections.sets["empty"].folder == "series"
    collections.move_set("empty", "")
    assert collections.sets["empty"] == ModSet("Empty")


def test_detach_and_delete_preserve_other_members(collections: ModCollections) -> None:
    collections.detach(["translation", "missing"])
    assert collections.sets["first"].members == ["main"]
    collections.delete("set", "first")
    assert collections.folders["series"].members == ["standalone", "main"]
    collections.move_set("second", "series")
    collections.delete("folder", "series")
    assert collections.sets["second"] == ModSet("Other mods", ["addon"])
    assert collections.sets["empty"] == ModSet("Empty")
    assert collections.labels() == {"addon": "Other mods"}


@pytest.mark.parametrize(
    ("operation", "error"),
    [
        (lambda groups: groups.create("unknown", "Name"), ValueError),
        (lambda groups: groups.create("set", " \t "), ValueError),
        (lambda groups: groups.group("unknown", "series"), ValueError),
        (lambda groups: groups.members("unknown", "series"), ValueError),
        (lambda groups: groups.delete("unknown", "series"), ValueError),
        (lambda groups: groups.rename("unknown", "series", "Name"), ValueError),
        (lambda groups: groups.rename("set", "first", " \n "), ValueError),
        (lambda groups: groups.rename("folder", "series", ""), ValueError),
        (lambda groups: groups.rename("set", "missing", "Name"), KeyError),
        (lambda groups: groups.assign_set(["main"], "missing"), KeyError),
        (lambda groups: groups.move_set("first", "missing"), KeyError),
        (lambda groups: groups.move_set("missing", "series"), KeyError),
        (
            lambda groups: groups.move_to_folder(["main", "standalone"], "missing"),
            KeyError,
        ),
    ],
)
def test_invalid_operations_leave_collections_unchanged(
    collections: ModCollections,
    operation: Callable[[ModCollections], object],
    error: type[Exception],
) -> None:
    before = msgspec.json.encode(collections)
    with pytest.raises(error):
        operation(collections)
    assert msgspec.json.encode(collections) == before


def test_instance_roundtrip_and_independent_defaults(
    collections: ModCollections,
) -> None:
    legacy = msgspec.json.decode(b"{}", type=Instance)
    current = Instance(mod_collections=collections)
    restored = msgspec.json.decode(msgspec.json.encode(current), type=Instance)
    assert restored.mod_collections == collections
    assert legacy.mod_collections == ModCollections()
    legacy.mod_collections.create("set", "Legacy instance")
    assert Instance().mod_collections == ModCollections()
    assert current.mod_collections == collections
