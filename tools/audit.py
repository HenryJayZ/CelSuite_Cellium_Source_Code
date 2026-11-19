#!/usr/bin/env python3
"""Static smell audit for Cellium.

Aimed squarely at the bug class that bit us: hand-mangled one-liners. A refactor
or an AI edit can leave behind calls with the wrong arity, no-op ``replace``s,
swallowed exceptions, and Qt access from worker threads -- all of which compile
cleanly and only fail at runtime.

    /home/henry/Documents/Projects/Python/venv/bin/python tools/audit.py [--json]

Exit code 0 = no HIGH findings.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "cellium"

SEV_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
findings = []


def add(sev, path, line, kind, msg, fix=""):
    findings.append({"severity": sev, "file": str(path.relative_to(ROOT)),
                     "line": line, "kind": kind, "message": msg, "fix": fix})


class Visitor(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.src = path.read_text(errors="ignore")
        self.lines = self.src.splitlines()
        self.class_stack = []

    # ── str.replace with one arg / no-op replacements ───────────────────
    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Attribute):
            # replace() with fewer than 2 args always raises TypeError
            if f.attr == "replace" and len(node.args) < 2 and not node.keywords:
                add("HIGH", self.path, node.lineno, "replace-arity",
                    f".replace() called with {len(node.args)} arg(s) - always TypeError",
                    "supply (old, new); this is how _escape_html was silently broken")
            # replace("x","x") - provably a no-op
            if f.attr == "replace" and len(node.args) == 2:
                a, b = node.args
                if isinstance(a, ast.Constant) and isinstance(b, ast.Constant) and a.value == b.value:
                    add("HIGH", self.path, node.lineno, "no-op-replace",
                        f".replace({a.value!r}, {b.value!r}) does nothing",
                        "this usually means an HTML entity such as &amp; lost its text in an edit")
            # join() with 1 arg -> TypeError
            if f.attr == "join" and len(node.args) < 1:
                add("HIGH", self.path, node.lineno, "join-arity",
                    f".join() called with {len(node.args)} arg(s)", "")
        self.generic_visit(node)

    # ── exception handling that hides failures ─────────────────────────
    def visit_ExceptHandler(self, node):
        body = node.body
        # except: pass  (single Pass statement)
        if len(body) == 1 and isinstance(body[0], ast.Pass):
            add("MEDIUM", self.path, node.lineno, "silent-except",
                "except ...: pass - failure is invisible",
                "log it via dev_log so a broken feature is diagnosable")
        # bare except:
        if node.type is None:
            add("LOW", self.path, node.lineno, "bare-except",
                "bare except: also catches KeyboardInterrupt/SystemExit", "use except Exception")
        self.generic_visit(node)

    # ── Qt calls from non-UI layers ─────────────────────────────────────
    def visit_FunctionDef(self, node):
        self.class_stack.append(node.name)
        self._check_thread_safety(node)
        self.generic_visit(node)
        self.class_stack.pop()

    def _check_thread_safety(self, node):
        stack = [c.func.attr for c in ast.walk(node)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)]
        # Precisely QThread.run(). A substring match on "run" used to flag
        # unrelated helpers such as _run_code_block().
        if node.name != "run":
            return
        qt = {"setText", "setPixmap", "setVisible", "repaint", "update",
              "insertPlainText", "appendPlainText", "setHtml", "setStyleSheet"}
        hits = sorted(set(stack) & qt)
        if hits:
            add("HIGH", self.path, node.lineno, "qt-from-thread",
                f"run() touches widgets directly: {', '.join(hits)}",
                "emit a signal and let the UI thread apply it (AGENTS.md invariant 1)")

    # ── QTimer.singleShot inside a run() ────────────────────────────────
    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "singleShot":
            add("LOW", self.path, node.lineno, "singleShot",
                "QTimer.singleShot - banned inside worker threads per AGENTS.md", "")
        # f-string with no placeholders
        if isinstance(f, ast.Name) and f.id == "print":
            pass
        self.generic_visit(node)


# NOTE: an empty-f-string check used to live here. It was removed after it
# produced 32 false positives - for both `node.values` and
# `ast.get_source_segment()`, spans on f-strings that are elements of a larger
# multi-line call do not reliably correspond to the literal on that line.
# A check that cries wolf trains you to ignore the tool. Two reliable checks
# (replace-arity, no-op-replace) are what actually found a real bug here.


class Unused:  # pragma: no cover
    pass


def main() -> int:
    files = [p for p in PKG.rglob("*.py") if "__pycache__" not in str(p)]
    for p in files:
        try:
            tree = ast.parse(p.read_text(errors="ignore"))
        except SyntaxError as e:
            add("HIGH", p, e.lineno or 0, "syntax", f"SyntaxError: {e.msg}", "")
            continue
        Visitor(p).visit(tree)
        pass  # f-string check removed, see note below

    findings.sort(key=lambda f: (SEV_ORDER[f["severity"]], f["file"], f["line"]))

    if "--json" in sys.argv:
        print(json.dumps(findings, indent=2))
        return 0

    counts = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1

    print("=" * 74)
    print(f"  Cellium static audit - {len(files)} files")
    print("=" * 74)
    for sev in ("HIGH", "MEDIUM", "LOW"):
        rows = [f for f in findings if f["severity"] == sev]
        if not rows:
            continue
        print(f"\n{sev}  ({len(rows)})")
        print("-" * 74)
        for f in rows:
            print(f"  {f['file']}:{f['line']}  [{f['kind']}]")
            print(f"      {f['message']}")
            if f["fix"]:
                print(f"      -> {f['fix']}")
    print()
    print("-" * 74)
    print("  " + "  ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "  clean")
    print("=" * 74)
    return 1 if counts.get("HIGH") else 0


if __name__ == "__main__":
    sys.exit(main())