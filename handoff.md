# Cellium Android ("Gemini Android") Handoff Brief

## 1. Project Context & Environment
- **Project Root:** `/home/henry/Documents/Projects/Python/Cellium`
- **Mobile Project Directory:** `/home/henry/Documents/Projects/Python/Cellium/Gemini Android`
- **Android Native Directory:** `/home/henry/Documents/Projects/Python/Cellium/Gemini Android/android`
- **Central Python Venv:** `/home/henry/Documents/Projects/Python/venv/bin/python` (Strict rule: NEVER create new `.venv` folders)
- **Kotlin SDK Kit:** `/home/henry/Documents/Projects/Kotlin` (`source env.sh` provides OpenJDK 21 + Android SDK 34)
- **Connected Device for Testing:** `10.149.194.31:5555` (Samsung SM-A035F, Android 13 / SDK 33)
- **APK Output:** `/home/henry/Documents/Projects/Python/Cellium/dist/HenryJayZ.CelSuite.Cellium-v<VER>.apk`

---

## 2. Current Architecture & What Works

### A. High-Performance Android Native Shell
- **Asset Interceptor:** Located in `Gemini Android/android/app/src/main/java/HenryJayZ/CelSuite/Cellium/MainActivity.java`.
  - Maps `https://cellium.local/*` to local APK assets (`assets/public/*`).
  - Resolves all CORS / null origin issues on Android Chromium WebView.
  - Zero white screen: WebView background set to `#07040d`.
  - JS console output forwarded directly to Logcat (`CelliumJS` tag).
- **Launcher Icons:** Fully regenerated across all 5 mipmap densities (`mipmap-mdpi` through `mipmap-xxxhdpi`) from `icon.webp`. Launcher displays the real, sharp, circular/square Cellium icon.
- **Background OOM Shield:** `CelliumForegroundService.java` runs as a persistent foreground service with wake lock.
- **Assist & Voice Interactor:** `CelliumVoiceInteractionService.java` registered in `AndroidManifest.xml`.

### B. Build & Testing Pipeline
- **`build_kotlin.sh`:** Updated to default to `build_gemini_android.sh` unless `legacy` is passed.
- **`build_gemini_android.sh`:**
  1. Runs `npm run build` in `Gemini Android/`.
  2. Syncs `dist/` to `android/app/src/main/assets/public/`.
  3. Bumps `versionName` (e.g. `2611.06.11`) and `versionCode` (e.g. `26110611`).
  4. Runs Gradle `assembleDebug`.
  5. Copies signed debug APK to `dist/`.
- **`Test Android.py`:** Autonomously executes adb install, records a 20s or 60s forensic window, verifies PID, takes device screenshots, and writes `Android_Bugs.md`.

---

## 3. Crucial Findings & Bugs to Fix Next

### A. Gemini API Model Endpoint Mismatch (P0)
- **Root Cause of Fallback Output:** 
  In `nativeBridges.ts`, the model name was hardcoded to `gemini-1.5-flash`.
  Google's API returned `404 NOT_FOUND: models/gemini-1.5-flash is not found for API version v1main`.
  Because of this 404 error, `callGemini` threw an exception, triggering the offline template fallback (`"I hear you loud and clear, Henry! ✨ I've processed your thought..."`).
- **Verified Working Model:**
  Testing confirmed that Henny's API key (`AIzaSyCoQ5CQkCIassTWohDC82apDeGdVVusU8U`) works with:
  - Model: `gemini-2.5-flash` or `gemini-flash-latest` or `gemini-2.5-flash-lite`
  - Direct Endpoint: `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${apiKey}`
  - Streaming Endpoint: `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent?alt=sse&key=${apiKey}`
- **Fix:** Update `nativeBridges.ts` to call `gemini-2.5-flash` directly via `:streamGenerateContent?alt=sse&key=${apiKey}` with standard SSE parsing, so questions like `"What's 9 times 54 and what's today?"` receive real answers (`486` + date).

### B. New Components Added in this Session
- **`OnboardingModal.tsx`:** 4-step Liquid Glass setup wizard mirroring `cellium/ui/onboarding.py`.
  - Step 1: Terms & Privacy Covenant
  - Step 2: Offline Voice & AI Downloads (Kokoro, Whisper)
  - Step 3: Cloud API Keys (Gemini, Groq)
  - Step 4: Personalization (Display Name input, Avatar Photo upload/camera, Companion Persona selector)
  - Triggered automatically on first run (`!cellium_onboarding_completed`), or via `modal=setup`, or from Settings / Drawer.
- **`ModelSelectorModal.tsx`:** Bottom-sheet modal to switch models:
  - Gemini 2.5 Flash Lite (`gemini-flash-lite-latest`)
  - Gemini 2.5 Flash (`gemini-2.5-flash`)
  - Gemini 3.8 Flash (`gemini-3.8-flash`)
  - Groq Llama 3.3 70B (`llama-3.3-70b-versatile`)
- **`ChatScreen.tsx`:**
  - Real file picker wired to `<Paperclip>` and `<ImageIcon>` buttons for camera/gallery image attachments.
  - Real `webkitSpeechRecognition` wired to `<Mic>` button.
  - Model pill wired to open `ModelSelectorModal`.
  - Thinking pill (`✦ Auto`) toggles Auto / High / Low / Off.
  - User name and avatar loaded dynamically from `localStorage` (`cellium_user_name`, `cellium_user_avatar`).
- **`ArenaScreen.tsx`:**
  - Replaced hardcoded script with dynamic duel engine where Fighter A and Fighter B alternate turns debating any user-injected topic.
- **`SettingsScreen.tsx`:**
  - Replaced mock buttons with real tabbed settings: Profile & Name, API Keys with "Test Key" button, Audio/Chirps volume, and Setup Wizard launcher.

---

## 4. Key Files to Inspect in the New Chat
- `Gemini Android/src/bridges/nativeBridges.ts` (API calls to Gemini 2.5 Flash)
- `Gemini Android/src/components/ChatScreen.tsx` (Chat view & controls)
- `Gemini Android/src/components/OnboardingModal.tsx` (First-run wizard)
- `Gemini Android/src/components/SettingsScreen.tsx` (Settings & API keys)
- `Gemini Android/src/components/ArenaScreen.tsx` (Arena duel)
- `Gemini Android/android/app/src/main/java/HenryJayZ/CelSuite/Cellium/MainActivity.java` (Native WebView host)
- `build_kotlin.sh` / `build_gemini_android.sh` (Build pipeline)
- `Test Android.py` (Forensic automated tester)

---

## 5. Next Steps for Next Session
1. Fix `callGemini` in `nativeBridges.ts` to use `gemini-2.5-flash:streamGenerateContent?alt=sse&key=${apiKey}` so cloud intelligence responds live.
2. Verify that `OnboardingModal` displays cleanly for any new user/friend on first boot so they can set their own name.
3. Build and test on connected phone (`bash build_kotlin.sh && python "Test Android.py" 20`).
