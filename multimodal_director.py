# -*- coding: utf-8 -*-
"""Ultimate Multimodal Director for MiniMax H3.

Combines:
1. Storyboard Grid Mode (2x2, 3x2, 3x3 multi-panel splitting & timeline arrangement)
2. Omnipotent Multimodal Reference Canvas (@Picture, @Video, @Audio tags to H3 <Picture N>, <Video N>, <Audio N>)
3. 3-Track Timeline (Visual Storyboard / Motion Reference / Audio Voice & Music)
4. Dynamic canvas aspect ratio calculation (aligned to 32)
5. Robust media loading with Pillow & graceful PyAV handling.
"""

from __future__ import annotations

import inspect
import json
import logging
import math
import os
import re
import secrets
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from aiohttp import web

import folder_paths
from comfy_api.latest import io
from comfy_extras.nodes_minimax_h3 import (
    MiniMaxH3ReferenceToVideo,
    adapt_canvas,
)
from server import PromptServer

log = logging.getLogger("UltimateDirector.MultimodalDirector")

FPS = 24.0
UPLOAD_SUBFOLDER = "ultimate_director"
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}

MAX_UPLOAD_BYTES = {
    "image": 30 * 1024 * 1024,
    "video": 50 * 1024 * 1024,
    "audio": 15 * 1024 * 1024,
}


def _input_root() -> Path:
    return Path(folder_paths.get_input_directory()).resolve()


def _upload_root() -> Path:
    root = (_input_root() / UPLOAD_SUBFOLDER).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_media_path(relative_name: str) -> Path:
    if not relative_name:
        raise ValueError("參考素材缺少檔案名稱。")
    candidate = (_input_root() / str(relative_name).replace("\\", "/")).resolve()
    if os.path.commonpath([str(_input_root()), str(candidate)]) != str(_input_root()):
        raise ValueError("參考素材路徑超出 ComfyUI input 目錄。")
    if not candidate.is_file():
        raise FileNotFoundError(f"找不到參考素材：{relative_name}")
    return candidate


