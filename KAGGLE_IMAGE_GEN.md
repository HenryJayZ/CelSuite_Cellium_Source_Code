# 🎨 Kaggle Cloud Image Generation - User Guide (BYOK)

Generate images on **Kaggle's free GPU** straight from Cellium chat. You bring
your own Kaggle API key; Cellium talks to Kaggle directly (push script → poll →
fetch PNG). No middleman server, no CLI.

---

## 1. You do these 3 things (agent can't) 🙋

1. **SMS-verify your phone** on Kaggle: `kaggle.com` → Settings → Account →
   *Phone Verification*. **GPU quota stays locked until you do this.**
2. **Create an API token**: `kaggle.com/settings/api` → **Create Legacy API Key**
   → **Continue** → downloads `kaggle.json` with `{"username": "...", "key": "..."}`.
   (Use *Legacy API Key*, not the newer Bearer "API Token" - Cellium's backend
   authenticates with HTTP Basic `username:key`, which is the `kaggle.json` format.)
3. Open Cellium → **Settings → 🖼️ Image Generation** → click
   **📥 Import kaggle.json** (or type username + key manually) → **🔍 Test
   Connection** → **✓ Save Preferences**.

> ✅ Already done for this machine: `kaggle.json` lives at `~/Downloads/kaggle.json`
> and `~/.kaggle/kaggle.json` (both `chmod 600`), and the username/key are saved
> in the local `cerebrium_settings.json` (key shown masked, never logged).

> ⚠️ Keep the key private. It's stored only in the local (gitignored)
> `cerebrium_settings.json` and shown masked. Cellium never logs or echoes it.

---

## 2. Generate an image

- Click the **🎨 button** in the chat input pill, **or**
- type **`/imagine <your prompt>`** in chat (a `/` drop-up lists commands), **or**
- press **Ctrl+K** → *🎨 Generate image (Kaggle)*.

### 🤖 Let the AI do it for you
Hamburger **⋯ More → 🎨 Enable Image Gen** (off by default → the tool is
never sent to the model, keeping prompts small). When ON, Cel gets a
`generate_image` tool and will call it herself when you say things like
*"generate a cute cartoon cat"*, *"nah, generate a new one of a dog"* (new
image), or *"put a clown face on the cat"* (**edits the last image**, img2img).
Progress shows as a small nameless bubble in the chat (pings every 33 s) and
the finished image lands inline with its seed.

## 2b. ✨ Enhance with your own model
The Imagine dialog has an **✨ Enhancer** dropdown (any model from Model Hub,
or "Local tags"). **✨ Enhance** expands what you typed into a full Danbooru
tag list using that dedicated model (falls back to local tags if unset/offline).

## 2c. 📦 Mega-batch & ☁️ cloud storage (speed)
- Set **Images (batch)** up to **20** - the chat bubble tracks "×N images".
- Settings → Image Generation → **☁️ Keep model in a private Kaggle dataset**:
  **⬆️ Upload model** pushes a local `.safetensors` to a private dataset with a
  real progress bar; kernels then **mount** it (`/kaggle/input/<slug>/...`),
  cutting the ~2-min model download to ~5 s. **🗑 Delete dataset** removes it.
- **🔥 Warm cache v2 (ntfy.sh relay)**: `/imagine-start-cache` /
  `/imagine-stop-cache` (or `/` drop-up / ⋯ menu) start/stop a **quota-capped
  (1 h, idle-stop 10 min) watcher notebook** on Kaggle. Because this Kaggle
  key can't write dataset versions (`403 datasets.update`), the mailbox moved
  out of Kaggle to **ntfy.sh** (free, zero-account pub/sub): the app POSTs job
  JSON to a `cmd` topic, the notebook consumes via one SSE connection
  (reconnects on drop), and posts results to a `res` topic. The notebook loads
  the model ONCE into VRAM, generates each job to `/kaggle/working/
  out_<id>.png`, and the app pulls images via `/kernels/output` every 4 s.
  While ready, `/imagine` (and batches up to 20) queue to the notebook  - 
  **~15–20 s first image, ~8–13 s each after**. If the heartbeat goes stale
  >90 s or the kernel ends, pending jobs **auto-requeue through the normal
  script path** (images are never lost). Stop with `/imagine-stop-cache`  - 
  the notebook also self-kills at its cap/idle timer. ⚠️ It holds a GPU slot
  the whole time - the ⋯ toggle shows the live countdown.

