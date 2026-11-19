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

# --- KOKORO LOCAL STT IMPORTS ---
HAS_KOKORO_STT = False
try:
    from pywhispercpp.model import Model
    import sounddevice as sd
    HAS_KOKORO_STT = True
except Exception:
    HAS_KOKORO_STT = False

# ggml (whisper.cpp) model resolution: settings override → KOKORO_MODELS_DIR
# → the directories that actually exist on this machine. The old default
# pointed at ~/Documents/Projects/Python/Kokoro, which does not exist here  - 
# the real file is one level up - so every recording answered
# "❌ Missing ggml-base.en-q5_1.bin at .../Projects/Python/Kokoro".
GGML_MODEL_NAME = "ggml-base.en-q5_1.bin"
_GGML_DIRS = tuple(Path(p) for p in dict.fromkeys(filter(None, [
    os.environ.get("KOKORO_MODELS_DIR", "").strip(),
    str(globals().get("APP_EXEC_DIR", BASE_DIR) / "Kokoro"),
    str(globals().get("APP_EXEC_DIR", BASE_DIR) / "models"),
    str(BASE_DIR.parent / "models"),
    str(Path.home() / ".local" / "share" / "cellium" / "Kokoro"),
    str(Path.home() / "Documents" / "Projects" / "Kokoro"),
    str(Path.home() / "Documents" / "Projects" / "Python" / "Kokoro"),
])))


def resolve_ggml_path(custom="") -> Path:
    """Settings file → env → first directory that really has the model.

    A configured path always wins outright: if it is wrong, the error must
    name *your* path, not a fallback you did not choose.
    """
    c = str(custom or "").strip()
    if c:
        return Path(os.path.expanduser(c))
    for d in _GGML_DIRS:
        p = d / GGML_MODEL_NAME
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return _GGML_DIRS[0] / GGML_MODEL_NAME


KOKORO_PROJECT_DIR = resolve_ggml_path().parent
KOKORO_WHISPER_PATH = resolve_ggml_path()

# Kokoro STT tuning constants
KOKORO_SR = 16000
KOKORO_SPEECH_RMS = 0.015
KOKORO_SILENCE_RMS = 0.007
KOKORO_SILENT_BLOCKS = 8
KOKORO_PRE_ROLL = 4
KOKORO_METER_SCALE = 400.0


def stt_text_is_error(text) -> bool:
    """True when a transcription result is a *failure notice*, not speech.

    The engine helpers above report problems as ordinary strings ("❌ No Groq
    API Key", "HTTP 401: …", "Kokoro Err: …"). Those used to travel out of
    ``single_result``, so the app typed the error into the chat box and, worse,
    *sent it to the model as if you had said it* during a Live call. Callers
    now get failures on ``signals.error`` and can never mistake them for words.
    """
    t = str(text or "").strip()
    if not t:
        return True
    if t.startswith("❌"):
        return True
    low = t.lower()
    return low.startswith(("err:", "error", "http ", "kokoro err", "groq err",
                           "hf err", "google err", "failed", "*("))


_WHISPER_MODEL_CACHE: dict = {}
_WHISPER_LOCK = threading.Lock()


class STTSignals(QObject):
    single_result = Signal(str, str)
    multi_results = Signal(dict)
    error = Signal(str)
    rms_update = Signal(float)
    status_update = Signal(str)


