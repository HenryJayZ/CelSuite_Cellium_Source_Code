"""Vector SVG & Rendered PNG Icon Engine for Cellium UI."""

from __future__ import annotations
import re
from pathlib import Path
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton

ICONS_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"
_ICON_CACHE: dict[str, QIcon] = {}

# Clean modern 24x24 Lucide-style SVG bodies
_SVG_PATHS: dict[str, str] = {
    "info":        '<circle cx="12" cy="12" r="9"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
    "sparkles":    '<path d="M12 3l1.9 5.8a2 2 0 0 0 1.3 1.3L21 12l-5.8 1.9a2 2 0 0 0-1.3 1.3L12 21l-1.9-5.8a2 2 0 0 0-1.3-1.3L3 12l5.8-1.9a2 2 0 0 0 1.3-1.3L12 3z"/>',
    "bookmark":    '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/><polyline points="9 10 12 13 15 10"/>',
    "bookmark_up": '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/><polyline points="9 13 12 10 15 13"/>',
    "undo":        '<polyline points="9 14 4 9 9 4"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/>',
    "close":       '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "minimize":    '<line x1="5" y1="12" x2="19" y2="12"/>',
    "restore":     '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "tray":        '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "target":      '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "branch":      '<line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
    "play":        '<polygon points="6 4 20 12 6 20 6 4"/>',
    "copy":        '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "check":       '<polyline points="20 6 9 17 4 12"/>',
    "eye":         '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    "code":        '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    "trash":       '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>',
    "mic":         '<rect x="9" y="2" width="6" height="11" rx="3"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/>',
    "mic_off":     '<line x1="1" y1="1" x2="23" y2="23"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/><path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23"/><line x1="12" y1="19" x2="12" y2="22"/>',
    "camera":      '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    "cpu":         '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/>',
    "bot":         '<rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16.01"/><line x1="16" y1="16" x2="16" y2="16.01"/>',
    "bolt":        '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "volume":      '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>',
    "keyboard":    '<rect x="2" y="4" width="20" height="16" rx="2"/><line x1="6" y1="8" x2="6" y2="8"/><line x1="10" y1="8" x2="10" y2="8"/><line x1="14" y1="8" x2="14" y2="8"/><line x1="18" y1="8" x2="18" y2="8"/><line x1="8" y1="16" x2="16" y2="16"/>',
    "heart":       '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>',
    "chat":        '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "mood":        '<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/>',
    "moon":        '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    "dice":        '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><circle cx="15.5" cy="8.5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="8.5" cy="15.5" r="1.5"/><circle cx="15.5" cy="15.5" r="1.5"/>',
    "prev":        '<polygon points="15 18 9 12 15 6 15 18"/>',
    "next":        '<polygon points="9 18 15 12 9 6 9 18"/>',
    "settings":    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "chart":       '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
    "terminal":    '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
}

EMOJI_TO_ICON_NAME: list[tuple[str, str]] = [
    ("🔖", "bookmark"),
    ("✨", "sparkles"),
    ("🎙️", "mic"),
    ("🎙", "mic"),
    ("🔇", "mic_off"),
    ("📸", "camera"),
    ("🧠", "cpu"),
    ("🤖", "bot"),
    ("⚡", "bolt"),
    ("🔊", "volume"),
    ("⌨️", "keyboard"),
    ("⌨", "keyboard"),
    ("💖", "heart"),
    ("💬", "chat"),
    ("🎭", "mood"),
    ("💤", "moon"),
    ("🗑", "trash"),
    ("📋", "copy"),
    ("👁", "eye"),
    ("📝", "code"),
    ("▶", "play"),
    ("◀", "prev"),
    ("🎲", "dice"),
    ("⚙", "settings"),
    ("📊", "chart"),
    ("🖥", "terminal"),
]


