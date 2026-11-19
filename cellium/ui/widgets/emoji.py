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
from cellium.ui.chat.glass import *
from cellium.core.logger import *
from cellium.core.config import *
from cellium.core.utils import *
from cellium.core.tools import *
from cellium.services.sound_engine import *
from cellium.services.ai_llama import *
from cellium.services.audio_stt import *
from cellium.services.audio_tts import *
from cellium.services.ai_workers import *
from PySide6.QtCore import QTimer  # wave12

class AnimatedFaceOrb(QWidget):
    def __init__(self, size=112, theme_accent=QColor(138, 43, 226), parent=None):
        super().__init__(parent)
        # Blinking disabled for the home-circle face (Task 11): it uses a
        # separate static texture instead of the blink animation.
        self._wave12_blink = None
        self.setFixedSize(size, size)
        self.orb_size = size
        self.theme_accent = theme_accent
        self.hovered = False

        self.float_offset = 0.0
        self.float_direction = 1
        self.pulse_phase = 0.0
        self.blink_state = 0.0
        self.is_blinking = False

        # Curated Kaomojis with NO awkward spacing gaps between eyes & mouth!
        self.kaomoji_list = [
            "(◕‿◕)", "(>‿<)", "(˶˃ᆺ˂˶)", "≽^•⩊•^≼", "(｡♥‿♥｡)", "(๑>ᴗ<๑)", "(✿◠‿◠)", "(ᗜ⩊ᗜ)", "( ˘ ³˘)♥"
        ]
        self.active_kao_idx = 0

        self.timer_physics = QTimer(self)
        self.timer_physics.timeout.connect(self.update_physics)
        self.timer_physics.start(33)

        # Blinking disabled (Task 11) - home circle uses a separate texture.
        self.timer_blink = None

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click me to switch expression! 💕✨")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._physics_active = False

    def mousePressEvent(self, event):
        """Click to cycle expressions (Multi-Kaomoji System) with satisfying pop!"""
        self.active_kao_idx = (self.active_kao_idx + 1) % len(self.kaomoji_list)
        play_ui_sound("pop", 0.8)
        self.float_offset = -10.0
        self.pulse_phase += 2.2
        self.update()

    def set_accent(self, color):
        self.theme_accent = color
        self.update()

    def enterEvent(self, event):
        self.hovered = True
        self.update()

    def leaveEvent(self, event):
        self.hovered = False
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._physics_active = True
        if hasattr(self, "timer_physics") and self.timer_physics is not None:
            self.timer_physics.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._physics_active = False
        if hasattr(self, "timer_physics") and self.timer_physics is not None:
            self.timer_physics.stop()

    def trigger_blink(self):
        if not self.is_blinking:
            self.is_blinking = True
            self.blink_state = 0.0

    def update_physics(self):
        self.float_offset += 0.16 * self.float_direction
        if abs(self.float_offset) > 3.5:
            self.float_direction *= -1

        self.pulse_phase = (self.pulse_phase + 0.045) % (2 * math.pi)

        if self.is_blinking:
            self.blink_state += 0.22
            if self.blink_state >= 1.0:
                self.is_blinking = False
                self.blink_state = 0.0

        if not self._physics_active:
            return
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, (h / 2.0) + self.float_offset
        base_radius = (self.orb_size / 2.0) - 10

        if getattr(self, "hovered", False):
            glow_intensity = 0.88 + 0.12 * math.sin(self.pulse_phase)
        else:
            glow_intensity = 0.5 + 0.5 * math.sin(self.pulse_phase)
        glow_radius = base_radius + 8 + (glow_intensity * 6)
        glow_grad = QRadialGradient(cx, cy, glow_radius)
        accent = self.theme_accent
        glow_grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), int(140 * glow_intensity)))
        glow_grad.setColorAt(0.7, QColor(accent.red(), accent.green(), accent.blue(), int(45 * glow_intensity)))
        glow_grad.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        painter.setBrush(QBrush(glow_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), glow_radius, glow_radius)

        orb_grad = QRadialGradient(cx - base_radius * 0.35, cy - base_radius * 0.35, base_radius * 1.3)
        bright_col = accent.lighter(170)
        dark_col = accent.darker(240)
        orb_grad.setColorAt(0.0, bright_col)
        orb_grad.setColorAt(0.45, accent)
        orb_grad.setColorAt(1.0, dark_col)
        painter.setBrush(QBrush(orb_grad))
        painter.setPen(QPen(QColor(255, 255, 255, 110), 1.4))
        painter.drawEllipse(QPointF(cx, cy), base_radius, base_radius)

        highlight_grad = QLinearGradient(cx - base_radius * 0.6, cy - base_radius * 0.8,
                                         cx + base_radius * 0.4, cy)
        highlight_grad.setColorAt(0.0, QColor(255, 255, 255, 170))
        highlight_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(highlight_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx - base_radius * 0.25, cy - base_radius * 0.35),
                            base_radius * 0.55, base_radius * 0.35)

        painter.setPen(QColor(255, 255, 255, 245))
        font = QFont("Segoe UI Emoji", 14, QFont.Weight.Bold)
        painter.setFont(font)

        if self.is_blinking:
            active_text = "(-‿-)"
        else:
            active_text = self.kaomoji_list[self.active_kao_idx]

        text_rect = QRectF(cx - base_radius, cy - 14, base_radius * 2, 32)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, active_text)

