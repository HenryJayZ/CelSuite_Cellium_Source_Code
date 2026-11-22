# Cel.Cellium — Mega Project Handoff (`v2611.21.0`)

> **Purpose of this document**: Complete, self-contained engineering handoff for continuing **Cel.Cellium (Android)** in a brand-new chat session with **zero lost context**. Everything built, fixed, decided, constrained, and pending is recorded below.

---

## 1. Project Identity & Immutable Constraints

| Field | Value | Notes |
|---|---|---|
| **In-App Display Name** | `Cel.Cellium` | Shown in top bars, onboarding, branding |
| **Android Launcher Name** | `Cellium` | `app/src/main/res/values/strings.xml` + `metadata.json` (`"name": "Cellium"`) |
| **Application ID** | `CelSuite.HenryJayz.Cellium` | Set in `app/build.gradle.kts` — **DO NOT CHANGE** |
| **Namespace** | `com.henny.cellium` | Keeps generated `R` class and Kotlin packages intact |
| **Version Name / Code** | `v2611.21.0` / `versionCode = 3` | Upgraded from `v2611.20.2` per user instruction |
| **Target / Compile / Min SDK** | `compileSdk = 36`, `targetSdk = 36`, `minSdk = 26` | Tested compatible toolchain — **DO NOT bump compileSdk** |
| **AGP / Kotlin / KSP** | AGP `9.1.1`, Kotlin `2.2.21`, KSP `2.3.5` | Managed in `gradle/libs.versions.toml` |
| **PC Upstream Repo** | `https://github.com/HenryJayZ/CelSuite_Cellium_Source_Code` | Reference for PC Cellium features (Note: PC repo is outside this Android workspace) |
| **Google AI Studio Platform Sync** | Keep `MAJOR_CAPABILITY_SERVER_SIDE_GEMINI_API` in `metadata.json` | Never remove from `metadata.json` |

### Hard Rules (NEVER Violate)
1. **Zero Emojis in UI Chrome**: Every emoji across tabs, chips, providers, personas, headers, and status badges was replaced with Material Rounded Vector Icons & `VectorBadgeIcon` (`ui/components/CelliumIcons.kt`). Never reintroduce emojis into UI components.
2. **Exact 4-Tab Bottom Nav / Rail Order**: Strictly **`Imagine` · `Chat` · `Live` · `Settings`**.
   - **Avatar Studio**, **Stats & Dev Console**, and **RAM Watchdog** live inside **Settings** (opened as sub-overlays with `BackHandler`).
   - **Arena Mode (2-AI Group Chat)** opens from a dedicated button in **both** the Chat top bar and the Sessions drawer.
3. **Never Modify Signing Configs or Keystores**:
   - Never touch `debug.keystore`, `debug.keystore.base64`, or `signingConfigs` (`debugConfig`) in `app/build.gradle.kts`.
   - Never add product flavors or relocate Gradle's default APK/AAB output paths.
4. **Never Use `./gradlew`**: In this cloud container, always use `gradle <task>` (e.g., `gradle :app:assembleRelease --console=plain`), never `./gradlew`.
5. **No Firebase AI Logic / App Check / Direct Hardcoded API Keys**:
   - This app is a **universal BYOK + On-Device Offline AI** platform. It intentionally uses **Firebase Auth (Google Sign-In via Jetpack Credential Manager)** + **Cloud Firestore** for optional private user account backup ONLY.
   - **DO NOT** add `firebase-ai-logic` or `firebase-appcheck` — all LLM calls go through `UniversalLlmClient.kt` (200+ cloud providers + keyless Pollinations) or `OnDeviceLlmEngine.kt` (`.gguf` / `.task`).
6. **Llamatik Version Lock**:
   - Keep `llamatik = "0.17.0"` (`com.llamatik:library-android:0.17.0`) in `gradle/libs.versions.toml`!
   - **WARNING**: `com.llamatik:core-android:2.0.0` and `2.4.0` require `compileSdk = 37` and will break `:app:checkDebugAarMetadata` on `compileSdk = 36`.
7. **Shizuku Service Manifest Rule**:
   - **DO NOT** declare `<service android:name=".shizuku.ShizukuShellService" />` in `AndroidManifest.xml`! `ShizukuShellService` is a Shizuku `UserService` bound dynamically via `Shizuku.bindUserService`, not an `android.app.Service` — declaring it in the manifest causes `lintVitalRelease` to fail with `Instantiatable`.

