"""Circular control bar for Live Mode - model, agent, STT engine, voice, history.

Rectangular buttons down the side of a full-screen call UI look like a settings
dialog that crashed into a phone call. These are round, glassy and quiet: an
icon in the middle, a whisper-quiet caption underneath, and a popup of choices
that only exists while you are actually choosing.

The circles *feel* alive: they idle-bob on a shared sine (staggered phase per
circle), lift when a menu opens, and the model circle's state dot pulses green
whenever Cel is thinking. The 🎙 engine circle swaps the input engine
(offline whisper ↔ online APIs) for the very next utterance.

Selection is kept deliberately **separate from chat**: a call is its own
context. Picking "Hyper Kawaii" for the call writes ``live_voice`` and leaves
``voice_host`` / ``ac_voice_variant`` (what chat and the desktop pet use) alone,
so the two never fight.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QSize, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QMenu, QToolButton, QVBoxLayout, QWidget,
)

from ...core.config import ASSETS_DIR, CEL_VOICE_VARIANTS

#: Cel's own voices, offered alongside the real TTS hosts.
CEL_VOICE_CHOICES: List[str] = list(CEL_VOICE_VARIANTS.keys())

#: Actual speech hosts.
TTS_HOST_CHOICES: List[str] = ["Kokoro (Offline)", "Edge TTS (Online)"]

#: Everything the voice button can offer.
VOICE_CHOICES: List[str] = TTS_HOST_CHOICES + CEL_VOICE_CHOICES

#: Input engines for the 🎙 circle - offline first (no key, no quota), then
#: the online APIs. Names must match ``STTWorker``'s engine branches and the
#: settings dialog's combo so one key drives both.
STT_ENGINE_OFFLINE = "ggml Whisper (Local)"
STT_ENGINE_CHOICES: List[str] = [
    "ggml Whisper (Local)",
    "Groq Whisper (Fastest)",
    "Google Speech (Free)",
    "Hugging Face Whisper",
    "OpenAI Whisper",
]

_MENU_QSS = """
QMenu {
    background: rgba(14, 8, 30, 0.96);
    border: 1px solid rgba(192, 132, 252, 0.45);
    border-radius: 14px;
    padding: 8px;
}
QMenu::item {
    padding: 8px 16px;
    border-radius: 10px;
    color: #E9D5FF;
    font-size: 13px;
}
QMenu::item:selected {
    background: rgba(147, 51, 234, 0.55);
    color: #FFFFFF;
}
QMenu::separator {
    height: 1px;
    background: rgba(192, 132, 252, 0.25);
    margin: 6px 10px;
}
"""

_BTN_QSS = """
QToolButton {
    background: rgba(255, 255, 255, 0.07);
    border: 1.5px solid rgba(192, 132, 252, 0.45);
    border-radius: 27px;
}
QToolButton:hover {
    background: rgba(147, 51, 234, 0.45);
    border-color: #E879F9;
}
QToolButton:pressed {
    background: rgba(147, 51, 234, 0.7);
}
QToolButton::menu-indicator { image: none; }
"""


class _Dot(QWidget):
    """The little state dot under a control - solid when on, softly *pulsing*
    when the state is live (Cel thinking), pinned to a colour when the state is
    a warning (a red 🎙 dot means the selected engine cannot hear you at all)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(6, 6)
        self._on = False
        self._pulse = False
        self._color = None
        self._ph = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._pulse_tick)

    def set_on(self, on: bool) -> None:
        self._on = bool(on)
        self._sync()
        self.update()

    def set_pulse(self, on: bool) -> None:
        """Breathe the green while the state behind the dot is active."""
        self._pulse = bool(on)
        self._sync()
        self.update()

    def set_color(self, color) -> None:
        """Pin the dot to an explicit colour (``None`` returns to green/dim)."""
        self._color = QColor(color) if color is not None else None
        self.update()

    def _sync(self) -> None:
        if self._on and self._pulse:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._ph = 0.0

    def _pulse_tick(self) -> None:
        self._ph = (self._ph + 0.55) % math.tau
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(Qt.PenStyle.NoPen))
        if self._color is not None:
            p.setBrush(QColor(self._color))
        elif self._on:
            if self._pulse:
                a = int(115 + 140 * (0.5 + 0.5 * math.sin(self._ph)))
                p.setBrush(QColor(110, 231, 183, max(60, min(255, a))))
            else:
                p.setBrush(QColor("#6EE7B7"))
        else:
            p.setBrush(QColor(120, 100, 160, 160))
        p.drawEllipse(0, 0, 6, 6)
        p.end()


