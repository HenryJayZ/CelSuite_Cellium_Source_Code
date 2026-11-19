#!/usr/bin/env python3
"""
Cellium profile pictures - circular cutouts for you and for Cel. 🎀

Three pieces live here:

``CircularAvatarLabel``
    The round portrait painted inside a chat bubble header (and in Settings /
    onboarding). Click it to re-crop the picture. With no picture on disk it
    falls back to a violet gradient disc with the display initial, so a fresh
    install still looks intentional instead of empty.

``AvatarCropperDialog``
    Pick a file, then drag to pan / wheel or slider to zoom / slider to rotate
    inside a circle viewport with a live preview, and confirm. The confirmed
    crop is stored as a square PNG on disk; the circle is cut at paint time so
    one file works at 26 px (chat header), 48 px (settings) or 132 px (cropper
    preview) without re-encoding.

``run_avatar_flow``
    The one-call "open cropper → save → refresh callers" flow shared by the
    Settings dialog and the onboarding wizard, so both behave identically.

The paths themselves live in ``core.config`` (Qt-free); this module owns the
rendering. Exported cutouts are cached per ``(who, diameter, mtime)`` so a chat
with 500 bubbles costs 500 cache hits, not 500 pixmap loads - and the cache
busts itself the moment a new avatar lands on disk.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from cellium.core.config import (
    AVATARS_DIR,
    CEL_AVATAR_FILE,
    USER_AVATAR_FILE,
)
from cellium.core.logger import dev_log

# ── palette ────────────────────────────────────────────────────────────────
_ACCENT_USER = ("#F472B6", "#C084FC")      # pink → violet ring for you
_ACCENT_CEL = ("#C084FC", "#818CF8")       # violet → indigo ring for Cel
_DISC_TOP = QColor(74, 32, 110, 235)
_DISC_BOTTOM = QColor(28, 12, 52, 235)
_RING_FADE = QColor(91, 33, 182, 235)

_AVATAR_FILES = {"user": Path(USER_AVATAR_FILE), "cel": Path(CEL_AVATAR_FILE)}

#: Supersample factor when cutting the circle - 4x keeps the rim silky.
_SS = 4
#: Export resolution of a confirmed crop (square PNG on disk).
_CROP_EXPORT = 320
#: Diameter of the crop viewport in the dialog.
_CROP_CANVAS = 300


def avatar_file(who: str) -> Path:
    """On-disk PNG for ``who`` ("user" / "cel")."""
    return _AVATAR_FILES.get(who, _AVATAR_FILES["user"])


# ── pixmap cache ───────────────────────────────────────────────────────────
_cache: dict[tuple, QPixmap] = {}


def _source_mtime(who: str) -> float:
    try:
        return avatar_file(who).stat().st_mtime
    except OSError:
        return -1.0


def load_square_avatar(who: str) -> QPixmap | None:
    """Raw square avatar PNG, or ``None`` when nothing usable is on disk."""
    p = avatar_file(who)
    try:
        if not p.is_file() or p.stat().st_size <= 0:
            return None
    except OSError:
        return None
    pm = QPixmap(str(p))
    return None if pm.isNull() else pm


def _square_of(pm: QPixmap) -> QPixmap:
    """Centre-crop any pixmap to a square (a no-op for our own exports)."""
    side = min(pm.width(), pm.height())
    if pm.width() == side and pm.height() == side:
        return pm
    if side <= 0:
        return pm
    return pm.copy((pm.width() - side) // 2, (pm.height() - side) // 2,
                   side, side)


def circular_pixmap(source: QPixmap, diameter: int) -> QPixmap:
    """Cut ``source`` into an antialiased circle of ``diameter`` px."""
    d = max(8, int(diameter))
    big = d * _SS
    sq = _square_of(source)
    img = QImage(big, big, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    clip = QPainterPath()
    clip.addEllipse(QRectF(0.0, 0.0, float(big), float(big)))
    p.setClipPath(clip)
    if sq.width() and sq.height():
        scaled = sq.scaled(big, big,
                           Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        p.drawImage(QRectF(0.0, 0.0, float(big), float(big)), scaled.toImage())
    p.end()
    return QPixmap.fromImage(img.scaled(d, d, Qt.AspectRatioMode.IgnoreAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))


def avatar_pixmap(who: str, diameter: int) -> QPixmap | None:
    """Circular cutout at ``diameter``, cached by (who, diameter, mtime)."""
    key = (who, int(diameter), _source_mtime(who))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    src = load_square_avatar(who)
    if src is None:
        return None
    out = circular_pixmap(src, diameter)
    if len(_cache) > 24:            # a handful of sizes is all we ever need
        _cache.clear()
    _cache[key] = out
    return out


def bust_avatar_cache() -> None:
    """Force every label to re-read the avatars from disk."""
    _cache.clear()


def save_avatar(who: str, pixmap: QPixmap) -> bool:
    """Persist a confirmed crop (square PNG) for ``who``."""
    if pixmap is None or pixmap.isNull():
        return False
    path = avatar_file(who)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ok = bool(pixmap.save(str(path), "PNG"))
    except Exception as e:                                   # noqa: BLE001
        dev_log(f"pfp: saving {who} avatar failed: {e}")
        ok = False
    if ok:
        bust_avatar_cache()
    return ok


def clear_avatar(who: str) -> None:
    """Remove ``who``'s picture, falling back to the initial disc."""
    try:
        p = avatar_file(who)
        if p.exists():
            p.unlink()
    except OSError as e:
        dev_log(f"pfp: removing {who} avatar failed: {e}")
    bust_avatar_cache()


