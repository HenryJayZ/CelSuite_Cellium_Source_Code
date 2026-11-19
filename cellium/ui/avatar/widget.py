"""Qt renderer for avatar expressions.

The archive's ``Cerebellium.py`` does **not** draw the face as connected lines.
Its ``Pixel.draw`` (``Cerebellium.py:853``) blits a small filled square per data
point::

    surf = pygame.Surface((self.size, self.size), pygame.SRCALPHA)
    surf.fill((r, g, b, self.alpha))
    surface.blit(surf, (int(actual_x), int(actual_y)))

with ``self.size = random.randint(5, 9)``. The face is therefore a **dot matrix**
 -  a glowing grid of particles, not a wireframe. Two examples from the data:

* ``eyelid`` for *Happy* is ten samples of one arc (``x`` steps of 10, ``y`` the
  curve height). Joined into a polyline it becomes a zigzag scribble.
* ``blush`` / ``perm_blush`` is literally a filled grid  - 
  ``range(150, 210, 20) x range(270, 290, 10)`` - so both cheeks must be drawn
  as separate dot clusters, never as one blob spanning the whole face.

This module reproduces that model. Every point becomes a soft dot whose size and
tint come from a *stable* hash of the expression and coordinates, so a face does
not shimmer on every repaint (the archive's per-process randomness caused exactly
that flicker) while still looking hand-scattered.

Blinking follows the archive's own mechanic (``Cerebellium.py:814, 832``): eyelid
dots slide **down** by the per-side ``depth`` parameter as the lid closes and
fade as they pass the eye. ``blink_left`` / ``blink_right`` and the per-side
speeds are honoured, so each eye can blink on its own clock.

The widget is a passive view: :meth:`AvatarView.set_expression` swaps the
expression, :meth:`AvatarView.blink_now` forces a blink, and nothing else is
required of the host.
"""

from __future__ import annotations

import math
import random
import zlib
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import QWidget

from .schema import AvatarExpression, AvatarPoint

__all__ = ["AvatarView", "AVATAR_PALETTE"]

AVATAR_PALETTE = {
    "outline": "#f4f4ff",
    "fill": "#1b1636",
    "blush": "#f472b6",
    "tear": "#7dd3fc",
    "sweat": "#bae6fd",
    "accent": "#c084fc",
    "dust": "#a78bfa",
}

#: Archive dot size range, in canonical 600x400 units.
DOT_MIN = 5.0
DOT_MAX = 9.0

#: Kinds that are pure-fill decorations rather than line work.
_BLUSH = ("blush", "perm_blush")

#: Draw order - blush first so line work reads on top (archive's layering).
_DRAW_ORDER = ("blush", "perm_blush", "eyelid", "eyebrow", "icon", "stem",
               "mid_bar", "bottom_bar", "tear", "cartoon_sweat",
               "exclamation", "dust")

#: Per-expression shake amplitude + vertical lift, straight from the archive's
#: ``Pixel.update`` (``Cerebellium.py:806+``). ``Happy``=1.2, ``Excited``=2.5,
#: ``Shocked``=3.5, ``Heavy Sobbing``=4.0 … this is what made the face feel alive.
SHAKE_TABLE = {
    "Excited": (2.5, -10.0), "Happy": (1.2, 0.0), "Shocked": (3.5, 0.0),
    "Angry": (3.0, 0.0), "Fearful": (2.1, 0.0), "Crying": (1.5, 0.0),
    "Heavy Sobbing": (4.0, 0.0), "Flustered": (2.5, 0.0), "Disgusted": (1.2, 0.0),
    "In Love": (1.0, 0.0), "Love and Hearts": (2.0, 0.0), "Blushing": (1.0, 0.0),
    "Pleading": (1.8, 0.0), "Nervous": (1.8, 0.0), "Winking": (0.6, 0.0),
}

#: Expressions that bob on a sine wave: (amplitude, period-ms divisor).
BOB_TABLE = {
    "Happy": (4.0, 0.005), "In Love": (5.0, 0.01),
    "Love and Hearts": (3.0, 0.01), "Shocked": (5.0, 0.05),
}


class _Dot:
    """One animated particle - the PySide6 port of the archive's ``Pixel``.

    ``x``/``y`` are the *live* position, ``tx``/``ty`` the target. The archive's
    ``self.rel_x += (tx - self.rel_x) * 0.2`` is exactly what makes expressions
    morph fluidly instead of snapping.
    """
    __slots__ = ("x", "y", "tx", "ty", "kind", "left", "seed", "alpha", "at", "ph")

    def __init__(self):
        # The archive spawns new particles at the origin and lets them converge.
        self.x = self.y = self.tx = self.ty = 0.0
        self.kind = "stem"
        self.left = True
        self.seed = ()
        self.alpha = 0.0
        #: Target alpha - dots *fade* between expressions instead of popping.
        self.at = 1.0
        #: Deterministic jitter phase (set in _rebuild_dots from the target,
        #: mirrored around x=300 so left/right dots breathe in sync).
        self.ph = 0.0


