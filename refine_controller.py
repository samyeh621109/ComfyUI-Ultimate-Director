# -*- coding: utf-8 -*-
"""MiniMax H3 Refine & Latent Upscale Controller.

Integrates:
1. Same-resolution 2nd pass refinement (Euler / ResMultistep)
2. H3 3D Latent Upscaler (minimax_h3_latent_upscaler_3d_fp16)
3. Multi-pass refinement (1~4 passes)
4. First-and-Last-Frame (fl2v) keyframe lock protection
5. Dynamic Aspect Ratio & Megapixel canvas calculations aligned to x32.
"""

from __future__ import annotations

import math
import os
from typing import Any

import folder_paths
import comfy.samplers

# Category & Types
_CATEGORY = "UltimateDirector/Refine"
MMX_DIR_REFINE = "MMX_DIR_REFINE"

REFINE_MODES = ("refine", "upscale", "latent_upscale")
UPSCALE_METHODS = ("mmh3_split_upscale", "h3_latent", "lanczos", "nvidia_rtx_vsr")
SEED_MODES = ("inherit", "offset")

ASPECT_RATIO_PRESETS = {
    "16:9 (寬螢幕)": 16 / 9,
    "9:16 (直式直屏)": 9 / 16,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
    "1:1": 1.0,
    "21:9 (超寬電影)": 21 / 9,
}
FOLLOW_DIRECTOR_ASPECT = "跟隨導演台 (Auto: match Director aspect)"
CUSTOM_ASPECT = "自訂 (Custom)"

ASPECT_RATIO_CHOICES = [FOLLOW_DIRECTOR_ASPECT] + list(ASPECT_RATIO_PRESETS.keys()) + [CUSTOM_ASPECT]

DEFAULT_UPSCALE_MEGAPIXELS = 1.0
DEFAULT_REFINE_SIGMA_SAMPLER = "res_multistep"


def list_h3_latent_upscale_models():
    """List 3D latent upscale models in models/latent_upscale_models/."""
    folder = "latent_upscale_models"
    if folder not in folder_paths.folder_names_and_paths:
        folder_paths.add_model_folder_path(
            folder,
            os.path.join(folder_paths.models_dir, folder)
        )
    files = folder_paths.get_filename_list(folder)
    models = [f for f in files if "3d" in f.lower() or "h3" in f.lower() or f.endswith(".safetensors")]
    if not models:
        models = ["minimax_h3_latent_upscaler_3d_fp16.safetensors"]
    return models


def infer_upscale_target(
    orig_w: int,
    orig_h: int,
    aspect_ratio: str = FOLLOW_DIRECTOR_ASPECT,
    megapixels: float = DEFAULT_UPSCALE_MEGAPIXELS,
    custom_w: int = 1280,
    custom_h: int = 720,
    multiple: int = 32,
) -> tuple[int, int]:
    """Calculate target canvas dimensions aligned to multiple of 32."""
    if aspect_ratio == CUSTOM_ASPECT:
        w = max(multiple, round(custom_w / multiple) * multiple)
        h = max(multiple, round(custom_h / multiple) * multiple)
        return w, h

    ratio = None
    if aspect_ratio in ASPECT_RATIO_PRESETS:
        ratio = ASPECT_RATIO_PRESETS[aspect_ratio]
    elif orig_w > 0 and orig_h > 0:
        ratio = float(orig_w) / float(orig_h)
    else:
        ratio = 16 / 9

    mp = max(0.1, min(16.0, megapixels))
    total_pixels = mp * 1024 * 1024
    width = max(multiple, round(math.sqrt(total_pixels * ratio) / multiple) * multiple)
    height = max(multiple, round(math.sqrt(total_pixels / ratio) / multiple) * multiple)
    return width, height


def pack_refine_config(
    mode: str = "upscale",
    upscale_method: str = "mmh3_split_upscale",
    latent_upscale_model: str = "minimax_h3_latent_upscaler_3d_fp16.safetensors",
    sampler: str = DEFAULT_REFINE_SIGMA_SAMPLER,
    passes: int = 1,
    seed_mode: str = "inherit",
    aspect_ratio: str = FOLLOW_DIRECTOR_ASPECT,
    megapixels: float = DEFAULT_UPSCALE_MEGAPIXELS,
    width: int = 1280,
    height: int = 720,
    skip_fl2v: bool = True,
    refine_model: Any = None,
    sigmas: Any = None,
    upscale_model: Any = None,
    temporal_split_param: Any = None,
    spatial_split_param: Any = None,
) -> dict[str, Any]:
    """Pack refine & latent upscaler parameters into MMX_DIR_REFINE contract."""
    target_w, target_h = infer_upscale_target(
        0, 0, aspect_ratio=aspect_ratio, megapixels=megapixels, custom_w=width, custom_h=height
    )
    return {
        "enabled": True,
        "mode": mode,
        "upscale_method": upscale_method,
        "latent_upscale_model": latent_upscale_model,
        "sampler": sampler or DEFAULT_REFINE_SIGMA_SAMPLER,
        "passes": max(1, passes),
        "seed_mode": seed_mode,
        "aspect_ratio": aspect_ratio,
        "megapixels": megapixels,
        "target_width": target_w,
        "target_height": target_h,
        "skip_fl2v": skip_fl2v,
        "sample_model": refine_model,
        "sigmas": sigmas,
        "upscale_model": upscale_model,
        "temporal_split_param": temporal_split_param,
        "spatial_split_param": spatial_split_param,
    }


