# Operation: Save Henry's Performance In Rust 🦀

> **Read this first in any new session.** The mission: systematically migrate Henny's
> Python/PySide6 projects toward Rust, starting with the bottlenecks, not the widgets.
> Flagship context: **Cellium ~105,000 lines of Python (>1M tokens)** — that scale is a
> strategy, not a rewrite target. This file lives in `Projects/Python/Cellium/` so every
> future chat inherits the plan instantly.
> Do NOT commit secrets to this file, ever.

---

## 1. Why (the honest pitch)

1. **Python bottleneck = interpreter + GIL + startup + memory.** Rust compiles to native
   machine code: no interpreter, no GIL, ~MB binaries, sub-100 ms launches.
2. **Henny is already ~70% there.** The Horizon launcher he's been running all day is a
   production Rust GUI app (GPUI). The skills transfer. This is not a cold start.
3. **PySide6 is the cage.** Long-lived PySide apps get slower to build, package (Nuitka =
   multi-GB toolchains), and scale. In Rust, one `cargo build --release` ships a single
   self-contained binary — no runtime, no venv, no installer wizard.
4. **Examples of speed wins won already:** the Horizon engine runs Minecraft in Rust at
   interactive rates on an Intel HD 4600 — Python "inspired ports" die on that hardware.

## 2. Inventory (fill this in per project)

| Project | Lines (py) | Hot spots | GUI? | Strategy |
| --- | --- | --- | --- | --- |
| Cellium | ~105k | _(fill in)_ | PySide6 | §3 ladder |
| _(others)_ | | | | |

Detect hot spots yourself: `python3 -c` + `cProfile`, measure startup time, memory, and
package size *before* touching anything. No measurement = no migration.

## 3. The ladder (in order — never skip a rung)

**Rung 1 — PyO3 bridge (default first move).** Keep the PySide6 UI. Extract the 10-20%
of code that burns 90% of CPU (parsers, crypto, media, networking, DB/walking) into a
Rust crate (`pyo3` + ` maturin`/`setuptools-rust`). Call it from Python like a normal
library. Result: instant speedups, zero UI rewrite, one new cargo dep.

**Rung 2 — One Rust-native rewrite (prove it).** Pick the *smallest* user-facing tool,
rewrite fully in Rust. For tools/utilities: **egui** (fewest lines, immediate mode, GPU
via wgpu). This validates the skill transfer and a packaging story (CI like the Horizon
launcher: build on push, publish signed release).

**Rung 3 — Production-class apps: GPUI.** Big, polished, long-lived apps with heavy
lists/tables/text (the Zed engine = what the Horizon launcher runs on). Fewer mistakes
in big projects, steepest learning curve — you already run one, so you have a teacher.

**Rung 4 — Qt-brand people: Slint.** Declarative `.slint` markup ≈ QML, Rust logic
underneath, first-party Python/C++/JS bindings too (so it's also a bridge, not a leap).
Pick this when the UI has to look designed, not assembled.

**Rung 5 — Web-flavored UI: Tauri / Dioxus.** If the app is mostly tables/forms/
markdown/editors of documents, keep HTML/CSS/JS front ends and put everything
behind a Rust core (Tauri) or go full-Rust React-style (Dioxus).

## 4. Per-project protocol

1. Profile. Record: startup ms, memory MB, package MB, worst function + its share.
2. Apply Rung 1 to the worst 20% first. Re-profile. Keep the wins in a table in §2.
3. If a full rewrite is picked (Rung 2+), list screens/commands FIRST, then port
   screens in vertical slices (one view fully working beats ten half-done).
4. Ship dual: `--standalone` folder + portable single file, versioned
   `YYM.DD.V` (YYM = 2-digit year + month, DD = day, V = build #).
5. CI builds the binary (no local 30-min cargo on the i5 — cloud builds it, Henny
   downloads artifacts, same as the Horizon game/launcher flow).
6. Update this file with what actually happened (dates, numbers, failures).

## 5. Rules that protect Henny

- **No quota-burning rewrites.** A project over ~20k lines is a bridge candidate
  (Rung 1) until proven otherwise; Cellium (105k) is *never* a rewrite target.
- **Rust is for speed, not purity.** If a GUI is easier in PySide and it isn't slow,
  it stays PySide. No religion.
- **Trash before delete; never hard-delete.** Backups in
  `~/Documents/Projects/OpenCode/tmp/Trash/` (or a per-project `.backups/`).
- **Packaging rules:** PySide6 only (never PyQt6) when Python remains; Nuitka over
  PyInstaller; central venv at `~/Documents/Projects/Python/venv`; Flatpak is the
  nuclear option (never).
- **Use env vars, not flags, for machine settings**; paths with spaces must be quoted;
  never `rm -rf` — move to Trash and let Henny empty it.

## 6. Next moves (in order)

1. Inventory Cellium (§2) + profile it. One chat, one table.
2. Bridge its worst function (Rung 1). Prove the speedup.
3. Rewrite the smallest useful tool in egui (Rung 2).
4. Promote Cellium screens to GPUI one by one (Rung 3) as they get painful.
5. Revisit this file after each step; numbers or it didn't happen.

---

*Last updated: 2026-11-09. Next milestone: Cellium inventory + a pyo3 spike.*