class AvatarView(QWidget):
    """Renders one :class:`AvatarExpression` as a dot-matrix face."""

    blink_started = Signal()
    blink_finished = Signal()

    def __init__(self, parent: QWidget | None = None,
                 expression: AvatarExpression | None = None,
                 blink_interval_ms: int = 4200,
                 blink_duration_ms: int = 130,
                 scale: float = 1.0,
                 palette: dict | None = None):
        super().__init__(parent)
        self._expr = _cel_norm_expr(expression, self)
        self._blink_t = 0.0
        self._blink_dur = max(0.03, blink_duration_ms / 1000.0)
        self._interval = max(0.5, blink_interval_ms / 1000.0)
        self._elapsed = 0.0
        self._blink_amount = 0.0
        self._scale = max(0.05, float(scale))
        self._plate = True
        self.palette = dict(AVATAR_PALETTE)
        if palette:
            self.palette.update(palette)
        self.setMinimumSize(160, 120)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()
        self._rng = random.Random(0xC3)
        self._last_ticked = 0

        # ── motion engine (archive Pixel.update / update_formation) ──
        self._dots: list = []
        self._time = 0.0
        self._shake = 0.6
        self._lift = 0.0
        self._bob = 0.0

    # ── state ────────────────────────────────────────────────────────────
    def set_expression(self, expression: Optional[AvatarExpression]) -> None:
        self._expr = _cel_norm_expr(expression, self)
        self._blink_amount = 0.0
        self._rebuild_dots()
        self.update()

    def expression(self) -> Optional[AvatarExpression]:
        return self._expr

    def set_scale(self, scale: float) -> None:
        self._scale = max(0.05, float(scale))
        self.update()

    def set_plate(self, enabled: bool) -> None:
        self._plate = bool(enabled)
        self.update()

    def blink_now(self) -> None:
        # Manual blink button should always work, even on expressions whose
        # auto-blink is disabled (e.g. "deadpan", "sleepy").
        if self._expr is not None:
            self._blink_t = 0.0001
            self._blink_amount = 1.0
            self.blink_started.emit()
            self.update()

    def stop(self) -> None:
        self._timer.stop()

    def dispose(self) -> None:
        self._timer.stop()
        self._expr = None
        self._dots = []

    # ── motion engine ────────────────────────────────────────────────────
    def _rebuild_dots(self) -> None:
        """Assign targets to the particle pool - the archive's ``update_formation``.

        Pool is persistent, so switching expression keeps every dot's current
        position and it *eases* to the new formation instead of teleporting.
        """
        expr = self._expr
        if expr is None:
            for d in self._dots:
                d.at = 0.0       # fade out; _advance eases alpha to match
            return
        groups = expr.by_kind()
        targets = []
        for kind in _DRAW_ORDER:
            pts = groups.get(kind)
            if not pts:
                continue
            for side, group in self._grouped(pts).items():
                for dot_idx, p in enumerate(group):
                    targets.append((kind, side, p, dot_idx))
        while len(self._dots) < len(targets):
            nd = _Dot()
            nd.alpha = 0.0
            nd.at = 0.0          # born invisible - fades in from the origin
            self._dots.append(nd)
        for i, d in enumerate(self._dots):
            if i >= len(targets):
                d.at = 0.0       # surplus dots fade out instead of vanishing
                continue
            kind, side, p, dot_idx = targets[i]
            d.kind, d.left = kind, side
            d.tx, d.ty = float(p.x), float(p.y)
            d.at = 1.0
            # Symmetrical jitter phase: mirrored left and right dots share
            # the exact same feature kind and local index phase so both eyes
            # shake with perfectly balanced, synchronous force.
            _phkey = ("%s:%d" % (kind, dot_idx)).encode()
            d.ph = (zlib.crc32(_phkey) & 0xFFFF) / 0xFFFF * 6.2832
            d.seed = (expr.name, kind, side, i, round(p.x, 2), round(p.y, 2))

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        curr_x, curr_y = pos.x(), pos.y()
        prev_x, prev_y = getattr(self, "_mouse_pos", (curr_x, curr_y))
        self._mouse_velocity = math.hypot(curr_x - prev_x, curr_y - prev_y)
        self._mouse_pos = (curr_x, curr_y)
        self._mouse_active = True
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._mouse_active = False
        self._mouse_velocity = 0.0
        super().leaveEvent(event)

    def _advance(self) -> None:
        """Ease every dot home, apply mouse repulsion spring physics, and jitter."""
        self._time += 0.033
        if self._expr is None:
            name = ""
        elif isinstance(self._expr, str):
            name = self._expr
        else:
            name = getattr(self._expr, "name", "")
        self._shake, self._lift = SHAKE_TABLE.get(name, (0.6, 0.0))
        amp, period = BOB_TABLE.get(name, (2.0, 0.004))
        self._bob = math.sin(self._time * period * 1000.0) * amp
        k = 0.2
        s = self._shake

        mx, my = getattr(self, "_mouse_pos", (-999, -999))
        mouse_on = getattr(self, "_mouse_active", False)
        velocity = getattr(self, "_mouse_velocity", 0.0)
        self._mouse_velocity = max(0.0, velocity * 0.85)

        # Convert screen mouse pos to canonical coordinate space (600x400)
        sc = self._scale
        w, h = self.width(), self.height()
        ox = (w - 600.0 * sc) / 2.0
        oy = (h - 400.0 * sc) / 2.0
        canon_mx = (mx - ox) / max(0.01, sc)
        canon_my = (my - oy) / max(0.01, sc)

        for d in self._dots:
            if abs(d.at - d.alpha) > 0.004:
                d.alpha += (d.at - d.alpha) * 0.16
            else:
                d.alpha = d.at
            if d.alpha <= 0.004 and d.at <= 0.0:
                continue

            # Pixel repulsion: only push pixels away if mouse is moving
            if mouse_on and velocity > 1.2:
                cdx = d.x - canon_mx
                cdy = d.y - canon_my
                cdist = math.hypot(cdx, cdy)
                if 0.1 < cdist < 55.0:
                    force = (1.0 - cdist / 55.0) * min(velocity * 0.35, 6.0)
                    d.x += (cdx / cdist) * force
                    d.y += (cdy / cdist) * force

            # Clamp displacement to max 28px from home (prevent offscreen glitch)
            offset_x = d.x - d.tx
            offset_y = d.y - d.ty
            offset_dist = math.hypot(offset_x, offset_y)
            if offset_dist > 28.0:
                d.x = d.tx + (offset_x / offset_dist) * 28.0
                d.y = d.ty + (offset_y / offset_dist) * 28.0

            # Spring relaxation returning home
            d.x += (d.tx - d.x) * k
            d.y += (d.ty - d.y) * k
            # Deterministic mirrored breathing - smooth sines on the shared
            # per-target phase, NOT per-frame uniform noise. Independent noise
            # let one eye's dots randomly gang up at 3–4x the other's
            # amplitude (the seizure); sines keep both eyes at exactly the
            # table's force, forever in sync.
            d.x += math.sin(self._time * 7.3 + d.ph) * s
            d.y += math.cos(self._time * 5.9 + d.ph * 1.31) * s

    # ── blink driver ─────────────────────────────────────────────────────
    def _on_tick(self) -> None:
        # Skip the per-dot motion math while this view is on a hidden page  - 
        # the timer keeps running, but a hidden avatar has nobody watching it.
        if not self.isVisible():
            return
        self._elapsed += 0.033
        self._advance()
        self.update()
        e = self._expr
        if e is None or not e.blink_enabled:
            self._blink_amount = 0.0
            return
        if self._blink_t > 0.0:
            self._blink_t += 0.033
            if self._blink_t >= self._blink_dur:
                self._blink_t = 0.0
                self._blink_amount = 0.0
                self.blink_finished.emit()
                self.update()
                return
            frac = self._blink_t / self._blink_dur
            # Fast close, slower reopen.
            self._blink_amount = (frac / 0.35) if frac < 0.35 else (1.0 - (frac - 0.35) / 0.65)
            self.update()
            return
        if self._elapsed >= self._interval:
            self._elapsed = 0.0
            # Real people don't blink on a metronome - re-roll the gap.
            self._interval = 2.6 + self._rng.random() * 3.4
            self._blink_amount = 1.0
            self._blink_t = 0.0001
            self.blink_started.emit()
            self.update()

    def _lid_amount(self, side_left: bool) -> float:
        e = self._expr
        if e is None:
            return 0.0
        if side_left and not e.blink_left:
            return 0.0
        if (not side_left) and not e.blink_right:
            return 0.0
        return max(0.0, min(1.0, self._blink_amount))

    # ── geometry ─────────────────────────────────────────────────────────
    def _to_screen(self, p: AvatarPoint, dy: float = 0.0):
        """Stored (0..600, 0..400) space -> widget pixels."""
        s = self._scale
        w, h = self.width(), self.height()
        ox = (w - 600.0 * s) / 2.0
        oy = (h - 400.0 * s) / 2.0
        return QPointF(ox + p.x * s, oy + (p.y + dy) * s)

    # ── appearance ───────────────────────────────────────────────────────
    @staticmethod
    def _rand(seed_parts) -> float:
        """Stable 0..1 from a tuple - identical on every run, so no flicker."""
        key = "|".join(str(v) for v in seed_parts).encode("utf-8", "replace")
        return (zlib.crc32(key) & 0xFFFFFFFF) / 0xFFFFFFFF

    def _dot_size(self, point: AvatarPoint, seed_parts) -> float:
        r = self._rand(seed_parts)
        return DOT_MIN + (DOT_MAX - DOT_MIN) * r

    def _colour(self, kind: str, r: float) -> QColor:
        """Archive colours, keyed by particle type."""
        if kind in _BLUSH:
            return QColor(255, 105, 180)
        if kind == "tear":
            return QColor(0, 150, 255)
        if kind == "cartoon_sweat":
            return QColor(186, 230, 253)
        if kind == "exclamation":
            return QColor(255, 50, 50)
        if kind == "dust":
            return QColor(self.palette["dust"])
        if kind == "stem":
            return QColor(self.palette["outline"])
        # Default particle tint: the archive's random magenta family
        # (random.randint(100,180), 0, random.randint(180,255)).
        return QColor(int(120 + r * 70), 0, int(195 + r * 60))

    @staticmethod
    def _grouped(pts):
        out = {}
        for p in pts:
            out.setdefault(p.left, []).append(p)
        return out

    # ── main paint ───────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        expr = self._expr
        if expr is None:
            painter.end()
            return

        scale = self._scale

        # Face plate - a faint backdrop so the dots have something to sit on.
        if self._plate:
            origin = self._to_screen(AvatarPoint(0, 0, "plate", True))
            plate = QRectF(origin.x(), origin.y(), 600 * scale, 400 * scale)
            fill = QColor(self.palette["fill"])
            fill.setAlpha(70)
            painter.setPen(QPen(Qt.PenStyle.NoPen))
            painter.setBrush(QBrush(fill))
            painter.drawRoundedRect(plate, 40 * scale, 40 * scale)

        # Global fade (schema: fade_opacity 0..1)
        if expr.fade_opacity > 0.0:
            painter.setOpacity(max(0.0, min(1.0, 1.0 - expr.fade_opacity)))

        # Blush goes down first so line work reads on top of it.
        for d in self._dots:
            if d.alpha <= 0.0:
                continue
            # Archive blink: eyelid dots slide down by the per-side depth and
            # fade out as they pass the eye.
            drop = 0.0
            fade = 1.0
            if d.kind == "eyelid":
                amount = self._lid_amount(d.left)
                if amount > 0.0:
                    depth = expr.left_depth if d.left else expr.right_depth
                    drop = amount * max(0.0, float(depth))
                    fade = max(0.0, 1.0 - amount * 0.85)
            r = self._rand(d.seed)
            size = DOT_MIN + (DOT_MAX - DOT_MIN) * r
            colour = self._colour(d.kind, r)
            if d.alpha < 1.0:
                colour.setAlphaF(colour.alphaF() * max(0.0, d.alpha))
            if fade < 1.0:
                colour.setAlphaF(colour.alphaF() * fade)
            if colour.alpha() == 0:
                continue
            centre = self._to_screen(AvatarPoint(d.x, d.y, d.kind, d.left),
                                     dy=drop + self._lift + self._bob)
            half = max(0.6, size * scale) / 2.0
            painter.setPen(QPen(Qt.PenStyle.NoPen))
            painter.setBrush(QBrush(colour))
            painter.drawEllipse(QRectF(centre.x() - half, centre.y() - half,
                                       half * 2, half * 2))
        painter.end()


# ═════════════════════════════════════════════════════════════════════════════
# CEREBRIUM REBORN - 5-PART PROCEDURAL EYE PHYSICS & FADE-MASK ENGINE
# ═════════════════════════════════════════════════════════════════════════════
import time
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
import random as _random_mod
_random_mod = __import__("random")

_NO_BLINK_EXPRESSIONS = frozenset({
    "sleepy", "sleepy (local)", "dead", "dizzy", "flustered", "blank",
    "disgusted", "feeling cool", "derp", "in love", "love and hearts",
    "happy", "annoyed", "uwu", "chibi joy", "pepelaugh", "starstruck",
    "excited", "blushing", "smitten", "error 404", "api crash", "net crash",
    "buffering", "hypnotized", "deadpan", "sarcastic",
})

_INTENSE_SHAKE_EXPRESSIONS = frozenset({
    "angry", "rage", "baka", "shocked", "terrified", "scared",
    "heavy sobbing", "crying", "menacing", "nani",
})

_BORED_STAGE1_POOL = ("Sarcastic", "Tired", "Blank", "Sad")
_HUMAN_LAUGH_BOUT = (0.0, 2.0, 1.5, 1.5, 1.0, 1.0, 2.0, 0.0)
_HUMAN_SOB_BOUT   = (0.0, 2.2, 1.4, 0.9, 1.8, 0.5, 0.2, 0.0)


def _sample_bout_curve(curve: tuple[float, ...], t_sec: float, cycle_s: float) -> float:
    n = len(curve)
    pos = ((t_sec / max(0.1, cycle_s)) % 1.0) * n
    idx = int(pos) % n
    frac = pos - int(pos)
    u = frac ** 0.62
    return curve[idx] * (1.0 - u) + curve[(idx + 1) % n] * u


