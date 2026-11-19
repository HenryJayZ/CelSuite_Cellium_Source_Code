# 💜 Cellium for Android

Native Kotlin port of [Cellium](https://github.com/HenryCarm) - the PySide6 desktop
chat + agent + companion app - rebuilt as a real Android voice assistant.

**Architecture** (see `input/READ ME PackagingVoice.md`): Cellium is a zero-latency
local acoustic gatekeeper. OpenWakeWord spots *"okay cel"* → Whisper STT → Gemini
pass-through → TTS playback. On Android 12+ the listener lives in a
`VoiceInteractionService` sandbox (set Cellium as **Default Digital Assistant**)
so there is no persistent mic dot.

| Dir | What |
|---|---|
| `input/` | Sanitized Python reference (package + tools + docs). Secrets, logs, `_legacy/`, avatar bulk data excluded. 4 sample expressions ship under `input/cellium/ui/avatar/Anim/`. |
| `output/android/` | The native app (`com.henny.cellium`). Builds to APK in CI. |
| `output/kotlin/` | Converted Kotlin modules, mirrored from the app tree. |
| `agent/run_shift.py` | The night-shift goblin: converts `input/*.py` → Kotlin file-by-file, rebuilds, drops `release/cellium-drop.zip`. |
| `storage/state.json` | Shift progress (committed every shift). |
| `release/` | Local drop zips (gitignored; real drops ship as Actions artifacts). |

**Versioning:** `YYM.DD.V` - e.g. `267.07.1` = 2026-10-07, build 1.

**Secrets needed for cloud shifts** (never committed; set as Actions secrets):
`CELL_PAT`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `OPENCODE_MODEL`, `GEMINI_API_KEY`.
