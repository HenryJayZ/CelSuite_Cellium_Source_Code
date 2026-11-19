"""Cerebellium Avatar Studio - the UI page for the avatar subsystem.

The archive shipped 1,520 expressions, a renderer, a desktop companion and a
procedural variant generator, and Cellium could reach none of it except through
a context-menu toggle. This module is that missing page.

Layout::

    ┌────────────────────────────────────────────────────────────────┐
    │ [← Back]  🧬 Cerebellium Avatar Studio              status     │
    ├───────────────┬────────────────────────────────────────────────┤
    │ ♀/♂ gender    │            gradient stage                      │
    │ search        │        ┌──────────────────────┐                │
    │ 760-item list │        │      AvatarView      │                │
    │ companion box │  ◀  ▶play  ▶  👁blink   scale ──────            │
    │ library stats │  name / points / blink flags / primitives       │
    └───────────────┴────────────────────────────────────────────────┘

Loading is deliberately incremental: 1,520 JSON files is ~14 MB, so the library
is pumped in batches from a QTimer and the page paints a real progress bar
instead of freezing for a second. See :meth:`AvatarStudioWidget.ensure_loaded`.

The widget talks to the rest of the app through three signals
(:attr:`back_to_chat`, :attr:`expression_selected`,
:attr:`companion_requested`) so it stays usable standalone in tests.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QProgressBar, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QVBoxLayout, QWidget,
)

from .library import GENDERS, AvatarLibrary
from .variants import available_modifiers
from .widget import AvatarView

__all__ = ["AvatarStudioWidget", "AvatarStage", "VariantCuratorDialog"]

#: Files parsed per QTimer tick while loading.
BATCH_SIZE = 96
#: Milliseconds between batches - long enough to repaint, short enough to finish fast.
BATCH_MS = 8
#: Auto-rotate interval in the playback controls.
ROTATE_MS = 1500

THEME = {
    "text": "#F8F4FF",
    "muted": "#A78BFA",
    "accent": "#C084FC",
    "accent_hi": "#E879F9",
    "edge": "rgba(147, 51, 234, 0.45)",
    "card": "rgba(20, 14, 38, 0.72)",
    "card_hi": "rgba(40, 26, 70, 0.88)",
}


def _btn(text: str, *, primary: bool = False, checkable: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        b.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                            stop:0 #A855F7, stop:1 #7C3AED);
                color: #FFFFFF; border: 1.5px solid #E879F9; border-radius: 10px;
                padding: 7px 14px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { border-color: #FFFFFF; background: #9333EA; }
            QPushButton:disabled { background: rgba(120,90,160,0.35);
                color: rgba(248,244,255,0.45); border-color: rgba(147,51,234,0.4); }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                            stop:0 #E879F9, stop:1 #A855F7);
                color: #1B1030; border-color: #F5D0FE;
            }
        """)
    else:
        b.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.06); color: #F8F4FF;
                border: 1.2px solid rgba(147,51,234,0.55); border-radius: 10px;
                padding: 7px 12px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(147,51,234,0.34); border-color: #E879F9; color: #FFFFFF;
            }
            QPushButton:pressed { background: rgba(147,51,234,0.55); }
            QPushButton:disabled { color: rgba(248,244,255,0.35);
                border-color: rgba(147,51,234,0.25); }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                            stop:0 #E879F9, stop:1 #A855F7);
                color: #1B1030; border-color: #F5D0FE;
            }
        """)
    return b


def _field_style() -> str:
    return """
        QLineEdit, QComboBox {
            background: rgba(10, 8, 20, 0.86); color: #F8F4FF;
            border: 1.4px solid rgba(147, 51, 234, 0.6); border-radius: 9px;
            padding: 6px 10px; font-size: 12px;
        }
        QLineEdit:focus, QComboBox:focus { border: 1.4px solid #E879F9; }
        QComboBox::drop-down { border: none; width: 22px; }
        QComboBox QAbstractItemView {
            background: #150E2C; color: #F8F4FF;
            border: 1px solid #9333EA; selection-background-color: #7C3AED;
        }
    """


def _card() -> QFrame:
    f = QFrame()
    f.setStyleSheet(f"""
        QFrame {{
            background: {THEME['card']};
            border: 1.2px solid {THEME['edge']};
            border-radius: 14px;
        }}
    """)
    return f


class AvatarStage(QWidget):
    """Gradient stage that hosts one :class:`AvatarView` over a breathing glow."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._phase = 0.0
        self._audio_level = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_audio_level(self, level: float) -> None:
        self._audio_level = max(0.0, min(1.0, float(level)))
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.033) % 6.283185307
        if getattr(self, "_audio_level", 0.0) > 0.001:
            self._audio_level = max(0.0, self._audio_level * 0.92 - 0.005)
        self.update()

    def dispose(self) -> None:
        self._timer.stop()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()

        base = QLinearGradient(0, 0, 0, r.height())
        base.setColorAt(0.0, QColor(28, 17, 58))
        base.setColorAt(0.55, QColor(13, 9, 28))
        base.setColorAt(1.0, QColor(21, 13, 42))
        p.fillRect(r, QBrush(base))

        pulse = 0.5 + 0.5 * math.sin(self._phase)
        cx, cy = r.width() / 2.0, r.height() * 0.46
        rad = max(140.0, min(r.width(), r.height()) * 0.66)
        glow = QRadialGradient(cx, cy, rad)
        c = QColor(self._accent)
        c.setAlpha(int(30 + 24 * pulse))
        glow.setColorAt(0.0, c)
        c2 = QColor(232, 121, 249)
        c2.setAlpha(int(10 + 14 * pulse))
        glow.setColorAt(1.0, c2)
        p.fillRect(r, QBrush(glow))

        # Bug 7: Gemini-style ambient audio-reactive smoke aura
        audio_boost = getattr(self, "_audio_level", 0.0)
        smoke_count = 5
        for i in range(smoke_count):
            angle = (self._phase * 0.8 + i * (math.tau / smoke_count)) % math.tau
            drift_r = 30.0 + 70.0 * audio_boost
            sx = cx + math.cos(angle) * drift_r
            sy = cy + math.sin(angle) * drift_r * 0.6
            s_rad = (rad * 0.45) * (1.0 + 0.6 * audio_boost)
            smoke_grad = QRadialGradient(sx, sy, s_rad)
            sc = QColor(168, 85, 247) if i % 2 == 0 else QColor(6, 182, 212)
            sc.setAlpha(int(min(255, (22 + 55 * audio_boost) * (0.6 + 0.4 * pulse))))
            smoke_grad.setColorAt(0.0, sc)
            sc_out = QColor(sc)
            sc_out.setAlpha(0)
            smoke_grad.setColorAt(1.0, sc_out)
            p.fillRect(r, QBrush(smoke_grad))

        grid = QPen(QColor(167, 139, 250, 24))
        grid.setWidth(1.0)
        p.setPen(grid)
        step = 46
        x = step
        while x < r.width():
            p.drawLine(x, 0, x, r.height())
            x += step
        y = step
        while y < r.height():
            p.drawLine(0, y, r.width(), y)
            y += step

        ring = QPen(QColor(192, 132, 252, int(40 + 45 * pulse)))
        ring.setWidth(1.6)
        p.setPen(ring)
        p.setBrush(Qt.BrushStyle.NoBrush)
        inset = QRectF(r).adjusted(1.0, 1.0, -1.0, -1.0)
        p.drawRoundedRect(inset, 16, 16)
        p.end()

    @property
    def _accent(self) -> QColor:
        return QColor(THEME["accent"])


