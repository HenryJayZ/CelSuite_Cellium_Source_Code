# 🎨 How Kaggle Works in Cellium — Full Image Pipeline & Android Porting Spec

> **Audience:** Henny + the AI porting Cellium to Android.
> **Status:** verified against the live source on **2026-11-27**.
> **Rule:** if this document and the code ever disagree, the code wins — then fix this document.
>
> **Source of truth (PC app):**
> - `cellium/services/kaggle_image.py` — backend, kernel template, presets, enhancer, datasets
> - `cellium/services/model_cache.py` — server-side model cache (Phase 5)
> - `cellium/services/kaggle_relay.py` — warm-cache v3 watcher + ntfy relay
> - `cellium/services/image_tool.py` — the AI-callable `generate_image` tool + img2img
> - `cellium/ui/widgets/imagine_dialog.py` — Imagine dialog (Simple/Advanced)
> - `cellium/ui/settings/dialog.py` — “🖼️ Image Generation” settings tab
> - `cellium/ui/main_window.py` — chat entry points, progress bubbles, gallery, warm cache
> - `cellium/core/config.py` — every `kaggle_*` default
> - `cellium/services/ai_workers.py` — where the `generate_image` tool is registered

---

## Contents

0. The 30-second version
1. Prerequisites & quota
2. Architecture
3. The four image models
4. Script mode: the complete protocol
5. The kernel script
6. All the image features
7. Phase 5 — server-side model cache
8. Warm-cache v3 — the ntfy relay
9. Security, privacy, secrets
10. Android port blueprint
11. Error catalog
12. Constants cheat sheet
13. Landmines & “do not port blindly”
14. Source map
15. Glossary

---

## 0. The 30-second version

Kaggle is **Cellium’s free cloud GPU render farm**. The phone/PC never runs Stable Diffusion.

```
Cellium (phone/PC)                         Kaggle (cloud GPU)
──────────────────                         ──────────────────
1. HTTPS + user's Kaggle key  ──────────►  push a private Python "script" kernel
2. poll status every 5 s      ──────────►  queued → running → complete
3. download the JPEG          ◄──────────  /kaggle/working/out.jpg + meta.json
4. (optional) wipe traces     ──────────►  CPU-only clean script, zero GPU quota
```

- **BYOK:** each user brings their own Kaggle username + **legacy** API key.
- **No middleman server.** The app talks directly to `https://www.kaggle.com/api/v1`.
- **No model on the device.** Kaggle downloads/loads the checkpoint; only the finished image comes back.
- **4 image presets:** DreamShaper XL Turbo v2, Nova Cartoon XL, Juggernaut XL Ragnarok, Custom.
- **Two execution modes:**
  - **Script mode** — default, reliable. A fresh GPU VM per job, self-terminates at the end.
  - **Warm-cache v3** — optional. One long-running GPU kernel holds the model in VRAM and receives jobs over an `ntfy.sh` relay; ~6–9 s per image after warm-up. Costs a GPU slot the whole time.
- **The mobile port is pure Kotlin/HTTP.** No Python, no diffusers, no local GPU. The phone only builds a JSON payload + a Python script string, polls, and downloads a JPEG.

---

## 1. Prerequisites & quota (human-only)

| Step | Where | Why it matters |
|---|---|---|
| Create a Kaggle account | `kaggle.com` | The key belongs to this account. |
| **SMS-verify the phone** | Settings → Account → Phone Verification | **GPU quota stays locked until verified.** |
| Create a **Legacy API Key** | `kaggle.com/settings/api` → *Create Legacy API Key* → *Continue* | Downloads `kaggle.json` = `{"username": "...", "key": "..."}`. |
| Keep the key private | — | It can push kernels and read datasets as the user. |

> ⚠️ **Legacy key, not the newer Bearer “API Token”.** Cellium authenticates with HTTP **Basic** `username:key`. The `kaggle.json` format is the correct one.
>
> ⚠️ **Kaggle’s free GPU quota is ~30 h/week** and resets weekly (Monday). A hung kernel can burn it, so every pushed script has a hard `sessionTimeoutSeconds` cap (2700 s = 45 min for renders, 3600 s = 1 h for cache builders/watchers).
>
> ✅ The PC app already has Henny’s `kaggle.json` at `~/Downloads/kaggle.json` and `~/.kaggle/kaggle.json` (`chmod 600`), with the key stored in the local (gitignored) `cerebrium_settings.json`. The Android app must store its own copy in **EncryptedSharedPreferences / Keystore** — never in a shared APK, never in logs.

---

## 2. Architecture

### 2.1 Script mode (default, always works)

```
┌────────────────────────────── Cellium ──────────────────────────────┐
│ Settings (BYOK)                                                     │
│   kaggle_username / kaggle_api_key                                  │
│   kaggle_preset → ModelConfig (mode, repo/URL, LoRA, steps, CFG)    │
│                                                                     │
│ KaggleImageBackend                                                  │
│   1. _maybe_mount_cache()   ── JSON-only dataset probe              │
│   2. _build_kernel_script() ── CFG + model loader + LoRA            │
│   3. POST /kernels/push     ── private, GPU, internet, 45-min cap   │
│   4. POST /kernels/status   ── every 5 s                            │
│   5. POST /kernels/output   ── log tail every 30 s while running    │
│   6. GET  file URLs         ── out.jpg / out_01.jpg + meta.json     │
│   7. POST /kernels/push     ── CPU-only stealth wipe (optional)     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Warm-cache v3 (optional turbo)

```
Cellium                          ntfy.sh                         Kaggle watcher kernel
────────                         ───────                         ─────────────────────
POST cmd topic  ───────────────►  cmd topic  ── SSE ─────────────►  consume jobs
                                  (plain text JSON)                  load model ONCE
                                                                     render 6–9 s/image
GET res topic   ◄───────────────  res topic  ◄── SSE/JSON poll ───  heartbeat + result
download JPEG   ◄───────────────  attachment ◄────────────────────  raw JPEG + Filename
```

The watcher is a **script** kernel (not a notebook) because Kaggle validates notebook bodies as `.ipynb` JSON. It stays alive until the shutdown pill, the 1 h hard cap, or the 10 min idle watchdog.

---

## 3. The four image models (exact presets)

`MODEL_PRESETS` in `kaggle_image.py` is the single source of truth. The app ships **four** entries: three real engines + a manual Custom mode.

| # | UI label (exact string) | Mode | Checkpoint / repo | Size | Base | LoRA | Steps | CFG | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `✨ DreamShaper XL Turbo v2 (fast, public HF)` | HuggingFace | `lykon/dreamshaper-xl-v2-turbo` | ~7 GB (HF) | SDXL Turbo fine-tune | none | **8** | **2.0** | Fastest, public, non-gated. Default preset. |
| 2 | `🎨 Nova Cartoon XL (Civitai)` | Civitai | version **`2329740`** → `novaCartoonXL_v60.safetensors` | **6.94 GB** | Illustrious (SDXL family) | version **`1524099`** (Cartoony / Juukyuu Illustrious, ~228 MB) | **33** | **7.0** | Anime/cartoon engine. LoRA is optional garnish; failure is non-fatal. |
| 3 | `📸 Juggernaut XL Ragnarok (Civitai)` | Civitai | version **`1759168`** → `juggernautXL_ragnarok.safetensors` | **7.11 GB** | SDXL 1.0 | **none** | **33** | **7.0** | Photoreal/realism engine. Keep the cartoon LoRA off it. |
| 4 | `🔧 Custom (from Settings)` | `custom` | whatever the user sets | user | user | user | **28** (default) | **6.5** (default) | Uses `kaggle_model_mode` + HF/Civitai fields + LoRA fields. |

### 3.1 Why the exact IDs matter

- **Civitai *version* IDs are safe.** `https://civitai.com/api/download/models/2329740` always serves that exact file.
- **Civitai *model* IDs are a trap.** `https://civitai.com/api/download/models/133005` serves the page’s **latest** file — which once was a 151 MB different checkpoint (`MaouBigV1.2.safetensors`), not Juggernaut XL. That then failed with `CLIPTextModel weights missing`.
- If a user pastes `https://civitai.com/models/<id>`, the kernel resolves it through `GET https://civitai.com/api/v1/models/<id>` and picks the best **SDXL / Illustrious** version, skipping names containing `inpaint`. Direct `/api/download/models/<id>` URLs pass straight through.
- The Mini App’s old Nova LoRA id `627178` is genuinely gone; the preset uses `1524099`, which is alive.

### 3.2 Per-preset recipe behavior

- Selecting a preset in the **Imagine dialog** writes its `steps` and `guidance` into the controls (`_on_model_changed`).
- Selecting a preset in **Settings** mirrors its mode, HF repo / Civitai URL, LoRA URL, steps and guidance into the editable fields (`_on_kaggle_preset_changed`).
- The **actual request** uses the control/settings values. This matters for `/imagine` and the AI tool: they read `kaggle_steps` / `kaggle_guidance` from settings, not directly from `MODEL_PRESETS`.
- `build_model_config()` applies a preset only when its `mode != "custom"`. The Custom preset deliberately falls back to the manual settings.
- **LoRA strength** default `0.9`, range `0.1–2.0` in the UI.

### 3.3 Quality tags are *not* automatic

The backend does **not** silently prepend quality tags. They are added by:

1. the **✨ Enhance** button (`enhance_prompt` / LLM enhancer), or
2. the user’s **🍯 Sticky style** / quick-style tags.

The local enhancer prefix is exactly:

```text
score_9, score_8_up, score_7_up, source_cartoon, masterpiece, best quality, vibrant colors, full color, 
```

If the prompt already starts with `score_` or `masterpiece`, it is returned unchanged. If the prompt is **≤ 6 words**, it appends:

```text
, detailed illustration, cinematic lighting, sharp focus, 8k, highly detailed
```

This is the “Mini App style” deterministic enhancer — no API key required.

---

## 4. Script mode: the complete protocol

### 4.1 Request object (`GenerationConfig`)

| Field | Type | Default | Meaning |
|---|---|---|---|
| `prompt` | string | — | Positive prompt. |
| `negative_prompt` | string | `""` | What to avoid. |
| `steps` | int | `28` | 1–100 in the UI. |
| `width` | int | `832` | Parsed from the size preset. |
| `height` | int | `1216` | Parsed from the size preset. |
| `seed` | int | `-1` | `-1` = random; `>=0` = deterministic. |
| `guidance_scale` | float | `6.5` | 0–20 in the UI. |
| `batch` | int | `1` | 1–20 in the dialog. |
| `init_b64` | string | `""` | Base64 JPEG for img2img “edit last”. |
| `denoise` | float | `0.75` | img2img strength; tool default `0.7`. |

### 4.2 Step A — validate credentials

```
GET https://www.kaggle.com/api/v1/datasets/list?user=<username>&page=1
Authorization: Basic base64(username:key)
User-Agent: Cellium/1.0
```

| Response | Meaning | UI message |
|---|---|---|
| `200` | valid | `✅ Connected! GPU quota available.` |
| `401` | bad key/user | `❌ Invalid Kaggle username or API key` |
| `403` | connected but no GPU quota | `⚠️ Connected but no GPU quota (verify phone on Kaggle)` |
| other | unexpected | `❌ Unexpected: <code>` |

The settings test runs this on a background thread and emits a Qt signal back to the UI. Android: do it in a coroutine and update a `StateFlow`.

### 4.3 Step B — make sure no previous job is active

Before pushing, the backend asks for the status of `cloud-render-w1`:

```
POST https://www.kaggle.com/api/v1/kernels/status
Content-Type: application/json

{"userName": "<username>", "kernelSlug": "cloud-render-w1"}
```

If the status is `queued` or `running`, it waits (5 s poll, up to 15 min) so two jobs never fight over the same kernel slug. If the user cancels, it raises `cancelled`.

### 4.4 Step C — push the kernel

```
POST https://www.kaggle.com/api/v1/kernels/push
Content-Type: application/json
```

Exact payload:

```json
{
  "slug": "<username>/cloud-render-w1",
  "newTitle": "Cloud Render W1",
  "text": "<the generated Python script>",
  "language": "python",
  "kernelType": "script",
  "isPrivate": true,
  "enableGpu": true,
  "enableInternet": true,
  "datasetDataSources": ["<username>/<optional-cache-dataset-slug>"],
  "competitionDataSources": [],
  "kernelDataSources": [],
  "modelDataSources": [],
  "categoryIds": [],
  "sessionTimeoutSeconds": 2700
}
```

- `kernelType: "script"` → the VM **self-terminates when the script exits**, so GPU billing stops immediately.
- `isPrivate: true` → only the owner can see the code/output.
- `enableInternet: true` → needed for pip + HuggingFace/Civitai downloads.
- `datasetDataSources` is empty unless a healthy Phase-5 cache exists.
- `sessionTimeoutSeconds: 2700` = hard 45-min cap. A hung script cannot burn the whole weekly quota.