# ------------------------------------------------------------------ Message Bubble Widget (Zero Truncation Bug)



    def _wave12_blink_tick(self):  # wave12: kaomoji eye blink
        try:
            txt = self._wave12_cur()
            closed = txt
            for ch in "•◕●○ᵔ≧⊙":
                closed = closed.replace(ch, "-")
            if closed == txt:
                return
            self._wave12_set(closed)
            QTimer.singleShot(140, lambda: self._wave12_set(txt))
        except Exception:
            pass

    def _wave12_cur(self):  # wave12: kaomoji eye blink
        if callable(getattr(self, "text", None)):
            try:
                return self.text()
            except Exception:
                pass
        l = getattr(self, "label", None) or getattr(self, "lbl", None)
        if l is not None:
            return l.text()
        return getattr(self, "current_kaomoji", "") or ""

    def _wave12_set(self, t):  # wave12: kaomoji eye blink
        if callable(getattr(self, "setText", None)):
            self.setText(t)
            return
        l = getattr(self, "label", None) or getattr(self, "lbl", None)
        if l is not None:
            l.setText(t)

# ══ WAVE_OMG_PARITY_START ══
# PC #7: Per-Kaomoji Eye-Specific Blinking Variant Engine
_KAOMOJI_BLINK_MAP = {
    "(\u02f6\u02c3\u0d25\u02c2\u02f6)": "(\u02f6-\u0d25-\u02f6)",
    "(\uff61\u2665\u203f\u2665\uff61)": "(\uff61-\u203f-\uff61)",
    "(\u25d5\u203f\u25d5\u273f)": "(-\u203f-\u273f)",
    "(\u3063\u02d8\u03c9\u02d8\u03c2)": "(\u3063-\u03c9-\u03c2)",
    "(\u2267\u25e1\u2266)": "(-\u25e1-)",
    "(\u00b4\uff65\u03c9\uff65`)": "(\u00b4-\u03c9-`)",
    "(\u2727\u03c9\u2727)": "(-\u03c9-)",
    "(\u02f6\u2022\u0301\u1d25\u2022\u0300\u02f6)\u2727": "(\u02f6-\u1d25-\u02f6)\u2727",
}

_OPEN_EYE_GLYPHS = re.compile(r"[\u25d5\u2665\u2727\u2022\uff65\u02c3\u02c2\u2267\u2266\u02d8\u25c9\u25cf\u00b0\u00f2\u00f3\u00ac\u0ca0\u2310\u25a0\u005e]")


def make_kaomoji_blink_variant(face: str) -> str:
    if not face:
        return "(-\u203f-)"
    if face in _KAOMOJI_BLINK_MAP:
        return _KAOMOJI_BLINK_MAP[face]
    # Replace open eye characters with closed '-' while preserving brackets, blush, and mouth
    converted = _OPEN_EYE_GLYPHS.sub("-", face)
    converted = re.sub(r"-\s*[\u0300\u0301]", "-", converted)
    converted = re.sub(r"--+", "-", converted)
    if converted == face:
        # Fallback if face had ASCII eyes like :3 or >_<
        converted = face.replace(">", "-").replace("<", "-").replace(":", ";")
    return converted


if "AnimatedFaceOrb" in globals():
    _orig_orb_init_omg = AnimatedFaceOrb.__init__

    def _patched_orb_init_omg(self, *args, **kwargs):
        _orig_orb_init_omg(self, *args, **kwargs)
        # Override any blink method or timer to blink the CURRENT kaomoji's eyes
        if hasattr(self, "_do_blink") or hasattr(self, "blink"):
            pass

    def _orb_blink_current_kaomoji(self) -> None:
        cur_face = getattr(self, "current_face", None) or (
            self.faces[getattr(self, "face_idx", 0) % len(self.faces)]
            if hasattr(self, "faces") and self.faces else "(\u25d5\u203f\u25d5\u273f)"
        )
        blink_face = make_kaomoji_blink_variant(cur_face)
        self._display_face_override = blink_face
        if hasattr(self, "lbl") and self.lbl is not None:
            self.lbl.setText(blink_face)
        self.update()

        def _restore():
            self._display_face_override = None
            latest = getattr(self, "current_face", None) or (
                self.faces[getattr(self, "face_idx", 0) % len(self.faces)]
                if hasattr(self, "faces") and self.faces else cur_face
            )
            if hasattr(self, "lbl") and self.lbl is not None:
                self.lbl.setText(latest)
            self.update()

        QTimer.singleShot(160, _restore)

    for _mname in ("_blink", "blink", "_trigger_blink", "_on_blink"):
        if hasattr(AnimatedFaceOrb, _mname):
            setattr(AnimatedFaceOrb, _mname, _orb_blink_current_kaomoji)
# ══ WAVE_OMG_PARITY_END ══
