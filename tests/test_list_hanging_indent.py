"""Tests for hanging indent alignment on checkboxes, bullet lists, and numbered lists."""

import unittest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtCore import QPointF

from ui.editor import MarkdownEditor
from utils.markdown import calculate_block_hanging_indent

app = QApplication.instance() or QApplication([])


class TestListHangingIndentCalculation(unittest.TestCase):
    """Test calculate_block_hanging_indent mathematical calculations."""

    def setUp(self) -> None:
        self.font = QFont("sans-serif", 16)

    def test_normal_text_zero_margin_and_indent(self) -> None:
        lm, ti = calculate_block_hanging_indent("Regular paragraph of text", self.font)
        self.assertEqual(lm, 0.0)
        self.assertEqual(ti, 0.0)

    def test_empty_line_zero_margin_and_indent(self) -> None:
        lm, ti = calculate_block_hanging_indent("", self.font)
        self.assertEqual(lm, 0.0)
        self.assertEqual(ti, 0.0)

    def test_checkbox_hanging_indent(self) -> None:
        lm, ti = calculate_block_hanging_indent("- [ ] Checkbox task", self.font)
        self.assertGreater(lm, 20.0)
        self.assertAlmostEqual(lm + ti, 0.0, places=1)
        self.assertLess(ti, 0.0)

    def test_checked_matches_unchecked_advance(self) -> None:
        lm_unchecked, ti_unchecked = calculate_block_hanging_indent("- [ ] Task", self.font)
        lm_checked, ti_checked = calculate_block_hanging_indent("- [x] Task", self.font)
        self.assertAlmostEqual(lm_unchecked, lm_checked, places=2)
        self.assertAlmostEqual(ti_unchecked, ti_checked, places=2)

    def test_indented_checkbox(self) -> None:
        lm_base, _ = calculate_block_hanging_indent("- [ ] Task", self.font)
        lm_indented, ti_indented = calculate_block_hanging_indent("  - [ ] Task", self.font)
        self.assertGreater(lm_indented, lm_base)
        # First line starts at indent position (greater than 0)
        self.assertGreater(lm_indented + ti_indented, 0.0)

    def test_bullet_list_hanging_indent(self) -> None:
        for marker in ("-", "*", "+"):
            lm, ti = calculate_block_hanging_indent(f"{marker} Bullet item", self.font)
            self.assertGreater(lm, 15.0)
            self.assertAlmostEqual(lm + ti, 0.0, places=1)
            self.assertLess(ti, 0.0)

    def test_numbered_list_hanging_indent(self) -> None:
        lm1, ti1 = calculate_block_hanging_indent("1. Item 1", self.font)
        lm10, ti10 = calculate_block_hanging_indent("10. Item 10", self.font)
        self.assertGreater(lm1, 15.0)
        self.assertGreater(lm10, lm1)
        self.assertAlmostEqual(lm1 + ti1, 0.0, places=1)
        self.assertAlmostEqual(lm10 + ti10, 0.0, places=1)

    def test_blockquote_without_list(self) -> None:
        lm, ti = calculate_block_hanging_indent("> Quoted line", self.font)
        self.assertEqual(lm, 26.0)
        self.assertEqual(ti, 0.0)

    def test_blockquoted_checkbox(self) -> None:
        lm, ti = calculate_block_hanging_indent("> - [ ] Quoted task", self.font)
        self.assertGreater(lm, 26.0)
        # First line starts at the blockquote margin (26.0)
        self.assertAlmostEqual(lm + ti, 26.0, places=1)
        self.assertLess(ti, 0.0)


