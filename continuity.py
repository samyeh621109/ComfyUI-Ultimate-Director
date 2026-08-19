"""Segment Continuity and Image Locking (SCAIL).

This module manages cross-segment continuity for long video generation.
Adapted from ComfyUI_Bernini_Director's industrial-grade segment_continuity.py.

Core mechanism (WanSCAIL-style handoff):
1. Prepend prev-tail pixels so canvas length matches generation.
2. Generate prefix + settling + segment body.
3. SCAIL latent prefix lock via noise_mask=0.0 (prefix not resampled).
4. Append appearance ref frames to context_latents.
5. Trim prefix and settling burn-in after decode.
6. Mild luma bridging on concat.
"""

from __future__ import annotations

import logging
from typing import Any

import torch
from . import lattice
from .lattice import VideoModel

log = logging.getLogger("UltimateDirector.continuity")

# -- Continuity Constants --------------------------------------------------

DEFAULT_OVERLAP = 9
MIN_OVERLAP = 1
MAX_OVERLAP = 81

# Burn-in frames after SCAIL lock, discarded on export (anti hold->pop).
SETTLING_FRAMES = 12

# Lookahead frames past segment end so the model doesn't invent a frozen tail.
SOURCE_LOOKAHEAD = 8


def get_overlap_pixels(overlap_frames: int, model: VideoModel = VideoModel.H3) -> int:
    """Get aligned prefix length for clean VAE round-trip."""
    ov = max(MIN_OVERLAP, min(MAX_OVERLAP, int(overlap_frames)))
    return lattice.snap_up(ov, model)


def get_generation_frames(
    body_frames: int,
    segment_index: int,
    continuity_enabled: bool,
    overlap_frames: int,
    model: VideoModel = VideoModel.H3,
) -> tuple[int, int]:
    """Calculate actual frames to generate and how many to trim after.

    Returns:
        (total_frames_to_generate, frames_to_trim_from_start)
    """
    body = max(1, int(body_frames))
    if not continuity_enabled or segment_index <= 0:
        return lattice.snap_up(body, model), 0

    lock_px = get_overlap_pixels(overlap_frames, model)
    if lock_px <= 0:
        return lattice.snap_up(body, model), 0

    settling = max(0, int(SETTLING_FRAMES))
    raw = lock_px + settling + body + SOURCE_LOOKAHEAD
    return lattice.snap_up(raw, model), lock_px + settling


def apply_scail_lock(
    latent: dict[str, Any],
    tail_latent: torch.Tensor,
    overlap_pixel_frames: int,
    model: VideoModel = VideoModel.H3,
) -> tuple[dict[str, Any], bool]:
    """Lock prefix latents with noise_mask=0 to enforce continuity.

    Args:
        latent: The ComfyUI latent dict to modify.
        tail_latent: The 5D encoded latent of the previous segment's tail.
        overlap_pixel_frames: Number of frames to lock.

    Returns:
        (modified_latent, success_flag)
    """
    samples = latent["samples"]
    if samples.ndim == 4:
        samples = samples.unsqueeze(0)
        
    _, _c, t_total, h, w = samples.shape
    th, tw = int(tail_latent.shape[3]), int(tail_latent.shape[4])

    # Resize if spatial dimensions mismatch (better than silent skip)
    if th != h or tw != w:
        log.warning(f"SCAIL spatial mismatch: tail {th}x{tw} vs latent {h}x{w}. Resizing.")
        b, c, f, _, _ = tail_latent.shape
        flat = tail_latent.reshape(b * c * f, 1, th, tw)
        flat = torch.nn.functional.interpolate(
            flat.float(), size=(h, w), mode="bilinear", align_corners=False
        )
        tail_latent = flat.to(dtype=tail_latent.dtype).reshape(b, c, f, h, w)

    aligned_pixels = get_overlap_pixels(overlap_pixel_frames, model)
    # Simple estimation for latent frames. Actual ratio depends on the model's temporal VAE.
    t_tail_est = max(1, (max(1, aligned_pixels) - 1) // 4 + 1)
    
    t_tail = min(
        int(tail_latent.shape[2]),
        t_tail_est,
        t_total,
    )

    if t_tail <= 0:
        return latent, False

    out = dict(latent)
    patched = samples.clone()
    patched[:, :, :t_tail] = tail_latent[:, :, :t_tail].to(
        device=patched.device, dtype=patched.dtype
    )

    # Initialize noise mask
    noise_mask = torch.ones(
        (1, 1, t_total, h, w),
        dtype=patched.dtype,
        device=patched.device,
    )
    
    # 0.0 means do not denoise (keep locked)
    noise_mask[:, :, :t_tail] = 0.0

    # Warm-start first free latents from the last locked frame
    # (prevents harsh artifact lines at the transition point)
    warms = (0.55, 0.34, 0.16)
    for offset, warm in enumerate(warms):
        t = t_tail + offset
        if t <= 0 or t >= t_total:
            continue
        patched[:, :, t] = patched[:, :, t] * (1.0 - warm) + patched[:, :, t - 1] * warm
        noise_mask[:, :, t] = 1.0  # Must be 1.0 (full denoise) to avoid under-denoised artifacts

    out["samples"] = patched
    out["noise_mask"] = noise_mask
    
    log.info(
        f"SCAIL lock applied: {t_tail} latent frames locked, "
        f"warmstarts={warms[:min(len(warms), t_total - t_tail)]}"
    )
    return out, True


def trim_decoded_segment(
    decoded: torch.Tensor,
    prefix_trim: int,
    target_len: int,
) -> torch.Tensor:
    """Drop SCAIL overlap prefix and settling frames, keeping only the body."""
    prefix_trim = max(0, int(prefix_trim))
    out = decoded
    
    if prefix_trim > 0 and int(decoded.shape[0]) > prefix_trim:
        out = decoded[prefix_trim:]
    elif prefix_trim > 0 and int(decoded.shape[0]) == prefix_trim:
        out = decoded[:0]

    if target_len > 0 and int(out.shape[0]) > target_len:
        out = out[:target_len]
        
    return out


def _frame_mad(a: torch.Tensor, b: torch.Tensor) -> float:
    """Mean absolute difference proxy (RGB)."""
    aa = a.detach().float()
    bb = b.detach().float()
    if aa.dim() == 3:
        aa = aa.unsqueeze(0)
        bb = bb.unsqueeze(0)
    if aa.shape[0] != bb.shape[0]:
        return 1e9
    return float((aa[..., :3] - bb[..., :3]).abs().mean().item() * 255.0)


def concat_segments(chunks: list[torch.Tensor]) -> torch.Tensor:
    """Concatenate segments. Additive luma blending if needed."""
    if not chunks:
        raise ValueError("No chunks to concatenate")
    if len(chunks) == 1:
        return chunks[0]

    fixed = [chunks[0]]
    for i in range(1, len(chunks)):
        left = fixed[-1]
        body = chunks[i]
        
        # Mild micro seam bridge to avoid harsh jump cuts in continuity
        if left.shape[0] > 0 and body.shape[0] > 0:
            seam_mad = _frame_mad(left[-1], body[0])
            if 15.0 < seam_mad < 50.0:  # Only if it's a moderate jump
                weight = 0.15
                left_clone = left.clone()
                body_clone = body.clone()
                left_clone[-1] = (left[-1] * (1.0 - weight) + body[0] * weight).clamp(0, 1)
                body_clone[0]  = (body[0]  * (1.0 - weight) + left[-1] * weight).clamp(0, 1)
                left = left_clone
                body = body_clone
                
        fixed[-1] = left
        fixed.append(body)
        
    return torch.cat(fixed, dim=0)
