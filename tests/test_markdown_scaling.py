"""Unit tests verifying UI scaling for checkboxes, bullet lists, and code blocks."""

import unittest
from PyQt6.QtCore import QPointF, QRect, QRectF
from PyQt6.QtGui import QFont, QPainter, QPixmap, QTextCursor
from PyQt6.QtWidgets import QApplication

from ui.editor import MarkdownEditor
from ui.highlighter import MarkdownHighlighter
from utils.code_engine import (
    CodeRegion,
    get_code_content_width,
    get_code_copy_button_rect,
    get_code_edit_button_rect,
    get_code_gutter_width,
    get_code_scrollbar_geometry,
    render_code_card,
)


class TestMarkdownScaling(unittest.TestCase):
    """Test scaling of checkboxes, bullets, and code cards with ui_scale."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_highlighter_scaling_properties(self) -> None:
        """Verify highlighter bullet and list spacings scale proportionally with ui_scale."""
        editor = MarkdownEditor()
        highlighter = editor.highlighter

        # Default scale 1.0
        highlighter.set_ui_scale(1.0)
        self.assertAlmostEqual(highlighter.ui_scale, 1.0)
        self.assertAlmostEqual(highlighter.bullet_hide_format.fontLetterSpacing(), 10.0, places=1)
        self.assertAlmostEqual(highlighter.ordered_list_space_format.fontLetterSpacing(), 14.0, places=1)

        # Scale 1.5
        highlighter.ui_scale = 1.5
        self.assertAlmostEqual(highlighter.ui_scale, 1.5)
        self.assertAlmostEqual(highlighter.bullet_hide_format.fontLetterSpacing(), 15.0, places=1)
        self.assertAlmostEqual(highlighter.ordered_list_space_format.fontLetterSpacing(), 21.0, places=1)

        # Scale 1.25
        highlighter.ui_scale = 1.25
        self.assertAlmostEqual(highlighter.bullet_hide_format.fontLetterSpacing(), 12.5, places=1)
        self.assertAlmostEqual(highlighter.ordered_list_space_format.fontLetterSpacing(), 17.5, places=1)

    def test_checkbox_hit_testing_scales(self) -> None:
        """Verify checkbox click hit-testing area expands with ui_scale."""
        editor = MarkdownEditor()
        editor.setPlainText("- [ ] Task item 1\n- [x] Task item 2")
        editor.resize(600, 400)
        editor.show()

        # At scale 1.0
        editor.set_ui_scale(1.0)
        block = editor.document().firstBlock()
        cur = QTextCursor(block)
        r = editor.cursorRect(cur)
        box_x = float(r.left() + 3)
        box_y = float(r.top()) + (r.height() - 14.0) / 2.0

        hit_block = editor._checkbox_block_at_pos(QPointF(box_x + 5, box_y + 5))
        self.assertIsNotNone(hit_block)
        self.assertEqual(hit_block.blockNumber(), 0)

        # At scale 1.5, click point inside scaled box (e.g. offset 18px from box_x) is detected
        editor.set_ui_scale(1.5)
        scaled_box_x = float(r.left() + round(3.0 * 1.5))
        scaled_box_y = float(r.top()) + (r.height() - round(14.0 * 1.5)) / 2.0
        hit_block_scaled = editor._checkbox_block_at_pos(QPointF(scaled_box_x + 18, scaled_box_y + 18))
        self.assertIsNotNone(hit_block_scaled)
        self.assertEqual(hit_block_scaled.blockNumber(), 0)

        editor.close()
        editor.deleteLater()

    def test_checkbox_and_bullet_drawing_at_scale(self) -> None:
        """Verify _draw_checkbox and _draw_bullet execute without error at different scales."""
        editor = MarkdownEditor()
        editor.resize(600, 400)
        pm = QPixmap(300, 200)
        painter = QPainter(pm)

        rect = QRect(10, 20, 20, 30)

        # Draw at scale 1.0
        editor.set_ui_scale(1.0)
        editor._draw_bullet(painter, rect, indent_len=0)
        editor._draw_bullet(painter, rect, indent_len=2)
        editor._draw_bullet(painter, rect, indent_len=4)
        editor._draw_checkbox(painter, rect, is_checked=False)
        editor._draw_checkbox(painter, rect, is_checked=True)

        # Draw at scale 1.5
        editor.set_ui_scale(1.5)
        editor._draw_bullet(painter, rect, indent_len=0)
        editor._draw_bullet(painter, rect, indent_len=2)
        editor._draw_bullet(painter, rect, indent_len=4)
        editor._draw_checkbox(painter, rect, is_checked=False)
        editor._draw_checkbox(painter, rect, is_checked=True)

        painter.end()
        editor.close()
        editor.deleteLater()

    def test_code_card_geometry_scales(self) -> None:
        """Verify code card dimensions and buttons scale proportionally with ui_scale."""
        card_rect_10 = QRectF(20.0, 30.0, 500.0, 200.0)

        # Button rects at scale 1.0
        copy_10 = get_code_copy_button_rect(card_rect_10, ui_scale=1.0)
        edit_10 = get_code_edit_button_rect(card_rect_10, ui_scale=1.0)
        self.assertAlmostEqual(copy_10.width(), 58.0)
        self.assertAlmostEqual(copy_10.height(), 20.0)
        self.assertAlmostEqual(edit_10.width(), 48.0)
        self.assertAlmostEqual(edit_10.height(), 20.0)

        # Button rects at scale 1.5
        copy_15 = get_code_copy_button_rect(card_rect_10, ui_scale=1.5)
        edit_15 = get_code_edit_button_rect(card_rect_10, ui_scale=1.5)
        self.assertAlmostEqual(copy_15.width(), 87.0)  # 58 * 1.5
        self.assertAlmostEqual(copy_15.height(), 30.0)  # 20 * 1.5
        self.assertAlmostEqual(edit_15.width(), 72.0)  # 48 * 1.5
        self.assertAlmostEqual(edit_15.height(), 30.0)  # 20 * 1.5

        # Code content width scales with font size
        reg = CodeRegion(start_block=0, end_block=2, language="python", lines=["print('hello world')"])
        w_10 = get_code_content_width(reg, ui_scale=1.0)
        w_15 = get_code_content_width(reg, ui_scale=1.5)
        self.assertGreater(w_15, w_10)

        # Code gutter width scales with font size
        gw_10 = get_code_gutter_width(reg, ui_scale=1.0)
        gw_15 = get_code_gutter_width(reg, ui_scale=1.5)
        self.assertGreater(gw_15, gw_10)

        # Scrollbar geometry scales with ui_scale
        sb_10 = get_code_scrollbar_geometry(card_rect_10, content_width=800.0, scroll_x=0.0, ui_scale=1.0)
        sb_15 = get_code_scrollbar_geometry(card_rect_10, content_width=800.0, scroll_x=0.0, ui_scale=1.5)
        self.assertIsNotNone(sb_10)
        self.assertIsNotNone(sb_15)
        self.assertGreater(sb_15[0].height(), sb_10[0].height())

    def test_editor_code_card_rect_scales(self) -> None:
        """Verify MarkdownEditor._get_code_card_rect height scales proportionally."""
        editor = MarkdownEditor()
        editor.setPlainText("```python\na = 1\nb = 2\nc = 3\n```")
        editor.resize(600, 400)
        editor.show()

        highlighter = editor.highlighter
        highlighter.rehighlight()
        self.assertEqual(len(highlighter.code_regions), 1)
        cr = highlighter.code_regions[0]

        editor.set_ui_scale(1.0)
        r_10 = editor._get_code_card_rect(cr)
        self.assertIsNotNone(r_10)

        editor.set_ui_scale(1.5)
        r_15 = editor._get_code_card_rect(cr)
        self.assertIsNotNone(r_15)

        # Card height at 1.5x should be significantly taller than at 1.0x
        self.assertGreater(r_15.height(), r_10.height())
        expected_ratio = r_15.height() / r_10.height()
        self.assertAlmostEqual(expected_ratio, 1.5, delta=0.08)

        editor.close()
        editor.deleteLater()

    def test_render_code_card_scaled(self) -> None:
        """Verify render_code_card paints cleanly with scaling applied."""
        pm = QPixmap(500, 300)
        painter = QPainter(pm)
        reg = CodeRegion(start_block=0, end_block=3, language="python", lines=["x = 10", "y = 20", "z = x + y"])
        card_rect = QRectF(10.0, 10.0, 400.0, 200.0)

        render_code_card(painter, card_rect, reg, ui_scale=1.25, show_line_numbers=True)
        render_code_card(painter, card_rect, reg, ui_scale=1.5, show_line_numbers=False)
        painter.end()


if __name__ == "__main__":
    unittest.main()
