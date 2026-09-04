# -*- coding: utf-8 -*-
"""Ultimate Director: Zero-dependency compatibility stubs.

Provides drop-in replacements for third-party helper nodes so existing
workflows load seamlessly without raising 'missing node' dialogs.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("UltimateDirector.compat")


class MiniMaxH3MemoryEfficientSageAttentionPatch:
    """Compatibility pass-through for SageAttention patch.
    ComfyUI native engine already handles SageAttention globally via --use-sage-attention.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL", {"tooltip": "Model to pass through."}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "patch"
    CATEGORY = "MiniMaxH3"
    DESCRIPTION = "MiniMax H3 SageAttention 顯存補丁（核心已原生啟用）。"

    def patch(self, model: Any):
        return (model,)


class ModelPreviewOverrideKJ:
    """Compatibility pass-through for ModelPreviewOverrideKJ.
    Prevents missing node errors when loading legacy KJNodes workflows.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL", {"tooltip": "Model to pass through."}),
            },
            "optional": {
                "preview_latent": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "override"
    CATEGORY = "MiniMaxH3"
    DESCRIPTION = "TAEH3 即時預覽相容節點（Director 已內建預覽支援）。"

    def override(self, model: Any, **_kwargs):
        return (model,)
