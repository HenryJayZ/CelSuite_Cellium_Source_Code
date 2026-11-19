"""CelAS Live Mode - full-screen voice companion shell.

Pressing **Live** beside send clears the entire GUI and leaves nothing but Cel,
full screen, talking. Hanging up restores every panel exactly as it was.

Design notes (see ``CELAS_LIVE_MODE_SPEC.md``):

* The host GUI is **hidden and shown, never rebuilt** - rebuilding loses scroll
  position and re-pays layout cost, which is exactly bug #1 ("switching chats is
  slow"). Visibility of every chrome widget is recorded on entry and restored.
* ``enter``/``exit`` are idempotent and re-entrant, so a double-click cannot
  half-hide the UI.
* No worker thread ever touches a widget. Audio workers only emit signals.
* Audio is optional: with no microphone or no TTS engine the shell still runs,
  so Live Mode is never the thing that breaks the app.
"""

from __future__ import annotations

import math
import random
import re
import time
from enum import Enum
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QElapsedTimer, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QLinearGradient
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

from ..avatar.library import AvatarLibrary
from ...core.config import ASSETS_DIR, stt_missing_key
from ..avatar.pet import MOODS, CompanionStage
from ..avatar.studio import AvatarStage
from ..avatar.widget import AvatarView
from .talk_animation import TalkEnvelope, talking_expression
from .controls import LiveControlBar

__all__ = ["LiveState", "LiveCaptions", "LiveStage", "LiveModeController",
           "LIVE_RULES", "extract_mood"]

#: Appended to the system prompt for the duration of one live turn. A call is
#: spoken, not read: a wall of markdown read aloud is unusable, and it is why
#: replies used to run long enough that you talked over her.
LIVE_RULES = ""

#: Base expressions that must never be used as a live/idle face: they are
#: literally empty, or they depict a crash. This is the trap that made Live
#: Mode look like a blank screen - ``MOODS["idle"]`` fell through to "Blank".
_UNUSABLE = frozenset({
    "blank", "none", "dead", "deadpan", "api crash", "net crash",
    "error 404", "dizzy", "hypnotized",
})

#: Words that mark a face as a *reaction*, never an idle rotation.
_NOT_IDLE = ("scared", "terrified", "fearful", "crying", "sobbing", "doomer",
             "menacing", "yandere", "gremlin", "rage", "angry", "annoyed",
             "disgusted", "flustered", "heavy", "dizzy", "error", "crash",
             "sick", "hypnotized", "relieved")

#: Real base names, most-welcoming first - the face Cel greets you with.
#: Happy / Excited / Laughing rank last *on purpose*: their JSON carries no
#: mouth points at all (eyebrows + eyes + blush only), so on a full-screen
#: call they read as a face with the lower half missing.
_PREFERRED_LIVE_FACES = (
    "Kawaii", "Chibi Joy", "UwU", "Relieved", "Side Eye",
    "Winking", "Sparkle Hype", "Happy", "Excited", "Laughing",
)

#: Kinds that make up a mouth - same set ``variants.py`` uses.
_MOUTH_KINDS = frozenset({"stem", "bottom_bar", "mid_bar"})


def _has_mouth(expr) -> bool:
    """True when the expression actually draws a lower half."""
    if expr is None:
        return False
    try:
        groups = expr.by_kind()
    except Exception:
        return False
    return any(k in _MOUTH_KINDS for k in groups)


class LiveState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


STATE_LABEL = {
    LiveState.IDLE: "",
    LiveState.LISTENING: "Listening…",
    LiveState.THINKING: "Cel is thinking…",
    LiveState.SPEAKING: "",
}

_EMOJI_MOOD_MAP = {
    "😄": "happy", "😊": "warm", "🥰": "love", "💅": "sassy",
    "😴": "sleepy", "🥺": "pleading", "😤": "proud", "🤔": "thinking",
    "😳": "confused", "😍": "love", "😢": "sad", "😱": "shocked",
    "🔥": "excited", "✨": "playful", "❤️": "love", "💖": "love",
    "💃": "excited", "🎉": "excited", "😏": "playful", "🛠️": "working"
}

_MOOD_LINE = re.compile(
    r"(?i)\b(?:[*_]{1,2})?[ \t]*(?:mood|emotions?)[ \t]*:[ \t]*(?:[*_]{1,2})?[ \t]*([a-zA-Z_,\s\U00010000-\U0010ffff\u2600-\u27bf]+)(?:[.!?\n]|$)"
)


#: Bug 12 safety net: models love inventing feeling names ("Mood: Crazy",
#: "mischief"). Unknown keys used to resolve to None and freeze the face
#: forever - every free-form word here maps onto a REAL MOODS key instead.
_MOOD_FREEFORM_SYNONYMS = {
    "crazy": "gremlin", "chaotic": "gremlin", "chaos": "gremlin",
    "feral": "gremlin", "unhinged": "gremlin",
    "hyped": "excited", "hype": "excited", "wild": "excited",
    "pumped": "excited", "energetic": "excited", "thrilled": "excited",
    "amazed": "shocked", "astonished": "shocked", "startled": "shocked",
    "curious": "confused", "puzzled": "confused", "intrigued": "confused",
    "cool": "playful", "chill": "playful", "cheeky": "playful",
    "smug": "proud", "cocky": "proud", "confident": "proud", "victory": "proud",
    "flirty": "warm", "cozy": "warm", "soft": "warm", "grateful": "warm",
    "affectionate": "love", "admiring": "love", "tender": "love",
    "annoyed": "sassy", "salty": "sassy", "snarky": "sassy", "irritated": "sassy",
    "scared": "worried", "nervous": "worried", "anxious": "worried",
    "afraid": "worried", "stressed": "worried",
    "exhausted": "tired", "drained": "tired", "drowsy": "sleepy", "zzz": "sleepy",
    "upset": "sad", "down": "sad", "lonely": "sad", "disappointed": "sad",
    "focused": "working", "busy": "working", "coding": "working",
    "joy": "happy", "cheerful": "happy", "glad": "happy", "delighted": "happy",
    "pensive": "thinking", "pondering": "thinking", "musing": "thinking",
    "fine": "idle", "neutral": "idle", "okay": "idle",
}


def _fuzzy_mood_key(token: str) -> Optional[str]:
    """Map a model-invented feeling onto a REAL mood key (never None if close)."""
    tok = str(token or "").strip().lower()
    if not tok:
        return None
    if tok in MOODS:
        return tok
    syn = _MOOD_FREEFORM_SYNONYMS.get(tok)
    if syn and syn in MOODS:
        return syn
    try:
        import difflib
        close = difflib.get_close_matches(tok, MOODS.keys(), n=1, cutoff=0.55)
    except Exception:
        close = []
    return close[0] if close else None


def extract_mood(text: str) -> "tuple[str, Optional[str]]":
    """Split a reply into ``(display_text, mood_key)``.

    First-line mood contract: the FIRST full mood line wins (it arrives in
    the first streamed chunk, so the face reacts instantly), every mood line
    is stripped from display/TTS, and the value is validated against MOODS  - 
    garbage parses to None instead of a stuck face. Supports compound
    comma-separated moods (up to 3, played in sequence).
    """
    from cellium.core.utils import split_mood_first
    text = str(text or "")
    cleaned, raw = split_mood_first(text)
    if not raw:
        return cleaned, None

    # Check for emojis
    for emo, key in _EMOJI_MOOD_MAP.items():
        if emo in raw:
            return cleaned, key

    # Handle compound comma-separated moods (e.g. "excited, warm"). Bug 12:
    # invented keys ("Crazy") froze the face - fuzzy-map them onto REAL keys.
    mood_tokens = [m.strip() for m in raw.split(",") if m.strip()]
    resolved, seen = [], set()
    for tok in mood_tokens:
        key = _fuzzy_mood_key(tok)
        if key and key not in seen:
            seen.add(key)
            resolved.append(key)
    if resolved:
        # Return comma-resolved valid moods for sequential playback
        return cleaned, ",".join(resolved[:3])
    return cleaned, None


