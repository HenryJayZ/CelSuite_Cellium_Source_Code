# Changelog

All notable changes to **CelSuite - Cellium** will be documented in this file.

## [Unreleased] — Kaggle cloud image generation (BYOK) + companion orb polish

### 2026-11-12 — Provider out-of-budget (HTTP 402) errors now readable
- The reported "Mistral keys don't work (Generation Error)" traced to the
  provider's billing, not the app: `/models` returns HTTP 200 for that key, but
  every chat completion (`mistral-medium-3-5`, `mistral-large-latest`,
  `mistral-small-latest`, `codestral-latest`, ministrals, magistrals …) answers
  `HTTP 402 {"message": "Vibe budget exhausted.", "code": "2304"}`.
- `_friendly_generation_error()` maps 402 / "budget exhausted" / billing to a
  clear out-of-budget sentence instead of the old generic
  "Cel couldn't finish that reply".
- `on_error()` now treats 402 as quota-class (it triggers the auto-fallback
  model chain) and logs the raw provider reason as
  `[UI-WARN] Generation Error: <raw>` so future mystery errors can be grepped.

### 2026-11-03 - Bundled wallpaper is the source of truth
- The wallpaper engine no longer prefers
  `~/Documents/Projects/Python/.png/Cel Cellium Wallpaper.webp`; it now loads
  `cellium/core/assets/cel_wallpaper.webp` (falling back to the packaged
  `cellium/assets` copy, then the external file). Moving the project, freezing
  it with Nuitka, or deleting the loose `.png` folder no longer changes or
  breaks the app's background.
- Added a portability regression check that the resolved wallpaper exists and
  lives inside the `cellium/` package.

### 2026-11-03 - Imagine dialog: Simple/Advanced, sticky prompts & appending styles
- **Remembered prompt state**: the dialog restores the last prompt, sticky style
  tags, negative prompt, model preset, steps, guidance, resolution and batch
  count from settings every time it opens, and writes them back on
  Generate/close.
- **CelAS-style sticky prompt + appending presets**: the prompt is split into a
  main subject and a persistent *Sticky style* suffix appended to every render
  (including `/imagine` slash commands). The Quick Style presets (anime, retro
  cel, chibi, dark fantasy, cyberpunk, watercolour) **append** their tag block
  instead of replacing the sticky text, exactly like CelAS.
- **Simple / Advanced modes**: Simple shows just the prompt, sticky style,
  resolution and batch; Advanced reveals the Kaggle model engine, enhancer,
  negative prompt, steps, guidance and seed. The chosen mode is remembered.
- **Local safetensors upload removed**: Settings → Image Generation no longer
  offers "Cloud Storage" / "Upload model to dataset"; Cellium is online-Kaggle
  only. The server-side `cellium-cache-*` builder (built on Kaggle, mounted
  read-only) remains the only cache path.

### 2026-11-03 - "/" command menu rebuilt
- **No more overlap or clipping**: the drop-up positioned itself with the frame's
  stale pre-layout height, so it grew downwards over the input pill, while each
  row crammed `cmd - description` into one 280 px line that cut off mid-word. It
  now measures its exact size first, sits 10 px above the pill (flipping below
  when the screen is short), clamps inside the available screen, and paints
  two-line rows - a bold command plus an elided, muted description.
- **Commands execute on the first click**: picking `/imagine` opens the image
  dialog immediately; `/imagine-start-cache` and `/imagine-stop-cache` run their
  cache actions immediately. Enter on the highlighted row does the same, so no
  second send is needed.

### 2026-11-03 - Settings layout & profile-picture painter fixes
- **Settings tabs no longer clip**: the eight-tab `QTabBar` needed ~1370 px in an
  884 px pane, cutting *Persona & Memory*, *Local Models & Hardware* and *Logs*
  off behind scroll arrows. Replaced it with a wrapping pill rail
  (`_SettingsTabFlow`) so every label stays fully visible at any window width.
- **No more floating label windows**: `HF Repo ID:` / `HF Token…` were parentless
  `QLabel`s toggled with `setVisible(True)`, so Qt promoted them to tiny top-level
  windows whenever Settings opened (the Civitai labels repeated it on mode
  switch). Visibility now toggles the real input rows built by `_make_input_row`.
