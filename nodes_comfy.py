# -*- coding: utf-8 -*-
"""ComfyUI Custom Node wrappers for Ultimate Director.
Unified Director Node Suite combining:
1. LLM Story Engine (scoped GGUF zero-VRAM purge)
2. H3 Prompt Enhancer (VLM / GGUF / Calliope 6-section template + smart post-processing)
3. H3 Refine & 3D Latent Upscaler Controller
4. Multimodal Studio Director (Dual-mode Storyboard & Reference Timeline)
5. Storyboard Grid Splitter (2x2, 3x2, 3x3)
6. Motion Context Continuity & SCAIL Locks
"""
from __future__ import annotations

import json
import os
import re
import logging
from typing import Any, Dict, List, Tuple, Optional
import torch
import folder_paths

log = logging.getLogger("UltimateDirector.nodes_comfy")

from .lattice import VideoModel, snap_up
from .timeline import Timeline
from .compile import compile_timeline, CompiledPrompt
from .story_engine import StoryEngine, find_llama_server_bin
from .continuity import apply_scail_lock, trim_decoded_segment
from .grid_splitter import UltimateDirectorStoryboardGridNode, UltimateDirectorCharacterSheetSplitterNode
from .motion_context import UltimateDirectorMotionHandoffNode, UltimateDirectorMotionTrimNode
from .pipeline_switch import (
    UltimateDirectorPipelineSwitchNode,
    UltimateDirectorBranchGateNode,
    UltimateDirectorAssetBridgeNode,
)
from .prompt_enhancer import (
    H3_VLM_SYSTEM_PROMPT,
    VISION_PRESETS,
    build_calliope_ref_fallback,
    run_vlm_generate,
    validate_and_repair_prompt,
)
from .refine_controller import UltimateDirectorRefineNode
from .multimodal_director import UltimateDirectorMultimodalDirector, UltimateDirectorMediaDashboardNode
from .cast_iterator import UltimateDirectorCastIteratorNode
from .auto_cast_generator import UltimateDirectorAutoCastBatchGenerator
from .video_combine import UltimateDirectorVideoCombine
from .text_display import UltimateDirectorTextDisplay
from .compat_nodes import MiniMaxH3MemoryEfficientSageAttentionPatch, ModelPreviewOverrideKJ

# Native H3 Cinema Director Engine (Embedded & Self-Contained)
from .h3_engine.nodes.director import MiniMaxH3Director
from .h3_engine.nodes.director_refine import MiniMaxH3DirectorRefine
from .h3_engine.nodes.conditioning import (
    MiniMaxH3DirectorConditioning,
    MiniMaxH3DirectorPlannerConditioning,
)
from .h3_engine.nodes.director_groups import (
    MiniMaxH3DirectorGroupImageToVideo,
    MiniMaxH3DirectorGroupReferenceToVideo,
    MiniMaxH3DirectorGroupsCombine,
)



# Supported models
SUPPORTED_MODELS = [m.value for m in VideoModel]

KNOWN_LLM_DIRS = [
    "/media/sam/data/llm",
    os.path.join(folder_paths.models_dir, "LLM"),
    os.path.join(folder_paths.models_dir, "text_encoders"),
    folder_paths.models_dir,
]


def scan_gguf_models():
    models = []
    for directory in KNOWN_LLM_DIRS:
        if os.path.exists(directory):
            try:
                for root, _, files in os.walk(directory):
                    for file in files:
                        if file.lower().endswith(".gguf") and not file.lower().startswith("mmproj"):
                            full_path = os.path.join(root, file)
                            if full_path not in models:
                                models.append(full_path)
            except Exception:
                pass
    if not models:
        models.append("/media/sam/data/ComfyUI/models/LLM/Ornith-1.5-35B-Q4_K_M.gguf")
    return models


