#!/usr/bin/env python3
"""
Kaggle Cloud Image Generation Backend (BYOK)

Each user enters their own Kaggle username + API key. Generation runs on
the user's account/quota. The app makes direct HTTPS calls to Kaggle  - 
no middleman server, no CLI subprocesses needed.

Architecture:
  PC App (user key) ── POST /kernels/push (script w/ prompt baked in)
                        GET /kernels/status (5s poll)
                        GET /kernels/output ──► PNG + meta.json
"""

import json
import time
import threading
import hashlib
from pathlib import Path
from typing import Optional, Callable, Literal
from dataclasses import dataclass, field
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth

from cellium.core.config import USER_DATA_DIR
from cellium.core.logger import dev_log


# ─── Constants ──────────────────────────────────────────────────────────────
KAGGLE_API_BASE = "https://www.kaggle.com/api/v1"
KAGGLE_KERNEL_SLUG = "cloud-render-w1"
POLL_INTERVAL = 5.0
TOTAL_TIMEOUT = 15 * 60  # 15 minutes
MAX_PUSH_RETRIES = 3

# Default public SDXL model (non-gated)
DEFAULT_HF_MODEL = "lykon/dreamshaper-xl-v2-turbo"
# Alternative: "RunDiffusion/Juggernaut-XL-v9"

# ─── Data Classes ───────────────────────────────────────────────────────────
@dataclass
class ModelConfig:
    """Configuration for the model to use on Kaggle."""
    mode: Literal["huggingface", "civitai"] = "huggingface"
    # HF mode
    hf_model: str = DEFAULT_HF_MODEL
    hf_token: str = ""
    # Civitai mode
    civitai_url: str = ""
    civitai_token: str = ""
    # Optional LoRA
    lora_url: str = ""
    lora_token: str = ""
    lora_strength: float = 0.9
    # Cloud storage (Option A): mount a private Kaggle dataset holding the
    # model file so the kernel loads it in ~5 s instead of re-downloading.
    dataset_slug: str = ""


# ─── Model presets (Henny's Colab engines + public HF default) ─────────────
# These are the three engines Henny runs in the Art Studio Mini App
# ("Google Colab/Art Studio/Mini App.py") - DreamShaper stays as the fast
# public-HF default, the others are Mini App's exact engines.
#
# Civitai ids below are MODEL VERSION ids ("/api/download/models/<versionId>")
# and are served as-is. A *model* id is a trap: "/api/download/models/133005"
# serves the page's LATEST file (a 151 MB "MaouBigV1.2.safetensors"), not
# Juggernaut XL. Verified live:
#   Nova Cartoon XL v6.0      → 2329740 → 6.94 GB (Illustrious base)
#   Oops! All Toons v1.0      → 1445455 → 6.62 GB (Illustrious base)
#   Juggernaut XL Ragnarok    → 1759168 → 7.11 GB (SDXL 1.0 base)
#   Cartoony Anime Style LoRA → 1524099 → Juukyuu_Style.safetensors, 228 MB
MODEL_PRESETS: list[dict] = [
    {"name": "✨ DreamShaper XL Turbo v2 (fast, public HF)", "mode": "huggingface",
     "hf_model": "lykon/dreamshaper-xl-v2-turbo", "steps": 8, "guidance": 2.0, "lora_url": ""},
    {"name": "🎨 Nova Cartoon XL (Civitai)", "mode": "civitai",
     "civitai_url": "https://civitai.com/api/download/models/2329740", "steps": 33, "guidance": 7.0,
     "lora_url": "https://civitai.com/api/download/models/1524099"},
    {"name": "📸 Juggernaut XL Ragnarok (Civitai)", "mode": "civitai",
     "civitai_url": "https://civitai.com/api/download/models/1759168", "steps": 33, "guidance": 7.0,
     "lora_url": ""},
    {"name": "🔧 Custom (from Settings)", "mode": "custom", "hf_model": "", "civitai_url": "",
     "steps": 28, "guidance": 6.5, "lora_url": ""},
]


# SDXL quality prefix (same idea as the Mini App's style prefix).
# "source_cartoon" is included because the Mini App puts it on every SDXL
# render (score_9, score_8_up, score_7_up, source_cartoon, masterpiece...).
SDXL_QUALITY_PREFIX = ("score_9, score_8_up, score_7_up, source_cartoon, masterpiece, "
                       "best quality, vibrant colors, full color, ")


def enhance_prompt(prompt: str, arch: str = "sdxl") -> str:
    """User-friendly '✨ Enhance' - wraps a short idea into a rich tag list.

    Deterministic (no API key needed): prepends the SDXL quality prefix and,
    if the prompt looks like a bare idea, expands it with sensible defaults.
    The Mini App's Mistral 'director brain' can be layered on top later.
    """
    p = (prompt or "").strip().rstrip(",")
    if not p:
        return p
    low = p.lower()
    prefix = SDXL_QUALITY_PREFIX if arch == "sdxl" else "masterpiece, best quality, "
    if low.startswith(("score_", "masterpiece")):
        return p  # already enhanced
    # if it's very short (<= 6 words) treat as an idea and flesh it out a touch
    words = p.split()
    if len(words) <= 6 and not p.endswith(("...", "…")):
        p = f"{p}, detailed illustration, cinematic lighting, sharp focus, 8k, highly detailed"
    return prefix + p


def preset_by_name(name: str) -> Optional[dict]:
    for p in MODEL_PRESETS:
        if p["name"] == name:
            return p
    return None


def build_model_config(settings: dict, preset_name: str = "", **overrides) -> ModelConfig:
    """Build a ModelConfig from settings, optionally overridden by a named preset."""
    mc = ModelConfig(
        mode=settings.get("kaggle_model_mode", "huggingface"),
        hf_model=settings.get("kaggle_hf_model", DEFAULT_HF_MODEL),
        hf_token=settings.get("kaggle_hf_token", ""),
        civitai_url=settings.get("kaggle_civitai_url", ""),
        civitai_token=settings.get("kaggle_civitai_token", ""),
        lora_url=settings.get("kaggle_lora_url", ""),
        lora_token=settings.get("kaggle_civitai_token", ""),
        lora_strength=float(settings.get("kaggle_lora_strength", 0.9)),
    )
    p = preset_by_name(preset_name) if preset_name else None
    if p and p.get("mode") != "custom":
        mc.mode = p["mode"]
        if p.get("hf_model"):
            mc.hf_model = p["hf_model"]
        if p.get("civitai_url"):
            mc.civitai_url = p["civitai_url"]
        if p.get("lora_url") is not None:
            mc.lora_url = p["lora_url"]
    for k, v in overrides.items():
        if v is not None and hasattr(mc, k):
            setattr(mc, k, v)
    # PHASE 5: mount the healthy server-side cache for the chosen preset, so
    # the kernel reads /kaggle/input/<slug>/model.safetensors instead of
    # downloading from Civitai (30–60s render instead of ~6 min).
    try:
        from cellium.services.model_cache import cached_slug_for_preset
        pick = preset_name or settings.get("kaggle_preset", "")
        cached = (settings.get("kaggle_cache_map") or {}).get(pick) or {}
        if cached.get("healthy") and cached.get("slug"):
            mc.dataset_slug = str(cached["slug"])
    except Exception:
        pass
    return mc

