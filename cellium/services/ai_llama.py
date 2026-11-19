#!/usr/bin/env python3
"""
CelStudio Cerebrium - Native PySide6 Desktop Application
Liquid Glass UI, Neon Glow Saturation & Dynamic Color-Shifting Wallpaper Engine
100% LGPL PySide6 Standard | Central Venv | Strict Signals
Telegram-Style Glass Input | Inbuilt Emoji Picker | Multi-Engine STT | 100% Inbuilt Views
Animal Crossing / Scratchin Melodi Musical Cel Voice | Cozy Sound System | Zero Popups
"""

import sys
import os
import io
import json
import time
import tempfile
import uuid
import base64
import hashlib
import threading
import requests
import urllib.request
import urllib.error
import subprocess
import math
import gc
import wave
import struct
import ctypes
import re
import shutil
import html
import queue
from pathlib import Path
from datetime import datetime
import numpy as np

# ============================================================
# GLOBAL REAL-TIME LOGGING SYSTEM - Immediate stdout/stderr flush
# ============================================================
_original_print = print

# --- CROSS IMPORTS ---
from cellium.core.logger import *
from cellium.core.config import *
from cellium.core.utils import *
from cellium.core.tools import *

# Module-level caches (always available for imports) - 2-slot warm LRU:
# _LLAMA_CACHE = active model, _LLAMA_PREV = last-used model (switch-back = zero reload)
_LLAMA_CACHE = {"instance": None, "model_path": None, "n_ctx": None, "n_threads": None, "n_gpu_layers": None, "type_k": None, "type_v": None, "flash_attn": None, "cache_prompt": None}
_LLAMA_PREV = {"instance": None, "model_path": None, "n_ctx": None, "n_threads": None, "n_gpu_layers": None, "type_k": None, "type_v": None, "flash_attn": None, "cache_prompt": None}
_LLAMA_CACHE_MAX = 2  # Keep up to 2 models warm so A→B→A never reloads

# ── KV cache guard ──────────────────────────────────────────────────────
# llama.cpp refuses to build a context from a quantized K/V cache unless
# Flash Attention is on, and it says so *after* the weights are mmap'd:
#
#   llama_init_from_model: quantized V cache requires flash_attn to be enabled
#   [DEV] Generation Error: Failed to create llama_context
#
# The exception surfaced as a ValueError from inside the C++ constructor,
# and taking that half-built context down took the app with it. Worse, the old
# loader had already evicted the warm model *before* attempting the load, so a
# single illegal setting cost you the model that was working. The illegal
# combination is now resolved here - before a single byte is read - and the
# outgoing model is only demoted once the new one exists.
_UNQUANTIZED_KV = ("f32", "f16")


def _is_quantized_kv(kind) -> bool:
    """True when a KV cache type is quantized (llama.cpp needs flash_attn)."""
    if kind is None:
        return False
    if isinstance(kind, str):
        return kind.strip().lower() not in _UNQUANTIZED_KV
    try:
        # GGML_TYPE_F32 == 0, GGML_TYPE_F16 == 1 - the only unquantized ones.
        return int(kind) > 1
    except (TypeError, ValueError):
        return False


def sanitize_kv_cache(type_k=None, type_v=None, flash_attn=None):
    """Return ``(type_k, type_v, flash_attn, note)`` that llama.cpp accepts.

    The only automatic change is the one llama.cpp itself demands: a quantized
    K or V cache forces Flash Attention on. Nothing the user picked is silently
    downgraded, and the swap is written to the log so it stays visible.
    """
    fa = bool(flash_attn) if flash_attn is not None else False
    note = ""
    if not fa and (_is_quantized_kv(type_k) or _is_quantized_kv(type_v)):
        fa = True
        note = "flash_attn forced on (quantized KV cache requires it)"
    return type_k, type_v, fa, note


def _empty_entry():
    return {"instance": None, "model_path": None, "n_ctx": None,
            "n_threads": None, "n_gpu_layers": None, "type_k": None,
            "type_v": None, "flash_attn": None, "cache_prompt": None}


def _entry_matches(entry, model_path, n_ctx, n_threads, n_gpu_layers, type_k=None, type_v=None, flash_attn=None, cache_prompt=None):
    return (
        entry is not None
        and entry.get("instance") is not None
        and entry.get("model_path") == model_path
        and entry.get("n_ctx") == n_ctx
        and entry.get("n_threads") == n_threads
        and entry.get("n_gpu_layers") == n_gpu_layers
        and entry.get("type_k") == type_k
        and entry.get("type_v") == type_v
        and entry.get("flash_attn") == flash_attn
        and entry.get("cache_prompt") == cache_prompt
    )


_LLAMA_INFER_LOCK = threading.Lock()
_LLAMA_ABORT_EVENT = threading.Event()
_LLAMA_LAST_SID = None


def request_llama_abort() -> None:
    """Signal the active C++ llama_decode loop to abort immediately."""
    _LLAMA_ABORT_EVENT.set()


def clear_llama_abort() -> None:
    _LLAMA_ABORT_EVENT.clear()


