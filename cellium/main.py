import sys, os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QCoreApplication
from PySide6.QtGui import QIcon
from cellium.core.config import ASSETS_DIR
from cellium.core.utils import generate_sound_library
from cellium.ui.main_window import CelStudioCerebrium
from cellium.core.logger import dev_log

MD_SAMPLE = """## Markdown Showcase

Cel renders **full markdown** live - tables, rules, lists and more ✨

### Features

#### Included Blocks

- Tables with neon glass styling
- Horizontal rules & heading glyphs
- Task lists with checkboxes
- *Italic*, **bold**, ~~strikethrough~~ and `inline code`

| Block | Supported | Notes |
| --- | :---: | --- |
| Headings h1-h6 | ✅ | Glyph prefixes auto-injected |
| Tables | ✅ | Neon purple header row |
| Horizontal rules | ✅ | Divider ornament |
| Task lists | ☑ | Checkbox glyph conversion |

---

1. Ordered list item one
2. Ordered list item two
   - nested bullet with `code` and **inline bold**

> Blockquote: Glassmorphism, neon glow and liquid glass all the way down 🎀

- [x] Approved markdown pipeline
- [ ] Click the eye icon (👁) to flip raw source

Final line with a [neon link](https://example.com) and ~~deprecated~~ text.
"""


def _inject_md_sample(window):
    from PySide6.QtCore import Qt
    from cellium.ui.chat.bubble import MessageBubbleNew
    bubble = MessageBubbleNew(
        "assistant", MD_SAMPLE,
        meta={"time": "12:00", "model": "markdown-sample", "turn_tokens": 0, "think_time": 0.0},
        chat_app=window,
    )
    window.chat_substack.setCurrentIndex(1)
    window.chat_layout.insertWidget(window.chat_layout.count() - 1, bubble, 0, Qt.AlignmentFlag.AlignLeft)
    window.update_all_bubble_geometries()
    window.scroll_bottom(force=True)
    dev_log("[MD_SAMPLE] injected markdown showcase bubble")


def _capture_markdown_shots(window, path):
    pix = window.grab()
    pix.save(path, "PNG")
    dev_log(f"[SCREENSHOT_OK] markdown pretty capture: {path}")
    lay = getattr(window, "chat_layout", None)
    if lay is not None:
        for i in range(lay.count()):
            item = lay.itemAt(i)
            w = item.widget() if item else None
            if hasattr(w, "_toggle_eye_mode"):
                try:
                    w._toggle_eye_mode()
                except Exception as e:
                    dev_log(f"[MD_SAMPLE] eye toggle failed: {e}")

    def raw_shot():
        raw_path = path[:-4] + "_raw.png" if path.lower().endswith(".png") else path + "_raw.png"
        pix2 = window.grab()
        pix2.save(raw_path, "PNG")
        dev_log(f"[SCREENSHOT_OK] markdown raw capture: {raw_path}")
        QCoreApplication.quit()

    QTimer.singleShot(700, raw_shot)


def main():
    app = QApplication(sys.argv)

    # ── Font substitution: fix the root cause of HarfBuzz bearing spam ──────
    # Qt's font fallback chain loads every system font to measure glyphs.
    # "Noto Sans Thai UI" has a known HarfBuzz bearing bug that fires one
    # warning per glyph table - hundreds of lines per session.
    # QFont.insertSubstitution redirects the broken font to a working one
    # so Qt's shaper never attempts to load it at all.
    from PySide6.QtGui import QFont
    for _broken in ("Noto Sans Thai UI", "Noto Sans Thai UI Regular",
                    "Noto Sans Thai UI Bold", "Noto Sans Thai UI Light"):
        QFont.insertSubstitution(_broken, "Noto Sans")
    
    # Disable scroll wheel on comboboxes/sliders unless focused
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QComboBox, QAbstractSpinBox, QSlider
    class WheelEventFilter(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.Wheel:
                if isinstance(obj, (QComboBox, QAbstractSpinBox, QSlider)) and not obj.hasFocus():
                    return True  # Block event
            return super().eventFilter(obj, event)
            
    wheel_filter = WheelEventFilter(app)
    app.installEventFilter(wheel_filter)

    # The tray owns the lifecycle once the window hides into it.
    try:
        app.setQuitOnLastWindowClosed(False)
    except Exception:
        pass
    icon_path = ASSETS_DIR / "icon.webp"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = CelStudioCerebrium()
    window.show()

    # Defer non-critical sound synthesis check so the window appears on screen instantly
    QTimer.singleShot(200, generate_sound_library)

    if "--md-sample" in sys.argv:
        idx = sys.argv.index("--md-sample")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("--"):
            out_path = sys.argv[idx + 1]
        else:
            out_path = "/tmp/md_pretty.png"
        QTimer.singleShot(400, lambda: _inject_md_sample(window))
        QTimer.singleShot(1700, lambda: _capture_markdown_shots(window, out_path))
    elif "--auto-screenshot" in sys.argv:
        idx = sys.argv.index("--auto-screenshot")
        path = sys.argv[idx + 1]
        def capture():
            pix = window.grab()
            pix.save(path, "PNG")
            dev_log(f"[SCREENSHOT_OK] Captured offscreen window screenshot at: {path}")
            os._exit(0)
        QTimer.singleShot(1500, capture)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
