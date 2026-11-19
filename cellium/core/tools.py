#!/usr/bin/env python3
"""
CelStudio Cerebrium - Native PySide6 Desktop Application
Liquid Glass UI, Neon Glow Saturation & Dynamic Color-Shifting Wallpaper Engine
100% LGPL PySide6 Standard | Central Venv | Strict Signals
Telegram-Style Glass Input | Inbuilt Emoji Picker | Multi-Engine STT | 100% Inbuilt Views
Animal Crossing / Scratchin Melodi Musical Cel Voice | Cozy Sound System | Zero Popups
"""

import sys
import os
import io
import json
import time
import tempfile
import uuid
import base64
import hashlib
import threading
import requests
import urllib.request
import urllib.error
import subprocess
import math
import gc
import wave
import struct
import ctypes
import re
import shutil
import html
import queue
import difflib
from pathlib import Path
from datetime import datetime
import numpy as np

# ── Tool classification for Claude Code-style UI display ─────────
EDIT_TOOLS = {"replace_file_content", "file_write", "write_file"}
ACTIVITY_TOOLS = {"file_read", "file_list", "grep_search", "web_search"}

_ACTIVE_SUBPROCESSES = set()
_SUBPROC_LOCK = threading.Lock()


def register_active_subprocess(proc):
    with _SUBPROC_LOCK:
        _ACTIVE_SUBPROCESSES.add(proc)


def unregister_active_subprocess(proc):
    with _SUBPROC_LOCK:
        _ACTIVE_SUBPROCESSES.discard(proc)


def kill_active_subprocesses():
    """Force-terminate any running tool subprocesses immediately when Stop is clicked."""
    import signal
    with _SUBPROC_LOCK:
        procs = list(_ACTIVE_SUBPROCESSES)
        _ACTIVE_SUBPROCESSES.clear()
    for p in procs:
        try:
            if p.poll() is None:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                except Exception:
                    p.terminate()
                try:
                    p.kill()
                except Exception:
                    pass
        except Exception:
            pass


def build_unified_diff(old_text: str, new_text: str, path: str = "file", context: int = 3) -> str:
    """Build a standard unified diff string. Every emitted line is newline-terminated."""
    def _term(lines):
        # keepends=True preserves EXISTING newlines, but files without a
        # trailing newline produced GLUED one-line diffs
        # ("--- a/x+++ b/x@@ ...-old+new") that the diff card could neither
        # render as rows nor count (+0 −0). Always terminate each line.
        return [ln if ln.endswith("\n") else ln + "\n" for ln in lines]
    old_lines = _term(old_text.splitlines(keepends=True))
    new_lines = _term(new_text.splitlines(keepends=True))
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{path}", tofile=f"b/{path}",
        lineterm="\n", n=context,
    ))
    return "".join(diff)

# ============================================================
# GLOBAL REAL-TIME LOGGING SYSTEM - Immediate stdout/stderr flush
# ============================================================
_original_print = print

# --- CROSS IMPORTS ---
from cellium.core.logger import *
from cellium.core.config import *

class AgentTool:
    """Base class for agent tools."""
    def __init__(self, name: str, description: str, parameters: dict):
        self.name = name
        self.description = description
        self.parameters = parameters  # JSON schema for parameters
    
    def execute(self, **kwargs) -> str:
        """Execute the tool and return result as string."""
        raise NotImplementedError

