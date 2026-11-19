"""Always-on "Hey Cel" wake-word listener.

Battery- and quota-friendly by construction:

* The mic runs through the proven :class:`AudioRecordWorker`. A clip only
  reaches the speech model if it actually contains sound - silence is scored
  with a cheap RMS pass first, so an idle listener never spins Whisper.
* Transcription is forced to the **local** Kokoro Whisper engine: a wake word
  must not burn API quota.
* A cooldown stops one utterance from waking her twice, and ``stop()`` fully
  releases the microphone so Live Mode / push-to-talk can take it.

Toggle it from the 🎧 quick switch in the top bar; off means the mic is free.
"""

from __future__ import annotations

import array
import io
import re
import threading
import time
import wave
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

from .audio_stt import AudioRecordWorker, STTWorker

__all__ = ["WakeListener", "WAKE_PHRASES", "wav_rms", "matches_wake_phrase",
           "normalize", "resolve_oww_model"]

#: What Cel answers to. Whisper hears the phrase a few different ways, and a
#: wake word lives or dies on false negatives - bare "cel" is excluded on
#: purpose because it matches "cancel" / "cell".
WAKE_PHRASES = (
    "hey cel", "heycel", "hi cel", "hey cell", "hay cel",
    "okay cel", "ok cel", "yo cel", "aye cel",
    "okay cell", "ok cell", "okay sell", "ok sell",
    "hey sell", "hi cell", "hi sell", "yo cell", "yo sell",
    "okay sal", "ok sal", "hey sal", "okay shell", "hey shell",
    "okay self", "hey self", "okay cels", "hey cels",
    "okay phil", "hey phil", "o kay cel", "o k cel",
    "kay cel", "k cel", "okay seal", "hey seal",
    "okay so", "ok so", "i can sell", "i can say", "i can t sell",
    "i can t say", "acconsail", "and console", "a console",
    "okay sir", "hey sir", "okay still", "hey still",
)

_WAKE_PREFIXES = frozenset({
    "hey", "hi", "okay", "ok", "yo", "hay", "aye", "kay", "k", "oh",
})
_WAKE_TARGETS = frozenset({
    "cel", "cell", "sell", "sal", "shell", "self", "sells", "cells",
    "cels", "seul", "seal", "sil", "sol", "cal", "kal", "phil",
    "fell", "tell", "bell", "chelle", "selle", "so", "sir", "still",
    "console", "sail", "sale",
})