class CircularChoice(QWidget):
    """One round icon button + caption + state dot."""

    changed = Signal(str)

    def __init__(self, icon_name: str, caption: str, parent=None,
                 diameter: int = 54, cycle: bool = False):
        super().__init__(parent)
        self._diameter = diameter
        # Tap-to-cycle mode (model circle): one clean click steps to the next
        # choice; press-and-hold still opens the full menu.
        self._cycle_mode = bool(cycle)
        self._options: List[str] = []
        self._current: Optional[str] = None
        #: One choice at a time. Without this the STT menu happily showed two
        #: ticks at once (Groq *and* Google) while only one was ever used  - 
        #: ``QAction.setCheckable`` alone is a multi-select checkbox.
        self._group = QActionGroup(self)
        self._group.setExclusive(True)
        # Idle-bob / click-pop state - driven by LiveControlBar's shared timer.
        self._bob_base: Optional[tuple] = None
        self._bob_phase = 0.0
        self._pop = 0.0
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(5)
        col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.button = QToolButton(self)
        self.button.setIcon(QIcon(str(ASSETS_DIR / "icons" / f"{icon_name}.svg")))
        self.button.setIconSize(QSize(22, 22))
        self.button.setFixedSize(diameter, diameter)
        if self._cycle_mode:
            # DelayedPopup: a clean click cycles; only a press-and-hold
            # (or the hover popup on the voice circle) opens the menu.
            self.button.setPopupMode(
                QToolButton.ToolButtonPopupMode.DelayedPopup)
            self.button.clicked.connect(self._cycle_next)
        else:
            self.button.setPopupMode(
                QToolButton.ToolButtonPopupMode.InstantPopup)
        self.button.setStyleSheet(_BTN_QSS)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu = QMenu(self.button)
        # Without setMenu the popup modes have nothing to show - the menus
        # were built, styled and tested but never actually opened on click.
        self.button.setMenu(self.menu)
        self.menu.setStyleSheet(_MENU_QSS)
        # Opening a menu is a *choice* - lift the circle for a beat.
        self.menu.aboutToShow.connect(self._pop_now)

        self.caption = QLabel(caption, self)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setFixedWidth(96)
        # Model ids are long ("...er-2-preview"); elide rather than spill.
        self.caption.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.caption.setStyleSheet(
            "color: rgba(233,213,255,0.62); font-size: 10px; background: transparent;")

        self.dot = _Dot(self)
        holder = QWidget(self)
        hl = QHBoxLayout(holder)
        # Headroom for the bob/pop animation - flush against the holder, the
        # 54px button lost its bottom edge every time the sine dipped down.
        hl.setContentsMargins(0, 7, 0, 7)
        hl.addStretch(1)
        hl.addWidget(self.button)
        hl.addStretch(1)

        col.addWidget(holder)
        col.addWidget(self.caption, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignHCenter)

    def _pop_now(self) -> None:
        self._pop = 1.0

    # ── population ────────────────────────────────────────────────────────
    def set_options(self, options: List[str], current: Optional[str],
                    separator_after: Optional[int] = None) -> None:
        self._options = [str(o) for o in options]
        self._current = str(current) if current is not None else None
        self.set_caption(current or " - ")
        self.menu.clear()
        for i, opt in enumerate(options):
            if separator_after is not None and i == separator_after:
                self.menu.addSeparator()
            act = QAction(opt, self.menu)
            act.setCheckable(True)
            act.setChecked(opt == current)
            self._group.addAction(act)
            act.triggered.connect(
                lambda _checked=False, o=opt: self._pick(o))
            self.menu.addAction(act)
    def set_hierarchical_options(self, hierarchy: dict, current: Optional[str]) -> None:
        """Create structured hierarchical submenus with exclusive radio state."""
        self._current = str(current) if current is not None else None
        self._options = []
        self.menu.clear()
        matched_label = None
        for cat, items in hierarchy.items():
            sub = self.menu.addMenu(cat)
            sub.setStyleSheet("""
                QMenu {
                    background: rgba(18, 12, 32, 0.96);
                    border: 1.5px solid #A855F7;
                    border-radius: 10px;
                    color: #F0E6FF;
                    padding: 6px;
                }
                QMenu::item:selected {
                    background: rgba(147, 51, 234, 0.45);
                    color: #FFFFFF;
                }
            """)
            for item in items:
                self._options.append(str(item))
                act = QAction(item, sub)
                act.setCheckable(True)
                is_match = (item == current)
                act.setChecked(is_match)
                if is_match:
                    matched_label = item
                self._group.addAction(act)
                act.triggered.connect(lambda _c=False, o=item: self._pick(o))
                sub.addAction(act)
        shown = matched_label or current or " - "
        if " • " in str(shown):
            shown = str(shown).split(" • ", 1)[0].strip()
        self.set_caption(shown)

    def _pick(self, opt: str) -> None:
        """One selection path for menu picks *and* tap-cycles: caption,
        stored current and signal always move together."""
        self._current = str(opt)
        try:
            for act in self._group.actions():
                act.setChecked(act.text() == str(opt))
        except RuntimeError:
            pass
        shown = str(opt)
        if " • " in shown:
            shown = shown.split(" • ", 1)[0].strip()
        self.set_caption(shown)
        self.changed.emit(str(opt))

    def _cycle_next(self) -> None:
        """Tap-to-cycle (item 11): one click steps to the next option."""
        if not self._options:
            return
        try:
            i = self._options.index(self._current)
        except ValueError:
            i = -1
        self._pick(self._options[(i + 1) % len(self._options)])
        self._pop = 1.0

    def set_caption(self, text: str) -> None:
        shown = str(text or " - ")
        metrics = self.caption.fontMetrics()
        self.caption.setText(metrics.elidedText(shown, Qt.TextElideMode.ElideRight, 92))

    def set_toggle(self, on: bool) -> None:
        self.dot.set_on(on)


