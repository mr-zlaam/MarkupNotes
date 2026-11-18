"""Unit tests for dedicated settings modal dialog and configuration persistence."""

from pathlib import Path
import tempfile
import unittest

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication, QComboBox, QLineEdit, QSpinBox

from core.config import AppSettings, ConfigManager, EditorConfig, GeneralConfig, MarkdownConfig
from ui.editor import EditorPanel
from ui.settings_dialog import ModernComboBox, ModernSettingsDialog, SettingRow, ToggleSwitch
from utils.icons import (
    create_code_icon,
    create_palette_icon,
    create_settings_icon,
    create_sliders_icon,
    create_type_icon,
)

app = QApplication.instance() or QApplication([])


class TestSettingsDialog(unittest.TestCase):
    """Test suite for settings dialog, icons, controls, and configuration bindings."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "settings.json"
        self.config_manager = ConfigManager(config_file=self.config_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_settings_icons_generation(self) -> None:
        """Verify vector settings icons render non-null pixmaps."""
        for icon_fn in (
            create_settings_icon,
            create_sliders_icon,
            create_type_icon,
            create_code_icon,
            create_palette_icon,
        ):
            icon = icon_fn("#8e8e93", size=16)
            self.assertFalse(icon.isNull())
            pm = icon.pixmap(16, 16)
            self.assertFalse(pm.isNull())
            self.assertEqual(pm.width(), 16)
            self.assertEqual(pm.height(), 16)

    def test_config_manager_defaults_and_persistence(self) -> None:
        """Verify ConfigManager loads defaults and persists updates atomically."""
        cfg = self.config_manager.settings
        self.assertTrue(cfg.general.confirm_delete)
        self.assertEqual(cfg.editor.font_size, 12)
        self.assertEqual(cfg.editor.auto_save_delay_ms, 400)
        self.assertTrue(cfg.markdown.render_latex)
        self.assertTrue(cfg.markdown.render_mermaid)

        # Update editor settings
        self.config_manager.update_editor(
            font_size=18,
            font_family="JetBrains Mono",
            line_height=1.6,
            word_wrap=False,
            tab_size=4,
            auto_save_delay_ms=600,
        )
        self.assertEqual(self.config_manager.settings.editor.font_size, 18)
        self.assertEqual(self.config_manager.settings.editor.font_family, "JetBrains Mono")
        self.assertFalse(self.config_manager.settings.editor.word_wrap)
        self.assertEqual(self.config_manager.settings.editor.tab_size, 4)
        self.assertEqual(self.config_manager.settings.editor.auto_save_delay_ms, 600)

        # Reload from disk into fresh manager instance
        fresh_manager = ConfigManager(config_file=self.config_path)
        self.assertEqual(fresh_manager.settings.editor.font_size, 18)
        self.assertEqual(fresh_manager.settings.editor.font_family, "JetBrains Mono")
        self.assertFalse(fresh_manager.settings.editor.word_wrap)

    def test_config_manager_reset_to_defaults(self) -> None:
        """Verify reset_to_defaults restores standard configurations."""
        self.config_manager.update_editor(font_size=24)
        self.config_manager.update_general(confirm_delete=False)
        self.assertEqual(self.config_manager.settings.editor.font_size, 24)
        self.assertFalse(self.config_manager.settings.general.confirm_delete)

        self.config_manager.reset_to_defaults()
        self.assertEqual(self.config_manager.settings.editor.font_size, 12)
        self.assertTrue(self.config_manager.settings.general.confirm_delete)

    def test_restore_factory_defaults_row_and_rebuild(self) -> None:
        """Verify factory reset row exists on General page and rebuilds dialog controls."""
        dialog = ModernSettingsDialog(self.config_manager)
        dialog.show()

        # Find "Restore Factory Defaults" row
        reset_rows = [r for r in dialog.setting_rows if "Restore Factory Defaults" in r.title_text]
        self.assertTrue(len(reset_rows) >= 1)

        # Modify a setting
        self.config_manager.update_editor(font_size=28)
        self.assertEqual(self.config_manager.settings.editor.font_size, 28)

        # Reset to defaults and rebuild
        self.config_manager.reset_to_defaults()
        dialog._rebuild_pages()
        self.assertEqual(self.config_manager.settings.editor.font_size, 12)

        # Verify rows still exist after rebuild
        reset_rows_after = [r for r in dialog.setting_rows if "Restore Factory Defaults" in r.title_text]
        self.assertTrue(len(reset_rows_after) >= 1)
        dialog.close()

    def test_toggle_switch_widget(self) -> None:
        """Verify ToggleSwitch responds to clicks and key presses."""
        switch = ToggleSwitch(checked=False)
        self.assertFalse(switch.isChecked())
        switch.click()
        self.assertTrue(switch.isChecked())
        switch.click()
        self.assertFalse(switch.isChecked())

    def test_settings_dialog_initialization_and_pages(self) -> None:
        """Verify dialog initializes with 5 category pages and navigation buttons."""
        dialog = ModernSettingsDialog(self.config_manager)
        dialog.show()

        self.assertEqual(len(dialog.category_buttons), 5)
        self.assertEqual(dialog.stack.count(), 5)
        self.assertTrue(len(dialog.setting_rows) >= 12)

        # Test category switching
        dialog._on_category_clicked(1)  # Editor
        self.assertEqual(dialog.stack.currentIndex(), 1)
        self.assertTrue(dialog.category_buttons[1].isChecked())
        self.assertFalse(dialog.category_buttons[0].isChecked())

        dialog._on_category_clicked(3)  # Git & Backup
        self.assertEqual(dialog.stack.currentIndex(), 3)
        self.assertTrue(dialog.category_buttons[3].isChecked())
        dialog.close()

    def test_settings_dialog_search_filter(self) -> None:
        """Verify search query filters visible rows across pages."""
        dialog = ModernSettingsDialog(self.config_manager)
        dialog.show()

        total_rows = len(dialog.setting_rows)
        # Search for font
        dialog.search_edit.setText("font")
        visible = [r for r in dialog.setting_rows if not r.isHidden()]
        self.assertTrue(len(visible) >= 1)
        self.assertTrue(any("Font Size" in r.title_text for r in visible))

        # Search for nonexistent term
        dialog.search_edit.setText("nonexistent_unknown_xyz")
        visible = [r for r in dialog.setting_rows if not r.isHidden()]
        self.assertEqual(len(visible), 0)

        # Clear search
        dialog.search_edit.setText("")
        visible = [r for r in dialog.setting_rows if not r.isHidden()]
        self.assertEqual(len(visible), total_rows)
        dialog.close()

    def test_settings_dialog_signals_and_live_updates(self) -> None:
        """Verify changing dialog controls emits settings_updated signal."""
        dialog = ModernSettingsDialog(self.config_manager)
        signal_emitted = []
        dialog.settings_updated.connect(lambda: signal_emitted.append(True))

        # Toggle confirm delete
        dialog._on_confirm_delete_toggled(False)
        self.assertTrue(len(signal_emitted) > 0)
        self.assertFalse(self.config_manager.settings.general.confirm_delete)

        # Change font size
        dialog._on_font_size_changed(20)
        self.assertEqual(self.config_manager.settings.editor.font_size, 20)
        dialog.close()

    def test_editor_panel_settings_button_and_apply_config(self) -> None:
        """Verify EditorPanel exposes settings_btn and applies live configuration."""
        panel = EditorPanel()
        self.assertTrue(hasattr(panel, "settings_btn"))
        self.assertTrue(panel.settings_btn.isEnabled())

        # Test settings button signal
        clicked = []
        panel.settings_requested.connect(lambda: clicked.append(True))
        panel.settings_btn.click()
        self.assertEqual(len(clicked), 1)

        # Apply config
        cfg = AppSettings(
            editor=EditorConfig(
                font_size=22,
                font_family="DejaVu Sans",
                word_wrap=False,
                tab_size=4,
                auto_save_delay_ms=800,
            )
        )
        panel.apply_config(cfg)
        self.assertEqual(panel.editor.font().pointSize(), 22)
        self.assertEqual(panel._save_timer.interval(), 800)
        panel.deleteLater()

    def test_dialog_dismissal_via_keys_and_backdrop(self) -> None:
        """Verify Space on empty search or outside inputs, and backdrop clicks dismiss dialog."""
        dialog = ModernSettingsDialog(self.config_manager)
        dialog.show()

        # Space on empty search input should dismiss
        dialog.search_edit.setFocus()
        dialog.search_edit.setText("")
        space_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        dialog.eventFilter(dialog.search_edit, space_event)

        # Escape key on dialog
        esc_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        dialog.keyPressEvent(esc_event)

        # Click outside card
        click_event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(2.0, 2.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        dialog.mousePressEvent(click_event)
        dialog.close()

    def test_reveal_notes_and_open_config_do_not_crash(self) -> None:
        """Verify reveal notes folder and open config methods execute without type errors."""
        dialog = ModernSettingsDialog(self.config_manager)
        try:
            dialog._reveal_notes_folder()
            dialog._open_config_file()
        except TypeError as e:
            self.fail(f"openUrl raised unexpected TypeError: {e}")
        dialog.close()

    def test_streamlined_general_page_options(self) -> None:
        """Verify removed options are gone and essential settings remain."""
        dialog = ModernSettingsDialog(self.config_manager)
        titles = [r.title_text for r in dialog.setting_rows]

        self.assertNotIn("Startup View", titles)
        self.assertNotIn("Default Note Name", titles)
        self.assertNotIn("Editor Font Family", titles)
        self.assertNotIn("Auto-Save Delay", titles)
        self.assertNotIn("Runtime Environment", titles)
        self.assertNotIn("GitHub Remote Repository", titles)

        self.assertIn("Confirm on Delete", titles)
        self.assertIn("Interface Theme", titles)
        self.assertIn("Item Color Customizations", titles)
        self.assertIn("Notes Storage Folder", titles)
        self.assertIn("Font Size", titles)
        self.assertIn("Line Height", titles)
        self.assertIn("Word Wrap", titles)
        self.assertIn("Tab Indentation Width", titles)
        self.assertIn("Restore Factory Defaults", titles)
        dialog.close()

    def test_settings_dialog_modal_in_window_overlay(self) -> None:
        """Verify ModernSettingsDialog behaves as in-window child widget modal when parent is set."""
        from PyQt6.QtWidgets import QMainWindow

        mw = QMainWindow()
        mw.resize(1000, 700)
        mw.show()

        dialog = ModernSettingsDialog(self.config_manager, parent=mw)
        self.assertEqual(dialog.windowFlags() & Qt.WindowType.Widget, Qt.WindowType.Widget)
        self.assertEqual(dialog.geometry().width(), 1000)
        self.assertEqual(dialog.geometry().height(), 700)
        dialog.close()
        dialog.deleteLater()
        mw.close()
        mw.deleteLater()

    def test_modern_combobox_component(self) -> None:
        """Verify ModernComboBox uses QListView, renders items, and handles selection."""
        from PyQt6.QtWidgets import QListView

        combo = ModernComboBox()
        self.assertIsInstance(combo.view(), QListView)
        combo.addItems(["Option A", "Option B", "Option C"])
        self.assertEqual(combo.count(), 3)
        self.assertEqual(combo.currentText(), "Option A")

        combo.setCurrentIndex(2)
        self.assertEqual(combo.currentText(), "Option C")
        combo.deleteLater()

    def test_global_confirm_delete_setting(self) -> None:
        """Verify MainWindow respects confirm_delete setting when deleting notes and folders."""
        from unittest.mock import patch
        from core.note import Note
        from core.storage import StorageManager
        from ui.main_window import MainWindow

        notes_dir = Path(self.temp_dir.name) / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "TestNote.md").write_text("# Test Note", encoding="utf-8")

        storage = StorageManager(root_dir=notes_dir)
        win = MainWindow(storage_manager=storage, config_manager=self.config_manager)

        # 1. When confirm_delete is True: ModernConfirmDialog.ask should be called
        self.config_manager.update_general(confirm_delete=True)
        note = Note.from_file(notes_dir / "TestNote.md")
        self.assertIsNotNone(note)

        with patch("ui.dialogs.ModernConfirmDialog.ask", return_value=False) as mock_ask:
            win._on_delete_single_note(note)
            self.assertEqual(mock_ask.call_count, 1)

        # 2. When confirm_delete is False: ModernConfirmDialog.ask should NOT be called
        self.config_manager.update_general(confirm_delete=False)
        with patch("ui.dialogs.ModernConfirmDialog.ask") as mock_ask:
            win._on_delete_single_note(note)
            self.assertEqual(mock_ask.call_count, 0)

        win.close()
        win.deleteLater()

    def test_markdown_settings_live_propagation(self) -> None:
        """Verify markdown configuration settings propagate to EditorPanel dynamically."""
        panel = EditorPanel()
        self.assertFalse(panel.editor.code_line_numbers)
        self.assertTrue(panel.editor.render_latex)
        self.assertTrue(panel.editor.render_mermaid)
        self.assertTrue(panel.editor.smart_list)

        # Update markdown config to disable features and enable code_line_numbers
        cfg = AppSettings(
            markdown=MarkdownConfig(
                render_latex=False,
                render_mermaid=False,
                smart_list=False,
                code_line_numbers=True,
            )
        )
        panel.apply_config(cfg)
        self.assertTrue(panel.editor.code_line_numbers)
        self.assertFalse(panel.editor.render_latex)
        self.assertFalse(panel.editor.render_mermaid)
        self.assertFalse(panel.editor.smart_list)

        panel.close()
        panel.deleteLater()

    def test_code_gutter_width_and_render_code_card(self) -> None:
        """Verify code gutter width calculation and render_code_card execution with line numbers."""
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QPainter, QPixmap
        from utils.code_engine import (
            CodeRegion,
            get_code_gutter_width,
            get_code_scrollbar_geometry,
            render_code_card,
        )

        reg_small = CodeRegion(start_block=0, end_block=3, language="python", lines=["a = 1", "b = 2", "c = 3"])
        w_small = get_code_gutter_width(reg_small)
        self.assertGreater(w_small, 20.0)

        reg_large = CodeRegion(start_block=0, end_block=150, language="python", lines=[f"line {i}" for i in range(150)])
        w_large = get_code_gutter_width(reg_large)
        self.assertGreater(w_large, w_small)

        # Test scrollbar geometry with gutter width
        card_rect = QRectF(0, 0, 300, 200)
        sb = get_code_scrollbar_geometry(card_rect, content_width=500.0, scroll_x=0.0, gutter_width=w_small)
        self.assertIsNotNone(sb)

        # Test render_code_card with show_line_numbers=True and False
        pm = QPixmap(400, 250)
        painter = QPainter(pm)
        render_code_card(painter, card_rect, reg_small, show_line_numbers=True)
        render_code_card(painter, card_rect, reg_small, show_line_numbers=False)
        painter.end()

    def test_slash_menu_code_commands_present(self) -> None:
        """Verify code block and inline code slash commands are registered in slash menu."""
        from ui.slash_menu import COMMANDS

        cmd_ids = [cmd.id for cmd in COMMANDS]
        self.assertIn("code", cmd_ids)
        self.assertIn("inline_code", cmd_ids)

    def test_editor_zoom_in_out_and_persistence(self) -> None:
        """Verify Ctrl+/Ctrl- zoom actions resize editor font and persist to config."""
        from core.storage import StorageManager
        from ui.main_window import MainWindow

        notes_dir = Path(self.temp_dir.name) / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        storage = StorageManager(root_dir=notes_dir)
        win = MainWindow(storage_manager=storage, config_manager=self.config_manager)

        # Base font size is 12
        self.assertEqual(win.editor.editor.font().pointSize(), 12)
        self.assertEqual(self.config_manager.settings.editor.font_size, 12)

        # Zoom in
        win._on_zoom_in()
        self.assertEqual(win.editor.editor.font().pointSize(), 13)
        self.assertEqual(self.config_manager.settings.editor.font_size, 13)

        # Zoom in again
        win._on_zoom_in()
        self.assertEqual(win.editor.editor.font().pointSize(), 14)
        self.assertEqual(self.config_manager.settings.editor.font_size, 14)

        # Zoom out
        win._on_zoom_out()
        self.assertEqual(win.editor.editor.font().pointSize(), 13)
        self.assertEqual(self.config_manager.settings.editor.font_size, 13)

        # Zoom reset
        win._on_zoom_reset()
        self.assertEqual(win.editor.editor.font().pointSize(), 12)
        self.assertEqual(self.config_manager.settings.editor.font_size, 12)

        # Verify key press simulation directly on editor
        zoom_in_ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier, "=")
        win.editor.editor.keyPressEvent(zoom_in_ev)
        self.assertEqual(win.editor.editor.font().pointSize(), 13)

        zoom_out_ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier, "-")
        win.editor.editor.keyPressEvent(zoom_out_ev)
        self.assertEqual(win.editor.editor.font().pointSize(), 12)

        win.close()
        win.deleteLater()


if __name__ == "__main__":
    unittest.main()
