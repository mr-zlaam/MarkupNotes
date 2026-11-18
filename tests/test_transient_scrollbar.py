"""Unit tests for transient auto-hiding vertical scrollbar."""

import unittest

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QTextEdit

from ui.editor import MarkdownEditor
from utils.transient_scrollbar import TransientScrollBarController


class TestTransientScrollBar(unittest.TestCase):
    """Test transient scrollbar appearance and resting fade behavior."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_initial_resting_state(self) -> None:
        editor = QTextEdit()
        editor.setPlainText("\n".join(f"Line {i}" for i in range(100)))
        editor.resize(400, 300)
        editor.show()

        vsb = editor.verticalScrollBar()
        ctrl = TransientScrollBarController(vsb, parent=editor, show_duration_ms=100, fade_duration_ms=50)

        self.assertEqual(ctrl.opacity, 0.0)
        self.assertTrue(vsb.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        editor.close()
        editor.deleteLater()

    def test_scroll_shows_scrollbar(self) -> None:
        editor = QTextEdit()
        editor.setPlainText("\n".join(f"Line {i}" for i in range(100)))
        editor.resize(400, 300)
        editor.show()

        vsb = editor.verticalScrollBar()
        ctrl = TransientScrollBarController(vsb, parent=editor, show_duration_ms=100, fade_duration_ms=50)

        # Trigger scroll
        vsb.setValue(20)
        self.assertEqual(ctrl.opacity, 1.0)
        self.assertFalse(vsb.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertTrue(ctrl._hide_timer.isActive())

        editor.close()
        editor.deleteLater()

    def test_resting_fades_out(self) -> None:
        editor = QTextEdit()
        editor.setPlainText("\n".join(f"Line {i}" for i in range(100)))
        editor.resize(400, 300)
        editor.show()

        vsb = editor.verticalScrollBar()
        ctrl = TransientScrollBarController(vsb, parent=editor, show_duration_ms=50, fade_duration_ms=50)

        ctrl.show_transient()
        self.assertEqual(ctrl.opacity, 1.0)

        # Trigger rest timeout directly
        ctrl._start_fade_out()
        ctrl._fade_anim.setCurrentTime(50)
        ctrl._on_fade_finished()

        self.assertLessEqual(ctrl.opacity, 0.05)
        self.assertTrue(vsb.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

        editor.close()
        editor.deleteLater()

    def test_short_document_does_not_show(self) -> None:
        editor = QTextEdit()
        editor.setPlainText("Short line 1\nShort line 2")
        editor.resize(400, 300)
        editor.show()

        vsb = editor.verticalScrollBar()
        ctrl = TransientScrollBarController(vsb, parent=editor)

        # Should not show when maximum is 0
        ctrl.show_transient()
        self.assertEqual(ctrl.opacity, 0.0)

        editor.close()
        editor.deleteLater()

    def test_editor_integration(self) -> None:
        editor = MarkdownEditor()
        editor.resize(600, 400)
        editor.show()

        self.assertTrue(hasattr(editor, "_transient_scrollbar"))
        self.assertEqual(editor._transient_scrollbar.opacity, 0.0)

        editor.setPlainText("\n".join(f"Paragraph {i} content..." for i in range(150)))
        editor.verticalScrollBar().setValue(30)

        self.assertEqual(editor._transient_scrollbar.opacity, 1.0)

        editor.close()
        editor.deleteLater()


if __name__ == "__main__":
    unittest.main()
