"""Unit tests for modern dynamic date picker, date cards, and /date slash insertion."""

from datetime import date, timedelta
import unittest

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QTextCursor
from PyQt6.QtWidgets import QApplication

from ui.date_picker import ModernDatePickerDialog
from ui.editor import MarkdownEditor
from ui.slash_menu import COMMANDS, SlashCommand
from utils.date_card import render_date_card
from utils.date_format import format_dynamic_date, parse_date_string


class TestDateFormatUtils(unittest.TestCase):
    """Test date parsing and dynamic relative formatting."""

    def test_dynamic_date_today(self) -> None:
        today = date.today()
        self.assertEqual(format_dynamic_date(today), "Today")

    def test_dynamic_date_yesterday(self) -> None:
        yesterday = date.today() - timedelta(days=1)
        self.assertEqual(format_dynamic_date(yesterday), "Yesterday")

    def test_dynamic_date_standard(self) -> None:
        d = date(2026, 11, 29)
        self.assertEqual(format_dynamic_date(d), "November 29, 2026")

    def test_parse_date_string_keywords(self) -> None:
        today = date.today()
        self.assertEqual(parse_date_string("today"), today)
        self.assertEqual(parse_date_string("Today"), today)
        self.assertEqual(parse_date_string("yesterday"), today - timedelta(days=1))
        self.assertEqual(parse_date_string("tomorrow"), today + timedelta(days=1))

    def test_parse_date_string_iso_and_formats(self) -> None:
        self.assertEqual(parse_date_string("2026-11-29"), date(2026, 11, 29))
        self.assertEqual(parse_date_string("November 29, 2026"), date(2026, 11, 29))
        self.assertEqual(parse_date_string("29 November 2026"), date(2026, 11, 29))
        self.assertIsNone(parse_date_string("not-a-date"))
        self.assertIsNone(parse_date_string(""))


class TestDatePickerDialog(unittest.TestCase):
    """Test modern date picker dialog functionality."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_initial_and_selected_date(self) -> None:
        target = date(2026, 11, 20)
        dlg = ModernDatePickerDialog(initial_date=target)
        self.assertEqual(dlg.selected_date, target)
        dlg.close()

    def test_dialog_quick_buttons(self) -> None:
        dlg = ModernDatePickerDialog()
        today = date.today()
        dlg._on_quick_date_clicked(today - timedelta(days=1))
        self.assertEqual(dlg.selected_date, today - timedelta(days=1))
        dlg.close()

    def test_dialog_month_navigation(self) -> None:
        dlg = ModernDatePickerDialog(initial_date=date(2026, 5, 15))
        self.assertEqual(dlg._view_month, 5)
        dlg._prev_month()
        self.assertEqual(dlg._view_month, 4)
        dlg._next_month()
        self.assertEqual(dlg._view_month, 5)
        dlg.close()


class TestDateCardRendering(unittest.TestCase):
    """Test painter rendering for date cards."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_render_date_card_painting(self) -> None:
        img = QImage(300, 50, QImage.Format.Format_ARGB32)
        img.fill(QColor("#1e1e24"))
        painter = QPainter(img)
        rect = QRectF(10.0, 5.0, 280.0, 36.0)
        target = date(2026, 11, 29)

        # Should render without throwing exceptions
        render_date_card(painter, rect, target, ui_scale=1.0, is_hovered=False)
        render_date_card(painter, rect, target, ui_scale=1.25, is_hovered=True)
        painter.end()


class TestEditorDateIntegration(unittest.TestCase):
    """Test editor slash command palette and newline date insertion."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.editor = MarkdownEditor()

    def tearDown(self) -> None:
        self.editor.deleteLater()

    def test_slash_command_registered(self) -> None:
        date_cmd = next((c for c in COMMANDS if c.id == "date"), None)
        self.assertIsNotNone(date_cmd)
        self.assertEqual(date_cmd.title, "Date")

    def test_date_inserted_on_clean_newline_from_checkbox(self) -> None:
        self.editor.setPlainText("- [ ] Task item /date")
        cur = self.editor.textCursor()
        cur.setPosition(len("- [ ] Task item /date"))
        self.editor.setTextCursor(cur)
        self.editor._slash_start_pos = len("- [ ] Task item /")

        cmd = next(c for c in COMMANDS if c.id == "date")

        # Mock ModernDatePickerDialog execution to return target date
        target = date(2026, 11, 29)
        from unittest.mock import patch
        with patch("ui.editor.ModernDatePickerDialog") as MockDialog:
            mock_dlg = MockDialog.return_value
            mock_dlg.exec.return_value = True
            mock_dlg.selected_date = target

            self.editor._on_slash_command_selected(cmd)

        text = self.editor.toPlainText()
        lines = text.split("\n")
        self.assertEqual(lines[0], "- [ ] Task item ")
        self.assertEqual(lines[1], "@date(2026-11-29)")
        # Inactive block highlighter detects the date
        self.assertIn(1, self.editor.highlighter.date_blocks)
        self.assertEqual(self.editor.highlighter.date_blocks[1], target)

    def test_date_inserted_on_empty_line(self) -> None:
        self.editor.setPlainText("/date")
        cur = self.editor.textCursor()
        cur.setPosition(5)
        self.editor.setTextCursor(cur)
        self.editor._slash_start_pos = 1

        cmd = next(c for c in COMMANDS if c.id == "date")
        target = date(2026, 11, 29)
        from unittest.mock import patch
        with patch("ui.editor.ModernDatePickerDialog") as MockDialog:
            mock_dlg = MockDialog.return_value
            mock_dlg.exec.return_value = True
            mock_dlg.selected_date = target

            self.editor._on_slash_command_selected(cmd)

        text = self.editor.toPlainText()
        lines = text.split("\n")
        self.assertEqual(lines[0], "@date(2026-11-29)")
        self.assertIn(0, self.editor.highlighter.date_blocks)


if __name__ == "__main__":
    unittest.main()
