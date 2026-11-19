#!/usr/bin/env python3
"""Wave K13/K14 - chat timeline spine rail & right-side message scrubber.

ChatTimelineHost replaces the plain chat_content QWidget: it paints a
decorative vertical spine (gradient line + role-colored node dots) down the
RIGHT gutter of the conversation, behind every bubble. Bubbles sit between the
left turn rail (40px) and the right timeline scrubber (40px), so neither
rail band ever overlaps a child bubble widget.
"""

from PySide6.QtCore import QEvent, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

RAIL_OFFSET_RIGHT = 20.0
GUTTER_W = 40

_COLOR_USER = "#60A5FA"
_COLOR_CEL = "#C084FC"
_COLOR_OTHER = "#A78BFA"


class ChatTimelineHost(QWidget):
    """chat_content host that draws the timeline spine and scrubber on the right margin."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._rail_nodes = []
        self._dragging_rail = False

        self._rail_t0 = QTimer(self)
        self._rail_t0.setSingleShot(True)
        self._rail_t0.setInterval(0)
        self._rail_t0.timeout.connect(self.refresh_rail)
        self._rail_t90 = QTimer(self)
        self._rail_t90.setSingleShot(True)
        self._rail_t90.setInterval(90)
        self._rail_t90.timeout.connect(self.refresh_rail)

    # ------------------------------------------------------------- plumbing
    def event(self, ev):
        result = super().event(ev)
        if ev.type() in (QEvent.Type.LayoutRequest, QEvent.Type.ChildAdded, QEvent.Type.ChildRemoved):
            t0 = getattr(self, "_rail_t0", None)
            t90 = getattr(self, "_rail_t90", None)
            if t0 is not None and t90 is not None:
                t0.start()
                t90.start()
        return result

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.refresh_rail()

    def refresh_rail(self):
        """Repaint the right-side scrubber strip."""
        if self.height() > 0 and self.width() > 0:
            rx = max(0, int(self.width() - GUTTER_W - 12))
            self.update(QRect(rx, 0, GUTTER_W + 16, self.height()))
            return
        self.update()

    # -------------------------------------------------------------- painting
    def _collect_nodes(self):
        lay = self.layout()
        nodes = []
        if lay is None:
            return nodes
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w is None or w.isHidden() or w.width() <= 0 or w.height() <= 0:
                continue
            if w.property("cel_timeline") is False:
                continue
            y = w.y() + (18.0 if w.height() > 36 else w.height() / 2.0)
            nodes.append((float(y), getattr(w, "role", None)))
        nodes.sort(key=lambda n: n[0])
        return nodes

    # ------------------------------------------------------------- interaction
    def _scroll_to_y(self, y: float):
        scroll_area = self.parentWidget()
        while scroll_area and not hasattr(scroll_area, "verticalScrollBar"):
            scroll_area = scroll_area.parentWidget()
        if scroll_area:
            bar = scroll_area.verticalScrollBar()
            vp_h = scroll_area.viewport().height() if hasattr(scroll_area, "viewport") else 300
            target = int(y - vp_h / 2.0)
            target = max(bar.minimum(), min(bar.maximum(), target))
            bar.setValue(target)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and ev.position().x() >= self.width() - GUTTER_W - 10:
            self._dragging_rail = True
            self._scroll_to_y(ev.position().y())
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if getattr(self, "_dragging_rail", False) and (ev.buttons() & Qt.MouseButton.LeftButton):
            self._scroll_to_y(ev.position().y())
            ev.accept()
            return
        if ev.position().x() >= self.width() - GUTTER_W - 10:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._dragging_rail = False
        super().mouseReleaseEvent(ev)

    def paintEvent(self, ev):
        nodes = self._collect_nodes()
        self._rail_nodes = nodes
        if not nodes:
            return

        rail_x = float(self.width() - RAIL_OFFSET_RIGHT)

        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Gradient spine line connecting first message to last
            y0, y1 = nodes[0][0], nodes[-1][0]
            if y1 - y0 > 1.0:
                grad = QLinearGradient(0.0, y0, 0.0, y1)
                grad.setColorAt(0.0, QColor(96, 165, 250, 75))
                grad.setColorAt(0.5, QColor(168, 85, 247, 180))
                grad.setColorAt(1.0, QColor(192, 132, 252, 75))
                p.setPen(QPen(QBrush(grad), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(rail_x, y0), QPointF(rail_x, y1))

            # Role-colored glowing node circles for each message
            for y, role in nodes:
                if role == "user":
                    core = QColor(_COLOR_USER)
                elif role == "assistant":
                    core = QColor(_COLOR_CEL)
                else:
                    core = QColor(_COLOR_OTHER)

                p.setPen(Qt.PenStyle.NoPen)
                # Outer translucent glow aura
                p.setBrush(QColor(168, 85, 247, 45))
                p.drawEllipse(QPointF(rail_x, y), 7.5, 7.5)
                # Colored core
                p.setBrush(core)
                p.drawEllipse(QPointF(rail_x, y), 4.4, 4.4)
                # Specular glint
                p.setBrush(QColor(255, 255, 255, 210))
                p.drawEllipse(QPointF(rail_x - 1.4, y - 1.4), 1.3, 1.3)
