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

class WallpaperWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.orig_pixmap = None
        self._scaled_cache = None
        self._cache_size = None
        self.accent_color = THEME_COLORS["Server 1"]["accent"]
        self.tint_alpha = 0.55
        self.panel_opacity = 0.88
        self._frost_cache = {}
        self.load_wallpaper()

    def load_wallpaper(self):
        if WALLPAPER_FILE.exists():
            self.orig_pixmap = QPixmap(str(WALLPAPER_FILE))
            dev_log(f"Wallpaper loaded from {WALLPAPER_FILE}")

    def set_theme_and_tint(self, server_name, tint_alpha, panel_opacity=None):
        self.active_server = server_name
        theme = THEME_COLORS.get(server_name, THEME_COLORS["Server 1"])
        self.accent_color = theme["accent"]
        self.tint_alpha = max(0.05, min(0.95, tint_alpha))
        if panel_opacity is not None:
            self.panel_opacity = max(0.0, min(1.0, panel_opacity))
        self._frost_cache = {}
        self.update()

    def resizeEvent(self, event):
        self._frost_cache = {}
        self._scaled_cache = None
        self._cache_size = None
        super().resizeEvent(event)
        # Build the scaled cache after the base resize completes
        if self.orig_pixmap and not self.orig_pixmap.isNull():
            w, h = self.width(), self.height()
            if w >= 8 and h >= 8:
                scaled = self.orig_pixmap.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation
                )
                self._scaled_cache = scaled
                self._cache_size = (w, h)

    def frost_pixmap(self, blur: int = 0):
        """Render the wallpaper through a Gaussian blur, cached per radius.

        Qt has no CSS ``backdrop-filter``, so glass panels sample this and clip
        the result to their own rounded rect. The old implementation was a
        downscale/upscale box trick - blocky at 64 px, invisible at 4 - and
        cleared its 8-entry cache on every slider tick, which is exactly what
        made the wallpaper look *permanently blurred* while dragging Glass
        Blur. This one runs Pillow's real GaussianBlur and quantizes the key
        to 4 px steps (≤17 variants, 24-entry LRU), so ticks hit warm
        entries. Returns ``None`` when there is no wallpaper, which makes
        callers fall back to plain glass.
        """
        if self.orig_pixmap is None or self.orig_pixmap.isNull():
            return None
        if self.width() < 8 or self.height() < 8:
            return None
        key = int(max(0, min(64, blur)))
        if key > 0:
            key = min(64, ((key + 2) // 4) * 4)   # 0, 4, 8 … 64
        cache = getattr(self, "_frost_cache", None)
        if cache is None:
            cache = self._frost_cache = {}
        hit = cache.get(key)
        if hit is not None:
            # Re-insert as most-recent (dicts keep insertion order = LRU).
            cache.pop(key, None)
            cache[key] = hit
            return hit
        shot = QPixmap(self.size())
        p = QPainter(shot)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_backdrop(p)
        p.end()
        if key > 0:
            shot = self._gaussian_frost(shot, key)
        cache[key] = shot
        while len(cache) > 24:
            cache.pop(next(iter(cache)), None)
        return shot

    @staticmethod
    def _gaussian_frost(shot, radius: int):
        """Pillow GaussianBlur via a bytes round-trip (QImage has no blur)."""
        try:
            from PIL import Image, ImageFilter
            from PySide6.QtGui import QImage
            img = shot.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            w, h = img.width(), img.height()
            if w < 4 or h < 4:
                return shot
            stride = img.bytesPerLine()
            arr = np.frombuffer(bytes(img.constBits()), dtype=np.uint8)
            arr = arr.reshape(h, stride)[:, :w * 4].reshape(h, w, 4)
            pil = Image.fromarray(np.ascontiguousarray(arr), "RGBA")
            pil = pil.filter(ImageFilter.GaussianBlur(radius=radius * 0.5))
            out = QImage(pil.tobytes(), w, h, w * 4,
                         QImage.Format.Format_RGBA8888).copy()
            return QPixmap.fromImage(out)
        except Exception:
            return shot  # never break the frost - fall back to sharp

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_backdrop(painter)
        painter.end()

    def _paint_backdrop(self, painter):
        """Draw the wallpaper layers only - never children.

        frost_pixmap() calls this instead of QWidget.render(): render() also
        paints the child widgets layered on top of this one, i.e. every
        GlassPanel, and each of those asks for a frost snapshot while it is
        being produced. That recursed until the stack died.
        """
        w, h = self.width(), self.height()
        
        # ALWAYS fill opaque background first to prevent Win95 duplicate draw trails!
        painter.fillRect(0, 0, w, h, QColor(11, 9, 20))
        
        # 1. Draw the user's beautiful wallpaper! Use cached scaled version.
        if self.orig_pixmap and not self.orig_pixmap.isNull():
            if self._scaled_cache is not None:
                scaled = self._scaled_cache
                sx = int((scaled.width() - w) / 2)
                sy = int((scaled.height() - h) / 2)
                painter.drawPixmap(0, 0, scaled, sx, sy, w, h)
            else:
                painter.fillRect(0, 0, w, h, QColor(11, 9, 20))
        else:
            painter.fillRect(0, 0, w, h, QColor(11, 9, 20))
        
        # Dynamic color change removed per user instruction - Cel Cellium Wallpaper displays its natural colors!
        
        # 3. Black darkness overlay (not purple!) - driven by the tint slider
        # ONLY. It used to also multiply by panel_opacity, which made "Panel
        # Transparency" permanently murk the wallpaper behind every panel.
        darkness = QColor(10, 8, 18,
                          int(max(0.0, min(1.0, self.tint_alpha)) * 255))
        painter.fillRect(0, 0, w, h, darkness)


# --------------------------------------------------------------------------- #
# Kokoro Stream Engine (Physical cores + sentence chunking + raw PCM pipe)
# --------------------------------------------------------------------------- #
# Mute ONNX Runtime logger at import time to prevent constant_folding warnings per session
try:
    import onnxruntime as _ort_init
    _ort_init.set_default_logger_severity(3)
except Exception:
    pass
