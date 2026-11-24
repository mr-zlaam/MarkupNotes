"""Comprehensive tests for drag-and-drop, cut/copy/paste, pin guards, replace modal, and Ctrl+Z undo."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

from core.config import ConfigManager
from core.note import Note
from core.storage import StorageManager
from ui.main_window import MainWindow
from utils.paths import is_invalid_folder_transfer, resolve_copy_target_path

app = QApplication.instance() or QApplication([])


class TestFileOpsDragClipboardUndo(unittest.TestCase):
    """Verify note/folder move, copy, collision naming, replace modal, pin guards, and Ctrl+Z undo."""

    def _make_window(self, root: Path) -> MainWindow:
        cfg_dir = root / ".test_cfg"
        cfg_dir.mkdir(exist_ok=True)
        config_mgr = ConfigManager(config_file=cfg_dir / "settings.json")
        storage = StorageManager(root)
        win = MainWindow(storage_manager=storage, config_manager=config_mgr)
        return win

    def test_copy_collision_naming_copy_copy1_copy2(self) -> None:
        """Verify repeated copies into the same directory generate copy, copy1, copy2 suffixes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "Spec.md"
            note.write_text("# Spec", encoding="utf-8")

            c0 = resolve_copy_target_path(root, "Spec.md", is_dir=False)
            self.assertEqual(c0.name, "Spec copy.md")
            c0.write_text("# Spec", encoding="utf-8")

            c1 = resolve_copy_target_path(root, "Spec.md", is_dir=False)
            self.assertEqual(c1.name, "Spec copy1.md")
            c1.write_text("# Spec", encoding="utf-8")

            c2 = resolve_copy_target_path(root, "Spec.md", is_dir=False)
            self.assertEqual(c2.name, "Spec copy2.md")

            folder = root / "Work"
            folder.mkdir()
            f0 = resolve_copy_target_path(root, "Work", is_dir=True)
            self.assertEqual(f0.name, "Work copy")
            f0.mkdir()
            f1 = resolve_copy_target_path(root, "Work", is_dir=True)
            self.assertEqual(f1.name, "Work copy1")

    def test_move_and_copy_note_via_drop_and_undo_with_ctrl_z(self) -> None:
        """Verify dragging a note to a folder moves it, Ctrl+drop copies it, and Ctrl+Z undoes both."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder_a = root / "FolderA"
            folder_b = root / "FolderB"
            folder_a.mkdir()
            folder_b.mkdir()
            note_a = folder_a / "Draft.md"
            note_a.write_text("Hello world", encoding="utf-8")

            win = self._make_window(root)
            try:
                # 1. Drop move FolderA/Draft.md -> FolderB
                win._on_sidebar_item_dropped("note", note_a, folder_b, False)
                moved_path = folder_b / "Draft.md"
                self.assertFalse(note_a.exists())
                self.assertTrue(moved_path.exists())

                # 2. Ctrl+Drop copy FolderB/Draft.md -> FolderB (auto-renames to Draft copy.md)
                win._on_sidebar_item_dropped("note", moved_path, folder_b, True)
                copied_path = folder_b / "Draft copy.md"
                self.assertTrue(copied_path.exists())
                self.assertEqual(copied_path.read_text(encoding="utf-8"), "Hello world")

                # 3. Undo Copy -> removes Draft copy.md
                win._on_undo_file_operation()
                self.assertFalse(copied_path.exists())
                self.assertTrue(moved_path.exists())

                # 4. Undo Move -> restores FolderA/Draft.md
                win._on_undo_file_operation()
                self.assertTrue(note_a.exists())
                self.assertFalse(moved_path.exists())
            finally:
                win.close()
                win.deleteLater()

    def test_move_folder_into_folder_and_prevent_cycle(self) -> None:
        """Verify moving a folder into another folder works, cycles are blocked, and undo restores it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "Parent"
            child = parent / "Child"
            target = root / "Archive"
            child.mkdir(parents=True)
            target.mkdir()
            (child / "deep.md").write_text("Deep content", encoding="utf-8")

            self.assertTrue(is_invalid_folder_transfer(parent, parent))
            self.assertTrue(is_invalid_folder_transfer(parent, child))
            self.assertFalse(is_invalid_folder_transfer(parent, target))

            win = self._make_window(root)
            try:
                # Invalid cycle move is ignored
                win._on_sidebar_item_dropped("folder", parent, child, False)
                self.assertTrue(parent.exists())

                # Valid move Parent -> Archive/Parent
                win._on_sidebar_item_dropped("folder", parent, target, False)
                moved = target / "Parent"
                self.assertFalse(parent.exists())
                self.assertTrue((moved / "Child" / "deep.md").exists())

                # Undo restores Parent at root with nested contents intact
                win._on_undo_file_operation()
                self.assertTrue((parent / "Child" / "deep.md").exists())
                self.assertFalse(moved.exists())
            finally:
                win.close()
                win.deleteLater()

    def test_move_collision_prompts_replace_modal_and_undo_restores_both(self) -> None:
        """Verify VS Code-style replace confirmation on move collision and full restoration on undo."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src_dir = root / "Inbox"
            dst_dir = root / "Done"
            src_dir.mkdir()
            dst_dir.mkdir()
            src_note = src_dir / "Same.md"
            dst_note = dst_dir / "Same.md"
            src_note.write_text("NEW VERSION", encoding="utf-8")
            dst_note.write_text("OLD VERSION", encoding="utf-8")

            win = self._make_window(root)
            try:
                # 1. Cancel replace -> nothing changes
                with patch("ui.main_window.ModernConfirmDialog.ask", return_value=False) as mock_ask:
                    win._on_sidebar_item_dropped("note", src_note, dst_dir, False)
                    self.assertTrue(mock_ask.called)
                self.assertTrue(src_note.exists())
                self.assertEqual(dst_note.read_text(encoding="utf-8"), "OLD VERSION")

                # 2. Confirm replace -> replaces destination with source
                with patch("ui.main_window.ModernConfirmDialog.ask", return_value=True):
                    win._on_sidebar_item_dropped("note", src_note, dst_dir, False)
                self.assertFalse(src_note.exists())
                self.assertEqual(dst_note.read_text(encoding="utf-8"), "NEW VERSION")

                # 3. Undo -> restores NEW VERSION to Inbox and OLD VERSION back to Done!
                win._on_undo_file_operation()
                self.assertTrue(src_note.exists())
                self.assertEqual(src_note.read_text(encoding="utf-8"), "NEW VERSION")
                self.assertEqual(dst_note.read_text(encoding="utf-8"), "OLD VERSION")
            finally:
                win.close()
                win.deleteLater()

    def test_pinned_note_and_folder_cannot_be_moved_or_cut_but_can_be_copied(self) -> None:
        """Verify pinned notes, pinned folders, and folders containing pinned notes block move/cut."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder_a = root / "FolderA"
            folder_b = root / "FolderB"
            folder_a.mkdir()
            folder_b.mkdir()
            pinned_note = folder_a / "Important.md"
            pinned_note.write_text("Pinned!", encoding="utf-8")

            win = self._make_window(root)
            try:
                note_obj = Note.from_file(pinned_note)
                assert note_obj is not None
                win._on_toggle_pin_note(note_obj)

                # Cutting pinned note shows warning and does not set clipboard
                with patch("ui.main_window.ModernMessageDialog.show_info") as mock_warn:
                    win._on_cut_note(note_obj)
                    self.assertEqual(mock_warn.call_count, 1)
                self.assertIsNone(win._clipboard_item)

                # Moving pinned note shows warning and leaves file in place
                with patch("ui.main_window.ModernMessageDialog.show_info") as mock_warn:
                    win._on_sidebar_item_dropped("note", pinned_note, folder_b, False)
                    self.assertEqual(mock_warn.call_count, 1)
                self.assertTrue(pinned_note.exists())
                self.assertFalse((folder_b / "Important.md").exists())

                # Moving folder containing pinned note is also blocked with warning
                with patch("ui.main_window.ModernMessageDialog.show_info") as mock_warn:
                    win._on_sidebar_item_dropped("folder", folder_a, folder_b, False)
                    self.assertEqual(mock_warn.call_count, 1)
                self.assertTrue(folder_a.exists())

                # Copying pinned note IS allowed and creates an unpinned copy
                win._on_copy_note(note_obj)
                win._on_paste_into_folder(folder_b)
                copied = folder_b / "Important.md"
                self.assertTrue(copied.exists())
                self.assertFalse(win._is_note_pinned_path(copied))
            finally:
                win.close()
                win.deleteLater()

    def test_cut_copy_paste_workflow_for_notes_and_folders(self) -> None:
        """Verify Cut+Paste moves and clears clipboard, Copy+Paste keeps clipboard and copies."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder_a = root / "A"
            folder_b = root / "B"
            folder_a.mkdir()
            folder_b.mkdir()
            note_a = folder_a / "Item.md"
            note_a.write_text("Body", encoding="utf-8")

            win = self._make_window(root)
            try:
                note_obj = Note.from_file(note_a)
                assert note_obj is not None

                # Cut + Paste moves note and clears clipboard
                win._on_cut_note(note_obj)
                self.assertIsNotNone(win._clipboard_item)
                self.assertEqual(win.note_list._cut_path, note_a)
                win._on_paste_into_folder(folder_b)
                self.assertFalse(note_a.exists())
                self.assertTrue((folder_b / "Item.md").exists())
                self.assertIsNone(win._clipboard_item)
                self.assertIsNone(win.note_list._cut_path)

                # Copy folder B -> Paste into root creates 'B copy'
                win._on_copy_folder(folder_b)
                win._on_paste_into_folder(None)
                self.assertTrue((root / "B copy" / "Item.md").exists())
                # Clipboard remains populated after copy-paste
                self.assertIsNotNone(win._clipboard_item)
            finally:
                win.close()
                win.deleteLater()


if __name__ == "__main__":
    unittest.main()
