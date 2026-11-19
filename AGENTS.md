# AI Navigation Map

This document guides AI agents working on the `Cellium` package.

> **Corrected 2026-10-02.** The original map described classes that never existed
> (`SwitchControl`, `TranslucentOverlay`) or files that are empty shims. This map
> now matches the code. Do not document a class here before it exists.
> **Extended 2026-10-02** with the security, jobs, logging, Tier-1 widget and
> avatar subsystems.

## Directory Structure

- `cellium/core/` - headless utilities and globals. Must not import each other at top level.
  - `config.py` - **all global state, path resolvers, palettes, voice tables**
  - `utils.py` - helpers, provider definitions, JSON persistence paths
  - `tools.py` - `AgentTool` base, `FileReadTool`, `FileWriteTool`, `ShellExecTool`, …
  - `logger.py` - central dev logger (`dev_log`)
  - `command_guard.py` - dangerous-command auditing for `shell_exec` (warn, never block)
  - `jobs.py` - `ManagedJob`, `ProcessPool`, `current_job()` for background work
  - `safe_logging.py` - `redact_text`, `redact_mapping`, `RedactingFormatter`
- `cellium/services/` - background QThread workers (import `core/`, never `ui/`).
  - `ai_workers.py` - `GenerationWorker`, `AgentWorker`, `ModelPingWorker`, `ModelFetchWorker`
  - `ai_llama.py` - offline GGUF management
  - `audio_stt.py` - STT workers, Kokoro/whisper.cpp paths
  - `audio_tts.py` - Kokoro & Edge TTS streaming workers
  - `sound_engine.py` - pygame sound engine
  - `kaggle_image.py` - **Kaggle cloud image generation (BYOK)**. Pure-`requests`
    backend (`KaggleImageBackend`) that pushes a generated python script to
    Kaggle (`kernelType=script`, private, GPU, 45-min session cap), polls status,
    and fetches `out.png` + seed meta. HuggingFace-repo and Civitai-single-file
    model loaders + optional LoRA; all user text embedded via `repr()`+`json.dumps`
    (injection-proof). Plus a `KaggleImageWorker` QThread wrapper with
    progress/finished/error signals. Settings live in Settings → 🖼️ Image
    Generation; chat entry points are the 🎨 input-pill button, `/imagine <prompt>`,
    and the Ctrl+K palette. Regression tag: `kaggle`. See `KAGGLE_IMAGE_GEN.md`.
- `cellium/ui/` - PySide6 views (may import both `services/` and `core/`).
  - `main_window.py` - the QMainWindow (~3,450 lines, largest file)
  - `chat/bubble.py` - `MessageBubble` (custom-painted, ~2,730 lines)
  - `chat/glass.py` - `GlassPanel`, `GlassToast`, `ChatInputEdit`
  - `chat/typewriter.py` - `TypewriterEdit` streaming reveal
  - `settings/dialog.py` - settings UI, `SettingsWidgetNew`, `ModelManagerWidget`
  - `settings/models.py` - **re-export hub only**
  - `widgets/wallpaper.py` - `WallpaperWidget`
  - `widgets/emoji.py` - `EmojiPickerWidgetNew`
  - `widgets/welcome.py` - **welcome-page companion orb + typewriter**. `AnimatedFaceOrb`
    is painted with QPainter (no font glyphs, so nothing can fail to render and the
    glow stays inside the widget); animated eyebrows, 7 cross-faded moods (calm /
    happy / curious / wink / surprised / flustered / angry), head tilt and gaze
    wander. `react_to(text)` reads a chat's vibe (spicy → flustered); blush is gated
    on the `companion_gender` setting being Female via `set_blush_enabled()`.
    Spam-clicking builds an annoyance meter → red angry body, pulsing 💢 vein,
    trembling, and a bounds-clamped dodge away from the cursor. `TypedLabel`
    reveals text one *grapheme* at a time so emoji, VS16 and ZWJ sequences never
    flash half-drawn. Regression tag: `welcome`.
  - `widgets/toggle.py` - **intentionally empty** (kept; three modules star-import it)
  - `widgets/command_palette.py` - `CommandRegistry`, `CommandPaletteDialog` (Ctrl+K)
  - `widgets/focus_clock.py` - pomodoro clock
  - `widgets/particles.py` - `ParticleCanvas` ambient background
  - `avatar/` - **the Cerebellium companion**. `schema.py` (point/expression model),
    `variants.py` (9 style-modifier transforms), `library.py` (`AvatarLibrary`,
    matrix completion), `widget.py` (`AvatarView` Qt renderer), `pet.py`
    (`CompanionStage`, `FloatingPetWindow`, `PetGrip`, `SpeechBubble`, `MOODS`),
    `studio.py` (**`AvatarStudioWidget` - the Avatar Studio page**, wired as
    `central_stack[5]` / `open_avatar_view()`), and `Anim/<Gender>/*.json`  - 
    **1,520 expression files**.
