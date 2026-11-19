"""Ctrl+K command palette.

Qt widget. Ported in spirit from `CommandPalette` in the archived
`Cerebellium Opus.py`, which had no counterpart in Cellium.

Two pieces:

``CommandRegistry``
    A flat, ordered list of ``Command`` records with fuzzy subsequence matching.
    Qt-free, so it can be populated and unit-tested without a display.

``CommandPaletteDialog``
    The popup. Construct with a registry, or call
    ``main_window.install_command_palette(registry)`` to have it bind Ctrl+K
    automatically.

Matching is a subsequence test ("cnp" finds "New Chat Preview"), scored so that
contiguous and word-boundary hits rank first. That is enough for a few hundred
commands and avoids a dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QVBoxLayout, QWidget,
)

__all__ = ["Command", "CommandRegistry", "CommandPaletteDialog", "fuzzy_score"]


def fuzzy_score(needle: str, haystack: str) -> Optional[int]:
    """Return a lower-is-better score, or None when not a subsequence.

    Rewards: early start, contiguous runs, and matches at word boundaries.
    """
    if not needle:
        return 0
    n = needle.lower()
    h = haystack.lower()
    pos = 0
    score = 0
    run = 0
    for i, ch in enumerate(n):
        found = h.find(ch, pos)
        if found < 0:
            return None
        if found == pos and pos > 0:
            run += 1
            score -= 3 * run          # contiguous run bonus
        else:
            run = 0
        score += found - pos          # gap penalty
        if found == 0 or h[found - 1] in " -_/.":
            score -= 4                 # word-boundary bonus
        score += found * 0.1          # prefer earlier matches
        pos = found + 1
    return max(0, int(score))


@dataclass
class Command:
    title: str
    action: Callable[[], None]
    category: str = "General"
    shortcut: str = ""
    keywords: str = ""
    enabled: Callable[[], bool] = lambda: True

    @property
    def search_blob(self) -> str:
        return f"{self.title} {self.category} {self.keywords}".strip()


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: List[Command] = []
        self._seen: set[str] = set()

    def add(self, command: Command) -> Command:
        if command.title in self._seen:
            self.remove(command.title)
        self._seen.add(command.title)
        self._commands.append(command)
        return command

    def register(self, title: str, action: Callable[[], None], **kw) -> Command:
        return self.add(Command(title=title, action=action, **kw))

    def remove(self, title: str) -> None:
        self._commands = [c for c in self._commands if c.title != title]
        self._seen.discard(title)

    def clear(self) -> None:
        self._commands.clear()
        self._seen.clear()

    def __len__(self) -> int:
        return len(self._commands)

    def __iter__(self):
        return iter(self._commands)

    @property
    def commands(self) -> List[Command]:
        return list(self._commands)

    def search(self, query: str, limit: int = 50) -> List[Command]:
        """Ranked fuzzy matches. An empty query returns everything in order."""
        if not query.strip():
            return [c for c in self._commands if _safe_enabled(c)][:limit]
        scored: List[tuple] = []
        for c in self._commands:
            if not _safe_enabled(c):
                continue
            score = fuzzy_score(query, c.search_blob)
            if score is not None:
                scored.append((score, c.title, c))
        scored.sort(key=lambda t: (t[0], t[1]))
        return [c for _, _, c in scored[:limit]]

    def conflicts_with_shortcut(self, seq: str) -> List[Command]:
        return [c for c in self._commands if c.shortcut and c.shortcut == seq]


def _safe_enabled(command: Command) -> bool:
    try:
        return bool(command.enabled())
    except Exception:
        return False


class CommandPaletteDialog(QDialog):
    """Fuzzy-searchable action launcher."""

    command_activated = Signal(str)

    def __init__(self, registry: CommandRegistry, parent: QWidget | None = None):
        super().__init__(parent)
        self.registry = registry
        self.setWindowTitle("Command Palette")
        self.setModal(True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.resize(620, 420)
        self._results: List[Command] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a command…   (↑ ↓ to move, Enter to run, Esc to close)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refresh)
        self.search.returnPressed.connect(self._activate_selected)

        self.list = QListWidget()
        self.list.itemActivated.connect(lambda _: self._activate_selected())
        self.list.itemClicked.connect(lambda _: self._activate_selected())

        self.hint = QLabel("")
        self.hint.setStyleSheet("color:#64748b;font-size:11px;")

        frame = QFrame()
        frame.setStyleSheet(
            "QFrame{background:#171530;border:1px solid rgba(167,139,250,0.30);"
            "border-radius:12px;}")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(12, 12, 12, 12)
        inner.setSpacing(8)
        inner.addWidget(self.search)
        inner.addWidget(self.list)
        inner.addWidget(self.hint)

        root.addWidget(frame)

    # ── behaviour ────────────────────────────────────────────────────────
    def show_palette(self) -> None:
        self.search.clear()
        self._refresh("")
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()

    def _refresh(self, query: str) -> None:
        self.list.clear()
        self._results = self.registry.search(query)
        for cmd in self._results:
            label = cmd.title
            if cmd.shortcut:
                label += f"    {cmd.shortcut}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, cmd.title)
            item.setToolTip(f"{cmd.category}")
            self.list.addItem(item)
        total = len(self.registry)
        shown = len(self._results)
        self.hint.setText(
            f"{shown} of {total} commands" if query.strip() else f"{total} commands - press Ctrl+K anytime"
        )
        if self.list.count():
            self.list.setCurrentRow(0)

    def _current_command(self) -> Optional[Command]:
        item = self.list.currentItem()
        if item is None:
            return None
        title = item.data(Qt.UserRole)
        for c in self._results:
            if c.title == title:
                return c
        return None

    def _activate_selected(self) -> None:
        cmd = self._current_command()
        self.close()
        if cmd is None:
            return
        self.command_activated.emit(cmd.title)
        try:
            cmd.action()
        except Exception:
            # A failing command must never take the app down with it.
            import traceback
            try:
                from cellium.core.logger import dev_log
                dev_log(f"[command_palette] '{cmd.title}' failed:\n{traceback.format_exc()}")
            except Exception:
                pass

    # ── keys ─────────────────────────────────────────────────────────────
    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key_Escape,):
            self.close()
            return
        if key in (Qt.Key_Up, Qt.Key_Down):
            count = self.list.count()
            if count:
                cur = self.list.currentRow()
                step = -1 if key == Qt.Key_Up else 1
                self.list.setCurrentRow((cur + step) % count)
            return
        super().keyPressEvent(event)

    @staticmethod
    def install(parent: QWidget, registry: CommandRegistry,
                sequence: str = "Ctrl+K") -> "CommandPaletteDialog":
        """Create the dialog on ``parent`` and bind the shortcut to it."""
        dlg = CommandPaletteDialog(registry, parent)
        sc = QShortcut(QKeySequence(sequence), parent)
        sc.activated.connect(dlg.show_palette)
        dlg._shortcut = sc  # keep a reference alive  # noqa: SLF001
        return dlg
