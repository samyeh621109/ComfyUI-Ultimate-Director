"""ComfyUI Custom Node wrappers for Ultimate Director.
"""
from __future__ import annotations

import os
import folder_paths

from .lattice import VideoModel, snap_up
from .timeline import Timeline
from .compile import compile_timeline, CompiledPrompt
from .story_engine import StoryEngine
from .continuity import apply_scail_lock, trim_decoded_segment

# Provide a list of supported models for the UI
SUPPORTED_MODELS = [m.value for m in VideoModel]

# Register LLM models directory if not already done
LLM_DIR = os.path.join(folder_paths.models_dir, "LLM")
if "LLM" not in folder_paths.folder_names_and_paths:
    folder_paths.folder_names_and_paths["LLM"] = ([LLM_DIR], {".gguf"})

def get_llm_models():
    try:
        return folder_paths.get_filename_list("LLM")
    except Exception:
        return []

class UltimateDirectorStoryEngineNode:
    """Uses a local GGUF model via llama.cpp to generate a timeline JSON."""
    
    @classmethod
    def INPUT_TYPES(cls):
        models = get_llm_models()
        if not models:
            models = ["No GGUF models found in models/LLM"]
            
        return {
            "required": {
                "llm_model": (models,),
                "story_idea": ("STRING", {"multiline": True, "default": "A turtle and rabbit race..."}),
                "n_ctx": ("INT", {"default": 4096, "min": 512, "max": 128000}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 2.0, "step": 0.05}),
            }
        }
        
    RETURN_TYPES = ("TIMELINE_DICT",)
    RETURN_NAMES = ("timeline",)
    FUNCTION = "generate"
    CATEGORY = "UltimateDirector/Story"

    def generate(self, llm_model, story_idea, n_ctx, temperature):
        if not get_llm_models() or llm_model.startswith("No GGUF"):
            raise ValueError("No LLM model available. Please put a .gguf file in models/LLM")
            
        model_path = folder_paths.get_full_path("LLM", llm_model)
        engine = StoryEngine(model_path=model_path, n_ctx=n_ctx)
        
        timeline_obj = engine.generate_timeline(idea=story_idea, temperature=temperature)
        return (timeline_obj.to_dict(),)


class UltimateDirectorCompilerNode:
    """Compiles a Timeline JSON into a list of SegmentPrompts for the generator."""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "timeline": ("TIMELINE_DICT",),
                "model_type": (SUPPORTED_MODELS, {"default": VideoModel.H3.value}),
                "continuity_overlap_frames": ("INT", {"default": 9, "min": 0, "max": 30}),
            }
        }
        
    RETURN_TYPES = ("SEGMENT_LIST",)
    RETURN_NAMES = ("segments",)
    FUNCTION = "compile"
    CATEGORY = "UltimateDirector/Compiler"

    def compile(self, timeline, model_type, continuity_overlap_frames):
        tl = Timeline.from_dict(timeline)
        model = VideoModel(model_type)
        
        # In a real node, you'd integrate the actual prompt styling here.
        # This compiles the timeline into segment structures that tell the next
        # node exactly how many frames to generate and what prompt to use.
        compiled = compile_timeline(
            timeline=tl, 
            model=model, 
            continuity_enabled=(continuity_overlap_frames > 0),
            overlap_frames=continuity_overlap_frames
        )
        return (compiled,)


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
        
        out_latent, success = apply_scail_lock(
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


NODE_CLASS_MAPPINGS = {
    "UltimateDirectorStoryEngine": UltimateDirectorStoryEngineNode,
    "UltimateDirectorCompiler": UltimateDirectorCompilerNode,
    "UltimateDirectorSCAILLock": UltimateDirectorSCAILLockNode,
    "UltimateDirectorSCAILTrim": UltimateDirectorSCAILTrimNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "UltimateDirectorStoryEngine": "Ultimate Director: Story Engine (LlamaTE)",
    "UltimateDirectorCompiler": "Ultimate Director: Timeline Compiler",
    "UltimateDirectorSCAILLock": "Ultimate Director: SCAIL Latent Lock",
    "UltimateDirectorSCAILTrim": "Ultimate Director: SCAIL Output Trim",
}