#: Number of live worker runs that may call into the native llama.cpp context.
#: ``unload_llama`` refuses to close the model while any of them is alive  - 
#: closing a context mid-decode is a use-after-free that segfaults the app.
_LLAMA_USE_DEPTH = 0
_LLAMA_USE_LOCK = threading.Lock()


def begin_llama_use() -> None:
    """Mark the start of a worker run that may touch llama.cpp."""
    global _LLAMA_USE_DEPTH
    with _LLAMA_USE_LOCK:
        _LLAMA_USE_DEPTH += 1


def end_llama_use() -> None:
    """Mark the end of a worker run (safe even if called twice)."""
    global _LLAMA_USE_DEPTH
    with _LLAMA_USE_LOCK:
        _LLAMA_USE_DEPTH = max(0, _LLAMA_USE_DEPTH - 1)


def is_llama_in_use() -> bool:
    """True while any worker owns the model - unload must never race it."""
    with _LLAMA_USE_LOCK:
        return _LLAMA_USE_DEPTH > 0


def prepare_llama_session(llm, session_id: str | None) -> None:
    """Bug #23: Reset KV cache tokens when switching to a different chat session."""
    global _LLAMA_LAST_SID
    if llm is None:
        return
    if session_id != _LLAMA_LAST_SID:
        try:
            if hasattr(llm, "reset"):
                llm.reset()
            if hasattr(llm, "_input_ids"):
                llm._input_ids = np.ndarray((0,), dtype=np.intc)
            if hasattr(llm, "_scores"):
                llm._scores = np.ndarray((0, 0), dtype=np.single)
            if _LLAMA_LAST_SID is not None:
                dev_log(f"🧹 Reset GGUF KV cache state for chat switch ({_LLAMA_LAST_SID} -> {session_id})")
        except Exception as e:
            dev_log(f"[GGUF] KV reset note: {e}")
        _LLAMA_LAST_SID = session_id


def _free_entry(entry, label):
    global _LLAMA_LAST_SID
    inst = entry.get("instance")
    if inst is None:
        return False
    for k in list(entry.keys()):
        entry[k] = None
    _LLAMA_LAST_SID = None
    # Explicitly close C++ llama_context / llama_model mmap buffers!
    try:
        if hasattr(inst, "reset"):
            inst.reset()
    except Exception:
        pass
    try:
        if hasattr(inst, "close"):
            inst.close()
    except Exception:
        pass
    # Break internal llama-cpp-python cyclic references so refcount hits 0 immediately
    for attr in ("_ctx", "_model", "_batch", "_sampler", "chat_handler", "_input_ids", "_scores"):
        try:
            if hasattr(inst, attr):
                setattr(inst, attr, None)
        except Exception:
            pass
    del inst
    gc.collect()
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass
    dev_log(f"GGUF {label} freed from RAM")
    return True


#: Serializes model load vs unload across threads. Two QThreads must never
#: mmap two 4 GB models at once, and an unload must never interleave a load's
#: fallback ladder - both end in native heap corruption / OOM kills.
_LLAMA_LOCK = threading.Lock()


def _synchronized(fn):
    def _wrap(*a, **k):
        with _LLAMA_LOCK:
            return fn(*a, **k)
    _wrap.__name__ = getattr(fn, "__name__", "_wrap")
    return _wrap