class TestEditorHangingIndentLayout(unittest.TestCase):
    """Test MarkdownEditor integration with hanging indents and multiline line wrapping."""

    def setUp(self) -> None:
        self.editor = MarkdownEditor()
        self.editor.resize(400, 600)
        self.editor.show()
        app.processEvents()

    def tearDown(self) -> None:
        self.editor.deleteLater()
        app.processEvents()

    def test_multiline_checkbox_hanging_indent(self) -> None:
        text = (
            "- [ ] Very long checkbox task description that will wrap across multiple "
            "lines of text in this narrow 400px editor widget so that hanging indent can be verified."
        )
        self.editor.setPlainText(text)
        app.processEvents()

        b = self.editor.document().firstBlock()
        bf = b.blockFormat()
        self.assertGreater(bf.leftMargin(), 20.0)
        self.assertLess(bf.textIndent(), -20.0)
        self.assertAlmostEqual(bf.leftMargin() + bf.textIndent(), 0.0, places=1)

        layout = b.layout()
        self.assertGreater(layout.lineCount(), 1)
        line0 = layout.lineAt(0)
        line1 = layout.lineAt(1)
        # Line 0 starts at 0 (first line)
        self.assertAlmostEqual(line0.x(), 0.0, delta=1.0)
        # Line 1 wraps at leftMargin (hanging indent)
        self.assertAlmostEqual(line1.x(), bf.leftMargin(), delta=1.0)

    def test_multiline_bullet_hanging_indent(self) -> None:
        text = (
            "- Very long bullet list item description that will wrap across multiple "
            "lines of text in this narrow 400px editor widget."
        )
        self.editor.setPlainText(text)
        app.processEvents()

        b = self.editor.document().firstBlock()
        bf = b.blockFormat()
        self.assertGreater(bf.leftMargin(), 20.0)
        self.assertLess(bf.textIndent(), -20.0)

        layout = b.layout()
        self.assertGreater(layout.lineCount(), 1)
        line0 = layout.lineAt(0)
        line1 = layout.lineAt(1)
        self.assertAlmostEqual(line0.x(), 0.0, delta=1.0)
        self.assertAlmostEqual(line1.x(), bf.leftMargin(), delta=1.0)

    def test_multiline_numbered_hanging_indent(self) -> None:
        text = (
            "1. Very long numbered list item description that will wrap across multiple "
            "lines of text in this narrow 400px editor widget."
        )
        self.editor.setPlainText(text)
        app.processEvents()

        b = self.editor.document().firstBlock()
        bf = b.blockFormat()
        self.assertGreater(bf.leftMargin(), 20.0)
        self.assertLess(bf.textIndent(), -20.0)

        layout = b.layout()
        self.assertGreater(layout.lineCount(), 1)
        line0 = layout.lineAt(0)
        line1 = layout.lineAt(1)
        self.assertAlmostEqual(line0.x(), 0.0, delta=1.0)
        self.assertAlmostEqual(line1.x(), bf.leftMargin(), delta=1.0)

    def test_checkbox_hit_testing_with_hanging_indent(self) -> None:
        text = (
            "- [ ] Very long checkbox task description that wraps across multiple lines "
            "of text so we can verify click hit testing on line 0 vs line 1."
        )
        self.editor.setPlainText(text)
        app.processEvents()

        b = self.editor.document().firstBlock()
        c0 = QTextCursor(b)
        r0 = self.editor.cursorRect(c0)

        # Click on line 0 at checkbox icon
        cb_pos = QPointF(float(r0.left() + 6), float(r0.top() + 8))
        hit_block = self.editor._checkbox_block_at_pos(cb_pos)
        self.assertIsNotNone(hit_block)
        self.assertEqual(hit_block.blockNumber(), b.blockNumber())

        # Click on line 1 directly below checkbox (should NOT trigger checkbox)
        line1_gutter_pos = QPointF(float(r0.left() + 6), float(r0.top() + 35))
        miss_block = self.editor._checkbox_block_at_pos(line1_gutter_pos)
        self.assertIsNone(miss_block)

    def test_ui_scale_updates_hanging_indent(self) -> None:
        text = "- [ ] Task item with scaling"
        self.editor.setPlainText(text)
        app.processEvents()

        b = self.editor.document().firstBlock()
        lm_scale1 = b.blockFormat().leftMargin()

        # Scale up to 1.5 (font size scales proportionally as in apply_config)
        self.editor.set_font_size(int(round(16 * 1.5)))
        self.editor.set_ui_scale(1.5)
        # Flush debounced margin timer
        self.editor._update_block_margins()
        app.processEvents()

        b_scaled = self.editor.document().firstBlock()
        lm_scale15 = b_scaled.blockFormat().leftMargin()
        self.assertGreater(lm_scale15, lm_scale1)

    def test_bullet_scale_updates_without_font_change(self) -> None:
        text = "- Bullet item scaling"
        self.editor.setPlainText(text)
        app.processEvents()

        b = self.editor.document().firstBlock()
        lm_scale1 = b.blockFormat().leftMargin()

        self.editor.set_ui_scale(1.5)
        self.editor._update_block_margins()
        app.processEvents()

        b_scaled = self.editor.document().firstBlock()
        lm_scale15 = b_scaled.blockFormat().leftMargin()
        self.assertGreater(lm_scale15, lm_scale1)
