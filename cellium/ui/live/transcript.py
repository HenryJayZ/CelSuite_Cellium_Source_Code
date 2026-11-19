"""Live-call transcript: fading pixel bubbles + slide-in history sidebar.

During a call the chat is hidden, so every used-to-be utterance evaporated
into the caption bar and the conversation was *gone* by hang-up. This keeps
it visible: your words on the right, Cel's on the left, as frosted bubbles
that materialise and dissolve **one pixel-cell at a time** - never a hard
pop - plus a right-side session sidebar (the 🕘 circle in the control bar).

Nothing here touches persistence: the chat already owns the session memory;
the host reads it back through ``_live_session_messages()`` on connect.
"""

from __future__ import annotations

import html
import json
import math
import re
from collections import deque
from typing import Iterable, Optional

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, Qt, QTimer, Property, QSize, QRectF,
    Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen,
    QTextCharFormat, QTextCursor, QTextDocument,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

__all__ = ["LiveBubble", "LiveTranscript", "LiveHistoryPanel"]

#: Newest N bubbles kept on screen; the oldest dissolves out beyond this.
_MAX_BUBBLES = 5
#: Pixel-dissolve cell size - small enough to read as a dissolve, big
#: enough that one paint pass stays cheap.
_CELL = 7
_TICK_MS = 30
#: Live bubbles are a glanceable summary; the chat owns the full text.
#: Live bubbles are a glanceable summary; the chat owns the full text.


#: Same tag shape the chat bubble parses (bubble.py) - kept in sync so the
#: history panel never shows raw markup.
_AGENT_TAG_RE = re.compile(
    r'<agent_action tool="([^"]+)" args="([^"]+)" status="([^"]+)"'
    r'(?: diff="([^"]*)")?>(.*?)</agent_action>', re.DOTALL)


