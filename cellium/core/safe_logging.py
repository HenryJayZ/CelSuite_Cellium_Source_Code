"""Secret redaction for logs and diagnostics.

Qt-free (AGENTS.md invariant 2). The Qt-side read-only viewer that consumes this
lives in `cellium/ui/widgets/safe_logview.py`.

Cellium talks to eleven providers (see `PROVIDER_DEFS` in `core/utils.py`), any of
which may be present in a traceback, an HTTP debug dump, or a settings snapshot.
This module masks credential-shaped substrings before they ever reach a log file
or the screen.

Covered, in priority order:

1. Provider-prefixed keys for every provider Cellium supports.
2. Common third-party key shapes (GitHub, OpenAI, Anthropic, AWS, Slack, Stripe,
   HuggingFace, Google OAuth, JWTs).
3. Key/value assignments such as ``api_key="..."`` or ``Authorization: Bearer ...``.
4. Long base64 literals -- the shape used to hide a token by splitting it across
   string fragments, which was found in this codebase.

`redact()` is idempotent: redacting already-redacted text changes nothing.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Pattern, Tuple

__all__ = [
    "REDACTION_PATTERNS",
    "REDACTED",
    "redact",
    "redact_text",
    "redact_mapping",
    "RedactingFormatter",
    "install_redacting_handler",
    "scrub_exception",
]

REDACTED = "***REDACTED***"

# (compiled pattern, replacement template, description)
# Replacement uses \1-style groups only where a non-secret prefix is worth
# keeping, e.g. ``ghp_`` so the reader can still tell *which* key leaked.
REDACTION_PATTERNS: List[Tuple[Pattern[str], str, str]] = [
    # ── Cellium's own providers ──────────────────────────────────────────
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "AIza***REDACTED***", "Google API key"),
    (re.compile(r"\bcsk-[0-9A-Za-z]{16,}\b"), "csk-***REDACTED***", "Cerebras key"),
    (re.compile(r"\bgsk_[0-9A-Za-z]{32,}\b"), "gsk_***REDACTED***", "Groq key"),
    (re.compile(r"\bsk-or-v1-[0-9A-Za-z]{32,}\b"), "sk-or-v1-***REDACTED***", "OpenRouter key"),
    (re.compile(r"\bsf-[0-9A-Za-z]{32,}\b"), "sf-***REDACTED***", "SiliconFlow key"),

    # ── Widely used third-party shapes ───────────────────────────────────
    (re.compile(r"\bgithub_pat_[0-9A-Za-z_]{20,}"), "github_pat_***REDACTED***", "GitHub fine-grained PAT"),
    (re.compile(r"\bgh[pousr]_[0-9A-Za-z]{30,}"), "gh*_***REDACTED***", "GitHub token"),
    (re.compile(r"\bsk-ant-[0-9A-Za-z\-_]{20,}\b"), "sk-ant-***REDACTED***", "Anthropic key"),
    (re.compile(r"\bsk-proj-[0-9A-Za-z\-_]{20,}\b"), "sk-proj-***REDACTED***", "OpenAI project key"),
    (re.compile(r"\bsk-[0-9A-Za-z]{20,}\b"), "sk-***REDACTED***", "OpenAI-style key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA***REDACTED***", "AWS access key id"),
    (re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}"), "xox*-***REDACTED***", "Slack token"),
    (re.compile(r"\bsk_live_[0-9A-Za-z]{16,}\b"), "sk_live_***REDACTED***", "Stripe live key"),
    (re.compile(r"\bhf_[0-9A-Za-z]{30,}\b"), "hf_***REDACTED***", "HuggingFace token"),
    (re.compile(r"\bya29\.[0-9A-Za-z\-_]{20,}"), "ya29.***REDACTED***", "Google OAuth token"),

    # ── Structured values ────────────────────────────────────────────────
    (re.compile(r"(?i)\b(authorization\s*[:=]\s*)(bearer\s+)?[^\s\"',}]+"),
     r"\1\2" + REDACTED, "Authorization header"),
    (re.compile(r"(?i)\b(api[_-]?key|apikey|access[_-]?token|secret[_-]?key|"
                r"client[_-]?secret|refresh[_-]?token|private[_-]?token|"
                r"password|passwd)\b(\s*[:=]\s*)[\"']?([^\s\"',}]{6,})"),
     r"\1\2" + REDACTED, "key=value assignment"),
    (re.compile(r"(?i)(\"user_custom_keys\"\s*:\s*\{)([^\}]*)"),
     r"\1" + REDACTED + r"}", "user_custom_keys block"),

    # ── Structural ───────────────────────────────────────────────────────
    (re.compile(r"\beyJ[0-9A-Za-z_\-]{8,}\.eyJ[0-9A-Za-z_\-]{8,}\.[0-9A-Za-z_\-]{8,}"),
     REDACTED, "JWT"),
    (re.compile(r"\b[0-9a-fA-F]{40,}\b"), REDACTED, "long hex (hash/token)"),
]

# Long base64 literals are matched separately: they are only interesting when
# they are long enough to be a credential and not a font, an image chunk, or a
# numpy blob. 48 chars is ~36 random bytes, well past ordinary base64 in logs.
_B64_SECRET = re.compile(r"\b[A-Za-z0-9+/]{48,}={0,2}\b")


def redact_text(text: str, extra_patterns: Iterable[Tuple[Pattern[str], str, str]] = ()) -> str:
    """Mask every credential-shaped substring in ``text``.

    ``extra_patterns`` lets a caller add project-specific shapes without editing
    this module.
    """
    if not text:
        return text
    out = text
    for pattern, repl, _desc in list(REDACTION_PATTERNS) + list(extra_patterns):
        out = pattern.sub(repl, out)

    def _mask_b64(m: "re.Match[str]") -> str:
        raw = m.group(0)
        try:
            import base64
            decoded = base64.b64decode(raw + "=" * (-len(raw) % 4), validate=False)
        except Exception:
            return raw
        try:
            text_dec = decoded.decode("utf-8")
        except Exception:
            return raw
        if any(tok in text_dec for tok in ("ghp_", "gho_", "ghs_", "ghu_", "github_pat_",
                                          "sk-", "AIza", "AKIA", "csk-", "xox")):
            return REDACTED
        return raw

    out = _B64_SECRET.sub(_mask_b64, out)
    return out


# Back-compat alias; the archive called the class-level helper ``redact``.
def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, (list, tuple)):
        redacted = [redact(v) for v in value]
        return type(value)(redacted) if isinstance(value, tuple) else redacted
    return value


_SENSITIVE_KEY = re.compile(
    r"(?i)(key|token|secret|password|passwd|credential|auth|signature|session)")


def redact_mapping(data: Dict[str, Any], _depth: int = 0) -> Dict[str, Any]:
    """Recursively redact a settings-shaped dict.

    Keys whose *name* looks sensitive are replaced wholesale; other values are
    still passed through :func:`redact_text` so a stray token in a harmless
    field is caught too.
    """
    if _depth > 12 or not isinstance(data, dict):
        return data
    out: Dict[str, Any] = {}
    for k, v in data.items():
        if _SENSITIVE_KEY.search(str(k)) and not isinstance(v, (dict, list, tuple)):
            out[k] = REDACTED
        elif isinstance(v, dict):
            out[k] = redact_mapping(v, _depth + 1)
        elif isinstance(v, (list, tuple)):
            out[k] = [redact(item) for item in v]
        elif isinstance(v, str):
            out[k] = redact_text(v)
        else:
            out[k] = v
    return out


def scrub_exception(exc: BaseException) -> str:
    """Render an exception with its payload redacted."""
    try:
        return redact_text(f"{type(exc).__name__}: {exc}")
    except Exception:
        return f"{type(exc).__name__}: <unrenderable>"


class RedactingFormatter(logging.Formatter):
    """Drop-in ``logging.Formatter`` that masks secrets in the final message.

    Args are also masked, because secrets frequently arrive as a stray
    ``%s`` interpolation argument rather than in the format string.
    """

    def __init__(self, fmt: str | None = None, datefmt: str | None = None,
                 extra_patterns: Iterable[Tuple[Pattern[str], str, str]] = ()):
        super().__init__(fmt, datefmt)
        self._extra = list(extra_patterns)

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        return redact_text(rendered, self._extra)

    def formatException(self, ei) -> str:  # noqa: N802 - stdlib signature
        return redact_text(super().formatException(ei))


def install_redacting_handler(
    logger: logging.Logger | None = None,
    level: int = logging.INFO,
    fmt: str = "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
) -> logging.Handler:
    """Attach a redacting stream handler. Safe to call more than once."""
    target = logger or logging.getLogger()
    for h in target.handlers:
        if isinstance(h.formatter, RedactingFormatter):
            return h
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter(fmt))
    handler.setLevel(level)
    target.addHandler(handler)
    return handler
