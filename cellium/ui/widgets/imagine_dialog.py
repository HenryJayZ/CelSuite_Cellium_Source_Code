#!/usr/bin/env python3
"""
Imagine Dialog - Image Generation UI for the online Kaggle backend.

Two surfaces:
  • Simple   - prompt, quick style, resolution, batch.
  • Advanced - model engine, enhancer, negative prompt, sampler knobs, seed.

CelAS-style prompt logic:
  • **Prompt**      = the main subject (remembered between sessions).
  • **Sticky**      = a persistent style/quality suffix appended to every render.
  • **Negative**    = what to avoid (remembered).
  • **Quick style** = presets that APPEND their tag block to the sticky prompt
                      instead of replacing whatever is already there.

Nothing local ever leaves the PC: renders always run on Kaggle.
"""

from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFrame,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QTextEdit, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer

from cellium.ui.chat.glass import GlassPanel
from cellium.services.kaggle_image import MODEL_PRESETS, preset_by_name


# CelAS "Quick Style" presets - each one APPENDS to the sticky prompt.
STYLE_PRESETS = [
    ("✨ Select aesthetic style…", ""),
    ("🌸 Masterpiece Anime (Clean)",
     "masterpiece, best quality, ultra-detailed anime aesthetic, expressive eyes, "
     "vibrant colors, clean lineart"),
    ("📼 Retro 90s Cel Animation (Nostalgic)",
     "retro anime aesthetic, 1990s cel animation style, nostalgic color palette, "
     "retro anime screengrab, grain texture"),
    ("🧸 Chibi Kawaii (Super Cute)",
     "chibi style, kawaii aesthetic, rounded soft proportions, pastel palette, "
     "super cute, adorable expression"),
    ("⚔️ Dark Cinematic Fantasy (Epic)",
     "cinematic fantasy, dramatic dark atmosphere, volumetric lighting, "
     "hyper-detailed, epic composition, unreal engine render"),
    ("🌆 Cyberpunk Neon (Futuristic)",
     "cyberpunk aesthetic, vibrant neon lighting, reflections, rainy night city, "
     "high-tech glow, volumetric haze"),
    ("🎨 Soft Watercolor (Dreamy)",
     "soft watercolor painting, delicate brushstrokes, watercolor wash, "
     "ethereal lighting, gentle pastel tones"),
]

SIZES = [
    "512x512 (1:1)", "768x768 (1:1)", "832x1216 (9:16)", "1216x832 (16:9)",
    "1024x1024 (1:1)", "896x1152 (3:4)", "1152x896 (4:3)",
    "768x1344 (9:16)", "1344x768 (16:9)", "1536x640 (21:9)",
]
DEFAULT_SIZE = "832x1216 (9:16)"
DEFAULT_NEG = ("worst quality, low quality, ugly, blurry, deformed, bad anatomy, "
               "watermark, signature")


