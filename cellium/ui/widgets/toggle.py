"""Smooth animated toggle switch for Settings.

This module used to be an intentional empty shim (three modules star-import
it). It now owns the one toggle control the app uses for staged settings:
a pill track that glides between off/on with an OutCubic animation, a soft
neon glow, and a keyboard-accessible knob.

``ToggleSwitch`` is the bare control (no text); ``ToggleRow`` is the
label + switch row used by Settings. Both are Qt-only and safe to import
from any ``ui/`` module.
"""

from PySide6.QtCore import (
    Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal,
)
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPen,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

__all__ = ["ToggleSwitch", "ToggleRow"]


class ToggleSwitch(QWidget):
    """A smooth, animated on/off switch.

    The knob position is a real Qt property (``offset``, 0.0 → 1.0) so the
    animation interpolates in C++ and repaints at display refresh rate.
    """

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent=None,
                 width: int = 48, height: int = 27):
        super().__init__(parent)
        self._checked = bool(checked)
        self._offset = 1.0 if checked else 0.0
        self._hover = False
        self._pressed = False
        self._track_w = int(width)
        self._track_h = int(height)
        self.setFixedSize(self._track_w, self._track_h)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAccessibleName("Toggle")
        self.setAccessibleDescription("On" if checked else "Off")

        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(190)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ── Qt property used by QPropertyAnimation ─────────────────────────
    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = max(0.0, min(1.0, float(value)))
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    # ── state ─────────────────────────────────────────────────────────
    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, animate: bool = True) -> None:
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self.setAccessibleDescription("On" if checked else "Off")
        self._anim.stop()
        if animate and self.isVisible():
            self._anim.setStartValue(float(self._offset))
            self._anim.setEndValue(1.0 if checked else 0.0)
            self._anim.start()
        else:
            self._set_offset(1.0 if checked else 0.0)
        self.toggled.emit(checked)

    def toggle(self, animate: bool = True) -> None:
        self.setChecked(not self._checked, animate=animate)

    # ── input ─────────────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            if self.rect().contains(event.position().toPoint()):
                self.toggle()
            self.update()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.toggle()
            event.accept()
            return
        if key == Qt.Key.Key_Right:
            self.setChecked(True)
            event.accept()
            return
        if key == Qt.Key.Key_Left:
            self.setChecked(False)
            event.accept()
            return
        super().keyPressEvent(event)

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def sizeHint(self) -> QSize:
        return QSize(self._track_w, self._track_h)

    # ── paint ─────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            p.setOpacity(0.45)

        w, h = float(self.width()), float(self.height())
        track = QRectF(1.5, 1.5, w - 3.0, h - 3.0)
        radius = track.height() / 2.0

        # Outer neon halo - wider and brighter when on/hovered.
        if self._checked or self._hover:
            halo_alpha = 58 if self._checked else 30
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(192, 132, 252, halo_alpha), 4.0))
            p.drawRoundedRect(track.adjusted(-2.0, -2.0, 2.0, 2.0),
                              radius + 2.0, radius + 2.0)

        if self._checked:
            grad = QLinearGradient(track.topLeft(), track.topRight())
            grad.setColorAt(0.00, QColor("#7C3AED"))
            grad.setColorAt(0.55, QColor("#A855F7"))
            grad.setColorAt(1.00, QColor("#F472B6"))
            p.setBrush(grad)
            p.setPen(QPen(QColor(244, 114, 182, 210), 1.4))
        else:
            p.setBrush(QColor(28, 22, 46, 240))
            p.setPen(QPen(QColor(147, 51, 234, 155 if self._hover else 95), 1.4))
        p.drawRoundedRect(track, radius, radius)

        # Knob with a tiny drop shadow and a glossy highlight.
        knob_d = h - 8.0
        x0, x1 = 4.0, w - knob_d - 4.0
        kx = x0 + (x1 - x0) * self._offset
        knob = QRectF(kx, (h - knob_d) / 2.0, knob_d, knob_d)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(8, 4, 18, 90))
        p.drawEllipse(knob.translated(0.0, 1.3))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(knob)
        p.setBrush(QColor(255, 255, 255, 160))
        p.drawEllipse(knob.adjusted(2.0, 2.0, -knob_d * 0.46, -knob_d * 0.46))

        # Focus ring for keyboard users.
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(232, 121, 249, 190), 1.2,
                          Qt.PenStyle.DotLine))
            p.drawRoundedRect(track.adjusted(-3.5, -3.5, 3.5, 3.5),
                              radius + 3.5, radius + 3.5)
        p.end()


class ToggleRow(QWidget):
    """Label + description + :class:`ToggleSwitch` on one line."""

    toggled = Signal(bool)

    def __init__(self, text: str, checked: bool = False,
                 description: str = "", parent=None):
        super().__init__(parent)
        self.switch = ToggleSwitch(checked)
        self.switch.setAccessibleName(text)
        self.label = QLabel(text)
        self.label.setStyleSheet(
            "color: #F8F4FF; font-size: 13px; border: none; "
            "background: transparent;")
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label.setWordWrap(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 3, 0, 3)
        outer.setSpacing(2)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(12)
        top.addWidget(self.label, 1)
        top.addWidget(self.switch, 0)
        outer.addLayout(top)

        self.description = None
        if description:
            self.description = QLabel(description)
            self.description.setWordWrap(True)
            self.description.setStyleSheet(
                "color: #94A3B8; font-size: 11px; border: none; "
                "background: transparent;")
            outer.addWidget(self.description)

        self.label.mousePressEvent = lambda _e: self.switch.toggle()
        self.switch.toggled.connect(self.toggled.emit)

    def isChecked(self) -> bool:
        return self.switch.isChecked()

    def setChecked(self, checked: bool, animate: bool = True) -> None:
        self.switch.setChecked(checked, animate=animate)

    def toggle(self, animate: bool = True) -> None:
        self.switch.toggle(animate=animate)
