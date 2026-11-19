"""Utility functions for block-level manipulation (move, duplicate, delete) and grip handle rendering."""

from __future__ import annotations

import re
from typing import Optional, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QTextCursor, QTextDocument

CALLOUT_PATTERN = re.compile(
    r"^>\s*\[!(NOTE|TIP|WARNING|IMPORTANT|CAUTION|INFO|DANGER)\](?:\s+(.*))?$",
    re.IGNORECASE,
)

CALLOUT_COLORS = {
    "NOTE": QColor("#0a84ff"),       # Modern Blue
    "INFO": QColor("#0a84ff"),       # Modern Blue
    "TIP": QColor("#30d158"),        # Neon Emerald Green
    "WARNING": QColor("#ff9f0a"),    # Warm Amber
    "IMPORTANT": QColor("#bf5af2"),  # Royal Purple
    "CAUTION": QColor("#ff453a"),    # Coral Red
    "DANGER": QColor("#ff453a"),     # Coral Red
}


def get_callout_info(text: str) -> Optional[Tuple[str, QColor, str]]:
    """Return (callout_type, color, title) if line is a callout header, else None."""
    m = CALLOUT_PATTERN.match(text.strip())
    if not m:
        return None
    c_type = m.group(1).upper()
    title = m.group(2) or c_type.capitalize()
    color = CALLOUT_COLORS.get(c_type, QColor("#0a84ff"))
    return c_type, color, title


def get_selected_block_range(doc: QTextDocument, cursor: QTextCursor) -> Tuple[int, int]:
    """Return (start_block_num, end_block_num) for the current cursor or selection."""
    has_sel = cursor.hasSelection()
    s_pos = cursor.selectionStart() if has_sel else cursor.position()
    e_pos = cursor.selectionEnd() if has_sel else cursor.position()
    s_b = doc.findBlock(s_pos).blockNumber()
    e_b = doc.findBlock(e_pos).blockNumber()

    # If selection ends strictly at the first character of the next block, don't include it
    if has_sel and e_pos > s_pos and doc.findBlock(e_pos).position() == e_pos:
        e_b = max(s_b, e_b - 1)

    return s_b, e_b