@dataclass
class GenerationConfig:
    """Runtime generation parameters."""
    prompt: str
    negative_prompt: str = ""
    steps: int = 28
    width: int = 832
    height: int = 1216
    seed: int = -1
    guidance_scale: float = 6.5
    batch: int = 1
    init_b64: str = ""      # base64 image for img2img "edit last"
    denoise: float = 0.75   # img2img strength

@dataclass
class GenerationResult:
    """Result of a successful generation (batch = list of images)."""
    image_path: Path
    seed: int
    elapsed_seconds: float
    paths: list = field(default_factory=list)      # all image paths
    seeds: list = field(default_factory=list)      # all seeds

@dataclass
class GenerationError(Exception):
    """Structured error from the backend."""
    code: str
    message: str
    detail: str = ""
    recoverable: bool = False


# ─── Kernel Script Template ─────────────────────────────────────────────────
# Uses unique ``__TOKEN__`` placeholders filled with ``str.replace`` (NOT
# ``str.format``) so braces/dicts in the generated code never need escaping,
# and every user-supplied string is embedded as a ``repr()``-safe literal  - 
# prompt/token/URL can never break out of its string and inject code.
KERNEL_TEMPLATE = '''import json, time, subprocess, sys
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
'''


# ─── Backend Class ──────────────────────────────────────────────────────────
class KaggleImageBackend:
    """
    Pure-requests Kaggle image generation backend.
    
    Thread-safe: uses a lock to enforce one concurrent job per credentials.
    Extra requests queue locally in the app.
    """
    
    def __init__(
        self,
        username: str,
        api_key: str,
        model_config: ModelConfig,
        output_dir: Optional[Path] = None,
        progress_cb: Optional[Callable[[str, str], None]] = None,
        auto_clean: bool = True,
    ):
        self.username = username.strip()
        self.api_key = api_key.strip()
        self.model_config = model_config
        self.output_dir = output_dir or (USER_DATA_DIR / "generated_images")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.progress_cb = progress_cb
        #: name of the active model preset - used by the Phase 5 cache probe
        self.preset_name = ""
        #: whether to wipe Kaggle traces (notebook script & outputs) after download
        self.auto_clean = auto_clean
        
        self._lock = threading.Lock()
        self._job_queue: list[tuple[GenerationConfig, threading.Event, dict]] = []
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._current_job_cancel = False
        
        self._session = requests.Session()
        self._session.auth = HTTPBasicAuth(self.username, self.api_key)
        self._session.headers.update({"User-Agent": "Cellium/1.0"})
    
    def _report(self, stage: str, detail: str = "") -> None:
        """Report progress via callback."""
        if self.progress_cb:
            try:
                self.progress_cb(stage, detail)
            except Exception:
                pass
        dev_log(f"[KaggleImg] {stage}: {detail}")
    
    # ─── Public API ─────────────────────────────────────────────────────────
    
    def validate_credentials(self) -> tuple[bool, str]:
        """
        Validate Kaggle credentials.
        Returns (success, message).
        """
        try:
            resp = self._session.get(
                f"{KAGGLE_API_BASE}/datasets/list",
                params={"user": self.username, "page": 1},
                timeout=15,
            )
            if resp.status_code == 200:
                return True, "Credentials valid"
            elif resp.status_code == 401:
                return False, "Invalid Kaggle username or API key"
            else:
                return False, f"Unexpected response: {resp.status_code}"
        except requests.exceptions.RequestException as e:
            return False, f"Network error: {e}"
    
    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        steps: int = 28,
        width: int = 832,
        height: int = 1216,
        seed: int = -1,
        guidance_scale: float = 6.5,
        batch: int = 1,
        init_b64: str = "",
        denoise: float = 0.75,
    ) -> GenerationResult:
        """
        Synchronous generation - blocks until complete.
        Raises GenerationError on failure.
        """
        # PHASE 5: pick up a freshly built server-side cache before the kernel
        # is pushed (JSON-only probe, no model bytes).
        self._maybe_mount_cache()
        cfg = GenerationConfig(
            prompt=prompt,
            negative_prompt=negative_prompt,
            steps=steps,
            width=width,
            height=height,
            seed=seed,
            guidance_scale=guidance_scale,
            batch=max(1, int(batch)),
            init_b64=init_b64 or "",
            denoise=denoise,
        )
        return self._run_generation(cfg)

    def generate_async(
        self,
        prompt: str,
        negative_prompt: str = "",
        steps: int = 28,
        width: int = 832,
        height: int = 1216,
        seed: int = -1,
        guidance_scale: float = 6.5,
        batch: int = 1,
    ) -> tuple[threading.Event, dict]:
        """
        Queue generation and return (done_event, result_dict).
        result_dict will contain either {"result": GenerationResult} or {"error": GenerationError}.
        """
        cfg = GenerationConfig(
            prompt=prompt,
            negative_prompt=negative_prompt,
            steps=steps,
            width=width,
            height=height,
            seed=seed,
            guidance_scale=guidance_scale,
            batch=max(1, int(batch)),
        )
        done = threading.Event()
        result: dict = {}
        with self._lock:
            self._job_queue.append((cfg, done, result))
            self._ensure_worker()
        return done, result
    
    def cancel_current(self) -> bool:
        """Cancel the currently running job if any."""
        self._current_job_cancel = True
        return True
    
    def queue_length(self) -> int:
        """Return number of pending jobs."""
        with self._lock:
            return len(self._job_queue)
    
    def shutdown(self) -> None:
        """Stop worker and cleanup."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        self._session.close()
    
    # ─── Internal: Job Queue Worker ─────────────────────────────────────────
    
    def _ensure_worker(self) -> None:
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()
    
    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            job = None
            with self._lock:
                if self._job_queue:
                    job = self._job_queue.pop(0)
            
            if job:
                cfg, done, result = job
                try:
                    res = self._run_generation(cfg)
                    result["result"] = res
                except GenerationError as e:
                    result["error"] = e
                except Exception as e:
                    result["error"] = GenerationError("internal", str(e))
                finally:
                    done.set()
            else:
                time.sleep(0.5)
    
    # ─── Internal: Core Generation Logic ────────────────────────────────────
    
    def _run_generation(self, cfg: GenerationConfig) -> GenerationResult:
        self._current_job_cancel = False
        start_time = time.time()
        
        # 1. Build kernel script
        script = self._build_kernel_script(cfg)
        
        # 2. Check if a job is already running/queued on Kaggle
        self._report("checking_status")
        status = self._get_kernel_status()
        if status in ("queued", "running"):
            self._report("waiting_for_slot", f"Kaggle job is {status}, waiting...")
            # Wait for it to finish (with timeout)
            wait_start = time.time()
            while status in ("queued", "running"):
                if self._current_job_cancel:
                    raise GenerationError("cancelled", "Cancelled by user", recoverable=True)
                if time.time() - wait_start > TOTAL_TIMEOUT:
                    raise GenerationError("timeout", "Timed out waiting for previous job")
                time.sleep(POLL_INTERVAL)
                status = self._get_kernel_status()
        
        # 3. Push new job
        self._report("pushing")
        self._push_kernel(script)
        
        # 4. Poll for completion
        self._report("queued")
        poll_start = time.time()
        # Scale timeout dynamically: ~75s per image + 6 min base buffer
        dynamic_timeout = max(TOTAL_TIMEOUT, int(cfg.batch * 90 + 360))
        last_log_fetch = 0.0

        while True:
            if self._current_job_cancel:
                # Try to cancel on Kaggle side
                self._cancel_kernel()
                raise GenerationError("cancelled", "Cancelled by user", recoverable=True)
            
            elapsed = time.time() - poll_start
            if elapsed > dynamic_timeout:
                raise GenerationError("timeout", f"Generation timed out ({int(dynamic_timeout/60)} min)", recoverable=True)
            
            status = self._get_kernel_status()
            if status == "complete":
                self._report("complete")
                break
            elif status in ("error", "cancelled"):
                failure = self._get_failure_message()
                tail = self._fetch_log_tail(1800)
                if tail:
                    failure = (failure + "\n--- kernel log tail ---\n" + tail).strip()
                low = failure.lower()
                if "quota" in low or "accelerator" in low or ("gpu" in low and "quota" in low):
                    raise GenerationError(
                        "quota", "Weekly GPU quota exhausted (30h/wk) - resets Monday. "
                        f"Detail: {failure}", recoverable=False)
                if status == "cancelled":
                    raise GenerationError("cancelled", failure or "Kaggle job was cancelled",
                                          recoverable=True)
                raise GenerationError("kaggle_error", f"Kaggle job failed: {failure}")
            elif status == "queued":
                self._report("queued", f"Waiting for GPU... ({int(elapsed)}s)")
            elif status == "running":
                # Setup phase takes ~45-60s on Kaggle (CUDA boot, diffusers, model/lora load)
                setup_est = 60.0
                est_per_img = max(30.0, float(cfg.steps) * 2.2)
                
                live_msg = ""
                # Attempt log tail occasionally (every 30s) without spamming Kaggle API
                now = time.time()
                if now - last_log_fetch > 30.0:
                    last_log_fetch = now
                    try:
                        tail = self._fetch_log_tail(1200)
                        if tail:
                            lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
                            clean = [ln for ln in lines if ln and not ln.startswith("{") and not ln.startswith("[{")]
                            if clean:
                                last = clean[-1]
                                if len(last) > 55:
                                    last = last[:52] + "..."
                                live_msg = f"{last} ({int(elapsed)}s)"
                    except Exception:
                        pass
                
                if not live_msg:
                    if elapsed < setup_est:
                        live_msg = f"Booting GPU & loading model... ({int(elapsed)}s)"
                    else:
                        infer_elapsed = elapsed - setup_est
                        cur_img = min(cfg.batch, max(1, int(infer_elapsed / est_per_img) + 1))
                        total_expected = setup_est + (cfg.batch * est_per_img)
                        pct = min(98, max(5, int((elapsed / total_expected) * 100)))
                        if cfg.batch > 1:
                            live_msg = f"Rendering {cur_img}/{cfg.batch} (~{pct}%) ({int(elapsed)}s)"
                        else:
                            live_msg = f"Sampling steps (~{pct}%) ({int(elapsed)}s)"
                
                self._report("running", live_msg)

            time.sleep(POLL_INTERVAL)

        # 5. Fetch outputs (all out*.png + meta.json)
        self._report("downloading")
        paths, meta = self._fetch_outputs(cfg.prompt[:50])

        seeds = list(meta.get("seeds") or [])
        if not seeds and meta.get("seed") is not None:
            seeds = [meta.get("seed")]
        elapsed = meta.get("seconds", time.time() - start_time)
        image_path = paths[0] if paths else Path(self.output_dir / "out.png")
        seed = seeds[0] if seeds else -1

        # 6. Stealth Wipe: overwrite kernel script and empty output tab on Kaggle
        if getattr(self, "auto_clean", True):
            self._wipe_cloud_traces_async()

        self._report("done", f"Saved {len(paths)} image(s) to {self.output_dir.name}")
        return GenerationResult(image_path=image_path, seed=seed, elapsed_seconds=elapsed,
                                paths=paths, seeds=seeds)
    
    def _maybe_mount_cache(self) -> None:
        """PHASE 5 - mount the healthy server-side cache for the active preset.

        Cheap: one ~200-byte JSON GET per Civitai preset (via
        ``/datasets/view``). When a cache is healthy the kernel reads
        ``/kaggle/input/<slug>/model.safetensors`` instead of re-downloading
        ~7 GB from Civitai - so "Cache now" takes effect on the very next
        render, without reopening Settings.
        """
        name = (getattr(self, "preset_name", "") or "").strip()
        if not name and self.model_config.mode == "civitai":
            # Fallback: find matching preset by civitai_url
            for p in MODEL_PRESETS:
                if p.get("mode") == "civitai" and p.get("civitai_url") == self.model_config.civitai_url:
                    name = p.get("name", "")
                    self.preset_name = name
                    break
        if not name or self.model_config.mode != "civitai":
            return
        try:
            from cellium.services.model_cache import refresh_cache_map
            presets = list(MODEL_PRESETS)
            if name not in [p.get("name") for p in presets]:
                presets.append({"name": name, "mode": "civitai"})
            cmap = refresh_cache_map(self, presets)
            entry = cmap.get(name) or {}
            if entry.get("healthy"):
                self.model_config.dataset_slug = entry["slug"]
                dev_log(f"[model-cache] mounted {entry['slug']} for {name}")
            elif entry.get("exists"):
                dev_log(f"[model-cache] {name}: empty shell "
                        f"({entry.get('bytes')} B) - falling back to Civitai")
        except Exception as e:
            dev_log(f"[model-cache] discovery failed: {e}")

    def _build_kernel_script(self, cfg: GenerationConfig) -> str:
        """Build the Python script to run on Kaggle.

        Every user-supplied value is embedded as a ``repr()`` literal via a
        plain ``str.replace`` on ``__TOKEN__`` placeholders, so a prompt or
        token can never break out of its string literal and inject code.
        """
        mc = self.model_config

        # ── Model loader ──────────────────────────────────────────────────
        if mc.mode == "civitai" and mc.civitai_url.strip():
            token_lit = repr(mc.civitai_token) if mc.civitai_token else "None"
            # Resolve civitai.com/models/<id> pages to the best SDXL file via
            # the Civitai API (same idea as the Colab's civitai_pick); direct
            # download URLs pass straight through.
            model_loader = (
                "import requests, re\n"
                f"TOK = {token_lit}\n"
                "def _cv_headers():\n"
                "    return {\"Authorization\": \"Bearer \" + TOK} if TOK else {}\n"
                "def _cv_resolve(url):\n"
                "    # A VERSION id ('/api/download/models/<id>') is served as-is - that is\n"
                "    # the safe form. A MODEL id ('/models/<id>') serves the page's LATEST\n"
                "    # file, which can be a completely different checkpoint, so it has to\n"
                "    # be resolved through the Civitai API first.\n"
                "    if re.search(r'civitai.com/api/download/models/[0-9]+', url or ''):\n"
                "        return url\n"
                "    m = re.search(r'civitai.com/models/([0-9]+)', url or '')\n"
                "    if not m:\n"
                "        return url\n"
                "    mid = m.group(1)\n"
                "    direct = 'https://civitai.com/api/download/models/' + mid\n"
                "    try:\n"
                "        r = requests.get('https://civitai.com/api/v1/models/' + mid, headers=_cv_headers(), timeout=20)\n"
                "        r.raise_for_status()\n"
                "        vers = (r.json() or {}).get('modelVersions', []) or []\n"
                "        def good(v):\n"
                "            b = (v.get('baseModel') or '').upper()\n"
                "            n = (v.get('name') or '').lower()\n"
                "            return ('SDXL' in b or 'ILLUSTRIOUS' in b) and 'inpaint' not in n\n"
                "        pick = next((v for v in vers if good(v)), None)\n"
                "        if pick is None:\n"
                "            pick = next((v for v in vers if 'inpaint' not in (v.get('name') or '').lower()), None)\n"
                "        if pick is None and vers:\n"
                "            pick = vers[0]\n"
                "        if pick is not None:\n"
                "            for f in (pick.get('files') or []):\n"
                "                if (f.get('name') or '').lower().endswith('.safetensors'):\n"
                "                    return f.get('downloadUrl') or f.get('url') or direct\n"
                "            if pick.get('id'):\n"
                "                return 'https://civitai.com/api/download/models/' + str(pick['id'])\n"
                "    except Exception as e:\n"
                "        print('Civitai API resolve failed, using direct download:', e)\n"
                "    return direct\n"
                "import glob as _glob\n"
                "_slug = CFG.get('dataset_slug') or ''\n"
                "# Kaggle mounts datasets under /kaggle/input/datasets/<owner>/<slug>/... or /kaggle/input/<slug>/...\n"
                "_mounted = []\n"
                "if _slug:\n"
                "    _cands = [p for p in _glob.glob('/kaggle/input/**/*.safetensors', recursive=True) if _slug in p and 'lora' not in p.lower()]\n"
                "    if _cands:\n"
                "        _mounted = _cands\n"
                "if _mounted:\n"
                "    MODEL_PATH = _mounted[0]\n"
                "    klog('⚡ Loaded model from mounted cloud cache:', MODEL_PATH)\n"
                "else:\n"
                "    URL = _cv_resolve(CFG[\"civitai_url\"])\n"
                "    klog('Civitai resolved ->', URL[:120])\n"
                "    r = requests.get(URL, headers=_cv_headers(), stream=True, timeout=300)\n"
                "    r.raise_for_status()\n"
                "    _dl_total = 0\n"
                '    with open("/kaggle/working/model.safetensors", "wb") as f:\n'
                "        for chunk in r.iter_content(1 << 22):\n"
                "            f.write(chunk)\n"
                "            _dl_total += len(chunk)\n"
                "            if _dl_total % (200 * 1024 * 1024) < len(chunk):\n"
                "                klog(f'Downloading model: {_dl_total // (1024*1024)} MB')\n"
                "    klog('Model downloaded successfully.')\n"
                "    MODEL_PATH = '/kaggle/working/model.safetensors'\n"
                "klog('Loading SDXL pipeline from safetensors...')\n"
                "pipe = StableDiffusionXLPipeline.from_single_file(\n"
                "    MODEL_PATH, torch_dtype=torch.float16)\n"
                "klog('SDXL pipeline loaded into memory.')"
            )
        else:
            token_arg = f"\n    token={mc.hf_token!r}," if mc.hf_token else ""
            model_loader = (
                f"klog('Loading HuggingFace model {mc.hf_model}...')\n"
                "pipe = StableDiffusionXLPipeline.from_pretrained(\n"
                f"    {mc.hf_model!r}, torch_dtype=torch.float16,{token_arg})\n"
                "klog('HuggingFace model loaded.')"
            )

        # ── Optional LoRA ─────────────────────────────────────────────────
        if mc.lora_url.strip():
            lora_tok = getattr(mc, "lora_token", "") or mc.civitai_token
            if lora_tok:
                lora_headers = ('headers = {"Authorization": "Bearer " + '
                                + repr(lora_tok) + '}')
            else:
                lora_headers = "headers = {}"
            model_loader += (
                "\n# ── Optional LoRA - mounted cache first, download only as a fallback ──\n"
                'if CFG.get("lora_url"):\n'
                "    try:\n"
                "        import glob as _lg\n"
                "        _sl = CFG.get('dataset_slug') or ''\n"
                "        _lm = [p for p in _lg.glob('/kaggle/input/**/lora.safetensors', recursive=True)\n"
                "               if _sl and _sl in p] if _sl else []\n"
                "        if _lm:\n"
                "            _lora_path = _lm[0]\n"
                '            print("LoRA from mounted cloud cache:", _lora_path)\n'
                "        else:\n"
                "            import requests\n"
                f"            {lora_headers}\n"
                '            r = requests.get(CFG["lora_url"], headers=headers, stream=True, timeout=180)\n'
                "            r.raise_for_status()\n"
                '            with open("/kaggle/working/lora.safetensors", "wb") as f:\n'
                "                for chunk in r.iter_content(1 << 22):\n"
                "                    f.write(chunk)\n"
                '            _lora_path = "/kaggle/working/lora.safetensors"\n'
                '        pipe.load_lora_weights(_lora_path)\n'
                "        _names = set()\n"
                "        try:\n"
                "            for _v in pipe.get_list_adapters().values():\n"
                "                _names.update(_v)\n"
                "        except Exception:\n"
                "            pass\n"
                "        if not _names:\n"
                "            try:\n"
                "                pipe.unload_lora_weights()\n"
                "            except Exception:\n"
                "                pass\n"
                '            print("LoRA registered ZERO adapters (arch mismatch) - unloaded")\n'
                "        else:\n"
                "            _names = sorted(_names)\n"
                "            pipe.set_adapters(_names, adapter_weights=[CFG.get('lora_strength', 0.9)] * len(_names))\n"
                '            print("LoRA applied", _names)\n'
                "    except Exception as e:\n"
                '        print("LoRA skipped (download/load failed):", e)\n'
            )

        # ── CFG payload - JSON-encoded, then repr'd into a Python literal ──
        cfg_dict = {
            "prompt": cfg.prompt,
            "neg": cfg.negative_prompt,
            "steps": cfg.steps,
            "w": cfg.width,
            "h": cfg.height,
            "seed": cfg.seed,
            "guidance": cfg.guidance_scale,
            "batch": cfg.batch,
            "init_b64": cfg.init_b64,
            "denoise": cfg.denoise,
            "dataset_slug": mc.dataset_slug or "",
            "model": mc.hf_model if mc.mode == "huggingface" else "",
            "civitai_url": mc.civitai_url if mc.mode == "civitai" else "",
            "lora_url": mc.lora_url or "",
            "lora_strength": mc.lora_strength,
        }
        cfg_json = repr(json.dumps(cfg_dict, ensure_ascii=False))

        return (KERNEL_TEMPLATE
                .replace("__CFG_JSON__", cfg_json)
                .replace("__MODEL_LOADER__", model_loader))
    
    # ─── Kaggle API Calls ───────────────────────────────────────────────────
    
    def _push_kernel(self, script: str) -> None:
        """Push kernel script to Kaggle. Retries on 429."""
        # Field names verified against kagglesdk (Kaggle API v2.2.5) - camelCase JSON.
        dataset_sources = []
        if getattr(self.model_config, "dataset_slug", ""):
            dataset_sources = [f"{self.username}/{self.model_config.dataset_slug}"]
        payload = {
            "slug": f"{self.username}/{KAGGLE_KERNEL_SLUG}",
            "newTitle": "Cloud Render W1",
            "text": script,
            "language": "python",
            "kernelType": "script",
            "isPrivate": True,
            "enableGpu": True,
            "enableInternet": True,
            "datasetDataSources": dataset_sources,
            "competitionDataSources": [],
            "kernelDataSources": [],
            "modelDataSources": [],
            "categoryIds": [],
            # Safety: hard-cap the session at 45 min so a hung script can never
            # burn the whole weekly GPU quota.
            "sessionTimeoutSeconds": 2700,
        }
        
        for attempt in range(MAX_PUSH_RETRIES):
            try:
                resp = self._session.post(
                    f"{KAGGLE_API_BASE}/kernels/push",
                    json=payload,
                    timeout=30,
                )
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    self._report("rate_limited", f"Retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                dev_log(f"[KaggleImg] Push response: {data}")
                return
            except requests.exceptions.RequestException as e:
                if attempt == MAX_PUSH_RETRIES - 1:
                    raise GenerationError("push_failed", f"Failed to push kernel: {e}")
                time.sleep(2 ** attempt)
    
    def _kernels_call(self, path: str, body: dict, timeout: float = 30) -> Optional[requests.Response]:
        """Call a kernels endpoint the way the official kagglesdk client does:
        POST with a camelCase JSON body. Falls back to GET-with-query-params
        (the older public REST style) if the server rejects POST.
        Returns None on 404 (job not found)."""
        url = f"{KAGGLE_API_BASE}{path}"
        resp = self._session.post(url, json=body, timeout=timeout)
        if resp.status_code in (404, 405):
            # Legacy GET style
            resp = self._session.get(url, params=body, timeout=timeout)
        return resp

    # Status enum names (kagglesdk KernelWorkerStatus), lowercased.
    _ACTIVE = {"queued", "running", "new_script"}
    _FAILED = {"error", "cancel_requested", "cancel_acknowledged"}

    def _get_kernel_status(self) -> str:
        return self._get_kernel_status_for(KAGGLE_KERNEL_SLUG)

    def _get_kernel_status_for(self, slug: str) -> str:
        """Get kernel status for an arbitrary slug, normalised to
        queued|running|complete|error|cancelled|not_found"""
        body = {"userName": self.username, "kernelSlug": slug}
        try:
            resp = self._kernels_call("/kernels/status", body, timeout=15)
            if resp is None or resp.status_code == 404:
                return "not_found"
            resp.raise_for_status()
            data = resp.json()
            status = str(data.get("status", "unknown")).lower()
            # Map the full enum vocabulary onto our small set.
            if status in self._FAILED:
                return "error" if status == "error" else "cancelled"
            if status == "complete":
                return "complete"
            if status in self._ACTIVE:
                return status if status != "new_script" else "queued"
            return status or "unknown"
        except requests.exceptions.RequestException:
            return "unknown"

    def _get_failure_message(self) -> str:
        """Get failure message from kernel status."""
        body = {"userName": self.username, "kernelSlug": KAGGLE_KERNEL_SLUG}
        try:
            resp = self._kernels_call("/kernels/status", body, timeout=15)
            if resp is None:
                return "Unknown error"
            resp.raise_for_status()
            data = resp.json()
            msg = data.get("failureMessage") or data.get("failure_message") or ""
            return msg or "Unknown error"
        except Exception:
            return "Unknown error"

    def _wipe_cloud_traces_async(self) -> None:
        """Asynchronously sanitize the Kaggle notebook and wipe working files."""
        def _wipe():
            try:
                self.wipe_cloud_traces()
            except Exception as e:
                dev_log(f"[KaggleImg] Stealth wipe notice: {e}")

        threading.Thread(target=_wipe, daemon=True).start()

    def wipe_cloud_traces(self) -> bool:
        """Sanitize the Kaggle kernel script and wipe output files so no trace remains.
        Uses enableGpu=False (CPU only, zero GPU quota).
        """
        clean_script = (
            "import os, shutil\n"
            "print('[stealth] Sanitizing cloud session...')\n"
            "w = '/kaggle/working'\n"
            "if os.path.exists(w):\n"
            "    for f in os.listdir(w):\n"
            "        p = os.path.join(w, f)\n"
            "        try:\n"
            "            if os.path.isfile(p) or os.path.islink(p):\n"
            "                os.remove(p)\n"
            "            elif os.path.isdir(p):\n"
            "                shutil.rmtree(p)\n"
            "        except Exception:\n"
            "            pass\n"
            "print('[stealth] Cloud traces cleared.')\n"
        )
        payload = {
            "slug": f"{self.username}/{KAGGLE_KERNEL_SLUG}",
            "newTitle": "Cloud Render W1",
            "text": clean_script,
            "language": "python",
            "kernelType": "script",
            "isPrivate": True,
            "enableGpu": False,
            "enableInternet": False,
            "datasetDataSources": [],
            "competitionDataSources": [],
            "kernelDataSources": [],
            "modelDataSources": [],
            "categoryIds": [],
        }
        try:
            r = self._session.post(f"{KAGGLE_API_BASE}/kernels/push", json=payload, timeout=30)
            ok = r.status_code in (200, 201)
            if ok:
                dev_log(f"[KaggleImg] Stealth wipe pushed successfully to {KAGGLE_KERNEL_SLUG}")
            else:
                dev_log(f"[KaggleImg] Stealth wipe push returned {r.status_code}: {r.text[:120]}")
            return ok
        except Exception as e:
            dev_log(f"[KaggleImg] Stealth wipe failed: {e}")
            return False

    def _cancel_kernel(self) -> None:
        """Best-effort cancel of the running session (public API has no
        direct cancel; we just stop waiting - the 45-min session cap and
        script auto-teardown keep quota safe)."""
        dev_log("[KaggleImg] Cancel requested - stopping wait (kernel auto-tears down)")

    def _fetch_log_tail(self, n: int = 1800) -> str:
        """Return the last ~n chars of the kernel's streamed log (for live progress and errors)."""
        body = {"userName": self.username, "kernelSlug": KAGGLE_KERNEL_SLUG, "pageSize": 100}
        try:
            r = self._kernels_call("/kernels/output", body, timeout=30)
            if r is None:
                return ""
            r.raise_for_status()
            d = r.json()
            log = d.get("log") or ""
            if not log:
                return ""
            parts = []
            try:
                # Kaggle output endpoint often returns a JSON-serialized list of log events
                parsed = json.loads(log)
                if isinstance(parsed, list):
                    for item in parsed[-100:]:
                        if isinstance(item, dict) and "data" in item:
                            parts.append(str(item["data"]))
            except Exception:
                pass

            if not parts:
                for line in log.splitlines()[-120:]:
                    cleaned = line.strip().lstrip("[").rstrip("]").strip().lstrip(",")
                    if not cleaned:
                        continue
                    try:
                        o = json.loads(cleaned)
                        if isinstance(o, dict) and "data" in o:
                            parts.append(str(o["data"]))
                            continue
                    except Exception:
                        pass
                    parts.append(cleaned)
            return "".join(parts)[-n:]
        except Exception:
            return ""

    def _fetch_outputs(self, prompt_hint: str) -> tuple[list, dict]:
        """Fetch output files from Kaggle, save locally, return (paths, meta)."""
        body = {"userName": self.username, "kernelSlug": KAGGLE_KERNEL_SLUG}
        try:
            resp = self._kernels_call("/kernels/output", body, timeout=60)
            if resp is None:
                raise GenerationError("no_output", "Kernel output not found")
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_prompt = "".join(c if c.isalnum() or c in " -_" else "_" for c in prompt_hint)[:40]

            # Binary fallback (single raw file)
            if "application/json" not in content_type:
                img_path = self.output_dir / f"kaggle_{ts}_{safe_prompt}.png"
                img_path.write_bytes(resp.content)
                return [img_path], {}

            data = resp.json()
            files = data.get("files", []) or []
            token = data.get("nextPageToken") or data.get("next_page_token")
            while token:
                body2 = {"userName": self.username, "kernelSlug": KAGGLE_KERNEL_SLUG,
                         "pageToken": token, "pageSize": 100}
                r2 = self._kernels_call("/kernels/output", body2, timeout=60)
                if r2 is None:
                    break
                r2.raise_for_status()
                d2 = r2.json()
                files.extend(d2.get("files", []) or [])
                token = d2.get("nextPageToken") or d2.get("next_page_token")

            def _fname(f):
                return f.get("fileName") or f.get("file_name") or ""

            import re as _re
            img_files = [f for f in files if _re.match(r"out(_\d+)?\.(jpg|jpeg|png)$", _fname(f))]
            img_files.sort(key=lambda f: _fname(f))
            meta_file = next((f for f in files if _fname(f) == "meta.json"), None)

            if not img_files:
                raise GenerationError("no_output", "No out*.jpg or out*.png in kernel output")

            paths = []
            for idx, f in enumerate(img_files):
                img_resp = requests.get(f["url"], timeout=180)
                img_resp.raise_for_status()
                suffix = "" if len(img_files) == 1 else f"_{idx+1:02d}"
                ext = _fname(f).split(".")[-1].lower() if "." in _fname(f) else "jpg"
                img_path = self.output_dir / f"kaggle_{ts}_{safe_prompt}{suffix}.{ext}"
                img_path.write_bytes(img_resp.content)
                paths.append(img_path)

            meta: dict = {}
            if meta_file:
                meta_resp = requests.get(meta_file["url"], timeout=30)
                meta_resp.raise_for_status()
                raw = meta_resp.content
                (paths[0].with_suffix(".meta.json")).write_bytes(raw)
                try:
                    meta = json.loads(raw.decode("utf-8"))
                except Exception:
                    meta = {}

            return paths, meta

        except requests.exceptions.RequestException as e:
            raise GenerationError("fetch_failed", f"Failed to fetch outputs: {e}")