- **Avatar painter crash fixed**: `QBrush` was used but never imported in `pfp.py`;
  every avatar repaint raised `NameError`, left an active `QPainter` behind and
  spammed `QBackingStore::endPaint()`. Added the import and wrapped both painters
  in context managers so a future paint exception can never leak the painter.
- **Duplicate layout add removed**: `h_realistic` was added to `form_audio` twice,
  emitting `QLayout::addChildLayout: layout … already has a parent`.
- Ampersands in buttons, menus and tabs now render literally (`&&` instead of a
  swallowed mnemonic character).

### 2026-11-03 - Startup segfault at Kokoro preload (fixed)
- **Root cause**: `_preload_kokoro()` moved a parentless `PreloadWorker` into a
  `QThread` but kept it only in a local variable. The function returned, Python
  collected the worker, and Qt then emitted `started` to a dead receiver  - 
  `SIGSEGV` inside `PySide::SignalManager::qt_metacall` a few milliseconds after
  the wallpaper loaded. Both the worker and its thread are now held on `self`
  until `thread.finished`, then released.
- **Kokoro preload actually works now**: it read `self.parent().settings`, but a
  `QObject` moved to a thread cannot have a parent, so `parent()` was `None` and
  every preload failed with `'NoneType' object has no attribute 'settings'`.
  It also referenced `_KOKORO_SESSION_CACHE`, which `import *` never exports
  (leading underscore). The worker now receives the thread count up front and
  delegates to the public `get_kokoro()` helper.
- **CelMoji warmup worker hardened**: its signal was named `finished`, shadowing
  `QThread.finished()`; renamed to `tabsReady` and the worker is retained on the
  window. Removed a stray unreachable `except` block in `_on_celmoji_warmed`.

