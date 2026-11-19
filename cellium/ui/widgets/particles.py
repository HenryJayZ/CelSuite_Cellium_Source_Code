"""Ambient purple dust background.

Qt widget. The original drifting-dust field (small violet/cyan motes rising
through the wallpaper), with two deliberate upgrades kept from the firefly
experiment:

- Zero-cost suspension: while an open chat is on screen the tick timer AND
  the cursor-poll timer are stopped outright - 0% CPU, not a single timer
  wakeup. The host window's ``chat_substack`` ``currentChanged`` signal
  resurrects them the moment the chat closes.
- Mouse play: the canvas is mouse-transparent, so ``mouseMoveEvent`` can
  never fire; the cursor is tracked by polling the global ``QCursor``
  (works under glass panels). A flick scatters the dust, and a resting or
  slowly moving cursor gathers a gentle orbiting halo around it.

Design notes
------------
- Bounded particle count with a hard cap so a high-DPI display cannot make
  the paint loop unbounded. One QTimer drives the whole field; no
  per-particle timers.
- Every tick repaints only the tiny rects each mote moved through - never
  the whole window (a full-window update() used to invalidate every glass
  panel 30x per second: 3796 button repaints / 5s and ~30% idle CPU).
- Intended to sit *behind* translucent panels, so it honours
  ``WA_TransparentForMouseEvents`` to avoid swallowing clicks.
"""

from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import Qt, QTimer, QRectF, Signal
from PySide6.QtGui import QColor, QCursor, QPainter
from PySide6.QtWidgets import QWidget

__all__ = ["Particle", "ParticleCanvas"]

_ACTIVE_MS = 45        # cursor is stirring the dust - ~22 fps
_SLEEP_MS = 550        # cursor idle > _IDLE_SLEEP_S - barely drifting
_IDLE_SLEEP_S = 10.0
_SCATTER_R = 110.0     # px: influence circle of a cursor flick
_ORBIT_R = 150.0       # px: halo a resting cursor gathers
_SCATTER_MIN = 8.0     # mouse speed above which the dust scatters
_MAX_PARTICLES = 256
_WALL = 16.0           # wrap margin


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "radius", "alpha", "hue", "wobble", "phase")

    def __init__(self, w: float, h: float, rng: random.Random):
        self.x = rng.uniform(0, w)
        self.y = rng.uniform(0, h)
        self.vx = rng.uniform(-2.2, 2.2)                 # px/s lateral drift
        self.vy = rng.uniform(-7.0, -2.0)                # gentle upward drift
        self.radius = rng.uniform(1.5, 3.8)
        self.alpha = rng.uniform(0.28, 0.80)
        self.hue = rng.choice((192, 258, 268, 286, 312))  # cyan → violet
        self.wobble = rng.uniform(0.3, 1.1)              # sway rate rad/s
        self.phase = rng.uniform(0, math.tau)

    def step(self, w: float, h: float, dt: float, rng: random.Random,
             mx: float, my: float, scat: bool, orbit: bool,
             speed: float) -> None:
        """Advance the drift. All motion maths is px/second."""
        self.phase = (self.phase + dt * self.wobble) % math.tau
        self.x += self.vx * dt
        self.y += (self.vy + math.sin(self.phase) * 3.0) * dt

        # Mouse play driven by the global-cursor poll, never by events (the
        # canvas is mouse-transparent, see module docstring).
        if mx > -9000.0:
            dx = self.x - mx
            dy = self.y - my
            d2 = dx * dx + dy * dy
            if scat and d2 < _SCATTER_R * _SCATTER_R:
                d = math.sqrt(d2)
                if d < 6.0:
                    d = 6.0
                f = (1.0 - d / _SCATTER_R) * min(120.0, 20.0 + speed * 1.8)
                self.x += dx / d * f * dt
                self.y += dy / d * f * dt
            elif orbit and d2 < _ORBIT_R * _ORBIT_R:
                d = math.sqrt(d2) + 1.0
                pull = (1.0 - d / _ORBIT_R) * 20.0
                self.x -= dx / d * pull * dt             # drawn toward cursor
                self.y -= dy / d * pull * dt
                self.x += -dy / d * pull * 0.7 * dt      # + slight swirl so
                self.y += dx / d * pull * 0.7 * dt       # they orbit, not pile

        # Wrap rather than bounce: cheaper and reads better as ambient fog.
        if self.y < -_WALL:
            self.y = h + _WALL
            self.x = rng.uniform(0, w)
        elif self.y > h + _WALL:
            # Repulsion can fling a particle BELOW the bottom; recycle it in
            # from the top like the upward wrap does.
            self.y = -_WALL
            self.x = rng.uniform(0, w)
        if self.x < -_WALL:
            self.x = w + _WALL
        elif self.x > w + _WALL:
            self.x = -_WALL


