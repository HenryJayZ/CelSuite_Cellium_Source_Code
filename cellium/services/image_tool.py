#!/usr/bin/env python3
"""
Agent-callable image generation tool (Kaggle BYOK).

When Settings/hamburger "🎨 Enable Image Gen" is ON, the AgentWorker gets a
``generate_image`` tool. The LLM can then decide to:
  * create a NEW image from a text prompt, or
  * EDIT the last generated image (``edit_last=true`` → img2img on it),
    e.g. "put a clown face on the cat".

A module-level QObject hub carries Qt signals so the tool (running in the
worker thread) can update the GUI thread's chat status bubble / image bubble.
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from cellium.core.tools import AgentTool
from cellium.core.logger import dev_log


class ImageToolHub(QObject):
    """Shared signals + state between the main window and the agent tool."""

    progress = Signal(str, str, str)   # stage, detail, prompt
    image_ready = Signal(str, str, str)  # path, seed, prompt
    error = Signal(str)                # message

    def __init__(self):
        super().__init__()
        self.backend_factory = None      # callable -> KaggleImageBackend | None
        self.settings_getter = None      # callable -> dict
        self.preset_getter = None        # callable -> str (preset name)
        self.last_image: str = ""        # last generated image path (for edit_last)

    def make_tool(self) -> "ImagineTool":
        return ImagineTool(self)


_HUB: ImageToolHub | None = None


def get_hub() -> ImageToolHub:
    global _HUB
    if _HUB is None:
        _HUB = ImageToolHub()
    return _HUB


def image_to_b64(path: str, max_side: int = 1024, quality: int = 85) -> str:
    """Downscale + JPEG-encode an image to a small base64 string for img2img."""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class ImagineTool(AgentTool):
    name = "generate_image"

    def __init__(self, hub: ImageToolHub):
        self.hub = hub
        super().__init__(
            "generate_image",
            (
                "Generate an image on the cloud GPU (Kaggle) from a text prompt. "
                "Use it whenever the user asks to draw/generate/create an image, or to EDIT the "
                "last generated image: set edit_last=true and describe the change "
                "(e.g. 'put a clown face on it', 'make the background night'). "
                "edit_last=false always creates a brand-new image. Returns the saved file path "
                "and seed; the image is shown in the chat automatically."
            ),
            {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Detailed image prompt (danbooru-style tags work great)"},
                    "negative_prompt": {"type": "string", "description": "What to avoid", "default": ""},
                    "edit_last": {"type": "boolean", "description": "true = modify the last generated image (img2img)", "default": False},
                    "denoise": {"type": "number", "description": "img2img strength 0.4-0.9 (only when edit_last)", "default": 0.7},
                    "steps": {"type": "integer", "default": 28},
                    "width": {"type": "integer", "default": 832},
                    "height": {"type": "integer", "default": 1216},
                    "seed": {"type": "integer", "default": -1, "description": "-1 = random"},
                },
                "required": ["prompt"],
            },
        )

    def execute(self, prompt: str = "", negative_prompt: str = "", edit_last: bool = False,
                denoise: float = 0.7, steps: int = 0, width: int = 0, height: int = 0,
                seed: int = -1, **kwargs) -> str:
        prompt = (prompt or "").strip()
        if not prompt:
            return "Error: prompt is empty"
        hub = self.hub
        try:
            factory = hub.backend_factory
            backend = factory() if callable(factory) else None
        except Exception:
            backend = None
        if backend is None:
            msg = "Error: Kaggle not configured - set it up in Settings → Image Generation."
            hub.error.emit(msg)
            return msg

        # defaults from settings
        s = {}
        try:
            s = hub.settings_getter() if callable(hub.settings_getter) else {}
        except Exception:
            s = {}
        preset = ""
        try:
            preset = hub.preset_getter() if callable(hub.preset_getter) else ""
        except Exception:
            preset = ""
        from cellium.services.kaggle_image import build_model_config
        if preset:
            try:
                backend.model_config = build_model_config(s, preset)
            except Exception:
                pass

        neg = negative_prompt or s.get("kaggle_negative_prompt", "")
        steps = int(steps) if steps else int(s.get("kaggle_steps", 28))
        size_str = s.get("kaggle_size", "832x1216 (9:16)")
        try:
            w, h = map(int, size_str.split(" (")[0].split("x"))
        except Exception:
            w, h = 832, 1216
        if width:
            w = int(width)
        if height:
            h = int(height)
        guidance = float(s.get("kaggle_guidance", 6.5))

        # img2img on the last generated image?
        init_b64 = ""
        if edit_last and hub.last_image and os.path.exists(hub.last_image):
            try:
                init_b64 = image_to_b64(hub.last_image)
            except Exception as e:
                dev_log(f"[ImagineTool] init image encode failed: {e}")

        def cb(stage, detail):
            try:
                hub.progress.emit(stage, detail, prompt)
            except Exception:
                pass

        backend.progress_cb = cb
        try:
            result = backend.generate(
                prompt, neg, steps, w, h, seed, guidance,
                batch=1, init_b64=init_b64, denoise=float(denoise),
            )
        except Exception as e:
            msg = f"Error: image generation failed: {e}"
            hub.error.emit(str(e)[:400])
            return msg

        path = str(result.image_path)
        hub.last_image = path
        try:
            hub.image_ready.emit(path, str(result.seed), prompt)
        except Exception:
            pass
        mode = "edited last image" if init_b64 else "generated new image"
        return (f"OK: {mode}. Saved to {path} (seed {result.seed}, "
                f"{result.elapsed_seconds:.0f}s). The image is displayed in the chat.")
