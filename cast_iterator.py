# -*- coding: utf-8 -*-
"""Ultimate Director: Cast Iterator & Dynamic Asset Generator Helper.

Parses StoryEngine timeline JSON or YUAN format, extracts all cast characters / props / subjects,
and generates structured Krea2 4-view prompts and MiniMax H3 R2V mapping tags dynamically
based on a user-controllable cast_index (0, 1, 2...).
"""
from __future__ import annotations

import json
import re
import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("UltimateDirector.cast_iterator")


class AnyType(str):
    """Wildcard type for flexible ComfyUI slot connections."""
    def __ne__(self, __value: object) -> bool:
        return False
    def __eq__(self, __value: object) -> bool:
        return True


ANY = AnyType("*")


def _clean_json_or_dict(input_data: Any) -> dict:
    """Safely normalizes input_data into a dictionary."""
    if isinstance(input_data, dict):
        return input_data
    if isinstance(input_data, str):
        cleaned = input_data.strip()
        # Strip markdown fences if present
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            pass
        # Try finding outermost JSON object
        m = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    return {}


def _extract_cast_items(data: dict, include_props: bool = False, include_scenes: bool = False) -> List[Dict[str, str]]:
    """Extracts a normalized list of characters, hero props, and environments from various JSON schemas,
    including Ultimate Director 'cast', 'props', 'scenes', Director Canvas 'characters', and YUAN.
    Each item is tagged with 'asset_type': 'character' | 'prop' | 'scene'.
    """
    items: List[Dict[str, str]] = []

    # 1. Standard Ultimate Director 'cast' list: [{"id": "...", "name": "...", "description": "..."}]
    raw_cast = data.get("cast", [])
    if isinstance(raw_cast, list) and raw_cast:
        for idx, entry in enumerate(raw_cast):
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("id") or entry.get("trigger_word") or f"角色_{idx+1}"
                desc = entry.get("description") or entry.get("appearance") or ""
                items.append({"name": str(name).strip(), "description": str(desc).strip(), "asset_type": "character"})
            elif isinstance(entry, str) and entry.strip():
                s = entry.strip()
                name = s.split("，")[0].split(",")[0].strip()
                items.append({"name": name, "description": s, "asset_type": "character"})

    # 2. Director Canvas (krea2_skills / dramaData) 'characters' list
    if not items:
        raw_characters = data.get("characters", [])
        if isinstance(raw_characters, list) and raw_characters:
            for idx, entry in enumerate(raw_characters):
                if isinstance(entry, dict):
                    name = entry.get("name") or entry.get("title") or entry.get("id") or f"角色_{idx+1}"
                    desc = entry.get("krea_prompt") or entry.get("appearance") or entry.get("description") or ""
                    items.append({"name": str(name).strip(), "description": str(desc).strip(), "asset_type": "character"})
                elif isinstance(entry, str) and entry.strip():
                    s = entry.strip()
                    name = s.split("，")[0].split(",")[0].strip()
                    items.append({"name": name, "description": s, "asset_type": "character"})

    # 3. YUAN format '角色檔案': ["韓立，男，十歲...", "韓胖子，男，四十歲..."]
    if not items:
        raw_yuan = data.get("角色檔案", [])
        if isinstance(raw_yuan, list) and raw_yuan:
            for entry in raw_yuan:
                if entry and isinstance(entry, str):
                    s = entry.strip()
                    name = s.split("，")[0].split(",")[0].strip()
                    items.append({"name": name, "description": s, "asset_type": "character"})

    # 4. Multi-character extraction from krea2_character_sheet_prompt brackets: e.g. [小紅帽：...], [大野狼：...]
    if not items:
        krea_p = data.get("krea2_character_sheet_prompt", "")
        if krea_p:
            brackets = re.findall(r"\[(.*?)\]", krea_p)
            if len(brackets) >= 2:
                for b in brackets:
                    b_strip = b.strip()
                    if "：" in b_strip or ":" in b_strip:
                        parts = re.split(r"[：:]", b_strip, maxsplit=1)
                        c_name = parts[0].strip()
                        c_desc = parts[1].strip()
                    else:
                        c_name = b_strip.split("，")[0].split(",")[0].strip()
                        c_desc = b_strip
                    if c_name and c_desc:
                        items.append({"name": c_name, "description": c_desc, "asset_type": "character"})

    # 5. Extraction from shots subject_definitions (<Subject 1> is ..., <Subject 2> is ...)
    if not items:
        subject_map = {}
        for shot in data.get("shots", []):
            prompt_str = shot.get("prompt", "")
            matches = re.findall(r"<Subject\s*(\d+)>\s*(?:is|为|為|:)\s*(.*?)(?=\n<Subject|\n\n|\n[a-z_]+:|$)", prompt_str, re.DOTALL | re.IGNORECASE)
            for num, desc in matches:
                desc_clean = desc.strip().rstrip(".")
                if num not in subject_map or len(desc_clean) > len(subject_map[num]):
                    subject_map[num] = desc_clean
        if subject_map:
            for num in sorted(subject_map.keys(), key=lambda x: int(x)):
                full_desc = subject_map[num]
                first_part = full_desc.split(",")[0].strip()
                first_part = re.sub(r"^(?:the|a|an)\s+", "", first_part, flags=re.IGNORECASE).strip()
                items.append({"name": first_part, "description": full_desc, "asset_type": "character"})

    # 6. Hero Props extraction
    if include_props:
        raw_props = data.get("props", []) or data.get("道具檔案", [])
        if isinstance(raw_props, list) and raw_props:
            for idx, entry in enumerate(raw_props):
                if isinstance(entry, dict):
                    name = entry.get("name") or entry.get("id") or f"核心道具_{idx+1}"
                    desc = entry.get("art_prompt") or entry.get("description") or ""
                    items.append({"name": str(name).strip(), "description": str(desc).strip(), "asset_type": "prop"})
                elif isinstance(entry, str) and entry.strip():
                    s = entry.strip()
                    name = s.split("，")[0].split(",")[0].split("：")[0].split(":")[0].strip()
                    items.append({"name": name, "description": s, "asset_type": "prop"})

    # 7. Iconic Scenes extraction
    if include_scenes:
        raw_scenes = data.get("scenes", []) or data.get("場景檔案", [])
        if isinstance(raw_scenes, list) and raw_scenes:
            for idx, entry in enumerate(raw_scenes):
                if isinstance(entry, dict):
                    name = entry.get("name") or entry.get("id") or f"標誌場景_{idx+1}"
                    desc = entry.get("art_prompt") or entry.get("description") or ""
                    items.append({"name": str(name).strip(), "description": str(desc).strip(), "asset_type": "scene"})
                elif isinstance(entry, str) and entry.strip():
                    s = entry.strip()
                    name = s.split("，")[0].split(",")[0].split("：")[0].split(":")[0].strip()
                    items.append({"name": name, "description": s, "asset_type": "scene"})

    # 8. Single fallback if still nothing
    if not items:
        krea_p = data.get("krea2_character_sheet_prompt", "")
        if krea_p:
            items.append({"name": "主角", "description": krea_p, "asset_type": "character"})
        else:
            items.append({"name": "主角", "description": "寫實電影男女主角，精緻五官與服飾", "asset_type": "character"})

    return items


