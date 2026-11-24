"""Tests for LRU QTextDocument cache, invalidation rules, and >= 500 KB async note loader."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent, QTextCursor
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.note import Note
from ui.editor import EditorPanel
from utils.doc_cache import LARGE_NOTE_LOADER_BYTES, NoteDocumentCache


def _wait_until(app: QApplication, predicate, timeout_sec: float = 3.0) -> bool:
    """Process Qt events until predicate() returns True or timeout expires."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


class TestDocCacheAndLoader(unittest.TestCase):
    """Verify fast QTextDocument LRU switching, cache invalidation, and >= 500 KB async loader."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.panel = EditorPanel()
        self.panel.resize(800, 600)

    def tearDown(self) -> None:
        self.panel._load_pool.waitForDone(3000)
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()
        self.temp_dir.cleanup()

    def test_cache_hit_preserves_document_undo_and_cursor_state(self) -> None:
        """Switching Note A -> Note B -> Note A reuses QTextDocument, cursor, and undo history."""
        file_a = self.root / "NoteA.md"
        file_b = self.root / "NoteB.md"
        file_a.write_text("Alpha line 1\nAlpha line 2", encoding="utf-8")
        file_b.write_text("Beta content", encoding="utf-8")

        note_a = Note.from_file(file_a)
        note_b = Note.from_file(file_b)
        assert note_a is not None and note_b is not None

        self.panel.load_note(note_a)
        doc_a = self.panel.editor.document()

        # Type inside Note A so it has an undo step and non-zero cursor
        cur = self.panel.editor.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self.panel.editor.setTextCursor(cur)
        for ch in " edit":
            self.panel.editor.keyPressEvent(
                QKeyEvent(QEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, ch)
            )
        pos_in_a = self.panel.editor.textCursor().position()
        self.assertTrue(self.panel.editor.canUndo())

        # Switch to Note B
        self.panel.load_note(note_b)
        self.assertIsNot(self.panel.editor.document(), doc_a)
        self.assertEqual(self.panel.editor.toPlainText(), "Beta content")

        # Switch back to Note A -> exact same QTextDocument, cursor pos, and undo stack!
        self.panel.load_note(note_a)
        self.assertIs(self.panel.editor.document(), doc_a)
        self.assertEqual(self.panel.editor.textCursor().position(), pos_in_a)
        self.assertTrue(self.panel.editor.canUndo())
        self.panel.editor.undo()
        self.assertEqual(self.panel.editor.toPlainText(), "Alpha line 1\nAlpha line 2 ")

    def test_external_disk_modification_invalidates_cache_automatically(self) -> None:
        """Modifying a cached file externally on disk must trigger a fresh reload."""
        file_a = self.root / "External.md"
        file_b = self.root / "Other.md"
        file_a.write_text("Version 1", encoding="utf-8")
        file_b.write_text("Other", encoding="utf-8")

        note_a = Note.from_file(file_a)
        note_b = Note.from_file(file_b)
        assert note_a is not None and note_b is not None

        self.panel.load_note(note_a)
        old_doc = self.panel.editor.document()
        self.panel.load_note(note_b)

        # Simulate external editor modifying External.md on disk
        file_a.write_text("Version 2 from external editor!", encoding="utf-8")
        note_a_fresh = Note.from_file(file_a)
        assert note_a_fresh is not None

        self.panel.load_note(note_a_fresh)
        self.assertIsNot(self.panel.editor.document(), old_doc)
        self.assertEqual(self.panel.editor.toPlainText(), "Version 2 from external editor!")

    def test_rename_and_delete_cache_invalidation(self) -> None:
        """Renaming moves cache key cleanly; invalidating evicts cached document."""
        file_a = self.root / "OldName.md"
        file_b = self.root / "Stay.md"
        file_a.write_text("Original text", encoding="utf-8")
        file_b.write_text("Stay text", encoding="utf-8")

        note_a = Note.from_file(file_a)
        note_b = Note.from_file(file_b)
        assert note_a is not None and note_b is not None

        self.panel.load_note(note_a)
        doc_a = self.panel.editor.document()
        self.panel.load_note(note_b)

        new_path = self.root / "NewName.md"
        file_a.rename(new_path)
        self.panel.rename_cached_note(file_a, new_path)

        self.assertNotIn(file_a, self.panel._doc_cache)
        self.assertIn(new_path, self.panel._doc_cache)

        note_renamed = Note.from_file(new_path)
        assert note_renamed is not None
        self.panel.load_note(note_renamed)
        self.assertIs(self.panel.editor.document(), doc_a)

        # Switch away and evict
        self.panel.load_note(note_b)
        self.panel.invalidate_note_cache(new_path)
        self.assertNotIn(new_path, self.panel._doc_cache)

    def test_lru_cache_evicts_oldest_inactive_entry(self) -> None:
        """LRU cache enforces max_entries without evicting the active note."""
        self.panel._doc_cache = NoteDocumentCache(max_entries=2)
        notes = []
        for idx in range(3):
            p = self.root / f"N{idx}.md"
            p.write_text(f"Body {idx}", encoding="utf-8")
            n = Note.from_file(p)
            assert n is not None
            notes.append(n)

        for n in notes:
            self.panel.load_note(n)

        self.assertEqual(len(self.panel._doc_cache), 2)
        self.assertNotIn(notes[0].path, self.panel._doc_cache)
        self.assertIn(notes[1].path, self.panel._doc_cache)
        self.assertIn(notes[2].path, self.panel._doc_cache)

    def test_large_note_over_500kb_uses_async_loader_and_supports_cancellation(self) -> None:
        """Uncached files >= 500 KB show loading state, load asynchronously, and cancel on rapid switch."""
        big_file = self.root / "Novel.md"
        small_file = self.root / "Quick.md"
        big_text = ("This is a novel paragraph for async loader testing.\n" * 12_000)
        self.assertGreaterEqual(len(big_text.encode("utf-8")), LARGE_NOTE_LOADER_BYTES)
        big_file.write_text(big_text, encoding="utf-8")
        small_file.write_text("# Quick Note", encoding="utf-8")

        # 1. Start loading big note -> immediately enters loading state
        big_note = Note.from_file(big_file)
        small_note = Note.from_file(small_file)
        assert big_note is not None and small_note is not None

        self.panel.load_note(big_note)
        self.assertTrue(self.panel._is_loading_note)
        self.assertTrue(self.panel.editor.isReadOnly())
        self.assertIn("Loading large note", self.panel.meta_label.text())

        # Immediately cancel by switching to small note!
        self.panel.load_note(small_note)
        self.assertFalse(self.panel._is_loading_note)
        self.assertFalse(self.panel.editor.isReadOnly())
        self.assertEqual(self.panel.editor.toPlainText(), "# Quick Note")

        # Let background worker finish -> stale result must be ignored!
        self.panel._load_pool.waitForDone(3000)
        self.app.processEvents()
        self.assertEqual(self.panel.editor.toPlainText(), "# Quick Note")

        # 2. Now actually let big note finish loading asynchronously and cache itself
        big_note_2 = Note.from_file(big_file)
        assert big_note_2 is not None
        self.panel.load_note(big_note_2)
        done = _wait_until(self.app, lambda: not self.panel._is_loading_note)
        self.assertTrue(done, "Async large note load must complete")
        self.assertFalse(self.panel.editor.isReadOnly())
        self.assertEqual(len(self.panel.editor.toPlainText()), len(big_text))
        self.assertIn(big_file, self.panel._doc_cache)

        # 3. Switching away and back hits cache synchronously (no async loader!)
        big_doc = self.panel.editor.document()
        self.panel.load_note(small_note)
        self.panel.load_note(big_note_2)
        self.assertFalse(self.panel._is_loading_note)
        self.assertIs(self.panel.editor.document(), big_doc)


if __name__ == "__main__":
    unittest.main()