class UltimateDirectorStoryEngineNode:
    """Spawns a scoped llama-server subprocess (auto start/stop, --cpu-moe aware) to
    generate a timeline JSON, Krea2 asset prompts, and YUAN format. VRAM is guaranteed
    to be released before this node returns, so downstream Krea2 / MiniMax H3 nodes
    have the full VRAM back."""

    @classmethod
    def INPUT_TYPES(cls):
        models = scan_gguf_models()
        return {
            "required": {
                "llm_model": (models, {"default": models[0] if models else "", "tooltip": "選擇本地 GGUF 模型（如 Ornith-1.5-35B-Q4_K_M 或 Qwen3.6-35B）。"}),
                "story_idea": ("STRING", {
                    "multiline": True,
                    "default": "在秋日的皇家獵場上，永安帝率領皇子公主秋獵，卻在射擊白鹿之際突然中毒墜馬。九公主發現藥渣中的西域毒引，三人暗中結盟誓要查明真相...",
                    "tooltip": "故事梗概或小說原文。"
                }),
                "genre": ([
                    "Auto (自動智能研判故事風格與題材)",
                    "東方神魔玄幻 (Eastern Myth & Fantasy)",
                    "古代戰場史詩 (Ancient Epic Battlefield)",
                    "賽博龐克科幻 (Cyberpunk Sci-Fi Action)",
                    "極簡商業廣告 (Apple Minimalist Commercial)",
                    "現代都市懸疑 (Modern Crime & Suspense)",
                    "武俠江湖對決 (Wuxia Martial Arts Duel)",
                    "奇幻冒險史詩 (Western High Fantasy)",
                    "都市愛情/青春治癒",
                    "街頭快閃/歌舞藝術",
                    "現代日常/都市文藝",
                    "古裝權謀",
                    "科幻末日",
                    "中式驚悚"
                ], {"default": "Auto (自動智能研判故事風格與題材)", "tooltip": "選擇故事風格或設為 Auto 由劇本大腦根據故事梗概自動判定。"}),
                "scene_count": ("INT", {"default": 6, "min": 1, "max": 30, "step": 1}),
                "cpu_moe_all": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "啟動 llama-server 時加上 --cpu-moe：把 MoE 專家權重放到系統 RAM，只留 attention 在 GPU。低顯存環境建議保持開啟。"
                }),
                "n_gpu_layers": ("INT", {
                    "default": 999, "min": 0, "max": 999,
                    "tooltip": "GPU 卸載層數。"
                }),
                "n_ctx": ("INT", {"default": 16384, "min": 2048, "max": 65536, "step": 1024}),
                "temperature": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 1.5, "step": 0.05}),
                "ignore_manual_images": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "若開啟自動生圖，請將此設為 True，讓大腦忽略手動連接的參考圖，避免干擾劇本。"
                }),
            },
            "optional": {
                "assets": ("DIRECTOR_ASSETS", {"tooltip": "由 Media Dashboard 傳入的全局素材庫。"}),
                "custom_skill_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "可選填寫或連線外部導演技能心法（Skills）。大腦會將這些專業導演/攝影/提示詞規則與要求深度融入劇本與資產提示詞中！"
                }),
                "ref_image_1": ("IMAGE", {"tooltip": "主體 1 參考圖片（主角）。35B 視覺多模態大腦將親眼審視真實性別、年貌、五官、髮型與氣質，拒絕任何硬編碼！"}),
                "ref_image_2": ("IMAGE", {"tooltip": "主體 2 參考圖片（坐騎/載具/副角/核心道具）。視覺大腦將自動看圖提取外觀特徵！"}),
                "ref_image_3": ("IMAGE", {"tooltip": "主體 3 參考圖片。"}),
                "ref_image_4": ("IMAGE", {"tooltip": "主體 4 參考圖片。"}),
                "ref_image_5": ("IMAGE", {"tooltip": "主體 5 參考圖片。"}),
                "ref_image_6": ("IMAGE", {"tooltip": "主體 6 參考圖片。"}),
                "ref_image_7": ("IMAGE", {"tooltip": "主體 7 參考圖片。"}),
                "ref_image_8": ("IMAGE", {"tooltip": "主體 8 參考圖片。"}),
                "ref_image_9": ("IMAGE", {"tooltip": "主體 9 參考圖片。"}),
                "ref_image": ("IMAGE", {"tooltip": "單張參考圖輸入（向下相容別名）。"}),
                "custom_genre": ("STRING", {"default": "", "tooltip": "可選自訂風格（例如：台北101街頭快閃、日系清新、王家衛風）。若填寫則優先覆蓋題材選擇。"}),
                "custom_model_file": ("STRING", {"default": "", "tooltip": "自訂 GGUF 絕對路徑。"}),
                "server_bin": ("STRING", {
                    "default": find_llama_server_bin(),
                    "tooltip": "llama-server 執行檔的絕對路徑。"
                }),
                "server_port": ("INT", {
                    "default": 8099, "min": 1024, "max": 65535,
                    "tooltip": "子行程 llama-server 監聽的 port。"
                }),
            }
        }

    RETURN_TYPES = ("TIMELINE_DICT", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("timeline", "krea2_char_prompt", "krea2_scene_prompt", "yuan_json_output", "script_preview")
    FUNCTION = "generate"
    CATEGORY = "UltimateDirector/Story"

    def generate(
        self,
        llm_model: str,
        story_idea: str,
        genre: str,
        scene_count: int,
        cpu_moe_all: bool,
        n_gpu_layers: int,
        n_ctx: int,
        temperature: float,
        ignore_manual_images: bool = False,
        custom_skill_prompt: str = "",
        assets: dict = None,
        **kwargs
    ):
        if assets is None:
            assets = {"images": {}, "videos": {}, "audios": {}}

        ref_image_1 = kwargs.get("ref_image_1", None)
        ref_image_1 = ref_image_1 if ref_image_1 is not None else assets["images"].get("ref_image_1")
        ref_image_2 = kwargs.get("ref_image_2", None)
        ref_image_2 = ref_image_2 if ref_image_2 is not None else assets["images"].get("ref_image_2")
        ref_image = kwargs.get("ref_image", None)
        
        ref_images = [
            ref_image_1 if ref_image_1 is not None else ref_image,
            ref_image_2,
            kwargs.get("ref_image_3", assets["images"].get("ref_image_3")),
            kwargs.get("ref_image_4", assets["images"].get("ref_image_4")),
            kwargs.get("ref_image_5", assets["images"].get("ref_image_5")),
            kwargs.get("ref_image_6", assets["images"].get("ref_image_6")),
            kwargs.get("ref_image_7", assets["images"].get("ref_image_7")),
            kwargs.get("ref_image_8", assets["images"].get("ref_image_8")),
            kwargs.get("ref_image_9", assets["images"].get("ref_image_9")),
        ]
        
        custom_genre = kwargs.get("custom_genre", "")
        custom_model_file = kwargs.get("custom_model_file", "")
        server_bin = kwargs.get("server_bin", "")
        server_port = kwargs.get("server_port", 8099)

        if ignore_manual_images:
            ref_images = [None] * 9

        model_path = custom_model_file.strip() if custom_model_file.strip() else llm_model
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"找不到 GGUF 模型檔案: {model_path}")

        bin_path = server_bin.strip() if server_bin.strip() else find_llama_server_bin()

        # Resolve genre: custom_genre > combo selection
        resolved_genre = custom_genre.strip() if custom_genre.strip() else genre
        if resolved_genre.startswith("Auto"):
            resolved_genre = "由劇本大腦根據故事梗概智能自動判斷最適影視題材風格"

        engine = StoryEngine(
            model_path=model_path,
            server_bin=bin_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            cpu_moe_all=cpu_moe_all,
            port=server_port,
        )
        timeline_dict, krea_char, krea_scene, yuan_json, preview = engine.generate_timeline(
            idea=story_idea,
            genre=resolved_genre,
            scene_count=scene_count,
            temperature=temperature,
            ref_images=ref_images,
            custom_skill_prompt=custom_skill_prompt,
        )
        return (timeline_dict, krea_char, krea_scene, yuan_json, preview)



