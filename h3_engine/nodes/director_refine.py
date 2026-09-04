"""Graph packer: Refine / upscale config for MiniMax H3 Director.refine."""

from __future__ import annotations

import comfy.samplers

from ..director.h3_latent_upscale import list_h3_latent_upscale_models
from ..director.refine_pack import (
    ASPECT_RATIO_CHOICES,
    DEFAULT_REFINE_SIGMA_SAMPLER,
    DEFAULT_UPSCALE_MEGAPIXELS,
    FOLLOW_DIRECTOR_ASPECT,
    MAX_REFINE_PASSES,
    MMX_DIR_REFINE,
    REFINE_MODES,
    SEED_MODES,
    UPSCALE_METHODS,
    infer_upscale_target,
    pack_refine,
)

_CATEGORY = "MiniMaxH3"


class MiniMaxH3DirectorRefine:
    """Pack refine/upscale settings. Connect ``refine`` to Director.refine.

    ``refine``: same-resolution second sample.
    ``upscale``: enlarge to target canvas then second-sample.
    ``latent_upscale``: H3 latent enlarge only, no second sample.
    Second sample uses SIGMAS from BasicScheduler / ManualSigmas.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (
                    list(REFINE_MODES),
                    {
                        "default": "refine",
                        "tooltip": (
                            "refine = 同分辨率二採（精修）。"
                            "upscale = 先放大到目標畫布再二採。"
                            "latent_upscale = 只放大 H3 latent，不再二採。"
                        ),
                    },
                ),
                "upscale_method": (
                    list(UPSCALE_METHODS),
                    {
                        "default": "h3_latent",
                        "tooltip": (
                            "僅 mode=upscale。"
                            "h3_latent = 先按目標畫布放大 H3 影片 latent，再二採"
                            "（下方選 3D 權重）。"
                            "lanczos = 像素插值；可另接 upscale_model（RealESRGAN 等）。"
                            "nvidia_rtx_vsr = NVIDIA RTX Video Super Resolution"
                            "（需 nvidia-vfx + NVIDIA GPU）。"
                        ),
                    },
                ),
                "latent_upscale_model": (
                    list_h3_latent_upscale_models(),
                    {
                        "tooltip": (
                            "H3 3D latent 放大權重。"
                            "放到 ComfyUI/models/latent_upscale_models/，"
                            "文件名含 3d（如 minimax_h3_latent_upscaler_3d_*.safetensors）。"
                            "mode=latent_upscale，或 upscale + h3_latent 時使用。"
                        ),
                    },
                ),
                "sampler": (
                    comfy.samplers.KSampler.SAMPLERS,
                    {
                        "default": DEFAULT_REFINE_SIGMA_SAMPLER,
                        "tooltip": (
                            "二採采樣器。海螺案例用 euler；"
                            "BasicScheduler 高質量二採常用 res_multistep。"
                        ),
                    },
                ),
                "passes": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": MAX_REFINE_PASSES,
                        "tooltip": (
                            "精修次數。1 = 一次二採。"
                            "upscale 時只有第 1 次放大，之後都是同分辨率精修。"
                            "latent_upscale 不二採，此值無效。"
                        ),
                    },
                ),
            },
            "optional": {
                "refine_model": (
                    "MODEL",
                    {
                        "tooltip": (
                            "Second-pass UNET (二採模型)。"
                            "不接則用導演臺主模型。"
                            "適合一採掛 Turbo LoRA、二採卸掉或換另一套。"
                        ),
                    },
                ),
                "sigmas": (
                    "SIGMAS",
                    {
                        "forceInput": True,
                        "tooltip": (
                            "二採雜訊表。接 Comfy 內建 BasicScheduler 或 ManualSigmas。"
                            "mode=refine / upscale 時必須接線。"
                            "BasicScheduler 請接和二採相同的 MODEL（導演臺主模型或 refine_model）。"
                            "H3 的 SigmaShift 仍由 Refine 內部套上。"
                        ),
                    },
                ),
                "upscale_model": (
                    "UPSCALE_MODEL",
                    {
                        "tooltip": (
                            "可選。用「加載放大模型」接入，例如 RealESRGAN_x2plus。"
                            "僅 mode=upscale 且 upscale_method=lanczos 時使用。"
                            "不接則純 lanczos 插值。選 nvidia_rtx_vsr / h3_latent 時忽略此口。"
                        ),
                    },
                ),
                "seed_mode": (
                    list(SEED_MODES),
                    {
                        "default": "inherit",
                        "tooltip": "inherit = 用導演臺 seed；offset = 每輪 seed+1、+2…。",
                    },
                ),
                "aspect_ratio": (
                    list(ASPECT_RATIO_CHOICES),
                    {
                        "default": FOLLOW_DIRECTOR_ASPECT,
                        "tooltip": (
                            "放大目標畫布，算法同導演臺「輸出分辨率」。"
                            "導演臺是一採分辨率（例如 0.4 MP），這裏是放大後的目標"
                            "（例如 1.0 MP）。跟隨導演臺：按導演臺畫布比例推 720P 檔。"
                            "比例預設：配合百萬像素。"
                            "自定義：直接填寬高（對齊 ×32）。"
                        ),
                    },
                ),
                "megapixels": (
                    "FLOAT",
                    {
                        "default": DEFAULT_UPSCALE_MEGAPIXELS,
                        "min": 0.0,
                        "max": 16.0,
                        "step": 0.1,
                        "tooltip": (
                            "百萬像素，同導演臺 ResolutionSelector。"
                            "1.0 MP 在 16:9 約爲 1376×768（對齊 32）。僅比例預設時生效。"
                        ),
                    },
                ),
                "width": (
                    "INT",
                    {
                        "default": 1280,
                        "min": 0,
                        "max": 8192,
                        "step": 32,
                        "tooltip": "自定義寬度（×32）。僅「自定義」時生效。",
                    },
                ),
                "height": (
                    "INT",
                    {
                        "default": 720,
                        "min": 0,
                        "max": 8192,
                        "step": 32,
                        "tooltip": "自定義高度（×32）。僅「自定義」時生效。",
                    },
                ),
                "skip_fl2v": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": (
                            "跳過首尾影格（fl2v）鏡頭的二採/放大。"
                            "二採會改畫面，容易把釘死的首尾影格畫飄；默認跳過以保護關鍵影格。"
                            "關掉則 fl2v 也走精修 / latent 放大。"
                        ),
                    },
                ),
                "confirm_first_pass": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": (
                            "先確認一採再二採。默認關：一採完立刻二採（與現在相同）。"
                            "開：沒有一採快取時只跑一採並寫出快取/_pre.mp4；"
                            "已有精確匹配的一採快取（同一 seed 及一採參數）則跳過一採只跑二採。"
                            "seed 請用 fixed，或第二次 Queue 前改回寫出快取時的 seed。"
                        ),
                    },
                ),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, input_types=None, **_kwargs):
        # Skip combo/min checks so old workflows (target_width=0 → aspect_ratio) can load.
        return True

    RETURN_TYPES = (MMX_DIR_REFINE, "INT", "INT")
    RETURN_NAMES = ("refine", "width", "height")
    FUNCTION = "pack"
    CATEGORY = _CATEGORY
    DESCRIPTION = (
        "MiniMax H3 Director Refine: connect to Director.refine. "
        "Director.images is the refined / upscaled result; "
        "Director.images_pre_refine is the first-pass video (before second sample). "
        "Second sample uses SIGMAS from BasicScheduler / ManualSigmas. "
        "Upscale / latent_upscale canvas uses the same aspect + megapixels / custom W×H as Director. "
        "Director first-pass stays at its own resolution; Refine target is the enlarge size. "
        "width / height are the resolved target canvas (×32). "
        "Does not sample by itself — no IMAGE output. "
        "confirm_first_pass: first Queue writes first-pass cache; "
        "second Queue with the same seed runs refine only."
    )

    def pack(
        self,
        mode="refine",
        upscale_method="h3_latent",
        sampler="",
        passes=1,
        seed_mode="inherit",
        aspect_ratio=FOLLOW_DIRECTOR_ASPECT,
        megapixels=DEFAULT_UPSCALE_MEGAPIXELS,
        width=1280,
        height=720,
        skip_fl2v=True,
        confirm_first_pass=False,
        latent_upscale_model=None,
        upscale_model=None,
        h3_latent_model="",
        sigmas=None,
        refine_model=None,
        model=None,
        target_width=0,
        target_height=0,
        **kwargs,
    ):
        del kwargs
        try:
            mp = float(megapixels)
        except (TypeError, ValueError):
            mp = DEFAULT_UPSCALE_MEGAPIXELS
        if mp < 0.1:
            mp = DEFAULT_UPSCALE_MEGAPIXELS
        try:
            w = int(width or 0)
        except (TypeError, ValueError):
            w = 1280
        try:
            h = int(height or 0)
        except (TypeError, ValueError):
            h = 720
        if w < 32:
            w = 1280
        if h < 32:
            h = 720
        try:
            n_passes = int(passes or 1)
        except (TypeError, ValueError):
            n_passes = 1
        if n_passes < 1:
            n_passes = 1
        pack = pack_refine(
            mode=mode,
            passes=n_passes,
            seed_mode=seed_mode,
            aspect_ratio=aspect_ratio,
            megapixels=mp,
            width=w,
            height=h,
            target_width=target_width,
            target_height=target_height,
            skip_fl2v=skip_fl2v,
            confirm_first_pass=bool(confirm_first_pass),
            upscale_method=upscale_method,
            sample_model=refine_model if refine_model is not None else model,
            latent_upscale_model=latent_upscale_model if latent_upscale_model is not None else h3_latent_model,
            upscale_model=upscale_model,
            sampler=sampler,
            sigmas=sigmas,
        )
        out_w = int(pack.get("target_width") or 0)
        out_h = int(pack.get("target_height") or 0)
        if out_w <= 0 or out_h <= 0:
            out_w, out_h = infer_upscale_target(0, 0)
        return (pack, int(out_w), int(out_h))