**Retries:** on `429`, exponential backoff `1 s → 2 s → 4 s`, max 3 attempts. On other request exceptions, retry with `2^attempt` seconds, then raise `push_failed`.

**Kernel rename landmine:** Kaggle may not honour the requested slug/title (it can mint its own). Always parse the push response:

```json
{"ref": "<username>/<actual-slug>", "refNullable": "..."}
```

Use the **returned** slug for every later status/log/output poll. The PC `_push_kernel()` currently hardcodes `cloud-render-w1`; the cache builder and warm-cache code parse `ref`. For the Android port, **always parse `ref`** — it is the robust behaviour.

### 4.5 Step D — poll status

```
POST https://www.kaggle.com/api/v1/kernels/status
{"userName": "<username>", "kernelSlug": "<actual-slug>"}
```

The backend POSTs first; if the server returns `404` or `405`, it retries the same call as `GET` with query params (older public REST style).

Status vocabulary → normalized state:

| Kaggle status (lowercased) | Normalized | Meaning |
|---|---|---|
| `queued`, `new_script` | `queued` | Waiting for a GPU. |
| `running` | `running` | Booting CUDA / loading model / sampling. |
| `complete` | `complete` | Script exited successfully. |
| `error` | `error` | Script failed. |
| `cancel_requested`, `cancel_acknowledged` | `cancelled` | Cancelled. |
| anything else | `unknown` | Keep polling; log it. |

**Poll interval:** 5 s.
**Timeout:** `max(900, batch * 90 + 360)` seconds.

| Batch | Timeout |
|---|---|
| 1 | 900 s (15 min) |
| 4 | 900 s |
| 10 | 1260 s (21 min) |
| 20 | 2160 s (36 min) |

**Live progress:** every 30 s while `running`, the app fetches the kernel log tail and uses the last meaningful line as the status detail. If the log is empty, it estimates:

- first 60 s: `Booting GPU & loading model...`
- after that: `Sampling steps (~N%)` or `Rendering X/Y (~N%)`
- estimated per-image time: `max(30, steps * 2.2)` seconds.

**Failure:** read `failureMessage` from the status response, append the last ~1800 chars of the kernel log, and map:

- contains `quota`, `accelerator`, or (`gpu` + `quota`) → `quota` (weekly 30 h cap; resets Monday)
- status was cancelled → `cancelled`
- otherwise → `kaggle_error` with the log tail.

### 4.6 Step E — fetch outputs

```
POST https://www.kaggle.com/api/v1/kernels/output
{"userName": "<username>", "kernelSlug": "<actual-slug>", "pageSize": 100}
```

Response:

```json
{
  "files": [
    {"fileName": "out.jpg", "url": "https://..."},
    {"fileName": "meta.json", "url": "https://..."}
  ],
  "log": "...",
  "nextPageToken": "..."
}
```

- Paginate while `nextPageToken` / `next_page_token` is present.
- Accept `fileName` or `file_name`.
- Image filter: `^out(_\d+)?\.(jpg|jpeg|png)$` — the kernel writes `out.jpg` for batch 1 and `out_01.jpg … out_20.jpg` for batches.
- Sort by filename; download each `url` (no auth needed; signed URL).
- If `meta.json` exists, save it next to the first image and parse `{"seeds": [...], "seconds": N}`.
- If the response is **not** `application/json`, treat the whole body as one raw image (binary fallback).

**Local naming:**

```
<output_dir>/kaggle_<YYYYMMDD_HHMMSS>_<safe_prompt>[_NN].<ext>
<output_dir>/kaggle_<...>.meta.json
```

`safe_prompt` = first 50 chars of the prompt, then only alphanumerics / space / `-` / `_`, truncated to 40.

**Default output dir:** `<UserData>/generated_images` (Android: app-specific Pictures dir, then publish to MediaStore).

### 4.7 Step F — stealth wipe (optional, default ON)

After a successful download, the backend pushes a **CPU-only** script to the same slug:

```python
import os, shutil
print('[stealth] Sanitizing cloud session...')
w = '/kaggle/working'
if os.path.exists(w):
    for f in os.listdir(w):
        p = os.path.join(w, f)
        try:
            if os.path.isfile(p) or os.path.islink(p):
                os.remove(p)
            elif os.path.isdir(p):
                shutil.rmtree(p)
        except Exception:
            pass
print('[stealth] Cloud traces cleared.')
```

Payload differences: `enableGpu: false`, `enableInternet: false`, no dataset sources. It overwrites the notebook code and empties the output tab, leaving no prompt/image trace on Kaggle.

> ⚠️ **Race caveat:** the wipe uses the same kernel slug. On the PC it runs asynchronously after the download. For Android, do it **after** the image is safely saved and **before** allowing the next job to push to the same slug — or make it a serialized step. If you fire a new render immediately, the wipe push can replace the new kernel.

### 4.8 Result object

```python
GenerationResult(
    image_path = Path,      # first image
    seed       = int,       # first seed
    elapsed_seconds = float,# from meta.json if present, else wall clock
    paths      = [Path, ...],
    seeds      = [int, ...],
)
```

### 4.9 Observed timing (from live runs)

| Scenario | Time |
|---|---|
| HF DreamShaper cold (pip + model download + load) | ~2–4 min |
| Civitai 7 GB cold (download + load) | ~5–8 min |
| Mounted Phase-5 cache (no download) | much faster; model load still dominates |
| Warm-cache v3, model already in VRAM | **6–9 s per 512×512 image** (8 steps) |
| Warm-cache watcher cold start (HF DreamShaper) | **~165 s** |
| Warm-cache watcher cold start (7.1 GB Civitai mount) | **~11–12 min** (hence the 900 s warm deadline) |
| Kaggle queue wait | up to a few minutes; normal |

---

## 5. The kernel script (what actually runs on Kaggle)

### 5.1 Base template

The backend builds the script by `str.replace` on `__CFG_JSON__` and `__MODEL_LOADER__`. **Never use `str.format`** — the generated code contains braces/dicts. Every user string is embedded with `repr()`, so a prompt/token/URL can never break out of its string literal.

```python
import json, time, subprocess, sys
try:
    sys.stdout.reconfigure(line_buffering=True, write_through=True)
    sys.stderr.reconfigure(line_buffering=True, write_through=True)
except Exception:
    pass

def klog(*a):
    print("[render]", *a, flush=True)

t0 = time.time()
klog("Initializing cloud render environment...")
subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
    "diffusers>=0.34", "transformers>=4.41,<5", "accelerate", "safetensors"])
klog("Dependencies verified and ready.")

import torch
from diffusers import StableDiffusionXLPipeline

CFG = json.loads(__CFG_JSON__)   # prompt, neg, steps, w, h, seed, guidance
klog(f"Config loaded (steps: {CFG.get('steps')}, size: {CFG.get('w')}x{CFG.get('h')}, batch: {CFG.get('batch')})")

__MODEL_LOADER__

# fp16 SDXL VAE safety: upcast VAE math to avoid black/pink outputs.
try:
    pipe.vae.config.force_upcast = True
except Exception:
    pass
try:
    pipe.enable_vae_slicing()
    pipe.enable_vae_tiling()
except Exception:
    pass

device = "cuda" if torch.cuda.is_available() else "cpu"
klog(f"Targeting device: {device}")
if device == "cuda":
    pipe = pipe.to("cuda")
else:
    pipe.enable_model_cpu_offload()

# Optional img2img: edit the previous image (base64 JPEG embedded in CFG)
active_pipe = pipe
init_image = None
if CFG.get("init_b64"):
    import base64, io as _io
    from PIL import Image as _PILImage
    from diffusers import StableDiffusionXLImg2ImgPipeline
    init_image = _PILImage.open(_io.BytesIO(base64.b64decode(CFG["init_b64"]))).convert("RGB")
    active_pipe = StableDiffusionXLImg2ImgPipeline(**pipe.components)
    if device == "cuda":
        active_pipe = active_pipe.to("cuda")
    else:
        active_pipe.enable_model_cpu_offload()
    klog("img2img mode active, strength", CFG.get("denoise", 0.75))

batch = max(1, int(CFG.get("batch", 1)))
seeds = []
total_steps = int(CFG.get("steps", 28))

for i in range(batch):
    seed = (CFG["seed"] + i) if CFG["seed"] >= 0 else (int(time.time() * 1000) + i) % (2**32)
    klog(f"Starting image {i+1}/{batch} (seed: {seed})...")

    def _step_cb(p, s_idx, ts, cb_kwargs):
        step_num = s_idx + 1
        if step_num % 2 == 0 or step_num == total_steps or step_num == 1:
            klog(f"Step {step_num}/{total_steps} [img {i+1}/{batch}]")
        return cb_kwargs

    kwargs = dict(
        prompt=CFG["prompt"],
        negative_prompt=CFG.get("neg", ""),
        num_inference_steps=total_steps,
        guidance_scale=CFG.get("guidance", 6.5),
        generator=torch.Generator(device).manual_seed(seed),
        callback_on_step_end=_step_cb,
    )
    if init_image is not None:
        kwargs["image"] = init_image
        kwargs["strength"] = CFG.get("denoise", 0.75)
    else:
        kwargs["width"] = CFG["w"]
        kwargs["height"] = CFG["h"]
    img = active_pipe(**kwargs).images[0]
    name = "out.jpg" if batch == 1 else f"out_{i+1:02d}.jpg"
    img.convert("RGB").save(f"/kaggle/working/{name}", "JPEG", quality=88, optimize=True)
    seeds.append(seed)
    klog(f"Saved {name} ({i+1}/{batch}) [88% quality JPEG]")

json.dump({"seeds": seeds, "seconds": round(time.time() - t0, 1)},
          open("/kaggle/working/meta.json", "w"))
klog("ALLDONE", seeds)
```

### 5.2 CFG payload

```json
{
  "prompt": "...",
  "neg": "...",
  "steps": 28,
  "w": 832,
  "h": 1216,
  "seed": -1,
  "guidance": 6.5,
  "batch": 1,
  "init_b64": "",
  "denoise": 0.75,
  "dataset_slug": "",
  "model": "lykon/dreamshaper-xl-v2-turbo",
  "civitai_url": "",
  "lora_url": "",
  "lora_strength": 0.9
}
```

It is serialized with `json.dumps(..., ensure_ascii=False)`, then `repr()`-ed into the Python source, so the generated line is:

```python
CFG = json.loads('{"prompt": "...", ...}')
```

### 5.3 HuggingFace loader

```python
klog('Loading HuggingFace model <repo>...')
pipe = StableDiffusionXLPipeline.from_pretrained(
    '<repo>', torch_dtype=torch.float16,
    token='<optional-hf-token>',)
klog('HuggingFace model loaded.')
```

- `token` is omitted entirely when empty.
- Public repos need no token. Gated repos need one.

### 5.4 Civitai loader (with mount + resolver)

```python
import requests, re
TOK = None  # the builder writes repr(token) here when a token exists

def _cv_headers():
    return {"Authorization": "Bearer " + TOK} if TOK else {}

def _cv_resolve(url):
    # A VERSION id ('/api/download/models/<id>') is served as-is - that is
    # the safe form. A MODEL id ('/models/<id>') serves the page's LATEST
    # file, which can be a completely different checkpoint, so it has to
    # be resolved through the Civitai API first.
    if re.search(r'civitai.com/api/download/models/[0-9]+', url or ''):
        return url
    m = re.search(r'civitai.com/models/([0-9]+)', url or '')
    if not m:
        return url
    mid = m.group(1)
    direct = 'https://civitai.com/api/download/models/' + mid
    try:
        r = requests.get('https://civitai.com/api/v1/models/' + mid,
                         headers=_cv_headers(), timeout=20)
        r.raise_for_status()
        vers = (r.json() or {}).get('modelVersions', []) or []
        def good(v):
            b = (v.get('baseModel') or '').upper()
            n = (v.get('name') or '').lower()
            return ('SDXL' in b or 'ILLUSTRIOUS' in b) and 'inpaint' not in n
        pick = next((v for v in vers if good(v)), None)
        if pick is None:
            pick = next((v for v in vers if 'inpaint' not in (v.get('name') or '').lower()), None)
        if pick is None and vers:
            pick = vers[0]
        if pick is not None:
            for f in (pick.get('files') or []):
                if (f.get('name') or '').lower().endswith('.safetensors'):
                    return f.get('downloadUrl') or f.get('url') or direct
            if pick.get('id'):
                return 'https://civitai.com/api/download/models/' + str(pick['id'])
    except Exception as e:
        print('Civitai API resolve failed, using direct download:', e)
    return direct

import glob as _glob
_slug = CFG.get('dataset_slug') or ''
# Kaggle mounts datasets under /kaggle/input/datasets/<owner>/<slug>/...
# or /kaggle/input/<slug>/... - search by slug so both layouts work.
_mounted = []
if _slug:
    _cands = [p for p in _glob.glob('/kaggle/input/**/*.safetensors', recursive=True)
              if _slug in p and 'lora' not in p.lower()]
    if _cands:
        _mounted = _cands
if _mounted:
    MODEL_PATH = _mounted[0]
    klog('⚡ Loaded model from mounted cloud cache:', MODEL_PATH)
else:
    URL = _cv_resolve(CFG["civitai_url"])
    klog('Civitai resolved ->', URL[:120])
    r = requests.get(URL, headers=_cv_headers(), stream=True, timeout=300)
    r.raise_for_status()
    _dl_total = 0
    with open("/kaggle/working/model.safetensors", "wb") as f:
        for chunk in r.iter_content(1 << 22):
            f.write(chunk)
            _dl_total += len(chunk)
            if _dl_total % (200 * 1024 * 1024) < len(chunk):
                klog(f'Downloading model: {_dl_total // (1024*1024)} MB')
    klog('Model downloaded successfully.')
    MODEL_PATH = '/kaggle/working/model.safetensors'
klog('Loading SDXL pipeline from safetensors...')
pipe = StableDiffusionXLPipeline.from_single_file(
    MODEL_PATH, torch_dtype=torch.float16)
klog('SDXL pipeline loaded into memory.')
```