# ─── Qt Worker Wrapper ──────────────────────────────────────────────────────
class KaggleImageWorker:
    """
    QThread-compatible wrapper for use in the main window.
    Emits signals: progress(stage, detail), generation_done(result), error(message)
    """
    
    def __init__(
        self,
        backend: KaggleImageBackend,
        prompt: str,
        negative_prompt: str = "",
        steps: int = 28,
        width: int = 832,
        height: int = 1216,
        seed: int = -1,
        guidance_scale: float = 6.5,
        batch: int = 1,
    ):
        from PySide6.QtCore import QThread, Signal

        class WorkerThread(QThread):
            progress = Signal(str, str)  # stage, detail
            generation_done = Signal(object)  # GenerationResult
            error = Signal(str)          # error message

            def __init__(self, *args, **kwargs):
                super().__init__()
                self._backend = backend
                self._prompt = prompt
                self._neg = negative_prompt
                self._steps = steps
                self._w = width
                self._h = height
                self._seed = seed
                self._guidance = guidance_scale
                self._batch = batch

            def run(self):
                try:
                    def cb(stage, detail):
                        self.progress.emit(stage, detail)

                    # Temporarily override progress callback
                    old_cb = self._backend.progress_cb
                    self._backend.progress_cb = cb
                    try:
                        result = self._backend.generate(
                            self._prompt, self._neg, self._steps,
                            self._w, self._h, self._seed, self._guidance,
                            batch=self._batch,
                        )
                        self.generation_done.emit(result)
                    finally:
                        self._backend.progress_cb = old_cb
                        
                except GenerationError as e:
                    self.error.emit(f"{e.code}: {e.message}")
                except Exception as e:
                    self.error.emit(f"internal: {e}")
        
        self._worker = WorkerThread()
    
    @property
    def worker(self):
        return self._worker
    
    def start(self):
        self._worker.start()