# ── the round label ────────────────────────────────────────────────────────
class CircularAvatarLabel(QPushButton):
    """Round portrait with a gradient ring; click opens the cropper."""

    def __init__(self, who: str = "user", diameter: int = 30,
                 fallback_text: str = "", parent=None):
        super().__init__(parent)
        self.who = who if who in _AVATAR_FILES else "user"
        self._diameter = max(16, int(diameter))
        self._pm: QPixmap | None = None
        self._override: QPixmap | None = None
        a, b = _ACCENT_CEL if self.who == "cel" else _ACCENT_USER
        self._ring_a = QColor(a)
        self._ring_b = QColor(b)
        self.fallback_text = (fallback_text or ("C" if self.who == "cel"
                                               else "?"))[:1].upper()
        self.setFlat(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(self._diameter + 8, self._diameter + 8)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self.setToolTip("🖼️ Click to change this picture" if self.who == "user"
                        else "✨ Click to change Cel's picture")

    # -- painting ---------------------------------------------------------
    def _ring_brush(self, inner: QRectF) -> QLinearGradient:
        g = QLinearGradient(inner.topLeft(), inner.bottomRight())
        g.setColorAt(0.0, self._ring_a.lighter(130))
        g.setColorAt(0.55, self._ring_b)
        g.setColorAt(1.0, _RING_FADE)
        return g

    def paintEvent(self, _event):
        # `with` guarantees QPainter.end() even if a paint step raises  - 
        # otherwise Qt spams "QBackingStore::endPaint() called with active
        # painter" and the rest of the window paints half-finished.
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            outer = QRectF(self.rect()).adjusted(3.0, 3.0, -3.0, -3.0)
            inner = outer.adjusted(1.0, 1.0, -1.0, -1.0)

            if self._pm is None:
                disc = QLinearGradient(inner.topLeft(), inner.bottomRight())
                disc.setColorAt(0.0, _DISC_TOP)
                disc.setColorAt(1.0, _DISC_BOTTOM)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(disc)
                p.drawEllipse(inner)
                f = p.font()
                f.setPixelSize(max(9, int(inner.height() * 0.50)))
                f.setBold(True)
                p.setFont(f)
                p.setPen(QPen(QColor(246, 240, 255)))
                p.drawText(inner, Qt.AlignmentFlag.AlignCenter,
                           self.fallback_text)
            else:
                clip = QPainterPath()
                clip.addEllipse(inner)
                p.setClipPath(clip)
                src = QRectF(0.0, 0.0, float(self._pm.width()),
                             float(self._pm.height()))
                p.drawPixmap(inner, self._pm, src)
                p.setClipping(False)

            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QBrush(self._ring_brush(outer)), 1.7))
            p.drawEllipse(outer)
            # A single soft highlight arc sells the "glass lens" look.
            hi = QLinearGradient(inner.topLeft(), inner.center())
            hi.setColorAt(0.0, QColor(255, 255, 255, 70))
            hi.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setPen(QPen(QBrush(hi), 1.2))
            p.drawArc(inner.adjusted(inner.width() * 0.10,
                                     inner.height() * 0.06,
                                     -inner.width() * 0.30,
                                     -inner.height() * 0.42),
                      195 * 16, 150 * 16)

    # -- state ------------------------------------------------------------
    def refresh(self):
        """Re-read the avatar from disk (cheap: stat + cached pixmap)."""
        if self._override is not None:
            return self.set_image(self._override)
        self._pm = avatar_pixmap(self.who, self._diameter)
        self.update()

    def set_image(self, pixmap: QPixmap | None):
        """Show an unsaved crop (used by the live preview in the dialog)."""
        self._override = pixmap
        self._pm = (None if pixmap is None or pixmap.isNull()
                    else circular_pixmap(pixmap, self._diameter))
        self.update()

    def clear_override(self):
        self._override = None
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()