---

## 2. Full Feature Inventory (All Implemented in `v2611.21.0`)

### A. 200+ AI Providers, Keyless Default & Key-First Live Model Fetcher
- **Default Out-of-the-Box Provider**: **Pollinations AI (`preset_pollinations_free`)** — works immediately with **zero API key** so anyone can test Chat, Live, Imagine, and Arena right after install.
- **200+ Provider Catalog (`ai/ProviderCatalog.kt` & `ai/ProviderPresets.kt`)**:
  - Searchable dropdown sheet (`ProviderSearchDropdownSheet` in `ui/chat/ChatSheets.kt`) accessible from Chat bar, Arena slots, Settings, and Onboarding.
  - Category filter chips: `All`, `Popular`, `Free`, `Frontier`, `Fast`, `Aggregator`, `Regional`, `Enterprise`, `Local`, `Offline`.
  - Common & Free/Keyless providers pinned first.
  - Supports **OpenAI-compatible**, **Anthropic**, **Google AI (Gemini native `/v1beta/models`)**, **Ollama**, **Pollinations**, and **On-Device Offline** protocols, plus **Custom Providers** (add/edit/delete).
- **Bug Fix #1 — Key-First Live Model Fetching + ZERO Truncation**:
  - `ProviderCatalogEntry.toEntity()`: For any provider where `requiresKey == true`, initializes `selectedModel = ""` and `cachedModelsJson = "[]"` so the app **never** pretends stale/ancient guessed models exist before pinging the user's key.
  - `UniversalLlmClient.fetchModels(...)`:
    - Rejects empty keys on keyed providers with a clear error instead of guessing.
    - **Google AI (Gemini)**: Queries native paginated `https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000&key=...` following `nextPageToken` across ALL pages and strips `models/` prefix.
    - **Anthropic**: Queries paginated `/models?limit=1000` with `x-api-key` + `anthropic-version` headers across pages.
    - **Ollama**: Queries `/v1/models` and `/api/tags`.
    - **Pollinations**: Fetches live `/models` list.
    - **OpenAI-compatible**: Queries `/models` and parses `data[]`, `models[]`, `items[]`, or root JSON array.
  - **UI Shows ALL Models (No `.take(8)` / `.take(10)` / `.take(12)` truncation)**:
    - `ProviderManagerSection.kt` (`ProviderEditDialog`): `"Ping Key & Fetch All Models"` button + live count (`"Live models from key: X / Y"`) + instant search bar + scrollable `LazyColumn` of every model returned + error text styled in `CelDangerRed` + auto-selects a valid model if current selection isn't in the returned list.
    - `ChatSheets.kt` (`ProviderSearchDropdownSheet`): `"Fetch Live"` button right inside the dropdown sheet + model search bar + scrollable `LazyColumn` showing ALL models for the active provider.
    - `OnboardingScreen.kt` (`StartupProviderStep`): `"Ping Key & Fetch All Models"` + searchable scrollable `LazyColumn` of ALL returned models.

### B. Zero-Flash Cold Boot & Onboarding Guard
- **Bug Fix #2 — Eliminated Split-Second Welcome/Onboarding Flash**:
  - `PreferencesStore.kt` mirrors critical boot flags (`termsAccepted`, `guestMode`, `onboardingCompleted`, `activeProviderId`, `themePresetId`) synchronously into `SharedPreferences("cellium_boot_cache")` on every write and DataStore sync.
  - `ChatViewModel.kt` seeds `preferences: StateFlow<CelliumPreferences>` synchronously with `prefsStore.readCachedInitialPreferences()` and exposes `preferencesLoaded: StateFlow<Boolean>`.
  - `CelliumApp.kt` renders a solid `visuals.voidBg` hold frame if `!prefsLoaded && !prefs.onboardingCompleted`, guaranteeing returning users NEVER see a 1–2 frame Onboarding/Welcome flash on launch.

