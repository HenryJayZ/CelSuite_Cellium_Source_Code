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
from pathlib import Path
from datetime import datetime
import numpy as np

# ============================================================
# GLOBAL REAL-TIME LOGGING SYSTEM - Immediate stdout/stderr flush
# ============================================================
_original_print = print

# --- CROSS IMPORTS ---
from cellium.core.logger import *
from cellium.core.config import *
from cellium.core.utils import *
from cellium.core.tools import *
from cellium.services.ai_llama import (
    get_or_load_llama,
    prepare_llama_session,
    request_llama_abort,
    clear_llama_abort,
    begin_llama_use,
    end_llama_use,
    _LLAMA_INFER_LOCK,
)

# ── SHARED HELPERS ──────────────────────────────────────────────
def resolve_offline_model_path(model_key="", settings=None, models=None):
    """Return local GGUF path if this model key refers to an offline model, else None."""
    import os, re
    settings = settings or {}
    models = models or {}
    key = (model_key or "").strip()
    route = models.get(key) if key else None

    offline_map = settings.get("offline_models", {}) or {}
    local_model_path = settings.get("local_model_path", "")

    def _clean(k):
        # One canonical parser for every historical offline label shape
        # (📁 Offline: Name, 📂 Name.gguf 806.1MB, 📂 806.1MB Name.gguf).
        return strip_offline_label(k)

    is_offline_marker = is_offline_model_key(key, route)

    path = ""
    if is_offline_marker:
        clean = _clean(key)
        path = offline_map.get(clean, "") or offline_map.get(key, "")
        if not path:
            for name, p in offline_map.items():
                cn = _clean(name)
                if cn.lower() == clean.lower() or clean.lower() in cn.lower() or cn.lower() in clean.lower():
                    path = p
                    break
        if not path and key.lower().endswith(".gguf"):
            path = key if os.path.exists(key) else ""
        if not path:
            path = local_model_path

    if path and os.path.exists(path):
        return path
    return None


def resolve_any_offline_path(settings):
    """Return any available local GGUF path from settings."""
    import os
    settings = settings or {}
    offline_map = settings.get("offline_models", {}) or {}
    for name, p in offline_map.items():
        if p and os.path.exists(p):
            return p
    lp = settings.get("local_model_path", "")
    if lp and os.path.exists(lp):
        return lp
    return None


def message_needs_agent_tools(text):
    """Deprecated for routing: agent mode now always passes tools (tool_choice=auto).
    Kept only as an optional UI hint for 'this may use tools' badges.
    """
    import re
    t = (text or "").strip()
    if not t:
        return False

    # Explicit tool markers
    if re.search(r'\b(TOOL_CALL|shell_exec|file_read|file_write|grep_search|code_exec|web_search|run command|execute this|run this)\b', t, re.I):
        return True

    # Tool-intent verbs & phrases
    tool_verbs = r'\b(run|execute|install|compile|refactor|debug|grep|search\s+files|list\s+(files|directory)|read\s+(the\s+)?file|write\s+(a\s+)?file|edit\s+(the\s+)?file|create\s+(a\s+)?(file|folder|directory)|delete\s+(the\s+)?(file|folder)|mkdir|git\s+(push|pull|commit|clone|status)|pip\s+install|npm\s+install|shell|bash|terminal|open\s+(the\s+)?(file|folder)|check\s+(the\s+)?(logs|directory|files|my\s+(pc|system|hardware|specs)|system\s+info|hardware\s+info|pc\s+specs|specs)|look\s+up|google|browse|download|web\s*search|search\s+the\s+(web|internet))\b'
    if re.search(tool_verbs, t, re.I):
        return True

    # Explicit "agent mode" phrasing
    if re.search(r'\b(using|with|enable|turn\s+on)\s+agent\s+(mode|tools?)\b', t, re.I):
        return True

    # "tell/show me what is in <path>" or "what's in <path>" - directory listing intent
    if re.search(r'\b(tell|show|what.{0,5}in|list|ls)\b.*[\w./~-]+(/[\w.-]+)+', t, re.I):
        return True

    # File path with action verb
    if re.search(r'[\w./~-]+\.(py|js|ts|sh|json|md|txt|cpp|c|h|java|go|rs|yml|yaml|toml|cfg|ini|log)\b', t) and re.search(r'\b(read|open|edit|fix|write|check|run|delete|create|find|search)\b', t, re.I):
        return True

    # Long message with code-ish intent
    if len(t) > 60 and re.search(r'\b(code|script|program|project|function|class|bug|error|stack\s*trace|implement|build|deploy)\b', t, re.I):
        return True

    # Casual greetings / tiny talk → never tools
    casual = re.fullmatch(r'(hi|hey|hello|yo|sup|hiya|howdy|hola|henlo|good\s+(morning|evening|afternoon)|thanks?|thank\s+you|ty|ok(?:ay)?|lol|haha|yes|no|yep|nope|cool|nice|wow|amazing|cute|love\s+it|please|help|what\s+can\s+you\s+do)[\s!.?~💕✨🎀😅]*', t, re.IGNORECASE)
    if casual:
        return False

    # Short non-tool messages → chat
    if len(t) <= 12 and not re.search(tool_verbs, t, re.I):
        return False

    return False


