#!/usr/bin/env python3
"""PHASE 5 - ☁️ server-side model cache (zero local model traffic).

Why this exists
---------------
The Phase-2 "cloud storage" toggle uploads a *.safetensors that already sits on
the PC - useless on a metered connection. Here the **Kaggle builder kernel**
downloads the Civitai checkpoint (+ optional LoRA) straight into Kaggle and
writes it into a private dataset. The PC only exchanges JSON (~KB).

Live probe on the user's key (2026-11-03, recorded in KAGGLE_IMAGE_GEN.md):
    GET  /datasets/list             200  → unreliable, returns 0 rows
    POST /blobs/upload + PUT        200  → works
    POST /datasets/create/new       200  → works, file really stored
    POST /datasets/create/version   403  "Permission 'datasets.update' denied"
    GET  /datasets/view/{u}/{s}     200  → totalBytes reflects real storage

Consequences baked into this module
-----------------------------------
* One dataset **per preset** (`cellium-cache-<preset>`), created once - never
  updated, because `create/version` is forbidden on this key.
* Re-caching means DELETE first, then create again.
* Discovery uses `view` (deterministic slugs), not `list`.
* Builder kernel is CPU-only (`enableGpu=False`) → burns ZERO GPU quota.
"""

from __future__ import annotations

import json
import re
from typing import Dict, Optional

import requests

from cellium.core.logger import dev_log
from cellium.services.kaggle_image import (
    KAGGLE_API_BASE, GenerationError, KaggleImageBackend, delete_dataset,
)

#: Prefix shared by every cache dataset slug.
CACHE_PREFIX = "cellium-cache-"
#: Anything smaller than this is a failed/empty shell, not a model.
MIN_HEALTHY_BYTES = 1_000_000          # 1 MB
#: Kernel slug prefix for the builder job.
BUILDER_SLUG = "cellium-cache-builder"


# ─── naming / discovery ─────────────────────────────────────────────────────


def preset_slug(preset_name: str) -> str:
    """Deterministic dataset slug for a preset name.

    ``"🎨 Nova Cartoon XL (Civitai)"`` → ``"cellium-cache-nova-cartoon-xl"``
    """
    cleaned = re.sub(r"\([^)]*\)", " ", (preset_name or "").lower())
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    # drop the leading emoji remnants & duplicate separators
    parts = [p for p in cleaned.split("-") if p and len(p) > 1]
    cleaned = "-".join(parts)[:40].strip("-")
    return CACHE_PREFIX + (cleaned or "preset")


def cache_status(backend: KaggleImageBackend, slug: str) -> Dict:
    """Probe one cache dataset via ``/datasets/view`` (list is broken).

    Returns ``{exists, healthy, bytes, updated, ref, slug}``.
    """
    out = {"slug": slug, "exists": False, "healthy": False,
           "bytes": 0, "updated": "", "ref": ""}
    try:
        r = backend._session.get(
            f"{KAGGLE_API_BASE}/datasets/view/{backend.username}/{slug}",
            timeout=(5.0, 10.0))
        if r.status_code != 200:
            return out
        j = r.json() or {}
        total = int(j.get("totalBytes") or j.get("total_bytes") or 0)
        out.update(exists=True, bytes=total, healthy=total >= MIN_HEALTHY_BYTES,
                   updated=str(j.get("lastUpdated") or ""), ref=str(j.get("ref") or ""))
    except Exception as e:
        dev_log(f"[model-cache] status probe failed for {slug}: {e}")
    return out


def refresh_cache_map(backend: KaggleImageBackend,
                      presets: Optional[list] = None) -> Dict[str, Dict]:
    """Check every preset's cache dataset concurrently and return ``{preset_name: status}``.

    Fast and light: concurrent HTTPS GETs (~KB), safe on a metered connection.
    """
    import concurrent.futures
    from cellium.services.kaggle_image import MODEL_PRESETS

    presets = presets if presets is not None else MODEL_PRESETS
    out: Dict[str, Dict] = {}
    tasks = []
    for p in presets:
        name = p.get("name") or ""
        if not name or p.get("mode") == "huggingface":
            # public HF repos are already fast + free; nothing to cache
            continue
        tasks.append((name, preset_slug(name)))

    if not tasks:
        return out

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(tasks))) as ex:
            futures = {ex.submit(cache_status, backend, slug): name for name, slug in tasks}
            for fut in concurrent.futures.as_completed(futures, timeout=12):
                name = futures[fut]
                try:
                    out[name] = fut.result()
                except Exception as e:
                    dev_log(f"[model-cache] probe error for {name}: {e}")
                    out[name] = {"slug": preset_slug(name), "exists": False, "healthy": False, "bytes": 0}
    except Exception as e:
        dev_log(f"[model-cache] parallel refresh timed out or failed: {e}")
    return out