### C. Full Local-First Room SQLite + Optional Private Google Account Sync
- **Bug Fix #3 — Save ALL Keys, Stats, Preferences & Data to Google Account**:
  - **Local-First**: Everything works 100% locally in Guest Mode via Room SQLite (`CelliumDatabase.kt`) + DataStore (`PreferencesStore.kt`).
  - **Optional Google Sign-In**: Uses Jetpack `CredentialManager` (`GetSignInWithGoogleOption`) in `core/AuthManager.kt` + Firebase Auth (never anonymous auth).
  - **Bidirectional Cloud Sync (`data/sync/CloudSyncManager.kt`)**:
    - Syncs everything strictly under `users/{uid}` in Cloud Firestore:
      1. `users/{uid}/account/state`: Usage stats (`totalSessions`, `totalMessages`, `totalTokens`, `totalEstimatedCostUsd`), active provider/persona, theme & glass visuals, voice/TTS/SFX/haptics, Shizuku/Agent settings, **Imagine API key & custom URL**, and **Kaggle username, API key, kernel slug, model ID**.
      2. `users/{uid}/providers/{providerId}`: All configured providers including **BYOK API keys**, base URLs, selected models, cached live models, and sampling parameters.
      3. `users/{uid}/templates/{templateId}`: Slash prompt templates.
      4. `users/{uid}/personas/{personaId}`: Custom personas.
      5. `users/{uid}/memories/{memoryId}`: Persistent memories.
      6. `users/{uid}/sessions/{sessionId}` + `messages/{messageId}`: All chat & Arena sessions + full branching message trees.
    - `ChatViewModel.kt` triggers `scheduleBackgroundCloudSync()` (debounced 2.5s) automatically whenever signed-in users save provider keys, fetch models, import Kaggle credentials, or complete chat turns, plus manual `"Sync Now"` in Settings.
  - **Firestore Security Rules (`/firestore.rules`)**:
    - **ALREADY DEPLOYED** to Firebase via `deploy_firebase`.
    - Global default-deny (`allow read, write: if false`) + strict `isOwner(userId)` check (`request.auth != null && request.auth.uid == userId`) on every subcollection (`account`, `providers`, `templates`, `sessions`, `messages`, `personas`, `memories`).

### D. Dual On-Device Offline AI (`.gguf` + `.task`) & Shizuku Privilege Engine
- **Dual Runtime (`ai/OnDeviceLlmEngine.kt`)**:
  - **`.gguf` models**: Native `llama.cpp` via **Llamatik (`com.llamatik:library-android:0.17.0`)**, invoked through reflection against `com.llamatik.library.platform.LlamaBridge` (keep rules present in `proguard-rules.pro`).
  - **`.task` / `.bin` models**: **MediaPipe Tasks GenAI (`0.10.29`)** with GPU delegate toggle + automatic CPU fallback.
  - Includes file picker import (`OpenDocument`), installed model list with load/unload/delete, and curated downloadable `.gguf` & `.task` starter models.
- **Shizuku Anti-Kill RAM Watchdog & AI Agent Mode (`shizuku/`)**:
  - `IShizukuShellService.aidl`, `ShizukuShellService.kt`, `ShizukuBridge.kt`: Real Shizuku `UserService` binder + shell execution.
  - `MemoryGuardService.kt`: Foreground service (`dataSync`) + automatic RAM watchdog (configurable threshold, default `1536 MB` / 1.5 GB) that elevates process priority and invokes Shizuku anti-kill protection before Android LMK kills heavy local models.
  - `CommandGuard.kt`: 3-tier safety classifier for AI Agent Mode shell commands (`SAFE`, `MUTATING` requiring explicit user approval dialog, `BLOCKED` for destructive patterns).
  - Moved RAM Watchdog controls into **Settings** (out of Stats).

### E. Chat Workspace, Tree Branching, Editing, Retry & Arena Mode
- **Fixed Rapidly Expanding Chat Bubble Bug (`ui/chat/ChatMessageComponents.kt`)**:
  - Stabilized header layout (preventing vertical single-character wrapping seen in early screenshots like `1\n.\n1\n4\ns`) and constrained bubble width cleanly with throttled streaming updates to eliminate input lag/stutter.
