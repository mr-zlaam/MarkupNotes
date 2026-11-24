"""Unit tests for cascading folder selection, recursive batch deletion, and All Notes click after cancel."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from core.storage import StorageManager
from ui.sidebar import FolderSidebar
from utils.paths import prune_nested_paths

app = QApplication.instance() or QApplication([])


class TestFolderSelectionCascade(unittest.TestCase):
    """Verify nested child auto-selection, intact recursive trash deletion, and All Notes recovery."""

    def test_enter_selection_mode_auto_selects_nested_descendants(self) -> None:
        """Selecting a parent folder in selection mode automatically selects all deeply nested subfolders."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "Parent"
            child = parent / "Child"
            grandchild = child / "Grandchild"
            sibling = root / "Sibling"
            grandchild.mkdir(parents=True)
            sibling.mkdir()

            sidebar = FolderSidebar()
            sidebar.set_folders([parent, child, grandchild, sibling], current_selection=parent)

            sidebar.enter_selection_mode(initial_folder=parent)
            self.assertEqual(sidebar._selected_folders, {parent, child, grandchild})
            self.assertNotIn(sibling, sidebar._selected_folders)

            # Clicking Child while selected deselects Child, Grandchild, and unchecks Parent
            child_item = None
            parent_item = sidebar.tree_widget.topLevelItem(1)
            for i in range(parent_item.childCount()):
                if parent_item.child(i).data(0, Qt.ItemDataRole.UserRole) == child:
                    child_item = parent_item.child(i)
                    break
            self.assertIsNotNone(child_item)
            sidebar._on_item_clicked(child_item, 0)
            self.assertEqual(sidebar._selected_folders, set())

            # Clicking Parent again re-selects Parent and all nested descendants
            parent_item = sidebar.tree_widget.topLevelItem(1)
            sidebar._on_item_clicked(parent_item, 0)
            self.assertEqual(sidebar._selected_folders, {parent, child, grandchild})

            sidebar.deleteLater()

    def test_cancel_selection_restores_folder_and_clicking_all_notes_works(self) -> None:
        """Exiting selection mode restores previous focus and clicking All Notes emits folder_selected(None)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "Work"
            work.mkdir()

            sidebar = FolderSidebar()
            sidebar.set_folders([work], current_selection=work)

            emitted: list[object] = []
            sidebar.folder_selected.connect(emitted.append)

            sidebar.enter_selection_mode(initial_folder=work)
            sidebar.exit_selection_mode()

            # Focus should be restored to Work, not silently reset to All Notes
            self.assertEqual(
                sidebar.tree_widget.currentItem().data(0, Qt.ItemDataRole.UserRole),
                work,
            )

            # Clicking All Notes must emit folder_selected(None)
            all_notes_item = sidebar.tree_widget.topLevelItem(0)
            sidebar.tree_widget.setCurrentItem(all_notes_item)
            sidebar._on_item_clicked(all_notes_item, 0)
            self.assertIn(None, emitted)
            self.assertIsNone(emitted[-1])

            # Even if All Notes was already currentItem, clicking it still emits folder_selected(None)
            emitted.clear()
            sidebar._on_item_clicked(all_notes_item, 0)
            self.assertEqual(emitted, [None])

            sidebar.deleteLater()

    def test_batch_delete_moves_parent_tree_intact_to_trash(self) -> None:
        """Deleting a parent and its auto-selected nested children moves the full tree intact to .trash."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = StorageManager(root)
            parent = root / "Projects"
            child = parent / "Alpha"
            grandchild = child / "Deep"
            grandchild.mkdir(parents=True)
            note_file = grandchild / "spec.md"
            note_file.write_text("# Deep Note", encoding="utf-8")

            # Pass child/grandchild BEFORE parent to verify pruning prevents splitting
            pruned = prune_nested_paths([grandchild, child, parent])
            self.assertEqual(pruned, [parent])

            deleted = storage.delete_folders_batch([grandchild, child, parent])
            self.assertEqual(deleted, 1)
            self.assertFalse(parent.exists())

            trash_dir = root / ".trash"
            trashed_notes = list(trash_dir.rglob("spec.md"))
            self.assertEqual(len(trashed_notes), 1)
            self.assertIn("Alpha", trashed_notes[0].parts)
            self.assertIn("Deep", trashed_notes[0].parts)


if __name__ == "__main__":
    unittest.main()