def _media_kind(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        return "image"
    if ext in ALLOWED_VIDEO_EXTENSIONS:
        return "video"
    if ext in ALLOWED_AUDIO_EXTENSIONS:
        return "audio"
    raise ValueError(f"不支援的素材格式：{ext or '未知'}")


def _probe_media(path: Path, kind: str) -> dict:
    info = {"kind": kind, "width": 0, "height": 0, "duration": 0.0, "has_audio": False}
    if kind == "image":
        with Image.open(path) as image:
            info["width"], info["height"] = image.size
        return info

    try:
        import av
        with av.open(str(path)) as container:
            if kind == "video" and container.streams.video:
                stream = container.streams.video[0]
                info["width"] = int(stream.width or 0)
                info["height"] = int(stream.height or 0)
                if stream.duration is not None and stream.time_base is not None:
                    info["duration"] = float(stream.duration * stream.time_base)
                elif container.duration is not None:
                    info["duration"] = float(container.duration / av.time_base)
                info["has_audio"] = bool(container.streams.audio)
            elif kind == "audio" and container.streams.audio:
                stream = container.streams.audio[0]
                if stream.duration is not None and stream.time_base is not None:
                    info["duration"] = float(stream.duration * stream.time_base)
                elif container.duration is not None:
                    info["duration"] = float(container.duration / av.time_base)
    except ImportError:
        info["duration"] = 5.0
        log.warning("PyAV 未安裝，視頻/音頻素材將使用預設元數據。若需精確解碼請安裝 av (pip install av)。")
    return info


# Register upload endpoint
if hasattr(PromptServer, "instance") and PromptServer.instance is not None:
    @PromptServer.instance.routes.post("/ultimate_director/upload")
    async def upload_director_reference(request):
        reader = await request.multipart()
        field = await reader.next()
        while field is not None and field.name != "file":
            field = await reader.next()
        if field is None or not field.filename:
            return web.json_response({"error": "沒有收到素材檔案。"}, status=400)

        original_name = os.path.basename(field.filename)
        try:
            kind = _media_kind(original_name)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original_name).stem).strip("._") or "media"
        ext = Path(original_name).suffix.lower()
        stored_name = f"{int(time.time() * 1000)}_{secrets.token_hex(3)}_{safe_stem}{ext}"
        target = _upload_root() / stored_name
        total = 0
        try:
            with target.open("wb") as output:
                while True:
                    chunk = await field.read_chunk(size=1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_UPLOAD_BYTES[kind]:
                        limit_mb = MAX_UPLOAD_BYTES[kind] // (1024 * 1024)
                        raise ValueError(f"單個{ {'image': '圖片', 'video': '視頻', 'audio': '音頻'}[kind] }不能超過 {limit_mb}MB。")
                    output.write(chunk)
            info = _probe_media(target, kind)
        except Exception as exc:
            if target.exists():
                target.unlink(missing_ok=True)
            return web.json_response({"error": str(exc)}, status=400)

        relative_name = f"{UPLOAD_SUBFOLDER}/{stored_name}"
        return web.json_response(
            {
                "name": relative_name,
                "original_name": original_name,
                "size": total,
                **info,
            }
        )


def _load_image(path: Path) -> torch.Tensor:
    with Image.open(path) as image:
        array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def _load_video(path: Path) -> torch.Tensor:
    try:
        import av
    except ImportError:
        raise RuntimeError("解碼參考視頻需要安裝 PyAV (pip install av)。")

    frames = []
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError(f"視頻沒有畫面軌道：{path.name}")
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        canvas_w, canvas_h = adapt_canvas(int(stream.width), int(stream.height))
        source_rate = float(stream.average_rate) if stream.average_rate else FPS
        previous = None
        previous_time = 0.0
        next_time = 0.0
        decoded_index = 0
        for frame in container.decode(stream):
            frame_time = frame.time
            if frame_time is None:
                frame_time = decoded_index / max(source_rate, 1.0)
            decoded_index += 1
            if frame_time > 15.05:
                break
            current = frame.reformat(width=canvas_w, height=canvas_h, format="rgb24").to_ndarray()
            if previous is None:
                previous = current
                previous_time = float(frame_time)
            while next_time <= float(frame_time) + 1e-6 and len(frames) < int(15 * FPS):
                use_current = abs(float(frame_time) - next_time) <= abs(previous_time - next_time)
                frames.append(current if use_current else previous)
                next_time += 1.0 / FPS
            previous = current
            previous_time = float(frame_time)
    if not frames:
        raise ValueError(f"無法解碼參考視頻：{path.name}")
    array = np.stack(frames).astype(np.float32) / 255.0
    return torch.from_numpy(array)


def _load_audio(path: Path) -> dict:
    try:
        import av
    except ImportError:
        raise RuntimeError("解碼參考音頻需要安裝 PyAV (pip install av)。")

    chunks = []
    sample_rate = 32000
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise ValueError(f"素材沒有音頻軌道：{path.name}")
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=sample_rate)
        for frame in container.decode(stream):
            for converted in resampler.resample(frame):
                chunks.append(torch.from_numpy(converted.to_ndarray().copy()))
        for converted in resampler.resample(None):
            chunks.append(torch.from_numpy(converted.to_ndarray().copy()))
    if not chunks:
        raise ValueError(f"無法解碼參考音頻：{path.name}")
    waveform = torch.cat(chunks, dim=-1).float()
    return {"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate}


def _split_storyboard(images: torch.Tensor | None, layout: str, crop_strength: float) -> list[torch.Tensor]:
    if images is None:
        return []
    match = re.search(r"(\d+)\s*x\s*(\d+)", str(layout or ""), re.I)
    cols, rows = (int(match.group(1)), int(match.group(2))) if match else (3, 2)
    count = cols * rows
    if int(images.shape[0]) > 1:
        return [images[index : index + 1] for index in range(min(count, int(images.shape[0])))]

    source = images[:1]
    _, height, width, _ = source.shape
    strength = max(0.0, min(3.0, float(crop_strength)))
    result = []
    for index in range(count):
        col = index % cols
        row = index // cols
        x0 = int(round(col * width / cols))
        x1 = int(round((col + 1) * width / cols))
        y0 = int(round(row * height / rows))
        y1 = int(round((row + 1) * height / rows))
        inset_x = int(round((x1 - x0) * 0.012 * strength))
        inset_y = int(round((y1 - y0) * 0.012 * strength))
        if x1 - x0 > inset_x * 2 + 16:
            x0, x1 = x0 + inset_x, x1 - inset_x
        if y1 - y0 > inset_y * 2 + 16:
            y0, y1 = y0 + inset_y, y1 - inset_y
        result.append(source[:, y0:y1, x0:x1, :])
    return result


def _save_storyboard_previews(cells: list[torch.Tensor]) -> list[dict]:
    if not cells:
        return []
    preview_dir = Path(folder_paths.get_temp_directory()) / UPLOAD_SUBFOLDER
    preview_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{int(time.time() * 1000)}_{secrets.token_hex(3)}"
    previews = []
    try:
        for index, cell in enumerate(cells):
            array = cell[0].detach().float().clamp(0, 1).mul(255).byte().cpu().numpy()
            image = Image.fromarray(array, mode="RGB")
            image.thumbnail((640, 640), Image.Resampling.LANCZOS)
            filename = f"grid_{run_id}_{index + 1}.jpg"
            image.save(preview_dir / filename, "JPEG", quality=86, optimize=True)
            previews.append({"filename": filename, "subfolder": UPLOAD_SUBFOLDER, "type": "temp"})
    except Exception as exc:
        log.warning("無法生成 H3 宮格預覽：%s", exc)
        return []
    return previews


def _align_frame_count(seconds: float) -> int:
    frames = max(5, int(round(max(4.0, min(15.0, float(seconds))) * FPS)))
    while frames % 17 != 5:
        frames += 1
    return frames


ASPECT_RATIOS: dict[str, float] = {
    # 台灣繁體標準名稱
    "16:9 橫向": 16 / 9,
    "9:16 直向": 9 / 16,
    "4:3 橫向": 4 / 3,
    "3:4 直向": 3 / 4,
    "1:1 方形": 1.0,
    "21:9 超寬螢幕": 21 / 9,
    "9:21 超長直向": 9 / 21,
    # 純比例格式
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
    "1:1": 1.0,
    "21:9": 21 / 9,
    "9:21": 9 / 21,
    # 相容舊版名稱
    "16:9 横屏": 16 / 9,
    "9:16 竖屏": 9 / 16,
    "4:3 横屏": 4 / 3,
    "3:4 竖屏": 3 / 4,
    "21:9 超宽屏": 21 / 9,
    "9:21 超长竖屏": 9 / 21,
}

# MiniMax H3 官方原生最佳解析度標準（768p 原生短邊）
H3_NATIVE_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "16:9": (1344, 768),
    "9:16": (768, 1344),
    "4:3": (1024, 768),
    "3:4": (768, 1024),
    "1:1": (768, 768),
    "21:9": (1536, 672),
    "9:21": (672, 1536),
}


