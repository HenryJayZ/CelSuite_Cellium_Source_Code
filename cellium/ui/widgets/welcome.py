#!/usr/bin/env python3
"""The welcome-page companion orb and its typewriter labels.

The old orb rendered a kaomoji string in a 14 px emoji font inside a 112 px
widget whose glow was *wider than the widget itself*. That gave it a hard,
clipped square edge, and some of the kaomoji glyphs (``≽^•⩊•^≼``,
``˶˃ᆺ˂˶``) are missing from common Linux emoji fonts - clicking could cycle
onto a face that simply did not render, which looked like the animation had
died.

This version paints the face directly with QPainter:

* no font fallback, no missing glyphs, no baseline drift;
* the glow always fits inside the widget (no clipping / square edges);
* blinking, cursor-tracking pupils, blush, sparkles and a squishy click
  bounce are all part of one 30 fps clock that never stops on click;
* big gem-cut eyes with irises, catch-lights and lashes, a pulsing
  forehead gem, and a tiny sweat-drop when flustered - the face is a
  character now, not two dots on a ball;
* **animated eyebrows** with an idle bob, mood poses and random "brow flash"
  raises, so the face is alive even when nothing is happening;
* six big, smoothly *blended* moods (calm / happy / curious / wink /
  surprised / flustered) with head tilt, gaze wandering and open-mouth
  shapes - no more tiny, hard-to-read expressions;
* :meth:`AnimatedFaceOrb.react_to` lets the app make the orb react to the
  chat it just opened (spicy history → flustered blush, question storm →
  curious, hype → happy). Blush itself is gated behind the companion
  gender setting via :meth:`set_blush_enabled`.
* **spam-click rage**: rapid clicking builds an annoyance meter; past the
  boiling point the orb pins an angry pose, its body cross-fades to red, a
  comic anger vein pulses, it trembles - and it *physically dashes to a new
  spot on the page* whenever the pointer comes near, hard-clamped so it can
  leave its spot but never the screen. Leave it alone and it cools down and
  glides back home.

``TypedLabel`` is a grapheme-safe typewriter QLabel: emoji + variation
selectors are revealed as single units, so a heart never flashes half-drawn.
"""

from __future__ import annotations

import math
import random
import time
import unicodedata

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QLabel, QWidget


# ───────────────────────────────────────────────────────────────────────────
# Grapheme-safe reveal
# ───────────────────────────────────────────────────────────────────────────
def _graphemes(text: str) -> list[str]:
    """Split into user-visible units without tearing emoji sequences apart.

    A naive ``text[i]`` reveal splits ``❤️`` (heart + VS16), ``👩‍💻``
    (ZWJ sequence) and keycaps into two frames. Grouping combining marks,
    variation selectors, ZWJ joins, skin tones and keycap marks keeps each
    glyph whole.
    """
    units: list[str] = []
    join_next = False
    for ch in text:
        code = ord(ch)
        modifier = (
            join_next
            or unicodedata.combining(ch) != 0
            or ch in ("\ufe0e", "\ufe0f", "\u20e3")
            or ch == "\u200d"
            or 0x1F3FB <= code <= 0x1F3FF
        )
        if units and modifier:
            units[-1] += ch
        else:
            units.append(ch)
        join_next = ch == "\u200d"
    return units


class TypedLabel(QLabel):
    """A QLabel that types itself in, one grapheme at a time."""

    CARET = "▍"

    def __init__(self, text: str = "", parent=None):
        super().__init__("", parent)
        self._full = str(text or "")
        self._units: list[str] = _graphemes(self._full)
        self._index = 0
        self._typing = False
        self._done_cb = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self._full:
            self.setText(self._full)

    @property
    def is_typing(self) -> bool:
        return self._typing

    def type_text(self, text: str, cps: int = 50, done=None) -> None:
        """Start a fresh typewriter reveal at roughly ``cps`` units/second."""
        self._timer.stop()
        self._full = str(text or "")
        self._units = _graphemes(self._full)
        self._index = 0
        self._typing = True
        self._done_cb = done
        self.setText("")
        self._timer.setInterval(max(10, int(1000 / max(8, int(cps)))))
        if self._units:
            self._timer.start()
        else:
            self.finish()

    def cancel(self) -> None:
        """Stop a reveal and clear the label (used before a new greeting)."""
        self._timer.stop()
        self._typing = False
        self._done_cb = None
        self._index = 0
        self.setText("")

    def finish(self) -> None:
        """Reveal everything instantly."""
        was_typing = self._typing
        self._timer.stop()
        self._typing = False
        self._index = len(self._units)
        self.setText(self._full)
        cb = self._done_cb
        self._done_cb = None
        if was_typing and callable(cb):
            cb()

    def _step(self) -> None:
        self._index += 1
        if self._index >= len(self._units):
            self.finish()
            return
        self.setText("".join(self._units[: self._index]) + self.CARET)


class GradientTypedLabel(TypedLabel):
    """TypedLabel that paints its text with a horizontal gradient (Gemini-style
    headline) instead of a flat stylesheet color. Typing/caret still works."""

    def __init__(self, text: str = "", stops=None, parent=None):
        super().__init__(text, parent)
        self._stops = stops or (
            (0.0, "#FFFFFF"), (0.45, "#E879F9"), (1.0, "#8A2BE2"),
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setFont(self.font())
        rect = self.rect()
        grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
        for pos, col in self._stops:
            grad.setColorAt(pos, QColor(col))
        p.setPen(QPen(QBrush(grad), 1))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, self.text())
        p.end()


# ───────────────────────────────────────────────────────────────────────────
# Painted companion orb
# ───────────────────────────────────────────────────────────────────────────
# Keyword pools for react_to() - the orb "peeks" at a chat and picks a mood.
_SPICY_WORDS = (
    "spicy", "nsfw", "lewd", "horny", "flirt", "flirty", "kiss", "kisses",
    "sexy", "naughty", "smut", "dirty", "seduct", "moan", "blush", "crush",
    "romance", "romantic", "cuddle", "make out", "hot and heavy", " risqué",
)
_WOW_WORDS = (
    "wow", "amazing", "awesome", "incredible", "haha", "lol", "lmao",
    "😂", "🤣", "🔥", "great job", "nice work", "let's go", "lets go",
)
_GASP_WORDS = ("omg", "whoa", "no way", "cannot believe", "can't believe")

#: Spam-click rage tuning. Each click adds ANNOY_PER_CLICK to the meter while
#: it decays ANNOY_DECAY per second - so ~3 rapid clicks boil over, but casual
#: clicking never accumulates. Past RAGE_TREMBLE the body trembles with rage.
ANNOY_PER_CLICK = 0.34
ANNOY_DECAY = 0.22
ANNOY_MAX = 2.2
RAGE_TREMBLE = 1.55
#: Dodge limits (px). The body radius leaves ~20 px of margin inside the
#: widget, so dodge + tremble + float + bounce always stay inside the bounds.
DODGE_MAX_X = 15.0
DODGE_MAX_Y = 8.0
#: Roaming flee tuning (px). Past FLEE_ANGER the orb stops merely leaning
#: away: it physically relocates its halo wrapper around the welcome page
#: whenever the pointer comes within FLEE_TRIGGER px, choosing a landing spot
#: a real FLEE_MIN_JUMP away and clamped FLEE_MARGIN inside the page.
FLEE_ANGER = 0.85
FLEE_TRIGGER = 260.0
FLEE_MIN_JUMP = 280.0
FLEE_COOLDOWN = 0.55
FLEE_MARGIN = 10.0


