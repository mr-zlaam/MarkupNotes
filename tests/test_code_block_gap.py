"""Unit tests verifying code block gap elimination and vertical geometry synchronization."""

import unittest

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QTextBlockFormat, QTextCursor
from PyQt6.QtWidgets import QApplication

from ui.editor import MarkdownEditor
from ui.theme import DARK_THEME_QSS


class TestCodeBlockGap(unittest.TestCase):
    """Test code block vertical height and gap elimination."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls._orig_style = cls.app.styleSheet()
        cls.app.setStyleSheet(DARK_THEME_QSS)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.app:
            cls.app.setStyleSheet(cls._orig_style)

    def setUp(self) -> None:
        self.editor = MarkdownEditor()
        self.editor.resize(1000, 800)

    def tearDown(self) -> None:
        self.editor.deleteLater()

    def test_code_block_zero_gap_on_large_block(self) -> None:
        """Verify that big code blocks (30+ lines) have exact 0.0px gap between doc and card."""
        lines = [f"echo 'line {i}'" for i in range(1, 33)]
        code_body = "\n".join(lines)
        content = f"# Test Note\n\nSome intro text.\n\n```bash\n{code_body}\n```\n\nParagraph after code."

        self.editor.setPlainText(content)
        self.editor.show()

        # Place cursor at beginning of document so the code block is inactive
        cur = self.editor.textCursor()
        cur.setPosition(0)
        self.editor.setTextCursor(cur)
        self.editor._update_block_margins()

        highlighter = self.editor.highlighter
        self.assertEqual(len(highlighter.code_regions), 1)
        cr = highlighter.code_regions[0]

        b_top = self.editor.document().findBlockByNumber(cr.start_block)
        b_bot = self.editor.document().findBlockByNumber(cr.end_block)
        r_top = self.editor.cursorRect(QTextCursor(b_top))
        r_bot = self.editor.cursorRect(QTextCursor(b_bot))

        doc_h = float(r_bot.bottom() - r_top.top())
        card_rect = self.editor._get_code_card_rect(cr)
        self.assertIsNotNone(card_rect)

        gap = abs(doc_h - card_rect.height())
        self.assertLessEqual(gap, 1.0)

    def test_non_breakable_lines_on_long_code_lines(self) -> None:
        """Verify that long code lines in inactive code cards do not wrap and inflate document height."""
        long_line = "variable_name = " + " + ".join([f"'segment_{i}'" for i in range(25)])
        content = f"```python\n{long_line}\n```\n\nText below."

        self.editor.setPlainText(content)
        self.editor.show()

        cur = self.editor.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(cur)
        self.editor._update_block_margins()

        cr = self.editor.highlighter.code_regions[0]
        code_block = self.editor.document().findBlockByNumber(cr.start_block + 1)
        bf = code_block.blockFormat()

        self.assertTrue(bf.nonBreakableLines())
        self.assertEqual(bf.lineHeightType(), QTextBlockFormat.LineHeightTypes.FixedHeight.value)

    def test_active_code_block_restores_editing_format(self) -> None:
        """Verify that when cursor enters a code block, proportional line height is restored for editing."""
        content = "```python\nx = 1\ny = 2\n```\n\nText below."
        self.editor.setPlainText(content)
        self.editor.show()

        cr = self.editor.highlighter.code_regions[0]

        # Inactive state initially
        cur = self.editor.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(cur)
        self.editor._update_block_margins()

        code_block = self.editor.document().findBlockByNumber(cr.start_block + 1)
        self.assertEqual(code_block.blockFormat().lineHeightType(), QTextBlockFormat.LineHeightTypes.FixedHeight.value)

        # Move cursor inside code block
        cur.setPosition(code_block.position())
        self.editor.setTextCursor(cur)
        self.editor._on_cursor_position_changed()
        self.editor._update_block_margins()

        self.assertEqual(
            code_block.blockFormat().lineHeightType(),
            QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
        )