# ── crop viewport ──────────────────────────────────────────────────────────
class _CropCanvas(QWidget):
    """Circle viewport over an image: drag to pan, wheel to zoom."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_CROP_CANVAS, _CROP_CANVAS)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._img: QImage | None = None
        self._zoom = 1.0
        self._angle = 0.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._drag = None
        self.setAutoFillBackground(False)

    # -- geometry helpers -------------------------------------------------
    def _circle(self) -> QRectF:
        r = QRectF(self.rect()).adjusted(7.0, 7.0, -7.0, -7.0)
        side = min(r.width(), r.height())
        cx, cy = r.center().x(), r.center().y()
        return QRectF(cx - side / 2.0, cy - side / 2.0, side, side)

    def _src_side(self) -> float:
        if self._img is None:
            return 1.0
        return min(self._img.width(), self._img.height()) / self.zoom

    def _pan_limit(self) -> tuple[float, float]:
        if self._img is None:
            return (0.0, 0.0)
        s = self._src_side()
        return (max(0.0, (self._img.width() - s) / 2.0),
                max(0.0, (self._img.height() - s) / 2.0))

    def _transform(self, target_size: float) -> QTransform:
        """Place the visible source square onto a ``target_size`` circle."""
        assert self._img is not None
        sw, sh = float(self._img.width()), float(self._img.height())
        src_side = self._src_side()
        scale = target_size / max(src_side, 1e-6)
        cx = sw / 2.0 + self._offset_x
        cy = sh / 2.0 + self._offset_y
        t = QTransform()
        t.translate(target_size / 2.0, target_size / 2.0)
        t.scale(scale, scale)
        t.rotate(self._angle)
        t.translate(-cx, -cy)
        return t

    # -- state ------------------------------------------------------------
    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def angle(self) -> float:
        return self._angle

    def set_image(self, image: QImage | None):
        self._img = image
        self.reset_view()
        self.update()

    def set_zoom(self, z: float):
        self._zoom = max(0.5, min(6.0, float(z)))
        self._reclamp()
        self.update()

    def set_angle(self, deg: float):
        deg = (float(deg) + 180.0) % 360.0 - 180.0
        self._angle = deg
        self._reclamp()
        self.update()

    def _reclamp(self):
        lx, ly = self._pan_limit()
        self._offset_x = max(-lx, min(lx, self._offset_x))
        self._offset_y = max(-ly, min(ly, self._offset_y))

    def reset_view(self):
        self._zoom = 1.0
        self._angle = 0.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self.update()

    # -- input ------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._img is not None:
            self._drag = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None and self._img is not None:
            pos = event.position()
            d = pos - self._drag
            self._drag = pos
            circle = self._circle()
            scale = circle.width() / max(self._src_side(), 1e-6)
            self._offset_x -= float(d.x()) / max(scale, 1e-6)
            self._offset_y -= float(d.y()) / max(scale, 1e-6)
            self._reclamp()
            self.update()
        super().mouseMoveEvent(event)

    def wheelEvent(self, event):
        dy = event.angleDelta().y()
        if dy:
            self.set_zoom(self._zoom * (1.0015 ** dy))
            event.accept()
            return
        super().wheelEvent(event)

    # -- paint ------------------------------------------------------------
    def paintEvent(self, _event):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.fillRect(self.rect(), QColor(12, 7, 22, 255))
            circle = self._circle()

            if self._img is None:
                p.setPen(QPen(QColor(168, 139, 250, 170)))
                f = p.font()
                f.setPixelSize(13)
                p.setFont(f)
                p.drawText(circle, Qt.AlignmentFlag.AlignCenter,
                           "Drag an image in, or\npress “Choose image…” 📷")
                return

            # Everything outside the crop circle recedes.
            hole = QPainterPath(QRectF(self.rect()))
            ring = QPainterPath()
            ring.addEllipse(circle)
            p.fillPath(hole.subtracted(ring), QColor(6, 3, 12, 196))

            p.save()
            clip = QPainterPath()
            clip.addEllipse(circle)
            p.setClipPath(clip)
            p.fillRect(circle, QColor(24, 14, 40, 255))
            p.setTransform(self._transform(circle.width()))
            p.drawImage(0.0, 0.0, self._img)
            p.restore()

            # Rule-of-thirds guides.
            p.save()
            clip2 = QPainterPath()
            clip2.addEllipse(circle)
            p.setClipPath(clip2)
            p.setPen(QPen(QColor(255, 255, 255, 26), 0.7))
            for i in (1, 2):
                x = circle.left() + circle.width() * i / 3.0
                y = circle.top() + circle.height() * i / 3.0
                p.drawLine(int(x), int(circle.top()), int(x),
                           int(circle.bottom()))
                p.drawLine(int(circle.left()), int(y), int(circle.right()),
                           int(y))
            p.restore()

            # Ring + spokes so it reads as a live, movable crop.
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QBrush(self._conical()), 2.0))
            p.drawEllipse(circle)
            p.setPen(QPen(QColor(192, 132, 252, 120), 1.2))
            for deg in (0, 45, 90, 135, 180, 225, 270, 315):
                p.save()
                p.translate(circle.center())
                p.rotate(deg)
                p.drawLine(0, int(circle.height() / 2) + 3, 0,
                           int(circle.height() / 2) + 9)
                p.restore()

    def _conical(self) -> QConicalGradient:
        g = QConicalGradient(self._circle().center(), 0.0)
        g.setColorAt(0.00, QColor("#F472B6"))
        g.setColorAt(0.25, QColor("#C084FC"))
        g.setColorAt(0.50, QColor("#818CF8"))
        g.setColorAt(0.75, QColor("#C084FC"))
        g.setColorAt(1.00, QColor("#F472B6"))
        return g

    # -- export -----------------------------------------------------------
    def export_square(self) -> QPixmap | None:
        """Bake the current pan/zoom/rotate into a square PNG-sized pixmap."""
        if self._img is None:
            return None
        out = QImage(_CROP_EXPORT, _CROP_EXPORT, QImage.Format.Format_ARGB32)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # Transparent padding reads as "letterboxed" inside the circle; give
        # it the app's own backdrop so a wide zoom-out still looks deliberate.
        p.setTransform(self._transform(float(_CROP_EXPORT)))
        p.drawImage(0, 0, self._img)
        p.end()
        return QPixmap.fromImage(out)


# ── the dialog ─────────────────────────────────────────────────────────────
_DIALOG_QSS = """
QDialog#AvatarCropper { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
    stop:0 rgba(26, 14, 44, 250), stop:1 rgba(11, 6, 22, 252)); }
