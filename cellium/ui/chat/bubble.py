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
from PySide6.QtWidgets import QTextEdit

# ============================================================
# GLOBAL REAL-TIME LOGGING SYSTEM - Immediate stdout/stderr flush
# ============================================================
_original_print = print

# --- CROSS IMPORTS ---
from cellium.ui.chat.glass import *
from cellium.ui.widgets.pfp import CircularAvatarLabel, run_avatar_flow
from cellium.core.logger import *
from cellium.core.config import *
from cellium.core.utils import *
from cellium.core.tools import *
from cellium.services.sound_engine import *
from cellium.services.ai_llama import *
from cellium.services.audio_stt import *
from cellium.services.audio_tts import *
from cellium.services.ai_workers import *


# ── profile-picture helpers ────────────────────────────────────────────────
def _bubble_avatar_initial(is_user: bool, app=None) -> str:
    """Fallback initial for a bubble header when no picture is on disk."""
    if not is_user:
        return "C"
    if app is not None:
        try:
            n = str(getattr(app, "settings", {}).get("user_name", "") or "").strip()
            if n and n.lower() not in ("you", "user"):
                return n[0]
        except Exception:
            pass
    return "Y"


def _resolve_user_name(app=None) -> str:
    """Resolve the user's custom name from settings or config file."""
    if app is not None and hasattr(app, "settings"):
        n = str(getattr(app, "settings", {}).get("user_name", "") or "").strip()
        if n:
            return n
    try:
        from cellium.core.utils import F_SETTINGS, load_json
        from cellium.core.config import DEFAULT_SETTINGS
        s = load_json(F_SETTINGS, DEFAULT_SETTINGS)
        n = str(s.get("user_name", "") or "").strip()
        if n:
            return n
    except Exception:
        pass
    return "You"


def _refresh_avatar_labels(widget) -> None:
    """Refresh every circular avatar under ``widget`` (a chat host or bubble)."""
    if widget is None:
        return
    try:
        for lbl in widget.findChildren(CircularAvatarLabel):
            lbl.refresh()
    except Exception:
        pass


class MessageBubble(QWidget):
    def __init__(self, role, content, meta=None, glass_opacity=0.72, accent_color="#C084FC",
                 attached_images=None, attached_files=None, is_ghost=False, parent=None):
        super().__init__(parent)
        self.role = role
        self.content = content
        self.meta = meta or {}
        self.glass_opacity = glass_opacity
        self.accent_color = accent_color
        self.attached_images = attached_images or []
        self.attached_files = attached_files or []
        self.is_ghost = is_ghost
        self.body_label = None
        self.info_card = None
        self.info_expanded = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setMinimumWidth(200)
        self.setMaximumWidth(820)
        self.init_ui()

    def update_stream_text(self, text):
        self.content = text
        if self.body_label:
            self.body_label.setText(text)
        self.updateGeometry()
        self.adjustSize()
        if self.width() > 0:
            self.setFixedHeight(self.heightForWidth(self.width()))
        self.update()

    def init_ui(self):
        is_user = (self.role == "user")
        self.layout_v = QVBoxLayout(self)
        self.layout_v.setContentsMargins(14, 10, 14, 10)
        self.layout_v.setSpacing(6)

        hdr_layout = QHBoxLayout()
        hdr_layout.setContentsMargins(0, 0, 0, 0)
        hdr_layout.setSpacing(8)

        user_name = _resolve_user_name(getattr(self, "chat_app", None))
        name = user_name if is_user else "Cel"
        self.name_lbl = QLabel(name)
        name_lbl = self.name_lbl
        name_lbl.setStyleSheet("font-weight: bold; font-size: 11px; color: #A8C7FA; border: none; background: transparent;")

        # Circular profile picture: yours on your bubbles, Cel's on hers. With
        # no picture on disk it degrades to a gradient disc + initial.
        self.avatar_lbl = CircularAvatarLabel(
            who="user" if is_user else "cel", diameter=26,
            fallback_text=_bubble_avatar_initial(is_user, getattr(self, "chat_app", None)))
        self.avatar_lbl.clicked.connect(self._on_avatar_clicked)
        hdr_layout.addWidget(self.avatar_lbl)

        time_str = self.meta.get("time", datetime.now().strftime("%H:%M"))
        time_lbl = QLabel(time_str)
        time_lbl.setStyleSheet("font-size: 10px; color: #7C6F98; border: none; background: transparent;")

        hdr_layout.addWidget(name_lbl)
        hdr_layout.addWidget(time_lbl)

        if self.is_ghost:
            ghost_badge = QLabel("🛑 [Stopped - Temporary preview]")
            ghost_badge.setStyleSheet("font-size: 10px; font-weight: bold; color: #F87171; border: none;")
            hdr_layout.addWidget(ghost_badge)

        if not is_user:
            self.btn_info = QPushButton("✦ Info")
            self.btn_info.setToolTip("✨ View token statistics, generation speed & model capabilities")
            self.btn_info.setStyleSheet("""
                QPushButton {
                    background: rgba(138, 43, 226, 0.25);
                    border: 1px solid rgba(192, 132, 252, 0.35);
                    border-radius: 5px;
                    padding: 1px 8px;
                    font-size: 10px;
                    font-weight: bold;
                    color: #E3E3E3;
                }
                QPushButton:hover {
                    background: rgba(138, 43, 226, 0.55);
                    color: #FFFFFF;
                }
            """)
            self.btn_info.clicked.connect(self.toggle_info_card)
            hdr_layout.addWidget(self.btn_info)

            # Copy Bubble Text button
            btn_copy = QPushButton(); btn_copy.setIcon(QIcon(str(ASSETS_DIR / "gemini_copy.svg"))); btn_copy.setIconSize(QSize(16, 16))
            btn_copy.setFixedSize(24, 22)
            btn_copy.setToolTip("📋 Copy message to clipboard")
            btn_copy.setStyleSheet("background: transparent; color: #A78BFA; border: none; font-size: 12px;")
            btn_copy.clicked.connect(lambda: (
                QApplication.clipboard().setText(self.content),
                self.chat_app.show_toast("Copied to clipboard! 📋", icon="📋") if self.chat_app else None
            ))
            hdr_layout.addWidget(btn_copy)

        hdr_layout.addStretch()
        self.layout_v.addLayout(hdr_layout)

        if self.attached_images:
            for img_path in self.attached_images:
                if os.path.exists(img_path):
                    pix = QPixmap(img_path)
                    if not pix.isNull():
                        img_lbl = QLabel()
                        scaled = pix.scaledToWidth(min(380, pix.width()), Qt.TransformationMode.SmoothTransformation)
                        img_lbl.setPixmap(scaled)
                        img_lbl.setStyleSheet("border-radius: 10px; border: 1px solid rgba(255,255,255,0.1);")
                        self.layout_v.addWidget(img_lbl)

        if self.attached_files:
            for f_info in self.attached_files:
                f_card = QFrame()
                f_card.setStyleSheet("background: rgba(0,0,0,0.35); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px;")
                f_h = QHBoxLayout(f_card)
                f_h.setContentsMargins(8, 6, 8, 6)
                f_lbl = QLabel(f"📄 {f_info.get('name', 'File')} ({f_info.get('size_str', '')})")
                f_lbl.setStyleSheet("font-size: 11px; color: #81C784; font-weight: bold; border: none;")
                f_h.addWidget(f_lbl)
                self.layout_v.addWidget(f_card)

        display_text = self.content
        if is_user and display_text.startswith("Name - "):
            display_text = display_text.split("Prompt - ", 1)[-1]

        if not is_user and not display_text:
            self.body_label = QLabel("Cel is thinking... 💭✨")
            self.body_label.setWordWrap(True)
            self.body_label.setWordWrap(True)
            self.body_label.setStyleSheet("color: #C084FC; font-size: 14px; font-style: italic; border: none; background: transparent;")
            self.layout_v.addWidget(self.body_label)
        else:
            self._render_markdown(display_text)

        self.adjustSize()
        self.updateGeometry()

    def refresh_avatar(self) -> None:
        """Re-read this bubble's profile picture from disk."""
        if getattr(self, "avatar_lbl", None) is not None:
            self.avatar_lbl.refresh()

    def _on_avatar_clicked(self) -> None:
        """Click the cutout in the header → crop/zoom a new picture."""
        who = "user" if getattr(self, "role", "") == "user" else "cel"

        def _after() -> None:
            self.refresh_avatar()
            _refresh_avatar_labels(getattr(self, "chat_app", None))

        try:
            run_avatar_flow(who, self, _after)
        except Exception:
            pass

    def _render_markdown(self, text: str):
        """Render markdown text with full support for code blocks, tables, etc.

        Uses the shared `format_cel_markdown` pipeline (mistune with Qt and
        escaped-<pre> fallbacks plus theme injection). This method previously
        ran its own weaker regex converter, which is why headings, tables,
        task lists and emphasis never rendered in message bodies.
        """
        from cellium.core.utils import format_cel_markdown
        html_content = format_cel_markdown(text)
        # Split by our custom code block markers to handle them as interactive widgets
        self._render_html_with_code_blocks(html_content)

    def _markdown_to_html(self, text: str) -> str:
        """Convert markdown to HTML (lightweight, no external deps)."""
        import re
        
        # First, extract and protect code blocks
        code_blocks = []
        def protect_code(match):
            lang = match.group(1).strip() if match.group(1) else ""
            code = match.group(2).rstrip()
            code_blocks.append((lang, code))
            return f"{{{{CODE_BLOCK_{len(code_blocks)-1}}}}}"
        
        # Protect fenced code blocks
        text = re.sub(r'```(\w*)\n(.*?)\n```', protect_code, text, flags=re.DOTALL)
        
        # Protect inline code
        inline_codes = []
        def protect_inline(match):
            inline_codes.append(match.group(1))
            return f"{{{{INLINE_CODE_{len(inline_codes)-1}}}}}"
        text = re.sub(r'`([^`\n]+)`', protect_inline, text)
        
        # Headers
        text = re.sub(r'^#{1,6}\s+(.+)$', lambda m: f'<h{len(m.group(0))-len(m.group(1))}>{self._escape_html(m.group(1))}</h{len(m.group(0))-len(m.group(1))}>', text, flags=re.MULTILINE)
        
        # Bold and italic
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
        text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
        text = re.sub(r'_(.+?)_', r'<i>\1</i>', text)
        
        # Strikethrough
        text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
        
        # Links
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" style="color:#C084FC;">\1</a>', text)
        
        # Images
        text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1" style="max-width:100%;height:auto;border-radius:8px;">', text)
        
        # Blockquotes
        text = re.sub(r'^>\s*(.+)$', r'<blockquote style="border-left:3px solid #9333EA;padding-left:12px;margin:8px 0;color:#A78BFA;font-style:italic;">\1</blockquote>', text, flags=re.MULTILINE)
        
        # Horizontal rule
        text = re.sub(r'^---+\s*$', '<hr style="border:none;border-top:1px solid #9333EA;margin:16px 0;">', text, flags=re.MULTILINE)
        
        # Unordered lists
        text = re.sub(r'^\s*[-*+]\s+(.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
        text = re.sub(r'(<li>.*</li>\n?)+', r'<ul style="margin:8px 0;padding-left:24px;">\g<0></ul>', text)
        
        # Ordered lists
        text = re.sub(r'^\s*\d+\.\s+(.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
        text = re.sub(r'(<li>.*</li>\n?)+', r'<ol style="margin:8px 0;padding-left:24px;">\g<0></ol>', text)
        
        # Tables
        text = self._convert_tables(text)
        
        # Paragraphs (split by double newline)
        paragraphs = text.split('\n\n')
        html_paragraphs = []
        for p in paragraphs:
            p = p.strip()
            if p and not p.startswith('<'):
                # Check if it's a list item or already handled
                if not (p.startswith('<li>') or p.startswith('<ul') or p.startswith('<ol') or p.startswith('<h') or p.startswith('<blockquote') or p.startswith('<hr') or p.startswith('<table')):
                    p = f'<p style="margin:8px 0;line-height:1.6;">{p}</p>'
            html_paragraphs.append(p)
        text = '\n\n'.join(html_paragraphs)
        
        # Restore inline code
        for i, code in enumerate(inline_codes):
            text = text.replace(f'{{{{INLINE_CODE_{i}}}}}', f'<code style="background:rgba(10,8,18,0.9);color:#4ADE80;padding:2px 6px;border-radius:4px;font-family:Consolas,monospace;">{self._escape_html(code)}</code>')
        
        # Restore code blocks
        for i, (lang, code) in enumerate(code_blocks):
            lang_class = f' class="language-{lang}"' if lang else ''
            text = text.replace(f'{{{{CODE_BLOCK_{i}}}}}', f'<pre{lang_class} style="background:rgba(10,8,18,0.95);border:1.5px solid #9333EA;border-radius:10px;padding:12px;overflow:auto;margin:12px 0;"><code>{self._escape_html(code)}</code></pre>')
        
        # Replace newlines with <br> for non-block elements
        text = text.replace('\n', '<br>')
        
        return text

    def _convert_tables(self, text: str) -> str:
        """Convert markdown tables to HTML tables."""
        import re
        lines = text.split('\n')
        in_table = False
        table_lines = []
        result = []
        
        for line in lines:
            if '|' in line and line.strip().startswith('|') and line.strip().endswith('|'):
                in_table = True
                table_lines.append(line)
            else:
                if in_table:
                    # Process collected table lines
                    result.append(self._table_to_html(table_lines))
                    table_lines = []
                    in_table = False
                result.append(line)
        
        if in_table:
            result.append(self._table_to_html(table_lines))
        
        return '\n'.join(result)

    def _table_to_html(self, lines: list) -> str:
        """Convert table lines to HTML table."""
        import re
        if len(lines) < 2:
            return '\n'.join(lines)
        
        # Parse header
        header_cells = [c.strip() for c in lines[0].strip('|').split('|')]
        # Parse separator (skip)
        # Parse data rows
        data_rows = []
        for line in lines[2:]:
            cells = [c.strip() for c in line.strip('|').split('|')]
            if len(cells) == len(header_cells):
                data_rows.append(cells)
        
        html = ['<table style="width:100%;border-collapse:collapse;margin:12px 0;font-size:13px;">']
        html.append('<thead><tr>')
        for cell in header_cells:
            html.append(f'<th style="border:1px solid #9333EA;padding:8px 12px;background:rgba(147,51,234,0.2);color:#F8F4FF;font-weight:600;">{self._escape_html(cell)}</th>')
        html.append('</tr></thead>')
        html.append('<tbody>')
        for row in data_rows:
            html.append('<tr>')
            for cell in row:
                html.append(f'<td style="border:1px solid #9333EA;padding:8px 12px;color:#E3E3E3;">{self._escape_html(cell)}</td>')
            html.append('</tr>')
        html.append('</tbody></table>')
        return ''.join(html)
    def _escape_html(self, text: str) -> str:
        """Escape text for safe insertion into the bubble's rich text.

        This was previously a chain of no-op replaces whose last two calls had a
        single argument, so it raised TypeError on *every* invocation and broke
        markdown rendering for any message containing a heading, table cell,
        inline-code span, or fenced code block.

        ``html.escape`` handles & < > " ' correctly and in the right order
        (& first, so entities are not double-escaped).
        """
        import html as _html
        return _html.escape("" if text is None else str(text), quote=True)
    def _render_html_with_code_blocks(self, html: str):
        """Render HTML, but extract <pre><code> blocks as interactive widgets."""
        import re
        # Find all <pre><code>...</code></pre> blocks
        # mistune emits <pre><code class="language-x">, so the <code> tag must be
        # allowed to carry attributes here or no block is ever split out.
        parts = re.split(r'(<pre[^>]*><code[^>]*>.*?</code></pre>)', html, flags=re.DOTALL)
        
        for idx, part in enumerate(parts):
            if not part:
                continue
            if part.startswith('<pre'):
                # Extract language and code
                lang_match = re.search(r'class="language-(\w+)"', part)
                lang = lang_match.group(1) if lang_match else ""
                code_match = re.search(r'<code[^>]*>(.*?)</code>', part, re.DOTALL)
                raw_code = code_match.group(1) if code_match else ""
                import html as _html_mod
                code = _html_mod.unescape(raw_code)
                
                # Create interactive code card
                card = QFrame()
                card.setStyleSheet("""
                    QFrame {
                        background: rgba(10, 8, 18, 0.95);
                        border: 1.5px solid #9333EA;
                        border-radius: 10px;
                    }
                """)
                card_v = QVBoxLayout(card)
                card_v.setContentsMargins(10, 8, 10, 8)
                card_v.setSpacing(4)

                c_hdr = QHBoxLayout()
                c_lbl = QLabel(f"⚡ {lang.upper()}" if lang else "🗃️ Text Block")
                c_lbl.setStyleSheet("color: #C084FC; font-weight: bold; font-size: 11px; border: none;")
                c_btn_copy = QPushButton("📋 Copy")
                c_btn_copy.setStyleSheet("padding: 2px 8px; font-size: 10px; background: rgba(255,255,255,0.08); border-radius: 4px; color: white; border: none;")
                c_btn_copy.clicked.connect(lambda _, b=code: (
                    QApplication.clipboard().setText(b),
                    self.chat_app.show_toast("Copied to clipboard! 📋", icon="📋") if self.chat_app else None
                ))
                c_hdr.addWidget(c_lbl)
                c_hdr.addStretch()
                c_hdr.addWidget(c_btn_copy)
                card_v.addLayout(c_hdr)

                code_edit = QTextEdit()
                code_edit.setPlainText(code)
                code_edit.setReadOnly(True)
                code_edit.setFont(QFont("Consolas", 10))
                code_edit.setStyleSheet("background: transparent; border: none; color: #4ADE80;")
                lines_count = code.count("\n") + 1
                code_edit.setFixedHeight(min(400, max(55, lines_count * 19 + 22)))
                card_v.addWidget(code_edit)
                self.layout_v.addWidget(card)
            else:
                # Regular HTML content - render as rich text
                if part.strip():
                    lbl = QLabel()
                    lbl.setTextFormat(Qt.TextFormat.RichText)
                    lbl.setText(part)
                    lbl.setWordWrap(True)
                    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse)
                    lbl.setOpenExternalLinks(True)
                    lbl.setStyleSheet("color: #F8F4FF; font-size: 14px; line-height: 1.5; border: none; background: transparent;")
                    self.layout_v.addWidget(lbl)
                    if self.body_label is None:
                        self.body_label = lbl

    def toggle_info_card(self):
        if not self.info_card:
            self.info_card = QFrame()
            self.info_card.setStyleSheet("""
                QFrame {
                    background: rgba(14, 10, 24, 0.95);
                    border: 1.5px solid #9333EA;
                    border-radius: 8px;
                }
                QLabel { color: #E9D5FF; font-size: 11px; border: none; background: transparent; }
            """)
            inf_v = QVBoxLayout(self.info_card)
            inf_v.setContentsMargins(12, 10, 12, 10)
            inf_v.setSpacing(5)

            model_name = self.meta.get("model") or "Cerebras Fast Cloud"
            # Clean up every offline label shape (icon, size, .gguf).
            if is_offline_model_key(model_name):
                model_name = strip_offline_label(model_name)
            turn_tokens = self.meta.get("turn_tokens", 0)
            think_time = self.meta.get("think_time", 0.0)
            speed = f"{turn_tokens / max(0.01, think_time):.1f}" if think_time else " - "

            for lbl_text in [
                f"🏷️ Model: <b>{model_name}</b>",
                f"🍪 Tokens: <b>{turn_tokens:,}</b> tokens",
                f"⏱️ Think Time: <b>{think_time}s</b>",
                f"⚡ Speed: <b>{speed} tok/s</b>",
                f"🕒 Timestamp: <b>{self.meta.get('time', datetime.now().strftime('%H:%M:%S'))}</b>"
            ]:
                lbl = QLabel(lbl_text)
                lbl.setTextFormat(Qt.TextFormat.RichText)
                inf_v.addWidget(lbl)

            # Words & Letters count
            words = len(self.content.split())
            letters = len(self.content)
            lbl_wl = QLabel(f"📝 Words: <b>{words:,}</b>  •  Letters: <b>{letters:,}</b>")
            lbl_wl.setTextFormat(Qt.TextFormat.RichText)
            inf_v.addWidget(lbl_wl)

            self.layout_v.addWidget(self.info_card)
            self.info_card.setVisible(True)
            self.info_expanded = True
            self.btn_info.setText("🔼 Info")
        else:
            self.info_expanded = not self.info_expanded
            self.info_card.setVisible(self.info_expanded)
            self.btn_info.setText("▲ Info" if self.info_expanded else "✦ Info")
        exact_h = self.heightForWidth(self.width())
        self.setFixedHeight(exact_h)
        self.updateGeometry()

        self.updateGeometry()
        self.adjustSize()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = 16.0
        rect = QRectF(1.5, 1.5, w - 3.0, h - 3.0)
        path = QPainterPath()

        if self.role == "user":
            path.moveTo(rect.left() + r, rect.top())
            path.lineTo(rect.right() - r, rect.top())
            path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
            path.lineTo(rect.right(), rect.bottom() - 4.0)
            path.quadTo(rect.right(), rect.bottom(), rect.right() - 4.0, rect.bottom())
            path.lineTo(rect.left() + r, rect.bottom())
            path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - r)
            path.lineTo(rect.left(), rect.top() + r)
            path.quadTo(rect.left(), rect.top(), rect.left() + r, rect.top())

            bg = QColor(28, 20, 50, int(self.glass_opacity * 255))
            border = QColor(192, 132, 252, 90)
        else:
            path.moveTo(rect.left() + 4.0, rect.top())
            path.lineTo(rect.right() - r, rect.top())
            path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
            path.lineTo(rect.right(), rect.bottom() - r)
            path.quadTo(rect.right(), rect.bottom(), rect.right() - r, rect.bottom())
            path.lineTo(rect.left() + r, rect.bottom())
            path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - r)
            path.lineTo(rect.left(), rect.top() + 4.0)
            path.quadTo(rect.left(), rect.top(), rect.left() + 4.0, rect.top())

            if self.is_ghost:
                bg = QColor(36, 16, 22, 225)
                border = QColor(239, 68, 68, 180)
            else:
                bg = QColor(14, 10, 24, int(min(0.94, self.glass_opacity + 0.14) * 255))
                border = QColor(147, 51, 234, 110)

        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(border, 1.4))
        painter.drawPath(path)
        painter.end()
 
