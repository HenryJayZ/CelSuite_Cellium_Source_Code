# Cellium Refactor Map
**Status**: COMPLETE through Phase 10 (2026-10-02). Updated 2026-10-13.

Source monoliths: `_legacy/CelStudio_Cerebrium.py` (~9,700 lines, PySide6 app) and the archived `Cerebellium Opus.py` base85 avatar payload (728 expressions, SHA256-verified). Both fully ported. `compileall` clean, 38 modules import, `tools/regression.py` 41/41 green.

> **Corrections vs the old DRAFT (Phase 1/2) map.** The old map listed classes that never existed and locations that were wrong. Fixed here to match code (verified 2026-10-13 via grep):
> - ❌ `TranslucentOverlay -> chat/glass.py` - never existed. `chat/glass.py` holds only `GlassPanel` (:57), `GlassToast` (:154), `ChatInputEdit` (:186).
> - ❌ `SwitchControl -> widgets/toggle.py` - never existed. `toggle.py` is intentionally empty (`__all__ = []`); toggles are plain `QCheckBox`/`QToolButton` in `settings/dialog.py`. Kept because 3 modules star-import it.
> - ❌ `EmojiPickerWidgetNew -> widgets/emoji.py` - wrong. `widgets/emoji.py` holds only `AnimatedFaceOrb`. Real `EmojiPickerWidget` lives in `settings/dialog.py:162`.
> - ❌ `ModelManagerWidgetNew -> settings/models.py` - wrong. `settings/models.py` is a re-export hub only (re-exports `toggle` + `glass`). Real `ModelManagerWidget` is in `settings/dialog.py:694`, with alias `ModelManagerWidgetNew = ModelManagerWidget` in the same file.
> - ⚠️ `MessageBubbleNew -> chat/bubble.py` - incomplete. File also holds primary `MessageBubble` (:55) + 11 card widgets (see below).

## Core (`cellium/core/`) - headless, Qt-free, no top-level cross-imports

| Symbol | File | Notes |
|---|---|---|
| `load_json` / `save_json` | `config.py:535,542` | All global state, path resolvers (`PROJECTS_DIR`, `KOKORO_DIR`, `OFFICIAL_WALLPAPERS_DIR`, `VENV_DIR`, `ASSETS_DIR`, `SOUNDS_DIR`), palettes, voice tables live here |
| `dev_log` | `logger.py:77` | Central dev logger |
| `AgentTool` (base) | `tools.py:63` | - |
| `FileReadTool` | `tools.py:74` | Old map listed only this + `ShellExecTool`; full set below |
| `ReplaceFileContentTool` | `tools.py:118` | Missing from old map |
| `GrepSearchTool` | `tools.py:159` | Missing from old map |
| `FileWriteTool` | `tools.py:210` | Missing from old map |
| `FileListTool` | `tools.py:231` | Missing from old map |
| `CodeExecTool` | `tools.py:259` | Missing from old map |
| `WebSearchTool` | `tools.py:298` | Missing from old map |
| `ShellExecTool` + `build_unified_diff` | `tools.py:335,43` | Gated by `command_guard.py`; warns, never blocks; fails open |
| `CommandFinding`, guard tables | `command_guard.py:32` | 16/16 dangerous caught, 24/24 safe unflagged |
| `JobState`, `ManagedJob`, `ProcessPool`, `current_job()` | `jobs.py:45,63,206` | Background work; `checkpoint()` blocks while paused |
| `redact_text`, `redact`, `redact_mapping`, `RedactingFormatter` | `safe_logging.py:87,120,135,167` | 19/19 credential shapes redacted |
| Helpers, provider defs, JSON paths | `utils.py` | `core/utils.py:main` hosts `--auto-screenshot` drivers (`--avatar`, `--analytics`, `--settings`, `--hub`, `--chat-sample`) |

## Services (`cellium/services/`) - QThread workers, import `core/`, never `ui/`

| Symbol | File |
|---|---|
| `GenerationSignals`, `AIRenameSignals`, `AIRenameWorker`, `GenerationWorker`, `ModelPingWorker`, `ModelFetchWorker`, `ModelDetailWorker`, `AgentSignals`, `AgentWorker` | `ai_workers.py:260,268,272,345,757,812,906,1027,1037` (old map missed `AIRename*` + `ModelDetailWorker`) |
| Offline GGUF management (`get_or_load_llama`) | `ai_llama.py` |
| `STTSignals`, `STTWorker`, `AudioRecordSignals`, `AudioRecordWorker` | `audio_stt.py:120,128,293,302` |
| `StreamPlayer`, `KokoroStreamingWorker`, `EdgeTTSStreamingWorker` | `audio_tts.py:69,145,246` |
| `play_ui_sound`, `play_animalese_chirp`, pygame engine | `sound_engine.py` |
| `WakeListener`, `_OWWStreamThread` | `wake.py:86,467` (entirely missing from old map) |
| Noise gate / VAD | `noise_gate.py` (missing from old map) |

## UI (`cellium/ui/`) - PySide6 only (never PyQt6), may import `services/` + `core/`