class UltimateDirectorCastIteratorNode:
    """Extracts cast members dynamically from the story timeline JSON.
    Allows indexing through characters (0, 1, 2...) to generate individual 4-view sheets
    without hardcoding a fixed number of nodes.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "timeline_or_json": (ANY, {
                    "forceInput": True,
                    "tooltip": "StoryEngine 輸出的 timeline (TIMELINE_DICT) 或 yuan_json_output (STRING)。"
                }),
                "cast_index": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 99,
                    "step": 1,
                    "tooltip": "角色/主體切換索引（0=第1個角色、1=第2個角色、2=第3個角色...）。切換後排隊生成該角色的四視圖。"
                }),
                "view_layout": ([
                    "單人半身肖像 (高畫質正面肖像，五官微表情細膩)",
                    "單人七分身立繪 (膝上正面寫實，平衡五官與穿搭)",
                    "單人全身立繪 (完整全身站姿穿搭)",
                    "四視圖 (臉部特寫+正面全身+側面全身+背面全身)",
                    "三視圖 (臉部特寫+正面全身+側面全身)",
                    "道具/坐騎多角度視圖 (細節特寫+正視圖+側視圖+背視圖)"
                ], {"default": "單人半身肖像 (高畫質正面肖像，五官微表情細膩)", "tooltip": "Krea2 生成的角色立繪/視圖佈局格式。"}),
                "no_text_lock": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "強制追加禁止任何文字、招牌、字母、水印的防錯負向鎖定。"
                }),
            },
            "optional": {
                "custom_style_suffix": ("STRING", {
                    "multiline": True,
                    "default": "cinematic lighting, photorealistic, 8k resolution, raw photo, masterwork, sharp focus, 35mm film photography",
                    "tooltip": "自訂追加的畫質與風格後綴提示詞。"
                }),
            }
        }

    RETURN_TYPES = (
        "STRING",   # char_sheet_prompt
        "INT",      # cast_count
        "STRING",   # cast_name
        "STRING",   # cast_description
        "STRING",   # r2v_mapping_prompt (full multi-subject prompt for H3)
        "STRING",   # current_subject_tag (e.g. <Subject 1>)
        "STRING",   # current_picture_tags (e.g. <Picture 1> <Picture 2> <Picture 3>)
        "STRING",   # all_cast_summary (overview list)
    )
    RETURN_NAMES = (
        "char_sheet_prompt",
        "cast_count",
        "cast_name",
        "cast_description",
        "r2v_mapping_prompt",
        "current_subject_tag",
        "current_picture_tags",
        "all_cast_summary",
    )
    FUNCTION = "iterate_cast"
    CATEGORY = "UltimateDirector/Character"

    def iterate_cast(
        self,
        timeline_or_json: Any,
        cast_index: int,
        view_layout: str,
        no_text_lock: bool = True,
        custom_style_suffix: str = "",
    ) -> Tuple[str, int, str, str, str, str, str, str]:
        data = _clean_json_or_dict(timeline_or_json)
        cast_items = _extract_cast_items(data)
        cast_count = len(cast_items)

        # Safe index clamping
        clamped_idx = max(0, min(cast_index, cast_count - 1)) if cast_count > 0 else 0
        current_item = cast_items[clamped_idx] if cast_items else {"name": "未知主角", "description": ""}

        c_name = current_item.get("name", "主角")
        c_desc = current_item.get("description", "")

        # Build Krea2 Character Sheet Prompt
        is_prop_or_mount = any(kw in c_name for kw in ["馬", "車", "劍", "刀", "槍", "旗", "道具", "坐騎", "載具"])
        
        if is_prop_or_mount or "道具/坐騎" in view_layout:
            header = (
                "寫實電影照片，四欄橫向並列主體多角度設定圖，同一主體多角度視圖（Same subject consistent identity in all 4 views），"
                "35mm電影鏡頭拍攝，真實材質與光澤紋理。畫面從左到右嚴格分為四欄：第一欄局部細節微觀特寫，第二欄正面全貌，第三欄單側90度側面全貌，第四欄背面全貌。"
            )
        elif "單人半身" in view_layout:
            header = (
                "寫實真人電影肖像照片，單人正面半身特寫（Head and shoulders portrait, upper body medium shot），"
                "35mm電影鏡頭拍攝，真實皮膚毛孔紋理（detailed skin texture, realistic pores），自然眼神光與細膩微表情，清晰服飾質感與剪裁。"
            )
        elif "單人七分身" in view_layout:
            header = (
                "寫實真人電影照片，單人正面七分身立繪（Cowboy shot, from head to knees），"
                "35mm電影鏡頭拍攝，真實皮膚毛孔紋理（detailed skin texture, realistic pores），清晰五官與完整服飾搭配。"
            )
        elif "單人全身" in view_layout:
            header = (
                "寫實真人電影照片，單人正面完整全身立繪（Full body shot from head to feet），"
                "35mm電影鏡頭拍攝，真實皮膚毛孔紋理，完整身形比例與全身服飾穿搭。"
            )
        elif "三視圖" in view_layout:
            header = (
                "寫實真人電影照片，三欄橫向並列角色設定圖，同一人物三視圖（Same person consistent identity in all 3 views），"
                "35mm電影鏡頭拍攝，真實皮膚毛孔紋理（detailed skin texture, realistic pores），自然眼神光。畫面從左到右嚴格分為三欄：第一欄臉部極致近景特寫（聚焦五官細節與微表情），第二欄正面全身站姿，第三欄單側90度側面全身站姿。"
            )
        else:
            header = (
                "寫實真人電影照片，四欄橫向並列角色設定圖，同一人物四視圖（Same person consistent identity in all 4 views），"
                "35mm電影鏡頭拍攝，真實皮膚毛孔紋理（detailed skin texture, realistic pores），自然眼神光。畫面從左到右嚴格分為四欄：第一欄臉部極致近景特寫（聚焦五官細節與微表情），第二欄正面全身站姿，第三欄單側90度側面全身站姿，第四欄背面全身站姿。"
            )

        char_sheet_prompt = f"{header}[{c_name}，固定外貌與穿著：{c_desc}]"
        
        style = custom_style_suffix.strip() if custom_style_suffix.strip() else "cinematic lighting, photorealistic, 8k resolution, raw photo, masterwork, sharp focus, 35mm film photography"
        char_sheet_prompt += f"，{style}"

        if no_text_lock:
            char_sheet_prompt += ", absolutely no text, no words, no letters, no numbers, no captions, no labels, no titles, no writing, no watermarks on the image"

        # Build Full R2V Mapping Prompt for MiniMax H3
        r2v_lines = []
        summary_lines = [f"📋 【故事角色/主體檔案清單（共 {cast_count} 個）】："]

        for i, item in enumerate(cast_items):
            subj_id = i + 1
            p_start = i * 3 + 1
            p_mid = i * 3 + 2
            p_end = i * 3 + 3
            item_name = item.get("name", f"角色_{subj_id}")
            item_desc = item.get("description", "")
            
            mapping_line = f"<Subject {subj_id}> <Picture {p_start}> <Picture {p_mid}> <Picture {p_end}> 是{item_name}（{item_desc}）"
            r2v_lines.append(mapping_line)

            marker = " 👉 [當前選中]" if i == clamped_idx else ""
            summary_lines.append(
                f"  • 索引 {i} | <Subject {subj_id}>：{item_name} (對應插槽 Picture {p_start}~{p_end}){marker}\n    └ 描述：{item_desc[:60]}..."
            )

        r2v_mapping_prompt = "；\n".join(r2v_lines) + "。"
        all_cast_summary = "\n".join(summary_lines)

        # Tags for currently selected character
        curr_subj_num = clamped_idx + 1
        curr_p_start = clamped_idx * 3 + 1
        curr_p_mid = clamped_idx * 3 + 2
        curr_p_end = clamped_idx * 3 + 3
        current_subject_tag = f"<Subject {curr_subj_num}>"
        current_picture_tags = f"<Picture {curr_p_start}> <Picture {curr_p_mid}> <Picture {curr_p_end}>"

        return (
            char_sheet_prompt,
            cast_count,
            c_name,
            c_desc,
            r2v_mapping_prompt,
            current_subject_tag,
            current_picture_tags,
            all_cast_summary,
        )
