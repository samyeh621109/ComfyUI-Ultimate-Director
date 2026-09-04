# -*- coding: utf-8 -*-
"""Ultimate Director: Text Display & Script Viewer node.

Provides an interactive text/markdown viewer on the node card,
allowing seamless inspection of StoryEngine scripts and prompts
without requiring ComfyUI-Custom-Scripts.
"""

from __future__ import annotations

import logging
from typing import Any, Tuple

log = logging.getLogger("UltimateDirector.text_display")


class UltimateDirectorTextDisplay:
    """Displays text/markdown in the ComfyUI node graph with copy support.
    Direct replacement for ShowText|pysssss without requiring ComfyUI-Custom-Scripts.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True, "tooltip": "Input text to display."}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    OUTPUT_NODE = True
    FUNCTION = "display"
    CATEGORY = "UltimateDirector"
    DESCRIPTION = "📜 終極導演：文字與分鏡劇本檢視器，支援一鍵複製與格式化排版，原生取代 ShowText。"

    def display(self, text: Any, **_kwargs) -> dict:
        text_str = str(text) if text is not None else ""
        return {
            "ui": {
                "text": [text_str],
                "string": [text_str],
            },
            "result": (text_str,),
        }

