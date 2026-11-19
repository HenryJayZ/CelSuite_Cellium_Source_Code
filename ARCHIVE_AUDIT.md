# Archive Feature Audit - Cerebrium / Cerebellium → Cellium

**Date:** 2026-10-02
**Method:** AST-based structural extraction (classes, functions, constants) across
every `.py` file in `Archived/Cerebras AI`, diffed against `Cellium/cellium/` and
`Cellium/_legacy/`. Followed by framework detection, lineage comparison, and
feature keyword frequency analysis. No file was modified.

---

## 1. Scope

| | |
|---|---|
| Archived Python | **114,133 lines across 78 files** |
| Cellium package | 13,463 lines across 26 modules |
| Cellium `_legacy` monolith | 9,760 lines |
| Duplicate/wasted | ~292 KB (`Cerebellium_Astra (copy).py`, byte-identical) |

---

## 2. Framework evolution - the lineage map

```
tkinter     Cerebrium v0.0 → v1.0 → Cerebellium.py → Cerebrium26.py
   ↓  migrated for licensing (GPL → LGPL)
PyQt6       Cerebellium_Astra.py (Sep 9) · CerebelliumQt.py (Sep 21)
   ↓  migrated to the LGPL binding
PySide6     Cerebellium Opus.py (Sep 11) · CelStudio_Cerebrium.py (Sep 21)
   ↓  refactored 2026-09-21 → 2026-09-25
CELLIUM     ui/services/core package  ← you are here
   ↓
[kivy]      Cerebellium Android Opus.py (Sep 9, 2,136 lines → Sep 11, 9,909 lines)
   ↓  abandoned toolkits
Kotlin      not yet started
```

**Verdict:** Cellium sits on the newest desktop lineage (`CelStudio_Cerebrium.py`
→ refactor). PySide6 is correct and current. The PyQt6 files and every tkinter
file are historical - do not port from them.

---

## 3. Lineage test: Opus is a *separate* branch

Compared `Cerebellium Opus.py` against `Cellium/_legacy/CelStudio_Cerebrium.py`:

| Metric | Shared |
|---|---|
| Classes | **0** |
| Functions | 18 |
| Constants | 2 (`DEVNULL`, `DOTALL`) |

**These are two independent codebases, not a before/after pair.** Any port is a
real merge, not a diff-revert. The shared functions are generic helpers.

---

## 4. Feature gap - what Cellium does *not* have

All of the following exist in the archive with **zero** equivalent in Cellium:

| Feature | Archive refs | Opus class(es) | Port difficulty |
|---|---|---|---|
| **Desktop pet / companion** | 486 | `FloatingPetWindow`, `CompanionStage`, `PetGrip` | Medium |
| **Hands-free voice control** | 190 | `HandsFreeListener` (Qt), `SpeechService` | Medium |
| **Typewriter text effect** | 67 | `Typewriter` | **Easy** |
| **Avatar / face factory** | 67 | `face_factory.py` (standalone, 52 KB) | Medium |
| **Particle / animated background** | 63 | `ParticleSystem`, `ParticleCanvas` | **Easy** |
| **Focus / pomodoro clock** | 33 | `FocusClock` | **Easy** |
| **Safe / redacting log viewer** | 26 | `RedactingFormatter`, `SafeTextBrowser`, `LiveLogs` | **Easy** |
| **Regression test harness** | 21 | `RegressionTests` (Opus), `MobileRegressionTests` | Medium |
| **Background job manager** | 12 | `ManagedJob`, `ProcessPool` | **Easy** |
| **Command palette (Ctrl+K)** | 9 | `CommandPalette` | **Easy** |
| **Chat history composer** | 9 | `HistoryComposer`, `HistoryLineEdit` | **Easy** |
| **OS agent service** | 3 | `OSAgent`, `OSAgentService` | See §6 |

Also unique to Opus and worth noting: `BlinkStudioDialog`, `AnimationLibrary`,
`AnimationPoint`, `StatusPill`, `ModelFinderDialog`, `HelpGuideDialog`,
`AgentPlan`/`AgentPlanError`/`AgentResult` (a planned-agent pipeline Cellium
does not have), `_AgentTask`.

---

## 5. Portability tiers

### Tier 1 - cheap, high value (PySide6 → PySide6, drop-in)
`CommandPalette`, `FocusClock`, `Typewriter`, `StatusPill`, `ParticleSystem`,
`HistoryComposer`, `HistoryLineEdit`, `ManagedJob`, `LiveLogs` +
`RedactingFormatter`. These are self-contained widget/logic classes with no
architectural coupling.

