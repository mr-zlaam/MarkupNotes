"""Rendering engine for dynamic date cards in the Markdown editor canvas."""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen

from utils.date_format import format_dynamic_date
from utils.lucide_icons import render_lucide_pixmap


def render_date_card(
    painter: QPainter,
    card_rect: QRectF,
    target_date: date,
    ui_scale: float = 1.0,
    is_hovered: bool = False,
    has_focus: bool = False,
) -> None:
    """Render a rounded date card container matching the user reference design."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # 1. Card container background & border
    corner_r = round(10.0 * ui_scale, 1)
    border_col = QColor("#0a84ff") if (is_hovered or has_focus) else QColor("#444452")
    bg_col = QColor("#30303c") if is_hovered else QColor("#282832")

    painter.setPen(QPen(border_col, 1.0))
    painter.setBrush(QBrush(bg_col))
    painter.drawRoundedRect(card_rect, corner_r, corner_r)

    # 2. Calendar vector icon
    icon_size = max(16, int(round(18 * ui_scale)))
    icon_col = "#0a84ff" if is_hovered else "#9e9ea8"
    pix = render_lucide_pixmap("calendar", color=icon_col, size=icon_size)

    icon_x = card_rect.left() + round(18.0 * ui_scale)
    icon_y = card_rect.top() + (card_rect.height() - icon_size) / 2.0
    painter.drawPixmap(QPointF(icon_x, icon_y), pix)

    # 3. Dynamic date label
    display_text = format_dynamic_date(target_date)
    text_font = QFont("Cantarell", -1)
    text_font.setPixelSize(max(12, int(round(14 * ui_scale))))
    text_font.setWeight(QFont.Weight.Medium)
    painter.setFont(text_font)

    painter.setPen(QColor("#ffffff") if is_hovered else QColor("#f0f0f5"))
    text_x = icon_x + icon_size + round(12.0 * ui_scale)
    text_w = max(20.0, card_rect.right() - text_x - round(16.0 * ui_scale))
    text_rect = QRectF(text_x, card_rect.top(), text_w, card_rect.height())
    painter.drawText(
        text_rect,
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        display_text,
    )

    painter.restore()
