"""Tests for backing up customizations and settings into .markup-notes/ with VS Code-style conflict handling."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

from core.config import ConfigManager
from core.storage import StorageManager
from core.vault_sync import (
    get_vault_customizations_path,
    get_vault_settings_path,
)
from ui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


class TestVaultSync(unittest.TestCase):
    """Verify automatic export/import of customizations and conflict-aware settings sync."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.notes_dir = self.root / "notes"
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.root / "config" / "settings.json"
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.storage = StorageManager(self.notes_dir)

    def tearDown(self) -> None:
        app.processEvents()
        self.temp_dir.cleanup()

    def test_save_mirrors_customizations_and_settings_with_relative_note_colors(self) -> None:
        """Saving pins, colors, and settings exports portable JSON into .markup-notes/."""
        cfg = ConfigManager(config_file=self.config_file)
        cfg.set_vault_dir(self.notes_dir)

        note_path = self.notes_dir / "Work" / "Roadmap.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text("# Roadmap\n", encoding="utf-8")

        cfg.set_folder_color("Work", "#ff453a")
        cfg.set_note_color(str(note_path), "#30d158")
        cfg.toggle_pin_note("Work/Roadmap.md")
        cfg.toggle_pin_folder("Work")
        cfg.update_editor(font_size=16)

        cust_file = get_vault_customizations_path(self.notes_dir)
        sett_file = get_vault_settings_path(self.notes_dir)
        self.assertTrue(cust_file.exists())
        self.assertTrue(sett_file.exists())

        cust_data = json.loads(cust_file.read_text(encoding="utf-8"))
        self.assertEqual(cust_data["folder_colors"], {"Work": "#ff453a"})
        self.assertEqual(cust_data["note_colors"], {"Work/Roadmap.md": "#30d158"})
        self.assertEqual(cust_data["pinned_notes"], ["Work/Roadmap.md"])
        self.assertEqual(cust_data["pinned_folders"], ["Work"])

        sett_data = json.loads(sett_file.read_text(encoding="utf-8"))
        self.assertEqual(sett_data["editor"]["font_size"], 16)
        self.assertNotIn("session", sett_data)
        self.assertNotIn("github_repo_url", sett_data.get("backup", {}))

        # Hidden .markup-notes/ directory must never appear in StorageManager listings
        self.assertEqual([p.name for p in self.storage.get_folders()], ["Work"])

    def test_fresh_machine_auto_imports_customizations_and_settings(self) -> None:
        """On a fresh default setup, opening a backed-up vault auto-applies customizations and settings."""
        work = self.notes_dir / "Work"
        work.mkdir(parents=True, exist_ok=True)
        note_path = work / "Spec.md"
        note_path.write_text("# Spec\nbody", encoding="utf-8")

        # Simulate backup files created on another Linux machine
        cust_file = get_vault_customizations_path(self.notes_dir)
        sett_file = get_vault_settings_path(self.notes_dir)
        cust_file.parent.mkdir(parents=True, exist_ok=True)
        cust_file.write_text(
            json.dumps(
                {
                    "folder_colors": {"Work": "#0a84ff"},
                    "note_colors": {"Work/Spec.md": "#ff9f0a"},
                    "pinned_notes": ["Work/Spec.md"],
                    "pinned_folders": ["Work"],
                }
            ),
            encoding="utf-8",
        )
        sett_file.write_text(
            json.dumps(
                {
                    "editor": {"font_size": 18, "tab_size": 4},
                    "general": {"default_sort_order": "newest"},
                }
            ),
            encoding="utf-8",
        )

        fresh_cfg = ConfigManager(config_file=self.config_file)
        win = MainWindow(storage_manager=self.storage, config_manager=fresh_cfg)
        try:
            self.assertEqual(win.config.appearance.folder_colors, {"Work": "#0a84ff"})
            self.assertEqual(win.config.appearance.note_colors, {str(note_path): "#ff9f0a"})
            self.assertEqual(win.config.general.pinned_notes, ["Work/Spec.md"])
            self.assertEqual(win.config.general.pinned_folders, ["Work"])
            self.assertEqual(win.config.editor.font_size, 18)
            self.assertEqual(win.config.editor.tab_size, 4)
            self.assertEqual(win.config.general.default_sort_order, "newest")
        finally:
            win.close()
            win.deleteLater()

    def test_sync_conflict_resolution_and_default_auto_overwrite(self) -> None:
        """Verify VS Code-style conflict resolution: defaults auto-overwrite; modified local prompts user."""
        cfg = ConfigManager(config_file=self.config_file)
        cfg.set_vault_dir(self.notes_dir)
        cfg.export_to_vault()

        # 1. Local settings are defaults -> pulled settings overwrite silently without prompt
        sett_file = get_vault_settings_path(self.notes_dir)
        pulled = json.loads(sett_file.read_text(encoding="utf-8"))
        pulled["editor"]["font_size"] = 20
        sett_file.write_text(json.dumps(pulled), encoding="utf-8")

        prompted = []
        _, sett_updated = cfg.resolve_vault_sync(
            customizations_changed=False,
            settings_changed=True,
            ask_conflict_fn=lambda: prompted.append(True) or True,
        )
        self.assertTrue(sett_updated)
        self.assertEqual(prompted, [])
        self.assertEqual(cfg.settings.editor.font_size, 20)

        # 2. Local settings are non-default (20) AND remote differs (24) -> prompt; user chooses Keep Local (False)
        pulled["editor"]["font_size"] = 24
        sett_file.write_text(json.dumps(pulled), encoding="utf-8")

        _, sett_updated_2 = cfg.resolve_vault_sync(
            customizations_changed=False,
            settings_changed=True,
            ask_conflict_fn=lambda: prompted.append(False) or False,
        )
        self.assertFalse(sett_updated_2)
        self.assertEqual(len(prompted), 1)
        self.assertEqual(cfg.settings.editor.font_size, 20)
        # Vault file should now reflect local choice (20) for next push
        self.assertEqual(json.loads(sett_file.read_text(encoding="utf-8"))["editor"]["font_size"], 20)

        # 3. User chooses Use Backup Settings (True) -> overwrites local with 24
        pulled["editor"]["font_size"] = 24
        sett_file.write_text(json.dumps(pulled), encoding="utf-8")
        _, sett_updated_3 = cfg.resolve_vault_sync(
            customizations_changed=False,
            settings_changed=True,
            ask_conflict_fn=lambda: True,
        )
        self.assertTrue(sett_updated_3)
        self.assertEqual(cfg.settings.editor.font_size, 24)

    def test_main_window_sync_completed_applies_customizations_and_prompts_conflict(self) -> None:
        """End-to-end MainWindow._on_sync_completed updates pins/colors and prompts on settings conflict."""
        work = self.notes_dir / "Work"
        work.mkdir(parents=True, exist_ok=True)
        cfg = ConfigManager(config_file=self.config_file)
        win = MainWindow(storage_manager=self.storage, config_manager=cfg)
        try:
            # Modify local setting so conflict prompt triggers on remote change
            cfg.update_editor(font_size=15)
            get_vault_customizations_path(self.notes_dir).write_text(
                json.dumps({"folder_colors": {"Work": "#bf5af2"}, "pinned_folders": ["Work"]}),
                encoding="utf-8",
            )
            sett_path = get_vault_settings_path(self.notes_dir)
            pulled = json.loads(sett_path.read_text(encoding="utf-8"))
            pulled["editor"]["font_size"] = 22
            sett_path.write_text(json.dumps(pulled), encoding="utf-8")

            with (
                patch.object(win.backup_panel, "last_sync_vault_changes", return_value=(True, True)),
                patch.object(win, "_ask_settings_conflict_resolution", return_value=True) as mock_ask,
            ):
                win._on_sync_completed(True, "Synced")
                mock_ask.assert_called_once()

            self.assertEqual(win.config.appearance.folder_colors, {"Work": "#bf5af2"})
            self.assertEqual(win.config.general.pinned_folders, ["Work"])
            self.assertEqual(win.config.editor.font_size, 22)
        finally:
            win.close()
            win.deleteLater()
