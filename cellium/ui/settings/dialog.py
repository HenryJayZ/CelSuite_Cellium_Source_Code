#!/usr/bin/env python3
"""
CelStudio Cerebrium - Native PySide6 Desktop Application
Liquid Glass UI, Neon Glow Saturation & Dynamic Color-Shifting Wallpaper Engine
100% LGPL PySide6 Standard | Central Venv | Strict Signals
Telegram-Style Glass Input | Inbuilt Emoji Picker | Multi-Engine STT | 100% Inbuilt Views
Animal Crossing / Mellodi Musical Cel Voice | Cozy Sound System | Zero Popups
"""

import sys
import os
import io
import json
import time
import tempfile
import uuid
import base64
import copy
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

from PySide6.QtWidgets import (
    QSpinBox, QDoubleSpinBox, QTabWidget, QProgressBar, QLayout,
)
from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer

# ============================================================
# GLOBAL REAL-TIME LOGGING SYSTEM - Immediate stdout/stderr flush
# ============================================================
_original_print = print

# --- CROSS IMPORTS ---
from cellium.ui.widgets.toggle import *
from cellium.ui.widgets.pfp import (
    CircularAvatarLabel, run_avatar_flow, clear_avatar, bust_avatar_cache,
)
from cellium.ui.chat.glass import *
from cellium.core.logger import *
from cellium.core.config import (
    CTX_MAP, VENV_DIR, TYPING_SOUND_MODES, FONT_SCALE_CHOICES,
    OFFLINE_PROMPT_TEMPLATES, TUNABLE_SOUNDS,
    stt_key_hint, stt_key_provider, STT_LOCAL_GGML, norm_stt_engine,
    KOKORO_DIR, DEFAULT_SOUND_PACK, normalize_sound_pack,
    CEL_TYPING_MODES, normalize_cel_typing_mode, DEFAULT_REALISTIC_VOICE,
)
import cellium.core.config as _sound_cfg  # live per-sound volume updates
from cellium.core.utils import *
from cellium.core.tools import *
from cellium.services.sound_engine import *
from cellium.services.realistic_voice import (
    play_realistic_voice_preview,
)
from cellium.services.ai_llama import *
from cellium.services.audio_stt import *
from cellium.services.audio_tts import *
from cellium.services.ai_workers import *

_SLIDER_QSS = """
QSlider::groove:horizontal {
    height: 5px; background: rgba(255, 255, 255, 0.10); border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #A855F7; border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #C084FC; border: 1.5px solid #E879F9;
    width: 13px; height: 13px; margin: -5px 0; border-radius: 8px;
}
QSlider::groove:horizontal:hover { background: rgba(255, 255, 255, 0.16); }
QSlider::sub-page:horizontal:hover { background: #C084FC; }
QSlider::handle:horizontal:hover { background: #E9D5FF; }
QSlider:disabled::sub-page:horizontal { background: rgba(168, 85, 247, 0.35); }
"""


def _theme_sliders(root) -> None:
    """Purple every slider under ``root``.

    Left to Qt these render in the OS default blue, which is the one saturated
    blue in an otherwise purple app.
    """
    for sld in root.findChildren(QSlider):
        try:
            sld.setStyleSheet(_SLIDER_QSS)
        except RuntimeError:
            pass


def _lock_wheel(widget, enabled: bool = True) -> None:
    """Stop the wheel from changing a combo/spin when unfocused.

    Instance-patch design: the original handler is stashed as
    ``_wheelEvent_original`` and a small shim consumes unfocused wheel
    events (no value change, no page scroll) while a focused widget keeps
    its real behaviour. Unlocking removes the shim; the stash stays so a
    re-lock never loses the true handler.
    """
    if widget is None:
        return
    if enabled:
        try:
            if "wheelEvent" in widget.__dict__:
                return  # already locked
        except Exception:
            pass
        try:
            original = widget.wheelEvent
        except Exception:
            return
        try:
            widget._wheelEvent_original = original
        except Exception:
            pass

        def _locked_wheel(event, _w=widget, _orig=original):
            try:
                if _w.hasFocus():
                    _orig(event)
                else:
                    try:
                        event.accept()
                    except Exception:
                        pass
            except RuntimeError:
                pass

        try:
            widget.wheelEvent = _locked_wheel
        except Exception:
            pass
    else:
        try:
            if "wheelEvent" in widget.__dict__:
                del widget.__dict__["wheelEvent"]
        except Exception:
            pass


def _lock_all_wheels(root, enabled: bool) -> None:
    """Wheel-lock every combo and spin box under ``root``.

    The per-widget calls only ever covered combos, so every numeric spinner  - 
    GPU layers, threads, context, timeouts - kept changing value under the
    cursor even with the lock on. One sweep fixes all of them, including the
    ones built later.
    """
    if root is None:
        return
    for cls in (QComboBox, QSpinBox, QDoubleSpinBox):
        for w in root.findChildren(cls):
            _lock_wheel(w, enabled)


def _live_sound_vol(self_widget, name: str, value, label) -> None:
    """Apply a per-sound slider change immediately (no Save required).

    Updates ``config.SOUND_VOLUMES`` so ``play_ui_sound`` honours the new
    volume *now*, and mirrors it into ``self_widget.settings["audio_volumes"]``
    so it persists on Save. Volume 0 mutes that sound entirely.
    """
    try:
        ival = max(0, min(250, int(value)))
    except (TypeError, ValueError):
        return
    try:
        label.setText(f"{ival}%")
    except RuntimeError:
        pass
    _sound_cfg.SOUND_VOLUMES[name] = ival
    try:
        self_widget.settings.setdefault("audio_volumes", {})[name] = ival
    except Exception:
        pass


from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QListWidget,
    QListWidgetItem, QStyle, QStyledItemDelegate, QListView,
)
from PySide6.QtCore import QAbstractListModel, QModelIndex
from PySide6.QtGui import QFontMetrics, QPixmap, QPixmapCache