# ─── Convenience Function ───────────────────────────────────────────────────
def create_backend_from_settings(settings: dict) -> Optional[KaggleImageBackend]:
    """Create backend from app settings dict. Returns None if not configured."""
    username = settings.get("kaggle_username", "").strip()
    api_key = settings.get("kaggle_api_key", "").strip()
    
    if not username or not api_key:
        return None
    
    # PHASE 5: a healthy server-side cache (cellium-cache-<preset>) is the
    # preset's own checkpoint, mounted read-only by Kaggle in ~1s, so the
    # kernel never downloads Civitai at all. Renders are online-only.
    dataset_slug = ""
    try:
        from cellium.services.model_cache import cached_slug_for_preset
        dataset_slug = cached_slug_for_preset(settings) or ""
    except Exception:
        pass

    model_config = ModelConfig(
        mode=settings.get("kaggle_model_mode", "huggingface"),
        hf_model=settings.get("kaggle_hf_model", DEFAULT_HF_MODEL),
        hf_token=settings.get("kaggle_hf_token", ""),
        civitai_url=settings.get("kaggle_civitai_url", ""),
        civitai_token=settings.get("kaggle_civitai_token", ""),
        lora_url=settings.get("kaggle_lora_url", ""),
        lora_token=settings.get("kaggle_civitai_token", ""),
        lora_strength=float(settings.get("kaggle_lora_strength", 0.9)),
        dataset_slug=dataset_slug,
    )

    output_dir = Path(settings.get("kaggle_output_dir", "")) if settings.get("kaggle_output_dir") else None

    backend = KaggleImageBackend(
        username, api_key, model_config, output_dir,
        auto_clean=bool(settings.get("kaggle_auto_clean", True))
    )
    backend.preset_name = (settings.get("kaggle_preset") or "").strip()
    return backend