### `main_window.py`
`_WakeRingOverlay` (:95), `ChatScrollArea` (:185), `CelStudioCerebrium(QMainWindow)` (:203, ~3,700 lines). Sixth page `central_stack[5]` = Avatar Studio (`open_avatar_view()`); 🐾 Desktop Companion via `_ensure_companion()` / `companion_react()` from `on_done()`; `RENDER_CHUNK_SIZE = 8` chunked bubble render; `WallpaperWidget.frost_pixmap()` + `_paint_backdrop()` (never `QWidget.render()` - recursion core-dumps); `_record_analytics()`, `nav_new_chat()`, `_propagate_font_to_bubbles` → `set_font_scale()`.

### `chat/`
- `glass.py` - `GlassPanel`, `GlassToast`, `ChatInputEdit` only (no `TranslucentOverlay`).
- `bubble.py` - `MessageBubble` (:55, primary), `MessageBubbleNew` (:2073), plus `STTChoiceCard`, `ChatBubbleBody`, `SlideToRetry`, `CodeBlockCard`, `ThoughtAccordionCard`, `CodeBlockResizer`, `AntigravityAgentWorkflow`, `EditDiffCard`, `ActivityLine`, `AgentToolCard`, `ThinkingCard` (~2,730 lines).
- `typewriter.py` - `TypewriterEdit` (:30), `TypewriterController` (:144). Missing from old map.
- `timeline.py` - `ChatTimelineHost` (:22). Missing from old map.

### `settings/`
- `dialog.py` - `EmojiPickerWidget` (:162), `ModelManagerWidget` (:694), `SettingsWidget` (:1674), `SettingsWidgetNew` (:3780, subclass alias), `AnalyticsBars`, `AnalyticsWidget`, `DevNotesWidget`.
- `models.py` - re-export hub only (see corrections above).

### `widgets/`
- `wallpaper.py` - `WallpaperWidget` (:53).
- `emoji.py` - `AnimatedFaceOrb` only.
- `toggle.py` - intentionally empty (see corrections).
- `command_palette.py` - `Command`, `CommandRegistry`, `CommandPaletteDialog` (:67,80,138). Tier-1, built+tested, not yet wired into `main_window.py`.
- `focus_clock.py` - `FocusSettings`, `FocusClock` (:24,34). Same Tier-1 status.
- `particles.py` - `Particle`, `ParticleCanvas` (:28,56). Same Tier-1 status.

### `avatar/` - the Cerebellium companion (all missing from old map)
`schema.py` (`AvatarError`, `AvatarPoint`, `AvatarExpression`), `variants.py` (9 style-modifier transforms), `library.py` (`AvatarLibrary`, `matrix_report`, `complete_matrix`, incremental `files/add_file/load_gender`), `widget.py` (`AvatarView` dot-matrix renderer, `_Dot`), `pet.py` (`SpeechBubble`, `ScreenshotBubble`, `PetGrip`, `PetControlBar`, `FloatingPetWindow`, `CompanionStage` + `MOODS`), `studio.py` (`AvatarStage`, `AvatarStudioWidget`, `VariantCuratorDialog`), `Anim/<Gender>/*.json` - 1,520 files (760/gender, 14 MB; 76 bases × 9 modifiers + completions). Face is a DOT MATRIX (one filled square per point, `zlib.crc32` size/tint hash) - never polylines; blink slides eyelid dots down by `depth`.

### `live/` - hands-free / call UI (all missing from old map)
`transcript.py` (`LiveBubble`, `LiveTranscript`, `LiveHistoryPanel`), `live_mode.py` (`LiveState`, `LiveCaptions`, `LiveStage`, `LiveModeController`, …), `audio.py` (`LiveAudio`), `controls.py` (`CircularChoice`, `RoundActionButton`, `LiveControlBar`, …), `calibration.py` (`WakeCalibrationDialog`, `NoiseCalibrationDialog`, `HeyCelWizardDialog`), `call_transition.py` (`CallTransition`), `talk_animation.py` (`TalkEnvelope`).

## Data / assets (not code, not in old map)
- `cellium/core/assets/` + `cellium/core/sounds/` - 90 tracked asset/sound files incl. 10 `cerebrium_*.wav`; never hardcode external paths.
- `cellium/core/cerebrium_*.json` - presets/sessions/analytics; `cerebrium_settings.json` holds live keys (gitignored, never bundle/share).
- `tools/regression.py` - 41 checks (security, redaction, jobs, avatar, companion, analytics, navigation, glass, zoom, scroll-wheel, chat-switch perf, persona presets, portability, Tier-1). Run `QT_QPA_PLATFORM=offscreen /home/henry/Documents/Projects/Python/venv/bin/python tools/regression.py`.

## Known rough edges
- `main_window.py` (~3,700) and `chat/bubble.py` (~2,730) far over the 500-line soft limit in `DECISIONS.md`. Next refactor targets.
- Tier-1 widgets (`command_palette`, `focus_clock`, `particles`) built+tested but not wired into `main_window.py`. Avatar Studio *is* wired.
- Never let a test call anything that persists (`set_zoom`/`save_preferences` rewrite whole settings dict - stub `main_window.save_json` in checks).