- **Full Tree Branching, Retry & Edit-With-Branch-Prompt (`ui/chat/ChatTreeHelper.kt`, `ChatViewModel.kt`, `ChatScreen.kt`)**:
  - Both **User bubbles** and **Cel (assistant) bubbles** support Edit, Retry/Regenerate, Branch, Copy, Speak (TTS), and Delete.
  - Editing either a user bubble or Cel's bubble **explicitly prompts** whether to **Create a new branch** or **Edit in place**.
  - Branch sibling switcher (`< 1/2 >`) navigates between parallel conversation branches seamlessly.
- **Composer Power Features (`ui/chat/ChatComposer.kt`)**:
  - **`+` Attachment Menu**: Separate **Image Picker** (Android Photo Picker — zero storage permission) and **Raw File Upload** (`OpenDocument` reading text/code/JSON/PDF metadata into prompt context).
  - **GBoard / Clipboard Rich Image Paste**: `contentReceiver` / clipboard paste support so images pasted from keyboards like Google GBoard attach directly to the prompt.
  - **Slash Command Menu (`/`)**: Instant popup of customizable Prompt Templates (`PromptTemplateEntity`) + built-in tool commands (`/search`, `/url`, etc.).
- **Web Search & URL Reader (`ai/WebToolsClient.kt`)**:
  - Live DuckDuckGo search + web page text extraction directly inside chat (auto-toggle or slash command).
- **Per-Reply Telemetry & Session Management**:
  - Token speed (`tok/s`), latency (`ms`/`s`), token estimate, and estimated USD cost per reply.
  - Sessions drawer: Full-text content search, Pin, Archive, Auto-Title generation, Export Markdown / JSON, and Full App JSON Backup/Restore (`data/local/AppBackupManager.kt`).
- **Arena Mode — 2-AI Group Chat (`ui/arena/ArenaController.kt`, `ui/arena/ArenaScreen.kt`)**:
  - Pick **AI A** (Provider + Model + Persona) and **AI B** (Provider + Model + Persona).
  - Send a topic/message and watch the 2 AIs converse back-and-forth automatically; **Pause / Resume / Stop** at any time; inject user messages mid-conversation whenever desired; persisted as `isArena = true` sessions in Room & Firestore.

### F. Multi-Provider Imagine Studio + Kaggle GPU `.json` Workflow
- **`ui/imagine/ImagineStudioScreen.kt` + `ai/MultiImagineClient.kt`**:
  - Supports **Pollinations (Free, No Key)**, **Kaggle GPU Notebook (`kaggle.json` import — exact PC Cellium flow)**, **Hugging Face Inference**, **OpenAI DALL-E / GPT-Image**, **Stability / Replicate**, and **Custom OpenAI Image Endpoints**.
  - Import `kaggle.json` file directly via document picker (`username` + `key` auto-extracted & synced if signed in) + configure kernel slug & HF model ID (`stabilityai/sdxl-turbo`, etc.).
  - Gallery persisted in Room (`ArtworkEntity`) with aspect ratio, seed, negative prompt, and save/share actions.

### G. Live Voice Mode, Animalese SFX, Haptics & Notifications
- **Live Voice Mode (`ui/live/LiveModeScreen.kt`)**:
  - Dedicated 3rd tab (`Live`, Call icon) with hands-free loop, Android `SpeechRecognizer` + `TextToSpeech` (configurable voice, pitch, rate), reactive 3,800-expression dot-matrix avatar, and real-time audio/status controls.
- **Audio & Haptics (`core/SoundEngine.kt`)**:
  - Bundled `.wav` SFX assets in `res/raw/` (`cerebrium_click`, `cerebrium_open`, `cerebrium_pop`, `cerebrium_recv`, `cerebrium_send`, `ac_note_0..10` for **Animalese** speech ticks!) + volume slider + haptic feedback toggles.
- **WhatsApp-Style Bundled Notifications (`core/CelliumNotificationManager.kt` & `core/ChatReplyReceiver.kt`)**:
  - Uses Android `MessagingStyle` + notification group summary so multiple background chat replies collapse into a single expandable notification stack with **Inline Direct Reply**.
- **System Permissions & Android Settings Deep-Links**:
  - Quick buttons in Settings for ignoring Battery Optimization, Notification Settings, Shizuku authorization, and app info/permissions.

