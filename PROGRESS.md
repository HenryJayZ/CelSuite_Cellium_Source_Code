# Cellium Progress

## Phase 1-6: Monolith → Modular Package (2026-09-21) ✅

Refactored the ~9,700-line `CelStudio_Cerebrium.py` into the `ui → services → core`
package. `compileall` passed; headless `--auto-screenshot` boot exited 0.

## Phase 7: Security & Portability Hardening (2026-10-02) ✅

- **Git initialised** with a `.gitignore` excluding real secrets
  (`cerebrium_settings.json` holds live API keys under `user_custom_keys`;
  `cerebrium_sessions.json` is private chat history). 90 asset/sound files stay
  tracked so a fresh clone still runs. **Still not committed - Henny's call.**
- **Removed a leaked GitHub PAT** from `core/utils.py` and `_legacy/`. It was
  base64-split across six string literals to evade grep and had **zero consumers**.
  Now reads `CELSTUDIO_GITHUB_TOKEN` from the environment.
- **Fixed 10 silently broken UI sounds.** `LEGACY_DIR` pointed at a folder that had
  moved into `Archived/`. All `cerebrium_*.wav` are now bundled in
  `cellium/core/sounds/`.
- **Eliminated hardcoded `/home/henry/` paths** via portable, env-overridable
  resolvers in `config.py`.
- **Rebuilt `requirements.txt`** from a real import audit: added `requests`,
  `pygame`, `onnxruntime`, `pywhispercpp`, `openai`, `soundfile`; dropped
  `openai-whisper`, which was never imported and pulls in PyTorch for nothing.
- **Corrected documentation drift** in `AGENTS.md`.
- Wrote `ARCHIVE_AUDIT.md` - full lineage and feature-gap analysis of the archives.

## Phase 8: Feature Port + Avatar Recovery (2026-10-02) ✅

### Security
- `core/command_guard.py` + `ShellExecTool` gate: **16/16 dangerous commands caught,
  24/24 safe commands unflagged**, warns and asks instead of blocking, and **fails open**.
- `core/safe_logging.py`: **19/19 credential shapes redacted** (all 11 of Henny's
  providers plus GitHub/OpenAI/Anthropic/AWS/Slack/Stripe/HF/JWT/base64-obfuscated),
  13/13 realistic log lines untouched, idempotent.

### Tier 1 features (all built, all tested offscreen)
- `core/jobs.py` - `ManagedJob` / `ProcessPool` / `current_job()`. Verified
  completion, error + traceback capture, cooperative cancel, and pause halting the
  loop (0 ticks during a 300 ms pause).
- `ui/widgets/command_palette.py` - `CommandRegistry` with fuzzy subsequence
  matching, `CommandPaletteDialog`, Ctrl+K binding.
- `ui/widgets/focus_clock.py` - work / short-break / long-break phases, round
  tracking, signals, painted.
- `ui/widgets/particles.py` - ambient particle field, count/opacity controls,
  re-wraps on resize.
- `ui/chat/typewriter.py` - per-glyph streaming reveal with an audio ticker hook.

### Avatar recovery - the Cerebellium companion
- **728 expressions recovered** from the archived `Cerebellium Opus.py` base85
  payload (SHA256-verified): 364 Female + 364 Male, exported as loose JSON.
- Discovered the library is a regular matrix: **76 base expressions × 9 style
  modifiers**, of which only 32 bases had all variants.
- `ui/avatar/` - `schema.py` (validation mirroring Opus exactly), `variants.py`
  (9 geometric modifier transforms), `library.py`, `widget.py` (Qt renderer for all
  12 primitives, per-eye blinking).
- **All 364 Female + 364 Male expressions render, 0 failures**, with every one of
  the 12 primitives exercised.
- `complete_matrix()` filled the gap: **76/76 bases now carry all 9 variants,
  1,520 expressions on disk (760 per gender, 14 MB)** - far beyond the 111+222 target.

### Verification
`compileall` clean · **38 modules import, 0 failures** · guard still gates
`rm -rf /` · 2,425 new lines of code.

## Phase 9: The Dream Made Real (2026-10-02) ✅

### Desktop companion - both dreams in one app
- `ui/avatar/pet.py` - `CompanionStage`, `FloatingPetWindow`, `PetGrip`, `SpeechBubble`.
  Frameless, translucent, always-on-top, draggable, with a speech bubble.
- **Wired into the real app**: **🐾 Desktop Companion** in the main context menu,
  and `companion_react()` fires from `on_done()` so the pet reacts to every
  finished reply. Verified against a live `CelStudioCerebrium` instance.
- 19 mood mappings, all resolving to real expressions for both genders;
  keyword-based reply sentiment inference scored **7/7** on a test set.