class UltimateDirectorPromptEnhancerNode:
    """Prompt Enhancer Node for MiniMax H3.
    Combines:
    - VLM Vision Analysis (Qwen3-VL native CLIP text generation)
    - GGUF LLM Rewrite (Scoped llama-server)
    - Calliope 6-Section Ref2VA Deterministic Template
    - Smart Post-Processor (Sanitize, Mode Alignment, 7000-char smart trim, soundscape auto-repair)
    """

    @classmethod
    def INPUT_TYPES(cls):
        models = scan_gguf_models()
        return {
            "required": {
                "user_idea": ("STRING", {
                    "multiline": True,
                    "default": "一位身穿深藍絲質刺繡旗袍的年輕女子，手持香檳杯站在夜景露台，緩慢轉頭看向鏡頭，眼神克制曖昧。",
                    "tooltip": "原始提示詞或影片動作設想。"
                }),
                "task_type": (["Auto", "Ref2VA", "I2VA", "FL2VA", "L2VA", "T2VA"], {"default": "Auto"}),
                "enhance_engine": ([
                    "calliope_deterministic (零顯存確定性模板)",
                    "vlm_native (ComfyUI 原生 Qwen3-VL 看圖)",
                    "gguf_llama_server (本地 GGUF 改寫)",
                ], {"default": "calliope_deterministic (零顯存確定性模板)"}),
                "vision_preset": (list(VISION_PRESETS.keys()) + ["skip"], {"default": "detailed_subject_scene"}),
                "duration": ("FLOAT", {"default": 6.0, "min": 4.0, "max": 15.0, "step": 0.1}),
                "seed": ("INT", {"default": 42, "min": 0, "max": 0xffffffffffffffff}),
                "temperature": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 1.5, "step": 0.05}),
            },
            "optional": {
                "clip": ("CLIP", {"tooltip": "可選連接 Qwen3-VL 文本編碼器（用於 vlm_native 模式）。"}),
                "image_1": ("IMAGE", {"tooltip": "參考圖 1 (<Picture 1>)"}),
                "image_2": ("IMAGE", {"tooltip": "參考圖 2 (<Picture 2>)"}),
                "image_3": ("IMAGE", {"tooltip": "參考圖 3 (<Picture 3>)"}),
                "image_4": ("IMAGE", {"tooltip": "參考圖 4 (<Picture 4>)"}),
                "gguf_model": (models, {"default": models[0] if models else "", "tooltip": "GGUF 大語言模型路徑。"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("enhanced_prompt", "vision_context", "debug_report")
    FUNCTION = "enhance"
    CATEGORY = "UltimateDirector/Prompt"

    def enhance(
        self,
        user_idea: str,
        task_type: str,
        enhance_engine: str,
        vision_preset: str,
        duration: float,
        seed: int,
        temperature: float,
        clip=None,
        image_1=None,
        image_2=None,
        image_3=None,
        image_4=None,
        gguf_model="",
    ):
        # Collect available images
        images = [img for img in (image_1, image_2, image_3, image_4) if img is not None]
        n_images = len(images)

        # Resolve task type
        resolved_task = task_type
        if resolved_task == "Auto":
            if n_images == 0:
                resolved_task = "T2VA"
            elif n_images == 1:
                resolved_task = "I2VA"
            elif n_images == 2:
                resolved_task = "FL2VA"
            else:
                resolved_task = "Ref2VA"

        vision_context = ""
        raw_prompt = ""

        # Engine 1: Native VLM
        if "vlm_native" in enhance_engine and clip is not None:
            combined_tensor = torch.cat(images, dim=0) if images else None
            user_prompt = f"Task: {resolved_task}\nDuration: {duration:.2f}s\nUser Idea: {user_idea}"
            if vision_preset != "skip" and vision_preset in VISION_PRESETS:
                user_prompt += f"\nVision Analysis Instruction: {VISION_PRESETS[vision_preset]}"

            raw_prompt = run_vlm_generate(
                clip=clip,
                system_prompt=H3_VLM_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                image_tensor=combined_tensor,
                seed=seed,
                temperature=temperature,
            )
            vision_context = f"VLM generated for {n_images} images."

        # Engine 2: GGUF LLM Server
        elif "gguf_llama_server" in enhance_engine and gguf_model and os.path.exists(gguf_model):
            engine = StoryEngine(
                model_path=gguf_model,
                server_bin=find_llama_server_bin(),
                n_ctx=8192,
                n_gpu_layers=999,
                cpu_moe_all=True,
            )
            prompt_req = (
                f"Please write a complete MiniMax H3 {resolved_task} prompt for a {duration:.2f}s scene based on: {user_idea}\n"
                f"Make sure to include exact camera movement, rich action, dialogue tags, overall_soundscape, and non_diegetic_music."
            )
            raw_prompt = engine._call_llm(
                system_prompt=H3_VLM_SYSTEM_PROMPT,
                user_prompt=prompt_req,
                temperature=temperature,
            )
            vision_context = "GGUF LLM rewritten prompt."

        # Engine 3: Deterministic Calliope Template (zero VRAM)
        else:
            subjects = [{"name": f"Subject {i}", "appearance": f"Visual entity referenced from Picture {i}"} for i in range(1, max(1, n_images + 1))]
            raw_prompt = build_calliope_ref_fallback(idea=user_idea, subjects=subjects, duration=duration)
            vision_context = "Calliope 6-section deterministic template used."

        # Post-Processing: sanitize, align, trim, and auto-repair audio fields
        final_prompt, warnings = validate_and_repair_prompt(raw_prompt, resolved_task, duration)

        debug = {
            "resolved_task": resolved_task,
            "engine": enhance_engine,
            "input_images": n_images,
            "duration": duration,
            "char_count": len(final_prompt),
            "warnings": warnings,
        }

        return (final_prompt, vision_context, json.dumps(debug, ensure_ascii=False, indent=2))


class UltimateDirectorCompilerNode:
    """Compiles a Timeline JSON into a list of SegmentPrompts for the generator."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "timeline": ("TIMELINE_DICT",),
                "model_type": (SUPPORTED_MODELS, {"default": VideoModel.H3.value}),
                "continuity_overlap_frames": ("INT", {"default": 22, "min": 0, "max": 56}),
            }
        }

    RETURN_TYPES = ("SEGMENT_LIST", "STRING")
    RETURN_NAMES = ("segments", "h3_compiled_prompt")
    FUNCTION = "compile"
    CATEGORY = "UltimateDirector/Compiler"

    def compile(self, timeline, model_type, continuity_overlap_frames):
        tl = Timeline.from_dict(timeline)
        compiled_prompt = compile_timeline(timeline=tl, first_frame=True, last_frame=False)
        compiled_segs = compile_timeline(timeline=tl, first_frame=True, last_frame=False)
        return (compiled_segs, str(compiled_prompt))


class UltimateDirectorSCAILLockNode:
    """Applies SCAIL (Segment Continuity and Image Locking) to the VAE encoded prefix."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "latent": ("LATENT",),
                "tail_latent": ("LATENT",),
                "overlap_pixel_frames": ("INT", {"default": 9, "min": 1, "max": 30}),
                "model_type": (SUPPORTED_MODELS, {"default": VideoModel.H3.value}),
            }
        }

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("locked_latent",)
    FUNCTION = "apply_lock"
    CATEGORY = "UltimateDirector/Continuity"

    def apply_lock(self, latent, tail_latent, overlap_pixel_frames, model_type):
        model = VideoModel(model_type)
        tail_tensor = tail_latent["samples"]
        out_latent, _ = apply_scail_lock(
            latent=latent,
            tail_latent=tail_tensor,
            overlap_pixel_frames=overlap_pixel_frames,
            model=model
        )
        return (out_latent,)


class UltimateDirectorSCAILTrimNode:
    """Trims the overlap and settling frames from the decoded video output."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "decoded_images": ("IMAGE",),
                "prefix_trim": ("INT", {"default": 0}),
                "target_len": ("INT", {"default": 0}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("trimmed_images",)
    FUNCTION = "trim"
    CATEGORY = "UltimateDirector/Continuity"

    def trim(self, decoded_images, prefix_trim, target_len):
        trimmed = trim_decoded_segment(
            decoded=decoded_images,
            prefix_trim=prefix_trim,
            target_len=target_len
        )
        return (trimmed,)


def _align_to_h3_grid(duration_sec: float, fps: int = 24) -> Tuple[int, float]:
    """Align duration to nearest 17k+5 frame grid for MiniMax H3 (minimum 124 frames ~ 5.16s)."""
    raw_frames = max(124, round(duration_sec * fps))
    lo = raw_frames - ((raw_frames - 5) % 17)
    hi = lo + 17
    best_frames = lo if (raw_frames - lo) <= (hi - raw_frames) else hi
    best_frames = max(124, best_frames)
    actual_sec = best_frames / fps
    return best_frames, actual_sec


def _extract_clean_shot_components(raw_prompt: str, default_soundscape: str = "") -> Tuple[str, str, str, str, str, str]:
    """Parses out the pure visual summary, pure detailed action, soundscape, and non-diegetic music from raw_prompt,
    eliminating any duplicate or nested DY section headers.
    """
    text = raw_prompt.strip()
    summary = ""
    detail = ""
    soundscape = default_soundscape.strip() if default_soundscape else ""
    bgm = ""
    parsed_subj = ""
    parsed_ret = ""

    # Check for official English / Traditional / Simplified keys
    if "detailed_description:" in text.lower() or "detailed_description：" in text.lower():
        match_subj = re.search(r"(?:subject_definition|DY\.subject_definitions|subject_definitions)[:：](.*?)(?=(?:overview|summary|摘要)[:：]|$)", text, re.DOTALL | re.IGNORECASE)
        if match_subj:
            parsed_subj = match_subj.group(1).strip()
            
        match_ret = re.search(r"(?:retention_analysis)[:：](.*?)(?=(?:detailed_description|詳細描述|详细描述)[:：]|$)", text, re.DOTALL | re.IGNORECASE)
        if match_ret:
            parsed_ret = match_ret.group(1).strip()

        match_detail = re.search(r"detailed_description[:：](.*?)(?:overall_soundscape[:：]|non_diegetic_music[:：]|$)", text, re.DOTALL | re.IGNORECASE)
        if match_detail:
            detail = match_detail.group(1).strip()
        match_summary = re.search(r"(?:overview|summary)[:：](.*?)(?:retention_analysis[:：]|detailed_description[:：]|$)", text, re.DOTALL | re.IGNORECASE)
        if match_summary:
            summary = match_summary.group(1).strip()
        match_sound = re.search(r"overall_soundscape[:：](.*?)(?:non_diegetic_music[:：]|$)", text, re.DOTALL | re.IGNORECASE)
        if match_sound:
            soundscape = match_sound.group(1).strip()
        match_bgm = re.search(r"non_diegetic_music[:：](.*?)$", text, re.DOTALL | re.IGNORECASE)
        if match_bgm:
            bgm = match_bgm.group(1).strip()
    elif "詳細描述:" in text or "詳細描述：" in text or "详细描述:" in text or "详细描述：" in text:
        parts = re.split(r"(?:詳細描述|详细描述)[:：]", text)
        pre = parts[0]
        post = parts[1]

        if "整體聲景:" in post or "整體聲景：" in post or "整体声景:" in post or "整体声景：" in post:
            d_parts = re.split(r"(?:整體聲景|整体声景)[:：]", post)
            detail = d_parts[0].strip()
            soundscape = d_parts[1].strip()
        elif "overall_soundscape:" in post.lower():
            d_parts = re.split(r"overall_soundscape[:：]", post, flags=re.IGNORECASE)
            detail = d_parts[0].strip()
            soundscape = d_parts[1].strip()
        else:
            detail = post.strip()

        if "摘要:" in pre or "摘要：" in pre:
            s_parts = re.split(r"摘要[:：]", pre)
            summary = s_parts[1].strip()
    else:
        detail = text

    # Strip residual metadata
    summary = re.sub(r"^\[reference generation\]\s*\d+-\d+(?:\.\d+)?s[，,\s]*", "", summary).strip()
    detail = re.sub(r"^\[Shot\s*\d+[^\]]*\]\s*", "", detail).strip()
    summary = re.sub(r"^(?:subject_definition|DY\.subject_definitions|主體定義|主体定义)[:：].*?(?=(?:overview|summary|摘要)[:：]|$)", "", summary, flags=re.DOTALL | re.IGNORECASE).strip()
    detail = re.sub(r"^(?:subject_definition|DY\.subject_definitions|主體定義|主体定义)[:：].*?(?=(?:detailed_description|詳細描述|详细描述)[:：]|$)", "", detail, flags=re.DOTALL | re.IGNORECASE).strip()

    if not detail:
        detail = summary if summary else text
    if not summary:
        summary = detail
    if not soundscape:
        soundscape = default_soundscape or "Realistic environmental ambient audio, sharp synchronized action sound effects."

    return summary, detail, soundscape, bgm, parsed_subj, parsed_ret


class UltimateDirectorTimelineToR2VGroupsNode:
    """Dynamically compiles StoryEngine's timeline JSON and AutoCastBatchGenerator's reference images
    into a native list of MiniMax H3 MMX_DIR_GROUP objects with official DY.subject_definitions format.
    Enhanced with MiniMax-H3-Longvideos features: Dialogue Audio Silencing Guard, 17k+5 Grid Lock & Seamless Handoff.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "timeline_or_json": ("TIMELINE_DICT", {
                    "forceInput": True,
                    "tooltip": "StoryEngine 輸出的 timeline (TIMELINE_DICT) 或 JSON 字串。"
                }),
                "render_shots": ([
                    "第 1 鏡頭打樣 (Shot 1 Only - 3分鐘極速驗光)",
                    "全部 6 鏡頭 (All Shots - 完整電影成片)",
                    "前 2 鏡頭 (Shots 1-2)",
                    "前 3 鏡頭 (Shots 1-3)",
                ], {
                    "default": "第 1 鏡頭打樣 (Shot 1 Only - 3分鐘極速驗光)",
                    "tooltip": "🔥 分鏡渲染選擇：選「第 1 鏡頭打樣」只跑第 1 鏡（只需 3 分鐘，秒看角色還原度！）；確認滿意後再切換為「全部 6 鏡頭」渲染完整大片！"
                }),
            },
            "optional": {
                "ref_images": ("IMAGE", {
                    "tooltip": "【模式 A：AI 自動角色生圖】由動態多角色自動生圖器輸入的 all_images。若留空或關閉自動生圖，可直接使用下方自選參考圖！"
                }),
                "override_image_1": ("IMAGE", {"tooltip": "【模式 B：自選立繪 1】自訂主角參考圖 (Node 120)。若有輸入，將優先使用/覆蓋作為 Picture 1！"}),
                "override_image_2": ("IMAGE", {"tooltip": "【模式 B：自選立繪 2】自訂坐騎/配角參考圖 (Node 121)。若有輸入，將優先使用/覆蓋作為 Picture 2！"}),
                "override_image_3": ("IMAGE", {"tooltip": "【模式 B：自選立繪 3】自訂參考圖 3。"}),
                "override_image_4": ("IMAGE", {"tooltip": "【模式 B：自選立繪 4】自訂參考圖 4。"}),
                "override_image_5": ("IMAGE", {"tooltip": "【模式 B：自選立繪 5】自訂參考圖 5。"}),
                "override_image_6": ("IMAGE", {"tooltip": "【模式 B：自選立繪 6】自訂參考圖 6。"}),
                "override_image_7": ("IMAGE", {"tooltip": "【模式 B：自選立繪 7】自訂參考圖 7。"}),
                "override_image_8": ("IMAGE", {"tooltip": "【模式 B：自選立繪 8】自訂參考圖 8。"}),
                "override_image_9": ("IMAGE", {"tooltip": "【模式 B：自選立繪 9】自訂參考圖 9。"}),
                "override_video_1": ("IMAGE", {"tooltip": "自訂影片參考 1（作為 <Video 1>）。"}),
                "override_video_2": ("IMAGE", {"tooltip": "自訂影片參考 2（作為 <Video 2>）。"}),
                "override_video_3": ("VIDEO", {"tooltip": "直接指定第三個參考影片"}),
                "override_video_audio_1": ("AUDIO", {"tooltip": "與 override_video_1 綁定的音訊。"}),
                "override_video_audio_2": ("AUDIO", {"tooltip": "與 override_video_2 綁定的音訊。"}),
                "override_video_audio_3": ("AUDIO", {"tooltip": "與 override_video_3 綁定的音訊。"}),
                "override_audio_1": ("AUDIO", {"tooltip": "自訂純音訊參考 1（作為 <Audio 1>）。"}),
                "override_audio_2": ("AUDIO", {"tooltip": "自訂純音訊參考 2（作為 <Audio 2>）。"}),
                "override_audio_3": ("AUDIO", {"tooltip": "自訂純音訊參考 3（作為 <Audio 3>）。"}),

                "default_duration_sec": ("FLOAT", {
                    "default": 5.5, "min": 1.0, "max": 10.0, "step": 0.1,
                    "tooltip": "當分鏡未指定時長時的預設秒數。"
                }),
                "dialogue_audio_guard": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "對白語法音訊自動靜音保護：當鏡頭無帶引號對白時，自動抑制 AI 隨機喃喃自語，保持純淨環境音。"
                }),
                "align_17k5_grid": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "強制將分鏡時長精確鎖定至 MiniMax H3 原生 17k+5 幀時序網格（確保音畫完全同步）。"
                }),
                "continuous_take_handoff": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "啟用長視頻首尾幀連續鏈路標記（供段間尾幀銜接使用）。"
                }),
                "manual_prompt_override": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "【手動精修分鏡提示詞 (可選)】：在此貼上或手動修改提示詞，將直接覆蓋鏡頭的描述！留空則完全遵循大腦自動生成的提示詞。"
                }),
                "assets": ("DIRECTOR_ASSETS", {"tooltip": "由 Media Dashboard 傳入的全局素材庫。"}),
            }
        }

    RETURN_TYPES = ("H3_R2V_GROUPS", "STRING", "INT")
    RETURN_NAMES = ("r2v_groups", "shots_summary", "shot_count")
    FUNCTION = "convert_timeline"
    CATEGORY = "UltimateDirector/Pipeline"

    def convert_timeline(
        self,
        timeline_or_json: Any,
        render_shots: str = "第 1 鏡頭打樣 (Shot 1 Only - 3分鐘極速驗光)",
        ref_images: torch.Tensor | None = None,
        override_image_1: Any = None,
        override_image_2: Any = None,
        override_image_3: Any = None,
        override_image_4: Any = None,
        override_image_5: Any = None,
        override_image_6: Any = None,
        override_image_7: Any = None,
        override_image_8: Any = None,
        override_image_9: Any = None,
        override_video_1: Any = None,
        override_video_2: Any = None,
        override_video_3: Any = None,
        override_video_audio_1: Any = None,
        override_video_audio_2: Any = None,
        override_video_audio_3: Any = None,
        override_audio_1: Any = None,
        override_audio_2: Any = None,
        override_audio_3: Any = None,
        default_duration_sec: float = 5.5,
        dialogue_audio_guard: bool = True,
        align_17k5_grid: bool = True,
        continuous_take_handoff: bool = True,
        manual_prompt_override: str = "",
        assets: dict = None,
        **kwargs
    ):
        from .timeline import Timeline
        import json
        from .cast_iterator import _clean_json_or_dict, _extract_cast_items

        if assets is None:
            assets = {"images": {}, "videos": {}, "audios": {}}

        override_video_1 = override_video_1 if override_video_1 is not None else assets["videos"].get("override_video_1")
        override_video_2 = override_video_2 if override_video_2 is not None else assets["videos"].get("override_video_2")
        override_video_3 = override_video_3 if override_video_3 is not None else assets["videos"].get("override_video_3")
        
        override_image_1 = override_image_1 if override_image_1 is not None else assets["images"].get("ref_image_1")
        override_image_2 = override_image_2 if override_image_2 is not None else assets["images"].get("ref_image_2")
        override_image_3 = override_image_3 if override_image_3 is not None else assets["images"].get("ref_image_3")
        override_image_4 = override_image_4 if override_image_4 is not None else assets["images"].get("ref_image_4")
        override_image_5 = override_image_5 if override_image_5 is not None else assets["images"].get("ref_image_5")
        override_image_6 = override_image_6 if override_image_6 is not None else assets["images"].get("ref_image_6")
        override_image_7 = override_image_7 if override_image_7 is not None else assets["images"].get("ref_image_7")
        override_image_8 = override_image_8 if override_image_8 is not None else assets["images"].get("ref_image_8")
        override_image_9 = override_image_9 if override_image_9 is not None else assets["images"].get("ref_image_9")
        
        override_audio_1 = override_audio_1 if override_audio_1 is not None else assets["audios"].get("override_audio_1")
        override_audio_2 = override_audio_2 if override_audio_2 is not None else assets["audios"].get("override_audio_2")
        override_audio_3 = override_audio_3 if override_audio_3 is not None else assets["audios"].get("override_audio_3")
        override_video_audio_1 = override_video_audio_1 if override_video_audio_1 is not None else assets["audios"].get("override_video_audio_1")
        override_video_audio_2 = override_video_audio_2 if override_video_audio_2 is not None else assets["audios"].get("override_video_audio_2")
        override_video_audio_3 = override_video_audio_3 if override_video_audio_3 is not None else assets["audios"].get("override_video_audio_3")

        data = _clean_json_or_dict(timeline_or_json)
        shots = data.get("shots", [])

        if not isinstance(shots, list) or not shots:
            shots = [{
                "id": "shot_1",
                "title": "全景鏡頭",
                "duration_seconds": default_duration_sec,
                "prompt": data.get("krea2_scene_prompt") or "A cinematic movie scene with natural motion."
            }]

        total_original_shots = len(shots)
        if "第 1 鏡頭" in render_shots or "Shot 1" in render_shots:
            shots = shots[:1]
            log.info("🎯 【單鏡打樣模式啟用】：僅渲染第 1 分鏡（3分鐘極速出片）")
        elif "前 2 鏡頭" in render_shots or "1-2" in render_shots:
            shots = shots[:2]
            log.info("🎯 【前兩鏡模式啟用】：僅渲染前 2 分鏡")
        elif "前 3 鏡頭" in render_shots or "1-3" in render_shots:
            shots = shots[:3]
            log.info("🎯 【前三鏡模式啟用】：僅渲染前 3 分鏡")
        else:
            log.info("🎬 【全劇渲染模式啟用】：編譯全部 %d 個分鏡", len(shots))


        images_dict = {}
        has_auto_gen = False
        if isinstance(ref_images, torch.Tensor) and ref_images.ndim == 4:
            # Ignore dummy placeholder tensors (< 128x128)
            if ref_images.shape[1] >= 128 and ref_images.shape[2] >= 128:
                b_count = min(ref_images.shape[0], 9)
                for b in range(b_count):
                    images_dict[b] = ref_images[b:b+1].clone()
                has_auto_gen = True
                log.info(f"UltimateDirector: 採用 AI 自動角色生圖器產出的 {b_count} 張高清立繪作為主參考圖！")

        # Handle user custom overrides: only apply if auto_gen is OFF
        # (Auto Gen completely isolates from manual images to avoid cross-contamination)
        overrides = [
            override_image_1, override_image_2, override_image_3,
            override_image_4, override_image_5, override_image_6,
            override_image_7, override_image_8, override_image_9
        ]
        
        if not has_auto_gen:
            for o_idx, o_img in enumerate(overrides):
                if o_img is not None and isinstance(o_img, torch.Tensor):
                    images_dict[o_idx] = o_img[0:1].clone() if o_img.ndim == 4 else o_img.unsqueeze(0).clone()
                    log.info(f"已使用自訂參考圖設定 Picture {o_idx+1}")
        else:
            log.info("自動生圖已開啟，手動參考圖將完全忽略以避免污染角色特徵。")

        # Collect videos and audios
        videos_dict = {}
        for idx, vid in enumerate([override_video_1, override_video_2, override_video_3]):
            if vid is not None and isinstance(vid, torch.Tensor):
                videos_dict[idx] = vid.clone()
        
        video_audios_dict = {}
        for idx, vaud in enumerate([override_video_audio_1, override_video_audio_2, override_video_audio_3]):
            if vaud is not None:
                video_audios_dict[idx] = vaud
        
        audios_dict = {}
        for idx, aud in enumerate([override_audio_1, override_audio_2, override_audio_3]):
            if aud is not None:
                audios_dict[idx] = aud

        groups_list = []
        summary_lines = [f"🎬 【動態分鏡編譯清單（共 {len(shots)} 個鏡頭）】："]

        # Support both Ultimate Director 'cast' and Director Canvas 'characters'
        cast_list = data.get("cast") or data.get("characters") or _extract_cast_items(data)
        subject_defs = []
        retention_defs = []

        cast_map = {}
        if isinstance(cast_list, list) and cast_list:
            for c_idx, c_item in enumerate(cast_list[:len(images_dict)]):
                c_name = c_item.get("name") or c_item.get("id") or f"角色{c_idx+1}"
                c_desc = c_item.get("description") or c_item.get("appearance") or c_item.get("krea_prompt") or ""
                cast_map[c_name] = f"<Subject {c_idx+1}> {c_name}"
                if c_item.get("id"):
                    cast_map[str(c_item.get("id"))] = f"<Subject {c_idx+1}> {c_name}"
                
                # Check for anti-beard / anti-aging keywords and apply gender-specific identity locks
                anti_extra = ""
                c_desc_lower = c_desc.lower()
                if any(w in c_desc_lower for w in ["女", "少女", "巾幗", "公主", "female", "woman", "girl", "lady"]):
                    anti_extra = " (female warrior, preserving delicate feminine facial features, youthful beauty, long dark hair, strictly NO beard, NO mustache, NO clone)"
                elif any(w in c_desc_lower for w in ["將軍", "少年", "青年", "無鬍", "英俊", "英挺", "英姿", "帥氣", "男子", "主角"]):
                    anti_extra = " (clean-shaven, strictly NO beard, NO mustache, NO facial hair, pristine smooth skin, NO clone)"

                subject_defs.append(f"<Subject {c_idx+1}> is the {c_name} whose visual identity comes from <Picture {c_idx+1}>, preserving {c_desc}{anti_extra}.")
                retention_defs.append(f"<Subject {c_idx+1}>: fully_preserved - maintaining recognized facial proportions, wardrobe, and texture.")

        for s_idx, shot in enumerate(shots):
            s_id = str(shot.get("id") or f"shot_{s_idx+1}")
            s_title = str(shot.get("title") or shot.get("shot_number") or shot.get("shot_type") or f"鏡頭 {s_idx+1}")
            raw_dur = float(shot.get("duration_seconds") or shot.get("duration") or default_duration_sec)
            
            if align_17k5_grid:
                _, s_dur = _align_to_h3_grid(raw_dur)
            else:
                s_dur = raw_dur

            raw_prompt = str(shot.get("prompt") or shot.get("h3_video_prompt") or shot.get("first_frame_krea_prompt") or "")
            if manual_prompt_override and manual_prompt_override.strip():
                raw_prompt = manual_prompt_override.strip()
                log.info(f"UltimateDirector: 🎯 採用使用者在 Node 110 手動精修之提示詞覆蓋 Shot {s_idx+1}！")
            raw_soundscape = str(shot.get("soundscape") or shot.get("dialogue") or shot.get("audio") or "Realistic environmental ambient audio, sharp synchronized action sound effects.")

            # Clean out nested headers
            c_summary, c_detail, c_soundscape, c_bgm, c_subj, c_ret = _extract_clean_shot_components(raw_prompt, raw_soundscape)

            # Ensure subject tokens are explicitly injected into the shot prompt
            bound_summary = c_summary
            bound_detail = c_detail
            for c_name, subj_tag in cast_map.items():
                if c_name in bound_summary and subj_tag not in bound_summary:
                    bound_summary = bound_summary.replace(c_name, subj_tag)
                if c_name in bound_detail and subj_tag not in bound_detail:
                    bound_detail = bound_detail.replace(c_name, subj_tag)
            
            if "<Subject 1>" not in bound_detail and subject_defs:
                bound_detail = f"<Subject 1> {bound_detail}"
            if "<Subject 1>" not in bound_summary and subject_defs:
                bound_summary = f"<Subject 1> {bound_summary}"

            # MiniMax-H3-Longvideos feature: Dialogue audio guard
            dwc = shot.get("dialogue_word_count", 0)
            has_dwc = False
            try:
                has_dwc = int(dwc) > 0
            except (ValueError, TypeError):
                has_dwc = False

            has_dialogue = bool(
                re.search(r'"[^"]{2,}"', bound_detail)
                or re.search(r'「[^」]{2,}」', bound_detail)
                or re.search(r'\(S\d+\)', bound_detail)
                or has_dwc
            )
            final_soundscape = c_soundscape
            if dialogue_audio_guard and not has_dialogue:
                if "strictly no spoken dialogue" not in final_soundscape.lower():
                    final_soundscape += " (Pure environmental atmosphere, strictly NO spoken dialogue, NO vocal mumbling)."

            # Construct official MiniMax H3 DY.subject_definitions structure
            final_subj_str = c_subj if c_subj else ("\n".join(subject_defs) if subject_defs else "")
            
            # Ensure anti-beard / anti-aging identity locks are injected even if the LLM provided c_subj
            if c_subj and isinstance(cast_list, list):
                for c_idx, c_item in enumerate(cast_list[:len(images_dict)]):
                    c_desc_lower = (c_item.get("description") or c_item.get("appearance") or "").lower()
                    anti_extra = ""
                    if any(w in c_desc_lower for w in ["女", "少女", "巾幗", "公主", "female", "woman", "girl", "lady"]):
                        anti_extra = " (female warrior, preserving delicate feminine facial features, youthful beauty, long dark hair, strictly NO beard, NO mustache, NO clone)"
                    elif any(w in c_desc_lower for w in ["將軍", "少年", "青年", "無鬍", "英俊", "英挺", "英姿", "帥氣", "男子", "主角"]):
                        anti_extra = " (clean-shaven, strictly NO beard, NO mustache, NO facial hair, pristine smooth skin, NO clone)"
                    
                    if anti_extra and "NO beard" not in final_subj_str:
                        # Append anti_extra to the specific picture definition line
                        pattern = re.compile(rf"(<Picture {c_idx+1}> is.*?)(?=\n|$)", re.IGNORECASE)
                        final_subj_str = pattern.sub(rf"\1 {anti_extra}", final_subj_str)

            final_ret_str = c_ret if c_ret else ("\n".join(retention_defs) if retention_defs else "")

            if final_subj_str:
                bgm_section = f"\n\nnon_diegetic_music:\n{c_bgm}" if c_bgm else ""
                
                # Prevent double prepending if the summary somehow still has the tag
                c_summary_clean = re.sub(r"^\[reference generation\]\s*\d+-\d+(?:\.\d+)?s[，,\s]*", "", bound_summary).strip()

                full_prompt = (
                    f"subject_definitions:\n{final_subj_str}\n\n"
                    f"summary:\n[reference generation] 0-{s_dur:.1f}s, {c_summary_clean}\n\n"
                    f"retention_analysis:\n{final_ret_str}\n\n"
                    f"detailed_description:\n[Shot {s_idx+1}: {s_title}] {bound_detail}\n\n"
                    f"overall_soundscape:\n{final_soundscape}{bgm_section}"
                )
            else:
                full_prompt = bound_detail

            group = {
                "version": 1,
                "family": "r2v",
                "kind": "r2v",
                "prompt": full_prompt.strip(),
                "duration_sec": s_dur,
                "first_frame": None,
                "last_frame": None,
                "ref_images": images_dict,
                "ref_videos": videos_dict,
                "ref_video_audios": video_audios_dict,
                "ref_audios": audios_dict,
                "handoff_chain": continuous_take_handoff,
                "has_dialogue": has_dialogue,
            }
            groups_list.append(group)
            summary_lines.append(f"\n====================\n🎬 分鏡 {s_idx+1} [{s_id}] ({s_dur:.2f}s | 17k+5對齊) - {s_title}\n{full_prompt}\n")

        summary_text = "\n".join(summary_lines)
        return (groups_list, summary_text, len(groups_list))