class LiveCaptions(QWidget):
    """Bottom caption bar: status line, live word text, and a mic VU meter."""

    #: Hold-to-talk pill - only ever shown when PTT is enabled in settings.
    ptt_pressed = Signal()
    ptt_released = Signal()

    #: Captions are a glance, not the transcript - the bubble column on the
    #: right keeps the full text. Long enough for two or three sentences.
    _MAX_CAPTION = 420
    #: …and never taller than this many lines. A word-wrapped QLabel whose
    #: height comes from its own sizeHint gets *shorter* the moment the column
    #: narrows, so a three-line reply was drawn through a two-line box and
    #: clipped at both ends. Height is therefore fixed and the text elided.
    _MAX_CAPTION_LINES = 3

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # Deliberately NOT transparent-for-mouse: that attribute covers the
        # widget *and its children*, so with it on the hold-to-talk pill was a
        # button nobody could press - QApplication.widgetAt() over its centre
        # returned the avatar behind it, and every click did nothing. Only the
        # decorative labels opt out, one by one.
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 10, 24, 18)
        lay.setSpacing(8)

        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                                 True)
        self.status.setStyleSheet(
            "color:#C084FC; font-size:13px; font-weight:600; background:transparent;")

        # ── Hold to talk ──────────────────────────────────────────────
        # With push-to-talk off the mic is *always* open, so a hold button
        # would be a lie. With it on, the only way to talk is a key that is
        # not labelled anywhere on screen - so the button sits directly above
        # the "Listening…" line, and only then.
        self.ptt = QPushButton("Hold to talk", self)
        # A drawn mic, not an emoji: 🎙 in a button renders as a colour blob
        # that fights the theme and breaks at other font sizes.
        self.ptt.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_mic.svg")))
        self.ptt.setIconSize(QSize(15, 15))
        self._ptt_idle_text = "Hold to talk"
        self._ptt_live_text = "Listening - release to send"
        self._transcribing = False
        self._content_w = 0
        self.ptt.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ptt.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ptt.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                              False)
        self.ptt.setToolTip(
            "Push to talk - hold to let Cel hear you, release to send. "
            "(Space works too.)")
        self.ptt.setStyleSheet("""
            QPushButton {
                background: rgba(20, 12, 40, 0.78);
                color: #E9D5FF;
                border: 1.5px solid rgba(192, 132, 252, 0.55);
                /* Must stay under half the button's height (36px -> 18):
                   Qt silently drops an over-large radius and draws a hard
                   rectangle, which is how the pill looked like a text box. */
                border-radius: 16px;
                padding: 7px 22px;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: rgba(147, 51, 234, 0.55);
                border-color: #E879F9;
            }
            QPushButton:pressed {
                background: rgba(16, 185, 129, 0.65);
                border-color: #6EE7B7;
                color: #FFFFFF;
            }
        """)
        self.ptt.pressed.connect(self.ptt_pressed)
        self.ptt.released.connect(self.ptt_released)
        self._ptt_row = QWidget(self)
        self._ptt_row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                                   False)
        _pl = QHBoxLayout(self._ptt_row)
        _pl.setContentsMargins(0, 0, 0, 6)
        _pl.setSpacing(0)
        _pl.addStretch(1)
        _pl.addWidget(self.ptt)
        _pl.addStretch(1)
        self._ptt_row.setVisible(False)

        self.caption = QLabel("")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setWordWrap(True)
        self.caption.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.caption.setStyleSheet(
            "color:#F4F1FF; font-size:19px; background:transparent;")

        self.vu = _VuMeter()
        self.vu.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                             True)
        self.vu.setFixedHeight(4)
        # A full-width level bar reads as a stray divider line; a short
        # centred track reads as the meter it is.
        self.vu.setFixedWidth(260)

        lay.addStretch(1)
        # AlignHCenter on every row: each label keeps its *natural* width up to
        # set_content_width(), so a short line sits centred instead of being
        # stretched across the whole stage - which is exactly what let it run
        # its text straight under the floating control circles on the left.
        lay.addWidget(self._ptt_row, 0, Qt.AlignHCenter)
        lay.addWidget(self.status, 0, Qt.AlignHCenter)
        lay.addWidget(self.caption, 0, Qt.AlignHCenter)
        lay.addWidget(self.vu, 0, Qt.AlignHCenter)

    def set_content_width(self, width: int) -> None:
        """Bound the caption/status column to the free space on screen.

        The gap between the round controls (bottom-left) and the transcript
        column (right). Without this the labels were laid out across the entire
        stage, so one line of reply was measured against the full window width
        and ran underneath the buttons.
        """
        try:
            w = max(240, int(width))
            self._content_w = w
            for wdg in [x for x in (getattr(self, "status", None), getattr(self, "caption", None)) if x is not None]:
                wdg.setMaximumWidth(w)
            self._fix_caption_height()
            self.set_caption(self.caption.text())
        except (RuntimeError, TypeError, ValueError):
            pass

    def _fix_caption_height(self) -> None:
        """Pin the caption to exactly the lines it is allowed to use."""
        if not self._content_w:
            return
        try:
            fm = self.caption.fontMetrics()
            self.caption.setFixedHeight(fm.height() * self._MAX_CAPTION_LINES)
            self.status.setFixedHeight(fm.height())
            self._ptt_row.setFixedHeight(self.ptt.sizeHint().height() + 6)
        except RuntimeError:
            pass

    def set_state(self, state: LiveState) -> None:
        if state is LiveState.LISTENING and self._ptt_row.isVisible():
            if getattr(self, "_transcribing", False):
                self.status.setText("Transcribing…")
            elif getattr(self, "_ptt_on", False):
                self.status.setText("Listening - release to send")
            else:
                self.status.setText("Waiting… (Hold [SPACE])")
        else:
            self.status.setText(STATE_LABEL.get(state, ""))

    def set_ptt_active(self, on: bool) -> None:
        """Prove the press registered.

        A hold-to-talk button that gives no feedback reads as a broken button,
        so the label itself reports the state and flips the icon colour.
        """
        self._ptt_on = bool(on)
        self._refresh_ptt()

    def set_transcribing(self, on: bool) -> None:
        """Show that the clip is being turned into words.

        The recording has stopped but nothing has happened on screen for the
        second or two a transcription takes, which reads as a dead button.
        """
        self._transcribing = bool(on)
        self._refresh_ptt()

    def _refresh_ptt(self) -> None:
        """One place decides the pill's text + icon, so the three states
        (idle / listening / transcribing) can never contradict each other."""
        if self._transcribing:
            text = "Transcribing…"
            icon = "ui_transcribe.svg"
            if hasattr(self, "lbl_status"):
                self.lbl_status.setText("Transcribing…")
        elif getattr(self, "_ptt_on", False):
            text = self._ptt_live_text
            icon = "ui_mic_live.svg"
            if hasattr(self, "lbl_status"):
                self.lbl_status.setText("Listening…")
        else:
            text = getattr(self, "_ptt_idle_text", "Hold to talk")
            icon = "ui_mic.svg"
            if hasattr(self, "lbl_status"):
                self.lbl_status.setText("Waiting… (Hold [SPACE])")
        try:
            self.ptt.setText(text)
            path = ASSETS_DIR / "icons" / icon
            # The transcribing glyph is optional; never lose the state text
            # over a missing file.
            if not path.exists() and icon != "ui_mic.svg":
                path = ASSETS_DIR / "icons" / "ui_mic.svg"
            self.ptt.setIcon(QIcon(str(path)))
        except RuntimeError:
            pass

    def set_push_to_talk(self, on: bool) -> None:
        """Show the hold-to-talk pill only when PTT is actually enabled."""
        try:
            self._ptt_row.setVisible(bool(on))
        except RuntimeError:
            pass

    def push_to_talk_visible(self) -> bool:
        # isHidden(), not isVisible(): a caption bar whose window is not on
        # screen yet must still report the *setting* it was given.
        try:
            return not self._ptt_row.isHidden()
        except RuntimeError:
            return False

    def set_caption(self, text: str) -> None:
        t = str(text or "")
        if len(t) > self._MAX_CAPTION:
            cut = t[:self._MAX_CAPTION].rsplit(" ", 1)[0].rstrip()
            t = (cut or t[:self._MAX_CAPTION]) + "…"
        if self._content_w and t:
            # Elide to the lines we actually have room for, so the text can
            # never outgrow its own box.
            try:
                t = self.caption.fontMetrics().elidedText(
                    t, Qt.TextElideMode.ElideRight, self._content_w,
                    self._MAX_CAPTION_LINES)
            except (RuntimeError, TypeError):
                pass
        self.caption.setText(t)

    def set_level(self, rms: float) -> None:
        self.vu.set_level(rms)


class _VuMeter(QWidget):
    """Slim level bar. Audio VU meter + thinking progress bar + status color shifts."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._level = 0.0
        self._target = 0.0
        self._phase = 0.0
        self._mode = "listening"  # "listening", "thinking", "done"
        self._flash_green = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_mode(self, mode: str) -> None:
        if mode == "done":
            self._flash_green = 1.0
            self._mode = "listening"
        else:
            self._mode = mode
        self.update()

    def set_level(self, rms: float) -> None:
        try:
            v = max(0.0, min(1.0, float(rms) * 12.0))
        except (TypeError, ValueError):
            v = 0.0
        self._target = v

    def _tick(self) -> None:
        cur, tgt = self._level, self._target
        if abs(tgt - cur) > 0.0005:
            self._level = cur + (tgt - cur) * (0.45 if tgt > cur else 0.10)
        self._phase = (self._phase + 0.12) % (math.tau)
        if self._flash_green > 0.0:
            self._flash_green = max(0.0, self._flash_green - 0.05)
        self.update()

    def dispose(self) -> None:
        self._timer.stop()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        r = self.rect()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 26))
        p.drawRoundedRect(r, 2, 2)

        if self._flash_green > 0.0:
            # Flash vibrant emerald green on finish
            p.setBrush(QColor(16, 185, 129, int(255 * self._flash_green)))
            p.drawRoundedRect(r, 2, 2)
        elif self._mode == "thinking":
            # Oscillating red/coral progress bar while thinking
            osc = 0.5 + 0.5 * math.sin(self._phase * 4)
            bar_w = r.width() * 0.35
            x = (r.width() - bar_w) * osc
            p.setBrush(QColor("#EF4444"))
            p.drawRoundedRect(x, 0, bar_w, r.height(), 2, 2)
        elif self._level > 0.01:
            pulse = 0.94 + 0.06 * math.sin(self._phase * 2)
            w = max(3.0, r.width() * self._level * pulse)
            p.setBrush(QColor("#C084FC"))
            p.drawRoundedRect(0, 0, w, r.height(), 2, 2)
        p.end()


class LiveInput(QWidget):
    """Bottom text field - a call still needs a keyboard.

    The chat input is hidden while Live Mode owns the screen, so typing to Cel
    during a call was impossible. This pill sits above End call and submits
    through the exact same path as a spoken transcript.
    """

    submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(46)
        # A plain QWidget needs this or the stylesheet background never paints.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # No selector: a bare declaration is what actually paints on a plain
        # QWidget subclass (a `LiveInput{...}` rule silently matched nothing).
        self.setStyleSheet(
            "background: rgba(10, 6, 24, 0.80);"
            "border: 1.5px solid rgba(192, 132, 252, 0.55);"
            "border-radius: 23px;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 4, 5, 4)
        lay.setSpacing(4)

        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("Type to Cel…   ⏎ sends")
        self.edit.setStyleSheet(
            "QLineEdit{background: transparent; border: none; color: #F4F1FF;"
            "font-size: 15px;"
            "selection-background-color: rgba(147, 51, 234, 0.55);}")
        self.edit.returnPressed.connect(self._send)

        self.btn = QPushButton(self)
        self.btn.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_send.svg")))
        self.btn.setIconSize(QSize(18, 18))
        self.btn.setFixedSize(36, 36)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setToolTip("Send to Cel")
        self.btn.setStyleSheet(
            "QPushButton{background: rgba(147, 51, 234, 0.75); border: none;"
            "border-radius: 18px;}"
            "QPushButton:hover{background: #9333EA;}")
        self.btn.clicked.connect(self._send)

        lay.addWidget(self.edit, 1)
        lay.addWidget(self.btn)

    def _send(self) -> None:
        text = self.edit.text().strip()
        if not text:
            return
        self.edit.clear()
        self.submitted.emit(text)

    def focus_edit(self) -> None:
        self.edit.setFocus(Qt.FocusReason.OtherFocusReason)


from .transcript import LiveHistoryPanel, LiveTranscript


class _FadeCurtain(QWidget):
    """Solid veil that fades the whole stage out.

    A full-stage ``QGraphicsOpacityEffect`` re-renders every child (glass
    backdrop snapshots included) on each opacity tick - measured 0.4–1 s paint
    stalls under software rendering, enough to swallow the entire outro window.
    One fill-rect veil costs ~nothing per tick.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._alpha = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setGeometry(parent.rect())

    def set_alpha(self, a: float) -> None:
        self._alpha = max(0.0, min(1.0, a))
        self.update()

    def paintEvent(self, ev) -> None:
        if self._alpha <= 0.0:
            return
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, int(round(self._alpha * 255))))
        p.end()
 
 