- Idle rotation across 76 base expressions; gender swap; a "wave" nudge.

### Regression harness
- `tools/regression.py` - **29 checks, all passing**: security (6), redaction (3),
  jobs (4), avatar (4), companion (2), portability (3), Tier 1 (5).
- Tag-filterable, headless, ~20 s. Non-execution of flagged shell commands is
  proven by side effect rather than string matching.

### Archive tidy
- Trashed 2 byte-identical duplicates (436 KB) to
  `OpenCode/tmp/Trash/archive_dedup_2610.02.1/`.
- Filed 22 tkinter-era files and the 3 PyQt6 files into
  `Archived/Cerebras AI/PRE-PYSIDE6 (do not port from here)/` so the GPL-bound
  toolkits cannot become an accidental port source.

## Verification
`compileall` clean · 36 modules import with 0 failures · **regression suite 29/29** ·
2,425 lines of new code · 1,520 avatar expressions on disk.

## Phase 10: The Avatar Page & The Bug List (2026-10-02) ✅

### #12 - Avatar Studio (the headline gap, now closed)
`ui/avatar/studio.py` - `AvatarStudioWidget`, wired as the sixth page
(`central_stack[5]`, `open_avatar_view()`, new **Avatar Studio** sidebar button
with an `avatar.svg` icon). Gradient stage with a breathing glow, live
`AvatarView` preview, gender switch, instant search across 760 expressions,
**`Base` + 9 style-modifier chips**, prev/auto-play/next, blink, scale slider,
clipboard JSON export, desktop-companion toggle + "send this face to the
companion", and a matrix-coverage readout. Back button returns to chat; the
page talks to the rest of the app only through three signals, so it stays
usable standalone in tests.

Library loading is **incremental** - new `AvatarLibrary.files/add_file/load_gender`
pump 14 MB of JSON through a QTimer in batches behind a real progress bar
instead of freezing for a second.

### Six more bugs closed
| # | Bug | Root cause | Fix |
|---|---|---|---|
| **#2** | Sidebar "New Chat" did nothing on other pages | `new_session()` ran but never left the current page | New `nav_new_chat()` switches to chat first |
| **#3** | `glass_blur` saved but never read | `GlassPanel` had no blur concept at all | `WallpaperWidget.frost_pixmap()` + `GlassPanel.set_blur()`; frost and fill alpha now trade off. Settings slider previews live |
| **#8** | "Disable scrollwheel" guarded only combos, lived in Network & API | One checkbox, wrong target, wrong tab | **Two** checkboxes in **Appearance**: lock combos (default on), block chat scrolling (default off). Handled in `eventFilter` |
| **#4** | Zoom never reached message text | Bubble bodies bake `font-size` into **inline HTML**, which beats any stylesheet - and `set_font_scale()` had **zero callers** | `_propagate_font_to_bubbles` now calls `set_font_scale()` |
| **#1** | Chat switching froze **784 ms** | 40 bubbles rendered in one blocking pass | `RENDER_CHUNK_SIZE = 8`, drained from a zero-delay QTimer |
| **#11** | Analytics page empty; `F_ANALYTICS` never written | Nothing recorded anything | `_record_analytics()` logs every turn (tokens/latency/model/chars) to `cerebrium_analytics.json`; page rebuilt with 4 KPI tiles, a 14-day token chart and a per-model split |
| **#9** | Persona/memory presets unnameable | Saving always reused the selected entry, or literal `"Custom Persona"` | `_prompt_preset_name()` asks via `QInputDialog`, never collides |

### Three more wiring failures - the pattern held
`set_font_scale()` was fully written and **never called**. `glass_blur` was
persisted and **never read**. `F_ANALYTICS` was loaded and **never written**.
Same disease as #6 and #7. Only running the app found them.

### Two real bugs the screenshots caught
- `frost_pixmap` used `QWidget.render()`, which paints children - and the glass
  panels *are* children of the wallpaper, so every panel asked for a snapshot
  that painted it again. **Unbounded recursion → core dump.** Split out
  `WallpaperWidget._paint_backdrop()`.
- PySide6 has no `drawPixmap(QRect, QPixmap, int, int, int, int)` overload, so
  the frost threw on every single panel paint. Fixed to the `QRectF` form.

### Avatar renderer fixes (visible in the Studio)
- Eyelids and eyebrows were joined into **one** polyline across the whole face →
  now drawn per side, giving two distinct eyes.
- `blush`/`perm_blush` passed both cheeks into a single `_blob()` → one giant
  disc across the face → now grouped per side into two cheeks.
- `_blob()` applies the scale itself but callers pre-scaled, double-scaling the
  radius.