def move_selected_blocks_up(doc: QTextDocument, cursor: QTextCursor) -> QTextCursor:
    """Move current block(s) up by one block, preserving cursor position and selection."""
    s_b, e_b = get_selected_block_range(doc, cursor)
    if s_b <= 0:
        return cursor

    has_sel = cursor.hasSelection()
    pos_in_b = cursor.positionInBlock()

    cursor.beginEditBlock()
    cur_lines = [doc.findBlockByNumber(i).text() for i in range(s_b, e_b + 1)]
    prev_line = doc.findBlockByNumber(s_b - 1).text()

    replace_c = QTextCursor(doc.findBlockByNumber(s_b - 1))
    end_block = doc.findBlockByNumber(e_b)
    replace_c.setPosition(end_block.position() + end_block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
    new_text = "\n".join(cur_lines) + "\n" + prev_line
    replace_c.insertText(new_text)
    cursor.endEditBlock()

    new_sb = doc.findBlockByNumber(s_b - 1)
    new_eb = doc.findBlockByNumber(e_b - 1)
    new_c = QTextCursor(doc)
    if has_sel:
        new_c.setPosition(new_sb.position())
        new_c.setPosition(new_eb.position() + new_eb.length() - 1, QTextCursor.MoveMode.KeepAnchor)
    else:
        new_c.setPosition(new_sb.position() + min(len(new_sb.text()), pos_in_b))
    return new_c


def move_selected_blocks_down(doc: QTextDocument, cursor: QTextCursor) -> QTextCursor:
    """Move current block(s) down by one block, preserving cursor position and selection."""
    s_b, e_b = get_selected_block_range(doc, cursor)
    if e_b >= doc.blockCount() - 1:
        return cursor

    has_sel = cursor.hasSelection()
    pos_in_b = cursor.positionInBlock()

    cursor.beginEditBlock()
    cur_lines = [doc.findBlockByNumber(i).text() for i in range(s_b, e_b + 1)]
    next_line = doc.findBlockByNumber(e_b + 1).text()

    replace_c = QTextCursor(doc.findBlockByNumber(s_b))
    end_block = doc.findBlockByNumber(e_b + 1)
    replace_c.setPosition(end_block.position() + end_block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
    new_text = next_line + "\n" + "\n".join(cur_lines)
    replace_c.insertText(new_text)
    cursor.endEditBlock()

    new_sb = doc.findBlockByNumber(s_b + 1)
    new_eb = doc.findBlockByNumber(e_b + 1)
    new_c = QTextCursor(doc)
    if has_sel:
        new_c.setPosition(new_sb.position())
        new_c.setPosition(new_eb.position() + new_eb.length() - 1, QTextCursor.MoveMode.KeepAnchor)
    else:
        new_c.setPosition(new_sb.position() + min(len(new_sb.text()), pos_in_b))
    return new_c


def duplicate_selected_blocks(doc: QTextDocument, cursor: QTextCursor) -> QTextCursor:
    """Duplicate the current line or selected block(s) directly below."""
    s_b, e_b = get_selected_block_range(doc, cursor)

    cursor.beginEditBlock()
    cur_lines = [doc.findBlockByNumber(i).text() for i in range(s_b, e_b + 1)]
    dup_text = "\n".join(cur_lines)

    end_block = doc.findBlockByNumber(e_b)
    ins_c = QTextCursor(end_block)
    ins_c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    ins_c.insertText("\n" + dup_text)
    cursor.endEditBlock()

    # Move cursor into the duplicated block
    new_target_b = doc.findBlockByNumber(e_b + 1)
    new_c = QTextCursor(new_target_b)
    new_c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    return new_c


def delete_selected_blocks(doc: QTextDocument, cursor: QTextCursor) -> QTextCursor:
    """Delete the current block or selected lines cleanly without leaving blank lines."""
    s_b, e_b = get_selected_block_range(doc, cursor)

    cursor.beginEditBlock()
    first_b = doc.findBlockByNumber(s_b)
    last_b = doc.findBlockByNumber(e_b)

    del_c = QTextCursor(first_b)
    if e_b < doc.blockCount() - 1:
        # Include newline after last block
        next_b = last_b.next()
        del_c.setPosition(next_b.position(), QTextCursor.MoveMode.KeepAnchor)
    elif s_b > 0:
        # Delete preceding newline
        prev_b = first_b.previous()
        del_c.setPosition(prev_b.position() + prev_b.length() - 1)
        del_c.setPosition(last_b.position() + last_b.length() - 1, QTextCursor.MoveMode.KeepAnchor)
    else:
        # Document has only this block, clear text
        del_c.setPosition(last_b.position() + last_b.length() - 1, QTextCursor.MoveMode.KeepAnchor)

    del_c.removeSelectedText()
    cursor.endEditBlock()

    # Ensure cursor remains in a valid position
    active_b = doc.findBlockByNumber(min(s_b, doc.blockCount() - 1))
    new_c = QTextCursor(active_b)
    return new_c


def render_grip_handle(
    painter: QPainter,
    rect: QRectF,
    is_hovered: bool = False,
    ui_scale: float = 1.0,
) -> None:
    """Render a Notion/Anytype-style 6-dot grip handle (2 columns x 3 rows)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    dot_r = round(1.5 * ui_scale, 1)
    col_gap = round(5.0 * ui_scale)
    row_gap = round(5.0 * ui_scale)

    color = QColor("#0a84ff") if is_hovered else QColor("#4e4e5a")
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(color))

    start_x = rect.left() + (rect.width() - col_gap) / 2.0
    start_y = rect.top() + (rect.height() - (2 * row_gap)) / 2.0

    for col in (0, 1):
        cx = start_x + (col * col_gap)
        for row in (0, 1, 2):
            cy = start_y + (row * row_gap)
            painter.drawEllipse(QPointF(cx, cy), dot_r, dot_r)

    painter.restore()