### H. 3,800-Expression Dot-Matrix Avatar Studio & Liquid Glass Theme Engine
- **Avatar System (`avatar/` + `ui/avatar/`)**:
  - `assets/cel_expressions.bin` decoded via `AvatarBinaryLoader.kt` and rendered smoothly on Compose `Canvas` (`DotMatrixAvatarCanvas.kt`) with real-time mood detection (`MoodDetector`).
  - **Avatar Studio** (inside Settings) + optional **Floating Mini-Cel** overlay (`FloatingMiniCel.kt`).
- **Liquid Glass Theme Editor (`ui/theme/` + `ui/settings/ThemeVoiceSection.kt`)**:
  - Multiple color presets + custom primary hex + custom wallpaper picker + wallpaper dim + glass opacity + border glow + particle density + high-FPS toggle + font scale.
  - Bundled local Google Fonts in `res/font/` (`plus_jakarta_sans.ttf`, `space_grotesk.ttf`, `jetbrains_mono.ttf`).
- **RAM Optimization**:
  - Lazy loading, downsampled image decoding, bounded caches, optional particle reduction, and on-device model unload controls to keep idle RAM lean.

---

## 3. Complete Workspace File Map

```text
/
├── app/
│   ├── build.gradle.kts                      # App config, R8 release minification, signingConfig debugConfig
│   ├── proguard-rules.pro                    # Keep rules for Llamatik, MediaPipe, Shizuku, Kotlinx Serialization, Firestore
│   ├── google-services.json                  # Provisioned Firebase config
│   └── src/main/
│       ├── AndroidManifest.xml               # Permissions, ShizukuProvider, MemoryGuardService, ChatReplyReceiver
│       ├── aidl/com/henny/cellium/shizuku/
│       │   └── IShizukuShellService.aidl     # Shizuku privileged shell IPC interface
│       ├── assets/
│       │   └── cel_expressions.bin           # Binary 3,800-expression dot-matrix avatar atlas
│       ├── res/
│       │   ├── drawable/                     # cel_avatar.png, cel_wallpaper.webp, ic_cellium_brand.png, adaptive icon layers
│       │   ├── font/                         # jetbrains_mono.ttf, plus_jakarta_sans.ttf, space_grotesk.ttf
│       │   ├── mipmap-*/                     # Custom adaptive launcher icons
│       │   ├── raw/                          # ac_note_{0,2,4,6,8,10}.wav, cerebrium_{click,open,pop,recv,send}.wav
│       │   └── values/                       # strings.xml, themes.xml, firebase_applet_config.xml
│       └── java/com/henny/cellium/
│           ├── MainActivity.kt               # Edge-to-edge entry point, ViewModel init
│           ├── CelliumApp.kt                 # Zero-flash boot guard, 4-tab NavBar/NavRail, sub-overlays (Arena, Avatar, Stats)
│           ├── ai/
│           │   ├── UniversalLlmClient.kt     # Streaming chat + key-first paginated live model fetcher (Google/Anthropic/OpenAI/Ollama/Pollinations)
│           │   ├── ProviderCatalog.kt        # 200+ provider registry, category search, keyless vs keyed entity builder
│           │   ├── ProviderPresets.kt        # Default profiles, curated .gguf/.task models, model JSON codec
│           │   ├── OnDeviceLlmEngine.kt      # Dual offline engine: Llamatik (.gguf) + MediaPipe (.task/.bin)
│           │   ├── MultiImagineClient.kt     # Pollinations, Kaggle GPU (.json), HF, OpenAI, Custom image gen
│           │   └── WebToolsClient.kt         # Web search + URL content extractor
│           ├── avatar/
│           │   ├── AvatarBinaryLoader.kt     # Binary atlas decoder for cel_expressions.bin
│           │   ├── AvatarModels.kt           # Moods, expression specs, MoodDetector
│           │   ├── DotMatrixAvatarCanvas.kt  # High-FPS Compose Canvas dot-matrix renderer
│           │   └── WelcomeFaceOrb.kt         # Animated orb header widget
│           ├── core/
│           │   ├── AuthManager.kt            # CredentialManager Google Sign-In -> Firebase Auth
│           │   ├── PreferencesStore.kt       # DataStore + synchronous SharedPreferences("cellium_boot_cache") + cloud snapshot apply
│           │   ├── SoundEngine.kt            # SoundPool SFX + Animalese speech engine + haptics
│           │   ├── CelliumNotificationManager.kt # WhatsApp-style grouped MessagingStyle notifications + inline reply
│           │   ├── ChatReplyReceiver.kt      # BroadcastReceiver handling inline notification replies
│           │   └── FirestoreErrorHandler.kt  # Friendly Firestore error formatting
│           ├── data/
│           │   ├── Models.kt                 # Built-in personas, UI domain models
│           │   ├── CelliumRepository.kt      # Data repository helpers
│           │   ├── local/
│           │   │   ├── CelliumDatabase.kt    # Room SQLite database
│           │   │   ├── CelliumEntities.kt    # 7 Room tables: providers, sessions, messages, custom_personas, memories, prompt_templates, artworks
│           │   │   ├── CelliumDao.kt         # Queries, flows, full-text session search
│           │   │   └── AppBackupManager.kt   # Full JSON export/import backup
│           │   └── sync/
│           │       └── CloudSyncManager.kt   # Bidirectional Google Account sync (keys, Kaggle, stats, prefs, templates, personas, memories, chats)
│           ├── shizuku/
│           │   ├── ShizukuBridge.kt          # Shizuku binder, permission, anti-kill OOM boost, shell exec
│           │   ├── ShizukuShellService.kt    # Privileged UserService implementation
│           │   ├── MemoryGuardService.kt     # Foreground anti-kill service for >1.5GB local inference
│           │   └── CommandGuard.kt           # 3-tier Agent shell safety guard
│           └── ui/
│               ├── analytics/AnalyticsScreen.kt        # Usage stats, token/cost charts, Dev Console log viewer
│               ├── arena/ArenaController.kt            # 2-AI turn orchestration, pause/resume/inject
│               ├── arena/ArenaScreen.kt                # 2-AI Group Chat UI
│               ├── avatar/AvatarStudioScreen.kt        # Expression browser & avatar customization
│               ├── avatar/FloatingMiniCel.kt           # Draggable floating companion overlay
│               ├── chat/ChatViewModel.kt               # Main MVVM state holder, streaming, branching, sync, Shizuku, local LLM
│               ├── chat/ChatScreen.kt                  # Primary Chat tab
│               ├── chat/ChatComposer.kt                # + menu (Image/File), GBoard paste, slash commands, voice trigger
│               ├── chat/ChatMessageComponents.kt       # Stabilized chat bubbles, edit/branch dialog, retry, tok/s & cost pills
│               ├── chat/ChatSheets.kt                  # 200+ Provider & live ALL-models searchable sheet, Sessions drawer, Persona picker
│               ├── chat/ChatTreeHelper.kt              # Tree linearization & sibling branch navigation
│               ├── components/AgentComponents.kt       # Shizuku Agent approval dialog & command cards
│               ├── components/CelliumIcons.kt          # Zero-emoji VectorBadgeIcon registry
│               ├── components/GlassComponents.kt       # Liquid Glass cards & animated background
│               ├── imagine/ImagineStudioScreen.kt      # Multi-provider Imagine Studio + Kaggle .json import
│               ├── live/LiveModeScreen.kt              # Hands-free Live Voice Mode
│               ├── onboarding/OnboardingScreen.kt      # 3-step First-Run Onboarding (Terms -> Guest/Google -> Provider)
│               ├── settings/SettingsScreen.kt          # Master Settings hub (Avatar, Stats, RAM Watchdog, Shizuku, Backup, Google Sync)
│               ├── settings/ProviderManagerSection.kt  # Provider Hub, ProviderEditDialog (all live models), On-Device Model Manager
│               ├── settings/ThemeVoiceSection.kt       # Liquid Glass theme editor, voice/TTS/Animalese/SFX/haptics controls
│               └── theme/{Color,Theme,ThemePresets,Type}.kt
├── firestore.rules                           # Deployed strict owner-only Firestore security rules
├── firebase.json & firebase-blueprint.json   # Firebase project config & schema blueprint
├── gradle/libs.versions.toml                 # Version catalog (llamatik 0.17.0, AGP 9.1.1, Kotlin 2.2.21)
├── metadata.json                             # AI Studio app metadata
└── mega_handoff.md                           # THIS FILE
```

