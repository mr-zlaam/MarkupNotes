"""Tests for clean plain-text Undo/Redo across markdown syntax, margins, and highlights."""

import sys
import time
import unittest
from pathlib import Path

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent, QTextCursor
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.editor import MarkdownEditor
from utils.undo_manager import PlainTextUndoManager, compute_text_delta


def _pump_events(app: QApplication, ms: int = 80) -> None:
    """Process Qt events and timers for at least `ms` milliseconds."""
    deadline = time.time() + (ms / 1000.0)
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


class TestPlainTextUndoManager(unittest.TestCase):
    """Unit tests for PlainTextUndoManager delta calculation and coalescing."""

    def test_compute_text_delta_variants(self) -> None:
        self.assertEqual(compute_text_delta("abc", "abbc"), (2, "", "b"))
        self.assertEqual(compute_text_delta("hello world", "<mark>hello</mark> world"), (0, "hello", "<mark>hello</mark>"))
        self.assertEqual(compute_text_delta("abcdef", "abef"), (2, "cd", ""))

    def test_typing_coalesces_by_word_and_breaks_on_newline(self) -> None:
        mgr = PlainTextUndoManager("")
        t0 = 100.0
        mgr.record_change("h", 1, 1, now=t0)
        mgr.record_change("hi", 2, 2, now=t0 + 0.05)
        mgr.record_change("hi ", 3, 3, now=t0 + 0.10)
        mgr.record_change("hi t", 4, 4, now=t0 + 0.15)
        mgr.record_change("hi there", 8, 8, atomic=False, now=t0 + 0.20)
        # "hi there" multi-char insert is atomic; let's test char-by-char:
        mgr2 = PlainTextUndoManager("")
        for i, txt in enumerate(["h", "hi", "hi ", "hi m", "hi ma", "hi man"], start=1):
            mgr2.record_change(txt, i, i, now=t0 + i * 0.05)

        self.assertEqual(mgr2.undo_count, 2)
        step1 = mgr2.undo()
        self.assertIsNotNone(step1)
        self.assertEqual(mgr2.current_text, "hi ")
        self.assertEqual((step1[3], step1[4]), (3, 3))

        step2 = mgr2.undo()
        self.assertIsNotNone(step2)
        self.assertEqual(mgr2.current_text, "")
        self.assertEqual((step2[3], step2[4]), (0, 0))


