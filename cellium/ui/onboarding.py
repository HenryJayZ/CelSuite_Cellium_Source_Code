"""
Cellium 2026 Full-Window Liquid Glass Onboarding & Terms Wizard.
Mounts edge-to-edge inside the main window so zero background chrome is visible.
Closing the window or declining without accepting Terms immediately exits the app.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtCore import QEvent, QEventLoop, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QLinearGradient,
    QPainter,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cellium.ui.widgets.pfp import run_avatar_flow, clear_avatar, bust_avatar_cache

DIRECT_DOWNLOAD_LINKS = {
    "kokoro_onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.fp16.onnx",
    "kokoro_voices": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
    "kokoro_hf": "https://huggingface.co/hexgrad/Kokoro-82M",
    "whisper_fast": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en-q5_1.bin",
    "whisper_repo": "https://huggingface.co/ggerganov/whisper.cpp/tree/main",
    "gguf_bartowski": "https://huggingface.co/bartowski",
}

WIZARD_STYLESHEET = """
QWidget#CelliumOnboardingRoot {
    background: transparent;
}
QLabel {
    border: none;
    background: transparent;
    color: #F3E8FF;
    font-family: 'Segoe UI', system-ui, sans-serif;
}
QFrame#WizardOuterCard {
    background: rgba(14, 9, 28, 0.94);
    border: 1.5px solid rgba(192, 132, 252, 0.45);
    border-radius: 22px;
}
QFrame#WizardSectionCard {
    background: rgba(22, 15, 42, 0.88);
    border: 1px solid rgba(168, 85, 247, 0.32);
    border-radius: 14px;
}
QFrame#WizardSectionCard:hover {
    border: 1px solid rgba(216, 180, 254, 0.55);
    background: rgba(28, 19, 52, 0.94);
}
QFrame#TermsBoxCard {
    background: rgba(8, 5, 18, 0.92);
    border: 1px solid rgba(147, 51, 234, 0.40);
    border-radius: 14px;
}
QFrame#ConsentBannerCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(88, 28, 135, 0.42), stop:1 rgba(49, 16, 82, 0.42));
    border: 1.2px solid rgba(192, 132, 252, 0.55);
    border-radius: 12px;
}
QFrame#FeaturePillCard {
    background: rgba(147, 51, 234, 0.15);
    border: 1px solid rgba(192, 132, 252, 0.30);
    border-radius: 10px;
}
QPushButton#WizardPrimaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #A855F7, stop:1 #7C3AED);
    color: #FFFFFF;
    border: 1.5px solid #E879F9;
    border-radius: 11px;
    padding: 8px 22px;
    font-size: 13px;
    font-weight: bold;
    min-height: 36px;
}
QPushButton#WizardPrimaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #C084FC, stop:1 #9333EA);
    border-color: #FFFFFF;
}
QPushButton#WizardPrimaryBtn:disabled {
    background: rgba(76, 52, 110, 0.35);
    color: rgba(233, 213, 255, 0.38);
    border: 1px solid rgba(147, 51, 234, 0.22);
}
QPushButton#WizardSecondaryBtn {
    background: rgba(255, 255, 255, 0.06);
    color: #E9D5FF;
    border: 1px solid rgba(168, 85, 247, 0.42);
    border-radius: 11px;
    padding: 8px 18px;
    font-size: 12px;
    font-weight: 600;
    min-height: 36px;
}
QPushButton#WizardSecondaryBtn:hover {
    background: rgba(168, 85, 247, 0.28);
    color: #FFFFFF;
    border-color: #E879F9;
}
QPushButton#WizardSecondaryBtn:disabled {
    background: rgba(255, 255, 255, 0.02);
    color: rgba(233, 213, 255, 0.30);
    border-color: rgba(147, 51, 234, 0.16);
}
QPushButton#WizardDangerBtn {
    background: rgba(239, 68, 68, 0.16);
    color: #FCA5A5;
    border: 1px solid rgba(239, 68, 68, 0.48);
    border-radius: 11px;
    padding: 8px 16px;
    font-size: 12px;
    font-weight: bold;
    min-height: 36px;
}
QPushButton#WizardDangerBtn:hover {
    background: rgba(239, 68, 68, 0.38);
    color: #FFFFFF;
    border-color: #F87171;
}
QPushButton#WizardDownloadBtn {
    background: rgba(147, 51, 234, 0.26);
    color: #F5D0FE;
    border: 1px solid rgba(192, 132, 252, 0.58);
    border-radius: 9px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 600;
    min-height: 32px;
}
QPushButton#WizardDownloadBtn:hover {
    background: rgba(168, 85, 247, 0.52);
    color: #FFFFFF;
    border-color: #FFFFFF;
}
QPushButton#WizardCopyBtn {
    background: rgba(255, 255, 255, 0.07);
    color: #DDD6FE;
    border: 1px solid rgba(168, 85, 247, 0.34);
    border-radius: 9px;
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 600;
    min-height: 32px;
}
QPushButton#WizardCopyBtn:hover {
    background: rgba(168, 85, 247, 0.35);
    color: #FFFFFF;
}
QLineEdit, QComboBox {
    background: rgba(10, 7, 22, 0.92);
    color: #F8F4FF;
    border: 1.4px solid rgba(168, 85, 247, 0.55);
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 13px;
    min-height: 36px;
}
QLineEdit:focus, QComboBox:focus {
    border: 1.5px solid #E879F9;
}
QCheckBox {
    color: #F5D0FE;
    font-size: 13px;
    font-weight: 600;
    spacing: 10px;
    border: none;
    background: transparent;
}
QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border-radius: 6px;
    border: 1.5px solid #C084FC;
    background: rgba(10, 6, 22, 0.95);
}
QCheckBox::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #E879F9, stop:1 #9333EA);
    border-color: #FFFFFF;
}
"""


class CelliumOnboardingWizard(QDialog):
    """Full-window 4-step setup wizard embedded directly inside the main window."""

    completed = Signal()

    def __init__(self, main_win: Optional[QWidget] = None, parent: Optional[QWidget] = None):
        host = main_win or parent
        super().__init__(host)
        self.main_win = main_win
        self.setObjectName("CelliumOnboardingRoot")
        self._saved_chrome_vis: dict[QWidget, bool] = {}
        self._modal_loop: Optional[QEventLoop] = None

        if self.main_win is not None:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setParent(self.main_win)
            self.setGeometry(0, 0, max(800, self.main_win.width()), max(600, self.main_win.height()))
            self.main_win.installEventFilter(self)
        else:
            self.setWindowTitle("Cellium • Welcome & Setup")
            self.resize(980, 680)

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(WIZARD_STYLESHEET)

        self._build_ui()
        self._sync_nav_state()

    def _hide_main_window_chrome(self) -> None:
        if self.main_win is None:
            return
        for attr in ("left_drawer", "top_bar", "central_stack", "right_drawer", "input_pill"):
            w = getattr(self.main_win, attr, None)
            if isinstance(w, QWidget) and w not in self._saved_chrome_vis:
                self._saved_chrome_vis[w] = not w.isHidden()
                w.setVisible(False)
        self.setGeometry(0, 0, self.main_win.width(), self.main_win.height())
        self.raise_()

    def _restore_main_window_chrome(self) -> None:
        for w, was_vis in list(self._saved_chrome_vis.items()):
            try:
                w.setVisible(was_vis)
            except RuntimeError:
                pass
        self._saved_chrome_vis.clear()

    def exec(self) -> int:
        if self.main_win is not None and os.environ.get("QT_QPA_PLATFORM", "") not in ("offscreen",):
            if self.main_win.isHidden():
                self.main_win.show()
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setParent(self.main_win)
            self._hide_main_window_chrome()
            self.show()
            self.raise_()
            loop = QEventLoop(self)
            self._modal_loop = loop
            loop.exec()
            self._modal_loop = None
            return int(QDialog.DialogCode.Accepted)
        return super().exec()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.main_win and event is not None:
            et = event.type()
            if et == QEvent.Type.Resize:
                self.setGeometry(0, 0, self.main_win.width(), self.main_win.height())
                self.raise_()
            elif et == QEvent.Type.Close:
                accepted = False
                if hasattr(self.main_win, "settings") and isinstance(self.main_win.settings, dict):
                    accepted = bool(self.main_win.settings.get("terms_accepted", False))
                if not accepted and not self.chk_accept_terms.isChecked():
                    event.accept()
                    self._exit_app_unaccepted()
                    return True
        return super().eventFilter(watched, event)

    def showEvent(self, event) -> None:
        self._hide_main_window_chrome()
        super().showEvent(event)

    def _exit_app_unaccepted(self) -> None:
        if self._modal_loop is not None and self._modal_loop.isRunning():
            self._modal_loop.quit()
        if os.environ.get("QT_QPA_PLATFORM", "") == "offscreen":
            self.close()
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()
        os._exit(0)

    def reject(self) -> None:
        accepted = False
        if self.main_win is not None and hasattr(self.main_win, "settings"):
            accepted = bool(self.main_win.settings.get("terms_accepted", False))
        if not accepted and not self.chk_accept_terms.isChecked():
            self._exit_app_unaccepted()
            return
        self._restore_main_window_chrome()
        if self._modal_loop is not None and self._modal_loop.isRunning():
            self._modal_loop.quit()
        super().reject()

    def closeEvent(self, event) -> None:
        accepted = False
        if self.main_win is not None and hasattr(self.main_win, "settings"):
            accepted = bool(self.main_win.settings.get("terms_accepted", False))
        if not accepted and not self.chk_accept_terms.isChecked() and os.environ.get("QT_QPA_PLATFORM", "") not in ("offscreen",):
            event.accept()
            self._exit_app_unaccepted()
            return
        self._restore_main_window_chrome()
        if self._modal_loop is not None and self._modal_loop.isRunning():
            self._modal_loop.quit()
        super().closeEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect()

        bg = QLinearGradient(0, 0, r.width(), r.height())
        bg.setColorAt(0.0, QColor(9, 6, 20, 255))
        bg.setColorAt(0.5, QColor(16, 10, 34, 255))
        bg.setColorAt(1.0, QColor(8, 5, 18, 255))
        p.fillRect(r, QBrush(bg))

        g1 = QRadialGradient(r.width() * 0.22, r.height() * 0.18, max(260.0, r.width() * 0.45))
        g1.setColorAt(0.0, QColor(168, 85, 247, 52))
        g1.setColorAt(1.0, QColor(168, 85, 247, 0))
        p.fillRect(r, QBrush(g1))

        g2 = QRadialGradient(r.width() * 0.80, r.height() * 0.82, max(260.0, r.width() * 0.45))
        g2.setColorAt(0.0, QColor(232, 121, 249, 40))
        g2.setColorAt(1.0, QColor(232, 121, 249, 0))
        p.fillRect(r, QBrush(g2))
        p.end()

    def _build_ui(self) -> None:
        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(32, 24, 32, 24)
        root_lay.setSpacing(0)
        root_lay.addStretch(1)

        self.outer_card = QFrame(self)
        self.outer_card.setObjectName("WizardOuterCard")
        self.outer_card.setMinimumWidth(680)
        self.outer_card.setMaximumWidth(880)
        self.outer_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        card_lay = QVBoxLayout(self.outer_card)
        card_lay.setContentsMargins(32, 26, 32, 26)
        card_lay.setSpacing(18)

        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        hdr_row.setSpacing(12)

        brand_pill = QLabel("🌀 CELLIUM STUDIO")
        brand_pill.setStyleSheet(
            "color: #E879F9; font-size: 11px; font-weight: 800; letter-spacing: 1.6px;"
        )
        hdr_row.addWidget(brand_pill)

        self.lbl_step_tag = QLabel("STEP 1 OF 4  •  TERMS & PRIVACY COVENANT")
        self.lbl_step_tag.setStyleSheet(
            "color: #C4B5FD; font-size: 11px; font-weight: 700; letter-spacing: 1.2px;"
        )
        hdr_row.addWidget(self.lbl_step_tag)
        hdr_row.addStretch(1)

        self._step_dots: list[QLabel] = []
        dots_row = QHBoxLayout()
        dots_row.setSpacing(8)
        for _ in range(4):
            dot = QLabel("●")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setFixedSize(18, 18)
            self._step_dots.append(dot)
            dots_row.addWidget(dot)
        hdr_row.addLayout(dots_row)
        card_lay.addLayout(hdr_row)

        self.stack = QStackedWidget(self.outer_card)
        self.stack.addWidget(self._build_step1_terms())
        self.stack.addWidget(self._build_step2_downloads())
        self.stack.addWidget(self._build_step3_keys())
        self.stack.addWidget(self._build_step4_profile())
        card_lay.addWidget(self.stack, stretch=1)

        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(0, 6, 0, 0)
        nav_row.setSpacing(12)

        self.btn_decline = QPushButton("✕ Decline && Exit")
        self.btn_decline.setObjectName("WizardDangerBtn")
        self.btn_decline.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_decline.clicked.connect(self._exit_app_unaccepted)
        nav_row.addWidget(self.btn_decline)

        self.btn_back = QPushButton("◀ Back")
        self.btn_back.setObjectName("WizardSecondaryBtn")
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.clicked.connect(self.go_back)
        nav_row.addWidget(self.btn_back)

        self.btn_skip = QPushButton("Skip this step")
        self.btn_skip.setObjectName("WizardSecondaryBtn")
        self.btn_skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_skip.clicked.connect(self.go_next)
        nav_row.addWidget(self.btn_skip)

        nav_row.addStretch(1)

        self.btn_next = QPushButton("Continue ▶")
        self.btn_next.setObjectName("WizardPrimaryBtn")
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next.clicked.connect(self._on_next_clicked)
        nav_row.addWidget(self.btn_next)

        card_lay.addLayout(nav_row)

        h_center = QHBoxLayout()
        h_center.addStretch(1)
        h_center.addWidget(self.outer_card, stretch=4)
        h_center.addStretch(1)
        root_lay.addLayout(h_center)
        root_lay.addStretch(1)

    def _build_step1_terms(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        title = QLabel("Welcome to Cellium")
        title.setStyleSheet("font-size: 24px; font-weight: 800; color: #FFFFFF;")
        lay.addWidget(title)

        sub = QLabel(
            "Your private, offline-first AI studio, voice companion, and autonomous agent workspace. "
            "Please review and accept the core usage terms below to unlock the studio."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("font-size: 13px; color: #DDD6FE; line-height: 1.45;")
        lay.addWidget(sub)

        pills_row = QHBoxLayout()
        pills_row.setSpacing(10)
        for icon_txt, head_txt, desc_txt in (
            ("🔒", "100% Local Privacy", "Chats, voice profiles, and API keys stay on your device with zero telemetry."),
            ("🛡️", "Guarded Agent Tools", "Shell and file operations require your confirmation on high-risk actions."),
            ("⚡", "Hybrid Cloud + Offline", "Seamlessly switch between local GGUF weights and 12 cloud providers."),
        ):
            pill = QFrame()
            pill.setObjectName("FeaturePillCard")
            p_lay = QVBoxLayout(pill)
            p_lay.setContentsMargins(12, 10, 12, 10)
            p_lay.setSpacing(4)
            lbl_h = QLabel(f"{icon_txt}  {head_txt}")
            lbl_h.setStyleSheet("font-size: 12px; font-weight: 700; color: #F5D0FE;")
            lbl_d = QLabel(desc_txt)
            lbl_d.setWordWrap(True)
            lbl_d.setStyleSheet("font-size: 11px; color: #C4B5FD;")
            p_lay.addWidget(lbl_h)
            p_lay.addWidget(lbl_d)
            pills_row.addWidget(pill, stretch=1)
        lay.addLayout(pills_row)

        terms_card = QFrame()
        terms_card.setObjectName("TermsBoxCard")
        tc_lay = QVBoxLayout(terms_card)
        tc_lay.setContentsMargins(16, 14, 16, 14)
        tc_lay.setSpacing(8)

        terms_scroll = QScrollArea()
        terms_scroll.setWidgetResizable(True)
        terms_scroll.setFrameShape(QFrame.Shape.NoFrame)
        terms_scroll.setMinimumHeight(170)
        terms_scroll.setMaximumHeight(220)
        terms_scroll.setStyleSheet("background: transparent; border: none;")

        terms_body = QLabel(
            "<b>1. Local-First Data Ownership & Zero Telemetry</b><br/>"
            "Cellium stores all conversation histories, custom personas, and API keys locally on your machine. "
            "No analytics or chat logs are ever transmitted to external servers.<br/><br/>"
            "<b>2. Autonomous Agent & Shell Execution Responsibility</b><br/>"
            "When Agent Mode is enabled, Cellium can read/write files and execute terminal commands on your behalf. "
            "While the built-in Command Guard flags destructive operations for your approval, you remain the final "
            "authority over commands executed on your system.<br/><br/>"
            "<b>3. Third-Party Cloud APIs & Local Models</b><br/>"
            "When routing prompts to third-party providers (Google Gemini, Groq, Cerebras, OpenRouter, GitHub Copilot) "
            "or local GGUF models, you agree to abide by the respective model licenses and acceptable use policies.<br/><br/>"
            "<b>4. Warranty Disclaimer</b><br/>"
            "Cellium is provided as-is under the MIT and LGPLv3 open-source ecosystem without warranty of any kind. "
            "Closing this window without accepting these terms will immediately exit the application."
        )
        terms_body.setWordWrap(True)
        terms_body.setTextFormat(Qt.TextFormat.RichText)
        terms_body.setStyleSheet("font-size: 12px; color: #E9D5FF; line-height: 1.5;")
        terms_scroll.setWidget(terms_body)
        tc_lay.addWidget(terms_scroll)
        lay.addWidget(terms_card)

        consent_card = QFrame()
        consent_card.setObjectName("ConsentBannerCard")
        cc_lay = QHBoxLayout(consent_card)
        cc_lay.setContentsMargins(16, 12, 16, 12)
        self.chk_accept_terms = QCheckBox(
            "I have read and agree to the Cellium Terms of Use, Privacy Covenant, and Agent Safety Guidelines"
        )
        self.chk_accept_terms.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_accept_terms.toggled.connect(self._on_terms_toggled)
        cc_lay.addWidget(self.chk_accept_terms)
        lay.addWidget(consent_card)

        return page

    def _build_step2_downloads(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        title = QLabel("Offline Voice & Local AI Downloads (Optional)")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #FFFFFF;")
        lay.addWidget(title)

        sub = QLabel(
            "Want 100% offline voice calls and local AI chat? Click any direct download button below, "
            "or skip this step to use built-in cloud voices and add offline files later."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("font-size: 12px; color: #DDD6FE;")
        lay.addWidget(sub)

        sections = [
            (
                "🔊  Kokoro-82M Offline Neural Voice (TTS)",
                "Ultra-fast local voice synthesis ('kokoro-v1.0.fp16.onnx' + 'voices-v1.0.bin').",
                [
                    ("⬇ kokoro-v1.0.onnx", DIRECT_DOWNLOAD_LINKS["kokoro_onnx"]),
                    ("⬇ voices-v1.0.bin", DIRECT_DOWNLOAD_LINKS["kokoro_voices"]),
                    ("🌐 HuggingFace Repo", DIRECT_DOWNLOAD_LINKS["kokoro_hf"]),
                ],
            ),
            (
                "🎙️  Whisper.cpp Offline Speech Recognition (STT)",
                "Instant local microphone voice-to-text for hands-free Live Mode & Pet Mode.",
                [
                    ("⬇ Faster-Whisper Base.en", DIRECT_DOWNLOAD_LINKS["whisper_fast"]),
                    ("🌐 Whisper.cpp Models", DIRECT_DOWNLOAD_LINKS["whisper_repo"]),
                ],
            ),
            (
                "🧠  Offline Local GGUF Chat Models",
                "Run Qwen3, Llama-3.2, or Gemma-3 completely offline on your own CPU/GPU.",
                [
                    ("🌐 Browse GGUF Models (Bartowski)", DIRECT_DOWNLOAD_LINKS["gguf_bartowski"]),
                ],
            ),
        ]

        for sec_title, sec_desc, links in sections:
            card = QFrame()
            card.setObjectName("WizardSectionCard")
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(16, 12, 16, 12)
            c_lay.setSpacing(6)

            lbl_t = QLabel(sec_title)
            lbl_t.setStyleSheet("font-size: 13px; font-weight: 700; color: #F5D0FE;")
            c_lay.addWidget(lbl_t)

            lbl_d = QLabel(sec_desc)
            lbl_d.setWordWrap(True)
            lbl_d.setStyleSheet("font-size: 11px; color: #C4B5FD;")
            c_lay.addWidget(lbl_d)

            btn_row = QHBoxLayout()
            btn_row.setContentsMargins(0, 4, 0, 0)
            btn_row.setSpacing(8)
            for label_txt, url_str in links:
                btn_dl = QPushButton(label_txt)
                btn_dl.setObjectName("WizardDownloadBtn")
                btn_dl.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_dl.setToolTip(f"Open {url_str}")
                btn_dl.clicked.connect(lambda _=False, u=url_str: QDesktopServices.openUrl(QUrl(u)))
                btn_row.addWidget(btn_dl)

                btn_cp = QPushButton("Copy URL")
                btn_cp.setObjectName("WizardCopyBtn")
                btn_cp.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_cp.clicked.connect(lambda _=False, u=url_str, b=btn_cp: self._copy_url(u, b))
                btn_row.addWidget(btn_cp)

            btn_row.addStretch(1)
            c_lay.addLayout(btn_row)
            lay.addWidget(card)

        lay.addStretch(1)
        return page

    def _build_step3_keys(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        title = QLabel("Connect Cloud AI Providers (Optional)")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #FFFFFF;")
        lay.addWidget(title)

        sub = QLabel(
            "Paste an API key below for instant cloud intelligence, or skip to configure keys later in Model Hub."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("font-size: 12px; color: #DDD6FE;")
        lay.addWidget(sub)

        card = QFrame()
        card.setObjectName("WizardSectionCard")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(18, 16, 18, 16)
        c_lay.setSpacing(12)

        lbl_gem = QLabel("✨ Google Gemini API Key (Free tier supported)")
        lbl_gem.setStyleSheet("font-size: 12px; font-weight: 700; color: #F5D0FE;")
        self.in_gemini_key = QLineEdit()
        self.in_gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.in_gemini_key.setPlaceholderText("AIzaSy...")
        c_lay.addWidget(lbl_gem)
        c_lay.addWidget(self.in_gemini_key)

        lbl_groq = QLabel("🚀 Groq Cloud API Key (Ultra-fast Llama & Whisper STT)")
        lbl_groq.setStyleSheet("font-size: 12px; font-weight: 700; color: #F5D0FE;")
        self.in_groq_key = QLineEdit()
        self.in_groq_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.in_groq_key.setPlaceholderText("gsk_...")
        c_lay.addWidget(lbl_groq)
        c_lay.addWidget(self.in_groq_key)

        lbl_or = QLabel("🌐 OpenRouter / Cerebras API Key")
        lbl_or.setStyleSheet("font-size: 12px; font-weight: 700; color: #F5D0FE;")
        self.in_openrouter_key = QLineEdit()
        self.in_openrouter_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.in_openrouter_key.setPlaceholderText("sk-or-v1-... or csk-...")
        c_lay.addWidget(lbl_or)
        c_lay.addWidget(self.in_openrouter_key)

        lay.addWidget(card)
        lay.addStretch(1)
        return page

    def _build_step4_profile(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        title = QLabel("Personalize Your Companion")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #FFFFFF;")
        lay.addWidget(title)

        sub = QLabel(
            "Tell Cel what name to call you and pick your default dot-matrix avatar style."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("font-size: 12px; color: #DDD6FE;")
        lay.addWidget(sub)

        card = QFrame()
        card.setObjectName("WizardSectionCard")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(18, 18, 18, 18)
        c_lay.setSpacing(14)

        lbl_name = QLabel("👤 Your Display Name")
        lbl_name.setStyleSheet("font-size: 13px; font-weight: 700; color: #F5D0FE;")
        self.in_user_name = QLineEdit()
        self.in_user_name.setPlaceholderText("Enter your name (e.g. Alex)")
        if self.main_win is not None and hasattr(self.main_win, "settings"):
            cur_n = str(self.main_win.settings.get("user_name", "") or "").strip()
            if cur_n and cur_n.lower() not in ("you", "user"):
                self.in_user_name.setText(cur_n)
        c_lay.addWidget(lbl_name)
        c_lay.addWidget(self.in_user_name)

        # ── 🖼️ Your profile picture (circular cutout beside your chat bubbles)
        h_avatar = QHBoxLayout()
        h_avatar.setSpacing(10)
        lbl_avatar = QLabel("📸 Your profile picture")
        lbl_avatar.setStyleSheet("font-size: 12px; font-weight: 700; color: #F5D0FE; border: none;")
        h_avatar.addWidget(lbl_avatar)
        h_avatar.addStretch(1)
        self.btn_avatar_upload = QPushButton("Upload…")
        self.btn_avatar_upload.setFixedWidth(80)
        self.btn_avatar_upload.setStyleSheet(
            "QPushButton { background: rgba(147,51,234,0.35); color:#E9D5FF;"
            " border:1px solid #9333EA; border-radius:7px; padding:5px 12px; font-size:11px; }"
            "QPushButton:hover { background:#9333EA; color:#fff; }")
        self.btn_avatar_upload.clicked.connect(lambda: run_avatar_flow("user", self))
        h_avatar.addWidget(self.btn_avatar_upload)
        self.btn_avatar_remove = QPushButton("Remove")
        self.btn_avatar_remove.setFixedWidth(70)
        self.btn_avatar_remove.setStyleSheet(
            "QPushButton { background: rgba(239,68,68,0.18); color:#FCA5A5;"
            " border:1px solid rgba(248,113,113,0.45); border-radius:7px;"
            " padding:5px 12px; font-size:11px; }"
            "QPushButton:hover { background:#DC2626; color:#fff; }")
        self.btn_avatar_remove.clicked.connect(self._on_avatar_remove)
        h_avatar.addWidget(self.btn_avatar_remove)
        c_lay.addLayout(h_avatar)

        lbl_style = QLabel("🎭 Default Avatar Style")
        lbl_style.setStyleSheet("font-size: 13px; font-weight: 700; color: #F5D0FE;")
        self.combo_style = QComboBox()
        for style_name in ("Female", "Male", "Detailed Female", "Detailed Male", "Chibi"):
            self.combo_style.addItem(style_name, style_name)
        c_lay.addWidget(lbl_style)
        c_lay.addWidget(self.combo_style)

        lay.addWidget(card)
        lay.addStretch(1)
        return page

    def _copy_url(self, url_str: str, btn: QPushButton) -> None:
        QApplication.clipboard().setText(url_str)
        btn.setText("✓ Copied")
        QTimer.singleShot(1400, lambda: btn.setText("Copy URL"))

    def _on_terms_toggled(self, checked: bool) -> None:
        if self.main_win is not None and hasattr(self.main_win, "settings"):
            self.main_win.settings["terms_accepted"] = bool(checked)
        self._sync_nav_state()

    def _sync_nav_state(self) -> None:
        idx = self.stack.currentIndex()
        terms_ok = self.chk_accept_terms.isChecked()

        step_titles = (
            "STEP 1 OF 4  •  TERMS & PRIVACY COVENANT",
            "STEP 2 OF 4  •  OFFLINE VOICE & AI DOWNLOADS",
            "STEP 3 OF 4  •  CLOUD API KEYS",
            "STEP 4 OF 4  •  YOUR DISPLAY NAME & AVATAR",
        )
        self.lbl_step_tag.setText(step_titles[min(idx, 3)])

        for i, dot in enumerate(self._step_dots):
            if i <= idx:
                dot.setStyleSheet("color: #E879F9; font-size: 14px; border: none; background: transparent;")
            else:
                dot.setStyleSheet("color: rgba(168, 85, 247, 0.30); font-size: 14px; border: none; background: transparent;")

        self.btn_back.setVisible(idx > 0)
        self.btn_decline.setVisible(idx == 0)

        if idx == 0:
            self.btn_next.setEnabled(terms_ok)
            self.btn_skip.setEnabled(terms_ok)
            self.btn_skip.setText("Skip Setup")
            self.btn_next.setText("Accept & Continue ▶")
        elif idx < 3:
            self.btn_next.setEnabled(True)
            self.btn_skip.setEnabled(True)
            self.btn_skip.setText("Skip this step")
            self.btn_next.setText("Continue ▶")
        else:
            self.btn_next.setEnabled(True)
            self.btn_skip.setEnabled(True)
            self.btn_skip.setText("Skip")
            self.btn_next.setText("✨ Launch Cellium")

    def _on_next_clicked(self) -> None:
        if self.stack.currentIndex() < self.stack.count() - 1:
            self.go_next()
        else:
            self.finish_onboarding()

    def go_next(self) -> None:
        if self.stack.currentIndex() == 0 and not self.chk_accept_terms.isChecked():
            return
        nxt = min(self.stack.count() - 1, self.stack.currentIndex() + 1)
        self.stack.setCurrentIndex(nxt)
        self._sync_nav_state()

    def go_back(self) -> None:
        prv = max(0, self.stack.currentIndex() - 1)
        self.stack.setCurrentIndex(prv)
        self._sync_nav_state()

    def finish_onboarding(self) -> None:
        if self.main_win is not None and hasattr(self.main_win, "settings"):
            s = self.main_win.settings
            s["terms_accepted"] = True
            s["onboarding_completed"] = True
            name_val = (self.in_user_name.text() or "").strip()
            if name_val:
                s["user_name"] = name_val
            chosen_style = (self.combo_style.currentText() or "Female").strip()
            s["companion_gender"] = chosen_style

            keys = s.setdefault("user_custom_keys", {})
            if (self.in_gemini_key.text() or "").strip():
                keys["Google Gemini"] = self.in_gemini_key.text().strip()
            if (self.in_groq_key.text() or "").strip():
                keys["Groq"] = self.in_groq_key.text().strip()
            if (self.in_openrouter_key.text() or "").strip():
                raw_k = self.in_openrouter_key.text().strip()
                if raw_k.startswith("csk-"):
                    keys["Cerebras"] = raw_k
                else:
                    keys["OpenRouter"] = raw_k

            if hasattr(self.main_win, "save_settings"):
                try:
                    self.main_win.save_settings()
                except Exception:
                    pass

        self._restore_main_window_chrome()
        if self._modal_loop is not None and self._modal_loop.isRunning():
            self._modal_loop.quit()
        self.completed.emit()
        self.hide()
        self.accept()

    def _on_avatar_remove(self):
        """Remove the user avatar chosen during onboarding."""
        try:
            clear_avatar("user")
        except Exception:
            pass
        try:
            bust_avatar_cache()
        except Exception:
            pass