# ─── Phase 2: LLM prompt enhancer (dedicated model) ─────────────────────────
class EnhanceError(Exception):
    """Typed enhancer failure so the UI can pick the right button state."""
    def __init__(self, kind: str, message: str, status: int = 0):
        super().__init__(message)
        self.kind = kind        # "rate_limit" | "auth" | "network" | "empty"
        self.status = status


def enhance_with_model(prompt: str, model_key: str, settings: dict, models: dict,
                       timeout: float = 60.0) -> str:
    """One-shot chat call to the user-picked enhancer model.

    Returns a Danbooru-style tag list. Raises EnhanceError(kind=...) on failure
    so the caller can fall back / show the right retry state. Never logs the key.
    """
    import urllib.request
    import urllib.error
    route = (models or {}).get(model_key)
    if not isinstance(route, dict):
        raise RuntimeError(f"unknown model: {model_key}")
    prov = route.get("provider", "")
    base = str(route.get("base_url", "")).rstrip("/")
    mid = route.get("model", "")
    key = ((settings.get("user_custom_keys") or {}).get(prov, "")).strip()
    if prov == "GitHub Copilot":
        key = key or os.environ.get("CELSTUDIO_GITHUB_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    if not (base and mid and key):
        raise RuntimeError("enhancer model not configured (need base_url/model/key)")
    sys_prompt = (
        "You are a prompt engineer for SDXL image generation. Convert the user's "
        "idea into ONE comma-separated Danbooru-style tag list: style/quality prefix "
        "(score_9, score_8_up, masterpiece, best quality), subject, hair/eyes/clothes, "
        "pose, background, lighting, camera framing. Keep every content tag the user "
        "gave. Output ONLY the tag list - no sentences, no markdown, no numbering."
    )
    payload = json.dumps({
        "model": mid,
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": prompt}],
        "max_tokens": 700,
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions", data=payload, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "Cellium/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        code = e.code
        if code == 429:
            raise EnhanceError("rate_limit", f"HTTP 429 rate-limited", code)
        if code in (401, 403):
            raise EnhanceError("auth", f"HTTP {code} - check the provider key", code)
        raise EnhanceError("network", f"HTTP {code}", code)
    except Exception as e:
        raise EnhanceError("network", f"{type(e).__name__}: {e}")
    txt = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    txt = (txt or "").strip()
    if not txt:
        raise EnhanceError("empty", "enhancer returned empty text")
    # strip any markdown fences the model added
    if txt.startswith("```"):
        txt = txt.strip("`").split("\n", 1)[-1]
    return txt


# ─── Kaggle cloud datasets (used by the server-side model cache) ────────────
def _dataset_api(backend: "KaggleImageBackend", method: str, path: str, **kw) -> requests.Response:
    url = f"{KAGGLE_API_BASE}{path}"
    return backend._session.request(method, url, timeout=kw.pop("timeout", 60), **kw)


def dataset_exists(backend: "KaggleImageBackend", slug: str) -> bool:
    try:
        r = _dataset_api(backend, "GET", "/datasets/list",
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


def _upload_blob(backend: "KaggleImageBackend", name: str, content,
                 content_type: str, progress_state: dict | None = None) -> str:
    """Kaggle blob-upload flow: POST /blobs/upload -> {token, createUrl}, then
    PUT the bytes to the signed createUrl. Returns the blob token.

    `content` may be bytes or a file-like (streamed, updates progress_state)."""
    if isinstance(content, (bytes, bytearray)):
        data = bytes(content)
        length = len(data)
    else:
        data = content
        try:
            length = len(content)
        except TypeError:
            length = int(getattr(content, "_total", 0) or 0)
    r = backend._session.post(f"{KAGGLE_API_BASE}/blobs/upload", json={
        "type": "DATASET", "name": name, "contentType": content_type,
        "contentLength": length,
    }, timeout=25)
    r.raise_for_status()
    d = r.json()
    token = d["token"]
    create_url = d["createUrl"]
    headers = {"Content-Type": content_type}
    if length:
        headers["Content-Length"] = str(length)
    if progress_state is not None:
        progress_state["total"] = length
        progress_state.setdefault("sent", 0)
    pr = requests.put(create_url, data=data, headers=headers, timeout=3600)
    pr.raise_for_status()
    if progress_state is not None and isinstance(content, (bytes, bytearray)):
        progress_state["sent"] = length
    return token


def _create_version(backend: "KaggleImageBackend", slug: str,
                    file_entries: list, notes: str = "") -> dict:
    """Create a new dataset version. NOTE: the endpoint expects FLAT fields
    (owner/slug live in the path) - nesting them under "body" 500s, multipart
    400s. Verified live."""
    body = {"versionNotes": notes, "deleteOldVersions": True, "files": file_entries,
            "subtitle": "", "description": "", "licenseName": "CC0-1.0",
            "isPrivate": True, "categoryIds": []}
    r = backend._session.post(
        f"{KAGGLE_API_BASE}/datasets/create/version/{backend.username}/{slug}",
        json=body, timeout=180)
    if r.status_code not in (200, 201):
        raise GenerationError("dataset_version_failed",
                              f"{r.status_code} {r.text[:200]}")
    try:
        return r.json()
    except Exception:
        return {}


def upsert_dataset(backend: "KaggleImageBackend", slug: str, title: str,
                   filename: str, content, content_type: str = "application/octet-stream",
                   progress_state: dict | None = None) -> dict:
    """Create the private dataset (with the file inline - create/new requires
    ≥1 file) or push a new version of it (flat body). Blob flow for the bytes."""
    token = _upload_blob(backend, filename, content, content_type, progress_state)
    files = [{"token": token}]
    # Try a new version first (dataset already exists) - flat body, verified live.
    try:
        _create_version(backend, slug, files, "update")
        return {"ok": True}
    except GenerationError:
        pass  # dataset may not exist yet (403) → fall through to create
    # Create the dataset WITH the file inline (create/new requires ≥1 file).
    body = {"ownerSlug": backend.username, "slug": slug, "title": title,
            "licenseName": "CC0-1.0", "isPrivate": True, "files": files,
            "categoryIds": []}
    r = backend._session.post(f"{KAGGLE_API_BASE}/datasets/create/new", json=body, timeout=120)
    try:
        j = r.json()
    except Exception:
        j = {}
    if r.status_code not in (200, 201) or str(j.get("status", "")).lower() == "error":
        raise GenerationError("dataset_create_failed",
                              f"{r.status_code} {j.get('error') or r.text[:200]}")
    return j


def create_dataset(backend: "KaggleImageBackend", slug: str, title: str) -> None:
    """Create an empty dataset is NOT allowed (needs ≥1 file) - kept for compat;
    use upsert_dataset with a real file instead."""
    raise GenerationError("dataset_create_failed",
                          "create/new requires at least one file; use upsert_dataset()")


def delete_dataset(backend: "KaggleImageBackend", slug: str) -> bool:
    try:
        r = _dataset_api(backend, "POST",
                         f"/dataset/{backend.username}/{slug}/delete",
                         json={"ownerSlug": backend.username, "datasetSlug": slug}, timeout=60)
        return r.status_code in (200, 201, 204)
    except Exception:
        return False


# ─── Phase 2: warm-cache notebook (quota-guarded) ───────────────────────────
# NOTE: Kaggle's public API cannot inject prompts into a *running* notebook, so
# a persistent notebook cannot be fed new prompts interactively. We still expose
# /imagine-start-cache & /imagine-stop-cache as a quota-guarded warm notebook
# (hard-capped by sessionTimeoutSeconds) so the user can hold a GPU slot; the app
# warns loudly that batches still run as script jobs.
CACHE_KERNEL_SLUG = "cellium-warm-cache"
CACHE_SESSION_CAP = 3600  # 1h hard cap - can never burn the weekly quota unattended

CACHE_NOTEBOOK_TEMPLATE = '''import time, torch
print("warm cache alive - model will be loaded on demand", flush=True)
# Keep the notebook alive but do NOTHING heavy; sessionTimeoutSeconds caps it.
t0 = time.time()
while time.time() - t0 < 3300:
    time.sleep(30)
    print("warm", int(time.time() - t0), flush=True)
print("warm cache exiting (cap reached)")
'''


def start_warm_cache(backend: "KaggleImageBackend") -> dict:
    """Push a quota-capped warm notebook. Returns push response dict."""
    payload = {
        "slug": f"{backend.username}/{CACHE_KERNEL_SLUG}",
        "newTitle": "Cellium Warm Cache",
        "text": CACHE_NOTEBOOK_TEMPLATE,
        "language": "python",
        "kernelType": "notebook",   # stays alive
        "isPrivate": True,
        "enableGpu": True,
        "enableInternet": True,
        "datasetDataSources": [],
        "competitionDataSources": [],
        "kernelDataSources": [],
        "modelDataSources": [],
        "categoryIds": [],
        "sessionTimeoutSeconds": CACHE_SESSION_CAP,
    }
    r = backend._session.post(f"{KAGGLE_API_BASE}/kernels/push", json=payload, timeout=30)
    r.raise_for_status()
    return r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}


def stop_warm_cache(backend: "KaggleImageBackend") -> None:
    """Best-effort: the notebook self-terminates at its cap; we also mark it
    cancelled by pushing nothing - the hard cap guarantees teardown."""
    dev_log("[KaggleImg] warm cache stop requested - notebook exits at its session cap")