class AnimatedFaceOrb(QWidget):
    """A glossy little companion face that lives above the greeting.

    Everything is painted, so it looks identical on every machine. It floats,
    breathes, blinks on a random timer (with occasional double-blinks), its
    pupils track the cursor *and* wander on their own, the eyebrows bob and
    flash, the head tilts with the mood, and moods cross-fade into each other
    instead of snapping. Clicking squishes it - and never touches the clock.

    Spam-clicking is a different story: the orb keeps count, and past the
    boiling point it turns red, pulls an angry face, pulses a comic anger
    vein, trembles, and slides away from your cursor (clamped well inside
    its own bounds). Left alone, it cools off and forgives you. Eventually.
    """

    _MOODS = ("calm", "happy", "curious", "wink", "surprised", "flustered", "angry")

    # Per-mood target pose. Every value is a float so moods can cross-fade:
    #   brow_l/brow_r   brow lift -0.2..1 (1 = high arch, <0 = lowered)
    #   ang_l/ang_r     brow rotation in degrees (+ = inner end down = angry V)
    #   eye_ry          eye height scale (1 = normal, <1 squint, >1 wide)
    #   pupil           pupil size scale (<1 = tiny shocked pupils)
    #   eye_l/eye_r     per-eye openness (0 = closed → wink)
    #   smile           smile-curve amplitude (negative = frown)
    #   open/open_w     open-mouth height / half-width (0 = line mouth)
    #   blush           blush strength 0..1 (draw-gated by persona)
    #   tilt            head tilt in degrees
    #   look_x/look_y   where the eyes lean when idle
    _POSE = {
        "calm": dict(brow_l=0.10, brow_r=0.10, ang_l=0.0, ang_r=0.0,
                     eye_ry=1.0, pupil=1.0, eye_l=1.0, eye_r=1.0,
                     smile=0.13, open=0.0, open_w=0.105,
                     blush=0.0, tilt=0.0, look_x=0.0, look_y=0.0),
        # A warm, unmistakable smile: bright eyes, soft brows and a closed
        # upward curve - the boot face should read happy at a glance, not
        # sleepy or gasping.
        "happy": dict(brow_l=0.50, brow_r=0.50, ang_l=-5.0, ang_r=5.0,
                      eye_ry=0.80, pupil=1.08, eye_l=1.0, eye_r=1.0,
                      smile=0.19, open=0.0, open_w=0.19,
                      blush=0.55, tilt=2.5, look_x=0.0, look_y=0.15),
        "curious": dict(brow_l=0.90, brow_r=0.05, ang_l=-7.0, ang_r=3.0,
                        eye_ry=1.10, pupil=0.90, eye_l=1.0, eye_r=1.0,
                        smile=0.08, open=0.17, open_w=0.075,
                        blush=0.10, tilt=-6.0, look_x=0.40, look_y=-0.55),
        "wink": dict(brow_l=0.15, brow_r=0.75, ang_l=7.0, ang_r=-9.0,
                     eye_ry=1.0, pupil=1.0, eye_l=0.0, eye_r=1.0,
                     smile=0.16, open=0.0, open_w=0.165,
                     blush=0.45, tilt=7.0, look_x=0.25, look_y=0.0),
        "surprised": dict(brow_l=1.0, brow_r=1.0, ang_l=-3.0, ang_r=3.0,
                          eye_ry=1.48, pupil=0.66, eye_l=1.0, eye_r=1.0,
                          smile=0.0, open=0.85, open_w=0.10,
                          blush=0.0, tilt=0.0, look_x=0.0, look_y=-0.85),
        "flustered": dict(brow_l=0.42, brow_r=0.42, ang_l=-17.0, ang_r=17.0,
                          eye_ry=1.20, pupil=0.85, eye_l=1.0, eye_r=1.0,
                          smile=0.0, open=0.0, open_w=0.12,
                          blush=1.0, tilt=-4.0, look_x=-0.95, look_y=0.30),
        # Angry: V-brows (inner ends down), squint, deep frown, no blush  - 
        # the red body + dodge do the rest of the talking.
        "angry": dict(brow_l=-0.18, brow_r=-0.18, ang_l=20.0, ang_r=-20.0,
                      eye_ry=0.62, pupil=1.05, eye_l=1.0, eye_r=1.0,
                      smile=-0.14, open=0.0, open_w=0.125,
                      blush=0.0, tilt=0.0, look_x=0.0, look_y=-0.10),
    }

    def __init__(self, size: int = 150, theme_accent="#8A2BE2", parent=None):
        super().__init__(parent)
        self.orb_size = max(96, int(size))
        self.setFixedSize(self.orb_size, self.orb_size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click me for a lil bounce 💜")

        self.theme_accent = QColor(theme_accent)
        self.hovered = False

        self._clock = 0.0
        self._last_tick = time.monotonic()
        self._float = 0.0
        self._blink_t = -1.0
        self._blink_wait = random.uniform(1.8, 4.2)
        self._gaze = QPointF(0.0, 0.0)
        self._bounce = 0.0
        self._ring = 1.0
        self._pop = 0.0            # signed squash pulse on mood change
        self._mood = "happy"        # boot greeting: start smiling, not blank
        self._mood_left = 15.0      # hold the happy face through the first greeting
        self._mood_source = "pinned"  # keeps _roll_new_chat_greeting from overwriting it

        # Face pose (blended toward _POSE[self._mood] every tick).
        self._pose = dict(self._POSE[self._mood])
        self._target_pose = dict(self._pose)
        self._blush_ok = True       # persona gate - set_blush_enabled()
        self._blush_draw = 0.0      # effective blush level used by paint

        # Eyebrow flash scheduler: a quick surprised raise every few seconds.
        self._flash_t = -1.0
        self._flash_wait = random.uniform(2.5, 6.5)

        # Idle gaze wandering: eyes drift to random spots when not followed.
        self._wander = QPointF(0.0, 0.0)
        self._wander_wait = random.uniform(1.0, 3.0)

        # Spam-click rage state.
        self._annoy = 0.0           # annoyance meter (decays when left alone)
        self._anger = 0.0           # clamped 0..1 drive for red tint / dodge
        self._dodge = QPointF(0.0, 0.0)   # body offset away from the cursor
        self._look_away = QPointF(0.0, 0.0)
        self._tilt_away = 0.0       # lean away from the pointer
        self._jitter = QPointF(0.0, 0.0)  # trembling past the boiling point

        # Physical roaming: while raging the orb moves its own halo wrapper
        # around the host page, so it truly leaves its spot instead of just
        # nudging 15 px. The host + home anchor are injected by the window.
        self._roam_host = None
        self._roam_anchor = None
        self._roam_mover = None
        self._roam_pos = None       # current top-left in host coordinates
        self._roam_target = None    # landing spot top-left
        self._roam_cooldown = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ── public compatibility API ────────────────────────────────────────
    def set_accent(self, color) -> None:
        self.theme_accent = QColor(color)
        self.update()

    def trigger_blink(self) -> None:
        self._blink_t = 0.0

    def set_blush_enabled(self, enabled: bool) -> None:
        """Gate the blush: only on when the persona is Female (settings)."""
        self._blush_ok = bool(enabled)
        self.update()

    def set_mood(self, mood: str, hold: float = 4.0, pop: bool = True) -> None:
        """Pin a mood explicitly (app-driven). Blends in over ~0.3 s."""
        self._transition(mood, hold, pop=1.0 if pop else 0.0)
        self._mood_source = "pinned"

    def set_roam_area(self, host, anchor=None) -> None:
        """Let the orb physically dash around ``host`` when it boils over.

        ``host`` is the page the orb lives on; ``anchor`` is the widget whose
        centre is its home (usually the layout-managed slot). The orb moves
        its own wrapper, so the page layout never fights the dash, and every
        landing spot is clamped inside ``host`` - it leaves its spot, never
        the screen.
        """
        self._roam_host = host
        self._roam_anchor = anchor
        self._roam_mover = None
        self._roam_pos = None
        self._roam_target = None
        self._roam_cooldown = 0.0
        self._resolve_roam_mover()

    # ── rage roaming helpers ─────────────────────────────────────────────
    def _resolve_roam_mover(self):
        """The widget that physically travels: the halo wrapper if possible."""
        host = self._roam_host
        self._roam_mover = None
        if host is None:
            return None
        parent = self.parentWidget()
        if parent is host:
            self._roam_mover = self
        elif parent is not None and parent.parentWidget() is host:
            self._roam_mover = parent
        return self._roam_mover

    def _roam_home_pos(self) -> QPointF | None:
        """Top-left the orb should occupy when calm (anchor centre)."""
        host = self._roam_host
        mover = self._roam_mover
        if host is None or mover is None:
            return None
        anchor = self._roam_anchor
        try:
            if anchor is not None and anchor is not host:
                centre = anchor.mapTo(host, anchor.rect().center())
            else:
                centre = host.rect().center()
        except Exception:
            centre = host.rect().center()
        return QPointF(centre.x() - mover.width() / 2.0,
                       centre.y() - mover.height() / 2.0)

    def _roam_limits(self):
        """Clamp box for the mover's top-left, keeping it fully on the page."""
        host = self._roam_host
        mover = self._roam_mover
        if host is None or mover is None:
            return None
        r = host.rect().adjusted(FLEE_MARGIN, FLEE_MARGIN,
                                 -FLEE_MARGIN, -FLEE_MARGIN)
        x0, x1 = r.left(), r.right() - mover.width() + 1
        y0, y1 = r.top(), r.bottom() - mover.height() + 1
        if x1 < x0:
            x0 = x1 = r.left()
        if y1 < y0:
            y0 = y1 = r.top()
        return x0, x1, y0, y1

    def _cursor_host_pos(self) -> QPointF | None:
        """Pointer in host coordinates (overridable in tests)."""
        host = self._roam_host
        if host is None:
            return None
        try:
            if not host.isVisible():
                return None
            return QPointF(host.mapFromGlobal(QCursor.pos()))
        except Exception:
            return None

    def _pick_flee_target(self, cursor: QPointF) -> QPointF | None:
        """Sample landing spots and keep the farthest, liveliest one."""
        limits = self._roam_limits()
        mover = self._roam_mover
        if limits is None or mover is None:
            return None
        x0, x1, y0, y1 = limits
        w, h = mover.width(), mover.height()
        here = self._roam_pos or self._roam_home_pos() or QPointF(x0, y0)
        hx, hy = here.x() + w / 2.0, here.y() + h / 2.0
        best: QPointF | None = None
        best_score = -1e18
        for _ in range(48):
            x = random.uniform(x0, x1)
            y = random.uniform(y0, y1)
            mx, my = x + w / 2.0, y + h / 2.0
            away = math.hypot(mx - cursor.x(), my - cursor.y())
            jump = math.hypot(mx - hx, my - hy)
            # Ignore tiny shuffles - a flee has to actually leave the spot.
            if jump < FLEE_MIN_JUMP * 0.55:
                continue
            score = away + min(jump, 480.0) * 0.45 + random.uniform(0.0, 70.0)
            if score > best_score:
                best_score = score
                best = QPointF(x, y)
        if best is None:
            # Degenerate page size: bolt for the corner opposite the pointer.
            best = QPointF(x0 if cursor.x() > (x0 + x1) / 2.0 else x1,
                           y0 if cursor.y() > (y0 + y1) / 2.0 else y1)
        return best

    def _update_roam(self, dt: float) -> None:
        """Dash away from the pointer while raging; glide home when calm."""
        host = self._roam_host
        mover = self._roam_mover or self._resolve_roam_mover()
        if host is None or mover is None or not host.isVisible():
            return
        home = self._roam_home_pos()
        limits = self._roam_limits()
        if home is None or limits is None:
            return
        x0, x1, y0, y1 = limits
        home.setX(max(x0, min(x1, home.x())))
        home.setY(max(y0, min(y1, home.y())))
        if self._roam_pos is None:
            # First visible tick: snap home so the orb never flies in.
            self._roam_pos = QPointF(home)
            self._roam_target = QPointF(home)
            mover.move(round(home.x()), round(home.y()))
        self._roam_pos.setX(max(x0, min(x1, self._roam_pos.x())))
        self._roam_pos.setY(max(y0, min(y1, self._roam_pos.y())))

        raging = self._annoy >= FLEE_ANGER
        self._roam_cooldown = max(0.0, self._roam_cooldown - dt)
        cursor = self._cursor_host_pos() if raging else None
        if raging and cursor is not None:
            cx = self._roam_pos.x() + mover.width() / 2.0
            cy = self._roam_pos.y() + mover.height() / 2.0
            near = math.hypot(cx - cursor.x(), cy - cursor.y()) < FLEE_TRIGGER
            if near and self._roam_cooldown <= 0.0:
                target = self._pick_flee_target(cursor)
                if target is not None:
                    self._roam_target = target
                    self._roam_cooldown = FLEE_COOLDOWN
                    self._pop = max(self._pop, 0.45)
                    try:
                        mover.raise_()
                    except Exception:
                        pass
        elif not raging:
            self._roam_target = QPointF(home)
        if self._roam_target is None:
            self._roam_target = QPointF(home)
        self._roam_target.setX(max(x0, min(x1, self._roam_target.x())))
        self._roam_target.setY(max(y0, min(y1, self._roam_target.y())))

        # Fast, stable ease: ~0.3 s to cross a few hundred pixels, no jitter.
        step = min(1.0, dt * 9.5)
        self._roam_pos = self._roam_pos + (self._roam_target - self._roam_pos) * step
        if abs(self._roam_target.x() - self._roam_pos.x()) < 0.4:
            self._roam_pos.setX(self._roam_target.x())
        if abs(self._roam_target.y() - self._roam_pos.y()) < 0.4:
            self._roam_pos.setY(self._roam_target.y())
        mover.move(round(self._roam_pos.x()), round(self._roam_pos.y()))

    def react_to(self, text: str, hold: float = 8.0) -> str:
        """Pick a mood from the vibe of ``text`` (e.g. a chat's history).

        Spicy words → flustered (big blush), question storms → curious,
        hype → happy, gasps → surprised, otherwise a fresh random mood.
        Returns the chosen mood so callers can log/branch on it.
        """
        t = str(text or "").lower()
        if any(w in t for w in _SPICY_WORDS):
            mood = "flustered"
        elif t.count("?") >= 2 or any(w in t for w in ("why", "how come", "what if")):
            mood = "curious"
        elif any(w in t for w in _WOW_WORDS):
            mood = "happy"
        elif "!" in t or any(w in t for w in _GASP_WORDS):
            mood = "surprised"
        else:
            mood = self._pick_mood()
        self.set_mood(mood, hold=hold)
        return mood

    @property
    def mood(self) -> str:
        return self._mood

    @property
    def mood_source(self) -> str:
        return self._mood_source

    # ── events ───────────────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:
        """Squish + grin. Spam-clicking builds annoyance → red rage mode."""
        self._bounce = 1.0
        self._ring = 0.0
        self._pop = 1.0
        self._annoy = min(ANNOY_MAX, self._annoy + ANNOY_PER_CLICK)
        if self._annoy >= 1.0:
            # That's it. Angry, red, and dodging the pointer.
            self._transition("angry", max(2.5, 1.2 + self._annoy * 1.8), pop=1.0)
            self._mood_source = "pinned"
        elif self._annoy > 0.55 and self._mood == "angry":
            # Still grumbling from the last spam wave - stay angry.
            self._transition("angry", max(self._mood_left, 1.5), pop=0.0)
        else:
            self._transition(self._pick_mood(), 3.4, pop=0.0)
            self._mood_source = "auto"
        try:
            from cellium.services.sound_engine import play_ui_sound
            play_ui_sound("pop", 0.75)
        except Exception:
            pass
        self.update()
        event.accept()

    def enterEvent(self, event) -> None:
        self.hovered = True
        self.update()

    def leaveEvent(self, event) -> None:
        self.hovered = False
        self.update()

    def showEvent(self, event) -> None:
        self._last_tick = time.monotonic()
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.start()
        # Snap to the anchor before the first frame paints, so the orb never
        # flashes at (0, 0) while waiting for the 33 ms clock.
        self._update_roam(0.0)
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        # Qt may deliver hideEvent while the widget is being torn down, after
        # Python attributes are already cleared - never assume _timer exists.
        timer = getattr(self, "_timer", None)
        if timer is not None:
            timer.stop()
        super().hideEvent(event)

    # ── clock ────────────────────────────────────────────────────────────
    def _pick_mood(self) -> str:
        """Random playful mood - "angry" is earned by spam, never rolled."""
        choices = [m for m in self._MOODS
                   if m != self._mood and m != "angry"]
        return random.choice(choices or list(self._MOODS))

    def _transition(self, mood: str, hold: float, pop: float = 1.0) -> None:
        if mood not in self._POSE:
            return
        self._mood = mood
        self._target_pose = dict(self._POSE[mood])
        self._mood_left = max(0.6, float(hold))
        self._pop = max(self._pop, pop)

    def _cursor_local(self) -> QPointF:
        """Cursor position in widget coordinates (overridable in tests)."""
        return self.mapFromGlobal(QCursor.pos())

    def _cursor_in_window(self) -> QPointF | None:
        """Cursor in widget coordinates while it is inside this app window.

        The eyes follow the pointer anywhere in the window - not just while it
        hovers the orb - so the companion feels aware of you. ``None`` means
        the pointer left the app and the gaze should wander instead.
        """
        try:
            # Hovering already proves the pointer is on us - this also keeps
            # detached/test orbs (no visible window yet) working.
            if self.hovered:
                return QPointF(self._cursor_local())
            win = self.window()
            if win is None or not win.isVisible():
                return None
            global_pos = QCursor.pos()
            if not win.rect().contains(win.mapFromGlobal(global_pos)):
                return None
            return QPointF(self._cursor_local())
        except Exception:
            return None

    def _tick(self) -> None:
        now = time.monotonic()
        dt = max(0.001, min(0.08, now - self._last_tick))
        self._last_tick = now
        self._clock += dt
        self._float = math.sin(self._clock * 1.45) * 2.3
        self._bounce = max(0.0, self._bounce - dt * 2.5)
        self._ring = min(1.0, self._ring + dt * 1.8)
        if self._pop:
            step = min(abs(self._pop), dt * 3.2)
            self._pop -= math.copysign(step, self._pop)

        # Annoyance cools down when left alone; anger is its clamped form.
        self._annoy = max(0.0, self._annoy - dt * ANNOY_DECAY)
        self._anger = min(1.0, self._annoy)

        # Blink scheduler: close 0.09 s, hold 0.04 s, open 0.12 s - with a
        # cheeky 22 % chance of an immediate double-blink.
        if self._blink_t < 0.0:
            self._blink_wait -= dt
            if self._blink_wait <= 0.0:
                self._blink_t = 0.0
        else:
            self._blink_t += dt
            if self._blink_t >= 0.25:
                self._blink_t = -1.0
                if random.random() < 0.22:
                    self._blink_wait = 0.18
                else:
                    self._blink_wait = random.uniform(2.2, 5.2)

        # Brow-flash scheduler: a quick both-brows-up "oh!" every few seconds.
        if self._flash_t < 0.0:
            self._flash_wait -= dt
            if self._flash_wait <= 0.0:
                self._flash_t = 0.0
        else:
            self._flash_t += dt
            if self._flash_t >= 0.38:
                self._flash_t = -1.0
                self._flash_wait = random.uniform(2.8, 7.0)

        # Lazy mood drift keeps the face from feeling frozen/repetitive  - 
        # but an annoyed orb stays angry until it has cooled off.
        self._mood_left -= dt
        if self._mood_left <= 0.0:
            if self._annoy > 0.55:
                self._transition("angry", 2.0, pop=0.0)
            else:
                self._transition(self._pick_mood(), random.uniform(6.0, 10.5), pop=0.45)
            self._mood_source = "auto"

        # Cross-fade the face pose toward the mood target (~0.3 s blend).
        rate = min(1.0, dt * 9.0)
        for key, val in self._target_pose.items():
            cur = self._pose.get(key, 0.0)
            self._pose[key] = cur + (val - cur) * rate

        # Effective blush = mood blush × persona gate × calmness (+ hover).
        base_blush = self._pose.get("blush", 0.0) * (1.0 - self._anger)
        if not self._blush_ok:
            base_blush = 0.0
        hover_blush = 0.25 if (self.hovered and self._blush_ok) else 0.0
        self._blush_draw = max(0.0, min(1.0, base_blush + hover_blush))

        # Cursor position anywhere inside the app window - drives both the
        # window-wide gaze and the rage dodge.
        cursor_local = self._cursor_in_window()

        # Rage dodge: while annoyed, glare away from the pointer - and when
        # the pointer is actually on the orb, slide away from it like a tiny
        # mini-game, hard-clamped so the body never leaves the widget.
        dodge_t = QPointF(0.0, 0.0)
        tilt_away_t = 0.0
        self._look_away = QPointF(0.0, 0.0)
        if self._annoy > 0.15 and cursor_local is not None:
            half_w = max(1.0, self.width() / 2.0)
            half_h = max(1.0, self.height() / 2.0)
            dx = cursor_local.x() - half_w
            dy = cursor_local.y() - half_h
            dist = max(1.0, math.hypot(dx, dy))
            ux, uy = -dx / dist, -dy / dist
            intensity = min(1.0, self._annoy)
            self._look_away = QPointF(ux * 3.8, uy * 3.0)
            if self.hovered:
                dodge_t = QPointF(ux * DODGE_MAX_X * intensity,
                                  uy * DODGE_MAX_Y * intensity)
                tilt_away_t = -math.copysign(1.0, dx or 1.0) * 7.0 * intensity
        self._dodge += (dodge_t - self._dodge) * min(1.0, dt * 8.0)
        self._dodge.setX(max(-DODGE_MAX_X, min(DODGE_MAX_X, self._dodge.x())))
        self._dodge.setY(max(-DODGE_MAX_Y, min(DODGE_MAX_Y, self._dodge.y())))
        self._tilt_away += (tilt_away_t - self._tilt_away) * min(1.0, dt * 6.0)

        # Devil mode: physically relocate away from the pointer (or glide
        # back to the anchor once the rage has cooled off).
        self._update_roam(dt)

        # Trembling with rage past the boiling point.
        jitter_amp = 0.0
        if self._annoy > RAGE_TREMBLE:
            jitter_amp = min(1.6, (self._annoy - RAGE_TREMBLE) * 2.2)
        self._jitter = QPointF(random.uniform(-jitter_amp, jitter_amp),
                               random.uniform(-jitter_amp * 0.7, jitter_amp * 0.7))

        # Pupils: away-from-cursor when annoyed, window-wide cursor tracking
        # otherwise, and a lazy idle wander once the pointer leaves the app.
        if self._annoy > 0.15 and cursor_local is not None:
            target = QPointF(self._look_away)
        elif cursor_local is not None:
            half_w = max(1.0, self.width() / 2.0)
            half_h = max(1.0, self.height() / 2.0)
            tx = max(-1.0, min(1.0, (cursor_local.x() - half_w) / half_w))
            ty = max(-1.0, min(1.0, (cursor_local.y() - half_h) / half_h))
            target = QPointF(tx * 3.4, ty * 2.6)
        else:
            self._wander_wait -= dt
            if self._wander_wait <= 0.0:
                self._wander = QPointF(random.uniform(-0.6, 0.6),
                                       random.uniform(-0.4, 0.4))
                self._wander_wait = random.uniform(1.2, 3.5)
            target = QPointF(self._wander.x() * 3.0, self._wander.y() * 2.2)
        # Mood gaze bias on top (surprised looks up, flustered looks away).
        target += QPointF(self._pose.get("look_x", 0.0) * 2.2,
                          self._pose.get("look_y", 0.0) * 2.0)
        self._gaze += (target - self._gaze) * min(1.0, dt * 11.0)

        if self.isVisible():
            self.update()

    def _eye_openness(self) -> float:
        if self._blink_t < 0.0:
            return 1.0
        p = self._blink_t / 0.25
        if p < 0.36:
            return 1.0 - p / 0.36
        if p < 0.52:
            return 0.0
        return (p - 0.52) / 0.48

    # ── painting ─────────────────────────────────────────────────────────
    @staticmethod
    def _mix(c1: QColor, c2: QColor, t: float) -> QColor:
        """Blend two colours (t=0 → c1, t=1 → c2), keeping c1's alpha."""
        t = max(0.0, min(1.0, t))
        return QColor(int(c1.red() + (c2.red() - c1.red()) * t),
                      int(c1.green() + (c2.green() - c1.green()) * t),
                      int(c1.blue() + (c2.blue() - c1.blue()) * t),
                      c1.alpha())

    @staticmethod
    def _sparkle(painter: QPainter, x: float, y: float, r: float, color: QColor) -> None:
        path = QPainterPath()
        path.moveTo(x, y - r)
        path.quadTo(x + r * 0.18, y - r * 0.18, x + r, y)
        path.quadTo(x + r * 0.18, y + r * 0.18, x, y + r)
        path.quadTo(x - r * 0.18, y + r * 0.18, x - r, y)
        path.quadTo(x - r * 0.18, y - r * 0.18, x, y - r)
        path.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPath(path)

    def _paint_brows(self, painter: QPainter, base: float) -> None:
        """Animated eyebrows: mood lift/tilt + idle bob + random flash."""
        pose = self._pose
        eye_y = -base * 0.090
        eye_rx = base * 0.155
        eye_ry = base * 0.195 * pose.get("eye_ry", 1.0)
        brow_y = eye_y - eye_ry - base * 0.055
        brow_w = eye_rx * 1.35
        flash = 0.0
        if self._flash_t >= 0.0:
            p = min(1.0, self._flash_t / 0.38)
            flash = math.sin(math.pi * p) ** 1.5

        # A soft dark under-stroke keeps the brow readable over the glass
        # highlight; the white stroke on top gives it the cel-shaded pop.
        shadow = QPen(QColor(44, 16, 74, 135),
                      max(2.8, base * 0.050),
                      Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin)
        line = QPen(QColor(255, 250, 255, 242),
                    max(1.8, base * 0.032),
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for side, lift, ang in ((-1.0, pose.get("brow_l", 0.0), pose.get("ang_l", 0.0)),
                                (1.0, pose.get("brow_r", 0.0), pose.get("ang_r", 0.0))):
            bob = math.sin(self._clock * 2.3 + side * 1.9) * base * 0.011
            by = brow_y - lift * base * 0.085 - flash * base * 0.055 + bob
            bx = side * base * 0.305
            painter.save()
            painter.translate(bx, by)
            painter.rotate(ang)
            path = QPainterPath()
            path.moveTo(-brow_w, base * 0.022)
            path.quadTo(0.0, -base * 0.060, brow_w, base * 0.012)
            painter.setPen(shadow)
            painter.drawPath(path)
            painter.setPen(line)
            painter.drawPath(path)
            painter.restore()

    def _paint_forehead_gem(self, painter: QPainter, base: float) -> None:
        """A tiny pulsing gem on the forehead - Cel's signature sparkle."""
        gy = -base * 0.525
        gr = base * 0.070
        pulse = 0.5 + 0.5 * math.sin(self._clock * 2.6)
        rage = self._anger
        glow_c = self._mix(QColor(232, 190, 255), QColor(255, 196, 196), rage)
        glow = QRadialGradient(QPointF(0.0, gy), gr * 2.9)
        glow.setColorAt(0.0, QColor(glow_c.red(), glow_c.green(), glow_c.blue(),
                                    int(72 + 66 * pulse)))
        glow.setColorAt(0.55, QColor(glow_c.red(), glow_c.green(), glow_c.blue(),
                                     int(26 + 26 * pulse)))
        glow.setColorAt(1.0, QColor(glow_c.red(), glow_c.green(), glow_c.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(QPointF(0.0, gy), gr * 2.9, gr * 2.9)

        gem_c = self._mix(QColor(198, 132, 255), QColor(255, 170, 170), rage)
        path = QPainterPath()
        path.moveTo(0.0, gy - gr)
        path.lineTo(gr * 0.72, gy)
        path.lineTo(0.0, gy + gr)
        path.lineTo(-gr * 0.72, gy)
        path.closeSubpath()
        painter.setBrush(gem_c)
        painter.setPen(QPen(QColor(78, 32, 130, 210), max(1.1, base * 0.018)))
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 238))
        painter.drawEllipse(QPointF(-gr * 0.16, gy - gr * 0.18),
                            gr * 0.21, gr * 0.21)

    def _paint_horns(self, painter: QPainter, base: float, rage: float) -> None:
        """Two little demon horns fade in as the orb boils over.

        They are painted *before* the body so their roots hide behind the
        glossy head, and kept short enough that the body-plus-dodge envelope
        can never push a tip outside the widget.
        """
        alpha = int(238 * min(1.0, rage * 1.6))
        if alpha <= 4:
            return
        for side in (-1.0, 1.0):
            root_x = side * base * 0.44
            root_y = -base * 0.74
            tip_x = side * base * 0.70
            tip_y = -base * 1.01
            path = QPainterPath()
            path.moveTo(root_x - side * base * 0.13, root_y + base * 0.06)
            path.quadTo(side * base * 0.60, -base * 0.94, tip_x, tip_y)
            path.quadTo(side * base * 0.55, -base * 0.80,
                        root_x + side * base * 0.16, root_y + base * 0.04)
            path.closeSubpath()
            grad = QLinearGradient(root_x, root_y, tip_x, tip_y)
            grad.setColorAt(0.0, QColor(96, 8, 26, alpha))
            grad.setColorAt(0.62, QColor(196, 28, 48, alpha))
            grad.setColorAt(1.0, QColor(255, 116, 108, alpha))
            painter.setBrush(QBrush(grad))
            painter.setPen(QPen(QColor(62, 4, 16, alpha),
                                max(1.0, base * 0.014)))
            painter.drawPath(path)

    def _paint_eye(self, painter: QPainter, base: float, ex: float, ey: float,
                   rx: float, ry: float, openness: float,
                   gx: float, gy: float, side: float) -> None:
        """One big gem-cut eye: sclera, iris, pupil, catch-lights and lashes.

        ``openness`` is the blink/mood lid scale (0 = closed). The iris and
        pupil follow the gaze while the sclera stays anchored, which reads as
        a real eyeball instead of a sticker sliding across the face.
        """
        pose = self._pose
        ry_open = max(0.6, ry * openness)

        if openness < 0.18:
            path = QPainterPath()
            path.moveTo(ex - rx, ey + base * 0.012)
            path.quadTo(ex, ey - base * 0.078, ex + rx, ey + base * 0.012)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 250, 255, 238),
                                max(1.8, base * 0.040),
                                Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(path)
            # Two little outer lashes, even when the eye is shut.
            ox = ex + side * rx * 0.82
            oy = ey + base * 0.004
            lash_pen = QPen(QColor(58, 24, 92, 220),
                            max(1.2, base * 0.022),
                            Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap)
            painter.setPen(lash_pen)
            painter.drawLine(QPointF(ox, oy - base * 0.010),
                             QPointF(ox + side * rx * 0.38, oy - base * 0.052))
            painter.drawLine(QPointF(ox - side * rx * 0.20, oy - base * 0.020),
                             QPointF(ox + side * rx * 0.18, oy - base * 0.078))
            if self._mood == "wink" and side < 0.0:
                tw = 0.5 + 0.5 * math.sin(self._clock * 6.0)
                self._sparkle(painter, ex - rx * 1.35, ey - base * 0.05,
                              base * (0.045 + 0.020 * tw),
                              QColor(255, 236, 160, int(150 + 90 * tw)))
            return

        # Soft socket shadow makes the white sclera pop off the purple body.
        socket_rx = rx * 1.55
        socket_ry = max(rx * 1.05, ry_open * 1.28)
        socket = QRadialGradient(QPointF(ex, ey), max(socket_rx, socket_ry))
        socket.setColorAt(0.0, QColor(38, 10, 66, 62))
        socket.setColorAt(1.0, QColor(38, 10, 66, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(socket))
        painter.drawEllipse(QPointF(ex, ey), socket_rx, socket_ry)

        # Sclera: a hair of lavender at the bottom keeps it from looking flat.
        sclera = QLinearGradient(ex, ey - ry_open, ex, ey + ry_open)
        sclera.setColorAt(0.0, QColor(255, 252, 255, 250))
        sclera.setColorAt(1.0, QColor(239, 226, 250, 250))
        painter.setBrush(QBrush(sclera))
        painter.drawEllipse(QPointF(ex, ey), rx, ry_open)

        # Upper-lid shadow inside the sclera (the iris paints over it).
        lid = QLinearGradient(ex, ey - ry_open, ex, ey + ry_open * 0.10)
        lid.setColorAt(0.0, QColor(74, 32, 118, 78))
        lid.setColorAt(1.0, QColor(74, 32, 118, 0))
        painter.setBrush(QBrush(lid))
        painter.drawEllipse(QPointF(ex, ey), rx, ry_open)

        # Iris + pupil track the gaze together.
        ix = ex + gx * 0.45
        iy = ey + gy * 0.45
        iris_rx = rx * 0.70
        iris_ry = ry_open * 0.74
        # Rage turns the irises demon-red instead of the theme purple. Only
        # once the face has actually snapped to "angry" - a half-annoyed
        # smile should not get slit demon eyes yet.
        rage = self._anger if self._mood == "angry" else 0.0
        accent = self._mix(self.theme_accent, QColor(255, 60, 72), rage * 0.80)
        iris = QRadialGradient(QPointF(ix - rx * 0.18, iy - ry_open * 0.26),
                               max(1.0, iris_rx * 1.35))
        iris.setColorAt(0.0, self._mix(QColor(238, 218, 255),
                                       accent.lighter(160), 0.55))
        iris.setColorAt(0.45, accent.lighter(118))
        iris.setColorAt(1.0, accent.darker(215))
        painter.setBrush(QBrush(iris))
        painter.drawEllipse(QPointF(ix, iy), iris_rx, iris_ry)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(40, 14, 72, 150), max(0.8, base * 0.012)))
        painter.drawEllipse(QPointF(ix, iy), iris_rx, iris_ry)

        pupil_scale = pose.get("pupil", 1.0)
        # Narrow, tall slit pupils sell the demon look at full rage.
        pupil_rx = rx * 0.31 * pupil_scale * (1.0 - 0.38 * rage)
        pupil_ry = ry_open * 0.37 * pupil_scale * (1.0 + 0.08 * rage)
        pupil = QRadialGradient(QPointF(ix, iy - pupil_ry * 0.20),
                                max(1.0, pupil_rx * 1.5))
        pupil.setColorAt(0.0, QColor(62, 24, 92, 250))
        pupil.setColorAt(1.0, QColor(20, 5, 36, 252))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(pupil))
        painter.drawEllipse(QPointF(ix, iy + ry_open * 0.03), pupil_rx, pupil_ry)

        # Big soft catch-light + a smaller sparkle underneath.
        hl_x = ix - rx * 0.28
        hl_y = iy - ry_open * 0.30
        hl_r = max(1.1, min(rx * 0.30, ry_open * 0.34))
        hl = QRadialGradient(QPointF(hl_x, hl_y), hl_r)
        hl.setColorAt(0.0, QColor(255, 255, 255, 252))
        hl.setColorAt(0.72, QColor(255, 255, 255, 225))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(hl))
        painter.drawEllipse(QPointF(hl_x, hl_y), hl_r, hl_r)
        painter.setBrush(QColor(255, 255, 255, 205))
        painter.drawEllipse(QPointF(ix + rx * 0.24, iy + ry_open * 0.26),
                            max(0.8, rx * 0.13), max(0.8, rx * 0.11))

        # Thick upper lash line, with two flicks at the outer corner.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(48, 18, 80, 232),
                            max(1.6, base * 0.032),
                            Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        lid_path = QPainterPath()
        lid_path.moveTo(ex - rx * 1.02, ey - ry_open * 0.10)
        lid_path.quadTo(ex, ey - ry_open * 1.12, ex + rx * 1.02,
                        ey - ry_open * 0.10)
        painter.drawPath(lid_path)

        painter.setPen(QPen(QColor(58, 24, 92, 218),
                            max(1.2, base * 0.023),
                            Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        ox = ex + side * rx * 0.86
        oy = ey - ry_open * 0.54
        painter.drawLine(QPointF(ox, oy),
                         QPointF(ox + side * rx * 0.42, oy - ry_open * 0.38))
        painter.drawLine(QPointF(ox - side * rx * 0.20, oy - ry_open * 0.20),
                         QPointF(ox + side * rx * 0.20, oy - ry_open * 0.62))

        # A whisper of a lower lid grounds the eyeball in the face.
        painter.setPen(QPen(QColor(92, 48, 132, 90),
                            max(0.7, base * 0.011)))
        lower = QPainterPath()
        lower.moveTo(ex - rx * 0.88, ey + ry_open * 0.58)
        lower.quadTo(ex, ey + ry_open * 1.02, ex + rx * 0.88,
                     ey + ry_open * 0.58)
        painter.drawPath(lower)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        try:
            side = float(min(self.width(), self.height()))
            half = side / 2.0
            cx = self.width() / 2.0
            cy = self.height() / 2.0 + self._float - 4.5 * self._bounce
            # Rage dodge + trembling shift the whole body inside the widget.
            bcx = cx + self._dodge.x() + self._jitter.x()
            bcy = cy + self._dodge.y() + self._jitter.y()
            base = half - 20.0
            accent = self.theme_accent
            hover = 1.0 if self.hovered else 0.0
            pulse = 0.5 + 0.5 * math.sin(self._clock * 2.1)
            pose = self._pose
            rage = self._anger

            # Click shockwave ring (fades out as _ring → 1).
            if self._ring < 1.0:
                ring_r = base + 4.0 + 16.0 * self._ring
                alpha = int(110 * (1.0 - self._ring))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(
                    QColor(accent.red(), accent.green(), accent.blue(), alpha),
                    1.6))
                painter.drawEllipse(QPointF(bcx, bcy), ring_r, ring_r)

            # Halo: follows the body but is clamped to fit inside the widget,
            # so even a fully-dodged orb never shows a clipped edge.
            glow_r = min(half - 1.0, base + 6.0 + 3.0 * pulse + 4.0 * hover)
            fit = min(bcx, side - bcx, bcy, side - bcy) - 1.0
            glow_r = min(glow_r, max(6.0, fit))
            glow = QRadialGradient(QPointF(bcx, bcy), glow_r)
            glow_c = self._mix(QColor(accent.red(), accent.green(), accent.blue()),
                               QColor(255, 84, 92), rage * 0.9)
            glow.setColorAt(0.0, QColor(glow_c.red(), glow_c.green(), glow_c.blue(),
                                        int(118 + 34 * hover)))
            glow.setColorAt(0.55, QColor(glow_c.red(), glow_c.green(), glow_c.blue(),
                                         int(46 + 18 * hover)))
            glow.setColorAt(1.0, QColor(glow_c.red(), glow_c.green(), glow_c.blue(), 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(QPointF(bcx, bcy), glow_r, glow_r)

            # Orbiting sparkles, behind the body so they read as a halo.
            for i in range(3):
                ang = self._clock * 0.52 + i * math.tau / 3.0
                rad = base * 1.13 + 2.2 * math.sin(self._clock * 1.7 + i * 2.1)
                sx = bcx + math.cos(ang) * rad
                sy = bcy + math.sin(ang) * rad * 0.92
                alpha = int(80 + 70 * (0.5 + 0.5 * math.sin(self._clock * 2.3 + i * 1.7)))
                # Skip sparkles that a full dodge would clip at the edge.
                if 2.0 <= sx <= side - 2.0 and 2.0 <= sy <= side - 2.0:
                    self._sparkle(painter, sx, sy, max(1.6, base * 0.052),
                                  QColor(245, 208, 254, max(0, min(255, alpha))))

            # Squishy body: click bounce squashes wide, a surprised "gasp"
            # (negative _pop) stretches tall - both ease back to round.
            squash = 0.085 * self._bounce + 0.055 * self._pop
            sx = 1.0 + squash
            sy = 1.0 - squash * 0.8

            painter.save()
            painter.translate(bcx, bcy)
            painter.scale(sx, sy)

            # Demon horns fade in behind the glossy head as rage builds  - 
            # reserved for the angry face, not a half-annoyed smile.
            self._paint_horns(painter, base,
                              rage if self._mood == "angry" else 0.0)

            # Body gradient cross-fades to a hot angry red with rage.
            body = QRadialGradient(-base * 0.34, -base * 0.40, base * 1.34)
            if rage > 0.01:
                body.setColorAt(0.0, self._mix(accent.lighter(188), QColor(255, 136, 140), rage))
                body.setColorAt(0.40, self._mix(accent.lighter(116), QColor(242, 88, 98), rage))
                body.setColorAt(0.78, self._mix(accent, QColor(216, 50, 68), rage))
                body.setColorAt(1.0, self._mix(accent.darker(235), QColor(126, 18, 36), rage))
            else:
                body.setColorAt(0.0, accent.lighter(188))
                body.setColorAt(0.40, accent.lighter(116))
                body.setColorAt(0.78, accent)
                body.setColorAt(1.0, accent.darker(235))
            painter.setBrush(QBrush(body))
            painter.setPen(QPen(QColor(255, 255, 255, 118), max(1.0, base * 0.022)))
            painter.drawEllipse(QPointF(0.0, 0.0), base, base)

            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 34), max(0.8, base * 0.018)))
            painter.drawEllipse(QPointF(0.0, 0.0), base * 0.93, base * 0.93)

            # Glass highlight + specular pip.
            glass = QLinearGradient(-base * 0.58, -base * 0.78,
                                    base * 0.30, -base * 0.05)
            glass.setColorAt(0.0, QColor(255, 255, 255, 172))
            glass.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(glass))
            painter.drawEllipse(QPointF(-base * 0.24, -base * 0.39),
                                base * 0.53, base * 0.32)
            painter.setBrush(QColor(255, 255, 255, 205))
            painter.drawEllipse(QPointF(-base * 0.41, -base * 0.47),
                                base * 0.060, base * 0.042)
            painter.restore()

            # ── the face: tilted with the mood, squishing with the body ──
            painter.save()
            painter.translate(bcx, bcy)
            painter.rotate(pose.get("tilt", 0.0)
                           + math.sin(self._clock * 0.9) * 1.2
                           + self._tilt_away)
            painter.scale(sx, sy)

            eye_y = -base * 0.090
            eye_dx = base * 0.305
            eye_rx = base * 0.155
            eye_ry = base * 0.195 * pose.get("eye_ry", 1.0)
            gx, gy = self._gaze.x(), self._gaze.y()
            blink_open = self._eye_openness()

            # Blush (under the eyes, above the mouth) - persona-gated, and
            # suppressed while angry (the red body does that job). Two layers
            # (soft glow + solid core) so it pops against the purple.
            blush = self._blush_draw * (1.0 - rage)
            if blush > 0.03:
                painter.setPen(Qt.PenStyle.NoPen)
                brx = base * (0.170 + 0.040 * blush)
                bry = base * (0.095 + 0.022 * blush)
                bcx_blush = base * 0.47
                bcy_blush = base * 0.160
                for s in (-1.0, 1.0):
                    painter.setBrush(QColor(255, 130, 190, int(46 + 74 * blush)))
                    painter.drawEllipse(QPointF(s * bcx_blush, bcy_blush),
                                        brx * 1.25, bry * 1.3)
                    painter.setBrush(QColor(255, 142, 196, int(90 + 88 * blush)))
                    painter.drawEllipse(QPointF(s * bcx_blush, bcy_blush),
                                        brx, bry)

            # Forehead gem: Cel's signature sparkle.
            self._paint_forehead_gem(painter, base)

            # Eyebrows.
            self._paint_brows(painter, base)

            # Eyes - big gem-cut eyes with irises, catch-lights and lashes.
            for s, openness_side in ((-1.0, pose.get("eye_l", 1.0)),
                                     (1.0, pose.get("eye_r", 1.0))):
                ex = s * eye_dx + gx * 0.55
                ey = eye_y + gy * 0.55
                self._paint_eye(painter, base, ex, ey, eye_rx, eye_ry,
                                openness_side * blink_open, gx, gy, s)

            # Mouth: big per-mood shapes - open grin, gasp-O, wavy line or
            # deep angry frown.
            mouth_y = base * 0.255
            smile = pose.get("smile", 0.10)
            opn = pose.get("open", 0.0)
            mw = pose.get("open_w", 0.105) * 1.12
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 246, 255, 232),
                                max(1.8, base * 0.038),
                                Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            if opn > 0.12:
                # Open mouth: dark lens, cheeky tongue and a glossy lower lip.
                mh = base * (0.045 + 0.135 * opn)
                painter.setBrush(QColor(42, 12, 66, 238))
                painter.drawEllipse(QPointF(0.0, mouth_y), base * mw, mh)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 122, 170, 232))
                painter.drawEllipse(QPointF(0.0, mouth_y + mh * 0.45),
                                    base * mw * 0.55, mh * 0.42)
                painter.setBrush(QColor(255, 192, 218, 180))
                painter.drawEllipse(QPointF(-base * mw * 0.16,
                                            mouth_y + mh * 0.30),
                                    base * mw * 0.16, mh * 0.13)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(255, 214, 242, 120),
                                    max(0.7, base * 0.010),
                                    Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap))
                lip = QPainterPath()
                lip.moveTo(-base * mw * 0.86, mouth_y + mh * 0.55)
                lip.quadTo(0.0, mouth_y + mh * 0.95,
                           base * mw * 0.86, mouth_y + mh * 0.55)
                painter.drawPath(lip)
            elif self._mood == "flustered":
                # Embarrassed wavy "~_~" mouth.
                w = base * mw
                path = QPainterPath()
                path.moveTo(-w, mouth_y)
                path.quadTo(-w * 0.5, mouth_y - base * 0.065, 0.0, mouth_y)
                path.quadTo(w * 0.5, mouth_y + base * 0.065, w, mouth_y)
                painter.drawPath(path)
                # A little anime sweat-drop at the temple sells the fluster.
                sw = 0.5 + 0.5 * math.sin(self._clock * 4.0)
                sx = base * 0.66
                sy = -base * 0.20 - base * 0.035 * sw
                drop = QPainterPath()
                drop.moveTo(sx, sy - base * 0.078)
                drop.quadTo(sx + base * 0.058, sy + base * 0.018,
                            sx, sy + base * 0.058)
                drop.quadTo(sx - base * 0.058, sy + base * 0.018,
                            sx, sy - base * 0.078)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(150, 220, 255, 215))
                painter.drawPath(drop)
                painter.setBrush(QColor(255, 255, 255, 190))
                painter.drawEllipse(QPointF(sx - base * 0.016,
                                            sy + base * 0.012),
                                    base * 0.014, base * 0.020)
            else:
                amp = base * smile
                w = base * mw
                path = QPainterPath()
                path.moveTo(-w, mouth_y - amp * 0.30)
                path.quadTo(0.0, mouth_y + amp * 0.75, w, mouth_y - amp * 0.30)
                painter.drawPath(path)
                # Two tiny fangs peek out once the rage takes over.
                if rage > 0.25 and self._mood == "angry":
                    fa = max(0, min(255, int(248 * rage)))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(255, 250, 255, fa))
                    for side in (-1.0, 1.0):
                        fx = side * w * 0.40
                        fang = QPainterPath()
                        fang.moveTo(fx - base * 0.040, mouth_y - amp * 0.12)
                        fang.lineTo(fx + base * 0.040, mouth_y - amp * 0.12)
                        fang.lineTo(fx, mouth_y + base * 0.080)
                        fang.closeSubpath()
                        painter.drawPath(fang)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                # Soft lower-lip catch-light under the smile.
                if smile > 0.04:
                    painter.setPen(QPen(QColor(255, 214, 242, 85),
                                        max(0.7, base * 0.010),
                                        Qt.PenStyle.SolidLine,
                                        Qt.PenCapStyle.RoundCap))
                    lip = QPainterPath()
                    lip.moveTo(-w * 0.80, mouth_y + amp * 0.16)
                    lip.quadTo(0.0, mouth_y + amp * 0.72, w * 0.80,
                               mouth_y + amp * 0.16)
                    painter.drawPath(lip)

            # Comic anger vein (💢) pulsing at the top-right when pissed.
            if rage > 0.06:
                va = int(200 * rage * (0.72 + 0.28 * math.sin(self._clock * 9.0)))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(168, 24, 44, max(0, min(255, va))),
                                    max(1.6, base * 0.040),
                                    Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap,
                                    Qt.PenJoinStyle.RoundJoin))
                vx, vy = base * 0.50, -base * 0.56
                vr = base * 0.15
                vein_path = QPainterPath()
                for k in range(4):
                    a0 = math.tau * k / 4.0 + math.tau / 8.0
                    a1 = a0 + math.tau / 8.0
                    am = a0 + math.tau / 16.0
                    x1 = vx + math.cos(a0) * vr * 0.30
                    y1 = vy + math.sin(a0) * vr * 0.30
                    x2 = vx + math.cos(a1) * vr
                    y2 = vy + math.sin(a1) * vr
                    vmx = vx + math.cos(am) * vr * 0.60 - math.sin(am) * vr * 0.22
                    vmy = vy + math.sin(am) * vr * 0.60 + math.cos(am) * vr * 0.22
                    vein_path.moveTo(x1, y1)
                    vein_path.quadTo(vmx, vmy, x2, y2)
                painter.drawPath(vein_path)

            painter.restore()
        finally:
            painter.end()
