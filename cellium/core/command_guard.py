"""Dangerous-command auditing for the agent's shell_exec tool.

Design intent (agreed with user): this module NEVER hard-blocks a command.
It surfaces a warning, asks the user for confirmation, and executes only once
the user has explicitly said yes. Trust the agent, but make the user the final
authority on anything irreversible.

The agent receives a confirmation request as its tool result and is instructed
to re-issue the identical call with ``confirmed=True`` only after the user has
approved out of band.

Nothing here executes anything -- it is pure string analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

__all__ = [
    "CommandFinding",
    "DANGEROUS_PATTERNS",
    "audit_command",
    "format_confirmation_request",
    "pending_approvals",
    "clear_pending",
]


@dataclass(frozen=True)
class CommandFinding:
    pattern_id: str
    severity: str      # "high" | "medium"
    reason: str
    matched: str = ""

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"[{self.severity.upper()}] {self.reason} (matched: {self.matched!r})"


# Ordered most-severe first. Patterns are deliberately conservative: a noisy
# denylist trains the user to click "yes" without reading, which is worse than
# having no guard at all.
DANGEROUS_PATTERNS: List[tuple] = [
    ("wipe_root",    "high",
     "Recursive delete aimed at the filesystem root or your home directory",
     re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*-{1,2}[a-zA-Z]*[rR][a-zA-Z]*f?[a-zA-Z]*\s+(/|~|\$HOME|/\*|~/\*|\*)\s*$")),

    ("wipe_root_anywhere", "high",
     "Recursive force-delete of a broad path",
     re.compile(r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*f?[a-zA-Z]*\s+(/|~|/\*|~/\*|\$HOME)\b")),

    ("sudo",         "medium",
     "Privilege escalation with sudo",
     re.compile(r"(^|[;&|]\s*|\s)sudo\s")),

    ("pipe_to_shell", "high",
     "Downloading and immediately executing a remote script",
     re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|k|da|)sh\b")),

    ("fork_bomb",    "high",
     "Fork bomb - will hang or crash the machine",
     re.compile(r":\(\)\s*\{.*\|.*&.*\}\s*;?\s*:"),),

    ("raw_disk_write", "high",
     "Writing directly to a block device",
     re.compile(r"\bdd\b[^|;]*\bof=/dev/")),

    ("filesystem_format", "high",
     "Formatting a filesystem",
     re.compile(r"\bmkfs(\.\w+)?\b")),

    ("chmod_777",    "medium",
     "World-writable permissions, recursively",
     re.compile(r"\bchmod\s+(-R\s+)?0?777\b")),

    ("shutdown",     "high",
     "Powering the machine off or restarting it",
     re.compile(r"\b(shutdown|reboot|poweroff|halt|init\s+0)\b")),

    ("kill_init",    "high",
     "Killing PID 1 or all processes",
     re.compile(r"\b(kill\s+-9\s+1\b|killall\s+-9\b|pkill\s+-9\s+-u)")),

    ("device_zero",  "high",
     "Redirecting output to a block device",
     re.compile(r">\s*/dev/(sd|nvme|hd|disk)")),

    ("history_wipe", "medium",
     "Clearing shell history",
     re.compile(r"\bhistory\s+-c\b")),

    ("disable_firewall", "medium",
     "Disabling the firewall",
     re.compile(r"\bufw\s+(disable|allow)\b|\biptables\s+-F\b")),

    ("git_force_push", "medium",
     "Force-pushing, which can destroy remote history",
     re.compile(r"\bgit\s+push\b[^|;]*(--force(?!-with-lease)|(^|\s)-f(\s|$))")),

    ("package_purge", "medium",
     "Purging system packages",
     re.compile(r"\b(apt|apt-get|yum|dnf|pacman)\s+(purge|remove|autoremove)\b")),

    ("crontab_wipe", "medium",
     "Clearing the crontab",
     re.compile(r"\bcrontab\s+-r\b")),
]


def audit_command(command: str) -> List[CommandFinding]:
    """Return every finding for ``command``. Empty list means nothing flagged."""
    if not command or not isinstance(command, str):
        return []
    text = command.replace("\\\n", " ")
    findings: List[CommandFinding] = []
    for pid, severity, reason, pattern in DANGEROUS_PATTERNS:
        m = pattern.search(text)
        if m:
            findings.append(CommandFinding(pid, severity, reason, m.group(0).strip()))
    # De-duplicate by pattern id, keeping the highest severity encountered.
    seen = {}
    for f in findings:
        prev = seen.get(f.pattern_id)
        if prev is None or (prev.severity == "medium" and f.severity == "high"):
            seen[f.pattern_id] = f
    order = {"high": 0, "medium": 1}
    return sorted(seen.values(), key=lambda f: (order.get(f.severity, 2), f.pattern_id))


# ─── Pending-approval registry ────────────────────────────────────────────────
# The UI can inspect this to show a confirmation prompt. Kept deliberately tiny
# and in-memory; nothing is persisted and nothing is cached across restarts.
pending_approvals: dict = {}


def _approval_key(command: str, timeout: int) -> str:
    import hashlib
    return hashlib.sha256(f"{command}\x00{timeout}".encode("utf-8")).hexdigest()[:16]


def format_confirmation_request(command: str, findings: List[CommandFinding],
                                timeout: int = 30) -> str:
    """The exact text handed back to the model as the tool result."""
    lines = [
        "CONFIRMATION REQUIRED - this shell command was not executed.",
        "",
        f"Command: {command}",
        "",
        "The following risks were detected:",
    ]
    for f in findings:
        lines.append(f"  • [{f.severity.upper()}] {f.reason}  (matched {f.matched!r})")
    lines += [
        "",
        "Do NOT retry on your own initiative. Ask the user to approve this exact",
        "command first. Only if the user explicitly agrees, call shell_exec again",
        "with the identical arguments plus confirmed=true.",
    ]
    key = _approval_key(command, timeout)
    pending_approvals[key] = {
        "command": command,
        "timeout": timeout,
        "findings": [f.pattern_id for f in findings],
    }
    lines.append(f"(pending-approval id: {key})")
    return "\n".join(lines)


def clear_pending(key: str) -> None:
    pending_approvals.pop(key, None)


def clear_all_pending() -> None:
    pending_approvals.clear()
