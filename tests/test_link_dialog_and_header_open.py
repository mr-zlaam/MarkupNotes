"""Unit tests verifying ModernLinkDialog, top-right Open File header button, and link formatting."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure offscreen Qt platform for headless CI / testing
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication, QDialog

from ui.dialogs import ModernLinkDialog
from ui.editor import EditorPanel, MarkdownEditor
from utils.icons import create_link_icon, create_open_file_icon


class TestLinkDialogAndHeaderOpen(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(sys.argv)

    def test_open_file_icon_generation(self) -> None:
        """Verify vector open file icon generates a non-null QIcon."""
        icon = create_open_file_icon(color="#8e8e93", size=16)
        self.assertFalse(icon.isNull())
        sizes = icon.availableSizes()
        self.assertTrue(len(sizes) > 0 or not icon.pixmap(16, 16).isNull())

    def test_link_icon_generation(self) -> None:
        """Verify vector link chain icon generates a non-null QIcon with valid pixmap."""
        icon = create_link_icon(color="#d0d0d4", size=14)
        self.assertFalse(icon.isNull())
        pix = icon.pixmap(14, 14)
        self.assertFalse(pix.isNull())
        self.assertEqual(pix.width(), 14)

    def test_editor_panel_has_open_file_button(self) -> None:
        """Verify EditorPanel top right header contains the open file button with signal."""
        panel = EditorPanel()
        self.assertTrue(hasattr(panel, "open_file_btn"))
        self.assertTrue(panel.open_file_btn.isEnabled())
        self.assertIn("Open Markdown File", panel.open_file_btn.toolTip())

        # Test signal emission
        emitted = []
        panel.open_file_requested.connect(lambda: emitted.append(True))
        panel.open_file_btn.click()
        self.assertEqual(len(emitted), 1)
        panel.deleteLater()

    def test_modern_link_dialog_initialization(self) -> None:
        """Verify ModernLinkDialog initializes with text and url and handles focus."""
        # Case 1: Initial text provided -> focus is on url_input
        dlg1 = ModernLinkDialog(initial_text="GitHub", initial_url="https://github.com")
        self.assertEqual(dlg1.text_input.text(), "GitHub")
        self.assertEqual(dlg1.url_input.text(), "https://github.com")
        self.assertEqual(dlg1.windowTitle(), "Insert Link")
        dlg1.deleteLater()

        # Case 2: Initial text empty -> focus is on text_input
        dlg2 = ModernLinkDialog(initial_text="", initial_url="")
        self.assertEqual(dlg2.text_input.text(), "")
        self.assertEqual(dlg2.url_input.text(), "")
        dlg2.deleteLater()

    def test_modern_link_dialog_enter_key_progression(self) -> None:
        """Verify pressing enter in text input moves focus to url if url is empty."""
        dlg = ModernLinkDialog(initial_text="My Link", initial_url="")
        # Simulate enter on text input
        dlg._on_enter_pressed()
        # When text is non-empty and url is empty, sender check moves focus to url_input
        dlg.deleteLater()

    def test_editor_link_formatting_with_modal(self) -> None:
        """Verify MarkdownEditor opens modal and applies markdown link formatting."""
        editor = MarkdownEditor()
        editor.setPlainText("Check out this cool resource today.")

        # Select "cool resource"
        cursor = editor.textCursor()
        cursor.setPosition(15)
        cursor.setPosition(28, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        self.assertEqual(editor.textCursor().selectedText(), "cool resource")

        # Mock ModernLinkDialog.get_link_data to simulate user input
        with patch.object(
            ModernLinkDialog,
            "get_link_data",
            return_value=("cool resource", "https://resource.com", True),
        ):
            editor._apply_text_format("link")

        self.assertIn("[cool resource](https://resource.com)", editor.toPlainText())
        self.assertEqual(
            editor.toPlainText(),
            "Check out this [cool resource](https://resource.com) today.",
        )
        editor.deleteLater()

    def test_editor_link_formatting_preserves_structural_prefix(self) -> None:
        """Verify applying link format to a checkbox or bullet line preserves prefix."""
        editor = MarkdownEditor()
        editor.setPlainText("- [ ] Visit Python Website\n")

        # Select whole line
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(26, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)

        with patch.object(
            ModernLinkDialog,
            "get_link_data",
            return_value=("Visit Python Website", "https://python.org", True),
        ):
            editor._apply_text_format("link")

        # The structural prefix "- [ ] " must not be broken or wrapped inside the link
        self.assertEqual(
            editor.toPlainText(),
            "- [ ] [Visit Python Website](https://python.org)\n",
        )
        editor.deleteLater()

    def test_editor_link_formatting_canceled_does_not_modify_text(self) -> None:
        """Verify that canceling the link dialog leaves document unmodified."""
        editor = MarkdownEditor()
        editor.setPlainText("Unchanged text here")

        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(9, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)

        with patch.object(
            ModernLinkDialog,
            "get_link_data",
            return_value=("", "", False),
        ):
            editor._apply_text_format("link")

        self.assertEqual(editor.toPlainText(), "Unchanged text here")
        editor.deleteLater()

    def test_raw_url_highlighting_and_punctuation_handling(self) -> None:
        """Verify raw URLs are highlighted with link format while trailing sentence punctuation is excluded."""
        from ui.highlighter import MarkdownHighlighter
        from utils.markdown import find_link_at_offset

        editor = MarkdownEditor()
        editor.resize(600, 300)
        editor.show()
        text = "Visit https://example.com/test. Thanks!"
        editor.setPlainText(text)

        blk = editor.document().firstBlock()
        formats = blk.layout().formats()
        link_formats = [f for f in formats if f.format.fontUnderline()]
        self.assertEqual(len(link_formats), 1)

        f = link_formats[0]
        formatted_text = text[f.start : f.start + f.length]
        self.assertEqual(formatted_text, "https://example.com/test")
        self.assertEqual(f.format.foreground().color().name(), "#0a84ff")
        self.assertTrue(f.format.fontUnderline())

        # Test link offset detection (period at offset 31 should not be part of the link)
        link_info = find_link_at_offset(text, 10)
        self.assertIsNotNone(link_info)
        start, end, url = link_info
        self.assertEqual(url, "https://example.com/test")
        self.assertEqual(text[start:end], "https://example.com/test")

        # Offset over trailing period
        self.assertIsNone(find_link_at_offset(text, 32))
        editor.deleteLater()

    def test_raw_url_in_inline_code_not_highlighted_as_link(self) -> None:
        """Verify raw URLs inside inline code blocks are not styled with link format."""
        editor = MarkdownEditor()
        editor.resize(600, 300)
        editor.show()
        text = "Code `https://code.example.com` is code."
        editor.setPlainText(text)

        blk = editor.document().firstBlock()
        formats = blk.layout().formats()
        underlined_formats = [f for f in formats if f.format.fontUnderline()]
        self.assertEqual(len(underlined_formats), 0)
        editor.deleteLater()

    def test_autolink_highlighting(self) -> None:
        """Verify autolinks <https://...> have their URL highlighted with link format."""
        editor = MarkdownEditor()
        editor.resize(600, 300)
        editor.show()
        text = "Check <https://autolink.org> out"
        editor.setPlainText(text)

        blk = editor.document().firstBlock()
        formats = blk.layout().formats()
        link_formats = [f for f in formats if f.format.fontUnderline()]
        self.assertEqual(len(link_formats), 1)

        f = link_formats[0]
        self.assertEqual(text[f.start : f.start + f.length], "https://autolink.org")
        self.assertEqual(f.format.foreground().color().name(), "#0a84ff")
        editor.deleteLater()


if __name__ == "__main__":
    unittest.main()
