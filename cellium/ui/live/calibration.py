"""First-run voice calibration for the "Hey Cel" wake word.

Records three short samples of you saying the phrase, measures the *actual*
speech level on this microphone, and stores a threshold a little below the
quietest sample. A generic 0.012 either misses soft speech or fires on a
keyboard - which is exactly why the wake word has to be taught once.

Nothing leaves the machine: only RMS levels are measured, and the samples are
discarded after each read.
"""

from __future__ import annotations

import math
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ...core.config import ASSETS_DIR
from ...services import noise_gate
from ...services.audio_stt import AudioRecordWorker, STTWorker
from ...services.wake import (
    WakeListener, matches_wake_phrase, normalize, wav_rms,
)

__all__ = ["HeyCelWizardDialog", "WakeCalibrationDialog", "NoiseCalibrationDialog"]

#: Below this a clip is "silence that happened to reach the auto-stop" - not
#: someone saying the phrase - so it is retried rather than counted.
_TOO_QUIET = 0.005

_STEPS = 3


class _LevelBar(QWidget):
    """Live mic level during a sample."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self._level = 0.0
        self.setStyleSheet(
            "background: rgba(255,255,255,0.10); border-radius: 4px;")

    def set_level(self, rms: float, floor: float = 0.0) -> None:
        """Show the level *above* the room floor.

        Raw RMS x12 pinned this bar at 100% for the entire calibration on any
        machine with a fan (floor 0.137 RMS) - the meter looked broken and the
        whole wizard felt dead. Subtracting the calibrated floor is what makes
        it move with your voice.
        """
        try:
            v = max(0.0, float(rms or 0.0) - max(0.0, float(floor or 0.0)))
        except (TypeError, ValueError):
            v = 0.0
        self._level = max(0.0, min(1.0, v * 12.0))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(self.rect(), 4, 4)
        w = int(self.width() * self._level)
        if w > 2:
            p.setBrush(QColor("#C084FC"))
            p.drawRoundedRect(0, 0, w, self.height(), 4, 4)
        p.end()


class _StepDots(QWidget):
    """Three progress pips - one per recorded sample."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(88, 14)
        self.done = 0
        self.active = 0

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(_STEPS):
            x = i * 32
            if i < self.done:
                p.setBrush(QColor("#6EE7B7"))
            elif i == self.active:
                p.setBrush(QColor("#C084FC"))
            else:
                p.setBrush(QColor(255, 255, 255, 45))
            p.drawEllipse(x, 2, 12, 12)
        p.end()


_PRIMARY_QSS = """
QPushButton {
    background: rgba(147, 51, 234, 0.75); color: #F8F4FF;
    border: 1.5px solid #A855F7; border-radius: 20px;
    padding: 10px 26px; font-weight: bold; font-size: 14px;
}
QPushButton:hover { background: #9333EA; }
"""

_SECONDARY_QSS = """
QPushButton {
    background: transparent; color: rgba(233, 213, 255, 0.7);
    border: 1.5px solid rgba(192, 132, 252, 0.35); border-radius: 20px;
    padding: 10px 22px; font-size: 13px;
}
QPushButton:hover { color: #FFFFFF; border-color: #C084FC; }
"""


