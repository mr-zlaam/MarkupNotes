"""Tests for F2 folder rename shortcut and All Notes relative folder path preview."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QStyleOptionViewItem

from core.config import ConfigManager
from core.note import Note
from core.storage import StorageManager
from ui.main_window import MainWindow
from ui.note_list import NoteListPanel
from ui.shortcuts_dialog import SHORTCUT_GROUPS
from ui.sidebar import FolderSidebar

app = QApplication.instance() or QApplication([])


class TestF2AndAllNotesPath(unittest.TestCase):
    """Test suite verifying F2 rename on focused folders and All Notes relative path rendering."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.notes_dir = self.root / "notes"
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.root / "settings.json"
        self.config_manager = ConfigManager(config_file=self.config_file)
        self.storage = StorageManager(self.notes_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_f2_key_on_focused_folder_and_nested_subfolder(self) -> None:
        """Verify F2 renames focused custom/nested folder and ignores All Notes or selection mode."""
        sidebar = FolderSidebar()
        parent_dir = self.notes_dir / "projects"
        sub_dir = parent_dir / "markupnotes"
        sub_dir.mkdir(parents=True)
        sidebar.set_folders([parent_dir, sub_dir])

        emitted: list[Path] = []
        sidebar.rename_folder_requested.connect(emitted.append)

        # Focused 'All Notes' -> should not emit
        all_notes_item = sidebar.tree_widget.topLevelItem(0)
        sidebar.tree_widget.setCurrentItem(all_notes_item)
        QTest.keyClick(sidebar.tree_widget, Qt.Key.Key_F2)
        self.assertEqual(emitted, [])

        # Focused root folder -> emits parent_dir
        parent_item = sidebar.tree_widget.topLevelItem(1)
        sidebar.tree_widget.setCurrentItem(parent_item)
        QTest.keyClick(sidebar.tree_widget, Qt.Key.Key_F2)
        self.assertEqual(emitted, [parent_dir])

        # Focused nested subfolder on viewport -> emits sub_dir
        sub_item = parent_item.child(0)
        sidebar.tree_widget.setCurrentItem(sub_item)
        QTest.keyClick(sidebar.tree_widget.viewport(), Qt.Key.Key_F2)
        self.assertEqual(emitted, [parent_dir, sub_dir])

        # Modifier Ctrl+F2 should not trigger rename
        QTest.keyClick(sidebar.tree_widget, Qt.Key.Key_F2, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(emitted), 2)

        # Selection mode should suppress F2 rename
        sidebar.enter_selection_mode()
        QTest.keyClick(sidebar.tree_widget, Qt.Key.Key_F2)
        self.assertEqual(len(emitted), 2)

        sidebar.deleteLater()

    def test_shortcuts_cheatsheet_lists_f2_rename_folder(self) -> None:
        """Verify Rename Folder and Rename Note (F2) are documented in the shortcuts cheatsheet."""
        entries = {
            title: keys
            for _, items in SHORTCUT_GROUPS
            for title, _, keys in items
        }
        self.assertEqual(entries.get("Rename Folder"), ["F2"])
        self.assertEqual(entries.get("Rename Note"), ["F2"])

    def test_f2_key_on_focused_note(self) -> None:
        """Verify pressing F2 on a focused note card emits rename_note_requested."""
        panel = NoteListPanel()
        emitted: list[Note] = []
        panel.rename_note_requested.connect(emitted.append)

        # Empty list -> nothing emitted
        QTest.keyClick(panel.list_widget, Qt.Key.Key_F2)
        self.assertEqual(emitted, [])

        n1 = Note.from_memory(self.notes_dir / "First.md", "one", 1000.0)
        n2 = Note.from_memory(self.notes_dir / "Second.md", "two", 2000.0)
        panel.set_notes([n1, n2])

        panel.list_widget.setCurrentRow(1)
        QTest.keyClick(panel.list_widget, Qt.Key.Key_F2)
        self.assertEqual(emitted, [n2])

        # Viewport event filter also triggers rename
        QTest.keyClick(panel.list_widget.viewport(), Qt.Key.Key_F2)
        self.assertEqual(emitted, [n2, n2])

        # Ctrl+F2 ignored
        QTest.keyClick(panel.list_widget, Qt.Key.Key_F2, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(emitted), 2)

        # Selection mode suppresses F2 rename
        panel.enter_selection_mode()
        QTest.keyClick(panel.list_widget, Qt.Key.Key_F2)
        self.assertEqual(len(emitted), 2)

        panel.deleteLater()

    def test_all_notes_relative_path_rendering_and_root_omission(self) -> None:
        """Verify relative path is shown in All Notes for nested files and hidden for root/folder views."""
        nested_dir = self.notes_dir / "projects" / "markupnotes"
        nested_dir.mkdir(parents=True)
        nested_note = Note.from_memory(
            nested_dir / "Roadmap.md",
            "# Roadmap\nImplement new features",
            1000.0,
        )
        root_note = Note.from_memory(
            self.notes_dir / "Inbox.md",
            "# Inbox\nRoot level note",
            1000.0,
        )

        panel = NoteListPanel()
        panel.set_path_context(self.notes_dir, show_relative_path=True)
        panel.set_notes([nested_note, root_note])

        self.assertEqual(panel.get_note_relative_folder(nested_note), "projects/markupnotes")
        self.assertEqual(panel.get_note_relative_folder(root_note), "")

        model = panel.list_widget.model()
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 260, 80)

        delegate = panel.list_widget.itemDelegate()
        nested_hint = delegate.sizeHint(opt, model.index(0, 0))
        root_hint = delegate.sizeHint(opt, model.index(1, 0))
        self.assertEqual(nested_hint.height(), 78)
        self.assertEqual(root_hint.height(), 64)

        # Paint both cards into an offscreen image to ensure zero painter errors
        img = QImage(280, 180, QImage.Format.Format_ARGB32)
        painter = QPainter(img)
        try:
            opt0 = QStyleOptionViewItem()
            opt0.rect = QRect(0, 0, 260, 78)
            delegate.paint(painter, opt0, model.index(0, 0))

            opt1 = QStyleOptionViewItem()
            opt1.rect = QRect(0, 78, 260, 64)
            delegate.paint(painter, opt1, model.index(1, 0))
        finally:
            painter.end()

        # Inside specific folder -> relative path hidden even for nested note
        panel.set_path_context(self.notes_dir, show_relative_path=False)
        self.assertEqual(panel.get_note_relative_folder(nested_note), "")
        self.assertEqual(delegate.sizeHint(opt, model.index(0, 0)).height(), 64)

        panel.deleteLater()

    def test_main_window_toggles_relative_path_between_all_notes_and_folder(self) -> None:
        """Verify MainWindow enables relative paths in All Notes and disables them in folder view."""
        sub_dir = self.notes_dir / "projects" / "markupnotes"
        sub_dir.mkdir(parents=True)
        note_path = sub_dir / "Design.md"
        note_path.write_text("# Design\narchitecture", encoding="utf-8")

        win = MainWindow(storage_manager=self.storage, config_manager=self.config_manager)
        try:
            # Default startup opens All Notes
            self.assertIsNone(win._current_folder)
            self.assertTrue(win.note_list._show_relative_path)
            self.assertEqual(
                win.note_list.get_note_relative_folder(win._all_current_notes[0]),
                "projects/markupnotes",
            )

            # Switch into specific subfolder -> path line turns off
            win._on_folder_selected(sub_dir)
            self.assertFalse(win.note_list._show_relative_path)
            self.assertEqual(
                win.note_list.get_note_relative_folder(win._all_current_notes[0]),
                "",
            )

            # Return to All Notes -> path line turns back on
            win._on_folder_selected(None)
            self.assertTrue(win.note_list._show_relative_path)
        finally:
            win.close()
