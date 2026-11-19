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

def tts_gain_from_settings(settings) -> float:
    """Cel voice loudness: settings ``tts_volume`` 10–200, default 100.

    Over-100% uses a soft saturate (see :func:`apply_tts_gain`) so 200%
    is loud, not crunchy.
    """
    try:
        pct = float((settings or {}).get("tts_volume", 100))
    except (TypeError, ValueError):
        pct = 100.0
    return max(0.1, min(2.5, pct / 100.0))


def apply_tts_gain(samples, gain: float):
    """Multiply float32 mono samples by ``gain`` with soft saturation."""
    out = np.asarray(samples, dtype=np.float32) * float(gain)
    if float(gain) > 1.0:
        out = np.tanh(out)
    return np.clip(out, -1.0, 1.0).astype(np.float32)


class StreamPlayer:
    def __init__(self, sample_rate: int = 24000) -> None:
        self._sr = int(sample_rate)
        self._killed = False
        self._wrote = False
        self._extra_flags = True
        self._proc = self._spawn(self._extra_flags)
        self.ok = self._proc is not None

    def _cmd(self, extra: bool):
        if shutil.which("paplay"):
            cmd = ["paplay", "--raw", f"--rate={self._sr}", "--channels=1", "--format=s16le"]
            if extra:
                cmd += ["--latency-msec=300"]
            return cmd
        if shutil.which("aplay"):
            cmd = ["aplay", "-q", "-t", "raw", "-r", str(self._sr), "-c", "1", "-f", "S16_LE"]
            if extra:
                cmd += ["--buffer-size=131072", "--period-size=8192"]
            return cmd
        return None

    def _spawn(self, extra: bool):
        cmd = self._cmd(extra)
        if cmd is None:
            return None
        try:
            return subprocess.Popen(
                cmd, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,  # isolate process group
            )
        except OSError:
            return None

    def write(self, data: bytes) -> None:
        if self._proc is None or self._killed:
            return
        if not self._wrote and self._proc.poll() is not None and self._extra_flags:
            self._extra_flags = False
            self._proc = self._spawn(False)
            if self._proc is None:
                self.ok = False
                return
        try:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
            self._wrote = True
        except Exception:
            self.ok = False

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.stdin.close()
        except Exception:
            pass
        try:
            # Allow audio server (paplay/aplay) to finish draining audio buffer cleanly
            self._proc.wait(timeout=4.0)
        except Exception:
            try:
                self._proc.terminate()
            except Exception:
                self.kill()

    def kill(self) -> None:
        self._killed = True
        self.ok = False
        if self._proc is not None:
            try:
                self._proc.kill()
            except OSError:
                pass

class KokoroStreamingWorker(QObject):
    chunk_played = Signal(int, int)
    finished = Signal()
    error = Signal(str)

    def __init__(self, text: str, voice: str = "af_heart", speed: float = 1.0,
                 threads: int | None = None, volume: float = 1.0, parent=None):
        super().__init__(parent)
        self.text = text
        self.voice = voice
        self.speed = speed
        self.threads = threads
        self.volume = float(volume or 1.0)
        self._stop = threading.Event()
        self._player = None

    def stop(self):
        self._stop.set()
        if self._player:
            self._player.kill()

    def _put(self, q: queue.Queue, item) -> bool:
        while not self._stop.is_set():
            try:
                q.put(item, timeout=0.2)
                return True
            except queue.Full:
                continue
        return False

    def _writer(self, q: queue.Queue):
        self._player = StreamPlayer(24000)
        while not self._stop.is_set():
            try:
                item = q.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            sr, samples = item
            pcm = to_pcm(samples)
            if self._player and self._player.ok:
                self._player.write(pcm)
        if self._player:
            if self._stop.is_set():
                self._player.kill()
            else:
                self._player.close()

    def run(self):
        kokoro = get_kokoro(self.threads)
        if not kokoro:
            self.error.emit("Kokoro model files not found on disk!")
            self.finished.emit()
            return

        segments = segment_text(self.text)
        chunks = []
        for seg in segments:
            chunks.extend(chunk_text(seg))

        if not chunks:
            self.finished.emit()
            return

        audio_q = queue.Queue(maxsize=2)
        writer_thread = threading.Thread(target=self._writer, args=(audio_q,), daemon=True)
        writer_thread.start()

        try:
            total = len(chunks)
            for idx, ch in enumerate(chunks):
                if self._stop.is_set():
                    break
                samples, rate = kokoro.create(
                    ch, voice=self.voice, speed=self.speed, lang="en-us",
                    trim=True, sentence_pause=0.25, clause_pause=0.1
                )
                if samples is None or len(samples) == 0:
                    continue
                samples = np.asarray(samples, dtype=np.float32)
                sr = int(rate)
                samples = fade_edges(samples, sr)
                samples = apply_tts_gain(samples, self.volume)
                if idx < total - 1:
                    samples = np.concatenate(
                        [samples, np.zeros(int(sr * INTER_CHUNK_SILENCE_S), dtype=np.float32)]
                    )
                if not self._put(audio_q, (sr, samples)):
                    break
                self.chunk_played.emit(idx + 1, total)

            if not self._stop.is_set():
                self._put(audio_q, None)
            writer_thread.join(timeout=5)
        except Exception as e:
            self.stop()
            self.error.emit(str(e))
        finally:
            self.finished.emit()

