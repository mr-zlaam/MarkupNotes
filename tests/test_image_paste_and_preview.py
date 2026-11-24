"""Unit tests for Ctrl+V image pasting, live Markdown image previews, and hidden images folder."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QMimeData, QUrl
from PyQt6.QtGui import QColor, QImage, QPixmap, QTextCursor
from PyQt6.QtWidgets import QApplication

from core.storage import StorageManager
from ui.editor import MarkdownEditor
from utils.image_engine import resolve_image_path

app = QApplication.instance() or QApplication([])


class TestImagePasteAndPreview(unittest.TestCase):
    """Verify clipboard image paste, Obsidian-style live image preview, and hidden images/ folder."""

    def test_paste_clipboard_qimage_saves_to_note_images_folder(self) -> None:
        """Pasting a raw QImage via Ctrl+V saves PNG in <note_dir>/images/ and inserts Markdown."""
        with tempfile.TemporaryDirectory() as tmp:
            note_dir = Path(tmp) / "Novel"
            note_dir.mkdir()

            editor = MarkdownEditor()
            editor._note_dir = note_dir
            editor._vault_root = Path(tmp)

            pasted_signals: list[bool] = []
            editor.image_pasted.connect(lambda: pasted_signals.append(True))

            img = QImage(120, 80, QImage.Format.Format_ARGB32)
            img.fill(QColor("#0a84ff"))
            mime = QMimeData()
            mime.setImageData(img)

            editor.insertFromMimeData(mime)
            text = editor.toPlainText()
            self.assertTrue(text.startswith("![Image](images/pasted-"))
            self.assertTrue(text.endswith(".png)"))
            self.assertEqual(len(pasted_signals), 1)

            rel_path = text[len("![Image](") : -1]
            saved_file = note_dir / rel_path
            self.assertTrue(saved_file.is_file())
            self.assertGreater(saved_file.stat().st_size, 0)

            editor.deleteLater()

    def test_paste_local_image_file_url_copies_into_images_folder(self) -> None:
        """Pasting a copied local image file URL copies it into <note_dir>/images/."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note_dir = root / "Chapter"
            note_dir.mkdir()
            src_img = root / "cover.png"
            img = QImage(64, 64, QImage.Format.Format_ARGB32)
            img.fill(QColor("#30d158"))
            self.assertTrue(img.save(str(src_img), "PNG"))

            editor = MarkdownEditor()
            editor._note_dir = note_dir
            editor._vault_root = root

            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(src_img))])
            editor.insertFromMimeData(mime)

            self.assertEqual(editor.toPlainText(), "![cover](images/cover.png)")
            self.assertTrue((note_dir / "images" / "cover.png").is_file())

            editor.deleteLater()

    def test_storage_hides_images_folder_from_sidebar_list(self) -> None:
        """StorageManager.get_folders excludes 'images' directories while keeping them on disk for Git."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = StorageManager(root)
            (root / "Work").mkdir()
            (root / "Work" / "images").mkdir()
            (root / "images").mkdir()
            (root / "Work" / "Sub").mkdir()

            folders = storage.get_folders()
            folder_names = {f.name for f in folders}
            self.assertIn("Work", folder_names)
            self.assertIn("Sub", folder_names)
            self.assertNotIn("images", folder_names)

    def test_live_image_preview_renders_inactive_and_reveals_markdown_on_active_line(self) -> None:
        """Verify ![Cover](images/...) renders as image preview when inactive and reveals raw text when focused."""
        with tempfile.TemporaryDirectory() as tmp:
            note_dir = Path(tmp) / "Book"
            img_dir = note_dir / "images"
            img_dir.mkdir(parents=True)
            cover_path = img_dir / "epub-62e172d81dc7a7e3.jpg"
            img = QImage(320, 200, QImage.Format.Format_ARGB32)
            img.fill(QColor("#bf5af2"))
            self.assertTrue(img.save(str(cover_path), "JPG"))

            resolved = resolve_image_path("images/epub-62e172d81dc7a7e3.jpg", note_dir=note_dir)
            self.assertEqual(resolved, cover_path)

            editor = MarkdownEditor()
            editor._note_dir = note_dir
            editor._vault_root = Path(tmp)
            editor.resize(700, 500)
            editor.setPlainText("# Chapter 1\n![Cover](images/epub-62e172d81dc7a7e3.jpg)\nSome text below.")
            editor.show()
            app.processEvents()

            # Cursor starts on line 0 -> line 1 is inactive image preview
            self.assertEqual(len(editor.highlighter.image_regions), 1)
            self.assertEqual(editor.highlighter._block_modes.get(1)[0], "inactive_image")

            # Render paintEvent -> image card rect is registered
            pm = QPixmap(editor.size())
            editor.render(pm)
            app.processEvents()
            img_rects = [r for s, e, r in editor._rendered_block_rects if s == 1]
            self.assertEqual(len(img_rects), 1)
            self.assertGreaterEqual(img_rects[0].height(), 100.0)

            # Move cursor onto line 1 -> switches to active_image (raw Markdown editable)
            c = editor.textCursor()
            c.setPosition(editor.document().findBlockByNumber(1).position() + 2)
            editor.setTextCursor(c)
            app.processEvents()
            self.assertEqual(editor.highlighter._block_modes.get(1)[0], "active_image")

            editor.deleteLater()


if __name__ == "__main__":
    unittest.main()
