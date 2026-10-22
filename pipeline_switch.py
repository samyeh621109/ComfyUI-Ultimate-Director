"""Ultimate Director: Pipeline Switch & Flow Control Nodes.

Provides rock-solid, Python-level workflow routing and branch gating for ComfyUI.
Replaces brittle frontend DOM muters (e.g. rgthree group muters) with reliable
backend logic and optional lazy evaluation.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

class AnyType(str):
    """Wildcard type for ComfyUI slot connections."""
    def __ne__(self, __value: object) -> bool:
        return False
    def __eq__(self, __value: object) -> bool:
        return True

ANY = AnyType("*")

PIPELINE_MODES = [
    "1_Character_Asset (僅生成角色四視圖)",
    "2_Scene_Prop_Asset (僅生成場景/道具)",
    "3_H3_Video_Generation (H3 雙採視頻生成)",
    "4_SeedVR2_4K_Upscale (4K 高清放大)",
    "5_All_Active (全管線貫通)",
]

class UltimateDirectorPipelineSwitchNode:
    """Master pipeline switch node. Selects which production stage is active."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (PIPELINE_MODES, {"default": PIPELINE_MODES[0]}),
            },
            "optional": {
                "character_data": (ANY,),
                "scene_prop_data": (ANY,),
                "video_data": (ANY,),
                "upscale_data": (ANY,),
            }
        }

    RETURN_TYPES = ("STRING", ANY, "BOOLEAN", "BOOLEAN", "BOOLEAN", "BOOLEAN")
    RETURN_NAMES = (
        "active_mode",
        "routed_data",
        "is_char_active",
        "is_scene_active",
        "is_video_active",
        "is_upscale_active",
    )
    FUNCTION = "switch"
    CATEGORY = "UltimateDirector/Control"

    def check_lazy_status(self, mode: str, **kwargs) -> List[str]:
        """ComfyUI Execution Model v2 lazy evaluation support.
        Only requests inputs for the active mode.
        """
        if "5_All_Active" in mode:
            return ["character_data", "scene_prop_data", "video_data", "upscale_data"]
        elif "1_Character" in mode:
            return ["character_data"]
        elif "2_Scene" in mode:
            return ["scene_prop_data"]
        elif "3_H3_Video" in mode:
            return ["video_data"]
        elif "4_SeedVR2" in mode:
            return ["upscale_data"]
        return []

    def switch(
        self,
        mode: str,
        character_data: Any = None,
        scene_prop_data: Any = None,
        video_data: Any = None,
        upscale_data: Any = None,
    ) -> Tuple[str, Any, bool, bool, bool, bool]:
        is_all = "5_All_Active" in mode
        is_char = "1_Character" in mode or is_all
        is_scene = "2_Scene" in mode or is_all
        is_video = "3_H3_Video" in mode or is_all
        is_upscale = "4_SeedVR2" in mode or is_all

        routed_data = None
        if "1_Character" in mode:
            routed_data = character_data
        elif "2_Scene" in mode:
            routed_data = scene_prop_data
        elif "3_H3_Video" in mode:
            routed_data = video_data
        elif "4_SeedVR2" in mode:
            routed_data = upscale_data
        elif is_all:
            routed_data = video_data if video_data is not None else character_data

        return (
            mode,
            routed_data,
            is_char,
            is_scene,
            is_video,
            is_upscale,
        )