- **🎨 Image Generation (Kaggle BYOK)**: generate images on Kaggle's free GPU straight from chat.
  - New `cellium/services/kaggle_image.py` backend: pure `requests` to Kaggle's job API
    (push script → poll status → fetch outputs), `kernelType: "script"` so the GPU
    auto-tears-down, a 45-min session cap, and a local FIFO queue (one job per key).
  - Prompt/token/URL are embedded via `repr()` + `json.dumps` - injection-proof kernel scripts.
  - HuggingFace public-repo mode (default `lykon/dreamshaper-xl-v2-turbo`) **and**
    Civitai single-file mode, plus optional LoRA (URL + strength).
  - New **Settings → 🖼️ Image Generation** tab: Kaggle username + masked API key,
    one-click `kaggle.json` import, Test Connection, model source, LoRA, defaults
    (steps / size / CFG / negative prompt) and output folder.
  - **🎨 Imagine button** in the chat input pill + **`/imagine <prompt>`** chat command
    + Ctrl+K palette entry; results render inline in chat with the seed, and save to
    the gallery folder.
  - Friendly error mapping: 401, GPU quota, 429 backoff, timeout, cancelled.
  - **Model presets** (curated): ✨ DreamShaper XL Turbo (public HF), 🎨 Nova
    Cartoon XL, 📸 Juggernaut XL Ragnarok, 🔧 Custom - picked in the Imagine
    dialog or Settings. Civitai URLs auto-resolve (API first, direct-download
    fallback so no token is required for public models). The Civitai ids are
    **model-version ids**: a model id silently serves the page's latest file
    (a 151 MB different checkpoint), which used to break the Juggernaut preset.
    The two Civitai engines are now **exactly Henny's Mini App lineup**:
    Nova Cartoon XL (version `2329740`, 6.94 GB, Illustrious base) with the
    cartoony Illustrious LoRA `1524099`, and Juggernaut XL Ragnarok
    (version `1759168`, 7.11 GB) **without** a LoRA - the Mini App keeps the
    cartoon LoRA off realism engines. Both use the Mini App's chef recipe
    (33 steps / CFG 7.0). The Mini App's old LoRA id `627178` is genuinely
    deleted upstream, so its living Illustrious twin is used instead.
  - **Batch** (1–4 images per run, `out_NN.png` + seeds), **✨ Enhance** button
    (Mini-App-style quality-prefix/tag expansion), negative prompt, steps/CFG/
    size/seed - ported from the Colab Mini App, still one-click friendly.
  - **Progress lives in chat now**: tiny nameless system bubbles (no floating
    toasts), updated on every stage change and heart-beating every 33 s;
    errors render as a small red in-chat bubble with the kernel log tail.
  - **"/" slash drop-up** above the input lists commands (`/imagine`) with
    filter + ↑/↓/Enter keyboard nav.
  - **🤖 AI-callable image tool**: hamburger ⋯ menu → **🎨 Enable Image Gen**
    exposes a `generate_image` tool to the agent (OFF = tool never sent, so
    context stays small). The model can create a NEW image from text or
    **edit the last one** (`edit_last=true` → img2img, base64-embedded on the
    Kaggle GPU, e.g. "put a clown face on the cat"). Results land inline in
    chat via a shared Qt-signal hub; progress uses the same in-chat bubbles.
  - **Phase 2**: ✨ **Enhancer model** picker (Settings + Imagine dialog) - the
    ✨ Enhance button expands your idea via that dedicated LLM (one-shot call),
    falling back to local tag expansion. **Mega-batch up to 20** images with a
    "×N images" chat tracker. **☁️ Cloud storage** toggle: upload your
    .safetensors to a private Kaggle dataset with a real progress bar; kernels
    then mount it (`datasetDataSources` + load from `/kaggle/input/...`), cutting
    the ~2-min model download to ~5 s; turning it off deletes the dataset via API.
    **🔥 Warm-cache** `/imagine-start-cache` / `/imagine-stop-cache` commands +
    ⋯ menu toggle, with a loud quota warning and a hard 1 h `sessionTimeoutSeconds`
    cap so it can never burn the weekly quota unattended.
  - **Phase 3**: ✨ **Enhance button state machine** (working "Pinging <model>…"
    with cancel-on-click, rate-limit auto-retry ×3 with backoff, "↻ Retry" on
    failure - always re-enhances from the stored original prompt; local fallback
    is instant). **🔥 Warm-cache v2 mailbox**: watcher notebook re-downloads the
    latest `queue.json` via `GET /datasets/download` every 5 s (fresh HTTP, not
    the frozen mount), app polls `/kernels/output` for results, dead-cache
    auto-requeues via script path. 111/111 green.
  - Welcome page glow-up: centered halo orb + gradient headline + suggestion chips.
  - Kernel pins fixed for Kaggle's Python 3.13 (`diffusers>=0.34,<0.35`,
    `transformers>=4.41,<5`); kernel log tail surfaced on errors.
  - **LoRA is non-fatal** (skips cleanly if the download needs a token).
  - **Live smoke tests passed on real Kaggle GPU**: HF DreamShaper → red apple
    PNG; Civitai Nova Cartoon XL → anime PNG (both fetched with seed shown).
  - 8 new regression checks - **103/103 green**.
- **Image Gen button icon**: the pink input-pill button had been borrowing the
  Attach paperclip SVG. It now has a dedicated `ui_imagine.svg` - a white glass
  photo card with a landscape ridge, sun and a generation sparkle, tuned to stay
  crisp at the button's 20 px render size.
- **Welcome orb fixes**: the bubble is now dead-centre - the halo used a
  `QStackedLayout` whose layout-level alignment Qt ignores, parking the orb
  65 px left and up of the greeting. Devil-mode rage now *physically dashes*
  the orb to a far landing spot on the welcome page whenever the pointer gets
  close, hard-clamped fully on-screen, then glides it home when it cools off.
- **Welcome page glow-up**: gradient headline with glow, halo behind the orb,
  and GPT/Gemini-style suggestion chips (🎨 Generate an image, Debug, Explain,
  Write) wired into the input.
- **Welcome orb**: boots smiling, tracks the pointer window-wide, and spam-clicking
  triggers a demon-rage face (horns, slit pupils, fangs) that dodges the cursor
  inside its bounds before cooling off.
