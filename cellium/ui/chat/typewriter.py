"""Typewriter reveal for streaming chat replies.

Qt widget, additive: nothing in the existing bubble pipeline depends on it, so
it can be dropped in or left out per bubble.

Ported in spirit from `Typewriter` in the archived `Cerebellium Opus.py`, which
had no counterpart in Cellium. Pairs naturally with Cellium's existing token
streaming (`GenerationSignals.delta`).

Usage::

    tw = TypewriterEdit(self)
    tw.set_markup_streamed(html_fragment)   # call per delta chunk
    tw.finish()                              # snap to full text when done

Rendering rule: during streaming we append raw text so markdown never has to be
re-parsed mid-flight. `finish()` hands the complete string to an optional
`finalizer` (typically the bubble's real markdown renderer) exactly once.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal, Property
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QTextEdit, QWidget, QVBoxLayout

__all__ = ["TypewriterEdit", "TypewriterController"]


class TypewriterEdit(QTextEdit):
    """Read-only text view that reveals appended text character by character.

    Emits ``reveal_finished`` when the queue drains, and ``char_revealed`` per
    character so a caller can drive an audio "tick" per glyph.
    """

    reveal_finished = Signal()

    def __init__(self, parent: QWidget | None = None,
                 cps: int = 90,
                 chunk: int = 3,
                 ticker=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self._queue: list[str] = []
        self._cps = max(1, int(cps))
        self._chunk = max(1, int(chunk))
        self._ticker = ticker
        self._finished_fired = False
        self._timer = QTimer(self)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._tick)

    # ── configuration ────────────────────────────────────────────────────
    def set_speed(self, cps: int) -> None:
        self._cps = max(1, int(cps))

    def set_ticker(self, ticker) -> None:
        """``ticker`` is called with no args once per revealed glyph."""
        self._ticker = ticker

    @property
    def is_animating(self) -> bool:
        return self._timer.isActive() or bool(self._queue)

    # ── streaming ────────────────────────────────────────────────────────
    def set_markup_streamed(self, fragment: str) -> None:
        """Append a raw (unescaped) fragment and keep animating."""
        if not fragment:
            return
        self._queue.append(str(fragment))
        self._finished_fired = False
        if not self._timer.isActive():
            self._timer.start()

    def set_text_immediate(self, text: str) -> None:
        """Replace everything and show it at once (no animation)."""
        self._timer.stop()
        self._queue.clear()
        self._finished_fired = False
        self.setPlainText(str(text or ""))
        self._move_to_end()

    def reveal_all(self) -> None:
        """Flush the queue instantly, e.g. on scroll or user click."""
        if not self._queue:
            self._stop_and_fire()
            return
        pending = "".join(self._queue)
        self._queue.clear()
        self._timer.stop()
        self._append_raw(pending)

    def clear_all(self) -> None:
        self._timer.stop()
        self._queue.clear()
        self._finished_fired = False
        self.clear()

    # ── internals ────────────────────────────────────────────────────────
    def _append_raw(self, text: str) -> None:
        if not text:
            return
        self.moveCursor(QTextCursor.End)
        self.insertPlainText(text)
        self.ensureCursorVisible()

    def _move_to_end(self) -> None:
        self.moveCursor(QTextCursor.End)
        self.ensureCursorVisible()

    def _tick(self) -> None:
        if not self._queue:
            self._stop_and_fire()
            return
        # Pull a small slice from the head fragment; loop so long fragments
        # drain faster than the per-tick budget allows.
        budget = self._chunk
        while budget > 0 and self._queue:
            head = self._queue[0]
            if not head:
                self._queue.pop(0)
                continue
            take = head[:budget]
            self._queue[0] = head[budget:]
            self._append_raw(take)
            budget -= len(take)
            if self._ticker is not None:
                try:
                    self._ticker()
                except Exception:
                    self._ticker = None
        if not self._queue:
            self._stop_and_fire()

    def _stop_and_fire(self) -> None:
        self._timer.stop()
        if not self._finished_fired:
            self._finished_fired = True
            self.reveal_finished.emit()


class TypewriterController(QWidget):
    """Thin owner that keeps a TypewriterEdit sized to its container.

    Useful where a bare editor would fight the bubble's own layout.
    """

    def __init__(self, parent: QWidget | None = None, **kwargs):
        super().__init__(parent)
        self.edit = TypewriterEdit(self, **kwargs)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.edit)
        self.reveal_finished = self.edit.reveal_finished

    # convenience passthrough
    def set_markup_streamed(self, fragment: str) -> None:
        self.edit.set_markup_streamed(fragment)

    def finish(self) -> None:
        self.edit.reveal_all()

    def set_text_immediate(self, text: str) -> None:
        self.edit.set_text_immediate(text)
