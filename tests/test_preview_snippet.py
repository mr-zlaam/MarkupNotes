"""Unit tests for HTML and Markdown stripping in note list preview snippets."""

from __future__ import annotations

import unittest

from core.note import Note
from utils.note_io import clean_markdown_preview_line


class TestPreviewSnippetSanitization(unittest.TestCase):
    """Verify note card preview snippets strip HTML tags and Markdown syntax cleanly."""

    def test_html_tags_stripped_from_preview(self) -> None:
        """Verify inline span, mark, u, kbd, and mixed HTML tags are removed cleanly."""
        md = (
            '- [ ] <span style="color: #ff453a;">Make sure to remember where user was</span>\n'
            '> <mark style="background: #fff3b0;">Highlighted</mark> and <u>underlined</u> '
            'with <kbd>Ctrl+B</kbd> &amp; more'
        )
        _, snippet = Note.parse_title_and_snippet(md, fallback_title="Improvements")
        self.assertEqual(
            snippet,
            "Make sure to remember where user was Highlighted and underlined with Ctrl+B & more",
        )

    def test_markdown_links_images_formatting_and_delimiters_stripped(self) -> None:
        """Verify links, images, emphasis, code/math fences, HRs, and tables sanitize cleanly."""
        md = (
            "# Sprint Plan\n"
            "---\n"
            "```python\n"
            "![diagram](assets/diagram.png)\n"
            "## [**Roadmap** *Details*](https://example.com) and _italic_ ==focus== ~~old~~\n"
            "| Task A | `markup_notes` |\n"
        )
        _, snippet = Note.parse_title_and_snippet(md, fallback_title="Sprint Plan")
        self.assertEqual(
            snippet,
            "diagram Roadmap Details and italic focus old",
        )

    def test_snake_case_identifiers_and_empty_structural_notes(self) -> None:
        """Verify snake_case underscores stay intact and delimiter-only notes fall back cleanly."""
        self.assertEqual(clean_markdown_preview_line("check markup_notes_config file"), "check markup_notes_config file")
        self.assertEqual(clean_markdown_preview_line("<https://example.com>"), "https://example.com")
        self.assertEqual(clean_markdown_preview_line("|---|---|"), "")
        self.assertEqual(clean_markdown_preview_line("$$"), "")

        _, fallback = Note.parse_title_and_snippet("---\n```\n<br/>\n", fallback_title="Empty")
        self.assertEqual(fallback, "No additional text")
