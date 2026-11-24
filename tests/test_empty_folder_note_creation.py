"""Tests ensuring empty folders allow immediate title and content note creation without freezing title_edit."""

import sys
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ConfigManager
from core.storage import StorageManager
from ui.main_window import MainWindow


class TestEmptyFolderNoteCreation(unittest.TestCase):
    """Integration tests for creating notes directly from title or body in an empty folder."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.notes_dir = self.root_dir / "notes"
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir = self.root_dir / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self.storage = StorageManager(root_dir=self.notes_dir)
        self.config_manager = ConfigManager(config_file=self.config_dir / "settings.json")
        self.window = MainWindow(storage_manager=self.storage, config_manager=self.config_manager)

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp_dir.cleanup()

    def test_empty_folder_keeps_title_enabled_and_body_creation_does_not_freeze_title(self) -> None:
        """Typing body content in a newly created empty folder must leave title_edit enabled and editable."""
        self.window._on_create_folder("Work")
        self.app.processEvents()

        self.assertEqual(self.window._current_folder, self.notes_dir / "Work")
        self.assertIsNone(self.window._current_note)
        self.assertTrue(self.window.editor.title_edit.isEnabled())
        self.assertEqual(self.window.editor.title_edit.text(), "")

        # Type directly in body editor without creating a file manually first
        self.window.editor.editor.setPlainText("Direct body text")
        self.window.editor._trigger_auto_save()
        self.app.processEvents()

        expected_file = self.notes_dir / "Work" / "Untitled.md"
        self.assertTrue(expected_file.exists())
        self.assertEqual(expected_file.read_text(encoding="utf-8"), "Direct body text")
        self.assertIsNotNone(self.window._current_note)
        self.assertTrue(
            self.window.editor.title_edit.isEnabled(),
            "title_edit must remain enabled after auto-creating a note from body content",
        )
        self.assertTrue(self.window.editor.export_btn.isEnabled())

        # Now user can immediately edit title and rename Untitled.md
        self.window.editor.title_edit.setText("Renamed Work Note")
        self.window.editor._flush_title_change()
        self.app.processEvents()

        renamed_file = self.notes_dir / "Work" / "Renamed Work Note.md"
        self.assertTrue(renamed_file.exists())
        self.assertFalse(expected_file.exists())
        self.assertEqual(renamed_file.read_text(encoding="utf-8"), "Direct body text")

    def test_typing_title_in_empty_folder_creates_markdown_file(self) -> None:
        """Typing a title directly in a new empty folder must generate <title>.md immediately."""
        self.window._on_create_folder("Ideas")
        self.app.processEvents()

        self.assertTrue(self.window.editor.title_edit.isEnabled())
        self.window.editor.title_edit.setText("First Idea")
        self.window.editor.title_edit.textEdited.emit("First Idea")
        self.window.editor._flush_title_change()
        self.app.processEvents()

        created_file = self.notes_dir / "Ideas" / "First Idea.md"
        self.assertTrue(created_file.exists())
        self.assertIsNotNone(self.window._current_note)
        self.assertEqual(self.window._current_note.path, created_file)
        self.assertTrue(self.window.editor.title_edit.isEnabled())
        self.assertTrue(self.window.editor.export_btn.isEnabled())

        # Moving to body editor and typing saves into that generated file
        self.window.editor._on_title_enter_or_down()
        self.window.editor.editor.setPlainText("# Body content")
        self.window.editor._trigger_auto_save()
        self.app.processEvents()

        self.assertEqual(created_file.read_text(encoding="utf-8"), "# Body content")


if __name__ == "__main__":
    unittest.main()