class TestEditorUndoRedo(unittest.TestCase):
    """Integration tests verifying MarkdownEditor undo/redo never gets trapped by margins or tags."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.editor = MarkdownEditor()
        self.editor.resize(700, 500)

    def tearDown(self) -> None:
        self.editor.deleteLater()

    def _type_text(self, text: str) -> None:
        for ch in text:
            ev = QKeyEvent(QEvent.Type.KeyPress, 0, Qt.KeyboardModifier.NoModifier, ch)
            self.editor.keyPressEvent(ev)

    def _press_enter(self) -> None:
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "\n")
        self.editor.keyPressEvent(ev)

    def _press_ctrl_z(self) -> None:
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.editor.keyPressEvent(ev)

    def _press_ctrl_shift_z(self) -> None:
        ev = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Z,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        self.editor.keyPressEvent(ev)

    def _press_ctrl_y(self) -> None:
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        self.editor.keyPressEvent(ev)

    def test_set_plain_text_resets_undo_and_caret_stays_put(self) -> None:
        self.editor.setPlainText("- [ ] existing task\n> blockquote")
        _pump_events(self.app, 80)

        self.assertFalse(self.editor.canUndo())
        self.assertFalse(self.editor.canRedo())

        cur = self.editor.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(cur)
        end_pos = self.editor.textCursor().position()

        self._press_ctrl_z()
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.textCursor().position(), end_pos)
        self.assertEqual(self.editor.toPlainText(), "- [ ] existing task\n> blockquote")

    def test_checkbox_typing_undo_and_redo_with_margin_timer(self) -> None:
        self.editor.setPlainText("")
        _pump_events(self.app, 80)

        self._type_text("Hello world")
        _pump_events(self.app, 80)
        self._press_enter()
        _pump_events(self.app, 80)
        self._type_text("- [ ] task 1")
        _pump_events(self.app, 80)
        self._press_enter()
        _pump_events(self.app, 80)
        self._type_text("task 2")
        _pump_events(self.app, 80)

        self.assertEqual(self.editor.toPlainText(), "Hello world\n- [ ] task 1\n- [ ] task 2")

        # Undo #1: undoes "2" (word boundary) and keeps caret right after "task " (NOT position 0!)
        self._press_ctrl_z()
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.toPlainText(), "Hello world\n- [ ] task 1\n- [ ] task ")
        self.assertEqual(self.editor.textCursor().position(), len("Hello world\n- [ ] task 1\n- [ ] task "))
        self.assertTrue(self.editor.canRedo())

        # Undo #2: undoes "task " and keeps caret right after "- [ ] "
        self._press_ctrl_z()
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.toPlainText(), "Hello world\n- [ ] task 1\n- [ ] ")
        self.assertEqual(self.editor.textCursor().position(), len("Hello world\n- [ ] task 1\n- [ ] "))
        self.assertTrue(self.editor.canRedo())

        # Undo #3: undoes auto-continued "\n- [ ] " and leaves caret after "task 1"
        self._press_ctrl_z()
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.toPlainText(), "Hello world\n- [ ] task 1")
        self.assertEqual(self.editor.textCursor().position(), len("Hello world\n- [ ] task 1"))
        self.assertTrue(self.editor.canRedo())

        # Undo #4: must undo "1", NOT get stuck at position 0!
        self._press_ctrl_z()
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.toPlainText(), "Hello world\n- [ ] task ")
        self.assertGreater(self.editor.textCursor().position(), 0)
        self.assertTrue(self.editor.canRedo())

        # Redo restores step-by-step back to full document
        self._press_ctrl_y()
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.toPlainText(), "Hello world\n- [ ] task 1")

        self._press_ctrl_shift_z()
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.toPlainText(), "Hello world\n- [ ] task 1\n- [ ] ")

        self._press_ctrl_y()
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.toPlainText(), "Hello world\n- [ ] task 1\n- [ ] task ")

        self._press_ctrl_y()
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.toPlainText(), "Hello world\n- [ ] task 1\n- [ ] task 2")

    def test_highlight_background_color_undo_redo(self) -> None:
        self.editor.setPlainText("")
        _pump_events(self.app, 80)

        self._type_text("- [ ] highlight me")
        _pump_events(self.app, 80)

        idx = self.editor.toPlainText().index("highlight")
        cur = self.editor.textCursor()
        cur.setPosition(idx)
        cur.setPosition(idx + len("highlight"), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cur)
        _pump_events(self.app, 40)

        self.editor._apply_highlight_color("#ffd60a")
        _pump_events(self.app, 80)
        self.assertIn('<mark style="background-color: #ffd60a;">highlight</mark>', self.editor.toPlainText())

        # Single Ctrl+Z must immediately undo the highlight without skipping or jumping to 0
        self._press_ctrl_z()
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.toPlainText(), "- [ ] highlight me")
        self.assertTrue(self.editor.canRedo())

        # Next Ctrl+Z undoes "me", NOT leaving the highlight intact
        self._press_ctrl_z()
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.toPlainText(), "- [ ] highlight ")

        # Ctrl+Y steps forward cleanly
        self._press_ctrl_y()
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.toPlainText(), "- [ ] highlight me")

        self._press_ctrl_y()
        _pump_events(self.app, 80)
        self.assertIn('<mark style="background-color: #ffd60a;">highlight</mark>', self.editor.toPlainText())

    def test_cursor_movement_across_code_block_preserves_redo_stack(self) -> None:
        self.editor.setPlainText("above\n```python\nx = 1\n```\nbelow")
        _pump_events(self.app, 80)

        cur = self.editor.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.Start)
        self.editor.setTextCursor(cur)
        self._type_text("edit ")
        _pump_events(self.app, 80)

        self._press_ctrl_z()
        _pump_events(self.app, 80)
        self.assertTrue(self.editor.canRedo())
        undo_before = self.editor.undo_manager.undo_count

        # Move cursor inside and back out of the code block (triggers margin recalc at line 1400)
        cur = self.editor.textCursor()
        cur.setPosition(self.editor.toPlainText().index("x = 1"))
        self.editor.setTextCursor(cur)
        _pump_events(self.app, 80)

        cur.setPosition(len(self.editor.toPlainText()))
        self.editor.setTextCursor(cur)
        _pump_events(self.app, 80)

        self.assertTrue(self.editor.canRedo(), "Cursor navigation across code block must not clear redo stack")
        self.assertEqual(self.editor.undo_manager.undo_count, undo_before)

    def test_empty_mark_tag_cleanup_undo_is_atomic(self) -> None:
        self.editor.setPlainText('<mark style="background-color: #ffd60a;">a</mark>')
        _pump_events(self.app, 80)

        # Place caret right after 'a' and press Backspace -> triggers empty <mark></mark> cleanup
        idx = self.editor.toPlainText().index("</mark>")
        cur = self.editor.textCursor()
        cur.setPosition(idx)
        self.editor.setTextCursor(cur)
        _pump_events(self.app, 40)

        ev_bs = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Backspace, Qt.KeyboardModifier.NoModifier)
        self.editor.keyPressEvent(ev_bs)
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.toPlainText(), "")

        # One Ctrl+Z restores '<mark ...>a</mark>' without leaving an empty '<mark></mark>' loop
        self._press_ctrl_z()
        _pump_events(self.app, 80)
        self.assertEqual(self.editor.toPlainText(), '<mark style="background-color: #ffd60a;">a</mark>')


if __name__ == "__main__":
    unittest.main()
