#!/usr/bin/env python3
"""
Relay Backend Abstraction + ntfy.sh Implementation

Abstracts the communication channel between the app (PC) and the Kaggle
watcher notebook. Supports ntfy.sh (primary) with Telegram fallback.

Architecture:
  App ──POST/GET──► Relay ──SSE/Poll──► Watcher Notebook (on Kaggle)
                    ◄── results ◄────────── (heartbeat, done signals)
"""

from __future__ import annotations

import json
import time
import threading
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from PySide6.QtCore import QObject, QThread, Signal

from cellium.core.logger import dev_log
from cellium.services.kaggle_image import (
    KaggleImageBackend, KAGGLE_API_BASE, CACHE_KERNEL_SLUG,
)

# ─── Relay Interface ────────────────────────────────────────────────────────


class RelayBackend(ABC):
    """Abstract base for command/result relay between app and notebook."""

    @abstractmethod
    def start(self) -> Dict[str, str]:
        """Create/prepare the relay. Returns dict with topic names etc."""
        pass

    @abstractmethod
    def enqueue(self, jobs: List[Dict]) -> None:
        """Enqueue one or more jobs (atomic, batched)."""
        pass

    @abstractmethod
    def subscribe_results(self, on_result: Callable[[Dict], None]) -> None:
        """Start listening for results. Callback receives result dict."""
        pass

    @abstractmethod
    def publish_shutdown(self) -> None:
        """Send shutdown signal."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Clean up resources."""
        pass

    @property
    @abstractmethod
    def is_healthy(self) -> bool:
        """True if relay is usable."""
        pass


# ─── ntfy.sh Implementation ────────────────────────────────────────────────


