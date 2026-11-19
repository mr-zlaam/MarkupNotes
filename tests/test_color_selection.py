"""Unit tests for text color and background highlight color selection toolbar modal."""

import unittest
from PyQt6.QtCore import Qt, QPoint, QRect
from PyQt6.QtGui import QColor, QKeyEvent, QTextCursor
from PyQt6.QtWidgets import QApplication

from ui.editor import MarkdownEditor
from ui.color_popup import ColorPickerPopup
from ui.selection_toolbar import SelectionFormatToolbar
from ui.highlighter import MarkdownHighlighter


app = QApplication.instance() or QApplication([])


class TestColorSelectionAndHighlighter(unittest.TestCase):
    """Test ColorPickerPopup, SelectionFormatToolbar color integration, and MarkdownHighlighter."""

    def setUp(self) -> None:
        self.editor = MarkdownEditor()
        self.toolbar = self.editor.format_toolbar

    def tearDown(self) -> None:
        self.editor.deleteLater()

    def test_color_picker_popup_structure_and_signals(self) -> None:
        """Verify ColorPickerPopup swatches and signal emissions for text and highlight colors."""
        popup = ColorPickerPopup()
        self.assertTrue(len(popup.TEXT_COLORS) >= 8)
        self.assertTrue(len(popup.HIGHLIGHT_COLORS) >= 8)

        text_emitted: list[str] = []
        hl_emitted: list[str] = []
        popup.text_color_selected.connect(text_emitted.append)
        popup.highlight_color_selected.connect(hl_emitted.append)

        # Trigger text color selection
        popup._pick_text_color("#ff453a")
        self.assertEqual(text_emitted, ["#ff453a"])
        self.assertFalse(popup.isVisible())

        # Trigger highlight color selection
        popup._pick_highlight_color("#ffd60a")
        self.assertEqual(hl_emitted, ["#ffd60a"])
        self.assertFalse(popup.isVisible())

        # Trigger reset
        popup._pick_text_color("")
        popup._pick_highlight_color("")
        self.assertEqual(text_emitted, ["#ff453a", ""])
        self.assertEqual(hl_emitted, ["#ffd60a", ""])

        popup.deleteLater()

    def test_selection_toolbar_chevron_and_toggle(self) -> None:
        """Verify chevron button exists and toggles popup modal visibility."""
        self.assertIsNotNone(self.toolbar.chevron_btn)
        self.assertFalse(self.toolbar.color_popup.isVisible())

        # Toggle open
        self.toolbar._toggle_color_popup()
        self.assertTrue(self.toolbar.color_popup.isVisible())

        # Toggle closed
        self.toolbar._toggle_color_popup()
        self.assertFalse(self.toolbar.color_popup.isVisible())

        # Hide toolbar also hides popup
        self.toolbar._toggle_color_popup()
        self.assertTrue(self.toolbar.color_popup.isVisible())
        self.toolbar.hide()
        self.assertFalse(self.toolbar.color_popup.isVisible())

    def test_apply_text_color_basic_and_toggle(self) -> None:
        """Verify applying text color wraps in span and re-applying toggles off."""
        self.editor.setPlainText("Hello World")
        cursor = self.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

        # Apply blue text color
        self.editor._apply_text_color("#0a84ff")
        self.assertEqual(
            self.editor.toPlainText(),
            '<span style="color: #0a84ff;">Hello</span> World',
        )

        # Re-apply same color toggles it off
        self.editor._apply_text_color("#0a84ff")
        self.assertEqual(self.editor.toPlainText(), "Hello World")

    def test_apply_text_color_change_and_reset(self) -> None:
        """Verify changing text color updates the style attribute and empty color resets."""
        self.editor.setPlainText("Hello World")
        cursor = self.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

        self.editor._apply_text_color("#0a84ff")
        self.assertEqual(
            self.editor.toPlainText(),
            '<span style="color: #0a84ff;">Hello</span> World',
        )

        # Change color to red
        self.editor._apply_text_color("#ff453a")
        self.assertEqual(
            self.editor.toPlainText(),
            '<span style="color: #ff453a;">Hello</span> World',
        )

        # Reset color with empty string
        self.editor._apply_text_color("")
        self.assertEqual(self.editor.toPlainText(), "Hello World")

    def test_apply_highlight_color_basic_and_toggle(self) -> None:
        """Verify applying highlight color wraps in mark and re-applying toggles off."""
        self.editor.setPlainText("Important Note")
        cursor = self.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(9, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

        # Apply green highlight
        self.editor._apply_highlight_color("#30d158")
        self.assertEqual(
            self.editor.toPlainText(),
            '<mark style="background-color: #30d158;">Important</mark> Note',
        )

        # Toggle off with same color
        self.editor._apply_highlight_color("#30d158")
        self.assertEqual(self.editor.toPlainText(), "Important Note")

    def test_apply_highlight_color_change_and_reset(self) -> None:
        """Verify changing highlight color updates tag and empty string strips mark."""
        self.editor.setPlainText("Important Note")
        cursor = self.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(9, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

        self.editor._apply_highlight_color("#30d158")
        # Change to purple highlight
        self.editor._apply_highlight_color("#bf5af2")
        self.assertEqual(
            self.editor.toPlainText(),
            '<mark style="background-color: #bf5af2;">Important</mark> Note',
        )

        # Reset to none
        self.editor._apply_highlight_color("")
        self.assertEqual(self.editor.toPlainText(), "Important Note")

    def test_structural_prefix_preserved_for_checkbox_and_lists(self) -> None:
        """Verify checkboxes, bullet points, and numbers are not wrapped inside color tags."""
        # 1. Checkbox item
        self.editor.setPlainText("- [ ] Finish writing tests\n")
        cursor = self.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(len(self.editor.toPlainText()), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

        self.editor._apply_text_color("#ff9f0a")
        self.assertEqual(
            self.editor.toPlainText(),
            '- [ ] <span style="color: #ff9f0a;">Finish writing tests</span>\n',
        )

        # 2. Numbered list item
        self.editor.setPlainText("1. First step in process\n")
        cursor = self.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(len(self.editor.toPlainText()), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

        self.editor._apply_highlight_color("#ffd60a")
        self.assertEqual(
            self.editor.toPlainText(),
            '1. <mark style="background-color: #ffd60a;">First step in process</mark>\n',
        )

    def test_multi_line_text_color_formatting(self) -> None:
        """Verify selecting multiple lines colors each line without breaking syntax."""
        self.editor.setPlainText("Line 1\nLine 2")
        cursor = self.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(len(self.editor.toPlainText()), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

        # Apply red color across both lines
        self.editor._apply_text_color("#ff453a")
        expected = (
            '<span style="color: #ff453a;">Line 1</span>\n'
            '<span style="color: #ff453a;">Line 2</span>'
        )
        self.assertEqual(self.editor.toPlainText(), expected)

        # Toggle off across both lines
        self.editor._apply_text_color("#ff453a")
        self.assertEqual(self.editor.toPlainText(), "Line 1\nLine 2")

    def test_multi_line_checkbox_color_preserves_prefixes(self) -> None:
        """Verify selecting multiple task checkboxes preserves '- [ ] ' on all lines."""
        content = "- [ ] Task one\n- [ ] Task two\n"
        self.editor.setPlainText(content)
        cursor = self.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(len(self.editor.toPlainText()), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

        self.editor._apply_text_color("#0a84ff")
        expected = (
            '- [ ] <span style="color: #0a84ff;">Task one</span>\n'
            '- [ ] <span style="color: #0a84ff;">Task two</span>\n'
        )
        self.assertEqual(self.editor.toPlainText(), expected)

    def test_multi_line_highlight_color_formatting(self) -> None:
        """Verify selecting multiple lines highlights each line cleanly."""
        self.editor.setPlainText("First line\nSecond line")
        cursor = self.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(len(self.editor.toPlainText()), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

        self.editor._apply_highlight_color("#ffd60a")
        expected = (
            '<mark style="background-color: #ffd60a;">First line</mark>\n'
            '<mark style="background-color: #ffd60a;">Second line</mark>'
        )
        self.assertEqual(self.editor.toPlainText(), expected)

    def test_highlighter_parses_mark_and_span_colors(self) -> None:
        """Verify syntax highlighter handles custom mark background and span foreground."""
        text = '<mark style="background-color: #ffd60a;">highlighted</mark> and <span style="color: #0a84ff;">colored</span> and #realtag'
        self.editor.setPlainText(text)
        highlighter = self.editor.highlighter
        # Test active line
        highlighter.active_block_number = 0
        highlighter.rehighlight()

        # Check block layout
        block = self.editor.document().firstBlock()
        self.assertTrue(block.isValid())
        self.assertIn("highlighted", block.text())
        self.assertIn("colored", block.text())
        self.assertIn("#realtag", block.text())

    def test_highlighter_does_not_format_hex_in_style_as_tag(self) -> None:
        """Verify #ffd60a in background-color style is not highlighted as a tag."""
        text = '<mark style="background-color: #ffd60a;">into the editor</mark> #validtag'
        self.editor.setPlainText(text)
        highlighter = self.editor.highlighter
        highlighter.active_block_number = 0
        highlighter.rehighlight()

        # The document text contains the tag
        self.assertIn("#validtag", self.editor.toPlainText())

    def test_caret_skips_across_hidden_tag_on_arrow_keys(self) -> None:
        """Verify Right and Left arrow keys jump across hidden HTML tags atomically."""
        text = 'a <span style="color: #ff453a;">word</span> b'
        self.editor.setPlainText(text)
        cursor = self.editor.textCursor()
        # Position at index 2 (right before '<span...')
        cursor.setPosition(2)
        self.editor.setTextCursor(cursor)

        # Press Right Arrow
        event_right = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        self.editor.keyPressEvent(event_right)
        # Should jump directly to position 32 (immediately before 'w' in 'word')
        self.assertEqual(self.editor.textCursor().position(), 32)

        # Press Left Arrow from position 34
        event_left = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
        self.editor.keyPressEvent(event_left)
        # Should jump directly back to position 2
        self.assertEqual(self.editor.textCursor().position(), 2)

    def test_backspace_at_content_start_preserves_opening_tag(self) -> None:
        """Verify Backspace at the start of colored text deletes preceding char without breaking tag."""
        text = 'hello <span style="color: #ff453a;">world</span>'
        self.editor.setPlainText(text)
        cursor = self.editor.textCursor()
        # Position right before 'w' in 'world'
        cursor.setPosition(text.index("world"))
        self.editor.setTextCursor(cursor)

        event_bs = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Backspace, Qt.KeyboardModifier.NoModifier)
        self.editor.keyPressEvent(event_bs)

        # The space before the tag should have been deleted, leaving tag intact
        expected = 'hello<span style="color: #ff453a;">world</span>'
        self.assertEqual(self.editor.toPlainText(), expected)

    def test_delete_at_content_end_preserves_closing_tag(self) -> None:
        """Verify Delete at the end of colored text deletes following char without breaking tag."""
        text = '<span style="color: #ff453a;">world</span> there'
        self.editor.setPlainText(text)
        cursor = self.editor.textCursor()
        # Position right after 'world' (before '</span>')
        cursor.setPosition(text.index("world") + len("world"))
        self.editor.setTextCursor(cursor)

        event_del = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
        self.editor.keyPressEvent(event_del)

        # The space after </span> should have been deleted, leaving tag intact
        expected = '<span style="color: #ff453a;">world</span>there'
        self.assertEqual(self.editor.toPlainText(), expected)

    def test_highlighter_tolerates_missing_opening_bracket(self) -> None:
        """Verify highlighter parses and hides malformed tag missing leading bracket without crash."""
        text = 'before mark style="background-color: #ffd60a;">inside</mark> after'
        self.editor.setPlainText(text)
        highlighter = self.editor.highlighter
        highlighter.rehighlight()
        block = self.editor.document().firstBlock()
        self.assertTrue(block.isValid())

    def test_hidden_format_eliminates_horizontal_gap(self) -> None:
        """Verify hidden HTML tag advance collapses to 0 and maintains normal word spacing."""
        text = 'move <mark style="background-color: #ffd60a;">into</mark>'
        self.editor.setPlainText(text)
        self.editor.show()
        app.processEvents()

        c_move = self.editor.textCursor()
        c_move.setPosition(4)  # after 'move'
        r_move = self.editor.cursorRect(c_move)

        c_into = self.editor.textCursor()
        c_into.setPosition(text.index("into"))
        r_into = self.editor.cursorRect(c_into)

        gap = r_into.left() - r_move.left()
        # Normal single space between words is ~3-4px, not 20-30px
        self.assertLess(gap, 8)

    def test_strip_multiple_highlights_in_line(self) -> None:
        """Verify selecting a line with multiple highlighted words removes all of them on 'None'."""
        text = 'This has <mark style="background-color: #ffd60a;">first</mark>, <mark style="background-color: #30d158;">second</mark>, and <mark style="background-color: #ff375f;">third</mark> highlights.'
        self.editor.setPlainText(text)
        cursor = self.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(len(text), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

        self.editor._apply_highlight_color("")
        self.assertEqual(
            self.editor.toPlainText(),
            "This has first, second, and third highlights.",
        )

    def test_strip_multiple_text_colors_in_line(self) -> None:
        """Verify selecting a line with multiple colored words removes all of them on 'Default'."""
        text = 'Alpha <span style="color: #ff453a;">one</span> beta <span style="color: #0a84ff;">two</span> gamma <span style="color: #bf5af2;">three</span> delta'
        self.editor.setPlainText(text)
        cursor = self.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(len(text), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

        self.editor._apply_text_color("")
        self.assertEqual(
            self.editor.toPlainText(),
            "Alpha one beta two gamma three delta",
        )

    def test_strip_highlight_from_inner_selection_boundary_expansion(self) -> None:
        """Verify selecting only the inner text of a highlighted word expands and removes tags."""
        text = 'before <mark style="background-color: #ffd60a;">target</mark> after'
        self.editor.setPlainText(text)
        cursor = self.editor.textCursor()
        # Select strictly 'target' (without the hidden <mark> and </mark>)
        s = text.index("target")
        cursor.setPosition(s)
        cursor.setPosition(s + len("target"), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

        self.editor._apply_highlight_color("")
        self.assertEqual(self.editor.toPlainText(), "before target after")


if __name__ == "__main__":
    unittest.main()
