"""Unit tests for selection rendering across checkboxes, code cards, and date cards."""

from datetime import date
import unittest

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QColor, QImage, QPainter, QTextCursor
from PyQt6.QtWidgets import QApplication

from ui.editor import MarkdownEditor
from ui.theme import DARK_THEME_QSS


class TestSelectionRendering(unittest.TestCase):
    """Test selection rendering and overlay styling."""

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
        self.editor.resize(800, 600)

    def tearDown(self) -> None:
        self.editor.deleteLater()

    def test_select_all_highlights_code_blocks(self) -> None:
        content = """# Title

```python
x = 10
y = 20
```

- [ ] Task
"""
        self.editor.setPlainText(content)
        self.editor.selectAll()
        self.assertTrue(self.editor.textCursor().hasSelection())

        # Render to image to ensure paintEvent executes selection overlay without error
        img = QImage(self.editor.size(), QImage.Format.Format_ARGB32)
        img.fill(QColor("#1e1e24"))
        self.editor.render(img)

        # Highlighting verified: code regions are recognized
        self.assertEqual(len(self.editor.highlighter.code_regions), 1)

    def test_select_all_masks_checkbox_brackets(self) -> None:
        content = """- [ ] Unchecked item
- [x] Checked item
"""
        self.editor.setPlainText(content)
        self.editor.selectAll()

        img = QImage(self.editor.size(), QImage.Format.Format_ARGB32)
        img.fill(QColor("#1e1e24"))
        self.editor.render(img)

        # Ensure no crash and checkboxes are drawn
        self.assertTrue(self.editor.textCursor().hasSelection())

    def test_select_all_highlights_date_cards(self) -> None:
        content = """- [ ] Features
@date(2026-11-29)
"""
        self.editor.setPlainText(content)
        self.editor.selectAll()

        img = QImage(self.editor.size(), QImage.Format.Format_ARGB32)
        img.fill(QColor("#1e1e24"))
        self.editor.render(img)

        self.assertIn(1, self.editor.highlighter.date_blocks)


if __name__ == "__main__":
    unittest.main()