# ------------------------------------------------------------------ STT Choice Comparison Card
class STTChoiceCard(GlassPanel):
    text_chosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(radius=16, parent=parent)
        self.setFixedHeight(145)
        self.setVisible(False)
        self.layout_v = QVBoxLayout(self)
        self.layout_v.setContentsMargins(14, 8, 14, 8)
        self.layout_v.setSpacing(6)

        hdr = QHBoxLayout()
        title = QLabel("🎙️ Multi-Engine STT Results (Select best to insert):")
        title.setStyleSheet("font-weight: bold; font-size: 12px; color: #C084FC; border: none;")
        hdr.addWidget(title)
        hdr.addStretch()

        btn_x = QPushButton(); btn_x.setIcon(QIcon(str(ASSETS_DIR / "gemini_close.svg"))); btn_x.setIconSize(QSize(16, 16))
        btn_x.setFixedSize(20, 20)
        btn_x.setStyleSheet("background: transparent; color: #C084FC; border: none; font-weight: bold;")
        btn_x.clicked.connect(lambda: self.setVisible(False))
        hdr.addWidget(btn_x)
        self.layout_v.addLayout(hdr)

        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_scroll.setStyleSheet("background: transparent; border: none;")

        self.cards_content = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_content)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(4)
        self.cards_scroll.setWidget(self.cards_content)
        self.layout_v.addWidget(self.cards_scroll)

    def show_results(self, results_dict):
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for eng_name, trans_text in results_dict.items():
            row = QFrame()
            row.setStyleSheet("background: rgba(255,255,255,0.04); border-radius: 8px; padding: 4px;")
            r_h = QHBoxLayout(row)
            r_h.setContentsMargins(8, 4, 8, 4)
            r_h.setSpacing(10)

            eng_lbl = QLabel(f"<b>{eng_name}:</b>")
            eng_lbl.setStyleSheet("font-size: 11px; color: #E9D5FF; border: none;")
            txt_lbl = QLabel(trans_text)
            txt_lbl.setStyleSheet("font-size: 12px; color: #F8F4FF; border: none;")
            txt_lbl.setWordWrap(True)

            btn_use = QPushButton("Use / Edit")
            btn_use.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8A2BE2, stop:1 #A855F7);
                    color: white; border-radius: 6px; padding: 4px 10px; font-weight: bold; font-size: 11px; border: none;
                }
                QPushButton:hover { background: #C084FC; }
            """)
            btn_use.clicked.connect(lambda _, t=trans_text: self.choose_text(t))

            r_h.addWidget(eng_lbl)
            r_h.addWidget(txt_lbl, stretch=1)
            r_h.addWidget(btn_use)
            self.cards_layout.addWidget(row)

        self.setVisible(True)

    def choose_text(self, text):
        self.setVisible(False)
        self.text_chosen.emit(text)

# ------------------------------------------------------------------ Emoji & Kaomoji Picker Dock
class ChatBubbleBody(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.setOpenExternalLinks(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.font_size = self._resolve_initial_font_px(parent)
        self._target_w = 0
        bubble_font = QFont("Segoe UI", max(9, int(self.font_size * 0.8)))
        self.setFont(bubble_font)
        self.setStyleSheet(
            f"color: #F8F4FF; font-size: {self.font_size}px; line-height: 1.5; border: none; background: transparent;"
        )
        self._doc = QTextDocument(self)
        self._doc.setDocumentMargin(0)
        self._doc.setDefaultFont(bubble_font)
        self.raw_html = text
        if text:
            self.setHtmlText(text)

    @staticmethod
    def _resolve_initial_font_px(parent) -> int:
        """Bug #17: Inherit active window zoom & font_scale immediately at construction."""
        p = parent
        while p is not None:
            chat_app = getattr(p, "chat_app", None)
            win = chat_app if chat_app is not None else (p if hasattr(p, "BUBBLE_BASE_FONT_PX") else None)
            if win is not None and hasattr(win, "BUBBLE_BASE_FONT_PX"):
                try:
                    z = float(getattr(win, "zoom_level", 1.0) or 1.0)
                    fs = float(win.font_scale_factor()) if hasattr(win, "font_scale_factor") else 1.0
                    return max(9, int(round(win.BUBBLE_BASE_FONT_PX * z * fs)))
                except Exception:
                    break
            p = p.parentWidget() if hasattr(p, "parentWidget") else None
        return 14

    def set_font_scale(self, font_size: int):
        self.font_size = font_size
        self.setFont(QFont("Segoe UI", max(9, int(font_size * 0.8))))
        self.setStyleSheet(f"color: #F8F4FF; font-size: {font_size}px; line-height: 1.5; border: none; background: transparent;")
        if hasattr(self, "raw_html") and self.raw_html:
            self.setHtmlText(self.raw_html)

    def setHtmlText(self, html_content: str):
        self.raw_html = html_content
        bubble_font = self.font()
        self._doc.setDefaultFont(bubble_font)
        scaled_html = self._scale_inline_px(html_content, self.font_size)
        styled_html = f"<div style=\"font-family: 'Segoe UI', system-ui, sans-serif; font-size: {self.font_size}px; line-height: 1.48; color: #F8F4FF;\">{scaled_html}</div>"
        self._doc.setHtml(styled_html)
        self.setText(styled_html)
        self.updateGeometry()

    @staticmethod
    def _scale_inline_px(html_str: str, body_px: int) -> str:
        """Scale inline markdown tag font-sizes (h1-h6, code, table) proportionally with body_px."""
        if not html_str or body_px == 14:
            return html_str
        ratio = body_px / 14.0
        return re.sub(
            r"font-size:\s*(\d+(?:\.\d+)?)px",
            lambda m: f"font-size: {max(9, int(round(float(m.group(1)) * ratio)))}px",
            html_str,
        )

    def get_ideal_width(self) -> int:
        prev_w = self._doc.textWidth()
        self._doc.setTextWidth(-1)
        ideal = int(math.ceil(self._doc.idealWidth()))
        if prev_w > 0:
            self._doc.setTextWidth(prev_w)
        return ideal

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        eff_w = width if width > 0 else (self._target_w if self._target_w > 0 else 560)
        self._doc.setDefaultFont(self.font())
        self._doc.setTextWidth(eff_w)
        doc_h = int(math.ceil(self._doc.size().height()))
        try:
            native_h = super().heightForWidth(eff_w)
        except Exception:
            native_h = 0
        base = max(doc_h, native_h, 0)
        return base + 10

    def sizeHint(self) -> QSize:
        eff_w = self._target_w if getattr(self, "_target_w", 0) > 0 else (
            self.width() if self.width() > 160 else max(240, self.get_ideal_width())
        )
        h = self.heightForWidth(eff_w)
        return QSize(eff_w, h)

class _StatusBubbleLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._bubble = parent

    def setText(self, text):
        super().setText(text)
        if hasattr(self, "_bubble") and self._bubble is not None:
            self._bubble._text = str(text or "")
            if hasattr(self._bubble, "update_dynamic_width"):
                self._bubble.update_dynamic_width(getattr(self._bubble, "_last_max_w", 600))

    def setStyleSheet(self, ss):
        super().setStyleSheet(ss)
        if hasattr(self, "_bubble") and self._bubble is not None:
            m = re.search(r"color:\s*([^;]+)", ss)
            if m:
                self._bubble._color = m.group(1).strip()
            if hasattr(self._bubble, "update_dynamic_width"):
                self._bubble.update_dynamic_width(getattr(self._bubble, "_last_max_w", 600))


class ChatStatusBubble(GlassPanel):
    """
    A sleek, bulletproof glass status bubble for in-chat progress/notifications.
    Subclasses GlassPanel for native hardware-accelerated frost and neon border.
    Guarantees ZERO text clipping for any string, any length, and any wrap state.
    Single-line text stays strictly on 1 line with generous padding.
    Multi-line text dynamically wraps with calculated height that never clips descenders.
    """
    def __init__(self, text: str = "🎨 …", color: str = "#C084FC", parent=None):
        super().__init__(radius=14, panel_opacity=0.92, parent=parent)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 9, 16, 9)
        self.lay.setSpacing(0)

        self.font_size = 13
        self._text = str(text or "")
        self._color = color
        self._last_max_w = 600

        self.lbl = QLabel(text, self)
        self.lbl.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl.setStyleSheet(
            f"color: {color}; font-size: {self.font_size}px; font-weight: 500; border: none; background: transparent; padding: 0px;"
        )
        self.lay.addWidget(self.lbl)
        self._kaggle_lbl = self.lbl
        self.update_dynamic_width(600)

    def set_font_scale(self, font_size: int):
        self.font_size = max(9, font_size)
        self.lbl.setStyleSheet(
            f"color: {self._color}; font-size: {self.font_size}px; font-weight: 500; border: none; background: transparent; padding: 0px;"
        )
        self.update_dynamic_width(getattr(self, "_last_max_w", 600))

    def set_status(self, text: str, color: str = "#C084FC", max_available_w: int = 600):
        self._text = str(text or "")
        self._color = color
        self.lbl.setText(self._text)
        self.lbl.setStyleSheet(
            f"color: {color}; font-size: {self.font_size}px; font-weight: 500; border: none; background: transparent; padding: 0px;"
        )
        self.update_dynamic_width(max_available_w)

    def update_dynamic_width(self, max_available_w: int):
        self._last_max_w = max_available_w
        doc = QTextDocument()
        font = self.lbl.font()
        font.setPixelSize(self.font_size)
        font.setWeight(QFont.Weight.Medium)
        doc.setDefaultFont(font)
        doc.setPlainText(self._text)
        doc.setTextWidth(-1)
        raw_w = int(math.ceil(doc.idealWidth()))

        effective_max = max(200, min(max_available_w, 680))
        # Generous horizontal padding (16 left + 16 right = 32px + 16px safety for color emojis and antialiasing = 48px)
        needed_w = raw_w + 48

        if needed_w <= effective_max:
            # Single line: strictly avoid wrapping
            self.lbl.setWordWrap(False)
            target_w = max(90, needed_w)
            target_h = int(math.ceil(doc.size().height())) + 20
            self.setFixedSize(target_w, max(42, target_h))
        else:
            # Multi-line wrapped: compute exact wrapped height with breathing room
            self.lbl.setWordWrap(True)
            target_w = effective_max
            inner_w = max(40, target_w - 36)
            doc.setTextWidth(inner_w)
            target_h = int(math.ceil(doc.size().height())) + 24
            self.setFixedSize(target_w, max(46, target_h))
        self.updateGeometry()


