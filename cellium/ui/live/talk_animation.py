"""Mouth movement while Cel speaks.

The expression library is a set of **static point sets**, so "talking" has to be
synthesised. We modulate only the mouth primitives (``stem``, ``bottom_bar``,
``mid_bar``) and leave every other point untouched - which keeps blinking, brows
and blushes exactly as the chosen expression defined them.

Nothing here mutates a cached :class:`AvatarExpression`: `talking_expression`
builds a fresh one, so scrubbing the library, undoing a mood change, or switching
gender can never leave a half-open mouth behind in a shared object.
"""

from __future__ import annotations

import math

from ..avatar.schema import AvatarExpression, AvatarPoint

__all__ = ["MOUTH_KINDS", "talking_expression", "TalkEnvelope"]

MOUTH_KINDS = ("stem", "bottom_bar", "mid_bar")

# Vertical travel per primitive, in stored face units.
_LIFT = {"stem": 7.0, "bottom_bar": 5.0, "mid_bar": 4.0}


def talking_expression(base: AvatarExpression, openness: float) -> AvatarExpression:
    """Return ``base`` with the mouth opened to ``openness`` (0.0 .. 1.0).

    Only the right-hand (non-``left``) mouth primitives move, matching how the
    expressions are authored - the left flag marks the mirrored half.
    """
    if not base or base.points is None:
        return base
    amount = max(0.0, min(1.0, float(openness)))
    if amount <= 0.001:
        return base
    out = []
    for p in base.points:
        lift = _LIFT.get(p.kind) if not p.left else None
        if lift:
            out.append(AvatarPoint(p.x, p.y + lift * amount, p.kind, p.left))
        else:
            out.append(p)
    return base.with_points(out)


class TalkEnvelope:
    """Smoothed pseudo-random mouth envelope.

    Real amplitude is not exposed by the TTS workers, so we synthesise one. It is
    deliberately band-limited (a slow carrier plus a faster wobble) because a
    random-per-tick value reads as visual static rather than speech.

    Feed it ``progress`` (0..1) as well: between audio chunks the mouth would
    otherwise freeze, so progress keeps it moving through the gaps.
    """

    def __init__(self, hz: float = 12.0, seed: float = 0.0):
        self.hz = max(1.0, float(hz))
        self._phase = seed
        self._value = 0.0

    @property
    def value(self) -> float:
        return self._value

    def step(self, dt: float = 1.0 / 12.0, progress: float = 1.0, active: bool = True) -> float:
        if not active:
            # Ease closed rather than snapping, or every pause looks like a glitch.
            self._value += (0.0 - self._value) * min(1.0, dt * 10.0)
            return self._value
        self._phase += dt * self.hz * 0.55
        carrier = 0.5 + 0.5 * math.sin(self._phase * 0.9)
        wobble = 0.5 + 0.5 * math.sin(self._phase * 2.7 + 1.3)
        target = max(0.0, min(1.0, 0.18 + 0.72 * (0.65 * carrier + 0.35 * wobble)))
        # Progress nudges it upward near the end of a chunk so the mouth is open
        # when the audio is actually sounding.
        target *= 0.72 + 0.28 * max(0.0, min(1.0, progress))
        self._value += (target - self._value) * min(1.0, dt * 18.0)
        return self._value