### 5.5 Optional LoRA

```python
# ── Optional LoRA - mounted cache first, download only as a fallback ──
if CFG.get("lora_url"):
    try:
        import glob as _lg
        _sl = CFG.get('dataset_slug') or ''
        _lm = [p for p in _lg.glob('/kaggle/input/**/lora.safetensors', recursive=True)
               if _sl and _sl in p] if _sl else []
        if _lm:
            _lora_path = _lm[0]
            print("LoRA from mounted cloud cache:", _lora_path)
        else:
            import requests
            headers = {}  # builder writes {"Authorization": "Bearer " + repr(token)} when set
            r = requests.get(CFG["lora_url"], headers=headers, stream=True, timeout=180)
            r.raise_for_status()
            with open("/kaggle/working/lora.safetensors", "wb") as f:
                for chunk in r.iter_content(1 << 22):
                    f.write(chunk)
            _lora_path = "/kaggle/working/lora.safetensors"
        pipe.load_lora_weights(_lora_path)
        _names = set()
        try:
            for _v in pipe.get_list_adapters().values():
                _names.update(_v)
        except Exception:
            pass
        if not _names:
            try:
                pipe.unload_lora_weights()
            except Exception:
                pass
            print("LoRA registered ZERO adapters (arch mismatch) - unloaded")
        else:
            _names = sorted(_names)
            pipe.set_adapters(_names, adapter_weights=[CFG.get('lora_strength', 0.9)] * len(_names))
            print("LoRA applied", _names)
    except Exception as e:
        print("LoRA skipped (download/load failed):", e)
```

> **Why the adapter check matters:** a LoRA with the wrong architecture can register **zero adapters** and silently do nothing (or break the pipeline). The kernel verifies `get_list_adapters()`; if empty, it unloads the LoRA and keeps the render. This is why a failed LoRA is never fatal.

### 5.6 Dependency pins (do not “modernize” blindly)

- `diffusers>=0.34` (render template); the watcher uses `diffusers>=0.34,<0.35`.
- `transformers>=4.41,<5` — Kaggle’s Python 3.13 + `transformers` 5 broke with `FLAX_WEIGHTS_NAME` ImportError.
- `accelerate`, `safetensors`.
- If you change these, re-run a live smoke test; a green build is not proof.

---

## 6. All the image features (“the image stuff”)

### 6.1 Entry points

| Surface | How it triggers |
|---|---|
| 🎨 button in the chat input pill | Opens `ImagineDialog`. |
| `/imagine <prompt>` | Intercepted before the LLM; renders with settings defaults. |
| `/imagine-start-cache` | Starts the warm-cache v3 watcher (GPU, ≤ 1 h). |
| `/imagine-stop-cache` | Sends the shutdown pill. |
| Ctrl+K command palette | “🎨 Generate image (Kaggle)”. |
| AI tool `generate_image` | Only when **⋯ More → 🎨 Enable Image Gen** is ON. |
| Welcome chip “🎨 Generate an image” | Opens the dialog. |

### 6.2 Imagine dialog — Simple vs Advanced

**Simple (default):**

- ✨ Prompt
- 🍯 Sticky style + quick-style dropdown
- 🖼 Resolution
- 🔢 Images (batch 1–20)
- Cancel / 🎨 Generate

**Advanced:**

- 🤖 Model engine (4 presets)
- ✨ Prompt enhancer (Model Hub list or “Local tags (offline)”)
- 🚫 Negative prompt
- ⚙️ Steps (1–100), Guidance (0–20), Seed (-1…2147483647) + “Random each time”
- Everything from Simple

**Persistence keys** (written on close/generate):

```
kaggle_prompt
kaggle_sticky_prompt
kaggle_negative_prompt
kaggle_steps
kaggle_guidance
kaggle_size
kaggle_batch
kaggle_preset
kaggle_dialog_mode   # "simple" | "advanced"
```

**Generate params emitted to the main window:**

```json
{
  "prompt": "<main>, <sticky>",
  "negative_prompt": "...",
  "steps": 28,
  "size": "832x1216 (9:16)",
  "guidance": 6.5,
  "seed": -1,
  "preset": "✨ DreamShaper XL Turbo v2 (fast, public HF)",
  "batch": 1,
  "sticky_prompt": "...",
  "mode": "simple"
}
```

### 6.3 Prompt model: Prompt + Sticky + Quick Styles

- **Prompt** = the main subject. Remembered between sessions.
- **Sticky style** = persistent quality/style suffix, appended to **every** render.
- **Negative** = what to avoid, remembered.
- **Quick style** = appends a tag block to the sticky prompt (never replaces it), then resets the dropdown to “Select”.

Exact style presets:

| Label | Tags appended |
|---|---|
| `✨ Select aesthetic style…` | — |
| `🌸 Masterpiece Anime (Clean)` | `masterpiece, best quality, ultra-detailed anime aesthetic, expressive eyes, vibrant colors, clean lineart` |
| `📼 Retro 90s Cel Animation (Nostalgic)` | `retro anime aesthetic, 1990s cel animation style, nostalgic color palette, retro anime screengrab, grain texture` |
| `🧸 Chibi Kawaii (Super Cute)` | `chibi style, kawaii aesthetic, rounded soft proportions, pastel palette, super cute, adorable expression` |
| `⚔️ Dark Cinematic Fantasy (Epic)` | `cinematic fantasy, dramatic dark atmosphere, volumetric lighting, hyper-detailed, epic composition, unreal engine render` |
| `🌆 Cyberpunk Neon (Futuristic)` | `cyberpunk aesthetic, vibrant neon lighting, reflections, rainy night city, high-tech glow, volumetric haze` |
| `🎨 Soft Watercolor (Dreamy)` | `soft watercolor painting, delicate brushstrokes, watercolor wash, ethereal lighting, gentle pastel tones` |

> The `/imagine` command also appends the sticky prompt. The **AI tool does not** — it passes the prompt exactly as the model wrote it.

### 6.4 Sizes (exact list)

| Size | Aspect | Notes |
|---|---|---|
| `512x512 (1:1)` | 1:1 | Fastest; lower detail. |
| `768x768 (1:1)` | 1:1 | Good speed/quality. |
| `832x1216 (9:16)` | 9:16 | **Default**; SDXL portrait sweet spot. |
| `1216x832 (16:9)` | 16:9 | SDXL landscape sweet spot. |
| `1024x1024 (1:1)` | 1:1 | SDXL square. |
| `896x1152 (3:4)` | 3:4 | Portrait. |
| `1152x896 (4:3)` | 4:3 | Landscape. |
| `768x1344 (9:16)` | 9:16 | Taller portrait. |
| `1344x768 (16:9)` | 16:9 | Wider landscape. |
| `1536x640 (21:9)` | 21:9 | Ultrawide; can be out of SDXL’s training distribution. |

Parsing rule: split on `" ("`, then split on `"x"`; fall back to `832x1216`.

### 6.5 Batch (1–20)

- The kernel loops `batch` times.
- Seeds: if `seed >= 0`, each image uses `seed + i`; if `seed == -1`, each uses `(int(time.time()*1000) + i) % 2**32`.
- Output: `out.jpg` for 1, `out_01.jpg … out_20.jpg` for many.
- Timeout scales with batch (see 4.5).
- The chat bubble shows `🎨 <prompt> × N images`.
- The result bubble shows all images in one assistant message with a comma-separated seed list.

### 6.6 Seed semantics

- `-1` = random (the UI has “Random each time” checked by default).
- `>= 0` = reproducible.
- Batch increments the seed per image, so a batch of 4 with seed 100 gives 100, 101, 102, 103.
- The finished image caption shows the seed(s); the gallery/meta JSON stores them.

### 6.7 Negative prompt default

```
worst quality, low quality, ugly, blurry, deformed, bad anatomy, watermark, signature
```

### 6.8 ✨ Enhancer

**Local (offline, deterministic):**

- `enhance_prompt(prompt, "sdxl")`.
- Prepends the quality prefix.
- If ≤ 6 words and not ending in `...`/`…`, appends the detail suffix.
- If it already starts with `score_` or `masterpiece`, returns unchanged.

**LLM enhancer:**

- The dropdown lists every Model Hub model key; the default entry is `✨ Local tags (offline)`.
- One-shot OpenAI-compatible call: `POST <base_url>/chat/completions`, `Authorization: Bearer <key>`.
- System prompt:

  ```text
  You are a prompt engineer for SDXL image generation. Convert the user's
  idea into ONE comma-separated Danbooru-style tag list: style/quality prefix
  (score_9, score_8_up, masterpiece, best quality), subject, hair/eyes/clothes,
  pose, background, lighting, camera framing. Keep every content tag the user
  gave. Output ONLY the tag list - no sentences, no markdown, no numbering.
  ```

- `max_tokens: 700`, `temperature: 0.7`.
- Strips markdown fences if the model adds them.
- Error kinds: `rate_limit` (429), `auth` (401/403), `network`, `empty`.
- UI: busy state with animated dots + elapsed; click while working cancels; 429 auto-retries at **2 s, 4 s, 8 s** (max 3); permanent failure becomes `↻ Retry enhance`; success flashes `✅ Enhanced` for 1.5 s.

### 6.9 img2img “edit last image”

- Triggered by the AI tool’s `edit_last: true` (e.g. *“put a clown face on the cat”*).
- The last generated image is downscaled so its longest side is **1024 px**, JPEG quality **85**, base64 (ASCII).
- The kernel builds `StableDiffusionXLImg2ImgPipeline(**pipe.components)` from the already-loaded pipeline.
- `strength` = `denoise`; backend default `0.75`, tool default `0.7`; UI schema range 0.4–0.9.
- The init image is embedded in `CFG["init_b64"]`; the same model/LoRA is reused.
- Output is a normal `out.jpg`; the result replaces the chat image and updates `hub.last_image`.

> **Implemented nuance:** `hub.last_image` is set by the **tool** after each `generate_image` call. Images generated through the dialog are tracked separately (`_last_generated_image_to_append`) for auto-attachment to the next user message, but they do **not** automatically become the tool’s img2img source. For Android parity, either reproduce this exactly or improve it by setting the “last image” pointer from **every** successful render — document which you choose.

### 6.10 AI tool: `generate_image`

Registered only when `image_gen_enabled` is true (`ai_workers.py`), so the tool is **never sent** to the model when off (smaller context).

**Description (exact intent):**

> Generate an image on the cloud GPU (Kaggle) from a text prompt. Use it whenever the user asks to draw/generate/create an image, or to EDIT the last generated image: set `edit_last=true` and describe the change (e.g. ‘put a clown face on it’, ‘make the background night’). `edit_last=false` always creates a brand-new image. Returns the saved file path and seed; the image is shown in the chat automatically.

**JSON schema:**

```json
{
  "type": "object",
  "properties": {
    "prompt": {"type": "string", "description": "Detailed image prompt (danbooru-style tags work great)"},
    "negative_prompt": {"type": "string", "description": "What to avoid", "default": ""},
    "edit_last": {"type": "boolean", "description": "true = modify the last generated image (img2img)", "default": false},
    "denoise": {"type": "number", "description": "img2img strength 0.4-0.9 (only when edit_last)", "default": 0.7},
    "steps": {"type": "integer", "default": 28},
    "width": {"type": "integer", "default": 832},
    "height": {"type": "integer", "default": 1216},
    "seed": {"type": "integer", "default": -1, "description": "-1 = random"}
  },
  "required": ["prompt"]
}
```

**Execution:**

1. Get the backend from `hub.backend_factory`; if none, return “Kaggle not configured”.
2. Apply the active preset via `build_model_config`.
3. Defaults: negative from settings; steps from settings; size from `kaggle_size`; guidance from `kaggle_guidance`.
4. If `edit_last` and a last image exists, encode it to `init_b64`.
5. Call `backend.generate(..., batch=1, init_b64=..., denoise=...)`.
6. Update `hub.last_image`; emit `image_ready(path, seed, prompt)`; return a text result like:

   ```text
   OK: generated new image. Saved to <path> (seed <n>, <s>s). The image is displayed in the chat.
   ```