class WakeCalibrationDialog(QDialog):
    """Teach Cel the level of "Hey Cel" on this microphone."""

    def __init__(self, settings: Optional[dict] = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.settings = settings if isinstance(settings, dict) else {}
        self.samples: List[float] = []
        self._rec: Optional[AudioRecordWorker] = None
        self._retries = 0
        self._closing = False
        self._peak = 0.0

        self.setWindowTitle("Hey Cel - voice calibration")
        self.setModal(True)
        self.setMinimumSize(520, 420)
        self.setStyleSheet(
            "WakeCalibrationDialog{background: rgba(8, 4, 20, 0.97);"
            "border: 1.5px solid rgba(168, 85, 247, 0.55);}"
            "QLabel{background: transparent; border: none;}")

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 26)
        root.setSpacing(14)

        title = QLabel("🎙  Teach Cel your voice")
        title.setStyleSheet("color: #F4F1FF; font-size: 22px; font-weight: bold;")
        root.addWidget(title)

        self.hint = QLabel(
            "Say “Hey Cel” out loud three times, the way you'd actually call "
            "me. I'll learn how loud your mic gets so the wake word fires on "
            "you - and not on the keyboard.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: rgba(233, 213, 255, 0.75); font-size: 14px;")
        root.addWidget(self.hint)

        self.prompt = QLabel("Get ready…")
        self.prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prompt.setStyleSheet(
            "color: #C084FC; font-size: 18px; font-weight: bold; margin: 12px 0 2px 0;")
        root.addWidget(self.prompt)

        self.vu = _LevelBar(self)
        root.addWidget(self.vu)

        # ── Noise cancellation ──────────────────────────────────────────
        # This wizard used to paint raw mic level behind a flat 0.006 gate,
        # so on a machine with a fan the meter sat pinned at 100% and the
        # "silence after you" it waited for never arrived. It now measures
        # against the same room profile the app subtracts everywhere else, and
        # the strength is adjustable right here.
        noise_box = QFrame(self)
        noise_box.setStyleSheet(
            "QFrame{background: rgba(110, 231, 183, 0.07);"
            "border: 1px solid rgba(110, 231, 183, 0.30); border-radius: 12px;}"
            "QLabel{background: transparent; border: none;}")
        nb = QVBoxLayout(noise_box)
        nb.setContentsMargins(12, 9, 12, 9)
        nb.setSpacing(6)
        self.lbl_noise = QLabel("")
        self.lbl_noise.setWordWrap(True)
        self.lbl_noise.setStyleSheet(
            "color: rgba(167, 243, 208, 0.9); font-size: 11px;")
        nb.addWidget(self.lbl_noise)
        nrow = QHBoxLayout()
        nrow.setSpacing(8)
        lbl_n = QLabel("Cancellation strength:")
        lbl_n.setStyleSheet(
            "color: rgba(233, 213, 255, 0.8); font-size: 12px;")
        nrow.addWidget(lbl_n)
        self.slider_noise = QSlider(Qt.Orientation.Horizontal)
        self.slider_noise.setRange(0, 100)
        # Start from the preference already saved - but 0 when there is no room
        # profile, because a quiet machine needs no cancellation at all.
        self.slider_noise.setValue(
            int(self.settings.get("noise_cancel_strength", 70))
            if self._has_profile() else 0)
        self.slider_noise.setFixedWidth(150)
        self.lbl_noise_val = QLabel(f"{self.slider_noise.value()}%")
        self.lbl_noise_val.setStyleSheet("color: #6EE7B7; font-weight: bold;")
        self.slider_noise.valueChanged.connect(self._on_strength)
        nrow.addWidget(self.slider_noise, 1)
        nrow.addWidget(self.lbl_noise_val)
        nb.addLayout(nrow)
        self.btn_room = QPushButton("🧹 Calibrate my room first")
        self.btn_room.setStyleSheet(
            _SECONDARY_QSS.replace("#C084FC", "#34D399")
                        .replace("rgba(233, 213, 255, 0.7)", "#D1FAE5"))
        self.btn_room.setToolTip(
            "Listen to a few seconds of your quiet room and store it as the "
            "profile Cel subtracts - that is what makes the meter meaningful.")
        self.btn_room.clicked.connect(self._calibrate_room)
        nb.addWidget(self.btn_room)
        root.addWidget(noise_box)
        self._sync_noise_label()

        self.dots = _StepDots(self)
        dots_row = QHBoxLayout()
        dots_row.addStretch(1)
        dots_row.addWidget(self.dots)
        dots_row.addStretch(1)
        root.addLayout(dots_row)
        root.addStretch(1)

        btn_row = QHBoxLayout()
        self.btn_skip = QPushButton("Skip for now")
        self.btn_skip.setStyleSheet(_SECONDARY_QSS)
        self.btn_skip.clicked.connect(self.reject)
        self.btn_primary = QPushButton("Start")
        self.btn_primary.setStyleSheet(_PRIMARY_QSS)
        self.btn_primary.clicked.connect(self._on_primary)
        btn_row.addWidget(self.btn_skip)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_primary)
        root.addLayout(btn_row)

        self._started = False

    # ── noise cancellation ───────────────────────────────────────────
    def _has_profile(self) -> bool:
        try:
            return bool(noise_gate.has_profile())
        except Exception:
            return False

    def _floor(self) -> float:
        """The room floor this wizard measures against.

        The *whole* saved profile, not a strength-scaled slice of it: the
        wizard's job is "did I hear you *above* my room", so a fan that sits at
        the profile level must read as silence instead of as a half-full bar.
        """
        if not self._has_profile():
            return 0.0
        try:
            return noise_gate.profile_rms()
        except Exception:
            return 0.0

    def _gate(self) -> float:
        """Silence gate for this recorder - the same rule a live call uses."""
        try:
            return noise_gate.effective_gate(self.settings, base=0.006,
                                             cap=0.25)
        except Exception:
            return 0.006

    def _sync_noise_label(self) -> None:
        try:
            if self._has_profile():
                self.lbl_noise.setText(
                    f"✅ Using your saved room profile (floor "
                    f"{noise_gate.profile_rms():.3f}). The bar shows what is "
                    "left after cancellation.")
                self.btn_room.setText("🧹 Re-calibrate my room")
            else:
                self.lbl_noise.setText(
                    "⚠️ No room profile yet - the bar shows raw mic level, so a "
                    "noisy PC pins it at 100%. Calibrate for a meter that means "
                    "something (0% is fine on a quiet machine).")
                self.btn_room.setText("🧹 Calibrate my room first")
        except (RuntimeError, AttributeError):
            pass

    def _on_strength(self, v: int) -> None:
        try:
            self.lbl_noise_val.setText(f"{v}%")
        except RuntimeError:
            pass

    def _calibrate_room(self) -> None:
        """Run the room calibrator inline - the same dialog Settings uses."""
        try:
            dlg = NoiseCalibrationDialog(self.settings, self)
            dlg.exec()
        except Exception as exc:
            self._fail(f"Couldn't calibrate the room: {exc}")
            return
        # The calibrator wrote straight into the shared settings dict.
        try:
            self.slider_noise.blockSignals(True)
            self.slider_noise.setValue(int(self.settings.get(
                "noise_cancel_strength", self.slider_noise.value())))
            self.slider_noise.blockSignals(False)
            self._on_strength(self.slider_noise.value())
            self._sync_noise_label()
        except RuntimeError:
            pass

    def _on_level(self, rms: float) -> None:
        """Meter follows the mic with the room floor subtracted."""
        try:
            self._peak = max(self._peak, float(rms or 0.0))
            self.vu.set_level(rms, floor=self._floor())
        except Exception:
            pass

    # ── flow ─────────────────────────────────────────────────────────────
    def _on_primary(self) -> None:
        if self.samples and len(self.samples) >= _STEPS:
            self.accept()
            return
        if self._rec is not None:
            return
        self.btn_primary.setEnabled(False)
        self._begin()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        if not self._started:
            self._started = True
            # Let the dialog paint before the mic opens.
            QTimer.singleShot(500, self._on_primary)

    def _begin(self) -> None:
        self.prompt.setText(
            f"Say “Hey Cel”  ·  sample {len(self.samples) + 1} of {_STEPS}")
        self.hint.setText(
            "Speak normally - don't shout. I'll listen for the silence after "
            "you and move on by myself.")
        try:
            rec = AudioRecordWorker(auto_stop_silence_ms=900,
                                    silence_threshold=self._gate(),
                                    min_record_ms=400)
        except Exception as exc:
            self._fail(f"Microphone unavailable: {exc}")
            return
        self._rec = rec
        rec.signals.level.connect(self._on_level)
        rec.signals.finished.connect(self._on_sample)
        rec.signals.error.connect(self._on_error)
        try:
            rec.start()
        except Exception as exc:
            self._rec = None
            self._fail(f"Could not open the microphone: {exc}")

    def _teardown_rec(self) -> None:
        rec = self._rec
        self._rec = None
        if rec is None:
            return
        try:
            rec.signals.level.disconnect(self._on_level)
        except (RuntimeError, TypeError):
            pass
        for sig, slot in ((rec.signals.finished, self._on_sample),
                          (rec.signals.error, self._on_error)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        try:
            if rec.is_recording:
                rec.stop()
        except Exception:
            pass

    def _on_error(self, msg: str) -> None:
        self._teardown_rec()
        self._fail(str(msg))

    def _fail(self, msg: str) -> None:
        self.prompt.setText("Hmm - that didn't work")
        self.hint.setText(f"{msg}  You can retry, or skip and turn the wake "
                          "word on later.")
        self.btn_primary.setText("Retry")
        self.btn_primary.setEnabled(True)

    def _on_sample(self, wav_bytes: bytes) -> None:
        self._teardown_rec()
        if self._closing:
            return
        self.vu.set_level(0.0)
        level = wav_rms(wav_bytes)
        if level < _TOO_QUIET and self._retries < 2:
            self._retries += 1
            self.prompt.setText("I barely heard that…")
            self.hint.setText(
                "Try again a little closer to the mic, and say it at your "
                "normal volume.")
            QTimer.singleShot(700, self._begin)
            return
        self._retries = 0
        if level < _TOO_QUIET:
            # Three near-silent clips would bake a useless threshold - bail
            # out cleanly instead of "succeeding" with garbage.
            self._fail("I still can't hear you. Check the mic in Settings, "
                       "then retry.")
            return
        self.samples.append(level)
        self.dots.done = len(self.samples)
        self.dots.active = min(len(self.samples), _STEPS - 1)
        self.dots.update()
        if len(self.samples) < _STEPS:
            QTimer.singleShot(650, self._begin)
            return
        self._finish()

    def _finish(self) -> None:
        # Threshold sits just under the *quietest* sample: loud samples are
        # easy, the soft one is where false negatives come from.
        speech = min(self.samples)
        thr = max(0.006, min(0.045, speech * 0.55))
        self.settings["wake_threshold"] = round(thr, 4)
        self.settings["wake_calibration_done"] = True
        # Keep the cancellation strength the user just chose, and hand it to the
        # gate so the wizard, the call and the settings slider all agree.
        try:
            self.settings["noise_cancel_strength"] = int(self.slider_noise.value())
            if self._has_profile():
                self.settings["noise_cancel_enabled"] = True
            noise_gate.configure(self.settings)
        except (RuntimeError, AttributeError):
            pass

        self.dots.active = -1
        self.dots.done = _STEPS
        self.dots.update()
        self.prompt.setText("✅  Got it - I know your voice now")
        self.hint.setText(
            f"Threshold set to {thr:.3f} from {len(self.samples)} samples. "
            "Say “Hey Cel” whenever you need me.")
        self.btn_skip.setText("Back")
        self.btn_primary.setText("Done")
        self.btn_primary.setEnabled(True)
        try:
            from ...services.sound_engine import play_animalese_chirp
            play_animalese_chirp("c", True, "Classic AC")
        except Exception:
            pass

    # ── teardown ─────────────────────────────────────────────────────────
    def done(self, r: int) -> None:  # noqa: N802 - Qt naming
        self._closing = True
        self._teardown_rec()
        super().done(r)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._closing = True
        self._teardown_rec()
        super().closeEvent(event)


class NoiseCalibrationDialog(QDialog):
    """Teach Cel what your *room* sounds like so she can subtract it.

    Captures ~2.8 s of ambient silence through the normal
    ``AudioRecordWorker`` (so the meter shows the real mic), stores it as
    the spectral-gating profile, and lets you audition the cancellation
    strength live against that very clip before saving.
    """

    CAPTURE_MS = 2800

    def __init__(self, settings: Optional[dict] = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.settings = settings if isinstance(settings, dict) else {}
        self._rec: Optional[AudioRecordWorker] = None
        self._wav: Optional[bytes] = None
        self._closing = False
        self._started = False
        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._stop_capture)
        self._peak = 0.0

        self.setWindowTitle("Noise cancellation - microphone calibration")
        self.setModal(True)
        self.setMinimumSize(540, 430)
        self.setStyleSheet(
            "NoiseCalibrationDialog{background: rgba(8, 4, 20, 0.97);"
            "border: 1.5px solid rgba(110, 231, 183, 0.5);}"
            "QLabel{background: transparent; border: none;}")

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 26)
        root.setSpacing(14)

        title = QLabel("🧹  Teach me your room")
        title.setStyleSheet(
            "color: #F4F1FF; font-size: 22px; font-weight: bold;")
        root.addWidget(title)

        self.hint = QLabel(
            "Stay quiet for a few seconds - just your room as it normally "
            "is: fans, hum, hiss. I'll learn exactly what to subtract so "
            "your voice comes through crystal clear. ✨")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(
            "color: rgba(233, 213, 255, 0.75); font-size: 14px;")
        root.addWidget(self.hint)

        self.prompt = QLabel("Get ready…")
        self.prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prompt.setStyleSheet(
            "color: #6EE7B7; font-size: 18px; font-weight: bold;"
            "margin: 10px 0 2px 0;")
        root.addWidget(self.prompt)

        self.vu = _LevelBar(self)
        root.addWidget(self.vu)

        # Result panel - hidden until a clip exists.
        self.result = QWidget(self)
        self.result.setStyleSheet(
            "QWidget{background: rgba(110, 231, 183, 0.08);"
            "border: 1px solid rgba(110, 231, 183, 0.35);"
            "border-radius: 12px;}")
        rv = QVBoxLayout(self.result)
        rv.setContentsMargins(14, 12, 14, 12)
        rv.setSpacing(8)
        self.lbl_stats = QLabel(" - ")
        self.lbl_stats.setStyleSheet(
            "color: #A7F3D0; font-size: 13px; font-weight: bold;"
            "border: none; background: transparent;")
        rv.addWidget(self.lbl_stats)
        sh = QHBoxLayout()
        lbl_s = QLabel("Cancellation strength:")
        lbl_s.setStyleSheet(
            "color: rgba(233, 213, 255, 0.8); font-size: 12px;"
            "border: none; background: transparent;")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(self.settings.get(
            "noise_cancel_strength", 70)))
        self.slider.setFixedWidth(190)
        self.lbl_val = QLabel(f"{self.slider.value()}%")
        self.lbl_val.setStyleSheet(
            "color: #6EE7B7; font-weight: bold; border: none;"
            "background: transparent;")
        self.slider.valueChanged.connect(self._on_strength)
        sh.addWidget(lbl_s)
        sh.addWidget(self.slider, 1)
        sh.addWidget(self.lbl_val)
        rv.addLayout(sh)
        self.result.hide()
        root.addWidget(self.result)

        root.addStretch(1)

        btn_row = QHBoxLayout()
        self.btn_skip = QPushButton("Skip")
        self.btn_skip.setStyleSheet(_SECONDARY_QSS)
        self.btn_skip.clicked.connect(self.reject)
        self.btn_primary = QPushButton("Start listening")
        # Same geometry as the wake dialog, green because this one is about
        # clean audio, not purple mic tuning.
        self.btn_primary.setStyleSheet(
            _PRIMARY_QSS.replace("#A855F7", "#6EE7B7")
                        .replace("#9333EA", "#34D399"))
        self.btn_primary.clicked.connect(self._on_primary)
        btn_row.addWidget(self.btn_skip)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_primary)
        root.addLayout(btn_row)

    # ── flow ───────────────────────────────────────────────────────────────
    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        if not self._started:
            self._started = True
            # Let the dialog paint before the mic opens.
            QTimer.singleShot(450, self._on_primary)

    def _on_live_level(self, v: float) -> None:
        """Follow the mic and remember the loudest moment of the capture."""
        self._peak = max(self._peak, float(v or 0.0))
        self.vu.set_level(v)

    def _on_primary(self) -> None:
        if self._rec is not None:
            return
        if self._wav is not None and self.btn_primary.text().startswith("Save"):
            self._save()
            return
        self._begin()

    def _begin(self) -> None:
        self._wav = None
        self.result.hide()
        self.btn_primary.setEnabled(False)
        self.btn_primary.setText("Listening…")
        self.prompt.setText("Listening to your room… stay quiet ✨")
        self.hint.setText(
            f"Nothing but ambience for {self.CAPTURE_MS // 1000} seconds - "
            "no talking, no typing.")
        try:
            rec = AudioRecordWorker(auto_stop_silence_ms=0,
                                    silence_threshold=1.0,
                                    min_record_ms=0)
        except Exception as exc:
            self._fail(f"Microphone unavailable: {exc}")
            return
        self._rec = rec
        rec.signals.level.connect(self._on_live_level)
        rec.signals.finished.connect(self._on_captured)
        rec.signals.error.connect(self._on_error)
        try:
            rec.start()
        except Exception as exc:
            self._rec = None
            self._fail(f"Could not open the microphone: {exc}")
            return
        self._stop_timer.start(self.CAPTURE_MS)

    def _stop_capture(self) -> None:
        rec = self._rec
        if rec is not None:
            try:
                rec.stop()
            except Exception:
                pass

    def _teardown_rec(self) -> None:
        self._stop_timer.stop()
        rec = self._rec
        self._rec = None
        if rec is None:
            return
        try:
            rec.signals.level.disconnect(self._on_live_level)
        except (RuntimeError, TypeError):
            pass
        for sig, slot in ((rec.signals.finished, self._on_captured),
                          (rec.signals.error, self._on_error)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        try:
            if rec.is_recording:
                rec.stop()
        except Exception:
            pass

    def _on_error(self, msg: str) -> None:
        self._teardown_rec()
        self._fail(str(msg))

    def _fail(self, msg: str) -> None:
        self.vu.set_level(0.0)
        self.prompt.setText("Hmm - that didn't work")
        self.hint.setText(
            f"{msg}  You can retry, or skip and calibrate later from "
            "Settings.")
        self.btn_primary.setText("Retry")
        self.btn_primary.setEnabled(True)

    def _on_captured(self, wav_bytes: bytes) -> None:
        self._teardown_rec()
        if self._closing:
            return
        # Hold the room floor on the bar - the mic is closed, but the
        # audition below keeps the same bar alive under the slider.
        self.vu.set_level(self._peak)
        if not wav_bytes or noise_gate.measure(wav_bytes) <= 0.0:
            self._fail("I didn't get any audio. Check the mic in Settings, "
                       "then retry.")
            return
        self._wav = wav_bytes
        self.result.show()
        self.prompt.setText("✅  Room captured - tune it below")
        self.hint.setText(
            "The bar is what's left after cancellation - slide the "
            "strength and watch it shrink, then save. Re-run this "
            "anytime from Settings.")
        self.btn_primary.setText("Save profile")
        self.btn_primary.setEnabled(True)
        self._on_strength(self.slider.value())

    @staticmethod
    def _db(rms: float) -> str:
        return f"{20.0 * math.log10(max(1e-7, float(rms or 0.0))):.0f} dB"

    def _on_strength(self, v: int) -> None:
        self.lbl_val.setText(f"{v}%")
        if not self._wav:
            return
        try:
            # Audition against the *just-captured* clip (it is not the saved
            # profile yet) so the dB numbers move with the slider.
            before, after = noise_gate.estimate_reduction(
                self._wav, v / 100.0, profile_wav=self._wav)
            self.lbl_stats.setText(
                f"Room floor {self._db(before)} → {self._db(after)} "
                f"at {v}%")
            # Same bar, same units as the live mic feed: show what
            # cancellation lets through at this strength (0% = full floor,
            # 95% = nearly silent). This is the drag preview.
            self.vu.set_level(after)
        except Exception:
            self.lbl_stats.setText(f"Cancellation strength: {v}%")

    def _save(self) -> None:
        if not self._wav:
            return
        try:
            noise_gate.save_profile(self._wav)
        except Exception as exc:
            self._fail(f"Couldn't store the profile: {exc}")
            return
        self.settings["noise_cancel_strength"] = int(self.slider.value())
        self.settings["noise_cancel_enabled"] = True
        self.settings["noise_calibration_done"] = True
        noise_gate.configure(self.settings)
        try:
            from ...services.sound_engine import play_ui_sound
            play_ui_sound("send", 0.5)
        except Exception:
            pass
        self.accept()

    # ── teardown ───────────────────────────────────────────────────────────
    def done(self, r: int) -> None:  # noqa: N802 - Qt naming
        self._closing = True
        self._teardown_rec()
        super().done(r)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._closing = True
        self._teardown_rec()
        super().closeEvent(event)


#: Guided "Hey Cel" setup: explainer -> enrolled samples -> live self-test.
_WIZ_SAMPLES = 10
#: A sample nobody ends gets cut here - Start/End is the normal path.
_WIZ_MAX_CLIP_MS = 8000


class HeyCelWizardDialog(QDialog):
    """Stepped "Hey Cel" setup wizard.

    Page 0 says what the wake word does and what never leaves the machine.
    Page 1 enrolls the phrase: press Start, say it once, press End - ten
    accepted samples. Every sample is transcribed locally; only clips that
    actually contain the phrase count, and distinct hearings are kept as
    pronunciation variants. Page 2 proves it live with the real listener,
    so nobody leaves wondering whether it hears them.
    """

    def __init__(self, settings: Optional[dict] = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.settings = settings if isinstance(settings, dict) else {}
        try:
            phrase = str(self.settings.get("live_wake_phrase", "")
                         or "Okay Cel").strip()
            self._phrase = phrase or "Okay Cel"
        except Exception:
            self._phrase = "Okay Cel"
        self._peaks: List[float] = []
        self._variants: List[str] = []
        self._rec: Optional[AudioRecordWorker] = None
        self._stt: Optional[STTWorker] = None
        self._pending_peak = 0.0
        self._closing = False
        self._recording = False
        self._safety: Optional[QTimer] = None
        self._test = None
        self._test_ok = False
        self._learn_candidate = ""

        self.setWindowTitle("Hey Cel - setup wizard")
        self.setModal(True)
        self.setMinimumSize(560, 500)
        self.setStyleSheet(
            "HeyCelWizardDialog{background: rgba(8, 4, 20, 0.97);"
            "border: 1.5px solid rgba(168, 85, 247, 0.55);}"
            "QLabel{background: transparent; border: none;}"
            "QLineEdit{background: rgba(255,255,255,0.06); color: #F4F1FF;"
            "border: 1px solid rgba(192,132,252,0.4); border-radius: 10px;"
            "padding: 8px 12px; font-size: 14px;}")

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 26)
        root.setSpacing(12)

        self.stack = QStackedWidget(self)
        root.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_about())
        self.stack.addWidget(self._build_enroll())
        self.stack.addWidget(self._build_test())

        nav = QHBoxLayout()
        self.btn_back = QPushButton("← Back")
        self.btn_back.setStyleSheet(_SECONDARY_QSS)
        self.btn_back.clicked.connect(self._on_back)
        self.btn_skip = QPushButton("Skip for now")
        self.btn_skip.setStyleSheet(_SECONDARY_QSS)
        self.btn_skip.clicked.connect(self.reject)
        self.btn_go = QPushButton("Next →")
        self.btn_go.setStyleSheet(_PRIMARY_QSS)
        self.btn_go.clicked.connect(self._on_go)
        nav.addWidget(self.btn_back)
        nav.addWidget(self.btn_skip)
        nav.addStretch(1)
        nav.addWidget(self.btn_go)
        root.addLayout(nav)
        self._sync_nav()

    # ── pages ────────────────────────────────────────────────────────────
    def _build_about(self) -> QWidget:
        page = QWidget(self)
        v = QVBoxLayout(page)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(12)
        title = QLabel("👋  Meet your wake word")
        title.setStyleSheet(
            "color: #F4F1FF; font-size: 22px; font-weight: bold;")
        v.addWidget(title)
        body = QLabel(
            f"Say “{self._phrase}” any time and Cel opens Live Mode - "
            "no hands needed.\n\n"
            "• The mic only listens on this machine. Clips are transcribed "
            "by the local ggml model and thrown away - your voice is never "
            "uploaded.\n\n"
            "• Next you'll say the phrase 10 times: press Start, say it "
            "once, press End. Only clips that actually contain the phrase "
            "count.\n\n"
            "• Then we test it live together, so you leave knowing it "
            "hears you.")
        body.setWordWrap(True)
        body.setStyleSheet(
            "color: rgba(233, 213, 255, 0.8); font-size: 14px;")
        v.addWidget(body)
        v.addStretch(1)
        return page

    def _build_enroll(self) -> QWidget:
        page = QWidget(self)
        v = QVBoxLayout(page)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(10)
        title = QLabel("🎙  Teach me how you say it")
        title.setStyleSheet(
            "color: #F4F1FF; font-size: 22px; font-weight: bold;")
        v.addWidget(title)
        prow = QHBoxLayout()
        plab = QLabel("Phrase:")
        plab.setStyleSheet(
            "color: rgba(233, 213, 255, 0.8); font-size: 13px;")
        prow.addWidget(plab)
        self.edit_phrase = QLineEdit(self._phrase, self)
        try:
            self.edit_phrase.textChanged.connect(self._on_phrase_changed)
        except Exception:
            pass
        prow.addWidget(self.edit_phrase, 1)
        v.addLayout(prow)
        self.lbl_count = QLabel(f"Sample 1 of {_WIZ_SAMPLES}")
        self.lbl_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_count.setStyleSheet(
            "color: #C084FC; font-size: 18px; font-weight: bold;")
        v.addWidget(self.lbl_count)
        self.lbl_dots = QLabel("○" * _WIZ_SAMPLES)
        self.lbl_dots.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_dots.setStyleSheet(
            "color: #C084FC; font-size: 15px; letter-spacing: 2px;")
        v.addWidget(self.lbl_dots)
        self.vu = _LevelBar(self)
        v.addWidget(self.vu)
        self.lbl_status = QLabel(
            "Press Start, say the phrase once, press End.")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(
            "color: rgba(233, 213, 255, 0.75); font-size: 13px;")
        v.addWidget(self.lbl_status)
        brow = QHBoxLayout()
        self.btn_start = QPushButton("🔴 Start recording")
        self.btn_start.setStyleSheet(_PRIMARY_QSS)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_end = QPushButton("⏹ End sample")
        self.btn_end.setStyleSheet(_SECONDARY_QSS)
        self.btn_end.clicked.connect(self._on_end)
        brow.addWidget(self.btn_start)
        brow.addWidget(self.btn_end)
        v.addLayout(brow)
        v.addStretch(1)
        self._sync_rec_buttons()
        return page

    def _build_test(self) -> QWidget:
        page = QWidget(self)
        v = QVBoxLayout(page)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(12)
        title = QLabel("🎧  Let's prove it")
        title.setStyleSheet(
            "color: #F4F1FF; font-size: 22px; font-weight: bold;")
        v.addWidget(title)
        self.lbl_test_info = QLabel("")
        self.lbl_test_info.setWordWrap(True)
        self.lbl_test_info.setStyleSheet(
            "color: rgba(233, 213, 255, 0.8); font-size: 14px;")
        v.addWidget(self.lbl_test_info)
        self.lbl_heard = QLabel("…")
        self.lbl_heard.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_heard.setWordWrap(True)
        self.lbl_heard.setStyleSheet(
            "color: #6EE7B7; font-size: 16px; font-weight: bold;")
        v.addWidget(self.lbl_heard)
        self.btn_learn = QPushButton("")
        self.btn_learn.setStyleSheet(_SECONDARY_QSS)
        self.btn_learn.clicked.connect(self._on_learn)
        self.btn_learn.setVisible(False)
        v.addWidget(self.btn_learn)
        self.lbl_test = QLabel("Listening…")
        self.lbl_test.setWordWrap(True)
        self.lbl_test.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_test.setStyleSheet(
            "color: #C084FC; font-size: 14px;")
        v.addWidget(self.lbl_test)
        v.addStretch(1)
        return page

    # ── navigation ─────────────────────────────────────────────────────
    def _sync_nav(self) -> None:
        i = self.stack.currentIndex()
        try:
            self.btn_back.setVisible(i > 0)
            self.btn_go.setVisible(i != 1)
            if i == 0:
                self.btn_go.setText("Next →")
            elif i == 2:
                self.btn_go.setText("✅ Done - turn Hey Cel on")
        except RuntimeError:
            pass

    def _on_back(self) -> None:
        self._goto(max(0, self.stack.currentIndex() - 1))

    def _on_go(self) -> None:
        i = self.stack.currentIndex()
        if i == 0:
            self._goto(1)
        elif i == 2:
            self._finish()

    def _goto(self, i: int) -> None:
        cur = self.stack.currentIndex()
        if i == cur:
            return
        if cur == 1:
            self._stop_enrollment()
        if cur == 2:
            self._stop_test()
        self.stack.setCurrentIndex(i)
        if i == 1:
            self._sync_rec_buttons()
        if i == 2:
            try:
                self.lbl_test_info.setText(
                    "I'm listening with your new settings right now - "
                    f"just say “{self._phrase}”.")
            except RuntimeError:
                pass
            self._start_test()
        self._sync_nav()

    # ── enrollment ─────────────────────────────────────────────────────
    def _rec_gate(self) -> float:
        try:
            return noise_gate.effective_gate(self.settings, base=0.006,
                                             cap=0.25)
        except Exception:
            return 0.006

    def _floor(self) -> float:
        try:
            if noise_gate.has_profile():
                return noise_gate.profile_rms()
        except Exception:
            pass
        return 0.0

    def _status(self, msg: str) -> None:
        try:
            self.lbl_status.setText(msg)
        except RuntimeError:
            pass

    def _sync_rec_buttons(self) -> None:
        busy = (self._recording or self._rec is not None
                or self._stt is not None)
        done = len(self._peaks) >= _WIZ_SAMPLES
        on_page = self.stack.currentIndex() == 1
        try:
            self.btn_start.setEnabled(on_page and not busy and not done)
            self.btn_end.setEnabled(on_page and bool(self._recording))
        except RuntimeError:
            pass

    def _on_phrase_changed(self) -> None:
        try:
            new = self.edit_phrase.text().strip() or "Okay Cel"
        except RuntimeError:
            return
        if new == self._phrase:
            return
        self._phrase = new
        if self._peaks or self._variants:
            self._peaks = []
            self._variants = []
            try:
                self.lbl_count.setText(f"Sample 1 of {_WIZ_SAMPLES}")
                self.lbl_dots.setText("○" * _WIZ_SAMPLES)
            except RuntimeError:
                pass
            self._status("Phrase changed - count restarted so every "
                         "sample matches it.")

    def _on_level(self, rms: float) -> None:
        try:
            self.vu.set_level(rms, floor=self._floor())
        except Exception:
            pass

    def _on_start(self) -> None:
        if (self._recording or self._rec is not None
                or self.stack.currentIndex() != 1):
            return
        try:
            self._phrase = self.edit_phrase.text().strip() or "Okay Cel"
        except RuntimeError:
            pass
        try:
            rec = AudioRecordWorker(auto_stop_silence_ms=0,
                                    silence_threshold=self._rec_gate(),
                                    min_record_ms=300)
        except Exception as exc:
            self._status(f"Microphone unavailable: {exc}")
            return
        self._rec = rec
        try:
            rec.signals.level.connect(self._on_level)
            rec.signals.finished.connect(self._on_sample)
            rec.signals.error.connect(self._on_rec_error)
        except Exception:
            pass
        try:
            rec.start()
        except Exception as exc:
            self._teardown_rec()
            self._status(f"Could not open the microphone: {exc}")
            self._sync_rec_buttons()
            return
        self._recording = True
        self._sync_rec_buttons()
        self._status(f"Listening… say “{self._phrase}” once, then press End.")
        try:
            self._stop_safety()
            self._safety = QTimer(self)
            self._safety.setSingleShot(True)
            self._safety.timeout.connect(self._on_end)
            self._safety.start(_WIZ_MAX_CLIP_MS)
        except Exception:
            pass

    def _on_end(self) -> None:
        if not self._recording or self._rec is None:
            return
        self._stop_safety()
        self._recording = False
        self._sync_rec_buttons()
        self._status("Checking what I heard…")
        try:
            self._rec.stop()
        except Exception:
            pass
        # finished → _on_sample packs the clip

    def _on_sample(self, wav_bytes: bytes) -> None:
        rec = self._rec
        peak = 0.0
        try:
            peak = float(getattr(rec, "peak_rms", 0.0) or 0.0)
        except Exception:
            pass
        self._teardown_rec()
        if self._closing:
            return
        if peak < _TOO_QUIET:
            self._status(
                f"I barely heard that (peak {peak:.3f}) - a touch closer, "
                "normal voice, then Start again.")
            self._sync_rec_buttons()
            return
        self._transcribe_sample(wav_bytes, peak)

    def _on_rec_error(self, msg: str) -> None:
        self._teardown_rec()
        if self._closing:
            return
        self._status(f"Microphone hiccup: {msg} - press Start to retry.")
        self._sync_rec_buttons()

    def _transcribe_sample(self, wav_bytes: bytes, peak: float) -> None:
        try:
            ggml = str(self.settings.get("stt_ggml_path", "") or "")
        except Exception:
            ggml = ""
        try:
            stt = STTWorker(wav_bytes, engine="ggml Whisper (Local)",
                            ggml_path=ggml)
        except Exception as exc:
            self._status(f"Transcriber unavailable: {exc}")
            self._sync_rec_buttons()
            return
        self._stt = stt
        self._pending_peak = peak
        try:
            stt.signals.single_result.connect(self._on_sample_text)
            stt.signals.error.connect(self._on_sample_stt_error)
        except Exception:
            pass
        self._status("Heard you - checking the words…")
        self._sync_rec_buttons()
        try:
            stt.start()
        except Exception as exc:
            self._teardown_stt()
            self._status(f"Couldn't transcribe: {exc}")
            self._sync_rec_buttons()

    def _on_sample_text(self, engine: str, text: str) -> None:
        self._teardown_stt()
        if self._closing:
            return
        heard = str(text or "").strip()
        if matches_wake_phrase(heard, [self._phrase]):
            self._accept_sample(self._pending_peak, normalize(heard))
        else:
            shown = heard if heard else "(nothing)"
            self._status(f"I heard “{shown}” - no “{self._phrase}” in "
                         "there. Same phrase, a touch slower.")
            self._sync_rec_buttons()
        self._pending_peak = 0.0

    def _on_sample_stt_error(self, msg: str) -> None:
        self._teardown_stt()
        if self._closing:
            return
        m = str(msg or "")
        if ("pywhispercpp" in m or "sounddevice" in m or "Missing" in m):
            self._status("I can't transcribe here: the local ggml voice "
                         "model isn't set (Settings → Voice Input). Set the "
                         "model path, then come back.")
        else:
            self._status(f"Couldn't make out that one ({m}) - press Start "
                         "and try again.")
        self._sync_rec_buttons()

    def _accept_sample(self, peak: float, norm_text: str) -> None:
        self._peaks.append(float(peak))
        try:
            base_len = len(normalize(self._phrase))
            if (norm_text and norm_text not in self._variants
                    and len(norm_text) <= base_len + 6):
                self._variants.append(norm_text)
        except Exception:
            pass
        n = len(self._peaks)
        try:
            self.lbl_count.setText(
                f"Sample {min(n + 1, _WIZ_SAMPLES)} of {_WIZ_SAMPLES}")
            self.lbl_dots.setText("●" * n + "○" * (_WIZ_SAMPLES - n))
        except RuntimeError:
            pass
        if n >= _WIZ_SAMPLES:
            self._status("All 10 locked in - taking you to the live test…")
            self._sync_rec_buttons()
            QTimer.singleShot(900, self._maybe_advance_to_test)
        else:
            self._status(f"✅ Sample {n} of {_WIZ_SAMPLES} kept. "
                         "Press Start for the next one.")
            self._sync_rec_buttons()

    def _maybe_advance_to_test(self) -> None:
        if self._closing or self.stack.currentIndex() != 1:
            return
        if len(self._peaks) >= _WIZ_SAMPLES:
            self._goto(2)

    def _stop_enrollment(self) -> None:
        self._stop_safety()
        self._teardown_rec()
        self._teardown_stt()
        self._recording = False

    # ── live self-test ───────────────────────────────────────────────
    def _candidate_threshold(self) -> float:
        if not self._peaks:
            try:
                return float(self.settings.get("wake_threshold", 0.012))
            except (TypeError, ValueError):
                return 0.012
        # Threshold sits just under the *quietest* sample: loud samples are
        # easy, the soft one is where false negatives come from.
        return max(0.006, min(0.045, min(self._peaks) * 0.55))

    def _start_test(self) -> None:
        self._stop_test()
        if self._closing:
            return
        test_settings = dict(self.settings)
        test_settings["wake_threshold"] = self._candidate_threshold()
        test_settings["live_wake_phrase"] = self._phrase
        test_settings["wake_phrase_variants"] = list(self._variants)
        try:
            lst = WakeListener(self, settings=test_settings)
        except Exception as exc:
            self._test_label(f"Couldn't start the listener: {exc}")
            return
        try:
            lst.woken.connect(self._on_test_woke)
            lst.heard.connect(self._on_test_heard)
            lst.error.connect(self._on_test_error)
        except Exception:
            pass
        self._test = lst
        self._test_ok = False
        self._learn_candidate = ""
        try:
            self.btn_learn.setVisible(False)
        except RuntimeError:
            pass
        try:
            if not lst.start():
                self._test_label("Microphone wouldn't open - check "
                                 "Settings → Audio, then go Back and return.")
                self._test = None
                return
        except Exception as exc:
            self._test_label(f"Microphone wouldn't open: {exc}")
            self._test = None
            return
        self._test_label(f"Listening… say “{self._phrase}”.")
        try:
            self.lbl_heard.setText("…")
        except RuntimeError:
            pass

    def _stop_test(self) -> None:
        lst = self._test
        self._test = None
        if lst is None:
            return
        try:
            lst.stop()
        except Exception:
            pass

    def _test_label(self, msg: str) -> None:
        try:
            self.lbl_test.setText(msg)
        except RuntimeError:
            pass

    def _on_test_heard(self, text: str) -> None:
        t = str(text or "").strip()
        if not t:
            return
        try:
            self.lbl_heard.setText(f"I heard: “{t}”")
        except RuntimeError:
            return
        nt = normalize(t)
        try:
            base_len = len(normalize(self._phrase))
        except Exception:
            base_len = 7
        if (nt and nt not in self._variants and nt != normalize(self._phrase)
                and len(nt) <= base_len + 6):
            self._learn_candidate = nt
            try:
                self.btn_learn.setText(f"🔖 “{t}” is how I say it - learn it")
                self.btn_learn.setVisible(True)
            except RuntimeError:
                pass
        else:
            try:
                self.btn_learn.setVisible(False)
            except RuntimeError:
                pass
        self._test_label(f"Not a match - say “{self._phrase}”.")

    def _on_learn(self) -> None:
        if self._learn_candidate and \
                self._learn_candidate not in self._variants:
            self._variants.append(self._learn_candidate)
        self._learn_candidate = ""
        try:
            self.btn_learn.setVisible(False)
        except RuntimeError:
            pass
        self._test_label(f"Learned it - say “{self._phrase}” again.")
        # Re-listen with the new variant so the retry proves it.
        self._start_test()

    def _on_test_woke(self, phrase: str) -> None:
        self._test_ok = True
        self._stop_test()
        try:
            self.lbl_heard.setText(f"Matched: “{phrase}”")
        except RuntimeError:
            pass
        self._test_label("✅ She heard you - that's exactly what the "
                         "app does.")
        try:
            self.btn_learn.setVisible(False)
            self.btn_go.setText("✅ Done - turn Hey Cel on")
        except RuntimeError:
            pass
        try:
            from ...services.sound_engine import play_animalese_chirp
            play_animalese_chirp("c", True, "Classic AC")
        except Exception:
            pass

    def _on_test_error(self, msg: str) -> None:
        # The listener respawns itself - this is a hiccup, not a death.
        self._test_label(f"Listener hiccup: {msg} - still listening…")

    # ── finish ─────────────────────────────────────────────────────
    def _finish(self) -> None:
        thr = self._candidate_threshold()
        self.settings["live_wake_phrase"] = self._phrase
        self.settings["wake_threshold"] = round(thr, 4)
        self.settings["wake_calibration_done"] = True
        try:
            base = normalize(self._phrase)
            base_nospace = base.replace(" ", "")
        except Exception:
            base, base_nospace = "hey cel", "heycel"
        seen = []
        try:
            for v in self._variants:
                nv = normalize(v)
                if nv and nv != base and nv.replace(" ", "") != base_nospace \
                        and nv not in seen:
                    seen.append(nv)
        except Exception:
            pass
        self.settings["wake_phrase_variants"] = seen
        self.accept()

    # ── teardown ─────────────────────────────────────────────────────
    def _stop_safety(self) -> None:
        t = self._safety
        self._safety = None
        if t is not None:
            try:
                t.stop()
            except Exception:
                pass

    def _teardown_rec(self, wait: bool = False) -> None:
        rec = self._rec
        self._rec = None
        self._recording = False
        if rec is None:
            return
        for sig, slot in ((rec.signals.level, self._on_level),
                          (rec.signals.finished, self._on_sample),
                          (rec.signals.error, self._on_rec_error)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        try:
            if rec.is_recording:
                rec.stop()
        except Exception:
            pass
        if wait:
            try:
                if rec.isRunning():
                    rec.wait(2000)
            except Exception:
                pass

    def _teardown_stt(self, wait: bool = False) -> None:
        stt = self._stt
        self._stt = None
        if stt is None:
            return
        for sig, slot in ((stt.signals.single_result, self._on_sample_text),
                          (stt.signals.error, self._on_sample_stt_error)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        if wait:
            try:
                if stt.isRunning():
                    stt.wait(2000)
            except Exception:
                pass

    def done(self, r: int) -> None:  # noqa: N802 - Qt naming
        self._closing = True
        self._stop_safety()
        self._stop_test()
        self._teardown_rec(wait=True)
        self._teardown_stt(wait=True)
        super().done(r)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._closing = True
        self._stop_safety()
        self._stop_test()
        self._teardown_rec(wait=True)
        self._teardown_stt(wait=True)
        super().closeEvent(event)
