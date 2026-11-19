"""Tests for PDF and HTML note export with styled checkboxes."""

import tempfile
import unittest
from pathlib import Path
from PyQt6.QtWidgets import QApplication

from utils.exporter import (
    _convert_markdown_to_styled_html,
    export_note_to_html,
    export_note_to_pdf,
)

app = QApplication.instance() or QApplication([])


class TestExporter(unittest.TestCase):
    """Test exporting notes to PDF and HTML with styled vector checkboxes."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_convert_markdown_to_styled_html_replaces_ballot_boxes(self) -> None:
        md = (
            "- [ ] Unchecked task\n"
            "- [x] Checked task\n"
            "- Regular bullet point\n"
            "1. Numbered item"
        )
        html = _convert_markdown_to_styled_html("Tasks", md)

        # Must not contain default Qt ballot box glyphs or CSS markers
        self.assertNotIn("\\2610", html)
        self.assertNotIn("\\2612", html)
        self.assertNotIn("☐", html)
        self.assertNotIn("☒", html)

        # Must contain modern SVG data URIs for both unchecked and checked checkboxes
        self.assertIn("data:image/svg+xml;base64,", html)
        self.assertIn('class="task-item unchecked"', html)
        self.assertIn('class="task-item checked"', html)

    def test_export_note_to_pdf_creates_valid_file(self) -> None:
        pdf_path = self.dir_path / "test_tasks.pdf"
        md = (
            "# Sprint Tasks\n\n"
            "- [ ] First unchecked task\n"
            "- [x] Second checked task\n"
            "- [ ] Third task with [link](https://example.com)\n"
        )
        success = export_note_to_pdf("Sprint Tasks", md, pdf_path)
        self.assertTrue(success)
        self.assertTrue(pdf_path.exists())
        self.assertGreater(pdf_path.stat().st_size, 1000)

    def test_export_note_to_html_light_and_dark(self) -> None:
        md = "- [ ] Light task\n- [x] Done task"

        # Light theme HTML
        light_path = self.dir_path / "light.html"
        ok_light = export_note_to_html("Light Note", md, light_path, dark_theme=False)
        self.assertTrue(ok_light)
        light_content = light_path.read_text(encoding="utf-8")
        self.assertNotIn("☐", light_content)
        self.assertNotIn("☒", light_content)
        self.assertIn("data:image/svg+xml;base64,", light_content)
        self.assertIn("task-item unchecked", light_content)
        self.assertIn("task-item checked", light_content)

        # Dark theme HTML
        dark_path = self.dir_path / "dark.html"
        ok_dark = export_note_to_html("Dark Note", md, dark_path, dark_theme=True)
        self.assertTrue(ok_dark)
        dark_content = dark_path.read_text(encoding="utf-8")
        self.assertIn("--bg-color: #1e1e22", dark_content)
        self.assertIn("task-item checked", dark_content)