class ParticleCanvas(QWidget):
    """Animated dust field. Emits ``clicked`` on a direct click, which is
    only reachable where a host suspends the mouse transparency."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None,
                 count: int = 90,
                 interval_ms: int = 100,
                 opacity: float = 1.0,
                 seed: int | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._rng = random.Random(seed)
        self._count = max(0, min(_MAX_PARTICLES, int(count)))
        self._ambient_iv = max(140, int(interval_ms))
        self._interval = self._ambient_iv
        self._opacity = max(0.0, min(1.0, float(opacity)))
        self._paused = False
        self._mouse_pos = (-9999.0, -9999.0)
        self._mouse_speed = 0.0
        self._last_move_ms = time.monotonic()
        self._particles: list[Particle] = []
        self._last_ms = 0.0
        self._ensure_particles()
        # The "last size" MUST equal the box _ensure_particles() just spawned
        # into. Leaving it 0 made the first resizeEvent scale by width/1 and
        # teleport every particle out of the viewport - an empty (black)
        # 08_particles_wake screenshot.
        self._last_w, self._last_h = self._viewport()

        self._timer = QTimer(self)
        self._timer.setInterval(self._ambient_iv)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

        # Global cursor poll: mouse-transparency blocks mouseMoveEvent here on
        # purpose (a full-window overlay must never swallow clicks), so the
        # cursor is tracked via QCursor while the canvas stays glued to its
        # parent rect.
        self._cursor_poll = QTimer(self)
        self._cursor_poll.setInterval(120)
        self._cursor_poll.timeout.connect(self._poll_cursor)
        self._cursor_poll.start()

        # Zero-CPU suspension while an open chat is showing (module docstring).
        self._gate = None          # the host's chat_substack, once hooked
        self._hooked = False
        self._hook_page_gate()

    # ── lifecycle ────────────────────────────────────────────────────────
    def _viewport(self) -> tuple[int, int]:
        """Field size in px, floored at 1 (Qt reports 0 before the first layout)."""
        return max(1, self.width()), max(1, self.height())

    def _ensure_particles(self) -> None:
        w, h = self._viewport()
        while len(self._particles) < self._count:
            self._particles.append(Particle(float(w), float(h), self._rng))
        del self._particles[self._count:]

    def set_count(self, count: int) -> None:
        self._count = max(0, min(_MAX_PARTICLES, int(count)))
        self._ensure_particles()
        self.update()

    def set_opacity(self, opacity: float) -> None:
        self._opacity = max(0.0, min(1.0, float(opacity)))
        self.update()

    def start(self) -> None:
        self._paused = False
        if not self._chat_active():
            self._timer.start()
            self._cursor_poll.start()

    def stop(self) -> None:
        self._paused = True
        self._timer.stop()
        self._cursor_poll.stop()
        self._last_ms = 0.0
        self._mouse_speed = 0.0

    def dispose(self) -> None:
        self.stop()
        if self._gate is not None:
            try:
                self._gate.currentChanged.disconnect(self._resync_gate)
            except Exception:
                pass
            self._gate = None
        self._hooked = False
        self._particles.clear()

    def resizeEvent(self, event) -> None:
        # Proportional remap so the field always fills the viewport - particles
        # that merely keep their birth coords cluster in a corner when the
        # widget grows (caught by tools/regression.py's bounds check).
        old_w = float(max(1, self._last_w))
        old_h = float(max(1, self._last_h))
        w, h = self._viewport()
        sx, sy = w / old_w, h / old_h
        if (sx, sy) != (1.0, 1.0):
            for p in self._particles:
                p.x = min(w + 16.0, max(-16.0, p.x * sx))
                p.y = min(h + 16.0, max(-16.0, p.y * sy))
        self._last_w, self._last_h = w, h
        # Spawn AFTER the remap: brand-new particles already live in the new
        # viewport and must not be scaled a second time.
        self._ensure_particles()
        super().resizeEvent(event)

    # ── zero-CPU chat suspension ─────────────────────────────────────────
    def _chat_active(self) -> bool:
        """True while an open chat covers us - the user is reading messages."""
        top = self.window()
        if top is self:
            return False
        sub = getattr(top, "chat_substack", None)
        return sub is not None and sub.currentIndex() == 1   # 1 = chat page

    def _hook_page_gate(self) -> None:
        """Find the host's ``chat_substack`` once and ride ``currentChanged``.

        Attempted in __init__ and re-attempted by the cursor poll until it
        lands, so construction order never matters.
        """
        if self._hooked:
            return
        sub = getattr(self.window(), "chat_substack", None)
        if sub is None:
            return
        self._gate = sub
        sub.currentChanged.connect(self._resync_gate)
        self._hooked = True
        self._resync_gate()

    def _resync_gate(self) -> None:
        """Chat opened → stop BOTH timers outright (0% CPU, no wakeups).
        Chat closed → resurrect them instantly."""
        if self._paused:
            return
        if self._chat_active():
            self._timer.stop()
            self._cursor_poll.stop()
            self._last_ms = 0.0
            self._mouse_speed = 0.0
        else:
            self._timer.start()
            self._cursor_poll.start()

    # ── global cursor wake ────────────────────────────────────────────────
    def _poll_cursor(self) -> None:
        """Track the mouse through mouse-transparency + keep parent-glued."""
        if not self._hooked:
            self._hook_page_gate()
        if self._paused or not self.isVisible():
            self._mouse_speed = 0.0
            return
        par = self.parentWidget()
        if par is not None:
            rect = par.rect()
            try:
                if self.geometry() != rect:
                    self.setGeometry(rect)
            except Exception:
                pass
        gp = QCursor.pos()
        try:
            lp = self.mapFromGlobal(gp)
        except Exception:
            return
        nx, ny = float(lp.x()), float(lp.y())
        px, py = self._mouse_pos
        if -9000.0 < px < 9000.0 and -9000.0 < py < 9000.0:
            inside = 0 <= lp.x() <= self.width() and 0 <= lp.y() <= self.height()
            self._mouse_speed = min(60.0, math.hypot(nx - px, ny - py) * 14.0) if inside else 0.0
            if inside and (abs(nx - px) > 0.5 or abs(ny - py) > 0.5):
                self._last_move_ms = time.monotonic()
                # Wake instantly out of the sleepy tier instead of waiting a
                # full 550 ms for the next slow tick.
                if self._timer.interval() > 50:
                    self._timer.setInterval(_ACTIVE_MS)
        else:
            self._mouse_speed = 0.0
        self._mouse_pos = (nx, ny)

    # ── tick ─────────────────────────────────────────────────────────────
    @staticmethod
    def _app_active() -> bool:
        """False while the platform explicitly hides/suspends the app.

        ``ApplicationInactive`` fails OPEN: headless/offscreen runs report
        that state forever (no window manager), and since chat-page
        suspension now owns the drop to 0%, an unfocused-but-visible window
        only costs dirty-rect paints at the ambient tier anyway.
        """
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return True
            state = app.applicationState()
            if state == Qt.ApplicationState.ApplicationHidden:
                return False
            if getattr(Qt.ApplicationState, "ApplicationSuspended", None) == state:
                return False
            return True
        except Exception:
            return True

    def _on_tick(self) -> None:
        if self._paused or not self.isVisible():
            self._last_ms = 0.0
            return
        if not self._app_active():
            self._last_ms = 0.0
            self._mouse_speed = 0.0
            return
        # Safety net when the currentChanged hook never connects (e.g. a host
        # that names its stack differently): stop rather than burn CPU.
        if self._chat_active():
            self._timer.stop()
            self._cursor_poll.stop()
            self._last_ms = 0.0
            return
        # Monotonic delta so animation speed is frame-rate independent.
        now = time.monotonic()
        if self._last_ms == 0.0:
            self._last_ms = now
        dt = max(0.001, min(0.35, now - self._last_ms))
        self._last_ms = now

        w, h = float(self.width()), float(self.height())
        mx, my = self._mouse_pos
        speed = self._mouse_speed
        self._mouse_speed *= 0.82  # decay so the field settles when the mouse rests
        if speed > 0.6:
            self._last_move_ms = now
        alive = mx > -9000.0 and my > -9000.0
        scat = alive and speed >= _SCATTER_MIN
        orbit = (alive and not scat
                 and (now - self._last_move_ms < 2.0 or speed > 0.15))

        # Frame-rate tiers: stirred → 22 fps, ambient → ~7 fps, sleepy → 1.8 fps.
        idle_for = now - self._last_move_ms
        iv = _ACTIVE_MS if speed > 0.6 else (
            _SLEEP_MS if idle_for > _IDLE_SLEEP_S else self._ambient_iv)
        if self._timer.interval() != iv:
            self._timer.setInterval(iv)
            self._cursor_poll.setInterval(320 if iv > 300 else 120)

        dirty: list[tuple[float, float, float, float]] = []
        rng = self._rng
        sstep = Particle.step
        for part in self._particles:
            pad = part.radius + 2.0
            dirty.append((part.x - pad, part.y - pad, pad * 2.0, pad * 2.0))
            sstep(part, w, h, dt, rng, mx, my, scat, orbit, speed)
            dirty.append((part.x - pad, part.y - pad, pad * 2.0, pad * 2.0))
        for x, y, ww, hh in dirty:
            self.update(QRectF(x, y, ww, hh).toAlignedRect())

    # ── painting ─────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        if not self._particles or self._opacity <= 0.0:
            return
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(Qt.NoPen)
            base = self._opacity
            for part in self._particles:
                a = part.alpha * base
                if a <= 0.02:
                    continue
                colour = QColor.fromHsv(part.hue, int(0.62 * 255), 255)
                colour.setAlphaF(min(1.0, a))
                p.setBrush(colour)
                p.drawEllipse(QRectF(part.x - part.radius, part.y - part.radius,
                                     part.radius * 2, part.radius * 2))
        finally:
            p.end()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        # Only reached when a host disables mouse transparency; the ambient
        # path polls QCursor instead.
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        px, py = self._mouse_pos
        nx, ny = float(pos.x()), float(pos.y())
        if px > -9000.0:
            self._mouse_speed = min(60.0, math.hypot(nx - px, ny - py) * 14.0)
        self._last_move_ms = time.monotonic()
        self._mouse_pos = (nx, ny)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._mouse_pos = (-9999.0, -9999.0)
        self._mouse_speed = 0.0
        super().leaveEvent(event)