The agent system prompt includes a hard rule:

> CRITICAL: When the user asks to draw, generate, or create an image, you MUST output a tool call … NEVER fake, hallucinate, or pretend you generated an image in text (NEVER write ‘🎨 Generated: … Seed: …’ yourself). Always call the real tool!

### 6.11 Progress UI

Stage → icon:

| Stage | Icon | Text |
|---|---|---|
| `checking_status` | 🔍 | checking status |
| `waiting_for_slot` | ⏳ | waiting for slot |
| `pushing` | 📤 | pushing |
| `queued` | ⏳ | queued |
| `running` | 🎨 | running |
| `downloading` | 📥 | downloading |
| `complete` / `done` | ✅ | complete / done |
| `rate_limited` | 🐌 | rate limited |
| `error` | ❌ | red bubble with log tail |

- The status bubble is a **small nameless in-chat bubble**, not a toast.
- Identical heartbeats are throttled to **one per 33 s**; stage changes and new details apply immediately.
- The finished job drops the status bubble and inserts the image bubble + a tiny done line:
  `✅ done in <s>s · seed <seeds> · N images`.

### 6.12 Result rendering & gallery

- The assistant message is added to session memory with:

  ```json
  {
    "role": "assistant",
    "content": "🎨 **Generated:** <prompt>\n\n*Seed: <seeds>*",
    "time": "HH:MM",
    "model": "Kaggle (SDXL)",
    "attached_images": ["<path1>", "<path2>"]
  }
  ```

- The image bubble displays the images inline; click opens fullscreen (existing chat image viewer).
- The image is saved to the output folder and the gallery.
- The **primary** generated image is auto-attached to the user’s **next** message once (`_last_generated_image_to_append`), so follow-ups can refer to it visually.
- If `incognito` is on, the session is not persisted.

### 6.13 Slash commands

```
/imagine <prompt>
/imagine-start-cache
/imagine-stop-cache
```

The “/” drop-up filters and supports keyboard navigation. `/imagine` appends sticky tags and uses settings defaults.

### 6.14 Errors in chat

Failures appear as a red nameless bubble with a short message (up to 600 chars) and, when available, the kernel log tail. No toast spam.

### 6.15 Settings → 🖼️ Image Generation

**Credentials:**

- Kaggle Username
- Kaggle API Key (masked)
- 📥 Import `kaggle.json` → populates fields, saves, auto-tests
- 🔍 Test Connection → `datasets/list` (200/401/403)

**Model Source:**

- Model Preset (4)
- Model Source: `HuggingFace (public repo)` / `Civitai (single file URL)`
- HF Repo ID, HF Token (masked, optional)
- Civitai URL, Civitai Token (masked, optional)
- LoRA URL, LoRA Strength (0.1–2.0, step 0.05)

**Generation Defaults:**

- Steps (1–100)
- Default Size
- Guidance Scale (0–20)
- Default Negative Prompt
- Output Folder + Browse + Open

**Stealth:**

- `🕶️ Stealth Mode: Auto-delete notebook code & images from Kaggle after download` (default ON)

**Enhancer:**

- `Enhancer Model` (Model Hub name; blank = local tags)

**Cloud Model Cache:**

- One row per Civitai/HF preset: status (`…`, `☁️ not cached`, `☁️ cached · 6.71 GB`, `⚠️ empty shell`), `☁️ Cache now`, `🗑`, `🔄 Refresh cache status`.

**Saved keys:**

```
kaggle_username
kaggle_api_key
kaggle_preset
kaggle_model_mode
kaggle_hf_model
kaggle_hf_token
kaggle_civitai_url
kaggle_civitai_token
kaggle_lora_url
kaggle_lora_strength
kaggle_steps
kaggle_size
kaggle_guidance
kaggle_negative_prompt
kaggle_output_dir
kaggle_auto_clean
kaggle_enhancer_model
```

---

## 7. Phase 5 — ☁️ server-side model cache (zero model bytes on the phone)

### 7.1 Why

Downloading a 7 GB Civitai checkpoint on every cold render is slow and, on a metered connection, unacceptable. The cache builder does the download **on Kaggle** and stores the `.safetensors` in a **private Kaggle dataset**. Later renders mount the dataset read-only and skip the download.

**The phone/PC only exchanges JSON (~KB).** No model bytes ever cross the user’s connection.

### 7.2 Naming

```
cellium-cache-<preset-slug>
```

`preset_slug()`:

1. Lowercase.
2. Remove `(...)`.
3. Replace non-alphanumerics with `-`.
4. Drop 1-character parts and duplicate separators.
5. Truncate to 40 chars.
6. Prefix `cellium-cache-`.

Examples:

| Preset | Slug |
|---|---|
| `🎨 Nova Cartoon XL (Civitai)` | `cellium-cache-nova-cartoon-xl` |
| `📸 Juggernaut XL Ragnarok (Civitai)` | `cellium-cache-juggernaut-xl-ragnarok` |

### 7.3 Builder kernel (CPU-only, zero GPU quota)

`push_cache_builder()`:

1. Compute the slug.
2. If the dataset already exists, **delete it first** (because `create/version` is 403 on this key).
3. Push a script kernel:

   ```json
   {
     "slug": "<user>/cellium-cache-builder-<6hex>",
     "newTitle": "Cellium cache builder <6hex>",
     "text": "<builder script>",
     "language": "python",
     "kernelType": "script",
     "isPrivate": true,
     "enableGpu": false,
     "enableInternet": true,
     "datasetDataSources": [],
     "competitionDataSources": [],
     "kernelDataSources": [],
     "modelDataSources": [],
     "categoryIds": [],
     "sessionTimeoutSeconds": 3600
   }
   ```

4. Parse `ref` / `refNullable` to get the real slug.
5. The builder downloads the checkpoint (+ optional LoRA), streams each to a Kaggle **blob**, then creates the dataset with `POST /datasets/create/new`.

**Builder blob flow (exact):**

```
POST /blobs/upload
{
  "type": "DATASET",
  "name": "model.safetensors",
  "contentType": "application/octet-stream",
  "contentLength": <bytes>
}
→ {"token": "...", "createUrl": "https://..."}

PUT <createUrl>
Content-Type: application/octet-stream
Content-Length: <bytes>
<body = file stream>
```

Then:

```json
POST /datasets/create/new
{
  "ownerSlug": "<user>",
  "slug": "cellium-cache-<preset>",
  "title": "Cellium cache <preset>",
  "licenseName": "CC0-1.0",
  "isPrivate": true,
  "files": [{"token": "<blob-token>"}],
  "categoryIds": []
}
```

The builder streams the file (never loads 7 GB into RAM) and logs every 200 MB.

### 7.4 Discovery / health

```
GET /datasets/view/<user>/<slug>
```

- `200` → `totalBytes` reflects real storage.
- `healthy` if `totalBytes >= 1,000,000` (1 MB).
- `< 1 MB` → `⚠️ empty shell`; treat as broken.
- `files: []` in `/datasets/view` is normal — the view endpoint does not list files. Use `GET /datasets/list/<owner>/<slug>` if you need the file list.
- `GET /datasets/list` is unreliable (returns 0 rows on this account). **Use `view` for discovery, not `list`.**

`refresh_cache_map()` probes all Civitai presets concurrently (max 4 workers, 12 s timeout) and returns:

```json
{
  "🎨 Nova Cartoon XL (Civitai)": {
    "slug": "cellium-cache-nova-cartoon-xl",
    "exists": true,
    "healthy": true,
    "bytes": 7105350162,
    "updated": "...",
    "ref": "..."
  }
}
```

### 7.5 Mount + render

- `build_model_config()` / `create_backend_from_settings()` read `kaggle_cache_map` and set `dataset_slug` when healthy.
- `_maybe_mount_cache()` re-probes before every render (cheap JSON GET), so “Cache now” takes effect on the next render without reopening Settings.
- The push payload includes:

  ```json
  "datasetDataSources": ["<user>/cellium-cache-<preset>"]
  ```

- The kernel globs `/kaggle/input/**/*.safetensors`, keeps paths containing the slug and not `lora`, and loads the first. LoRA globs `/kaggle/input/**/lora.safetensors` filtered by the same slug.

### 7.6 Live proof (2026-11-03)

| Step | Result |
|---|---|
| Cache now on Juggernaut XL Ragnarok | CPU-only builder kernel, zero GPU quota |
| Builder download | 7.1 GB streamed to `/kaggle/working/model.safetensors` |
| Dataset write | `henrycarm/cellium-cache-juggernaut-xl-ragnarok` |
| Size read back | **7,105,350,162 bytes** → `healthy: true` |
| Render from mounted cache | `model from mounted cache: /kaggle/input/datasets/henrycarm/cellium-cache-juggernaut-xl-ragnarok/model.safetensors` |
| App receipt | `🖼 IMAGE out_mounted1.jpg seed=7 size=64436 B` (valid 512×512 JPEG) |
| Phone/PC traffic | JSON only — **0 model bytes** |

### 7.7 Cache landmines

| Landmine | What happens | Fix |
|---|---|---|
| `POST /datasets/create/version` | `403 Permission 'datasets.update' was denied` | One dataset per preset; re-cache = delete → create. |
| `GET /datasets/list` | Often returns 0 rows | Use `/datasets/view/<user>/<slug>`. |
| `files: []` in `/datasets/view` | No file list | Use `/datasets/list/<owner>/<slug>` if needed. |
| Mount path | Kaggle mounts at `/kaggle/input/datasets/<owner>/<slug>/…`, not `/kaggle/input/<slug>/` | Glob `/kaggle/input/**` and filter by slug. |
| Dataset title/slug clash | `409` / create fails | Delete first; use deterministic slug. |
| Builder kernel title clash | Kaggle may rename | Parse `ref`. |

---

## 8. Warm-cache v3 — the ntfy relay (optional turbo)

### 8.1 Why a relay

Kaggle’s public API **cannot inject prompts into a running kernel**. A persistent notebook therefore cannot be fed new prompts through Kaggle itself. The app uses `ntfy.sh` (free, zero-account pub/sub) as a mailbox:

- App → `cmd` topic → watcher.
- Watcher → `res` topic → app.

The watcher loads the model **once** into VRAM and renders each job in **6–9 s**.

### 8.2 Topics

```
cellium-<12 hex>-cmd
cellium-<12 hex>-res
```

- Random, unguessable, no auth.
- One relay per warm session; the app and the pushed watcher must use the **same** topics. (The old bug minted a second relay inside the worker, so both sides listened on different topics.)

### 8.3 App → watcher

```
POST https://ntfy.sh/<cmd-topic>
body: {"jobs": [ {...}, {...} ], "ts": 1234567890.0}
```

- **Plain-text body** (`data=...`), **not** `Content-Type: application/json`. ntfy parses a JSON content type as its own message struct and drops unknown fields — the publish returns 200 but the watcher receives an empty message.
- The watcher unwraps `msg["jobs"]`; treating every envelope as one job made `job.get("id")` `None` and silently dropped the whole batch.
- `?since=all` on the watcher SSE subscription replays the topic cache, so jobs queued while the model was still loading are not lost.
- The watcher also has `started_ids` + `done_ids` guards so a replayed batch cannot render twice.

**Job shape:**

```json
{
  "id": "<epoch_ms>_<i>",
  "prompt": "...",
  "neg": "...",
  "steps": 28,
  "w": 832,
  "h": 1216,
  "seed": -1,
  "guidance": 6.5,
  "init_b64": "",
  "denoise": 0.7
}
```

### 8.4 Watcher → app

1. Metadata message (plain text JSON):

   ```json
   {
     "type": "result",
     "id": "<job-id>",
     "seed": 1234,
     "prompt": "...",
     "name": "out_<job-id>.jpg",
     "seconds": 7.2
   }
   ```

2. **Raw JPEG attachment** immediately after:

   ```
   POST https://ntfy.sh/<res-topic>
   Filename: out_<job-id>.jpg
   Content-Type: image/jpeg
   <raw JPEG bytes>
   ```

- ntfy **replaces the body** of an upload with “You received a file: …” and drops extra form fields. That is why metadata travels as its own message and the app pairs the two **FIFO** (with a 2-minute staleness cutoff).
- The attachment must be a **raw body + `Filename` header**. A multipart body is stored verbatim (boundary + MIME headers + file + closing boundary), producing corrupt `.jpg` files. The app also sanitizes bytes by finding `FF D8 FF` … `FF D9`.

### 8.5 Heartbeat + lifecycle

- Watcher posts a heartbeat every **25 s**:

  ```json
  {"type": "heartbeat", "uptime_s": 42, "done_count": 3, "vram_mb": 0}
  ```

