"""Plain-text delta-based Undo/Redo manager decoupled from Qt layout formatting."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(slots=True)
class UndoEntry:
    """Single reversible plain-text edit delta with cursor/selection bounds."""

    offset: int
    removed: str
    inserted: str
    before_anchor: int
    before_pos: int
    after_anchor: int
    after_pos: int
    coalesce_kind: str  # "insert", "backspace", "delete_fwd", or "atomic"
    timestamp: float


def compute_text_delta(old_text: str, new_text: str) -> Tuple[int, str, str]:
    """Compute minimal (offset, removed, inserted) delta using C-speed binary search."""
    old_len = len(old_text)
    new_len = len(new_text)
    limit = min(old_len, new_len)

    # Binary search common prefix length via C-level string slice comparisons
    lo, hi = 0, limit
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if old_text[:mid] == new_text[:mid]:
            lo = mid
        else:
            hi = mid - 1
    prefix = lo

    old_rem = old_len - prefix
    new_rem = new_len - prefix
    suffix_limit = min(old_rem, new_rem)

    # Binary search common suffix length
    lo, hi = 0, suffix_limit
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if old_text[old_len - mid :] == new_text[new_len - mid :]:
            lo = mid
        else:
            hi = mid - 1
    suffix = lo

    removed = old_text[prefix : old_len - suffix]
    inserted = new_text[prefix : new_len - suffix]
    return prefix, removed, inserted


class PlainTextUndoManager:
    """Manages clean plain-text undo/redo history independent of QTextBlockFormat edits."""

    COALESCE_WINDOW_SEC: float = 0.8

    def __init__(self, initial_text: str = "", max_steps: int = 500) -> None:
        self._max_steps = max(10, max_steps)
        self._current_text: str = initial_text
        self._last_anchor: int = 0
        self._last_pos: int = 0
        self._undo_stack: List[UndoEntry] = []
        self._redo_stack: List[UndoEntry] = []

    @property
    def current_text(self) -> str:
        """Return the last committed plain text known to the undo manager."""
        return self._current_text

    @property
    def can_undo(self) -> bool:
        """Return True if at least one undo step is available."""
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        """Return True if at least one redo step is available."""
        return bool(self._redo_stack)

    @property
    def undo_count(self) -> int:
        """Return the number of available undo steps."""
        return len(self._undo_stack)

    @property
    def redo_count(self) -> int:
        """Return the number of available redo steps."""
        return len(self._redo_stack)

    def reset(self, text: str = "", anchor: int = 0, pos: int = 0) -> None:
        """Clear undo and redo stacks and initialize baseline document state."""
        self._current_text = text
        self._last_anchor = anchor
        self._last_pos = pos
        self._undo_stack.clear()
        self._redo_stack.clear()

    def update_cursor(self, anchor: int, pos: int) -> None:
        """Record latest caret/selection coordinates when no text change occurred."""
        self._last_anchor = anchor
        self._last_pos = pos

    def record_delta(
        self,
        offset: int,
        removed: str,
        inserted: str,
        after_anchor: int,
        after_pos: int,
        *,
        atomic: bool = False,
        force_merge: bool = False,
        now: Optional[float] = None,
    ) -> bool:
        """Record an already-known (offset, removed, inserted) delta without scanning full text."""
        if removed == inserted:
            self._last_anchor = after_anchor
            self._last_pos = after_pos
            return False

        old_text = self._current_text
        new_text = old_text[:offset] + inserted + old_text[offset + len(removed) :]

        if force_merge and self._undo_stack:
            return self.record_change(
                new_text,
                after_anchor,
                after_pos,
                atomic=atomic,
                force_merge=True,
                now=now,
            )

        ts = time.monotonic() if now is None else now
        before_anchor = self._last_anchor
        before_pos = self._last_pos

        kind = self._classify_edit(
            removed, inserted, before_anchor, before_pos, after_pos, atomic=atomic
        )

        merged = False
        if self._undo_stack and kind != "atomic":
            merged = self._try_coalesce(
                self._undo_stack[-1],
                offset,
                removed,
                inserted,
                before_pos,
                after_anchor,
                after_pos,
                kind,
                ts,
            )

        if not merged:
            self._undo_stack.append(
                UndoEntry(
                    offset=offset,
                    removed=removed,
                    inserted=inserted,
                    before_anchor=before_anchor,
                    before_pos=before_pos,
                    after_anchor=after_anchor,
                    after_pos=after_pos,
                    coalesce_kind=kind,
                    timestamp=ts,
                )
            )
            if len(self._undo_stack) > self._max_steps:
                self._undo_stack.pop(0)

        self._redo_stack.clear()
        self._current_text = new_text
        self._last_anchor = after_anchor
        self._last_pos = after_pos
        return True

    def record_change(
        self,
        new_text: str,
        after_anchor: int,
        after_pos: int,
        *,
        atomic: bool = False,
        force_merge: bool = False,
        now: Optional[float] = None,
    ) -> bool:
        """Record a plain-text transition from current_text to new_text.

        Returns True if a real text change was recorded, False if text was identical.
        """
        old_text = self._current_text
        if new_text == old_text:
            self._last_anchor = after_anchor
            self._last_pos = after_pos
            return False

        ts = time.monotonic() if now is None else now
        before_anchor = self._last_anchor
        before_pos = self._last_pos

        if force_merge and self._undo_stack:
            prev = self._undo_stack[-1]
            doc_before_prev = (
                old_text[: prev.offset]
                + prev.removed
                + old_text[prev.offset + len(prev.inserted) :]
            )
            offset, removed, inserted = compute_text_delta(doc_before_prev, new_text)
            if removed == "" and inserted == "":
                self._undo_stack.pop()
            else:
                prev.offset = offset
                prev.removed = removed
                prev.inserted = inserted
                prev.after_anchor = after_anchor
                prev.after_pos = after_pos
                prev.coalesce_kind = "atomic"
                prev.timestamp = ts
            self._current_text = new_text
            self._last_anchor = after_anchor
            self._last_pos = after_pos
            self._redo_stack.clear()
            return True

        offset, removed, inserted = compute_text_delta(old_text, new_text)
        kind = self._classify_edit(
            removed, inserted, before_anchor, before_pos, after_pos, atomic=atomic
        )

        merged = False
        if self._undo_stack and kind != "atomic":
            merged = self._try_coalesce(
                self._undo_stack[-1],
                offset,
                removed,
                inserted,
                before_pos,
                after_anchor,
                after_pos,
                kind,
                ts,
            )

        if not merged:
            self._undo_stack.append(
                UndoEntry(
                    offset=offset,
                    removed=removed,
                    inserted=inserted,
                    before_anchor=before_anchor,
                    before_pos=before_pos,
                    after_anchor=after_anchor,
                    after_pos=after_pos,
                    coalesce_kind=kind,
                    timestamp=ts,
                )
            )
            if len(self._undo_stack) > self._max_steps:
                self._undo_stack.pop(0)

        self._redo_stack.clear()
        self._current_text = new_text
        self._last_anchor = after_anchor
        self._last_pos = after_pos
        return True

    def undo(self) -> Optional[Tuple[int, int, str, int, int]]:
        """Pop the top undo step and push it to redo.

        Returns (replace_start, replace_end, replacement_text, target_anchor, target_pos)
        or None if undo stack is empty.
        """
        if not self._undo_stack:
            return None

        entry = self._undo_stack.pop()
        replace_start = entry.offset
        replace_end = entry.offset + len(entry.inserted)
        replacement = entry.removed

        restored_text = (
            self._current_text[:replace_start]
            + replacement
            + self._current_text[replace_end:]
        )
        self._redo_stack.append(entry)
        self._current_text = restored_text
        self._last_anchor = entry.before_anchor
        self._last_pos = entry.before_pos

        return (
            replace_start,
            replace_end,
            replacement,
            entry.before_anchor,
            entry.before_pos,
        )

    def redo(self) -> Optional[Tuple[int, int, str, int, int]]:
        """Pop the top redo step and push it back to undo.

        Returns (replace_start, replace_end, replacement_text, target_anchor, target_pos)
        or None if redo stack is empty.
        """
        if not self._redo_stack:
            return None

        entry = self._redo_stack.pop()
        replace_start = entry.offset
        replace_end = entry.offset + len(entry.removed)
        replacement = entry.inserted

        restored_text = (
            self._current_text[:replace_start]
            + replacement
            + self._current_text[replace_end:]
        )
        self._undo_stack.append(entry)
        self._current_text = restored_text
        self._last_anchor = entry.after_anchor
        self._last_pos = entry.after_pos

        return (
            replace_start,
            replace_end,
            replacement,
            entry.after_anchor,
            entry.after_pos,
        )

    @staticmethod
    def _classify_edit(
        removed: str,
        inserted: str,
        before_anchor: int,
        before_pos: int,
        after_pos: int,
        *,
        atomic: bool,
    ) -> str:
        if atomic or before_anchor != before_pos:
            return "atomic"
        if removed == "" and len(inserted) == 1 and inserted != "\n":
            return "insert"
        if inserted == "" and len(removed) == 1 and removed != "\n":
            return "backspace" if after_pos < before_pos else "delete_fwd"
        return "atomic"

    def _try_coalesce(
        self,
        prev: UndoEntry,
        offset: int,
        removed: str,
        inserted: str,
        before_pos: int,
        after_anchor: int,
        after_pos: int,
        kind: str,
        ts: float,
    ) -> bool:
        if prev.coalesce_kind != kind:
            return False
        if ts - prev.timestamp > self.COALESCE_WINDOW_SEC:
            return False
        if before_pos != prev.after_pos or prev.after_anchor != prev.after_pos:
            return False

        if kind == "insert":
            # Break typing burst after trailing whitespace so word-by-word undo stays crisp
            if prev.inserted and prev.inserted[-1].isspace():
                return False
            if offset == prev.offset + len(prev.inserted):
                prev.inserted += inserted
                prev.after_anchor = after_anchor
                prev.after_pos = after_pos
                prev.timestamp = ts
                return True
            return False

        if kind == "backspace":
            if offset + len(removed) == prev.offset:
                prev.offset = offset
                prev.removed = removed + prev.removed
                prev.after_anchor = after_anchor
                prev.after_pos = after_pos
                prev.timestamp = ts
                return True
            return False

        if kind == "delete_fwd":
            if offset == prev.offset:
                prev.removed += removed
                prev.after_anchor = after_anchor
                prev.after_pos = after_pos
                prev.timestamp = ts
                return True
            return False

        return False