def cached_slug_for_preset(settings: dict) -> str:
    """Healthy cache slug for the currently selected preset (or "")."""
    preset = (settings.get("kaggle_preset") or "").strip()
    entry = (settings.get("kaggle_cache_map") or {}).get(preset) or {}
    if entry.get("healthy") and entry.get("slug"):
        return str(entry["slug"])
    return ""


def delete_cache(backend: KaggleImageBackend, slug: str) -> bool:
    """Delete a cache dataset (needed before re-caching - create/version is 403)."""
    try:
        ok = delete_dataset(backend, slug)
        dev_log(f"[model-cache] delete {slug} -> {ok}")
        return bool(ok)
    except Exception as e:
        dev_log(f"[model-cache] delete failed for {slug}: {e}")
        return False


# ─── builder kernel ─────────────────────────────────────────────────────────

BUILDER_TEMPLATE = '''import json, os, re, sys, time
import requests

CFG = json.loads(__CFG__)
API = "https://www.kaggle.com/api/v1"
AUTH = (CFG["owner"], CFG["api_key"])
t0 = time.time()


def log(*a):
    print("[cache-build]", *a, flush=True)


def _civitai_url(url: str) -> str:
    """Resolve a Civitai url to a direct .safetensors download.

    A VERSION id ("/api/download/models/<id>") is served as-is - that is the
    safe form. A MODEL id ("/models/<id>") serves the page's LATEST file (a
    model id is a trap: 133005 once served a 151 MB different checkpoint), so
    it is resolved through the Civitai API first.
    """
    if re.search(r"civitai\\.com/api/download/models/[0-9]+", url or ""):
        return url
    m = re.search(r"civitai\\.com/models/([0-9]+)", url or "")
    if not m:
        return url
    mid = m.group(1)
    direct = "https://civitai.com/api/download/models/" + mid
    try:
        r = requests.get("https://civitai.com/api/v1/models/" + mid, timeout=30,
                         headers={"User-Agent": "Cellium/1.0"})
        r.raise_for_status()
        vers = (r.json() or {}).get("modelVersions", []) or []
        for v in vers:
            b = (v.get("baseModel") or "").upper()
            if "SDXL" not in b and "ILLUSTRIOUS" not in b:
                continue
            for f in (v.get("files") or []):
                if (f.get("name") or "").lower().endswith(".safetensors"):
                    return f.get("downloadUrl") or f.get("url") or direct
    except Exception as e:
        log("civitai resolve fallback:", e)
    return direct


def download(url: str, dest: str) -> int:
    url = _civitai_url(url)
    hdrs = {"User-Agent": "Cellium/1.0"}
    _tok = CFG.get("civitai_token") or ""
    if _tok:
        hdrs["Authorization"] = "Bearer " + _tok
    log("downloading", url[:110])
    r = requests.get(url, stream=True, timeout=900, headers=hdrs)
    r.raise_for_status()
    n = 0
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1 << 22):
            f.write(chunk)
            n += len(chunk)
            if n % (200 << 20) < (1 << 22):
                log("  ...", round(n / (1024 ** 2)), "MB")
    log("saved", dest, round(n / (1024 ** 2), 1), "MB")
    return n


def blob(name: str, path: str) -> str:
    """Kaggle blob flow, streamed (never loads a 7 GB model into RAM)."""
    length = os.path.getsize(path)
    r = requests.post(f"{API}/blobs/upload", auth=AUTH, timeout=60, json={
        "type": "DATASET", "name": name,
        "contentType": "application/octet-stream", "contentLength": length})
    r.raise_for_status()
    d = r.json()
    with open(path, "rb") as fh:
        pr = requests.put(d["createUrl"], data=fh, timeout=7200,
                          headers={"Content-Type": "application/octet-stream",
                                   "Content-Length": str(length)})
    pr.raise_for_status()
    log("blob uploaded", name, round(length / (1024 ** 2), 1), "MB")
    return d["token"]


try:
    files = []
    if CFG.get("civitai_url"):
        model_path = "/kaggle/working/model.safetensors"
        download(CFG["civitai_url"], model_path)
        files.append({"token": blob("model.safetensors", model_path)})
    if CFG.get("lora_url"):
        # A dead LoRA must never kill the whole cache - the checkpoint is the
        # expensive part, the style LoRA is optional garnish.
        try:
            lora_path = "/kaggle/working/lora.safetensors"
            download(CFG["lora_url"], lora_path)
            files.append({"token": blob("lora.safetensors", lora_path)})
        except Exception as e:
            log("lora skipped (download failed):", e)
    if not files:
        raise RuntimeError("nothing to cache: no civitai_url and no lora_url")

    body = {"ownerSlug": CFG["owner"], "slug": CFG["slug"],
            "title": CFG["title"], "licenseName": "CC0-1.0",
            "isPrivate": True, "files": files, "categoryIds": []}
    r = requests.post(f"{API}/datasets/create/new", auth=AUTH, json=body, timeout=900)
    log("create/new ->", r.status_code, r.text[:200])
    if r.status_code in (200, 201):
        log("CACHE_DONE", CFG["slug"], "files:", len(files),
            "seconds:", round(time.time() - t0))
    else:
        log("CACHE_FAILED", r.status_code, r.text[:300])
except Exception as e:
    log("CACHE_FAILED exception:", e)
'''