- The app marks the cache `ready` on the first heartbeat, then **republishes pending jobs once** (the watcher may have subscribed after the app published).
- Hard cap: **3600 s**; idle stop: **600 s**. The watcher self-kills with `os._exit(0)`.
- The app pushes the watcher as a **script** kernel, private, GPU, internet, `sessionTimeoutSeconds: 3600`, with a **unique title/slug per start** (`cellium-warm-cache-<6hex>`); if Kaggle returns `409` (“title already in use”), it retries once with a new tag.
- Warm deadline: **900 s**. A 7.1 GB Civitai mount + parse can take ~11–12 min; if it doesn’t warm in 15 min, the app falls back to script mode.
- If the kernel ends/errors or the heartbeat goes stale, pending jobs are **requeued through the normal script path** — images are never lost.

### 8.6 Quota warning

The warm cache **holds a GPU slot for the whole session** (up to 1 h). It is off by default and should show a loud warning. On mobile, default it off; it burns battery and quota.

### 8.7 Commands

```
/imagine-start-cache
/imagine-stop-cache
```

`/imagine-stop-cache` sends `{"action": "shutdown"}` to the cmd topic; the watcher exits, and the hard cap guarantees teardown even if the pill is lost.

### 8.8 Measured results

| Metric | Value |
|---|---|
| Watcher ready (HF DreamShaper, cold) | **164.9 s** |
| Render after warm-up | **6–9 s** per 512×512 image (8 steps) |
| Jobs delivered end-to-end | **3 / 3** |
| Downloaded files | valid 512×512 RGB JPEG, 48–71 KB |
| Regression suite | **112 passed / 0 failed** |
| Phone/PC traffic | JSON only — 0 model bytes |

### 8.9 Warm-cache landmines

| Landmine | What happens | Fix |
|---|---|---|
| `Content-Type: application/json` on ntfy POST | Body dropped | Plain-text `data=...` |
| Batch envelope | `job.get("id")` is `None`; all jobs skipped | Unwrap `msg["jobs"]` |
| No in-flight guard | Replay renders twice | `started_ids` + `done_ids` |
| Jobs queued before watcher subscribes | Early jobs vanish | `?since=all` + `_republish_pending()` on first heartbeat |
| ntfy replaces upload body | Metadata destroyed | Metadata as its own message; pair FIFO |
| Multipart upload | Corrupt `.jpg` | Raw body + `Filename` header |
| Duplicate SSE + poll | Two bubbles/downloads | Dedupe by ntfy message id |
| Same title reused | `409` | Unique tag per start; retry once |

---

## 9. Security, privacy, secrets

1. **BYOK.** Each user’s key stays on their device. Never ship a shared Kaggle key in an APK.
2. **Never log the key.** The PC uses masked `QLineEdit`s and never `dev_log`s the key. Android: never put `Authorization` in Logcat, crash reports, analytics, or error toasts.
3. **Private kernels/datasets.** `isPrivate: true` on every push. The kernel script contains the prompt and possibly a Civitai/HF token — keep it private.
4. **Injection-proof script generation.** Every user value is embedded as a `repr()`-safe literal via `str.replace` on `__TOKEN__` placeholders. Never interpolate raw prompts into Python source with f-strings.
5. **Stealth wipe.** After download, the CPU-only clean script overwrites the kernel code and empties `/kaggle/working`. Default ON. Note the same-slug race (4.7).
6. **ntfy is public.** Topics are unguessable UUIDs but not authenticated. Do **not** put API keys, Kaggle credentials, or private user data in job JSON. Prompts and images are visible to anyone who knows the topic; treat that as acceptable only because the topic is random and short-lived.
7. **Android storage.** Use `EncryptedSharedPreferences` (AES256-GCM master key in the Android Keystore). Exclude the prefs file from backup (`android:allowBackup="false"` or a backup rule). Prefer `MODE_PRIVATE`.
8. **Import via SAF.** Use `ACTION_OPEN_DOCUMENT` for `kaggle.json`; don’t request broad storage permission just to read one file.
9. **Output files.** Save to app-specific storage, then publish to `MediaStore` only when the user asks to keep/share. Use `FileProvider` for sharing; never expose `file://` URIs.
10. **Network.** HTTPS only. Consider certificate pinning to `www.kaggle.com` if the threat model warrants it; at minimum, use the default OkHttp trust chain and no cleartext traffic.

---

## 10. Android port blueprint (the main event)

### 10.1 Decision: native Kotlin, no Python

The entire Kaggle integration is **HTTPS + JSON + a Python script string + a JPEG download**. There is no reason to embed Python, diffusers, or a local GPU stack in the APK.

Recommended stack:

| Concern | Choice |
|---|---|
| Language | Kotlin |
| Async | Coroutines + `StateFlow` |
| HTTP | OkHttp 4.x |
| JSON | kotlinx.serialization (or Moshi) |
| Persistence | Room (job history) + DataStore (settings) |
| Background | WorkManager `CoroutineWorker` + foreground notification |
| Images | Coil (display) + BitmapFactory (decode/downscale) |
| UI | Jetpack Compose + Material 3 |
| Secure storage | `androidx.security:security-crypto` / Keystore |
| Min SDK | 24 (foreground service type APIs guarded by version) |

### 10.2 Module map (Python → Kotlin)

| Python | Responsibility | Kotlin |
|---|---|---|
| `KaggleImageBackend` | auth, push, poll, fetch, wipe | `KaggleApi` + `KaggleRenderer` |
| `ModelConfig` | mode/repo/URL/LoRA/strength/dataset | `ModelConfig` |
| `GenerationConfig` | prompt/neg/steps/size/seed/guidance/batch/init/denoise | `RenderRequest` |
| `GenerationResult` | paths/seeds/elapsed | `RenderResult` |
| `GenerationError` | code/message/detail/recoverable | `KaggleException(code, message)` |
| `KERNEL_TEMPLATE` | Python script | `KernelScriptBuilder` (raw string + replace) |
| `MODEL_PRESETS` | 4 presets | `KagglePresets.all` |
| `enhance_prompt` | local tag expander | `PromptEnhancer.local()` |
| `enhance_with_model` | OpenAI-compatible call | `PromptEnhancer.remote()` |
| `image_to_b64` | downscale + JPEG + base64 | `ImageCodec.toBase64Jpeg()` |
| `KaggleImageWorker` | QThread wrapper | `KaggleRenderWorker` (CoroutineWorker) |
| `KaggleImageBackend._maybe_mount_cache` | cache probe | `ModelCache.refresh()` |
| `model_cache.py` | builder/dataset/blob flow | `ModelCacheBuilder` (optional; PC can build) |
| `kaggle_relay.py` | warm cache | `WarmCacheManager` (optional; v2+) |
| `image_tool.py` | AI tool | `GenerateImageTool` (your agent framework) |
| `ImagineDialog` | UI | `ImagineSheet` (Compose) |
| `_on_kaggle_progress` | status bubble | `RenderState` + `StatusCard` |
| `_send_generated_images` | session memory + bubble | `ChatRepository.addGeneratedImages()` |

### 10.3 Data model (exact JSON)

```kotlin
@Serializable
data class KaggleCredentials(
    val username: String,
    val key: String,
)

@Serializable
enum class KaggleMode { HUGGINGFACE, CIVITAI, CUSTOM }

data class KagglePreset(
    val label: String,
    val mode: KaggleMode,
    val hfModel: String = "",
    val civitaiUrl: String = "",
    val loraUrl: String = "",
    val steps: Int,
    val guidance: Double,
)

object KagglePresets {
    const val DREAMSHAPER = "✨ DreamShaper XL Turbo v2 (fast, public HF)"
    const val NOVA = "🎨 Nova Cartoon XL (Civitai)"
    const val JUGGERNAUT = "📸 Juggernaut XL Ragnarok (Civitai)"
    const val CUSTOM = "🔧 Custom (from Settings)"

    val all = listOf(
        KagglePreset(
            label = DREAMSHAPER,
            mode = KaggleMode.HUGGINGFACE,
            hfModel = "lykon/dreamshaper-xl-v2-turbo",
            steps = 8,
            guidance = 2.0,
        ),
        KagglePreset(
            label = NOVA,
            mode = KaggleMode.CIVITAI,
            civitaiUrl = "https://civitai.com/api/download/models/2329740",
            loraUrl = "https://civitai.com/api/download/models/1524099",
            steps = 33,
            guidance = 7.0,
        ),
        KagglePreset(
            label = JUGGERNAUT,
            mode = KaggleMode.CIVITAI,
            civitaiUrl = "https://civitai.com/api/download/models/1759168",
            steps = 33,
            guidance = 7.0,
        ),
        KagglePreset(
            label = CUSTOM,
            mode = KaggleMode.CUSTOM,
            steps = 28,
            guidance = 6.5,
        ),
    )

    fun byLabel(label: String): KagglePreset =
        all.firstOrNull { it.label == label } ?: all.first()
}

@Serializable
data class ModelConfig(
    val mode: KaggleMode = KaggleMode.HUGGINGFACE,
    val hfModel: String = "lykon/dreamshaper-xl-v2-turbo",
    val hfToken: String = "",
    val civitaiUrl: String = "",
    val civitaiToken: String = "",
    val loraUrl: String = "",
    val loraToken: String = "",
    val loraStrength: Double = 0.9,
    val datasetSlug: String = "",
)

@Serializable
data class RenderRequest(
    val prompt: String,
    val negativePrompt: String = "",
    val steps: Int = 28,
    val width: Int = 832,
    val height: Int = 1216,
    val seed: Long = -1,
    val guidance: Double = 6.5,
    val batch: Int = 1,
    val initB64: String = "",
    val denoise: Double = 0.75,
    val preset: String = KagglePresets.DREAMSHAPER,
    val datasetSlug: String = "",
)

data class RenderResult(
    val files: List<File>,
    val seeds: List<Long>,
    val seconds: Double,
)

class KaggleException(
    val code: String,
    override val message: String,
    val recoverable: Boolean = false,
) : Exception(message)
```

### 10.4 Network client

```kotlin
object KaggleHttp {
    val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
        explicitNulls = false
    }

    val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .callTimeout(0, TimeUnit.SECONDS) // polls/downloads manage their own budgets
        .build()

    val downloadClient: OkHttpClient = client.newBuilder()
        .readTimeout(180, TimeUnit.SECONDS)
        .build()
}
```

**Every request:**

```kotlin
val auth = Credentials.basic(credentials.username, credentials.key)
val request = Request.Builder()
    .url("https://www.kaggle.com/api/v1$path")
    .header("Authorization", auth)
    .header("User-Agent", "Cellium/1.0")
    .apply { if (body != null) post(body.toRequestBody(JSON_MEDIA)) }
    .build()
```

> `Credentials.basic()` is in `okhttp3.Credentials`. `JSON_MEDIA = "application/json; charset=utf-8".toMediaType()`.

### 10.5 API calls (complete)