class FileReadTool(AgentTool):
    def __init__(self):
        super().__init__(
            "file_read",
            "Read the contents of a file with line numbers and optional range (start_line, end_line)",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                    "start_line": {"type": "integer", "description": "1-based starting line number (optional)", "default": 1},
                    "end_line": {"type": "integer", "description": "1-based ending line number (optional)", "default": -1}
                },
                "required": ["path"]
            }
        )
    
    def execute(self, path: str = "", start_line: int = 1, end_line: int = -1, **kwargs) -> str:
        if not path:
            path = kwargs.get("file_path", kwargs.get("file", "."))
        try:
            path_obj = Path(path).expanduser().resolve()
            if not path_obj.exists():
                return f"Error: File not found: {path}"
            if path_obj.is_dir():
                return f"Error: Path is a directory: {path}"
            raw = path_obj.read_text(encoding='utf-8', errors='replace')
            lines = raw.splitlines(keepends=True)
            total_lines = len(lines)
            
            s = max(1, int(start_line))
            e = total_lines if int(end_line) <= 0 else min(total_lines, int(end_line))
            
            selected = lines[s-1:e]
            formatted = []
            for i, line in enumerate(selected, start=s):
                formatted.append(f"{i:5d}: {line}")
            
            out = "".join(formatted)
            if len(out) > 50000:
                return out[:50000] + f"\n... (truncated for safety, {total_lines} total lines in file)"
            return out if out else "(empty file)"
        except Exception as e:
            return f"Error reading file: {e}"

class ReplaceFileContentTool(AgentTool):
    """Surgical file editing without rewriting the entire file."""
    def __init__(self):
        super().__init__(
            "replace_file_content",
            "Replace an exact snippet of code or text inside a file with new replacement text",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Target file path"},
                    "target": {"type": "string", "description": "Exact text block to replace"},
                    "replacement": {"type": "string", "description": "New replacement content"}
                },
                "required": ["path", "target", "replacement"]
            }
        )
    
    def execute(self, path: str = ".", target: str = "", replacement: str = "", **kwargs) -> str:
        if not path: path = kwargs.get("file", ".")
        if not target: target = kwargs.get("old", kwargs.get("find", ""))
        if not replacement: replacement = kwargs.get("new", "")
        
        if not target:
            return "Error: No target text provided to replace."
        try:
            path_obj = Path(path).expanduser().resolve()
            if not path_obj.exists():
                return f"Error: File not found: {path}"
            content = path_obj.read_text(encoding='utf-8', errors='replace')
            count = content.count(target)
            if count == 0:
                return f"Error: Target text not found in {path}. Make sure whitespace and formatting match exactly."
            if count > 1:
                return f"Error: Target text occurs {count} times in {path}. Provide more surrounding context to make the target unique."
            
            new_content = content.replace(target, replacement, 1)
            path_obj.write_text(new_content, encoding='utf-8')
            return f"Successfully replaced 1 occurrence in {path}."
        except Exception as e:
            return f"Error replacing file content: {e}"

class GrepSearchTool(AgentTool):
    """Fast regex or literal text search across files in a directory."""
    def __init__(self):
        super().__init__(
            "grep_search",
            "Search for an exact string or regex pattern across files in a directory",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search pattern or string"},
                    "path": {"type": "string", "description": "Directory or file to search", "default": "."},
                    "max_matches": {"type": "integer", "description": "Max results to return", "default": 20}
                },
                "required": ["query"]
            }
        )
    
    def execute(self, query: str = "", path: str = ".", max_matches: int = 20, **kwargs) -> str:
        if not query: query = kwargs.get("pattern", kwargs.get("q", ""))
        if not path: path = kwargs.get("dir", ".")
        if not query: return "Error: No search query provided."
        
        try:
            path_obj = Path(path).expanduser().resolve()
            if not path_obj.exists():
                return f"Error: Path not found: {path}"
            
            matches = []
            files_to_search = [path_obj] if path_obj.is_file() else list(path_obj.rglob("*"))
            
            for f in files_to_search:
                if len(matches) >= max_matches:
                    break
                if f.is_file() and not any(p in f.parts for p in (".git", "__pycache__", "venv", ".venv", "node_modules")):
                    try:
                        text = f.read_text(encoding='utf-8', errors='ignore')
                        for line_idx, line in enumerate(text.splitlines(), start=1):
                            if query.lower() in line.lower():
                                rel_path = f.relative_to(path_obj) if path_obj.is_dir() else f.name
                                matches.append(f"{rel_path}:{line_idx}: {line.strip()}")
                                if len(matches) >= max_matches:
                                    break
                    except Exception:
                        pass
            
            if not matches:
                return f"No matches found for '{query}' in {path}."
            return "\n".join(matches) + (f"\n... (capped at {max_matches} matches)" if len(matches) >= max_matches else "")
        except Exception as e:
            return f"Error in grep_search: {e}"