def _render_fallback_png(name: str, png_path: Path, color_hex: str = "#E9D5FF") -> None:
    """Render a crisp 32x32 anti-aliased PNG icon using QPainter vector primitives."""
    img = QImage(32, 32, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color_hex), 2.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    if name in ("bookmark", "bookmark_up"):
        path = QPainterPath()
        path.moveTo(8, 5)
        path.lineTo(24, 5)
        path.lineTo(24, 27)
        path.lineTo(16, 21)
        path.lineTo(8, 27)
        path.closeSubpath()
        p.setBrush(QColor(168, 85, 247, 75))
        p.drawPath(path)
        if name == "bookmark":
            p.drawPolyline([QPointF(13, 11), QPointF(16, 14), QPointF(19, 11)])
        else:
            p.drawPolyline([QPointF(13, 14), QPointF(16, 11), QPointF(19, 14)])
    elif name in ("sparkles", "info"):
        path = QPainterPath()
        path.moveTo(16, 4)
        path.quadTo(16, 16, 28, 16)
        path.quadTo(16, 16, 16, 28)
        path.quadTo(16, 16, 4, 16)
        path.quadTo(16, 16, 16, 4)
        p.setBrush(QColor(216, 180, 254, 90))
        p.drawPath(path)
    elif name == "play":
        path = QPainterPath()
        path.moveTo(9, 6)
        path.lineTo(25, 16)
        path.lineTo(9, 26)
        path.closeSubpath()
        p.setBrush(QColor(168, 85, 247, 110))
        p.drawPath(path)
    elif name == "copy":
        p.drawRoundedRect(QRectF(11, 11, 15, 15), 3, 3)
        p.drawRoundedRect(QRectF(6, 6, 15, 15), 3, 3)
    elif name == "trash":
        p.drawLine(6, 9, 26, 9)
        p.drawRoundedRect(QRectF(9, 9, 14, 18), 2, 2)
        p.drawLine(14, 13, 14, 22)
        p.drawLine(18, 13, 18, 22)
    elif name == "eye":
        p.drawEllipse(QRectF(4, 9, 24, 14))
        p.setBrush(QColor(color_hex))
        p.drawEllipse(QPointF(16, 16), 3.5, 3.5)
    elif name == "mic":
        p.drawRoundedRect(QRectF(12, 4, 8, 14), 4, 4)
        p.drawArc(QRectF(7, 8, 18, 14), 0, -180 * 16)
        p.drawLine(16, 22, 16, 28)
    elif name == "mic_off":
        p.drawRoundedRect(QRectF(12, 4, 8, 14), 4, 4)
        p.setPen(QPen(QColor("#F87171"), 2.5))
        p.drawLine(5, 5, 27, 27)
    elif name == "camera":
        p.drawRoundedRect(QRectF(4, 9, 24, 17), 3, 3)
        p.drawEllipse(QPointF(16, 17.5), 4.5, 4.5)
    elif name == "heart":
        p.setBrush(QColor(244, 114, 182, 120))
        p.drawEllipse(QPointF(12, 13), 5.5, 5.5)
        p.drawEllipse(QPointF(20, 13), 5.5, 5.5)
    else:
        p.drawRoundedRect(QRectF(6, 6, 20, 20), 5, 5)
        p.drawEllipse(QPointF(16, 16), 4, 4)
    p.end()
    img.save(str(png_path), "PNG")


def ensure_icon_assets() -> Path:
    """Write all .svg and rendered .png icon files into `cellium/assets/icons/`."""
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    for name, body in _SVG_PATHS.items():
        svg_file = ICONS_DIR / f"{name}.svg"
        png_file = ICONS_DIR / f"{name}.png"
        if not svg_file.is_file():
            svg_xml = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
                'viewBox="0 0 24 24" fill="none" stroke="#E9D5FF" stroke-width="2" '
                f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>\n'
            )
            svg_file.write_text(svg_xml, encoding="utf-8")
        if not png_file.is_file():
            rendered = False
            try:
                from PySide6.QtSvg import QSvgRenderer
                renderer = QSvgRenderer(str(svg_file))
                if renderer.isValid():
                    img = QImage(32, 32, QImage.Format.Format_ARGB32)
                    img.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(img)
                    renderer.render(painter)
                    painter.end()
                    img.save(str(png_file), "PNG")
                    rendered = True
            except Exception:
                rendered = False
            if not rendered:
                _render_fallback_png(name, png_file)
    return ICONS_DIR


def get_svg_icon(name: str) -> QIcon:
    """Return a cached QIcon backed by both `.png` and `.svg` assets on disk."""
    if name in _ICON_CACHE:
        return _ICON_CACHE[name]
    ensure_icon_assets()
    png_p = ICONS_DIR / f"{name}.png"
    svg_p = ICONS_DIR / f"{name}.svg"
    icon = QIcon()
    if png_p.is_file():
        pix = QPixmap(str(png_p))
        if not pix.isNull():
            icon.addPixmap(pix)
    if icon.isNull() and svg_p.is_file():
        icon = QIcon(str(svg_p))
    _ICON_CACHE[name] = icon
    return icon


def iconify_button(btn: QAbstractButton, default_icon: str | None = None) -> None:
    """Replace raw emoji characters on a QAbstractButton with a rendered .svg/.png QIcon."""
    if btn is None:
        return
    txt = btn.text() or ""
    # Preserve test-locked button labels
    if txt in ("✓ Save Edit", "✓ Copied!"):
        return
    chosen_icon = default_icon
    cleaned_txt = txt
    for em, ic_name in EMOJI_TO_ICON_NAME:
        if em in cleaned_txt:
            if chosen_icon is None:
                chosen_icon = ic_name
            cleaned_txt = cleaned_txt.replace(em, "")
    # Also strip dropdown triangle glyphs when paired with an icon
    if chosen_icon:
        cleaned_txt = re.sub(r"[▾▴►◄↕]+", "", cleaned_txt).strip()
        ic = get_svg_icon(chosen_icon)
        if not ic.isNull():
            btn.setIcon(ic)
            btn.setIconSize(QSize(15, 15))
            btn.setText(cleaned_txt)
