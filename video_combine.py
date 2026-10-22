# -*- coding: utf-8 -*-
"""Ultimate Director: Video Combine & Export node.

High-quality H.264 + AAC MP4 exporter with HTML5 browser playback.
Provides a self-contained replacement for VHS_VideoCombine without
requiring ComfyUI-VideoHelperSuite.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import torch
import folder_paths

log = logging.getLogger("UltimateDirector.video_combine")


def _find_ffmpeg() -> str:
    """Locate ffmpeg executable from PATH or imageio_ffmpeg."""
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        exe = get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except ImportError:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    raise RuntimeError("ffmpeg not found on PATH or via imageio-ffmpeg.")


def _ensure_even(val: int) -> int:
    val = max(2, int(val))
    return val if val % 2 == 0 else val + 1


def _pad_even_hw(rgb: np.ndarray) -> np.ndarray:
    """Pad H/W to even numbers required by H.264 yuv420p."""
    n, h, w, c = rgb.shape
    eh, ew = _ensure_even(h), _ensure_even(w)
    if eh == h and ew == w:
        return rgb
    padded = np.zeros((n, eh, ew, c), dtype=np.uint8)
    padded[:, :h, :w, :] = rgb
    return padded


def _write_audio_wav(wav_path: str, audio: Dict[str, Any]) -> bool:
    """Write standard ComfyUI AUDIO dict to 16-bit PCM WAV."""
    if not isinstance(audio, dict):
        return False
    wave_t = audio.get("waveform")
    if not isinstance(wave_t, torch.Tensor) or wave_t.numel() == 0:
        return False
    sr = int(audio.get("sample_rate") or 0)
    if sr <= 0:
        return False

    w = wave_t.detach().cpu().float()
    if w.ndim == 2:
        w = w.unsqueeze(0)
    if w.ndim != 3:
        return False
    # Format: [B, C, T] -> transpose first batch element to [T, C]
    w = w[0].transpose(0, 1).contiguous()
    channels = int(w.shape[1])
    if channels <= 0:
        return False

    pcm = (w.clamp(-1.0, 1.0) * 32767.0).to(torch.int16).numpy()
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return True


class UltimateDirectorVideoCombine:
    """High-quality video encoder combining IMAGE frames and optional AUDIO into MP4.
    Includes in-browser HTML5 video player preview.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {"tooltip": "Image frames [B, H, W, C] to assemble into video."}),
            },
            "optional": {
                "frame_rate": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 1.0, "tooltip": "Frames per second (MiniMax H3 default is 24)."}),
                "crf": ("INT", {"default": 20, "min": 0, "max": 51, "step": 1, "tooltip": "H.264 CRF quality (lower = higher quality, 18-23 recommended)."}),
                "filename_prefix": ("STRING", {"default": "Ultimate_Director_Movie", "tooltip": "Prefix for saved MP4 file in output folder."}),
                "save_output": ("BOOLEAN", {"default": True, "tooltip": "Save the video file to ComfyUI output directory."}),
                "audio": ("AUDIO", {"tooltip": "Optional audio track to mux into video."}),
                "format": (["video/h264-mp4", "video/webm", "image/gif"], {"default": "video/h264-mp4"}),
                "loop_count": ("INT", {"default": 0, "min": 0, "max": 100}),
                "pingpong": ("BOOLEAN", {"default": False}),
            },
        }


    RETURN_TYPES = ("STRING", "IMAGE", "AUDIO")
    RETURN_NAMES = ("filenames", "images", "audio")
    OUTPUT_NODE = True
    FUNCTION = "combine"
    CATEGORY = "UltimateDirector"
    DESCRIPTION = "🎬 終極導演：高品質 H.264 影音合成導出器，內建瀏覽器播放器，原生取代 VHS_VideoCombine。"

    def combine(
        self,
        images: torch.Tensor,
        frame_rate: float = 24.0,
        crf: int = 20,
        filename_prefix: str = "Ultimate_Director_Movie",
        save_output: bool = True,
        audio: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        if not isinstance(images, torch.Tensor) or images.ndim != 4:
            raise ValueError(f"Expected 4D image tensor [B, H, W, C], got {type(images)}")

        n_frames, h, w, c = images.shape
        if n_frames == 0:
            raise ValueError("No frames provided to video combine.")

        fps = float(frame_rate) if frame_rate > 0 else 24.0
        ffmpeg_bin = _find_ffmpeg()

        eh, ew = _ensure_even(h), _ensure_even(w)

        # Resolve output destination
        out_dir = folder_paths.get_output_directory() if save_output else folder_paths.get_temp_directory()
        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(
            filename_prefix, out_dir, ew, eh
        )
        file = f"{filename}_{counter:05}_.mp4"
        final_mp4_path = os.path.join(full_output_folder, file)
        os.makedirs(full_output_folder, exist_ok=True)

        tmp_dir = tempfile.mkdtemp(prefix="ud_vcombine_")
        tmp_mp4 = os.path.join(tmp_dir, "temp_out.mp4")
        wav_path = os.path.join(tmp_dir, "temp_audio.wav")

        try:
            has_audio = bool(audio) and _write_audio_wav(wav_path, audio)

            cmd = [
                ffmpeg_bin,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "rawvideo",
                "-vcodec",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                f"{ew}x{eh}",
                "-r",
                f"{fps:.6f}",
                "-i",
                "-",
            ]
            if has_audio:
                cmd += ["-i", wav_path]

            cmd += [
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "veryfast",
                "-crf",
                str(int(crf)),
            ]
            if has_audio:
                cmd += ["-c:a", "aac", "-b:a", "192k"]

            cmd += ["-movflags", "+faststart", tmp_mp4]

            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            # 串流逐幀寫入 FFmpeg 標準輸入，防止 800+ 幀長影片在編碼存檔時產生 30GB+ 記憶體尖峰
            for i in range(n_frames):
                frame_t = images[i:i + 1].detach().cpu().float().clamp(0.0, 1.0)
                frame_np = (frame_t * 255.0).numpy().astype(np.uint8)
                if c >= 3:
                    frame_np = frame_np[..., :3]
                frame_padded = _pad_even_hw(frame_np)
                proc.stdin.write(frame_padded.tobytes())
            proc.stdin.close()
            _, stderr = proc.communicate()

            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="ignore") if stderr else "Unknown ffmpeg error"
                raise RuntimeError(f"FFmpeg encoding failed with code {proc.returncode}: {err_msg}")

            shutil.move(tmp_mp4, final_mp4_path)
            log.info(f"Video saved successfully to: {final_mp4_path} ({n_frames} frames @ {fps} fps)")

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Standard ComfyUI video UI response format (renders interactive player)
        ui_res = {
            "videos": [{
                "filename": file,
                "subfolder": subfolder,
                "type": "output" if save_output else "temp",
                "format": "video/h264-mp4"
            }],
            "images": [{
                "filename": file,
                "subfolder": subfolder,
                "type": "output" if save_output else "temp",
                "format": "video/h264-mp4"
            }],
            "animated": (True,)
        }

        ret_audio = audio if audio is not None else {"waveform": torch.zeros((1, 1, 1)), "sample_rate": 24000}
        return {"ui": ui_res, "result": (final_mp4_path, images, ret_audio)}
