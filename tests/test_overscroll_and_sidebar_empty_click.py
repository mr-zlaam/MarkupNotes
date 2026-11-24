"""Unit tests for editor scroll-past-end bottom padding and sidebar empty-space clicks."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QTextCursor
from PyQt6.QtWidgets import QApplication

from ui.editor import MarkdownEditor
from ui.sidebar import FolderSidebar

app = QApplication.instance() or QApplication([])


class TestOverscrollAndSidebarEmptyClick(unittest.TestCase):
    """Verify editor bottom overscroll to center and sidebar empty-space click behavior."""

    def test_editor_scrolls_last_line_to_center_without_false_text_changed(self) -> None:
        """Verify long documents can scroll their last line up to vertical center without firing textChanged."""
        editor = MarkdownEditor()
        editor.resize(640, 500)
        editor.show()
        app.processEvents()

        lines = [f"Line {i}" for i in range(1, 81)]
        content = "\n".join(lines)
        editor.setPlainText(content)
        app.processEvents()

        text_changed_calls: list[bool] = []
        editor.textChanged.connect(lambda: text_changed_calls.append(True))

        # Resizing should update bottom overscroll margin without emitting textChanged
        editor.resize(640, 600)
        app.processEvents()
        self.assertEqual(text_changed_calls, [])

        vp_h = editor.viewport().height()
        bottom_margin = editor.document().rootFrame().frameFormat().bottomMargin()
        self.assertAlmostEqual(bottom_margin, vp_h // 2, delta=2.0)

        # Scroll all the way to the bottom and verify the last line sits near/above vertical center
        vbar = editor.verticalScrollBar()
        self.assertGreater(vbar.maximum(), 0)
        vbar.setValue(vbar.maximum())
        app.processEvents()

        end_cursor = editor.textCursor()
        end_cursor.movePosition(QTextCursor.MoveOperation.End)
        last_line_rect = editor.cursorRect(end_cursor)
        self.assertLessEqual(last_line_rect.top(), int(vp_h * 0.58))
        self.assertEqual(editor.toPlainText(), content)

        editor.deleteLater()

    def test_sidebar_empty_space_click_keeps_focused_folder(self) -> None:
        """Verify clicking empty space in the folder sidebar does not switch focus to All Notes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work_dir = root / "Work"
            work_dir.mkdir()

            sidebar = FolderSidebar()
            sidebar.resize(260, 500)
            sidebar.show()
            sidebar.set_folders([work_dir], current_selection=work_dir)
            app.processEvents()

            emitted: list[object] = []
            sidebar.folder_selected.connect(emitted.append)

            # Confirm 'Work' is currently selected
            current_item = sidebar.tree_widget.currentItem()
            self.assertIsNotNone(current_item)
            self.assertEqual(current_item.data(0, Qt.ItemDataRole.UserRole), work_dir)

            # Left-click in empty space near bottom of tree viewport
            empty_pos = QPointF(80.0, float(sidebar.tree_widget.viewport().height() - 20))
            self.assertIsNone(sidebar.tree_widget.itemAt(empty_pos.toPoint()))
            left_press = QMouseEvent(
                QEvent.Type.MouseButtonPress,
                empty_pos,
                empty_pos,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(sidebar.tree_widget.viewport(), left_press)
            app.processEvents()

            self.assertEqual(emitted, [])
            self.assertEqual(
                sidebar.tree_widget.currentItem().data(0, Qt.ItemDataRole.UserRole),
                work_dir,
            )

            # Left-click on sidebar margins outside tree
            margin_press = QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(5.0, 5.0),
                QPointF(5.0, 5.0),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            sidebar.mousePressEvent(margin_press)
            app.processEvents()

            self.assertEqual(emitted, [])
            self.assertEqual(
                sidebar.tree_widget.currentItem().data(0, Qt.ItemDataRole.UserRole),
                work_dir,
            )

            sidebar.deleteLater()

    def test_sidebar_empty_space_right_click_new_folder_creates_root_folder(self) -> None:
        """Verify right-clicking empty space creates a root parent folder even when a folder is focused."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work_dir = root / "Work"
            work_dir.mkdir()

            sidebar = FolderSidebar()
            sidebar.resize(260, 500)
            sidebar.show()
            sidebar.set_folders([work_dir], current_selection=work_dir)
            app.processEvents()

            folder_selected_events: list[object] = []
            created_folders: list[tuple[str, object]] = []
            sidebar.folder_selected.connect(folder_selected_events.append)
            sidebar.create_folder_requested.connect(
                lambda name, parent: created_folders.append((name, parent))
            )

            empty_pos = QPoint(80, sidebar.tree_widget.viewport().height() - 20)
            self.assertIsNone(sidebar.tree_widget.itemAt(empty_pos))

            # Simulate choosing "New Folder..." from empty-space context menu
            from ui.context_menu import ModernContextMenu

            class _AutoNewFolderMenu(ModernContextMenu):
                def exec(self, *_args, **_kwargs):
                    return self.actions()[0]

            with (
                patch("ui.sidebar.ModernContextMenu", _AutoNewFolderMenu),
                patch("ui.sidebar.ModernInputDialog.get_text", return_value=("Projects", True)),
            ):
                sidebar._on_context_menu(empty_pos)

            # Should NOT have switched focus to All Notes
            self.assertEqual(folder_selected_events, [])
            self.assertEqual(
                sidebar.tree_widget.currentItem().data(0, Qt.ItemDataRole.UserRole),
                work_dir,
            )
            # Should create 'Projects' at root (parent=None), NOT inside 'Work'
            self.assertEqual(created_folders, [("Projects", None)])

            sidebar.deleteLater()


if __name__ == "__main__":
    unittest.main()
