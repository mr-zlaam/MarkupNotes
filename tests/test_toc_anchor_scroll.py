"""Unit tests for Table of Contents (#anchor) click-to-scroll navigation in MarkdownEditor."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QTextCursor, QTextDocument
from PyQt6.QtWidgets import QApplication

from ui.editor import MarkdownEditor
from utils.markdown import find_anchor_block_number, slugify_heading

app = QApplication.instance() or QApplication([])


class TestTocAnchorScroll(unittest.TestCase):
    """Verify heading slug matching, HTML anchors, and clicking TOC links to scroll to content."""

    def test_slugify_heading_and_duplicate_anchors_skip_code_blocks(self) -> None:
        """Verify GitHub-style slugification, duplicate suffixes, HTML ids, and code-block exclusion."""
        self.assertEqual(slugify_heading("Chapter 1: Getting Started!"), "chapter-1-getting-started")
        self.assertEqual(slugify_heading("**Bold** & `Code`"), "bold-code")

        doc = QTextDocument()
        doc.setPlainText(
            "# Table of Contents\n"
            "```markdown\n"
            "# Fake Heading Inside Code\n"
            "```\n"
            "## Overview\n"
            "Some text\n"
            "## Overview\n"
            '<a id="custom-epub-anchor"></a>\n'
            "## Final Section\n"
        )

        self.assertIsNone(find_anchor_block_number(doc, "#fake-heading-inside-code"))
        self.assertEqual(find_anchor_block_number(doc, "#overview"), 4)
        self.assertEqual(find_anchor_block_number(doc, "#overview-1"), 6)
        self.assertEqual(find_anchor_block_number(doc, "#custom-epub-anchor"), 7)
        self.assertEqual(find_anchor_block_number(doc, "#final-section"), 8)

    def test_clicking_toc_link_scrolls_editor_to_target_heading(self) -> None:
        """Clicking an inactive TOC '#anchor' link scrolls directly to the heading without opening browser."""
        filler = "\n".join(f"Paragraph line {i}" for i in range(60))
        markdown = (
            "# Contents\n"
            "- [Chapter 1](#chapter-1)\n"
            "- [Chapter 2](#chapter-2)\n\n"
            "## Chapter 1\n"
            f"{filler}\n\n"
            "## Chapter 2\n"
            "Welcome to Chapter 2!\n"
        )

        editor = MarkdownEditor()
        editor.resize(640, 360)
        editor.setPlainText(markdown)
        editor.show()
        app.processEvents()

        # Cursor is on line 0 ('# Contents'), so line 2 ('- [Chapter 2](#chapter-2)') is inactive
        self.assertEqual(editor.textCursor().blockNumber(), 0)
        self.assertEqual(editor.verticalScrollBar().value(), 0)

        # Find viewport position of 'Chapter 2' inside the TOC link on block 2
        toc_block = editor.document().findBlockByNumber(2)
        link_offset = toc_block.text().index("Chapter 2") + 2
        c = QTextCursor(toc_block)
        c.setPosition(toc_block.position() + link_offset)
        click_rect = editor.cursorRect(c)
        click_pos = QPointF(float(click_rect.center().x()), float(click_rect.center().y()))

        with patch("ui.editor.QDesktopServices.openUrl") as mock_open:
            press = QMouseEvent(
                QEvent.Type.MouseButtonPress,
                click_pos,
                click_pos,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            editor.mousePressEvent(press)
            app.processEvents()

            mock_open.assert_not_called()

        # Cursor jumped to '## Chapter 2' and viewport scrolled down
        self.assertEqual(editor.textCursor().block().text(), "## Chapter 2")
        self.assertGreater(editor.verticalScrollBar().value(), 0)

        editor.deleteLater()

    def test_ctrl_click_toc_link_scrolls_even_on_active_line(self) -> None:
        """Ctrl+Click on a '#anchor' link scrolls to the heading even when the TOC line is active."""
        filler = "\n".join(f"Line {i}" for i in range(45))
        markdown = f"- [Jump Here](#target-section)\n\n{filler}\n\n## Target Section\nBody\n"

        editor = MarkdownEditor()
        editor.resize(640, 320)
        editor.setPlainText(markdown)
        editor.show()
        app.processEvents()

        with patch("ui.editor.QDesktopServices.openUrl") as mock_open:
            editor._open_url("#target-section")
            app.processEvents()
            mock_open.assert_not_called()

        self.assertEqual(editor.textCursor().block().text(), "## Target Section")
        self.assertGreater(editor.verticalScrollBar().value(), 0)
        editor.deleteLater()

    def test_epub_relative_html_toc_link_scrolls_to_matching_chapter_heading(self) -> None:
        """Clicking EPUB-style '[Chapter 90: It’s just a little wind frost](page-89.html)' scrolls to the chapter."""
        filler = "\n".join(f"Story line {i}" for i in range(55))
        markdown = (
            "# Table of Contents\n"
            "*   [Chapter 90: It’s just a little wind frost](page-89.html)\n\n"
            f"{filler}\n\n"
            "## Chapter 90: It's just a little wind frost\n"
            "The cold wind blew across the mountain.\n"
        )

        editor = MarkdownEditor()
        editor.resize(680, 340)
        editor.setPlainText(markdown)
        editor.show()
        app.processEvents()

        # Line 0 is active, so line 1 (EPUB TOC link) is inactive
        toc_block = editor.document().findBlockByNumber(1)
        link_offset = toc_block.text().index("Chapter 90") + 4
        c = QTextCursor(toc_block)
        c.setPosition(toc_block.position() + link_offset)
        click_rect = editor.cursorRect(c)
        click_pos = QPointF(float(click_rect.center().x()), float(click_rect.center().y()))

        with patch("ui.editor.QDesktopServices.openUrl") as mock_open:
            press = QMouseEvent(
                QEvent.Type.MouseButtonPress,
                click_pos,
                click_pos,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            editor.mousePressEvent(press)
            app.processEvents()
            mock_open.assert_not_called()

        self.assertEqual(
            editor.textCursor().block().text(),
            "## Chapter 90: It's just a little wind frost",
        )
        self.assertGreater(editor.verticalScrollBar().value(), 0)
        editor.deleteLater()

    def test_link_hover_hit_test_rejects_empty_space_right_left_and_below(self) -> None:
        """Link hit-testing and pointer cursor must only trigger directly over rendered link text."""
        editor = MarkdownEditor()
        editor.resize(700, 400)
        editor.setPlainText("https://google.com")
        editor.show()
        app.processEvents()

        block = editor.document().findBlockByNumber(0)
        start_cur = QTextCursor(block)
        start_cur.setPosition(0)
        mid_cur = QTextCursor(block)
        mid_cur.setPosition(8)
        end_cur = QTextCursor(block)
        end_cur.setPosition(len("https://google.com"))

        start_rect = editor.cursorRect(start_cur)
        mid_rect = editor.cursorRect(mid_cur)
        end_rect = editor.cursorRect(end_cur)

        # 1. Directly over the link text -> detected + PointingHandCursor
        on_link = QPointF(float(mid_rect.center().x()), float(mid_rect.center().y()))
        self.assertIsNotNone(editor._link_details_at_pos(on_link))
        move_on = QMouseEvent(
            QEvent.Type.MouseMove,
            on_link,
            on_link,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        editor.mouseMoveEvent(move_on)
        self.assertEqual(editor.viewport().cursor().shape(), Qt.CursorShape.PointingHandCursor)

        # 2. Far to the right on the same line -> NOT a link + IBeamCursor
        far_right = QPointF(float(end_rect.right() + 120), float(mid_rect.center().y()))
        self.assertIsNone(editor._link_details_at_pos(far_right))
        move_right = QMouseEvent(
            QEvent.Type.MouseMove,
            far_right,
            far_right,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        editor.mouseMoveEvent(move_right)
        self.assertEqual(editor.viewport().cursor().shape(), Qt.CursorShape.IBeamCursor)

        # 3. Far below the last line (overscroll empty canvas) -> NOT a link
        far_below = QPointF(float(mid_rect.center().x()), float(mid_rect.bottom() + 150))
        self.assertIsNone(editor._link_details_at_pos(far_below))

        # 4. Left padding before link start -> NOT a link
        far_left = QPointF(max(0.0, float(start_rect.left() - 12)), float(mid_rect.center().y()))
        if far_left.x() < start_rect.left():
            self.assertIsNone(editor._link_details_at_pos(far_left))

        editor.deleteLater()


if __name__ == "__main__":
    unittest.main()