class NtfyRelay:
    """ntfy.sh relay: app publishes to cmd-topic, notebook subscribes via SSE,
    results published to res-topic, app consumes via JSON poll (reliable) or SSE."""

    BASE = "https://ntfy.sh"

    def __init__(self, cmd_topic: str, res_topic: str):
        self.cmd_topic = cmd_topic
        self.res_topic = res_topic
        self._sse_thread: Optional[threading.Thread] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._on_result: Optional[Callable[[Dict], None]] = None
        #: ntfy message ids already handed to the callback. SSE and the JSON
        #: poller overlap by design, so without this every result would fire
        #: twice (two bubbles, two downloads).
        self._seen: set = set()
        self._lock = threading.Lock()
        #: ntfy replaces the body of an upload with "You received a file: ..." and
        #: drops every extra form field (verified live), so the result metadata
        #: travels as its OWN message right before the attachment. These two
        #: FIFOs pair them back together.
        self._pending_meta: List[tuple] = []      # [(ts, metadata dict)]
        self._pending_attach: List[tuple] = []    # [(ts, attachment url)]

    def start(self) -> Dict[str, str]:
        # Topics are unguessable uuids; no auth needed
        return {"cmd_topic": self.cmd_topic, "res_topic": self.res_topic}

    def enqueue(self, jobs: List[Dict]) -> None:
        """Publish jobs as a single message to cmd-topic (batched)."""
        payload = {"jobs": jobs, "ts": time.time()}
        r = requests.post(
            f"{self.BASE}/{self.cmd_topic}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=20,
        )
        r.raise_for_status()

    def subscribe_results(self, on_result: Callable[[Dict], None]) -> None:
        """Subscribe to res-topic via SSE (primary) + JSON poll fallback."""
        self._on_result = on_result
        self._stop.clear()
        self._sse_thread = threading.Thread(target=self._sse_consumer, daemon=True)
        self._sse_thread.start()
        self._poll_thread = threading.Thread(target=self._json_poller, daemon=True)
        self._poll_thread.start()

    # ── one envelope in, deduped result out ────────────────────────────────
    def _dispatch(self, payload: Dict) -> None:
        """Dedupe (SSE + poll overlap) and forward a single ntfy envelope."""
        if not isinstance(payload, dict):
            return
        mid = payload.get("id")
        if mid:
            with self._lock:
                if mid in self._seen:
                    return
                self._seen.add(mid)
                if len(self._seen) > 5000:      # bounded memory
                    self._seen = set(list(self._seen)[-2500:])
        if "message" not in payload:
            return
        try:
            msg = json.loads(payload["message"])
        except Exception:
            msg = {}
        if not isinstance(msg, dict):
            msg = {}
        att = payload.get("attachment") or {}
        att_url = att.get("url") if isinstance(att, dict) else None

        if att_url:
            # ── an upload message: ntfy replaced the body, so the metadata
            #    was published just before it → pair them (FIFO) ──
            with self._lock:
                self._drop_stale_pending()
                meta = self._pending_meta.pop(0) if self._pending_meta else None
                if meta is None:
                    self._pending_attach.append((time.time(), att_url))
                    return
            msg = dict(meta[1])
            msg["_attachment"] = att_url
        elif msg.get("type") == "result" and msg.get("id"):
            # ── the metadata message: wait for its attachment (or take one
            #    that arrived first) ──
            with self._lock:
                self._drop_stale_pending()
                pend = self._pending_attach.pop(0) if self._pending_attach else None
                if pend is None:
                    self._pending_meta.append((time.time(), msg))
                    return
            msg = dict(msg)
            msg["_attachment"] = pend[1]
        if self._on_result:
            self._on_result(msg)

    def _drop_stale_pending(self) -> None:
        """Forget half-pairs older than 2 min (caller holds the lock)."""
        cutoff = time.time() - 120
        self._pending_meta = [p for p in self._pending_meta if p[0] >= cutoff]
        self._pending_attach = [p for p in self._pending_attach if p[0] >= cutoff]

    def _sse_consumer(self) -> None:
        """Consume results via ntfy SSE stream (most responsive)."""
        url = f"https://ntfy.sh/{self.res_topic}/sse"
        headers = {"Accept": "text/event-stream", "Accept-Encoding": "identity"}
        while not self._stop.is_set():
            try:
                r = requests.get(
                    url, stream=True, headers=headers,
                    timeout=(10, 60),  # connect timeout, read timeout
                )
                for line in r.iter_lines():
                    if self._stop.is_set():
                        return
                    if not line or not line.startswith(b"data:"):
                        continue
                    try:
                        self._dispatch(json.loads(line[5:].decode()))
                    except Exception:
                        pass
            except Exception as e:
                dev_log(f"[ntfy] SSE error: {e}")
                time.sleep(2)  # backoff before reconnect

    def _json_poller(self) -> None:
        """Fallback: poll /json endpoint every 4s (reliable, no 429)."""
        while not self._stop.is_set():
            time.sleep(4)
            try:
                r = requests.get(
                    f"{self.BASE}/{self.res_topic}/json",
                    params={"poll": 1},
                    timeout=10,
                )
                if r.status_code == 200:
                    for line in r.text.strip().splitlines():
                        if not line:
                            continue
                        try:
                            self._dispatch(json.loads(line))
                        except Exception:
                            pass
            except Exception:
                pass

    def publish_shutdown(self) -> None:
        """Send shutdown signal."""
        requests.post(
            f"{self.BASE}/{self.cmd_topic}",
            data=json.dumps({"action": "shutdown"}),
            timeout=10,
        )

    def stop(self) -> None:
        self._stop.set()
        for t in (self._sse_thread, self._poll_thread):
            if t and t.is_alive():
                t.join(timeout=2)

    @property
    def is_healthy(self) -> bool:
        try:
            r = requests.get(
                f"{self.BASE}/{self.res_topic}/json",
                params={"poll": 1},
                timeout=5,
            )
            return r.status_code == 200
        except Exception:
            return False


# ─── Factory & Fallback ───────────────────────────────────────────────────


def get_relay() -> RelayBackend:
    """Return ntfy relay (primary). Telegram fallback can be added later."""
    cmd = f"cellium-{uuid.uuid4().hex[:12]}-cmd"
    res = f"cellium-{uuid.uuid4().hex[:12]}-res"
    return NtfyRelay(cmd, res)


# ─── Watcher kernel template (kernel_type=script, pushed once) ─────────────
# A script (not a notebook) because Kaggle validates notebook bodies as
# .ipynb JSON; the watcher is a plain long-running Python program instead.
# The job loop blocks on ntfy SSE, so the kernel stays alive until the
# shutdown pill / 1 h cap / 10 min idle watchdog ends it.

