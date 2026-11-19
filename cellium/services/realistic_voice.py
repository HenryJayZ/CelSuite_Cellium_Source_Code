#!/usr/bin/env python3
"""Cel's Realistic Voice - Lossless Concept Engine Bridge.

Runs `melodii_oxford_phonetic_studio_monochrome.html` directly in a background
headless Chromium instance via Playwright. This executes the bit-exact native
Web Audio graph (formant filter bank, glottal periodic wave, pink noise
consonant bursts, true diphthong glides, warm tape shaper, convolution reverb,
and natural prosody) directly through Linux PipeWire / PulseAudio with ZERO
conversion artifacts, zero numpy distortion, and zero CPU jitter.
"""

from __future__ import annotations

import collections
import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Optional

from cellium.core import config
from cellium.core.logger import dev_log

# ═══════════════════════════════════════════════════════════════════════════
# 16 VOICE PROFILES (1:1 with melodii_oxford_phonetic_studio_monochrome.html)
# ═══════════════════════════════════════════════════════════════════════════
REALISTIC_VOICE_PROFILES = {
    "melodii_f": {
        "id": "melodii_f",
        "name": "Melodii (Female)",
        "label": "🎤 Melodii (Female) - Funk Chop",
        "icon": "🎤",
        "baseHz": 235.0,
        "defaultStyle": "melodii",
    },
    "melodii_m": {
        "id": "melodii_m",
        "name": "Soul Boy (Male)",
        "label": "🎧 Soul Boy (Male) - Warm Groove",
        "icon": "🎧",
        "baseHz": 132.0,
        "defaultStyle": "melodii",
    },
    "human_f": {
        "id": "human_f",
        "name": "Human Female",
        "label": "👩 Human Female - Natural Conversational",
        "icon": "👩",
        "baseHz": 215.0,
        "defaultStyle": "speech",
    },
    "human_m": {
        "id": "human_m",
        "name": "Human Male",
        "label": "👨 Human Male - Baritone Warmth",
        "icon": "👨",
        "baseHz": 118.0,
        "defaultStyle": "speech",
    },
    "child": {
        "id": "child",
        "name": "Child Voice",
        "label": "🧒 Child Voice - Bright & Playful",
        "icon": "🧒",
        "baseHz": 295.0,
        "defaultStyle": "speech",
    },
    "old_man": {
        "id": "old_man",
        "name": "Old Man Voice",
        "label": "👴 Old Man Voice - Gravel Storyteller",
        "icon": "👴",
        "baseHz": 96.0,
        "defaultStyle": "speech",
    },
    "choir": {
        "id": "choir",
        "name": "Angelic Choir",
        "label": "✨ Angelic Choir - 4-Part Harmony",
        "icon": "✨",
        "baseHz": 220.0,
        "defaultStyle": "hymn",
    },
    "whistle": {
        "id": "whistle",
        "name": "Soft Whistle",
        "label": "🌬️ Soft Whistle - Airy Melodii",
        "icon": "🌬️",
        "baseHz": 440.0,
        "defaultStyle": "melodii",
    },
    "guitar": {
        "id": "guitar",
        "name": "Wildlife Guitar",
        "label": "🎸 Wildlife Guitar - Acoustic Pluck",
        "icon": "🎸",
        "baseHz": 220.0,
        "defaultStyle": "melodii",
    },
    "celesta": {
        "id": "celesta",
        "name": "Celesta Bell",
        "label": "🔔 Celesta Bell - Crystal Sparkle",
        "icon": "🔔",
        "baseHz": 350.0,
        "defaultStyle": "melodii",
    },
    "ocarina": {
        "id": "ocarina",
        "name": "Ocarina Flute",
        "label": "🎶 Ocarina Flute - Nostalgic Legend",
        "icon": "🎶",
        "baseHz": 392.0,
        "defaultStyle": "melodii",
    },
    "kalimba": {
        "id": "kalimba",
        "name": "Kalimba Tine",
        "label": "🎹 Kalimba Tine - Thumb Piano",
        "icon": "🎹",
        "baseHz": 277.18,
        "defaultStyle": "melodii",
    },
    "rhodes": {
        "id": "rhodes",
        "name": "Dream Keys",
        "label": "🎹 Dream Keys - Electric Rhodes",
        "icon": "🎹",
        "baseHz": 220.0,
        "defaultStyle": "hymn",
    },
    "cello": {
        "id": "cello",
        "name": "Warm Cello",
        "label": "🎻 Warm Cello - Resonant Bowed Wood",
        "icon": "🎻",
        "baseHz": 130.81,
        "defaultStyle": "melodii",
    },
    "seraph": {
        "id": "seraph",
        "name": "Seraph Air",
        "label": "🪽 Seraph Air - Ethereal Pad",
        "icon": "🪽",
        "baseHz": 293.66,
        "defaultStyle": "hymn",
    },
    "animalese": {
        "id": "animalese",
        "name": "Isabelle NPC",
        "label": "🐶 Isabelle NPC - Fast Villager Gibberish",
        "icon": "🐶",
        "baseHz": 330.0,
        "defaultStyle": "melodii",
    },
}

DEFAULT_REALISTIC_VOICE = "melodii_f"

