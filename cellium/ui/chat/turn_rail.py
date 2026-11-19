#!/usr/bin/env python3
"""
Wave K14 - Antigravity-Style Chat Turn Navigation Rail & Slick Preview Popover.
Fixed-viewport dot rail on the left margin with live hover preview cards and smooth turn jumping.
"""

import re
from PySide6.QtCore import (
    QEvent, QObject, QPointF, QPropertyAnimation, QEasingCurve, QRect, Qt, QTimer
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPen
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
)


def _clean_preview_text(text: str, max_chars: int = 140) -> str:
    """Strip code blocks, tags, excessive whitespace and markdown for a clean snippet."""
    if not text:
        return ""
    # Strip agent actions and code fences
    s = re.sub(r"<agent_action.*?</agent_action>", " [Action] ", str(text), flags=re.DOTALL)
    s = re.sub(r"```.*?```", " [Code] ", s, flags=re.DOTALL)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    # Strip markdown headers, bold, italics, strikes
    s = re.sub(r"^#+\s*", "", s, flags=re.MULTILINE)
    s = re.sub(r"[*_~]+", "", s)
    # Collapse whitespace and newlines
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_chars:
        return s[:max_chars - 1].rstrip() + "…"
    return s


class TurnPreviewCard(QFrame):
    """Slick floating glass card that previews the hovered conversation turn."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(320)

        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 220))
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(6)

        # User prompt label (white, bold)
        self.lbl_user = QLabel()
        self.lbl_user.setWordWrap(True)
        self.lbl_user.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_user.setStyleSheet("""
            color: #FFFFFF;
            font-size: 12px;
            font-weight: 600;
            line-height: 1.35;
            background: transparent;
            border: none;
        """)
        layout.addWidget(self.lbl_user)

        # Assistant response label (soft lavender / gray)
        self.lbl_asst = QLabel()
        self.lbl_asst.setWordWrap(True)
        self.lbl_asst.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_asst.setStyleSheet("""
            color: #D1D5DB;
            font-size: 11px;
            font-weight: 400;
            line-height: 1.35;
            background: transparent;
            border: none;
        """)
        layout.addWidget(self.lbl_asst)

        # Footer row: "3 of 5" | "15:29"
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        footer.setSpacing(8)

        self.lbl_turn = QLabel()
        self.lbl_turn.setStyleSheet("color: #9CA3AF; font-size: 10px; font-weight: 500; background: transparent; border: none;")
        footer.addWidget(self.lbl_turn)

        footer.addStretch(1)

        self.lbl_time = QLabel()
        self.lbl_time.setStyleSheet("color: #9CA3AF; font-size: 10px; font-weight: 500; background: transparent; border: none;")
        footer.addWidget(self.lbl_time)

        layout.addLayout(footer)
        self.hide()

    def paintEvent(self, ev):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor(168, 85, 247, 130), 1.2))
            p.setBrush(QColor(22, 14, 34, 248))
            r = self.rect().adjusted(1, 1, -1, -1)
            p.drawRoundedRect(r, 12, 12)
        super().paintEvent(ev)

    def set_turn(self, turn_idx: int, total_turns: int, user_text: str, asst_text: str, time_str: str):
        clean_user = _clean_preview_text(user_text, max_chars=130)
        clean_asst = _clean_preview_text(asst_text, max_chars=150)
        self.lbl_user.setText(clean_user or "User prompt")
        if clean_asst:
            self.lbl_asst.setText(clean_asst)
            self.lbl_asst.setVisible(True)
        else:
            self.lbl_asst.setVisible(False)

        self.lbl_turn.setText(f"{turn_idx} of {total_turns}")
        self.lbl_time.setText(time_str or "")
        self.adjustSize()


class ChatTurnNavRail(QWidget):
    """Antigravity-style turn navigation dot rail on the left margin of chat_scroll."""

    RAIL_WIDTH = 26
    DOT_X = 13.0

    def __init__(self, scroll_area: QScrollArea, chat_app=None):
        super().__init__(scroll_area.viewport())
        self.scroll_area = scroll_area
        self.chat_app = chat_app
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self._turns = []         # list of turn dicts
        self._dot_positions = [] # list of (turn_idx, y_center)
        self._active_index = 0
        self._hover_index = -1
        self._anim = None

        self.card = TurnPreviewCard(scroll_area.viewport())

        # Event filter to track viewport resize
        scroll_area.viewport().installEventFilter(self)
        self.update_geometry()

    def eventFilter(self, watched, ev):
        if watched is self.scroll_area.viewport() and ev.type() == QEvent.Type.Resize:
            self.update_geometry()
        return super().eventFilter(watched, ev)

    def update_geometry(self):
        vp = self.scroll_area.viewport()
        if vp:
            h = vp.height()
            self.setGeometry(0, 0, self.RAIL_WIDTH, h)
            self._recalculate_dots()
            self.update()

    def refresh_turns(self):
        """Scrape active user turns from chat_app's current session."""
        if not self.chat_app:
            return
        ses = self.chat_app.sessions.get(self.chat_app.current_sid)
        if not ses:
            self._turns = []
            self._dot_positions = []
            self.card.hide()
            self.update()
            return

        mem = ses.get("memory", [])
        turns = []
        user_turn_counter = 0

        for i, m in enumerate(mem):
            if m.get("role") == "user":
                user_turn_counter += 1
                asst_content = ""
                for j in range(i + 1, len(mem)):
                    if mem[j].get("role") == "assistant":
                        asst_content = mem[j].get("content", "")
                        break
                    elif mem[j].get("role") == "user":
                        break

                turns.append({
                    "turn_idx": user_turn_counter,
                    "user_text": m.get("content", ""),
                    "asst_text": asst_content,
                    "time": m.get("time", ""),
                    "mem_index": i,
                })

        self._turns = turns
        self._recalculate_dots()
        self.update_active_from_scroll()
        self.update()

    def _recalculate_dots(self):
        vp_h = self.height()
        n = len(self._turns)
        self._dot_positions = []
        if n == 0 or vp_h <= 60:
            return

        # Modern fluid spacing (clamped to fit viewport gracefully)
        max_spacing = 22.0
        min_spacing = 13.0
        avail_h = max(40.0, float(vp_h) - 140.0)

        if n == 1:
            spacing = 0.0
            start_y = vp_h / 2.0
        else:
            spacing = min(max_spacing, max(min_spacing, avail_h / float(n - 1)))
            start_y = (vp_h - (spacing * (n - 1))) / 2.0

        for i in range(n):
            y = start_y + i * spacing
            self._dot_positions.append((i, y))

    def update_active_from_scroll(self, scroll_val=None):
        """Update the active dot based on which turn bubble is currently in view."""
        if not self._turns or not self.chat_app or not hasattr(self.chat_app, "chat_layout"):
            return
        if scroll_val is None:
            scroll_val = self.scroll_area.verticalScrollBar().value()

        best_idx = 0
        lay = self.chat_app.chat_layout
        for turn_i, t in enumerate(self._turns):
            mem_i = t["mem_index"]
            for item_idx in range(lay.count()):
                w = lay.itemAt(item_idx).widget()
                if w and getattr(w, "is_user", False) and getattr(w, "memory_index", None) == mem_i:
                    if w.y() <= scroll_val + 140:
                        best_idx = turn_i
                    break

        if best_idx != self._active_index:
            self._active_index = best_idx
            self.update()

    def _find_bubble_widget(self, mem_index: int):
        """Return the user MessageBubbleNew in chat_layout matching mem_index."""
        if not self.chat_app or not hasattr(self.chat_app, "chat_layout"):
            return None
        lay = self.chat_app.chat_layout
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if w and getattr(w, "is_user", False) and getattr(w, "memory_index", None) == mem_index:
                return w
        return None

    def _scroll_to_turn(self, turn_idx: int):
        """Smoothly scroll the chat area directly to the chosen turn."""
        if turn_idx < 0 or turn_idx >= len(self._turns):
            return
        turn = self._turns[turn_idx]
        w = self._find_bubble_widget(turn["mem_index"])
        if not w:
            return

        bar = self.scroll_area.verticalScrollBar()
        # Align bubble top comfortably near viewport top (~28px breathing room)
        target = max(bar.minimum(), min(bar.maximum(), w.y() - 28))

        if self._anim is not None:
            self._anim.stop()

        self._anim = QPropertyAnimation(bar, b"value")
        self._anim.setDuration(240)
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

        self._active_index = turn_idx
        self.update()

    # ----------------------------------------------------------- mouse events
    def mouseMoveEvent(self, ev):
        y = ev.position().y()
        found = -1
        hit_radius = 11.0

        for i, dot_y in self._dot_positions:
            if abs(y - dot_y) <= hit_radius:
                found = i
                break

        if found != self._hover_index:
            self._hover_index = found
            if found != -1 and found < len(self._turns):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                turn = self._turns[found]
                dot_y = self._dot_positions[found][1]

                self.card.set_turn(
                    turn["turn_idx"],
                    len(self._turns),
                    turn["user_text"],
                    turn["asst_text"],
                    turn["time"]
                )
                card_h = self.card.height()
                card_y = int(dot_y - (card_h / 2.0))
                vp_h = self.scroll_area.viewport().height()
                card_y = max(10, min(vp_h - card_h - 10, card_y))

                self.card.move(int(self.RAIL_WIDTH + 6), card_y)
                self.card.show()
                self.card.raise_()
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self.card.hide()
            self.update()

        super().mouseMoveEvent(ev)

    def leaveEvent(self, ev):
        self._hover_index = -1
        self.card.hide()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self._hover_index != -1:
            self._scroll_to_turn(self._hover_index)
            ev.accept()
            return
        super().mousePressEvent(ev)

    # --------------------------------------------------------------- painting
    def paintEvent(self, ev):
        if len(self._dot_positions) < 2:
            return

        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            # 1. Subtle vertical spine connector line
            y_first = self._dot_positions[0][1]
            y_last = self._dot_positions[-1][1]
            p.setPen(QPen(QColor(168, 85, 247, 45), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(self.DOT_X, y_first), QPointF(self.DOT_X, y_last))

            # 2. Render each turn dot
            for i, dot_y in self._dot_positions:
                center = QPointF(self.DOT_X, dot_y)
                is_active = (i == self._active_index)
                is_hover = (i == self._hover_index)

                if is_active:
                    # Active turn: Glowing purple halo + bright white core
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(168, 85, 247, 75))
                    p.drawEllipse(center, 7.5, 7.5)
                    p.setBrush(QColor(192, 132, 252, 220))
                    p.drawEllipse(center, 4.8, 4.8)
                    p.setBrush(QColor(255, 255, 255, 255))
                    p.drawEllipse(center, 2.5, 2.5)
                elif is_hover:
                    # Hovered turn: Neon pink glow
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(236, 72, 153, 85))
                    p.drawEllipse(center, 7.0, 7.0)
                    p.setBrush(QColor(244, 114, 182, 240))
                    p.drawEllipse(center, 4.2, 4.2)
                    p.setBrush(QColor(255, 255, 255, 255))
                    p.drawEllipse(center, 2.0, 2.0)
                else:
                    # Inactive turn: Soft translucent white/purple dot
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(255, 255, 255, 80))
                    p.drawEllipse(center, 3.2, 3.2)