def _parse_aspect_ratio(aspect_name: str, first_visual: torch.Tensor | None = None) -> float:
    """Robust aspect ratio parser with regex and tensor fallback."""
    if not aspect_name:
        return 16 / 9

    clean_name = str(aspect_name).strip()
    if clean_name in ASPECT_RATIOS:
        return ASPECT_RATIOS[clean_name]

    # Try regex match (e.g., "16:9", "9:16", "21/9", "4：3")
    match = re.search(r"(\d+(?:\.\d+)?)\s*[:：/]\s*(\d+(?:\.\d+)?)", clean_name)
    if match:
        try:
            w, h = float(match.group(1)), float(match.group(2))
            if h > 0:
                return w / h
        except (ValueError, ZeroDivisionError):
            pass

    # Follow first visual material
    if ("跟隨" in clean_name or "跟随" in clean_name or "自動" in clean_name or "自动" in clean_name) and first_visual is not None:
        if first_visual.ndim >= 3:
            h = float(first_visual.shape[1] if first_visual.ndim == 3 else first_visual.shape[1])
            w = float(first_visual.shape[2] if first_visual.ndim == 3 else first_visual.shape[2])
            if h > 0:
                return w / h

    if first_visual is not None and first_visual.ndim >= 3:
        h = float(first_visual.shape[1])
        w = float(first_visual.shape[2])
        if h > 0:
            return w / h

    return 16 / 9