QFrame#CropCard { background: rgba(22, 13, 40, 210); border: 1px solid rgba(192,132,252,0.34);
    border-radius: 18px; }
QLabel { color: #EDE9FE; border: none; background: transparent; }
QPushButton { border-radius: 10px; padding: 8px 16px; font-size: 12px; font-weight: 600; }
QPushButton#CropPrimary { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
    stop:0 #A855F7, stop:1 #7C3AED); color: #FFFFFF; border: 1.5px solid #E879F9; }
QPushButton#CropPrimary:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
    stop:0 #C084FC, stop:1 #9333EA); }
QPushButton#CropGhost { background: rgba(255,255,255,0.06); color: #E9D5FF;
    border: 1px solid rgba(168, 85, 247, 0.42); }
QPushButton#CropGhost:hover { background: rgba(168, 85, 247, 0.30); color: #FFFFFF; }
QPushButton#CropDanger { background: rgba(239, 68, 68, 0.18); color: #FCA5A5;
    border: 1px solid rgba(248, 113, 113, 0.45); }
QPushButton#CropDanger:hover { background: rgba(239, 68, 68, 0.42); color: #FFFFFF; }
QPushButton:disabled { background: rgba(80, 60, 110, 0.28); color: rgba(233,213,255,0.4);
    border-color: rgba(147, 51, 234, 0.2); }