- **Recent Chats**: drawer opens below the top bar so its header no longer overlaps
  the window buttons.

## [Unreleased] - companion orb expressiveness + Recent Chats header
- **Welcome orb**: boots with a clear smile, tracks the pointer anywhere in the app window, and spam-clicking triggers a demon-rage face (horns, slit pupils, fangs, red body, pulsing 💢 vein) that dodges the cursor inside its widget bounds before cooling off.
- **Recent Chats**: the drawer now opens below the top bar, so its header no longer paints over the window buttons.
- **Regression**: the mood-contract check no longer depends on the developer's saved Coding Mode; all 95 checks green.

## [v2610.12.3] - 2026-10-13 - gray-button purge + empty state + proven send
- Programmatic buttons (studio chips/bases, permission rows, drawer delete) now use the themed pill style - no more default-gray anywhere.
- Chat shows a proper empty state; session list hides until there's content.
- Send path proven end-to-end: new `SendPathTest` gets a real AI reply through `ChatClient` over a live endpoint. 6 headless tests green.

## [v2610.12.2] - 2026-10-12 - 2026 visual overhaul + live models
- **Design system**: pill buttons (ALL-CAPS killed globally), tonal cards, rounded input bars, gradient primary, vector send/call/add/menu icons, transparent system bars + edge-to-edge, Material dynamic color on Android 12+, expressive transitions kept.
- **Main chat**: toolbar with avatar + live model/persona subtitle, circular send/call FABs, session drawer (switch, delete, long-press rename), chat bubbles with better type, **send failures now appear as inline red ERROR bubbles** (never silent again).
- **Model Hub**: "Test key & refresh models" pings the live `/models` endpoint per provider and caches the list; chat model picker prefers live IDs. **Gemini defaults fixed** (`gemini-flash-latest`, `gemini-3.8-flash`, `gemini-3.5-flash-lite`) - the old 1.5/2.0 IDs are dead and caused silent 404s.
- **Hub/Studio/Live/Setup** layouts rebuilt as cards + pill buttons; hub status uses theme colors.
- Headless launch tests now cover Main, Hub, Live, Setup + studio asset count.

## [v2610.12.1] - 2026-10-12 - launch-crash fix + real icon
- **Fixed instant crash on first launch** - with no provider keys saved, the model spinner's adapter was backed by an immutable `listOf(...)` and `onResume()` called `clear()` on it → `UnsupportedOperationException` before the first frame. Backing list is now mutable. Caught by the new headless `MainActivityLaunchTest` (Robolectric 4.15.1, JVM, no emulator needed: `gradle :app:testDebugUnitTest`).
- **Launcher icon is now the desktop `icon.webp`** feather-C art (adaptive foreground + per-density legacy mipmaps, placeholder vector removed).
- Headless options confirmed for this machine: Robolectric (works now), SDK emulator with `-no-accel` (slow software boot, no KVM needed); Redroid impossible here (no docker, no binder module).

