"""Unit tests for global OS drag-and-drop of Markdown files and images."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage
from PyQt6.QtWidgets import QApplication

from core.config import ConfigManager
from core.storage import StorageManager
from ui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


class TestGlobalDragDrop(unittest.TestCase):
    """Verify OS drag-and-drop of Markdown files and images across MainWindow, Sidebar, NoteList, and Editor."""

    def _make_window(self, vault: Path, cfg_dir: Path) -> MainWindow:
        cfg_dir.mkdir(exist_ok=True)
        config_mgr = ConfigManager(config_file=cfg_dir / "settings.json")
        storage = StorageManager(vault)
        return MainWindow(storage_manager=storage, config_manager=config_mgr)

    def test_drop_external_markdown_onto_editor_imports_and_opens_note(self) -> None:
        """Dropping an external .md file onto the editor imports it into the active folder and opens it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            work = vault / "Work"
            work.mkdir(parents=True)

            ext_file = root / "ExternalNote.md"
            ext_file.write_text("# Imported Heading\nDropped from Nautilus.", encoding="utf-8")

            win = self._make_window(vault, root / "cfg")
            try:
                win._current_folder = work
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(ext_file))])

                drop_ev = QDropEvent(
                    QPointF(50.0, 50.0),
                    Qt.DropAction.CopyAction,
                    mime,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                win.editor.editor.dropEvent(drop_ev)
                app.processEvents()

                imported = work / "ExternalNote.md"
                self.assertTrue(imported.is_file())
                self.assertEqual(
                    imported.read_text(encoding="utf-8"),
                    "# Imported Heading\nDropped from Nautilus.",
                )
                self.assertIsNotNone(win._current_note)
                self.assertEqual(win._current_note.path, imported)
                self.assertIn("Dropped from Nautilus.", win.editor.get_content())
            finally:
                win.close()
                win.deleteLater()

    def test_drop_external_markdown_onto_sidebar_folder_imports_into_target_folder(self) -> None:
        """Dropping an external .md file onto a specific folder in FolderSidebar imports it there."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            folder_a = vault / "Alpha"
            folder_b = vault / "Beta"
            folder_a.mkdir(parents=True)
            folder_b.mkdir(parents=True)

            ext_file = root / "Guide.md"
            ext_file.write_text("# Guide", encoding="utf-8")

            win = self._make_window(vault, root / "cfg")
            try:
                win._current_folder = folder_a
                win._on_external_files_dropped([ext_file], target_folder=folder_b)
                app.processEvents()

                imported = folder_b / "Guide.md"
                self.assertTrue(imported.is_file())
                self.assertFalse((folder_a / "Guide.md").exists())
                self.assertEqual(win._current_note.path, imported)
            finally:
                win.close()
                win.deleteLater()

    def test_drop_in_vault_markdown_opens_without_duplicating(self) -> None:
        """Dropping a .md file already inside the vault opens it without creating a duplicate copy."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            notes_dir = vault / "Docs"
            notes_dir.mkdir(parents=True)
            existing = notes_dir / "Existing.md"
            existing.write_text("Already inside vault", encoding="utf-8")

            win = self._make_window(vault, root / "cfg")
            try:
                win._on_external_files_dropped([existing])
                app.processEvents()

                self.assertEqual(win._current_note.path, existing)
                self.assertEqual(list(notes_dir.glob("*.md")), [existing])
            finally:
                win.close()
                win.deleteLater()

    def test_drop_image_file_onto_editor_saves_and_inserts_markdown(self) -> None:
        """Dropping an image file from the OS file manager onto the editor inserts ![stem](images/...)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            notes_dir = vault / "Journal"
            notes_dir.mkdir(parents=True)
            note_file = notes_dir / "Day1.md"
            note_file.write_text("# Day 1\n", encoding="utf-8")

            ext_img = root / "sunset.png"
            img = QImage(100, 60, QImage.Format.Format_ARGB32)
            img.fill(QColor("#ff9f0a"))
            self.assertTrue(img.save(str(ext_img), "PNG"))

            win = self._make_window(vault, root / "cfg")
            try:
                win._on_external_files_dropped([note_file])
                app.processEvents()

                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(ext_img))])
                drop_ev = QDropEvent(
                    QPointF(20.0, 40.0),
                    Qt.DropAction.CopyAction,
                    mime,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                win.editor.editor.dropEvent(drop_ev)
                app.processEvents()

                self.assertIn("![sunset](images/sunset.png)", win.editor.get_content())
                self.assertTrue((notes_dir / "images" / "sunset.png").is_file())
            finally:
                win.close()
                win.deleteLater()

    def test_unsupported_binary_drop_is_ignored(self) -> None:
        """Dropping an unsupported binary file is ignored cleanly on dragEnterEvent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            vault.mkdir()
            bad_file = root / "archive.bin"
            bad_file.write_bytes(b"\x00\x01\x02\x03")

            win = self._make_window(vault, root / "cfg")
            try:
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(bad_file))])
                enter_ev = QDragEnterEvent(
                    QPointF(50.0, 50.0).toPoint(),
                    Qt.DropAction.CopyAction,
                    mime,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                win.dragEnterEvent(enter_ev)
                self.assertFalse(enter_ev.isAccepted())
            finally:
                win.close()
                win.deleteLater()

    def test_wayland_deferred_uri_list_drag_enter_and_drop(self) -> None:
        """Wayland sends text/uri-list with empty urls() on dragEnterEvent and populates it on dropEvent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            vault.mkdir()
            hero_file = root / "hero.md"
            hero_file.write_text("# Hero\nFrom Downloads", encoding="utf-8")

            win = self._make_window(vault, root / "cfg")
            try:
                # 1. dragEnterEvent with empty text/uri-list (Wayland deferred payload)
                deferred_mime = QMimeData()
                deferred_mime.setData("text/uri-list", b"")
                enter_ev = QDragEnterEvent(
                    QPointF(50.0, 50.0).toPoint(),
                    Qt.DropAction.CopyAction,
                    deferred_mime,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                win.editor.editor.dragEnterEvent(enter_ev)
                self.assertTrue(enter_ev.isAccepted())

                # 2. dropEvent with raw text/uri-list bytes
                drop_mime = QMimeData()
                drop_mime.setData("text/uri-list", f"file://{hero_file}\r\n".encode("utf-8"))
                drop_ev = QDropEvent(
                    QPointF(50.0, 50.0),
                    Qt.DropAction.CopyAction,
                    drop_mime,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                win.editor.editor.dropEvent(drop_ev)
                app.processEvents()

                imported = vault / "hero.md"
                self.assertTrue(imported.is_file())
                self.assertEqual(win._current_note.path, imported)
            finally:
                win.close()
                win.deleteLater()


if __name__ == "__main__":
    unittest.main()
