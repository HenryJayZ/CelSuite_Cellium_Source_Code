#!/usr/bin/env python3
"""CelStudio Cerebrium - Unified Sound Engine (Lossless Clean Slate).

Zero artificial distortion, zero soft-knee clipping, zero tanh waveshaping.
Provides:
  1. Cel's Legacy Sound: 100% exact procedural synth bloops from Cerebellium v1.5.
  2. Cel's Modern Melodi: 100% exact pentatonic multi-beep bank from October 12 backup.
  3. Cel's Realistic Voice: direct lossless concept bridge to Oxford Phonetic Studio.
  4. Crisp UI Sounds: bit-exact playback of authored sound pack WAVs.
"""

from __future__ import annotations

import io
import math
import os
import struct
import sys
import time
import wave
from pathlib import Path
from typing import Dict, Optional

# --- Pygame Lazy Initializer ---
_pygame = None
_mixer_initialized = False

def _ensure_pygame_mixer() -> bool:
    global _pygame, _mixer_initialized
    if _mixer_initialized:
        return True
    try:
        import pygame
        _pygame = pygame
        if not pygame.mixer.get_init():
            # Suppress ALSA/JACK warnings at OS level
            os.environ["JACK_NO_START_SERVER"] = "1"
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
        _mixer_initialized = True
        return True
    except Exception as e:
        return False

from cellium.core import config
from cellium.core.logger import dev_log


# ═══════════════════════════════════════════════════════════════════════════
# 1. CEL'S LEGACY SOUND - 1:1 PURE CEREBELLIUM v1.5 PROCEDURAL SYNTH
# ═══════════════════════════════════════════════════════════════════════════
# Exact formulas from Cerebellium v1.5:
#   - create_smooth_bloop(freq, duration=0.05, vol=0.15)
#   - create_cellium_bloop(freq, duration=0.05) [square + exp decay]

_legacy_cellium_female = None
_legacy_cellium_male = None
_legacy_sound_female = None
_legacy_sound_male = None
_legacy_ui_click = None
_legacy_ui_swoosh = None


