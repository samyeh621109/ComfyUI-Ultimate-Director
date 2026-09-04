# -*- coding: utf-8 -*-
"""Motion Context & Tail Handoff Engine for Ultimate Director.

Extracts the last N frames (22/5/39/56) of a previous segment to guide the next segment,
and trims the overlap prefix after decoding to ensure 100% seamless continuity (Zero Jump-Cut).
Inspired by ComfyUI-MiniMaxH3-Director & ComfyUI-H3-Motion-Context.
"""
from __future__ import annotations

import torch

CONTEXT_FRAME_CHOICES = [22, 5, 39, 56]
DEFAULT_CONTEXT_FRAMES = 22

def extract_tail_frames(
    images: torch.Tensor | None, 
    context_frames: int = DEFAULT_CONTEXT_FRAMES
) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Extracts (tail_motion_clip, last_single_frame) from video tensor [T, H, W, C].
    """
    if images is None or images.shape[0] == 0:
        empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
        return empty, empty
        
    total_frames = images.shape[0]
    n = min(total_frames, context_frames)
    
    tail_clip = images[total_frames - n :]
    last_frame = images[total_frames - 1 : total_frames]
    return tail_clip, last_frame

def trim_motion_prefix(
    images: torch.Tensor | None, 
    prefix_trim: int = DEFAULT_CONTEXT_FRAMES
) -> torch.Tensor:
    """
    Trims the motion-context overlap prefix from the decoded video segment.
    """
    if images is None or images.shape[0] == 0:
        return torch.zeros((1, 64, 64, 3), dtype=torch.float32)
        
    total_frames = images.shape[0]
    if prefix_trim <= 0 or prefix_trim >= total_frames:
        return images
        
    return images[prefix_trim:]

class UltimateDirectorMotionHandoffNode:
    """
    Extracts the tail frames from the previous video segment to lock continuity for the next segment.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prev_video_frames": ("IMAGE", {"tooltip": "上一段產生的完整視訊幀序列 (IMAGE)。"}),
                "context_frames": (["22 (推薦標準)", "5 (極短過渡)", "39 (長時序緩衝)", "56 (超長引導)"], {
                    "default": "22 (推薦標準)",
                    "tooltip": "MiniMax H3 官方推薦的 17k+5 潛空間時序對齊幀數（預設 22 幀 ≈ 0.9 秒）。"
                }),
            }
        }
        
    RETURN_TYPES = ("IMAGE", "IMAGE", "INT")
    RETURN_NAMES = ("motion_tail_clip", "last_single_frame", "trim_prefix_frames")
    FUNCTION = "extract_handoff"
    CATEGORY = "UltimateDirector/Continuity"
    
    def extract_handoff(self, prev_video_frames, context_frames):
        num_frames = int(context_frames.split()[0])
        tail_clip, last_frame = extract_tail_frames(prev_video_frames, num_frames)
        return (tail_clip, last_frame, num_frames)

class UltimateDirectorMotionTrimNode:
    """
    Trims the pinned motion-context prefix from the current segment's decoded output.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "decoded_video": ("IMAGE", {"tooltip": "本段解碼後的視訊畫面 (IMAGE)。"}),
                "trim_prefix_frames": ("INT", {
                    "default": 22,
                    "min": 0,
                    "max": 120,
                    "step": 1,
                    "tooltip": "需切除的引導前綴幀數（通常與上一節點輸出的 trim_prefix_frames 相連）。"
                }),
            }
        }
        
    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("seamless_video", "actual_frames")
    FUNCTION = "trim_prefix"
    CATEGORY = "UltimateDirector/Continuity"
    
    def trim_prefix(self, decoded_video, trim_prefix_frames):
        trimmed = trim_motion_prefix(decoded_video, trim_prefix_frames)
        return (trimmed, trimmed.shape[0])
