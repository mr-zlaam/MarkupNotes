"""Modern dark-themed dedicated settings modal dialog."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, List, Optional, Tuple

from PyQt6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsDropShadowEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.config import ConfigManager
from utils.icons import (
    create_backup_icon,
    create_badge_pixmap,
    create_chevron_icon,
    create_close_icon,
    create_code_icon,
    create_info_icon,
    create_keyboard_icon,
    create_palette_icon,
    create_search_icon,
    create_settings_icon,
    create_sliders_icon,
    create_type_icon,
)
from utils.paths import get_config_dir, get_default_notes_dir


class ToggleSwitch(QAbstractButton):
    """Modern iOS/GNOME-style animated pill toggle switch."""

    def __init__(self, checked: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event: QEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        is_on = self.isChecked()
        # Neutral platinum/graphite styling (no blue/indigo)
        track_color = QColor("#555562") if is_on else QColor("#2a2a32")
        border_color = QColor("#707080") if is_on else QColor("#3c3c46")
        thumb_color = QColor("#f4f4f8") if is_on else QColor("#8e8e98")

        # Track
        rect = QRectF(0.5, 0.5, float(self.width()) - 1.0, float(self.height()) - 1.0)
        radius = float(self.height() - 1) / 2.0
        painter.setPen(QPen(border_color, 1.0))
        painter.setBrush(QBrush(track_color))
        painter.drawRoundedRect(rect, radius, radius)

        # Thumb
        thumb_radius = 8.0
        thumb_x = (float(self.width()) - thumb_radius * 2.0 - 3.0) if is_on else 3.0
        thumb_y = (float(self.height()) - thumb_radius * 2.0) / 2.0
        thumb_rect = QRectF(thumb_x, thumb_y, thumb_radius * 2.0, thumb_radius * 2.0)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(thumb_color))
        painter.drawEllipse(thumb_rect)
        painter.end()


class ModernComboBox(QComboBox):
    """Modern dark-themed styled combo box with vector chevron and dark item popup."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chevron_icon = create_chevron_icon("down", color="#9e9ea6", size=12, stroke_width=2.0)

        # Force Qt to use a standard QListView delegate to prevent unstyled native platform popups
        list_view = QListView(self)
        list_view.setObjectName("ModernComboListView")
        list_view.setStyleSheet("""
            QListView {
                background-color: transparent;
                color: #e4e4ec;
                border: none;
                padding: 4px;
                outline: none;
            }
            QListView::item {
                height: 28px;
                padding: 4px 10px;
                border-radius: 5px;
                color: #e4e4ec;
            }
            QListView::item:hover {
                background-color: #2c2c36;
                color: #ffffff;
            }
            QListView::item:selected {
                background-color: #383848;
                color: #ffffff;
                font-weight: 600;
            }
            QScrollBar:vertical {
                background-color: transparent;
                width: 6px;
                margin: 2px 0;
            }
            QScrollBar::handle:vertical {
                background-color: #3a3a44;
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #555562;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        self.setView(list_view)

        self.setStyleSheet("""
            QComboBox {
                background-color: #24242a;
                color: #f2f2f6;
                border: 1px solid #3c3c46;
                border-radius: 6px;
                padding: 6px 32px 6px 12px;
                font-size: 13px;
                min-width: 150px;
            }
            QComboBox:hover {
                background-color: #2a2a32;
                border-color: #50505c;
            }
            QComboBox:focus, QComboBox:on {
                border-color: #70707e;
                background-color: #282830;
            }
            QComboBox::drop-down {
                border: none;
                background: transparent;
                width: 0px;
            }
        """)

    def showPopup(self) -> None:
        """Ensure popup container frame is dark-themed with no light platform borders."""
        popup_frame = self.view().window()
        if isinstance(popup_frame, QFrame):
            popup_frame.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
            popup_frame.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            popup_frame.setFrameShape(QFrame.Shape.NoFrame)
            popup_frame.setLineWidth(0)
            popup_frame.setContentsMargins(0, 0, 0, 0)
            popup_frame.setStyleSheet("""
                QFrame {
                    background-color: #1e1e24;
                    border: 1px solid #3c3c48;
                    border-radius: 8px;
                }
            """)
        super().showPopup()

    def paintEvent(self, event: QEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        x = self.width() - 22
        y = (self.height() - 12) // 2
        self._chevron_icon.paint(painter, x, y, 12, 12)
        painter.end()


class SettingRow(QFrame):
    """A clean horizontal setting card containing title, description, and control widget."""

    def __init__(
        self,
        title: str,
        description: str,
        control_widget: QWidget,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.title_text = title
        self.description_text = description
        self.setObjectName("SettingRow")
        self.setStyleSheet("""
            QFrame#SettingRow {
                background-color: #222227;
                border: 1px solid #32323a;
                border-radius: 8px;
            }
            QFrame#SettingRow:hover {
                border-color: #40404c;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(3)

        self.title_lbl = QLabel(title, parent=self)
        self.title_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #f0f0f5;")
        text_col.addWidget(self.title_lbl)

        if description:
            self.desc_lbl = QLabel(description, parent=self)
            self.desc_lbl.setStyleSheet("font-size: 11px; color: #8a8a94;")
            self.desc_lbl.setWordWrap(True)
            text_col.addWidget(self.desc_lbl)

        layout.addLayout(text_col, 1)
        layout.addWidget(control_widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def matches_query(self, query: str) -> bool:
        """Check if row matches search text."""
        q = query.lower()
        return q in self.title_text.lower() or q in self.description_text.lower()


class ModernSettingsDialog(QDialog):
    """Modern dark-themed dedicated settings dialog overlay with category navigation."""

    settings_updated = pyqtSignal()

    def __init__(
        self,
        config_manager: ConfigManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.config_manager = config_manager
        self.parent_win = parent.window() if parent else None
        self._blurred_pm: Optional[QPixmap] = None
        self.setting_rows: List[SettingRow] = []

        self.setWindowTitle("Settings")
        if self.parent_win:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setGeometry(self.parent_win.rect())
            self.parent_win.installEventFilter(self)
            self._capture_blurred_backdrop()
        else:
            self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setFixedSize(860, 620)

        self._init_ui()

    def _update_card_geometry(self) -> None:
        """Adjust card size smoothly on parent resize."""
        if self.parent_win and hasattr(self, "card"):
            w = min(860, max(560, self.width() - 40))
            h = min(620, max(460, self.height() - 40))
            self.card.setFixedSize(w, h)

    def _init_ui(self) -> None:
        """Construct the settings dialog layout and components."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 1. Main Modal Card
        self.card = QFrame(parent=self)
        self.card.setObjectName("SettingsCard")
        self.card.setFixedSize(860, 620)
        self._update_card_geometry()
        self.card.setStyleSheet("""
            QFrame#SettingsCard {
                background-color: #1a1a1e;
                border: 1px solid #383842;
                border-radius: 14px;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 0, 0, 200))
        shadow.setOffset(0, 8)
        self.card.setGraphicsEffect(shadow)
        outer_layout.addWidget(self.card)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(22, 18, 22, 18)
        card_layout.setSpacing(12)

        # 2. Header
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        gear_icon = create_settings_icon(color="#f2f2f6", size=20)
        badge_pm = create_badge_pixmap(gear_icon, bg_color="#24242c", border_color="#3c3c48", badge_size=40, icon_size=20)
        icon_lbl = QLabel(parent=self.card)
        icon_lbl.setPixmap(badge_pm)
        header_layout.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)

        title_lbl = QLabel("Settings", parent=self.card)
        title_lbl.setStyleSheet("font-size: 17px; font-weight: 700; color: #f2f2f6;")
        title_col.addWidget(title_lbl)

        sub_lbl = QLabel("Preferences and workspace configuration", parent=self.card)
        sub_lbl.setStyleSheet("font-size: 12px; color: #8e8e93;")
        title_col.addWidget(sub_lbl)
        header_layout.addLayout(title_col, 1)

        # Search Bar
        self.search_edit = QLineEdit(parent=self.card)
        self.search_edit.setPlaceholderText("Search settings...")
        self.search_edit.addAction(create_search_icon(color="#7a7a82", size=14), QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.setFixedWidth(240)
        self.search_edit.textChanged.connect(self._on_search_changed)
        self.search_edit.installEventFilter(self)
        self.search_edit.setStyleSheet("""
            QLineEdit {
                background-color: #24242a;
                color: #f2f2f6;
                font-size: 12px;
                border: 1px solid #3c3c46;
                border-radius: 8px;
                padding: 6px 10px 6px 6px;
            }
            QLineEdit:focus {
                border: 1px solid #63636e;
                background-color: #282830;
            }
        """)
        header_layout.addWidget(self.search_edit)

        # Close button
        close_btn = QPushButton(parent=self.card)
        close_btn.setIcon(create_close_icon(color="#8e8e93", size=14))
        close_btn.setFixedSize(30, 30)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setToolTip("Close (Esc or Space)")
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #242428;
                border: 1px solid #383840;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #303038;
            }
        """)
        header_layout.addWidget(close_btn)
        card_layout.addLayout(header_layout)

        # Divider line
        divider = QFrame(parent=self.card)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        divider.setStyleSheet("background-color: #282830; max-height: 1px;")
        card_layout.addWidget(divider)

        # 3. Two-Column Body: Navigation Sidebar + Pages Stack
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(14)

        # Left Category Navigation Sidebar
        self.nav_sidebar = QWidget(parent=self.card)
        self.nav_sidebar.setFixedWidth(190)
        self.nav_sidebar.setStyleSheet("background-color: transparent;")
        nav_layout = QVBoxLayout(self.nav_sidebar)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)

        self.category_buttons: List[QPushButton] = []
        categories = [
            ("General", create_sliders_icon("#9e9ea6", size=15), 0),
            ("Editor", create_type_icon("#9e9ea6", size=15), 1),
            ("Markdown", create_code_icon("#9e9ea6", size=15), 2),
            ("Appearance", create_palette_icon("#9e9ea6", size=15), 3),
            ("Git & Backup", create_backup_icon("#9e9ea6", size=15), 4),
            ("About", create_info_icon("#9e9ea6", size=15), 5),
        ]

        for name, icon, idx in categories:
            btn = QPushButton(name.replace("&", "&&"), parent=self.nav_sidebar)
            btn.setIcon(icon)
            btn.setIconSize(QSize(16, 16))
            btn.setCheckable(True)
            btn.setChecked(idx == 0)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    text-align: left;
                    padding: 8px 12px;
                    font-size: 13px;
                    font-weight: 500;
                    color: #9e9ea6;
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #24242a;
                    color: #e4e4ec;
                }
                QPushButton:checked {
                    background-color: #2b2b32;
                    color: #f4f4f8;
                    border: 1px solid #42424e;
                    font-weight: 600;
                }
            """)
            btn.clicked.connect(lambda checked, i=idx: self._on_category_clicked(i))
            nav_layout.addWidget(btn)
            self.category_buttons.append(btn)

        nav_layout.addStretch()
        body_layout.addWidget(self.nav_sidebar)

        # Vertical Divider
        v_divider = QFrame(parent=self.card)
        v_divider.setFrameShape(QFrame.Shape.VLine)
        v_divider.setStyleSheet("background-color: #282830; max-width: 1px;")
        body_layout.addWidget(v_divider)

        # Right Content Area (Stacked Widget with Scrollable Category Pages)
        self.stack = QStackedWidget(parent=self.card)
        self.stack.setStyleSheet("background-color: transparent;")

        self.stack.addWidget(self._build_general_page())
        self.stack.addWidget(self._build_editor_page())
        self.stack.addWidget(self._build_markdown_page())
        self.stack.addWidget(self._build_appearance_page())
        self.stack.addWidget(self._build_backup_page())
        self.stack.addWidget(self._build_about_page())

        body_layout.addWidget(self.stack, 1)
        card_layout.addLayout(body_layout, 1)

        # 4. Footer
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(10)

        open_cfg_btn = QPushButton("Open settings.json", parent=self.card)
        open_cfg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_cfg_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #8e8e93;
                border: 1px solid #363640;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #24242a;
                color: #e0e0e6;
                border-color: #484854;
            }
        """)
        open_cfg_btn.clicked.connect(self._open_config_file)
        footer_layout.addWidget(open_cfg_btn)

        reset_btn = QPushButton("Reset to Defaults", parent=self.card)
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #ff6961;
                border: 1px solid #4a2828;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #381e1e;
                color: #ff8580;
                border-color: #6a3434;
            }
        """)
        reset_btn.clicked.connect(self._reset_to_defaults)
        footer_layout.addWidget(reset_btn)

        footer_layout.addStretch()

        done_btn = QPushButton("Done", parent=self.card)
        done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        done_btn.setStyleSheet("""
            QPushButton {
                background-color: #32323a;
                color: #f2f2f6;
                border: 1px solid #484854;
                border-radius: 6px;
                padding: 6px 20px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #3e3e48;
                border-color: #646472;
            }
        """)
        done_btn.clicked.connect(self.accept)
        footer_layout.addWidget(done_btn)

        card_layout.addLayout(footer_layout)

    def _create_scroll_page(self) -> Tuple[QScrollArea, QVBoxLayout]:
        """Create a standard scrollable container for a settings page."""
        scroll = QScrollArea(parent=self.card)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background-color: transparent;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #3a3a44;
                min-height: 24px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #555562;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 2, 8, 4)
        layout.setSpacing(10)

        scroll.setWidget(container)
        return scroll, layout

    # =========================================================================
    # Page Builders
    # =========================================================================

    def _build_general_page(self) -> QWidget:
        """Construct the General & Workspace settings page."""
        scroll, layout = self._create_scroll_page()
        cfg = self.config_manager.settings

        # 1. Confirm Deletion
        del_toggle = ToggleSwitch(checked=cfg.general.confirm_delete)
        del_toggle.toggled.connect(self._on_confirm_delete_toggled)
        r1 = SettingRow("Confirm on Delete", "Prompt a confirmation modal before deleting notes or folders", del_toggle)
        layout.addWidget(r1)
        self.setting_rows.append(r1)

        # 2. Open Notes Folder
        open_folder_btn = QPushButton("Reveal in File Manager")
        open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder_btn.setStyleSheet("background-color: #282830; color: #e0e0e6; border: 1px solid #3c3c46; border-radius: 6px; padding: 5px 12px; font-size: 12px;")
        open_folder_btn.clicked.connect(self._reveal_notes_folder)
        r2 = SettingRow("Notes Storage Folder", str(get_default_notes_dir()), open_folder_btn)
        layout.addWidget(r2)
        self.setting_rows.append(r2)

        # 3. Restore Factory Defaults
        factory_reset_btn = QPushButton("Reset to Defaults")
        factory_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        factory_reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #2e1a1a;
                color: #ff8580;
                border: 1px solid #5a2828;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #3e2222;
                color: #ffa09c;
                border-color: #7a3535;
            }
        """)
        factory_reset_btn.clicked.connect(self._reset_to_defaults)
        r3 = SettingRow(
            "Restore Factory Defaults",
            "Reset all settings, editor typography, layout sizes, and appearance colors to initial factory state as if opening Markup Notes for the first time",
            factory_reset_btn,
        )
        layout.addWidget(r3)
        self.setting_rows.append(r3)

        layout.addStretch()
        return scroll

    def _build_editor_page(self) -> QWidget:
        """Construct the Editor typography and behavior settings page."""
        scroll, layout = self._create_scroll_page()
        cfg = self.config_manager.settings

        # 1. Font Size
        size_spin = QSpinBox()
        size_spin.setRange(10, 32)
        size_spin.setValue(cfg.editor.font_size)
        size_spin.setSuffix(" px")
        size_spin.setStyleSheet("""
            QSpinBox {
                background-color: #24242a;
                color: #f2f2f6;
                border: 1px solid #3c3c46;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 13px;
                min-width: 90px;
            }
            QSpinBox:hover {
                background-color: #2a2a32;
                border-color: #50505c;
            }
            QSpinBox:focus {
                border-color: #70707e;
                background-color: #282830;
            }
        """)
        size_spin.valueChanged.connect(self._on_font_size_changed)
        r1 = SettingRow("Font Size", "Base font size for markdown editor content (default 12 px)", size_spin)
        layout.addWidget(r1)
        self.setting_rows.append(r1)

        # 2. Line Spacing Multiplier
        line_combo = ModernComboBox()
        line_combo.addItems(["1.2 (Compact)", "1.4 (Default)", "1.6 (Relaxed)", "1.8 (Spacious)"])
        val_map = {1.2: 0, 1.4: 1, 1.5: 1, 1.6: 2, 1.8: 3}
        line_combo.setCurrentIndex(val_map.get(cfg.editor.line_height, 1))
        line_combo.currentIndexChanged.connect(self._on_line_height_changed)
        r2 = SettingRow("Line Height", "Vertical line spacing between text paragraphs", line_combo)
        layout.addWidget(r2)
        self.setting_rows.append(r2)

        # 3. Word Wrap
        wrap_toggle = ToggleSwitch(checked=cfg.editor.word_wrap)
        wrap_toggle.toggled.connect(self._on_word_wrap_toggled)
        r3 = SettingRow("Word Wrap", "Soft-wrap long lines to fit the current editor viewport", wrap_toggle)
        layout.addWidget(r3)
        self.setting_rows.append(r3)

        # 4. Tab Width
        tab_combo = ModernComboBox()
        tab_combo.addItems(["2 Spaces", "4 Spaces"])
        tab_combo.setCurrentIndex(0 if cfg.editor.tab_size == 2 else 1)
        tab_combo.currentIndexChanged.connect(lambda idx: self._on_tab_size_changed(2 if idx == 0 else 4))
        r4 = SettingRow("Tab Indentation Width", "Number of spaces inserted per indentation level", tab_combo)
        layout.addWidget(r4)
        self.setting_rows.append(r4)

        layout.addStretch()
        return scroll

        layout.addStretch()
        return scroll

    def _build_markdown_page(self) -> QWidget:
        """Construct the Markdown features and rendering settings page."""
        scroll, layout = self._create_scroll_page()
        cfg = self.config_manager.settings

        # 1. LaTeX Math
        latex_toggle = ToggleSwitch(checked=cfg.markdown.render_latex)
        latex_toggle.toggled.connect(self._on_render_latex_toggled)
        r1 = SettingRow("LaTeX Math Rendering", "Render inline and block LaTeX math equations via KaTeX", latex_toggle)
        layout.addWidget(r1)
        self.setting_rows.append(r1)

        # 2. Mermaid Diagrams
        mermaid_toggle = ToggleSwitch(checked=cfg.markdown.render_mermaid)
        mermaid_toggle.toggled.connect(self._on_render_mermaid_toggled)
        r2 = SettingRow("Mermaid Diagrams", "Render live flowcharts and diagrams from mermaid code blocks", mermaid_toggle)
        layout.addWidget(r2)
        self.setting_rows.append(r2)

        # 3. Smart Lists
        list_toggle = ToggleSwitch(checked=cfg.markdown.smart_list)
        list_toggle.toggled.connect(self._on_smart_list_toggled)
        r3 = SettingRow("Smart List Continuation", "Automatically continue bullets, numbers, and checkboxes on Enter", list_toggle)
        layout.addWidget(r3)
        self.setting_rows.append(r3)

        # 4. Code Line Numbers
        code_nums = ToggleSwitch(checked=cfg.markdown.code_line_numbers)
        code_nums.toggled.connect(self._on_code_line_numbers_toggled)
        r4 = SettingRow("Code Block Line Numbers", "Show line numbering gutter inside fenced code blocks", code_nums)
        layout.addWidget(r4)
        self.setting_rows.append(r4)

        layout.addStretch()
        return scroll

    def _build_appearance_page(self) -> QWidget:
        """Construct the Appearance & Theme settings page."""
        scroll, layout = self._create_scroll_page()
        cfg = self.config_manager.settings

        # 1. Theme Selection
        theme_combo = ModernComboBox()
        theme_combo.addItems(["Dark Modern (Default)", "OLED Black", "System Match"])
        theme_map = {"dark": 0, "oled": 1, "system": 2}
        theme_combo.setCurrentIndex(theme_map.get(cfg.appearance.theme, 0))
        theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        r1 = SettingRow("Interface Theme", "Application background palette and interface styling", theme_combo)
        layout.addWidget(r1)
        self.setting_rows.append(r1)

        # 2. Clear Folder and Note Color Overrides
        clear_colors_btn = QPushButton("Reset Custom Colors")
        clear_colors_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_colors_btn.setStyleSheet("background-color: #282830; color: #e0e0e6; border: 1px solid #3c3c46; border-radius: 6px; padding: 5px 12px; font-size: 12px;")
        clear_colors_btn.clicked.connect(self._on_clear_custom_colors)
        num_folders = len(cfg.appearance.folder_colors)
        num_notes = len(cfg.appearance.note_colors)
        desc = f"{num_folders} folder overrides, {num_notes} note color overrides active"
        r2 = SettingRow("Item Color Customizations", desc, clear_colors_btn)
        layout.addWidget(r2)
        self.setting_rows.append(r2)

        layout.addStretch()
        return scroll

    def _build_backup_page(self) -> QWidget:
        """Construct the Git & Cloud Backup settings page."""
        scroll, layout = self._create_scroll_page()
        cfg = self.config_manager.settings

        # 1. Auto Backup Toggle
        auto_toggle = ToggleSwitch(checked=cfg.backup.auto_backup)
        auto_toggle.toggled.connect(self._on_auto_backup_toggled)
        r1 = SettingRow("Automatic Git Backup", "Commit local note changes automatically on every save", auto_toggle)
        layout.addWidget(r1)
        self.setting_rows.append(r1)

        # 2. Git Status Info
        notes_git_dir = get_default_notes_dir() / ".git"
        git_status_text = "Initialized (Active)" if notes_git_dir.exists() else "Not initialized"
        status_lbl = QLabel(git_status_text)
        status_lbl.setStyleSheet("color: #30d158; font-weight: 600; font-size: 12px;" if notes_git_dir.exists() else "color: #8e8e93; font-size: 12px;")
        r2 = SettingRow("Local Git Repository", str(notes_git_dir), status_lbl)
        layout.addWidget(r2)
        self.setting_rows.append(r2)

        # 3. GitHub Remote Repository URL
        repo_edit = QLineEdit(cfg.backup.github_repo_url)
        repo_edit.setPlaceholderText("https://github.com/user/my-notes.git")
        repo_edit.setFixedWidth(220)
        repo_edit.setStyleSheet("background-color: #24242a; color: #f2f2f6; border: 1px solid #3c3c46; border-radius: 6px; padding: 4px 8px; font-size: 12px;")
        repo_edit.editingFinished.connect(lambda: self._on_github_repo_changed(repo_edit.text()))
        r3 = SettingRow("GitHub Remote Repository", "Target git remote URL for cloud synchronization", repo_edit)
        layout.addWidget(r3)
        self.setting_rows.append(r3)

        layout.addStretch()
        return scroll

    def _build_about_page(self) -> QWidget:
        """Construct the About & System Diagnostics settings page."""
        scroll, layout = self._create_scroll_page()

        # 1. Application Info
        version_lbl = QLabel("v0.2.0")
        version_lbl.setStyleSheet("color: #e0e0e8; font-weight: 600; font-size: 13px;")
        r1 = SettingRow("Markup Notes Version", "Native high-performance Markdown note-taking app", version_lbl)
        layout.addWidget(r1)
        self.setting_rows.append(r1)

        # 2. Shortcuts Dialog Launcher
        shortcuts_btn = QPushButton("View Shortcuts (Ctrl+/)")
        shortcuts_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        shortcuts_btn.setStyleSheet("background-color: #282830; color: #e0e0e6; border: 1px solid #3c3c46; border-radius: 6px; padding: 5px 12px; font-size: 12px;")
        shortcuts_btn.clicked.connect(self._launch_shortcuts_dialog)
        r2 = SettingRow("Keyboard Shortcuts Cheatsheet", "Complete reference of all editor and navigation keybindings", shortcuts_btn)
        layout.addWidget(r2)
        self.setting_rows.append(r2)

        # 3. Factory Reset Option
        about_reset_btn = QPushButton("Reset All Settings")
        about_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        about_reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #2e1a1a;
                color: #ff8580;
                border: 1px solid #5a2828;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #3e2222;
                color: #ffa09c;
                border-color: #7a3535;
            }
        """)
        about_reset_btn.clicked.connect(self._reset_to_defaults)
        r3 = SettingRow(
            "Restore Factory Defaults",
            "Clear all custom settings and revert to initial installation defaults",
            about_reset_btn,
        )
        layout.addWidget(r3)
        self.setting_rows.append(r3)

        layout.addStretch()
        return scroll

    # =========================================================================
    # Event Handlers & State Persistence
    # =========================================================================

    def _on_category_clicked(self, index: int) -> None:
        """Switch active page in the stacked widget."""
        for i, btn in enumerate(self.category_buttons):
            btn.setChecked(i == index)
        self.stack.setCurrentIndex(index)

    def _on_search_changed(self, text: str) -> None:
        """Filter setting rows across all pages based on search text."""
        query = text.strip().lower()
        for row in self.setting_rows:
            if not query:
                row.setVisible(True)
            else:
                row.setVisible(row.matches_query(query))

    def _on_confirm_delete_toggled(self, checked: bool) -> None:
        self.config_manager.update_general(confirm_delete=checked)
        self.settings_updated.emit()

    def _on_font_size_changed(self, size: int) -> None:
        self.config_manager.update_editor(font_size=size)
        self.settings_updated.emit()

    def _on_line_height_changed(self, index: int) -> None:
        heights = [1.2, 1.4, 1.6, 1.8]
        val = heights[index] if index < len(heights) else 1.4
        self.config_manager.update_editor(line_height=val)
        self.settings_updated.emit()

    def _on_word_wrap_toggled(self, checked: bool) -> None:
        self.config_manager.update_editor(word_wrap=checked)
        self.settings_updated.emit()

    def _on_tab_size_changed(self, size: int) -> None:
        self.config_manager.update_editor(tab_size=size)
        self.settings_updated.emit()

    def _on_render_latex_toggled(self, checked: bool) -> None:
        self.config_manager.update_markdown(render_latex=checked)
        self.settings_updated.emit()

    def _on_render_mermaid_toggled(self, checked: bool) -> None:
        self.config_manager.update_markdown(render_mermaid=checked)
        self.settings_updated.emit()

    def _on_smart_list_toggled(self, checked: bool) -> None:
        self.config_manager.update_markdown(smart_list=checked)
        self.settings_updated.emit()

    def _on_code_line_numbers_toggled(self, checked: bool) -> None:
        self.config_manager.update_markdown(code_line_numbers=checked)
        self.settings_updated.emit()

    def _on_theme_changed(self, index: int) -> None:
        themes = ["dark", "oled", "system"]
        theme = themes[index] if index < len(themes) else "dark"
        self.config_manager.settings.appearance.theme = theme
        self.config_manager.save()
        self.settings_updated.emit()

    def _on_clear_custom_colors(self) -> None:
        self.config_manager.clear_all_custom_colors()
        self.settings_updated.emit()

    def _on_auto_backup_toggled(self, checked: bool) -> None:
        self.config_manager.set_auto_backup(checked)
        self.settings_updated.emit()

    def _on_github_repo_changed(self, url: str) -> None:
        self.config_manager.settings.backup.github_repo_url = url.strip()
        self.config_manager.save()
        self.settings_updated.emit()

    def _reveal_notes_folder(self) -> None:
        """Open the notes directory in system file manager."""
        folder = get_default_notes_dir()
        folder.mkdir(parents=True, exist_ok=True)
        url = QUrl.fromLocalFile(str(folder))
        if not QDesktopServices.openUrl(url):
            try:
                subprocess.Popen(["xdg-open", str(folder)])
            except OSError:
                pass

    def _open_config_file(self) -> None:
        """Open the raw settings.json in the user's default text editor."""
        cfg_file = self.config_manager.config_path
        if not cfg_file.exists():
            self.config_manager.save()
        url = QUrl.fromLocalFile(str(cfg_file))
        if not QDesktopServices.openUrl(url):
            try:
                subprocess.Popen(["xdg-open", str(cfg_file)])
            except OSError:
                pass

    def _rebuild_pages(self) -> None:
        """Rebuild all category pages to reflect refreshed configuration state."""
        current_idx = self.stack.currentIndex()
        self.setting_rows.clear()
        while self.stack.count() > 0:
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()

        self.stack.addWidget(self._build_general_page())
        self.stack.addWidget(self._build_editor_page())
        self.stack.addWidget(self._build_markdown_page())
        self.stack.addWidget(self._build_appearance_page())
        self.stack.addWidget(self._build_backup_page())
        self.stack.addWidget(self._build_about_page())
        self.stack.setCurrentIndex(current_idx)

    def _reset_to_defaults(self) -> None:
        """Reset all configuration values to defaults using modern confirmation modal."""
        from ui.dialogs import ModernConfirmDialog
        from utils.icons import create_alert_icon

        confirmed = ModernConfirmDialog.ask(
            parent=self,
            title="Restore Factory Defaults",
            message=(
                "Are you sure you want to restore all settings to their original factory defaults?\n\n"
                "This will reset all preferences, editor typography, layout sizes, and appearance "
                "colors to initial factory state as if opening Markup Notes for the first time.\n\n"
                "Your notes and folders will remain completely safe and untouched."
            ),
            confirm_text="Reset to Defaults",
            is_destructive=True,
            custom_icon=create_alert_icon("#ff453a", size=20),
            dialog_width=470,
        )
        if confirmed:
            self.config_manager.reset_to_defaults()
            if self.parent_win and hasattr(self.parent_win, "restore_default_layout"):
                self.parent_win.restore_default_layout()
            self._rebuild_pages()
            self.settings_updated.emit()

    def _launch_shortcuts_dialog(self) -> None:
        """Launch the shortcuts modal directly from the About page."""
        self.reject()
        if self.parent_win and hasattr(self.parent_win, "show_shortcuts_cheatsheet"):
            self.parent_win.show_shortcuts_cheatsheet()

    # =========================================================================
    # Frosted Glass Gaussian Blur Backdrop
    # =========================================================================

    def _capture_blurred_backdrop(self) -> None:
        """Capture the parent window contents and render a Gaussian blurred frosted glass backdrop."""
        if not self.parent_win:
            self._blurred_pm = None
            return

        try:
            pm = self.parent_win.grab()
            if pm.isNull():
                return
            scene = QGraphicsScene()
            item = QGraphicsPixmapItem(pm)
            blur = QGraphicsBlurEffect()
            blur.setBlurRadius(24)
            item.setGraphicsEffect(blur)
            scene.addItem(item)
            self._blurred_pm = QPixmap(pm.size())
            self._blurred_pm.fill(Qt.GlobalColor.transparent)
            painter = QPainter(self._blurred_pm)
            w = float(pm.width())
            h = float(pm.height())
            scene.render(painter, QRectF(0.0, 0.0, w, h), QRectF(0.0, 0.0, w, h))
            painter.fillRect(self._blurred_pm.rect(), QColor(10, 10, 14, 185))
            painter.end()
        except Exception:
            self._blurred_pm = None

    def showEvent(self, event: QEvent) -> None:
        """Synchronize geometry with parent window and capture backdrop on open."""
        if self.parent_win:
            self.setGeometry(self.parent_win.rect())
            self._update_card_geometry()
            self._capture_blurred_backdrop()
        super().showEvent(event)

    def paintEvent(self, event: QEvent) -> None:
        """Paint blurred backdrop or dark translucent scrim."""
        painter = QPainter(self)
        if self._blurred_pm is not None:
            painter.drawPixmap(0, 0, self.width(), self.height(), self._blurred_pm)
        elif self.parent_win:
            painter.fillRect(self.rect(), QColor(10, 10, 14, 190))
        else:
            painter.fillRect(self.rect(), QColor(12, 12, 14, 210))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Dismiss dialog when clicking on the dark backdrop outside the central card."""
        if hasattr(self, "card"):
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if not self.card.geometry().contains(pos):
                self.accept()
                event.accept()
                return
        super().mousePressEvent(event)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        """Keep overlay geometry synchronized with parent window and handle search keypresses."""
        if self.parent_win and watched == self.parent_win and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent_win.rect())
            self._update_card_geometry()
            self.update()
        elif hasattr(self, "search_edit") and watched == self.search_edit and event.type() == QEvent.Type.KeyPress:
            key_event: QKeyEvent = event  # type: ignore
            if key_event.key() == Qt.Key.Key_Space and not self.search_edit.text().strip():
                self.accept()
                return True
            elif key_event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.accept()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Allow dismissal via Space or Escape keys."""
        if event.key() == Qt.Key.Key_Space:
            focus_w = self.focusWidget()
            if not isinstance(focus_w, (QLineEdit, QSpinBox, QComboBox)):
                self.accept()
                return
        elif event.key() == Qt.Key.Key_Escape:
            self.accept()
            return
        super().keyPressEvent(event)
