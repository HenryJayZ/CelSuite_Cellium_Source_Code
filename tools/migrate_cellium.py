#!/usr/bin/env python3
"""Cellium source migrations - kept OUT of the regression suite.

The tester must never edit the application it is testing. Run this script after
pulling changes that need a source migration, then run tools/regression.py:

    python3 tools/migrate_cellium.py            # dry run: what is pending?
    python3 tools/migrate_cellium.py --apply    # write the migrations
    python3 tools/migrate_cellium.py --check    # CI: exit 1 if anything is pending

Every migration is idempotent: a second run reports "No pending migrations".
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def _discover_cellium_root() -> Path:
    candidates: list[Path] = []
    env_root = os.environ.get("CELSTUDIO_PROJECT_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser().resolve())

    for start in (Path.cwd(), Path(__file__).resolve().parent):
        candidates.append(start)
        candidates.extend(start.parents)

    home = Path.home()
    for pdir in (
        home / "Documents" / "Projects" / "Python",
        home / "Documents" / "Projects",
        home / "Projects",
    ):
        if pdir.is_dir():
            candidates.append(pdir)
            try:
                for child in sorted(pdir.iterdir()):
                    if child.is_dir() and not child.name.startswith("."):
                        candidates.append(child)
            except OSError:
                pass

    def _is_root(p: Path) -> bool:
        return (
            (p / "cellium" / "ui" / "main_window.py").is_file()
            and (p / "cellium" / "core" / "config.py").is_file()
            and (p / "cellium" / "ui" / "chat" / "bubble.py").is_file()
        )

    seen = set()
    for cand in candidates:
        try:
            real = cand.resolve()
        except OSError:
            continue
        if real in seen:
            continue
        seen.add(real)
        if _is_root(real):
            return real

    raise FileNotFoundError(
        "Could not locate the Cellium project directory!\n"
        "Set CELSTUDIO_PROJECT_ROOT=/path/to/Cellium and re-run."
    )

def _apply_pending_code_patches(root: Path, write: bool = True) -> list[str]:
    """Apply the CodeBlockCard ▶ Run GUI fix, .Inf button fix, and Wave 7 fixes idempotently."""
    def _commit(path: Path, text: str) -> None:
        """Write only in --apply mode; a dry run just reports what would change."""
        if write:
            path.write_text(text, encoding="utf-8")

    applied: list[str] = []

    # ── A. Fix CodeBlockCard ▶ Run GUI squash & .Inf button clipping in bubble.py ──
    bubble_path = root / "cellium" / "ui" / "chat" / "bubble.py"
    if bubble_path.is_file():
        b_src = bubble_path.read_text(encoding="utf-8")
        changed_b = False

        # 1. Scope CodeBlockCard border to QFrame#CodeBlockCard so child frames
        #    don't inherit rogue purple borders!
        old_cb_init = (
            '        self.setStyleSheet("""\n'
            '            QFrame {\n'
            '                background: rgba(12, 9, 22, 0.94);\n'
            '                border: 1.5px solid #9333EA;\n'
            '                border-radius: 10px;\n'
            '            }\n'
            '        """)'
        )
        new_cb_init = (
            '        self.setObjectName("CodeBlockCard")\n'
            '        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)\n'
            '        self.setStyleSheet("""\n'
            '            QFrame#CodeBlockCard {\n'
            '                background: rgba(12, 9, 22, 0.94);\n'
            '                border: 1.5px solid #9333EA;\n'
            '                border-radius: 10px;\n'
            '            }\n'
            '            QLabel { border: none; background: transparent; }\n'
            '        """)'
        )
        if 'self.setObjectName("CodeBlockCard")' not in b_src and old_cb_init in b_src:
            b_src = b_src.replace(old_cb_init, new_cb_init, 1)
            changed_b = True
            applied.append("bubble.py: scoped CodeBlockCard border to QFrame#CodeBlockCard")

        # Lock initial CodeBlockCard height in __init__ via _recalc_card_height()
        old_init_tail = (
            '        self.card_h = 34 + editor_h + 10\n'
            '        self._update_preview()'
        )
        new_init_tail = (
            '        self.card_h = 34 + editor_h + 10\n'
            '        self._recalc_card_height()\n'
            '        self._update_preview()'
        )
        if "self._recalc_card_height()\n        self._update_preview()" not in b_src and old_init_tail in b_src:
            b_src = b_src.replace(old_init_tail, new_init_tail, 1)
            changed_b = True

        # 2. Upgrade _toggle_shrink, _toggle_preview, and _run_code_block so
        #    CodeBlockCard recalculates its exact height (including console_frame!)
        #    and triggers a full parent bubble geometry reflow immediately!
        if "def _recalc_card_height(self):" not in b_src:
            old_run_target = "    def _toggle_shrink(self):"
            e_idx = b_src.find("class ThoughtAccordionCard(QFrame):")
            s_idx = b_src.find(old_run_target)
            if not (0 <= s_idx < e_idx):
                applied.append("SKIPPED bubble.py: _toggle_shrink/ThoughtAccordionCard anchors not found")
            if 0 <= s_idx < e_idx:
                replacement_methods = '''    def _recalc_card_height(self):
        """Calculate exact total height of header + editor/preview + resizer + console_frame."""
        hdr_h = 34
        if self.show_preview and hasattr(self, "preview"):
            body_h = self.preview.height()
        else:
            body_h = self.editor.height()
        resizer_h = self.resizer.height() if hasattr(self, "resizer") and not self.resizer.isHidden() else 10
        console_h = 0
        if hasattr(self, "console_frame") and self.console_frame is not None and not self.console_frame.isHidden():
            console_h = self.console_frame.height() + 8
        self.card_h = hdr_h + body_h + resizer_h + console_h + 4
        self.setFixedHeight(self.card_h)
        self.updateGeometry()
        p = self.parentWidget()
        while p is not None:
            if hasattr(p, "update_dynamic_width") and hasattr(p, "max_allowed_w"):
                try:
                    p.update_dynamic_width(p.max_allowed_w)
                except Exception:
                    pass
            if hasattr(p, "update_all_bubble_geometries"):
                try:
                    p.update_all_bubble_geometries()
                except Exception:
                    pass
                break
            p = p.parentWidget()

    def _toggle_shrink(self):
        self._is_shrunk = not self._is_shrunk
        if self._is_shrunk:
            self.editor.setFixedHeight(204)
            if hasattr(self, "btn_shrink"):
                self.btn_shrink.setText("↕ Expand")
        else:
            self.editor.setFixedHeight(self._full_h)
            if hasattr(self, "btn_shrink"):
                self.btn_shrink.setText("↕ 9 Lines")
        self._recalc_card_height()

    def _update_preview(self):
        if self.is_markdown and hasattr(self, "preview"):
            html_content = format_cel_markdown(self.code_text)
            styled_html = f"""
            <div style="font-family: 'Segoe UI', system-ui, sans-serif; line-height: 1.6;">
                {html_content}
            </div>
            """
            self.preview.setHtml(styled_html)

    def _toggle_preview(self):
        self.show_preview = not self.show_preview
        if self.show_preview:
            self.btn_toggle.setText("📝 Raw")
            self.stack.setCurrentIndex(1)
            self.preview.document().setTextWidth(max(240, self.width() - 20))
            preview_h = int(min(500, max(100, self.preview.document().size().height() + 20)))
            self.preview.setFixedHeight(preview_h)
        else:
            self.btn_toggle.setText("👁 Preview")
            self.stack.setCurrentIndex(0)
            lines = self.code_text.count("\\n") + 1
            editor_h = min(340, max(50, lines * 20 + 24))
            self.editor.setFixedHeight(editor_h)
        self._recalc_card_height()

    def sizeHint(self) -> QSize:
        return QSize(self.width() if self.width() > 0 else 420, getattr(self, "card_h", 120))

    def _copy_code(self):
        QApplication.clipboard().setText(self.code_text)
        self.btn_copy.setText("✓ Copied!")
        QTimer.singleShot(1800, self._reset_copy_button)

    def _reset_copy_button(self):
        self.btn_copy.setText("📋 Copy")

    def _close_console(self):
        if hasattr(self, "console_frame") and self.console_frame is not None:
            self.console_frame.setVisible(False)
            self._recalc_card_height()

    def _run_code_block(self):
        """Execute the code block in local environment and expand the card cleanly!"""
        if not hasattr(self, "console_frame") or self.console_frame is None:
            self.console_frame = QFrame(self)
            self.console_frame.setObjectName("CodeConsoleFrame")
            self.console_frame.setStyleSheet("""
                QFrame#CodeConsoleFrame {
                    background: rgba(6, 4, 14, 0.92);
                    border-top: 1.5px solid #9333EA;
                    border-bottom-left-radius: 9px;
                    border-bottom-right-radius: 9px;
                    margin: 0px;
                }
            """)
            cf_layout = QVBoxLayout(self.console_frame)
            cf_layout.setContentsMargins(10, 6, 10, 8)
            cf_layout.setSpacing(4)

            c_hdr = QHBoxLayout()
            c_hdr.setContentsMargins(0, 0, 0, 0)
            c_lbl = QLabel("<b>💻 Terminal Output</b>")
            c_lbl.setStyleSheet("color: #38BDF8; font-size: 11px; border: none; background: transparent;")
            c_hdr.addWidget(c_lbl)
            c_hdr.addStretch()

            self.btn_copy_out = QPushButton("📋 Copy Output")
            self.btn_copy_out.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_copy_out.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,0.10); color: #E2E8F0; border-radius: 4px; "
                "padding: 2px 8px; font-size: 10px; font-weight: bold; border: none; } "
                "QPushButton:hover { background: #9333EA; color: #FFFFFF; }"
            )
            self.btn_copy_out.clicked.connect(
                lambda: (QApplication.clipboard().setText(self.console_out.toPlainText()), self.btn_copy_out.setText("✓ Copied!"))
            )
            c_hdr.addWidget(self.btn_copy_out)

            btn_close_con = QPushButton("✕")
            btn_close_con.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_close_con.setFixedSize(20, 20)
            btn_close_con.setToolTip("Hide terminal output")
            btn_close_con.setStyleSheet(
                "QPushButton { background: transparent; color: #94A3B8; border: none; font-size: 11px; font-weight: bold; } "
                "QPushButton:hover { color: #F87171; }"
            )
            btn_close_con.clicked.connect(self._close_console)
            c_hdr.addWidget(btn_close_con)
            cf_layout.addLayout(c_hdr)

            self.console_out = QTextEdit(self.console_frame)
            self.console_out.setReadOnly(True)
            self.console_out.setFont(QFont("Consolas", 9))
            self.console_out.setStyleSheet(
                "QTextEdit { background: rgba(0, 0, 0, 0.45); color: #4ADE80; "
                "border: 1px solid rgba(147, 51, 234, 0.28); border-radius: 6px; padding: 6px; }"
            )
            self.console_out.setFixedHeight(68)
            cf_layout.addWidget(self.console_out)
            self.layout().addWidget(self.console_frame)

        self.console_out.setPlainText("⏳ Executing script in local environment...")
        self.console_out.setFixedHeight(58)
        self.console_frame.setFixedHeight(32 + 58 + 14)
        self.console_frame.setVisible(True)
        self.console_frame.show()
        self.btn_run.setEnabled(False)
        self.btn_run.setText("⏳ Running...")
        self._recalc_card_height()

        class ExecWorker(QThread):
            output_ready = Signal(str, int)
            def __init__(self, code, lang):
                super().__init__()
                self.code = code
                self.lang = lang
            def run(self):
                try:
                    if self.lang in ("python", "py"):
                        py_bin = resolve_python_executable() if "resolve_python_executable" in globals() else sys.executable
                        cmd = [py_bin, "-c", self.code]
                    else:
                        cmd = ["bash", "-c", self.code]
                    res = subprocess.run(cmd, shell=False, capture_output=True, text=True, timeout=30, cwd=os.getcwd())
                    out = res.stdout
                    if res.stderr:
                        out += f"\\nSTDERR:\\n{res.stderr}"
                    self.output_ready.emit(out.strip() or "(no output)", res.returncode)
                except subprocess.TimeoutExpired:
                    self.output_ready.emit("Error: Execution timed out after 30s", 1)
                except Exception as e:
                    self.output_ready.emit(f"Error: {e}", 1)

        def _on_done(output, code):
            self.btn_run.setEnabled(True)
            self.btn_run.setText("▶ Run")
            if code == 0:
                full_out = f"{output}\\n\\n✓ Exit code: 0"
                self.console_out.setStyleSheet(
                    "QTextEdit { background: rgba(0, 0, 0, 0.45); color: #4ADE80; "
                    "border: 1px solid rgba(74, 222, 128, 0.35); border-radius: 6px; padding: 6px; }"
                )
            else:
                full_out = f"{output}\\n\\n⚠️ Exit code: {code}"
                self.console_out.setStyleSheet(
                    "QTextEdit { background: rgba(0, 0, 0, 0.45); color: #F87171; "
                    "border: 1px solid rgba(248, 113, 113, 0.45); border-radius: 6px; padding: 6px; }"
                )
            self.console_out.setPlainText(full_out)
            out_lines = max(2, full_out.count("\\n") + 1)
            out_h = min(220, max(62, out_lines * 18 + 18))
            self.console_out.setFixedHeight(out_h)
            self.console_frame.setFixedHeight(32 + out_h + 14)
            self._recalc_card_height()

            top_win = self.window()
            if top_win is not None:
                if hasattr(top_win, "record_code_run_output"):
                    try:
                        top_win.record_code_run_output(self.lang, self.code_text, output, code)
                    except Exception:
                        pass
                if hasattr(top_win, "update_all_bubble_geometries"):
                    top_win.update_all_bubble_geometries()

        self._exec_thread = ExecWorker(self.code_text, self.lang)
        self._exec_thread.output_ready.connect(_on_done)
        self._exec_thread.finished.connect(self._exec_thread.deleteLater)
        self._exec_thread.start()

'''
                region = b_src[s_idx:e_idx]
                extra = sorted(
                    set(re.findall(r"^    def (\w+)\(", region, re.M))
                    - set(re.findall(r"^    def (\w+)\(", replacement_methods, re.M))
                )
                if extra:
                    applied.append(f"SKIPPED bubble.py: patch region has unexpected methods {extra}")
                else:
                    b_src = b_src[:s_idx] + replacement_methods + b_src[e_idx:]
                    changed_b = True
                    applied.append("bubble.py: fixed CodeBlockCard ▶ Run GUI squash & dynamic console height")

        # 3. Update CodeBlockResizer.mouseMoveEvent to call _recalc_card_height()
        old_resizer_move = (
            '            if hasattr(self.parent(), "card_h"):\n'
            '                self.parent().card_h = new_h + 34 + 10\n'
            '            self.parent().updateGeometry()'
        )
        new_resizer_move = (
            '            if hasattr(self.parent(), "_recalc_card_height"):\n'
            '                self.parent()._recalc_card_height()\n'
            '            elif hasattr(self.parent(), "card_h"):\n'
            '                self.parent().card_h = new_h + 34 + 10\n'
            '                self.parent().updateGeometry()'
        )
        if old_resizer_move in b_src:
            b_src = b_src.replace(old_resizer_move, new_resizer_move, 1)
            changed_b = True

        # 4. Prevent `✨ Info` button from clipping to `. Inf` (from screenshot!)
        old_btn_info = (
            '            self.btn_info = QPushButton("✨ Info")\n'
            '            self.btn_info.setToolTip("✨ View token statistics, generation speed & model capabilities")'
        )
        new_btn_info = (
            '            self.btn_info = QPushButton("✨ Info")\n'
            '            self.btn_info.setMinimumWidth(62)\n'
            '            self.btn_info.setFixedHeight(22)\n'
            '            self.btn_info.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)\n'
            '            self.btn_info.setToolTip("✨ View token statistics, generation speed & model capabilities")'
        )
        if "self.btn_info.setMinimumWidth(62)" not in b_src and old_btn_info in b_src:
            b_src = b_src.replace(old_btn_info, new_btn_info, 1)
            changed_b = True
            applied.append("bubble.py: fixed ✨ Info button clipping (. Inf) with minimumWidth(62)")

        if 'hdr_min = int((262 if self.role == "user" else 292)' in b_src:
            b_src = b_src.replace(
                'hdr_min = int((262 if self.role == "user" else 292)',
                'hdr_min = int((262 if self.role == "user" else 332)',
                1,
            )
            changed_b = True

        if changed_b:
            _commit(bubble_path, b_src)

    # ── B. Ensure Wave 7 (#4 zoom-back-to-1.0 & Nuitka portability) is applied ──
    mw_path = root / "cellium" / "ui" / "main_window.py"
    if mw_path.is_file():
        src = mw_path.read_text(encoding="utf-8")
        old_zoom_block = (
            '        need_zoom = abs(z - 1.0) > 1e-6 or body_px != self.BUBBLE_BASE_FONT_PX\n'
            '        if need_zoom:\n'
            '            app_font = self.font()\n'
            '            for i in range(self.chat_layout.count()):\n'
            '                item = self.chat_layout.itemAt(i)\n'
            '                w = item.widget() if item else None\n'
            '                if w is None:\n'
            '                    continue\n'
            '                try:\n'
            '                    self._apply_stylesheet_zoom(w)\n'
            '                    for target in [w] + w.findChildren(QWidget):\n'
            '                        if hasattr(target, "set_font_scale") and getattr(target, "font_size", None) != body_px:\n'
            '                            target.set_font_scale(body_px)\n'
            '                        elif target.font().pointSizeF() != app_font.pointSizeF():\n'
            '                            target.setFont(app_font)\n'
            '                except RuntimeError:\n'
            '                    pass'
        )
        new_zoom_block = (
            '        app_font = self.font()\n'
            '        is_zoomed = abs(z - 1.0) > 1e-6\n'
            '        for i in range(self.chat_layout.count()):\n'
            '            item = self.chat_layout.itemAt(i)\n'
            '            w = item.widget() if item else None\n'
            '            if w is None:\n'
            '                continue\n'
            '            try:\n'
            '                if is_zoomed or getattr(w, "_was_ss_zoomed", False):\n'
            '                    self._apply_stylesheet_zoom(w)\n'
            '                    w._was_ss_zoomed = is_zoomed\n'
            '                for target in [w] + w.findChildren(QWidget):\n'
            '                    if hasattr(target, "set_font_scale"):\n'
            '                        if getattr(target, "font_size", None) != body_px:\n'
            '                            target.set_font_scale(body_px)\n'
            '                    elif target.font().pointSizeF() != app_font.pointSizeF():\n'
            '                        target.setFont(app_font)\n'
            '            except RuntimeError:\n'
            '                pass'
        )
        if old_zoom_block in src:
            src = src.replace(old_zoom_block, new_zoom_block, 1)
            _commit(mw_path, src)
            applied.append("main_window.py: fixed #4 zoom-back-to-1.0 restoration")

    cfg_path = root / "cellium" / "core" / "config.py"
    if cfg_path.is_file():
        c_src = cfg_path.read_text(encoding="utf-8")
        if "def resolve_python_executable() -> str:" not in c_src:
            old_kokoro = (
                'KOKORO_DIR = (Path(_ENV_KOKORO) if _ENV_KOKORO else _first_existing(\n'
                '    (PROJECTS_DIR / "Kokoro",\n'
                '     Path.home() / "Documents" / "Projects" / "Kokoro"),\n'
                '    "kokoro-v1.0.fp16.onnx"))'
            )
            new_kokoro = (
                'IS_FROZEN = bool(\n'
                '    "__compiled__" in globals()\n'
                '    or getattr(sys, "frozen", False)\n'
                '    or hasattr(sys, "_MEIPASS")\n'
                ')\n'
                'APP_EXEC_DIR = Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else BASE_DIR\n'
                '\n'
                'def _resolve_user_data_dir() -> Path:\n'
                '    if not IS_FROZEN:\n'
                '        return BASE_DIR\n'
                '    cfg_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))\n'
                '    d = cfg_root / "Cellium"\n'
                '    d.mkdir(parents=True, exist_ok=True)\n'
                '    return d\n'
                '\n'
                'USER_DATA_DIR = _resolve_user_data_dir()\n'
                '\n'
                'def resolve_python_executable() -> str:\n'
                '    if not IS_FROZEN:\n'
                '        return sys.executable\n'
                '    for cand in (VENV_DIR / "bin" / "python", shutil.which("python3"), shutil.which("python")):\n'
                '        if cand and Path(cand).is_file():\n'
                '            return str(cand)\n'
                '    return "python3"\n'
                '\n'
                'KOKORO_DIR = (Path(_ENV_KOKORO) if _ENV_KOKORO else _first_existing(\n'
                '    (APP_EXEC_DIR / "Kokoro",\n'
                '     APP_EXEC_DIR / "models",\n'
                '     BASE_DIR.parent / "models",\n'
                '     Path.home() / ".local" / "share" / "cellium" / "Kokoro",\n'
                '     PROJECTS_DIR / "Kokoro",\n'
                '     Path.home() / "Documents" / "Projects" / "Kokoro"),\n'
                '    "kokoro-v1.0.fp16.onnx"))'
            )
            if old_kokoro in c_src:
                _commit(cfg_path, c_src.replace(old_kokoro, new_kokoro, 1))
                applied.append("config.py: added Nuitka IS_FROZEN, USER_DATA_DIR & resolve_python_executable")

    workers_p = root / "cellium" / "services" / "ai_workers.py"
    if workers_p.is_file():
        w_src = workers_p.read_text(encoding="utf-8")
        old_td = (
            '                # Attach thinking directive to latest user turn so local GGUF models follow it\n'
            '                if think_directive and safe_chat_messages and safe_chat_messages[-1]["role"] == "user":\n'
            '                    safe_chat_messages[-1]["content"] += think_directive'
        )
        new_td = (
            '                # NOTE (#26): think_directive is already merged into safe_chat_messages[0] via\n'
            '                # system_text above so earlier turns keep a 100% stable KV prefix!'
        )
        if old_td in w_src:
            _commit(workers_p, w_src.replace(old_td, new_td, 1))
            applied.append("ai_workers.py: stabilized multi-turn GGUF KV prefix cache (#26)")

    return applied

def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if any(a in ("-h", "--help") for a in args):
        print(__doc__.strip())
        return 0
    known = {"--apply", "--check"}
    unknown = [a for a in args if a not in known]
    if unknown:
        print(f"Unknown option(s): {' '.join(unknown)}")
        print("Usage: migrate_cellium.py [--apply] [--check]")
        return 2

    root = _discover_cellium_root()
    applying = "--apply" in args
    results = _apply_pending_code_patches(root, write=applying)

    if not results:
        print("No pending migrations - source is up to date.")
        return 0

    changed = 0
    skipped = 0
    for item in results:
        if item.startswith("SKIPPED "):
            skipped += 1
            print(f"  SKIPPED : {item.removeprefix('SKIPPED ')}")
        else:
            changed += 1
            label = "APPLIED" if applying else "PENDING"
            print(f"  {label} : {item}")

    if "--check" in args:
        return 1 if (changed or skipped) else 0
    if not applying:
        print(f"\nDry run only - re-run with --apply to write {changed} migration(s).")
    return 0 if not skipped else 1


if __name__ == "__main__":
    sys.exit(main())