class FileWriteTool(AgentTool):
    def __init__(self):
        super().__init__(
            "file_write",
            "Write content to a file",
            {"type": "object", "properties": {"path": {"type": "string", "description": "File path to write"}, "content": {"type": "string", "description": "Content to write"}}, "required": ["path", "content"]}
        )
    
    def execute(self, path: str = "", content: str = "", **kwargs) -> str:
        if not path:
            path = kwargs.get("file_path", kwargs.get("file", "."))
        if not content:
            content = kwargs.get("text", kwargs.get("data", ""))
        try:
            path_obj = Path(path).expanduser().resolve()
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            path_obj.write_text(content, encoding='utf-8')
            return f"Successfully wrote {len(content)} chars to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

class FileListTool(AgentTool):
    def __init__(self):
        super().__init__(
            "file_list",
            "List files in a directory",
            {"type": "object", "properties": {"path": {"type": "string", "description": "Directory path to list"}}, "required": ["path"]}
        )
    
    def execute(self, path: str = "", **kwargs) -> str:
        if not path:
            path = kwargs.get("directory_path", kwargs.get("dir", kwargs.get("directory", ".")))
        try:
            path_obj = Path(path).expanduser().resolve()
            if not path_obj.exists():
                return f"Error: Directory not found: {path}"
            if not path_obj.is_dir():
                return f"Error: Path is not a directory: {path}"
            items = []
            for item in path_obj.iterdir():
                if item.is_dir():
                    items.append(f"📁 {item.name}/")
                else:
                    size = item.stat().st_size
                    items.append(f"📄 {item.name} ({size} bytes)")
            return "\n".join(items) if items else "(empty directory)"
        except Exception as e:
            return f"Error listing directory: {e}"

