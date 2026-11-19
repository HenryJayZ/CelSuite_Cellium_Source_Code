#!/usr/bin/env python3
"""Cellium Visual QA harness - boots the app offscreen and captures PNG evidence.

Usage:
    QT_QPA_PLATFORM=offscreen /home/henry/Documents/Projects/Python/venv/bin/python \
        tools/visual_qa.py [output_dir]

Captures: main chat, toast stacking + reflow glide, analytics month/year picker,
Focus Studio, Avatar Studio, particle mouse-wake.

Design notes
------------
* Every shot is a FULL-WINDOW render (`WIN.grab()`). Standalone `child.grab()`
  skips the wallpaper behind transparent pages, which is why earlier evidence
  showed white canvases with light headings rendered white-on-white.
* Stages are CHAINED: each step schedules the next only after its own grab has
  completed. Independent absolute timers collided, because a 1280x800 grab with
  frosted glass can block the event loop long enough for the next stage to fire
  first (evidence: the "monthly" shot contained the Focus page).
* Toasts type themselves out (typewriter) and hold for 5 s. We wait for the
  text to finish typing, prove the reflow glide, then clear them so later page
  shots stay clean.
* Zero side effects on saved settings/chats (mirrors tools/regression.py's
  stubbed persistence).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else
           "/home/henry/Documents/Projects/OpenCode/tmp/cellium_shots")
OUT.mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

# Stub persistence exactly like tools/regression.py so nothing real is written.
import cellium.core.utils as _utils  # noqa: E402
for _name in ("save_json",):
    if hasattr(_utils, _name):
        setattr(_utils, _name, lambda *a, **k: None)

from cellium.ui.main_window import CelStudioCerebrium  # noqa: E402

WIN = CelStudioCerebrium()


def _later(ms: int, fn) -> None:
    QTimer.singleShot(ms, fn)


def _grab(name: str) -> None:
    """Save a full-window render - the only capture that matches the user's eyes."""
    try:
        WIN.grab().save(str(OUT / f"{name}.png"))
        print(f"📸 {name}.png")
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ {name}: {exc}")


def _clear_toasts() -> None:
    """Kill any toast still on screen so later page shots stay clean."""
    for t in list(getattr(WIN, "_active_morph_toasts", []) or []):
        try:
            t._timer.stop()
            t.hide()
            t.deleteLater()
        except Exception:
            pass
    try:
        WIN._active_morph_toasts.clear()
    except Exception:
        pass


# ── 02/03: toast stacking + reflow glide ─────────────────────────────────────
def stage_toasts(done) -> None:
    WIN.show_chat_view()
    for i, (msg, icon) in enumerate((
            ("Cel replied! (1,024 tokens in 3.4s) 💖", "✓"),
            ("Model cached locally - zero data used 💾", "💾"),
            ("Persona preset 'Sassy' restored 💜", "🎭"),
            ("Queued message will send next 📬", "📬"))):
        QTimer.singleShot(i * 120, lambda m=msg, ic=icon: WIN.show_toast(m, icon=ic))

    def shot_stack() -> None:
        _grab("02_toast_stack")
        _later(200, dismiss_bottom)

    def dismiss_bottom() -> None:
        toasts = getattr(WIN, "_active_morph_toasts", [])
        if toasts:
            lowest = min(toasts, key=lambda t: getattr(t, "slot_idx", 0))
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtCore import QPointF, QEvent
            ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(10, 10),
                             Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                             Qt.KeyboardModifier.NoModifier)
            lowest.mousePressEvent(ev)
        _later(1600, shot_glide)

    def shot_glide() -> None:
        _grab("03_toast_glide_after_dismiss")
        _later(200, finish)

    def finish() -> None:
        _clear_toasts()
        _later(200, done)

    # Typewriter needs ~1.2 s after the last toast; 2 s is safely past it.
    _later(2000, shot_stack)


# ── 04/05/06: analytics 14-day / October 2026 / Year 2026 ────────────────────
def stage_analytics(done) -> None:
    try:
        av = getattr(WIN, "analytics_view", None)
        if av is None:
            print("⚠️ no analytics_view on the window")
            done()
            return
        # Rich fake history: several days, months, models.
        days = []
        for d in range(1, 28):
            days.append({"day": f"2026-09-{d:02d}", "tokens": 1200 + d * 37,
                         "model": "⚡ gemini-2.5-flash", "chars": 5000, "seconds": 4.0})
            if d % 3 == 0:
                days.append({"day": f"2026-09-{d:02d}", "tokens": 300 + d * 11,
                             "model": "📁 offline:Qwen3-4B", "chars": 1200, "seconds": 9.0})
        for d in range(1, 21):
            days.append({"day": f"2026-10-{d:02d}", "tokens": 900 + d * 53,
                         "model": "⚡ groq/llama-3.3-70b", "chars": 4200, "seconds": 3.1})
        WIN.analytics_data = {"turns": days}
        WIN.open_analytics_view()
        av.set_data({"turns": days})

        def shot_14d() -> None:
            _grab("04_analytics_14d")
            _later(150, pick_month)

        def pick_month() -> None:
            av.combo_analytics_mode.setCurrentIndex(1)    # Monthly Breakdown
            av.combo_analytics_month.setCurrentIndex(10)  # October
            _later(300, shot_month)

        def shot_month() -> None:
            _grab("05_analytics_oct2026")
            _later(150, pick_year)

        def pick_year() -> None:
            av.combo_analytics_mode.setCurrentIndex(2)    # Yearly Overview
            _later(300, shot_year)

        def shot_year() -> None:
            _grab("06_analytics_year")
            _later(200, done)

        _later(250, shot_14d)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ analytics stage: {exc}")
        done()