class EdgeTTSStreamingWorker(QObject):
    finished = Signal()
    error = Signal(str)

    def __init__(self, text: str, voice: str = "en-US-JennyNeural", speed: float = 1.0, volume: float = 1.0, parent=None):
        super().__init__(parent)
        self.text = text
        self.voice = voice
        self.speed = speed
        self.volume = float(volume or 1.0)
        self._stop = threading.Event()
        self._proc = None

    def stop(self):
        self._stop.set()
        if self._proc:
            try:
                self._proc.kill()
            except OSError:
                pass

    def run(self):
        try:
            import edge_tts
            import asyncio
            import soundfile as sf
            import io

            rate_str = "+0%"
            if self.speed != 1.0:
                pct = int((self.speed - 1.0) * 100)
                rate_str = f"{pct:+d}%"

            async def _fetch():
                comm = edge_tts.Communicate(self.text, self.voice, rate=rate_str)
                audio_bytes = bytearray()
                try:
                    async for chunk in comm.stream():
                        if self._stop.is_set():
                            break
                        if chunk["type"] == "audio":
                            audio_bytes.extend(chunk["data"])
                finally:
                    # Properly close the internal aiohttp session to prevent
                    # "Unclosed client session" and "Event loop is closed" errors
                    try:
                        if hasattr(comm, 'session') and comm.session:
                            await comm.session.close()
                    except Exception:
                        pass
                    try:
                        if hasattr(comm, '_session') and comm._session:
                            await comm._session.close()
                    except Exception:
                        pass
                return audio_bytes

            # Always create a fresh event loop - asyncio.run() properly cleans
            # up the loop, pending tasks, and async generators on exit, which
            # prevents the "Task was destroyed but is pending" and
            # "RuntimeError: Event loop is closed" tracebacks.
            audio_data = asyncio.run(_fetch())
            if self._stop.is_set() or not audio_data:
                self.finished.emit()
                return

            data, sr = sf.read(io.BytesIO(audio_data), dtype="int16")
            if len(data.shape) > 1:
                data = data[:, 0]
            _f = np.asarray(data, dtype=np.float32) / 32768.0
            _f = apply_tts_gain(_f, self.volume)
            data = (_f * 32767.0).astype(np.int16)
            raw_bytes = data.tobytes()

            player = StreamPlayer(sr)
            self._proc = player._proc
            if player.ok and not self._stop.is_set():
                chunk_size = 4096
                for i in range(0, len(raw_bytes), chunk_size):
                    if self._stop.is_set():
                        break
                    player.write(raw_bytes[i:i+chunk_size])
                if not self._stop.is_set():
                    player.close()
                else:
                    player.kill()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()