---

## 4. Exact Current State & Pending Verification (Start Here in Your Next Chat!)

### What Was JUST Finished (Code Written on Disk, Not Yet Re-Compiled After Final 6 Edits)
Right before this handoff, we fixed the user's final **3 bugs** across backend + UI:
1. **Live Key-First Model Fetching + Zero Truncation**:
   - `UniversalLlmClient.kt`, `ProviderCatalog.kt`, `ChatViewModel.kt`, `ProviderManagerSection.kt`, `ChatSheets.kt`, `ChatScreen.kt`, `ArenaScreen.kt`, `OnboardingScreen.kt`.
2. **Zero-Flash Cold Boot (No Split-Second Onboarding Flash)**:
   - `PreferencesStore.kt` (`cellium_boot_cache`), `ChatViewModel.kt` (`preferencesLoaded`), `CelliumApp.kt` (boot hold frame + fixed missing `androidx.compose.foundation.background` import).
3. **Full Private Google Account Sync (All Keys, Kaggle, Stats, Prefs, Chats, Templates, Personas, Memories)**:
   - `firestore.rules` (**already deployed to Firebase**), `CloudSyncManager.kt`, `PreferencesStore.kt` (`applyCloudSnapshot`), `ChatViewModel.kt` (added `com.google.firebase.Firebase` + `com.google.firebase.auth.auth` imports + debounced auto-sync), `OnboardingScreen.kt`, `SettingsScreen.kt`, `ProviderManagerSection.kt`.