def _canvas_size(
    aspect_name: str,
    first_visual: torch.Tensor | None,
    megapixels: float,
    multiple: int,
) -> tuple[int, int]:
    """Computes exact canvas dimensions aligned to DiT multiple (default 32) and native H3 scale."""
    ratio = _parse_aspect_ratio(aspect_name, first_visual)
    megapixels = max(0.1, min(16.0, float(megapixels)))
    multiple = max(8, min(128, int(multiple)))
    
    # If megapixels is around standard 1.0 MP and matches standard ratios, use native anchors scaled
    total_pixels = megapixels * 1024 * 1024
    scale = math.sqrt(total_pixels / (1024 * 1024))
    
    # Base calculation aligned to multiple
    target_w = math.sqrt(total_pixels * ratio)
    target_h = math.sqrt(total_pixels / ratio)
    
    width = max(multiple, int(round(target_w / multiple) * multiple))
    height = max(multiple, int(round(target_h / multiple) * multiple))
    return width, height


def _timeline_items(raw: str) -> tuple[dict, list[dict]]:
    try:
        data = json.loads(raw) if raw else {}
    except Exception as exc:
        raise ValueError(f"導演台時間線數據損壞：{exc}") from exc
    if not isinstance(data, dict):
        data = {}
    items = data.get("items") or []
    return data, [item for item in items if isinstance(item, dict)]


def _duration_of_audio(audio: dict) -> float:
    waveform = audio.get("waveform")
    rate = float(audio.get("sample_rate") or 1)
    return float(waveform.shape[-1]) / rate if waveform is not None else 0.0


def _validate_reference_duration(duration: float, name: str, kind: str) -> None:
    label = "影片" if kind == "video" else "音訊"
    if duration < 1.99:
        raise ValueError(f"參考{label}「{name}」只有 {duration:.2f} 秒，H3 要求單個素材至少 2 秒。")
    if duration > 15.01:
        raise ValueError(f"參考{label}「{name}」為 {duration:.2f} 秒，超過 H3 的 15 秒上限。")


