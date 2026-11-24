"""Unit and integration tests for Linux-style sorting of folders (including deep nesting) and notes."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication, QTreeWidgetItem

from core.config import AppSettings, ConfigManager
from core.note import Note
from core.storage import StorageManager
from ui.main_window import MainWindow
from ui.settings_dialog import ModernComboBox, ModernSettingsDialog
from ui.sidebar import FolderSidebar
from utils.sorting import (
    DEFAULT_SORT_ORDER,
    SORT_NAME_ASC,
    SORT_NAME_DESC,
    SORT_NEWEST,
    SORT_OLDEST,
    natural_sort_key,
    normalize_sort_order,
    sort_folders,
    sort_notes,
)

app = QApplication.instance() or QApplication([])


def _collect_tree_names(sidebar: FolderSidebar) -> list[tuple[str, list]]:
    """Recursively collect (name, children) structure from FolderSidebar QTreeWidget."""

    def _walk(item: QTreeWidgetItem) -> tuple[str, list]:
        children = [_walk(item.child(i)) for i in range(item.childCount())]
        return (item.text(0), children)

    return [
        _walk(sidebar.tree_widget.topLevelItem(i))
        for i in range(sidebar.tree_widget.topLevelItemCount())
    ]


class TestSorting(unittest.TestCase):
    """Test suite verifying natural Linux sorting across utils, storage, sidebar, settings, and MainWindow."""

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

    def test_natural_linux_key_and_normalization(self) -> None:
        """Verify case-insensitive natural ordering and sort order normalization."""
        self.assertEqual(normalize_sort_order(None), DEFAULT_SORT_ORDER)
        self.assertEqual(normalize_sort_order("invalid"), SORT_NAME_ASC)
        self.assertEqual(normalize_sort_order(SORT_NAME_DESC), SORT_NAME_DESC)

        raw = ["zebra", "Note 10", "apple", "Note 2", "Banana", "note 1"]
        ordered = sorted(raw, key=natural_sort_key)
        self.assertEqual(ordered, ["apple", "Banana", "note 1", "Note 2", "Note 10", "zebra"])

    def test_sort_notes_all_modes(self) -> None:
        """Verify sort_notes handles name_asc, name_desc, newest, and oldest cleanly."""
        n1 = Note.from_memory(self.notes_dir / "Note 10.md", "ten", modified_at=200.0)
        n2 = Note.from_memory(self.notes_dir / "apple.md", "app", modified_at=100.0)
        n3 = Note.from_memory(self.notes_dir / "Note 2.md", "two", modified_at=300.0)
        n4 = Note.from_memory(self.notes_dir / "Zebra.md", "zeb", modified_at=250.0)
        notes = [n1, n2, n3, n4]

        self.assertEqual(
            [n.title for n in sort_notes(notes, SORT_NAME_ASC)],
            ["apple", "Note 2", "Note 10", "Zebra"],
        )
        self.assertEqual(
            [n.title for n in sort_notes(notes, SORT_NAME_DESC)],
            ["Zebra", "Note 10", "Note 2", "apple"],
        )
        self.assertEqual(
            [n.title for n in sort_notes(notes, SORT_NEWEST)],
            ["Note 2", "Zebra", "Note 10", "apple"],
        )
        self.assertEqual(
            [n.title for n in sort_notes(notes, SORT_OLDEST)],
            ["apple", "Note 10", "Zebra", "Note 2"],
        )

    def test_deep_nested_folders_sorting(self) -> None:
        """Verify sort_folders and FolderSidebar apply sorting through deepest nested levels."""
        # Create 3-level nested directory hierarchy
        d_b = self.notes_dir / "beta"
        d_a = self.notes_dir / "Alpha"
        d_a_sub10 = d_a / "sub 10"
        d_a_sub2 = d_a / "sub 2"
        d_a_sub2_deep_z = d_a_sub2 / "zebra"
        d_a_sub2_deep_a = d_a_sub2 / "apple"

        for d in (d_b, d_a, d_a_sub10, d_a_sub2, d_a_sub2_deep_z, d_a_sub2_deep_a):
            d.mkdir(parents=True, exist_ok=True)

        # Assign deterministic mtimes bottom-up so child creations don't overwrite test values
        timestamps = {
            d_b: (1000.0, 1000.0),
            d_a: (2000.0, 2000.0),
            d_a_sub10: (1100.0, 1100.0),
            d_a_sub2: (2100.0, 2100.0),
            d_a_sub2_deep_z: (3100.0, 3100.0),
            d_a_sub2_deep_a: (1200.0, 1200.0),
        }
        for path, times in timestamps.items():
            os.utime(path, times)

        folders = self.storage.get_folders(sort_order=SORT_NAME_ASC)
        self.assertEqual(
            [p.name for p in folders],
            ["Alpha", "sub 2", "apple", "zebra", "sub 10", "beta"],
        )

        # Check Sidebar tree widget across all 4 modes
        sidebar = FolderSidebar()
        sidebar.set_folders(folders, sort_order=SORT_NAME_ASC)
        tree_asc = _collect_tree_names(sidebar)
        self.assertEqual(tree_asc[0][0], "All Notes")
        self.assertEqual([node[0] for node in tree_asc[1:]], ["Alpha", "beta"])
        alpha_children = tree_asc[1][1]
        self.assertEqual([node[0] for node in alpha_children], ["sub 2", "sub 10"])
        deep_children = alpha_children[0][1]
        self.assertEqual([node[0] for node in deep_children], ["apple", "zebra"])

        # Switch to Z-A and verify deepest level reverses cleanly
        sidebar.set_sort_order(SORT_NAME_DESC)
        tree_desc = _collect_tree_names(sidebar)
        self.assertEqual([node[0] for node in tree_desc[1:]], ["beta", "Alpha"])
        alpha_desc = tree_desc[2][1]
        self.assertEqual([node[0] for node in alpha_desc], ["sub 10", "sub 2"])
        deep_desc = alpha_desc[1][1]
        self.assertEqual([node[0] for node in deep_desc], ["zebra", "apple"])

        # Switch to Newest and verify folder mtimes sort all levels
        sidebar.set_sort_order(SORT_NEWEST)
        tree_newest = _collect_tree_names(sidebar)
        self.assertEqual([node[0] for node in tree_newest[1:]], ["Alpha", "beta"])
        alpha_newest = tree_newest[1][1]
        self.assertEqual([node[0] for node in alpha_newest], ["sub 2", "sub 10"])
        deep_newest = alpha_newest[0][1]
        self.assertEqual([node[0] for node in deep_newest], ["zebra", "apple"])

        # Switch to Oldest
        ordered_oldest = sort_folders(folders, sort_order=SORT_OLDEST)
        self.assertEqual(
            [p.name for p in ordered_oldest],
            ["beta", "Alpha", "sub 10", "sub 2", "apple", "zebra"],
        )

    def test_config_and_settings_dialog_sort_order(self) -> None:
        """Verify default_sort_order defaults to name_asc, persists, resets, and binds in Settings."""
        self.assertEqual(self.config_manager.settings.general.default_sort_order, SORT_NAME_ASC)

        self.config_manager.update_general(default_sort_order=SORT_OLDEST)
        reloaded = ConfigManager(config_file=self.config_file)
        self.assertEqual(reloaded.settings.general.default_sort_order, SORT_OLDEST)

        invalid_cfg = AppSettings.from_dict({"general": {"default_sort_order": "bogus"}})
        self.assertEqual(invalid_cfg.general.default_sort_order, SORT_NAME_ASC)

        dialog = ModernSettingsDialog(self.config_manager)
        sort_row = next(
            (r for r in dialog.setting_rows if r.title_lbl.text() == "Default Sort Order"),
            None,
        )
        self.assertIsNotNone(sort_row)
        combo = sort_row.findChild(ModernComboBox)
        self.assertIsNotNone(combo)
        self.assertEqual(combo.currentText(), "Oldest First")

        idx_za = next(
            i for i, (_, val) in enumerate(dialog.SORT_ORDER_OPTIONS) if val == SORT_NAME_DESC
        )
        combo.setCurrentIndex(idx_za)
        self.assertEqual(self.config_manager.settings.general.default_sort_order, SORT_NAME_DESC)
        dialog.close()

        self.config_manager.reset_to_defaults()
        self.assertEqual(self.config_manager.settings.general.default_sort_order, SORT_NAME_ASC)

    def test_main_window_startup_and_live_sort_updates(self) -> None:
        """Verify MainWindow sorts by default (A-Z) at launch and updates live from Settings."""
        f_z = self.notes_dir / "z_folder"
        f_a = self.notes_dir / "a_folder"
        f_a_nested_b = f_a / "nested_b"
        f_a_nested_a = f_a / "nested_a"
        for d in (f_z, f_a, f_a_nested_b, f_a_nested_a):
            d.mkdir(parents=True, exist_ok=True)

        p1 = self.notes_dir / "Note 10.md"
        p2 = self.notes_dir / "alpha.md"
        p3 = self.notes_dir / "Note 2.md"
        p1.write_text("# Note 10\nbody", encoding="utf-8")
        p2.write_text("# alpha\nbody", encoding="utf-8")
        p3.write_text("# Note 2\nbody", encoding="utf-8")
        os.utime(p1, (1000.0, 1000.0))
        os.utime(p2, (3000.0, 3000.0))
        os.utime(p3, (2000.0, 2000.0))

        win = MainWindow(storage_manager=self.storage, config_manager=self.config_manager)
        try:
            # Default A-Z Linux natural sorting
            self.assertEqual(
                [n.title for n in win._all_current_notes],
                ["alpha", "Note 2", "Note 10"],
            )
            tree_default = _collect_tree_names(win.sidebar)
            self.assertEqual([node[0] for node in tree_default[1:]], ["a_folder", "z_folder"])
            self.assertEqual([node[0] for node in tree_default[1][1]], ["nested_a", "nested_b"])

            # Simulate changing Default Sort Order in Settings -> Newest First
            self.config_manager.update_general(default_sort_order=SORT_NEWEST)
            win._on_settings_updated()
            self.assertEqual(
                [n.title for n in win._all_current_notes],
                ["alpha", "Note 2", "Note 10"],
            )

            # Switch to Name (Z-A) -> re-sorts both deep folders and notes live
            self.config_manager.update_general(default_sort_order=SORT_NAME_DESC)
            win._on_settings_updated()
            self.assertEqual(
                [n.title for n in win._all_current_notes],
                ["Note 10", "Note 2", "alpha"],
            )
            tree_za = _collect_tree_names(win.sidebar)
            self.assertEqual([node[0] for node in tree_za[1:]], ["z_folder", "a_folder"])
            self.assertEqual([node[0] for node in tree_za[2][1]], ["nested_b", "nested_a"])

            # Verify in-memory upsert preserves active Z-A sort order
            updated_alpha = Note.from_memory(p2, "# alpha\nedited", 9999.0)
            win._upsert_current_note_in_list(p2, updated_alpha)
            self.assertEqual(
                [n.title for n in win._all_current_notes],
                ["Note 10", "Note 2", "alpha"],
            )
        finally:
            win.close()
