# 💜 Cellium Android - Agent Handoff Brief

**Read this first. Everything you need to take over is here.**

## 1. Mission

Build the most perfect Android version of the **Cellium PC app** (PySide6 desktop:
chat + AI agents + Kokoro/Edge TTS + Whisper STT + openWakeWord *"okay cel"* +
live voice mode + 1,520-expression avatar companion + 7 personas). Not a demo.
The real thing, on Henny's phone.

## 2. Current state (verified, not assumed)

Repo: `HenryCarm/Cellium` (public, branch `main`). Local: `~/Cellium/`.

- **Skeleton APK `v267.07.1` BUILT offline, installed on Henny's phone
  (`10.134.183.218:5555`), full flow screenshot-verified**: Splash → Terms →
  Permission-gate (800 ms polling watcher, auto-advances) → Main (7 personas,
  Ask Cel via Gemini, mic-energy listener, set-as-assistant intent).
  Two real bugs found and fixed this way (missing guava runtime → crash;
  Groovy-vs-KTS syntax). **Always verify on-device with screenshots + logcat,
  never trust green builds alone.**
- **Cloud loop green**: `.github/workflows/cellium.yml` (6 h cron + chained
  dispatch) ran SUCCESS; `cellium-drop.zip` artifact contains cloud-built APK +
  state + screenshots. Currently build-only (no LLM secrets yet).
- `input/` = sanitized Python reference (52 files, secrets/logs/`_legacy`/
  avatar bulk excluded, 4 sample expressions kept). Secret scan clean.
- Local APK: `~/Cellium/release/Cellium_v267.07.1.apk`.

## 3. The strategic decision (research done 2026-10-07 - read before coding)

Henny heard "only the GUI gets rebuilt" - that is **one of three real options**:

| # | Path | What it means | Sources |
|---|------|---------------|---------|
| **A** | **`pyside6-android-deploy` (official Qt tool, 6.5+)** - ship the ACTUAL Python Cellium as an APK via python-for-android + buildozer. Same code, same avatar, same everything. Entry must be `main.py`, configured by `pysidedeploy.spec`. | [Qt blog](https://www.qt.io/blog/taking-qt-for-python-to-android) · [official docs](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-android-deploy.html) · [community guide](https://github.com/EchterAlsFake/PySide6-to-Android) · [buildozer hello-world (PySide 6.9.1, JDK 17, arm64)](https://github.com/meowmeowahr/pyside6_android_helloworld) |
| B | **Native Kotlin rewrite** (current skeleton) - rebuild GUI in Jetpack Views/Compose, port logic file-by-file. Best long-term UX, most work. Precedent: X rebuilt Android ground-up in Kotlin+Compose (2026). | `output/android/` skeleton + `agent/run_shift.py` converter |
| C | **Hybrid** - embed Python via Chaquopy/PyBridge (JNI) or local REST server, native Kotlin UI on top. | [PyBridge](https://github.com/joaoventura/pybridge) · [python+kotlin REST consensus](https://stackoverflow.com/questions/73936027/python-back-end-and-kotlin-front-end-for-android) |

**Recommended first task: feasibility SPIKE on Option A.** Audit every package in
`input/requirements.txt` against python-for-android recipes, in this order of
suspicion: `pywhispercpp` (needs C++ whisper build), `onnxruntime` + `kokoro`
(ML runtime on ARM), `pygame`/`sounddevice` (audio), then the safe ones
(`numpy`, `requests`, `openai`, `mistune`, `emoji`, `edge-tts`, `openwakeword`).
- If the whole stack has recipes (or wheels): **go A** - write `pysidedeploy.spec`,
  build with buildozer in cloud CI, and the "perfect version" is done in days.
- If 1–2 deps are unbuildable: **go C** - replace just those (e.g. server-side
  STT/TTS) and keep the rest.
- If the native stack is hopeless: **continue B** - the skeleton, converter,
  and 6 h shift loop are already wired; work through `input/cellium/` module by
  module (config → core → services → avatar → live mode last, it's the hardest).

## 4. Repo map

```
input/                  sanitized Python reference + docs (READ ME PackagingVoice.md = voice architecture)
output/android/         native app, com.henny.cellium (skeleton; minSdk 24, target/compile 34)
output/kotlin/          converted modules mirror
agent/run_shift.py      night-shift converter (opencode run -m $OPENCODE_MODEL; build-only without keys)
.github/workflows/     cellium.yml - needs CELL_PAT + TELEGRAM_* + OPENCODE_MODEL + GEMINI_API_KEY secrets
storage/state.json      shift progress (committed each run)
release/                local APKs (gitignored; drops ship as Actions artifacts)
```

Key specs: `input/CELAS_LIVE_MODE_SPEC.md` (live mode), `input/AGENTS.md`
(avatar dot-matrix warning - faces are DOT CLUSTERS, never polylines),
`input/READ ME PackagingVoice.md` (VoiceInteractionService + Gemini pass-through).

## 5. Build (offline kit - never download tooling)

```bash
source /home/henry/Documents/Projects/Kotlin/env.sh   # JDK 21 + SDK + gradle-home
cd ~/Cellium/output/android
gradle :app:assembleDebug --offline --no-daemon --console=plain
adb -s 10.134.183.218:5555 install -r app/build/outputs/apk/debug/app-debug.apk
```

- `local.properties` (gitignored) must say
  `sdk.dir=/home/henry/Documents/Projects/Kotlin/android-sdk`.
- `app/build.gradle.kts` pins versions to exactly what the kit cache holds
  (AGP 8.5.0, KGP 2.0.0, core 1.13.1, lifecycle 2.8.4, activity 1.9.0, guava
  android 32.1.3…). If you add a dep, run once ONLINE, then offline forever.
- Full kit rules: `/home/henry/Documents/Projects/OpenCode/kotlin.md`;
  patterns: `.../kotlin_android_patterns.md`
  (Splash→Terms→Permission→Dashboard, 800 ms watcher, foreground service,
  version format **`YYM.DD.V`**, e.g. `267.07.1`).

## 6. Guardrails

- **Secrets**: never commit keys/sessions/logs. `.gitignore` already covers
  `cerebrium_*.json`, `*.log`, `*.apk`, `release/`, `local.properties`.
  Never print secret values; check with redaction, not `cat`.
- **PySide6 only, never PyQt6** (LGPL). **Nuitka, never PyInstaller** (PC side).
- Central venv for Python: `/home/henry/Documents/Projects/Python/venv/bin/python`.
- Keep files ~under 500 lines (`main_window.py`/`bubble.py` are the bad example).
- Verify like Henny's metered line depends on it: batch tool calls, compile +
  install + screenshot + logcat every slice. **A green suite is necessary and
  not sufficient - run it and LOOK at it.**

## 7. Secrets the human must supply (you cannot create these)

`CELL_PAT` (classic PAT: `repo`+`workflow`), `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `OPENCODE_MODEL`, `GEMINI_API_KEY` (or matching provider
key). Set via `gh secret set NAME --repo HenryCarm/Cellium`. Without them,
shifts stay build-only.

## 8. Definition of done

Parity checklist against the PC app: chat + sessions, all providers, STT/TTS,
wake word, live mode with mouth movement + barge-in, avatar studio +
companion, personas, settings. `tools/regression.py` philosophy ported:
every feature proven by on-device effect, not by "did not crash".