def _compile_prompt(global_prompt: str, items: list[dict], tag_by_id: dict[str, str], actual_seconds: float,
                    storyboard_indices: list[int]) -> str:
    parts = []
    base = str(global_prompt or "").strip()
    if base:
        parts.append(base)

    reference_lines = []
    for item in items:
        if item.get("source") == "storyboard":
            continue
        tag = tag_by_id.get(str(item.get("id", "")))
        if tag:
            label = str(item.get("name") or item.get("originalName") or item.get("kind") or "參考素材")
            reference_lines.append(f"{tag}：{label}")
        audio_tag = tag_by_id.get(f"{item.get('id', '')}:audio")
        if audio_tag:
            reference_lines.append(f"{audio_tag}：{label}的原始聲音")
    for index in storyboard_indices:
        tag = tag_by_id.get(f"storyboard_{index}")
        if tag:
            reference_lines.append(f"{tag}：第{index + 1}張宮格分鏡圖")
    if reference_lines:
        parts.append("參考素材對應關係：\n" + "\n".join(reference_lines))

    visual_items = [
        item for item in items
        if item.get("kind") in ("image", "video")
        and item.get("source") != "storyboard"
        and str(item.get("track") or "visual") == "visual"
    ]
    timeline_lines = []
    for item in sorted(visual_items, key=lambda value: float(value.get("start", 0) or 0)):
        start = max(0.0, float(item.get("start", 0) or 0))
        duration = max(0.1, float(item.get("duration", 1) or 1))
        end = min(actual_seconds, start + duration)
        prompt = str(item.get("prompt") or "").strip()
        sound = str(item.get("sound") or "").strip()
        item_id = str(item.get("id", ""))
        tag = tag_by_id.get(item_id, "")
        audio_tag = tag_by_id.get(f"{item_id}:audio", "")
        references = " ".join(part for part in (tag, audio_tag) if part)
        description = " ".join(part for part in (references, prompt) if part).strip() or "保持參考素材的主體與場景連續。"
        if sound:
            description += f" 聲音：{sound}"
        timeline_lines.append((start, f"[{start:.2f}秒-{end:.2f}秒] {description}"))

    storyboard_items = {
        int(item.get("gridIndex", index)): item
        for index, item in enumerate(items)
        if item.get("source") == "storyboard"
    }
    if storyboard_indices and storyboard_items:
        segment = actual_seconds / max(1, len(storyboard_indices))
        for position, index in enumerate(storyboard_indices):
            item = storyboard_items.get(index, {})
            start = max(0.0, float(item.get("start", segment * position) or 0))
            duration = max(0.1, float(item.get("duration", segment) or segment))
            end = min(actual_seconds, start + duration)
            tag = tag_by_id.get(f"storyboard_{index}", "")
            item_prompt = str(item.get("prompt") or "").strip()
            description = item_prompt or "保持該分鏡的主體、動作和場景連續。"
            sound = str(item.get("sound") or "").strip()
            if sound:
                description += f" 聲音：{sound}"
            timeline_lines.append((start, f"[{start:.2f}秒-{end:.2f}秒] {tag} {description}".strip()))

    if timeline_lines:
        parts.append("主畫面時間線：\n" + "\n".join(line for _, line in sorted(timeline_lines, key=lambda entry: entry[0])))

    motion_lines = []
    motion_items = [
        item for item in items
        if item.get("kind") == "video" and str(item.get("track") or "") == "motion"
    ]
    for item in sorted(motion_items, key=lambda value: float(value.get("start", 0) or 0)):
        start = max(0.0, float(item.get("start", 0) or 0))
        duration = max(0.1, float(item.get("duration", 1) or 1))
        end = min(actual_seconds, start + duration)
        item_id = str(item.get("id", ""))
        tag = tag_by_id.get(item_id, "")
        audio_tag = tag_by_id.get(f"{item_id}:audio", "")
        instruction = str(item.get("prompt") or "參考其中的人物動作、表演節奏與攝影機運動").strip()
        references = " ".join(part for part in (tag, audio_tag) if part)
        motion_lines.append(f"[{start:.2f}秒-{end:.2f}秒] {references} {instruction}".strip())
    if motion_lines:
        parts.append("動作與運鏡參考：\n" + "\n".join(motion_lines))

    audio_lines = []
    for item in items:
        if item.get("kind") == "audio" or str(item.get("track") or "") == "audio":
            start = max(0.0, float(item.get("start", 0) or 0))
            duration = max(0.1, float(item.get("duration", actual_seconds) or actual_seconds))
            end = min(actual_seconds, start + duration)
            tag = tag_by_id.get(str(item.get("id", "")), "")
            instruction = str(item.get("prompt") or item.get("sound") or "參考其音色、節奏或聲音氛圍").strip()
            audio_lines.append(f"[{start:.2f}秒-{end:.2f}秒] {tag}：{instruction}".strip("："))
    if audio_lines:
        parts.append("聲音參考：\n" + "\n".join(audio_lines))

    prompt = "\n\n".join(parts).strip()
    if len(prompt) > 7000:
        raise ValueError(f"編譯後的提示詞為 {len(prompt)} 個字符，超過 H3 的 7000 字符上限。")
    return prompt


def _compile_reference_prompt(reference_prompt: str, items: list[dict], tag_by_id: dict[str, str]) -> str:
    compiled = str(reference_prompt or "").strip()
    counters = {"image": 0, "video": 0, "audio": 0}
    labels_cn = {"image": "图片", "video": "视频", "audio": "音频"}
    labels_tw = {"image": "圖片", "video": "影片", "audio": "音訊"}

    for item in items:
        kind = str(item.get("kind") or "")
        if kind not in counters:
            continue
        counters[kind] += 1
        token_cn = f"@{labels_cn[kind]}{counters[kind]}"
        token_tw = f"@{labels_tw[kind]}{counters[kind]}"
        item_id = str(item.get("id") or "")
        tag = tag_by_id.get(item_id)
        if not tag:
            continue
        compiled = re.sub(rf"{re.escape(token_cn)}(?!\d)", tag, compiled)
        compiled = re.sub(rf"{re.escape(token_tw)}(?!\d)", tag, compiled)
    return compiled


