"""Sidebar widget displaying folders tree hierarchy, navigation categories, and folder management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Set

from PyQt6.QtCore import QEvent, QMimeData, QModelIndex, QObject, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScroller,
    QStackedWidget,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.context_menu import ModernContextMenu
from ui.dialogs import ModernColorDialog, ModernInputDialog
from ui.note_list import MIME_WORKSPACE_ITEM
from utils.file_validator import MAX_FOLDER_NAME_LENGTH, validate_folder_name
from utils.paths import (
    classify_dropped_local_paths,
    collect_ancestors_in_set,
    collect_folder_and_descendants,
    extract_local_paths_from_mime,
    should_accept_external_file_drag,
)
from utils.sorting import DEFAULT_SORT_ORDER, normalize_sort_order, sort_folders
from utils.icons import (
    PRESET_COLORS,
    create_all_notes_icon,
    create_check_icon,
    create_checkbox_icon,
    create_close_icon,
    create_collapse_all_icon,
    create_color_circle_icon,
    create_copy_icon,
    create_cut_icon,
    create_edit_icon,
    create_folder_icon,
    create_open_folder_icon,
    create_paste_icon,
    create_pin_icon,
    create_plus_icon,
    create_sidebar_toggle_icon,
    create_trash_icon,
    create_uncheck_icon,
)


class _DraggableFolderTreeWidget(QTreeWidget):
    """QTreeWidget supporting dragging folders and dropping notes/folders onto targets."""

    def __init__(self, sidebar: "FolderSidebar") -> None:
        super().__init__(parent=sidebar)
        self._sidebar = sidebar
        self._drop_target_item: Optional[QTreeWidgetItem] = None
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        if self._sidebar.is_selection_mode:
            return
        item = self.currentItem()
        if item is None:
            return
        folder: Optional[Path] = item.data(0, Qt.ItemDataRole.UserRole)
        if folder is None:
            return

        mime = QMimeData()
        payload = json.dumps({"kind": "folder", "path": str(folder)}).encode("utf-8")
        mime.setData(MIME_WORKSPACE_ITEM, payload)

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(
            Qt.DropAction.MoveAction | Qt.DropAction.CopyAction,
            Qt.DropAction.MoveAction,
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._sidebar.is_selection_mode:
            event.ignore()
            return
        if event.mimeData().hasFormat(MIME_WORKSPACE_ITEM):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                event.setDropAction(Qt.DropAction.CopyAction)
            else:
                event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        if should_accept_external_file_drag(event.mimeData(), allow_images=False):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._sidebar.is_selection_mode:
            event.ignore()
            return
        accepted = False
        if event.mimeData().hasFormat(MIME_WORKSPACE_ITEM):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                event.setDropAction(Qt.DropAction.CopyAction)
            else:
                event.setDropAction(Qt.DropAction.MoveAction)
            accepted = True
        elif should_accept_external_file_drag(event.mimeData(), allow_images=False):
            event.setDropAction(Qt.DropAction.CopyAction)
            accepted = True
        if not accepted:
            event.ignore()
            return
        hovered = self.itemAt(event.position().toPoint())
        if hovered is not self._drop_target_item:
            self._drop_target_item = hovered
            self.viewport().update()
        event.accept()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        if self._drop_target_item is not None:
            self._drop_target_item = None
            self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._drop_target_item = None
        self.viewport().update()
        if self._sidebar.is_selection_mode:
            event.ignore()
            return

        target_item = self.itemAt(event.position().toPoint())
        target_folder: Optional[Path] = (
            target_item.data(0, Qt.ItemDataRole.UserRole)
            if target_item is not None
            else None
        )

        if event.mimeData().hasFormat(MIME_WORKSPACE_ITEM):
            try:
                raw = bytes(event.mimeData().data(MIME_WORKSPACE_ITEM)).decode("utf-8")
                payload = json.loads(raw)
                kind = str(payload.get("kind", ""))
                src_path = Path(str(payload.get("path", "")))
            except (ValueError, TypeError, OSError):
                event.ignore()
                return

            if kind not in ("note", "folder") or not str(src_path):
                event.ignore()
                return

            is_copy = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier) or (
                event.dropAction() == Qt.DropAction.CopyAction
            )
            event.acceptProposedAction()
            self._sidebar.item_drop_requested.emit(kind, src_path, target_folder, is_copy)
            return

        local_paths = extract_local_paths_from_mime(event.mimeData())
        if local_paths:
            md_files, _ = classify_dropped_local_paths(local_paths)
            if md_files:
                event.acceptProposedAction()
                self._sidebar.external_files_dropped.emit(md_files, target_folder)
                return

        event.ignore()


class _FolderTreeDelegate(QStyledItemDelegate):
    """Item delegate rendering a subtle pin badge on pinned folder rows."""

    def __init__(self, sidebar: "FolderSidebar") -> None:
        super().__init__(sidebar)
        self._sidebar = sidebar

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        folder: Optional[Path] = index.data(Qt.ItemDataRole.UserRole)
        is_cut = folder is not None and self._sidebar._cut_path == folder
        is_drop_target = (
            self._sidebar.tree_widget._drop_target_item is not None
            and self._sidebar.tree_widget.indexFromItem(
                self._sidebar.tree_widget._drop_target_item
            )
            == index
        )
        if is_cut:
            painter.save()
            painter.setOpacity(0.5)
        super().paint(painter, option, index)
        if is_cut:
            painter.restore()
        if is_drop_target:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(QColor("#0a84ff"), 1.5))
            painter.setBrush(QColor(10, 132, 255, 36))
            painter.drawRoundedRect(option.rect.adjusted(2, 1, -2, -1), 5, 5)
            painter.restore()
        if folder is not None and not self._sidebar.is_selection_mode and self._sidebar.is_folder_pinned(folder):
            icon_sz = max(11, int(round(12 * self._sidebar.ui_scale)))
            x = option.rect.right() - icon_sz - 8
            y = option.rect.top() + (option.rect.height() - icon_sz) // 2
            pin_icon = create_pin_icon(pinned=True, color="#ff9f0a", size=icon_sz)
            pin_icon.paint(painter, QRect(x, y, icon_sz, icon_sz))


class FolderSidebar(QWidget):
    """Left sidebar widget displaying folder hierarchy tree for notes with subfolder creation."""

    # Signal emitted when a folder is selected. None represents 'All Notes'.
    folder_selected = pyqtSignal(object)
    # Signal emitted when user requests a new folder or subfolder: (folder_name, parent_folder_or_None)
    create_folder_requested = pyqtSignal(str, object)
    # Signal emitted when user clicks the sidebar collapse button
    collapse_requested = pyqtSignal()
    # Folder management signals
    rename_folder_requested = pyqtSignal(object)  # Emits Path
    delete_folder_requested = pyqtSignal(object)  # Emits Path
    delete_folders_batch_requested = pyqtSignal(list)  # Emits List[Path]
    select_all_notes_requested = pyqtSignal()
    folder_color_changed = pyqtSignal(str, object)  # Emits (folder_name, hex_color_or_None)
    folder_expansion_changed = pyqtSignal()
    pin_folder_requested = pyqtSignal(object)  # Emits Path
    item_drop_requested = pyqtSignal(str, object, object, bool)  # (kind, src_path, target_folder_or_None, is_copy)
    cut_folder_requested = pyqtSignal(object)  # Emits Path
    copy_folder_requested = pyqtSignal(object)  # Emits Path
    paste_into_folder_requested = pyqtSignal(object)  # Emits Optional[Path] (None = root)
    undo_file_op_requested = pyqtSignal()
    cancel_clipboard_requested = pyqtSignal()
    external_files_dropped = pyqtSignal(list, object)  # (List[Path], Optional[Path] target_folder)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent=parent)
        self.ui_scale: float = 1.0
        self._folders: List[Path] = []
        self._root_dir: Optional[Path] = None
        self._collapsed_keys: Set[str] = set()
        self._pinned_keys: List[str] = []
        self._sort_order: str = DEFAULT_SORT_ORDER
        self._is_selection_mode: bool = False
        self._selected_folders: Set[Path] = set()
        self._pre_selection_folder: Optional[Path] = None
        self._folder_colors: Dict[str, str] = {}
        self._has_clipboard: bool = False
        self._cut_path: Optional[Path] = None
        self._init_ui()

    def set_clipboard_state(
        self, has_clipboard: bool, cut_path: Optional[Path] = None
    ) -> None:
        """Update visual cut dimming and Paste menu availability."""
        self._has_clipboard = bool(has_clipboard)
        self._cut_path = cut_path
        self.tree_widget.viewport().update()

    def set_sort_order(self, sort_order: str, current_selection: Optional[Path] = None) -> None:
        """Update folder tree sort order and re-render all hierarchy levels."""
        normalized = normalize_sort_order(sort_order)
        if self._sort_order == normalized:
            return
        self._sort_order = normalized
        self._update_folder_items(current_selection)

    def set_folder_colors(self, colors: Dict[str, str]) -> None:
        """Update cached folder colors and refresh UI."""
        self._folder_colors = dict(colors)
        self._update_folder_items()

    def set_ui_scale(self, scale: float) -> None:
        """Update UI scaling factor for sidebar tree and header."""
        self.ui_scale = scale
        self.header_stack.setFixedHeight(max(26, int(round(34 * scale))))
        icon_dim = max(14, int(round(18 * scale)))
        self.tree_widget.setIconSize(QSize(icon_dim, icon_dim))
        self.tree_widget.setIndentation(max(12, int(round(16 * scale))))
        self.tree_widget.doItemsLayout()
        self.tree_widget.viewport().update()

    @property
    def is_selection_mode(self) -> bool:
        return self._is_selection_mode

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(6)

        # Header Stack: Normal header vs. Batch selection header
        self.header_stack = QStackedWidget(parent=self)
        self.header_stack.setFixedHeight(34)

        # 1. Normal Header with title, "New Folder" (+) button, and sidebar collapse button
        normal_header_widget = QWidget(parent=self.header_stack)
        header_layout = QHBoxLayout(normal_header_widget)
        header_layout.setContentsMargins(10, 4, 6, 4)
        header_layout.setSpacing(4)

        title_label = QLabel("Folders", parent=normal_header_widget)
        title_label.setStyleSheet(
            "font-weight: 600; color: #888888; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;"
        )
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # Clean vector + icon for new folder
        self.add_folder_btn = QPushButton(parent=normal_header_widget)
        self.add_folder_btn.setObjectName("IconButton")
        self.add_folder_btn.setIcon(create_plus_icon("#8e8e93", size=14))
        self.add_folder_btn.setToolTip("New Folder (Ctrl+Shift+N)")
        self.add_folder_btn.setFixedSize(26, 26)
        self.add_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_folder_btn.clicked.connect(lambda: self._on_add_folder_clicked(force_root=False))
        header_layout.addWidget(self.add_folder_btn)

        # Single toggle button to collapse or expand all folders (VS Code Explorer style)
        self.collapse_all_btn = QPushButton(parent=normal_header_widget)
        self.collapse_all_btn.setObjectName("IconButton")
        self.collapse_all_btn.setIcon(create_collapse_all_icon(collapsed=False, color="#8e8e93", size=15))
        self.collapse_all_btn.setToolTip("Collapse All Folders (Ctrl+Left)")
        self.collapse_all_btn.setFixedSize(26, 26)
        self.collapse_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_all_btn.clicked.connect(self.toggle_collapse_all_folders)
        header_layout.addWidget(self.collapse_all_btn)

        # Domain-owned collapse button for Folders
        self.collapse_btn = QPushButton(parent=normal_header_widget)
        self.collapse_btn.setObjectName("IconButton")
        self.collapse_btn.setIcon(create_sidebar_toggle_icon("#8e8e93", size=15))
        self.collapse_btn.setToolTip("Collapse Folders (Ctrl+\\)")
        self.collapse_btn.setFixedSize(26, 26)
        self.collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_btn.clicked.connect(self.collapse_requested.emit)
        header_layout.addWidget(self.collapse_btn)

        self.header_stack.addWidget(normal_header_widget)

        # 2. Batch Header for Folders
        batch_header_widget = QWidget(parent=self.header_stack)
        batch_layout = QHBoxLayout(batch_header_widget)
        batch_layout.setContentsMargins(6, 2, 4, 2)
        batch_layout.setSpacing(4)

        self.select_count_label = QLabel("0 selected", parent=batch_header_widget)
        self.select_count_label.setStyleSheet("font-size: 11px; font-weight: 600; color: #a8a8b0;")
        batch_layout.addWidget(self.select_count_label)

        self.select_all_btn = QPushButton("Select All", parent=batch_header_widget)
        self.select_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #2c2c30;
                color: #e0e0e0;
                font-size: 10px;
                font-weight: 500;
                border: 1px solid #3c3c44;
                border-radius: 4px;
                padding: 2px 5px;
            }
            QPushButton:hover {
                background-color: #383840;
                color: #ffffff;
            }
        """)
        self.select_all_btn.setToolTip("Select or deselect all folders")
        self.select_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_all_btn.clicked.connect(self._on_toggle_select_all)
        batch_layout.addWidget(self.select_all_btn)

        batch_layout.addStretch()

        # Vector trash icon button for batch delete
        self.batch_delete_btn = QPushButton(parent=batch_header_widget)
        self.batch_delete_btn.setObjectName("IconButton")
        self.batch_delete_btn.setIcon(create_trash_icon("#e03e3e", size=15))
        self.batch_delete_btn.setFixedSize(24, 24)
        self.batch_delete_btn.setToolTip("Delete selected folders")
        self.batch_delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.batch_delete_btn.setEnabled(False)
        self.batch_delete_btn.clicked.connect(self._on_batch_delete_clicked)
        batch_layout.addWidget(self.batch_delete_btn)

        # Vector close/cross icon button for cancel
        self.cancel_btn = QPushButton(parent=batch_header_widget)
        self.cancel_btn.setObjectName("IconButton")
        self.cancel_btn.setIcon(create_close_icon("#8e8e93", size=15))
        self.cancel_btn.setFixedSize(24, 24)
        self.cancel_btn.setToolTip("Cancel selection (Esc)")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.exit_selection_mode)
        batch_layout.addWidget(self.cancel_btn)

        self.header_stack.addWidget(batch_header_widget)
        layout.addWidget(self.header_stack, 0)

        # Folder Tree Widget
        self.tree_widget = _DraggableFolderTreeWidget(self)
        self.tree_widget.setObjectName("SidebarTree")
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setIndentation(16)
        self.tree_widget.setAnimated(True)
        self.tree_widget.setIconSize(QSize(18, 18))
        self.tree_widget.setCursor(Qt.CursorShape.ArrowCursor)
        self.tree_widget.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self.tree_widget.setMouseTracking(True)
        self.tree_widget.viewport().setMouseTracking(True)
        self.tree_widget.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.tree_widget.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        QScroller.grabGesture(
            self.tree_widget.viewport(), QScroller.ScrollerGestureType.TouchGesture
        )

        self.tree_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree_widget.itemClicked.connect(self._on_item_clicked)
        self.tree_widget.itemExpanded.connect(self._on_item_expanded)
        self.tree_widget.itemCollapsed.connect(self._on_item_collapsed)
        self.tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.tree_widget.installEventFilter(self)
        self.tree_widget.viewport().installEventFilter(self)
        self.tree_widget.setItemDelegate(_FolderTreeDelegate(self))

        layout.addWidget(self.tree_widget, 1)

    def enter_selection_mode(self, initial_folder: Optional[Path] = None) -> None:
        """Enter folder selection mode, auto-selecting any nested children of initial_folder."""
        if not self._is_selection_mode:
            current_item = self.tree_widget.currentItem()
            self._pre_selection_folder = (
                current_item.data(0, Qt.ItemDataRole.UserRole)
                if current_item is not None
                else None
            )
        self._is_selection_mode = True
        if initial_folder is not None:
            self._selected_folders = collect_folder_and_descendants(
                initial_folder, self._folders
            )
        else:
            self._selected_folders = set()
        self.header_stack.setCurrentIndex(1)
        self._update_folder_items()
        self._update_batch_bar()

    def exit_selection_mode(self) -> None:
        """Exit folder selection mode and restore the previously focused folder."""
        self._is_selection_mode = False
        self._selected_folders.clear()
        self.header_stack.setCurrentIndex(0)
        restored = (
            self._pre_selection_folder
            if self._pre_selection_folder in self._folders
            else None
        )
        self._update_folder_items(current_selection=restored)

    def _update_batch_bar(self) -> None:
        """Update counter and button states in folder selection header."""
        count = len(self._selected_folders)
        self.select_count_label.setText(f"{count} selected")
        self.batch_delete_btn.setEnabled(count > 0)
        self.batch_delete_btn.setToolTip(
            f"Delete {count} selected folder{'s' if count != 1 else ''}"
            if count > 0
            else "Delete selected folders"
        )
        if count == len(self._folders) and len(self._folders) > 0:
            self.select_all_btn.setText("Deselect All")
        else:
            self.select_all_btn.setText("Select All")

    def _on_toggle_select_all(self) -> None:
        """Toggle selecting all custom folders."""
        if len(self._selected_folders) == len(self._folders) and len(self._folders) > 0:
            self._selected_folders.clear()
        else:
            self._selected_folders = set(self._folders)
        self._update_folder_items()
        self._update_batch_bar()

    def select_all_notes(self) -> None:
        """Select 'All Notes' (the root view), deselecting any custom folder."""
        if self._is_selection_mode:
            return
        if self.tree_widget.topLevelItemCount() > 0:
            all_notes_item = self.tree_widget.topLevelItem(0)
            if self.tree_widget.currentItem() != all_notes_item:
                self.tree_widget.setCurrentItem(all_notes_item)
            else:
                self._refresh_folder_icon_state(all_notes_item, all_notes_item)
                self.folder_selected.emit(None)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle clicking outside the tree widget in sidebar margins without changing folder focus."""
        super().mousePressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Handle keyboard shortcuts and mouse interactions on the folder tree."""
        if watched == self.tree_widget.viewport():
            if event.type() == QEvent.Type.MouseMove:
                item = self.tree_widget.itemAt(event.pos())
                target_cursor = (
                    Qt.CursorShape.PointingHandCursor
                    if item is not None
                    else Qt.CursorShape.ArrowCursor
                )
                if self.tree_widget.viewport().cursor().shape() != target_cursor:
                    self.tree_widget.viewport().setCursor(target_cursor)
            elif event.type() == QEvent.Type.Leave:
                self.tree_widget.viewport().setCursor(Qt.CursorShape.ArrowCursor)

        if (
            watched in (self.tree_widget, self.tree_widget.viewport())
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            if not self._is_selection_mode:
                pos = event.pos()
                if watched == self.tree_widget:
                    pos = self.tree_widget.viewport().mapFromParent(pos)
                item = self.tree_widget.itemAt(pos)
                if item is None and event.button() in (
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.RightButton,
                ):
                    # Preserve current folder focus when clicking empty space
                    return True

        if (
            watched in (self.tree_widget, self.tree_widget.viewport())
            and event.type() == QEvent.Type.KeyPress
        ):
            key_event = event
            if key_event.key() == Qt.Key.Key_F2:
                no_mod = not (
                    key_event.modifiers()
                    & (
                        Qt.KeyboardModifier.ControlModifier
                        | Qt.KeyboardModifier.AltModifier
                        | Qt.KeyboardModifier.MetaModifier
                    )
                )
                if no_mod and not self._is_selection_mode:
                    current_item = self.tree_widget.currentItem()
                    if current_item is not None:
                        folder = current_item.data(0, Qt.ItemDataRole.UserRole)
                        if folder is not None:
                            self.rename_folder_requested.emit(folder)
                            return True
            if not self._is_selection_mode:
                mods = key_event.modifiers()
                ctrl_only = bool(mods & Qt.KeyboardModifier.ControlModifier) and not bool(
                    mods
                    & (
                        Qt.KeyboardModifier.AltModifier
                        | Qt.KeyboardModifier.MetaModifier
                        | Qt.KeyboardModifier.ShiftModifier
                    )
                )
                if ctrl_only:
                    current_item = self.tree_widget.currentItem()
                    folder = (
                        current_item.data(0, Qt.ItemDataRole.UserRole)
                        if current_item is not None
                        else None
                    )
                    if key_event.key() == Qt.Key.Key_X and folder is not None:
                        self.cut_folder_requested.emit(folder)
                        return True
                    if key_event.key() == Qt.Key.Key_C and folder is not None:
                        self.copy_folder_requested.emit(folder)
                        return True
                    if key_event.key() == Qt.Key.Key_V and self._has_clipboard:
                        self.paste_into_folder_requested.emit(folder)
                        return True
                    if key_event.key() == Qt.Key.Key_Z:
                        self.undo_file_op_requested.emit()
                        return True
                if key_event.key() == Qt.Key.Key_Escape and self._cut_path is not None:
                    self.cancel_clipboard_requested.emit()
                    return True
            if key_event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                if self._is_selection_mode:
                    if self._selected_folders:
                        self.delete_folders_batch_requested.emit(list(self._selected_folders))
                        return True
                else:
                    current_item = self.tree_widget.currentItem()
                    if current_item is not None:
                        folder = current_item.data(0, Qt.ItemDataRole.UserRole)
                        if folder is not None:
                            self.delete_folder_requested.emit(folder)
                            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:
        """Handle Escape key to cancel selection mode."""
        if self._is_selection_mode and event.key() == Qt.Key.Key_Escape:
            self.exit_selection_mode()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_batch_delete_clicked(self) -> None:
        """Emit batch delete signal for selected folders."""
        if self._selected_folders:
            self.delete_folders_batch_requested.emit(list(self._selected_folders))

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int = 0) -> None:
        """Handle single-click on folder tree item."""
        if self._is_selection_mode:
            folder = item.data(0, Qt.ItemDataRole.UserRole)
            if folder is None:
                # 'All Notes' cannot be selected for folder deletion
                return
            if folder in self._selected_folders:
                self._selected_folders -= collect_folder_and_descendants(folder, self._folders)
                self._selected_folders -= collect_ancestors_in_set(folder, self._selected_folders)
            else:
                self._selected_folders |= collect_folder_and_descendants(folder, self._folders)
            self._update_folder_items()
            self._update_batch_bar()
            return

        folder = item.data(0, Qt.ItemDataRole.UserRole)
        if folder is None:
            # 'All Notes' pinned root: always ensure All Notes view is activated
            self.folder_selected.emit(None)
            return

        folder_color = self._folder_colors.get(folder.name) or "#e5a93c"

        if item.childCount() > 0:
            # Folder with subfolders (has chevron branch indicator):
            # Toggle expansion state on single click
            new_expanded = not item.isExpanded()
            item.setExpanded(new_expanded)
            item.setIcon(0, create_folder_icon(color=folder_color, size=16, is_open=new_expanded))
        else:
            # Leaf folder without subfolders:
            # Single click toggles open and closed state
            current_open = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if current_open is None:
                current_open = (self.tree_widget.currentItem() == item)
            new_open = not current_open
            item.setData(0, Qt.ItemDataRole.UserRole + 1, new_open)
            item.setIcon(0, create_folder_icon(color=folder_color, size=16, is_open=new_open))

    def _on_context_menu(self, pos: QPoint) -> None:
        """Display sleek context menu for folder actions or empty space."""
        item = self.tree_widget.itemAt(pos)
        menu = ModernContextMenu(self)

        if item is None:
            # Right-click in empty space: keep current folder focus, create root parent folder
            new_folder_act = menu.addAction(create_plus_icon("#8e8e93", size=14), "New Folder...")
            paste_act = None
            if self._has_clipboard:
                paste_act = menu.addAction(create_paste_icon("#8e8e93", size=14), "Paste")
            select_act = menu.addAction(create_checkbox_icon("#8e8e93", size=14), "Select Notes...")

            action = menu.exec(self.tree_widget.viewport().mapToGlobal(pos))
            if action == new_folder_act:
                self._on_add_folder_clicked(force_root=True)
            elif paste_act is not None and action == paste_act:
                self.paste_into_folder_requested.emit(None)
            elif action == select_act:
                self.select_all_notes_requested.emit()
            return

        folder: Optional[Path] = item.data(0, Qt.ItemDataRole.UserRole)
        folder_name = folder.name if folder is not None else "All Notes"

        if folder is not None:
            # Custom Folder or Subfolder
            is_pinned = self.is_folder_pinned(folder)
            pin_label = "Unpin Folder" if is_pinned else "Pin Folder"
            pin_act = menu.addAction(create_pin_icon(pinned=not is_pinned, color="#ff9f0a" if not is_pinned else "#8e8e93", size=14), pin_label)
            new_subfolder_act = menu.addAction(create_plus_icon("#8e8e93", size=14), "New Subfolder...")
            rename_act = menu.addAction(create_edit_icon("#8e8e93", size=14), "Rename Folder...")
            select_act = menu.addAction(create_checkbox_icon("#8e8e93", size=14), "Select...")

            menu.addSeparator()
            cut_act = menu.addAction(create_cut_icon("#8e8e93", size=14), "Cut")
            copy_act = menu.addAction(create_copy_icon("#8e8e93", size=14), "Copy")
            paste_act = None
            if self._has_clipboard:
                paste_act = menu.addAction(create_paste_icon("#8e8e93", size=14), "Paste")

            # Color options submenu
            menu.addSeparator()
            color_menu = menu.addMenu("Color")
            color_menu.menuAction().setIcon(create_color_circle_icon("#bf5af2", size=14))
            self._populate_color_menu(color_menu, folder_name)

            menu.addSeparator()
            delete_act = menu.addAction(create_trash_icon("#ff453a", size=14), "Delete Folder")
            delete_act.setProperty("is_destructive", True)

            action = menu.exec(self.tree_widget.viewport().mapToGlobal(pos))
            if action == pin_act:
                self.pin_folder_requested.emit(folder)
            elif action == new_subfolder_act:
                subfolder_name, ok = ModernInputDialog.get_text(
                    self,
                    "New Subfolder",
                    f"Create subfolder inside '{folder.name}':",
                    icon_type="folder",
                    validator=validate_folder_name,
                    max_length=MAX_FOLDER_NAME_LENGTH,
                )
                if ok and subfolder_name.strip():
                    self.create_folder_requested.emit(subfolder_name.strip(), folder)
            elif action == rename_act:
                self.rename_folder_requested.emit(folder)
            elif action == select_act:
                self.enter_selection_mode(initial_folder=folder)
            elif action == cut_act:
                self.cut_folder_requested.emit(folder)
            elif action == copy_act:
                self.copy_folder_requested.emit(folder)
            elif paste_act is not None and action == paste_act:
                self.paste_into_folder_requested.emit(folder)
            elif action == delete_act:
                self.delete_folder_requested.emit(folder)
        else:
            # 'All Notes'
            new_folder_act = menu.addAction(create_plus_icon("#8e8e93", size=14), "New Folder...")
            paste_act = None
            if self._has_clipboard:
                paste_act = menu.addAction(create_paste_icon("#8e8e93", size=14), "Paste")
            select_act = menu.addAction(create_checkbox_icon("#8e8e93", size=14), "Select Notes...")

            color_menu = menu.addMenu("Color")
            color_menu.menuAction().setIcon(create_color_circle_icon("#bf5af2", size=14))
            self._populate_color_menu(color_menu, folder_name)

            action = menu.exec(self.tree_widget.viewport().mapToGlobal(pos))
            if action == new_folder_act:
                self._on_add_folder_clicked(force_root=True)
            elif paste_act is not None and action == paste_act:
                self.paste_into_folder_requested.emit(None)
            elif action == select_act:
                self.select_all_notes_requested.emit()

    def _populate_color_menu(self, color_menu: QMenu, folder_name: str) -> None:
        """Populate the color submenu with color presets and custom color picker."""
        for name, hex_code in PRESET_COLORS:
            icon = create_color_circle_icon(hex_code, size=12)
            act = color_menu.addAction(icon, name)
            act.triggered.connect(
                lambda checked=False, fn=folder_name, col=hex_code: self._apply_folder_color(fn, col)
            )

        color_menu.addSeparator()
        custom_act = color_menu.addAction("Custom Color...")
        custom_act.triggered.connect(
            lambda checked=False, fn=folder_name: self._pick_custom_folder_color(fn)
        )

    def _apply_folder_color(self, folder_name: str, color: Optional[str]) -> None:
        """Apply color to folder and emit change signal."""
        if color:
            self._folder_colors[folder_name] = color
        else:
            self._folder_colors.pop(folder_name, None)
        self._update_folder_items()
        self.folder_color_changed.emit(folder_name, color)

    def _pick_custom_folder_color(self, folder_name: str) -> None:
        """Open modern color dialog for custom color selection."""
        fallback = "#0a84ff" if folder_name == "All Notes" else "#e5a93c"
        initial = QColor(self._folder_colors.get(folder_name, fallback))
        color = ModernColorDialog.get_color(initial, self, f"Choose Color for {folder_name}")
        if color.isValid():
            self._apply_folder_color(folder_name, color.name())

    def set_folders(
        self,
        folders: List[Path],
        current_selection: Optional[Path] = None,
        sort_order: Optional[str] = None,
    ) -> None:
        """Populate the sidebar with 'All Notes' and custom folders tree."""
        self._folders = folders
        if sort_order is not None:
            self._sort_order = normalize_sort_order(sort_order)
        self._update_folder_items(current_selection)

    def set_root_dir(self, root_dir: Optional[Path]) -> None:
        """Set workspace root directory used to normalize collapsed folder keys."""
        self._root_dir = root_dir

    def _folder_key(self, folder: Path) -> str:
        """Return stable relative POSIX key for a folder path (or str fallback)."""
        if self._root_dir is not None:
            try:
                return folder.relative_to(self._root_dir).as_posix()
            except ValueError:
                pass
        return str(folder)

    def set_collapsed_folders(self, collapsed_paths: List[str]) -> None:
        """Restore persisted collapsed folder relative paths without triggering save."""
        self._collapsed_keys = {str(p) for p in collapsed_paths if p}

    def set_pinned_folders(self, pinned_keys: List[str]) -> None:
        """Update ordered pinned folder relative paths (latest pin at index 0)."""
        self._pinned_keys = [str(p) for p in pinned_keys if p]

    def is_folder_pinned(self, folder: Path) -> bool:
        """Return True if `folder` is currently pinned."""
        return self._folder_key(folder) in self._pinned_keys

    def get_collapsed_folders(self) -> List[str]:
        """Return sorted list of currently collapsed folder keys."""
        return sorted(self._collapsed_keys)

    def expand_folder(self, folder: Path) -> None:
        """Ensure a specific folder is marked expanded (e.g. after creating a subfolder inside it)."""
        self._collapsed_keys.discard(self._folder_key(folder))

    def _find_item_for_folder(self, target: Path) -> Optional[QTreeWidgetItem]:
        """Locate the QTreeWidgetItem corresponding to `target` folder path."""

        def _walk(item: QTreeWidgetItem) -> Optional[QTreeWidgetItem]:
            folder = item.data(0, Qt.ItemDataRole.UserRole)
            if folder is not None and folder == target:
                return item
            for c in range(item.childCount()):
                found = _walk(item.child(c))
                if found is not None:
                    return found
            return None

        for i in range(self.tree_widget.topLevelItemCount()):
            found = _walk(self.tree_widget.topLevelItem(i))
            if found is not None:
                return found
        return None

    def reveal_folder(self, folder: Optional[Path]) -> None:
        """Expand only the ancestor folders needed to reveal `folder` in the sidebar tree."""
        if folder is None or (self._root_dir is not None and folder == self._root_dir):
            return
        item = self._find_item_for_folder(folder)
        if item is None:
            return

        changed = False
        self.tree_widget.blockSignals(True)
        anc = item.parent()
        while anc is not None:
            if not anc.isExpanded():
                anc.setExpanded(True)
                changed = True
            anc_folder = anc.data(0, Qt.ItemDataRole.UserRole)
            if anc_folder is not None:
                self._collapsed_keys.discard(self._folder_key(anc_folder))
            anc = anc.parent()
        self.tree_widget.blockSignals(False)

        if changed:
            if not self._is_selection_mode:
                current_item = self.tree_widget.currentItem()
                for i in range(self.tree_widget.topLevelItemCount()):
                    self._refresh_folder_icon_state(self.tree_widget.topLevelItem(i), current_item)
            self._update_collapse_all_button_state()
            self.folder_expansion_changed.emit()

    def _iter_expandable_items(self) -> List[QTreeWidgetItem]:
        """Collect all tree items that have at least one child folder."""
        expandable: List[QTreeWidgetItem] = []

        def _walk(item: QTreeWidgetItem) -> None:
            if item.childCount() > 0:
                expandable.append(item)
                for c in range(item.childCount()):
                    _walk(item.child(c))

        for i in range(self.tree_widget.topLevelItemCount()):
            _walk(self.tree_widget.topLevelItem(i))
        return expandable

    def are_all_folders_collapsed(self) -> bool:
        """Return True when expandable folders exist and all of them are collapsed."""
        expandable = self._iter_expandable_items()
        return bool(expandable) and all(not item.isExpanded() for item in expandable)

    def _update_collapse_all_button_state(self) -> None:
        """Sync the Collapse/Expand All button icon and tooltip with current tree state."""
        if not hasattr(self, "collapse_all_btn"):
            return
        all_collapsed = self.are_all_folders_collapsed()
        self.collapse_all_btn.setIcon(
            create_collapse_all_icon(collapsed=all_collapsed, color="#8e8e93", size=15)
        )
        self.collapse_all_btn.setToolTip(
            "Expand All Folders (Ctrl+Left)" if all_collapsed else "Collapse All Folders (Ctrl+Left)"
        )

    def toggle_collapse_all_folders(self) -> None:
        """Collapse all expandable folders if any are open; otherwise expand all folders."""
        expandable = self._iter_expandable_items()
        if not expandable:
            return

        expand = self.are_all_folders_collapsed()
        self.tree_widget.blockSignals(True)
        for item in expandable:
            item.setExpanded(expand)
            folder = item.data(0, Qt.ItemDataRole.UserRole)
            if folder is not None:
                key = self._folder_key(folder)
                if expand:
                    self._collapsed_keys.discard(key)
                else:
                    self._collapsed_keys.add(key)
        self.tree_widget.blockSignals(False)

        if not self._is_selection_mode:
            current_item = self.tree_widget.currentItem()
            for i in range(self.tree_widget.topLevelItemCount()):
                self._refresh_folder_icon_state(self.tree_widget.topLevelItem(i), current_item)

        self._update_collapse_all_button_state()
        self.folder_expansion_changed.emit()

    def _update_folder_items(self, current_selection: Optional[Path] = None) -> None:
        """Render folder items in hierarchical tree with expansion and selection icons."""
        self.tree_widget.blockSignals(True)
        self.tree_widget.clear()

        # Item 0: All Notes (Pinned Root)
        all_notes_item = QTreeWidgetItem(["All Notes"])
        all_notes_item.setData(0, Qt.ItemDataRole.UserRole, None)
        all_notes_color = self._folder_colors.get("All Notes") or "#0a84ff"
        all_notes_item.setIcon(0, create_all_notes_icon(color=all_notes_color, size=16))
        self.tree_widget.addTopLevelItem(all_notes_item)

        selected_item = all_notes_item

        # Map Path -> QTreeWidgetItem to parent subfolders cleanly
        item_map: Dict[Path, QTreeWidgetItem] = {}

        # Sort folders hierarchically across all nesting depths (pinned siblings first)
        sorted_folders = sort_folders(
            self._folders,
            sort_order=self._sort_order,
            pinned_keys=self._pinned_keys,
            root_dir=self._root_dir,
        )

        for folder in sorted_folders:
            item = QTreeWidgetItem([folder.name])
            item.setData(0, Qt.ItemDataRole.UserRole, folder)

            if self._is_selection_mode:
                if folder in self._selected_folders:
                    item.setIcon(0, create_check_icon(size=14))
                else:
                    item.setIcon(0, create_uncheck_icon(size=14))
            else:
                folder_color = self._folder_colors.get(folder.name) or "#e5a93c"
                is_selected = current_selection is not None and folder == current_selection
                item.setIcon(0, create_folder_icon(color=folder_color, size=16, is_open=is_selected))

            parent_path = folder.parent
            if parent_path in item_map:
                item_map[parent_path].addChild(item)
            else:
                self.tree_widget.addTopLevelItem(item)

            item_map[folder] = item

            if current_selection is not None and folder == current_selection:
                selected_item = item

        if not self._is_selection_mode:
            self.tree_widget.setCurrentItem(selected_item)

        # Apply saved expansion/collapse state AFTER setCurrentItem so Qt does not auto-reopen collapsed parents
        for folder, item in item_map.items():
            if item.childCount() > 0:
                is_expanded = self._folder_key(folder) not in self._collapsed_keys
                item.setExpanded(is_expanded)

        self.tree_widget.blockSignals(False)

        if not self._is_selection_mode:
            current_item = self.tree_widget.currentItem()
            for i in range(self.tree_widget.topLevelItemCount()):
                self._refresh_folder_icon_state(self.tree_widget.topLevelItem(i), current_item)

        self._update_collapse_all_button_state()

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        """Update folder icon and persisted state when expanded."""
        folder = item.data(0, Qt.ItemDataRole.UserRole)
        if folder is not None:
            self._collapsed_keys.discard(self._folder_key(folder))
            if not self._is_selection_mode:
                folder_color = self._folder_colors.get(folder.name) or "#e5a93c"
                item.setIcon(0, create_folder_icon(color=folder_color, size=16, is_open=True))
        self._update_collapse_all_button_state()
        self.folder_expansion_changed.emit()

    def _on_item_collapsed(self, item: QTreeWidgetItem) -> None:
        """Update folder icon and persisted state when collapsed."""
        folder = item.data(0, Qt.ItemDataRole.UserRole)
        if folder is not None:
            self._collapsed_keys.add(self._folder_key(folder))
            if not self._is_selection_mode:
                folder_color = self._folder_colors.get(folder.name) or "#e5a93c"
                item.setIcon(0, create_folder_icon(color=folder_color, size=16, is_open=False))
        self._update_collapse_all_button_state()
        self.folder_expansion_changed.emit()

    def _on_selection_changed(self) -> None:
        if self._is_selection_mode:
            return
        current_item = self.tree_widget.currentItem()
        if current_item is not None:
            folder_path = current_item.data(0, Qt.ItemDataRole.UserRole)
            self.folder_selected.emit(folder_path)

        # Refresh open/closed state on all folder items
        for i in range(self.tree_widget.topLevelItemCount()):
            self._refresh_folder_icon_state(self.tree_widget.topLevelItem(i), current_item)

    def _refresh_folder_icon_state(
        self, item: QTreeWidgetItem, current_item: Optional[QTreeWidgetItem]
    ) -> None:
        folder = item.data(0, Qt.ItemDataRole.UserRole)
        if folder is not None and not self._is_selection_mode:
            folder_color = self._folder_colors.get(folder.name) or "#e5a93c"
            if item.childCount() > 0:
                is_open = item.isExpanded()
            else:
                is_open = (item == current_item)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, is_open)
            item.setIcon(0, create_folder_icon(color=folder_color, size=16, is_open=is_open))
        for c in range(item.childCount()):
            self._refresh_folder_icon_state(item.child(c), current_item)

    def _on_add_folder_clicked(self, force_root: bool = False) -> None:
        # If currently a folder is selected and not forced to root, prompt for subfolder
        current_item = None if force_root else self.tree_widget.currentItem()
        current_folder = (
            current_item.data(0, Qt.ItemDataRole.UserRole)
            if current_item is not None
            else None
        )

        title = "New Folder"
        prompt = "Enter folder name:"
        if current_folder is not None:
            title = f"New Subfolder inside '{current_folder.name}'"
            prompt = f"Enter subfolder name for '{current_folder.name}':"

        folder_name, ok = ModernInputDialog.get_text(
            self,
            title,
            prompt,
            icon_type="folder",
            validator=validate_folder_name,
            max_length=MAX_FOLDER_NAME_LENGTH,
        )
        if ok and folder_name.strip():
            self.create_folder_requested.emit(
                folder_name.strip(), None if force_root else current_folder
            )
