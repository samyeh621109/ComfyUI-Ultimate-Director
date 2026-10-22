"""Release GPU memory between MiniMax H3 Director segment runs."""

from __future__ import annotations

import gc
import logging

log = logging.getLogger("ComfyUI-MiniMaxH3-Director.director.vram")


def cleanup_segment_vram(*, enabled: bool = True, unload_models: bool = True) -> None:
    """Release segment GPU memory: gc, optional unload of ComfyUI models, empty CUDA cache."""
    if not enabled:
        return
    gc.collect()
    try:
        import comfy.model_management as mm
        import torch

        mm.cleanup_models_gc()
        if unload_models:
            mm.unload_all_models()
            mm.cleanup_models()
        mm.soft_empty_cache()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception as exc:
        log.warning("Segment VRAM cleanup failed: %s", exc)
        return
    if unload_models:
        log.info("MiniMax H3 Director: segment VRAM cleanup (models unloaded, CUDA cache cleared)")
    else:
        log.info("MiniMax H3 Director: segment VRAM cleanup (CUDA cache cleared, models kept loaded)")
