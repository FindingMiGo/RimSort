---
title: Mod Sets and Folders
layout: default
parent: User Guide
permalink: user-guide/mod-collections
---

# Mod Sets and Folders

Sets collect mods that you want to enable together, such as a main mod, its
translation and optional addons. Membership is entirely manual: mods do not need
to declare dependencies to belong to the same set.

Virtual folders organize sets and individual mods by theme or series. They do not
move files on disk. Each mod can belong to one set, and each set or standalone mod
can belong to one folder. Moving a set member to a folder moves the entire set.

## Create and organize

Select mods in the active or inactive lists and choose **Organize selected mods**.
Create a set or folder, or add the selection to an existing one. Choose
**Folders and sets** above the right list to see the hierarchy. Right-click a group
to rename, move or delete it. Deleting a group keeps its mods and their active state.
Deleting a folder also keeps its sets; deleting a set leaves its members in its
former folder.

The folder view includes inactive members and retains missing members as
**Not installed**. Empty sets can be moved using their right-click menu.

## Enable and disable

Check a set or folder to enable all its installed members. Uncheck it to disable
them. A folder includes both its standalone mods and the members of its sets.
Individual mod checkboxes affect only that mod. A partially checked group contains
both active and inactive or missing members.

Search and **Active only** filter the display. Group actions still apply to all
members, including hidden ones. Activation appends inactive members in their
existing list order and preserves the order of mods that were already active.
Dependency validation and sorting use the usual RimSort controls.

## Load order and storage

**Load order** remains the actual game order and shows folder/set membership beside
mod names. The folder view displays each active mod's load position separately.
Sorting changes those positions without changing membership. To manually reorder
mods, switch to **Load order**.

Organization is saved separately for each RimSort instance. It is independent of
mod-list imports and exports. This first version stores membership by installation
path: moving or reinstalling a mod at a different path requires adding the new
installation to its group. Folders have one level; nested folders are not supported.
