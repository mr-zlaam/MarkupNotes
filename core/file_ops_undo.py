"""Reversible undo stack for workspace file and folder move/copy operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(slots=True)
class FileOpRecord:
    """Single reversible file or folder move/copy operation."""

    kind: str  # "move" or "copy"
    item_type: str  # "note" or "folder"
    src_path: Path
    dst_path: Path
    replaced_backup_path: Optional[Path] = None


class FileOperationUndoStack:
    """Bounded LIFO stack tracking workspace file/folder move and copy operations."""

    def __init__(self, max_entries: int = 50) -> None:
        self._max_entries = max(1, max_entries)
        self._undo_stack: List[FileOpRecord] = []

    @property
    def can_undo(self) -> bool:
        """Return True if at least one file operation can be undone."""
        return bool(self._undo_stack)

    def push(self, record: FileOpRecord) -> None:
        """Record a completed file/folder operation."""
        self._undo_stack.append(record)
        if len(self._undo_stack) > self._max_entries:
            del self._undo_stack[:-self._max_entries]

    def pop_undo(self) -> Optional[FileOpRecord]:
        """Pop and return the most recent operation, or None if empty."""
        if not self._undo_stack:
            return None
        return self._undo_stack.pop()

    def clear(self) -> None:
        """Clear all recorded file operations."""
        self._undo_stack.clear()