### What Was Intentionally Skipped at User Request
- The user canceled the final `gradle :app:assembleRelease` build and manually deleted `/apk/cellium-signing.keystore` and `/apk/SIGNING_INFO.txt` because they are downloading/pushing this project folder to continue in a new chat.
- **First Action for the Next Agent**:
  1. Run `compile_applet` (or `gradle :app:assembleDebug --console=plain`) to verify the final 6 UI/import edits compile with zero errors.
  2. If the user asks for a minified release APK again:
     - Run `gradle :app:assembleRelease --console=plain` (R8 minification + resource shrinking are already configured in `app/build.gradle.kts` & `app/proguard-rules.pro`).
     - Copy `app/build/outputs/apk/release/app-release.apk` into `/apk/Cel.Cellium-v2611.21.0-release.apk` (note: APK is ~171 MB because it bundles native C++ `.so` libraries for both `llama.cpp` GGUF and MediaPipe GenAI across ABIs; ABI splits could shrink per-arch APKs to ~55–65 MB if requested later).
     - Copy `debug.keystore` -> `/apk/cellium-signing.keystore` ONLY if requested (never modify the root `debug.keystore`).

---

## 5. Known Gotchas, Lessons Learned & Optional Future Polish Ideas

### Gotchas Already Solved (Don't Regress!)
- **Llamatik `core-android:2.0.0+` breaks API 36**: Stay on `com.llamatik:library-android:0.17.0`.
- **`ShizukuShellService` in `AndroidManifest.xml` breaks `lintVitalRelease`**: Keep it removed from `AndroidManifest.xml`; Shizuku binds it dynamically.
- **Google AI `/v1beta/models` vs OpenAI `/models`**: Google AI Studio keys require the native paginated `/v1beta/models?pageSize=1000&key=...` endpoint to list ALL models reliably (including latest Gemini models), stripping the `models/` prefix.
- **Compose `LazyColumn` inside `verticalScroll`**: In `OnboardingScreen.kt` (`StartupProviderStep`), the model list `LazyColumn` uses `.heightIn(max = 200.dp)` so it has bounded constraints and never crashes inside the scrollable step column.

### High-Value Next Ideas (If the User Asks in the Next Chat)
- **Per-ABI Release APK Splits (`arm64-v8a`)**: Reduces the ~171 MB universal APK down to ~60 MB for modern Android phones while keeping both `.gguf` and `.task` native engines intact.
- **Encrypted Cloud Key Vault Passphrase Option**: Optional client-side AES-GCM encryption layer on top of Firestore's owner-only TLS/at-rest storage for power users.
- **Live Streaming Markdown Renderer**: Rich code-block syntax highlighting + one-tap "Copy Code" button inside chat bubbles.
- **PC Version Parity Check**: Remind user that `https://github.com/HenryJayZ/CelSuite_Cellium_Source_Code` is external to this Android workspace — if they want Arena Mode or other features added to the **PC** app, they should share/open the PC repository in a separate session.