QSlider::groove:horizontal { height: 5px; background: rgba(255,255,255,0.10); border-radius: 3px; }
QSlider::sub-page:horizontal { background: #A855F7; border-radius: 3px; }
QSlider::handle:horizontal { background: #C084FC; border: 1.5px solid #E879F9;
    width: 13px; height: 13px; margin: -5px 0; border-radius: 8px; }
"""


class AvatarCropperDialog(QDialog):
    """Pick, pan, zoom, rotate, confirm - then the crop is saved by the caller."""

    def __init__(self, who: str = "user", title: str = "", parent=None):
        super().__init__(parent)
        self.who = who if who in _AVATAR_FILES else "user"
        self._result: QPixmap | None = None
        self._removed = False
        is_cel = self.who == "cel"
        self.setObjectName("AvatarCropper")
        self.setWindowTitle(title or ("✨ Cel's profile picture" if is_cel
                                      else "🖼️ Your profile picture"))
        self.setStyleSheet(_DIALOG_QSS)
        self.setMinimumSize(700, 430)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        head = QLabel(
            "Position your picture inside the circle - drag to move, scroll or "
            "slider to zoom, and rotate until it feels right. ✨"
            if not is_cel else
            "Give Cel a face of her own! Drag to move, scroll or slider to "
            "zoom, and rotate until she looks adorable. 🎀")
        head.setWordWrap(True)
        head.setStyleSheet("font-size: 12px; color: #DDD6FE;")
        root.addWidget(head)

        body = QHBoxLayout()
        body.setSpacing(16)

        self.canvas = _CropCanvas()
        body.addWidget(self.canvas)

        side = QVBoxLayout()
        side.setSpacing(12)
        self.preview = CircularAvatarLabel(who=self.who, diameter=132)
        self.preview.setToolTip("Live preview")
        side.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        cap = QLabel("Live preview")
        cap.setStyleSheet("font-size: 10px; color: #A78BFA;")
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(cap)

        side.addWidget(self._divider())
        side.addWidget(self._control_label("🔍 Zoom"))
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(50, 600)
        self.zoom_slider.setValue(100)
        self.zoom_slider.valueChanged.connect(self._on_zoom_slide)
        side.addWidget(self.zoom_slider)

        side.addWidget(self._control_label("🔄 Rotate"))
        self.rotate_slider = QSlider(Qt.Orientation.Horizontal)
        self.rotate_slider.setRange(-180, 180)
        self.rotate_slider.setValue(0)
        self.rotate_slider.valueChanged.connect(self.canvas.set_angle)
        side.addWidget(self.rotate_slider)

        self.btn_reset = QPushButton("↺ Reset view")
        self.btn_reset.setObjectName("CropGhost")
        self.btn_reset.clicked.connect(self._on_reset)
        side.addWidget(self.btn_reset)

        self.btn_pick = QPushButton("📷 Choose image…")
        self.btn_pick.setObjectName("CropGhost")
        self.btn_pick.clicked.connect(self._on_pick)
        side.addWidget(self.btn_pick)

        self.btn_remove = QPushButton("🗑 Remove picture")
        self.btn_remove.setObjectName("CropDanger")
        self.btn_remove.clicked.connect(self._on_remove)
        side.addWidget(self.btn_remove)

        side.addStretch(1)
        body.addLayout(side)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("CropGhost")
        btn_cancel.clicked.connect(self.reject)
        footer.addWidget(btn_cancel)
        self.btn_ok = QPushButton("✓ Confirm && Save")
        self.btn_ok.setObjectName("CropPrimary")
        self.btn_ok.setEnabled(False)
        self.btn_ok.clicked.connect(self._on_confirm)
        footer.addWidget(self.btn_ok)
        root.addLayout(footer)

        self._sync_preview()
        # Seed the viewport with the current picture so it can be re-cropped.
        existing = load_square_avatar(self.who)
        if existing is not None:
            self.canvas.set_image(existing.toImage())
            self.btn_remove.setEnabled(True)
        else:
            self.btn_remove.setEnabled(False)

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _control_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 11px; color: #C4B5FD; font-weight: bold;")
        return lbl

    @staticmethod
    def _divider() -> QFrame:
        ln = QFrame()
        ln.setFixedHeight(1)
        ln.setStyleSheet("background: rgba(192, 132, 252, 0.25); border: none;")
        return ln

    def _sync_preview(self):
        self.preview.set_image(self.canvas.export_square())
        self.btn_ok.setEnabled(self.canvas._img is not None)

    def _on_zoom_slide(self, value: int):
        self.canvas.set_zoom(value / 100.0)
        self._sync_preview()

    def _on_reset(self):
        self.canvas.reset_view()
        self.zoom_slider.setValue(100)
        self.rotate_slider.setValue(0)
        self._sync_preview()

    def _on_pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.heic *.heif);;"
            "All files (*)",
        )
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Can't use that image",
                                "Cellium couldn't read that file as an image. "
                                "Try a PNG, JPG or WEBP. 💔")
            return
        # Sanity cap so a 40 MP photo doesn't get painted huge.
        biggest = max(img.width(), img.height())
        if biggest > 4096:
            img = img.scaled(4096, 4096, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self.canvas.set_image(img)
        self.btn_remove.setEnabled(True)
        self._sync_preview()

    def _on_remove(self):
        self._removed = True
        self._result = None
        self.accept()

    def _on_confirm(self):
        square = self.canvas.export_square()
        if square is None:
            self.reject()
            return
        self._removed = False
        self._result = square
        self.accept()

    # -- results ----------------------------------------------------------
    def result_pixmap(self) -> QPixmap | None:
        return self._result

    def was_removed(self) -> bool:
        return self._removed


def run_avatar_flow(who: str, parent_widget=None,
                    on_changed=None) -> bool:
    """Open the cropper, persist the outcome, refresh the caller's labels.

    Shared by Settings and onboarding so the two never drift apart. Returns
    True when something on disk actually changed.
    """
    try:
        dlg = AvatarCropperDialog(who=who, parent=parent_widget)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        pm = dlg.result_pixmap()
        changed = False
        if pm is None:
            if avatar_file(who).exists():
                clear_avatar(who)
                changed = True
        else:
            changed = save_avatar(who, pm)
        bust_avatar_cache()
        try:
            if callable(on_changed):
                on_changed()
        except Exception as e:                                       # noqa: BLE001
            dev_log(f"pfp: on_changed hook failed: {e}")
        return changed
    except Exception as e:                                           # noqa: BLE001
        dev_log(f"pfp: avatar flow failed for {who}: {e}")
        return False


__all__ = [
    "AvatarCropperDialog",
    "CircularAvatarLabel",
    "AVATARS_DIR",
    "avatar_file",
    "avatar_pixmap",
    "bust_avatar_cache",
    "circular_pixmap",
    "clear_avatar",
    "load_square_avatar",
    "run_avatar_flow",
    "save_avatar",
]
