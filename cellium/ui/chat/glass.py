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
from cellium.core.logger import *
from cellium.core.config import *
from cellium.core.utils import *
from cellium.core.tools import *
from cellium.services.sound_engine import *
from cellium.services.ai_llama import *
from cellium.services.audio_stt import *
from cellium.services.audio_tts import *
from cellium.services.ai_workers import *

#: Fallback frost radius used when a panel is built before settings are read.
DEFAULT_GLASS_BLUR = 16


class GlassPanel(QFrame):
    def __init__(self, radius=18, parent=None, panel_opacity=None, blur=None):
        super().__init__(parent)
        self.radius = radius
        self.panel_opacity = panel_opacity if panel_opacity is not None else 0.88
        self.blur_radius = DEFAULT_GLASS_BLUR if blur is None else int(max(0, blur))
        self._backdrop = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("GlassPanel { background: transparent; border: none; }")

    def set_blur(self, radius):
        """Apply the persisted ``glass_blur`` radius (0-64 px)."""
        try:
            r = int(max(0, min(64, radius)))
        except (TypeError, ValueError):
            r = DEFAULT_GLASS_BLUR
        if r != self.blur_radius:
            self.blur_radius = r
            self.update()

    def _resolve_backdrop(self):
        """Find the wallpaper widget this panel should frost over."""
        if self._backdrop is not None:
            return self._backdrop
        win = self.window()
        if win is None:
            return None
        for child in win.findChildren(QWidget):
            if hasattr(child, "frost_pixmap"):
                self._backdrop = child
                return child
        return None

    @Property(int)
    def drawer_width(self):
        return self.width()

    @drawer_width.setter
    def drawer_width(self, w):
        self.setFixedWidth(w)

    def set_panel_opacity(self, opacity):
        self.panel_opacity = max(0.0, min(1.0, opacity))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        
        # Backdrop frost. Qt has no backdrop-filter, so sample the wallpaper
        # widget's blurred render and clip it to this panel's rounded rect.
        if self.blur_radius > 0 and self.panel_opacity > 0.15:
            backdrop = self._resolve_backdrop()
            if backdrop is not None:
                shot = backdrop.frost_pixmap(self.blur_radius)
                if shot is not None and not shot.isNull():
                    # mapFromGlobal, not mapTo: toasts are siblings of the
                    # wallpaper (both children of the main window), and mapTo
                    # warns whenever the target is not a strict ancestor.
                    pos = self.mapFromGlobal(backdrop.mapToGlobal(QPoint(0, 0)))
                    sx = shot.width() / max(1, backdrop.width())
                    sy = shot.height() / max(1, backdrop.height())
                    clip = QPainterPath()
                    clip.addRoundedRect(QRectF(r), self.radius, self.radius)
                    src = QRectF(
                        pos.x() * sx, pos.y() * sy,
                        max(1.0, self.width() * sx),
                        max(1.0, self.height() * sy),
                    )
                    painter.save()
                    painter.setClipPath(clip)
                    painter.drawPixmap(QRectF(self.rect()), shot, src)
                    painter.restore()

        # Backup-style glass: black base (14, 11, 24) + purple border (168, 85, 247)
        # Scaled by panel_opacity. Frost and fill trade off instead of
        # stacking, so cranking the blur does not turn panels into tar.
        if self.panel_opacity <= 0.15:
            # Just outline - no fill
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen_color = QColor(168, 85, 247, int(50 * self.panel_opacity * 3))
            painter.setPen(QPen(pen_color, 1.5))
            painter.drawRoundedRect(r, self.radius, self.radius)
        else:
            # Solid glass with opacity scaling
            frost_relief = min(90, int(self.blur_radius * 1.4))
            bg_alpha = int(max(70, 210 - frost_relief) * self.panel_opacity)
            border_alpha = int((50 + min(45, self.blur_radius)) * self.panel_opacity)
            bg = QColor(14, 11, 24, bg_alpha)
            border = QColor(168, 85, 247, border_alpha)
            
            painter.setBrush(QBrush(bg))
            painter.setPen(QPen(border, 1.2))
            painter.drawRoundedRect(r, self.radius, self.radius)

