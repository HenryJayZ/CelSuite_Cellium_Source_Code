"""Focus / pomodoro clock widget.

Qt widget. Ported in spirit from `FocusClock` in the archived
`Cerebellium Opus.py`, which had no counterpart in Cellium.

Self-contained: owns its own QTimer, emits `session_completed` so a caller can
drive TTS ("break's over") or log the session. No dependency on Cellium's
`core.config` so it stays testable and droppable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout

__all__ = ["FocusClock", "FocusSettings", "PHASES"]


@dataclass(frozen=True)
class FocusSettings:
    work_minutes: int = 25
    short_break_minutes: int = 5
    long_break_minutes: int = 15
    rounds_before_long_break: int = 4
    auto_start_breaks: bool = True
    auto_start_work: bool = False
    daily_goal_rounds: int = 8
    chime_on_complete: bool = True


PHASES = ("work", "short_break", "long_break")


class FocusClock(QWidget):
    """Circular countdown with work/break phases and round tracking.

    Signals
    ------
    phase_changed(str)        new phase name entered
    session_completed(str)    phase finished (``"work"`` or a break name)
    tick(int)                 every second; ``int`` = seconds remaining
    """

    phase_changed = Signal(str)
    session_completed = Signal(str)
    tick = Signal(int)
    rounds_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None,
                 settings: FocusSettings | None = None,
                 accent: str = "#a78bfa",
                 track: str = "#2e2a4a",
                 bg: str = "#0d0b1a"):
        super().__init__(parent)
        self.settings = settings or FocusSettings()
        self.accent = accent
        self.track = track
        self.bg = bg

        self._phase = "work"
        self._round = 1
        self._remaining = self.settings.work_minutes * 60
        self._total = self._remaining
        self._running = False
        self._rounds_today = 0

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

        self.setMinimumSize(180, 180)
        self._build_ui()

    # ── ui ───────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self._label = QLabel(self._fmt(self._remaining))
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            f"color:{self.accent};font-size:26px;font-weight:700;")
        self._phase_label = QLabel("Focus")
        self._phase_label.setAlignment(Qt.AlignCenter)
        self._phase_label.setStyleSheet(f"color:{self.accent};font-size:11px;letter-spacing:1px;")
        self._round_label = QLabel(f"Round {self._round}")
        self._round_label.setAlignment(Qt.AlignCenter)
        self._round_label.setStyleSheet("color:#94a3b8;font-size:10px;")

        self._toggle = QPushButton("Start")
        self._toggle.clicked.connect(self.toggle)
        self._skip = QPushButton("Skip")
        self._skip.clicked.connect(self.skip)
        self._reset = QPushButton("Reset")
        self._reset.clicked.connect(self.reset)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        for b in (self._toggle, self._skip, self._reset):
            btns.addWidget(b)

        root.addStretch(1)
        root.addWidget(self._label)
        root.addWidget(self._phase_label)
        root.addWidget(self._round_label)
        root.addStretch(1)
        root.addLayout(btns)

    # ── state ────────────────────────────────────────────────────────────
    @staticmethod
    def _fmt(seconds: int) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def remaining(self) -> int:
        return self._remaining

    @property
    def running(self) -> bool:
        return self._running

    @property
    def rounds_today(self) -> int:
        return self._rounds_today

    @property
    def fraction(self) -> float:
        if self._total <= 0:
            return 0.0
        return max(0.0, min(1.0, self._remaining / self._total))

    def _duration_for(self, phase: str) -> int:
        s = self.settings
        return {
            "work": s.work_minutes * 60,
            "short_break": s.short_break_minutes * 60,
            "long_break": s.long_break_minutes * 60,
        }[phase]

    def _label_for(self, phase: str) -> str:
        return {"work": "Focus", "short_break": "Short Break",
                "long_break": "Long Break"}[phase]

    def _set_phase(self, phase: str) -> None:
        self._phase = phase
        self._total = self._duration_for(phase)
        self._remaining = self._total
        self._phase_label.setText(self._label_for(phase))
        goal = getattr(self.settings, "daily_goal_rounds", 0)
        goal_txt = f" · 🏆 {self._rounds_today}/{goal} today" if goal else ""
        self._round_label.setText(f"Round {self._round}{goal_txt}")
        self._label.setText(self._fmt(self._remaining))
        self.phase_changed.emit(phase)
        self.update()

    # ── controls ─────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._toggle.setText("Pause")
        self._timer.start()
        self.update()

    def pause(self) -> None:
        if not self._running:
            return
        self._running = False
        self._toggle.setText("Start")
        self._timer.stop()
        self.update()

    def toggle(self) -> None:
        self.pause() if self._running else self.start()

    def reset(self) -> None:
        was = self._running
        self._timer.stop()
        self._running = False
        self._toggle.setText("Start")
        self._set_phase("work")
        if was:
            self.start()

    def skip(self) -> None:
        self._complete_phase(advance=True)

    def _on_tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self._complete_phase(advance=True)
        else:
            self._label.setText(self._fmt(self._remaining))
            self.tick.emit(self._remaining)
            self.update()

    def _complete_phase(self, advance: bool) -> None:
        finished = self._phase
        self.session_completed.emit(finished)
        if not advance:
            self._set_phase(finished)
            return
        if finished == "work":
            self._round += 1
            self._rounds_today += 1
            self.rounds_changed.emit(self._rounds_today)
            is_long = self._round % max(1, self.settings.rounds_before_long_break) == 1
            self._set_phase("long_break" if is_long else "short_break")
        else:
            self._set_phase("work")
        # Auto-continue so the cycle keeps running without babysitting  - 
        # but only into phases the user opted into auto-starting (Task 19).
        if self._running:
            if finished == "work" and not self.settings.auto_start_breaks:
                self._running = False
                self._toggle.setText("Start")
            elif finished != "work" and not self.settings.auto_start_work:
                self._running = False
                self._toggle.setText("Start")
            else:
                self._timer.start()
            self.update()

    # ── painting ─────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        size = min(self.width(), self.height() - 70)
        if size <= 0:
            return
        # Centre the dial in the space above the labels.
        cx = self.width() / 2
        cy = (self.height() - 70) / 2 + 8
        radius = size / 2 - 6
        thickness = 8

        p.setPen(QPen(QColor(self.track), thickness, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2),
                  0, 360 * 16)

        if self.fraction > 0:
            p.setPen(QPen(QColor(self.accent), thickness, Qt.SolidLine, Qt.RoundCap))
            span = int(-360 * 16 * self.fraction)
            p.drawArc(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2),
                      90 * 16, span)
        p.end()
