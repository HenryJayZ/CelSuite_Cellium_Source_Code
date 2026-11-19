# 🚀 PHASE 2 - Enhancer model, Mega-batch, Cloud storage, Warm-cache commands

> Legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked/needs-human

## 0. Groundwork
- [ ] Find a lightweight one-shot LLM helper (for Enhance's dedicated model)
- [ ] Verify Kaggle dataset create/version/delete endpoints (kagglesdk)
- [ ] Map main_window model list for the enhancer-model combo

## 1. ✨ Enhance = dedicated model (user-pickable)
- [x] Settings: `kaggle_enhancer_model` field in Settings → Image Gen (saved)
- [x] Imagine dialog: "✨ Enhancer" combo populated from the app's Model Hub list (+ "Local tags")
- [x] Enhance button → one-shot LLM call (`enhance_with_model`) with that model (Danbooru-tag system prompt), fallback to local `enhance_prompt`

## 2. 📦 Mega-batch (up to 20) + progress tracker
- [x] Batch cap 4 → 20 in the Imagine dialog
- [x] Kernel already loops `out_NN.png`; chat status bubble shows "×N images" when batch>1
- [x] Done bubble shows total count + seeds

## 3. ☁️ Cloud storage (Option A - the real speed fix)
- [x] Settings toggle "☁️ Keep model in a private Kaggle dataset & mount it" + dataset slug field
- [x] Upload local .safetensors → private dataset with a REAL progress bar (ProgressReader multipart streaming, QTimer-polled)
- [x] Kernel payload adds `datasetDataSources` and loads from `/kaggle/input/<slug>/**/model.safetensors` (skips the ~2-min download → ~5s)
- [x] Delete dataset button → `POST /api/v1/dataset/{owner}/{slug}/delete`
- [x] Civitai/HF URL models: upload needs a local file; slug mount works for any dataset

## 4. 🔥 Warm-cache commands (honesty note honored)
- [x] `/imagine-start-cache` / `/imagine-stop-cache` slash commands (in the `/` drop-up) + ⋯ menu "🔥 Warm Cache" toggle
- [x] Loud quota warning in the chat bubble + hard 1h `sessionTimeoutSeconds` cap (CACHE_SESSION_CAP=3600)
- [x] NOTE honored: Kaggle can't inject prompts into a running notebook, so batches run as script jobs (fast with the dataset mount); the warm notebook is quota-guarded and auto-tears-down

## 5. Tests & docs
- [x] Regression: enhancer setting, batch cap 20, dataset payload field + kernel mount, cache commands/toggle, cloud settings fields - **109/109 green**
- [x] CHANGELOG + KAGGLE_IMAGE_GEN.md + TODO_PHASE2