```kotlin
class KaggleApi(
    private val credentials: KaggleCredentials,
    private val client: OkHttpClient = KaggleHttp.client,
) {
    private val base = "https://www.kaggle.com/api/v1"
    private val auth = Credentials.basic(credentials.username, credentials.key)
    private val jsonMedia = "application/json; charset=utf-8".toMediaType()

    private fun builder(path: String): Request.Builder =
        Request.Builder()
            .url("$base$path")
            .header("Authorization", auth)
            .header("User-Agent", "Cellium/1.0")

    private fun postJson(path: String, body: JsonObject): Response =
        client.newCall(
            builder(path)
                .post(body.toString().toRequestBody(jsonMedia))
                .build()
        ).execute()

    /** Kaggle kernels endpoints: POST camelCase JSON, fall back to GET query. */
    private fun kernelsCall(path: String, body: JsonObject): Response {
        val first = postJson(path, body)
        if (first.code != 404 && first.code != 405) return first
        first.close()
        val query = body.entries.joinToString("&") { (k, v) ->
            "$k=${URLEncoder.encode(v.jsonPrimitive.content, "UTF-8")}"
        }
        return client.newCall(builder("$path?$query").get().build()).execute()
    }

    suspend fun validate(): ValidateResult = withContext(Dispatchers.IO) {
        val url = "$base/datasets/list?user=${URLEncoder.encode(credentials.username, "UTF-8")}&page=1"
        client.newCall(
            Request.Builder().url(url)
                .header("Authorization", auth)
                .header("User-Agent", "Cellium/1.0")
                .get().build()
        ).execute().use { response ->
            when (response.code) {
                200 -> ValidateResult.Valid
                401 -> ValidateResult.Invalid
                403 -> ValidateResult.NoGpuQuota
                else -> ValidateResult.Error(response.code)
            }
        }
    }

    suspend fun pushKernel(script: String, datasetSlug: String = ""): String =
        withContext(Dispatchers.IO) {
            val payload = buildJsonObject {
                put("slug", "${credentials.username}/cloud-render-w1")
                put("newTitle", "Cloud Render W1")
                put("text", script)
                put("language", "python")
                put("kernelType", "script")
                put("isPrivate", true)
                put("enableGpu", true)
                put("enableInternet", true)
                putJsonArray("datasetDataSources") {
                    if (datasetSlug.isNotBlank()) {
                        add("${credentials.username}/$datasetSlug")
                    }
                }
                putJsonArray("competitionDataSources") {}
                putJsonArray("kernelDataSources") {}
                putJsonArray("modelDataSources") {}
                putJsonArray("categoryIds") {}
                put("sessionTimeoutSeconds", 2700)
            }
            var last: Exception? = null
            for (attempt in 0 until 3) {
                try {
                    val response = postJson("/kernels/push", payload)
                    if (response.code == 429) {
                        response.close()
                        delay(1_000L shl attempt) // 1s, 2s, 4s
                        continue
                    }
                    response.use {
                        if (!it.isSuccessful) {
                            throw KaggleException(
                                "push_failed",
                                "HTTP ${it.code}: ${it.body?.string()?.take(180)}"
                            )
                        }
                        val body = it.body?.string().orEmpty()
                        val obj = runCatching {
                            KaggleHttp.json.parseToJsonElement(body).jsonObject
                        }.getOrNull()
                        val ref = obj?.get("ref")?.jsonPrimitive?.contentOrNull
                            ?: obj?.get("refNullable")?.jsonPrimitive?.contentOrNull
                        return@withContext ref
                            ?.trimEnd('/')
                            ?.substringAfterLast('/')
                            ?: "cloud-render-w1"
                    }
                } catch (e: Exception) {
                    last = e
                    delay(1_000L shl attempt)
                }
            }
            throw KaggleException(
                "push_failed",
                "Failed to push kernel: ${last?.message ?: "unknown"}"
            )
        }

    suspend fun status(slug: String): KernelStatus = withContext(Dispatchers.IO) {
        val body = buildJsonObject {
            put("userName", credentials.username)
            put("kernelSlug", slug)
        }
        kernelsCall("/kernels/status", body).use { response ->
            if (response.code == 404) return@withContext KernelStatus(KernelState.NOT_FOUND)
            if (!response.isSuccessful) {
                throw KaggleException("status_failed", "HTTP ${response.code}")
            }
            val obj = KaggleHttp.json
                .parseToJsonElement(response.body?.string().orEmpty())
                .jsonObject
            val raw = obj["status"]?.jsonPrimitive?.contentOrNull?.lowercase() ?: "unknown"
            val failure = obj["failureMessage"]?.jsonPrimitive?.contentOrNull
                ?: obj["failure_message"]?.jsonPrimitive?.contentOrNull
                ?: ""
            KernelStatus(raw.toState(), failure)
        }
    }

    suspend fun output(slug: String, pageToken: String? = null): KernelOutput =
        withContext(Dispatchers.IO) {
            val body = buildJsonObject {
                put("userName", credentials.username)
                put("kernelSlug", slug)
                put("pageSize", 100)
                if (pageToken != null) put("pageToken", pageToken)
            }
            kernelsCall("/kernels/output", body).use { response ->
                if (response.code == 404) {
                    return@withContext KernelOutput(emptyList(), "", null, "")
                }
                if (!response.isSuccessful) {
                    throw KaggleException("output_failed", "HTTP ${response.code}")
                }
                val contentType = response.header("Content-Type").orEmpty()
                if (!contentType.contains("application/json")) {
                    // Binary fallback: one raw image body.
                    return@withContext KernelOutput(
                        files = emptyList(),
                        log = "",
                        nextPageToken = null,
                        binary = response.body?.bytes() ?: ByteArray(0),
                    )
                }
                val obj = KaggleHttp.json
                    .parseToJsonElement(response.body?.string().orEmpty())
                    .jsonObject
                val files = obj["files"]?.jsonArray?.mapNotNull { element ->
                    val f = element.jsonObject
                    val name = f["fileName"]?.jsonPrimitive?.contentOrNull
                        ?: f["file_name"]?.jsonPrimitive?.contentOrNull
                        ?: return@mapNotNull null
                    val url = f["url"]?.jsonPrimitive?.contentOrNull ?: return@mapNotNull null
                    KernelFile(name, url)
                }.orEmpty()
                KernelOutput(
                    files = files,
                    log = obj["log"]?.jsonPrimitive?.contentOrNull.orEmpty(),
                    nextPageToken = obj["nextPageToken"]?.jsonPrimitive?.contentOrNull
                        ?: obj["next_page_token"]?.jsonPrimitive?.contentOrNull,
                    binary = null,
                )
            }
        }

    suspend fun download(url: String, destination: File): File =
        withContext(Dispatchers.IO) {
            val request = Request.Builder().url(url).get().build()
            KaggleHttp.downloadClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    throw KaggleException("download_failed", "HTTP ${response.code}")
                }
                destination.parentFile?.mkdirs()
                response.body?.byteStream()?.use { input ->
                    destination.outputStream().use { output -> input.copyTo(output) }
                } ?: throw KaggleException("download_failed", "Empty body")
                destination
            }
        }
}

data class KernelFile(val name: String, val url: String)

data class KernelOutput(
    val files: List<KernelFile>,
    val log: String,
    val nextPageToken: String?,
    val binary: ByteArray?,
)

data class KernelStatus(val state: KernelState, val failure: String = "")

sealed interface ValidateResult {
    data object Valid : ValidateResult
    data object Invalid : ValidateResult
    data object NoGpuQuota : ValidateResult
    data class Error(val code: Int) : ValidateResult
}

enum class KernelState { QUEUED, RUNNING, COMPLETE, ERROR, CANCELLED, NOT_FOUND, UNKNOWN }

private fun String.toState(): KernelState = when (this) {
    "queued", "new_script" -> KernelState.QUEUED
    "running" -> KernelState.RUNNING
    "complete" -> KernelState.COMPLETE
    "error" -> KernelState.ERROR
    "cancel_requested", "cancel_acknowledged" -> KernelState.CANCELLED
    else -> KernelState.UNKNOWN
}
```

> The `for` loop above retries `429` with 1/2/4 s backoff. A successful push returns the real slug parsed from `ref`/`refNullable`; a failed push throws `push_failed`. Do not swallow a successful response inside a retry loop.

### 10.6 Kernel script builder

Embed the **body** of the template from section 5.1 as a Kotlin raw string (everything between the outer `'''`), with `__CFG_JSON__` and `__MODEL_LOADER__` placeholders. Kotlin raw strings do not treat `\` as an escape, so the Python source stays intact; the template contains no `$`, so Kotlin interpolation will not fire.

```kotlin
object KernelScriptBuilder {
    // KERNEL_BODY and CIVITAI_LOADER are the Python source blocks from 5.1 and 5.4/5.5.

    fun build(request: RenderRequest, model: ModelConfig): String {
        val cfg = buildJsonObject {
            put("prompt", request.prompt)
            put("neg", request.negativePrompt)
            put("steps", request.steps)
            put("w", request.width)
            put("h", request.height)
            put("seed", request.seed)
            put("guidance", request.guidance)
            put("batch", request.batch)
            put("init_b64", request.initB64)
            put("denoise", request.denoise)
            put("dataset_slug", model.datasetSlug)
            put("model", if (model.mode == KaggleMode.HUGGINGFACE) model.hfModel else "")
            put("civitai_url", if (model.mode == KaggleMode.CIVITAI) model.civitaiUrl else "")
            put("lora_url", model.loraUrl)
            put("lora_strength", model.loraStrength)
        }
        val loader = when {
            model.mode == KaggleMode.CIVITAI && model.civitaiUrl.isNotBlank() ->
                civitaiLoader(model)
            else -> huggingFaceLoader(model)
        }
        return KERNEL_BODY
            .replace("__CFG_JSON__", pyRepr(cfg.toString()))
            .replace("__MODEL_LOADER__", loader)
    }

    /** Python repr() of a string: single quotes, escaped backslash/quote/newlines. */
    private fun pyRepr(value: String): String {
        val escaped = value
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        return "'$escaped'"
    }

    private fun huggingFaceLoader(model: ModelConfig): String {
        val token = if (model.hfToken.isBlank()) "" else
            "\n    token=${pyRepr(model.hfToken)},"
        return """
klog('Loading HuggingFace model ${model.hfModel}...')
pipe = StableDiffusionXLPipeline.from_pretrained(
    ${pyRepr(model.hfModel)}, torch_dtype=torch.float16,$token)
klog('HuggingFace model loaded.')
        """.trimIndent()
    }

    private fun civitaiLoader(model: ModelConfig): String =
        CIVITAI_LOADER
            .replace("__TOKEN__", if (model.civitaiToken.isBlank()) "None" else pyRepr(model.civitaiToken))
            .replace("__LORA_TOKEN__", if (model.loraToken.isBlank()) "" else pyRepr(model.loraToken))
}
```

`CIVITAI_LOADER` is the Python block from 5.4 plus the LoRA block from 5.5, with `__TOKEN__` / `__LORA_TOKEN__` placeholders. Keep the `repr()` rule: never interpolate raw user text into Python.

### 10.7 Render orchestration

```kotlin
class KaggleRenderer(
    private val api: KaggleApi,
    private val scriptBuilder: KernelScriptBuilder,
    private val outputDir: File,
    private val onProgress: suspend (RenderStage, String) -> Unit,
) {
    suspend fun render(request: RenderRequest, model: ModelConfig): RenderResult {
        val started = System.currentTimeMillis()

        // 1. Do not fight a previous job on the same kernel.
        val initial = api.status("cloud-render-w1")
        if (initial.state == KernelState.QUEUED || initial.state == KernelState.RUNNING) {
            onProgress(RenderStage.WAITING_FOR_SLOT, "Kaggle job is ${initial.state.name.lowercase()}...")
            waitUntilIdle("cloud-render-w1", 900_000L)
        }

        // 2. Push.
        onProgress(RenderStage.PUSHING, "Pushing job to Kaggle...")
        val script = scriptBuilder.build(request, model)
        val slug = api.pushKernel(script, model.datasetSlug)
        onProgress(RenderStage.QUEUED, "Waiting for GPU...")

        // 3. Poll.
        val timeoutMs = maxOf(900_000L, request.batch * 90_000L + 360_000L)
        val pollStart = System.currentTimeMillis()
        var lastLogFetch = 0L

        while (true) {
            val elapsed = System.currentTimeMillis() - pollStart
            if (elapsed > timeoutMs) {
                throw KaggleException(
                    "timeout",
                    "Generation timed out (${timeoutMs / 60_000} min)",
                    recoverable = true,
                )
            }
            val status = api.status(slug)
            when (status.state) {
                KernelState.COMPLETE -> break
                KernelState.ERROR, KernelState.CANCELLED -> {
                    val tail = runCatching { api.output(slug).log.takeLast(1800) }
                        .getOrDefault("")
                    val combined = (status.failure + "\n--- kernel log tail ---\n" + tail).trim()
                    if (status.state == KernelState.CANCELLED) {
                        throw KaggleException("cancelled", combined.ifBlank { "Cancelled" }, true)
                    }
                    if (combined.contains("quota", true) ||
                        combined.contains("accelerator", true) ||
                        (combined.contains("gpu", true) && combined.contains("quota", true))
                    ) {
                        throw KaggleException(
                            "quota",
                            "Weekly GPU quota exhausted (30h/wk) - resets Monday. Detail: $combined",
                        )
                    }
                    throw KaggleException("kaggle_error", "Kaggle job failed: $combined")
                }
                KernelState.QUEUED ->
                    onProgress(RenderStage.QUEUED, "Waiting for GPU... (${elapsed / 1000}s)")
                KernelState.RUNNING -> {
                    val now = System.currentTimeMillis()
                    if (now - lastLogFetch > 30_000L) {
                        lastLogFetch = now
                        val tail = runCatching { api.output(slug).log }.getOrDefault("")
                        val line = tail.lineSequence()
                            .map { it.trim() }
                            .filter { it.isNotEmpty() && !it.startsWith("{") && !it.startsWith("[{") }
                            .lastOrNull()
                            ?.let { if (it.length > 55) it.take(52) + "..." else it }
                        onProgress(
                            RenderStage.RUNNING,
                            line?.let { "$it (${elapsed / 1000}s)" }
                                ?: "Booting GPU & loading model... (${elapsed / 1000}s)",
                        )
                    }
                }
                KernelState.NOT_FOUND, KernelState.UNKNOWN -> Unit
            }
            delay(5_000L)
        }

        // 4. Download.
        onProgress(RenderStage.DOWNLOADING, "Downloading image(s)...")
        return fetchOutputs(slug, request, started)
    }

    private suspend fun waitUntilIdle(slug: String, timeoutMs: Long) {
        val start = System.currentTimeMillis()
        while (true) {
            if (System.currentTimeMillis() - start > timeoutMs) {
                throw KaggleException("timeout", "Timed out waiting for previous job")
            }
            val s = api.status(slug).state
            if (s != KernelState.QUEUED && s != KernelState.RUNNING) return
            delay(5_000L)
        }
    }

    private suspend fun fetchOutputs(
        slug: String,
        request: RenderRequest,
        started: Long,
    ): RenderResult {
        val all = mutableListOf<KernelFile>()
        var token: String? = null
        var log = ""
        var binary: ByteArray? = null
        do {
            val page = api.output(slug, token)
            all += page.files
            log = page.log.ifBlank { log }
            binary = page.binary ?: binary
            token = page.nextPageToken
        } while (token != null)

        val stamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        val safePrompt = request.prompt
            .filter { it.isLetterOrDigit() || it == ' ' || it == '-' || it == '_' }
            .take(40)
            .ifBlank { "image" }

        val files = mutableListOf<File>()
        val seeds = mutableListOf<Long>()

        if (binary != null && binary.isNotEmpty()) {
            val file = File(outputDir, "kaggle_${stamp}_$safePrompt.jpg")
            file.parentFile?.mkdirs()
            file.writeBytes(binary)
            files += file
        } else {
            val images = all
                .filter { Regex("""^out(_\d+)?\.(jpg|jpeg|png)$""").matches(it.name) }
                .sortedBy { it.name }
            if (images.isEmpty()) {
                throw KaggleException("no_output", "No out*.jpg or out*.png in kernel output")
            }
            images.forEachIndexed { index, entry ->
                val suffix = if (images.size == 1) "" else "_${"%02d".format(index + 1)}"
                val ext = entry.name.substringAfterLast('.', "jpg").lowercase()
                val file = File(outputDir, "kaggle_${stamp}_$safePrompt$suffix.$ext")
                api.download(entry.url, file)
                files += file
            }
            val meta = all.firstOrNull { it.name == "meta.json" }
            if (meta != null) {
                val metaFile = File(outputDir, "kaggle_${stamp}_$safePrompt.meta.json")
                api.download(meta.url, metaFile)
                runCatching {
                    val obj = KaggleHttp.json
                        .parseToJsonElement(metaFile.readText()).jsonObject
                    obj["seeds"]?.jsonArray?.forEach {
                        seeds += it.jsonPrimitive.long
                    }
                }
            }
        }

        return RenderResult(
            files = files,
            seeds = seeds,
            seconds = (System.currentTimeMillis() - started) / 1000.0,
        )
    }
}

