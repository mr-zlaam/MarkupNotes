"""Unit tests for folder name validation and hidden folder prevention."""

import tempfile
import unittest
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from core.storage import StorageManager
from ui.dialogs import ModernInputDialog
from ui.theme import DARK_THEME_QSS
from utils.file_validator import MAX_FOLDER_NAME_LENGTH, validate_folder_name


class TestFolderNameValidation(unittest.TestCase):
    """Test suite for folder name validation rules and dialog feedback."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls._orig_style = cls.app.styleSheet()
        cls.app.setStyleSheet(DARK_THEME_QSS)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.app:
            cls.app.setStyleSheet(cls._orig_style)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temp_dir.name)
        self.storage = StorageManager(root_dir=self.root_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_valid_folder_names(self) -> None:
        """Verify normal, sensible folder names pass validation."""
        valid_names = [
            "Projects",
            "Work Notes",
            "Python 3.12",
            "Sprint-1",
            "Docs (2026)",
            "client_work",
            "Test & Debug",
            "Reports [Q4]",
        ]
        for name in valid_names:
            is_valid, err_title, err_msg = validate_folder_name(name)
            self.assertTrue(is_valid, f"Expected '{name}' to be valid")
            self.assertIsNone(err_title)
            self.assertIsNone(err_msg)

    def test_hidden_folder_names_rejected(self) -> None:
        """Verify hidden folder names starting with a dot are strictly rejected."""
        hidden_names = [
            ".folder_name",
            ".hidden",
            "..secret",
            ".config",
            ".trash",
            "  .spaced_hidden",
        ]
        for name in hidden_names:
            is_valid, err_title, err_msg = validate_folder_name(name)
            self.assertFalse(is_valid, f"Expected '{name}' to be rejected")
            self.assertEqual(err_title, "Hidden Folder Not Allowed")
            self.assertIn("cannot start with a dot '.'", err_msg)

    def test_trailing_dot_rejected(self) -> None:
        """Verify folder names ending with a dot are rejected."""
        is_valid, err_title, err_msg = validate_folder_name("folder.")
        self.assertFalse(is_valid)
        self.assertEqual(err_title, "Invalid Folder Name")
        self.assertIn("cannot end with a dot", err_msg)

    def test_empty_and_whitespace_rejected(self) -> None:
        """Verify empty and whitespace-only folder names are rejected."""
        for empty in ["", "   ", "\t", "\n"]:
            is_valid, err_title, err_msg = validate_folder_name(empty)
            self.assertFalse(is_valid)
            self.assertEqual(err_title, "Invalid Folder Name")

    def test_overly_long_folder_names_rejected(self) -> None:
        """Verify folder names exceeding MAX_FOLDER_NAME_LENGTH (50 chars) are rejected."""
        long_name = "a" * (MAX_FOLDER_NAME_LENGTH + 1)
        is_valid, err_title, err_msg = validate_folder_name(long_name)
        self.assertFalse(is_valid)
        self.assertEqual(err_title, "Folder Name Too Long")
        self.assertIn("too long", err_msg)

        # Exact max length passes
        exact_name = "a" * MAX_FOLDER_NAME_LENGTH
        is_valid_exact, _, _ = validate_folder_name(exact_name)
        self.assertTrue(is_valid_exact)

    def test_invalid_filesystem_characters_rejected(self) -> None:
        """Verify forbidden filesystem characters are rejected."""
        invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
        for char in invalid_chars:
            name = f"folder{char}name"
            is_valid, err_title, err_msg = validate_folder_name(name)
            self.assertFalse(is_valid, f"Expected char '{char}' to be rejected")
            self.assertEqual(err_title, "Invalid Characters")

    def test_reserved_system_names_rejected(self) -> None:
        """Verify reserved device names (CON, NUL, AUX, etc.) are rejected."""
        for reserved in ["CON", "prn", "AUX", "NUL", "com1", "lpt1"]:
            is_valid, err_title, err_msg = validate_folder_name(reserved)
            self.assertFalse(is_valid, f"Expected reserved name '{reserved}' to be rejected")
            self.assertEqual(err_title, "Reserved Name")

    def test_storage_create_and_rename_enforces_validation(self) -> None:
        """Verify StorageManager refuses to create or rename hidden or invalid folders."""
        # Reject hidden folder creation
        res = self.storage.create_folder(".hidden_folder")
        self.assertIsNone(res)
        self.assertFalse((self.root_path / ".hidden_folder").exists())

        # Valid folder creates successfully
        valid_folder = self.storage.create_folder("ValidFolder")
        self.assertIsNotNone(valid_folder)
        self.assertTrue(valid_folder.exists())

        # Reject rename to hidden folder
        renamed = self.storage.rename_folder(valid_folder, ".renamed_hidden")
        self.assertIsNone(renamed)
        self.assertTrue(valid_folder.exists())
        self.assertFalse((self.root_path / ".renamed_hidden").exists())

    def test_modern_input_dialog_live_validation(self) -> None:
        """Verify ModernInputDialog provides live feedback and button disabling."""
        dlg = ModernInputDialog(
            title="New Folder",
            prompt="Enter folder name:",
            validator=validate_folder_name,
            max_length=MAX_FOLDER_NAME_LENGTH,
        )

        # Initially empty -> OK button disabled, error label hidden
        self.assertFalse(dlg.ok_btn.isEnabled())
        self.assertTrue(dlg.error_label.isHidden())

        # Type hidden folder name -> OK disabled, error label visible with guidance
        dlg.input_field.setText(".hidden")
        self.assertFalse(dlg.ok_btn.isEnabled())
        self.assertFalse(dlg.error_label.isHidden())
        self.assertIn("cannot start with a dot", dlg.error_label.text())

        # Type valid name -> OK enabled, error label hidden
        dlg.input_field.setText("My Folder")
        self.assertTrue(dlg.ok_btn.isEnabled())
        self.assertTrue(dlg.error_label.isHidden())

        # Max length is enforced on QLineEdit
        dlg.input_field.setText("x" * 100)
        self.assertEqual(len(dlg.input_field.text()), MAX_FOLDER_NAME_LENGTH)

        dlg.close()
        dlg.deleteLater()