class _CelMojiListModel(QAbstractListModel):
    """Zero-allocation virtualized list model holding items without widget churn."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []  # list of (item, kw_str, is_pinned, is_divider)

    def set_items(self, items):
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._items):
            return None
        entry = self._items[row]
        if role == Qt.ItemDataRole.UserRole:
            return entry[0]
        elif role == Qt.ItemDataRole.UserRole + 1:
            return entry[1]
        elif role == Qt.ItemDataRole.UserRole + 2:
            return entry[2]
        elif role == Qt.ItemDataRole.UserRole + 3:
            return entry[3]
        elif role == Qt.ItemDataRole.ToolTipRole:
            if entry[3]:
                return None
            return f"{entry[0]}  -  {entry[1]}\n(Click left 📌 to pin · Right-click for options)"
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        row = index.row()
        if 0 <= row < len(self._items) and self._items[row][3]:
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


class _CelMojiRowDelegate(QStyledItemDelegate):
    """Ultra-fast custom row painter with hardware QPixmapCache acceleration and Linux color font prioritization."""
    DIVIDER = "__DIVIDER__"
    PIN_ZONE_W = 32

    def __init__(self, picker, emoji_pt: int = 20, row_h: int = 38, kw_pt: int = 10, parent=None):
        super().__init__(parent)
        self.picker = picker
        self.emoji_pt = emoji_pt
        self.row_h = row_h
        QPixmapCache.setCacheLimit(65536)  # 64 MB hardware pixmap cache

        self.emoji_font = QFont()
        self.emoji_font.setFamilies([
            "Noto Color Emoji", "Twemoji Mozilla", "Apple Color Emoji", "Segoe UI Emoji", "Sans Serif"
        ])
        self.emoji_font.setPointSize(emoji_pt)
        self.fm_emoji = QFontMetrics(self.emoji_font)

        self.kw_font = QFont()
        self.kw_font.setPointSize(kw_pt)
        self.fm_kw = QFontMetrics(self.kw_font)

    def sizeHint(self, option, index):
        return QSize(option.rect.width() or 360, self.row_h)

    def paint(self, painter, option, index):
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            r = option.rect
            item = index.data(Qt.ItemDataRole.UserRole) or ""
            is_div = index.data(Qt.ItemDataRole.UserRole + 3)
            if item == self.DIVIDER or is_div:
                painter.setPen(QPen(QColor(168, 85, 247, 95), 1.0, Qt.PenStyle.DashLine))
                ymid = r.y() + r.height() // 2
                painter.drawLine(r.x() + 10, ymid, r.right() - 10, ymid)
                return

            if option.state & QStyle.StateFlag.State_Selected:
                painter.fillRect(r, QColor(147, 51, 234, 95))
                painter.fillRect(r.x(), r.y(), 3, r.height(), QColor("#E879F9"))
                kw_color = QColor("#F8F4FF")
            elif option.state & QStyle.StateFlag.State_MouseOver:
                painter.fillRect(r, QColor(147, 51, 234, 42))
                kw_color = QColor("#E9D5FF")
            else:
                kw_color = QColor("#A78BFA")

            kw = index.data(Qt.ItemDataRole.UserRole + 1) or ""
            pinned = index.data(Qt.ItemDataRole.UserRole + 2) or (item in self.picker._pin_set)
            cy = r.y() + r.height() // 2
            px = r.x() + 10

            # Pin indicator in left 32px zone
            painter.setPen(QPen(QColor("#E879F9") if pinned else QColor(167, 139, 250, 70), 1.5))
            painter.drawLine(px + 4, cy - 1, px + 2, cy + 9)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#C084FC") if pinned else QColor(147, 51, 234, 65))
            painter.drawEllipse(px - 2, cy - 9, 12, 12)
            painter.setBrush(QColor("#F8F4FF") if pinned else QColor(20, 14, 38, 180))
            painter.drawEllipse(px + 1, cy - 6, 4, 4)

            # Emoji / Kaomoji / Emoticon glyph with QPixmapCache hardware acceleration
            cache_key = f"cellium_emj_{item}_{self.emoji_pt}"
            pixmap = QPixmapCache.find(cache_key)
            if pixmap is None:
                ew_calc = max(28, min(self.fm_emoji.horizontalAdvance(item), 175))
                pixmap = QPixmap(int(ew_calc) + 8, self.row_h)
                pixmap.fill(Qt.GlobalColor.transparent)
                p = QPainter(pixmap)
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
                p.setFont(self.emoji_font)
                p.setPen(QColor("#F8F4FF"))
                p.drawText(QRect(0, 0, pixmap.width(), pixmap.height()),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, item)
                p.end()
                QPixmapCache.insert(cache_key, pixmap)

            # Instant 0.0ms blit
            glyph_x = r.x() + 34
            painter.drawPixmap(glyph_x, r.y(), pixmap)
            ew = pixmap.width() - 8

            # Keywords
            kw_x = r.x() + 44 + int(ew)
            painter.setFont(self.kw_font)
            painter.setPen(kw_color)
            avail = max(10, r.width() - (kw_x - r.x()) - 8)
            elided = self.fm_kw.elidedText(kw, Qt.TextElideMode.ElideRight, avail)
            painter.drawText(kw_x, r.y(), avail, r.height(),
                             Qt.AlignmentFlag.AlignVCenter, elided)
        finally:
            painter.restore()

    def editorEvent(self, event, model, option, index):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.MouseButtonRelease:
            px = event.position().x() if hasattr(event, "position") else event.pos().x()
            if event.button() == Qt.MouseButton.LeftButton and (option.rect.x() <= px <= option.rect.x() + self.PIN_ZONE_W):
                item = index.data(Qt.ItemDataRole.UserRole)
                if item and item != self.DIVIDER:
                    self.picker._toggle_pin(item)
                    return True
        return False


class EmojiPickerWidget(GlassPanel):
    """CelMoji Engine merged into Cellium's Liquid Glass Purple Palette.

    Uses QListWidget + _CelMojiRowDelegate + 0ms setRowHidden() filtering across
    3 tabs (Emojis, Kaomoji, Emoticons) so searching thousands of items is
    instant with zero widget churn.
    """
    emoji_selected = Signal(str)
    DIVIDER = "__DIVIDER__"

    def __init__(self, parent=None):
        super().__init__(radius=18, parent=parent)
        self.setFixedSize(460, 360)
        self.settings = None
        self._emj_mem = {"emoji_frec": {}, "emoji_pins": [], "emoji_bans": [], "emoji_tags": {}}
        self._celmoji_dir = Path.home() / "Documents" / "Projects" / "Python" / "CelSuite CelMoji"
        self._celmoji_data_dir = Path.home() / ".local" / "share" / "celmoji"
        self._pin_set = set()
        self._raw_tabs = {"emoji": {}, "kaomoji": {}, "emoticons": {}}
        self._all_data = {"emoji": [], "kaomoji": [], "emoticons": []}
        self._haystacks = {}
        self._built = set()
        self._last_filter = {}
        self._display = {}
        self._shown = {}
        self._page_size = 200
        self._canonical = {}
        self.custom_kaomojis = []

        self.layout_v = QVBoxLayout(self)
        self.layout_v.setContentsMargins(12, 10, 12, 10)
        self.layout_v.setSpacing(6)

        # Header row: search + close
        top_h = QHBoxLayout()
        top_h.setSpacing(6)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Search emojis, kaomoji, emoticons, tags… (Down=list, Enter=use)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setStyleSheet("""
            QLineEdit {
                background: rgba(14, 10, 24, 0.90);
                border: 1.5px solid #9333EA;
                border-radius: 10px;
                color: #F8F4FF;
                padding: 6px 10px;
                font-size: 12px;
            }
            QLineEdit:focus { border: 1.5px solid #E879F9; }
        """)
        self.search_edit.textChanged.connect(self._schedule_search)
        top_h.addWidget(self.search_edit, stretch=1)

        btn_close = QPushButton()
        btn_close.setIcon(QIcon(str(ASSETS_DIR / "gemini_close.svg")))
        btn_close.setIconSize(QSize(16, 16))
        btn_close.setFixedSize(24, 24)
        btn_close.setStyleSheet("background: transparent; color: #C084FC; font-weight: bold; border: none;")
        btn_close.clicked.connect(lambda: self.setVisible(False))
        top_h.addWidget(btn_close)
        self.layout_v.addLayout(top_h)

        # 3-Tab CelMoji View (Emojis, Kaomoji, Emoticons)
        self.tabw = QTabWidget()
        self.tabw.setStyleSheet("""
            QTabWidget::pane {
                background: rgba(12, 8, 22, 0.72);
                border: 1px solid rgba(168, 85, 247, 0.35);
                border-radius: 10px;
            }
            QTabBar::tab {
                background: rgba(255, 255, 255, 0.05);
                color: #C4B5FD;
                border: 1px solid rgba(168, 85, 247, 0.22);
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: bold;
                margin-right: 3px;
            }
            QTabBar::tab:selected {
                background: rgba(147, 51, 234, 0.65);
                color: #FFFFFF;
                border: 1px solid #E879F9;
            }
            QTabBar::tab:hover:!selected {
                background: rgba(147, 51, 234, 0.30);
                color: #F8F4FF;
            }
        """)
        self.layout_v.addWidget(self.tabw, stretch=1)

        self._order = ["emoji", "kaomoji", "emoticons"]
        self._titles = {"emoji": "😀 Emojis", "kaomoji": "✨ Kaomoji", "emoticons": "⌨ Emoticons"}
        self.lists = {}
        self.models = {}
        pts = {"emoji": (20, 38), "kaomoji": (13, 34), "emoticons": (14, 34)}

        for key in self._order:
            lw = QListView()
            lw.setViewMode(QListView.ViewMode.ListMode)
            lw.setUniformItemSizes(True)
            lw.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            lw.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            lw.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            lw.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            lw.setMouseTracking(True)
            lw.setStyleSheet("""
                QListView { background: transparent; border: none; outline: none; color: #F8F4FF; }
                QScrollBar:vertical { background: transparent; width: 6px; margin: 2px 0px; }
                QScrollBar::handle:vertical { background: rgba(168, 85, 247, 0.4); border-radius: 3px; min-height: 24px; }
                QScrollBar::handle:vertical:hover { background: rgba(232, 121, 249, 0.7); }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
            """)
            
            model = _CelMojiListModel(lw)
            ep, rh = pts[key]
            lw.setItemDelegate(_CelMojiRowDelegate(self, emoji_pt=ep, row_h=rh, kw_pt=10, parent=lw))
            lw.setModel(model)
            lw.clicked.connect(self._on_item_clicked)
            lw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            lw.customContextMenuRequested.connect(lambda pos, k=key: self._on_context_menu(k, pos))
            
            self.tabw.addTab(lw, self._titles[key])
            self.lists[key] = lw
            self.models[key] = model

        self.tabw.currentChanged.connect(self._on_tab_changed)

        # Action & Status Footer
        foot_h = QHBoxLayout()
        foot_h.setSpacing(5)
        self.lbl_status = QLabel("★ 0 recent")
        self.lbl_status.setStyleSheet("color: #A78BFA; font-size: 10px; border: none; background: transparent;")
        foot_h.addWidget(self.lbl_status, stretch=1)

        btn_qss = """
            QPushButton {
                background: rgba(147, 51, 234, 0.25);
                color: #E9D5FF;
                border: 1px solid rgba(192, 132, 252, 0.45);
                border-radius: 7px;
                padding: 3px 8px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.60); color: #FFFFFF; border-color: #E879F9; }
        """
        for label, tip, slot in (
            ("⏎ Use", "Insert selected item(s) into chat", self._use_selected),
            ("📋 Copy", "Copy selected item(s) to clipboard", self._copy_selected),
            ("📌 Pin", "Pin / unpin selected item to top", self._pin_selected),
            ("🏷️ Tags", "Edit custom search keywords for selected item", self._edit_tags_dialog),
            ("➕ Custom", "Add a custom Kaomoji", self.add_custom_kaomoji),
        ):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(btn_qss)
            b.clicked.connect(slot)
            foot_h.addWidget(b)

        self.layout_v.addLayout(foot_h)

        # Fallback seed lists (merged with CelMoji CSV/TXT files if present on disk)
        self.emojis = [
            ("😀", "grinning face smile happy"), ("😃", "grinning face big eyes smile happy"),
            ("😄", "grinning face smiling eyes happy"), ("😁", "beaming face smiling eyes happy"),
            ("😆", "grinning squinting face happy laugh"), ("😅", "grinning face sweat smile nervous"),
            ("😂", "face tears joy laugh lol"), ("🤣", "rolling floor laughing rofl lol"),
            ("😊", "smiling face smiling eyes happy blush"), ("😇", "smiling face halo angel innocent"),
            ("🙂", "slightly smiling face happy"), ("😉", "winking face wink flirt"),
            ("😍", "smiling heart eyes love"), ("🥰", "smiling hearts love"),
            ("😘", "face blowing kiss love"), ("😋", "face savoring food yummy"),
            ("😜", "winking tongue playful"), ("🤪", "zany face crazy goofy"),
            ("🤗", "hugging face hug"), ("🤭", "hand over mouth giggle shy"),
            ("🤫", "shushing face quiet secret"), ("🤔", "thinking face hmm ponder"),
            ("🤨", "raised eyebrow skeptical"), ("😐", "neutral face meh"),
            ("😏", "smirk face smug"), ("😒", "unamused face meh"),
            ("🙄", "face rolling eyes whatever"), ("😬", "grimacing face awkward"),
            ("😌", "relieved face phew"), ("😔", "pensive face sad"),
            ("😴", "sleeping face zzz tired"), ("🥵", "hot face heat sweat"),
            ("🥶", "cold face freeze shiver"), ("🤯", "exploding head mind blown"),
            ("🥳", "partying face celebration"), ("😎", "smiling sunglasses cool"),
            ("🤓", "nerd face geek"), ("🧐", "monocle face fancy"),
            ("😳", "flushed face embarrassed blush"), ("🥺", "pleading face puppy eyes"),
            ("😢", "crying face sad tears"), ("😭", "loudly crying face bawl sob"),
            ("😱", "screaming fear shock"), ("😤", "steam nose angry mad"),
            ("😡", "pouting face angry mad"), ("💀", "skull dead death lol"),
            ("👻", "ghost halloween spooky"), ("🤖", "robot face ai"),
            ("👍", "thumbs up like good"), ("👎", "thumbs down dislike"),
            ("👏", "clapping hands applause"), ("🙏", "folded hands please thank you pray"),
            ("🤝", "handshake deal"), ("✨", "sparkles magic clean"),
            ("🔥", "fire hot lit flame"), ("🚀", "rocket launch space fast"),
            ("💖", "sparkling heart love"), ("💜", "purple heart cellium love"),
            ("❤️", "red heart love"), ("💯", "hundred perfect score"),
            ("🎉", "party popper celebration"), ("⭐", "star favorite"),
            ("💡", "light bulb idea"), ("🧠", "brain smart think"),
            ("🫠", "melting face hot"), ("🫣", "peeking eye shy"),
            ("🫡", "saluting face respect"), ("🫦", "biting lip flirt"),
            ("🫶", "heart hands love"), ("🥹", "holding back tears proud"),
        ]
        self.kaomojis = [
            ("≽^•⩊•^≼", "cat happy cute"), ("(˶˃ᆺ˂˶)", "blush shy cute"),
            ("(｡♥‿♥｡)", "love heart eyes cute"), ("(๑>ᴗ<๑)", "happy cute smile"),
            ("٩(ˊᗜˋ*)و", "excited yay arms up"), ("(/ =ω=)/", "confused shrug"),
            ("(◕‿◕)", "sparkle eyes cute"), ("(>‿<)", "happy grin"),
            ("( ˘ ³˘)♥", "kiss love"), ("(✿◠‿◠)", "flower happy"),
            ("ಠ_ಠ", "disapproval stare"), ("(づ｡◕‿‿◕｡)づ", "hug love"),
            ("(ノಠ益ಠ)ノ彡┻━┻", "flip table angry rage"), ("(⊙_⊙)", "surprised shock"),
            ("¯\\_(ツ)_/¯", "shrug whatever"), ("(¬‿¬)", "smirk sly"),
            ("(╥﹏╥)", "cry sad tears"), ("(≧◡≦)", "happy joy"),
            ("(ง'̀-'́)ง", "fight determined"), ("(⁄ ⁄•⁄ω⁄•⁄ ⁄)", "blush shy"),
            ("(｡•̀ᴗ-)✧", "wink star"), ("(๑•̀ㅂ•́)و✧", "determined sparkle"),
        ]
        self.emoticons = [
            (":)", "smile happy"), (":-)", "smile happy"), (":D", "grin big smile"),
            ("xD", "laughing squinting"), (";)", "wink"), (":P", "tongue playful"),
            (":3", "cute cat smile"), (">:3", "mischievous cute"), ("<3", "heart love"),
            ("</3", "broken heart"), (":(", "sad frown"), (":'(", "crying tears"),
            (":O", "surprised shock"), ("-_-", "unamused tired"), ("o_O", "confused"),
            ("^_^", "happy anime smile"), ("T_T", "crying tears"), ("uwu", "cute happy"),
            ("owo", "surprised cute"),
        ]

        self._wire_keyboard_nav()
        self._reload_all_datasets()
        self._rebuild_current()

    # ── Storage & CelMoji Sync ──────────────────────────────────────────
    def _emj_store(self):
        st = getattr(self, "settings", None)
        if isinstance(st, dict):
            try:
                cur = getattr(self.window(), "settings", None)
            except Exception:
                cur = None
            if isinstance(cur, dict) and cur is not st:
                st = self.settings = cur
            return st
        return self._emj_mem

    def _emj_frec(self) -> dict:
        d = dict(self._emj_store().get("emoji_frec", {}) or {})
        frec_file = self._celmoji_data_dir / "frecency.json"
        if frec_file.is_file():
            try:
                ext = json.loads(frec_file.read_text(encoding="utf-8"))
                if isinstance(ext, dict):
                    for k, v in ext.items():
                        if k not in d or (isinstance(v, dict) and v.get("t", 0) > d.get(k, {}).get("t", 0)):
                            d[k] = v
            except Exception:
                pass
        return d

    def _emj_pins(self) -> list[str]:
        pins = list(self._emj_store().get("emoji_pins", []) or [])
        pins_file = self._celmoji_data_dir / "pins.json"
        if pins_file.is_file():
            try:
                ext = json.loads(pins_file.read_text(encoding="utf-8"))
                if isinstance(ext, list):
                    for p in ext:
                        if isinstance(p, str) and p not in pins:
                            pins.append(p)
            except Exception:
                pass
        self._pin_set = set(pins)
        return pins

    def _emj_bans(self) -> set[str]:
        bans = set(self._emj_store().get("emoji_bans", []) or [])
        bans_file = self._celmoji_data_dir / "bans.json"
        if bans_file.is_file():
            try:
                ext = json.loads(bans_file.read_text(encoding="utf-8"))
                if isinstance(ext, list):
                    bans.update(x for x in ext if isinstance(x, str))
            except Exception:
                pass
        return bans

    def _emj_tags(self) -> dict:
        tags = dict(self._emj_store().get("emoji_tags", {}) or {})
        tags_file = self._celmoji_data_dir / "tags.json"
        if tags_file.is_file():
            try:
                ext = json.loads(tags_file.read_text(encoding="utf-8"))
                if isinstance(ext, dict):
                    tags.update(ext)
            except Exception:
                pass
        return tags

    def _emj_save(self):
        try:
            store = self._emj_store()
            if store is not self._emj_mem:
                save_json(F_SETTINGS, store)
            if self._celmoji_data_dir.is_dir():
                if "emoji_pins" in store:
                    (self._celmoji_data_dir / "pins.json").write_text(
                        json.dumps(store["emoji_pins"], ensure_ascii=False), encoding="utf-8"
                    )
                if "emoji_bans" in store:
                    (self._celmoji_data_dir / "bans.json").write_text(
                        json.dumps(store["emoji_bans"], ensure_ascii=False), encoding="utf-8"
                    )
                if "emoji_frec" in store:
                    (self._celmoji_data_dir / "frecency.json").write_text(
                        json.dumps(store["emoji_frec"], ensure_ascii=False), encoding="utf-8"
                    )
                if "emoji_tags" in store:
                    (self._celmoji_data_dir / "tags.json").write_text(
                        json.dumps(store["emoji_tags"], ensure_ascii=False, indent=1), encoding="utf-8"
                    )
        except Exception:
            pass

    def _reload_all_datasets(self):
        """Load CelMoji sets once into class cache and build a cheap per-instance
        display list. The old version deep-copied 105,580 keyword lists and
        sorted them all - measured at **4.7 s** per picker. Now the raw parse
        happens once per process and each open only shallow-copies tuple refs.
        """
        if EmojiPickerWidget._CACHED_RAW_TABS is None:
            EmojiPickerWidget._CACHED_RAW_TABS = self._load_raw_datasets_once()
        raw = EmojiPickerWidget._CACHED_RAW_TABS
        EmojiPickerWidget._ensure_class_caches(raw)
        self._raw_tabs = raw

        store = self._emj_store()
        custom_tags = self._emj_tags()
        bans = self._emj_bans()
        custom_kao = [
            c.strip() for c in (store.get("custom_kaomojis", []) or [])
            if isinstance(c, str) and c.strip()
        ]

        tabs = {}
        self._haystacks = {}
        for key, mapping in raw.items():
            if key == "kaomoji":
                lst = list(mapping.items())
                for ck in custom_kao:
                    if ck not in mapping:
                        lst.append((ck, ["custom", "user", "kaomoji"]))
            else:
                lst = list(mapping.items())

            if custom_tags or bans or key == "kaomoji":
                out = []
                hay = []
                for it, kw in lst:
                    if it in bans:
                        continue
                    v = custom_tags.get(it)
                    if isinstance(v, dict):
                        hide = set(v.get("hide", []))
                        add = [t for t in v.get("add", []) if t not in kw]
                        kw = [w for w in kw if w not in hide] + add
                    elif isinstance(v, list):
                        kw = list(kw) + [t for t in v if t not in kw]
                    out.append((it, kw))
                    hay.append((str(it) + " " + " ".join(kw)).lower())
                tabs[key] = out
                self._haystacks[key] = hay
            else:
                tabs[key] = lst
                # Share the class-level haystack; it is aligned with the raw
                # mapping order and immutable.
                self._haystacks[key] = None
        self._finalize_tabs_with_frecency(tabs)

    @classmethod
    def _ensure_class_caches(cls, raw=None):
        """Build the immutable item + search-haystack lists once per process."""
        if cls._CACHED_ITEMS is not None and cls._CACHED_HAY is not None:
            return
        raw = raw if raw is not None else cls._CACHED_RAW_TABS
        if not raw:
            return
        items, hay = {}, {}
        for key, mapping in raw.items():
            lst = list(mapping.items())
            items[key] = lst
            hay[key] = [(str(it) + " " + " ".join(kw)).lower() for it, kw in lst]
        cls._CACHED_ITEMS = items
        cls._CACHED_HAY = hay

    def _schedule_search(self, _text: str = "") -> None:
        """Debounce the 105k-row search so typing never blocks the UI."""
        timer = getattr(self, "_search_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(120)
            timer.timeout.connect(
                lambda: self.filter_items(self.search_edit.text()))
            self._search_timer = timer
        timer.start()

    @staticmethod
    def _parse_celmoji_line(line: str):
        line = line.rstrip("\n")
        if not line or line.startswith("#"):
            return None
        line = re.sub(r"<[^>]*>", " ", line)
        line = line.replace("(", " ").replace(")", " ").replace(",", " ")
        line = " ".join(line.split())
        if "\t" in line:
            item, rest = line.split("\t", 1)
            return item.strip(), rest.split()
        parts = line.split(None, 1)
        if not parts:
            return None
        return (parts[0], parts[1].split() if len(parts) > 1 else [])

    @classmethod
    def _load_celmoji_file(cls, path: Path) -> list[tuple[str, list[str]]]:
        out = []
        if not path.is_file():
            return out
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for ln in f:
                    r = cls._parse_celmoji_line(ln)
                    if r and r[0]:
                        out.append(r)
        except OSError:
            pass
        return out

    _CACHED_RAW_TABS = None
    _CACHED_ITEMS = None
    _CACHED_HAY = None
    #: Bump when the parsing rules or built-in fallback lists change so stale
    #: on-disk caches are ignored.
    _RAW_CACHE_VERSION = 7

    def _raw_dataset_signature(self):
        """Cheap fingerprint of every CelMoji source file (name/mtime/size)."""
        sig = [self._RAW_CACHE_VERSION, len(self.emojis),
               len(self.kaomojis), len(self.emoticons)]
        for sdir in (self._celmoji_dir / "sets",
                     self._celmoji_data_dir / "sets",
                     Path.home() / ".local" / "share" / "rofimoji" / "data"):
            if not sdir.is_dir():
                continue
            for p in sorted(sdir.glob("*.csv")):
                try:
                    st = p.stat()
                    sig.append((p.name, int(st.st_mtime_ns), st.st_size))
                except OSError:
                    pass
        for p in (self._celmoji_data_dir / "kaomoji.txt",
                  self._celmoji_dir / "kaomoji.txt",
                  self._celmoji_data_dir / "emoticons.txt",
                  self._celmoji_dir / "emoticons.txt"):
            try:
                st = p.stat()
                sig.append((p.name, int(st.st_mtime_ns), st.st_size))
            except OSError:
                pass
        return sig

    def _load_raw_datasets_once(self) -> dict:
        """Return the merged CelMoji datasets, using a disk cache when fresh.

        First run parses ~375k lines (multi-second); afterwards the parsed
        tabs come back as a pickle in ~100 ms. The cache is keyed on source
        file name/mtime/size, so editing a set or upgrading CelMoji rebuilds
        it automatically.
        """
        import pickle
        cache_path = self._celmoji_data_dir / "raw_tabs_cache.pkl"
        signature = self._raw_dataset_signature()
        try:
            blob = pickle.loads(cache_path.read_bytes())
            if (blob.get("version") == self._RAW_CACHE_VERSION
                    and blob.get("sig") == signature):
                return blob["tabs"]
        except Exception:
            pass
        tabs = self._build_raw_datasets()
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(pickle.dumps(
                {"version": self._RAW_CACHE_VERSION,
                 "sig": signature,
                 "tabs": tabs},
                protocol=pickle.HIGHEST_PROTOCOL))
        except Exception:
            pass
        return tabs

    def _build_raw_datasets(self) -> dict:
        blessed_first = [
            "emojis_smileys_emotion", "emojis_people_body", "emojis_animals_nature",
            "emojis_food_drink", "emojis_activities", "emojis_travel_places",
            "emojis_objects", "emojis_symbols", "emojis_flags", "gitmoji",
        ]
        merged_em = {}
        sets_dirs = [
            self._celmoji_dir / "sets",
            self._celmoji_data_dir / "sets",
            Path.home() / ".local" / "share" / "rofimoji" / "data",
        ]
        for sdir in sets_dirs:
            if sdir.is_dir():
                csv_map = {p.stem: p for p in sorted(sdir.glob("*.csv"))}
                ordered_paths = [csv_map[n] for n in blessed_first if n in csv_map]
                ordered_paths += [p for k, p in sorted(csv_map.items()) if k not in blessed_first]
                for cp in ordered_paths:
                    for item, kw in self._load_celmoji_file(cp):
                        if item in merged_em:
                            merged_em[item].extend(w for w in kw if w not in merged_em[item])
                        else:
                            merged_em[item] = list(kw)

        for emo, kw_str in self.emojis:
            kw = kw_str.split()
            if emo in merged_em:
                merged_em[emo].extend(w for w in kw if w not in merged_em[emo])
            else:
                merged_em[emo] = kw

        if len(merged_em) < 300:
            try:
                import emoji as _emoji_pkg
                for em_ch, meta in list(_emoji_pkg.EMOJI_DATA.items())[:800]:
                    if em_ch not in merged_em and len(em_ch) <= 2:
                        en_name = str(meta.get("en", "")).strip(":").replace("_", " ")
                        if en_name:
                            merged_em[em_ch] = en_name.split()
            except Exception:
                pass

        kao_list = (
            self._load_celmoji_file(self._celmoji_data_dir / "kaomoji.txt")
            or self._load_celmoji_file(self._celmoji_dir / "kaomoji.txt")
        )
        merged_kao = {}
        for item, kw in kao_list:
            merged_kao[item] = list(dict.fromkeys(kw))
        for item, kw_str in self.kaomojis:
            if item != "+ Add Custom":
                merged_kao.setdefault(item, kw_str.split())
        for c_kao in self._emj_store().get("custom_kaomojis", []) or []:
            if isinstance(c_kao, str) and c_kao.strip():
                merged_kao[c_kao.strip()] = ["custom", "user", "kaomoji"]

        emo_list = (
            self._load_celmoji_file(self._celmoji_data_dir / "emoticons.txt")
            or self._load_celmoji_file(self._celmoji_dir / "emoticons.txt")
        )
        merged_emot = {}
        for item, kw in emo_list:
            merged_emot[item] = list(dict.fromkeys(kw))
        for item, kw_str in self.emoticons:
            merged_emot.setdefault(item, kw_str.split())

        return {
            "emoji": merged_em,
            "kaomoji": merged_kao,
            "emoticons": merged_emot,
        }

    def _finalize_tabs_with_frecency(self, tabs: dict):
        """Order pins/recent items without sorting all 105k rows.

        The old implementation ran ``list.sort(key=score)`` over the entire
        emoji catalogue (731 ms) even though only a handful of items have a
        frecency score. Now we pull the scored items out (O(n)), sort just
        those, and keep the rest in source order.
        """
        now = time.time()
        frec = self._emj_frec()
        pins = self._emj_pins()
        pin_set = set(pins)
        self._pin_set = pin_set
        # Canonical (source) order is what the search haystacks align with.
        self._canonical = {k: list(v) for k, v in tabs.items()}

        for key, tab in tabs.items():
            scored = []
            if frec:
                scored = [(it, kw) for it, kw in tab if it in frec]
                scored.sort(
                    key=lambda kv: self._emj_score(frec.get(kv[0]), now),
                    reverse=True)
            scored_items = {it for it, _ in scored}
            by_item = dict(tab)
            top = [(p, by_item[p]) for p in pins if p in by_item]
            rest = [(it, kw) for it, kw in tab
                    if it not in pin_set and it not in scored_items]
            tabs[key] = top + ([(self.DIVIDER, [])] if top else []) + scored + rest
            idx = self._order.index(key)
            self.tabw.setTabText(idx, f"{self._titles[key]} ({len(tab)})")

        self._all_data = tabs
        self._all_model_items = {}
        self._haystacks = {}
        pin_set = self._pin_set
        for k, tab in tabs.items():
            items = []
            hay = []
            for it, kw in tab:
                is_div = (it == self.DIVIDER)
                is_pin = (it in pin_set)
                kw_str = " ".join(kw) if isinstance(kw, (list, tuple)) else str(kw)
                items.append((it, kw_str, is_pin, is_div))
                hay.append((str(it) + " " + kw_str).lower())
            self._all_model_items[k] = items
            self._haystacks[k] = hay
        self._display = {k: list(v) for k, v in self._all_model_items.items()}
        self._built.clear()
        self._last_filter.clear()

    @staticmethod
    def _emj_score(entry, now: float) -> tuple[float, float]:
        try:
            e = entry or {}
            age_h = max(0.0, (now - float(e.get("t", 0))) / 3600.0)
            return (float(e.get("n", 0)) / (1.0 + age_h / 24.0), float(e.get("t", 0)))
        except (TypeError, ValueError):
            return (0.0, 0.0)

    def _current_key(self) -> str:
        return self._order[self.tabw.currentIndex()]

    def _current_list(self):
        return self.lists[self._current_key()]

    def _ensure_built(self, key: str):
        if key in self._built:
            return
        self._display.setdefault(key, list(self._all_model_items.get(key, [])))
        self._built.add(key)

    def _rebuild_current(self):
        key = self._current_key()
        self._ensure_built(key)
        self.filter_items(self.search_edit.text())

    def filter_items(self, text: str = ""):
        key = self._current_key()
        self._ensure_built(key)
        words = (text or "").lower().split()
        self._last_filter[key] = text or ""
        all_model_items = self._all_model_items.get(key, [])
        if not words:
            filtered = all_model_items
        else:
            hay = self._haystacks.get(key)
            if not hay:
                hay = [(str(it) + " " + kw).lower() for it, kw, _p, _d in all_model_items]
                self._haystacks[key] = hay
            if len(words) == 1:
                w = words[0]
                filtered = [
                    all_model_items[i] for i, h in enumerate(hay)
                    if w in h and i < len(all_model_items)
                ]
            else:
                filtered = [
                    all_model_items[i] for i, h in enumerate(hay)
                    if i < len(all_model_items) and all(w in h for w in words)
                ]

        self.models[key].set_items(filtered)
        lw = self.lists[key]
        if filtered:
            lw.setCurrentIndex(self.models[key].index(0, 0))
        n_recent = len(self._emj_frec())
        self.lbl_status.setText(f"★ {n_recent} recent · {len(filtered)} shown")

    def _on_tab_changed(self, _idx: int):
        self._rebuild_current()
        self.search_edit.setFocus()

    def _on_item_clicked(self, index):
        txt = index.data(Qt.ItemDataRole.UserRole) if index.isValid() else None
        if txt and txt != self.DIVIDER:
            self._choose(txt)

    def _picked_items(self) -> list[str]:
        lw = self._current_list()
        indexes = sorted(lw.selectionModel().selectedIndexes(), key=lambda i: i.row())
        out = []
        for idx in indexes:
            t = idx.data(Qt.ItemDataRole.UserRole)
            if t and t != self.DIVIDER:
                out.append(t)
        if not out:
            cur = lw.currentIndex()
            if cur.isValid():
                t = cur.data(Qt.ItemDataRole.UserRole)
                if t and t != self.DIVIDER:
                    out.append(t)
        return out

    def _choose(self, item: str):
        if not item or item == self.DIVIDER:
            return
        try:
            store = self._emj_store()
            frec = self._emj_frec()
            e = dict(frec.get(item, {}) or {})
            e["n"] = int(e.get("n", 0) or 0) + 1
            e["t"] = time.time()
            frec[item] = e
            store["emoji_frec"] = frec
            self._emj_save()
        except Exception:
            pass
        try:
            self.emoji_selected.emit(item)
        except Exception:
            pass

    def _use_selected(self):
        for t in self._picked_items():
            self._choose(t)

    def _copy_selected(self):
        picks = self._picked_items()
        if not picks:
            return
        blob = "".join(picks)
        QApplication.clipboard().setText(blob)
        mw = self.window()
        if hasattr(mw, "show_toast"):
            mw.show_toast(f"Copied: {blob}", icon="📋")

    def _toggle_pin(self, item: str):
        store = self._emj_store()
        pins = self._emj_pins()
        if item in pins:
            pins = [p for p in pins if p != item]
        else:
            pins = [item] + [p for p in pins if p != item]
        store["emoji_pins"] = pins
        self._pin_set = set(pins)
        self._emj_save()
        self._reload_all_datasets()
        self._rebuild_current()

    def _pin_selected(self):
        picks = self._picked_items()
        if picks:
            self._toggle_pin(picks[0])

    def _ban_item(self, item: str):
        store = self._emj_store()
        bans = self._emj_bans()
        bans.add(item)
        store["emoji_bans"] = sorted(bans)
        self._emj_save()
        self._reload_all_datasets()
        self._rebuild_current()

    def _edit_tags_dialog(self, target_item: str | None = None):
        item = target_item if isinstance(target_item, str) and target_item else (self._picked_items() or [None])[0]
        if not item:
            return
        tags = self._emj_tags()
        v = tags.get(item, [])
        add = v.get("add", []) if isinstance(v, dict) else list(v)
        hide = set(v.get("hide", []) if isinstance(v, dict) else [])
        raw = self._raw_tabs.get(self._current_key(), {}).get(item, [])
        shown_now = [k for k in raw if k not in hide] + [t for t in add if t not in raw]

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Edit tags for {item}")
        dlg.setStyleSheet("QDialog { background: #120B22; color: #F8F4FF; } QLabel { color: #E9D5FF; }")
        dlay = QVBoxLayout(dlg)
        big = QLabel(item)
        bf = big.font()
        bf.setPointSize(32)
        big.setFont(bf)
        big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dlay.addWidget(big)
        hint = QLabel("Space-separated search keywords (add, edit, or remove words):")
        hint.setWordWrap(True)
        dlay.addWidget(hint)
        field = QLineEdit(" ".join(shown_now))
        field.setStyleSheet("background: #1A1030; color: #F8F4FF; border: 1.5px solid #9333EA; border-radius: 8px; padding: 6px;")
        dlay.addWidget(field)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dlay.addWidget(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        words = field.text().split()
        add_new = [w for w in words if w not in raw]
        hide_new = [w for w in raw if w not in words]
        if add_new or hide_new:
            tags[item] = {"add": add_new, "hide": hide_new}
        else:
            tags.pop(item, None)
        self._emj_store()["emoji_tags"] = tags
        self._emj_save()
        self._reload_all_datasets()
        self._rebuild_current()

    def _on_context_menu(self, key: str, pos):
        lw = self.lists[key]
        idx = lw.indexAt(pos)
        item = idx.data(Qt.ItemDataRole.UserRole) if idx.isValid() else None
        if not item or item == self.DIVIDER:
            return
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #160E2A; color: #F8F4FF; border: 1.5px solid #9333EA; border-radius: 8px; padding: 4px; }
            QMenu::item { padding: 6px 14px; border-radius: 5px; }
            QMenu::item:selected { background: rgba(147, 51, 234, 0.55); }
        """)
        pinned = item in self._pin_set
        a_use = menu.addAction(f"⏎ Insert {item}")
        a_copy = menu.addAction("📋 Copy to clipboard")
        a_pin = menu.addAction("📌 Unpin" if pinned else "📌 Pin to top")
        a_tags = menu.addAction("🏷️ Edit search tags…")
        a_ban = menu.addAction("🚫 Hide / Ban this item")
        a_unban = menu.addAction("♻️ Unhide all banned items") if self._emj_bans() else None
        chosen = menu.exec(lw.mapToGlobal(pos))
        if chosen == a_use:
            self._choose(item)
        elif chosen == a_copy:
            QApplication.clipboard().setText(item)
        elif chosen == a_pin:
            self._toggle_pin(item)
        elif chosen == a_tags:
            self._edit_tags_dialog(item)
        elif chosen == a_ban:
            self._ban_item(item)
        elif a_unban is not None and chosen == a_unban:
            self._emj_store()["emoji_bans"] = []
            self._emj_save()
            self._reload_all_datasets()
            self._rebuild_current()

    def _wire_keyboard_nav(self):
        orig_search_key = self.search_edit.keyPressEvent

        def _search_key(ev):
            if ev.key() == Qt.Key.Key_Down:
                lw = self._current_list()
                m = self.models.get(self._current_key())
                if m and m.rowCount() > 0:
                    lw.setFocus()
                    lw.setCurrentIndex(m.index(0, 0))
                    return
            elif ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._use_selected()
                return
            orig_search_key(ev)

        self.search_edit.keyPressEvent = _search_key

        for lw in self.lists.values():
            orig_lw_key = lw.keyPressEvent

            def _lw_key(ev, _lw=lw, _orig=orig_lw_key):
                if ev.key() == Qt.Key.Key_Up and _lw.currentIndex().row() <= 0:
                    self.search_edit.setFocus()
                    return
                if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._use_selected()
                    return
                if ev.modifiers() == Qt.KeyboardModifier.ControlModifier:
                    if ev.key() == Qt.Key.Key_P:
                        self._pin_selected()
                        return
                    if ev.key() == Qt.Key.Key_E:
                        self._edit_tags_dialog()
                        return
                _orig(ev)

            lw.keyPressEvent = _lw_key

    def add_custom_kaomoji(self):
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Add Custom Kaomoji", "Enter your kaomoji:", text="(◕‿◕)")
        if ok and text.strip():
            store = self._emj_store()
            custom = list(store.get("custom_kaomojis", []) or [])
            if text.strip() not in custom:
                custom.append(text.strip())
            store["custom_kaomojis"] = custom
            self._emj_save()
            self._reload_all_datasets()
            self.tabw.setCurrentIndex(1)
            self._rebuild_current()

    def switch_tab(self, idx: int):
        if 0 <= idx < self.tabw.count():
            self.tabw.setCurrentIndex(idx)

    def populate_emojis(self):
        self._rebuild_current()

    def populate_kaomojis(self):
        self._rebuild_current()

    def _show_all_items(self):
        self.search_edit.clear()
        self._rebuild_current()

EmojiPickerWidgetNew = EmojiPickerWidget

# ------------------------------------------------------------------ Floating Glass Toast
class ModelManagerWidget(QWidget):
    back_to_chat = Signal()
    model_selected = Signal(str)
    keys_updated = Signal()

    def __init__(self, settings, providers, models, chat_app=None, parent=None):
        super().__init__(parent)
        self.settings = dict(settings)
        self.providers = dict(providers)
        self.models = dict(models)
        self.chat_app = chat_app
        self.ping_status = {}
        self.ping_worker = None
        self.fetch_worker = None
        self.view_mode = "key_selected"  # "key_selected" or "all_models"
        self.init_ui()
        _theme_sliders(self)

    def _disable_combo_wheel(self, combo, enabled=True):
        """Prevent mouse wheel from changing combo/spinbox value unless focused.

        Delegates to the module-level :func:`_lock_wheel`, which actually
        consumes the event instead of letting it scroll the page behind.
        """
        _lock_wheel(combo, enabled)

    def _apply_combo_wheel_setting(self, widget):
        if get_disable_combo_wheel(self.settings):
            self._disable_combo_wheel(widget, True)

    def init_ui(self):
        # Root layout with top header and a master scroll area so the screen NEVER squishes
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 12, 16, 12)
        root_layout.setSpacing(10)

        hdr = QHBoxLayout()
        btn_back = QPushButton("← Back to Chat")
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.setStyleSheet("""
            QPushButton {
                background: #33363D;
                color: #FFFFFF; border: 1.5px solid #F87171; border-radius: 10px;
                padding: 7px 18px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: #DC2626; border-color: #FCA5A5; }
        """)
        btn_back.clicked.connect(self.back_to_chat.emit)
        hdr.addWidget(btn_back)

        title_lbl = QLabel("🎛️ Model Hub & API Provider Manager")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #F8F4FF; border: none;")
        hdr.addWidget(title_lbl)
        hdr.addStretch()

        self.btn_ping_all = QPushButton("⚡ Ping Active Models")
        self.btn_ping_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ping_all.setStyleSheet("""
            QPushButton {
                background: rgba(147, 51, 234, 0.45); color: #E9D5FF;
                border: 1.5px solid #C084FC; border-radius: 10px; padding: 7px 16px;
                font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: #9333EA; color: #FFFFFF; }
        """)
        self.btn_ping_all.clicked.connect(self.start_ping_all)
        hdr.addWidget(self.btn_ping_all)

        root_layout.addLayout(hdr)

        # Master Scroll Area wrapping ALL panels to prevent any clipping on smaller viewports
        self.master_scroll = QScrollArea()
        self.master_scroll.setWidgetResizable(True)
        self.master_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.master_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.master_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: rgba(15, 10, 25, 0.4);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(168, 85, 247, 0.5);
                min-height: 25px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #A855F7;
            }
        """)
        self.master_scroll.verticalScrollBar().valueChanged.connect(lambda _: self.master_scroll.viewport().update())

        self.scroll_content = QWidget()
        self.scroll_content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.scroll_content.setStyleSheet("background: transparent;")
        self.main_layout = QVBoxLayout(self.scroll_content)
        self.main_layout.setContentsMargins(0, 0, 8, 0)
        self.main_layout.setSpacing(12)

        # ==========================================
        # Panel 1: Provider Config & API Key Panel
        # ==========================================
        prov_panel = GlassPanel(radius=14)
        p_form = QGridLayout(prov_panel)
        p_form.setContentsMargins(14, 12, 14, 12)
        p_form.setSpacing(8)

        lbl_p = QLabel("Provider:")
        lbl_p.setStyleSheet("border: none; color: #F8F4FF; font-weight: bold;")
        self.combo_prov = QComboBox()
        self._apply_combo_wheel_setting(self.combo_prov)
        self.combo_prov.addItems(list(PROVIDER_DEFS.keys()))
        self.combo_prov.setStyleSheet("""
            QComboBox {
                background: rgba(14, 10, 24, 0.85); color: #F8F4FF;
                border: 1.5px solid #9333EA; border-radius: 8px; padding: 6px 10px; font-size: 11px;
            }
            QComboBox:focus { border: 1.5px solid #E879F9; }
        """)
        self.combo_prov.currentTextChanged.connect(self.on_prov_selected)
        p_form.addWidget(lbl_p, 0, 0)
        p_form.addWidget(self.combo_prov, 0, 1)

        self.btn_fetch_models = QPushButton("🔄 Refresh Model List")
        self.btn_fetch_models.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fetch_models.setToolTip("Query cloud API to check for newest models.")
        self.btn_fetch_models.setStyleSheet("""
            QPushButton {
                background: rgba(59, 130, 246, 0.3); color: #93C5FD;
                border: 1.5px solid #60A5FA; border-radius: 8px; padding: 6px 14px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #2563EB; color: white; }
        """)
        self.btn_fetch_models.clicked.connect(self.fetch_live_models)
        p_form.addWidget(self.btn_fetch_models, 0, 2)

        lbl_k = QLabel("API Key:")
        lbl_k.setStyleSheet("border: none; color: #F8F4FF; font-weight: bold;")
        self.edit_key = QLineEdit()
        self.edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_key.setPlaceholderText("Enter API Key (stored securely locally)...")
        self.edit_key.setStyleSheet("""
            QLineEdit {
                background: rgba(14, 10, 24, 0.85); color: #F8F4FF;
                border: 1.5px solid #9333EA; border-radius: 8px; padding: 6px 10px; font-size: 11px;
            }
            QLineEdit:focus { border: 1.5px solid #E879F9; }
        """)
        p_form.addWidget(lbl_k, 1, 0)
        p_form.addWidget(self.edit_key, 1, 1)

        btn_save_key = QPushButton("💾 Save Key")
        btn_save_key.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save_key.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #10B981, stop:1 #059669);
                color: white; border: 1.5px solid #34D399; border-radius: 8px; padding: 6px 14px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #059669; }
        """)
        btn_save_key.clicked.connect(self.save_key)
        p_form.addWidget(btn_save_key, 1, 2)

        lbl_custom = QLabel("Custom Model:")
        lbl_custom.setStyleSheet("border: none; color: #E9D5FF; font-weight: bold; font-size: 11px;")
        self.edit_custom_model = QLineEdit()
        self.edit_custom_model.setPlaceholderText("Add ANY custom/future model ID for this provider...")
        self.edit_custom_model.setStyleSheet("""
            QLineEdit {
                background: rgba(14, 10, 24, 0.85); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.6); border-radius: 8px; padding: 5px 10px; font-size: 11px;
            }
            QLineEdit:focus { border: 1.5px solid #E879F9; }
        """)
        p_form.addWidget(lbl_custom, 2, 0)
        p_form.addWidget(self.edit_custom_model, 2, 1)

        btn_add_custom = QPushButton("➕ Add Model")
        btn_add_custom.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_custom.setStyleSheet("""
            QPushButton {
                background: rgba(168, 85, 247, 0.35); color: #F3E8FF;
                border: 1.5px solid #C084FC; border-radius: 8px; padding: 5px 12px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #9333EA; color: white; }
        """)
        btn_add_custom.clicked.connect(self.add_custom_model)
        p_form.addWidget(btn_add_custom, 2, 2)

        self.main_layout.addWidget(prov_panel)

        # ==========================================
        # Panel 2: Offline Models Manager (Multiple GGUF)
        # ==========================================
        offline_panel = GlassPanel(radius=14)
        offline_layout = QVBoxLayout(offline_panel)
        offline_layout.setContentsMargins(14, 12, 14, 12)
        offline_layout.setSpacing(8)

        off_hdr = QHBoxLayout()
        off_title = QLabel("📁 Offline Models (Multiple GGUF Files)")
        off_title.setStyleSheet("color: #4ADE80; font-weight: bold; font-size: 13px; border: none;")
        off_hdr.addWidget(off_title)
        off_hdr.addStretch()
        offline_layout.addLayout(off_hdr)

        off_input_h = QHBoxLayout()
        off_input_h.setSpacing(8)
        self.edit_offline_name = QLineEdit()
        self.edit_offline_name.setPlaceholderText("Model Display Name...")
        self.edit_offline_name.setStyleSheet("""
            QLineEdit {
                background: rgba(14, 10, 24, 0.85); color: #F8F4FF;
                border: 1.5px solid #10B981; border-radius: 8px; padding: 6px 10px; font-size: 11px;
            }
        """)
        off_input_h.addWidget(self.edit_offline_name, 1)

        self.edit_offline_path = QLineEdit()
        self.edit_offline_path.setPlaceholderText("Path to .gguf file...")
        self.edit_offline_path.setStyleSheet("""
            QLineEdit {
                background: rgba(14, 10, 24, 0.85); color: #F8F4FF;
                border: 1.5px solid #10B981; border-radius: 8px; padding: 6px 10px; font-size: 11px;
            }
        """)
        off_input_h.addWidget(self.edit_offline_path, 2)

        btn_browse_off = QPushButton("📂 Browse")
        btn_browse_off.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_browse_off.setStyleSheet("""
            QPushButton {
                background: rgba(16, 185, 129, 0.3); color: #6EE7B7;
                border: 1.5px solid #10B981; border-radius: 8px; padding: 6px 12px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #059669; color: white; }
        """)
        btn_browse_off.clicked.connect(self.browse_offline_model)
        off_input_h.addWidget(btn_browse_off)

        btn_add_off = QPushButton("➕ Add Offline Model")
        btn_add_off.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_off.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #10B981, stop:1 #059669);
                color: white; border: 1.5px solid #34D399; border-radius: 8px; padding: 6px 14px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #059669; }
        """)
        btn_add_off.clicked.connect(self.add_offline_model)
        off_input_h.addWidget(btn_add_off)
        offline_layout.addLayout(off_input_h)

        self.offline_list_layout = QVBoxLayout()
        self.offline_list_layout.setSpacing(6)
        offline_layout.addLayout(self.offline_list_layout)
        self.main_layout.addWidget(offline_panel)

        # ==========================================
        # Panel 3: Fallback Models (User Configurable)
        # ==========================================
        fb_panel = GlassPanel(radius=14)
        fb_layout = QVBoxLayout(fb_panel)
        fb_layout.setContentsMargins(14, 12, 14, 12)
        fb_layout.setSpacing(8)

        fb_hdr = QHBoxLayout()
        fb_title = QLabel("🔄 Fallback Models (Auto-switch on 429/Rate Limits)")
        fb_title.setStyleSheet("color: #38BDF8; font-weight: bold; font-size: 13px; border: none;")
        fb_hdr.addWidget(fb_title)
        fb_hdr.addStretch()
        fb_layout.addLayout(fb_hdr)

        fb_input_h = QHBoxLayout()
        fb_input_h.setSpacing(8)
        self.edit_fallback_model = QLineEdit()
        self.edit_fallback_model.setPlaceholderText("Enter model key (e.g. ⚡ gemini-3.1-flash-lite [Google Gemini])...")
        self.edit_fallback_model.setStyleSheet("""
            QLineEdit {
                background: rgba(14, 10, 24, 0.85); color: #F8F4FF;
                border: 1.5px solid #38BDF8; border-radius: 8px; padding: 6px 10px; font-size: 11px;
            }
        """)
        fb_input_h.addWidget(self.edit_fallback_model, stretch=1)

        btn_add_fb = QPushButton("➕ Add Fallback")
        btn_add_fb.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_fb.setStyleSheet("""
            QPushButton {
                background: rgba(56, 189, 248, 0.35); color: #BAE6FD;
                border: 1.5px solid #38BDF8; border-radius: 8px; padding: 6px 14px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #0284C7; color: white; }
        """)
        btn_add_fb.clicked.connect(self.add_fallback_model)
        fb_input_h.addWidget(btn_add_fb)
        fb_layout.addLayout(fb_input_h)

        self.fallback_list_layout = QVBoxLayout()
        self.fallback_list_layout.setSpacing(6)
        fb_layout.addLayout(self.fallback_list_layout)
        self.main_layout.addWidget(fb_panel)

        # ==========================================
        # Panel 4: Smart Universal Banned Models
        # ==========================================
        ban_panel = GlassPanel(radius=14)
        ban_layout = QVBoxLayout(ban_panel)
        ban_layout.setContentsMargins(14, 12, 14, 12)
        ban_layout.setSpacing(8)

        ban_hdr = QHBoxLayout()
        ban_title = QLabel("🚫 Banned Models (Smart Matching across all APIs)")
        ban_title.setStyleSheet("color: #F87171; font-weight: bold; font-size: 13px; border: none;")
        ban_hdr.addWidget(ban_title)
        ban_hdr.addStretch()
        ban_layout.addLayout(ban_hdr)

        ban_input_h = QHBoxLayout()
        ban_input_h.setSpacing(8)
        self.edit_ban_model = QLineEdit()
        self.edit_ban_model.setPlaceholderText("Ban pattern (e.g. 'chatgpt4o', 'gpt-4', 'dall-e')...")
        self.edit_ban_model.setStyleSheet("""
            QLineEdit {
                background: rgba(14, 10, 24, 0.85); color: #F8F4FF;
                border: 1.5px solid #EF4444; border-radius: 8px; padding: 6px 10px; font-size: 11px;
            }
        """)
        ban_input_h.addWidget(self.edit_ban_model, stretch=1)

        btn_add_ban = QPushButton("🚫 Ban Model")
        btn_add_ban.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_ban.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #EF4444, stop:1 #DC2626);
                color: white; border: 1.5px solid #F87171; border-radius: 8px; padding: 6px 14px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #DC2626; }
        """)
        btn_add_ban.clicked.connect(self.add_banned_model)
        ban_input_h.addWidget(btn_add_ban)
        ban_layout.addLayout(ban_input_h)

        self.banned_list_layout = QVBoxLayout()
        self.banned_list_layout.setSpacing(6)
        ban_layout.addLayout(self.banned_list_layout)
        # ban_panel added later (after available models) below

        # ==========================================
        # Panel 5: Split View Models Directory (GlassPanel)
        # ==========================================
        models_panel = GlassPanel(radius=14)
        mp_layout = QVBoxLayout(models_panel)
        mp_layout.setContentsMargins(14, 12, 14, 12)
        mp_layout.setSpacing(10)

        sec_hdr = QHBoxLayout()
        self.lbl_models_header = QLabel("⚡ Available Models Directory:")
        self.lbl_models_header.setStyleSheet("color: #C084FC; font-weight: bold; font-size: 13px; border: none; background: transparent;")
        sec_hdr.addWidget(self.lbl_models_header)
        sec_hdr.addStretch()

        # Split toggle segmented buttons
        self.btn_view_key_selected = QPushButton(f"🔑 Key Selected ({self.combo_prov.currentText()})")
        self.btn_view_key_selected.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_view_key_selected.clicked.connect(lambda: self.set_view_mode("key_selected"))

        self.btn_view_all = QPushButton("🌐 All Configured Models")
        self.btn_view_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_view_all.clicked.connect(lambda: self.set_view_mode("all_models"))

        sec_hdr.addWidget(self.btn_view_key_selected)
        sec_hdr.addWidget(self.btn_view_all)
        mp_layout.addLayout(sec_hdr)

        self.models_container = QVBoxLayout()
        self.models_container.setSpacing(6)
        mp_layout.addLayout(self.models_container)

        self.main_layout.addWidget(models_panel)
        # Banned models at the very bottom (Task 8)
        self.main_layout.addWidget(ban_panel)

        self.master_scroll.setWidget(self.scroll_content)
        root_layout.addWidget(self.master_scroll, stretch=1)

        self.on_prov_selected(self.combo_prov.currentText())
        self.update_segmented_buttons()
        self.refresh_model_rows()
        self.refresh_all_extra_lists()

    def set_view_mode(self, mode: str):
        self.view_mode = mode
        self.update_segmented_buttons()
        self.refresh_model_rows()

    def update_segmented_buttons(self):
        active_style = """
            QPushButton {
                background: #9333EA; color: #FFFFFF;
                border: 1.5px solid #C084FC; border-radius: 8px;
                padding: 5px 14px; font-weight: bold; font-size: 11px;
            }
        """
        inactive_style = """
            QPushButton {
                background: rgba(255, 255, 255, 0.08); color: #CBD5E1;
                border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 8px;
                padding: 5px 14px; font-size: 11px;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.3); color: #FFFFFF; }
        """
        cur_p = self.combo_prov.currentText()
        self.btn_view_key_selected.setText(f"🔑 Key Selected ({cur_p})")
        if self.view_mode == "key_selected":
            self.btn_view_key_selected.setStyleSheet(active_style)
            self.btn_view_all.setStyleSheet(inactive_style)
        else:
            self.btn_view_key_selected.setStyleSheet(inactive_style)
            self.btn_view_all.setStyleSheet(active_style)

    def on_prov_selected(self, prov_name):
        keys = self.settings.get("user_custom_keys", {})
        self.edit_key.setText(keys.get(prov_name, ""))
        cached = self.settings.get("all_discovered_models", {}).get(prov_name, [])
        if cached:
            self.btn_fetch_models.setText(f"🔄 Refresh ({len(cached)} cached)")
        else:
            self.btn_fetch_models.setText("🔄 Fetch Models (Cloud)")
        self.update_segmented_buttons()
        if self.view_mode == "key_selected":
            self.refresh_model_rows()

    def save_key(self):
        prov = self.combo_prov.currentText()
        key = self.edit_key.text().strip()
        if not hasattr(self, "settings"): self.settings = {}
        self.settings.setdefault("user_custom_keys", {})[prov] = key
        save_json(F_SETTINGS, self.settings)
        play_ui_sound("click", 0.5)
        if self.chat_app:
            self.chat_app.settings = dict(self.settings)
            self.chat_app.rebuild_available_models()
            self.models = dict(self.chat_app.models)
        # Seed Gemini with flash defaults if empty cache
        if prov == "Google Gemini" and key:
            defaults = PROVIDER_DEFS.get(prov, {}).get("default_models", [])
            disc = self.settings.setdefault("all_discovered_models", {})
            existing = disc.get(prov) or []
            if not existing:
                disc[prov] = list(defaults)
            else:
                # Ensure flash-latest models at front, filter old 1.5 hardcodes
                seen = set()
                ordered = []
                for m in defaults + existing:
                    if m in seen:
                        continue
                    if m.startswith("gemini-1.5"):
                        continue
                    seen.add(m)
                    ordered.append(m)
                disc[prov] = ordered
            save_json(F_SETTINGS, self.settings)
        self.refresh_model_rows()
        if self.chat_app:
            self.chat_app.show_toast(f"Saved key for {prov}! Models unlocked.", icon="🔑")

    def fetch_live_models(self):
        prov = self.combo_prov.currentText()
        key = self.edit_key.text().strip()
        if not key:
            if self.chat_app:
                self.chat_app.show_toast(f"Enter an API key for {prov} first!", icon="⚠️")
            return
        p_data = PROVIDER_DEFS.get(prov, {})
        base_url = self.settings.get("custom_provider_urls", {}).get(prov, p_data.get("base_url", ""))
        self.btn_fetch_models.setEnabled(False)
        self.btn_fetch_models.setText("⏳ Querying API...")
        self.fetch_worker = ModelFetchWorker(prov, base_url, key, self, self.settings)
        self.fetch_worker.finished.connect(self.fetch_worker.deleteLater)
        self.fetch_worker.fetched.connect(self.on_models_fetched)
        self.fetch_worker.error.connect(self.on_fetch_error)
        self.fetch_worker.start()

    def on_models_fetched(self, prov, model_list):
        self.btn_fetch_models.setEnabled(True)
        self.btn_fetch_models.setText(f"🔄 Refresh ({len(model_list)} cached)")
        if not model_list:
            if self.chat_app: self.chat_app.show_toast(f"No chat models returned by {prov}", icon="⚠️")
            return
        self.settings.setdefault("all_discovered_models", {})[prov] = model_list
        save_json(F_SETTINGS, self.settings)
        play_ui_sound("pop", 0.5)
        if self.chat_app:
            self.chat_app.settings = dict(self.settings)
            self.chat_app.rebuild_available_models()
            self.models = dict(self.chat_app.models)
            self.chat_app.show_toast(f"Cached {len(model_list)} models locally! Zero future data usage.", icon="💾")
        self.refresh_model_rows()

    def on_fetch_error(self, prov, err):
        self.btn_fetch_models.setEnabled(True)
        cached = self.settings.get("all_discovered_models", {}).get(prov, [])
        self.btn_fetch_models.setText(f"🔄 Refresh ({len(cached)} cached)" if cached else "🔄 Fetch Models (Cloud)")
        if self.chat_app:
            self.chat_app.show_toast(f"Fetch failed: {err}", icon="⚠️")

    def add_custom_model(self):
        prov = self.combo_prov.currentText()
        custom_id = self.edit_custom_model.text().strip()
        if not custom_id:
            return
        existing = self.settings.setdefault("all_discovered_models", {}).setdefault(prov, [])
        if custom_id not in existing:
            existing.append(custom_id)
            save_json(F_SETTINGS, self.settings)
        self.edit_custom_model.clear()
        play_ui_sound("pop", 0.5)
        if self.chat_app:
            self.chat_app.settings = dict(self.settings)
            self.chat_app.rebuild_available_models()
            self.models = dict(self.chat_app.models)
            self.chat_app.show_toast(f"Added model {custom_id} to {prov}!", icon="✨")
        self.refresh_model_rows()

    def start_ping_all(self):
        if self.ping_worker and self.ping_worker.isRunning():
            return
        self.btn_ping_all.setEnabled(False)
        self.btn_ping_all.setText("⏳ Pinging Models...")
        self.ping_worker = ModelPingWorker(self.models, self.settings, self)
        self.ping_worker.finished.connect(self.ping_worker.deleteLater)
        self.ping_worker.ping_result.connect(self.on_ping_result)
        self.ping_worker.finished.connect(self.on_ping_finished)
        self.ping_worker.start()

    def on_ping_result(self, m_name, status_text, is_ok, latency):
        self.ping_status[m_name] = (status_text, is_ok, latency)
        self.refresh_model_rows()

    def on_ping_finished(self):
        self.btn_ping_all.setEnabled(True)
        self.btn_ping_all.setText("⚡ Ping Active Models")
        play_ui_sound("pop", 0.5)

    def refresh_model_rows(self):
        # Comprehensive layout clearance
        while self.models_container.count():
            item = self.models_container.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
                sub_l = item.layout()
                if sub_l is not None:
                    while sub_l.count():
                        sub_i = sub_l.takeAt(0)
                        if sub_i and sub_i.widget():
                            sub_i.widget().hide()
                            sub_i.widget().setParent(None)
                            sub_i.widget().deleteLater()

        keys = self.settings.get("user_custom_keys", {})
        cur_prov = self.combo_prov.currentText()
        active_models = {}

        for m_name, m_route in self.models.items():
            if is_offline_model_key(m_name, m_route):
                if self.view_mode == "all_models":
                    active_models[m_name] = m_route
            elif isinstance(m_route, dict):
                prov = m_route.get("provider", "")
                if keys.get(prov):
                    if self.view_mode == "key_selected":
                        if prov == cur_prov:
                            active_models[m_name] = m_route
                    else:
                        active_models[m_name] = m_route

        if not active_models:
            empty_box = QFrame()
            empty_box.setStyleSheet("background: rgba(20, 14, 32, 0.7); border: 1.5px dashed rgba(192, 132, 252, 0.35); border-radius: 12px; padding: 20px;")
            e_l = QVBoxLayout(empty_box)
            e_icon = QLabel("🔒")
            e_icon.setStyleSheet("font-size: 28px; border: none; background: transparent;")
            e_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e_msg = QLabel(f"No active models found for {cur_prov}!\nEnter your API key above, save it, and fetch/add models.")
            e_msg.setStyleSheet("color: #C084FC; font-size: 12px; font-weight: 500; border: none; background: transparent;")
            e_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e_l.addWidget(e_icon)
            e_l.addWidget(e_msg)
            self.models_container.addWidget(empty_box)
            return

        # Deduplicate active models display
        seen_models = set()
        for m_name, m_route in list(active_models.items()):
            norm_key = re.sub(r'[^a-zA-Z0-9]', '', m_name).lower()
            if norm_key in seen_models:
                continue
            seen_models.add(norm_key)
            row = QFrame()
            row.setMinimumHeight(46)
            row.setStyleSheet("background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 4px 8px;")
            r_h = QHBoxLayout(row)
            r_h.setContentsMargins(10, 4, 10, 4)
            r_h.setSpacing(10)

            name_l = QLabel(f"<b>{m_name}</b>")
            name_l.setStyleSheet("font-size: 13px; color: #F8F4FF; border: none;")
            r_h.addWidget(name_l, stretch=1)

            # Favorite/star button
            favs = self.settings.get("favorite_models", [])
            is_fav = m_name in favs
            btn_star = QPushButton("⭐" if is_fav else "☆")
            btn_star.setToolTip("Remove from favorites" if is_fav else "Add to favorites (appears in top bar dropdown)")
            btn_star.setFixedSize(28, 28)
            btn_star.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_star.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.08); color: #F8F4FF; border-radius: 6px;
                    padding: 2px; font-size: 14px; border: 1.5px solid rgba(192, 132, 252, 0.4); font-weight: bold;
                }
                QPushButton:hover { background: #9333EA; color: white; border-color: #C084FC; }
            """)
            btn_star.clicked.connect(lambda _, mn=m_name, b=btn_star: self.toggle_favorite(mn, b))
            r_h.addWidget(btn_star)

            # 1-Click Smart Ban Button
            btn_ban_quick = QPushButton("🚫")
            btn_ban_quick.setToolTip(f"Ban model '{m_name}' (hides it across all views)")
            btn_ban_quick.setFixedSize(28, 28)
            btn_ban_quick.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_ban_quick.setStyleSheet("""
                QPushButton {
                    background: rgba(239, 68, 68, 0.15); color: #F87171; border-radius: 6px;
                    padding: 2px; font-size: 13px; border: 1px solid rgba(239, 68, 68, 0.4);
                }
                QPushButton:hover { background: #EF4444; color: white; border-color: #F87171; }
            """)
            btn_ban_quick.clicked.connect(lambda _, mn=m_name: self.quick_ban_model(mn))
            r_h.addWidget(btn_ban_quick)

            # Health badge if pinged
            if m_name in self.ping_status:
                stat_txt, is_ok, lat = self.ping_status[m_name]
                badge_col = "#4ADE80" if is_ok else "#F87171"
                badge_bg = "rgba(74, 222, 128, 0.15)" if is_ok else "rgba(248, 113, 113, 0.15)"
                lat_part = f" ({lat})" if lat else ""
                badge = QLabel(f"● {stat_txt}{lat_part}")
                badge.setStyleSheet(f"color: {badge_col}; background: {badge_bg}; border: 1px solid {badge_col}; border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: bold;")
                r_h.addWidget(badge)

            btn_sel = QPushButton("🚀 Select")
            btn_sel.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_sel.setStyleSheet("""
                QPushButton {
                    background: rgba(147, 51, 234, 0.65); color: white; border-radius: 6px;
                    padding: 5px 14px; font-weight: bold; font-size: 11px; border: none;
                }
                QPushButton:hover { background: #A855F7; }
            """)
            btn_sel.clicked.connect(lambda _, mn=m_name: self.choose_model(mn))
            r_h.addWidget(btn_sel)
            self.models_container.addWidget(row)

    def choose_model(self, model_name):
        self.model_selected.emit(model_name)
        self.back_to_chat.emit()

    def toggle_favorite(self, m_name, btn):
        favs = self.settings.get("favorite_models", [])
        if m_name in favs:
            favs.remove(m_name)
            btn.setText("☆")
            btn.setToolTip("Add to favorites (appears in top bar dropdown)")
        else:
            favs.append(m_name)
            btn.setText("⭐")
            btn.setToolTip("Remove from favorites")
        self.settings["favorite_models"] = favs
        save_json(F_SETTINGS, self.settings)
        if self.chat_app:
            self.chat_app.settings = dict(self.settings)
            self.chat_app.update_model_dropdown()

    def quick_ban_model(self, full_model_name):
        # Extract core model identifier (strip icon, size, .gguf and provider brackets)
        clean = strip_offline_label(str(full_model_name).replace("⚡", ""))
        if "[" in clean and "]" in clean:
            clean = clean.split("[")[0].strip()
        
        banned = self.settings.get("banned_models", [])
        if clean not in banned:
            banned.append(clean)
            self.settings["banned_models"] = banned
            save_json(F_SETTINGS, self.settings)
            play_ui_sound("pop", 0.5)
            if self.chat_app:
                self.chat_app.settings = dict(self.settings)
                self.chat_app.rebuild_available_models()
                self.models = dict(self.chat_app.models)
                self.chat_app.show_toast(f"🚫 Banned model: {clean}", icon="🚫")
            self.refresh_model_rows()
            self.refresh_banned_list()

    # ===== Banned Models Management =====
    def add_banned_model(self):
        pattern = self.edit_ban_model.text().strip()
        if not pattern:
            return
        banned = self.settings.get("banned_models", [])
        if pattern not in banned:
            banned.append(pattern)
            self.settings["banned_models"] = banned
            save_json(F_SETTINGS, self.settings)
            self.edit_ban_model.clear()
            play_ui_sound("pop", 0.5)
            if self.chat_app:
                self.chat_app.settings = dict(self.settings)
                self.chat_app.rebuild_available_models()
                self.models = dict(self.chat_app.models)
                self.chat_app.show_toast(f"Banned: {pattern}", icon="🚫")
            self.refresh_model_rows()
            self.refresh_banned_list()

    def remove_banned_model(self, pattern):
        banned = self.settings.get("banned_models", [])
        if pattern in banned:
            banned.remove(pattern)
            self.settings["banned_models"] = banned
            save_json(F_SETTINGS, self.settings)
            if self.chat_app:
                self.chat_app.settings = dict(self.settings)
                self.chat_app.rebuild_available_models()
                self.models = dict(self.chat_app.models)
            self.refresh_model_rows()
            self.refresh_banned_list()

    def refresh_banned_list(self):
        while self.banned_list_layout.count():
            item = self.banned_list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        banned = self.settings.get("banned_models", [])
        for pattern in banned:
            row = QFrame()
            row.setMinimumHeight(38)
            row.setStyleSheet("background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; padding: 4px 8px;")
            r_h = QHBoxLayout(row)
            r_h.setContentsMargins(8, 2, 8, 2)
            lbl = QLabel(f"🚫 {pattern}")
            lbl.setStyleSheet("color: #F87171; font-size: 11px; font-weight: bold; border: none;")
            r_h.addWidget(lbl)
            r_h.addStretch()
            btn_remove = QPushButton("Unban")
            btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_remove.setFixedSize(65, 24)
            btn_remove.setStyleSheet("""
                QPushButton { background: rgba(239, 68, 68, 0.3); color: #FCA5A5; border: 1px solid #EF4444; border-radius: 4px; font-size: 10px; font-weight: bold; }
                QPushButton:hover { background: #EF4444; color: white; }
            """)
            btn_remove.clicked.connect(lambda _, p=pattern: self.remove_banned_model(p))
            r_h.addWidget(btn_remove)
            self.banned_list_layout.addWidget(row)

    def browse_offline_model(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select GGUF Model(s)", "", "GGUF Files (*.gguf);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog
        )
        if not paths:
            return
        if len(paths) == 1:
            path = paths[0]
            self.edit_offline_path.setText(path)
            name = os.path.basename(path).replace(".gguf", "")
            self.edit_offline_name.setText(name)
        else:
            # Batch add multiple models quietly skipping duplicates
            offline_models = self.settings.get("offline_models", {})
            added = 0
            for p in paths:
                m_name = os.path.basename(p).replace(".gguf", "")
                if m_name not in offline_models:
                    offline_models[m_name] = p
                    added += 1
            if added > 0:
                self.settings["offline_models"] = offline_models
                save_json(F_SETTINGS, self.settings)
                if self.chat_app:
                    self.chat_app.settings = dict(self.settings)
                    self.chat_app.rebuild_available_models()
                    self.models = dict(self.chat_app.models)
                    self.chat_app.show_toast(f"✅ Added {added} model(s) to Hub!", icon="💾")
                self.refresh_offline_list()
                self.refresh_model_rows()

    def add_offline_model(self):
        name = self.edit_offline_name.text().strip()
        path = self.edit_offline_path.text().strip()
        if not name or not path:
            if self.chat_app:
                self.chat_app.show_toast("Enter both name and path!", icon="⚠️")
            return
        if not os.path.exists(path):
            if self.chat_app:
                self.chat_app.show_toast("File not found!", icon="⚠️")
            return
        offline_models = self.settings.get("offline_models", {})
        offline_models[name] = path
        self.settings["offline_models"] = offline_models
        self.settings["local_model_path"] = path
        save_json(F_SETTINGS, self.settings)
        self.edit_offline_name.clear()
        self.edit_offline_path.clear()
        play_ui_sound("pop", 0.5)
        if self.chat_app:
            self.chat_app.settings = dict(self.settings)
            self.chat_app.rebuild_available_models()
            self.models = dict(self.chat_app.models)
            self.chat_app.show_toast(f"Added offline model: {name}", icon="📁")
        self.refresh_offline_list()
        self.refresh_model_rows()

    def remove_offline_model(self, name):
        offline_models = self.settings.get("offline_models", {})
        if name in offline_models:
            del offline_models[name]
            self.settings["offline_models"] = offline_models
            if offline_models:
                self.settings["local_model_path"] = list(offline_models.values())[0]
            else:
                self.settings["local_model_path"] = ""
            save_json(F_SETTINGS, self.settings)
            if self.chat_app:
                self.chat_app.settings = dict(self.settings)
                self.chat_app.rebuild_available_models()
                self.models = dict(self.chat_app.models)
            self.refresh_offline_list()
            self.refresh_model_rows()

    def refresh_offline_list(self):
        while self.offline_list_layout.count():
            item = self.offline_list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        offline_models = self.settings.get("offline_models", {})
        favs = self.settings.get("favorite_models", [])

        for name, path in offline_models.items():
            row = QFrame()
            row.setMinimumHeight(46)
            row.setStyleSheet("background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 8px; padding: 4px 8px;")
            r_h = QHBoxLayout(row)
            r_h.setContentsMargins(8, 4, 8, 4)
            r_h.setSpacing(8)

            display = offline_model_label(name, path, self.settings)
            lbl = QLabel(
                f"<b>{html.escape(display)}</b><br>"
                f"<span style='color: #94A3B8; font-size: 10px;'>"
                f"{html.escape(str(path))}</span>")
            lbl.setStyleSheet("color: #4ADE80; font-size: 12px; border: none;")
            r_h.addWidget(lbl, stretch=1)

            # Favorite ⭐ button for offline models
            m_key = offline_model_label(name, path, self.settings)
            is_fav = m_key in favs or name in favs
            btn_star = QPushButton("⭐" if is_fav else "☆")
            btn_star.setToolTip("Toggle favorite (adds offline model directly to top bar dropdown)")
            btn_star.setFixedSize(28, 28)
            btn_star.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_star.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.08); color: #F8F4FF; border-radius: 6px;
                    padding: 2px; font-size: 14px; border: 1.5px solid rgba(16, 185, 129, 0.4); font-weight: bold;
                }
                QPushButton:hover { background: #10B981; color: white; border-color: #34D399; }
            """)
            btn_star.clicked.connect(lambda _, mn=m_key, b=btn_star: self.toggle_favorite(mn, b))
            r_h.addWidget(btn_star)

            # Direct Select button for offline models
            btn_sel = QPushButton("🚀 Select")
            btn_sel.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_sel.setStyleSheet("""
                QPushButton {
                    background: rgba(16, 185, 129, 0.45); color: #FFFFFF; border-radius: 6px;
                    padding: 4px 12px; font-weight: bold; font-size: 11px; border: 1px solid #10B981;
                }
                QPushButton:hover { background: #059669; }
            """)
            btn_sel.clicked.connect(lambda _, mn=m_key: self.choose_model(mn))
            r_h.addWidget(btn_sel)

            btn_remove = QPushButton()
            btn_remove.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_x.svg")))
            btn_remove.setIconSize(QSize(13, 13))
            btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_remove.setFixedSize(26, 26)
            btn_remove.setStyleSheet("""
                QPushButton { background: rgba(239, 68, 68, 0.2); color: #FCA5A5; border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 4px; font-size: 11px; font-weight: bold; }
                QPushButton:hover { background: #EF4444; color: white; }
            """)
            btn_remove.clicked.connect(lambda _, n=name: self.remove_offline_model(n))
            r_h.addWidget(btn_remove)
            self.offline_list_layout.addWidget(row)

    # ===== Fallback Models Management =====
    def add_fallback_model(self):
        model = self.edit_fallback_model.text().strip()
        if not model:
            return
        fallbacks = self.settings.get("fallback_models", [])
        if model not in fallbacks:
            fallbacks.append(model)
            self.settings["fallback_models"] = fallbacks
            save_json(F_SETTINGS, self.settings)
            self.edit_fallback_model.clear()
            play_ui_sound("pop", 0.5)
            if self.chat_app:
                self.chat_app.settings = dict(self.settings)
                self.chat_app.show_toast(f"Added fallback: {model}", icon="🔄")
            self.refresh_fallback_list()

    def remove_fallback_model(self, model):
        fallbacks = self.settings.get("fallback_models", [])
        if model in fallbacks:
            fallbacks.remove(model)
            self.settings["fallback_models"] = fallbacks
            save_json(F_SETTINGS, self.settings)
            if self.chat_app:
                self.chat_app.settings = dict(self.settings)
            self.refresh_fallback_list()

    def refresh_fallback_list(self):
        while self.fallback_list_layout.count():
            item = self.fallback_list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        fallbacks = self.settings.get("fallback_models", [])
        for i, model in enumerate(fallbacks):
            row = QFrame()
            row.setMinimumHeight(38)
            row.setStyleSheet("background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 8px; padding: 4px 8px;")
            r_h = QHBoxLayout(row)
            r_h.setContentsMargins(8, 2, 8, 2)
            lbl = QLabel(f"{i+1}. {model}")
            lbl.setStyleSheet("color: #38BDF8; font-size: 11px; font-weight: bold; border: none;")
            r_h.addWidget(lbl)
            r_h.addStretch()
            btn_remove = QPushButton("Remove")
            btn_remove.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_x.svg")))
            btn_remove.setIconSize(QSize(12, 12))
            btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_remove.setFixedSize(94, 24)
            btn_remove.setStyleSheet("""
                QPushButton { background: rgba(56, 189, 248, 0.2); color: #BAE6FD; border: 1px solid #38BDF8; border-radius: 4px; font-size: 10px; font-weight: bold; }
                QPushButton:hover { background: #0284C7; color: white; }
            """)
            btn_remove.clicked.connect(lambda _, m=model: self.remove_fallback_model(m))
            r_h.addWidget(btn_remove)
            self.fallback_list_layout.addWidget(row)

    def refresh_all_extra_lists(self):
        self.refresh_banned_list()
        self.refresh_offline_list()
        self.refresh_fallback_list()

ModelManagerWidgetNew = ModelManagerWidget

_SETTINGS_NAV_QSS = """
QWidget#SettingsTabNav { background: transparent; }
QPushButton#SettingsTabPill {
    background: rgba(255, 255, 255, 0.045);
    color: #CBD5E1;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 11px;
    padding: 7px 14px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#SettingsTabPill:hover {
    background: rgba(147, 51, 234, 0.28);
    color: #F8F4FF;
    border-color: rgba(192, 132, 252, 0.55);
}
QPushButton#SettingsTabPill:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #8A2BE2, stop:1 #A855F7);
    color: #FFFFFF;
    border: 1.5px solid #E879F9;
}
"""


class _SettingsTabFlow(QLayout):
    """Wrapping pill rail for the Settings tabs.

    A QTabBar is a single fixed row: eight tabs need ~1370 px, so on the
    default window it silently cut the last three labels off and painted
    scroll arrows over the fifth. This layout keeps every label intact and
    wraps onto another row instead - nothing is ever clipped or elided.
    """

    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(),
                            margins.top() + margins.bottom())

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(),
                             -margins.right(), -margins.bottom())
        x, y = area.x(), area.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if next_x - self._spacing > area.right() + 1 and line_height > 0:
                x = area.x()
                y += line_height + self._spacing
                next_x = x + hint.width() + self._spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


# ------------------------------------------------------------------ Inbuilt View 2: Settings (Tabbed Interface)
class SettingsWidget(QWidget):
    back_to_chat = Signal()
    saved = Signal(dict)
    _log_line = Signal(str)
    kaggle_test_done = Signal(str, str)
    cache_status_done = Signal(object)
    cache_action_done = Signal(str, str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.kaggle_test_done.connect(self._on_test_done)
        self.cache_status_done.connect(self._cache_refreshed)
        self.cache_action_done.connect(self._on_cache_action_done)
        # Deep staging copy: nested tables (keys, model lists) must not
        # alias the caller's dict, or an un-saved edit would leak into the
        # main settings - and from there into any unrelated save_json  - 
        # before ✓ Save Preferences is ever clicked.
        self.settings = copy.deepcopy(dict(settings or {}))
        # Building ~540 widgets takes ~420 ms. Suppressing updates during
        # construction avoids repeated polish/layout passes; the page is only
        # shown after __init__ returns anyway.
        self.setUpdatesEnabled(False)
        try:
            self.init_ui()
        finally:
            self.setUpdatesEnabled(True)
        # Every slider in here is Qt-blue by default; make them ours.
        _theme_sliders(self)
        # …and lock the wheel on every combo *and* spinner, not just the combos
        # that happened to opt in individually.
        try:
            _lock_all_wheels(self, bool(
                self.settings.get("disable_combo_wheel", True)))
        except Exception:
            pass
        self._apply_visibility_rules()
        # Reuse contract: open_settings_view keeps this widget alive while it is
        # clean, so reopening Settings is instant instead of rebuilding 540
        # widgets every time.
        self._dirty = False
        self._built_sig = None
        self._wire_dirty_tracking()

    def _wire_dirty_tracking(self) -> None:
        """Mark the staging copy dirty on any real user edit."""
        from PySide6.QtWidgets import (
            QLineEdit, QComboBox, QAbstractButton, QSlider, QSpinBox,
            QDoubleSpinBox, QPlainTextEdit, QTextEdit,
        )

        def _mark(*_a):
            self._dirty = True

        try:
            for w in self.findChildren(QLineEdit):
                w.textEdited.connect(_mark)
            for w in self.findChildren(QComboBox):
                w.currentIndexChanged.connect(_mark)
            for w in self.findChildren(QAbstractButton):
                w.toggled.connect(_mark)
            for w in self.findChildren(QSlider):
                w.valueChanged.connect(_mark)
            for w in self.findChildren(QSpinBox):
                w.valueChanged.connect(_mark)
            for w in self.findChildren(QDoubleSpinBox):
                w.valueChanged.connect(_mark)
            for w in self.findChildren(QPlainTextEdit):
                w.textChanged.connect(_mark)
            for w in self.findChildren(QTextEdit):
                w.textChanged.connect(_mark)
        except Exception:
            pass

    @staticmethod
    def _disable_combo_wheel(combo):
        """Prevent mouse wheel from changing combo selection unless focused."""
        _lock_wheel(combo, True)

    def _make_tab(self, title):
        """Create a scrollable tab widget with consistent styling."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: rgba(15, 10, 25, 0.4);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(168, 85, 247, 0.5);
                min-height: 25px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #A855F7;
            }
        """)
        content = QWidget()
        content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)
        scroll.setWidget(content)
        return scroll, content, layout

    def _build_tab_nav(self, layout) -> None:
        """Replace the overflowing QTabBar with wrapping pill buttons."""
        bar = self.tab_widget.tabBar()
        bar.hide()
        nav = QWidget()
        nav.setObjectName("SettingsTabNav")
        nav.setStyleSheet(_SETTINGS_NAV_QSS)
        flow = _SettingsTabFlow(nav, spacing=8)
        nav.setLayout(flow)

        self._tab_buttons = []
        for i in range(self.tab_widget.count()):
            # QTabBar keeps the raw text; a single "&" becomes a mnemonic
            # underline (that is why "Audio & Voice" rendered as "Audio
            # _Voice"). Double it so the pill shows a literal ampersand.
            btn = QPushButton(bar.tabText(i).replace("&", "&&"))
            btn.setObjectName("SettingsTabPill")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked=False, idx=i: self.tab_widget.setCurrentIndex(idx))
            flow.addWidget(btn)
            self._tab_buttons.append(btn)

        at = layout.indexOf(self.tab_widget)
        layout.insertWidget(at if at >= 0 else layout.count(), nav)
        self.tab_widget.currentChanged.connect(self._sync_tab_nav)
        self._sync_tab_nav(self.tab_widget.currentIndex())

    def _sync_tab_nav(self, index: int) -> None:
        for i, btn in enumerate(getattr(self, "_tab_buttons", [])):
            try:
                btn.setChecked(i == index)
            except RuntimeError:
                pass

    def _add_section_header(self, layout, text, color="#C084FC", margin_top=0):
        """Add a styled section header."""
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {color}; border: none; margin-top: {margin_top}px;")
        layout.addWidget(lbl)

    def _add_avatar_row(self, layout, who: str):
        """Build one 'Your profile picture' / 'Cel's profile picture' row."""
        is_cel = who == "cel"
        title = "✨ Cel's profile picture" if is_cel else "🖼️ Your profile picture"
        subtitle = (
            "Give Cel a face of her own - appears beside her bubble header in chat."
            if is_cel else
            "Your circular cutout beside your bubble header in chat - click to crop / zoom."
        )

        h = QHBoxLayout()
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight: bold; font-size: 12px; color: #F8F4FF; border: none;")
        h.addWidget(lbl)
        h.addStretch(1)

        prev = CircularAvatarLabel(who=who, diameter=48)
        prev.clicked.connect(
            lambda _=False, w=who: self._on_avatar_upload(w))
        h.addWidget(prev, 0, Qt.AlignmentFlag.AlignVCenter)
        self.avatar_labels[who] = prev

        btn_upload = QPushButton("Upload…")
        btn_upload.setStyleSheet(
            "QPushButton { background: rgba(147, 51, 234, 0.35); color:#E9D5FF;"
            " border:1px solid #9333EA; border-radius:7px; padding:5px 12px; font-size:11px; }"
            "QPushButton:hover { background:#9333EA; color:#fff; }"
            "QPushButton:disabled { background: rgba(80,80,90,0.28); border-color:#555; color:#888; }")
        btn_upload.clicked.connect(lambda _=False, w=who: self._on_avatar_upload(w))
        h.addWidget(btn_upload)

        btn_clear = QPushButton("Remove")
        btn_clear.setStyleSheet(
            "QPushButton { background: rgba(239, 68, 68, 0.18); color:#FCA5A5;"
            " border:1px solid rgba(248, 113, 113, 0.45); border-radius:7px;"
            " padding:5px 12px; font-size:11px; }"
            "QPushButton:hover { background:#DC2626; color:#fff; }")
        btn_clear.clicked.connect(lambda _=False, w=who: self._on_avatar_clear(w))
        h.addWidget(btn_clear)

        cap = QLabel(subtitle)
        cap.setStyleSheet("font-size: 10px; color: #A78BFA; border: none;")
        cap.setWordWrap(True)
        cap.setMaximumWidth(300)

        layout.addLayout(h)
        layout.addWidget(cap)

        # Let SettingsRefreshBubbles on save refresh these labels.

    def _make_input_row(self, layout, label_text, widget, stretch=1, label_color="#F8F4FF"):
        """Create a horizontal layout with label and widget."""
        h = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"border: none; color: {label_color};")
        h.addWidget(lbl)
        h.addWidget(widget, stretch=stretch)
        layout.addLayout(h)
        return h

    def _make_slider_row(self, layout, label_text, value, min_val, max_val, suffix="", label_color="#F8F4FF"):
        """Create a slider with value label."""
        h = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"border: none; color: {label_color};")
        h.addWidget(lbl)
        val_lbl = QLabel(f"{value}{suffix}")
        val_lbl.setStyleSheet("border: none; color: #C084FC; font-weight: bold;")
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setValue(value)
        slider.valueChanged.connect(lambda v: val_lbl.setText(f"{v}{suffix}"))
        h.addWidget(slider)
        h.addWidget(val_lbl)
        layout.addLayout(h)
        return slider, val_lbl

    def _style_combo(self, combo):
        """Apply consistent styling to combo boxes."""
        combo.setStyleSheet("""
            QComboBox {
                background: rgba(22, 14, 38, 0.42);
                color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45);
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 12px;
            }
            QComboBox:hover {
                border: 1.5px solid rgba(192, 132, 252, 0.75);
                background: rgba(28, 18, 48, 0.52);
            }
            QComboBox:focus {
                border: 2px solid #C084FC;
                background: rgba(32, 20, 56, 0.65);
            }
            QComboBox QAbstractItemView {
                background: rgba(18, 12, 32, 0.96);
                border: 1.5px solid #A855F7;
                border-radius: 8px;
                color: #F0E6FF;
                selection-background-color: #8A2BE2;
                selection-color: white;
                padding: 4px;
            }
        """)
        return combo

    def _style_spin(self, spin):
        """Apply consistent styling to spin boxes."""
        spin.setStyleSheet("""
            QSpinBox {
                background: rgba(22, 14, 38, 0.42);
                color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45);
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 12px;
            }
            QSpinBox:hover {
                border: 1.5px solid rgba(192, 132, 252, 0.75);
                background: rgba(28, 18, 48, 0.52);
            }
            QSpinBox:focus {
                border: 2px solid #C084FC;
                background: rgba(32, 20, 56, 0.65);
            }
        """)
        return spin

    def _style_check(self, chk):
        """Apply consistent styling to checkboxes."""
        _ck = (ASSETS_DIR / "checkmark.png").as_posix()
        chk.setStyleSheet(f"""
            QCheckBox {{
                color: #F8F4FF; font-size: 13px; spacing: 8px; border: none; background: transparent;
            }}
            QCheckBox::indicator {{
                width: 20px; height: 20px; border-radius: 6px;
                border: 2px solid #9333EA; background: rgba(18, 12, 32, 0.6);
            }}
            QCheckBox::indicator:hover {{
                border: 2px solid #C084FC; background: rgba(138, 43, 226, 0.35);
            }}
            QCheckBox::indicator:checked {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8A2BE2, stop:1 #A855F7);
                border: 2px solid #C084FC;
                image: url("{_ck}");
            }}
        """)
        return chk

    def _refresh_offline_label_preview(self, *_):
        """Live sample of the three offline-label switches."""
        if not hasattr(self, "lbl_off_preview"):
            return
        opts = {
            "show_offline_model_size": self.toggle_off_size.isChecked(),
            "show_offline_model_tag": self.toggle_off_tag.isChecked(),
            "offline_model_size_first": self.toggle_off_size_first.isChecked(),
        }
        models = self.settings.get("offline_models", {}) or {}
        if models:
            name, path = next(iter(models.items()))
            sample = offline_model_label(name, path, opts)
        else:
            sample = offline_model_label(
                "gemma-3-1b-it-abliterated.i1-Q4_K_M", "", opts,
                size_bytes=806_059_008)
        self.lbl_off_preview.setText(
            "<span style='color:#7DD3FC; font-weight:bold;'>Preview</span>"
            f"&nbsp;&nbsp;{html.escape(sample)}")

    # ── conditional options ────────────────────────────────────────────
    # Settings used to keep every option on screen no matter what was picked
    # above it, so contradictory combinations were one click away ("Cel
    # Legacy Sounds" while the modern pack still played underneath). Each
    # rule hides a row until the choice that gives it meaning is made.
    @staticmethod
    def _row_widgets(target):
        """Accept a widget or a layout - layouts are not hideable themselves."""
        if isinstance(target, QWidget):
            return [target]
        out = []
        for i in range(target.count()):
            w = target.itemAt(i).widget()
            if w is not None:
                out.append(w)
        return out

    def _on_ptt_key_changed(self, seq) -> None:
        """Store the bound push-to-talk key, refusing the unusable ones."""
        from PySide6.QtGui import QKeySequence as _QKS
        name = ""
        try:
            name = _QKS(seq).toString(_QKS.SequenceFormat.PortableText).strip()
        except Exception:
            name = ""
        if not name:
            self.settings["live_ptt_key"] = ""
            self._ptt_key = ""
            return
        # Escape is the "get me out" key. Qt would happily bind it, and then
        # every panic press would open the mic mid-call. Modifiers on their own
        # are not keys either.
        from PySide6.QtCore import Qt as _Qt
        try:
            bare = _QKS(name)
            banned = (
                _Qt.Key.Key_Escape, _Qt.Key.Key_Shift, _Qt.Key.Key_Control,
                _Qt.Key.Key_Alt, _Qt.Key.Key_Meta, _Qt.Key.Key_CapsLock,
            )
            # bare[0] is a QKeyCombination: compare its *key*, not int(...).
            if bare.count() and bare[0].key() in banned:
                self.edit_ptt_key.blockSignals(True)
                self.edit_ptt_key.setKeySequence(_QKS(""))
                self.edit_ptt_key.blockSignals(False)
                self.settings["live_ptt_key"] = ""
                self._ptt_key = ""
                return
        except Exception:
            pass
        self.settings["live_ptt_key"] = name
        self._ptt_key = name

    def _bind_dependent(self, source, targets, predicate) -> None:
        """Show ``targets`` only while ``predicate(source)`` holds."""
        widgets = []
        for t in targets:
            widgets.extend(self._row_widgets(t))
        rule = (source, widgets, predicate)
        self._vis_rules.append(rule)
        self._apply_rule(rule)
        self._wire_rule_source(source)

    @staticmethod
    def _apply_rule(rule) -> None:
        source, widgets, predicate = rule
        try:
            want = bool(predicate(source))
        except RuntimeError:
            return
        for w in widgets:
            try:
                w.setVisible(want)
            except RuntimeError:
                continue

    def _apply_visibility_rules(self) -> None:
        """Re-evaluate every rule - called once the whole dialog exists, so a
        rule bound to a control built later still lands correctly."""
        for rule in getattr(self, "_vis_rules", []):
            self._apply_rule(rule)

    def _wire_rule_source(self, source) -> None:
        for sig in ("currentTextChanged", "currentIndexChanged", "toggled"):
            s = getattr(source, sig, None)
            if s is None:
                continue
            try:
                s.connect(lambda *_a: self._apply_visibility_rules())
            except (RuntimeError, TypeError):
                continue

    # ── Kaggle Image Generation Handlers ────────────────────────────────────

    def _on_kaggle_preset_changed(self, name: str) -> None:
        """Apply a named preset to the manual model fields (editable afterwards)."""
        from cellium.services.kaggle_image import preset_by_name
        p = preset_by_name(name)
        if not p or p.get("mode") == "custom":
            return
        self.combo_kaggle_model_mode.setCurrentIndex(0 if p["mode"] == "huggingface" else 1)
        if p.get("hf_model"):
            self.edit_kaggle_hf_model.setText(p["hf_model"])
        if p.get("civitai_url"):
            self.edit_kaggle_civitai_url.setText(p["civitai_url"])
        if p.get("lora_url") is not None:
            self.edit_kaggle_lora_url.setText(p["lora_url"])
        if p.get("steps"):
            self.spin_kaggle_steps.setValue(p["steps"])
        if p.get("guidance"):
            self.spin_kaggle_guidance.setValue(p["guidance"])

    def _on_kaggle_model_mode_changed(self, index: int) -> None:
        """Show/hide HF vs Civitai fields based on model mode.

        Toggle the *rows* built by ``_make_input_row`` - never standalone
        QLabels. A parentless QLabel that receives ``setVisible(True)`` is a
        top-level window, which is exactly why the HF labels used to pop up
        as two tiny floating windows when Settings opened.
        """
        is_hf = (index == 0)
        rows = (
            (self._row_kaggle_hf_model, is_hf),
            (self._row_kaggle_hf_token, is_hf),
            (self._row_kaggle_civitai_url, not is_hf),
            (self._row_kaggle_civitai_token, not is_hf),
        )
        for row, visible in rows:
            for w in self._row_widgets(row):
                try:
                    w.setVisible(visible)
                except RuntimeError:
                    pass

    def _import_kaggle_json(self) -> None:
        """Import kaggle.json file and populate username/key fields."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Import kaggle.json", "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            user = data.get("username", "").strip()
            key = data.get("key", "").strip()
            if user and key:
                self.edit_kaggle_user.setText(user)
                self.edit_kaggle_key.setText(key)
                self.settings["kaggle_username"] = user
                self.settings["kaggle_api_key"] = key
                self.lbl_kaggle_test.setText("✅ kaggle.json imported - testing connection...")
                self.lbl_kaggle_test.setStyleSheet("border: none; color: #6EE7B7; font-size: 11px; margin-top: 4px;")
                self._test_kaggle_connection()
            else:
                self.lbl_kaggle_test.setText("❌ Invalid kaggle.json (missing username/key)")
                self.lbl_kaggle_test.setStyleSheet("border: none; color: #EF4444; font-size: 11px; margin-top: 4px;")
        except Exception as e:
            self.lbl_kaggle_test.setText(f"❌ Failed to import: {e}")
            self.lbl_kaggle_test.setStyleSheet("border: none; color: #EF4444; font-size: 11px; margin-top: 4px;")

    def _test_kaggle_connection(self) -> None:
        """Test Kaggle credentials by calling datasets/list."""
        user = self.edit_kaggle_user.text().strip()
        key = self.edit_kaggle_key.text().strip()
        if not user or not key:
            self.lbl_kaggle_test.setText("❌ Enter username and API key first")
            self.lbl_kaggle_test.setStyleSheet("border: none; color: #EF4444; font-size: 11px; margin-top: 4px;")
            return
        
        self.lbl_kaggle_test.setText("🔄 Testing...")
        self.lbl_kaggle_test.setStyleSheet("border: none; color: #FBBF24; font-size: 11px; margin-top: 4px;")
        self.btn_test_kaggle.setEnabled(False)
        
        def test():
            try:
                import requests
                from requests.auth import HTTPBasicAuth
                session = requests.Session()
                session.auth = HTTPBasicAuth(user, key)
                session.headers.update({"User-Agent": "Cellium/1.0"})
                resp = session.get(
                    "https://www.kaggle.com/api/v1/datasets/list",
                    params={"user": user, "page": 1},
                    timeout=15,
                )
                if resp.status_code == 200:
                    msg = "✅ Connected! GPU quota available."
                    color = "#6EE7B7"
                elif resp.status_code == 401:
                    msg = "❌ Invalid credentials"
                    color = "#EF4444"
                elif resp.status_code == 403:
                    msg = "⚠️ Connected but no GPU quota (verify phone on Kaggle)"
                    color = "#FBBF24"
                else:
                    msg = f"❌ Unexpected: {resp.status_code}"
                    color = "#EF4444"
            except Exception as e:
                msg = f"❌ Network error: {e}"
                color = "#EF4444"
            
            # Emit across thread boundary via Qt Signal (QueuedConnection)
            self.kaggle_test_done.emit(msg, color)
        
        import threading
        threading.Thread(target=test, daemon=True).start()

    def _on_test_done(self, msg: str, color: str) -> None:
        self.lbl_kaggle_test.setText(msg)
        self.lbl_kaggle_test.setStyleSheet(f"border: none; color: {color}; font-size: 11px; margin-top: 4px;")
        self.btn_test_kaggle.setEnabled(True)

    def _pick_kaggle_output_dir(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Choose Output Folder")
        if path:
            self.edit_kaggle_output_dir.setText(path)

    def _open_kaggle_output_dir(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        path = self.edit_kaggle_output_dir.text().strip()
        if not path:
            from cellium.core.config import USER_DATA_DIR
            path = str(USER_DATA_DIR / "generated_images")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _kaggle_backend_now(self):
        """Backend from the *current form* credentials (not yet saved)."""
        from cellium.services.kaggle_image import KaggleImageBackend, build_model_config
        user = self.edit_kaggle_user.text().strip()
        key = self.edit_kaggle_key.text().strip()
        if not user or not key:
            return None
        mc = build_model_config(self.settings)
        return KaggleImageBackend(user, key, mc)

    # ── PHASE 5: ☁️ server-side model cache ──────────────────────────────
    def _render_cache_rows(self) -> None:
        """Paint each preset's cache state from the persisted map (no network)."""
        cmap = self.settings.get("kaggle_cache_map") or {}
        from cellium.services.kaggle_image import MODEL_PRESETS, preset_by_name
        for name, (stat, btn_now, btn_del) in getattr(self, "_cache_rows", {}).items():
            entry = cmap.get(name) or {}
            nbytes = int(entry.get("bytes") or 0)
            p = preset_by_name(name) or {}
            is_hf = (p.get("mode") == "huggingface")
            if is_hf:
                stat.setText("⚡ Fast Public HuggingFace model (Instant / No Cache Needed)")
                stat.setStyleSheet("border:none; color:#38BDF8; font-size:11px;")
                btn_now.setVisible(False)
                btn_del.setVisible(False)
            elif entry.get("healthy"):
                stat.setText(f"☁️ cached · {nbytes / (1024 ** 3):.2f} GB")
                stat.setStyleSheet("border:none; color:#6EE7B7; font-size:11px;")
                btn_now.setText("↻ Re-cache")
                btn_now.setVisible(True)
                btn_now.setEnabled(True)
                btn_del.setVisible(True)
                btn_del.setEnabled(True)
            elif entry.get("exists"):
                stat.setText(f"⚠️ empty shell ({nbytes:,} B) - re-cache it")
                stat.setStyleSheet("border:none; color:#FBBF24; font-size:11px;")
                btn_now.setText("☁️ Cache now")
                btn_now.setVisible(True)
                btn_now.setEnabled(True)
                btn_del.setVisible(True)
                btn_del.setEnabled(True)
            else:
                stat.setText(" -  not cached (Civitai download on every render)")
                stat.setStyleSheet("border:none; color:#94A3B8; font-size:11px;")
                btn_now.setText("☁️ Cache now")
                btn_now.setVisible(True)
                btn_now.setEnabled(True)
                btn_del.setVisible(True)
                btn_del.setEnabled(False)

    def _cache_refresh(self) -> None:
        """Probe `cellium-cache-*` datasets (view endpoint) in a background thread."""
        b = self._kaggle_backend_now()
        if b is None:
            self._render_cache_rows()
            return
        for stat, _n, _d in getattr(self, "_cache_rows", {}).values():
            stat.setText("🔍 checking…")
            stat.setStyleSheet("border:none; color:#C084FC; font-size:11px;")
        import threading

        def work():
            from cellium.services import model_cache as mc
            payload = {}
            try:
                payload = mc.refresh_cache_map(b)
            except Exception as e:
                dev_log(f"[model-cache] refresh failed: {e}")
            try:
                self.cache_status_done.emit(payload)
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _cache_refreshed(self, payload) -> None:
        if isinstance(payload, dict) and payload:
            self.settings["kaggle_cache_map"] = payload
            try:
                from cellium.core.config import load_json, save_json, USER_DATA_DIR
                cfg_path = USER_DATA_DIR / "cerebrium_settings.json"
                cur = load_json(cfg_path, {})
                cur["kaggle_cache_map"] = payload
                save_json(cfg_path, cur)
            except Exception as e:
                dev_log(f"[model-cache] persist failed: {e}")
        self._render_cache_rows()

    def _cache_start(self, preset: dict) -> None:
        """Push the CPU-only builder kernel (no GPU quota, no PC download)."""
        b = self._kaggle_backend_now()
        pname = preset.get("name") or ""
        row = getattr(self, "_cache_rows", {}).get(pname)
        if b is None:
            if row:
                row[0].setText("❌ Enter Kaggle username + key first")
                row[0].setStyleSheet("border:none; color:#EF4444; font-size:11px;")
            return
        if row:
            row[0].setText("☁️ Pushing CPU-only builder kernel…")
            row[0].setStyleSheet("border:none; color:#FBBF24; font-size:11px;")
            row[1].setEnabled(False)
        import threading

        def work():
            from cellium.services import model_cache as mc
            try:
                kernel = mc.push_cache_builder(b, preset)
                msg = f"☁️ Builder running ({kernel}) - click Refresh in ~5 min"
            except Exception as e:
                msg = f"❌ {str(e)[:150]}"
            self.cache_action_done.emit(pname, msg)

        threading.Thread(target=work, daemon=True).start()

    def _cache_remove(self, preset: dict) -> None:
        b = self._kaggle_backend_now()
        pname = preset.get("name") or ""
        row = getattr(self, "_cache_rows", {}).get(pname)
        if b is None:
            if row:
                row[0].setText("❌ Enter Kaggle username + key first")
                row[0].setStyleSheet("border:none; color:#EF4444; font-size:11px;")
            return
        if row:
            row[0].setText("🗑 Deleting cache dataset…")
            row[0].setStyleSheet("border:none; color:#FBBF24; font-size:11px;")
            row[1].setEnabled(False)
            row[2].setEnabled(False)
        import threading

        def work():
            from cellium.services import model_cache as mc
            try:
                ok = mc.delete_cache(b, mc.preset_slug(pname))
                msg = "🗑 Cache deleted" if ok else "❌ Delete failed - see logs"
            except Exception as e:
                msg = f"❌ {str(e)[:150]}"
            self.cache_action_done.emit(pname, msg)

        threading.Thread(target=work, daemon=True).start()

    def _on_cache_action_done(self, preset_name: str, msg: str) -> None:
        row = getattr(self, "_cache_rows", {}).get(preset_name)
        if not row:
            return
        row[0].setText(msg)
        if "Builder running" in msg:
            # Live realtime progress polling on Kaggle
            row[1].setEnabled(False)
            import time
            start_t = time.time()

            def poll_builder():
                b = self._kaggle_backend_now()
                if not b:
                    return
                from cellium.services import model_cache as mc
                slug = mc.preset_slug(preset_name)
                st = mc.cache_status(b, slug)
                elapsed = int(time.time() - start_t)
                if st.get("healthy"):
                    nbytes = int(st.get("bytes") or 0)
                    row[0].setText(f"☁️ cached · {nbytes / (1024 ** 3):.2f} GB")
                    row[0].setStyleSheet("border:none; color:#6EE7B7; font-size:11px;")
                    row[1].setText("↻ Re-cache")
                    row[1].setEnabled(True)
                    if len(row) > 2:
                        row[2].setEnabled(True)
                    # Refresh persisted map
                    self._cache_refresh()
                elif elapsed > 600:
                    row[0].setText("⚠️ Build timed out (>10m) - check Kaggle output")
                    row[0].setStyleSheet("border:none; color:#FBBF24; font-size:11px;")
                    row[1].setEnabled(True)
                else:
                    row[0].setText(f"☁️ Downloading on Kaggle ({elapsed}s elapsed)…")
                    row[0].setStyleSheet("border:none; color:#C084FC; font-size:11px;")
                    QTimer.singleShot(8000, poll_builder)

            QTimer.singleShot(8000, poll_builder)
        else:
            row[1].setEnabled(True)
            if len(row) > 2:
                row[2].setEnabled(True)
            QTimer.singleShot(1500, self._cache_refresh)

    def init_ui(self):
        self._vis_rules = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        btn_back = QPushButton("← Back to Chat")
        btn_back.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #EF4444, stop:1 #DC2626);
                color: #FFFFFF; border: 1.5px solid #F87171; border-radius: 10px;
                padding: 7px 16px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: #DC2626; border-color: #FCA5A5; }
        """)
        btn_back.clicked.connect(self.back_to_chat.emit)
        hdr.addWidget(btn_back)

        title_lbl = QLabel("⚙️ Preferences & Configuration")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #F8F4FF; border: none;")
        hdr.addWidget(title_lbl)
        hdr.addStretch()

        btn_save_top = QPushButton("✓ Save Preferences")
        btn_save_top.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #10B981, stop:1 #059669);
                color: #FFFFFF; border: 1.5px solid #34D399; border-radius: 10px;
                padding: 7px 18px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: #059669; border-color: #6EE7B7; }
        """)
        btn_save_top.clicked.connect(self.save_preferences)
        hdr.addWidget(btn_save_top)
        layout.addLayout(hdr)

        # Tab Widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1.5px solid rgba(147, 51, 234, 0.3);
                border-radius: 12px;
                background: rgba(14, 10, 24, 0.6);
            }
            QTabBar::tab {
                background: rgba(255, 255, 255, 0.05);
                color: #CBD5E1;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-bottom: none;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                padding: 10px 20px;
                font-size: 12px;
                font-weight: bold;
                min-width: 120px;
            }
            QTabBar::tab:selected {
                background: rgba(147, 51, 234, 0.7);
                color: #FFFFFF;
                border: 1.5px solid #C084FC;
                border-bottom: 1.5px solid rgba(147, 51, 234, 0.7);
            }
            QTabBar::tab:hover:!selected {
                background: rgba(147, 51, 234, 0.3);
                color: #F8F4FF;
            }
        """)
        layout.addWidget(self.tab_widget, stretch=1)

        # ============================================================
        # TAB 1: 🎵 Audio & Voice
        # ============================================================
        tab_audio, content_audio, form_audio = self._make_tab("🎵 Audio & Voice")
        self.tab_widget.addTab(tab_audio, "🎵 Audio & Voice")

        # ────────── 🎵 Cel's Voice - one choice, three engines ──────────
        # Legacy = archived Cerebellium v1.5 cellium bloop
        # Modern = Oct-12 melodii multi-beep bank
        # Realistic = Oxford phonetic-studio formant synth (profile picker below)
        # Choosing one silently sets both the UI sound pack and Cel's typing
        # mode so they always match - no more two dropdowns fighting each other.
        self.combo_cel_voice = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_cel_voice)
        self.combo_cel_voice.addItems([
            "🕰️ Cel's Legacy Sound",
            "🎵 Cel's Modern Melodi",
            "✨ Cel's Realistic Voice",
        ])
        _saved_mode = normalize_cel_typing_mode(
            self.settings.get("typing_sound_mode", "Cel's Legacy Sound"))
        _label_by_key = {
            "Cel's Legacy Sound": "🕰️ Cel's Legacy Sound",
            "Cel's Modern Melodi": "🎵 Cel's Modern Melodi",
            "Cel's Realistic Voice": "✨ Cel's Realistic Voice",
        }
        _saved_label = _label_by_key.get(_saved_mode, "🕰️ Cel's Legacy Sound")
        _idx = self.combo_cel_voice.findText(_saved_label)
        if _idx >= 0:
            self.combo_cel_voice.setCurrentIndex(_idx)

        _MODE_LABELS = {
            "🕰️ Cel's Legacy Sound": "Cel's Legacy Sound",
            "🎵 Cel's Modern Melodi": "Cel's Modern Melodi",
            "✨ Cel's Realistic Voice": "Cel's Realistic Voice",
        }

        def _on_cel_voice_changed(_text):
            _mode = _MODE_LABELS[_text]
            self.settings["typing_sound_mode"] = _mode
            # Match the UI sound pack to the chosen engine so clicks feel right.
            self.settings["sound_pack"] = (
                "Cel's Original Sound" if _mode == "Cel's Legacy Sound"
                else "Cel's New Sounds")
            _show = _mode == "Cel's Realistic Voice"
            self._lbl_realistic_voice.setVisible(_show)
            self.combo_realistic_voice.setVisible(_show)
            self.btn_preview_realistic.setVisible(_show)

        self.combo_cel_voice.currentTextChanged.connect(_on_cel_voice_changed)
        self._make_input_row(form_audio, "🎵 Cel's Voice:", self.combo_cel_voice)

        # Realistic voice profile picker - shown only when Realistic is chosen.
        # Keeps the 16 Oxford/Melodii profiles auditable without cluttering the
        # Legacy / Modern views.
        self.combo_realistic_voice = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_realistic_voice)
        for _key in ("melodii_f", "melodii_m", "human_f", "human_m", "child",
                     "old_man", "whistle", "guitar", "celesta", "ocarina",
                     "kalimba", "rhodes", "cello", "seraph", "choir", "animalese"):
            _vdef = _sound_cfg.REALISTIC_VOICE_PROFILES[_key]
            # The label ALREADY carries its own icon - prepending `icon` a
            # second time is what produced "🧒 🧒 Child Voice - Bright Kid".
            self.combo_realistic_voice.addItem(
                str(_vdef.get("label") or _key), _key)
        _saved_profile = self.settings.get(
            "realistic_voice_profile", _sound_cfg.DEFAULT_REALISTIC_VOICE)
        _prof_idx = self.combo_realistic_voice.findData(_saved_profile)
        if _prof_idx >= 0:
            self.combo_realistic_voice.setCurrentIndex(_prof_idx)

        self._lbl_realistic_voice = QLabel("Cel's Realistic Voice profile:")
        self._lbl_realistic_voice.setStyleSheet(
            "border: none; color: #F8F4FF;")
        self.btn_preview_realistic = QPushButton("▶ Preview")
        self.btn_preview_realistic.setProperty("silent_preview", True)
        self.btn_preview_realistic.setStyleSheet("""
            QPushButton {
                background: rgba(147, 51, 234, 0.4); color: #F8F4FF; border: 1px solid #9333EA;
                border-radius: 8px; padding: 5px 12px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.7); }
        """)
        self.btn_preview_realistic.setToolTip(
            "Speaks a short line in the selected realistic voice.")
        self.btn_preview_realistic.clicked.connect(
            lambda: play_realistic_voice_preview(
                self.combo_realistic_voice.currentData()
                or _sound_cfg.DEFAULT_REALISTIC_VOICE))

        h_realistic = QHBoxLayout()
        h_realistic.addWidget(self._lbl_realistic_voice)
        h_realistic.addWidget(self.combo_realistic_voice, stretch=1)
        h_realistic.addWidget(self.btn_preview_realistic)
        form_audio.addLayout(h_realistic)

        _show_initial = _saved_mode == "Cel's Realistic Voice"
        self._lbl_realistic_voice.setVisible(_show_initial)
        self.combo_realistic_voice.setVisible(_show_initial)
        self.btn_preview_realistic.setVisible(_show_initial)

        # Streaming Text Flow
        self.combo_streaming_mode = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_streaming_mode)
        self.combo_streaming_mode.addItems(["Letter-by-Letter (Smooth & Musical)", "Word-by-Word (Instant Chunks)"])
        cur_mode = self.settings.get("streaming_mode", "Letter-by-Letter")
        self.combo_streaming_mode.setCurrentIndex(1 if cur_mode == "Word-by-Word" else 0)
        self._make_input_row(form_audio, "Streaming Text Flow:", self.combo_streaming_mode)

        # Typing Animation Speed
        self.combo_text_speed = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_text_speed)
        self.combo_text_speed.addItems(["Normal (Balanced)", "Fast (Express)", "Slow (Cozy)", "Instant (No Animation)"])
        cur_spd = self.settings.get("text_speed", "Normal")
        idx_spd = next((i for i, opt in enumerate(["Normal", "Fast", "Slow", "Instant"]) if opt in cur_spd), 0)
        self.combo_text_speed.setCurrentIndex(idx_spd)
        self._make_input_row(form_audio, "Typing Animation Speed:", self.combo_text_speed)

        # TTS Voice Host Engine
        self.combo_voice_host = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_voice_host)
        self.combo_voice_host.addItems(["Kokoro (Offline)", "Edge TTS (Online)"])
        cur_vhost = self.settings.get("voice_host", "Kokoro (Offline)")
        idx_vh = self.combo_voice_host.findText(cur_vhost)
        if idx_vh != -1: self.combo_voice_host.setCurrentIndex(idx_vh)
        self._make_input_row(form_audio, "TTS Voice Host Engine:", self.combo_voice_host)

        # TTS Spoken Voice
        self.combo_tts_voice = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_tts_voice)
        self._make_input_row(form_audio, "TTS Spoken Voice:", self.combo_tts_voice)

        def _update_voice_dropdown(host_name):
            self.combo_tts_voice.blockSignals(True)
            self.combo_tts_voice.clear()
            v_list = KOKORO_VOICES if host_name == "Kokoro (Offline)" else EDGE_VOICES
            saved_v = self.settings.get("tts_voice", "af_heart" if host_name == "Kokoro (Offline)" else "en-US-JennyNeural")
            sel_idx = 0
            for i, (v_lbl, v_id) in enumerate(v_list):
                self.combo_tts_voice.addItem(v_lbl, v_id)
                if v_id == saved_v:
                    sel_idx = i
            self.combo_tts_voice.setCurrentIndex(sel_idx)
            self.combo_tts_voice.blockSignals(False)

        self.combo_voice_host.currentTextChanged.connect(_update_voice_dropdown)
        _update_voice_dropdown(self.combo_voice_host.currentText())

        # TTS Options
        self.chk_skip_asterisks = self._style_check(QCheckBox("🤫 Strip Asterisks & Roleplay Actions from TTS (e.g. *giggles*, *sighs*)"))
        self.chk_skip_asterisks.setChecked(self.settings.get("tts_skip_asterisks", True))
        form_audio.addWidget(self.chk_skip_asterisks)

        self.chk_animalese = self._style_check(QCheckBox("🎶 Cel Animal Crossing / Mellodi Musical Voice (Melodious speech tones)"))
        self.chk_animalese.setChecked(self.settings.get("animalese_voice", True))
        form_audio.addWidget(self.chk_animalese)

        # Cel Voice Style
        self.combo_cel_style = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_cel_style)
        for _vn, _vd in CEL_VOICE_VARIANTS.items():
            self.combo_cel_style.addItem(_vd.get("label", _vn), _vn)
        _saved_style = self.settings.get("ac_voice_variant", "Classic AC")
        _style_idx = self.combo_cel_style.findData(_saved_style)
        if _style_idx >= 0:
            self.combo_cel_style.setCurrentIndex(_style_idx)
        btn_preview_cel = QPushButton("▶ Preview")
        btn_preview_cel.setProperty("silent_preview", True)
        btn_preview_cel.setStyleSheet("""
            QPushButton {
                background: rgba(147, 51, 234, 0.4); color: #F8F4FF; border: 1px solid #9333EA;
                border-radius: 8px; padding: 5px 12px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.7); }
        """)
        btn_preview_cel.setToolTip(
            "Plays a short melody in the selected Cel voice.")
        btn_preview_cel.clicked.connect(
            lambda: play_cel_voice_preview(
                self.combo_cel_style.currentData() or "Classic AC"))
        h_cel_style = QHBoxLayout()
        h_cel_style.addWidget(QLabel("🎻 Cel Voice Style:"))
        h_cel_style.addWidget(self.combo_cel_style, stretch=1)
        h_cel_style.addWidget(btn_preview_cel)
        form_audio.addLayout(h_cel_style)

        self.chk_kokoro_preload = self._style_check(QCheckBox(
            "🚀 Preload Kokoro TTS at Startup (instant speaker button, ~200MB RAM)"))
        self.chk_kokoro_preload.setChecked(self.settings.get("kokoro_preload", True))

        self.chk_hist_nav = self._style_check(QCheckBox(
            "⌨️ Shift+PageUp/PageDown browses input history (keeps unsent draft)"))
        self.chk_hist_nav.setChecked(self.settings.get("history_shift_nav", True))

        # ── chat-only options, kept home in Audio & Voice ───────────────
        form_audio.addWidget(self.chk_kokoro_preload)

        # Cel's voice on/off. The combo picks *what* she sounds like; this is
        # whether she makes a sound at all while her reply types out.
        self.chk_cel_typing = self._style_check(QCheckBox(
            "🔊 Let Cel make typing sounds as she replies"))
        self.chk_cel_typing.setChecked(bool(
            self.settings.get("typing_sound_enabled", True)))
        self.chk_cel_typing.setToolTip(
            "Independent of your own keyboard sounds below and of her spoken "
            "voice - this is only the tick while her text appears.")
        form_audio.addWidget(self.chk_cel_typing)

        self.chk_typing_anim = self._style_check(QCheckBox(
            "✨ Animate her typing (off = text appears as fast as she writes)"))
        self.chk_typing_anim.setChecked(bool(
            self.settings.get("typing_animation", True)))
        form_audio.addWidget(self.chk_typing_anim)

        # ── the user's own keyboard channel ──────────────────────────────
        # Cel's streaming voice and *your* keystrokes used to be one setting,
        # so changing her voice changed yours and muting her muted you.
        self.chk_user_typing = self._style_check(QCheckBox(
            "⌨️ Play a sound when I type"))
        self.chk_user_typing.setChecked(bool(
            self.settings.get("user_typing_sound_enabled", True)))
        form_audio.addWidget(self.chk_user_typing)

        self.combo_user_typing = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_user_typing)
        self.combo_user_typing.addItems(list(TYPING_SOUND_MODES))
        _ut = self.combo_user_typing.findText(str(self.settings.get(
            "user_typing_sound_mode", "Normal (UI clicks")))
        self.combo_user_typing.setCurrentIndex(_ut if _ut >= 0 else 0)
        h_user_typing = self._make_input_row(
            form_audio, "🖱️ My typing sound:", self.combo_user_typing)

        self.slider_user_typing, self.lbl_user_typing = self._make_slider_row(
            form_audio, "My typing volume:",
            int(self.settings.get("user_typing_sound_volume", 40)), 0, 250, "%")
        self._bind_dependent(self.chk_user_typing,
                             [h_user_typing, self.slider_user_typing,
                              self.lbl_user_typing],
                             lambda s: s.isChecked())

        self.slider_tts_volume, self.lbl_tts_volume = self._make_slider_row(
            form_audio, "Cel voice volume (TTS):",
            int(float(self.settings.get("tts_volume", 100))), 10, 250, "%")
        try:
            self.slider_tts_volume.setToolTip(
                "Kokoro + Edge spoken replies. Over 100% uses soft saturation so 200% is loud, not crunchy.")
        except Exception:
            pass

        # ── per-sound volume + custom files ──────────────────────────────
        # `audio_volumes` and `custom_sounds` were two dead keys for months.
        # They now drive play_ui_sound() for real: a row per sound, your own
        # volume, and any .wav you want instead of the pack's.
        from PySide6.QtWidgets import QGridLayout
        self._add_section_header(form_audio, "🔊 Per-Sound Tuning", "#6EE7B7", 10)
        lbl_sound_hint = QLabel(
            "Volume 0 mutes just that sound. Browse… replaces the bundled "
            "sample with any .wav on this machine.")
        lbl_sound_hint.setWordWrap(True)
        lbl_sound_hint.setStyleSheet(
            "color: rgba(233, 213, 255, 0.70); font-size: 11px;")
        form_audio.addWidget(lbl_sound_hint)

        self._custom_sound_paths = {}
        _existing = self.settings.get("custom_sounds")
        if isinstance(_existing, dict):
            self._custom_sound_paths = {str(k): str(v) for k, v in _existing.items()
                                        if str(v or "").strip()}
        _vols = self.settings.get("audio_volumes")
        _vols = _vols if isinstance(_vols, dict) else {}

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        self.sound_rows = {}
        for i, name in enumerate(TUNABLE_SOUNDS):
            pretty = name.replace("_", " ").title()
            lbl = QLabel(pretty)
            lbl.setStyleSheet(
                "color: rgba(248, 244, 255, 0.9); font-size: 12px;")
            sld = QSlider(Qt.Orientation.Horizontal)
            sld.setRange(0, 250)
            try:
                sld.setValue(int(_vols.get(name, 100)))
            except (TypeError, ValueError):
                sld.setValue(100)
            sld.setFixedWidth(130)
            vol = QLabel(f"{sld.value()}%")
            vol.setFixedWidth(38)
            vol.setStyleSheet(
                "color: #6EE7B7; font-size: 11px; font-weight: bold;")
            sld.valueChanged.connect(
                lambda val, _n=name, _lbl=vol, _sw=self: _live_sound_vol(_sw, _n, val, _lbl))
            cur = QLabel(Path(str(self._custom_sound_paths.get(name, ""))).name
                         if self._custom_sound_paths.get(name) else "bundled")
            cur.setStyleSheet(
                "color: rgba(233, 213, 255, 0.6); font-size: 10px;")
            browse = QPushButton("Browse…")
            browse.setFixedHeight(24)
            browse.setStyleSheet("""
                QPushButton{background:rgba(52,211,153,0.22);color:#ECFDF5;
                  border:1px solid rgba(52,211,153,0.45);border-radius:8px;
                  padding:2px 10px;font-size:11px;}
                QPushButton:hover{background:rgba(52,211,153,0.45);}
            """)
            browse.clicked.connect(
                lambda _=False, n=name: self._pick_custom_sound(n))
            clr = QPushButton("✕")
            clr.setFixedSize(24, 24)
            clr.setToolTip("Use the bundled sound again")
            clr.setStyleSheet("""
                QPushButton{background:rgba(255,255,255,0.06);color:#E9D5FF;
                  border:1px solid rgba(192,132,252,0.35);border-radius:8px;
                  font-size:11px;}
                QPushButton:hover{background:rgba(239,68,68,0.35);}
            """)
            clr.clicked.connect(lambda _=False, n=name: self._clear_custom_sound(n))
            grid.addWidget(lbl, i, 0)
            grid.addWidget(sld, i, 1)
            grid.addWidget(vol, i, 2)
            grid.addWidget(cur, i, 3)
            grid.addWidget(browse, i, 4)
            grid.addWidget(clr, i, 5)
            self.sound_rows[name] = (sld, vol, cur)
        grid.setColumnStretch(3, 1)
        form_audio.addLayout(grid)

        form_audio.addWidget(self.chk_hist_nav)

        # ============================================================
        # TAB 2: 🎙️ Live Mode
        #
        # A call is its own context - its own voice, its own mic, its own
        # input engine. None of it belongs in "Audio & Voice", which is about
        # what Cel sounds like *in chat*, and having it all in one tab is how
        # the live options ended up buried under chat options nobody in a call
        # ever touches.
        # ============================================================
        tab_live, content_live, form_live = self._make_tab("🎙️ Live Mode")
        self.tab_widget.addTab(tab_live, "🎙️ Live Mode")

        self._add_section_header(form_live, "📞 Cel's Call Voice")

        from ..live.controls import TTS_HOST_CHOICES

        self.combo_live_host = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_live_host)
        self.combo_live_host.addItems(list(TTS_HOST_CHOICES))
        _cur_host = self.settings.get("live_voice", "Kokoro (Offline)")
        _idx_host = self.combo_live_host.findText(_cur_host)
        if _idx_host >= 0:
            self.combo_live_host.setCurrentIndex(_idx_host)
        self._make_input_row(form_live, "Speech engine:", self.combo_live_host)

        self.combo_live_voice = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_live_voice)

        def _fill_live_voices(host_name):
            from ...core.utils import EDGE_VOICES, KOKORO_VOICES
            self.combo_live_voice.blockSignals(True)
            self.combo_live_voice.clear()
            pool = (KOKORO_VOICES if host_name == "Kokoro (Offline)"
                    else EDGE_VOICES)
            saved = self.settings.get("live_voice_id", "")
            sel = 0
            for i, (_lbl, _vid) in enumerate(pool):
                self.combo_live_voice.addItem(_lbl, _vid)
                if _vid == saved:
                    sel = i
            self.combo_live_voice.setCurrentIndex(sel)
            self.combo_live_voice.blockSignals(False)

        self.combo_live_host.currentTextChanged.connect(_fill_live_voices)
        _fill_live_voices(self.combo_live_host.currentText())

        btn_preview_live = QPushButton("▶ Preview")
        btn_preview_live.setStyleSheet("""
            QPushButton {
                background: rgba(147, 51, 234, 0.4); color: #F8F4FF; border: 1px solid #9333EA;
                border-radius: 8px; padding: 5px 12px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.7); }
        """)
        btn_preview_live.setToolTip(
            'Speaks "Hi, I\'m Cel, and this is the voice you selected." through '
            "the same engine the call itself uses.")
        btn_preview_live.clicked.connect(self._preview_live_voice)
        h_live_voice = QHBoxLayout()
        h_live_voice.addWidget(QLabel("🎙️ Voice:"))
        h_live_voice.addWidget(self.combo_live_voice, stretch=1)
        h_live_voice.addWidget(btn_preview_live)
        form_live.addLayout(h_live_voice)

        # ── Voice input ────────────────────────────────────────────────
        self._add_section_header(form_live, "🎙️ Voice Input - Speech to Text", "#38BDF8", 10)

        self.combo_stt = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_stt)
        self.combo_stt.addItems([
            STT_LOCAL_GGML,
            "Groq Whisper (Fastest)",
            "Google Speech (Free)",
            "Hugging Face Whisper",
            "OpenAI Whisper",
        ])
        self.combo_stt.setCurrentText(norm_stt_engine(
            self.settings.get("voice_stt_engine", STT_LOCAL_GGML)))
        self._make_input_row(form_live, "Default Voice Engine:", self.combo_stt)

        # ── Model paths (each row shown only by the engine that reads it) ─
        # The local engine is ggml/whisper.cpp - Kokoro only *speaks*. The old
        # code hardcoded ~/Documents/Projects/Python/Kokoro (does not exist),
        # so every recording died with "Missing ggml-base.en-q5_1.bin".
        _path_qss = """
            QLineEdit {
                background: rgba(22, 14, 38, 0.42);
                color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45);
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 12px;
            }
            QLineEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QLineEdit:focus { border: 1.5px solid #A855F7; }
        """
        _btn_qss = """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #8A2BE2, stop:1 #A855F7);
                color: white; border: none; border-radius: 10px;
                padding: 8px 14px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: #C084FC; }
        """

        lbl_ggml = QLabel("ggml model file:")
        lbl_ggml.setStyleSheet("border: none; color: #F8F4FF;")
        self.edit_stt_ggml = QLineEdit()
        try:
            _ggml_hint = str(resolve_ggml_path(
                self.settings.get("stt_ggml_path", "")))
        except Exception:
            _ggml_hint = str(KOKORO_DIR / "ggml-base.en-q5_1.bin")
        self.edit_stt_ggml.setPlaceholderText(_ggml_hint)
        self.edit_stt_ggml.setText(
            str(self.settings.get("stt_ggml_path", "") or ""))
        self.edit_stt_ggml.setStyleSheet(_path_qss)
        btn_ggml = QPushButton("Browse…")
        btn_ggml.setStyleSheet(_btn_qss)

        def _pick_ggml():
            start = self.edit_stt_ggml.text().strip() or _ggml_hint
            try:
                path, _f = QFileDialog.getOpenFileName(
                    self, "Choose ggml (whisper.cpp) model", start,
                    "Model files (*.bin *.gguf);;All Files (*)")
            except Exception:
                path = ""
            if path:
                self.edit_stt_ggml.setText(path)

        btn_ggml.clicked.connect(_pick_ggml)
        h_ggml = QHBoxLayout()
        h_ggml.setContentsMargins(0, 0, 0, 0)
        h_ggml.setSpacing(8)
        h_ggml.addWidget(lbl_ggml)
        h_ggml.addWidget(self.edit_stt_ggml, stretch=1)
        h_ggml.addWidget(btn_ggml)
        form_live.addLayout(h_ggml)
        # Only the local engine reads that file.
        self._bind_dependent(self.combo_stt, [h_ggml],
                             lambda s: "Local" in s.currentText())

        lbl_tts = QLabel("Kokoro TTS folder:")
        lbl_tts.setStyleSheet("border: none; color: #F8F4FF;")
        self.edit_kokoro_tts = QLineEdit()
        self.edit_kokoro_tts.setPlaceholderText(str(KOKORO_DIR))
        self.edit_kokoro_tts.setText(
            str(self.settings.get("kokoro_tts_dir", "") or ""))
        self.edit_kokoro_tts.setStyleSheet(_path_qss)
        btn_tts = QPushButton("Browse…")
        btn_tts.setStyleSheet(_btn_qss)

        def _pick_tts():
            start = self.edit_kokoro_tts.text().strip() or str(KOKORO_DIR)
            try:
                path = QFileDialog.getExistingDirectory(
                    self, "Choose Kokoro TTS folder", start)
            except Exception:
                path = ""
            if path:
                self.edit_kokoro_tts.setText(path)

        btn_tts.clicked.connect(_pick_tts)
        h_tts = QHBoxLayout()
        h_tts.setContentsMargins(0, 0, 0, 0)
        h_tts.setSpacing(8)
        h_tts.addWidget(lbl_tts)
        h_tts.addWidget(self.edit_kokoro_tts, stretch=1)
        h_tts.addWidget(btn_tts)
        form_live.addLayout(h_tts)
        # The folder only matters while Kokoro is the speaking host.
        self._bind_dependent(self.combo_voice_host, [h_tts],
                             lambda s: s.currentText() == "Kokoro (Offline)")

        # ── The key this engine needs ─────────────────────────────────
        # Groq is the shipped default and needs a credential nobody has, so
        # picking it used to fail at the first utterance - and the failure was
        # typed into the chat box as if you had said it. The credential box
        # appears only for engines that need one, pre-filled with whatever is
        # already stored, and disappears for Local/Google.
        self._stt_key_row = QHBoxLayout()
        self._stt_key_row.setContentsMargins(0, 0, 0, 0)
        self._stt_key_row.setSpacing(8)
        self.edit_stt_key = QLineEdit()
        self.edit_stt_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_stt_key.setPlaceholderText("gsk_…")
        self.edit_stt_key.setStyleSheet("""
            QLineEdit {
                background: rgba(22, 14, 38, 0.42);
                color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45);
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 12px;
            }
            QLineEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QLineEdit:focus { border: 2px solid #C084FC; }
        """)
        btn_stt_key = QPushButton("💾 Save key")
        btn_stt_key.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_stt_key.setToolTip(
            "Stores the key on this machine for this engine only.")
        btn_stt_key.setStyleSheet("""
            QPushButton {
                background: rgba(16, 185, 129, 0.35); color: #ECFDF5;
                border: 1px solid #34D399; border-radius: 8px;
                padding: 6px 12px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: rgba(16, 185, 129, 0.6); }
        """)
        btn_stt_key.clicked.connect(self._save_stt_key)
        lbl_stt_key = QLabel("🔑 API key:")
        lbl_stt_key.setStyleSheet("border: none; color: #F8F4FF;")
        self._stt_key_row.addWidget(lbl_stt_key)
        self._stt_key_row.addWidget(self.edit_stt_key, stretch=1)
        self._stt_key_row.addWidget(btn_stt_key)
        form_live.addLayout(self._stt_key_row)
        self.lbl_stt_key = QLabel("")
        self.lbl_stt_key.setWordWrap(True)
        self.lbl_stt_key.setStyleSheet(
            "color: rgba(167, 243, 208, 0.8); font-size: 11px; border: none;")
        form_live.addWidget(self.lbl_stt_key)
        self.combo_stt.currentTextChanged.connect(self._sync_stt_key_row)
        self._sync_stt_key_row()

        self.chk_multi_stt = self._style_check(QCheckBox(
            "🚀 Multi-Engine Mode (record once, transcribe in parallel & pick the best to edit)"))
        self.chk_multi_stt.setChecked(self.settings.get("voice_multi_mode", False))
        self.chk_multi_stt.setToolTip(
            "Runs two speech engines at once. It is noticeably heavier, and "
            "with only the local engine loaded there is nothing to race "
            "against - which is why it is hidden there.")
        form_live.addWidget(self.chk_multi_stt)

        # ── Noise cancellation (moved out of Audio & Voice: it only ever
        #    mattered for the call) ──────────────────────────────────────
        self._add_section_header(form_live, "🧹 Noise Cancellation", "#6EE7B7", 10)
        self.chk_noise = self._style_check(QCheckBox(
            "🧹 Subtract room noise from my mic (fans, hum, hiss)"))
        self.chk_noise.setChecked(bool(self.settings.get("noise_cancel_enabled", True)))
        form_live.addWidget(self.chk_noise)
        self.slider_noise, self.lbl_noise = self._make_slider_row(
            form_live, "Cancellation strength:",
            int(self.settings.get("noise_cancel_strength", 70)), 0, 100, "%"
        )
        h_noise = QHBoxLayout()
        btn_cal_noise = QPushButton("🧹 Calibrate microphone…")
        btn_cal_noise.setStyleSheet("""
            QPushButton {
                background: rgba(52, 211, 153, 0.35); color: #ECFDF5;
                border: 1px solid #34D399; border-radius: 8px;
                padding: 5px 12px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: rgba(52, 211, 153, 0.6); }
        """)
        btn_cal_noise.setToolTip(
            "Listen to a few seconds of your quiet room and store it as the "
            "noise profile Cel subtracts from the mic.")
        btn_cal_noise.clicked.connect(self._calibrate_noise)
        h_noise.addWidget(btn_cal_noise)
        h_noise.addStretch(1)
        form_live.addLayout(h_noise)
        self.lbl_noise_profile = QLabel(self._noise_profile_text())
        self.lbl_noise_profile.setWordWrap(True)
        self.lbl_noise_profile.setStyleSheet(
            "color: rgba(167, 243, 208, 0.8); font-size: 11px; border: none;")
        form_live.addWidget(self.lbl_noise_profile)

        # ── Wake word ───────────────────────────────────────────────────
        self._add_section_header(form_live, "🎧 Wake Word & Activation", "#C084FC", 10)
        self.chk_wake = self._style_check(QCheckBox(
            "🎧 Listen for my wake phrase (hands-free - opens Live Mode; keeps the mic while ON)"))
        self.chk_wake.setChecked(bool(self.settings.get("listen_activation", False)))
        form_live.addWidget(self.chk_wake)

        self.edit_wake_phrase = QLineEdit(
            self.settings.get("live_wake_phrase", "Okay Cel"))
        self.edit_wake_phrase.setPlaceholderText("Okay Cel")
        self.edit_wake_phrase.setStyleSheet("""
            QLineEdit {
                background: rgba(22, 14, 38, 0.42);
                color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45);
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 12px;
            }
            QLineEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QLineEdit:focus { border: 2px solid #C084FC; }
        """)
        self.edit_wake_phrase.setToolTip(
            "She answers to this instead of “Okay Cel”. Two or more words is "
            "safest - a single short word matches by accident.")
        h_phrase = QHBoxLayout()
        h_phrase.addWidget(QLabel("Wake phrase:"))
        h_phrase.addWidget(self.edit_wake_phrase, stretch=1)
        form_live.addLayout(h_phrase)

        h_wake = QHBoxLayout()
        # The 10-sample Hey Cel wizard is retired - the bundled “Okay Cel”
        # model already knows the phrase. Tick the box, Save, say it.
        lbl_wake_hint = QLabel(
            "Bundled “Okay Cel” model - tick the box above, press "
            "✓ Save Preferences, and just say it. No training needed.")
        lbl_wake_hint.setWordWrap(True)
        lbl_wake_hint.setStyleSheet(
            "color: rgba(167, 243, 208, 0.8); font-size: 11px; border: none;")
        h_wake.addWidget(lbl_wake_hint)
        h_wake.addStretch(1)
        form_live.addLayout(h_wake)

        h_wengine = QHBoxLayout()
        h_wengine.addWidget(QLabel("Wake engine:"))
        self.combo_wake_engine = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_wake_engine)
        self.combo_wake_engine.addItems([
            "Auto (best available)",
            "openWakeWord (efficient)",
            "Legacy Whisper (compatible)",
        ])
        try:
            cur_we = str(self.settings.get("wake_engine", "auto") or "auto")
            idx_we = 0
            for i in range(self.combo_wake_engine.count()):
                txt = self.combo_wake_engine.itemText(i).lower()
                if cur_we.lower() in txt or txt.startswith(cur_we.lower()):
                    idx_we = i
                    break
            self.combo_wake_engine.setCurrentIndex(idx_we)
        except (RuntimeError, AttributeError):
            pass
        h_wengine.addWidget(self.combo_wake_engine, 1)
        form_live.addLayout(h_wengine)

        h_oww = QHBoxLayout()
        h_oww.addWidget(QLabel("Wake model (.onnx):"))
        self.edit_oww_model = QLineEdit(
            str(self.settings.get("wake_oww_model", "") or ""))
        self.edit_oww_model.setPlaceholderText(
            "hey_cel.onnx - train at openwakeword.com, drop it anywhere")
        h_oww.addWidget(self.edit_oww_model, 1)
        btn_oww_browse = QPushButton("Browse…")
        btn_oww_browse.clicked.connect(self._pick_oww_model)
        h_oww.addWidget(btn_oww_browse)
        form_live.addLayout(h_oww)

        h_oww_thr = QHBoxLayout()
        h_oww_thr.addWidget(QLabel("Wake sensitivity:"))
        self.slider_oww_thr = QSlider(Qt.Orientation.Horizontal)
        self.slider_oww_thr.setRange(5, 95)
        try:
            self.slider_oww_thr.setValue(int(float(
                self.settings.get("wake_oww_threshold", 0.5)) * 100))
        except (TypeError, ValueError):
            self.slider_oww_thr.setValue(50)
        self.lbl_oww_thr = QLabel(f"{self.slider_oww_thr.value()}%")
        try:
            self.slider_oww_thr.valueChanged.connect(
                lambda v: self.lbl_oww_thr.setText(f"{v}%"))
        except (RuntimeError, AttributeError):
            pass
        h_oww_thr.addWidget(self.slider_oww_thr, 1)
        h_oww_thr.addWidget(self.lbl_oww_thr)
        form_live.addLayout(h_oww_thr)

        # ── Mic behaviour ───────────────────────────────────────────────
        self._add_section_header(form_live, "🎚️ Live Mic Behaviour", "#F472B6", 10)

        self.chk_ptt = self._style_check(QCheckBox(
            "🎯 Push-to-talk (the mic only listens while you hold the key)"))
        self.chk_ptt.setChecked(bool(self.settings.get("live_push_to_talk", False)))
        self.chk_ptt.setToolTip(
            "Hold the push-to-talk key to talk and release it to send. "
            "Nothing is recorded the rest of the time - no accidental turns, "
            "no waiting for the silence timer.")
        form_live.addWidget(self.chk_ptt)

        # ── Bind key to push-to-talk ────────────────────────────────────
        # QKeySequenceEdit *is* the "press a key and wait" widget: it captures
        # the next chord, names it, and can be cleared. Hand-rolling key
        # capture is how you end up binding Escape.
        from PySide6.QtGui import QKeySequence as _QKS
        from PySide6.QtWidgets import QKeySequenceEdit as _QKSE
        self.edit_ptt_key = _QKSE(self)
        self.edit_ptt_key.setMaximumSequenceLength(1)
        self.edit_ptt_key.setClearButtonEnabled(True)
        self.edit_ptt_key.setToolTip(
            "Click, then press the key (or chord) you want to hold while "
            "talking. Escape is refused on purpose - you need a way out.")
        try:
            seq = _QKS(str(self.settings.get("live_ptt_key", "Space")))
            if seq.count():
                self.edit_ptt_key.setKeySequence(seq)
        except Exception:
            pass
        self.edit_ptt_key.keySequenceChanged.connect(self._on_ptt_key_changed)

        h_pttkey = QHBoxLayout()
        h_pttkey.addWidget(QLabel("Bind key to push-to-talk:"))
        h_pttkey.addWidget(self.edit_ptt_key)
        lbl_pttkey = QLabel("Held while you speak, released to send.")
        h_pttkey.addWidget(lbl_pttkey)
        h_pttkey.addStretch(1)
        form_live.addLayout(h_pttkey)
        # A binding for a mode that is off is a lie - grey it out.
        self._bind_dependent(self.chk_ptt, [h_pttkey],
                             lambda s: s.isChecked())

        self.chk_live_autosend = self._style_check(QCheckBox(
            "✅ Auto-send what I say (off = she waits for you to confirm)"))
        self.chk_live_autosend.setChecked(bool(self.settings.get("live_auto_send", True)))
        self.chk_live_autosend.setToolTip(
            "She only sends a turn that actually contains speech - an empty or "
            "noise-only transcript is discarded instead of sent.")
        form_live.addWidget(self.chk_live_autosend)

        self.chk_live_muted = self._style_check(QCheckBox(
            "🔇 Start every call muted (nothing is recorded until you unmute)"))
        self.chk_live_muted.setChecked(bool(self.settings.get("live_mic_muted", False)))
        form_live.addWidget(self.chk_live_muted)

        self.chk_live_names = self._style_check(QCheckBox(
            "👤 Display names of animation"))
        self.chk_live_names.setChecked(bool(
            self.settings.get("live_show_names", False)))
        self.chk_live_names.setToolTip(
            "Show the floating YOU/CEL name tags on the floating transcript "
            "bubbles. Off = clean interface for new users.")
        self.chk_live_names.toggled.connect(self._on_live_names_toggled)
        form_live.addWidget(self.chk_live_names)

        # ── Pet mode ───────────────────────────────────────────────────
        # The floating companion used to be reachable only from the right-click
        # menu, which made it feel like a demo. It is a real setting now: a
        # saved toggle, a size, and whether she narrates her replies.
        self._add_section_header(form_live, "🐾 Pet Mode", "#F9A8D4", 10)
        self.chk_pet_mode = self._style_check(QCheckBox(
            "🐾 Let Cel float around your desktop as a companion"))
        self.chk_pet_mode.setChecked(bool(
            self.settings.get("pet_mode_enabled", False)))
        self.chk_pet_mode.setToolTip(
            "A frameless always-on-top Cel you can drag anywhere. She reacts to "
            "every reply and follows live calls. Off = hidden, not deleted.")
        form_live.addWidget(self.chk_pet_mode)

        self.chk_pet_speak = self._style_check(QCheckBox(
            "💬 Show her replies in a speech bubble"))
        self.chk_pet_speak.setChecked(bool(
            self.settings.get("pet_speak_replies", True)))
        self.chk_pet_speak.setToolTip(
            "Her face reacts either way - this only controls the bubble.")
        form_live.addWidget(self.chk_pet_speak)

        self.slider_pet, self.lbl_pet = self._make_slider_row(
            form_live, "Pet size:",
            int(self.settings.get("pet_scale", 100) or 100), 40, 200, "%")
        self._bind_dependent(self.chk_pet_mode,
                             [self.chk_pet_speak, self.slider_pet,
                              self.lbl_pet],
                             lambda s: s.isChecked())
        lbl_pet_hint = QLabel(
            "Drag her by the round handle · double-click it for a greeting.")
        lbl_pet_hint.setWordWrap(True)
        form_live.addWidget(lbl_pet_hint)
        self._bind_dependent(self.chk_pet_mode, [lbl_pet_hint],
                             lambda s: s.isChecked())

        form_live.addStretch()

        # ── Live-tab conditional options ────────────────────────────────
        self._bind_dependent(
            self.chk_noise,
            [self.slider_noise, self.lbl_noise, btn_cal_noise, self.lbl_noise_profile],
            lambda s: s.isChecked())
        self._bind_dependent(
            self.chk_wake, [h_phrase, h_wake],
            lambda s: s.isChecked())
        self._bind_dependent(
            self.combo_wake_engine, [h_oww, h_oww_thr],
            lambda s: "Legacy" not in s.currentText())
        # Parallel transcription with a single local engine has nothing to
        # race against, and it is exactly the "two engines at once" lag.
        self._bind_dependent(
            self.combo_stt, [self.chk_multi_stt],
            lambda s: s.currentText() != STT_LOCAL_GGML)
        self._bind_dependent(
            self.chk_ptt, [self.chk_live_autosend],
            lambda s: not s.isChecked())

        # ── Audio-tab conditional options ───────────────────────────────
        # The AC voice-variant picker (Classic AC / Mellodi / …) only matters
        # when Cel's Modern Melodi is the chosen engine.
        self._bind_dependent(
            self.combo_cel_voice, [h_cel_style],
            lambda s: "Modern Melodi" in s.currentText())
        # Kokoro preload means nothing while Edge is the host.
        self._bind_dependent(
            self.combo_voice_host, [self.chk_kokoro_preload],
            lambda s: s.currentText() == "Kokoro (Offline)")

        form_audio.addStretch()

        # ============================================================
        # TAB 2: 🎨 Appearance
        # ============================================================
        tab_appearance, content_app, form_app = self._make_tab("🎨 Appearance")
        self.tab_widget.addTab(tab_appearance, "🎨 Appearance")

        self._add_section_header(form_app, "🔤 Chat Text", "#C084FC", 10)
        self.combo_font_scale = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_font_scale)
        self.combo_font_scale.addItems(list(FONT_SCALE_CHOICES))
        _fs = self.combo_font_scale.findText(str(self.settings.get(
            "font_scale", "Small (Default)")))
        self.combo_font_scale.setCurrentIndex(_fs if _fs >= 0 else 0)
        self.combo_font_scale.setToolTip(
            "Scales only the words inside message bubbles. Window zoom (Ctrl +"
            " / Ctrl -) scales everything - the two multiply.")
        self._make_input_row(form_app, "Message text size:",
                             self.combo_font_scale)
        self.chk_verbose_log = self._style_check(QCheckBox(
            "🧰 Write a dev log file (celstudio_app.log)"))
        self.chk_verbose_log.setChecked(bool(
            self.settings.get("verbose_logging", True)))
        self.chk_verbose_log.setToolTip(
            "Off stops the on-disk log from growing. The in-app log viewer and "
            "the console keep working either way.")
        form_app.addWidget(self.chk_verbose_log)

        self._add_section_header(form_app, "🖼️ CelStudio Glass & Wallpaper Saturation")

        # Dark Overlay Tint
        self.slider_tint, self.lbl_tint = self._make_slider_row(
            form_app, "Dark Overlay Tint:",
            int(self.settings.get("wallpaper_tint", 0.32) * 100), 5, 95, "%"
        )

        # Panel Transparency
        self.slider_panel, self.lbl_panel = self._make_slider_row(
            form_app, "Panel Transparency:",
            int(self.settings.get("panel_opacity", 0.88) * 100), 0, 100, "%"
        )

        # Glass Blur
        self.slider_blur, self.lbl_blur = self._make_slider_row(
            form_app, "Glass Blur Radius:",
            int(self.settings.get("glass_blur", 16)), 0, 64, "px"
        )

        # Glass Opacity
        self.slider_glass_opacity, self.lbl_glass_opacity = self._make_slider_row(
            form_app, "Glass Panel Opacity:",
            int(self.settings.get("glass_opacity", 0.72) * 100), 0, 100, "%"
        )

        # ── Mouse wheel (#8) ──────────────────────────────────────────────
        # These used to live in "🌐 Network & API", where they made no sense,
        # and there was only ONE of them - it guarded combos while the label
        # promised to disable the scroll-wheel. Now there are two, and the chat
        # scroll area is genuinely covered.
        self._add_section_header(form_app, "🖱️ Mouse Wheel")
        self.chk_disable_wheel = self._style_check(
            QCheckBox("Lock dropdowns, spin boxes and sliders (needs focus)"))
        self.chk_disable_wheel.setChecked(self.settings.get("disable_combo_wheel", True))
        self.chk_disable_wheel.setToolTip(
            "Stops the wheel from silently changing dropdown / spin / slider "
            "values while you scroll past them.")
        form_app.addWidget(self.chk_disable_wheel)

        self.chk_disable_chat_wheel = self._style_check(
            QCheckBox("Block scrolling in the chat area"))
        self.chk_disable_chat_wheel.setChecked(
            self.settings.get("disable_chat_wheel", False))
        self.chk_disable_chat_wheel.setToolTip(
            "Off by default - turn this on only if you keep bumping the chat "
            "with the wheel. Ctrl+wheel zoom keeps working either way.")
        form_app.addWidget(self.chk_disable_chat_wheel)

        self._add_section_header(form_app, "🪟 Window & System Tray")
        self.chk_minimize_to_tray = self._style_check(
            QCheckBox("Minimize to system tray on window minimize (-) button"))
        self.chk_minimize_to_tray.setChecked(bool(self.settings.get("minimize_to_tray", False)))
        self.chk_minimize_to_tray.setToolTip(
            "Off by default - minimizing will minimize to taskbar. Check this if you want it to hide to tray.")
        form_app.addWidget(self.chk_minimize_to_tray)

        self.chk_close_to_tray = self._style_check(
            QCheckBox("Minimize to system tray on window close (X button)"))
        self.chk_close_to_tray.setChecked(bool(self.settings.get("close_to_tray", False)))
        self.chk_close_to_tray.setToolTip(
            "Off by default - clicking 'X' cleanly terminates the app. Check this if you want it to hide to tray.")
        form_app.addWidget(self.chk_close_to_tray)

        form_app.addStretch()

        # ============================================================
        # TAB 3: 🌐 Network & API
        # ============================================================
        tab_network, content_net, form_net = self._make_tab("🌐 Network & API")
        self.tab_widget.addTab(tab_network, "🌐 Network & API")

        self._add_section_header(form_net, "🌐 Network & Generation Limits")

        # Network Timeout
        self.spin_net_timeout = self._style_spin(QSpinBox())
        self.spin_net_timeout.setRange(3, 9999)
        self.spin_net_timeout.setSuffix(" s")
        self.spin_net_timeout.setValue(int(self.settings.get("network_timeout", 60)))
        self._make_input_row(form_net, "Network Timeout (seconds):", self.spin_net_timeout)

        # Network Max Retries
        self.spin_net_retries = self._style_spin(QSpinBox())
        self.spin_net_retries.setRange(1, 100)
        self.spin_net_retries.setValue(int(self.settings.get("network_max_retries", 5)))
        self._make_input_row(form_net, "Network Max Retries:", self.spin_net_retries)

        # Output Max Tokens
        self.spin_out_tokens = self._style_spin(QSpinBox())
        self.spin_out_tokens.setRange(16, 32768)
        self.spin_out_tokens.setValue(int(self.settings.get("output_max_tokens", 4096)))
        self._make_input_row(form_net, "Output Max Tokens:", self.spin_out_tokens)

        # NOTE: the scroll-wheel toggles moved to 🎨 Appearance (#8) - they are
        # interaction preferences, not network ones.

        # Custom Provider URLs
        self._add_section_header(form_net, "🔗 Custom Provider Endpoints", "#38BDF8", 10)
        self.edit_custom_urls = QTextEdit()
        self.edit_custom_urls.setPlainText(json.dumps(self.settings.get("custom_provider_urls", {}), indent=2))
        self.edit_custom_urls.setFixedHeight(100)
        self.edit_custom_urls.setStyleSheet("""
            QTextEdit {
                background: rgba(22, 14, 38, 0.42);
                color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45);
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 11px;
                font-family: monospace;
            }
            QTextEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QTextEdit:focus { border: 2px solid #C084FC; }
        """)
        form_net.addWidget(QLabel("Custom API Base URLs (JSON):"))
        form_net.addWidget(self.edit_custom_urls)

        form_net.addStretch()

        # ============================================================
        # TAB 4: 🖼️ Image Generation (Kaggle BYOK)
        # ============================================================
        tab_image, content_img, form_img = self._make_tab("🖼️ Image Generation")
        self.tab_widget.addTab(tab_image, "🖼️ Image Generation")

        self._add_section_header(form_img, "🔑 Kaggle Credentials (BYOK - your key, your quota)")

        # Username
        self.edit_kaggle_user = QLineEdit(self.settings.get("kaggle_username", ""))
        self.edit_kaggle_user.setPlaceholderText("your_kaggle_username")
        self.edit_kaggle_user.setStyleSheet("""
            QLineEdit {
                background: rgba(22, 14, 38, 0.42); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45); border-radius: 10px;
                padding: 8px 12px; font-size: 12px;
            }
            QLineEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QLineEdit:focus { border: 2px solid #C084FC; }
        """)
        self._make_input_row(form_img, "Kaggle Username:", self.edit_kaggle_user)

        # API Key (password field)
        self.edit_kaggle_key = QLineEdit(self.settings.get("kaggle_api_key", ""))
        self.edit_kaggle_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_kaggle_key.setPlaceholderText("kaggle.json API key")
        self.edit_kaggle_key.setStyleSheet("""
            QLineEdit {
                background: rgba(22, 14, 38, 0.42); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45); border-radius: 10px;
                padding: 8px 12px; font-size: 12px;
            }
            QLineEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QLineEdit:focus { border: 2px solid #C084FC; }
        """)
        self._make_input_row(form_img, "Kaggle API Key:", self.edit_kaggle_key)

        # Import kaggle.json button
        btn_import_kaggle = QPushButton("📥 Import kaggle.json")
        btn_import_kaggle.setIcon(QIcon(str(ASSETS_DIR / "attach.png")))
        btn_import_kaggle.setIconSize(QSize(16, 16))
        btn_import_kaggle.setStyleSheet("""
            QPushButton {
                background: rgba(147, 51, 234, 0.45); color: white;
                border: 1px solid #9333EA; border-radius: 8px;
                padding: 6px 12px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.7); border-color: #C084FC; }
        """)
        btn_import_kaggle.clicked.connect(self._import_kaggle_json)
        form_img.addWidget(btn_import_kaggle)

        # Test connection button
        self.btn_test_kaggle = QPushButton("🔍 Test Connection")
        self.btn_test_kaggle.setStyleSheet("""
            QPushButton {
                background: rgba(16, 185, 129, 0.45); color: white;
                border: 1px solid #10B981; border-radius: 8px;
                padding: 6px 12px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: rgba(16, 185, 129, 0.7); border-color: #34D399; }
        """)
        self.btn_test_kaggle.clicked.connect(self._test_kaggle_connection)
        form_img.addWidget(self.btn_test_kaggle)

        self.lbl_kaggle_test = QLabel("")
        self.lbl_kaggle_test.setStyleSheet("border: none; color: #6EE7B7; font-size: 11px; margin-top: 4px;")
        form_img.addWidget(self.lbl_kaggle_test)

        # Model Source
        self._add_section_header(form_img, "🤖 Model Source", "#38BDF8", 10)

        # Preset picker (Henny's Colab engines + public HF default)
        from cellium.services.kaggle_image import MODEL_PRESETS, preset_by_name
        self.combo_kaggle_preset = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_kaggle_preset)
        self.combo_kaggle_preset.addItems([p["name"] for p in MODEL_PRESETS])
        _saved_preset = self.settings.get("kaggle_preset", MODEL_PRESETS[0]["name"])
        _pi = self.combo_kaggle_preset.findText(_saved_preset)
        self.combo_kaggle_preset.setCurrentIndex(_pi if _pi >= 0 else 0)
        self.combo_kaggle_preset.currentTextChanged.connect(self._on_kaggle_preset_changed)
        self._make_input_row(form_img, "Model Preset:", self.combo_kaggle_preset)

        self.combo_kaggle_model_mode = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_kaggle_model_mode)
        self.combo_kaggle_model_mode.addItems(["HuggingFace (public repo)", "Civitai (single file URL)"])
        mode_idx = 0 if self.settings.get("kaggle_model_mode", "huggingface") == "huggingface" else 1
        self.combo_kaggle_model_mode.setCurrentIndex(mode_idx)
        self.combo_kaggle_model_mode.currentIndexChanged.connect(self._on_kaggle_model_mode_changed)
        self._make_input_row(form_img, "Model Source:", self.combo_kaggle_model_mode)

        # HuggingFace fields
        self.edit_kaggle_hf_model = QLineEdit(self.settings.get("kaggle_hf_model", "lykon/dreamshaper-xl-v2-turbo"))
        self.edit_kaggle_hf_model.setPlaceholderText("e.g. lykon/dreamshaper-xl-v2-turbo")
        self.edit_kaggle_hf_model.setStyleSheet("""
            QLineEdit {
                background: rgba(22, 14, 38, 0.42); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45); border-radius: 10px;
                padding: 8px 12px; font-size: 12px;
            }
            QLineEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QLineEdit:focus { border: 2px solid #C084FC; }
        """)
        self._row_kaggle_hf_model = self._make_input_row(
            form_img, "HF Repo ID:", self.edit_kaggle_hf_model)

        self.edit_kaggle_hf_token = QLineEdit(self.settings.get("kaggle_hf_token", ""))
        self.edit_kaggle_hf_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_kaggle_hf_token.setPlaceholderText("hf_xxx... (optional)")
        self.edit_kaggle_hf_token.setStyleSheet("""
            QLineEdit {
                background: rgba(22, 14, 38, 0.42); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45); border-radius: 10px;
                padding: 8px 12px; font-size: 12px;
            }
            QLineEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QLineEdit:focus { border: 2px solid #C084FC; }
        """)
        self._row_kaggle_hf_token = self._make_input_row(
            form_img, "HF Token:", self.edit_kaggle_hf_token)

        # Civitai fields
        self.edit_kaggle_civitai_url = QLineEdit(self.settings.get("kaggle_civitai_url", ""))
        self.edit_kaggle_civitai_url.setPlaceholderText("https://civitai.com/models/12345 or direct download URL")
        self.edit_kaggle_civitai_url.setStyleSheet("""
            QLineEdit {
                background: rgba(22, 14, 38, 0.42); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45); border-radius: 10px;
                padding: 8px 12px; font-size: 12px;
            }
            QLineEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QLineEdit:focus { border: 2px solid #C084FC; }
        """)
        self._row_kaggle_civitai_url = self._make_input_row(
            form_img, "Civitai URL:", self.edit_kaggle_civitai_url)

        self.edit_kaggle_civitai_token = QLineEdit(self.settings.get("kaggle_civitai_token", ""))
        self.edit_kaggle_civitai_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_kaggle_civitai_token.setPlaceholderText("Bearer token for private models")
        self.edit_kaggle_civitai_token.setStyleSheet("""
            QLineEdit {
                background: rgba(22, 14, 38, 0.42); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45); border-radius: 10px;
                padding: 8px 12px; font-size: 12px;
            }
            QLineEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QLineEdit:focus { border: 2px solid #C084FC; }
        """)
        self._row_kaggle_civitai_token = self._make_input_row(
            form_img, "Civitai Token:", self.edit_kaggle_civitai_token)

        # Optional LoRA
        self._add_section_header(form_img, "🎨 Optional LoRA", "#F472B6", 10)

        self.edit_kaggle_lora_url = QLineEdit(self.settings.get("kaggle_lora_url", ""))
        self.edit_kaggle_lora_url.setPlaceholderText("https://civitai.com/api/download/models/... (optional)")
        self.edit_kaggle_lora_url.setStyleSheet("""
            QLineEdit {
                background: rgba(22, 14, 38, 0.42); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45); border-radius: 10px;
                padding: 8px 12px; font-size: 12px;
            }
            QLineEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QLineEdit:focus { border: 2px solid #C084FC; }
        """)
        self._make_input_row(form_img, "LoRA URL:", self.edit_kaggle_lora_url)

        self.spin_kaggle_lora_strength = self._style_spin(QDoubleSpinBox())
        self.spin_kaggle_lora_strength.setRange(0.1, 2.0)
        self.spin_kaggle_lora_strength.setSingleStep(0.05)
        self.spin_kaggle_lora_strength.setValue(float(self.settings.get("kaggle_lora_strength", 0.9)))
        self._make_input_row(form_img, "LoRA Strength:", self.spin_kaggle_lora_strength)

        # Generation Defaults
        self._add_section_header(form_img, "⚙️ Generation Defaults", "#FBBF24", 10)

        self.spin_kaggle_steps = self._style_spin(QSpinBox())
        self.spin_kaggle_steps.setRange(1, 100)
        self.spin_kaggle_steps.setValue(int(self.settings.get("kaggle_steps", 28)))
        self._make_input_row(form_img, "Steps:", self.spin_kaggle_steps)

        self.combo_kaggle_size = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_kaggle_size)
        self.combo_kaggle_size.addItems([
            "512x512 (1:1)", "768x768 (1:1)", "832x1216 (9:16)", "1216x832 (16:9)",
            "1024x1024 (1:1)", "896x1152 (3:4)", "1152x896 (4:3)",
            "768x1344 (9:16)", "1344x768 (16:9)", "1536x640 (21:9)",
        ])
        saved_size = self.settings.get("kaggle_size", "832x1216 (9:16)")
        self.combo_kaggle_size.setCurrentText(saved_size)
        self._make_input_row(form_img, "Default Size:", self.combo_kaggle_size)

        self.spin_kaggle_guidance = self._style_spin(QDoubleSpinBox())
        self.spin_kaggle_guidance.setRange(0.0, 20.0)
        self.spin_kaggle_guidance.setSingleStep(0.5)
        self.spin_kaggle_guidance.setValue(float(self.settings.get("kaggle_guidance", 6.5)))
        self._make_input_row(form_img, "Guidance Scale:", self.spin_kaggle_guidance)

        self.edit_kaggle_neg = QLineEdit(self.settings.get("kaggle_negative_prompt", "worst quality, low quality, ugly, blurry, deformed, bad anatomy"))
        self.edit_kaggle_neg.setStyleSheet("""
            QLineEdit {
                background: rgba(22, 14, 38, 0.42); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45); border-radius: 10px;
                padding: 8px 12px; font-size: 12px;
            }
            QLineEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QLineEdit:focus { border: 2px solid #C084FC; }
        """)
        self._make_input_row(form_img, "Default Negative Prompt:", self.edit_kaggle_neg)

        # Output folder
        self._add_section_header(form_img, "📁 Output", "#6EE7B7", 10)

        self.edit_kaggle_output_dir = QLineEdit(self.settings.get("kaggle_output_dir", ""))
        self.edit_kaggle_output_dir.setPlaceholderText("Leave empty for default (UserData/generated_images)")
        self.edit_kaggle_output_dir.setStyleSheet("""
            QLineEdit {
                background: rgba(22, 14, 38, 0.42); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45); border-radius: 10px;
                padding: 8px 12px; font-size: 12px;
            }
            QLineEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QLineEdit:focus { border: 2px solid #C084FC; }
        """)
        self._make_input_row(form_img, "Output Folder:", self.edit_kaggle_output_dir)

        btn_pick_output = QPushButton("📂 Browse")
        btn_pick_output.setStyleSheet("""
            QPushButton {
                background: rgba(147, 51, 234, 0.45); color: white;
                border: 1px solid #9333EA; border-radius: 8px;
                padding: 6px 12px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.7); border-color: #C084FC; }
        """)
        btn_pick_output.clicked.connect(self._pick_kaggle_output_dir)
        form_img.addWidget(btn_pick_output)

        btn_open_output = QPushButton("📂 Open Output Folder")
        btn_open_output.setStyleSheet("""
            QPushButton {
                background: rgba(16, 185, 129, 0.45); color: white;
                border: 1px solid #10B981; border-radius: 8px;
                padding: 6px 12px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: rgba(16, 185, 129, 0.7); border-color: #34D399; }
        """)
        btn_open_output.clicked.connect(self._open_kaggle_output_dir)
        form_img.addWidget(btn_open_output)

        # ── Stealth Mode / Zero-Trace ──
        self.chk_kaggle_auto_clean = QCheckBox("🕶️ Stealth Mode: Auto-delete notebook code & images from Kaggle after download")
        self.chk_kaggle_auto_clean.setChecked(bool(self.settings.get("kaggle_auto_clean", True)))
        self.chk_kaggle_auto_clean.setStyleSheet("""
            QCheckBox { color: #E9D5FF; font-size: 11px; spacing: 8px; font-weight: bold; margin-top: 4px; }
            QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1.5px solid #9333EA; background: rgba(22, 14, 38, 0.6); }
            QCheckBox::indicator:checked { background: #10B981; border-color: #34D399; }
        """)
        self.chk_kaggle_auto_clean.setToolTip(
            "Immediately replaces notebook script on Kaggle with a clean 0-byte script and empties output tab once downloaded to your PC, leaving zero trace."
        )
        form_img.addWidget(self.chk_kaggle_auto_clean)

        # Apply HF/Civitai field visibility for the *initial* mode (the
        # currentIndexChanged handler only fires on user changes).
        self._on_kaggle_model_mode_changed(self.combo_kaggle_model_mode.currentIndex())

        # ── Phase 2: ✨ Enhancer model (dedicated LLM for prompt expansion) ──
        self._add_section_header(form_img, "✨ Enhance Model (dedicated LLM)", "#FBBF24", 10)
        self.edit_kaggle_enhancer = QLineEdit(self.settings.get("kaggle_enhancer_model", ""))
        self.edit_kaggle_enhancer.setPlaceholderText("Model name from Model Hub (blank = local tag expander)")
        self.edit_kaggle_enhancer.setStyleSheet("""
            QLineEdit { background: rgba(22,14,38,0.42); color:#F8F4FF; border:1.5px solid rgba(147,51,234,0.45);
                border-radius:10px; padding:8px 12px; font-size:12px; }
            QLineEdit:hover { border:1.5px solid rgba(192,132,252,0.75); }
            QLineEdit:focus { border:2px solid #C084FC; }
        """)
        self._make_input_row(form_img, "Enhancer Model:", self.edit_kaggle_enhancer)

        # ── PHASE 5: ☁️ server-side model cache (zero bytes to the PC) ──
        from cellium.services.kaggle_image import MODEL_PRESETS

        self._add_section_header(
            form_img, "☁️ Cloud Model Cache - built on Kaggle, never on your PC",
            "#C084FC", 10)
        _cache_hint = QLabel(
            "One CPU-only builder kernel downloads the Civitai checkpoint into a private "
            "dataset, so renders mount it in ~5 s instead of re-downloading ~7 GB. "
            "Your PC only exchanges JSON - no model bytes ever cross your connection.")
        _cache_hint.setWordWrap(True)
        _cache_hint.setStyleSheet("border:none; color:#A78BFA; font-size:11px;")
        form_img.addWidget(_cache_hint)

        self._cache_rows = {}
        for _preset in [p for p in MODEL_PRESETS if p.get("mode") in ("civitai", "huggingface")]:
            _box = QFrame()
            _box.setStyleSheet(
                "QFrame { background: rgba(22,14,38,0.35); border:1px solid rgba(147,51,234,0.30);"
                " border-radius:10px; }")
            _lv = QVBoxLayout(_box)
            _lv.setContentsMargins(10, 8, 10, 8)
            _lv.setSpacing(4)
            _name = QLabel(_preset["name"])
            _name.setWordWrap(True)
            _name.setStyleSheet("border:none; color:#E9D5FF; font-size:11px; font-weight:bold;")
            _lv.addWidget(_name)
            _row = QHBoxLayout()
            _row.setSpacing(8)
            _stat = QLabel("…")
            _stat.setStyleSheet("border:none; color:#C084FC; font-size:11px;")
            _row.addWidget(_stat, 1)
            _btn_now = QPushButton("☁️ Cache now")
            _btn_now.setCursor(Qt.CursorShape.PointingHandCursor)
            _btn_now.setStyleSheet(
                "QPushButton { background: rgba(16,185,129,0.40); color:#fff; border:1px solid #10B981;"
                " border-radius:7px; padding:4px 10px; font-weight:bold; font-size:10px; }"
                "QPushButton:hover { background: rgba(16,185,129,0.72); }"
                "QPushButton:disabled { background: rgba(80,80,90,0.35); border-color:#555; color:#999; }")
            _btn_now.clicked.connect(lambda _c=False, p=_preset: self._cache_start(p))
            _row.addWidget(_btn_now)
            _btn_del = QPushButton("🗑")
            _btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
            _btn_del.setToolTip("Delete this cache dataset (needed before re-caching)")
            _btn_del.setStyleSheet(
                "QPushButton { background: rgba(239,68,68,0.32); color:#FCA5A5; border:1px solid #EF4444;"
                " border-radius:7px; padding:4px 9px; font-size:10px; }"
                "QPushButton:hover { background:#DC2626; color:#fff; }"
                "QPushButton:disabled { background: rgba(80,80,90,0.3); border-color:#555; color:#888; }")
            _btn_del.clicked.connect(lambda _c=False, p=_preset: self._cache_remove(p))
            _row.addWidget(_btn_del)
            _lv.addLayout(_row)
            form_img.addWidget(_box)
            self._cache_rows[_preset["name"]] = (_stat, _btn_now, _btn_del)

        self.btn_cache_refresh = QPushButton("🔄 Refresh cache status")
        self.btn_cache_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cache_refresh.setStyleSheet(
            "QPushButton { background: rgba(147,51,234,0.35); color:#E9D5FF; border:1px solid #9333EA;"
            " border-radius:8px; padding:5px 11px; font-size:10px; font-weight:bold; }"
            "QPushButton:hover { background:#9333EA; color:#fff; }")
        self.btn_cache_refresh.clicked.connect(self._cache_refresh)
        form_img.addWidget(self.btn_cache_refresh)
        self._render_cache_rows()
        QTimer.singleShot(600, self._cache_refresh)

        form_img.addStretch()

        # ============================================================
        # TAB 5: 👤 Persona & Memory
        # ============================================================
        tab_persona, content_per, form_per = self._make_tab("👤 Persona & Memory")
        self.tab_widget.addTab(tab_persona, "👤 Persona & Memory")

        self._add_section_header(form_per, "👤 Persona & Character Settings")

        # User Display Name
        self.edit_user = QLineEdit(self.settings.get("user_name", "You"))
        self.edit_user.setStyleSheet("""
            QLineEdit {
                background: rgba(22, 14, 38, 0.42);
                color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45);
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 12px;
            }
            QLineEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QLineEdit:focus { border: 2px solid #C084FC; }
        """)
        form_per.addWidget(QLabel("🏷️ Your Display Name:"))
        form_per.addWidget(self.edit_user)

        # ── 🖼️ Profile pictures (yours + Cel's) ──────────────────────────
        # These are the circular cutouts drawn beside every bubble in chat.
        # Click the preview (or Upload) → crop/zoom/rotate → confirm; the
        # crop lands on disk immediately and every open bubble repaints.
        self.avatar_labels = {}
        self._add_avatar_row(form_per, "user")
        self._add_avatar_row(form_per, "cel")

        # Persona Presets
        h_persona_top = QHBoxLayout()
        lbl_p_hdr = QLabel("🎭 Persona System Prompt:")
        lbl_p_hdr.setStyleSheet("color: #E9D5FF; font-size: 12px; font-weight: bold; border: none;")
        h_persona_top.addWidget(lbl_p_hdr)
        h_persona_top.addStretch()

        self.combo_persona_presets = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_persona_presets)
        self.combo_persona_presets.setMinimumWidth(180)
        self.f_persona = F_PRESETS
        self.persona_presets = load_json(self.f_persona, {"Default": "Your name is Cel and You are a Sassy Human and a Gen-Z Female. Keep it occasionally short when needed, fun, weird and unfiltered always"})
        self.combo_persona_presets.addItems(list(self.persona_presets.keys()))
        cur_per = self.settings.get("user_persona", "")
        saved_per_name = self.settings.get("user_persona_preset")
        matched_per = "Default"
        if saved_per_name and saved_per_name in self.persona_presets:
            matched_per = saved_per_name
        else:
            for p_name, p_text in self.persona_presets.items():
                if p_text.strip() == cur_per.strip():
                    matched_per = p_name
                    break
        self.combo_persona_presets.setCurrentText(matched_per)
        self.combo_persona_presets.currentTextChanged.connect(self._on_persona_preset_chosen)
        h_persona_top.addWidget(self.combo_persona_presets)

        btn_save_persona = QPushButton(" Save Preset")
        btn_save_persona.setIcon(QIcon(str(ASSETS_DIR / "save.png")))
        btn_save_persona.setIconSize(QSize(14, 14))
        btn_save_persona.setToolTip("Save current text as a persona preset")
        btn_save_persona.setStyleSheet("background: rgba(147, 51, 234, 0.45); color: white; border-radius: 8px; padding: 6px 12px; font-weight: bold; font-size: 11px; border: 1px solid #9333EA;")
        btn_save_persona.clicked.connect(self._save_persona_preset)
        h_persona_top.addWidget(btn_save_persona)

        btn_del_persona = QPushButton()
        btn_del_persona.setIcon(QIcon(str(ASSETS_DIR / "trash.png")))
        btn_del_persona.setIconSize(QSize(15, 15))
        btn_del_persona.setFixedSize(32, 28)
        btn_del_persona.setToolTip("Delete selected persona preset")
        btn_del_persona.setStyleSheet("background: rgba(239, 68, 68, 0.2); border-radius: 8px; border: 1px solid rgba(239, 68, 68, 0.4);")
        btn_del_persona.clicked.connect(self._delete_persona_preset)
        h_persona_top.addWidget(btn_del_persona)
        form_per.addLayout(h_persona_top)

        self.edit_persona = QTextEdit()
        self.edit_persona.setPlainText(self.settings.get("user_persona", ""))
        self.edit_persona.setMinimumHeight(110)
        self.edit_persona.setMaximumHeight(220)
        self.edit_persona.setFixedHeight(110)
        # Task 2 (oct 19): default ~5 lines, expand to ~10 on hover/focus.
        _ep = self.edit_persona
        def _pe_enter(e):
            if not _ep.hasFocus():
                _ep.setFixedHeight(220)
            super(type(_ep), _ep).enterEvent(e)
        def _pe_leave(e):
            if not _ep.hasFocus() and not _ep.underMouse():
                _ep.setFixedHeight(110)
            super(type(_ep), _ep).leaveEvent(e)
        def _pe_focusin(e):
            _ep.setFixedHeight(220)
            super(type(_ep), _ep).focusInEvent(e)
        def _pe_focusout(e):
            if not _ep.underMouse():
                _ep.setFixedHeight(110)
            super(type(_ep), _ep).focusOutEvent(e)
        _ep.enterEvent = _pe_enter
        _ep.leaveEvent = _pe_leave
        _ep.focusInEvent = _pe_focusin
        _ep.focusOutEvent = _pe_focusout
        self.edit_persona.setStyleSheet("""
            QTextEdit {
                background: rgba(22, 14, 38, 0.42);
                color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45);
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 12px;
            }
            QTextEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QTextEdit:focus { border: 2px solid #C084FC; }
        """)
        form_per.addWidget(self.edit_persona)

        # Memory Presets
        h_mem_top = QHBoxLayout()
        lbl_m_hdr = QLabel("🧠 Memory & Behavioral Constraints:")
        lbl_m_hdr.setStyleSheet("color: #E9D5FF; font-size: 12px; font-weight: bold; border: none;")
        h_mem_top.addWidget(lbl_m_hdr)
        h_mem_top.addStretch()

        self.combo_mem_presets = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_mem_presets)
        self.combo_mem_presets.setMinimumWidth(180)
        self.f_mem = F_MEMPRESETS
        self.mem_presets = load_json(self.f_mem, {"Default": "Always use Kaomojis which are Japanese Emoticons made of Keyboard Symbols"})
        self.combo_mem_presets.addItems(list(self.mem_presets.keys()))
        cur_mem = self.settings.get("user_memory_rules", "")
        saved_mem_name = self.settings.get("user_memory_preset")
        matched_mem = "Default"
        if saved_mem_name and saved_mem_name in self.mem_presets:
            matched_mem = saved_mem_name
        else:
            for m_name, m_text in self.mem_presets.items():
                if m_text.strip() == cur_mem.strip():
                    matched_mem = m_name
                    break
        self.combo_mem_presets.setCurrentText(matched_mem)
        self.combo_mem_presets.currentTextChanged.connect(self._on_mem_preset_chosen)
        h_mem_top.addWidget(self.combo_mem_presets)

        btn_save_mem = QPushButton(" Save Preset")
        btn_save_mem.setIcon(QIcon(str(ASSETS_DIR / "save.png")))
        btn_save_mem.setIconSize(QSize(14, 14))
        btn_save_mem.setToolTip("Save current memory rules as a preset")
        btn_save_mem.setStyleSheet("background: rgba(147, 51, 234, 0.45); color: white; border-radius: 8px; padding: 6px 12px; font-weight: bold; font-size: 11px; border: 1px solid #9333EA;")
        btn_save_mem.clicked.connect(self._save_mem_preset)
        h_mem_top.addWidget(btn_save_mem)

        btn_del_mem = QPushButton()
        btn_del_mem.setIcon(QIcon(str(ASSETS_DIR / "trash.png")))
        btn_del_mem.setIconSize(QSize(15, 15))
        btn_del_mem.setFixedSize(32, 28)
        btn_del_mem.setToolTip("Delete selected memory preset")
        btn_del_mem.setStyleSheet("background: rgba(239, 68, 68, 0.2); border-radius: 8px; border: 1px solid rgba(239, 68, 68, 0.4);")
        btn_del_mem.clicked.connect(self._delete_mem_preset)
        h_mem_top.addWidget(btn_del_mem)
        form_per.addLayout(h_mem_top)

        self.edit_mem = QTextEdit()
        self.edit_mem.setPlainText(self.settings.get("user_memory_rules", ""))
        self.edit_mem.setMinimumHeight(90)
        self.edit_mem.setMaximumHeight(180)
        self.edit_mem.setFixedHeight(90)
        self.edit_mem.setStyleSheet("""
            QTextEdit {
                background: rgba(22, 14, 38, 0.42);
                color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45);
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 12px;
            }
            QTextEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QTextEdit:focus { border: 2px solid #C084FC; }
        """)
        form_per.addWidget(self.edit_mem)

        # ── Editable system-instruction categories (Oct 22) ──────────────
        # The prompt blocks below used to be hardcoded in main_window and
        # ai_workers. Now every one of them is visible and editable - clear a
        # box and that category is not sent at all.
        self._add_section_header(
            form_per, "🧩 Edit System Instructions Categories", margin_top=10)
        lbl_sys_hint = QLabel(
            "Everything here is actually sent to the AI - nothing is hidden. "
            "Clear a category to stop sending it. The mood contract is attached "
            "only in Live Mode / Pet Mode and is stripped automatically when "
            "you leave.")
        lbl_sys_hint.setWordWrap(True)
        lbl_sys_hint.setStyleSheet(
            "color: #A78BFA; font-size: 11px; border: none;")
        form_per.addWidget(lbl_sys_hint)

        h_sys = QHBoxLayout()
        self.combo_sysinstr = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_sysinstr)
        for _cat in SYSTEM_INSTRUCTION_ORDER:
            self.combo_sysinstr.addItem(
                SYSTEM_INSTRUCTION_LABELS.get(_cat, _cat), _cat)
        h_sys.addWidget(self.combo_sysinstr, stretch=1)

        btn_reset_sys = QPushButton("↺ Reset category")
        btn_reset_sys.setToolTip("Restore the selected category to its default text")
        btn_reset_sys.setStyleSheet(
            "background: rgba(147, 51, 234, 0.32); color: #E9D5FF; "
            "border-radius: 8px; padding: 6px 10px; border: 1px solid "
            "rgba(168, 85, 247, 0.45); font-weight: bold; font-size: 11px;")
        btn_reset_sys.clicked.connect(self._reset_sysinstr_category)
        h_sys.addWidget(btn_reset_sys)

        btn_reset_all_sys = QPushButton("↺ Reset all")
        btn_reset_all_sys.setToolTip("Restore every category to its default text")
        btn_reset_all_sys.setStyleSheet(
            "background: rgba(239, 68, 68, 0.18); color: #FCA5A5; "
            "border-radius: 8px; padding: 6px 10px; border: 1px solid "
            "rgba(239, 68, 68, 0.4); font-weight: bold; font-size: 11px;")
        btn_reset_all_sys.clicked.connect(self._reset_sysinstr_all)
        h_sys.addWidget(btn_reset_all_sys)
        form_per.addLayout(h_sys)

        self.lbl_sysinstr_hint = QLabel("")
        self.lbl_sysinstr_hint.setWordWrap(True)
        self.lbl_sysinstr_hint.setStyleSheet(
            "color: #8E918F; font-size: 11px; border: none;")
        form_per.addWidget(self.lbl_sysinstr_hint)

        self.edit_sysinstr = QTextEdit()
        self.edit_sysinstr.setMinimumHeight(120)
        self.edit_sysinstr.setMaximumHeight(260)
        self.edit_sysinstr.setFixedHeight(160)
        self.edit_sysinstr.setStyleSheet("""
            QTextEdit {
                background: rgba(22, 14, 38, 0.42);
                color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45);
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 12px;
            }
            QTextEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QTextEdit:focus { border: 2px solid #C084FC; }
        """)
        form_per.addWidget(self.edit_sysinstr)

        self._sysinstr = system_instructions(self.settings)
        self._sysinstr_current = None
        self.combo_sysinstr.currentIndexChanged.connect(self._on_sysinstr_changed)
        self._load_sysinstr_category()

        form_per.addStretch()

        # ============================================================
        # TAB 5: 📁 Local Models & Hardware
        # ============================================================
        tab_local, content_loc, form_loc = self._make_tab("📁 Local Models & Hardware")
        self.tab_widget.addTab(tab_local, "📁 Local Models & Hardware")

        self._add_section_header(form_loc, "📁 Local GGUF Engine & Memory")

        # GGUF Model Path
        self.lbl_off_path = QLabel(self.settings.get("local_model_path") or "No GGUF file selected")
        self.lbl_off_path.setStyleSheet("font-size: 11px; color: #C084FC; border: none;")
        btn_browse = QPushButton("📂 Browse GGUF")
        btn_browse.setStyleSheet("""
            QPushButton {
                background: rgba(147, 51, 234, 0.4); color: white; border-radius: 6px;
                padding: 6px 14px; font-weight: bold; border: 1px solid #9333EA;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.7); }
        """)
        btn_browse.clicked.connect(self.browse_gguf)
        h_off = QHBoxLayout()
        h_off.addWidget(btn_browse)
        h_off.addWidget(self.lbl_off_path, stretch=1)
        form_loc.addLayout(h_off)

        # ── Offline model label switches ───────────────────────────────
        # Staged like every other Settings control (applied on Save), with a
        # live preview so the effect of each switch is obvious.
        self._add_section_header(form_loc, "🏷️ Offline Model Labels", "#38BDF8", 10)
        self.toggle_off_size = ToggleRow(
            "Show MB/GB size of offline model?",
            bool(self.settings.get("show_offline_model_size", True)),
            "Adds the exact file size (decimal MB/GB, like your file manager) next to the GGUF name.",
        )
        self.toggle_off_tag = ToggleRow(
            "Show 'Offline' for offline models?",
            bool(self.settings.get("show_offline_model_tag", False)),
            "Prefixes local GGUF models with the word Offline.",
        )
        self.toggle_off_size_first = ToggleRow(
            "Put model size at the beginning?",
            bool(self.settings.get("offline_model_size_first", False)),
            "Shows 806.1MB gemma… instead of gemma… 806.1MB.",
        )
        for _tog in (self.toggle_off_size, self.toggle_off_tag,
                     self.toggle_off_size_first):
            form_loc.addWidget(_tog)
            _tog.toggled.connect(self._refresh_offline_label_preview)

        self.lbl_off_preview = QLabel("")
        self.lbl_off_preview.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_off_preview.setWordWrap(True)
        self.lbl_off_preview.setStyleSheet(
            "background: rgba(56, 189, 248, 0.08); "
            "border: 1px solid rgba(56, 189, 248, 0.28); border-radius: 8px; "
            "padding: 8px 10px; color: #E0F2FE; font-size: 11px;")
        form_loc.addWidget(self.lbl_off_preview)
        self._refresh_offline_label_preview()

        self._add_section_header(form_loc, "⚡ Advanced AI Engine & Hardware Optimization", "#38BDF8", 10)

        max_cpus = os.cpu_count() or 4
        # CPU Threads
        self.lbl_threads_val = QLabel(str(self.settings.get("offline_threads", max(1, max_cpus // 2))))
        self.lbl_threads_val.setStyleSheet("border: none; color: #C084FC; font-weight: bold;")
        self.slider_threads = QSlider(Qt.Orientation.Horizontal)
        self.slider_threads.setRange(1, max_cpus)
        self.slider_threads.setValue(int(self.settings.get("offline_threads", max(1, max_cpus // 2))))
        self.slider_threads.valueChanged.connect(self._on_threads_changed)
        h_threads = QHBoxLayout()
        h_threads.addWidget(QLabel("CPU Inference Threads:"))
        h_threads.addWidget(self.slider_threads)
        h_threads.addWidget(self.lbl_threads_val)
        form_loc.addLayout(h_threads)

        # Context Window
        self.combo_ctx = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_ctx)
        self.combo_ctx.addItems(["1024 (Fast)", "2048 (Balanced - Default)", "4096 (Deep)", "8192 (Max)", "16384 (Ultra)", "32768 (Native)"])
        cur_ctx = self.settings.get("offline_n_ctx_str", "2048 (Balanced - Default)")
        idx_ctx = self.combo_ctx.findText(cur_ctx)
        if idx_ctx != -1: self.combo_ctx.setCurrentIndex(idx_ctx)
        self.combo_ctx.currentTextChanged.connect(self._on_ctx_changed)
        self._make_input_row(form_loc, "Context Window (ctx_size):", self.combo_ctx)

        # Temperature
        cur_temp = float(self.settings.get("offline_temperature", 0.7))
        self.lbl_temp_val = QLabel(f"{cur_temp:.2f}")
        self.lbl_temp_val.setStyleSheet("border: none; color: #C084FC; font-weight: bold;")
        self.slider_temp = QSlider(Qt.Orientation.Horizontal)
        self.slider_temp.setRange(0, 200)
        self.slider_temp.setValue(int(cur_temp * 100))
        self.slider_temp.valueChanged.connect(lambda v: self.lbl_temp_val.setText(f"{v / 100.0:.2f}"))
        h_temp = QHBoxLayout()
        h_temp.addWidget(QLabel("Generation Temperature:"))
        h_temp.addWidget(self.slider_temp)
        h_temp.addWidget(self.lbl_temp_val)
        form_loc.addLayout(h_temp)

        # Top-p
        cur_top_p = float(self.settings.get("offline_top_p", 0.9))
        self.lbl_top_p_val = QLabel(f"{cur_top_p:.2f}")
        self.lbl_top_p_val.setStyleSheet("border: none; color: #C084FC; font-weight: bold;")
        self.slider_top_p = QSlider(Qt.Orientation.Horizontal)
        self.slider_top_p.setRange(0, 100)
        self.slider_top_p.setValue(int(cur_top_p * 100))
        self.slider_top_p.valueChanged.connect(lambda v: self.lbl_top_p_val.setText(f"{v / 100.0:.2f}"))
        h_top_p = QHBoxLayout()
        h_top_p.addWidget(QLabel("Top-p (Nucleus Sampling):"))
        h_top_p.addWidget(self.slider_top_p)
        h_top_p.addWidget(self.lbl_top_p_val)
        form_loc.addLayout(h_top_p)

        # Repeat Penalty
        cur_rep_pen = float(self.settings.get("offline_repeat_penalty", 1.1))
        self.lbl_rep_pen_val = QLabel(f"{cur_rep_pen:.2f}")
        self.lbl_rep_pen_val.setStyleSheet("border: none; color: #C084FC; font-weight: bold;")
        self.slider_rep_pen = QSlider(Qt.Orientation.Horizontal)
        self.slider_rep_pen.setRange(0, 200)
        self.slider_rep_pen.setValue(int(cur_rep_pen * 100))
        self.slider_rep_pen.valueChanged.connect(lambda v: self.lbl_rep_pen_val.setText(f"{v / 100.0:.2f}"))
        h_rep_pen = QHBoxLayout()
        h_rep_pen.addWidget(QLabel("Repeat Penalty:"))
        h_rep_pen.addWidget(self.slider_rep_pen)
        h_rep_pen.addWidget(self.lbl_rep_pen_val)
        form_loc.addLayout(h_rep_pen)

        # KV Cache Quantization
        self._add_section_header(form_loc, "🔧 KV Cache Quantization (RAM Savings)", "#38BDF8", 10)
        
        # Cache Type K (Keys)
        self.combo_kv_type_k = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_kv_type_k)
        self.combo_kv_type_k.addItems(["FP16 (Default, 2 bytes/token)", "INT8 / Q8_0 (1 byte/token, 50% savings)", "INT4 / Q4_0 (0.5 bytes/token, 75% savings)", "Q4_K (4-bit K-quant, balanced)"])
        cur_type_k = self.settings.get("offline_kv_cache_type_k", "f16")
        idx_map_k = {"f16": 0, "q8_0": 1, "q4_0": 2, "q4_k": 3}
        self.combo_kv_type_k.setCurrentIndex(idx_map_k.get(cur_type_k, 0))
        self._make_input_row(form_loc, "Key Cache (K) Type:", self.combo_kv_type_k)

        # Cache Type V (Values)
        self.combo_kv_type_v = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_kv_type_v)
        self.combo_kv_type_v.addItems(["FP16 (Default, 2 bytes/token)", "INT8 / Q8_0 (1 byte/token, 50% savings)", "INT4 / Q4_0 (0.5 bytes/token, 75% savings)", "Q4_K (4-bit K-quant, balanced)"])
        cur_type_v = self.settings.get("offline_kv_cache_type_v", "f16")
        idx_map_v = {"f16": 0, "q8_0": 1, "q4_0": 2, "q4_k": 3}
        self.combo_kv_type_v.setCurrentIndex(idx_map_v.get(cur_type_v, 0))
        self._make_input_row(form_loc, "Value Cache (V) Type:", self.combo_kv_type_v)

        # Flash Attention
        self.chk_flash_attn = self._style_check(QCheckBox("⚡ Flash Attention (IO-aware attention, lowers peak RAM for long contexts, faster)"))
        self.chk_flash_attn.setChecked(self.settings.get("offline_flash_attn", False))
        form_loc.addWidget(self.chk_flash_attn)

        # Prompt Caching
        self.chk_cache_prompt = self._style_check(QCheckBox("📝 Cache Prompt (--cache-prompt: precompute prompt KV cache, faster multi-turn with same context)"))
        self.chk_cache_prompt.setChecked(self.settings.get("offline_cache_prompt", False))
        form_loc.addWidget(self.chk_cache_prompt)

        # Reload banner
        self.banner_reload = QFrame()
        self.banner_reload.setStyleSheet("QFrame { background: rgba(147, 51, 234, 0.2); border: 1px solid #9333EA; border-radius: 8px; padding: 6px; }")
        h_ban = QHBoxLayout(self.banner_reload)
        self.lbl_reload_notice = QLabel("⚡ Hardware settings modified. Model must be reloaded to apply changes.")
        self.lbl_reload_notice.setStyleSheet("color: #E9D5FF; font-size: 11px; border: none; background: transparent;")
        btn_reload_now = QPushButton("🔄 Reload Model Now")
        btn_reload_now.setStyleSheet("background: #9333EA; color: white; border-radius: 5px; padding: 4px 10px; font-weight: bold; font-size: 11px; border: none;")
        btn_reload_now.clicked.connect(self._reload_model_action)
        h_ban.addWidget(self.lbl_reload_notice, stretch=1)
        h_ban.addWidget(btn_reload_now)
        self.banner_reload.setVisible(False)
        form_loc.addWidget(self.banner_reload)

        # Auto-load to RAM
        self.chk_auto_load_ram = self._style_check(QCheckBox("🧠 Auto-load GGUF to RAM at Startup (faster inference, uses more RAM)"))
        self.chk_auto_load_ram.setChecked(self.settings.get("auto_load_offline_to_ram", False))
        form_loc.addWidget(self.chk_auto_load_ram)

        # GPU Layers
        self.spin_gpu_layers = self._style_spin(QSpinBox())
        self.spin_gpu_layers.setRange(0, 999)
        self.spin_gpu_layers.setValue(int(self.settings.get("offline_gpu_layers", 0)))
        self._make_input_row(form_loc, "GPU Layers (Metal/ROCm/CUDA):", self.spin_gpu_layers)

        # Offline chat template. Autodetect reads the model filename, which is
        # the only reliable clue when you collect random GGUFs - a Qwen
        # finetune called "abliterated" still says qwen.
        self.combo_offline_fmt = self._style_combo(QComboBox())
        self._disable_combo_wheel(self.combo_offline_fmt)
        self.combo_offline_fmt.addItems(list(OFFLINE_PROMPT_TEMPLATES))
        _of = self.combo_offline_fmt.findText(str(self.settings.get(
            "offline_format", "Auto-detect from model name")))
        self.combo_offline_fmt.setCurrentIndex(_of if _of >= 0 else 0)
        self.combo_offline_fmt.setToolTip(
            "Only used when the offline model falls back to raw completion.\n\n"
            "Auto-detect matches the model filename (qwen / llama-3 / mistral / "
            "gemma) and uses a plain transcript for anything it does not know.")
        self._make_input_row(form_loc, "Offline chat template:",
                             self.combo_offline_fmt)

        form_loc.addStretch()

        # ============================================================
        # TAB 6: 📋 Logs - live, selectable/copyable app console
        # ============================================================
        tab_logs, content_logs, form_logs = self._make_tab("📋 Logs")
        self.tab_widget.addTab(tab_logs, "📋 Logs")

        self._add_section_header(form_logs, "📋 Application Logs - errors, warnings & dev output (live)")

        log_bar = QHBoxLayout()
        btn_copy_logs = QPushButton("📋 Copy All")
        btn_clear_logs = QPushButton("🧹 Clear")
        _log_btn_css = """
            QPushButton {
                background: rgba(147, 51, 234, 0.25); color: #F8F4FF;
                border: 1px solid #A855F7; border-radius: 8px;
                padding: 6px 14px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.55); border-color: #E9D5FF; }
        """
        btn_copy_logs.setStyleSheet(_log_btn_css)
        btn_clear_logs.setStyleSheet(_log_btn_css)
        btn_copy_logs.clicked.connect(self._copy_logs)
        btn_clear_logs.clicked.connect(self._clear_logs)

        self.edit_log_filter = QLineEdit()
        self.edit_log_filter.setPlaceholderText("🔍 Filter… (e.g. error, Fetch, WARN)")
        self.edit_log_filter.setStyleSheet("""
            QLineEdit {
                background: rgba(8, 6, 16, 0.8); color: #E9D5FF;
                border: 1px solid rgba(147, 51, 234, 0.45); border-radius: 8px;
                padding: 6px 10px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #C084FC; }
        """)
        self.edit_log_filter.textChanged.connect(self._refresh_log_view)

        self.chk_log_autoscroll = QCheckBox("⬇ Auto-scroll")
        self.chk_log_autoscroll.setChecked(True)
        self.chk_log_autoscroll.setStyleSheet("border: none; color: #C084FC; font-size: 12px; font-weight: bold;")

        self.lbl_log_count = QLabel("0 lines")
        self.lbl_log_count.setStyleSheet("border: none; color: #94A3B8; font-size: 11px;")

        log_bar.addWidget(btn_copy_logs)
        log_bar.addWidget(btn_clear_logs)
        log_bar.addWidget(self.edit_log_filter, stretch=1)
        log_bar.addWidget(self.chk_log_autoscroll)
        log_bar.addWidget(self.lbl_log_count)
        form_logs.addLayout(log_bar)

        # Read-only console - text stays fully selectable & copyable
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setAcceptRichText(False)
        try:
            _mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        except AttributeError:
            _mono = QFontDatabase.systemFont(QFontDatabase.FontType.FixedFont)
        _mono.setPointSize(10)
        self.log_view.setFont(_mono)
        self.log_view.setStyleSheet("""
            QTextEdit {
                background: rgba(6, 5, 12, 0.92);
                color: #A5F3FC;
                border: 1.5px solid rgba(147, 51, 234, 0.4);
                border-radius: 12px;
                padding: 10px;
                selection-background-color: #9333EA;
                selection-color: #FFFFFF;
            }
        """)
        self.log_view.setPlaceholderText("Logs appear here live… 💕")
        form_logs.addWidget(self.log_view, stretch=1)

        lbl_log_hint = QLabel("💡 Click text to select • Ctrl+C to copy • ⚠️ failed button actions are logged here instantly")
        lbl_log_hint.setStyleSheet("border: none; color: #94A3B8; font-size: 11px; font-style: italic;")
        form_logs.addWidget(lbl_log_hint)

        # Live feed - marshalled to the GUI thread via Signal (safe from workers)
        self._log_line.connect(self._append_log_line)
        register_log_listener(self._on_dev_log)
        self._refresh_log_view()

        # Set first tab as default, then swap the single-row tab bar for the
        # wrapping pill rail (the built-in bar clipped 3 of 8 labels).
        self._build_tab_nav(layout)
        self.tab_widget.setCurrentIndex(0)

    def _on_dev_log(self, line):
        # dev_log listeners can fire from ANY thread - Signal queues safely
        self._log_line.emit(line)

    def _append_log_line(self, line):
        try:
            if getattr(self, "log_view", None) is None:
                return
            filt = self.edit_log_filter.text().strip().lower()
            if filt and filt not in line.lower():
                self._sync_log_count()
                return
            self.log_view.append(line)
            if self.chk_log_autoscroll.isChecked():
                sb = self.log_view.verticalScrollBar()
                sb.setValue(sb.maximum())
            self._sync_log_count()
        except RuntimeError:
            pass

    def _sync_log_count(self):
        try:
            n = self.log_view.document().blockCount()
            self.lbl_log_count.setText(f"{n} line{'s' if n != 1 else ''}")
        except RuntimeError:
            pass

    def _refresh_log_view(self):
        try:
            if getattr(self, "log_view", None) is None:
                return
            lines = get_recent_logs()
            filt = self.edit_log_filter.text().strip().lower()
            if filt:
                lines = [l for l in lines if filt in l.lower()]
            self.log_view.setPlainText("\n".join(lines))
            sb = self.log_view.verticalScrollBar()
            sb.setValue(sb.maximum())
            self._sync_log_count()
        except RuntimeError:
            pass

    def _copy_logs(self):
        QApplication.clipboard().setText(self.log_view.toPlainText())

    def _clear_logs(self):
        clear_log_buffer()
        try:
            self.log_view.clear()
        except RuntimeError:
            pass
        self._sync_log_count()

    def browse_gguf(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Select GGUF Model", "", "GGUF Models (*.gguf)",
            options=QFileDialog.Option.DontUseNativeDialog
        )
        if f:
            self.settings["local_model_path"] = f
            self.lbl_off_path.setText(os.path.basename(f))

    # ── editable system-instruction categories (Oct 22) ─────────────────
    def _flush_sysinstr_editor(self):
        """Save the visible editor into the category it belongs to."""
        key = getattr(self, "_sysinstr_current", None)
        if key and hasattr(self, "edit_sysinstr"):
            self._sysinstr[key] = self.edit_sysinstr.toPlainText().strip()

    def _on_sysinstr_changed(self, *_):
        self._load_sysinstr_category()

    def _load_sysinstr_category(self, *_):
        # Flush the PREVIOUS category before switching, never the new one.
        self._flush_sysinstr_editor()
        key = self.combo_sysinstr.currentData()
        self._sysinstr_current = key
        if hasattr(self, "edit_sysinstr"):
            self.edit_sysinstr.setPlainText(str(self._sysinstr.get(key, "")))
        if hasattr(self, "lbl_sysinstr_hint"):
            self.lbl_sysinstr_hint.setText(
                SYSTEM_INSTRUCTION_HINTS.get(key, ""))

    def _reset_sysinstr_category(self):
        key = self.combo_sysinstr.currentData()
        if not key:
            return
        self._sysinstr[key] = SYSTEM_INSTRUCTION_DEFAULTS.get(key, "")
        self._sysinstr_current = key
        self.edit_sysinstr.setPlainText(self._sysinstr[key])

    def _reset_sysinstr_all(self):
        self._sysinstr = dict(SYSTEM_INSTRUCTION_DEFAULTS)
        # Forget the current key first, or the flush would restore the old
        # editor text over the reset we just applied.
        self._sysinstr_current = None
        self._load_sysinstr_category()

    def _on_persona_preset_chosen(self, name):
        if name in self.persona_presets:
            self.settings["user_persona_preset"] = name
            self.edit_persona.setPlainText(self.persona_presets[name])

    def _save_persona_preset(self):
        text = self.edit_persona.toPlainText().strip()
        if not text: return
        name = self._prompt_preset_name(self.combo_persona_presets,
                                        self.persona_presets, "Persona")
        if not name:
            return
        self.persona_presets[name] = text
        self.settings["user_persona_preset"] = name
        save_json(self.f_persona, self.persona_presets)
        if self.combo_persona_presets.findText(name) == -1:
            self.combo_persona_presets.addItem(name)
        self.combo_persona_presets.setCurrentText(name)
        play_ui_sound("pop", 0.5)

    def _prompt_preset_name(self, combo, presets, kind):
        """Ask what to call a preset instead of silently overwriting (#9).

        Saving used to always reuse the selected combo entry, or the literal
        "Custom Persona"/"Custom Memory", so a second save clobbered the first
        and nothing was ever nameable.
        """
        from PySide6.QtWidgets import QInputDialog
        current = combo.currentText().strip()
        taken = set(presets)
        if current and current not in ("Default", f"Custom {kind}"):
            suggestion = current
        else:
            n = 1
            while f"{kind} {n}" in taken:
                n += 1
            suggestion = f"{kind} {n}"
        while suggestion in taken:
            n = 2
            while f"{suggestion} {n}" in taken:
                n += 1
            suggestion = f"{suggestion} {n}"
        name, ok = QInputDialog.getText(self, f"Name this {kind.lower()}",
                                        "Preset name:", text=suggestion)
        name = (name or "").strip()
        if not ok or not name:
            return None
        return name

    def _delete_persona_preset(self):
        cur = self.combo_persona_presets.currentText()
        if cur in self.persona_presets:
            del self.persona_presets[cur]
            save_json(self.f_persona, self.persona_presets)
            idx = self.combo_persona_presets.currentIndex()
            self.combo_persona_presets.removeItem(idx)

    def _on_mem_preset_chosen(self, name):
        if name in self.mem_presets:
            self.settings["user_memory_preset"] = name
            self.edit_mem.setPlainText(self.mem_presets[name])

    def _save_mem_preset(self):
        text = self.edit_mem.toPlainText().strip()
        if not text: return
        name = self._prompt_preset_name(self.combo_mem_presets,
                                        self.mem_presets, "Memory")
        if not name:
            return
        self.mem_presets[name] = text
        self.settings["user_memory_preset"] = name
        save_json(self.f_mem, self.mem_presets)
        if self.combo_mem_presets.findText(name) == -1:
            self.combo_mem_presets.addItem(name)
        self.combo_mem_presets.setCurrentText(name)
        play_ui_sound("pop", 0.5)

    def _delete_mem_preset(self):
        cur = self.combo_mem_presets.currentText()
        if cur in self.mem_presets:
            del self.mem_presets[cur]
            save_json(self.f_mem, self.mem_presets)
            # Mirror into the canonical core location so the two copies cannot
            # drift. This used to be a hardcoded absolute path to the Cellium
            # source tree, which broke anywhere but this exact machine.
            save_json(F_MEMPRESETS, self.mem_presets)
            idx = self.combo_mem_presets.currentIndex()
            self.combo_mem_presets.removeItem(idx)

    def _on_threads_changed(self, v):
        self.lbl_threads_val.setText(str(v))
        self.banner_reload.setVisible(True)

    def _on_ctx_changed(self, text):
        self.banner_reload.setVisible(True)

    def _preview_live_voice(self) -> None:
        """Speak the preview line through the *call's* engine + voice.

        This used to fire a bare UI click for every non-chirp voice, which is
        why no voice ever previewed. It now hands the real pick to the main
        window, which speaks it with the same workers the call uses.
        """
        mw = self.window()
        fn = getattr(mw, "_preview_live_voice", None)
        if callable(fn):
            try:
                if fn(self.combo_live_host.currentText(),
                     self.combo_live_voice.currentData()):
                    return
            except Exception:
                pass
        try:
            play_ui_sound("click", 0.5)
        except Exception:
            pass

    # NOTE: the sound pack no longer mutates Cel's typing voice. They are
    # independent channels; selecting a UI click pack must not silently
    # change what Cel sounds like when she replies.

    # NOTE (retired): _calibrate_wake / _retake_wake_wizard used to open the
    # 10-sample Hey Cel wizard. The bundled “Okay Cel” model needs no per-user
    # training, so the wizard is unwired - HeyCelWizardDialog stays in
    # calibration.py as archived code only.

    def _pick_oww_model(self):
        """Point the wake engine at a trained .onnx model file."""
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, "Pick wake-word model", "",
                "ONNX models (*.onnx)")
        except Exception:
            return
        if path:
            try:
                self.edit_oww_model.setText(path)
            except RuntimeError:
                pass

    def _pick_custom_sound(self, name: str) -> None:
        """Use the user's own .wav for one UI sound."""
        path, _ = QFileDialog.getOpenFileName(
            self, f"Pick a sound for “{name.replace('_', ' ').title()}”", "",
            "Audio Files (*.wav *.ogg *.mp3);;All Files (*)")
        if not path:
            return
        try:
            if not Path(path).is_file():
                return
            self._custom_sound_paths[name] = path
            sld, _vol, cur = self.sound_rows[name]
            cur.setText(Path(path).name)
            cur.setStyleSheet(
                "color: #6EE7B7; font-size: 10px; font-weight: bold;")
        except (KeyError, RuntimeError, AttributeError):
            pass

    def _clear_custom_sound(self, name: str) -> None:
        """Back to the bundled sample."""
        try:
            self._custom_sound_paths.pop(name, None)
            _sld, _vol, cur = self.sound_rows[name]
            cur.setText("bundled")
            cur.setStyleSheet(
                "color: rgba(233, 213, 255, 0.6); font-size: 10px;")
        except (KeyError, RuntimeError, AttributeError):
            pass

    def _noise_profile_text(self):
        try:
            from cellium.services import noise_gate
            if noise_gate.has_profile():
                return ("✅ Room profile saved - Cel subtracts it from every "
                        "mic recording.")
            return ("⚠️ No room profile yet - calibrate so Cel knows exactly "
                    "what to subtract.")
        except Exception:
            return "🧹 Noise profile status unavailable."

    def _sync_stt_key_row(self, *_args) -> None:
        """Show the credential box only for engines that actually need a key."""
        try:
            engine = self.combo_stt.currentText()
            prov = stt_key_provider(engine)
            want = bool(prov)
            for i in range(self._stt_key_row.count()):
                w = self._stt_key_row.itemAt(i).widget()
                if w is not None:
                    w.setVisible(want)
            self.lbl_stt_key.setVisible(want)
            if not want:
                return
            self.edit_stt_key.setPlaceholderText(stt_key_hint(engine) or "paste your key")
            keys = self.settings.get("user_custom_keys") or {}
            stored = str(keys.get(prov) or "")
            if self.edit_stt_key.text() != stored:
                self.edit_stt_key.setText(stored)
            self.lbl_stt_key.setText(
                f"{engine} sends your audio to {prov} - the key stays on this "
                f"machine." if stored else
                f"No {prov} key yet: pick an engine that needs none "
                f"(Local, Google) or save one here, or the mic stays silent."
            )
        except RuntimeError:
            pass

    def _save_stt_key(self) -> None:
        """Stage the key for the selected engine - it hits disk on Save.

        Nothing in Settings persists until ✓ Save Preferences is clicked,
        so this button only parks the key in the staged dict (Save commits
        it alongside everything else - see save_preferences).
        """
        prov = stt_key_provider(self.combo_stt.currentText())
        if not prov:
            return
        key = self.edit_stt_key.text().strip()
        self.settings.setdefault("user_custom_keys", {})[prov] = key
        try:
            play_ui_sound("click", 0.5)
        except Exception:
            pass
        self._sync_stt_key_row()
        mw = self.window()
        if hasattr(mw, "show_toast"):
            try:
                mw.show_toast(
                    f"🔑 {prov} key staged - press ✓ Save Preferences",
                    icon="⏳")
            except Exception:
                pass

    def _calibrate_noise(self):
        """Open the room-noise calibration from the Audio tab (F1)."""
        mw = self.window()
        fn = getattr(mw, "_run_noise_calibration", None)
        if not callable(fn):
            return
        fn()
        # Reflect whatever the calibration decided. The staged dict is
        # isolated from the main window (deepcopy), so copy the fresh
        # values back from there and stage them - they persist on Save
        # like every other setting.
        try:
            src = getattr(mw, "settings", None) or {}
            self.settings["noise_cancel_enabled"] = bool(
                src.get("noise_cancel_enabled", True))
            self.settings["noise_cancel_strength"] = int(
                src.get("noise_cancel_strength", 70))
            self.chk_noise.setChecked(
                bool(self.settings.get("noise_cancel_enabled", True)))
            self.slider_noise.setValue(
                int(self.settings.get("noise_cancel_strength", 70)))
            self.lbl_noise_profile.setText(self._noise_profile_text())
        except RuntimeError:
            pass

    def _reload_model_action(self):
        main_win = self.window()
        self.save_preferences()
        if hasattr(main_win, "reload_local_model"):
            main_win.reload_local_model()
            self.banner_reload.setVisible(False)

    def _on_avatar_upload(self, who: str) -> None:
        """Open the cropper for ``who`` and persist + refresh on confirm."""
        app = self.window()

        def _after() -> None:
            # Refresh this settings row's label and every open bubble header.
            self.avatar_labels.get(who, None) and self.avatar_labels[who].refresh()
            try:
                bust_avatar_cache()
            except Exception:
                pass
            for lbl in self.findChildren(CircularAvatarLabel):
                lbl.refresh()
            if app is not None:
                try:
                    app._refresh_avatar_labels()
                except AttributeError:
                    pass
                try:
                    app.update_all_bubble_geometries()
                except AttributeError:
                    pass

        run_avatar_flow(who, self, _after)

    def _on_avatar_clear(self, who: str) -> None:
        """Remove ``who``'s picture on disk and refresh all labels."""
        try:
            clear_avatar(who)
        except Exception:
            pass
        try:
            bust_avatar_cache()
        except Exception:
            pass
        for lbl in self.findChildren(CircularAvatarLabel):
            if lbl.who == who:
                lbl.refresh()
        app = self.window()
        if app is not None:
            try:
                app._refresh_avatar_labels()
            except AttributeError:
                pass
            try:
                app.update_all_bubble_geometries()
            except AttributeError:
                pass

    def save_preferences(self):
        # Cel's Voice dropdown already writes sound_pack + typing_sound_mode
        # live via _on_cel_voice_changed, so nothing to re-save here.
        self.settings["streaming_mode"] = "Letter-by-Letter" if "Letter-by-Letter" in self.combo_streaming_mode.currentText() else "Word-by-Word"
        self.settings["text_speed"] = self.combo_text_speed.currentText().split()[0]
        self.settings["voice_host"] = self.combo_voice_host.currentText()
        self.settings["tts_voice"] = self.combo_tts_voice.currentData() or "af_heart"
        self.settings["tts_skip_asterisks"] = self.chk_skip_asterisks.isChecked()
        self.settings["animalese_voice"] = self.chk_animalese.isChecked()
        self.settings["ac_voice_variant"] = self.combo_cel_style.currentData() or "Classic AC"
        self.settings["live_voice"] = self.combo_live_host.currentText() or "Kokoro (Offline)"
        self.settings["live_voice_id"] = self.combo_live_voice.currentData() or ""
        self.settings["live_push_to_talk"] = bool(self.chk_ptt.isChecked())
        self.settings["live_auto_send"] = bool(self.chk_live_autosend.isChecked())
        self.settings["live_mic_muted"] = bool(self.chk_live_muted.isChecked())
        self.settings["live_show_names"] = bool(self.chk_live_names.isChecked())
        self.settings["pet_mode_enabled"] = bool(self.chk_pet_mode.isChecked())
        self.settings["pet_speak_replies"] = bool(self.chk_pet_speak.isChecked())
        try:
            self.settings["pet_scale"] = int(self.slider_pet.value())
        except (AttributeError, RuntimeError):
            self.settings["pet_scale"] = 100
        self.settings["live_ptt_key"] = str(
            getattr(self, "_ptt_key", "") or "Space")
        self.settings["live_silence_ms"] = max(
            400, int(self.settings.get("live_silence_ms", 2000) or 2000))
        self.settings["live_wake_phrase"] = (
            self.edit_wake_phrase.text().strip() or "Okay Cel")
        self.settings["listen_activation"] = bool(self.chk_wake.isChecked())
        try:

            self.settings["wake_engine"] = self.combo_wake_engine.currentText()
        except (RuntimeError, AttributeError):
            pass
        try:
            self.settings["wake_oww_model"] = self.edit_oww_model.text().strip()
        except (RuntimeError, AttributeError):
            pass
        try:
            self.settings["wake_oww_threshold"] = max(
                0.05, min(0.95, int(self.slider_oww_thr.value()) / 100.0))
        except (TypeError, ValueError, RuntimeError, AttributeError):
            pass
        try:
            mw = self.window()
            if hasattr(mw, "_update_wake_button"):
                mw._update_wake_button(bool(self.settings["listen_activation"]))
            if hasattr(mw, "refresh_wake_listener"):
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, mw.refresh_wake_listener)
        except Exception:
            pass
        self.settings["kokoro_preload"] = self.chk_kokoro_preload.isChecked()
        # typing_sound_mode is written live by _on_cel_voice_changed - no
        # stale combo to read here.
        self.settings["realistic_voice_profile"] = (
            self.combo_realistic_voice.currentData()
            or _sound_cfg.DEFAULT_REALISTIC_VOICE)
        try:
            self.settings["typing_sound_enabled"] = bool(
                self.chk_cel_typing.isChecked())
            self.settings["typing_animation"] = bool(
                self.chk_typing_anim.isChecked())
        except (AttributeError, RuntimeError):
            pass
        try:
            self.settings["font_scale"] = self.combo_font_scale.currentText()
            self.settings["verbose_logging"] = bool(
                self.chk_verbose_log.isChecked())
        except (AttributeError, RuntimeError):
            pass
        try:
            self.settings["user_typing_sound_enabled"] = bool(
                self.chk_user_typing.isChecked())
            self.settings["user_typing_sound_mode"] = (
                self.combo_user_typing.currentText())
            self.settings["user_typing_sound_volume"] = int(
                self.slider_user_typing.value())
            try:
                self.settings["tts_volume"] = max(
                    10, min(250, int(self.slider_tts_volume.value())))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        except (AttributeError, RuntimeError):
            pass
        self.settings["history_shift_nav"] = self.chk_hist_nav.isChecked()
        self.settings["voice_stt_engine"] = norm_stt_engine(
            self.combo_stt.currentText())
        # Local whisper alone has nothing to race, so multi-engine is only
        # ever saved as on for an engine that actually has a second opinion.
        self.settings["voice_multi_mode"] = bool(
            self.chk_multi_stt.isChecked()
            and norm_stt_engine(self.combo_stt.currentText()) != STT_LOCAL_GGML)
        # Model paths - written verbatim; "" means auto-resolve.
        self.settings["stt_ggml_path"] = self.edit_stt_ggml.text().strip()
        self.settings["kokoro_tts_dir"] = self.edit_kokoro_tts.text().strip()
        # STT credential: only the engine that is actually selected owns the
        # box, and saving preferences must not drop what was typed into it.
        stt_prov = stt_key_provider(self.combo_stt.currentText())
        if stt_prov:
            self.settings.setdefault("user_custom_keys", {})[stt_prov] = (
                self.edit_stt_key.text().strip())
        self.settings["noise_cancel_enabled"] = bool(self.chk_noise.isChecked())
        self.settings["noise_cancel_strength"] = int(self.slider_noise.value())
        try:
            from cellium.services import noise_gate
            noise_gate.configure(self.settings)
        except Exception:
            pass
        self.settings["wallpaper_tint"] = self.slider_tint.value() / 100.0
        self.settings["panel_opacity"] = self.slider_panel.value() / 100.0
        self.settings["glass_blur"] = self.slider_blur.value()
        self.settings["glass_opacity"] = self.slider_glass_opacity.value() / 100.0
        if hasattr(self, "chk_minimize_to_tray"):
            self.settings["minimize_to_tray"] = bool(self.chk_minimize_to_tray.isChecked())
        if hasattr(self, "chk_close_to_tray"):
            self.settings["close_to_tray"] = bool(self.chk_close_to_tray.isChecked())
        self.settings["network_timeout"] = self.spin_net_timeout.value()
        self.settings["network_max_retries"] = self.spin_net_retries.value()
        self.settings["output_max_tokens"] = self.spin_out_tokens.value()
        self.settings["disable_combo_wheel"] = self.chk_disable_wheel.isChecked()
        self.settings["disable_chat_wheel"] = self.chk_disable_chat_wheel.isChecked()
        # Re-apply the wheel lock *now*, in both directions. Locking is only
        # useful if it takes effect on Save instead of after a restart - and
        # turning it off has to put the real handler back.
        try:
            _want = bool(self.chk_disable_wheel.isChecked())
            _lock_all_wheels(self, _want)
        except (AttributeError, RuntimeError):
            pass
        self.settings["user_name"] = self.edit_user.text().strip() or "You"
        self.settings["user_persona"] = self.edit_persona.toPlainText().strip()
        self.settings["user_persona_preset"] = self.combo_persona_presets.currentText()
        self.settings["user_memory_rules"] = self.edit_mem.toPlainText().strip()
        self.settings["user_memory_preset"] = self.combo_mem_presets.currentText()
        try:
            self._flush_sysinstr_editor()
            self.settings["system_instructions"] = dict(self._sysinstr)
        except (AttributeError, RuntimeError):
            pass
        self.settings["offline_threads"] = self.slider_threads.value()
        try:
            self.settings["offline_format"] = self.combo_offline_fmt.currentText()
        except (AttributeError, RuntimeError):
            pass
        try:
            self.settings["audio_volumes"] = {
                n: int(s.value()) for n, (s, _v, _c) in self.sound_rows.items()}
            self.settings["custom_sounds"] = dict(self._custom_sound_paths)
        except (AttributeError, RuntimeError):
            pass
        self.settings["offline_n_ctx_str"] = self.combo_ctx.currentText()
        self.settings["offline_n_ctx"] = CTX_MAP.get(self.combo_ctx.currentText(), 2048)
        self.settings["offline_temperature"] = self.slider_temp.value() / 100.0
        self.settings["offline_top_p"] = self.slider_top_p.value() / 100.0
        self.settings["offline_repeat_penalty"] = self.slider_rep_pen.value() / 100.0
        self.settings["offline_gpu_layers"] = self.spin_gpu_layers.value()
        self.settings["auto_load_offline_to_ram"] = self.chk_auto_load_ram.isChecked()
        # Offline GGUF label switches (size ON, "Offline" tag OFF by default).
        self.settings["show_offline_model_size"] = bool(self.toggle_off_size.isChecked())
        self.settings["show_offline_model_tag"] = bool(self.toggle_off_tag.isChecked())
        self.settings["offline_model_size_first"] = bool(self.toggle_off_size_first.isChecked())
        
        # KV Cache Quantization & Optimization
        kv_type_map = {0: "f16", 1: "q8_0", 2: "q4_0", 3: "q4_k"}
        self.settings["offline_kv_cache_type_k"] = kv_type_map.get(self.combo_kv_type_k.currentIndex(), "f16")
        self.settings["offline_kv_cache_type_v"] = kv_type_map.get(self.combo_kv_type_v.currentIndex(), "f16")
        self.settings["offline_flash_attn"] = self.chk_flash_attn.isChecked()
        self.settings["offline_cache_prompt"] = self.chk_cache_prompt.isChecked()
        
        # Parse custom provider URLs
        try:
            self.settings["custom_provider_urls"] = json.loads(self.edit_custom_urls.toPlainText())
        except Exception:
            pass
        
        # Kaggle Image Generation settings
        try:
            self.settings["kaggle_username"] = self.edit_kaggle_user.text().strip()
            self.settings["kaggle_api_key"] = self.edit_kaggle_key.text().strip()
            self.settings["kaggle_preset"] = self.combo_kaggle_preset.currentText()
            self.settings["kaggle_model_mode"] = "huggingface" if self.combo_kaggle_model_mode.currentIndex() == 0 else "civitai"
            self.settings["kaggle_hf_model"] = self.edit_kaggle_hf_model.text().strip()
            self.settings["kaggle_hf_token"] = self.edit_kaggle_hf_token.text().strip()
            self.settings["kaggle_civitai_url"] = self.edit_kaggle_civitai_url.text().strip()
            self.settings["kaggle_civitai_token"] = self.edit_kaggle_civitai_token.text().strip()
            self.settings["kaggle_lora_url"] = self.edit_kaggle_lora_url.text().strip()
            self.settings["kaggle_lora_strength"] = float(self.spin_kaggle_lora_strength.value())
            self.settings["kaggle_steps"] = self.spin_kaggle_steps.value()
            self.settings["kaggle_size"] = self.combo_kaggle_size.currentText()
            self.settings["kaggle_guidance"] = float(self.spin_kaggle_guidance.value())
            self.settings["kaggle_negative_prompt"] = self.edit_kaggle_neg.text().strip()
            self.settings["kaggle_output_dir"] = self.edit_kaggle_output_dir.text().strip()
            self.settings["kaggle_auto_clean"] = bool(self.chk_kaggle_auto_clean.isChecked())
            # Phase 2
            self.settings["kaggle_enhancer_model"] = self.edit_kaggle_enhancer.text().strip()
        except (AttributeError, RuntimeError):
            pass
        
        save_json(F_SETTINGS, self.settings)
        play_ui_sound("send", 0.5)
        self.saved.emit(self.settings)


class SettingsWidgetNew(SettingsWidget):
    def init_ui(self):
        super().init_ui()

        # Tint slider: label only - the staged value applies on Save.
        if hasattr(self, "slider_tint"):
            def _live_tint(v):
                self.lbl_tint.setText(f"{v}%")
            self.slider_tint.valueChanged.connect(_live_tint)

        # Panel opacity slider: label only - the staged value applies on Save.
        if hasattr(self, "slider_panel"):
            def _live_panel(v):
                self.lbl_panel.setText(f"{v}%")
            self.slider_panel.valueChanged.connect(_live_panel)

        # Glass blur slider: label only - the staged value applies on Save.
        if hasattr(self, "slider_blur"):
            def _live_blur(v):
                self.lbl_blur.setText(f"{v}px")
            self.slider_blur.valueChanged.connect(_live_blur)

        # Glass opacity slider: label only - the staged value applies on Save.
        if hasattr(self, "slider_glass_opacity"):
            def _live_glass_opacity(v):
                self.lbl_glass_opacity.setText(f"{v}%")
            self.slider_glass_opacity.valueChanged.connect(_live_glass_opacity)

    def save_preferences(self):
        super().save_preferences()
        
        main_win = self.window()
        if hasattr(main_win, "wallpaper_surface"):
            main_win.wallpaper_surface.set_theme_and_tint(
                getattr(main_win, "active_server", "Server 1"), self.settings.get("wallpaper_tint", 0.32)
            )

# ------------------------------------------------------------------ Inbuilt View 3: Analytics Dashboard
class AnalyticsBars(QWidget):
    """Liquid-Glass 14-Day Token & Turn Bar Chart with hover inspection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.buckets = []
        self._hover_idx = -1
        self._bar_rects = []
        self._tooltips = {}
        self.setMinimumHeight(195)
        self.setMouseTracking(True)

    def set_buckets(self, buckets, tooltips=None):
        self.buckets = list(buckets)
        self._tooltips = dict(tooltips or {})
        self._hover_idx = -1
        self.update()

    def _hover_tooltip(self):
        """Task 20: rich hover card - every model used that bucket-day + tokens."""
        if 0 <= self._hover_idx < len(self.buckets):
            return self._tooltips.get(self.buckets[self._hover_idx][0], "")
        return ""

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        hit = -1
        for i, rect in enumerate(self._bar_rects):
            if rect.contains(pos):
                hit = i
                break
        if hit != self._hover_idx:
            self._hover_idx = hit
            self.update()
        # Task 20: floating inspection card while hovering a bar
        from PySide6.QtWidgets import QToolTip
        tip = self._hover_tooltip()
        if hasattr(event, "globalPosition"):
            gpos = event.globalPosition().toPoint()
        else:
            gpos = event.globalPos()
        if tip:
            QToolTip.showText(gpos, tip, self)
        elif self._hover_idx == -1:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover_idx != -1:
            self._hover_idx = -1
            self.update()
        super().leaveEvent(event)

    @staticmethod
    def _fmt_k(val: int) -> str:
        if val >= 1_000_000:
            return f"{val / 1_000_000:.1f}M"
        if val >= 1_000:
            return f"{val / 1_000:.1f}k"
        return str(val)

    def paintEvent(self, event):
        from PySide6.QtCore import QRect, QRectF
        from PySide6.QtGui import QBrush, QFont, QLinearGradient, QPainterPath
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()

        bg_path = QPainterPath()
        bg_path.addRoundedRect(QRectF(r).adjusted(1, 1, -1, -1), 12, 12)
        p.fillPath(bg_path, QColor(12, 9, 24, 210))
        p.setPen(QPen(QColor(147, 51, 234, 70), 1.0))
        p.drawPath(bg_path)

        f = QFont()
        self._bar_rects = []
        has_any = any((b[1] > 0) for b in self.buckets)
        if not self.buckets or not has_any:
            f.setPointSize(10)
            p.setFont(f)
            p.setPen(QColor(196, 181, 253))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                       "No token activity in the last 14 days yet - send a message to light up the chart! 📊✨")
            p.end()
            return

        top = max((b[1] for b in self.buckets), default=0) or 1
        n = len(self.buckets)
        left_pad = 46
        right_pad = 14
        top_pad = 24
        base_y = r.height() - 26
        chart_h = max(40, base_y - top_pad)
        avail_w = max(80, r.width() - left_pad - right_pad)
        gap = 6
        bw = max(6.0, (avail_w - gap * (n + 1)) / n)

        # Horizontal grid lines & Y-axis labels
        f.setPointSize(8)
        p.setFont(f)
        for frac in (0.0, 0.5, 1.0):
            gy = int(base_y - chart_h * frac)
            grid_pen = QPen(QColor(168, 85, 247, 38 if frac > 0 else 80), 1.0,
                            Qt.PenStyle.DashLine if frac > 0 else Qt.PenStyle.SolidLine)
            p.setPen(grid_pen)
            p.drawLine(left_pad, gy, r.width() - right_pad, gy)
            val_lbl = self._fmt_k(int(round(top * frac)))
            p.setPen(QColor(167, 139, 250, 190))
            p.drawText(QRect(4, gy - 8, left_pad - 8, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, val_lbl)

        for i, item in enumerate(self.buckets):
            label = item[0]
            value = int(item[1] or 0)
            x = left_pad + gap + i * (bw + gap)
            h = int(chart_h * (value / top)) if value > 0 else 2
            bar_rect = QRect(int(x), int(base_y - max(2, h)), int(bw), max(2, h))
            hit_rect = QRect(int(x) - 2, top_pad, int(bw) + 4, base_y - top_pad + 20)
            self._bar_rects.append(hit_rect)

            is_hov = (i == self._hover_idx)
            grad = QLinearGradient(0, bar_rect.top(), 0, bar_rect.bottom())
            if is_hov:
                grad.setColorAt(0.0, QColor(240, 171, 252))
                grad.setColorAt(1.0, QColor(147, 51, 234))
            elif value > 0:
                grad.setColorAt(0.0, QColor(232, 121, 249, 230))
                grad.setColorAt(1.0, QColor(109, 40, 217, 210))
            else:
                grad.setColorAt(0.0, QColor(148, 163, 184, 45))
                grad.setColorAt(1.0, QColor(148, 163, 184, 25))

            bpath = QPainterPath()
            bpath.addRoundedRect(QRectF(bar_rect), 4.0, 4.0)
            p.fillPath(bpath, QBrush(grad))
            if is_hov:
                p.setPen(QPen(QColor("#FFFFFF"), 1.2))
                p.drawPath(bpath)

            # Value label above bar if non-zero or hovered
            if value > 0 or is_hov:
                p.setPen(QColor("#F8F4FF" if is_hov else "#D8B4FE"))
                f_val = QFont()
                f_val.setPointSize(7)
                f_val.setBold(is_hov)
                p.setFont(f_val)
                p.drawText(QRect(int(x) - 6, max(2, bar_rect.top() - 16), int(bw) + 12, 14),
                           Qt.AlignmentFlag.AlignCenter, self._fmt_k(value))

            # Date label on X-axis
            f_lbl = QFont()
            f_lbl.setPointSize(7)
            f_lbl.setBold(is_hov)
            p.setFont(f_lbl)
            p.setPen(QColor("#FFFFFF" if is_hov else "#C4B5FD"))
            p.drawText(QRect(int(x) - 4, base_y + 5, int(bw) + 8, 16),
                       Qt.AlignmentFlag.AlignCenter, label)

        p.end()


class AnalyticsWidget(QWidget):
    """Polished Liquid-Glass Usage Analytics Dashboard (#11)."""

    back_to_chat = Signal()
    cleared = Signal()

    def __init__(self, analytics_data, parent=None):
        super().__init__(parent)
        self.data = dict(analytics_data or {})
        self.init_ui()

    # ── data ────────────────────────────────────────────────────────────
    def set_data(self, data):
        self.data = dict(data or {})
        self.refresh()

    def turns(self):
        rows = self.data.get("turns")
        return [t for t in rows if isinstance(t, dict)] if isinstance(rows, list) else []

    @staticmethod
    def _effective_tokens(t: dict) -> int:
        tok = int(t.get("tokens", 0) or 0)
        if tok <= 0:
            chars = int(t.get("chars", 0) or 0)
            if chars > 0:
                tok = max(1, chars // 4)
        return tok

    @staticmethod
    def _effective_seconds(t: dict) -> float:
        secs = float(t.get("seconds", 0.0) or 0.0)
        if secs <= 0.0:
            chars = int(t.get("chars", 0) or 0)
            if chars > 0:
                secs = round(max(0.4, chars / 60.0), 2)
        return secs

    def _stats(self):
        rows = self.turns()
        tokens = sum(self._effective_tokens(t) for t in rows)
        secs = sum(self._effective_seconds(t) for t in rows)
        chars = sum(int(t.get("chars", 0) or 0) for t in rows)
        days = len({str(t.get("day") or "")[:10] for t in rows if t.get("day")})
        return {
            "turns": len(rows),
            "tokens": tokens,
            "chars": chars,
            "days": days,
            "avg_tokens": (tokens / len(rows)) if rows else 0,
            "avg_s": (secs / len(rows)) if rows else 0.0,
            "tps": (chars / secs) if secs > 0.05 else 0.0,
            "tok_per_s": (tokens / secs) if secs > 0.05 else 0.0,
        }

    def _by_model(self):
        agg = {}
        for t in self.turns():
            name = str(t.get("model") or "unknown")
            slot = agg.setdefault(name, {"turns": 0, "tokens": 0, "secs": 0.0, "chars": 0})
            slot["turns"] += 1
            slot["tokens"] += self._effective_tokens(t)
            slot["secs"] += self._effective_seconds(t)
            slot["chars"] += int(t.get("chars", 0) or 0)
        return sorted(agg.items(), key=lambda kv: (-kv[1]["tokens"], -kv[1]["turns"]))

    def _daily(self, days=14):
        from datetime import date, timedelta
        agg = {}
        for t in self.turns():
            d = str(t.get("day") or "")[:10]
            if d:
                agg[d] = agg.get(d, 0) + self._effective_tokens(t)
        today = date.today()
        out = []
        for i in range(days - 1, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            out.append((d[5:], agg.get(d, 0)))
        return out

    def _day_tooltips(self):
        """Task 20: hover card per chart day - every model used + its token share."""
        day_models = {}
        for t in self.turns():
            d = str(t.get("day") or "")[:10]
            if not d:
                continue
            dm = day_models.setdefault(d[5:], {})
            name = str(t.get("model") or "unknown")
            dm[name] = dm.get(name, 0) + self._effective_tokens(t)
        tips = {}
        for lbl, dm in day_models.items():
            lines = [f"<b>{lbl}</b>"]
            for name, tok in sorted(dm.items(), key=lambda kv: -kv[1]):
                short = strip_offline_label(name).replace("⚡", "").strip()
                lines.append(f"• {html.escape(short[:34])}: <b>{tok:,}</b> tok")
            lines.append(f"<i>Total: {sum(dm.values()):,} tokens</i>")
            tips[lbl] = "<br/>".join(lines)
        return tips

    # ── ui ──────────────────────────────────────────────────────────────
    def init_ui(self):
        from PySide6.QtWidgets import QScrollArea, QFrame, QProgressBar
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        hdr = QHBoxLayout()
        btn_back = QPushButton("← Back to Chat")
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #EF4444, stop:1 #DC2626);
                color: #FFFFFF; border: 1.5px solid #F87171; border-radius: 10px;
                padding: 7px 16px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: #DC2626; border-color: #FCA5A5; }
        """)
        btn_back.clicked.connect(self.back_to_chat.emit)
        hdr.addWidget(btn_back)

        title_lbl = QLabel("📊 Usage Analytics & Telemetry")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #F8F4FF; border: none;")
        hdr.addWidget(title_lbl)
        hdr.addStretch()

        self.lbl_summary_pill = QLabel("")
        self.lbl_summary_pill.setStyleSheet(
            "background: rgba(147, 51, 234, 0.22); color: #E9D5FF; "
            "border: 1px solid rgba(192, 132, 252, 0.45); border-radius: 10px; "
            "padding: 5px 12px; font-size: 11px; font-weight: bold;"
        )
        hdr.addWidget(self.lbl_summary_pill)

        btn_clear = QPushButton("🧹 Clear history")
        btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clear.setStyleSheet("""
            QPushButton {
                background: rgba(239,68,68,0.18); color: #FCA5A5; border-radius: 8px;
                padding: 6px 12px; font-weight: bold; border: 1px solid rgba(239,68,68,0.4);
            }
            QPushButton:hover { background: rgba(239,68,68,0.35); color: #FFFFFF; }
        """)
        btn_clear.clicked.connect(self._clear)
        hdr.addWidget(btn_clear)
        layout.addLayout(hdr)

        body = QScrollArea()
        body.setWidgetResizable(True)
        body.setFrameShape(QFrame.Shape.NoFrame)
        body.setStyleSheet("background: transparent; border: none;")
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        hv = QVBoxLayout(holder)
        hv.setContentsMargins(0, 0, 6, 0)
        hv.setSpacing(12)

        card_css = """
            QFrame {
                background: rgba(20, 14, 38, 0.78);
                border: 1.2px solid rgba(147, 51, 234, 0.45);
                border-radius: 14px;
            }
        """

        # 6 KPI Tiles
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self.kpi_labels = {}
        self.kpi_sublabels = {}
        kpi_defs = (
            ("turns", "🔁 Total Turns", "conversations"),
            ("tokens", "⚬ Total Tokens", "generated"),
            ("avg_s", "⏱ Avg Latency", "per turn"),
            ("tps", "⚡ Chars / Sec", "throughput"),
            ("tok_per_s", "🚀 Tokens / Sec", "generation speed"),
            ("days", "📅 Active Days", "logged"),
        )
        for key, caption, sub_default in kpi_defs:
            card = QFrame()
            card.setStyleSheet(card_css)
            cv = QVBoxLayout(card)
            cv.setContentsMargins(14, 10, 14, 10)
            cv.setSpacing(3)
            cap = QLabel(caption)
            cap.setStyleSheet("font-size: 10px; font-weight: bold; color: #C084FC; border: none; background: transparent;")
            val = QLabel(" - ")
            val.setStyleSheet("font-size: 20px; font-weight: bold; color: #F8F4FF; border: none; background: transparent;")
            sub = QLabel(sub_default)
            sub.setStyleSheet("font-size: 10px; color: #94A3B8; border: none; background: transparent;")
            cv.addWidget(cap)
            cv.addWidget(val)
            cv.addWidget(sub)
            tiles.addWidget(card, stretch=1)
            self.kpi_labels[key] = val
            self.kpi_sublabels[key] = sub
        hv.addLayout(tiles)

        # 14-Day Chart Card
        chart_card = QFrame()
        chart_card.setStyleSheet(card_css)
        cv2 = QVBoxLayout(chart_card)
        cv2.setContentsMargins(14, 12, 14, 14)
        cv2.setSpacing(8)
        chart_hdr = QHBoxLayout()
        chart_title = QLabel("📈 TOKEN OUTPUT - LAST 14 DAYS")
        chart_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #C084FC; border: none; background: transparent;")
        self.lbl_chart_peak = QLabel("")
        self.lbl_chart_peak.setStyleSheet("font-size: 11px; color: #A78BFA; border: none; background: transparent;")
        chart_hdr.addWidget(chart_title)
        chart_hdr.addStretch()
        chart_hdr.addWidget(self.lbl_chart_peak)
        cv2.addLayout(chart_hdr)
        self.bars = AnalyticsBars()
        cv2.addWidget(self.bars)
        hv.addWidget(chart_card)

        # Split Row: Per-Model Breakdown + Recent Activity Feed
        split_row = QHBoxLayout()
        split_row.setSpacing(12)

        models_card = QFrame()
        models_card.setStyleSheet(card_css)
        mv = QVBoxLayout(models_card)
        mv.setContentsMargins(14, 12, 14, 14)
        mv.setSpacing(8)
        models_title = QLabel("🤖 MODEL LEADERBOARD & SHARE")
        models_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #C084FC; border: none; background: transparent;")
        mv.addWidget(models_title)
        self.model_box = QVBoxLayout()
        self.model_box.setSpacing(8)
        mv.addLayout(self.model_box)
        mv.addStretch()
        split_row.addWidget(models_card, stretch=3)

        recent_card = QFrame()
        recent_card.setStyleSheet(card_css)
        rv = QVBoxLayout(recent_card)
        rv.setContentsMargins(14, 12, 14, 14)
        rv.setSpacing(8)
        recent_title = QLabel("🕒 RECENT TURN TELEMETRY")
        recent_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #38BDF8; border: none; background: transparent;")
        rv.addWidget(recent_title)
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(6)
        rv.addLayout(self.recent_box)
        rv.addStretch()
        split_row.addWidget(recent_card, stretch=2)

        hv.addLayout(split_row)
        hv.addStretch()

        body.setWidget(holder)
        layout.addWidget(body, stretch=1)
        self.refresh()

    def refresh(self):
        if not hasattr(self, "bars"):
            return
        s = self._stats()
        self.kpi_labels["turns"].setText(f"{s['turns']:,}")
        self.kpi_labels["tokens"].setText(f"{s['tokens']:,}")
        self.kpi_labels["avg_s"].setText(f"{s['avg_s']:.1f}s")
        self.kpi_labels["tps"].setText(f"{s['tps']:.0f}")
        if "tok_per_s" in self.kpi_labels:
            self.kpi_labels["tok_per_s"].setText(f"{s['tok_per_s']:.1f}")
        if "days" in self.kpi_labels:
            self.kpi_labels["days"].setText(f"{s['days']:,}")

        if "turns" in self.kpi_sublabels:
            self.kpi_sublabels["turns"].setText(f"~{s['avg_tokens']:.0f} tok/turn")
        if "tokens" in self.kpi_sublabels:
            self.kpi_sublabels["tokens"].setText(f"{s['chars']:,} total chars")

        buckets = self._daily(14)
        self.bars.set_buckets(buckets, self._day_tooltips())
        peak_day, peak_val = max(buckets, key=lambda b: b[1]) if buckets else (" - ", 0)
        if hasattr(self, "lbl_chart_peak"):
            self.lbl_chart_peak.setText(
                f"Peak day: {peak_day} ({peak_val:,} tokens)" if peak_val > 0 else "No recent peak"
            )
        if hasattr(self, "lbl_summary_pill"):
            self.lbl_summary_pill.setText(f"⚡ {s['turns']:,} Turns  •  {s['tokens']:,} Tokens")

        # Rebuild Model Leaderboard
        while self.model_box.count():
            item = self.model_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rows = self._by_model()
        total_tokens_all = max(1, sum(r[1]["tokens"] for r in rows))
        if not rows:
            empty = QLabel("No model usage recorded yet. Send a message in chat! 💜")
            empty.setStyleSheet("font-size: 12px; color: #E9D5FF; border: none; background: transparent;")
            self.model_box.addWidget(empty)
        else:
            top = max(r[1]["tokens"] for r in rows) or 1
            for name, agg in rows[:10]:
                share_top = agg["tokens"] / top * 100.0
                share_total = agg["tokens"] / total_tokens_all * 100.0
                avg_lat = agg["secs"] / max(1, agg["turns"])
                tok_s = agg["tokens"] / agg["secs"] if agg["secs"] > 0.05 else 0.0
                is_off = is_offline_model_key(name)
                badge_col = "#4ADE80" if is_off else "#38BDF8"
                badge_txt = "LOCAL GGUF" if is_off else "CLOUD API"

                m_frame = QFrame()
                m_frame.setStyleSheet("""
                    QFrame {
                        background: rgba(12, 9, 24, 0.65);
                        border: 1px solid rgba(168, 85, 247, 0.28);
                        border-radius: 10px;
                    }
                """)
                mf_v = QVBoxLayout(m_frame)
                mf_v.setContentsMargins(10, 8, 10, 8)
                mf_v.setSpacing(4)

                top_line = QHBoxLayout()
                lbl_name = QLabel(f"<b>{html.escape(name)}</b>")
                lbl_name.setStyleSheet("font-size: 12px; color: #F8F4FF; border: none; background: transparent;")
                lbl_badge = QLabel(badge_txt)
                lbl_badge.setStyleSheet(
                    f"font-size: 9px; font-weight: bold; color: {badge_col}; "
                    f"background: rgba(255,255,255,0.05); border: 1px solid {badge_col}; "
                    f"border-radius: 5px; padding: 1px 6px;"
                )
                top_line.addWidget(lbl_name, stretch=1)
                top_line.addWidget(lbl_badge)
                mf_v.addLayout(top_line)

                stats_line = QLabel(
                    f"<span style='color:#D8B4FE'><b>{agg['tokens']:,}</b> tokens</span> · "
                    f"{agg['turns']:,} turns · {avg_lat:.1f}s avg · "
                    f"<span style='color:#6EE7B7'>{tok_s:.1f} tok/s</span> · "
                    f"<span style='color:#94A3B8'>{share_total:.1f}% share</span>"
                )
                stats_line.setTextFormat(Qt.TextFormat.RichText)
                stats_line.setStyleSheet("font-size: 11px; color: #CBD5E1; border: none; background: transparent;")
                mf_v.addWidget(stats_line)

                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(max(2, int(round(share_top))))
                bar.setTextVisible(False)
                bar.setFixedHeight(6)
                bar.setStyleSheet(f"""
                    QProgressBar {{
                        background: rgba(255, 255, 255, 0.07);
                        border: none;
                        border-radius: 3px;
                    }}
                    QProgressBar::chunk {{
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 #8A2BE2, stop:1 {badge_col});
                        border-radius: 3px;
                    }}
                """)
                mf_v.addWidget(bar)
                self.model_box.addWidget(m_frame)

        # Rebuild Recent Turns Feed
        if hasattr(self, "recent_box"):
            while self.recent_box.count():
                item = self.recent_box.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            recent_turns = list(reversed(self.turns()[-10:]))
            if not recent_turns:
                empty_r = QLabel("No recent turns logged yet.")
                empty_r.setStyleSheet("font-size: 11px; color: #94A3B8; border: none; background: transparent;")
                self.recent_box.addWidget(empty_r)
            else:
                for t in recent_turns:
                    ts = str(t.get("ts") or "").replace("T", " ")[5:16]
                    m_raw = str(t.get("model") or "unknown")
                    m_short = strip_offline_label(m_raw).replace("⚡", "").strip()
                    if len(m_short) > 26:
                        m_short = m_short[:24] + "…"
                    tok = self._effective_tokens(t)
                    sec = self._effective_seconds(t)
                    spd = tok / sec if sec > 0.05 else 0.0
                    row_lbl = QLabel(
                        f"<span style='color:#94A3B8; font-family:monospace;'>{html.escape(ts)}</span>  "
                        f"<b style='color:#E9D5FF;'>{html.escape(m_short)}</b><br/>"
                        f"<span style='color:#C084FC;'>{tok:,} tok</span> · "
                        f"<span style='color:#38BDF8;'>{sec:.1f}s</span> · "
                        f"<span style='color:#4ADE80;'>{spd:.1f} tok/s</span>"
                    )
                    row_lbl.setWordWrap(True)
                    row_lbl.setTextFormat(Qt.TextFormat.RichText)
                    row_lbl.setStyleSheet(
                        "background: rgba(12, 9, 24, 0.55); "
                        "border: 1px solid rgba(56, 189, 248, 0.22); "
                        "border-radius: 8px; padding: 6px 8px; font-size: 11px;"
                    )
                    self.recent_box.addWidget(row_lbl)

    def _clear(self):
        self.data = {}
        self.refresh()
        self.cleared.emit()

# ------------------------------------------------------------------ Inbuilt View 4: Dev Notes & Live Logger
class DevNotesWidget(QWidget):
    back_to_chat = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

        hdr = QHBoxLayout()
        btn_back = QPushButton("← Back to Chat")
        btn_back.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #EF4444, stop:1 #DC2626);
                color: #FFFFFF; border: 1.5px solid #F87171; border-radius: 10px;
                padding: 7px 16px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: #DC2626; border-color: #FCA5A5; }
        """)
        btn_back.clicked.connect(self.back_to_chat.emit)
        hdr.addWidget(btn_back)

        title_lbl = QLabel("📝 Developer Notes & Live App Console")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #F8F4FF; border: none;")
        hdr.addWidget(title_lbl)
        hdr.addStretch()

        btn_clear_log = QPushButton("🧹 Clear Logs")
        btn_clear_log.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.08); color: #F8F4FF; border-radius: 8px;
                padding: 6px 12px; font-weight: bold; border: 1px solid #9333EA;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.4); }
        """)
        btn_clear_log.clicked.connect(self.clear_logs)
        btn_wiz = QPushButton("🚀 First-Time Setup", self)
        btn_wiz.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_wiz.setStyleSheet(
            "QPushButton { background: rgba(147, 51, 234, 0.32); color: #F3E8FF; "
            "border: 1px solid #C084FC; border-radius: 8px; padding: 6px 14px; "
            "font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background: #9333EA; color: #FFFFFF; }"
        )

        def _run_wiz():
            mw = self.window()
            sw = getattr(mw, "settings_view", None)
            if sw is not None and hasattr(sw, "_trigger_setup_wizard"):
                sw._trigger_setup_wizard()

        btn_wiz.clicked.connect(_run_wiz)
        hdr.addWidget(btn_wiz)
        layout.addLayout(hdr)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Consolas", 11))
        self.log_box.setStyleSheet("""
            QTextEdit {
                background: rgba(10, 8, 18, 0.94);
                color: #4ADE80;
                border: 1.5px solid #9333EA;
                border-radius: 12px;
                padding: 10px;
            }
        """)
        layout.addWidget(self.log_box, stretch=1)
        register_log_listener(self.append_log)

    def append_log(self, text):
        QTimer.singleShot(0, lambda: self._append(text))

    def _append(self, text):
        if self.log_box:
            self.log_box.append(text)
            self.log_box.moveCursor(QTextCursor.MoveOperation.End)

    def clear_logs(self):
        if self.log_box:
            self.log_box.clear()
            self.log_box.append("[DEV] Logs cleared.")

# ------------------------------------------------------------------ Wallpaper Surface


# ── Upgrade Settings Dropdowns with All 5 Avatar Styles (Pet Mode + Live Mode) ──
_ALL_FIVE_AVATAR_STYLES = ["Female", "Male", "Detailed Female", "Detailed Male", "Chibi"]

_orig_settings_init = SettingsWidget.__init__

def _patched_settings_init(self, *args, **kwargs):
    _orig_settings_init(self, *args, **kwargs)
    # 1. Upgrade Desktop Companion gender dropdown to all 5 styles
    if hasattr(self, "combo_pet_gender"):
        cur_pet = self.settings.get("pet_gender", "Female")
        self.combo_pet_gender.blockSignals(True)
        self.combo_pet_gender.clear()
        self.combo_pet_gender.addItems(_ALL_FIVE_AVATAR_STYLES)
        if cur_pet in _ALL_FIVE_AVATAR_STYLES:
            self.combo_pet_gender.setCurrentText(cur_pet)
        self.combo_pet_gender.blockSignals(False)

    # 2. Add/upgrade Live Mode Avatar Style selector right inside Voice & Live Call settings!
    if hasattr(self, "combo_live_voice") and not hasattr(self, "combo_live_gender"):
        try:
            self.combo_live_gender = QComboBox()
            self.combo_live_gender.addItems(_ALL_FIVE_AVATAR_STYLES)
            cur_live = self.settings.get("live_gender", self.settings.get("pet_gender", "Female"))
            if cur_live in _ALL_FIVE_AVATAR_STYLES:
                self.combo_live_gender.setCurrentText(cur_live)
            self.combo_live_gender.setStyleSheet(self.combo_live_voice.styleSheet())
            self.combo_live_gender.currentTextChanged.connect(self._on_live_gender_setting_changed)
            # Insert right above or below combo_live_voice in its parent layout
            parent_w = self.combo_live_voice.parentWidget()
            if parent_w is not None and parent_w.layout() is not None:
                lay = parent_w.layout()
                row_h = QHBoxLayout()
                lbl = QLabel("🎭 Live Mode Avatar Style:")
                lbl.setStyleSheet("color: #E9D5FF; font-size: 12px; font-weight: bold; border: none; background: transparent;")
                row_h.addWidget(lbl)
                row_h.addStretch(1)
                row_h.addWidget(self.combo_live_gender)
                lay.addLayout(row_h)
        except Exception:
            pass

def _on_live_gender_setting_changed(self, style_name: str) -> None:
    if style_name in _ALL_FIVE_AVATAR_STYLES:
        self.settings["live_gender"] = style_name
        self.settings["pet_gender"] = style_name
        save_json(F_SETTINGS, self.settings)
        mw = self.window()
        if mw is not None and hasattr(mw, "_on_live_gender_changed"):
            try:
                mw._on_live_gender_changed(style_name)
            except Exception:
                pass

SettingsWidget.__init__ = _patched_settings_init
SettingsWidget._on_live_gender_setting_changed = _on_live_gender_setting_changed


# ── Commercial Personalization: User Display Name & Setup Wizard Button ─────
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton

if not hasattr(SettingsWidget, "_orig_init_before_commercial"):
    SettingsWidget._orig_init_before_commercial = SettingsWidget.__init__


def _commercial_settings_init(self, *args, **kwargs):
    SettingsWidget._orig_init_before_commercial(self, *args, **kwargs)
    # NOTE: this used to create a second, parented-but-layout-less
    # `edit_user_name` QLineEdit here. When `combo_pet_gender` was absent it
    # never entered a layout, so Qt rendered it at (0,0) - the floating
    # "Henry" chip over "Back to Chat". The real display-name field lives in
    # Persona & Memory (`edit_user`) and is the single source of truth.
    # Never create a parented widget unless it is immediately added to a
    # layout.


def _on_live_names_toggled(self, checked) -> None:
    """Gate the floating YOU/CEL name tags behind the Live Mode checkbox."""
    self.settings["live_show_names"] = bool(checked)
    try:
        save_json(F_SETTINGS, self.settings)
    except Exception:
        pass
    mw = self.window()
    live = getattr(mw, "_live", None)
    transcript = getattr(live, "transcript", None)
    if transcript is None:
        return
    try:
        col = transcript._col
        for i in range(max(0, col.count())):
            item = col.itemAt(i)
            row = item.widget() if item is not None else None
            lbl = getattr(row, "_who_label", None)
            if lbl is not None:
                lbl.setVisible(bool(checked))
    except Exception:
        pass
    try:
        save_json(F_SETTINGS, self.settings)
    except Exception:
        pass
    mw = self.window()
    if mw is not None and hasattr(mw, "_roll_new_chat_greeting"):
        try:
            mw._roll_new_chat_greeting()
        except Exception:
            pass


def _trigger_setup_wizard(self) -> None:
    mw = self.window()
    if mw is not None:
        from cellium.ui.onboarding import CelliumOnboardingWizard
        wiz = CelliumOnboardingWizard(main_win=mw, parent=mw)
        wiz.exec()


SettingsWidget.__init__ = _commercial_settings_init
SettingsWidget._on_live_names_toggled = _on_live_names_toggled
SettingsWidget._trigger_setup_wizard = _trigger_setup_wizard