def _display_text(content: str) -> str:
    """Readable history text: prose + one line per tool call.

    Raw memory embeds ``<agent_action>`` tags whose args are HTML-escaped
    JSON (so the tag stays parseable) - rendered literally that reads as
    ``args="&quot;command&quot;..."``. Collapse each tag to a summary line
    and unescape the prose.
    """
    def _one(m: "re.Match") -> str:
        tool = html.unescape(m.group(1) or "").strip() or "tool"
        status = html.unescape(m.group(3) or "").strip() or "done"
        low = status.lower()
        mark = "✓" if ("complet" in low or "done" in low or "success" in low) else "•"
        return f"\n🔧 {tool} - {mark} {status}"
    text = _AGENT_TAG_RE.sub(_one, str(content or ""))
    text = html.unescape(text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


class LiveBubble(QWidget):
    """One transcript line that materialises/dissolves pixel by pixel."""

    def __init__(self, role: str, text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.role = "user" if role == "user" else "cel"
        self.text = _display_text(text)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._reveal = 0.0
        self._target = 1.0
        self._dying = False

        self._doc = QTextDocument(self)
        self._doc.setDefaultFont(QFont("Google Sans", 11))
        cap = 300
        try:
            pw = parent.width() if parent is not None else 0
            if pw > 48:
                cap = max(120, min(300, pw - 10))
        except Exception:
            pass
        try:
            self._doc.setMarkdown(self.text)
        except Exception:
            self._doc.setPlainText(self.text)
        self._doc.setTextWidth(-1)
        natural = self._doc.size().width()
        self._w = int(max(72, min(cap, natural + 26)))
        self._doc.setTextWidth(self._w - 24)
        fmt = QTextCharFormat()
        fmt.setForeground(QBrush(QColor("#F6F1FF") if self.role == "user"
                                 else QColor("#E4D7FF")))
        cur = QTextCursor(self._doc)
        cur.select(QTextCursor.SelectionType.Document)
        cur.mergeCharFormat(fmt)

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ── geometry ───────────────────────────────────────────────────────────
    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        h = int(math.ceil(self._doc.size().height())) + 24
        return QSize(getattr(self, "_w", 256), max(38, h))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        h = int(math.ceil(self._doc.size().height())) + 24
        return QSize(getattr(self, "_w", 256), max(38, h))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        try:
            w = max(72, int(self.width()))
            if abs(w - getattr(self, "_w", 0)) > 2:
                self._w = w
                self._doc.setTextWidth(w - 24)
                self.updateGeometry()
        except (RuntimeError, AttributeError):
            pass

    # ── lifecycle ──────────────────────────────────────────────────────────
    def dissolve_out(self) -> None:
        """Come apart pixel by pixel, then delete."""
        self._dying = True
        self._target = 0.0
        if not self._timer.isActive():
            self._timer.start()

    def park(self) -> None:
        """Dissolve to invisible but stay alive - the history sidebar owns
        this screen space while open. ``unpark`` brings the same bubble back,
        so the two never overlap."""
        self._dying = False
        self._target = 0.0
        if not self._timer.isActive():
            self._timer.start()

    def unpark(self) -> None:
        """Re-materialise a parked bubble (no-op if it is dying for real)."""
        if self._dying:
            return
        self._target = 1.0
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        step = 0.13
        if self._reveal < self._target:
            self._reveal = min(self._target, self._reveal + step)
        elif self._reveal > self._target:
            self._reveal = max(self._target, self._reveal - step * 1.25)
        else:
            # Settled: stop burning frames on a static bubble…
            if not self._dying:
                self._timer.stop()
                self.update()
                return
        self.update()
        if self._dying and self._reveal <= 0.001:
            self._timer.stop()
            self.deleteLater()

    # ── paint ──────────────────────────────────────────────────────────────
    @staticmethod
    def _cell_frac(gx: int, gy: int) -> float:
        """Stable pseudo-random 0..1 per cell (same pattern every frame)."""
        n = (int(gx) * 73856093) ^ (int(gy) * 19349663) ^ 0x9E3779B9
        n = ((n ^ (n >> 15)) * 0x2C1B3C6D) & 0xFFFFFFFF
        n ^= n >> 16
        return (n & 0xFFFF) / 65535.0

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        reveal = max(0.0, min(1.0, self._reveal))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if reveal <= 0.002:
            p.end()
            return
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        path = QPainterPath()
        path.addRoundedRect(r, 14.0, 14.0)
        if self.role == "user":
            bg = QColor(48, 30, 74, int(195 * reveal))
            border = QColor(192, 132, 252, int(95 * reveal))
        else:
            bg = QColor(18, 12, 34, int(185 * reveal))
            border = QColor(192, 132, 252, int(72 * reveal))
        p.setBrush(QBrush(bg))
        p.setPen(QPen(border, 1.0))
        p.drawPath(path)

        # Text, clipped to the plate.
        p.save()
        p.setClipPath(path)
        p.translate(12.0, 8.0)
        self._doc.drawContents(p)
        p.restore()

        # Pixel dissolve: erase every cell that has not been revealed yet.
        if reveal < 0.999:
            p.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationOut)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 255))
            w, h = self.width(), self.height()
            for gy in range(0, h + _CELL, _CELL):
                for gx in range(0, w + _CELL, _CELL):
                    if self._cell_frac(gx, gy) > reveal:
                        p.fillRect(gx, gy, _CELL, _CELL, QColor(0, 0, 0, 255))
            p.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver)
        p.end()


def _strip_mood_line(text: str) -> str:
    """Drop the ``mood: <key>`` contract line for on-screen bubbles.

    The floating transcript is a glanceable mirror - the mood key already did
    its job on Cel's face. The history sidebar keeps the raw session text, so
    the mood stays visible there.
    """
    try:
        from .live_mode import extract_mood
    except Exception:
        return str(text or "")
    try:
        cleaned, _ = extract_mood(text)
    except Exception:
        return str(text or "")
    try:
        from cellium.core.utils import strip_inline_mood_display
        return strip_inline_mood_display(cleaned)
    except Exception:
        return cleaned