@_synchronized
def get_or_load_llama(model_path, n_ctx=4096, n_threads=4, n_gpu_layers=0, type_k=None, type_v=None, flash_attn=None, cache_prompt=None, status_cb=None, verbose=False):
    global _LLAMA_CACHE, _LLAMA_PREV
    if not model_path or not os.path.exists(model_path):
        raise FileNotFoundError(f"GGUF model file not found at: {model_path}")

    # Resolve the illegal Flash-Attention/KV combination *first*, so the cache
    # key and the constructor always agree on what was actually used.
    type_k, type_v, flash_attn, kv_note = sanitize_kv_cache(
        type_k, type_v, flash_attn)
    if kv_note:
        dev_log(f"[DEV] GGUF KV guard: {kv_note}")

    # 1) Active slot exact hit (instant)
    if _entry_matches(_LLAMA_CACHE, model_path, n_ctx, n_threads, n_gpu_layers, type_k, type_v, flash_attn, cache_prompt):
        if status_cb: status_cb("⚡ GGUF model warm in RAM (instant hit)")
        dev_log(f"GGUF cache hit: {os.path.basename(model_path)}")
        return _LLAMA_CACHE["instance"]

    # 2) Warm swap - previous slot matches: promote without reloading (model never left RAM)
    if _entry_matches(_LLAMA_PREV, model_path, n_ctx, n_threads, n_gpu_layers, type_k, type_v, flash_attn, cache_prompt):
        _LLAMA_CACHE, _LLAMA_PREV = _LLAMA_PREV, _LLAMA_CACHE
        if status_cb: status_cb("⚡ GGUF warm swap - model never left RAM")
        dev_log(f"GGUF warm swap from prev slot: {os.path.basename(model_path)}")
        return _LLAMA_CACHE["instance"]

    if status_cb: status_cb("⏳ Loading GGUF weights into system RAM...")
    dev_log(f"Loading GGUF model: {os.path.basename(model_path)} (ctx={n_ctx}, threads={n_threads}, gpu_layers={n_gpu_layers}, type_k={type_k}, type_v={type_v}, flash_attn={flash_attn}, cache_prompt={cache_prompt})")

    try:
        from llama_cpp import Llama, GGML_TYPE_F16, GGML_TYPE_Q8_0, GGML_TYPE_Q4_0, GGML_TYPE_Q4_K
    except ImportError:
        raise ImportError("llama-cpp-python is not installed in the central environment.")

    # Resolve cache types from settings
    type_map = {"f16": GGML_TYPE_F16, "q8_0": GGML_TYPE_Q8_0,
                "q4_0": GGML_TYPE_Q4_0, "q4_k": GGML_TYPE_Q4_K}
    resolved_type_k = type_map.get(type_k.lower(), GGML_TYPE_F16) if isinstance(type_k, str) else type_k
    resolved_type_v = type_map.get(type_v.lower(), GGML_TYPE_F16) if isinstance(type_v, str) else type_v

    def _build(tk, tv, fa):
        # Use all logical CPU threads for prompt batch evaluation so resuming
        # chats evaluates 2x faster on dual-core / 4-thread CPUs!
        batch_threads = max(int(n_threads), os.cpu_count() or 4)
        extra_kw = {}
        try:
            import inspect
            sig_params = inspect.signature(Llama.__init__).parameters
            if "n_threads_batch" in sig_params:
                extra_kw["n_threads_batch"] = batch_threads
            if "n_batch" in sig_params:
                extra_kw["n_batch"] = 256
        except Exception:
            pass
        return Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_gpu_layers=n_gpu_layers,
            type_k=tk,
            type_v=tv,
            flash_attn=fa,
            verbose=bool(verbose),
            **extra_kw,
        )

    # Fallback ladder. Context creation can still fail for reasons the settings
    # cannot predict (a context larger than the KV budget, a quantized cache on
    # a build without flash-attn kernels). Retry with the least-lossy thing
    # that is still legal instead of dying on the first exception.
    attempts = [(resolved_type_k, resolved_type_v, bool(flash_attn), "as configured")]
    if not flash_attn:
        attempts.append((resolved_type_k, resolved_type_v, True, "flash_attn on"))
    if _is_quantized_kv(type_k) or _is_quantized_kv(type_v):
        attempts.append((GGML_TYPE_F16, GGML_TYPE_F16, bool(flash_attn), "f16 KV cache"))
    attempts.append((GGML_TYPE_F16, GGML_TYPE_F16, True, "f16 KV cache + flash_attn"))

    llm = None
    last_exc = None
    for tk, tv, fa, label in attempts:
        try:
            llm = _build(tk, tv, fa)
            if label != "as configured":
                dev_log(f"[DEV] GGUF load fallback: {label}")
                if status_cb:
                    status_cb(f"⚠️ GGUF loaded with a safer KV setting ({label})")
            break
        except Exception as exc:
            last_exc = exc
            dev_log(f"[DEV] GGUF load attempt failed ({label}): {exc}")

    if llm is None:
        # Nothing has been evicted or cached yet - the model that was already
        # warm is untouched, so this stays a message instead of a dead app.
        raise ValueError(
            f"Failed to create llama_context for {os.path.basename(model_path)} "
            f"after {len(attempts)} attempts: {last_exc}") from last_exc

    # Only now is the outgoing model demoted: a *failed* load must not also
    # cost you the model that was already loaded and working.
    if _LLAMA_CACHE.get("instance") is not None:
        if _LLAMA_PREV.get("instance") is not None:
            _free_entry(_LLAMA_PREV, "prev slot (evicted oldest)")
        _LLAMA_PREV, _LLAMA_CACHE = _LLAMA_CACHE, _empty_entry()

    _LLAMA_CACHE = {
        "model_path": model_path,
        "instance": llm,
        "n_ctx": n_ctx,
        "n_threads": n_threads,
        "n_gpu_layers": n_gpu_layers,
        "type_k": type_k,
        "type_v": type_v,
        "flash_attn": flash_attn,
        "cache_prompt": cache_prompt
    }

    if status_cb: status_cb("🟢 GGUF ready in RAM")
    dev_log(f"GGUF loaded successfully: {os.path.basename(model_path)}")
    return llm


@_synchronized
def unload_llama():
    global _LLAMA_CACHE, _LLAMA_PREV
    # A worker that called stop_generation() is retired *before* its thread
    # exits. Closing the context under it is a native use-after-free, so
    # refuse until the last owner has left llama.cpp. The UI queues Free RAM
    # and calls us again once every worker is gone.
    if is_llama_in_use():
        dev_log("GGUF unload deferred - a worker still owns the model")
        return False
    freed = False
    if _LLAMA_CACHE.get("instance") is not None:
        freed = _free_entry(_LLAMA_CACHE, "current slot") or freed
    if _LLAMA_PREV.get("instance") is not None:
        freed = _free_entry(_LLAMA_PREV, "prev slot") or freed
    if freed:
        dev_log("GGUF model(s) unloaded from RAM")
    return freed
