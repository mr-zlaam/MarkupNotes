"""Unit tests verifying automatic backup toggle and debounced auto-sync functionality."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication

from core.config import AppSettings, ConfigManager
from core.storage import StorageManager
from ui.backup_panel import BackupPanel
from ui.settings_dialog import ModernComboBox, ModernSettingsDialog


class TestAutoBackup(unittest.TestCase):
    """Test suite verifying auto-backup toggle persistence and background sync scheduling."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.config_file = self.root / "settings.json"
        self.config_manager = ConfigManager(config_file=self.config_file)
        self.storage = StorageManager(self.root / "notes")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_config_defaults_and_persistence(self) -> None:
        """Verify BackupConfig defaults to False and persists changes."""
        self.assertFalse(self.config_manager.get_auto_backup())

        self.config_manager.set_auto_backup(True)
        self.assertTrue(self.config_manager.get_auto_backup())

        # Reload from disk
        reloaded = ConfigManager(config_file=self.config_file)
        self.assertTrue(reloaded.get_auto_backup())

        # Test from_dict deserialization
        settings = AppSettings.from_dict({"backup": {"auto_backup": True}})
        self.assertTrue(settings.backup.auto_backup)

        settings_false = AppSettings.from_dict({})
        self.assertFalse(settings_false.backup.auto_backup)

    def test_backup_panel_toggle_integration(self) -> None:
        """Verify BackupPanel initializes toggle state from ConfigManager and updates on toggle."""
        self.config_manager.set_auto_backup(True)
        panel = BackupPanel(storage_manager=self.storage, config_manager=self.config_manager)

        self.assertTrue(panel.toggle_auto_backup.isChecked())
        self.assertTrue(panel.is_auto_backup_enabled())

        # Toggle OFF
        panel.toggle_auto_backup.setChecked(False)
        self.assertFalse(panel.is_auto_backup_enabled())
        self.assertFalse(self.config_manager.get_auto_backup())

        # Toggle ON
        panel.toggle_auto_backup.setChecked(True)
        self.assertTrue(panel.is_auto_backup_enabled())
        self.assertTrue(self.config_manager.get_auto_backup())

    def test_schedule_auto_backup_behavior(self) -> None:
        """Verify schedule_auto_backup starts debounce timer only when enabled and in repo."""
        panel = BackupPanel(storage_manager=self.storage, config_manager=self.config_manager)
        panel.git_manager.init_repo()

        # When auto backup is disabled
        panel.toggle_auto_backup.setChecked(False)
        panel.schedule_auto_backup()
        self.assertFalse(panel._auto_backup_timer.isActive())

        # When auto backup is enabled
        panel.toggle_auto_backup.setChecked(True)
        panel.schedule_auto_backup()
        self.assertTrue(panel._auto_backup_timer.isActive())

        # Toggling off stops active timer
        panel.toggle_auto_backup.setChecked(False)
        self.assertFalse(panel._auto_backup_timer.isActive())

    def test_auto_backup_delay_config_defaults_clamping_and_persistence(self) -> None:
        """Verify auto_backup_delay_ms defaults, bounds clamping, and persistence."""
        self.assertEqual(self.config_manager.get_auto_backup_delay_ms(), 2500)

        self.config_manager.set_auto_backup_delay_ms(10000)
        self.assertEqual(self.config_manager.get_auto_backup_delay_ms(), 10000)

        reloaded = ConfigManager(config_file=self.config_file)
        self.assertEqual(reloaded.get_auto_backup_delay_ms(), 10000)

        # Clamping checks
        self.config_manager.set_auto_backup_delay_ms(200)
        self.assertEqual(self.config_manager.get_auto_backup_delay_ms(), 1000)
        self.config_manager.set_auto_backup_delay_ms(9999999)
        self.assertEqual(self.config_manager.get_auto_backup_delay_ms(), 600000)

        # Deserialization defaults & bounds
        s_default = AppSettings.from_dict({})
        self.assertEqual(s_default.backup.auto_backup_delay_ms, 2500)
        s_custom = AppSettings.from_dict({"backup": {"auto_backup_delay_ms": 30000}})
        self.assertEqual(s_custom.backup.auto_backup_delay_ms, 30000)
        s_clamped = AppSettings.from_dict({"backup": {"auto_backup_delay_ms": 100}})
        self.assertEqual(s_clamped.backup.auto_backup_delay_ms, 1000)

    def test_backup_panel_uses_configured_delay_and_syncs(self) -> None:
        """Verify BackupPanel uses ConfigManager delay and syncs updates without looping."""
        self.config_manager.set_auto_backup(True)
        self.config_manager.set_auto_backup_delay_ms(15000)

        panel = BackupPanel(storage_manager=self.storage, config_manager=self.config_manager)
        panel.git_manager.init_repo()
        self.assertEqual(panel._auto_backup_timer.interval(), 15000)

        panel.schedule_auto_backup()
        self.assertTrue(panel._auto_backup_timer.isActive())
        self.assertEqual(panel._auto_backup_timer.interval(), 15000)

        # Update config externally (as SettingsDialog does) and sync
        self.config_manager.set_auto_backup_delay_ms(60000)
        panel.sync_auto_backup_settings()
        self.assertEqual(panel._auto_backup_timer.interval(), 60000)
        self.assertTrue(panel._auto_backup_timer.isActive())

        # Disable externally and sync stops active timer
        self.config_manager.set_auto_backup(False)
        panel.sync_auto_backup_settings()
        self.assertFalse(panel.is_auto_backup_enabled())
        self.assertFalse(panel._auto_backup_timer.isActive())

    def test_settings_dialog_auto_backup_delay_control(self) -> None:
        """Verify SettingsDialog Backup page shows delay selector and persists changes."""
        self.config_manager.set_auto_backup_delay_ms(5000)
        dialog = ModernSettingsDialog(self.config_manager)
        signals: list[bool] = []
        dialog.settings_updated.connect(lambda: signals.append(True))

        delay_row = next(
            (row for row in dialog.setting_rows if row.title_lbl.text() == "Auto-Backup Delay"),
            None,
        )
        self.assertIsNotNone(delay_row)
        combo = delay_row.findChild(ModernComboBox)
        self.assertIsNotNone(combo)
        self.assertEqual(combo.currentText(), "5 seconds")

        # Select 1 minute
        target_idx = next(
            i for i, (_, ms) in enumerate(dialog.AUTO_BACKUP_DELAY_OPTIONS) if ms == 60000
        )
        combo.setCurrentIndex(target_idx)
        self.assertEqual(self.config_manager.get_auto_backup_delay_ms(), 60000)
        self.assertTrue(len(signals) >= 1)
        dialog.close()