### Tier 2 - medium
Desktop pet trio (`FloatingPetWindow` + `CompanionStage` + `PetGrip`, plus the
`Sleepy.json` / `Waking.json` state files), `SpeechService` /
`HandsFreeListener`, the animation library (`AnimationLibrary`,
`AnimationPoint`, `BlinkStudioDialog`), `face_factory.py`, `RegressionTests`.

### Tier 3 - rewrite required
- **`Cerebellium Android Opus.py` (kivy, 9,909 lines).** Kivy is a completely
  different toolkit. Its mobile ideas (`ChatStore`, `RequestGate`,
  `LightingDirector`, `TouchButton`, `AnimationStore`) are *design references*,
  not portable code. This is the Kotlin work item.
- **`OSAgentService`** - see §6.

### Do not port
`Cerebellium_Astra.py` and `CerebelliumQt.py` (PyQt6, GPL - would contaminate
your LGPL PySide6 build), and all tkinter-era files.

---

## 6. ⚠️ Security gap present in *both* codebases

`Cellium/core/tools.py` → `ShellExecTool.execute()` runs:

```python
subprocess.run(command, shell=True, capture_output=True, timeout=timeout, cwd=os.getcwd())
```

with **no validation whatsoever** - no allow-list, no deny-list, no path checks.
The `command` string arrives verbatim from the LLM. Opus has a class named
`UnsafeCommand`, but it is a two-line `ValueError` subclass with a docstring; it
contains **no filtering logic**. Opus is not safer than Cellium here.

**Attack path:** Cellium can read files (`FileReadTool`) *and* run shell
commands. Prompt injection inside any file the agent reads - a cloned repo, a
downloaded document, a web page - can steer `shell_exec` into arbitrary commands.

**Recommendation:** port a real denylist *before* pointing Cellium at untrusted
content. This is new work, not a port; nothing usable exists in the archive.

---

## 7. Recoverable unfinished work

`Cerebellium Opus/face_factory.py` (51,997 bytes) is a **procedural face /
expression factory**, generated by a previous AI session. The transcripts are in
the same folder:

- `Tasklet_Extraction session 1.md` (691 lines) - analysis + schema discovery
- `Tasklet_Extraction session 2.md` (1,228 lines) - the generated `face_factory.py`

Injection is reversible: `Cerebellium Opus.py.face_factory-*.bak` (354 KB) and
`Cerebellium Android Opus.py.face_factory-*.bak` (91 KB) are pre-injection
snapshots. This is finished, tested-in-archive work that was never ported forward.

---

## 8. Other findings

- `Cerebellium Android Opus.py` exists in **two generations**: 91,833 bytes
  (Sep 9) at `Cerebellium/` and 887,487 bytes (Sep 11) in `Cerebellium Opus/`.
  Different apps, same name.
- `Cerebellium Opus.py` mixes 4 `PyQt*` references into a PySide6 file - a latent
  binding bug; `PySide6` and `PyQt` both resolve at runtime only if both bindings
  are installed.
- Opus uses `gtts` + `asyncio` for TTS. Cellium uses `edge-tts` + `kokoro`.
  Prefer Cellium's stack; do not port the Opus TTS layer.
- `Cerebrium26.py` and `Cerebrium HTML/Cerebrium26.py` are duplicate tkinter
  generations (2,244 lines each).

---

## 9. Recommended order

1. **Add the shell-command denylist** to `tools.py` (new work - highest risk reduction).
2. Port **Tier 1** classes (8 items, all PySide6, no coupling) into new
   `cellium/ui/widgets/` and `cellium/core/` modules.
3. Recover **`face_factory.py`** + its animation library as
   `cellium/ui/avatar/`.
4. Port the **desktop pet** trio and its `Sleepy`/`Waking` state.
5. Treat **Android Opus** as a design brief for the Kotlin rewrite, not code.

---

## Appendix - Opus class inventory (38 classes Cellium lacks)

```
AgentPlan              AgentPlanError        AgentResult
Animation              AnimationLibrary      AnimationPoint
AudioService           BlinkStudioDialog     CerebelliumApp
ChatPanel              CommandPalette        CompanionStage
Effect                 FloatingPetWindow     FocusClock
HelpGuideDialog        HistoryComposer       LiveLogs
LogViewerDialog        ManagedJob            ModelFinderDialog
OSAgent                OSAgentService        ParticleCanvas
ParticleSystem         PetGrip               ProcessPool
RedactingFormatter     RegressionTests       SafeTextBrowser
Settings               SettingsDialog        SpeechService
StatusPill             Typewriter            UnsafeCommand
_AgentSignals          _AgentTask
```

Android Opus (kivy) - 14 classes Cellium lacks:
```
AIClient               AnimationStore        CerebelliumMobileApp
ChatBubble             ChatScreen            ChatStore
LightingDirector       MobileRegressionTests MobileSettings
RequestGate            RequestIdentity       SettingsFile
SettingsScreen         TouchButton
```