# ------------------------------------------------------------------ Multi-Kaomoji Animated Face Orb
class GlassToast(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(radius=14, parent=parent)
        self.setFixedHeight(46)
        self.setVisible(False)
        self.layout_h = QHBoxLayout(self)
        self.layout_h.setContentsMargins(14, 6, 14, 6)
        self.layout_h.setSpacing(8)

        self.lbl_icon = QLabel("✨")
        self.lbl_icon.setStyleSheet("font-size: 16px; border: none; background: transparent;")
        self.lbl_msg = QLabel("Message")
        self.lbl_msg.setStyleSheet("color: #F8F4FF; font-size: 12px; font-weight: bold; border: none; background: transparent;")
        self.layout_h.addWidget(self.lbl_icon)
        self.layout_h.addWidget(self.lbl_msg)
        self.timer_hide = QTimer(self)
        self.timer_hide.setSingleShot(True)
        self.timer_hide.timeout.connect(lambda: self.setVisible(False))
        self.mousePressEvent = lambda e: self.hide()  # wave10: pc click dismiss


    def show_toast(self, message, icon="✨", duration_ms=2800):
        self.lbl_icon.setText(icon)
        self.lbl_msg.setText(message)
        self.adjustSize()
        if self.parent():
            pw, ph = self.parent().width(), self.parent().height()
            self.move(int((pw - self.width()) / 2), ph - 90)
        self.setVisible(True)
        self.raise_()
        self.timer_hide.start(duration_ms)

# ------------------------------------------------------------------ Inbuilt View 1: Model Hub

class ChatInputEdit(QTextEdit):
    returnPressed = Signal()
    filePasted = Signal()
    historyUp = Signal()
    historyDown = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.setMinimumWidth(100)
        self.history = []
        self.history_index = -1
        self.current_draft = ""
        self.document().documentLayout().documentSizeChanged.connect(self.auto_resize)

    def text(self) -> str:
        return self.toPlainText()

    def clear(self):
        self.setPlainText("")
        self.auto_resize()
        parent = self.parent()
        if parent:
            parent.setFixedHeight(58)

    def auto_resize(self, *args):
        doc_h = int(math.ceil(self.document().size().height()))
        new_h = max(38, min(140, doc_h + 12))
        self.setFixedHeight(new_h)
        # Also resize parent input pill to accommodate growing text
        parent = self.parent()
        if parent:
            parent.setFixedHeight(new_h + 20)

    def add_history(self, text: str):
        if text.strip() and (not self.history or self.history[-1] != text.strip()):
            self.history.append(text.strip())
        self.history_index = -1
        self.current_draft = ""

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()

        # Enter to send (without Shift)
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (mods & Qt.KeyboardModifier.ShiftModifier):
            self.returnPressed.emit()
            return

        # Bare PageUp/PageDown - smoothly scroll the active chat / view!
        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) and not (mods & Qt.KeyboardModifier.ShiftModifier):
            mw = self.window()
            if mw is not None and hasattr(mw, "page_scroll_active_view"):
                mw.page_scroll_active_view(up=(key == Qt.Key.Key_PageUp))
                event.accept()
                return

        # Shift+PageUp/PageDown - browse full input history (unsent draft preserved)
        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) and (mods & Qt.KeyboardModifier.ShiftModifier):
            enabled = True
            try:
                mw = self.window()
                if mw is not None and hasattr(mw, "settings"):
                    enabled = bool(mw.settings.get("history_shift_nav", True))
            except Exception:
                enabled = True
            if enabled:
                self._nav_history(1 if key == Qt.Key.Key_PageUp else -1)
                return

        # Up/Down for history navigation only at first/last line
        elif key == Qt.Key.Key_Up:
            cursor = self.textCursor()
            if cursor.blockNumber() == 0 and cursor.positionInBlock() == 0:
                self._nav_history(1)
                return
        elif key == Qt.Key.Key_Down:
            cursor = self.textCursor()
            if cursor.blockNumber() == self.document().blockCount() - 1 and cursor.positionInBlock() == len(cursor.block().text()):
                self._nav_history(-1)
                return

        # Play animalese typing sound for user input (moved from Cel's voice)
        if key not in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
                       Qt.Key.Key_CapsLock, Qt.Key.Key_Escape, Qt.Key.Key_Tab,
                       Qt.Key.Key_Backspace, Qt.Key.Key_Delete, Qt.Key.Key_Home,
                       Qt.Key.Key_End, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
                       Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            # Only play for actual character input
            if event.text() and len(event.text()) == 1:
                main_win = self.window()
                if main_win and hasattr(main_win, "play_user_typing_sound"):
                    # The *user's* channel. Cel's typing-voice setting used to
                    # decide what your own keyboard sounded like, so the two
                    # could never be different.
                    try:
                        main_win.play_user_typing_sound(event.text())
                    except Exception:
                        pass

        # Explicitly allow standard navigation keys to pass through to QTextEdit
        # This ensures Ctrl+Left/Right, Home, End, Ctrl+Home/End, etc. work
        super().keyPressEvent(event)

    def _nav_history(self, direction: int):
        if not self.history:
            return
        if self.history_index == -1 and direction == 1:
            # Capture unsent draft (may contain text user is still typing)
            self.current_draft = self.toPlainText()
            self.history_index = len(self.history) - 1
            self.setPlainText(self.history[self.history_index])
        elif self.history_index != -1:
            new_idx = self.history_index - direction
            if 0 <= new_idx < len(self.history):
                self.history_index = new_idx
                self.setPlainText(self.history[self.history_index])
            elif new_idx >= len(self.history):
                self.history_index = -1
                self.setPlainText(self.current_draft)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasImage() or mime.hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasImage() or mime.hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls():
            event.acceptProposedAction()
            local_paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            if local_paths:
                mw = self.window()
                if mw and hasattr(mw, "attach_files_from_urls"):
                    mw.attach_files_from_urls(local_paths)
                    return
        super().dropEvent(event)

    def insertFromMimeData(self, source):
        if source.hasUrls():
            local_paths = [u.toLocalFile() for u in source.urls() if u.isLocalFile()]
            if local_paths:
                mw = self.window()
                if mw and hasattr(mw, "attach_files_from_urls"):
                    mw.attach_files_from_urls(local_paths)
                    return
        if source.hasImage() or (source.hasText() and len(source.text()) > 1200):
            self.filePasted.emit()
        else:
            super().insertFromMimeData(source)