### 🧪 Smoke Test #1 findings (recorded - which hops died)
- **Hop A (naive multipart upload)**: 400 "Error reading JToken" → fixed with the
  proper **blob flow** (`POST /blobs/upload` → PUT signed `createUrl` → version
  with `files:[{token}]`) in `kaggle_image._upload_blob` / `_create_version`.
- **Hop B (dataset version WRITE with this account)**: `403 Permission
  'datasets.update' was denied` - intermittent but consistent: this Kaggle key
  can create a dataset once (with a file inline, flat body) but **cannot reliably
  push new versions**. So the warm-cache mailbox is **implemented but
  auto-fails-fast to script mode** on start (403 probe → dead → pending jobs
  requeue via the normal script path). The **kernels API is unrestricted**, which
  is why script-mode images always work - that is the reliable path.
- **Results hop (`/kernels/output` mid-run)** was never reached because the
  notebook never got jobs (Hop B). Script-mode runs already proved
  `/kernels/output` serves `out.png` after completion.
- Net: images always work (script path); warm-cache is a best-effort turbo that
  degrades gracefully. Logs: `/tmp/opencode/smoke1*.log`.

Tweak prompt / negative prompt / steps / size / CFG / seed in the dialog, hit
**🎨 Generate**. Progress toasts show `pushing → queued → running → downloading → ✅`.
The finished PNG appears **inline in chat** (click it for full-screen) with its
**seed**, and is saved to your gallery folder (Settings → output folder, default
`<user data>/generated_images`).

---

## 3. Pick a model

Settings → Image Generation → *Model Source*:

| Mode | What you enter | Notes |
|------|----------------|-------|
| **HuggingFace (public repo)** | repo id, e.g. `lykon/dreamshaper-xl-v2-turbo` (default) | Fast, public, non-gated. Add an HF token only for gated repos. |
| **Civitai (single file URL)** | model URL or `https://civitai.com/api/download/models/<id>` + optional Bearer token | For your own ~7 GB checkpoint. |

Optional **LoRA**: paste a LoRA download URL + strength - loaded on top of the
checkpoint each run.

The model weights are downloaded **by Kaggle's server** inside the kernel
(`enableInternet`), never by your PC - only the tiny PNG comes back.

---

## 4. How it works under the hood

```
Cellium ──POST /api/v1/kernels/push──► Kaggle  (python script, kernelType=script,
Cellium ◄─POST /api/v1/kernels/status─┘         isPrivate, enableGpu, enableInternet,
Cellium ◄─POST /api/v1/kernels/output────────   sessionTimeoutSeconds=2700)
         └─ out.png + <img>.meta.json (seed)
```

- `kernelType: "script"` → the VM **self-terminates** when the script exits, so
  GPU quota stops billing immediately. Plus a hard 45-min session cap.
- One job per Kaggle account: extra requests **queue locally** in the app.
- Prompts/tokens/URLs are embedded via `repr()`+`json.dumps` - the generated
  kernel script is injection-proof.
- Statuses normalized (`QUEUED/RUNNING/COMPLETE/ERROR/CANCEL_*`); errors mapped
  to friendly messages (bad key, weekly GPU quota, rate-limit backoff, timeout).

---

## 5. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Invalid credentials` | Re-import `kaggle.json`, check username/key, Save. |
| `GPU quota exhausted` | Weekly 30 h/wk cap used - waits until reset (Monday). |
| Long "Waiting for GPU" | Kaggle queue is busy - normal, up to a few minutes. |
| `No out.png in kernel output` | Model failed to load - check the Civitai URL/token, or pick a public HF repo. |
| 15-min timeout | Big model + slow queue - retry; the session cap protects quota. |

Kernel runs are visible at `https://www.kaggle.com/code/<you>/cloud-render-w1`.

---

## 6. Android later

All Kaggle logic lives in `cellium/services/kaggle_image.py` as pure `requests`
calls - portable to the Android port unchanged (just keep the key in secure
storage there, never in a shared APK).

---

## 7. Phase 5 - ☁️ Cloud Model Cache (server-side, zero local traffic)

