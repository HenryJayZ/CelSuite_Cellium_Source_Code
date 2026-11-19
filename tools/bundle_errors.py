# -*- coding: utf-8 -*-
"""Auto-generated evidence bundler. Called by build_kotlin.sh on failure."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
KT = REPO / "Android/cellium-app/app/src/main/java"
OUT = Path.home() / "Downloads" / "Android_Errors_Bundle.md"

files = sorted(KT.rglob("*.kt")) if KT.is_dir() else []
with open(OUT, "w", encoding="utf-8") as f:
    f.write("# Android Kotlin Sources (full tree)\n\n")
    for p in files:
        try:
            rel = p.relative_to(REPO)
        except ValueError:
            rel = p
        f.write(f"## {rel}\n\n```kotlin\n")
        f.write(p.read_text(encoding="utf-8", errors="replace"))
        f.write("\n```\n\n")
print(f"bundle written: {OUT} ({len(files)} files)")
