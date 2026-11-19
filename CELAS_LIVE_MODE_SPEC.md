# 🎙️ CelAS Live Mode - Implementation Spec

**Owner:** CelAgent (manager) · **Implementer:** Space Bunny (coder)
**Status:** spec only - nothing built yet. All APIs below were **verified on disk**, not assumed.

---

## 0. The dream
A **Live** button beside send, like ChatGPT / Gemini. Press it and the **entire GUI
clears away** - topbar, sidebar, chat scroll, input box, status bar all hide - leaving
nothing but **Cel, full screen, at maximum size**. You talk with your voice. She
answers with her voice, live, her face reacting while she talks. **Hang up (📞) and the
whole GUI comes back exactly as it was.**

Full immersion. Same process, same session, same model. No new window, no second app.

---

## 1. What already exists - DO NOT REBUILD THESE

```python
# cellium/services/audio_stt.py
class STTSignals(QObject):
    single_result  = Signal(str, str)      # (sid, transcript)
    multi_results  = Signal(dict)
    error          = Signal(str)
    rms_update     = Signal(float)         # mic level -> VU meter
    status_update  = Signal(str)
class STTWorker(QThread): ...
class AudioRecordSignals(QObject):
    finished = Signal(bytes); error = Signal(str)
class AudioRecordWorker(QThread): ...

# cellium/services/audio_tts.py
class StreamPlayer: ...
class KokoroStreamingWorker(QObject):
    chunk_played = Signal(int, int)       # (played, total)
    finished     = Signal(); error = Signal(str)
class EdgeTTSStreamingWorker(QObject):
    finished = Signal(); error = Signal(str)

# cellium/ui/avatar/studio.py
class AvatarStage(QWidget):        # custom-painted stage
    def dispose(self) -> None: ...
class AvatarStudioWidget(QWidget):
    def ensure_loaded(self, *, blocking: bool = False) -> None: ...
    def sync_companion(self, visible: bool) -> None: ...
    def dispose(self) -> None: ...

# cellium/ui/avatar/
from .schema   import AvatarExpression, AvatarPoint
from .library  import AvatarLibrary          # 1,520 expressions, .get(gender, name)
from .widget   import AvatarView            # renders an expression, blink, scale
from .pet      import MOODS, CompanionStage # 19 moods + _guess_mood(text)

# cellium/ui/main_window.py - the chrome to hide
self.chat_scroll   = QScrollArea()   # :452
self.chat_content  = <widget>        # :467  chat_scroll.setWidget(...)
self.lbl_chat_title = QLabel(...)    # :380
self.active_tts_worker / active_tts_thread / active_tts_bubble  # :111-113
```

**1,520 expressions** are on disk at `cellium/ui/avatar/Anim/<Gender>/*.json`,
76 base × 9 style modifiers, 12 primitives (`eyelid eyebrow icon stem bottom_bar
mid_bar exclamation blush perm_blush tear cartoon_sweat dust`).

---

## 2. New files to create

```
cellium/ui/live/__init__.py
cellium/ui/live/live_mode.py      # the shell: LiveModeController + LiveStage
cellium/ui/live/talk_animation.py # mouth movement while she speaks
cellium/ui/live/captions.py       # bottom caption bar
```

Keep `core/` Qt-free (AGENTS.md invariant 2). All of the above is `ui/`.

---

## 3. State machine

```
IDLE ──press Live──► LISTENING ──speech detected──► THINKING
  ▲                     │                              │
  │                  (silence 900ms)                  │first token
  │                     ▼                              ▼
  └────hang up────  SPEAKING ◄──tts chunk── SPEAKING ◄──┘
```

| State | Avatar | Caption bar | Mic |
|---|---|---|---|
| `IDLE` | calm idle expression, slow blink | hidden | closed |
| `LISTENING` | attentive; eyes follow VU level | "Listening…" + live VU bar | **open** |
| `THINKING` | `MOODS["thinking"]`, slight sway | "Cel is thinking…" | open (keep hot) |
| `SPEAKING` | current mood + **talk animation** | live word-by-word words | open |

Transitions must be **idempotent** and **re-entrant**: barge-in (user talks while she
speaks) must cancel TTS and go back to `LISTENING`, not queue.

---

## 4. Hiding / restoring the GUI

