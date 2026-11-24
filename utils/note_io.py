"""Lightweight note I/O helpers, streaming search, fast word counting, and async save queue."""

from __future__ import annotations

import html
from pathlib import Path
import re
import threading
from typing import Callable, Dict, Optional, Tuple

from PyQt6.QtCore import QRunnable, QThreadPool

SNIPPET_READ_BYTES: int = 4096
SEARCH_CHUNK_BYTES: int = 65536
ASYNC_SAVE_THRESHOLD_BYTES: int = 64 * 1024
WORD_COUNT_CHUNK_CHARS: int = 65536

_DECORATIVE_LINE_RE = re.compile(
    r"^\s*(?:```.*|~~~.*|\$\$|\\+\[|\\+\]|(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,}|\|[\s:\-|]+\|?)\s*$"
)
_LINE_PREFIX_RE = re.compile(
    r"^(?:\s*[-*+]\s*\[[ xX]?\]\s*|\s*[-*+]\s+|\s*\d+[.)]\s+|\s*\\?#+\s+|\s*>+\s*)+"
)
_IMAGE_MD_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_MD_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_AUTOLINK_RE = re.compile(r"<((?:https?|ftp)://[^\s>]+)>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[a-zA-Z!/][^>]*>")
_BOLD_MARK_RE = re.compile(r"(\*\*|__)(.+?)\1")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_STRIKE_HIGHLIGHT_RE = re.compile(r"(~{1,2}|==)(.+?)\1")
_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_ITALIC_UNDER_RE = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")
_LEFTOVER_MARKERS_RE = re.compile(r"(\*\*|__|~~|==|`)")
_MULTISPACE_RE = re.compile(r"\s+")


def clean_markdown_preview_line(raw_line: str) -> str:
    """Strip HTML tags and Markdown syntax from a single line for card previews."""
    stripped = raw_line.strip()
    if not stripped or _DECORATIVE_LINE_RE.match(stripped):
        return ""

    text = _LINE_PREFIX_RE.sub("", stripped)
    text = _IMAGE_MD_RE.sub(r"\1", text)
    text = _LINK_MD_RE.sub(r"\1", text)
    text = _AUTOLINK_RE.sub(r"\1", text)
    text = _HTML_TAG_RE.sub("", text)

    if text.lstrip().startswith("|"):
        text = text.strip().strip("|")
        text = re.sub(r"\s*\|\s*", " ", text)

    text = _BOLD_MARK_RE.sub(r"\2", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _STRIKE_HIGHLIGHT_RE.sub(r"\2", text)
    text = _ITALIC_STAR_RE.sub(r"\1", text)
    text = _ITALIC_UNDER_RE.sub(r"\1", text)
    text = _LEFTOVER_MARKERS_RE.sub("", text)
    text = html.unescape(text)
    return _MULTISPACE_RE.sub(" ", text).strip()


def read_note_head(path: Path, max_bytes: int = SNIPPET_READ_BYTES) -> str:
    """Read at most `max_bytes` from the start of a UTF-8 note file for fast snippet extraction."""
    with path.open("rb") as fh:
        raw = fh.read(max_bytes)
    return raw.decode("utf-8", errors="ignore")


def read_note_full(path: Path) -> str:
    """Read the complete UTF-8 contents of a note file."""
    return path.read_text(encoding="utf-8")


def note_matches_query(
    title: str,
    path: Path,
    cached_content: Optional[str],
    query_lower: str,
) -> bool:
    """Return True if `query_lower` matches note title or file body without pinning huge files in RAM."""
    if not query_lower:
        return True
    if query_lower in title.lower():
        return True
    if cached_content is not None:
        return query_lower in cached_content.lower()

    overlap_len = max(1, len(query_lower) - 1)
    tail = ""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            while True:
                chunk = fh.read(SEARCH_CHUNK_BYTES)
                if not chunk:
                    return False
                haystack = (tail + chunk).lower()
                if query_lower in haystack:
                    return True
                tail = chunk[-overlap_len:] if len(chunk) >= overlap_len else chunk
    except (FileNotFoundError, PermissionError, OSError):
        return False


def count_words_fast(text: str) -> int:
    """Count whitespace-delimited words efficiently without huge list allocations on large notes."""
    length = len(text)
    if length == 0:
        return 0
    if length <= WORD_COUNT_CHUNK_CHARS:
        return len(text.split())

    total = 0
    in_word = False
    pos = 0
    while pos < length:
        chunk = text[pos : pos + WORD_COUNT_CHUNK_CHARS]
        pos += WORD_COUNT_CHUNK_CHARS
        chunk_words = len(chunk.split())
        if chunk_words == 0:
            in_word = False
            continue
        if in_word and not chunk[0].isspace():
            # First token continues the word from the previous chunk
            total += chunk_words - 1
        else:
            total += chunk_words
        in_word = not chunk[-1].isspace()
    return total


class _SaveTask(QRunnable):
    """Background runnable that drains the latest pending content for a file path."""

    def __init__(self, queue: "AsyncSaveQueue", path: Path) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._queue = queue
        self._path = path

    def run(self) -> None:
        self._queue._execute_pending(self._path)


class AsyncSaveQueue:
    """Serialized atomic save dispatcher offloading large-file writes to a worker thread."""

    def __init__(self, threshold_bytes: int = ASYNC_SAVE_THRESHOLD_BYTES) -> None:
        self._threshold_bytes = threshold_bytes
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(1)
        self._lock = threading.Lock()
        self._pending: Dict[Path, Tuple[Callable[[Path, str], bool], str]] = {}

    def save(
        self,
        path: Path,
        content: str,
        save_fn: Callable[[Path, str], bool],
        *,
        force_sync: bool = False,
    ) -> bool:
        """Persist content synchronously for small notes or asynchronously for large files."""
        est_bytes = len(content)
        if force_sync or est_bytes < self._threshold_bytes:
            self.wait_for_done()
            return save_fn(path, content)

        with self._lock:
            already_queued = path in self._pending
            self._pending[path] = (save_fn, content)

        if not already_queued:
            self._pool.start(_SaveTask(self, path))
        return True

    def _execute_pending(self, path: Path) -> None:
        while True:
            with self._lock:
                entry = self._pending.pop(path, None)
            if entry is None:
                return
            save_fn, content = entry
            try:
                save_fn(path, content)
            except (PermissionError, OSError):
                pass
            with self._lock:
                if path not in self._pending:
                    return

    def wait_for_done(self, timeout_ms: int = 5000) -> bool:
        """Block until all queued background save operations finish."""
        return self._pool.waitForDone(timeout_ms)
