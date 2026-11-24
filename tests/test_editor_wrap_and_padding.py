"""Unit tests for editor horizontal padding setting and Alt+W word wrap toggle."""

from pathlib import Path
import tempfile
import unittest

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QTextEdit

from core.config import AppSettings, ConfigManager, EditorConfig, GeneralConfig
from ui.editor import EditorPanel, MarkdownEditor
from ui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


class TestEditorWrapAndPadding(unittest.TestCase):
    """Test suite for editor horizontal padding configuration and word wrap toggle."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.config_file = Path(self.tmp_dir.name) / "settings.json"
        self.config_manager = ConfigManager(config_file=self.config_file)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_horizontal_padding_config_persistence(self) -> None:
        """Verify horizontal_padding defaults to 36 and updates correctly."""
        self.assertEqual(self.config_manager.settings.editor.horizontal_padding, 36)

        self.config_manager.update_editor(horizontal_padding=64)
        self.assertEqual(self.config_manager.settings.editor.horizontal_padding, 64)

        # Fresh instance reading from persisted JSON
        fresh_cm = ConfigManager(config_file=self.config_file)
        self.assertEqual(fresh_cm.settings.editor.horizontal_padding, 64)

    def test_editor_panel_applies_horizontal_padding(self) -> None:
        """Verify apply_config applies horizontal padding to note title and editor."""
        panel = EditorPanel()
        cfg = AppSettings(
            editor=EditorConfig(
                horizontal_padding=72,
            )
        )
        panel.apply_config(cfg)

        # Check stylesheet of title_edit and editor contains 72px
        self.assertIn("72px", panel.title_edit.styleSheet())
        self.assertIn("72px", panel.editor.styleSheet())

        # Test with UI scale factor
        cfg_scaled = AppSettings(
            general=GeneralConfig(ui_scale=1.5),
            editor=EditorConfig(horizontal_padding=72),
        )
        panel.apply_config(cfg_scaled, ui_scale=1.5)
        expected_scaled = str(int(round(72 * 1.5)))
        self.assertIn(f"{expected_scaled}px", panel.title_edit.styleSheet())
        self.assertIn(f"{expected_scaled}px", panel.editor.styleSheet())

    def test_markdown_editor_toggle_word_wrap_method(self) -> None:
        """Verify toggle_word_wrap switches mode and emits word_wrap_toggled."""
        editor = MarkdownEditor()
        editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)

        emitted: list[bool] = []
        editor.word_wrap_toggled.connect(emitted.append)

        # Toggle to NoWrap
        res = editor.toggle_word_wrap()
        self.assertFalse(res)
        self.assertEqual(editor.lineWrapMode(), QTextEdit.LineWrapMode.NoWrap)
        self.assertEqual(emitted, [False])

        # Toggle back to WidgetWidth
        res2 = editor.toggle_word_wrap()
        self.assertTrue(res2)
        self.assertEqual(editor.lineWrapMode(), QTextEdit.LineWrapMode.WidgetWidth)
        self.assertEqual(emitted, [False, True])

    def test_markdown_editor_alt_w_key_event(self) -> None:
        """Verify Alt+W key press event triggers toggle_word_wrap."""
        editor = MarkdownEditor()
        editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)

        emitted: list[bool] = []
        editor.word_wrap_toggled.connect(emitted.append)

        # Send Alt+W event
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_W,
            Qt.KeyboardModifier.AltModifier,
            "w",
        )
        editor.keyPressEvent(event)
        self.assertEqual(editor.lineWrapMode(), QTextEdit.LineWrapMode.NoWrap)
        self.assertEqual(emitted, [False])

        # Send Alt+W event again
        editor.keyPressEvent(event)
        self.assertEqual(editor.lineWrapMode(), QTextEdit.LineWrapMode.WidgetWidth)
        self.assertEqual(emitted, [False, True])

    def test_editor_panel_word_wrap_signal_propagation(self) -> None:
        """Verify EditorPanel forwards word_wrap_toggled from MarkdownEditor."""
        panel = EditorPanel()
        panel.editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)

        emitted: list[bool] = []
        panel.word_wrap_toggled.connect(emitted.append)

        res = panel.toggle_word_wrap()
        self.assertFalse(res)
        self.assertEqual(emitted, [False])

    def test_main_window_word_wrap_persistence(self) -> None:
        """Verify word wrap toggling from MainWindow updates config manager."""
        from core.storage import StorageManager

        win = MainWindow(
            storage_manager=StorageManager(self.config_manager.config_path.parent / "vault"),
            config_manager=self.config_manager,
        )
        self.assertTrue(self.config_manager.settings.editor.word_wrap)

        # Toggle word wrap via editor
        win.editor.toggle_word_wrap()
        self.assertFalse(self.config_manager.settings.editor.word_wrap)

        # Toggle again
        win.editor.toggle_word_wrap()
        self.assertTrue(self.config_manager.settings.editor.word_wrap)

        win.close()
        win.deleteLater()

    def test_editor_scaling_with_padding(self) -> None:
        """Verify editor text and padding scale proportionally with ui_scale."""
        panel = EditorPanel()
        for scale in (1.0, 1.25, 1.5, 2.0):
            cfg = AppSettings(
                general=GeneralConfig(ui_scale=scale),
                editor=EditorConfig(font_size=12, horizontal_padding=36),
            )
            panel.apply_config(cfg, ui_scale=scale)
            expected_font = max(8, int(round(12 * scale)))
            expected_pad = max(8, int(round(36 * scale)))

            self.assertEqual(panel.editor.font().pointSize(), expected_font)
            self.assertEqual(panel.editor._horizontal_padding, expected_pad)
            self.assertIn(f"{expected_pad}px", panel.editor.styleSheet())
            self.assertIn(f"{expected_font}pt", panel.editor.styleSheet())


if __name__ == "__main__":
    unittest.main()
