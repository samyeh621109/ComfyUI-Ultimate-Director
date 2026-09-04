# -*- coding: utf-8 -*-
"""Ultimate Director: ComfyUI custom node package.

A unified director node suite that integrates the best features from:
- Story Engine: Nuanced human acting, micro-expressions, GGUF in-process zero-VRAM purge
- Prompt Enhancer: VLM vision analysis, GGUF rewrite, Calliope 6-section template, 7000-char smart trim
- Refine & Latent Upscaler: Same-res 2nd pass, H3 3D Latent Upscaler, multi-pass, fl2v keyframe lock
- Multimodal Studio Director: Storyboard Grid & Omnipotent Reference Studio (Dual Mode UI)
- Storyboard Grid: 4/6/9 panel grid splitting & auto-batching (from CS-H3)
- Motion Context: 22-frame tail handoff & prefix trim for zero-jumpcut continuous video (from MiniMaxH3 Director)
- Lattice & Compiler: Exact frame arithmetic & multi-model prompt compilation
"""

import os
from .lattice import VideoModel, snap_up, from_seconds, to_seconds, is_valid
from .timeline import Timeline, Shot, CastMember, Reference
from .compile import compile_timeline, compile_segments, CompiledPrompt, CompiledSegment
from .lint import lint, lint_report
from .continuity import get_generation_frames, apply_scail_lock, trim_decoded_segment, concat_segments
from .story_engine import StoryEngine
from .grid_splitter import split_storyboard_grid, UltimateDirectorStoryboardGridNode
from .motion_context import extract_tail_frames, trim_motion_prefix, UltimateDirectorMotionHandoffNode, UltimateDirectorMotionTrimNode
from .prompt_enhancer import validate_and_repair_prompt, build_calliope_ref_fallback
from .refine_controller import UltimateDirectorRefineNode, pack_refine_config
from .multimodal_director import UltimateDirectorMultimodalDirector, UltimateDirectorMediaDashboardNode
from .cast_iterator import UltimateDirectorCastIteratorNode
from .auto_cast_generator import UltimateDirectorAutoCastBatchGenerator
from .nodes_comfy import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./js"

# Register AI Drama Infinite Canvas static route
try:
    from server import PromptServer
    from aiohttp import web
    import logging

    _CANVAS_DIR = "/home/sam/Desktop/krea2_skills/canvas"
    if hasattr(PromptServer, "instance") and PromptServer.instance is not None:
        if os.path.isdir(_CANVAS_DIR):
            PromptServer.instance.app.add_routes([
                web.static("/director_canvas", _CANVAS_DIR, follow_symlinks=True)
            ])
            logging.getLogger("UltimateDirector").info("✅ AI 短劇無限畫布已掛載至 /director_canvas/index.html")
except Exception as _e:
    pass

__version__ = "2.0.0"

__all__ = [
    "VideoModel",
    "Timeline",
    "Shot",
    "CastMember",
    "Reference",
    "compile_timeline",
    "compile_segments",
    "CompiledPrompt",
    "CompiledSegment",
    "lint",
    "lint_report",
    "get_generation_frames",
    "apply_scail_lock",
    "trim_decoded_segment",
    "concat_segments",
    "snap_up",
    "from_seconds",
    "to_seconds",
    "is_valid",
    "StoryEngine",
    "split_storyboard_grid",
    "extract_tail_frames",
    "trim_motion_prefix",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