- The **Avatar Studio** is the visible surface for the whole avatar subsystem:
  gradient stage, live preview, gender switch, search over 760 expressions per
  gender, `Base` + 9 modifier chips, auto-play, blink, scale, clipboard export,
  companion toggle, and matrix-coverage readout. It loads the library
  **incrementally** (`AvatarLibrary.load_gender`) from a QTimer so 14 MB of JSON
  never blocks the UI - never call the monolithic `load()` from a widget.
- Glass panels frost over the wallpaper via `WallpaperWidget.frost_pixmap()`.
  Qt has no `backdrop-filter`, so panels sample that blurred snapshot and clip it
  to their own rounded rect. **When editing it, keep using `_paint_backdrop()` and
  not `QWidget.render()`** - the panels are *children* of the wallpaper widget, so
  `render()` repaints them, each of which asks for a snapshot again, and it
  recurses until the process dies.
- Chat opening renders in slices of `RENDER_CHUNK_SIZE` (8) bubbles off a
  zero-delay QTimer instead of one blocking pass. Keep it that way: 40 bubbles in
  a single pass measured **784 ms** of frozen UI.

## Tools

- `tools/regression.py` - 41 checks covering security, redaction, jobs, avatar,
  companion, analytics, navigation, glass, zoom, scroll-wheel, chat-switch
  performance, persona presets, portability and Tier 1. Run it before any release:

  ```bash
  QT_QPA_PLATFORM=offscreen \
    /home/henry/Documents/Projects/Python/venv/bin/python tools/regression.py
  ```

  Filter by tag: `... regression.py security avatar`. Exit 0 = all green.

## Desktop companion

Toggled from the main context menu (**🐾 Desktop Companion**) or via
`CelStudioCerebrium.toggle_companion()`. `_ensure_companion()` builds it lazily and
is fully guarded, so Cellium still starts if the avatar data is missing.
`companion_react()` is called from `on_done()`, so the pet reacts to every finished
reply. `CompanionStage.respond_to()` infers a mood from the reply text via a small
keyword heuristic; pass your own `detector=` to override it.

## Important Invariants

1. **Cross-thread updates**: `QTimer.singleShot` is banned inside worker threads.
   Custom Qt signals must be used, with matching C++ type signatures.
2. **Circular imports**: `ui/` → `services/` → `core/`. Files in `core/` must **not**
   import each other at top level. All globals live in `core.config`.
   `core/` is also **Qt-free** - `jobs.py` and `safe_logging.py` deliberately use
   plain callbacks rather than Qt signals so they stay headless-testable.
3. **Assets & sounds**: `cellium/core/assets` and `cellium/core/sounds`. The 10
   `cerebrium_*.wav` UI sounds are bundled there - do **not** reintroduce a
   hardcoded external path.
4. **Never hardcode `/home/<user>/`.** Use `PROJECTS_DIR`, `KOKORO_DIR`,
   `OFFICIAL_WALLPAPERS_DIR`, `VENV_DIR`, `ASSETS_DIR`, `SOUNDS_DIR` from
   `config.py`, or the matching env vars (`CELSTUDIO_PROJECTS_DIR`,
   `KOKORO_MODELS_DIR`, `CELSTUDIO_WALLPAPER_DIR`, `CELSTUDIO_VENV_DIR`).
5. **Never hardcode secrets.** `cerebrium_settings.json` holds real API keys and is
   gitignored. GitHub access reads `CELSTUDIO_GITHUB_TOKEN` from the environment.
   Log through `core.safe_logging` so credentials are masked.
