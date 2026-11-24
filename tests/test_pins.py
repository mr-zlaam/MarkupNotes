"""Unit and integration tests for pinning notes and folders with latest-pin-first ordering."""

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
from ui.shortcuts_dialog import SHORTCUT_GROUPS
from utils.icons import create_pin_icon
from utils.sorting import SORT_NAME_ASC, sort_folders, sort_notes

app = QApplication.instance() or QApplication([])


class TestPins(unittest.TestCase):
    """Test suite verifying file/folder pinning, latest-pin-first sorting, Alt+P, and persistence."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.notes_dir = self.root / "notes"
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.root / "settings.json"
        self.config_manager = ConfigManager(config_file=self.config_file)
        self.storage = StorageManager(self.notes_dir)

    def tearDown(self) -> None:
        app.processEvents()
        self.temp_dir.cleanup()

    def test_pin_icon_and_shortcuts_entry(self) -> None:
        """Verify pin/unpin icons render cleanly and Alt+P is listed in shortcuts cheatsheet."""
        self.assertFalse(create_pin_icon(pinned=True).isNull())
        self.assertFalse(create_pin_icon(pinned=False).isNull())
        entries = {title: keys for _, items in SHORTCUT_GROUPS for title, _, keys in items}
        self.assertEqual(entries.get("Pin / Unpin Note or Folder"), ["Alt", "P"])

    def test_config_pin_ordering_transfer_and_cleanup(self) -> None:
        """Verify latest pin is placed at index 0 and renames/deletes update pin keys."""
        self.assertTrue(self.config_manager.toggle_pin_note("Work/Alpha.md"))
        self.assertTrue(self.config_manager.toggle_pin_note("Work/Zeta.md"))
        self.assertEqual(self.config_manager.settings.general.pinned_notes, ["Work/Zeta.md", "Work/Alpha.md"])

        # Rename Alpha -> Beta preserves its pin slot
        self.config_manager.transfer_note_pin("Work/Alpha.md", "Work/Beta.md")
        self.assertEqual(self.config_manager.settings.general.pinned_notes, ["Work/Zeta.md", "Work/Beta.md"])

        # Folder rename updates nested pinned folder and pinned notes under it
        self.assertTrue(self.config_manager.toggle_pin_folder("Work"))
        self.config_manager.transfer_folder_pin("Work", "Office")
        self.assertEqual(self.config_manager.settings.general.pinned_folders, ["Office"])
        self.assertEqual(self.config_manager.settings.general.pinned_notes, ["Office/Zeta.md", "Office/Beta.md"])

        # Unpinning removes item; folder delete removes descendants
        self.assertFalse(self.config_manager.toggle_pin_note("Office/Zeta.md"))
        self.assertEqual(self.config_manager.settings.general.pinned_notes, ["Office/Beta.md"])
        self.config_manager.remove_folder_pin("Office")
        self.assertEqual(self.config_manager.settings.general.pinned_folders, [])
        self.assertEqual(self.config_manager.settings.general.pinned_notes, [])

    def test_sort_notes_and_nested_folders_latest_pin_first(self) -> None:
        """Verify latest pin appears on top while keeping nested folders inside their parent."""
        n_a = Note.from_memory(self.notes_dir / "Alpha.md", "a", 100.0)
        n_b = Note.from_memory(self.notes_dir / "Beta.md", "b", 200.0)
        n_z = Note.from_memory(self.notes_dir / "Zeta.md", "z", 300.0)

        # Zeta pinned first, then Beta pinned later -> Beta is latest -> Beta, Zeta, Alpha
        sorted_n = sort_notes(
            [n_a, n_b, n_z],
            sort_order=SORT_NAME_ASC,
            pinned_keys=["Beta.md", "Zeta.md"],
            root_dir=self.notes_dir,
        )
        self.assertEqual([n.title for n in sorted_n], ["Beta", "Zeta", "Alpha"])
        self.assertTrue(sorted_n[0].is_pinned)
        self.assertTrue(sorted_n[1].is_pinned)
        self.assertFalse(sorted_n[2].is_pinned)

        # Nested folders: pinning Work/Zeta keeps it inside Work at the top of Work's children
        f_a = self.notes_dir / "Alpha"
        f_w = self.notes_dir / "Work"
        f_wa = f_w / "A_Sub"
        f_wz = f_w / "Z_Sub"
        for d in (f_a, f_w, f_wa, f_wz):
            d.mkdir(parents=True, exist_ok=True)

        ordered_f = sort_folders(
            [f_a, f_w, f_wa, f_wz],
            sort_order=SORT_NAME_ASC,
            pinned_keys=["Work/Z_Sub"],
            root_dir=self.notes_dir,
        )
        self.assertEqual(
            [p.relative_to(self.notes_dir).as_posix() for p in ordered_f],
            ["Alpha", "Work", "Work/Z_Sub", "Work/A_Sub"],
        )

    def test_main_window_pins_relative_to_folder_alt_p_and_persistence(self) -> None:
        """Verify pinning files/folders, folder-scoped note lists, Alt+P, painting, and relaunch restore."""
        work = self.notes_dir / "Work"
        personal = self.notes_dir / "Personal"
        work.mkdir(parents=True)
        personal.mkdir(parents=True)

        w_alpha = work / "Alpha.md"
        w_zeta = work / "Zeta.md"
        w_mid = work / "Mid.md"
        p_note = personal / "Diary.md"
        for p in (w_alpha, w_zeta, w_mid, p_note):
            p.write_text(f"# {p.stem}\ncontent", encoding="utf-8")

        win1 = MainWindow(storage_manager=self.storage, config_manager=self.config_manager)
        win1.show()
        app.processEvents()
        try:
            # Select Work folder -> initial A-Z order: Alpha, Mid, Zeta
            win1._on_folder_selected(work)
            app.processEvents()
            self.assertEqual([n.title for n in win1._all_current_notes], ["Alpha", "Mid", "Zeta"])

            # Pin Zeta via signal, then Mid via Alt+P in editor -> Mid (latest), Zeta, Alpha
            zeta_note = next(n for n in win1._all_current_notes if n.path == w_zeta)
            win1._on_toggle_pin_note(zeta_note)
            self.assertEqual([n.title for n in win1._all_current_notes], ["Zeta", "Alpha", "Mid"])

            mid_note = next(n for n in win1._all_current_notes if n.path == w_mid)
            win1._on_note_selected(mid_note)
            app.processEvents()
            QTest.keyClick(win1.editor.editor, Qt.Key.Key_P, Qt.KeyboardModifier.AltModifier)
            app.processEvents()
            self.assertEqual([n.title for n in win1._all_current_notes], ["Mid", "Zeta", "Alpha"])

            # Switching to Personal does NOT show Work's pinned notes (pins are folder-relative)
            win1._on_folder_selected(personal)
            app.processEvents()
            self.assertEqual([n.title for n in win1._all_current_notes], ["Diary"])

            # Switching to All Notes shows Work's pinned notes at the top (Mid, Zeta)
            win1._on_folder_selected(None)
            app.processEvents()
            self.assertEqual([n.title for n in win1._all_current_notes[:2]], ["Mid", "Zeta"])

            # Focus Personal folder in sidebar and press Alt+P -> Personal moves above Work (below All Notes)
            personal_item = win1.sidebar._find_item_for_folder(personal)
            win1.sidebar.tree_widget.setCurrentItem(personal_item)
            win1.sidebar.tree_widget.setFocus()
            app.processEvents()
            QTest.keyClick(win1.sidebar.tree_widget, Qt.Key.Key_P, Qt.KeyboardModifier.AltModifier)
            app.processEvents()
            top_names = [
                win1.sidebar.tree_widget.topLevelItem(i).text(0)
                for i in range(win1.sidebar.tree_widget.topLevelItemCount())
            ]
            self.assertEqual(top_names, ["All Notes", "Personal", "Work"])

            # Verify note delegate paints pinned card cleanly without error
            img = QImage(280, 100, QImage.Format.Format_ARGB32)
            painter = QPainter(img)
            try:
                opt = QStyleOptionViewItem()
                opt.rect = QRect(0, 0, 260, 78)
                win1.note_list.list_widget.itemDelegate().paint(
                    painter, opt, win1.note_list.list_widget.model().index(0, 0)
                )
            finally:
                painter.end()
        finally:
            win1.close()
            win1.deleteLater()
            app.processEvents()

        # Relaunch and verify pin order persisted for both folders and notes
        reloaded_cfg = ConfigManager(config_file=self.config_file)
        win2 = MainWindow(storage_manager=self.storage, config_manager=reloaded_cfg)
        try:
            top_names_2 = [
                win2.sidebar.tree_widget.topLevelItem(i).text(0)
                for i in range(win2.sidebar.tree_widget.topLevelItemCount())
            ]
            self.assertEqual(top_names_2, ["All Notes", "Personal", "Work"])
            win2._on_folder_selected(work)
            app.processEvents()
            self.assertEqual([n.title for n in win2._all_current_notes], ["Mid", "Zeta", "Alpha"])
        finally:
            win2.close()
            win2.deleteLater()
            app.processEvents()