## [v2610.12.0] - 2026-10-12 - Android native rebuild
**`Android/cellium-app/`** (PART 1 held no Kotlin source, so the app was rebuilt clean; `assembleDebug` + signed `assembleRelease` both green, SDK-verified manifest):
- Dot-matrix `AvatarCanvas` (dots-never-polylines, 60 fps spring easing, breathing, per-side blink slide, touch repel, mood pop), 152 base expressions bundled (1.4 MB), 9 modifiers computed at runtime, 24-mood map, studio with gender/search/chips/preview.
- Chat with streaming SSE across 8 providers (Gemini/Groq/DeepSeek/Cerebras/OpenRouter/Mistral/**Copilot**/Custom) + photo attach with vision parts, `<think>` cards, mood-line strip, 7 personas, sessions on disk.
- Live call: face owns a centered full-weight stage (the off-center bug), capped transcript, VU meter hidden under the noise floor, barge-in, clean mic release on hangup.
- Permissions console incl. **working default-assistant** (real `VoiceInteractionService` + session + recognition stub + `interaction_service.xml` - the old intent-only row could never list us) and **fork-proof Shizuku** (own provider authority + manager discovery by ID list + name heuristic + v11 permission flow + `UserService` priv shell; `newProcess` avoided per API-14 removal).
- Floating pet overlay, companion/reply notifications, encrypted key store with fallback, Gemini-style transitions + staggered chat entrance + mood pop.
- Drops: `Android/release/HenryJayZ.CelSuite.Cellium-v2610.12.0.apk` (release-signed) + `-debug.apk`.
- Carried: on-device run-through (no device here), neural wake-word (`.onnx` present, needs onnxruntime port), release keystore lives at `/opt/cellium.jks` + props (ephemeral - back up before VM recycle or updates can't be signed).

## [Unreleased] - 2026-10-12 - deep audit sweep (ruff + threading + GGUF)

### Fixed (found by systematic audit)
- **Image-URL previews stuck on "Loading…" forever** - the loader thread posted `QTimer.singleShot` into a thread with no event loop (never fires) and the error lambda read a dead `except ... as e` (NameError). Delivery is now a queued Signal; decoding happens as thread-safe `QImage` off-thread, `QPixmap` conversion in the GUI slot.
- **Segfault hardening (prime suspect: `QThread.terminate()` inside llama.cpp)** - new `_stop_worker_gracefully`: staged 2 s + 3 s + 5 s cooperative waits at all 3 Generation/Agent respawn sites; `terminate()` only as a last resort.
- **GGUF load/unload race** - module lock serializes `get_or_load_llama` vs `unload_llama` (no more double-mmap OOM or unload-mid-ladder).
- **Free RAM vs live generation** - `free_all_ram(skip_gguf=…)` keeps the warm model while a worker runs (unloading then would let the next send mmap a *second* multi-GB model next to it).
- **Agent-mode Copilot 401s** - AgentWorker + summary call now mint the Copilot token (env fallback, minted token stored in `_online_ctx`), Copilot skips structured `tools`, Copilot headers on both call sites.
- **Custom kaomoji lost in portable builds** - now persisted in the settings dict (`custom_kaomojis`) with one-time migration from the old package-dir sidecar; branched chats also carry `pinned`/`last_active`.
- **Lint-real**: duplicate `text_speed` default key (config), missing `Optional` import (avatar widget).

### Added - NEW.txt #9: CelMoji + Copilot merges
- **CelMoji smarts in the emoji picker** - frecency ordering (uses/day, 24 h decay), 📌 pin-to-top, 🚫 hide + unhide-all, right-click menu, pin/usage tooltips; all backed by the main settings dict (`emoji_frec` / `emoji_pins` / `emoji_bans`) with stale-dict rebinding after settings saves. Search results respect the same ordering; "+ Add Custom" sentinel stays last and can never be pinned/hidden.
- **GitHub Copilot provider** - new `GitHub Copilot` entry (🤖, `api.githubcopilot.com`, 12-model roster from the Arena client) flowing through Model Hub keys, model discovery, ping ("Ready - key set"), and details. Generation mints a short-lived Copilot token from the Hub GitHub token (or `CELSTUDIO_GITHUB_TOKEN`/`GITHUB_TOKEN` env) with in-memory caching, sends Copilot client headers over the shared SSE streaming path, and never sends `reasoning_effort`.
- **Security**: scrubbed a live hardcoded GitHub token (`FALLBACK_TOKEN`) from the dropped `models abilterated.py` source - no baked-in secrets anywhere; revoke it if it was ever real.

### Added
- **Chat sessions: right-click menu** - Open / Rename / Pin / Delete on every history entry; pinned chats sort first with 📌 prefix.
- **Session hover dates** - tooltip shows creation date and last-chat date (`created` + `last_active` are now tracked on every turn).
- **Cel voice volume to 200%** - new "Cel voice volume (TTS)" slider in Settings → Audio (10–200%, soft-saturated past 100%); applies to Kokoro + Edge, chat + live + preview.
- **Session-history tool summaries** - the 🕘 history panel collapses `<agent_action>` tags to one `🔧 tool - ✓ status` line and unescapes args (no more `&quot;` soup).

### Fixed
- **Paperclip button dead** - `show_attach_menu` built the QMenu but never called `exec()`; it now pops under the button.
- **Tray notification lied about Hey Cel** - minimize/close-to-tray now says "resting 💤, Hey Cel is off" when the wake word is off.
- **Rebrand strings** - window title → `Cellium`, sidebar → `🌀 Cellium` / `AI LLM Communicator`, input placeholder + tray strings updated (code identifiers and saved-data keys untouched).
- **Zoom restore race** - persisted zoom now applies synchronously at startup instead of a losable `singleShot(0)`.
- **Retry slider looked square** - bigger box (88×26) with margins and a 14px handle so nothing clips.
- **Thinking dropdown truncation** - wider box + AdjustToContents + 160px popup so "✦ Medium" never reads as "um…".
- **Inline `Mood: warm …` leaked into bubbles** - new `strip_inline_mood_display` (boundary-aware, prose-safe) wired through every display path + live transcript.
- **Thinking card in wrong chats** - finalize only touches the visible layout when the finished turn belongs to the open chat; history-loaded empty replies show "(interrupted - no reply text)" instead of a live "analyzing…" card; stream bubbles carry `is_live=True`.
- **Chat "multiplication"** - `_render_mem_entry` now paints each `(session, memory)` entry exactly once; TTS finish re-triggers a geometry pass (the narrow-wrap-after-talking case).
- **Thinking dots lane** - fixed-width minimum so the status line never jumps.

### Verified
- `tools/regression.py`: **43 passed, 1 skipped**, 2 failing on Male avatar data only (99 curator-culled files in `Anim/_Trash/Male`, incl. the Ahegao family - deliberate curation, left untouched).
- Headless assertions green: inline-mood strip, multi-`<think>` split, backtick TTS, TTS gain clamp, history unescape, live/history bubble modes.
- Items confirmed already-fixed in this snapshot (no change needed): TTS backtick eating, eye-jitter symmetry, `set_transcribing` crash, `_update_pet_mode_button` crash, multi-`<think>` 999x blowout, think-on-Low directives, settings/live autostart gates, phantom-STT toasts, studio wizard/expr-click/gender loading state.

### Known-blocked (carried, needs Henny)
- `I want this NEW.txt` #3 ("check my AI models in…") is truncated mid-sentence - Model Hub verified healthy; needs the ending.
- Crash-log segfault after GGUF unload/load cycling: native (llama.cpp) crash, not reproducible headless.
- `I want this NEW.txt` itself is now closed and removed (last actionable item #9 merged above); the two drop files (`celmoji.py`, `models abilterated.py`) are kept as provenance.

## [v2610.09.0] - 2026-10-09

### Added
- **Official CelSuite Rebrand:** Ecosystem integration under `HenryJayZ.CelSuite.Cellium`.
- **1,520 Procedural Dot-Matrix Expressions:** 760 Female + 760 Male animations with real-time synchronized blinking, eye tracking, and emotional reactions across 10 modifier styles.
- **Deep Reasoning Engine:** Collapsible `<think>` token accordion cards with 1-click height toggling.
- **Desktop Companion (Pet Mode):** Always-on-top, frameless desktop avatar that stays on your screen, reacts to your typing, and displays speech bubbles.
- **CelAS Live Voice Companion:** Full-screen voice calls with real-time mic-energy metering (VAD), live transcripts, and animated avatar mouth synchronization.
- **Unified Multi-Provider Cloud Hub:** First-class support for 11 providers (Google Gemini, Groq, DeepSeek, Cerebras, OpenRouter, SambaNova, Mistral, Together AI, Fireworks AI, SiliconFlow, and Custom OpenAI endpoints).
- **Native Android Client:** 100% finished Kotlin application with offline Gradle packaging, Live call mode, and complete avatar studio.

### Fixed
- **Chat Viewport Translucency:** Completely eradicated the black backing store box behind chat bubbles; wallpaper now shines seamlessly through the chat history.
- **Symmetrical Eye Physics:** Synchronized eye dilation and jitter using deterministic mirrored sine wave math.
- **TTS Backtick Word Stripping:** Fixed regex bug in Android text utilities that previously deleted words inside code backticks.
