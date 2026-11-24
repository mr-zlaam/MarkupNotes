"""Unit tests for workspace reload (Ctrl+R / F5 / sidebar refresh button) across multiple instances."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication

from core.config import ConfigManager
from core.note import Note
from core.storage import StorageManager
from ui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


class TestReloadWorkspace(unittest.TestCase):
    """Verify reloading workspace syncs folders, notes, active file edits, deletions, and customizations."""

    def _make_window(self, vault: Path, cfg_file: Path) -> MainWindow:
        config_mgr = ConfigManager(config_file=cfg_file)
        storage = StorageManager(vault)
        return MainWindow(storage_manager=storage, config_manager=config_mgr)

    def test_reload_workspace_syncs_external_folders_notes_and_active_edits(self) -> None:
        """Simulates a second instance creating a folder/note and editing the open note on disk."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            folder_a = vault / "Work"
            folder_a.mkdir(parents=True)
            open_note_path = folder_a / "Spec.md"
            open_note_path.write_text("# Spec\nLine 1\nLine 2\n", encoding="utf-8")

            cfg_file = root / "settings.json"
            win = self._make_window(vault, cfg_file)
            try:
                self.assertIsNotNone(win.sidebar.reload_btn)

                # Open Spec.md and move cursor to position 10
                win._on_note_selected(Note.from_file(open_note_path))
                app.processEvents()
                cur = win.editor.editor.textCursor()
                cur.setPosition(10)
                win.editor.editor.setTextCursor(cur)

                # Simulate Instance 2 modifying Spec.md, adding a new folder, and adding a new note
                new_folder = vault / "FromInstance2"
                new_folder.mkdir()
                new_note = folder_a / "AddedByOther.md"
                new_note.write_text("# Added Externally", encoding="utf-8")
                open_note_path.write_text("# Spec\nLine 1 UPDATED\nLine 2\n", encoding="utf-8")

                # Trigger reload (same as clicking Refresh button or pressing Ctrl+R / F5)
                win.sidebar.reload_btn.click()
                app.processEvents()

                # 1. New folder appears in sidebar
                folder_names = {f.name for f in win.sidebar._folders}
                self.assertIn("FromInstance2", folder_names)

                # 2. New note appears in note list
                note_paths = {n.path for n in win.note_list._notes}
                self.assertIn(new_note, note_paths)

                # 3. Active open note picked up disk changes while preserving cursor position
                self.assertIn("Line 1 UPDATED", win.editor.get_content())
                self.assertEqual(win.editor.editor.textCursor().position(), 10)
            finally:
                win.close()
                win.deleteLater()

    def test_reload_workspace_clears_editor_if_active_note_deleted_externally(self) -> None:
        """If another instance deleted the open note, reloading clears the editor gracefully."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            vault.mkdir()
            note_path = vault / "Temp.md"
            note_path.write_text("Soon deleted", encoding="utf-8")

            win = self._make_window(vault, root / "settings.json")
            try:
                win._on_note_selected(Note.from_file(note_path))
                app.processEvents()
                self.assertEqual(win._current_note.path, note_path)

                # Delete file externally
                note_path.unlink()
                win.reload_workspace()
                app.processEvents()

                self.assertIsNone(win._current_note)
                self.assertEqual(win.editor.get_content(), "")
            finally:
                win.close()
                win.deleteLater()


if __name__ == "__main__":
    unittest.main()
