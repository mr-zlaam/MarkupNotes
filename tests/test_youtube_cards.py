"""Tests for YouTube video detection, metadata caching, vector rendering, and editor integration."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap, QTextDocument
from PyQt6.QtWidgets import QApplication

from ui.editor import MarkdownEditor
from ui.slash_menu import COMMANDS
from utils.video_engine import (
    VideoRegion,
    extract_youtube_id,
    find_video_regions,
    get_video_card_dimensions,
    is_standalone_video_line,
    render_video_card,
)


class TestYouTubeDetection(unittest.TestCase):
    """Test YouTube URL and iframe regex detection and ID extraction."""

    def test_extract_youtube_id_standard(self) -> None:
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        self.assertEqual(extract_youtube_id(url), "dQw4w9WgXcQ")

    def test_extract_youtube_id_short(self) -> None:
        url = "https://youtu.be/dQw4w9WgXcQ"
        self.assertEqual(extract_youtube_id(url), "dQw4w9WgXcQ")

    def test_extract_youtube_id_embed(self) -> None:
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        self.assertEqual(extract_youtube_id(url), "dQw4w9WgXcQ")

    def test_extract_youtube_id_nocookie(self) -> None:
        url = "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"
        self.assertEqual(extract_youtube_id(url), "dQw4w9WgXcQ")

    def test_extract_youtube_id_shorts(self) -> None:
        url = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        self.assertEqual(extract_youtube_id(url), "dQw4w9WgXcQ")

    def test_extract_youtube_id_with_params(self) -> None:
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&feature=shared"
        self.assertEqual(extract_youtube_id(url), "dQw4w9WgXcQ")

    def test_extract_youtube_id_iframe(self) -> None:
        iframe = '<iframe width="560" height="315" src="https://www.youtube.com/embed/dQw4w9WgXcQ" frameborder="0" allowfullscreen></iframe>'
        self.assertEqual(extract_youtube_id(iframe), "dQw4w9WgXcQ")

    def test_extract_youtube_id_invalid(self) -> None:
        self.assertIsNone(extract_youtube_id("https://vimeo.com/123456"))
        self.assertIsNone(extract_youtube_id("just some random text"))

    def test_is_standalone_video_line(self) -> None:
        self.assertTrue(is_standalone_video_line("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertTrue(is_standalone_video_line("https://youtu.be/dQw4w9WgXcQ"))
        self.assertTrue(is_standalone_video_line("[Favorite Song](https://youtu.be/dQw4w9WgXcQ)"))
        self.assertTrue(is_standalone_video_line('<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'))
        # Inline video link within a larger sentence should NOT be standalone
        self.assertFalse(is_standalone_video_line("Check this out: https://youtu.be/dQw4w9WgXcQ is awesome!"))


class TestYouTubeEngine(unittest.TestCase):
    """Test find_video_regions, card dimensions, and vector rendering."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_find_video_regions_urls_and_iframes(self) -> None:
        doc = QTextDocument()
        text = (
            "# My Notes\n"
            "\n"
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
            "\n"
            "Some text in between.\n"
            "\n"
            '<iframe width="560" height="315"\n'
            ' src="https://www.youtube.com/embed/9bZkp7q19f0"\n'
            ' title="YouTube video player" frameborder="0">\n'
            "</iframe>\n"
            "\n"
            "Done."
        )
        doc.setPlainText(text)
        regions = find_video_regions(doc)
        self.assertEqual(len(regions), 2)

        # Region 0: single-line URL
        self.assertEqual(regions[0].start_block, 2)
        self.assertEqual(regions[0].end_block, 2)
        self.assertEqual(regions[0].video_id, "dQw4w9WgXcQ")
        self.assertEqual(regions[0].url, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        # Region 1: multiline iframe
        self.assertEqual(regions[1].start_block, 6)
        self.assertEqual(regions[1].end_block, 9)
        self.assertEqual(regions[1].video_id, "9bZkp7q19f0")

    def test_find_video_regions_excluded_blocks(self) -> None:
        doc = QTextDocument()
        text = "```html\n<iframe src=\"https://www.youtube.com/embed/dQw4w9WgXcQ\"></iframe>\n```"
        doc.setPlainText(text)
        excluded = {0, 1, 2}
        regions = find_video_regions(doc, excluded_blocks=excluded)
        self.assertEqual(len(regions), 0)

    def test_get_video_card_dimensions(self) -> None:
        w, h = get_video_card_dimensions(available_w=600.0, ui_scale=1.0)
        self.assertEqual(w, 480.0)
        self.assertEqual(h, 270.0 + 46.0)

        # Narrow screen
        w_narrow, h_narrow = get_video_card_dimensions(available_w=320.0, ui_scale=1.0)
        self.assertEqual(w_narrow, 320.0)
        self.assertEqual(h_narrow, round((320.0 * 9.0) / 16.0) + 46.0)

    def test_render_video_card_paint(self) -> None:
        pix = QPixmap(500, 350)
        pix.fill(QColor("#16161a"))
        painter = QPainter(pix)
        rect = QRectF(10.0, 10.0, 480.0, 316.0)

        # Render placeholder state (no thumbnail)
        render_video_card(
            painter,
            rect,
            video_id="dQw4w9WgXcQ",
            pixmap=None,
            title="Never Gonna Give You Up",
            author="Rick Astley",
            is_hovered=False,
            is_play_hovered=False,
        )
        painter.end()
        self.assertFalse(pix.isNull())

        # Render loaded thumbnail state
        thumb_pix = QPixmap(120, 90)
        thumb_pix.fill(QColor("#ff0000"))
        painter2 = QPainter(pix)
        render_video_card(
            painter2,
            rect,
            video_id="dQw4w9WgXcQ",
            pixmap=thumb_pix,
            title="Never Gonna Give You Up",
            author="Rick Astley",
            is_hovered=True,
            is_play_hovered=True,
        )
        painter2.end()
        self.assertFalse(pix.isNull())


class TestYouTubeEditorIntegration(unittest.TestCase):
    """Test editor interactions, line height calibration, and click handling for YouTube cards."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.editor = MarkdownEditor()
        self.editor.resize(800, 600)

    def tearDown(self) -> None:
        self.editor.deleteLater()

    def test_editor_video_region_detection(self) -> None:
        content = (
            "# Video Test\n"
            "\n"
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
            "\n"
            "Below the video.\n"
        )
        self.editor.setPlainText(content)
        self.editor._update_block_margins()

        regions = self.editor.highlighter.video_regions
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].video_id, "dQw4w9WgXcQ")

        # Inactive block formatting should have fixed height
        b = self.editor.document().findBlockByNumber(2)
        bf = b.blockFormat()
        self.assertEqual(bf.lineHeightType(), 2)  # FixedHeight
        self.assertTrue(bf.nonBreakableLines())

    def test_editor_multiline_iframe_calibration(self) -> None:
        content = (
            "Start\n"
            '<iframe width="560" height="315"\n'
            ' src="https://www.youtube.com/embed/dQw4w9WgXcQ"\n'
            " allowfullscreen>\n"
            "</iframe>\n"
            "End"
        )
        self.editor.setPlainText(content)
        self.editor._update_block_margins()

        regions = self.editor.highlighter.video_regions
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].start_block, 1)
        self.assertEqual(regions[0].end_block, 4)

        for bn in range(1, 5):
            b = self.editor.document().findBlockByNumber(bn)
            bf = b.blockFormat()
            self.assertEqual(bf.lineHeightType(), 2)  # FixedHeight
            self.assertTrue(bf.nonBreakableLines())

    def test_editor_video_click_opens_url(self) -> None:
        content = "https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
        self.editor.setPlainText(content)
        self.editor._update_block_margins()

        # Simulate card rect populated during paint
        vr = self.editor.highlighter.video_regions[0]
        test_rect = QRectF(36.0, 10.0, 480.0, 316.0)
        self.editor._video_card_rects[0] = (test_rect, vr)

        with patch.object(self.editor, "_open_url") as mock_open:
            click_event = MagicMock()
            click_event.button.return_value = Qt.MouseButton.LeftButton
            click_event.modifiers.return_value = Qt.KeyboardModifier.NoModifier
            click_event.position.return_value = QPointF(100.0, 100.0)

            self.editor.mousePressEvent(click_event)
            mock_open.assert_called_once_with("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_slash_menu_contains_video_command(self) -> None:
        video_cmds = [cmd for cmd in COMMANDS if cmd.id == "video"]
        self.assertEqual(len(video_cmds), 1)
        self.assertIn("youtube", video_cmds[0].keywords)


if __name__ == "__main__":
    unittest.main()