def normalize(text: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace."""
    t = re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def matches_wake_phrase(text: str, extra=None) -> bool:
    """True when ``text`` contains a wake phrase or close Whisper homophone."""
    t = normalize(text)
    if not t:
        return False
    phrases = list(WAKE_PHRASES)
    if extra:
        for raw in extra:
            n = normalize(raw)
            if n and n not in phrases:
                phrases.append(n)
                phrases.append(n.replace(" ", ""))
    if any(p in t for p in phrases):
        return True
    tokens = t.split()
    for i in range(len(tokens) - 1):
        if tokens[i] in _WAKE_PREFIXES and tokens[i + 1] in _WAKE_TARGETS:
            return True
    return False


def wav_rms(wav_bytes: bytes) -> float:
    """Normalised 0..1 RMS of a 16-bit PCM WAV - used as the cheap energy gate
    so silence never reaches the speech model."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        a = array.array("h")
        a.frombytes(raw)
        if not a:
            return 0.0
        acc = 0
        for v in a:
            acc += v * v
        return (acc / len(a)) ** 0.5 / 32768.0
    except Exception:
        return 0.0


class WakeListener(QObject):
    """Continuous mic -> (energy gate) -> local STT -> wake phrase."""

    heard = Signal(str)            # any transcribed utterance
    woken = Signal(str)            # the wake phrase matched
    error = Signal(str)
    listening_changed = Signal(bool)

    def __init__(self, parent: Optional[QObject] = None,
                 settings: Optional[dict] = None):
        super().__init__(parent)
        self.settings = settings if isinstance(settings, dict) else {}
        self.recorder: Optional[AudioRecordWorker] = None
        self.stt: Optional[STTWorker] = None
        self._retired_stt: list = []
        self._running = False
        self._stopping = False
        self._last_wake = 0.0
        self._oww = None
        self._engine = "whisper"

    # ── lifecycle ────────────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return self._running

    @property
    def engine_in_use(self) -> str:
        """Which backend is actually listening: openwakeword or whisper."""
        return self._engine if self._running else "off"

    def start(self) -> bool:
        if self._running:
            return False
        self._stopping = False
        # A previous scorer can still be winding down (stop() only waits 3 s).
        # Starting a second InputStream against the same mic fails, so reap
        # the old thread first instead of orphaning it.
        old = self._oww
        if old is not None:
            self._oww = None
            try:
                if old.isRunning():
                    old.wait(2000)
            except Exception:
                pass
        eng = _wake_engine(self.settings)
        if eng == "openwakeword":
            if self._spawn_oww():
                self._engine = "openwakeword"
            else:
                self._spawn_capture()
                if self.recorder is None:
                    return False
                self._engine = "whisper"
        else:
            self._spawn_capture()
            if self.recorder is None:
                return False
            self._engine = "whisper"
        self._running = True
        try:
            self.listening_changed.emit(True)
        except RuntimeError:
            pass
        return True

    def stop(self) -> None:
        """Stop capture and release the device. Safe to call repeatedly."""
        self._stopping = True
        self._running = False
        oww = self._oww
        self._oww = None
        if oww is not None:
            try:
                oww.request_stop()
            except Exception:
                pass
            try:
                if oww.isRunning():
                    oww.wait(3000)
            except Exception:
                pass
        rec = self.recorder
        self.recorder = None
        if rec is not None:
            self._disconnect(rec)
            try:
                if rec.is_recording:
                    rec.stop()
            except Exception:
                pass
            try:
                if rec.isRunning():
                    rec.wait(1500)
            except Exception:
                pass
        stt = self.stt
        self.stt = None
        for worker in ([stt] if stt is not None else []) + list(self._retired_stt):
            try:
                if worker is not None and worker.isRunning():
                    worker.requestInterruption()
                    worker.wait(3000)
            except Exception:
                pass
        self._retired_stt.clear()
        try:
            self.listening_changed.emit(False)
        except RuntimeError:
            pass

    def dispose(self) -> None:
        self.stop()

    # ── capture ──────────────────────────────────────────────────────────
    def _spawn_capture(self) -> None:
        base_thr = float(self.settings.get("wake_threshold", 0.012) or 0.012)
        try:
            from . import noise_gate
            thr = float(noise_gate.effective_gate(self.settings, base=base_thr, cap=0.28))
        except Exception:
            thr = max(0.006, base_thr)
        try:
            rec = AudioRecordWorker(
                auto_stop_silence_ms=650,
                silence_threshold=max(0.006, thr),
                min_record_ms=280,
                max_record_ms=3200,
            )
        except Exception as exc:
            self.error.emit(f"Mic unavailable: {exc}")
            return
        rec.signals.finished.connect(self._on_captured)
        rec.signals.error.connect(self._on_error)
        self.recorder = rec
        try:
            rec.start()
        except Exception as exc:
            self.recorder = None
            self.error.emit(f"Mic could not start: {exc}")

    def _disconnect(self, rec: AudioRecordWorker) -> None:
        try:
            rec.signals.finished.disconnect(self._on_captured)
            rec.signals.error.disconnect(self._on_error)
        except (RuntimeError, TypeError):
            pass

    def _respawn(self) -> None:
        if self._stopping or not self._running:
            return
        old = self.recorder
        self.recorder = None
        if old is not None:
            try:
                if old.isRunning():
                    old.wait(1500)
            except Exception:
                pass
        self._spawn_capture()

    def _on_error(self, msg: str) -> None:
        # A dead mic must not leave the listener believing it is still up.
        self._running = False
        try:
            self.error.emit(str(msg))
            self.listening_changed.emit(False)
        except RuntimeError:
            pass

    # ── energy gate -> STT -> wake ───────────────────────────────────────
    def _custom_phrases(self):
        """The user's own wake phrase ("Hey Cel" unless they named another).

        Plus anything the setup wizard learned: distinct ways the user's own
        mouth renders the phrase ("hey chell"), so accents stop being false
        negatives.
        """
        try:
            raw = self.settings.get("live_wake_phrase", "") or ""
        except Exception:
            return []
        out = []
        n = normalize(raw)
        if n:
            out.append(n)
        try:
            extra = self.settings.get("wake_phrase_variants") or []
            for v in extra:
                nv = normalize(v)
                if nv and nv not in out:
                    out.append(nv)
        except Exception:
            pass
        return out

    @staticmethod
    def _clip_has_voice_burst(wav_bytes: bytes) -> bool:
        """True only when the clip contains a modulated speech burst above steady fan noise.

        Steady fan noise has a flat envelope (p95 / p25 < 1.45), whereas
        speaking 'Okay Cel' creates a distinct syllable crest >= 1.55x.
        Checking this in 0.1ms prevents Whisper from EVER running on idle fan noise!
        """
        try:
            import numpy as np
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                raw = wf.readframes(wf.getnframes())
            y = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if y.size < 1600:
                return False
            hp = y[1:] - 0.94 * y[:-1]
            block = 800  # 50ms at 16kHz
            n = hp.size // block
            if n < 4:
                return True
            rms = np.sqrt(np.mean(hp[:n * block].reshape(n, block) ** 2, axis=1))
            p25 = float(np.percentile(rms, 25))
            p95 = float(np.percentile(rms, 95))
            if p95 < 0.006:
                return False
            return (p95 / max(p25, 0.0015)) >= 1.52
        except Exception:
            return True

    def _on_captured(self, wav_bytes: bytes) -> None:
        if self._stopping:
            return
        rec = self.recorder
        spoke = bool(getattr(rec, "has_speech", True)) if rec is not None else True
        if not spoke or not wav_bytes or not self._clip_has_voice_burst(wav_bytes):
            if self._engine == "whisper":
                self._respawn()
            return
        self._begin_transcription(wav_bytes)
        if self._engine == "whisper":
            self._respawn()

    def _release_stt(self, worker) -> None:
        if worker is None:
            return
        try:
            if worker.isRunning():
                if worker not in self._retired_stt:
                    self._retired_stt.append(worker)
                worker.finished.connect(lambda w=worker: self._drop_stt(w))
            else:
                worker.deleteLater()
        except RuntimeError:
            pass

    def _drop_stt(self, worker) -> None:
        try:
            if worker in self._retired_stt:
                self._retired_stt.remove(worker)
            worker.deleteLater()
        except RuntimeError:
            pass

    def _begin_transcription(self, wav_bytes: bytes) -> None:
        if self._stopping or not wav_bytes:
            return
        # Never stack overlapping Whisper threads - if one is still transcribing,
        # let it finish cleanly so QThread is never destroyed mid-flight!
        if self.stt is not None and self.stt.isRunning():
            return
        self._retired_stt = [w for w in self._retired_stt if w.isRunning()]
        if self._retired_stt:
            return
        try:
            # Forced local: the wake word must not spend API quota.
            stt = STTWorker(wav_bytes, engine="Kokoro Whisper (Local)",
                            multi_mode=False,
                            ggml_path=self.settings.get("stt_ggml_path", ""))
        except Exception as exc:
            self.error.emit(f"Wake transcription unavailable: {exc}")
            return
        prev, self.stt = self.stt, stt
        if prev is not None:
            self._release_stt(prev)
        stt.signals.single_result.connect(self._on_transcript)
        stt.signals.error.connect(self._on_stt_error)
        try:
            stt.start()
        except Exception as exc:
            self._release_stt(stt)
            self.stt = None
            self.error.emit(f"Wake transcription failed: {exc}")

    def _on_stt_error(self, msg: str) -> None:
        prev, self.stt = self.stt, None
        self._release_stt(prev)
        # Ignore silent clips; only forward real configuration errors.
        m = str(msg or "")
        if "no speech" not in m.lower() and "incomprehensible" not in m.lower():
            try:
                self.error.emit(m)
            except RuntimeError:
                pass

    def _on_transcript(self, sid: str, text: str) -> None:
        prev, self.stt = self.stt, None
        self._release_stt(prev)
        cleaned = (text or "").strip()
        if not cleaned:
            return
        try:
            from ..core.logger import dev_log
            dev_log(f"[Wake] Heard: {cleaned!r}")
        except Exception:
            pass
        try:
            self.heard.emit(cleaned)
        except RuntimeError:
            return
        if not matches_wake_phrase(cleaned, self._custom_phrases()):
            return
        now = time.monotonic()
        if now - self._last_wake < 4.5:
            return
        self._last_wake = now
        try:
            self.woken.emit(cleaned)
        except RuntimeError:
            pass

    # ── openWakeWord backend ─────────────────────────────────────────
    def _spawn_oww(self) -> bool:
        """Start the streaming scorer. False = fall back to Whisper."""
        model_path = resolve_oww_model(self.settings)
        if not model_path:
            return False
        try:
            import openwakeword  # noqa: F401
        except Exception:
            return False
        try:
            thr = float(self.settings.get("wake_oww_threshold", 0.4))
        except (TypeError, ValueError):
            thr = 0.4
        thr = max(0.05, min(0.95, thr))
        try:
            t = _OWWStreamThread(model_path, threshold=thr, parent=self)
        except Exception as exc:
            try:
                self.error.emit(f"Wake listener unavailable: {exc}")
            except RuntimeError:
                pass
            return False
        t.detected.connect(self._on_oww_detected)
        t.clip_captured.connect(self._on_captured)
        t.error.connect(self._on_oww_error)
        self._oww = t
        try:
            t.start()
        except Exception as exc:
            self._oww = None
            try:
                self.error.emit(f"Wake listener failed to start: {exc}")
            except RuntimeError:
                pass
            return False
        return True

    def _on_oww_detected(self, score: float) -> None:
        if self._stopping or not self._running:
            return
        now = time.monotonic()
        if now - self._last_wake < 4.5:
            return
        self._last_wake = now
        try:
            phrase = str(self.settings.get("live_wake_phrase", "")
                         or "Okay Cel")
        except Exception:
            phrase = "Okay Cel"
        for sig in (self.heard, self.woken):
            try:
                sig.emit(phrase)
            except RuntimeError:
                pass

    def _on_oww_error(self, msg: str) -> None:
        """If openWakeWord fails at runtime, seamlessly fall back to Whisper!"""
        self._oww = None
        if self._stopping:
            return
        try:
            from ..core.logger import dev_log
            dev_log(f"[Wake] OWW fallback to Whisper ({msg})")
        except Exception:
            pass
        self._spawn_capture()
        if self.recorder is not None:
            self._engine = "whisper"
            self._running = True
            try:
                self.listening_changed.emit(True)
            except RuntimeError:
                pass
            return
        self._running = False
        try:
            self.error.emit(str(msg))
            self.listening_changed.emit(False)
        except RuntimeError:
            pass


def _wake_models_dir() -> Path:
    """Folder the app looks in for wake-word .onnx models (created on demand)."""
    try:
        from ..core.config import ASSETS_DIR
        base = Path(ASSETS_DIR) / "wake"
    except Exception:
        base = (Path(__file__).resolve().parent.parent
                / "core" / "assets" / "wake")
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return base


def resolve_oww_model(settings) -> str:
    """Path to the openWakeWord .onnx model, or "" when none is configured.

    Explicit ``wake_oww_model`` wins; otherwise ``<phrase-slug>.onnx`` and
    then any ``*.onnx`` inside the wake-models folder.
    """
    try:
        explicit = str((settings or {}).get("wake_oww_model", "")
                       or "").strip()
    except Exception:
        explicit = ""
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file() and p.suffix.lower() == ".onnx":
            return str(p)
    try:
        base = _wake_models_dir()
    except Exception:
        return ""
    try:
        phrase = str((settings or {}).get("live_wake_phrase", "") or "Okay Cel")
        slug = re.sub(r"[^a-z0-9]+", "_", phrase.strip().lower()).strip("_")
        slug = slug or "hey_cel"
    except Exception:
        slug = "hey_cel"
    try:
        cand = base / f"{slug}.onnx"
        if cand.is_file():
            return str(cand)
        onnxes = sorted(base.glob("*.onnx"))
        if onnxes:
            return str(onnxes[0])
    except Exception:
        pass
    return ""


def _wake_engine(settings) -> str:
    """Which backend should listen: "openwakeword" or "whisper"."""
    try:
        eng = str((settings or {}).get("wake_engine", "") or "auto")
        eng = eng.strip().lower()
    except Exception:
        eng = "auto"
    if "openwake" in eng:
        return "openwakeword"
    if "whisper" in eng or "legacy" in eng:
        return "whisper"
    try:
        if resolve_oww_model(settings):
            return "openwakeword"
    except Exception:
        pass
    return "whisper"


class _OWWStreamThread(QThread):
    """Always-on mic -> openWakeWord scores + hybrid VAD clip fallback."""

    detected = Signal(float)
    clip_captured = Signal(bytes)
    error = Signal(str)

    def __init__(self, model_path, threshold: float = 0.5,
                 cooldown_s: float = 3.0, parent=None):
        super().__init__(parent)
        self.setObjectName("cellium-oww")
        self.model_path = str(model_path)
        self.threshold = float(threshold)
        self.cooldown_s = float(cooldown_s)
        self._stop_flag = threading.Event()

    def request_stop(self) -> None:
        self._stop_flag.set()

    @staticmethod
    def _patch_ort_providers() -> None:
        import warnings
        warnings.filterwarnings("ignore", message=r".*CUDAExecutionProvider.*", category=UserWarning)
        try:
            import onnxruntime as ort
            if not getattr(ort, "_cellium_provider_patched", False):
                _orig_init = ort.InferenceSession.__init__
                _avail = set(ort.get_available_providers())

                def _safe_init(self, path_or_bytes, sess_options=None, providers=None, **kw):
                    if providers:
                        filtered = [
                            p for p in providers
                            if (p[0] if isinstance(p, tuple) else p) in _avail
                        ] or ["CPUExecutionProvider"]
                        providers = filtered
                    else:
                        providers = ["CPUExecutionProvider"]
                    return _orig_init(self, path_or_bytes, sess_options=sess_options, providers=providers, **kw)

                ort.InferenceSession.__init__ = _safe_init
                ort._cellium_provider_patched = True
        except Exception:
            pass

    @staticmethod
    def _load_oww_model(OWWModel, path: str):
        _OWWStreamThread._patch_ort_providers()
        for kwargs in (
            {"wakeword_models": [path], "inference_framework": "onnx"},
            {"wakeword_model_paths": [path], "inference_framework": "onnx"},
            {"wakeword_models": [path]},
            {"wakeword_model_paths": [path]},
        ):
            try:
                return OWWModel(**kwargs)
            except TypeError:
                continue
        return OWWModel(wakeword_model_paths=[path])

    def run(self) -> None:
        try:
            from openwakeword.model import Model as OWWModel
        except Exception as exc:
            try:
                self.error.emit(f"openWakeWord not installed: {exc}")
            except RuntimeError:
                pass
            return
        try:
            import sounddevice as sd
        except Exception as exc:
            try:
                self.error.emit(f"Microphone unavailable: {exc}")
            except RuntimeError:
                pass
            return
        try:
            model = self._load_oww_model(OWWModel, self.model_path)
            key = next(iter(model.models.keys()))
        except Exception as exc:
            try:
                self.error.emit(f"Wake model failed to load: {exc}")
            except RuntimeError:
                pass
            return
        import queue
        frames: "queue.Queue[bytes]" = queue.Queue(maxsize=64)

        def _cb(indata, nframes, time_info, status):
            try:
                frames.put_nowait(bytes(indata))
            except queue.Full:
                pass

        try:
            stream = sd.InputStream(samplerate=16000, channels=1,
                                    dtype="int16", blocksize=1280,
                                    callback=_cb)
            stream.start()
        except Exception as exc:
            try:
                self.error.emit(f"Microphone unavailable: {exc}")
            except RuntimeError:
                pass
            return
        import numpy as np
        cooling = 0.0
        ambient_floor = None
        pre_roll: list[bytes] = []
        speech_frames: list[bytes] = []
        speaking = False
        silent_frames = 0
        try:
            while not self._stop_flag.is_set():
                try:
                    raw = frames.get(timeout=0.2)
                except queue.Empty:
                    continue
                chunk = np.frombuffer(raw, dtype=np.int16)
                if len(chunk) != 1280:
                    continue
                now = time.monotonic()
                oww_fired = False
                try:
                    scores = model.predict(chunk)
                    score = float(scores.get(key, 0.0))
                    if score >= self.threshold and now >= cooling:
                        cooling = now + self.cooldown_s
                        oww_fired = True
                        speaking = False
                        speech_frames.clear()
                        try:
                            self.detected.emit(score)
                        except RuntimeError:
                            pass
                except Exception:
                    pass
                if oww_fired or now < cooling:
                    continue
                # Hybrid adaptive VAD: if OWW missed a spoken phrase,
                # ship the short burst to local Whisper!
                rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) / 32768.0
                if ambient_floor is None:
                    ambient_floor = rms
                elif rms < ambient_floor:
                    ambient_floor = 0.75 * ambient_floor + 0.25 * rms
                elif not speaking:
                    ambient_floor = 0.95 * ambient_floor + 0.05 * rms
                dyn_thr = max(0.010, min(0.35, ambient_floor * 1.38 + 0.008))
                if rms >= dyn_thr:
                    if not speaking:
                        speaking = True
                        speech_frames = list(pre_roll)
                    speech_frames.append(raw)
                    silent_frames = 0
                    if len(speech_frames) >= 42:  # ~3.3s cap
                        speaking = False
                        self._emit_wav(speech_frames)
                        speech_frames = []
                else:
                    if speaking:
                        speech_frames.append(raw)
                        silent_frames += 1
                        if silent_frames >= 8:  # ~640ms pause
                            speaking = False
                            if len(speech_frames) >= 10:
                                self._emit_wav(speech_frames)
                            speech_frames = []
                            silent_frames = 0
                    else:
                        pre_roll.append(raw)
                        if len(pre_roll) > 8:
                            del pre_roll[:-8]
        finally:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def _emit_wav(self, pcm_frames: list[bytes]) -> None:
        try:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"".join(pcm_frames))
            self.clip_captured.emit(buf.getvalue())
        except Exception:
            pass