_STUDIO_HTML_PATH = Path("/home/henry/Documents/Projects/Python/Cellium/melodii_oxford_phonetic_studio_monochrome.html")


class _RealisticVoiceBridge:
    """Manages the background Playwright Chromium headless process for HTML WebAudio."""

    _instance: Optional[_RealisticVoiceBridge] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> Optional[_RealisticVoiceBridge]:
        with cls._lock:
            if cls._instance is None:
                if not _STUDIO_HTML_PATH.exists():
                    dev_log(f"[realistic-voice] HTML studio not found at {_STUDIO_HTML_PATH}")
                    return None
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._cmd_queue: queue.Queue = queue.Queue()
        self._ready_event = threading.Event()
        self._is_speaking = False
        self._thread = threading.Thread(target=self._run_browser_loop, daemon=True, name="RealisticVoicePlaywright")
        self._thread.start()

    def _run_browser_loop(self):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--autoplay-policy=no-user-gesture-required",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",  # Web Audio is purely CPU/DSP; disables heavy GPU process
                        "--disable-extensions",
                        "--disable-component-update",
                        "--disable-background-networking",
                        "--js-flags=--max-old-space-size=64",  # Cap V8 JS memory footprint to 64MB
                    ]
                )
                page = browser.new_page()
                page.goto(f"file://{_STUDIO_HTML_PATH.resolve()}")
                self._ready_event.set()
                dev_log("[realistic-voice] Concept engine WebAudio bridge active on Linux PipeWire.")

                while True:
                    cmd, args = self._cmd_queue.get()
                    if cmd == "quit":
                        break
                    elif cmd == "speak":
                        text, voice = args
                        self._is_speaking = True
                        try:
                            page.evaluate("([t, v]) => { if (window.MelodiiSynth) window.MelodiiSynth.speak(t, v); }", [text, voice])
                        except Exception as e:
                            dev_log(f"[realistic-voice] speak evaluate error: {e}")
                    elif cmd == "stop":
                        self._is_speaking = False
                        try:
                            page.evaluate("() => { if (window.stopStreamingSpeech) window.stopStreamingSpeech(); }")
                        except Exception as e:
                            dev_log(f"[realistic-voice] stop evaluate error: {e}")
                browser.close()
        except Exception as exc:
            dev_log(f"[realistic-voice] Playwright background runner crashed or missing: {exc}")
            self._ready_event.set()

    def speak(self, text: str, voice_id: str = "melodii_f"):
        t = str(text or "").strip()
        if not t:
            return
        v = voice_id if voice_id in REALISTIC_VOICE_PROFILES else DEFAULT_REALISTIC_VOICE
        self._cmd_queue.put(("speak", (t, v)))

    def stop(self):
        self._cmd_queue.put(("stop", ()))
        self._is_speaking = False

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking


# ═══════════════════════════════════════════════════════════════════════════
# STREAMING BUFFER & PUBLIC CONTROLS
# ═══════════════════════════════════════════════════════════════════════════
_stream_text_buffer = ""
_stream_profile = DEFAULT_REALISTIC_VOICE
_stream_lock = threading.Lock()
_PUNCT_SPLIT_RE = re.compile(r"([.!?,;: - \n]+)")


def feed_realistic_voice(text: str, profile_key: str | None = None, volume: float = 0.9):
    """Feed delta streaming tokens to the realistic voice engine.

    Buffers until a sentence or clause boundary so words are spoken with
    full natural prosody from the concept engine.
    """
    global _stream_text_buffer, _stream_profile
    bridge = _RealisticVoiceBridge.get()
    if not bridge:
        return

    with _stream_lock:
        if profile_key:
            _stream_profile = profile_key
        _stream_text_buffer += text
        # If we have a sentence or phrase break, speak the completed chunk
        parts = _PUNCT_SPLIT_RE.split(_stream_text_buffer)
        if len(parts) > 2:
            # We have at least one complete phrase: parts[0] + parts[1]
            chunk_to_speak = "".join(parts[:-1]).strip()
            _stream_text_buffer = parts[-1]
            if chunk_to_speak:
                bridge.speak(chunk_to_speak, _stream_profile)


def flush_realistic_voice() -> None:
    """Flush any remaining buffered text when Cel finishes generating her reply."""
    global _stream_text_buffer, _stream_profile
    bridge = _RealisticVoiceBridge.get()
    if not bridge:
        return
    with _stream_lock:
        rem = _stream_text_buffer.strip()
        _stream_text_buffer = ""
        if rem:
            bridge.speak(rem, _stream_profile)


def stop_realistic_voice() -> None:
    """Instantly silence realistic voice speech."""
    global _stream_text_buffer
    with _stream_lock:
        _stream_text_buffer = ""
    bridge = _RealisticVoiceBridge.get()
    if bridge:
        bridge.stop()


def play_realistic_voice_preview(profile_key: str, text: str | None = None) -> None:
    """Preview a realistic voice profile (e.g. from Settings Dialog ▶ Preview)."""
    bridge = _RealisticVoiceBridge.get()
    if not bridge:
        return
    phrase = text or "Hi, I'm Cel, and this is the voice you selected."
    bridge.stop()
    bridge.speak(phrase, profile_key)


def realistic_voice_is_speaking() -> bool:
    bridge = _RealisticVoiceBridge.get()
    return bridge.is_speaking if bridge else False
