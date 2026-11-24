"""Performance and correctness regression tests for Phase 1 large-file optimizations."""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ConfigManager
from core.note import Note
from core.storage import StorageManager
from ui.editor import MarkdownEditor
from ui.main_window import MainWindow
from utils.note_io import (
    ASYNC_SAVE_THRESHOLD_BYTES,
    WORD_COUNT_CHUNK_CHARS,
    AsyncSaveQueue,
    count_words_fast,
    note_matches_query,
)


class TestLargeFilePhase1Performance(unittest.TestCase):
    """Verify head-only folder listing, streaming search, async saves, and O(1) cursor updates."""

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

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_list_notes_uses_head_only_reads_and_lazy_content(self) -> None:
        """Listing a folder with a multi-MB note must not read full bodies into RAM."""
        novel_dir = self.notes_dir / "Novel"
        novel_dir.mkdir()
        big_file = novel_dir / "BigBook.md"
        # ~2 MB file
        body = "# Chapter One\nOpening preview line here.\n" + ("Lorem ipsum dolor sit amet. " * 75_000)
        big_file.write_text(body, encoding="utf-8")

        t0 = time.perf_counter()
        notes = self.storage.list_notes(novel_dir)
        elapsed = time.perf_counter() - t0

        self.assertEqual(len(notes), 1)
        note = notes[0]
        self.assertFalse(note.has_loaded_content, "list_notes must keep content unloaded until opened")
        self.assertIn("Chapter One", note.preview_snippet)
        self.assertLess(elapsed, 0.25, f"Head-only folder listing should be fast (took {elapsed:.3f}s)")

        # Lazy load works transparently when accessed
        loaded = note.content
        self.assertTrue(note.has_loaded_content)
        self.assertEqual(len(loaded), len(body))

    def test_streaming_search_finds_tail_keyword_without_loading_note_cache(self) -> None:
        """Searching for a keyword at the end of a large file works without pinning full content."""
        big_file = self.notes_dir / "HugeSearch.md"
        payload = ("alpha beta gamma delta\n" * 10_000) + "UNIQUE_END_MARKER_42\n"
        big_file.write_text(payload, encoding="utf-8")

        note = Note.from_file(big_file)
        self.assertIsNotNone(note)
        assert note is not None
        self.assertFalse(note.has_loaded_content)

        self.assertTrue(note_matches_query(note.title, note.path, None, "unique_end_marker_42"))
        self.assertFalse(note_matches_query(note.title, note.path, None, "nonexistent_token_99"))
        self.assertFalse(note.has_loaded_content)

    def test_count_words_fast_matches_split_across_chunk_boundary(self) -> None:
        """Chunked word counting must remain exact even when a word straddles 65536-char boundary."""
        # Place a word directly straddling WORD_COUNT_CHUNK_CHARS
        prefix = "word " * (WORD_COUNT_CHUNK_CHARS // 5 - 1)
        bridge = "supercalifragilisticexpialidocious"
        suffix = " tail end words"
        sample = prefix + bridge + suffix
        self.assertGreater(len(sample), WORD_COUNT_CHUNK_CHARS)
        self.assertEqual(count_words_fast(sample), len(sample.split()))

    def test_async_save_queue_persists_large_content_cleanly(self) -> None:
        """Large saves (>64 KB) offload to worker thread and flush reliably."""
        target = self.notes_dir / "AsyncLarge.md"
        content_v1 = "A" * (ASYNC_SAVE_THRESHOLD_BYTES + 1024)
        content_v2 = "B" * (ASYNC_SAVE_THRESHOLD_BYTES + 2048)

        queue = AsyncSaveQueue()
        self.assertTrue(queue.save(target, content_v1, self.storage.save_note_content))
        self.assertTrue(queue.save(target, content_v2, self.storage.save_note_content))
        self.assertTrue(queue.wait_for_done(5000))
        self.assertEqual(target.read_text(encoding="utf-8"), content_v2)

    def test_content_saved_does_not_rescan_folder(self) -> None:
        """Auto-saving a note must update note metadata in-memory without calling storage.list_notes."""
        cfg = ConfigManager(config_file=self.config_dir / "settings.json")
        note_path = self.notes_dir / "Doc.md"
        note_path.write_text("initial", encoding="utf-8")

        window = MainWindow(storage_manager=self.storage, config_manager=cfg)
        try:
            self.app.processEvents()
            with patch.object(self.storage, "list_notes", wraps=self.storage.list_notes) as spy_list:
                window._on_content_saved("updated body text")
                self.app.processEvents()
                spy_list.assert_not_called()
            self.assertEqual(note_path.read_text(encoding="utf-8"), "updated body text")
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_cursor_movement_skips_full_region_rescan(self) -> None:
        """Moving caret across lines must call update_active_modes, not full refresh_regions."""
        editor = MarkdownEditor()
        try:
            editor.setPlainText("\n".join(f"Paragraph line {i}" for i in range(100)))
            self.app.processEvents()

            with patch.object(editor.highlighter, "refresh_regions", wraps=editor.highlighter.refresh_regions) as spy_refresh:
                cur = editor.textCursor()
                cur.movePosition(QTextCursor.MoveOperation.NextBlock)
                editor.setTextCursor(cur)
                cur.movePosition(QTextCursor.MoveOperation.NextBlock)
                editor.setTextCursor(cur)
                self.app.processEvents()
                spy_refresh.assert_not_called()
        finally:
            editor.deleteLater()


if __name__ == "__main__":
    unittest.main()