NODE_CLASS_MAPPINGS = {
    "UltimateDirectorStoryEngine": UltimateDirectorStoryEngineNode,
    "UltimateDirectorPromptEnhancer": UltimateDirectorPromptEnhancerNode,
    "UltimateDirectorRefine": UltimateDirectorRefineNode,
    "UltimateDirectorMultimodalDirector": UltimateDirectorMultimodalDirector,
    "UltimateDirectorMediaDashboard": UltimateDirectorMediaDashboardNode,
    "UltimateDirectorStoryboardGrid": UltimateDirectorStoryboardGridNode,
    "UltimateDirectorCharacterSheetSplitter": UltimateDirectorCharacterSheetSplitterNode,
    "UltimateDirectorMotionHandoff": UltimateDirectorMotionHandoffNode,
    "UltimateDirectorMotionTrim": UltimateDirectorMotionTrimNode,
    "UltimateDirectorPipelineSwitch": UltimateDirectorPipelineSwitchNode,
    "UltimateDirectorBranchGate": UltimateDirectorBranchGateNode,
    "UltimateDirectorAssetBridge": UltimateDirectorAssetBridgeNode,
    "UltimateDirectorCompiler": UltimateDirectorCompilerNode,
    "UltimateDirectorSCAILLock": UltimateDirectorSCAILLockNode,
    "UltimateDirectorSCAILTrim": UltimateDirectorSCAILTrimNode,
    "UltimateDirectorCastIterator": UltimateDirectorCastIteratorNode,
    "UltimateDirectorAutoCastBatchGenerator": UltimateDirectorAutoCastBatchGenerator,
    "UltimateDirectorTimelineToR2VGroups": UltimateDirectorTimelineToR2VGroupsNode,
    # High-quality zero-dependency video & text nodes:
    "UltimateDirectorVideoCombine": UltimateDirectorVideoCombine,
    "UltimateDirectorTextDisplay": UltimateDirectorTextDisplay,
    # Seamless backward-compatibility aliases:
    "VHS_VideoCombine": UltimateDirectorVideoCombine,
    "ShowText|pysssss": UltimateDirectorTextDisplay,
    "MiniMaxH3MemoryEfficientSageAttentionPatch": MiniMaxH3MemoryEfficientSageAttentionPatch,
    # Native Cinema Engine & Backward-Compatibility mappings:
    "UltimateDirectorH3Engine": MiniMaxH3Director,
    "MiniMaxH3Director": MiniMaxH3Director,
    "ComfyMiniMaxH3Director": MiniMaxH3Director,
    "MiniMaxH3DirectorRefine": MiniMaxH3DirectorRefine,
    "MiniMaxH3DirectorConditioning": MiniMaxH3DirectorConditioning,
    "MiniMaxH3DirectorPlannerConditioning": MiniMaxH3DirectorPlannerConditioning,
    "MiniMaxH3DirectorGroupImageToVideo": MiniMaxH3DirectorGroupImageToVideo,
    "MiniMaxH3DirectorGroupReferenceToVideo": MiniMaxH3DirectorGroupReferenceToVideo,
    "MiniMaxH3DirectorGroupsCombine": MiniMaxH3DirectorGroupsCombine,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "UltimateDirectorStoryEngine": "🎬 終極導演：劇本大腦 (Story Engine GGUF)",
    "UltimateDirectorPromptEnhancer": "🧠 終極導演：H3 提示詞增強器 (Prompt Enhancer)",
    "UltimateDirectorRefine": "🔍 終極導演：二採放大控制器 (Refine & Upscale)",
    "UltimateDirectorMultimodalDirector": "🎬 終極導演：多模態參考導演台 (Multimodal Studio)",
    "UltimateDirectorMediaDashboard": "🎬 終極導演：多模態素材庫 (Media Dashboard)",
    "UltimateDirectorStoryboardGrid": "🎨 終極導演：宮格分鏡裁切器 (Storyboard Grid Splitter)",
    "UltimateDirectorCharacterSheetSplitter": "👤 終極導演：角色四視圖切割器 (Character Sheet Splitter)",
    "UltimateDirectorCastIterator": "👥 終極導演：角色/主體迭代提取器 (Cast & Prop Iterator)",
    "UltimateDirectorAutoCastBatchGenerator": "🎭 終極導演：動態多角色自動生圖器 (Auto Multi-Cast Batch Generator)",
    "UltimateDirectorTimelineToR2VGroups": "⚡ 終極導演：動態全分鏡影片調度器 (Timeline to R2V Groups)",
    "UltimateDirectorMotionHandoff": "🔗 終極導演：段間尾幀引導 (Motion Context Handoff)",
    "UltimateDirectorMotionTrim": "✂️ 終極導演：無縫過渡裁切 (Motion Prefix Trim)",
    "UltimateDirectorPipelineSwitch": "🎛️ 終極導演：全流程總控開關 (Pipeline Master Switch)",
    "UltimateDirectorBranchGate": "🚪 終極導演：管線分支閘門 (Branch Gate)",
    "UltimateDirectorAssetBridge": "🌉 終極導演：資產轉 H3 橋接器 (Asset Bridge)",
    "UltimateDirectorCompiler": "⚙️ 終極導演：時間線編譯器 (Timeline Compiler)",
    "UltimateDirectorSCAILLock": "🔒 終極導演：SCAIL 潛空間鎖定 (SCAIL Latent Lock)",
    "UltimateDirectorSCAILTrim": "✂️ 終極導演：SCAIL 輸出裁切 (SCAIL Output Trim)",
    "UltimateDirectorVideoCombine": "🎥 終極導演：電影影音合成導出器 (Video Combine)",
    "UltimateDirectorTextDisplay": "📜 終極導演：文字與分鏡劇本檢視器 (Text Display)",
    "VHS_VideoCombine": "🎥 終極導演：影音合成導出器 (VHS相容)",
    "ShowText|pysssss": "📜 終極導演：文字檢視器 (ShowText相容)",
    "MiniMaxH3MemoryEfficientSageAttentionPatch": "⚡ 終極導演：SageAttention顯存優化 (內建原生)",
    "ModelPreviewOverrideKJ": "👁️ 終極導演：採樣預覽 (內建原生)",
    "UltimateDirectorH3Engine": "🚀 終極導演：電影級渲染引擎 (Ultimate Director H3 Engine)",
    "MiniMaxH3Director": "🚀 終極導演：H3 分鏡渲染台 (MiniMax H3 Director 原生內建)",
    "ComfyMiniMaxH3Director": "🚀 終極導演：H3 分鏡渲染台 (相容別名)",
    "MiniMaxH3DirectorRefine": "🔍 終極導演：H3 二採控制器 (Director Refine)",
    "MiniMaxH3DirectorConditioning": "🧠 終極導演：H3 條件控制 (Director Conditioning)",
    "MiniMaxH3DirectorPlannerConditioning": "🧠 終極導演：H3 規劃條件控制 (Planner Conditioning)",
    "MiniMaxH3DirectorGroupImageToVideo": "🖼️ 終極導演：H3 鏡頭群組 (I2V)",
    "MiniMaxH3DirectorGroupReferenceToVideo": "👥 終極導演：H3 參考主體鏡頭群組 (R2V)",
    "MiniMaxH3DirectorGroupsCombine": "🔗 終極導演：H3 鏡頭群組合併 (Groups Combine)",
}
