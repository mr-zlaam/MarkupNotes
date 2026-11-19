"""Unit tests for block-level operations, keyboard movement, callouts, and grip handle."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QKeyEvent, QPainter, QPixmap, QTextCursor, QTextDocument
from PyQt6.QtWidgets import QApplication

from ui.editor import MarkdownEditor
from ui.slash_menu import COMMANDS
from utils.block_ops import (
    CALLOUT_COLORS,
    delete_selected_blocks,
    duplicate_selected_blocks,
    get_callout_info,
    move_selected_blocks_down,
    move_selected_blocks_up,
    render_grip_handle,
)


class TestBlockOperations(unittest.TestCase):
    """Test block manipulation helpers (move, duplicate, delete) on QTextDocument."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_move_block_down_single(self) -> None:
        doc = QTextDocument()
        doc.setPlainText("Line 1\nLine 2\nLine 3")
        c = QTextCursor(doc.findBlockByNumber(0))
        c.setPosition(3)  # inside Line 1

        new_c = move_selected_blocks_down(doc, c)
        self.assertEqual(doc.toPlainText(), "Line 2\nLine 1\nLine 3")
        self.assertEqual(new_c.blockNumber(), 1)

    def test_move_block_down_at_bottom_noop(self) -> None:
        doc = QTextDocument()
        doc.setPlainText("Line 1\nLine 2")
        c = QTextCursor(doc.findBlockByNumber(1))
        new_c = move_selected_blocks_down(doc, c)
        self.assertEqual(doc.toPlainText(), "Line 1\nLine 2")
        self.assertEqual(new_c.blockNumber(), 1)

    def test_move_block_up_single(self) -> None:
        doc = QTextDocument()
        doc.setPlainText("Line 1\nLine 2\nLine 3")
        c = QTextCursor(doc.findBlockByNumber(1))
        c.setPosition(10)  # inside Line 2

        new_c = move_selected_blocks_up(doc, c)
        self.assertEqual(doc.toPlainText(), "Line 2\nLine 1\nLine 3")
        self.assertEqual(new_c.blockNumber(), 0)

    def test_move_block_up_at_top_noop(self) -> None:
        doc = QTextDocument()
        doc.setPlainText("Line 1\nLine 2")
        c = QTextCursor(doc.findBlockByNumber(0))
        new_c = move_selected_blocks_up(doc, c)
        self.assertEqual(doc.toPlainText(), "Line 1\nLine 2")
        self.assertEqual(new_c.blockNumber(), 0)

    def test_move_multiline_selection_down(self) -> None:
        doc = QTextDocument()
        doc.setPlainText("A\nB\nC\nD\nE")
        c = QTextCursor(doc)
        b_b = doc.findBlockByNumber(1)  # B
        b_c = doc.findBlockByNumber(2)  # C
        c.setPosition(b_b.position())
        c.setPosition(b_c.position() + len(b_c.text()), QTextCursor.MoveMode.KeepAnchor)

        new_c = move_selected_blocks_down(doc, c)
        self.assertEqual(doc.toPlainText(), "A\nD\nB\nC\nE")
        self.assertTrue(new_c.hasSelection())

    def test_move_multiline_selection_up(self) -> None:
        doc = QTextDocument()
        doc.setPlainText("A\nD\nB\nC\nE")
        c = QTextCursor(doc)
        b_b = doc.findBlockByNumber(2)  # B
        b_c = doc.findBlockByNumber(3)  # C
        c.setPosition(b_b.position())
        c.setPosition(b_c.position() + len(b_c.text()), QTextCursor.MoveMode.KeepAnchor)

        new_c = move_selected_blocks_up(doc, c)
        self.assertEqual(doc.toPlainText(), "A\nB\nC\nD\nE")
        self.assertTrue(new_c.hasSelection())

    def test_duplicate_block(self) -> None:
        doc = QTextDocument()
        doc.setPlainText("Alpha\nBeta\nGamma")
        c = QTextCursor(doc.findBlockByNumber(1))  # Beta
        new_c = duplicate_selected_blocks(doc, c)
        self.assertEqual(doc.toPlainText(), "Alpha\nBeta\nBeta\nGamma")
        self.assertEqual(new_c.blockNumber(), 2)

    def test_delete_block_middle(self) -> None:
        doc = QTextDocument()
        doc.setPlainText("Alpha\nBeta\nGamma")
        c = QTextCursor(doc.findBlockByNumber(1))  # Beta
        delete_selected_blocks(doc, c)
        self.assertEqual(doc.toPlainText(), "Alpha\nGamma")

    def test_delete_block_last(self) -> None:
        doc = QTextDocument()
        doc.setPlainText("Alpha\nBeta")
        c = QTextCursor(doc.findBlockByNumber(1))  # Beta
        delete_selected_blocks(doc, c)
        self.assertEqual(doc.toPlainText(), "Alpha")


