"""Call transition - the curtain that closes when you start a Live call.

Clicking **Live** used to snap the GUI away instantly, which felt like a window
disappearing rather than a call connecting. This paints a black curtain over the
whole window with a glowing ring that expands from the centre, holds while the
host proves the model is actually reachable, and then lifts to reveal Live Mode
underneath.

Three phases, all purely visual and interrupt-free:

* :meth:`CallTransition.play_in` - curtain closes (``covered`` fires at full
  opacity, which is when the host starts its connectivity check *behind* it).
* :meth:`CallTransition.fail` - the ring turns red and a floating error bubble
  explains why; 5 s (or ✕) later the curtain lifts back to chat without ever
  entering the call, and ``dismissed`` fires so the host can restore the wake
  listener and toast the reason.
* :meth:`CallTransition.play_out` - curtain lifts, revealing Cel (or chat).

The widget is parented to the host window and covers its full geometry, so it
also swallows clicks while it is up - no stray keystrokes reach the chat input
during the animation.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, Qt, QTimer, Property, Signal,
)
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

#: Ink black with a hint of Cel's purple, not pure #000.
_BACKDROP = QColor(4, 2, 14)
_RING = QColor(192, 132, 252)
_RING_SOFT = QColor(147, 51, 234)
#: Failure palette - the same geometry, dialled to alarm red.
_RING_FAIL = QColor(248, 113, 113)
_RING_FAIL_SOFT = QColor(190, 40, 60)

#: How long the red state + error bubble stay up before lifting by itself.
_FAIL_HOLD_MS = 5000


class CallTransition(QWidget):
    """Full-window curtain used for entering and leaving Live Mode."""

    covered = Signal()
    #: A failed connect finished lifting - the host is back in the chat.
    dismissed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._progress = 0.0
        self._pulse = 0.0
        self._caption = "Connecting to Cel…"
        self._on_covered: Optional[Callable[[], None]] = None
        self._closing = False
        #: True once fail() flipped the ring red (until fully lifted).
        self._failed = False
        #: True while the host owns the caption (connect-check cycler).
        self._hold_caption = False
        self._fail_done_pending = False
        self._err: Optional[QFrame] = None

        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(520)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self._anim.finished.connect(self._on_finished)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(33)
        self._pulse_timer.timeout.connect(self._on_pulse)

        self._fail_timer = QTimer(self)
        self._fail_timer.setSingleShot(True)
        self._fail_timer.setInterval(_FAIL_HOLD_MS)
        self._fail_timer.timeout.connect(self.dismiss)

    # ── animated property ─────────────────────────────────────────────────
    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = float(value)
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    # ── lifecycle ─────────────────────────────────────────────────────────
    def play_in(self, on_covered: Optional[Callable[[], None]] = None) -> None:
        """Close the curtain, then call ``on_covered`` at full opacity."""
        self._on_covered = on_covered
        self._closing = True
        self._failed = False
        self._hold_caption = False
        self._fail_done_pending = False
        self._fail_timer.stop()
        self._hide_error()
        self._caption = "Connecting to Cel…"
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self._pulse_timer.start()
        self._anim.stop()
        self._anim.setDuration(520)
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def play_out(self, on_done: Optional[Callable[[], None]] = None) -> None:
        """Lift the curtain to reveal whatever is underneath."""
        self._closing = False
        self._on_covered = on_done
        if not self._failed:
            self._caption = "Connected"
        self._fail_timer.stop()
        self._pulse_timer.start()
        self._anim.stop()
        self._anim.setDuration(460)
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def set_caption(self, text: str) -> None:
        """Let the host own the caption while the ring keeps breathing."""
        self._caption = str(text or "")
        self._hold_caption = True
        self.update()

    def fail(self, message: str) -> None:
        """Flip the ring red and float the reason for 5 s (✕ dismisses sooner).

        The curtain stays fully closed - the chat behind it was never hidden,
        so lifting after the hold drops the user right back into it.
        """
        self._failed = True
        self._hold_caption = True
        self._caption = "Couldn’t connect"
        self._show_error(str(message))
        self._pulse_timer.start()
        self._fail_timer.stop()
        self._fail_timer.start()
        self.update()

    def dismiss(self) -> None:
        """Leave the red state: lift the curtain, then emit ``dismissed``."""
        if not self._failed:
            return
        self._fail_timer.stop()
        self._fail_done_pending = True
        self.play_out()

    def _on_value(self, value: float) -> None:
        # Lift the caption in on the way out so it reads while still visible.
        self.update()

    def _on_pulse(self) -> None:
        self._pulse = (self._pulse + 0.055) % 1.0
        if self.isVisible():
            self.update()

    def _on_finished(self) -> None:
        cb, self._on_covered = self._on_covered, None
        if self._closing and self._progress >= 0.999:
            # Host may be holding the caption for its connect-check cycler  - 
            # do not stomp "Ringing…" with a premature "Connected".
            if not self._hold_caption:
                self._caption = "Connected"
            self.update()
            self.covered.emit()
            if cb is not None:
                # Must NOT restart an animation from inside its own finished
                # handler - Qt drops the start() and the curtain sticks fully
                # black for seconds. Defer to the next event loop tick.
                QTimer.singleShot(0, cb)
            return
        self._pulse_timer.stop()
        self.hide()
        if self._fail_done_pending:
            self._fail_done_pending = False
            self._failed = False
            self._hide_error()
            self.dismissed.emit()
        if cb is not None:
            cb()

    # ── error bubble ──────────────────────────────────────────────────────
    def _show_error(self, message: str) -> None:
        if self._err is None:
            fr = QFrame(self)
            fr.setStyleSheet(
                "QFrame{background: rgba(127, 29, 29, 0.6);"
                "border: 1.5px solid #F87171; border-radius: 14px;}"
                "QLabel{color: #FEE2E2; background: transparent;"
                " border: none; font-size: 13px; font-weight: 600;}"
                "QPushButton{background: rgba(248, 113, 113, 0.3);"
                " color: #FFF1F2; border: none; border-radius: 12px;"
                " padding: 5px 14px; font-weight: bold; font-size: 12px;}"
                "QPushButton:hover{background: #EF4444;}")
            lay = QVBoxLayout(fr)
            lay.setContentsMargins(18, 14, 18, 14)
            lay.setSpacing(8)
            lbl = QLabel(message)
            lbl.setWordWrap(True)
            lay.addWidget(lbl)
            row = QHBoxLayout()
            row.addStretch(1)
            x = QPushButton("✕  Back to chat")
            x.setCursor(Qt.CursorShape.PointingHandCursor)
            x.clicked.connect(self.dismiss)
            row.addWidget(x)
            lay.addLayout(row)
            self._err = fr
            self._err_lbl = lbl
        else:
            try:
                self._err_lbl.setText(message)
            except RuntimeError:
                return
        avail = max(280, self.width() - 80)
        self._err.setFixedWidth(min(520, avail))
        self._err.adjustSize()
        w, h = self._err.width(), self._err.height()
        x = max(8, (self.width() - w) // 2)
        y = int(self.height() * 0.5 + 130)
        y = max(8, min(self.height() - h - 16, y))
        self._err.setGeometry(x, y, w, h)
        self._err.show()
        self._err.raise_()

    def _hide_error(self) -> None:
        if self._err is not None:
            try:
                self._err.hide()
            except RuntimeError:
                self._err = None

    # ── paint ─────────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        p = max(0.0, min(1.0, self._progress))
        ring = _RING_FAIL if self._failed else _RING
        soft = _RING_FAIL_SOFT if self._failed else _RING_SOFT
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Curtain. Ease the alpha a touch slower than the ring so the ring
        # appears to lead the wipe.
        alpha = int(255 * min(1.0, p * 1.15))
        painter.fillRect(self.rect(), QColor(_BACKDROP.red(), _BACKDROP.green(),
                                             _BACKDROP.blue(), alpha))

        if p <= 0.001:
            painter.end()
            return

        cx, cy = self.width() / 2.0, self.height() / 2.0
        max_r = math.hypot(self.width(), self.height()) / 2.0

        # Expanding glow disc.
        r = max_r * p
        glow = QRadialGradient(cx, cy, max(1.0, r))
        glow.setColorAt(0.0, QColor(soft.red(), soft.green(), soft.blue(), 0))
        glow.setColorAt(0.82, QColor(soft.red(), soft.green(), soft.blue(),
                                     int(70 * p)))
        glow.setColorAt(1.0, QColor(ring.red(), ring.green(), ring.blue(),
                                    int(190 * p)))
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        # Breathing ring while "connecting" - the call is alive, not frozen.
        breathe = 0.5 + 0.5 * math.sin(self._pulse * math.tau)
        ring_r = max(24.0, min(96.0, self.width() * 0.075)) * (1.0 + 0.06 * breathe)
        pen = QPen(ring, max(2.0, 3.0 * p))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(int(cx - ring_r), int(cy - ring_r),
                            int(ring_r * 2), int(ring_r * 2))

        # Three orbiting dots, like a dialling tone made visual.
        for i in range(3):
            ang = (self._pulse * math.tau) + (i * math.tau / 3.0)
            dx = math.cos(ang) * ring_r * 0.62
            dy = math.sin(ang) * ring_r * 0.62
            dot = 5.0 * p + 2.0
            painter.setPen(QPen(Qt.PenStyle.NoPen))
            painter.setBrush(QBrush(QColor(ring.red(), ring.green(),
                                           ring.blue(), int(230 * p))))
            painter.drawEllipse(int(cx + dx - dot), int(cy + dy - dot),
                                int(dot * 2), int(dot * 2))

        # Outward particle streaks - they fly out as the curtain closes, so the
        # wipe feels like the call pulling you in rather than a sheet sliding.
        if p < 0.995:
            for i in range(28):
                seed = (i * 2654435761) % 1000 / 1000.0
                ang = seed * math.tau + self._pulse * 0.6
                dist = max_r * (0.25 + 0.85 * ((seed + p) % 1.0))
                px = cx + math.cos(ang) * dist
                py = cy + math.sin(ang) * dist
                fade = int(200 * p * (1.0 - ((seed + p) % 1.0)))
                if fade <= 4:
                    continue
                streak = max(2.0, 26.0 * p)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(ring.red(), ring.green(),
                                               ring.blue(), fade)))
                painter.drawEllipse(int(px - 1.5), int(py - 1.5), 3, 3)
                painter.setPen(QPen(QColor(ring.red(), ring.green(),
                                           ring.blue(), int(fade * 0.45)),
                                    max(1.0, 2.0 * p)))
                painter.drawLine(int(px), int(py),
                                 int(px - math.cos(ang) * streak),
                                 int(py - math.sin(ang) * streak))

        # Radar sweep - a rotating wedge, like a dial trying to lock on.
        sweep = self._pulse * math.tau
        painter.setPen(Qt.PenStyle.NoPen)
        for k in range(5):
            f = k / 5.0
            a2 = sweep - f * 0.9
            rr = ring_r * (1.35 + 0.5 * f)
            painter.setBrush(QBrush(QColor(ring.red(), ring.green(),
                                           ring.blue(),
                                           int(70 * p * (1.0 - f)))))
            px = cx + math.cos(a2) * rr
            py = cy + math.sin(a2) * rr
            d = max(2.0, 9.0 * p * (1.0 - f * 0.6))
            painter.drawEllipse(int(px - d), int(py - d), int(d * 2), int(d * 2))

        # Caption.
        if p > 0.35:
            font = QFont(self.font())
            font.setPointSize(13)
            font.setBold(True)
            painter.setFont(font)
            cap_a = int(255 * (p - 0.35) / 0.65)
            cap_color = QColor(254, 205, 220, cap_a) if self._failed \
                else QColor(233, 213, 255, cap_a)
            painter.setPen(QPen(cap_color))
            text = self._caption
            painter.drawText(self.rect().adjusted(0, int(ring_r * 1.9), 0, 0),
                             Qt.AlignmentFlag.AlignHCenter
                             | Qt.AlignmentFlag.AlignTop, text)

        painter.end()

# ══ WAVE_OMG_PARITY_START ══
# PC #30: Mathematical Sin/Cos Lissajous & Orbital Velocity Vortex Call Transition
if "CallTransition" in globals():
    def _math_vortex_paint_event(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        p.fillRect(self.rect(), QColor(10, 7, 22, 238))

        t = float(getattr(self, "_phase", 0.0) or (time.monotonic() * 2.6))
        self._phase = t + 0.045
        cx, cy = w * 0.5, h * 0.44
        base_r = min(w, h) * 0.16

        # 1. Breathing radial nebula glow
        pulse = 0.5 + 0.5 * math.sin(t * 2.2)
        glow = QRadialGradient(QPointF(cx, cy), base_r * (2.2 + 0.35 * pulse))
        glow.setColorAt(0.0, QColor(168, 85, 247, int(95 + 45 * pulse)))
        glow.setColorAt(0.45, QColor(56, 189, 248, int(45 + 25 * (1.0 - pulse))))
        glow.setColorAt(1.0, QColor(10, 7, 22, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), base_r * 2.5, base_r * 2.5)

        # 2. 3 Harmonic Lissajous / Rose curves with phase velocity
        for ring_i, (freq_a, freq_b, col_hex, alpha_v) in enumerate((
            (3.0, 2.0, "#C084FC", 185),
            (5.0, 4.0, "#38BDF8", 145),
            (7.0, 6.0, "#F472B6", 125),
        )):
            path = QPainterPath()
            steps = 96
            rot = t * (0.9 + ring_i * 0.35) * (1.0 if ring_i % 2 == 0 else -1.0)
            cos_r, sin_r = math.cos(rot), math.sin(rot)
            for s_i in range(steps + 1):
                theta = (s_i / float(steps)) * math.tau
                mod = 1.0 + 0.18 * math.sin(freq_a * theta + t * 2.4) * math.cos(freq_b * theta - t * 1.7)
                rx = math.cos(theta) * base_r * (0.78 + ring_i * 0.18) * mod
                ry = math.sin(theta) * base_r * (0.78 + ring_i * 0.18) * mod
                px = cx + rx * cos_r - ry * sin_r
                py = cy + rx * sin_r + ry * cos_r
                if s_i == 0:
                    path.moveTo(px, py)
                else:
                    path.lineTo(px, py)
            c = QColor(col_hex)
            c.setAlpha(alpha_v)
            p.setPen(QPen(c, 2.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        # 3. 18 Velocity-accelerated orbital particles with comet tails
        p.setPen(Qt.PenStyle.NoPen)
        for k in range(18):
            seed_ang = k * (math.tau / 18.0)
            vel = 1.6 + 0.65 * math.sin(t * 1.3 + k)
            ang = seed_ang + t * vel
            orbit_r = base_r * (0.55 + 0.62 * (0.5 + 0.5 * math.sin(t * 1.9 + k * 0.7)))
            ecc = 0.78 + 0.22 * math.cos(k * 1.1)
            ox = cx + math.cos(ang) * orbit_r
            oy = cy + math.sin(ang) * orbit_r * ecc
            dot_r = 2.8 + 2.2 * (0.5 + 0.5 * math.cos(t * 3.0 + k))
            col = QColor("#E879F9") if k % 3 == 0 else (QColor("#67E8F9") if k % 3 == 1 else QColor("#FDE047"))
            for tail in range(3):
                t_ang = ang - tail * 0.08 * vel
                tx = cx + math.cos(t_ang) * orbit_r
                ty = cy + math.sin(t_ang) * orbit_r * ecc
                tc = QColor(col)
                tc.setAlpha(int(220 / (tail + 1)))
                p.setBrush(tc)
                r_tail = dot_r * (1.0 - tail * 0.25)
                p.drawEllipse(QPointF(tx, ty), r_tail, r_tail)

        # 4. Crisp status caption
        caption = str(getattr(self, "_text", "") or getattr(self, "status_text", "") or "Connecting to Cel Live\u2026")
        f = QFont("Segoe UI", 13, QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(QColor("#F8F4FF"))
        p.drawText(QRectF(0, cy + base_r * 1.55, w, 36), Qt.AlignmentFlag.AlignCenter, caption)
        p.end()

    CallTransition.paintEvent = _math_vortex_paint_event
# ══ WAVE_OMG_PARITY_END ══
