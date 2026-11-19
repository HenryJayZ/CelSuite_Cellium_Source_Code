# 🎨 Kaggle Cloud Image Generation - Build Plan

> Status legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked (human-only)

## 0. Groundwork
- [x] Read browser automation rules
- [x] Read Henny's Colab `Mini App.py` + `Run Once.py`
- [x] Read Cellium `AGENTS.md`
- [x] Read utilities / python execution rules
- [x] Map Cellium settings, chat input, bubble rendering, config paths
- [x] Verify Kaggle API field names + public default model (kagglesdk source: camelCase JSON, POST; status enum names; verified `lykon/dreamshaper-xl-v2-turbo` & `RunDiffusion/Juggernaut-XL-v9` are public/non-gated)

## 1. Backend (`cellium/services/kaggle_image.py`)
- [x] `KaggleImageBackend` - pure `requests`, BYOK Basic auth
- [x] `validate_credentials()` → friendly result
- [x] Build kernel source from template - `repr()`+`json.dumps` token replacement (injection-proof, ast-verified)
- [x] HF mode (public repo / optional token)
- [x] Civitai single-file mode (URL + optional token)
- [x] Optional LoRA (URL + strength)
- [x] Push → poll (5s, 15m timeout) → fetch outputs (JSON camelCase+snake_case + binary fallback, paginated)
- [x] Parse `<img>.meta.json` seed; save PNG to gallery
- [x] Error mapping: 401 / quota / 429 backoff / timeout / cancelled; sessionTimeoutSeconds=2700 cap
- [x] One-job lock + local FIFO queue
- [x] `KaggleImageWorker(QThread)` with Qt signals

## 2. Settings UI
- [x] New "🖼️ Image Generation" settings tab (friendly)
- [x] Kaggle username + API key (masked) + import `kaggle.json`
- [x] Test connection button
- [x] Model source: HuggingFace / Civitai, repo/URL/token fields (visibility toggles)
- [x] Defaults: negative prompt, steps, CFG, size preset, LoRA, output folder
- [x] Persist through existing settings save path (DEFAULT_SETTINGS updated)
- [x] Never log/echo secrets (masked QLineEdit, no dev_log of key)

## 3. User-facing generation
- [x] `ImagineDialog` - prompt, negative, steps, size, CFG, seed (random toggle)
- [x] Progress toasts: pushing → queued → running → downloading → done
- [x] "🎨 Imagine" button in chat input pill
- [x] `/imagine <prompt>` chat command (intercepted before LLM)
- [x] Inline image bubble in chat (MessageBubbleNew attached_images, click fullscreen via existing path)
- [x] Seed shown in bubble caption
- [x] Save to gallery folder + Open Output Folder button

## 4. Tests & docs
- [x] Regression: 6 kaggle checks (injection safety, civitai+lora, status+payload, output+factory, settings UI, /imagine intercept)
- [x] Full suite **101/101 green**
- [x] CHANGELOG + `KAGGLE_IMAGE_GEN.md` user guide
- [x] Update AGENTS.md map
- [x] Visual QA screenshots of settings tab + imagine dialog

## 5. Human-only / browser steps
- [x] SMS-verify Kaggle account (unlocks GPU) - done by Henny
- [x] Create API token → `kaggle.json` - agent drove browser to kaggle.com/settings/api → Create Legacy API Key → Continue → downloaded ~/Downloads/kaggle.json (chmod 600, also copied to ~/.kaggle/kaggle.json)
- [x] Credentials injected into cerebrium_settings.json (kaggle_username=henrycarm, key SET, never printed) - validate_credentials() → 200 OK against live API
- [x] Live smoke test **PASSED end-to-end**: push accepted (v3) → queued → running → complete (173s) → fetched 322KB PNG `kaggle_20261102_231721_...png`, seed 1234 - a real red apple on a wooden table 🍎
- [x] Fixed Kaggle py3.13/transformers-5 breakage: pinned `diffusers>=0.34,<0.35` + `transformers>=4.41,<5` (was `FLAX_WEIGHTS_NAME` ImportError)
- [x] Added Colab model presets (Nova/Oops/Pony/Juggernaut/CyberRealistic/DreamShaper) to Imagine dialog + Settings, with Civitai page-URL→SDXL-file resolver baked into the kernel
- [x] Kernel log tail now surfaced in errors (no more "Unknown error")
- [x] Welcome page glow-up: halo orb + gradient headline + GPT/Gemini suggestion chips (🎨 Generate an image chip wired to the dialog)
- [x] Orb centered in halo (QStackedLayout AlignCenter)
- [x] Presets trimmed to DreamShaper / Nova / Juggernaut / Custom only
- [x] Mini-App feature port: batch (1-4), ✨ Enhance prompt, aspect sizes, negative, steps/CFG/seed, LoRA
- [x] Kaggle progress → small nameless in-chat bubbles, NO toasts, 33s heartbeat throttle, errors as red in-chat bubble w/ log tail
- [x] Civitai failure fixed: API resolve wrapped in try/except → falls back to direct api/download/models/<id> (no token needed for public models)
- [x] "/" slash-command drop-up above input (commands: /imagine), filter + keyboard nav
- [x] LoRA made non-fatal: download/load wrapped in try/except → "LoRA skipped" on failure (gated LoRAs 401 without a Civitai token; set one in Settings to use them)
- [x] Nova (Civitai) live smoke test v2 **PASSED**: complete ~307s → 343KB anime PNG (seed 7), LoRA gracefully skipped - Civitai direct-download path proven end-to-end
- [x] Both live paths proven: HF DreamShaper (red apple 🍎) + Civitai Nova (anime girl 🎨)
- [x] AI-callable `generate_image` agent tool (cellium/services/image_tool.py hub + ImagineTool) - registered only when `image_gen_enabled`
- [x] Hamburger ⋯ menu "🎨 Enable Image Gen" toggle (off = tool not sent to model = smaller context)
- [x] img2img "edit last image" (edit_last → init_b64 embedded, Img2ImgPipeline, denoise) - like Mini App follow-ups
- [x] Tool results render inline in chat via hub signals (image_ready → bubble + session memory)
- [x] Welcome block vertically centered (leading+trailing stretch), orb centered in halo
