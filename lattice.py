"""Frame arithmetic for MiniMax H3 and LTX video models.

H3 Frame Lattice:
    H3 temporal VAE compresses in blocks of 17 frames plus a 5-frame head,
    so a valid clip length always satisfies: length % 17 == 5
    giving 5, 22, 39, 56, 73, 90, 107, 124, ... at a fixed 24 fps.

LTX Frame Rules:
    LTX 2.5 requires frames satisfying: (frames - 1) % 8 == 0
    giving 1, 9, 17, 25, 33, 41, ... at a configurable fps (default 24).

Design credit: Adapted from ComfyUI-MiniMaxDirector's lattice.py
(pure integer math, zero floating-point drift).
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple


class VideoModel(Enum):
    """Supported video generation backends."""
    H3 = "minimax_h3"
    LTX = "ltx"
    BERNINI = "bernini"


# -- H3 constants ----------------------------------------------------------

H3_FPS = 24
"""Frame rate of every H3 clip. Not configurable in the model."""

H3_STRIDE = 17
"""Temporal VAE block size."""

H3_PHASE = 5
"""Head frames outside the blocks; also the shortest legal H3 clip."""

H3_MAX_FRAMES = 512
"""Maximum frames per H3 segment (practical ceiling)."""

# -- LTX constants ---------------------------------------------------------

LTX_FPS = 24
"""Default LTX frame rate (configurable, but 24 is standard)."""

LTX_STRIDE = 8
"""LTX temporal VAE block size."""

LTX_PHASE = 1
"""LTX head frame offset."""

LTX_MAX_FRAMES = 257
"""Maximum frames per LTX segment."""

# -- Bernini constants -----------------------------------------------------

BERNINI_FPS = 24
"""Bernini frame rate."""

BERNINI_STRIDE = 4
"""Wan/Bernini temporal stride (4n+1)."""

BERNINI_PHASE = 1
"""Bernini head frame offset."""

BERNINI_MAX_FRAMES = 81
"""Maximum frames per Bernini segment."""


class ModelSpec(NamedTuple):
    """Model-specific frame arithmetic specification."""
    fps: int
    stride: int
    phase: int
    max_frames: int


MODEL_SPECS: dict[VideoModel, ModelSpec] = {
    VideoModel.H3: ModelSpec(H3_FPS, H3_STRIDE, H3_PHASE, H3_MAX_FRAMES),
    VideoModel.LTX: ModelSpec(LTX_FPS, LTX_STRIDE, LTX_PHASE, LTX_MAX_FRAMES),
    VideoModel.BERNINI: ModelSpec(BERNINI_FPS, BERNINI_STRIDE, BERNINI_PHASE, BERNINI_MAX_FRAMES),
}


def is_valid(frames: int, model: VideoModel = VideoModel.H3) -> bool:
    """True when `frames` is a length the model will accept."""
    spec = MODEL_SPECS[model]
    return frames >= spec.phase and frames % spec.stride == spec.phase


def snap_up(frames: int, model: VideoModel = VideoModel.H3) -> int:
    """Round `frames` up to the next valid length.

    Never rounds down, so a shot list is never silently truncated.
    """
    spec = MODEL_SPECS[model]
    frames = max(spec.phase, int(frames))
    return frames + (spec.phase - frames % spec.stride) % spec.stride


def snap_down(frames: int, model: VideoModel = VideoModel.H3) -> int:
    """Round `frames` down to the previous valid length.

    Useful when a duration must not exceed a ceiling.
    """
    spec = MODEL_SPECS[model]
    frames = max(spec.phase, int(frames))
    aligned = frames - (frames % spec.stride - spec.phase) % spec.stride
    return max(spec.phase, aligned)


def from_seconds(seconds: float, model: VideoModel = VideoModel.H3) -> int:
    """Wall-clock seconds -> a valid frame count."""
    spec = MODEL_SPECS[model]
    return snap_up(round(seconds * spec.fps), model)


def to_seconds(frames: int, model: VideoModel = VideoModel.H3) -> float:
    """Frame index or count -> wall-clock seconds."""
    spec = MODEL_SPECS[model]
    return frames / spec.fps


def ladder(count: int, model: VideoModel = VideoModel.H3) -> list[int]:
    """The first `count` valid lengths, shortest first.

    Useful for building a UI that can only express legal durations.
    """
    spec = MODEL_SPECS[model]
    return [spec.phase + spec.stride * step for step in range(count)]


def max_duration_seconds(model: VideoModel = VideoModel.H3) -> float:
    """Maximum clip duration in seconds for a single segment."""
    spec = MODEL_SPECS[model]
    return spec.max_frames / spec.fps


def format_timestamp(seconds: float) -> str:
    """Format a timestamp for prompt injection: `MM:SS.mmm`.

    H3 prompts require this exact format for shot cut times.
    """
    minutes = int(seconds // 60)
    remaining = seconds - minutes * 60
    whole = int(remaining)
    millis = int(round((remaining - whole) * 1000))
    return f"{minutes:02d}:{whole:02d}.{millis:03d}"


def format_seconds_short(seconds: float) -> str:
    """Format a timestamp as compact prose: `0`, `1`, `2.5`.

    Trailing zeros are dropped because the text encoder reads these as prose,
    and `2.50s` reads worse than `2.5s`.
    """
    rounded = round(seconds, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:g}"


def validate_segment_frames(
    frames: int,
    model: VideoModel = VideoModel.H3,
    label: str = "segment",
) -> int:
    """Validate and align frames, raising on overflow."""
    spec = MODEL_SPECS[model]
    aligned = snap_up(frames, model)
    if aligned > spec.max_frames:
        raise ValueError(
            f"{label} compiles to {aligned} frames; "
            f"{model.value} allows at most {spec.max_frames} frames per segment"
        )
    return aligned