WATCHER_TEMPLATE = '''import json, time, io, base64, os, re, subprocess, sys, glob
import urllib.request, threading, requests

CFG = json.loads(__CFG__)
t0 = time.time()
last_work = time.time()
subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
    "diffusers>=0.34,<0.35", "transformers>=4.41,<5", "accelerate", "safetensors"])
import torch
from diffusers import StableDiffusionXLPipeline, StableDiffusionXLImg2ImgPipeline

def log(*a):
    print("[watcher]", *a, flush=True)

def _cv_resolve(url):
    """Resolve a Civitai URL to a direct .safetensors download.

    A VERSION id ("/api/download/models/<id>") is served as-is - that is the
    safe form. A MODEL id ("/models/<id>") serves the page's LATEST file (a
    model id is a trap: 133005 once served a 151 MB different checkpoint), so
    it has to be resolved through the Civitai API first.
    """
    if re.search(r"civitai\\.com/api/download/models/[0-9]+", url or ""):
        return url
    m = re.search(r"civitai\\.com/models/([0-9]+)", url or "")
    if not m:
        return url
    mid = m.group(1)
    try:
        r = requests.get("https://civitai.com/api/v1/models/" + mid, timeout=30,
                         headers={"User-Agent": "Cellium/1.0"})
        if r.status_code == 200:
            vers = (r.json() or {}).get("modelVersions") or []
            def good(v):
                b = (v.get("baseModel") or "").upper()
                n = (v.get("name") or "").lower()
                return ("SDXL" in b or "ILLUSTRIOUS" in b) and "inpaint" not in n
            pick = next((v for v in vers if good(v)), None)
            if pick is None:
                pick = next((v for v in vers if "inpaint" not in (v.get("name") or "").lower()), None)
            if pick is None and vers:
                pick = vers[0]
            if pick is not None:
                for f in (pick.get("files") or []):
                    if (f.get("name") or "").lower().endswith(".safetensors"):
                        return f.get("downloadUrl") or f.get("url") or url
                if pick.get("id"):
                    return "https://civitai.com/api/download/models/" + str(pick["id"])
    except Exception as e:
        log("civitai resolve failed:", e)
    return url


# ── load model ONCE (the whole point of the cache) ──
slug = CFG.get("dataset_slug") or ""
# Kaggle mounts datasets under /kaggle/input/datasets/<owner>/<slug>/...
# (NOT /kaggle/input/<slug>/) - search by slug so both layouts work.
mounted = []
if slug:
    _cands = glob.glob("/kaggle/input/**/model.safetensors", recursive=True)
    mounted = [p for p in _cands if slug in p]
if CFG["mode"] == "civitai":
    if mounted:
        path = mounted[0]
        log("model from mounted cache:", path)
    else:
        url = _cv_resolve(CFG["civitai_url"])
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
        _lp = ""
        _sl = CFG.get("dataset_slug") or ""
        if _sl:
            _c = [p for p in glob.glob("/kaggle/input/**/lora.safetensors", recursive=True)
                  if _sl in p]
            if _c:
                _lp = _c[0]
        if not _lp:
            _r = requests.get(CFG["lora_url"], stream=True, timeout=600)
            _r.raise_for_status()
            _lp = "/kaggle/working/lora.safetensors"
            with open(_lp, "wb") as _f:
                for _chunk in _r.iter_content(1 << 22):
                    _f.write(_chunk)
        pipe.load_lora_weights(_lp)
        # The Mini App verifies the adapters actually registered - a LoRA with
        # the wrong architecture registers ZERO adapters and silently does
        # nothing (or breaks the pipeline). Unload it and keep the render.
        try:
            _names = set()
            for _v in pipe.get_list_adapters().values():
                _names.update(_v)
        except Exception:
            _names = set()
        if not _names:
            try:
                pipe.unload_lora_weights()
            except Exception:
                pass
            log("LoRA registered ZERO adapters (arch mismatch) - unloaded")
        else:
            _names = sorted(_names)
            pipe.set_adapters(_names, adapter_weights=[CFG.get("lora_strength", 0.9)] * len(_names))
            log("LoRA applied:", _lp, _names)
    except Exception as e:
        log("lora skip", e)
log("model loaded in", round(time.time() - t0, 1), "s")

CMD_TOPIC = CFG["cmd_topic"]
RES_TOPIC = CFG["res_topic"]

def post_result(job_id, seed, prompt, seconds):
    # NOTE: plain-text body. ntfy parses a JSON Content-Type as a message
    # struct and drops unknown fields - the payload vanished and the app
    # received an empty message.
    requests.post(f"https://ntfy.sh/{RES_TOPIC}", data=json.dumps({
        "id": job_id, "seed": seed, "prompt": prompt[:80], "seconds": seconds
    }), timeout=10)

def heartbeat(uptime, done, vram=0):
    requests.post(f"https://ntfy.sh/{RES_TOPIC}", data=json.dumps({
        "type": "heartbeat", "uptime_s": int(uptime), "done_count": done, "vram_mb": vram
    }), timeout=5)

# ── ntfy SSE consumer ──────────────────────────────────────────────
def consume_loop():
    while True:
        try:
            # since=all: topics are freshly minted per session, so replaying the
            # cache guarantees jobs queued while the model was still loading
            # are never lost.
            r = requests.get(f"https://ntfy.sh/{CMD_TOPIC}/sse",
                             params={"since": "all"},
                             stream=True,
                             headers={"Accept": "text/event-stream",
                                      "Accept-Encoding": "identity"},
                             timeout=(10, 65))
            for line in r.iter_lines():
                if not line or not line.startswith(b"data:"):
                    continue
                payload = json.loads(line[5:].decode())
                if "message" not in payload:
                    continue
                try:
                    msg = json.loads(payload["message"])
                except Exception:
                    continue
                if msg.get("type") == "heartbeat":
                    continue
                # The app publishes a BATCH: {"jobs": [job, job, ...]}.
                # Treating every envelope as one job made job.get("id") None
                # and the whole batch was silently dropped - nothing rendered.
                batch = msg.get("jobs")
                if isinstance(batch, list):
                    for _job in batch:
                        yield _job
                else:
                    yield msg
        except Exception as e:
            log("sse error:", e)
            time.sleep(2)

log("watcher alive; cap", CFG["hard_cap_s"], "s; idle-stop", CFG["idle_stop_s"], "s")
done_ids = set()
started_ids = set()      # in-flight guard: a re-published job must not render twice
last_work = time.time()


def _hb_loop():
    """Heartbeat every 25s so the app can prove the cache is alive + ready."""
    while True:
        try:
            heartbeat(time.time() - t0, len(done_ids))
        except Exception:
            pass
        time.sleep(25)


def _watchdog():
    """Hard 1h cap + 10min idle self-kill - never burn quota unattended."""
    while True:
        time.sleep(5)
        if time.time() - t0 > CFG["hard_cap_s"]:
            log("hard cap reached - exiting")
            os._exit(0)
        if time.time() - last_work > CFG["idle_stop_s"]:
            log("idle stop reached - exiting")
            os._exit(0)


threading.Thread(target=_hb_loop, daemon=True).start()
threading.Thread(target=_watchdog, daemon=True).start()

for job in consume_loop():
    if job.get("action") == "shutdown":
        log("shutdown pill - exiting"); break
    jid = job.get("id")
    if not jid or jid in done_ids or jid in started_ids:
        continue
    started_ids.add(jid)
    last_work = time.time()
    try:
        seed = job.get("seed", -1)
        if seed is None or seed < 0:
            seed = int(time.time() * 1000) % (2**32)
        job_t0 = time.time()
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

        # ── JPEG 88% quality ──
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=CFG.get("jpeg_quality", 88), optimize=True)
        jpeg_bytes = buf.getvalue()
        # Save PNG for gallery (Kaggle working dir) + send JPEG via ntfy attachment
        img.save(f"/kaggle/working/out_{jid}.png")
        done_ids.add(jid)
        # ntfy REPLACES the body of an upload with "You received a file: ..." and
        # drops every extra form field (verified live), so the metadata travels
        # as its own message right before the attachment; the app pairs them.
        requests.post(f"https://ntfy.sh/{RES_TOPIC}", data=json.dumps({
            "type": "result", "id": jid, "seed": seed,
            "prompt": job["prompt"][:80], "name": f"out_{jid}.jpg",
            "seconds": round(time.time() - job_t0, 1)
        }), timeout=30)
        # ntfy's documented attachment upload = RAW body + "Filename" header.
        # A multipart body is stored VERBATIM (boundary + MIME headers + the
        # file + closing boundary), which produced corrupt .jpg downloads.
        requests.post(f"https://ntfy.sh/{RES_TOPIC}", data=jpeg_bytes,
                      headers={"Filename": f"out_{jid}.jpg",
                               "Content-Type": "image/jpeg"},
                      timeout=120)
        log("done", jid, "seed", seed)
        last_work = time.time()
    except Exception as e:
        log("job failed", jid, e)
    time.sleep(CFG.get("poll_s", 5))

log("watcher exit; done", len(done_ids))
'''