class UltimateDirectorRefineNode:
    """Ultimate Director Refine & 3D Latent Upscale Controller.
    Connect output `refine` to MiniMaxH3Director.refine.
    """

    @classmethod
    def INPUT_TYPES(cls):
        models = list_h3_latent_upscale_models()
        return {
            "required": {
                "enable_refine": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "🔥 二採/放大總開關：勾選開啟二採放大，取消勾選則直出成片（省時省顯存，完全免按 Ctrl+M 靜音）。",
                    },
                ),
                "mode": (
                    list(REFINE_MODES),
                    {
                        "default": "upscale",
                        "tooltip": (
                            "upscale = 推薦模式：以 MMH3 時空分塊 + 三重錨點放大到目標畫布並重採樣精修（8GB 顯存零崩壞、不斷肢）。\n"
                            "latent_upscale = 只以 Latent 快速放大，不再二採。\n"
                            "refine = 同解析度二採（精修微細節）。"
                        ),
                    },
                ),
                "upscale_method": (
                    list(UPSCALE_METHODS),
                    {
                        "default": "mmh3_split_upscale",
                        "tooltip": "放大引擎。mmh3_split_upscale = 終極時空分塊防斷肢二採；h3_latent = 傳統 3D Latent；lanczos = 像素插值；nvidia_rtx_vsr = 硬體超分。",
                    },
                ),
                "latent_upscale_model": (
                    models,
                    {
                        "default": models[0] if models else "minimax_h3_latent_upscaler_3d_fp16.safetensors",
                        "tooltip": "可選 MiniMax H3 專用 3D Latent 或 LTX-2.5 放大模型權重（位於 models/latent_upscale_models/）。",
                    },
                ),
                "sampler": (
                    comfy.samplers.KSampler.SAMPLERS,
                    {
                        "default": DEFAULT_REFINE_SIGMA_SAMPLER,
                        "tooltip": "二採採樣器（建議 res_multistep 或 euler）。",
                    },
                ),
                "passes": (
                    "INT",
                    {"default": 1, "min": 1, "max": 4, "step": 1, "tooltip": "精修次數。1 = 一輪二採精修。"},
                ),
                "seed_mode": (list(SEED_MODES), {"default": "inherit", "tooltip": "隨機種子模式：inherit 繼承上一階段，offset 偏移。"}),
                "aspect_ratio": (list(ASPECT_RATIO_CHOICES), {"default": FOLLOW_DIRECTOR_ASPECT, "tooltip": "目標畫面比例設定。"}),
                "megapixels": ("FLOAT", {"default": DEFAULT_UPSCALE_MEGAPIXELS, "min": 0.1, "max": 16.0, "step": 0.1, "tooltip": "目標百萬像素（1.0 = 720p/1080p 等效）。"}),
                "width": ("INT", {"default": 1280, "min": 64, "max": 8192, "step": 32, "tooltip": "自訂目標寬度（像素）。"}),
                "height": ("INT", {"default": 720, "min": 64, "max": 8192, "step": 32, "tooltip": "自訂目標高度（像素）。"}),
                "skip_fl2v": ("BOOLEAN", {"default": True, "tooltip": "首尾幀鎖定鏡頭是否跳過二採，防止關鍵幀跑偏。"}),
            },
            "optional": {
                "temporal_split_param": ("H3_TEMPORAL_PARAM_V10", {"tooltip": "可選接 MMH3 Temporal Split Params 節點（時間切分與三重時序錨點）。"}),
                "spatial_split_param": ("H3_SPATIAL_PARAM_V10", {"tooltip": "可選接 MMH3 Spatial Split Params 節點（空間切分與 seam_denoise 接縫防撕裂）。"}),
                "refine_model": ("MODEL", {"tooltip": "可選獨立二採模型/LoRA。不接則沿用導演台主模型。"}),
                "sigmas": ("SIGMAS", {"tooltip": "二採噪聲表。連接 BasicScheduler (建議 beta 3步, denoise 0.25)。"}),
                "upscale_model": ("UPSCALE_MODEL", {"tooltip": "可選像素放大模型（如 RealESRGAN）。"}),
            },
        }

    RETURN_TYPES = (MMX_DIR_REFINE, "INT", "INT")
    RETURN_NAMES = ("refine", "target_width", "target_height")
    FUNCTION = "pack"
    CATEGORY = _CATEGORY

    def pack(
        self,
        enable_refine=False,
        mode="upscale",
        upscale_method="mmh3_split_upscale",
        latent_upscale_model="minimax_h3_latent_upscaler_3d_fp16.safetensors",
        sampler=DEFAULT_REFINE_SIGMA_SAMPLER,
        passes=1,
        refine_model=None,
        sigmas=None,
        seed_mode="inherit",
        aspect_ratio=FOLLOW_DIRECTOR_ASPECT,
        megapixels=DEFAULT_UPSCALE_MEGAPIXELS,
        width=1280,
        height=720,
        skip_fl2v=True,
        upscale_model=None,
        temporal_split_param=None,
        spatial_split_param=None,
        **kwargs,
    ):
        if not enable_refine:
            return (None, 0, 0)

        config = pack_refine_config(
            mode=mode,
            upscale_method=upscale_method,
            latent_upscale_model=latent_upscale_model,
            sampler=sampler,
            passes=passes,
            seed_mode=seed_mode,
            aspect_ratio=aspect_ratio,
            megapixels=megapixels,
            width=width,
            height=height,
            skip_fl2v=skip_fl2v,
            refine_model=refine_model,
            sigmas=sigmas,
            upscale_model=upscale_model,
            temporal_split_param=temporal_split_param,
            spatial_split_param=spatial_split_param,
        )
        return (config, config.get("target_width", width), config.get("target_height", height))
