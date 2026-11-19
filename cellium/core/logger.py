_LOG_LISTENERS = []
from collections import deque as _deque

_LOG_BUFFER = _deque(maxlen=2000)
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

LOG_FILE = Path(__file__).resolve().parent / "celstudio_app.log"
def register_log_listener(callback):
    _LOG_LISTENERS.append(callback)

def log_to_file(msg: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {msg}\n")
    except Exception:
        pass


#: ``verbose_logging`` (Settings -> Advanced). The console print and the in-app
#: log viewer always run - they are how you diagnose a live problem - but the
#: on-disk file only grows while this is on, because it otherwise rewrites
#: itself on every keystroke-level message for the whole session.
_VERBOSE = True


def set_verbose(on: bool) -> None:
    """Turn on-disk dev logging on/off."""
    global _VERBOSE
    _VERBOSE = bool(on)


def is_verbose() -> bool:
    return _VERBOSE


def dev_log(msg: str):
    """Centralized dev logging - prints to console AND file AND in-app listeners"""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    formatted = f"[DEV][{ts}] {msg}"
    try:
        _LOG_BUFFER.append(formatted)
    except Exception:
        pass
    print(formatted)
    if _VERBOSE:
        log_to_file(formatted)
    for listener in list(_LOG_LISTENERS):
        try:
            listener(formatted)
        except Exception:
            pass

def get_recent_logs():
    """Snapshot of the in-RAM log ring buffer (oldest first)."""
    return list(_LOG_BUFFER)

def clear_log_buffer():
    _LOG_BUFFER.clear()

_original_excepthook = sys.excepthook
def _cel_excepthook(exc_type, exc_value, exc_tb):
    try:
        dev_log(f"[UNCAUGHT] {exc_type.__name__}: {exc_value}")
    except Exception:
        pass
    _original_excepthook(exc_type, exc_value, exc_tb)
sys.excepthook = _cel_excepthook

# ------------------------------------------------------------------ PySide6 (Headless Safe)
try:
    from PySide6.QtCore import (Qt, QTimer, QPoint, QPointF, QRect, QRectF, QSize,
                                 Signal, QObject, QThread, QPropertyAnimation,
                                 QEasingCurve, Property, QParallelAnimationGroup, QUrl)
    from PySide6.QtGui import (QGuiApplication, QTextDocument, QColor, QPainter, QBrush, QPen, QFont, QFontDatabase,
                              QPainterPath, QIcon, QPixmap, QImage, QLinearGradient,
                              QRadialGradient, QAction, QKeySequence, QShortcut, QTextCursor)
    from PySide6.QtWidgets import (QMenu, QApplication, QMainWindow, QWidget, QVBoxLayout,
                                  QHBoxLayout, QStackedWidget, QLabel, QPushButton,
                                  QLineEdit, QTextEdit, QComboBox, QCheckBox, QSlider,
                                  QScrollArea, QFrame, QFileDialog, QSizePolicy,
                                  QGraphicsOpacityEffect, QGridLayout, QTabBar, QCompleter,
                                  QTextBrowser)
    from PySide6.QtCore import QStringListModel
except ImportError:
    # Safe fallbacks for headless CLI execution
    Qt = None
    QColor = lambda *a, **k: None

# ------------------------------------------------------------------ Speech & Audio Dependencies
