# -*- coding: utf-8 -*-
"""Ultimate Director: Auto Cast Batch Generator.

Dynamically extracts ALL cast members (1, 2, 3, 4 ... up to 9) from the StoryEngine timeline,
automatically generates 1024x1024 high-fidelity reference portraits using Krea 2 Turbo
in a single automated batch pass, and provides both individual reference image sockets
(ref_image_1 to ref_image_9) and a full image batch + grid preview.
"""
from __future__ import annotations

import logging
import torch
import comfy.sample
import comfy.samplers
import comfy.utils
from typing import Any, Dict, List, Tuple

from .cast_iterator import _clean_json_or_dict, _extract_cast_items, ANY
from .style_manager import style_manager

log = logging.getLogger("UltimateDirector.auto_cast_generator")


class UltimateDirectorAutoCastBatchGenerator:
    """Dynamically generates reference portraits for all characters in the story (up to 9)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "timeline_or_json": (ANY, {
                    "forceInput": True,
                    "tooltip": "StoryEngine 輸出的 timeline (TIMELINE_DICT) 或 json 字串，自動讀取所有角色/坐騎/道具清單。"
                }),
                "model": ("MODEL", {"tooltip": "Krea 2 Turbo 生圖模型（可串接 LoRA）。"}),
                "clip": ("CLIP", {"tooltip": "Krea 2 CLIP (Qwen3-VL 4B)。"}),
                "vae": ("VAE", {"tooltip": "Krea 2 VAE。"}),
                "generator_switch": (["開啟自動生圖 (On)", "關閉/使用自選參考圖 (Off)"], {
                    "default": "開啟自動生圖 (On)",
                    "tooltip": "模式開關：若您已有自選參考圖 (Node 120/121)，切換為「關閉/使用自選參考圖 (Off)」即可秒過此節點，省下 45 秒！"
                }),

                "steps": ("INT", {"default": 8, "min": 1, "max": 50, "step": 1, "tooltip": "生圖採樣步數（Turbo 推薦 4~8 步）。"}),
                "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 20.0, "step": 0.1, "tooltip": "CFG 引導係數（Krea 2 推薦 1.0）。"}),
                "sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"default": "euler"}),
                "scheduler": (comfy.samplers.KSampler.SCHEDULERS, {"default": "simple"}),
                "seed": ("INT", {"default": 42, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True, "tooltip": "隨機種子。"}),
                "visual_style": (style_manager.get_category_list(), {
                    "default": "Auto (自動匹配故事題材風格)",
                    "tooltip": "從 4000+ Krea2 大師風格庫與電影色調中選擇（支援攝影寫實、好萊塢色調、動漫、3D、哥德等）。"
                }),
                "view_layout": ([
                    "單人半身肖像 (高畫質正面肖像，五官微表情細膩)",
                    "單人七分身立繪 (膝上正面寫實，平衡五官與穿搭)",
                    "單人全身立繪 (完整全身站姿穿搭)",
                    "四視圖 (臉部特寫+正面全身+側面全身+背面全身)",
                    "三視圖 (臉部特寫+正面全身+側面全身)",
                    "道具/坐騎多角度視圖 (細節特寫+正視圖+側視圖+背視圖)"
                ], {"default": "單人半身肖像 (高畫質正面肖像，五官微表情細膩)", "tooltip": "角色立繪格式。"}),
                "max_characters": ("INT", {"default": 9, "min": 1, "max": 9, "step": 1, "tooltip": "最多產生角色數量限制（1~9）。"}),
                "custom_style_suffix": ("STRING", {
                    "multiline": True,
                    "default": "cinematic lighting, photorealistic, 8k resolution, raw photo, masterwork, sharp focus, 35mm film photography",
                    "tooltip": "追加的畫質與風格後綴提示詞。"
                }),
                "negative_prompt": ("STRING", {
                    "multiline": True,
                    "default": "ugly, deformed, disfigured, blurry, low resolution, duplicate, bad anatomy, bad hands, mutated, text, watermark",
                    "tooltip": "負向提示詞。"
                }),
            }
        }




    RETURN_TYPES = (
        "IMAGE",   # all_images (batch of all characters)
        "IMAGE",   # ref_image_1 (Picture 1)
        "IMAGE",   # ref_image_2 (Picture 2)
        "IMAGE",   # ref_image_3 (Picture 3)
        "IMAGE",   # ref_image_4 (Picture 4)
        "IMAGE",   # ref_image_5 (Picture 5)
        "IMAGE",   # ref_image_6 (Picture 6)
        "IMAGE",   # ref_image_7 (Picture 7)
        "IMAGE",   # ref_image_8 (Picture 8)
        "IMAGE",   # ref_image_9 (Picture 9)
        "IMAGE",   # grid_preview (single concatenated canvas showing all characters)
        "INT",     # cast_count
        "STRING",  # cast_summary
    )
    RETURN_NAMES = (
        "all_images",
        "ref_image_1",
        "ref_image_2",
        "ref_image_3",
        "ref_image_4",
        "ref_image_5",
        "ref_image_6",
        "ref_image_7",
        "ref_image_8",
        "ref_image_9",
        "grid_preview",
        "cast_count",
        "cast_summary",
    )
    FUNCTION = "generate_all_cast"
    CATEGORY = "UltimateDirector/Character"

    def generate_all_cast(
        self,
        timeline_or_json: Any,
        model: Any,
        clip: Any,
        vae: Any,
        generator_switch: Any = "開啟自動生圖 (On)",
        steps: int = 8,
        cfg: float = 1.0,
        sampler_name: str = "euler",
        scheduler: str = "simple",
        seed: int = 42,
        visual_style: str = "Auto (自動匹配故事題材風格)",
        view_layout: str = "單人半身肖像 (高畫質正面肖像，五官微表情細膩)",
        max_characters: int = 9,
        custom_style_suffix: str = "",
        negative_prompt: str = "",
        **_kwargs,
    ):
        is_on = "開啟" in str(generator_switch) or "On" in str(generator_switch) or generator_switch is True
        if not is_on:
            log.info("UltimateDirector: ⚡ 自動角色生圖開關為【關閉/使用自選參考圖 (Off)】（已略過生圖，0 秒完成）。下游將由自選參考圖接管！")
            dummy_empty = torch.zeros((1, 64, 64, 3), dtype=torch.float32)

            return (
                dummy_empty,
                dummy_empty,
                dummy_empty,
                dummy_empty,
                dummy_empty,
                dummy_empty,
                dummy_empty,
                dummy_empty,
                dummy_empty,
                dummy_empty,
                dummy_empty,
                0,
                "⚡ 自動角色生圖已關閉（請在下游節點使用自選參考圖）。",
            )

        data = _clean_json_or_dict(timeline_or_json)
        cast_items = _extract_cast_items(data)

        
        if not cast_items:
            cast_items = [{"name": "主角", "description": "寫實電影主角，精緻五官與服飾"}]
            
        actual_count = min(len(cast_items), max_characters)
        cast_items = cast_items[:actual_count]

        log.info(f"UltimateDirector: Automatically generating {actual_count} reference character portraits using style [{visual_style}]...")

        # Initialize helper nodes for standard ComfyUI encoding/decoding
        from nodes import CLIPTextEncode, EmptyLatentImage, common_ksampler, VAEDecode
        clip_encoder = CLIPTextEncode()
        latent_maker = EmptyLatentImage()
        vae_decoder = VAEDecode()

        # Style suffix
        style = custom_style_suffix.strip() if custom_style_suffix.strip() else "cinematic lighting, photorealistic, 8k resolution, raw photo, masterwork, sharp focus, 35mm film photography"

        # Determine prompt header based on layout
        if "單人半身" in view_layout:
            header = "寫實真人電影肖像照片，單人正面半身特寫（Head and shoulders portrait, upper body medium shot），35mm電影鏡頭拍攝，真實皮膚毛孔紋理（detailed skin texture, realistic pores），自然眼神光與細膩微表情，清晰服飾質感與剪裁。"
        elif "單人七分身" in view_layout:
            header = "寫實真人電影照片，單人正面七分身立繪（Cowboy shot, from head to knees），35mm電影鏡頭拍攝，真實皮膚毛孔紋理（detailed skin texture, realistic pores），清晰五官與完整服飾搭配。"
        elif "單人全身" in view_layout:
            header = "寫實真人電影照片，單人正面完整全身立繪（Full body shot from head to feet），35mm電影鏡頭拍攝，真實皮膚毛孔紋理，完整身形比例與全身服飾穿搭。"
        elif "三視圖" in view_layout:
            header = "寫實真人電影照片，三欄橫向並列角色設定圖，同一人物三視圖，35mm電影鏡頭拍攝，真實皮膚毛孔紋理。畫面從左到右嚴格分為三欄：臉部極致近景特寫，正面全身站姿，側面全身站姿。"
        elif "道具/坐騎" in view_layout:
            header = "寫實電影照片，四欄橫向並列主體多角度設定圖，同一主體多角度視圖，35mm電影鏡頭拍攝。第一欄局部細節特寫，第二欄正面全貌，第三欄側面全貌，第四欄背面全貌。"
        else:
            header = "寫實真人電影照片，四欄橫向並列角色設定圖，同一人物四視圖，35mm電影鏡頭拍攝，真實皮膚毛孔紋理。畫面從左到右嚴格分為四欄：臉部極致近景特寫，正面全身站姿，側面全身站姿，背面全身站姿。"

        generated_images: List[torch.Tensor] = []
        summary_lines = [f"👥 【自動生成主體/角色參考圖清單（共 {actual_count} 位）】："]

        _animal_keywords = [
            "馬", "horse", "steed", "獸", "beast", "車", "car", "vehicle", "龍", "dragon",
            "犬", "dog", "坐騎", "mount", "道具", "prop", "雲", "cloud", "觔斗雲", "祥雲",
            "飛劍", "劍", "sword", "飛船", "ship", "機甲", "mecha", "法寶", "神器", "靈獸", "寵物", "creature", "artifact"
        ]

        for idx, item in enumerate(cast_items):
            c_name = item.get("name", f"主體_{idx+1}")
            c_desc = item.get("description", "")
            
            # Canonical enhancement for iconic figures to guarantee authentic armor and correct weapons
            c_lower = (c_name + " " + c_desc).lower()
            if any(k in c_lower for k in ["悟空", "wukong", "美猴王", "齊天大聖", "monkey king"]):
                canon_extra = "身披精緻鎖子黃金甲與虎皮戰裙，頭戴鳳翅紫金冠或緊箍咒。手持如意金箍棒（筆直圓柱形黑鐵棍，兩端各有一道雕花純金箍環，頂端完全平截，嚴禁圓球頭、嚴禁拐杖球、嚴禁槍尖，Straight cylindrical black iron staff with two gold bands at both ends, blunt flat ends, strictly NO ball head, NO scepter knob, NO spearhead）"
                if "金箍棒" not in c_desc and "如意棒" not in c_desc:
                    c_desc = f"{c_desc}，{canon_extra}"
                else:
                    c_desc = f"{c_desc}，如意金箍棒為筆直圓柱形黑鐵棍且兩端為平頭金箍（Straight cylindrical iron staff, blunt flat ends with gold bands, strictly NO ball head, NO spearhead）"
            elif any(k in c_lower for k in ["關羽", "關公", "雲長", "guan yu"]):
                canon_extra = "身穿綠色戰袍與黃金甲冑，美髯飄拂，手持青龍偃月刀（冷豔鋸）"
                c_desc = f"{c_desc}，{canon_extra}"
            elif any(k in c_lower for k in ["趙雲", "子龍", "zhao yun"]):
                canon_extra = "英姿颯爽，身披白袍銀甲，手持龍膽亮銀槍"
                c_desc = f"{c_desc}，{canon_extra}"

            # Auto-detect mounts, vehicles, animals, magical clouds or props
            is_non_human = any(k in c_name.lower() or k in c_desc.lower() for k in _animal_keywords)
            if is_non_human:
                if any(k in c_name.lower() or k in c_desc.lower() for k in ["雲", "cloud", "法寶", "光", "神器", "magic", "劍", "sword"]):
                    char_header = "寫實電影照片，單一主體神話法寶/仙家靈物/御空載具完整全貌立繪視圖（Single solo standalone shot of magical mount, ethereal cloud, flying artifact, or divine entity），35mm電影鏡頭拍攝，真實流光粒子與仙家神光質感，清晰外觀輪廓與細節。"
                else:
                    char_header = "寫實電影照片，單一匹/隻主體完整全身立繪（Single solo standalone full body shot of mount, animal, vehicle or item, strictly ONE subject only），35mm電影鏡頭拍攝，真實毛皮與肌肉金屬質感（realistic coat texture, muscular definition），完整四肢與配備，清晰細節，自然光影。"
            else:
                char_header = header

            subject_prompt = f"{char_header}[{c_name}，固定外觀細節：{c_desc}]"
            prompt_text, dyn_neg = style_manager.apply_style(
                subject_prompt=subject_prompt,
                style_choice=visual_style,
                default_suffix=style,
            )

            # Combine negative prompt with dynamic style negative
            base_neg = negative_prompt.strip() if negative_prompt.strip() else dyn_neg
            combined_neg = f"{base_neg}, multiple subjects, 2 horses, two animals, extra animals, double mount, split screen, duplicate body" if is_non_human else base_neg
            
            log.info(f"Generating Cast [{idx+1}/{actual_count}]: {c_name} -> {prompt_text[:90]}...")
            
            pos_cond = clip_encoder.encode(clip, prompt_text)[0]
            neg_cond = clip_encoder.encode(clip, combined_neg)[0]
            empty_latent = latent_maker.generate(1024, 1024, batch_size=1)[0]

            # Sampler execution via standard common_ksampler
            char_seed = (seed + idx * 10007) % (0xffffffffffffffff)
            sampled_latent = common_ksampler(
                model=model,
                seed=char_seed,
                steps=steps,
                cfg=cfg,
                sampler_name=sampler_name,
                scheduler=scheduler,
                positive=pos_cond,
                negative=neg_cond,
                latent=empty_latent,
                denoise=1.0
            )[0]
            
            # Decode to RGB Image
            decoded = vae_decoder.decode(vae, sampled_latent)[0]
            # Ensure decoded is on CPU float32 [1, H, W, 3]
            decoded = decoded.detach().cpu()
            generated_images.append(decoded)
            
            summary_lines.append(f"  • Picture {idx+1} | {c_name}: {c_desc[:60]}...")

        # Stack into batch [N, H, W, 3]
        all_images = torch.cat(generated_images, dim=0)

        # Build 1xN horizontal grid preview
        grid_preview = torch.cat(generated_images, dim=2) # Concat along width

        # Individual slots (pad up to 9 with empty or fallback image)
        fallback_img = generated_images[0] # Fallback to first character if slot is empty
        slots: List[torch.Tensor] = []
        for s_idx in range(9):
            if s_idx < len(generated_images):
                slots.append(generated_images[s_idx])
            else:
                slots.append(fallback_img)

        summary_text = "\n".join(summary_lines)

        return (
            all_images,
            slots[0],
            slots[1],
            slots[2],
            slots[3],
            slots[4],
            slots[5],
            slots[6],
            slots[7],
            slots[8],
            grid_preview,
            actual_count,
            summary_text,
        )