def build_watcher_script(backend: KaggleImageBackend, model_cfg,
                         cmd_topic: str = "", res_topic: str = "",
                         jpeg_quality: int = 88) -> str:
    cfg = {
        "owner": backend.username,
        "api_key": backend.api_key,
        "cmd_topic": cmd_topic or f"cellium-{uuid.uuid4().hex[:12]}-cmd",
        "res_topic": res_topic or f"cellium-{uuid.uuid4().hex[:12]}-res",
        "mode": model_cfg.mode,
        "hf_model": model_cfg.hf_model,
        "civitai_url": model_cfg.civitai_url,
        "lora_url": model_cfg.lora_url,
        "dataset_slug": getattr(model_cfg, "dataset_slug", ""),
        "hard_cap_s": 3600,
        "idle_stop_s": 600,
        "poll_s": 5,
        "jpeg_quality": int(jpeg_quality),
    }
    return WATCHER_TEMPLATE.replace("__CFG__", repr(json.dumps(cfg, ensure_ascii=False)))


# ─── Image payload helpers ─────────────────────────────────────────────────


def _jpeg_payload(raw: bytes) -> bytes:
    """Return the real JPEG bytes, stripping a multipart envelope if present.

    ntfy can store the whole multipart body (boundary + MIME headers + file +
    closing boundary) as the attachment; slicing the JPEG out of it keeps every
    downloaded file a valid image.
    """
    if raw[:3] == b"\xff\xd8\xff":
        return raw
    start = raw.find(b"\xff\xd8\xff")
    end = raw.rfind(b"\xff\xd9")
    if start != -1 and end > start:
        return raw[start:end + 2]
    return raw


