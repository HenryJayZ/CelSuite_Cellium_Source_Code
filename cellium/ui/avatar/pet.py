"""Floating desktop companion (Pet Mode).

The Cerebellium dream made real inside Cellium: a frameless avatar that lives on
your desktop, reacts while you chat, and can be dragged anywhere.

Features:
- Tactile Petting: click or stroke Cel's face to trigger joyful headpat reactions,
  heart glows, and cute purring captions!
- Auto-Hiding Minimalist Controls: sleek frosted glass pill docking under Cel that
  smoothly fades in on mouse hover and fades out on mouse leave.
- Sleep & Fatigue State Machine: energetic idle -> tired after 45s -> sleepy with
  floating "Z"s after 90s. Moving mouse or petting wakes her up with 3 rapid blinks!
- Voice Mic Quick-Toggle: talk directly to Cel from your desktop companion.
- Complete 1,520 Expression Library Support with Male/Female models.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, QTimer, Signal,
)
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu,
    QPushButton, QVBoxLayout, QWidget,
)

from .library import AvatarLibrary
from .widget import AvatarView
from .schema import AvatarExpression

__all__ = ["PetGrip", "PetControlBar", "SpeechBubble", "ScreenshotBubble",
           "FloatingPetWindow", "CompanionStage", "MOODS"]

#: Reply sentiment / intent -> expression name candidates, in priority order.
MOODS: Dict[str, tuple] = {
    "idle":      ("Happy", "Kawaii", "Side Eye", "Relieved"),
    "happy":     ("Happy", "Excited", "Chibi Joy"),
    "excited":   ("Excited", "Happy", "Heart Eyes"),
    "thinking":  ("Thinking", "Focused", "Buffering"),
    "working":   ("Focused", "Galaxy Brain", "Thinking"),
    "love":      ("Heart Eyes", "Flirty", "UwU"),
    "playful":   ("Winking", "Derp", "Happy", "Laughing"),
    "sad":       ("Sad", "Sarcastic", "Crying"),
    "worried":   ("Fearful", "Terrified", "Confused"),
    "tired":     ("Tired", "Sleepy", "Waking"),
    "sleepy":    ("Sleepy", "Tired", "Waking"),
    "confused":  ("Confused", "Disbelief", "Derp"),
    "error":     ("Deadpan", "Error 404", "Annoyed"),
    "sassy":     ("Tsundere", "Annoyed", "Smug"),
    "shocked":   ("Terrified", "Ahegao", "Shocked"),
    "waking":    ("Waking", "Sleepy", "Yandere"),
    "gremlin":   ("Gremlin", "Menacing", "Derp"),
    "deadpan":   ("Deadpan", "Side Eye", "MonkaS"),
    "warm":      ("UwU", "Flirty", "Happy"),
    "surprised": ("Shocked", "Terrified", "Excited"),
    "angry":     ("Angry", "Annoyed", "Tsundere"),
    "blush":     ("Blushing", "Flustered", "UwU"),
    "talk":      ("Happy", "Kawaii", "UwU"),
    "pleading":  ("Pleading", "Sad", "UwU"),
    "proud":     ("Smug", "Cocky", "Happy"),
}

PET_PAT_GREETINGS = [
    "*purrs happily* 💕",
    "(˶˃ᆺ˂˶) *loves headpats!*",
    "Nyaa~ ✨",
    "Hehe, that tickles! 💖",
    "Bestie pats! (｡♥‿♥｡)",
    "Cel loves you! 💜",
]


class SpeechBubble(QFrame):
    """Small rounded caption above the pet."""

    def __init__(self, parent: QWidget | None = None, width: int = 320):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._label = QLabel("", self)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            "color:#f4f4ff;background:transparent;font-size:12px;padding:2px 4px;font-weight:500;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.addWidget(self._label)
        self.setFixedWidth(width)
        self.setStyleSheet(
            "QFrame{background:rgba(27, 22, 54, 0.95);border:1px solid rgba(167,139,250,0.65);"
            "border-radius:16px;}")

    def show_text(self, text: str, msec: int = 4200) -> None:
        self._label.setText(str(text))
        self.adjustSize()
        self.show()
        self.raise_()
        if msec > 0:
            QTimer.singleShot(msec, self.hide)


class ScreenshotBubble(QFrame):
    """One-shot pill floating above the pet canvas.

    [⏎ Screenshot] appends the screenshot Cel just took to the chat, then
    hides itself (one click, gone); [✕] hides it without attaching. Either
    way it stays hidden until the next outside-app wake shows it again.
    """

    shot_clicked = Signal()
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 6, 4)
        lay.setSpacing(6)
        self.btn_shot = QPushButton("⏎ Screenshot")
        self.btn_shot.setCursor(Qt.PointingHandCursor)
        self.btn_shot.setToolTip("Append the screenshot Cel just took to the chat")
        self.btn_shot.clicked.connect(self._on_shot)
        lay.addWidget(self.btn_shot)
        self.btn_x = QPushButton("✕")
        self.btn_x.setFixedWidth(28)
        self.btn_x.setCursor(Qt.PointingHandCursor)
        self.btn_x.setToolTip("Hide for now")
        self.btn_x.clicked.connect(self._on_x)
        lay.addWidget(self.btn_x)
        self.setStyleSheet("""
            ScreenshotBubble {
                background: rgba(18, 12, 32, 0.94);
                border: 1px solid rgba(168, 85, 247, 0.65);
                border-radius: 14px;
            }
            QPushButton {
                background: transparent; border: none; border-radius: 9px;
                color: #E9D5FF; font-size: 12px; font-weight: bold;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background: rgba(168, 85, 247, 0.35); color: #FFFFFF;
            }
        """)
        self.hide()

    def _on_shot(self) -> None:
        self.hide()
        self.shot_clicked.emit()

    def _on_x(self) -> None:
        self.hide()
        self.dismissed.emit()


class PetGrip(QFrame):
    """Drag handle for the pet window. Emits movement while dragging."""

    moved = Signal(int, int)          # dx, dy in global pixels
    double_clicked = Signal()

    def __init__(self, parent: QWidget | None = None, size: int = 24):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(QCursor(Qt.OpenHandCursor))
        self._press_global = QPoint()
        self._dragging = False
        self.setToolTip("Drag Cel anywhere · Double-click for greeting ✨")
        self.setStyleSheet(
            "QFrame{background:rgba(167,139,250,0.35);border-radius:12px;"
            "border:1px solid rgba(196,132,252,0.75);}"
            "QFrame:hover{background:rgba(167,139,250,0.65);border:1px solid #C084FC;}")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._dragging = True
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            return
        now = event.globalPosition().toPoint()
        delta = now - self._press_global
        self._press_global = now
        self.moved.emit(delta.x(), delta.y())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        self.setCursor(QCursor(Qt.OpenHandCursor))
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        self.double_clicked.emit()
        event.accept()


class PetControlBar(QFrame):
    """Auto-hiding frosted glass mini-panel docking seamlessly beneath Cel.
    
    Full Mini-Live control bar: Mic Mute/Unmute, Screen Capture Ribbon, Model Picker,
    Agent Toggle, Voice Picker, Type-to-Cel Toggle, Speech Bubble Toggle, Mood & Sleep.
    """

    mic_clicked = Signal()
    screen_clicked = Signal()
    model_clicked = Signal(object)
    agent_clicked = Signal()
    voice_clicked = Signal(object)
    kbd_clicked = Signal()
    pet_clicked = Signal()
    speech_toggled = Signal(bool)
    mood_selected = Signal(str)
    sleep_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setStyleSheet("""
            QFrame {
                background: rgba(18, 14, 34, 0.92);
                border: 1px solid rgba(168, 85, 247, 0.50);
                border-radius: 17px;
            }
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 12px;
                color: #DDD6FE;
                font-size: 13px;
                padding: 2px 6px;
            }
            QPushButton:hover {
                background: rgba(168, 85, 247, 0.35);
                color: #FFFFFF;
            }
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(6)

        # 🎙️ Mic / Live Listening toggle
        self.btn_mic = QPushButton("🎙️")
        self.btn_mic.setToolTip("Toggle Pet Live Microphone (Green = Listening)")
        self.btn_mic.setCursor(Qt.PointingHandCursor)
        self.btn_mic.clicked.connect(self.mic_clicked.emit)
        lay.addWidget(self.btn_mic)

        # 📸 Screen Ribbon Capture button
        self.btn_screen = QPushButton("📸")
        self.btn_screen.setToolTip("Snap Screen with Purple/Blue Ribbon & Ask Cel")
        self.btn_screen.setCursor(Qt.PointingHandCursor)
        self.btn_screen.clicked.connect(self.screen_clicked.emit)
        lay.addWidget(self.btn_screen)

        # 🧠 Model Quick-Picker
        self.btn_model = QPushButton("🧠")
        self.btn_model.setToolTip("Switch AI Model")
        self.btn_model.setCursor(Qt.PointingHandCursor)
        self.btn_model.clicked.connect(lambda: self.model_clicked.emit(self.btn_model))
        lay.addWidget(self.btn_model)

        # ⚡ Agent Mode Toggle
        self.btn_agent = QPushButton("🤖")
        self.btn_agent.setToolTip("Toggle Autonomous Agent Mode")
        self.btn_agent.setCursor(Qt.PointingHandCursor)
        self.btn_agent.clicked.connect(self.agent_clicked.emit)
        lay.addWidget(self.btn_agent)

        # 🔊 Voice Engine Picker
        self.btn_voice = QPushButton("🔊")
        self.btn_voice.setToolTip("Switch Cel's Spoken Voice")
        self.btn_voice.setCursor(Qt.PointingHandCursor)
        self.btn_voice.clicked.connect(lambda: self.voice_clicked.emit(self.btn_voice))
        lay.addWidget(self.btn_voice)

        # ⌨️ Quick Type-to-Cel Input Bar Toggle
        self.btn_kbd = QPushButton("⌨️")
        self.btn_kbd.setToolTip("Type a message to Cel")
        self.btn_kbd.setCursor(Qt.PointingHandCursor)
        self.btn_kbd.clicked.connect(self.kbd_clicked.emit)
        lay.addWidget(self.btn_kbd)

        # 💖 Tactile Petting button
        self.btn_pet = QPushButton("💖")
        self.btn_pet.setToolTip("Pet Cel (Headpats & Love)")
        self.btn_pet.setCursor(Qt.PointingHandCursor)
        self.btn_pet.clicked.connect(self.pet_clicked.emit)
        lay.addWidget(self.btn_pet)

        # 💬 Speech bubble toggle button
        self.btn_speech = QPushButton("💬")
        self.btn_speech.setToolTip("Toggle Speech Bubbles")
        self.btn_speech.setCursor(Qt.PointingHandCursor)
        self._speech_on = True
        self.btn_speech.clicked.connect(self._toggle_speech)
        lay.addWidget(self.btn_speech)

        # 🎭 Mood quick-picker button
        self.btn_mood = QPushButton("🎭")
        self.btn_mood.setToolTip("Choose Cel's Mood")
        self.btn_mood.setCursor(Qt.PointingHandCursor)
        self.btn_mood.clicked.connect(self._show_mood_menu)
        lay.addWidget(self.btn_mood)

        # 💤 Sleep / Hide button
        self.btn_sleep = QPushButton("💤")
        self.btn_sleep.setToolTip("Put Cel to Sleep (Hide Pet)")
        self.btn_sleep.setCursor(Qt.PointingHandCursor)
        self.btn_sleep.clicked.connect(self.sleep_clicked.emit)
        lay.addWidget(self.btn_sleep)

        # Smooth opacity transition for auto-hiding
        self._opacity_fx = QGraphicsOpacityEffect(self)
        self._opacity_fx.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_fx)

        self._anim = QPropertyAnimation(self._opacity_fx, b"opacity", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)

    def _toggle_speech(self):
        self._speech_on = not self._speech_on
        self.btn_speech.setText("💬" if self._speech_on else "🔇")
        self.btn_speech.setToolTip("Speech Bubbles: ON" if self._speech_on else "Speech Bubbles: MUTED")
        self.speech_toggled.emit(self._speech_on)

    def set_speech_on(self, enabled: bool):
        self._speech_on = bool(enabled)
        self.btn_speech.setText("💬" if self._speech_on else "🔇")

    def set_mic_listening(self, listening: bool):
        if listening:
            self.btn_mic.setText("🎙️")
            self.btn_mic.setStyleSheet("background: rgba(16, 185, 129, 0.45); border: 1px solid #34D399; border-radius: 12px; color: #FFFFFF; padding: 2px 6px;")
            self.btn_mic.setToolTip("Pet Mic: LISTENING (click to mute)")
        else:
            self.btn_mic.setText("🔇")
            self.btn_mic.setStyleSheet("")
            self.btn_mic.setToolTip("Pet Mic: MUTED (click to unmute and talk)")

    def set_agent_active(self, active: bool):
        self.btn_agent.setText("⚡" if active else "🤖")
        self.btn_agent.setStyleSheet(
            "background: rgba(6, 182, 212, 0.45); border: 1px solid #67E8F9; border-radius: 12px; color: #FFFFFF; padding: 2px 6px;"
            if active else ""
        )

    def _show_mood_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #181430;
                color: #F3EEFF;
                border: 1px solid rgba(168, 85, 247, 0.6);
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item:selected {
                background: rgba(168, 85, 247, 0.4);
                border-radius: 4px;
            }
        """)
        for mood_key in ("happy", "love", "playful", "excited", "warm", "thinking", "sassy", "tired"):
            act = menu.addAction(f"✨ {mood_key.title()}")
            act.triggered.connect(lambda checked=False, m=mood_key: self.mood_selected.emit(m))
        menu.exec(self.btn_mood.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    def fade_in(self):
        self._anim.stop()
        self._anim.setStartValue(self._opacity_fx.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()

    def fade_out(self):
        self._anim.stop()
        self._anim.setStartValue(self._opacity_fx.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()


class FloatingPetWindow(QWidget):
    """Frameless translucent always-on-top window wrapping AvatarView and PetControlBar."""

    closed = Signal()
    petted = Signal()
    mic_triggered = Signal()
    screen_triggered = Signal()
    model_triggered = Signal(object)
    agent_triggered = Signal()
    voice_triggered = Signal(object)
    text_submitted = Signal(str)
    speech_toggled = Signal(bool)
    mood_triggered = Signal(str)
    screenshot_requested = Signal()
    shot_dismissed = Signal()

    def __init__(self, expression: Optional[AvatarExpression] = None,
                 size: int = 320, scale: float = 0.52):
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        self.bubble = SpeechBubble(self)
        self.bubble.hide()

        self.shot = ScreenshotBubble(self)
        self.shot.shot_clicked.connect(self.screenshot_requested.emit)
        self.shot.dismissed.connect(self.shot_dismissed.emit)
        self.shot.hide()

        self.view = AvatarView(expression=expression, scale=scale)
        self.view.setFixedSize(size, int(size * 0.75))
        self.view.installEventFilter(self)

        self.grip = PetGrip(self)
        self.grip.moved.connect(self._drag_by)
        self.grip.double_clicked.connect(self._on_grip_double)

        self.control_bar = PetControlBar(self)
        self.control_bar.mic_clicked.connect(self.mic_triggered.emit)
        self.control_bar.screen_clicked.connect(self.screen_triggered.emit)
        self.control_bar.model_clicked.connect(self.model_triggered.emit)
        self.control_bar.agent_clicked.connect(self.agent_triggered.emit)
        self.control_bar.voice_clicked.connect(self.voice_triggered.emit)
        self.control_bar.kbd_clicked.connect(self._toggle_input_bar)
        self.control_bar.pet_clicked.connect(self.petted.emit)
        self.control_bar.speech_toggled.connect(self.speech_toggled.emit)
        self.control_bar.mood_selected.connect(self.mood_triggered.emit)
        self.control_bar.sleep_clicked.connect(self.close)

        # Live Status Pill (Listening / Thinking / Speaking + VU bar)
        self.status_pill = QLabel("", self)
        self.status_pill.setAlignment(Qt.AlignCenter)
        self.status_pill.setStyleSheet(
            "QLabel { background: rgba(18, 12, 34, 0.88); color: #C084FC; "
            "border: 1px solid rgba(168, 85, 247, 0.45); border-radius: 10px; "
            "padding: 2px 10px; font-size: 11px; font-weight: bold; }"
        )
        self.status_pill.hide()

        # Quick Type-to-Cel Input Bar right on the Pet!
        from PySide6.QtWidgets import QLineEdit
        self.input_bar = QLineEdit(self)
        self.input_bar.setPlaceholderText("Message Cel… (Enter to send)")
        self.input_bar.setStyleSheet(
            "QLineEdit { background: rgba(14, 10, 26, 0.94); color: #F8F4FF; "
            "border: 1.5px solid #A855F7; border-radius: 12px; padding: 4px 10px; font-size: 12px; }"
        )
        self.input_bar.returnPressed.connect(self._submit_input_bar)
        self.input_bar.hide()

        # Layout hierarchy
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        lay.addWidget(self.view, alignment=Qt.AlignCenter)
        lay.addWidget(self.status_pill, alignment=Qt.AlignCenter)
        lay.addWidget(self.input_bar)
        
        # Bottom controls row hosting grip and control pill
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(8, 0, 8, 2)
        bottom_row.addWidget(self.grip)
        bottom_row.addSpacing(6)
        bottom_row.addWidget(self.control_bar)
        lay.addLayout(bottom_row)

        self.resize(size + 36, int(size * 0.75) + 84)

    # ── interactivity & auto-hiding controls ─────────────────────────────
    def enterEvent(self, event) -> None:
        self.control_bar.fade_in()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.control_bar.fade_out()
        super().leaveEvent(event)

    def eventFilter(self, watched, event):
        """Intercept mouse clicks on Cel's avatar to enable direct tactile petting!"""
        if watched is self.view:
            if event.type() == event.Type.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    self.petted.emit()
                    return True
                elif event.button() == Qt.RightButton:
                    self._show_context_menu(event.globalPosition().toPoint())
                    return True
        return super().eventFilter(watched, event)

    def _show_context_menu(self, global_pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #181430;
                color: #F3EEFF;
                border: 1px solid rgba(168, 85, 247, 0.6);
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item:selected {
                background: rgba(168, 85, 247, 0.4);
                border-radius: 4px;
            }
        """)
        act_pet = menu.addAction("💖 Pet Cel (Headpats)")
        act_pet.triggered.connect(self.petted.emit)

        act_talk = menu.addAction("🎙️ Talk to Cel")
        act_talk.triggered.connect(self.mic_triggered.emit)

        menu.addSeparator()
        act_sleep = menu.addAction("💤 Sleep (Hide)")
        act_sleep.triggered.connect(self.close)

        menu.exec(global_pos)

    # ── geometry ─────────────────────────────────────────────────────────
    def _drag_by(self, dx: int, dy: int) -> None:
        self.move(self.x() + dx, self.y() + dy)
        self._reposition_bubble()

    def _reposition_bubble(self) -> None:
        if self.bubble.isVisible():
            bw, bh = self.bubble.width(), self.bubble.height()
            self.bubble.move(
                max(0, (self.width() - bw) // 2),
                max(0, self.view.y() - bh - 6),
            )
        self._reposition_shot()

    def show_screenshot_bubble(self) -> None:
        """Float the one-shot Screenshot pill above the canvas."""
        try:
            self._reposition_shot()
            self.shot.show()
            self.shot.raise_()
        except Exception:
            pass

    def hide_screenshot_bubble(self) -> None:
        try:
            self.shot.hide()
        except Exception:
            pass

    def _reposition_shot(self) -> None:
        try:
            bw = self.shot.sizeHint().width()
            bh = self.shot.sizeHint().height()
            self.shot.resize(bw, bh)
            self.shot.move(
                max(0, (self.width() - bw) // 2),
                max(0, self.view.y() - bh - 4),
            )
        except Exception:
            pass

    def _on_grip_double(self) -> None:
        self.say("Hi! ✨")

    def _toggle_input_bar(self) -> None:
        vis = not self.input_bar.isVisible()
        self.input_bar.setVisible(vis)
        if vis:
            self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, False)
            self.show()
            self.activateWindow()
            self.input_bar.setFocus()
        else:
            self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
            self.show()

    def _submit_input_bar(self) -> None:
        txt = self.input_bar.text().strip()
        if not txt:
            return
        self.input_bar.clear()
        self.text_submitted.emit(txt)

    def set_status_text(self, text: str) -> None:
        t = (text or "").strip()
        if not t:
            self.status_pill.hide()
        else:
            self.status_pill.setText(t)
            self.status_pill.adjustSize()
            self.status_pill.show()

    # ── content ──────────────────────────────────────────────────────────
    def set_expression(self, expression: Optional[AvatarExpression]) -> None:
        self.view.set_expression(expression)

    def say(self, text: str, msec: int = 4200) -> None:
        self.bubble.show_text(text, msec)
        self._reposition_bubble()

    # ── sleepy "Z" floaties ──────────────────────────────────────────
    def start_zzz(self) -> None:
        """Float translucent 'Z' letters above the face while sleepy.

        Idempotent: calling twice keeps a single loop. Each letter rises,
        fades, and restarts on its own stagger while ``_zzz_active`` holds,
        so sleepy Cel visibly dreams until woken. Pure child QLabels with
        property animations - no paintEvent hacking, everything dies with
        the window.
        """
        try:
            if getattr(self, "_zzz_active", False):
                return
            self._zzz_active = True
            self._zzz_labels = []
            self._zzz_anims = []
            self._zzz_bases = []
            vw = max(80, self.view.width())
            for i, (txt, dx, size) in enumerate((("Z", -30, 24), ("z", 8, 17), ("Z", 40, 13))):
                lab = QLabel(txt, self.view)
                lab.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                lab.setStyleSheet(
                    "background: transparent; border: none; "
                    f"color: rgba(201, 182, 255, 0.95); font-size: {size}px; font-weight: bold;")
                lab.adjustSize()
                base = QPoint(vw // 2 + dx - lab.width() // 2, 24 + i * 12)
                lab.move(base)
                lab.show()
                eff = QGraphicsOpacityEffect(lab)
                eff.setOpacity(0.0)
                lab.setGraphicsEffect(eff)
                rise = QPropertyAnimation(lab, b"pos", self)
                rise.setDuration(2600)
                rise.setStartValue(base)
                rise.setEndValue(base + QPoint(10, -54))
                rise.setEasingCurve(QEasingCurve.OutQuad)
                fade = QPropertyAnimation(eff, b"opacity", self)
                fade.setDuration(2600)
                fade.setKeyValueAt(0.0, 0.0)
                fade.setKeyValueAt(0.25, 0.9)
                fade.setKeyValueAt(1.0, 0.0)
                rise.finished.connect(lambda idx=i: self._restart_zzz(idx))
                self._zzz_labels.append(lab)
                self._zzz_anims.append((rise, fade))
                self._zzz_bases.append(base)
                QTimer.singleShot(i * 850, lambda _r=rise, _f=fade: (_r.start(), _f.start()))
        except Exception:
            pass

    def _restart_zzz(self, idx: int) -> None:
        """Loop one Z letter while sleep is active; silently stops otherwise."""
        try:
            if not getattr(self, "_zzz_active", False):
                return
            rise, fade = self._zzz_anims[idx]
            lab = self._zzz_labels[idx]
            base = self._zzz_bases[idx]
            lab.move(base)
            rise.setStartValue(base)
            rise.setEndValue(base + QPoint(10, -54))
            rise.start()
            fade.start()
        except (Exception, RuntimeError):
            pass

    def stop_zzz(self) -> None:
        """End the sleepy Z loop and remove every letter (safe anytime)."""
        try:
            self._zzz_active = False
            for rise, fade in getattr(self, "_zzz_anims", []):
                for anim in (rise, fade):
                    try:
                        anim.stop()
                    except Exception:
                        pass
            for lab in getattr(self, "_zzz_labels", []):
                try:
                    lab.hide()
                    lab.deleteLater()
                except Exception:
                    pass
            self._zzz_anims = []
            self._zzz_labels = []
            self._zzz_bases = []
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        self.view.dispose()
        self.closed.emit()
        super().closeEvent(event)


class CompanionStage(QWidget):
    """Controller: owns the pet window, rotates idles, maps moods, and manages fatigue."""

    expression_changed = Signal(str)
    voice_requested = Signal()

    def __init__(self, parent: QWidget | None = None,
                 library: Optional[AvatarLibrary] = None,
                 gender: str = "Female",
                 size: int = 300,
                 scale: float = 0.5,
                 idle_seconds: int = 14):
        super().__init__(parent)
        self.lib = library or AvatarLibrary()
        self.gender = gender
        self._hidden: set = set()
        self.idle_names = self._visible_idle_names(gender)
        if not self.idle_names:
            self.idle_names = [n for n in self.lib.names(gender)
                               if n not in self._hidden] or self.lib.names(gender)
        self.idle_seconds = max(3, int(idle_seconds))
        self._current: Optional[str] = None
        self._rng = random.Random(0xBEEF)
        self._speak = True
        self._base_size = max(140, int(size))
        self._base_scale = max(0.05, float(scale))

        # Sleep / Fatigue State Machine (Bug 17.5 & user request)
        self._state = "idle"  # "reacting" -> "idle" -> "tired" -> "sleepy"
        self._inactivity_secs = 0

        # Sequential multi-mood playback (Bug 38): a finished reply may carry
        # several mood directives; they play back in order, ~2.4s per face.
        self._mood_queue: list = []
        self._mood_step_ms = 2400
        self._mood_timer = QTimer(self)
        self._mood_timer.setSingleShot(True)
        self._mood_timer.timeout.connect(self._advance_mood_queue)

        self.window = FloatingPetWindow(self._pick(self.idle_names), size=size, scale=scale)
        self.window.closed.connect(self._on_window_closed)
        self.window.petted.connect(self.pet)
        self.window.mic_triggered.connect(self.voice_requested.emit)
        self.window.speech_toggled.connect(self.set_speak_enabled)
        self.window.mood_triggered.connect(lambda m: self.react(m))
        self._place_bottom_right()

        # 30 FPS Mouth Lip-Sync timer while Cel speaks in Pet Mode
        from ..live.talk_animation import TalkEnvelope, talking_expression
        self._talk_env = TalkEnvelope(hz=12.0)
        self._talking_expr_fn = talking_expression
        self._speaking = False
        self._talk_base_expr = None
        self._talk_timer = QTimer(self)
        self._talk_timer.setInterval(33)
        self._talk_timer.timeout.connect(self._on_talk_tick)

        # Idle rotation & activity tick (every 1 second)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start()

    # ── placement ────────────────────────────────────────────────────────
    def _place_bottom_right(self, margin: int = 40) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.window.move(120, 120)
            return
        area = screen.availableGeometry()
        self.window.move(
            area.right() - self.window.width() - margin,
            area.bottom() - self.window.height() - margin,
        )

    # ── lookup ───────────────────────────────────────────────────────────
    def _pick(self, names: List[str]) -> Optional[AvatarExpression]:
        for n in names:
            expr = self.lib.get(self.gender, n)
            if expr is not None:
                self._current = n
                return expr
        return None

    def _lookup_mood(self, mood: str) -> Optional[AvatarExpression]:
        candidates = MOODS.get(mood, MOODS["idle"])
        for n in candidates:
            expr = self.lib.get(self.gender, n)
            if expr is not None:
                return expr
        for n in MOODS["idle"]:
            expr = self.lib.get(self.gender, n)
            if expr is not None:
                return expr
        return None

    # ── public API ───────────────────────────────────────────────────────
    def show(self) -> None:
        self.window.show()
        self.window.raise_()

    def hide(self) -> None:
        self.window.hide()

    def toggle(self) -> bool:
        if self.window.isVisible():
            self.hide()
            return False
        self.show()
        return True

    @property
    def visible(self) -> bool:
        return self.window.isVisible()

    def available(self) -> bool:
        return bool(self.idle_names)

    def set_speak_enabled(self, on: bool) -> None:
        self._speak = bool(on)
        self.window.control_bar.set_speech_on(self._speak)

    def set_speaking(self, speaking: bool) -> None:
        """Animate Cel's mouth at 30 FPS while she speaks in Pet Mode!"""
        self._speaking = bool(speaking)
        if self._speaking:
            self._talk_base_expr = self.window.view.expression() or self._lookup_mood("happy")
            self.window.set_status_text("🔊 Speaking…")
            if not self._talk_timer.isActive():
                self._talk_timer.start()
        else:
            self._talk_timer.stop()
            if self._talk_base_expr is not None:
                self.window.set_expression(self._talk_base_expr)

    def _on_talk_tick(self) -> None:
        if not self._speaking or self._talk_base_expr is None:
            return
        openness = self._talk_env.step(1.0 / 30.0, progress=1.0, active=True)
        try:
            self.window.set_expression(self._talking_expr_fn(self._talk_base_expr, openness))
        except Exception:
            pass

    def set_scale(self, scale: float) -> None:
        try:
            factor = max(0.4, min(2.2, float(scale)))
            size = max(140, int(self._base_size * factor))
            self.window.view.setFixedSize(size, int(size * 0.75))
            self.window.view.set_scale(self._base_scale * factor)
            self.window.resize(size + 16, int(size * 0.75) + 52)
            self.window._reposition_bubble()
            self._place_bottom_right()
            self.window.view.update()
            if self._state == "sleepy":
                self.window.stop_zzz()
                self.window.start_zzz()
        except Exception:
            pass

    def set_expression_by_name(self, name: str) -> bool:
        expr = self.lib.get(self.gender, name)
        if expr is None:
            return False
        self._current = name
        self.window.set_expression(expr)
        self.expression_changed.emit(name)
        return True

    def react(self, mood: str = "idle", say: str = "", msec: int = 4200) -> bool:
        """Show an expression matching ``mood``. Linger for 15-30s before idle."""
        expr = self._lookup_mood(mood)
        if expr is None:
            return False
        self._current = expr.name
        self.window.set_expression(expr)
        self.expression_changed.emit(expr.name)
        if say and self._speak:
            self.window.say(say, msec)
        self._state = "reacting"
        self._inactivity_secs = 0
        try:
            if mood == "sleepy":
                self.window.start_zzz()
            else:
                self.window.stop_zzz()
        except Exception:
            pass
        return True

    def pet(self) -> None:
        """Tactile Petting: patting Cel triggers joy, hearts, bounce and headpat caption!"""
        # If sleeping, wake up with 3 blinks!
        if self._state in ("sleepy", "tired"):
            self.wake_up()
        
        # Joyful loving reaction
        self.react("love", say=random.choice(PET_PAT_GREETINGS), msec=3200)
        self.wave()

    def wake_up(self) -> None:
        """Wakes up Cel from sleepy/tired states with 3 rapid blinks."""
        self._state = "idle"
        self._inactivity_secs = 0
        try:
            self._cancel_mood_sequence()
        except Exception:
            pass
        try:
            self.window.stop_zzz()
        except Exception:
            pass
        
        # 3 rapid blinks in sequence
        def blink():
            self.set_expression_by_name("Waking")
            QTimer.singleShot(180, lambda: self.react("idle"))
        
        blink()
        QTimer.singleShot(400, blink)
        QTimer.singleShot(800, blink)

    def say(self, text: str, msec: int = 4200) -> None:
        if not self._speak:
            return
        self.window.say(text, msec)

    def show_screenshot_bubble(self) -> None:
        """Float the one-shot Screenshot pill above the pet canvas."""
        try:
            self.window.show_screenshot_bubble()
        except Exception:
            pass

    def hide_screenshot_bubble(self) -> None:
        try:
            self.window.hide_screenshot_bubble()
        except Exception:
            pass

    def wave(self) -> None:
        anim = QPropertyAnimation(self.window, b"pos", self)
        anim.setDuration(320)
        anim.setEasingCurve(QEasingCurve.InOutSine)
        base = self.window.pos()
        anim.setStartValue(base)
        anim.setKeyValueAt(0.5, base + QPoint(0, -14))
        anim.setEndValue(base)
        anim.start()
        self._wave_anim = anim

    # ── fatigue & idle state machine ─────────────────────────────────────
    def _on_tick(self) -> None:
        if not self.visible:
            return
        self._inactivity_secs += 1

        # State transitions
        if self._state == "reacting" and self._inactivity_secs >= 20:
            self._state = "idle"
            self._rotate_idle()
        elif self._state == "idle":
            if self._inactivity_secs >= 90:
                self._state = "sleepy"
                self.react("sleepy", say="Zzz... 💤" if self._speak else "", msec=3000)
            elif self._inactivity_secs >= 45:
                self._state = "tired"
                self.react("tired")
            elif self._inactivity_secs % self.idle_seconds == 0:
                self._rotate_idle()

    def _rotate_idle(self) -> None:
        if not self.idle_names:
            return
        others = [n for n in self.idle_names if n != self._current]
        if not others:
            return
        self.set_expression_by_name(self._rng.choice(others))

    def _visible_idle_names(self, gender: str) -> list:
        """Base expressions (the readable faces), minus curated-out variants."""
        names = []
        for n in self.lib.names(gender):
            if n in self._hidden:
                continue
            expr = self.lib.get(gender, n)
            if expr is not None and expr.modifier is None:
                names.append(n)
        return names

    def set_hidden(self, names) -> None:
        """Curated-out variants (Avatar Studio wizard) skip idle rotation."""
        try:
            self._hidden = {str(n) for n in (names or [])}
        except Exception:
            self._hidden = set()
        self.idle_names = self._visible_idle_names(self.gender) or [
            n for n in self.lib.names(self.gender) if n not in self._hidden]
        if self._current in self._hidden:
            self._rotate_idle()

    def set_gender(self, gender: str) -> bool:
        if gender not in self.lib.expressions:
            return False
        self.gender = gender
        self.idle_names = self._visible_idle_names(gender) or [
            n for n in self.lib.names(gender) if n not in self._hidden]
        self.react("idle")
        return True

    def stop(self) -> None:
        self._tick_timer.stop()
        try:
            self._cancel_mood_sequence()
        except Exception:
            pass
        try:
            self.window.stop_zzz()
        except Exception:
            pass
        self.window.view.dispose()

    def dispose(self) -> None:
        self.stop()
        self.window.close()

    def _on_window_closed(self) -> None:
        self._tick_timer.stop()
        try:
            self._cancel_mood_sequence()
        except Exception:
            pass
        try:
            self.window.stop_zzz()
        except Exception:
            pass

    # ── chat bridge ──────────────────────────────────────────────────────
    def respond_to(self, text: str, *, reply: str = "", detector: Optional[Callable[[str], str]] = None,
                   mood: Optional[str] = None) -> str:
        """Map assistant text to a mood and speak it. Honors explicit mood tag."""
        chosen_mood = mood or (detector(text) if detector else self._guess_mood(text))
        spoken = (reply or text or "").strip()
        if len(spoken) > 220:
            spoken = spoken[:217].rstrip() + "…"
        self.react(chosen_mood, say=spoken)
        self.wave()
        return chosen_mood

    # ── sequential mood playback ─────────────────────────────────────
    def play_mood_sequence(self, moods, step_ms: int = 2400, max_steps: int = 6) -> None:
        """Play every mood in a finished reply, in order, one face per step.

        Silent face changes only (no re-speak, no wave spam): the reply was
        already spoken by :meth:`respond_to`. A new call replaces the old
        queue, so rapid replies never pile up face-dances.
        """
        try:
            self._cancel_mood_sequence()
            seq = []
            for m in (moods or []):
                key = str(m or "").strip().lower()
                if key and (not seq or seq[-1] != key):
                    seq.append(key)
            self._mood_queue = seq[:max(1, int(max_steps))]
            self._mood_step_ms = max(800, int(step_ms))
            if self._mood_queue:
                self._advance_mood_queue()
        except Exception:
            pass

    def _advance_mood_queue(self) -> None:
        """Apply the next queued face; schedule the following step."""
        try:
            if not self._mood_queue:
                return
            mood = self._mood_queue.pop(0)
            try:
                if self.visible:
                    self.react(mood)
            except Exception:
                pass
            if self._mood_queue:
                self._mood_timer.start(self._mood_step_ms)
        except Exception:
            pass

    def _cancel_mood_sequence(self) -> None:
        try:
            self._mood_queue = []
            self._mood_timer.stop()
        except Exception:
            pass

    @staticmethod
    def _guess_mood(text: str) -> str:
        t = (text or "").lower()
        table = (
            (("error", "exception", "traceback", "failed", "cannot", "denied"), "error"),
            (("sorry", "apolog", "unfortunately", "regret"), "sad"),
            (("!🎉", "congratulations", "yay", "awesome", "🎉"), "excited"),
            (("love", "❤", "beautiful", "gorgeous", "amazing", "💜"), "love"),
            (("haha", "lol", "😂", "joke", "funny", "playful"), "playful"),
            (("?", "unclear", "not sure", "ambiguous", "confus"), "confused"),
            (("think", "let me", "analyz", "considering", "reasoning"), "thinking"),
            (("done", "complete", "finished", "✅", "success"), "happy"),
            (("warning", "careful", "danger", "risk", "⚠"), "worried"),
            (("sleep", "tired", "rest", "zzz"), "sleepy"),
        )
        for needles, mood in table:
            if any(n in t for n in needles):
                return mood
        return "idle"


_orig_comp_react = CompanionStage.react

def _patched_comp_react(self, mood: str, say: str = "", msec: int = 3500) -> str:
    from cellium.core.utils import parse_mood_sequence
    seq = parse_mood_sequence(mood)
    if len(seq) > 1:
        self.play_mood_sequence(seq, sentence_text=say)
        if say:
            self.say(say, msec=msec)
        return seq[0]
    target = seq[0] if seq else mood
    res = _orig_comp_react(self, target, say=say, msec=msec)
    if getattr(self, "_speaking", False):
        self._talk_base_expr = self.window.view.expression()
    return res

def _comp_play_mood_sequence(self, moods, total_ms: int = 0, sentence_text: str = "") -> None:
    from cellium.core.utils import parse_mood_sequence
    seq = parse_mood_sequence(", ".join(moods) if isinstance(moods, (list, tuple)) else str(moods))
    if not seq:
        return
    for tm in getattr(self, "_pet_mood_timers", []):
        try:
            tm.stop()
            tm.deleteLater()
        except Exception:
            pass
    self._pet_mood_timers = []
    _orig_comp_react(self, seq[0], say="", msec=3500)
    if getattr(self, "_speaking", False):
        self._talk_base_expr = self.window.view.expression()
    if len(seq) == 1:
        return
    if total_ms <= 0:
        words = max(4, len((sentence_text or "").split()))
        total_ms = max(1800, min(14000, words * 340))
    n = len(seq)
    for idx in range(1, n):
        delay = int(round(total_ms * (idx / float(n))))
        tm = QTimer(self)
        tm.setSingleShot(True)
        tm.timeout.connect(lambda m=seq[idx]: (_orig_comp_react(self, m, say="", msec=3500), setattr(self, "_talk_base_expr", self.window.view.expression())))
        tm.start(max(250, delay))
        self._pet_mood_timers.append(tm)

CompanionStage.react = _patched_comp_react
CompanionStage.play_mood_sequence = _comp_play_mood_sequence


# ── #7 & #8: Complete Pet Mode Overhaul (SVG Icons, Hover Help Box, Close-Up Zoom, Speech Card, Stable Idle) ──
from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel
from cellium.core.svg_icons import get_svg_icon

_PET_STATE_COLORS = {
    "ready":    "#10B981",
    "stt":      "#3B82F6",
    "loading":  "#FACC15",
    "thinking": "#A855F7",
    "tts":      "#F97316",
    "error":    "#EF4444",
}

_PET_BTN_SPECS = {
    "btn_mic":    ("mic",      "Voice Mic • Hands-free talk to Cel (click to mute/unmute)"),
    "btn_screen": ("camera",   "Screen Snap • Flash ribbon, capture screen & ask Cel"),
    "btn_model":  ("cpu",      "AI Model • Switch active LLM for Pet & Chat"),
    "btn_agent":  ("bot",      "Agent Mode • Toggle autonomous tools & terminal execution"),
    "btn_voice":  ("volume",   "Voice Engine • Switch Kokoro Offline or Edge TTS voice"),
    "btn_kbd":    ("keyboard", "Quick Type • Open mini text input bar right on Cel"),
    "btn_pet":    ("heart",    "Headpat • Give Cel headpats & affection"),
    "btn_speech": ("chat",     "Speech Bubbles • Toggle floating transcript bubbles"),
    "btn_mood":   ("mood",     "Expression • Pick Cel's current mood manually"),
    "btn_sleep":  ("moon",     "Sleep • Dismiss companion & return to normal window"),
}


class _PetButtonHoverFilter(QObject):
    """Event filter that shows the dynamic floating help box when hovering any Pet button!"""
    def __init__(self, pet_win, help_text: str):
        super().__init__(pet_win)
        self._win = pet_win
        self._text = help_text

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (QEvent.Type.Enter, QEvent.Type.HoverEnter, QEvent.Type.MouseMove):
            if hasattr(self._win, "show_hover_help"):
                self._win.show_hover_help(self._text)
        elif et in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            if hasattr(self._win, "hide_hover_help"):
                self._win.hide_hover_help()
        return False


def _apply_svg_icons_and_hover_to_pet_window(pet_win) -> None:
    """Retroactively convert all PetControlBar buttons to SVG/PNG icons & wire floating hover help."""
    if pet_win is None:
        return
    # 1. Make Pet window & AvatarView 100% transparent + zoom face up close (1.58x)!
    pet_win.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    pet_win.setAutoFillBackground(False)
    pet_win.setStyleSheet("background: transparent; border: none;")

    if hasattr(pet_win, "view") and pet_win.view is not None:
        pet_win.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        pet_win.view.setAutoFillBackground(False)
        pet_win.view.setStyleSheet("background: transparent; border: none;")
        pet_win.view._pet_zoom = 1.58
        pet_win.view._show_grid = False
        pet_win.view.setMinimumSize(250, 175)

    # 2. Lock status_pill to a fixed width so "Listening ●●●" NEVER jumps or resizes the layout!
    if hasattr(pet_win, "status_pill") and pet_win.status_pill is not None:
        pet_win.status_pill.setFixedWidth(220)
        pet_win.status_pill.setFixedHeight(24)

    # 3. Create the Dynamic Floating Hover Help Box right above the control bar!
    if not hasattr(pet_win, "hover_help_pill") or pet_win.hover_help_pill is None:
        hp = QLabel("", pet_win)
        hp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hp.setWordWrap(True)
        hp.setFixedWidth(254)
        hp.setMinimumHeight(26)
        hp.setStyleSheet(
            "QLabel { background: rgba(16, 10, 32, 0.95); color: #F3E8FF; "
            "border: 1.2px solid #C084FC; border-radius: 9px; "
            "padding: 4px 10px; font-size: 11px; font-weight: 600; }"
        )
        hp.hide()
        pet_win.hover_help_pill = hp
        if pet_win.layout() is not None:
            # Insert right above the bottom controls row
            idx = max(0, pet_win.layout().count() - 1)
            pet_win.layout().insertWidget(idx, hp, 0, Qt.AlignmentFlag.AlignHCenter)

    # 4. Create a visible, non-clipped Floating Speech & Transcript Card at the TOP of the Pet window!
    if not hasattr(pet_win, "chat_bubble_card") or pet_win.chat_bubble_card is None:
        cb = QLabel("", pet_win)
        cb.setWordWrap(True)
        cb.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cb.setFixedWidth(264)
        cb.setMinimumHeight(34)
        cb.setStyleSheet(
            "QLabel { background: rgba(18, 12, 36, 0.94); color: #F8F4FF; "
            "border: 1.5px solid #A855F7; border-radius: 13px; "
            "padding: 8px 12px; font-size: 12px; font-weight: 500; }"
        )
        cb.hide()
        pet_win.chat_bubble_card = cb
        pet_win._chat_card_timer = QTimer(pet_win)
        pet_win._chat_card_timer.setSingleShot(True)
        pet_win._chat_card_timer.timeout.connect(cb.hide)
        if pet_win.layout() is not None:
            pet_win.layout().insertWidget(0, cb, 0, Qt.AlignmentFlag.AlignHCenter)

    # 5. Strip emojis from every PetControlBar button and install SVG/PNG QIcons + Hover Filters!
    cbar = getattr(pet_win, "control_bar", None)
    if cbar is not None:
        cbar._hover_filters = []
        for attr, (ic_name, help_txt) in _PET_BTN_SPECS.items():
            btn = getattr(cbar, attr, None)
            if btn is None:
                continue
            ic = get_svg_icon(ic_name)
            if not ic.isNull():
                btn.setIcon(ic)
                btn.setIconSize(QSize(15, 15))
                btn.setText("")
            btn.setFixedSize(28, 26)
            btn.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            hf = _PetButtonHoverFilter(pet_win, help_txt)
            btn.installEventFilter(hf)
            cbar._hover_filters.append(hf)

    pet_win.resize(284, 310)


def _pet_win_show_hover_help(self, text: str) -> None:
    hp = getattr(self, "hover_help_pill", None)
    if hp is not None:
        hp.setText(text)
        hp.adjustSize()
        hp.setFixedWidth(254)
        hp.show()


def _pet_win_hide_hover_help(self) -> None:
    hp = getattr(self, "hover_help_pill", None)
    if hp is not None:
        hp.hide()


def _pet_win_say_v8(self, text: str, msec: int = 4500) -> None:
    """Show speech in the visible top `chat_bubble_card` AND sync `self.bubble._text`."""
    _apply_svg_icons_and_hover_to_pet_window(self)
    clean = (text or "").strip()
    if hasattr(self, "bubble") and self.bubble is not None:
        self.bubble._text = clean
    card = getattr(self, "chat_bubble_card", None)
    if card is not None:
        if not clean:
            card.hide()
            return
        card.setText(clean)
        card.setFixedWidth(264)
        card.adjustSize()
        card.show()
        if hasattr(self, "_chat_card_timer") and self._chat_card_timer is not None:
            self._chat_card_timer.start(max(2500, int(msec or 4500)))


def _pet_win_set_status_text_v8(self, text: str) -> None:
    """Update status_pill WITHOUT calling adjustSize() so width stays locked at 220px!"""
    t = (text or "").strip()
    if not t:
        self.status_pill.hide()
    else:
        self.status_pill.setFixedWidth(220)
        self.status_pill.setFixedHeight(24)
        self.status_pill.setText(t)
        self.status_pill.show()


def _pet_win_paint_transparent(self, _event) -> None:
    """Ensure FloatingPetWindow never paints an opaque background rectangle."""
    painter = QPainter(self)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
    painter.end()


_orig_fpw_init_v8 = FloatingPetWindow.__init__
def _patched_fpw_init_v8(self, *args, **kwargs):
    _orig_fpw_init_v8(self, *args, **kwargs)
    _apply_svg_icons_and_hover_to_pet_window(self)

FloatingPetWindow.__init__ = _patched_fpw_init_v8
FloatingPetWindow.show_hover_help = _pet_win_show_hover_help
FloatingPetWindow.hide_hover_help = _pet_win_hide_hover_help
FloatingPetWindow.say = _pet_win_say_v8
FloatingPetWindow.set_status_text = _pet_win_set_status_text_v8
FloatingPetWindow.paintEvent = _pet_win_paint_transparent


def _svg_set_speech_on(self, enabled: bool):
    self._speech_on = bool(enabled)
    self.btn_speech.setIcon(get_svg_icon("chat" if self._speech_on else "mic_off"))
    self.btn_speech.setText("")


def _svg_set_mic_listening(self, listening: bool):
    if listening:
        self.btn_mic.setIcon(get_svg_icon("mic"))
        self.btn_mic.setText("")
        self.btn_mic.setStyleSheet("background: rgba(16, 185, 129, 0.45); border: 1px solid #34D399; border-radius: 12px; padding: 4px 6px;")
    else:
        self.btn_mic.setIcon(get_svg_icon("mic_off"))
        self.btn_mic.setText("")
        self.btn_mic.setStyleSheet("")


def _svg_set_agent_active(self, active: bool):
    self.btn_agent.setIcon(get_svg_icon("bolt" if active else "bot"))
    self.btn_agent.setText("")
    self.btn_agent.setStyleSheet(
        "background: rgba(6, 182, 212, 0.45); border: 1px solid #67E8F9; border-radius: 12px; padding: 4px 6px;"
        if active else ""
    )


PetControlBar.set_speech_on = _svg_set_speech_on
PetControlBar.set_mic_listening = _svg_set_mic_listening
PetControlBar.set_agent_active = _svg_set_agent_active


# Stop CompanionStage._on_tick from randomly switching to crazy expressions like API Crash / Angry!
def _calm_companion_on_tick(self) -> None:
    """Keep Cel's expression steady unless she is reacting to chat/voice or entering natural sleep."""
    return

CompanionStage._on_tick = _calm_companion_on_tick


def _pet_set_activity_state(self, state: str, text: str) -> None:
    _apply_svg_icons_and_hover_to_pet_window(getattr(self, "window", None))
    col = _PET_STATE_COLORS.get((state or "ready").lower(), "#C084FC")
    if hasattr(self, "window") and hasattr(self.window, "status_pill"):
        pill = self.window.status_pill
        pill.setStyleSheet(
            f"QLabel {{ background: rgba(14, 10, 28, 0.92); color: {col}; "
            f"border: 1.5px solid {col}; border-radius: 10px; "
            f"padding: 2px 8px; font-size: 11px; font-weight: bold; }}"
        )
        self.window.set_status_text(text)


def _pet_stream_say(self, text: str, is_final: bool = False, speaker: str = "Cel") -> None:
    _apply_svg_icons_and_hover_to_pet_window(getattr(self, "window", None))
    if not getattr(self, "_speak", True):
        return
    clean = (text or "").strip()
    if not clean:
        return
    prefix = f"{speaker}: " if speaker and not clean.startswith(f"{speaker}:") else ""
    body = prefix + clean
    if not is_final and len(body) > 170:
        disp = f"{speaker}: …" + clean[-155:].lstrip() + " ▎"
    elif not is_final:
        disp = body + " ▎"
    else:
        disp = body if len(body) <= 220 else (body[:217] + "…")

    hold = max(6000, min(16000, len(clean) * 65)) if is_final else 8500
    try:
        self.window.say(disp, msec=hold)
    except Exception:
        pass


CompanionStage.set_activity_state = _pet_set_activity_state
CompanionStage.stream_say = _pet_stream_say

# ══ WAVE_OMG_PARITY_START ══
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QWidget
from cellium.core.utils import ALL_76_EXPRESSIONS


class _DynamicPetHoverFilter(QObject):
    """Shows floating help box with live selected model/mic/voice/mood without moving layout."""
    def __init__(self, pet_win, btn_key: str, base_help: str):
        super().__init__(pet_win)
        self._win = pet_win
        self._key = btn_key
        self._base = base_help

    def _build_dynamic_text(self) -> str:
        mw = getattr(self._win, "_host_main_win", None)
        if mw is None:
            for top_w in QApplication.topLevelWidgets():
                if hasattr(top_w, "settings") and hasattr(top_w, "sessions"):
                    mw = top_w
                    self._win._host_main_win = mw
                    break
        settings = getattr(mw, "settings", {}) if mw is not None else {}
        if self._key == "btn_model":
            cur_m = settings.get("selected_model") or "Default Cloud Model"
            return f"AI Model \u2022 Active: {cur_m}"
        if self._key == "btn_mic":
            eng = settings.get("voice_stt_engine", "ggml Whisper (Local)")
            active = bool(getattr(mw, "_pet_voice_active", False)) if mw else False
            state_str = "LISTENING" if active else "MUTED"
            return f"Voice Mic ({state_str}) \u2022 Engine: {eng}"
        if self._key == "btn_voice":
            vh = settings.get("live_voice") or settings.get("voice_host", "Kokoro (Offline)")
            vid = settings.get("live_voice_id") or settings.get("tts_voice", "af_heart")
            return f"Speech Voice \u2022 {vh} ({vid})"
        if self._key == "btn_agent":
            ag = bool(getattr(mw, "agent_mode_enabled", False)) if mw else False
            return f"Agent Mode \u2022 {'ON (Autonomous Tools)' if ag else 'OFF (Standard Chat)'}"
        if self._key == "btn_speech":
            cbar = getattr(self._win, "control_bar", None)
            sp = bool(getattr(cbar, "_speech_on", True))
            return f"Speech Bubbles \u2022 {'ON (Showing Replies)' if sp else 'MUTED'}"
        if self._key == "btn_mood":
            expr = getattr(self._win.view, "_expr", None) if hasattr(self._win, "view") else None
            ename = getattr(expr, "name", "Happy") if expr else "Happy"
            egender = getattr(expr, "gender", "Female") if expr else "Female"
            return f"Emotion Picker \u2022 Current: {ename} ({egender})"
        if self._key == "btn_screen":
            atts = len(getattr(mw, "pending_attachments", []) or []) if mw else 0
            return f"Screen Snap \u2022 {atts} attached (click to snap & append)"
        return self._base

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (QEvent.Type.Enter, QEvent.Type.HoverEnter):
            if hasattr(self._win, "show_hover_help"):
                self._win.show_hover_help(self._build_dynamic_text())
        elif et in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            if hasattr(self._win, "hide_hover_help"):
                self._win.hide_hover_help()
        return False


# ═══ WAVE OMG PET PARITY BLOCK START ═══
import random as _pet_rng
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import (
    QLayout,
    QPushButton,
    QScrollArea,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
)

_PET_PLEASANT_FACES = (
    "Happy", "Kawaii", "Chibi Joy", "Excited", "Winking", "UwU",
    "Flirty", "Sparkle Hype", "Starstruck", "Feeling Cool", "Relieved",
)


# === WAVE_OMG_PARITY_START (PET_V3_CLEAN) ===
import random as _pet_rng
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtWidgets import QLayout, QPushButton, QWidget

_PET_PLEASANT_FACES = (
    "Happy", "Kawaii", "Chibi Joy", "Excited", "Winking", "UwU",
    "Flirty", "Sparkle Hype", "Starstruck", "Feeling Cool", "Relieved",
)

def _pet_pick_random_face(lib, gender: str) -> str:
    try:
        names = lib.names(gender) if lib is not None else []
        pleasant = [n for n in _PET_PLEASANT_FACES if n in names]
        pool = pleasant if pleasant else names
        if pool:
            return _pet_rng.choice(pool)
    except Exception:
        pass
    return "Happy"

def _detach_overlay_from_layout(parent_win: QWidget, child_widget: QWidget | None) -> None:
    if child_widget is None or parent_win is None:
        return
    try:
        for lay in parent_win.findChildren(QLayout):
            lay.removeWidget(child_widget)
    except Exception:
        pass
    try:
        child_widget.setParent(parent_win)
        child_widget.raise_()
    except Exception:
        pass

def _reposition_pet_overlays(pet_win) -> None:
    if pet_win is None:
        return
    w = pet_win.width()
    pill = getattr(pet_win, 'hover_help_pill', None)
    if pill is not None:
        pill.adjustSize()
        pw = min(max(pill.sizeHint().width() + 16, 160), max(w - 16, 160))
        ph = max(pill.sizeHint().height(), 26)
        pill.setFixedSize(pw, ph)
        pill.move(max(8, (w - pw) // 2), 6)
        pill.raise_()
    badge = getattr(pet_win, 'attach_badge_pill', None)
    if badge is not None and badge.isVisible():
        badge.adjustSize()
        bw = max(badge.sizeHint().width() + 12, 110)
        bh = 24
        badge.setFixedSize(bw, bh)
        av = getattr(pet_win, 'avatar', None)
        ay = av.y() if av is not None else 40
        badge.move(max(8, (w - bw) // 2), max(34, ay + 6))
        badge.raise_()

def _upgrade_pet_window_v2(pet_win) -> None:
    if pet_win is None or getattr(pet_win, '_omg_v2_upgraded', False):
        return
    pet_win._omg_v2_upgraded = True
    _detach_overlay_from_layout(pet_win, getattr(pet_win, 'hover_help_pill', None))
    if not hasattr(pet_win, 'attach_badge_pill') or pet_win.attach_badge_pill is None:
        badge = QPushButton('', pet_win)
        badge.setCursor(Qt.CursorShape.PointingHandCursor)
        badge.setStyleSheet(
            "QPushButton { background: rgba(15, 23, 42, 225); color: #A7F3D0; "
            "border: 1px solid rgba(52, 211, 153, 180); border-radius: 12px; "
            "padding: 2px 10px; font-size: 11px; font-weight: 600; } "
            "QPushButton:hover { background: rgba(220, 38, 38, 210); color: #FFFFFF; }"
        )
        badge.hide()
        pet_win.attach_badge_pill = badge
    def _set_pet_attachment_count(count: int, label: str = '') -> None:
        b = getattr(pet_win, 'attach_badge_pill', None)
        if b is None:
            return
        if count <= 0:
            b.hide()
        else:
            txt = label if label else f'\U0001f4ce {count} attached \u00b7 click to clear'
            b.setText(txt)
            b.show()
            _reposition_pet_overlays(pet_win)
    pet_win.set_attachment_count = _set_pet_attachment_count
    _reposition_pet_overlays(pet_win)

if 'PetWindow' in globals():
    _orig_pw_resize_omg = getattr(PetWindow, 'resizeEvent', None)
    def _patched_pw_resize_omg(self, event):
        if _orig_pw_resize_omg is not None:
            _orig_pw_resize_omg(self, event)
        _reposition_pet_overlays(self)
    PetWindow.resizeEvent = _patched_pw_resize_omg

if 'CompanionStage' in globals():
    _orig_comp_init_omg = CompanionStage.__init__
    _orig_comp_set_gender_omg = getattr(CompanionStage, 'set_gender', None)

    def _patched_comp_init_omg(self, *args, **kwargs):
        _orig_comp_init_omg(self, *args, **kwargs)
        try:
            if hasattr(self, 'window') and self.window is not None:
                _upgrade_pet_window_v2(self.window)
                pick = _pet_pick_random_face(getattr(self, 'library', None), getattr(self, 'gender', 'Female'))
                self._current_expr = pick
                if hasattr(self.window, 'set_expression'):
                    self.window.set_expression(pick)
        except Exception:
            pass

    def _patched_comp_set_gender_omg(self, gender: str) -> None:
        if _orig_comp_set_gender_omg is not None:
            _orig_comp_set_gender_omg(self, gender)
        try:
            pick = _pet_pick_random_face(getattr(self, 'library', None), gender)
            self._current_expr = pick
            if hasattr(self, 'window') and self.window is not None and hasattr(self.window, 'set_expression'):
                self.window.set_expression(pick)
        except Exception:
            pass

    CompanionStage.__init__ = _patched_comp_init_omg
    CompanionStage.set_gender = _patched_comp_set_gender_omg
# === WAVE_OMG_PARITY_END (PET_V3_CLEAN) ===