class LiveTranscript(QWidget):
    """Right-hand column of bubbles - newest at the bottom, max five.

    Purely decorative for input (``WA_TransparentForMouseEvents``): clicks
    pass straight through to Cel behind it.

    Can be *parked*: every bubble dissolves away (and new arrivals wait
    invisible) while the history sidebar covers this column, then all of
    them dissolve back when it closes - nothing is deleted, so closing the
    panel restores exactly what was on screen.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._col = QVBoxLayout(self)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(8)
        self._col.addStretch(1)
        self._bubbles: "deque[LiveBubble]" = deque()
        self._parked = False

    # ── parking (history sidebar owns the screen) ──────────────────────────
    def set_parked(self, on: bool) -> None:
        """Dissolve every bubble out (True) or bring them all back (False)."""
        self._parked = bool(on)
        for b in list(self._bubbles):
            try:
                (b.park if self._parked else b.unpark)()
            except RuntimeError:
                continue

    @property
    def parked(self) -> bool:
        return self._parked

    # ── content ────────────────────────────────────────────────────────────
    def add_user(self, text: str) -> None:
        self._add("user", text)

    def add_cel(self, text: str) -> None:
        self._add("cel", _strip_mood_line(text))

    def _add(self, role: str, text: str) -> None:
        if not str(text or "").strip():
            return
        try:
            b = LiveBubble(role, str(text), self)
        except RuntimeError:
            return
        if self._parked:
            # Sidebar is up: arrive invisible, join the others on unpark
            # instead of popping under the panel.
            b.park()
        self._bubbles.append(b)
        align = (Qt.AlignmentFlag.AlignRight if role == "user"
                 else Qt.AlignmentFlag.AlignLeft)
        self._col.addWidget(b, 0, align)
        while len(self._bubbles) > _MAX_BUBBLES:
            old = self._bubbles.popleft()
            try:
                self._col.removeWidget(old)
            except RuntimeError:
                continue
            old.dissolve_out()

    def clear(self, immediate: bool = False) -> None:
        """Drop every bubble - animated by default, instantly on (re)entry."""
        while self._bubbles:
            b = self._bubbles.popleft()
            try:
                self._col.removeWidget(b)
            except RuntimeError:
                continue
            if immediate:
                b.deleteLater()
            else:
                b.dissolve_out()

    def populate(self, messages: Iterable[dict]) -> None:
        """Reset to the session so far when a call connects."""
        self.clear(immediate=True)
        for m in messages or []:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            if role == "user":
                self.add_user(m.get("content"))
            elif role == "assistant":
                self.add_cel(m.get("content"))


class LiveHistoryPanel(QWidget):
    """Right-side slide-in sidebar with the whole session, read-only."""

    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.is_open = False
        self._anim: Optional[QPropertyAnimation] = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(
            "LiveHistoryPanel{background: rgba(9, 5, 22, 0.94);"
            "border-left: 1.5px solid rgba(168, 85, 247, 0.55);}")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 14, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("🕘  Session history")
        title.setStyleSheet(
            "color: #F4F1FF; font-size: 15px; font-weight: bold;"
            "border: none; background: transparent;")
        head.addWidget(title)
        head.addStretch(1)
        self._btn_close = QPushButton("✕")
        self._btn_close.setFixedSize(28, 28)
        self._btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_close.setStyleSheet(
            "QPushButton{background: rgba(239, 68, 68, 0.22); color: #FECACA;"
            "border: 1px solid rgba(248, 113, 113, 0.5); border-radius: 14px;"
            "font-weight: bold; font-size: 12px;}"
            "QPushButton:hover{background: rgba(239, 68, 68, 0.55);}")
        self._btn_close.clicked.connect(self.closed)
        head.addWidget(self._btn_close)
        root.addLayout(head)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea{background: transparent; border: none;}"
            "QScrollBar:vertical{background: rgba(255,255,255,0.06);"
            " width: 8px; border-radius: 4px; margin: 0;}"
            "QScrollBar::handle:vertical{background: rgba(192,132,252,0.55);"
            " border-radius: 4px; min-height: 24px;}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{"
            " height: 0; width: 0;}")
        self._rows = QWidget()
        self._rows.setStyleSheet("background: transparent;")
        self._col = QVBoxLayout(self._rows)
        self._col.setContentsMargins(0, 0, 4, 0)
        self._col.setSpacing(8)
        self._col.addStretch(1)
        self._scroll.setWidget(self._rows)
        root.addWidget(self._scroll, 1)

        self.hide()

    # ── slide property ─────────────────────────────────────────────────────
    @Property(float)
    def slideX(self) -> float:
        return float(self.x())

    @slideX.setter
    def slideX(self, x) -> None:
        self.move(int(x), 0)

    # ── content ────────────────────────────────────────────────────────────
    def populate(self, messages: Iterable[dict]) -> None:
        while self._col.count() > 1:
            item = self._col.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        added = 0
        insert_at = self._col.count() - 1
        for m in messages or []:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            if role not in ("user", "assistant"):
                continue
            content = str(m.get("content") or "").strip()
            if not content:
                continue
            content = _display_text(content)
            if not content:
                continue
            self._col.insertWidget(insert_at, self._make_row(role, content))
            added += 1
        if not added:
            empty = QLabel("No messages yet - everything you say on this call "
                           "lands in the chat when you hang up. 💬")
            empty.setWordWrap(True)
            empty.setStyleSheet(
                "color: rgba(233, 213, 255, 0.55); font-size: 12px;"
                "border: none; background: transparent;")
            self._col.insertWidget(insert_at, empty)

    def add_turn(self, role: str, content: str) -> None:
        """Dynamically append a new turn so the open history panel stays live."""
        content = _display_text(content)
        if not content:
            return
        insert_at = max(0, self._col.count() - 1)
        self._col.insertWidget(insert_at, self._make_row(role, content))
        QTimer.singleShot(40, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        ))

    def _make_row(self, role: str, content: str) -> QFrame:
        fr = QFrame()
        fr.setStyleSheet(
            "QFrame{background: rgba(255, 255, 255, 0.05);"
            "border: 1px solid rgba(168, 85, 247, 0.28); border-radius: 10px;}"
            "QLabel{background: transparent; border: none;}")
        v = QVBoxLayout(fr)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(4)
        who = QLabel("YOU" if role == "user" else "CEL")
        who.setStyleSheet(
            "color: #C084FC; font-size: 9px; font-weight: bold;"
            "letter-spacing: 1px; border: none; background: transparent;"
            if role == "user" else
            "color: #6EE7B7; font-size: 9px; font-weight: bold;"
            "letter-spacing: 1px; border: none; background: transparent;")
        # Clean interface by default: the floating YOU/CEL name tags only
        # appear when the user ticks 👤 "Display names of animation" in Live
        # Mode settings (live_show_names).
        try:
            _app = self.window()
            show_names = bool((getattr(_app, "settings", {}) or {}).get(
                "live_show_names", False))
        except Exception:
            show_names = False
        who.setVisible(show_names)
        fr._who_label = who   # lets the settings toggle flip existing rows
        v.addWidget(who)
        txt = QLabel(content)
        txt.setWordWrap(True)
        txt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        txt.setStyleSheet(
            "color: rgba(233, 213, 255, 0.88); font-size: 12px;"
            "border: none; background: transparent;")
        v.addWidget(txt)
        return fr

    # ── open / close ───────────────────────────────────────────────────────
    def set_open(self, on: bool) -> None:
        on = bool(on)
        if on == self.is_open:
            return
        parent = self.parentWidget()
        self.is_open = on
        if parent is None:
            self.setVisible(on)
            return
        pw = parent.width()
        target = float((pw - self.width()) if on else pw)
        if on:
            self.move(pw, 0)
            self.show()
            self.raise_()
        self._anim = QPropertyAnimation(self, b"slideX", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(float(self.x()))
        self._anim.setEndValue(target)
        self._anim.finished.connect(self._on_slide_done)
        self._anim.start()

    def _on_slide_done(self) -> None:
        if not self.is_open:
            self.hide()


# ── Screenshot 9 Fix: Strip mood: in LiveTranscript & Keep Bubbles Inside Margins ──
from cellium.core.utils import clean_chat_display, split_mood_first

if "LiveBubble" in globals():
    _orig_lb_init = LiveBubble.__init__
    def _clean_lb_init(self, role: str, text: str = "", *args, **kwargs):
        cleaned, _ = split_mood_first(text or "")
        cleaned = clean_chat_display(cleaned)
        _orig_lb_init(self, role, cleaned, *args, **kwargs)
        self.setMaximumWidth(520)

    LiveBubble.__init__ = _clean_lb_init

if "LiveTranscript" in globals():
    _orig_lt_add_cel = getattr(LiveTranscript, "add_cel", None)
    _orig_lt_add_user = getattr(LiveTranscript, "add_user", None)
    _orig_lt_update = getattr(LiveTranscript, "update_last_cel", None) or getattr(LiveTranscript, "set_stream_text", None)

    if _orig_lt_add_cel is not None:
        def _patched_lt_add_cel(self, text: str):
            c, _ = split_mood_first(text or "")
            c = clean_chat_display(c)
            return _orig_lt_add_cel(self, c)
        LiveTranscript.add_cel = _patched_lt_add_cel

    if _orig_lt_update is not None:
        _u_name = "update_last_cel" if hasattr(LiveTranscript, "update_last_cel") else "set_stream_text"
        def _patched_lt_update(self, text: str):
            c, _ = split_mood_first(text or "")
            c = clean_chat_display(c)
            return _orig_lt_update(self, c)
        setattr(LiveTranscript, _u_name, _patched_lt_update)