# ── Offline chat templates ───────────────────────────────────────────────────
# The normal offline path is fine: llama-cpp-python's create_chat_completion
# applies the GGUF's *own* template. The FALLBACK path calls llm(prompt_text)
# with whatever we built by hand, and that hand-built prompt used to be a bare
# "role\ncontent\n" transcript with no template at all - which is exactly how a
# ChatML model like Qwen ends up answering the last line of your history.
def detect_offline_template(model_path) -> str:
    """Guess the chat template from the model filename.

    Autodetect exists because collecting random GGUFs means the filename is the
    only signal available: a Qwen finetune called "...-abliterated.Q5_K_M.gguf"
    still says qwen, and matching on the family beats a wrong global default.
    """
    name = str(model_path or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    if not name:
        return "Plain transcript (no template)"
    if "llama-3" in name or "llama3" in name:
        return "Llama 3"
    if "gemma" in name:
        return "Gemma"
    # ChatML families are tested BEFORE Mistral: merges like
    # "dolphin-mixtral" carry a ChatML template in their GGUF metadata, so the
    # base family wins over the merge suffix. SmolLM2 ships a ChatML template
    # too, so it belongs here (it previously fell through to the plain
    # transcript and deranged tiny models further).
    if any(k in name for k in ("qwen", "dolphin", "hermes", "phi",
                               "abacus", "glm", "internlm", "smol")):
        return "ChatML (Qwen / Dolphin / Hermes)"
    if "mistral" in name or "mixtral" in name or "ministral" in name:
        return "Mistral / Mixtral [INST]"
    return "Plain transcript (no template)"


def _resolve_offline_style(settings, model_path):
    """The user's choice, or the detected one when they chose Auto."""
    try:
        want = str((settings or {}).get("offline_format", "") or "")
    except Exception:
        want = ""
    if not want or want.startswith("Auto"):
        return detect_offline_template(model_path)
    return want


def format_offline_prompt(messages, style=None, model_path="") -> str:
    """Render chat messages with the requested template.

    Unknown styles fall back to the plain transcript rather than raising - a
    bad setting must never be the reason a reply cannot be generated.
    """
    msgs = list(messages or [])
    style = str(style or "Plain transcript (no template)")
    sys_text = "\n\n".join(
        str(m.get("content", "")) for m in msgs if m.get("role") == "system")
    turns = [m for m in msgs if m.get("role") in ("user", "assistant")]

    if style == "ChatML (Qwen / Dolphin / Hermes)":
        out = []
        if sys_text:
            out.append(f"<|im_start|>system\n{sys_text}<|im_end|>")
        for m in turns:
            out.append(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>")
        out.append("<|im_start|>assistant\n")
        return "\n".join(out) + "\n"

    if style == "Llama 3":
        out = ["<|begin_of_text|>"]
        if sys_text:
            out.append(
                f"<|start_header_id|>system<|end_header_id|>\n\n"
                f"{sys_text}<|eot_id|>")
        for m in turns:
            out.append(f"<|start_header_id|>{m['role']}<|end_header_id|>\n\n"
                       f"{m['content']}<|eot_id|>")
        out.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
        return "\n".join(out)

    if style == "Mistral / Mixtral [INST]":
        out = ["<s>"]
        for i, m in enumerate(turns):
            if m["role"] == "user":
                prefix = f"[INST] {sys_text}\n" if (i == 0 and sys_text) else "[INST] "
                out.append(f"{prefix}{m['content']} [/INST]")
            else:
                out.append(f" {m['content']}</s>")
        if not turns:
            out.append(f"[INST] {sys_text} [/INST]")
        return "".join(out)

    if style == "Gemma":
        out = ["<bos>"]
        if sys_text:
            out.append(f"<start_of_turn>user\n{sys_text}<end_of_turn>\n")
        for m in turns:
            role = "model" if m["role"] == "assistant" else "user"
            out.append(f"<start_of_turn>{role}\n{m['content']}<end_of_turn>\n")
        out.append("<start_of_turn>model\n")
        return "".join(out)

    # Plain transcript - the original behaviour.
    raw = ""
    if sys_text:
        raw += f"system\n{sys_text}\n"
    for m in turns:
        raw += f"{m['role']}\n{m['content']}\n"
    return raw + "assistant\n"


class GenerationSignals(QObject):
    delta = Signal(str, str)
    done = Signal(str, str, int, float, bool)
    error = Signal(str, str, str)
    status = Signal(str)


# ------------------------------------------------------------------ AI Auto-Rename Background Worker
class AIRenameSignals(QObject):
    finished = Signal(str, str) # sid, generated_title
    error = Signal(str)

class AIRenameWorker(QThread):
    def __init__(self, sid, prompt_context, settings, models, providers, parent=None):
        super().__init__(parent)
        self.sid = sid
        self.context = prompt_context
        self.settings = settings
        self.models = models
        self.providers = providers
        self.signals = AIRenameSignals()

    def run(self):
        try:
            cur_model = self.settings.get("selected_model", "")
            title_prompt = (
                f"You are a concise title generator. Summarize the main topic of this chat into 2 to 4 words. "
                f"Do not use quotes, punctuation, or markdown. Output ONLY the 2-4 word title:\n\n"
                f"{self.context[:350]}\n\nTitle:"
            )
            # Smart title extraction fallback for offline or no-cloud models
            fallback_title = ""
            if self.context:
                clean_lines = []
                for line in self.context.splitlines():
                    cleaned = re.sub(r'^(User|Cel|Assistant):\s*', '', line, flags=re.I).strip()
                    cleaned = re.sub(r'[*_`#~\[\]\(\)<>]', '', cleaned).strip()
                    if cleaned:
                        clean_lines.append(cleaned)
                if clean_lines:
                    words = [w for w in clean_lines[0].split() if w.lower() not in (
                        "what", "how", "why", "can", "you", "please", "the", "a", "an",
                        "is", "are", "do", "i", "me", "my", "to", "for", "in", "on", "of", "and"
                    )]
                    if len(words) >= 2:
                        fallback_title = " ".join(words[:4]).title()
                    else:
                        fallback_title = " ".join(clean_lines[0].split()[:4]).title()
                    fallback_title = fallback_title[:24].strip()

            # Offline GGUF fallback
            if is_offline_model_key(cur_model, self.models.get(cur_model)) or not cur_model:
                out = fallback_title or "Chat Discussion"
                self.signals.finished.emit(self.sid, out)
                return

            # Cloud provider call
            m_info = self.models.get(cur_model, {})
            p_name = m_info.get("provider", "Cerebras Fast Cloud")
            p_data = self.providers.get(p_name, {})
            api_key = p_data.get("key") or self.settings.get("user_custom_keys", {}).get(p_name, "")
            base_url = m_info.get("base_url") or "https://api.cerebras.ai/v1"

            if not api_key:
                out = fallback_title or "Chat Discussion"
                self.signals.finished.emit(self.sid, out)
                return

            from openai import OpenAI
            net_timeout = get_network_timeout(self.settings)
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=net_timeout)
            res = client.chat.completions.create(
                model=m_info.get("model", "llama3.1-8b"),
                messages=[{"role": "user", "content": title_prompt}],
                max_tokens=16,
                temperature=0.3
            )
            raw_title = res.choices[0].message.content.strip()
            clean_title = re.sub(r'["\'*#_\n]', "", raw_title).strip()[:24]
            if clean_title:
                self.signals.finished.emit(self.sid, clean_title)
        except Exception as e:
            self.signals.error.emit(str(e))

#: Minted Copilot tokens are short-lived - exchanged once, reused until near
#: expiry so every turn doesn't pay for a token round-trip.
_COPILOT_CACHE = {"token": "", "exp": 0.0}


def _copilot_bearer(settings) -> str:
    """Copilot Bearer token, minted from the GitHub token and cached."""
    try:
        from cellium.core.utils import copilot_github_token, exchange_copilot_token
        now = time.time()
        if _COPILOT_CACHE["token"] and _COPILOT_CACHE["exp"] - now > 120:
            return _COPILOT_CACHE["token"]
        tok, exp = exchange_copilot_token(copilot_github_token(settings))
        if tok:
            _COPILOT_CACHE["token"] = tok
            _COPILOT_CACHE["exp"] = float(exp or (now + 1500.0))
            return tok
    except Exception:
        pass
    return ""


class GenerationWorker(QThread):
    def __init__(self, session_id, user_prompt, settings, sessions, models, providers, dev_mem, attachments=None, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.user_prompt = user_prompt
        self.settings = dict(settings)
        self.sessions = dict(sessions)
        self.models = dict(models)
        self.providers = dict(providers)
        self.dev_mem = dev_mem
        self.attachments = attachments or []
        self.signals = GenerationSignals()
        self._stop_event = threading.Event()

    def _emit_status(self, msg: str):
        """Thread-safe status emission - use instead of lambda capturing self.signals"""
        self.signals.status.emit(msg)

    @property
    def stop_requested(self):
        return self._stop_event.is_set()

    @stop_requested.setter
    def stop_requested(self, val):
        if val:
            self._stop_event.set()
        else:
            self._stop_event.clear()

    def request_stop(self):
        self._stop_event.set()
        try:
            request_llama_abort()
        except Exception:
            pass
        resp = getattr(self, "_active_resp", None)
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def run(self):
        """Guarantee a terminal signal - see AgentWorker.run for the rationale."""
        begin_llama_use()
        try:
            self._run_impl()
        except Exception as exc:
            try:
                self.signals.error.emit(
                    self.session_id,
                    "Generation crashed",
                    f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass
        finally:
            # Only now may the UI close the native llama context.
            end_llama_use()

    def _run_impl(self):
        start_t = time.time()
        ses = self.sessions.get(self.session_id)
        if not ses:
            self.signals.error.emit(self.session_id, "Session Error", "Active session not found.")
            return

        model_key = self.settings.get("selected_model", "")
        route = self.models.get(model_key)
        offline_path = resolve_offline_model_path(model_key, self.settings, self.models)
        is_offline = bool(offline_path)
        has_vision = is_vision_model(model_key, route)

        # No API key for the selected online model? Gracefully fall back to any local GGUF.
        if not is_offline:
            if isinstance(route, dict):
                target_server = route.get("provider", "Cerebras")
            else:
                target_server = self.settings.get("selected_provider", "Cerebras")
            custom_keys = self.settings.get("user_custom_keys", {})
            api_key = custom_keys.get(target_server, "")
            if not api_key:
                provider_data = self.providers.get(target_server, {})
                keys = provider_data.get("keys", [])
                if keys:
                    api_key = keys[0]
            if not api_key:
                fallback_gguf = resolve_any_offline_path(self.settings)
                if fallback_gguf:
                    offline_path = fallback_gguf
                    is_offline = True
                    self.signals.status.emit("🔑 No API key - chatting on local GGUF instead 💾")

        # Memory already contains system prompt as first entry - use it directly!
        # Just append the new user message to existing memory
        want_mood = bool(self.settings.get("_mood_contract_active", False))
        messages = []
        for m in ses.get("memory", []):
            if m.get("role") in ("system", "user", "assistant"):
                c = m.get("content", "")
                if m["role"] == "system" and not want_mood:
                    # Strip the live-only mood contract; send NOTHING in its
                    # place. The old "do not start with mood:" sentence was a
                    # pure token tax on every plain-chat turn - also purge it
                    # from sessions saved by older builds.
                    c = re.sub(r"\n*\[MOOD CONTRACT:.*?\]", "", c, flags=re.DOTALL)
                    c = re.sub(
                        r"\n*\[IMPORTANT: Do NOT start your reply with `mood:`"
                        r" or any emotion tag\.\]", "", c)
                if m["role"] == "assistant":
                    c = re.sub(r"<agent_action\b.*?</agent_action\s*>", "", c, flags=re.DOTALL | re.IGNORECASE)
                    c = re.sub(r"<think(?:\s[^>]*)?>.*?</think\s*>", "", c, flags=re.DOTALL | re.IGNORECASE).strip()
                    run_log = m.get("code_run_log", "")
                    if run_log:
                        c = f"{c}\n\n{run_log}".strip()
                if m["role"] == "user" and "Prompt - " in c:
                    c = c.split("Prompt - ", 1)[-1]
                att_txt = m.get("attached_files_text", "")
                if m["role"] == "user" and att_txt and att_txt not in c:
                    if c.strip() == "*(sent attachments)*":
                        c = f"Please inspect the attached snippet/file(s):{att_txt}"
                    else:
                        c = f"{c}{att_txt}"
                messages.append({"role": m["role"], "content": c})

        # CRITICAL: Remove trailing empty assistant messages - API requires conversation to end with user turn
        while messages and messages[-1]["role"] == "assistant" and not messages[-1]["content"].strip():
            messages.pop()

        prompt_with_files = self.user_prompt or ("Please analyze the attached snippet/file(s):" if self.attachments else "")
        image_attachments = []
        for att in self.attachments:
            if att["type"] == "image":
                image_attachments.append(att)
            elif att["type"] == "file":
                f_name = att.get('name', 'file')
                f_path = att.get('path', 'unknown')
                f_content = att.get('content', '')
                line_count = f_content.count('\n') + 1 if f_content else 0
                char_count = len(f_content)
                prompt_with_files += f"\n\n[Attached File: {f_name} (Location: {f_path}, Lines: {line_count}, Characters: {char_count})]\n```{att.get('ext', '')}\n{f_content}\n```"

        if image_attachments and has_vision and not is_offline:
            user_content = [{"type": "text", "text": prompt_with_files}]
            for img in image_attachments:
                mime = img.get("mime", "image/png")
                b64 = img.get("base64", "")
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"}
                })
            messages.append({"role": "user", "content": user_content})
        else:
            # Ensure the user message in messages contains the attached files
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] = prompt_with_files
            else:
                messages.append({"role": "user", "content": prompt_with_files})

        parts = []
        try:
            if is_offline:
                local_path = offline_path
                if not local_path or not os.path.exists(local_path):
                    self.signals.error.emit(self.session_id, "No Offline Model", f"Local GGUF model path not found for {model_key or 'local_model_path'}. Please configure in Model Hub.")
                    return

                n_ctx = int(self.settings.get("offline_n_ctx", 2048))
                n_threads = int(self.settings.get("offline_threads", max(1, (os.cpu_count() or 4) // 2)))
                n_gpu_layers = int(self.settings.get("offline_gpu_layers", 0))
                temp = float(self.settings.get("offline_temperature", 0.7))
                top_p = float(self.settings.get("offline_top_p", 0.9))
                rep_pen = float(self.settings.get("offline_repeat_penalty", 1.1))
                type_k = self.settings.get("offline_kv_cache_type_k", "f16")
                type_v = self.settings.get("offline_kv_cache_type_v", "f16")
                flash_attn = self.settings.get("offline_flash_attn", False)
                cache_prompt = self.settings.get("offline_cache_prompt", False)

                llm = get_or_load_llama(
                    model_path=local_path,
                    n_ctx=n_ctx,
                    n_threads=n_threads,
                    n_gpu_layers=n_gpu_layers,
                    type_k=type_k,
                    type_v=type_v,
                    flash_attn=flash_attn,
                    cache_prompt=cache_prompt,
                    status_cb=self._emit_status,
                )

                self.signals.status.emit("🧠 Local GGUF Generating...")

                chat_messages = []
                for m in messages:
                    c = m["content"]
                    if isinstance(c, list):
                        c = " ".join([item.get("text", "") for item in c if item.get("type") == "text"])
                    chat_messages.append({"role": m["role"], "content": c})

                def _calc_tokens(msgs):
                    raw_p = format_offline_prompt(
                        msgs,
                        _resolve_offline_style(self.settings, local_path),
                        local_path)
                    try:
                        return len(llm.tokenize(raw_p.encode("utf-8", errors="ignore"))), raw_p
                    except Exception:
                        return max(10, len(raw_p) // 3), raw_p

                # Thinking level for local GGUF: prompt-injected directives
                # (these models have no reasoning_effort API). "Low" means NO
                # deliberation and NO <think> tags - the old "minimal
                # deliberation" phrasing still let reasoning models think out
                # loud, which is why Low behaved like High.
                from cellium.core.utils import thinking_level_key
                thinking_level = thinking_level_key(
                    self.settings.get("thinking_level", "auto"))
                think_directive = ""
                if thinking_level == "force_off":
                    think_directive = (
                        "\n[THINKING MODE: FORCE OFF - CRITICAL] Do NOT reason, "
                        "plan, analyze, or deliberate. Do NOT emit <think> tags "
                        "or any internal monologue. Answer immediately with ONLY "
                        "the final response - never restate the question, never "
                        "explain your process. Any thinking is forbidden and "
                        "wastes the user's quota."
                    )
                elif thinking_level == "off":
                    think_directive = (
                        "\n[REASONING DIRECTIVE: Answer directly and concisely. "
                        "Do NOT deliberate, reason, or emit <think> tags - "
                        "respond immediately with only the final answer.]"
                    )
                elif thinking_level in ("high", "max"):
                    think_directive = (
                        "\n[REASONING DIRECTIVE: Think deeply step-by-step before answering. "
                        "Enclose your internal reasoning and step-by-step problem breakdown inside "
                        "<think>...</think> tags before providing your final answer.]"
                    )
                elif thinking_level == "medium":
                    think_directive = (
                        "\n[REASONING DIRECTIVE: Answer concisely. Only deliberate "
                        "inside <think>...</think> tags when the problem genuinely "
                        "needs math, code, or multi-step logic.]"
                    )
                elif thinking_level in ("low", "minimal"):
                    think_directive = (
                        "\n[REASONING DIRECTIVE: Answer directly and briefly. "
                        "Do NOT reason step-by-step. Do NOT emit <think> tags "
                        "or any internal monologue - only the final answer.]"
                    )

                if think_directive and chat_messages:
                    if chat_messages[0]["role"] == "system":
                        chat_messages[0] = dict(chat_messages[0])
                        chat_messages[0]["content"] += think_directive
                    else:
                        chat_messages.insert(0, {"role": "system", "content": think_directive.strip()})

                # Bug #22: Fast sliding history window for CPU GGUF inference.
                # Resuming an old chat with dozens of turns used to feed 1,500+
                # tokens into an 8B model on 2 CPU threads (taking 15-20 mins!).
                # Keep the system prompt + last 6 turns (or ~750 tokens max for history).
                if len(chat_messages) > 8:
                    sys_msg = [chat_messages[0]] if chat_messages[0]["role"] == "system" else []
                    turns = chat_messages[1:] if sys_msg else chat_messages[:]
                    chat_messages = sys_msg + turns[-6:]

                prompt_tokens, prompt_text = _calc_tokens(chat_messages)

                reserve_buffer = max(512, int(n_ctx * 0.45))
                max_history_tokens = max(512, min(900, n_ctx - reserve_buffer))
                if prompt_tokens > max_history_tokens and len(chat_messages) > 2:
                    sys_msg = [chat_messages[0]] if chat_messages[0]["role"] == "system" else []
                    turns = chat_messages[1:] if sys_msg else chat_messages[:]
                    while len(turns) > 1 and prompt_tokens > max_history_tokens:
                        turns.pop(0)
                        prompt_tokens, prompt_text = _calc_tokens(sys_msg + turns)
                    chat_messages = sys_msg + turns

                # If still over limit due to massive attachment or turn, trim middle of latest prompt
                if prompt_tokens > n_ctx - 384 and chat_messages:
                    last_msg = dict(chat_messages[-1])
                    content = last_msg.get("content", "")
                    if len(content) > 1000:
                        trim_len = max(500, int(len(content) * 0.6))
                        last_msg["content"] = content[:trim_len] + "\n\n[...content truncated for context budget...]\n"
                        chat_messages[-1] = last_msg
                        prompt_tokens, prompt_text = _calc_tokens(chat_messages)

                available_tokens = max(128, n_ctx - prompt_tokens - 24)
                safe_max_tokens = max(64, min(1024, available_tokens))

                # Merge system prompt into first user message to prevent create_chat_completion from crashing 
                # on GGUF models that don't support the 'system' role natively (e.g. Llama-3, Phi-3).
                safe_chat_messages = []
                system_text = ""
                for m in chat_messages:
                    if m["role"] == "system":
                        system_text += m["content"] + "\n\n"
                    else:
                        safe_chat_messages.append(dict(m))
                if system_text:
                    if safe_chat_messages and safe_chat_messages[0]["role"] == "user":
                        safe_chat_messages[0]["content"] = system_text + safe_chat_messages[0]["content"]
                    else:
                        safe_chat_messages.insert(0, {"role": "user", "content": system_text.strip()})

                # NOTE (#26): think_directive is already merged into safe_chat_messages[0] via
                # system_text above. Keeping it out of safe_chat_messages[-1] ensures earlier
                # turns never change their token prefix, preserving llama.cpp KV prefix reuse!

                if not _LLAMA_INFER_LOCK.acquire(blocking=False):
                    self.signals.status.emit("⏳ Waiting for previous local generation to release GGUF...")
                    request_llama_abort()
                    _LLAMA_INFER_LOCK.acquire()
                try:
                    clear_llama_abort()
                    prepare_llama_session(llm, self.session_id)
                    dev_log(
                        f"[GGUF] Evaluating prompt: {prompt_tokens} tokens "
                        f"({len(safe_chat_messages)} messages, max_new={safe_max_tokens})"
                    )
                    self.signals.status.emit(f"🧠 Local GGUF reading {prompt_tokens} tokens...")
                    res = llm.create_chat_completion(
                        messages=safe_chat_messages,
                        max_tokens=safe_max_tokens,
                        temperature=temp,
                        top_p=top_p,
                        repeat_penalty=rep_pen,
                        stream=True
                    )
                    generated_tokens_count = 0
                    for chunk in res:
                        if self.stop_requested:
                            break
                        generated_tokens_count += 1
                        # Hard stop safety check to prevent C++ GGML_ASSERT(i1 >= 0 && i1 < ne1)
                        if prompt_tokens + generated_tokens_count >= n_ctx - 8:
                            dev_log(f"[DEV] Local GGUF hit safe context ceiling ({prompt_tokens + generated_tokens_count}/{n_ctx}); finished generation cleanly.")
                            break
                        delta = chunk["choices"][0].get("delta", {})
                        t = delta.get("content", "")
                        if t:
                            parts.append(t)
                            self.signals.delta.emit(self.session_id, t)
                except Exception as gen_exc:
                    # Never swallow this silently: the fallback builds a raw
                    # transcript by hand, which mis-renders ChatML models and
                    # makes a tiny model regurgitate its persona intro. Log it.
                    dev_log(f"[GGUF] create_chat_completion failed; falling back to raw transcript: {gen_exc}")
                    res = llm(prompt_text, max_tokens=safe_max_tokens, stop=["<|im_end|>", "<|im_start|>"], stream=True)
                    for chunk in res:
                        if self.stop_requested:
                            break
                        t = chunk["choices"][0].get("text", "")
                        if t:
                            parts.append(t)
                            self.signals.delta.emit(self.session_id, t)
                finally:
                    try:
                        _LLAMA_INFER_LOCK.release()
                    except RuntimeError:
                        pass
                    llm = None
            else:
                target_server = route.get("provider") if isinstance(route, dict) else "Cerebras"
                target_model = route.get("model") if isinstance(route, dict) else "llama3.3-70b"
                base_url = route.get("base_url") if isinstance(route, dict) else None
                _is_copilot = (target_server == "GitHub Copilot")

                custom_keys = self.settings.get("user_custom_keys", {})
                api_key = custom_keys.get(target_server)
                if not api_key and _is_copilot:
                    # Hub key missing - environment is a valid second home.
                    api_key = os.environ.get("CELSTUDIO_GITHUB_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
                if not api_key:
                    provider_data = self.providers.get(target_server, {})
                    keys = provider_data.get("keys", [])
                    if keys:
                        api_key = keys[0]

                if not api_key:
                    self.signals.error.emit(
                        self.session_id,
                        "API Key Required",
                        f"No API key configured for {target_server}.\n\nGo to Model Hub (🎛️) to paste your key!"
                    )
                    return

                if not base_url:
                    cfg = PROVIDER_DEFS.get(target_server, PROVIDER_DEFS["Cerebras"])
                    base_url = self.settings.get("custom_provider_urls", {}).get(target_server, cfg["base_url"])

                if _is_copilot:
                    # Copilot needs the minted token + client headers, not the
                    # raw GitHub token with stock OpenAI headers.
                    _copilot_bearer_token = _copilot_bearer(self.settings)
                    if not _copilot_bearer_token:
                        self.signals.error.emit(
                            self.session_id, "Copilot Token",
                            "Could not mint a Copilot token. Paste a GitHub token in Model Hub → GitHub Copilot (or set CELSTUDIO_GITHUB_TOKEN).")
                        return
                    from cellium.core.utils import copilot_headers
                    headers = copilot_headers(_copilot_bearer_token)
                else:
                    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                # Include thinking level for models that support reasoning effort
                # (normalised key - legacy labels like "🧠 Low" used to slip
                # past the sentinel check and send no effort at all).
                from cellium.core.utils import thinking_level_key
                thinking_level = thinking_level_key(
                    self.settings.get("thinking_level", "auto"))
                if thinking_level == "force_off":
                    # Belt AND braces: native effort + an explicit critical
                    # system directive. Reasoning models still "reason" when
                    # the provider only lowers effort, which is exactly the
                    # 40-line internal monologue this mode exists to kill.
                    try:
                        from cellium.core.utils import inject_force_off_directive
                        inject_force_off_directive(messages)
                    except Exception:
                        pass
                from cellium.core.utils import normalize_google_model_id, build_online_thinking_params
                if target_server == "Google Gemini":
                    target_model = normalize_google_model_id(target_model)
                payload = {"model": target_model, "messages": messages, "temperature": 0.2, "stream": True}

                # OpenRouter dynamic routing & context uncapping
                is_openrouter = (target_server == "OpenRouter") or ("openrouter" in base_url.lower())
                if is_openrouter:
                    from cellium.core.utils import (
                        build_openrouter_routing_payload,
                        handle_openrouter_affordability_error,
                    )
                    token_mode = self.settings.get("openrouter_token_usage", "medium (safe for casual coding)")
                    or_routing = build_openrouter_routing_payload(
                        model_id=target_model,
                        messages=messages,
                        mode=token_mode,
                        max_output_tokens=payload.get("max_tokens", 4096),
                    )
                    if "transforms" in or_routing:
                        payload["transforms"] = or_routing["transforms"]
                    if "provider" in or_routing:
                        payload["provider"] = or_routing["provider"]

                if thinking_level not in ("auto", "off") and not _is_copilot:
                    # Copilot takes no reasoning_effort - sending it errors the turn.
                    # Map UI values to API values
                    effort_map = {"minimal": "minimal", "low": "low", "medium": "medium", "high": "high", "max": "max"}
                    if thinking_level == "force_off":
                        # Lowest effort every reasoning-capable provider accepts;
                        # the resilient 400-retry strips it if unsupported.
                        payload["reasoning_effort"] = "minimal"
                    elif thinking_level in effort_map:
                        payload["reasoning_effort"] = effort_map[thinking_level]

                last_err = None
                net_retries = get_network_max_retries(self.settings)
                net_timeout = get_network_timeout(self.settings)
                for attempt in range(net_retries):
                    if self.stop_requested:
                        raise Exception("Stopped by user")
                    try:
                        if attempt > 0:
                            self.signals.status.emit(f"📡 Network dropped! Retrying ({attempt}/{net_retries})...")
                            time.sleep(2.0)
                        
                        self.signals.status.emit(f"📡 Connecting to {target_server}...")
                        resp = requests.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=payload, stream=True, timeout=net_timeout)
                        self._active_resp = resp
                        if self.stop_requested:
                            try:
                                resp.close()
                            except Exception:
                                pass
                            break
                        
                        if resp.status_code != 200:
                            err_text = resp.text
                            # OpenRouter Auto-Affordability Clamp (402 / Credit Pre-Check Recovery)
                            if is_openrouter:
                                from cellium.core.utils import handle_openrouter_affordability_error
                                affordable = handle_openrouter_affordability_error(err_text)
                                if affordable is not None:
                                    if affordable >= 128:
                                        clamped_max = max(64, affordable - 20)
                                        payload["max_tokens"] = clamped_max
                                        self.signals.status.emit(f"⚠️ OpenRouter credit limit: auto-clamped to {clamped_max} tokens. Retrying...")
                                        resp = requests.post(
                                            f"{base_url.rstrip('/')}/chat/completions",
                                            headers=headers,
                                            json=payload,
                                            stream=True,
                                            timeout=net_timeout,
                                        )
                                        self._active_resp = resp
                                        if resp.status_code == 200:
                                            break  # Succeeded with clamped max_tokens!
                                        err_text = resp.text
                                    else:
                                        raise Exception(
                                            f"OpenRouter wallet depleted (can only afford {affordable} tokens). "
                                            "Please top up your OpenRouter account or switch to a :free model."
                                        )
                            if resp.status_code in (408, 429, 500, 502, 503, 504):
                                last_err = Exception(f"HTTP {resp.status_code}: {err_text[:220]}")
                                continue
                            raise Exception(f"HTTP {resp.status_code}: {err_text[:220]}")
                        
                        break # Success
                    except requests.exceptions.RequestException as e:
                        last_err = e
                        continue
                else:
                    raise last_err

                self.signals.status.emit("💭 Waiting for first token...")
                first_token = True
                for raw in resp.iter_lines():
                    if self.stop_requested:
                        break
                    if not raw:
                        continue
                    line = raw.decode("utf-8", "ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        obj = json.loads(data_str)
                        delta = (obj.get("choices", [{}])[0].get("delta", {}) or {}).get("content")
                        if delta:
                            if first_token:
                                self.signals.status.emit("✨ Receiving response...")
                                first_token = False
                            parts.append(delta)
                            self.signals.delta.emit(self.session_id, delta)
                    except Exception:
                        continue

            full_reply = "".join(parts).strip()
            if self.stop_requested:
                if not full_reply:
                    full_reply = "*(stopped immediately before generating)*"
            elif not full_reply:
                # A 200 response with an empty stream is a dropped connection,
                # not a reply. Surface it as an error so the UI shows the
                # friendly "check your internet / API key" card instead of
                # "Cel replied!".
                self.signals.error.emit(
                    self.session_id,
                    "Connection Failed",
                    "No response received from the model. The connection may have dropped.",
                )
                return

            think_time = round(time.time() - start_t, 2)
            from cellium.core.utils import estimate_accurate_tokens
            tokens = estimate_accurate_tokens(full_reply)
            self.signals.done.emit(self.session_id, full_reply, tokens, think_time, self.stop_requested)
        except Exception as e:
            self.signals.error.emit(self.session_id, "Generation Error", str(e)[:300])

# ------------------------------------------------------------------ Dedicated Glass Panel
class ModelPingWorker(QThread):
    ping_result = Signal(str, str, bool, str)  # model_key, status_text, is_ok, latency

    def __init__(self, models_dict, settings, parent=None):
        super().__init__(parent)
        self.models_dict = dict(models_dict)
        self.settings = dict(settings)

    def run(self):
        keys = self.settings.get("user_custom_keys", {})
        for m_name, m_route in self.models_dict.items():
            if is_offline_model_key(m_name, m_route):
                self.ping_result.emit(m_name, "Local GGUF Ready", True, "0ms")
                continue
            if not isinstance(m_route, dict):
                continue
            prov = m_route.get("provider", "")
            base_url = m_route.get("base_url", "")
            model_id = m_route.get("model", "")
            api_key = keys.get(prov, "")
            if prov == "GitHub Copilot":
                _gh = (api_key or "").strip() or os.environ.get("CELSTUDIO_GITHUB_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
                if _gh:
                    self.ping_result.emit(m_name, "Ready - key set", True, "")
                    continue
            if not api_key:
                self.ping_result.emit(m_name, "No Key Provided", False, "")
                continue

            endpoint = base_url.rstrip("/") + "/chat/completions"
            payload = json.dumps({
                "model": model_id,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1
            }).encode("utf-8")
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "CelStudio/1.0"
            }
            req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
            t0 = time.time()
            net_timeout = get_network_timeout(self.settings)
            try:
                with urllib.request.urlopen(req, timeout=net_timeout) as resp:
                    lat = int((time.time() - t0) * 1000)
                    self.ping_result.emit(m_name, f"HTTP {resp.status} OK", True, f"{lat}ms")
            except urllib.error.HTTPError as e:
                lat = int((time.time() - t0) * 1000)
                msg = f"HTTP {e.code} ({e.reason})"
                self.ping_result.emit(m_name, msg, False, f"{lat}ms")
            except Exception as e:
                self.ping_result.emit(m_name, f"Err: {str(e)[:120]}", False, "")


class ModelFetchWorker(QThread):
    fetched = Signal(str, list)  # provider, model_list
    error = Signal(str, str)     # provider, error_message

    def __init__(self, provider, base_url, api_key, parent=None, settings=None):
        super().__init__(parent)
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.settings = dict(settings) if settings else {}

    def run(self):
        import urllib.request, json
        if not self.api_key and self.provider != "Cerebras":
            self.error.emit(self.provider, "No API key configured for this provider.")
            return

        # GitHub Copilot: exchange token & query live /models catalog + COPILOT_MODELS
        if self.provider == "GitHub Copilot":
            from cellium.core.utils import (
                COPILOT_MODELS, copilot_github_token, copilot_headers, exchange_copilot_token,
            )
            _gh = (self.api_key or "").strip() or copilot_github_token(self.settings)
            if not _gh:
                self.error.emit(self.provider, "No GitHub Copilot token found.")
                return
            discovered = []
            try:
                bearer, _exp = exchange_copilot_token(_gh)
                if bearer:
                    r = requests.get(
                        "https://api.githubcopilot.com/models",
                        headers=copilot_headers(bearer),
                        timeout=12,
                    )
                    if r.status_code == 200:
                        body = r.json() if hasattr(r, "json") else {}
                        for item in (body.get("data") or body.get("models") or []):
                            if isinstance(item, dict) and item.get("id"):
                                mid = str(item["id"]).strip()
                                if not any(b in mid.lower() for b in ("embed", "moderation")):
                                    discovered.append(mid)
            except Exception:
                pass
            merged = list(dict.fromkeys(discovered + list(COPILOT_MODELS)))
            self.fetched.emit(self.provider, merged)
            return

        # Google Gemini - uses x-goog-api-key header, not Bearer
        if self.provider == "Google Gemini":
            endpoint = "https://generativelanguage.googleapis.com/v1beta/models"
            headers = {
                "x-goog-api-key": self.api_key,
                "User-Agent": "CelStudio/1.0"
            }
        # Cerebras has a public models endpoint (no auth needed!)
        elif self.provider == "Cerebras":
            endpoint = "https://api.cerebras.ai/public/v1/models"
            headers = {"User-Agent": "CelStudio/1.0"}
        else:
            # OpenAI-compatible providers (Groq, OpenRouter, DeepSeek, Mistral, etc.)
            endpoint = f"{self.base_url}/models"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "CelStudio/1.0"
            }

        req = urllib.request.Request(endpoint, headers=headers, method="GET")
        try:
            net_timeout = get_network_timeout(self.settings)
            with urllib.request.urlopen(req, timeout=net_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_models = []

                if self.provider == "Google Gemini":
                    # Gemini returns models in "models" array with "name" field
                    if "models" in data and isinstance(data["models"], list):
                        raw_models = [
                            item.get("name", "").replace("models/", "")
                            for item in data["models"]
                            if isinstance(item, dict) and item.get("name")
                        ]
                else:
                    # OpenAI-compatible format (data array or models array)
                    if "data" in data and isinstance(data["data"], list):
                        raw_models = [item.get("id", "") for item in data["data"] if isinstance(item, dict) and item.get("id")]
                    elif "models" in data and isinstance(data["models"], list):
                        raw_models = [item.get("id", "") or item.get("name", "") for item in data["models"] if isinstance(item, dict)]

                # Filter down to conversational / chat / text models
                clean_models = []
                for m in raw_models:
                    m_str = str(m).replace("models/", "")
                    m_lower = m_str.lower()
                    # Skip embedding, whisper, tts, moderations, audio, image gen
                    if any(bad in m_lower for bad in ["embed", "whisper", "tts", "moderation", "babbage", "davinci", "curie", "audio", "dall-e", "text-embedding", "imagen", "veo"]):
                        continue
                    # For Gemini, only keep gemini models
                    if self.provider == "Google Gemini" and "gemini" not in m_lower:
                        continue
                    clean_models.append(m_str)

                clean_models = sorted(list(dict.fromkeys(clean_models)))
                if not clean_models:
                    clean_models = raw_models[:25]
                self.fetched.emit(self.provider, clean_models)
        except urllib.error.HTTPError as e:
            self.error.emit(self.provider, f"HTTP {e.code}: {e.reason}")
        except Exception as e:
            self.error.emit(self.provider, f"{type(e).__name__}: {str(e)[:100]}")


class ModelDetailWorker(QThread):
    """Fetch model details including supported thinking levels."""
    details_fetched = Signal(str, dict)  # model_id, details dict
    error = Signal(str, str)

    def __init__(self, provider, base_url, api_key, model_id, parent=None, settings=None):
        super().__init__(parent)
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_id = model_id
        self.settings = dict(settings) if settings else {}

    def run(self):
        import urllib.request, json
        if not self.api_key and self.provider != "Cerebras":
            self.error.emit(self.model_id, "No API key configured.")
            return

        # Try to fetch model details from /models/{model_id} endpoint
        if self.provider == "Google Gemini":
            # Gemini doesn't have a standard details endpoint
            self.details_fetched.emit(self.model_id, self._infer_gemini_details())
            return
        elif self.provider == "GitHub Copilot":
            # No details endpoint; Copilot takes no reasoning_effort either.
            self.details_fetched.emit(self.model_id, {"thinking_levels": ["low", "medium", "high"]})
            return
        elif self.provider == "Cerebras":
            endpoint = f"https://api.cerebras.ai/public/v1/models/{urllib.parse.quote(self.model_id)}"
            headers = {"User-Agent": "CelStudio/1.0"}
        else:
            endpoint = f"{self.base_url}/models/{urllib.parse.quote(self.model_id)}"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "CelStudio/1.0"
            }

        req = urllib.request.Request(endpoint, headers=headers, method="GET")
        try:
            net_timeout = get_network_timeout(self.settings)
            with urllib.request.urlopen(req, timeout=net_timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                # Extract thinking/reasoning levels from response
                details = self._parse_details(data)
                self.details_fetched.emit(self.model_id, details)
        except urllib.error.HTTPError as e:
            # Fallback to known mappings if 404
            if e.code == 404:
                details = self._get_known_details()
                self.details_fetched.emit(self.model_id, details)
            else:
                self.error.emit(self.model_id, f"HTTP {e.code}: {e.reason}")
        except Exception as e:
            details = self._get_known_details()
            self.details_fetched.emit(self.model_id, details)

    def _parse_details(self, data):
        """Extract thinking levels and input/output modalities from the
        provider catalog response. OpenRouter-style architecture.input_modalities
        is the authoritative signal for what a model can actually support."""
        details = {"thinking_levels": ["low", "medium", "high"], "modalities": []}
        
        if isinstance(data, dict):
            # OpenRouter / unified catalog: architecture.modalities
            arch = data.get("architecture")
            if isinstance(arch, dict):
                for key in ("input_modalities", "output_modalities", "modalities"):
                    val = arch.get(key)
                    if isinstance(val, list):
                        details["modalities"].extend(str(m).lower() for m in val)
            # Flat modality fields some providers use.
            for key in ("modalities", "input_modalities", "output_modalities"):
                val = data.get(key)
                if isinstance(val, list):
                    details["modalities"].extend(str(m).lower() for m in val)
            details["modalities"] = list(dict.fromkeys(details["modalities"]))

            # OpenAI-style: capabilities.reasoning_effort or supported_parameters
            if "capabilities" in data and isinstance(data["capabilities"], dict):
                caps = data["capabilities"]
                if "reasoning_effort" in caps:
                    efforts = caps["reasoning_effort"]
                    if isinstance(efforts, list):
                        details["thinking_levels"] = efforts
            
            # Some providers use "supported_parameters" 
            if "supported_parameters" in data and isinstance(data["supported_parameters"], dict):
                params = data["supported_parameters"]
                if "reasoning_effort" in params:
                    efforts = params["reasoning_effort"]
                    if isinstance(efforts, dict) and "enum" in efforts:
                        details["thinking_levels"] = efforts["enum"]
            
            # Check for "thinking" or "reasoning" fields
            for key in ["thinking", "reasoning", "reasoning_effort", "effort"]:
                if key in data and isinstance(data[key], list):
                    details["thinking_levels"] = data[key]
        
        return details

    def _infer_gemini_details(self):
        """Infer thinking levels for Gemini models based on model name."""
        name = self.model_id.lower()
        if "2.5" in name or "2.0" in name or "flash-thinking" in name:
            return {"thinking_levels": ["minimal", "low", "medium", "high", "max"]}
        elif "1.5" in name:
            return {"thinking_levels": ["low", "medium", "high"]}
        return {"thinking_levels": ["low", "medium", "high"]}

    def _get_known_details(self):
        """Return known thinking levels for popular models."""
        name = self.model_id.lower()
        # OpenAI o1 series
        if "o1" in name:
            if "mini" in name:
                return {"thinking_levels": ["low", "medium", "high"]}
            return {"thinking_levels": ["low", "medium", "high"]}
        # OpenAI o3 series
        if "o3" in name:
            return {"thinking_levels": ["low", "medium", "high"]}
        # DeepSeek R1
        if "deepseek" in name and "r1" in name:
            return {"thinking_levels": ["low", "medium", "high", "max"]}
        # Groq models with reasoning
        if "groq" in self.provider.lower() or "llama" in name:
            return {"thinking_levels": ["low", "medium", "high"]}
        # Cerebras
        if "cerebras" in self.provider.lower():
            return {"thinking_levels": ["low", "medium", "high"]}
        return {"thinking_levels": ["low", "medium", "high"]}


# ============================================================
# AGENT FRAMEWORK - Tool Calling & Autonomous Capabilities
# ============================================================
# ── Bug 19: agent stream marker shield ───────────────────────────────────────
# Machine-only control tokens. A streaming chunk boundary can land mid-marker
# ("TOOL" then "_CALL:"), which used to leak the bare "TOOL" into the bubble.
_AGENT_STREAM_MARKER_RE = re.compile(
    r"(?:TOOL_CALL|TOOLCALL|\[TOOL_CALL\]|\[TOOLCALL\]|¼)", re.IGNORECASE)
_AGENT_STREAM_MARKERS = ("tool_call:", "toolcall:", "[tool_call]", "[toolcall]", "¼")


def _agent_safe_cut(text: str) -> int:
    """Length of the prefix of *text* that can never grow into a marker."""
    end = len(text)
    low = text.lower()
    for mk in _AGENT_STREAM_MARKERS:
        for n in range(min(len(mk) - 1, 11), 0, -1):
            if low.endswith(mk[:n]):
                return min(end, len(low) - n)
    return end


class AgentSignals(QObject):
    delta = Signal(str, str)             # sid, token
    done = Signal(str, str, int, float, bool)  # sid, reply, tokens, think_time, stopped
    error = Signal(str, str, str)        # sid, title, desc
    status = Signal(str)                 # status message
    tool_call = Signal(str, dict)        # tool_name, arguments
    tool_result = Signal(str, str)       # tool_name, result
    tool_diff = Signal(str, str)         # path, unified_diff


class AgentWorker(QThread):
    """Worker that handles agent-style tool calling loop with full compatibility."""
    def __init__(self, session_id, messages, settings, models, providers, dev_memory, tools_enabled=True, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.messages = messages
        self.settings = settings
        self.models = models
        self.providers = providers
        self.dev_memory = dev_memory
        self.tools_enabled = tools_enabled
        self.tools = self._init_tools()
        self.max_tool_rounds = 10
        self._stop_event = threading.Event()
        self._action_history = []  # Circuit breaker tracking
        self._successful_calls = {}  # exact (tool,args) → successful result
        self._force_finish = False   # set when a successful call is repeated
        self.signals = AgentSignals()

        # Direct signal aliases bound at initialization
        self.delta = self.signals.delta
        self.done = self.signals.done
        self.error = self.signals.error
        self.status = self.signals.status
        self.tool_call = self.signals.tool_call
        self.tool_result = self.signals.tool_result
        self.tool_diff = self.signals.tool_diff

    def _emit_status(self, msg: str):
        self.signals.status.emit(msg)

    @property
    def stop_requested(self):
        return self._stop_event.is_set()

    @stop_requested.setter
    def stop_requested(self, val):
        if val:
            self._stop_event.set()
        else:
            self._stop_event.clear()
    
    def _init_tools(self):
        """Initialize available tools."""
        tools = {
            "file_read": FileReadTool(),
            "file_write": FileWriteTool(),
            "replace_file_content": ReplaceFileContentTool(),
            "grep_search": GrepSearchTool(),
            "file_list": FileListTool(),
            "code_exec": CodeExecTool(),
            "web_search": WebSearchTool(),
            "shell_exec": ShellExecTool(),
            "batch_exec": BatchExecTool(),
        }
        # 🎨 Image Gen tool - only exposed when the user enabled it, so the
        # prompt context stays small otherwise.
        if self.settings.get("image_gen_enabled", False):
            try:
                from cellium.services.image_tool import get_hub
                tools["generate_image"] = get_hub().make_tool()
            except Exception as e:
                dev_log(f"[AgentWorker] generate_image tool unavailable: {e}")
        return tools

    @staticmethod
    def _has_complete_tool_call(text: str) -> tuple[bool, int]:
        """Return (True, end_pos) the instant a TOOL_CALL JSON or <tool_call> closes.

        Cutting the generation stream at `end_pos` makes it physically
        impossible for an LLM to hallucinate fake output after a command!
        """
        if not text:
            return False, -1
        for m in re.finditer(r"(?:TOOL_CALL|TOOLCALL|\[TOOL_CALL\]|\[TOOLCALL\])\s*:", text, re.IGNORECASE):
            json_str, _s, e_idx = extract_balanced_json(text, m.end())
            if json_str and e_idx > 0:
                try:
                    parsed = json.loads(json_str.strip())
                    if isinstance(parsed, dict) and ("name" in parsed or "tool" in parsed):
                        return True, e_idx
                except Exception:
                    pass
        tc_xml = re.search(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, re.DOTALL | re.IGNORECASE)
        if tc_xml:
            return True, tc_xml.end()
        return False, -1

    _MARKER_RE = re.compile(
        r"(?:TOOL_CALL|TOOLCALL|\[TOOL_CALL\]|\[TOOLCALL\]|<tool_call>)",
        re.IGNORECASE)

    @staticmethod
    def _marker_hold_len(text: str) -> int:
        """Longest suffix of `text` that could still become a control marker."""
        u = text.upper()
        best = 0
        for p in ("TOOL_CALL", "TOOLCALL", "[TOOL_CALL]", "[TOOLCALL]", "<TOOL_CALL>"):
            for k in range(1, min(len(p), len(u)) + 1):
                if p.startswith(u[-k:]) and k > best:
                    best = k
        return best

    def _emit_filtered_delta(self, prev_acc: str, chunk: str) -> None:
        """Stream prose to the UI while never leaking control markers.

        The old whole-chunk drop let `"TOO"`, `"L_CALL"` (and a bare `"TOOL"`
        glued to the next sentence) through when a marker was split across SSE
        chunks. We now emit up to a safe point and hold back any tail that
        could still grow into a marker.
        """
        if not chunk:
            return
        combined = prev_acc + chunk
        m = self._MARKER_RE.search(combined)
        cutoff = m.start() if m else len(combined)
        hold = 0 if m else self._marker_hold_len(combined[:cutoff])
        safe_end = max(0, cutoff - hold)
        start = int(getattr(self, "_stream_emitted", 0) or 0)
        # A stray "TOOL" token that resolved into ordinary prose is still junk.
        if combined[start:start + 4].upper() == "TOOL":
            prev_ch = combined[start - 1] if start > 0 else ""
            if start == 0 or prev_ch.isspace() or prev_ch in ">])":
                start += 4
        if safe_end > start:
            self.signals.delta.emit(self.session_id, combined[start:safe_end])
            self._stream_emitted = safe_end
        if m:
            # Marker reached - nothing after it may ever be shown this round.
            self._stream_emitted = len(combined)
    
    def get_tool_schemas(self):
        """Get OpenAI-compatible tool schemas."""
        return [
            {"type": "function", "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters
            }}
            for t in self.tools.values()
        ]
    
    def request_stop(self):
        self.stop_requested = True
        try:
            request_llama_abort()
        except Exception:
            pass
        resp = getattr(self, "_active_resp", None)
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass
        try:
            kill_active_subprocesses()
        except Exception:
            pass
    
    def run(self):
        """Guarantee a terminal signal and release any C++ GGUF handle on exit."""
        begin_llama_use()
        try:
            self._run_impl()
        except Exception as exc:
            try:
                self.signals.error.emit(
                    self.session_id,
                    "Agent crashed",
                    f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass
        finally:
            self._offline_llm = None
            # Only now may the UI close the native llama context.
            end_llama_use()

    def _run_impl(self):
        import urllib.request, json, time
        self._start_t = time.time()
        self._stream_emitted = 0   # Bug 19: marker-shield state, per agent run
        self._successful_calls = {}   # exact call → result (loop guard)
        self._force_finish = False    # duplicate success → stop the agent loop

        if not self.tools_enabled:
            self._regular_generation()
            return
        
        # Build system prompt with tool instructions
        tool_descriptions = "\n".join([
            f"- {t.name}: {t.description}"
            for t in self.tools.values()
        ])
        
        # Ground the agent in the actual environment to prevent hallucinated paths
        cwd = os.getcwd()
        home_dir = os.path.expanduser('~')
        try:
            os_info = f"{sys.platform} ({os.uname().release})"
        except Exception:
            os_info = sys.platform

        # self.messages already includes system prompt from session memory
        # Add minimal agent instructions as a developer note
        model_key = self.settings.get("selected_model", "")
        route = self.models.get(model_key)
        offline_path = resolve_offline_model_path(model_key, self.settings, self.models)
        is_offline = bool(offline_path)
        
        from cellium.core.utils import thinking_level_key, THINKING_FORCE_OFF_DIRECTIVE
        _think_level = thinking_level_key(self.settings.get("thinking_level", "auto"))
        _force_off = (_think_level == "force_off")
        _thinking_off = _think_level in ("off", "default", "none", "force_off", "")
        if _thinking_off:
            _think_instr = (
                "STRICT AGENT EXECUTION PROTOCOL ([RUN TOOL -> RUN TOOL] -> [SPEAK]):\n"
                "1. When a task requires inspecting files, searching, or running commands, DO NOT speak to the user yet and DO NOT write commands in markdown ``` code blocks.\n"
                "2. Immediately output ONLY:\n"
                "   TOOL_CALL: {\"name\": \"tool_name\", \"arguments\": {...}}\n"
                "3. STOP immediately after `TOOL_CALL: {...}`. NEVER guess, fabricate, or roleplay command outputs or file paths - wait for the real [Tool Result].\n"
                "4. Repeat [ TOOL_CALL: {...} ] across rounds until you have all real facts, or batch multiple commands at once with `batch_exec` / `shell_exec(commands=[...])`.\n"
                "5. Only AFTER all tool calls finish, speak directly to user with the real answer. Do NOT explain your code or commands unless user explicitly asks.\n"
                "Do NOT emit <think> blocks, mood: tags, or any reasoning prose."
            )
        else:
            _think_instr = (
                "STRICT AGENT EXECUTION PROTOCOL ([THINK -> RUN TOOL -> THINK -> RUN TOOL] -> [SPEAK]):\n"
                "1. When a task requires inspecting files, searching, or running commands, DO NOT speak to the user yet and DO NOT write commands in markdown ``` code blocks.\n"
                "2. Instead, plan briefly inside <think>...</think> and immediately output ONLY:\n"
                "   TOOL_CALL: {\"name\": \"tool_name\", \"arguments\": {...}}\n"
                "3. STOP immediately after `TOOL_CALL: {...}`. NEVER guess, fabricate, or roleplay command outputs or file paths - wait for the real [Tool Result].\n"
                "4. Repeat [ <think>...</think> + TOOL_CALL: {...} ] across rounds until you have all real facts, or batch multiple commands at once with `batch_exec` / `shell_exec(commands=[...])`.\n"
                "5. Only AFTER all tool calls finish, speak directly to user with the real answer. Do NOT explain your code or commands unless user explicitly asks."
            )
        agent_instruction = (
            f"You are Cel, an elite autonomous agent working with user.\n"
            f"ENV: cwd={cwd} | home={home_dir} | os={os_info} | python={sys.executable}\n\n"
            f"AVAILABLE TOOLS:\n{tool_descriptions}\n"
            f"- shell_exec supports single `command` OR batch `commands`: [\"cmd1\", \"cmd2\"]\n"
            f"- batch_exec runs an ordered list of `commands`: [\"cmd1\", \"cmd2\"] in one shot\n"
            f"- generate_image: Generates or edits images on Kaggle GPU. CRITICAL: When the user asks to draw, generate, or create an image, you MUST output a tool call: `TOOL_CALL: {{\"name\": \"generate_image\", \"arguments\": {{\"prompt\": \"...\"}}}}`. NEVER fake, hallucinate, or pretend you generated an image in text (NEVER write '🎨 Generated: ... Seed: ...' yourself). Always call the real tool!\n\n"
            f"{_think_instr}"
            "\nCRITICAL: think:, TOOL_CALL: and mood: are MACHINE CONTROL TOKENS. "
            "Never echo, imitate or quote them in your visible text."
        )
        if _force_off:
            agent_instruction += THINKING_FORCE_OFF_DIRECTIVE
        
        # Insert agent instruction as a developer message after system prompt
        want_mood = bool(self.settings.get("_mood_contract_active", False)) and not _thinking_off
        messages = []
        for _m in self.messages:
            _mc = dict(_m)
            if _mc.get("role") == "system" and not want_mood:
                # Strip the live-only mood contract; inject nothing in its
                # place (the old negative instruction was pure token waste).
                _mc["content"] = re.sub(
                    r"\n*\[MOOD CONTRACT:.*?\]", "",
                    _mc.get("content", ""), flags=re.DOTALL)
                _mc["content"] = re.sub(
                    r"\n*\[IMPORTANT: Do NOT start your reply with `mood:`"
                    r" or any emotion tag\.\]", "", _mc["content"])
            messages.append(_mc)
        
        # CRITICAL: Remove trailing empty assistant messages - API requires conversation to end with user turn
        while messages and messages[-1]["role"] == "assistant" and not messages[-1]["content"].strip():
            messages.pop()
        
        last_user_txt = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        if isinstance(last_user_txt, list):
            last_user_txt = " ".join(x.get("text", "") for x in last_user_txt if isinstance(x, dict))
        if self._is_casual_opener(str(last_user_txt)):
            # Screenshot fix: user just said e.g. "hehe, I want you to help with something"  - 
            # reply conversationally without advertising or triggering tools on this turn!
            self.tools_enabled = False
        else:
            sys_idx = next((i for i, m in enumerate(messages) if m.get("role") == "system"), 0)
            messages.insert(sys_idx + 1, {"role": "system", "content": agent_instruction})
        
        # ─── OFFLINE GGUF DETECTION (with graceful fallback) ─────────────────────────────────────────────────────
        if not offline_path:
            if isinstance(route, dict):
                target_server = route.get("provider", "Cerebras")
            else:
                target_server = self.settings.get("selected_provider", "Cerebras")
            custom_keys = self.settings.get("user_custom_keys", {})
            api_key = custom_keys.get(target_server, "")
            if not api_key:
                provider_data = self.providers.get(target_server, {})
                keys = provider_data.get("keys", [])
                if keys:
                    api_key = keys[0]
            if not api_key:
                fallback_gguf = resolve_any_offline_path(self.settings)
                if fallback_gguf:
                    offline_path = fallback_gguf
                    self.signals.status.emit("🔑 No API key - chatting on local GGUF instead 💾")

        if offline_path:
            self._run_agent_offline(messages, model_key)
            return
        if isinstance(route, dict):
            provider = route.get("provider", "Cerebras")
            model = route.get("model", model_key)
            base_url = route.get("base_url", "")
        else:
            provider = self.settings.get("selected_provider", "Cerebras")
            model = model_key
            base_url = ""

        api_key = self.settings.get("user_custom_keys", {}).get(provider, "")
        if not api_key:
            provider_data = self.providers.get(provider, {})
            keys = provider_data.get("keys", [])
            if keys:
                api_key = keys[0]
        if not api_key and provider == "GitHub Copilot":
            api_key = os.environ.get("CELSTUDIO_GITHUB_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")

        if not base_url:
            cfg = PROVIDER_DEFS.get(provider, PROVIDER_DEFS.get("Cerebras", {}))
            base_url = self.settings.get("custom_provider_urls", {}).get(provider, cfg.get("base_url", ""))
        
# Store for _make_final_summary_call
        self._online_ctx = {"model": model, "provider": provider, "base_url": base_url, "api_key": api_key}

        # Missing API key → offline fallback (already handled above for offline_path, but double-check)
        if not api_key:
            fallback_gguf = resolve_any_offline_path(self.settings)
            if fallback_gguf:
                self.signals.status.emit("🔑 No API key - chatting on local GGUF instead 💾")
                self._run_agent_offline(messages, model_key)
                return
            self.signals.error.emit(self.session_id, "API Key Required", f"No API key configured for {provider} and no offline GGUF available.")
            return

        if provider == "GitHub Copilot":
            # Exchange once per turn; ctx + both header sites reuse the minted token.
            api_key = _copilot_bearer(self.settings)
            if not api_key:
                self.signals.error.emit(self.session_id, "Copilot Token", "Could not mint a Copilot token. Paste a GitHub token in Model Hub → GitHub Copilot (or set CELSTUDIO_GITHUB_TOKEN).")
                return
            try:
                self._online_ctx["api_key"] = api_key
            except Exception:
                pass

        round_count = 0
        final_response = ""
        
        while round_count < self.max_tool_rounds and not self.stop_requested:
            round_count += 1
            self.signals.status.emit("🤖 Agent thinking...")
            self._stream_emitted = 0   # Bug 19: new stream round → fresh shield window
            
            # Prepare request
            out_max = get_output_max_tokens(self.settings)
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": out_max,
                "stream": True
            }
            
            # Gemini /openai endpoint doesn't reliably support OpenAI-style structured tools
            # Use text-based tool calling (TOOL_CALL: format) instead which works perfectly
            use_structured_tools = self.tools_enabled and provider not in ("Google Gemini", "GitHub Copilot")
            
            # Sanitize messages for providers that don't support structured tool protocol
            # This prevents Gemini from choking on tool_calls/tool role from previous rounds
            if not use_structured_tools:
                sanitized = []
                for m in messages:
                    clean_m = {"role": m["role"], "content": m.get("content", "")}
                    if clean_m["role"] == "tool":
                        # Convert tool results to user messages
                        clean_m["role"] = "user"
                        clean_m["content"] = f"[Tool Result]: {clean_m['content']}"
                    # Strip tool_calls key entirely (Gemini doesn't understand it)
                    sanitized.append(clean_m)
                if any(m.get("role") == "tool" for m in messages):
                    sanitized.append({
                        "role": "user",
                        "content": (
                            "[System note]: Every tool call above has already run. "
                            "If it succeeded, do NOT repeat it - reply to the user "
                            "with the final result now."
                        ),
                    })
                send_messages = sanitized
            else:
                send_messages = messages
            
            # Prepare request
            out_max = get_output_max_tokens(self.settings)
            payload = {
                "model": model,
                "messages": send_messages,
                "temperature": 0.7,
                "max_tokens": out_max,
                "stream": True
            }
            
            if use_structured_tools:
                payload["tools"] = self.get_tool_schemas()
                payload["tool_choice"] = "auto"
            
            # Determine headers and endpoint
            if provider == "Google Gemini":
                if not base_url or "generativelanguage" not in base_url:
                    base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
                endpoint = f"{base_url.rstrip('/')}/chat/completions"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "CelStudio/1.0"
                }
            else:
                endpoint = f"{base_url.rstrip('/')}/chat/completions"
                if provider == "GitHub Copilot":
                    from cellium.core.utils import copilot_headers
                    headers = copilot_headers(api_key)
                else:
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "CelStudio/1.0"
                    }
            
            # Streaming request with automatic fallback to text-based tool calling
            
            net_timeout = get_network_timeout(self.settings)
            net_retries = get_network_max_retries(self.settings)
            
            def _robust_urlopen(request_obj, timeout_val=net_timeout, max_retries=net_retries):
                last_err = None
                for attempt in range(max_retries):
                    if self.stop_requested:
                        raise Exception("Stopped by user")
                    try:
                        if attempt > 0:
                            self.signals.status.emit(f"📡 Network dropped! Retrying ({attempt}/{max_retries})...")
                            time.sleep(2.0)
                        return urllib.request.urlopen(request_obj, timeout=timeout_val)
                    except urllib.error.HTTPError as he:
                        if he.code in (408, 429, 500, 502, 503, 504):
                            last_err = he
                            continue
                        raise he # Bubble up 400/401/403/422 as fatal to trigger fallback
                    except urllib.error.URLError as ue:
                        last_err = ue
                        continue
                    except Exception as e:
                        last_err = e
                        continue
                raise last_err

            req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
            
            try:
                accumulated = ""
                tool_calls = []
                
                try:
                    resp = _robust_urlopen(req, timeout_val=net_timeout)
                except urllib.error.HTTPError as he:
                    # Read error response body for debugging
                    error_body = ""
                    try:
                        error_body = he.read().decode('utf-8')
                    except Exception:
                        pass
                    
                    # If endpoint returns 400/422 because it does not support structured `tools`, retry without `tools` parameter
                    if (he.code in (400, 422)) and use_structured_tools:
                        dev_log(f"[AgentWorker] Tools not supported (HTTP {he.code}), retrying without tools. Error: {error_body[:200]}")
                        del payload["tools"]
                        if "tool_choice" in payload:
                            del payload["tool_choice"]
                        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
                        try:
                            resp = _robust_urlopen(req, timeout_val=net_timeout)
                        except urllib.error.HTTPError as he2:
                            error_body2 = ""
                            try:
                                error_body2 = he2.read().decode('utf-8')
                            except Exception:
                                pass
                            raise Exception(f"HTTP {he2.code}: {he2.reason} - {error_body2[:300]}")
                    else:
                        # Include status code and body in exception for fallback detection
                        raise Exception(f"HTTP {he.code}: {he.reason} - {error_body[:300]}")
                
                self._active_resp = resp
                with resp:
                    for line in resp:
                        if self.stop_requested:
                            break
                        line = line.decode('utf-8').strip()
                        if not line or line == "data: [DONE]":
                            continue
                        if line.startswith("data: "):
                            line = line[6:]
                        
                        try:
                            data = json.loads(line)
                            
                            # Support OpenAI-compatible format (used by Cerebras, OpenRouter, Groq, and Gemini /openai endpoint)
                            if "choices" in data and data["choices"]:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta and delta["content"]:
                                    text = delta["content"]
                                    prev_acc = accumulated
                                    accumulated += text
                                    self._emit_filtered_delta(prev_acc, text)
                                if "tool_calls" in delta:
                                    for tc in delta["tool_calls"]:
                                        tc_idx = tc.get("index", len(tool_calls))
                                        while len(tool_calls) <= tc_idx:
                                            tool_calls.append({"name": "", "arguments": ""})
                                        if "function" in tc:
                                            if "name" in tc["function"] and tc["function"]["name"]:
                                                tool_calls[tc_idx]["name"] = tc["function"]["name"]
                                            if "arguments" in tc["function"] and tc["function"]["arguments"]:
                                                tool_calls[tc_idx]["arguments"] += tc["function"]["arguments"]
                            elif "candidates" in data and data["candidates"]:
                                # Fallback for native Gemini candidates format
                                cand = data["candidates"][0]
                                if "content" in cand and "parts" in cand["content"]:
                                    for part in cand["content"]["parts"]:
                                        if "text" in part:
                                            text = part["text"]
                                            prev_acc_gem = accumulated
                                            accumulated += text
                                            self._emit_filtered_delta(prev_acc_gem, text)
                                        if "functionCall" in part:
                                            fc = part["functionCall"]
                                            tool_calls.append({
                                                "name": fc.get("name", ""),
                                                "arguments": fc.get("args", {})
                                            })
                        
                        except json.JSONDecodeError:
                            continue
                        has_tc, tc_end = self._has_complete_tool_call(accumulated)
                        if has_tc:
                            accumulated = accumulated[:tc_end]
                            try:
                                resp.close()
                            except Exception:
                                pass
                            break
                
                # Parse text-based + execute tools (shared logic)
                tool_calls = self._parse_text_tool_calls(accumulated, tool_calls)
                result = self._execute_and_loop(accumulated, tool_calls, messages)
                if result == "__CONTINUE__":
                    final_response = accumulated.strip()
                    if getattr(self, "_force_finish", False):
                        break   # duplicate successful tool call - summarize now
                    continue
                final_response = result
                break
                    
            except Exception as e:
                self.signals.error.emit(self.session_id, "Agent Execution Error", str(e))
                return
        
        self._emit_final(final_response, messages)
    
# ── OFFLINE GGUF AGENT PATH ─────────────────────────────────────
    def _run_agent_offline(self, messages, model_key):
        """Run agent loop using local GGUF model via llama-cpp-python."""
        # Resolve offline model path using shared helper (with fallback to any available GGUF)
        local_path = resolve_offline_model_path(model_key, self.settings, self.models) or resolve_any_offline_path(self.settings)

        if not local_path or not os.path.exists(local_path):
            self.signals.error.emit(self.session_id, "No Offline Model",
                f"Local GGUF model path not found for '{model_key or 'local_model_path'}'. Please configure in Model Hub.")
            return
        
        # Load offline settings
        n_ctx = int(self.settings.get("offline_n_ctx", 2048))
        n_threads = int(self.settings.get("offline_threads", max(1, (os.cpu_count() or 4) // 2)))
        n_gpu_layers = int(self.settings.get("offline_gpu_layers", 0))
        temp = float(self.settings.get("offline_temperature", 0.7))
        top_p = float(self.settings.get("offline_top_p", 0.9))
        rep_pen = float(self.settings.get("offline_repeat_penalty", 1.1))
        type_k = self.settings.get("offline_kv_cache_type_k", "f16")
        type_v = self.settings.get("offline_kv_cache_type_v", "f16")
        flash_attn = self.settings.get("offline_flash_attn", False)
        cache_prompt = self.settings.get("offline_cache_prompt", False)
        
        self.signals.status.emit("⏳ Loading GGUF model for Agent Mode...")
        
        try:
            llm = get_or_load_llama(
                model_path=local_path,
                n_ctx=n_ctx,
                n_threads=n_threads,
                n_gpu_layers=n_gpu_layers,
                type_k=type_k,
                type_v=type_v,
                flash_attn=flash_attn,
                cache_prompt=cache_prompt,
                status_cb=self._emit_status,
            )
        except Exception as e:
            self.signals.error.emit(self.session_id, "GGUF Load Error", str(e))
            return
        
        # Store for _make_final_summary_call offline path
        self._online_ctx = None
        self._offline_llm = llm
        self._offline_params = {"temp": temp, "top_p": top_p, "rep_pen": rep_pen, "n_ctx": n_ctx, "type_k": type_k, "type_v": type_v, "flash_attn": flash_attn, "cache_prompt": cache_prompt}
        
        # Flatten multimodal content for offline (GGUF doesn't support vision)
        chat_messages = []
        for m in messages:
            c = m["content"]
            if isinstance(c, list):
                c = " ".join([item.get("text", "") for item in c if item.get("type") == "text"])
            chat_messages.append({"role": m["role"], "content": c})
        
        # Task 24: honor the thinking-level setting on offline models in agent
        # mode too - /no_think + THINKING MODE directives, same as chat worker.
        try:
            from cellium.core.utils import build_offline_thinking_config
            _mname = str(local_path).replace("\\", "/").rsplit("/", 1)[-1]
            _tcfg = build_offline_thinking_config(
                _mname, self.settings.get("thinking_level", "auto"))
            _directive = str(_tcfg.get("directive") or "")
            if _directive:
                _placed = False
                for _m in chat_messages:
                    if _m.get("role") == "system":
                        _m["content"] = _m.get("content", "") + _directive
                        _placed = True
                        break
                if not _placed and chat_messages:
                    chat_messages[0]["content"] = (
                        _directive.strip() + "\n" + chat_messages[0].get("content", ""))
        except Exception:
            pass

        prepare_llama_session(llm, self.session_id)
        if len(chat_messages) > 8:
            sys_m = [m for m in chat_messages[:2] if m.get("role") == "system"]
            rest_m = [m for m in chat_messages if m.get("role") != "system"]
            chat_messages = sys_m + rest_m[-6:]

        round_count = 0
        final_response = ""
        
        while round_count < self.max_tool_rounds and not self.stop_requested:
            round_count += 1
            self.signals.status.emit("🧠 Offline Agent thinking...")
            
# Token budgeting (same as GenerationWorker)
            def _calc_tokens(msgs):
                raw_p = format_offline_prompt(
                    msgs,
                    _resolve_offline_style(self.settings, local_path),
                    local_path)
                try:
                    return len(llm.tokenize(raw_p.encode("utf-8", errors="ignore")))
                except Exception:
                    return max(10, len(raw_p) // 3)
            
            prompt_tokens = _calc_tokens(chat_messages)
            self._stream_emitted = 0   # new streaming round → new emission window

            # Prune old history if context is too tight
            reserve_buffer = max(256, min(512, int(n_ctx * 0.25)))
            if prompt_tokens > n_ctx - reserve_buffer and len(chat_messages) > 2:
                sys_msg = [chat_messages[0]] if chat_messages[0]["role"] == "system" else []
                turns = chat_messages[1:] if sys_msg else chat_messages[:]
                while len(turns) > 1 and prompt_tokens > n_ctx - reserve_buffer:
                    turns.pop(0)
                    prompt_tokens = _calc_tokens(sys_msg + turns)
                chat_messages = sys_msg + turns
            
            available_tokens = max(16, n_ctx - prompt_tokens - 24)
            safe_max_tokens = max(16, min(2048, available_tokens))
            
            try:
                accumulated = ""
                
                # Strip tool_calls and merge system role into first user message
                # This prevents llama-cpp from crashing on non-system GGUF models
                clean_msgs = []
                system_text = ""
                for m in chat_messages:
                    cm = {"role": m["role"], "content": m.get("content", "")}
                    if cm["role"] == "system":
                        system_text += cm["content"] + "\n\n"
                        continue
                    elif cm["role"] == "tool":
                        cm["role"] = "user"
                        cm["content"] = f"[Tool Result]: {cm['content']}"
                    clean_msgs.append(cm)
                
                if system_text:
                    if clean_msgs and clean_msgs[0]["role"] == "user":
                        clean_msgs[0]["content"] = system_text + clean_msgs[0]["content"]
                    else:
                        clean_msgs.insert(0, {"role": "user", "content": system_text.strip()})
                
                res = llm.create_chat_completion(
                    messages=clean_msgs,
                    max_tokens=safe_max_tokens,
                    temperature=temp,
                    top_p=top_p,
                    repeat_penalty=rep_pen,
                    stream=True
                )
                
                generated_count = 0
                for chunk in res:
                    if self.stop_requested:
                        break
                    generated_count += 1
                    if prompt_tokens + generated_count >= n_ctx - 8:
                        dev_log(f"[AgentWorker] Offline hit context ceiling ({prompt_tokens + generated_count}/{n_ctx})")
                        break
                    delta = chunk["choices"][0].get("delta", {})
                    t = delta.get("content", "")
                    if t:
                        prev_acc = accumulated
                        accumulated += t
                        self._emit_filtered_delta(prev_acc, t)
                        has_tc, tc_end = self._has_complete_tool_call(accumulated)
                        if has_tc:
                            accumulated = accumulated[:tc_end]
                            break
                
            except Exception as e:
                self.signals.error.emit(self.session_id, "Offline Agent Error", str(e))
                return
            
            # Parse text-based tool calls + execute (shared logic)
            tool_calls = self._parse_text_tool_calls(accumulated, [])
            result = self._execute_and_loop(accumulated, tool_calls, chat_messages)
            if result == "__CONTINUE__":
                final_response = accumulated.strip()
                if getattr(self, "_force_finish", False):
                    break   # duplicate successful tool call - summarize now
                continue
            final_response = result
            break
        
        self._emit_final(final_response, chat_messages)
    
    # ── SHARED HELPERS ──────────────────────────────────────────────
    def _parse_text_tool_calls(self, accumulated, tool_calls):
        """Parse text-based tool calls from accumulated response text."""
        if not tool_calls:
            for match in re.finditer(r'(?:TOOL_CALL|TOOLCALL|\[TOOL_CALL\]|\[TOOLCALL\])\s*:', accumulated, re.IGNORECASE):
                json_str, _, _ = extract_balanced_json(accumulated, match.end())
                if json_str:
                    try:
                        parsed = json.loads(json_str.strip())
                        if isinstance(parsed, dict) and "name" in parsed:
                            tool_calls.append(parsed)
                    except Exception:
                        pass
            
            if not tool_calls:
                for match in re.finditer(r'```(?:json|tool_call)?\s*(\{)', accumulated, re.IGNORECASE):
                    json_str, _, _ = extract_balanced_json(accumulated, match.start(1))
                    if json_str:
                        try:
                            parsed = json.loads(json_str.strip())
                            if isinstance(parsed, dict) and "name" in parsed:
                                tool_calls.append(parsed)
                        except Exception:
                            pass
        
        # Parse {{ tool_name(...) }} and FILECONTENT: {{ tool_name(...) }} formats
        if not tool_calls:
            # Match FILECONTENT: {{ tool_name(args) }} or just {{ tool_name(args) }}
            for match in re.finditer(r'(?:FILECONTENT|FILE_CONTENT)?\s*:\s*\{\{\s*(\w+)\((.*?)\)\s*\}\}', accumulated, re.DOTALL | re.IGNORECASE):
                tool_name_raw = match.group(1).strip()
                args_str = match.group(2).strip()
                tool_name = self._normalize_tool_name(tool_name_raw)
                args = self._parse_function_args(args_str, tool_name)
                if args is not None:
                    tool_calls.append({"name": tool_name, "arguments": args})
        
        # Parse simple {{ tool_name(args) }} without FILECONTENT
        if not tool_calls:
            for match in re.finditer(r'\{\{\s*(\w+)\((.*?)\)\s*\}\}', accumulated, re.DOTALL | re.IGNORECASE):
                tool_name_raw = match.group(1).strip()
                args_str = match.group(2).strip()
                tool_name = self._normalize_tool_name(tool_name_raw)
                args = self._parse_function_args(args_str, tool_name)
                if args is not None:
                    tool_calls.append({"name": tool_name, "arguments": args})

        if not tool_calls:
            for match in re.finditer(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", accumulated, re.DOTALL | re.IGNORECASE):
                try:
                    parsed = json.loads(match.group(1).strip())
                    if isinstance(parsed, dict) and ("name" in parsed or "tool" in parsed):
                        if "tool" in parsed and "name" not in parsed:
                            parsed["name"] = parsed.pop("tool")
                        tool_calls.append(parsed)
                except Exception:
                    pass

        if not tool_calls:
            # Catch ```bash / ```sh / ```exec OR unlabeled ``` blocks that start with a shell command
            # when the model forgot TOOL_CALL: syntax (like in Bug #7.5)!
            shell_starts = (
                "find ", "grep ", "rg ", "ls", "cat ", "head ", "tail ", "wc ",
                "sed ", "awk ", "git ", "python", "pip ", "pytest", "npm ",
                "cd ", "pwd", "mkdir ", "rm ", "cp ", "mv ", "chmod ", "echo ",
                "curl ", "wget ", "tree", "locate ", "which ", "whereis ", "stat ",
            )
            for m in re.finditer(r"```(bash|sh|zsh|exec|shell|)?\s*\n(.*?)```", accumulated, re.DOTALL | re.IGNORECASE):
                lang = (m.group(1) or "").strip().lower()
                body = (m.group(2) or "").strip()
                if not body or len(body) > 1200:
                    continue
                first_line = body.splitlines()[0].lstrip("$ ").strip()
                is_shell_cmd = bool(lang in ("bash", "sh", "zsh", "exec", "shell")) or first_line.startswith(shell_starts)
                # If the model wrote text AFTER the command block pretending it ran ("Bingo!", "yields", "output:"),
                # or used an explicit shell tag, intercept it and run the REAL command!
                after_text = accumulated[m.end():].strip()
                if is_shell_cmd and (lang or after_text):
                    lines = [ln.lstrip("$ ").strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
                    if len(lines) == 1:
                        tool_calls.append({"name": "shell_exec", "arguments": {"command": lines[0]}})
                    elif len(lines) > 1:
                        tool_calls.append({"name": "batch_exec", "arguments": {"commands": lines}})
                    self._truncate_fenced_hallucination_at = m.start()
                    break

        return tool_calls
    
    def _parse_function_args(self, args_str: str, tool_name: str):
        """Parse function-style arguments: keyword args or positional args."""
        args_str = args_str.strip()
        if not args_str:
            # Provide defaults for tools that need them
            defaults = {
                "file_list": {"path": "."},
                "file_read": {"path": "."},
                "shell_exec": {"command": ""},
                "code_exec": {"code": ""},
                "web_search": {"query": ""},
            }
            return defaults.get(tool_name, {})
        
        # Try to parse as JSON object (keyword args)
        if args_str.startswith("{"):
            try:
                return json.loads(args_str)
            except Exception:
                pass
        
        # Try to parse as keyword=value pairs
        if "=" in args_str and not (args_str.startswith('"') or args_str.startswith("'")):
            try:
                # Parse key=value, key2=value2 format
                pairs = re.findall(r'(\w+)\s*=\s*("[^"]*"|\'[^\']*\'|\S+)', args_str)
                if pairs:
                    args = {}
                    for k, v in pairs:
                        v = v.strip()
                        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                            v = v[1:-1]
                        args[k] = v
                    return args
            except Exception:
                pass
        
        # Single positional argument - map to appropriate parameter
        # Remove surrounding quotes if present
        if (args_str.startswith('"') and args_str.endswith('"')) or (args_str.startswith("'") and args_str.endswith("'")):
            args_str = args_str[1:-1]
        
        positional_map = {
            "file_list": "path",
            "file_read": "path",
            "file_write": "path",
            "shell_exec": "command",
            "code_exec": "code",
            "web_search": "query",
        }
        param = positional_map.get(tool_name, "arg")
        return {param: args_str}
    
    @staticmethod
    def _is_casual_opener(text: str) -> bool:
        """True when the user message is just a greeting/opener with no concrete task yet."""
        t = (text or "").strip()
        if not t or len(t) > 95 or "\n" in t:
            return False
        # Any image or visual generation request MUST NEVER be treated as casual opener!
        if re.search(r"\b(image|picture|pic|draw|photo|generate|art|render|paint|sketch|illustrate|wallpaper|avatar|sdxl|civitai)\b", t, re.IGNORECASE):
            return False
        # Any path, extension, backtick, or concrete action/tech noun means it is NOT casual
        if re.search(
            r"(`|/|\\|\.[a-z]{1,4}\b|\b(file|folder|dir|directory|path|code|script|command|terminal|bash|shell|python|git|pip|find|grep|search|read|write|edit|create|delete|remove|run|execute|list|ls|cat|check|fix|bug|error|install|build|test|web|google|http|url)\b)",
            t, re.IGNORECASE,
        ):
            return False
        return True

    def _normalize_tool_name(self, raw_name: str) -> str:
        base = str(raw_name or "").strip()
        for sep in (":", ".", "/"):
            if sep in base:
                base = base.rsplit(sep, 1)[-1].strip()
        clean = re.sub(r"[^a-z0-9]", "", base.lower())
        mapping = {
            "shellexec": "shell_exec", "shell": "shell_exec", "exec": "shell_exec",
            "bash": "shell_exec", "sh": "shell_exec", "terminal": "shell_exec", "cmd": "shell_exec",
            "run": "shell_exec", "codeexec": "code_exec", "python": "code_exec", "py": "code_exec", "grep": "grep_search", "searchfiles": "grep_search", "replace": "replace_file_content", "editfile": "replace_file_content",
            "fileread": "file_read", "readfile": "file_read", "cat": "file_read",
            "filewrite": "file_write", "writefile": "file_write",
            "filelist": "file_list", "listfiles": "file_list", "ls": "file_list", "dir": "file_list",
            "websearch": "web_search", "search": "web_search", "google": "web_search",
            "batchexec": "batch_exec", "batch": "batch_exec", "runbatch": "batch_exec",
            "multicmd": "batch_exec", "commands": "batch_exec",
        }
        return mapping.get(clean, raw_name)
    
    def _execute_and_loop(self, accumulated, tool_calls, messages):
        """Execute tool calls and return '__CONTINUE__' to loop or the final cleaned response."""
        trunc_at = getattr(self, "_truncate_fenced_hallucination_at", None)
        if trunc_at is not None:
            self._truncate_fenced_hallucination_at = None
            accumulated = accumulated[:trunc_at].strip()
        
        if tool_calls and not self.stop_requested:
            # Keep the raw TOOL_CALL text out of the visible assistant history  - 
            # weak models otherwise copy their own marker on the next round.
            _assistant_text = self._clean_tool_markup(accumulated)
            messages.append({"role": "assistant", "content": _assistant_text, "tool_calls": [
                {"id": f"call_{i}", "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"]) if isinstance(tc["arguments"], (dict, list)) else str(tc["arguments"])}}
                for i, tc in enumerate(tool_calls)
            ]})
            
            for tc in tool_calls:
                if self.stop_requested:
                    break
                raw_tool_name = tc.get("name", "")
                tool_name = self._normalize_tool_name(raw_tool_name)
                try:
                    args = json.loads(tc["arguments"]) if isinstance(tc.get("arguments"), str) else tc.get("arguments", {})
                except Exception:
                    args = {}
                # Gemini text-parsing sometimes DOUBLE-encodes arguments as a JSON
                # *string* (args == '"{...}"'). `**str` would crash execute() and
                # Signal(str, dict) silently delivers {} to the tool card - unwrap
                # it so the executor and the UI always see the same real dict.
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"text": args}
                if not isinstance(args, dict):
                    args = {}

                self.signals.tool_call.emit(tool_name, args)
                self.signals.status.emit(f"🔧 Running {tool_name}...")
                
                # ── CIRCUIT BREAKER: Prevent infinite hallucination / repeating identical failures ──
                call_sig = (tool_name, json.dumps(args, sort_keys=True))
                repeated_failures = sum(1 for (sig, res) in getattr(self, "_action_history", []) if sig == call_sig and "Error" in res[:30])
                
                # Snapshot pre-edit content for unified diff capture
                _edit_path = str(args.get("path", "")) if tool_name in ("replace_file_content", "file_write", "write_file") else ""
                _pre_content = ""
                _pre_existed = False
                if _edit_path:
                    try:
                        _pp = Path(_edit_path).expanduser().resolve()
                        if _pp.is_file():
                            _pre_content = _pp.read_text(encoding="utf-8", errors="replace")
                            _pre_existed = True
                    except Exception:
                        _pre_content = ""
                
                repeated_success = (
                    tool_name in ("file_write", "write_file", "create_file")
                    and call_sig in getattr(self, "_successful_calls", {})
                )
                if repeated_success:
                    # A successful write must never run again - looping
                    # models re-issued file_write forever, recreating the file.
                    result = (
                        "This exact tool call already SUCCEEDED earlier in this task. "
                        "Do NOT run it again. Reply to the user with the final result now."
                    )
                    self._force_finish = True
                elif repeated_failures >= 2:
                    result = f"Circuit Breaker Alert: You have repeated {tool_name} with the exact same arguments twice and failed each time. STOP repeating this command. Change strategy, run file_list or grep_search to discover reality, or explain what you need."
                elif tool_name in self.tools:
                    try:
                        result = self.tools[tool_name].execute(**args)
                    except Exception as e:
                        result = f"Error executing {tool_name}: {e}"
                else:
                    result = f"Error: Unknown tool {tool_name}"
                
                # Emit unified diff if this was an edit tool and it succeeded
                if _edit_path and not str(result).startswith("Error"):
                    try:
                        _pp = Path(_edit_path).expanduser().resolve()
                        _post = _pp.read_text(encoding="utf-8", errors="replace") if _pp.is_file() else ""
                        if _pre_existed:
                            _diff = build_unified_diff(_pre_content, _post, path=_edit_path)
                        else:
                            _diff = build_unified_diff("", _post, path=_edit_path)
                        if _diff.strip():
                            self.signals.tool_diff.emit(_edit_path, _diff)
                    except Exception:
                        pass
                
                self._action_history.append((call_sig, result[:100]))
                if not repeated_success and not str(result).startswith("Error"):
                    self._successful_calls[call_sig] = str(result)[:2000]

                self.signals.tool_result.emit(tool_name, result)
                messages.append({"role": "tool", "tool_call_id": f"call_{tool_calls.index(tc)}", "content": result})
            
            # Clean raw tool call markup from accumulated before continuing
            clean_acc = self._clean_tool_markup(accumulated)
            return "__CONTINUE__"
        
        # No tool calls - done
        return self._clean_tool_markup(accumulated) or accumulated
    
    def _clean_tool_markup(self, text):
        """Remove all tool call markup from text."""
        clean = text
        # Remove TOOL_CALL: {...} style
        while True:
            match = re.search(r'(?:TOOL_CALL|TOOLCALL|\[TOOL_CALL\]|\[TOOLCALL\])\s*:', clean, re.IGNORECASE)
            if not match:
                break
            json_str, s_idx, e_idx = extract_balanced_json(clean, match.end())
            if json_str:
                clean = clean[:match.start()] + clean[e_idx:]
            else:
                clean = clean[:match.start()] + clean[match.end():]
                break
        # Remove {{ tool_name(...) }} style
        clean = re.sub(r'\{\{\s*\w+\(.*?\)\s*\}\}', '', clean, flags=re.DOTALL)
        # Remove FILECONTENT: {{ ... }} style
        clean = re.sub(r'(?:FILECONTENT|FILE_CONTENT)\s*:\s*\{\{.*?\}\}', '', clean, flags=re.DOTALL | re.IGNORECASE)
        # Remove <respond>...</respond> tags
        clean = re.sub(r'<respond>.*?</respond>', '', clean, flags=re.DOTALL | re.IGNORECASE)
        # Remove <agent_action>...</agent_action> tags
        clean = re.sub(r'<agent_action.*?>.*?</agent_action>', '', clean, flags=re.DOTALL | re.IGNORECASE)
        # Stray control-token echoes ("TOOLI have…", "TOOL I have…").
        clean = re.sub(r"(?m)^[\t ]*TOOL(?=[A-Z])", "", clean)
        clean = re.sub(r"(?m)^[\t ]*TOOL[\t ]+(?=I\b)", "", clean)
        return clean.strip()
    
    def _emit_final(self, final_response, messages):
        """Emit the final done signal, optionally requesting a summary."""
        elapsed = round(max(0.05, time.time() - getattr(self, "_start_t", time.time())), 2)
        if self.stop_requested:
            self.signals.done.emit(self.session_id, final_response, max(1, len(final_response) // 4), elapsed, True)
        else:
            _has_marker = bool(re.search(
                r"(?:TOOL_CALL|TOOLCALL|\[TOOL_CALL\]|<tool_call>)",
                final_response, re.IGNORECASE))
            if final_response.strip() and not _has_marker and not final_response.strip().startswith("TOOL_"):
                self.signals.done.emit(self.session_id, final_response, max(1, len(final_response) // 4), elapsed, False)
            else:
                messages.append({"role": "system", "content": "All tools have completed. Provide a clear, concise, conversational summary of what was accomplished for user. Be warm and personal - you're Cel, not a robot."})
                summary_response = self._make_final_summary_call(messages)
                elapsed = round(max(0.05, time.time() - getattr(self, "_start_t", time.time())), 2)
                if not summary_response:
                    # A failed summary call after a real tool run is not a
                    # reason to fake success. If tools actually completed,
                    # keep the warm completion note; otherwise surface the
                    # dropped connection as an error.
                    if getattr(self, "_successful_calls", None):
                        summary_response = "✓ Task completed! *smiles* All done for you! 💕"
                    else:
                        self.signals.error.emit(
                            self.session_id,
                            "Connection Failed",
                            "No response received from the model. The connection may have dropped.",
                        )
                        return
                out_txt = summary_response
                self.signals.done.emit(self.session_id, out_txt, max(1, len(out_txt) // 4), elapsed, False)
    
    def _regular_generation(self):
        """Fallback path - should not be reached; send_message() routes correctly."""
        dev_log("[AgentWorker] _regular_generation called unexpectedly (tools_enabled=False)")
        self.signals.done.emit(self.session_id, "", 0, 0.0, True)

    def _make_final_summary_call(self, messages):
        """Make a final call to get a conversational summary after tools complete.
        Supports both online API and offline GGUF models."""
        
        # ── OFFLINE PATH ────────────────────────────────────────────
        if hasattr(self, "_offline_llm") and self._offline_llm is not None:
            try:
                llm = self._offline_llm
                params = self._offline_params
                
                # Flatten messages and merge system prompt for offline
                clean_msgs = []
                system_text = ""
                for m in messages:
                    c = m.get("content", "")
                    if isinstance(c, list):
                        c = " ".join([item.get("text", "") for item in c if item.get("type") == "text"])
                    role = m["role"]
                    if role == "system":
                        system_text += c + "\n\n"
                        continue
                    elif role == "tool":
                        role = "user"
                        c = f"[Tool Result]: {c}"
                    
                    # Strip tool_calls key (llama-cpp doesn't use it)
                    clean_msgs.append({"role": role, "content": c})
                
                if system_text:
                    if clean_msgs and clean_msgs[0]["role"] == "user":
                        clean_msgs[0]["content"] = system_text + clean_msgs[0]["content"]
                    else:
                        clean_msgs.insert(0, {"role": "user", "content": system_text.strip()})
                
                res = llm.create_chat_completion(
                    messages=clean_msgs,
                    max_tokens=min(512, max(16, params["n_ctx"] // 4)),
                    temperature=params["temp"],
                    top_p=params["top_p"],
                    repeat_penalty=params["rep_pen"],
                    stream=False
                )
                if "choices" in res and res["choices"]:
                    return res["choices"][0].get("message", {}).get("content", "").strip()
            except Exception as e:
                dev_log(f"[AgentWorker] Offline final summary failed: {e}")
            return None
        
        # ── ONLINE PATH ─────────────────────────────────────────────
        ctx = getattr(self, "_online_ctx", None)
        if not ctx:
            return None
        
        try:
            model = ctx["model"]
            provider = ctx["provider"]
            base_url = ctx["base_url"]
            api_key = ctx["api_key"]
            
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 1500,
                "stream": False
            }
            
            if provider == "Google Gemini":
                if not base_url or "generativelanguage" not in base_url:
                    base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
                endpoint = f"{base_url.rstrip('/')}/chat/completions"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "CelStudio/1.0"
                }
            else:
                endpoint = f"{base_url.rstrip('/')}/chat/completions"
                if provider == "GitHub Copilot":
                    from cellium.core.utils import copilot_headers
                    headers = copilot_headers(api_key)
                else:
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "CelStudio/1.0"
                    }
            
            req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
            
            last_err = None
            net_timeout = get_network_timeout(self.settings)
            net_retries = get_network_max_retries(self.settings)
            for attempt in range(net_retries):
                if self.stop_requested:
                    return None
                try:
                    if attempt > 0:
                        time.sleep(2.0)
                    resp = urllib.request.urlopen(req, timeout=net_timeout)
                    with resp:
                        data = json.loads(resp.read().decode('utf-8'))
                        if "choices" in data and data["choices"]:
                            return data["choices"][0].get("message", {}).get("content", "").strip()
                except urllib.error.HTTPError as he:
                    if he.code in (408, 429, 500, 502, 503, 504):
                        last_err = he
                        continue
                    break # Fatal 400/401/403
                except urllib.error.URLError as ue:
                    last_err = ue
                    continue
                except Exception as e:
                    last_err = e
                    continue
            
            if last_err:
                dev_log(f"[AgentWorker] Final summary call failed after retries: {last_err}")
            return None
        except Exception as e:
            dev_log(f"[AgentWorker] Final summary call failed: {e}")
        return None




# ── #24 & #25: Resilient Stream Auto-Retry & Universal Thinking Hook ─────────
import time as _aw_time
import requests as _aw_requests
from cellium.core.utils import (
    build_offline_thinking_config,
    build_online_thinking_params,
    normalize_thinking_level,
)

# 1. Resilient HTTP POST wrapper for SSE streams:
#    - Automatically retries transient network / 429 / 502 / 503 / 504 drops up to 3 times!
#    - If a provider returns HTTP 400 because a model doesn't support `thinkingConfig` or
#      `reasoning_effort` or `reasoning`, automatically strips the unsupported parameter and retries immediately!
_orig_requests_post = _aw_requests.post


def _resilient_ai_post(url, *args, **kwargs):
    json_payload = kwargs.get("json")
    max_attempts = 3
    last_exc = None

    for attempt in range(1, max_attempts + 1):
        try:
            resp = _orig_requests_post(url, *args, **kwargs)
            # If HTTP 400 due to unsupported thinking/reasoning field, strip it and retry once immediately!
            if resp.status_code == 400 and isinstance(json_payload, dict):
                stripped = False
                for k in ("reasoning_effort", "reasoning", "thinking", "output_config"):
                    if k in json_payload:
                        json_payload.pop(k, None)
                        stripped = True
                gen_cfg = json_payload.get("generationConfig")
                if isinstance(gen_cfg, dict) and "thinkingConfig" in gen_cfg:
                    gen_cfg.pop("thinkingConfig", None)
                    stripped = True
                if stripped:
                    resp = _orig_requests_post(url, *args, **kwargs)

            # Retry on transient rate-limit or gateway errors (429, 502, 503, 504)
            if resp.status_code in (429, 502, 503, 504) and attempt < max_attempts:
                _aw_time.sleep(0.75 * attempt)
                continue
            return resp
        except (_aw_requests.exceptions.ConnectionError, _aw_requests.exceptions.Timeout, _aw_requests.exceptions.ChunkedEncodingError) as exc:
            last_exc = exc
            if attempt < max_attempts:
                _aw_time.sleep(0.8 * attempt)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    return _orig_requests_post(url, *args, **kwargs)


_aw_requests.post = _resilient_ai_post


# 2. Wrap GenerationWorker._run_impl so transient mid-stream drops auto-retry instead of dying!
if "GenerationWorker" in globals() and hasattr(GenerationWorker, "_run_impl"):
    _orig_gen_run_impl = GenerationWorker._run_impl

    def _resilient_gen_run_impl(self):
        # Inject offline thinking budget metadata for local GGUF models
        try:
            lvl_raw = getattr(self, "thinking_level", "") or (self.settings.get("thinking_level", "Off") if hasattr(self, "settings") else "Off")
            m_name = getattr(self, "model_name", "") or (self.settings.get("selected_model", "") if hasattr(self, "settings") else "")
            self._offline_think_cfg = build_offline_thinking_config(m_name, lvl_raw)
        except Exception:
            self._offline_think_cfg = {"level": "off", "max_think_chars": 0}

        return _orig_gen_run_impl(self)

    GenerationWorker._run_impl = _resilient_gen_run_impl

# ══ WAVE_OMG_PARITY_START ══
def sanitize_alternating_messages(messages: list) -> list:
    """Ensure no empty/error turns and strict user/assistant alternation for Turn 2+ stability."""
    if not messages:
        return []
    bad_markers = (
        "*(connection interrupted)*",
        "*(no response received)*",
        "*(stopped immediately before generating)*",
    )
    out = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, str):
            c_strip = content.strip()
            if not c_strip:
                continue
            if role == "assistant" and c_strip in bad_markers:
                continue
        if out and out[-1].get("role") == role and role in ("user", "assistant"):
            if isinstance(out[-1].get("content"), str) and isinstance(content, str):
                if content.strip() not in out[-1]["content"]:
                    out[-1]["content"] = out[-1]["content"].rstrip() + "\n\n" + content.strip()
                continue
        out.append(dict(m))
    return out
# ══ WAVE_OMG_PARITY_END ══
