"""Ultimate Director: ComfyUI custom node package.

A unified director node that integrates the best features from 22 reference
projects into a single cohesive system for short-drama video production.

Core modules:
    lattice  -- Frame arithmetic for H3/LTX/Bernini
    timeline -- Unified timeline document structure
    compile  -- Multi-model prompt compiler
    lint     -- Quality gate validation
"""

from .lattice import VideoModel, snap_up, from_seconds, to_seconds, is_valid
from .timeline import Timeline, Shot, CastMember, Reference
from .compile import compile_timeline, compile_segments, CompiledPrompt, CompiledSegment
from .lint import lint, lint_report
from .continuity import get_generation_frames, apply_scail_lock, trim_decoded_segment, concat_segments
from .story_engine import StoryEngine
from .nodes_comfy import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__version__ = "0.1.0"
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
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