class RoundActionButton(QWidget):
    """A round icon button that *does* something (no menu) - the 🕘 history."""

    clicked = Signal()

    def __init__(self, icon_name: str, caption: str, parent=None,
                 diameter: int = 54):
        super().__init__(parent)
        self._bob_base: Optional[tuple] = None
        self._bob_phase = 0.0
        self._pop = 0.0
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(5)
        col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.button = QToolButton(self)
        icon_path = ASSETS_DIR / "icons" / f"{icon_name}.svg"
        if icon_path.exists():
            self.button.setIcon(QIcon(str(icon_path)))
            self.button.setIconSize(QSize(22, 22))
        else:
            self.button.setText(icon_name)
        self.button.setFixedSize(diameter, diameter)
        self.button.setStyleSheet(_BTN_QSS)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.clicked.emit)

        self.caption = QLabel(caption, self)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setFixedWidth(96)
        self.caption.setStyleSheet(
            "color: rgba(233,213,255,0.62); font-size: 10px; background: transparent;")

        self.dot = _Dot(self)
        holder = QWidget(self)
        hl = QHBoxLayout(holder)
        # Headroom for the bob/pop animation - flush against the holder, the
        # 54px button lost its bottom edge every time the sine dipped down.
        hl.setContentsMargins(0, 7, 0, 7)
        hl.addStretch(1)
        hl.addWidget(self.button)
        hl.addStretch(1)

        col.addWidget(holder)
        col.addWidget(self.caption, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_toggle(self, on: bool) -> None:
        self.dot.set_on(on)

    def is_toggled(self) -> bool:
        return self.dot._on

    def set_caption(self, text: str) -> None:
        self.caption.setText(text)


class _HoverPopup(QObject):
    """Open a circle's menu on hover instead of click, after a short dwell.

    The dwell is the whole point: a menu that pops the instant the pointer
    crosses the circle turns every pass-by into an accidental modal. Still
    under the cursor ~180 ms later means intent, not traffic - and no menu
    ever opens on top of another one.
    """

    def __init__(self, choice, siblings, delay_ms: int = 180):
        super().__init__(choice)
        self._choice = choice
        self._siblings = siblings          # callable -> list[QMenu]
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._show)

    def eventFilter(self, obj, ev):  # noqa: N802 - Qt naming
        t = ev.type()
        if t == QEvent.Type.Enter:
            self._timer.start()
        elif t in (QEvent.Type.Leave, QEvent.Type.Hide):
            self._timer.stop()
        return False

    def _show(self) -> None:
        try:
            btn = self._choice.button
            if not (btn.isVisible() and btn.underMouse()):
                return
            menu = getattr(self._choice, "menu", None)
            if menu is None or menu.isVisible():
                return
            for m in self._siblings():
                if m is not None and m.isVisible():
                    return
            # QMenu::popup directly: QToolButton::showMenu() detours through
            # the button's internal timer and its C++ underMouse check, which
            # flaps when the input is synthetic - popup() is the same call
            # Qt ends up making anyway, minus the detour.
            menu.popup(btn.mapToGlobal(QPoint(0, btn.height())))
        except RuntimeError:
            pass