class AvatarStudioWidget(QWidget):
    """Browse, preview and drive all 1,520 Cerebellium expressions."""

    back_to_chat = Signal()
    #: (gender, expression name) - emitted whenever the preview changes.
    expression_selected = Signal(str, str)
    #: ("visible"|"expression"|"gender", payload) - request for the main window.
    companion_requested = Signal(str, str)
    #: (gender, hidden_names) - curated variant filter for the host to persist.
    variants_curated = Signal(str, list)

    def __init__(self, settings: Optional[dict] = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.settings = dict(settings or {})
        gender = self.settings.get("companion_gender", "Female")
        self.gender = gender if gender in GENDERS else GENDERS[0]
        #: Curated-out variants per gender - the wizard writes these, every
        #: list/rotation path reads them (see _refilter).
        self._hidden: dict = dict(
            (settings or {}).get("studio_hidden_variants", {}) or {})

        self._lib = AvatarLibrary(autoload=False)
        self._all: List[str] = []
        self._filtered: List[str] = []
        self._current: Optional[str] = None
        self._cursor = 0
        self._rotating = False
        self._sync_guard = False
        self._loading_gender: Optional[str] = None
        self._load_generator = None
        self._load_done: set = set()

        self._build()

        self._batch_timer = QTimer(self)
        self._batch_timer.setInterval(BATCH_MS)
        self._batch_timer.timeout.connect(self._on_batch)

        self._rotate_timer = QTimer(self)
        self._rotate_timer.setInterval(ROTATE_MS)
        self._rotate_timer.timeout.connect(self._rotate_step)

        self.progress.setVisible(False)

    # ── construction ─────────────────────────────────────────────────────
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(14)
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_stage(), stretch=1)

        self.status = QLabel("Idle")
        self.status.setStyleSheet(
            f"font-size:11px; color:{THEME['muted']}; border:none; background:transparent;")
        self.header.addWidget(self.status)

    def _build_sidebar(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(336)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        side = QWidget()
        side.setStyleSheet("background: transparent;")
        v = QVBoxLayout(side)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(10)

        # gender + search
        row = QHBoxLayout()
        row.setSpacing(8)
        self.combo_gender = QComboBox()
        self.combo_gender.addItem("♀  Female", "Female")
        self.combo_gender.addItem("♂  Male", "Male")
        self.combo_gender.setCurrentIndex(
            0 if self.gender == GENDERS[0] else 1)
        self.combo_gender.currentIndexChanged.connect(self._on_gender_changed)
        self.combo_gender.setStyleSheet(_field_style())
        row.addWidget(self.combo_gender, stretch=1)

        btn_rand = _btn("🎲 Surprise me")
        btn_rand.clicked.connect(self._pick_random)
        row.addWidget(btn_rand)
        v.addLayout(row)

        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 Filter expressions…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refilter)
        self.search.setStyleSheet(_field_style())
        v.addWidget(self.search)

        # expression list
        list_card = _card()
        lv = QVBoxLayout(list_card)
        lv.setContentsMargins(10, 10, 10, 10)
        lv.setSpacing(6)
        lrow = QHBoxLayout()
        self.list_title = QLabel("EXPRESSIONS")
        self.list_title.setStyleSheet(
            f"font-size:10px; font-weight:bold; color:{THEME['accent']};"
            "letter-spacing:1px; border:none; background:transparent;")
        self.count_label = QLabel(" - ")
        self.count_label.setStyleSheet(
            f"font-size:10px; color:{THEME['muted']}; border:none;"
            "background:transparent;")
        lrow.addWidget(self.list_title)
        lrow.addStretch()
        lrow.addWidget(self.count_label)
        btn_curate = _btn("🧬 Curate")
        btn_curate.setToolTip(
            "Trim lookalike sub-variants: walk each main animation with "
            "Prev/Next and tick which subs survive.")
        btn_curate.clicked.connect(self._open_curator)
        lrow.addWidget(btn_curate)
        lv.addLayout(lrow)

        self.expr_list = QListWidget()
        self.expr_list.setUniformItemSizes(True)
        self.expr_list.setFont(QFont("Sans", 10))
        self.expr_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.expr_list.currentTextChanged.connect(self._on_list_text)
        self.expr_list.itemClicked.connect(lambda item: self._on_list_text(item.text()))
        self.expr_list.setStyleSheet("""
            QListWidget {
                background: rgba(8, 6, 16, 0.8); color: #DCD0F5;
                border: 1px solid rgba(147,51,234,0.35); border-radius: 9px;
                outline: none; padding: 3px;
            }
            QListWidget::item { padding: 5px 7px; border-radius: 6px; }
            QListWidget::item:selected {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                            stop:0 rgba(168,85,247,0.55), stop:1 rgba(232,121,249,0.28));
                color: #FFFFFF;
            }
            QListWidget::item:hover { background: rgba(147, 51, 234, 0.22); }
        """)
        lv.addWidget(self.expr_list, stretch=1)
        v.addWidget(list_card, stretch=1)

        # companion
        comp = _card()
        pv = QVBoxLayout(comp)
        pv.setContentsMargins(12, 10, 12, 12)
        pv.setSpacing(8)
        phead = QLabel("🐾 DESKTOP COMPANION")
        phead.setStyleSheet(
            f"font-size:10px; font-weight:bold; color:{THEME['accent']};"
            "letter-spacing:1px; border:none; background:transparent;")
        pv.addWidget(phead)

        self.chk_companion = QCheckBox("Show the floating companion")
        self.chk_companion.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_companion.toggled.connect(self._on_companion_toggled)
        self.chk_companion.setStyleSheet("""
            QCheckBox { color: #E9D5FF; font-size: 12px; spacing: 8px; }
            QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px;
                border: 1.4px solid rgba(147,51,234,0.8); background: rgba(10,8,20,0.9); }
            QCheckBox::indicator:checked {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #E879F9, stop:1 #A855F7);
                border-color: #F5D0FE;
            }
        """)
        pv.addWidget(self.chk_companion)

        btn_push = _btn("⬆  Send to the companion")
        btn_push.clicked.connect(
            lambda: self._request("expression", self._current or ""))
        pv.addWidget(btn_push)

        v.addWidget(comp)

        # matrix report
        rep = _card()
        rv = QVBoxLayout(rep)
        rv.setContentsMargins(12, 10, 12, 12)
        rv.setSpacing(6)
        rhead = QLabel("LIBRARY")
        rhead.setStyleSheet(
            f"font-size:10px; font-weight:bold; color:{THEME['accent']};"
            "letter-spacing:1px; border:none; background:transparent;")
        rv.addWidget(rhead)
        self.matrix_label = QLabel(" - ")
        self.matrix_label.setWordWrap(True)
        self.matrix_label.setTextFormat(Qt.TextFormat.RichText)
        self.matrix_label.setStyleSheet(
            "font-size:11px; color:#E9D5FF; border:none; background:transparent;")
        rv.addWidget(self.matrix_label)
        v.addWidget(rep)

        v.addStretch()
        scroll.setWidget(side)
        return scroll


    def _build_stage(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # header
        self.header = QHBoxLayout()
        self.header.setSpacing(10)
        btn_back = _btn("← Back to Chat", primary=True)
        btn_back.clicked.connect(self.back_to_chat.emit)
        self.header.addWidget(btn_back)
        title = QLabel("🧬 Cerebellium Avatar Studio")
        title.setStyleSheet(
            f"font-size:16px; font-weight:bold; color:{THEME['text']}; border:none;"
            "background:transparent;")
        self.header.addWidget(title)
        self.header.addStretch()
        v.addLayout(self.header)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setStyleSheet("""
            QProgressBar { background: rgba(10,8,20,0.8); border: none;
                border-radius: 2px; }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #A855F7, stop:1 #F0ABFC);
                border-radius: 2px;
            }
        """)
        v.addWidget(self.progress)

        # stage
        self.stage = AvatarStage()
        sl = QVBoxLayout(self.stage)
        sl.setContentsMargins(26, 22, 26, 22)
        self.preview = AvatarView(scale=0.69)
        self.preview.setMinimumSize(320, 240)
        sl.addWidget(self.preview, stretch=1)
        v.addWidget(self.stage, stretch=1)

        # playback row
        ctl = QHBoxLayout()
        ctl.setSpacing(8)
        btn_prev = _btn("◀  Prev")
        btn_prev.clicked.connect(lambda: self._step(-1))
        ctl.addWidget(btn_prev)

        self.btn_play = _btn("▶  Auto-play")
        self.btn_play.clicked.connect(self._toggle_rotate)
        ctl.addWidget(self.btn_play)

        btn_next = _btn("Next  ▶")
        btn_next.clicked.connect(lambda: self._step(1))
        ctl.addWidget(btn_next)

        btn_blink = _btn("👁  Blink")
        btn_blink.clicked.connect(self.preview.blink_now)
        ctl.addWidget(btn_blink)

        btn_copy = _btn("📋  Copy JSON")
        btn_copy.clicked.connect(self._copy_json)
        ctl.addWidget(btn_copy)

        btn_del = _btn("🗑  Delete")
        btn_del.setToolTip(
            "Delete the selected expression and immediately advance to the next one "
            "(files are safely parked in Anim/_Trash).")
        btn_del.clicked.connect(self._delete_current)
        ctl.addWidget(btn_del)

        self._skip_delete_confirm = False
        self.chk_no_confirm_del = QCheckBox("Do not ask again")
        self.chk_no_confirm_del.setToolTip(
            "Skip confirmation popup for rapid deleting (resets when Cellium is reopened)")
        self.chk_no_confirm_del.setStyleSheet(
            "QCheckBox { color: #C4B5FD; font-size: 11px; spacing: 5px; } "
            "QCheckBox::indicator { width: 14px; height: 14px; border-radius: 4px; "
            "border: 1.2px solid #9333EA; background: rgba(10,8,20,0.85); } "
            "QCheckBox::indicator:checked { background: #A855F7; border-color: #F5D0FE; }"
        )
        self.chk_no_confirm_del.toggled.connect(self._on_skip_del_toggled)
        ctl.addWidget(self.chk_no_confirm_del)

        ctl.addStretch()
        ctl.addWidget(QLabel("Scale"))
        self.slider_scale = QSlider(Qt.Orientation.Horizontal)
        self.slider_scale.setRange(20, 160)
        self.slider_scale.setValue(92)
        self.slider_scale.setFixedWidth(170)
        self.slider_scale.valueChanged.connect(self._on_scale)
        self.slider_scale.setStyleSheet("""
            QSlider::groove:horizontal { height: 4px; border-radius: 2px;
                background: rgba(147,51,234,0.35); }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #F0ABFC,stop:1 #A855F7);
                border: 1px solid #F5D0FE; border-radius: 8px; width: 14px; margin: -6px 0;
            }
        """)
        ctl.addWidget(self.slider_scale)
        v.addLayout(ctl)

        # readouts
        info = _card()
        iv = QVBoxLayout(info)
        iv.setContentsMargins(14, 11, 14, 12)
        iv.setSpacing(6)

        self.name_label = QLabel(" - ")
        self.name_label.setStyleSheet(
            f"font-size:14px; font-weight:bold; color:{THEME['text']}; border:none;"
            "background:transparent;")
        iv.addWidget(self.name_label)

        self.meta_label = QLabel(" - ")
        self.meta_label.setWordWrap(True)
        self.meta_label.setTextFormat(Qt.TextFormat.RichText)
        self.meta_label.setStyleSheet(
            "font-size:11px; color:#D8C7F5; border:none; background:transparent;")
        iv.addWidget(self.meta_label)

        self.kinds_label = QLabel(" - ")
        self.kinds_label.setWordWrap(True)
        self.kinds_label.setStyleSheet(
            f"font-size:11px; color:{THEME['muted']}; border:none;"
            "background:transparent;")
        iv.addWidget(self.kinds_label)
        v.addWidget(info)
        return panel

    # ── loading ──────────────────────────────────────────────────────────
    def ensure_loaded(self, *, blocking: bool = False) -> None:
        """Start loading this gender's expressions (idempotent).

        ``blocking=True`` runs the generator to completion, which is what the
        regression suite uses so it does not depend on a running event loop.
        """
        if self.gender in self._load_done:
            return
        if blocking:
            for _ in self._lib.load_gender(self.gender, BATCH_SIZE):
                pass
            self._finish_loading(self.gender)
            return
        if self._load_generator is not None and self._loading_gender == self.gender:
            return
        self._load_generator = self._lib.load_gender(self.gender, BATCH_SIZE)
        self._loading_gender = self.gender
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self._set_status(f"Loading {self.gender} expressions…")
        self._batch_timer.start()

    def _on_batch(self) -> None:
        """Pull one batch from the generator so the event loop can paint."""
        if self._load_generator is None:
            self._batch_timer.stop()
            return
        # Task 3: never splice fresh rows into the list while the user is
        # mid-click - rows shifting under the cursor is exactly what made
        # clicks land on the wrong expression. Defer the batch instead.
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            QTimer.singleShot(120, self._on_batch)
            return
        try:
            next(self._load_generator)
        except StopIteration:
            self._batch_timer.stop()
            self._finish_loading(self._loading_gender or self.gender)
            return
        self._set_status(f"Loading {self.gender}… {self._lib.count(self.gender)} so far")

    def _finish_loading(self, gender: str) -> None:
        self._batch_timer.stop()
        self._load_generator = None
        self._loading_gender = None
        self._load_done.add(gender)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setVisible(False)
        # A slow load finishing AFTER the user already flipped gender again
        # must not repaint the page with the wrong gender's names - the fresh
        # gender's own finish owns the refresh.
        if gender != self.gender:
            return
        self.expr_list.setEnabled(True)
        self._refresh_names()
        self._refresh_matrix()
        bad = len(self._lib.errors)
        self._set_status(
            f"{self._lib.count(gender)} {gender} expressions loaded"
            + (f" · {bad} rejected" if bad else ""))
        if self._filtered:
            target = self._current if self._current in self._filtered else self._filtered[0]
            self._select(target)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self.ensure_loaded()

    # ── data plumbing ────────────────────────────────────────────────────
    def _refresh_names(self) -> None:
        self._all = self._lib.names(self.gender)
        self._refilter()

    def _refilter(self, *_args) -> None:
        # Curated-out variants never list (wizard, fix 5.1) - search, steps,
        # Surprise-me and auto-play all walk _filtered, so one filter covers
        # every path that surfaces expressions.
        hidden = set((self._hidden or {}).get(self.gender, []) or [])
        needle = (self.search.text() or "").strip().lower()
        if needle:
            self._filtered = [n for n in self._all
                              if needle in n.lower() and n not in hidden]
        else:
            self._filtered = [n for n in self._all if n not in hidden]
        self.expr_list.blockSignals(True)
        self.expr_list.clear()
        for name in self._filtered:
            item = QListWidgetItem(name)
            item.setToolTip(name)
            self.expr_list.addItem(item)
        self.expr_list.blockSignals(False)
        self.count_label.setText(f"{len(self._filtered):,} / {len(self._all):,}")
        if not self._filtered:
            self.list_title.setText("NO MATCHES")
            return
        self.list_title.setText("EXPRESSIONS")
        target = self._current if self._current in self._filtered else self._filtered[0]
        self._select(target)

    # ── variant curator (fix 5.1) ──────────────────────────────────────
    def set_hidden_map(self, hidden_map) -> None:
        """Host push: curated hidden variants per gender (settings file)."""
        try:
            self._hidden = {str(g): [str(n) for n in (v or [])]
                            for g, v in dict(hidden_map or {}).items()}
        except Exception:
            self._hidden = {}
        self._refilter()

    def _apply_hidden(self, gender: str, hidden: set) -> None:
        if self._hidden is None:
            self._hidden = {}
        self._hidden[str(gender)] = sorted(str(n) for n in (hidden or []))
        if gender == self.gender:
            cur = self._current
            self._refilter()
            if cur is not None and cur not in self._filtered:
                if self._filtered:
                    self._select(self._filtered[0])

    def _open_curator(self) -> None:
        """Trim lookalike sub-variants family by family."""
        if self.gender not in self._load_done:
            self._set_status("Hold on - expressions are still loading…")
            return
        hidden = set((self._hidden or {}).get(self.gender, []) or [])
        dlg = VariantCuratorDialog(
            self._lib, self.gender, hidden,
            preview_cb=self._curator_preview, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # The curator may have deleted files, not just hidden names - rebuild
        # the name index first so the dead rows vanish from the list too.
        self._refresh_names()
        self._apply_hidden(self.gender, dlg.hidden())
        self.variants_curated.emit(self.gender, sorted(dlg.hidden()))

    def _curator_preview(self, gender: str, name: str) -> None:
        if gender != self.gender:
            return
        expr = self._lib.get(gender, name)
        if expr is not None:
            try:
                self.preview.set_expression(expr)
            except Exception:
                pass

    def _on_list_text(self, text: str) -> None:
        # Clicking an EXPRESSION previews it - the old push_to_view=False left
        # the preview frozen on the first selection forever.
        if text and text != self._current:
            self._select(text)

    def _on_gender_changed(self, _index: int) -> None:
        gender = self.combo_gender.currentData()
        if gender not in GENDERS:
            return
        if gender == self.gender and gender in self._load_done:
            return
        self.gender = gender
        self._current = None
        self._cursor = 0
        # Park the page in an explicit LOADING state. The old code kept the
        # previous gender's names selected, so every click resolved
        # lib.get(new_gender, old_name) -> None, _select bailed early, the
        # chips never re-synced (several stayed checked) and the preview
        # froze dead. Nothing is clickable until the new gender lands.
        self._all = []
        self._filtered = []
        self.expr_list.blockSignals(True)
        self.expr_list.clear()
        self.expr_list.setEnabled(False)
        self.expr_list.blockSignals(False)
        self.count_label.setText("loading…")
        self.list_title.setText("LOADING…")
        try:
            self.preview.set_expression(None)
        except Exception:
            pass
        self.name_label.setText(" - ")
        self.meta_label.setText(f"Loading {gender} expressions…")
        self.kinds_label.setText("primitives:  - ")
        self.ensure_loaded()
        self._set_status(f"Switched to {gender}…")
        self._request("gender", gender)

    def _select(self, name: str, *, push_to_view: bool = True) -> None:
        expr = self._lib.get(self.gender, name)
        if expr is None:
            return
        self._current = name
        if push_to_view:
            self.preview.set_expression(expr)
        self._cursor = self._filtered.index(name) if name in self._filtered else self._cursor
        self._update_readout(expr)
        if push_to_view:
            self._sync_list_selection(name)
            self.expression_selected.emit(self.gender, name)

    def _sync_list_selection(self, name: str) -> None:
        self.expr_list.blockSignals(True)
        items = self.expr_list.findItems(name, Qt.MatchFlag.MatchExactly)
        if items:
            self.expr_list.setCurrentItem(items[0])
            self.expr_list.scrollToItem(items[0], QListWidget.ScrollHint.PositionAtCenter)
        self.expr_list.blockSignals(False)

    def _update_readout(self, expr) -> None:
        self.name_label.setText(f"{expr.name}")
        mod = expr.modifier or "base"
        blink = "on" if expr.blink_enabled else "off"
        sides = f"L {'✓' if expr.blink_left else '✗'} / R {'✓' if expr.blink_right else '✗'}"
        self.meta_label.setText(
            f"<b style='color:{THEME['accent_hi']}'>{expr.gender}</b> · "
            f"{mod} · <b>{len(expr.points):,}</b> points · blink {blink} ({sides}) · "
            f"speed L {expr.left_speed:.2f} / R {expr.right_speed:.2f} · "
            f"depth L {expr.left_depth:.0f} / R {expr.right_depth:.0f}<br/>"
            f"fade {expr.fade_opacity:.2f} · occlusion {expr.occlusion_offset:.1f} · "
            f"shift L {expr.left_eye_shift:+.1f} / R {expr.right_eye_shift:+.1f}"
        )
        used = sorted(expr.by_kind().keys())
        self.kinds_label.setText("primitives: " + " · ".join(used) if used
                                 else "primitives: none")

    def _refresh_matrix(self) -> None:
        rep = self._lib.matrix_report(self.gender)
        if not rep.get("total"):
            self.matrix_label.setText("No data loaded yet.")
            return
        self.matrix_label.setText(
            f"<b style='color:{THEME['accent_hi']}'>{rep['bases']}</b> base expressions<br/>"
            f"{rep['variants_present']:,} style variants on disk · "
            f"{rep['total']:,} files for {rep['gender']}"
        )

    def _step(self, delta: int) -> None:
        if not self._filtered:
            return
        self._cursor = (self._cursor + delta) % len(self._filtered)
        self._select(self._filtered[self._cursor])

    def _pick_random(self) -> None:
        if not self._filtered:
            return
        self._cursor = random.randrange(len(self._filtered))
        self._select(self._filtered[self._cursor])

    def _toggle_rotate(self) -> None:
        self._rotating = not self._rotating
        self.btn_play.setText("⏸  Pause" if self._rotating else "▶  Auto-play")
        if self._rotating:
            self._rotate_timer.start()
        else:
            self._rotate_timer.stop()

    def _rotate_step(self) -> None:
        self._step(1)

    def _on_scale(self, value: int) -> None:
        self.preview.set_scale(value / 100.0)

    def _copy_json(self) -> None:
        expr = self._lib.get(self.gender, self._current) if self._current else None
        if expr is None:
            self._set_status("Nothing selected to copy.")
            return
        payload = json.dumps({"name": expr.name, "gender": expr.gender,
                              **expr.to_json()}, indent=1)
        QApplication.clipboard().setText(payload)
        self._set_status(f"Copied {expr.name} JSON to the clipboard.")

    def _on_skip_del_toggled(self, checked: bool) -> None:
        self._skip_delete_confirm = bool(checked)

    def _delete_current(self) -> None:
        """Delete the selected expression and immediately advance to the next item in the list."""
        item = self.expr_list.currentItem()
        name = item.text() if item is not None else self._current
        if name and name != self._current:
            self._select(name)
        expr = self._lib.get(self.gender, name) if name else None
        if expr is None:
            self._set_status("Nothing selected to delete.")
            return
        try:
            is_base = (expr.base_name == name)
        except Exception:
            is_base = False

        # Remember current index in _filtered so we land on the very next item!
        try:
            cur_idx = self._filtered.index(name)
        except ValueError:
            cur_idx = max(0, self.expr_list.currentRow())

        if not getattr(self, "_skip_delete_confirm", False):
            msg = QMessageBox(self)
            msg.setWindowTitle("Delete expression?")
            msg.setIcon(QMessageBox.Icon.Question)
            if is_base:
                msg.setText(
                    f"Hide/cull base expression “{name}” from the active list?\n\n"
                    "(Base files are kept on disk so variant math stays intact.)"
                )
            else:
                msg.setText(
                    f"Delete “{name}”?\n\nOnly this sub-variant goes (the "
                    f"“{expr.base_name}” family stays whole). The file is parked in "
                    "Anim/_Trash, not erased."
                )
            chk = QCheckBox("Do not ask again (for this session)", msg)
            chk.setChecked(False)
            msg.setCheckBox(chk)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            msg.setDefaultButton(QMessageBox.StandardButton.Ok)
            if msg.exec() != QMessageBox.StandardButton.Ok:
                return
            if chk.isChecked():
                self._skip_delete_confirm = True
                if hasattr(self, "chk_no_confirm_del"):
                    self.chk_no_confirm_del.blockSignals(True)
                    self.chk_no_confirm_del.setChecked(True)
                    self.chk_no_confirm_del.blockSignals(False)

        if is_base:
            # Base expressions are hidden via the curated filter so _t_lib_delete invariant stays intact
            hidden = set((self._hidden or {}).get(self.gender, []) or [])
            hidden.add(name)
            self._hidden[self.gender] = sorted(hidden)
            self.variants_curated.emit(self.gender, sorted(hidden))
            reason = "hidden from list"
        else:
            ok, reason = self._lib.delete(self.gender, name)
            if not ok:
                self._set_status(f"Could not delete {name}: {reason}.")
                return
            try:
                hidden = set((self._hidden or {}).get(self.gender, []) or [])
                hidden.discard(name)
                self._hidden[self.gender] = sorted(hidden)
            except Exception:
                pass

        # Rebuild list & immediately select + scroll to the NEXT expression at `cur_idx`!
        self._all = self._lib.names(self.gender)
        hidden_set = set((self._hidden or {}).get(self.gender, []) or [])
        needle = (self.search.text() or "").strip().lower()
        self._filtered = [
            n for n in self._all
            if n not in hidden_set and (not needle or needle in n.lower())
        ]
        if self._filtered:
            next_idx = min(cur_idx, len(self._filtered) - 1)
            self._current = self._filtered[next_idx]
        else:
            self._current = None
        self._refilter()
        self._refresh_matrix()
        if self._current:
            items = self.expr_list.findItems(self._current, Qt.MatchFlag.MatchExactly)
            if items:
                self.expr_list.setCurrentItem(items[0])
                self.expr_list.scrollToItem(items[0], QListWidget.ScrollHint.PositionAtCenter)
                self.expr_list.setFocus()
        self._set_status(f"Deleted {name} ({reason}) → advanced to {self._current or 'end'}.")

    def _on_companion_toggled(self, checked: bool) -> None:
        if self._sync_guard:
            return
        self._request("visible", "true" if checked else "false")

    def _request(self, action: str, payload: str) -> None:
        self.companion_requested.emit(action, payload)

    def _set_status(self, text: str) -> None:
        if getattr(self, "status", None) is not None:
            self.status.setText(text)

    # ── host bridge ──────────────────────────────────────────────────────
    def sync_companion(self, visible: bool) -> None:
        """Reflect the real companion state without re-emitting a request."""
        self._sync_guard = True
        self.chk_companion.setChecked(bool(visible))
        self._sync_guard = False

    def on_shown(self) -> None:
        """Called by the main window when the page becomes visible."""
        self.ensure_loaded()

    def dispose(self) -> None:
        self._batch_timer.stop()
        self._rotate_timer.stop()
        self.stage.dispose()
        self.preview.dispose()


class VariantCuratorDialog(QDialog):
    """Mini-wizard over expression bloat (fix 5.1): Prev/Next walks the MAIN
    (base) animations one family at a time; the checklist picks which
    sub-variants survive. Ten near-identical "Terrified" siblings stop being
    ten list rows and become one family you trim once.

    The result is a per-gender hidden set. The studio list, Prev/Next,
    Surprise-me, auto-play and the companion's idle rotation all honour it,
    so trimmed variants vanish everywhere at once. Save persists through the
    host (``variants_curated``); Cancel changes nothing.
    """

    def __init__(self, lib: AvatarLibrary, gender: str,
                 hidden: set | None = None,
                 preview_cb=None, parent=None):
        super().__init__(parent)
        self._lib = lib
        self._gender = gender
        self._hidden: set = set(hidden or [])
        self._preview_cb = preview_cb
        self._bases = [b for b in lib.base_names(gender)
                       if self._family_variants(b)]
        if not self._bases:
            self._bases = list(lib.base_names(gender))
        self._idx = 0

        self.setWindowTitle(f"🧬 Curate {gender} variants")
        self.setMinimumSize(420, 480)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        self.lbl_family = QLabel(" - ")
        self.lbl_family.setStyleSheet(
            "font-size:15px; font-weight:bold; color:#F8F4FF;")
        self.lbl_family.setWordWrap(True)
        root.addWidget(self.lbl_family)

        self.lbl_count = QLabel(" - ")
        self.lbl_count.setStyleSheet("font-size:11px; color:#A78BFA;")
        root.addWidget(self.lbl_count)

        self.variant_list = QListWidget()
        self.variant_list.setStyleSheet("""
            QListWidget {
                background: rgba(8, 6, 16, 0.85); color: #DCD0F5;
                border: 1px solid rgba(147,51,234,0.35); border-radius: 9px;
                outline: none; padding: 3px;
            }
            QListWidget::item { padding: 5px 7px; border-radius: 6px; }
            QListWidget::item:selected {
                background: rgba(168,85,247,0.4); color: #FFFFFF;
            }
        """)
        self.variant_list.itemChanged.connect(self._on_item_changed)
        self.variant_list.itemClicked.connect(self._on_item_clicked)
        root.addWidget(self.variant_list, stretch=1)

        quick = QHBoxLayout()
        quick.setSpacing(8)
        btn_all = _btn("✓ All")
        btn_all.setToolTip("Keep every sub-variant of this family.")
        btn_all.clicked.connect(self._keep_all)
        quick.addWidget(btn_all)
        btn_none = _btn("✕ None")
        btn_none.setToolTip("Cull every sub-variant except the base.")
        btn_none.clicked.connect(self._keep_none)
        quick.addWidget(btn_none)
        btn_del_unsel = _btn("🗑 Delete unselected")
        btn_del_unsel.setToolTip(
            "Permanently delete every UNCHECKED sub-variant of this family "
            "(files → Anim/_Trash). The base is never deleted.")
        btn_del_unsel.clicked.connect(self._delete_unselected)
        quick.addWidget(btn_del_unsel)
        quick.addStretch()
        root.addLayout(quick)

        stepping = QHBoxLayout()
        stepping.setSpacing(8)
        btn_prev = _btn("◀  Prev main")
        btn_prev.clicked.connect(lambda: self._step_family(-1))
        stepping.addWidget(btn_prev)
        btn_next = _btn("Next main  ▶")
        btn_next.clicked.connect(lambda: self._step_family(1))
        stepping.addWidget(btn_next)
        root.addLayout(stepping)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

        self._show_base(0)

    # ── data ───────────────────────────────────────────────────────────
    def _family_variants(self, base: str) -> list:
        """Existing on-disk variants of one base, base first."""
        out = []
        if self._lib.get(self._gender, base) is not None:
            out.append(base)
        for mod in available_modifiers():
            name = f"{base} - {mod}"
            if self._lib.get(self._gender, name) is not None:
                out.append(name)
        return out

    def hidden(self) -> set:
        """Working hidden set (full variant names) for this gender."""
        return set(self._hidden)

    # ── ui ─────────────────────────────────────────────────────────────
    def _show_base(self, idx: int) -> None:
        if not self._bases:
            return
        self._idx = idx % len(self._bases)
        base = self._bases[self._idx]
        variants = self._family_variants(base)
        self.variant_list.blockSignals(True)
        self.variant_list.clear()
        for name in variants:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked
                               if name not in self._hidden
                               else Qt.CheckState.Unchecked)
            item.setToolTip(("Keep" if name not in self._hidden else "Culled")
                            + f" - click to preview {name}")
            self.variant_list.addItem(item)
        self.variant_list.blockSignals(False)
        self._refresh_header()
        # Preview the base (or first kept) so every family shows its face.
        first = next((n for n in variants if n not in self._hidden),
                     variants[0] if variants else base)
        self._preview(first)

    def _refresh_header(self) -> None:
        base = self._bases[self._idx]
        variants = self._family_variants(base)
        kept = sum(1 for n in variants if n not in self._hidden)
        self.lbl_family.setText(
            f"Main {self._idx + 1}/{len(self._bases)} - {base}")
        self.lbl_count.setText(
            f"keeping {kept}/{len(variants)} sub-variants"
            + ("  •  ✓ = survives, ☐ = tucked away" if variants else ""))

    def _preview(self, name: str) -> None:
        if self._preview_cb is not None:
            try:
                self._preview_cb(self._gender, name)
            except Exception:
                pass

    def _step_family(self, delta: int) -> None:
        if self._bases:
            self._show_base(self._idx + delta)

    def _keep_all(self) -> None:
        base = self._bases[self._idx]
        for n in self._family_variants(base):
            self._hidden.discard(n)
        self._show_base(self._idx)

    def _keep_none(self) -> None:
        base = self._bases[self._idx]
        variants = self._family_variants(base)
        for n in variants[1:]:
            self._hidden.add(n)
        if variants:
            self._hidden.discard(variants[0])
        self._show_base(self._idx)

    def _delete_unselected(self) -> None:
        """Delete this family's unchecked sub-variants from disk.

        Unchecked = culled (in the hidden set). The base is never deleted  - 
        an unchecked base simply stays tucked away. The dialog stays open on
        the same family so the new counts are visible immediately.
        """
        if not self._bases:
            return
        base = self._bases[self._idx]
        victims = [n for n in self._family_variants(base)
                   if n in self._hidden and n != base]
        if not victims:
            QMessageBox.information(
                self, "Nothing to delete",
                "Every sub-variant of this family is checked - uncheck the "
                "ones you want gone first (or press ✕ None).")
            return
        ans = QMessageBox.question(
            self, "Delete unselected?",
            f"Delete {len(victims)} unchecked sub-variant(s) of “{base}”?\n\n"
            + "\n".join(f"• {n}" for n in victims[:12])
            + (f"\n… and {len(victims) - 12} more" if len(victims) > 12 else "")
            + "\n\nFiles are parked in Anim/_Trash, not erased. The base stays.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if ans != QMessageBox.StandardButton.Ok:
            return
        gone, failed = 0, []
        for n in victims:
            try:
                ok, reason = self._lib.delete(self._gender, n)
            except Exception as exc:
                ok, reason = False, str(exc)
            if ok:
                gone += 1
                self._hidden.discard(n)
            else:
                failed.append(f"{n} ({reason})")
        self._show_base(self._idx)
        if failed:
            QMessageBox.warning(
                self, "Partially deleted",
                f"Deleted {gone}, failed {len(failed)}:\n" + "\n".join(failed[:8]))
        else:
            QMessageBox.information(
                self, "Deleted",
                f"Deleted {gone} sub-variant(s) → Anim/_Trash.\n"
                f"“{base}” and every checked variant survived.")

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        name = item.text()
        if item.checkState() == Qt.CheckState.Checked:
            self._hidden.discard(name)
        else:
            self._hidden.add(name)
        self._refresh_header()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self._preview(item.text())


# ── 5-Style Dropdown & Quick-Switch Hook (Female, Male, Detailed Female, Detailed Male, Chibi) ──
_STUDIO_STYLE_ITEMS = [
    ("♀  Female (Original)", "Female"),
    ("♂  Male (Original)", "Male"),
    ("♀✨ Detailed Female", "Detailed Female"),
    ("♂✨ Detailed Male", "Detailed Male"),
    ("🐣 Chibi (Subtle)", "Chibi"),
]

_orig_studio_init = AvatarStudioWidget.__init__

def _patched_studio_init(self, *args, **kwargs):
    _orig_studio_init(self, *args, **kwargs)
    try:
        self.combo_gender.blockSignals(True)
        self.combo_gender.clear()
        for label, g_key in _STUDIO_STYLE_ITEMS:
            self.combo_gender.addItem(label, g_key)
        # Pick the index that matches the gender we actually loaded so the
        # dropdown and the preview never disagree (oct 19 #5).
        _idx = 0
        for i, (_label, g_key) in enumerate(_STUDIO_STYLE_ITEMS):
            if g_key == getattr(self, "gender", None):
                _idx = i
                break
        self.combo_gender.setCurrentIndex(_idx)
        self.combo_gender.blockSignals(False)
    except Exception:
        pass

def _patched_on_gender_changed(self, idx: int) -> None:
    if 0 <= idx < len(_STUDIO_STYLE_ITEMS):
        new_gender = _STUDIO_STYLE_ITEMS[idx][1]
    else:
        new_gender = "Female"
    if new_gender == self.gender:
        return
    self.gender = new_gender
    self._current = None
    self.ensure_loaded(blocking=True)
    self._request('gender', new_gender)

AvatarStudioWidget.__init__ = _patched_studio_init
AvatarStudioWidget._on_gender_changed = _patched_on_gender_changed


# ── 3. Rock-Solid Zero-Shake EXPRESSIONS Menu Hook ───────────────────────────
import warnings as _st_warnings
from PySide6.QtWidgets import QAbstractButton, QAbstractItemView, QListWidget
from cellium.core.svg_icons import iconify_button

_prev_studio_init_v3 = AvatarStudioWidget.__init__


def _get_studio_avatar_view(self):
    v = getattr(self, "view", None)
    if v is not None:
        return v
    from cellium.ui.avatar.widget import AvatarView
    v = self.findChild(AvatarView)
    self.view = v
    return v


def _stable_studio_init(self, *args, **kwargs):
    _prev_studio_init_v3(self, *args, **kwargs)
    _get_studio_avatar_view(self)
    try:
        if hasattr(self, "_load_timer") and self._load_timer is not None:
            self._load_timer.stop()

        if hasattr(self, "_mod_buttons"):
            for mb in self._mod_buttons.values():
                p_box = mb.parentWidget()
                if p_box is not None and p_box is not self:
                    p_box.hide()
                    break

        lw = self.expr_list
        lw.setAutoScroll(False)
        lw.setDragEnabled(False)
        lw.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        lw.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        lw.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lw.setUniformItemSizes(True)
        lw.verticalScrollBar().setSingleStep(10)
        lw.setStyleSheet(
            "QListWidget { background: rgba(10, 7, 20, 0.78); border: 1px solid rgba(168, 85, 247, 0.32); "
            "border-radius: 10px; padding: 4px; outline: none; } "
            "QListWidget::item { height: 28px; padding: 2px 10px; border-radius: 6px; color: #E9D5FF; font-size: 12px; } "
            "QListWidget::item:hover:!selected { background: rgba(147, 51, 234, 0.22); } "
            "QListWidget::item:selected { background: rgba(147, 51, 234, 0.68); color: #FFFFFF; font-weight: bold; }"
        )

        with _st_warnings.catch_warnings():
            _st_warnings.simplefilter("ignore")
            for sig in (lw.itemClicked, lw.currentTextChanged, lw.currentRowChanged):
                try:
                    sig.disconnect()
                except Exception:
                    pass
        lw.currentTextChanged.connect(self._on_stable_item_selected)

        for lbl_attr in ("readout", "lbl_meta", "lbl_status", "status"):
            w_lbl = getattr(self, lbl_attr, None)
            if w_lbl is not None and hasattr(w_lbl, "setMinimumHeight"):
                w_lbl.setMinimumHeight(22)

        # Convert all studio buttons to crisp .svg/.png QIcons
        for btn in self.findChildren(QAbstractButton):
            iconify_button(btn)
    except Exception:
        pass


def _on_stable_item_selected(self, text: str) -> None:
    name = (text or "").strip()
    if not name or getattr(self, "_suppress_list_signal", False):
        return
    self._current = name
    expr = self._lib.get(self.gender, name)
    if expr is not None:
        v = _get_studio_avatar_view(self)
        if v is not None:
            v.set_expression(expr)
        if hasattr(self, "_update_readout"):
            try:
                self._update_readout(expr)
            except Exception:
                pass


def _stable_select(self, name: str, scroll_into_view: bool = False) -> None:
    if not name:
        return
    self._current = name
    expr = self._lib.get(self.gender, name)
    if expr is not None:
        v = _get_studio_avatar_view(self)
        if v is not None:
            v.set_expression(expr)
        if hasattr(self, "_update_readout"):
            try:
                self._update_readout(expr)
            except Exception:
                pass

    lw = self.expr_list
    cur_item = lw.currentItem()
    if cur_item is not None and cur_item.text() == name:
        return

    items = lw.findItems(name, Qt.MatchFlag.MatchExactly)
    if items:
        self._suppress_list_signal = True
        try:
            lw.setCurrentItem(items[0])
            if scroll_into_view:
                lw.scrollToItem(items[0], QListWidget.ScrollHint.EnsureVisible)
        finally:
            self._suppress_list_signal = False


def _stable_refilter(self) -> None:
    needle = (self.search.text() or "").strip().lower() if hasattr(self, "search") else ""
    hidden_set = set((getattr(self, "_hidden", {}) or {}).get(self.gender, []) or [])
    new_filtered = [
        n for n in getattr(self, "_all", [])
        if n not in hidden_set and (not needle or needle in n.lower())
    ]
    self._filtered = new_filtered

    lw = self.expr_list
    existing = [lw.item(i).text() for i in range(lw.count())]
    if existing != new_filtered:
        self._suppress_list_signal = True
        vbar = lw.verticalScrollBar()
        prev_scroll = vbar.value() if vbar is not None else 0
        lw.setUpdatesEnabled(False)
        try:
            lw.clear()
            lw.addItems(new_filtered)
            target = self._current if self._current in new_filtered else (new_filtered[0] if new_filtered else None)
            if target:
                self._current = target
                matches = lw.findItems(target, Qt.MatchFlag.MatchExactly)
                if matches:
                    lw.setCurrentItem(matches[0])
            if vbar is not None and not needle:
                vbar.setValue(prev_scroll)
        finally:
            lw.setUpdatesEnabled(True)
            self._suppress_list_signal = False

    if hasattr(self, "lbl_count"):
        try:
            self.lbl_count.setText(f"{len(new_filtered)} / {len(getattr(self, '_all', []))}")
        except Exception:
            pass
    if self._current:
        expr = self._lib.get(self.gender, self._current)
        if expr is not None:
            v = _get_studio_avatar_view(self)
            if v is not None:
                v.set_expression(expr)
            if hasattr(self, "_update_readout"):
                try:
                    self._update_readout(expr)
                except Exception:
                    pass


def _stable_ensure_loaded(self, blocking: bool = True) -> None:
    if hasattr(self, "_load_timer") and self._load_timer is not None:
        self._load_timer.stop()
    if not self._lib.names(self.gender) and hasattr(self._lib, "load_gender"):
        for _ in self._lib.load_gender(self.gender, batch_size=512):
            pass
    self._all = self._lib.names(self.gender)
    if not self._current or self._current not in self._all:
        self._current = self._all[0] if self._all else None
    self._refilter()
    if hasattr(self, "_refresh_matrix"):
        try:
            self._refresh_matrix()
        except Exception:
            pass


AvatarStudioWidget.__init__ = _stable_studio_init
AvatarStudioWidget._on_stable_item_selected = _on_stable_item_selected
AvatarStudioWidget._select = _stable_select
AvatarStudioWidget._refilter = _stable_refilter
AvatarStudioWidget.ensure_loaded = _stable_ensure_loaded


# ══ WAVE_OMG_PARITY_START ══
import random as _st_rng

_BOOT_PLEASANT_FACES = (
    "Happy", "Kawaii", "Chibi Joy", "Excited", "Winking", "UwU",
    "Flirty", "Sparkle Hype", "Starstruck", "Feeling Cool", "Smug", "Relieved",
)


def _studio_random_face_for(lib, gender: str) -> str:
    names = lib.names(gender)
    if not names:
        return "Happy"
    pleasant = [n for n in _BOOT_PLEASANT_FACES if n in names]
    pool = pleasant if pleasant else names
    return _st_rng.choice(pool)


_orig_stable_ensure_loaded_omg = AvatarStudioWidget.ensure_loaded


def _random_ensure_loaded(self, blocking: bool = True) -> None:
    was_empty = not bool(self._current)
    _orig_stable_ensure_loaded_omg(self, blocking=blocking)
    if was_empty and self._all:
        pick = _studio_random_face_for(self._lib, self.gender)
        if pick in self._all:
            self._select(pick, scroll_into_view=True)


AvatarStudioWidget.ensure_loaded = _random_ensure_loaded
# ══ WAVE_OMG_PARITY_END ══