def _ensure_cerebrium_state(view) -> None:
    if getattr(view, "_cerebrium_ready", False):
        return
    view._cerebrium_ready = True
    view.setMouseTracking(True)
    view._particles = []
    view._last_expr_name = None
    view._last_Step_ms = time.monotonic() * 1000.0

    # Part 2: "Dirt in the Eye" Irritation System
    view.dirt_counter = 0.0
    view._dirt_passive_accum_ms = 0.0
    view._dirt_hover_accum_ms = 0.0
    view._blink_active = False
    view._blink_hold_until_ms = 0.0

    # Part 3: Smooth Blink Offset & Eyelid Fade-Mask
    view.target_blink = 0.0
    view.current_blink_offset = 0.0

    # Part 4: Mouse Repulsion & Interactive Dust Sweeping
    view._mouse_canvas_x = -9999.0
    view._mouse_canvas_y = -9999.0
    view._mouse_rel_x = 0.0
    view._mouse_rel_y = 0.0
    view._mouse_moving_until_ms = 0.0
    view._mouse_pressed = False

    # Part 5: Two-Stage Idle Animation State Machine
    now_ms = time.monotonic() * 1000.0
    view._last_interaction_ms = now_ms
    view._idle_stage = 0
    view._pre_idle_expr = None
    view._stage1_delay_ms = _random_mod.uniform(22000.0, 33000.0)
    view._stage2_delay_ms = _random_mod.uniform(7000.0, 11000.0)
    view._in_idle_auto_switch = False


def _sync_particles_to_expr(view, expr) -> None:
    """Sync particle list to `expr.points` while preserving current (cx, cy, alpha) for 20% spring morphing!"""
    _ensure_cerebrium_state(view)
    if expr is None:
        view._particles = []
        view._last_expr_name = None
        return

    pts = getattr(expr, "points", []) or []
    old_p = view._particles
    is_first_load = (len(old_p) == 0 or view._last_expr_name is None)
    new_list = []
    rng = _random_mod.Random(20261015)

    for i, p in enumerate(pts):
        tx = float(p[0] if isinstance(p, (list, tuple)) else getattr(p, "x", 0.0))
        ty = float(p[1] if isinstance(p, (list, tuple)) else getattr(p, "y", 0.0))
        kind = str(p[2] if isinstance(p, (list, tuple)) else getattr(p, "kind", "eyelid"))
        left = bool(p[3] if isinstance(p, (list, tuple)) else getattr(p, "left", getattr(p, "is_left", True)))
        sz = rng.randint(5, 9)

        if not is_first_load and i < len(old_p):
            prev = old_p[i]
            cx, cy = prev["cx"], prev["cy"]
            alpha = prev["alpha"]
            vx, vy = prev["vx"], prev["vy"]
        elif not is_first_load and old_p:
            donor = old_p[i % len(old_p)]
            cx, cy = donor["cx"], donor["cy"]
            alpha = donor["alpha"]
            vx, vy = 0.0, 0.0
        else:
            cx, cy = tx, ty
            alpha = 255.0
            vx, vy = 0.0, 0.0

        new_list.append({
            "cx": cx, "cy": cy,
            "tx": tx, "ty": ty,
            "vx": vx, "vy": vy,
            "alpha": alpha,
            "size": sz,
            "kind": kind,
            "left": left,
            "idx": i,
        })

    view._particles = new_list
    view._last_expr_name = getattr(expr, "name", "")


def _widget_to_canvas_coords(view, wx: float, wy: float) -> tuple[float, float]:
    w = max(1.0, float(view.width()))
    h = max(1.0, float(view.height()))
    user_scale = float(getattr(view, "_scale", getattr(view, "_user_scale", 1.0)) or 1.0)
    sx = (w / 600.0) * user_scale
    sy = (h / 400.0) * user_scale
    s = min(sx, sy)
    if s <= 1e-4:
        return 300.0, 200.0
    ox = (w - 600.0 * s) * 0.5
    oy = (h - 400.0 * s) * 0.5
    return (wx - ox) / s, (wy - oy) / s


def _wake_from_idle_if_needed(view) -> None:
    _ensure_cerebrium_state(view)
    view._last_interaction_ms = time.monotonic() * 1000.0
    if view._idle_stage > 0 and view._pre_idle_expr is not None:
        view._idle_stage = 0
        view._stage1_delay_ms = _random_mod.uniform(22000.0, 33000.0)
        view._stage2_delay_ms = _random_mod.uniform(7000.0, 11000.0)
        restore = view._pre_idle_expr
        view._pre_idle_expr = None
        view._in_idle_auto_switch = True
        try:
            view.set_expression(restore)
        finally:
            view._in_idle_auto_switch = False