enum class RenderStage { CHECKING, WAITING_FOR_SLOT, PUSHING, QUEUED, RUNNING, DOWNLOADING, DONE }
```

### 10.8 WorkManager worker

```kotlin
class KaggleRenderWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val requestJson = inputData.getString(KEY_REQUEST) ?: return Result.failure()
        val request = KaggleHttp.json.decodeFromString<RenderRequest>(requestJson)
        val store = SecureKaggleStore(applicationContext)
        val credentials = store.load() ?: return Result.failure(
            workDataOf(KEY_ERROR to "Kaggle is not configured")
        )
        val settings = SettingsStore(applicationContext)
        val model = settings.modelConfig(request.preset)
        val api = KaggleApi(credentials)
        val renderer = KaggleRenderer(
            api = api,
            scriptBuilder = KernelScriptBuilder,
            outputDir = settings.outputDir(applicationContext),
            onProgress = { stage, detail ->
                setForeground(foregroundInfo(stage, detail))
                setProgress(workDataOf(KEY_STAGE to stage.name, KEY_DETAIL to detail))
            },
        )
        return try {
            val result = renderer.render(request, model)
            val uris = result.files.map { GalleryPublisher.publish(applicationContext, it) }
            Result.success(
                workDataOf(
                    KEY_FILES to result.files.joinToString("|") { it.absolutePath },
                    KEY_URIS to uris.joinToString("|"),
                    KEY_SEEDS to result.seeds.joinToString(","),
                    KEY_SECONDS to result.seconds,
                )
            )
        } catch (e: CancellationException) {
            throw e
        } catch (e: KaggleException) {
            if (e.recoverable) Result.retry() else Result.failure(
                workDataOf(KEY_ERROR to e.message, KEY_CODE to e.code)
            )
        } catch (e: Exception) {
            Result.failure(workDataOf(KEY_ERROR to (e.message ?: "Unknown error")))
        }
    }

    private fun foregroundInfo(stage: RenderStage, detail: String): ForegroundInfo {
        val manager = NotificationManagerCompat.from(applicationContext)
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "Image rendering",
                    NotificationManager.IMPORTANCE_LOW,
                )
            )
        }
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_gallery)
            .setContentTitle("Cellium is rendering")
            .setContentText(detail.ifBlank { stage.name.lowercase() })
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setProgress(0, 0, true)
            .build()
        return if (Build.VERSION.SDK_INT >= 29) {
            ForegroundInfo(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            ForegroundInfo(NOTIFICATION_ID, notification)
        }
    }

    companion object {
        const val KEY_REQUEST = "request"
        const val KEY_STAGE = "stage"
        const val KEY_DETAIL = "detail"
        const val KEY_FILES = "files"
        const val KEY_URIS = "uris"
        const val KEY_SEEDS = "seeds"
        const val KEY_SECONDS = "seconds"
        const val KEY_ERROR = "error"
        const val KEY_CODE = "code"
        const val CHANNEL_ID = "cellium_render"
        const val NOTIFICATION_ID = 4201
        const val WORK_NAME = "kaggle_render"
    }
}
```

Enqueue:

```kotlin
val work = OneTimeWorkRequestBuilder<KaggleRenderWorker>()
    .setInputData(workDataOf(
        KaggleRenderWorker.KEY_REQUEST to KaggleHttp.json.encodeToString(request)
    ))
    .setConstraints(
        Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
    )
    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
    .addTag(KaggleRenderWorker.WORK_NAME)
    .build()

WorkManager.getInstance(context).enqueueUniqueWork(
    KaggleRenderWorker.WORK_NAME,
    ExistingWorkPolicy.KEEP,
    work,
)
```

**Manifest:**

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_DATA_SYNC" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />

<service
    android:name=".image.KaggleRenderWorker$Companion"
    android:foregroundServiceType="dataSync"
    android:exported="false" />
```

> WorkManager’s `CoroutineWorker` already runs in a background executor; the `setForeground` call is what promotes it to a foreground service. On Android 14+, declare the `dataSync` type and request the permission. On Android 13+, request `POST_NOTIFICATIONS` at runtime; if denied, the work still runs but the notification is silent/hidden.

### 10.9 Secure credentials

```kotlin
class SecureKaggleStore(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context,
        "kaggle_secure",
        MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun save(credentials: KaggleCredentials) {
        prefs.edit()
            .putString(KEY_USER, credentials.username)
            .putString(KEY_KEY, credentials.key)
            .apply()
    }

    fun load(): KaggleCredentials? {
        val user = prefs.getString(KEY_USER, null) ?: return null
        val key = prefs.getString(KEY_KEY, null) ?: return null
        if (user.isBlank() || key.isBlank()) return null
        return KaggleCredentials(user, key)
    }

    fun clear() = prefs.edit().clear().apply()

    private companion object {
        const val KEY_USER = "username"
        const val KEY_KEY = "key"
    }
}
```

**Import `kaggle.json`:**

```kotlin
val launcher = rememberLauncherForActivityResult(
    ActivityResultContracts.OpenDocument()
) { uri ->
    uri ?: return@rememberLauncherForActivityResult
    val text = context.contentResolver.openInputStream(uri)
        ?.bufferedReader()?.use { it.readText() } ?: return@rememberLauncherForActivityResult
    val obj = JSONObject(text)
    val user = obj.optString("username").trim()
    val key = obj.optString("key").trim()
    if (user.isNotEmpty() && key.isNotEmpty()) {
        store.save(KaggleCredentials(user, key))
    }
}
launcher.launch(arrayOf("application/json"))
```

### 10.10 Image codec (img2img)

```kotlin
object ImageCodec {
    fun toBase64Jpeg(
        source: File,
        maxSide: Int = 1024,
        quality: Int = 85,
    ): String {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(source.absolutePath, bounds)

        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / sample > maxSide * 2) {
            sample *= 2
        }
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        var bitmap = BitmapFactory.decodeFile(source.absolutePath, options)
            ?: throw IllegalArgumentException("Cannot decode ${source.name}")

        val longest = maxOf(bitmap.width, bitmap.height)
        if (longest > maxSide) {
            val scale = maxSide.toFloat() / longest
            bitmap = Bitmap.createScaledBitmap(
                bitmap,
                (bitmap.width * scale).toInt().coerceAtLeast(1),
                (bitmap.height * scale).toInt().coerceAtLeast(1),
                true,
            )
        }

        val out = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, quality, out)
        bitmap.recycle()
        return Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
    }
}
```

### 10.11 Output storage + gallery

```kotlin
object GalleryPublisher {
    fun publish(context: Context, file: File): Uri {
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, file.name)
            put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
            if (Build.VERSION.SDK_INT >= 29) {
                put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/Cellium")
            }
        }
        val uri = resolver.insert(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            values,
        ) ?: throw IOException("MediaStore insert failed")
        resolver.openOutputStream(uri)?.use { output ->
            file.inputStream().use { input -> input.copyTo(output) }
        } ?: throw IOException("MediaStore open failed")
        return uri
    }
}
```

- Default app output dir: `context.getExternalFilesDir(Environment.DIRECTORY_PICTURES) ?: context.filesDir` + `/Cellium`.
- Keep a Room row per render: prompt, preset, seed(s), file path(s), timestamp, status, error code.
- On Android 10+, `MediaStore` with `RELATIVE_PATH` needs no storage permission. On Android 9 and below, either use app-specific storage + `FileProvider`, or request `WRITE_EXTERNAL_STORAGE` (legacy).

### 10.12 Compose UI map

| PC surface | Compose |
|---|---|
| Imagine glass panel | `ModalBottomSheet` with `GlassCard` background (blur via `RenderEffect` on API 31+, fallback gradient) |
| Simple/Advanced segmented control | `SingleChoiceSegmentedButtonRow` |
| Prompt | `OutlinedTextField` (multiline, 5–6 lines) |
| Sticky style + quick style | `OutlinedTextField` + `ExposedDropdownMenuBox` |
| Model engine | `ExposedDropdownMenuBox` with the 4 labels |
| Enhancer | Dropdown + `✨ Enhance` `FilledTonalButton` with busy/retry states |
| Negative prompt | `OutlinedTextField` |
| Steps/Guidance | `Slider` + numeric label, or `OutlinedTextField` with validation |
| Seed + random | `OutlinedTextField` + `Switch` |
| Size | `ExposedDropdownMenuBox` |
| Batch | `Slider` 1–20 + value label |
| Generate | Gradient `Button` (purple → pink) |
| Progress | `StatusCard` with stage icon, text, elapsed; cancel button |
| Result | `LazyVerticalGrid` of rounded images + seed caption; tap → fullscreen `ZoomableImage` |
| Gallery | `LazyVerticalGrid` + share/save |
| Settings | `SettingsScreen` with sections: Credentials, Model, Defaults, Output, Stealth, Enhancer, Cache |

**UX rules to preserve:**

- Progress is a small in-chat bubble, not a modal spinner.
- Stage changes are immediate; identical heartbeats are throttled (33 s on PC; 5–10 s is fine on mobile).
- The finished image lands inline; the seed is visible.
- Errors are a red bubble/card with a short message, not a crash dialog.
- The “Enable Image Gen” toggle hides the tool from the AI entirely when off.

### 10.13 Settings storage

Use DataStore (Preferences) for non-secret settings:

```
kaggle_preset
kaggle_model_mode
kaggle_hf_model
kaggle_hf_token          # secret → EncryptedSharedPreferences, not DataStore
kaggle_civitai_url
kaggle_civitai_token     # secret
kaggle_lora_url
kaggle_lora_strength
kaggle_steps
kaggle_size
kaggle_guidance
kaggle_negative_prompt
kaggle_output_dir
kaggle_auto_clean
kaggle_enhancer_model
kaggle_prompt
kaggle_sticky_prompt
kaggle_dialog_mode
image_gen_enabled
```

**ModelConfig resolution (parity with `build_model_config`):**

1. Start from settings.
2. If the selected preset is not Custom, override `mode`, `hfModel`, `civitaiUrl`, `loraUrl`.
3. If the selected preset is Custom, keep the manual settings.
4. If the cache map has a healthy slug for the preset, set `datasetSlug`.
5. `loraToken` = the Civitai token (same token).

### 10.14 Warm cache on mobile (optional)

If you port it:

- Use OkHttp `EventSource` (or a raw SSE reader) against `https://ntfy.sh/<res>/sse`.
- Publish jobs with `RequestBody.create("text/plain", json)` — **not** JSON media type.
- Keep a `ConcurrentHashMap<String, Job>` for dedupe (`started`, `done`).
- Pair metadata + attachment FIFO; sanitize JPEG bytes.
- Heartbeat every 25 s → mark ready; republish pending once.
- Foreground service + notification with the cap countdown.
- Default OFF; warn “burns ~1 GPU-hour/hour”.
- On death/stale heartbeat, requeue pending jobs through the script path.