class LiveControlBar(QWidget):
    """The round controls shown during a call - 2-column grid, bottom-left."""

    #: 🎙 circle states - green = hearing you, dim = muted,
    #: red = the selected engine has no key and the call is deaf.
    ENGINE_OK = "ok"
    ENGINE_MUTED = "muted"
    ENGINE_ERROR = "error"

    model_changed = Signal(str)
    agent_toggled = Signal(bool)
    voice_changed = Signal(str)
    engine_changed = Signal(str)
    history_toggled = Signal(bool)
    mute_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setHorizontalSpacing(18)
        lay.setVerticalSpacing(18)

        self.model = CircularChoice("ui_model", "model", self, cycle=True)
        self.agent = CircularChoice("ui_agent", "agent off", self)
        _icons = ASSETS_DIR / "icons"
        _eng_icon = next(
            (n for n in ("ui_mic", "ui_voice", "ui_model")
             if (_icons / f"{n}.svg").exists()), "ui_model")
        self.engine = CircularChoice(_eng_icon, "engine", self)
        self.voice = CircularChoice("ui_voice", "voice", self)
        self.hist = RoundActionButton("ui_history", "History", self)
        self._hist_open = False
        self._muted = False
        self._engine_state = self.ENGINE_OK
        _mic_icon = next(
            (n for n in ("ui_mic_mute", "ui_mic_off", "ui_mic")
             if (_icons / f"{n}.svg").exists()), _eng_icon)
        self.mute = RoundActionButton(_mic_icon, "Mute Mic", self)
        _pet_icon = next(
            (n for n in ("ui_pet", "ui_companion", "ui_avatar")
             if (_icons / f"{n}.svg").exists()), _eng_icon)
        self.pet = RoundActionButton(_pet_icon, "Companion", self)
        self._apply_mute_look()

        self._circles = [
            self.model, self.agent,
            self.engine, self.voice,
            self.hist, self.mute,
            self.pet,
        ]
        for i, w in enumerate(self._circles):
            w._bob_phase = i * 1.15
            row = i // 2
            col = i % 2
            lay.addWidget(w, row, col)

        self.agent.changed.connect(self._on_agent)
        self.model.changed.connect(self.model_changed)
        self.voice.changed.connect(self.voice_changed)
        self.engine.changed.connect(self.engine_changed)
        self.hist.clicked.connect(self._on_history)
        self.mute.clicked.connect(self._on_mute)
        # Voice circle (item 11): hovering opens its choice menu - dwell
        # gated, and never while any sibling menu is already up.
        self._voice_hover = _HoverPopup(
            self.voice, lambda: [getattr(c, "menu", None)
                                 for c in self._circles])
        self.voice.installEventFilter(self._voice_hover)
        self.voice.button.installEventFilter(self._voice_hover)
        # Model circle (item 2): a tap still cycles the favourites, but holding
        # the pointer for 1.11 s opens the full list - the long dwell means
        # "I am choosing", never "I was passing by".
        self._model_hover = _HoverPopup(
            self.model, lambda: [getattr(c, "menu", None)
                                 for c in self._circles],
            delay_ms=1110)
        self.model.installEventFilter(self._model_hover)
        self.model.button.installEventFilter(self._model_hover)

        self._bob_t = 0.0
        self._bob_timer = QTimer(self)
        self._bob_timer.setInterval(40)
        self._bob_timer.timeout.connect(self._bob_tick)

    # ── idle-bob animation ────────────────────────────────────────────────
    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        for w in self._circles:
            w._bob_base = None
        self._bob_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._bob_timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        # The layout re-placed the buttons - re-capture their rest position.
        for w in self._circles:
            w._bob_base = None

    def _bob_tick(self) -> None:
        self._bob_t += 0.085
        for w in self._circles:
            btn = getattr(w, "button", None)
            if btn is None:
                continue
            try:
                if w._bob_base is None:
                    w._bob_base = (btn.x(), btn.y())
                if w._pop > 0.0:
                    w._pop = max(0.0, w._pop - 0.09)
                lift = round(math.sin(self._bob_t + w._bob_phase) * 2.0
                             - w._pop * 5.0)
                y = w._bob_base[1] + lift
                holder = btn.parentWidget()
                if holder is not None:
                    # Never let a stale base or a big pop push the circle
                    # outside the holder - a clipped circle looks broken.
                    y = max(0, min(y, max(0, holder.height() - btn.height())))
                btn.move(w._bob_base[0], y)
            except RuntimeError:
                continue

    # ── wiring ────────────────────────────────────────────────────────────
    def _apply_mute_look(self) -> None:
        """Caption + icon for the mute circle, in one place.

        Three copies of ``"muted" if muted else "mic"`` is three chances for
        the drawing and the label to disagree.
        """
        self.mute.set_caption("Muted" if self._muted else "Mute Mic")
        icon = "ui_mic_mute" if self._muted else "ui_mic"
        try:
            path = ASSETS_DIR / "icons" / f"{icon}.svg"
            if path.exists():
                self.mute.button.setIcon(QIcon(str(path)))
        except RuntimeError:
            pass
        self.mute.set_toggle(self._muted)

    def _on_agent(self, value: str) -> None:
        on = value.strip().lower() in ("on", "enabled", "true", "yes")
        self.agent.set_toggle(on)
        self.agent.set_caption("Agent on" if on else "Agent off")
        self.agent_toggled.emit(on)

    def _on_history(self) -> None:
        """Toggle the session-history sidebar (state dot mirrors it)."""
        self._hist_open = not self._hist_open
        self.hist.set_toggle(self._hist_open)
        self.hist._pop = 1.0
        self.history_toggled.emit(self._hist_open)

    def _on_mute(self) -> None:
        """Toggle microphone mute state."""
        self._muted = not self._muted
        self._apply_mute_look()
        # Visual feedback: flash the mute icon
        self.mute._pop = 1.0
        self.mute_toggled.emit(self._muted)
        if self._engine_state != self.ENGINE_ERROR:
            self.set_engine_status(
                self.ENGINE_MUTED if self._muted else self.ENGINE_OK)

    def set_muted(self, muted: bool) -> None:
        """External control of mute state (e.g. from controller settings)."""
        self._muted = bool(muted)
        self._apply_mute_look()
        self.mute_toggled.emit(self._muted)
        if self._engine_state != self.ENGINE_ERROR:
            self.set_engine_status(
                self.ENGINE_MUTED if self._muted else self.ENGINE_OK)

    def set_engine_status(self, state: str) -> None:
        """Paint the 🎙 dot: green listening, dim muted, red no-key."""
        state = str(state or self.ENGINE_OK)
        self._engine_state = state
        try:
            if state == self.ENGINE_ERROR:
                self.engine.dot.set_color("#F87171")
                self.engine.dot.set_on(True)
            else:
                self.engine.dot.set_color(None)
                self.engine.dot.set_on(state == self.ENGINE_OK)
        except RuntimeError:
            pass

    def populate(self, models: Dict, current_model: str,
                 agent_on: bool, voice: str,
                 apply_model=None,
                 stt_engine: Optional[str] = None,
                 favorites: Optional[List[str]] = None) -> None:
        """Fill every menu from live app state.

        ``apply_model`` is stashed (not re-connected per call): this ran on
        every call connect, so the old code stacked one more connection each
        time and a single pick fired ``set_active_model`` N times.

        ``favorites`` restricts the model circle to the user's shortlist. It
        matters: with 99+ models loaded, tapping the circle used to step
        through the entire catalogue to reach the one you wanted.
        """
        names = sorted(models.keys()) if isinstance(models, dict) else list(models or [])
        if favorites is not None:
            have = set(models.keys()) if isinstance(models, dict) else set(models or [])
            pool = [str(f) for f in favorites if str(f) in have]
            # Never hand the circle an empty list - a blank caption with an
            # inert tap is worse than one entry.
            names = pool or ([str(current_model)] if current_model else [])
        self._apply_model = apply_model
        if not getattr(self, "_model_wired", False):
            self._model_wired = True
            self.model.changed.connect(self._on_model_pick)
        self.model.set_options(names, current_model)

        self.agent.set_options(["off", "on"],
                               "on" if agent_on else "off")
        self.agent.set_toggle(agent_on)
        self.agent.set_caption("Agent on" if agent_on else "Agent off")

        self.engine.set_options(
            STT_ENGINE_CHOICES,
            stt_engine or STT_ENGINE_OFFLINE,
            separator_after=1)

        # Bug 0: Structured voice submenus
        from cellium.core.utils import KOKORO_VOICES, EDGE_VOICES
        from cellium.core.config import CEL_VOICE_VARIANTS
        voice_hierarchy = {
            "Kokoro (Offline)": [f"{v[0]}" for v in KOKORO_VOICES],
            "Edge TTS (Online)": [f"{v[0]}" for v in EDGE_VOICES],
            "Melody Voices": list(CEL_VOICE_VARIANTS.keys())
        }
        self.voice.set_hierarchical_options(voice_hierarchy, voice)

    def _on_model_pick(self, name: str) -> None:
        fn = getattr(self, "_apply_model", None)
        if callable(fn):
            try:
                fn(name)
            except Exception:
                pass