class UltimateDirectorMultimodalDirector(io.ComfyNode):
    """Ultimate Multimodal Director Node. Dual-mode Storyboard & Omnipotent Reference Studio."""

    @classmethod
    def check_legacy_registration(cls):
        return True

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="UltimateDirectorMultimodalDirector",
            display_name="🎬 終極導演：多模態參考導演台 (Multimodal Studio)",
            category="UltimateDirector/Studio",
            description="雙模式 MiniMax H3 導演台：提供宮格分鏡拆切與全能多模態參考畫布，自動產生 <Picture N>、<Video N>、<Audio N> 標籤與影音條件。",
            inputs=[
                io.Model.Input("model", display_name="模型"),
                io.Clip.Input("clip", display_name="H3 文字編碼器"),
                io.Vae.Input("video_vae", display_name="H3 視訊 VAE"),
                io.Vae.Input("audio_vae", display_name="H3 音訊 VAE"),
                io.Combo.Input("mode", display_name="導演台模式", options=["全能參考", "宮格模式"], default="全能參考"),
                io.Float.Input("duration_seconds", display_name="目標時長（秒）", default=5.0, min=4.0, max=15.0, step=0.1),
                io.Combo.Input(
                    "aspect_ratio",
                    display_name="輸出比例",
                    options=["16:9 橫向", "9:16 直向", "4:3 橫向", "3:4 直向", "1:1 方形", "21:9 超寬螢幕", "自動（跟隨首個素材）"],
                    default="16:9 橫向",
                ),
                io.Combo.Input(
                    "ref_image_size",
                    display_name="參考圖精度",
                    options=["匹配輸出（推薦）", "最高保真（更慢）"],
                    default="匹配輸出（推薦）",
                ),
                io.String.Input("global_prompt", display_name="全域創作要求", multiline=True, default="", optional=True),
                io.String.Input("timeline_data", display_name="導演台數據", multiline=True, default="{}"),
                io.Combo.Input(
                    "grid_layout",
                    display_name="宮格格式",
                    options=["2x2 四宮格", "3x2 六宮格", "3x3 九宮格"],
                    default="3x2 六宮格",
                ),
                io.Float.Input("grid_border_crop", display_name="白邊裁剪強度", default=1.0, min=0.0, max=3.0, step=0.05),
                io.Float.Input(
                    "output_megapixels",
                    display_name="輸出像素規模（MP）",
                    default=0.4,
                    min=0.1,
                    max=16.0,
                    step=0.1,
                ),
                io.Int.Input(
                    "resolution_multiple",
                    display_name="尺寸對齊倍數",
                    default=32,
                    min=8,
                    max=128,
                    step=4,
                ),
            ],
            outputs=[
                io.Model.Output(display_name="模型"),
                io.Conditioning.Output(display_name="正向條件"),
                io.Latent.Output(display_name="影音潛空間"),
            ],
        )

    @classmethod
    def execute(
        cls,
        model,
        clip,
        video_vae,
        audio_vae,
        mode,
        duration_seconds,
        aspect_ratio,
        ref_image_size,
        global_prompt="",
        timeline_data="{}",
        grid_layout="3x2 六宫格",
        grid_border_crop=1.0,
        output_megapixels=0.4,
        resolution_multiple=32,
    ) -> io.NodeOutput:
        mode = "全能參考" if mode == "全能參考" else "宮格模式"
        data, items = _timeline_items(timeline_data)
        global_prompt = str(global_prompt or data.get("globalPrompt") or "").strip()
        reference_prompt = str(data.get("allReferencePrompt") or "").strip()
        frame_count = _align_frame_count(duration_seconds)
        actual_seconds = frame_count / FPS

        grid_mode = mode == "宮格模式"
        active_items = []
        for item in items:
            if item.get("source") == "storyboard":
                if grid_mode:
                    active_items.append(item)
                continue
            scope = str(item.get("scope") or "reference")
            if (grid_mode and scope == "grid") or (not grid_mode and scope != "grid"):
                active_items.append(item)

        motion_track_enabled = not grid_mode or data.get("motionTrackEnabled", True) is not False
        audio_track_enabled = not grid_mode or data.get("audioTrackEnabled", True) is not False
        runtime_items = []
        for item in active_items:
            track = str(item.get("track") or ("audio" if item.get("kind") == "audio" else "visual"))
            if grid_mode and track == "motion" and not motion_track_enabled:
                continue
            if grid_mode and track == "audio" and not audio_track_enabled:
                continue
            runtime_items.append(item)

        imported_grid = data.get("gridImage") if grid_mode else None
        storyboard_source = None
        if isinstance(imported_grid, dict) and imported_grid.get("file"):
            storyboard_source = _load_image(_safe_media_path(str(imported_grid["file"])))
        storyboard_cells = (
            _split_storyboard(storyboard_source, grid_layout, grid_border_crop)
            if grid_mode else []
        )
        if grid_mode and not storyboard_cells:
            raise ValueError("宮格模式未導入宮格圖像，請點擊導演台中的“導入宮格圖”。")

        storyboard_previews = _save_storyboard_previews(storyboard_cells) if grid_mode else []
        hidden_storyboard_indices = {
            int(index)
            for index in (data.get("hiddenStoryboardIndices") or [])
            if str(index).lstrip("-").isdigit()
        }
        storyboard_indices = [
            index for index in range(len(storyboard_cells))
            if index not in hidden_storyboard_indices
        ]

        image_entries: list[tuple[str, torch.Tensor]] = [
            (f"storyboard_{index}", storyboard_cells[index]) for index in storyboard_indices
        ]
        uploaded_images = []
        uploaded_videos = []
        uploaded_audios = []
        for item in runtime_items:
            kind = str(item.get("kind") or "")
            if kind not in ("image", "video", "audio") or not item.get("file"):
                continue
            path = _safe_media_path(str(item["file"]))
            if kind == "image":
                uploaded_images.append((str(item.get("id")), _load_image(path)))
            elif kind == "video":
                video = _load_video(path)
                _validate_reference_duration(float(video.shape[0]) / FPS, path.name, "video")
                paired_audio = (
                    _load_audio(path)
                    if audio_track_enabled
                    and bool(item.get("includeAudio"))
                    and _probe_media(path, "video")["has_audio"]
                    else None
                )
                if paired_audio is not None:
                    _validate_reference_duration(_duration_of_audio(paired_audio), f"{path.name} 的原聲", "audio")
                uploaded_videos.append((str(item.get("id")), video, paired_audio))
            else:
                audio = _load_audio(path)
                _validate_reference_duration(_duration_of_audio(audio), path.name, "audio")
                uploaded_audios.append((str(item.get("id")), audio))

        image_entries.extend(uploaded_images)
        if len(image_entries) > 9:
            raise ValueError(f"參考圖片共 {len(image_entries)} 張，超過 H3 的 9 張上限。")

        video_entries = list(uploaded_videos)
        if len(video_entries) > 3:
            raise ValueError(f"參考視頻共 {len(video_entries)} 段，超過 H3 的 3 段上限。")

        audio_entries = list(uploaded_audios)
        if len(audio_entries) > 3:
            raise ValueError(f"獨立參考音頻共 {len(audio_entries)} 段，超過 H3 的 3 段上限。")

        first_visual = None
        if first_visual is None and image_entries:
            first_visual = image_entries[0][1]
        if first_visual is None and video_entries:
            first_visual = video_entries[0][1][:1]

        width, height = _canvas_size(
            aspect_ratio,
            first_visual,
            output_megapixels,
            resolution_multiple,
        )

        if not image_entries and not video_entries and audio_entries:
            raise ValueError("H3 參考音頻不能單獨使用，請至少添加一張圖片或一段視頻。")

        ref_images = {}
        ref_videos = {}
        ref_video_audios = {}
        ref_audios = {}
        tag_by_id = {}
        for index, (item_id, image) in enumerate(image_entries, start=1):
            ref_images[f"ref_image_{index}"] = image
            tag_by_id[item_id] = f"<Picture {index}>"
        audio_number = 1
        for index, (item_id, video, paired_audio) in enumerate(video_entries, start=1):
            ref_videos[f"ref_video_{index}"] = video
            tag_by_id[item_id] = f"<Video {index}>"
            if paired_audio is not None:
                ref_video_audios[f"ref_video_audio_{index}"] = paired_audio
                tag_by_id[f"{item_id}:audio"] = f"<Audio {audio_number}>"
                audio_number += 1
        for index, (item_id, audio) in enumerate(audio_entries, start=1):
            ref_audios[f"ref_audio_{index}"] = audio
            tag_by_id[item_id] = f"<Audio {audio_number}>"
            audio_number += 1

        prompt = (
            _compile_prompt(
                global_prompt,
                runtime_items,
                tag_by_id,
                actual_seconds,
                storyboard_indices,
            )
            if grid_mode
            else _compile_reference_prompt(reference_prompt or global_prompt, runtime_items, tag_by_id)
        )

        ref_size_val = "max" if ref_image_size.startswith("最高") else "match"
        sig = inspect.signature(MiniMaxH3ReferenceToVideo.execute)
        params = list(sig.parameters.keys())
        if len(params) > 1 and params[1] == "prompt":
            result = MiniMaxH3ReferenceToVideo.execute(
                clip=clip,
                prompt=prompt,
                width=width,
                height=height,
                length=frame_count,
                ref_image_size=ref_size_val,
                vae=video_vae,
                audio_vae=audio_vae,
                ref_images=ref_images,
                ref_videos=ref_videos,
                ref_video_audios=ref_video_audios,
                ref_audios=ref_audios,
            )
        else:
            result = MiniMaxH3ReferenceToVideo.execute(
                clip,
                video_vae,
                audio_vae,
                prompt,
                width,
                height,
                frame_count,
                ref_image_size=ref_size_val,
                ref_images=ref_images,
                ref_videos=ref_videos,
                ref_video_audios=ref_video_audios,
                ref_audios=ref_audios,
            )
        summary = (
            f"{mode}｜{len(ref_images)}圖 {len(ref_videos)}視頻 "
            f"{len(ref_video_audios) + len(ref_audios)}音頻｜{frame_count}幀｜{width}x{height}"
        )

        return io.NodeOutput(
            model,
            result.result[0],
            result.result[1],
            ui={
                "compiled_prompt": [prompt],
                "summary": [summary],
                "storyboard_previews": storyboard_previews,
            },
        )
class UltimateDirectorMediaDashboardNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "dashboard_data": ("STRING", {"default": "{}", "multiline": True}),
                "mode": (["宮格模式", "全能參考"], {"default": "全能參考"}),
            },
            "optional": {
                "global_prompt": ("STRING", {"multiline": True}),
            }
        }
    RETURN_TYPES = ("DIRECTOR_ASSETS",)
    RETURN_NAMES = ("ASSETS",)
    FUNCTION = "execute"
    CATEGORY = "UltimateDirector/Studio"

    def execute(self, dashboard_data="{}", mode="全能參考", global_prompt=""):
        import json
        import logging
        log = logging.getLogger("UltimateDirector")
        try:
            data = json.loads(dashboard_data)
        except Exception:
            data = {}
            
        items = data.get("items", [])
        assets = {
            "images": {},
            "videos": {},
            "audios": {}
        }
        
        image_idx = 1
        video_idx = 1
        audio_idx = 1
        
        for item in items:
            kind = str(item.get("kind") or "")
            file_name = str(item.get("file") or "")
            if not file_name or not kind:
                continue
                
            try:
                path = _safe_media_path(file_name)
                if kind == "image":
                    assets["images"][f"ref_image_{image_idx}"] = _load_image(path)
                    image_idx += 1
                elif kind == "video":
                    assets["videos"][f"override_video_{video_idx}"] = _load_video(path)
                    if bool(item.get("includeAudio")):
                        try:
                            if _probe_media(path, "video").get("has_audio"):
                                assets["audios"][f"override_video_audio_{video_idx}"] = _load_audio(path)
                        except Exception as a_err:
                            log.warning(f"Failed to load paired audio from {file_name}: {a_err}")
                    video_idx += 1
                elif kind == "audio":
                    assets["audios"][f"override_audio_{audio_idx}"] = _load_audio(path)
                    audio_idx += 1
            except Exception as e:
                log.warning(f"Failed to load media {file_name}: {e}")
                
        return (assets,)