class UltimateDirectorBranchGateNode:
    """Universal branch gate. Passes data only if current active mode matches."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "data": (ANY,),
                "active_mode": ("STRING", {"forceInput": True}),
                "target_pipeline": ([
                    "1_Character_Asset",
                    "2_Scene_Prop_Asset",
                    "3_H3_Video_Generation",
                    "4_SeedVR2_4K_Upscale",
                    "All_Pass",
                ], {"default": "3_H3_Video_Generation"}),
            }
        }

    RETURN_TYPES = (ANY, "BOOLEAN")
    RETURN_NAMES = ("gated_data", "is_passed")
    FUNCTION = "gate"
    CATEGORY = "UltimateDirector/Control"

    def gate(self, data: Any, active_mode: str, target_pipeline: str) -> Tuple[Any, bool]:
        is_match = False
        if target_pipeline == "All_Pass" or "5_All_Active" in active_mode:
            is_match = True
        elif target_pipeline == "1_Character_Asset" and "1_Character" in active_mode:
            is_match = True
        elif target_pipeline == "2_Scene_Prop_Asset" and "2_Scene" in active_mode:
            is_match = True
        elif target_pipeline == "3_H3_Video_Generation" and "3_H3_Video" in active_mode:
            is_match = True
        elif target_pipeline == "4_SeedVR2_4K_Upscale" and "4_SeedVR2" in active_mode:
            is_match = True

        return (data if is_match else None, is_match)


class UltimateDirectorAssetBridgeNode:
    """Bridges Krea 2 Four-View / Scene / Prop assets directly into H3 R2V slot inputs."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {
                "char_face_image": ("IMAGE",),
                "char_body_image": ("IMAGE",),
                "scene_image": ("IMAGE",),
                "prop_image": ("IMAGE",),
                "char_audio_1": ("AUDIO",),
                "char_audio_2": ("AUDIO",),
                "char_audio_3": ("AUDIO",),
                "prompt_template": ("STRING", {
                    "multiline": True,
                    "default": "<Subject 1> [主角色外觀與特徵]\n<Subject 2> [場景環境]\n[鏡頭運鏡與動作描述]"
                }),
            }
        }

    RETURN_TYPES = (
        "IMAGE", "IMAGE", "IMAGE", "IMAGE",
        "AUDIO", "AUDIO", "AUDIO",
        "STRING",
    )
    RETURN_NAMES = (
        "ref_image_1", "ref_image_2", "ref_image_3", "ref_image_4",
        "ref_audio_1", "ref_audio_2", "ref_audio_3",
        "compiled_h3_prompt",
    )
    FUNCTION = "bridge"
    CATEGORY = "UltimateDirector/Bridge"

    def bridge(
        self,
        char_face_image: Any = None,
        char_body_image: Any = None,
        scene_image: Any = None,
        prop_image: Any = None,
        char_audio_1: Any = None,
        char_audio_2: Any = None,
        char_audio_3: Any = None,
        prompt_template: str = "",
    ) -> Tuple[Any, Any, Any, Any, Any, Any, Any, str]:
        # Formatted bridge outputs
        return (
            char_face_image,
            char_body_image,
            scene_image,
            prop_image,
            char_audio_1,
            char_audio_2,
            char_audio_3,
            prompt_template,
        )


class UltimateDirectorVideoOutputSwitchNode:
    """Intelligent Output Switch: Instantly toggle between Raw Passthrough and 4K Upscale/Refine pipeline.
    Supports ComfyUI Lazy Evaluation so the optional post-processing branch is skipped in Raw mode.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": ([
                    "極速直通模式 (Raw Video - 0秒保存成片)",
                    "超分精修模式 (Upscaled Video - 頂級畫質)",
                ], {
                    "default": "極速直通模式 (Raw Video - 0秒保存成片)",
                    "tooltip": "選擇輸出影片：選「極速直通」直接拿 Node 300 導演台原始成片保存（完全不執行後續超分，省下 40 分鐘！）；選「超分精修」則執行已連接的後處理節點。"
                }),
                "raw_video": ("IMAGE", {
                    "lazy": True,
                    "tooltip": "來自 Node 300 MiniMaxH3Director 的原始影片輸出"
                }),
            },
            "optional": {
                "upscaled_video": ("IMAGE", {
                    "lazy": True,
                    "tooltip": "來自後處理節點的影片輸出（可選）"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("video",)
    FUNCTION = "route"
    CATEGORY = "UltimateDirector/Control"

    def check_lazy_status(self, mode: str, raw_video=None, upscaled_video=None):
        needed = []
        if "極速直通" in mode:
            if raw_video is None:
                needed.append("raw_video")
        else:
            if upscaled_video is None:
                needed.append("upscaled_video")
        return needed

    def route(self, mode: str, raw_video=None, upscaled_video=None):
        if "極速直通" in mode:
            if raw_video is not None:
                return (raw_video,)
            return (upscaled_video,)
        else:
            if upscaled_video is not None:
                return (upscaled_video,)
            return (raw_video,)