class ImagineDialog(QFrame):
    """Inbuilt modal glass panel for configuring and triggering image generation."""

    generate_requested = Signal(dict)  # params dict
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ImaginePanel")
        self._mode = "simple"
        self._advanced_only: list[QWidget] = []
        self._ready = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(420, 360)
        self.resize(560, 480)

        self._build_ui()
        self._load_settings()
        self._ready = True
        mode = str((self._settings_dict() or {}).get("kaggle_dialog_mode", "simple")).lower()
        self._set_mode("advanced" if mode == "advanced" else "simple", persist=False)

    def accept(self):
        self._persist()
        self.hide()
        self.closed.emit()

    def reject(self):
        self._persist()
        self.hide()
        self.closed.emit()

    def close(self):
        self.reject()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            event.accept()
        else:
            super().keyPressEvent(event)

    def center_in_parent(self):
        p = self.parentWidget()
        if p:
            pw, ph = p.width(), p.height()
            w = min(600, max(460, pw - 40))
            # Keep dialog safely within container height so the pinned footer never clips
            target_h = 560 if self._mode == "advanced" else 480
            h = min(target_h, max(360, ph - 30))
            x = max(10, (pw - w) // 2)
            y = max(10, (ph - h) // 2)
            self.setGeometry(x, y, w, h)

    # ── settings bridge ───────────────────────────────────────────────────────
    def _settings_dict(self):
        mw = self.parent()
        s = getattr(mw, "settings", None)
        return s if isinstance(s, dict) else None

    def _persist(self) -> None:
        """Remember prompt, sticky tags, negative prompt and every simple knob."""
        if not getattr(self, "_ready", False):
            return
        s = self._settings_dict()
        if s is None:
            return
        try:
            s["kaggle_prompt"] = self.edit_prompt.toPlainText()
            s["kaggle_sticky_prompt"] = self.edit_sticky.toPlainText()
            s["kaggle_negative_prompt"] = self.edit_neg.toPlainText()
            s["kaggle_steps"] = int(self.spin_steps.value())
            s["kaggle_guidance"] = float(self.spin_guid.value())
            s["kaggle_size"] = self.combo_size.currentText()
            s["kaggle_batch"] = int(self.spin_batch.value())
            s["kaggle_preset"] = self.combo_model.currentText()
            s["kaggle_dialog_mode"] = self._mode
        except RuntimeError:
            return
        saver = getattr(self.parent(), "save_settings", None)
        if callable(saver):
            try:
                saver()
            except Exception:
                pass

    def done(self, result):
        self._persist()
        super().done(result)

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        panel = GlassPanel(radius=18, panel_opacity=0.9)
        panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        v = QVBoxLayout(panel)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(12)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("🎨 Imagine")
        title.setStyleSheet(
            "font-size: 18px; font-weight: 800; color: #F8F4FF; border: none;")
        hdr.addWidget(title)
        sub = QLabel("Kaggle GPU · cloud render")
        sub.setStyleSheet(
            "font-size: 10px; color: #9F86C9; border: none; padding-top: 4px;")
        hdr.addWidget(sub)
        hdr.addStretch()
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(32, 32)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: rgba(239, 68, 68, 0.3); border: 1px solid #EF4444;
                border-radius: 16px; color: #FCA5A5; font-weight: bold; font-size: 14px;
            }
            QPushButton:hover { background: #EF4444; color: white; }
        """)
        btn_close.clicked.connect(self.reject)
        hdr.addWidget(btn_close)
        v.addLayout(hdr)

        # Simple / Advanced segmented control
        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(8)
        self.btn_mode_simple = QPushButton("✦  Simple")
        self.btn_mode_adv = QPushButton("⚙  Advanced")
        for btn in (self.btn_mode_simple, self.btn_mode_adv):
            btn.setObjectName("modeBtn")
            btn.setCheckable(True)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet(self._mode_style())
            mode_bar.addWidget(btn)
        self.btn_mode_simple.clicked.connect(lambda: self._set_mode("simple"))
        self.btn_mode_adv.clicked.connect(lambda: self._set_mode("advanced"))
        v.addLayout(mode_bar)

        # Scrollable form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: rgba(15, 10, 25, 0.4); width: 8px; border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(168, 85, 247, 0.5); min-height: 25px; border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover { background: #A855F7; }
        """)
        content = QWidget()
        content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        content.setStyleSheet("background: transparent;")
        form = QVBoxLayout(content)
        form.setContentsMargins(4, 6, 10, 14)
        form.setSpacing(11)

        # ── Advanced: model engine ──
        self.combo_model = QComboBox()
        self.combo_model.addItems([p["name"] for p in MODEL_PRESETS])
        self.combo_model.setStyleSheet(self._combo_style())
        form.addWidget(self._block(
            "🤖 Model engine", self.combo_model, advanced=True,
            hint="Kaggle preset"))

        # ── Advanced: prompt enhancer ──
        self.combo_enhancer = QComboBox()
        self.combo_enhancer.setStyleSheet(self._combo_style())
        self.combo_enhancer.addItem("✨ Local tags (offline)")
        form.addWidget(self._block(
            "✨ Prompt enhancer", self.combo_enhancer, advanced=True,
            hint="optional LLM"))

        # ── Prompt (always visible) ──
        self._enh_state = "idle"          # idle|working|retry|error
        self._pre_enhance_prompt = ""
        self._enh_worker = None
        self._enh_cancel = None
        self._enh_retry = 0
        self._enh_retry_timer = None
        self._enh_dots_timer = None
        self._enh_start = 0.0
        self._enh_dots = 0
        self._enh_btn = QPushButton("✨ Enhance")
        self._enh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._enh_btn.setToolTip("Expand your idea into a rich tag list (Mini-App style)")
        self._enh_btn.setStyleSheet(self._ENH_IDLE_SS)
        self._enh_btn.clicked.connect(self._enhance)
        self.edit_prompt = QTextEdit()
        self.edit_prompt.textChanged.connect(self._on_prompt_edited)
        self.edit_prompt.setPlaceholderText("Describe what you want to generate…")
        self.edit_prompt.setFixedHeight(92)
        self.edit_prompt.setStyleSheet(self._input_style())
        form.addWidget(self._block_with_action(
            "✨ Prompt", self._enh_btn, self.edit_prompt))

        # ── Sticky style + appending quick presets (always visible) ──
        sticky_box = QWidget()
        sticky_box.setStyleSheet("background: transparent;")
        sv = QVBoxLayout(sticky_box)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(6)
        s_head = QHBoxLayout()
        s_head.setContentsMargins(0, 0, 0, 0)
        s_head.setSpacing(8)
        s_lbl = QLabel("🍯 Sticky style")
        s_lbl.setStyleSheet(self._label_style())
        s_head.addWidget(s_lbl)
        s_hint = QLabel("appended to every prompt")
        s_hint.setStyleSheet(self._hint_style())
        s_head.addWidget(s_hint)
        s_head.addStretch()
        sv.addLayout(s_head)
        self.combo_style = QComboBox()
        self.combo_style.addItems([name for name, _ in STYLE_PRESETS])
        self.combo_style.setStyleSheet(self._combo_style())
        self.combo_style.setToolTip("Appends the chosen aesthetic tags to the sticky prompt")
        self.combo_style.currentIndexChanged.connect(self._on_style_preset)
        sv.addWidget(self.combo_style)
        self.edit_sticky = QTextEdit()
        self.edit_sticky.setPlaceholderText(
            "Persistent quality tags (e.g. masterpiece, best quality, soft light)…")
        self.edit_sticky.setFixedHeight(48)
        self.edit_sticky.setStyleSheet(self._input_style())
        sv.addWidget(self.edit_sticky)
        form.addWidget(sticky_box)

        # ── Advanced: negative prompt ──
        self.edit_neg = QTextEdit()
        self.edit_neg.setPlaceholderText("What to avoid (optional)…")
        self.edit_neg.setFixedHeight(62)
        self.edit_neg.setStyleSheet(self._input_style())
        form.addWidget(self._block(
            "🚫 Negative prompt", self.edit_neg, advanced=True))

        # ── Advanced: sampler & seed ──
        form.addWidget(self._section("⚙️ Sampler & seed", advanced=True))

        self.spin_steps = QSpinBox()
        self.spin_steps.setRange(1, 100)
        self.spin_steps.setValue(28)
        self.spin_steps.setStyleSheet(self._spin_style())
        form.addWidget(self._inline_block("Steps", self.spin_steps, advanced=True))

        self.spin_guid = QDoubleSpinBox()
        self.spin_guid.setRange(0.0, 20.0)
        self.spin_guid.setSingleStep(0.5)
        self.spin_guid.setValue(6.5)
        self.spin_guid.setStyleSheet(self._spin_style())
        form.addWidget(self._inline_block("Guidance", self.spin_guid, advanced=True))

        self.spin_seed = QSpinBox()
        self.spin_seed.setRange(-1, 2147483647)
        self.spin_seed.setValue(-1)
        self.spin_seed.setStyleSheet(self._spin_style())
        self.spin_seed.setEnabled(False)
        self.chk_random = QCheckBox("Random each time")
        self.chk_random.setChecked(True)
        self.chk_random.setStyleSheet(
            "QCheckBox { color: #C084FC; font-size: 11px; border: none; }"
            "QCheckBox::indicator { width: 15px; height: 15px; }")
        self.chk_random.toggled.connect(lambda v: self.spin_seed.setEnabled(not v))
        form.addWidget(self._inline_block(
            "Seed", self.spin_seed, self.chk_random, advanced=True))

        # ── Simple knobs (always visible) ──
        self.combo_size = QComboBox()
        self.combo_size.addItems(SIZES)
        self.combo_size.setCurrentText(DEFAULT_SIZE)
        self.combo_size.setStyleSheet(self._combo_style())
        self.spin_batch = QSpinBox()
        self.spin_batch.setRange(1, 20)
        self.spin_batch.setValue(1)
        self.spin_batch.setStyleSheet(self._spin_style())

        size_box = self._block("🖼 Resolution", self.combo_size)
        batch_box = self._block("🔢 Images", self.spin_batch)
        knobs = QHBoxLayout()
        knobs.setSpacing(12)
        knobs.addWidget(size_box, stretch=3)
        knobs.addWidget(batch_box, stretch=2)
        form.addLayout(knobs)

        form.addStretch()
        scroll.setWidget(content)
        v.addWidget(scroll, stretch=1)

        # Footer (always visible)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.08); color: #F8F4FF;
                border: 1px solid rgba(255,255,255,0.2); border-radius: 8px;
                padding: 10px 24px; font-weight: bold; font-size: 12px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.15); }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_generate = QPushButton("🎨 Generate")
        btn_generate.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_generate.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #A855F7, stop:1 #EC4899);
                border: 1.5px solid #E9D5FF; border-radius: 10px; color: white;
                padding: 10px 32px; font-weight: bold; font-size: 13px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #C084FC, stop:1 #F472B6);
            }
        """)
        btn_generate.clicked.connect(self._emit_generate)
        btn_row.addWidget(btn_generate)
        v.addLayout(btn_row)

        outer.addWidget(panel)

    # ── small builders ────────────────────────────────────────────────────────
    def _block(self, label: str, widget: QWidget, advanced: bool = False,
               hint: str = "") -> QWidget:
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        lbl = QLabel(label)
        lbl.setStyleSheet(self._label_style())
        head.addWidget(lbl)
        if hint:
            h = QLabel(hint)
            h.setStyleSheet(self._hint_style())
            head.addWidget(h)
        head.addStretch()
        lay.addLayout(head)
        lay.addWidget(widget)
        if advanced:
            self._advanced_only.append(box)
        return box

    def _block_with_action(self, label: str, action: QWidget, widget: QWidget,
                           advanced: bool = False) -> QWidget:
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        lbl = QLabel(label)
        lbl.setStyleSheet(self._label_style())
        head.addWidget(lbl)
        head.addStretch()
        head.addWidget(action)
        lay.addLayout(head)
        lay.addWidget(widget)
        if advanced:
            self._advanced_only.append(box)
        return box

    def _inline_block(self, label: str, *widgets: QWidget,
                      advanced: bool = False) -> QWidget:
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        lbl = QLabel(label)
        lbl.setStyleSheet(self._label_style())
        h.addWidget(lbl)
        for w in widgets:
            h.addWidget(w)
        h.addStretch()
        if advanced:
            self._advanced_only.append(box)
        return box

    def _section(self, text: str, advanced: bool = False) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-weight: 800; font-size: 12px; color: #C084FC; border: none;"
            "margin-top: 6px;")
        if advanced:
            self._advanced_only.append(lbl)
        return lbl

    # ── Simple / Advanced ─────────────────────────────────────────────────────
    def _set_mode(self, mode: str, persist: bool = True) -> None:
        mode = "advanced" if str(mode).lower() == "advanced" else "simple"
        self._mode = mode
        simple = mode == "simple"
        for w in self._advanced_only:
            try:
                w.setVisible(not simple)
            except RuntimeError:
                pass
        self.btn_mode_simple.setChecked(simple)
        self.btn_mode_adv.setChecked(not simple)
        for b in (self.btn_mode_simple, self.btn_mode_adv):
            b.style().unpolish(b)
            b.style().polish(b)
        if persist and self._ready:
            self._persist()
        self.center_in_parent()

    # ── appending style presets (CelAS logic) ─────────────────────────────────
    def _on_style_preset(self, index: int) -> None:
        if index <= 0:
            return
        text = STYLE_PRESETS[index][1]
        cur = self.edit_sticky.toPlainText().strip()
        if text and text not in cur:
            self.edit_sticky.setPlainText(f"{cur}, {text}" if cur else text)
        self.combo_style.blockSignals(True)
        self.combo_style.setCurrentIndex(0)
        self.combo_style.blockSignals(False)

    # ── settings load ─────────────────────────────────────────────────────────
    def _load_settings(self) -> None:
        s = self._settings_dict() or {}

        preset_name = str(s.get("kaggle_preset", "") or "")
        self.combo_model.blockSignals(True)
        i = self.combo_model.findText(preset_name)
        if i >= 0:
            self.combo_model.setCurrentIndex(i)
        self.combo_model.blockSignals(False)
        self.combo_model.currentTextChanged.connect(self._on_model_changed)

        try:
            mw = self.parent()
            models = getattr(mw, "models", {}) if mw is not None else {}
            for name in sorted(models.keys()):
                self.combo_enhancer.addItem(name)
            saved = str(s.get("kaggle_enhancer_model", "") or "")
            if saved:
                j = self.combo_enhancer.findText(saved)
                if j >= 0:
                    self.combo_enhancer.setCurrentIndex(j)
        except Exception:
            pass

        self.edit_prompt.setPlainText(str(s.get("kaggle_prompt", "") or ""))
        self.edit_sticky.setPlainText(str(s.get("kaggle_sticky_prompt", "") or ""))
        self.edit_neg.setPlainText(
            str(s.get("kaggle_negative_prompt", DEFAULT_NEG) or DEFAULT_NEG))

        try:
            self.spin_steps.setValue(
                max(1, min(100, int(s.get("kaggle_steps", 28) or 28))))
        except Exception:
            self.spin_steps.setValue(28)
        try:
            self.spin_guid.setValue(
                max(0.0, min(20.0, float(s.get("kaggle_guidance", 6.5) or 6.5))))
        except Exception:
            self.spin_guid.setValue(6.5)
        try:
            self.spin_batch.setValue(
                max(1, min(20, int(s.get("kaggle_batch", 1) or 1))))
        except Exception:
            self.spin_batch.setValue(1)

        size = str(s.get("kaggle_size", DEFAULT_SIZE) or DEFAULT_SIZE)
        if self.combo_size.findText(size) < 0:
            self.combo_size.addItem(size)
        self.combo_size.setCurrentText(size)
        self.edit_prompt.setFocus()

    # ── ✨ Enhance button state machine ────────────────────────────────────────
    _ENH_IDLE_SS = """
        QPushButton { background: rgba(147,51,234,0.3); color:#E9D5FF; border:1px solid #A855F7;
            border-radius:8px; padding:4px 10px; font-size:11px; font-weight:bold; }
        QPushButton:hover { background: rgba(147,51,234,0.55); color:#fff; }"""
    _ENH_BUSY_SS = """
        QPushButton { background: rgba(59,130,246,0.35); color:#BFDBFE; border:1px solid #3B82F6;
            border-radius:8px; padding:4px 10px; font-size:11px; font-weight:bold; }
        QPushButton:hover { background: rgba(59,130,246,0.6); color:#fff; }"""
    _ENH_ERR_SS = """
        QPushButton { background: rgba(245,158,11,0.4); color:#FDE68A; border:1.5px solid #F59E0B;
            border-radius:8px; padding:4px 10px; font-size:11px; font-weight:bold; }
        QPushButton:hover { background: rgba(245,158,11,0.7); color:#fff; }"""
    _ENH_OK_SS = """
        QPushButton { background: rgba(16,185,129,0.5); color:#D1FAE5; border:1px solid #10B981;
            border-radius:8px; padding:4px 10px; font-size:11px; font-weight:bold; }"""

    def _enh_set_btn(self, text, ss, tip=None, enabled=True):
        b = getattr(self, "_enh_btn", None)
        if b is None:
            return
        b.setText(text)
        b.setStyleSheet(ss)
        b.setEnabled(enabled)
        if tip is not None:
            b.setToolTip(tip)

    def _on_prompt_edited(self):
        # user edited after a success/error → clear retry state back to idle
        if getattr(self, "_enh_state", "idle") == "error":
            self._enh_state = "idle"
            self._enh_set_btn("✨ Enhance", self._ENH_IDLE_SS,
                              "Expand your idea into a rich tag list")

    def _enhance(self):
        from cellium.services.kaggle_image import enhance_prompt
        # click while working = cancel
        if self._enh_state == "working":
            if self._enh_cancel is not None:
                self._enh_cancel.set()
            self._stop_dots()
            self._enh_state = "idle"
            self._enh_set_btn("✨ Enhance", self._ENH_IDLE_SS,
                              "Expand your idea into a rich tag list")
            return
        # retry path: always enhance from the stored ORIGINAL prompt
        if self._enh_state == "error":
            cur = self._pre_enhance_prompt or self.edit_prompt.toPlainText().strip()
        else:
            cur = self.edit_prompt.toPlainText().strip()
        if not cur:
            return
        self._pre_enhance_prompt = cur
        enh = self.combo_enhancer.currentText()
        mw = self.parent()
        model_key = "" if (not enh or enh.startswith("✨ Local")) else enh
        # local fallback is instant → straight to success, no working state
        if not model_key or mw is None:
            self.edit_prompt.setPlainText(enhance_prompt(cur, "sdxl"))
            self._flash_ok()
            return
        self._start_enhance(model_key, mw, cur)

    def _start_enhance(self, model_key, mw, original, reset_retry=True):
        from cellium.services.kaggle_image import enhance_with_model, EnhanceError
        self._enh_state = "working"
        if reset_retry:
            self._enh_retry = 0
        self._enh_cancel = __import__("threading").Event()
        self._enh_start = __import__("time").monotonic()
        self._enh_dots = 0
        short = model_key if len(model_key) <= 24 else model_key[:21] + "…"
        self._enh_set_btn(f"✨ Pinging {short}…", self._ENH_BUSY_SS,
                          "Click to cancel", enabled=True)
        # animated dots + elapsed tooltip
        self._dots_timer = QTimer(self)
        self._dots_timer.setInterval(400)

        def _tick():
            self._enh_dots += 1
            el = int(__import__("time").monotonic() - self._enh_start)
            dots = "." * (1 + self._enh_dots % 3)
            self._enh_set_btn(f"✨ Pinging {short}{dots}", self._ENH_BUSY_SS,
                              f"Calling {model_key}… {el}s - click to cancel")
        self._dots_timer.timeout.connect(_tick)
        self._dots_timer.start()

        settings = getattr(mw, "settings", {})
        models = getattr(mw, "models", {})

        class _W(QThread):
            ok = Signal(str)
            failed = Signal(object)  # EnhanceError

            def __init__(self, parent=None):
                super().__init__(parent)
                self._cancel = None

            def run(self):
                try:
                    if self._cancel is not None and self._cancel.is_set():
                        return
                    out = enhance_with_model(original, model_key, settings, models)
                    if self._cancel is not None and self._cancel.is_set():
                        return
                    self.ok.emit(out)
                except EnhanceError as e:
                    self.failed.emit(e)
                except Exception as e:
                    self.failed.emit(EnhanceError("network", f"{type(e).__name__}: {e}"))
        w = _W(self)
        w._cancel = self._enh_cancel
        self._enh_worker = w
        w.ok.connect(self._enhance_ok)
        w.failed.connect(self._enhance_failed)
        w.start()

    def _stop_dots(self):
        if getattr(self, "_dots_timer", None):
            try:
                self._dots_timer.stop()
            except Exception:
                pass

    def _flash_ok(self, then_idle=True):
        self._stop_dots()
        self._enh_state = "idle"
        self._enh_set_btn("✅ Enhanced", self._ENH_OK_SS, "Enhanced!", enabled=False)
        if then_idle:
            def _back_to_idle():
                if getattr(self, "_enh_state", "idle") == "idle":
                    self._enh_set_btn("✨ Enhance", self._ENH_IDLE_SS,
                                      "Expand your idea into a rich tag list", enabled=True)
            QTimer.singleShot(1500, _back_to_idle)

    def _enhance_ok(self, text):
        if self._enh_cancel is not None and self._enh_cancel.is_set():
            return  # cancelled - leave prompt untouched
        self.edit_prompt.setPlainText(text)
        self._flash_ok()

    def _enhance_failed(self, err):
        from cellium.services.kaggle_image import EnhanceError
        if self._enh_cancel is not None and self._enh_cancel.is_set():
            return
        self._stop_dots()
        kind = getattr(err, "kind", "network")
        if kind == "rate_limit" and self._enh_retry < 3:
            self._enh_retry += 1
            wait = 2 ** self._enh_retry  # 2,4,8
            self._enh_state = "retry"
            self._enh_set_btn(f"⏳ Rate-limited - retry {self._enh_retry}/3 in {wait}s…",
                              self._ENH_BUSY_SS, "Auto-retrying…", enabled=False)
            self._enh_retry_timer = QTimer(self)
            self._enh_retry_timer.setSingleShot(True)
            self._enh_retry_timer.timeout.connect(
                lambda: self._start_enhance(self._enh_model_key(), self.parent(),
                                            self._pre_enhance_prompt, reset_retry=False))
            self._enh_retry_timer.start(wait * 1000)
            return
        # permanent failure → retry button
        self._enh_state = "error"
        short = str(err)[:80]
        self._enh_set_btn("↻ Retry enhance", self._ENH_ERR_SS,
                          f"Enhance failed: {short} - click to retry", enabled=True)

    def _enh_model_key(self):
        enh = self.combo_enhancer.currentText()
        return "" if (not enh or enh.startswith("✨ Local")) else enh

    def _on_model_changed(self, name: str):
        p = preset_by_name(name)
        if not p:
            return
        if p.get("steps"):
            self.spin_steps.setValue(p["steps"])
        if p.get("guidance"):
            self.spin_guid.setValue(p["guidance"])

    # ── generate ──────────────────────────────────────────────────────────────
    def _emit_generate(self):
        main = self.edit_prompt.toPlainText().strip()
        sticky = self.edit_sticky.toPlainText().strip().strip(",")
        prompt = f"{main}, {sticky}" if sticky else main
        if not prompt:
            self.edit_prompt.setFocus()
            return
        self._persist()
        params = {
            "prompt": prompt,
            "negative_prompt": self.edit_neg.toPlainText().strip(),
            "steps": self.spin_steps.value(),
            "size": self.combo_size.currentText(),
            "guidance": self.spin_guid.value(),
            "seed": -1 if self.chk_random.isChecked() else self.spin_seed.value(),
            "preset": self.combo_model.currentText(),
            "batch": self.spin_batch.value(),
            "sticky_prompt": sticky,
            "mode": self._mode,
        }
        self.generate_requested.emit(params)
        self.accept()

    # ── styles ────────────────────────────────────────────────────────────────
    def _label_style(self) -> str:
        return "color: #C4B5FD; font-size: 11px; font-weight: 700; border: none;"

    def _hint_style(self) -> str:
        return "color: #7E6A9E; font-size: 10px; border: none;"

    def _mode_style(self) -> str:
        return """
            QPushButton#modeBtn {
                background: rgba(255,255,255,0.04); color: #B9A6D8;
                border: 1px solid rgba(168,85,247,0.25); border-radius: 9px;
                padding: 6px 16px; font-size: 12px; font-weight: 700;
            }
            QPushButton#modeBtn:hover {
                background: rgba(168,85,247,0.16); color: #E9D5FF;
                border-color: rgba(192,132,252,0.55);
            }
            QPushButton#modeBtn:checked {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #7C3AED, stop:1 #A855F7);
                color: #FFFFFF; border: 1px solid #C084FC;
            }
        """

    def _input_style(self) -> str:
        return """
            QTextEdit {
                background: rgba(22, 14, 38, 0.42); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45); border-radius: 10px;
                padding: 8px 12px; font-size: 12px;
            }
            QTextEdit:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QTextEdit:focus { border: 2px solid #C084FC; }
        """

    def _combo_style(self) -> str:
        return """
            QComboBox {
                background: rgba(22, 14, 38, 0.42); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45); border-radius: 10px;
                padding: 8px 12px; font-size: 12px; min-width: 140px;
            }
            QComboBox:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QComboBox:focus { border: 2px solid #C084FC; }
            QComboBox QAbstractItemView {
                background: rgba(18, 12, 32, 0.96); border: 1.5px solid #A855F7;
                border-radius: 8px; color: #F0E6FF; selection-background-color: #8A2BE2;
            }
        """

    def _spin_style(self) -> str:
        return """
            QSpinBox, QDoubleSpinBox {
                background: rgba(22, 14, 38, 0.42); color: #F8F4FF;
                border: 1.5px solid rgba(147, 51, 234, 0.45); border-radius: 10px;
                padding: 8px 12px; font-size: 12px; min-width: 90px;
            }
            QSpinBox:hover, QDoubleSpinBox:hover { border: 1.5px solid rgba(192, 132, 252, 0.75); }
            QSpinBox:focus, QDoubleSpinBox:focus { border: 2px solid #C084FC; }
        """
