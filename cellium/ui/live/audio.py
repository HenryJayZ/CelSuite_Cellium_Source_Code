"""Live Mode audio loop: mic → STT → transcript.

Captures continuously, uses the live input level for the VU meter and for
voice-activity detection, and emits a transcript when the speaker stops talking.

Reuses the existing, proven ``AudioRecordWorker`` and ``STTWorker`` - no new
capture or transcription code. Silence auto-stop is opt-in so the ordinary
push-to-talk mic button keeps its original behaviour.

Three hard rules, each learned from a real crash or a real silence:

* **Never delete a running QThread.** ``deleteLater()`` on a thread that has
  not finished makes Qt abort the entire process ("QThread: Destroyed while
  thread '' is still running"). Holding the push-to-talk key in a stutter
  created more finished-but-still-running STT workers than the old hard cap of
  four, and the cap force-deleted one mid-flight. Finished workers now wait in
  ``_retired_stt``, only *stopped* ones are ever deleted, and anything still
  winding down is parked in ``_graveyard`` until its own ``finished`` fires.
* **A bounded number of transcriptions.** Hammering push-to-talk used to spawn
  a thread per press until Qt aborted the process. Once three are alive the
  new clip is dropped with a word on screen instead of piling up more.
* **The mic closes while she answers.** With push-to-talk off the mic used to
  stay open for the whole call, so the recorder heard Cel's own voice and
  transcribed it back as your words.
"""

from __future__ import annotations

import time
import warnings
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

from ...core.config import stt_missing_key
from ...services.audio_stt import AudioRecordWorker, STTWorker

__all__ = ["LiveAudio"]

#: Retained finished STT workers we *aim* to keep. Only stopped ones are ever
#: evicted, so this is a target and not a cliff.
_RETIRED_SOFT_CAP = 4
#: Hard ceiling on workers alive at once (in flight + winding down + parked).
#: Past it, new audio is refused instead of piling up more threads - this is
#: the difference between a dropped word and an aborted process.
_MAX_PENDING_STT = 3