**Goal:** each Civitai preset (checkpoint + optional LoRA) is fetched **once**
by a CPU-only Kaggle builder kernel into a private dataset; every later render
*mounts* that dataset (~5 s) instead of re-downloading ~7 GB. The PC only
exchanges JSON - **zero model bytes** ever cross Henny's metered connection.

### 7.1 Step 0 - live hop probe (2026-11-03, key `henrycarm`)

| Hop | Status | Result |
|---|---|---|
| `GET /datasets/list` | 200 | returns **0 rows** → unusable for discovery |
| `GET /datasets/view/{user}/{slug}` | 200 | `totalBytes` reflects real storage → **the discovery endpoint** |
| `POST /blobs/upload` + `PUT createUrl` | 200 | blob token issued |
| `POST /datasets/create/new` (inline blob) | 200 | dataset created **with the file stored** (1 021 B probe verified) |
| `POST /datasets/create/version` | **403** | `Permission 'datasets.update' was denied` → datasets can only be *created*, never updated |

**Consequences:** one dataset per preset (`cellium-cache-<preset-slug>`),
created once; re-caching means **delete → create**; discovery always uses
`view`, never `list`.

### 7.2 Builder kernel (CPU-only, zero GPU quota)

`cellium/services/model_cache.py` → `BUILDER_TEMPLATE`: pushes a Kaggle script
kernel with `enableGpu=False`, `enableInternet=True` → downloads
`civitai_url` (+ `lora_url`) to `/kaggle/working`, uploads both through the
blob flow, then `datasets/create/new`.

### 7.3 Discovery + auto-mount

- `cache_status()` → `GET /datasets/view/{user}/{slug}`; `< 1 MB` = broken
  shell → the UI shows `⚠️ empty shell`.
- `refresh_cache_map()` → one cheap GET per preset (KB of traffic).
- `build_model_config()` / `create_backend_from_settings()` mount the healthy
  slug into `datasetDataSources` → the kernel reads
  `/kaggle/input/<slug>/model.safetensors` (+ `lora.safetensors`) and
  **skips the Civitai download entirely**.

### 7.4 UI (Settings → Image Gen)

Per Civitai preset row: `☁️ not cached` / `☁️ cached · 6.71 GB` /
`⚠️ empty shell`, with `☁️ Cache now`, `↻ Re-cache`, `🗑` and a
`🔄 Refresh cache status` button.

### 7.5 ntfy relay bugs found by the live smoke test

