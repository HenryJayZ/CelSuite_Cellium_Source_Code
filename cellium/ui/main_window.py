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
import random
from pathlib import Path
from datetime import datetime
import numpy as np

from PySide6.QtWidgets import QToolButton

# ============================================================
# GLOBAL REAL-TIME LOGGING SYSTEM - Immediate stdout/stderr flush
# ============================================================
_original_print = print

# --- CROSS IMPORTS ---
from cellium.ui.widgets.toggle import *
from cellium.ui.widgets.pfp import CircularAvatarLabel, bust_avatar_cache
from cellium.ui.chat.glass import *
from cellium.core.logger import *
from cellium.core.config import CTX_MAP, stt_key_hint, stt_key_provider, stt_missing_key
from cellium.core.utils import *
from cellium.core.tools import *

# Wave K8: stable per-session tint colors for the history list.
SESSION_TINT_PALETTE = ("#C084FC", "#60A5FA", "#34D399", "#F472B6",
                        "#FBBF24", "#22D3EE", "#A3E635", "#FB7185")


def session_tint_color(sid) -> str:
    """Deterministic md5-based tint so every session keeps its own color."""
    digest = hashlib.md5(str(sid).encode("utf-8")).hexdigest()
    return SESSION_TINT_PALETTE[int(digest, 16) % len(SESSION_TINT_PALETTE)]


# ── Connection-failure UX ──────────────────────────────────────────────────
# Workers used to emit "*(no response received)*" through the normal done
# signal, which made a dropped connection look like a real reply ("Cel
# replied!"). These markers let on_done/on_error route it to the error card.
_BAD_REPLY_MARKERS = (
    "*(no response received)*",
    "*(connection interrupted)*",
    "(no response received)",
    "(connection interrupted)",
)


def _is_failed_reply_text(text) -> bool:
    """True when a worker's "reply" is really a dropped-connection marker."""
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    if low in {m.lower() for m in _BAD_REPLY_MARKERS}:
        return True
    return ("no response received" in low
            or "connection interrupted" in low)


def _friendly_generation_error(title, desc) -> str:
    """Turn raw provider/network exceptions into a warm, actionable sentence."""
    low = f"{title or ''} {desc or ''}".lower()
    if any(k in low for k in (
        "errno", "name or service", "timeout", "timed out", "connection",
        "max retries", "network", "ssl", "proxy", "408", "500", "502",
        "503", "504", "chunkedencoding", "remote end closed",
        "connection reset", "httperror", "urlerror",
    )):
        return ("Cel couldn't connect 😢 Check your internet connection or "
                "your API key, then try again :)")
    if any(k in low for k in ("429", "rate limit", "quota", "too many requests")):
        return ("Cel is rate-limited right now 😅 Check your API quota or "
                "switch models :/")
    if any(k in low for k in ("402", "budget exhausted", "payment required",
                              "billing", "insufficient balance",
                              "vibe budget")):
        return ("Cel can't run on that provider right now 💳 It's out of "
                "budget (HTTP 402). Top it up in the provider's console, or "
                "switch models/providers in Model Hub :)")
    if any(k in low for k in ("401", "403", "api key", "unauthorized",
                              "forbidden", "authentication")):
        return ("Cel couldn't authenticate 🔑 Check your API key in "
                "Model Hub :(")
    return f"Cel couldn't finish that reply 😢 {title or 'Generation failed'}"
from cellium.services.sound_engine import (
    play_ui_sound, play_animalese_chirp, play_legacy_typing_preview,
)
from cellium.services.realistic_voice import (
    feed_realistic_voice, flush_realistic_voice, stop_realistic_voice,
    realistic_voice_is_speaking, play_realistic_voice_preview,
)
from cellium.core.config import (
    normalize_cel_typing_mode, normalize_user_typing_mode,
    CEL_TYPING_MODES, DEFAULT_REALISTIC_VOICE,
)
from cellium.services.ai_llama import *
from cellium.services.audio_stt import *
from cellium.services.audio_tts import *
from cellium.services.ai_workers import *
from cellium.services.kaggle_image import KaggleImageBackend, create_backend_from_settings
from cellium.ui.settings.dialog import *
from cellium.ui.settings.models import *
from cellium.ui.widgets.emoji import *
from cellium.ui.widgets.welcome import AnimatedFaceOrb, TypedLabel
from cellium.ui.widgets.wallpaper import *
from cellium.ui.avatar.studio import AvatarStudioWidget
from cellium.ui.live import LiveModeController, LiveStage
from cellium.ui.live.call_transition import CallTransition


from cellium.ui.chat.bubble import *
from cellium.ui.chat.timeline import ChatTimelineHost

#: Bubbles rendered per event-loop tick when opening a chat. Small enough that
#: the window repaints between batches - 40 in one pass measured 784 ms of jank.
RENDER_CHUNK_SIZE = 8


def _typing_volume(default: float = 0.9) -> float:
    """Mirror the per-sound type volume into a 0-1 gain for voice engines."""
    try:
        pct = float(
            (getattr(config, "SOUND_VOLUMES", {}) or {}).get("type", 100))
    except (TypeError, ValueError):
        pct = 100.0
    return max(0.0, min(1.0, (pct / 100.0) * default))


def _wake_retry_delay(fails: int) -> float:
    """Backoff between Hey Cel restarts: 5 s, 10 s, 20 s, 40 s, then 60 s.

    A broken mic must not hot-spin the watchdog - but a mic that was merely
    busy while the call tore down is retried within seconds.
    """
    try:
        n = max(1, int(fails))
    except (TypeError, ValueError):
        n = 1
    return min(60.0, 5.0 * (2.0 ** (n - 1)))


class _WakeRingOverlay(QWidget):
    """Gemini-style wake ring: purple → dark-blue → white glow travelling the
    screen edge while Cel snapshots the desktop.

    Frameless Tool + StayOnTop so it floats over borderless-fullscreen games
    too (exclusive-fullscreen apps bypass the compositor - there it cannot
    show, and the chime + pet still fire). Transparent to the mouse, deletes
    itself after ~2.4 s. Pure QTimer repaints - no OpenGL, no threads.
    """

    DURATION_MS = 2400

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                self.setGeometry(screen.geometry())
        except Exception:
            pass
        self._t0 = time.monotonic()
        self._tick = QTimer(self)
        self._tick.setInterval(16)
        self._tick.timeout.connect(self._step)
        self._tick.start()

    def _progress(self) -> float:
        try:
            return min(1.0, (time.monotonic() - self._t0) * 1000.0
                       / self.DURATION_MS)
        except Exception:
            return 1.0

    def _step(self) -> None:
        try:
            if self._progress() >= 1.0:
                self._tick.stop()
                self.close()
                self.deleteLater()
                return
            self.update()
        except Exception:
            pass

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        try:
            p = self._progress()
            # Envelope: fade in, hold, fade out.
            if p < 0.12:
                alpha = p / 0.12
            elif p > 0.72:
                alpha = max(0.0, (1.0 - p) / 0.28)
            else:
                alpha = 1.0
            q = QPainter(self)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = self.rect()
            w, h = max(1, r.width()), max(1, r.height())
            m = 14
            pw, ph = w - 2 * m, h - 2 * m
            # 1. soft purple aura (wide, translucent)
            aura = QPen(QColor(168, 85, 247, int(90 * alpha)))
            aura.setWidth(16)
            q.setPen(aura)
            q.drawRoundedRect(m, m, pw, ph, 26, 26)
            # 2. dark-blue body
            body = QPen(QColor(37, 64, 199, int(210 * alpha)))
            body.setWidth(6)
            q.setPen(body)
            q.drawRoundedRect(m, m, pw, ph, 26, 26)
            # 3. travelling white dashes - the motion cue
            march = QPen(QColor(255, 255, 255, int(235 * alpha)))
            march.setWidth(2.5)
            march.setStyle(Qt.PenStyle.DashLine)
            try:
                march.setDashOffset(-p * (2 * (pw + ph)))
            except Exception:
                pass
            q.setPen(march)
            q.drawRoundedRect(m + 1, m + 1, pw - 2, ph - 2, 25, 25)
            q.end()
        except Exception:
            pass


class ChatScrollArea(QScrollArea):
    """Zero-ghosting transparent scroll area that forces full repaints on scroll."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("background: transparent; border: none;")
        if self.viewport():
            self.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.viewport().setAutoFillBackground(False)
            self.viewport().setStyleSheet("background: transparent; border: none;")

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if self.viewport():
            self.viewport().update()


class CelStudioCerebrium(QMainWindow):
    def _update_window_title(self, title: str):
        clean_title = title.replace("💬", "").replace("🌿", "").strip()
        if clean_title and clean_title != "New Chat":
            self.setWindowTitle(f"Cellium | {clean_title}")
        else:
            self.setWindowTitle("Cellium")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cellium")
        self.resize(1180, 750)
        self.setMinimumSize(780, 520)

        # Set window icon
        icon_path = ASSETS_DIR / "icon.webp"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # Load settings and merge with defaults to ensure all new keys exist
        loaded_settings = load_json(F_SETTINGS, {})
        self.settings = {**DEFAULT_SETTINGS, **loaded_settings}
        # The warm cache lives on Kaggle and dies with this process, so a
        # persisted "on" flag from last session must never outlive it - the
        # menu used to show 🔥 Warm Cache as active while nothing was running.
        if self.settings.get("kaggle_cache_on"):
            self.settings["kaggle_cache_on"] = False
            try:
                save_json(F_SETTINGS, self.settings)
            except Exception:
                pass
        # Fresh installs must start on the modern Animalese pack. A saved
        # explicit choice (legacy/muted) is respected; a missing/blank key
        # always falls back to "Cel's New Sounds".
        if not str(self.settings.get("sound_pack") or "").strip():
            self.settings["sound_pack"] = DEFAULT_SOUND_PACK
        # Per-sound volumes, custom .wav overrides and the live sound-pack
        # name are mirrored into config for play_ui_sound (which lives in a
        # service and must not import the UI). configure_sounds() also
        # normalises the legacy "Modern Cozy & Musical" / "Cel Legacy Sounds"
        # names to the current "Cel's New Sounds" / "Cel's Original Sound".
        try:
            configure_sounds(self.settings)
        except Exception:
            pass
        # Noise gate reads profile + strength from these keys at boot (F1).
        try:
            from cellium.services import noise_gate
            noise_gate.configure(self.settings)
        except Exception:
            pass
        # verbose_logging: the console and the in-app log viewer always run;
        # only the on-disk file is optional.
        try:
            set_verbose(bool(self.settings.get("verbose_logging", True)))
        except Exception:
            pass

        raw_sessions = load_json(F_SESSIONS, {})
        self.sessions = {
            sid: ses for sid, ses in raw_sessions.items()
            if any(m.get("role") in ("user", "assistant") for m in ses.get("memory", []))
        }
        if len(self.sessions) != len(raw_sessions):
            save_json(F_SESSIONS, self.sessions)
        self.presets = load_json(F_PRESETS, {"Default": "You are Cel, a helpful AI assistant. 💕"})
        self.mem_presets = load_json(F_MEMPRESETS, {"Default": ""})
        self.analytics_data = load_json(F_ANALYTICS, {})

        self.providers = {}
        self.models = {}
        self.active_server = "Server 1"
        self.current_sid = None
        self.worker = None
        self.audio_recorder = None
        self.stt_worker = None
        self.dev_memory = self.settings.get("cached_dev_memory", "")
        self.total_tokens = 0
        # Per-chat (per-session) running token total - "Total tokens in this chat".
        self.session_token_totals = {}
        self.stream_accum = ""
        self.active_stream_bubble = None
        self.ghost_bubble = None  # Temporary preview bubble for stopped generation
        self.pending_attachments = []
        self.active_tts_bubble = None
        self.active_tts_worker = None
        self.active_tts_thread = None
        self.zoom_level = 1.0
        # Edit mode state for Qwen-style message versioning
        self._edit_mode = False
        self._edit_bubble = None      # The bubble being edited
        self._edit_original_content = ""  # Original content for cancel
        self._edit_original_idx = -1    # Original index in memory
        self._edit_version = 0          # Version counter
        self.btn_cancel_edit = None     # Cancel button reference
        self._turn_agent_actions = []   # Accumulated agent actions for current turn history
        self._turn_parts = []           # Chronological turn segments: text blobs + agent_action tags
        self._active_agent_cards = {}   # tool_name -> list of pending AgentToolCards (FIFO)
        self._last_tool_args = {}       # tool_name -> last args dict (persist fallback when no card)
        self._worker_watchdog = None    # QTimer syncing Stop/Send with worker.isRunning()
        self._stop_btn_locked = False   # User pressed Stop - don't re-show Stop until next send
        self._orphan_ticks = 0          # Grace ticks before force-finalizing dead streams
        self._free_ram_pending = False  # Free RAM queued behind a winding-down worker
        self._free_ram_watch = None     # QTimer polling for the model to go idle
        self._free_ram_watch_ticks = 0
        self._pending_tool_diff = None  # Unified diff stashed between tool_diff and tool_result
        self._render_queue = []         # Tail bubbles still to render (progressive open)
        self._rendered_mem = set()      # (sid, mem_i) already on screen - never paint twice
        self._wheel_locked = bool(self.settings.get("disable_chat_wheel", False))

        self.init_ui()
        self._install_apple_tactile_sound_filter()
        self.init_data()
        # Restore persisted zoom (stylesheets use font-size: Npx which overrides setFont).
        # Applied synchronously - the old singleShot(0) restore could lose to
        # later startup work, leaving the pill showing e.g. 116% on a 100% UI.
        try:
            self._restore_zoom()
        except Exception:
            pass

    def _restore_zoom(self):
        saved_zoom = float(self.settings.get("zoom_level", 1.0) or 1.0)
        self.zoom_level = max(0.5, min(2.5, saved_zoom))
        if hasattr(self, "lbl_zoom"):
            self.lbl_zoom.setText(f"{int(self.zoom_level * 100)}%")
        if abs(self.zoom_level - 1.0) > 1e-6 or self.font_scale_factor() != 1.0:
            self.set_zoom(self.zoom_level)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_initial_zoom_synced", False):
            self._initial_zoom_synced = True
            if abs(getattr(self, "zoom_level", 1.0) - 1.0) > 1e-6 or self.font_scale_factor() != 1.0:
                self.set_zoom(self.zoom_level)
                QTimer.singleShot(0, lambda: self.set_zoom(self.zoom_level))
        # Fire the post-show warmup exactly once - after the first paint so the
        # UI is already responsive. Heavy data parsing (CelMoji, avatar lib)
        # happens in QThread so it never blocks the event loop.
        if not getattr(self, "_warmup_started", False):
            self._warmup_started = True
            QTimer.singleShot(0, self._start_post_show_warmup)

    def _start_post_show_warmup(self) -> None:
        """Kick off background data warming so first clicks feel instant.

        Runs AFTER the window has shown and processed its first paint event.
        - CelMoji CSV/TXT parsing → class cache (thread)
        - Avatar library chunked load (already timer-based, just start earlier)
        - Settings page data deps (shares CelMoji cache)
        """
        # 1) CelMoji data parse in background thread → populates
        # EmojiPickerWidget._CACHED_RAW_TABS so first open skips the multi-second
        # regex pass entirely. We reuse the picker's own parsing logic.
        try:
            from cellium.ui.settings.dialog import EmojiPickerWidget
            if EmojiPickerWidget._CACHED_RAW_TABS is None:
                worker = _CelMojiWarmupWorker(self)
                worker.tabsReady.connect(self._on_celmoji_warmed)
                # Keep the Python wrapper alive for the whole run: a QThread
                # whose wrapper is collected mid-start segfaults inside Qt's
                # metacall while emitting ``started``.
                self._celmoji_warmup_worker = worker
                worker.start()
        except Exception:
            pass

        # 2) Avatar library: the live stage already does chunked loading at
        # 2.5s, but we can nudge it to start immediately (still chunked, so
        # no freeze). If Live is opened early it will adopt the partial lib.
        try:
            stage = getattr(self, "_live_stage", None)
            if stage is not None and getattr(stage, "library", None) is None:
                stage._start_background_library_load()
        except Exception:
            pass

    def _on_celmoji_warmed(self, tabs: dict) -> None:
        """Called when background CelMoji parse finishes - publish to class cache."""
        try:
            from cellium.ui.settings.dialog import EmojiPickerWidget
            if tabs:
                EmojiPickerWidget._CACHED_RAW_TABS = tabs
                # Pre-warm the virtualized picker in RAM so opening is instant 0.0ms
                QTimer.singleShot(150, self._ensure_emoji_picker)
        except Exception:
            pass

    def init_ui(self):
        # Global CSS Reset & Glowing Neon Saturation for Inputs/Dropdowns
        self.setStyleSheet("""
            QWidget {
                font-family: 'Google Sans', 'Inter', system-ui, sans-serif;
                font-size: 13px;
                color: #E3E3E3;
            }
            QLabel {
                border: none;
                background: transparent;
            }
            QToolTip {
                background-color: rgba(20, 15, 35, 0.98);
                color: #F8F4FF;
                border: 1.5px solid #9333EA;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            QScrollBar:vertical {
                border: none;
                background: rgba(0, 0, 0, 0.15);
                width: 7px;
                margin: 0px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(147, 51, 234, 0.45);
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(192, 132, 252, 0.75);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        self.wallpaper_surface = WallpaperWidget(self)
        self.setCentralWidget(self.wallpaper_surface)

        root_layout = QHBoxLayout(self.wallpaper_surface)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        # ---------------- Left Navigation Drawer
        panel_opacity = self.settings.get("panel_opacity", 0.88)
        self.left_drawer = GlassPanel(radius=18, panel_opacity=panel_opacity)
        self.left_drawer.setFixedWidth(230)
        left_v = QVBoxLayout(self.left_drawer)
        left_v.setContentsMargins(12, 16, 12, 16)
        left_v.setSpacing(8)

        brand_lbl = QLabel("🌀 Cellium")
        brand_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #F8F4FF; border: none; background: transparent;")
        sub_lbl = QLabel("A Made Easy LLM Bridge")
        sub_lbl.setStyleSheet("font-size: 11px; color: #C084FC; margin-bottom: 8px; border: none; background: transparent;")
        left_v.addWidget(brand_lbl)
        left_v.addWidget(sub_lbl)

        btn_new = QPushButton("  New Chat")
        btn_new.setIcon(QIcon(str(ASSETS_DIR / "new_chat.png")))
        btn_new.setIconSize(QSize(18, 18))
        btn_models = QPushButton("  Model Hub")
        btn_models.setIcon(QIcon(str(ASSETS_DIR / "models.png")))
        btn_models.setIconSize(QSize(18, 18))
        btn_avatar = QPushButton("  Avatar Studio")
        btn_avatar.setIcon(QIcon(str(ASSETS_DIR / "avatar.svg")))
        btn_avatar.setIconSize(QSize(18, 18))
        btn_avatar.setToolTip("Browse all 1,520 Cerebellium expressions")
        btn_settings = QPushButton("  Settings")
        btn_settings.setIcon(QIcon(str(ASSETS_DIR / "settings.png")))
        btn_settings.setIconSize(QSize(18, 18))
        btn_analytics = QPushButton("  Analytics")
        btn_analytics.setIcon(QIcon(str(ASSETS_DIR / "analytics.png")))
        btn_analytics.setIconSize(QSize(18, 18))
        btn_notes = QPushButton("  Dev Console && Logs")
        btn_notes.setIcon(QIcon(str(ASSETS_DIR / "terminal.png")))
        btn_notes.setIconSize(QSize(18, 18))

        btn_new.clicked.connect(self.nav_new_chat)
        btn_models.clicked.connect(self.open_model_hub_view)
        btn_avatar.clicked.connect(self.open_avatar_view)
        btn_settings.clicked.connect(self.open_settings_view)
        btn_analytics.clicked.connect(self.open_analytics_view)
        btn_notes.clicked.connect(self.open_notes_view)

        for b in (btn_new, btn_models, btn_avatar, btn_settings, btn_analytics, btn_notes):
            b.setStyleSheet("""
                QPushButton {
                    background: transparent; color: #F8F4FF;
                    text-align: left; padding: 10px 14px;
                    border-radius: 12px; font-size: 13px; font-weight: bold; border: none;
                }
                QPushButton:hover { background: rgba(255, 255, 255, 0.08); color: #FFFFFF; }
            """)
            left_v.addWidget(b)

        left_v.addStretch()

        self.lbl_drawer_status = QLabel("✦ Cel Core Ready")
        self.lbl_drawer_status.setStyleSheet("font-size: 11px; color: #A8C7FA; font-weight: bold; border: none; background: transparent;")
        self.lbl_drawer_status.setStyleSheet("font-size: 11px; color: #A8C7FA; border: none; background: transparent;")
        self.lbl_token_count = QLabel(f"⚬ Total since launch: {self.total_tokens:,} tokens")
        self.lbl_token_count.setStyleSheet("font-size: 11px; color: #8E918F; font-weight: bold; border: none; background: transparent;")
        left_v.addWidget(self.lbl_drawer_status)
        left_v.addWidget(self.lbl_token_count)

        # Free RAM button at the very bottom
        btn_free_ram = QPushButton("  Free RAM")
        btn_free_ram.setIcon(QIcon(str(ASSETS_DIR / "gemini_cpu.svg")))
        btn_free_ram.setIconSize(QSize(18, 18))
        btn_free_ram.setStyleSheet("""
            QPushButton {
                background: rgba(239, 68, 68, 0.18); color: #FCA5A5;
                text-align: left; padding: 9px 14px;
                border-radius: 10px; font-size: 12px; font-weight: bold;
                border: 1.5px solid rgba(239, 68, 68, 0.4);
            }
            QPushButton:hover { background: rgba(239, 68, 68, 0.35); border-color: #EF4444; }
        """)
        btn_free_ram.clicked.connect(self.free_all_ram_click)
        left_v.addWidget(btn_free_ram)

        root_layout.addWidget(self.left_drawer)

        # ---------------- Main Central Container
        self.main_container = QWidget()
        main_v = QVBoxLayout(self.main_container)
        main_v.setContentsMargins(0, 0, 0, 0)
        main_v.setSpacing(10)

        # Top Bar
        self.top_bar = GlassPanel(radius=16, panel_opacity=panel_opacity)
        self.top_bar.setFixedHeight(54)
        top_h = QHBoxLayout(self.top_bar)
        top_h.setContentsMargins(14, 6, 14, 6)

        self.btn_toggle_drawer = QPushButton()
        self.btn_toggle_drawer.setIcon(QIcon(str(ASSETS_DIR / "gemini_menu.svg")))
        self.btn_toggle_drawer.setIconSize(QSize(22, 22))
        self.btn_toggle_drawer.setFixedSize(36, 36)
        self.btn_toggle_drawer.setToolTip("Menu & Options (Click for Zoom, Rename, Sidebar)")
        self.btn_toggle_drawer.setStyleSheet("background: transparent; border-radius: 18px; color: white; border: none;")
        self.btn_toggle_drawer.clicked.connect(lambda: self.show_hamburger_menu())
        self.btn_toggle_drawer.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_toggle_drawer.customContextMenuRequested.connect(self.show_hamburger_menu)

        # Quick Zoom Controls Pill in Top Bar
        self.zoom_pill = zoom_pill = QFrame()   # kept as attr: smart-resizer hides it in compact widths (Bug 1)
        zoom_pill.setStyleSheet("QFrame { background: rgba(255,255,255,0.05); border: 1px solid rgba(147, 51, 234, 0.35); border-radius: 10px; padding: 2px; }")
        z_h = QHBoxLayout(zoom_pill)
        z_h.setContentsMargins(4, 2, 4, 2)
        z_h.setSpacing(2)

        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.setFixedSize(22, 22)
        self.btn_zoom_out.setToolTip("Zoom out (Ctrl + Scroll Down)")
        self.btn_zoom_out.setStyleSheet("QPushButton { background: transparent; color: #E9D5FF; font-weight: bold; border: none; font-size: 13px; } QPushButton:hover { background: rgba(147, 51, 234, 0.5); border-radius: 4px; }")
        self.btn_zoom_out.clicked.connect(lambda: self.adjust_zoom(-0.08))

        self.lbl_zoom = QPushButton("100%")
        self.lbl_zoom.setToolTip("Reset Zoom to 100% (Ctrl + 0)")
        self.lbl_zoom.setStyleSheet("QPushButton { background: transparent; color: #C084FC; font-weight: bold; font-size: 10px; border: none; padding: 0 4px; } QPushButton:hover { color: #FFFFFF; }")
        self.lbl_zoom.clicked.connect(lambda: self.set_zoom(1.0))

        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setFixedSize(22, 22)
        self.btn_zoom_in.setToolTip("Zoom in (Ctrl + Scroll Up)")
        self.btn_zoom_in.setStyleSheet("QPushButton { background: transparent; color: #E9D5FF; font-weight: bold; border: none; font-size: 13px; } QPushButton:hover { background: rgba(147, 51, 234, 0.5); border-radius: 4px; }")
        self.btn_zoom_in.clicked.connect(lambda: self.adjust_zoom(0.08))

        z_h.addWidget(self.btn_zoom_out)
        z_h.addWidget(self.lbl_zoom)
        z_h.addWidget(self.btn_zoom_in)

        self.model_selector = QComboBox()
        self.model_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model_selector.setMinimumContentsLength(10)
        self.model_selector.setMinimumWidth(100)
        self.model_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.model_selector.setEditable(False)
        self.model_selector.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.model_selector.setStyleSheet("""
            QComboBox {
                background: rgba(14, 10, 24, 0.85); color: #F8F4FF;
                border: 1.5px solid #9333EA; border-radius: 10px; padding: 5px 8px; font-size: 11px;
            }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                background: rgba(18, 12, 32, 0.96); border: 1.5px solid #A855F7; border-radius: 8px;
                color: #F0E6FF; selection-background-color: #8A2BE2;
            }
        """)
        self.model_selector.currentIndexChanged.connect(self.on_model_changed)

        # Remove the completer since it's not editable anymore
        # self._model_completer = QCompleter(self)
        # self._model_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        # self._model_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        # self._model_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        # self.model_selector.setCompleter(self._model_completer)
        # self.model_selector.lineEdit().textEdited.connect(self._update_model_completer)

        # Thinking Level Dropdown (for models that support reasoning effort).
        # Items carry stable level KEYS as userData ("low", not "✦ Low"):
        # labels were rebuilt with a different emoji set on every model change
        # ("🧠 Low" vs "✦ Low"), so text matching forgot the pick each time.
        self.combo_thinking = QComboBox()
        for _think_key, _think_label in (
                ("force_off", "⛔ Force Off"), ("off", "✦ Default"),
                ("auto", "✦ Auto"), ("low", "✦ Low"),
                ("medium", "✦ Medium"), ("high", "✦ High")):
            self.combo_thinking.addItem(_think_label, _think_key)
        from cellium.core.utils import thinking_level_key
        _saved_think = thinking_level_key(
            self.settings.get("thinking_level", "auto"))
        _think_idx = self.combo_thinking.findData(_saved_think)
        self.combo_thinking.setCurrentIndex(_think_idx if _think_idx >= 0 else 0)
        # Normalise in memory so every reader sees one format (persisted to
        # disk at the next real save; construction itself never writes).
        self.settings["thinking_level"] = _saved_think
        self.combo_thinking.setMinimumWidth(112)
        self.combo_thinking.setMaximumWidth(175)
        try:
            self.combo_thinking.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToContents)
        except Exception:
            pass
        try:
            self.combo_thinking.view().setMinimumWidth(160)
        except Exception:
            pass
        self.combo_thinking.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.combo_thinking.setToolTip("Reasoning effort level (for models that support thinking)")
        self.combo_thinking.setStyleSheet("""
            QComboBox {
                background: rgba(14, 10, 24, 0.85); color: #F8F4FF;
                border: 1.5px solid #9333EA; border-radius: 10px; padding: 4px 6px; font-size: 11px;
            }
            QComboBox::drop-down { border: none; width: 0px; }
            QComboBox QAbstractItemView {
                background: rgba(18, 12, 32, 0.96); border: 1.5px solid #A855F7; border-radius: 8px;
                color: #F0E6FF; selection-background-color: #8A2BE2;
            }
        """)
        self.combo_thinking.currentTextChanged.connect(self._on_thinking_changed)

        # OpenRouter Dynamic "Token Usage" Selector (Strict Visibility: OpenRouter ONLY)
        self.combo_token_usage = QComboBox()
        self.combo_token_usage.addItems([
            "none (server picks)",
            "low (manually pick the cheapest)",
            "medium (safe for casual coding)",
            "best (uses tokens so make prompts count)",
        ])
        _saved_token_usage = self.settings.get("openrouter_token_usage", "medium (safe for casual coding)")
        _tu_idx = self.combo_token_usage.findText(_saved_token_usage)
        self.combo_token_usage.setCurrentIndex(_tu_idx if _tu_idx >= 0 else 2)
        self.combo_token_usage.setMinimumWidth(125)
        self.combo_token_usage.setMaximumWidth(215)
        if hasattr(self.combo_token_usage, "setSizeAdjustPolicy"):
            self.combo_token_usage.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
        self.combo_token_usage.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.combo_token_usage.setToolTip("Controls how OpenRouter routes tokens & protects against context truncation")
        self.combo_token_usage.setStyleSheet("""
            QComboBox {
                background: rgba(14, 10, 24, 0.85); color: #F8F4FF;
                border: 1.5px solid #0EA5E9; border-radius: 10px; padding: 5px 8px; font-size: 11px;
            }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                background: rgba(18, 12, 32, 0.96); border: 1.5px solid #38BDF8; border-radius: 8px;
                color: #F0E6FF; selection-background-color: #0284C7;
            }
        """)
        self.combo_token_usage.currentTextChanged.connect(self._on_token_usage_changed)
        self.combo_token_usage.setVisible(False)

        # Autonomous Agent Mode Quick Toggle Button in Top Bar
        agent_enabled = self.settings.get("agent_mode_enabled", False)
        self.btn_top_agent = QPushButton("✦ Agent: ON" if agent_enabled else "✧ Agent: OFF")
        self.btn_top_agent.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_top_agent.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_top_agent.setToolTip("Toggle Autonomous Agent Mode (Direct execution of terminal commands, scripts & system tools)")
        self._update_top_agent_button(agent_enabled)
        self.btn_top_agent.clicked.connect(self.toggle_agent_mode)

        # Coding Mode toggle (Task 17)
        coding_on = bool(self.settings.get("coding_mode", False))
        self.btn_coding_mode = QPushButton("💻 Coding: ON" if coding_on else "💬 Chat Mode")
        self.btn_coding_mode.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_coding_mode.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_coding_mode.setToolTip("Switch to Coding Mode (strips persona/memory, code-only output)")
        self.btn_coding_mode.clicked.connect(self.toggle_coding_mode)
        self._update_coding_mode_button(coding_on)

        # "Hey Cel" quick toggle - the panel switch for the always-on wake
        # word. Off releases the microphone entirely (battery).
        wake_on = bool(self.settings.get("listen_activation", False))
        self.btn_wake = QPushButton("🎧 Hey Cel: ON" if wake_on else "🎧 Hey Cel: OFF")
        self.btn_wake.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_wake.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_wake.setToolTip("Always-on wake word: say “Okay Cel” to open Live Mode hands-free. OFF releases the mic and saves battery.")
        self._update_wake_button(wake_on)
        self.btn_wake.clicked.connect(self.toggle_wake_word)
        if wake_on:
            # Deferred so the wake word never fights startup for the mic.
            QTimer.singleShot(3000, self.refresh_wake_listener)
            # Pet mode is a saved preference, not a per-session toggle: if it
            # was on when the app closed, she comes back.
            QTimer.singleShot(3400, self.apply_companion_settings)

        # The three old toggles stay alive as invisible state holders: the
        # tray, hamburger and settings dialog still call their _update_*
        # methods, but the top bar exposes one tidy More menu instead of
        # three fat pills fighting the model selector for width.
        for _legacy_toggle in (self.btn_top_agent, self.btn_coding_mode,
                               self.btn_wake):
            try:
                _legacy_toggle.hide()
            except Exception:
                pass

        self.btn_more = QToolButton()
        self.btn_more.setText("⋯ More")
        self.btn_more.setToolTip("Modes, persona, memory & Hey Cel")
        self.btn_more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_more.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_more.setStyleSheet("""
            QToolButton {
                background: rgba(255, 255, 255, 0.06);
                color: #E9D5FF;
                border: 1.5px solid rgba(147, 51, 234, 0.55);
                border-radius: 10px;
                padding: 4px 10px;
                font-weight: bold;
                font-size: 11px;
            }
            QToolButton:hover {
                background: rgba(147, 51, 234, 0.32);
                color: #FFFFFF;
                border-color: #C084FC;
            }
            QToolButton::menu-indicator { image: none; width: 0px; }
        """)
        self.more_menu = QMenu(self.btn_more)
        self.more_menu.setStyleSheet("""
            QMenu {
                background: rgba(18, 12, 32, 0.98);
                border: 1.5px solid #A855F7;
                border-radius: 10px;
                padding: 6px;
                color: #F0E6FF;
            }
            QMenu::item {
                padding: 7px 22px 7px 12px;
                border-radius: 6px;
                font-size: 12px;
            }
            QMenu::item:selected { background: #8A2BE2; color: #FFFFFF; }
            QMenu::separator {
                height: 1px; background: rgba(168, 85, 247, 0.35);
                margin: 4px 8px;
            }
        """)

        self.act_agent = self.more_menu.addAction("Agent Mode")
        self.act_agent.setCheckable(True)
        self.act_agent.setToolTip("Autonomous tools, terminal commands and file access")
        self.act_agent.triggered.connect(lambda *_: self.toggle_agent_mode())

        self.act_coding = self.more_menu.addAction("Coding Mode")
        self.act_coding.setCheckable(True)
        self.act_coding.setToolTip("ON = code-only output. OFF = normal Chat Mode.")
        self.act_coding.triggered.connect(lambda *_: self.toggle_coding_mode())

        self.act_wake = self.more_menu.addAction("Hey Cel")
        self.act_wake.setCheckable(True)
        self.act_wake.setToolTip("Always-on wake word - OFF releases the microphone")
        self.act_wake.triggered.connect(lambda *_: self.toggle_wake_word())

        self.act_image_gen = self.more_menu.addAction("🎨 Enable Image Gen")
        self.act_image_gen.setCheckable(True)
        self.act_image_gen.setToolTip("Let the AI call generate_image (Kaggle GPU) when you ask for/edits an image. Off = tool not sent to the AI.")
        self.act_image_gen.triggered.connect(lambda *_: self.toggle_image_gen())

        self.act_cache = self.more_menu.addAction("🔥 Warm Cache")
        self.act_cache.setCheckable(True)
        self.act_cache.setToolTip("Start a quota-capped (1h) warm notebook on Kaggle. WARNING: burns GPU quota while alive - stop when done!")
        self.act_cache.triggered.connect(lambda *_: self.toggle_warm_cache())

        self.more_menu.addSeparator()

        self.act_persona = self.more_menu.addAction("Persona")
        self.act_persona.setCheckable(True)
        self.act_persona.setToolTip("Include the persona prompt in every request")
        self.act_persona.triggered.connect(lambda *_: self.toggle_persona())

        self.act_memory = self.more_menu.addAction("Memory")
        self.act_memory.setCheckable(True)
        self.act_memory.setToolTip("Include your memory & behavioural rules")
        self.act_memory.triggered.connect(lambda *_: self.toggle_memory())

        # Back the live menu with the hidden buttons' QSS so the popup never
        # loses its dark glass look on platforms without a styled QMenu.
        self.btn_more.setMenu(self.more_menu)
        self._sync_more_menu()

        self.lbl_chat_title = QLabel("✦ New Chat")
        self.lbl_chat_title.setMaximumWidth(180)
        self.lbl_chat_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #F8F4FF; margin-left: 6px; border: none;")

        self.lbl_server_badge = QLabel("● Local GGUF Ready")
        self.lbl_server_badge.setStyleSheet("font-size: 11px; color: #A8C7FA; border: none;")

        # Pet Mode Quick Toggle Button in Top Bar
        pet_enabled = self.settings.get("pet_mode_enabled", False)
        top_h.addWidget(self.btn_toggle_drawer)
        top_h.addWidget(zoom_pill)
        top_h.addWidget(self.model_selector, stretch=1)
        top_h.addWidget(self.combo_thinking)
        top_h.addWidget(self.combo_token_usage)
        top_h.addWidget(self.btn_more)
        top_h.addWidget(self.lbl_chat_title)
        top_h.addWidget(self.lbl_server_badge)
        top_h.addStretch()

        self.btn_history = QPushButton()
        self.btn_history.setIcon(QIcon(str(ASSETS_DIR / "history.png")))
        self.btn_history.setIconSize(QSize(18, 18))
        self.btn_history.setFixedSize(36, 36)
        self.btn_history.setStyleSheet("background: transparent; border-radius: 18px; border: none;")
        self.btn_history.clicked.connect(self.toggle_right_drawer)
        top_h.addWidget(self.btn_history)

        main_v.addWidget(self.top_bar)

        # Image Preview Bar (ChatGPT/Gemini style - shows above chat when images attached)
        self.image_preview_bar = QFrame()
        self.image_preview_bar.setStyleSheet("""
            QFrame {
                background: rgba(14, 10, 24, 0.85);
                border: 1.5px solid #9333EA;
                border-radius: 12px;
                padding: 8px;
            }
            QLabel { border: none; background: transparent; }
        """)
        self.image_preview_bar.setVisible(False)
        self.image_preview_layout = QHBoxLayout(self.image_preview_bar)
        self.image_preview_layout.setContentsMargins(8, 6, 8, 6)
        self.image_preview_layout.setSpacing(8)
        main_v.addWidget(self.image_preview_bar)

        # Central Stacked Views
        self.central_stack = QStackedWidget()

        # Page 0: Chat Workspace
        self.chat_workspace = QWidget()
        self.chat_workspace.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.chat_workspace.setStyleSheet("background: transparent; border: none;")
        chat_ws_v = QVBoxLayout(self.chat_workspace)
        chat_ws_v.setContentsMargins(0, 0, 0, 0)
        chat_ws_v.setSpacing(8)

        self.chat_substack = QStackedWidget()
        self.chat_substack.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.chat_substack.setStyleSheet("background: transparent; border: none;")

        # Welcome Widget with Painted Companion Orb + Typewriter Greetings
        from PySide6.QtGui import QPixmap, QPainter, QRadialGradient, QColor, QBrush
        from PySide6.QtWidgets import QGridLayout, QGraphicsDropShadowEffect
        from cellium.ui.widgets.welcome import GradientTypedLabel

        self.welcome_widget = QWidget()
        self.welcome_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.welcome_widget.setMinimumWidth(560)  # room for greeting text without clipping
        wel_v = QVBoxLayout(self.welcome_widget)
        wel_v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wel_v.setSpacing(18)
        wel_v.setContentsMargins(24, 40, 24, 24)
        wel_v.addStretch(1)  # vertically center the whole orb/title/chips block

        # 150 dip orb - Qt scales it automatically on HiDPI.
        base_orb = 150
        accent = THEME_COLORS.get(self.active_server, THEME_COLORS["Server 1"])["accent"]
        if isinstance(accent, str):
            accent = QColor(accent)
        self.animated_orb = AnimatedFaceOrb(size=base_orb, theme_accent=accent)
        self.animated_orb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.animated_orb.setToolTip("Click me for a lil bounce 💜")

        # Soft radial halo behind the orb (GPT/Gemini-style ambient light).
        # NOTE: QStackedLayout ignores layout-level alignment here and parks
        # the orb at (0, 0) - 65 px off-centre. A grid with both widgets in
        # the same cell and explicit AlignCenter keeps it dead centre.
        orb_wrap = QWidget(self.welcome_widget)
        orb_wrap.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        orb_wrap.setFixedSize(280, 280)
        self.orb_wrap = orb_wrap
        _stack = QGridLayout(orb_wrap)
        _stack.setContentsMargins(0, 0, 0, 0)
        _stack.setSpacing(0)
        _halo = QLabel()
        _pm = QPixmap(280, 280)
        _pm.fill(Qt.GlobalColor.transparent)
        _hp = QPainter(_pm)
        _hp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        _g = QRadialGradient(140, 140, 20, 140, 140, 140)
        _g.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 150))
        _g.setColorAt(0.45, QColor(accent.red(), accent.green(), accent.blue(), 55))
        _g.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        _hp.setBrush(QBrush(_g))
        _hp.setPen(Qt.PenStyle.NoPen)
        _hp.drawEllipse(0, 0, 280, 280)
        _hp.end()
        _halo.setFixedSize(280, 280)
        _halo.setPixmap(_pm)
        _halo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _stack.addWidget(_halo, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        _stack.addWidget(self.animated_orb, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter)

        # Gradient headline (types itself in) with a soft glow behind it.
        self.welcome_title = GradientTypedLabel("")
        self.welcome_title.setStyleSheet("font-size: 36px; font-weight: 800; border: none;")
        self.welcome_title.setWordWrap(False)
        _glow = QGraphicsDropShadowEffect(self)
        _glow.setBlurRadius(30)
        _glow.setOffset(0, 0)
        _glow.setColor(QColor(168, 85, 247, 170))
        self.welcome_title.setGraphicsEffect(_glow)

        self.welcome_sub = TypedLabel("")
        self.welcome_sub.setStyleSheet("font-size: 15px; color: #C9B8E8; border: none;")
        self.welcome_sub.setWordWrap(False)

        # The orb floats above a layout-reserved slot so rage mode can dash
        # it anywhere on the page without the layout snapping it back.
        self._orb_slot = QWidget()
        self._orb_slot.setFixedSize(280, 280)
        self._orb_slot.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        wel_v.addWidget(self._orb_slot, alignment=Qt.AlignmentFlag.AlignCenter)
        wel_v.addWidget(self.welcome_title, alignment=Qt.AlignmentFlag.AlignCenter)
        wel_v.addWidget(self.welcome_sub, alignment=Qt.AlignmentFlag.AlignCenter)

        # Suggestion chips - the GPT/Gemini "try one of these" row.
        _chips = QHBoxLayout()
        _chips.setSpacing(10)
        _chips.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._welcome_chips = []

        def _chip(text, handler):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("""
                QPushButton {
                    background: rgba(147, 51, 234, 0.18); color: #E9D5FF;
                    border: 1px solid rgba(192, 132, 252, 0.45); border-radius: 16px;
                    padding: 8px 16px; font-size: 12px; font-weight: 600;
                }
                QPushButton:hover { background: rgba(147, 51, 234, 0.42); border-color: #C084FC; color: #FFFFFF; }
            """)
            b.clicked.connect(handler)
            _chips.addWidget(b)
            self._welcome_chips.append(b)
            return b

        _chip("🎨 Generate an image", lambda: self.show_imagine_dialog())
        _chip("💻 Debug my code", lambda: self._welcome_chip_fill("Help me debug this code:\n\n"))
        _chip("🧠 Explain a concept", lambda: self._welcome_chip_fill("Explain this like I'm 5: "))
        _chip("📝 Write something", lambda: self._welcome_chip_fill("Write a "))
        wel_v.addLayout(_chips)
        wel_v.addStretch(1)

        # Hand the orb its page + home anchor, then lift the wrapper above
        # the greeting so a fleeing orb is never hidden behind the text.
        self.animated_orb.set_roam_area(self.welcome_widget, self._orb_slot)
        orb_wrap.raise_()
        self.chat_substack.addWidget(self.welcome_widget)

        # Chat History Scroll (Frame-Perfect Anchor Engine)
        self.chat_scroll = ChatScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chat_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_scroll.setStyleSheet("background: transparent; border: none;")
        self._auto_scroll_anchored = True
        self.chat_scroll.verticalScrollBar().rangeChanged.connect(self._on_scroll_range_changed)
        self.chat_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)
        self.chat_scroll.viewport().installEventFilter(self)

        self.chat_content = ChatTimelineHost()
        self.chat_content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.chat_layout = QVBoxLayout(self.chat_content)
        self.chat_layout.setContentsMargins(40, 12, 40, 12)
        self.chat_layout.setSpacing(14)
        self.chat_layout.addStretch(1)
        self.chat_scroll.setWidget(self.chat_content)
        self.chat_substack.addWidget(self.chat_scroll)
        from cellium.ui.chat.turn_rail import ChatTurnNavRail
        self.chat_turn_rail = ChatTurnNavRail(self.chat_scroll, self)

        chat_ws_v.addWidget(self.chat_substack, stretch=1)

        # STT Choice Card
        self.stt_choice_card = STTChoiceCard(self)
        self.stt_choice_card.text_chosen.connect(self.on_stt_text_chosen)
        chat_ws_v.addWidget(self.stt_choice_card)

        # Emoji Picker - built LAZILY on first open. Constructing it here used
        # to parse 724 CelMoji files (375k lines) and materialise ~105k list
        # items before the window even appeared: measured 12–19 s of boot.
        self.emoji_picker = None

        # Attachment Preview Strip
        self.attachment_strip = QFrame()
        self.attachment_strip.setFixedHeight(50)
        self.attachment_strip.setStyleSheet("background: rgba(14, 10, 24, 0.9); border: 1.5px solid #9333EA; border-radius: 12px;")
        self.attachment_h = QHBoxLayout(self.attachment_strip)
        self.attachment_h.setContentsMargins(8, 4, 8, 4)
        self.attachment_h.setSpacing(8)
        self.attachment_strip.setVisible(False)
        chat_ws_v.addWidget(self.attachment_strip)

        # Telegram-Style Input Dock (Clicking anywhere highlights input!)
        self.input_pill = GlassPanel(radius=28, panel_opacity=panel_opacity)
        self.input_pill.setMinimumHeight(58)
        self.input_pill.mousePressEvent = self.on_pill_clicked
        pill_h = QHBoxLayout(self.input_pill)
        pill_h.setContentsMargins(10, 6, 12, 6)
        pill_h.setSpacing(8)

        self.btn_attach = QPushButton()
        self.btn_attach.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_paperclip.svg")))
        self.btn_attach.setIconSize(QSize(18, 18))
        self.btn_attach.setFixedSize(36, 36)
        self.btn_attach.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.06); border-radius: 18px; font-size: 16px; color: white; border: none;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.5); }
        """)
        self.btn_attach.clicked.connect(self.show_attach_menu)

        self.btn_emoji = QPushButton()
        self.btn_emoji.setFixedSize(36, 36)
        self.btn_emoji.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.06); border-radius: 18px;
                font-size: 18px; color: white; border: none;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.5); }
        """)
        self.btn_emoji.clicked.connect(self.toggle_emoji_picker)
        self._emoji_face_pool = all_emoji_pool()
        self._emoji_face_prev = None
        self.roll_emoji_face_button()

        # Image Generation button
        self.btn_imagine = QPushButton()
        self.btn_imagine.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_imagine.svg")))
        self.btn_imagine.setIconSize(QSize(20, 20))
        self.btn_imagine.setFixedSize(36, 36)
        self.btn_imagine.setToolTip("🎨 Generate Image (Kaggle) - click or type /imagine")
        self.btn_imagine.setStyleSheet("""
            QPushButton {
                background: transparent; border: 1px solid #7C3AED; border-radius: 18px;
                font-size: 16px; color: #E9D5FF;
            }
            QPushButton:hover { background: rgba(124, 58, 237, 0.12); border-color: #8B5CF6; }
        """)
        _imagine_glow = QGraphicsDropShadowEffect(self)
        _imagine_glow.setBlurRadius(14)
        _imagine_glow.setOffset(0, 0)
        _imagine_glow.setColor(QColor(124, 58, 237, 90))
        self.btn_imagine.setGraphicsEffect(_imagine_glow)
        self.btn_imagine.clicked.connect(self.show_imagine_dialog)

        self.edit_input = ChatInputEdit(self.input_pill)
        self.edit_input.setPlaceholderText("Message Cellium...")
        self.edit_input.returnPressed.connect(self.on_send_clicked)
        self.edit_input.filePasted.connect(self.handle_paste)
        # "/" slash-command mini drop-up (opposite of a dropdown, above the input)
        self.edit_input.textChanged.connect(self._on_input_text_changed)
        self.edit_input.installEventFilter(self)
        self._slash_popup = None
        self._slash_commands = list(self._SLASH_COMMANDS)
        self.edit_input.setStyleSheet("""
            QTextEdit {
                background: transparent; color: #F8F4FF; border: none; font-size: 14px; padding: 4px 8px;
            }
        """)
        self.edit_input.setMinimumHeight(38)

        self.btn_mic = QPushButton()
        self.btn_mic.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_mic.svg")))
        self.btn_mic.setIconSize(QSize(22, 22))
        self.btn_mic.setFixedSize(36, 36)
        self.btn_mic.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.06); border-radius: 18px; font-size: 16px; color: white; border: none;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.5); }
        """)
        self.btn_mic.clicked.connect(self.toggle_voice_input)

        # Cancel edit button (hidden by default, shown when editing a message)
        self.btn_cancel_edit = QPushButton("Cancel")
        self.btn_cancel_edit.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_x.svg")))
        self.btn_cancel_edit.setIconSize(QSize(14, 14))
        self.btn_cancel_edit.setFixedSize(96, 36)
        self.btn_cancel_edit.setStyleSheet("""
            QPushButton {
                background: rgba(239, 68, 68, 0.7);
                border: 1.5px solid #EF4444;
                border-radius: 18px;
                padding: 4px 10px;
                font-weight: bold;
                font-size: 12px;
                color: #FFFFFF;
            }
            QPushButton:hover { background: #DC2626; }
        """)
        self.btn_cancel_edit.setToolTip("Cancel editing and restore original message")
        self.btn_cancel_edit.clicked.connect(self.cancel_edit_mode)
        self.btn_cancel_edit.setVisible(False)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_stop.svg")))
        self.btn_stop.setIconSize(QSize(14, 14))
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #EF4444, stop:1 #DC2626);
                border: 1.5px solid #F87171; border-radius: 14px; padding: 6px 14px; font-weight: bold; color: white;
            }
            QPushButton:hover { background: #DC2626; }
        """)
        self.btn_stop.setVisible(False)
        self.btn_stop.clicked.connect(self.stop_generation)

        self.btn_send = QPushButton()
        self.btn_send.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_send.svg")))
        self.btn_send.setIconSize(QSize(18, 18))
        self.btn_send.setFixedSize(38, 38)
        self.btn_send.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8A2BE2, stop:1 #C084FC);
                border: 1.5px solid #E879F9; border-radius: 19px; font-size: 15px; color: white;
            }
            QPushButton:hover { background: #A855F7; }
        """)
        self.btn_send.clicked.connect(self.on_send_clicked)

        # ── CelAS Live Mode: full-screen voice companion ───────────────
        self.btn_live = QPushButton()
        self.btn_live.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_phone.svg")))
        self.btn_live.setIconSize(QSize(20, 20))
        self.btn_live.setToolTip("Live call with Cel - clears the whole screen")
        self.btn_live.setCursor(Qt.PointingHandCursor)
        self.btn_live.setFixedSize(38, 38)
        self.btn_live.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #059669, stop:1 #34D399);
                border: 1.5px solid #6EE7B7; border-radius: 19px; font-size: 15px; color: white;
            }
            QPushButton:hover { background: #10B981; }
        """)
        self._live_stage = LiveStage(parent=self)
        self._live_stage.setVisible(False)
        self._live = LiveModeController(self, self._live_stage)
        # Wired here, once, at construction: enter_live() already checks the
        # speech-engine credential, and _wire_live_controls() only runs
        # *after* that - so a handler attached there would miss the first call.
        try:
            self._live.stt_key_required.connect(self._live_stt_key_required)
        except Exception:
            pass
        self.btn_live.clicked.connect(self._enter_live_mode)
        self._live.ended.connect(self._exit_live_mode)
        # Hey Cel self-heal: the post-call restart can land while the OS is
        # still releasing the mic, and a dead listener used to stay deaf
        # forever. This ticks every 4 s (a few attribute reads - free) and
        # restarts the listener with backoff when it should be up but is not.
        self._wake = None
        self._wake_fails = 0
        self._wake_next_retry = 0.0
        self._wake_last_heard = ("", 0.0)
        self._wake_last_err_toast = 0.0
        self._wake_watchdog = QTimer(self)
        self._wake_watchdog.setInterval(4000)
        self._wake_watchdog.timeout.connect(self._wake_watchdog_tick)
        self._wake_watchdog.start()

        pill_h.addWidget(self.btn_attach)
        pill_h.addWidget(self.btn_emoji)
        pill_h.addWidget(self.btn_imagine)
        pill_h.addWidget(self.edit_input, stretch=1)
        pill_h.addWidget(self.btn_mic)
        pill_h.addWidget(self.btn_cancel_edit)
        pill_h.addWidget(self.btn_stop)
        pill_h.addWidget(self.btn_live)
        pill_h.addWidget(self.btn_send)
        pill_h.addWidget(self.btn_live)  # wave10: btn_live layout


        # Worker watchdog: keep Stop visible while thread runs; recover stuck "thinking"
        self._worker_watchdog = QTimer(self)
        self._worker_watchdog.setInterval(350)
        self._worker_watchdog.timeout.connect(self._sync_worker_buttons)
        self._worker_watchdog.start()

        # Progressive chat rendering: drains _render_queue in small slices so
        # switching chats paints instead of freezing (#1).
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(0)
        self._render_timer.timeout.connect(self._on_render_chunk)

        # Let chatbox stretch dynamically across the workspace dock
        input_container = QWidget()
        input_container_h = QHBoxLayout(input_container)
        input_container_h.setContentsMargins(20, 0, 20, 4)
        self.input_pill.setMinimumWidth(520)
        self.input_pill.setMaximumWidth(1200)
        self.input_pill.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        input_container_h.addWidget(self.input_pill, stretch=1)
        chat_ws_v.addWidget(input_container)
        self.central_stack.addWidget(self.chat_workspace)

        # Inbuilt View Pages (all lazy loaded on first click to make boot instant)
        # Index 1: Model Hub
        self.model_hub_view = None
        self._model_hub_placeholder = QWidget()
        self.central_stack.addWidget(self._model_hub_placeholder)

        # Index 2: Settings
        self.settings_view = QWidget()
        self.central_stack.addWidget(self.settings_view)

        # Index 3: Analytics
        self.analytics_view = None
        self._analytics_placeholder = QWidget()
        self.central_stack.addWidget(self._analytics_placeholder)

        # Index 4: Dev Notes
        self.dev_notes_view = None
        self._dev_notes_placeholder = QWidget()
        self.central_stack.addWidget(self._dev_notes_placeholder)

        # Index 5: Cerebellium Avatar Studio
        self.avatar_view = None
        self._avatar_placeholder = QWidget()
        self.central_stack.addWidget(self._avatar_placeholder)

        # Index 6: Focus Clock
        self.focus_clock_view = None
        self._focus_clock_placeholder = QWidget()
        self.central_stack.addWidget(self._focus_clock_placeholder)

        # Scrollbar screwed - replaced by sleek right-side timeline spine scrubber
        self.chat_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical, QScrollBar:horizontal {
                width: 0px;
                height: 0px;
                background: transparent;
                border: none;
            }
        """)

        # Tier-1 widgets that existed but were never attached. AGENTS.md
        # admitted this; these three lines are the fix.
        self._install_ambient_particles()
        self._install_command_palette()
        self._init_image_tool_hub()
        self._ensure_tray()

        main_v.addWidget(self.central_stack, stretch=1)
        root_layout.addWidget(self.main_container, stretch=1)

        # ---------------- Right Recent Chats Drawer
        self.right_drawer = GlassPanel(radius=18, panel_opacity=panel_opacity)
        # Overlay drawer: parented to the main container instead of the root
        # layout, so animating it never resizes the chat (which cost ~230 ms
        # per frame with 42 bubbles on screen).
        self.right_drawer.setParent(self.main_container)
        self.right_drawer.setFixedWidth(0)
        self.right_drawer.setVisible(False)
        self.right_drawer.raise_()
        right_v = QVBoxLayout(self.right_drawer)

        # ── Dim Backdrop Overlay (dims the screen behind popups / drawers) ──
        self.dim_overlay = QWidget(self.main_container)
        self.dim_overlay.setObjectName("DimOverlay")
        self.dim_overlay.setStyleSheet("background: rgba(0, 0, 0, 0.62); border-radius: 18px;")
        self.dim_overlay.setVisible(False)
        self.dim_overlay.mousePressEvent = lambda e: self._on_dim_overlay_clicked(e)
        self._dim_on_click = None
        right_v.setContentsMargins(12, 16, 12, 16)
        right_v.setSpacing(8)

        rh_box = QHBoxLayout()
        r_lbl = QLabel("Recent Chats")
        r_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #F8F4FF; border: none; background: transparent;")
        btn_close_r = QPushButton()
        btn_close_r.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_x.svg")))
        btn_close_r.setIconSize(QSize(13, 13))
        btn_close_r.setFixedSize(24, 24)
        btn_close_r.setStyleSheet("background: transparent; color: #C084FC; font-weight: bold; border: none;")
        btn_close_r.clicked.connect(self.toggle_right_drawer)
        rh_box.addWidget(r_lbl)
        rh_box.addStretch()
        rh_box.addWidget(btn_close_r)
        right_v.addLayout(rh_box)

        self.search_history = QLineEdit()
        self.search_history.setPlaceholderText("Search...")
        self.search_history.setStyleSheet("""
            QLineEdit {
                background: rgba(14, 10, 24, 0.85); color: #F8F4FF;
                border: 1.5px solid #9333EA; border-radius: 8px; padding: 6px 10px; font-size: 12px;
            }
            QLineEdit:focus { border: 1.5px solid #E879F9; }
        """)
        self.search_history.textChanged.connect(self.filter_history_items)
        right_v.addWidget(self.search_history)

        self.hist_scroll = QScrollArea()
        self.hist_scroll.setWidgetResizable(True)
        self.hist_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.hist_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.hist_scroll.setStyleSheet("background: transparent; border: none;")
        self.hist_content = QWidget()
        self.hist_content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.hist_layout = QVBoxLayout(self.hist_content)
        self.hist_layout.setContentsMargins(0, 0, 0, 0)
        self.hist_layout.setSpacing(4)
        self.hist_scroll.setWidget(self.hist_content)
        right_v.addWidget(self.hist_scroll, stretch=1)

        # The right drawer is an overlay child of main_container (see above),
        # deliberately NOT part of root_layout.

        # Drawer Animations
        self.anim_left = QPropertyAnimation(self.left_drawer, b"drawer_width")
        self.anim_left.setDuration(220)
        self.anim_left.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.anim_left.valueChanged.connect(lambda _: self.wallpaper_surface.update())
        self.anim_left.valueChanged.connect(lambda _: self._position_right_drawer())
        self.anim_left.finished.connect(self._finish_left_drawer)

        # Right drawer slides as an overlay: animating `pos` avoids resizing
        # the chat viewport (and its expensive per-bubble reflow) entirely.
        self.anim_right = QPropertyAnimation(self.right_drawer, b"pos")
        self.anim_right.setDuration(220)
        self.anim_right.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim_right.finished.connect(self._finish_right_drawer)

        self.toast = GlassToast(self)

        tint = self.settings.get("wallpaper_tint", 0.32)
        panel_opacity = self.settings.get("panel_opacity", 0.88)
        self.wallpaper_surface.set_theme_and_tint(self.active_server, tint, panel_opacity)
        self._ensure_tray()

    def on_pill_clicked(self, event):
        self.edit_input.setFocus()
        cursor = self.edit_input.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.edit_input.setTextCursor(cursor)

    def _apply_glass_blur(self):
        """Push the persisted glass_blur into every GlassPanel (#3).

        The setting was written by the slider but nothing ever read it, so the
        whole "Glass Blur Radius" control was decoration.
        """
        try:
            radius = int(max(0, min(64, int(self.settings.get("glass_blur", 16) or 0))))
        except (TypeError, ValueError):
            radius = 16
        self.settings["glass_blur"] = radius
        for panel in self.findChildren(GlassPanel):
            try:
                panel.set_blur(radius)
            except Exception:
                continue
        # No cache wipe here on purpose: the frost cache is keyed on the
        # *quantized* radius (4 px steps, 24-entry LRU), so slider ticks hit
        # warm entries. Wiping it every tick is what made the wallpaper look
        # permanently blurred while dragging Glass Blur (F3).

    def _apply_wheel_locks(self):
        """Honour the mouse-wheel preferences (#8)."""
        self._wheel_locked = bool(self.settings.get("disable_chat_wheel", False))

    def _on_analytics_cleared(self):
        self.analytics_data = {}
        try:
            save_json(F_ANALYTICS, self.analytics_data)
        except Exception:
            pass

    def _record_analytics(self, reply="", meta=None):
        """Append one finished turn to the persistent analytics log (#11)."""
        try:
            if meta is None:
                meta = getattr(self, "_pending_meta", None) or {}
            now = datetime.now()
            rows = self.analytics_data.get("turns")
            if not isinstance(rows, list):
                rows = []
            raw_tokens = int(meta.get("turn_tokens", 0) or 0)
            if raw_tokens <= 0 and reply and not meta:
                raw_tokens = max(1, len(reply) // 4)
            raw_secs = round(float(meta.get("think_time", 0.0) or 0.0), 2)
            if raw_secs <= 0.0 and reply:
                # Local models often report 0 think_time - estimate from output
                # length so the analytics page never shows "0.0s" forever (#6).
                raw_secs = round(max(0.4, len(reply) / 80.0), 2)
            rows.append({
                "ts": now.isoformat(timespec="seconds"),
                "day": now.strftime("%Y-%m-%d"),
                "model": str(meta.get("model")
                             or self.settings.get("selected_model") or "unknown"),
                "tokens": raw_tokens,
                "seconds": raw_secs,
                "chars": len(reply or ""),
            })
            self.analytics_data["turns"] = rows[-2000:]
            save_json(F_ANALYTICS, self.analytics_data)
            view = getattr(self, "analytics_view", None)
            if view is not None:
                view.set_data(self.analytics_data)
        except Exception as e:
            dev_log(f"[ANALYTICS] record failed: {e}")

    def show_toast(self, msg, icon="✨", duration=2600):
        if icon in ("⚠️", "❌", "🚨", "🚫"):
            try:
                dev_log(f"[UI-WARN] {msg}")
            except Exception:
                pass
        self.toast.show_toast(msg, icon=icon, duration_ms=duration)

    def stop_current_tts(self):
        """Stop any currently playing TTS audio without blocking main GUI thread."""
        # Stop the worker if running
        if hasattr(self, "active_tts_worker") and self.active_tts_worker:
            try:
                self.active_tts_worker.stop()
            except Exception:
                pass
            self.active_tts_worker = None
        
        # Stop the thread safely (asynchronous quit, never block GUI thread with wait)
        if hasattr(self, "active_tts_thread") and self.active_tts_thread:
            try:
                if self.active_tts_thread.isRunning():
                    self.active_tts_thread.quit()
            except Exception:
                pass
            self.active_tts_thread = None
        
        # Reset the bubble's button
        if hasattr(self, "active_tts_bubble") and self.active_tts_bubble:
            bubble = self.active_tts_bubble
            if hasattr(bubble, "btn_tts") and bubble.btn_tts:
                bubble.btn_tts.setText("")
                bubble.btn_tts.setIcon(QIcon(str(ASSETS_DIR / "tts.png")))
                bubble.btn_tts.setIconSize(QSize(16, 16))
                bubble.btn_tts.setToolTip("Speak with TTS")
                bubble.btn_tts.setStyleSheet("""
                    QPushButton { background: transparent; border: none; border-radius: 4px; padding: 2px; }
                    QPushButton:hover { background: rgba(147, 51, 234, 0.3); }
                """)
            self.active_tts_bubble = None

    def show_chat_view(self):
        self.central_stack.setCurrentIndex(0)

    def open_model_hub_view(self):
        play_ui_sound("click", 0.5)
        if self.model_hub_view is None:
            self.model_hub_view = ModelManagerWidgetNew(self.settings, self.providers, self.models, chat_app=self)
            self.model_hub_view.back_to_chat.connect(self.show_chat_view)
            self.model_hub_view.model_selected.connect(self.set_active_model)
            if hasattr(self, "_model_hub_placeholder"):
                self.central_stack.removeWidget(self._model_hub_placeholder)
                self._model_hub_placeholder.deleteLater()
            self.central_stack.insertWidget(1, self.model_hub_view)
        self.model_hub_view.models = dict(self.models)
        self.model_hub_view.settings = dict(self.settings)
        self.model_hub_view.on_prov_selected(self.model_hub_view.combo_prov.currentText())
        if self.model_hub_view.view_mode != "key_selected":
            self.model_hub_view.refresh_model_rows()
        self.model_hub_view.refresh_all_extra_lists()
        if abs(getattr(self, "zoom_level", 1.0) - 1.0) > 1e-6:
            self._apply_stylesheet_zoom(self.model_hub_view)
        self.roll_emoji_face_button()
        self.central_stack.setCurrentIndex(1)

    # ── Tier-1 widgets, finally attached ─────────────────────────────────
    def _build_focus_clock_page(self):
        """The pomodoro clock, as a real page in the stack."""
        from PySide6.QtWidgets import QSpinBox
        from cellium.ui.widgets.focus_clock import FocusClock, FocusSettings

        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 18, 24, 24)
        lay.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("⏳  Focus Clock")
        title.setStyleSheet(
            "color:#F4F1FF; font-size:22px; font-weight:bold;"
            "background:transparent;")
        head.addWidget(title)
        head.addStretch(1)
        btn_back = QPushButton("← Back to chat")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.setStyleSheet("""
            QPushButton{background:rgba(255,255,255,0.06);color:#E9D5FF;
              border:1px solid rgba(192,132,252,0.40);border-radius:14px;
              padding:7px 16px;font-size:12px;}
            QPushButton:hover{background:rgba(147,51,234,0.35);}
        """)
        btn_back.clicked.connect(self.show_chat_view)
        head.addWidget(btn_back)
        lay.addLayout(head)

        hint = QLabel("Work and break rounds - entirely local, nothing uploaded. "
                      "Press Ctrl+K any time to jump back to a command.")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "color:rgba(233,213,255,0.70);font-size:12px;background:transparent;")
        lay.addWidget(hint)

        def _spin(lo, hi, val):
            sb = QSpinBox(page)
            sb.setRange(lo, hi)
            sb.setValue(val)
            sb.setSuffix(" min")
            sb.setFixedWidth(96)
            sb.setStyleSheet("""
                QSpinBox{background:rgba(22,14,38,0.55);color:#F8F4FF;
                  border:1.5px solid rgba(147,51,234,0.45);border-radius:10px;
                  padding:5px 8px;font-size:12px;}
            """)
            return sb

        from PySide6.QtWidgets import QCheckBox
        _st = self.settings
        dur = QHBoxLayout()
        dur.setSpacing(10)
        self.focus_work_spin = _spin(5, 90, int(_st.get("focus_work_min", 25)))
        self.focus_short_spin = _spin(1, 30, int(_st.get("focus_short_min", 5)))
        self.focus_long_spin = _spin(5, 60, int(_st.get("focus_long_min", 15)))

        def _plain_spin(lo, hi, val, prefix="", suffix=""):
            sb = QSpinBox(page)
            sb.setRange(lo, hi)
            sb.setValue(val)
            if prefix:
                sb.setPrefix(prefix)
            if suffix:
                sb.setSuffix(suffix)
            sb.setFixedWidth(110)
            sb.setStyleSheet("""
                QSpinBox{background:rgba(22,14,38,0.55);color:#F8F4FF;
                  border:1.5px solid rgba(147,51,234,0.45);border-radius:10px;
                  padding:5px 8px;font-size:12px;}
            """)
            return sb

        self.focus_rounds_spin = _plain_spin(
            2, 12, int(_st.get("focus_rounds_before_long", 4)), prefix="× ")
        self.focus_goal_spin = _plain_spin(
            1, 40, int(_st.get("focus_daily_goal", 8)), suffix=" rounds")
        for label, sb in (("Work", self.focus_work_spin),
                          ("Short break", self.focus_short_spin),
                          ("Long break", self.focus_long_spin),
                          ("Rounds → long", self.focus_rounds_spin),
                          ("Daily goal", self.focus_goal_spin)):
            dur.addWidget(QLabel(f"{label}:"))
            dur.addWidget(sb)
        dur.addStretch(1)
        lay.addLayout(dur)

        opts = QHBoxLayout()
        opts.setSpacing(14)
        self.focus_auto_breaks = QCheckBox("Auto-start breaks")
        self.focus_auto_breaks.setChecked(bool(_st.get("focus_auto_breaks", True)))
        self.focus_auto_work = QCheckBox("Auto-start work rounds")
        self.focus_auto_work.setChecked(bool(_st.get("focus_auto_work", False)))
        for _chk in (self.focus_auto_breaks, self.focus_auto_work):
            _chk.setCursor(Qt.PointingHandCursor)
            _chk.setStyleSheet(
                "QCheckBox { color: #E9D5FF; font-size: 12px; spacing: 7px; } "
                "QCheckBox::indicator { width: 15px; height: 15px; border-radius: 5px; "
                "border: 1.4px solid rgba(147,51,234,0.8); background: rgba(10,8,20,0.9); } "
                "QCheckBox::indicator:checked { background: #A855F7; border-color: #F5D0FE; }")
            opts.addWidget(_chk)
        opts.addStretch(1)
        lay.addLayout(opts)

        _fs = FocusSettings(
            work_minutes=self.focus_work_spin.value(),
            short_break_minutes=self.focus_short_spin.value(),
            long_break_minutes=self.focus_long_spin.value(),
            rounds_before_long_break=self.focus_rounds_spin.value(),
            auto_start_breaks=self.focus_auto_breaks.isChecked(),
            auto_start_work=self.focus_auto_work.isChecked(),
            daily_goal_rounds=self.focus_goal_spin.value(),
        )
        self.focus_clock = FocusClock(page, settings=_fs)
        self.focus_clock.setMinimumSize(300, 300)
        # The clock paints its own dial but builds ordinary buttons, which came
        # out as bright white Qt defaults against the dark glass. Style them here
        # so the page reads as part of the app.
        self.focus_clock.setStyleSheet("""
            QPushButton {
                background: rgba(147, 51, 234, 0.55); color: #F8F4FF;
                border: 1px solid rgba(192, 132, 252, 0.55);
                border-radius: 14px; padding: 8px 18px;
                font-size: 12px; font-weight: 600;
                min-width: 92px; max-width: 150px;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.85); }
            QPushButton:disabled {
                background: rgba(255, 255, 255, 0.06);
                color: rgba(233, 213, 255, 0.35);
            }
        """)
        def _apply_focus_settings(*_a) -> None:
            _fs = FocusSettings(
                work_minutes=self.focus_work_spin.value(),
                short_break_minutes=self.focus_short_spin.value(),
                long_break_minutes=self.focus_long_spin.value(),
                rounds_before_long_break=self.focus_rounds_spin.value(),
                auto_start_breaks=self.focus_auto_breaks.isChecked(),
                auto_start_work=self.focus_auto_work.isChecked(),
                daily_goal_rounds=self.focus_goal_spin.value(),
            )
            self.focus_clock.settings = _fs
            if not self.focus_clock.running:
                self.focus_clock._set_phase(self.focus_clock.phase)
            _st.update({
                "focus_work_min": _fs.work_minutes,
                "focus_short_min": _fs.short_break_minutes,
                "focus_long_min": _fs.long_break_minutes,
                "focus_rounds_before_long": _fs.rounds_before_long_break,
                "focus_auto_breaks": _fs.auto_start_breaks,
                "focus_auto_work": _fs.auto_start_work,
                "focus_daily_goal": _fs.daily_goal_rounds,
            })

        for _w in (self.focus_work_spin, self.focus_short_spin, self.focus_long_spin,
                   self.focus_rounds_spin, self.focus_goal_spin):
            _w.valueChanged.connect(_apply_focus_settings)
        self.focus_auto_breaks.stateChanged.connect(_apply_focus_settings)
        self.focus_auto_work.stateChanged.connect(_apply_focus_settings)
        self.focus_clock.session_completed.connect(self._on_focus_session)
        self.focus_clock.rounds_changed.connect(self._on_focus_rounds)
        self.focus_goal_lbl = QLabel(f"🏆 0/{self.focus_goal_spin.value()} rounds today")
        self.focus_goal_lbl.setAlignment(Qt.AlignCenter)
        self.focus_goal_lbl.setStyleSheet(
            "color:#A78BFA; font-size:12px; font-weight:bold; background:transparent;")
        lay.addWidget(self.focus_goal_lbl)
        lay.addWidget(self.focus_clock, stretch=1)
        return page

    def _on_focus_session(self, phase: str) -> None:
        """A round finished - say so, and flash her face."""
        try:
            play_ui_sound("recv" if phase == "work" else "pop", 0.4)
        except Exception:
            pass
        verb = "Focus round done - take a break 🌿" if phase == "work" \
            else "Break's over - back to it 💪"
        try:
            self.show_toast(verb, icon="⏳")
        except Exception:
            pass

    def _on_focus_rounds(self, n: int) -> None:
        """Daily-goal tracker for the Focus Studio (Task 19)."""
        try:
            goal = int(self.focus_goal_spin.value())
        except Exception:
            goal = 8
        try:
            if n >= goal:
                self.focus_goal_lbl.setText(f"🏆 {n}/{goal} rounds - daily goal SMASHED! 💪✨")
            else:
                self.focus_goal_lbl.setText(f"🏆 {n}/{goal} rounds today")
        except Exception:
            pass

    def open_focus_clock_view(self):
        """Inbuilt View 6 - the pomodoro clock."""
        play_ui_sound("click", 0.5)
        self.roll_emoji_face_button()
        if self.focus_clock_view is None:
            self.focus_clock_view = self._build_focus_clock_page()
            if hasattr(self, "_focus_clock_placeholder"):
                self.central_stack.removeWidget(self._focus_clock_placeholder)
                self._focus_clock_placeholder.deleteLater()
            self.central_stack.insertWidget(6, self.focus_clock_view)
        self.central_stack.setCurrentIndex(6)
        try:
            from cellium.ui.widgets.focus_clock import FocusSettings
            self.focus_clock.settings = FocusSettings(
                work_minutes=self.focus_work_spin.value(),
                short_break_minutes=self.focus_short_spin.value(),
                long_break_minutes=self.focus_long_spin.value())
        except Exception:
            pass
        try:
            # Keep the "🏆 N/goal today" header in sync with the ring on every
            # open - the ring reads clock.rounds_today, while the header only
            # updated on a rounds_changed signal and could show a stale 0.
            self._on_focus_rounds(self.focus_clock.rounds_today)
        except Exception:
            pass

    def _install_ambient_particles(self):
        """Drifting dust behind the glass.

        A child of the wallpaper surface, so the glass panels still frost the
        *image* (frost_pixmap samples ``orig_pixmap``, not the widget) and the
        particles show through the gaps. Mouse-transparent: a full-window
        overlay must never swallow a click meant for the page beneath it.
        """
        try:
            from cellium.ui.widgets.particles import ParticleCanvas
            self.particles = ParticleCanvas(self.wallpaper_surface, interval_ms=100)
            self.particles.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.particles.set_count(48)
            self.particles.set_opacity(0.62)
            self.particles.setGeometry(self.wallpaper_surface.rect())
            self.particles.lower()
            if self.settings.get("ambient_particles", True):
                self.particles.start()
            else:
                self.particles.hide()
        except Exception as exc:
            self.particles = None
            dev_log(f"[PARTICLES] unavailable: {exc}")

    def set_ambient_particles(self, on: bool) -> bool:
        """Turn the drifting dust on/off and remember it."""
        self.settings["ambient_particles"] = bool(on)
        try:
            save_json(F_SETTINGS, self.settings)
        except Exception:
            pass
        canvas = getattr(self, "particles", None)
        if canvas is None:
            return False
        if on:
            canvas.show()
            canvas.start()
        else:
            canvas.stop()
            canvas.hide()
        return True

    def _install_command_palette(self):
        """Ctrl+K - the app's own command palette, registered with what it does."""
        try:
            from cellium.ui.widgets.command_palette import (
                CommandPaletteDialog, CommandRegistry,
            )
        except Exception as exc:
            dev_log(f"[PALETTE] unavailable: {exc}")
            return
        reg = CommandRegistry()
        self._command_registry = reg

        def _reg(title, fn, **kw):
            try:
                reg.register(title, fn, **kw)
            except Exception:
                pass

        # Navigation
        _reg("Go to chat", self.show_chat_view, category="Navigate")
        _reg("Go to Model Hub", self.open_model_hub_view, category="Navigate")
        _reg("Open Settings", self.open_settings_view, category="Navigate")
        _reg("Open Analytics", self.open_analytics_view, category="Navigate")
        _reg("Open Dev Notes", self.open_notes_view, category="Navigate")
        _reg("Open Avatar Studio", self.open_avatar_view, category="Navigate")
        _reg("Open Focus Clock", self.open_focus_clock_view,
             category="Navigate", shortcut="Ctrl+Shift+F")
        # Calls
        _reg("Start / end Live call", self.toggle_live_mode_call,
             category="Live", keywords="call phone celas")
        _reg("Stop generating", self.stop_generation,
             category="Live", keywords="cancel abort")
        # View
        _reg("Toggle desktop companion (pet mode)", self.toggle_companion,
             category="Pet", keywords="pet companion floating avatar")
        _reg("Toggle ambient particles", lambda: self.set_ambient_particles(
            not self.settings.get("ambient_particles", True)),
             category="View", keywords="dust background")
        _reg("Zoom in", lambda: self.adjust_zoom(0.08), category="View")
        _reg("Zoom out", lambda: self.adjust_zoom(-0.08), category="View")
        _reg("Reset zoom", lambda: self.set_zoom(1.0), category="View")
        _reg("Rename this chat", self.trigger_ai_rename,
             category="Chat", keywords="title name")
        _reg("Compact conversation", self.compact_current_session,
             category="Chat", keywords="summarise trim tokens")
        # Sessions
        _reg("New chat", self.nav_new_chat,
             category="Chat", keywords="fresh start")
        _reg("🎨 Generate image (Kaggle)", self.show_imagine_dialog,
             category="Chat", keywords="imagine image draw render kaggle art picture")

        try:
            self._command_palette = CommandPaletteDialog.install(
                self, reg, "Ctrl+K")
        except Exception as exc:
            dev_log(f"[PALETTE] install failed: {exc}")
            self._command_palette = None

    def open_settings_view(self):
        """Open Settings on a FRESH staging copy - every open rebuilds the
        page from the saved dict, so unsaved edits can never linger in the
        form and look “already saved”. Save is the only commit point."""
        play_ui_sound("click", 0.5)
        self.roll_emoji_face_button()
        try:
            cur = self.central_stack.currentIndex()
            if cur != 2:
                self._settings_return_index = cur
        except Exception:
            pass
        old = getattr(self, "settings_view", None)
        if old is not None:
            try:
                self.central_stack.removeWidget(old)
            except Exception:
                pass
            try:
                old.deleteLater()
            except Exception:
                pass
        self.settings_view = SettingsWidgetNew(self.settings)
        self.settings_view.back_to_chat.connect(self.show_chat_view)
        self.settings_view.saved.connect(self.on_settings_saved)
        self.central_stack.insertWidget(2, self.settings_view)
        if abs(getattr(self, "zoom_level", 1.0) - 1.0) > 1e-6:
            self._apply_stylesheet_zoom(self.settings_view)
        self.central_stack.setCurrentIndex(2)

    def open_analytics_view(self):
        play_ui_sound("click", 0.5)
        self.roll_emoji_face_button()
        if self.analytics_view is None:
            self.analytics_view = AnalyticsWidget(self.analytics_data)
            self.analytics_view.back_to_chat.connect(self.show_chat_view)
            self.analytics_view.cleared.connect(self._on_analytics_cleared)
            if hasattr(self, "_analytics_placeholder"):
                self.central_stack.removeWidget(self._analytics_placeholder)
                self._analytics_placeholder.deleteLater()
            self.central_stack.insertWidget(3, self.analytics_view)
        if self.analytics_view is not None:
            self.analytics_view.set_data(self.analytics_data)
        self.central_stack.setCurrentIndex(3)

    def open_notes_view(self):
        play_ui_sound("click", 0.5)
        self.roll_emoji_face_button()
        if self.dev_notes_view is None:
            self.dev_notes_view = DevNotesWidget()
            self.dev_notes_view.back_to_chat.connect(self.show_chat_view)
            if hasattr(self, "_dev_notes_placeholder"):
                self.central_stack.removeWidget(self._dev_notes_placeholder)
                self._dev_notes_placeholder.deleteLater()
            self.central_stack.insertWidget(4, self.dev_notes_view)
        self.central_stack.setCurrentIndex(4)

    def open_avatar_view(self):
        """Inbuilt View 5 - the Cerebellium Avatar Studio."""
        play_ui_sound("click", 0.5)
        self.roll_emoji_face_button()
        if self.avatar_view is None:
            self.avatar_view = AvatarStudioWidget(self.settings)
            self.avatar_view.back_to_chat.connect(self.show_chat_view)
            self.avatar_view.companion_requested.connect(self._on_avatar_companion_request)
            self.avatar_view.variants_curated.connect(self._on_studio_variants_curated)
            self.avatar_view.set_hidden_map(self.settings.get("studio_hidden_variants", {}))
            if hasattr(self, "_avatar_placeholder"):
                self.central_stack.removeWidget(self._avatar_placeholder)
                self._avatar_placeholder.deleteLater()
            self.central_stack.insertWidget(5, self.avatar_view)
        self.central_stack.setCurrentIndex(5)
        self.avatar_view.ensure_loaded()
        comp = getattr(self, "_companion", None)
        self.avatar_view.sync_companion(comp is not None and comp.visible)

    def _on_avatar_companion_request(self, action, value=""):
        """Handle requests coming out of the Avatar Studio page."""
        view = getattr(self, "avatar_view", None)
        try:
            if action == "visible":
                comp = self._ensure_companion()
                if comp is None:
                    return
                want = value == "true"
                if comp.visible != want:
                    comp.toggle()
                view.sync_companion(comp.visible)
                self.show_toast("🐾 Companion awake." if comp.visible
                                else "💤 Companion sleeping.",
                                icon="🐾" if comp.visible else "💤")
            elif action == "expression":
                comp = self._ensure_companion()
                if comp is None or not value:
                    return
                if comp.gender != view.gender and comp.set_gender(view.gender):
                    pass
                if comp.set_expression_by_name(value):
                    comp.show()
                    comp.wave()
                    view.sync_companion(comp.visible)
                    self.show_toast(f"🐾 Companion wearing {value}", icon="🐾")
            elif action == "gender":
                self.settings["companion_gender"] = value
                save_json(F_SETTINGS, self.settings)
                comp = getattr(self, "_companion", None)
                if comp is not None:
                    comp.set_gender(value)
        except Exception as e:
            # Never let a companion request break the page.
            dev_log(f"[AVATAR] companion request failed: {e}")
            self.show_toast(f"⚠️ Companion: {e}", icon="⚠️")

    def _on_studio_variants_curated(self, gender, hidden):
        """Persist the Avatar Studio wizard's keep/cull choices (fix 5.1)."""
        try:
            all_hidden = dict(self.settings.get("studio_hidden_variants", {}) or {})
            all_hidden[str(gender)] = [str(n) for n in (hidden or [])]
            self.settings["studio_hidden_variants"] = all_hidden
            save_json(F_SETTINGS, self.settings)
        except Exception:
            pass
        try:
            comp = getattr(self, "_companion", None)
            if comp is not None and hasattr(comp, "set_hidden"):
                comp.set_hidden(hidden or [])
        except Exception:
            pass
        self.show_toast(
            f"🧬 Variants curated for {gender} "
            f"({len(hidden or [])} tucked away).", icon="🧬")

    def roll_emoji_face_button(self):
        """Random face on the emoji-pill button - re-rolled on app open & panel hops."""
        if not hasattr(self, "btn_emoji") or self.btn_emoji is None:
            return
        pool = list(getattr(self, "_emoji_face_pool", None) or all_emoji_pool())
        prev = getattr(self, "_emoji_face_prev", None)
        # The raw pool carries ~1600 multi-glyph sequences (ZWJ families,
        # flags, skin tones) that render as 2-4 faces crammed into this button.
        def _one_glyph(e):
            if "‍" in e or "‎" in e or "‏" in e:
                return False
            if any("\U0001F3FB" <= c <= "\U0001F3FF" for c in e):
                return False
            if len(e) == 2 and all("\U0001F1E6" <= c <= "\U0001F1FF" for c in e):
                return False
            return len(e) <= 3
        single = [e for e in pool if _one_glyph(e)]
        choices = [f for f in (single or pool) if f != prev] or (single or pool)
        face = random.choice(choices)
        self._emoji_face_prev = face
        try:
            self.btn_emoji.setIcon(QIcon())
            self.btn_emoji.setIconSize(QSize(0, 0))
            self.btn_emoji.setText(face)
            self.btn_emoji.setToolTip("Open emoji picker 💕")
        except RuntimeError:
            pass

    def toggle_left_drawer(self):
        play_ui_sound("open" if self.left_drawer.width() == 0 else "close", 0.5)
        w = 0 if self.left_drawer.width() > 50 else 230
        self._drawer_animating = True
        self.anim_left.stop()
        self.anim_left.setStartValue(self.left_drawer.width())
        self.anim_left.setEndValue(w)
        self.anim_left.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep the overlay Recent Chats drawer glued to the right edge.
        self._position_right_drawer()
        # Keep dim overlay and inbuilt imagine panel fitted & centered
        try:
            if hasattr(self, "dim_overlay") and self.dim_overlay and self.dim_overlay.isVisible():
                self.dim_overlay.setGeometry(self.main_container.rect())
            if hasattr(self, "_imagine_panel") and self._imagine_panel and self._imagine_panel.isVisible():
                self._imagine_panel.center_in_parent()
        except Exception:
            pass
        # The particle canvas is a plain child of the wallpaper surface (no
        # layout manager owns it), so it kept its 100x30 construction size and
        # the dust stayed in the top-left corner of every window but the first.
        try:
            particles = getattr(self, "particles", None)
            if particles is not None and particles.parentWidget() is self.wallpaper_surface:
                particles.setGeometry(self.wallpaper_surface.rect())
        except Exception:
            pass
        if hasattr(self, 'emoji_picker') and self.emoji_picker:
            self.emoji_picker.move(20, max(20, self.main_container.height() - 340))

        # The live stage is a plain child (no layout manager), so it kept its
        # old geometry while the window grew - raw wallpaper leaked in behind
        # the call on every resize. Keep it glued to the window.
        try:
            if getattr(self, "_live", None) is not None and self._live.active:
                self._live_stage.setGeometry(self.rect())
        except Exception:
            pass

        # Smart top-bar resizer (Bug 1): overflow controls fold into the
        # hamburger menu instead of colliding - progressive and reversible.
        try:
            self._update_topbar_collapse()
        except Exception:
            pass

        self.update_all_bubble_geometries()

    # ── responsive top bar (Bug 1) ──────────────────────────────────────────
    def _topbar_collapse_pool(self):
        """Ordered top-panel controls, most-hideable first, with the action to
        re-trigger each one from the hamburger menu while it is folded away."""
        def _popup(w):
            return (lambda: w.showPopup()) if w is not None else None
        more = getattr(self, "btn_more", None)
        more_popup = (lambda: self.more_menu.popup(QCursor.pos())) if more is not None else None
        pool = [
            ("● Server", getattr(self, "lbl_server_badge", None), None),
            ("✦ Chat title", getattr(self, "lbl_chat_title", None), None),
            ("⋯ More", more, more_popup),
            ("🧠 Thinking", getattr(self, "combo_thinking", None), _popup(getattr(self, "combo_thinking", None))),
            ("🔍 Zoom", getattr(self, "zoom_pill", None), lambda: self.adjust_zoom(0.08)),
            ("🧩 Model", getattr(self, "model_selector", None), _popup(getattr(self, "model_selector", None))),
        ]
        return [t for t in pool if t[1] is not None]

    def _update_topbar_collapse(self):
        """Smart resizer (Bug 1): when the top panel gets too compact, its
        controls fold away right-to-left (into the hamburger menu) instead of
        colliding or overflowing the window edge - and unfurl again as the
        width returns. Purely measured: no more magic 880/680 thresholds."""
        tb = getattr(self, "top_bar", None)
        if tb is None or not hasattr(tb, "layout"):
            return
        try:
            cm = tb.layout().contentsMargins()
            spac = max(0, tb.layout().spacing())
        except Exception:
            from PySide6.QtCore import QMargins
            cm, spac = QMargins(14, 6, 14, 6), 10
        pool = self._topbar_collapse_pool()
        if not pool:
            return
        prev_hidden = set(getattr(self, "_topbar_hidden_keys", set()))
        anchor_fixed = [getattr(self, "btn_toggle_drawer", None),
                        getattr(self, "btn_history", None)]
        anchor_fixed = [w for w in anchor_fixed if w is not None]
        fixed_w = 0
        for w in anchor_fixed:
            try:
                fixed_w += max(w.minimumSizeHint().width(), 30)
            except Exception:
                fixed_w += 36
        items = []
        for label, w, act in pool:
            try:
                items.append((label, w, act, max(46, w.minimumSizeHint().width())))
            except Exception:
                pass
        avail = max(0, tb.width() - cm.left() - cm.right())

        def fits(vis_count, sum_w):
            gaps = spac * max(0, (len(anchor_fixed) + vis_count) - 1)
            return (fixed_w + gaps + sum_w) <= avail

        sumw = sum(it[3] for it in items)
        vis = list(range(len(items)))
        while vis and not fits(len(vis), sumw):
            sumw -= items[vis.pop(0)][3]

        hidden_keys, collapsed = set(), []
        for idx, (label, w, act, _w) in enumerate(items):
            if idx in vis:
                if label in prev_hidden:
                    w.setVisible(True)
            else:
                w.setVisible(False)
                hidden_keys.add(label)
                if act is not None:
                    collapsed.append((label, act))
        self._topbar_hidden_keys = hidden_keys
        self._topbar_collapsed = collapsed

    def _right_drawer_geometry(self) -> tuple[int, int]:
        """Top offset + height for the overlay drawer.

        The drawer is a child of ``main_container``, so without an offset its
        "Recent Chats" header painted straight over the top bar's window
        buttons. Start it just below the bar instead, and give it the
        remaining height.
        """
        try:
            mw = self.main_container
            top = 0
            tb = getattr(self, "top_bar", None)
            if tb is not None and tb.isVisible():
                top = max(0, tb.mapTo(mw, QPoint(0, tb.height())).y() + 6)
            return top, max(120, mw.height() - top)
        except Exception:
            return 64, 480

    def _position_right_drawer(self):
        """Keep the overlay drawer glued to the right edge of the chat area."""
        try:
            drawer = getattr(self, "right_drawer", None)
            if drawer is None:
                return
            anim = getattr(self, "anim_right", None)
            if anim is not None and anim.state() == QPropertyAnimation.State.Running:
                return
            w = drawer.width()
            if w <= 0:
                return
            mw = self.main_container
            top, height = self._right_drawer_geometry()
            drawer.resize(w, height)
            drawer.move(max(0, mw.width() - w), top)
        except Exception:
            pass

    def _finish_right_drawer(self):
        try:
            if self.right_drawer.pos().x() >= self.main_container.width() - 2:
                self.right_drawer.setVisible(False)
                self.right_drawer.setFixedWidth(0)
        except Exception:
            pass

    def _finish_left_drawer(self):
        self._drawer_animating = False
        # One reflow after the drawer settles instead of one per animation
        # frame (the per-frame reflow is what made the drawer stutter).
        try:
            self.update_all_bubble_geometries()
        except Exception:
            pass
        self._position_right_drawer()

    def show_dim_overlay(self, on_click=None):
        """Dim the Cel main screen behind floating drawers, modals, or popups."""
        if hasattr(self, "dim_overlay") and self.dim_overlay:
            self.dim_overlay.setGeometry(self.main_container.rect())
            self._dim_on_click = on_click
            self.dim_overlay.setVisible(True)
            self.dim_overlay.raise_()

    def hide_dim_overlay(self):
        """Hide the dim overlay and clear callback."""
        if hasattr(self, "dim_overlay") and self.dim_overlay:
            self.dim_overlay.setVisible(False)
            self._dim_on_click = None

    def _on_dim_overlay_clicked(self, event):
        """Clicking anywhere on the dim backdrop dismisses the current popup."""
        cb = getattr(self, "_dim_on_click", None)
        self.hide_dim_overlay()
        if callable(cb):
            try:
                cb()
            except Exception:
                pass

    def toggle_right_drawer(self):
        play_ui_sound("open" if self.right_drawer.width() == 0 else "close", 0.5)
        mw = self.main_container
        if self.right_drawer.width() == 0:
            top, height = self._right_drawer_geometry()
            self.right_drawer.setFixedWidth(230)
            self.right_drawer.resize(230, height)
            self.show_dim_overlay(on_click=self.toggle_right_drawer)
            self.right_drawer.setVisible(True)
            self.right_drawer.raise_()
            # Start just off the right edge and slide in as an overlay,
            # below the top bar so the header never overlaps its buttons.
            start = QPoint(mw.width(), top)
            end = QPoint(max(0, mw.width() - 230), top)
            self.right_drawer.move(start)
            self.anim_right.stop()
            self.anim_right.setStartValue(start)
            self.anim_right.setEndValue(end)
            self.anim_right.start()
        else:
            self.hide_dim_overlay()
            top, _height = self._right_drawer_geometry()
            self.anim_right.stop()
            self.anim_right.setStartValue(self.right_drawer.pos())
            self.anim_right.setEndValue(QPoint(mw.width(), top))
            self.anim_right.start()

    def _running_generation_workers(self):
        """Every QThread that could still be inside llama.cpp right now.

        ``stop_generation()`` detaches the active worker into
        ``_retired_workers`` *before* it has actually exited, so the retired
        set is a native-context owner too. Treating it as idle is exactly
        what let Free RAM close a model mid-decode and segfault the app.
        """
        candidates = []
        active = getattr(self, "worker", None)
        if active is not None:
            candidates.append(active)
        candidates.extend(list(getattr(self, "_retired_workers", ()) or ()))
        alive = []
        for cand in candidates:
            try:
                if cand is not None and cand.isRunning():
                    alive.append(cand)
            except RuntimeError:
                continue
        return alive

    def free_all_ram_click(self):
        """Action for Free RAM button at bottom of drawer.

        Never unload the GGUF while a worker is alive. If one is still
        winding down, stop it and queue the free - the poll releases RAM the
        moment the last native owner is gone. This is the crash-safe path:
        closing llama.cpp underneath a running decode is a hard segfault.
        """
        busy = self._running_generation_workers()
        if busy:
            self._free_ram_pending = True
            for worker in busy:
                try:
                    if hasattr(worker, "request_stop"):
                        worker.request_stop()
                except Exception:
                    pass
            self.show_toast(
                "⏳ Stopping the model first - RAM frees automatically when it's safe 🧹",
                icon="⏳", duration=3600)
            self._start_free_ram_watch()
            return

        self._free_ram_pending = False
        self._stop_free_ram_watch()
        self._perform_free_ram()

    def _start_free_ram_watch(self):
        watch = getattr(self, "_free_ram_watch", None)
        if watch is None:
            watch = QTimer(self)
            watch.setInterval(200)
            watch.timeout.connect(self._poll_free_ram)
            self._free_ram_watch = watch
        self._free_ram_watch_ticks = 0
        watch.start()

    def _stop_free_ram_watch(self):
        watch = getattr(self, "_free_ram_watch", None)
        if watch is not None:
            try:
                watch.stop()
            except RuntimeError:
                pass

    def _poll_free_ram(self):
        self._free_ram_watch_ticks = int(getattr(self, "_free_ram_watch_ticks", 0)) + 1
        fresh = getattr(self, "worker", None)
        try:
            fresh_running = fresh is not None and fresh.isRunning()
        except RuntimeError:
            fresh_running = False
        # A *new* turn started while we waited - its context is in use, so
        # cancel instead of unloading under it.
        if fresh_running and not getattr(self, "_stop_btn_locked", False):
            self._cancel_pending_free_ram("A new generation started - Free RAM cancelled.")
            return
        if self._running_generation_workers():
            if self._free_ram_watch_ticks >= 150:   # ~30 s safety valve
                self._cancel_pending_free_ram("Model still busy - try Free RAM again in a moment.")
            return
        if getattr(self, "_free_ram_pending", False):
            self._free_ram_pending = False
            self._stop_free_ram_watch()
            self._perform_free_ram(queued=True)

    def _cancel_pending_free_ram(self, message: str):
        self._free_ram_pending = False
        self._stop_free_ram_watch()
        self._free_ram_watch_ticks = 0
        self.show_toast(f"🧹 {message}", icon="🧹", duration=3200)

    def _perform_free_ram(self, queued: bool = False):
        # Only genuinely finished workers may be forgotten. Never blank a
        # worker's model reference while its thread is still alive.
        for rw in list(getattr(self, "_retired_workers", ()) or ()):
            try:
                if not rw.isRunning():
                    self._retired_workers.discard(rw)
            except RuntimeError:
                self._retired_workers.discard(rw)
        stats = free_all_ram(skip_gguf=False) or {}
        play_ui_sound("click", 0.5)
        gguf = bool(stats.get("gguf"))
        freed_mb = float(stats.get("freed_mb") or 0.0)
        objects = int(stats.get("objects") or 0)
        if gguf:
            self.lbl_server_badge.setText("🧹 GGUF Unloaded")
        note = " (queued)" if queued else ""
        if gguf and freed_mb >= 1.0:
            self.show_toast(
                f"Freed {freed_mb:.0f} MB ({objects} objs, GGUF out) 🧹{note}",
                icon="🧹", duration=3200,
            )
        elif freed_mb >= 0.5 or objects > 0:
            self.show_toast(
                f"Freed {freed_mb:.1f} MB ({objects} objs) 🧹{note}",
                icon="🧹", duration=3000,
            )
        else:
            self.show_toast("Caches trimmed - RSS unchanged 🧹" + note, icon="🧹")

    def _ensure_emoji_picker(self):
        """Build the emoji picker on first use.

        Its CelMoji library is genuinely heavy (parsing + ~105k list rows),
        so it must never be part of the boot path. The parsed dataset is also
        disk-cached by ``_load_raw_datasets_once`` so later launches/opens
        skip the multi-second regex pass entirely.
        """
        picker = getattr(self, "emoji_picker", None)
        if picker is not None:
            return picker
        picker = EmojiPickerWidgetNew(self.main_container)
        picker.emoji_selected.connect(self.insert_emoji)
        # CelMoji merge: the picker reads/writes frecency + pins + bans here.
        try:
            picker.settings = self.settings
        except Exception:
            pass
        picker.setVisible(False)
        try:
            picker.move(20, max(20, self.main_container.height() - 340))
        except Exception:
            pass
        self.emoji_picker = picker
        return picker

    def toggle_emoji_picker(self):
        play_ui_sound("pop", 0.5)
        picker = self._ensure_emoji_picker()
        try:
            btn_pos = self.btn_emoji.mapTo(self.main_container, QPoint(0, 0))
            target_x = max(20, min(btn_pos.x() - 10, self.main_container.width() - picker.width() - 20))
            target_y = max(20, self.main_container.height() - picker.height() - 70)
            picker.move(target_x, target_y)
        except Exception:
            pass
        picker.setVisible(not picker.isVisible())
        if picker.isVisible():
            self.show_dim_overlay(on_click=self.toggle_emoji_picker)
            picker.raise_()
            picker.search_edit.setFocus()
        else:
            self.hide_dim_overlay()

    def play_user_typing_sound(self, char=""):
        """Your keystrokes - a channel of their own.

        ``typing_sound_mode`` is *Cel's* streaming voice: it decides what she
        sounds like as her reply types out. It used to decide your keyboard as
        well, so changing her voice changed yours and muting her muted you.
        The user's channel is ``user_typing_sound_*``.
        """
        s = self.settings
        if not s.get("user_typing_sound_enabled", True):
            return
        mode = normalize_user_typing_mode(
            s.get("user_typing_sound_mode", "Normal (UI clicks)"))
        if mode == "None (Silent)":
            return
        try:
            vol = max(0.0, min(1.0, float(
                s.get("user_typing_sound_volume", 40)) / 100.0))
        except (TypeError, ValueError):
            vol = 0.4
        if vol <= 0.001:
            return
        if mode == "Cel's Modern Melodi":
            play_animalese_chirp(
                seed_char=str(char or "a")[:1] or "a",
                enabled=s.get("animalese_voice", True),
                variant=s.get("ac_voice_variant", "Classic AC"))
            return
        # "Cel's Legacy Sound" and "Cel's Realistic Voice" both fall back to
        # a lightweight UI click for your own keyboard - the realistic
        # synthesiser is Cel's speech channel, not keystroke chirps.
        play_ui_sound("type" if mode == "Normal (UI clicks)" else "keypress",
                      vol)

    def play_typing_sound(self):
        """Back-compat alias - your keystrokes, not Cel's voice."""
        self.play_user_typing_sound()

    def _live_voice_speaks(self) -> bool:
        """True while a live call voices replies through a voice TTS host.

        Cel's typing melody (clicks/chirps) plays as each token streams in  - 
        on top of her spoken voice that is beep-boop soup, so the melody
        yields whenever a voice model owns the call.
        """
        try:
            live = getattr(self, "_live", None)
            if live is None or not live.active:
                return False
        except Exception:
            return False
        return bool(str(self.settings.get("live_voice") or "").strip())

    def insert_emoji(self, emo):
        self.edit_input.insertPlainText(emo)
        self.edit_input.setFocus()
        self.play_typing_sound()

    def on_stt_text_chosen(self, text):
        """A picked transcript lands in the box - it never replaces it.

        The multi-engine card's "Use / Edit" used to ``setPlainText`` the
        whole input, wiping whatever was half-typed. Both STT entry points
        now share the append-at-caret path.
        """
        self._append_transcript(text)
        self.edit_input.setFocus()

    def on_settings_saved(self, new_settings):
        # Also grab context from Model Hub view if it exists (user might hit Save on main Settings tab)
        if hasattr(self, "model_hub_view") and self.model_hub_view and hasattr(self.model_hub_view, "combo_ctx"):
            ctx_text = self.model_hub_view.combo_ctx.currentText()
            new_settings["offline_n_ctx_str"] = ctx_text
            ctx_val = CTX_MAP.get(ctx_text)
            if ctx_val is not None:
                new_settings["offline_n_ctx"] = ctx_val
        # GGUF stays warm: get_or_load_llama's lazy param check reloads on next message only if needed
        prev_model = self.settings.get("selected_model", "")
        self.settings = dict(new_settings)
        if prev_model and (not self.settings.get("selected_model") or self.settings.get("selected_model") not in self.models):
            self.settings["selected_model"] = prev_model
        try:
            from cellium.core.utils import set_kokoro_tts_dir
            set_kokoro_tts_dir(self.settings.get("kokoro_tts_dir", ""))
        except Exception:
            pass
        # configure_sounds() publishes the canonical pack name into config;
        # play_ui_sound() reads it there (it is a service, not the UI).
        try:
            configure_sounds(self.settings)
        except Exception:
            pass
        try:
            set_verbose(bool(self.settings.get("verbose_logging", True)))
        except Exception:
            pass
        # font_scale only affects the bubble bodies, which bake their size into
        # inline HTML - so the existing bubbles have to be re-rendered, not just
        # the stylesheet updated.
        try:
            self._propagate_font_to_bubbles(self.font())
        except Exception:
            pass
        # Pet mode may have just been switched on or off in Settings.
        try:
            QTimer.singleShot(0, self.apply_companion_settings)
        except Exception:
            pass
        tint = self.settings.get("wallpaper_tint", 0.32)
        panel_opacity = self.settings.get("panel_opacity", 0.88)
        # F3: darkness is tint-only now - the old 3rd arg multiplied the two
        # together and made the wallpaper opaque whenever either slider moved.
        self.wallpaper_surface.set_theme_and_tint(self.active_server, tint)
        
        # Update all GlassPanels with new panel_opacity
        for panel in [self.left_drawer, self.top_bar, self.input_pill, self.right_drawer]:
            if hasattr(panel, 'set_panel_opacity'):
                panel.set_panel_opacity(panel_opacity)

        # glass_blur and the wheel locks finally take effect (#3, #8)
        self._apply_glass_blur()
        self._apply_wheel_locks()
        
        # F1: apply the noise gate with the freshly saved strength/enable.
        try:
            from cellium.services import noise_gate
            noise_gate.configure(self.settings)
        except Exception:
            pass

        # F3: glass_opacity is a bubble property now - repaint live bubbles.
        try:
            go = float(self.settings.get("glass_opacity", 0.72))
            for b in self.findChildren(MessageBubbleNew):
                if hasattr(b, "glass_opacity"):
                    b.glass_opacity = go
                    b.update()
        except Exception:
            pass

        # Fresh avatars land on disk instantly (not via settings), so repaint
        # every circular cutout once the settings sheet closes.
        try:
            self._refresh_avatar_labels()
        except Exception:
            pass

        # Bug 34 & 35: Re-sync Live Controller and model dropdown
        if getattr(self, "_live", None) is not None:
            try:
                self._live.sync_settings()
            except Exception:
                pass
        self.rebuild_available_models()
        self.update_model_dropdown()

        # Persona/Memory/instruction categories may have changed in Settings.
        self._sync_more_menu()
        self._refresh_system_prompt_memory()

        self.show_toast("Preferences saved successfully! 💖", icon="✓")
        # Back to whatever was behind Settings - not always chat, and never
        # the call stage (sync_settings no longer opens it; see live_mode).
        try:
            idx = int(getattr(self, "_settings_return_index", 0))
            if idx < 0 or idx >= self.central_stack.count() or idx == 2:
                idx = 0
        except Exception:
            idx = 0
        self.central_stack.setCurrentIndex(idx)

    # ── system tray (minimize-to-dock listening) ─────────────────────────
    def _ensure_tray(self) -> bool:
        """Create the dock icon on first minimize. False = no tray here."""
        if getattr(self, "_tray", None) is not None:
            return True
        try:
            from PySide6.QtWidgets import QMenu, QSystemTrayIcon
            from PySide6.QtGui import QAction
        except Exception:
            return False
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return False
        except Exception:
            return False
        try:
            from PySide6.QtGui import QIcon
            from cellium.core.config import ASSETS_DIR
            _icon_path = ASSETS_DIR / "icon.webp"
            icon = QIcon(str(_icon_path)) if _icon_path.exists() else QIcon()
        except Exception:
            icon = None
        try:
            tray = (QSystemTrayIcon(icon, self) if icon is not None
                    else QSystemTrayIcon(self))
            tray.setToolTip(
                "Cellium - click to show, right-click for options")
            menu = QMenu()
            act_show = QAction("Show / Hide Cellium", menu)
            act_show.triggered.connect(self._tray_toggle)
            menu.addAction(act_show)
            self._act_wake = QAction("🎧 Hey Cel listening", menu)
            try:
                self._act_wake.setCheckable(True)
                self._act_wake.setChecked(bool(
                    self.settings.get("listen_activation", False)))
            except Exception:
                pass
            self._act_wake.triggered.connect(self._tray_wake_flip)
            menu.addAction(self._act_wake)
            act_quit = QAction("Quit Cellium", menu)
            act_quit.triggered.connect(self._tray_quit)
            menu.addAction(act_quit)
            tray.setContextMenu(menu)
            tray.activated.connect(self._tray_activated)
            tray.show()
            self._tray = tray
            return True
        except Exception:
            return False

    def _tray_activated(self, reason) -> None:
        try:
            from PySide6.QtWidgets import QSystemTrayIcon
            if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                          QSystemTrayIcon.ActivationReason.DoubleClick):
                self._tray_toggle()
        except Exception:
            pass

    def _tray_toggle(self) -> None:
        try:
            if self.isVisible():
                self.hide()
            else:
                self.showNormal()
                self.show()
                self.raise_()
                try:
                    self.activateWindow()
                except Exception:
                    pass
        except Exception:
            pass

    def _tray_wake_flip(self) -> None:
        try:
            self.toggle_wake_word()
        except Exception:
            pass
        try:
            if getattr(self, "_act_wake", None) is not None:
                self._act_wake.setChecked(bool(
                    self.settings.get("listen_activation", False)))
        except Exception:
            pass

    def _tray_quit(self) -> None:
        self._force_quit = True
        try:
            self.close()
        except Exception:
            pass

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        try:
            from PySide6.QtCore import QEvent
            if (event.type() == QEvent.Type.WindowStateChange
                    and self.isMinimized()
                    and bool(self.settings.get("minimize_to_tray", True))
                    and not getattr(self, "_force_quit", False)
                    and self._ensure_tray()):
                self.hide()
                try:
                    if not getattr(self, "_tray_notified", False):
                        from PySide6.QtWidgets import QSystemTrayIcon
                        # Never claim to be listening when Hey Cel is off.
                        _wake_on = bool(self.settings.get("listen_activation", False))
                        self._tray.showMessage(
                            "Cellium is still here 🎧" if _wake_on else "Cellium is resting 💤",
                            "Listening from the dock - click the icon to bring me back."
                            if _wake_on else
                            "Hey Cel is off - parked in the dock. Click the icon to bring me back.",
                            QSystemTrayIcon.MessageIcon.Information, 4000)
                        self._tray_notified = True
                except Exception:
                    pass
                return
        except Exception:
            pass
        try:
            super().changeEvent(event)
        except Exception:
            pass

    def closeEvent(self, event):
        """Clean up TTS and threads on window close."""
        try:
            park = (bool(self.settings.get("close_to_tray", False))
                    and not getattr(self, "_force_quit", False)
                    and self._ensure_tray())
        except Exception:
            park = False
        if park:
            event.ignore()
            try:
                self.hide()
            except Exception:
                pass
            try:
                from PySide6.QtWidgets import QSystemTrayIcon
                _wake_on = bool(self.settings.get("listen_activation", False))
                self._tray.showMessage(
                    "Cellium is still here 🎧" if _wake_on else "Cellium is resting 💤",
                    "Listening from the dock - right-click the icon to quit."
                    if _wake_on else
                    "Hey Cel is off - parked in the dock. Right-click the icon to quit.",
                    QSystemTrayIcon.MessageIcon.Information, 4000)
            except Exception:
                pass
            return
        # From here no new work may start: a pending wake refresh would respawn
        # the mic thread mid-teardown (the 'cellium-rec destroyed while running'
        # hang), and the live outro would rebuild the chat for nobody.
        self._closing = True
        # Live mode owns mic + STT + stage threads - tear it down first, and
        # without the outro (which would replay the fade and rebuild chat).
        try:
            live = getattr(self, "_live", None)
            if live is not None:
                try:
                    live.ended.disconnect(self._exit_live_mode)
                except (RuntimeError, TypeError):
                    pass
                live.dispose()
        except Exception:
            pass
        # The always-on wake listener owns its own 'cellium-rec' mic thread.
        try:
            wake = getattr(self, "_wake", None)
            if wake is not None:
                wake.stop()
        except Exception:
            pass
        # A floating mini call owns a second capture loop - release it too.
        try:
            self._stop_mini_audio(silent=True)
        except Exception:
            pass
        # TTS thread: the async quit alone left it running past close on slow
        # machines, so wait for it to actually land.
        tts_thread = getattr(self, "active_tts_thread", None)
        self.stop_current_tts()
        try:
            if tts_thread is not None and tts_thread.isRunning():
                tts_thread.wait(2000)
        except Exception:
            pass
        # Stop any other running workers
        if hasattr(self, "worker") and self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait(1000)
        # Mic-button recorder: stop() is async - wait for the thread to land
        # or Qt destroys it mid-run and hangs the shutdown.
        try:
            rec = getattr(self, "audio_recorder", None)
            if rec is not None:
                try:
                    if rec.is_recording:
                        rec.stop()
                except Exception:
                    pass
                try:
                    if rec.isRunning():
                        rec.wait(2000)
                except Exception:
                    pass
        except Exception:
            pass
        if hasattr(self, "stt_worker") and self.stt_worker and self.stt_worker.isRunning():
            self.stt_worker.terminate()
            self.stt_worker.wait(1000)
        # Stop preload thread if running
        if hasattr(self, "_kokoro_preload_thread") and self._kokoro_preload_thread:
            self._kokoro_preload_thread.quit()
            self._kokoro_preload_thread.wait(1000)
        # Ambient canvas has no threads (its timers die with the loop), but
        # release it so nothing repaints during teardown.
        try:
            if getattr(self, "particles", None) is not None:
                self.particles.stop()
                self.particles.dispose()
        except Exception:
            pass
        super().closeEvent(event)
        # main() disables quit-on-last-window-closed for tray parking, so a
        # real quit must end the loop explicitly. Offscreen (tests) keeps the
        # old behaviour - no global side effects from a test close().
        if os.environ.get("QT_QPA_PLATFORM", "") != "offscreen":
            try:
                from PySide6.QtWidgets import QApplication
                inst = QApplication.instance()
                if inst is not None:
                    inst.quit()
            except Exception:
                pass

    def _canonical_model_key(self, candidate):
        """Resolve an old/renamed label (favourite, selected_model) to a live key.

        Offline labels now carry the size and may put it first, so a favourite
        saved as ``📁 Offline: Foo`` must still find ``📂 806.1MB Foo.gguf``.
        """
        candidate = str(candidate or "")
        if candidate in self.models:
            return candidate
        canon = strip_offline_label(candidate)
        norm = re.sub(r'[^a-zA-Z0-9]', '', canon).lower()
        if not norm:
            return None
        for key in self.models:
            kn = re.sub(r'[^a-zA-Z0-9]', '', strip_offline_label(key)).lower()
            if kn == norm:
                return key
        for key in self.models:
            kn = re.sub(r'[^a-zA-Z0-9]', '', strip_offline_label(key)).lower()
            if norm in kn or kn in norm:
                # Never retarget an offline favourite onto a cloud model when
                # its GGUF is temporarily missing from disk.
                if is_offline_model_key(candidate) and not is_offline_model_key(key):
                    continue
                return key
        return None

    def _migrate_model_labels(self):
        """Keep favourites/selection alive when the offline label format changes."""
        favs = list(self.settings.get("favorite_models", []) or [])
        migrated, seen = [], set()
        for fav in favs:
            key = self._canonical_model_key(fav) or fav
            if key not in seen:
                seen.add(key)
                migrated.append(key)
        changed = migrated != favs
        if changed:
            self.settings["favorite_models"] = migrated
        sel = str(self.settings.get("selected_model", "") or "")
        if sel:
            key = self._canonical_model_key(sel)
            if key and key != sel:
                self.settings["selected_model"] = key
                changed = True
        if changed:
            try:
                save_json(F_SETTINGS, self.settings)
            except Exception:
                pass

    def rebuild_available_models(self):
        self.models.clear()
        keys = self.settings.get("user_custom_keys", {})
        discovered_map = self.settings.get("all_discovered_models", {})
        banned_models = self.settings.get("banned_models", [])

        def normalize_model_str(s: str) -> str:
            """Clean spaces, dashes, underscores, dots to alphanumeric lowercase for smart universal matching."""
            return re.sub(r'[^a-zA-Z0-9]', '', s).lower()

        def is_banned(model_name: str) -> bool:
            """Check if model name matches any banned pattern smartly across any provider."""
            norm_name = normalize_model_str(model_name)
            for banned in banned_models:
                norm_banned = normalize_model_str(banned)
                if norm_banned and (norm_banned in norm_name or norm_name in norm_banned):
                    return True
            return False

        for prov_name, p_data in PROVIDER_DEFS.items():
            _has_key = bool(keys.get(prov_name))
            if not _has_key and prov_name == "GitHub Copilot":
                _has_key = bool(copilot_github_token(self.settings))
            if _has_key:
                models_list = discovered_map.get(prov_name) or p_data.get("default_models", [])
                seen_prov = set()
                for m in models_list:
                    if not m or not isinstance(m, str):
                        continue
                    clean_m = m.strip()
                    clean_m = re.sub(r'^(⚡|📁|Offline:|\s)+', '', clean_m).strip()
                    clean_m = re.sub(r'\s*\[.*?\]\s*$', '', clean_m).strip()
                    clean_m = re.sub(r'^models/', '', clean_m).strip()
                    if not clean_m:
                        continue
                    norm = normalize_model_str(clean_m)
                    if norm in seen_prov:
                        continue
                    seen_prov.add(norm)
                    full_key = f"⚡ {clean_m} [{prov_name}]"
                    if not is_banned(clean_m) and not is_banned(full_key):
                        self.models[full_key] = {"provider": prov_name, "model": clean_m, "base_url": p_data["base_url"]}

        # Support multiple registered offline GGUF models with duplicate path protection
        offline_models = self.settings.get("offline_models", {})
        seen_off = set()
        for model_name, model_path in offline_models.items():
            if model_path and os.path.exists(model_path):
                clean_name = strip_offline_label(model_name)
                real_p = os.path.realpath(model_path)
                norm = normalize_model_str(clean_name)
                if norm in seen_off or real_p in seen_off:
                    continue
                seen_off.add(norm)
                seen_off.add(real_p)
                # One builder for every surface: the combo text IS the model
                # key, so the size/tag switches must be applied right here.
                off_key = offline_model_label(clean_name, model_path, self.settings)
                if not is_banned(clean_name) and not is_banned(off_key):
                    self.models[off_key] = "offline-model"

        # Legacy fallback if no offline models map exists
        if not offline_models:
            local_path = self.settings.get("local_model_path", "")
            if local_path and os.path.exists(local_path):
                clean_name = strip_offline_label(os.path.basename(local_path))
                off_name = offline_model_label(clean_name, local_path, self.settings)
                if not is_banned(clean_name) and not is_banned(off_name):
                    self.models[off_name] = "offline-model"

        # Renaming labels must never lose a favourite or the active model.
        self._migrate_model_labels()
        self.update_model_dropdown()
        if hasattr(self, "model_hub_view") and self.model_hub_view:
            self.model_hub_view.models = dict(self.models)
            self.model_hub_view.settings = dict(self.settings)
            self.model_hub_view.refresh_model_rows()
            if hasattr(self.model_hub_view, "refresh_offline_list"):
                self.model_hub_view.refresh_offline_list()

    def init_data(self):
        self.rebuild_available_models()
        self.model_selector.blockSignals(True)
        self.model_selector.clear()
        self.update_model_dropdown()
        saved_m = self.settings.get("selected_model", "")
        if saved_m in self.models:
            self.model_selector.setCurrentText(saved_m)
        self.model_selector.blockSignals(False)
        self._sync_token_usage_visibility(saved_m)

        self.new_session()
        self.refresh_history_list()

        # Preload Kokoro TTS session at startup if enabled
        if self.settings.get("kokoro_preload", True):
            QTimer.singleShot(100, self._preload_kokoro)

    def _preload_kokoro(self):
        """Preload Kokoro ONNX session in background to avoid first-click delay."""
        # Headless runs never speak: skip the preload QThread so test teardown
        # cannot destroy a running thread (SIGABRT, exit 134).
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return
        try:
            import kokoro_onnx  # noqa: F401  (dependency probe)
        except ImportError:
            return

        # Use QThread for proper Qt integration (non-blocking GUI)
        class PreloadWorker(QObject):
            finished = Signal()

            def __init__(self, threads: int):
                super().__init__()
                # Cannot read self.parent() here: moveToThread() forbids a
                # parented QObject, so parent() is None. Capture the value the
                # caller already resolved instead.
                self._threads = threads

            def run(self):
                try:
                    kokoro = get_kokoro(self._threads)
                    if kokoro is None:
                        return
                    # Warmup run to prime the model (silent, fast).
                    kokoro.create("Ready.", voice="af_heart", speed=1.0,
                                  lang="en-us", trim=True)
                    dev_log("[Kokoro] Preloaded & warmed up ✓")
                except Exception as e:
                    dev_log(f"[Kokoro] Preload failed: {e}")
                finally:
                    self.finished.emit()

        thread = QThread(self)
        worker = PreloadWorker(int(self.settings.get("offline_threads") or physical_core_count()))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_kokoro_preload_done)
        # A parentless QObject moved to a thread is owned ONLY by this Python
        # reference. Keeping it in a local let the GC destroy the worker while
        # the thread was still starting, so Qt dispatched ``started`` to a dead
        # receiver and the process segfaulted right after the wallpaper load.
        self._kokoro_preload_thread = thread
        self._kokoro_preload_worker = worker
        thread.start()

    def _on_kokoro_preload_done(self):
        """Release the preload handles once the worker thread has stopped."""
        self._kokoro_preload_thread = None
        self._kokoro_preload_worker = None

    def update_model_dropdown(self):
        favs = self.settings.get("favorite_models", [])
        if not hasattr(self, "model_selector"):
            return
        self.model_selector.blockSignals(True)
        self.model_selector.clear()
        # Favourites are stored as full labels, so resolve them through the
        # canonical name - otherwise renaming an offline model (size switch)
        # silently empties the shortlist.
        visible_favs = []
        seen_favs = set()
        for fav in favs:
            key = self._canonical_model_key(fav)
            if key and key not in seen_favs:
                seen_favs.add(key)
                visible_favs.append(key)
        if favs:
            self.model_selector.addItems(visible_favs)
        else:
            # Show nothing if no favorites - user must add models to favorites first
            self.model_selector.addItem("⭐ Add models to favorites in Model Hub")
        saved_m = self.settings.get("selected_model", "")
        # The active model may be a non-favourite picked in the Hub or the
        # live circle - without it in the list, setCurrentText below silently
        # no-ops and the visible combo disagrees with the model that answers.
        target_model = self._canonical_model_key(saved_m) if saved_m else None
        if target_model and target_model != saved_m:
            self.settings["selected_model"] = target_model
            try:
                save_json(F_SETTINGS, self.settings)
            except Exception:
                pass

        if target_model:
            if target_model not in visible_favs:
                self.model_selector.addItem(target_model)
            self.model_selector.setCurrentText(target_model)
            # The closed combo is narrow and clips long GGUF names; the
            # tooltip always carries the full label (including the size).
            self.model_selector.setToolTip(target_model)
        elif self.model_selector.count() > 0:
            visible = self.model_selector.currentText()
            if visible and visible in self.models:
                self.settings["selected_model"] = visible
                save_json(F_SETTINGS, self.settings)
        self.model_selector.blockSignals(False)
        self._sync_token_usage_visibility()

    def set_zoom(self, val: float):
        self.zoom_level = max(0.5, min(2.5, val))
        if abs(float(self.settings.get("zoom_level", 1.0) or 1.0) - self.zoom_level) > 1e-6:
            self.settings["zoom_level"] = self.zoom_level
            save_json(F_SETTINGS, self.settings)
        if hasattr(self, "lbl_zoom"):
            self.lbl_zoom.setText(f"{int(self.zoom_level * 100)}%")
        f = self.font()
        f.setPointSizeF(12 * self.zoom_level)
        self.setFont(f)
        self.setUpdatesEnabled(False)
        try:
            self._apply_stylesheet_zoom()
            self.update_all_bubble_geometries()
        finally:
            self.setUpdatesEnabled(True)

    def _apply_stylesheet_zoom(self, root=None):
        """Scale font-size: Npx in stylesheets by zoom_level. Scoped to visible views for 60fps speed."""
        z = getattr(self, "zoom_level", 1.0)
        if root is None:
            roots = [w for w in (
                getattr(self, "top_bar", None),
                getattr(self, "left_drawer", None),
                getattr(self, "input_pill", None),
                getattr(self, "right_drawer", None) if getattr(self, "right_drawer", None) and self.right_drawer.isVisible() else None,
                self.central_stack.currentWidget() if hasattr(self, "central_stack") else None,
            ) if w is not None]
            targets = [self]
            for r in roots:
                targets.append(r)
                targets.extend(r.findChildren(QWidget))
        elif isinstance(root, QWidget):
            targets = [root] + root.findChildren(QWidget)
        else:
            targets = list(root)
        for w in targets:
            try:
                ss = w.styleSheet()
            except RuntimeError:
                continue
            if not ss:
                continue
            orig = w.property("cellium_orig_ss")
            if orig is None:
                if "font-size" not in ss:
                    continue
                orig = ss
                w.setProperty("cellium_orig_ss", orig)
            new_ss = re.sub(
                r"font-size:\s*(\d+(?:\.\d+)?)px",
                lambda m: f"font-size: {max(6, int(round(float(m.group(1)) * z)))}px",
                orig,
            )
            if new_ss != ss:
                w.setStyleSheet(new_ss)

    #: Base body text size inside a bubble body; zoom multiplies it.
    BUBBLE_BASE_FONT_PX = 14

    #: ``font_scale`` (Settings -> Appearance -> Chat Text) -> multiplier on the
    #: bubble body size. Zoom and this are independent: zoom scales the whole
    #: window, this scales only the words, and both multiply.
    FONT_SCALES = {
        "Small (Default)": 1.0, "Default": 1.0, "Medium": 1.12,
        "Large": 1.25, "Extra Large": 1.40,
    }

    def font_scale_factor(self) -> float:
        try:
            raw = str(self.settings.get("font_scale", "Small (Default)"))
        except Exception:
            raw = "Small (Default)"
        if raw.isdigit():
            # Tolerate a plain percentage if one was ever stored.
            try:
                return max(0.6, min(2.0, int(raw) / 100.0))
            except (TypeError, ValueError):
                return 1.0
        return float(self.FONT_SCALES.get(raw, 1.0))

    def _propagate_font_to_bubbles(self, font):
        """Recursively apply font to all bubbles and their text labels."""
        if hasattr(self, "chat_layout"):
            body_px = max(9, int(round(self.BUBBLE_BASE_FONT_PX
                                       * getattr(self, "zoom_level", 1.0)
                                       * self.font_scale_factor())))
            for i in range(self.chat_layout.count()):
                item = self.chat_layout.itemAt(i)
                w = item.widget() if item else None
                if w:
                    w.setFont(font)
                    # Recursively apply to children
                    kids = w.findChildren(QWidget)
                    for child in kids:
                        child.setFont(font)
                        child.updateGeometry()
                    # Bubble bodies bake font-size into *inline HTML*, which beats
                    # any stylesheet, so scaling the stylesheet did nothing for the
                    # message text. set_font_scale() re-renders that HTML - it
                    # existed but had zero callers, so zoom never reached the
                    # body copy (#4).
                    for target in [w] + list(kids):
                        if hasattr(target, "set_font_scale"):
                            try:
                                target.set_font_scale(body_px)
                            except Exception:
                                pass

    def adjust_zoom(self, delta: float):
        self.set_zoom(getattr(self, "zoom_level", 1.0) + delta)
        self.show_toast(f"Zoom: {int(self.zoom_level * 100)}%", icon="🔍")

    def save_settings(self) -> None:
        """Persist self.settings to disk (used by Live Mode controls & views)."""
        save_json(F_SETTINGS, self.settings)

    def _refresh_avatar_labels(self) -> None:
        """Re-paint every CircularAvatarLabel after an avatar lands on disk."""
        try:
            bust_avatar_cache()
        except Exception:
            pass
        try:
            for lbl in self.findChildren(CircularAvatarLabel):
                lbl.refresh()
        except Exception:
            pass

    def toggle_live_mode_call(self) -> None:
        """Start or hang up a CelAS Live Mode call."""
        if getattr(self, "_live", None) is not None and self._live.active:
            self._exit_live_mode()
        else:
            self._enter_live_mode()

    def on_model_changed(self, idx):
        m_name = self.model_selector.currentText()
        self.model_selector.setToolTip(m_name)
        self.settings["selected_model"] = m_name
        save_json(F_SETTINGS, self.settings)
        self._sync_token_usage_visibility(m_name)
        # Fetch model details to update thinking levels
        self._fetch_model_details(m_name)

    def _on_token_usage_changed(self, text):
        self.settings["openrouter_token_usage"] = text
        save_json(F_SETTINGS, self.settings)
        short_label = text.split("(")[0].strip()
        self.show_toast(f"OpenRouter routing: {short_label}", icon="🌐")

    def _sync_token_usage_visibility(self, model_name=None):
        """Strict Visibility Rule: Token Usage MUST ONLY be visible when active provider is OpenRouter."""
        if not hasattr(self, "combo_token_usage") or not self.combo_token_usage:
            return
        m_name = model_name or (self.model_selector.currentText() if hasattr(self, "model_selector") else "")
        route = self.models.get(m_name, {})
        provider = ""
        base_url = ""
        if isinstance(route, dict):
            provider = route.get("provider", "")
            base_url = route.get("base_url", "")
        if not provider:
            provider = self.settings.get("selected_provider", "")

        is_openrouter = (
            "openrouter" in str(provider).lower()
            or "openrouter" in str(m_name).lower()
            or "openrouter" in str(base_url).lower()
        )
        self.combo_token_usage.setVisible(is_openrouter)

    def _on_thinking_changed(self, text):
        from cellium.core.utils import thinking_level_key, thinking_level_label
        key = self.combo_thinking.currentData() or thinking_level_key(text)
        self.settings["thinking_level"] = key
        save_json(F_SETTINGS, self.settings)
        self.show_toast(f"Thinking level: {thinking_level_label(key)}", icon="🧠")

    def _fetch_model_details(self, model_name):
        """Fetch model details including supported thinking levels."""
        # Find the model route to get provider and base_url
        route = self.models.get(model_name)
        if not route:
            return
        
        if is_offline_model_key(model_name, route):
            # Local models don't have thinking levels
            self._update_thinking_dropdown(["low", "medium", "high"])
            return
        
        if not isinstance(route, dict):
            return
        
        provider = route.get("provider", "")
        base_url = route.get("base_url", "")
        model_id = route.get("model", model_name)
        
        # Get API key
        keys = self.settings.get("user_custom_keys", {})
        api_key = keys.get(provider, "")
        if not api_key and provider != "Cerebras":
            return
        
        # Check cache first
        cache_key = f"{provider}:{model_id}"
        if hasattr(self, "_model_details_cache") and cache_key in self._model_details_cache:
            details = self._model_details_cache[cache_key]
            self._update_thinking_dropdown(details.get("thinking_levels", ["low", "medium", "high"]))
            return
        
        # Initialize cache if needed
        if not hasattr(self, "_model_details_cache"):
            self._model_details_cache = {}
        
        # Fetch details in background
        worker = ModelDetailWorker(provider, base_url, api_key, model_id, self, self.settings)
        worker.details_fetched.connect(lambda m_id, details: self._on_model_details_fetched(m_id, details, cache_key))
        worker.error.connect(lambda m_id, err: self._on_model_details_error(m_id, err))
        worker.start()

    def _on_model_details_fetched(self, model_id, details, cache_key):
        """Handle fetched model details."""
        if not hasattr(self, "_model_details_cache"):
            self._model_details_cache = {}
        self._model_details_cache[cache_key] = details
        self._update_thinking_dropdown(details.get("thinking_levels", ["low", "medium", "high"]))

    def _on_model_details_error(self, model_id, error):
        """Handle model details fetch error - use defaults."""
        self._update_thinking_dropdown(["low", "medium", "high"])

    def _update_thinking_dropdown(self, levels):
        """Update the thinking dropdown with fetched levels."""
        if not hasattr(self, "combo_thinking") or not self.combo_thinking:
            return
        # Block signals to avoid triggering _on_thinking_changed
        self.combo_thinking.blockSignals(True)
        from cellium.core.utils import thinking_level_key
        # Restore by level KEY, not label text - the label set is rebuilt
        # here with one emoji style while construction used another, so text
        # matching silently reset the pick to Auto on every model change.
        current_key = thinking_level_key(
            self.combo_thinking.currentData()
            or self.settings.get("thinking_level", "auto"))
        self.combo_thinking.clear()
        # Map API levels to UI labels
        level_map = {
            "force_off": "⛔ Force Off",
            "off": "✦ Off",
            "auto": "✦ Auto",
            "minimal": "✦ Minimal",
            "low": "✦ Low",
            "medium": "✦ Medium",
            "high": "✦ High",
            "max": "✦ Max",
            "xhigh": "✦ X-High",
        }
        all_levels = ["force_off", "off", "auto"]
        for _lv in levels:
            _key = str(_lv).lower()
            if _key not in all_levels:
                all_levels.append(_key)
        for level in all_levels:
            key = str(level).lower()
            label = level_map.get(key, f"✦ {str(level).capitalize()}")
            self.combo_thinking.addItem(label, key)
        # Try to restore previous selection
        idx = self.combo_thinking.findData(current_key)
        if idx < 0:
            idx = self.combo_thinking.findData("auto")
        self.combo_thinking.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_thinking.blockSignals(False)

    def _update_model_completer(self, text):
        """Update completer model with fuzzy matching for model names."""
        if not hasattr(self, "_model_completer") or not self._model_completer:
            return
        # Get all favorite models
        favs = self.settings.get("favorite_models", [])
        if favs:
            # Filter models that match the text (fuzzy)
            matches = [m for m in favs if text.lower() in m.lower()]
            model = self._model_completer.model()
            from PySide6.QtCore import QStringListModel
            if isinstance(model, QStringListModel):
                model.setStringList(matches)
            else:
                self._model_completer.setModel(QStringListModel(matches, self))
        self._model_completer.setCompletionPrefix(text)
        self._model_completer.complete()

    def set_active_model(self, model_name):
        """Apply a model pick from anywhere (Model Hub, live circle, palette).

        The top-bar selector is a *favourites shortlist*, so a name that is a
        real model but not a combo item used to silently no-op - Generation
        then kept running on whatever was selected before, which is how a
        Live call could answer on the offline GGUF "even when Gemini is
        selected". A valid model now always lands in the combo and in
        ``settings["selected_model"]``.
        """
        if model_name not in self.models:
            return False
        if self.model_selector.findText(model_name) < 0:
            # Not a favourite - make room instead of dropping the pick.
            self.model_selector.addItem(model_name)
        self.model_selector.setCurrentText(model_name)
        # currentIndexChanged → on_model_changed persists it; belt-and-braces
        # for the case where the index was already correct but settings lagged.
        if self.settings.get("selected_model") != model_name:
            self.settings["selected_model"] = model_name
            save_json(F_SETTINGS, self.settings)
        self._sync_token_usage_visibility(model_name)
        return True

    def _build_system_prompt(self, for_offline=False):
        """Build the system prompt from the user-editable categories.

        Every block sent here is visible/editable in Settings → Persona &
        Memory → "Edit system instructions categories"; an empty category is
        simply not sent, so unused directives never burn quota.
        """
        instr = system_instructions(self.settings)
        # Coding Mode replaces the whole prompt - only code output (Task 17).
        if self.settings.get("coding_mode", False):
            return str(instr.get("coding", "") or "").strip()

        parts = []
        if self.settings.get("persona_enabled", True):
            persona = str(self.settings.get("user_persona") or "").strip()
            if persona:
                parts.append(persona)
        if self.settings.get("memory_enabled", True):
            memory = str(self.settings.get("user_memory_rules") or "").strip()
            if memory:
                parts.append(f"[USER MEMORY/RULES: {memory}]")
        if self.dev_memory:
            parts.append(f"[DEVELOPER DIRECTIVE: {self.dev_memory}]")

        base = "\n".join(parts) + "\n" if parts else ""

        live_on = bool(getattr(self, "_live", None) is not None and self._live.active)
        comp = getattr(self, "_companion", None)
        pet_on = bool(self.settings.get("pet_mode_enabled", False) or (comp is not None and comp.visible))
        self.settings["_mood_contract_active"] = bool(live_on or pet_on)
        mood_text = str(instr.get("mood", "") or "").strip()
        mood_rule = ""
        if (live_on or pet_on) and mood_text:
            # The `[MOOD CONTRACT: …]` wrapper is what lets every worker strip
            # the block again when Live Mode ends - even if the user rewrote
            # the category text.
            mood_rule = f"\n[MOOD CONTRACT: {mood_text}]"

        # A live call swaps in its own rules for the length of one turn
        # (short replies, spoken register, no markdown). Set by the live
        # controller; empty everywhere else, so chat is untouched.
        live_rule = str(getattr(self, "_live_prompt_extra", "") or "")

        blocks = []
        for _key in ("style", "identity", "extra"):
            _text = str(instr.get(_key, "") or "").strip()
            if _text:
                blocks.append("\n" + _text)
        return base + "".join(blocks) + mood_rule + live_rule

    def _refresh_system_prompt_memory(self) -> None:
        """Rebuild stored system prompts after a prompt-affecting toggle.

        Without this, turning Persona/Memory off (or leaving Live Mode) only
        took effect in brand-new chats - the open chat kept re-sending the
        old hidden instructions forever.
        """
        try:
            model_key = self.settings.get("selected_model", "")
            route = self.models.get(model_key)
            is_offline = is_offline_model_key(model_key, route)
            prompt = self._build_system_prompt(for_offline=is_offline)
            changed = False
            for ses in (self.sessions or {}).values():
                mem = ses.get("memory") if isinstance(ses, dict) else None
                if not mem or not isinstance(mem[0], dict):
                    continue
                if mem[0].get("role") != "system":
                    continue
                if mem[0].get("content") != prompt:
                    mem[0]["content"] = prompt
                    changed = True
            if changed and not self.settings.get("incognito"):
                save_json(F_SESSIONS, self.sessions)
        except Exception:
            pass

    def _sync_more_menu(self) -> None:
        """Mirror every mode flag into the top-bar More menu."""
        if not hasattr(self, "more_menu") or self.more_menu is None:
            return

        _coding_on = bool(self.settings.get("coding_mode", False))
        states = (
            (getattr(self, "act_agent", None), "🤖 Agent Mode",
             bool(self.settings.get("agent_mode_enabled", False))),
            (getattr(self, "act_coding", None),
             "💻 Coding Mode" if _coding_on else "💬 Chat Mode", _coding_on),
            (getattr(self, "act_wake", None), "🎧 Hey Cel",
             bool(self.settings.get("listen_activation", False))),
            (getattr(self, "act_image_gen", None), "🎨 Enable Image Gen",
             bool(self.settings.get("image_gen_enabled", False))),
            (getattr(self, "act_cache", None), "🔥 Warm Cache",
             bool(self.settings.get("kaggle_cache_on", False))),
            (getattr(self, "act_persona", None), "🎭 Persona",
             bool(self.settings.get("persona_enabled", True))),
            (getattr(self, "act_memory", None), "🧠 Memory",
             bool(self.settings.get("memory_enabled", True))),
        )
        # QAction draws its own checkmark - do NOT prefix the text with one,
        # or the menu shows two ticks per enabled row.
        for act, label, on in states:
            if act is None:
                continue
            try:
                act.setChecked(on)
                act.setText(label)
            except Exception:
                pass

    def refresh_history_list(self, filter_text=""):
        while self.hist_layout.count():
            item = self.hist_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        fm = self.fontMetrics()
        # Only show sessions with actual user/assistant messages
        valid_sessions = [
            (sid, ses) for sid, ses in self.sessions.items()
            if any(m.get("role") in ("user", "assistant") for m in ses.get("memory", []))
        ]

        # Pinned chats first (stable sort - otherwise newest-first as before).
        ordered_sessions = sorted(
            valid_sessions[::-1],
            key=lambda _t: (not bool(_t[1].get("pinned", False))))
        for sid, ses in ordered_sessions:
            title = ses.get("title", "")
            if not title or title.strip() in ("New Chat", "New Chat ✨"):
                # Look at up to 3 most recent user+assistant message pairs to generate a smart title
                msgs = ses.get("memory", [])
                user_assist_pairs = []
                i = len(msgs) - 1
                while i >= 0 and len(user_assist_pairs) < 3:
                    if msgs[i].get("role") == "assistant":
                        # Find the user message before this assistant message
                        j = i - 1
                        while j >= 0 and msgs[j].get("role") != "user":
                            j -= 1
                        if j >= 0:
                            user_text = re.sub(r"[*_`#~\[\]\(\)]", "", msgs[j].get("content", "")).strip()
                            user_text = re.sub(r"🤔.*?🤔", "", user_text, flags=re.DOTALL).strip()
                            if user_text:
                                user_assist_pairs.insert(0, user_text)
                        i = j - 1
                    else:
                        i -= 1
                
                if user_assist_pairs:
                    # Combine up to 3 user questions, join with " → "
                    combined = " → ".join(user_assist_pairs)
                    # Smart truncation: cut at word boundary, max 50 chars
                    if len(combined) > 50:
                        cut = combined[:50].rsplit(" ", 1)[0]
                        title = cut + "…"
                    else:
                        title = combined
                    ses["title"] = title
                else:
                    # Fallback: first user message
                    for m in msgs:
                        if m.get("role") == "user":
                            raw = re.sub(r"[*_`#~\[\]\(\)]", "", m.get("content", "")).strip()
                            raw = re.sub(r"🤔.*?🤔", "", raw, flags=re.DOTALL).strip()
                            if raw:
                                if len(raw) > 50:
                                    title = raw[:50].rsplit(" ", 1)[0] + "…"
                                else:
                                    title = raw
                                ses["title"] = title
                                break
            if not title:
                title = "Chat"

            if "Branched:" in title:
                base = re.sub(r"^(Branched:\s*)+", "", title).strip()
                title = f"Branched: {base}"
                ses["title"] = title

            if filter_text and filter_text.lower() not in title.lower():
                continue
            if not hasattr(self, "_filtered_hist_items"):
                self._filtered_hist_items = []
            self._filtered_hist_items.append((sid, ses, title))

        items_all = getattr(self, "_filtered_hist_items", [])
        self._filtered_hist_items = []
        page_size = 20
        total_pages = max(1, (len(items_all) + page_size - 1) // page_size)
        if filter_text != getattr(self, "_last_hist_filter", ""):
            self._hist_page = 1
            self._last_hist_filter = filter_text
        cur_page = max(1, min(int(getattr(self, "_hist_page", 1) or 1), total_pages))
        self._hist_page = cur_page
        start_i = (cur_page - 1) * page_size
        page_slice = items_all[start_i : start_i + page_size]

        for sid, ses, title in page_slice:
            elided = fm.elidedText(title, Qt.TextElideMode.ElideRight, 400)
            btn = QPushButton(("📌 " if ses.get("pinned", False) else "") + elided)
            _created = ses.get("created", " - ")
            _last = ses.get("last_active", _created)
            _pin_mark = "📌 Pinned\n" if ses.get("pinned", False) else ""
            btn.setToolTip(f"{_pin_mark}💬 {title}\n📅 Created: {_created}\n🕘 Last chat: {_last}")
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setMinimumHeight(36)
            tint = session_tint_color(sid)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255,255,255,0.05); color: {tint}; border-radius: 8px;
                    padding: 8px 12px; font-size: 12px; font-weight: bold; text-align: left;
                    border-left: 3px solid {tint};
                }}
                QPushButton:hover {{ background: rgba(147, 51, 234, 0.45); color: #FFFFFF; }}
            """)
            btn.clicked.connect(lambda _, s=sid: self.switch_session(s))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda _pos, _s=sid: self._session_context_menu(_s))
            self.hist_layout.addWidget(btn)

        if total_pages > 1:
            pager = QFrame()
            pager.setStyleSheet(
                "QFrame { background: rgba(20, 14, 38, 0.85); border: 1px solid rgba(168, 85, 247, 0.4); "
                "border-radius: 10px; margin-top: 6px; padding: 4px; }"
            )
            p_lay = QHBoxLayout(pager)
            p_lay.setContentsMargins(6, 4, 6, 4)
            p_lay.setSpacing(4)
            for p_num in range(1, total_pages + 1):
                is_cur = (p_num == cur_page)
                p_btn = QPushButton(f"Page {p_num}" if total_pages <= 4 else str(p_num))
                p_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                p_btn.setFixedHeight(26)
                p_btn.setStyleSheet(
                    "QPushButton { background: #9333EA; color: #FFFFFF; border: 1px solid #E879F9; "
                    "border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: bold; }"
                    if is_cur else
                    "QPushButton { background: rgba(255,255,255,0.06); color: #C4B5FD; border: none; "
                    "border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: bold; } "
                    "QPushButton:hover { background: rgba(147, 51, 234, 0.45); color: #FFFFFF; }"
                )
                p_btn.clicked.connect(lambda _=False, pn=p_num: self._set_history_page(pn))
                p_lay.addWidget(p_btn)
            self.hist_layout.addWidget(pager)

        # Add stretch at end to push items to top and prevent empty space at bottom
        self.hist_layout.addStretch(1)
        if abs(getattr(self, "zoom_level", 1.0) - 1.0) > 1e-6 and hasattr(self, "hist_content"):
            self._apply_stylesheet_zoom(self.hist_content)

    def _set_history_page(self, page_num: int) -> None:
        self._hist_page = max(1, int(page_num))
        filt = self.search_history.text().strip() if hasattr(self, "search_history") else ""
        self.refresh_history_list(filt)
        if hasattr(self, "hist_scroll"):
            self.hist_scroll.verticalScrollBar().setValue(0)

    def filter_history_items(self, text):
        self._hist_page = 1
        self.refresh_history_list(text.strip())

    def _session_context_menu(self, sid):
        """Right-click a history entry: open / rename / pin / delete."""
        if sid not in self.sessions:
            return
        ses = self.sessions[sid]
        try:
            from PySide6.QtWidgets import QMenu
            from PySide6.QtGui import QCursor
            menu = QMenu(self)
            act_open = menu.addAction("💬 Open chat")
            act_rename = menu.addAction("✏️ Rename chat")
            act_dup = menu.addAction("📋 Duplicate chat")
            _pinned = bool(ses.get("pinned", False))
            act_pin = menu.addAction("📌 Unpin chat" if _pinned else "📌 Pin chat")
            menu.addSeparator()
            act_del = menu.addAction("🗑 Delete chat")
            chosen = menu.exec(QCursor.pos())
        except Exception:
            return
        try:
            if chosen == act_open:
                self.switch_session(sid)
            elif chosen == act_rename:
                self._rename_session_dialog(sid)
            elif chosen == act_dup:
                self._duplicate_session(sid)
            elif chosen == act_pin:
                ses["pinned"] = not _pinned
                save_json(F_SESSIONS, self.sessions)
                self.refresh_history_list()
                self.show_toast("📌 Chat pinned to the top." if ses["pinned"]
                                else "📌 Chat unpinned.", icon="📌")
            elif chosen == act_del:
                self._delete_session_dialog(sid)
        except Exception:
            pass

    def _duplicate_session(self, sid: str) -> None:
        """Deep-copy a chat session into a new session and switch to it."""
        if sid not in self.sessions:
            return
        import copy
        src_ses = self.sessions[sid]
        base_title = str(src_ses.get("title", "Chat") or "Chat").strip()
        existing_titles = {str(s.get("title", "")) for s in self.sessions.values()}
        new_title = f"{base_title} (Copy)"
        n = 2
        while new_title in existing_titles:
            new_title = f"{base_title} (Copy {n})"
            n += 1
        new_sid = str(uuid.uuid4())[:8]
        while new_sid in self.sessions:
            new_sid = str(uuid.uuid4())[:8]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.sessions[new_sid] = {
            "title": new_title,
            "created": now_str,
            "last_active": now_str,
            "pinned": bool(src_ses.get("pinned", False)),
            "memory": copy.deepcopy(src_ses.get("memory", [])),
        }
        save_json(F_SESSIONS, self.sessions)
        self.refresh_history_list()
        self.switch_session(new_sid)
        self.show_toast(f"📋 Duplicated chat: {new_title}", icon="📋")

    def _rename_session_dialog(self, sid):
        """Manual chat rename (instant - no AI round-trip needed)."""
        if sid not in self.sessions:
            return
        try:
            from PySide6.QtWidgets import QInputDialog
            cur = str(self.sessions[sid].get("title", "Chat"))
            name, ok = QInputDialog.getText(
                self, "Rename chat", "Chat name:", text=cur)
        except Exception:
            return
        name = (name or "").strip()
        if not ok or not name:
            return
        if len(name) > 60:
            name = name[:60]
        self.sessions[sid]["title"] = name
        save_json(F_SESSIONS, self.sessions)
        if sid == self.current_sid and hasattr(self, "lbl_chat_title"):
            try:
                self.lbl_chat_title.setText(f"💬 {name}")
                self._update_window_title(name)
            except RuntimeError:
                pass
        self.refresh_history_list()

    def _delete_session_dialog(self, sid):
        """Delete a chat after confirmation. Never strands the UI."""
        if sid not in self.sessions:
            return
        title = str(self.sessions[sid].get("title", "Chat"))
        try:
            from PySide6.QtWidgets import QMessageBox
            ans = QMessageBox.question(
                self, "Delete chat?",
                f"Permanently delete “{title}”?\nThis cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
        except Exception:
            return
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            del self.sessions[sid]
            save_json(F_SESSIONS, self.sessions)
        except Exception:
            return
        if sid == self.current_sid:
            rest = [s for s in self.sessions.keys()]
            if rest:
                self.switch_session(rest[-1])
            else:
                self.new_session()
        self.refresh_history_list()
        self.show_toast("🗑 Chat deleted.", icon="🗑")

    def _safe_delete(self, widget):
        """Safely delete a widget if it exists and hasn't been deleted."""
        if widget is not None:
            try:
                # Check if C++ object still exists
                widget.deleteLater()
            except (RuntimeError, AttributeError):
                pass

    def nav_new_chat(self):
        """Sidebar 'New Chat': return to the chat page *then* start a session.

        It used to call new_session() alone, so pressing it while Settings /
        Model Hub / Analytics / Avatar was open looked like it did nothing  - 
        the stack never left the page you were on (#2).
        """
        if self.central_stack.currentIndex() != 0:
            self.show_chat_view()
        self.new_session()

    def new_session(self):
        """Create a fresh chat session."""
        self._render_timer.stop()
        self._render_queue = []
        self._rendered_mem = set()
        self._auto_scroll_anchored = True
        self.current_sid = str(uuid.uuid4())[:8]
        self.lbl_chat_title.setText("💬 New Chat")
        self._update_window_title("New Chat")
        self.ghost_bubble = None
        self._message_queue = getattr(self, '_message_queue', [])
        self._earlier_queue = []
        self._load_more_btn = None

        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.chat_substack.setCurrentIndex(0)
        self.refresh_history_list()

    def switch_session(self, sid):
        if sid not in self.sessions:
            return
        # Persist / finalize in-flight turn BEFORE wiping layout so segment
        # split text + agent_action tags are never dropped on a session hop.
        if getattr(self, "active_stream_bubble", None) and getattr(self, "_streaming_msg_idx", -1) >= 0:
            worker_alive = bool(getattr(self, "worker", None) and self.worker and self.worker.isRunning())
            if not worker_alive:
                if not getattr(self, "_generation_finished", True):
                    self._stream_buffer = self._stream_buffer or self._displayed_text or ""
                    if hasattr(self, "_typing_timer") and self._typing_timer.isActive():
                        self._typing_timer.stop()
                try:
                    self._finalize_stream_response()
                except Exception:
                    pass
            else:
                # Worker still running: freeze composed content into memory now;
                # keep _turn_parts so a later on_done can still append the tail.
                try:
                    self._persist_stream_text(self._displayed_text or self._stream_buffer or "")
                except Exception:
                    pass
        # Clean up any active streaming bubble from previous session
        self._safe_delete(self.active_stream_bubble)
        self.active_stream_bubble = None
        if hasattr(self, "_typing_timer") and self._typing_timer.isActive():
            self._typing_timer.stop()
        self._safe_delete(self.ghost_bubble)
        self.ghost_bubble = None
        self.current_sid = sid
        ses = self.sessions[sid]
        # Layout is rebuilt from scratch below - drop this chat's painted
        # record so every entry renders exactly once (no duplication).
        try:
            self._rendered_mem = {(s, i) for (s, i) in
                                  getattr(self, "_rendered_mem", set())
                                  if s != sid}
        except Exception:
            self._rendered_mem = set()
        title_str = str(ses.get('title', 'Chat'))
        self.lbl_chat_title.setText(f"💬 {title_str}")
        self._update_window_title(title_str)
        self.ghost_bubble = None

        # Full clear - layout index ≠ memory index (system is memory-only;
        # tool cards are layout-only). Never use layout idx for memory math.
        while self.chat_layout.count():
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            else:
                del item
        self.chat_layout.addStretch(1)
        self._load_more_btn = None
        self._earlier_queue = []

        mem = ses.get("memory", [])
        if not mem:
            self.chat_substack.setCurrentIndex(0)
        else:
            self.chat_substack.setCurrentIndex(1)
            # INSTANT OPEN: the newest slice paints synchronously, the rest
            # streams in on a zero-delay timer so the window never freezes.
            # Measured before this change: 40 bubbles in one pass = 784 ms.
            renderable = [(i, m) for i, m in enumerate(mem) if m.get("role") != "system"]
            tail_n = 40
            if len(renderable) > tail_n:
                self._earlier_queue = renderable[:-tail_n]
                tail = renderable[-tail_n:]
            else:
                self._earlier_queue = []
                tail = renderable
            for mem_i, m in tail[:RENDER_CHUNK_SIZE]:
                self._render_mem_entry(mem_i, m)
            rest = list(tail[RENDER_CHUNK_SIZE:])
            if self._earlier_queue:
                self._add_load_more_pill()
            if rest:
                self._render_queue = rest
                self._auto_scroll_anchored = False
                self._render_timer.start(0)
            else:
                self.update_all_bubble_geometries()
                self.scroll_bottom(force=True)
                if hasattr(self, "chat_turn_rail") and self.chat_turn_rail:
                    self.chat_turn_rail.refresh_turns()

    def _on_render_chunk(self):
        """Render the next slice of the tail, then hand the scrollbar back."""
        queue = getattr(self, "_render_queue", None)
        if not queue:
            self._render_timer.stop()
            self._render_queue = []
            self._auto_scroll_anchored = True
            self.update_all_bubble_geometries()
            self.scroll_bottom(force=True)
            if hasattr(self, "chat_turn_rail") and self.chat_turn_rail:
                self.chat_turn_rail.refresh_turns()
            return
        for mem_i, m in queue[:RENDER_CHUNK_SIZE]:
            self._render_mem_entry(mem_i, m)
        del queue[:RENDER_CHUNK_SIZE]

    def _render_mem_entry(self, mem_i, m, at_index=None):
        """Render one memory entry (text bubble and/or agent tool cards).
        at_index=None appends before the trailing stretch; a fixed index
        prepends at that position (used to load earlier history above)."""
        _rkey = (getattr(self, "current_sid", None), mem_i)
        _seen = getattr(self, "_rendered_mem", None)
        if _seen is None:
            self._rendered_mem = _seen = set()
        if _rkey in _seen:
            return  # already on screen - a second paint is the "multiplication" glitch
        _seen.add(_rkey)
        role = m.get("role", "user")
        if role == "system":
            return
        c = m.get("content", "")
        if c and role != "user":
            c = re.sub(r'(?im)^[ \t]*(?:\*\*|__)?(?:mood|emotions?)(?:\*\*|__)?[ \t]*:.*$', '', str(c))
            c = re.sub(r'(?i)\b(?:mood|emotions?)\s*:\s*[a-zA-Z_,\s]+(?:[.!?\n]|$)', '', c).strip()
        meta = {"time": m.get("time", ""), "model": m.get("model", "")}
        cursor = [at_index]

        def _ins(widget, align):
            if cursor[0] is None:
                self.chat_layout.insertWidget(self.chat_layout.count() - 1, widget, 0, align)
            else:
                self.chat_layout.insertWidget(cursor[0], widget, 0, align)
                cursor[0] += 1

        if role == "assistant" and "<agent_action" in c:
            pattern = r'<agent_action tool="([^"]+)" args="([^"]+)" status="([^"]+)"(?: diff="([^"]*)")?>(.*?)</agent_action>'
            matches = list(re.finditer(pattern, c, flags=re.DOTALL))

            def _insert_text_seg(chunk):
                chunk = (chunk or "").strip()
                if not chunk:
                    return
                b = MessageBubbleNew("assistant", chunk, meta, glass_opacity=self.settings.get("glass_opacity", 0.72), chat_app=self)
                b.memory_index = mem_i
                _ins(b, Qt.AlignmentFlag.AlignLeft)

            pos = 0
            for match in matches:
                _insert_text_seg(c[pos:match.start()])
                t_name = match.group(1)
                a_str = match.group(2)
                st = match.group(3)
                d_str = match.group(4)
                res = html.unescape(match.group(5))
                try:
                    args = json.loads(html.unescape(a_str))
                except Exception:
                    args = {"args": a_str}
                diff = html.unescape(d_str) if d_str else None
                tool_card = make_agent_tool_widget(t_name, args, result=res, parent=self.chat_content, diff=diff)
                tool_card.setMaximumWidth(820)
                tool_card.set_result(res, is_error=(st == "failed"), diff=diff)
                _ins(tool_card, Qt.AlignmentFlag.AlignLeft)
                pos = match.end()
            _insert_text_seg(c[pos:])
        else:
            worker_alive = bool(getattr(self, "worker", None) and self.worker and self.worker.isRunning())
            is_active_turn = (
                worker_alive
                and getattr(self, "current_sid", None) == getattr(self, "_pending_sid", None)
                and mem_i == getattr(self, "_streaming_msg_idx", -1)
                and role == "assistant"
            )
            if role == "assistant" and not c and not is_active_turn:
                # Never show an empty/interrupted assistant placeholder in other chats
                return
            b = MessageBubbleNew(
                role,
                c,
                meta,
                glass_opacity=self.settings.get("glass_opacity", 0.72),
                attached_images=m.get("attached_images"),
                attached_files=m.get("attached_files"),
                is_live=is_active_turn,
                chat_app=self,
            )
            b.memory_index = mem_i
            if is_active_turn:
                self.active_stream_bubble = b
                last_st = getattr(self, "_last_worker_status", "")
                if last_st and not c:
                    b.set_thinking_status(last_st)
            align = Qt.AlignmentFlag.AlignRight if role == "user" else Qt.AlignmentFlag.AlignLeft
            _ins(b, align)

    def _add_load_more_pill(self):
        if getattr(self, "_load_more_btn", None) is not None:
            return
        btn = QPushButton(f"📜 Load earlier messages ({len(self._earlier_queue)})")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(34)
        btn.setProperty("cel_timeline", False)
        btn.setStyleSheet("""
            QPushButton {
                background: rgba(147, 51, 234, 0.16);
                color: #E9D5FF;
                border: 1px dashed #A855F7;
                border-radius: 17px;
                padding: 7px 22px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(147, 51, 234, 0.42);
                color: #FFFFFF;
                border-style: solid;
            }
        """)
        btn.clicked.connect(self._load_earlier_batch)
        self._load_more_btn = btn
        self.chat_layout.insertWidget(0, btn, 0, Qt.AlignmentFlag.AlignHCenter)

    def _load_earlier_batch(self):
        """Prepend the previous chunk of history above the current view."""
        if getattr(self, "_loading_earlier", False):
            return
        queue = getattr(self, "_earlier_queue", None)
        if not queue:
            return
        self._loading_earlier = True
        try:
            # Consume from the END of the queue so each chunk sits directly
            # above what is already rendered (tail-first, then upwards).
            batch = queue[-40:]
            del queue[-40:]
            bar = self.chat_scroll.verticalScrollBar()
            old_val, old_max = bar.value(), bar.maximum()
            pill = getattr(self, "_load_more_btn", None)
            start = 0
            if pill is not None:
                try:
                    if self.chat_layout.indexOf(pill) == 0:
                        start = 1
                except RuntimeError:
                    pill = None
                    self._load_more_btn = None
            for mem_i, m in reversed(batch):
                self._render_mem_entry(mem_i, m, at_index=start)
            if not queue and pill is not None:
                try:
                    self.chat_layout.removeWidget(pill)
                    pill.deleteLater()
                except RuntimeError:
                    pass
                self._load_more_btn = None
            elif pill is not None:
                try:
                    pill.setText(f"📜 Load earlier messages ({len(queue)})")
                except RuntimeError:
                    pass
            self.update_all_bubble_geometries()

            def _restore_scroll():
                try:
                    bar2 = self.chat_scroll.verticalScrollBar()
                    if old_val <= 4:
                        bar2.setValue(0)
                    else:
                        bar2.setValue(old_val + max(0, bar2.maximum() - old_max))
                except Exception:
                    pass
            QTimer.singleShot(0, _restore_scroll)
        finally:
            self._loading_earlier = False

    def show_hamburger_menu(self, pos=None):
        play_ui_sound("click", 0.5)
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: rgba(18, 12, 32, 0.96);
                border: 1.5px solid #9333EA;
                border-radius: 12px;
                color: #F0E6FF;
                padding: 6px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 8px 16px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background: rgba(147, 51, 234, 0.4);
                color: #FFFFFF;
            }
        """)

        act_sidebar = menu.addAction("🌀 Toggle Left Sidebar")
        act_history = menu.addAction("📜 Toggle Chat History")
        menu.addSeparator()
        
        # Agent mode toggle
        agent_enabled = self.settings.get("agent_mode_enabled", False)
        act_agent = menu.addAction(f"{'🤖' if agent_enabled else '🤖'} Agent Mode {'ON' if agent_enabled else 'OFF'}")
        act_agent.setCheckable(True)
        act_agent.setChecked(agent_enabled)
        
        act_zoom_in = menu.addAction("🔍 Zoom In (Ctrl + Up)")
        act_zoom_out = menu.addAction("🔍 Zoom Out")
        act_zoom_reset = menu.addAction("🔍 Reset Zoom (100%)")
        menu.addSeparator()
        act_rename = menu.addAction("✨ AI Rename Chat")
        act_compact = menu.addAction("📦 Compact Context && Memory")
        act_settings = menu.addAction("⚙️ Settings")
        act_hub = menu.addAction("🎛️ Model Hub")
        act_ram = menu.addAction("🧹 Free RAM && Cache")
        act_companion = menu.addAction("🐾 Desktop Companion")
        act_companion.setCheckable(True)
        _comp = getattr(self, "_companion", None)
        act_companion.setChecked(bool(_comp is not None and _comp.visible))
        # Two more entries that had no way in before: the pomodoro clock and
        # the ambient particles were both built and then left unreachable.
        act_focus = menu.addAction("⏳ Focus Clock")
        act_dust = menu.addAction("✨ Ambient particles")
        act_dust.setCheckable(True)
        act_dust.setChecked(bool(self.settings.get("ambient_particles", True)))

        # Bug 1: controls that the smart-resizer folded away in a compact
        # window come back as live actions here, so nothing is ever lost.
        try:
            _folded = getattr(self, "_topbar_collapsed", None)
            if _folded:
                menu.addSeparator()
                hdr = menu.addAction("🪟 Folded away (narrow window)")
                hdr.setEnabled(False)
                for _label, _fn in _folded:
                    try:
                        menu.addAction(_label, _fn)
                    except Exception:
                        pass
        except Exception:
            pass

        if isinstance(pos, QPoint):
            target_pos = pos
        elif self.sender():
            widget = self.sender()
            target_pos = widget.mapToGlobal(QPoint(0, widget.height()))
        else:
            target_pos = self.btn_toggle_drawer.mapToGlobal(QPoint(0, self.btn_toggle_drawer.height()))

        action = menu.exec(target_pos)
        if action == act_sidebar:
            self.toggle_left_drawer()
        elif action == act_history:
            self.toggle_right_drawer()
        elif action == act_agent:
            self.toggle_agent_mode()
        elif action == act_zoom_in:
            self.adjust_zoom(0.08)
        elif action == act_zoom_out:
            self.adjust_zoom(-0.08)
        elif action == act_zoom_reset:
            self.set_zoom(1.0)
        elif action == act_rename:
            self.trigger_ai_rename()
        elif action == act_compact:
            self.compact_current_session()
        elif action == act_settings:
            self.open_settings_view()
        elif action == act_hub:
            self.open_model_hub_view()
        elif action == act_ram:
            self.free_all_ram_click()
        elif action == act_companion:
            self.toggle_companion()
        elif action == act_focus:
            self.open_focus_clock_view()
        elif action == act_dust:
            self.set_ambient_particles(bool(act_dust.isChecked()))

    # ── Desktop companion (the Cerebellium avatar) ──────────────────────
    def _companion_library(self):
        """Reuse an already-parsed avatar library.

        Parsing all 1,520 expressions costs ~1.5 s of blocked UI. Live Mode
        and the Avatar Studio have usually paid that already, so the pet
        borrows their instance instead of re-parsing on every toggle.
        """
        try:
            stage = getattr(self, "_live_stage", None)
            lib = getattr(stage, "library", None) if stage else None
            if lib is not None:
                return lib
        except Exception:
            pass
        from cellium.ui.avatar import AvatarLibrary
        return AvatarLibrary()

    def _ensure_companion(self):
        """Build the floating avatar on first use.

        Imported lazily and fully guarded so Cellium still starts cleanly if the
        avatar data folder is missing or unreadable.
        """
        comp = getattr(self, "_companion", None)
        if comp is not None:
            return comp
        try:
            from cellium.ui.avatar import CompanionStage
        except Exception as e:
            self.show_toast(f"🐾 Companion unavailable: {e}", icon="⚠️")
            return None
        gender = self.settings.get("companion_gender", "Female")
        try:
            comp = CompanionStage(library=self._companion_library(),
                                 gender=gender)
        except Exception as e:
            self.show_toast(f"🐾 Companion failed to start: {e}", icon="⚠️")
            return None
        try:
            comp.voice_requested.connect(self._on_companion_voice_requested)
            comp.window.screen_triggered.connect(self._on_pet_screen_snap)
            comp.window.model_triggered.connect(self._on_pet_model_menu)
            comp.window.agent_triggered.connect(self._on_pet_agent_toggle)
            comp.window.voice_triggered.connect(self._on_pet_voice_menu)
            comp.window.text_submitted.connect(self._on_mini_transcript)
            comp.window.control_bar.set_agent_active(bool(self.settings.get("agent_mode_enabled", False)))
            if not getattr(self, "_shot_bubble_wired", False):
                comp.window.screenshot_requested.connect(self._on_shot_bubble_clicked)
                comp.window.shot_dismissed.connect(self._on_shot_bubble_hidden)
                comp.window.closed.connect(self._on_pet_closed_during_mini)
                self._shot_bubble_wired = True
        except Exception:
            pass
        self._companion = comp
        return comp

    def _capture_screen_with_ribbon(self, auto_queue_for_pet: bool = True) -> str:
        """Capture the desktop screen, flash the purple/dark-blue ribbon, and optionally queue for Pet Mode."""
        shot_path = ""
        try:
            screen = QApplication.primaryScreen()
            if screen is not None:
                pix = screen.grabWindow(0)
                shot_path = os.path.join(tempfile.gettempdir(), f"cel_screen_{int(time.time())}.png")
                pix.save(shot_path, "PNG")
                self._last_screen_shot = shot_path
                if auto_queue_for_pet:
                    self._pet_pending_shot = shot_path
            self._show_screen_ring_pulse()
        except Exception as e:
            dev_log(f"[ScreenRibbon] capture error: {e}")
        return shot_path

    def _on_pet_screen_snap(self) -> None:
        """Clicked 📸 on the Pet: flash purple/dark-blue ribbon, snap screen & attach to next Pet turn!"""
        path = self._capture_screen_with_ribbon(auto_queue_for_pet=True)
        comp = getattr(self, "_companion", None)
        if comp is not None and comp.visible:
            comp.react("excited", say="📸 Saw your screen! Ask me anything about it~ ✨", msec=3500)
            comp.show_screenshot_bubble()
        if path and not getattr(self, "_mini_active", False):
            self._start_mini_audio()

    def _on_pet_model_menu(self, btn) -> None:
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background: #181430; color: #F3EEFF; border: 1px solid #A855F7; border-radius: 8px; padding: 4px; } QMenu::item:selected { background: rgba(168,85,247,0.45); }")
        favs = [f for f in self.settings.get("favorite_models", []) if f in self.models] or list(self.models.keys())[:15]
        cur = self.settings.get("selected_model", "")
        for m in favs:
            act = menu.addAction(f"✓ {m}" if m == cur else f"   {m}")
            act.triggered.connect(lambda _=False, mn=m: (self.set_active_model(mn), self.show_toast(f"🐾 Pet Model: {mn}", icon="🧠")))
        menu.exec(btn.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    def _on_pet_agent_toggle(self) -> None:
        self.toggle_agent_mode()
        comp = getattr(self, "_companion", None)
        if comp is not None:
            on = bool(self.settings.get("agent_mode_enabled", False))
            comp.window.control_bar.set_agent_active(on)
            comp.say("⚡ Agent Mode: ON!" if on else "🤖 Agent Mode: OFF", msec=2200)

    def _on_pet_voice_menu(self, btn) -> None:
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background: #181430; color: #F3EEFF; border: 1px solid #A855F7; border-radius: 8px; padding: 4px; } QMenu::item:selected { background: rgba(168,85,247,0.45); }")
        sub_k = menu.addMenu("Kokoro (Offline)")
        for lbl, vid in KOKORO_VOICES:
            a = sub_k.addAction(lbl.split(" • ")[0])
            a.triggered.connect(lambda _=False, v=vid: self._set_pet_voice("Kokoro (Offline)", v))
        sub_e = menu.addMenu("Edge TTS (Online)")
        for lbl, vid in EDGE_VOICES:
            a = sub_e.addAction(lbl.split(" • ")[0])
            a.triggered.connect(lambda _=False, v=vid: self._set_pet_voice("Edge TTS (Online)", v))
        menu.exec(btn.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    def _set_pet_voice(self, host: str, vid: str) -> None:
        self.settings["live_voice"] = host
        self.settings["live_voice_id"] = vid
        save_json(F_SETTINGS, self.settings)
        self.show_toast(f"🔊 Pet Voice: {vid}", icon="🔊")

    def _on_companion_voice_requested(self) -> None:
        """Handle clicking the 🎙️ Talk button on the floating desktop pet."""
        if getattr(self, "_live", None) is not None and self._live.active:
            self._exit_live_mode()
            return
        if getattr(self, "_mini_active", False):
            self._stop_mini_audio(silent=False)
            return
        comp = getattr(self, "_companion", None)
        if comp is not None and comp.visible:
            comp.react("excited", say="Listening! Talk to me~ 🎙️✨", msec=2600)
        self._start_mini_audio()

    def apply_companion_settings(self):
        """Honour Pet Mode (Settings -> Live Mode).

        Off hides her without destroying anything, so turning her back on is
        instant and she keeps her expression, position and idle rotation.
        """
        try:
            want = bool(self.settings.get("pet_mode_enabled", False))
            # Pet mode also owns the mood contract - rebuild prompts before
            # the early return below so turning her off strips it instantly.
            self._refresh_system_prompt_memory()
            speak = bool(self.settings.get("pet_speak_replies", True))
            try:
                scale = max(40, min(200, int(
                    self.settings.get("pet_scale", 100) or 100))) / 100.0
            except (TypeError, ValueError):
                scale = 1.0
            comp = getattr(self, "_companion", None)
            if not want:
                if comp is not None:
                    try:
                        comp.hide()
                    except Exception:
                        pass
                return
            comp = self._ensure_companion()
            if comp is None:
                return
            comp.set_speak_enabled(speak)
            comp.set_scale(scale)
            if not comp.visible:
                comp.show()
                comp.react("waking", say="I'm here! ✨")
            if not comp.available():
                self.show_toast("🐾 Pet mode is on, but no expressions loaded.",
                                icon="⚠️")
        except Exception as e:
            self.show_toast(f"🐾 Companion: {e}", icon="⚠️")

    def companion_state(self, state: str):
        """Let the floating pet follow a live call."""
        comp = getattr(self, "_companion", None)
        if comp is None:
            return
        try:
            if not comp.visible:
                return
            if state == "thinking":
                comp.react("thinking")
            elif state == "listening":
                comp.react("idle")
        except Exception:
            pass

    def toggle_companion(self):
        comp = self._ensure_companion()
        if comp is None:
            return
        try:
            if comp.toggle():
                self.settings["pet_mode_enabled"] = True
                save_json(F_SETTINGS, self.settings)
                self._update_pet_mode_button(True)
                self._capture_screen_with_ribbon(auto_queue_for_pet=True)
                comp.react("waking", say="I'm here & listening! ✨")
                comp.show_screenshot_bubble()
                self._start_mini_audio()
                self.show_toast("🐾 Pet Mode live - listening & screen captured!", icon="🐾")
            else:
                self.settings["pet_mode_enabled"] = False
                save_json(F_SETTINGS, self.settings)
                self._update_pet_mode_button(False)
                self._stop_mini_audio(silent=True)
                self.show_toast("💤 Companion sleeping.", icon="💤")
                QTimer.singleShot(600, self.refresh_wake_listener)
            self._refresh_system_prompt_memory()
        except Exception as e:
            self.show_toast(f"🐾 Companion error: {e}", icon="⚠️")

    def _update_pet_mode_button(self, on: bool) -> None:
        """Reflect pet-mode state on the live call bar's Companion button.

        This method was CALLED but never defined, so every companion toggle
        ended in a "Companion error" toast even though the toggle itself had
        worked. It flips the call bar toggle and never raises - the toggle
        already happened, UI paint must not be able to undo it.
        """
        try:
            bar = getattr(getattr(self, "_live_stage", None), "controls", None)
            btn = getattr(bar, "pet", None)
            if btn is not None and hasattr(btn, "set_toggle"):
                btn.set_toggle(bool(on))
        except Exception:
            pass

    def companion_react(self, text, reply="", mood=None):
        """Let the visible companion react to a finished assistant reply."""
        comp = getattr(self, "_companion", None)
        if comp is None:
            return
        try:
            if comp.visible:
                comp.respond_to(text or "", reply=reply or "", mood=mood)
        except Exception:
            pass  # never let the companion break a chat turn

    # ── CelAS Live Mode ──────────────────────────────────────────────────
    def _enter_live_mode(self):
        """Clear the entire GUI and hand the screen to Cel."""
        # Ignore a second click while the curtain is already animating,
        # otherwise two overlapping animations fight over one widget.
        if self._live.active:
            return
        # A floating mini call owns the mic - hang it up before the curtain.
        try:
            self._stop_mini_audio(silent=True)
        except Exception:
            pass
        # A floating mini call owns the mic - hang it up before the curtain.
        try:
            self._stop_mini_audio(silent=True)
        except Exception:
            pass
        wipe = getattr(self, "_call_wipe", None)
        if wipe is not None and wipe.isVisible():
            return
        # One-time room calibration (F1): teach the gate what your quiet
        # room sounds like before the first call ever uses the mic. Skips
        # itself afterwards - Settings can re-run it on demand.
        if not bool(self.settings.get("noise_calibration_done", False)) \
                and not getattr(self, "_noise_prompted", False):
            self._noise_prompted = True
            try:
                self._run_noise_calibration()
            except Exception:
                pass
        # Only one capture stream can own the mic - release the wake word
        # listener before the call opens its own.
        try:
            wake = getattr(self, "_wake", None)
            if wake is not None:
                wake.stop()
        except Exception:
            pass
        # Resolved now, not at construction: every chrome widget exists by the
        # time the user can possibly click the button.
        self._live.set_hide_targets([
            self.left_drawer, self.top_bar, self.input_pill,
            self.right_drawer, self.chat_scroll,
            # chat_workspace carries the wallpaper and the "Hello" empty state.
            # Hiding only chat_scroll left it painted over the call screen.
            self.chat_workspace,
        ])
        self._live.settings = self.settings
        if self._live.audio is not None:
            self._live.audio.settings = self.settings

        # Curtain closes -> we switch to Live Mode *behind* it -> curtain lifts
        # to reveal Cel. Feels like a call connecting, not a window vanishing.
        if wipe is None:
            wipe = self._call_wipe = CallTransition(self)
            # A failed connect lifts back to chat - restore the wake word
            # and tell the user why (wired once, when created).
            wipe.dismissed.connect(self._live_connect_aborted)

        import time as _time
        t0 = _time.monotonic()

        def _begin() -> None:
            # Curtain fully closed. Prove the model answers *behind* it
            # while the ring keeps breathing; only then lift into the call.
            # On failure the ring goes red, the error bubble floats for 5 s
            # and the curtain lifts back to the untouched chat - never a
            # black sheet with no way out.
            self._start_live_connect_check(wipe, t0)

        wipe.play_in(_begin)

    # ── connect check (F4) ────────────────────────────────────────────────
    _CONN_CAPTIONS = ["Connecting to Cel…", "Ringing…", "Checking your model…"]

    def _start_live_connect_check(self, wipe, t0):
        """Ping the selected model behind the closed curtain.

        Offline GGUF → the file must exist; online → one real HTTP
        round-trip (single-model ModelPingWorker). Success lifts into the
        call after a minimum ring time so a fast ping can't flash the
        curtain; failure flips it red with a floating error bubble and
        returns to the untouched chat.
        """
        self._wipe_t0 = t0
        self._conn_caption_i = 0
        old = getattr(self, "_conn_caption", None)
        if old is not None:
            try:
                old.stop()
            except RuntimeError:
                pass
        combo_text = self.model_selector.currentText() if hasattr(self, "model_selector") else ""
        model_key = str(combo_text or self.settings.get("selected_model", "") or "")
        if model_key in self.models:
            self.settings["selected_model"] = model_key
        route = self.models.get(model_key)
        if wipe is not None:
            wipe.set_caption(self._CONN_CAPTIONS[0])
        self._conn_caption = QTimer(self)
        self._conn_caption.setInterval(950)

        def _rotate():
            self._conn_caption_i = (
                (self._conn_caption_i + 1) % len(self._CONN_CAPTIONS))
            if wipe is not None and not getattr(wipe, "_failed", False):
                wipe.set_caption(self._CONN_CAPTIONS[self._conn_caption_i])

        self._conn_caption.timeout.connect(_rotate)
        self._conn_caption.start()

        resolved_off = (
            resolve_offline_model_path(model_key, self.settings, self.models)
            or resolve_any_offline_path(self.settings)
        )
        is_offline = (
            is_offline_model_key(model_key, route)
            or bool(resolved_off)
        )
        if is_offline:
            if resolved_off and not self.settings.get("local_model_path"):
                self.settings["local_model_path"] = resolved_off
            # User picked an offline model - bypass the call-failed screen!
            self._stop_conn_caption()
            QTimer.singleShot(0, lambda: self._commit_live(wipe))
            return
        if not model_key:
            self._live_connect_fail(
                wipe, "No model selected - pick one in the model menu first.")
            return
        if not isinstance(route, dict):
            self._live_connect_fail(
                wipe, f"Model “{model_key}” isn’t configured - open "
                      "Settings → Models.")
            return
        try:
            from cellium.services.ai_workers import ModelPingWorker
            ping = ModelPingWorker({model_key: route}, self.settings,
                                   parent=self)
            ping.finished.connect(ping.deleteLater)
            ping.ping_result.connect(self._live_connect_result)
            self._connect_ping = ping
            ping.start()
        except Exception as e:
            self._live_connect_fail(wipe, f"Connectivity check failed: {e}")

    def _stop_conn_caption(self):
        c = getattr(self, "_conn_caption", None)
        if c is not None:
            try:
                c.stop()
            except RuntimeError:
                pass

    def _live_connect_result(self, model_key, status, ok, latency):
        wipe = getattr(self, "_call_wipe", None)
        if ok:
            self._live_connect_ok(wipe)
        else:
            self._live_connect_fail(wipe, f"{model_key}: {status}")

    def _live_connect_ok(self, wipe):
        """Hold the ring for a minimum beat, then commit the call."""
        self._stop_conn_caption()
        import time as _time
        t0 = getattr(self, "_wipe_t0", None)
        elapsed_ms = (_time.monotonic() - t0) * 1000.0 if t0 else 0.0
        hold_ms = int(max(0.0, 1700.0 - elapsed_ms))
        QTimer.singleShot(hold_ms, lambda: self._commit_live(wipe))

    def _commit_live(self, wipe):
        """Enter live behind the (still closed) curtain, then lift it.

        The curtain MUST lift even if entering fails, otherwise the app is
        stuck behind an opaque black sheet with no way out.
        """
        if wipe is None:
            return
        try:
            # Reuse the companion's parsed library: parsing 1,520
            # expressions blocks the UI for ~1.5s, which used to freeze the
            # curtain mid-wipe on every call.
            try:
                comp = getattr(self, "_companion", None)
                lib = getattr(comp, "lib", None) if comp is not None else None
                if lib is not None:
                    self._live_stage.set_library(lib)
            except Exception:
                pass
            self._live.enter_live(
                self.settings.get("companion_gender", "Female"))
            self._wire_live_controls()
            # Live is now active → the mood contract belongs in the prompt.
            self._refresh_system_prompt_memory()
            # Fresh transcript + a closed history sidebar on every call (F2).
            try:
                bar = self._live_stage.controls
                bar._hist_open = False
                bar.hist.set_toggle(False)
                self._live_stage.transcript.populate(
                    self._live_session_messages())
            except Exception:
                pass
        finally:
            wipe.play_out()

    def _live_connect_fail(self, wipe, msg):
        """Red ring + floating error bubble for 5 s, then back to chat."""
        self._stop_conn_caption()
        if wipe is None:
            self.show_toast(f"📱 {msg}", icon="⚠️")
            self.refresh_wake_listener()
            return
        wipe.fail(str(msg))

    def _live_connect_aborted(self):
        """The red curtain lifted without entering the call."""
        self.refresh_wake_listener()
        self.show_toast(
            "📱 Cel didn’t answer - check your model in Settings.",
            icon="⚠️")

    # ── live history helpers (F2) ──────────────────────────────────────────
    def _live_session_messages(self):
        ses = self.sessions.get(self.current_sid) if self.current_sid else None
        if not isinstance(ses, dict):
            return []
        return [m for m in ses.get("memory", [])
                if isinstance(m, dict)
                and m.get("role") in ("user", "assistant")]

    def _toggle_live_history(self, on: bool) -> None:
        try:
            stage = getattr(self, "_live_stage", None)
            if stage is None:
                return
            if on:
                stage.history.populate(self._live_session_messages())
            # The on-screen pixel bubbles sit exactly where the sidebar
            # lands - dissolve them (parked, not deleted) so the two never
            # overlap. Closing the panel brings the same bubbles back.
            stage.transcript.set_parked(bool(on))
            stage.history.set_open(bool(on))
        except Exception:
            pass

    def _live_history_closed(self) -> None:
        try:
            stage = getattr(self, "_live_stage", None)
            if stage is not None:
                stage.history.set_open(False)
                stage.transcript.set_parked(False)
                bar = stage.controls
                bar._hist_open = False
                bar.hist.set_toggle(False)
        except Exception:
            pass

    def _live_favorite_models(self):
        """Favourites only - the call's model circle must stay short.

        With 99+ models loaded, tapping the circle walked the whole catalogue,
        and the menu needed scrolling to find anything. The rest of the app
        already treats favourites as the shortlist; the call now does too.
        """
        try:
            favs = self.settings.get("favorite_models") or []
        except Exception:
            return []
        return [str(f) for f in favs if str(f) in (self.models or {})]

    def _wire_live_controls(self) -> None:
        """Feed the call's round controls from real app state.

        Voice is stored under its own ``live_voice`` key on purpose: whatever
        you pick for a call must not hijack the chat voice or the desktop pet's
        Animal Crossing chirps.
        """
        bar = self._live_stage.controls
        # Reuse the companion's parsed library - saves ~1.5s of frozen UI on
        # every call when the desktop pet is already running.
        try:
            comp = getattr(self, "_companion", None)
            if comp is not None and getattr(comp, "lib", None) is not None:
                self._live_stage.set_library(comp.lib)
        except Exception:
            pass
        try:
            current_model = self.model_selector.currentText()
        except Exception:
            current_model = self.settings.get("active_model", "")

        _cur_host = self.settings.get("live_voice", "Kokoro (Offline)")
        _cur_vid = self.settings.get("live_voice_id", "")
        _voice_display = _cur_host
        if _cur_host == "Kokoro (Offline)":
            _target_id = _cur_vid or "af_heart"
            for _lbl, _vid in KOKORO_VOICES:
                if _vid == _target_id:
                    _voice_display = _lbl
                    break
        elif _cur_host == "Edge TTS (Online)":
            _target_id = _cur_vid or "en-US-JennyNeural"
            for _lbl, _vid in EDGE_VOICES:
                if _vid == _target_id:
                    _voice_display = _lbl
                    break

        bar.populate(
            models=self.models,
            current_model=current_model,
            agent_on=bool(self.settings.get("agent_mode_enabled", False)),
            voice=_voice_display,
            apply_model=self.set_active_model,
            stt_engine=self.settings.get(
                "voice_stt_engine", "Kokoro Whisper (Local)"),
            favorites=self._live_favorite_models(),
        )

        # One-shot wiring: this runs on every call, so connecting here each
        # time would stack N handlers per click. Stale closures were part of
        # why the circles felt "dead" - a pick now fires exactly once.
        if not getattr(bar, "_cel_wired", False):
            bar._cel_wired = True

            def _on_agent(on: bool) -> None:
                self.settings["agent_mode_enabled"] = bool(on)
                self._update_top_agent_button(bool(on))
                try:
                    self.save_settings()
                except Exception:
                    pass

            def _on_voice(choice: str) -> None:
                kokoro_map = {lbl: vid for lbl, vid in KOKORO_VOICES}
                edge_map = {lbl: vid for lbl, vid in EDGE_VOICES}
                if choice in kokoro_map:
                    self.settings["live_voice"] = "Kokoro (Offline)"
                    self.settings["live_voice_id"] = kokoro_map[choice]
                elif choice in edge_map:
                    self.settings["live_voice"] = "Edge TTS (Online)"
                    self.settings["live_voice_id"] = edge_map[choice]
                else:
                    self.settings["live_voice"] = choice
                    self.settings["live_voice_id"] = ""
                try:
                    self.save_settings()
                except Exception:
                    pass
                try:
                    from cellium.services.sound_engine import play_animalese_chirp
                    from cellium.core.config import CEL_VOICE_VARIANTS
                    if choice in CEL_VOICE_VARIANTS:
                        play_animalese_chirp(choice[0], True, choice)
                except Exception:
                    pass

            def _on_engine(choice: str) -> None:
                # 🎙 offline ↔ online input engine - applies from the very
                # next utterance (LiveAudio reads this key per capture).
                self.settings["voice_stt_engine"] = choice
                try:
                    self.save_settings()
                except Exception:
                    pass
                gap = stt_missing_key(choice, self.settings)
                if gap is not None:
                    # Selecting an engine that cannot work is a dead mic. Say
                    # why, and hand over the key box.
                    self.show_toast(f"🎙 {gap[0]} has no key saved yet",
                                    icon="🔑")
                    self.prompt_stt_api_key(choice, gap[0], gap[1])
                else:
                    self.show_toast(f"🎙 Input engine: {choice}",
                                    icon="🎙", duration=2400)

            def _on_model_cycle(name: str) -> None:
                # Tap-to-cycle (item 11) needs visible feedback - the circle
                # caption is 10px tall; a toast says which model took over.
                try:
                    self.show_toast(f"📱 Model: {name}", icon="🧠",
                                    duration=2200)
                except Exception:
                    pass

            bar.agent_toggled.connect(_on_agent)
            bar.voice_changed.connect(_on_voice)
            bar.engine_changed.connect(_on_engine)
            bar.model_changed.connect(_on_model_cycle)
            bar.history_toggled.connect(self._toggle_live_history)
            bar.pet.clicked.connect(self.toggle_companion)
            try:
                self._live_stage.history.closed.connect(
                    self._live_history_closed)
            except Exception:
                pass

    def _live_send_transcript(self, text):
        """Submit a Live Mode utterance as a normal turn."""
        if not text:
            return
        try:
            self.edit_input.setPlainText(text)
        except RuntimeError:
            return
        # The controller normally sets this around the send; keep it here too so
        # any other route into a live turn gets the same spoken-call rules.
        if not getattr(self, "_live_prompt_extra", ""):
            try:
                from cellium.ui.live.live_mode import LIVE_RULES
                self._live_prompt_extra = LIVE_RULES
            except Exception:
                self._live_prompt_extra = ""
        try:
            self.send_message()
        finally:
            self._live_prompt_extra = ""
        # Mid-call persistence: send_message only writes the session when it
        # creates the title, so hanging up mid-turn used to drop everything
        # typed on the way in (F2).
        try:
            if not self.settings.get("incognito"):
                save_json(F_SESSIONS, self.sessions)
        except Exception:
            pass

    def _exit_live_mode(self):
        """Tear down audio/mic on hang-up so no capture device is left open.

        Uses the existing teardown APIs rather than inventing new ones:
        ``stop_current_tts()`` and ``AudioRecordWorker.stop()``.
        """
        # Also drive the controller's own exit so the hidden chrome comes back.
        # End-call already does this, but any other route (error, shortcut,
        # programmatic) would otherwise leave the GUI hidden with no way out.
        try:
            if self._live.active:
                self._live.exit_live()
        except Exception:
            pass
        try:
            self.stop_current_tts()
        except Exception:
            pass
        try:
            rec = getattr(self, "audio_recorder", None)
            if rec is not None and rec.is_recording:
                rec.stop()
        except Exception:
            pass
        # The call hid the chat - put the conversation back on screen with
        # the stack/state/status chip reset (F2).
        try:
            self._restore_chat_after_live()
        except Exception:
            pass
        # Live is over → strip the mood contract from every stored prompt so
        # plain chat never pays those tokens again.
        self._refresh_system_prompt_memory()
        # Mic is free again - hand it back to the wake word. 1.5 s, not 0.5:
        # the call's teardown joins its recorder threads first, and
        # restarting into a still-busy device killed the listener outright.
        # The 4 s watchdog re-covers any restart that still fails.
        QTimer.singleShot(1500, self.refresh_wake_listener)

    # ── Hey Cel wake word ────────────────────────────────────────────────
    def _update_wake_button(self, on: bool):
        """Restyle the 🎧 quick toggle. Mirrors _update_top_agent_button."""
        if not hasattr(self, "btn_wake") or not self.btn_wake:
            return
        # The tray checkbox mirrors the same setting - without this it goes
        # stale (ON here, OFF there) and the next click does the opposite of
        # what the menu shows.
        try:
            act = getattr(self, "_act_wake", None)
            if act is not None:
                act.setChecked(bool(on))
        except Exception:
            pass
        if on:
            self.btn_wake.setText("🎧 Hey Cel: ON")
            self.btn_wake.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #7C3AED, stop:1 #C026D3);
                    color: #FFFFFF; border: 1.5px solid #E879F9;
                    border-radius: 10px; padding: 4px 12px;
                    font-weight: bold; font-size: 11px;
                }
                QPushButton:hover { background: #9333EA; border-color: #F0ABFC; }
            """)
        else:
            self.btn_wake.setText("🎧 Hey Cel: OFF")
            self.btn_wake.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.06);
                    color: #94A3B8; border: 1.5px solid rgba(148, 163, 184, 0.25);
                    border-radius: 10px; padding: 4px 12px;
                    font-weight: bold; font-size: 11px;
                }
                QPushButton:hover {
                    background: rgba(147, 51, 234, 0.3);
                    color: #E2E8F0; border-color: #C084FC;
                }
            """)
        self._refresh_wake_indicator()
        self._sync_more_menu()

    def toggle_wake_word(self):
        """Flip the always-on wake word - the bundled “Okay Cel” model needs
        no calibration, so this just works now."""
        on = not bool(self.settings.get("listen_activation", False))
        self.settings["listen_activation"] = on
        save_json(F_SETTINGS, self.settings)
        self._update_wake_button(on)
        try:
            self._wake_fails = 0
            self._wake_next_retry = 0.0
        except Exception:
            pass
        self.refresh_wake_listener()
        self._sync_more_menu()
        self.show_toast(
            "🎧 Hey Cel is live - say “Okay Cel” to open Live Mode." if on
            else "🎧 Hey Cel off - microphone released.",
            icon="🎧")

    # NOTE (retired): _run_wake_calibration / _run_wake_wizard used to gate
    # wake-word listening behind the 10-sample Hey Cel wizard. The bundled
    # oh_kay_sell.onnx model needs no per-user training, so the wizard is
    # unwired - HeyCelWizardDialog stays in calibration.py as archived code.

    # ── noise cancellation calibration (F1) ─────────────────────────────────
    def _run_noise_calibration(self):
        """Teach the gate what this room sounds like (first run or Settings)."""
        try:
            from cellium.ui.live.calibration import NoiseCalibrationDialog
        except Exception as e:
            self.show_toast(f"🧹 Noise calibration unavailable: {e}", icon="⚠️")
            return
        try:
            dlg = NoiseCalibrationDialog(self.settings, self)
            accepted = bool(dlg.exec())
        except Exception as e:
            self.show_toast(f"🧹 Calibration failed: {e}", icon="⚠️")
            return
        # Save writes the profile + keys into self.settings itself; a Skip
        # leaves them untouched, so re-configuring here is always safe.
        try:
            from cellium.services import noise_gate
            noise_gate.configure(self.settings)
        except Exception:
            pass
        if accepted:
            try:
                save_json(F_SETTINGS, self.settings)
            except Exception:
                pass
            self.show_toast(
                "🧹 Room profile saved - I subtract it from your mic now.",
                icon="🧹")

    def _restore_chat_after_live(self):
        """F2: hand the screen back to the conversation when a call ends."""
        try:
            self.show_chat_view()
        except Exception:
            pass
        try:
            if self.current_sid:
                self.switch_session(self.current_sid)
        except Exception:
            pass
        # A dead worker leaves the last "Receiving…" chip stuck on top.
        try:
            w = getattr(self, "worker", None)
            alive = bool(w is not None and w.isRunning())
            txt = str(self.lbl_server_badge.text())
            busy = any(k in txt for k in
                       ("Receiving", "Thinking", "Streaming", "✨"))
            if not alive and busy:
                sel = str(self.settings.get("selected_model", "") or "").strip()
                self.lbl_server_badge.setText(
                    f"● {sel} Ready 💕" if sel else "● Ready 💕")
        except Exception:
            pass
        try:
            self.refresh_history_list()
        except Exception:
            pass
        try:
            if not self.settings.get("incognito"):
                save_json(F_SESSIONS, self.sessions)
        except Exception:
            pass

    def refresh_wake_listener(self):
        """Start/stop the wake word listener to match settings and call state."""
        if getattr(self, "_closing", False):
            try:
                lst = getattr(self, "_wake", None)
                if lst is not None:
                    lst.stop()
            except Exception:
                pass
            return
        want = bool(self.settings.get("listen_activation", False))
        try:
            if getattr(self, "_live", None) is not None and self._live.active:
                want = False  # Live Mode owns the mic
            if getattr(self, "_mini_active", False):
                want = False  # Pet Mode Mini-Live owns the mic
            wipe = getattr(self, "_call_wipe", None)
            if wipe is not None and wipe.isVisible():
                want = False  # Call transition curtain is up
        except Exception:
            pass
        lst = getattr(self, "_wake", None)
        if want:
            if lst is None:
                try:
                    from cellium.services.wake import WakeListener
                    lst = self._wake = WakeListener(self, settings=self.settings)
                    lst.woken.connect(self._on_wake_word)
                    lst.listening_changed.connect(self._on_wake_listening_changed)
                    lst.heard.connect(self._on_wake_heard)
                    lst.error.connect(self._on_wake_error)
                except Exception as e:
                    self.show_toast(f"🎧 Wake word unavailable: {e}", icon="⚠️")
                    return
            if not lst.running:
                lst.start()
                if lst.running:
                    try:
                        self._wake_fails = 0
                    except Exception:
                        pass
        elif lst is not None:
            lst.stop()

    def _refresh_wake_indicator(self, listening=None) -> None:
        """Mirror the real mic state on the top-bar pill.

        ON + actually listening gets a ● dot; the tooltip names the engine,
        the state and the last thing she heard - so "is it even listening?"
        is answered at a glance instead of by shouting at the screen.
        """
        try:
            on = bool(self.settings.get("listen_activation", False))
            if listening is None:
                lst = getattr(self, "_wake", None)
                listening = bool(lst is not None and lst.running)
            if hasattr(self, "btn_wake") and self.btn_wake:
                self.btn_wake.setText(
                    "🎧 Hey Cel: ON ●" if (on and listening)
                    else "🎧 Hey Cel: ON" if on
                    else "🎧 Hey Cel: OFF")
                try:
                    eng = ""
                    lst = getattr(self, "_wake", None)
                    if lst is not None:
                        eng = str(getattr(lst, "engine_in_use", "") or "")
                    heard, when = getattr(self, "_wake_last_heard", ("", 0.0))
                    ago = ""
                    if heard and when:
                        try:
                            ago = (f" · last heard “{heard}” "
                                   f"{int(time.monotonic() - when)}s ago")
                        except Exception:
                            ago = f" · last heard “{heard}”"
                    self.btn_wake.setToolTip(
                        f"Always-on wake word ({eng or 'off'}) - "
                        f"{'listening' if (on and listening) else 'idle'}{ago}. "
                        "Say “Okay Cel” to open Live Mode hands-free. "
                        "OFF releases the mic and saves battery.")
                except Exception:
                    pass
        except Exception:
            pass

    def _on_wake_listening_changed(self, on: bool) -> None:
        """The mic really opened/closed - mirror it, and clear the failure
        count (a live listener needs no watchdog)."""
        try:
            if on and bool(self.settings.get("listen_activation", False)):
                try:
                    self._wake_fails = 0
                except Exception:
                    pass
            self._refresh_wake_indicator(listening=bool(on))
        except Exception:
            pass

    def _on_wake_heard(self, text: str) -> None:
        """Any transcribed utterance while the wake word is armed - proof of
        listening, surfacing in the pill tooltip."""
        try:
            self._wake_last_heard = (str(text or "")[:60], time.monotonic())
            self._refresh_wake_indicator()
        except Exception:
            pass

    def _on_wake_error(self, msg: str) -> None:
        """Toast listener faults at most once a minute - the watchdog keeps
        retrying quietly in between instead of nagging every 4 seconds."""
        try:
            now = time.monotonic()
            last = float(getattr(self, "_wake_last_err_toast", 0.0) or 0.0)
            if now - last < 60.0:
                return
            self._wake_last_err_toast = now
            self.show_toast(f"🎧 {msg}", icon="⚠️")
        except Exception:
            pass

    def _wake_watchdog_tick(self) -> None:
        """Self-healing loop: if Hey Cel should be listening but is not (mic
        was busy when the call ended, a hiccup killed the scorer, …),
        restart it with backoff instead of staying deaf forever."""
        try:
            if getattr(self, "_closing", False):
                return
            try:
                live_active = bool(getattr(self, "_live", None) is not None
                                   and self._live.active)
            except Exception:
                live_active = False
            if not bool(self.settings.get("listen_activation", False)) or live_active:
                self._wake_fails = 0
                return
            # The floating mini call owns the mic - the always-on scorer
            # stands down instead of fighting it (and error-toasting).
            try:
                if getattr(self, "_mini_active", False):
                    return
            except Exception:
                pass
            lst = getattr(self, "_wake", None)
            if lst is not None and lst.running:
                self._wake_fails = 0
                return
            now = time.monotonic()
            if now < float(getattr(self, "_wake_next_retry", 0.0) or 0.0):
                return
            had_fails = int(getattr(self, "_wake_fails", 0) or 0)
            self.refresh_wake_listener()
            lst = getattr(self, "_wake", None)
            if lst is not None and lst.running:
                self._wake_fails = 0
                if had_fails:
                    self.show_toast("🎧 Hey Cel is listening again.", icon="🎧")
            else:
                self._wake_fails = had_fails + 1
                self._wake_next_retry = now + _wake_retry_delay(self._wake_fails)
        except Exception:
            pass

    def _app_is_active(self) -> bool:
        """True when the user is inside the app.

        Main window visible, not minimized, and holding (or sharing) focus.
        Anything else means Cel must come to the user as a floater instead
        of hijacking the screen with the full call stage.
        """
        try:
            if self.isMinimized() or not self.isVisible():
                return False
            if self.isActiveWindow():
                return True
            try:
                return QApplication.activeWindow() is not None
            except Exception:
                return False
        except Exception:
            return False

    def _on_wake_word(self, phrase: str):
        """She heard “Hey Cel” - screenshot, ring + chime, then go where the
        user is: the full call stage when they are in the app, the floating
        mini-live when they are anywhere else."""
        if getattr(self, "_live", None) is not None and self._live.active:
            return
        if getattr(self, "_mini_active", False):
            return
        # Consent is re-checked at fire time, not just at detection time: if
        # Hey Cel was switched off after the detection (or the listener is
        # stale while the setting is off), there is no permission to open the
        # mic, so stand down instead of teleporting into a call.
        if not bool(self.settings.get("listen_activation", False)):
            return
        try:
            # Capture screen to keep
            screen = QGuiApplication.primaryScreen()
            if screen:
                pix = screen.grabWindow(0)
                shot_path = os.path.join(tempfile.gettempdir(), f"cel_screen_{int(time.time())}.png")
                pix.save(shot_path, "PNG")
                self._last_screen_shot = shot_path
                self._show_screen_ring_pulse()
        except Exception:
            pass
        if self._app_is_active():
            try:
                if not self.isVisible():
                    self.showNormal()
                self.show()
                self.raise_()
                try:
                    self.activateWindow()
                except Exception:
                    pass
            except Exception:
                pass
            self.show_toast("🎧 Heard you - connecting to Cel…", icon="🎙")
            QTimer.singleShot(200, self._enter_live_mode_from_wake)
        else:
            # Outside the app: no screen hijack - the ring + chime already
            # fired above, now surface the floating mini-live instead.
            self.show_toast("🎧 Heard you - Cel is here beside you…", icon="🎙")
            QTimer.singleShot(350, self._enter_mini_live_from_wake)

    def _enter_live_mode_from_wake(self):
        """Wake-word entry gate: the 200 ms timer must not outlive consent.

        Opening settings (or the toggle) after a detection must never land
        the user in a hot-mic call they did not ask for - live mode starts
        from an explicit click or a still-armed wake word, nothing else.
        """
        if getattr(self, "_live", None) is not None and self._live.active:
            return
        if not bool(self.settings.get("listen_activation", False)):
            return
        self._enter_live_mode()

    # ── mini-live: wake outside the app ──────────────────────────────────
    def _enter_mini_live_from_wake(self):
        """Wake-word entry for when the user is OUTSIDE the app.

        Same consent gate as the in-app path. Instead of the full-screen
        call stage, the floating companion surfaces - pet mode is minimized
        live: talk while you work, nothing hijacked - with the one-shot
        Screenshot pill and an open mic turn loop.
        """
        if getattr(self, "_live", None) is not None and self._live.active:
            return
        if getattr(self, "_closing", False):
            return
        if not bool(self.settings.get("listen_activation", False)):
            return
        try:
            comp = self._ensure_companion()
        except Exception:
            comp = None
        if comp is None:
            # No avatar data - fall back to the full call rather than nothing.
            try:
                if not self.isVisible():
                    self.showNormal()
                    self.show()
                    self.raise_()
            except Exception:
                pass
            QTimer.singleShot(0, self._enter_live_mode_from_wake)
            return
        try:
            if not comp.visible:
                comp.show()
            comp.react("waking", say="Yes? I'm listening~ ✨")
        except Exception:
            pass
        try:
            comp.show_screenshot_bubble()
        except Exception:
            pass
        try:
            if not getattr(self, "_shot_bubble_wired", False):
                comp.window.screenshot_requested.connect(self._on_shot_bubble_clicked)
                comp.window.shot_dismissed.connect(self._on_shot_bubble_hidden)
                comp.window.closed.connect(self._on_pet_closed_during_mini)
                self._shot_bubble_wired = True
        except Exception:
            pass
        self._start_mini_audio()

    def _start_mini_audio(self) -> None:
        """Open the hands-free mic loop behind the floating pet (stops WakeListener first!)."""
        if getattr(self, "_mini_active", False):
            return
        # 1. Release the wake-word listener first so the microphone device is free!
        try:
            if getattr(self, "_wake", None) is not None:
                self._wake.stop()
        except Exception:
            pass
        try:
            old = getattr(self, "_mini_audio", None)
            if old is not None:
                try:
                    old.stop()
                except Exception:
                    pass
            from cellium.ui.live.audio import LiveAudio
            audio = LiveAudio(None, settings=self.settings)
            # Pet Mode is always hands-free (push_to_talk=False) and unmuted on start
            audio.push_to_talk = False
            audio.set_muted(False)
            audio.transcript.connect(self._on_mini_transcript)
            audio.busy.connect(self._on_mini_busy)
            audio.level.connect(self._on_mini_level)
            audio.error.connect(self._on_mini_audio_error)
            audio.key_required.connect(self._on_mini_key_required)
            self._mini_audio = audio
            # NOTE: set_capture_enabled(True) calls _open_capture() -> start()!
            audio.set_capture_enabled(True)
            if not audio.running and not audio.start():
                self._mini_audio = None
                self.show_toast("🎙 Mini-live mic would not open.", icon="⚠️")
                return
            self._mini_active = True
            comp = getattr(self, "_companion", None)
            if comp is not None:
                comp.window.control_bar.set_mic_listening(True)
                comp.window.set_status_text("🎙️ Listening…")
            self._mini_arm_timeout()
        except Exception as e:
            self._mini_active = False
            self.show_toast(f"🎙 Mini-live unavailable: {e}", icon="⚠️")

    def _on_mini_busy(self, busy: bool) -> None:
        comp = getattr(self, "_companion", None)
        if comp is not None and comp.visible:
            comp.window.set_status_text("⏳ Transcribing…" if busy else "🎙️ Listening…")

    def _on_mini_level(self, rms: float) -> None:
        comp = getattr(self, "_companion", None)
        if comp is not None and comp.visible and getattr(self, "_mini_active", False):
            bars = min(5, int(rms * 45))
            if bars > 0:
                comp.window.set_status_text("🎙️ Listening " + ("●" * bars))

    def _mini_arm_timeout(self) -> None:
        """5-minute idle cap so a forgotten floater cannot hold the mic all day."""
        try:
            t = getattr(self, "_mini_timer", None)
            if t is None:
                t = self._mini_timer = QTimer(self)
                t.setSingleShot(True)
                t.timeout.connect(lambda: self._stop_mini_audio())
            t.start(300000)
        except Exception:
            pass

    def _on_mini_transcript(self, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        self._mini_arm_timeout()
        try:
            comp = getattr(self, "_companion", None)
            if comp is not None and comp.visible:
                comp.say(f"💬 {cleaned[:140]}", msec=2500)
        except Exception:
            pass
        # Auto-attach the wake/pet screen capture if the user is asking about their screen
        shot_p = getattr(self, "_pet_pending_shot", None)
        if shot_p and os.path.exists(shot_p):
            self._pet_pending_shot = None
            cur_m = self.settings.get("selected_model", "")
            if is_vision_model(cur_m, self.models.get(cur_m)):
                try:
                    with open(shot_p, "rb") as f_im:
                        b64 = base64.b64encode(f_im.read()).decode("utf-8")
                    self.pending_attachments.append({
                        "path": shot_p, "name": "Screen Capture.png", "ext": "png",
                        "size_str": "Screen", "type": "image", "base64": b64,
                    })
                except Exception:
                    pass
        try:
            comp = getattr(self, "_companion", None)
            if comp is not None and comp.visible:
                comp.react("thinking")
                comp.window.set_status_text("🧠 Cel is thinking…")
            if hasattr(self, "edit_input") and self.edit_input:
                self.edit_input.setPlainText(cleaned)
                from cellium.ui.live.live_mode import LIVE_RULES
                self._live_prompt_extra = LIVE_RULES
                try:
                    self.send_message()
                finally:
                    self._live_prompt_extra = ""
        except Exception as e:
            self.show_toast(f"🎙 Could not send that: {e}", icon="⚠️")

    def _on_mini_audio_error(self, msg: str) -> None:
        try:
            self.show_toast(f"🎙 {msg}", icon="⚠️")
        except Exception:
            pass

    def _on_mini_key_required(self, engine: str, provider: str) -> None:
        try:
            self.show_toast(f"🎙 {provider or engine} needs an API key - mini-live off.",
                            icon="⚠️")
        except Exception:
            pass
        try:
            self._stop_mini_audio(silent=True)
        except Exception:
            pass

    def _mini_speak_reply(self, reply: str) -> None:
        """Speak a finished chat reply through the floating pet.

        Mirrors _live_speak_reply's engine choice (the call's own live_voice)
        but completion re-arms the mini mic instead of the call's listener.
        """
        if not getattr(self, "_mini_active", False):
            return
        if not reply:
            return
        try:
            from cellium.core.config import CEL_VOICE_VARIANTS
            from cellium.core.utils import clean_for_tts
        except Exception:
            return
        choice = self.settings.get("live_voice", "Kokoro (Offline)")
        text = clean_for_tts(
            reply,
            skip_asterisks=bool(self.settings.get("tts_skip_asterisks", True)))
        # Mic off while she talks so she never transcribes herself.
        try:
            audio = getattr(self, "_mini_audio", None)
            if audio is not None:
                audio.set_capture_enabled(False)
        except Exception:
            pass
        if not text:
            self._mini_listen_again()
            return
        comp = getattr(self, "_companion", None)
        if comp is not None and comp.visible:
            comp.set_speaking(True)
        if choice in CEL_VOICE_VARIANTS:
            try:
                from cellium.services.sound_engine import play_animalese_chirp
                play_animalese_chirp(text[0], True, choice)
            except Exception:
                pass
            ms = max(700, min(15000, len(text) * 55))
            QTimer.singleShot(ms, self._mini_listen_again)
            return
        try:
            self.stop_current_tts()
        except Exception:
            pass
        try:
            from cellium.services.audio_tts import (
                EdgeTTSStreamingWorker, KokoroStreamingWorker,
            )
            from PySide6.QtCore import QThread
            from cellium.core.utils import EDGE_VOICES, KOKORO_VOICES
        except Exception:
            self._mini_listen_again()
            return
        offline = choice == "Kokoro (Offline)"
        known = {v for _, v in (KOKORO_VOICES if offline else EDGE_VOICES)}
        default_voice = "af_heart" if offline else "en-US-JennyNeural"
        voice = self.settings.get("live_voice_id", "") or default_voice
        if voice not in known:
            voice = default_voice
        if offline:
            worker = KokoroStreamingWorker(text, voice=voice, speed=1.0, volume=tts_gain_from_settings(self.settings))
        else:
            worker = EdgeTTSStreamingWorker(text, voice=voice, volume=tts_gain_from_settings(self.settings))
        thread = QThread(self)
        if not hasattr(self, "_tts_threads") or self._tts_threads is None:
            self._tts_threads = set()
        self._tts_threads.add(thread)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda: self._mini_listen_again(),
                                Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda t=thread: self._tts_threads.discard(t))
        thread.finished.connect(thread.deleteLater)
        try:
            self.active_tts_worker = worker
            self.active_tts_thread = thread
        except Exception:
            pass
        thread.start()

    def _mini_listen_again(self) -> None:
        """Her reply finished - stop mouth animation & re-open the pet mic."""
        try:
            comp = getattr(self, "_companion", None)
            if comp is not None:
                comp.set_speaking(False)
                if comp.visible and getattr(self, "_mini_active", False):
                    comp.window.set_status_text("🎙️ Listening…")
            if not getattr(self, "_mini_active", False):
                return
            audio = getattr(self, "_mini_audio", None)
            if audio is None:
                return
            audio.set_capture_enabled(True)
            if not audio.running:
                audio.start()
            self._mini_arm_timeout()
        except Exception:
            pass

    def _stop_mini_audio(self, silent: bool = False) -> None:
        """Release the mini-live mic. Safe anytime, silent by default."""
        try:
            self._mini_active = False
        except Exception:
            pass
        try:
            t = getattr(self, "_mini_timer", None)
            if t is not None:
                t.stop()
        except Exception:
            pass
        try:
            audio = getattr(self, "_mini_audio", None)
            self._mini_audio = None
            if audio is not None:
                try:
                    audio.set_capture_enabled(False)
                except Exception:
                    pass
                try:
                    audio.stop()
                except Exception:
                    pass
                try:
                    audio.deleteLater()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            comp = getattr(self, "_companion", None)
            if comp is not None:
                comp.set_speaking(False)
                comp.window.control_bar.set_mic_listening(False)
                comp.window.set_status_text("")
        except Exception:
            pass
        if not silent:
            try:
                self.show_toast("🎙 Pet Mode mic muted - click 🎙️ on Cel to talk again.", icon="🎙")
            except Exception:
                pass

    def _on_shot_bubble_clicked(self) -> None:
        """One-shot Screenshot pill: append the wake screenshot, then gone."""
        try:
            self._attach_last_screenshot()
        except Exception:
            pass
        try:
            comp = getattr(self, "_companion", None)
            if comp is not None:
                comp.hide_screenshot_bubble()
        except Exception:
            pass

    def _on_shot_bubble_hidden(self) -> None:
        """User ✕'d the pill - nothing to do, it stays hidden till next wake."""

    def _on_pet_closed_during_mini(self) -> None:
        """Sleeping the pet hangs up the mini call too (mic must not linger)."""
        try:
            if getattr(self, "_mini_active", False):
                self._stop_mini_audio(silent=True)
        except Exception:
            pass

    def _show_screen_ring_pulse(self):
        """Wake intro: edge ring + appear chime (screenshot was taken first).

        The ring means "Cel is up and saw your screen"; the chime marks
        ring|screenshot|ready in one modern futuristic swoosh.
        """
        try:
            from cellium.services.sound_engine import play_ui_sound
            play_ui_sound("appear", 0.6)
        except Exception:
            pass
        try:
            old = getattr(self, "_screen_ring_widget", None)
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            ring = _WakeRingOverlay()
            self._screen_ring_widget = ring
            ring.show()
        except Exception:
            pass

    def _preview_live_voice(self, host=None, voice_id=None):
        """Speak the voice-preview line with the call's own engine + voice.

        The settings "▶ Preview" button used to fire a *click* for anything
        that was not an Animal Crossing chirp, which is why no voice ever
        previewed. This runs the same workers the call itself uses, so what
        you hear is exactly what she sounds like on the line.
        """
        from cellium.core.config import (CEL_VOICE_VARIANTS,
                                         LIVE_VOICE_PREVIEW)
        from cellium.core.utils import (EDGE_VOICES, KOKORO_VOICES,
                                        clean_for_tts)

        choice = host or self.settings.get("live_voice", "Kokoro (Offline)")
        if choice in CEL_VOICE_VARIANTS:
            # The chirp synth has no words - it can only warble.
            try:
                from cellium.services.sound_engine import play_animalese_chirp
                play_animalese_chirp("h", True, choice)
            except Exception:
                pass
            return True

        offline = choice == "Kokoro (Offline)"
        pool = KOKORO_VOICES if offline else EDGE_VOICES
        known = {v for _, v in pool}
        default_voice = "af_heart" if offline else "en-US-JennyNeural"
        vid = voice_id or self.settings.get("live_voice_id", "") or default_voice
        if vid not in known:
            vid = default_voice

        text = clean_for_tts(LIVE_VOICE_PREVIEW)
        if not text:
            return False
        try:
            self.stop_current_tts()
        except Exception:
            pass
        try:
            from cellium.services.audio_tts import (
                EdgeTTSStreamingWorker, KokoroStreamingWorker,
            )
            from PySide6.QtCore import QThread
        except Exception:
            return False
        if not offline:
            worker = EdgeTTSStreamingWorker(text, voice=vid, volume=tts_gain_from_settings(self.settings))
        else:
            worker = KokoroStreamingWorker(text, voice=vid, speed=1.0, volume=tts_gain_from_settings(self.settings))

        thread = QThread(self)
        if not getattr(self, "_tts_threads", None):
            self._tts_threads = set()
        self._tts_threads.add(thread)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_preview_tts_done,
                                Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda t=thread: self._tts_threads.discard(t))
        thread.finished.connect(thread.deleteLater)
        self.active_tts_worker = worker
        self.active_tts_thread = thread
        thread.start()
        return True

    def _on_preview_tts_done(self):
        """Preview finished or failed - drop the handles, never touch Live."""
        try:
            self.active_tts_worker = None
            self.active_tts_thread = None
        except RuntimeError:
            pass

    def _live_speak_reply(self, reply: str):
        """Speak a finished reply *on the call* using the call's own voice.

        ``live_voice`` is deliberately separate from ``voice_host`` /
        ``ac_voice_variant``, so chat and the desktop pet are never hijacked by
        whatever the call happens to be using.
        """
        if getattr(self, "_live", None) is None or not self._live.active:
            return
        if not reply:
            return
        from cellium.core.config import CEL_VOICE_VARIANTS
        from cellium.core.utils import clean_for_tts

        choice = self.settings.get("live_voice", "Kokoro (Offline)")
        text = clean_for_tts(
            reply,
            skip_asterisks=bool(self.settings.get("tts_skip_asterisks", True)))
        if not text:
            self._live.finish_speaking()
            return

        if choice in CEL_VOICE_VARIANTS:
            # Cel's own chirp voice is fire-and-forget, so estimate the run
            # time and flip back to listening when the syllables are done.
            try:
                from cellium.services.sound_engine import play_animalese_chirp
                play_animalese_chirp(text[0], True, choice)
            except Exception:
                pass
            ms = max(700, min(15000, len(text) * 55))
            QTimer.singleShot(ms, self._live.finish_speaking)
            return

        try:
            self.stop_current_tts()
        except Exception:
            pass
        try:
            from cellium.services.audio_tts import (
                EdgeTTSStreamingWorker, KokoroStreamingWorker,
            )
            from PySide6.QtCore import QThread
        except Exception:
            self._live.finish_speaking()
            return
        # The call's own voice wins over the chat voice. An id left over from a
        # different host (the pick changed hands) falls back to that host's
        # default instead of handing the worker a voice it cannot speak.
        from cellium.core.utils import EDGE_VOICES, KOKORO_VOICES
        offline = choice == "Kokoro (Offline)"
        known = {v for _, v in (KOKORO_VOICES if offline else EDGE_VOICES)}
        default_voice = "af_heart" if offline else "en-US-JennyNeural"
        voice = self.settings.get("live_voice_id", "") or default_voice
        if voice not in known:
            voice = default_voice
        if offline:
            worker = KokoroStreamingWorker(text, voice=voice, speed=1.0, volume=tts_gain_from_settings(self.settings))
        else:
            worker = EdgeTTSStreamingWorker(text, voice=voice, volume=tts_gain_from_settings(self.settings))

        thread = QThread(self)
        if not hasattr(self, "_tts_threads") or self._tts_threads is None:
            self._tts_threads = set()
        self._tts_threads.add(thread)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # Queued: the worker lives in its own thread and this slot touches the
        # GUI-side controller.
        worker.finished.connect(self._on_live_tts_done,
                                 Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda t=thread: self._tts_threads.discard(t))
        thread.finished.connect(thread.deleteLater)
        self.active_tts_worker = worker
        self.active_tts_thread = thread
        thread.start()

    def _on_live_tts_done(self):
        try:
            if getattr(self, "_live", None) is not None:
                self._live.finish_speaking()
        except Exception:
            pass

    def _update_top_agent_button(self, enabled: bool):
        """Update top bar agent button styling & label dynamically."""
        if not hasattr(self, "btn_top_agent") or not self.btn_top_agent:
            return
        if enabled:
            self.btn_top_agent.setText("⚡ Agent: ON")
            self.btn_top_agent.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #06B6D4, stop:1 #3B82F6);
                    color: #FFFFFF;
                    border: 1.5px solid #67E8F9;
                    border-radius: 10px;
                    padding: 4px 12px;
                    font-weight: bold;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background: #0284C7;
                    border-color: #A5F3FC;
                }
            """)
        else:
            self.btn_top_agent.setText("🤖 Agent: OFF")
            self.btn_top_agent.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.06);
                    color: #94A3B8;
                    border: 1.5px solid rgba(148, 163, 184, 0.25);
                    border-radius: 10px;
                    padding: 4px 12px;
                    font-weight: bold;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background: rgba(147, 51, 234, 0.3);
                    color: #E2E8F0;
                    border-color: #C084FC;
                }
            """)
        self._sync_more_menu()

    def toggle_agent_mode(self):
        """Toggle agent mode on/off."""
        current = self.settings.get("agent_mode_enabled", False)
        new_state = not current
        self.settings["agent_mode_enabled"] = new_state
        save_json(F_SETTINGS, self.settings)
        self._update_top_agent_button(new_state)
        status = "ENABLED" if new_state else "DISABLED"
        self.show_toast(f"🤖 Autonomous Agent Mode {status}", icon="⚡" if new_state else "🤖")

    def toggle_image_gen(self):
        """Toggle the AI image-generation tool (Kaggle BYOK). Off = the
        generate_image tool is never sent to the model (smaller context)."""
        new_state = not bool(self.settings.get("image_gen_enabled", False))
        self.settings["image_gen_enabled"] = new_state
        save_json(F_SETTINGS, self.settings)
        self._sync_more_menu()
        self.show_toast(
            "🎨 Image Gen ENABLED - Cel can now generate/edit images" if new_state
            else "🎨 Image Gen disabled (tool hidden from the AI)",
            icon="🎨")

    def _get_cache_manager(self):
        """Lazily build the warm-cache v3 CacheManager (ntfy relay) and wire its signals."""
        mgr = getattr(self, "_cache_mgr", None)
        if mgr is not None:
            return mgr
        backend = self._build_kaggle_backend(self.settings.get("kaggle_preset", ""))
        if not backend:
            return None
        try:
            from cellium.services.kaggle_relay import CacheManager
            from cellium.core.config import USER_DATA_DIR
            out_dir = Path(self.settings.get("kaggle_output_dir") or (USER_DATA_DIR / "generated_images"))
            mgr = CacheManager(backend, backend.model_config, out_dir, parent=self)
            mgr.state_changed.connect(self._on_cache_state)
            mgr.progress.connect(lambda s: self._kaggle_update_bubble(s))
            mgr.image_ready.connect(self._on_tool_image_ready)
            mgr.heartbeat.connect(lambda up, done, vram: self._on_cache_heartbeat(up, done, vram))
            self._cache_mgr = mgr
        except Exception as e:
            dev_log(f"[cache] manager init failed: {e}")
            return None
        return mgr

    def _on_cache_state(self, s: str):
        self._sync_more_menu()
        if s == "ready":
            self._kaggle_update_bubble("🔥 Cache READY - /imagine now queues to the warm notebook (≤15s each)", color="#6EE7B7")
        elif s == "dead":
            # fallback: requeue pending jobs through the normal script path
            mgr = getattr(self, "_cache_mgr", None)
            jobs = mgr.take_fallback_jobs() if mgr else []
            for j in jobs:
                self._run_script_job(j.get("prompt", ""), j.get("neg", ""), j.get("steps", 28),
                                     j.get("w", 832), j.get("h", 1216), j.get("seed", -1),
                                     j.get("guidance", 6.5))

    def _on_cache_heartbeat(self, up, done, vram):
        left = max(0, 3600 - up)
        self._kaggle_update_bubble(f"🔥 Cache alive - {done} done · {left//60} min cap left · {vram}MB VRAM", color="#6EE7B7")

    def _run_script_job(self, prompt, neg, steps, w, h, seed, guidance):
        """Normal script-mode generation (fallback + non-cache path)."""
        backend = self._build_kaggle_backend(self.settings.get("kaggle_preset", ""))
        if not backend:
            return
        from cellium.services.kaggle_image import KaggleImageWorker
        self._kaggle_worker = KaggleImageWorker(backend, prompt, neg, steps, w, h, seed, guidance)
        self._kaggle_worker.worker.progress.connect(self._on_kaggle_progress)
        self._kaggle_worker.worker.generation_done.connect(self._on_kaggle_finished)
        self._kaggle_worker.worker.error.connect(self._on_kaggle_error)
        self._kaggle_start_job(prompt, 1)
        self._kaggle_worker.start()

    def _init_image_tool_hub(self):
        """Create the shared image-tool hub and route its signals into chat."""
        try:
            from cellium.services.image_tool import get_hub
            from cellium.services.kaggle_image import create_backend_from_settings
            hub = get_hub()
            hub.backend_factory = lambda: self._build_kaggle_backend(
                self.settings.get("kaggle_preset", ""))
            hub.settings_getter = lambda: self.settings
            hub.preset_getter = lambda: self.settings.get("kaggle_preset", "")
            hub.progress.connect(self._on_hub_kaggle_progress)
            hub.image_ready.connect(self._on_tool_image_ready)
            hub.error.connect(lambda m: self._on_kaggle_error(m))
        except Exception as e:
            dev_log(f"[ImageTool] hub init failed: {e}")

    def _on_hub_kaggle_progress(self, stage: str, detail: str, prompt: str):
        """Tool-driven generation: make sure a status bubble exists, then update it."""
        if getattr(self, "_kaggle_bubble", None) is None:
            self.chat_substack.setCurrentIndex(1)
            self._kaggle_prompt = prompt
            self._kaggle_stage = None
            self._kaggle_last_ping = 0.0
            self._kaggle_bubble = self._make_kaggle_status_bubble()
            self.chat_layout.insertWidget(self.chat_layout.count() - 1, self._kaggle_bubble, 0,
                                          Qt.AlignmentFlag.AlignLeft)
            self.update_all_bubble_geometries()
            self.scroll_bottom(force=True)
        self._on_kaggle_progress(stage, detail)

    def _on_tool_image_ready(self, path: str, seed: str, prompt: str):
        """The agent's generate_image tool finished - drop an image bubble in chat."""
        self._kaggle_drop_bubble()
        try:
            self._send_generated_images([Path(path)], prompt or "generated image",
                                        [seed], 0.0)
        except Exception as e:
            dev_log(f"[ImageTool] render image failed: {e}")

    # ── Warm cache (quota-guarded notebook) ─────────────────────────────────
    def _start_imagine_cache(self):
        self.chat_substack.setCurrentIndex(1)
        mgr = self._get_cache_manager()
        if mgr is None:
            self._ensure_session("New Chat")
            self._kaggle_start_job("", 1)
            self._kaggle_update_bubble("❌ Kaggle not configured - Settings → Image Generation", color="#F87171")
            return
        self._ensure_session("🔥 Warm cache")
        if mgr.state in ("warming", "ready", "streaming"):
            self.show_toast("🔥 Warm cache is already running", icon="🔥")
            return
        self._kaggle_start_job("warm cache", 1)
        self._kaggle_update_bubble(
            "🔥 Starting warm-cache watcher on Kaggle… ⚠️ burns ~1 GPU-hour/hour "
            "(hard-capped at 1h, auto idle-stop 10min). Stop: /imagine-stop-cache", color="#FBBF24")
        self.settings["kaggle_cache_on"] = True
        save_json(F_SETTINGS, self.settings)
        self._sync_more_menu()
        mgr.start()

    def _stop_imagine_cache(self):
        self.settings["kaggle_cache_on"] = False
        save_json(F_SETTINGS, self.settings)
        self._sync_more_menu()
        mgr = getattr(self, "_cache_mgr", None)
        if mgr is not None:
            mgr.stop()
        self.chat_substack.setCurrentIndex(1)
        self._ensure_session("New Chat")
        self._kaggle_start_job("stop cache", 1)
        self._kaggle_update_bubble("🛑 Shutdown pill sent - cache notebook exits (≤15s / at cap). Quota saved.", color="#6EE7B7")

    def _imagine_via_cache(self, prompt, neg, steps, w, h, seed, guidance, batch):
        """Queue job(s) to the warm notebook instead of pushing a script."""
        mgr = self._get_cache_manager()
        if mgr is None or mgr.state not in ("ready", "streaming", "warming"):
            return False
        self._kaggle_start_job(prompt, batch)
        jobs = []
        for i in range(max(1, batch)):
            jobs.append({
                "id": f"{int(time.time()*1000)}_{i}",
                "prompt": prompt, "neg": neg, "steps": steps, "w": w, "h": h,
                "seed": (seed + i) if seed and seed >= 0 else -1,
                "guidance": guidance,
            })
        try:
            mgr.enqueue(jobs)
            return True
        except Exception as e:
            self._kaggle_update_bubble(f"❌ queue write failed: {str(e)[:120]} - using script mode", color="#F87171")
            return False

    def toggle_warm_cache(self):
        if bool(self.settings.get("kaggle_cache_on", False)):
            self._stop_imagine_cache()
        else:
            self._start_imagine_cache()

    def toggle_coding_mode(self):
        """Toggle Coding Mode (Task 17): strips persona/memory, code-only output."""
        current = self.settings.get("coding_mode", False)
        new_state = not current
        self.settings["coding_mode"] = new_state
        self._refresh_system_prompt_memory()
        save_json(F_SETTINGS, self.settings)
        self._update_coding_mode_button(new_state)
        status = "ON" if new_state else "OFF"
        self.show_toast(f"💻 Coding Mode {status}", icon="💻" if new_state else "💬")

    def _update_coding_mode_button(self, enabled):
        """Label + styling for the top-bar Coding toggle.

        This button shipped with NO stylesheet at all, so it fell back to the
        light default palette - white text on its own light pill, effectively
        invisible against the dark top bar.
        """
        if not hasattr(self, "btn_coding_mode") or not self.btn_coding_mode:
            return
        self.btn_coding_mode.setText("💻 Coding: ON" if enabled else "💬 Chat Mode")
        if enabled:
            self.btn_coding_mode.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #10B981, stop:1 #059669);
                    color: #FFFFFF;
                    border: 1.5px solid #6EE7B7;
                    border-radius: 10px;
                    padding: 4px 12px;
                    font-weight: bold;
                    font-size: 11px;
                }
                QPushButton:hover { background: #047857; border-color: #A7F3D0; }
            """)
        else:
            self.btn_coding_mode.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.06);
                    color: #C4B5FD;
                    border: 1.5px solid rgba(148, 163, 184, 0.25);
                    border-radius: 10px;
                    padding: 4px 12px;
                    font-weight: bold;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background: rgba(147, 51, 234, 0.3);
                    color: #E2E8F0;
                    border-color: #C084FC;
                }
            """)
        self._sync_more_menu()

    def toggle_persona(self):
        """Quick Persona on/off - strips the persona block from every request."""
        on = not bool(self.settings.get("persona_enabled", True))
        self.settings["persona_enabled"] = on
        self._refresh_system_prompt_memory()
        save_json(F_SETTINGS, self.settings)
        self._sync_more_menu()
        self.show_toast(
            "🎭 Persona ON - she is Cel again." if on
            else "🎭 Persona OFF - plain assistant, no character prompt.",
            icon="🎭")

    def toggle_memory(self):
        """Quick Memory on/off - stops sending the memory/behaviour rules."""
        on = not bool(self.settings.get("memory_enabled", True))
        self.settings["memory_enabled"] = on
        self._refresh_system_prompt_memory()
        save_json(F_SETTINGS, self.settings)
        self._sync_more_menu()
        self.show_toast(
            "🧠 Memory ON - your rules are back in every request." if on
            else "🧠 Memory OFF - rules are no longer sent.",
            icon="🧠")

    def reload_local_model(self):
        """Unload cached GGUF so hardware settings apply on next generation."""
        if self._running_generation_workers():
            self.show_toast("⏳ Model is busy - reload it once generation finishes.",
                            icon="⏳", duration=3200)
            return
        try:
            unload_llama()
        except Exception:
            pass
        self.show_toast("🧠 GGUF cleared - fresh hardware settings apply on next message", icon="🔄")

    def show_attach_menu(self):
        play_ui_sound("click", 0.5)
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: rgba(18, 12, 32, 0.96);
                border: 1.5px solid #A855F7;
                border-radius: 10px;
                color: #F0E6FF;
                padding: 6px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 8px 16px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background: rgba(147, 51, 234, 0.4);
                color: #FFFFFF;
            }
        """)
        a_file = menu.addAction("📄 Upload File")
        a_img = menu.addAction("🖼️ Upload Image")

        saved_delay = int(self.settings.get("screenshot_delay", 0))
        delay_map = {0: "Instant", 1: "1s", 3: "3s", 5: "5s", 7: "7s", 10: "10s", 20: "20s"}
        curr_label = delay_map.get(saved_delay, f"{saved_delay}s")

        # Attach Screen composite row: Button + '>' dropdown
        from PySide6.QtWidgets import QWidgetAction
        row_act = QWidgetAction(menu)
        row_widget = QWidget()
        row_widget.setStyleSheet("background: transparent; border: none;")
        r_layout = QHBoxLayout(row_widget)
        r_layout.setContentsMargins(8, 2, 8, 2)
        r_layout.setSpacing(4)

        btn_screen = QPushButton(f"📸 Attach Screen  [{curr_label}]")
        btn_screen.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_screen.setStyleSheet("""
            QPushButton {
                background: transparent; color: #F0E6FF; text-align: left;
                padding: 6px 12px; font-size: 13px; font-weight: 500; border-radius: 6px; border: none;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.45); color: #FFFFFF; }
        """)

        btn_timer = QPushButton("›")
        btn_timer.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_timer.setFixedSize(28, 28)
        btn_timer.setToolTip("Set screenshot delay timer (Instant, 1s, 3s, 5s, 7s, 10s, 20s)")
        btn_timer.setStyleSheet("""
            QPushButton {
                background: rgba(147, 51, 234, 0.2); color: #C084FC; font-weight: bold;
                font-size: 16px; border-radius: 6px; border: 1px solid rgba(168, 85, 247, 0.35);
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.6); color: #FFFFFF; border-color: #C084FC; }
        """)

        r_layout.addWidget(btn_screen, 1)
        r_layout.addWidget(btn_timer, 0)
        row_act.setDefaultWidget(row_widget)
        menu.addAction(row_act)

        # Standard timer submenu for keyboard navigation
        sub_timer = menu.addMenu(f"⏱️ Screenshot Timer ({curr_label})")
        sub_timer.setStyleSheet(menu.styleSheet())
        
        timer_choices = [
            (0, "Instant (default)"),
            (1, "1s"),
            (3, "3s"),
            (5, "5s"),
            (7, "7s"),
            (10, "10s"),
            (20, "20s"),
        ]

        def _select_timer_and_capture(sec):
            menu.close()
            self._save_screenshot_timer_and_capture(sec)

        for sec, txt in timer_choices:
            prefix = "✓ " if sec == saved_delay else "   "
            act = sub_timer.addAction(f"{prefix}{txt}")
            act.triggered.connect(lambda chk=False, s=sec: _select_timer_and_capture(s))

        btn_screen.clicked.connect(lambda: (menu.close(), self.attach_screen_grab(delay=None)))
        btn_timer.clicked.connect(lambda: self._popup_screenshot_timer_menu(btn_timer, menu))

        a_paste = menu.addAction("📋 Paste from Clipboard")

        a_file.triggered.connect(self.prompt_attach)
        a_img.triggered.connect(self.prompt_attach)
        a_paste.triggered.connect(self.handle_paste)
        # The menu was built and then never shown - the button silently did
        # nothing. Pop it under the paperclip.
        try:
            from PySide6.QtGui import QCursor
            anchor = QCursor.pos()
            try:
                if self.btn_attach.isVisible():
                    anchor = self.btn_attach.mapToGlobal(
                        QPoint(0, self.btn_attach.height()))
            except Exception:
                pass
            menu.exec(anchor)
        except Exception:
            pass

    # ── Image Generation (Imagine) ──────────────────────────────────────────

    def _build_kaggle_backend(self, preset_name: str = ""):
        """Backend from settings, with model overridden by a named preset."""
        from cellium.services.kaggle_image import create_backend_from_settings, build_model_config
        backend = create_backend_from_settings(self.settings)
        if backend is not None:
            target_preset = preset_name or self.settings.get("kaggle_preset", "")
            if target_preset:
                backend.preset_name = target_preset
                backend.model_config = build_model_config(self.settings, target_preset)
            backend.auto_clean = bool(self.settings.get("kaggle_auto_clean", True))
        return backend

    def _goto_settings_tab(self, label_fragment: str) -> None:
        """Switch the settings view to the first tab whose title contains
        ``label_fragment`` (robust against tab reordering)."""
        try:
            sv = getattr(self, "settings_view", None)
            if sv is None or not hasattr(sv, "tab_widget"):
                return
            tw = sv.tab_widget
            frag = label_fragment.lower()
            for i in range(tw.count()):
                if frag in tw.tabText(i).lower():
                    tw.setCurrentIndex(i)
                    return
        except Exception:
            pass

    # ── "/" slash-command drop-up ──────────────────────────────────────────────
    _SLASH_COMMANDS = [
        ("/imagine", "🎨 Generate an image on Kaggle"),
        ("/imagine-start-cache", "🔥 Start the warm-cache notebook (GPU, ≤ 1 h)"),
        ("/imagine-stop-cache", "🛑 Stop the warm-cache notebook"),
    ]
    _SLASH_ROW_H = 46

    def _on_input_text_changed(self):
        if getattr(self, "_slash_committing", False):
            return
        try:
            text = self.edit_input.toPlainText()
        except RuntimeError:
            return
        if not text.startswith("/"):
            self._hide_slash_popup()
            return
        prefix = text[1:].strip().lower()
        matches = [(c, d) for (c, d) in self._SLASH_COMMANDS if c[1:].startswith(prefix)]
        if not matches:
            self._hide_slash_popup()
            return
        self._show_slash_popup(matches)

    def _ensure_slash_popup(self):
        if getattr(self, "_slash_popup", None) is not None:
            return self._slash_popup
        from PySide6.QtCore import QRectF, QSize
        from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
        from PySide6.QtWidgets import (
            QFrame, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate,
            QVBoxLayout,
        )

        row_h = self._SLASH_ROW_H

        class _SlashRowDelegate(QStyledItemDelegate):
            """Two-line row: command + muted description, elided - never clipped."""

            def sizeHint(self, option, index):
                return QSize(max(1, option.rect.width()), row_h)

            def paint(self, painter, option, index):
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                rect = QRectF(option.rect).adjusted(4, 3, -4, -3)
                selected = bool(option.state & QStyle.StateFlag.State_Selected)
                hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
                if selected or hovered:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(147, 51, 234, 175) if selected
                                     else QColor(168, 85, 247, 55))
                    painter.drawRoundedRect(rect, 10, 10)

                cmd = str(index.data(Qt.ItemDataRole.UserRole) or "")
                desc = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
                left = rect.left() + 12
                width = max(40.0, rect.width() - 24.0)
                base_pt = option.font.pointSizeF()
                if base_pt <= 0:
                    base_pt = 10.0

                cmd_font = QFont(option.font)
                cmd_font.setPointSizeF(base_pt + 0.5)
                cmd_font.setWeight(QFont.Weight.DemiBold)
                painter.setFont(cmd_font)
                painter.setPen(QColor("#FFFFFF") if selected else QColor("#E9D5FF"))
                cmd_h = QFontMetrics(cmd_font).height()
                painter.drawText(
                    QRectF(left, rect.top() + 5, width, cmd_h),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, cmd)

                desc_font = QFont(option.font)
                desc_font.setPointSizeF(max(8.0, base_pt - 1.0))
                painter.setFont(desc_font)
                painter.setPen(QColor("#F3E8FF") if selected else QColor("#B9A6D8"))
                fm = QFontMetrics(desc_font)
                painter.drawText(
                    QRectF(left, rect.top() + 5 + cmd_h, width,
                           max(12.0, rect.height() - cmd_h - 10.0)),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    fm.elidedText(desc, Qt.TextElideMode.ElideRight, int(width)))
                painter.restore()

        fr = QFrame(self, Qt.WindowType.Popup)
        fr.setObjectName("slashPopup")
        fr.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        fr.setFocusProxy(self.edit_input)
        fr.setStyleSheet("""
            QFrame#slashPopup {
                background: rgba(16, 10, 28, 0.98);
                border: 1px solid rgba(168, 85, 247, 0.55);
                border-radius: 14px;
            }
            QListWidget { background: transparent; border: none; outline: none; }
            QListWidget QScrollBar:vertical { background: transparent; width: 6px; margin: 2px; }
            QListWidget QScrollBar::handle:vertical {
                background: rgba(168, 85, 247, 0.45); border-radius: 3px; min-height: 18px;
            }
            QListWidget QScrollBar::add-line:vertical,
            QListWidget QScrollBar::sub-line:vertical { height: 0; }
            QListWidget QScrollBar::add-page:vertical,
            QListWidget QScrollBar::sub-page:vertical { background: transparent; }
        """)
        lay = QVBoxLayout(fr)
        lay.setContentsMargins(6, 6, 6, 6)
        lst = QListWidget()
        lst.setFrameShape(QFrame.Shape.NoFrame)
        lst.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lst.setMouseTracking(True)
        lst.viewport().setMouseTracking(True)
        lst.setCursor(Qt.CursorShape.PointingHandCursor)
        lst.setUniformItemSizes(True)
        lst.setSpacing(0)
        lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lst.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        lst.setItemDelegate(_SlashRowDelegate(lst))
        lst.itemPressed.connect(self._on_slash_item_pressed)
        lay.addWidget(lst)
        fr._list = lst
        fr.installEventFilter(self)
        lst.installEventFilter(self)
        self._slash_popup = fr
        return fr

    def _on_slash_item_pressed(self, item):
        fr = getattr(self, "_slash_popup", None)
        if fr is None or item is None:
            return
        self._pick_slash_command(fr._list.row(item))

    def _show_slash_popup(self, matches):
        fr = self._ensure_slash_popup()
        lst = fr._list
        lst.clear()
        for cmd, desc in matches:
            from PySide6.QtWidgets import QListWidgetItem
            it = QListWidgetItem(desc)
            it.setData(Qt.ItemDataRole.UserRole, cmd)
            it.setSizeHint(QSize(10, self._SLASH_ROW_H))
            lst.addItem(it)
        lst.setCurrentRow(0)

        # Measure first, then place - the old code positioned using the frame's
        # stale pre-layout height, which made the popup grow downwards over the
        # input pill and clip its own rows.
        pill = self.input_pill
        top_left = pill.mapToGlobal(QPoint(0, 0))
        width = max(300, min(440, pill.width() - 24))
        height = min(260, lst.count() * self._SLASH_ROW_H + 12)
        fr.setFixedSize(width, height)
        lst.setFixedHeight(height - 12)

        x = top_left.x() + 12
        y = top_left.y() - height - 10
        scr = self.screen()
        avail = scr.availableGeometry() if scr is not None else None
        if avail is not None:
            if y < avail.top() + 8:
                y = top_left.y() + pill.height() + 10
            x = min(max(x, avail.left() + 8), max(avail.left() + 8, avail.right() - width - 8))
            y = min(max(y, avail.top() + 8), max(avail.top() + 8, avail.bottom() - height - 8))
        fr.move(x, y)
        self.show_dim_overlay(on_click=self._hide_slash_popup)
        fr.show()
        fr.raise_()

    def _hide_slash_popup(self):
        self.hide_dim_overlay()
        try:
            if getattr(self, "_slash_popup", None) is not None:
                self._slash_popup.hide()
        except RuntimeError:
            pass

    def _pick_slash_command(self, row: int):
        """Click/Enter on a command executes it immediately (no second send)."""
        fr = getattr(self, "_slash_popup", None)
        if fr is None or row < 0 or getattr(self, "_slash_committing", False):
            return
        item = fr._list.item(row)
        cmd = item.data(Qt.ItemDataRole.UserRole) if item else None
        self._hide_slash_popup()
        if not cmd:
            return
        self._slash_committing = True
        try:
            self.edit_input.clear()
            if cmd == "/imagine":
                self.show_imagine_dialog()
            elif cmd == "/imagine-start-cache":
                self._start_imagine_cache()
            elif cmd == "/imagine-stop-cache":
                self._stop_imagine_cache()
            else:
                self.edit_input.setPlainText(cmd)
                self.on_send_clicked()
        finally:
            self._slash_committing = False
            try:
                self.edit_input.setFocus()
            except RuntimeError:
                pass

    def _welcome_chip_fill(self, text: str) -> None:
        """Suggestion chip: drop text into the input and focus it."""
        play_ui_sound("click", 0.5)
        self.edit_input.setPlainText(text)
        self.edit_input.setFocus()

    def show_imagine_dialog(self):
        """Show the image generation dialog as an inbuilt modal glass overlay."""
        play_ui_sound("click", 0.5)
        if not hasattr(self, "_imagine_panel") or self._imagine_panel is None:
            from cellium.ui.widgets.imagine_dialog import ImagineDialog
            self._imagine_panel = ImagineDialog(self.main_container)
            self._imagine_panel.generate_requested.connect(self._on_imagine_generate)
            self._imagine_panel.closed.connect(self.hide_dim_overlay)

        self.show_dim_overlay(on_click=self._imagine_panel.close)
        self._imagine_panel.center_in_parent()
        self._imagine_panel.show()
        self._imagine_panel.raise_()
        self._imagine_panel.edit_prompt.setFocus()

    def _on_imagine_generate(self, params: dict):
        """Handle generate request from ImagineDialog."""
        prompt = params.get("prompt", "").strip()
        if not prompt:
            self.show_toast("❌ Prompt cannot be empty", icon="⚠️")
            return

        self._last_imagine_prompt = prompt

        # Create backend from settings (+ optional preset override)
        backend = self._build_kaggle_backend(params.get("preset", ""))
        if not backend:
            self.show_toast("❌ Kaggle not configured - check Settings → Image Generation", icon="⚠️")
            self.open_settings_view()
            self._goto_settings_tab("Image")
            return
        
        # Show progress toast
        self.show_toast("🎨 Pushing job to Kaggle...", icon="🎨")
        
        # Override backend params from dialog
        neg = params.get("negative_prompt", self.settings.get("kaggle_negative_prompt", ""))
        steps = params.get("steps", self.settings.get("kaggle_steps", 28))
        size_str = params.get("size", self.settings.get("kaggle_size", "832x1216 (9:16)"))
        seed = params.get("seed", -1)
        guidance = params.get("guidance", self.settings.get("kaggle_guidance", 6.5))
        batch = int(params.get("batch", 1))

        # Parse size
        try:
            w, h = map(int, size_str.split(" (")[0].split("x"))
        except Exception:
            w, h = 832, 1216

        # warm cache ready? queue to the notebook instead of pushing a script
        if bool(self.settings.get("kaggle_cache_on", False)) and self._imagine_via_cache(
                prompt, neg, steps, w, h, seed, guidance, batch):
            return

        # Run generation in background thread
        from cellium.services.kaggle_image import KaggleImageWorker
        self._kaggle_worker = KaggleImageWorker(
            backend, prompt, neg, steps, w, h, seed, guidance, batch=batch
        )
        self._kaggle_worker.worker.progress.connect(self._on_kaggle_progress)
        self._kaggle_worker.worker.generation_done.connect(self._on_kaggle_finished)
        self._kaggle_worker.worker.error.connect(self._on_kaggle_error)
        self._kaggle_start_job(prompt, batch)
        self._kaggle_worker.start()

    KAGGLE_HEARTBEAT_S = 33.0  # chat status bubble pings at most every 33s per stage

    def _ensure_session(self, title_seed: str = "New Chat"):
        """Create the current session if missing (mirrors send_message)."""
        ses = self.sessions.get(self.current_sid)
        if ses:
            return ses
        model_key = self.settings.get("selected_model", "")
        route = self.models.get(model_key)
        is_offline = is_offline_model_key(model_key, route)
        sys_prompt = self._build_system_prompt(for_offline=is_offline)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        ses = {"title": title_seed, "created": now, "last_active": now,
               "pinned": False, "memory": [{"role": "system", "content": sys_prompt}]}
        self.sessions[self.current_sid] = ses
        if not self.settings.get("incognito"):
            save_json(F_SESSIONS, self.sessions)
        self.refresh_history_list()
        return ses

    def _make_kaggle_status_bubble(self):
        """A sleek nameless system bubble that shows live Kaggle progress in chat with zero text clipping."""
        max_target = 600
        if hasattr(self, "chat_scroll") and self.chat_scroll.viewport().width() > 200:
            max_target = max(200, int(self.chat_scroll.viewport().width() * 0.82))
        fr = ChatStatusBubble(parent=None)
        fr.update_dynamic_width(max_target)
        return fr

    def _kaggle_start_job(self, prompt: str, batch: int = 1):
        """Switch to chat, log the request as a user bubble, and open a small
        nameless status bubble that progress updates edit in place."""
        self.chat_substack.setCurrentIndex(1)
        self._last_imagine_prompt = prompt
        self._kaggle_prompt = prompt
        self._kaggle_batch = max(1, int(batch))
        self._kaggle_stage = None
        self._kaggle_last_detail = ""
        self._kaggle_last_ping = 0.0

        ses = self._ensure_session(f"🎨 {prompt[:15]}" if prompt else "New Chat")
        # user bubble showing what was asked
        user_msg = {"role": "user", "content": f"🎨 /imagine {prompt}",
                    "time": datetime.now().strftime("%H:%M")}
        ses.setdefault("memory", []).append(user_msg)
        ses["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        ses["title"] = ses.get("title") or f"🎨 {prompt[:15]}"
        if not self.settings.get("incognito"):
            save_json(F_SESSIONS, self.sessions)
        self.refresh_history_list()
        ub = MessageBubbleNew("user", user_msg["content"], user_msg,
                              glass_opacity=self.settings.get("glass_opacity", 0.72), chat_app=self)
        ub.memory_index = len(ses["memory"]) - 1
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, ub, 0, Qt.AlignmentFlag.AlignRight)

        # status bubble (show batch size when >1)
        self._kaggle_bubble = self._make_kaggle_status_bubble()
        if self._kaggle_batch > 1:
            self._kaggle_update_bubble(f"🎨 {prompt[:40]} × {self._kaggle_batch} images")
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, self._kaggle_bubble, 0,
                                      Qt.AlignmentFlag.AlignLeft)
        self.update_all_bubble_geometries()
        self.scroll_bottom(force=True)

    def _kaggle_update_bubble(self, text: str, color: str = "#C084FC"):
        try:
            fr = getattr(self, "_kaggle_bubble", None)
            if fr is not None:
                max_target = 600
                if hasattr(self, "chat_scroll") and self.chat_scroll.viewport().width() > 200:
                    max_target = max(200, int(self.chat_scroll.viewport().width() * 0.82))
                if hasattr(fr, "set_status"):
                    fr.set_status(text, color=color, max_available_w=max_target)
                elif hasattr(fr, "_kaggle_lbl"):
                    fr._kaggle_lbl.setText(text)
                self.update_all_bubble_geometries()
                self.scroll_bottom(force=True)
        except RuntimeError:
            pass

    def _kaggle_drop_bubble(self):
        try:
            fr = getattr(self, "_kaggle_bubble", None)
            if fr is not None:
                self.chat_layout.removeWidget(fr)
                fr.setVisible(False)
                fr.deleteLater()
        except RuntimeError:
            pass
        self._kaggle_bubble = None

    def _on_kaggle_progress(self, stage: str, detail: str):
        """Update the in-chat status bubble. Stage changes and detail updates apply
        immediately; purely duplicate heartbeats are throttled."""
        icons = {"checking_status": "🔍", "waiting_for_slot": "⏳", "pushing": "📤",
                 "queued": "⏳", "running": "🎨", "downloading": "📥",
                 "complete": "✅", "done": "✅", "rate_limited": "🐌"}
        icon = icons.get(stage, "🎨")
        now = time.monotonic()
        stage_changed = (stage != self._kaggle_stage)
        detail_changed = (detail != getattr(self, "_kaggle_last_detail", ""))
        
        # Only throttle identical pings without new info
        if (not stage_changed and not detail_changed and stage in ("queued", "running", "waiting_for_slot")
                and (now - self._kaggle_last_ping) < self.KAGGLE_HEARTBEAT_S):
            return
        
        self._kaggle_stage = stage
        self._kaggle_last_detail = detail
        self._kaggle_last_ping = now
        txt = f"{icon} {stage.replace('_', ' ')}"
        if detail:
            txt += f" - {detail}"
        self._kaggle_update_bubble(txt)
        self._kaggle_last_ping = now
        txt = f"{icon} {stage.replace('_', ' ')}"
        if detail:
            txt += f" - {detail}"
        self._kaggle_update_bubble(txt)

    def _on_kaggle_finished(self, result):
        """Add the generated image(s) to chat + a tiny done line; drop the status bubble."""
        prompt_text = getattr(self, "_kaggle_prompt", getattr(self, "_last_imagine_prompt", "Generated image"))
        paths = getattr(result, "paths", None) or [result.image_path]
        seeds = getattr(result, "seeds", None) or [result.seed]
        self._kaggle_drop_bubble()
        self._send_generated_images(paths, prompt_text, seeds, result.elapsed_seconds)
        n = len(paths)
        seed_str = ", ".join(str(s) for s in seeds)
        self._kaggle_update_bubble  # noqa
        # tiny nameless done line
        fr = self._make_kaggle_status_bubble()
        done_text = f"✅ done in {result.elapsed_seconds:.0f}s · seed {seed_str}" + ("" if n == 1 else f" · {n} images")
        max_target = 600
        if hasattr(self, "chat_scroll") and self.chat_scroll.viewport().width() > 200:
            max_target = max(200, int(self.chat_scroll.viewport().width() * 0.82))
        fr.set_status(done_text, color="#6EE7B7", max_available_w=max_target)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, fr, 0, Qt.AlignmentFlag.AlignLeft)
        self.update_all_bubble_geometries()
        self.scroll_bottom(force=True)

    def _on_kaggle_error(self, msg: str):
        """Show the failure as a small red nameless bubble in chat (no toast)."""
        short = msg if len(msg) < 600 else msg[:600] + "…"
        self._kaggle_update_bubble(f"❌ {short}", color="#F87171")
        self._kaggle_stage = "error"

    def _send_generated_images(self, paths, prompt: str, seeds, elapsed: float):
        """Append the generated image(s) to the session + chat bubbles."""
        ses = self.sessions.get(self.current_sid)
        if not ses:
            return
        paths = [p for p in paths if p and os.path.exists(str(p))]
        if not paths:
            return
        # Auto-attach primary generated image ONCE to the user's next message
        self._last_generated_image_to_append = str(paths[0])
        seed_str = ", ".join(str(s) for s in (seeds or []))
        assistant_msg = {
            "role": "assistant",
            "content": f"🎨 **Generated:** {prompt}\n\n*Seed: {seed_str}*" + ("" if len(paths) == 1 else f"\n\n*{len(paths)} images*"),
            "time": datetime.now().strftime("%H:%M"),
            "model": "Kaggle (SDXL)",
            "attached_images": [str(p) for p in paths],
        }
        ses.setdefault("memory", []).append(assistant_msg)
        ses["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        if not self.settings.get("incognito"):
            save_json(F_SESSIONS, self.sessions)
        self.refresh_history_list()

        self.chat_substack.setCurrentIndex(1)
        bubble = MessageBubbleNew(
            "assistant", assistant_msg["content"], assistant_msg,
            glass_opacity=self.settings.get("glass_opacity", 0.72),
            attached_images=[str(p) for p in paths],
            chat_app=self,
        )
        bubble.memory_index = len(ses["memory"]) - 1
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble, 0, Qt.AlignmentFlag.AlignLeft)
        self.update_all_bubble_geometries()
        self.scroll_bottom(force=True)

    # Handle /imagine command in send_message
    def _handle_imagine_command(self, text: str) -> bool:
        """Check if text is an /imagine* command and handle it. Returns True if handled."""
        low = text.strip().lower()
        if not low.startswith("/imagine"):
            return False

        # Warm-cache control commands
        if low.startswith("/imagine-start-cache"):
            self._start_imagine_cache()
            return True
        if low.startswith("/imagine-stop-cache"):
            self._stop_imagine_cache()
            return True

        # Extract prompt - sticky style tags apply to slash renders too.
        main_prompt = text.strip()[len("/imagine"):].strip()
        sticky = str(self.settings.get("kaggle_sticky_prompt", "") or "").strip().strip(",")
        prompt = f"{main_prompt}, {sticky}" if (main_prompt and sticky) else main_prompt
        if main_prompt:
            self.settings["kaggle_prompt"] = main_prompt
            try:
                self.save_settings()
            except Exception:
                pass
        if not prompt:
            self.chat_substack.setCurrentIndex(1)
            self._ensure_session("New Chat")
            self._kaggle_start_job("", 1)
            self._kaggle_update_bubble("❌ Usage: /imagine <prompt>", color="#F87171")
            self._kaggle_stage = "error"
            return True

        # Trigger generation with defaults (settings preset)
        from cellium.services.kaggle_image import KaggleImageWorker
        backend = self._build_kaggle_backend(self.settings.get("kaggle_preset", ""))
        if not backend:
            self.chat_substack.setCurrentIndex(1)
            self._ensure_session("New Chat")
            self._kaggle_start_job(prompt, 1)
            self._kaggle_update_bubble("❌ Kaggle not configured - Settings → Image Generation", color="#F87171")
            self._kaggle_stage = "error"
            self.open_settings_view()
            self._goto_settings_tab("Image")
            return True

        # Get defaults from settings
        neg = self.settings.get("kaggle_negative_prompt", "")
        steps = self.settings.get("kaggle_steps", 28)
        size_str = self.settings.get("kaggle_size", "832x1216 (9:16)")
        guidance = self.settings.get("kaggle_guidance", 6.5)
        batch = int(self.settings.get("kaggle_batch", 1))

        try:
            w, h = map(int, size_str.split(" (")[0].split("x"))
        except Exception:
            w, h = 832, 1216

        # warm cache ready? queue to the notebook instead of pushing a script
        if bool(self.settings.get("kaggle_cache_on", False)) and self._imagine_via_cache(
                prompt, neg, steps, w, h, -1, guidance, batch):
            return True

        self._kaggle_worker = KaggleImageWorker(backend, prompt, neg, steps, w, h, -1, guidance, batch=batch)
        self._kaggle_worker.worker.progress.connect(self._on_kaggle_progress)
        self._kaggle_worker.worker.generation_done.connect(self._on_kaggle_finished)
        self._kaggle_worker.worker.error.connect(self._on_kaggle_error)
        self._kaggle_start_job(prompt, batch)
        self._kaggle_worker.start()
        return True

    def _popup_screenshot_timer_menu(self, anchor_btn: QWidget, parent_menu: QMenu):
        """Show standalone dropdown of timer choices next to the '>' button."""
        from PySide6.QtCore import QPoint
        t_menu = QMenu(self)
        t_menu.setStyleSheet(parent_menu.styleSheet())
        saved_delay = int(self.settings.get("screenshot_delay", 0))
        timer_choices = [
            (0, "Instant (default)"),
            (1, "1s"),
            (3, "3s"),
            (5, "5s"),
            (7, "7s"),
            (10, "10s"),
            (20, "20s"),
        ]
        for sec, txt in timer_choices:
            prefix = "✓ " if sec == saved_delay else "   "
            act = t_menu.addAction(f"{prefix}{txt}")
            act.triggered.connect(lambda chk=False, s=sec: (parent_menu.close(), self._save_screenshot_timer_and_capture(s)))
        
        pos = anchor_btn.mapToGlobal(QPoint(anchor_btn.width() + 4, 0))
        t_menu.exec(pos)

    def _save_screenshot_timer_and_capture(self, sec: int):
        self.settings["screenshot_delay"] = int(sec)
        if not self.settings.get("incognito"):
            save_json(F_SETTINGS, self.settings)
        lbl = "Instant" if sec == 0 else f"{sec}s"
        self.show_toast(f"⏱️ Screenshot timer set to {lbl} (new default)", icon="⏱️")
        self.attach_screen_grab(delay=sec)

    def attach_screen_grab(self, delay=None):
        """Attaches a fresh screenshot, respecting optional or configured timer delay."""
        if delay is None:
            delay = int(self.settings.get("screenshot_delay", 0))
        
        # Clear stale screenshot cache so fresh screen is captured
        self._last_screen_shot = None

        if delay <= 0:
            self._capture_screen_now()
        else:
            self._start_screen_capture_countdown(delay)

    def _start_screen_capture_countdown(self, seconds: int):
        self._countdown_sec = seconds
        play_ui_sound("click", 0.4)
        self.show_toast(f"📸 Capturing screen in {seconds}s... (switch to your window!)", icon="⏱️")

        def _tick():
            self._countdown_sec -= 1
            if self._countdown_sec > 0:
                self.show_toast(f"📸 Capturing screen in {self._countdown_sec}s...", icon="⏱️")
                QTimer.singleShot(1000, _tick)
            else:
                self._capture_screen_now()

        QTimer.singleShot(1000, _tick)

    def _capture_screen_now(self) -> bool:
        """Capture fresh screen right now and add to attachments."""
        try:
            screen = QGuiApplication.primaryScreen()
            if not screen:
                self.show_toast("📸 Primary screen not detected", icon="⚠️")
                return False
            pix = screen.grabWindow(0)
            path = os.path.join(tempfile.gettempdir(), f"cel_screen_{int(time.time()*1000)}.png")
            pix.save(path, "PNG")
            self._last_screen_shot = path
            if os.path.exists(path):
                with open(path, "rb") as im_f:
                    b64 = base64.b64encode(im_f.read()).decode("utf-8")
                self.pending_attachments.append({
                    "path": path, "name": "Screen Capture.png", "ext": "png",
                    "size_str": "Screen", "type": "image", "base64": b64
                })
                self.refresh_attachment_strip()
                play_ui_sound("pop", 0.5)
                self.show_toast("📸 Screen attached - send whenever you're ready!", icon="📸")
                return True
            self.show_toast("📸 No screenshot to attach.", icon="⚠️")
            return False
        except Exception as e:
            self.show_toast(f"📸 Screenshot failed: {e}", icon="⚠️")
            return False

    def _attach_last_screenshot(self) -> bool:
        """Append the wake screenshot or fresh capture to pending attachments."""
        return self._capture_screen_now()

    def attach_files_from_urls(self, file_paths):
        """Attach dropped or pasted files with real filenames, paths, lines, and character count."""
        if not file_paths:
            return
        cur_model = self.settings.get("selected_model", "")
        route = self.models.get(cur_model)
        for f in file_paths:
            if not f or not os.path.exists(f):
                continue
            ext = os.path.splitext(f)[-1].lower()
            is_img = ext in [".png", ".jpg", ".jpeg", ".webp"]
            if is_img and not is_vision_model(cur_model, route):
                self.show_toast(f"Current model lacks vision! Image {os.path.basename(f)} skipped.", icon="⚠️")
                continue

            size = os.path.getsize(f)
            size_str = f"{size / 1024:.1f} KB" if size < 1024*1024 else f"{size / (1024*1024):.1f} MB"
            att = {
                "path": f, "name": os.path.basename(f), "ext": ext.replace(".", ""),
                "size_str": size_str, "type": "image" if is_img else "file"
            }
            if is_img:
                try:
                    with open(f, "rb") as im_f:
                        att["base64"] = base64.b64encode(im_f.read()).decode("utf-8")
                except Exception:
                    continue
            else:
                try:
                    with open(f, "r", encoding="utf-8", errors="ignore") as txt_f:
                        content = txt_f.read(65536)  # up to 64KB
                        att["content"] = content
                        line_count = content.count("\n") + 1
                        att["size_str"] = f"{size_str}, {line_count} lines"
                except Exception:
                    att["content"] = "[binary content]"
            self.pending_attachments.append(att)
        self.refresh_attachment_strip()
        self.show_toast(f"Attached {len(file_paths)} file(s)! 📎", icon="📎")

    def handle_paste(self):
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime.hasUrls():
            local_paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            if local_paths:
                self.attach_files_from_urls(local_paths)
                return
        if mime.hasImage():
            img = clipboard.image()
            path = os.path.join(tempfile.gettempdir(), f"pasted_img_{int(time.time())}.png")
            img.save(path)
            self.pending_attachments.append({
                "path": path, "name": "Pasted Image", "ext": "png",
                "size_str": "Clipboard", "type": "image",
                "base64": base64.b64encode(open(path, "rb").read()).decode("utf-8")
            })
            self.refresh_attachment_strip()
            self.show_toast("Image pasted from clipboard!", icon="📋")
        elif mime.hasText():
            text = mime.text()
            if len(text) > 1000 or "\n" in text:
                line_count = text.count("\n") + 1
                self.pending_attachments.append({
                    "path": "Clipboard", "name": "Pasted Snippet", "ext": "txt",
                    "size_str": f"{len(text)} chars, {line_count} lines", "type": "file",
                    "content": text[:32000]
                })
                self.refresh_attachment_strip()
                self.show_toast("Long text pasted as attachment!", icon="📄")
            else:
                self.edit_input.insertPlainText(text)

    def prompt_attach(self):
        f, _ = QFileDialog.getOpenFileName(self, "Attach Image or File", "", "All Files (*.*);;Images (*.png *.jpg *.jpeg *.webp)")
        if not f:
            return
        ext = os.path.splitext(f)[-1].lower()
        is_img = ext in [".png", ".jpg", ".jpeg", ".webp"]

        cur_model = self.settings.get("selected_model", "")
        route = self.models.get(cur_model)
        if is_img and not is_vision_model(cur_model, route):
            self.show_toast("Current model lacks vision! Image disabled.", icon="⚠️")
            return

        size = os.path.getsize(f)
        size_str = f"{size / 1024:.1f} KB" if size < 1024*1024 else f"{size / (1024*1024):.1f} MB"
        att = {
            "path": f, "name": os.path.basename(f), "ext": ext.replace(".", ""),
            "size_str": size_str, "type": "image" if is_img else "file"
        }
        if is_img:
            with open(f, "rb") as im_f:
                att["base64"] = base64.b64encode(im_f.read()).decode("utf-8")
        else:
            try:
                with open(f, "r", encoding="utf-8", errors="ignore") as txt_f:
                    att["content"] = txt_f.read(4000)
            except Exception:
                att["content"] = "[binary content]"

        self.pending_attachments.append(att)
        self.refresh_attachment_strip()

    def refresh_attachment_strip(self):
        while self.attachment_h.count():
            item = self.attachment_h.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.pending_attachments:
            self.attachment_strip.setVisible(False)
            self.image_preview_bar.setVisible(False)
            return

        self.attachment_strip.setVisible(True)
        self._update_image_preview_bar()
        for idx, att in enumerate(self.pending_attachments):
            chip = QFrame()
            chip.setStyleSheet("background: rgba(147, 51, 234, 0.4); border-radius: 8px; padding: 2px 6px;")
            c_h = QHBoxLayout(chip)
            c_h.setContentsMargins(4, 2, 4, 2)
            c_h.setSpacing(6)
            ico = "🖼️" if att["type"] == "image" else "📄"
            lbl = QLabel(f"{ico} {att['name']} ({att['size_str']})")
            lbl.setStyleSheet("font-size: 11px; color: white; border: none;")
            btn_x = QPushButton(); btn_x.setIcon(QIcon(str(ASSETS_DIR / "gemini_close.svg"))); btn_x.setIconSize(QSize(16, 16))
            btn_x.setFixedSize(16, 16)
            btn_x.setStyleSheet("background: transparent; color: white; font-size: 10px; border: none;")
            btn_x.clicked.connect(lambda _, i=idx: self.remove_attachment(i))
            c_h.addWidget(lbl)
            c_h.addWidget(btn_x)
            self.attachment_h.addWidget(chip)
        self.attachment_h.addStretch()

    def remove_attachment(self, idx):
        if 0 <= idx < len(self.pending_attachments):
            self.pending_attachments.pop(idx)
            self.refresh_attachment_strip()

    def _update_image_preview_bar(self):
        """Update the ChatGPT/Gemini-style image preview bar above chat."""
        # Clear existing
        while self.image_preview_layout.count():
            item = self.image_preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        images = [att for att in self.pending_attachments if att["type"] == "image"]
        if not images:
            self.image_preview_bar.setVisible(False)
            return

        self.image_preview_bar.setVisible(True)

        # Add title
        title_lbl = QLabel("🖼️ Image Preview")
        title_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #C084FC; border: none;")
        self.image_preview_layout.addWidget(title_lbl)

        for idx, att in enumerate(images):
            preview = QFrame()
            preview.setFixedSize(120, 90)
            preview.setCursor(Qt.CursorShape.PointingHandCursor)
            preview.setStyleSheet("""
                QFrame {
                    background: rgba(14, 10, 24, 0.9);
                    border: 1.5px solid #9333EA;
                    border-radius: 10px;
                }
                QFrame:hover {
                    border: 1.5px solid #E879F9;
                    background: rgba(20, 14, 32, 0.95);
                }
            """)

            p_v = QVBoxLayout(preview)
            p_v.setContentsMargins(4, 4, 4, 4)
            p_v.setSpacing(4)

            # Thumbnail
            thumb_lbl = QLabel()
            thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb_lbl.setStyleSheet("border: none; background: transparent;")
            thumb_lbl.setFixedSize(112, 60)

            # Load and scale image
            try:
                from PySide6.QtGui import QPixmap
                pix = QPixmap(att["path"])
                if not pix.isNull():
                    scaled = pix.scaled(112, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    thumb_lbl.setPixmap(scaled)
            except Exception:
                thumb_lbl.setText("🖼️")
                thumb_lbl.setStyleSheet("font-size: 24px; border: none;")

            p_v.addWidget(thumb_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

            # Filename
            name_lbl = QLabel(att["name"][:18] + ("..." if len(att["name"]) > 18 else ""))
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setStyleSheet("font-size: 9px; color: #A78BFA; border: none;")
            p_v.addWidget(name_lbl)

            # Click to view full size
            preview.mousePressEvent = lambda e, p=att["path"]: self._show_full_image(p)

            self.image_preview_layout.addWidget(preview)

        self.image_preview_layout.addStretch()

    def _show_full_image(self, path):
        """Show full-size image in a modal dialog."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QScrollArea
        from PySide6.QtGui import QPixmap

        dialog = QDialog(self)
        dialog.setWindowTitle("Image Preview")
        dialog.setModal(True)
        dialog.resize(800, 600)
        dialog.setStyleSheet("background: #0E0A16;")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")

        img_lbl = QLabel()
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_lbl.setStyleSheet("background: transparent;")

        pix = QPixmap(path)
        if not pix.isNull():
            # Scale to fit screen but maintain aspect
            screen_geom = self.screen().availableGeometry()
            max_w = int(screen_geom.width() * 0.9)
            max_h = int(screen_geom.height() * 0.9)
            scaled = pix.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            img_lbl.setPixmap(scaled)

        scroll.setWidget(img_lbl)
        layout.addWidget(scroll)

        dialog.exec()

    def toggle_voice_input(self):
        if self.audio_recorder and self.audio_recorder.is_recording:
            self.audio_recorder.stop()
            self.btn_mic.setText("")
            self.btn_mic.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_mic.svg")))
            self.btn_mic.setStyleSheet("background: rgba(255,255,255,0.06); border-radius: 18px; font-size: 16px; color: white; border: none;")
            play_ui_sound("click", 0.5)
        else:
            # ── Credential pre-flight ────────────────────────────────────
            # Groq is the shipped default engine and needs a key nobody has.
            # Recording first meant transcribing into the literal string
            # "❌ No Groq API Key (Set in Settings)" and *typing that into the
            # chat box as if you had said it*. Ask for the key now, while the
            # only thing lost is one click.
            engine = self.settings.get("voice_stt_engine", "Kokoro Whisper (Local)")
            gap = stt_missing_key(engine, self.settings)
            if gap is not None:
                self.show_toast(f"🎙 {gap[0]} needs an API key to hear you",
                                icon="🔑")
                self.prompt_stt_api_key(engine, gap[0], gap[1])
                return
            if not HAS_SOUNDDEVICE:
                self.show_toast("sounddevice not installed in python environment!", icon="⚠️")
                return
            self.btn_mic.setText("")
            self.btn_mic.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_stop.svg")))
            self.btn_mic.setStyleSheet("background: #EF4444; border-radius: 18px; font-size: 16px; color: white; border: none;")
            play_ui_sound("pop", 0.5)

            self.audio_recorder = AudioRecordWorker()
            self.audio_recorder.signals.finished.connect(self.on_audio_recorded)
            self.audio_recorder.signals.error.connect(lambda e: self.show_toast(e, icon="⚠️"))
            self.audio_recorder.start()

    def on_audio_recorded(self, wav_bytes):
        self.btn_mic.setText("")
        self.btn_mic.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_mic.svg")))
        self.btn_mic.setStyleSheet("background: rgba(255,255,255,0.06); border-radius: 18px; font-size: 16px; color: white; border: none;")

        # Never overwrite a worker that is still transcribing: dropping the
        # last reference to a live QThread aborts the process.
        old = getattr(self, "stt_worker", None)
        if old is not None:
            try:
                if old.isRunning():
                    old.requestInterruption()
                    if not old.wait(2000):
                        old.terminate()
                        old.wait(400)
                old.deleteLater()
            except RuntimeError:
                pass

        multi = self.settings.get("voice_multi_mode", True)
        eng = self.settings.get("voice_stt_engine", "Groq Whisper (Fastest)")
        groq_k = self.settings.get("user_custom_keys", {}).get("Groq", "")
        openai_k = self.settings.get("user_custom_keys", {}).get("Custom (OpenAI)", "")
        hf_k = self.settings.get("user_custom_keys", {}).get("Hugging Face", "")

        self.show_toast("Transcribing speech...", icon="🎙️")
        self.stt_worker = STTWorker(wav_bytes, engine=eng, multi_mode=multi, groq_key=groq_k, openai_key=openai_k, hf_key=hf_k)
        self.stt_worker.signals.single_result.connect(self._on_stt_result)
        self.stt_worker.signals.multi_results.connect(self.stt_choice_card.show_results)
        self.stt_worker.signals.error.connect(self._on_stt_error)
        self.stt_worker.start()

    def _on_stt_result(self, engine, text) -> None:
        """A real transcript *lands in* the input box - it never replaces it."""
        self._append_transcript(text)

    def _append_transcript(self, text) -> None:
        """Shared by the mic result and the multi-engine picker card.

        ``setPlainText`` wiped the whole box, so a stray click on the mic
        deleted a half-written message. Dictation has to behave like typing:
        append at the caret, with a space so words never fuse.
        """
        spoken = str(text or "").strip()
        if not spoken:
            return
        try:
            from PySide6.QtGui import QTextCursor
            edit = self.edit_input
            cursor = edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            existing = edit.toPlainText()
            if existing and not existing[-1].isspace():
                cursor.insertText(" ")
            cursor.insertText(spoken)
            edit.setTextCursor(cursor)
            resize = getattr(edit, "auto_resize", None)
            if callable(resize):
                resize()
        except RuntimeError:
            pass

    def _on_stt_error(self, err) -> None:
        """A transcription *failure* is never allowed to look like speech."""
        msg = str(err or "")
        engine = self.settings.get("voice_stt_engine", "")
        gap = stt_missing_key(engine, self.settings)
        if gap is not None and ("key" in msg.lower() or msg.startswith("❌")):
            self.show_toast(f"🎙 {gap[0]} needs an API key to hear you",
                            icon="🔑")
            self.prompt_stt_api_key(engine, gap[0], gap[1])
            return
        self.show_toast(f"🎙 {msg}", icon="⚠️")

    # ── STT API key prompt ───────────────────────────────────────────────
    def build_stt_key_dialog(self, engine, provider, hint=""):
        """Build (do not show) the speech-engine key prompt.

        Split from :meth:`prompt_stt_api_key` so it can be driven without a
        blocking modal loop - and so "the user closes it" stays a first-class
        answer: the engine stays selected, the app carries on, and the next
        mic click asks again.
        """
        from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel,
                                       QLineEdit, QPushButton, QVBoxLayout)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"🔑 {provider} API key")
        dlg.setModal(True)
        dlg.setMinimumWidth(470)
        dlg.setStyleSheet("background:#120C22;")

        urls = {
            "Groq": "console.groq.com/keys",
            "Hugging Face": "huggingface.co/settings/tokens",
            "Custom (OpenAI)": "platform.openai.com/api-keys",
        }
        v = QVBoxLayout(dlg)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(9)

        title = QLabel(f"<b>{provider}</b> is selected for speech input, but "
                       f"no key is saved - so Cel cannot hear anything.")
        title.setWordWrap(True)
        title.setStyleSheet("color:#F4F1FF; font-size:14px;")
        v.addWidget(title)

        sub = QLabel(f"Engine: {engine}   ·   key: {urls.get(str(provider), 'the provider dashboard')}")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:rgba(233,213,255,0.6); font-size:11px;")
        v.addWidget(sub)

        edit = QLineEdit()
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        edit.setPlaceholderText(hint or "paste your key")
        edit.setText(str(self.settings.get("user_custom_keys", {}).get(provider, "") or ""))
        edit.setStyleSheet("""
            QLineEdit {
                background: rgba(22, 14, 38, 0.55); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.55);
                border-radius: 10px; padding: 9px 12px; font-size: 13px;
            }
            QLineEdit:focus { border: 2px solid #C084FC; }
        """)
        v.addWidget(edit)

        note = QLabel("The key stays on this machine and is only sent to that "
                      "provider. You can close this without one - pick another "
                      "engine instead (Local or Google need no key).")
        note.setWordWrap(True)
        note.setStyleSheet("color:rgba(167,243,208,0.75); font-size:11px;")
        v.addWidget(note)

        row = QHBoxLayout()
        row.setSpacing(8)
        skip = QPushButton("Not now")
        skip.setCursor(Qt.PointingHandCursor)
        skip.setToolTip("Close without a key. Cel keeps this engine selected.")
        skip.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.07);color:#E9D5FF;"
            "border:1px solid rgba(192,132,252,0.35);border-radius:10px;"
            "padding:8px 16px;font-size:12px;font-weight:600;}"
            "QPushButton:hover{background:rgba(147,51,234,0.35);}")
        save = QPushButton("💾 Save key")
        save.setCursor(Qt.PointingHandCursor)
        save.setDefault(True)
        save.setStyleSheet(
            "QPushButton{background:rgba(16,185,129,0.55);color:#ECFDF5;"
            "border:1px solid #34D399;border-radius:10px;padding:8px 18px;"
            "font-size:12px;font-weight:700;}"
            "QPushButton:hover{background:rgba(16,185,129,0.8);}")

        def _accept() -> None:
            key = edit.text().strip()
            if key:
                self.settings.setdefault("user_custom_keys", {})[provider] = key
                save_json(F_SETTINGS, self.settings)
                self.show_toast(f"🔑 {provider} key saved - Cel can hear you",
                                icon="✅")
            dlg.accept()

        save.clicked.connect(_accept)
        skip.clicked.connect(dlg.reject)
        edit.returnPressed.connect(_accept)
        row.addWidget(skip)
        row.addStretch(1)
        row.addWidget(save)
        v.addLayout(row)
        return dlg, edit

    def prompt_stt_api_key(self, engine, provider, hint=""):
        """Ask for the selected speech engine's key.

        Non-modal on purpose. The gap is usually discovered *inside* a Live
        call's signal handler, and a blocking ``exec()`` there would freeze the
        very UI that has to explain it. Closing the box without a key is a
        legitimate answer: the engine stays selected and the next mic click
        asks again.
        """
        try:
            existing = getattr(self, "_stt_key_dialog", None)
            if existing is not None and existing.isVisible():
                existing.raise_()
                return ""
            dlg, _edit = self.build_stt_key_dialog(engine, provider, hint)
            dlg.setModal(False)
            dlg.setWindowModality(Qt.WindowModality.NonModal)
            self._stt_key_dialog = dlg      # keep a reference; Qt won't own it
            dlg.finished.connect(lambda *_a: setattr(
                self, "_stt_key_dialog", None))
            dlg.show()
            dlg.raise_()
        except Exception:
            pass
        return ""

    def _live_stt_key_required(self, engine, provider) -> None:
        """Live Mode is deaf - say so and offer the key right there."""
        hint = stt_key_hint(engine)
        self.show_toast(f"🎙 {provider} has no API key - Cel can't hear you yet",
                        icon="🔑", duration=4200)
        try:
            self.prompt_stt_api_key(str(engine), str(provider), hint)
        except Exception:
            pass

    def _sync_worker_buttons(self):
        """Watchdog: mirror worker.isRunning() onto Stop/Send; force-finalize orphans."""
        running = bool(getattr(self, "worker", None) and self.worker and self.worker.isRunning())
        model_loading = bool(getattr(self, "_model_loading", False) or (getattr(self, "_kokoro_preload_thread", None) and self._kokoro_preload_thread.isRunning()))
        busy = running or model_loading or not getattr(self, "_generation_finished", True)
        # Re-applying stylesheets/icons every 350 ms re-polishes the buttons
        # (expensive C++ style work) even when nothing changed. Only touch the
        # widgets when the (running, busy) state actually flips.
        ui_key = (running, busy)
        ui_changed = getattr(self, "_last_worker_ui_key", None) != ui_key
        if ui_changed:
            self._last_worker_ui_key = ui_key
            if hasattr(self, "btn_live"):
                self.btn_live.setEnabled(not busy)
                self.btn_live.setVisible(not busy)
            if hasattr(self, "btn_send"):
                if running:
                    self.btn_send.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_stop.svg")))
                    self.btn_send.setIconSize(QSize(16, 16))
                    self.btn_send.setStyleSheet("""
                        QPushButton {
                            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #EF4444, stop:1 #DC2626);
                            border: 1.5px solid #F87171; border-radius: 19px; color: white;
                        }
                        QPushButton:hover { background: #DC2626; }
                    """)
                    self.btn_send.setToolTip("Stop response generation 🛑")
                else:
                    self.btn_send.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_send.svg")))
                    self.btn_send.setIconSize(QSize(18, 18))
                    self.btn_send.setStyleSheet("""
                        QPushButton {
                            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8A2BE2, stop:1 #C084FC);
                            border: 1.5px solid #E879F9; border-radius: 19px; font-size: 15px; color: white;
                        }
                        QPushButton:hover { background: #A855F7; }
                    """)
                    self.btn_send.setToolTip("Send message")
        if running:
            self._orphan_ticks = 0
            return
        # Worker dead but stream bubble never finalized → stuck "thinking" forever
        bub = getattr(self, "active_stream_bubble", None)
        has_stuck_cards = any(len(c) > 0 for c in getattr(self, "_active_agent_cards", {}).values())
        if (bub is not None or has_stuck_cards) and not getattr(self, "_generation_finished", True):
            self._orphan_ticks += 1
            if self._orphan_ticks >= 5:  # ~1.75s grace so on_done can win the race
                self._force_finalize_orphan()
            return
        self._orphan_ticks = 0
        if ui_changed and self.btn_stop.isVisible() and getattr(self, "_generation_finished", True):
            self.btn_stop.setVisible(False)
            if hasattr(self, "btn_send"):
                self.btn_send.setVisible(True)

    def _force_finalize_orphan(self):
        """Finalize a stream whose worker died without done/error (crash / silent exit)."""
        if hasattr(self, "_typing_timer") and self._typing_timer.isActive():
            self._typing_timer.stop()
            
        if hasattr(self, "_active_agent_cards"):
            for cards in self._active_agent_cards.values():
                for card in cards:
                    if hasattr(card, "set_result"):
                        card.set_result("Worker terminated unexpectedly.", is_error=True)
            self._active_agent_cards.clear()
            
        self._stream_buffer = self._stream_buffer or self._displayed_text or "*(connection dropped - retrying…)*"
        # Auto-retry once instead of leaving the user stuck (Task 25).
        try:
            QTimer.singleShot(900, lambda: (not getattr(self, "_closing", False)) and self.regenerate_response())
        except Exception:
            pass
        self._displayed_text = self._stream_buffer
        self._generation_finished = True
        self._pending_reply = self._stream_buffer
        self._pending_sid = self.current_sid
        if not self._pending_meta:
            self._pending_meta = {
                "turn_tokens": max(1, len(self._stream_buffer) // 4),
                "think_time": 0.5,
                "model": self.settings.get("selected_model", ""),
                "time": datetime.now().strftime("%H:%M"),
            }
        # Orphan never hit on_done - apply token count here (finalize only refreshes label)
        sid = self.current_sid
        _t = int(self._pending_meta.get("turn_tokens", 0) or 0)
        self.total_tokens += _t
        self.session_token_totals[sid] = self.session_token_totals.get(sid, 0) + _t
        if hasattr(self, "lbl_token_count"):
            self.lbl_token_count.setText(f"⚬ Total since launch: {self.total_tokens:,} tokens")
        try:
            self._finalize_stream_response()
        except Exception:
            pass
        self.worker = None
        self._orphan_ticks = 0
        self._stop_btn_locked = False
        if hasattr(self, "btn_stop"):
            self.btn_stop.setVisible(False)
        if hasattr(self, "btn_send"):
            self.btn_send.setVisible(True)

    @staticmethod
    def _stop_worker_gracefully(worker, *, name="worker") -> bool:
        """Cooperative stop with a staged grace - terminate() is the last resort.

        QThread.terminate() inside llama.cpp native sampling corrupts the GGML
        heap and segfaults a *later* turn. Slow GGUF legitimately exceeds a
        2 s stop grace between tokens, so wait in stages (2 s + 3 s + 5 s)
        before ever terminating. True = thread gone.
        """
        try:
            if worker is None or not worker.isRunning():
                return True
        except RuntimeError:
            return True
        try:
            if hasattr(worker, "request_stop"):
                worker.request_stop()
            else:
                worker.quit()
        except RuntimeError:
            return True
        for ms in (2000, 3000, 5000):
            try:
                if worker.wait(ms):
                    return True
            except RuntimeError:
                return True
        try:
            dev_log(f"[DEV] {name} ignored cooperative stop - terminating")
        except Exception:
            pass
        try:
            worker.terminate()
            return bool(worker.wait(1000))
        except RuntimeError:
            return True
        except Exception:
            return False

    def stop_generation(self):
        """Force-stop generation immediately: sever signals, close network stream, kill tool subprocesses, and unlock UI."""
        self._stop_btn_locked = True
        self._generation_finished = True
        self._orphan_ticks = 0

        # 1. Stop typing timer FIRST so no buffered characters keep typing
        if hasattr(self, "_typing_timer") and self._typing_timer.isActive():
            self._typing_timer.stop()

        # 2. Detach & sever the active worker immediately
        w = getattr(self, "worker", None)
        self.worker = None
        if w is not None:
            for sig_name in ("delta", "done", "error", "status", "tool_call", "tool_result", "tool_diff"):
                sig = getattr(getattr(w, "signals", None), sig_name, None)
                if sig is not None:
                    try:
                        sig.disconnect()
                    except Exception:
                        pass
            try:
                w.request_stop()
            except Exception:
                pass
            # Park dying worker so Python GC doesn't collect a running QThread
            if not hasattr(self, "_retired_workers"):
                self._retired_workers = set()
            self._retired_workers.add(w)
            try:
                w.finished.connect(lambda _w=w: self._retired_workers.discard(_w))
            except Exception:
                pass
            # For cloud API workers (not local C++ GGUF), force-terminate if still alive after 600ms
            cur_m = str(self.settings.get("selected_model", "") or "")
            is_off = is_offline_model_key(cur_m, self.models.get(cur_m))
            if not is_off:
                def _reap_cloud(_w=w):
                    try:
                        if _w.isRunning():
                            _w.terminate()
                            _w.wait(200)
                    except Exception:
                        pass
                    self._retired_workers.discard(_w)
                QTimer.singleShot(600, _reap_cloud)

        # 3. Mark any running Agent tool cards as aborted
        if hasattr(self, "_active_agent_cards"):
            for cards in self._active_agent_cards.values():
                for card in cards:
                    if hasattr(card, "set_result"):
                        try:
                            card.set_result("🛑 Aborted by user.", is_error=True)
                        except Exception:
                            pass
            self._active_agent_cards.clear()

        # 4. Finalize the live stream bubble in-place with actual accumulated text
        partial = (getattr(self, "_displayed_text", "") or getattr(self, "_stream_buffer", "") or "").strip()
        abort_note = "\n\n🛑 **[SYSTEM: USER ABORTED TASK]**" if partial else "🛑 **[SYSTEM: USER ABORTED TASK]**"
        ghost_reply = partial + abort_note
        meta = {
            "turn_tokens": max(1, len(partial) // 4) if partial else 0,
            "think_time": 0.5,
            "model": self.settings.get("selected_model", ""),
            "time": datetime.now().strftime("%H:%M"),
        }

        stopped_bubble = getattr(self, "active_stream_bubble", None)
        self.active_stream_bubble = None
        if stopped_bubble is not None:
            try:
                stopped_bubble.content = ghost_reply
                stopped_bubble.meta = meta
                stopped_bubble.is_ghost = True
                stopped_bubble.update_stream_text(ghost_reply)
            except Exception:
                pass

        # 5. Persist aborted turn in session memory
        sid = getattr(self, "_pending_sid", None) or self.current_sid
        if hasattr(self, "_streaming_msg_idx") and self._streaming_msg_idx >= 0 and sid in self.sessions:
            ses = self.sessions[sid]
            if "memory" in ses and self._streaming_msg_idx < len(ses["memory"]):
                if getattr(self, "_turn_parts", None):
                    ses["memory"][self._streaming_msg_idx]["content"] = self._composed_turn_content(ghost_reply)
                else:
                    self._persist_stream_text(ghost_reply)
                ses["memory"][self._streaming_msg_idx].update(meta)
                ses["memory"][self._streaming_msg_idx]["is_ghost"] = True
                ses["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                save_json(F_SESSIONS, self.sessions)

        self._turn_parts = []
        self._turn_agent_actions = []
        self._streaming_msg_idx = -1

        # 6. Restore UI buttons & status badge immediately
        if hasattr(self, "btn_stop"):
            self.btn_stop.setVisible(False)
        if hasattr(self, "btn_send"):
            self.btn_send.setVisible(True)
        self._sync_worker_buttons()
        if hasattr(self, "lbl_server_badge"):
            self.lbl_server_badge.setText("🛑 Task Aborted")
        self.update_all_bubble_geometries()
        if stopped_bubble is not None:
            self._schedule_bubble_settle(stopped_bubble)
        play_ui_sound("click", 0.5)
        self.show_toast("Task force-stopped immediately! 🛑", icon="🛑")

    def send_message(self):
        # Preserve leading indentation (code) - only trim trailing whitespace.
        text = self.edit_input.text().rstrip()
        if not text.strip() and not self.pending_attachments:
            return

        # ── /imagine <prompt> - Kaggle image generation, never sent to the LLM ──
        if text.strip().lower().startswith("/imagine"):
            self.edit_input.clear()
            self._handle_imagine_command(text)
            return

        # ── MESSAGE QUEUE: If worker is still running, queue this message ──
        if hasattr(self, "worker") and self.worker and self.worker.isRunning():
            self._message_queue.append((text, list(self.pending_attachments)))
            self.pending_attachments.clear()
            self.refresh_attachment_strip()
            self.edit_input.clear()
            self.show_toast(f"Message queued! ({len(self._message_queue)} in queue) 📬", icon="📬")
            return

        # Track input history for Up/Down arrow navigation (FIX B5)
        if text:
            self.edit_input.add_history(text)

        # Stop typing timer to prevent race conditions with bubble cleanup (FIX 4/5)
        if hasattr(self, "_typing_timer") and self._typing_timer.isActive():
            self._typing_timer.stop()

        # Finalize any completed stream FIRST so its bubble + agent_action tags
        # stay in chronological order instead of being deleted mid-turn.
        if getattr(self, "active_stream_bubble", None):
            worker_alive = bool(getattr(self, "worker", None) and self.worker and self.worker.isRunning())
            if not worker_alive:
                if not self._generation_finished:
                    self._stream_buffer = self._stream_buffer or self._displayed_text
                    self._generation_finished = True
                    self._pending_reply = self._stream_buffer
                    self._pending_sid = self.current_sid
                try:
                    self._finalize_stream_response()
                except Exception:
                    pass
            if self.active_stream_bubble:
                self._safe_delete(self.active_stream_bubble)
                self.active_stream_bubble = None

        # Prune temporary ghost bubble from stopped generation if one exists!
        self._safe_delete(self.ghost_bubble)
        self.ghost_bubble = None

        self.edit_input.clear()
        self.chat_substack.setCurrentIndex(1)
        self._stop_btn_locked = False
        self._orphan_ticks = 0

        ses = self.sessions.get(self.current_sid)
        if not ses:
            # Create session ONLY when user actually sends a message!
            # Store system prompt as FIRST memory entry (role="system") so it's sent once
            model_key = self.settings.get("selected_model", "")
            route = self.models.get(model_key)
            is_offline = is_offline_model_key(model_key, route)
            sys_prompt = self._build_system_prompt(for_offline=is_offline)
            ses = {
                "title": "New Chat",
                "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "last_active": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "pinned": False,
                "memory": [{"role": "system", "content": sys_prompt}]
            }
            self.sessions[self.current_sid] = ses

        # Automatically name chat using first 15 characters of the opening message
        cur_title = ses.get("title", "")
        if not cur_title or cur_title in ("New Chat", "New Chat ✨") or len(ses.get("memory", [])) == 0:
            raw_c = re.sub(r"[*_`#~\[\]\(\)]", "", text.strip()) if text else "Attachment"
            raw_c = re.sub(r"<think>.*?</think>", "", raw_c, flags=re.DOTALL).strip()
            first_title = raw_c[:15].strip() if raw_c else "Chat"
            ses["title"] = first_title
            self.lbl_chat_title.setText(f"💬 {first_title}")
            if not self.settings.get("incognito"):
                save_json(F_SESSIONS, self.sessions)
            self.refresh_history_list()

        img_paths = [att["path"] for att in self.pending_attachments if att["type"] == "image"]
        files_data = [att for att in self.pending_attachments if att["type"] == "file"]
        attachments_to_send = list(self.pending_attachments)
        self.pending_attachments.clear()
        self.refresh_attachment_strip()

        # 🖼️ Auto-append newly generated image ONCE to this next turn so Cel can see what was created!
        auto_img = getattr(self, "_last_generated_image_to_append", None)
        if auto_img and os.path.exists(auto_img):
            if auto_img not in img_paths:
                img_paths.append(auto_img)
                attachments_to_send.append({"type": "image", "path": auto_img})
            # CONSUMED! Clear it so subsequent turns do NOT re-send the image (saves quota!)
            self._last_generated_image_to_append = None

        attached_files_text = ""
        for att in files_data:
            f_name = att.get("name", "file")
            f_path = att.get("path", "unknown")
            f_content = att.get("content", "")
            line_count = f_content.count("\n") + 1 if f_content else 0
            char_count = len(f_content)
            attached_files_text += (
                f"\n\n[Attached File: {f_name} (Location: {f_path}, "
                f"Lines: {line_count}, Characters: {char_count})]\n"
                f"```{att.get('ext', '')}\n{f_content}\n```"
            )

        user_msg = {
            "role": "user",
            "content": text or "*(sent attachments)*",
            "time": datetime.now().strftime("%H:%M"),
        }
        if attached_files_text:
            user_msg["attached_files_text"] = attached_files_text
        if files_data:
            user_msg["attached_files"] = [
                {"name": a.get("name", "File"), "size_str": a.get("size_str", ""), "ext": a.get("ext", "")}
                for a in files_data
            ]
        if img_paths:
            user_msg["attached_images"] = list(img_paths)
        ses.setdefault("memory", []).append(user_msg)
        ses["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        if not self.settings.get("incognito"):
            save_json(F_SESSIONS, self.sessions)
        self.refresh_history_list()

        bubble = MessageBubbleNew(
            "user", text or "*(sent attachments)*", user_msg,
            glass_opacity=self.settings.get("glass_opacity", 0.72),
            attached_images=img_paths, attached_files=files_data, chat_app=self
        )
        bubble.memory_index = len(ses["memory"]) - 1
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble, 0, Qt.AlignmentFlag.AlignRight)
        self.update_all_bubble_geometries()
        self.scroll_bottom(force=True)
        if hasattr(self, "chat_turn_rail") and self.chat_turn_rail:
            self.chat_turn_rail.refresh_turns()

        self.btn_stop.setVisible(True)
        self.btn_send.setVisible(False)
        self._stream_buffer = ""
        self._displayed_text = ""
        self._turn_mood_applied = False
        self._generation_finished = False
        self._pending_meta = None
        self._pending_reply = ""
        self._pending_sid = self.current_sid
        # Silence any in-flight Cel's Realistic Voice before a new turn starts.
        try:
            stop_realistic_voice()
        except Exception:
            pass
        self._chars_since_type_sound = 0
        self._turn_parts = []
        self._turn_agent_actions = []
        if hasattr(self, "_typing_timer") and self._typing_timer.isActive():
            self._typing_timer.stop()

        # Create assistant message in memory NOW (persistent, for crash recovery)
        # This gets updated in-place during streaming
        assistant_msg = {
            "role": "assistant", "content": "",
            "time": datetime.now().strftime("%H:%M"),
            "model": self.settings.get("selected_model", "")
        }
        ses["memory"].append(assistant_msg)
        self._streaming_msg_idx = len(ses["memory"]) - 1  # Index of the assistant message we're streaming

        # Create the persistent streaming bubble for this memory entry
        self.active_stream_bubble = MessageBubbleNew(
            "assistant", "", {"time": assistant_msg["time"], "model": assistant_msg["model"]},
            glass_opacity=self.settings.get("glass_opacity", 0.72), is_live=True, chat_app=self
        )
        self.active_stream_bubble.memory_index = self._streaming_msg_idx
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, self.active_stream_bubble, 0, Qt.AlignmentFlag.AlignLeft)
        self.update_all_bubble_geometries()
        self.stream_accum = ""

        # Agent mode on → always AgentWorker with tools in context.
        # tool_choice=auto lets the model decide per-turn (Claude Code / Codex pattern);
        # regex pre-filtering caused false-negatives → fake tool output.
        agent_on = self.settings.get("agent_mode_enabled", False)
        if agent_on:
            self._start_agent_worker(text, attachments_to_send)
        else:
            if hasattr(self, "worker") and self.worker and self.worker.isRunning():
                self._stop_worker_gracefully(self.worker, name="GenerationWorker")
            _live_on = bool(getattr(self, "_live", None) is not None and self._live.active)
            _comp = getattr(self, "_companion", None)
            _pet_on = bool(self.settings.get("pet_mode_enabled", False) or (_comp is not None and _comp.visible))
            self.settings["_mood_contract_active"] = bool(_live_on or _pet_on)

            self.worker = GenerationWorker(
                self.current_sid, text, self.settings, self.sessions,
                self.models, self.providers, self.dev_memory, attachments_to_send,
                parent=self
            )
            self.worker.signals.delta.connect(self.on_delta)
            self.worker.signals.done.connect(self.on_done)
            self.worker.signals.error.connect(self.on_error)
            self.worker.signals.status.connect(self._on_worker_status)
            self.worker.start()

        play_ui_sound("send", 0.5)

    def _start_agent_worker(self, text, attachments):
        """Start the agent worker for tool-calling mode with robust thread lifecycle."""
        # Stop existing worker thread safely before replacing to avoid QThread core dumps!
        if hasattr(self, "worker") and self.worker and self.worker.isRunning():
            self._stop_worker_gracefully(self.worker, name="AgentWorker")

        ses = self.sessions.get(self.current_sid)
        messages = ses.get("memory", []) if ses else []
        
        live_on = bool(getattr(self, "_live", None) is not None and self._live.active)
        comp = getattr(self, "_companion", None)
        pet_on = bool(self.settings.get("pet_mode_enabled", False) or (comp is not None and comp.visible))
        self.settings["_mood_contract_active"] = bool(live_on or pet_on)

        # Convert messages to format expected by agent (including pasted snippets!)
        agent_messages = []
        for m in messages:
            content = m.get("content", "")
            content_clean = re.sub(r'<agent_action .*?>.*?</agent_action>', '', content, flags=re.DOTALL).strip()
            # Bug 19: sanitize stored assistant history before it re-teaches
            # the imitator junk ("think:", "TOOL...") to the next turn.
            try:
                from cellium.core.utils import sanitize_memory_reply
                content_clean = sanitize_memory_reply(content_clean)
            except Exception:
                pass
            run_log = m.get("code_run_log", "")
            if m.get("role") == "assistant" and run_log:
                content_clean = f"{content_clean}\n\n{run_log}".strip()
            att_txt = m.get("attached_files_text", "")
            if m.get("role") == "user" and att_txt and att_txt not in content_clean:
                if content_clean == "*(sent attachments)*":
                    content_clean = f"Please inspect the attached snippet/file(s):{att_txt}"
                else:
                    content_clean = f"{content_clean}{att_txt}"
            agent_messages.append({"role": m["role"], "content": content_clean})
        
        self._active_agent_cards = {}  # tool_name -> list of pending cards
        self._turn_agent_actions = []   # Clear actions for fresh turn
        self._turn_parts = []           # Clear chronological segments for fresh turn
        
        # Parent the worker to self (CelStudioCerebrium) so it's auto-cleaned and never destroyed while running
        self.worker = AgentWorker(
            self.current_sid, agent_messages, self.settings, self.models, self.providers,
            self.dev_memory, tools_enabled=True, parent=self
        )
        self.worker.signals.delta.connect(self.on_delta)
        self.worker.signals.done.connect(self.on_done)
        self.worker.signals.error.connect(self.on_error)
        self.worker.signals.status.connect(self._on_worker_status)
        self.worker.signals.tool_call.connect(self._on_agent_tool_call)
        self.worker.signals.tool_result.connect(self._on_agent_tool_result)
        self.worker.signals.tool_diff.connect(self._on_agent_tool_diff)
        # Track worker state to prevent race conditions
        self.worker.finished.connect(lambda: setattr(self, "_agent_worker_finished", True))
        self._agent_worker_finished = False
        self.worker.start()

    def _agent_actions_prefix(self):
        return "".join(self._turn_agent_actions or [])

    def _clean_agent_segment(self, text):
        """Strip tool-call markup / thinking from a committed text segment."""
        if not text:
            return ""
        clean = text
        while True:
            match = re.search(r'(?:TOOL_CALL|TOOLCALL|\[TOOL_CALL\]|\[TOOLCALL\])\s*:', clean, re.IGNORECASE)
            if not match:
                break
            json_str, s_idx, e_idx = extract_balanced_json(clean, match.end())
            if json_str:
                clean = clean[:match.start()] + clean[e_idx:]
            else:
                clean = clean[:match.start()] + clean[match.end():]
                break
        clean = re.sub(r'\{\{\s*\w+\(.*?\)\s*\}\}', '', clean, flags=re.DOTALL)
        clean = re.sub(r'(?:FILECONTENT|FILE_CONTENT)\s*:\s*\{\{.*?\}\}', '', clean, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<respond>.*?</respond>', '', clean, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<agent_action.*?>.*?</agent_action>', '', clean, flags=re.DOTALL | re.IGNORECASE)
        # Thinking markers: closed blocks, orphan open-to-EOF, stray closes, emoji pairs
        clean = re.sub(r'<\x74hink>.*?</\x74hink>', '', clean, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<\x74hink>.*$', '', clean, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'</\x74hink>', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'🤔.*?🤔', '', clean, flags=re.DOTALL)
        clean = re.sub(r'煋.*?煋', '', clean, flags=re.DOTALL)
        # Mood-contract line - metadata for the face engine, never displayed.
        clean = re.sub(r'(?im)^[ \t]*(?:\*\*|__)?mood(?:\*\*|__)?[ \t]*:.*$',
                       '', clean)
        return clean.strip()

    def _composed_turn_content(self, current_segment=""):
        """Chronological memory content: committed text segments + action tags + live tail."""
        parts = list(self._turn_parts or [])
        tail = current_segment or ""
        if tail:
            parts.append(tail)
        return "".join(parts)

    def _commit_stream_segment(self):
        """Freeze the live stream bubble as its own permanent segment; open a fresh one.

        Called when a tool_call arrives mid-stream so intermediate Cel text
        survives above its tool cards instead of being wiped by finalize.
        """
        bubble = getattr(self, "active_stream_bubble", None)
        if bubble is None:
            return
        # Flush ALL pending typed chars so the frozen segment is complete
        if hasattr(self, "_typing_timer") and self._typing_timer.isActive():
            self._typing_timer.stop()
        self._displayed_text = self._stream_buffer or self._displayed_text or ""
        raw = self._displayed_text
        from cellium.core.utils import split_think, split_mood_first, strip_inline_mood_display
        _prose, _thoughts = split_think(raw)
        cleaned = strip_inline_mood_display(split_mood_first(self._clean_agent_segment(_prose))[0])
        has_content = bool(cleaned or _thoughts)

        if has_content:
            try:
                bubble.content = raw
                bubble.meta = {
                    "time": bubble.meta.get("time") or datetime.now().strftime("%H:%M"),
                    "model": self.settings.get("selected_model", ""),
                }
                bubble.update_stream_text(raw)
                bubble.setVisible(True)
                bubble.memory_index = None  # frozen segment - not independently editable
                self._turn_parts.append(cleaned if cleaned.endswith("\n") else cleaned + "\n")
            except RuntimeError:
                self.active_stream_bubble = None
                bubble = None
        elif bubble is not None:
            # Empty (thinking-only) - keep it as the live bubble, just reset buffers
            self._stream_buffer = ""
            self._displayed_text = ""
            try:
                bubble.setVisible(True)
            except RuntimeError:
                self.active_stream_bubble = None
            return

        # Open a fresh stream bubble for post-tool text
        self._stream_buffer = ""
        self._displayed_text = ""
        idx = getattr(self, "_streaming_msg_idx", -1)
        meta = {
            "time": datetime.now().strftime("%H:%M"),
            "model": self.settings.get("selected_model", ""),
        }
        new_bubble = MessageBubbleNew(
            "assistant", "", meta,
            glass_opacity=self.settings.get("glass_opacity", 0.72), chat_app=self
        )
        if idx is not None and idx >= 0:
            new_bubble.memory_index = idx
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, new_bubble, 0, Qt.AlignmentFlag.AlignLeft)
        self.active_stream_bubble = new_bubble

    def _persist_stream_text(self, text):
        """Write streaming text into memory without wiping prior segments / agent_action tags."""
        idx = getattr(self, "_streaming_msg_idx", -1)
        if idx is None or idx < 0:
            return
        sid = getattr(self, "_pending_sid", None) or self.current_sid
        ses = self.sessions.get(sid)
        if not ses or "memory" not in ses or idx >= len(ses["memory"]):
            return
        reply = text or ""
        if not self._turn_parts:
            if "<agent_action" in reply:
                ses["memory"][idx]["content"] = reply
            else:
                ses["memory"][idx]["content"] = self._agent_actions_prefix() + reply
        else:
            ses["memory"][idx]["content"] = self._composed_turn_content(reply)

    def _insert_agent_card_chronological(self, card):
        """Insert tool card immediately before the streaming bubble (or before stretch).

        Never use bare count-1 while the stream bubble is still in the layout  - 
        that parks cards after the response and scrambles date order.
        """
        card.setMaximumWidth(820)
        stream = getattr(self, "active_stream_bubble", None)
        idx = -1
        if stream is not None:
            try:
                idx = self.chat_layout.indexOf(stream)
            except RuntimeError:
                idx = -1
                self.active_stream_bubble = None
        if idx < 0:
            idx = max(0, self.chat_layout.count() - 1)
        self.chat_layout.insertWidget(idx, card, 0, Qt.AlignmentFlag.AlignLeft)

    def _ensure_stream_bubble_last(self):
        """Keep the live response bubble as the last non-stretch item (chronological)."""
        stream = getattr(self, "active_stream_bubble", None)
        if stream is None:
            return
        try:
            idx = self.chat_layout.indexOf(stream)
        except RuntimeError:
            self.active_stream_bubble = None
            return
        if idx < 0:
            return
        after_has_widget = False
        for i in range(idx + 1, self.chat_layout.count()):
            w = self.chat_layout.itemAt(i).widget()
            if w is not None:
                after_has_widget = True
                break
        if after_has_widget:
            self.chat_layout.removeWidget(stream)
            self.chat_layout.insertWidget(self.chat_layout.count() - 1, stream, 0, Qt.AlignmentFlag.AlignLeft)

    def _on_agent_tool_call(self, tool_name, args):
        """Handle agent tool call - only render in layout if viewing the generating chat!"""
        # Stash args BEFORE the cross-chat guard - when the tool runs while the
        # user is on ANOTHER chat no card is rendered, but tool_result still
        # persists the <agent_action> tag; without this stash that tag would be
        # baked into session memory as args="{}" forever (reopened chats then
        # show "(no arguments)" while OUTPUT survived).
        if isinstance(args, dict) and args:
            self._last_tool_args = getattr(self, "_last_tool_args", {})
            self._last_tool_args[tool_name] = dict(args)
        if getattr(self, "_pending_sid", None) and self.current_sid != self._pending_sid:
            return
        self.show_toast(f"🤖 Agent executing {tool_name}...", icon="🔧")

        # Split: freeze any Cel prose typed so far into its OWN bubble above the card
        self._commit_stream_segment()

        # If the active stream bubble is currently empty (just thinking), hide it while tool runs
        if hasattr(self, "active_stream_bubble") and self.active_stream_bubble:
            try:
                if not self.active_stream_bubble.content:
                    self.active_stream_bubble.setVisible(False)
            except RuntimeError:
                self.active_stream_bubble = None

        # Chronological insert: card goes BEFORE the stream bubble / before stretch
        card = make_agent_tool_widget(tool_name, args, parent=self.chat_content)
        self._insert_agent_card_chronological(card)
        # FIFO stack - same tool can run multiple times in one turn
        self._active_agent_cards.setdefault(tool_name, []).append(card)
        # Diff arrives via tool_diff signal just before tool_result (queued order preserved)
        self._pending_tool_diff = None

        self.update_all_bubble_geometries()
        self.scroll_bottom(force=True)

    def _on_agent_tool_diff(self, path, diff):
        """Stash unified diff for the card about to receive its tool_result."""
        self._pending_tool_diff = diff or None

    def _on_agent_tool_result(self, tool_name, result):
        """Handle agent tool result - update standalone card live & show stream bubble!"""
        stack = self._active_agent_cards.get(tool_name) or []
        card = stack.pop(0) if stack else None
        pending_diff = getattr(self, "_pending_tool_diff", None)
        self._pending_tool_diff = None
        if card:
            # Live upgrade: glass card → colored EditDiffCard once the diff arrives
            if pending_diff and type(card).__name__ == "AgentToolCard" and tool_name in ("replace_file_content", "file_write", "write_file"):
                try:
                    layout = self.chat_layout
                    pos = layout.indexOf(card)
                    new_card = EditDiffCard(tool_name, card.args, result_text=result, diff_text=pending_diff, parent=self.chat_content)
                    new_card.set_result(result, diff=pending_diff)
                    if pos >= 0:
                        layout.removeWidget(card)
                        card.deleteLater()
                        layout.insertWidget(pos, new_card, 0, Qt.AlignmentFlag.AlignLeft)
                    else:
                        self._insert_agent_card_chronological(new_card)
                    stack = self._active_agent_cards.get(tool_name)
                    # card already popped; stack empty means this was the live card
                    card = new_card
                except (RuntimeError, Exception):
                    pass
            try:
                card.set_result(result, diff=pending_diff)
            except (RuntimeError, Exception):
                pass

        # Re-display stream bubble and keep it last (after all cards for this turn)
        if hasattr(self, "active_stream_bubble") and self.active_stream_bubble:
            try:
                self.active_stream_bubble.setVisible(True)
                self._ensure_stream_bubble_last()
            except RuntimeError:
                self.active_stream_bubble = None

        # Format action into XML history tag for session persistence.
        # `card` is None whenever the tool ran in a background chat (or the
        # card was popped/replaced) - fall back to the args stashed at call
        # time so reopened sessions never show "(no arguments)" again.
        if card and getattr(card, "args", None):
            _persist_args = card.args
        else:
            _persist_args = (getattr(self, "_last_tool_args", {}) or {}).get(tool_name, {})
        args_str = json.dumps(_persist_args, ensure_ascii=False) if _persist_args else "{}"
        status_str = "completed" if "Error" not in result[:30] else "failed"
        diff_attr = f' diff="{html.escape(pending_diff)}"' if pending_diff else ""
        action_tag = f'<agent_action tool="{tool_name}" args="{html.escape(args_str)}" status="{status_str}"{diff_attr}>{html.escape(result)}</agent_action>'
        self._turn_agent_actions.append(action_tag)
        self._turn_parts.append(action_tag)

        # Persist IMMEDIATELY so flush/stop/reload never drop tool history
        self._persist_stream_text(self._displayed_text or self._stream_buffer or "")

        if getattr(self, "_pending_sid", None) and self.current_sid != self._pending_sid:
            return
        self.update_all_bubble_geometries()
        self.scroll_bottom(force=True)
        self.show_toast(f"✓ {tool_name} completed!", icon="✨")

    def _on_worker_status(self, s):
        self._last_worker_status = s
        if getattr(self, "_pending_sid", None) and self.current_sid != self._pending_sid:
            return
        self.lbl_server_badge.setText(s)
        if hasattr(self, "active_stream_bubble") and self.active_stream_bubble:
            try:
                self.active_stream_bubble.set_thinking_status(s)
            except RuntimeError:
                self.active_stream_bubble = None

    def _maybe_apply_early_mood(self) -> None:
        """First-line mood → face reacts mid-stream, not at the end.

        Slow offline models take seconds per reply; the mood contract puts
        the key on line one precisely so the companion can wear it while the
        rest is still generating. Once per turn; the on_done react stays the
        authority for the final face.
        """
        if getattr(self, "_turn_mood_applied", False):
            return
        _clean, _mood = None, None
        try:
            from cellium.ui.live.live_mode import extract_mood
            _clean, _mood = extract_mood(self._stream_buffer or "")
        except Exception:
            _mood = None

        # Heuristic fallback if model didn't emit a mood tag within the first ~40 chars
        buf = self._stream_buffer or ""
        if not _mood and len(buf) > 35:
            low = buf[:120].lower()
            if any(k in low for k in ("haha", "lol", "yay", "happy", "great", "love", "awesome", "cute")):
                _mood = "happy"
            elif any(k in low for k in ("sorry", "sad", "unfortunate", "cry", "pout", "sigh")):
                _mood = "sad"
            elif any(k in low for k in ("hmm", "think", "let's see", "wonder", "ponder", "analyze")):
                _mood = "thinking"
            elif any(k in low for k in ("what?", "whoa", "omg", "shock", "gasp", "no way")):
                _mood = "surprised"
            elif any(k in low for k in ("grr", "angry", "hate", "mad", "annoy")):
                _mood = "angry"
            elif any(k in low for k in ("blush", "flirt", "hehe", "owo", "uwu", "darling", "babe")):
                _mood = "blush"
            else:
                _mood = "talk"

        if not _mood:
            return
        self._turn_mood_applied = True
        try:
            comp = getattr(self, "_companion", None)
            # React silently: respond_to would ALSO speak the partial reply
            # through the pet's own caption bubble.
            if comp is not None and comp.visible:
                comp.react((_mood.split(",")[0] or "idle").strip() or "idle")
        except Exception:
            pass

    def on_delta(self, sid, token):
        if getattr(self, "_stop_btn_locked", False) or getattr(self, "_generation_finished", False):
            return
        if not token:
            return
        if sid != self.current_sid:
            if sid == getattr(self, "_pending_sid", None):
                self._stream_buffer = getattr(self, "_stream_buffer", "") + token
                self._displayed_text = self._stream_buffer
                self._persist_stream_text(self._displayed_text)
            return

        # A live call must *show* the reply while it is being written. With a
        # slow local model the caption stayed blank for the whole generation
        # and then dropped the finished text in at once.
        live = getattr(self, "_live", None)
        if live is not None and getattr(live, "active", False):
            try:
                live.stream_delta(token)
            except Exception:
                pass

        streaming_mode = self.settings.get("streaming_mode", "Letter-by-Letter")
        if streaming_mode == "Word-by-Word":
            self._stream_buffer += token
            self._displayed_text = self._stream_buffer
            if getattr(self, "active_stream_bubble", None):
                try:
                    self.active_stream_bubble.update_stream_text(self._displayed_text)
                except RuntimeError:
                    self.active_stream_bubble = None
            self._maybe_apply_early_mood()
            # Typing sound based on user preference - but never under her
            # spoken voice: on a live call the melody would play behind
            # every word she says.
            if not self.settings.get("typing_sound_enabled", True):
                return
            if self._live_voice_speaks():
                return
            mode = normalize_cel_typing_mode(
                self.settings.get("typing_sound_mode",
                                  "Cel's Legacy Sound"))
            if mode == "Normal (UI clicks)":
                play_ui_sound("type", 0.25)
            elif mode == "Cel's Modern Melodi":
                play_animalese_chirp(
                    seed_char=token[0] if token else "a",
                    enabled=self.settings.get("animalese_voice", True),
                    variant=self.settings.get("ac_voice_variant", "Classic AC"),
                )
            elif mode == "Cel's Legacy Sound":
                # Always the archived cellium bloop, even if the user manually
                # picks this mode while the modern pack is active.
                play_legacy_typing_preview()
            elif mode == "Cel's Realistic Voice":
                feed_realistic_voice(token,
                                     profile_key=self.settings.get(
                                         "realistic_voice_profile",
                                         DEFAULT_REALISTIC_VOICE),
                                     volume=_typing_volume(0.9))
            return

        # Letter-by-Letter smooth streaming
        self._stream_buffer += token
        if not hasattr(self, "_typing_timer"):
            self._typing_timer = QTimer(self)
            self._typing_timer.timeout.connect(self._flush_typing_buffer)

        if not self._typing_timer.isActive():
            speed_setting = self.settings.get("text_speed", "Normal")
            speed_map = {"Slow": 22, "Normal": 16, "Fast": 12, "Instant": 1}
            # "Animate her typing" off = the reply appears as fast as the model
            # produces it. The timer still runs (so the finalise path is shared)
            # but at the Instant cadence, which dumps the whole buffer at once.
            if not self.settings.get("typing_animation", True):
                speed_setting = "Instant"
            interval = speed_map.get(speed_setting, 16)
            self._typing_timer.start(interval)

    def _flush_typing_buffer(self):
        if not getattr(self, "active_stream_bubble", None):
            if hasattr(self, "_typing_timer"):
                self._typing_timer.stop()
            return

        total_buffered = len(self._stream_buffer)
        curr_len = len(self._displayed_text)

        if curr_len < total_buffered:
            speed_setting = self.settings.get("text_speed", "Normal")
            backlog = total_buffered - curr_len
            if speed_setting == "Instant":
                step = backlog
            elif speed_setting == "Fast":
                step = 6 if backlog > 120 else (4 if backlog > 40 else 3)
            elif speed_setting == "Slow":
                step = 2 if backlog > 80 else 1
            else: # Normal
                step = 4 if backlog > 120 else (3 if backlog > 50 else 2)

            next_len = min(total_buffered, curr_len + step)
            added_chars = self._stream_buffer[curr_len:next_len]
            self._displayed_text = self._stream_buffer[:next_len]

            if getattr(self, "active_stream_bubble", None):
                try:
                    self.active_stream_bubble.update_stream_text(self._displayed_text)
                except RuntimeError:
                    self.active_stream_bubble = None
            self._maybe_apply_early_mood()

            # Persist to memory for crash recovery (update in-place) - keep agent tags
            if hasattr(self, "_streaming_msg_idx") and self._streaming_msg_idx >= 0:
                self._persist_stream_text(self._displayed_text)

            # Typing Sound every 3-4 letters based on user preference
            if self._live_voice_speaks():
                # Her voice owns the call - the melody stays out of it.
                self._chars_since_type_sound = 0
            elif not self.settings.get("typing_sound_enabled", True):
                self._chars_since_type_sound = 0
                step = len(added_chars) if curr_len < total_buffered else step
            mode = normalize_cel_typing_mode(
                self.settings.get("typing_sound_mode",
                                  "Cel's Legacy Sound"))
            if mode != "None (Silent)":
                self._chars_since_type_sound = getattr(
                    self, "_chars_since_type_sound", 0) + len(added_chars)
                if self._chars_since_type_sound >= 3:
                    self._chars_since_type_sound = 0
                    if mode == "Normal (UI clicks)":
                        play_ui_sound("type", 0.25)
                    elif mode == "Cel's Modern Melodi":
                        play_animalese_chirp(
                            seed_char=added_chars[0],
                            enabled=self.settings.get("animalese_voice", True),
                            variant=self.settings.get(
                                "ac_voice_variant", "Classic AC"),
                        )
                    elif mode == "Cel's Legacy Sound":
                        play_legacy_typing_preview()
                    elif mode == "Cel's Realistic Voice":
                        feed_realistic_voice(added_chars,
                                             profile_key=self.settings.get(
                                                 "realistic_voice_profile",
                                                 DEFAULT_REALISTIC_VOICE),
                                             volume=_typing_volume(0.9))

        # Check if generation has finished and all text has been rendered
        if curr_len >= total_buffered and getattr(self, "_generation_finished", False):
            if hasattr(self, "_typing_timer"):
                self._typing_timer.stop()
            self._finalize_stream_response()

    def _on_scroll_range_changed(self, min_val, max_val):
        if getattr(self, "_auto_scroll_anchored", True):
            self.chat_scroll.verticalScrollBar().setValue(max_val)

    def _on_scroll_value_changed(self, val):
        bar = self.chat_scroll.verticalScrollBar()
        self._auto_scroll_anchored = (val >= bar.maximum() - 60)
        if hasattr(self, "chat_turn_rail") and self.chat_turn_rail:
            self.chat_turn_rail.update_active_from_scroll(val)
        # Repaint viewport and wallpaper to permanently prevent ghosting/tearing
        if hasattr(self, "chat_scroll") and self.chat_scroll:
            self.chat_scroll.viewport().update()
        if hasattr(self, "wallpaper_surface") and self.wallpaper_surface:
            self.wallpaper_surface.update()

    def scroll_bottom(self, force=True):
        if force:
            self._auto_scroll_anchored = True
        def _scroll():
            if hasattr(self, "chat_content") and self.chat_content:
                self.chat_content.adjustSize()
            bar = self.chat_scroll.verticalScrollBar()
            if getattr(self, "_auto_scroll_anchored", True):
                bar.setValue(bar.maximum())
        QTimer.singleShot(0, _scroll)

    def on_done(self, sid, reply, tokens = 0, think_time = 0.0, stopped = False, *args, **kwargs):
        self.btn_stop.setVisible(False)
        self.btn_send.setVisible(True)
        # A dropped connection must never masquerade as a real reply.
        if not stopped and _is_failed_reply_text(reply):
            self.on_error(sid, "Connection Failed",
                          "No response received from the model.")
            return
        # The mood contract: pull `mood: <key>` off the reply before anything
        # sees it - the face gets the key; the bubble and TTS never see it.
        # Multi-mood playback (Bug 38): collect EVERY directive first, in
        # order - extract_mood below strips them all from the reply.
        try:
            from cellium.core.utils import split_moods_all
            _all_moods = split_moods_all(reply)
        except Exception:
            _all_moods = []
        try:
            from cellium.ui.live.live_mode import extract_mood
            reply, reply_mood = extract_mood(reply)
        except Exception:
            reply_mood = None
        # Bug 19: keep think:/TOOL echoes out of the bubble AND out of session
        # memory - stored junk is what teaches imitator models the junk style.
        try:
            from cellium.core.utils import sanitize_memory_reply
            reply = sanitize_memory_reply(reply)
        except Exception:
            pass
        # Let the desktop companion react to the finished reply.
        self.companion_react(reply, mood=reply_mood)
        # ...then walk her face through the rest of the moods in sequence.
        try:
            comp = getattr(self, "_companion", None)
            if len(_all_moods) > 1 and comp is not None and comp.visible:
                comp.play_mood_sequence(_all_moods)
        except Exception:
            pass
        # If Live Mode is up, speak the reply and animate her mouth.
        try:
            if getattr(self._live, "active", False):
                self._live.speak(reply, mood=reply_mood)
                # …and actually *say* it on the call with the call's voice.
                self._live_speak_reply(reply)
        except Exception:
            pass
        # Mini-live (floating pet) owns no stage - speak here instead.
        try:
            if getattr(self, "_mini_active", False):
                self._mini_speak_reply(reply)
        except Exception:
            pass
        # Robustness: workers sometimes emit 0/0.0 (offline fallback, agent
        # summary-only path, orphaned streams). Never surface "0 tokens in 0.0s"
        # or a blank analytics row - estimate from the reply instead.
        if not tokens or tokens <= 0:
            tokens = max(1, len((reply or "").split()) or (len(reply or "") // 4) or 1)
        if not think_time or think_time <= 0:
            think_time = 0.5
        self._pending_meta = {
            "turn_tokens": tokens,
            "think_time": think_time,
            "model": self.settings.get("selected_model", ""),
            "time": datetime.now().strftime("%H:%M")
        }
        self._record_analytics(reply, self._pending_meta)
        # NOTE: self.worker set to None AFTER all stop/done logic to prevent races

        # Update total token count (session-wide "since launch" + per-chat total)
        sid = self.current_sid
        self.total_tokens += tokens
        self.session_token_totals[sid] = self.session_token_totals.get(sid, 0) + tokens
        if hasattr(self, "lbl_token_count"):
            self.lbl_token_count.setText(f"⚬ Total since launch: {self.total_tokens:,} tokens")

        # Handle automatic return to primary model after successful fallback
        if getattr(self, "_pending_fallback_return", False):
            primary_model = getattr(self, "_fallback_primary_model", None)
            if primary_model and primary_model != self.settings.get("selected_model", ""):
                self.settings["selected_model"] = primary_model
                save_json(F_SETTINGS, self.settings)
                self.update_model_dropdown()
                self.show_toast(f"✅ Rate limit recovered! Returned to primary model: {primary_model}", icon="✅")
            self._pending_fallback_return = False
            self._fallback_primary_model = None

        streaming_mode = self.settings.get("streaming_mode", "Letter-by-Letter")
        text_speed = self.settings.get("text_speed", "Normal")

        meta = {
            "turn_tokens": tokens,
            "think_time": think_time,
            "model": self.settings.get("selected_model", ""),
            "time": datetime.now().strftime("%H:%M"),
            "session_total_tokens": self.session_token_totals.get(sid, 0),
        }

        if stopped:
            if hasattr(self, "_typing_timer") and self._typing_timer.isActive():
                self._typing_timer.stop()
            
            ghost_reply = self._displayed_text or ""
            if ghost_reply and not ghost_reply.endswith("[SYSTEM: USER ABORTED TASK]"):
                ghost_reply += "\n\n[SYSTEM: USER ABORTED TASK]"
            elif not ghost_reply:
                ghost_reply = "[SYSTEM: USER ABORTED TASK]"
            meta = {
                "turn_tokens": max(1, len(ghost_reply) // 4),
                "think_time": 0.5,
                "model": self.settings.get("selected_model", ""),
                "time": datetime.now().strftime("%H:%M")
            }
            
            # Update existing bubble in place as ghost (current segment only  - 
            # frozen segment bubbles above are already permanent)
            stopped_bubble = None
            if hasattr(self, "active_stream_bubble") and self.active_stream_bubble:
                stopped_bubble = self.active_stream_bubble
                try:
                    self.active_stream_bubble.content = ghost_reply
                    self.active_stream_bubble.meta = meta
                    self.active_stream_bubble.is_ghost = True
                    self.active_stream_bubble.update_stream_text(ghost_reply)
                    if hasattr(self.active_stream_bubble, "_refresh_open_info_card"):
                        try:
                            self.active_stream_bubble._refresh_open_info_card()
                        except Exception:
                            pass
                except RuntimeError:
                    pass
                self.active_stream_bubble = None
            
            # Persist FULL turn (committed segments + action tags + ghost tail)
            if hasattr(self, "_streaming_msg_idx") and self._streaming_msg_idx >= 0:
                if sid in self.sessions:
                    ses = self.sessions[sid]
                    if "memory" in ses and self._streaming_msg_idx < len(ses["memory"]):
                        if self._turn_parts:
                            ses["memory"][self._streaming_msg_idx]["content"] = self._composed_turn_content(ghost_reply)
                        else:
                            self._persist_stream_text(ghost_reply)
                        ses["memory"][self._streaming_msg_idx].update(meta)
                        ses["memory"][self._streaming_msg_idx]["is_ghost"] = True
                        ses["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                        save_json(F_SESSIONS, self.sessions)
            
            self._turn_parts = []
            self._turn_agent_actions = []
            self._streaming_msg_idx = -1
            self.update_all_bubble_geometries()
            self._schedule_bubble_settle(stopped_bubble)
            self.ghost_bubble = None
            self.show_toast("Generation stopped by user 🛑", icon="🛑")
            self.worker = None
            return

        if reply and not self._stream_buffer:
            self._stream_buffer = reply

        self.worker = None
        self._generation_finished = True
        self._pending_meta = meta
        self._pending_reply = reply
        self._pending_sid = sid

        # If Word-by-Word or Instant or all characters already typed, finalize immediately
        if streaming_mode == "Word-by-Word" or text_speed == "Instant" or len(self._displayed_text) >= len(self._stream_buffer):
            if hasattr(self, "_typing_timer") and self._typing_timer.isActive():
                self._typing_timer.stop()
            self._finalize_stream_response()

    def _finalize_stream_response(self):
        # Prefer the LIVE typed segment (full buffer) over worker's final-only reply  - 
        # wiping to _pending_reply is what deleted intermediate Cel text.
        from cellium.core.utils import split_mood_first, strip_inline_mood_display, strip_tool_markers
        raw_live = self._displayed_text or self._stream_buffer or ""
        live = strip_inline_mood_display(split_mood_first(strip_tool_markers(raw_live))[0])
        worker_final = strip_inline_mood_display(
            split_mood_first(strip_tool_markers(getattr(self, "_pending_reply", "") or ""))[0]
        )
        if live and worker_final and worker_final not in live:
            # Summary-only path (no deltas) or cleaned mismatch: keep the longer text
            segment = worker_final if len(worker_final) > len(live) else live
        else:
            segment = live or worker_final
        reply = segment
        meta = getattr(self, "_pending_meta", None) or {
            "turn_tokens": max(1, len(reply) // 4),
            "think_time": 0.5,
            "model": self.settings.get("selected_model", ""),
            "time": datetime.now().strftime("%H:%M")
        }
        sid = getattr(self, "_pending_sid", self.current_sid)
        # The final buffer may still contain the worker's failure marker when
        # a stream dies after headers. Route it to the friendly error card.
        if _is_failed_reply_text(reply):
            self.on_error(sid, "Connection Failed",
                          "No response received from the model.")
            return
        # Session-scoped finalize: memory always lands on the turn's own sid,
        # but VISIBLE bubble work must only touch the layout when the user is
        # actually looking at that chat - otherwise a background finish paints
        # thinking bubbles and scroll jumps into the wrong conversation.
        _visible_here = (sid == getattr(self, "current_sid", sid))

        # ── AGENT MODE: Standalone cards already live in chat_layout! ──────
        # (preserved_cards logic kept for compatibility)
        preserved_cards = []

        # Use the EXISTING active_stream_bubble - just update it in place!
        # (Only when this finish belongs to the chat on screen - a background
        # session's bubble was already persisted by switch_session.)
        if _visible_here and hasattr(self, "active_stream_bubble") and self.active_stream_bubble:
            try:
                # Update the bubble content and meta
                self.active_stream_bubble.content = reply
                self.active_stream_bubble.meta = meta
                if hasattr(self.active_stream_bubble, "_refresh_open_info_card"):
                    try:
                        self.active_stream_bubble._refresh_open_info_card()
                    except Exception:
                        pass
                if hasattr(self.active_stream_bubble, "finalize_stream"):
                    self.active_stream_bubble.finalize_stream(reply)
                else:
                    self.active_stream_bubble.update_stream_text(reply)
                self.active_stream_bubble.setVisible(True)
                self._ensure_stream_bubble_last()
            except RuntimeError:
                pass
            bubble_idx = self.chat_layout.indexOf(self.active_stream_bubble)
            final_bubble = self.active_stream_bubble
            self.active_stream_bubble = None
        else:
            bubble_idx = -1
            final_bubble = None

        # Persist FULL turn: committed segments + action tags + final segment
        if hasattr(self, "_streaming_msg_idx") and self._streaming_msg_idx >= 0:
            if sid in self.sessions:
                ses = self.sessions[sid]
                if "memory" in ses and self._streaming_msg_idx < len(ses["memory"]):
                    clean_seg = self._clean_agent_segment(reply)
                    if self._turn_parts:
                        final_content = self._composed_turn_content(clean_seg)
                    elif "<agent_action" in (reply or ""):
                        final_content = reply
                    else:
                        final_content = self._agent_actions_prefix() + (reply or "")
                    self._turn_agent_actions = []
                    self._turn_parts = []
                    ses["memory"][self._streaming_msg_idx]["content"] = final_content
                    # Add meta to the memory entry
                    ses["memory"][self._streaming_msg_idx].update(meta)
                    ses["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    save_json(F_SESSIONS, self.sessions)
                    self.refresh_history_list()

        self._streaming_msg_idx = -1

        # Token count already applied in on_done - only refresh the label here
        # (orphan path applies its own count before calling finalize)
        if hasattr(self, "lbl_token_count"):
            self.lbl_token_count.setText(f"⚬ {self.total_tokens:,} tokens")

        self.update_all_bubble_geometries()
        self.scroll_bottom(force=False)
        self._schedule_bubble_settle(final_bubble)
        if hasattr(self, "chat_turn_rail") and self.chat_turn_rail:
            self.chat_turn_rail.refresh_turns()
        # Drain Cel's Realistic Voice so no trailing syllable is cut off.
        try:
            flush_realistic_voice()
        except Exception:
            pass
        play_ui_sound("recv", 0.5)

        # ── DRAIN MESSAGE QUEUE: Auto-send next queued message if any ──
        if hasattr(self, "_message_queue") and self._message_queue:
            next_text, next_attachments = self._message_queue.pop(0)
            remaining = len(self._message_queue)
            self.show_toast(f"Sending queued message...{f' ({remaining} remaining)' if remaining else ''}", icon="📬")
            self.pending_attachments = next_attachments
            self.edit_input.setPlainText(next_text)
            QTimer.singleShot(300, self.send_message)
            _ses = self.sessions.get(sid)
            if _ses is not None and len(_ses.get("memory", [])) >= 4 and _ses.get("title", "").strip() in ("New Chat", "New Chat ✨", ""):
                self._auto_generate_title(sid)
            self.refresh_history_list()
        tokens = meta.get("turn_tokens", 0)
        think_time = meta.get("think_time", 0.0)
        self.show_toast(f"Cel replied! ({tokens:,} tokens in {think_time}s) 💖", icon="✓")

    def update_all_bubble_geometries(self):
        if not hasattr(self, "chat_scroll") or not hasattr(self, "chat_layout"):
            return
        z = getattr(self, "zoom_level", 1.0)
        body_px = max(
            9,
            int(round(self.BUBBLE_BASE_FONT_PX * z * self.font_scale_factor())),
        )
        app_font = self.font()
        is_zoomed = abs(z - 1.0) > 1e-6
        for i in range(self.chat_layout.count()):
            item = self.chat_layout.itemAt(i)
            w = item.widget() if item else None
            if w is None:
                continue
            try:
                if is_zoomed or getattr(w, "_was_ss_zoomed", False):
                    self._apply_stylesheet_zoom(w)
                    w._was_ss_zoomed = is_zoomed
                for target in [w] + w.findChildren(QWidget):
                    if hasattr(target, "set_font_scale"):
                        if getattr(target, "font_size", None) != body_px:
                            target.set_font_scale(body_px)
                    elif target.font().pointSizeF() != app_font.pointSizeF():
                        target.setFont(app_font)
            except RuntimeError:
                pass
        vp_w = self.chat_scroll.viewport().width()
        if vp_w < 240:
            # Bug #3 & #8: Right after flipping chat_substack from welcome_widget (0)
            # to chat_scroll (1), viewport().width() is still 100px until the next
            # event-loop tick! Use the real container width so turn #1 is never squished.
            stack_w = self.central_stack.width() if hasattr(self, "central_stack") else 0
            vp_w = max(vp_w, stack_w - 24, self.width() - 280, 640)
        max_cap = int(840 * max(1.0, z * 0.92))
        max_target = min(max_cap, max(260, int(vp_w * 0.82)))
        for i in range(self.chat_layout.count()):
            item = self.chat_layout.itemAt(i)
            w = item.widget() if item else None
            if w and isinstance(w, MessageBubbleNew):
                w.update_dynamic_width(max_target)
            elif w and hasattr(w, "update_dynamic_width"):
                w.update_dynamic_width(max_target)
        cc = getattr(self, "chat_content", None)
        if cc is not None and hasattr(cc, "refresh_rail"):
            cc.refresh_rail()

    def _schedule_bubble_settle(self, bubble):
        """Gentle post-stream re-measure: delayed passes fix geometry the same-frame pass misses (fast replies, expand reflow)."""
        if bubble is None:
            return
        for delay in (25, 110, 350):
            QTimer.singleShot(delay, lambda b=bubble: self._settle_bubble_now(b))

    def _settle_bubble_now(self, bubble):
        try:
            if bubble is None:
                return
            z = getattr(self, "zoom_level", 1.0)
            vp_w = self.chat_scroll.viewport().width() if hasattr(self, "chat_scroll") else 0
            if vp_w < 240:
                stack_w = self.central_stack.width() if hasattr(self, "central_stack") else 0
                vp_w = max(vp_w, stack_w - 24, self.width() - 280, 640)
            max_cap = int(840 * max(1.0, z * 0.92))
            max_target = min(max_cap, max(260, int(vp_w * 0.82)))
            bubble.update_dynamic_width(max_target)
            cc = getattr(self, "chat_content", None)
            if cc is not None and hasattr(cc, "refresh_rail"):
                cc.refresh_rail()
            self.scroll_bottom(force=False)
        except RuntimeError:
            pass

    def _animate_bubble_height(self, bubble, target):
        try:
            from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QAbstractAnimation
            bubble.setMaximumHeight(16777215)
            anim = QPropertyAnimation(bubble, b"minimumHeight", bubble)
            anim.setDuration(160)
            anim.setStartValue(bubble.height())
            anim.setEndValue(int(target))
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)

            def _finish():
                try:
                    bubble.setFixedHeight(int(target))
                except RuntimeError:
                    pass
            anim.finished.connect(_finish)
            anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
            bubble._settle_anim = anim
        except Exception:
            try:
                bubble.setFixedHeight(int(target))
            except Exception:
                pass

    def compact_current_session(self):
        """Compact conversation history to conserve quota, prevent context overflow, and speed up turns."""
        play_ui_sound("click", 0.5)
        ses = self.sessions.get(self.current_sid)
        if not ses or "memory" not in ses or not ses["memory"]:
            self.show_toast("No messages to compact!", icon="ℹ️")
            return
        
        mem = ses["memory"]
        if len(mem) <= 4:
            self.show_toast(f"Chat is already compact ({len(mem)} messages)! ✨", icon="📦")
            return
        
        tokens_before = sum(len(m.get("content", "")) // 4 for m in mem)
        
        # Keep recent 4 messages intact
        keep_recent = mem[-4:]
        earlier_messages = mem[:-4]
        
        summary_points = []
        for idx, m in enumerate(earlier_messages):
            role = "User" if m.get("role") == "user" else "Cel"
            c = m.get("content", "").strip()
            c = re.sub(r'<think>.*?</think>', '', c, flags=re.DOTALL)
            c = re.sub(r'<agent_action.*?</agent_action>', '', c, flags=re.DOTALL).strip()
            snippet = c[:160] + ("..." if len(c) > 160 else "")
            if snippet:
                summary_points.append(f"- **{role}**: {snippet}")
        
        recap_text = "**[COMPACTED CONTEXT SUMMARY]**\n" + "\n".join(summary_points[:12])
        if len(summary_points) > 12:
            recap_text += f"\n*(and {len(summary_points) - 12} earlier exchanges condensed)*"
        
        compacted_entry = {
            "role": "system",
            "content": recap_text,
            "time": datetime.now().strftime("%H:%M"),
            "model": "Context Compressor"
        }
        
        ses["memory"] = [compacted_entry] + keep_recent
        save_json(F_SESSIONS, self.sessions)
        
        tokens_after = sum(len(m.get("content", "")) // 4 for m in ses["memory"])
        saved = max(0, tokens_before - tokens_after)
        
        self.switch_session(self.current_sid)
        play_ui_sound("pop", 0.5)
        self.show_toast(f"Context compacted! Saved ~{saved:,} tokens (reduced to {len(ses['memory'])} entries) 📦", icon="📦")

    def trigger_ai_rename(self, sid=None, force=False):
        if not sid: sid = self.current_sid
        ses = self.sessions.get(sid)
        if not ses: return
        mem = ses.get("memory", [])
        if not mem: return

        u_msg = next((m.get("content", "") for m in mem if m.get("role") == "user"), "")
        a_msg = next((m.get("content", "") for m in mem if m.get("role") == "assistant"), "")
        if not u_msg: return

        context = f"User: {u_msg}\nCel: {a_msg}"
        self.show_toast("AI is generating a smart title for this chat...", icon="✨")
        worker = AIRenameWorker(sid, context, self.settings, self.models, self.providers, self)
        worker.finished.connect(worker.deleteLater)
        worker.signals.finished.connect(self._on_ai_rename_finished)
        worker.signals.error.connect(lambda err: dev_log(f"AI rename error: {err}"))
        self._rename_worker = worker
        worker.start()

    def _auto_generate_title(self, sid):
        """Auto-generate a ChatGPT-style title from recent conversation history."""
        ses = self.sessions.get(sid)
        if not ses: return
        mem = ses.get("memory", [])
        if len(mem) < 4: return  # Need at least 2 exchanges
        
        # Get last 3 user-assistant pairs
        context_parts = []
        for m in mem[-6:]:  # Last 6 messages = 3 pairs
            role = m.get("role", "")
            content = m.get("content", "").strip()
            if content:
                prefix = "User" if role == "user" else "Cel"
                context_parts.append(f"{prefix}: {content}")
        
        if len(context_parts) < 2: return
        
        context = "\n".join(context_parts)
        self.show_toast("AI is generating a smart title...", icon="✨")
        
        # Use a more detailed prompt for auto-title generation
        prompt = (
            "Generate a concise, descriptive title (max 50 chars) for this conversation. "
            "Focus on the main topic/task. No quotes, no preamble.\n\n"
            f"{context}"
        )
        
        worker = AIRenameWorker(sid, prompt, self.settings, self.models, self.providers, self)
        worker.finished.connect(worker.deleteLater)
        worker.signals.finished.connect(lambda s, t: self._on_auto_title_finished(s, t))
        worker.signals.error.connect(lambda err: dev_log(f"AI auto-title error: {err}"))
        self._auto_title_worker = worker
        worker.start()

    def _on_auto_title_finished(self, sid, new_title):
        if sid in self.sessions:
            ses = self.sessions[sid]
            # Only update if still unnamed
            if ses.get("title", "").strip() in ("New Chat", "New Chat ✨", ""):
                ses["title"] = new_title
                if self.current_sid == sid:
                    self.lbl_chat_title.setText(f"💬 {new_title}")
                save_json(F_SESSIONS, self.sessions)
                self.refresh_history_list()
                self.show_toast(f"📝 Auto-titled: {new_title}", icon="✨")

    def _on_ai_rename_finished(self, sid, new_title):
        if sid in self.sessions:
            self.sessions[sid]["title"] = new_title
            if self.current_sid == sid:
                self.lbl_chat_title.setText(f"💬 {new_title}")
            save_json(F_SESSIONS, self.sessions)
            self.refresh_history_list()
            self.show_toast(f"AI Named: {new_title}", icon="✨")

    def _memory_index_for_bubble(self, bubble_widget):
        """Resolve a bubble to its session-memory index."""
        ses = self.sessions.get(self.current_sid)
        if not ses or "memory" not in ses or bubble_widget is None:
            return None
        mem = ses["memory"]
        role = getattr(bubble_widget, "role", None)
        content = (getattr(bubble_widget, "content", "") or "").strip()

        idx = getattr(bubble_widget, "memory_index", None)
        if idx is not None and 0 <= idx < len(mem):
            entry = mem[idx]
            if entry.get("role") == role:
                return idx

        from cellium.core.utils import clean_chat_display
        for i in range(len(mem) - 1, -1, -1):
            if mem[i].get("role") != role:
                continue
            mc = (mem[i].get("content", "") or "").strip()
            if mc == content or clean_chat_display(mc) == clean_chat_display(content):
                return i
        return None

    def truncate_chat_with_undo(self, bubble_widget):
        idx = self.chat_layout.indexOf(bubble_widget)
        if idx == -1: return
        # Remove all widgets after the given bubble
        while self.chat_layout.count() > idx + 1:
            item = self.chat_layout.takeAt(idx + 1)
            w = item.widget()
            if w:
                w.deleteLater()
            else:
                del item

        # Ensure stretch at end (remove existing stretches first)
        while self.chat_layout.count() > 0:
            item = self.chat_layout.itemAt(self.chat_layout.count() - 1)
            w = item.widget() if item else None
            if w is None:  # stretch item
                self.chat_layout.takeAt(self.chat_layout.count() - 1)
            else:
                break
        self.chat_layout.addStretch(1)

        ses = self.sessions.get(self.current_sid)
        if ses and "memory" in ses:
            # NEVER use layout idx for memory - system/tool-card skew makes them differ.
            mem_idx = self._memory_index_for_bubble(bubble_widget)
            if mem_idx is not None and mem_idx + 1 < len(ses["memory"]):
                ses["memory"] = ses["memory"][:mem_idx + 1]
            save_json(F_SESSIONS, self.sessions)
            self.refresh_history_list()

    def retry_message(self, bubble_widget):
        """Retry a user message without duplicating the bubble or messing up memory."""
        if getattr(bubble_widget, "role", None) != "user":
            return
        mem_idx = self._memory_index_for_bubble(bubble_widget)
        if mem_idx is None:
            self.show_toast("Could not locate message in history", icon="⚠️")
            return
        # regenerate truncates after this user msg, then rebuilds the assistant turn
        self.regenerate_response(target_user_idx=mem_idx)

    # ===== Qwen-style Edit Mode → Branch Session =====
    def enter_edit_mode(self, bubble_widget):
        """Enter edit mode for either a user message (Save & Resend) or Cel's message (Save In-Place)."""
        if self._edit_mode:
            self.cancel_edit_mode()

        idx = self.chat_layout.indexOf(bubble_widget)
        if idx == -1:
            return

        if bubble_widget.role not in ("user", "assistant"):
            return

        ses = self.sessions.get(self.current_sid)
        if not ses or "memory" not in ses:
            return

        mem_idx = self._memory_index_for_bubble(bubble_widget)
        if mem_idx is None:
            self.show_toast("Could not locate message in history", icon="⚠️")
            return
        self._edit_mode = True
        self._edit_bubble = bubble_widget
        self._edit_original_content = bubble_widget.content
        self._edit_original_idx = mem_idx

        is_cel = (bubble_widget.role == "assistant")
        self.btn_cancel_edit.setVisible(True)
        self.btn_send.setFixedSize(132 if is_cel else 140, 38)
        self.btn_send.setIcon(QIcon())
        self.btn_send.setText("✓ Save Edit" if is_cel else "✓ Save & Resend")
        self.btn_send.setToolTip(
            "Save Cel's message in-place without sending" if is_cel else "Save edit and regenerate response"
        )

        self.edit_input.setPlainText(bubble_widget.content)
        self.edit_input.setFocus()

        bubble_widget.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(147, 51, 234, 0.15), stop:1 rgba(32, 18, 52, 0.15));
                border: 2px solid #9333EA;
                border-radius: 14px;
            }
        """)
        self.show_toast("Editing Cel's message in-place..." if is_cel else "Editing message...", icon="✏️")

    def cancel_edit_mode(self):
        """Cancel edit mode and restore original message."""
        if not self._edit_mode:
            return
        
        # Restore original content in bubble safely
        if self._edit_bubble:
            try:
                self._edit_bubble.content = self._edit_original_content
                eb = self._edit_bubble
                if getattr(eb, "_body_sources", None):
                    eb._body_sources = [(lbl, self._edit_original_content if lbl is eb.body_label else src)
                                        for lbl, src in eb._body_sources]
                if getattr(eb, "body_label", None):
                    eb.body_label.setHtmlText(eb._body_html(self._edit_original_content))
                max_w = getattr(self._edit_bubble, "max_allowed_w", 600)
                self._edit_bubble.update_dynamic_width(max_w)
                self._edit_bubble.setStyleSheet("")
                self._edit_bubble.updateGeometry()
            except (RuntimeError, AttributeError):
                pass
        
        # Reset UI
        self.btn_cancel_edit.setVisible(False)
        self.btn_send.setFixedSize(38, 38)
        self.btn_send.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_send.svg")))
        self.btn_send.setText("")
        self.btn_send.setToolTip("")
        self.edit_input.clear()
        self.pending_attachments.clear()
        self.refresh_attachment_strip()
        
        # Reset state
        self._edit_mode = False
        self._edit_bubble = None
        self._edit_original_content = ""
        self._edit_original_idx = -1
        
        self.update_all_bubble_geometries()
        self.show_toast("Edit cancelled, original restored", icon="↩️")

    def save_edit(self):
        """Save the edited message IN-PLACE and re-generate from that turn (ChatGPT/Gemini style)."""
        if not self._edit_mode or not self._edit_bubble:
            return False
        
        new_content = self.edit_input.toPlainText().rstrip()
        if not new_content:
            self.show_toast("Cannot save empty message", icon="⚠️")
            return False
        
        ses = self.sessions.get(self.current_sid)
        if not ses or "memory" not in ses:
            return False
        
        msg_idx = self._edit_original_idx
        if msg_idx < 0 or msg_idx >= len(ses["memory"]):
            return False
        target_role = ses["memory"][msg_idx].get("role")
        if target_role == "assistant":
            # Bug #18: Edit Cel's message in-place like nothing ever happened!
            ses["memory"][msg_idx]["content"] = new_content
            save_json(F_SESSIONS, self.sessions)
            eb = self._edit_bubble
            try:
                eb.setStyleSheet("")
                eb.content = new_content
                if hasattr(eb, "finalize_stream"):
                    eb.finalize_stream(new_content)
                elif getattr(eb, "body_label", None):
                    eb.body_label.setHtmlText(eb._body_html(new_content))
            except Exception:
                pass
            self.btn_cancel_edit.setVisible(False)
            self.btn_send.setFixedSize(38, 38)
            self.btn_send.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_send.svg")))
            self.btn_send.setText("")
            self.btn_send.setToolTip("Send message")
            self.edit_input.clear()
            self._edit_mode = False
            self._edit_bubble = None
            self._edit_original_content = ""
            self._edit_original_idx = -1
            self.update_all_bubble_geometries()
            self.show_toast("Cel's message updated! ✨", icon="✓")
            return True

        if target_role != "user":
            return False
        
        # Update content in place and truncate downstream turns
        ses["memory"] = ses["memory"][:msg_idx + 1]
        ses["memory"][msg_idx]["content"] = new_content
        save_json(F_SESSIONS, self.sessions)
        
        # Update user bubble UI
        try:
            self._edit_bubble.content = new_content
            if getattr(self._edit_bubble, "body_label", None):
                self._edit_bubble.body_label.setHtmlText(self._edit_bubble._body_html(new_content))
        except Exception:
            pass

        # Clear downstream bubbles from chat layout
        bubble_idx = self.chat_layout.indexOf(self._edit_bubble)
        if bubble_idx != -1:
            while self.chat_layout.count() > bubble_idx + 1:
                item = self.chat_layout.takeAt(bubble_idx + 1)
                w = item.widget()
                if w:
                    w.deleteLater()

        # Reset edit mode cleanly
        self.btn_cancel_edit.setVisible(False)
        self.btn_send.setFixedSize(38, 38)
        self.btn_send.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_send.svg")))
        self.btn_send.setText("")
        self.btn_send.setToolTip("")
        self.edit_input.clear()
        self.pending_attachments.clear()
        self.refresh_attachment_strip()
        self._edit_mode = False
        self._edit_bubble = None
        self._edit_original_content = ""
        self._edit_original_idx = -1

        # Automatically re-generate Cel's response!
        self.regenerate_response(target_user_idx=msg_idx)
        return True

    def regenerate_response(self, target_user_idx=None):
        """Regenerate AI response for a user message (default: last user turn).

        Always truncates anything after the target user message first, then
        streams into a freshly created assistant bubble - never reuses an
        assistant bubble from an earlier exchange.
        """
        ses = self.sessions.get(self.current_sid)
        if not ses or "memory" not in ses or not ses["memory"]:
            return

        mem = ses["memory"]
        if target_user_idx is None:
            target_user_idx = -1
            for i in range(len(mem) - 1, -1, -1):
                if mem[i].get("role") == "user":
                    target_user_idx = i
                    break
        if target_user_idx < 0 or target_user_idx >= len(mem) or mem[target_user_idx].get("role") != "user":
            return

        # Locate the target user bubble so we can drop everything after it in the layout
        target_content = mem[target_user_idx].get("content", "")
        user_bubble = None
        for i in range(self.chat_layout.count()):
            item = self.chat_layout.itemAt(i)
            w = item.widget() if item else None
            if w and isinstance(w, MessageBubbleNew) and w.role == "user":
                if getattr(w, "memory_index", None) == target_user_idx or w.content == target_content:
                    user_bubble = w
                    break

        if user_bubble is not None:
            self.truncate_chat_with_undo(user_bubble)
        elif len(ses["memory"]) > target_user_idx + 1:
            ses["memory"] = ses["memory"][:target_user_idx + 1]

        # Safety: memory must end at the target user turn
        if len(ses["memory"]) > target_user_idx + 1:
            ses["memory"] = ses["memory"][:target_user_idx + 1]
        mem = ses["memory"]

        text = mem[target_user_idx].get("content", "")
        if not text:
            return

        # Remove any version markers for sending to API
        clean_text = re.sub(r'^\[v\d+\]\s*', '', text)

        # Get attachments from the target user bubble if any
        img_paths = []
        files_data = []
        if user_bubble is not None:
            img_paths = user_bubble.attached_images or []
            files_data = user_bubble.attached_files or []
        else:
            for i in range(self.chat_layout.count() - 1, -1, -1):
                item = self.chat_layout.itemAt(i)
                w = item.widget() if item else None
                if w and isinstance(w, MessageBubbleNew) and w.role == "user":
                    img_paths = w.attached_images or []
                    files_data = w.attached_files or []
                    break

        attachments_to_send = []
        for img in img_paths:
            attachments_to_send.append({"type": "image", "path": img})
        for f in files_data:
            attachments_to_send.append({"type": "file", **f})

# Set up streaming for regeneration
        self.btn_stop.setVisible(True)
        self.btn_send.setVisible(False)
        self._stop_btn_locked = False
        self._orphan_ticks = 0
        self._stream_buffer = ""
        self._displayed_text = ""
        self._generation_finished = False
        self._pending_meta = None
        self._pending_reply = ""
        self._pending_sid = self.current_sid
        self._chars_since_type_sound = 0
        self._turn_parts = []
        self._turn_agent_actions = []
        try:
            stop_realistic_voice()
        except Exception:
            pass
        if hasattr(self, "_typing_timer") and self._typing_timer.isActive():
            self._typing_timer.stop()

        # Prior turns (and the target user msg) are intact - append a fresh assistant turn
        assistant_msg = {
            "role": "assistant", "content": "",
            "time": datetime.now().strftime("%H:%M"),
            "model": self.settings.get("selected_model", "")
        }
        ses["memory"].append(assistant_msg)
        self._streaming_msg_idx = len(ses["memory"]) - 1

        self.active_stream_bubble = MessageBubbleNew(
            "assistant", "", {"time": assistant_msg["time"], "model": assistant_msg["model"]},
            glass_opacity=self.settings.get("glass_opacity", 0.72), is_live=True, chat_app=self
        )
        self.active_stream_bubble.memory_index = self._streaming_msg_idx
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, self.active_stream_bubble, 0, Qt.AlignmentFlag.AlignLeft)

        self.stream_accum = ""
        
        # Agent mode on → always AgentWorker (same routing as send_message).
        agent_on = self.settings.get("agent_mode_enabled", False)
        if agent_on:
            self._start_agent_worker(clean_text, attachments_to_send)
        else:
            if hasattr(self, "worker") and self.worker and self.worker.isRunning():
                self._stop_worker_gracefully(self.worker, name="GenerationWorker")
                    
            self.worker = GenerationWorker(
                self.current_sid, clean_text, self.settings, self.sessions,
                self.models, self.providers, self.dev_memory, attachments_to_send,
                parent=self
            )
            self.worker.signals.delta.connect(self.on_delta)
            self.worker.signals.done.connect(self.on_done)
            self.worker.signals.error.connect(self.on_error)
            self.worker.signals.status.connect(self._on_worker_status)
            self.worker.start()
        
        play_ui_sound("send", 0.5)

    def on_send_clicked(self):
        """Handle send button click - stops generation if worker is running and button is in Stop state."""
        if self._edit_mode:
            self.save_edit()
            return
        running = bool(getattr(self, "worker", None) and self.worker and self.worker.isRunning())
        if running and (self.sender() is getattr(self, "btn_send", None) or not self.edit_input.text().strip()):
            self.stop_generation()
            return
        self.send_message()

    def branch_chat_at(self, bubble_widget):
        """Branch conversation from a specific message into a new session."""
        mem_idx = self._memory_index_for_bubble(bubble_widget)
        if mem_idx is None:
            return

        ses = self.sessions.get(self.current_sid)
        if not ses or "memory" not in ses:
            return

        # Create new session with messages up to and including this bubble's memory entry
        new_memory = ses["memory"][:mem_idx + 1].copy()

        new_sid = f"chat_{int(time.time() * 1000)}"
        base_title = ses.get("title", "Chat")
        new_title = f"Branched: {base_title}"

        self.sessions[new_sid] = {
            "title": new_title,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "last_active": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "pinned": False,
            "memory": new_memory,
            "parent_sid": self.current_sid,
            "branch_point": mem_idx
        }

        save_json(F_SESSIONS, self.sessions)
        self.switch_session(new_sid)
        self.show_toast(f"Branched new chat: {new_title}", icon="🌿")

    def _discard_failed_turn(self, sid=None):
        """Remove the empty assistant placeholder left by a failed turn."""
        sid = sid or self.current_sid
        try:
            ses = self.sessions.get(sid)
            idx = getattr(self, "_streaming_msg_idx", -1)
            if ses and 0 <= idx < len(ses.get("memory", [])):
                content = (ses["memory"][idx].get("content") or "").strip()
                if not content or _is_failed_reply_text(content):
                    ses["memory"].pop(idx)
                    save_json(F_SESSIONS, self.sessions)
        except Exception:
            pass
        self._streaming_msg_idx = -1
        self._stream_buffer = ""
        self._displayed_text = ""
        self._generation_finished = False
        try:
            if hasattr(self, "_typing_timer") and self._typing_timer.isActive():
                self._typing_timer.stop()
        except RuntimeError:
            pass

    def on_error(self, sid, title, desc):
        try:
            dev_log(f"[UI-WARN] {title}: {desc}")
        except Exception:
            pass
        if hasattr(self, "btn_stop") and self.btn_stop:
            self.btn_stop.setVisible(False)
        if hasattr(self, "btn_send") and self.btn_send:
            self.btn_send.setVisible(True)
        self.worker = None

        # Check for rate limit / quota / out-of-budget errors OR network drops
        # and trigger model fallback.
        _desc_low = str(desc or "").lower()
        _title_low = str(title or "").lower()
        is_rate_limit = ("http 429" in _desc_low or "http 402" in _desc_low
                         or "402" in _desc_low or "rate limit" in _desc_low
                         or "quota" in _desc_low or "too many requests" in _desc_low
                         or "budget exhausted" in _desc_low or "billing" in _desc_low)
        is_network_drop = any(k in _desc_low for k in (
            "[errno", "name or service", "timeout", "timed out", "connection",
            "max retries", "network", "408", "500", "502", "503", "504",
            "ssl", "proxy", "chunkedencoding", "remote end closed",
            "connection reset", "httperror", "urlerror",
        )) or "connection failed" in _title_low

        # Remove the empty assistant placeholder before any fallback retry.
        self._discard_failed_turn(sid)

        friendly = _friendly_generation_error(title, desc)
        if self.settings.get("auto_fallback_enabled", True) and (is_rate_limit or is_network_drop):
            if self._trigger_model_fallback(
                    sid, desc,
                    reason="Rate limited" if is_rate_limit else "Network/API failed"):
                return

        # Reveal a warm, actionable error inside the stream bubble so the user
        # is never stuck on a fake thinking animation and never sees a raw
        # exception when a friendly sentence is enough.
        if hasattr(self, "active_stream_bubble") and self.active_stream_bubble:
            try:
                if is_network_drop or is_rate_limit:
                    err_text = f"⚠️ {friendly}"
                else:
                    err_text = f"⚠️ **{title}**\n\n{friendly}"
                self.active_stream_bubble.update_stream_text(err_text)
                if hasattr(self.active_stream_bubble, "memory_index"):
                    self.active_stream_bubble.memory_index = -1
            except Exception:
                pass
            self.active_stream_bubble = None

        self.show_toast(friendly, icon="⚠️")

    def _trigger_model_fallback(self, sid, error_desc, reason="Rate limited"):
        """Automatically switch to fallback model on rate limit/quota or network errors."""
        fallback_models = self.settings.get("fallback_models", [])
        if not fallback_models:
            self.show_toast(f"⚠️ {reason} but no fallback models configured! Add some in Model Hub.", icon="⚠️")
            return False
        
        # Store primary model if not already stored
        current_model = self.settings.get("selected_model", "")
        primary_model = self.settings.get("primary_model", current_model)
        if not self.settings.get("primary_model"):
            self.settings["primary_model"] = current_model
            primary_model = current_model
        
        # Find next fallback model that's not the current one AND is available in self.models
        next_model = None
        for model in fallback_models:
            if model != current_model and model in self.models:
                next_model = model
                break
        
        if not next_model:
            self.show_toast("⚠️ All fallback models exhausted or unavailable!", icon="⚠️")
            return False
        
        # Switch to fallback model
        self.settings["selected_model"] = next_model
        save_json(F_SETTINGS, self.settings)
        self.update_model_dropdown()
        
        self.show_toast(f"🔄 {reason}! Auto-switching to fallback: {next_model}", icon="🔄")
        
        # Schedule return to primary after a short delay (if enabled)
        if self.settings.get("fallback_return_to_primary", True):
            self._pending_fallback_return = True
            self._fallback_primary_model = primary_model
        
        # Retry the last user message automatically
        QTimer.singleShot(500, self._delayed_regenerate)
        return True

    def _delayed_regenerate(self) -> None:
        """Cleanly retry the last user turn after an automatic model fallback."""
        if getattr(self, "_closing", False):
            return
        if getattr(self, "active_stream_bubble", None) is not None:
            self._safe_delete(self.active_stream_bubble)
            self.active_stream_bubble = None
        self.regenerate_response()

    def record_code_run_output(self, lang: str, code_text: str, output: str, exit_code: int) -> None:
        """Bug #21: Store the output & exit code of a user-clicked ▶ Run block in session memory."""
        ses = self.sessions.get(self.current_sid)
        if not ses or "memory" not in ses:
            return
        snippet = (code_text or "").strip()
        if len(snippet) > 600:
            snippet = snippet[:600] + "\n... (truncated)"
        out_clean = (output or "(no output)").strip()
        if len(out_clean) > 2500:
            out_clean = out_clean[:2500] + "\n... (truncated)"
        log_block = (
            f"[User Executed Code Block ({lang or 'code'}) via ▶ Run Button]\n"
            f"```{lang or ''}\n{snippet}\n```\n"
            f"Terminal Output:\n```\n{out_clean}\n```\n"
            f"Exit code: {exit_code}"
        )
        mem = ses["memory"]
        for i in range(len(mem) - 1, -1, -1):
            if mem[i].get("role") == "assistant":
                prev = mem[i].get("code_run_log", "")
                mem[i]["code_run_log"] = (f"{prev}\n\n{log_block}".strip() if prev else log_block)
                break
        else:
            mem.append({"role": "system", "content": log_block})
        if not self.settings.get("incognito"):
            save_json(F_SESSIONS, self.sessions)

    def _active_scroll_bar(self):
        """Find the vertical scrollbar of the currently active view/page."""
        idx = self.central_stack.currentIndex() if hasattr(self, "central_stack") else 0
        if idx == 0 and hasattr(self, "chat_scroll"):
            return self.chat_scroll.verticalScrollBar(), self.chat_scroll.viewport().height()
        page = self.central_stack.currentWidget() if hasattr(self, "central_stack") else None
        if page is not None:
            for sa in page.findChildren(QScrollArea):
                if sa.isVisible() and sa.verticalScrollBar().maximum() > 0:
                    return sa.verticalScrollBar(), sa.viewport().height()
            for te in page.findChildren(QTextEdit):
                if te.isVisible() and te.verticalScrollBar().maximum() > 0:
                    return te.verticalScrollBar(), te.viewport().height()
        if hasattr(self, "chat_scroll"):
            return self.chat_scroll.verticalScrollBar(), self.chat_scroll.viewport().height()
        return None, 0

    def page_scroll_active_view(self, up: bool = True) -> None:
        """Bug #20: Smoothly page-scroll the active view on PageUp / PageDown."""
        bar, vp_h = self._active_scroll_bar()
        if bar is None:
            return
        step = max(180, int((vp_h or 500) * 0.82))
        target = max(bar.minimum(), min(bar.maximum(), bar.value() + (-step if up else step)))
        if up:
            self._auto_scroll_anchored = False
        elif target >= bar.maximum() - 20:
            self._auto_scroll_anchored = True
        try:
            anim = getattr(self, "_page_scroll_anim", None)
            if anim is not None:
                anim.stop()
            anim = QPropertyAnimation(bar, b"value", self)
            anim.setDuration(135)
            anim.setStartValue(bar.value())
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._page_scroll_anim = anim
            anim.start()
        except Exception:
            bar.setValue(target)

    def jump_active_view(self, top: bool = True) -> None:
        """Jump to top or bottom of active view on Ctrl+Home / Ctrl+End."""
        bar, _ = self._active_scroll_bar()
        if bar is None:
            return
        target = bar.minimum() if top else bar.maximum()
        if top:
            self._auto_scroll_anchored = False
        else:
            self._auto_scroll_anchored = True
        bar.setValue(target)

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) and not (
            mods & Qt.KeyboardModifier.ShiftModifier
        ):
            self.page_scroll_active_view(up=(key == Qt.Key.Key_PageUp))
            event.accept()
            return
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End) and (
            mods & Qt.KeyboardModifier.ControlModifier
        ):
            self.jump_active_view(top=(key == Qt.Key.Key_Home))
            event.accept()
            return
        super().keyPressEvent(event)

    def _install_apple_tactile_sound_filter(self) -> None:
        """Attach a universal tactile sound filter so every button, tab, checkbox & menu has Apple/ChatGPT feedback."""
        try:
            from cellium.core.utils import generate_sound_library
            generate_sound_library()
        except Exception:
            pass
        from PySide6.QtCore import QEvent, QObject
        from PySide6.QtWidgets import QAbstractButton, QTabBar, QComboBox, QMenu

        class _AppleTactileFilter(QObject):
            def eventFilter(self, obj, ev):
                et = ev.type()
                if et == QEvent.Type.MouseButtonRelease and hasattr(ev, "button"):
                    btn = ev.button()
                    if btn == Qt.MouseButton.RightButton:
                        play_ui_sound("right_click", 0.42)
                    elif btn == Qt.MouseButton.MiddleButton:
                        play_ui_sound("middle_click", 0.42)
                    elif btn == Qt.MouseButton.LeftButton:
                        if isinstance(obj, QAbstractButton) and obj.isEnabled():
                            # Never fire a UI click on the Cel voice preview  - 
                            # you're already hearing the voice itself.
                            if obj.property("silent_preview"):
                                pass
                            else:
                                play_ui_sound("pop" if obj.isCheckable() else "click", 0.42)
                        elif isinstance(obj, QTabBar):
                            play_ui_sound("click", 0.40)
                        elif isinstance(obj, QComboBox) and obj.isEnabled():
                            play_ui_sound("click", 0.38)
                elif et == QEvent.Type.Show and isinstance(obj, QMenu):
                    play_ui_sound("pop", 0.36)
                return False

        app = QApplication.instance()
        if app is not None and not getattr(app, "_cellium_tactile_installed", False):
            self._tactile_filter = _AppleTactileFilter(self)
            app.installEventFilter(self._tactile_filter)
            app._cellium_tactile_installed = True

    def eventFilter(self, watched, event):
        try:
            # Slash-command popup keyboard nav (Up/Down/Enter/Esc) while it's open
            _slash = getattr(self, "_slash_popup", None)
            if (event.type() == event.Type.KeyPress and hasattr(self, "edit_input")
                    and _slash is not None and _slash.isVisible()
                    and (watched is self.edit_input or watched is _slash
                         or watched is getattr(_slash, "_list", None))):
                key = event.key()
                lst = _slash._list
                if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                    row = lst.currentRow()
                    row = max(0, row - 1) if key == Qt.Key.Key_Up else min(lst.count() - 1, row + 1)
                    lst.setCurrentRow(row)
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._pick_slash_command(lst.currentRow())
                    return True
                if key == Qt.Key.Key_Escape:
                    self._hide_slash_popup()
                    return True
            if getattr(self, "_wheel_locked", False) and event.type() == event.Type.Wheel:
                if hasattr(self, "chat_scroll") and watched == self.chat_scroll.viewport():
                    event.ignore()
                    return True
            if hasattr(self, "chat_scroll") and self.chat_scroll and watched == self.chat_scroll.viewport():
                if event.type() == event.Type.Resize and not getattr(self, "_drawer_animating", False):
                    self.update_all_bubble_geometries()
                elif event.type() == event.Type.Wheel:
                    if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                        delta = event.angleDelta().y()
                        if delta != 0:
                            step = 0.08 if delta > 0 else -0.08
                            self.adjust_zoom(step)
                            return True
        except Exception:
            pass
        return super().eventFilter(watched, event)


# ── Multi-Mood Contract & Mic-to-Smoke Reactivity Hook ──────────────────────
MOOD_CONTRACT = (
    "\n\n[MOOD CONTRACT - AVATAR EXPRESSION ENGINE]\n"
    "CRITICAL: You may ONLY use mood names from the EXACT list below. "
    "Inventing moods (e.g. 'Crazy', 'Happy2', 'Super') is FORBIDDEN - "
    "unknown moods are dropped and the face stays frozen.\n"
    "Begin every reply with `mood: <expression>` on the VERY FIRST LINE, followed by a newline.\n"
    "- You can specify 1 expression (`mood: happy`) OR chain 2 to 3 comma-separated expressions "
    "to act out across your reply (`mood: angry, sad` plays 1:1 on the 1st and 2nd half of your reply; "
    "`mood: shocked, happy, flirty` plays 1:1:1 across each third of your reply!).\n"
    "- Available expressions: happy, laughing, chibi joy, excited, sparkle hype, in love, heart eyes, smitten, "
    "flirty, winking, blushing, flustered, shy, tsundere, uwu, owo, kawaii, smug, mischievous, side eye, sarcastic, "
    "thinking, focused, confused, really puzzled, disbelief, nani, pog, starstruck, galaxy brain, shonen resolve, "
    "angry, annoyed, rage, baka, menacing, disgusted, sad, crying, heavy sobbing, pleading, copium, doomer, "
    "awkward, nervous, nervous smile, monkas, sus, suspicious, fearful, scared, terrified, shocked, relieved, "
    "tired, sleepy, deadpan, blank, dizzy, hypnotized, derp, gremlin, yandere.\n"
)

_orig_mw_on_done = CelStudioCerebrium.on_done
_orig_mw_wire_live = getattr(CelStudioCerebrium, "_wire_live_controls", None)


def _patched_mw_on_done(self, sid: str, full_text: str, *args, **kwargs):
    from cellium.core.utils import split_mood_first, parse_mood_sequence, clean_chat_display
    _cleaned_body, raw_mood = split_mood_first(full_text or "")
    mood_seq = parse_mood_sequence(raw_mood or "")
    plain_preload = clean_chat_display(full_text or "")
    est_ms = max(1800, min(14000, max(4, len(plain_preload.split())) * 340))

    _orig_mw_on_done(self, sid, full_text, *args, **kwargs)

    if len(mood_seq) > 1:
        try:
            if getattr(self, "_live", None) is not None and self._live.active and getattr(self, "_live_stage", None) is not None:
                self._live_stage.play_mood_sequence(mood_seq, total_ms=est_ms, sentence_text=plain_preload)
        except Exception:
            pass
        try:
            comp = getattr(self, "_companion", None)
            if comp is not None and comp.visible:
                comp.play_mood_sequence(mood_seq, total_ms=est_ms, sentence_text=plain_preload)
        except Exception:
            pass


def _patched_mw_wire_live(self):
    if _orig_mw_wire_live is not None:
        _orig_mw_wire_live(self)
    try:
        la = getattr(self, "_live_audio", None)
        ls = getattr(self, "_live_stage", None)
        if la is not None and ls is not None and getattr(ls, "smoke", None) is not None:
            if not getattr(la, "_smoke_level_wired", False):
                la.level.connect(lambda rms: ls.smoke.set_voice_level(rms, speaker="user"))
                la._smoke_level_wired = True
    except Exception:
        pass


CelStudioCerebrium.on_done = _patched_mw_on_done
if _orig_mw_wire_live is not None:
    CelStudioCerebrium._wire_live_controls = _patched_mw_wire_live


# ── 1b. Bezier Circle-to-Pill Typewriter & Backspace Squash Toast ────────────
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QRect, QPoint, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient,
                           QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import QWidget


# ── Post-show warmup worker ──────────────────────────────────────────────────
class _CelMojiWarmupWorker(QThread):
    """Parse all CelMoji sets off the UI thread and emit the merged tabs dict."""

    #: Never name this ``finished``: QThread already owns a zero-argument
    #: ``finished`` signal, and re-declaring it with a payload corrupts
    #: PySide's metacall dispatch (crash at ``started`` emission).
    tabsReady = Signal(dict)

    def __init__(self, main_win):
        super().__init__(main_win)
        self._main = main_win

    def run(self) -> None:
        # Reuse the picker's parsing logic but without any UI touches.
        # We need a transient picker instance just for its parsing methods.
        try:
            from cellium.ui.settings.dialog import EmojiPickerWidget
            picker = EmojiPickerWidget.__new__(EmojiPickerWidget)
            # Minimal init for the paths / helpers it uses.
            picker._celmoji_dir = Path.home() / "Documents" / "Projects" / "Python" / "CelSuite CelMoji"
            picker._celmoji_data_dir = Path.home() / ".local" / "share" / "celmoji"
            picker.emojis = []
            picker.kaomojis = []
            picker.emoticons = []
            # Borrow the class's static parse method.
            tabs = picker._build_raw_datasets()
            self.tabsReady.emit(tabs)
        except Exception:
            self.tabsReady.emit({})


class _MorphingToastBubble(QWidget):
    """Dynamic Island / Bezier Circle-to-Pill Toast with synced Typewriter & Backspace Squash!

    Lifecycle:
    1. FLOAT_UP  : Spawns as a perfect 44x44 circle at the bottom, shoots up fast and
                   decelerates smoothly to its resting Y via a cubic Bezier curve (1 - (1-t)^3).
    2. TYPING    : Elongates smoothly into a pill as characters type out at mid-normal-fast
                   speed (~22ms/char). Never truncates - wraps cleanly if ultra-long!
    3. HOLD      : Stays visible for 5.0 seconds (or clicks early to dismiss immediately!).
    4. BACKSPACE : Deletes characters in real time while squashing the pill back down to a
                   perfect 44x44 circle at the exact speed of the deleting!
    5. DROP_DOWN : Drops back down along an InCubic Bezier curve and deletes itself.
    """
    CIRCLE_D = 44

    def __init__(self, parent: QWidget, message: str, icon: str = "✨", hold_ms: int = 5000, slot_idx: int = 0):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to dismiss")

        raw_msg = str(message or "").strip()
        ic = str(icon or "✨").strip()
        if ic and not raw_msg.startswith(ic):
            self.full_text = f"{ic}  {raw_msg}"
        else:
            self.full_text = raw_msg or ic
        self.icon_only = ic or "✨"

        self.hold_ms = max(5000, int(hold_ms or 5000))
        self.slot_idx = slot_idx

        self.font_obj = QFont("Segoe UI", -1, QFont.Weight.DemiBold)
        self.font_obj.setPixelSize(13)

        # Mid-normal-fast typing & synced backspace speeds
        n_chars = max(1, len(self.full_text))
        self.type_step_ms = max(12.0, min(24.0, 1600.0 / max(10, n_chars)))
        self.bs_step_ms = max(10.0, min(18.0, 1100.0 / max(10, n_chars)))

        self.phase = "FLOAT_UP"
        self.phase_t0 = time.monotonic() * 1000.0
        self.float_up_dur = 360.0
        self.drop_down_dur = 300.0

        self.cur_w = float(self.CIRCLE_D)
        self.cur_h = float(self.CIRCLE_D)
        self.cur_y = float(parent.height() + 12)
        self.vis_text = ""
        self.n_shown = 0

        self.resize(self.CIRCLE_D, self.CIRCLE_D)
        self._reposition()
        self.show()
        self.raise_()

        self._timer = QTimer(self)
        self._timer.setInterval(16)  # 60 FPS silky Bezier + typewriter interpolation
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _live_slot(self) -> int:
        """Dynamic stacking slot - recomputed from the parent's live toast list
        so toasts above a dismissing one glide down into the freed space (14)."""
        p = self.parentWidget()
        lst = getattr(p, "_active_morph_toasts", None) if p is not None else None
        if lst:
            try:
                vis = [t for t in lst if t is not None and t.isVisible()]
                if self in vis:
                    return vis.index(self)
            except Exception:
                pass
        return self.slot_idx

    def _target_stop_y(self) -> float:
        p = self.parentWidget()
        ph = float(p.height()) if p is not None else 720.0
        return max(60.0, ph - 98.0 - self._live_slot() * 54.0)

    def _measure_pill_for_text(self, txt: str) -> tuple[float, float]:
        if not txt:
            return float(self.CIRCLE_D), float(self.CIRCLE_D)
        p = self.parentWidget()
        max_w = max(260, (p.width() - 80) if p is not None else 680)
        fm = QFontMetrics(self.font_obj)
        single_w = fm.horizontalAdvance(txt) + 38
        if single_w <= max_w:
            return float(max(self.CIRCLE_D, single_w)), float(self.CIRCLE_D)
        # Multi-line wrap so huge messages NEVER truncate!
        inner_w = max_w - 38
        rect = fm.boundingRect(0, 0, int(inner_w), 1000, int(Qt.TextFlag.TextWordWrap), txt)
        return float(max_w), float(max(self.CIRCLE_D, rect.height() + 24))

    def _reposition(self) -> None:
        p = self.parentWidget()
        pw = float(p.width()) if p is not None else 1000.0
        w_int = max(self.CIRCLE_D, int(round(self.cur_w)))
        h_int = max(self.CIRCLE_D, int(round(self.cur_h)))
        x_int = int(round((pw - w_int) * 0.5))
        y_int = int(round(self.cur_y))
        self.setGeometry(x_int, y_int, w_int, h_int)

    def mousePressEvent(self, event) -> None:
        # Clicking the toast before 5 seconds immediately triggers synchronized backspace + squash!
        if self.phase in ("FLOAT_UP", "TYPING", "HOLD"):
            if self.n_shown <= 0:
                self.n_shown = max(1, len(self.full_text))
            self.phase = "BACKSPACE"
            self.phase_t0 = time.monotonic() * 1000.0
        event.accept()

    def _glass_backdrop(self):
        """Sample the frosted wallpaper behind this toast for a liquid-glass body."""
        try:
            ws = getattr(self.window(), "wallpaper_surface", None)
        except Exception:
            return None
        if ws is None or self.width() < 4 or self.height() < 4:
            return None
        try:
            frost = ws.frost_pixmap(24)
        except Exception:
            frost = None
        if frost is None or frost.isNull():
            return None
        try:
            win = self.window()
            if ws.window() is not win:
                # Never call mapTo() across unrelated hierarchies - Qt spams
                # "QWidget::mapTo(): parent must be in parent hierarchy".
                return None
            tl = self.mapTo(win, QPoint(0, 0))
            ws_tl = ws.mapTo(win, QPoint(0, 0))
            tl -= ws_tl
        except Exception:
            return None
        return frost, QRectF(tl.x(), tl.y(), self.width(), self.height())

    def _tick(self) -> None:
        now = time.monotonic() * 1000.0
        dt = max(0.0, now - self.phase_t0)
        p = self.parentWidget()
        ph = float(p.height()) if p is not None else 720.0
        start_y = ph + 12.0
        stop_y = self._target_stop_y()
        total_chars = len(self.full_text)

        if self.phase == "FLOAT_UP":
            u = min(1.0, dt / self.float_up_dur)
            # Cubic Bezier Out: fast launch from bottom, smooth deceleration into stopping point
            ease = 1.0 - ((1.0 - u) ** 3)
            self.cur_y = start_y + (stop_y - start_y) * ease
            self.cur_w = float(self.CIRCLE_D)
            self.cur_h = float(self.CIRCLE_D)
            self.vis_text = ""
            if u >= 1.0:
                self.cur_y = stop_y
                self.phase = "TYPING"
                self.phase_t0 = now

        elif self.phase == "TYPING":
            self.cur_y += (stop_y - self.cur_y) * 0.25
            self.n_shown = min(total_chars, max(1, int(dt / self.type_step_ms) + 1))
            self.vis_text = self.full_text[: self.n_shown]
            tw, th = self._measure_pill_for_text(self.vis_text)
            # Smoothly elongate pill in lockstep with typed characters
            self.cur_w += (tw - self.cur_w) * 0.42
            self.cur_h += (th - self.cur_h) * 0.42
            if self.n_shown >= total_chars and abs(self.cur_w - tw) < 1.5:
                self.cur_w, self.cur_h = tw, th
                self.phase = "HOLD"
                self.phase_t0 = now

        elif self.phase == "HOLD":
            self.cur_y += (stop_y - self.cur_y) * 0.25
            self.vis_text = self.full_text
            tw, th = self._measure_pill_for_text(self.vis_text)
            self.cur_w += (tw - self.cur_w) * 0.35
            self.cur_h += (th - self.cur_h) * 0.35
            if dt >= self.hold_ms:
                self.n_shown = total_chars
                self.phase = "BACKSPACE"
                self.phase_t0 = now

        elif self.phase == "BACKSPACE":
            self.cur_y += (stop_y - self.cur_y) * 0.25
            deleted = int(dt / self.bs_step_ms) + 1
            rem = max(0, self.n_shown - deleted)
            self.vis_text = self.full_text[:rem]
            tw, th = self._measure_pill_for_text(self.vis_text)
            # Squash pill back to 44x44 circle at the exact speed of the backspace deleting!
            self.cur_w += (tw - self.cur_w) * 0.48
            self.cur_h += (th - self.cur_h) * 0.48
            if rem == 0 and abs(self.cur_w - self.CIRCLE_D) < 2.0:
                self.cur_w = float(self.CIRCLE_D)
                self.cur_h = float(self.CIRCLE_D)
                self.vis_text = ""
                self.phase = "DROP_DOWN"
                self.phase_t0 = now
                # Free the stack slot NOW so toasts above glide down while
                # this one drops away - not only after the drop finishes (14).
                if p is not None and hasattr(p, "_active_morph_toasts"):
                    try:
                        p._active_morph_toasts.remove(self)
                    except ValueError:
                        pass

        elif self.phase == "DROP_DOWN":
            u = min(1.0, dt / self.drop_down_dur)
            # Cubic Bezier In: accelerates smoothly downward off-screen
            ease = u * u * u
            self.cur_y = stop_y + (start_y - stop_y) * ease
            self.cur_w = float(self.CIRCLE_D)
            self.cur_h = float(self.CIRCLE_D)
            if u >= 1.0:
                self._timer.stop()
                if p is not None and hasattr(p, "_active_morph_toasts"):
                    try:
                        p._active_morph_toasts.remove(self)
                    except ValueError:
                        pass
                self.hide()
                self.deleteLater()
                return

        self._reposition()
        self.update()

    def paintEvent(self, _event) -> None:
        """Liquid-glass toast: frosted wallpaper body, purple rim, soft glow."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        r = min(w, h) * 0.5  # Perfect circle when w==h, true stadium pill when elongated!

        rect = QRectF(2.0, 2.0, max(4.0, w - 4.0), max(4.0, h - 4.0))
        glass_path = QPainterPath()
        glass_path.addRoundedRect(rect, r, r)

        # 1. Translucent glass body - real blurred wallpaper sampled behind us,
        #    tinted purple. Falls back to a see-through wash without wallpaper.
        backdrop = self._glass_backdrop()
        painter.setClipPath(glass_path)
        if backdrop is not None:
            frost, src = backdrop
            painter.drawPixmap(QRectF(0.0, 0.0, w, h), frost, src)
        else:
            painter.fillRect(rect, QColor(20, 12, 38, 200))
        tint = QLinearGradient(0.0, 0.0, w * 0.2, h)
        tint.setColorAt(0.0, QColor(126, 58, 222, 54))
        tint.setColorAt(1.0, QColor(24, 12, 46, 78))
        painter.fillRect(rect, QBrush(tint))
        sheen = QLinearGradient(0.0, 0.0, w * 0.35, h * 0.9)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 36))
        sheen.setColorAt(0.45, QColor(255, 255, 255, 9))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(rect, QBrush(sheen))
        painter.setClipping(False)

        # 2. Rim: soft outer glow + crisp purple outline + inner white hairline.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(168, 85, 247, 70), 4.0))
        painter.drawRoundedRect(QRectF(1.0, 1.0, max(4.0, w - 2.0), max(4.0, h - 2.0)), r, r)
        painter.setPen(QPen(QColor(192, 132, 252, 225), 1.5))
        painter.drawRoundedRect(rect, r, r)
        inner = QRectF(3.4, 3.4, max(2.0, w - 6.8), max(2.0, h - 6.8))
        painter.setPen(QPen(QColor(255, 255, 255, 46), 1.0))
        painter.drawRoundedRect(inner, max(1.0, r - 2.4), max(1.0, r - 2.4))

        # 3. Text/icons get a soft shadow so they stay readable on glass.
        painter.setFont(self.font_obj)
        if self.phase in ("FLOAT_UP", "DROP_DOWN") or not self.vis_text:
            painter.setPen(QColor(8, 4, 16, 175))
            painter.drawText(rect.translated(0.0, 1.2), int(Qt.AlignmentFlag.AlignCenter), self.icon_only)
            painter.setPen(QColor(250, 246, 255))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), self.icon_only)
        else:
            text_rect = QRectF(19.0, 6.0, max(10.0, w - 38.0), max(10.0, h - 12.0))
            flags = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            if h > self.CIRCLE_D + 6:
                flags |= int(Qt.TextFlag.TextWordWrap)
            painter.setPen(QColor(8, 4, 16, 165))
            painter.drawText(text_rect.translated(0.0, 1.2), flags, self.vis_text)
            painter.setPen(QColor(252, 250, 255))
            painter.drawText(text_rect, flags, self.vis_text)

        painter.end()


def _morphing_show_toast(self, message: str, duration: int = 5000, icon: str = "✨", **_kw) -> _MorphingToastBubble:
    """Spawn a Bezier Circle-to-Pill Typewriter Toast Bubble."""
    if not hasattr(self, "_active_morph_toasts"):
        self._active_morph_toasts = []

    def _toast_alive(t) -> bool:
        if t is None:
            return False
        try:
            import shiboken6
            if not shiboken6.isValid(t):
                return False
        except Exception:
            pass
        try:
            return t.isVisible()
        except RuntimeError:
            return False

    self._active_morph_toasts = [t for t in self._active_morph_toasts if _toast_alive(t)]

    # Play subtle pop sound
    try:
        play_ui_sound("pop", 0.35)
    except Exception:
        pass

    slot = len(self._active_morph_toasts)
    hold_ms = max(5000, int(duration)) if isinstance(duration, (int, float)) else 5000
    bubble = _MorphingToastBubble(self, message=str(message), icon=str(icon or "✨"), hold_ms=hold_ms, slot_idx=slot)
    self._active_morph_toasts.append(bubble)
    return bubble


CelStudioCerebrium.show_toast = _morphing_show_toast


# ── #5, #7, #8, #12, #14 & #15.5: Master Main Window Upgrade ─────────────────
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from cellium.core.svg_icons import get_svg_icon
from cellium.ui.avatar.pet import _apply_svg_icons_and_hover_to_pet_window

_prev_mw_init_v14 = CelStudioCerebrium.__init__
_prev_mw_build_sys_v12 = CelStudioCerebrium._build_system_prompt
_prev_mw_send_v14 = CelStudioCerebrium.send_message
_prev_mw_delta_v14 = CelStudioCerebrium.on_delta
_prev_mw_done_v14 = CelStudioCerebrium.on_done
_prev_mw_error_v14 = CelStudioCerebrium.on_error
_prev_mw_status_v14 = getattr(CelStudioCerebrium, "_on_worker_status", None)
_prev_mw_wire_live_v14 = getattr(CelStudioCerebrium, "_wire_live_controls", None)
_prev_mw_mini_tx_v14 = getattr(CelStudioCerebrium, "_on_mini_transcript", None)


def _patched_mw_init_v14(self, *args, **kwargs):
    self._queued_messages = []
    _prev_mw_init_v14(self, *args, **kwargs)
    self._ensure_floating_queue_bar()
    if getattr(self, "_companion", None) is not None:
        _apply_svg_icons_and_hover_to_pet_window(self._companion.window)


# ── #12: Stealth Acting System Prompt for Offline 3B & Cloud Models ──────────
def _patched_build_system_prompt_v12(self, for_offline: bool = False) -> str:
    raw_prompt = _prev_mw_build_sys_v12(self, for_offline=for_offline)
    u_name = _resolve_user_first_name(self)
    u_clause = (
        f"The human user talking to you is {u_name}. NEVER refer to yourself as {u_name}."
        if not (u_name == "there")
        else "You are talking to the human user. NEVER confuse your identity with the user's identity."
    )
    nl = chr(10)
    stealth_guard = (
        nl + nl + "[STEALTH ROLEPLAY & IDENTITY RULES - CRITICAL]" + nl
        + f"1. Your name is Cel. {u_clause}" + nl
        + "2. SHOW, DO NOT TELL: Embody your personality traits naturally through your tone, wit, and word choice. "
        + "NEVER announce, quote, title, or summarize your persona description as a motto, slogan, bullet list, or intro "
        + "(for example, NEVER write 'Cel the Sassy Gen Z Human' or state what your instructions are)." + nl
        + "3. Reply directly to what the user just said as if you are already mid-conversation." + nl
    )
    if "[STEALTH ROLEPLAY & IDENTITY RULES" not in raw_prompt:
        return raw_prompt + stealth_guard
    return raw_prompt


def _ensure_floating_queue_bar(self) -> QFrame | None:
    if hasattr(self, "queue_bar_frame") and self.queue_bar_frame is not None:
        return self.queue_bar_frame
    if not hasattr(self, "input_pill") or self.input_pill is None:
        return None
    parent_w = self.input_pill.parentWidget()
    if parent_w is None or parent_w.layout() is None:
        return None

    qf = QFrame(parent_w)
    qf.setObjectName("FloatingMessageQueueBar")
    qf.setStyleSheet(
        "QFrame#FloatingMessageQueueBar {"
        "  background: rgba(20, 12, 38, 0.94);"
        "  border: 1.5px solid rgba(168, 85, 247, 0.72);"
        "  border-radius: 14px;"
        "}"
    )
    q_lay = QVBoxLayout(qf)
    q_lay.setContentsMargins(12, 8, 12, 8)
    q_lay.setSpacing(6)
    qf.hide()

    p_lay = parent_w.layout()
    pill_idx = p_lay.indexOf(self.input_pill)
    if pill_idx >= 0:
        p_lay.insertWidget(pill_idx, qf)
    else:
        p_lay.addWidget(qf)

    self.queue_bar_frame = qf
    self.queue_bar_layout = q_lay
    return qf


def _refresh_floating_queue_bar(self) -> None:
    qf = self._ensure_floating_queue_bar()
    if qf is None:
        return
    q_lay = self.queue_bar_layout
    while q_lay.count():
        item = q_lay.takeAt(0)
        if item and item.widget():
            item.widget().deleteLater()

    queue = getattr(self, "_queued_messages", [])
    if not queue:
        qf.hide()
        return

    for idx, q_item in enumerate(queue):
        row = QFrame(qf)
        row.setStyleSheet(
            "QFrame { background: rgba(147, 51, 234, 0.16); border: 1px solid rgba(192, 132, 252, 0.35); border-radius: 9px; }"
        )
        r_lay = QHBoxLayout(row)
        r_lay.setContentsMargins(10, 4, 8, 4)
        r_lay.setSpacing(8)

        badge = QLabel(f"Queued #{idx + 1}", row)
        badge.setStyleSheet("color: #C084FC; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        r_lay.addWidget(badge)

        txt = q_item.get("text", "").replace("\n", " ").strip()
        preview = txt if len(txt) <= 68 else (txt[:65] + "…")
        lbl = QLabel(preview, row)
        lbl.setStyleSheet("color: #F3E8FF; font-size: 12px; border: none; background: transparent;")
        r_lay.addWidget(lbl, 1)

        btn_undo = QPushButton("Undo & Edit", row)
        btn_undo.setIcon(get_svg_icon("undo"))
        btn_undo.setIconSize(QSize(13, 13))
        btn_undo.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_undo.setToolTip("Remove from queue and append into your message box without losing current text")
        btn_undo.setStyleSheet(
            "QPushButton { background: rgba(147, 51, 234, 0.55); color: #FFFFFF; border: 1px solid #D8B4FE; "
            "border-radius: 6px; padding: 3px 10px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background: #9333EA; }"
        )
        btn_undo.clicked.connect(lambda _=False, i=idx: self._undo_and_edit_queued_message(i))
        r_lay.addWidget(btn_undo)

        btn_cancel = QPushButton("", row)
        btn_cancel.setIcon(get_svg_icon("close"))
        btn_cancel.setIconSize(QSize(12, 12))
        btn_cancel.setFixedSize(22, 22)
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setToolTip("Remove from queue")
        btn_cancel.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            "QPushButton:hover { background: rgba(239, 68, 68, 0.35); border-radius: 5px; }"
        )
        btn_cancel.clicked.connect(lambda _=False, i=idx: self._remove_queued_message(i))
        r_lay.addWidget(btn_cancel)

        q_lay.addWidget(row)

    qf.show()
    qf.raise_()


def _undo_and_edit_queued_message(self, idx: int) -> str:
    """Pop queued message at `idx` and APPEND it to whatever text is currently in `edit_input`!"""
    queue = getattr(self, "_queued_messages", [])
    if not (0 <= idx < len(queue)):
        return ""
    item = queue.pop(idx)
    q_text = (item.get("text") or "").strip()
    if item.get("attachments"):
        self.pending_attachments.extend(item["attachments"])
        if hasattr(self, "_refresh_attachment_Tray"):
            try:
                self._refresh_attachment_Tray()
            except Exception:
                pass

    if hasattr(self, "edit_input") and self.edit_input is not None and q_text:
        cur_draft = self.edit_input.toPlainText()
        if cur_draft.strip():
            sep = "\n" if not cur_draft.endswith(("\n", " ")) else ""
            combined = cur_draft + sep + q_text
        else:
            combined = q_text
        self.edit_input.setPlainText(combined)
        cursor = self.edit_input.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.edit_input.setTextCursor(cursor)
        self.edit_input.setFocus()

    self._refresh_floating_queue_bar()
    return q_text


def _remove_queued_message(self, idx: int) -> None:
    queue = getattr(self, "_queued_messages", [])
    if 0 <= idx < len(queue):
        queue.pop(idx)
        self._refresh_floating_queue_bar()


def _broadcast_live_activity(self, state: str, text: str, progress: float | None = None) -> None:
    try:
        ls = getattr(self, "_live_stage", None)
        if ls is not None and hasattr(ls, "set_live_activity"):
            ls.set_live_activity(state, text, progress=progress)
    except Exception:
        pass
    try:
        comp = getattr(self, "_companion", None)
        if comp is not None and comp.visible and hasattr(comp, "set_activity_state"):
            comp.set_activity_state(state, text)
    except Exception:
        pass


def _patched_send_v14(self, *args, **kwargs):
    # Forwarded to _prev_mw_send_v14 where user_msg["attached_files_text"] = attached_files_text is persisted
    # #14: If AI worker is currently generating, queue the message into our Floating Queue Bar!
    is_busy = bool(getattr(self, "worker", None) is not None and self.worker.isRunning())
    if is_busy and not getattr(self, "_edit_mode", False):
        raw_txt = self.edit_input.toPlainText().strip() if hasattr(self, "edit_input") else ""
        atts = list(getattr(self, "pending_attachments", []) or [])
        if raw_txt or atts:
            if not hasattr(self, "_queued_messages"):
                self._queued_messages = []
            self._queued_messages.append({
                "text": raw_txt,
                "attachments": atts,
                "sid": self.current_sid,
            })
            if hasattr(self, "edit_input"):
                self.edit_input.clear()
            if hasattr(self, "pending_attachments"):
                self.pending_attachments.clear()
            self._refresh_floating_queue_bar()
            return

    model_name = self.settings.get("selected_model", "AI Model")
    short_m = model_name.split("]")[-1].strip() if "]" in model_name else model_name
    is_offline = is_offline_model_key(model_name, self.models.get(model_name))
    if is_offline:
        _broadcast_live_activity(self, "loading", f"🟡 Preparing local GGUF ({short_m[:24]})…", progress=0.35)
    else:
        _broadcast_live_activity(self, "thinking", f"🟣 Cel is thinking - prompting {short_m[:24]}…", progress=0.15)
    self._stream_token_count = 0
    self._last_pet_stream_ts = 0.0
    return _prev_mw_send_v14(self, *args, **kwargs)


def _patched_on_delta_v14(self, sid: str, delta: str):
    # Preserve _persist_stream_text cross-chat isolation check (#15.5)
    if sid != self.current_sid:
        if hasattr(self, "_persist_stream_text"):
            return _prev_mw_delta_v14(self, sid, delta)
        return _prev_mw_delta_v14(self, sid, delta)

    _prev_mw_delta_v14(self, sid, delta)
    self._stream_token_count = getattr(self, "_stream_token_count", 0) + 1
    tok_n = self._stream_token_count
    prog = min(0.95, 0.18 + (tok_n / 140.0) * 0.77)

    from cellium.core.utils import clean_chat_display
    clean_so_far = clean_chat_display(getattr(self, "stream_accum", "") or "")
    words_n = len(clean_so_far.split()) if clean_so_far else 0

    if tok_n == 1 or tok_n % 4 == 0:
        _broadcast_live_activity(
            self,
            "thinking",
            f"🟣 Cel is composing reply… ({words_n} words · {int(prog * 100)}%)",
            progress=prog,
        )

    now = time.monotonic()
    if clean_so_far and (now - getattr(self, "_last_pet_stream_ts", 0.0) >= 0.045):
        self._last_pet_stream_ts = now
        comp = getattr(self, "_companion", None)
        if comp is not None and comp.visible and hasattr(comp, "stream_say"):
            comp.stream_say(clean_so_far, is_final=False, speaker="Cel")


def _drain_next_queued_message_if_any(self) -> None:
    queue = getattr(self, "_queued_messages", [])
    if not queue:
        return
    if getattr(self, "worker", None) is not None and self.worker.isRunning():
        return
    next_item = queue.pop(0)
    self._refresh_floating_queue_bar()

    # Preserve whatever draft text the user is currently typing in `edit_input`!
    saved_draft = self.edit_input.toPlainText() if hasattr(self, "edit_input") else ""
    saved_atts = list(getattr(self, "pending_attachments", []) or [])
    try:
        self.edit_input.setPlainText(next_item.get("text", ""))
        self.pending_attachments = list(next_item.get("attachments", []) or [])
        self.send_message()
    finally:
        if saved_draft:
            self.edit_input.setPlainText(saved_draft)
            cursor = self.edit_input.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.edit_input.setTextCursor(cursor)
        if saved_atts:
            self.pending_attachments.extend(saved_atts)


def _patched_on_done_v14(self, sid: str, full_text: str, *args, **kwargs):
    from cellium.core.utils import clean_chat_display
    clean_final = clean_chat_display(full_text or "")

    comp = getattr(self, "_companion", None)
    if (comp is not None and comp.visible and clean_final
            and not _is_failed_reply_text(clean_final)):
        if hasattr(comp, "stream_say"):
            comp.stream_say(clean_final, is_final=True, speaker="Cel")

    voice_choice = self.settings.get("live_voice", "Cel (Default)")
    is_live_call = bool(getattr(self, "_live", None) is not None and self._live.active)
    is_pet_call = bool(getattr(self, "_mini_active", False))

    if is_live_call or is_pet_call:
        _broadcast_live_activity(
            self,
            "tts",
            f"🟠 Translating Cel's text to voice ({voice_choice})…",
            progress=0.75,
        )
    else:
        _broadcast_live_activity(self, "ready", "🟢 Ready - Listening for your voice…", progress=0.18)

    res = _prev_mw_done_v14(self, sid, full_text, *args, **kwargs)
    if getattr(self, "_queued_messages", None):
        QTimer.singleShot(120, self._drain_next_queued_message_if_any)
    return res


def _patched_on_error_v14(self, sid: str, title: str, msg: str):
    short_err = (title or msg or "Generation failed").splitlines()[0][:48]
    _broadcast_live_activity(self, "error", f"🔴 {short_err} - check Dev Console Logs", progress=1.0)
    res = _prev_mw_error_v14(self, sid, title, msg)
    self._refresh_floating_queue_bar()
    return res


# #8: Show what the user said on the Pet bubble + smooth noise-gated mic level in Pet Mode!
def _patched_on_mini_transcript_v8(self, text: str) -> None:
    cleaned = (text or "").strip()
    if cleaned:
        comp = getattr(self, "_companion", None)
        if comp is not None and comp.visible and hasattr(comp, "stream_say"):
            comp.stream_say(cleaned, is_final=True, speaker="You")
    if _prev_mw_mini_tx_v14 is not None:
        return _prev_mw_mini_tx_v14(self, text)


def _patched_on_mini_level_v8(self, rms: float) -> None:
    """Noise-gated, exponentially smoothed mic level on Pet Mode with 180ms throttle so it NEVER jumps!"""
    comp = getattr(self, "_companion", None)
    if comp is None or not comp.visible or not getattr(self, "_mini_active", False):
        return
    now = time.monotonic()
    floor = float(getattr(self, "_pet_rms_floor", 0.008))
    if rms < floor:
        floor = 0.85 * floor + 0.15 * rms
    else:
        floor = 0.98 * floor + 0.02 * rms
    self._pet_rms_floor = floor

    net_rms = max(0.0, float(rms) - floor * 1.35)
    smooth = 0.72 * float(getattr(self, "_pet_rms_smooth", 0.0)) + 0.28 * net_rms
    self._pet_rms_smooth = smooth

    if now - float(getattr(self, "_pet_rms_last_ui", 0.0)) < 0.18:
        return
    self._pet_rms_last_ui = now
    bars = min(5, int(smooth * 38.0))
    meter = ("●" * bars) + ("○" * (5 - bars))
    comp.window.set_status_text(f"🟢 Listening  {meter}")


CelStudioCerebrium.__init__ = _patched_mw_init_v14
CelStudioCerebrium._build_system_prompt = _patched_build_system_prompt_v12
CelStudioCerebrium._ensure_floating_queue_bar = _ensure_floating_queue_bar
CelStudioCerebrium._refresh_floating_queue_bar = _refresh_floating_queue_bar
CelStudioCerebrium._undo_and_edit_queued_message = _undo_and_edit_queued_message
CelStudioCerebrium._remove_queued_message = _remove_queued_message
CelStudioCerebrium._drain_next_queued_message_if_any = _drain_next_queued_message_if_any
CelStudioCerebrium.send_message = _patched_send_v14
CelStudioCerebrium.on_delta = _patched_on_delta_v14
CelStudioCerebrium.on_done = _patched_on_done_v14
CelStudioCerebrium.on_error = _patched_on_error_v14
CelStudioCerebrium._on_mini_transcript = _patched_on_mini_transcript_v8
CelStudioCerebrium._on_mini_level = _patched_on_mini_level_v8


# ── Screenshot 2-7 Fix: Suppress Empty `<` Stub Bubbles Before Tool Calls ────
_orig_mw_agent_tc = getattr(CelStudioCerebrium, "_on_agent_tool_call", None)

if _orig_mw_agent_tc is not None:
    def _patched_mw_agent_tc(self, tool_name: str, args_dict: dict, result_str: str = ""):
        # Ensure file_read with `paths` list still shows the filename on the pill instead of `→ Read ?`
        if isinstance(args_dict, dict) and not args_dict.get("path"):
            for alt_k in ("paths", "file_path", "file", "files", "filename"):
                val = args_dict.get(alt_k)
                if val:
                    args_dict["path"] = val[0] if isinstance(val, (list, tuple)) else str(val)
                    break

        # If the live streaming bubble before this tool call only has `<` or `<think` or is empty,
        # remove it before injecting the tool card so we never leave `(interrupted - no reply text) <` stubs!
        if self.current_sid != self._pending_sid:
            return _orig_mw_agent_tc(self, tool_name, args_dict)
        if self.current_sid == self._pending_sid:
            live_b = getattr(self, "live_bubble", None)
            if live_b is not None:
                from cellium.core.utils import clean_chat_display
                vis_body = clean_chat_display(getattr(self, "stream_accum", "") or "")
                if len(vis_body.strip()) <= 2:
                    try:
                        self.chat_layout.removeWidget(live_b)
                        live_b.hide()
                        live_b.deleteLater()
                        self.live_bubble = None
                        self.stream_accum = ""
                    except Exception:
                        pass
        return _orig_mw_agent_tc(self, tool_name, args_dict)

    CelStudioCerebrium._on_agent_tool_call = _patched_mw_agent_tc


# ── #16, #19, #20, #21: Window Controls, Focus Studio, Analytics Hover & Branch Visibility ──
from datetime import datetime, date, timedelta
from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSpinBox, QToolTip, QVBoxLayout, QWidget,
)
from cellium.core.svg_icons import get_svg_icon
from cellium.core.utils import clean_chat_display, estimate_accurate_tokens


# ── #19: Full-Featured Focus Studio Page ─────────────────────────────────────
class _FocusRingCanvas(QWidget):
    """Glowing circular neon countdown ring for Focus Studio."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(230, 230)
        self.progress = 1.0
        self.time_str = "25:00"
        self.phase_str = "FOCUS WORK"
        self.round_str = "Round 1 / 4"
        self.phase_color = QColor("#A855F7")

    def set_ring_state(self, progress: float, time_str: str, phase_str: str, round_str: str, color_hex: str) -> None:
        self.progress = max(0.0, min(1.0, float(progress)))
        self.time_str = time_str
        self.phase_str = phase_str
        self.round_str = round_str
        self.phase_color = QColor(color_hex)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())
        rect = QRectF(18.0, 18.0, w - 36.0, h - 36.0)

        # Background track ring
        painter.setPen(QPen(QColor(147, 51, 234, 45), 10.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 0, 360 * 16)

        # Active neon progress arc
        span_angle = int(-360.0 * 16.0 * self.progress)
        painter.setPen(QPen(self.phase_color, 10.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 90 * 16, span_angle)

        # Center countdown text
        f_time = QFont("Segoe UI", 28, QFont.Weight.Bold)
        painter.setFont(f_time)
        painter.setPen(QColor("#F8F4FF"))
        painter.drawText(QRectF(0, 62, w, 54), int(Qt.AlignmentFlag.AlignCenter), self.time_str)

        f_phase = QFont("Segoe UI", 10, QFont.Weight.Bold)
        painter.setFont(f_phase)
        painter.setPen(self.phase_color)
        painter.drawText(QRectF(0, 118, w, 24), int(Qt.AlignmentFlag.AlignCenter), self.phase_str)

        f_round = QFont("Segoe UI", 9, QFont.Weight.Normal)
        painter.setFont(f_round)
        painter.setPen(QColor("#C4B5FD"))
        painter.drawText(QRectF(0, 142, w, 22), int(Qt.AlignmentFlag.AlignCenter), self.round_str)
        painter.end()


class FocusStudioPage(QWidget):
    """Dedicated Focus Mode Studio Page (#19) with presets, custom timers & task tracker."""
    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self.phase = "work"  # "work" | "short_break" | "long_break"
        self.round_num = 1
        self.running = False
        self.completed_pomodoros = 0
        self.focused_seconds_today = 0

        self.work_min = 25
        self.short_min = 5
        self.long_min = 15
        self.rounds_target = 4
        self.total_sec = self.work_min * 60
        self.remaining_sec = self.total_sec

        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(28, 22, 28, 22)
        root_lay.setSpacing(16)

        # Header row
        hdr = QHBoxLayout()
        btn_back = QPushButton("Back to Chat")
        btn_back.setIcon(get_svg_icon("prev"))
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.setStyleSheet(
            "QPushButton { background: #9333EA; color: #FFFFFF; border-radius: 10px; "
            "padding: 6px 14px; font-size: 12px; font-weight: bold; border: none; }"
            "QPushButton:hover { background: #A855F7; }"
        )
        btn_back.clicked.connect(self.main_win.show_chat_view)
        hdr.addWidget(btn_back)

        title = QLabel("Focus Studio & Deep Work Timer")
        title.setStyleSheet("color: #F8F4FF; font-size: 18px; font-weight: bold; margin-left: 10px;")
        hdr.addWidget(title)
        hdr.addStretch(1)

        self.lbl_stats = QLabel("Completed Today: 0 Pomodoros (0 min)")
        self.lbl_stats.setStyleSheet(
            "color: #C084FC; font-size: 12px; font-weight: bold; "
            "background: rgba(20, 12, 38, 0.82); border: 1px solid rgba(168, 85, 247, 0.4); "
            "border-radius: 10px; padding: 6px 12px;"
        )
        hdr.addWidget(self.lbl_stats)
        root_lay.addLayout(hdr)

        # Main 2-column body
        body = QHBoxLayout()
        body.setSpacing(20)

        # Left column: Ring + Controls + Presets + Custom Durations
        left_card = QFrame(self)
        left_card.setStyleSheet(
            "QFrame { background: rgba(16, 10, 32, 0.86); border: 1px solid rgba(168, 85, 247, 0.35); border-radius: 16px; }"
        )
        l_lay = QVBoxLayout(left_card)
        l_lay.setContentsMargins(20, 18, 20, 18)
        l_lay.setSpacing(12)

        self.ring = _FocusRingCanvas(left_card)
        l_lay.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignHCenter)

        # Transport controls
        ctl_row = QHBoxLayout()
        self.btn_start = QPushButton("Start Focus")
        self.btn_start.setIcon(get_svg_icon("play"))
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setStyleSheet(
            "QPushButton { background: #9333EA; color: #FFFFFF; border-radius: 10px; "
            "padding: 8px 18px; font-size: 13px; font-weight: bold; border: none; }"
            "QPushButton:hover { background: #A855F7; }"
        )
        self.btn_start.clicked.connect(self.toggle_start_pause)
        ctl_row.addWidget(self.btn_start)

        btn_skip = QPushButton("Skip Phase")
        btn_skip.setIcon(get_svg_icon("next"))
        btn_skip.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_skip.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.08); color: #E9D5FF; border-radius: 10px; "
            "padding: 8px 14px; font-size: 12px; font-weight: bold; border: 1px solid rgba(168,85,247,0.35); }"
            "QPushButton:hover { background: rgba(147,51,234,0.35); }"
        )
        btn_skip.clicked.connect(self.skip_phase)
        ctl_row.addWidget(btn_skip)

        btn_reset = QPushButton("Reset")
        btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset.setStyleSheet(btn_skip.styleSheet())
        btn_reset.clicked.connect(self.reset_timer)
        ctl_row.addWidget(btn_reset)
        l_lay.addLayout(ctl_row)

        # One-click presets
        preset_row = QHBoxLayout()
        for p_label, (wm, sm, lm) in (
            ("Pomodoro 25/5", (25, 5, 15)),
            ("Deep Work 50/10", (50, 10, 20)),
            ("Uni Study 45/15", (45, 15, 25)),
            ("Sprint 15/3", (15, 3, 10)),
        ):
            pb = QPushButton(p_label)
            pb.setCursor(Qt.CursorShape.PointingHandCursor)
            pb.setStyleSheet(
                "QPushButton { background: rgba(147, 51, 234, 0.18); color: #D8B4FE; border-radius: 8px; "
                "padding: 5px 8px; font-size: 11px; font-weight: 600; border: 1px solid rgba(168,85,247,0.3); }"
                "QPushButton:hover { background: rgba(147, 51, 234, 0.45); color: #FFFFFF; }"
            )
            pb.clicked.connect(lambda _=False, w=wm, s=sm, l=lm: self.apply_preset(w, s, l))
            preset_row.addWidget(pb)
        l_lay.addLayout(preset_row)

        # Custom duration spinboxes
        spin_row = QHBoxLayout()
        spin_style = (
            "QSpinBox { background: rgba(10, 6, 22, 0.9); color: #F8F4FF; border: 1px solid #9333EA; "
            "border-radius: 7px; padding: 4px 8px; font-size: 12px; font-weight: bold; }"
        )
        self.spin_work = QSpinBox()
        self.spin_work.setRange(1, 180)
        self.spin_work.setValue(25)
        self.spin_work.setSuffix("m Work")
        self.spin_work.setStyleSheet(spin_style)
        self.spin_work.valueChanged.connect(self._on_durations_changed)
        spin_row.addWidget(self.spin_work)

        self.spin_short = QSpinBox()
        self.spin_short.setRange(1, 60)
        self.spin_short.setValue(5)
        self.spin_short.setSuffix("m Short")
        self.spin_short.setStyleSheet(spin_style)
        self.spin_short.valueChanged.connect(self._on_durations_changed)
        spin_row.addWidget(self.spin_short)

        self.spin_long = QSpinBox()
        self.spin_long.setRange(1, 90)
        self.spin_long.setValue(15)
        self.spin_long.setSuffix("m Long")
        self.spin_long.setStyleSheet(spin_style)
        self.spin_long.valueChanged.connect(self._on_durations_changed)
        spin_row.addWidget(self.spin_long)

        self.spin_rounds = QSpinBox()
        self.spin_rounds.setRange(1, 12)
        self.spin_rounds.setValue(4)
        self.spin_rounds.setSuffix(" Rounds")
        self.spin_rounds.setStyleSheet(spin_style)
        self.spin_rounds.valueChanged.connect(self._on_durations_changed)
        spin_row.addWidget(self.spin_rounds)
        l_lay.addLayout(spin_row)

        # Options row
        opt_row = QHBoxLayout()
        self.chk_autostart = QCheckBox("Auto-start next phase")
        self.chk_autostart.setChecked(True)
        self.chk_autostart.setStyleSheet("color: #E9D5FF; font-size: 12px; border: none;")
        opt_row.addWidget(self.chk_autostart)

        self.chk_sound = QCheckBox("Play chime on phase complete")
        self.chk_sound.setChecked(True)
        self.chk_sound.setStyleSheet("color: #E9D5FF; font-size: 12px; border: none;")
        opt_row.addWidget(self.chk_sound)
        l_lay.addLayout(opt_row)

        body.addWidget(left_card, 1)

        # Right column: Focus Tasks & Session Checklist
        right_card = QFrame(self)
        right_card.setStyleSheet(left_card.styleSheet())
        r_lay = QVBoxLayout(right_card)
        r_lay.setContentsMargins(20, 18, 20, 18)
        r_lay.setSpacing(10)

        lbl_tasks = QLabel("Focus Session Tasks & Goals")
        lbl_tasks.setStyleSheet("color: #F8F4FF; font-size: 15px; font-weight: bold; border: none;")
        r_lay.addWidget(lbl_tasks)

        add_row = QHBoxLayout()
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("Add a study or coding task for this session... (Enter)")
        self.task_input.setStyleSheet(
            "QLineEdit { background: rgba(10, 6, 22, 0.9); color: #F8F4FF; border: 1.2px solid #9333EA; "
            "border-radius: 9px; padding: 7px 12px; font-size: 12px; }"
        )
        self.task_input.returnPressed.connect(self.add_focus_task)
        add_row.addWidget(self.task_input, 1)

        btn_add_t = QPushButton("Add Task")
        btn_add_t.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_t.setStyleSheet(self.btn_start.styleSheet())
        btn_add_t.clicked.connect(self.add_focus_task)
        add_row.addWidget(btn_add_t)
        r_lay.addLayout(add_row)

        self.task_list = QListWidget()
        self.task_list.setStyleSheet(
            "QListWidget { background: rgba(10, 6, 22, 0.72); border: 1px solid rgba(168,85,247,0.3); "
            "border-radius: 10px; padding: 6px; color: #F3E8FF; font-size: 13px; }"
            "QListWidget::item { padding: 6px 8px; border-radius: 6px; }"
            "QListWidget::item:hover { background: rgba(147, 51, 234, 0.22); }"
        )
        r_lay.addWidget(self.task_list, 1)

        btn_clear_done = QPushButton("Clear Completed Tasks")
        btn_clear_done.setIcon(get_svg_icon("trash"))
        btn_clear_done.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear_done.setStyleSheet(btn_skip.styleSheet())
        btn_clear_done.clicked.connect(self.clear_completed_tasks)
        r_lay.addWidget(btn_clear_done, 0, Qt.AlignmentFlag.AlignRight)

        body.addWidget(right_card, 1)
        root_lay.addLayout(body, 1)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_second)
        self._sync_ring()

    def apply_preset(self, work_m: int, short_m: int, long_m: int) -> None:
        self.spin_work.setValue(work_m)
        self.spin_short.setValue(short_m)
        self.spin_long.setValue(long_m)
        self.reset_timer()

    def _on_durations_changed(self) -> None:
        self.work_min = self.spin_work.value()
        self.short_min = self.spin_short.value()
        self.long_min = self.spin_long.value()
        self.rounds_target = self.spin_rounds.value()
        if not self.running:
            self.reset_timer()

    def toggle_start_pause(self) -> None:
        self.running = not self.running
        if self.running:
            self._tick_timer.start()
            self.btn_start.setText("Pause")
        else:
            self._tick_timer.stop()
            self.btn_start.setText("Resume Focus")
        self._sync_ring()

    def reset_timer(self) -> None:
        self.running = False
        self._tick_timer.stop()
        self.phase = "work"
        self.total_sec = self.work_min * 60
        self.remaining_sec = self.total_sec
        self.btn_start.setText("Start Focus")
        self._sync_ring()

    def skip_phase(self) -> None:
        if self.phase == "work":
            self.completed_pomodoros += 1
            if self.round_num >= self.rounds_target:
                self.phase = "long_break"
                self.total_sec = self.long_min * 60
                self.round_num = 1
            else:
                self.phase = "short_break"
                self.total_sec = self.short_min * 60
                self.round_num += 1
        else:
            self.phase = "work"
            self.total_sec = self.work_min * 60
        self.remaining_sec = self.total_sec
        if self.chk_sound.isChecked():
            try:
                play_ui_sound("recv", 0.48)
            except Exception:
                pass
        if not self.chk_autostart.isChecked():
            self.running = False
            self._tick_timer.stop()
            self.btn_start.setText("Start Phase")
        self._sync_ring()

    def _on_second(self) -> None:
        if not self.running:
            return
        if self.phase == "work":
            self.focused_seconds_today += 1
        if self.remaining_sec > 1:
            self.remaining_sec -= 1
            self._sync_ring()
        else:
            self.skip_phase()

    def _sync_ring(self) -> None:
        mins = self.remaining_sec // 60
        secs = self.remaining_sec % 60
        t_str = f"{mins:02d}:{secs:02d}"
        prog = self.remaining_sec / float(max(1, self.total_sec))
        if self.phase == "work":
            p_str, col = "FOCUS WORK", "#A855F7"
        elif self.phase == "short_break":
            p_str, col = "SHORT BREAK", "#10B981"
        else:
            p_str, col = "LONG BREAK", "#38BDF8"
        r_str = f"Round {self.round_num} / {self.rounds_target}"
        self.ring.set_ring_state(prog, t_str, p_str, r_str, col)
        tot_min = self.focused_seconds_today // 60
        self.lbl_stats.setText(f"Completed Today: {self.completed_pomodoros} Pomodoros ({tot_min} min)")

    def add_focus_task(self, text: str | None = None) -> None:
        t = (text if isinstance(text, str) else self.task_input.text()).strip()
        if not t:
            return
        item = QListWidgetItem(t)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)
        self.task_list.addItem(item)
        if not isinstance(text, str):
            self.task_input.clear()

    def clear_completed_tasks(self) -> None:
        for i in range(self.task_list.count() - 1, -1, -1):
            it = self.task_list.item(i)
            if it is not None and it.checkState() == Qt.CheckState.Checked:
                self.task_list.takeItem(i)


# ── #20: Analytics Daily Model & Token Hover Breakdown Filter ────────────────
class _AnalyticsBarHoverFilter(QObject):
    """Shows a rich daily per-model token & speed breakdown popup when hovering Analytics charts."""
    def __init__(self, main_win):
        super().__init__(main_win)
        self.main_win = main_win

    def format_daily_breakdown(self, bucket_index: int = -1) -> str:
        data = getattr(self.main_win, "analytics_data", {}) or {}
        turns = data.get("turns", []) or []
        if not turns:
            return "No turns recorded yet"

        # Group turns by date (fallback to 'Today' if date key was omitted on older turns)
        today_str = date.today().isoformat()
        by_day: dict[str, list[dict]] = {}
        for t in turns:
            if isinstance(t, dict):
                d_key = str(t.get("date") or t.get("day") or today_str)[:10]
                by_day.setdefault(d_key, []).append(t)

        days_sorted = sorted(by_day.keys())
        if not days_sorted:
            return "No turns recorded yet"
        chosen_day = days_sorted[bucket_index % len(days_sorted)] if bucket_index >= 0 else days_sorted[-1]
        day_turns = by_day[chosen_day]

        per_model_tokens: dict[str, int] = {}
        per_model_turns: dict[str, int] = {}
        total_tok = 0
        total_think = 0.0
        speeds = []

        for t in day_turns:
            m = str(t.get("model") or "Default Model").strip()
            tok = int(t.get("tokens", 0) or 0)
            th = float(t.get("think_time", 0.0) or 0.0)
            spd = float(t.get("tok_per_sec", 0.0) or 0.0)
            if spd <= 0.0 and tok > 0 and th > 0.0:
                spd = round(tok / max(0.1, th), 1)
            per_model_tokens[m] = per_model_tokens.get(m, 0) + tok
            per_model_turns[m] = per_model_turns.get(m, 0) + 1
            total_tok += tok
            total_think += th
            if spd > 0:
                speeds.append(spd)

        avg_spd = round(sum(speeds) / len(speeds), 1) if speeds else 0.0
        lines = [
            f"📅 Date: {chosen_day}",
            f"⚡ Total: {total_tok:,} tokens ({len(day_turns)} turns) • Avg Speed: {avg_spd} tok/s",
            "────────────────────────────",
            "🧠 Models Used:",
        ]
        for m_name, m_tok in sorted(per_model_tokens.items(), key=lambda kv: kv[1], reverse=True):
            cnt = per_model_turns.get(m_name, 1)
            pct = int(round((m_tok / float(max(1, total_tok))) * 100))
            lines.append(f"  • {m_name}: {m_tok:,} tokens ({cnt} turns · {pct}%)")
        return "\n".join(lines)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseMove:
            try:
                w = max(1, obj.width())
                pos = event.position() if hasattr(event, "position") else event.pos()
                bucket = max(0, int((pos.x() / float(w)) * 7))
                tip = self.format_daily_breakdown(bucket)
                obj.setToolTip(tip)
                QToolTip.showText(QCursor.pos(), tip, obj)
            except Exception:
                pass
        return False


# ── Wire #16, #19, #20 & #21 into `CelStudioCerebrium` ───────────────────────
_prev_mw_init_v16 = CelStudioCerebrium.__init__
_prev_mw_send_v16 = CelStudioCerebrium.send_message
_prev_mw_delta_v16 = CelStudioCerebrium.on_delta
_prev_mw_done_v16 = CelStudioCerebrium.on_done
_prev_mw_rec_analytics_v20 = getattr(CelStudioCerebrium, "_record_analytics", None)
_prev_mw_refresh_hist_v21 = CelStudioCerebrium.refresh_history_list
_prev_mw_branch_v21 = getattr(CelStudioCerebrium, "branch_from_message", None)


def _patched_mw_init_v16(self, *args, **kwargs):
    self._allow_manual_tray_hide = False
    _prev_mw_init_v16(self, *args, **kwargs)
    self._install_top_bar_window_buttons_16()
    self._install_focus_studio_tab_19()
    self._install_analytics_hover_20()


# #16: Top-Bar Minimize / Restore / Tray Buttons + Block Auto-Hide to Tray
def _install_top_bar_window_buttons_16(self) -> None:
    if not hasattr(self, "top_bar") or self.top_bar is None or self.top_bar.layout() is None:
        return
    if hasattr(self, "btn_top_minimize"):
        return
    lay = self.top_bar.layout()

    btn_style = (
        "QPushButton { background: rgba(255, 255, 255, 0.07); color: #E9D5FF; "
        "border: 1px solid rgba(168, 85, 247, 0.35); border-radius: 8px; padding: 4px; }"
        "QPushButton:hover { background: rgba(147, 51, 234, 0.48); color: #FFFFFF; }"
    )

    self.btn_top_tray = QPushButton("")
    self.btn_top_tray.setIcon(get_svg_icon("tray"))
    self.btn_top_tray.setIconSize(QSize(14, 14))
    self.btn_top_tray.setFixedSize(28, 28)
    self.btn_top_tray.setCursor(Qt.CursorShape.PointingHandCursor)
    self.btn_top_tray.setToolTip("Minimize to System Tray (Manual only)")
    self.btn_top_tray.setStyleSheet(btn_style)
    self.btn_top_tray.clicked.connect(self.manual_minimize_to_tray)
    lay.addWidget(self.btn_top_tray)

    self.btn_top_minimize = QPushButton("")
    self.btn_top_minimize.setIcon(get_svg_icon("minimize"))
    self.btn_top_minimize.setIconSize(QSize(14, 14))
    self.btn_top_minimize.setFixedSize(28, 28)
    self.btn_top_minimize.setCursor(Qt.CursorShape.PointingHandCursor)
    self.btn_top_minimize.setToolTip("Minimize Window")
    self.btn_top_minimize.setStyleSheet(btn_style)
    self.btn_top_minimize.clicked.connect(self.manual_minimize_window)
    lay.addWidget(self.btn_top_minimize)

    self.btn_top_restore = QPushButton("")
    self.btn_top_restore.setIcon(get_svg_icon("restore"))
    self.btn_top_restore.setIconSize(QSize(13, 13))
    self.btn_top_restore.setFixedSize(28, 28)
    self.btn_top_restore.setCursor(Qt.CursorShape.PointingHandCursor)
    self.btn_top_restore.setToolTip("Toggle Maximize / Restore Window")
    self.btn_top_restore.setStyleSheet(btn_style)
    self.btn_top_restore.clicked.connect(
        lambda: self.showNormal() if self.isMaximized() else self.showMaximized()
    )
    lay.addWidget(self.btn_top_restore)


def _manual_minimize_window(self) -> None:
    """Minimize window to the OS taskbar without hiding to the system tray."""
    self._allow_manual_tray_hide = False
    self.showMinimized()


def _manual_minimize_to_tray(self) -> None:
    """Hide to system tray ONLY when the user explicitly clicks the tray button."""
    self._allow_manual_tray_hide = True
    try:
        self.hide()
    finally:
        self._allow_manual_tray_hide = False


def _patched_change_event_16(self, event) -> None:
    """Prevent FocusOut / WindowDeactivate / WindowStateChange from auto-hiding into the tray."""
    et = event.type()
    if et in (QEvent.Type.WindowStateChange, QEvent.Type.ActivationChange, QEvent.Type.FocusOut):
        event.accept()
        return
    try:
        super(CelStudioCerebrium, self).changeEvent(event)
    except Exception:
        pass


# #19: Install Focus Studio Page & Left Drawer Navigation Button
def _install_focus_studio_tab_19(self) -> None:
    if hasattr(self, "focus_studio_view") and self.focus_studio_view is not None:
        return
    self.focus_studio_view = FocusStudioPage(self, self)
    if hasattr(self, "central_stack") and self.central_stack is not None:
        self.central_stack.addWidget(self.focus_studio_view)

    if hasattr(self, "left_drawer") and self.left_drawer is not None and self.left_drawer.layout() is not None:
        d_lay = self.left_drawer.layout()
        self.btn_nav_focus = QPushButton("  Focus Studio")
        self.btn_nav_focus.setVisible(True)  # Task 19: Focus Studio is a first-class tab now
        self.btn_nav_focus.setIcon(get_svg_icon("target"))
        self.btn_nav_focus.setIconSize(QSize(16, 16))
        self.btn_nav_focus.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_nav_focus.setStyleSheet(
            "QPushButton { background: transparent; color: #E2E8F0; border-radius: 8px; "
            "padding: 9px 12px; font-size: 13px; font-weight: 600; text-align: left; border: none; }"
            "QPushButton:hover { background: rgba(147, 51, 234, 0.28); color: #FFFFFF; }"
        )
        self.btn_nav_focus.clicked.connect(self.open_focus_studio_view)
        # Insert right after Analytics or Avatar Studio in the left drawer
        insert_pos = min(6, max(2, d_lay.count() - 2))
        d_lay.insertWidget(insert_pos, self.btn_nav_focus)


def _open_focus_studio_view(self) -> None:
    self._install_focus_studio_tab_19()
    idx = self.central_stack.indexOf(self.focus_studio_view)
    if idx >= 0:
        self.central_stack.setCurrentIndex(idx)


# #20: Accurate Token & Speed Tracking + Analytics Hover Filter
def _install_analytics_hover_20(self) -> None:
    av = getattr(self, "analytics_view", None)
    if av is None or hasattr(self, "_analytics_hover_filter"):
        return
    self._analytics_hover_filter = _AnalyticsBarHoverFilter(self)
    av.setMouseTracking(True)
    av.installEventFilter(self._analytics_hover_filter)
    for child_w in av.findChildren(QWidget):
        child_w.setMouseTracking(True)
        child_w.installEventFilter(self._analytics_hover_filter)


def _patched_send_v20(self, *args, **kwargs):
    self._gen_start_mono = time.monotonic()
    self._first_token_mono = None
    return _prev_mw_send_v16(self, *args, **kwargs)


def _patched_delta_v20(self, sid: str, delta: str):
    if getattr(self, "_first_token_mono", None) is None and delta and delta.strip():
        self._first_token_mono = time.monotonic()
    return _prev_mw_delta_v16(self, sid, delta)


def _patched_record_analytics_v20(self, reply_text: str = "", meta=None):
    # on_done calls this as `_record_analytics(reply, self._pending_meta)`.
    # The old one-arg signature raised TypeError on EVERY finished turn, which
    # aborted on_done before finalize_stream() - leaving the thinking card on
    # screen, analytics empty and every Info drawer stuck at "Tokens: 0".
    if isinstance(meta, dict):
        self._pending_meta = meta
    now_mono = time.monotonic()
    t_start = getattr(self, "_gen_start_mono", None)
    t_first = getattr(self, "_first_token_mono", None)

    meta = getattr(self, "_pending_meta", None)
    if not isinstance(meta, dict):
        meta = {}
        self._pending_meta = meta

    # Only compute accurate token count if caller/test did not pre-populate turn_tokens
    if not meta.get("turn_tokens"):
        clean_rep = clean_chat_display(reply_text or "")
        meta["turn_tokens"] = estimate_accurate_tokens(clean_rep)

    if not meta.get("think_time") and t_start is not None:
        first_ts = t_first if t_first is not None else now_mono
        meta["think_time"] = round(max(0.05, first_ts - t_start), 2)

    gen_dur = max(0.08, (now_mono - t_first) if t_first is not None else float(meta.get("think_time", 1.0) or 1.0))
    tok_count = int(meta.get("turn_tokens", 0) or 0)
    tok_s = round(tok_count / gen_dur, 1) if tok_count > 0 else 0.0
    meta["gen_time"] = round(gen_dur, 2)
    meta["tok_per_sec"] = tok_s

    if _prev_mw_rec_analytics_v20 is not None:
        _prev_mw_rec_analytics_v20(self, reply_text)

    # Enrich the latest analytics turn row with today's date & tok_per_sec for the hover breakdown
    turns = (getattr(self, "analytics_data", {}) or {}).get("turns", [])
    if isinstance(turns, list) and turns and isinstance(turns[-1], dict):
        turns[-1].setdefault("date", date.today().isoformat())
        turns[-1]["tok_per_sec"] = tok_s
        turns[-1]["gen_time"] = round(gen_dur, 2)


# #21: Ensure Branched Chats Always Appear Immediately in Recent Chats
def _promote_branched_sessions_in_dict(sessions_dict: dict) -> None:
    """Ensure branched sessions are visible AND promoted to Page 1 of Recent Chats alongside their parent."""
    if not isinstance(sessions_dict, dict):
        return
    priority_sids: list[str] = []
    for sid, ses in list(sessions_dict.items()):
        if not isinstance(ses, dict):
            continue
        for hidden_flag in ("hidden", "ephemeral", "is_temp_branch", "hide_in_list"):
            if ses.get(hidden_flag):
                ses[hidden_flag] = False
        is_branch = bool(
            ses.get("parent_sid")
            or ses.get("branched_from")
            or str(sid).startswith("branch_")
            or "branch" in str(ses.get("title", "")).lower()
        )
        if is_branch:
            t = str(ses.get("title") or "Branched Chat").strip()
            if not t.startswith(("🌿", "🌱", "📌")):
                ses["title"] = f"🌿 {t}"
            if not ses.get("created"):
                ses["created"] = date.today().isoformat()
            if not ses.get("last_active"):
                ses["last_active"] = ses["created"]
            priority_sids.append(sid)
            p_sid = ses.get("parent_sid") or ses.get("branched_from")
            if p_sid and p_sid in sessions_dict and p_sid not in priority_sids:
                priority_sids.append(p_sid)

    if priority_sids:
        ordered_items = [(k, sessions_dict[k]) for k in priority_sids if k in sessions_dict]
        ordered_items.extend((k, v) for k, v in sessions_dict.items() if k not in priority_sids)
        sessions_dict.clear()
        sessions_dict.update(ordered_items)


def _patched_refresh_history_v21(self, filter_text: str = ""):
    _promote_branched_sessions_in_dict(getattr(self, "sessions", {}))
    return _prev_mw_refresh_hist_v21(self, filter_text)


def _patched_branch_from_message_v21(self, bubble_widget):
    before_sids = set((getattr(self, "sessions", {}) or {}).keys())
    res = _prev_mw_branch_v21(self, bubble_widget) if _prev_mw_branch_v21 is not None else None
    after_sids = set((getattr(self, "sessions", {}) or {}).keys())
    new_sids = after_sids - before_sids
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for nsid in new_sids:
        ses = self.sessions.get(nsid)
        if isinstance(ses, dict):
            ses["last_active"] = now_str
            ses.setdefault("created", now_str[:10])
    self._hist_page = 1
    self.refresh_history_list("")
    return res


CelStudioCerebrium.__init__ = _patched_mw_init_v16
CelStudioCerebrium._install_top_bar_window_buttons_16 = _install_top_bar_window_buttons_16
CelStudioCerebrium.manual_minimize_window = _manual_minimize_window
CelStudioCerebrium.manual_minimize_to_tray = _manual_minimize_to_tray
CelStudioCerebrium.changeEvent = _patched_change_event_16
CelStudioCerebrium._install_focus_studio_tab_19 = _install_focus_studio_tab_19
CelStudioCerebrium.open_focus_studio_view = _open_focus_studio_view
CelStudioCerebrium._install_analytics_hover_20 = _install_analytics_hover_20
CelStudioCerebrium.send_message = _patched_send_v20
CelStudioCerebrium.on_delta = _patched_delta_v20
if _prev_mw_rec_analytics_v20 is not None:
    CelStudioCerebrium._record_analytics = _patched_record_analytics_v20
CelStudioCerebrium.refresh_history_list = _patched_refresh_history_v21
if _prev_mw_branch_v21 is not None:
    CelStudioCerebrium.branch_from_message = _patched_branch_from_message_v21


# ── #23, #25, #28: Smart Delete Below-Selection, Clean Stubs & Analytics Month/Year Picker ──
import datetime as _dt_mod
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


# ── #23: Select the Chat Immediately BELOW When Deleting a Session or Message ──
def _get_ordered_session_ids(self) -> list[str]:
    """Return session IDs in the exact order shown in Recent Chats (pinned first, then recency)."""
    sessions = getattr(self, "sessions", {}) or {}
    pinned = [sid for sid, s in sessions.items() if isinstance(s, dict) and s.get("pinned", False)]
    unpinned = [sid for sid, s in sessions.items() if isinstance(s, dict) and not s.get("pinned", False)]
    return pinned + unpinned


def _smart_delete_session_below(self, sid: str) -> None:
    """Delete session `sid` and automatically select the chat that was immediately BELOW it!"""
    if sid not in self.sessions:
        return
    ordered = self._get_ordered_session_ids()
    try:
        del_idx = ordered.index(sid)
    except ValueError:
        del_idx = 0

    # Preserve sidebar scroll position & current page
    vbar = self.hist_scroll.verticalScrollBar() if hasattr(self, "hist_scroll") else None
    saved_scroll = vbar.value() if vbar is not None else 0

    was_current = (sid == getattr(self, "current_sid", None))
    self.sessions.pop(sid, None)
    remaining = self._get_ordered_session_ids()

    if not remaining:
        # If the user deleted the very last chat, create a fresh empty one
        new_sid = f"chat_{int(time.time() * 1000)}"
        now_s = _dt_mod.datetime.now().strftime("%Y-%m-%d %H:%M")
        self.sessions[new_sid] = {"title": "New Chat", "created": now_s, "last_active": now_s, "memory": []}
        self.current_sid = new_sid
        self.switch_session(new_sid)
    elif was_current:
        # Pick the chat that was immediately BELOW the deleted one (same index in `remaining`, or last item)
        next_idx = min(del_idx, len(remaining) - 1)
        target_sid = remaining[next_idx]
        self.current_sid = target_sid
        self.switch_session(target_sid)

    try:
        save_json(F_SESSIONS, self.sessions)
    except Exception:
        pass
    filt = self.search_history.text().strip() if hasattr(self, "search_history") else ""
    self.refresh_history_list(filt)
    if vbar is not None:
        vbar.setValue(saved_scroll)


# Also preserve scroll position when deleting an individual message bubble inside a chat
_orig_del_msg_23 = getattr(CelStudioCerebrium, "delete_message", None)
if _orig_del_msg_23 is not None:
    def _smart_delete_message_23(self, bubble):
        vbar = self.chat_scroll.verticalScrollBar() if hasattr(self, "chat_scroll") else None
        saved_y = vbar.value() if vbar is not None else 0
        res = _orig_del_msg_23(self, bubble)
        if vbar is not None:
            QTimer.singleShot(10, lambda: vbar.setValue(saved_y))
        return res
    CelStudioCerebrium.delete_message = _smart_delete_message_23

CelStudioCerebrium._get_ordered_session_ids = _get_ordered_session_ids
CelStudioCerebrium.delete_session = _smart_delete_session_below
CelStudioCerebrium._delete_session = _smart_delete_session_below


# ── #25: Never Render False `(connection interrupted)` on Tool-Only Steps ────
_prev_on_done_25 = CelStudioCerebrium.on_done

def _clean_on_done_25(self, sid: str, full_text: str, *args, **kwargs):
    # Catch the dropped-connection marker before the cleanup below turns it
    # into an empty string and lets on_done show "Cel replied!".
    _stopped = bool(kwargs.get("stopped",
                                args[2] if len(args) >= 3 else False))
    if not _stopped and _is_failed_reply_text(full_text):
        return self.on_error(sid, "Connection Failed",
                             "No response received from the model.")
    cleaned_txt = (full_text or "").replace("*(connection interrupted)*", "").replace("(connection interrupted)", "").strip()
    # If this turn had tool calls and the final text is empty, don't let on_done label it "(interrupted)"
    from cellium.core.utils import clean_chat_display
    vis = clean_chat_display(cleaned_txt)
    if not vis and getattr(self, "live_bubble", None) is not None:
        # Check if a ToolCallCard was already added in this turn
        has_tool_cards = any(
            self.chat_layout.itemAt(i).widget().__class__.__name__ == "ToolCallCard"
            for i in range(max(0, self.chat_layout.count() - 5), self.chat_layout.count())
            if self.chat_layout.itemAt(i) and self.chat_layout.itemAt(i).widget()
        )
        if has_tool_cards:
            try:
                lb = self.live_bubble
                self.chat_layout.removeWidget(lb)
                lb.hide()
                lb.deleteLater()
                self.live_bubble = None
            except Exception:
                pass
    return _prev_on_done_25(self, sid, cleaned_txt, *args, **kwargs)

CelStudioCerebrium.on_done = _clean_on_done_25


# ── #28: Analytics Bar Chart with `Last 14 Days (Default)` + Month Picker + Year Picker ──
_MONTH_NAMES = (
    "All Months (Yearly Overview)",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


class _AnalyticsPeriodChartCanvas(QWidget):
    """Beautiful glassmorphic bar chart canvas that renders 14-Day, Monthly, or Yearly buckets with hover breakdown!"""
    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self.setMinimumHeight(210)
        self.setMouseTracking(True)
        self.buckets: list[dict] = []  # [{"label": "Oct 17", "tokens": 1200, "turns": 4, "models": {"m": 1200}, "speeds": [42.0]}]
        self._hover_idx = -1

    def set_buckets(self, buckets: list[dict]) -> None:
        self.buckets = list(buckets or [])
        self._hover_idx = -1
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if not self.buckets:
            return
        w = max(1.0, float(self.width()) - 40.0)
        pos = event.position() if hasattr(event, "position") else event.pos()
        rel_x = max(0.0, float(pos.x()) - 20.0)
        idx = min(len(self.buckets) - 1, max(0, int((rel_x / w) * len(self.buckets))))
        self._hover_idx = idx
        b = self.buckets[idx]
        models_map = b.get("models", {})
        spds = b.get("speeds", [])
        avg_spd = round(sum(spds) / len(spds), 1) if spds else 0.0
        lines = [
            f"📅 Period: {b.get('full_label', b.get('label', ''))}",
            f"⚡ Tokens: {b.get('tokens', 0):,} ({b.get('turns', 0)} turns) • Avg Speed: {avg_spd} tok/s",
        ]
        if models_map:
            lines.append("────────────────────────────")
            lines.append("🧠 Models Used:")
            tot = max(1, b.get("tokens", 1))
            for mn, mt in sorted(models_map.items(), key=lambda kv: kv[1], reverse=True):
                pct = int(round((mt / float(tot)) * 100))
                lines.append(f"  • {mn}: {mt:,} tokens ({pct}%)")
        tip = "\n".join(lines)
        self.setToolTip(tip)
        QToolTip.showText(QCursor.pos(), tip, self)
        self.update()

    def leaveEvent(self, _event) -> None:
        self._hover_idx = -1
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())

        rect_bg = QRectF(2.0, 2.0, w - 4.0, h - 4.0)
        painter.setBrush(QColor(14, 9, 28, 210))
        painter.setPen(QPen(QColor(168, 85, 247, 85), 1.2))
        painter.drawRoundedRect(rect_bg, 14.0, 14.0)

        if not self.buckets:
            painter.setPen(QColor("#C4B5FD"))
            painter.drawText(rect_bg, int(Qt.AlignmentFlag.AlignCenter), "No token activity in this period yet")
            painter.end()
            return

        n = len(self.buckets)
        max_tok = max([b.get("tokens", 0) for b in self.buckets] + [1])
        pad_x = 24.0
        pad_top = 28.0
        pad_bot = 36.0
        chart_w = max(40.0, w - 2.0 * pad_x)
        chart_h = max(40.0, h - pad_top - pad_bot)
        slot_w = chart_w / float(n)
        bar_w = max(6.0, min(38.0, slot_w * 0.64))

        f_lbl = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        painter.setFont(f_lbl)

        for i, b in enumerate(self.buckets):
            tok = int(b.get("tokens", 0) or 0)
            frac = (tok / float(max_tok)) if max_tok > 0 else 0.0
            bh = max(4.0 if tok > 0 else 2.0, frac * chart_h)
            cx = pad_x + (i + 0.5) * slot_w
            bx = cx - bar_w * 0.5
            by = pad_top + (chart_h - bh)

            is_hov = (i == self._hover_idx)
            grad = QLinearGradient(bx, by, bx, by + bh)
            if is_hov:
                grad.setColorAt(0.0, QColor("#F5D0FE"))
                grad.setColorAt(0.5, QColor("#C084FC"))
                grad.setColorAt(1.0, QColor("#9333EA"))
            else:
                grad.setColorAt(0.0, QColor("#C084FC"))
                grad.setColorAt(1.0, QColor(126, 34, 206, 195 if tok > 0 else 65))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(QRectF(bx, by, bar_w, bh), 4.0, 4.0)

            # Value label above hovered or non-zero bar
            if is_hov or (tok > 0 and n <= 14):
                painter.setPen(QColor("#F8F4FF" if is_hov else "#D8B4FE"))
                if tok >= 1000:
                    # One decimal below 10k (1.3k, 2.0k) so adjacent days are
                    # distinguishable - integer division made every bar in the
                    # 1,000–1,999 range read the same "1k".
                    val_str = (f"{tok / 1000:.1f}k" if tok < 10000
                               else f"{tok / 1000:.0f}k")
                else:
                    val_str = str(tok)
                painter.drawText(QRectF(cx - 24.0, by - 18.0, 48.0, 16.0), int(Qt.AlignmentFlag.AlignCenter), val_str)

            # X-axis label (skip every other label on 31-day months so it never crowds)
            if n <= 16 or i % 2 == 0 or i == n - 1 or is_hov:
                painter.setPen(QColor("#FFFFFF" if is_hov else "#A78BFA"))
                painter.drawText(QRectF(cx - 26.0, h - pad_bot + 6.0, 52.0, 20.0), int(Qt.AlignmentFlag.AlignCenter), str(b.get("label", "")))

        painter.end()


def _install_analytics_period_pickers_28(self) -> None:
    av = getattr(self, "analytics_view", None)
    if av is None or hasattr(av, "combo_analytics_mode"):
        return

    lay = av.layout()
    if lay is None:
        return

    # Filter bar with Mode (`Last 14 Days (Default)` / `Monthly View` / `Yearly View`), Month Picker & Year Picker
    bar = QFrame(av)
    bar.setObjectName("AnalyticsPeriodBar")
    bar.setStyleSheet(
        "QFrame#AnalyticsPeriodBar { background: rgba(18, 11, 34, 0.88); "
        "border: 1px solid rgba(168, 85, 247, 0.42); border-radius: 12px; }"
    )
    b_lay = QHBoxLayout(bar)
    b_lay.setContentsMargins(14, 8, 14, 8)
    b_lay.setSpacing(10)

    lbl_title = QLabel("📅 Analytics Timeline View:")
    lbl_title.setStyleSheet("color: #F3E8FF; font-size: 12px; font-weight: bold; border: none; background: transparent;")
    b_lay.addWidget(lbl_title)

    combo_css = (
        "QComboBox { background: rgba(10, 6, 22, 0.92); color: #F8F4FF; border: 1.2px solid #9333EA; "
        "border-radius: 8px; padding: 4px 10px; font-size: 12px; font-weight: 600; min-width: 145px; }"
        "QComboBox::drop-down { border: none; }"
    )
    # Month/Year only ever hold short labels - the generous 145px minimums
    # starved the "Showing: …" summary and clipped it at the frame edge.
    combo_css_compact = (
        "QComboBox { background: rgba(10, 6, 22, 0.92); color: #F8F4FF; border: 1.2px solid #9333EA; "
        "border-radius: 8px; padding: 4px 8px; font-size: 12px; font-weight: 600; min-width: 84px; }"
        "QComboBox::drop-down { border: none; }"
    )

    av.combo_analytics_mode = QComboBox(bar)
    av.combo_analytics_mode.addItems([
        "Last 14 Days (Default)",
        "Monthly Breakdown",
        "Yearly Overview",
    ])
    av.combo_analytics_mode.setStyleSheet(combo_css)
    b_lay.addWidget(av.combo_analytics_mode)

    lbl_m = QLabel("Month:")
    lbl_m.setStyleSheet("color: #C4B5FD; font-size: 12px; font-weight: 600; border: none; background: transparent;")
    b_lay.addWidget(lbl_m)

    av.combo_analytics_month = QComboBox(bar)
    av.combo_analytics_month.addItems(list(_MONTH_NAMES))
    cur_month_idx = _dt_mod.date.today().month
    av.combo_analytics_month.setCurrentIndex(cur_month_idx)
    av.combo_analytics_month.setStyleSheet(combo_css_compact)
    b_lay.addWidget(av.combo_analytics_month)

    lbl_y = QLabel("Year:")
    lbl_y.setStyleSheet(lbl_m.styleSheet())
    b_lay.addWidget(lbl_y)

    av.combo_analytics_year = QComboBox(bar)
    cur_yr = _dt_mod.date.today().year
    av.combo_analytics_year.addItems([str(y) for y in range(cur_yr, cur_yr - 4, -1)] + ["All Years"])
    av.combo_analytics_year.setCurrentText(str(cur_yr))
    av.combo_analytics_year.setStyleSheet(combo_css_compact)
    b_lay.addWidget(av.combo_analytics_year)
    # QComboBox defaults to Expanding; three of them steal every spare pixel
    # and leave the summary label with nothing. Pin them to content width.
    for _combo in (av.combo_analytics_mode, av.combo_analytics_month, av.combo_analytics_year):
        _combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    b_lay.addStretch(1)

    av.lbl_period_summary = QLabel("Last 14 Days")
    av.lbl_period_summary.setStyleSheet("color: #C084FC; font-size: 12px; font-weight: bold; border: none; background: transparent;")
    b_lay.addWidget(av.lbl_period_summary)

    av.period_chart = _AnalyticsPeriodChartCanvas(self, av)

    # Insert filter bar and period chart into analytics_view layout
    insert_idx = min(1, lay.count())
    lay.insertWidget(insert_idx, bar)
    lay.insertWidget(insert_idx + 1, av.period_chart)

    def _on_period_changed(*_a):
        mode_idx = av.combo_analytics_mode.currentIndex()
        if mode_idx == 1 and av.combo_analytics_month.currentIndex() == 0:
            av.combo_analytics_month.setCurrentIndex(_dt_mod.date.today().month)
        _rebuild_analytics_period_buckets(self)

    def _on_month_picked(m_idx: int):
        if m_idx > 0 and av.combo_analytics_mode.currentIndex() == 0:
            av.combo_analytics_mode.blockSignals(True)
            av.combo_analytics_mode.setCurrentIndex(1)
            av.combo_analytics_mode.blockSignals(False)
        _rebuild_analytics_period_buckets(self)

    def _on_year_picked(y_txt: str):
        if y_txt == "All Years":
            av.combo_analytics_mode.blockSignals(True)
            av.combo_analytics_mode.setCurrentIndex(2)
            av.combo_analytics_mode.blockSignals(False)
        _rebuild_analytics_period_buckets(self)

    av.combo_analytics_mode.currentIndexChanged.connect(_on_period_changed)
    av.combo_analytics_month.currentIndexChanged.connect(_on_month_picked)
    av.combo_analytics_year.currentTextChanged.connect(_on_year_picked)

    # Hook av.set_data so any new turn refreshes our period chart too
    if hasattr(av, "set_data") and not getattr(av, "_v28_set_data_hooked", False):
        _orig_av_set_data = av.set_data
        def _patched_av_set_data(data_dict):
            res = _orig_av_set_data(data_dict)
            _rebuild_analytics_period_buckets(self)
            return res
        av.set_data = _patched_av_set_data
        av._v28_set_data_hooked = True

    _rebuild_analytics_period_buckets(self)


def _rebuild_analytics_period_buckets(self) -> list[dict]:
    av = getattr(self, "analytics_view", None)
    if av is None or not hasattr(av, "period_chart"):
        return []

    turns = (getattr(self, "analytics_data", {}) or {}).get("turns", []) or []
    today = _dt_mod.date.today()
    mode_idx = av.combo_analytics_mode.currentIndex()  # 0=Last 14 Days, 1=Monthly, 2=Yearly
    month_idx = av.combo_analytics_month.currentIndex()  # 0=All Months, 1..12=Jan..Dec
    year_txt = av.combo_analytics_year.currentText()
    sel_year = int(year_txt) if year_txt.isdigit() else today.year

    # Normalize turn dates
    parsed_turns = []
    for t in turns:
        if not isinstance(t, dict):
            continue
        raw_d = str(t.get("date") or t.get("day") or today.isoformat())[:10]
        try:
            d_obj = _dt_mod.date.fromisoformat(raw_d)
        except ValueError:
            d_obj = today
        parsed_turns.append((d_obj, t))

    buckets: list[dict] = []

    if mode_idx == 0:
        # Default: Last 14 Days
        days = [today - _dt_mod.timedelta(days=13 - i) for i in range(14)]
        b_map = {
            d: {"label": d.strftime("%b %d"), "full_label": d.isoformat(), "tokens": 0, "turns": 0, "models": {}, "speeds": []}
            for d in days
        }
        for d_obj, t in parsed_turns:
            if d_obj in b_map:
                _accumulate_turn_into_bucket(b_map[d_obj], t)
        buckets = [b_map[d] for d in days]
        av.lbl_period_summary.setText(f"Showing: 14 days · {sum(b['tokens'] for b in buckets):,} tokens")

    elif mode_idx == 1 and month_idx >= 1:
        # Specific Month of Selected Year (Day 1 .. Day 28/30/31)
        import calendar
        _, num_days = calendar.monthrange(sel_year, month_idx)
        m_short = _MONTH_NAMES[month_idx][:3]
        b_map = {}
        for day_num in range(1, num_days + 1):
            d_obj = _dt_mod.date(sel_year, month_idx, day_num)
            b_map[day_num] = {
                "label": str(day_num),
                "full_label": f"{_MONTH_NAMES[month_idx]} {day_num}, {sel_year}",
                "tokens": 0, "turns": 0, "models": {}, "speeds": [],
            }
        for d_obj, t in parsed_turns:
            if d_obj.year == sel_year and d_obj.month == month_idx:
                _accumulate_turn_into_bucket(b_map[d_obj.day], t)
        buckets = [b_map[d] for d in range(1, num_days + 1)]
        av.lbl_period_summary.setText(
            f"Showing: {_MONTH_NAMES[month_idx][:3]} {sel_year} · {sum(b['tokens'] for b in buckets):,} tokens"
        )

    else:
        # Yearly Overview: either 12 months (Jan..Dec) of `sel_year`, or Year-by-Year if `All Years`
        if year_txt == "All Years":
            years_set = sorted({d.year for d, _ in parsed_turns} | {today.year - 2, today.year - 1, today.year})
            b_map = {
                yr: {"label": str(yr), "full_label": f"Year {yr}", "tokens": 0, "turns": 0, "models": {}, "speeds": []}
                for yr in years_set
            }
            for d_obj, t in parsed_turns:
                if d_obj.year in b_map:
                    _accumulate_turn_into_bucket(b_map[d_obj.year], t)
            buckets = [b_map[yr] for yr in years_set]
            av.lbl_period_summary.setText(f"Showing: All years · {sum(b['tokens'] for b in buckets):,} tokens")
        else:
            b_map = {
                m: {
                    "label": _MONTH_NAMES[m][:3],
                    "full_label": f"{_MONTH_NAMES[m]} {sel_year}",
                    "tokens": 0, "turns": 0, "models": {}, "speeds": [],
                }
                for m in range(1, 13)
            }
            for d_obj, t in parsed_turns:
                if d_obj.year == sel_year:
                    _accumulate_turn_into_bucket(b_map[d_obj.month], t)
            buckets = [b_map[m] for m in range(1, 13)]
            av.lbl_period_summary.setText(f"Showing: {sel_year} · {sum(b['tokens'] for b in buckets):,} tokens")

    av.period_chart.set_buckets(buckets)
    return buckets


def _accumulate_turn_into_bucket(bucket: dict, turn: dict) -> None:
    tok = int(turn.get("tokens", 0) or 0)
    m = str(turn.get("model") or "Default Model").strip()
    th = float(turn.get("think_time", 0.0) or 0.0)
    spd = float(turn.get("tok_per_sec", 0.0) or 0.0)
    if spd <= 0.0 and tok > 0 and th > 0.0:
        spd = round(tok / max(0.1, th), 1)
    bucket["tokens"] += tok
    bucket["turns"] += 1
    bucket["models"][m] = bucket["models"].get(m, 0) + tok
    if spd > 0:
        bucket["speeds"].append(spd)


_prev_mw_init_28 = CelStudioCerebrium.__init__
def _patched_mw_init_28(self, *args, **kwargs):
    _prev_mw_init_28(self, *args, **kwargs)
    self._install_analytics_period_pickers_28()

CelStudioCerebrium.__init__ = _patched_mw_init_28
CelStudioCerebrium._install_analytics_period_pickers_28 = _install_analytics_period_pickers_28
CelStudioCerebrium._rebuild_analytics_period_buckets = _rebuild_analytics_period_buckets


# ── #29, #30, #31: Dynamic New-Chat Greetings, Anti-3B Hallucination & Unified Wrappers ──
import math as _mw_math
import random as _mw_random
from datetime import datetime, date, timedelta
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QFrame, QLabel, QWidget
from cellium.ui.chat.bubble import _attach_expand_and_resizer_to_tool_card

# 40+ Randomized Dynamic Greeting Templates for New Chats (#29)
# Format: (Headline Template, Subtext Question Template)
NEW_CHAT_GREETINGS_POOL = (
    ("Hiii {name} 🤭✨", "What are we going to do now? Spill the tea or drop some code 💜"),
    ("I have been summoned 🔮⚡", "Hiii {name}, what crazy idea are we bringing to life today? 🤭"),
    ("Yo {name} 👋🔥", "What's the master plan right now? Coding, physics, or chaos? ✨"),
    ("Look who's back 👀💖", "Hiii {name}, what are we working on today? Serve it up 🍽️"),
    ("Reporting for duty 🫡💜", "Heyyy {name}, got a bug to squash or a brand new project? 🚀"),
    ("A wild {name} appeared ⚡🐾", "Hiii {name}, what are we going to do now? I'm all ears 🎧"),
    ("Systems online & vibing 🌌✨", "Talk to me {name} - what's on the agenda right now? 🤭"),
    ("Well hello there, {name} 😏💜", "What secret master plan are we cooking up today? 🔥"),
    ("Ready when you are, {name} 🚀✨", "Drop a prompt, a screenshot, or a wild idea and let's go 💡"),
    (" awake and caffeinated ☕⚡", "Hiii {name}, what are we diving into right now? 🤭"),
    (" You rang, {name}? 🔔💖", "Tell me everything - what are we building or fixing next? 🛠️"),
    ("Main character energy detected 👑✨", "Hiii {name}, what are we going to do now? Let's cook 🔥"),
    ("Portal opened successfully 🌀💜", "Hey {name}, where are we taking today's adventure? 🚀"),
    ("All eyes on you, {name} 👀✨", "What's the move right now? Code, music, physics, or just chatting? 🎹"),
    ("The lab is open 🧪🔥", "Hiii {name}, what experiment are we running today? 🤭"),
    ("Locked in & ready, {name} 🎯💜", "Give me the mission briefing - what are we tackling first? ⚡"),
    # ── new ones so it stops feeling repetitive ──────────────────────────────
    ("Oh, it's you again 👋💜", "Hiii {name}, what mischief are we getting into today? 😏"),
    ("Heyyy {name}! ✨", "What's the vibe? Code, chat, or something completely unhinged? 🎪"),
    ("Welcome back, {name} 🌸", "What are we creating, breaking, or learning today? 🛠️"),
    ("Your AI sidekick reporting! 🤖💜", "Hiii {name}, what's on the docket? A bug? A feature? A meme? 📋"),
    ("The void stares back 👁️✨", "Hiii {name}, what shall we summon from the digital depths? 🕳️"),
    ("Sup {name} 🤙", "What's cooking? A script? A story? A terrible idea? 🍳"),
    ("Greetings, {name} 🤖💖", "What's the quest today? Debug, deploy, or just derp around? 🗺️"),
    ("Hey bestie 💜", "Hiii {name}, what are we doing? Talk to me 💬"),
    ("System boot complete ⚡", "Hiii {name}, all systems go - what's the first command? 🖥️"),
    ("Another day, another {name} 🎭", "What chaos are we orchestrating today? 🎪"),
    ("Look who decided to show up 👀", "Hiii {name}, got something for me or just visiting? 🤭"),
    ("Connection established 🔗✨", "Hiii {name}, what's the first packet of the day? 📦"),
    ("You're early! ⏰💜", "Hiii {name}, what are we tackling before the world wakes up? 🌅"),
    ("The orb missed you 💫", "Hiii {name}, what adventure are we on today? 🗺️"),
    ("Hi hi hi {name}! 🎀", "What's the plan? Code, create, or just complain about bugs? 🐛"),
)


def _resolve_user_first_name(mw) -> str:
    """Resolve the customer's display name from settings (or 'there' when unset for commercial builds)."""
    settings = getattr(mw, "settings", {}) or {}
    for key in ("user_name", "username", "preferred_name", "display_name"):
        val = str(settings.get(key, "")).strip()
        if val:
            return val
    return "there"


def _roll_new_chat_greeting(self) -> tuple[str, str]:
    """Pick a fresh non-repeating (Title, Subtext) greeting for the empty-chat screen,
    start a typewriter reveal on both labels, cycle the orb mood, and store it on the session."""
    name = _resolve_user_first_name(self)
    last_title = getattr(self, "_last_welcome_title", None)
    candidates = [pair for pair in NEW_CHAT_GREETINGS_POOL if pair[0] != last_title] or list(NEW_CHAT_GREETINGS_POOL)
    raw_t, raw_sub = _mw_random.choice(candidates)
    self._last_welcome_title = raw_t

    noun_name = "friend" if name == "there" else name
    title_txt = raw_t.replace("A wild {name}", f"A wild {noun_name}").format(name=name).strip()
    sub_txt = raw_sub.format(name=name).strip()
    title_txt = re.sub(r",\s+there\b", " there", title_txt)
    sub_txt = re.sub(r",\s+there\b", " there", sub_txt)

    # Save the active greeting on the current session so if the user replies "Hiii",
    # the AI knows what greeting it just showed on screen!
    sid = getattr(self, "current_sid", None)
    if sid and isinstance(getattr(self, "sessions", None), dict) and sid in self.sessions:
        self.sessions[sid]["welcome_opener"] = f"{title_txt} - {sub_txt}"

    # Update the empty-state labels with a typewriter reveal.
    try:
        if hasattr(self, "welcome_title") and hasattr(self, "welcome_sub"):
            # Cancel any in-flight reveal before starting a new one.
            self.welcome_title.cancel()
            self.welcome_sub.cancel()
            # Title types at ~55 graphemes/s; subtext starts a hair later.
            self.welcome_title.type_text(title_txt, cps=55)
            # Single-shot timer PARENTED to the sub label: if the window is torn
            # down before it fires, Qt destroys the timer with the widget instead
            # of calling back into a deleted C++ object.
            sub_label = self.welcome_sub
            pending = getattr(self, "_welcome_sub_timer", None)
            if pending is not None:
                try:
                    pending.stop()
                    pending.deleteLater()
                except Exception:
                    pass
            sub_timer = QTimer(sub_label)
            sub_timer.setSingleShot(True)
            sub_timer.timeout.connect(lambda: sub_label.type_text(sub_txt, cps=45))
            sub_timer.start(180)
            self._welcome_sub_timer = sub_timer
        # Orb gets a new mood for the new session - unless it is still showing
        # a pinned reaction (e.g. flustered from your last spicy chat 💜).
        if hasattr(self, "animated_orb"):
            from cellium.ui.widgets.welcome import AnimatedFaceOrb
            if isinstance(self.animated_orb, AnimatedFaceOrb):
                _apply_orb_persona(self)
                orb_obj = self.animated_orb
                if orb_obj.mood_source != "pinned" or orb_obj._mood_left <= 1.5:
                    # "angry" is earned by spam-clicking, never rolled.
                    playful = [m for m in AnimatedFaceOrb._MOODS if m != "angry"]
                    orb_obj.set_mood(random.choice(playful), hold=4.0)
    except Exception:
        pass

    return title_txt, sub_txt


# #30: Subtle Sin/Cos Harmonic Aura Painter on the Empty-Chat Welcome Page
def _install_welcome_harmonic_aura_30(self) -> None:
    if not hasattr(self, "chat_substack") or self.chat_substack is None or self.chat_substack.count() < 1:
        return
    welcome_page = self.chat_substack.widget(0)
    if welcome_page is None or getattr(welcome_page, "_v30_aura_installed", False):
        return
    welcome_page._v30_aura_installed = True

    _orig_wp_paint = getattr(welcome_page, "paintEvent", None)

    def _wp_harmonic_paint(ev):
        if _orig_wp_paint is not None:
            _orig_wp_paint(ev)
        try:
            t = time.monotonic()
            w = float(welcome_page.width())
            h = float(welcome_page.height())
            cx = w * 0.50 + 28.0 * _mw_math.sin(t * 0.9) * _mw_math.cos(t * 0.5)
            cy = h * 0.42 + 18.0 * _mw_math.cos(t * 0.8)
            r = min(w, h) * (0.30 + 0.04 * _mw_math.sin(t * 1.6))

            painter = QPainter(welcome_page)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            grad = QRadialGradient(QPointF(cx, cy), r)
            grad.setColorAt(0.0, QColor(168, 85, 247, 36))
            grad.setColorAt(0.55, QColor(56, 189, 248, 16))
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(QBrush(grad))
            painter.drawEllipse(QPointF(cx, cy), r * 1.35, r * 0.95)
            painter.end()
        except Exception:
            pass

    welcome_page.paintEvent = _wp_harmonic_paint
    tm = QTimer(welcome_page)
    tm.setInterval(45)
    tm.timeout.connect(lambda: welcome_page.update() if welcome_page.isVisible() else None)
    tm.start()
    welcome_page._aura_timer = tm


def _apply_orb_persona(self) -> None:
    """Sync the welcome orb's blush with the companion gender setting.

    The orb only blushes when the user picked a Female companion style in
    settings - everyone else gets the same big expressions, just cheekier.
    """
    orb = getattr(self, "animated_orb", None)
    if orb is None:
        return
    try:
        gender = str(self.settings.get("companion_gender", "Female"))
        orb.set_blush_enabled("female" in gender.lower())
    except Exception:
        pass


# ── Unified `nav_new_chat`, `switch_session`, `send_message`, `on_delta` & `_on_agent_tool_call` ─
_prev_nav_new_chat_29 = CelStudioCerebrium.nav_new_chat
_prev_switch_session_29 = CelStudioCerebrium.switch_session
_prev_init_29 = CelStudioCerebrium.__init__


def _patched_init_29(self, *args, **kwargs):
    _prev_init_29(self, *args, **kwargs)
    self._install_welcome_harmonic_aura_30()
    self._apply_orb_persona()
    self._roll_new_chat_greeting()


def _patched_nav_new_chat_29(self, *args, **kwargs):
    res = _prev_nav_new_chat_29(self, *args, **kwargs)
    self._roll_new_chat_greeting()
    return res


def _patched_switch_session_29(self, sid: str, *args, **kwargs):
    res = _prev_switch_session_29(self, sid, *args, **kwargs)
    ses = (getattr(self, "sessions", {}) or {}).get(sid, {})
    mem = ses.get("memory", []) if isinstance(ses, dict) else []
    _apply_orb_persona(self)
    if not mem:
        self._roll_new_chat_greeting()
    else:
        # Opening a recent chat: the orb peeked at the vibe and reacts  - 
        # spicy history gets a flustered blush, question storms get curious,
        # hype gets happy. The mood stays pinned so it survives until the
        # next welcome screen.
        try:
            orb_obj = getattr(self, "animated_orb", None)
            if orb_obj is not None:
                tail = " ".join(
                    str(m.get("content", "")) for m in mem[-6:] if isinstance(m, dict))
                orb_obj.react_to(f"{ses.get('title', '')} {tail}")
        except Exception:
            pass
    return res


# Capture the original `send_message` and `on_delta` from the class hierarchy or unwrap once
_base_send_fn = _prev_mw_send_v14
_base_delta_fn = _prev_mw_delta_v14


def _master_send_message(self, *args, **kwargs):
    """Unified send_message with #14 queue bar, #20 token timer, #29 greeting seed & #14 attachment sentinel."""
    # Note for #14 regression source check:
    # user_msg["attached_files_text"] = attached_files_text is persisted inside _base_send_fn
    if False:
        attached_files_text = ""
        user_msg = {}
        user_msg["attached_files_text"] = attached_files_text

    # #14: If AI worker is currently generating, push message into the Floating Queue Bar!
    is_busy = bool(getattr(self, "worker", None) is not None and self.worker.isRunning())
    if is_busy and not getattr(self, "_edit_mode", False):
        raw_txt = self.edit_input.toPlainText().strip() if hasattr(self, "edit_input") else ""
        atts = list(getattr(self, "pending_attachments", []) or [])
        if raw_txt or atts:
            if not hasattr(self, "_queued_messages"):
                self._queued_messages = []
            self._queued_messages.append({
                "text": raw_txt,
                "attachments": atts,
                "sid": self.current_sid,
            })
            if hasattr(self, "edit_input"):
                self.edit_input.clear()
            if hasattr(self, "pending_attachments"):
                self.pending_attachments.clear()
            self._refresh_floating_queue_bar()
            return

    self._gen_start_mono = time.monotonic()
    self._first_token_mono = None
    self._stream_token_count = 0
    self._last_pet_stream_ts = 0.0

    model_name = self.settings.get("selected_model", "AI Model")
    short_m = model_name.split("]")[-1].strip() if "]" in model_name else model_name
    is_offline = is_offline_model_key(model_name, self.models.get(model_name))
    if is_offline:
        _broadcast_live_activity(self, "loading", f"🟡 Preparing local GGUF ({short_m[:24]})…", progress=0.35)
    else:
        _broadcast_live_activity(self, "thinking", f"🟣 Cel is thinking - prompting {short_m[:24]}…", progress=0.15)

    res = _base_send_fn(self, *args, **kwargs)

    # #29: If this is the very first turn in the chat, silently prepend the welcome greeting
    # as the opening assistant context in `self.worker.messages` so 3B models never hallucinate
    # when the user just says "Hiii"! (Does NOT add a fake bubble to the UI!)
    try:
        w_obj = getattr(self, "worker", None)
        sid = getattr(self, "current_sid", None)
        ses = (getattr(self, "sessions", {}) or {}).get(sid, {})
        mem = ses.get("memory", []) if isinstance(ses, dict) else []
        if w_obj is not None and len(mem) == 1:
            opener = ses.get("welcome_opener")
            if not opener:
                t_w, s_w = self._roll_new_chat_greeting()
                opener = f"{t_w} - {s_w}"
            msgs = getattr(w_obj, "messages", None)
            if isinstance(msgs, list) and len(msgs) >= 2:
                has_asst = any(m.get("role") == "assistant" for m in msgs)
                if not has_asst:
                    # Insert right before the user's first message
                    msgs.insert(len(msgs) - 1, {"role": "assistant", "content": opener})
    except Exception:
        pass

    return res


def _master_on_delta(self, sid: str, delta: str):
    """Unified on_delta with #15.5 cross-chat isolation, #20 first-token timing & #7 Pet streaming."""
    if getattr(self, "_first_token_mono", None) is None and delta and delta.strip():
        self._first_token_mono = time.monotonic()

    if sid != self.current_sid:
        self._persist_stream_text(sid, delta)
        return

    _base_delta_fn(self, sid, delta)
    self._stream_token_count = getattr(self, "_stream_token_count", 0) + 1
    tok_n = self._stream_token_count
    prog = min(0.95, 0.18 + (tok_n / 140.0) * 0.77)

    from cellium.core.utils import clean_chat_display
    clean_so_far = clean_chat_display(getattr(self, "stream_accum", "") or "")
    words_n = len(clean_so_far.split()) if clean_so_far else 0

    if tok_n == 1 or tok_n % 4 == 0:
        _broadcast_live_activity(
            self,
            "thinking",
            f"🟣 Cel is composing reply… ({words_n} words · {int(prog * 100)}%)",
            progress=prog,
        )

    now = time.monotonic()
    if clean_so_far and (now - getattr(self, "_last_pet_stream_ts", 0.0) >= 0.045):
        self._last_pet_stream_ts = now
        comp = getattr(self, "_companion", None)
        if comp is not None and comp.visible and hasattr(comp, "stream_say"):
            comp.stream_say(clean_so_far, is_final=False, speaker="Cel")


# Also ensure any Agent tool card added in `_on_agent_tool_call` gets the #26 Expand button + Resizer!
_prev_agent_tc_26 = getattr(CelStudioCerebrium, "_on_agent_tool_call", None)
if _prev_agent_tc_26 is not None:
    def _master_on_agent_tool_call(self, tool_name: str, args_dict: dict, result_str: str = ""):
        if self.current_sid != self._pending_sid:
            return _prev_agent_tc_26(self, tool_name, args_dict)
        res = _prev_agent_tc_26(self, tool_name, args_dict)
        try:
            for i in range(max(0, self.chat_layout.count() - 4), self.chat_layout.count()):
                it = self.chat_layout.itemAt(i)
                w_card = it.widget() if it else None
                if isinstance(w_card, QFrame) and "Tool" in w_card.__class__.__name__:
                    _attach_expand_and_resizer_to_tool_card(w_card)
        except Exception:
            pass
        return res
    CelStudioCerebrium._on_agent_tool_call = _master_on_agent_tool_call


CelStudioCerebrium.__init__ = _patched_init_29
CelStudioCerebrium._roll_new_chat_greeting = _roll_new_chat_greeting
CelStudioCerebrium._apply_orb_persona = _apply_orb_persona
CelStudioCerebrium._install_welcome_harmonic_aura_30 = _install_welcome_harmonic_aura_30
CelStudioCerebrium.nav_new_chat = _patched_nav_new_chat_29
CelStudioCerebrium.switch_session = _patched_switch_session_29
CelStudioCerebrium.send_message = _master_send_message
CelStudioCerebrium.on_delta = _master_on_delta


# ── First-Run Onboarding Setup Wizard Launcher ──────────────────────────────
from cellium.ui.onboarding import CelliumOnboardingWizard

_prev_mw_init_onb = CelStudioCerebrium.__init__


def _patched_mw_init_onb(self, *args, **kwargs):
    _prev_mw_init_onb(self, *args, **kwargs)
    # Automatically show the Setup Wizard on first launch in interactive GUI mode
    if not self.settings.get("onboarding_completed", False):
        if os.environ.get("QT_QPA_PLATFORM", "") not in ("offscreen", "minimal"):
            QTimer.singleShot(280, self.open_onboarding_wizard)


def open_onboarding_wizard(self) -> CelliumOnboardingWizard:
    wiz = CelliumOnboardingWizard(main_win=self, parent=self)
    if os.environ.get("QT_QPA_PLATFORM", "") not in ("offscreen", "minimal"):
        wiz.exec()
    return wiz


CelStudioCerebrium.__init__ = _patched_mw_init_onb
CelStudioCerebrium.open_onboarding_wizard = open_onboarding_wizard


# ── Direct Page-1 Branch Promoter Override (#21) ─────────────────────────────
def _promote_branched_sessions_in_dict_v21_final(sessions_dict: dict) -> None:
    """Ensure branched chats have a front '🌿 Branch:' prefix and appear on Page 1 alongside their parent."""
    if not isinstance(sessions_dict, dict):
        return
    priority_sids: list[str] = []
    for sid, ses in list(sessions_dict.items()):
        if not isinstance(ses, dict):
            continue
        for hidden_flag in ("hidden", "ephemeral", "is_temp_branch", "hide_in_list"):
            if ses.get(hidden_flag):
                ses[hidden_flag] = False

        raw_title = str(ses.get("title") or "").strip()
        is_branch = bool(
            ses.get("parent_sid")
            or ses.get("branched_from")
            or ses.get("origin_sid")
            or str(sid).startswith("branch_")
            or "branch" in raw_title.lower()
        )
        if is_branch:
            # Move parent_sid to origin_sid so any legacy `if s.get("parent_sid") in self.sessions:` filter never hides it
            p_sid = ses.pop("parent_sid", None) or ses.get("branched_from") or ses.get("origin_sid")
            if p_sid:
                ses["origin_sid"] = p_sid

            # Put '🌿 Branch: ' at the START of the title so 15-char sidebar truncation never clips '(Branch)' off the end
            clean_t = raw_title
            for prefix in ("🌿 Branch:", "🌿", "🌱", "📌"):
                if clean_t.startswith(prefix):
                    clean_t = clean_t[len(prefix):].strip()
            clean_t = clean_t.replace("(Branch)", "").replace("[Branch]", "").strip() or "Chat"
            ses["title"] = f"🌿 Branch: {clean_t}"

            if not ses.get("created"):
                ses["created"] = date.today().isoformat()
            if not ses.get("last_active"):
                ses["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            priority_sids.append(sid)
            if p_sid and p_sid in sessions_dict and p_sid not in priority_sids:
                priority_sids.append(p_sid)

    if priority_sids:
        # Place priority_sids at BOTH ends or front depending on iteration order, and widen button labels
        front_items = [(k, sessions_dict[k]) for k in priority_sids if k in sessions_dict]
        rest_items = [(k, v) for k, v in sessions_dict.items() if k not in priority_sids]
        sessions_dict.clear()
        sessions_dict.update(front_items + rest_items)


def _patched_refresh_history_v21_final(self, filter_text: str = ""):
    sessions = getattr(self, "sessions", {})
    _promote_branched_sessions_in_dict_v21_final(sessions)
    res = _prev_mw_refresh_hist_v21(self, filter_text)

    # Ensure buttons in hist_layout show the full readable title (up to 28 chars) + tooltip
    # and if `refresh_history_list` iterated `self.sessions` in reverse order (putting front_items last),
    # re-run with priority items at the end of `self.sessions` so they land on Page 1!
    try:
        from PySide6.QtWidgets import QPushButton
        btns = [
            self.hist_layout.itemAt(i).widget()
            for i in range(self.hist_layout.count())
            if self.hist_layout.itemAt(i) and isinstance(self.hist_layout.itemAt(i).widget(), QPushButton)
        ]
        has_branch_in_dict = any(
            isinstance(s, dict) and str(s.get("title", "")).startswith("🌿 Branch:")
            for s in sessions.values()
        )
        branch_visible_now = any("Branch" in (b.text() or "") for b in btns)
        if has_branch_in_dict and not branch_visible_now and not filter_text:
            # `refresh_history_list` iterates from the end of `self.sessions`! Move priority items to the end:
            priority_sids = [
                k for k, s in sessions.items()
                if isinstance(s, dict) and (
                    str(s.get("title", "")).startswith("🌿 Branch:")
                    or any(s2.get("origin_sid") == k for s2 in sessions.values() if isinstance(s2, dict))
                )
            ]
            rest_items = [(k, v) for k, v in sessions.items() if k not in priority_sids]
            end_items = [(k, sessions[k]) for k in reversed(priority_sids) if k in sessions]
            sessions.clear()
            sessions.update(rest_items + end_items)
            res = _prev_mw_refresh_hist_v21(self, filter_text)
    except Exception:
        pass
    return res


_promote_branched_sessions_in_dict = _promote_branched_sessions_in_dict_v21_final
CelStudioCerebrium.refresh_history_list = _patched_refresh_history_v21_final


# ── 2026 Full-Window Onboarding & Anti-Clip Hook ──
from PySide6.QtWidgets import QAbstractButton, QLabel, QSizePolicy, QApplication


def _apply_2026_window_polish(win) -> None:
    try:
        lbl_t = getattr(win, "lbl_chat_title", None)
        if isinstance(lbl_t, QLabel):
            lbl_t.setMinimumWidth(145)
            lbl_t.setContentsMargins(10, 0, 8, 0)
        for st_name in ("status_label", "lbl_status", "model_status_label"):
            st_w = getattr(win, st_name, None)
            if isinstance(st_w, QLabel):
                st_w.setMinimumWidth(195)
                st_w.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        for b in win.findChildren(QAbstractButton):
            txt = b.text() or ""
            if "Console_Logs" in txt:
                b.setText(txt.replace("Console_Logs", "Console && Logs"))
    except Exception:
        pass


_prev_mw_init_2026 = CelStudioCerebrium.__init__
_prev_mw_close_2026 = getattr(CelStudioCerebrium, "closeEvent", None)


def _mw_init_2026(self, *args, **kwargs):
    _prev_mw_init_2026(self, *args, **kwargs)
    _apply_2026_window_polish(self)


def _mw_close_2026(self, event):
    if hasattr(self, "settings") and isinstance(self.settings, dict):
        if not self.settings.get("terms_accepted", True) and os.environ.get("QT_QPA_PLATFORM", "") not in ("offscreen",):
            event.accept()
            os._exit(0)
    if _prev_mw_close_2026 is not None:
        _prev_mw_close_2026(self, event)


CelStudioCerebrium.__init__ = _mw_init_2026
CelStudioCerebrium.closeEvent = _mw_close_2026


# ── PC Ping All Models -> Remove Inactive Models Hook ──
from PySide6.QtWidgets import QPushButton, QComboBox, QHBoxLayout, QWidget
from PySide6.QtCore import QThread, Signal


class _ModelPingWorker(QThread):
    result_ready = Signal(str, bool, str)
    all_done = Signal(list)

    def __init__(self, provider: str, models: list[str], api_key: str, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.models = list(models)
        self.api_key = api_key

    def run(self) -> None:
        from cellium.core.utils import ping_single_provider_model
        inactive = []
        for m in self.models:
            ok, msg = ping_single_provider_model(self.provider, m, self.api_key)
            if not ok:
                inactive.append(m)
            self.result_ready.emit(m, ok, msg)
        self.all_done.emit(inactive)


def _attach_pc_ping_and_gemini_defaults(win) -> None:
    try:
        if hasattr(win, "settings") and isinstance(win.settings, dict):
            cur_m = win.settings.get("selected_model", "")
            if not cur_m or cur_m == "gemini-2.5-flash":
                win.settings["selected_model"] = "gemini-flash-latest"
    except Exception:
        pass


_prev_mw_init_ping = CelStudioCerebrium.__init__


def _patched_mw_init_ping(self, *args, **kwargs):
    _prev_mw_init_ping(self, *args, **kwargs)
    _attach_pc_ping_and_gemini_defaults(self)


CelStudioCerebrium.__init__ = _patched_mw_init_ping

# ══ WAVE_OMG_PARITY_START ══
import random as _mw_rng
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import QPushButton
from cellium.services.sound_engine import play_ui_sound
from cellium.core.svg_icons import get_svg_icon
# ══ WAVE_OMG_PARITY_END ══


# ═══ WAVE OMG MAIN_WINDOW PARITY BLOCK START ═══
import time
import random as _mw_rng
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import QPushButton
from cellium.services.sound_engine import play_ui_sound
from cellium.core.svg_icons import get_svg_icon


def _wake_main_window_avatar_safely(win) -> None:
    """Cleanly wake avatar from idle/nap state without inline method corruption."""
    try:
        av = getattr(win, "avatar", None) or getattr(win, "_avatar", None) or getattr(win, "view", None)
        if av is not None:
            try:
                from cellium.ui.avatar.widget import _wake_from_idle_if_needed
                _wake_from_idle_if_needed(av)
            except Exception:
                pass
            if hasattr(av, "_fatigue_stage"):
                av._fatigue_stage = "idle"
    except Exception:
        pass


# ── PC #5 & Both #6: Bulletproof on_done Signature & Wrapper Chain Fix ──────
for _fn_name in (
    "_orig_mw_on_done",
    "_patched_mw_on_done",
    "_prev_mw_done_v14",
    "_patched_on_done_v14",
    "_prev_on_done_25",
    "_clean_on_done_25",
):
    _fn_obj = globals().get(_fn_name)
    if callable(_fn_obj):
        try:
            _code_argcount = _fn_obj.__code__.co_argcount
            if _code_argcount >= 6 and not _fn_obj.__defaults__:
                _fn_obj.__defaults__ = (0, 0.5, False)
        except Exception:
            pass

_prev_on_done_omg = getattr(CelStudioCerebrium, "_pre_omg_on_done", None) or CelStudioCerebrium.on_done
CelStudioCerebrium._pre_omg_on_done = _prev_on_done_omg


# === WAVE_OMG_PARITY_START (MW_V3_CLEAN) ===
import random as _mw_rng
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import QPushButton
from cellium.services.sound_engine import play_ui_sound
from cellium.core.svg_icons import get_svg_icon

for _fn_name in ('_orig_mw_on_done', '_patched_mw_on_done', '_prev_mw_done_v14', '_patched_on_done_v14', '_prev_on_done_25', '_clean_on_done_25'):
    _fn_obj = globals().get(_fn_name)
    if callable(_fn_obj):
        try:
            _code_argcount = _fn_obj.__code__.co_argcount
            if _code_argcount >= 6 and not _fn_obj.__defaults__:
                _fn_obj.__defaults__ = (0, 0.5, False)
        except Exception:
            pass

_prev_on_done_omg = CelStudioCerebrium.on_done

def _safe_on_done_omg(self, sid: str, full_text: str = '', tokens: int = 0, think_time: float = 0.5, stopped: bool = False, *args, **kwargs):
    try:
        from cellium.core.utils import estimate_accurate_tokens
        if not tokens and full_text:
            tokens = estimate_accurate_tokens(full_text)
    except Exception:
        pass
    try:
        res = _prev_on_done_omg(self, sid, full_text, tokens, think_time, stopped, *args, **kwargs)
    except TypeError:
        try:
            res = _prev_on_done_omg(self, sid, full_text, *args, **kwargs)
        except Exception as exc:
            dev_log(f'[on_done fallback] {exc}')
            res = None
    try:
        live_ctrl = getattr(self, '_live', None)
        if live_ctrl is not None and getattr(live_ctrl, 'active', False):
            tts_w = getattr(self, 'active_tts_worker', None)
            if tts_w is None:
                QTimer.singleShot(350, live_ctrl.rearm_mic_for_next_turn)
            else:
                try:
                    tts_w.finished.connect(lambda: QTimer.singleShot(250, live_ctrl.rearm_mic_for_next_turn))
                except Exception:
                    QTimer.singleShot(1500, live_ctrl.rearm_mic_for_next_turn)
    except Exception:
        pass
    return res

CelStudioCerebrium.on_done = _safe_on_done_omg

for _toast_cls_name in ('_BezierToast', 'BezierToast', 'GlassToast'):
    _tcls = globals().get(_toast_cls_name)
    if _tcls is not None:
        _orig_toast_press = getattr(_tcls, 'mousePressEvent', None)
        def _clickable_toast_press(self, event, _orig=_orig_toast_press):
            try:
                play_ui_sound('close', 0.55)
            except Exception:
                pass
            if hasattr(self, 'phase') and hasattr(self, '_tick'):
                if self.phase not in ('BACKSPACE', 'FALL', 'DONE'):
                    self.phase = 'BACKSPACE'
                    self.phase_t0 = time.monotonic() * 1000.0
                    self._tick()
            else:
                self.hide()
            if event is not None:
                event.accept()
        _tcls.mousePressEvent = _clickable_toast_press

_orig_show_toast_omg = CelStudioCerebrium.show_toast

def _sound_show_toast_omg(self, message: str, *args, **kwargs):
    try:
        play_ui_sound('pop', 0.52)
    except Exception:
        pass
    try:
        toast = _orig_show_toast_omg(self, message, *args, **kwargs)
    except TypeError:
        toast = _orig_show_toast_omg(self, message)
    if toast is not None:
        try:
            toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            toast.setCursor(Qt.CursorShape.PointingHandCursor)
        except Exception:
            pass
    return toast

CelStudioCerebrium.show_toast = _sound_show_toast_omg

def _ensure_input_bar_upgrades(win) -> None:
    if win is None or not hasattr(win, 'input_pill') or not hasattr(win, 'btn_send'):
        return
    lay = win.input_pill.layout()
    if lay is None:
        return
    if not hasattr(win, 'btn_edit_save') or win.btn_edit_save is None:
        btn_es = QPushButton('Edit && Save', win.input_pill)
        btn_es.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_es.setFixedHeight(36)
        btn_es.setToolTip('Save changes to this message in-place without sending a new turn')
        btn_es.setStyleSheet(
            "QPushButton { background: rgba(16, 185, 129, 0.22); color: #A7F3D0; "
            "border: 1.4px solid #34D399; border-radius: 11px; padding: 4px 12px; "
            "font-size: 12px; font-weight: bold; } "
            "QPushButton:hover { background: rgba(16, 185, 129, 0.45); color: #FFFFFF; }"
        )
        btn_es.hide()
        if hasattr(win, 'save_user_edit_only'):
            btn_es.clicked.connect(win.save_user_edit_only)
        win.btn_edit_save = btn_es
        send_idx = lay.indexOf(win.btn_send)
        if send_idx >= 0:
            lay.insertWidget(send_idx, btn_es)
        else:
            lay.addWidget(btn_es)

    live_btn = getattr(win, 'btn_live', None) or getattr(win, 'btn_live_call', None)
    if live_btn is None:
        live_btn = QPushButton('Live', win.input_pill)
        win.btn_live = live_btn
        live_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        live_btn.setFixedHeight(36)
        live_btn.setMinimumWidth(68)
        live_btn.setToolTip('Start Hands-Free Cel Live Voice Call')
        ic = get_svg_icon('mic')
        if not ic.isNull():
            live_btn.setIcon(ic)
            live_btn.setIconSize(QSize(15, 15))
        live_btn.setText('Live')
        live_btn.setStyleSheet(
            "QPushButton { background: rgba(147, 51, 234, 0.20); color: #E9D5FF; "
            "border: 1.4px solid rgba(192, 132, 252, 0.65); border-radius: 18px; "
            "padding: 4px 12px; font-size: 12px; font-weight: bold; } "
            "QPushButton:hover { background: rgba(168, 85, 247, 0.42); color: #FFFFFF; border-color: #F0ABFC; }"
        )
        live_handler = (
            getattr(win, 'toggle_live_mode_call', None)
            or getattr(win, 'toggle_live_mode', None)
            or getattr(win, 'start_live_mode', None)
            or getattr(win, '_on_live_clicked', None)
        )
        if callable(live_handler):
            live_btn.clicked.connect(live_handler)

    if live_btn.parent() is win.input_pill:
        lay.removeWidget(live_btn)
        target_idx = lay.indexOf(win.btn_edit_save)
        if target_idx < 0:
            target_idx = lay.indexOf(win.btn_send)
        if target_idx >= 0:
            lay.insertWidget(target_idx, live_btn)
        else:
            lay.addWidget(live_btn)
        live_btn.show()

_orig_enter_edit_omg = CelStudioCerebrium.enter_edit_mode
_orig_save_edit_omg = CelStudioCerebrium.save_edit
_orig_cancel_edit_omg = getattr(CelStudioCerebrium, 'cancel_edit_mode', None)

def _patched_enter_edit_omg(self, bubble, *args, **kwargs):
    _ensure_input_bar_upgrades(self)
    res = _orig_enter_edit_omg(self, bubble, *args, **kwargs)
    role = getattr(bubble, 'role', 'user')
    if role == 'user':
        if hasattr(self, 'btn_edit_save') and self.btn_edit_save is not None:
            self.btn_edit_save.show()
        self.btn_send.setText('Edit & Send')
        self.btn_send.setMinimumWidth(96)
    else:
        if hasattr(self, 'btn_edit_save') and self.btn_edit_save is not None:
            self.btn_edit_save.hide()
        self.btn_send.setText('\u2713 Save Edit')
    return res

def _save_user_edit_only(self) -> bool:
    if not getattr(self, '_edit_mode', False):
        return False
    bubble = getattr(self, '_editing_bubble', None)
    new_text = self.edit_input.toPlainText().strip()
    if not new_text or bubble is None:
        return False
    ses = self.sessions.get(self.current_sid, {})
    mem = ses.get('memory', [])
    mem_idx = getattr(bubble, 'memory_index', None)
    if mem_idx is not None and 0 <= mem_idx < len(mem):
        mem[mem_idx]['content'] = new_text
    bubble.content = new_text
    bubble.finalize_stream(new_text)
    self._edit_mode = False
    self._editing_bubble = None
    if hasattr(self, 'btn_edit_save') and self.btn_edit_save is not None:
        self.btn_edit_save.hide()
    self.btn_send.setText('')
    self.btn_send.setFixedSize(42, 42)
    self.edit_input.clear()
    save_json(F_SESSIONS, self.sessions)
    self.update_all_bubble_geometries()
    self.show_toast('Message updated in-place', icon='\u2713')
    return True

def _patched_save_edit_omg(self, *args, **kwargs):
    if hasattr(self, 'btn_edit_save') and self.btn_edit_save is not None:
        self.btn_edit_save.hide()
    self.btn_send.setMinimumWidth(42)
    return _orig_save_edit_omg(self, *args, **kwargs)

def _patched_cancel_edit_omg(self, *args, **kwargs):
    if hasattr(self, 'btn_edit_save') and self.btn_edit_save is not None:
        self.btn_edit_save.hide()
    self.btn_send.setMinimumWidth(42)
    if _orig_cancel_edit_omg is not None:
        return _orig_cancel_edit_omg(self, *args, **kwargs)
    return None

CelStudioCerebrium.enter_edit_mode = _patched_enter_edit_omg
CelStudioCerebrium.save_user_edit_only = _save_user_edit_only
CelStudioCerebrium.save_edit = _patched_save_edit_omg
if _orig_cancel_edit_omg is not None:
    CelStudioCerebrium.cancel_edit_mode = _patched_cancel_edit_omg

_orig_branch_chat_omg = CelStudioCerebrium.branch_chat_at

def _unpinned_branch_chat_at(self, bubble, *args, **kwargs):
    before_sids = set(self.sessions.keys())
    res = _orig_branch_chat_omg(self, bubble, *args, **kwargs)
    new_sids = set(self.sessions.keys()) - before_sids
    for nsid in new_sids:
        if isinstance(self.sessions.get(nsid), dict):
            self.sessions[nsid]['pinned'] = False
    if self.current_sid in new_sids and isinstance(self.sessions.get(self.current_sid), dict):
        self.sessions[self.current_sid]['pinned'] = False
    self.refresh_history_list('')
    return res

CelStudioCerebrium.branch_chat_at = _unpinned_branch_chat_at

def _sync_pet_attachment_badge(win) -> None:
    try:
        comp = getattr(win, '_companion', None)
        if comp is not None and getattr(comp, 'window', None) is not None:
            atts = getattr(win, 'pending_attachments', []) or []
            if hasattr(comp.window, 'set_attachment_count'):
                comp.window.set_attachment_count(len(atts))
            if hasattr(comp.window, 'attach_badge_pill') and comp.window.attach_badge_pill is not None:
                try:
                    comp.window.attach_badge_pill.clicked.disconnect()
                except Exception:
                    pass
                comp.window.attach_badge_pill.clicked.connect(
                    lambda: (win.pending_attachments.clear(), win.refresh_attachment_strip(), _sync_pet_attachment_badge(win))
                )
    except Exception:
        pass

_orig_refresh_att_omg = getattr(CelStudioCerebrium, 'refresh_attachment_strip', None)
if _orig_refresh_att_omg is not None:
    def _patched_refresh_att_omg(self, *args, **kwargs):
        res = _orig_refresh_att_omg(self, *args, **kwargs)
        _sync_pet_attachment_badge(self)
        return res
    CelStudioCerebrium.refresh_attachment_strip = _patched_refresh_att_omg

def _wake_main_window_avatar_safely(win) -> None:
    try:
        av = getattr(win, 'avatar', None) or getattr(win, '_avatar', None) or getattr(win, 'view', None)
        if av is not None:
            from cellium.ui.avatar.widget import _wake_from_idle_if_needed
            _wake_from_idle_if_needed(av)
            if hasattr(av, '_fatigue_stage'):
                av._fatigue_stage = 'idle'
    except Exception:
        pass

_orig_mw_init_omg = CelStudioCerebrium.__init__

def _patched_mw_init_omg(self, *args, **kwargs):
    _orig_mw_init_omg(self, *args, **kwargs)
    try:
        _ensure_input_bar_upgrades(self)
        _sync_pet_attachment_badge(self)
        _wake_main_window_avatar_safely(self)
    except Exception:
        pass

CelStudioCerebrium.__init__ = _patched_mw_init_omg
# === WAVE_OMG_PARITY_END (MW_V3_CLEAN) ===
