"""Floating popup modal for choosing text color and background highlight color."""

from typing import Optional

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ColorPickerPopup(QFrame):
    """Small floating popup modal offering independent text color and highlight color palettes."""

    text_color_selected = pyqtSignal(str)  # Emits hex code or "" for default/reset
    highlight_color_selected = pyqtSignal(str)  # Emits hex code or "" for none/reset

    TEXT_COLORS: list[tuple[str, str, str]] = [
        ("", "#e0e0e4", "Default"),
        ("#8e8e93", "#8e8e93", "Gray"),
        ("#ff453a", "#ff453a", "Red"),
        ("#ff9f0a", "#ff9f0a", "Orange"),
        ("#ffd60a", "#ffd60a", "Yellow"),
        ("#30d158", "#30d158", "Green"),
        ("#0a84ff", "#0a84ff", "Blue"),
        ("#bf5af2", "#bf5af2", "Purple"),
        ("#ff375f", "#ff375f", "Pink"),
    ]

    HIGHLIGHT_COLORS: list[tuple[str, str, str]] = [
        ("", "transparent", "None"),
        ("#ffd60a", "#ffd60a", "Yellow"),
        ("#30d158", "#30d158", "Green"),
        ("#0a84ff", "#0a84ff", "Blue"),
        ("#bf5af2", "#bf5af2", "Purple"),
        ("#ff375f", "#ff375f", "Pink"),
        ("#ff453a", "#ff453a", "Red"),
        ("#ff9f0a", "#ff9f0a", "Orange"),
        ("#636366", "#636366", "Gray"),
    ]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setObjectName("ColorPickerPopup")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.setStyleSheet("""
            QFrame#ColorPickerPopup {
                background-color: #202024;
                border: 1px solid #36363a;
                border-radius: 8px;
            }
            QLabel#ColorSectionHeader {
                color: #8e8e93;
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-top: 1px;
                margin-bottom: 2px;
            }
            QPushButton#ColorSwatchBtn {
                border: 1px solid transparent;
                border-radius: 4px;
                min-width: 22px;
                max-width: 22px;
                min-height: 22px;
                max-height: 22px;
                padding: 0px;
            }
            QPushButton#ColorSwatchBtn:hover {
                border: 1px solid #ffffff;
            }
            QFrame#HColorDivider {
                background-color: #36363a;
                height: 1px;
                max-height: 1px;
                margin: 4px 0px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # 1. Text Color Section
        lbl_text = QLabel("Text Color", parent=self)
        lbl_text.setObjectName("ColorSectionHeader")
        layout.addWidget(lbl_text)

        row_text = QHBoxLayout()
        row_text.setSpacing(4)
        for hex_code, display_c, name in self.TEXT_COLORS:
            btn = QPushButton("A", parent=self)
            btn.setObjectName("ColorSwatchBtn")
            btn.setToolTip(f"{name} Text")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(
                f"QPushButton#ColorSwatchBtn {{ color: {display_c}; font-weight: bold; font-size: 12px; background-color: #2a2a30; }}"
            )
            btn.clicked.connect(lambda checked=False, c=hex_code: self._pick_text_color(c))
            row_text.addWidget(btn)
        layout.addLayout(row_text)

        # Divider
        divider = QFrame(parent=self)
        divider.setObjectName("HColorDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        # 2. Highlight Color Section
        lbl_hl = QLabel("Highlight Color", parent=self)
        lbl_hl.setObjectName("ColorSectionHeader")
        layout.addWidget(lbl_hl)

        row_hl = QHBoxLayout()
        row_hl.setSpacing(4)
        for hex_code, display_c, name in self.HIGHLIGHT_COLORS:
            btn = QPushButton(parent=self)
            btn.setObjectName("ColorSwatchBtn")
            btn.setToolTip(f"{name} Highlight")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if display_c == "transparent":
                btn.setText("×")
                btn.setStyleSheet(
                    "QPushButton#ColorSwatchBtn { color: #8e8e93; font-size: 14px; font-weight: bold; background-color: #2a2a30; }"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton#ColorSwatchBtn {{ background-color: {display_c}; border-radius: 4px; }}"
                )
            btn.clicked.connect(lambda checked=False, c=hex_code: self._pick_highlight_color(c))
            row_hl.addWidget(btn)
        layout.addLayout(row_hl)

        self.adjustSize()

    def _pick_text_color(self, hex_color: str) -> None:
        self.text_color_selected.emit(hex_color)
        self.hide()

    def _pick_highlight_color(self, hex_color: str) -> None:
        self.highlight_color_selected.emit(hex_color)
        self.hide()

    def show_below_widget(self, anchor_widget: QWidget) -> None:
        """Position and show the popup directly below the anchor widget, clamped to screen."""
        self.adjustSize()
        w = self.width()
        h = self.height()

        origin = anchor_widget.mapToGlobal(QPoint(0, anchor_widget.height() + 4))
        x = origin.x() - w + anchor_widget.width()
        y = origin.y()

        screen = anchor_widget.screen()
        if screen:
            geom = screen.availableGeometry()
            if x < geom.left() + 8:
                x = geom.left() + 8
            elif x + w > geom.right() - 8:
                x = geom.right() - w - 8

            if y + h > geom.bottom() - 8:
                # If overflow at bottom, show above anchor
                anchor_top = anchor_widget.mapToGlobal(QPoint(0, 0)).y()
                y = anchor_top - h - 4

        self.move(x, y)
        self.show()
        self.raise_()