### 10.15 Testing checklist (must pass before claiming parity)

| Test | Expected |
|---|---|
| No credentials | Friendly “not configured”, no crash |
| Bad key | 401 → “Invalid Kaggle username or API key” |
| Unverified phone | 403 → “no GPU quota (verify phone)” |
| `429` on push | Backoff 1/2/4 s, then success or clear error |
| Queued → running → complete | Progress stages update; image downloads |
| `error` status | Red bubble with log tail; no fake image |
| Quota message | Mapped to “Weekly GPU quota exhausted” |
| Timeout | `timeout` error; no infinite spinner |
| No `out.jpg` | `no_output` error; no crash |
| Batch 4 | 4 images, seeds increment, one assistant message |
| Batch 20 | Timeout scales; filenames `out_01…out_20` |
| Seed 1234 | Same image on repeat (same model/settings) |
| img2img | `edit_last` sends base64; output is a valid JPEG |
| Process death mid-render | WorkManager resumes/reports; no duplicate job |
| Airplane mode | Clear network error; retry works |
| Rotation | State survives (ViewModel/StateFlow) |
| Large image | Downscaled to 1024 for img2img; no OOM |
| Stealth ON | Kernel code/output wiped after download |
| Cache healthy | Render mounts dataset; no 7 GB download |
| Warm cache | Ready heartbeat; 6–9 s image; stop pill works |
| Security | No key in Logcat, crash report, or screenshot |

### 10.16 Parity checklist

- [ ] Kaggle username + legacy key, import `kaggle.json`, test connection
- [ ] 4 presets with exact labels, steps, guidance, URLs
- [ ] HF / Civitai / Custom model source + tokens
- [ ] LoRA URL + strength, non-fatal failure
- [ ] 10 sizes, default `832x1216 (9:16)`
- [ ] Steps 1–100, guidance 0–20, seed -1/random, batch 1–20
- [ ] Negative prompt default
- [ ] Prompt + sticky + 6 quick styles
- [ ] Local enhancer + LLM enhancer with retry/cancel
- [ ] img2img “edit last”
- [ ] AI tool `generate_image` with `edit_last`/`denoise`
- [ ] Progress stages + 33 s heartbeat (or mobile equivalent)
- [ ] Inline result + seed + gallery + fullscreen
- [ ] Auto-attach primary image to next message
- [ ] Stealth wipe
- [ ] Cloud model cache status/mount
- [ ] Warm cache (optional)
- [ ] Error catalog + quota mapping
- [ ] Secrets encrypted, never logged

---

## 11. Error catalog

| Code | Cause | User-facing message | Recovery |
|---|---|---|---|
| `invalid_credentials` | 401 | Invalid Kaggle username or API key | Re-import key |
| `no_gpu_quota` | 403 / quota text | Connected but no GPU quota (verify phone) | Verify phone / wait for weekly reset |
| `quota` | `failureMessage` contains quota/accelerator | Weekly GPU quota exhausted (30h/wk) — resets Monday | Wait |
| `push_failed` | Push HTTP error | Failed to push kernel: … | Retry; check key/quota |
| `rate_limited` | 429 | Retrying in Ns… | Auto backoff |
| `queued` | — | Waiting for GPU… | Wait |
| `timeout` | Poll > dynamic timeout | Generation timed out (N min) | Retry; smaller batch |
| `cancelled` | User cancel | Cancelled by user | Retry |
| `kaggle_error` | Script error | Kaggle job failed: … + log tail | Inspect log; model URL/token |
| `no_output` | No `out*.jpg` | No out.jpg in kernel output | Check model load / log |
| `fetch_failed` | Output download failed | Failed to fetch outputs: … | Retry |
| `dataset_create_failed` | Cache create failed | … | Delete/recreate |
| `dataset_version_failed` | 403 `datasets.update` | … | Delete → create |
| `cache_push_failed` | Builder push failed | … | Retry |
| `enhance: rate_limit` | 429 | Rate-limited — retry 1/3 in 2s… | Auto 2/4/8 |
| `enhance: auth` | 401/403 | Check the provider key | Fix key |
| `enhance: network` | Network | … | Retry |
| `enhance: empty` | Empty completion | Enhancer returned empty text | Retry |
| `internal` | Unexpected | … | Report with log |

**Friendly mapping rules from the PC:**

- Quota: `"quota" in low or "accelerator" in low or ("gpu" in low and "quota" in low)`.
- Cancelled: status was `cancelled`.
- Everything else: `Kaggle job failed: <failure>` + `--- kernel log tail ---`.

---

## 12. Constants cheat sheet

| Constant | Value |
|---|---|
| API base | `https://www.kaggle.com/api/v1` |
| Kernel slug | `cloud-render-w1` |
| Kernel title | `Cloud Render W1` |
| Poll interval | `5.0 s` |
| Base timeout | `900 s` (15 min) |
| Dynamic timeout | `max(900, batch * 90 + 360)` s |
| Push retries | `3` |
| Render session cap | `2700 s` (45 min) |
| Builder/watcher cap | `3600 s` (1 h) |
| Warm deadline | `900 s` |
| Watcher idle stop | `600 s` |
| Watcher heartbeat | `25 s` |
| Cache health threshold | `1,000,000 bytes` |
| Cache prefix | `cellium-cache-` |
| Builder prefix | `cellium-cache-builder` |
| Warm kernel slug | `cellium-warm-cache` |
| JPEG quality | `88` |
| img2img max side | `1024 px` |
| img2img JPEG quality | `85` |
| img2img denoise | `0.75` backend / `0.7` tool |
| Batch max | `20` |
| Steps max | `100` |
| Guidance max | `20.0` |
| Seed max | `2147483647` |
| Default size | `832x1216 (9:16)` |
| Default negative | `worst quality, low quality, ugly, blurry, deformed, bad anatomy, watermark, signature` |
| Default preset | `✨ DreamShaper XL Turbo v2 (fast, public HF)` |
| Default steps/guidance | `28` / `6.5` |
| Output filter | `^out(_\d+)?\.(jpg|jpeg|png)$` |
| Status active | `queued`, `running`, `new_script` |
| Status failed | `error`, `cancel_requested`, `cancel_acknowledged` |

---

## 13. Landmines & “do not port blindly”

1. **`new_script`** is a status, not an error. Map it to `queued`.
2. **Kaggle may rename the kernel.** Parse `ref`/`refNullable`; poll the returned slug. The PC script path hardcodes the slug; the mobile port should do better.
3. **Dataset mount path** is `/kaggle/input/datasets/<owner>/<slug>/…`, not `/kaggle/input/<slug>/`. Glob and filter by slug.
4. **Civitai model IDs are traps.** Use version IDs (`/api/download/models/<versionId>`).
5. **`/datasets/view` has `files: []`.** Use `/datasets/list/<owner>/<slug>` for files.
6. **`/datasets/list` is unreliable.** Use `/datasets/view` for discovery.
7. **`datasets/create/version` is 403** on Henny’s key. One dataset per preset; delete → create.
8. **`409` title clash** on warm cache. Unique tag per start; retry once.
9. **ntfy + `Content-Type: application/json`** drops the body. Use plain text.
10. **ntfy multipart** stores the envelope verbatim. Use raw body + `Filename`.
11. **ntfy upload replaces the body.** Metadata must be its own message; pair FIFO.
12. **Batch envelope.** The watcher must unwrap `msg["jobs"]`.
13. **Late subscriber.** Use `?since=all` and republish pending on first heartbeat.
14. **Warm deadline.** 7.1 GB mount can take ~11–12 min; don’t use a 180 s budget.
15. **`/kernels/output` log** is often a JSON-serialized list of events; parse `{"data": ...}`.
16. **Binary fallback** may save a JPEG with a `.png` name. Detect magic bytes (`FF D8 FF`) and name correctly.
17. **`with_suffix(".meta.json")`** on the first image produces `<name>.meta.json`; keep the seed metadata.
18. **Sticky prompt parity.** The dialog and `/imagine` append sticky; the AI tool does not.
19. **Preset steps/guidance parity.** The dialog applies preset values to controls; the request uses the controls/settings. `/imagine` and the tool use settings.
20. **`hub.last_image`** is only set by the tool. Dialog renders are tracked separately for auto-attach. Decide and document your mobile behaviour.
21. **Stealth wipe race.** Same slug; serialize or delay a new push.
22. **`start_warm_cache()` / `stop_warm_cache()`** in `kaggle_image.py` are a **stub** (push a do-nothing notebook). The real warm cache is `kaggle_relay.CacheManager`. Do not port the stub.
23. **`create_dataset()`** raises by design: `create/new` requires ≥1 file. Use `upsert_dataset()` with a real file.
24. **`_queue_read` / `_queue_write`** reference `QUEUE_DATASET`, which is not defined in the current module. They are dead fallback code; do not port.
25. **`delete_dataset()`** uses `POST /dataset/<user>/<slug>/delete` (singular `dataset`), body `{ownerSlug, datasetSlug}`. Do not guess `/datasets/.../delete`.
26. **`enableGpu: false`** for cache builders and stealth wipes. This is what keeps them at zero GPU quota.
27. **`isPrivate: true`** always. Prompts/tokens live in the script.
28. **Never interpolate raw user text into Python.** Use `repr()` / `pyRepr()` and `str.replace`.
29. **`diffusers` / `transformers` pins** exist for a reason (Kaggle py3.13 + transformers 5 breakage). Re-test after changing.
30. **One job per Kaggle account.** The PC backend serializes with a lock + local FIFO; the mobile app should use unique work + a mutex/queue.

---

## 14. Source map (for the porting AI)

| File | What to read |
|---|---|
| `cellium/services/kaggle_image.py` | `MODEL_PRESETS`, `KERNEL_TEMPLATE`, `KaggleImageBackend` (`_build_kernel_script`, `_push_kernel`, `_get_kernel_status`, `_fetch_outputs`, `_wipe_cloud_traces_async`), `KaggleImageWorker`, `create_backend_from_settings`, `enhance_prompt`, `enhance_with_model`, `upsert_dataset`, `delete_dataset` |
| `cellium/services/model_cache.py` | `preset_slug`, `cache_status`, `refresh_cache_map`, `BUILDER_TEMPLATE`, `push_cache_builder`, `build_builder_script` |
| `cellium/services/kaggle_relay.py` | `NtfyRelay`, `WATCHER_TEMPLATE`, `build_watcher_script`, `CacheManager`, `_jpeg_payload` |
| `cellium/services/image_tool.py` | `ImageToolHub`, `image_to_b64`, `ImagineTool` |
| `cellium/ui/widgets/imagine_dialog.py` | `STYLE_PRESETS`, `SIZES`, `ImagineDialog` |
| `cellium/ui/settings/dialog.py` | Image Generation tab (~4180–4490), save (~5627–5648), import/test (~2814–2893), cache rows (~2921–3050) |
| `cellium/ui/main_window.py` | `_build_kaggle_backend`, `_on_imagine_generate`, `_handle_imagine_command`, `_kaggle_start_job`, `_on_kaggle_progress`, `_on_kaggle_finished`, `_send_generated_images`, `_init_image_tool_hub`, `_get_cache_manager`, `_imagine_via_cache` |
| `cellium/core/config.py` | `DEFAULT_SETTINGS` `kaggle_*` |
| `cellium/services/ai_workers.py` | `generate_image` registration + system prompt rule |
| `KAGGLE_IMAGE_GEN.md` | User guide + live smoke-test history |
| `TODO_KAGGLE_IMAGE.md` | Build plan + verification log |

---

## 15. Glossary

| Term | Meaning |
|---|---|
| **Kernel** | A Kaggle cloud script/notebook run. `kernelType: "script"` self-terminates. |
| **Push** | Upload a kernel script via `POST /kernels/push`. |
| **Slug** | `<username>/<kernel-name>` identifier. |
| **Dataset mount** | Read-only `/kaggle/input/...` view of a Kaggle dataset. |
| **Blob** | Kaggle’s upload token flow: `POST /blobs/upload` → `PUT createUrl`. |
| **BYOK** | Bring Your Own Key. |
| **Warm cache** | A long-running kernel that keeps the model in VRAM. |
| **Stealth wipe** | CPU-only clean script that erases the kernel code/output after download. |
| **CFG** | Classifier-Free Guidance scale (`guidance_scale`). |
| **img2img** | Image-to-image edit using an init image + denoise strength. |
| **Seed** | Deterministic noise seed; `-1` = random. |

---

### Final note for the Android AI

The phone is a **thin client**. It should never download a checkpoint, never run diffusers, and never hold a GPU. Its whole job is:

1. Keep the Kaggle key encrypted.
2. Build a JSON request + a Python script string.
3. Push, poll, download.
4. Show a beautiful progress card and the finished image.
5. Optionally wipe traces and use the cache.

If you get those five right, the mobile version will match the PC app without porting a single line of ML code. 💜
