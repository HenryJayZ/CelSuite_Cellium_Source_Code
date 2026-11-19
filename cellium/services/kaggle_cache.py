#!/usr/bin/env python3
"""
Warm Cache v2 - watcher notebook + Kaggle "mailbox" (PHASE_3_SPEC).

Neither side can reach the other directly (notebook has no inbound ports; PC
is behind NAT), but BOTH can call Kaggle REST over HTTPS. So Kaggle is the
post office:

  PC app   → writes mail: uploads a new version of private dataset
             {user}/celium-queue containing queue.json
  Notebook → reads mail: every 5s downloads the LATEST queue version over REST
             (GET /datasets/download/{owner}/{slug}) - NOT the static mount,
             which is why this works mid-session.
  Notebook → writes results to /kaggle/working/out_<id>.png + heartbeat.json
  PC app   → reads results: polls GET /kernels/output every 4s, downloads new
             out_<id>.png as they appear.

The PC stays the controller (queue owner, UI, timeouts, fallback). If the
cache dies (stale heartbeat / kernel complete), pending jobs auto-requeue
through the normal script path - images are never lost.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

import requests
from PySide6.QtCore import QObject, QThread, Signal

from cellium.core.logger import dev_log
from cellium.services.kaggle_image import (
    KaggleImageBackend, KAGGLE_API_BASE, GenerationError,
)

QUEUE_DATASET = "celium-queue"
CACHE_KERNEL_SLUG = "cellium-warm-cache"
HARD_CAP_S = 3600      # notebook self-kills after 1h
IDLE_STOP_S = 600      # notebook self-kills after 10min idle
POLL_QUEUE_S = 5       # notebook queue poll
APP_POLL_S = 4         # app results poll
HEARTBEAT_STALE_S = 90

# ─── Watcher notebook (kernel_type=notebook, pushed once) ───────────────────
# __CFG__ is replaced with a repr'd JSON blob (prompt-safe, like the main kernel).
WATCHER_TEMPLATE = '''import json, time, io, zipfile, os, subprocess, sys, glob
import urllib.request, base64

CFG = json.loads(__CFG__)
t0 = time.time()
last_work = time.time()
subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
    "diffusers>=0.34,<0.35", "transformers>=4.41,<5", "accelerate", "safetensors"])
import torch
from diffusers import StableDiffusionXLPipeline

def log(*a):
    print("[watcher]", *a, flush=True)

# ── load model ONCE (the whole point of the cache) ──
slug = CFG.get("dataset_slug") or ""
mounted = glob.glob("/kaggle/input/" + slug + "/**/model.safetensors", recursive=True) if slug else []
if CFG["mode"] == "civitai":
    if mounted:
        path = mounted[0]
    else:
        url = CFG["civitai_url"]
        log("downloading model", url[:80])
        req = urllib.request.Request(url, headers={"User-Agent": "Cellium/1.0"})
        data = urllib.request.urlopen(req, timeout=600).read()
        path = "/kaggle/working/model.safetensors"
        open(path, "wb").write(data)
    pipe = StableDiffusionXLPipeline.from_single_file(path, torch_dtype=torch.float16)
else:
    pipe = StableDiffusionXLPipeline.from_pretrained(CFG["hf_model"], torch_dtype=torch.float16)
try:
    pipe.vae.config.force_upcast = True
except Exception:
    pass
pipe = pipe.to("cuda")
try:
    pipe.enable_vae_slicing(); pipe.enable_vae_tiling()
except Exception:
    pass
if CFG.get("lora_url"):
    try:
        pipe.load_lora_weights(CFG["lora_url"])
    except Exception as e:
        log("lora skip", e)
log("model loaded in", round(time.time() - t0, 1), "s")

OWNER = CFG["owner"]; QSLUG = CFG["queue_slug"]
AUTH = base64.b64encode((OWNER + ":" + CFG["api_key"]).encode()).decode()

def fetch_queue():
    """Download the LATEST queue dataset version over REST (not the static mount)."""
    url = "https://www.kaggle.com/api/v1/datasets/download/%s/%s?nocache=%d" % (OWNER, QSLUG, time.time() * 1000)
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + AUTH, "User-Agent": "Cellium/1.0"})
    try:
        raw = urllib.request.urlopen(req, timeout=30).read()
        zf = zipfile.ZipFile(io.BytesIO(raw))
        for name in zf.namelist():
            if name.endswith("queue.json"):
                return json.loads(zf.read(name).decode("utf-8"))
    except Exception as e:
        log("queue fetch failed:", e)
    return None

def write_heartbeat(done_count):
    hb = {"ts": time.time(), "uptime_s": int(time.time() - t0),
          "done_count": done_count, "vram_mb": 0}
    try:
        import torch as _t
        if _t.cuda.is_available():
            hb["vram_mb"] = int(_t.cuda.memory_allocated() / 1e6)
    except Exception:
        pass
    json.dump(hb, open("/kaggle/working/heartbeat.json", "w"))

done_ids = set()
log("watcher alive; cap", CFG["hard_cap_s"], "s; idle-stop", CFG["idle_stop_s"], "s")
while True:
    q = fetch_queue()
    if q is None:
        time.sleep(CFG["poll_s"]); continue
    if q.get("action") == "shutdown":
        log("shutdown pill received - exiting")
        break
    jobs = q.get("jobs") or []
    done_ids.update(q.get("done") or [])
    worked = False
    for job in jobs:
        jid = job.get("id")
        if not jid or jid in done_ids:
            continue
        try:
            seed = job.get("seed", -1)
            if seed is None or seed < 0:
                seed = int(time.time() * 1000) % (2**32)
            kwargs = dict(prompt=job["prompt"], negative_prompt=job.get("neg", ""),
                          num_inference_steps=job.get("steps", 28),
                          guidance_scale=job.get("guidance", 6.5),
                          generator=torch.Generator("cuda").manual_seed(seed))
            if job.get("init_b64"):
                from PIL import Image
                from diffusers import StableDiffusionXLImg2ImgPipeline
                init = Image.open(io.BytesIO(base64.b64decode(job["init_b64"]))).convert("RGB")
                p2 = StableDiffusionXLImg2ImgPipeline(**pipe.components).to("cuda")
                kwargs["image"] = init; kwargs["strength"] = job.get("denoise", 0.7)
                img = p2(**kwargs).images[0]
            else:
                kwargs["width"] = job.get("w", 832); kwargs["height"] = job.get("h", 1216)
                img = pipe(**kwargs).images[0]
            img.save(f"/kaggle/working/out_{jid}.png")
            done_ids.add(jid)
            meta = {"id": jid, "seed": seed, "prompt": job["prompt"][:80]}
            json.dump(meta, open(f"/kaggle/working/out_{jid}.meta.json", "w"))
            log("done", jid, "seed", seed)
            worked = True
            last_work = time.time()
        except Exception as e:
            log("job failed", jid, e)
    write_heartbeat(len(done_ids))
    uptime = time.time() - t0
    if uptime > CFG["hard_cap_s"]:
        log("hard cap reached - exiting"); break
    if not worked and time.time() - last_work > CFG["idle_stop_s"]:
        log("idle too long - exiting to save quota"); break
    time.sleep(CFG["poll_s"])
log("watcher exit; done", len(done_ids))
'''


def build_watcher_script(backend: KaggleImageBackend, model_cfg) -> str:
    cfg = {
        "owner": backend.username,
        "api_key": backend.api_key,          # only inside the private notebook
        "queue_slug": QUEUE_DATASET,
        "mode": model_cfg.mode,
        "hf_model": model_cfg.hf_model,
        "civitai_url": model_cfg.civitai_url,
        "lora_url": model_cfg.lora_url,
        "dataset_slug": getattr(model_cfg, "dataset_slug", ""),
        "hard_cap_s": HARD_CAP_S,
        "idle_stop_s": IDLE_STOP_S,
        "poll_s": POLL_QUEUE_S,
    }
    return WATCHER_TEMPLATE.replace("__CFG__", repr(json.dumps(cfg, ensure_ascii=False)))


# ─── App-side queue I/O ─────────────────────────────────────────────────────
def _queue_read(backend: KaggleImageBackend) -> dict:
    """Download latest queue.json from the queue dataset (returns {} on miss)."""
    url = (f"{KAGGLE_API_BASE}/datasets/download/{backend.username}/{QUEUE_DATASET}"
           f"?nocache={int(time.time() * 1000)}")
    try:
        r = backend._session.get(url, timeout=15)
        if r.status_code != 200:
            return {}
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        for name in zf.namelist():
            if name.endswith("queue.json"):
                return json.loads(zf.read(name).decode("utf-8"))
    except Exception as e:
        dev_log(f"[cache] queue read failed: {e}")
    return {}


def _queue_write(backend: KaggleImageBackend, queue: dict) -> None:
    """Upload a new version of the queue dataset containing queue.json.

    Uses the Kaggle blob-upload flow (POST /blobs/upload -> PUT to signed
    createUrl -> create version with the blob token)."""
    from cellium.services.kaggle_image import upsert_dataset
    payload = json.dumps(queue).encode("utf-8")
    upsert_dataset(backend, QUEUE_DATASET, "Cellium queue", "queue.json",
                   payload, "application/json")


def _kernel_files(backend: KaggleImageBackend, slug: str) -> list:
    body = {"userName": backend.username, "kernelSlug": slug, "pageSize": 100}
    r = backend._kernels_call("/kernels/output", body, timeout=30)
    if r is None or r.status_code != 200:
        return []
    d = r.json()
    return d.get("files") or []


def _kernel_log_tail(backend: KaggleImageBackend, slug: str, n: int = 800) -> str:
    """Last ~n chars of a kernel's streamed log (to show why it died)."""
    body = {"userName": backend.username, "kernelSlug": slug, "pageSize": 100}
    try:
        r = backend._kernels_call("/kernels/output", body, timeout=30)
        if r is None or r.status_code != 200:
            return ""
        log = r.json().get("log") or ""
        parts = []
        for line in log.splitlines()[-60:]:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
                if isinstance(o, dict) and "data" in o:
                    parts.append(str(o["data"]))
                    continue
            except Exception:
                pass
            parts.append(line)
        return "".join(parts)[-n:]
    except Exception:
        return ""