class LiveAudio(QObject):
    """Continuous mic -> transcript pipeline for CelAS Live Mode."""

    level = Signal(float)              # 0..1 live input level
    transcript = Signal(str)           # final text for this turn
    partial_transcript = Signal(str)   # interim/partial text (if supported)
    error = Signal(str)
    listening_changed = Signal(bool)
    busy = Signal(bool)                # True while transcribing
    #: (engine, provider) - the selected engine needs an API key it does not
    #: have. Raised *before* the mic opens, so a call can never record you
    #: only to hand the failure to the model as your words.
    key_required = Signal(str, str)
    #: Something worth telling the user that is *not* an error and must never
    #: reach the model ("hold to talk for longer").
    hint = Signal(str)

    def __init__(self, parent: Optional[QObject] = None,
                 settings: Optional[dict] = None,
                 silence_ms: int = 2000,
                 threshold: float = 0.012,
                 min_record_ms: int = 400,
                 min_hold_ms: int = 250):
        super().__init__(parent)
        self.settings = settings if isinstance(settings, dict) else {}
        self.silence_ms = max(200, int(silence_ms))
        self.threshold = float(threshold)
        self.min_record_ms = max(0, int(min_record_ms))
        #: A tap is not a hold. Shorter than this and the clip is thrown away
        #: instead of being transcribed into silence.
        self.min_hold_ms = max(0, int(min_hold_ms))

        self.recorder: Optional[AudioRecordWorker] = None
        self.stt: Optional[STTWorker] = None
        #: Finished-but-still-running STT workers. Their result signal is
        #: emitted from *inside* run(), so the slot that receives it runs while
        #: the thread is still live - dropping the last reference there is
        #: what aborted the process on hang-up.
        self._retired_stt: list = []
        #: Workers that were asked to stop and did not. Never deleted; their own
        #: ``finished`` signal deletes them. See the module docstring.
        self._graveyard: list = []
        self._running = False
        self._stopping = False
        self._ptt_active = False
        self._ptt_started = 0.0
        self._muted = False
        self._push_to_talk = False
        self._auto_send = True
        #: Whether the call *wants* the mic open right now. Cel thinking or
        #: speaking flips this off; see :meth:`set_capture_enabled`.
        self._capture_enabled = False

    # ── lifecycle ────────────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return self._running

    @property
    def push_to_talk(self) -> bool:
        return self._push_to_talk

    @push_to_talk.setter
    def push_to_talk(self, val: bool) -> None:
        self._push_to_talk = bool(val)
        if self._push_to_talk and self._running and not self._ptt_active:
            self.stop()
            self._stopping = False

    @property
    def auto_send(self) -> bool:
        return self._auto_send

    @auto_send.setter
    def auto_send(self, val: bool) -> None:
        self._auto_send = bool(val)

    @property
    def muted(self) -> bool:
        return self._muted

    @property
    def capture_enabled(self) -> bool:
        return self._capture_enabled

    def set_capture_enabled(self, on: bool) -> None:
        """Hold the mic closed while Cel is thinking or speaking."""
        on = bool(on)
        if on == self._capture_enabled:
            return
        self._capture_enabled = on
        if on:
            self._open_capture()
        else:
            self._close_capture()

    def set_muted(self, muted: bool) -> None:
        """Mute/unmute the microphone without leaving live mode."""
        self._muted = bool(muted)
        if self._muted and self._running:
            self.stop()
        elif not self._muted and self._push_to_talk:
            pass
        elif not self._muted and not self._running:
            self._open_capture()

    def start(self) -> bool:
        if self._running or self._muted:
            return False
        parent = self.parent()
        if parent is not None and not getattr(parent, "active", False):
            return False
        if not self._capture_enabled:
            return False
        if self._push_to_talk and not self._ptt_active:
            return False
        # ── Credential pre-flight ────────────────────────────────────────
        # Groq ships as the default engine and needs a key nobody has. The
        # old flow recorded you, transcribed into the literal string
        # "❌ No Groq API Key", and auto-sent that to the model. Ask first.
        gap = self.key_gap()
        if gap is not None:
            engine = str(self.settings.get("voice_stt_engine", ""))
            self.key_required.emit(engine, gap[0])
            self.error.emit(f"{gap[0]} needs an API key - speech input is off.")
            return False
        self._stopping = False
        rec = self._make_recorder()
        if rec is None:
            return False
        self.recorder = rec
        rec.signals.finished.connect(self._on_captured)
        rec.signals.error.connect(self._on_error)
        rec.signals.level.connect(self._on_level)
        try:
            rec.start()
        except Exception as exc:
            self.error.emit(f"Could not start microphone: {exc}")
            self.recorder = None
            self._retire(rec)
            return False
        self._running = True
        self.listening_changed.emit(True)
        return True

    def _open_capture(self) -> None:
        """Open the mic if the call wants it and nothing is in the way."""
        if self._stopping or not self._capture_enabled:
            return
        if self._muted or self._running:
            return
        parent = self.parent()
        if parent is not None and not getattr(parent, "active", False):
            return
        if self._push_to_talk and not self._ptt_active:
            return
        self.start()

    def _close_capture(self) -> None:
        """Close just the mic. Any transcription in flight is left alone."""
        if not self._running and self.recorder is None:
            return
        self._running = False
        rec = self.recorder
        self.recorder = None
        self._retire(rec)
        try:
            self.listening_changed.emit(False)
        except RuntimeError:
            pass

    def _silence_window_ms(self) -> int:
        """How long near-silence ends a turn.

        Settings win. The default is 2 s because 900 ms lands in the middle of
        ordinary sentences ("...and *then* I went...") and cuts you off.
        """
        try:
            return max(400, int(self.settings.get("live_silence_ms", 2000)))
        except (TypeError, ValueError):
            return 2000

    def _effective_threshold(self) -> float:
        """The gate that separates *you talking* from *the room being quiet*.

        A flat 0.012 only works in a silent room. user's own calibration
        measured a floor of 0.137 RMS (a steady fan, loudest block 0.147), so
        a 0.012 gate meant the recorder **never saw a quiet second** - the
        auto-stop could not fire, ever, and live mode looked dead. The gate now
        clears the room's own loudest background (scaled by the strength
        slider) instead of being a magic number nobody can tune.
        """
        try:
            from ...services import noise_gate
            return float(noise_gate.effective_gate(self.settings,
                                                   base=self.threshold))
        except Exception:
            return max(0.006, min(self.threshold, 0.40))

    def _make_recorder(self):
        """Build a recorder wired to the *current* silence rules."""
        try:
            silence_ms = 0 if self._push_to_talk else self._silence_window_ms()
            return AudioRecordWorker(
                auto_stop_silence_ms=silence_ms,
                silence_threshold=self._effective_threshold(),
                min_record_ms=self.min_record_ms,
            )
        except Exception as exc:
            self.error.emit(f"Microphone unavailable: {exc}")
            return None

    def stop(self) -> None:
        """Full stop - hang up. Mic, transcription and every retained worker."""
        self._stopping = True
        self._running = False
        self._ptt_active = False
        rec = self.recorder
        self.recorder = None
        self._retire(rec)
        stt = self.stt
        self.stt = None
        if stt is not None:
            self._shutdown_worker(stt)
        # Anything still winding down from earlier turns goes too.
        for old in list(self._retired_stt) + list(self._graveyard):
            self._shutdown_worker(old)
        try:
            self.listening_changed.emit(False)
        except RuntimeError:
            pass

    # ── worker lifetime ──────────────────────────────────────────────────
    def _park(self, worker) -> None:
        """Keep a still-running worker alive until its own ``finished`` fires.

        This is the whole point of the module: deleting a QThread that has not
        stopped makes Qt abort the process. Nothing here ever terminates a
        thread - ``terminate()`` on a live QThread is the same crash wearing a
        different hat.
        """
        if worker is None:
            return
        try:
            if getattr(worker, "_cellium_parked", False):
                return
            setattr(worker, "_cellium_parked", True)
            if worker not in self._graveyard:
                self._graveyard.append(worker)
            worker.finished.connect(lambda s=worker: self._forget(s))
        except RuntimeError:
            pass

    def _forget(self, worker) -> None:
        """A parked worker's thread finally ended - now it is safe to delete."""
        if worker is None:
            return
        try:
            for lst in (self._graveyard, self._retired_stt):
                if worker in lst:
                    lst.remove(worker)
            if worker.isRunning():
                self._park(worker)
                return
            worker.deleteLater()
        except RuntimeError:
            pass

    def _drop_stt(self, worker) -> None:
        """Release a worker, deleting it only once its thread has stopped."""
        if worker is None:
            return
        try:
            for lst in (self._retired_stt, self._graveyard):
                if worker in lst:
                    lst.remove(worker)
            if worker.isRunning():
                self._park(worker)
                return
            worker.deleteLater()
        except RuntimeError:
            pass

    def _release_stt(self, worker) -> None:
        """Keep a finished STT worker alive until its thread has really stopped.

        ``single_result``/``error`` are emitted from inside ``run()``, so the
        receiving slot executes *while the worker thread is still running*.
        Letting it be collected at that moment is exactly what printed
        "QThread: Destroyed while thread '' is still running" and took the app
        down on hang-up.
        """
        if worker is None:
            return
        try:
            if worker.isRunning():
                if getattr(worker, "_cellium_releasing", False):
                    return
                setattr(worker, "_cellium_releasing", True)
                self._retired_stt.append(worker)
                worker.finished.connect(lambda s=worker: self._drop_stt(s))
                self._evict_stopped()
            else:
                worker.deleteLater()
        except RuntimeError:
            pass

    def _evict_stopped(self) -> None:
        """Trim the retention list - stopped workers only, never running ones."""
        for w in list(self._retired_stt):
            if len(self._retired_stt) <= _RETIRED_SOFT_CAP:
                break
            try:
                if not w.isRunning():
                    self._retired_stt.remove(w)
                    w.deleteLater()
            except RuntimeError:
                continue

    def _shutdown_worker(self, worker) -> None:
        """Ask one worker to wind down; park it if it will not."""
        if worker is None:
            return
        try:
            if worker.isRunning():
                try:
                    worker.requestInterruption()
                except Exception:
                    pass
                if not worker.wait(1200):
                    self._park(worker)
                    return
            self._drop_stt(worker)
        except Exception:
            pass

    def _pending_workers(self) -> int:
        """STT threads alive right now: in flight, winding down or parked."""
        n = len(self._retired_stt) + len(self._graveyard)
        if self.stt is not None:
            n += 1
        return n

    def _retire(self, rec) -> None:
        """Detach *and join* a recorder before dropping it.

        Three real bugs lived here. A still-connected old recorder kept firing
        ``finished`` into this object, so a late capture hijacked the next one
        and the pipeline lost turns. Dropping a running QThread makes Python
        abort the whole process. And ``terminate()`` on a thread that is inside
        a sounddevice callback does the same thing more violently. So:
        disconnect, stop, wait briefly, and park anything still alive.
        """
        if rec is None:
            return
        try:
            for sig, slot in ((rec.signals.finished, self._on_captured),
                              (rec.signals.error, self._on_error),
                              (rec.signals.level, self._on_level)):
                try:
                    # PySide6 *warns* instead of raising when a slot was never
                    # connected; left alone that prints a RuntimeWarning per
                    # signal on every retire.
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            if rec.is_recording:
                rec.stop()
            if rec.isRunning():
                if not rec.wait(1500):
                    self._park(rec)
                    return
            rec.deleteLater()
        except Exception:
            pass

    def start_listening(self) -> bool:
        """Open the mic for a hold. False = nothing opened (muted/no key/busy)."""
        if self._running or self._muted or not self._push_to_talk:
            return False
        self._ptt_active = True
        self._ptt_started = time.monotonic()
        return self.start()

    def stop_listening(self) -> None:
        """Release the key: finish the clip and *transcribe it*.

        This used to call ``stop()``, which detached the recorder and threw
        the captured audio away - push-to-talk therefore could never produce a
        transcript, in any engine, ever. Finishing the recorder instead lets
        ``_on_captured`` run, which is the only path that transcribes.
        """
        if not self._ptt_active:
            return
        self._ptt_active = False
        rec = self.recorder
        held_ms = (time.monotonic() - self._ptt_started) * 1000.0
        if rec is not None and held_ms < self.min_hold_ms:
            # A tap, not a hold. Transcribing 80 ms of room tone yields an
            # empty turn, which from the outside is a button that does nothing.
            # Drop it and say why.
            self._running = False
            self.recorder = None
            self._retire(rec)
            try:
                self.listening_changed.emit(False)
            except RuntimeError:
                pass
            self.hint.emit("Hold to talk - keep holding while you speak.")
            return
        if rec is not None:
            try:
                if rec.is_recording:
                    rec.stop()      # run() packs the wav and emits finished()
                    return
            except Exception:
                pass
        self.stop()

    def dispose(self) -> None:
        self.stop()

    def toggle_mute(self) -> bool:
        self.set_muted(not self._muted)
        return self._muted

    def key_gap(self):
        """``(provider, hint)`` when the selected engine has no key, else None."""
        try:
            return stt_missing_key(
                self.settings.get("voice_stt_engine", ""), self.settings)
        except Exception:
            return None

    # ── signals ──────────────────────────────────────────────────────────
    def _on_level(self, rms: float) -> None:
        if not self._running:
            return
        self.level.emit(rms)

    def _on_error(self, msg: str) -> None:
        self.error.emit(str(msg))
        self._running = False
        try:
            self.listening_changed.emit(False)
        except RuntimeError:
            pass

    # ── capture → transcription ──────────────────────────────────────────
    def _on_captured(self, wav_bytes: bytes) -> None:
        if self._stopping:
            return
        # The recorder that produced this clip is done - hand it to Qt instead
        # of leaving it referenced (and collectable while still winding down).
        done = self.recorder
        self.recorder = None
        spoke = True
        try:
            if done is not None:
                spoke = bool(getattr(done, "has_speech", True))
                self._retire(done)
        except RuntimeError:
            pass
        if self._push_to_talk:
            self._ptt_active = False
            self._running = False
            self.listening_changed.emit(False)
        else:
            self._respawn_capture()
        if not spoke:
            # The whole point of the silence timer: two seconds of nothing is
            # not a sentence. Stay quiet instead of spending an API call to be
            # told the user said nothing.
            return
        self._begin_transcription(wav_bytes)

    def _respawn_capture(self) -> None:
        if self._stopping or not self._running or self._push_to_talk:
            return
        if not self._capture_enabled:
            return
        self._retire(self.recorder)
        self.recorder = None
        rec = self._make_recorder()
        if rec is None:
            return
        rec.signals.finished.connect(self._on_captured)
        rec.signals.error.connect(self._on_error)
        rec.signals.level.connect(self._on_level)
        self.recorder = rec
        try:
            rec.start()
        except Exception:
            self.recorder = None

    def _begin_transcription(self, wav_bytes: bytes) -> None:
        if self._stopping or not wav_bytes:
            return
        if self._pending_workers() >= _MAX_PENDING_STT:
            # Hammering push-to-talk used to spawn a thread per press until
            # Qt aborted the process. One in flight is plenty; the rest are
            # dropped with a word on screen instead of a crash.
            self.hint.emit("Still transcribing the last one - one moment.")
            return
        s = self.settings
        try:
            stt = STTWorker(
                wav_bytes,
                engine=s.get("voice_stt_engine", "Kokoro Whisper (Local)"),
                # A call needs ONE engine. Multi-engine mode reports on
                # ``multi_results`` - which nothing in Live Mode listens to,
                # so honouring it made every live turn silently vanish.
                multi_mode=False,
                groq_key=s.get("user_custom_keys", {}).get("Groq", ""),
                openai_key=s.get("user_custom_keys", {}).get("Custom (OpenAI)", ""),
                hf_key=s.get("user_custom_keys", {}).get("Hugging Face", ""),
                ggml_path=s.get("stt_ggml_path", ""),
            )
        except Exception as exc:
            self.error.emit(f"Transcription unavailable: {exc}")
            return
        # Never overwrite the in-flight worker while it is still running: the
        # old reference was its last one, so Python would collect a live
        # QThread and Qt would abort the process. This single line was the
        # crash behind "spam the push-to-talk key and the app dies".
        prev, self.stt = self.stt, None
        if prev is not None:
            self._release_stt(prev)
        self.stt = stt
        self.busy.emit(True)
        # Bound to the worker that produced it, so a late result from an
        # overtaken turn cannot clear the current turn's state.
        stt.signals.single_result.connect(
            lambda eng, txt, w=stt: self._on_transcript(eng, txt, w))
        stt.signals.error.connect(
            lambda msg, w=stt: self._on_stt_error(msg, w))
        try:
            stt.start()
        except Exception as exc:
            self.busy.emit(False)
            self._release_stt(stt)
            self.stt = None
            self.error.emit(f"Transcription failed to start: {exc}")

    def _on_transcript(self, engine: str, text: str, worker=None) -> None:
        # A superseded worker (its turn was overtaken by a newer one) still
        # hands its words over - dropping them loses what the user said - but
        # only the *current* worker may clear the in-flight state.
        if worker is None or worker is self.stt:
            self.busy.emit(False)
            stt, self.stt = self.stt, None
            self._release_stt(stt)
        else:
            self._release_stt(worker)
        cleaned = (text or "").strip()
        if cleaned:
            self.transcript.emit(cleaned)

    def _on_stt_error(self, msg: str, worker=None) -> None:
        if worker is None or worker is self.stt:
            self.busy.emit(False)
            stt, self.stt = self.stt, None
            self._release_stt(stt)
        else:
            self._release_stt(worker)
        self.error.emit(str(msg))


# ── #8: Apply Calibrated Noise Gate & STFT Denoiser in LiveAudio ─────────────
from cellium.services import noise_gate as _ng

_orig_la_on_rec_done = getattr(LiveAudio, "_on_record_done", None) or getattr(LiveAudio, "_on_captured", None)
if _orig_la_on_rec_done is not None:
    _fn_name = "_on_record_done" if hasattr(LiveAudio, "_on_record_done") else "_on_captured"
    def _denoised_la_on_captured(self, wav_bytes: bytes):
        if wav_bytes:
            try:
                _ng.configure(getattr(self, "settings", {}) or {})
                wav_bytes = _ng.denoise(wav_bytes)
            except Exception:
                pass
        return _orig_la_on_rec_done(self, wav_bytes)
    setattr(LiveAudio, _fn_name, _denoised_la_on_captured)