def _step_cerebrium_physics(view) -> None:
    _ensure_cerebrium_state(view)
    expr = getattr(view, "_expr", None)
    if expr is None:
        return
    if len(view._particles) != len(getattr(expr, "points", [])):
        _sync_particles_to_expr(view, expr)

    now_ms = time.monotonic() * 1000.0
    dt_ms = max(1.0, min(100.0, now_ms - view._last_Step_ms))
    view._last_Step_ms = now_ms
    t_sec = now_ms * 0.001

    base_name = (getattr(expr, "base_name", "") or getattr(expr, "name", "") or "").strip()
    bl = base_name.lower()
    is_crash = bl in ("api crash", "net crash")

    # ── Part 5: Two-Stage Idle Animation State Machine (22-33s -> Stage 1, +7-11s -> Stage 2) ──
    idle_elapsed = now_ms - view._last_interaction_ms
    if getattr(view, "_idle_motion", True) and not is_crash:
        if view._idle_stage == 0 and idle_elapsed >= view._stage1_delay_ms:
            view._idle_stage = 1
            view._pre_idle_expr = expr
            view._last_interaction_ms = now_ms
            try:
                from cellium.ui.avatar import AvatarLibrary
                lib = getattr(view, "_lib", None) or AvatarLibrary()
                view._lib = lib
                g = getattr(expr, "gender", "Female") or "Female"
                choices = [c for c in _BORED_STAGE1_POOL if c.lower() != bl]
                pick = _random_mod.choice(choices) if choices else "Tired"
                bored_expr = lib.get(g, pick)
                if bored_expr is not None:
                    view._in_idle_auto_switch = True
                    try:
                        view.set_expression(bored_expr)
                        expr = bored_expr
                        bl = pick.lower()
                    finally:
                        view._in_idle_auto_switch = False
            except Exception:
                pass
        elif view._idle_stage == 1 and idle_elapsed >= view._stage2_delay_ms:
            view._idle_stage = 2
            try:
                from cellium.ui.avatar import AvatarLibrary
                lib = getattr(view, "_lib", None) or AvatarLibrary()
                view._lib = lib
                g = getattr(expr, "gender", "Female") or "Female"
                sleep_expr = lib.get(g, "Sleepy")
                if sleep_expr is not None:
                    view._in_idle_auto_switch = True
                    try:
                        view.set_expression(sleep_expr)
                        expr = sleep_expr
                        bl = "sleepy"
                    finally:
                        view._in_idle_auto_switch = False
            except Exception:
                pass

    # ── Part 2: "Dirt in the Eye" Irritation System ──────────────────────────
    can_blink = bool(getattr(expr, "blink_enabled", True)) and (bl not in _NO_BLINK_EXPRESSIONS)
    if can_blink:
        # Passive dust accumulation: +1.0..3.0 every 1000ms
        view._dirt_passive_accum_ms += dt_ms
        if view._dirt_passive_accum_ms >= 1000.0:
            view._dirt_passive_accum_ms -= 1000.0
            view.dirt_counter += _random_mod.uniform(1.0, 3.0)

        # Mouse hover irritation within 20px of any eye pixel: +0.5 every 100ms
        mx, my = view._mouse_canvas_x, view._mouse_canvas_y
        if -100.0 <= mx <= 700.0 and -100.0 <= my <= 500.0:
            near_eye = any(
                math.hypot(mx - p["cx"], my - p["cy"]) <= 20.0
                for p in view._particles
            )
            if near_eye:
                view._dirt_hover_accum_ms += dt_ms
                if view._dirt_hover_accum_ms >= 100.0:
                    view._dirt_hover_accum_ms -= 100.0
                    view.dirt_counter += 0.5

        if not view._blink_active and view.dirt_counter >= 15.0:
            view._blink_active = True
            view._blink_hold_until_ms = now_ms + 150.0
            view.dirt_counter = 0.0

    if view._blink_active and now_ms >= view._blink_hold_until_ms:
        view._blink_active = False
        view.dirt_counter = 0.0

    # ── Part 3: Smooth Blink Offset & Dynamic Eyelid Cutoff Edge (`eyelid_edge`) ──
    view.target_blink = 160.0 if (view._blink_active and can_blink) else 0.0
    blink_lerp = 0.05 if "tired" in bl else 0.35
    view.current_blink_offset += (view.target_blink - view.current_blink_offset) * blink_lerp
    if view.current_blink_offset < 0.3 and view.target_blink == 0.0:
        view.current_blink_offset = 0.0

    extra_edge = 45.0 if "tired" in bl else (
        30.0 if any(k in bl for k in ("annoyed", "smug", "suspicious", "sus", "focused", "sad", "doomer", "shy")) else 0.0
    )
    eyelid_edge = (400.0 / 2.0) - 50.0 + extra_edge + view.current_blink_offset

    # ── Part 1: Continuous Breathing Float & Special Expression Offsets ──────
    breath_y = math.sin(now_ms * 0.003) * 8.0 if getattr(view, "_idle_motion", True) else 0.0
    jitter_amp = 3.4 if any(k in bl for k in _INTENSE_SHAKE_EXPRESSIONS) else (0.6 if getattr(view, "_idle_motion", True) else 0.0)

    laugh_dy = 0.0
    if any(k in bl for k in ("laugh", "chibi joy", "pepelaugh")):
        # 5-beat / [0, 2, 1.5, 1.5, 1, 1, 2, 0] rhythmic human laugh bounce!
        laugh_dy = -_sample_bout_curve(_HUMAN_LAUGH_BOUT, t_sec, cycle_s=1.35) * 6.5
    elif any(k in bl for k in ("sob", "crying", "copium", "doomer")):
        laugh_dy = _sample_bout_curve(_HUMAN_SOB_BOUT, t_sec, cycle_s=1.70) * 5.0

    is_dizzy_spin = any(k in bl for k in ("dizzy", "hypnotized"))
    mouse_active = (now_ms <= view._mouse_moving_until_ms)
    mx, my = view._mouse_canvas_x, view._mouse_canvas_y

    # Update every pixel particle with the exact Cerebrium math!
    pts_src = getattr(expr, "points", [])
    for i, p in enumerate(view._particles):
        if i < len(pts_src):
            raw_p = pts_src[i]
            p["tx"] = float(raw_p[0] if isinstance(raw_p, (list, tuple)) else getattr(raw_p, "x", p["tx"]))
            p["ty"] = float(raw_p[1] if isinstance(raw_p, (list, tuple)) else getattr(raw_p, "y", p["ty"]))

        kind = p["kind"]
        is_left = p["left"]
        side_blinks = (getattr(expr, "blink_left", True) if is_left else getattr(expr, "blink_right", True))
        eff_blink = view.current_blink_offset if (can_blink and side_blinks) else 0.0

        # ── Part 4B: Interactive Dust Sweeping for Crash States ──────────────
        if is_crash and kind == "dust":
            p["vy"] += 0.8
            p["vx"] *= 0.95
            if mouse_active and math.hypot(mx - p["cx"], my - p["cy"]) <= 50.0:
                p["vx"] += view._mouse_rel_x * 0.8
                p["vy"] += view._mouse_rel_y * 0.8
            p["cx"] += p["vx"]
            p["cy"] += p["vy"]
            floor_y = 400.0 - 60.0
            if p["cy"] >= floor_y:
                p["cy"] = floor_y
                p["vy"] *= -0.3
                if _random_mod.random() < 0.03:
                    p["vy"] = _random_mod.uniform(-14.0, -6.0)
                    p["vx"] = _random_mod.uniform(-3.0, 3.0)
            p["cx"] = max(20.0, min(580.0, p["cx"]))
            p["alpha"] = 255.0
            continue

        # Target coordinates with continuous breathing float + expression physics
        tx = p["tx"]
        ty = p["ty"] + breath_y + laugh_dy
        resting_ty = ty

        # 360-degree trigonometry spin for Dizzy / Hypnotized!
        if is_dizzy_spin and kind in ("eyelid", "stem"):
            eye_cx = 200.0 if is_left else 400.0
            eye_cy = 215.0 + breath_y
            dx0 = tx - eye_cx
            dy0 = (p["ty"] - 215.0)
            ang = t_sec * (4.5 if is_left else -4.5)
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            tx = eye_cx + dx0 * cos_a - dy0 * sin_a
            ty = eye_cy + dx0 * sin_a + dy0 * cos_a

        # Prop animations (Falling tears, sliding water sweat drop, rising white steam, drifting Zzz)
        phase_seed = (p["idx"] * 0.37)
        if kind == "tear":
            if "laugh" in bl:
                prog = (t_sec * 2.2 + phase_seed * 0.1) % 1.0
                tx += (-1.0 if is_left else 1.0) * prog * 10.0
                ty += (prog * prog) * 12.0
            else:
                ty += ((t_sec * 44.0 + (0.0 if is_left else 11.0) + p["ty"] * 0.35) % 28.0)
        elif kind == "cartoon_sweat":
            ph = (t_sec * 0.85 + (0.3 if is_left else 0.0)) % 1.0
            ty += (min(1.0, ph * 1.45) ** 1.6) * 22.0
        elif kind == "dust" and not is_crash:
            if any(k in bl for k in ("angry", "annoyed", "rage", "baka", "menacing", "tsundere")):
                puff = (t_sec * 38.0 + (0.0 if is_left else 14.0) + phase_seed * 3.0) % 32.0
                ty -= puff
                tx += (-1.0 if is_left else 1.0) * (puff * 0.45)
            elif any(k in bl for k in ("sleepy", "tired", "waking")):
                zf = (t_sec * 22.0) % 26.0
                tx += zf * 0.55
                ty -= zf
            elif any(k in bl for k in ("thinking", "focused")):
                ty -= ((t_sec * 18.0 + phase_seed * 2.0) % 18.0) - 6.0

        # ── Part 3: Eyelid & Mid-Bar Descent + Precise Top-to-Bottom Alpha Fade-Mask ──
        if kind == "eyelid":
            ty = min(300.0, ty + eff_blink)
            p["alpha"] = 255.0
        elif kind == "mid_bar":
            ty += min(eff_blink, 25.0)
            if eff_blink > 1.5 and resting_ty < eyelid_edge:
                p["alpha"] = max(0.0, p["alpha"] - 80.0)
            else:
                p["alpha"] = min(255.0, p["alpha"] + 80.0)
        elif kind in ("stem", "bottom_bar"):
            if eff_blink > 1.5 and resting_ty < eyelid_edge:
                p["alpha"] = max(0.0, p["alpha"] - 80.0)
            else:
                p["alpha"] = min(255.0, p["alpha"] + 80.0)
        elif kind == "eyebrow":
            dip = float(getattr(expr, "left_eyebrow_dip" if is_left else "right_eyebrow_dip", 4.0) or 4.0)
            ty += min(eff_blink * 0.08, dip)
            p["alpha"] = 255.0
        else:
            p["alpha"] = 255.0

        # ── Part 4A: 60px Live Mouse Cursor Repulsion (`* 0.4`) ──────────────
        if mouse_active:
            dist = math.hypot(mx - p["cx"], my - p["cy"])
            if dist < 60.0:
                p["cx"] -= (mx - p["cx"]) * 0.4
                ty -= (my - ty) * 0.4

        # ── Part 1: 20% Spring Interpolation (`* 0.2`) + Micro-Jitter ────────
        p["cx"] += (tx - p["cx"]) * 0.20
        p["cy"] += (ty - p["cy"]) * 0.20
        if jitter_amp > 0.0:
            p["cx"] += _random_mod.uniform(-jitter_amp, jitter_amp)
            p["cy"] += _random_mod.uniform(-jitter_amp, jitter_amp)

    view._mouse_rel_x *= 0.5
    view._mouse_rel_y *= 0.5