class LiveStage(QWidget):
    """Full-screen Cel. Gradient backdrop, large avatar, captions, hang-up."""

    end_requested = Signal()
    #: User typed into the call's text box.
    text_submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None, gender: str = "Female"):
        super().__init__(parent)
        self.gender = gender
        self.library: Optional[AvatarLibrary] = None
        # The stage itself must be able to take the keyboard: push-to-talk is
        # a held key, and if the text box owns focus at call entry the key goes
        # to the line edit and the mic never opens. Escape hands focus back.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.backdrop = AvatarStage(self)

        # The scrim dims the *backdrop* so Live Mode reads as a call screen  - 
        # and it is deliberately created BEFORE the avatar: Qt paints children
        # in creation order, so a scrim above Cel is exactly what put her
        # behind purple glass and drained the colour out of every dot.
        self._scrim = QWidget(self)
        self._scrim.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._scrim.setStyleSheet("background: rgba(3, 1, 12, 0.52);")

        self.avatar = AvatarView(parent=self, scale=1.0)
        # No face plate on a call: the 600x400 box has ~70u of empty padding
        # around the face, and a filled plate would park that padding on top
        # of the captions and text box. The scrim already gives the dots
        # all the contrast they need.
        self.avatar.set_plate(False)

        # Round model / agent / voice controls - the call's only chrome.
        self.controls = LiveControlBar(self)

        # Idle rotation: without it Live Mode froze on one face and looked
        # "blank" - the archive cycled expressions continuously.
        self._rng = random.Random(0xCE11)
        self._idle_names: list = []
        self._current_expr_name = None
        self._manual_until = 0.0
        self._attentive = False
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(6500)
        self._idle_timer.timeout.connect(self._rotate_idle)

        # Warm the expression library in the background - but in SMALL SLICES
        # and only after the window has settled. The old `singleShot(900)` fired
        # during launch and parsed all 1,520 expressions in one go (~1.5 s of
        # frozen UI right after the window appeared). Chunked loading keeps
        # every frame responsive; opening Live early drains the rest in one go.
        QTimer.singleShot(2500, self._start_background_library_load)
        self.captions = LiveCaptions(self)
        # Type-to-Cel: the chat box is hidden during a call, so without this
        # there was no way to type while she speaks.
        self.input = LiveInput(self)
        self.input.submitted.connect(self.text_submitted.emit)

        # Fading conversation column + slide-in session sidebar (F2).
        self.transcript = LiveTranscript(self)
        self.history = LiveHistoryPanel(self)

        btn = QPushButton("End call")
        btn.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_phone_off.svg")))
        btn.setIconSize(QSize(16, 16))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            # 18, not 22: the pill is ~39px tall and Qt discards a radius
            # larger than half the height, leaving a square red box.
            "QPushButton{background:rgba(239,68,68,0.85);color:#fff;border:none;"
            "border-radius:18px;padding:11px 26px;font-size:14px;font-weight:700;}"
            "QPushButton:hover{background:#ef4444;}")
        btn.clicked.connect(self.end_requested.emit)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.captions, stretch=1)
        # Layout-managed, not floating: the text box used to be absolutely
        # positioned and sat on top of the caption bar's VU meter. The
        # invisible side spacers keep it clear of the round controls (left)
        # and the transcript column (right) at every window width.
        self._in_sp_l = QWidget(self)
        self._in_sp_r = QWidget(self)
        self._in_sp_l.setFixedWidth(0)
        self._in_sp_r.setFixedWidth(0)
        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(0)
        input_row.addWidget(self._in_sp_l)
        input_row.addWidget(self.input, 1, Qt.AlignHCenter)
        input_row.addWidget(self._in_sp_r)
        root.addLayout(input_row)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 40)
        btn_row.addStretch(1)
        btn_row.addWidget(btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self._t = QTimer(self)
        self._t.setInterval(33)

    # ── avatar ───────────────────────────────────────────────────────────
    def load_library(self, blocking: bool = False) -> None:
        """Load the expression library off the UI path (non-blocking default)."""
        if self.library is not None:
            # A chunked background load may still be mid-way. Live is being
            # entered now, so finish whatever is left in one pass (~1 s worst
            # case, only if Live is opened within a few seconds of launch).
            it = getattr(self, "_bg_lib_iter", None)
            if it is not None:
                try:
                    for _ in it:
                        pass
                except Exception:
                    pass
                self._bg_lib_iter = None
                timer = getattr(self, "_bg_lib_timer", None)
                if timer is not None:
                    try:
                        timer.stop()
                    except Exception:
                        pass
            return
        try:
            self.library = AvatarLibrary()
        except Exception:
            self.library = None

    def _start_background_library_load(self) -> None:
        """Begin parsing the avatar library in tiny event-loop-friendly slices.

        Nothing calls this until ~2.5 s after boot, and each tick parses only
        16 files (~60 ms), so the welcome orb, typewriter and wallpaper all
        stay smooth while the library warms up.
        """
        if self.library is not None:
            return  # already adopted (desktop companion) or fully loaded
        try:
            self.library = AvatarLibrary(autoload=False)
        except Exception:
            self.library = None
            return
        try:
            gender = getattr(self, "gender", "Female") or "Female"
            self._bg_lib_iter = self.library.load_gender(gender, batch_size=16)
            self._bg_lib_timer = QTimer(self)
            self._bg_lib_timer.setInterval(0)
            self._bg_lib_timer.timeout.connect(self._pump_background_library)
            self._bg_lib_timer.start()
        except Exception:
            self._bg_lib_iter = None

    def _pump_background_library(self) -> None:
        """Parse one 16-file slice, then yield back to the event loop."""
        it = getattr(self, "_bg_lib_iter", None)
        if it is None:
            return
        try:
            next(it)
        except StopIteration:
            self._bg_lib_iter = None
            timer = getattr(self, "_bg_lib_timer", None)
            if timer is not None:
                timer.stop()
        except Exception:
            self._bg_lib_iter = None
            timer = getattr(self, "_bg_lib_timer", None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass

    def set_library(self, library) -> None:
        """Adopt an already-parsed library.

        Parsing all 1,520 expressions blocks the event loop for ~1.5s. The
        desktop companion has already paid that cost by the time anyone can
        click Live, so reuse its instance instead of freezing the call screen.
        """
        if library is not None:
            self.library = library

    def _first_expression(self):
        """Pick a *good* base face - never a modifier, blank or crash face.

        Prefers the welcoming set *and* a real mouth: Cel opening a call with
        eyebrows, eyes and no mouth looks half-rendered.
        """
        if self.library is None:
            return None
        by_name = {n: self.library.get(self.gender, n)
                   for n in self.library.names(self.gender)}
        for with_mouth in (True, False):
            for cand in _PREFERRED_LIVE_FACES:
                e = by_name.get(cand)
                if e is not None and (not with_mouth or _has_mouth(e)):
                    return e
        for n, e in by_name.items():
            if (e is not None and e.modifier is None
                    and n.lower() not in _UNUSABLE and _has_mouth(e)):
                return e
        return next(iter(by_name.values()), None)

    def hold_rotation(self, seconds: float = 3.0) -> None:
        """Freeze idle rotation while the controller drives the face."""
        self._manual_until = time.monotonic() + max(0.0, seconds)

    def _idle_pool(self) -> list:
        """Base expressions worth rotating through - the archive's face set.

        Mouth-less bases (Happy, Excited, Laughing …) are dropped when any
        mouth-ed face exists: a rotating face that loses its lower half reads
        as a rendering bug, not as an expression.
        """
        if self.library is None:
            return []
        if self._idle_names:
            return self._idle_names
        usable, full = [], []
        for n in self.library.names(self.gender):
            e = self.library.get(self.gender, n)
            if e is None or e.modifier is not None:
                continue
            if n.lower() in _UNUSABLE:
                continue
            # Reaction faces are for replies, not idle ambience - rotating into
            # "Scared" two seconds after "Happy" reads as broken.
            if any(w in n.lower() for w in _NOT_IDLE):
                continue
            usable.append(n)
            if _has_mouth(e):
                full.append(n)
        out = full or usable
        self._idle_names = out
        return out

    def _rotate_idle(self) -> None:
        """State machine for avatar fatigue & sleep (Bug 17.5)."""
        if self._attentive:
            return
        now = time.monotonic()
        if now < self._manual_until:
            return
        stage = getattr(self, "_fatigue_stage", "idle")
        last_t = getattr(self, "_fatigue_time", now)
        elapsed = now - last_t

        if stage == "reaction" and elapsed > 20.0:
            # Reaction hold completed -> transition to idle
            self._fatigue_stage = "idle"
            self._fatigue_time = now
            self.show_expression("idle")
        elif stage == "idle" and elapsed > 15.0:
            # 15s idle -> transition to tired
            self._fatigue_stage = "tired"
            self._fatigue_time = now
            self.show_expression("tired")
        elif stage == "tired" and elapsed > 10.0:
            # 10s tired -> transition to sleepy with floating Z particles
            self._fatigue_stage = "sleepy"
            self._fatigue_time = now
            self.show_expression("sleepy")

    def wake_avatar(self) -> None:
        """Wake up Cel on mouse hover: 3 quick blinks sequence and restore idle."""
        self._fatigue_stage = "idle"
        self._fatigue_time = time.monotonic()
        self.show_expression("idle")
        if hasattr(self.avatar, "blink_now"):
            for delay in (100, 350, 600):
                QTimer.singleShot(delay, self.avatar.blink_now)

    def mouseMoveEvent(self, event) -> None:
        if getattr(self, "_fatigue_stage", "idle") in ("tired", "sleepy"):
            self.wake_avatar()
        super().mouseMoveEvent(event)

    def _resolve_expression(self, name: str):
        """Resolve an exact expression title OR a lowercase mood key."""
        if self.library is None or not name:
            return None
        expr = self.library.get(self.gender, name)
        if expr is not None:
            return expr
        low = name.strip().lower()
        if low == "idle":
            pool = [n for n in self._idle_pool() if n != self._current_expr_name]
            if pool:
                return self.library.get(self.gender, self._rng.choice(pool))
            return self._first_expression()
        for cand in MOODS.get(low, ()):
            expr = self.library.get(self.gender, cand)
            if expr is not None:
                return expr
        return None

    def show_expression(self, name: str) -> bool:
        if self.library is None:
            return False
        expr = self._resolve_expression(name)
        if expr is None:
            return False
        low = str(name or "").strip().lower()
        if low in ("idle", "tired", "sleepy"):
            self._fatigue_stage = low
        else:
            # Hold reaction emotion for 15-35s before transitioning to idle
            self.hold_rotation(random.uniform(15.0, 35.0))
            self._fatigue_stage = "reaction"
        self._fatigue_time = time.monotonic()
        self._current_expr_name = expr.name
        self.avatar.set_expression(expr)
        self.update()
        return True

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._relayout()
        if not self._attentive:
            self._idle_timer.start()

    def set_attentive(self, on: bool) -> None:
        """Hold the face still while Cel is meant to be hearing you.

        Rotating random expressions mid-turn is what made Live Mode read as
        "she can't hear me" - a listening companion watches you instead.
        """
        self._attentive = bool(on)
        if self._attentive:
            self._idle_timer.stop()
        elif self.isVisible():
            self._idle_timer.start()

    def hideEvent(self, event) -> None:
        self._idle_timer.stop()
        super().hideEvent(event)

    def _relayout(self) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        self.backdrop.setGeometry(0, 0, w, h)
        self._scrim.setGeometry(0, 0, w, h)

        # Bottom band the face must stay clear of: captions + text box +
        # End call. She is sized against what is *left*, so a short window
        # shrinks her instead of letting the caption bar eat her chin.
        top, band = 16, 250
        avail_h = max(180, h - band - top)

        # Measured dot bounds are x 80..560 (480u) and y 29..359 (330u) of the
        # canonical 600x400 box - scale off the *face*, not the padded box.
        s = min(w * 0.86 / 480.0, avail_h * 0.95 / 330.0, 3.2)
        s = max(0.35, s)
        self.avatar.set_scale(s)

        # The avatar centres the full 600x400 box inside its own rect, so the
        # rect must be exactly 600s x 400s. The old 540x370 size shifted every
        # dot up-left by 30s x 15s - that was the "off-centre face" bug.
        bw, bh = int(600 * s), int(400 * s)
        self.avatar.setGeometry((w - bw) // 2,
                                top + max(0, (avail_h - bh) // 2), bw, bh)

        # The bar must be exactly as tall as its own hint: 3 rows of
        # (54px circle + caption + dot) need ~330px, and the old hard-coded
        # 96 squeezed every row to a 20px cell with a 4px holder - the
        # circles were sliced down to their top arc and the captions to a
        # 3px sliver.
        bs = self.controls.sizeHint()
        cw = max(240, bs.width())
        ch = max(96, bs.height())
        wide = w >= 1000
        if wide:
            # Bottom-left stack, sitting clear of the text pill and End call.
            self.controls.setGeometry(24, max(12, h - ch - 132), cw, ch)
            left_pad = 24 + cw + 36
        else:
            # Narrow window: move them out of the text box's way entirely.
            self.controls.setGeometry(16, 16, cw, ch)
            left_pad = 20

        # Conversation column (F2) - right edge, clear of the face.
        tw = min(330, max(260, int(w * 0.24)))
        right_pad = tw + 40

        # The caption/status column lives in the gap between the two, and is
        # never wider than that gap: this is what stops a reply from running
        # its text under the floating controls.
        self.captions.set_content_width(
            max(260, w - left_pad - right_pad - 28))

        # The pill lives between the spacers, so it can never slide under
        # the round controls or the transcript column at any window size.
        self._in_sp_l.setFixedWidth(left_pad if wide else 0)
        self._in_sp_r.setFixedWidth(right_pad)
        iw = max(220, min(640, w - left_pad - right_pad - 24))
        self.input.setFixedWidth(iw)

        self.transcript.setGeometry(w - tw - 18, 54, tw,
                                    max(150, h - 340))
        # History sidebar (F2) - parked off-screen until toggled.
        hw = min(360, max(280, int(w * 0.30)))
        hx = (w - hw) if self.history.is_open else w
        self.history.setGeometry(hx, 0, hw, h)

        # Paint order: scrim -> Cel -> chrome (raise_ is cheap and makes the
        # stacking explicit instead of relying on creation order).
        self.avatar.raise_()
        self.captions.raise_()
        self.input.raise_()
        self.transcript.raise_()
        self.controls.raise_()
        if self.history.is_open:
            self.history.raise_()

    def dispose(self) -> None:
        self._t.stop()
        try:
            self.backdrop.dispose()
        except Exception:
            pass
        try:
            self.avatar.dispose()
        except Exception:
            pass
        try:
            self.captions.vu.dispose()
        except Exception:
            pass


class LiveModeController(QObject):
    """Drives Live Mode and hides/restores the host GUI."""

    state_changed = Signal(str)
    ended = Signal()
    #: (engine, provider) - the selected speech engine needs an API key it does
    #: not have, so the call cannot hear anything yet. The host owns the prompt;
    #: the call itself only reports the gap.
    stt_key_required = Signal(str, str)

    def __init__(self, host: QWidget, stage: LiveStage,
                 hide_targets: Optional[List[QWidget]] = None,
                 silence_ms: int = 2000,
                 detector: Optional[Callable[[str], str]] = None,
                 settings: Optional[dict] = None):
        super().__init__(host)
        self.host = host
        self.stage = stage
        self.stage.end_requested.connect(self.exit_live)
        self.stage.text_submitted.connect(self._on_user_text)
        self._hide_targets = list(hide_targets or [])
        self._saved: Dict[QWidget, bool] = {}
        self.active = False
        self.state = LiveState.IDLE
        self.gender = "Female"
        self._exiting = False
        if isinstance(settings, dict):
            self.settings = settings
        else:
            # The host owns the live settings dict - *sharing* it is what
            # makes the STT engine pick, noise floor and strength actually
            # apply mid-call instead of falling back to hardcoded defaults.
            host_settings = getattr(host, "settings", None)
            self.settings = (host_settings if isinstance(host_settings, dict)
                             else {})

        self.silence_ms = max(200, int(silence_ms))
        try:
            self.silence_ms = max(
                400, int(self.settings.get("live_silence_ms", self.silence_ms)))
        except (TypeError, ValueError):
            pass
        self._silence_elapsed = 0.0
        self._level = 0.0
        self._barge_threshold = 0.020
        self._detector = detector
        #: Cel's reply as it streams in, and when the caption last repainted.
        self._stream_buf = ""
        self._stream_paint = 0.0

        self.audio = None
        try:
            from .audio import LiveAudio
            self.audio = LiveAudio(parent=self, settings=self.settings,
                                   silence_ms=self.silence_ms)
            self.audio.level.connect(self._on_audio_level)
            self.audio.transcript.connect(self._on_transcript)
            self.audio.error.connect(self._on_audio_error)
            self.audio.key_required.connect(self._on_key_required)
            self.audio.hint.connect(self._on_audio_hint)
            self.audio.busy.connect(self._on_audio_busy)
            # Wire PTT / auto-send / mute from settings
            self.audio.push_to_talk = bool(
                self.settings.get("live_push_to_talk", False))
            self.audio.auto_send = bool(
                self.settings.get("live_auto_send", True))
            self.audio.set_muted(bool(
                self.settings.get("live_mic_muted", False)))
        except Exception:
            self.audio = None  # audio is optional; Live Mode still runs

        # Hold-to-talk pill: shown only when the setting asks for it.
        try:
            self.stage.captions.ptt_pressed.connect(self._ptt_pressed)
            self.stage.captions.ptt_released.connect(self._ptt_released)
        except (AttributeError, RuntimeError):
            pass

        self.envelope = TalkEnvelope(hz=12.0)
        self._base_expression = None
        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

        # PTT key handling (Space by default)
        self._ptt_shortcut = None

    def ptt_binding(self) -> str:
        """The push-to-talk binding as Qt's portable text.

        ``"Space"``, ``"K"``, ``"Ctrl+Shift+M"``. An empty result means the
        user cleared the binding, which we treat as Space rather than as a
        dead key - the mic must never become unreachable.
        """
        from PySide6.QtGui import QKeySequence
        raw = str(self.settings.get("live_ptt_key", "Space") or "").strip()
        if not raw:
            return ""
        try:
            seq = QKeySequence(raw)
            if not seq.count():
                return ""
            # QKeySequence[i] is a QKeyCombination, not an int - converting it
            # naively raises, which silently pinned the key to Space.
            combined = int(seq[0].toCombined())
            return QKeySequence(combined).toString(
                QKeySequence.SequenceFormat.PortableText)
        except Exception:
            return ""

    # ── audio plumbing ───────────────────────────────────────────────────
    def _on_audio_level(self, rms: float) -> None:
        self.set_level(rms)
        try:
            if hasattr(self.stage, "backdrop") and hasattr(self.stage.backdrop, "set_audio_level"):
                self.stage.backdrop.set_audio_level(rms)
        except Exception:
            pass
        # Barge-in: the user started talking over Cel.
        if (self.active and self.state is LiveState.SPEAKING
                and rms >= self._barge_threshold):
            self._on_barge_in()

    def _on_barge_in(self) -> None:
        host = self.host
        for name in ("stop_current_tts",):
            fn = getattr(host, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
        self._set_state(LiveState.LISTENING)
        self.show_transcript("")

    def _on_transcript(self, text: str) -> None:
        if not self.active:
            return
        # Respect auto_send: if off, show transcript but don't auto-send.
        if self.audio and self.audio.auto_send:
            self._on_user_text(text)
        else:
            # Just show the transcript, wait for user to confirm.
            self.show_transcript(text)
            try:
                self.stage.transcript.add_user(text)
            except Exception:
                pass

    def _on_user_text(self, text: str) -> None:
        """One entry point for *any* utterance - mic transcript or typed."""
        text = str(text or "").strip()
        if not text or not self.active:
            return
        self.show_transcript(text)
        try:
            self.stage.transcript.add_user(text)
            self.stage.history.add_turn("user", text)
        except Exception:
            pass
        self.begin_thinking()
        send = getattr(self.host, "_live_send_transcript", None)
        if callable(send):
            # A spoken turn is not a typed one: the call's rules (keep it short,
            # no markdown) ride along with this one send and nothing else.
            try:
                self.host._live_prompt_extra = LIVE_RULES
            except Exception:
                pass
            try:
                send(text)
            except Exception:
                pass
            finally:
                try:
                    self.host._live_prompt_extra = ""
                except Exception:
                    pass

    # ── streaming ────────────────────────────────────────────────────────
    def stream_delta(self, token: str) -> None:
        """Show Cel's reply while she is still writing it."""
        if not self.active or not token:
            return
        self._stream_buf += str(token)
        # Real-time mood detection: switch face early as soon as mood tag appears in stream
        _, early_mood = extract_mood(self._stream_buf)
        if early_mood and getattr(self, "_last_stream_mood", None) != early_mood:
            self._last_stream_mood = early_mood
            self._apply_mood(early_mood)
        now = time.monotonic()
        if now - self._stream_paint < 0.06:
            return
        self._stream_paint = now
        self.show_transcript(self._stream_buf)

    def _on_audio_error(self, msg: str) -> None:
        text = str(msg or "")
        low = text.lower()
        gap = self.stt_key_gap()
        if gap is not None and ("key" in low or text.startswith("❌")):
            self._on_key_required(
                str(self.settings.get("voice_stt_engine", "")), gap[0])
        toast = getattr(self.host, "show_toast", None)
        if callable(toast):
            try:
                toast(f"🎙 {msg}", icon="⚠️")
            except Exception:
                pass

    # ── push-to-talk ─────────────────────────────────────────────────────
    def _ptt_pressed(self) -> None:
        """The on-screen hold-to-talk button (the bound key does the same)."""
        if not self.active or self.audio is None:
            return
        if not self.audio.start_listening():
            return
        try:
            self.stage.captions.set_ptt_active(True)
        except RuntimeError:
            pass
        self._set_state(LiveState.LISTENING)

    def _ptt_released(self) -> None:
        if not self.active or self.audio is None:
            return
        try:
            self.stage.captions.set_ptt_active(False)
        except RuntimeError:
            pass
        self.audio.stop_listening()

    def _on_audio_hint(self, text: str) -> None:
        """A caption-only note. Never a transcript - nothing here is speech."""
        if self.active:
            self.show_transcript(str(text or ""))

    def set_transcribing(self, on: bool) -> None:
        """Forward transcribing status to the captions widget without crashing."""
        try:
            if self.stage and hasattr(self.stage, "captions"):
                self.stage.captions.set_transcribing(bool(on))
        except (AttributeError, RuntimeError):
            pass
        # Task 5: light up the blue 'stt' state - the one color nobody ever
        # broadcast before, so the bar sat green while Whisper was working.
        try:
            bar = getattr(self.stage, "activity_bar", None)
            if bar is not None:
                bar.set_activity("stt" if on else "ready")
        except (AttributeError, RuntimeError):
            pass

    def _on_audio_busy(self, busy: bool) -> None:
        """Transcribing state on the hold-to-talk pill."""
        if not self.active:
            return
        self.set_transcribing(bool(busy))

    # ── speech-engine credential ─────────────────────────────────────────
    def stt_key_gap(self):
        """``(provider, hint)`` when the selected STT engine has no key."""
        try:
            return stt_missing_key(
                self.settings.get("voice_stt_engine", ""), self.settings)
        except Exception:
            return None

    def _on_key_required(self, engine: str, provider: str) -> None:
        """Report the gap to the host and paint the 🎙 circle red."""
        try:
            self.stage.controls.set_engine_status(LiveControlBar.ENGINE_ERROR)
        except RuntimeError:
            pass
        try:
            self.stt_key_required.emit(str(engine), str(provider))
        except RuntimeError:
            pass

    def _on_engine_pick(self, choice: str) -> None:
        """A new engine is only allowed to stay if it can actually hear you."""
        self.settings["voice_stt_engine"] = str(choice)
        gap = self.stt_key_gap()
        try:
            if gap is not None:
                self.stage.controls.set_engine_status(LiveControlBar.ENGINE_ERROR)
            elif self.audio is not None and self.audio.muted:
                self.stage.controls.set_engine_status(LiveControlBar.ENGINE_MUTED)
            else:
                self.stage.controls.set_engine_status(LiveControlBar.ENGINE_OK)
        except RuntimeError:
            pass
        if gap is not None:
            self._on_key_required(str(choice), gap[0])

    # ── hide / restore ───────────────────────────────────────────────────
    @staticmethod
    def _self_hidden(w: QWidget) -> bool:
        """True when the widget hides *itself* (user collapse / never shown).

        An ancestor being hidden (e.g. the never-selected chat_substack page)
        does NOT count - those widgets must come back after the call even
        though isHidden() was True while the curtain was closed, otherwise a
        live chat that flips the stack to the bubble page re-hides chat_scroll
        and the conversation vanishes.
        """
        if not w.isHidden():
            return False
        p = w.parentWidget()
        while p is not None:
            if p.isHidden():
                return False
            p = p.parentWidget()
        return True

    def enter_live(self, gender: Optional[str] = None) -> bool:
        if self.active:
            return False
        if gender:
            self.gender = gender

        # Re-read live settings from host at entry time (settings may have
        # changed since controller construction) - then open the stage.
        # NOTE: sync_settings() itself must NEVER show the stage: Settings →
        # Save Preferences calls it on every save, and that used to teleport
        # the user straight into a call (mic hot, library loaded, RAM up).
        self.sync_settings()
        self._open_stage()
        return True

    def sync_settings(self) -> None:
        """Re-apply updated settings (PTT, mute, autosend) without opening
        the call. Between calls this only stages values for next time - the
        stage stays hidden, the mic stays off, no library load."""
        if hasattr(self.host, "settings"):
            self.settings = self.host.settings
        if self.audio is not None:
            self.audio.settings = self.settings
            was_ptt = getattr(self.audio, "push_to_talk", False)
            now_ptt = bool(self.settings.get("live_push_to_talk", False))
            self.audio.push_to_talk = now_ptt
            self.audio.auto_send = bool(self.settings.get("live_auto_send", True))
            self.audio.set_muted(bool(self.settings.get("live_mic_muted", False)))
            if self.stage and hasattr(self.stage, "captions"):
                self.stage.captions.set_push_to_talk(now_ptt)
            if now_ptt and not getattr(self.audio, "_ptt_active", False):
                self.audio.stop()
            if now_ptt != was_ptt and self.active:
                if now_ptt and getattr(self, "_ptt_filter", None) is None:
                    self._ptt_filter = self._PTTFilter(
                        self.audio, self.stage,
                        self.ptt_binding() or "Space",
                        guarded=(self.stage.input.edit,))
                    self.stage.installEventFilter(self._ptt_filter)
                elif not now_ptt and getattr(self, "_ptt_filter", None) is not None:
                    try:
                        self.stage.removeEventFilter(self._ptt_filter)
                    except Exception:
                        pass
                    self._ptt_filter = None
                    if not self.audio.muted and self.active:
                        self.audio._open_capture()

        if not self.active:
            # Between calls there is nothing visible to refresh - and this
            # is exactly where Save Preferences lands.
            return
        # Mid-call refresh: control-bar mute + engine dot only. Never
        # re-hide targets or re-show the stage (that would clobber _saved).
        try:
            bar = self.stage.controls
            bar.set_muted(self.audio.muted if self.audio else False)
            if self.stt_key_gap() is not None:
                bar.set_engine_status(LiveControlBar.ENGINE_ERROR)
            elif self.audio is not None and self.audio.muted:
                bar.set_engine_status(LiveControlBar.ENGINE_MUTED)
            else:
                bar.set_engine_status(LiveControlBar.ENGINE_OK)
        except (AttributeError, RuntimeError):
            pass

    def _open_stage(self) -> None:
        """Show the call screen - entry only, via enter_live()."""
        self._saved = {}
        for w in self._hide_targets:
            try:
                self._saved[w] = self._self_hidden(w)
                w.setVisible(False)
            except RuntimeError:
                continue
        host = self.stage.parentWidget()
        if host is not None:
            self.stage.setGeometry(host.rect())
        self.stage.setVisible(True)
        self.stage.raise_()
        self.stage.load_library()
        self._base_expression = self.stage._first_expression()
        if self._base_expression is not None:
            self.stage.avatar.set_expression(self._base_expression)
            self.stage._current_expr_name = self._base_expression.name
        self.stage.hold_rotation(2.5)
        self.stage.captions.set_caption("")
        self.stage.captions.set_level(0.0)
        self.stage.input.edit.clear()
        self._exiting = False
        self.active = True

        # PTT handling - the bound key, watched on the stage *and* on the call's
        # text box (a release bubbles up from there, so it has to be filtered
        # too or every typed space ends a phantom turn).
        self._ptt_filter = None
        if self.audio and self.audio.push_to_talk:
            self._ptt_filter = self._PTTFilter(
                self.audio, self.stage,
                self.ptt_binding() or "Space",
                guarded=(self.stage.input.edit,))
            self.stage.installEventFilter(self._ptt_filter)
            try:
                self.stage.input.installEventFilter(self._ptt_filter)
            except (AttributeError, RuntimeError):
                pass
        # The on-screen pill only exists in push-to-talk mode; with the mic
        # always open there is nothing to hold.
        self.stage.captions.set_push_to_talk(
            bool(self.audio is not None and self.audio.push_to_talk))

        # Sync mute state with control bar. Connected ONCE - this runs on every
        # call, so re-connecting here stacked one more handler each time.
        bar = self.stage.controls
        bar.set_muted(self.audio.muted if self.audio else False)
        if not getattr(self, "_bar_wired", False):
            self._bar_wired = True
            bar.mute_toggled.connect(
                lambda m: self.audio.set_muted(m) if self.audio else None)
            bar.engine_changed.connect(self._on_engine_pick)

        # The 🎙 dot: green while she hears you, dim when muted, red when the
        # chosen engine has no key and the call is deaf.
        if self.stt_key_gap() is not None:
            bar.set_engine_status(LiveControlBar.ENGINE_ERROR)
        elif self.audio is not None and self.audio.muted:
            bar.set_engine_status(LiveControlBar.ENGINE_MUTED)
        else:
            bar.set_engine_status(LiveControlBar.ENGINE_OK)

        self._set_state(LiveState.LISTENING)
        # Focus the *stage*, not the text box: a call starts with the
        # push-to-talk key live, and a line edit holding focus swallows it.
        # Clicking the box still types; Escape comes back out.
        try:
            self.stage.activateWindow()
            self.stage.setFocus(Qt.FocusReason.OtherFocusReason)
        except (AttributeError, RuntimeError):
            self.stage.input.focus_edit()
        try:
            from ...services.sound_engine import play_ui_sound
            play_ui_sound("open", 0.45)
        except Exception:
            pass
        if self.audio is not None:
            try:
                if not self.audio.muted:
                    self.audio.start()
            except Exception:
                pass
        # Ask for the missing credential *before* the first turn, so a deaf
        # call explains itself instead of looking like a broken microphone.
        gap = self.stt_key_gap()
        if gap is not None:
            self._on_key_required(
                str(self.settings.get("voice_stt_engine", "")), gap[0])
        return True

    class _PTTFilter(QObject):
        """Hold a key to talk - the key the user bound in Settings.

        Two things it must never do. It must not fire while the call's text box
        has focus (a KeyRelease from the line edit bubbles up to the stage, so
        Space in a typed sentence used to fire a phantom "stop listening"), and
        it must not fire on auto-repeat (one press, one turn).
        """

        def __init__(self, audio, stage, binding, guarded=()):
            super().__init__(stage)
            self.audio = audio
            self.stage = stage
            self.binding = str(binding or "")
            self.guarded = tuple(guarded or ())
            self._bound = None
            try:
                from PySide6.QtGui import QKeySequence
                seq = QKeySequence(self.binding)
                if seq.count() == 1:
                    self._bound = seq[0]
            except Exception:
                self._bound = None

        def _matches(self, event) -> bool:
            """Compare whole key+modifier combinations.

            Qt delivers a key event as *key plus modifiers*; a binding is a
            single combined sequence. Comparing plain key codes only ever
            matched unmodified keys - ``Ctrl+Shift+M`` silently did nothing.
            (``int(Qt.KeyboardModifier.X)`` raises in PySide6, which is why
            this compares Qt's own objects instead of packing bits by hand.)
            """
            if self._bound is None:
                return False
            from PySide6.QtCore import QKeyCombination
            try:
                # event.key() arrives as a plain int and the combination
                # constructor wants a real Qt.Key in the *second* slot  - 
                # getting either detail wrong raises inside the filter and
                # silently turns push-to-talk into a dead key.
                combo = QKeyCombination(event.modifiers(), Qt.Key(event.key()))
            except Exception:
                return False
            return combo == self._bound

        def _typing(self) -> bool:
            focus = QApplication.focusWidget()
            if focus is None:
                return False
            if any(focus is g for g in self.guarded):
                return True
            return isinstance(focus, (QLineEdit, QTextEdit))

        def eventFilter(self, obj, event):
            if event.type() not in (event.Type.KeyPress, event.Type.KeyRelease):
                return super().eventFilter(obj, event)
            # Escape is the way out of the text box and back to keying the
            # call - the binding itself is never Escape (Settings refuses it).
            if (event.type() == event.Type.KeyPress
                    and event.key() == Qt.Key.Key_Escape and self._typing()):
                try:
                    self.stage.setFocus(Qt.FocusReason.OtherFocusReason)
                except RuntimeError:
                    pass
                return True
            if not self._matches(event):
                return super().eventFilter(obj, event)
            if event.isAutoRepeat():
                return True
            if self._typing():
                return super().eventFilter(obj, event)
            if event.type() == event.Type.KeyPress:
                self.audio.start_listening()
                try:
                    self.stage.captions.set_ptt_active(True)
                except RuntimeError:
                    pass
            else:
                try:
                    self.stage.captions.set_ptt_active(False)
                except RuntimeError:
                    pass
                self.audio.stop_listening()
            return True

    def exit_live(self) -> bool:
        """Hang up with a real outro: goodbye face, fade, close sound.

        Teardown itself runs in :meth:`_finish_exit` *after* the fade so the
        call dissolves instead of vanishing; dispose() still tears down
        instantly when the app is closing.
        """
        if not self.active or self._exiting:
            return False
        self._exiting = True
        try:
            from ...services.sound_engine import play_ui_sound
            play_ui_sound("close", 0.45)
        except Exception:
            pass
        self._apply_mood("warm")   # a soft goodbye face while she fades
        try:
            self._fade_curtain = _FadeCurtain(self.stage)
            self._fade_curtain.raise_()
            self._fade_curtain.show()
            self._fade_clock = QElapsedTimer()
            self._fade_clock.start()
            self._fade_timer = QTimer(self.stage)
            self._fade_timer.setInterval(16)
            self._fade_timer.timeout.connect(self._fade_step)
            self._fade_timer.start()
            QTimer.singleShot(1400, self._fade_watchdog)
            return True
        except Exception:
            self._finish_exit()
            return True

    def _on_outro_done(self) -> None:
        self._finish_exit()

    def _fade_step(self) -> None:
        """16 ms wall-clock outro fade (QPropertyAnimation's timeline could
        stall mid-run under a manual event pump, stranding the shell)."""
        if not self._exiting or getattr(self, "_fade_curtain", None) is None:
            self._stop_fade()
            return
        p = min(1.0, self._fade_clock.elapsed() / 560.0)
        eased = p * p * (3.0 - 2.0 * p)
        self._fade_curtain.set_alpha(eased)
        if p >= 1.0:
            self._stop_fade()
            self._on_outro_done()

    def _fade_watchdog(self) -> None:
        """Hard cap: never strand the shell mid-fade if a tick is missed."""
        if self._exiting:
            self._on_outro_done()

    def _stop_fade(self) -> None:
        t = getattr(self, "_fade_timer", None)
        if t is not None:
            try:
                t.stop()
            except RuntimeError:
                pass

    def _finish_exit(self) -> None:
        """The original instant teardown, now only run once the fade is done."""
        self._stop_fade()
        c = getattr(self, "_fade_curtain", None)
        if c is not None:
            self._fade_curtain = None
            try:
                c.hide()
                c.setParent(None)
                c.deleteLater()
            except RuntimeError:
                pass
        # Clean up PTT event filter
        if getattr(self, "_ptt_filter", None) is not None:
            try:
                self.stage.removeEventFilter(self._ptt_filter)
                self.stage.input.removeEventFilter(self._ptt_filter)
            except (AttributeError, RuntimeError):
                pass
            self._ptt_filter = None
        if not self.active:
            return
        self.stage.setVisible(False)
        try:
            self.stage.transcript.clear()
            self.stage.history.set_open(False)
        except Exception:
            pass
        for w, self_hidden in self._saved.items():
            try:
                # Stack pages (welcome vs bubbles) belong to the stack: the
                # in-call send may have flipped chat_substack to the bubble
                # page, so the stack - not our saved flag - decides visibility.
                parent = w.parentWidget()
                if parent is not None and hasattr(parent, "currentWidget") \
                        and hasattr(parent, "indexOf") and parent.indexOf(w) >= 0:
                    w.setVisible(parent.currentWidget() is w)
                    continue
                w.setVisible(not self_hidden)
            except RuntimeError:
                continue
        self._saved.clear()
        self.stage.captions.set_caption("")
        self.stage.captions.set_level(0.0)
        self.stage.captions.set_push_to_talk(False)
        try:
            self.stage.captions.set_ptt_active(False)
        except RuntimeError:
            pass
        self.stage.input.edit.clear()
        self.active = False
        self._exiting = False
        self._set_state(LiveState.IDLE)
        if self.audio is not None:
            try:
                self.audio.stop()
            except Exception:
                pass
        self.ended.emit()

    def toggle(self, gender: Optional[str] = None) -> bool:
        return self.exit_live() if self.active else self.enter_live(gender)

    def set_hide_targets(self, targets: List[QWidget]) -> None:
        """Replace the chrome list.

        Resolved lazily by the host at click time, because some of the host's
        widgets are constructed *after* the controller is created.
        """
        self._hide_targets = [w for w in (targets or []) if w is not None]

    def dispose(self) -> None:
        self._tick.stop()
        if self.active:
            # App is closing - tear down immediately, no outro fade.
            try:
                self._finish_exit()
            except Exception:
                self.active = False
        try:
            self.stage.dispose()
        except Exception:
            pass

    # ── state ────────────────────────────────────────────────────────────
    def _set_state(self, state: LiveState) -> None:
        self.state = state
        # The mic closes while she is mid-turn. With push-to-talk off it used
        # to stay open for the whole call, so the recorder heard Cel's own
        # voice and handed it back as your words.
        try:
            if self.audio is not None and not self.audio.push_to_talk:
                busy = state in (LiveState.THINKING, LiveState.SPEAKING)
                self.audio.set_capture_enabled(not busy)
        except Exception:
            pass
        # The desktop pet follows the call: it looks up while she thinks and
        # settles back to listening when she is done.
        hook = getattr(self.host, "companion_state", None)
        if callable(hook):
            try:
                hook(state.value)
            except Exception:
                pass
        try:
            self.stage.captions.set_state(state)
            # Anything but IDLE means Cel is mid-turn: freeze idle face
            # rotation and settle back onto the mood face, instead of leaving
            # whatever random expression the rotation last picked on screen.
            self.stage.set_attentive(state is not LiveState.IDLE)
            if state is LiveState.LISTENING and self._base_expression is not None:
                self.stage.avatar.set_expression(self._base_expression)
                self.stage._current_expr_name = self._base_expression.name
            # The 🟢 under the model circle: pulses green while Cel thinks,
            # goes dark the moment she is idle again.
            thinking = state is LiveState.THINKING
            bar = self.stage.controls
            bar.model.set_toggle(thinking)
            bar.model.dot.set_pulse(thinking)
            # The 🎙 circle: green while Cel is hearing you, dim when muted,
            # red when the selected engine has no key and cannot hear at all.
            if self.stt_key_gap() is None:
                if self.audio is not None and self.audio.muted:
                    bar.set_engine_status(LiveControlBar.ENGINE_MUTED)
                elif state is LiveState.LISTENING:
                    bar.set_engine_status(LiveControlBar.ENGINE_OK)
        except RuntimeError:
            pass
        if state in (LiveState.THINKING, LiveState.SPEAKING):
            try:
                self.stage.avatar.blink_now()
            except Exception:
                pass
        self.state_changed.emit(state.value)

    def set_level(self, rms: float) -> None:
        self._level = float(rms or 0.0)
        # Gate the *meter* the way the STT clip is gated: everything at or
        # below the calibrated room floor (scaled by the strength slider) is
        # silence - so a PC fan no longer makes the bar dance.
        shown = self._level
        try:
            if self.settings.get("noise_cancel_enabled", True):
                from ...services import noise_gate
                if noise_gate.has_profile():
                    floor = noise_gate.profile_rms()
                    strength = max(0.0, min(1.0, float(
                        self.settings.get("noise_cancel_strength", 70)) / 100.0))
                    shown = max(0.0, self._level - floor * strength)
        except Exception:
            shown = self._level
        try:
            self.stage.captions.set_level(shown)
        except RuntimeError:
            pass

    def show_transcript(self, text: str) -> None:
        try:
            self.stage.captions.set_caption(text)
        except RuntimeError:
            pass

    def begin_thinking(self) -> None:
        self._silence_elapsed = 0.0
        self._stream_buf = ""
        self._stream_paint = 0.0
        self._apply_mood("thinking")
        self._set_state(LiveState.THINKING)

    def speak(self, text: str, mood: Optional[str] = None) -> None:
        """Start a spoken turn: caption it, pick the mood, move the mouth."""
        if text:
            try:
                text = extract_mood(text)[0]
            except Exception:
                pass
            self.show_transcript(text)
            try:
                self.stage.transcript.add_cel(text)
                self.stage.history.add_turn("cel", text)
            except Exception:
                pass
        # The stream buffer has done its job - the finished reply is the truth.
        self._stream_buf = ""
        mood_str = str(mood or "").strip().lower()

        # Bug 38: Multi-mood sequential playback (up to 3 moods, 2.5s each)
        if "," in mood_str:
            tokens = [m.strip() for m in mood_str.split(",") if m.strip()]
            if tokens:
                self._apply_mood(tokens[0])
                if len(tokens) > 1:
                    QTimer.singleShot(2500, lambda t=tokens[1]: self._apply_mood(t))
                if len(tokens) > 2:
                    QTimer.singleShot(5000, lambda t=tokens[2]: self._apply_mood(t))
        else:
            key = mood_str if mood_str in MOODS else (self._detector or CompanionStage._guess_mood)(text or "")
            self._apply_mood(key)
        self._set_state(LiveState.SPEAKING)

    def finish_speaking(self) -> None:
        if self.active and self.state is LiveState.SPEAKING:
            # Settle onto the *warm* face, not the neutral idle set - a
            # reply that ends on a default smile reads as "done talking",
            # which is exactly the flat after-thinking look (item 7).
            self._apply_mood("warm")
            self._set_state(LiveState.LISTENING)

    # ── expression + mouth ───────────────────────────────────────────────
    def _apply_mood(self, mood: str) -> None:
        if self.stage.library is None:
            return
        for candidate in MOODS.get(mood, MOODS["idle"]):
            expr = self.stage.library.get(self.gender, candidate)
            if expr is not None:
                self._base_expression = expr
                self.stage.avatar.set_expression(expr)
                self.stage._current_expr_name = expr.name
                # A mood reaction owns the face for a beat - don't let idle
                # rotation stomp on it mid-reaction.
                self.stage.hold_rotation(3.0)
                self.stage.update()
                return

    def _on_tick(self) -> None:
        if not self.active or self._base_expression is None:
            return
        speaking = self.state is LiveState.SPEAKING
        openness = self.envelope.step(1.0 / 30.0, progress=1.0, active=speaking)
        if speaking:
            try:
                self.stage.avatar.set_expression(
                    talking_expression(self._base_expression, openness))
            except RuntimeError:
                pass


_orig_ls_show_expression = LiveStage.show_expression
_orig_ls_set_talk_progress = getattr(LiveStage, "set_talk_progress", None)


def _patched_ls_show_expression(self, name: str) -> bool:
    from cellium.core.utils import parse_mood_sequence, resolve_single_mood_name
    seq = parse_mood_sequence(name)
    if len(seq) > 1:
        self.play_mood_sequence(seq)
        return True
    target = seq[0] if seq else resolve_single_mood_name(name) or name
    ok = _orig_ls_show_expression(self, target)
    if not ok and target != name:
        ok = _orig_ls_show_expression(self, name)
    if ok and getattr(self, "avatar", None) is not None:
        cur_expr = self.avatar.expression()
        if cur_expr is not None:
            self._talk_base = cur_expr
    return ok


def _patched_ls_play_mood_sequence(self, moods, total_ms: int = 0, sentence_text: str = "") -> None:
    from cellium.core.utils import parse_mood_sequence
    seq = parse_mood_sequence(", ".join(moods) if isinstance(moods, (list, tuple)) else str(moods))
    if not seq:
        return
    for tm in getattr(self, "_mood_seq_timers", []):
        try:
            tm.stop()
            tm.deleteLater()
        except Exception:
            pass
    self._mood_seq_timers = []
    self._active_mood_seq = list(seq)
    self._active_mood_idx = 0

    _patched_ls_show_expression(self, seq[0])
    if getattr(self, "smoke", None) is not None and hasattr(self.smoke, "pulse"):
        self.smoke.pulse(0.85)
    if len(seq) == 1:
        return

    if total_ms <= 0:
        words = max(4, len((sentence_text or "").split()))
        total_ms = max(1800, min(14000, words * 340))

    n = len(seq)
    for idx in range(1, n):
        delay_ms = int(round(total_ms * (idx / float(n))))
        tm = QTimer(self)
        tm.setSingleShot(True)
        tm.timeout.connect(lambda m=seq[idx], i=idx: self._advance_mood_seq(i, m))
        tm.start(max(250, delay_ms))
        self._mood_seq_timers.append(tm)


def _advance_mood_seq(self, idx: int, mood_name: str) -> None:
    if idx >= getattr(self, "_active_mood_idx", 0):
        self._active_mood_idx = idx
        _patched_ls_show_expression(self, mood_name)
        if getattr(self, "smoke", None) is not None and hasattr(self.smoke, "pulse"):
            self.smoke.pulse(0.75)


def _patched_ls_set_talk_progress(self, progress: float) -> None:
    if _orig_ls_set_talk_progress is not None:
        _orig_ls_set_talk_progress(self, progress)
    seq = getattr(self, "_active_mood_seq", None)
    if seq and len(seq) > 1 and 0.0 < progress <= 1.0:
        n = len(seq)
        want_idx = min(n - 1, int(progress * n))
        if want_idx > getattr(self, "_active_mood_idx", 0):
            self._advance_mood_seq(want_idx, seq[want_idx])


LiveStage.show_expression = _patched_ls_show_expression
LiveStage.play_mood_sequence = _patched_ls_play_mood_sequence
LiveStage._advance_mood_seq = _advance_mood_seq
LiveStage.set_talk_progress = _patched_ls_set_talk_progress


# ── #5: Smoothly Crossfading 6-Color Live Activity & Microphone Bar ──────────
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget


class LiveActivityBar(QWidget):
    """Smoothly crossfading 6-color state & progress bar for Live Mode!

    Color Palette (smooth 60fps RGB interpolation):
    - 'ready'    (GREEN  #10B981): Ready / User can talk now (fill = live mic input volume)
    - 'stt'      (BLUE   #3B82F6): Translating user's voice to text (Whisper STT)
    - 'loading'  (YELLOW #FACC15): Loading heavy offline GGUF / Kokoro / Whisper model
    - 'thinking' (PURPLE #A855F7): Cel is thinking / generating tokens (fill = token progress)
    - 'tts'      (ORANGE #F97316): Translating Cel's text to voice / speaking (fill = speech progress)
    - 'error'    (RED    #EF4444): Something failed - check Dev Console Logs
    """

    PALETTE = {
        "ready":    (16.0, 185.0, 129.0),  # Green
        "listening":(16.0, 185.0, 129.0),  # Green
        "stt":      (59.0, 130.0, 246.0),  # Blue
        "loading":  (250.0, 204.0, 21.0),  # Yellow
        "thinking": (168.0, 85.0, 247.0),  # Purple
        "tts":      (249.0, 115.0, 22.0),  # Orange
        "error":    (239.0, 68.0, 68.0),   # Red
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setMinimumWidth(260)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._state = "ready"
        self._cur_rgb = [16.0, 185.0, 129.0]
        self._target_rgb = [16.0, 185.0, 129.0]
        self._progress = 0.18
        self._target_progress = 0.18
        self._pulse_phase = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(33)  # 30 FPS is plenty for a smooth color fade
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()   # never interpolate a hidden bar
        super().hideEvent(event)

    def set_activity(self, state: str, progress: float | None = None) -> None:
        st = (state or "ready").lower().strip()
        if st not in self.PALETTE:
            st = "ready"
        self._state = st
        self._target_rgb = list(self.PALETTE[st])
        if progress is not None:
            self._target_progress = max(0.08, min(1.0, float(progress)))
        elif st == "ready":
            self._target_progress = max(0.14, self._target_progress * 0.5)
        elif st in ("loading", "stt"):
            self._target_progress = 0.65

    def _tick(self) -> None:
        self._pulse_phase = (self._pulse_phase + 0.09) % (2.0 * 3.14159265)
        # Smoothly crossfade RGB channels (never snaps!)
        for i in range(3):
            self._cur_rgb[i] += (self._target_rgb[i] - self._cur_rgb[i]) * 0.14

        # In indeterminate states (loading / stt), gently oscillate progress wave
        if self._state in ("loading", "stt"):
            import math as _m
            wave_p = 0.52 + 0.36 * _m.sin(self._pulse_phase)
            self._progress += (wave_p - self._progress) * 0.18
        else:
            self._progress += (self._target_progress - self._progress) * 0.22

        if self.isVisible():
            self.update()

    def current_hex_color(self) -> str:
        r, g, b = (int(max(0, min(255, round(c)))) for c in self._cur_rgb)
        return f"#{r:02X}{g:02X}{b:02X}"

    def paintEvent(self, _event) -> None:
        w = float(self.width())
        h = float(self.height())
        if w < 10 or h < 4:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        r, g, b = (int(max(0, min(255, round(c)))) for c in self._cur_rgb)
        bar_h = 8.0
        y0 = (h - bar_h) * 0.5
        rad = bar_h * 0.5

        # Track background
        track_rect = QRectF(4.0, y0, w - 8.0, bar_h)
        painter.setPen(QPen(QColor(r, g, b, 90), 1.0))
        painter.setBrush(QColor(14, 10, 26, 190))
        painter.drawRoundedRect(track_rect, rad, rad)

        # Animated glowing fill bar
        fill_w = max(bar_h * 1.5, (w - 8.0) * max(0.08, min(1.0, self._progress)))
        fill_rect = QRectF(4.0, y0, fill_w, bar_h)
        grad = QLinearGradient(fill_rect.left(), 0.0, fill_rect.right(), 0.0)
        grad.setColorAt(0.0, QColor(r, g, b, 175))
        grad.setColorAt(0.65, QColor(r, g, b, 245))
        grad.setColorAt(1.0, QColor(min(255, r + 45), min(255, g + 45), min(255, b + 45), 255))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawRoundedRect(fill_rect, rad, rad)
        painter.end()


# Wire `set_talking`, `wake_avatar`, `set_live_activity`, and `LiveActivityBar` onto `LiveStage`
_orig_ls_init_v5 = LiveStage.__init__
_orig_ls_wake_v5 = getattr(LiveStage, "wake_avatar", None)


def _patched_ls_init_v5(self, *args, **kwargs):
    _orig_ls_init_v5(self, *args, **kwargs)
    try:
        self.activity_bar = LiveActivityBar(self)
        # Insert activity_bar right above the bottom controls row if layout exists
        lay = self.layout()
        if lay is not None:
            idx = max(0, lay.count() - 1)
            lay.insertWidget(idx, self.activity_bar, 0, Qt.AlignmentFlag.AlignHCenter)
            self.activity_bar.setFixedWidth(340)
        # Also tint the mic button smoothly as the activity bar crossfades!
        self.activity_bar._timer.timeout.connect(self._sync_mic_button_tint)
    except Exception:
        pass


def _ls_sync_mic_button_tint(self) -> None:
    try:
        bar = getattr(self, "activity_bar", None)
        ctrl = getattr(self, "controls", None)
        mic_btn = getattr(ctrl, "mic", None) if ctrl is not None else None
        if bar is None or mic_btn is None:
            return
        r, g, b = (int(max(0, min(255, round(c)))) for c in bar._cur_rgb)
        mic_btn.setStyleSheet(
            f"QPushButton {{ background: rgba({r}, {g}, {b}, 0.28); "
            f"border: 2px solid rgb({r}, {g}, {b}); border-radius: 23px; color: #FFFFFF; }}"
            f"QPushButton:hover {{ background: rgba({r}, {g}, {b}, 0.48); }}"
        )
        # Also tint the status label text to match the smooth crossfading state color!
        st_lbl = getattr(self, "status", None) or getattr(self, "_status_label", None)
        if st_lbl is not None:
            st_lbl.setStyleSheet(
                f"color: rgb({min(255, r + 35)}, {min(255, g + 35)}, {min(255, b + 35)}); "
                f"font-size: 13px; font-weight: bold; background: rgba(14, 10, 26, 0.72); "
                f"border: 1px solid rgba({r}, {g}, {b}, 0.45); border-radius: 10px; padding: 4px 12px;"
            )
    except Exception:
        pass


def _ls_set_live_activity(self, state: str, status_text: str = "", progress: float | None = None) -> None:
    """Update both the crossfading color bar and the detailed status text simultaneously!"""
    if hasattr(self, "activity_bar") and self.activity_bar is not None:
        self.activity_bar.set_activity(state, progress=progress)
    if status_text:
        if hasattr(self, "set_status"):
            self.set_status(status_text)
        elif hasattr(self, "status") and self.status is not None:
            self.status.setText(status_text)
            self.status.show()


def _ls_set_talking(self, talking: bool) -> None:
    """Compatibility & state method for starting/stopping Cel's talking state on LiveStage."""
    self._talking = bool(talking)
    if self._talking and getattr(self, "avatar", None) is not None:
        self._talk_base = self.avatar.expression()
    if getattr(self, "smoke", None) is not None and hasattr(self.smoke, "set_talking"):
        self.smoke.set_talking(self._talking)
    if hasattr(self, "set_speaking"):
        try:
            self.set_speaking(self._talking)
        except Exception:
            pass
    if self._talking:
        self.set_live_activity("tts", progress=0.55)
    else:
        self.set_live_activity("ready", "🟢 Ready - Listening for your voice…", progress=0.18)


# ── Wire the v5 helpers onto LiveStage (they were defined but never attached) ──
if 'LiveStage' in globals():
    LiveStage.__init__ = _patched_ls_init_v5
    LiveStage.set_talking = _ls_set_talking
    LiveStage.set_live_activity = _ls_set_live_activity
    LiveStage._sync_mic_button_tint = _ls_sync_mic_button_tint


# ═══ WAVE OMG LIVE_MODE PARITY BLOCK START ═══
import time as _lm_time
import random as _lm_rng
from PySide6.QtCore import QTimer
from cellium.ui.avatar.widget import _wake_from_idle_if_needed

_LIVE_PLEASANT_FACES = (
    "Happy", "Kawaii", "Chibi Joy", "Excited", "Winking", "UwU",
    "Flirty", "Sparkle Hype", "Starstruck", "Feeling Cool", "Relieved",
)
_LIVE_TIRED_SET = frozenset({
    "tired", "sleepy", "sleepy (local)", "blank", "deadpan",
    "sarcastic", "sad", "doomer", "waking",
})


# === WAVE_OMG_PARITY_START (LIVE_V3_CLEAN) ===
import random as _lm_rng
from cellium.ui.avatar.widget import _wake_from_idle_if_needed

_LIVE_PLEASANT_FACES = (
    "Happy", "Kawaii", "Chibi Joy", "Excited", "Winking", "UwU",
    "Flirty", "Sparkle Hype", "Starstruck", "Feeling Cool", "Relieved",
)

def _live_pick_random_face(stage) -> str:
    try:
        lib = stage.load_library()
        names = lib.names(stage.gender)
        pleasant = [n for n in _LIVE_PLEASANT_FACES if n in names]
        pool = pleasant if pleasant else names
        if pool:
            return _lm_rng.choice(pool)
    except Exception:
        pass
    return "Kawaii"

if 'LiveStage' in globals():
    _orig_ls_wake_omg = getattr(LiveStage, 'wake_avatar', None)
    _orig_ls_set_gender_omg = getattr(LiveStage, 'set_gender', None)

    def _patched_ls_wake_avatar(self, *args, **kwargs):
        self._fatigue_stage = 'idle'
        self._idle_macro_t = 0.0
        self._last_interaction_ts = time.monotonic() if 'time' in globals() else 0.0
        res = None
        if callable(_orig_ls_wake_omg):
            try:
                res = _orig_ls_wake_omg(self, *args, **kwargs)
            except Exception:
                pass
        self._fatigue_stage = 'idle'
        self._idle_macro_t = 0.0
        av = getattr(self, 'avatar', None)
        if av is not None:
            av._fatigue_stage = 'idle'
            av._was_napping = True
            try:
                _wake_from_idle_if_needed(av)
            except Exception:
                pass
            if hasattr(av, 'blink_now'):
                try:
                    av.blink_now()
                except Exception:
                    pass
        return res

    def _patched_ls_set_gender(self, gender: str) -> None:
        if callable(_orig_ls_set_gender_omg):
            _orig_ls_set_gender_omg(self, gender)
        else:
            self.gender = gender
        pick = _live_pick_random_face(self)
        self.show_expression(pick)

    LiveStage.wake_avatar = _patched_ls_wake_avatar
    LiveStage.set_gender = _patched_ls_set_gender

if 'LiveModeController' in globals():
    _orig_lmc_enter_omg = LiveModeController.enter_live
    _orig_lmc_wake_omg = getattr(LiveModeController, 'wake_avatar', None)

    def _patched_lmc_enter_live(self, gender: str = 'Female') -> bool:
        ok = _orig_lmc_enter_omg(self, gender)
        if ok and hasattr(self, 'stage') and self.stage is not None:
            pick = _live_pick_random_face(self.stage)
            self.stage.show_expression(pick)
            self.stage._fatigue_stage = 'idle'
        return ok

    def _patched_lmc_wake_avatar(self, *args, **kwargs):
        self._fatigue_stage = 'idle'
        res = None
        if callable(_orig_lmc_wake_omg):
            try:
                res = _orig_lmc_wake_omg(self, *args, **kwargs)
            except Exception:
                pass
        self._fatigue_stage = 'idle'
        st = getattr(self, 'stage', None)
        if st is not None:
            st._fatigue_stage = 'idle'
            if hasattr(st, 'wake_avatar'):
                try:
                    st.wake_avatar()
                except Exception:
                    pass
            st._fatigue_stage = 'idle'
        return res

    def _rearm_live_mic_for_next_turn(self) -> None:
        if not getattr(self, 'active', False):
            return
        try:
            self.set_state(LiveState.LISTENING)
        except Exception:
            pass
        if hasattr(self, 'stage') and self.stage is not None and hasattr(self.stage, 'set_live_activity'):
            self.stage.set_live_activity('ready', '\U0001f7e2 Listening\u2026', progress=0.18)
        aud = getattr(self, 'audio', None)
        if aud is not None:
            try:
                aud._stopping = False
                aud.set_capture_enabled(True)
                if not aud.running and not aud.muted and not aud.push_to_talk:
                    aud.start()
            except Exception:
                pass

    LiveModeController.enter_live = _patched_lmc_enter_live
    LiveModeController.wake_avatar = _patched_lmc_wake_avatar
    LiveModeController.rearm_mic_for_next_turn = _rearm_live_mic_for_next_turn
# === WAVE_OMG_PARITY_END (LIVE_V3_CLEAN) ===
