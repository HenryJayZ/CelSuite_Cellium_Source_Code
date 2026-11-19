#!/usr/bin/env python3
"""
CelStudio Cerebrium - Native PySide6 Desktop Application
Liquid Glass UI, Neon Glow Saturation & Dynamic Color-Shifting Wallpaper Engine
100% LGPL PySide6 Standard | Central Venv | Strict Signals
Telegram-Style Glass Input | Inbuilt Emoji Picker | Multi-Engine STT | 100% Inbuilt Views
Animal Crossing / Mellodi Musical Cel Voice | Cozy Sound System | Zero Popups
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
import warnings
import numpy as np

warnings.filterwarnings(
    "ignore",
    message=r".*CUDAExecutionProvider.*",
    category=UserWarning,
)

# ============================================================
# GLOBAL REAL-TIME LOGGING SYSTEM - Immediate stdout/stderr flush
# ============================================================
_original_print = print

# --- CROSS IMPORTS ---
from cellium.core.logger import *

import importlib.util

# Fast non-blocking capability probes (find_spec takes <1ms instead of loading heavy C audio engines on boot)
HAS_SOUNDDEVICE = importlib.util.find_spec("sounddevice") is not None
HAS_SR = importlib.util.find_spec("speech_recognition") is not None

# ------------------------------------------------------------------ UI Sound System (pygame + QSoundEffect fallback)
# pygame mixer is heavy (~1.3 s at import). Initialise it LAZILY on first
# sound use so boot doesn't pay for it unless the user actually hears a sound.
HAS_PYGAME = None  # None = uninitialised, True/False = tried
#: Module-level pygame handle, set by :func:`_ensure_pygame_mixer`. Keeping it
#: here (instead of importing pygame locally and then referencing it as a
#: global) is what made every Cel voice note fail to load with a silent
#: NameError - and therefore made the Preview button play nothing.
pygame = None

HAS_QT_MULTIMEDIA = False
try:
    from PySide6.QtMultimedia import QSoundEffect
    from PySide6.QtCore import QUrl
    HAS_QT_MULTIMEDIA = True
except Exception:
    HAS_QT_MULTIMEDIA = False

#: Call this once at the first UI sound / voice chirp. Safe to call repeatedly.
def _ensure_pygame_mixer() -> bool:
    global HAS_PYGAME, pygame
    if HAS_PYGAME is not None:
        return HAS_PYGAME
    try:
        import pygame as _pygame
        pygame = _pygame
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=2048)
        pygame.mixer.init()
        pygame.mixer.set_num_channels(32)
        # Channels 0 and 1 belong to Cel's Realistic Voice: its scheduler
        # alternates between them so a new word never steals a UI click.
        try:
            pygame.mixer.set_reserved(2)
        except Exception:
            pass
        HAS_PYGAME = True
    except Exception:
        HAS_PYGAME = False
    return HAS_PYGAME

BASE_DIR = Path(__file__).resolve().parent
# Primary assets directory lives in cellium/assets (icons, svgs, and UI graphics)
ASSETS_DIR = BASE_DIR.parent / "assets" if (BASE_DIR.parent / "assets").exists() else BASE_DIR / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
SOUNDS_DIR = BASE_DIR.parent / "sounds" if (BASE_DIR.parent / "sounds").exists() else BASE_DIR / "sounds"
SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
# ─── Portable external-resource resolvers ────────────────────────────────────
# These used to be hardcoded to /home/user/..., which silently breaks on any
# other machine and on Nuitka builds (AGENTS.md: never hardcode /home/<user>/).
# Each one is overridable with an environment variable.
PROJECTS_DIR = Path(os.environ.get(
    "CELSTUDIO_PROJECTS_DIR",
    Path.home() / "Documents" / "Projects" / "Python",
))
# Kokoro model dir: env override first, then the directories that actually
# exist on this machine. The old default (PROJECTS_DIR/"Kokoro" =
# ~/Documents/Projects/Python/Kokoro) never existed here - the real files
# live one level up - so STT and TTS both died on a path written in stone.
_ENV_KOKORO = os.environ.get("KOKORO_MODELS_DIR", "").strip()


def _first_existing(paths, marker):
    """First directory that really holds ``marker`` (else the first path)."""
    for p in paths:
        try:
            if (p / marker).is_file():
                return p
        except OSError:
            continue
    return paths[0]


#: True when compiled via Nuitka (--standalone / --onefile) or PyInstaller.
IS_FROZEN = bool(
    "__compiled__" in globals()
    or getattr(sys, "frozen", False)
    or hasattr(sys, "_MEIPASS")
)
#: Directory containing the outer executable (for portable models/wallpapers).
APP_EXEC_DIR = Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else BASE_DIR


def _resolve_user_data_dir() -> Path:
    """Return BASE_DIR when running from source; OS user config dir when compiled with Nuitka.

    Nuitka `--onefile` unpacks `__file__` into `/tmp/onefile_<pid>_...` which is
    wiped on exit! Routing mutable JSON state to `~/.config/Cellium` (or
    `%APPDATA%/Cellium` on Windows) when frozen keeps friends' chats & keys safe.
    """
    if not IS_FROZEN:
        return BASE_DIR
    if sys.platform.startswith("win"):
        cfg_root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        cfg_root = Path.home() / "Library" / "Application Support"
    else:
        cfg_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = cfg_root / "Cellium"
    try:
        d.mkdir(parents=True, exist_ok=True)
        # Seed default presets on first launch if absent
        for seed_name in ("cerebrium_presets.json", "cerebrium_memory_presets.json"):
            src_seed = BASE_DIR / seed_name
            dst_seed = d / seed_name
            if src_seed.is_file() and not dst_seed.exists():
                shutil.copy2(src_seed, dst_seed)
    except OSError:
        return BASE_DIR
    return d


USER_DATA_DIR = _resolve_user_data_dir()


def resolve_python_executable() -> str:
    """Return a real Python interpreter for running user code snippets.

    Under Nuitka, `sys.executable` is the compiled GUI binary itself,
    so calling `[sys.executable, "-c", code]` would spawn a second GUI window!
    """
    if not IS_FROZEN:
        return sys.executable
    for cand in (
        VENV_DIR / "bin" / "python",
        VENV_DIR / "Scripts" / "python.exe",
        shutil.which("python3"),
        shutil.which("python"),
    ):
        if cand and Path(cand).is_file():
            return str(cand)
    return "python3"


KOKORO_DIR = (Path(_ENV_KOKORO) if _ENV_KOKORO else _first_existing(
    (APP_EXEC_DIR / "Kokoro",
     APP_EXEC_DIR / "models",
     BASE_DIR.parent / "models",
     Path.home() / ".local" / "share" / "cellium" / "Kokoro",
     PROJECTS_DIR / "Kokoro",
     Path.home() / "Documents" / "Projects" / "Kokoro"),
    "kokoro-v1.0.fp16.onnx"))
OFFICIAL_WALLPAPERS_DIR = Path(os.environ.get(
    "CELSTUDIO_WALLPAPER_DIR",
    PROJECTS_DIR / ".png",
))
VENV_DIR = Path(os.environ.get(
    "CELSTUDIO_VENV_DIR",
    PROJECTS_DIR / "venv",
))

# UI sound effects are bundled inside the package (AGENTS.md invariant 3).
# This constant used to be hardcoded to "/home/user/.../Cerebras AI" -- a
# folder that has since moved under Archived/, which silently broke all 10 UI
# sounds. The bundled copies are now authoritative; the old location is kept
# only as a fallback.
_SOUND_DIR_CANDIDATES = (
    SOUNDS_DIR,
    Path.home() / "Documents" / "Projects" / "Python" / "Archived" / "Cerebras AI",
)
LEGACY_DIR = next(
    (d for d in _SOUND_DIR_CANDIDATES if (d / "cerebrium_click.wav").exists()),
    SOUNDS_DIR,
)

# ── Profile pictures (you + Cel) ───────────────────────────────────────────
# The circular cutouts that sit beside your name (and Cel's) in every chat
# bubble header. Stored as square PNGs under USER_DATA_DIR so a Nuitka build
# keeps them next to chats/keys in %APPDATA%/Cellium instead of a temp dir
# (same rule as cerebrium_settings.json above).
AVATARS_DIR = USER_DATA_DIR / "avatars"
try:
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
USER_AVATAR_FILE = AVATARS_DIR / "user_avatar.png"
CEL_AVATAR_FILE = AVATARS_DIR / "cel_avatar.png"
#: Diameter of the cutout inside a chat bubble header (px at zoom 1.0).
AVATAR_DISPLAY_SIZE = 26

# Pentatonic scale frequencies for Animal Crossing musical voice (C Major Pentatonic: D4, E4, G4, A4, C5, D5, E5, G5, A5, C6, D6)
# Removed C4 (261.63 Hz) - too dark/low. Range now D4 (293.66) to D6 (1174.66)
ANIMALESE_FREQS = [293.66, 329.63, 392.00, 440.00, 523.25, 587.33, 659.25, 783.99, 880.00, 1046.50, 1174.66]

# 10 selectable Cel talk-style variants (Animal Crossing / Mellodi)
# Keys are stable settings values; "label" is what the Preferences combo shows.
CEL_VOICE_VARIANTS = {
    "Classic AC": {
        "label": "🍃 Classic AC",
        "freqs": [293.66, 329.63, 392.00, 440.00, 523.25, 587.33, 659.25, 783.99, 880.00, 1046.50, 1174.66],
        "prefix": "ac_note_",
        "sub": 0.08, "h2": 0.0, "h3": 0.0, "vib": 0.0, "vib_hz": 0.0,
        "attack": 80, "decay": 1100, "frames": 3200, "amplitude": 7500, "volume": 0.22,
    },
    "Mellodi": {
        "label": "✨ Mellodi",
        "freqs": [440.00, 493.88, 554.37, 659.25, 739.99, 880.00, 987.77, 1108.73, 1318.51, 1479.98, 1760.00],
        "prefix": "ac_v1_note_",
        "sub": 0.0, "h2": 0.25, "h3": 0.0, "vib": 0.0, "vib_hz": 0.0,
        "attack": 40, "decay": 700, "frames": 2800, "amplitude": 8000, "volume": 0.22,
    },
    "Cozy Villager": {
        "label": "🏡 Cozy Villager",
        "freqs": [196.00, 220.00, 246.94, 293.66, 329.63, 392.00, 440.00, 493.88, 587.33, 659.25, 783.99],
        "prefix": "ac_v2_note_",
        "sub": 0.15, "h2": 0.0, "h3": 0.05, "vib": 0.0, "vib_hz": 0.0,
        "attack": 120, "decay": 1600, "frames": 3600, "amplitude": 7000, "volume": 0.24,
    },
    "Hyper Kawaii": {
        "label": "💖 Hyper Kawaii",
        "freqs": [523.25, 587.33, 659.25, 783.99, 880.00, 1046.50, 1174.66, 1318.51, 1567.98, 1760.00, 2093.00],
        "prefix": "ac_v3_note_",
        "sub": 0.0, "h2": 0.30, "h3": 0.0, "vib": 0.0, "vib_hz": 0.0,
        "attack": 30, "decay": 500, "frames": 2200, "amplitude": 7000, "volume": 0.20,
    },
    "Starlight Lullaby": {
        "label": "🌙 Starlight Lullaby",
        "freqs": [440.00, 523.25, 587.33, 698.46, 783.99, 880.00, 1046.50, 1174.66, 1396.91, 1567.98, 1760.00],
        "prefix": "ac_v4_note_",
        "sub": 0.0, "h2": 0.0, "h3": 0.12, "vib": 0.4, "vib_hz": 5.5,
        "attack": 100, "decay": 1400, "frames": 3600, "amplitude": 6500, "volume": 0.20,
    },
    "Neon Bell": {
        "label": "🔔 Neon Bell",
        "freqs": [587.33, 659.25, 783.99, 880.00, 1046.50, 1174.66, 1318.51, 1567.98, 1760.00, 2093.00, 2349.32],
        "prefix": "ac_v5_note_",
        "sub": 0.05, "h2": 0.40, "h3": 0.15, "vib": 0.1, "vib_hz": 6.0,
        "attack": 15, "decay": 1200, "frames": 3000, "amplitude": 7800, "volume": 0.22,
    },
    "Music Box": {
        "label": "🎼 Music Box",
        "freqs": [523.25, 659.25, 783.99, 1046.50, 1318.51, 1567.98, 2093.00, 2637.02, 3135.96, 3520.00, 4186.01],
        "prefix": "ac_v6_note_",
        "sub": 0.0, "h2": 0.10, "h3": 0.0, "vib": 0.05, "vib_hz": 4.0,
        "attack": 10, "decay": 900, "frames": 2600, "amplitude": 7200, "volume": 0.21,
    },
    "Pixel Flute": {
        "label": "🪈 Pixel Flute",
        "freqs": [392.00, 440.00, 523.25, 587.33, 659.25, 783.99, 880.00, 1046.50, 1174.66, 1318.51, 1567.98],
        "prefix": "ac_v7_note_",
        "sub": 0.10, "h2": 0.15, "h3": 0.05, "vib": 0.35, "vib_hz": 5.0,
        "attack": 60, "decay": 1300, "frames": 3400, "amplitude": 6800, "volume": 0.23,
    },
    "Crystal Harp": {
        "label": "💎 Crystal Harp",
        "freqs": [440.00, 554.37, 659.25, 880.00, 1108.73, 1318.51, 1760.00, 2217.46, 2637.02, 3520.00, 4434.92],
        "prefix": "ac_v8_note_",
        "sub": 0.0, "h2": 0.35, "h3": 0.20, "vib": 0.15, "vib_hz": 7.0,
        "attack": 25, "decay": 1500, "frames": 3800, "amplitude": 7500, "volume": 0.22,
    },
    "Dreamy Chime": {
        "label": "🎐 Dreamy Chime",
        "freqs": [659.25, 783.99, 987.77, 1174.66, 1318.51, 1567.98, 1975.53, 2349.32, 2637.02, 3135.96, 3951.07],
        "prefix": "ac_v9_note_",
        "sub": 0.0, "h2": 0.20, "h3": 0.10, "vib": 0.25, "vib_hz": 6.5,
        "attack": 20, "decay": 1100, "frames": 2900, "amplitude": 7000, "volume": 0.20,
    },
}
DEFAULT_AC_VOICE_VARIANT = "Classic AC"

# ═══════════════════════════════════════════════════════════════════════════
# CEL'S REALISTIC VOICE - 16 profiles ported 1:1 from
# melodii_oxford_phonetic_studio_monochrome.html
# ═══════════════════════════════════════════════════════════════════════════
# These are the *voice cards* the studio shows. Each profile is a different
# vocal-tract length, pitch and articulation style, not a different sound
# effect: the synthesiser in services/realistic_voice.py reads these numbers.
REALISTIC_VOICE_PROFILES = {
    "melodii_f": {
        "label": "🎤 Melodii (F) - Funk Chop", "name": "Melodii (Female)",
        "sub": "Funk Chop", "icon": "🎤",
        "baseHz": 235.0, "tractScale": 1.14, "syllableDur": 0.115,
        "defaultStyle": "melodii", "vibRate": 5.5, "vibDepth": 4.5,
        "breath": 0.08, "sourceType": "glottal",
    },
    "melodii_m": {
        "label": "🎧 Soul Boy (M) - Warm Groove", "name": "Soul Boy (Male)",
        "sub": "Warm Groove", "icon": "🎧",
        "baseHz": 132.0, "tractScale": 0.88, "syllableDur": 0.118,
        "defaultStyle": "melodii", "vibRate": 5.2, "vibDepth": 3.8,
        "breath": 0.06, "sourceType": "glottal",
    },
    "whistle": {
        "label": "😙 Whistle - Breeze Flute", "name": "Soft Whistle",
        "sub": "Breeze Flute", "icon": "😙",
        "baseHz": 440.0, "tractScale": 1.18, "syllableDur": 0.130,
        "defaultStyle": "melodii", "vibRate": 5.5, "vibDepth": 7.5,
        "breath": 0.12, "sourceType": "whistle",
    },
    "guitar": {
        "label": "🎸 Guitar Talk - Wildlife Box", "name": "Wildlife Guitar",
        "sub": "Wildlife Box", "icon": "🎸",
        "baseHz": 220.0, "tractScale": 1.00, "syllableDur": 0.120,
        "defaultStyle": "melodii", "vibRate": 5.0, "vibDepth": 2.0,
        "breath": 0.04, "sourceType": "guitar",
    },
    "celesta": {
        "label": "🎐 Celesta Bell - Music Box", "name": "Celesta Bell",
        "sub": "Music Box", "icon": "🎐",
        "baseHz": 350.0, "tractScale": 1.16, "syllableDur": 0.135,
        "defaultStyle": "melodii", "vibRate": 5.2, "vibDepth": 2.5,
        "breath": 0.03, "sourceType": "celesta",
    },
    "ocarina": {
        "label": "🪈 Ocarina - Sweet Clay", "name": "Ocarina Flute",
        "sub": "Sweet Clay", "icon": "🪈",
        "baseHz": 392.0, "tractScale": 1.14, "syllableDur": 0.132,
        "defaultStyle": "melodii", "vibRate": 5.3, "vibDepth": 6.2,
        "breath": 0.10, "sourceType": "ocarina",
    },
    "kalimba": {
        "label": "✨ Kalimba - Thumb Tines", "name": "Kalimba Tine",
        "sub": "Thumb Tines", "icon": "✨",
        "baseHz": 277.18, "tractScale": 1.08, "syllableDur": 0.118,
        "defaultStyle": "melodii", "vibRate": 4.8, "vibDepth": 1.8,
        "breath": 0.03, "sourceType": "kalimba",
    },
    "rhodes": {
        "label": "🎹 Dream Keys - Warm Rhodes", "name": "Dream Keys",
        "sub": "Warm Rhodes", "icon": "🎹",
        "baseHz": 220.0, "tractScale": 1.05, "syllableDur": 0.140,
        "defaultStyle": "hymn", "vibRate": 4.6, "vibDepth": 4.2,
        "breath": 0.04, "sourceType": "rhodes",
    },
    "cello": {
        "label": "🎻 Warm Cello - Bowed Soul", "name": "Warm Cello",
        "sub": "Bowed Soul", "icon": "🎻",
        "baseHz": 130.81, "tractScale": 0.88, "syllableDur": 0.145,
        "defaultStyle": "melodii", "vibRate": 4.9, "vibDepth": 6.5,
        "breath": 0.05, "sourceType": "cello",
    },
    "seraph": {
        "label": "🕊️ Seraph Air - Angel Halo", "name": "Seraph Air",
        "sub": "Angel Halo", "icon": "🕊️",
        "baseHz": 293.66, "tractScale": 1.22, "syllableDur": 0.150,
        "defaultStyle": "hymn", "vibRate": 5.4, "vibDepth": 6.8,
        "breath": 0.11, "sourceType": "seraph",
    },
    "choir": {
        "label": "👼 Choir SATB - Cathedral", "name": "Angelic Choir",
        "sub": "Cathedral", "icon": "👼",
        "baseHz": 220.0, "tractScale": 1.02, "syllableDur": 0.155,
        "defaultStyle": "hymn", "vibRate": 5.2, "vibDepth": 6.0,
        "breath": 0.10, "sourceType": "choir",
    },
    "human_f": {
        "label": "👩 Human (F) - Natural Talk", "name": "Human Female",
        "sub": "Natural Talk", "icon": "👩",
        "baseHz": 215.0, "tractScale": 1.12, "syllableDur": 0.105,
        "defaultStyle": "speech", "vibRate": 5.4, "vibDepth": 2.2,
        "breath": 0.09, "sourceType": "glottal",
    },
    "human_m": {
        "label": "👨 Human (M) - Deep Talk", "name": "Human Male",
        "sub": "Deep Talk", "icon": "👨",
        "baseHz": 118.0, "tractScale": 0.85, "syllableDur": 0.108,
        "defaultStyle": "speech", "vibRate": 5.0, "vibDepth": 1.8,
        "breath": 0.07, "sourceType": "glottal",
    },
    "child": {
        "label": "🧒 Child Voice - Bright Kid", "name": "Child Voice",
        "sub": "Bright Kid", "icon": "🧒",
        "baseHz": 295.0, "tractScale": 1.30, "syllableDur": 0.098,
        "defaultStyle": "speech", "vibRate": 5.8, "vibDepth": 3.0,
        "breath": 0.06, "sourceType": "glottal",
    },
    "old_man": {
        "label": "👴 Old Man - Wise Elder", "name": "Old Man Voice",
        "sub": "Wise Elder", "icon": "👴",
        "baseHz": 96.0, "tractScale": 0.80, "syllableDur": 0.142,
        "defaultStyle": "speech", "vibRate": 4.3, "vibDepth": 9.5,
        "breath": 0.15, "sourceType": "glottal",
    },
    "animalese": {
        "label": "🐾 Isabelle NPC - Cozy Village", "name": "Isabelle NPC",
        "sub": "Cozy Village", "icon": "🐾",
        "baseHz": 330.0, "tractScale": 1.34, "syllableDur": 0.075,
        "defaultStyle": "melodii", "vibRate": 6.0, "vibDepth": 3.0,
        "breath": 0.05, "sourceType": "glottal",
    },
}
DEFAULT_REALISTIC_VOICE = "melodii_f"

#: What *Cel* sounds like while her reply types out. The three engines this
#: build ships - exactly three presets, no overlapping dropdowns:
#:   1. Cel's Legacy Sound - the archived Cerebellium v1.5 cellium bloop
#:   2. Cel's Modern Melodi  - the Oct-12 melodii multi-beep bank
#:   3. Cel's Realistic Voice - the Oxford phonetic-studio formant synth
#: Old labels are accepted as aliases so earlier settings files keep working.
CEL_TYPING_MODES = (
    "Cel's Legacy Sound",
    "Cel's Modern Melodi",
    "Cel's Realistic Voice",
)

#: What *your own keyboard* sounds like. Cel's voice channel and yours are
#: deliberately separate (see main_window.play_user_typing_sound).
USER_TYPING_MODES = (
    "Normal (UI clicks)",
    "Cel's Modern Melodi",
    "Cel's Legacy Sound",
    "None (Silent)",
)

# Backwards-compatible name used by older settings/UI code.
TYPING_SOUND_MODES = USER_TYPING_MODES

_CEL_TYPING_ALIASES = {
    "Preview Legacy Sound": "Cel's Legacy Sound",
    "Cel's Original Sound": "Cel's Legacy Sound",
    "Cel Melodi (Musical chirps)": "Cel's Modern Melodi",
    "Normal (UI clicks)": "Cel's Legacy Sound",
    "None (Silent)": "Cel's Legacy Sound",
}
_USER_TYPING_ALIASES = {
    "Cel Melodi (Musical chirps)": "Cel's Modern Melodi",
    "Preview Legacy Sound": "Cel's Legacy Sound",
}


def normalize_cel_typing_mode(value) -> str:
    """Map every historical Cel-voice label onto the current four modes."""
    raw = str(value or "").strip()
    raw = _CEL_TYPING_ALIASES.get(raw, raw)
    return raw if raw in CEL_TYPING_MODES else "Cel's Legacy Sound"


def normalize_user_typing_mode(value) -> str:
    """Map every historical keyboard-sound label onto the current modes."""
    raw = str(value or "").strip()
    raw = _USER_TYPING_ALIASES.get(raw, raw)
    return raw if raw in USER_TYPING_MODES else "Normal (UI clicks)"


#: Canonical sound-pack names. Old names are aliases so a settings file from
#: an earlier build keeps working instead of silently falling back.
DEFAULT_SOUND_PACK = "Cel's New Sounds"
SOUND_PACK_ALIASES = {
    "Modern Cozy & Musical": DEFAULT_SOUND_PACK,
    "Cel Legacy Sounds": "Cel's Original Sound",
}
CURRENT_SOUND_PACK = DEFAULT_SOUND_PACK

#: Spoken by the Live Mode "▶ Preview" button, so a voice is judged by ear
#: instead of by guesswork - and by the *call's* engine, not the chat one.
LIVE_VOICE_PREVIEW = "Hi, I'm Cel, and this is the voice you selected."
SOUND_PRESET_MAPS = {
    # Cel's New Sounds - the Animal Crossing "villager" chirps from the
    # original Celium voice bank. Every UI event is a different note from the
    # same pentatonic scale, so clicks and typing feel like Cel humming along.
    "Cel's New Sounds": {
        "click": SOUNDS_DIR / "ac_note_3.wav",
        "pop": SOUNDS_DIR / "ac_note_5.wav",
        "send": SOUNDS_DIR / "ac_note_7.wav",
        "recv": SOUNDS_DIR / "ac_note_6.wav",
        "open": SOUNDS_DIR / "ac_note_2.wav",
        "close": SOUNDS_DIR / "ac_note_1.wav",
        "type": SOUNDS_DIR / "ac_note_4.wav",
        "scroll": SOUNDS_DIR / "ac_note_2.wav",
        "keypress": SOUNDS_DIR / "ac_note_4.wav",
        "right_click": SOUNDS_DIR / "ac_note_3.wav",
        "middle_click": SOUNDS_DIR / "ac_note_3.wav",
        "appear": SOUNDS_DIR / "cel_appear.wav",
    },
    # Cel's Original Sound - the *actual* archived Cerebellium.py synth.
    # create_smooth_bloop() (sine + sin(pi*t/dur) envelope) and
    # create_cellium_bloop() (square + exp(-i/500) decay) are reproduced
    # exactly in generate_sound_library(); nothing is modernised here.
    "Cel's Original Sound": {
        "click": SOUNDS_DIR / "cerebrium_click.wav",
        "pop": SOUNDS_DIR / "cerebrium_pop.wav",
        "send": SOUNDS_DIR / "cerebrium_send.wav",
        "recv": SOUNDS_DIR / "cerebrium_recv.wav",
        "open": SOUNDS_DIR / "cerebrium_open.wav",
        "close": SOUNDS_DIR / "cerebrium_close.wav",
        "type": SOUNDS_DIR / "cerebrium_type.wav",
        "scroll": SOUNDS_DIR / "cerebrium_scroll.wav",
        "keypress": SOUNDS_DIR / "cerebrium_keypress.wav",
        "right_click": SOUNDS_DIR / "cerebrium_right_click.wav",
        "middle_click": SOUNDS_DIR / "cerebrium_middle_click.wav",
        "appear": SOUNDS_DIR / "cerebrium_appear.wav",
    },
}


def normalize_sound_pack(name) -> str:
    """Map legacy pack names to their canonical names."""
    raw = str(name or "").strip()
    raw = SOUND_PACK_ALIASES.get(raw, raw)
    if raw == "Muted" or raw in SOUND_PRESET_MAPS:
        return raw
    return DEFAULT_SOUND_PACK


def set_sound_pack(name) -> str:
    """Publish the live pack name to play_ui_sound() and return it."""
    global CURRENT_SOUND_PACK
    CURRENT_SOUND_PACK = normalize_sound_pack(name)
    return CURRENT_SOUND_PACK


CEL_VOICE_SOUND_OBJECTS = {}
_AC_SOUND_OBJECTS = []


def reload_cel_voice_sounds():
    """(Re)load pygame Sound objects for every Cel voice variant from disk.

    Lazy by design: config is imported before QApplication, and initialising
    the pygame mixer at import would add ~1.3 s to every cold boot. The first
    chirp/preview calls this; `_ensure_pygame_mixer()` is the only place that
    imports pygame, so the module-level handle is set there.
    """
    global _AC_SOUND_OBJECTS, CEL_VOICE_SOUND_OBJECTS
    CEL_VOICE_SOUND_OBJECTS = {}
    if not _ensure_pygame_mixer() or pygame is None:
        _AC_SOUND_OBJECTS = []
        return
    failed = []
    for vname, vdef in CEL_VOICE_VARIANTS.items():
        objs = []
        for idx in range(len(vdef["freqs"])):
            note_p = SOUNDS_DIR / f"{vdef['prefix']}{idx}.wav"
            if not note_p.exists():
                failed.append(note_p.name)
                continue
            try:
                snd = pygame.mixer.Sound(str(note_p))
                snd.set_volume(float(vdef.get("volume", 0.22)))
                objs.append(snd)
            except Exception as exc:
                failed.append(f"{note_p.name}: {exc}")
        CEL_VOICE_SOUND_OBJECTS[vname] = objs
    _AC_SOUND_OBJECTS = CEL_VOICE_SOUND_OBJECTS.get(DEFAULT_AC_VOICE_VARIANT, [])
    if failed:
        dev_log(f"Cel voice notes failed to load ({len(failed)}): {failed[:3]}")


# NOTE: do not call reload_cel_voice_sounds() at import - see docstring.

_LAST_AC_CHIRP = 0
VISION_KEYWORDS = ["vision", "vl", "gemini", "gpt-4o", "4o", "pixtral", "llava", "internvl", "minicpm", "qwen-vl"]

DEFAULT_SETTINGS = {
    "local_model_path": "",
    # Chat template for the *offline* GGUF path. Autodetect reads the model
    # filename, which is the only reliable signal when you collect random
    # GGUFs - a Qwen2.5 finetune called "abliterated" still says "qwen".
    "offline_format": "Auto-detect from model name",
    "user_name": "You",
    "screenshot_delay": 0,
    "user_persona": "Your name is Cel and You are a Sassy Human and a Gen-Z Female. Keep it occasionally short when needed, fun, weird and unfiltered always",
    "user_memory_rules": "Always use Kaomojis which are Japanese Emoticons made of Keyboard Symbols",
    "incognito": False,
    # CEL's streaming voice - what she sounds like as her reply types out.
    "typing_sound_enabled": True,
    "typing_sound_mode": "Cel's Legacy Sound",
    # Which of the 16 Melodii / Oxford profiles Cel's Realistic Voice uses.
    "realistic_voice_profile": DEFAULT_REALISTIC_VOICE,
    # YOUR keyboard. These used to be the same two keys, so changing her voice
    # changed what your own typing sounded like and muting her muted you.
    "user_typing_sound_enabled": True,
    "user_typing_sound_mode": "Normal (UI clicks)",
    "user_typing_sound_volume": 40,
    "animalese_voice": True,
    "ac_voice_variant": "Classic AC",
    "sound_pack": DEFAULT_SOUND_PACK,
    "auto_stt_removed": None,
    "voice_stt_engine": "ggml Whisper (Local)",
    # Explicit model paths. "" = auto-resolve (settings → env → filesystem).
    "stt_ggml_path": "",
    "kokoro_tts_dir": "",
    # Two transcriptions racing in parallel was the default - it doubled the
    # CPU during a call and bought nothing when only the local engine is live.
    "voice_multi_mode": False,
    "custom_sounds": {},
    "audio_volumes": {},
    "text_speed": "Normal",
    "selected_model": "",
    "streaming_mode": "Letter-by-Letter",
    "voice_host": "Kokoro (Offline)",
    "tts_voice": "af_heart",
    "tts_skip_asterisks": True,
    # CelAS Live Mode keeps its own voice so a call can never hijack chat's
    # voice_host / ac_voice_variant (what the desktop pet chirps with).
    "live_voice": "Kokoro (Offline)",
    # The voice *inside* that host ("af_heart", "en-US-JennyNeural", …).
    # Empty = the host's own default.
    "live_voice_id": "",
    # Live mic behaviour
    "live_push_to_talk": False,
    "live_auto_send": True,
    "live_mic_muted": False,
    # How long the mic must hear near-silence before it decides you stopped
    # talking, then transcribes and sends. 2 s is a natural end of sentence;
    # the old 900 ms cut people off mid-thought.
    "live_silence_ms": 2000,
    # The key you hold to talk during a call (Settings -> Bind Key). Any single
    # key or chord Qt can name: "Space", "K", "Ctrl+Shift+M".
    "live_ptt_key": "Space",
    # Floating YOU/CEL name tags on the Live Mode transcript - off for a
    # clean interface for new users; enabled via the Live settings checkbox.
    "live_show_names": False,
    # What she listens for before opening a call.
    "live_wake_phrase": "Okay Cel",
    # Drifting dust behind the glass (Tier-1 ParticleCanvas). Toggleable from the
    # right-click menu or Ctrl+K; off = no canvas at all.
    "ambient_particles": True,
    # Pet mode: the floating desktop companion, on demand from
    # Settings -> Live Mode. Off by default - it is a separate window.
    "pet_mode_enabled": False,
    # Show her replies in the pet's speech bubble (the face reacts either way).
    "pet_speak_replies": True,
    # 100 = the size she has always had.
    "pet_scale": 100,
    # Always-on "Hey Cel" wake word (the 🎧 quick toggle in the top bar).
    "listen_activation": False,
    "wake_calibration_done": False,
    "wake_threshold": 0.012,
    "wake_phrase_variants": [],
    "wake_engine": "auto",
    "wake_oww_model": "",
    "wake_oww_threshold": 0.4,
    "minimize_to_tray": False,
    "close_to_tray": False,
    # Calibrated mic noise cancellation: room-profile spectral gate (F1).
    "noise_cancel_enabled": True,
    "noise_cancel_strength": 70,
    "noise_calibration_done": False,
    "thinking_level": "🧠 Auto",
    "openrouter_token_usage": "medium (safe for casual coding)",
    # Quick persona/memory kill-switches (More menu). Both default ON so
    # existing installs keep the exact prompt they had before.
    "persona_enabled": True,
    "memory_enabled": True,
    # Per-category overrides for the instructions we actually send. Empty
    # dict = use SYSTEM_INSTRUCTION_DEFAULTS from core/utils.py.
    "system_instructions": {},
    "font_scale": "Small (Default)",
    "cached_dev_memory": "",
    "offline_n_ctx": 2048,
    "offline_n_ctx_str": "2048 (Balanced - Default)",
    "offline_threads": max(1, (os.cpu_count() or 4) - max(1, (os.cpu_count() or 4) // 4)),
    "offline_gpu_layers": 0,
    "offline_temperature": 0.7,
    "offline_top_p": 0.9,
    "offline_repeat_penalty": 1.1,
    "auto_load_offline_to_ram": False,
    # Offline GGUF label switches. Size is shown by default, the word
    # "Offline" is hidden by default, and the size trails the filename.
    "show_offline_model_size": True,
    "show_offline_model_tag": False,
    "offline_model_size_first": False,
    "verbose_logging": True,
    "streaming": True,
    "typing_animation": False,
    "wallpaper_tint": 0.32,
    "glass_opacity": 0.72,
    "panel_opacity": 0.88,
    "glass_blur": 16,
    "user_custom_keys": {},
    "enabled_models": {},
    "all_discovered_models": {},
    "custom_provider_urls": {},
    "kokoro_preload": True,
    "history_shift_nav": True,
    "zoom_level": 1.0,
    "network_timeout": 60,
    "network_max_retries": 5,
    "output_max_tokens": 4096,
    "disable_combo_wheel": True,
    # KV Cache & Hardware Optimization
    "offline_kv_cache_type_k": "f16",
    "offline_kv_cache_type_v": "f16",
    "offline_flash_attn": False,
    "offline_cache_prompt": False,
    # Kaggle cloud image generation (BYOK - each user brings their own key).
    "kaggle_preset": "✨ DreamShaper XL Turbo v2 (fast, public HF)",
    "kaggle_username": "",
    "kaggle_api_key": "",
    "kaggle_model_mode": "huggingface",       # "huggingface" | "civitai"
    "kaggle_hf_model": "lykon/dreamshaper-xl-v2-turbo",
    "kaggle_hf_token": "",
    "kaggle_civitai_url": "",
    "kaggle_civitai_token": "",
    "kaggle_lora_url": "",
    "kaggle_lora_strength": 0.9,
    "kaggle_steps": 28,
    "kaggle_batch": 1,
    "kaggle_size": "832x1216 (9:16)",
    "kaggle_guidance": 6.5,
    "kaggle_negative_prompt": "worst quality, low quality, ugly, blurry, deformed, bad anatomy, watermark, signature",
    "kaggle_output_dir": "",
    # When ON, the agent gets a `generate_image` tool (Kaggle GPU). OFF = tool
    # is not sent to the model at all, keeping the prompt context small.
    "image_gen_enabled": False,
    # Phase 2: dedicated LLM used by the ✨ Enhance button (blank = local tags).
    "kaggle_enhancer_model": "",
    # Imagine dialog memory (CelAS-style sticky prompt).
    "kaggle_prompt": "",
    "kaggle_sticky_prompt": "",
    "kaggle_dialog_mode": "simple",
}

#: Choices for the bubble text size (`font_scale`). Zoom is separate and
#: multiplies with this.
FONT_SCALE_CHOICES = (
    "Small (Default)", "Medium", "Large", "Extra Large",
)

#: Chat templates for the offline GGUF fallback path. llama-cpp-python applies
#: the GGUF's *own* template on the normal path, so these only matter when it
#: falls back to raw completion - but that fallback is what garbles a Qwen if
#: the prompt has no template at all.
OFFLINE_PROMPT_TEMPLATES = (
    "Auto-detect from model name",
    "ChatML (Qwen / Dolphin / Hermes)",
    "Llama 3",
    "Mistral / Mixtral [INST]",
    "Gemma",
    "Plain transcript (no template)",
)

#: Per-sound volume (0-100) and per-sound custom .wav overrides. Mirrored out
#: of the settings dict by :func:`configure_sounds` so `play_ui_sound` - which
#: lives in a service and must not import the UI - can honour them.
SOUND_VOLUMES = {}
CUSTOM_SOUNDS = {}

#: Every sound a user can retune, in the order the picker lists them.
TUNABLE_SOUNDS = (
    "click", "pop", "send", "recv", "open", "close",
    "type", "keypress", "scroll", "right_click", "middle_click",
)


def configure_sounds(settings) -> None:
    """Mirror the live sound pack, volumes and custom files into module state."""
    global SOUND_VOLUMES, CUSTOM_SOUNDS
    if not isinstance(settings, dict):
        return
    # This is the bridge the settings dialog was missing: it used to set a
    # *local* CURRENT_SOUND_PACK in the UI module, while play_ui_sound() read
    # config.CURRENT_SOUND_PACK - so changing the pack did nothing until a
    # restart, and even then the saved value was ignored.
    set_sound_pack(settings.get("sound_pack", DEFAULT_SOUND_PACK))
    vols, custom = {}, {}
    raw_v = settings.get("audio_volumes")
    if isinstance(raw_v, dict):
        for k, v in raw_v.items():
            try:
                vols[str(k)] = max(0, min(250, int(v)))
            except (TypeError, ValueError):
                continue
    raw_c = settings.get("custom_sounds")
    if isinstance(raw_c, dict):
        for k, v in raw_c.items():
            p = str(v or "").strip()
            if p and Path(p).is_file():
                custom[str(k)] = p
    SOUND_VOLUMES = vols
    CUSTOM_SOUNDS = custom
# ``TYPING_SOUND_MODES`` / ``CEL_TYPING_MODES`` are declared next to the Cel
# voice tables (before DEFAULT_SETTINGS) so the settings dialog and the
# streaming path share exactly one list.  The old tuple here was the source of
# the "Cel Melodi" / "Preview Legacy Sound" split; it is intentionally gone.

# ── Speech-to-text engines and the API key each one needs ────────────────
# Groq is the shipped default engine and it needs a key that ships with nobody's
# account. Selecting it used to fail silently at the *first utterance*: the mic
# recorded you, the transcription came back the literal string
# "❌ No Groq API Key (Set in Settings)", and that string was treated as your
# words (typed into the chat box, or auto-sent to the model during a call).
# Every engine now declares its credential here, so the UI asks for the key
# *before* the mic opens - and Live Mode, the chat mic and the settings dialog
# all read this one table instead of each guessing.
# The local engine is ggml/whisper.cpp - Kokoro only *speaks* (TTS). The old
# label read like Kokoro was transcribing you, so it is renamed here; both
# spellings are accepted when reading old settings.
STT_LOCAL_GGML = "ggml Whisper (Local)"
STT_LOCAL_LEGACY = "Kokoro Whisper (Local)"


def norm_stt_engine(value):
    """Map a saved engine label onto the current spelling."""
    v = str(value or STT_LOCAL_GGML)
    return STT_LOCAL_GGML if v == STT_LOCAL_LEGACY else v


STT_ENGINE_KEYS = {
    STT_LOCAL_GGML: (None, ""),
    STT_LOCAL_LEGACY: (None, ""),
    "Groq Whisper (Fastest)": ("Groq", "gsk_…"),
    "Google Speech (Free)": (None, ""),
    "Hugging Face Whisper": ("Hugging Face", "hf_…"),
    "OpenAI Whisper": ("Custom (OpenAI)", "sk-…"),
}


def stt_key_provider(engine):
    """Provider whose API key ``engine`` needs - ``None`` when it needs none."""
    try:
        return STT_ENGINE_KEYS.get(str(engine or ""), (None, ""))[0]
    except Exception:
        return None


def stt_key_hint(engine):
    """Shape of the key this engine expects ("" when it needs no key)."""
    try:
        return STT_ENGINE_KEYS.get(str(engine or ""), (None, ""))[1]
    except Exception:
        return ""


def stt_missing_key(engine, settings):
    """``(provider, hint)`` when ``engine`` is selected but has no key stored.

    ``None`` means the engine is usable as-is - either it needs no credential
    (local Whisper, Google) or one is already saved under its provider name.
    """
    prov = stt_key_provider(engine)
    if not prov:
        return None
    keys = {}
    try:
        if isinstance(settings, dict):
            raw = settings.get("user_custom_keys") or {}
            if isinstance(raw, dict):
                keys = raw
    except Exception:
        keys = {}
    if str(keys.get(prov) or "").strip():
        return None
    return (prov, stt_key_hint(engine))


THEME_COLORS = {
    "Server 1": {"accent": QColor(138, 43, 226), "bright": "#C084FC", "bg": QColor(11, 9, 20), "name": "Purple"},
    "Server 2": {"accent": QColor(139, 0, 0),    "bright": "#F87171", "bg": QColor(20, 9, 9),  "name": "Deep Red"},
    "Server 3": {"accent": QColor(210, 105, 30), "bright": "#FBBF24", "bg": QColor(20, 13, 9), "name": "Amber"},
    "Server 4": {"accent": QColor(0, 100, 0),   "bright": "#4ADE80", "bg": QColor(9, 20, 10), "name": "Forest Green"},
    "Teal":     {"accent": QColor(0, 128, 128), "bright": "#2DD4BF", "bg": QColor(9, 18, 20), "name": "Teal"},
    "Violet":   {"accent": QColor(139, 0, 139), "bright": "#E879F9", "bg": QColor(20, 9, 18), "name": "Violet"},
    "Incognito":{"accent": QColor(51, 51, 51),   "bright": "#9CA3AF", "bg": QColor(0, 0, 0),   "name": "Incognito"},
}

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    tmp = str(path) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        dev_log(f"save_json {path}: {e}")

# Centralized context length mapping
CTX_MAP = {
    "1024 (Fast)": 1024,
    "2048 (Balanced - Default)": 2048,
    "4096 (Deep)": 4096,
    "8192 (Max)": 8192,
    "16384 (Ultra)": 16384,
    "32768 (Native)": 32768,
}

# ------------------------------------------------------------------ GGUF Local Model Cache & Memory Manager