# ── Hook AvatarView with the Cerebrium Physics, Mouse Events & Renderer ─────
if "AvatarView" in globals():
    _orig_av_set_expr = AvatarView.set_expression
    _orig_av_trigger_blink = getattr(AvatarView, "trigger_blink", None)

    def _cerebrium_set_expression(self, expr) -> None:
        _ensure_cerebrium_state(self)
        if not getattr(self, "_in_idle_auto_switch", False):
            self._last_interaction_ms = time.monotonic() * 1000.0
            self._idle_stage = 0
        _orig_av_set_expr(self, expr)
        _sync_particles_to_expr(self, expr)
        self.update()

    def _cerebrium_trigger_blink(self) -> None:
        _ensure_cerebrium_state(self)
        self._blink_active = True
        self._blink_hold_until_ms = time.monotonic() * 1000.0 + 165.0
        self.dirt_counter = 0.0
        if _orig_av_trigger_blink is not None:
            try:
                _orig_av_trigger_blink(self)
            except Exception:
                pass
        self.update()

    def _cerebrium_mouse_move(self, event) -> None:
        _wake_from_idle_if_needed(self)
        pos = event.position() if hasattr(event, "position") else event.pos()
        nx, ny = _widget_to_canvas_coords(self, float(pos.x()), float(pos.y()))
        if self._mouse_canvas_x > -9000.0:
            self._mouse_rel_x = nx - self._mouse_canvas_x
            self._mouse_rel_y = ny - self._mouse_canvas_y
        self._mouse_canvas_x = nx
        self._mouse_canvas_y = ny
        self._mouse_moving_until_ms = time.monotonic() * 1000.0 + 120.0
        self.update()

    def _cerebrium_mouse_press(self, event) -> None:
        _wake_from_idle_if_needed(self)
        self._mouse_pressed = True
        pos = event.position() if hasattr(event, "position") else event.pos()
        nx, ny = _widget_to_canvas_coords(self, float(pos.x()), float(pos.y()))
        self._mouse_canvas_x = nx
        self._mouse_canvas_y = ny
        # Part 2: Click-to-Poke Reflex (within 20px of any eye pixel -> 50% immediate flinch blink!)
        hit_eye = any(math.hypot(nx - p["cx"], ny - p["cy"]) <= 20.0 for p in getattr(self, "_particles", []))
        if hit_eye and _random_mod.random() < 0.50:
            self._blink_active = True
            self._blink_hold_until_ms = time.monotonic() * 1000.0 + 150.0
            self.dirt_counter = 0.1
        self.update()

    def _cerebrium_mouse_release(self, _event) -> None:
        self._mouse_pressed = False

    def _cerebrium_paint_event(self, _event) -> None:
        _step_cerebrium_physics(self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        user_scale = float(getattr(self, "_pet_zoom", 1.0)) * float(getattr(self, "_scale", getattr(self, "_user_scale", 1.0)) or 1.0)
        s = min(w / 600.0, h / 400.0) * user_scale
        ox = (w - 600.0 * s) * 0.5
        oy = (h - 400.0 * s) * 0.5

        # Optional Studio background grid if enabled on widget
        if getattr(self, "_show_grid", False):
            painter.setPen(QColor(147, 51, 234, 24))
            step = max(16, int(40 * s))
            for gx in range(0, int(w), step):
                painter.drawLine(gx, 0, gx, int(h))
            for gy in range(0, int(h), step):
                painter.drawLine(0, gy, int(w), gy)

        # Resolve color map
        cmap = (
            globals().get("KIND_COLORS")
            or globals().get("PRIMITIVE_COLORS")
            or globals().get("COLORS")
            or {}
        )
        default_colors = {
            "eyelid": QColor(168, 85, 247),
            "eyebrow": QColor(192, 132, 252),
            "mid_bar": QColor(168, 85, 247),
            "bottom_bar": QColor(168, 85, 247),
            "stem": QColor(248, 244, 255),
            "blush": QColor(244, 114, 182),
            "perm_blush": QColor(244, 114, 182),
            "tear": QColor(56, 189, 248),
            "cartoon_sweat": QColor(103, 232, 249),
            "exclamation": QColor(248, 113, 113),
            "icon": QColor(192, 132, 252),
            "dust": QColor(245, 248, 255),
        }

        painter.setPen(Qt.PenStyle.NoPen)
        for p in self._particles:
            a = int(max(0.0, min(255.0, p["alpha"])))
            if a <= 2:
                continue
            kind = p["kind"]
            base_c = cmap.get(kind) or default_colors.get(kind) or QColor(168, 85, 247)
            c = QColor(base_c)
            if kind == "dust":
                c = QColor(245, 248, 255)
            c.setAlpha(a)
            painter.setBrush(c)

            clamped_cx = max(24.0, min(576.0, float(p["cx"])))
            clamped_cy = max(18.0, min(382.0, float(p["cy"])))
            px = ox + clamped_cx * s
            py = oy + clamped_cy * s
            sz = max(2.5, p["size"] * s)
            r_rad = max(1.2, sz * 0.28)
            painter.drawRoundedRect(QRectF(px - sz * 0.5, py - sz * 0.5, sz, sz), r_rad, r_rad)

        painter.end()

    AvatarView.set_expression = _cerebrium_set_expression
    AvatarView.trigger_blink = _cerebrium_trigger_blink
    AvatarView.mouseMoveEvent = _cerebrium_mouse_move
    AvatarView.mousePressEvent = _cerebrium_mouse_press
    AvatarView.mouseReleaseEvent = _cerebrium_mouse_release
    AvatarView.paintEvent = _cerebrium_paint_event

    _orig_av_init = AvatarView.__init__
    def _cerebrium_init(self, *args, **kwargs):
        _orig_av_init(self, *args, **kwargs)
        _ensure_cerebrium_state(self)
        _sync_particles_to_expr(self, getattr(self, "_expr", None))
    AvatarView.__init__ = _cerebrium_init


# ── 1a. Stacked Purple Background Expression Typewriter (30s Hold + Backspace) ──
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontMetrics

_BG_TYPE_SPEED_MS = 38.0     # Crisp typing speed (~26 chars/sec)
_BG_HOLD_DURATION_MS = 30000.0  # Stay visible for 30 seconds
_BG_BACKSPACE_SPEED_MS = 26.0   # Human holding backspace speed (~38 chars/sec)


def _queue_bg_expression_text(view, expr) -> None:
    """Append expression name to the non-overlapping purple background stack when expression changes."""
    if expr is None:
        return
    raw_name = (getattr(expr, "base_name", "") or getattr(expr, "name", "") or "").strip()
    if not raw_name:
        return
    # Strip any modifier suffix for clean display
    clean_name = raw_name.split(" - ")[0].strip()
    if not clean_name:
        return

    if not hasattr(view, "_bg_text_queue"):
        view._bg_text_queue = []
    if not hasattr(view, "_last_bg_queued_name"):
        view._last_bg_queued_name = None

    # Ignore 30fps lip-sync frames where the base expression name hasn't changed
    if clean_name.lower() == (view._last_bg_queued_name or "").lower():
        return
    view._last_bg_queued_name = clean_name

    now_ms = time.monotonic() * 1000.0
    view._bg_text_queue.append({
        "text": clean_name,
        "spawn_ms": now_ms,
        "y_Render": None,
    })
    # Cap stack at 8 visible lines max so rapid scrolling stays tidy
    if len(view._bg_text_queue) > 8:
        view._bg_text_queue = view._bg_text_queue[-8:]

    # Ensure 30fps repaint timer is running on the view so typing/backspacing animates smoothly
    if getattr(view, "_bg_anim_timer", None) is None:
        tm = QTimer(view)
        tm.setInterval(33)
        tm.timeout.connect(view.update)
        tm.start()
        view._bg_anim_timer = tm
    elif not view._bg_anim_timer.isActive():
        view._bg_anim_timer.start()


def _draw_bg_expression_stack(view, painter: QPainter, w: float, h: float) -> None:
    """Render the queued expression names in the background with typewriter + 30s hold + backspace."""
    queue = getattr(view, "_bg_text_queue", None)
    if not queue:
        return

    now_ms = time.monotonic() * 1000.0
    alive = []

    font_px = max(14, min(28, int(min(w, h) * 0.068)))
    font = QFont("Segoe UI", -1, QFont.Weight.Bold)
    font.setPixelSize(font_px)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
    painter.save()
    painter.setFont(font)
    fm = QFontMetrics(font)
    line_h = fm.height() + 6
    base_top_y = max(24.0, h * 0.08)

    for item in queue:
        full_txt = item["text"]
        n = len(full_txt)
        if n == 0:
            continue
        elapsed = max(0.0, now_ms - item["spawn_ms"])
        type_dur = n * _BG_TYPE_SPEED_MS
        hold_end = type_dur + _BG_HOLD_DURATION_MS
        bs_dur = n * _BG_BACKSPACE_SPEED_MS
        total_dur = hold_end + bs_dur

        if elapsed >= total_dur:
            continue

        if elapsed < type_dur:
            # Typing in character-by-character
            chars = max(1, min(n, int(elapsed / _BG_TYPE_SPEED_MS) + 1))
            vis_txt = full_txt[:chars] + "▎"
            alpha_mult = min(1.0, 0.4 + 0.6 * (chars / float(n)))
        elif elapsed < hold_end:
            # Holding steady for 30 seconds
            vis_txt = full_txt
            alpha_mult = 1.0
        else:
            # Human holding backspace: deleting character-by-character from the end!
            bs_elapsed = elapsed - hold_end
            deleted = int(bs_elapsed / _BG_BACKSPACE_SPEED_MS) + 1
            rem = max(0, n - deleted)
            if rem <= 0:
                continue
            vis_txt = full_txt[:rem] + "▎"
            alpha_mult = max(0.35, rem / float(n))

        item["_vis_txt"] = vis_txt
        item["_alpha_mult"] = alpha_mult
        alive.append(item)

    view._bg_text_queue = alive
    if not alive:
        painter.restore()
        return

    # Draw each active line stacked vertically in the background
    for idx, item in enumerate(alive):
        target_y = base_top_y + idx * line_h
        if item["y_Render"] is None:
            item["y_Render"] = target_y
        else:
            # Smoothly glide up when an older line above finishes backspacing!
            item["y_Render"] += (target_y - item["y_Render"]) * 0.25

        vis_txt = item["_vis_txt"]
        am = item["_alpha_mult"]
        tw = fm.horizontalAdvance(vis_txt)
        tx = max(18.0, (w - tw) * 0.5)
        ty = item["y_Render"] + fm.ascent()

        # Subtle dark-violet depth shadow + ambient purple text that blends with the BG
        painter.setPen(QColor(46, 16, 101, int(95 * am)))
        painter.drawText(QPointF(tx + 1.5, ty + 1.5), vis_txt)

        painter.setPen(QColor(178, 102, 255, int(135 * am)))
        painter.drawText(QPointF(tx, ty), vis_txt)

    painter.restore()


# Hook into AvatarView.set_expression and AvatarView.paintEvent
if "AvatarView" in globals():
    _prev_set_expr_1a = AvatarView.set_expression
    _prev_paint_1a = AvatarView.paintEvent

    def _set_expr_with_bg_text(self, expr) -> None:
        _queue_bg_expression_text(self, expr)
        _prev_set_expr_1a(self, expr)

    def _paint_with_bg_text(self, event) -> None:
        _step_cerebrium_physics(self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        user_scale = float(getattr(self, "_pet_zoom", 1.0)) * float(getattr(self, "_scale", getattr(self, "_user_scale", 1.0)) or 1.0)
        s = min(w / 600.0, h / 400.0) * user_scale
        ox = (w - 600.0 * s) * 0.5
        oy = (h - 400.0 * s) * 0.5

        if getattr(self, "_show_grid", False):
            painter.setPen(QColor(147, 51, 234, 24))
            step = max(16, int(40 * s))
            for gx in range(0, int(w), step):
                painter.drawLine(gx, 0, gx, int(h))
            for gy in range(0, int(h), step):
                painter.drawLine(0, gy, int(w), gy)

        # 1a: Draw stacked purple background typewriter text BEHIND the eye particles!
        _draw_bg_expression_stack(self, painter, w, h)

        cmap = (
            globals().get("KIND_COLORS")
            or globals().get("PRIMITIVE_COLORS")
            or globals().get("COLORS")
            or {}
        )
        default_colors = {
            "eyelid": QColor(168, 85, 247),
            "eyebrow": QColor(192, 132, 252),
            "mid_bar": QColor(168, 85, 247),
            "bottom_bar": QColor(168, 85, 247),
            "stem": QColor(248, 244, 255),
            "blush": QColor(244, 114, 182),
            "perm_blush": QColor(244, 114, 182),
            "tear": QColor(56, 189, 248),
            "cartoon_sweat": QColor(103, 232, 249),
            "exclamation": QColor(248, 113, 113),
            "icon": QColor(192, 132, 252),
            "dust": QColor(245, 248, 255),
        }

        painter.setPen(Qt.PenStyle.NoPen)
        for p in self._particles:
            a = int(max(0.0, min(255.0, p["alpha"])))
            if a <= 2:
                continue
            kind = p["kind"]
            base_c = cmap.get(kind) or default_colors.get(kind) or QColor(168, 85, 247)
            c = QColor(base_c)
            if kind == "dust":
                c = QColor(245, 248, 255)
            c.setAlpha(a)
            painter.setBrush(c)

            clamped_cx = max(24.0, min(576.0, float(p["cx"])))
            clamped_cy = max(18.0, min(382.0, float(p["cy"])))
            px = ox + clamped_cx * s
            py = oy + clamped_cy * s
            sz = max(2.5, p["size"] * s)
            r_rad = max(1.2, sz * 0.28)
            painter.drawRoundedRect(QRectF(px - sz * 0.5, py - sz * 0.5, sz, sz), r_rad, r_rad)

        painter.end()

    AvatarView.set_expression = _set_expr_with_bg_text
    AvatarView.paintEvent = _paint_with_bg_text


# ── #4 & #6: Universal Velocity-Scaled Cursor Physics Override ───────────────
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication


def _poll_universal_cursor(view) -> None:
    """Track cursor position & velocity universally across Studio, Pet Mode & Live Mode overlays."""
    if not view.isVisible():
        return
    try:
        global_pos = QCursor.pos()
        local_pos = view.mapFromGlobal(global_pos)
    except Exception:
        return

    now_ms = time.monotonic() * 1000.0
    if not hasattr(view, "_last_global_cursor"):
        view._last_global_cursor = (local_pos.x(), local_pos.y())

    inside = (0 <= local_pos.x() <= view.width() and 0 <= local_pos.y() <= view.height())
    if not inside:
        view._mouse_rel_x *= 0.15
        view._mouse_rel_y *= 0.15
        view._mouse_speed = 0.0
        return

    nx, ny = _widget_to_canvas_coords(view, float(local_pos.x()), float(local_pos.y()))
    prev_gx, prev_gy = view._last_global_cursor
    pixel_screen_delta = math.hypot(local_pos.x() - prev_gx, local_pos.y() - prev_gy)
    view._last_global_cursor = (local_pos.x(), local_pos.y())

    if pixel_screen_delta >= 0.4:
        _wake_from_idle_if_needed(view)
        if view._mouse_canvas_x > -9000.0:
            dx_c = nx - view._mouse_canvas_x
            dy_c = ny - view._mouse_canvas_y
            # Clamp extreme single-frame jumps when entering window
            if math.hypot(dx_c, dy_c) < 180.0:
                view._mouse_rel_x = dx_c
                view._mouse_rel_y = dy_c
                view._mouse_speed = math.hypot(dx_c, dy_c)
                view._mouse_moving_until_ms = now_ms + 28.0
        view._mouse_canvas_x = nx
        view._mouse_canvas_y = ny

    # Universal click-to-poke detection (works even through Live Mode transparent overlays)
    try:
        buttons = QApplication.mouseButtons()
        is_down = bool(buttons & Qt.MouseButton.LeftButton)
    except Exception:
        is_down = False
    was_down = getattr(view, "_univ_mouse_was_down", False)
    view._univ_mouse_was_down = is_down
    if is_down and not was_down:
        _wake_from_idle_if_needed(view)
        hit_eye = any(math.hypot(nx - p["cx"], ny - p["cy"]) <= 22.0 for p in getattr(view, "_particles", []))
        if hit_eye and _random_mod.random() < 0.55:
            view._blink_active = True
            view._blink_hold_until_ms = now_ms + 150.0
            view.dirt_counter = 0.1


def _step_cerebrium_physics_v2(view) -> None:
    _ensure_cerebrium_state(view)
    _poll_universal_cursor(view)
    expr = getattr(view, "_expr", None)
    if expr is None:
        return
    if len(view._particles) != len(getattr(expr, "points", [])):
        _sync_particles_to_expr(view, expr)

    now_ms = time.monotonic() * 1000.0
    dt_ms = max(1.0, min(100.0, now_ms - view._last_Step_ms))
    view._last_Step_ms = now_ms
    t_sec = now_ms * 0.001

    base_name = (getattr(expr, "base_name", "") or getattr(expr, "name", "") or "").strip()
    bl = base_name.lower()
    is_crash = bl in ("api crash", "net crash")

    # Part 5: Two-Stage Idle Animation State Machine
    idle_elapsed = now_ms - view._last_interaction_ms
    if getattr(view, "_idle_motion", True) and not is_crash:
        if view._idle_stage == 0 and idle_elapsed >= view._stage1_delay_ms:
            view._idle_stage = 1
            view._pre_idle_expr = expr
            view._last_interaction_ms = now_ms
            try:
                from cellium.ui.avatar import AvatarLibrary
                lib = getattr(view, "_lib", None) or AvatarLibrary()
                view._lib = lib
                g = getattr(expr, "gender", "Female") or "Female"
                choices = [c for c in _BORED_STAGE1_POOL if c.lower() != bl]
                pick = _random_mod.choice(choices) if choices else "Tired"
                bored_expr = lib.get(g, pick)
                if bored_expr is not None:
                    view._in_idle_auto_switch = True
                    try:
                        view.set_expression(bored_expr)
                        expr = bored_expr
                        bl = pick.lower()
                    finally:
                        view._in_idle_auto_switch = False
            except Exception:
                pass
        elif view._idle_stage == 1 and idle_elapsed >= view._stage2_delay_ms:
            view._idle_stage = 2
            try:
                from cellium.ui.avatar import AvatarLibrary
                lib = getattr(view, "_lib", None) or AvatarLibrary()
                view._lib = lib
                g = getattr(expr, "gender", "Female") or "Female"
                sleep_expr = lib.get(g, "Sleepy")
                if sleep_expr is not None:
                    view._in_idle_auto_switch = True
                    try:
                        view.set_expression(sleep_expr)
                        expr = sleep_expr
                        bl = "sleepy"
                    finally:
                        view._in_idle_auto_switch = False
            except Exception:
                pass

    # Part 2: "Dirt in the Eye" Irritation System
    can_blink = bool(getattr(expr, "blink_enabled", True)) and (bl not in _NO_BLINK_EXPRESSIONS)
    mx, my = view._mouse_canvas_x, view._mouse_canvas_y
    if can_blink:
        view._dirt_passive_accum_ms += dt_ms
        if view._dirt_passive_accum_ms >= 1000.0:
            view._dirt_passive_accum_ms -= 1000.0
            view.dirt_counter += _random_mod.uniform(1.0, 3.0)

        if -100.0 <= mx <= 700.0 and -100.0 <= my <= 500.0:
            near_eye = any(math.hypot(mx - p["cx"], my - p["cy"]) <= 20.0 for p in view._particles)
            if near_eye:
                view._dirt_hover_accum_ms += dt_ms
                if view._dirt_hover_accum_ms >= 100.0:
                    view._dirt_hover_accum_ms -= 100.0
                    view.dirt_counter += 0.5

        if not view._blink_active and view.dirt_counter >= 15.0:
            view._blink_active = True
            view._blink_hold_until_ms = now_ms + 150.0
            view.dirt_counter = 0.0

    if view._blink_active and now_ms >= view._blink_hold_until_ms:
        view._blink_active = False
        view.dirt_counter = 0.0

    # Part 3: Smooth Blink Offset & Dynamic Eyelid Cutoff Edge
    view.target_blink = 160.0 if (view._blink_active and can_blink) else 0.0
    blink_lerp = 0.05 if "tired" in bl else 0.35
    view.current_blink_offset += (view.target_blink - view.current_blink_offset) * blink_lerp
    if view.current_blink_offset < 0.3 and view.target_blink == 0.0:
        view.current_blink_offset = 0.0

    extra_edge = 45.0 if "tired" in bl else (
        30.0 if any(k in bl for k in ("annoyed", "smug", "suspicious", "sus", "focused", "sad", "doomer", "shy")) else 0.0
    )
    eyelid_edge = (400.0 / 2.0) - 50.0 + extra_edge + view.current_blink_offset

    # Part 1: Continuous Breathing Float & Special Expression Offsets
    breath_y = math.sin(now_ms * 0.003) * 8.0 if getattr(view, "_idle_motion", True) else 0.0
    jitter_amp = 3.2 if any(k in bl for k in _INTENSE_SHAKE_EXPRESSIONS) else (0.45 if getattr(view, "_idle_motion", True) else 0.0)

    laugh_dy = 0.0
    if any(k in bl for k in ("laugh", "chibi joy", "pepelaugh")):
        laugh_dy = -_sample_bout_curve(_HUMAN_LAUGH_BOUT, t_sec, cycle_s=1.35) * 6.5
    elif any(k in bl for k in ("sob", "crying", "copium", "doomer")):
        laugh_dy = _sample_bout_curve(_HUMAN_SOB_BOUT, t_sec, cycle_s=1.70) * 5.0

    is_dizzy_spin = any(k in bl for k in ("dizzy", "hypnotized"))

    # #4: Velocity-scaled mouse repulsion - only active while mouse is moving, scaled by speed!
    mouse_speed = float(getattr(view, "_mouse_speed", 0.0) or math.hypot(view._mouse_rel_x, view._mouse_rel_y))
    mouse_active = (now_ms <= view._mouse_moving_until_ms) and (mouse_speed > 0.15)
    # 0.01px movement = ~0.002 speed_factor (tiny nano-second nudge); fast swipe = up to 0.42
    speed_factor = min(1.0, mouse_speed / 26.0)
    repulse_strength = 0.42 * speed_factor

    pts_src = getattr(expr, "points", [])
    for i, p in enumerate(view._particles):
        if i < len(pts_src):
            raw_p = pts_src[i]
            p["tx"] = float(raw_p[0] if isinstance(raw_p, (list, tuple)) else getattr(raw_p, "x", p["tx"]))
            p["ty"] = float(raw_p[1] if isinstance(raw_p, (list, tuple)) else getattr(raw_p, "y", p["ty"]))

        kind = p["kind"]
        is_left = p["left"]
        side_blinks = (getattr(expr, "blink_left", True) if is_left else getattr(expr, "blink_right", True))
        eff_blink = view.current_blink_offset if (can_blink and side_blinks) else 0.0

        if is_crash and kind == "dust":
            p["vy"] += 0.8
            p["vx"] *= 0.95
            if mouse_active and math.hypot(mx - p["cx"], my - p["cy"]) <= 50.0:
                p["vx"] += view._mouse_rel_x * 0.8
                p["vy"] += view._mouse_rel_y * 0.8
            p["cx"] += p["vx"]
            p["cy"] += p["vy"]
            floor_y = 400.0 - 60.0
            if p["cy"] >= floor_y:
                p["cy"] = floor_y
                p["vy"] *= -0.3
                if _random_mod.random() < 0.03:
                    p["vy"] = _random_mod.uniform(-14.0, -6.0)
                    p["vx"] = _random_mod.uniform(-3.0, 3.0)
            p["cx"] = max(20.0, min(580.0, p["cx"]))
            p["alpha"] = 255.0
            continue

        tx = p["tx"]
        ty = p["ty"] + breath_y + laugh_dy
        resting_ty = ty

        if is_dizzy_spin and kind in ("eyelid", "stem"):
            eye_cx = 200.0 if is_left else 400.0
            eye_cy = 215.0 + breath_y
            dx0 = tx - eye_cx
            dy0 = (p["ty"] - 215.0)
            ang = t_sec * (4.5 if is_left else -4.5)
            cos_a, sin_a = math.cos(ang), math.sin(ang)
            tx = eye_cx + dx0 * cos_a - dy0 * sin_a
            ty = eye_cy + dx0 * sin_a + dy0 * cos_a

        phase_seed = (p["idx"] * 0.37)
        if kind == "tear":
            if "laugh" in bl:
                prog = (t_sec * 2.2 + phase_seed * 0.1) % 1.0
                tx += (-1.0 if is_left else 1.0) * prog * 10.0
                ty += (prog * prog) * 12.0
            else:
                ty += ((t_sec * 44.0 + (0.0 if is_left else 11.0) + p["ty"] * 0.35) % 28.0)
        elif kind == "cartoon_sweat":
            ph = (t_sec * 0.85 + (0.3 if is_left else 0.0)) % 1.0
            ty += (min(1.0, ph * 1.45) ** 1.6) * 22.0
        elif kind == "dust" and not is_crash:
            if any(k in bl for k in ("angry", "annoyed", "rage", "baka", "menacing", "tsundere")):
                puff = (t_sec * 38.0 + (0.0 if is_left else 14.0) + phase_seed * 3.0) % 32.0
                ty -= puff
                tx += (-1.0 if is_left else 1.0) * (puff * 0.45)
            elif any(k in bl for k in ("sleepy", "tired", "waking")):
                zf = (t_sec * 22.0) % 26.0
                tx += zf * 0.55
                ty -= zf
            elif any(k in bl for k in ("thinking", "focused")):
                ty -= ((t_sec * 18.0 + phase_seed * 2.0) % 18.0) - 6.0

        if kind == "eyelid":
            ty = min(300.0, ty + eff_blink)
            p["alpha"] = 255.0
        elif kind == "mid_bar":
            ty += min(eff_blink, 25.0)
            if eff_blink > 1.5 and resting_ty < eyelid_edge:
                p["alpha"] = max(0.0, p["alpha"] - 80.0)
            else:
                p["alpha"] = min(255.0, p["alpha"] + 80.0)
        elif kind in ("stem", "bottom_bar"):
            if eff_blink > 1.5 and resting_ty < eyelid_edge:
                p["alpha"] = max(0.0, p["alpha"] - 80.0)
            else:
                p["alpha"] = min(255.0, p["alpha"] + 80.0)
        elif kind == "eyebrow":
            dip = float(getattr(expr, "left_eyebrow_dip" if is_left else "right_eyebrow_dip", 4.0) or 4.0)
            ty += min(eff_blink * 0.08, dip)
            p["alpha"] = 255.0
        else:
            p["alpha"] = 255.0

        # #4: Velocity-proportional repulsion with smooth distance falloff
        if mouse_active and repulse_strength > 0.001:
            dist = math.hypot(mx - p["cx"], my - p["cy"])
            if dist < 60.0:
                falloff = 1.0 - (dist / 60.0)
                push = repulse_strength * falloff
                p["cx"] -= (mx - p["cx"]) * push - view._mouse_rel_x * (0.28 * falloff)
                ty -= (my - ty) * push - view._mouse_rel_y * (0.28 * falloff)

        # 25% spring snap-back so displaced pixels return smoothly right after movement stops
        p["cx"] += (tx - p["cx"]) * 0.24
        p["cy"] += (ty - p["cy"]) * 0.24
        if jitter_amp > 0.0:
            p["cx"] += _random_mod.uniform(-jitter_amp, jitter_amp)
            p["cy"] += _random_mod.uniform(-jitter_amp, jitter_amp)

    # Rapid velocity decay so repulsion stops the instant mouse stops moving
    view._mouse_rel_x *= 0.18
    view._mouse_rel_y *= 0.18
    view._mouse_speed = math.hypot(view._mouse_rel_x, view._mouse_rel_y)


_step_cerebrium_physics = _step_cerebrium_physics_v2


# ── Clean _bg_anim_timer on dispose ──
if "AvatarView" in globals():
    _prev_av_disp_2026 = AvatarView.dispose
    def _clean_av_disp_2026(self) -> None:
        if getattr(self, "_bg_anim_timer", None) is not None:
            try:
                self._bg_anim_timer.stop()
            except Exception:
                pass
        _prev_av_disp_2026(self)
    AvatarView.dispose = _clean_av_disp_2026

# ══ WAVE_OMG_PARITY_START ══
# Both #1: Fast <=3s Floating Background Typewriter
_BG_TYPE_SPEED_MS = 26.0
_BG_HOLD_DURATION_MS = 1850.0
_BG_BACKSPACE_SPEED_MS = 20.0

_TIRED_IDLE_SET = frozenset({
    "tired", "sleepy", "sleepy (local)", "blank", "deadpan",
    "sarcastic", "sad", "doomer", "waking",
})
_LIVELY_AWAKE_POOL = (
    "Happy", "Kawaii", "Chibi Joy", "Excited", "Winking", "UwU", "Relieved", "Sparkle Hype",
)

# Both #5: Layer Z-Order so Eyelids & Eyebrows ALWAYS render on top of main eyes (stem/mid_bar/bottom_bar)
_PARTICLE_LAYER_ORDER = {
    "blush": 0,
    "perm_blush": 0,
    "dust": 1,
    "bottom_bar": 2,
    "mid_bar": 3,
    "stem": 4,
    "icon": 5,
    "tear": 6,
    "cartoon_sweat": 6,
    "exclamation": 7,
    "eyelid": 8,
    "eyebrow": 9,
}


def _wake_from_idle_if_needed_v2(view) -> None:
    _ensure_cerebrium_state(view)
    view._last_interaction_ms = time.monotonic() * 1000.0
    cur_expr = getattr(view, "_expr", None)
    cur_name = (getattr(cur_expr, "base_name", "") or getattr(cur_expr, "name", "") or "").strip().lower()
    if view._idle_stage > 0 or (getattr(view, "_in_idle_auto_switch", False) is False and getattr(view, "_was_napping", False)):
        view._idle_stage = 0
        view._was_napping = False
        view._stage1_delay_ms = _random_mod.uniform(22000.0, 33000.0)
        view._stage2_delay_ms = _random_mod.uniform(7000.0, 11000.0)
        restore = view._pre_idle_expr
        view._pre_idle_expr = None
        restore_name = (getattr(restore, "base_name", "") or getattr(restore, "name", "") or "").strip().lower()
        if restore is None or restore_name in _TIRED_IDLE_SET or cur_name in _TIRED_IDLE_SET:
            try:
                from cellium.ui.avatar import AvatarLibrary
                lib = getattr(view, "_lib", None) or AvatarLibrary()
                view._lib = lib
                g = getattr(cur_expr, "gender", "Female") or "Female"
                pick = _random_mod.choice(_LIVELY_AWAKE_POOL)
                restore = lib.get(g, pick) or restore
            except Exception:
                pass
        if restore is not None:
            view._in_idle_auto_switch = True
            try:
                view.set_expression(restore)
            finally:
                view._in_idle_auto_switch = False


_wake_from_idle_if_needed = _wake_from_idle_if_needed_v2


def _draw_bg_expression_stack_v2(view, painter: QPainter, w: float, h: float) -> None:
    queue = getattr(view, "_bg_text_queue", None)
    if not queue:
        return
    now_ms = time.monotonic() * 1000.0
    alive = []
    font_px = max(14, min(28, int(min(w, h) * 0.068)))
    font = QFont("Segoe UI", -1, QFont.Weight.Bold)
    font.setPixelSize(font_px)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
    painter.save()
    painter.setFont(font)
    fm = QFontMetrics(font)
    line_h = fm.height() + 6
    base_top_y = max(24.0, h * 0.08)

    for item in queue:
        full_txt = item["text"]
        n = len(full_txt)
        if n == 0:
            continue
        elapsed = max(0.0, now_ms - item["spawn_ms"])
        type_dur = n * _BG_TYPE_SPEED_MS
        hold_end = type_dur + _BG_HOLD_DURATION_MS
        bs_dur = n * _BG_BACKSPACE_SPEED_MS
        total_dur = hold_end + bs_dur
        if elapsed >= total_dur:
            continue
        progress_ratio = elapsed / max(1.0, total_dur)
        float_dy = -16.0 * math.sin(progress_ratio * math.pi * 0.5)
        if elapsed < type_dur:
            chars = max(1, min(n, int(elapsed / _BG_TYPE_SPEED_MS) + 1))
            vis_txt = full_txt[:chars] + "\u258e"
            alpha_mult = min(1.0, 0.45 + 0.55 * (chars / float(n)))
        elif elapsed < hold_end:
            vis_txt = full_txt
            hold_frac = (elapsed - type_dur) / max(1.0, _BG_HOLD_DURATION_MS)
            alpha_mult = 1.0 - 0.15 * hold_frac
        else:
            bs_elapsed = elapsed - hold_end
            deleted = int(bs_elapsed / _BG_BACKSPACE_SPEED_MS) + 1
            rem = max(0, n - deleted)
            if rem <= 0:
                continue
            vis_txt = full_txt[:rem] + "\u258e"
            alpha_mult = max(0.25, rem / float(n))
        item["_vis_txt"] = vis_txt
        item["_alpha_mult"] = alpha_mult
        item["_float_dy"] = float_dy
        alive.append(item)

    view._bg_text_queue = alive
    if not alive:
        painter.restore()
        return

    for idx, item in enumerate(alive):
        target_y = base_top_y + idx * line_h + item.get("_float_dy", 0.0)
        if item["y_Render"] is None:
            item["y_Render"] = target_y
        else:
            item["y_Render"] += (target_y - item["y_Render"]) * 0.28
        vis_txt = item["_vis_txt"]
        am = item["_alpha_mult"]
        tw = fm.horizontalAdvance(vis_txt)
        tx = max(18.0, (w - tw) * 0.5)
        ty = item["y_Render"] + fm.ascent()
        painter.setPen(QColor(46, 16, 101, int(95 * am)))
        painter.drawText(QPointF(tx + 1.5, ty + 1.5), vis_txt)
        painter.setPen(QColor(178, 102, 255, int(145 * am)))
        painter.drawText(QPointF(tx, ty), vis_txt)
    painter.restore()


_draw_bg_expression_stack = _draw_bg_expression_stack_v2


def _paint_with_top_layer_eyebrows(self, event) -> None:
    _step_cerebrium_physics(self)
    painter = QPainter(self)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    w = float(self.width())
    h = float(self.height())
    user_scale = float(getattr(self, "_pet_zoom", 1.0)) * float(getattr(self, "_scale", getattr(self, "_user_scale", 1.0)) or 1.0)
    s = min(w / 600.0, h / 400.0) * user_scale
    ox = (w - 600.0 * s) * 0.5
    oy = (h - 400.0 * s) * 0.5

    if getattr(self, "_show_grid", False):
        painter.setPen(QColor(147, 51, 234, 24))
        step = max(16, int(40 * s))
        for gx in range(0, int(w), step):
            painter.drawLine(gx, 0, gx, int(h))
        for gy in range(0, int(h), step):
            painter.drawLine(0, gy, int(w), gy)

    _draw_bg_expression_stack(self, painter, w, h)

    cmap = (
        globals().get("KIND_COLORS")
        or globals().get("PRIMITIVE_COLORS")
        or globals().get("COLORS")
        or {}
    )
    default_colors = {
        "eyelid": QColor(168, 85, 247),
        "eyebrow": QColor(192, 132, 252),
        "mid_bar": QColor(168, 85, 247),
        "bottom_bar": QColor(168, 85, 247),
        "stem": QColor(248, 244, 255),
        "blush": QColor(244, 114, 182),
        "perm_blush": QColor(244, 114, 182),
        "tear": QColor(56, 189, 248),
        "cartoon_sweat": QColor(103, 232, 249),
        "exclamation": QColor(248, 113, 113),
        "icon": QColor(192, 132, 252),
        "dust": QColor(245, 248, 255),
    }

    painter.setPen(Qt.PenStyle.NoPen)
    # Sort particles so eyelids (8) and eyebrows (9) are ALWAYS painted on top of stems (4)
    ordered_particles = sorted(
        self._particles,
        key=lambda pt: _PARTICLE_LAYER_ORDER.get(pt.get("kind", ""), 4),
    )
    for p in ordered_particles:
        a = int(max(0.0, min(255.0, p["alpha"])))
        if a <= 2:
            continue
        kind = p["kind"]
        base_c = cmap.get(kind) or default_colors.get(kind) or QColor(168, 85, 247)
        c = QColor(base_c)
        if kind == "dust":
            c = QColor(245, 248, 255)
        c.setAlpha(a)
        painter.setBrush(c)

        clamped_cx = max(24.0, min(576.0, float(p["cx"])))
        clamped_cy = max(18.0, min(382.0, float(p["cy"])))
        px = ox + clamped_cx * s
        py = oy + clamped_cy * s
        sz = max(2.5, p["size"] * s)
        r_rad = max(1.2, sz * 0.28)
        painter.drawRoundedRect(QRectF(px - sz * 0.5, py - sz * 0.5, sz, sz), r_rad, r_rad)

    painter.end()


AvatarView.paintEvent = _paint_with_top_layer_eyebrows
# ══ WAVE_OMG_PARITY_END ══

# ═══ WAVE OMG WIDGET WAKE IDLE GUARANTEE ═══
_prev_wake_helper_omg = globals().get('_wake_from_idle_if_needed')
def _wake_from_idle_if_needed(av) -> None:
    if callable(_prev_wake_helper_omg):
        try:
            _prev_wake_helper_omg(av)
        except Exception:
            pass
    if av is not None:
        try:
            av._fatigue_stage = 'idle'
            av._idle_macro_t = 0.0
            av._was_napping = False
        except Exception:
            pass

if 'AvatarWidget' in globals():
    _orig_av_wake_omg = getattr(AvatarWidget, '_pre_omg_wake', None) or getattr(AvatarWidget, 'wake_avatar', None)
    if _orig_av_wake_omg is not None:
        AvatarWidget._pre_omg_wake = _orig_av_wake_omg
    def _patched_av_wake_omg(self, *args, **kwargs):
        res = None
        if callable(_orig_av_wake_omg):
            try:
                res = _orig_av_wake_omg(self, *args, **kwargs)
            except Exception:
                pass
        self._fatigue_stage = 'idle'
        self._idle_macro_t = 0.0
        self._was_napping = False
        if hasattr(self, 'blink_now'):
            try:
                self.blink_now()
            except Exception:
                pass
        return res
    AvatarWidget.wake_avatar = _patched_av_wake_omg

# === WAVE_OMG_WIDGET_FATIGUE_FIX ===
if 'AvatarWidget' in globals():
    _orig_av_wake_omg = getattr(AvatarWidget, 'wake_avatar', None)
    def _patched_av_wake_omg(self, *args, **kwargs):
        self._fatigue_stage = 'idle'
        self._was_napping = True
        res = _orig_av_wake_omg(self, *args, **kwargs) if callable(_orig_av_wake_omg) else None
        self._fatigue_stage = 'idle'
        try:
            _wake_from_idle_if_needed(self)
        except Exception:
            pass
        if hasattr(self, 'blink_now'):
            try:
                self.blink_now()
            except Exception:
                pass
        return res
    AvatarWidget.wake_avatar = _patched_av_wake_omg


def _cel_norm_expr(expression, owner=None):
    """Wave-5 root-cause guard: `_expr` must be an expression object or None,
    never a str. If a str (a name) is passed, try to resolve it via the
    owner's avatar library; otherwise fall back to None so the existing
    `if e is None` guards short-circuit instead of crashing."""
    if expression is None or not isinstance(expression, str):
        return expression
    try:
        lib = None
        for attr in ("_library", "library", "_lib", "_avatar_library"):
            cand = getattr(owner, attr, None)
            if cand is not None and hasattr(cand, "get"):
                lib = cand
                break
        gender = "Female"
        for gattr in ("_gender", "gender", "_companion_gender"):
            gv = getattr(owner, gattr, None)
            if isinstance(gv, str) and gv:
                gender = gv
                break
        if lib is not None and hasattr(lib, "get"):
            got = lib.get(gender, expression)
            if got is not None:
                return got
    except Exception:
        pass
    return None