`main_window` must keep references to its own top-level sections. **Do not rebuild
the UI on exit - hide and show.** Rebuilding loses scroll position and re-triggers
layout costs (that is bug #1, "switching chats is slow").

```python
self._live_saved_visibility = {}   # widget -> wasVisible
def _enter_live(self):
    for w in self._live_hide_targets():      # topbar, sidebar, chat_scroll,
        self._live_saved_visibility[w] = w.isVisible()   # input box, status bar
        w.setVisible(False)
    self._live_stage.setVisible(True)        # CelAS full-screen
def _exit_live(self):
    self._live_stage.setVisible(False)
    for w, was in self._live_saved_visibility.items():
        w.setVisible(was)
    self._live_saved_visibility.clear()
```

Guard: `if self._live_active: return` so a double-click can't double-hide.
`closeEvent` must call `_exit_live()` cleanup **and** tear down mic + TTS workers.

---

## 5. Talk animation - the fun part

The expressions are **static point sets**. While `SPEAKING`, modulate the mouth
primitives (`stem`, `bottom_bar`, `mid_bar`) on a timer at ~12 Hz.

**Do NOT mutate the cached `AvatarExpression`.** Copy the points, transform, hand a
fresh expression to `AvatarView.set_expression()`:

```python
def talking_expression(base: AvatarExpression, openness: float) -> AvatarExpression:
    """openness 0.0 = closed mouth, 1.0 = widest."""
    out = []
    for p in base.points:
        if p.kind == "stem" and not p.left:
            out.append(AvatarPoint(p.x, p.y + 7.0 * openness, p.kind, p.left))
        elif p.kind in ("bottom_bar", "mid_bar"):
            out.append(AvatarPoint(p.x, p.y + 5.0 * openness, p.kind, p.left))
        else:
            out.append(p)
    return base.with_points(out)
```

Drive `openness` from the actual audio: `KokoroStreamingWorker.chunk_played` tells you
progress; combine a smoothed pseudo-random envelope with progress so the mouth keeps
moving between chunks (otherwise it freezes during long gaps).

Blink must **keep working** during speech - `AvatarView` already handles that, so
never rebuild the `AvatarView`, only swap expressions.

---

## 6. Mood per turn

```python
from cellium.ui.avatar.pet import CompanionStage
mood = CompanionStage._guess_mood(reply_text)      # already written & tested
expr = library.get(gender, MOODS[mood][0]) or library.get(gender, MOODS["idle"][0])
```
Reuse it. Do **not** write a second sentiment function - that is exactly how the two
copies of the keybind map drifted apart in the first place.

---

## 7. Threading rules (this app has already been bitten)

- **Never** touch a widget from a worker thread. `STTWorker` / TTS workers emit signals;
  connect them to slots on the UI thread. `AGENTS.md` invariant 1.
- **Never** call `QTimer.singleShot` inside a worker.
- **Every** worker `run()` must be wrapped so a crash emits a terminal signal - both
  `AgentWorker` and `GenerationWorker` in `services/ai_workers.py` now have this
  pattern (`run()` → `try: self._run_impl() except: emit error`). **Copy it.**
- Mic and TTS must be stoppable from the UI thread. Never block on `.wait()`.

---

## 8. Definition of done - verify each, don't assume

1. Press **Live** → every panel hides within one frame, no flicker, no relayout flash
2. Avatar renders **large** and centred; `ensure_loaded(blocking=False)` used so the
   first press is not a 2-second freeze
3. Mic opens; VU meter moves when you speak; silence for 900 ms triggers a turn
4. Transcript appears in the caption bar
5. Cel's face changes to `thinking`, then to a mood matching her reply
6. **Mouth actually moves while audio plays** (watch for this - it is the whole point)
7. Barge-in: talk over her → she stops talking and listens
8. **📞 hang up restores the GUI exactly** - same scroll position, same session
9. Hang up **releases the mic** (check with `pactl list short sources` that no stream
   is left open - a leaked mic is the classic bug here)
10. Press Live again → works, no duplicate workers, no crash
11. Closing the window mid-call does not hang or warn
12. `python tools/regression.py` still exits 0

---

## 9. Suggested build order
1. `live_mode.py` shell + hide/restore + the **Live** button - *get the GUI clearing and
   restoring first*, with a static avatar. Smallest slice that proves the riskiest part.
2. `AvatarStage` big avatar + mood switching (no audio yet)
3. Talk animation
4. Mic → STT → send
5. TTS playback + barge-in
6. Regression checks for all of the above

---

## 10. Manager's note
Every significant bug found in this codebase so far was **wiring** - correct code that
was never connected to its caller (`format_cel_markdown`, the `AgentWorker.run` crash
swallow, the frost `drawPixmap` that threw on every paint while all tests passed).
**After building each slice, run it and look at it.** A green suite is necessary and
not sufficient - that has been proven here three times.