class SlideToRetry(QWidget):
    triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Fixed 88x26 with breathing room: the old 80x24 box clipped the
        # 18px round handle top/bottom so the circle read as a square.
        self.setFixedSize(88, 26)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 5)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        # wave6: z-order lids/brows above eyes
        for _w in [x for x in (getattr(self, "btn_eye", None),) if x is not None]:
            if hasattr(_w, 'setZValue'): _w.setZValue(1.0)
        for _w in [x for x in (getattr(self, "retry_slider", None), getattr(self, "slider", None),) if x is not None]:
            if hasattr(_w, 'setZValue'): _w.setZValue(10.0)
        self.slider.setRange(0, 100)
        self.slider.setValue(0)
        self.slider.setToolTip("🔁 Slide right to regenerate response")
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: rgba(147, 51, 234, 0.22);
                height: 10px;
                border-radius: 5px;
                border: 1px solid rgba(192, 132, 252, 0.35);
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 rgba(147,51,234,0.3), stop:1 rgba(192,132,252,0.85));
                border-radius: 5px;
            }
            QSlider::handle:horizontal {
                background: #C084FC;
                width: 14px;
                margin: -2px 0;
                border-radius: 7px;
                border: 2px solid #FFFFFF;
            }
            QSlider::handle:horizontal:pressed {
                background: #E9D5FF;
            }
        """)
        self.slider.sliderReleased.connect(self._on_released)
        layout.addWidget(self.slider)

    def _on_released(self):
        if self.slider.value() >= 80:
            self.triggered.emit()
        self.slider.setValue(0)

class CodeBlockCard(QFrame):
    def __init__(self, lang: str, code_text: str, parent=None):
        super().__init__(parent)
        self.code_text = code_text
        self.lang = lang.lower() if lang else ""
        self.is_markdown = self.lang in ("md", "markdown")
        lines = (code_text or "").count("\n") + 1
        self.show_preview = False  # False = raw code, True = rendered preview
        self.setObjectName("CodeBlockCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("""
            QFrame#CodeBlockCard {
                background: rgba(12, 9, 22, 0.94);
                border: 1.5px solid #9333EA;
                border-radius: 10px;
            }
            QLabel { border: none; background: transparent; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hdr = QFrame()
        hdr.setStyleSheet("""
            background: rgba(147, 51, 234, 0.25);
            border-bottom: 1px solid #9333EA;
            border-top-left-radius: 9px;
            border-top-right-radius: 9px;
        """)
        hdr_l = QHBoxLayout(hdr)
        hdr_l.setContentsMargins(12, 5, 12, 5)

        lbl_lang = QLabel(f"⚡ {lang.upper()}" if lang else "🗃️ Text Block")
        lbl_lang.setStyleSheet("color: #C084FC; font-weight: bold; font-size: 11px; border: none; background: transparent;")
        hdr_l.addWidget(lbl_lang)
        hdr_l.addStretch()

        # Preview/Raw toggle button (only for markdown)
        if self.is_markdown:
            self.btn_toggle = QPushButton("👁 Preview")
            self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_toggle.setToolTip("Toggle between raw markdown and rendered preview")
            self.btn_toggle.setStyleSheet("""
                QPushButton {
                    background: rgba(138, 43, 226, 0.3);
                    color: #E9D5FF;
                    border: 1px solid #9333EA;
                    border-radius: 5px;
                    padding: 2px 10px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover { background: #9333EA; color: #FFFFFF; }
            """)
            self.btn_toggle.clicked.connect(self._toggle_preview)
            hdr_l.addWidget(self.btn_toggle)

        # Run button for runnable scripts (bash, python, shell, etc.)
        self.is_runnable = self.lang in ("bash", "sh", "zsh", "python", "py", "cmd", "powershell", "exec", "terminal") or (not self.is_markdown and bool(code_text.strip()))
        if self.is_runnable:
            self.btn_run = QPushButton("▶ Run")
            self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_run.setToolTip("Execute code block in local terminal environment")
            self.btn_run.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #10B981, stop:1 #059669);
                    color: #FFFFFF;
                    border: 1px solid #34D399;
                    border-radius: 5px;
                    padding: 2px 10px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover { background: #059669; color: #FFFFFF; }
            """)
            self.btn_run.clicked.connect(self._run_code_block)
            hdr_l.addWidget(self.btn_run)

        # 9-line shrink toggle button
        self._is_shrunk = lines > 9
        if lines > 9:
            self.btn_shrink = QPushButton("↕ 9 Lines" if not self._is_shrunk else "↕ Expand")
            self.btn_shrink.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_shrink.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.08);
                    color: #DDD6FE;
                    border-radius: 5px;
                    padding: 2px 8px;
                    font-size: 10px;
                    border: none;
                }
                QPushButton:hover { background: #7C3AED; color: #FFFFFF; }
            """)
            self.btn_shrink.clicked.connect(self._toggle_shrink)
            hdr_l.addWidget(self.btn_shrink)

        self.btn_copy = QPushButton("📋 Copy")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.12);
                color: #F8F4FF;
                border-radius: 5px;
                padding: 2px 10px;
                font-size: 10px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover { background: #9333EA; color: #FFFFFF; }
        """)
        self.btn_copy.clicked.connect(self._copy_code)
        hdr_l.addWidget(self.btn_copy)
        layout.addWidget(hdr)

        # Stack widget to switch between raw editor and preview
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent; border: none;")
        
        # Raw code editor
        self.editor = QTextEdit()
        self.editor.setPlainText(code_text.strip())
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setFont(QFont("Consolas", 10))
        self.editor.setStyleSheet("background: transparent; border: none; color: #4ADE80; padding: 10px;")
        self._full_h = max(50, lines * 20 + 24)
        editor_h = 204 if self._is_shrunk else min(340, self._full_h)
        self.editor.setFixedHeight(editor_h)
        self.stack.addWidget(self.editor)

        # Preview widget (for markdown)
        if self.is_markdown:
            self.preview = QTextBrowser()
            self.preview.setOpenExternalLinks(True)
            self.preview.setStyleSheet("background: transparent; border: none; color: #F8F4FF; padding: 10px; font-size: 13px;")
            self.preview.setFont(QFont("Segoe UI", 10))
            self.stack.addWidget(self.preview)

        layout.addWidget(self.stack)

        # Attach smooth vertical resizer grip at bottom
        self.resizer = CodeBlockResizer(self.editor, self)
        layout.addWidget(self.resizer)

        self.card_h = 34 + editor_h + 10
        self._recalc_card_height()
        self._update_preview()

    def _recalc_card_height(self):
        """Calculate exact total height of header + editor/preview + resizer + console_frame."""
        hdr_h = 34
        if self.show_preview and hasattr(self, "preview"):
            body_h = self.preview.height()
        else:
            body_h = self.editor.height()
        resizer_h = self.resizer.height() if hasattr(self, "resizer") and not self.resizer.isHidden() else 10
        console_h = 0
        if hasattr(self, "console_frame") and self.console_frame is not None and not self.console_frame.isHidden():
            console_h = self.console_frame.height() + 8
        self.card_h = hdr_h + body_h + resizer_h + console_h + 4
        self.setFixedHeight(self.card_h)
        self.updateGeometry()
        p = self.parentWidget()
        while p is not None:
            if hasattr(p, "update_dynamic_width") and hasattr(p, "max_allowed_w"):
                try:
                    p.update_dynamic_width(p.max_allowed_w)
                except Exception:
                    pass
            if hasattr(p, "update_all_bubble_geometries"):
                try:
                    p.update_all_bubble_geometries()
                except Exception:
                    pass
                break
            p = p.parentWidget()

    def _toggle_shrink(self):
        self._is_shrunk = not self._is_shrunk
        if self._is_shrunk:
            self.editor.setFixedHeight(204)
            if hasattr(self, "btn_shrink"):
                self.btn_shrink.setText("↕ Expand")
        else:
            self.editor.setFixedHeight(self._full_h)
            if hasattr(self, "btn_shrink"):
                self.btn_shrink.setText("↕ 9 Lines")
        self._recalc_card_height()

    def _update_preview(self):
        if self.is_markdown and hasattr(self, "preview"):
            html_content = format_cel_markdown(self.code_text)
            styled_html = f"""
            <div style="font-family: 'Segoe UI', system-ui, sans-serif; line-height: 1.6;">
                {html_content}
            </div>
            """
            self.preview.setHtml(styled_html)

    def _toggle_preview(self):
        self.show_preview = not self.show_preview
        if self.show_preview:
            self.btn_toggle.setText("📝 Raw")
            self.stack.setCurrentIndex(1)
            self.preview.document().setTextWidth(max(240, self.width() - 20))
            preview_h = int(min(500, max(100, self.preview.document().size().height() + 20)))
            self.preview.setFixedHeight(preview_h)
        else:
            self.btn_toggle.setText("👁 Preview")
            self.stack.setCurrentIndex(0)
            lines = self.code_text.count("\n") + 1
            editor_h = min(340, max(50, lines * 20 + 24))
            self.editor.setFixedHeight(editor_h)
        self._recalc_card_height()

    def sizeHint(self) -> QSize:
        return QSize(self.width() if self.width() > 0 else 420, getattr(self, "card_h", 120))

    def _copy_code(self):
        play_ui_sound("pop", 0.48)
        QApplication.clipboard().setText(self.code_text)
        self.btn_copy.setText("✓ Copied!")
        QTimer.singleShot(1800, self._reset_copy_button)

    def _reset_copy_button(self):
        self.btn_copy.setText("📋 Copy")

    def _close_console(self):
        if hasattr(self, "console_frame") and self.console_frame is not None:
            self.console_frame.setVisible(False)
            self._recalc_card_height()

    def _run_code_block(self):
        """Execute the code block in local environment and expand the card cleanly!"""
        if not hasattr(self, "console_frame") or self.console_frame is None:
            self.console_frame = QFrame(self)
            self.console_frame.setObjectName("CodeConsoleFrame")
            self.console_frame.setStyleSheet("""
                QFrame#CodeConsoleFrame {
                    background: rgba(6, 4, 14, 0.92);
                    border-top: 1.5px solid #9333EA;
                    border-bottom-left-radius: 9px;
                    border-bottom-right-radius: 9px;
                    margin: 0px;
                }
            """)
            cf_layout = QVBoxLayout(self.console_frame)
            cf_layout.setContentsMargins(10, 6, 10, 8)
            cf_layout.setSpacing(4)

            c_hdr = QHBoxLayout()
            c_hdr.setContentsMargins(0, 0, 0, 0)
            c_lbl = QLabel("<b>💻 Terminal Output</b>")
            c_lbl.setStyleSheet("color: #38BDF8; font-size: 11px; border: none; background: transparent;")
            c_hdr.addWidget(c_lbl)
            c_hdr.addStretch()

            self.btn_copy_out = QPushButton("📋 Copy Output")
            self.btn_copy_out.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_copy_out.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,0.10); color: #E2E8F0; border-radius: 4px; "
                "padding: 2px 8px; font-size: 10px; font-weight: bold; border: none; } "
                "QPushButton:hover { background: #9333EA; color: #FFFFFF; }"
            )
            self.btn_copy_out.clicked.connect(
                lambda: (QApplication.clipboard().setText(self.console_out.toPlainText()), self.btn_copy_out.setText("✓ Copied!"))
            )
            c_hdr.addWidget(self.btn_copy_out)

            btn_close_con = QPushButton("✕")
            btn_close_con.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_close_con.setFixedSize(20, 20)
            btn_close_con.setToolTip("Hide terminal output")
            btn_close_con.setStyleSheet(
                "QPushButton { background: transparent; color: #94A3B8; border: none; font-size: 11px; font-weight: bold; } "
                "QPushButton:hover { color: #F87171; }"
            )
            btn_close_con.clicked.connect(self._close_console)
            c_hdr.addWidget(btn_close_con)
            cf_layout.addLayout(c_hdr)

            self.console_out = QTextEdit(self.console_frame)
            self.console_out.setReadOnly(True)
            self.console_out.setFont(QFont("Consolas", 9))
            self.console_out.setStyleSheet(
                "QTextEdit { background: rgba(0, 0, 0, 0.45); color: #4ADE80; "
                "border: 1px solid rgba(147, 51, 234, 0.28); border-radius: 6px; padding: 6px; }"
            )
            self.console_out.setFixedHeight(68)
            cf_layout.addWidget(self.console_out)
            self.layout().addWidget(self.console_frame)

        self.console_out.setPlainText("⏳ Executing script in local environment...")
        self.console_out.setFixedHeight(58)
        self.console_frame.setFixedHeight(32 + 58 + 14)
        self.console_frame.setVisible(True)
        self.console_frame.show()
        play_ui_sound("send", 0.45)
        self.btn_run.setEnabled(False)
        self.btn_run.setText("⏳ Running...")
        self._recalc_card_height()

        class ExecWorker(QThread):
            output_ready = Signal(str, int)
            def __init__(self, code, lang):
                super().__init__()
                self.code = code
                self.lang = lang
            def run(self):
                try:
                    if self.lang in ("python", "py"):
                        py_bin = resolve_python_executable() if "resolve_python_executable" in globals() else sys.executable
                        cmd = [py_bin, "-c", self.code]
                    else:
                        cmd = ["bash", "-c", self.code]
                    res = subprocess.run(cmd, shell=False, capture_output=True, text=True, timeout=30, cwd=os.getcwd())
                    out = res.stdout
                    if res.stderr:
                        out += f"\nSTDERR:\n{res.stderr}"
                    self.output_ready.emit(out.strip() or "(no output)", res.returncode)
                except subprocess.TimeoutExpired:
                    self.output_ready.emit("Error: Execution timed out after 30s", 1)
                except Exception as e:
                    self.output_ready.emit(f"Error: {e}", 1)

        def _on_done(output, code, *args, **kwargs):
            play_ui_sound("recv" if code == 0 else "pop", 0.48)
            self.btn_run.setEnabled(True)
            self.btn_run.setText("▶ Run")
            if code == 0:
                full_out = f"{output}\n\n✓ Exit code: 0"
                self.console_out.setStyleSheet(
                    "QTextEdit { background: rgba(0, 0, 0, 0.45); color: #4ADE80; "
                    "border: 1px solid rgba(74, 222, 128, 0.35); border-radius: 6px; padding: 6px; }"
                )
            else:
                full_out = f"{output}\n\n⚠️ Exit code: {code}"
                self.console_out.setStyleSheet(
                    "QTextEdit { background: rgba(0, 0, 0, 0.45); color: #F87171; "
                    "border: 1px solid rgba(248, 113, 113, 0.45); border-radius: 6px; padding: 6px; }"
                )
            self.console_out.setPlainText(full_out)
            out_lines = max(2, full_out.count("\n") + 1)
            out_h = min(220, max(62, out_lines * 18 + 18))
            self.console_out.setFixedHeight(out_h)
            self.console_frame.setFixedHeight(32 + out_h + 14)
            self._recalc_card_height()

            top_win = self.window()
            if top_win is not None:
                if hasattr(top_win, "record_code_run_output"):
                    try:
                        top_win.record_code_run_output(self.lang, self.code_text, output, code)
                    except Exception:
                        pass
                if hasattr(top_win, "update_all_bubble_geometries"):
                    top_win.update_all_bubble_geometries()

        self._exec_thread = ExecWorker(self.code_text, self.lang)
        self._exec_thread.output_ready.connect(_on_done)
        self._exec_thread.finished.connect(self._exec_thread.deleteLater)
        self._exec_thread.start()

class ThoughtAccordionCard(QFrame):
    """Collapsible Antigravity-style Thinking Process Card."""
    def __init__(self, thoughts_text: str = "", parent=None):
        super().__init__(parent)
        self.full_thoughts = thoughts_text
        self.is_expanded = False
        
        self.setStyleSheet("""
            QFrame {
                background: rgba(20, 14, 38, 0.7);
                border: 1px solid rgba(168, 85, 247, 0.35);
                border-radius: 8px;
                margin-top: 4px;
                margin-bottom: 4px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)
        
        # Header bar with toggle
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_title = QLabel("🧠 Thought Process & Agent Reasoning")
        self.lbl_title.setStyleSheet("color: #C084FC; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        hdr.addWidget(self.lbl_title)
        hdr.addStretch()
        
        self.btn_toggle = QPushButton("▼ Expand Thinking")
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setStyleSheet("""
            QPushButton {
                background: rgba(147, 51, 234, 0.2);
                color: #E9D5FF;
                border: 1px solid rgba(192, 132, 252, 0.3);
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover { background: rgba(147, 51, 234, 0.5); color: #FFFFFF; }
        """)
        self.btn_toggle.clicked.connect(self.toggle_expanded)
        hdr.addWidget(self.btn_toggle)
        
        layout.addLayout(hdr)
        
        # Collapsible Text Area with smart auto-height (no scrollbars unless 550px+ long)
        self.edit_thoughts = QTextEdit()
        self.edit_thoughts.setReadOnly(True)
        self.edit_thoughts.setFont(QFont("Consolas", 9))
        self.edit_thoughts.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.edit_thoughts.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.edit_thoughts.setStyleSheet("""
            QTextEdit {
                background: rgba(10, 6, 20, 0.85);
                color: #A7F3D0;
                border: 1px solid rgba(147, 51, 234, 0.2);
                border-radius: 6px;
                padding: 6px;
            }
        """)
        self.edit_thoughts.setVisible(False)
        self.edit_thoughts.setPlainText(self.full_thoughts)
        layout.addWidget(self.edit_thoughts)

    def _calc_target_height(self) -> int:
        self.edit_thoughts.document().setTextWidth(max(200, self.width() - 30))
        doc_h = self.edit_thoughts.document().size().height()
        lines = self.full_thoughts.count("\n") + 1
        est_h = lines * 20 + 20
        h = max(est_h, int(doc_h) + 16)
        return min(550, max(44, h))

    def set_thoughts(self, text: str):
        self.full_thoughts = text
        self.edit_thoughts.setPlainText(text)
        if self.is_expanded:
            self.edit_thoughts.setFixedHeight(self._calc_target_height())
            self.updateGeometry()

    def toggle_expanded(self):
        self.is_expanded = not self.is_expanded
        self.edit_thoughts.setVisible(self.is_expanded)
        if self.is_expanded:
            self.btn_toggle.setText("▲ Collapse Thinking")
            self.edit_thoughts.setFixedHeight(self._calc_target_height())
        else:
            self.btn_toggle.setText("▼ Expand Thinking")
            
        if self.parent() and hasattr(self.parent(), "updateGeometry"):
            self.parent().updateGeometry()
            if hasattr(self.parent(), "chat_app") and self.parent().chat_app:
                self.parent().chat_app.update_all_bubble_geometries()


class CodeBlockResizer(QFrame):
    """Interactive bottom grip handle to smoothly resize code blocks vertically."""
    def __init__(self, target_widget, parent=None):
        super().__init__(parent)
        self.target = target_widget
        self.setFixedHeight(10)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip("Drag vertically to resize code block")
        self._dragging = False
        self._start_y = 0
        self._start_h = 0
        self.setStyleSheet("""
            QFrame {
                background: rgba(147, 51, 234, 0.18);
                border-bottom-left-radius: 9px;
                border-bottom-right-radius: 9px;
                border-top: 1px solid rgba(168, 85, 247, 0.25);
            }
            QFrame:hover {
                background: rgba(168, 85, 247, 0.45);
            }
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._start_y = event.globalPosition().y()
            self._start_h = self.target.height()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = int(event.globalPosition().y() - self._start_y)
            new_h = max(60, min(900, self._start_h + delta))
            self.target.setFixedHeight(new_h)
            if hasattr(self.parent(), "_recalc_card_height"):
                self.parent()._recalc_card_height()
            elif hasattr(self.parent(), "card_h"):
                self.parent().card_h = new_h + 34 + 10
                self.parent().updateGeometry()
            top_p = self.window()
            if hasattr(top_p, "update_all_bubble_geometries"):
                top_p.update_all_bubble_geometries()
            event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()


class AntigravityAgentWorkflow(QFrame):
    """Antigravity/Codex-style sleek collapsible Agent Workflow Tray with individual subtask dropdowns."""
    def __init__(self, tool_items: list, parent=None):
        super().__init__(parent)
        self.tool_items = tool_items  # list of tuples: (tool_name, args, status, result_text)
        self.is_expanded = True
        
        self.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(14, 11, 28, 0.95), stop:1 rgba(8, 6, 18, 0.95));
                border: 1.5px solid #06B6D4;
                border-radius: 12px;
                margin-top: 4px;
                margin-bottom: 6px;
            }
        """)
        
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(12, 8, 12, 8)
        self.root_layout.setSpacing(6)
        
        # Summary Header Bar (Antigravity style)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(8)
        
        icon_lbl = QLabel("⚡")
        icon_lbl.setStyleSheet("font-size: 15px; border: none; background: transparent; color: #22D3EE;")
        hdr.addWidget(icon_lbl)
        
        count = len(tool_items)
        tool_names = list(dict.fromkeys([t[0] for t in tool_items]))
        tool_summary_str = ", ".join(tool_names[:3]) + (f" +{len(tool_names)-3}" if len(tool_names) > 3 else "")
        
        self.title_lbl = QLabel(f"<b>Agent Execution:</b> <span style='color: #22D3EE;'>{count} action{'s' if count != 1 else ''} ({tool_summary_str})</span>")
        self.title_lbl.setStyleSheet("font-size: 12px; color: #F0FDF4; border: none; background: transparent;")
        hdr.addWidget(self.title_lbl)
        hdr.addStretch()
        
        badge = QLabel("✓ Completed" if all("error" not in t[3].lower()[:40] for t in tool_items) else "⚠️ Attention")
        badge_col = "#4ADE80" if "Completed" in badge.text() else "#F87171"
        badge.setStyleSheet(f"color: {badge_col}; font-size: 10px; font-weight: bold; border: none; background: transparent;")
        hdr.addWidget(badge)
        
        self.btn_toggle_all = QPushButton("▼ Collapse Tasks" if self.is_expanded else "▶ View Tasks")
        self.btn_toggle_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_all.setStyleSheet("""
            QPushButton {
                background: rgba(6, 182, 212, 0.18);
                color: #22D3EE; border: 1px solid #06B6D4;
                border-radius: 6px; padding: 3px 10px; font-size: 10px; font-weight: bold;
            }
            QPushButton:hover { background: #06B6D4; color: #000000; }
        """)
        self.btn_toggle_all.clicked.connect(self.toggle_all)
        hdr.addWidget(self.btn_toggle_all)
        
        self.root_layout.addLayout(hdr)
        
        # Subtasks container
        self.tasks_container = QWidget()
        self.tasks_layout = QVBoxLayout(self.tasks_container)
        self.tasks_layout.setContentsMargins(4, 4, 4, 4)
        self.tasks_layout.setSpacing(6)
        
        # Use Claude Code-style widgets for edits (with diff) and reads/greps
        for idx, item in enumerate(tool_items):
            if len(item) >= 5:
                t_name, t_args, t_status, t_res, t_diff = item[0], item[1], item[2], item[3], item[4]
            else:
                t_name, t_args, t_status, t_res = item
                t_diff = None
            if (t_name in ("replace_file_content", "file_write", "write_file") and t_diff) or t_name in ("file_read", "file_list", "grep_search", "web_search"):
                step_card = make_agent_tool_widget(t_name, t_args, result=t_res, parent=self, diff=t_diff)
                step_card.set_result(t_res, is_error=(t_status == "failed"), diff=t_diff)
            else:
                step_card = self._build_step_card(idx + 1, t_name, t_args, t_status, t_res)
            self.tasks_layout.addWidget(step_card)
            
        self.root_layout.addWidget(self.tasks_container)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        lay = self.layout()
        if lay is not None:
            try:
                return lay.totalHeightForWidth(w)
            except Exception:
                pass
        return super().heightForWidth(w)

    def sizeHint(self) -> QSize:
        lay = self.layout()
        if lay is not None:
            return lay.sizeHint()
        return super().sizeHint()

    def _build_step_card(self, step_num: int, tool_name: str, args: dict, status: str, result_text: str):
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: rgba(0, 0, 0, 0.45);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(10, 6, 10, 6)
        c_layout.setSpacing(4)
        
        # Action chip header
        s_hdr = QHBoxLayout()
        s_hdr.setContentsMargins(0, 0, 0, 0)
        
        # Friendly action description
        if tool_name == "shell_exec":
            cmd = args.get("command", "") if isinstance(args, dict) else str(args)
            desc = f"Ran command: <code style='color: #67E8F9;'>{cmd[:65]}{'...' if len(cmd) > 65 else ''}</code>"
        elif tool_name in ("file_read", "read_file"):
            fpath = args.get("path", "") if isinstance(args, dict) else str(args)
            desc = f"Explored file: <code style='color: #67E8F9;'>{fpath[:65]}</code>"
        elif tool_name in ("file_write", "write_file"):
            fpath = args.get("path", "") if isinstance(args, dict) else str(args)
            desc = f"Wrote file: <code style='color: #67E8F9;'>{fpath[:65]}</code>"
        elif tool_name in ("file_list", "list_files"):
            desc = "Scanned directory tree"
        elif tool_name == "web_search":
            q = args.get("query", "") if isinstance(args, dict) else str(args)
            desc = f"Searched web: <span style='color: #67E8F9;'>\"{q[:50]}\"</span>"
        else:
            desc = f"Action: <span style='color: #67E8F9;'>{tool_name}</span>"
            
        lbl_step = QLabel(f"<span style='color: #94A3B8; font-size: 10px;'>#{step_num}</span>  {desc}")
        lbl_step.setStyleSheet("font-size: 11px; color: #E2E8F0; border: none; background: transparent;")
        s_hdr.addWidget(lbl_step, stretch=1)
        
        btn_details = QPushButton("› Details")
        btn_details.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_details.setStyleSheet("""
            QPushButton {
                background: transparent; color: #94A3B8; border: none; font-size: 10px; font-weight: bold;
            }
            QPushButton:hover { color: #22D3EE; }
        """)
        s_hdr.addWidget(btn_details)
        c_layout.addLayout(s_hdr)
        
        # Expandable result output
        detail_widget = QWidget()
        detail_widget.setVisible(False)
        d_v = QVBoxLayout(detail_widget)
        d_v.setContentsMargins(0, 4, 0, 2)
        d_v.setSpacing(4)
        
        txt_out = QTextEdit()
        txt_out.setReadOnly(True)
        txt_out.setFont(QFont("Consolas", 9))
        txt_out.setPlainText(result_text.strip() or "(empty stdout)")
        lines = result_text.count("\n") + 1
        txt_out.setFixedHeight(min(180, max(40, lines * 16 + 12)))
        txt_out.setStyleSheet("background: rgba(0,0,0,0.6); color: #4ADE80; border: 1px solid rgba(255,255,255,0.06); border-radius: 6px;")
        d_v.addWidget(txt_out)
        
        def toggle_step(w=detail_widget, b=btn_details):
            is_vis = not w.isVisible()
            w.setVisible(is_vis)
            b.setText("ˇ Hide" if is_vis else "› Details")
            top_p = self.window()
            if hasattr(top_p, "update_all_bubble_geometries"):
                top_p.update_all_bubble_geometries()
                
        btn_details.clicked.connect(toggle_step)
        c_layout.addWidget(detail_widget)
        return card

    def toggle_all(self):
        self.is_expanded = not self.is_expanded
        self.tasks_container.setVisible(self.is_expanded)
        self.btn_toggle_all.setText("▼ Collapse Tasks" if self.is_expanded else "▶ View Tasks")
        top_p = self.window()
        if hasattr(top_p, "update_all_bubble_geometries"):
            top_p.update_all_bubble_geometries()


class EditDiffCard(QFrame):
    """Claude Code-style colored unified-diff card for file edits."""

    def __init__(self, tool_name: str, args: dict, result_text: str = "", diff_text: str = "", parent=None):
        super().__init__(parent)
        self.tool_name = tool_name
        self.args = args or {}
        self.output_text = result_text or ""
        self.diff_text = diff_text or ""
        self.is_expanded = True   # diff starts visible; dropdown collapses it
        self._hover = False
        self.setObjectName("EditDiffCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.setMinimumWidth(280)
        self.setMaximumWidth(820)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("""
            QFrame#EditDiffCard { background: transparent; border: none; }
            QLabel { border: none; background: transparent; }
            QPushButton { border-radius: 8px; font-weight: 700; }
        """)

        path = str(self.args.get("path", "file"))
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # Header: ← Edit path  +N -M badge
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(10)
        lbl_icon = QLabel("←")
        lbl_icon.setStyleSheet("font-size: 16px; font-weight: 800; color: #A78BFA; border: none; background: transparent;")
        lbl_icon.setFixedWidth(20)
        hdr.addWidget(lbl_icon)
        title = QLabel(f"<b>Edit</b> <span style='color:#67E8F9; font-family:Consolas,Menlo,monospace;'>{path}</span>")
        title.setStyleSheet("font-size: 13px; color: #E9D5FF; border: none; background: transparent;")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        hdr.addWidget(title, stretch=1)
        self.btn_copy = QPushButton("Copy")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.setFixedHeight(22)
        self.btn_copy.setToolTip("Copy the written code (falls back to the diff)")
        self.btn_copy.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.08); color: #CBD5E1; border: 1px solid rgba(255,255,255,0.14);
                border-radius: 6px; padding: 2px 10px; font-size: 10px; font-weight: 700;
            }
            QPushButton:hover { background: rgba(168,85,247,0.35); color: #fff; border-color: #A855F7; }
        """)
        self.btn_copy.clicked.connect(self._copy_payload)
        hdr.addWidget(self.btn_copy)
        self.lbl_counts = QLabel("")
        self.lbl_counts.setStyleSheet(
            "QLabel { background: rgba(74,222,128,0.12); color: #4ADE80; border: 1px solid rgba(74,222,128,0.4);"
            " border-radius: 999px; padding: 2px 8px; font-size: 10px; font-weight: 800; font-family: Consolas,monospace; }"
        )
        self.lbl_counts.setFixedHeight(20)
        hdr.addWidget(self.lbl_counts)
        self.btn_toggle = QPushButton("⌃")
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setFixedSize(28, 24)
        self.btn_toggle.setToolTip("Collapse / expand the diff")
        self.btn_toggle.setStyleSheet("""
            QPushButton { background: rgba(168,85,247,0.22); color:#E9D5FF; border:1px solid rgba(192,132,252,0.55);
                border-radius:8px; font-size:14px; font-weight:800; padding:0; }
            QPushButton:hover { background: rgba(168,85,247,0.55); border-color:#C084FC; }
        """)
        self.btn_toggle.clicked.connect(self.toggle_expanded)
        hdr.addWidget(self.btn_toggle)
        root.addLayout(hdr)

        # Collapsed one-line result peek (shown while the diff is collapsed)
        self.lbl_result_peek = QLabel("")
        self.lbl_result_peek.setWordWrap(True)
        self.lbl_result_peek.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_result_peek.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_result_peek.setStyleSheet(
            "font-size: 11px; color: #94A3B8; font-family: 'Consolas', 'Menlo', monospace; "
            "border: none; background: transparent; padding: 1px 0;"
        )
        self.lbl_result_peek.setVisible(False)
        root.addWidget(self.lbl_result_peek)

        # Diff body
        self.diff_frame = QFrame()
        self.diff_frame.setObjectName("EditDiffBody")
        self.diff_frame.setStyleSheet("""
            QFrame#EditDiffBody {
                background: rgba(6, 4, 14, 0.88);
                border: 1px solid rgba(168, 85, 247, 0.35);
                border-radius: 10px;
            }
        """)
        self.diff_layout = QVBoxLayout(self.diff_frame)
        self.diff_layout.setContentsMargins(0, 0, 0, 0)
        self.diff_layout.setSpacing(0)
        root.addWidget(self.diff_frame)
        self._rebuild_diff_rows()

        if self.output_text:
            self.set_result(self.output_text, is_error=("Error" in self.output_text[:40]))

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        grad = QLinearGradient(r.left(), r.top(), r.right(), r.bottom())
        if self._hover:
            grad.setColorAt(0.0, QColor(30, 18, 60, 245))
            grad.setColorAt(1.0, QColor(14, 10, 32, 245))
        else:
            grad.setColorAt(0.0, QColor(22, 14, 46, 235))
            grad.setColorAt(1.0, QColor(10, 8, 24, 235))
        p.setBrush(grad)
        p.setPen(QPen(QColor(168, 85, 247, 140 if self._hover else 90), 1.4))
        p.drawRoundedRect(r, 14, 14)
        p.end()

    def _rebuild_diff_rows(self):
        while self.diff_layout.count():
            item = self.diff_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                sub = item.layout()
                while sub.count():
                    it = sub.takeAt(0)
                    if it.widget():
                        it.widget().deleteLater()
                del item

        if not self.diff_text.strip():
            lbl = QLabel("(no diff available)")
            lbl.setStyleSheet("font-size:11px; color:#64748B; padding:8px 12px; border:none; background:transparent;")
            self.diff_layout.addWidget(lbl)
            self.lbl_counts.setText("")
            return

        # Legacy turns persisted GLUED single-line diffs (the old newline bug)
        # - split the headers back onto their own rows so old cards stay readable.
        # Display-only heuristic; only runs when the diff has NO newlines at all.
        if "\n" not in self.diff_text and "@@" in self.diff_text:
            d = re.sub(r"(?=(?:--- |\+\+\+ |@@ ))", "\n", self.diff_text).lstrip("\n")
            fixed = []
            in_hunk = False
            for ln in d.split("\n"):
                m = re.match(r"(@@[^@]*@@)(.+)$", ln) if ln.startswith("@@") else None
                if m:
                    in_hunk = True
                    fixed.append(m.group(1))
                    ln = m.group(2)
                elif ln.startswith("@@"):
                    in_hunk = True
                # Glued "-old+new" pairs only inside hunks - never shred
                # the +++/--- header lines or pre-hunk text.
                if in_hunk and ln and not ln.startswith(("+++", "---")):
                    ln = re.sub(r"(?<=[^\s])\+(?=[^\s])", "\n+", ln)
                fixed.extend(ln.split("\n"))
            self.diff_text = "\n".join(fixed)

        added = sum(1 for ln in self.diff_text.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
        removed = sum(1 for ln in self.diff_text.splitlines() if ln.startswith("-") and not ln.startswith("---"))
        self.lbl_counts.setText(f"+{added} −{removed}")

        lines = self.diff_text.splitlines()
        MAX_ROWS = 60
        truncated = len(lines) > MAX_ROWS
        show_lines = lines[:MAX_ROWS] if truncated else lines

        old_no = new_no = 0
        in_hunk = False
        mono = "font-family:'Consolas','Menlo','Courier New',monospace;"
        for ln in show_lines:
            if ln.startswith("@@"):
                m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", ln)
                if m:
                    old_no, new_no = int(m.group(1)), int(m.group(2))
                    in_hunk = True
                row = QLabel(ln)
                row.setStyleSheet(
                    f"{mono} font-size:10px; font-weight:700; color:#C084FC; background:rgba(88,28,135,0.35);"
                    " padding:3px 10px; border:none;"
                )
                row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.diff_layout.addWidget(row)
                continue
            if ln.startswith("+++") or ln.startswith("---"):
                row = QLabel(ln)
                row.setStyleSheet(
                    f"{mono} font-size:10px; color:#94A3B8; background:rgba(15,10,30,0.9);"
                    " padding:2px 10px; border:none;"
                )
                row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.diff_layout.addWidget(row)
                continue
            if not in_hunk:
                continue
            if ln.startswith("+"):
                bg, fg, gno = "rgba(74,222,128,0.14)", "#4ADE80", str(new_no)
                new_no += 1
            elif ln.startswith("-"):
                bg, fg, gno = "rgba(248,113,113,0.14)", "#F87171", str(old_no)
                old_no += 1
            else:
                bg, fg, gno = "rgba(255,255,255,0.03)", "#94A3B8", str(new_no)
                new_no += 1
                old_no += 1
            row = QLabel(ln if ln else " ")
            row.setStyleSheet(
                f"{mono} font-size:11px; color:{fg}; background:{bg};"
                " padding:1px 10px; border:none;"
            )
            row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.diff_layout.addWidget(row)

        if truncated:
            more = QLabel(f"… {len(lines) - MAX_ROWS} more lines (use Copy for full diff)")
            more.setStyleSheet("font-size:10px; color:#64748B; padding:4px 10px; border:none; background:transparent;")
            self.diff_layout.addWidget(more)

    def _copy_payload(self):
        """Copy the code the tool actually wrote (diff as a fallback)."""
        a = self.args if isinstance(self.args, dict) else {}
        payload = ""
        if self.tool_name in ("file_write", "write_file", "create_file"):
            payload = str(a.get("content") or a.get("text") or "")
        elif self.tool_name == "replace_file_content":
            payload = str(a.get("replacement") or a.get("new_text") or "")
        if not payload:
            payload = self.diff_text or self.output_text or ""
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(payload)
            self.btn_copy.setText("✓")
            QTimer.singleShot(1400, self._reset_copy_btn)
        except Exception:
            pass

    def _reset_copy_btn(self):
        try:
            self.btn_copy.setText("Copy")
        except RuntimeError:
            pass

    def set_result(self, result, is_error=False, diff=None):
        self.output_text = result or ""
        line = " ".join((self.output_text or "").split())
        peek = line if len(line) <= 160 else line[:160] + "…"
        self.lbl_result_peek.setText(peek)
        self.lbl_result_peek.setToolTip(line)
        self.lbl_result_peek.setVisible(not self.is_expanded and bool(line))
        if diff:
            self.diff_text = diff
            self._rebuild_diff_rows()

    def toggle_expanded(self):
        """Collapse/expand the diff body (used to be permanently expanded)."""
        self.is_expanded = not self.is_expanded
        self.diff_frame.setVisible(self.is_expanded)
        self.btn_toggle.setText("⌃" if self.is_expanded else "⌄")
        line = " ".join((self.output_text or "").split())
        self.lbl_result_peek.setVisible(not self.is_expanded and bool(line))
        # Release any height clamp the #26 size button may have pinned.
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        if hasattr(self, "btn_expand_size"):
            self.btn_expand_size.setVisible(self.is_expanded)
        if hasattr(self, "resizer_bar"):
            self.resizer_bar.setVisible(self.is_expanded)
        lay = self.layout()
        if lay is not None:
            lay.invalidate()
            lay.activate()
        par = self.parentWidget()
        if par is not None and par.layout() is not None:
            par.layout().invalidate()
            par.layout().activate()
        self.adjustSize()
        self.updateGeometry()
        top_p = self.window()
        if hasattr(top_p, "update_all_bubble_geometries"):
            top_p.update_all_bubble_geometries()


class ActivityLine(QFrame):
    """Slim Claude Code-style activity line for reads / greps / lists."""

    def __init__(self, tool_name: str, args: dict, result_text: str = "", parent=None):
        super().__init__(parent)
        self.tool_name = tool_name
        self.args = args or {}
        self.output_text = result_text or ""
        self.is_expanded = False
        self.setObjectName("ActivityLine")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.setMinimumWidth(240)
        self.setMaximumWidth(820)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QFrame#ActivityLine { background: transparent; border: none; }
            QLabel { border: none; background: transparent; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 3, 10, 3)
        root.setSpacing(2)

        summary = self._activity_summary()
        arrow = "→" if tool_name in ("file_read", "file_list", "file_write") else "✳"
        arrow_col = "#A78BFA" if tool_name == "file_read" else ("#60A5FA" if tool_name == "file_list" else "#34D399")
        lbl = QLabel(f"<span style='color:{arrow_col}; font-weight:800;'>{arrow}</span>  {summary}")
        lbl.setStyleSheet("font-size:12px; color:#CBD5E1; border:none; background:transparent; font-family:'Consolas','Menlo',monospace;")
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setWordWrap(True)
        root.addWidget(lbl)

        # Collapsed result (hidden until click)
        self.detail = QLabel(self.output_text or "")
        self.detail.setVisible(False)
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.detail.setStyleSheet(
            "font-size:11px; color:#94A3B8; font-family:'Consolas','Menlo',monospace;"
            " background:rgba(0,0,0,0.5); border:1px solid rgba(255,255,255,0.08);"
            " border-radius:8px; padding:6px 10px;"
        )
        root.addWidget(self.detail)

        self._lbl_summary = lbl

    def _activity_summary(self) -> str:
        a = self.args
        t = self.tool_name
        if t == "file_read":
            p = a.get("path", "?")
            s, e = a.get("start_line"), a.get("end_line")
            meta = []
            if s: meta.append(f"offset={s}")
            if e and int(e) > 0: meta.append(f"limit={int(e) - int(s or 1) + 1}")
            suffix = f" [{', '.join(meta)}]" if meta else ""
            return f"Read <span style='color:#67E8F9;'>{p}</span>{suffix}"
        if t == "grep_search":
            q = a.get("query", "")
            p = a.get("path", ".")
            res_lines = (self.output_text or "").strip().splitlines()
            n = len([x for x in res_lines if x and not x.startswith("No matches") and not x.startswith("Error") and not x.startswith("...")])
            return f"Grep <span style='color:#FBBF25;'>\"{q}\"</span> in <span style='color:#67E8F9;'>{p}</span> ({n} match{'es' if n != 1 else ''})"
        if t == "file_list":
            p = a.get("path", ".")
            return f"List <span style='color:#67E8F9;'>{p}</span>"
        if t == "web_search":
            q = a.get("query", "")
            return f"Search web <span style='color:#FBBF25;'>\"{q}\"</span>"
        return f"{t}"

    def mousePressEvent(self, event):
        self.is_expanded = not self.is_expanded
        self.detail.setVisible(self.is_expanded and bool(self.output_text))
        top_p = self.window()
        if hasattr(top_p, "update_all_bubble_geometries"):
            top_p.update_all_bubble_geometries()
        super().mousePressEvent(event)

    def set_result(self, result, is_error=False, diff=None):
        self.output_text = result or ""
        self.detail.setText(self.output_text)
        if self.is_expanded:
            self.detail.setVisible(bool(self.output_text))


EDIT_TOOLS_UI = {"replace_file_content", "file_write", "write_file"}
ACTIVITY_TOOLS_UI = {"file_read", "file_list", "grep_search", "web_search"}


def make_agent_tool_widget(tool_name, args, result="", parent=None, diff=None):
    """Factory: Claude Code-style widgets for edits/reads, glass card otherwise."""
    if tool_name in EDIT_TOOLS_UI and diff:
        return EditDiffCard(tool_name, args, result_text=result, diff_text=diff, parent=parent)
    if tool_name in ACTIVITY_TOOLS_UI:
        return ActivityLine(tool_name, args, result_text=result, parent=parent)
    return AgentToolCard(tool_name, args, result_text=result, parent=parent)


class AgentToolCard(QFrame):
    """Modern liquid-glass agent tool card - auto-height, no dead scrollbars, resizable content."""

    _ICONS = {
        "file_read": "📄", "file_write": "✏️", "file_list": "📁", "replace_file_content": "✏️",
        "code_exec": "⚡", "web_search": "🌐", "shell_exec": "💻", "grep_search": "🔍",
    }

    def __init__(self, tool_name: str, args: dict, result_text: str = "", parent=None):
        super().__init__(parent)
        self.tool_name = tool_name
        self.args = args or {}
        self.output_text = result_text or ""
        self.is_expanded = False
        self.setObjectName("AgentToolCard")

        self.icon_str = self._ICONS.get(tool_name, "🔧")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(280)
        self.setMaximumWidth(820)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._hover = False

        self.setStyleSheet("""
            QFrame#AgentToolCard {
                background: transparent;
                border: none;
            }
            QLabel { border: none; background: transparent; }
            QPushButton {
                border-radius: 8px;
                font-weight: 700;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # ── Header ──────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(10)

        lbl_icon = QLabel(self.icon_str)
        lbl_icon.setStyleSheet("font-size: 18px; border: none; background: transparent;")
        lbl_icon.setFixedWidth(24)
        hdr.addWidget(lbl_icon)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        lbl_title = QLabel(f"<b>{tool_name}</b>")
        lbl_title.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #E9D5FF; letter-spacing: 0.3px; "
            "border: none; background: transparent;"
        )
        title_box.addWidget(lbl_title)

        # Always-visible one-line command preview (what it actually ran)
        preview = self._command_preview()
        self.lbl_preview = QLabel(preview)
        self.lbl_preview.setStyleSheet(
            "font-size: 11px; color: #A78BFA; font-family: 'Consolas', 'Menlo', monospace; "
            "border: none; background: transparent;"
        )
        self.lbl_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_preview.setWordWrap(True)
        self.lbl_preview.setToolTip(preview)
        title_box.addWidget(self.lbl_preview)
        hdr.addLayout(title_box, stretch=1)

        self.lbl_status = QLabel("⚡ Running")
        self.lbl_status.setStyleSheet(
            "QLabel { background: rgba(251, 191, 36, 0.16); color: #FBBF25; border: 1px solid rgba(251, 191, 36, 0.45);"
            " border-radius: 999px; padding: 3px 10px; font-size: 10px; font-weight: 800; }"
        )
        self.lbl_status.setFixedHeight(22)
        hdr.addWidget(self.lbl_status)

        self.btn_toggle = QPushButton("⌄")
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setFixedSize(28, 24)
        self.btn_toggle.setToolTip("Expand / collapse full command & output")
        self.btn_toggle.setStyleSheet("""
            QPushButton {
                background: rgba(168, 85, 247, 0.22);
                color: #E9D5FF;
                border: 1px solid rgba(192, 132, 252, 0.55);
                border-radius: 8px;
                font-size: 14px;
                font-weight: 800;
                padding: 0;
            }
            QPushButton:hover { background: rgba(168, 85, 247, 0.55); border-color: #C084FC; }
            QPushButton:pressed { background: rgba(147, 51, 234, 0.75); }
        """)
        self.btn_toggle.clicked.connect(self.toggle_expanded)
        hdr.addWidget(self.btn_toggle)

        root.addLayout(hdr)

        # ── Collapsed result strip (one-liner, always visible) ──
        self.lbl_result_peek = QLabel("")
        self.lbl_result_peek.setWordWrap(True)
        self.lbl_result_peek.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_result_peek.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_result_peek.setStyleSheet(
            "font-size: 11px; color: #94A3B8; font-family: 'Consolas', 'Menlo', monospace; "
            "border: none; background: transparent; padding: 2px 0;"
        )
        self.lbl_result_peek.setVisible(bool(self.output_text))
        root.addWidget(self.lbl_result_peek)

        # ── Expanded details (auto-height, zero scrollbars) ─────
        self.details_frame = QFrame()
        self.details_frame.setVisible(False)
        self.details_frame.setObjectName("AgentToolDetails")
        self.details_frame.setStyleSheet("""
            QFrame#AgentToolDetails {
                background: rgba(8, 6, 16, 0.72);
                border: 1px solid rgba(168, 85, 247, 0.28);
                border-radius: 12px;
            }
        """)
        d_layout = QVBoxLayout(self.details_frame)
        d_layout.setContentsMargins(12, 10, 12, 12)
        d_layout.setSpacing(8)
        self.d_layout = d_layout

        args_str = json.dumps(self.args, indent=2) if isinstance(self.args, dict) else str(self.args)

        args_head = QHBoxLayout()
        lbl_args_head = QLabel("INPUT")
        lbl_args_head.setStyleSheet(
            "font-size: 10px; font-weight: 800; letter-spacing: 1.2px; color: #C084FC; "
            "border: none; background: transparent;"
        )
        args_head.addWidget(lbl_args_head)
        args_head.addStretch()
        btn_copy_args = QPushButton("Copy")
        btn_copy_args.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy_args.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.08); color: #CBD5E1; border: 1px solid rgba(255,255,255,0.12);
                border-radius: 6px; padding: 2px 10px; font-size: 10px; font-weight: 700;
            }
            QPushButton:hover { background: rgba(168,85,247,0.35); color: #fff; border-color: #A855F7; }
        """)
        btn_copy_args.clicked.connect(lambda: (
            QApplication.clipboard().setText(args_str),
            btn_copy_args.setText("✓")
        ))
        args_head.addWidget(btn_copy_args)
        d_layout.addLayout(args_head)

        self.txt_args = self._make_mono_box(args_str)
        _sel_args = "QTextEdit" if isinstance(self.txt_args, QTextEdit) else "QLabel"
        self.txt_args.setStyleSheet(f"""
            {_sel_args} {{
                font-family: 'Consolas', 'Menlo', 'Courier New', monospace;
                font-size: 12px; line-height: 1.35; color: #E2E8F0;
                background: rgba(147, 51, 234, 0.10);
                border: 1px solid rgba(168, 85, 247, 0.22);
                border-radius: 8px;
                padding: 8px 10px;
            }}
        """)
        d_layout.addWidget(self.txt_args)

        out_hdr = QHBoxLayout()
        lbl_out_head = QLabel("OUTPUT")
        lbl_out_head.setStyleSheet(
            "font-size: 10px; font-weight: 800; letter-spacing: 1.2px; color: #38BDF8; "
            "border: none; background: transparent;"
        )
        out_hdr.addWidget(lbl_out_head)
        out_hdr.addStretch()
        btn_copy_out = QPushButton("Copy")
        btn_copy_out.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy_out.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.08); color: #CBD5E1; border: 1px solid rgba(255,255,255,0.12);
                border-radius: 6px; padding: 2px 10px; font-size: 10px; font-weight: 700;
            }
            QPushButton:hover { background: rgba(56,189,248,0.30); color: #fff; border-color: #38BDF8; }
        """)
        btn_copy_out.clicked.connect(lambda: (
            QApplication.clipboard().setText(self.output_text or ""),
            btn_copy_out.setText("✓")
        ))
        out_hdr.addWidget(btn_copy_out)
        d_layout.addLayout(out_hdr)

        self.txt_out = self._make_mono_box(self.output_text or "Executing…")
        self._style_output_label(False)
        d_layout.addWidget(self.txt_out)

        root.addWidget(self.details_frame)

        # Apply initial result styling / peek
        if self.output_text:
            self.set_result(self.output_text, is_error=("Error" in self.output_text[:40]))

    @staticmethod
    def _make_mono_box(text: str):
        """QLabel for normal payloads (auto-grows); scroll-capped QTextEdit for huge ones."""
        txt = text or ""
        huge = len(txt) > 8000 or len(txt.splitlines()) > 80
        if not huge:
            box = QLabel(txt)
            box.setWordWrap(True)
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            return box
        box = QTextEdit()
        box.setPlainText(txt)
        box.setReadOnly(True)
        box.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        box.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        box.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        box.setFixedHeight(300)
        box.setMinimumHeight(80)
        return box

    @staticmethod
    def _set_box_text(box, text: str):
        if isinstance(box, QTextEdit):
            box.setPlainText(text or "")
        else:
            box.setText(text or "")

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        lay = self.layout()
        if lay is not None:
            try:
                return lay.totalHeightForWidth(w)
            except Exception:
                pass
        return super().heightForWidth(w)

    def sizeHint(self) -> QSize:
        lay = self.layout()
        if lay is not None:
            return lay.sizeHint()
        return super().sizeHint()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        """Explicit glass gradient - stylesheet backgrounds don't paint under WA_TranslucentBackground."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        grad.setColorAt(0.0, QColor(28, 16, 52, 235))
        grad.setColorAt(0.55, QColor(18, 12, 36, 240))
        grad.setColorAt(1.0, QColor(12, 9, 24, 245))
        p.setBrush(grad)
        border = QColor(192, 132, 252, 217) if self._hover else QColor(168, 85, 247, 140)
        p.setPen(QPen(border, 1.5))
        p.drawRoundedRect(r, 16, 16)
        p.end()

    def _command_preview(self) -> str:
        a = self.args
        if not isinstance(a, dict) or not a:
            return str(a) if a else "(no arguments)"
        # Write tools: show "path ← \"content snippet\"" so you see exactly
        # WHAT file got written and with what body at a glance.
        if self.tool_name in ("file_write", "write_file", "create_file", "replace_file_content"):
            p = str(a.get("path") or a.get("file_path") or "?").replace("\n", " ")
            body = " ".join(str(a.get("content") or a.get("new_text") or "").split())
            if len(body) > 44:
                body = body[:44] + "…"
            return f"{p}  ←  \"{body}\"" if body else f"path: {p}"
        for key in ("command", "cmd", "path", "file_path", "directory", "directory_path", "query", "code"):
            if key in a:
                val = str(a[key]).replace("\n", " ").strip()
                return f"{key}: {val}" if key != "command" else val
        try:
            compact = json.dumps(a, separators=(",", ": "))
        except Exception:
            compact = str(a)
        return compact.replace("\n", " ")

    def _style_output_label(self, is_error: bool):
        color = "#F87171" if is_error else "#4ADE80"
        sel = "QTextEdit" if isinstance(self.txt_out, QTextEdit) else "QLabel"
        self.txt_out.setStyleSheet(f"""
            {sel} {{
                font-family: 'Consolas', 'Menlo', 'Courier New', monospace;
                font-size: 12px; line-height: 1.35; color: {color};
                background: {'rgba(239, 68, 68, 0.08)' if is_error else 'rgba(74, 222, 128, 0.07)'};
                border: 1px solid {'rgba(239, 68, 68, 0.28)' if is_error else 'rgba(74, 222, 128, 0.25)'};
                border-radius: 8px;
                padding: 8px 10px;
            }}
        """)

    def _set_peek(self, result_text: str):
        line = " ".join((result_text or "").split())
        if not line:
            self.lbl_result_peek.setVisible(False)
            return
        max_n = 160
        peek = line if len(line) <= max_n else line[:max_n] + "…"
        self.lbl_result_peek.setText(peek)
        self.lbl_result_peek.setToolTip(line)
        self.lbl_result_peek.setVisible(not self.is_expanded)

    def set_result(self, result_text: str, is_error: bool = False, diff: str = None):
        self.output_text = result_text or ""
        failed = is_error or "Error" in self.output_text[:40] or "failed" in self.output_text[:20].lower()

        if failed:
            self.lbl_status.setText("✗ Failed")
            self.lbl_status.setStyleSheet(
                "QLabel { background: rgba(239, 68, 68, 0.16); color: #F87171; border: 1px solid rgba(239, 68, 68, 0.5);"
                " border-radius: 999px; padding: 3px 10px; font-size: 10px; font-weight: 800; }"
            )
        else:
            self.lbl_status.setText("✓ Done")
            self.lbl_status.setStyleSheet(
                "QLabel { background: rgba(74, 222, 128, 0.14); color: #4ADE80; border: 1px solid rgba(74, 222, 128, 0.48);"
                " border-radius: 999px; padding: 3px 10px; font-size: 10px; font-weight: 800; }"
            )

        # Swap label -> scroll-capped QTextEdit when payload crosses the huge threshold
        if (not isinstance(self.txt_out, QTextEdit)
                and (len(self.output_text) > 8000 or len(self.output_text.splitlines()) > 80)):
            self.d_layout.removeWidget(self.txt_out)
            self.txt_out.deleteLater()
            self.txt_out = self._make_mono_box(self.output_text)
            self._style_output_label(failed)
            self.d_layout.addWidget(self.txt_out)
        else:
            self._set_box_text(self.txt_out, self.output_text or " - ")
            self._style_output_label(failed)
        self._set_peek(self.output_text)

        # Grow to fit full content - no fixed height, no scrollbars
        if not isinstance(self.txt_out, QTextEdit):
            self.txt_out.adjustSize()
        self.details_frame.adjustSize()
        self.updateGeometry()
        parent = self.parent()
        if parent is not None and hasattr(parent, "updateGeometry"):
            parent.updateGeometry()
            chat_app = getattr(parent, "chat_app", None)
            if chat_app is not None and hasattr(chat_app, "update_all_bubble_geometries"):
                chat_app.update_all_bubble_geometries()

    def set_output_box_height(self, h: int) -> None:
        """Resize the biggest scrollable payload (used by _ToolCardResizer drag)."""
        target = None
        box = getattr(self, "txt_out", None)
        if isinstance(box, QTextEdit):
            target = box
        if target is None:
            ed = getattr(self, "_out_editor", None)
            if isinstance(ed, QTextEdit):
                target = ed
        if target is not None:
            target.setFixedHeight(max(54, int(h)))
            target.updateGeometry()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        lay = self.layout()
        if lay is not None:
            lay.invalidate()
            lay.activate()
        self.adjustSize()
        self.updateGeometry()

    def toggle_expanded(self):
        self.is_expanded = not self.is_expanded
        self.details_frame.setVisible(self.is_expanded)
        self.btn_toggle.setText("⌃" if self.is_expanded else "⌄")
        self.lbl_result_peek.setVisible(not self.is_expanded and bool(self.output_text))
        if self.is_expanded:
            for lbl in [x for x in (getattr(self, "txt_args", None), getattr(self, "txt_out", None)) if x is not None]:
                if isinstance(lbl, QLabel):
                    lbl.setMinimumHeight(0)
                    lbl.setMaximumHeight(16777215)
                lbl.updateGeometry()
            self.details_frame.adjustSize()
        else:
            self.details_frame.adjustSize()
        # The #26 size toggle pinned this card with setMinimumHeight(); release
        # the clamp so collapsing actually shrinks the card on the FIRST click
        # instead of leaving a giant empty glass slab until you spam the button.
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        # '↕ Expand' + the drag bar only make sense while details are open.
        if hasattr(self, "btn_expand_size"):
            self.btn_expand_size.setVisible(self.is_expanded)
        if hasattr(self, "resizer_bar"):
            self.resizer_bar.setVisible(self.is_expanded)
        lay = self.layout()
        if lay is not None:
            lay.invalidate()
            lay.activate()
        par = self.parentWidget()
        if par is not None and par.layout() is not None:
            par.layout().invalidate()
            par.layout().activate()
        self.adjustSize()
        self.updateGeometry()
        p = self.parentWidget()
        while p is not None:
            if hasattr(p, "update_all_bubble_geometries"):
                p.update_all_bubble_geometries()
                break
            if hasattr(p, "chat_layout"):
                p.update_all_bubble_geometries()
                break
            p = p.parentWidget()


from PySide6.QtGui import QCursor  # live cursor sampling for the rail's tag game


class _ThinkingDotsCanvas(QWidget):
    """One glowing rail with a star that sweeps left ↔ right - and plays tag.

    The star is a tiny 1-D body: it accelerates out of one end, cruises,
    brakes into the other end, reverses along the exact same straight line
    and spins back. Its rotation is integrated from its *position*, so it
    rolls forward and unwinds in reverse on the return leg - never a snap.

    The fun bit: park the pointer on the rail and the star collides with it.
    It sticks under the cursor, trembles, and keeps winding up its internal
    acceleration the whole time (the glow swells to show the charge). Slide
    the cursor off the rail and all that stored energy becomes launch speed  - 
    it rockets away, then settles back to its lazy cruise.

    The canvas stays a fixed 96×24 rect, so Qt never recalculates layout
    geometry and the thinking card cannot jump.

    ``FRAMES``/``advance()`` are kept only as a compatibility shim for older
    tooling; paint() no longer uses them.
    """
    FRAMES = (
        (1, 0, 0),
        (0, 1, 0),
        (0, 0, 1),
        (0, 1, 0),
    )
    _PERIOD_S = 1.9          # nominal one-way sweep, for old checks/tooling
    _CRUISE = 0.62           # progress per second at cruising speed
    _EDGE_EASE = 0.20        # fraction of the rail used to brake into the end
    _THROTTLE = 10.0         # how quickly the star chases its target speed
    _CHARGE_MAX = 3.0        # cap on the wind-up (glow + launch power)
    _CHARGE_GAIN = 1.1       # base wind-up per second (self-multiplying)
    _RELEASE_COOLDOWN = 0.28  # seconds for a just-launched star to escape
    _SPEED_MAX = 3.2          # cap on the launch burst so it stays trackable

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(96, 24)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._frame_idx = 0
        self._phase = 0.0        # 0..1 position along the rail
        self._dir = 1            # +1 → right, -1 → left
        self._speed = 0.0        # progress / second (sign lives in _dir)
        self._spin = 0.0         # integrated star angle (radians)
        self._clock = 0.0        # seconds since show, for the halo pulse
        self._charge = 0.0       # wind-up stored while the cursor pins it
        self._blocked = False
        self._release_cd = 0.0
        self._last_tick = time.monotonic()
        self._anim = QTimer(self)
        self._anim.setInterval(33)   # ~30 fps, tiny 96×24 canvas only
        self._anim.timeout.connect(self._animate)
        self._anim.start()

    # ── animation clock ──────────────────────────────────────────────────
    def _animate(self) -> None:
        now = time.monotonic()
        dt = max(0.0, min(0.12, now - self._last_tick))
        self._last_tick = now
        if not self.isVisible():
            return

        self._clock += dt
        prev = self._phase
        self._release_cd = max(0.0, self._release_cd - dt)
        cursor_p = self._cursor_progress()

        # ── tag: the pointer catches the star ────────────────────────────
        if cursor_p is not None and self._release_cd <= 0.0:
            if self._blocked:
                self._follow_cursor(cursor_p, dt)
            else:
                span = max(1.0, float(self.width()) - 20.0)
                gap_px = (cursor_p - self._phase) * span
                touching = abs(gap_px) <= 9.0
                approaching = (gap_px * self._dir) >= -6.0
                if touching and approaching and (self._speed > 0.02 or abs(gap_px) <= 4.0):
                    self._blocked = True
                    self._speed = 0.0
                    self._charge = 0.15
                    self._follow_cursor(cursor_p, dt)
        elif self._blocked:
            self._launch()

        if not self._blocked:
            self._drift(dt)

        # Rotation follows the positional delta: forward on the way out,
        # unwinding on the way back, frozen while pinned under the cursor.
        self._spin += (self._phase - prev) * math.tau * 2.4
        self.update()

    def _follow_cursor(self, cursor_p: float, dt: float) -> None:
        """Pin the star under the pointer and wind it up like a spring."""
        self._phase += (cursor_p - self._phase) * min(1.0, dt * 18.0)
        self._phase = min(1.0, max(0.0, self._phase))
        self._speed = 0.0
        # The acceleration budget keeps compounding the longer it is held.
        self._charge = min(
            self._CHARGE_MAX,
            self._charge + dt * (self._CHARGE_GAIN + 1.4 * self._charge),
        )

    def _launch(self) -> None:
        """Release the spring: stored wind-up becomes a burst of speed."""
        self._blocked = False
        self._release_cd = self._RELEASE_COOLDOWN
        self._speed = min(self._SPEED_MAX,
                          self._CRUISE * (1.0 + 2.2 * self._charge))

    def _drift(self, dt: float) -> None:
        """Normal cruise: accelerate out, brake into the far end, reverse."""
        dist_end = (1.0 - self._phase) if self._dir > 0 else self._phase
        e = min(1.0, max(0.0, dist_end / self._EDGE_EASE))
        ease = e * e * (3.0 - 2.0 * e)
        # Never let the target reach exactly zero or the star would only
        # approach the end asymptotically; a small floor guarantees the
        # turnaround actually happens, then the clamp kills that last pinch.
        target = self._CRUISE * (0.10 + 0.90 * ease) * (1.0 + 1.8 * self._charge)
        self._speed += (target - self._speed) * min(1.0, dt * self._THROTTLE)
        self._speed = min(self._SPEED_MAX, max(0.0, self._speed))
        self._phase += self._dir * self._speed * dt
        if self._phase >= 1.0:
            self._phase = 1.0
            self._dir = -1
            self._speed = 0.0
        elif self._phase <= 0.0:
            self._phase = 0.0
            self._dir = 1
            self._speed = 0.0
        self._charge = max(0.0, self._charge - dt * 4.0)

    def _cursor_progress(self) -> float | None:
        """Cursor position as 0..1 along the rail, or None when it is away."""
        if not self.isVisible():
            return None
        local = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(local):
            return None
        if abs(local.y() - self.height() / 2.0) > 11.0:
            return None
        span = max(1.0, float(self.width()) - 20.0)
        return min(1.0, max(0.0, (local.x() - 10.0) / span))

    def showEvent(self, event) -> None:
        self._last_tick = time.monotonic()
        self._anim.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._anim.stop()
        self._blocked = False
        self._charge = 0.0
        self._speed = 0.0
        self._release_cd = 0.0
        super().hideEvent(event)

    def advance(self) -> tuple[int, int, int]:
        """Legacy frame API (kept for old checks; unused by paint)."""
        self._frame_idx = (self._frame_idx + 1) % len(self.FRAMES)
        self.update()
        return self.FRAMES[self._frame_idx]

    # ── geometry helpers ─────────────────────────────────────────────────
    @staticmethod
    def _star_path(cx: float, cy: float, r_outer: float, r_inner: float,
                   rotation: float = 0.0) -> QPainterPath:
        path = QPainterPath()
        pts = 5
        for i in range(pts * 2):
            r = r_outer if i % 2 == 0 else r_inner
            angle = -math.pi / 2.0 + rotation + i * (math.pi / pts)
            x = cx + math.cos(angle) * r
            y = cy + math.sin(angle) * r
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        return path

    def _point(self, t: float, x0: float, x1: float, cy: float):
        """Straight-line position on the rail - no vertical weave, ever."""
        t = min(1.0, max(0.0, t))
        return x0 + (x1 - x0) * t, cy

    # ── painting ─────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        cy = h / 2.0
        x0, x1 = 10.0, w - 10.0

        # 1. The rail: one long, soft purple line with bright end glints.
        rail = QLinearGradient(x0, 0.0, x1, 0.0)
        rail.setColorAt(0.0, QColor(147, 51, 234, 45))
        rail.setColorAt(0.5, QColor(192, 132, 252, 120))
        rail.setColorAt(1.0, QColor(147, 51, 234, 45))
        p.setPen(QPen(QBrush(rail), 2.0, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(x0, cy), QPointF(x1, cy))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(232, 121, 249, 90)))
        p.drawEllipse(QPointF(x0, cy), 1.6, 1.6)
        p.drawEllipse(QPointF(x1, cy), 1.6, 1.6)

        # 2. Position on the rail: a straight line, never a Bézier weave.
        t = min(1.0, max(0.0, self._phase))
        direction = float(self._dir)
        sx, sy = self._point(t, x0, x1, cy)

        charge_ratio = min(1.0, self._charge / self._CHARGE_MAX)
        if self._blocked:
            # Held under the cursor: a tiny, charged tremble on the spot.
            sx += math.sin(self._clock * 52.0) * (0.30 + 1.25 * charge_ratio)
            sx = min(x1, max(x0, sx))

        # 3. Comet trail: shorter while braking or pinned, long at cruise.
        trail_len = 0.04 + 0.26 * min(1.0, self._speed / self._CRUISE)
        if self._blocked:
            trail_len = 0.03
        tail_t = min(1.0, max(0.0, t - direction * trail_len))
        if abs(t - tail_t) > 1e-4:
            trail = QPainterPath()
            tx, ty = self._point(tail_t, x0, x1, cy)
            trail.moveTo(tx, ty)
            steps = 12
            for i in range(1, steps + 1):
                pt = tail_t + (t - tail_t) * (i / steps)
                px, py = self._point(pt, x0, x1, cy)
                trail.lineTo(px, py)
            tg = QLinearGradient(tx, 0.0, sx, 0.0)
            tg.setColorAt(0.0, QColor(232, 121, 249, 0))
            tg.setColorAt(1.0, QColor(232, 121, 249, 150))
            p.setPen(QPen(QBrush(tg), 2.4, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(trail)

        # 4. Star: halo pulse speeds up as the wind-up grows, and the glow
        #    swells to telegraph all that stored acceleration.
        pulse_hz = 1.6 + 3.2 * charge_ratio
        pulse = 0.5 + 0.5 * math.sin(self._clock * math.tau * pulse_hz)
        glow_r = 9.5 + 2.0 * pulse + 2.6 * charge_ratio
        glow_alpha = min(255, int(120 + 60 * pulse + 45 * charge_ratio))
        glow = QRadialGradient(QPointF(sx, sy), glow_r)
        glow.setColorAt(0.0, QColor(245, 208, 254, glow_alpha))
        glow.setColorAt(0.55, QColor(232, 121, 249, 70))
        glow.setColorAt(1.0, QColor(168, 85, 247, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(sx, sy), glow_r, glow_r)

        rotation = self._spin
        scale = 0.92 + 0.18 * pulse + 0.16 * charge_ratio
        star = self._star_path(sx, sy, 6.6 * scale, 2.9 * scale, rotation)
        p.setPen(QPen(QColor("#F5D0FE"), 1.1))
        p.setBrush(QBrush(QColor("#E879F9")))
        p.drawPath(star)
        p.end()


class ThinkingCard(QFrame):
    def __init__(self, provider: str = "", model_name: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(32, 18, 52, 0.94), stop:1 rgba(18, 12, 34, 0.94));
                border: 1.5px solid #A855F7;
                border-radius: 12px;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)

        self.spinner = QLabel("✦")
        self.spinner.setFixedWidth(22)
        self.spinner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spinner.setStyleSheet("font-size: 18px; border: none; background: transparent;")
        layout.addWidget(self.spinner)

        init_msg = "Cel is analyzing request & context..."
        if provider and model_name:
            init_msg = f"Connecting to {provider} ({model_name})..."
        elif provider:
            init_msg = f"Connecting to {provider}..."

        self.lbl_text = QLabel(init_msg)
        self.lbl_text.setStyleSheet("color: #E9D5FF; font-size: 12px; font-weight: bold; border: none; background: transparent;")
        layout.addWidget(self.lbl_text, stretch=1)

        self.dots_canvas = _ThinkingDotsCanvas(self)
        layout.addWidget(self.dots_canvas)

        # Hidden compatibility label in case any test checks lbl_dots
        self.lbl_dots = QLabel("⭐ ⭕ ⭕", self)
        self.lbl_dots.setVisible(False)
        self.dot_frames = ["⭐ ⭕ ⭕", "⭕ ⭐ ⭕", "⭕ ⭕ ⭐", "⭕ ⭐ ⭕"]
        self.dot_idx = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(320)

    def set_status(self, text: str):
        if not text:
            return
        icon = "⚡"
        if "Loading" in text or "RAM" in text or "weights" in text:
            icon = "⏳"
        elif "Generating" in text or "Local" in text:
            icon = "🧠"
        elif "Connecting" in text:
            icon = "📡"
        elif "Agent" in text or "agent" in text:
            icon = "🤖"
        elif "Running" in text or "shell_exec" in text or "exec" in text:
            icon = "🔧"
        elif "Tool" in text:
            icon = "🛠️"
        self.spinner.setText(icon)
        self.lbl_text.setText(text)

    def _tick(self):
        self.dots_canvas.advance()
        self.dot_idx = (self.dot_idx + 1) % len(self.dot_frames)

class MessageBubbleNew(QWidget):
    #: Image-URL previews decode off-thread and land here queued.
    _image_loaded = Signal(object, object, str, str)
    def __init__(self, role, content, meta=None, glass_opacity=0.72, accent_color="#C084FC",
                 attached_images=None, attached_files=None, is_ghost=False, is_live=False, chat_app=None, parent=None):
        super().__init__(parent)
        self.role = role
        self.is_user = (role == "user")
        #: Live stream bubbles show the animated ThinkingCard while empty;
        #: history-loaded empties render a static note instead (never a live
        #: "analyzing..." card in a chat the user never sent to).
        if content and role != "user":
            from cellium.core.utils import split_mood_first, strip_inline_mood_display
            content = strip_inline_mood_display(split_mood_first(content)[0])
        self.content = content
        self.meta = meta or {}
        self.glass_opacity = glass_opacity
        self.accent_color = accent_color
        self.attached_images = attached_images or []
        self.attached_files = attached_files or []
        self.is_ghost = is_ghost
        self.chat_app = chat_app
        self.memory_index = None  # index into session memory (NOT layout index)
        self.body_label = None
        self.thinking_card = None
        self.info_card = None
        self.info_expanded = False
        self.is_live = bool(is_live)
        self.show_raw = False
        self._body_sources = []
        self.btn_eye = None

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setMinimumWidth(140)
        self.max_allowed_w = 600
        self.init_ui()

    def refresh_avatar(self) -> None:
        """Re-read this bubble's profile picture from disk."""
        if getattr(self, "avatar_lbl", None) is not None:
            self.avatar_lbl.refresh()

    def _on_avatar_clicked(self) -> None:
        """Click the cutout in the header → crop/zoom a new picture."""
        who = "user" if self.is_user else "cel"

        def _after() -> None:
            self.refresh_avatar()
            _refresh_avatar_labels(self.chat_app)

        try:
            run_avatar_flow(who, self, _after)
        except Exception:
            pass

    def _is_child_active(self, w: QWidget) -> bool:
        """True unless `w` was explicitly hidden (e.g. collapsed info_card).

        Never skip a newly added ChatBubbleBody just because Qt's async
        QEvent::ShowToParent hasn't fired yet (which caused Bug #8 & Bug #3)!
        """
        if w is None:
            return False
        if self.info_card is not None and w is self.info_card:
            return bool(self.info_expanded)
        if isinstance(w, (ChatBubbleBody, CodeBlockCard, ThoughtAccordionCard, AntigravityAgentWorkflow, AgentToolCard)):
            if w.isHidden() and not w.testAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide):
                w.show()
            return not w.isHidden()
        return not w.isHidden()

    def update_dynamic_width(self, max_allowed_w: int):
        self.max_allowed_w = max_allowed_w
        margin_h = self.layout_v.contentsMargins().left() + self.layout_v.contentsMargins().right()
        text_ideal = 100
        for i in range(self.layout_v.count()):
            item = self.layout_v.itemAt(i)
            w = item.widget() if item else None
            if self._is_child_active(w):
                if isinstance(w, ChatBubbleBody):
                    doc_w = w.get_ideal_width()
                    text_ideal = max(text_ideal, doc_w)
                elif isinstance(w, CodeBlockCard):
                    text_ideal = max(text_ideal, 420)
                elif isinstance(w, ThinkingCard):
                    # Let the card be as wide as its measured loading text
                    # (set in _final_tc_set_status) - never hard-clamp to 280.
                    text_ideal = max(text_ideal, w.minimumWidth())
                elif isinstance(w, AgentToolCard):
                    text_ideal = max(text_ideal, 420)
                elif isinstance(w, AntigravityAgentWorkflow):
                    text_ideal = max(text_ideal, 460)
                elif isinstance(w, ThoughtAccordionCard):
                    text_ideal = max(text_ideal, 500)
                elif self.info_card and w is self.info_card:
                    text_ideal = max(text_ideal, 420)
                elif hasattr(w, "pixmap") and w.pixmap() and not w.pixmap().isNull():
                    text_ideal = max(text_ideal, min(w.pixmap().width(), max_allowed_w))

        z = 1.0
        if self.chat_app is not None:
            z = float(getattr(self.chat_app, "zoom_level", 1.0) or 1.0)
        # Bulletproof header spacing: guarantee avatar, name, time, icons, and retry slider never squish
        hdr_needed = 360 if self.role == "user" else 420
        if hasattr(self, "layout_v") and self.layout_v.count() > 0:
            first_item = self.layout_v.itemAt(0)
            if first_item and first_item.layout():
                hdr_needed = max(hdr_needed, first_item.layout().sizeHint().width() + margin_h + 16)
        hdr_min = int(hdr_needed * max(1.0, z * 0.95))
        ideal_total = max(hdr_min, text_ideal + margin_h + 20)
        final_w = min(max(ideal_total, hdr_min), max(hdr_min, max_allowed_w))
        w_inner = max(60, final_w - margin_h)

        for i in range(self.layout_v.count()):
            item = self.layout_v.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, ChatBubbleBody):
                w._target_w = w_inner
                if w.width() != w_inner:
                    w.setMinimumWidth(min(w_inner, max(60, w.get_ideal_width())))
                    w.setMaximumWidth(w_inner)

        self.setFixedWidth(final_w)
        self.layout_v.invalidate()
        self.layout_v.activate()
        actual_h = self.heightForWidth(final_w)
        self.setFixedHeight(actual_h)
        self.updateGeometry()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        if not hasattr(self, "layout_v") or self.layout_v is None:
            return super().heightForWidth(width)
        margin_v = self.layout_v.contentsMargins().top() + self.layout_v.contentsMargins().bottom()
        margin_h = self.layout_v.contentsMargins().left() + self.layout_v.contentsMargins().right()
        w_inner = max(60, width - margin_h)
        total_h = margin_v
        visible_items = 0
        for i in range(self.layout_v.count()):
            item = self.layout_v.itemAt(i)
            w = item.widget()
            l = item.layout()
            if self._is_child_active(w):
                if isinstance(w, ChatBubbleBody):
                    w._target_w = w_inner
                    total_h += w.heightForWidth(w_inner)
                elif self.info_card is not None and w is self.info_card:
                    w.setFixedWidth(w_inner)
                    if w.layout() is not None:
                        w.layout().invalidate()
                        w.layout().activate()
                    # 7 compact info lines + margins = ~148px max
                    total_h += min(210, max(120, w.sizeHint().height()))
                elif w.hasHeightForWidth():
                    total_h += w.heightForWidth(w_inner)
                else:
                    total_h += w.sizeHint().height()
                visible_items += 1
            elif l:
                total_h += l.sizeHint().height()
                visible_items += 1
        if visible_items > 1:
            total_h += (visible_items - 1) * self.layout_v.spacing()
        return total_h + 8

    def sizeHint(self) -> QSize:
        if self.width() > 0:
            return QSize(self.width(), self.heightForWidth(self.width()))
        return super().sizeHint()

    def set_thinking_status(self, text: str):
        if hasattr(self, "thinking_card") and self.thinking_card:
            self.thinking_card.set_status(text)
            if self.chat_app and hasattr(self.chat_app, "update_all_bubble_geometries"):
                self.chat_app.update_all_bubble_geometries()

    def update_stream_text(self, text):
        self.content = text
        if self.thinking_card:
            self.layout_v.removeWidget(self.thinking_card)
            self.thinking_card.setVisible(False)
            self.thinking_card.deleteLater()
            self.thinking_card = None

        # Clean tool call markers from streaming display (single helper  - 
        # the old inline loop drifted from the commit-path cleaner).
        from cellium.core.utils import strip_tool_markers, split_mood_first, strip_inline_mood_display
        display_str = strip_tool_markers(text).strip()
        if not self.is_user:
            display_str = strip_inline_mood_display(split_mood_first(display_str)[0])
        
        # Real-time Antigravity-style thinking extraction during streaming.
        # split_think collects EVERY block (closed pairs in order + a
        # trailing unclosed one), so a second <think> can no longer drag the
        # actual answer into the thought card (giant card + missing reply).
        from cellium.core.utils import split_think
        display_str, _thoughts = split_think(display_str)
        thought_content = "\n\n - \n\n".join(t for t in _thoughts if t)
        # A runaway reasoning dump never stretches the layout: cap the card.
        if len(thought_content) > 4000:
            thought_content = (thought_content[:4000]
                               + "\n\n…(thought truncated for display)")

        # Update or create ThoughtAccordionCard live during streaming
        if thought_content:
            if not getattr(self, "thought_card", None):
                self.thought_card = ThoughtAccordionCard(thought_content, parent=self)
                # Insert at top of bubble
                self.layout_v.insertWidget(1 if self.layout_v.count() > 1 else 0, self.thought_card)
            else:
                self.thought_card.set_thoughts(thought_content)
        elif getattr(self, "thought_card", None) is not None and not display_str:
            pass

        if self.body_label:
            self.body_label.setHtmlText(self._body_html(display_str))
        else:
            self.body_label = ChatBubbleBody(self._body_html(display_str), self)
            self.layout_v.addWidget(self.body_label)
            self.body_label.show()
        self._body_sources = [(self.body_label, display_str)]

        # The stream bubble must GROW with the text: recompute its fixed
        # geometry on a throttle, or the fixed height goes stale, content
        # paints past the bubble's rect (the tear/overlap look), and only an
        # Info-click re-measures it. Throttled to ~8 Hz so fast models can't
        # jank the layout with a full re-measure per token.
        import time as _time
        _now = _time.monotonic()
        if _now - getattr(self, "_last_stream_geo", 0.0) >= 0.12:
            self._last_stream_geo = _now
            try:
                if self.chat_app and hasattr(self.chat_app, "update_all_bubble_geometries"):
                    self.chat_app.update_all_bubble_geometries()
                else:
                    self.update_dynamic_width(self.max_allowed_w)
            except RuntimeError:
                pass
        # Trigger dynamic width recalculation (recomputes fixed height so content never overflows)
        self.updateGeometry()

    def finalize_stream(self, final_text=None):
        """Finalizes streaming by parsing complete markdown into interactive CodeBlockCards and rich text.

        Renders the DISPLAY-clean text (no <think>, no tool markup, no mood
        line) - rendering the raw reply re-showed everything the stream had
        just stripped. The raw reply stays in ``self.content``/memory.
        """
        from cellium.core.utils import split_think, clean_chat_display
        if final_text is not None:
            self.content = final_text
        # Remove any existing ChatBubbleBody or CodeBlockCard widgets before final render
        for _i in range(self.layout_v.count() - 1, -1, -1):
            _it = self.layout_v.itemAt(_i)
            _w = _it.widget() if _it else None
            if isinstance(_w, (ChatBubbleBody, CodeBlockCard, ThinkingCard)):
                self.layout_v.removeWidget(_w)
                _w.setVisible(False)
                _w.deleteLater()
        self.body_label = None
        self.thinking_card = None
        self._body_sources = []
        raw = self.content
        if getattr(self, "thought_card", None) is None:
            _, _fin_thoughts = split_think(raw)
            if _fin_thoughts:
                _tc = "\n\n - \n\n".join(_fin_thoughts)
                if len(_tc) > 4000:
                    _tc = _tc[:4000] + "\n\n…(thought truncated for display)"
                self.thought_card = ThoughtAccordionCard(_tc, parent=self)
                self.layout_v.insertWidget(
                    1 if self.layout_v.count() > 1 else 0, self.thought_card)
                self.thought_card.show()
        self._render_normal_content(clean_chat_display(raw), self.is_user)
        # If info_card exists, keep it at the bottom of the bubble
        if self.info_card is not None:
            self.layout_v.removeWidget(self.info_card)
            self.layout_v.addWidget(self.info_card)
        if self.chat_app and hasattr(self.chat_app, "update_all_bubble_geometries"):
            self.chat_app.update_all_bubble_geometries()
            QTimer.singleShot(0, self.chat_app.update_all_bubble_geometries)
        else:
            self.update_dynamic_width(self.max_allowed_w)

    def _body_html(self, source: str) -> str:
        """Render a body chunk honoring the eye toggle (markdown vs raw source)."""
        if not self.show_raw:
            return format_cel_markdown(source)
        escaped = html.escape(source or "")
        return (f'<pre style="white-space: pre-wrap; word-wrap: break-word; '
                f'font-family: Consolas, Menlo, monospace; font-size: 12px; '
                f'color: #C4B5FD; background: rgba(10, 8, 20, 0.85); '
                f'border: 1px dashed rgba(168, 85, 247, 0.45); border-radius: 10px; '
                f'padding: 10px 12px; margin: 4px 0;">{escaped}</pre>')

    def _toggle_eye_mode(self):
        """Switch this bubble between rendered markdown (default) and raw source."""
        self.show_raw = not self.show_raw
        if self.btn_eye is not None:
            icon_name = "eye_open.svg" if self.show_raw else "eye_closed.svg"
            try:
                self.btn_eye.setIcon(QIcon(str(ASSETS_DIR / icon_name)))
                self.btn_eye.setToolTip("👁 Show rendered markdown" if self.show_raw else "👁 Show raw source")
            except RuntimeError:
                return
        pairs = list(getattr(self, "_body_sources", []) or [])
        if not pairs and self.body_label is not None:
            pairs = [(self.body_label, self.content or "")]
        for lbl, src in pairs:
            try:
                lbl.setHtmlText(self._body_html(src))
            except RuntimeError:
                continue
        self.updateGeometry()
        if self.chat_app and hasattr(self.chat_app, "update_all_bubble_geometries"):
            self.chat_app.update_all_bubble_geometries()
        else:
            self.update_dynamic_width(self.max_allowed_w)

    def init_ui(self):
        is_user = (self.role == "user")
        self.layout_v = QVBoxLayout(self)
        self.layout_v.setContentsMargins(14, 10, 14, 10)
        self.layout_v.setSpacing(6)

        hdr_layout = QHBoxLayout()
        hdr_layout.setContentsMargins(0, 0, 0, 0)
        hdr_layout.setSpacing(8)

        user_name = _resolve_user_name(getattr(self, "chat_app", None))
        name = user_name if is_user else "Cel"
        self.name_lbl = QLabel(name)
        name_lbl = self.name_lbl
        name_lbl.setStyleSheet("font-weight: bold; font-size: 11px; color: #C084FC; border: none; background: transparent;")

        # Circular profile picture: yours on your bubbles (right side), Cel's
        # on hers. With no picture on disk it degrades to a gradient disc with
        # the display initial, so a fresh install never shows an empty hole.
        self.avatar_lbl = CircularAvatarLabel(
            who="user" if is_user else "cel",
            diameter=26,
            fallback_text=_bubble_avatar_initial(
                is_user, getattr(self, "chat_app", None)))
        self.avatar_lbl.clicked.connect(self._on_avatar_clicked)
        hdr_layout.addWidget(self.avatar_lbl)

        time_str = self.meta.get("time", datetime.now().strftime("%H:%M"))
        time_lbl = QLabel(time_str)
        time_lbl.setStyleSheet("font-size: 10px; color: #7C6F98; border: none; background: transparent;")

        hdr_layout.addWidget(name_lbl)
        hdr_layout.addWidget(time_lbl)

        if self.is_ghost:
            ghost_badge = QLabel("🛑 [Stopped]")
            ghost_badge.setStyleSheet("font-size: 10px; font-weight: bold; color: #F87171; border: none;")
            hdr_layout.addWidget(ghost_badge)

        hdr_layout.addStretch()

        btn_style = "QPushButton { background: transparent; border: none; border-radius: 4px; } QPushButton:hover { background: rgba(147, 51, 234, 0.35); }"

        btn_eye = QPushButton()
        btn_eye.setIcon(QIcon(str(ASSETS_DIR / "eye_closed.svg")))
        btn_eye.setIconSize(QSize(15, 15))
        btn_eye.setFixedSize(26, 22)
        btn_eye.setToolTip("👁 Toggle raw source / rendered markdown")
        btn_eye.setStyleSheet(btn_style)
        btn_eye.clicked.connect(self._toggle_eye_mode)
        self.btn_eye = btn_eye
        hdr_layout.addWidget(btn_eye)

        if is_user:
            btn_copy = QPushButton()
            btn_copy.setIcon(QIcon(str(ASSETS_DIR / "copy.png")))
            btn_copy.setIconSize(QSize(15, 15))
            btn_copy.setFixedSize(26, 22)
            btn_copy.setToolTip("Copy message to clipboard")
            btn_copy.setStyleSheet(btn_style)
            btn_copy.clicked.connect(lambda: (
                QApplication.clipboard().setText(self.content),
                self.chat_app.show_toast("Copied to clipboard! 📋", icon="📋") if self.chat_app else None
            ))
            hdr_layout.addWidget(btn_copy)

            btn_edit = QPushButton()
            btn_edit.setIcon(QIcon(str(ASSETS_DIR / "edit.png")))
            btn_edit.setIconSize(QSize(15, 15))
            btn_edit.setFixedSize(26, 22)
            btn_edit.setToolTip("Edit message and regenerate")
            btn_edit.setStyleSheet(btn_style)
            btn_edit.clicked.connect(self._on_user_edit)
            hdr_layout.addWidget(btn_edit)

            self.retry_slider = SlideToRetry()
            self.retry_slider.triggered.connect(self._on_retry)
            hdr_layout.addWidget(self.retry_slider)
        else:
            self.btn_info = QPushButton("✨ Info")
            self.btn_info.setMinimumWidth(62)
            self.btn_info.setFixedHeight(22)
            self.btn_info.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            self.btn_info.setToolTip("✨ View token statistics, generation speed & model capabilities")
            self.btn_info.setStyleSheet("QPushButton { background: rgba(138, 43, 226, 0.25); border: 1px solid rgba(192, 132, 252, 0.35); border-radius: 5px; padding: 1px 8px; font-size: 10px; font-weight: bold; color: #E9D5FF; } QPushButton:hover { background: rgba(138, 43, 226, 0.55); color: #FFFFFF; }")
            self.btn_info.clicked.connect(self.toggle_info_card)
            hdr_layout.addWidget(self.btn_info)

            self.btn_tts = QPushButton()
            self.btn_tts.setIcon(QIcon(str(ASSETS_DIR / "tts.png")))
            self.btn_tts.setIconSize(QSize(16, 16))
            self.btn_tts.setFixedSize(26, 22)
            self.btn_tts.setToolTip("Speak with TTS (Kokoro / Edge)")
            self.btn_tts.setStyleSheet(btn_style)
            self.btn_tts.clicked.connect(self._trigger_tts)
            hdr_layout.addWidget(self.btn_tts)

            btn_copy = QPushButton()
            btn_copy.setIcon(QIcon(str(ASSETS_DIR / "copy.png")))
            btn_copy.setIconSize(QSize(15, 15))
            btn_copy.setFixedSize(26, 22)
            btn_copy.setToolTip("Copy message to clipboard")
            btn_copy.setStyleSheet(btn_style)
            btn_copy.clicked.connect(lambda: (
                QApplication.clipboard().setText(self.content),
                self.chat_app.show_toast("Copied to clipboard! 📋", icon="📋") if self.chat_app else None
            ))
            hdr_layout.addWidget(btn_copy)

            btn_edit = QPushButton()
            btn_edit.setIcon(QIcon(str(ASSETS_DIR / "edit.png")))
            btn_edit.setIconSize(QSize(15, 15))
            btn_edit.setFixedSize(26, 22)
            btn_edit.setToolTip("Edit Cel's message in-place")
            btn_edit.setStyleSheet(btn_style)
            btn_edit.clicked.connect(self._on_user_edit)
            hdr_layout.addWidget(btn_edit)

            btn_branch = QPushButton()
            btn_branch.setIcon(QIcon(str(ASSETS_DIR / "branch.png")))
            btn_branch.setIconSize(QSize(16, 16))
            btn_branch.setFixedSize(26, 22)
            btn_branch.setToolTip("Branch conversation from this point into a new chat session")
            btn_branch.setStyleSheet(btn_style)
            btn_branch.clicked.connect(self._on_branch)
            hdr_layout.addWidget(btn_branch)

        self.layout_v.addLayout(hdr_layout)

        if self.attached_images:
            for img_path in self.attached_images:
                if os.path.exists(img_path):
                    pix = QPixmap(img_path)
                    if not pix.isNull():
                        img_lbl = QLabel()
                        scaled = pix.scaledToWidth(min(380, pix.width()), Qt.TransformationMode.SmoothTransformation)
                        img_lbl.setPixmap(scaled)
                        img_lbl.setStyleSheet("border-radius: 10px; border: 1px solid rgba(255,255,255,0.1);")
                        self.layout_v.addWidget(img_lbl)

        if self.attached_files:
            for f_info in self.attached_files:
                f_card = QFrame()
                f_card.setStyleSheet("background: rgba(0,0,0,0.35); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px;")
                f_h = QHBoxLayout(f_card)
                f_h.setContentsMargins(8, 6, 8, 6)
                f_lbl = QLabel(f"📄 {f_info.get('name', 'File')} ({f_info.get('size_str', '')})")
                f_lbl.setStyleSheet("font-size: 11px; color: #81C784; font-weight: bold; border: none;")
                f_h.addWidget(f_lbl)
                self.layout_v.addWidget(f_card)

        display_text = self.content
        if is_user and display_text.startswith("Name - "):
            display_text = display_text.split("Prompt - ", 1)[-1]

        if not is_user and not display_text and getattr(self, "is_live", False):
            model_name = self.meta.get("model", "")
            provider_name = ""
            if self.chat_app and hasattr(self.chat_app, "settings"):
                provider_name = self.chat_app.settings.get("selected_provider", "")
            self.thinking_card = ThinkingCard(provider=provider_name, model_name=model_name, parent=self)
            self.layout_v.addWidget(self.thinking_card)
        elif not is_user and not display_text:
            # History-loaded empty (interrupted turn): a static note, never
            # a live "analyzing..." card in a chat the user never sent to.
            _stop_lbl = QLabel("(interrupted - no reply text)")
            _stop_lbl.setStyleSheet("color: rgba(233,213,255,0.45); font-size: 11px; font-style: italic; border: none; background: transparent;")
            self.layout_v.addWidget(_stop_lbl)
        else:
            # Parse <think>...</think> blocks for Antigravity-style collapsible
            # thoughts - EVERY block is collected, never rendered as body text.
            from cellium.core.utils import split_think
            display_text, _init_thoughts = split_think(display_text)
            if _init_thoughts:
                _tc = "\n\n - \n\n".join(_init_thoughts)
                if len(_tc) > 4000:
                    _tc = _tc[:4000] + "\n\n…(thought truncated for display)"
                thought_card = ThoughtAccordionCard(_tc, parent=self)
                self.layout_v.addWidget(thought_card)

            # Parse agent actions: collect all tool calls into an Antigravity-style unified workflow tray
            pattern = r'<agent_action tool="([^"]+)" args="([^"]+)" status="([^"]+)"(?: diff="([^"]*)")?>(.*?)</agent_action>'
            matches = list(re.finditer(pattern, display_text, flags=re.DOTALL))
            if matches:
                # Extract conversational text by stripping agent_action tags
                clean_conv_text = re.sub(pattern, '', display_text, flags=re.DOTALL).strip()
                
                tool_items = []
                for m in matches:
                    t_name = m.group(1)
                    a_str = m.group(2)
                    st = m.group(3)
                    d_str = m.group(4)
                    res = m.group(5)
                    try:
                        args = json.loads(html.unescape(a_str))
                    except Exception:
                        args = {"args": a_str}
                    tool_items.append((t_name, args, st, html.unescape(res), html.unescape(d_str) if d_str else None))
                
                # Render unified Antigravity workflow tray
                agent_tray = AntigravityAgentWorkflow(tool_items, parent=self)
                self.layout_v.addWidget(agent_tray)
                
                # Render conversational answer cleanly separated below agent workflow
                if clean_conv_text:
                    self._render_normal_content(clean_conv_text, is_user)
            else:
                self._render_normal_content(display_text, is_user)

        self.adjustSize()
        self.updateGeometry()

    def _render_normal_content(self, display_text, is_user):
        # Detect image URLs in assistant messages (Gemini often returns image links)
        image_urls = self._extract_image_urls(display_text)
        text_for_display = display_text
        if text_for_display and not is_user:
            from cellium.core.utils import split_mood_first, strip_inline_mood_display
            text_for_display = strip_inline_mood_display(split_mood_first(text_for_display)[0])
        for url in image_urls:
            text_for_display = text_for_display.replace(url, "").strip()
        
        self._body_sources = []
        parts = text_for_display.split("```")
        for idx, part in enumerate(parts):
            if idx % 2 == 0:
                clean_chunk = part.strip()
                if clean_chunk:
                    txt_lbl = ChatBubbleBody(self._body_html(clean_chunk), self)
                    self.layout_v.addWidget(txt_lbl)
                    if not self.isHidden():
                        txt_lbl.show()
                    self._body_sources.append((txt_lbl, clean_chunk))
                    if self.body_label is None:
                        self.body_label = txt_lbl
            else:
                lines = part.split("\n", 1)
                lang = lines[0].strip() or "code"
                code_body = lines[1] if len(lines) > 1 else ""
                card = CodeBlockCard(lang, code_body, self)
                self.layout_v.addWidget(card)
                if not self.isHidden():
                    card.show()
        
        # Add image previews for detected URLs
        if image_urls and not is_user:
            for url in image_urls:
                self._add_image_preview(url)

    def _extract_image_urls(self, text):
        """Extract image URLs from text (Gemini, etc.)"""
        import re
        # Match common image URL patterns
        url_pattern = r'https?://[^\s\)\]\}]+\.(?:png|jpg|jpeg|gif|webp|bmp|svg)(?:\?[^\s\)\]\}]*)?'
        urls = re.findall(url_pattern, text, re.IGNORECASE)
        # Also match markdown image syntax ![alt](url)
        md_pattern = r'!\[.*?\]\((https?://[^\s\)]+)\)'
        urls.extend(re.findall(md_pattern, text, re.IGNORECASE))
        # Deduplicate
        return list(dict.fromkeys(urls))

    def _add_image_preview(self, url):
        """Add an image preview widget for a URL"""
        img_lbl = QLabel()
        img_lbl.setStyleSheet("border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background: rgba(0,0,0,0.3);")
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_lbl.setMinimumHeight(120)
        img_lbl.setMaximumWidth(380)
        
        # Show loading placeholder
        img_lbl.setText("📷 Loading image...")
        img_lbl.setStyleSheet(img_lbl.styleSheet() + " color: #888; font-size: 12px;")
        
        # Load image asynchronously. Delivery is a queued Signal, NOT
        # QTimer.singleShot: the loader runs in a threading.Thread with no Qt
        # event loop, so a singleShot posted there never fires (previews stuck
        # on "Loading..." forever), and the error-path lambda read a dead `e`
        # (NameError - `except ... as e` is deleted on block exit). Decoding
        # to QImage off-thread is safe; the slot converts to QPixmap in GUI.
        def _emit(label, img, url, err=""):
            try:
                self._image_loaded.emit(label, img, url, err)
            except RuntimeError:
                pass  # bubble died while the download was in flight

        def load_image():
            try:
                import urllib.request
                req = urllib.request.Request(url, headers={'User-Agent': 'CelStudio/1.0'})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                from PySide6.QtGui import QImage
                img = QImage()
                ok = img.loadFromData(data)
                if ok and not img.isNull():
                    img = img.scaledToWidth(min(380, img.width()), Qt.TransformationMode.SmoothTransformation)
                    _emit(img_lbl, img, url)
                else:
                    _emit(img_lbl, None, url)
            except Exception as e:
                _emit(img_lbl, None, url, str(e))

        try:
            self._image_loaded.connect(
                self._schedule_image_preview,
                Qt.ConnectionType.UniqueConnection)
        except (RuntimeError, TypeError):
            pass
        import threading
        threading.Thread(target=load_image, daemon=True).start()
        self.layout_v.addWidget(img_lbl)

    def _schedule_image_preview(self, label, pixmap, url, error=None):
        """Slot for the queued image signal (always runs in the GUI thread)."""
        try:
            from PySide6.QtGui import QImage, QPixmap
            if isinstance(pixmap, QImage):
                pixmap = QPixmap.fromImage(pixmap)
        except Exception:
            pass
        self._update_image_preview(label, pixmap, url, error)

    def _update_image_preview(self, label, pixmap, url, error=None):
        try:
            if not label or label.isHidden() or not label.isVisible():
                pass
            if pixmap and not pixmap.isNull():
                label.setPixmap(pixmap)
                label.setText("")
                label.setStyleSheet("border-radius: 10px; border: 1px solid rgba(255,255,255,0.1);")
                # Make clickable for full-screen view
                label.mousePressEvent = lambda e: self._show_fullscreen_image(pixmap, url)
                label.setCursor(Qt.CursorShape.PointingHandCursor)
                label.setToolTip(f"Click to view full-size\n{url}")
            else:
                label.setText(f"📷 Failed to load image\n{url}")
                label.setStyleSheet(label.styleSheet() + " color: #F87171; font-size: 11px;")
        except (RuntimeError, Exception):
            pass

    def _show_fullscreen_image(self, pixmap, url):
        """Show image in full-screen modal"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
        dialog = QDialog(self)
        dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dialog.setStyleSheet("background: rgba(0, 0, 0, 0.95);")
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        
        img_label = QLabel()
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Scale to fit screen
        screen = QApplication.primaryScreen().geometry()
        max_w = int(screen.width() * 0.9)
        max_h = int(screen.height() * 0.9)
        scaled = pixmap.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        img_label.setPixmap(scaled)
        layout.addWidget(img_label)
        
        # Close button
        btn_close = QPushButton("Close")
        btn_close.setIcon(QIcon(str(ASSETS_DIR / "icons" / "ui_x.svg")))
        btn_close.setIconSize(QSize(14, 14))
        btn_close.setFixedHeight(40)
        btn_close.setStyleSheet("""
            QPushButton {
                background: rgba(147, 51, 234, 0.7);
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover { background: #9333EA; }
        """)
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignCenter)
        
        dialog.exec()

    def _on_user_edit(self):
        if self.chat_app:
            self.chat_app.enter_edit_mode(self)

    def _on_retry(self):
        if self.chat_app:
            self.chat_app.retry_message(self)

    def _on_branch(self):
        if self.chat_app:
            self.chat_app.branch_chat_at(self)

    def _trigger_tts(self):
        main_win = self.chat_app
        if not main_win:
            return

        # Toggle stop if this bubble is already playing
        if getattr(main_win, "active_tts_bubble", None) is self:
            main_win.stop_current_tts()
            return

        # If another bubble is speaking, halt it first
        if getattr(main_win, "active_tts_bubble", None) is not None:
            main_win.stop_current_tts()

        skip_asterisks = bool(main_win.settings.get("tts_skip_asterisks", True))
        speak_text = clean_for_tts(self.content, skip_asterisks=skip_asterisks)
        if not speak_text:
            main_win.show_toast("No speakable text found!", icon="⚠️")
            return

        voice_host = main_win.settings.get("voice_host", "Kokoro (Offline)")
        selected_voice = main_win.settings.get("tts_voice", "af_heart" if voice_host == "Kokoro (Offline)" else "en-US-JennyNeural")

        main_win.active_tts_bubble = self
        if hasattr(self, "btn_tts") and self.btn_tts:
            self.btn_tts.setIcon(QIcon())
            self.btn_tts.setText("⏹")
            self.btn_tts.setToolTip("Stop audio playback")
            self.btn_tts.setStyleSheet("""
                QPushButton {
                    background: rgba(239, 68, 68, 0.7);
                    color: #FFFFFF;
                    border: 1.5px solid #EF4444;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover { background: #DC2626; }
            """)

        if not hasattr(main_win, "_tts_threads"):
            main_win._tts_threads = set()

        # Properly parent QThread to main window to prevent garbage collector destroying running C++ thread
        thread = QThread(main_win)
        main_win._tts_threads.add(thread)

        def _on_finished():
            if hasattr(self, "btn_tts") and self.btn_tts:
                self.btn_tts.setText("")
                self.btn_tts.setIcon(QIcon(str(ASSETS_DIR / "tts.png")))
                self.btn_tts.setIconSize(QSize(16, 16))
                self.btn_tts.setToolTip("Speak with TTS (Kokoro / Edge)")
                self.btn_tts.setStyleSheet("""
                    QPushButton { background: transparent; border: none; border-radius: 4px; padding: 2px; }
                    QPushButton:hover { background: rgba(147, 51, 234, 0.3); }
                """)
            if getattr(main_win, "active_tts_bubble", None) is self:
                main_win.active_tts_bubble = None
                main_win.active_tts_worker = None
            # TTS end re-measures the bubble: the finished-talking narrow
            # wrap came from a stale fixed width. Queued to the GUI thread.
            try:
                from PySide6.QtCore import QTimer as _QTimer
                _fn = getattr(main_win, "update_all_bubble_geometries", None)
                if callable(_fn):
                    _QTimer.singleShot(0, _fn)
            except Exception:
                pass

        if voice_host == "Edge TTS (Online)":
            main_win.show_toast("Edge TTS online audio started...", icon="🔊")
            worker = EdgeTTSStreamingWorker(speak_text, voice=selected_voice, volume=tts_gain_from_settings(main_win.settings))
        else:
            main_win.show_toast("Kokoro offline audio stream started...", icon="🔊")
            worker = KokoroStreamingWorker(speak_text, voice=selected_voice, speed=1.0, volume=tts_gain_from_settings(main_win.settings))

        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(_on_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: main_win._tts_threads.discard(thread))
        thread.finished.connect(thread.deleteLater)

        main_win.active_tts_worker = worker
        main_win.active_tts_thread = thread
        thread.start()

    def toggle_info_card(self):
        if not self.info_card:
            self.info_card = QFrame(self)
            self.info_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            z = float(getattr(self.chat_app, "zoom_level", 1.0) or 1.0) if self.chat_app else 1.0
            info_px = max(10, int(round(11 * z)))
            self.info_card.setStyleSheet(
                f"QFrame {{ background: rgba(14, 10, 24, 0.95); border: 1.5px solid #9333EA; border-radius: 8px; }} "
                f"QLabel {{ color: #E9D5FF; font-size: {info_px}px; border: none; background: transparent; padding: 0px; margin: 0px; }}"
            )
            inf_v = QVBoxLayout(self.info_card)
            inf_v.setContentsMargins(12, 8, 12, 8)
            inf_v.setSpacing(3)

            model_name = self.meta.get("model") or "Cerebras Fast Cloud"
            if is_offline_model_key(model_name):
                model_name = strip_offline_label(model_name)
            turn_tokens = self.meta.get("turn_tokens", 0)
            think_time = self.meta.get("think_time", 0.0)
            speed = f"{turn_tokens / max(0.01, think_time):.1f}" if think_time else " - "

            # ── Real capability detection: ask the provider catalog / GGUF
            # metadata what the model can actually support, instead of
            # defaulting every model to plain text. ────────────────────────
            raw_model_name = self.meta.get("model") or "Cerebras Fast Cloud"
            route = (self.chat_app.models.get(raw_model_name) if self.chat_app else {}) or {}
            if not isinstance(route, dict):
                route = {}
            # Resolve the GGUF path for offline models (route value is just
            # the string "offline-model", so look it up in settings).
            model_path = str(route.get("path", "") or route.get("model_path", "") or "")
            if not model_path and self.chat_app and is_offline_model_key(raw_model_name):
                for _nm, _p in (self.chat_app.settings.get("offline_models", {}) or {}).items():
                    if strip_offline_label(_nm) == model_name:
                        model_path = _p
                        break
            caps = get_model_capabilities(
                raw_model_name,
                self.chat_app.models if self.chat_app else {},
                self.chat_app.settings if self.chat_app else {},
                details_cache=getattr(self.chat_app, "_model_details_cache", {}),
                model_path=model_path,
            )
            cap_str = caps["cap_str"]
            files_str = caps["files"]

            words = len(self.content.split())
            letters = len(self.content)
            session_total = self.meta.get(
                "session_total_tokens",
                getattr(self.chat_app, "total_tokens", 0) if self.chat_app else 0,
            )
            for lbl_text in [
                f"🏷️ Model: <b>{model_name}</b>",
                f"✨ Capabilities: <b>{cap_str}</b>  <span style='color:#94A3B8;'>(via {caps.get('source','heuristic')})</span>",
                f"📂 Files Supported: <b>{files_str}</b>",
                f"🍪 Tokens (this turn): <b>{turn_tokens:,}</b>",
                f"💬 Total tokens in this chat: <b>{int(session_total):,}</b>",
                f"⏱️ Think Time: <b>{think_time}s</b>",
                f"⚡ Speed: <b>{speed} tok/s</b>",
                f"📝 Words: <b>{words:,}</b>  •  Letters: <b>{letters:,}</b>",
            ]:
                lbl = QLabel(lbl_text, self.info_card)
                lbl.setTextFormat(Qt.TextFormat.RichText)
                lbl.setWordWrap(True)
                lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                inf_v.addWidget(lbl)
                lbl.show()

            self.layout_v.addWidget(self.info_card)
            self.info_card.show()
            self.info_expanded = True
            self.btn_info.setText("🔼 Info")
        else:
            self.info_expanded = not self.info_expanded
            self.info_card.setVisible(self.info_expanded)
            self.btn_info.setText("🔼 Info" if self.info_expanded else "✨ Info")

        # Reflow only THIS bubble. A global reflow walks every bubble in the
        # chat and was measured at ~230 ms on a 42-bubble conversation - that
        # is what made opening ✦ Info feel like a freeze.
        try:
            self.update_dynamic_width(
                getattr(self, "max_allowed_w", 0) or self.width())
            if self.chat_app and hasattr(self.chat_app, "chat_layout"):
                self.chat_app.chat_layout.invalidate()
                self.chat_app.chat_layout.activate()
            if self.chat_app and hasattr(self.chat_app, "scroll_bottom"):
                self.chat_app.scroll_bottom(force=False)
        except Exception:
            self.setFixedHeight(self.heightForWidth(self.width()))
            self.updateGeometry()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = 16.0
        rect = QRectF(1.5, 1.5, w - 3.0, h - 3.0)
        path = QPainterPath()

        r = 24.0 # ultra soft radius
        if self.role == "user":
            path.addRoundedRect(rect, r, r)
            bg = QColor(48, 30, 74, int(self.glass_opacity * 255)) # Violet-tinted liquid glass
            border = QColor(192, 132, 252, 28)
        else:
            path.addRoundedRect(rect, r, r)
            if self.is_ghost:
                bg = QColor(34, 22, 56, 130)
                border = QColor(192, 132, 252, 20)
            else:
                bg = QColor(18, 12, 34, int(min(0.9, self.glass_opacity) * 255)) # Violet glass assistant background
                border = QColor(192, 132, 252, 26)

        painter.setBrush(QBrush(bg))
        if border.alpha() > 0:
            painter.setPen(QPen(border, 1.0))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)
        painter.end()
 
# ------------------------------------------------------------------ Main Window


# ── #10: Dual Top & Bottom Bookmark Info Drawer + ThinkingCard & ToolCallCard Fixes ──
from PySide6.QtCore import QEasingCurve, QSize, QVariantAnimation
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QAbstractButton, QTextEdit
from cellium.core.svg_icons import get_svg_icon, iconify_button

# A. Fix `ThinkingCard` duplicate brain emoji (`🧠 🧠`) & text clipping (`Local GGUF reading 729 t`)!
if "ThinkingCard" in globals():
    _orig_tc_init = ThinkingCard.__init__
    _orig_tc_set_status = getattr(ThinkingCard, "set_status", None)

    def _patched_tc_init(self, *args, **kwargs):
        _orig_tc_init(self, *args, **kwargs)
        # Hide duplicate leading icon label if self.lbl already shows an icon/emoji, or replace with clean SVG
        for ch_lbl in self.findChildren(QLabel):
            if ch_lbl is not getattr(self, "lbl", None) and "🧠" in (ch_lbl.text() or ""):
                ch_lbl.hide()
        if hasattr(self, "lbl") and self.lbl is not None:
            self.lbl.setMinimumWidth(260)
        self.setMinimumWidth(370)

    def _patched_tc_set_status(self, text: str) -> None:
        clean_t = re.sub(r"^(?:[🧠✨⏳🤖💭]+\s*)+", "", str(text or "").strip())
        disp = f"🧠 {clean_t}" if clean_t else "🧠 Thinking…"
        if _orig_tc_set_status is not None:
            _orig_tc_set_status(self, disp)
        elif hasattr(self, "lbl") and self.lbl is not None:
            self.lbl.setText(disp)
        if hasattr(self, "lbl") and self.lbl is not None:
            fm = QFontMetrics(self.lbl.font())
            needed_lbl_w = fm.horizontalAdvance(self.lbl.text()) + 28
            self.lbl.setMinimumWidth(max(220, needed_lbl_w))
            needed_card_w = needed_lbl_w + 115
            self.setMinimumWidth(max(350, min(680, needed_card_w)))
            self.adjustSize()
            p = self.parentWidget()
            while p is not None:
                if hasattr(p, "update_dynamic_width") and hasattr(p, "max_allowed_w"):
                    try:
                        p.update_dynamic_width(max(p.max_allowed_w, self.minimumWidth() + 36))
                    except Exception:
                        pass
                    break
                p = p.parentWidget()

    ThinkingCard.__init__ = _patched_tc_init
    ThinkingCard.set_status = _patched_tc_set_status


# B. Fix `ToolCallCard` INPUT / OUTPUT vertical clipping (`{` and `True` cut off in Screenshot 5)!
if "ToolCallCard" in globals():
    _orig_tcc_init = ToolCallCard.__init__

    def _patched_tcc_init(self, *args, **kwargs):
        _orig_tcc_init(self, *args, **kwargs)
        for te in self.findChildren(QTextEdit):
            if te.height() < 52:
                te.setMinimumHeight(54)
        for btn in self.findChildren(QAbstractButton):
            iconify_button(btn)

    ToolCallCard.__init__ = _patched_tcc_init


# C. #10 Dual Top & Bottom Bookmark Info Drawer with Exact 0px-Drift Collapse Height!
_orig_mb_init_v10 = MessageBubbleNew.__init__
_orig_mb_toggle_info_v10 = MessageBubbleNew.toggle_info_card
_orig_mb_update_width_v10 = MessageBubbleNew.update_dynamic_width


def _patched_mb_init_v10(self, *args, **kwargs):
    _orig_mb_init_v10(self, *args, **kwargs)
    self._info_anchor = None
    self._info_open = False
    self._info_drawer_h = 0
    self._info_anim = None

    for b_child in self.findChildren(QAbstractButton):
        iconify_button(b_child)

    if getattr(self, "role", "") != "user" and hasattr(self, "btn_info"):
        try:
            self.btn_info.clicked.disconnect()
        except Exception:
            pass
        self.btn_info.setIcon(get_svg_icon("sparkles"))
        self.btn_info.setIconSize(QSize(14, 14))
        self.btn_info.setText("Info")
        self.btn_info.clicked.connect(lambda _=False: self.toggle_info_card("top"))

        self.bookmark_wrap = QWidget(self)
        self.bookmark_wrap.setObjectName("InfoBookmarkWrap")
        self.bookmark_wrap.setFixedHeight(26)
        self.bookmark_wrap.setStyleSheet("background: transparent; border: none;")
        bm_lay = QHBoxLayout(self.bookmark_wrap)
        bm_lay.setContentsMargins(12, 0, 14, 0)
        bm_lay.setSpacing(0)
        bm_lay.addStretch(1)

        self.btn_info_bottom = QPushButton("Info", self.bookmark_wrap)
        self.btn_info_bottom.setIcon(get_svg_icon("bookmark"))
        self.btn_info_bottom.setIconSize(QSize(14, 14))
        self.btn_info_bottom.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_info_bottom.setFixedHeight(24)
        self.btn_info_bottom.setMinimumWidth(86)
        self.btn_info_bottom.setToolTip("Slide open token stats & model info right here at the bottom")
        self.btn_info_bottom.setStyleSheet(
            "QPushButton {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(76, 29, 149, 0.92), stop:1 rgba(147, 51, 234, 0.98));"
            "  color: #F3E8FF;"
            "  border: 1px solid rgba(216, 180, 254, 0.65);"
            "  border-top: 1px solid rgba(216, 180, 254, 0.20);"
            "  border-top-left-radius: 3px;"
            "  border-top-right-radius: 3px;"
            "  border-bottom-left-radius: 10px;"
            "  border-bottom-right-radius: 10px;"
            "  padding: 2px 12px;"
            "  font-size: 11px;"
            "  font-weight: bold;"
            "}"
            "QPushButton:hover {"
            "  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(107, 33, 168, 0.98), stop:1 rgba(168, 85, 247, 1.0));"
            "  color: #FFFFFF;"
            "  border-color: #F5D0FE;"
            "}"
        )
        self.btn_info_bottom.clicked.connect(lambda _=False: self.toggle_info_card("bottom"))
        bm_lay.addWidget(self.btn_info_bottom)

        if self.layout() is not None:
            self.layout().addWidget(self.bookmark_wrap)


def _sync_info_buttons_ui(self) -> None:
    is_open = bool(getattr(self, "_info_open", False))
    anchor = getattr(self, "_info_anchor", None)
    if hasattr(self, "btn_info") and self.btn_info is not None:
        self.btn_info.setIcon(get_svg_icon("bookmark_up" if (is_open and anchor == "top") else "sparkles"))
        self.btn_info.setText("Info")
    if hasattr(self, "btn_info_bottom") and self.btn_info_bottom is not None:
        self.btn_info_bottom.setIcon(get_svg_icon("bookmark_up" if (is_open and anchor == "bottom") else "bookmark"))
        self.btn_info_bottom.setText("Info")


def _position_info_card_in_layout(self, anchor: str) -> None:
    lay = self.layout()
    card = getattr(self, "info_card", None)
    if lay is None or card is None:
        return
    lay.removeWidget(card)
    if anchor == "top":
        lay.insertWidget(1, card)
    else:
        bm = getattr(self, "bookmark_wrap", None)
        if bm is not None:
            bm_idx = lay.indexOf(bm)
            if bm_idx >= 0:
                lay.insertWidget(bm_idx, card)
            else:
                lay.addWidget(card)
        else:
            lay.addWidget(card)


def _measure_full_info_card_h(self) -> int:
    card = getattr(self, "info_card", None)
    if card is None:
        return 148
    w_in = max(220, self.width() - 28)
    card.setFixedWidth(w_in)
    if card.layout() is not None:
        card.layout().invalidate()
        card.layout().activate()
    return int(min(210, max(125, card.sizeHint().height())))


def _reflow_bubble_for_drawer(self) -> None:
    max_w = getattr(self, "max_allowed_w", 0) or max(420, self.width())
    self.update_dynamic_width(max_w)
    if getattr(self, "chat_app", None) is not None and hasattr(self.chat_app, "update_all_bubble_geometries"):
        try:
            self.chat_app.update_all_bubble_geometries()
        except Exception:
            pass


def _patched_mb_toggle_info_v10(self, anchor: str = "top", animate: bool | None = None) -> None:
    if isinstance(anchor, bool) or anchor not in ("top", "bottom"):
        anchor = "top"

    if getattr(self, "info_card", None) is None:
        _orig_mb_toggle_info_v10(self)
        if getattr(self, "info_card", None) is not None:
            self.layout().removeWidget(self.info_card)
            self.info_card.hide()
            self._info_open = False
            if hasattr(self, "show_info"):
                self.show_info = False

    card = getattr(self, "info_card", None)
    if card is None:
        return

    try:
        play_ui_sound("pop", 0.38)
    except Exception:
        pass

    was_open = bool(getattr(self, "_info_open", False)) and (not card.isHidden())
    prev_anchor = getattr(self, "_info_anchor", None)

    old_anim = getattr(self, "_info_anim", None)
    if old_anim is not None:
        try:
            old_anim.stop()
            old_anim.deleteLater()
        except Exception:
            pass
        self._info_anim = None

    if was_open and prev_anchor == anchor:
        want_open = False
    else:
        want_open = True
        self._info_anchor = anchor
        _position_info_card_in_layout(self, anchor)

    self._info_open = want_open
    if hasattr(self, "show_info"):
        self.show_info = want_open
    _sync_info_buttons_ui(self)

    full_h = _measure_full_info_card_h(self)
    if animate is None:
        animate = (os.environ.get("QT_QPA_PLATFORM", "") != "offscreen")

    if not animate:
        if want_open:
            self._info_drawer_h = full_h
            card.setFixedHeight(full_h)
            card.setVisible(True)
            card.show()
        else:
            self._info_drawer_h = 0
            # Remove from layout when closed so update_dynamic_width never counts a hidden info_card!
            if self.layout() is not None:
                self.layout().removeWidget(card)
            card.setVisible(False)
            card.hide()
        _reflow_bubble_for_drawer(self)
        return

    start_h = (0 if (not was_open or prev_anchor != anchor) else max(10, card.height())) if want_open else max(10, card.height() or full_h)
    end_h = full_h if want_open else 0

    if want_open:
        self._info_drawer_h = max(12, start_h)
        card.setFixedHeight(self._info_drawer_h)
        card.setVisible(True)
        card.show()

    anim = QVariantAnimation(self)
    anim.setDuration(185)
    anim.setStartValue(int(start_h))
    anim.setEndValue(int(end_h))
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _on_step(val):
        h_now = int(val)
        self._info_drawer_h = h_now
        card.setFixedHeight(max(0, h_now))
        _reflow_bubble_for_drawer(self)

    def sizeHint(self):
        hint = super().sizeHint()
        if getattr(self, '_thinking_active', False) or getattr(self, '_is_thinking', False):
            hint.setWidth(hint.width() + 48) # Extra space for stars/dots
        return hint

    def _on_finished():
        if not self._info_open:
            self._info_drawer_h = 0
            if self.layout() is not None:
                self.layout().removeWidget(card)
            card.setVisible(False)
            card.hide()
        else:
            self._info_drawer_h = full_h
            card.setFixedHeight(full_h)
        _reflow_bubble_for_drawer(self)

    anim.valueChanged.connect(_on_step)
    anim.finished.connect(_on_finished)
    self._info_anim = anim
    anim.start()


def _patched_mb_update_width_v10(self, max_w: int) -> None:
    card = getattr(self, "info_card", None)
    is_open = bool(getattr(self, "_info_open", False)) and card is not None and (not card.isHidden())
    if hasattr(self, "show_info"):
        self.show_info = is_open
    if not is_open and card is not None and self.layout() is not None:
        self.layout().removeWidget(card)
    _orig_mb_update_width_v10(self, max_w)
    bm = getattr(self, "bookmark_wrap", None)
    if bm is not None and not bm.isHidden():
        self.setFixedHeight(max(58, self.height() + bm.height() + 4))


MessageBubbleNew.__init__ = _patched_mb_init_v10
MessageBubbleNew.toggle_info_card = _patched_mb_toggle_info_v10
MessageBubbleNew.update_dynamic_width = _patched_mb_update_width_v10


# ── #26: Expandable & Drag-Resizable Agent ToolCallCard (`shell_exec` & Tools) ──
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget


class _ToolCardResizer(QWidget):
    """Draggable bottom resize handle for Agent `ToolCallCard` (matches `CodeBlockResizer`)."""
    def __init__(self, card: QFrame):
        super().__init__(card)
        self._card = card
        self._dragging = False
        self._start_y = 0
        self._start_out_h = 0
        self.setFixedHeight(10)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip("Drag up or down to resize Agent tool output")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(168, 85, 247, 135))
        painter.drawRoundedRect(int((w - 36) * 0.5), 4, 36, 3, 1.5, 1.5)
        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            self._start_y = pos.y()
            out_ed = getattr(self._card, "_out_editor", None)
            self._start_out_h = out_ed.height() if out_ed is not None else 110
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            return
        pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
        dy = pos.y() - self._start_y
        new_h = max(56, min(680, self._start_out_h + dy))
        self._card.set_output_box_height(new_h)
        event.accept()

    def mouseReleaseEvent(self, _event) -> None:
        self._dragging = False


def _attach_expand_and_resizer_to_tool_card(card: QFrame) -> None:
    """Attach `↕ Expand` button + bottom `_ToolCardResizer` to any Agent tool card instance."""
    if getattr(card, "_v26_expand_wired", False):
        return
    card._v26_expand_wired = True
    card._is_expanded_full = False

    editors = card.findChildren(QTextEdit)
    card._in_editor = editors[0] if len(editors) >= 1 else None
    card._out_editor = editors[-1] if len(editors) >= 2 else (editors[0] if editors else None)

    # Label-only cards (normal AgentToolCard payloads) have NOTHING the size
    # toggle could resize - skip the whole #26 cluster instead of adding a
    # dead "↕ Expand" button and a drag bar that silently does nothing.
    if card._in_editor is None and card._out_editor is None:
        return

    if card._in_editor is not None:
        in_lines = max(2, (card._in_editor.toPlainText() or "").count("\n") + 1)
        card._in_editor.setFixedHeight(min(150, max(54, in_lines * 19 + 18)))

    if card._out_editor is not None:
        out_lines = max(2, (card._out_editor.toPlainText() or "").count("\n") + 1)
        card._compact_out_h = min(160, max(58, out_lines * 18 + 18))
        card._expanded_out_h = min(560, max(260, out_lines * 19 + 28))
        card._out_editor.setFixedHeight(card._compact_out_h)
    else:
        card._compact_out_h = 110
        card._expanded_out_h = 340

    card.btn_expand_size = QPushButton("↕ Expand", card)
    card.btn_expand_size.setCursor(Qt.CursorShape.PointingHandCursor)
    card.btn_expand_size.setFixedHeight(22)
    card.btn_expand_size.setToolTip("Expand or compact Agent shell/tool output height")
    card.btn_expand_size.setStyleSheet(
        "QPushButton { background: rgba(147, 51, 234, 0.25); color: #E9D5FF; "
        "border: 1px solid rgba(168, 85, 247, 0.45); border-radius: 6px; "
        "padding: 2px 8px; font-size: 10px; font-weight: bold; }"
        "QPushButton:hover { background: #9333EA; color: #FFFFFF; }"
    )
    card.btn_expand_size.clicked.connect(lambda: _tcc_toggle_expand_size(card))
    # Only visible once the dropdown is expanded - never a dead control
    # floating on a compact card.
    card.btn_expand_size.setVisible(bool(getattr(card, "is_expanded", False)))

    inserted_hdr = False
    if card.layout() is not None and card.layout().count() > 0:
        first_item = card.layout().itemAt(0)
        hdr_lay = first_item.layout() if first_item is not None else None
        if isinstance(hdr_lay, QHBoxLayout):
            idx_ins = max(0, hdr_lay.count() - 1)
            hdr_lay.insertWidget(idx_ins, card.btn_expand_size)
            inserted_hdr = True
    if not inserted_hdr and card.layout() is not None:
        card.layout().addWidget(card.btn_expand_size)

    target_container = getattr(card, "body_widget", None) or card
    if card._out_editor is not None and target_container.layout() is not None:
        card.resizer_bar = _ToolCardResizer(card)
        card.resizer_bar.setVisible(bool(getattr(card, "is_expanded", False)))
        target_container.layout().addWidget(card.resizer_bar)


def _tcc_set_output_box_height(self, h: int) -> None:
    if getattr(self, "_out_editor", None) is not None:
        self._out_editor.setFixedHeight(max(54, int(h)))
    _tcc_recalc_height(self)


def _tcc_toggle_expand_size(self) -> None:
    body_w = getattr(self, "body_widget", None)
    if body_w is not None and body_w.isHidden():
        if hasattr(self, "toggle_body"):
            self.toggle_body()
        elif hasattr(self, "_toggle"):
            self._toggle()
        body_w.setVisible(True)
        body_w.show()

    self._is_expanded_full = not getattr(self, "_is_expanded_full", False)
    if self._is_expanded_full:
        self.btn_expand_size.setText("↕ Compact")
        if getattr(self, "_in_editor", None) is not None:
            in_lines = max(2, (self._in_editor.toPlainText() or "").count("\n") + 1)
            self._in_editor.setFixedHeight(min(260, max(64, in_lines * 19 + 22)))
        _tcc_set_output_box_height(self, getattr(self, "_expanded_out_h", 340))
    else:
        self.btn_expand_size.setText("↕ Expand")
        if getattr(self, "_in_editor", None) is not None:
            in_lines = max(2, (self._in_editor.toPlainText() or "").count("\n") + 1)
            self._in_editor.setFixedHeight(min(140, max(54, in_lines * 19 + 18)))
        _tcc_set_output_box_height(self, getattr(self, "_compact_out_h", 110))


def _tcc_recalc_height(self) -> None:
    if self.layout() is not None:
        self.layout().invalidate()
        self.layout().activate()
    body_w = getattr(self, "body_widget", None)
    if body_w is not None and not body_w.isHidden() and body_w.layout() is not None:
        body_w.layout().invalidate()
        body_w.layout().activate()
    sh = self.sizeHint().height()
    if sh > 40:
        self.setMinimumHeight(sh)
        self.setMaximumHeight(max(sh + 24, 1200))
    self.updateGeometry()
    top_w = self.window()
    if top_w is not None and hasattr(top_w, "update_all_bubble_geometries"):
        try:
            top_w.update_all_bubble_geometries()
        except Exception:
            pass


if "ToolCallCard" not in globals():
    class ToolCallCard(QFrame):
        """Expandable & Drag-Resizable Agent Shell/Tool Execution Card (#26)."""
        def __init__(self, tool_name: str = "shell_exec", args_dict: dict | None = None, result_str: str = "", parent=None):
            super().__init__(parent)
            self.tool_name = str(tool_name or "shell_exec")
            self.args_dict = args_dict or {}
            self.result_str = str(result_str or "")
            self.setObjectName("ToolCallCard")
            self.setStyleSheet(
                "QFrame#ToolCallCard { background: rgba(14, 10, 28, 0.94); "
                "border: 1.5px solid #9333EA; border-radius: 12px; }"
            )
            lay = QVBoxLayout(self)
            lay.setContentsMargins(12, 8, 12, 8)
            lay.setSpacing(6)

            hdr = QHBoxLayout()
            lbl = QLabel(f"<b>{self.tool_name}</b>", self)
            lbl.setStyleSheet("color: #E9D5FF; font-size: 12px; border: none; background: transparent;")
            hdr.addWidget(lbl)
            hdr.addStretch(1)
            lay.addLayout(hdr)

            self.body_widget = QWidget(self)
            b_lay = QVBoxLayout(self.body_widget)
            b_lay.setContentsMargins(0, 4, 0, 4)
            b_lay.setSpacing(4)

            import json as _j
            in_ed = QTextEdit(self.body_widget)
            in_ed.setReadOnly(True)
            in_ed.setFont(QFont("Consolas", 9))
            in_ed.setPlainText(_j.dumps(self.args_dict, indent=2) if isinstance(self.args_dict, dict) else str(self.args_dict))
            b_lay.addWidget(in_ed)

            out_ed = QTextEdit(self.body_widget)
            out_ed.setReadOnly(True)
            out_ed.setFont(QFont("Consolas", 9))
            out_ed.setPlainText(self.result_str)
            b_lay.addWidget(out_ed)

            lay.addWidget(self.body_widget)
            _attach_expand_and_resizer_to_tool_card(self)

        set_output_box_height = _tcc_set_output_box_height
        toggle_expand_size = _tcc_toggle_expand_size
        _recalc_tool_card_height = _tcc_recalc_height
else:
    _orig_existing_tcc_init = ToolCallCard.__init__
    def _wrapped_existing_tcc_init(self, *args, **kwargs):
        _orig_existing_tcc_init(self, *args, **kwargs)
        _attach_expand_and_resizer_to_tool_card(self)
    ToolCallCard.__init__ = _wrapped_existing_tcc_init
    ToolCallCard.set_output_box_height = _tcc_set_output_box_height
    ToolCallCard.toggle_expand_size = _tcc_toggle_expand_size
    ToolCallCard._recalc_tool_card_height = _tcc_recalc_height


# ── 2026 Visual & Hidden Bug Patch (ThinkingCard + Zero Boxy Labels) ──
if "ThinkingCard" in globals():
    _prev_tc_init_2026 = ThinkingCard.__init__

    def _fixed_tc_init_2026(self, *args, **kwargs):
        _prev_tc_init_2026(self, *args, **kwargs)
        self.setObjectName("ThinkingCard")
        self.setStyleSheet(
            "QFrame#ThinkingCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 rgba(32, 18, 52, 0.94), stop:1 rgba(18, 12, 34, 0.94)); "
            "border: 1.5px solid #A855F7; border-radius: 12px; } "
            "QLabel { border: none; background: transparent; }"
        )
        if hasattr(self, "lbl_text"):
            self.lbl = self.lbl_text
            # The status row must always fit: let the label shrink instead of
            # pushing the 96px star rail past the card's right edge.
            self.lbl_text.setMinimumWidth(0)
            self.lbl_text.setWordWrap(False)
            self.lbl_text.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        if hasattr(self, "spinner") and self.spinner is not None:
            self.spinner.hide()
        self.setMinimumWidth(0)

    ThinkingCard.__init__ = _fixed_tc_init_2026

    # Final say on status text: keep the worker's own icon (🧠/🍑/🔧…) and let
    # the card grow so the loading text (e.g. "Local GGUF reading 685 tokens…")
    # is NEVER clipped - width is computed from the actual rendered text.
    def _final_tc_set_status(self, text: str) -> None:
        raw = str(text or "").strip()
        raw = re.sub(r"^(?:🧠\s*){2,}", "🧠 ", raw)  # collapse double brain
        lbl = getattr(self, "lbl_text", None) or getattr(self, "lbl", None)
        if lbl is not None:
            display = raw or "💭 Thinking…"
            lbl.setText(display)
            lbl.setToolTip(display)
            lbl.setMinimumWidth(0)
            lbl.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        # Measure how wide the status row truly needs to be: spinner + text +
        # dots rail + margins, then let the card expand to fit. Only reflow the
        # parent bubble when the width actually *grows* - streaming ticks call
        # this many times per second and a full bubble relayout on each tick
        # would trade one lag for another.
        needed = 60  # base padding / margins
        if lbl is not None:
            fm = QFontMetrics(lbl.font())
            needed += fm.horizontalAdvance(display) + 14
        if hasattr(self, "spinner") and self.spinner is not None:
            needed += self.spinner.width() + 10
        if hasattr(self, "dots_canvas") and self.dots_canvas is not None:
            needed += self.dots_canvas.width() + 10
        new_min = max(340, needed)
        last_min = int(getattr(self, "_status_min_w", 0) or 0)
        grew = new_min > last_min + 2
        if grew:
            self._status_min_w = new_min
            self.setMinimumWidth(new_min)
        self.adjustSize()
        self.updateGeometry()
        if not grew:
            return
        # Tell the parent bubble to re-measure so the card isn't squished.
        p = self.parentWidget()
        while p is not None:
            if hasattr(p, "update_dynamic_width") and hasattr(p, "max_allowed_w"):
                try:
                    p.update_dynamic_width(
                        max(p.max_allowed_w, self.minimumWidth() + 36))
                except Exception:
                    pass
                break
            p = p.parentWidget()

    ThinkingCard.set_status = _final_tc_set_status

if "ThoughtAccordionCard" in globals():
    _prev_tac_init_2026 = ThoughtAccordionCard.__init__

    def _fixed_tac_init_2026(self, *args, **kwargs):
        _prev_tac_init_2026(self, *args, **kwargs)
        self.setObjectName("ThoughtAccordionCard")
        self.setStyleSheet(
            "QFrame#ThoughtAccordionCard { background: rgba(20, 14, 38, 0.72); "
            "border: 1px solid rgba(168, 85, 247, 0.35); border-radius: 8px; margin-top: 4px; margin-bottom: 4px; } "
            "QLabel { border: none; background: transparent; }"
        )

    ThoughtAccordionCard.__init__ = _fixed_tac_init_2026

# ══ WAVE_OMG_PARITY_START ══
# PC #1: Ensure ThinkingCard never clips text AND bookmark_wrap is always at the bottom of the bubble
def _ensure_bookmark_at_bottom(bubble: MessageBubbleNew) -> None:
    bm = getattr(bubble, "bookmark_wrap", None)
    lay = bubble.layout()
    if bm is None or lay is None:
        return
    # Keep info_card right above bookmark_wrap when bottom-anchored
    card = getattr(bubble, "info_card", None)
    is_open = bool(getattr(bubble, "_info_open", False)) and card is not None and not card.isHidden()
    anchor = getattr(bubble, "_info_anchor", None)
    lay.removeWidget(bm)
    lay.addWidget(bm)
    if is_open and anchor == "bottom" and card is not None:
        lay.removeWidget(card)
        bm_idx = lay.indexOf(bm)
        if bm_idx >= 0:
            lay.insertWidget(bm_idx, card)


_orig_mb_update_stream_omg = MessageBubbleNew.update_stream_text
_orig_mb_finalize_stream_omg = MessageBubbleNew.finalize_stream
_orig_mb_render_normal_omg = MessageBubbleNew._render_normal_content
_orig_mb_update_width_omg = MessageBubbleNew.update_dynamic_width


def _patched_mb_update_stream_omg(self, text):
    _orig_mb_update_stream_omg(self, text)
    _ensure_bookmark_at_bottom(self)


def _patched_mb_finalize_stream_omg(self, final_text=None):
    _orig_mb_finalize_stream_omg(self, final_text)
    _ensure_bookmark_at_bottom(self)


def _patched_mb_render_normal_omg(self, display_text, is_user):
    _orig_mb_render_normal_omg(self, display_text, is_user)
    _ensure_bookmark_at_bottom(self)


def _patched_mb_update_width_omg(self, max_allowed_w: int) -> None:
    tc = getattr(self, "thinking_card", None)
    if tc is not None:
        # The star rail is fixed at 96px; inflating minimum widths here used
        # to push it outside the bubble on narrow chats.
        # Zero minimums keep the rail pinned inside the card at every width.
        tc.setMinimumWidth(0)
        lbl = getattr(tc, "lbl_text", None) or getattr(tc, "lbl", None)
        if lbl is not None:
            lbl.setMinimumWidth(0)
            lbl.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            lbl.setToolTip(lbl.text())
    _orig_mb_update_width_omg(self, max_allowed_w)


MessageBubbleNew.update_stream_text = _patched_mb_update_stream_omg
MessageBubbleNew.finalize_stream = _patched_mb_finalize_stream_omg
MessageBubbleNew._render_normal_content = _patched_mb_render_normal_omg
MessageBubbleNew.update_dynamic_width = _patched_mb_update_width_omg
# ══ WAVE_OMG_PARITY_END ══


# ═══ WAVE OMG BUBBLE PARITY BLOCK START ═══
import inspect as _bub_inspect
try:
    from cellium.core.utils import wrap_gemma_raw_thinking
except Exception:
    def wrap_gemma_raw_thinking(text: str) -> str:
        return text

if "MessageBubbleNew" in globals():
    _orig_bubble_init_omg = getattr(MessageBubbleNew, "_pre_omg_init", None) or MessageBubbleNew.__init__
    MessageBubbleNew._pre_omg_init = _orig_bubble_init_omg


# === WAVE_OMG_PARITY_START (BUBBLE_V3_CLEAN) ===
if 'MessageBubbleNew' in globals():
    _orig_bubble_init_v3 = MessageBubbleNew.__init__

    def _patched_bubble_init_v3(self, *args, **kwargs):
        try:
            _orig_bubble_init_v3(self, *args, **kwargs)
        except TypeError:
            import inspect as _insp
            sig = _insp.signature(_orig_bubble_init_v3)
            accepts_var_kw = any(p.kind == _insp.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if not accepts_var_kw:
                filtered_kw = {k: v for k, v in kwargs.items() if k in sig.parameters}
                _orig_bubble_init_v3(self, *args, **filtered_kw)
            else:
                raise
        try:
            btn_speaker = getattr(self, 'btn_speaker', None)
            if btn_speaker is not None:
                btn_speaker.setToolTip('Read Aloud (Kokoro / Edge TTS)')
        except Exception:
            pass

    MessageBubbleNew.__init__ = _patched_bubble_init_v3
# === WAVE_OMG_PARITY_END (BUBBLE_V3_CLEAN) ===


# ── Info drawer never shows stale "Tokens: 0" after finalize ───────────────────
if "MessageBubbleNew" in globals():
    _prev_mb_toggle_info_final = MessageBubbleNew.toggle_info_card

    def _refresh_open_info_card_final(self) -> None:
        """Rebuild an already-open drawer with the freshly attached turn meta."""
        card = getattr(self, "info_card", None)
        if card is None or not bool(getattr(self, "_info_open", False)):
            return
        try:
            lay = self.layout()
            if lay is not None:
                lay.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        except Exception:
            pass
        self.info_card = None
        self.info_expanded = False
        self._info_open = False
        if hasattr(self, "show_info"):
            self.show_info = False
        try:
            self.toggle_info_card("top", animate=False)
        except Exception:
            pass

    def _patched_mb_toggle_info_final(self, *args, **kwargs):
        # Fold the newest turn meta into the bubble so the drawer's numbers are
        # never the zeros captured while the reply was still streaming.
        try:
            meta = getattr(self, "meta", None) or {}
            app = getattr(self, "chat_app", None)
            pending = getattr(app, "_pending_meta", None) if app is not None else None
            if (isinstance(pending, dict) and not meta.get("turn_tokens")
                    and (getattr(self, "is_ghost", False)
                         or self is getattr(app, "active_stream_bubble", None))):
                merged = dict(meta)
                merged.update({k: v for k, v in pending.items() if v})
                self.meta = merged
        except Exception:
            pass
        # A closed card is stale by definition - rebuild it on the next open.
        card = getattr(self, "info_card", None)
        if card is not None and not bool(getattr(self, "_info_open", False)):
            try:
                lay = self.layout()
                if lay is not None:
                    lay.removeWidget(card)
                card.setParent(None)
                card.deleteLater()
            except Exception:
                pass
            self.info_card = None
            self.info_expanded = False
        return _prev_mb_toggle_info_final(self, *args, **kwargs)

    MessageBubbleNew.toggle_info_card = _patched_mb_toggle_info_final
    MessageBubbleNew._refresh_open_info_card = _refresh_open_info_card_final