# ─── App-side CacheManager (QThread) ───────────────────────────────────────


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
        self._jobs: Dict[str, Dict] = {}
        self._done: set = set()
        self._stop = False
        self._relay: Optional[RelayBackend] = None
        self._worker: Optional[QThread] = None
        self._slug = CACHE_KERNEL_SLUG
        self._last_hb = 0.0
        self._jobs_lock = threading.Lock()
        #: job ids already re-sent after the watcher went live
        self._republished_ids: set = set()

    # ── lifecycle ──────────────────────────────────────────────────────────
    def start(self):
        if self._relay is not None:
            return
        self._set_state("warming")
        # ONE relay for the whole session: the app subscribes here and the
        # notebook is built with these exact topics. Minting a second relay
        # inside _run() (the old bug) left both sides on different topics.
        self._relay = get_relay()
        self._republished_ids.clear()
        self._relay.start()
        self._relay.subscribe_results(self._on_tool_result)
        self._last_hb = time.time()
        self._worker = QThread(self)
        self._worker.run = self._run
        self._worker.start()

    def _set_state(self, s: str):
        if s == self.state:
            return
        self.state = s
        dev_log(f"[cache] state -> {s}")
        self.state_changed.emit(s)

    def stop(self):
        try:
            if self._relay:
                self._relay.publish_shutdown()
        except Exception as e:
            dev_log(f"[cache] shutdown pill failed: {e}")
        self._stop = True
        try:
            if self._relay:
                self._relay.stop()
        except Exception:
            pass

    # ── queue ──────────────────────────────────────────────────────────────
    def enqueue(self, jobs: List[Dict]) -> None:
        """Record + publish jobs (one batched ntfy message)."""
        with self._jobs_lock:
            for j in jobs:
                self._jobs[str(j.get("id"))] = dict(j)
        if self._relay is None:
            raise RuntimeError("cache relay is not started")
        self._relay.enqueue(jobs)

    def _republish_pending(self) -> None:
        """Re-send still-pending jobs once the watcher is demonstrably live.

        Why: the app publishes jobs seconds after the kernel is pushed, but the
        kernel only opens its ntfy SSE subscription after the model finished
        loading (~160 s). ntfy did NOT replay those early messages to the late
        subscriber (kernel log proof: the watcher received the shutdown pill but
        never the jobs). A heartbeat proves the watcher is subscribed right
        now, so a fresh publish is delivered live.
        """
        if self._relay is None:
            return
        pending = [j for j in self.take_fallback_jobs()
                   if j.get("id") and str(j["id"]) not in self._republished_ids]
        if not pending:
            return
        try:
            self._relay.enqueue(pending)
            for j in pending:
                self._republished_ids.add(str(j["id"]))
            dev_log(f"[cache] republished {len(pending)} job(s) to the live watcher")
        except Exception as e:
            dev_log(f"[cache] republish failed: {e}")

    def take_fallback_jobs(self) -> list[Dict]:
        """Pending (not-yet-done) jobs for the script-mode fallback."""
        with self._jobs_lock:
            done = set(self._done)
            return [dict(j) for jid, j in self._jobs.items() if jid not in done]

    # ── callbacks from relay thread (Qt thread-safe via signals) ───────────
    def _on_tool_result(self, result: Dict):
        """Called from the relay thread for every result / heartbeat."""
        msg_type = result.get("type", "result")
        if msg_type == "heartbeat":
            self._last_hb = time.time()
            if self.state in ("warming", "idle"):
                self._set_state("ready")
                self._republish_pending()
            self.heartbeat.emit(int(result.get("uptime_s", 0)),
                                int(result.get("done_count", 0)),
                                int(result.get("vram_mb", 0)))
            return

        jid = str(result.get("id") or "")
        if not jid or jid in self._done:
            return
        self._done.add(jid)
        seed = str(result.get("seed", ""))
        prompt = result.get("prompt", "")
        path = self._fetch_image(jid, result)
        if path:
            self.image_ready.emit(path, seed, prompt)
        else:
            self.progress.emit(f"⚠️ Result {jid} arrived but the image couldn't be fetched "
                               f"(checked ntfy attachment + /kernels/output)")

    def _fetch_image(self, jid: str, result: Dict) -> str:
        """Download a finished image: ntfy attachment first, Kaggle output second."""
        # 1) ntfy attachment (JPEG, ~300 KB)
        url = result.get("_attachment")
        if url:
            try:
                r = requests.get(url, timeout=90)
                r.raise_for_status()
                name = result.get("name") or f"out_{jid}.jpg"
                dest = self.output_dir / name
                dest.write_bytes(_jpeg_payload(r.content))
                dev_log(f"[cache] attachment saved {dest.name} ({dest.stat().st_size//1024} KB)")
                return str(dest)
            except Exception as e:
                dev_log(f"[cache] attachment download failed: {e}")

        # 2) Kaggle /kernels/output (PNG written by the notebook)
        try:
            for f in _kernel_files(self.backend, self._slug):
                name = f.get("fileName") or f.get("file_name") or ""
                if name == f"out_{jid}.png":
                    raw, _ = _dl(self.backend, f)
                    dest = self.output_dir / name
                    dest.write_bytes(raw)
                    return str(dest)
        except Exception as e:
            dev_log(f"[cache] kernels/output fetch failed: {e}")
        return ""

    # ── worker loop (runs in QThread) ──────────────────────────────────────
    def _run(self):
        try:
            b = self.backend
            if self._relay is None:
                self._set_state("dead")
                return
            slug = CACHE_KERNEL_SLUG
            # PHASE 5: mount the healthy server-side cache before pushing the
            # watcher (JSON-only probe) so the warm session boots straight
            # from /kaggle/input/<slug>/model.safetensors.
            try:
                b._maybe_mount_cache()
                self.model_cfg = b.model_config
            except Exception:
                pass
            script = build_watcher_script(
                b, self.model_cfg,
                cmd_topic=self._relay.cmd_topic,
                res_topic=self._relay.res_topic)
            payload = {
                "slug": f"{b.username}/{slug}",
                "newTitle": "Cellium Warm Cache v3",
                "text": script, "language": "python",
                "kernelType": "script",
                "isPrivate": True, "enableGpu": True, "enableInternet": True,
                "datasetDataSources": (
                    [f"{b.username}/{self.model_cfg.dataset_slug}"]
                    if getattr(self.model_cfg, "dataset_slug", "") else []),
                "competitionDataSources": [],
                "kernelDataSources": [],
                "modelDataSources": [], "categoryIds": [],
                "sessionTimeoutSeconds": 3600,
            }
            # Kaggle requires a UNIQUE kernel title (and slug) per account  - 
            # reusing "Cellium Warm Cache" after the first session returns
            # 409 "The requested title is already in use". Mint a fresh tag
            # per start; retry once with a brand-new tag if anything clashes.
            last_err = ""
            for _attempt in range(2):
                tag = uuid.uuid4().hex[:6]
                slug = f"{CACHE_KERNEL_SLUG}-{tag}"
                payload["slug"] = f"{b.username}/{slug}"
                payload["newTitle"] = f"Cellium Warm Cache {tag}"
                r = b._session.post(f"{KAGGLE_API_BASE}/kernels/push",
                                    json=payload, timeout=60)
                if r.status_code in (200, 201):
                    break
                last_err = f"{r.status_code} {r.text[:160]}"
                dev_log(f"[cache] push attempt {_attempt + 1} failed: {last_err}")
            self._slug = slug
            if r.status_code not in (200, 201):
                self.progress.emit(f"❌ cache push failed: {last_err}")
                self._set_state("dead")
                return

            self._last_hb = time.time()
            # A 7.1 GB SDXL checkpoint needs ~11-12 min to mount + parse on
            # Kaggle (measured live), so the warm budget must be generous  - 
            # the session then answers every following job in 6-9 s.
            warm_deadline = time.time() + 900
            while not self._stop:
                time.sleep(5)
                try:
                    st = b._get_kernel_status_for(self._slug)
                except Exception:
                    st = "unknown"
                if st in ("error", "cancel_requested", "cancel_acknowledged"):
                    tail = _kernel_log_tail(b, self._slug, 500)
                    self.progress.emit("❌ Cache session failed" + (f" - {tail[-180:]}" if tail else ""))
                    self._set_state("dead")
                    return
                if st == "complete" and time.time() - self._last_hb > 20:
                    self.progress.emit("💤 Cache session ended - requeueing pending jobs")
                    self._set_state("dead")
                    return
                if self.state == "warming" and time.time() > warm_deadline:
                    self.progress.emit("⏰ Cache didn't warm in 15min - using script mode")
                    self._set_state("dead")
                    return
        except Exception as e:
            dev_log(f"[cache] worker error: {e}")
            self._set_state("dead")


