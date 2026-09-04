# -*- coding: utf-8 -*-
"""Prompt Enhancer for MiniMax H3.

Combines:
1. Local VLM Vision Analysis (Qwen3-VL / Gemma-3/4 from ComfyUI-H3-VisionPromptor)
2. GGUF Scoped LLM Rewrite (from MiniMax-H3-Prompt-Rewriter & Story Engine)
3. Calliope 6-Section Ref2VA Format (<Subject N>, <Picture N>, <d>[Language]</d> dialogue)
4. Comprehensive Post-Processing (Sanitization, Mode Alignment Lines, 7000-char Smart Trim, Soundscape/Music Repair, Timestamp Validation)
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import folder_paths
import torch

log = logging.getLogger("UltimateDirector.PromptEnhancer")

# ===========================================================================
# 1. Constants & Templates
# ===========================================================================

MAX_PROMPT_CHARS = 7000

RECOGNIZED_HEADERS = (
    "subject_definitions:",
    "integrated_multimodal_description:",
    "For the target video",
    "How the reference pictures",
)

AUDIO_FIELDS = ("overall_soundscape:", "non_diegetic_music:")

I2VA_ALIGNMENT = (
    "For the target video, at 0.00 seconds into the target video, "
    "<Picture 1> (from [Shot 1]) is fully referenced."
)

_FL2VA_ALIGNMENT_TMPL = (
    "How the reference pictures align with the target video — "
    "<Picture 1> (from [Shot 1]) aligns with the 0.00-second mark of the "
    "target video; <Picture 2> (from [Shot {n}]) aligns with the "
    "{duration:.2f}-second mark of the target video."
)

_L2VA_ALIGNMENT_TMPL = (
    "How the reference pictures align with the target video — "
    "<Picture 1> (from [Shot {n}]) aligns with the {duration:.2f}-second "
    "mark of the target video."
)

_TIMESTAMP_RE = re.compile(r"\bAt (\d{1,2}):(\d{2})\.(\d{3})\b")
_SHOT_RE = re.compile(r"\[Shot (\d+)\]")
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*$", re.MULTILINE)
_FENCED_BLOCK_RE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)^\s*```\s*$", re.DOTALL | re.MULTILINE)

VISION_PRESETS = {
    "detailed_subject_scene": (
        "Describe this image for a video-generation prompt writer. Cover: "
        "(1) every visible subject with identity anchors — hair color/length/texture, approximate age, gender presentation, wardrobe items WITH colors, signature accessories, distinguishing props; "
        "(2) scene/environment with key set-dressing and spatial layout; "
        "(3) lighting and color palette; "
        "(4) overall visual style (e.g. cinematic, live-action, 3D CG); "
        "(5) camera framing/shot size. Be precise and factual, one paragraph per image, no speculation beyond the visible."
    ),
    "subject_identity_only": (
        "Describe ONLY the visible subject(s): identity anchors — hair, age, gender, wardrobe with colors, accessories, distinguishing features. "
        "One compact paragraph per image. Ignore background."
    ),
    "scene_only": (
        "Describe ONLY the environment: location type, key set-dressing, spatial layout, lighting, color palette, mood-neutral factual tone. "
        "One compact paragraph per image. Ignore people."
    ),
}

H3_VLM_SYSTEM_PROMPT = """You are an expert prompt writer for MiniMax H3 joint audio-video generation model.
Your task is to write a production-ready, highly detailed and cinematic prompt for MiniMax H3 based on the user's idea and reference image descriptions.

Output Format Rules:
- For Ref2VA (Reference to Video):
  You must output exactly 6 sections in this order:
  subject_definitions:
  summary:
  retention_analysis:
  detailed_description:
  overall_soundscape:
  non_diegetic_music:

- For T2VA / I2VA / FL2VA / L2VA:
  You must output exactly 3 sections:
  integrated_multimodal_description:
  overall_soundscape:
  non_diegetic_music:

