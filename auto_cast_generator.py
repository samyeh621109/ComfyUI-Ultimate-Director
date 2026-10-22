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
                "max_characters": ("INT", {"default": 9, "min": 1, "max": 9, "step": 1, "tooltip": "最多產生資產數量限制（1~9）。"}),
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
                "asset_scope": ([
                    "人物與核心道具 (Cast & Hero Props)",
                    "全劇資產：人物+道具+場景 (All Assets: Cast, Props & Scenes)",
                    "僅人物角色 (Characters Only)",
                ], {
                    "default": "人物與核心道具 (Cast & Hero Props)",
                    "tooltip": "選擇要自動生成的資產類別。可一鍵生成人物角色、推動劇情的關鍵道具（如魔鏡、寶劍、晶片），乃至核心場景概念圖！"
                }),
            }
        }




    RETURN_TYPES = (
        "IMAGE",   # all_images (batch of all characters/props/scenes)
        "IMAGE",   # ref_image_1 (Picture 1)
        "IMAGE",   # ref_image_2 (Picture 2)
        "IMAGE",   # ref_image_3 (Picture 3)
        "IMAGE",   # ref_image_4 (Picture 4)
        "IMAGE",   # ref_image_5 (Picture 5)
        "IMAGE",   # ref_image_6 (Picture 6)
        "IMAGE",   # ref_image_7 (Picture 7)
        "IMAGE",   # ref_image_8 (Picture 8)
        "IMAGE",   # ref_image_9 (Picture 9)
        "IMAGE",   # grid_preview (single concatenated canvas showing all assets)
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
        asset_scope: str = "人物與核心道具 (Cast & Hero Props)",
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
            log.info("UltimateDirector: ⚡ 自動資產生圖開關為【關閉/使用自選參考圖 (Off)】（已略過生圖，0 秒完成）。下游將由自選參考圖接管！")
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
                "⚡ 自動資產生圖已關閉（請在下游節點使用自選參考圖）。",
            )

        include_props = "道具" in asset_scope or "Props" in asset_scope or "全劇" in asset_scope
        include_scenes = "場景" in asset_scope or "Scenes" in asset_scope or "全劇" in asset_scope

        data = _clean_json_or_dict(timeline_or_json)
        cast_items = _extract_cast_items(data, include_props=include_props, include_scenes=include_scenes)

        if not cast_items:
            cast_items = [{"name": "主角", "description": "寫實電影主角，精緻五官與服飾", "asset_type": "character"}]

        actual_count = min(len(cast_items), max_characters)
        cast_items = cast_items[:actual_count]

        log.info(f"UltimateDirector: Automatically generating {actual_count} reference assets (scope: {asset_scope}) using style [{visual_style}]...")

        # Initialize helper nodes for standard ComfyUI encoding/decoding
        from nodes import CLIPTextEncode, EmptyLatentImage, common_ksampler, VAEDecode
        clip_encoder = CLIPTextEncode()
        latent_maker = EmptyLatentImage()
        vae_decoder = VAEDecode()

        # Style suffix
        style = custom_style_suffix.strip() if custom_style_suffix.strip() else "cinematic lighting, photorealistic, 8k resolution, raw photo, masterwork, sharp focus, 35mm film photography"

        # Determine prompt header based on layout
        if "單人半身" in view_layout:
            header = "solo, strictly single person, centered in frame, head and shoulders portrait, upper body medium close-up, front view, expressive face and detailed eyes, clear attire, 単人半身特寫肖像。"
        elif "單人七分身" in view_layout:
            header = "solo, strictly single person, centered in frame, cowboy shot from head to knees, front view, detailed facial features and outfit, 單人正面七分身立繪。"
        elif "單人全身" in view_layout:
            header = "solo, strictly single person, centered in frame, full length portrait, full body shot from head to toe, standing pose, front view, complete outfit and proportions, strictly ONE single view, absolutely NO multiple views, 單人正面完整全身站姿立繪。"
        elif "三視圖" in view_layout:
            header = "character sheet, 3 views side by side, triple view: face close-up, front full body standing, side full body standing, 三欄橫向並列角色三視圖設定圖。"
        elif "四視圖" in view_layout:
            header = "character sheet, 4 views side by side, turnaround model sheet: face close-up, front full body standing, side full body standing, back full body standing, 四欄橫向並列角色四視圖設定圖。"
        elif "道具/坐騎" in view_layout:
            header = "multi-angle product showcase, four angles: detail close-up, front view, side view, back view, 道具多角度設定圖。"
        else:
            header = "solo, strictly single person, centered in frame, full length portrait, full body shot, 正面單人立繪。"

        is_single_view = any(k in view_layout for k in ["單人半身", "單人七分身", "單人全身"])
        single_view_neg = ", split screen, multiple views, multi-view, character sheet, turnaround, model sheet, 2views, 3views, 4views, multiple angles, collage, grid, montage, side by side, composite, duplicate body, clone, twin, two persons, multiple characters, extra person" if is_single_view else ""

        generated_images: List[torch.Tensor] = []
        summary_lines = [f"📦 【全劇資產自動生成總覽（共 {actual_count} 項 · 範疇：{asset_scope}）】："]

        _animal_keywords = [
            "馬", "horse", "steed", "獸", "beast", "車", "car", "vehicle", "龍", "dragon",
            "狼", "wolf", "狐", "fox", "虎", "tiger", "獅", "lion", "熊", "bear", "豹", "leopard",
            "犬", "狗", "dog", "貓", "cat", "兔", "rabbit", "bunny", "鹿", "deer", "象", "elephant",
            "牛", "bull", "cow", "羊", "sheep", "goat", "豬", "pig", "boar", "猴", "monkey", "ape",
            "鳥", "bird", "鷹", "eagle", "hawk", "蛇", "snake", "魚", "fish", "鯊", "shark", "鯨", "whale",
            "動物", "animal", "坐騎", "mount", "道具", "prop", "雲", "cloud", "觔斗雲", "祥雲",
            "飛劍", "劍", "sword", "飛船", "ship", "機甲", "mecha", "法寶", "神器", "靈獸", "寵物", "creature", "wildlife", "artifact"
        ]

        for idx, item in enumerate(cast_items):
            c_name = item.get("name", f"主體_{idx+1}")
            c_desc = item.get("description", "")
            asset_type = item.get("asset_type", "character")
            
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

            base_neg = negative_prompt.strip()

            if asset_type == "prop":
                char_header = "寫實電影道具特寫劇照，單一核心主體置中展示（Hero prop product studio photography, centered isolated object），35mm電影鏡頭微距拍攝，極致精準材質細節與光澤質感（sharp intricate material details, realistic reflections, photorealistic textures），純粹展覽展示光影，深色乾淨背景，absolutely no human, no person, no hands, no background clutter。"
                is_non_human = True
                tag_label = "🗡️ 道具"
                extra_neg = ", human, person, man, woman, face, eyes, hands, fingers, body, crowd"
            elif asset_type == "scene":
                char_header = "寫實電影環境空鏡劇照，宏大場景全景構圖（Cinematic wide establishing shot, architecture and environment photography），35mm變形寬銀幕鏡頭，大氣光影層次（atmospheric volumetric lighting, dramatic depth of field），極致環境細節，absolutely no human, no person, clean empty space。"
                is_non_human = True
                tag_label = "🏰 場景"
                extra_neg = ", human, person, man, woman, face, crowd, character"
            else:
                # Character detection
                human_keywords = ["男", "女", "人", "將", "俠", "帝", "王", "士", "兵", "客", "man", "woman", "boy", "girl", "person", "human", "knight", "warrior", "hero", "subject"]
                is_human = any(k in c_name.lower() for k in human_keywords)
                if is_human:
                    is_non_human = False
                else:
                    is_non_human = any(k in c_name.lower() or k in c_desc.lower() for k in _animal_keywords)

                tag_label = "👤 角色"
                if is_non_human:
                    extra_neg = ", multiple subjects, 2 horses, two animals, extra animals, double mount, split screen, duplicate body"
                    if not any(k in c_desc.lower() for k in ["衣", "服", "裝", "袍", "甲", "shirt", "suit", "clothes", "jacket", "pants", "hat"]):
                        extra_neg += ", clothes, suit, jacket, coat, pants, shirt, tie, hat, shoes, boots, human clothing"
                else:
                    extra_neg = ""

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

            # Inanimate object protection: strip skin/anatomy tokens and enforce vacant furniture
            if asset_type in ("prop", "scene"):
                for human_phrase in [
                    "subsurface scattering on skin",
                    "expressive stylized anatomy",
                    "skin texture",
                    "pores",
                    "facial anatomy",
                    "expressive face and detailed eyes",
                    "detailed face"
                ]:
                    prompt_text = prompt_text.replace(human_phrase, "intricate physical material textures, studio lighting")
                if any(k in (c_name + " " + c_desc).lower() for k in ["床", "bed", "椅", "chair", "桌", "table", "車", "car", "房", "room", "屋", "house", "被", "quilt"]):
                    prompt_text += ", empty and unoccupied, completely vacant, clean furniture product display, strictly NO person, NO sleeping figure, NO human head"
                    extra_neg += ", head, human head, sleeping person, face, lying person, eyes, person on bed, character on bed, doll, mannequin"

            current_base_neg = base_neg if base_neg else dyn_neg
            combined_neg = f"{current_base_neg}{extra_neg}{single_view_neg}"

            log.info(f"Generating Asset [{idx+1}/{actual_count}] ({tag_label}): {c_name} -> {prompt_text[:90]}...")
            
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
            
            summary_lines.append(f"  • Picture {idx+1} [{tag_label}] | {c_name}: {c_desc[:60]}...")

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

        # 生圖階段結束：及時硬卸載 Krea2 / WanVAE (釋放 18GB+ 系統 RAM 與 Pinned Buffers)，
        # 徹底避免與後續 MiniMax H3 (40GB) 在系統 RAM 中重疊導致超過 32GB 實體記憶體上限而引發系統卡死 (Swap Thrashing Freeze)！
        for m in (model, clip, vae):
            if m is not None:
                try:
                    if hasattr(m, "unpatch_model"):
                        m.unpatch_model(unpatch_weights=True)
                    elif hasattr(m, "patcher") and hasattr(m.patcher, "unpatch_model"):
                        m.patcher.unpatch_model(unpatch_weights=True)
                except Exception:
                    pass
        try:
            import comfy.model_management as mm
            import gc
            if hasattr(mm, "free_pins"):
                mm.free_pins(1e32, evict_active=True)
            mm.unload_all_models()
            mm.soft_empty_cache()
            gc.collect()
        except Exception:
            pass

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