class CodeExecTool(AgentTool):
    def __init__(self):
        super().__init__(
            "code_exec",
            "Execute Python code and return output",
            {"type": "object", "properties": {"code": {"type": "string", "description": "Python code to execute"}, "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30}}, "required": ["code"]}
        )
    
    def execute(self, code: str = "", timeout: int = 30, **kwargs) -> str:
        if not code:
            code = kwargs.get("script", kwargs.get("python", kwargs.get("py", "")))
        if not code:
            return "Error: No code provided."
        import subprocess, tempfile, sys, os
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_path = f.name
            py_exe = resolve_python_executable() if "resolve_python_executable" in globals() else sys.executable
            result = subprocess.run(
                [py_exe, temp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.getcwd()
            )
            os.unlink(temp_path)
            output = ""
            if result.stdout:
                output += f"STDOUT:\n{result.stdout}\n"
            if result.stderr:
                output += f"STDERR:\n{result.stderr}\n"
            if result.returncode != 0:
                output += f"Exit code: {result.returncode}"
            return output.strip() if output else "(no output)"
        except subprocess.TimeoutExpired:
            return f"Error: Execution timed out after {timeout}s"
        except Exception as e:
            return f"Error executing code: {e}"

class WebSearchTool(AgentTool):
    def __init__(self):
        super().__init__(
            "web_search",
            "Search the web for information",
            {"type": "object", "properties": {"query": {"type": "string", "description": "Search query"}, "num_results": {"type": "integer", "description": "Number of results", "default": 5}}, "required": ["query"]}
        )
    
    def execute(self, query: str = "", num_results: int = 5, **kwargs) -> str:
        if not query:
            query = kwargs.get("q", kwargs.get("search", kwargs.get("keywords", "")))
        if not query:
            return "Error: No search query provided."
        try:
            import urllib.request, urllib.parse, json, re
            # Use DuckDuckGo HTML scraping (no API key needed)
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode('utf-8')
            
            # Extract results
            results = []
            # Simple regex to find result snippets
            snippets = re.findall(r'class="result__snippet">(.*?)</a>', html, re.DOTALL)
            links = re.findall(r'class="result__url">(.*?)</a>', html)
            
            for i, (snippet, link) in enumerate(zip(snippets[:num_results], links[:num_results])):
                clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                clean_link = re.sub(r'<[^>]+>', '', link).strip()
                results.append(f"{i+1}. {clean_snippet}\n   Source: {clean_link}")
            
            return "\n\n".join(results) if results else "No results found"
        except Exception as e:
            return f"Error searching web: {e}"

class ShellExecTool(AgentTool):
    def __init__(self):
        super().__init__(
            "shell_exec",
            "Execute a single shell command OR a planned batch of commands sequentially",
            {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Single shell command (supports &&, |, ;)"},
                    "commands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of shell commands to run sequentially as a planned batch",
                    },
                    "workdir": {"type": "string", "description": "Optional working directory path"},
                    "stop_on_error": {"type": "boolean", "description": "Stop batch if a step returns non-zero", "default": True},
                    "timeout": {"type": "integer", "description": "Timeout in seconds per command", "default": 30},
                    "confirmed": {"type": "boolean", "description": "Set true ONLY after the user has explicitly approved a flagged command", "default": False},
                },
            },
        )

    def _run_single(self, command: str, timeout: int, confirmed: bool, run_cwd: str) -> tuple[str, int]:
        try:
            from cellium.core.command_guard import audit_command, format_confirmation_request
            findings = audit_command(command)
            if findings and not confirmed:
                return format_confirmation_request(command, findings, timeout), -999
        except Exception as e:
            try:
                from cellium.core.logger import dev_log
                dev_log(f"[command_guard] audit failed, continuing unguarded: {e}")
            except Exception:
                pass

        proc = None
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=run_cwd,
                start_new_session=True,
            )
            register_active_subprocess(proc)
            stdout_str, stderr_str = proc.communicate(timeout=timeout)
            result = subprocess.CompletedProcess(command, proc.returncode, stdout_str, stderr_str)
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"
            if result.returncode != 0:
                output += f"\nExit code: {result.returncode}"
            return (output.strip() if output else "(no output)"), result.returncode
        except subprocess.TimeoutExpired:
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
            return f"Error: Command timed out after {timeout}s", -1
        except Exception as e:
            return f"Error executing command: {e}", -1
        finally:
            if proc is not None:
                unregister_active_subprocess(proc)

    def execute(self, command: str = "", timeout: int = 30, confirmed: bool = False, **kwargs) -> str:
        commands = kwargs.get("commands") or []
        if isinstance(commands, str):
            commands = [c.strip() for c in commands.splitlines() if c.strip()]
        if not command and not commands:
            raw = kwargs.get("cmd", kwargs.get("shell", kwargs.get("bash", kwargs.get("sh", ""))))
            if isinstance(raw, list):
                commands = [str(x).strip() for x in raw if str(x).strip()]
            else:
                command = str(raw or "")
        if not command and not commands:
            return "Error: No command provided."

        workdir = str(kwargs.get("workdir", kwargs.get("cwd", "")) or "").strip()
        run_cwd = os.getcwd()
        if workdir:
            resolved = Path(workdir).expanduser().resolve()
            if not resolved.is_dir():
                return f"Error: Working directory not found: {workdir}"
            run_cwd = str(resolved)

        # Single command path (100% backward-compatible with regression suite)
        if command and not commands:
            out, _rc = self._run_single(command, timeout, confirmed, run_cwd)
            return out

        # Planned batch execution path
        batch = [str(c).strip() for c in commands if str(c).strip()]
        if command and command.strip() not in batch:
            batch.insert(0, command.strip())
        stop_on_error = bool(kwargs.get("stop_on_error", True))
        reports: list[str] = []
        total = len(batch)
        for idx, cmd_item in enumerate(batch, start=1):
            out, rc = self._run_single(cmd_item, timeout, confirmed, run_cwd)
            reports.append(f"[{idx}/{total}] $ {cmd_item}\n{out}")
            if rc == -999:
                break
            if rc != 0 and stop_on_error:
                reports.append(f"Batch halted at step {idx}/{total} (exit code {rc}).")
                break
        return "\n\n".join(reports)