def build_builder_script(backend: KaggleImageBackend, preset: dict,
                         slug: str) -> str:
    """Render the CPU-only builder kernel for one preset."""
    cfg = {
        "owner": backend.username,
        "api_key": backend.api_key,
        "slug": slug,
        "title": f"Cellium cache {slug.replace(CACHE_PREFIX, '')}"[:50],
        "civitai_url": preset.get("civitai_url") or "",
        "lora_url": preset.get("lora_url") or "",
        "civitai_token": getattr(backend.model_config, "civitai_token", "") or "",
    }
    return BUILDER_TEMPLATE.replace("__CFG__", repr(json.dumps(cfg, ensure_ascii=False)))


def push_cache_builder(backend: KaggleImageBackend, preset: dict) -> str:
    """Push the builder kernel (CPU-only, no GPU quota) and return its slug.

    Raises :class:`GenerationError` when Kaggle refuses the push.
    """
    slug = preset_slug(preset.get("name") or "")
    # a stale shell would make create/new fail → delete it first
    if cache_status(backend, slug).get("exists"):
        delete_cache(backend, slug)

    import uuid
    kernel_slug = f"{BUILDER_SLUG}-{uuid.uuid4().hex[:6]}"
    payload = {
        "slug": f"{backend.username}/{kernel_slug}",
        "newTitle": f"Cellium cache builder {uuid.uuid4().hex[:6]}",
        "text": build_builder_script(backend, preset, slug),
        "language": "python",
        "kernelType": "script",
        "isPrivate": True,
        "enableGpu": False,          # ← CPU only: zero GPU quota
        "enableInternet": True,
        "datasetDataSources": [],
        "competitionDataSources": [],
        "kernelDataSources": [],
        "modelDataSources": [],
        "categoryIds": [],
        "sessionTimeoutSeconds": 3600,
    }
    r = backend._session.post(f"{KAGGLE_API_BASE}/kernels/push", json=payload, timeout=60)
    if r.status_code not in (200, 201):
        raise GenerationError("cache_push_failed",
                              f"{r.status_code} {r.text[:180]}")
    # Kaggle may NOT honour the requested slug (it mints its own when the
    # title/slug clashes) - always trust the ref the API hands back, or every
    # later status/log poll looks at a kernel that never existed.
    real_slug = kernel_slug
    try:
        body = r.json() or {}
        ref = body.get("ref") or body.get("refNullable") or ""
        if ref:
            real_slug = str(ref).rstrip("/").split("/")[-1]
    except Exception:
        pass
    dev_log(f"[model-cache] builder pushed: {real_slug}")
    return real_slug
