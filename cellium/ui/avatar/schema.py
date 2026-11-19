"""Avatar expression schema.

Recovered from the archived `Cerebellium Opus.py` (`AnimationPoint`,
`Animation`, `AnimationLibrary`) so that expressions exported out of the Opus
base85 payload load here byte-for-byte.

Coordinate convention (kept identical to Opus on purpose):

* Stored points are absolute; ``x`` runs 0..600 and ``y`` 0..400 in the
  canonical 600x400 space.
* On load, Opus subtracts ``(300, 200)`` so the face is centred on the origin.
  We keep the *stored* form and let the renderer centre it, because that keeps
  round-tripping lossless.

Validation mirrors Opus exactly so that nothing which loaded there fails here:
bounds ``-500..1100`` x, ``-500..900`` y, kind matching ``[A-Za-z_]{1,32}``,
1..2048 points, ``left`` strictly boolean.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Optional, Sequence

__all__ = [
    "AvatarError", "AvatarPoint", "AvatarExpression", "CANONICAL_W",
    "CANONICAL_H", "MAX_POINTS", "KINDS", "STYLE_MODIFIERS",
]

CANONICAL_W = 600.0
CANONICAL_H = 400.0
MAX_POINTS = 2048

_KIND_RE = re.compile(r"^[A-Za-z_]{1,32}$")

#: Every drawing primitive observed across the 728 recovered expressions.
#: Female-only entries are marked; the loader tolerates either set per gender.
KINDS = frozenset({
    "eyelid", "eyebrow", "icon", "stem", "bottom_bar", "mid_bar",
    "exclamation", "blush", "tear", "perm_blush", "cartoon_sweat", "dust",
})

#: The nine style modifiers Opus applied to 32 of its 76 base expressions.
STYLE_MODIFIERS = (
    "Chibi", "Cocky", "Downcast", "Intense",
    "Left Glance", "Right Glance", "Subtle", "Unhinged", "Upward",
)


class AvatarError(ValueError):
    """Raised when an expression file violates the schema."""


@dataclass(frozen=True)
class AvatarPoint:
    x: float
    y: float
    kind: str
    left: bool = True

    def to_json(self) -> list:
        return [round(self.x, 3), round(self.y, 3), self.kind, bool(self.left)]

    @classmethod
    def parse(cls, row: Sequence) -> "AvatarPoint":
        if not isinstance(row, (list, tuple)) or len(row) != 4:
            raise AvatarError("Every avatar point must be [x, y, kind, left].")
        if isinstance(row[0], bool) or isinstance(row[1], bool):
            raise AvatarError("Coordinate must be a number, not a bool.")
        try:
            x, y = float(row[0]), float(row[1])
        except (TypeError, ValueError, OverflowError) as exc:
            raise AvatarError("Invalid avatar coordinates.") from exc
        if not math.isfinite(x) or not math.isfinite(y):
            raise AvatarError("Coordinates must be finite.")
        if not (-500 <= x <= 1100 and -500 <= y <= 900):
            raise AvatarError("Coordinates exceed safe bounds.")
        kind = row[2]
        if not isinstance(kind, str) or not _KIND_RE.match(kind):
            raise AvatarError(f"Invalid point kind: {kind!r}")
        if row[3] not in (True, False) or isinstance(row[3], int) and not isinstance(row[3], bool):
            raise AvatarError("Point side must be exactly True or False.")
        return cls(x=x, y=y, kind=kind, left=bool(row[3]))


def _num(value, default: float, low: float, high: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return max(low, min(high, out))


def _flag(value, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return default


@dataclass
class AvatarExpression:
    name: str
    gender: str
    points: tuple = ()
    blink_enabled: bool = True
    blink_left: bool = True
    blink_right: bool = True
    left_depth: float = 55.0
    right_depth: float = 55.0
    left_eyebrow_dip: float = 4.0
    right_eyebrow_dip: float = 4.0
    left_eye_shift: float = 0.0
    right_eye_shift: float = 0.0
    left_speed: float = 1.0
    right_speed: float = 1.0
    fade_opacity: float = 0.0
    occlusion_offset: float = 0.0

    # ── construction ─────────────────────────────────────────────────────
    @classmethod
    def parse(cls, name: str, gender: str, raw) -> "AvatarExpression":
        obj = raw if isinstance(raw, dict) else {"points": raw}
        rows = obj.get("points")
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_POINTS:
            raise AvatarError(f"'{name}' needs 1-{MAX_POINTS} points, got {len(rows) if isinstance(rows, list) else 'none'}.")
        points = tuple(AvatarPoint.parse(r) for r in rows)

        kwargs = {"name": name, "gender": gender, "points": points}
        kwargs["blink_enabled"] = _flag(obj.get("blink_enabled", obj.get("blink", True)), True)
        kwargs["blink_left"] = _flag(obj.get("blink_left"), True)
        kwargs["blink_right"] = _flag(obj.get("blink_right"), True)
        for side in ("left", "right"):
            for suffix, default, low, high in (
                ("depth", 55.0, -100.0, 250.0),
                ("eyebrow_dip", 4.0, -50.0, 100.0),
                ("eye_shift", 0.0, -50.0, 50.0),
                ("speed", 1.0, 0.25, 3.0),
            ):
                legacy = "blink_depth" if suffix == "depth" else suffix
                raw_v = obj.get(f"{side}_{suffix}", obj.get(legacy))
                kwargs[f"{side}_{suffix}"] = _num(raw_v, default, low, high)
        kwargs["fade_opacity"] = _num(obj.get("fade_opacity"), 0.0, 0.0, 1.0)
        kwargs["occlusion_offset"] = _num(obj.get("occlusion_offset"), 0.0, -100.0, 150.0)
        return cls(**kwargs)

    @classmethod
    def from_file(cls, path: Path) -> "AvatarExpression":
        gender = path.parent.name
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AvatarError(f"{path.name}: unreadable ({exc})") from exc
        return cls.parse(path.stem, gender, raw)

    def to_json(self) -> dict:
        out = {
            "blink_enabled": self.blink_enabled,
            "blink_left": self.blink_left,
            "blink_right": self.blink_right,
            "left_depth": self.left_depth,
            "right_depth": self.right_depth,
            "left_eyebrow_dip": self.left_eyebrow_dip,
            "right_eyebrow_dip": self.right_eyebrow_dip,
            "left_eye_shift": self.left_eye_shift,
            "right_eye_shift": self.right_eye_shift,
            "left_speed": self.left_speed,
            "right_speed": self.right_speed,
            "fade_opacity": self.fade_opacity,
            "occlusion_offset": self.occlusion_offset,
        }
        out["points"] = [p.to_json() for p in self.points]
        return out

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), ensure_ascii=False,
                                   indent=1, allow_nan=False), encoding="utf-8")
        return path

    # ── convenience ──────────────────────────────────────────────────────
    @property
    def modifier(self) -> Optional[str]:
        for m in STYLE_MODIFIERS:
            if self.name.endswith(" - " + m):
                return m
        return None

    @property
    def base_name(self) -> str:
        for m in STYLE_MODIFIERS:
            if self.name.endswith(" - " + m):
                return self.name[: -(len(m) + 3)]
        return self.name

    def by_kind(self) -> dict:
        out: dict = {}
        for p in self.points:
            out.setdefault(p.kind, []).append(p)
        return out

    def with_points(self, points: Iterable[AvatarPoint]) -> "AvatarExpression":
        return replace(self, points=tuple(points))

    def renamed(self, name: str) -> "AvatarExpression":
        return replace(self, name=name)
