"""Modern, sleek dark-themed date picker dialog for Note Taker."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Optional

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ModernDatePickerDialog(QDialog):
    """Modern dark-themed popup calendar dialog with quick buttons and keyboard navigation."""

    date_selected = pyqtSignal(object)  # Emits selected datetime.date

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        initial_date: Optional[date] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._selected_date: date = initial_date or date.today()
        self._view_year: int = self._selected_date.year
        self._view_month: int = self._selected_date.month

        self._day_buttons: list[QPushButton] = []
        self._day_dates: list[date] = []

        self._init_ui()
        self._refresh_calendar()

    @property
    def selected_date(self) -> date:
        """Return the finalized chosen date object."""
        return self._selected_date

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)

        # Container card with rounded dark frame
        self._container = QFrame(self)
        self._container.setObjectName("DatePickerContainer")
        self._container.setStyleSheet("""
            QFrame#DatePickerContainer {
                background-color: #1a1a20;
                border: 1px solid #363640;
                border-radius: 12px;
            }
        """)

        container_layout = QVBoxLayout(self._container)
        container_layout.setContentsMargins(14, 12, 14, 12)
        container_layout.setSpacing(10)

        # 1. Quick Select Action Row (Yesterday, Today, Tomorrow)
        quick_layout = QHBoxLayout()
        quick_layout.setSpacing(6)

        today = date.today()
        quick_options = [
            ("Yesterday", today - timedelta(days=1)),
            ("Today", today),
            ("Tomorrow", today + timedelta(days=1)),
        ]

        for label, d_val in quick_options:
            btn = QPushButton(label, self._container)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #24242c;
                    color: #c8c8d0;
                    border: 1px solid #383842;
                    border-radius: 6px;
                    font-size: 11px;
                    font-weight: 600;
                    padding: 5px 8px;
                }
                QPushButton:hover {
                    background-color: #0a84ff;
                    color: #ffffff;
                    border-color: #0a84ff;
                }
            """)
            btn.clicked.connect(lambda _, d=d_val: self._on_quick_date_clicked(d))
            quick_layout.addWidget(btn)

        container_layout.addLayout(quick_layout)

        # 2. Month Navigation Header Row
        nav_layout = QHBoxLayout()
        self._prev_btn = QPushButton("<", self._container)
        self._prev_btn.setFixedSize(28, 28)
        self._prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8e8e93;
                border: none;
                border-radius: 4px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2c2c36;
                color: #ffffff;
            }
        """)
        self._prev_btn.clicked.connect(self._prev_month)

        self._next_btn = QPushButton(">", self._container)
        self._next_btn.setFixedSize(28, 28)
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8e8e93;
                border: none;
                border-radius: 4px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2c2c36;
                color: #ffffff;
            }
        """)
        self._next_btn.clicked.connect(self._next_month)

        self._month_title_lbl = QLabel(self._container)
        self._month_title_lbl.setStyleSheet("color: #f5f5f7; font-size: 13px; font-weight: 700;")
        self._month_title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        nav_layout.addWidget(self._prev_btn)
        nav_layout.addWidget(self._month_title_lbl, 1)
        nav_layout.addWidget(self._next_btn)
        container_layout.addLayout(nav_layout)

        # 3. Day of week labels row
        d_layout = QHBoxLayout()
        d_layout.setSpacing(2)
        for day_abbr in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]:
            lbl = QLabel(day_abbr, self._container)
            lbl.setFixedSize(32, 18)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #787882; font-size: 10px; font-weight: 700;")
            d_layout.addWidget(lbl)
        container_layout.addLayout(d_layout)

        # 4. 7x6 Day Buttons Grid
        self._grid_layout = QGridLayout()
        self._grid_layout.setSpacing(2)

        for i in range(42):
            r, c = divmod(i, 7)
            btn = QPushButton(self._container)
            btn.setFixedSize(32, 30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, idx=i: self._on_day_clicked(idx))
            self._grid_layout.addWidget(btn, r, c)
            self._day_buttons.append(btn)

        container_layout.addLayout(self._grid_layout)
        root_layout.addWidget(self._container)

        self.resize(270, 320)

    def _refresh_calendar(self) -> None:
        """Render the days of the active month/year into the button grid."""
        month_name = calendar.month_name[self._view_month]
        self._month_title_lbl.setText(f"{month_name} {self._view_year}")

        cal = calendar.Calendar(firstweekday=0)
        days = list(cal.itermonthdates(self._view_year, self._view_month))
        self._day_dates = days[:42]

        today = date.today()
        for idx, d in enumerate(self._day_dates):
            btn = self._day_buttons[idx]
            btn.setText(str(d.day))

            is_cur_month = d.month == self._view_month
            is_selected = d == self._selected_date
            is_today = d == today

            if is_selected:
                style = """
                    QPushButton {
                        background-color: #0a84ff;
                        color: #ffffff;
                        font-weight: 700;
                        border-radius: 6px;
                        border: none;
                        font-size: 12px;
                    }
                """
            elif is_cur_month:
                border_str = "border: 1px solid #0a84ff;" if is_today else "border: none;"
                style = f"""
                    QPushButton {{
                        background-color: transparent;
                        color: #f5f5f7;
                        border-radius: 6px;
                        font-size: 12px;
                        {border_str}
                    }}
                    QPushButton:hover {{
                        background-color: #2c2c36;
                        color: #ffffff;
                    }}
                """
            else:
                style = """
                    QPushButton {
                        background-color: transparent;
                        color: #4a4a54;
                        border-radius: 6px;
                        border: none;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        background-color: #22222a;
                        color: #787882;
                    }
                """
            btn.setStyleSheet(style)

    def _on_day_clicked(self, idx: int) -> None:
        if 0 <= idx < len(self._day_dates):
            self._selected_date = self._day_dates[idx]
            self.date_selected.emit(self._selected_date)
            self.accept()

    def _on_quick_date_clicked(self, chosen_date: date) -> None:
        self._selected_date = chosen_date
        self.date_selected.emit(self._selected_date)
        self.accept()

    def _prev_month(self) -> None:
        if self._view_month == 1:
            self._view_month = 12
            self._view_year -= 1
        else:
            self._view_month -= 1
        self._refresh_calendar()

    def _next_month(self) -> None:
        if self._view_month == 12:
            self._view_month = 1
            self._view_year += 1
        else:
            self._view_month += 1
        self._refresh_calendar()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.date_selected.emit(self._selected_date)
            self.accept()
            return
        if key == Qt.Key.Key_Left:
            self._selected_date -= timedelta(days=1)
            self._view_year = self._selected_date.year
            self._view_month = self._selected_date.month
            self._refresh_calendar()
            return
        if key == Qt.Key.Key_Right:
            self._selected_date += timedelta(days=1)
            self._view_year = self._selected_date.year
            self._view_month = self._selected_date.month
            self._refresh_calendar()
            return
        if key == Qt.Key.Key_Up:
            self._selected_date -= timedelta(days=7)
            self._view_year = self._selected_date.year
            self._view_month = self._selected_date.month
            self._refresh_calendar()
            return
        if key == Qt.Key.Key_Down:
            self._selected_date += timedelta(days=7)
            self._view_year = self._selected_date.year
            self._view_month = self._selected_date.month
            self._refresh_calendar()
            return

        super().keyPressEvent(event)
