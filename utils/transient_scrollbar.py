"""Transient auto-hiding scrollbar controller for desktop applications."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QEvent, QObject, QPropertyAnimation, QTimer, Qt
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QScrollBar


class TransientScrollBarController(QObject):
    """Controls a QScrollBar to appear dynamically during scrolling and fade out when resting."""

    def __init__(
        self,
        scrollbar: QScrollBar,
        parent: Optional[QObject] = None,
        show_duration_ms: int = 800,
        fade_duration_ms: int = 250,
    ) -> None:
        super().__init__(parent)
        self._scrollbar: QScrollBar = scrollbar
        self._show_duration_ms: int = show_duration_ms
        self._fade_duration_ms: int = fade_duration_ms

        # Graphics opacity effect attached to the scrollbar widget
        self._opacity_effect: QGraphicsOpacityEffect = QGraphicsOpacityEffect(self._scrollbar)
        self._opacity_effect.setOpacity(0.0)
        self._scrollbar.setGraphicsEffect(self._opacity_effect)
        self._scrollbar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Inactivity rest timer
        self._hide_timer: QTimer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(self._show_duration_ms)
        self._hide_timer.timeout.connect(self._start_fade_out)

        # Smooth fade-out animation
        self._fade_anim: QPropertyAnimation = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(self._fade_duration_ms)
        self._fade_anim.finished.connect(self._on_fade_finished)

        # Connect scroll value changes and event filter for hover/interaction
        self._scrollbar.valueChanged.connect(self._on_value_changed)
        self._scrollbar.installEventFilter(self)

    @property
    def opacity(self) -> float:
        """Return the current opacity value of the scrollbar."""
        return self._opacity_effect.opacity()

    def show_transient(self) -> None:
        """Reveal the scrollbar at full opacity and begin the resting timer."""
        if self._scrollbar.maximum() <= 0:
            return

        if self._fade_anim.state() == QPropertyAnimation.State.Running:
            self._fade_anim.stop()

        self._opacity_effect.setOpacity(1.0)
        self._scrollbar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        if not (self._scrollbar.underMouse() or self._scrollbar.isSliderDown()):
            self._hide_timer.start(self._show_duration_ms)

    def hide_immediately(self) -> None:
        """Immediately reset the scrollbar to zero opacity without animation."""
        self._hide_timer.stop()
        self._fade_anim.stop()
        self._opacity_effect.setOpacity(0.0)
        self._scrollbar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def _start_fade_out(self) -> None:
        """Begin fading the scrollbar to transparent if user is not hovering or dragging."""
        if self._scrollbar.underMouse() or self._scrollbar.isSliderDown():
            self._hide_timer.start(self._show_duration_ms)
            return

        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def _on_fade_finished(self) -> None:
        """Disable mouse event absorption when the scrollbar becomes completely transparent."""
        if self._opacity_effect.opacity() <= 0.05:
            self._scrollbar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def _on_value_changed(self, value: int) -> None:
        """Trigger transient appearance whenever the scroll position updates."""
        self.show_transient()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Keep the scrollbar visible while hovered or actively dragged."""
        if watched == self._scrollbar:
            e_type = event.type()
            if e_type in (QEvent.Type.Enter, QEvent.Type.HoverEnter):
                self.show_transient()
            elif e_type == QEvent.Type.MouseButtonPress:
                self.show_transient()
                self._hide_timer.stop()
            elif e_type in (QEvent.Type.Leave, QEvent.Type.HoverLeave, QEvent.Type.MouseButtonRelease):
                if not self._scrollbar.isSliderDown():
                    self._hide_timer.start(self._show_duration_ms)
        return super().eventFilter(watched, event)