def create_smooth_bloop(freq: float, duration: float = 0.05, vol: float = 0.15):
    """Cerebellium v1.5 smooth sine bloop with sine envelope."""
    if not _ensure_pygame_mixer():
        return None
    sample_rate = 44100
    buf = io.BytesIO()
    with wave.open(buf, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = []
        num_samples = int(sample_rate * duration)
        for i in range(num_samples):
            t = i / float(sample_rate)
            env = math.sin(math.pi * (t / duration))
            val = int(env * vol * 32767.0 * math.sin(2.0 * math.pi * freq * t))
            frames.append(struct.pack("<h", max(-32768, min(32767, val))))
        w.writeframes(b"".join(frames))
    buf.seek(0)
    return _pygame.mixer.Sound(buf)


def create_cellium_bloop(freq: float, duration: float = 0.05):
    """Cerebellium v1.5 iconic Cellium bloop: square wave with exponential decay."""
    if not _ensure_pygame_mixer():
        return None
    sample_rate = 44100
    buf = io.BytesIO()
    with wave.open(buf, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = []
        num_samples = int(sample_rate * duration)
        for i in range(num_samples):
            val = 1 if math.sin(2.0 * math.pi * freq * (i / sample_rate)) > 0 else -1
            v = int(4000 * val * math.exp(-i / 500))
            frames.append(struct.pack("<h", max(-32768, min(32767, v))))
        w.writeframes(b"".join(frames))
    buf.seek(0)
    return _pygame.mixer.Sound(buf)


def _init_legacy_sounds():
    global _legacy_cellium_female, _legacy_cellium_male, _legacy_sound_female, _legacy_sound_male, _legacy_ui_click, _legacy_ui_swoosh
    if not _ensure_pygame_mixer():
        return
    try:
        if _legacy_cellium_female is None:
            _legacy_cellium_female = create_cellium_bloop(550.0)
            _legacy_cellium_male = create_cellium_bloop(350.0)
            _legacy_sound_female = create_smooth_bloop(500.0)
            _legacy_sound_male = create_smooth_bloop(200.0)
            _legacy_ui_click = create_smooth_bloop(800.0, 0.02, 0.1)
            _legacy_ui_swoosh = create_smooth_bloop(200.0, 0.1, 0.05)
    except Exception as e:
        dev_log(f"[sound-engine] legacy sound init failed: {e}")


def play_legacy_typing_preview(volume: float | None = None):
    """Play the iconic Cel Legacy bloop directly (100% 1:1 Cerebellium v1.5)."""
    if not _ensure_pygame_mixer():
        return
    _init_legacy_sounds()
    if _legacy_cellium_female:
        try:
            vol = 1.0 if volume is None else max(0.0, min(1.0, float(volume)))
            _legacy_cellium_female.set_volume(vol)
            _legacy_cellium_female.play()
        except Exception:
            pass


def play_legacy_cel_sound(is_smooth: bool = False, male: bool = False):
    """Play Cerebellium v1.5 sound."""
    if not _ensure_pygame_mixer():
        return
    _init_legacy_sounds()
    snd = _legacy_sound_male if male else _legacy_sound_female if is_smooth else (_legacy_cellium_male if male else _legacy_cellium_female)
    if snd:
        try:
            snd.play()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# 2. CEL'S MODERN MELODI - 1:1 OCTOBER 12 MULTI-BEEP SOUND BANK
# ═══════════════════════════════════════════════════════════════════════════
_AC_SOUND_OBJECTS = []
_CEL_VOICE_SOUND_OBJECTS: Dict[str, list] = {}
_LAST_AC_CHIRP = 0.0


def reload_cel_voice_sounds():
    """Load bit-exact pre-rendered WAV notes for all 10 Cel voice variants from disk."""
    global _AC_SOUND_OBJECTS, _CEL_VOICE_SOUND_OBJECTS
    if not _ensure_pygame_mixer():
        return
    _CEL_VOICE_SOUND_OBJECTS = {}
    sounds_dir = config.SOUNDS_DIR

    for vname, vdef in config.CEL_VOICE_VARIANTS.items():
        objs = []
        prefix = vdef.get("prefix", "ac_note_")
        vol = float(vdef.get("volume", 0.22))
        for idx in range(len(vdef.get("freqs", []))):
            note_p = sounds_dir / f"{prefix}{idx}.wav"
            if note_p.exists():
                try:
                    snd = _pygame.mixer.Sound(str(note_p))
                    snd.set_volume(vol)
                    objs.append(snd)
                except Exception:
                    pass
        if objs:
            _CEL_VOICE_SOUND_OBJECTS[vname] = objs

    def_var = getattr(config, "DEFAULT_AC_VOICE_VARIANT", "Classic AC")
    _AC_SOUND_OBJECTS = _CEL_VOICE_SOUND_OBJECTS.get(def_var, [])


def play_animalese_chirp(seed_char: str = "a", enabled: bool = True, variant: str | None = None):
    """Play a melodious Animal Crossing / Melodii chirp (100% 1:1 October 12 backup)."""
    global _LAST_AC_CHIRP
    if not enabled or not _ensure_pygame_mixer():
        return
    if not _CEL_VOICE_SOUND_OBJECTS:
        reload_cel_voice_sounds()

    vname = variant or getattr(config, "DEFAULT_AC_VOICE_VARIANT", "Classic AC")
    sounds = _CEL_VOICE_SOUND_OBJECTS.get(vname) or _AC_SOUND_OBJECTS
    if not sounds:
        return

    now = time.time()
    if now - _LAST_AC_CHIRP < 0.065:
        return
    _LAST_AC_CHIRP = now

    try:
        note_idx = (ord(seed_char) * 7 + int(now * 10)) % len(sounds)
        sounds[note_idx].play()
    except Exception:
        pass


def play_cel_voice_preview(variant_name: str):
    """Play a short melodic phrase preview for the selected Melodi voice variant."""
    if not _ensure_pygame_mixer():
        return
    if not _CEL_VOICE_SOUND_OBJECTS:
        reload_cel_voice_sounds()

    sounds = _CEL_VOICE_SOUND_OBJECTS.get(variant_name) or _AC_SOUND_OBJECTS
    if not sounds:
        return

    try:
        channel = _pygame.mixer.find_channel(True)
        if not channel:
            return
        channel.stop()
        channel.set_volume(1.0)
        picks = (0, 2, 4, 5, 7, 6, 4, 2)
        n = len(sounds)
        for i, idx in enumerate(picks):
            snd = sounds[min(n - 1, idx)]
            if i == 0:
                channel.play(snd)
            else:
                channel.queue(snd)
    except Exception as exc:
        dev_log(f"[sound-engine] preview failed: {exc}")


# ═══════════════════════════════════════════════════════════════════════════
# 3. CEL'S REALISTIC VOICE - RE-EXPORTS FROM REALISTIC_VOICE.PY
# ═══════════════════════════════════════════════════════════════════════════
from cellium.services.realistic_voice import (
    REALISTIC_VOICE_PROFILES,
    DEFAULT_REALISTIC_VOICE,
    feed_realistic_voice,
    flush_realistic_voice,
    stop_realistic_voice,
    play_realistic_voice_preview,
    realistic_voice_is_speaking,
)


# ═══════════════════════════════════════════════════════════════════════════
# 4. CRISP LOSSLESS UI SOUNDS
# ═══════════════════════════════════════════════════════════════════════════
_LAST_SOUND_TS: Dict[str, float] = {}


def play_ui_sound(sound_name: str, volume: float = 0.5):
    """Play UI sound non-blocking using current sound pack preset (bit-exact, no distortion)."""
    pack_name = getattr(config, "CURRENT_SOUND_PACK", "Cel's New Sounds")
    if pack_name == "Muted":
        return

    now = time.monotonic()
    min_gap = 0.018 if sound_name in ("type", "keypress", "scroll") else 0.038
    if now - _LAST_SOUND_TS.get(sound_name, 0.0) < min_gap:
        return
    _LAST_SOUND_TS[sound_name] = now

    # Check per-sound volume slider (0-100%)
    try:
        raw_pct = (getattr(config, "SOUND_VOLUMES", {}) or {}).get(sound_name, 100)
        eff_vol = max(0.0, min(1.0, float(volume) * (int(raw_pct) / 100.0)))
        if eff_vol <= 0.001:
            return
    except Exception:
        eff_vol = max(0.0, min(1.0, float(volume)))

    # Custom override file if specified by user
    custom = (getattr(config, "CUSTOM_SOUNDS", {}) or {}).get(sound_name)
    path = Path(custom) if custom and Path(custom).exists() else None

    if not path:
        pack = config.SOUND_PRESET_MAPS.get(pack_name, config.SOUND_PRESET_MAPS.get("Modern Cozy & Musical", {}))
        path = pack.get(sound_name)
        if not path or not Path(path).exists():
            fallback = config.SOUND_PRESET_MAPS.get("Modern Cozy & Musical", {}).get(sound_name)
            if fallback and Path(fallback).exists():
                path = fallback
            else:
                return

    if not _ensure_pygame_mixer():
        return

    try:
        snd = _pygame.mixer.Sound(str(path))
        snd.set_volume(eff_vol)
        snd.play()
    except Exception as e:
        dev_log(f"[sound-engine] UI sound playback failed: {e}")


def configure_sounds(settings: dict):
    """Configure sound pack and per-sound volume multipliers."""
    if not isinstance(settings, dict):
        return
    pack = settings.get("sound_pack")
    if pack:
        config.CURRENT_SOUND_PACK = pack
    vols = settings.get("sound_volumes")
    if isinstance(vols, dict):
        config.SOUND_VOLUMES = vols
    cust = settings.get("custom_sounds")
    if isinstance(cust, dict):
        config.CUSTOM_SOUNDS = cust


def get_ac_voice_variant() -> str:
    return getattr(config, "CURRENT_AC_VOICE_VARIANT", getattr(config, "DEFAULT_AC_VOICE_VARIANT", "Classic AC"))


def set_ac_voice_variant(name: str):
    config.CURRENT_AC_VOICE_VARIANT = name