class BatchExecTool(ShellExecTool):
    """Dedicated alias tool for running a planned list of shell commands in batch."""
    def __init__(self):
        super().__init__()
        self.name = "batch_exec"
        self.description = (
            "Execute a planned sequence of shell commands in batch (one after another) "
            "and return combined step-by-step output."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered list of shell commands to execute in batch",
                },
                "workdir": {"type": "string", "description": "Optional working directory path"},
                "stop_on_error": {"type": "boolean", "description": "Stop batch if a step fails", "default": True},
                "timeout": {"type": "integer", "description": "Timeout in seconds per command", "default": 30},
            },
            "required": ["commands"],
        }




# ── Screenshot Fixes: Batch/Image FileRead & Python -c Newline Sanitizer ─────
_orig_file_read_exec = FileReadTool.execute
_orig_shell_exec = ShellExecTool.execute


def _patched_file_read_exec(self, path: str = "", start_line: int = 1, end_line: int = 250, **kwargs) -> str:
    """Support single `path`, batch `paths`/`files` lists, and `.png`/`.jpg` image inspection!"""
    batch = kwargs.get("paths") or kwargs.get("files") or kwargs.get("file_paths")
    if isinstance(batch, (list, tuple)) and batch:
        results = []
        for p_item in batch[:10]:
            results.append(f"=== {p_item} ===\n" + _patched_file_read_exec(self, path=str(p_item), start_line=start_line, end_line=end_line))
        return "\n\n".join(results)

    target = path or kwargs.get("file_path") or kwargs.get("file") or kwargs.get("filename") or ""
    if isinstance(target, (list, tuple)):
        return _patched_file_read_exec(self, paths=target, start_line=start_line, end_line=end_line)
    target = str(target).strip()
    if not target:
        return "Error: Please provide a file `path` to read."

    p_obj = Path(target).expanduser()
    if not p_obj.is_Absolute() if hasattr(p_obj, "is_Absolute") else not p_obj.is_absolute():
        p_obj = (Path.cwd() / p_obj).resolve()

    if p_obj.is_file() and p_obj.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        size_kb = p_obj.stat().st_size / 1024.0
        dims = ""
        try:
            from PySide6.QtGui import QImage
            im = QImage(str(p_obj))
            if not im.isNull():
                dims = f", dimensions={im.width()}x{im.height()}px"
        except Exception:
            pass
        return f"[Image File Verified: {p_obj.name} ({size_kb:.1f} KB{dims}) at {p_obj}]"

    return _orig_file_read_exec(self, path=str(p_obj), start_line=start_line, end_line=end_line)


def _patched_shell_exec(self, command: str = "", **kwargs) -> str:
    """Sanitize literal newlines inside `python3 -c "..."` one-liners so they never throw SyntaxError!"""
    cmd = str(command or "").strip()
    if re.match(r"^python3?\s+-c\s+", cmd) and "\n" in cmd:
        # Replace literal newlines inside the -c payload with escaped \\n
        m = re.match(r"^(python3?\s+-c\s+)(['\"])(.*)\2\s*$", cmd, flags=re.DOTALL)
        if m:
            prefix, quote_ch, body = m.groups()
            fixed_body = body.replace("\r\n", "\\n").replace("\n", "\\n")
            cmd = f"{prefix}{quote_ch}{fixed_body}{quote_ch}"
        else:
            cmd = cmd.replace("\r\n", "\\n").replace("\n", "\\n")
    return _orig_shell_exec(self, command=cmd, **kwargs)


FileReadTool.execute = _patched_file_read_exec
ShellExecTool.execute = _patched_shell_exec
