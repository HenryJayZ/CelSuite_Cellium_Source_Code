"""Style-modifier transforms for avatar expressions.

The archived Opus library holds 76 base expressions, of which only 32 were
given the full set of nine style modifiers ("Chibi", "Cocky", "Downcast",
"Intense", "Left Glance", "Right Glance", "Subtle", "Unhinged", "Upward"),
leaving 320 combinations per gender unused.

These transforms reproduce a modifier geometrically from its base expression, so
the matrix can be completed to 76 x 9 = 684 expressions per gender rather than
hand-authoring thousands of JSON files.

Every transform is a pure function ``AvatarExpression -> AvatarExpression``.
They operate on point groups by kind, which is how the archive's own data is
shaped, and they never invent new primitives.
"""

from __future__ import annotations

import math
from typing import Callable, Dict

from .schema import STYLE_MODIFIERS, AvatarExpression, AvatarPoint

__all__ = ["VARIANT_TRANSFORMS", "apply_modifier", "available_modifiers"]

# Point kinds that make up the eyes. Glance / vertical modifiers move these.
_EYE_KINDS = ("eyelid", "eyebrow")
_MOUTH_KINDS = ("stem", "bottom_bar", "mid_bar")

#: Canonical face centre in stored coordinates (Opus subtracts 300/200).
_CX, _CY = 300.0, 200.0


def _clone_points(expr: AvatarExpression) -> list:
    return list(expr.points)


def _scaled_about_centre(p: AvatarPoint, sx: float, sy: float) -> AvatarPoint:
    return AvatarPoint(_CX + (p.x - _CX) * sx, _CY + (p.y - _CY) * sy, p.kind, p.left)


def _translated(p: AvatarPoint, dx: float, dy: float) -> AvatarPoint:
    return AvatarPoint(p.x + dx, p.y + dy, p.kind, p.left)


# ── individual modifiers ─────────────────────────────────────────────────────

def _chibi(expr: AvatarExpression) -> AvatarExpression:
    """Rounder, larger features pushed toward a chibi silhouette."""
    out = []
    for p in _clone_points(expr):
        if p.kind == "eyelid":
            out.append(_scaled_about_centre(p, 1.10, 1.22))
        elif p.kind in _EYE_KINDS:
            out.append(_scaled_about_centre(p, 1.06, 1.14))
        elif p.kind == "blush":
            out.append(_scaled_about_centre(p, 1.18, 1.18))
        else:
            out.append(_scaled_about_centre(p, 1.04, 1.04))
    return expr.with_points(out)


def _cocky(expr: AvatarExpression) -> AvatarExpression:
    """Lopsided confidence: one brow up, mouth tilted."""
    out = []
    for p in _clone_points(expr):
        if p.kind == "eyebrow" and p.left:
            out.append(_translated(p, 0.0, -7.0))
        elif p.kind in _MOUTH_KINDS and p.left:
            out.append(_translated(p, 0.0, 2.5))
        else:
            out.append(p)
    return expr.with_points(out)


def _downcast(expr: AvatarExpression) -> AvatarExpression:
    """Drooped gaze: eyes and brows fall."""
    out = []
    for p in _clone_points(expr):
        if p.kind in _EYE_KINDS:
            out.append(_translated(p, 0.0, 4.5))
        elif p.kind in _MOUTH_KINDS:
            out.append(_translated(p, 0.0, 2.0))
        else:
            out.append(p)
    return expr.with_points(out)


def _intense(expr: AvatarExpression) -> AvatarExpression:
    """Hard stare: narrowed eyes, pressed-down brows."""
    out = []
    for p in _clone_points(expr):
        if p.kind == "eyelid":
            out.append(_scaled_about_centre(p, 0.84, 0.80))
        elif p.kind == "eyebrow":
            out.append(_translated(p, 0.0, 3.0))
        elif p.kind in _MOUTH_KINDS:
            out.append(_scaled_about_centre(p, 0.92, 0.92))
        else:
            out.append(p)
    return expr.with_points(out)


def _glance(dx: float):
    def _inner(expr: AvatarExpression) -> AvatarExpression:
        out = []
        for p in _clone_points(expr):
            out.append(_translated(p, dx, 0.0) if p.kind in _EYE_KINDS else p)
        return expr.with_points(out)
    return _inner


def _left_glance(expr: AvatarExpression) -> AvatarExpression:
    return _glance(-11.0)(expr)


def _right_glance(expr: AvatarExpression) -> AvatarExpression:
    return _glance(11.0)(expr)


def _subtle(expr: AvatarExpression) -> AvatarExpression:
    """Muted: pull every group 40% toward its own centroid."""
    groups: Dict[str, list] = {}
    for p in expr.points:
        groups.setdefault(p.kind, []).append(p)
    centroids = {
        k: (sum(q.x for q in v) / len(v), sum(q.y for q in v) / len(v))
        for k, v in groups.items() if v
    }
    blend = 0.40
    out = []
    for p in _clone_points(expr):
        cx, cy = centroids.get(p.kind, (_CX, _CY))
        out.append(AvatarPoint(p.x + (cx - p.x) * blend,
                               p.y + (cy - p.y) * blend,
                               p.kind, p.left))
    return expr.with_points(out)


def _unhinged(expr: AvatarExpression) -> AvatarExpression:
    """Deliberately asymmetric: push the two sides apart and tilt the mouth."""
    out = []
    for p in _clone_points(expr):
        if p.kind in _EYE_KINDS or p.kind in _MOUTH_KINDS:
            if p.left:
                out.append(_translated(p, -5.0, -5.0))
            else:
                out.append(_translated(p, 5.0, 5.0))
        else:
            out.append(p)
    return expr.with_points(out)


def _upward(expr: AvatarExpression) -> AvatarExpression:
    """Looking up: eyes and brows rise."""
    out = []
    for p in _clone_points(expr):
        if p.kind in _EYE_KINDS:
            out.append(_translated(p, 0.0, -6.0))
        else:
            out.append(p)
    return expr.with_points(out)


VARIANT_TRANSFORMS: Dict[str, Callable[[AvatarExpression], AvatarExpression]] = {
    "Chibi": _chibi,
    "Cocky": _cocky,
    "Downcast": _downcast,
    "Intense": _intense,
    "Left Glance": _left_glance,
    "Right Glance": _right_glance,
    "Subtle": _subtle,
    "Unhinged": _unhinged,
    "Upward": _upward,
}


def available_modifiers() -> tuple:
    return STYLE_MODIFIERS


def apply_modifier(base: AvatarExpression, modifier: str) -> AvatarExpression:
    """Return ``base`` restyled by ``modifier`` and renamed accordingly."""
    fn = VARIANT_TRANSFORMS.get(modifier)
    if fn is None:
        raise KeyError(f"Unknown style modifier: {modifier!r}")
    styled = fn(base)
    return styled.renamed(f"{base.base_name} - {modifier}")

STYLE_MODIFIERS = ("Subtle",)