# ── Ensure Live Mode Gender/Style Button Offers All 5 Styles in a Popup Menu ──
_LIVE_STYLES = (
    ("♀  Female (Original)", "Female"),
    ("♂  Male (Original)", "Male"),
    ("♀✨ Detailed Female", "Detailed Female"),
    ("♂✨ Detailed Male", "Detailed Male"),
    ("🐣 Chibi", "Chibi"),
)

if "GenderButton" in globals():
    def _gb_set_gender(self, gender: str) -> None:
        g = gender if gender in dict(_LIVE_STYLES).values() else "Female"
        self._gender = g
        short_map = {
            "Female": "♀ Female",
            "Male": "♂ Male",
            "Detailed Female": "♀✨ Det. Female",
            "Detailed Male": "♂✨ Det. Male",
            "Chibi": "🐣 Chibi",
        }
        try:
            self.setText(short_map.get(g, f"🎭 {g}"))
            self.setToolTip(f"Avatar Style: {g} (Click to switch style)")
        except Exception:
            pass
        if hasattr(self, "_actions") and isinstance(self._actions, dict):
            for k, act in self._actions.items():
                act.setChecked(k == g)

    def _gb_open_menu(self) -> None:
        from PySide6.QtWidgets import QMenu
        from PySide6.QtCore import QPoint
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #140D26; color: #F8F4FF; border: 1.5px solid #9333EA; "
            "border-radius: 10px; padding: 4px; } "
            "QMenu::item { padding: 6px 14px; border-radius: 6px; font-size: 12px; } "
            "QMenu::item:selected { background: rgba(147, 51, 234, 0.55); }"
        )
        cur = getattr(self, "_gender", "Female")
        for label, key in _LIVE_STYLES:
            act = menu.addAction(("✓ " if key == cur else "   ") + label)
            act.triggered.connect(lambda _=False, k=key: self._pick(k) if hasattr(self, "_pick") else (self.set_gender(k), self.gender_changed.emit(k)))
        menu.exec(self.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 6)))

    GenderButton.set_gender = _gb_set_gender
    if hasattr(GenderButton, "_toggle"):
        GenderButton._toggle = _gb_open_menu
    if hasattr(GenderButton, "_show_menu"):
        GenderButton._show_menu = _gb_open_menu
