"""Avatar expression library.

Loads ``Anim/<Gender>/*.json`` from this package and, on demand, completes the
style-modifier matrix.

Cellium ships 728 expressions recovered from the archived
``Cerebellium Opus.py`` base85 payload (364 Female + 364 Male). Of those, 32
base expressions per gender carry all nine style modifiers; the other 44 do
not. :meth:`AvatarLibrary.complete_matrix` fills those gaps procedurally.
"""

from __future__ import annotations

import copy
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .schema import (
    STYLE_MODIFIERS,
    AvatarError,
    AvatarExpression,
)
from .variants import VARIANT_TRANSFORMS, apply_modifier

__all__ = ["AvatarLibrary", "ANIM_ROOT", "GENDERS"]

ANIM_ROOT = Path(__file__).resolve().parent / "Anim"
GENDERS = ("Female", "Male", "Detailed Female", "Detailed Male", "Chibi")

_UNSAFE = re.compile(r'[\\/:*?"<>|]')


def _safe_filename(title: str) -> str:
    cleaned = _UNSAFE.sub("_", title).strip()
    return cleaned or "Unnamed"


class AvatarLibrary:
    """In-memory store of expressions, indexed by gender then title."""

    def __init__(self, root: Optional[Path] = None, autoload: bool = True):
        self.root = Path(root) if root else ANIM_ROOT
        self.expressions: Dict[str, Dict[str, AvatarExpression]] = {g: {} for g in GENDERS}
        self.errors: List[str] = []
        if autoload:
            self.load()

    # ── loading ──────────────────────────────────────────────────────────
    def load(self, limit_per_gender: int = 4096) -> int:
        self.errors.clear()
        loaded = 0
        for gender in GENDERS:
            folder = self.root / gender
            if not folder.is_dir():
                self.errors.append(f"missing folder: {folder}")
                continue
            try:
                paths = sorted(folder.glob("*.json"))[:limit_per_gender]
            except OSError as exc:
                self.errors.append(f"{gender}: {exc}")
                continue
            for path in paths:
                try:
                    expr = AvatarExpression.from_file(path)
                except AvatarError as exc:
                    self.errors.append(str(exc))
                    continue
                except Exception as exc:  # defensive: never fail a whole load
                    self.errors.append(f"{path.name}: unexpected {type(exc).__name__}")
                    continue
                self.expressions.setdefault(gender, {})[expr.name] = expr
                loaded += 1
        return loaded

    # ── incremental loading (UI-friendly) ────────────────────────────────
    # ``load()`` is all-or-nothing, which is fine for tests but freezes the UI
    # for ~1s on 1,520 files. The studio drives ``add_file`` from a QTimer so
    # the page can paint a progress bar between batches.
    def files(self, gender: str) -> List[Path]:
        folder = self.root / gender
        if not folder.is_dir():
            self.errors.append(f"missing folder: {folder}")
            return []
        try:
            return sorted(folder.glob("*.json"))
        except OSError as exc:
            self.errors.append(f"{gender}: {exc}")
            return []

    def add_file(self, gender: str, path: Path) -> bool:
        """Parse one expression file into the index. False if it was rejected."""
        try:
            expr = AvatarExpression.from_file(path)
        except AvatarError as exc:
            self.errors.append(str(exc))
            return False
        except Exception as exc:  # defensive: one bad file must not stop the rest
            self.errors.append(f"{path.name}: unexpected {type(exc).__name__}")
            return False
        self.expressions.setdefault(gender, {})[expr.name] = expr
        return True

    def load_gender(self, gender: str, batch_size: int = 96,
                    should_cancel=None) -> Iterable[int]:
        """Load one gender in batches, yielding the running total.

        ``should_cancel`` is an optional predicate; when it returns True the
        generator stops early. Used by the avatar studio to load off the
        critical path. The end state is identical to :meth:`load`.
        """
        bucket = self.expressions.setdefault(gender, {})
        paths = self.files(gender)
        loaded = 0
        for start in range(0, len(paths), max(1, batch_size)):
            if should_cancel is not None and should_cancel():
                return
            for path in paths[start:start + max(1, batch_size)]:
                if self.add_file(gender, path):
                    loaded += 1
            bucket = self.expressions.setdefault(gender, {})
            yield loaded

    # ── access ───────────────────────────────────────────────────────────
    def names(self, gender: str = "Female") -> List[str]:
        return sorted(self.expressions.get(gender, self.expressions.get("Female", {})))

    def get(self, gender: str, name: str) -> Optional[AvatarExpression]:
        return self.expressions.get(gender, {}).get(name)

    def count(self, gender: Optional[str] = None) -> int:
        if gender:
            return len(self.expressions.get(gender, {}))
        return sum(len(v) for v in self.expressions.values())

    def base_names(self, gender: str = "Female") -> List[str]:
        return sorted({e.base_name for e in self.expressions.get(gender, {}).values()})

    def modifier(self, gender: str, modifier: str) -> List[str]:
        return sorted(n for n in self.names(gender) if n.endswith(" - " + modifier))

    def __contains__(self, name: str) -> bool:
        return any(name in bucket for bucket in self.expressions.values())

    def __len__(self) -> int:
        return self.count()

    # ── matrix analysis ──────────────────────────────────────────────────
    def matrix_report(self, gender: str = "Female") -> dict:
        bases = self.base_names(gender)
        have = self.expressions.get(gender, {})
        per_modifier = {
            m: sum(1 for b in bases if f"{b} - {m}" in have)
            for m in STYLE_MODIFIERS
        }
        complete = [b for b in bases
                    if all(f"{b} - {m}" in have for m in STYLE_MODIFIERS)]
        return {
            "gender": gender,
            "bases": len(bases),
            "total": len(have),
            "variants_present": sum(per_modifier.values()),
            "per_modifier": per_modifier,
            "bases_with_all_variants": len(complete),
            # Ceilings: the variant grid is bases x modifiers; total files would
            # additionally include the bare base expressions themselves.
            "max_variant_matrix": len(bases) * len(STYLE_MODIFIERS),
            "max_total_files": len(bases) * (len(STYLE_MODIFIERS) + 1),
            "headroom": len(bases) * len(STYLE_MODIFIERS) - sum(per_modifier.values()),
        }

    # ── generation ───────────────────────────────────────────────────────
    def generate_missing(self, gender: str, write: bool = True,
                         overwrite: bool = False) -> List[AvatarExpression]:
        """Create every ``<base> - <modifier>`` combination that is absent.

        Returns the newly created expressions. With ``write=True`` each is saved
        into ``Anim/<gender>/`` so it persists like any hand-authored file.
        """
        bucket = self.expressions.setdefault(gender, {})
        folder = self.root / gender
        created: List[AvatarExpression] = []
        for base_name in self.base_names(gender):
            base = bucket.get(base_name)
            if base is None:
                continue
            for modifier in STYLE_MODIFIERS:
                target = f"{base_name} - {modifier}"
                if target in bucket and not overwrite:
                    continue
                try:
                    made = apply_modifier(base, modifier)
                except (KeyError, AvatarError) as exc:
                    self.errors.append(f"{target}: {exc}")
                    continue
                bucket[target] = made
                created.append(made)
                if write:
                    try:
                        made.save(folder / f"{_safe_filename(target)}.json")
                    except OSError as exc:
                        self.errors.append(f"{target}: cannot save ({exc})")
        return created

    def complete_matrix(self, write: bool = True) -> Dict[str, int]:
        """Run :meth:`generate_missing` for every gender. Returns counts."""
        return {g: len(self.generate_missing(g, write=write)) for g in GENDERS}

    # ── deletion ───────────────────────────────────────────────────────
    def delete(self, gender: str, name: str) -> tuple:
        """Delete ONE expression - a child variant only, never a base.

        The file is moved to ``Anim/_Trash/<Gender>/`` (recoverable, and it
        honours the project's no-``rm`` rule) and the in-memory index entry
        is dropped. Returns ``(ok, reason)`` where reason is one of
        ``"moved"``, ``"already gone"``, ``"base"`` (family anchors are
        refused - delete/curate only ever culls children), ``"missing"``
        (not loaded) or the OS error text.
        """
        bucket = self.expressions.get(gender, {})
        expr = bucket.get(name)
        if expr is None:
            return False, "missing"
        try:
            is_base = (expr.base_name == name)
        except Exception:
            is_base = (" - " not in str(name))
        if is_base:
            return False, "base"
        moved = False
        try:
            path = self.root / gender / f"{_safe_filename(name)}.json"
            if path.is_file():
                trash = self.root / "_Trash" / gender
                trash.mkdir(parents=True, exist_ok=True)
                dest = trash / path.name
                if dest.exists():
                    dest = trash / f"{path.stem}_{int(time.time())}.json"
                path.replace(dest)
                moved = True
        except OSError as exc:
            return False, str(exc)
        bucket.pop(name, None)
        return True, ("moved" if moved else "already gone")

    # ── export ───────────────────────────────────────────────────────────
    def iter_all(self) -> Iterable[AvatarExpression]:
        for gender in GENDERS:
            for expr in self.expressions.get(gender, {}).values():
                yield expr

# matrix_report is intentionally left unpatched: the studio must show real
# coverage, and the regression check compares it against the files on disk.


# delete() is intentionally left unpatched: base expressions are refused, and
# the studio hides bases instead of quietly moving their JSON files to _Trash.