# ── 07: Focus Studio (header + ring driven through the real signal) ──────────
def stage_focus(done) -> None:
    try:
        clock = getattr(WIN, "focus_clock", None)
        if clock is None:
            print("⚠️ no focus_clock on window")
            done()
            return
        WIN.open_focus_clock_view()
        clock._rounds_today = 3
        clock.rounds_changed.emit(3)

        def shot() -> None:
            _grab("07_focus_studio")
            _later(200, done)

        _later(350, shot)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ focus stage: {exc}")
        done()


# ── 08: particle mouse-wake over the real ambient canvas ─────────────────────
def stage_particles(done) -> None:
    try:
        from cellium.ui.widgets.particles import ParticleCanvas
        WIN.show_chat_view()
        pc = getattr(WIN, "particles", None)
        if pc is None or not pc.isVisible():
            pc = ParticleCanvas(WIN)
            pc.setGeometry(140, 120, 620, 420)
            pc.show()
            pc.raise_()
        pc.set_count(90)
        pc.set_opacity(0.9)
        # Simulate a mouse flick through the field (velocity-scaled repulsion).
        pc._mouse_pos = (pc.width() * 0.5, pc.height() * 0.5)
        pc._mouse_speed = 34.0
        # Zero-CPU rule: the canvas suspends itself while a chat is open, so
        # force a short animated burst against the paused field so the wake
        # shot still shows mouse interaction.
        pc._paused = False
        pc._timer.start()
        pc._cursor_poll.start()

        def shot() -> None:
            _grab("08_particles_wake")
            _later(200, done)

        _later(600, shot)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ particles stage: {exc}")
        done()


# ── 09: Avatar Studio ────────────────────────────────────────────────────────
def stage_studio() -> None:
    try:
        st = getattr(WIN, "avatar_view", None)
        if st is None:
            print("⚠️ no avatar_view on window")
            return
        WIN.open_avatar_view()
        st.ensure_loaded(blocking=True)

        def shot() -> None:
            _grab("09_avatar_studio")
            _later(200, _app.quit)

        _later(500, shot)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ studio stage: {exc}")
        _app.quit()


# ── 00: welcome page with painted orb + typewriter greeting ───────────────────
def stage_welcome(done) -> None:
    """Show the welcome page, let the typewriter finish, grab, then move on.

    Also captures the big new expressions (surprised / flustered) and the
    spam-click rage mode (red, angry, dodging) so regressions in the pose
    blending are visible at a glance.
    """
    WIN.chat_substack.setCurrentIndex(0)  # welcome page is index 0
    WIN._roll_new_chat_greeting()         # rolls greeting + starts typewriters
    # Title types at ~55 cps, sub at ~45 cps, longest ~30 chars each → ~2.5 s total

    def shot_surprised() -> None:
        WIN.animated_orb.set_mood("surprised", hold=6.0)
        _later(600, lambda: (_grab("00b_welcome_surprised"), _later(200, shot_flustered)))

    def shot_flustered() -> None:
        WIN.animated_orb.set_mood("flustered", hold=6.0)
        _later(600, lambda: (_grab("00c_welcome_flustered"), _later(200, shot_pissed)))

    def shot_pissed() -> None:
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        orb = WIN.animated_orb
        orb.hovered = True
        orb._cursor_local = lambda: QPointF(6.0, 6.0)  # pointer poking top-left
        ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(10, 10),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        for _ in range(6):
            orb.mousePressEvent(ev)

        def after_pissed() -> None:
            orb.hovered = False
            try:
                del orb._cursor_local
            except AttributeError:
                pass
            orb._annoy = 0.0
            orb.set_mood("calm", hold=2.0)
            done()

        _later(900, lambda: (_grab("00d_welcome_pissed"), _later(200, after_pissed)))

    _later(2800, lambda: (_grab("00_welcome"), _later(200, shot_surprised)))


def main() -> None:
    WIN.resize(1280, 800)
    WIN.show()
    _app.processEvents()

    def after_welcome() -> None:
        # Leave the welcome page, grab the live chat, then chain the rest.
        WIN.show_chat_view()

        def grab_chat() -> None:
            _grab("01_main_chat")
            stage_toasts(
                lambda: stage_analytics(
                    lambda: stage_focus(
                        lambda: stage_particles(stage_studio))))

        _later(300, grab_chat)

    _later(400, lambda: stage_welcome(after_welcome))
    _later(30000, _app.quit)  # hard safety net
    _app.exec()
    print(f"🏁 done → {OUT}")


if __name__ == "__main__":
    main()