class TestCalloutsAndGrip(unittest.TestCase):
    """Test callout syntax parsing and grip rendering."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_get_callout_info(self) -> None:
        self.assertIsNotNone(get_callout_info("> [!NOTE]"))
        self.assertIsNotNone(get_callout_info("> [!TIP] Performance Tips"))
        self.assertIsNotNone(get_callout_info("> [!WARNING] Danger Zone"))
        self.assertIsNotNone(get_callout_info("> [!IMPORTANT]"))
        self.assertIsNotNone(get_callout_info("> [!CAUTION]"))

        info = get_callout_info("> [!TIP] Pro Tip")
        self.assertIsNotNone(info)
        c_type, color, title = info
        self.assertEqual(c_type, "TIP")
        self.assertEqual(color, CALLOUT_COLORS["TIP"])
        self.assertEqual(title, "Pro Tip")

        # Plain quotes should return None
        self.assertIsNone(get_callout_info("> Just a standard quote"))

    def test_render_grip_handle(self) -> None:
        pix = QPixmap(50, 50)
        pix.fill(QColor("#1e1e24"))
        p = QPainter(pix)
        rect = QRectF(10.0, 10.0, 14.0, 18.0)
        render_grip_handle(p, rect, is_hovered=False)
        render_grip_handle(p, rect, is_hovered=True)
        p.end()
        self.assertFalse(pix.isNull())

    def test_slash_menu_contains_callout(self) -> None:
        callout_cmds = [cmd for cmd in COMMANDS if cmd.id == "callout"]
        self.assertEqual(len(callout_cmds), 1)
        self.assertEqual(callout_cmds[0].prefix, "> [!NOTE] ")


class TestEditorBlockIntegration(unittest.TestCase):
    """Test editor keyboard shortcuts and grip handle mouse interactions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.editor = MarkdownEditor()
        self.editor.resize(800, 600)

    def tearDown(self) -> None:
        self.editor.deleteLater()

    def test_alt_up_down_shortcuts(self) -> None:
        self.editor.setPlainText("First\nSecond\nThird")
        c = QTextCursor(self.editor.document().findBlockByNumber(1))  # Second
        self.editor.setTextCursor(c)

        # Alt+Up moves Second up
        event_up = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Up,
            Qt.KeyboardModifier.AltModifier,
        )
        self.editor.keyPressEvent(event_up)
        self.assertEqual(self.editor.document().toPlainText(), "Second\nFirst\nThird")

        # Alt+Down moves Second down
        event_down = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Down,
            Qt.KeyboardModifier.AltModifier,
        )
        self.editor.keyPressEvent(event_down)
        self.assertEqual(self.editor.document().toPlainText(), "First\nSecond\nThird")

    def test_ctrl_shift_d_duplicate_shortcut(self) -> None:
        self.editor.setPlainText("Item 1\nItem 2")
        c = QTextCursor(self.editor.document().findBlockByNumber(0))
        self.editor.setTextCursor(c)

        event_dup = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_D,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        self.editor.keyPressEvent(event_dup)
        self.assertEqual(self.editor.document().toPlainText(), "Item 1\nItem 1\nItem 2")

    def test_callout_info_walking(self) -> None:
        content = (
            "> [!NOTE] Important Title\n"
            "> First detail line\n"
            "> Second detail line\n"
            "\n"
            "Normal paragraph"
        )
        self.editor.setPlainText(content)
        b2 = self.editor.document().findBlockByNumber(2)
        info = self.editor._get_callout_info_for_block(b2)
        self.assertIsNotNone(info)
        self.assertEqual(info[0], "NOTE")

        # Normal paragraph should not have callout info
        b4 = self.editor.document().findBlockByNumber(4)
        self.assertIsNone(self.editor._get_callout_info_for_block(b4))


if __name__ == "__main__":
    unittest.main()
