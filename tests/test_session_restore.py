"""Integration tests verifying last active folder, note, cursor, and scroll restoration across launches."""

import sys
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ConfigManager
from core.storage import StorageManager
from ui.main_window import MainWindow


class TestSessionRestore(unittest.TestCase):
    """Verify MainWindow persists and restores last folder, nested subfolder, note, and caret."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.notes_dir = self.root_dir / "notes"
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.root_dir / "config" / "settings.json"
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

        # Populate multiple folders and notes so we never rely on default first-row coincidence
        (self.notes_dir / "RootNote.md").write_text("Root body", encoding="utf-8")
        work_dir = self.notes_dir / "Work"
        sub_dir = work_dir / "Projects"
        sub_dir.mkdir(parents=True)
        (work_dir / "Alpha.md").write_text("Alpha body text", encoding="utf-8")
        (work_dir / "Beta.md").write_text("Beta body text with extra words here", encoding="utf-8")
        (sub_dir / "Roadmap.md").write_text("Nested roadmap content", encoding="utf-8")
        (self.notes_dir / "EmptyFolder").mkdir()

        self.storage = StorageManager(root_dir=self.notes_dir)

    def tearDown(self) -> None:
        self.app.processEvents()
        self.temp_dir.cleanup()

    def _new_window(self) -> MainWindow:
        cfg = ConfigManager(config_file=self.config_file)
        win = MainWindow(storage_manager=self.storage, config_manager=cfg)
        self.app.processEvents()
        return win

    def test_restores_last_folder_note_and_cursor_on_relaunch(self) -> None:
        """Closing inside Work/Alpha.md restores exact folder, note, and cursor position."""
        win1 = self._new_window()
        work_dir = self.notes_dir / "Work"
        alpha_path = work_dir / "Alpha.md"
        win1._on_folder_selected(work_dir)
        self.app.processEvents()

        # Select Alpha.md specifically (even if Beta.md has newer mtime or vice versa)
        alpha_note = next(n for n in win1._all_current_notes if n.path == alpha_path)
        win1._on_note_selected(alpha_note)
        self.app.processEvents()

        cur = win1.editor.editor.textCursor()
        cur.setPosition(7)
        win1.editor.editor.setTextCursor(cur)
        win1.close()
        win1.deleteLater()
        self.app.processEvents()

        # Relaunch new window using saved settings.json
        win2 = self._new_window()
        try:
            self.assertEqual(win2._current_folder, work_dir)
            self.assertIsNotNone(win2._current_note)
            self.assertEqual(win2._current_note.path, alpha_path)
            self.assertEqual(win2.editor.editor.toPlainText(), "Alpha body text")
            self.assertEqual(win2.editor.editor.textCursor().position(), 7)

            sidebar_item = win2.sidebar.tree_widget.currentItem()
            self.assertIsNotNone(sidebar_item)
            self.assertEqual(sidebar_item.data(0, Qt.ItemDataRole.UserRole), work_dir)
        finally:
            win2.close()
            win2.deleteLater()

    def test_restores_nested_subfolder_and_empty_folder(self) -> None:
        """Restoring a nested subfolder selects it cleanly; closing in an empty folder stays in that folder."""
        win1 = self._new_window()
        sub_dir = self.notes_dir / "Work" / "Projects"
        win1._on_folder_selected(sub_dir)
        self.app.processEvents()
        win1.close()
        win1.deleteLater()
        self.app.processEvents()

        win2 = self._new_window()
        try:
            self.assertEqual(win2._current_folder, sub_dir)
            self.assertIsNotNone(win2._current_note)
            self.assertEqual(win2._current_note.path, sub_dir / "Roadmap.md")

            # Switch to EmptyFolder and close
            empty_dir = self.notes_dir / "EmptyFolder"
            win2._on_folder_selected(empty_dir)
            self.app.processEvents()
            self.assertIsNone(win2._current_note)
        finally:
            win2.close()
            win2.deleteLater()
            self.app.processEvents()

        win3 = self._new_window()
        try:
            self.assertEqual(win3._current_folder, self.notes_dir / "EmptyFolder")
            self.assertIsNone(win3._current_note)
            self.assertEqual(list((self.notes_dir / "EmptyFolder").glob("*.md")), [])
        finally:
            win3.close()
            win3.deleteLater()

    def test_restores_all_notes_view_and_handles_deleted_targets_gracefully(self) -> None:
        """Closing in All Notes preserves All Notes; deleted saved note/folder falls back cleanly."""
        win1 = self._new_window()
        work_alpha = self.notes_dir / "Work" / "Alpha.md"
        win1._on_folder_selected(None)  # All Notes
        self.app.processEvents()
        target_note = next(n for n in win1._all_current_notes if n.path == work_alpha)
        win1._on_note_selected(target_note)
        self.app.processEvents()
        win1.close()
        win1.deleteLater()
        self.app.processEvents()

        win2 = self._new_window()
        try:
            self.assertIsNone(win2._current_folder)
            self.assertIsNotNone(win2._current_note)
            self.assertEqual(win2._current_note.path, work_alpha)
        finally:
            win2.close()
            win2.deleteLater()
            self.app.processEvents()

        # Delete the saved file externally before relaunch -> must not crash
        work_alpha.unlink()
        win3 = self._new_window()
        try:
            self.assertIsNone(win3._current_folder)
            self.assertIsNotNone(win3._current_note)
            self.assertNotEqual(win3._current_note.path, work_alpha)
        finally:
            win3.close()
            win3.deleteLater()

    def test_collapse_expand_all_folders_button_ctrl_left_and_persistence(self) -> None:
        """Verify collapse/expand all button, Ctrl+Left shortcut, and folder state persistence across launches."""
        deep_dir = self.notes_dir / "Work" / "Projects" / "Sprint1"
        deep_dir.mkdir(parents=True, exist_ok=True)
        personal_sub = self.notes_dir / "Personal" / "Journal"
        personal_sub.mkdir(parents=True, exist_ok=True)

        # 1. First launch: folders start expanded and Collapse All button shows Collapse state
        win1 = self._new_window()
        win1.show()
        self.app.processEvents()
        self.assertFalse(win1.sidebar.are_all_folders_collapsed())
        self.assertEqual(win1.sidebar.collapse_all_btn.toolTip(), "Collapse All Folders (Ctrl+Left)")

        # Click Collapse All button -> collapses every expandable folder
        win1.sidebar.collapse_all_btn.click()
        self.app.processEvents()
        self.assertTrue(win1.sidebar.are_all_folders_collapsed())
        self.assertEqual(win1.sidebar.collapse_all_btn.toolTip(), "Expand All Folders (Ctrl+Left)")
        win1.close()
        win1.deleteLater()
        self.app.processEvents()

        # 2. Relaunch: collapsed state must be preserved
        win2 = self._new_window()
        win2.show()
        self.app.processEvents()
        try:
            self.assertTrue(win2.sidebar.are_all_folders_collapsed())
            self.assertEqual(win2.sidebar.collapse_all_btn.toolTip(), "Expand All Folders (Ctrl+Left)")

            # Ctrl+Left from sidebar expands all
            QTest.keyClick(win2.sidebar.tree_widget, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
            self.app.processEvents()
            self.assertFalse(win2.sidebar.are_all_folders_collapsed())

            # Ctrl+Left from editor also toggles back to collapsed, then expanded again
            QTest.keyClick(win2.editor.editor, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
            self.app.processEvents()
            self.assertTrue(win2.sidebar.are_all_folders_collapsed())

            QTest.keyClick(win2.editor.editor, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
            self.app.processEvents()
            self.assertFalse(win2.sidebar.are_all_folders_collapsed())
        finally:
            win2.close()
            win2.deleteLater()
            self.app.processEvents()

        # 3. Relaunch after leaving expanded -> folders remain expanded
        win3 = self._new_window()
        try:
            self.assertFalse(win3.sidebar.are_all_folders_collapsed())

            # Collapse only 'Personal', keep 'Work' expanded
            personal_item = next(
                win3.sidebar.tree_widget.topLevelItem(i)
                for i in range(win3.sidebar.tree_widget.topLevelItemCount())
                if win3.sidebar.tree_widget.topLevelItem(i).text(0) == "Personal"
            )
            personal_item.setExpanded(False)
            self.app.processEvents()
        finally:
            win3.close()
            win3.deleteLater()
            self.app.processEvents()

        # 4. Relaunch verifies mixed per-folder expansion state is preserved
        win4 = self._new_window()
        try:
            items_by_name = {
                win4.sidebar.tree_widget.topLevelItem(i).text(0): win4.sidebar.tree_widget.topLevelItem(i)
                for i in range(win4.sidebar.tree_widget.topLevelItemCount())
            }
            self.assertFalse(items_by_name["Personal"].isExpanded())
            self.assertTrue(items_by_name["Work"].isExpanded())
        finally:
            win4.close()
            win4.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