### Regression
**41 checks, 41 passing, exit 0.** The suite now stubs `main_window.save_json`  - 
`set_zoom()` writes the *whole* settings dict, and a zoom test had silently reset
the real `glass_blur` from 62 to 16. Restored, and the pollution is now prevented
at the source.

## Verification
`compileall` clean · **41/41 regression, exit 0** · 4 pages screenshotted offscreen
(avatar / analytics / settings / chat) · `cerebrium_settings.json` byte-identical
after a full run.

## Phase 11: ☁️ Cloud Model Cache - server-side models, zero local data (2026-11-03) ✅

### The problem
Phase 2's "cloud storage" toggle uploaded a `.safetensors` **already sitting on the
PC** - useless on a metered connection - and it left an 83-byte empty dataset
shell because `datasets/create/version` is **403** on this key.

### What exists now
- `cellium/services/model_cache.py` - deterministic cache slugs
  (`cellium-cache-<preset>`), a health probe via `/datasets/view` (`< 1 MB` =
  broken shell) and a **CPU-only** builder kernel (`enableGpu=False`, zero GPU
  quota) that downloads the checkpoint + LoRA **on Kaggle** and writes them into
  a private dataset through the one working write hop (`datasets/create/new`).
- Discovery runs on Settings open **and** before every generation
  (`_maybe_mount_cache`) - a healthy cache is mounted read-only, so the render
  skips the Civitai download entirely.
- Settings → 🖼️ Image Generation: one row per Civitai preset
  (`☁️ not cached` / `☁️ cached · 6.61 GB` / `⚠️ empty shell`) with
  **Cache now**, **↻ Re-cache**, **🗑 delete** and **🔄 Refresh cache status**.
- The three engines are now **Henny's Mini App lineup** (verified live on
  Civitai, 2026-11-03): ✨ DreamShaper XL Turbo v2 (public HF, 8 steps / CFG
  2.0) · 🎨 **Nova Cartoon XL** (version `2329740` = 6.94 GB Illustrious
  checkpoint + cartoony Illustrious LoRA `1524099`) · 📸 **Juggernaut XL
  Ragnarok** (version `1759168` = 7.11 GB, **no** LoRA - the Mini App keeps
  the cartoon LoRA off realism engines). Both Civitai engines run the Mini
  App's chef recipe: 33 steps / CFG 7.0.

### Live proof (2026-11-03)
- The builder kernel cached Juggernaut XL Ragnarok **server-side**:
  `cellium-cache-juggernaut-xl-ragnarok` = **7,105,350,162 B**, file
  `model.safetensors`, PC traffic = **JSON only**.
- The watcher then logged
  `model from mounted cache: /kaggle/input/datasets/henrycarm/cellium-cache-juggernaut-xl-ragnarok/model.safetensors`
  and rendered in **6–9 s** per image once warm.

### Bugs the live runs uncovered (all fixed)
| Bug | Fix |
|---|---|
| ntfy with `Content-Type: application/json` silently dropped the payload | plain-text body |
| the app publishes a job **batch**, the watcher read a single job | unwrap `msg["jobs"]` |
| jobs queued before the watcher subscribed were lost | republish pending jobs on the first heartbeat |
| ntfy replaces the body of an upload and stores multipart **verbatim** | metadata as its own message + raw body with a `Filename` header |
| Kaggle mounts datasets at `/kaggle/input/datasets/<owner>/<slug>/` | glob by slug under `/kaggle/input/**` |
| Kaggle renames kernels → status polls hit a phantom kernel | parse `ref` from the push response |
| a Civitai **model id** serves a different checkpoint | presets use **version ids**; the watcher resolves model ids → best SDXL version |
| probing `/api/v1/models/<versionId>` 404s (it only knows *model* ids) - a live Nova looked "deleted" when it was fine | probe the **download** endpoint and `/api/v1/model-versions/<id>`; only the LoRA id `627178` is truly gone |

## Verification
`compileall` clean · **112/112 regression, exit 0** (incl. the new Phase 5 case)
· live smoke: 3/3 images delivered as valid 512×512 JPEGs · live mounted-cache
render · live 7.1 GB server-side cache build.

## Next
- [ ] Hands-free voice control (`SpeechService` / `HandsFreeListener` - needs a mic)
- [ ] Agent plan pipeline (`AgentPlan` → `AgentResult`)
- [ ] First git commit (Henny's call)
- [ ] Split `main_window.py` (~3,700) and `chat/bubble.py` (2,730) under 500 lines
- [ ] Kotlin/Android rewrite of Cellium (the long dream)

## Backups

- `Cellium_backup_2610.02.1.tar.gz` - pre-hardening snapshot (1 MB). **Predates the
  token removal**, so it still contains the old GitHub PAT. Do not ship it.