def _dl(backend: KaggleImageBackend, file_entry):
    url = file_entry.get("url")
    name = file_entry.get("fileName") or file_entry.get("file_name") or ""
    if not url:
        return b"", name
    rr = requests.get(url, timeout=120)
    rr.raise_for_status()
    return rr.content, name


# ─── CacheManager (QObject + worker QThread) ────────────────────────────────
class CacheManager(QObject):
    state_changed = Signal(str)          # idle|warming|ready|streaming|stopped|dead
    progress = Signal(str)               # human line for the chat bubble
    image_ready = Signal(str, str, str)  # path, seed, prompt
    heartbeat = Signal(int, int, int)    # uptime_s, done_count, vram_mb

    def __init__(self, backend: KaggleImageBackend, model_cfg, output_dir: Path, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.model_cfg = model_cfg
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state = "idle"
        self._jobs: dict[str, dict] = {}     # id -> job
        self._done: set[str] = set()
        self._seen_files: set[str] = set()
        self._stop = False
        self._worker: QThread | None = None
        self._last_hb = 0.0

    # ── public API (GUI thread) ──
    def start(self):
        self._set_state("warming")
        self.progress.emit("🔥 Pushing watcher notebook (loads model once)…")
        self._worker = QThread(self)
        mgr = self

        class _W(QThread):
            def run(self):
                mgr._run()
        self._worker = _W(self)
        self._worker.start()

    def stop(self):
        try:
            q = _queue_read(self.backend)
            q["action"] = "shutdown"
            _queue_write(self.backend, q)
        except Exception as e:
            dev_log(f"[cache] shutdown pill failed: {e}")
        self.progress.emit("🛑 Shutdown pill sent - notebook exits ≤15s (or at its cap)")
        self._stop = True

    def enqueue(self, jobs: list[dict]):
        """Add jobs (each must have a unique id) to the mailbox queue."""
        dev_log(f"[cache] enqueue {len(jobs)} job(s)")
        q = _queue_read(self.backend)
        q.setdefault("jobs", [])
        q.setdefault("done", sorted(self._done))
        q["action"] = None
        for j in jobs:
            if j["id"] not in {x["id"] for x in q["jobs"]}:
                q["jobs"].append(j)
                self._jobs[j["id"]] = j
        _queue_write(self.backend, q)
        self.progress.emit(f"📮 Queued {len(jobs)} job(s) - notebook picks them up ≤{POLL_QUEUE_S}s")

    # ── worker loop (runs in QThread) ──
    def _set_state(self, s):
        self.state = s
        dev_log(f"[cache] state -> {s}")
        self.state_changed.emit(s)

    def _run(self):
        b = self.backend
        # Seed the mailbox FIRST so the watcher can heartbeat immediately. Non-fatal:
        # if the seed times out, the notebook still polls and the first enqueue
        # will (re)create the queue - never kill the cache over a slow seed.
        try:
            _queue_write(b, {"jobs": [], "done": [], "action": None})
        except Exception as e:
            msg = str(e)
            dev_log(f"[cache] queue seed failed: {msg[:120]}")
            if "403" in msg or "permission" in msg.lower() or "denied" in msg.lower():
                # mailbox hop is blocked for this Kaggle key (datasets.get/update
                # denied) → fail fast to script mode, which is the proven path.
                self.progress.emit("ℹ️ Warm-cache mailbox not permitted by this Kaggle key "
                                   "(datasets 403) - images still work via script mode ✅")
                self._set_state("dead")
                self._fallback()
                return
            self.progress.emit(f"⚠️ queue seed slow ({msg[:60]}) - continuing; first /imagine will (re)create it")
        warm_deadline = time.time() + 90  # model load can take ~2 min
        # push watcher notebook
        try:
            script = build_watcher_script(b, self.model_cfg)
            payload = {
                "slug": f"{b.username}/{CACHE_KERNEL_SLUG}",
                "newTitle": "Cellium Warm Cache v2",
                "text": script, "language": "python", "kernelType": "notebook",
                "isPrivate": True, "enableGpu": True, "enableInternet": True,
                "datasetDataSources": [f"{b.username}/{self.model_cfg.dataset_slug}"]
                                    if getattr(self.model_cfg, "dataset_slug", "") else [],
                "competitionDataSources": [], "kernelDataSources": [],
                "modelDataSources": [], "categoryIds": [],
                "sessionTimeoutSeconds": HARD_CAP_S,
            }
            r = b._session.post(f"{KAGGLE_API_BASE}/kernels/push", json=payload, timeout=60)
            r.raise_for_status()
        except Exception as e:
            self.progress.emit(f"❌ cache push failed: {e}")
            self._set_state("dead")
            self._fallback()
            return
        self._set_state("warming")
        # wait for first heartbeat, then poll results
        ready_announced = False
        while not self._stop:
            time.sleep(APP_POLL_S)
            # status
            try:
                st = b._get_kernel_status_for(CACHE_KERNEL_SLUG)
            except Exception:
                st = "unknown"
            if st in ("complete", "error", "cancelled"):
                tail = _kernel_log_tail(b, CACHE_KERNEL_SLUG, 400)
                self.progress.emit("💤 Cache session ended" + (f" - {tail[-160:]}" if tail else ""))
                self._set_state("dead")
                self._fallback()
                return
            if not ready_announced:
                if time.time() > warm_deadline:
                    tail = _kernel_log_tail(b, CACHE_KERNEL_SLUG, 600)
                    self.progress.emit("⏰ Cache didn't warm in 90s - falling back to script mode"
                                       + (f"\nlog: {tail[-200:]}" if tail else ""))
                    self._set_state("dead")
                    self._fallback()
                    return
                self.progress.emit(f"🔥 Warming… {int(time.time() - (warm_deadline - 150))}s (loading model)")
            files = _kernel_files(b, CACHE_KERNEL_SLUG)
            names = [f.get("fileName") or f.get("file_name") or "" for f in files]
            # heartbeat
            if "heartbeat.json" in names:
                try:
                    raw, _ = _dl(b, next(f for f in files if (f.get("fileName") or f.get("file_name")) == "heartbeat.json"))
                    hb = json.loads(raw.decode("utf-8"))
                    self._last_hb = time.time()
                    self.heartbeat.emit(int(hb.get("uptime_s", 0)), int(hb.get("done_count", 0)),
                                        int(hb.get("vram_mb", 0)))
                    if not ready_announced:
                        ready_announced = True
                        self._set_state("ready")
                        self.progress.emit(f"🔥 Cache ready - {HARD_CAP_S//60} min cap")
                except Exception:
                    pass
            # new result images
            for f in files:
                name = f.get("fileName") or f.get("file_name") or ""
                if name.startswith("out_") and name.endswith(".png") and name not in self._seen_files:
                    self._seen_files.add(name)
                    try:
                        raw, _ = _dl(b, f)
                        jid = name[4:-4]
                        ts = time.strftime("%Y%m%d_%H%M%S")
                        p = self.output_dir / f"cache_{ts}_{jid}.png"
                        p.write_bytes(raw)
                        # seed from meta if present
                        seed = "?"
                        meta_name = f"out_{jid}.meta.json"
                        if meta_name in names:
                            try:
                                mraw, _ = _dl(b, next(x for x in files if (x.get("fileName") or x.get("file_name")) == meta_name))
                                seed = str(json.loads(mraw.decode("utf-8")).get("seed", "?"))
                            except Exception:
                                pass
                        self._done.add(jid)
                        job = self._jobs.get(jid, {})
                        dev_log(f"[cache] image ready {p.name} seed={seed}")
                        self.image_ready.emit(str(p), seed, job.get("prompt", jid))
                        n = len(self._done)
                        self._set_state("streaming")
                        self.progress.emit(f"🎨 {n} image(s) done")
                    except Exception as e:
                        dev_log(f"[cache] result dl failed: {e}")
            # dead-cache detection: stale heartbeat
            if ready_announced and (time.time() - self._last_hb) > HEARTBEAT_STALE_S:
                self.progress.emit("💤 Cache heartbeat stale - falling back to script mode")
                self._set_state("dead")
                self._fallback()
                return
        self._set_state("stopped")

    def _fallback(self):
        """Requeue pending jobs through the normal script path (never lose images)."""
        pending = [j for jid, j in self._jobs.items() if jid not in self._done]
        if not pending:
            return
        dev_log(f"[cache] fallback requeueing {len(pending)} job(s) via script path")
        self.progress.emit(f"↩️ Cache dead - requeueing {len(pending)} job(s) as script jobs")
        # hand them to the caller via a signal
        self.fallback_jobs = pending

    def take_fallback_jobs(self) -> list[dict]:
        return getattr(self, "fallback_jobs", [])
