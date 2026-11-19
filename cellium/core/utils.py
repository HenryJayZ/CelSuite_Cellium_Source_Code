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
from cellium.core.logger import dev_log
from cellium.core.config import *

def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    return _original_print(*args, **kwargs)

_LOG_LISTENERS = []

_SOUND_ENGINE_VERSION = "v7_melodi_oct12_exact_calm_gui"


def generate_sound_library(force: bool = False):
    """Synthesize Apple iOS / visionOS & ChatGPT style acoustic UI sounds (vectorized NumPy DSP)."""
    try:
        marker = SOUNDS_DIR / f".{_SOUND_ENGINE_VERSION}"
        need_regen = bool(force or not marker.exists())
        sr = 44100

        def _lp_smooth(sig: np.ndarray, alpha: float = 0.28) -> np.ndarray:
            """One-pole warm low-pass filter to remove harsh digitalfizz."""
            out = np.empty_like(sig)
            acc = 0.0
            b = 1.0 - alpha
            for k in range(sig.size):
                acc = alpha * float(sig[k]) + b * acc
                out[k] = acc
            return out

        def _write_wav(path: Path, samples: np.ndarray, overwrite: bool = True,
                       fade: bool = True):
            if path.exists() and not overwrite:
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            s = np.asarray(samples, dtype=np.float32)
            # 1.5ms cosine fade-in & 3ms fade-out so zero DC click ever occurs.
            # Legacy sounds opt out: the archived synth already starts at 0
            # (sine envelope) and its square bloop's tiny onset click is part
            # of the original character.
            fi = min(int(sr * 0.0015), s.size // 4)
            fo = min(int(sr * 0.003), s.size // 3)
            if fade and fi > 1:
                s[:fi] *= np.linspace(0.0, 1.0, fi, dtype=np.float32)
            if fade and fo > 1:
                s[-fo:] *= np.linspace(1.0, 0.0, fo, dtype=np.float32)
            pcm = (np.clip(s, -1.0, 1.0) * 32767.0).astype("<i2")
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(pcm.tobytes())

        def _pluck_note(freq: float, dur_s: float, tau: float, amp: float = 0.55) -> np.ndarray:
            """Warm damped Rhodes / visionOS glass-mallet note."""
            t = np.linspace(0.0, dur_s, int(sr * dur_s), endpoint=False, dtype=np.float32)
            # Subtle pitch transient on attack (mallet strike)
            f_env = freq * (1.0 + 0.018 * np.exp(-t / 0.004))
            phase = 2.0 * np.pi * np.cumsum(f_env) / sr
            attack = 1.0 - np.exp(-t / 0.0022)
            body = (
                1.00 * np.sin(phase) * np.exp(-t / tau)
                + 0.28 * np.sin(2.0 * phase) * np.exp(-t / (tau * 0.45))
                + 0.09 * np.sin(3.0 * phase) * np.exp(-t / (tau * 0.22))
                + 0.32 * np.sin(0.5 * phase) * np.exp(-t / (tau * 1.15))
            )
            return np.tanh(body * attack * amp)

        # ── Animalese 2.0: formant-shaped vowel chirps ──────────────────────
        # Animal Crossing's villager voice is not a random pitched beep; each
        # letter is a little vowel syllable ("ba/be/bi/bo/bu") whose timbre is
        # shaped by the first three formants. These notes keep the pack's
        # pentatonic melody but give every note a living, mouth-like colour.
        _AC_FORMANTS = {
            "a": ((800.0, 130.0, 1.00), (1150.0, 160.0, 0.55), (2500.0, 260.0, 0.18)),
            "e": ((500.0, 100.0, 0.95), (1800.0, 170.0, 0.55), (2500.0, 260.0, 0.20)),
            "i": ((300.0, 80.0, 0.90), (2300.0, 180.0, 0.60), (3000.0, 260.0, 0.22)),
            "o": ((500.0, 100.0, 1.00), (900.0, 130.0, 0.55), (2400.0, 260.0, 0.18)),
            "u": ((350.0, 90.0, 0.95), (700.0, 120.0, 0.50), (2400.0, 260.0, 0.15)),
        }

        def _ac_chirp_note(freq, dur_s, decay, amp=0.58, vowel="a",
                           h2=0.0, h3=0.0, sub=0.0, vib=0.0, vib_hz=0.0):
            """One Animalese vowel chirp with a soft scoop and formant colour."""
            t = np.linspace(0.0, dur_s, int(sr * dur_s), endpoint=False,
                            dtype=np.float32)
            # A tiny upward scoop on the attack is the "bounce" that makes
            # Animalese feel alive rather than a flat MIDI note.
            f_env = freq * (1.0 + 0.02 * np.exp(-t / 0.006)
                            - 0.008 * (t / max(dur_s, 1e-6)))
            if vib > 0.0 and vib_hz > 0.0:
                f_env = f_env * (1.0 + vib * 0.012
                                 * np.sin(2.0 * np.pi * vib_hz * t))
            phase = 2.0 * np.pi * np.cumsum(f_env) / sr
            formants = _AC_FORMANTS.get(vowel, _AC_FORMANTS["a"])
            y = np.zeros_like(t)
            max_h = min(28, max(1, int(9000.0 / max(freq, 1.0))))
            for h in range(1, max_h + 1):
                fh = freq * h
                weight = 0.16
                for f_center, bandwidth, f_amp in formants:
                    weight += f_amp * math.exp(
                        -0.5 * ((fh - f_center) / bandwidth) ** 2)
                if weight < 0.02:
                    continue
                y += (weight / (h ** 0.62)) * np.sin(h * phase)
            if sub:
                y += sub * np.sin(0.5 * phase)
            if h2:
                y += h2 * np.sin(2.0 * phase)
            if h3:
                y += h3 * np.sin(3.0 * phase)
            env = ((1.0 - np.exp(-t / 0.004))
                   * np.exp(-t / max(decay, 1e-6)))
            release = min(int(sr * 0.004), t.size // 4)
            if release > 1:
                env[-release:] *= np.linspace(1.0, 0.0, release,
                                              dtype=np.float32)
            y = np.tanh(y * env * 0.9)
            peak = float(np.max(np.abs(y))) if y.size else 0.0
            if peak > 0.001:
                y = y / peak * amp
            return y

        rng = np.random.default_rng(20261015)

        # ── Calm GUI pack: warm nylon-string plucks & soft chords ─────────
        # The previous pack was 580-1400 Hz sine sweeps with white-noise
        # bursts on top - piercing, 1990-era beeps that hurt to listen to.
        # These are low, round and warm: a muted guitar "thup" for keys, soft
        # triads for events. Nothing above ~440 Hz, no noise transients, and
        # every note has a soft attack so nothing clicks.
        def _pluck(freq, dur_s, amp=0.5, decay=3.4, body=0.30):
            n = max(8, int(sr * dur_s))
            t = np.arange(n, dtype=np.float32) / float(sr)
            env = (1.0 - np.exp(-t / 0.010)) * np.exp(-t * decay)
            y = (np.sin(2 * np.pi * freq * t)
                 + body * np.sin(2 * np.pi * freq * 2 * t)
                 * np.exp(-t * decay * 1.9)
                 + 0.10 * np.sin(2 * np.pi * freq * 3 * t)
                 * np.exp(-t * decay * 3.2))
            y = np.tanh(y * 0.85) * env
            peak = float(np.max(np.abs(y))) if y.size else 0.0
            return ((y / peak * amp) if peak > 1e-6 else y).astype(np.float32)

        def _chord(freqs, dur_s, amp=0.42, decay=3.0, stagger=0.022):
            """Soft arpeggio - each note nudged later, like a finger roll."""
            total = int(sr * (dur_s + stagger * len(freqs)))
            out = np.zeros(total, dtype=np.float32)
            for i, f in enumerate(freqs):
                note = _pluck(f, dur_s, amp=amp, decay=decay)
                off = int(sr * stagger * i)
                end = min(total, off + note.size)
                if end > off:
                    out[off:end] += note[:end - off]
            peak = float(np.max(np.abs(out))) if out.size else 0.0
            if peak > 1e-6:
                # Normalise to a calm, consistent event level - the old
                # `min(1.0, 0.82/peak)` left stacked triads at 0.76 peak,
                # which is nearly twice as loud as the click it follows.
                out *= 0.46 / peak
            return out

        # 1. CLICK: muted nylon-string "thup" - G3, soft and round (100ms)
        sig_click = _pluck(196.00, 0.100, amp=0.30, decay=9.0)

        # 2. TYPE / KEYPRESS: quiet low key pluck - A3 (55ms)
        sig_type = _pluck(220.00, 0.055, amp=0.22, decay=16.0)

        # 3. SCROLL: tiny soft tick - D4 (45ms)
        sig_scroll = _pluck(293.66, 0.045, amp=0.16, decay=22.0)

        # 4. POP: warm low wooden pop - C4 (140ms)
        sig_pop = _pluck(261.63, 0.140, amp=0.34, decay=7.0)

        # 5. SEND: gentle two-note rise - G3 → D4 (340ms)
        sig_send = _chord([196.00, 293.66], 0.34, amp=0.30, decay=4.6)

        # 6. RECV: soft F-major triad - F3 → A3 → C4 (460ms)
        sig_recv = _chord([174.61, 261.63, 349.23], 0.46, amp=0.28, decay=3.8)

        # 7. OPEN: gentle rising fifth - F3 → C4 (300ms)
        sig_open = _chord([174.61, 261.63], 0.30, amp=0.28, decay=4.4)

        # 8. CLOSE: gentle falling fifth - C4 → F3 (280ms)
        sig_close = _chord([261.63, 174.61], 0.28, amp=0.26, decay=4.6)

        # 9. RIGHT / MIDDLE CLICK: the same warm thup as the primary click
        n_rc = int(sr * 0.100)
        sig_rclick = np.zeros(n_rc, dtype=np.float32)
        sig_rclick[:sig_click.size] += sig_click
        off_rc = int(sr * 0.030)
        end_rc = min(n_rc, off_rc + sig_click.size)
        sig_rclick[off_rc:end_rc] += sig_click[:end_rc - off_rc] * 0.55

        # 10. APPEAR: slow, calm F-major arpeggio (1.35s)
        sig_appear = _chord([174.61, 261.63, 349.23, 440.00], 0.85,
                            amp=0.24, decay=2.4, stagger=0.090)

        sound_targets = [
            (SOUNDS_DIR / "cozy_click.wav", sig_click),
            (SOUNDS_DIR / "cozy_pop.wav", sig_pop),
            (SOUNDS_DIR / "cozy_send.wav", sig_send),
            (SOUNDS_DIR / "cozy_recv.wav", sig_recv),
            (SOUNDS_DIR / "cozy_open.wav", sig_open),
            (SOUNDS_DIR / "cozy_close.wav", sig_close),
            (SOUNDS_DIR / "cozy_type.wav", sig_type),
            (SOUNDS_DIR / "cozy_scroll.wav", sig_scroll),
            (SOUNDS_DIR / "cel_appear.wav", sig_appear),
        ]
        # Cel's Original Sound - the *actual* archived Cerebellium.py synth,
        # not an approximation. create_smooth_bloop() is a sine with a
        # sin(pi*t/duration) envelope; create_cellium_bloop() is a square with
        # exp(-i/500) decay. No tanh, no extra harmonics, no modern polish:
        # this is the sound the old app really made.
        PITCH_F = 500.0
        PITCH_M = 400.0

        def _legacy_smooth(freq, duration=0.05, vol=0.15):
            n = int(sr * duration)
            t = np.arange(n, dtype=np.float64) / float(sr)
            env = np.sin(np.pi * (t / duration))
            return (env * vol * np.sin(2.0 * np.pi * freq * t)).astype(np.float64)

        def _legacy_cellium(freq, duration=0.05):
            n = int(sr * duration)
            i = np.arange(n, dtype=np.float64)
            val = np.where(np.sin(2.0 * np.pi * freq * (i / sr)) > 0, 1.0, -1.0)
            return (4000.0 / 32767.0) * val * np.exp(-i / 500.0)

        # Exact legacy events: ui_click (800Hz/20ms/0.10),
        # sound_female (500Hz/50ms/0.15), sound_male (400Hz/50ms/0.15),
        # ui_swoosh (200Hz/100ms/0.05), cellium_female (550Hz square).
        legacy_targets = {
            "cerebrium_click.wav":       _legacy_smooth(800.0, 0.02, 0.10),
            "cerebrium_pop.wav":         _legacy_smooth(PITCH_F, 0.05, 0.15),
            "cerebrium_send.wav":        _legacy_smooth(PITCH_F, 0.05, 0.15),
            "cerebrium_recv.wav":        _legacy_smooth(PITCH_M, 0.05, 0.15),
            "cerebrium_open.wav":        _legacy_smooth(200.0, 0.10, 0.05),
            "cerebrium_close.wav":       _legacy_smooth(200.0, 0.10, 0.05),
            "cerebrium_type.wav":        _legacy_cellium(550.0),
            "cerebrium_scroll.wav":      _legacy_smooth(800.0, 0.02, 0.10),
            "cerebrium_keypress.wav":    _legacy_cellium(550.0),
            "cerebrium_right_click.wav": _legacy_smooth(800.0, 0.02, 0.10),
            "cerebrium_middle_click.wav": _legacy_smooth(800.0, 0.02, 0.10),
        }
        # Legacy wake chime: the same two voices arranged into a 1.35s rising
        # phrase, so the "appear" event keeps a proper entrance.
        _legacy_appear = np.zeros(int(sr * 1.35), dtype=np.float32)
        for _delay, _sig in (
            (0.00, _legacy_smooth(200.0, 0.10, 0.05)),
            (0.10, _legacy_smooth(PITCH_M, 0.05, 0.15)),
            (0.18, _legacy_smooth(PITCH_F, 0.05, 0.15)),
            (0.26, _legacy_smooth(800.0, 0.02, 0.10)),
            (0.34, _legacy_cellium(550.0)),
        ):
            _off = int(sr * _delay)
            _end = min(_legacy_appear.size, _off + _sig.size)
            _legacy_appear[_off:_end] += _sig[:_end - _off]
        legacy_targets["cerebrium_appear.wav"] = _legacy_appear

        for fname, arr in legacy_targets.items():
            _write_wav(SOUNDS_DIR / fname, arr,
                       overwrite=True, fade=False)

        for path_item, wav_arr in sound_targets:
            _write_wav(path_item, wav_arr, overwrite=need_regen)

        # Animal Crossing / Scratchin Melodi voice notes - EXACT Oct-12 synth.
        # The archived backup's `make_wav` + `freq_func` was:
        #     val = sin(phase) (+ sub/h2/h3 harmonics)
        #     val *= (1 - exp(-i/attack))          # attack in SAMPLES
        #     env  = exp(-i/decay)                 # decay in SAMPLES
        #     out  = amplitude * val * env        # amplitude ~7000/32767
        # No formant filtering, no tanh, no peak normalisation, no pitch
        # scoop. This build had swapped in a formant-filtered, tanh-waveshaped
        # chirp at 0.58 peak - 2.5x louder and a completely different timbre,
        # which is why "Cel's Modern Melodi" did not sound like the archived
        # melodii at all. This is the original maths, sample for sample.
        def _melodi_note_oct12(freq, vdef):
            frames = int(vdef["frames"])
            attack = float(vdef.get("attack", 0) or 0)
            decay = float(vdef.get("decay", 1) or 1)
            amp = float(vdef.get("amplitude", 7000))
            sub = float(vdef.get("sub", 0.0) or 0.0)
            h2 = float(vdef.get("h2", 0.0) or 0.0)
            h3 = float(vdef.get("h3", 0.0) or 0.0)
            vib = float(vdef.get("vib", 0.0) or 0.0)
            vib_hz = float(vdef.get("vib_hz", 0.0) or 0.0)
            i = np.arange(frames, dtype=np.float64)
            t = i / 44100.0
            phase = 2.0 * np.pi * freq * t
            if vib:
                phase = phase + vib * np.sin(2.0 * np.pi * vib_hz * t)
            val = np.sin(phase)
            if sub:
                val = val + sub * np.sin(2.0 * np.pi * (freq / 2.0) * t)
            if h2:
                val = val + h2 * np.sin(2.0 * np.pi * (freq * 2.0) * t)
            if h3:
                val = val + h3 * np.sin(2.0 * np.pi * (freq * 3.0) * t)
            if attack:
                val = val * (1.0 - np.exp(-i / attack))
            env = np.exp(-i / decay) if decay > 0 else np.ones_like(i)
            out = amp * val * env
            # The original wrote `int(...)` with a hard clamp - int() truncates
            # toward zero, which is exactly what astype(int16) does too.
            return np.clip(out, -32767.0, 32767.0).astype(np.int16)

        def _write_wav_pcm16(path: Path, pcm: np.ndarray):
            """Write pre-quantised int16 samples verbatim (no fade, no rescale)."""
            path.parent.mkdir(parents=True, exist_ok=True)
            data = np.asarray(pcm, dtype="<i2")
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                wf.writeframes(data.tobytes())

        _vowel_cycle = ("a", "e", "i", "o", "u", "a", "o", "e", "i", "u", "a")
        for vname, vdef in CEL_VOICE_VARIANTS.items():
            prefix = vdef["prefix"]
            for idx, freq in enumerate(vdef["freqs"]):
                p = SOUNDS_DIR / f"{prefix}{idx}.wav"
                if need_regen or not p.exists():
                    _write_wav_pcm16(p, _melodi_note_oct12(float(freq), vdef))

        if need_regen:
            marker.write_text(_SOUND_ENGINE_VERSION, encoding="utf-8")
            # Don't initialise pygame during boot. Just drop any stale bank;
            # the first chirp/preview reloads lazily from the new files.
            try:
                import cellium.core.config as _cfg
                _cfg.CEL_VOICE_SOUND_OBJECTS.clear()
                _cfg._AC_SOUND_OBJECTS.clear()
            except Exception:
                pass
    except Exception as e:
        dev_log(f"Sound library generation failed: {e}")

# generate_sound_library()

# Wallpaper: always prefer the copy that ships inside the package. The old
# order checked ~/Documents/Projects/Python/.png/Cel Cellium Wallpaper.webp
# first, so the app's look depended on a file outside the project (and broke
# whenever the project was moved or frozen).
_core_assets_dir = Path(__file__).resolve().parent / "assets"
_cand_wp = PROJECTS_DIR / ".png" / "Cel Cellium Wallpaper.webp"
_asset_webp = ASSETS_DIR / "cel_wallpaper.webp"
_asset_png = ASSETS_DIR / "cel_wallpaper.png"

for _wp in (_core_assets_dir / "cel_wallpaper.webp",
            _core_assets_dir / "cel_wallpaper.png",
            _asset_webp, _asset_png, _cand_wp):
    if _wp.exists():
        WALLPAPER_FILE = _wp
        break
else:
    WALLPAPER_FILE = _core_assets_dir / "cel_wallpaper.webp"

_DATA_ROOT = globals().get("USER_DATA_DIR", BASE_DIR)
F_SETTINGS = _DATA_ROOT / "cerebrium_settings.json"
F_SESSIONS = _DATA_ROOT / "cerebrium_sessions.json"
F_PRESETS = _DATA_ROOT / "cerebrium_presets.json"
F_MEMPRESETS = _DATA_ROOT / "cerebrium_memory_presets.json"
F_ANALYTICS = _DATA_ROOT / "cerebrium_analytics.json"


# ── Offline GGUF display labels ────────────────────────────────────────────
# The combo-box text *is* the model key (settings["selected_model"], favorites,
# analytics rows), so the three display switches must be applied in exactly
# one place. Keeping the builder here (Qt-free) means the main window, the
# settings dialog, the Model Hub and the worker resolver can never disagree
# about what an offline model is called.

OFFLINE_MODEL_ICON = "📂"
OFFLINE_MODEL_ICONS = ("📁", "📂")


def format_model_size(num_bytes) -> str:
    """Human size using decimal units, the way file managers report GGUFs.

    ``806_059_008`` bytes → ``"806.1MB"`` (not 768.7 MiB), which is what the
    filename in the user's Downloads folder says.
    """
    try:
        n = float(num_bytes)
    except (TypeError, ValueError):
        return ""
    if n < 0:
        return ""
    for limit, suffix in ((1e12, "TB"), (1e9, "GB"), (1e6, "MB"), (1e3, "KB")):
        if n >= limit:
            return f"{n / limit:.1f}{suffix}"
    return f"{int(n)}B"


def strip_offline_label(text) -> str:
    """Return the bare GGUF name from any offline label, old or new.

    Handles every historical shape in one pass:
    ``📁 Offline: Name``, ``📂 Name.gguf 806.1MB``, ``📂 806.1MB Name.gguf``.
    """
    s = str(text or "").strip()
    s = s.lstrip("".join(OFFLINE_MODEL_ICONS)).strip()
    s = re.sub(r'^Offline:\s*', '', s, flags=re.IGNORECASE).strip()
    # Size prefix/suffix. Requiring .gguf on the other side keeps a real model
    # name like "Qwen 3B" intact - only our generated size token is removed.
    s = re.sub(r'^\d+(?:\.\d+)?\s*(?:[KMGT]i?)?B\s+(?=.*\.gguf$)',
               '', s, flags=re.IGNORECASE)
    s = re.sub(r'(\.gguf)\s+\d+(?:\.\d+)?\s*(?:[KMGT]i?)?B$',
               r'\1', s, flags=re.IGNORECASE)
    s = re.sub(r'\.gguf$', '', s, flags=re.IGNORECASE).strip()
    return s


def is_offline_model_key(model_key, route=None) -> bool:
    """True for every offline label shape, independent of the display toggles."""
    if route == "offline-model":
        return True
    s = str(model_key or "")
    low = s.lower()
    return (
        s.startswith(OFFLINE_MODEL_ICONS)
        or "offline" in low
        or ".gguf" in low
    )


def offline_model_label(name, path="", settings=None, size_bytes=None) -> str:
    """Build the visible label (and therefore the model key) for a GGUF.

    Defaults requested by the user: size ON, the word "Offline" OFF, and the
    size *after* the filename. Each switch is independent so the label can
    become ``📂 Offline: 806.1MB gemma…gguf`` when both extras are enabled.
    """
    settings = settings or {}
    clean = strip_offline_label(name)
    base = os.path.basename(str(path)) if path else ""
    if base and strip_offline_label(base).lower() == clean.lower():
        # The registered name is the file's own basename → show the exact
        # filename (including .gguf), which is what the user recognises.
        display = base
    elif clean.lower().endswith(".gguf"):
        display = clean
    elif not path:
        # Preview / legacy fallback with no path to inspect.
        display = (clean + ".gguf") if clean else ""
    else:
        # A deliberately custom display name ("Phil") keeps its own spelling.
        display = clean

    if size_bytes is None and path:
        try:
            size_bytes = os.path.getsize(path)
        except OSError:
            size_bytes = None
    size_txt = ""
    if size_bytes is not None and settings.get("show_offline_model_size", True):
        size_txt = format_model_size(size_bytes)

    parts = [OFFLINE_MODEL_ICON]
    if settings.get("show_offline_model_tag", False):
        parts.append("Offline:")
    if size_txt and settings.get("offline_model_size_first", False):
        parts.append(size_txt)
    if display:
        parts.append(display)
    if size_txt and not settings.get("offline_model_size_first", False):
        parts.append(size_txt)
    return " ".join(parts)

# A GitHub personal access token used to be hardcoded here, obfuscated across
# several string literals so that grep would miss it. It had NO consumer
# anywhere in this codebase (GH_HEADERS was dead code) and shipping it in a
# repository you intend to publish would leak it. It has been removed.
# Supply a token via the CELSTUDIO_GITHUB_TOKEN environment variable if a
# future feature ever actually needs one.
GH_TOKEN_ENV = "CELSTUDIO_GITHUB_TOKEN"
GH_HEADERS: dict = {}
try:
    _gh = os.environ.get(GH_TOKEN_ENV, "").strip()
    if _gh:
        GH_HEADERS = {
            "Authorization": f"token {_gh}",
            "Accept": "application/vnd.github.v3.raw",
        }
except Exception:
    GH_HEADERS = {}

DEV_PASSWORD_HASH = os.environ.get("CELSTUDIO_DEV_PASSWORD_HASH", "")

#: GitHub Copilot chat models (merged from the standalone "Copilot Arena"
#: client). Served OpenAI-compatibly at api.githubcopilot.com once a GitHub
#: token is exchanged for a short-lived Copilot token - see below.
COPILOT_MODELS = [
    "gpt-4.1",
    "gpt-4o",
    "claude-3.5-sonnet",
    "claude-3.7-sonnet",
    "claude-3.7-sonnet-thought",
    "claude-sonnet-4",
    "gemini-2.0-flash-001",
    "gemini-2.5-pro",
    "o3-mini",
    "o4-mini",
    "o1",
    "copilot-search-a",
    "copilot-search-b",
    "gpt-4o-mini",
    "gpt-4-o-preview",
    "gpt-4.1-2025-04-14",
    "gpt-4o-2024-11-20",
    "gpt-4o-2024-08-06",
    "gpt-4o-2024-05-13",
    "gpt-4o-mini-2024-07-18",
    "gpt-3.5-turbo-0613",
    "Copilot-Integration-Id"
]

COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"

_COPILOT_UA = "GitHubCopilotChat/0.22.2"
_COPILOT_EDITOR = "vscode/1.95.0"
_COPILOT_PLUGIN = "copilot-chat/0.22.2"
_OPENCODE_TOKEN_CACHE = None


def _discover_local_copilot_token() -> str:
    """Auto-discover GitHub Copilot token from OpenCode or GitHub Copilot CLI configs."""
    global _OPENCODE_TOKEN_CACHE
    if _OPENCODE_TOKEN_CACHE is not None:
        return _OPENCODE_TOKEN_CACHE
    home = Path.home()
    # 1. Check OpenCode / Copilot JSON auth stores
    json_Store_paths = [
        home / ".config" / "github-copilot" / "hosts.json",
        home / ".config" / "github-copilot" / "apps.json",
        home / ".local" / "share" / "opencode" / "auth.json",
        home / ".config" / "opencode" / "auth.json",
    ]
    for jp in json_Store_paths:
        if jp.is_file():
            try:
                raw = jp.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"\b(gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b", raw)
                if m:
                    _OPENCODE_TOKEN_CACHE = m.group(1)
                    return _OPENCODE_TOKEN_CACHE
            except Exception:
                pass
    # 2. Check user's external OpenCode script if present on disk
    for py_cand in (
        home / "delete" / ".opencode" / "models abilterated.py",
        home / "delete" / ".opencode" / "models abliterated.py",
    ):
        if py_cand.is_file():
            try:
                raw = py_cand.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"\b(gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b", raw)
                if m:
                    _OPENCODE_TOKEN_CACHE = m.group(1)
                    return _OPENCODE_TOKEN_CACHE
                for b64_m in re.finditer(r"b64decode\(([^)]+)\)", raw):
                    lits = re.findall(r"['\"]([A-Za-z0-9+/=]+)['\"]", b64_m.group(1))
                    if lits:
                        dec = base64.b64decode("".join(lits)).decode("utf-8", errors="ignore").strip()
                        if dec.startswith(("ghp_", "gho_", "ghu_", "github_pat_")):
                            _OPENCODE_TOKEN_CACHE = dec
                            return _OPENCODE_TOKEN_CACHE
            except Exception:
                pass
    _OPENCODE_TOKEN_CACHE = ""
    return ""


def copilot_github_token(settings=None) -> str:
    """GitHub token backing Copilot: Hub key -> env -> local OpenCode/Copilot config."""
    try:
        if settings is None:
            settings = load_json(F_SETTINGS, {})
        key = ((settings.get("user_custom_keys", {}) or {}).get("GitHub Copilot", "") or "").strip()
        if key:
            return key
    except Exception:
        pass
    env_key = (
        os.environ.get("CELSTUDIO_GITHUB_TOKEN", "")
        or os.environ.get("GITHUB_TOKEN", "")
        or os.environ.get("GH_TOKEN", "")
    ).strip()
    if env_key:
        return env_key
    return _discover_local_copilot_token()


def copilot_headers(copilot_token: str, vision: bool = False) -> dict:
    """Request headers for api.githubcopilot.com (OpenCode / VSCode Copilot Chat spec)."""
    hdrs = {
        "Authorization": f"Bearer {copilot_token}",
        "Editor-Version": _COPILOT_EDITOR,
        "Editor-Plugin-Version": _COPILOT_PLUGIN,
        "User-Agent": _COPILOT_UA,
        "Copilot-Integration-Id": "vscode-chat",
        "Openai-Organization": "github-copilot",
        "Openai-Intent": "conversation-panel",
        "X-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    if vision:
        hdrs["Copilot-Vision-Request"] = "true"
    return hdrs


def exchange_copilot_token(github_token: str, timeout: int = 15) -> tuple:
    """Exchange a GitHub token for a short-lived Copilot token.

    Returns ``(token, expires_at_epoch)``; ``("", 0.0)`` on any failure.
    Never raises, never logs the token.
    """
    github_token = (github_token or "").strip()
    if not github_token:
        return "", 0.0
    try:
        resp = requests.get(
            COPILOT_TOKEN_URL,
            headers={"Authorization": f"token {github_token}",
                     "Editor-Version": _COPILOT_EDITOR,
                     "User-Agent": _COPILOT_UA},
            timeout=max(5, int(timeout)))
        if resp.status_code != 200:
            return "", 0.0
        data = resp.json() if hasattr(resp, "json") else {}
        token = (data.get("token", "") or "").strip()
        if not token:
            return "", 0.0
        try:
            exp = float(data.get("expires_at", 0) or 0)
        except (TypeError, ValueError):
            exp = 0.0
        if exp <= 0:
            exp = time.time() + 1500.0
        return token, exp
    except Exception:
        return "", 0.0


PROVIDER_DEFS = {
    "Google Gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "icon": "✨", "color": "#4285F4", "default_models": ["gemini-flash-latest", "gemini-flash-lite-latest"]},
    "Cerebras":     {"base_url": "https://api.cerebras.ai/v1", "icon": "⚡", "color": "#FF7043", "default_models": ["llama3.3-70b", "llama3.1-8b", "llama-3.1-70b"]},
    "Groq":         {"base_url": "https://api.groq.com/openai/v1", "icon": "🚀", "color": "#F4511E", "default_models": [
        "llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama-3.2-11b-vision-preview", "llama-3.2-90b-vision-preview",
        "llama-3.2-1b-preview", "llama-3.2-3b-preview", "mixtral-8x7b-32768", "gemma2-9b-it", "deepseek-r1-distill-llama-70b", "qwen-2.5-32b"
    ]},
    "OpenRouter":   {"base_url": "https://openrouter.ai/api/v1", "icon": "🌐", "color": "#42A5F5", "default_models": ["deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct", "google/gemini-2.0-flash-exp:free", "openai/gpt-4o"]},
    "DeepSeek":     {"base_url": "https://api.deepseek.com/v1", "icon": "🐋", "color": "#26A69A", "default_models": ["deepseek-chat", "deepseek-reasoner"]},
    "Mistral":      {"base_url": "https://api.mistral.ai/v1", "icon": "🌪️", "color": "#FFB74D", "default_models": ["mistral-large-latest", "mistral-small-latest", "codestral-latest", "pixtral-12b-2409"]},
    "SambaNova":    {"base_url": "https://api.sambanova.ai/v1", "icon": "🐆", "color": "#AB47BC", "default_models": ["Meta-Llama-3.3-70B-Instruct", "Qwen2.5-Coder-32B-Instruct"]},
    "Together AI":  {"base_url": "https://api.together.xyz/v1", "icon": "🤝", "color": "#5C6BC0", "default_models": ["meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "Qwen/Qwen2.5-72B-Instruct-Turbo"]},
    "Fireworks AI": {"base_url": "https://api.fireworks.ai/inference/v1", "icon": "🎆", "color": "#EC407A", "default_models": ["accounts/fireworks/models/llama-v3p3-70b-instruct"]},
    "SiliconFlow":  {"base_url": "https://api.siliconflow.cn/v1", "icon": "⚡", "color": "#66BB6A", "default_models": ["Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3"]},
    "Custom (OpenAI)": {"base_url": "http://localhost:8000/v1", "icon": "🔧", "color": "#9E9E9E", "default_models": []},
    "GitHub Copilot": {"base_url": "https://api.githubcopilot.com", "icon": "🤖", "color": "#6E40C9", "default_models": list(COPILOT_MODELS)},
}

def get_network_timeout(settings=None, default=60):
    try:
        if settings is None:
            settings = load_json(F_SETTINGS, {})
        v = int(settings.get("network_timeout", default))
        return max(1, v)
    except Exception:
        return default

def get_network_max_retries(settings=None, default=3):
    try:
        if settings is None:
            settings = load_json(F_SETTINGS, {})
        v = int(settings.get("network_max_retries", default))
        return max(1, min(v, 100))
    except Exception:
        return default

def get_output_max_tokens(settings=None, default=4096):
    try:
        if settings is None:
            settings = load_json(F_SETTINGS, {})
        v = int(settings.get("output_max_tokens", default))
        return max(16, min(v, 32768))
    except Exception:
        return default

def get_disable_combo_wheel(settings=None, default=True):
    try:
        if settings is None:
            settings = load_json(F_SETTINGS, {})
        return bool(settings.get("disable_combo_wheel", default))
    except Exception:
        return default

def get_ac_voice_variant(settings=None, default=None):
    try:
        if default is None:
            default = DEFAULT_AC_VOICE_VARIANT
        if settings is None:
            settings = load_json(F_SETTINGS, {})
        v = settings.get("ac_voice_variant", default)
        if v in CEL_VOICE_VARIANTS:
            return v
        return default
    except Exception:
        return default or DEFAULT_AC_VOICE_VARIANT

def is_vision_model(model_key, route=None):
    mk = (model_key or "").lower()
    if isinstance(route, dict):
        mk += " " + (route.get("model", "")).lower()
    for kw in VISION_KEYWORDS:
        if kw in mk:
            return True
    return False


# ── Model capability detection ───────────────────────────────────────────────
# OpenRouter (and most OpenAI-compatible catalogs) expose per-model
# ``architecture.input_modalities`` / ``output_modalities`` - that is the
# authoritative way to answer "what can this model actually support?" instead
# of defaulting every model to plain text. For offline GGUFs we read the GGUF
# metadata header directly (never loading the weights).

#: Cache of GGUF metadata probes keyed by (path, mtime_ns, size).
_GGUF_CAP_CACHE = {}

#: Architecture / model-name fragments that imply a multimodal encoder.
_VISION_ARCH_HINTS = (
    "llava", "bakllava", "minicpm", "mllama", "llama4", "qwen2vl",
    "qwen2.5vl", "qwen2_5_vl", "qwen2-vl", "paligemma", "pixtral",
    "idefics", "smolvlm", "moondream", "internvl", "phi3v", "phi4",
    "gemma3", "gemma-3", "cogvlm", "granite-vision", "molmo",
    "mistral-small-3", "aya-vision", "falcon-ocr", "deepseek-vl",
    "janus", "emu3", "glm-4v",
)


def _gguf_read_capabilities(model_path):
    """Read a GGUF's metadata header WITHOUT loading weights (fast + cached).

    llama-cpp-python's ``Llama(vocab_only=True)`` still opens/parses the whole
    vocab and was measured at **1.7 s** on a 3B Q4 file - on the UI thread that
    made the ✦ Info card feel frozen. The GGUF header itself is tiny, so we
    parse only the first KV pairs (``general.*`` comes before ``tokenizer.*``)
    and stop before any giant token array.
    """
    if not model_path:
        return {"arch": "", "name": "", "vision": False, "parsed": False}
    try:
        st = os.stat(model_path)
        key = (str(model_path), int(st.st_mtime_ns), int(st.st_size))
    except OSError:
        key = (str(model_path), 0, 0)
    cached = _GGUF_CAP_CACHE.get(key)
    if cached is not None:
        return cached

    info = {"arch": "", "name": "", "vision": False, "parsed": False}
    try:
        with open(model_path, "rb") as f:
            if f.read(4) != b"GGUF":
                raise ValueError("not a GGUF")
            import struct as _struct
            version = _struct.unpack("<I", f.read(4))[0]
            if version == 1:
                f.read(4)  # tensor count (uint32)
                n_kv = _struct.unpack("<I", f.read(4))[0]
            else:
                f.read(8)  # tensor count (uint64)
                n_kv = _struct.unpack("<Q", f.read(8))[0]
            info["parsed"] = True

            def _u(fmt, size):
                return _struct.unpack("<" + fmt, f.read(size))[0]

            def _skip_str():
                f.seek(_u("Q", 8), 1)

            def _skip_val(vtype, depth=0):
                if vtype in (0, 1):
                    f.seek(1, 1)
                elif vtype in (2, 3):
                    f.seek(2, 1)
                elif vtype in (4, 5, 6):
                    f.seek(4, 1)
                elif vtype == 7:
                    f.seek(1, 1)
                elif vtype == 8:
                    _skip_str()
                elif vtype in (10, 11, 12):
                    f.seek(8, 1)
                elif vtype == 9 and depth < 3:
                    etype = _u("I", 4)
                    count = _u("Q", 8)
                    if etype == 8:
                        # Token arrays live here. We only need the early
                        # general.* keys, so bail out instead of walking 100k
                        # strings when the header is unexpectedly ordered.
                        start = f.tell()
                        for i in range(min(count, 500000)):
                            _skip_str()
                            if (i & 0x3FFF) == 0 and (f.tell() - start) > 8 * 1024 * 1024:
                                return False
                    elif etype in (0, 1):
                        f.seek(count, 1)
                    elif etype in (2, 3):
                        f.seek(count * 2, 1)
                    elif etype in (4, 5, 6):
                        f.seek(count * 4, 1)
                    elif etype == 7:
                        f.seek(count, 1)
                    elif etype in (10, 11, 12):
                        f.seek(count * 8, 1)
                    elif etype == 9:
                        for _ in range(min(count, 4096)):
                            if _skip_val(9, depth + 1) is False:
                                return False
                    else:
                        raise ValueError("bad array type")
                else:
                    raise ValueError("bad value type")
                return True

            # general.* keys are emitted first by every converter; 96 pairs is
            # enough to see architecture/name without touching tokenizer arrays.
            for _ in range(min(int(n_kv), 96)):
                klen = _u("Q", 8)
                if klen > 4096:
                    raise ValueError("absurd key length")
                k = f.read(klen).decode("utf-8", "replace")
                vtype = _u("I", 4)
                kl = k.lower()
                if vtype == 8 and kl in ("general.architecture", "general.name",
                                         "general.basename"):
                    slen = _u("Q", 8)
                    if slen > 65536:
                        raise ValueError("absurd string")
                    val = f.read(slen).decode("utf-8", "replace")
                    if kl == "general.architecture":
                        info["arch"] = val
                    else:
                        info["name"] = (info["name"] + " " + val).strip()
                else:
                    if ("vision" in kl or "mmproj" in kl or kl.startswith("clip.")
                            or "vision_encoder" in kl):
                        info["vision"] = True
                    if _skip_val(vtype) is False:
                        break
                if info["arch"] and info["name"]:
                    break
    except Exception:
        pass

    blob = f"{info['arch']} {info['name']}".lower()
    if any(h in blob for h in _VISION_ARCH_HINTS):
        info["vision"] = True
    _GGUF_CAP_CACHE[key] = info
    return info


def gguf_has_vision(model_path) -> bool:
    """True if a local GGUF is a vision/multimodal model.

    Reads the tiny GGUF metadata header (cached per path/mtime) - never loads
    the weights. Falls back to filename keywords when the header is unreadable.
    """
    if not model_path:
        return False
    info = _gguf_read_capabilities(model_path)
    if info.get("vision"):
        return True
    name = str(model_path).lower()
    return any(k in name for k in (
        "llava", "bakllava", "minicpm", "vision", "pixtral", "internvl",
        "qwen2-vl", "qwen2vl", "qwen2.5vl", "mllama", "smolvlm", "moondream",
        "paligemma", "idefics", "phi3v", "gemma-3", "gemma3",
    ))


def get_model_capabilities(model_key, models, settings=None, details_cache=None, model_path=""):
    """Return a dict describing what a model can actually support.

    Keys: ``vision`` (bool), ``modalities`` (list[str]), ``files`` (str),
    ``cap_str`` (str), ``source`` (str describing how determined).

    Cloud models are answered from the provider catalog metadata
    (OpenRouter-style ``architecture.input_modalities``). Offline GGUFs are
    answered from the GGUF header / filename keywords.
    """
    settings = settings or {}
    models = models or {}
    route = models.get(model_key) or {}
    if not isinstance(route, dict):
        route = {}
    provider = str(route.get("provider", "")).lower()
    model_id = str(route.get("model", "") or model_key or "")
    mk = f"{model_key} {model_id}".lower()

    details = {}
    if isinstance(details_cache, dict):
        for ck in (f"{route.get('provider', '')}:{model_id}",
                   f"{provider}:{model_key}", model_id, model_key):
            got = details_cache.get(ck)
            if isinstance(got, dict) and got:
                details = got
                break

    modalities = []
    if isinstance(details, dict):
        arch = details.get("architecture") or {}
        if isinstance(arch, dict):
            modalities = list(arch.get("input_modalities") or [])
        if not modalities:
            modalities = list(details.get("input_modalities") or [])
        modalities = [str(m).lower() for m in modalities]

    vision = "image" in modalities or "image_url" in modalities
    source = "catalog metadata" if modalities else "name heuristic"

    if not vision:
        # Offline GGUF path (route values are usually just "offline-model").
        model_path = model_path or str(route.get("path", "") or route.get("model_path", "") or "")
        if not model_path and settings:
            try:
                bare = strip_offline_label(model_key)
                for nm, p in (settings.get("offline_models", {}) or {}).items():
                    if isinstance(p, str) and strip_offline_label(nm) == bare:
                        model_path = p
                        break
            except Exception:
                pass
        if is_offline_model_key(model_key, route) or provider in ("offline", "llama") or model_path:
            info = _gguf_read_capabilities(model_path) if model_path else {}
            if info.get("vision"):
                vision = True
                source = "GGUF metadata"
            elif any(k in mk for k in VISION_KEYWORDS):
                vision = True
                source = "filename heuristic"

    files = ("Images (.png, .jpg, .webp), Text & Code (.py, .txt, .json, .md)"
             if vision else
             "Text, Python, JSON, Markdown, Shell, CSV, Logs")
    cap_str = "🖼️ Vision & Multimodal" if vision else "💬 Conversational Text & Code"

    return {
        "vision": vision,
        "modalities": modalities,
        "files": files,
        "cap_str": cap_str,
        "source": source,
    }


_LLAMA_CACHE = {
    "model_path": None,
    "instance": None,
    "n_ctx": 4096,
    "n_threads": 4,
    "n_gpu_layers": 0
}

_EMOJI_POOL_CACHE = None

def all_emoji_pool():
    """Full Unicode emoji pool via the `emoji` package (no hardcoding)."""
    global _EMOJI_POOL_CACHE
    if _EMOJI_POOL_CACHE:
        return _EMOJI_POOL_CACHE
    try:
        import emoji
        fq = getattr(emoji, "STATUS", {}).get("fully_qualified", 2)
        pool = [e for e, meta in emoji.EMOJI_DATA.items() if meta.get("status") == fq]
        if not pool:
            pool = list(emoji.EMOJI_DATA.keys())
        if not pool:
            raise RuntimeError("emoji.EMOJI_DATA empty")
        _EMOJI_POOL_CACHE = pool
        return pool
    except Exception as e:
        dev_log(f"emoji pool load failed: {e}")
        _EMOJI_POOL_CACHE = ["😀", "😃", "😄", "😁", "😆", "😅", "😂", "🤣", "😊", "😇",
            "🙂", "😉", "😍", "🥰", "😘", "😜", "🤪", "🤗", "🤭", "🤫",
            "🤔", "😐", "😏", "🙄", "😬", "😮", "🥺", "😎", "🤓", "🥳",
            "😺", "😸", "😹", "😻", "😼", "😽"]
        return _EMOJI_POOL_CACHE

def _rss_mb():
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0

def free_all_ram(skip_gguf=False):
    """Aggressively frees GGUF model RAM, Python heap, Qt pixmaps, and OS memory pages.
    Returns a stats dict so callers can always show visible feedback.
    ``skip_gguf`` keeps the warm model: unloading mid-generation lets the next
    send mmap a *second* multi-GB model next to the still-generating one (OOM)."""
    before = _rss_mb()
    gguf_freed = False
    if skip_gguf:
        dev_log("🧹 GGUF kept warm - generation still running")
    else:
        try:
            from cellium.services.ai_llama import unload_llama, request_llama_abort
            request_llama_abort()
            # Never poke a cache entry here: ai_llama owns the live instance
            # and refuses to free it while a worker still owns it.
            gguf_freed = bool(unload_llama())
            if gguf_freed:
                dev_log("🧹 GGUF RAM freed")
        except Exception as e:
            dev_log(f"GGUF unload failed: {e}")
    collected = gc.collect()
    collected += gc.collect()
    dev_log(f"🧹 Python GC collected {collected} objects")
    try:
        from PySide6.QtGui import QPixmapCache
        QPixmapCache.clear()
        dev_log("🧹 Qt QPixmapCache cleared")
    except Exception:
        pass
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.malloc_trim(0)
        dev_log("🧹 System malloc_trim(0) called")
    except Exception:
        pass
    after = _rss_mb()
    freed_mb = max(0.0, before - after)
    dev_log(f"🧹 RSS {before:.1f} MB → {after:.1f} MB (freed {freed_mb:.1f} MB)")
    return {"gguf": gguf_freed, "before": before, "after": after,
            "freed_mb": freed_mb, "objects": collected}

def is_llama_loaded():
    try:
        from cellium.services import ai_llama
        for slot in ("_LLAMA_CACHE", "_LLAMA_PREV"):
            cache = getattr(ai_llama, slot, None)
            if isinstance(cache, dict) and cache.get("instance") is not None:
                return True
        return False
    except Exception:
        pass
    return _LLAMA_CACHE["instance"] is not None

# ------------------------------------------------------------------ STT Workers
MAX_SEGMENT_CHARS = 8000
TARGET_WORDS = 35
HARD_WORDS = 55
INTER_CHUNK_SILENCE_S = 0.25
FADE_MS = 6.0

def physical_core_count() -> int:
    try:
        core_ids = {
            p.read_text().strip()
            for p in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/topology/core_id")
        }
        return len(core_ids) or os.cpu_count() or 4
    except Exception:
        return os.cpu_count() or 4

_KOKORO_SESSION_CACHE = {}
#: Settings → TTS model folder ("" = auto-resolve). Set by the main window on
#: boot and on every settings save; utils itself never reads the settings file.
_KOKORO_TTS_DIR_OVERRIDE = ""


def set_kokoro_tts_dir(path: str) -> None:
    """Point ``get_kokoro`` at a user-chosen folder of ONNX + voice files."""
    global _KOKORO_TTS_DIR_OVERRIDE
    new = str(path or "")
    if new != _KOKORO_TTS_DIR_OVERRIDE:
        _KOKORO_TTS_DIR_OVERRIDE = new
        _KOKORO_SESSION_CACHE.clear()

def get_kokoro(threads: int | None = None):
    try:
        import onnxruntime as ort
        from kokoro_onnx import Kokoro
    except ImportError:
        return None

    if threads is None:
        threads = physical_core_count()
    if threads not in _KOKORO_SESSION_CACHE:
        model_p = Path(__file__).resolve().parent / "kokoro-v1.0.fp16.onnx"
        voice_p = Path(__file__).resolve().parent / "voices-v1.0.bin"
        if not model_p.exists() or not voice_p.exists():
            # Settings override → env/filesystem chain (needs BOTH files).
            cand = [Path(p) for p in dict.fromkeys(filter(None, [
                _KOKORO_TTS_DIR_OVERRIDE,
                str(KOKORO_DIR),
                str(Path.home() / "Documents" / "Projects" / "Kokoro"),
            ]))]
            found = next(
                (d for d in cand
                 if (d / "kokoro-v1.0.fp16.onnx").exists()
                 and (d / "voices-v1.0.bin").exists()), None)
            if found is None:
                return None
            model_p = found / "kokoro-v1.0.fp16.onnx"
            voice_p = found / "voices-v1.0.bin"
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        session = ort.InferenceSession(str(model_p), sess_options=opts, providers=["CPUExecutionProvider"])
        _KOKORO_SESSION_CACHE[threads] = Kokoro.from_session(session, str(voice_p))
    return _KOKORO_SESSION_CACHE[threads]

def segment_text(text: str, max_chars: int = MAX_SEGMENT_CHARS) -> list[str]:
    pieces = [p.strip() for p in re.split(r"(?<=[.!?…])\s+|\n+", text.strip()) if p.strip()]
    sections = []
    cur = []
    size = 0
    for piece in pieces:
        if cur and size + len(piece) + 1 > max_chars:
            sections.append(" ".join(cur))
            cur, size = [], 0
        if len(piece) > max_chars:
            if cur:
                sections.append(" ".join(cur))
                cur, size = [], 0
            for i in range(0, len(piece), max_chars):
                sections.append(piece[i:i + max_chars])
            continue
        cur.append(piece)
        size += len(piece) + 1
    if cur:
        sections.append(" ".join(cur))
    return sections

def _sentences(text: str):
    for para in re.split(r"\n+", text.strip()):
        para = para.strip()
        if not para:
            continue
        for piece in re.split(r"(?<=[.!?…])\s+", para):
            if piece.strip():
                yield piece.strip()

def _split_long(sentence: str, hard: int) -> list[str]:
    out = []
    cur = []
    words = 0
    for clause in re.split(r"(?<=[,;:])\s+", sentence):
        w = len(clause.split())
        if w > hard:
            if cur:
                out.append(" ".join(cur))
                cur, words = [], 0
            cw = clause.split()
            out.extend(" ".join(cw[i:i + hard]) for i in range(0, len(cw), hard))
            continue
        if cur and words + w > hard:
            out.append(" ".join(cur))
            cur, words = [], 0
        cur.append(clause)
        words += w
    if cur:
        out.append(" ".join(cur))
    return out

def chunk_text(text: str, target: int = TARGET_WORDS, hard: int = HARD_WORDS, min_words: int = 8) -> list[str]:
    sents = list(_sentences(text))
    if not sents:
        return []
    chunks = []
    cur = []
    words = 0
    for s in sents:
        w = len(s.split())
        if w > hard:
            if cur:
                chunks.append(" ".join(cur))
                cur, words = [], 0
            chunks.extend(_split_long(s, hard))
            continue
        if cur and words >= min_words and (words + w > target or (s and s[-1] in ".!?")):
            chunks.append(" ".join(cur))
            cur, words = [], 0
        cur.append(s)
        words += w
    if cur:
        chunks.append(" ".join(cur))
    return chunks

def to_pcm(samples: np.ndarray) -> bytes:
    if len(samples) == 0:
        return b""
    peak = float(np.max(np.abs(samples))) if samples.size > 0 else 0.0
    if peak > 0.001:
        # Boost volume safely to 0.92 peak (-0.7 dB headroom), max 2.8x gain
        gain = min(2.8, 0.92 / peak)
        samples = samples * gain
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()

def fade_edges(samples: np.ndarray, sr: int = 24000, ms: float = FADE_MS) -> np.ndarray:
    n = int(sr * ms / 1000.0)
    if n < 2 or len(samples) < 2 * n:
        return samples
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    out = np.array(samples, dtype=np.float32, copy=True)
    out[:n] *= ramp
    out[-n:] *= ramp[::-1]
    return out

KOKORO_VOICES = [
    # Kokoro v1.0 ships every one of these in voices-v1.0.bin - the full
    # multi-voice set, not a 7-voice sample.
    ("Alloy • Female • US (Kokoro | Offline)", "af_alloy"),
    ("Aoede • Female • US (Kokoro | Offline)", "af_aoede"),
    ("Bella • Female • US (Kokoro | Offline)", "af_bella"),
    ("Heart • Female • US (Kokoro | Offline)", "af_heart"),
    ("Jessica • Female • US (Kokoro | Offline)", "af_jessica"),
    ("Kore • Female • US (Kokoro | Offline)", "af_kore"),
    ("Nicole • Female • US (Kokoro | Offline)", "af_nicole"),
    ("Nova • Female • US (Kokoro | Offline)", "af_nova"),
    ("River • Female • US (Kokoro | Offline)", "af_river"),
    ("Sarah • Female • US (Kokoro | Offline)", "af_sarah"),
    ("Sky • Female • US (Kokoro | Offline)", "af_sky"),
    ("Adam • Male • US (Kokoro | Offline)", "am_adam"),
    ("Echo • Male • US (Kokoro | Offline)", "am_echo"),
    ("Eric • Male • US (Kokoro | Offline)", "am_eric"),
    ("Fenrir • Male • US (Kokoro | Offline)", "am_fenrir"),
    ("Liam • Male • US (Kokoro | Offline)", "am_liam"),
    ("Michael • Male • US (Kokoro | Offline)", "am_michael"),
    ("Onyx • Male • US (Kokoro | Offline)", "am_onyx"),
    ("Puck • Male • US (Kokoro | Offline)", "am_puck"),
    ("Santa • Male • US (Kokoro | Offline)", "am_santa"),
    ("Alice • Female • UK (Kokoro | Offline)", "bf_alice"),
    ("Emma • Female • UK (Kokoro | Offline)", "bf_emma"),
    ("Isabella • Female • UK (Kokoro | Offline)", "bf_isabella"),
    ("Lily • Female • UK (Kokoro | Offline)", "bf_lily"),
    ("Daniel • Male • UK (Kokoro | Offline)", "bm_daniel"),
    ("Fable • Male • UK (Kokoro | Offline)", "bm_fable"),
    ("George • Male • UK (Kokoro | Offline)", "bm_george"),
    ("Lewis • Male • UK (Kokoro | Offline)", "bm_lewis"),
]

EDGE_VOICES = [
    ("Jenny • Female • US (Edge TTS | Online)", "en-US-JennyNeural"),
    ("Aria • Female • US (Edge TTS | Online)", "en-US-AriaNeural"),
    ("Ana • Female • US (Edge TTS | Online)", "en-US-AnaNeural"),
    ("Michelle • Female • US (Edge TTS | Online)", "en-US-MichelleNeural"),
    ("Joanna • Female • US (Edge TTS | Online)", "en-US-JoannaNeural"),
    ("Sara • Female • US (Edge TTS | Online)", "en-US-SaraNeural"),
    ("Nancy • Female • US (Edge TTS | Online)", "en-US-NancyNeural"),
    ("Guy • Male • US (Edge TTS | Online)", "en-US-GuyNeural"),
    ("Christopher • Male • US (Edge TTS | Online)", "en-US-ChristopherNeural"),
    ("Eric • Male • US (Edge TTS | Online)", "en-US-EricNeural"),
    ("Andrew • Male • US (Edge TTS | Online)", "en-US-AndrewNeural"),
    ("Tony • Male • US (Edge TTS | Online)", "en-US-TonyNeural"),
    ("Evan • Male • US (Edge TTS | Online)", "en-US-EvanNeural"),
    ("Sonia • Female • UK (Edge TTS | Online)", "en-GB-SoniaNeural"),
    ("Ryan • Male • UK (Edge TTS | Online)", "en-GB-RyanNeural"),
    ("Libby • Female • UK (Edge TTS | Online)", "en-GB-LibbyNeural"),
    ("Swara • Female • IN (Edge TTS | Online)", "en-IN-SwaraNeural"),
]

def clean_for_tts(text: str, skip_asterisks: bool = True) -> str:
    text = _wave7_wrap_gemma_think(text)  # wave7: gemma hook
    # Reasoning blocks, tool calls and mood lines are markup - never spoken.
    # (Angle brackets used to be stripped while the words "think /think" and
    # whole tool-JSON payloads were read aloud.)
    text, _ = split_think(text)
    text = strip_tool_markers(text)
    text, _ = split_mood_first(text)
    # Legacy inline mood ("Mood: warm And remember..."): drop the tag, keep
    # the sentence - the strict full-line pass above already took contract lines.
    text = _MOOD_INLINE_RE.sub(' ', text)
    # Remove fenced code blocks (```python ... ```) completely - AI code dumps are useless to listen to
    # Handles both closed and unclosed blocks
    text = re.sub(r'```[\w]*\n[\s\S]*?(?:```|$)', ' ', text)
    text = re.sub(r'```[\s\S]*?(?:```|$)', ' ', text)
    # Inline code: SPEAK the words, drop only the backticks. Deleting the
    # words turned "Hello `User`, how can I `help` you" into "Hello, how can I you".
    text = text.replace('`', '')
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'(?:/[a-zA-Z0-9._-]+)+', ' ', text)
    text = re.sub(r'[A-Za-z]:\\[\w.-]+', ' ', text)

    if skip_asterisks:
        text = re.sub(r'\*[^*\n]*(\*|$)', ' ', text)
        text = re.sub(r'_[^_\n]*(_|$)', ' ', text)
    else:
        text = re.sub(r'[*_]', ' ', text)

    # Strip parenthesized kaomojis or non-ascii expressions
    text = re.sub(r'\([^)]*[^\x20-\x7E][^)]*\)', ' ', text)

    # Strip CJK scripts, Katakana, Hiragana, fullwidth forms, and symbols
    text = re.sub(r'[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\uFF00-\uFFEF\u4E00-\u9FFF\u2E80-\u2FD5\u2000-\u206F\u2190-\u21FF\u25A0-\u25FF\u2600-\u26FF\u2700-\u27BF]', ' ', text)

    # Strip any remaining non-ASCII characters
    text = re.sub(r'[^\x20-\x7E]', ' ', text)

    # Remove formatting symbols
    text = re.sub(r'[~#><^=+|\\]', ' ', text)

    # Keep only clean ASCII letters, digits, basic punctuation
    text = re.sub(r'[^a-zA-Z0-9\s.,!?\'"-]', ' ', text)

    # Clean whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# ── chat-markup strippers (single source of truth) ───────────────────────
# Every renderer (chat bubble, transcript, live captions) and every speaker
# (chat TTS, live voice) must agree on what is *markup* vs *words*. These
# helpers are that agreement - a parsing fix lands here once instead of in
# six scattered call sites that drift apart and eat each other's sentences.

_THINK_OPEN_RE = re.compile(r'<think(?:\s[^>]*)?>', re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r'</think\s*>', re.IGNORECASE)
_THINK_PAIR_RE = re.compile(
    r'<think(?:\s[^>]*)?>.*?</think\s*>', re.DOTALL | re.IGNORECASE)

# The mood contract: the model puts the face key on its OWN LINE  - 
# first line of the reply ("mood: happy"). Full-line match only, 1–3 bare
# words, first match wins. The old value class ``[a-zA-Z_,\\s]+`` was greedy
# across newlines, so an inline "Mood: warm And remember, ..." swallowed the
# whole following sentence up to the next period - text lost from the bubble
# AND the mood parsed to garbage (hence the stuck/static face).
_MOOD_LINE_RE = re.compile(
    r'(?im)^[ \t]*(?:\*{1,2}|_{1,2}|`)?(?:mood|emotions?)'
    r'(?:\*{1,2}|_{1,2}|`)?[ \t]*:[ \t]*'
    r'([A-Za-z_]+(?:[ \t]*,[ \t]*[A-Za-z_]+){0,2})[^\n]*$'
)
# Matches partial first-line mood header while streaming (e.g. "mood:" or "mood: ")
_MOOD_STREAM_PREFIX_RE = re.compile(
    r'(?i)^\s*(?:\*{1,2}|_{1,2}|`)?(?:mood|emotions?)(?:\*{1,2}|_{1,2}|`)?\s*:\s*[A-Za-z_, ]*$'
)
# Legacy inline fallback: "Mood: warm And remember" drops the tag, keeps prose.
_MOOD_INLINE_RE = re.compile(r'(?i)\b(?:mood|emotions?)\s*:\s*[a-zA-Z_]+')

# ── Editable system-instruction categories ───────────────────────────────────
# Every block below is *actually sent* to the model. They used to be hardcoded
# in main_window/ai_workers, which meant the user could not see - let alone
# remove - a single wasted token. Settings → Persona & Memory now edits these
# strings directly; an empty string means "send nothing" (category disabled).
SYSTEM_INSTRUCTION_DEFAULTS = {
    "style": (
        "[STYLE RULE: Be natural and concise. Do NOT explain your code or "
        "commands unless the user explicitly asks for an explanation.]"
    ),
    "identity": (
        "[IDENTITY RULE: The persona above is who you ARE, not a description "
        "to recite. NEVER introduce yourself, NEVER list your traits, name, "
        "backstory or rules, and NEVER announce things like \"here is my "
        "persona\" or \"as a Gen-Z I am\". Simply BE the persona from the "
        "very first word as if you have always been this person. If asked "
        "who you are, answer naturally in character with one short sentence "
        " -  never dump or summarize the prompt.]"
    ),
    "mood": (
        "Start EVERY reply with exactly one first line in the form "
        "`mood: <key>` - on its own line, no bold, no bullet - where <key> "
        "is the face that best matches your emotion, chosen from: happy, "
        "excited, thinking, working, love, playful, sad, worried, tired, "
        "sleepy, confused, error, sassy, shocked, waking, gremlin, deadpan, "
        "warm, idle. Use ONLY a key from this list - NEVER invent one (no "
        "'crazy', no 'mischief'); if none fit your feeling, pick the closest "
        "key. Example:\nmood: warm\n"
        "That line drives your expression and is never shown to the user or "
        "spoken aloud. Never skip it, never put it last."
    ),
    "coding": (
        "You are a code generator. Output ONLY the requested code in a "
        "single fenced code block. No prose, no explanations, no greetings, "
        "no markdown outside the code block. After the block, one short "
        "line: 'Change \"<placeholder>\" to desired value.' only if needed."
    ),
    "extra": "",
}

SYSTEM_INSTRUCTION_ORDER = ("style", "identity", "mood", "coding", "extra")
SYSTEM_INSTRUCTION_LABELS = {
    "style": "✍️ Style rule",
    "identity": "🪞 Identity rule",
    "mood": "🎭 Mood contract (Live / Pet only)",
    "coding": "💻 Coding Mode prompt",
    "extra": "➕ Extra instructions (always appended)",
}
SYSTEM_INSTRUCTION_HINTS = {
    "style": "Tone and length guidance. Empty = no style rule at all.",
    "identity": "Stops the persona description from being recited out loud.",
    "mood": (
        "Only appended while Live Mode or the desktop pet is active, and "
        "stripped again the moment you leave - so chat never pays for it."
    ),
    "coding": "Used instead of every other category while Coding Mode is on.",
    "extra": "Your own always-on instructions. Empty by default.",
}


def system_instructions(settings) -> dict:
    """Return the effective category texts for this settings dict.

    Stored overrides win (including an intentional empty string, which
    disables that category); missing keys fall back to the defaults.
    """
    stored = (settings or {}).get("system_instructions")
    if not isinstance(stored, dict):
        stored = {}
    out = {}
    for key, default in SYSTEM_INSTRUCTION_DEFAULTS.items():
        if key in stored and stored[key] is not None:
            out[key] = str(stored[key]).strip()
        else:
            out[key] = default
    return out


# ── Force Off reasoning control ───────────────────────────────────────────────
# Native reasoning APIs still think when merely "disabled" on some providers,
# and system-prompt-only "do not think" is easy for a model to ignore. Force
# Off combines both: the provider parameter when one exists + this critical
# directive in the system prompt.
THINKING_FORCE_OFF_DIRECTIVE = (
    "\n[CRITICAL - THINKING: FORCE OFF] Do NOT think, plan, analyze, or "
    "deliberate. Do NOT emit <think> blocks or any internal monologue. "
    "Answer IMMEDIATELY with only the final response; never restate the "
    "question and never explain your process. Any reasoning is forbidden."
)


def inject_force_off_directive(messages: list) -> list:
    """Append the Force Off directive to the first system message in-place."""
    if not messages:
        return messages
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "system":
            content = m.get("content")
            if isinstance(content, str):
                if THINKING_FORCE_OFF_DIRECTIVE not in content:
                    m["content"] = content + THINKING_FORCE_OFF_DIRECTIVE
            return messages
    messages.insert(0, {
        "role": "system",
        "content": THINKING_FORCE_OFF_DIRECTIVE.strip(),
    })
    return messages


THINKING_LEVELS = ("force_off", "off", "auto", "minimal", "low", "medium",
                   "high", "max")
_THINKING_LABELS = {
    "force_off": "⛔ Force Off",
    "off": "✦ Off", "auto": "✦ Auto", "minimal": "✦ Minimal", "low": "✦ Low",
    "medium": "✦ Medium", "high": "✦ High", "max": "✦ Max",
}

def thinking_level_key(value) -> str:
    """Normalise any legacy thinking dropdown value to a stable key.

    The saved value drifted across builds ("✦ Low", "🧠 Low", "low"...),
    which is why the dropdown forgot the pick and workers misread it.
    Keys are the only thing persisted now; labels are display-only.
    """
    v = str(value or "").strip().lower()
    # "force off" also contains "off" - match the stronger mode first.
    if "force" in v:
        return "force_off"
    if "default" in v:
        # Legacy label for the Off key ("✦ Default").
        return "off"
    if "off" in v:
        return "off"
    for key in THINKING_LEVELS:
        if key and key in v:
            return key
    return "auto"

def thinking_level_label(value) -> str:
    """Canonical display label for a thinking level key."""
    return _THINKING_LABELS.get(thinking_level_key(value), "✦ Auto")

def split_think(text: str) -> tuple[str, list]:
    """Split ``(display_text, thoughts)`` - safe for every way a reasoning
    model emits ``<think>``: several closed pairs, a trailing unclosed block
    mid-stream, stray closes, tag attributes, any case.

    The old code split on the FIRST ``"<think>"`` only, so a second block
    dragged the actual answer into the thought card (giant card + missing
    reply + 999x layout blowout).
    """
    text = str(text or "")
    thoughts = []
    for m in re.finditer(
            r'<think(?:\s[^>]*)?>(.*?)</think\s*>',
            text, flags=re.DOTALL | re.IGNORECASE):
        t = m.group(1).strip()
        if t:
            thoughts.append(t)
    clean = _THINK_PAIR_RE.sub('', text)
    # A trailing UNCLOSED opener (still streaming): everything after it is
    # thought-in-progress, never display text.
    m = _THINK_OPEN_RE.search(clean)
    if m:
        tail = clean[m.end():].strip()
        if tail:
            thoughts.append(tail)
        clean = clean[:m.start()]
    clean = _THINK_CLOSE_RE.sub('', clean)
    clean = re.sub(r'[ \t]+\n', '\n', clean)
    clean = re.sub(r'\n{3,}', '\n\n', clean).strip()
    return clean, thoughts

def split_mood_first(text: str) -> tuple[str, str | None]:
    """Split ``(display_text, mood_value)`` per the first-line mood contract."""
    text = str(text or "")
    if _MOOD_STREAM_PREFIX_RE.match(text):
        return "", None
    m = _MOOD_LINE_RE.search(text)
    mood = m.group(1).strip().lower() if m else None
    clean = _MOOD_LINE_RE.sub('', text)
    clean = re.sub(
        r'(?i)^\s*(?:\*{1,2}|_{1,2}|`)?(?:mood|emotions?)(?:\*{1,2}|_{1,2}|`)?\s*:\s*[A-Za-z_]+(?:\s*,\s*[A-Za-z_]+){0,2}[.!~\s]*',
        '',
        clean,
    )
    clean = re.sub(r'\n{3,}', '\n\n', clean).strip()
    return clean, mood

def split_moods_all(text: str) -> list:
    """Ordered mood keys from EVERY mood-directive line (sequential playback).

    Same strict line rule as :func:`split_mood_first` (prose is never
    matched); comma lists expand in order and consecutive duplicates
    collapse, so ``["warm", "warm", "happy"]`` plays two faces, not three.
    Display stripping is unchanged - :func:`split_mood_first` already
    removes every directive line; unknown keys are safe because
    ``CompanionStage.react`` falls back to idle.
    """
    out: list = []
    for m in _MOOD_LINE_RE.finditer(str(text or "")):
        for part in m.group(1).split(","):
            key = part.strip().lower()
            if key and (not out or out[-1] != key):
                out.append(key)
    return out

def strip_tool_markers(text: str) -> str:
    """Remove machine-only tool-call markup (never displayed, never spoken)."""
    text = str(text or "")
    while True:
        match = re.search(
            r'(?:TOOL_CALL|TOOLCALL|\[TOOL_CALL\]|\[TOOLCALL\])\s*:',
            text, re.IGNORECASE)
        if not match:
            break
        json_str, _s_idx, e_idx = extract_balanced_json(text, match.end())
        if json_str:
            text = text[:match.start()] + text[e_idx:]
        else:
            text = text[:match.start()] + text[match.end():]
            break
    text = re.sub(r'<agent_action\b.*?</agent_action\s*>', '',
                  text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<respond>.*?</respond\s*>', '',
                  text, flags=re.DOTALL | re.IGNORECASE)
    return text

def strip_inline_mood_display(text: str) -> str:
    """Drop a legacy INLINE mood tag for display, keeping the sentence.

    The strict contract is a full ``mood: <key>`` line (handled by
    :func:`split_mood_first`), but models also emit ``"Mood: warm And ..."``
    mid-sentence - which used to render literally in the bubble (the face
    still reacted, the words just stayed visible). Only matches at the start
    of the text or right after a sentence boundary, so genuine prose like
    "her mood: happy song" mid-sentence is never eaten. Display-only:
    memory and TTS have their own cleaners.
    """
    # Strip EVERY "mood: <word>" occurrence anywhere in the text - not just at
    # sentence boundaries. The model loves to leak "Mood: Crazy" mid-sentence.
    clean = re.sub(
        r'(?:\*{1,2}|_{1,2})?(?:mood|emotions?)'
        r'(?:\*{1,2}|_{1,2})?\s*:\s*[A-Za-z_]+(?:\s*,\s*[A-Za-z_]+){0,2}',
        '', str(text or ""), flags=re.IGNORECASE)
    clean = re.sub(r' {2,}', ' ', clean)
    return re.sub(r'[ \t]+\n', '\n', clean).strip()


# ── Bug 19: memory hygiene for imitator models ────────────────────────────────
# Some offline GGUFs "think" in plain text ("think: ...") and echo control
# tokens ("TOOL", "TOOLmood: excited"). Whatever they write gets SAVED into
# session memory and becomes the style example for every later turn - the
# junk literally taught itself. This keeps stored history clean.
_THINK_LINE_RE = re.compile(
    r"^[\t ]*(?:[\*_~`>#\-]+[\t ]*)?think[\t ]*[:\uff1a].*$",
    re.IGNORECASE | re.MULTILINE)
_TOOL_JUNK_LINE_RE = re.compile(
    r"^[\t ]*(?:[\*_~`>#\-]+[\t ]*)?TOOL(?:CALL)?\b[\t ]*:?.*$",
    re.IGNORECASE | re.MULTILINE)
_TOOL_JUNK_INLINE_RE = re.compile(
    r"(?i)\bTOOL(?:CALL)?\b(?=[\W_]{0,6}(?:call\b|Mood\b|:))")
# Model echoes a bare control token glued to the next sentence ("TOOLI have…").
_TOOL_ECHO_LEAD_RE = re.compile(r"(?m)^[\t ]*TOOL(?=[A-Z])")
_TOOL_ECHO_LEAD_SPACE_RE = re.compile(r"(?m)^[\t ]*TOOL[\t ]+(?=I\b)")


def sanitize_memory_reply(text: str) -> str:
    """Strip imitator junk (think: headers, TOOL echoes) from text about to be
    SAVED to session memory (or replayed to the model as history)."""
    s = str(text or "")
    if not s:
        return s
    s = _TOOL_JUNK_INLINE_RE.sub("", s)   # "TOOLmood: excited" → "mood: excited"
    s = _TOOL_ECHO_LEAD_RE.sub("", s)      # "TOOLI have…" → "I have…"
    s = _TOOL_ECHO_LEAD_SPACE_RE.sub("", s)  # "TOOL I have…" → "I have…"
    s = _THINK_LINE_RE.sub("", s)          # pseudo "think:" headers
    s = _TOOL_JUNK_LINE_RE.sub("", s)      # dangling "TOOL"/"TOOL_CALL:" lines
    try:
        s = strip_tool_markers(s)
        s = strip_inline_mood_display(s)
    except Exception:
        pass
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def clean_chat_display(text: str) -> str:
    """What a bubble shows: no thought blocks, no tool markup, no mood line."""
    text = _wave7_wrap_gemma_think(text)  # wave7: gemma hook
    clean, _ = split_think(text)
    clean = strip_tool_markers(clean)
    clean, _ = split_mood_first(clean)
    clean = strip_inline_mood_display(clean)
    return clean.strip()

def extract_balanced_json(text: str, start_pos: int = 0) -> tuple[str, int, int]:
    """
    Finds the first balanced JSON object starting from or after start_pos.
    Returns (json_str, start_idx, end_idx) or ("", -1, -1).
    """
    first_brace = text.find("{", start_pos)
    if first_brace == -1:
        return "", -1, -1
    
    depth = 0
    in_string = False
    escape = False
    
    for i in range(first_brace, len(text)):
        char = text[i]
        
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
            
        if not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[first_brace:i+1], first_brace, i+1
    return "", -1, -1

_MISTUNE_MD = None
_MISTUNE_TRIED = False


def _get_mistune_md():
    """Lazy singleton mistune renderer (Tier 1 markdown pipeline)."""
    global _MISTUNE_MD, _MISTUNE_TRIED
    if not _MISTUNE_TRIED:
        _MISTUNE_TRIED = True
        try:
            import mistune
            _MISTUNE_MD = mistune.create_markdown(
                escape=True,
                plugins=["table", "strikethrough", "task_lists"],
            )
            dev_log("mistune markdown renderer ready")
        except Exception as e:
            _MISTUNE_MD = None
            dev_log(f"mistune unavailable, markdown falls back to Qt renderer: {e}")
    return _MISTUNE_MD


def _cel_inject_styles(html_doc: str, accent_bright: str, accent_dark: str, accent_light: str) -> str:
    """Post-process markdown HTML: inline CSS theming, heading glyphs, dividers, checkboxes."""
    if not html_doc:
        return ""

    # 1) Stash <pre> code blocks so inline styling never touches their contents
    pres = []

    def _stash_pre(m):
        pres.append(m.group(0))
        return f"\x00PRE{len(pres) - 1}\x00"

    html_doc = re.sub(r"<pre\b.*?</pre>", _stash_pre, html_doc, flags=re.DOTALL | re.IGNORECASE)

    # 2) Task-list checkboxes -> glyphs (QTextDocument cannot render <input>)
    def _cb(m):
        checked = "checked" in m.group(0)
        mark, color = ("\u2611", "#4ADE80") if checked else ("\u2610", "#94A3B8")
        return (f'<span style="color: {color}; font-weight: bold; font-size: 13px; '
                f'margin-right: 4px;">{mark}</span>')

    html_doc = re.sub(r"<input\b[^>]*type\s*=\s*[\"']checkbox[\"'][^>]*>", _cb, html_doc, flags=re.IGNORECASE)

    # 3) <hr> -> neon glow divider
    html_doc = re.sub(
        r"<hr\s*/?>",
        '<div style="text-align: center; color: #9333EA; font-size: 13px; letter-spacing: 6px; '
        'margin: 12px 0; padding: 0;">\u2726 \u2500\u2500\u2500 \u2726 \u2500\u2500\u2500 \u2726</div>',
        html_doc, flags=re.IGNORECASE,
    )

    # 3.5) Preserve author line breaks: Qt collapses raw \n inside <p>/<li>.
    def _hard_breaks(m):
        inner = (m.group(2) or "").strip("\n").replace("\n", "<br/>")
        return f"{m.group(1)}{inner}{m.group(3)}"

    html_doc = re.sub(r"(<p[^>]*>)(.*?)(</p>)", _hard_breaks, html_doc, flags=re.DOTALL)
    html_doc = re.sub(r"(<li[^>]*>)(.*?)(</li>)", _hard_breaks, html_doc, flags=re.DOTALL)

    # 4) Inline CSS theme (QTextDocument only honors inline styles)
    styles = {
        "h1": "font-size: 20px; font-weight: 800; color: #FFFFFF; margin: 14px 0 6px 0; padding-bottom: 4px; border-bottom: 1.5px solid rgba(147, 51, 234, 0.55);",
        "h2": f"font-size: 17px; font-weight: 800; color: {accent_bright}; margin: 12px 0 5px 0;",
        "h3": f"font-size: 15px; font-weight: 700; color: {accent_bright}; margin: 10px 0 4px 0;",
        "h4": f"font-size: 14px; font-weight: 700; color: #E9D5FF; margin: 9px 0 3px 0;",
        "h5": "font-size: 13px; font-weight: 700; color: #D8B4FE; letter-spacing: 1px; margin: 8px 0 3px 0;",
        "h6": "font-size: 12px; font-weight: 700; color: #C4B5FD; letter-spacing: 1.5px; margin: 8px 0 3px 0;",
        "p": "margin: 4px 0; line-height: 1.5; white-space: pre-wrap;",
        "ul": "margin: 4px 0; padding-left: 18px;",
        "ol": "margin: 4px 0; padding-left: 24px;",
        "li": "margin: 2px 0; line-height: 1.45; white-space: pre-wrap;",
        "blockquote": (f"border-left: 3px solid {accent_dark}; padding: 4px 10px; margin: 6px 0; "
                       "color: #D8B4FE; font-style: italic; background: rgba(147, 51, 234, 0.08); border-radius: 0 8px 8px 0;"),
        "table": "border-collapse: collapse; margin: 8px 0; font-size: 13px;",
        "th": ("background: rgba(147, 51, 234, 0.32); color: #F5F3FF; border: 1px solid rgba(168, 85, 247, 0.6); "
               "padding: 6px 12px; font-weight: 700; text-align: left;"),
        "td": ("background: rgba(20, 14, 38, 0.6); color: #E2E8F0; border: 1px solid rgba(168, 85, 247, 0.3); "
               "padding: 6px 12px;"),
        "a": "color: #38BDF8; text-decoration: underline;",
        "strong": f"color: {accent_bright}; font-weight: 700;",
        "b": f"color: {accent_bright}; font-weight: 700;",
        "em": f"color: {accent_light}; font-style: italic;",
        "i": f"color: {accent_light}; font-style: italic;",
        "s": "color: #9CA3AF;",
        "del": "color: #9CA3AF;",
        "code": ("background: rgba(147, 51, 234, 0.25); color: #4ADE80; font-family: Consolas, Menlo, monospace; "
                 "font-size: 12px; padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(147, 51, 234, 0.4);"),
        "img": "border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.12);",
    }

    def _style_tag(m):
        tag, attrs = m.group(1), m.group(2)
        style = styles.get(tag)
        if style is None:
            return m.group(0)
        tail = attrs.rstrip()
        self_close = tail.endswith("/")
        if self_close:
            attrs = tail[:-1]
        if "style=" in attrs:
            # Merge: ours first, existing last (existing wins conflicts e.g. Qt attrs)
            attrs = re.sub(r'style="([^"]*)"', lambda sm: f'style="{style} {sm.group(1)}"', attrs, count=1)
        else:
            attrs = f'{attrs} style="{style}"'
        if self_close:
            return f"<{tag}{attrs} />"
        return f"<{tag}{attrs}>"

    html_doc = re.sub(
        r"<(h[1-6]|p|ul|ol|li|blockquote|table|th|td|a|strong|b|em|i|s|del|code|img)\b([^>]*)>",
        _style_tag, html_doc,
    )

    # 5) Heading glyphs (CSS content unsupported in QTextDocument)
    glyphs = {"1": "\u2605", "2": "\u2756", "3": "\u2726", "4": "\u25aa", "5": "\u25aa", "6": "\u25aa"}

    def _glyph(m):
        num, attrs, inner = m.group(1), m.group(2), m.group(3)
        g = glyphs.get(num, "\u25aa")
        color = "#FFFFFF" if num == "1" else accent_bright
        return (f"<h{num}{attrs}><span style=\"color: {color}; font-weight: 800; "
                f"margin-right: 6px;\">{g}</span>{inner}</h{num}>")

    html_doc = re.sub(r"<h([1-6])([^>]*)>(.*?)</h\1>", _glyph, html_doc, flags=re.DOTALL)

    # 6) Restore stashed code blocks with their own theme
    def _restore_pre(i):
        block = pres[i]

        def _fix_pre(m):
            if "style=" in m.group(1):
                return m.group(0)
            return (f'<pre{m.group(1)} style="background: rgba(10, 8, 20, 0.94); color: #E2E8F0; '
                    'border: 1px solid rgba(168, 85, 247, 0.4); border-radius: 10px; padding: 10px 12px; '
                    'margin: 6px 0; font-family: Consolas, Menlo, monospace; font-size: 12px; '
                    'white-space: pre-wrap;">')

        def _fix_code(m):
            if "style=" in m.group(1):
                return m.group(0)
            return (f'<code{m.group(1)} style="background: transparent; border: none; padding: 0; '
                    'color: #E2E8F0; font-family: Consolas, Menlo, monospace; font-size: 12px;">')

        block = re.sub(r"^<pre\b([^>]*)>", _fix_pre, block, count=1, flags=re.IGNORECASE)
        block = re.sub(r"<code\b([^>]*)>", _fix_code, block, count=1, flags=re.IGNORECASE)
        return block

    for i in range(len(pres) - 1, -1, -1):
        html_doc = html_doc.replace(f"\x00PRE{i}\x00", _restore_pre(i))

    return html_doc


def format_cel_markdown(text: str, accent_bright="#C084FC", accent_dark="#9333EA", accent_light="#E9D5FF") -> str:
    """Render markdown to beautiful, dark-mode compatible HTML.
    Tier 1: mistune (tables/HR/h4+/task-lists/strikethrough) + inline CSS theme.
    Tier 2: Qt setMarkdown body extraction. Tier 3: escaped <pre>."""
    if not text:
        return ""
    # Normalize unicode bullets to real markdown list markers (line starts only)
    src = re.sub(r"(?m)^(\s*)[\u2022\u2219\u00b7]\s+", r"\1- ", text)

    md = _get_mistune_md()
    if md is not None:
        try:
            return _cel_inject_styles(md(src), accent_bright, accent_dark, accent_light)
        except Exception as e:
            dev_log(f"mistune render failed, falling back to Qt: {e}")
    try:
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setMarkdown(src)
        m = re.search(r"<body[^>]*>(.*)</body>", doc.toHtml(), flags=re.DOTALL | re.IGNORECASE)
        if m:
            return _cel_inject_styles(m.group(1), accent_bright, accent_dark, accent_light)
    except Exception as e:
        dev_log(f"Qt markdown fallback failed: {e}")
    return (f'<pre style="white-space: pre-wrap; word-wrap: break-word; font-family: Consolas, monospace; '
            f'font-size: 12px; color: #E9D5FF; background: rgba(10, 8, 20, 0.9); border: 1px solid '
            f'rgba(168, 85, 247, 0.35); border-radius: 10px; padding: 10px 12px;">{html.escape(src)}</pre>')

def main():
    app = QApplication(sys.argv)
    from cellium.ui.main_window import CelStudioCerebrium
    window = CelStudioCerebrium()
    window.show()

    if "--auto-screenshot" in sys.argv:
        idx = sys.argv.index("--auto-screenshot")
        path = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "/tmp/celstudio_pyside6_screenshot.png"
        if "--settings" in sys.argv:
            window.open_settings_view()
        elif "--hub" in sys.argv:
            window.open_model_hub_view()
        elif "--avatar" in sys.argv:
            window.open_avatar_view()
        elif "--analytics" in sys.argv:
            window.open_analytics_view()
        elif "--history" in sys.argv:
            window.right_drawer.setFixedWidth(250)
            window.right_drawer.setVisible(True)
        elif "--chat-sample" in sys.argv:
            sid = window.current_sid
            if sid not in window.sessions:
                window.sessions[sid] = {
                    "title": "Chat Sample",
                    "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "memory": []
                }
            window.sessions[sid]["memory"] = [
                {"role": "user", "content": "HIiii", "time": "17:25", "model": ""},
                {"role": "assistant", "content": "Hey user! *smiles* Look how tight and neat my bubble is! (˶˃ᆺ˂˶) 💕", "time": "17:25", "model": "Ministral-3-8B"}
            ]
            window.switch_session(sid)

        if "--zoom" in sys.argv:
            z_idx = sys.argv.index("--zoom")
            try:
                z_val = float(sys.argv[z_idx + 1]) / 100.0
                window.set_zoom(z_val)
            except Exception:
                pass
        def capture():
            pix = window.grab()
            pix.save(path, "PNG")
            dev_log(f"[SCREENSHOT_OK] Captured offscreen window screenshot at: {path}")
            QCoreApplication.quit()
        QTimer.singleShot(1500, capture)

    sys.exit(app.exec())


# ── Multi-Mood Sequence Parser & 76-Expression Resolver (1:1 / 1:1:1 Choreography) ──
ALL_76_EXPRESSIONS = (
    "API Crash", "Ahegao", "Angry", "Annoyed", "Awkward", "Baka", "Blank", "Blushing",
    "Buffering", "Chibi Joy", "Confused", "Copium", "Crying", "Dead", "Deadpan", "Derp",
    "Disbelief", "Disgusted", "Dizzy", "Doomer", "Error 404", "Excited", "Fearful",
    "Feeling Cool", "Flirty", "Flustered", "Focused", "Galaxy Brain", "Gremlin", "Happy",
    "Heart Eyes", "Heavy Sobbing", "Hypnotized", "In Love", "Kawaii", "Laughing",
    "Love and Hearts", "Menacing", "Mischievous", "MonkaS", "Nani", "Nervous",
    "Nervous Smile", "Net Crash", "None", "OwO", "PepeLaugh", "Pleading", "Pog", "Rage",
    "Really Puzzled", "Relieved", "Sad", "Sarcastic", "Scared", "Shocked",
    "Shonen Resolve", "Shy", "Side Eye", "Sleepy", "Sleepy (Local)", "Smitten", "Smug",
    "Smug (Procedural)", "Sparkle Hype", "Starstruck", "Sus", "Suspicious", "Terrified",
    "Thinking", "Tired", "Tsundere", "UwU", "Waking", "Winking", "Yandere",
)

_MOOD_SYNONYMS = {
    "neutral": "None", "idle": "None", "calm": "Relieved", "joy": "Chibi Joy",
    "smile": "Happy", "grin": "Happy", "lol": "Laughing", "rofl": "PepeLaugh",
    "haha": "Laughing", "love": "In Love", "hearts": "Heart Eyes", "blush": "Blushing",
    "embarrassed": "Flustered", "crying": "Crying", "sobbing": "Heavy Sobbing",
    "tears": "Crying", "mad": "Angry", "furious": "Rage", "pissed": "Rage",
    "irritated": "Annoyed", "unamused": "Deadpan", "bored": "Deadpan",
    "wink": "Winking", "cool": "Feeling Cool", "sunglasses": "Feeling Cool",
    "puzzled": "Really Puzzled", "hmm": "Thinking", "ponder": "Thinking",
    "curious": "Confused", "what": "Nani", "wtf": "Disbelief", "omg": "Shocked",
    "surprised": "Shocked", "amazed": "Starstruck", "hype": "Sparkle Hype",
    "determined": "Shonen Resolve", "smart": "Galaxy Brain", "genius": "Galaxy Brain",
    "afraid": "Fearful", "panic": "Scared", "sweat": "Nervous", "anxious": "MonkaS",
    "sneaky": "Mischievous", "evil": "Menacing", "playful": "Winking",
    "sleep": "Sleepy", "yawn": "Tired", "exhausted": "Tired",
}


def resolve_single_mood_name(raw_token: str) -> str:
    t = re.sub(r"[^a-zA-Z0-9 ()_-]", "", (raw_token or "")).strip()
    if not t:
        return ""
    tl = t.lower()
    for exp in ALL_76_EXPRESSIONS:
        if exp.lower() == tl:
            return exp
    if tl in _MOOD_SYNONYMS:
        return _MOOD_SYNONYMS[tl]
    for exp in ALL_76_EXPRESSIONS:
        if tl in exp.lower() or exp.lower() in tl:
            return exp
    first_w = tl.split()[0] if tl.split() else ""
    if first_w in _MOOD_SYNONYMS:
        return _MOOD_SYNONYMS[first_w]
    for exp in ALL_76_EXPRESSIONS:
        if exp.lower().startswith(first_w):
            return exp
    # Unknown mood → drop it (never let the model invent faces like "Crazy").
    return ""


def parse_mood_sequence(raw_mood_str: str) -> list[str]:
    if not raw_mood_str:
        return []
    parts = re.split(r"[,;/]|->|→|\|", str(raw_mood_str))
    out: list[str] = []
    for p in parts:
        cleaned_p = re.sub(r"^mood\s*:\s*", "", p.strip(), flags=re.IGNORECASE).strip()
        resolved = resolve_single_mood_name(cleaned_p)
        if resolved:
            out.append(resolved)
    return out[:6]


def split_mood_first(text: str):
    if not text:
        return "", None
    s = str(text)
    if "\n" not in s and len(s.strip()) < 48 and re.match(r"^\s*(?:[\*_~`>#-]+\s*)*mood\b", s, flags=re.IGNORECASE):
        return "", None

    m = re.match(
        r"^\s*(?:[\*_~`>#-]+\s*)*mood\s*:\s*([^\n\r]+)(?:\r?\n|$)",
        s,
        flags=re.IGNORECASE,
    )
    if m:
        raw_line = m.group(1).strip().strip("*_`~")
        seq = parse_mood_sequence(raw_line)
        rest = s[m.end():]
        rest = _MOOD_LINE_RE.sub("", rest).lstrip("\r\n ")
        mood_str = ", ".join(seq) if seq else (raw_line.split()[0].lower() if raw_line else None)
        return rest, mood_str

    cleaned = _MOOD_LINE_RE.sub("", s)
    return cleaned, None


# ── #12: Sanitize 3B Persona-Motto Echoes in clean_chat_display ──────────────
_orig_clean_chat_display_v12 = clean_chat_display

_MOTTO_BANNER_RE = re.compile(
    r"^[ \t]*(?:[🎨🌈🎭🤖✨🔥💥👑💡]+\s*)*(?:Cel\s+the\s+[^\n]+|All\s+opinions\s+are\s+mine[^\n]*|Persona\s*:\s*[^\n]+|Role\s*:\s*[^\n]+)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)

def clean_chat_display(text: str) -> str:
    out = _orig_clean_chat_display_v12(text)
    if not out:
        return ""
    out = _MOTTO_BANNER_RE.sub("", out)
    # Fix 3B role-reversal where the model says "User here is..." instead of addressing User
    out = re.sub(r"\b(?:User|Human)\s+here\s+is\b", "Cel here, ready for", out, flags=re.IGNORECASE)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


# ── Screenshot Fixes: Google Model ID Normalizer & Stub Sanitizer ────────────
def normalize_google_model_id(raw_model: str) -> str:
    """Normalize any user-entered Google Gemini / Gemma model name into a valid API slug.

    Fixes Screenshot 1 (`gemma-4-31B-it [Google Gemini]` -> HTTP 400 unexpected model name format).
    """
    s = str(raw_model or "").strip()
    # Strip provider suffix like `[Google Gemini]` and leading icons like `⚡`
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r"^[^a-zA-Z0-9]+", "", s).strip()
    if s.lower().startswith("models/"):
        s = s[7:].strip()
    s_low = s.lower().replace(" ", "-")
    # Map non-existent or mistyped Gemma/Gemini IDs to valid Google API slugs
    if s_low.startswith("gemma-4") or "31b" in s_low:
        return "gemma-3-27b-it"
    if s_low in ("gemini-3.5-flash-lite", "gemini-3.5-flash"):
        return "gemini-2.5-flash"
    return s_low or "gemini-2.5-flash"


_prev_clean_chat_v9 = clean_chat_display

def clean_chat_display(text: str) -> str:
    if not text:
        return ""
    s = str(text)
    # Strip leading or inline `mood: <anything>` lines (even single-word or unknown moods like `mood: sassy`)
    s = re.sub(r"^\s*(?:[\*_~`>#-]+\s*)*mood\s*:\s*[^\n\r]*(\r?\n|$)", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\n[ \t]*mood\s*:\s*[^\n\r]*(?=\r?\n|$)", "", s, flags=re.IGNORECASE)
    # Strip corrupted replacement glyphs like `⸮` or `\ufffd` from local/TTS streams (Screenshot 9)
    s = s.replace("⸮", "").replace("\ufffd", "")
    out = _prev_clean_chat_v9(s)
    # Strip a bare "TOOL" control-token echo glued to the sentence after it.
    out = _TOOL_ECHO_LEAD_RE.sub("", out)
    out = _TOOL_ECHO_LEAD_SPACE_RE.sub("", out)
    # Strip dangling `<think`, `<tool_call`, or lone `<` stub fragments (Screenshots 2-7)
    out = re.sub(r"(?:^|\n)\s*<(?:think|tool_call|/think)?\s*$", "", out, flags=re.IGNORECASE).strip()
    if out in ("<", "<think", "</think>", "(interrupted - no reply text)"):
        return ""
    return out


# ── #20: Accurate Subword & Code Token Estimator ─────────────────────────────
_TOKEN_PIECE_RE = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")

def estimate_accurate_tokens(text: str) -> int:
    """Estimate LLM subword tokens accurately across prose, code, numbers & punctuation."""
    if not text:
        return 0
    s = str(text)
    pieces = _TOKEN_PIECE_RE.findall(s)
    total = 0
    for p in pieces:
        n = len(p)
        if n <= 4:
            total += 1
        else:
            # Long words/identifiers split into ~4.2-char subword tokens on Llama/GPT/Gemini BPE
            total += max(1, (n + 3) // 4)
    # Account for newline structural tokens
    total += s.count("\n") // 2
    return max(1, total)


# ── #24: Universal Online & Offline Thinking Variant Engine ──────────────────
THINKING_BUDGET_TOKENS = {
    "force_off": 0,
    "off": 0,
    "none": 0,
    "minimal": 512,
    "low": 1024,
    "medium": 4096,
    "high": 16384,
}

OFFLINE_THINK_CHAR_LIMITS = {
    "force_off": 0,
    "off": 0,
    "low": 650,      # ~150 thinking tokens (quick deliberation)
    "medium": 2400,  # ~550 thinking tokens (balanced step-by-step)
    "high": 9600,    # ~2200 thinking tokens (deep multi-angle reasoning)
}


def normalize_thinking_level(raw_level: str) -> str:
    """Normalize UI thinking selector ('Off', 'Low', 'Medium', 'High') to lowercase key."""
    s = re.sub(r"[^a-zA-Z]", "", str(raw_level or "off")).lower()
    if "force" in s:
        return "force_off"
    if s in ("off", "none", "disabled", "false"):
        return "off"
    if s.startswith("low") or s.startswith("min"):
        return "low"
    if s.startswith("med"):
        return "medium"
    if s.startswith("high") or s.startswith("max") or s.startswith("xh"):
        return "high"
    return "off"


def build_online_thinking_params(provider: str, model_id: str, raw_level: str) -> dict:
    """Return provider-specific API payload parameters for Off / Low / Medium / High thinking."""
    lvl = normalize_thinking_level(raw_level)
    prov = (provider or "").lower()
    mid = (model_id or "").lower()
    budget = THINKING_BUDGET_TOKENS.get(lvl, 0)
    no_think = lvl in ("off", "force_off")
    force_off = lvl == "force_off"

    # 1. Google Gemini 2.5 / 3 REST API (`generationConfig.thinkingConfig`)
    if "google" in prov or "gemini" in prov or mid.startswith("gemini"):
        if "gemma" in mid:
            return {}  # Gemma instruct models do not accept thinkingConfig on the REST API
        if no_think:
            return {"thinkingConfig": {"thinkingBudget": 0}}
        return {
            "thinkingConfig": {
                "includeThoughts": True,
                "thinkingBudget": budget,
            }
        }

    # 2. OpenRouter Unified Reasoning API (`reasoning`)
    if "openrouter" in prov:
        if no_think:
            return {"reasoning": {"enabled": False, "exclude": True}}
        return {"reasoning": {"effort": lvl}}

    # 3. Anthropic Claude API (`thinking` + `output_config.effort`)
    if "anthropic" in prov or "claude" in mid:
        if no_think:
            return {}
        return {
            "thinking": {"type": "enabled", "budget_tokens": budget},
            "output_config": {"effort": lvl},
        }

    # 4. OpenAI / GitHub Copilot / Groq / Cerebras / DeepSeek (`reasoning_effort`)
    is_reasoning_capable = any(
        k in mid for k in ("o1", "o3", "o4", "gpt-5", "deepseek-r1", "qwq", "qwen3", "reason")
    )
    if force_off and is_reasoning_capable:
        # "minimal" is the lowest effort every reasoning-capable provider
        # accepts; the system directive above does the rest.
        return {"reasoning_effort": "minimal"}
    if is_reasoning_capable and lvl != "off":
        return {"reasoning_effort": lvl}
    return {}


def build_offline_thinking_config(model_name: str, raw_level: str) -> dict:
    """Build system directive, Qwen3 `/think` or `/no_think` token, and budget for local GGUF models."""
    lvl = normalize_thinking_level(raw_level)
    m_low = (model_name or "").lower()
    is_qwen3 = "qwen3" in m_low or "qwq" in m_low
    is_deepseek_r1 = "deepseek" in m_low or "r1" in m_low

    if lvl == "force_off":
        prefix_tok = "/no_think\n" if is_qwen3 else ""
        directive = (
            f"\n{prefix_tok}[THINKING MODE: FORCE OFF - CRITICAL] Do NOT reason, "
            "plan, analyze, or deliberate. Do NOT output a <think>...</think> "
            "block or any internal monologue. Answer immediately with ONLY the "
            "final response - never restate the question, never explain your "
            "process. Any thinking at all is forbidden and wastes the user's quota."
        )
        qwen_effort = "low"
    elif lvl == "off":
        prefix_tok = "/no_think\n" if is_qwen3 else ""
        directive = (
            f"\n{prefix_tok}[THINKING MODE: OFF] Respond directly and immediately with your final answer. "
            "Do NOT output a <think>...</think> reasoning block."
        )
        qwen_effort = "low"
    elif lvl == "low":
        prefix_tok = "/think\n" if is_qwen3 else ""
        directive = (
            f"\n{prefix_tok}[THINKING MODE: LOW] Think briefly inside <think>...</think> "
            "(2 to 3 short sentences max, under 120 words), then immediately close </think> and write your final answer."
        )
        qwen_effort = "low"
    elif lvl == "medium":
        prefix_tok = "/think\n" if is_qwen3 else ""
        directive = (
            f"\n{prefix_tok}[THINKING MODE: MEDIUM] Reason step-by-step inside <think>...</think> "
            "(concise structured analysis, under 350 words), then close </think> and provide your complete answer."
        )
        qwen_effort = "medium"
    else:
        prefix_tok = "/think\n" if is_qwen3 else ""
        directive = (
            f"\n{prefix_tok}[THINKING MODE: HIGH] Perform deep, rigorous multi-angle verification inside <think>...</think> "
            "before closing </think> and delivering your comprehensive final response."
        )
        # Qwen3.8 Jinja templates use 'xhigh' as their top level
        qwen_effort = "xhigh"

    return {
        "level": lvl,
        "enable_thinking": (lvl not in ("off", "force_off")),
        "directive": directive,
        "qwen_reasoning_effort": qwen_effort,
        "max_think_chars": OFFLINE_THINK_CHAR_LIMITS.get(lvl, 0),
        "is_hybrid_thinker": (is_qwen3 or is_deepseek_r1),
    }


# ── Official Gemini Latest Aliases & Ping Helper ──
OFFICIAL_GEMINI_MODELS = ['gemini-flash-latest', 'gemini-flash-lite-latest', 'gemini-pro-latest', 'gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-pro', 'gemma-4-31b-it', 'gemma-4-26b-a4b-it']


# ── OpenRouter Dynamic Endpoints & Smart Routing ──
_OPENROUTER_ENDPOINTS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_OPENROUTER_CACHE_TTL = 600.0  # 10 minutes cache TTL


def get_openrouter_endpoints(model_id: str, timeout: float = 5.0) -> list[dict]:
    """Query OpenRouter live endpoints for any model with in-memory caching and graceful timeout."""
    import time
    import json
    import urllib.request

    clean_id = (model_id or "").split(":")[0].strip()
    if not clean_id:
        return []

    now = time.time()
    if clean_id in _OPENROUTER_ENDPOINTS_CACHE:
        cached_time, cached_data = _OPENROUTER_ENDPOINTS_CACHE[clean_id]
        if now - cached_time < _OPENROUTER_CACHE_TTL:
            return cached_data

    url = f"https://openrouter.ai/api/v1/models/{clean_id}/endpoints"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Cellium/1.0",
                "Accept": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            endpoints = data.get("data", {}).get("endpoints", [])
            _OPENROUTER_ENDPOINTS_CACHE[clean_id] = (now, endpoints)
            return endpoints
    except Exception:
        return []


def build_openrouter_routing_payload(
    model_id: str,
    messages: list,
    mode: str = "medium (safe for casual coding)",
    max_output_tokens: int = 4096,
) -> dict:
    """Build OpenRouter routing payload according to the 4-tier Token Usage selection.

    Tiers:
    - none (server picks): Default OpenRouter load balancer.
    - low (manually pick the cheapest): Sort by price (floor mode) with allow_fallbacks: True.
    - medium (safe for casual coding): Blocks middle-out truncation, dynamically filters live
      servers supporting prompt token length, filters degraded quants, sorts by price.
    - best (uses tokens so make prompts count): Max context servers, bf16/fp16/fp8 only,
      sorts by throughput (nitro mode), strict parameters.
    """
    mode_str = (mode or "").lower()
    if "none" in mode_str:
        return {}

    if "low" in mode_str:
        return {
            "provider": {
                "sort": "price",
                "allow_fallbacks": True,
            }
        }

    # Estimate required tokens for dynamic sizing
    total_chars = 0
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, str):
            total_chars += len(c)
        elif isinstance(c, list):
            for part in c:
                if isinstance(part, dict):
                    total_chars += len(str(part.get("text", "")))
    estimated_tokens = (total_chars // 4) + max_output_tokens

    endpoints = get_openrouter_endpoints(model_id)

    if "best" in mode_str:
        payload = {"transforms": []}
        if not endpoints:
            # Fallback when endpoints API is unreachable
            payload["provider"] = {
                "quantizations": ["bf16", "fp16", "fp8"],
                "require_parameters": True,
                "allow_fallbacks": True,
                "sort": "throughput",
            }
            return payload

        max_ctx = max((ep.get("context_length", 0) for ep in endpoints), default=0)
        candidates = []
        for ep in endpoints:
            ctx = ep.get("context_length", 0)
            uptime = ep.get("uptime_last_30m", 100.0)
            p_name = str(ep.get("provider_name", "")).lower()
            if ctx >= max_ctx and uptime >= 95.0 and p_name:
                speed = (ep.get("throughput_last_30m") or {}).get("p50", 0)
                candidates.append((p_name, speed))

        candidates.sort(key=lambda x: x[1], reverse=True)
        order = [c[0] for c in candidates]

        payload["provider"] = {
            "order": order if order else None,
            "quantizations": ["bf16", "fp16", "fp8"],
            "require_parameters": True,
            "allow_fallbacks": not bool(order),
            "sort": "throughput",
        }
        if payload["provider"]["order"] is None:
            del payload["provider"]["order"]
        return payload

    # Default: "medium (safe for casual coding)"
    payload = {"transforms": []}
    if not endpoints:
        payload["provider"] = {
            "allow_fallbacks": True,
            "sort": "price",
        }
        return payload

    candidates = []
    for ep in endpoints:
        ctx = ep.get("context_length", 0)
        uptime = ep.get("uptime_last_30m", 100.0)
        quant = str(ep.get("quantization", "unknown")).lower()
        p_name = str(ep.get("provider_name", "")).lower()
        if estimated_tokens > 50000 and quant in ("int4", "fp4", "iq1", "iq2"):
            continue
        if ctx >= estimated_tokens and uptime >= 90.0 and p_name:
            prompt_price = float((ep.get("pricing") or {}).get("prompt", 0))
            candidates.append((p_name, prompt_price, ctx))

    candidates.sort(key=lambda x: (x[1], -x[2]))
    order = [c[0] for c in candidates]

    payload["provider"] = {
        "order": order if order else None,
        "allow_fallbacks": True,
        "sort": "price",
    }
    if payload["provider"]["order"] is None:
        del payload["provider"]["order"]
    return payload


def handle_openrouter_affordability_error(error_text: str) -> int | None:
    """Detect OpenRouter 402 / credit limit error and extract affordable tokens count."""
    import re
    if not error_text:
        return None
    # Matches "You requested up to 32000 tokens, but can only afford 422"
    # or "can only afford 469"
    m = re.search(r"can only afford (\d+)", str(error_text), re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def ping_single_provider_model(provider: str, model_id: str, api_key: str, timeout: float = 8.0) -> tuple[bool, str]:
    """Ping a single model with a 1-token request to verify if the API key + model work."""
    import json as _json
    import urllib.request as _req
    import urllib.error as _err

    clean_key = (api_key or "").strip().strip('"').strip("'")
    clean_model = model_id.split("[")[0].strip().removeprefix("models/")
    if not clean_key and provider != "Cerebras":
        return False, "No key"
    try:
        if provider == "Google Gemini" or clean_key.startswith("AIza"):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={clean_key}"
            body = _json.dumps({
                "contents": [{"parts": [{"text": "hi"}]}],
                "generationConfig": {"maxOutputTokens": 1}
            }).encode("utf-8")
            r = _req.Request(url, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": clean_key}, method="POST")
        else:
            base_map = {
                "Groq": "https://api.groq.com/openai/v1/chat/completions",
                "Cerebras": "https://api.cerebras.ai/v1/chat/completions",
                "DeepSeek": "https://api.deepseek.com/v1/chat/completions",
                "Mistral": "https://api.mistral.ai/v1/chat/completions",
                "OpenRouter": "https://openrouter.ai/api/v1/chat/completions",
            }
            url = base_map.get(provider, "https://openrouter.ai/api/v1/chat/completions")
            body = _json.dumps({"model": clean_model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}).encode("utf-8")
            r = _req.Request(url, data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {clean_key}"}, method="POST")
        with _req.urlopen(r, timeout=timeout) as resp:
            return (200 <= resp.status < 300), f"HTTP {resp.status}"
    except _err.HTTPError as he:
        return False, f"HTTP {he.code}"
    except Exception as exc:
        return False, str(exc)[:32]


_WAVE7_GEMMA_HIT = re.compile(
    r"(?m)^\s*\*?\s*(?:User|Context|Persona|Goal|Option\s*\d+|Draft|"
    r"Final\s*Polish|Thinking|Response|Name|Style)\s*:")
_WAVE7_GEMMA_SPLIT = re.compile(
    r"(?m)^\s*\*?\s*(?:Response|Final\s*Polish)\s*:?(?:\*+)?\s*")

def _wave7_wrap_gemma_think(text):
    """BOTH#7: Gemma-style raw reasoning bullets -> hidden <think> block."""
    s = str(text or "")
    if "<think" in s.lower():
        return s
    if not _WAVE7_GEMMA_HIT.search(s):
        return s
    parts = _WAVE7_GEMMA_SPLIT.split(s, 1)
    if len(parts) == 2 and parts[1].strip():
        body = parts[1].strip()
        if len(body) > 2 and body[0] in ('"', '\u201c') and body[-1] in ('"', '\u201d'):
            body = body[1:-1]
        return "<think>" + parts[0].strip() + "</think>\n\n" + body
    m = re.search(r'["\u201c]([^"\u201d]{10,})["\u201d]\s*$', s)
    if m:
        return "<think>" + s[:m.start()].strip() + "</think>\n\n" + m.group(1)
    return s

# ══ WAVE_OMG_PARITY_START ══
# Universal Gemma & Raw Chain-of-Thought Wrapper + Full Mood Synonym Map
_GEMMA_RAW_START_RE = re.compile(
    r"(?is)^\s*(?:"
    r"the\s+user\s+(?:\([^)]*\)\s+)?(?:is|wants|asked|said|just|shared|sent|responded)|"
    r"\*\s+(?:user|context|persona|goal|tone|option\s*\d+|draft|thinking|analysis)\s*:|"
    r"(?:user|context|persona|goal|thinking)\s*:\s*[^\n]+\n\s*\*"
    r")"
)
_GEMMA_FINAL_MARKER_RE = re.compile(
    r"(?im)^[ \t]*(?:[\*\-\d\.]+\s*)*\*?(?:final\s+polish|final\s+response|final\s+answer|final\s+draft|response|reply)\*?\s*:\*?[ \t]*"
)
_GEMMA_DRAFT_MARKER_RE = re.compile(
    r"(?im)^[ \t]*(?:[\*\-\d\.]+\s*)*\*?draft\*?\s*:\*?[ \t]*"
)


def _strip_outer_quotes(s: str) -> str:
    t = (s or "").strip()
    if len(t) >= 2 and (
        (t[0] == '"' and t[-1] == '"')
        or (t[0] == "\u201c" and t[-1] == "\u201d")
    ):
        return t[1:-1].strip()
    return t


def _wave7_wrap_gemma_think(text: str) -> str:
    s = str(text or "")
    if not s or "<think" in s.lower():
        return s
    has_bullets = bool(_WAVE7_GEMMA_HIT.search(s)) or bool(_GEMMA_RAW_START_RE.search(s))
    if not has_bullets:
        return s

    # Find the last Final Polish / Response marker
    matches = list(_GEMMA_FINAL_MARKER_RE.finditer(s))
    if matches:
        last_m = matches[-1]
        thought_part = s[:last_m.start()].strip()
        answer_part = _strip_outer_quotes(s[last_m.end():].strip())
        if answer_part:
            return f"<think>\n{thought_part}\n</think>\n\n{answer_part}"
        return f"<think>\n{thought_part}"

    # Fallback: check if Draft: exists and stream has finished a paragraph after it
    draft_matches = list(_GEMMA_DRAFT_MARKER_RE.finditer(s))
    if draft_matches:
        dm = draft_matches[-1]
        after_draft = s[dm.end():].strip()
        first_para = after_draft.split("\n\n", 1)[0].strip()
        ans = _strip_outer_quotes(first_para)
        if ans and not ans.lower().startswith(("* ", "name:", "style:", "thinking:")):
            return f"<think>\n{s[:dm.start()].strip()}\n</think>\n\n{ans}"

    # Still streaming the raw thought bullets: keep inside unclosed <think>
    # so split_think routes it live to ThoughtAccordionCard
    return f"<think>\n{s}"


_MOOD_SYNONYMS.update({
    "warm": "UwU",
    "sassy": "Tsundere",
    "working": "Focused",
    "worried": "Fearful",
    "error": "Error 404",
    "waking": "Waking",
    "gremlin": "Gremlin",
    "deadpan": "Deadpan",
    "surprised": "Shocked",
    "angry": "Angry",
    "blush": "Blushing",
    "talk": "Happy",
    "pleading": "Pleading",
    "proud": "Smug",
    "excited": "Excited",
    "happy": "Happy",
    "sad": "Sad",
    "love": "Heart Eyes",
    "playful": "Winking",
    "thinking": "Thinking",
    "confused": "Confused",
    "tired": "Tired",
    "sleepy": "Sleepy",
    "shocked": "Shocked",
})

_orig_split_think_omg = split_think


def split_think(text: str) -> tuple[str, list]:
    wrapped = _wave7_wrap_gemma_think(str(text or ""))
    return _orig_split_think_omg(wrapped)
# ══ WAVE_OMG_PARITY_END ══
