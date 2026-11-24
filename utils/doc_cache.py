"""LRU QTextDocument cache and async large-note loader for instant note switching."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Optional, Tuple

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal
from PyQt6.QtGui import QTextDocument

from utils.note_io import read_note_full
from utils.undo_manager import PlainTextUndoManager

LARGE_NOTE_LOADER_BYTES: int = 500 * 1024
STARTUP_DEFER_LOAD_BYTES: int = 2 * 1024 * 1024
DEFAULT_MAX_CACHE_ENTRIES: int = 6
DEFAULT_MAX_CACHE_BYTES: int = 32 * 1024 * 1024


def clean_note_markdown(content: str) -> str:
    """Normalize accidental escaped headings and empty '- []' checkboxes without unneeded regex passes."""
    cleaned = content
    if "\\#" in cleaned:
        cleaned = re.sub(r"^\\(#+\s)", r"\1", cleaned, flags=re.MULTILINE)
    if "[]" in cleaned:
        cleaned = re.sub(
            r"^(\s*[-*+]\s*)\[\](?=\s|$)", r"\1[ ]", cleaned, flags=re.MULTILINE
        )
    return cleaned


def get_file_stat_signature(path: Path) -> Optional[Tuple[int, int]]:
    """Return (st_mtime_ns, st_size) for an existing file path, or None if inaccessible."""
    try:
        st = path.stat()
        return st.st_mtime_ns, st.st_size
    except (FileNotFoundError, PermissionError, OSError):
        return None


@dataclass
class CachedNoteDocument:
    """Cached Qt document, highlighter, undo history, and viewport state for a note."""

    path: Path
    document: QTextDocument
    highlighter: Any  # MarkdownHighlighter
    undo_manager: PlainTextUndoManager
    scroll_y: int = 0
    cursor_anchor: int = 0
    cursor_pos: int = 0
    mtime_ns: int = 0
    size_bytes: int = 0
    text_bytes: int = 0
    ui_scale: float = 1.0
    font_size_pt: int = 12
    font_family: str = ""


class NoteDocumentCache:
    """Bounded LRU cache of laid-out QTextDocuments with automatic staleness invalidation."""

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_CACHE_ENTRIES,
        max_bytes: int = DEFAULT_MAX_CACHE_BYTES,
    ) -> None:
        self._max_entries = max(2, max_entries)
        self._max_bytes = max(1024 * 1024, max_bytes)
        self._entries: OrderedDict[Path, CachedNoteDocument] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, path: Path) -> bool:
        return path in self._entries

    @property
    def total_bytes(self) -> int:
        """Return total estimated text bytes currently held in cache."""
        return sum(entry.text_bytes for entry in self._entries.values())

    def get(
        self,
        path: Path,
        *,
        mtime_ns: Optional[int],
        size_bytes: Optional[int],
        ui_scale: float,
        font_size_pt: int,
        font_family: str,
        active_path: Optional[Path] = None,
    ) -> Optional[CachedNoteDocument]:
        """Return a valid cached entry and bump LRU recency, or evict and return None if stale."""
        entry = self._entries.get(path)
        if entry is None:
            return None

        stale_disk = (
            mtime_ns is not None
            and size_bytes is not None
            and (entry.mtime_ns != mtime_ns or entry.size_bytes != size_bytes)
        )
        stale_style = (
            abs(entry.ui_scale - ui_scale) > 1e-4
            or entry.font_size_pt != font_size_pt
            or entry.font_family != font_family
        )
        if stale_disk or stale_style:
            self.evict(path, active_path=active_path)
            return None

        self._entries.move_to_end(path)
        return entry

    def peek(self, path: Path) -> Optional[CachedNoteDocument]:
        """Return entry without modifying LRU order or validating staleness."""
        return self._entries.get(path)

    def put(
        self,
        entry: CachedNoteDocument,
        *,
        active_path: Optional[Path] = None,
    ) -> None:
        """Insert or update an entry and evict least-recently-used inactive entries if over budget."""
        existing = self._entries.get(entry.path)
        if existing is not None and existing.document is not entry.document:
            self._dispose_entry(existing, active_path=active_path)
        self._entries[entry.path] = entry
        self._entries.move_to_end(entry.path)
        self._enforce_limits(protected={entry.path, active_path})

    def update_stat(
        self,
        path: Path,
        mtime_ns: int,
        size_bytes: int,
        text_bytes: Optional[int] = None,
    ) -> None:
        """Synchronize cached disk signature after an internal save."""
        entry = self._entries.get(path)
        if entry is None:
            return
        entry.mtime_ns = mtime_ns
        entry.size_bytes = size_bytes
        if text_bytes is not None:
            entry.text_bytes = text_bytes

    def rename(self, old_path: Path, new_path: Path) -> None:
        """Re-key a cached note after renaming on disk."""
        if old_path == new_path:
            return
        entry = self._entries.pop(old_path, None)
        if entry is None:
            return
        old_target = self._entries.pop(new_path, None)
        if old_target is not None and old_target.document is not entry.document:
            self._dispose_entry(old_target, active_path=None)
        entry.path = new_path
        sig = get_file_stat_signature(new_path)
        if sig is not None:
            entry.mtime_ns, entry.size_bytes = sig
        self._entries[new_path] = entry
        self._entries.move_to_end(new_path)

    def rename_folder(self, old_folder: Path, new_folder: Path) -> None:
        """Re-key all cached notes located inside old_folder after moving/renaming the folder."""
        if old_folder == new_folder:
            return
        matching = [
            p for p in list(self._entries.keys())
            if old_folder in p.parents
        ]
        for old_note_path in matching:
            try:
                rel = old_note_path.relative_to(old_folder)
            except ValueError:
                continue
            self.rename(old_note_path, new_folder / rel)

    def evict(self, path: Path, *, active_path: Optional[Path] = None) -> None:
        """Remove a specific note path from cache and dispose its document if inactive."""
        entry = self._entries.pop(path, None)
        if entry is not None:
            self._dispose_entry(entry, active_path=active_path)

    def evict_folder(self, folder_path: Path, *, active_path: Optional[Path] = None) -> None:
        """Evict all cached notes located inside `folder_path`."""
        to_remove = [
            p for p in self._entries
            if p == folder_path or folder_path in p.parents
        ]
        for p in to_remove:
            self.evict(p, active_path=active_path)

    def clear(self, *, keep_path: Optional[Path] = None) -> None:
        """Evict all entries except an optional active path."""
        to_remove = [p for p in self._entries if p != keep_path]
        for p in to_remove:
            self.evict(p, active_path=keep_path)

    def _enforce_limits(self, protected: set[Optional[Path]]) -> None:
        while len(self._entries) > self._max_entries or (
            self.total_bytes > self._max_bytes and len(self._entries) > 1
        ):
            victim_key: Optional[Path] = None
            for k in self._entries:
                if k not in protected:
                    victim_key = k
                    break
            if victim_key is None:
                break
            victim = self._entries.pop(victim_key)
            self._dispose_entry(victim, active_path=None)

    @staticmethod
    def _dispose_entry(entry: CachedNoteDocument, *, active_path: Optional[Path]) -> None:
        if active_path is not None and entry.path == active_path:
            return
        try:
            entry.highlighter.setDocument(None)
        except RuntimeError:
            pass
        try:
            entry.document.deleteLater()
        except RuntimeError:
            pass


class AsyncNoteLoadSignals(QObject):
    """Signals emitted by AsyncNoteLoadWorker back onto the GUI thread."""

    # Use object for 64-bit mtime_ns and size_bytes so PyQt6 does not truncate to 32-bit C++ int
    loaded = pyqtSignal(int, object, str, object, object)  # gen_id, Path, cleaned_text, mtime_ns, size_bytes
    failed = pyqtSignal(int, object)  # gen_id, Path


class AsyncNoteLoadWorker(QRunnable):
    """Background worker that reads and normalizes a large markdown file off the GUI thread."""

    def __init__(self, gen_id: int, path: Path) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.gen_id = gen_id
        self.path = path
        self.signals = AsyncNoteLoadSignals()

    def run(self) -> None:
        try:
            st = self.path.stat()
            raw = read_note_full(self.path)
            cleaned = clean_note_markdown(raw)
        except (FileNotFoundError, PermissionError, UnicodeDecodeError, OSError):
            try:
                self.signals.failed.emit(self.gen_id, self.path)
            except RuntimeError:
                pass
            return

        try:
            self.signals.loaded.emit(self.gen_id, self.path, cleaned, st.st_mtime_ns, st.st_size)
        except RuntimeError:
            pass