class STTWorker(QThread):
    def __init__(self, wav_bytes, engine="ggml Whisper (Local)", multi_mode=False, groq_key="", openai_key="", hf_key="", parent=None, ggml_path=""):
        super().__init__(parent)
        self.wav_bytes = wav_bytes
        self.engine = engine
        self.multi_mode = multi_mode
        self.groq_key = groq_key
        self.openai_key = openai_key
        self.hf_key = hf_key
        # Settings-driven ggml path ("" = auto-resolve on this machine).
        self.ggml_path = ggml_path
        self.signals = STTSignals()
        # Named so Qt's "Destroyed while thread '' is still running" abort
        # names the culprit instead of an empty string.
        self.setObjectName("cellium-stt")

    def run(self):
        results = {}

        # Calibrated noise cancellation: strip the recorded room floor before
        # any engine sees the clip. Passthrough by default (no profile yet or
        # library missing), and never raises - STT must not break because of
        # an optional DSP step.
        try:
            from .noise_gate import denoise
            self.wav_bytes = denoise(self.wav_bytes)
        except Exception:
            pass

        def _transcribe_kokoro_local():
            if not HAS_KOKORO_STT:
                return "❌ pywhispercpp or sounddevice not installed"
            model_path = resolve_ggml_path(getattr(self, "ggml_path", ""))
            if not model_path.is_file():
                return (f"❌ Missing {model_path.name} at {model_path.parent}"
                        f" - set the path in Settings → Voice Input")
            try:
                with io.BytesIO(self.wav_bytes) as bio:
                    with wave.open(bio, 'rb') as wf:
                        frames = wf.readframes(wf.getnframes())
                        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                        nch = wf.getnchannels()
                        fr = wf.getframerate()
                if nch > 1:
                    audio = audio.reshape(-1, nch).mean(axis=1)
                if fr != KOKORO_SR:
                    import scipy.signal
                    audio = np.asarray(scipy.signal.resample(audio, int(len(audio) * KOKORO_SR / fr)), dtype=np.float32)
                with _WHISPER_LOCK:
                    key = str(model_path)
                    model = _WHISPER_MODEL_CACHE.get(key)
                    if model is None:
                        model = Model(key, n_threads=max(2, min(4, os.cpu_count() or 2)),
                                      print_realtime=False, print_progress=False)
                        _WHISPER_MODEL_CACHE[key] = model
                    text = _transcribe_kokoro(model, audio)
                return text
            except Exception as e:
                return f"Kokoro Err: {str(e)[:60]}"

        def _transcribe_kokoro(model, clip: np.ndarray) -> str:
            try:
                segs = model.transcribe(clip, language="en", initial_prompt="Okay Cel, Hey Cel, Hi Cel.")
            except TypeError:
                segs = model.transcribe(clip, language="en")
            raw_txt = " ".join(s.text for s in segs).strip()
            # Strip Whisper fan-noise hallucinations: (crowd cheering), [music], *sighs*
            raw_txt = re.sub(r"\([^)]*\)|\[[^\]]*\]|\*[^*]*\*", "", raw_txt).strip()
            return raw_txt

        def _transcribe_groq():
            if not self.groq_key:
                return "❌ No Groq API Key (Set in Settings)"
            try:
                files = {'file': ('speech.wav', self.wav_bytes, 'audio/wav')}
                data = {'model': 'whisper-large-v3-turbo', 'response_format': 'json'}
                headers = {'Authorization': f'Bearer {self.groq_key}'}
                r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                  headers=headers, files=files, data=data, timeout=12)
                if r.status_code == 200:
                    return r.json().get("text", "").strip()
                return f"HTTP {r.status_code}: {r.text[:80]}"
            except Exception as e:
                return f"Groq Err: {str(e)[:60]}"

        def _transcribe_google():
            if not HAS_SR:
                return "❌ speech_recognition not installed"
            try:
                r = sr.Recognizer()
                with sr.AudioFile(io.BytesIO(self.wav_bytes)) as source:
                    audio = r.record(source)
                return r.recognize_google(audio).strip()
            except sr.UnknownValueError:
                return "*(incomprehensible speech)*"
            except Exception as e:
                return f"Google Err: {str(e)[:60]}"

        def _transcribe_hf():
            if not self.hf_key:
                return "❌ No Hugging Face Token"
            try:
                headers = {"Authorization": f"Bearer {self.hf_key}"}
                r = requests.post("https://api-inference.huggingface.co/models/openai/whisper-large-v3",
                                  headers=headers, data=self.wav_bytes, timeout=15)
                if r.status_code == 200:
                    return r.json().get("text", "").strip()
                return f"HF {r.status_code}: {r.text[:60]}"
            except Exception as e:
                return f"HF Err: {str(e)[:60]}"

        def _transcribe_openai():
            if not self.openai_key:
                return "❌ No OpenAI Key"
            try:
                files = {'file': ('speech.wav', self.wav_bytes, 'audio/wav')}
                data = {'model': 'whisper-1'}
                headers = {'Authorization': f'Bearer {self.openai_key}'}
                r = requests.post("https://api.openai.com/v1/audio/transcriptions",
                                  headers=headers, files=files, data=data, timeout=15)
                if r.status_code == 200:
                    return r.json().get("text", "").strip()
                return f"HTTP {r.status_code}"
            except Exception as e:
                return f"Err: {str(e)[:60]}"

        if self.multi_mode:
            res_lock = threading.Lock()
            threads = []

            def run_kokoro():
                txt = _transcribe_kokoro_local()
                with res_lock: results["ggml Whisper (Local)"] = txt

            def run_groq():
                txt = _transcribe_groq()
                with res_lock: results["Groq Whisper (Fast)"] = txt

            def run_google():
                txt = _transcribe_google()
                with res_lock: results["Google Speech (Free)"] = txt

            def run_hf():
                if self.hf_key:
                    txt = _transcribe_hf()
                    with res_lock: results["Hugging Face Whisper"] = txt

            threads.append(threading.Thread(target=run_kokoro))
            threads.append(threading.Thread(target=run_groq))
            threads.append(threading.Thread(target=run_google))
            if self.hf_key:
                threads.append(threading.Thread(target=run_hf))

            for t in threads: t.start()
            for t in threads: t.join()

            self.signals.multi_results.emit(results)
        else:
            if ("kokoro" in self.engine.lower()
                    or "ggml" in self.engine.lower()):
                out = _transcribe_kokoro_local()
            elif "groq" in self.engine.lower():
                out = _transcribe_groq()
            elif "google" in self.engine.lower():
                out = _transcribe_google()
            elif "hugging" in self.engine.lower():
                out = _transcribe_hf()
            else:
                out = _transcribe_openai()
            if stt_text_is_error(out):
                # Fail loudly on the error channel - never as a "transcript".
                # Pure silence transcribes to "" - say so instead of toasting
                # an empty bubble.
                msg = str(out).strip() or "*(no speech detected)*"
                self.signals.error.emit(msg)
            else:
                self.signals.single_result.emit(self.engine, out)

