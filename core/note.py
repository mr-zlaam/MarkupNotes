"""Note data model and lazy content parsing."""

from pathlib import Path
import re
from typing import Optional

from utils.date_format import format_relative_time, is_date_badge_line
from utils.note_io import (
    SNIPPET_READ_BYTES,
    clean_markdown_preview_line,
    read_note_full,
    read_note_head,
)


class Note:
    """Represents a single Markdown note in the file system with lazy full-body loading."""

    __slots__ = ("path", "title", "_content", "modified_at", "preview_snippet", "is_pinned")

    def __init__(
        self,
        path: Path,
        title: str,
        content: Optional[str],
        modified_at: float,
        preview_snippet: str,
        is_pinned: bool = False,
    ) -> None:
        self.path = path
        self.title = title
        self._content = content
        self.modified_at = modified_at
        self.preview_snippet = preview_snippet
        self.is_pinned = is_pinned

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Note):
            return NotImplemented
        return (
            self.path == other.path
            and self.title == other.title
            and self.modified_at == other.modified_at
            and self.preview_snippet == other.preview_snippet
            and self.is_pinned == other.is_pinned
        )

    def __repr__(self) -> str:
        return (
            f"Note(path={self.path!r}, title={self.title!r}, "
            f"modified_at={self.modified_at!r}, preview_snippet={self.preview_snippet!r})"
        )

    @property
    def has_loaded_content(self) -> bool:
        """Return True if full markdown content is currently cached in memory."""
        return self._content is not None

    @property
    def content(self) -> str:
        """Lazily load and cache the full Markdown body from disk on first access."""
        if self._content is None:
            try:
                self._content = read_note_full(self.path)
            except (FileNotFoundError, PermissionError, UnicodeDecodeError, OSError):
                self._content = ""
        return self._content

    @content.setter
    def content(self, value: Optional[str]) -> None:
        self._content = value

    @property
    def formatted_time(self) -> str:
        """Return the relative human-friendly time for this note."""
        return format_relative_time(self.modified_at)

    @classmethod
    def from_file(cls, path: Path, *, load_content: bool = False) -> Optional["Note"]:
        """Build a Note from disk, reading only the file head by default for fast folder listing.

        Returns None if the file cannot be read.
        """
        try:
            stat_info = path.stat()
            if load_content:
                full_content = read_note_full(path)
                head_text = full_content[:SNIPPET_READ_BYTES]
                cached_content: Optional[str] = full_content
            else:
                head_text = read_note_head(path, SNIPPET_READ_BYTES)
                cached_content = None
        except (FileNotFoundError, PermissionError, UnicodeDecodeError, OSError):
            return None

        title = path.stem
        _, snippet = cls.parse_title_and_snippet(head_text, fallback_title=title)
        return cls(
            path=path,
            title=title,
            content=cached_content,
            modified_at=stat_info.st_mtime,
            preview_snippet=snippet,
            is_pinned=False,
        )

    @classmethod
    def from_memory(cls, path: Path, content: str, modified_at: float) -> "Note":
        """Construct a Note directly from in-memory content without re-reading disk."""
        title = path.stem
        _, snippet = cls.parse_title_and_snippet(
            content[:SNIPPET_READ_BYTES], fallback_title=title
        )
        return cls(
            path=path,
            title=title,
            content=content,
            modified_at=modified_at,
            preview_snippet=snippet,
            is_pinned=False,
        )

    @staticmethod
    def parse_title_and_snippet(
        content: str, fallback_title: str = "Untitled"
    ) -> tuple[str, str]:
        """Extract the note's title and a 2-line preview snippet from markdown content.

        Only inspects the head of the content so large documents stay O(1).
        """
        head = content[:SNIPPET_READ_BYTES]
        cleaned_lines: list[str] = []
        for raw_line in head.splitlines():
            stripped = raw_line.strip()
            if not stripped or is_date_badge_line(stripped):
                continue
            cleaned = clean_markdown_preview_line(stripped)
            if cleaned:
                cleaned_lines.append(cleaned)
                if len(cleaned_lines) >= 3:
                    break

        if not cleaned_lines:
            return fallback_title, "No additional text"

        # Skip leading line when it duplicates the note title (e.g. '# Title')
        start_idx = 1 if cleaned_lines[0].lower() == fallback_title.lower() else 0
        snippet_lines = cleaned_lines[start_idx : start_idx + 2]
        snippet = " ".join(snippet_lines) if snippet_lines else "No additional text"
        return fallback_title, snippet