# ─── Fallback helpers (kept for script-mode path when relay fails) ─────────


def dataset_exists(backend: KaggleImageBackend, slug: str) -> bool:
    try:
        r = backend._session.get(f"{KAGGLE_API_BASE}/datasets/list",
                                 params={"user": backend.username, "page": 1, "pageSize": 100})
        if r.status_code != 200:
            return False
        for d in r.json() or []:
            ref = d.get("ref") or ""
            if ref.endswith("/" + slug):
                return True
        return False
    except Exception:
        return False


def _queue_read(backend: KaggleImageBackend) -> dict:
    """Download latest queue.json from the queue dataset (fallback)."""
    url = f"{KAGGLE_API_BASE}/datasets/download/{backend.username}/{QUEUE_DATASET}"
    try:
        r = backend._session.get(url, timeout=15)
        if r.status_code == 200:
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            for name in zf.namelist():
                if name.endswith("queue.json"):
                    return json.loads(zf.read(name).decode("utf-8"))
    except Exception:
        pass
    return {}


def _queue_write(backend: KaggleImageBackend, queue: dict) -> None:
    """Upload a new version of the queue dataset containing queue.json (fallback)."""
    from cellium.services.kaggle_image import _upload_blob, _create_version, create_dataset
    slug = QUEUE_DATASET
    payload = json.dumps(queue).encode("utf-8")
    if not dataset_exists(backend, slug):
        create_dataset(backend, slug, "Cellium queue")
    token = _upload_blob(backend, "queue.json", payload, "application/json")
    _create_version(backend, slug, [{"token": token}], "queue update")


def _kernel_files(backend: KaggleImageBackend, slug: str) -> list:
    body = {"userName": backend.username, "kernelSlug": slug, "pageSize": 100}
    r = backend._kernels_call("/kernels/output", body, timeout=30)
    if r is None or r.status_code != 200:
        return []
    d = r.json()
    return d.get("files") or []


def _dl(backend: KaggleImageBackend, file_entry):
    url = file_entry.get("url")
    name = file_entry.get("fileName") or file_entry.get("file_name") or ""
    if not url:
        return b"", name
    rr = requests.get(url, timeout=120)
    rr.raise_for_status()
    return rr.content, name


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