| Bug | Symptom | Fix |
|---|---|---|
| `Content-Type: application/json` on the ntfy POST | ntfy parsed the body as a message struct and **dropped it** - publish returned 200, watcher received an empty message | plain-text body (`data=json.dumps(...)`) |
| batch envelope vs. single job | the app publishes `{"jobs": [...]}`; the watcher read `msg.get("id")` → `None` → **every job was silently skipped** (only the shutdown pill landed) | the watcher now unwraps `msg["jobs"]` into individual jobs |
| no in-flight guard | a replayed batch could render the same job twice | `started_ids` + `done_ids` in the watcher |
| jobs queued before the watcher subscribed | the app publishes at t+4 s, the watcher subscribes at t+160 s (after model load) → early jobs vanished | `_republish_pending()` re-sends pending jobs on the first heartbeat |
| ntfy replaces the body of an upload | the result metadata (job id, seed, prompt) was destroyed → the app could not map the image back to a job | metadata travels as its **own message** right before the attachment; the app pairs them FIFO |
| multipart uploads are stored verbatim | the attachment was the whole MIME envelope (boundary + headers + JPEG) → corrupt `.jpg` files | the watcher now uploads a **raw body + `Filename` header** (ntfy's documented path); the app also sanitises the bytes |

### 7.6 Live results (2026-11-03)

| Metric | Value |
|---|---|
| Watcher ready (HF DreamShaper XL Turbo, cold) | **164.9 s** (model download + load) |
| Render latency after warm-up | **6–9 s** per 512×512 image (8 steps) |
| Jobs delivered end-to-end | **3 / 3** (`out_smoke0/1/2.jpg`, seeds 1000–1002) |
| Downloaded files | valid **512×512 RGB JPEG**, 48–71 KB |
| Regression suite | **112 passed / 0 failed** (incl. the new Phase 5 case) |
| PC traffic | JSON only - **0 model bytes** |

### 7.7 Live proof of the server-side cache (2026-11-03)

| Step | Result |
|---|---|
| `Cache now` on **📸 Juggernaut XL Ragnarok** | CPU-only builder kernel `cellium-cache-builder-b1711e` (zero GPU quota) |
| Builder download (**on Kaggle**, not on the PC) | 7.1 GB streamed to `/kaggle/working/model.safetensors` |
| Dataset write | `POST /datasets/create/new` → `henrycarm/cellium-cache-juggernaut-xl-ragnarok` |
| Dataset size read back | **7,105,350,162 bytes** → `healthy: true` |
| Files inside | `model.safetensors` (via `GET /datasets/list/<owner>/<slug>`) |
| PC traffic | JSON only - the PC never touched a model byte |
| Render **from the mounted cache** | watcher logged `model from mounted cache: /kaggle/input/datasets/henrycarm/cellium-cache-juggernaut-xl-ragnarok/model.safetensors` → `done mounted1 seed 7` |
| App-side receipt | `🖼 IMAGE out_mounted1.jpg seed=7 size=64436 B` (valid 512×512 JPEG) |

### 7.9 The three engines (Henny's Mini App lineup)

The app ships exactly **three AI models** + a manual Custom mode:

| # | Preset in the app | Source | Checkpoint | LoRA | Recipe |
|---|---|---|---|---|---|
| 1 | ✨ **DreamShaper XL Turbo v2** (fast, public HF) | HuggingFace | `lykon/dreamshaper-xl-v2-turbo` | - | 8 steps / CFG 2.0 |
| 2 | 🎨 **Nova Cartoon XL** (Civitai) | Mini App `NOVA_URL` | version **`2329740`** → `novaCartoonXL_v60.safetensors` (6.94 GB, Illustrious base) | `1524099` (Cartoony/Juukyuu Illustrious) | 33 steps / CFG 7.0 |
| 3 | 📸 **Juggernaut XL Ragnarok** (Civitai) | Mini App `civitai_pick(133005, prefer=("Ragnarok",))` | version **`1759168`** → `juggernautXL_ragnarok.safetensors` (7.11 GB, SDXL 1.0 base) | **none** - the Mini App keeps the cartoon LoRA off realism engines | 33 steps / CFG 7.0 |
| - | 🔧 Custom (from Settings) | manual | any URL | any URL | user-defined |

> **Correction (2026-11-03):** an earlier revision wrongly declared Nova
> "deleted upstream". The probe was wrong, not the model - `/api/v1/models/<id>`
> only accepts **model** ids, so asking it with a **version** id always 404s.
> The Mini App's `NOVA_URL` (`/api/download/models/2329740`) is alive and
> serves 6.94 GB. Only the Mini App's *LoRA* id (`627178`) is genuinely gone.

### 7.8 Landmines found by the live runs

| Landmine | What actually happens | Fix |
|---|---|---|
| **Dataset mount path** | Kaggle mounts datasets at `/kaggle/input/datasets/<owner>/<slug>/…`, **not** `/kaggle/input/<slug>/` → every mount silently fell back to a Civitai download | glob `/kaggle/input/**/model.safetensors` and keep the paths whose slug matches |
| **Civitai *model* id** | `/api/download/models/133005` serves the page's *latest* file - a 151 MB `MaouBigV1.2.safetensors`, not Juggernaut XL (it then failed with "CLIPTextModel weights missing") | the presets use **version ids** (`1759168`), and the watcher resolves model ids through `/api/v1/models/<id>` → best SDXL version |
| **Kaggle renames kernels** | the push response's `ref` can differ from the requested slug → every later status/log poll looked at a kernel that never existed | parse `ref` / `refNullable` out of the push response |
| **`files: []` in `/datasets/view`** | the view endpoint does not list dataset files | use `GET /datasets/list/<owner>/<slug>` for the file list |
| **Warm deadline** | mounting + parsing a 7.1 GB SDXL checkpoint on Kaggle takes **~11–12 min** - the old 180 s budget always gave up and fell back to script mode | the warm budget is now **900 s**; once warm, every further job answers in **6–9 s** |
| **Wrong endpoint = fake "dead model"** | `/api/v1/models/<versionId>` 404s for *version* ids (it only knows *model* ids) - probing it made a perfectly alive Nova look deleted | probe the **download** endpoint (`/api/download/models/<versionId>`) and `/api/v1/model-versions/<versionId>`; only the LoRA id `627178` is really gone |