class AudioRecordSignals(QObject):
    finished = Signal(bytes)
    error = Signal(str)
    #: Live input level for a VU meter / voice-activity detection. This was
    #: declared on STTSignals but nothing ever emitted it, so no caller could
    #: show a live mic level. Emitted from the capture callback below.
    level = Signal(float)


class AudioRecordWorker(QThread):
    def __init__(self, parent=None, auto_stop_silence_ms: int = 0,
                 silence_threshold: float = 0.012,
                 min_record_ms: int = 300,
                 max_record_ms: int = 0):
        super().__init__(parent)
        self.setObjectName("cellium-rec")
        self.signals = AudioRecordSignals()
        self.is_recording = False
        self.sample_rate = 16000
        self.frames = []
        # 0 disables auto-stop, preserving the original push-to-talk behaviour.
        self.auto_stop_silence_ms = max(0, int(auto_stop_silence_ms))
        self.silence_threshold = float(silence_threshold)
        self.min_record_ms = max(0, int(min_record_ms))
        self.max_record_ms = max(0, int(max_record_ms))
        self._elapsed_ms = 0
        self._last_loud_ms = 0
        self._first_loud_ms = 0
        self._speech_detected = False
        self._ambient_floor = None
        self._tick = 0
        #: Loudest block seen in the current clip - the "did anyone actually
        #: speak?" evidence the VAD needs to skip empty turns.
        self.peak_rms = 0.0

    @property
    def has_speech(self) -> bool:
        """Did this clip ever rise above the gate?"""
        return bool(self._speech_detected or self.peak_rms >= self.silence_threshold)

    def run(self):
        if not HAS_SOUNDDEVICE:
            self.signals.error.emit("sounddevice is not installed in the python environment.")
            return
        self.is_recording = True
        self.frames = []
        self._elapsed_ms = 0
        self._last_loud_ms = 0
        self._first_loud_ms = 0
        self._speech_detected = False
        self._ambient_floor = None
        self._tick = 0
        self.peak_rms = 0.0
        chunk_ms = 0
        try:
            sample_rate = self.sample_rate
            block = int(sample_rate * 0.05)   # 50 ms per block

            def callback(indata, frames, time_info, status):
                if not self.is_recording:
                    return
                self.frames.append(bytes(indata))
                self._tick += 1
                chunk_ms = max(1, int(frames / sample_rate * 1000))
                self._elapsed_ms += chunk_ms
                # Measure vocal-band RMS (1st-order high-pass strips steady <200Hz fan hum)
                try:
                    arr = np.frombuffer(bytes(indata), dtype=np.int16).astype(np.float32) / 32768.0
                    if arr.size > 2:
                        hp = arr[1:] - 0.94 * arr[:-1]
                        rms = float(np.sqrt(np.mean(hp * hp)))
                    else:
                        rms = 0.0
                except Exception:
                    rms = 0.0
                if rms > self.peak_rms:
                    self.peak_rms = rms
                try:
                    self.signals.level.emit(rms)
                except Exception:
                    pass
                # Symmetric ambient floor tracking + 2-block speech burst confirmation
                if self.silence_threshold >= 0.99:
                    dyn_thr = self.silence_threshold
                else:
                    if self._ambient_floor is None:
                        self._ambient_floor = rms
                    elif not self._speech_detected:
                        self._ambient_floor = 0.90 * self._ambient_floor + 0.10 * rms
                    else:
                        self._ambient_floor = min(self._ambient_floor, 0.97 * self._ambient_floor + 0.03 * rms)
                    # Warmup first 3 blocks (150ms) so initial mic pop/fan doesn't false-trigger
                    if self._tick <= 3:
                        dyn_thr = 9.9
                    else:
                        dyn_thr = max(
                            self.silence_threshold * 0.85,
                            min(0.38, self._ambient_floor * 1.65 + 0.014),
                        )
                if rms >= dyn_thr:
                    self._loud_streak = getattr(self, "_loud_streak", 0) + 1
                    if not self._speech_detected and self._loud_streak >= 2:
                        self._speech_detected = True
                        self._first_loud_ms = self._elapsed_ms
                    if self._speech_detected:
                        self._last_loud_ms = self._elapsed_ms
                else:
                    self._loud_streak = 0
                if self.auto_stop_silence_ms:
                    if not self._speech_detected:
                        # Keep a rolling ~700ms pre-roll until speech starts
                        if len(self.frames) > 14:
                            del self.frames[:-14]
                        if self.max_record_ms and self._elapsed_ms >= self.max_record_ms * 3:
                            self.is_recording = False
                    else:
                        quiet_ms = self._elapsed_ms - self._last_loud_ms
                        spoken_ms = self._elapsed_ms - self._first_loud_ms
                        if (quiet_ms >= self.auto_stop_silence_ms
                                and spoken_ms >= self.min_record_ms):
                            self.is_recording = False
                        elif self.max_record_ms and spoken_ms >= self.max_record_ms:
                            self.is_recording = False

            with sd.RawInputStream(samplerate=self.sample_rate, channels=1,
                                   dtype='int16', callback=callback):
                while self.is_recording:
                    time.sleep(0.02)
        except Exception as e:
            self.signals.error.emit(f"Audio device error: {str(e)[:100]}")
            return

        if not self.frames:
            self.signals.error.emit("No audio recorded.")
            return

        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(b"".join(self.frames))
        self.signals.finished.emit(buf.getvalue())

    def stop(self):
        self.is_recording = False

# ------------------------------------------------------------------ Generation Worker