6. **Shell commands are gated, not blocked.** `ShellExecTool` returns a
   confirmation request for dangerous commands; the agent must re-issue the same
   call with `confirmed=True` only after the user approves. The guard **fails open**.
7. **PySide6 only**, never PyQt6 (LGPL).

## Background work

Long tasks go through `core.jobs.ProcessPool`, not the UI thread:

```python
from cellium.core.jobs import get_pool, current_job

def my_task(n):
    for i in range(n):
        job = current_job()
        if not job.checkpoint():        # False once cancelled or paused
            return "cancelled"
        job.set_progress(i / n, f"step {i}")
    return "done"

get_pool().submit("My task", my_task, 100)
```

`checkpoint()` blocks while paused, so a paused job costs no CPU.

## Avatar subsystem

> ### ⚠️ The face is a DOT MATRIX, never a polyline
> The archive's `Cerebellium.py:853` blits **one small filled square per data
> point** (`self.size = random.randint(5, 9)`, line 678). It does *not* join
> points into paths. Getting this wrong is what made the faces look like
> scribbles with pink blobs, and **every regression check still passed**  - 
> the tests only asserted "did not raise", never "does it look right".
>
> Concretely, from the real data:
> - `eyelid` on *Happy* is **ten samples of one arc** (`x` steps of 10, `y` the
>   curve height). Connecting them in file order is a zigzag.
> - `blush` / `perm_blush` is **literally a filled grid**  - 
>   `range(150, 210, 20) × range(270, 290, 10)` (see `Cerebellium.py:872`) - so
>   the two cheeks must be drawn as separate dot clusters, never as one blob.
> - Blink is **not** a squash: eyelid dots slide **down** by the per-side
>   `depth` and fade as they pass the eye (`Cerebellium.py:814, 832`).
>
> `widget.py` reproduces this, using a `zlib.crc32` hash of
> (expression, kind, side, index, x, y) for dot size and tint - the archive's
> per-process `random` made faces shimmer on every repaint.

```python
from cellium.ui.avatar import AvatarLibrary, AvatarView

lib = AvatarLibrary()                      # loads Anim/<Gender>/*.json
lib.matrix_report("Female")               # coverage of the base x modifier grid
lib.complete_matrix(write=False)          # generate the missing style variants

view = AvatarView(expression=lib.get("Female", "Happy"))
view.blink_now()
```

- Points are `[x, y, kind, left]`; 12 kinds (`eyelid`, `eyebrow`, `icon`, `stem`,
  `bottom_bar`, `mid_bar`, `exclamation`, `blush`, `perm_blush`, `tear`,
  `cartoon_sweat`, `dust`).
- Validation mirrors the archived Opus rules exactly (bounds `-500..1100` × `-500..900`,
  kind `[A-Za-z_]{1,32}`, 1–2048 points), so anything that loaded there loads here.
- 76 base expressions × 9 style modifiers = a 684-variant grid per gender.
  The 728 recovered expressions cover only 32 bases' variants; `complete_matrix()`
  fills the rest procedurally, giving 760 files per gender.

## Known Rough Edges

- `main_window.py` (~3,700 lines) and `chat/bubble.py` (~2,730) are far over the
  500-line soft limit in `DECISIONS.md`. Next refactor targets.
- The Tier-1 widgets (`command_palette`, `focus_clock`, `particles`) are still
  **built and tested but not wired into `main_window.py`** - additive and safe to
  attach. The avatar studio *is* wired now.
- `cerebrium_presets.json` / `cerebrium_memory_presets.json` are read from two
  locations; `_delete_mem_preset` mirrors writes to both.
- **Never let a test call anything that persists.** `set_zoom()` and
  `save_preferences()` write the *entire* settings dict, so a test that tweaks one
  key silently rewrites the others. `tools/regression.py` therefore stubs
  `main_window.save_json` in `_main_window()`; do the same in any new check.
- `tools/regression.py` has screenshot drivers for the new pages: pass
  `--auto-screenshot <path>` plus `--avatar`, `--analytics`, `--settings`,
  `--hub`, or `--chat-sample` (see `core/utils.py:main`).