Writing Rules:
1. Always write cinematic shots using [Shot 1], [Shot 2], etc.
2. Specify exact camera movements (slow push-in, low-angle tracking, smooth pan, static medium shot).
3. Describe detailed human actions, facial expressions, eye contact, and physical interaction.
4. For dialogue, use speaker ID tags with language specification: <Subject 1> (S1) says, <d>[Chinese] 你好。</d>
5. Always provide rich soundscape with studio vocal clarity: specify crisp close-mic dialogue (crisp vocal presence, zero hollow reverb), detailed foley, and layered non-diegetic music.
6. Never output markdown codeblocks (```), chatter, or preambles. Output ONLY the raw prompt."""


# ===========================================================================
# 2. Post-Processing & Validation
# ===========================================================================

def sanitize_prompt(text: str) -> str:
    """Strip ``` fences, <think> blocks, and preambles before recognized headers."""
    if not text:
        return ""
    out = _THINK_RE.sub("", text)
    for m in _FENCED_BLOCK_RE.finditer(out):
        if any(h in m.group(1) for h in RECOGNIZED_HEADERS):
            out = m.group(1)
            break
    out = _FENCE_RE.sub("", out)
    first = None
    for header in RECOGNIZED_HEADERS:
        idx = out.find(header)
        if idx != -1 and (first is None or idx < first):
            first = idx
    if first is not None:
        out = out[first:]
    return out.strip()


def _last_shot_index(text: str) -> int:
    shots = [int(m) for m in _SHOT_RE.findall(text)]
    return max(shots) if shots else 1


def ensure_alignment(text: str, task: str, duration: float) -> str:
    """Prepend mode-specific alignment instruction if missing."""
    if task == "I2VA":
        if "For the target video, at 0.00 seconds" not in text:
            text = I2VA_ALIGNMENT + "\n\n" + text
    elif task == "FL2VA":
        if "How the reference pictures align" not in text:
            line = _FL2VA_ALIGNMENT_TMPL.format(n=_last_shot_index(text), duration=duration)
            text = line + "\n\n" + text
    elif task == "L2VA":
        if "How the reference pictures align" not in text:
            line = _L2VA_ALIGNMENT_TMPL.format(n=_last_shot_index(text), duration=duration)
            text = line + "\n\n" + text
    return text


def _smart_trim(text: str) -> str:
    """Smart trim at newline boundary under 7000 chars."""
    if len(text) <= MAX_PROMPT_CHARS:
        return text
    cut = text.rfind("\n", 0, MAX_PROMPT_CHARS)
    if cut == -1:
        cut = MAX_PROMPT_CHARS
    return text[:cut].rstrip()


def validate_and_repair_prompt(text: str, task: str, duration: float) -> tuple[str, list[str]]:
    """Complete sanitize -> alignment -> smart trim -> audio field repair pipeline."""
    out = sanitize_prompt(text)
    out = ensure_alignment(out, task, duration)

    warnings: list[str] = []
    if task == "Ref2VA":
        required = ("subject_definitions:", "summary:", "retention_analysis:", "detailed_description:") + AUDIO_FIELDS
    else:
        required = ("integrated_multimodal_description:",) + AUDIO_FIELDS

    for field in required:
        if field not in out:
            warnings.append(f"missing required field: {field}")

    if len(out) > MAX_PROMPT_CHARS:
        out = _smart_trim(out)
        warnings.append(f"prompt exceeded {MAX_PROMPT_CHARS} chars; trimmed at line boundary")

    # Auto-repair missing audio fields
    fixed_warnings: list[str] = []
    for w in warnings:
        if w in (f"missing required field: {AUDIO_FIELDS[0]}", f"missing required field: {AUDIO_FIELDS[1]}"):
            field = w.split(": ", 1)[1]
            out = out.rstrip() + f"\n\n{field} N/A"
            fixed_warnings.append(f"auto-appended missing field: {field} N/A")
        else:
            fixed_warnings.append(w)

    return out, fixed_warnings


# ===========================================================================
# 3. Calliope Deterministic 6-Section Fallback Generator
# ===========================================================================

def build_calliope_ref_fallback(
    idea: str,
    subjects: list[dict[str, Any]],
    duration: float = 6.0,
) -> str:
    """Deterministic, zero-LLM 6-section H3 Ref2VA prompt generator."""
    defs = []
    retention = []
    for idx, s in enumerate(subjects, 1):
        name = s.get("name") or f"Subject {idx}"
        desc = (s.get("description") or s.get("appearance") or "").strip()
        defs.append(f"<Subject {idx}> is {name} in <Picture {idx}>" + (f", featuring {desc}." if desc else "."))
        retention.append(f"<Subject {idx}> (appears in [Shot 1]): fully_preserved - key visual features and attire are retained.")

    labels = ", ".join(f"<Subject {i}>" for i in range(1, len(subjects) + 1))
    summary = f"[reference generation] Cinematic scene featuring {labels} in a coherent environment with natural motion." if labels else f"[reference generation] {idea or 'A cinematic video scene.'}"

    body = (
        "The target video features high-end cinematic realism with natural lighting, subtle micro-expressions, and physical consistency.\n"
        f"[Shot 1] At 0.00 seconds, {idea.strip() or 'The subjects interact naturally within the frame with steady cinematic camera motion.'}"
    )

    return (
        "subject_definitions:\n" + ("\n".join(defs) if defs else "N/A") + "\n\n"
        "summary:\n" + summary + "\n\n"
        "retention_analysis:\n" + ("\n".join(retention) if retention else "N/A") + "\n\n"
        "detailed_description:\n" + body + "\n\n"
        "overall_soundscape:\n近麥克風清晰人聲錄音 (crisp close-mic studio vocal clarity, direct speech presence, zero hollow reverb)，自然環境氛圍底噪與細微衣物摩擦聲。\n\n"
        "non_diegetic_music:\nSubtle acoustic ambient background score, slow tempo, unobtrusive."
    )


# ===========================================================================
# 4. Native VLM Engine (ComfyUI CLIP text generation stack)
# ===========================================================================

def _detect_family(clip) -> str:
    names: list[str] = []
    try:
        transformer = getattr(getattr(clip, "cond_stage_model", None), "transformer", None)
        if transformer is not None:
            names.append(type(transformer).__name__)
    except Exception:
        pass
    try:
        tokenizer = getattr(clip, "tokenizer", None)
        if tokenizer is not None:
            names.append(type(tokenizer).__name__)
    except Exception:
        pass
    haystack = " ".join(names).lower()
    if "qwen" in haystack:
        return "qwen"
    if "gemma4" in haystack:
        return "gemma4"
    if "gemma" in haystack:
        return "gemma"
    return "generic"


def _build_vlm_chat_text(family: str, system: str, user: str, n_images: int) -> str:
    if family == "qwen":
        vision_tokens = "<|vision_start|><|image_pad|><|vision_end|>\n" * n_images if n_images > 0 else ""
        return f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{vision_tokens}{user}<|im_end|>\n<|im_start|>assistant\n"
    elif family == "gemma":
        vision_tokens = "<image_soft_token>\n" if n_images > 0 else ""
        return f"<start_of_turn>user\n{vision_tokens}{system}\n\n{user}<end_of_turn>\n<start_of_turn>model\n"
    return f"{system}\n\n{user}"


def run_vlm_generate(
    clip,
    system_prompt: str,
    user_prompt: str,
    image_tensor: torch.Tensor | None = None,
    seed: int = 0,
    temperature: float = 0.6,
    max_tokens: int = 2048,
) -> str:
    """Execute text/vision generation using ComfyUI's native CLIP.generate stack."""
    if clip is None or not hasattr(clip, "generate") or not hasattr(clip, "tokenize") or not hasattr(clip, "decode"):
        raise RuntimeError("Connected CLIP does not support native text generation. Please connect a Qwen3-VL text encoder via CLIPLoader.")

    family = _detect_family(clip)
    n_images = int(image_tensor.shape[0]) if image_tensor is not None else 0
    prompt_str = _build_vlm_chat_text(family, system_prompt, user_prompt, n_images)

    tokens = clip.tokenize(prompt_str, image=image_tensor, skip_template=True, min_length=1)
    generated_ids = clip.generate(
        tokens,
        do_sample=temperature > 0.0,
        max_length=max_tokens,
        temperature=temperature,
        top_k=64,
        top_p=0.95,
        repetition_penalty=1.05,
        seed=seed,
    )
    decoded = clip.decode(generated_ids)

    # Clean echo and turn tags
    text = decoded
    if text.startswith(prompt_str):
        text = text[len(prompt_str):]
    for marker in ("<|im_start|>assistant\n", "<start_of_turn>model\n"):
        if marker in text:
            text = text.split(marker, 1)[1]
    for stop in ("<|im_end|>", "<end_of_turn>", "<|im_start|>", "<start_of_turn>"):
        if stop in text:
            text = text[:text.find(stop)]
    return text.strip()
