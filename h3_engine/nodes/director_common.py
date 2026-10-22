"""Shared helpers for the MiniMax H3 Director timeline node."""

from __future__ import annotations

import json
import logging

import torch
from comfy_execution.graph_utils import ExecutionBlocker

from ..director.audio_export import (
    AUDIO_MODE_GENERATE,
    build_director_audio_outputs,
    resolve_audio_mode,
    source_audio_report_note,
)
from ..director.frame_align import pad_or_trim_frames
from ..director.gen_timeline import is_prompt_batch_timeline, is_video_batch_task_key
from ..director.plan import build_director_plan, count_all_timeline_segments, count_timeline_segments, plan_summary
from ..director.segment_mp4_export import released_output_slots
from ..director.progress import report_director_planning
from ..lib.image_prep import fit_canvas, fit_video_long_edge
from ..lib.video_io import load_timeline_segment
from ..lib.task_prompts import task_type_combo_options

log = logging.getLogger("ComfyUI-MiniMaxH3-Director")


def timeline_required_inputs() -> dict:
    """Timeline + prompt widgets shared by Director nodes."""
    combo_options, combo_meta = task_type_combo_options()
    return {
        "task_type": (combo_options, combo_meta),
        "global_prompt": (
            "STRING",
            {
                "default": "",
                "multiline": True,
                "tooltip": "Synced from in-node UI (global mode).",
            },
        ),
        "bd_grp_sample": ("BDGROUP", {"default": "采样设置"}),
        "cfg": (
            "FLOAT",
            {"default": 1.0, "min": 0.0, "max": 30.0, "step": 0.01, "tooltip": "CFG for KSampler."},
        ),
        "seed": (
            "INT",
            {
                "default": 0,
                "min": 0,
                "max": 0xFFFFFFFFFFFFFFFF,
                "control_after_generate": True,
                "tooltip": "Random seed for sampling.",
            },
        ),
        "frame_rate": (
            "FLOAT",
            {"default": 24.0, "min": 1.0, "max": 240.0, "step": 0.01, "tooltip": "Timeline / output FPS (H3 trained at 24)."},
        ),
        "width": ("INT", {"default": 864, "min": 32, "max": 8192, "step": 32}),
        "height": ("INT", {"default": 480, "min": 32, "max": 8192, "step": 32}),
        "ref_max_size": ("INT", {"default": 864, "min": 32, "max": 8192, "step": 32}),
        "total_frames": (
            "INT",
            {
                "default": 124,
                "min": 5,
                "max": 100000,
                "tooltip": "Timeline total frames (fl2v = sum of shots). Per-shot generation still capped near 512.",
            },
        ),
        "timeline_data": (
            "STRING",
            {"default": "", "multiline": True, "tooltip": "Internal — video, segments, refs (populated by UI)."},
        ),
    }


def director_perf_inputs() -> dict:
    """Performance widgets shared by Director nodes."""
    return {
        "bd_grp_perf": ("BDGROUP", {"default": "性能"}),
        "clear_vram_between_segments": (
            "BOOLEAN",
            {
                "default": True,
                "tooltip": "段间清理显存：每段结束后卸载模型并清空 CUDA 缓存。",
            },
        ),
        "clear_vram_before_refine": (
            "BOOLEAN",
            {
                "default": False,
                "tooltip": (
                    "二采前清理显存：一采结束后、放大或二采开始前卸载模型并清空 CUDA 缓存。"
                    "默认关。24GB 或一采/二采不同 UNET 时勾上，可降低二采峰值，"
                    "但每段会多一次加载。"
                ),
            },
        ),
        "clear_vram_before_face_refine": (
            "BOOLEAN",
            {
                "default": False,
                "tooltip": (
                    "脸修前清理显存：成片解码后、FaceRefine 开始前卸载模型并清空 CUDA 缓存。"
                    "默认关。未接 FaceRefine 时无效。24GB 或解码后立刻 OOM 时勾上，"
                    "但每段会多一次加载。"
                ),
            },
        ),
        "cache_frames_codec": (
            ["raw", "ffv1"],
            {
                "default": "raw",
                "tooltip": (
                    "分段缓存的像素帧怎么存。"
                    "raw：uint8 .pt，读写快，磁盘大。"
                    "ffv1：无损压缩，体积大约三分之一，命中和写入都会多一次编解码。"
                    "两种都能读；某一段被重新写入时才换成当前选项。"
                    "latent / 音频缓存不受影响。"
                ),
            },
        ),
        "export_source_images": (
            "BOOLEAN",
            {
                "default": False,
                "tooltip": (
                    "将时间轴原片解码到独立的 source_images 输出口；"
                    "需将 source_images 另接预览/合成节点才能查看，不会改变主 images。"
                    "默认关以节省内存。"
                ),
            },
        ),
        "export_pre_face_refine": (
            "BOOLEAN",
            {
                "default": False,
                "tooltip": (
                    "将修脸前的视频输出到 images_pre_face_refine，方便和 images 对比。"
                    "分段导出时同时写入 seg_XXXX_facepre.mp4。"
                    "默认关：该口阻断、下游不执行，也不占成片内存。未接 FaceRefine 时无效。"
                ),
            },
        ),
        # 必须追加在数组末尾：前端按**位置**恢复 widgets_values（本机
        # Comfy.Workflow.NamedValuesRestore 默认关），插在中间会让旧工作流
        # 后面所有控件的取值整体错位。
        "cache_name": (
            "STRING",
            {
                "default": "",
                "tooltip": (
                    "分段缓存目录：output/minimax_seg_cache/<这个名字>_<节点id>/。"
                    "留空 = 只用节点 id（旧行为，已有缓存目录不变）。"
                    "填了名字后，同一张图里的不同导演台、以及节点 id 不同的工作流会分开存放。"
                    "复制工作流后节点 id 通常不变，名字也相同的话仍然共用一个目录；要隔开就改名字。"
                    "非法字符 / \\ : * ? \" < > | 会自动替换成下划线。"
                ),
            },
        ),
    }


def default_timeline_json(
    *,
    task_type: str,
    global_prompt: str,
    total_frames: int,
    frame_rate: float,
    width: int,
    height: int,
    ref_max_size: int,
) -> str:
    return json.dumps(
        {
            "version": 4,
            "editMode": "global",
            "totalFrames": total_frames,
            "frameRate": frame_rate,
            "width": width,
            "height": height,
            "refMaxSize": ref_max_size,
            "output": {
                "mode": "fixed",
                "longEdge": ref_max_size,
                "width": width,
                "height": height,
                "maxExportFrames": 0,
                "exportMode": "all",
                "audioMode": "generate",
                "refImageSize": "match",
            },
            "videoClips": [],
            "video": {
                "fileName": "",
                "videoFile": "",
                "subfolder": "",
                "type": "input",
                "frames": [],
                "frameMap": [],
            },
            "global": {"taskType": task_type, "prompt": global_prompt, "refs": [], "referenceVideo": {}, "continuousReference": False},
            "segments": [
                {
                    "id": "s0",
                    "start": 0,
                    "length": total_frames,
                    "prompt": "",
                    "taskType": "",
                    "refs": [],
                    "referenceVideo": {},
                }
            ],
        },
        ensure_ascii=False,
    )


def prepare_director_plan(
    *,
    timeline_data: str,
    task_type: str,
    global_prompt: str,
    total_frames: int,
    frame_rate: float,
    width: int,
    height: int,
    ref_max_size: int,
    unique_id: str | None,
    i2v_groups=None,
    r2v_groups=None,
    selflift=None,
    refine=None,
    face_refine=None,
):
    from ..director.external_groups import (
        build_plan_from_external_groups,
        validate_external_group_inputs,
    )

    if not timeline_data or not timeline_data.strip():
        timeline_data = default_timeline_json(
            task_type=task_type,
            global_prompt=global_prompt,
            total_frames=total_frames,
            frame_rate=frame_rate,
            width=width,
            height=height,
            ref_max_size=ref_max_size,
        )

    task_key, ext_groups, family = validate_external_group_inputs(
        task_type=task_type,
        i2v_groups=i2v_groups,
        r2v_groups=r2v_groups,
    )

    if ext_groups is not None and family is not None:
        report_director_planning(
            unique_id,
            len(ext_groups),
            timeline_segment_total=len(ext_groups),
        )
        plan = build_plan_from_external_groups(
            ext_groups,
            family=family,
            timeline_data=timeline_data,
            task_type=task_type,
            global_prompt=global_prompt,
            total_frames=total_frames,
            frame_rate=frame_rate,
            width=width,
            height=height,
            ref_max_size=ref_max_size,
        )
        plan = _attach_selflift(plan, selflift)
        plan = _attach_refine(plan, refine)
        plan = _attach_face_refine(plan, face_refine)
        log.info(
            "MiniMax H3 Director: external %s groups × %d (task=%s) | %s",
            family,
            len(ext_groups),
            task_key,
            plan_summary(plan).replace("\n", " | "),
        )
        return plan

    report_director_planning(
        unique_id,
        count_timeline_segments(timeline_data),
        timeline_segment_total=count_all_timeline_segments(timeline_data),
    )

    plan = build_director_plan(
        timeline_data,
        global_task_type=task_type,
        global_prompt=global_prompt,
        total_frames=total_frames,
        frame_rate=frame_rate,
        width=width,
        height=height,
        ref_max_size=ref_max_size,
    )
    plan = _attach_selflift(plan, selflift)
    plan = _attach_refine(plan, refine)
    plan = _attach_face_refine(plan, face_refine)
    log.info(plan_summary(plan).replace("\n", " | "))
    return plan


def _attach_selflift(plan, selflift):
    from ..director.selflift.pack import normalize_selflift_pack

    plan.selflift = normalize_selflift_pack(selflift)
    return plan


def _attach_refine(plan, refine):
    from ..director.refine_pack import normalize_refine_pack

    plan.refine = normalize_refine_pack(
        refine,
        base_width=int(getattr(plan, "width", 0) or 0),
        base_height=int(getattr(plan, "height", 0) or 0),
    )
    return plan


def _attach_face_refine(plan, face_refine):
    from ..director.face_refine.pack import normalize_face_refine_pack

    plan.face_refine = normalize_face_refine_pack(face_refine)
    return plan


def _fit_source_clip_to_plan(plan, raw_clip: torch.Tensor) -> torch.Tensor:
    if plan.output_mode == "fixed":
        return fit_canvas(raw_clip, plan.width, plan.height)
    return fit_video_long_edge(raw_clip, plan.ref_max_size)


def build_source_images_output(
    plan,
    images_out: list[torch.Tensor],
    *,
    split_outputs: bool,
) -> list[torch.Tensor]:
    if split_outputs:
        chunks: list[torch.Tensor] = []
        # images_out is run-order (选择运行), not full timeline order.
        segs = plan.segments
        run_idx = getattr(plan, "run_indices", None)
        if run_idx is not None:
            segs = [
                plan.segments[i]
                for i in sorted(run_idx)
                if 0 <= i < len(plan.segments)
            ]
        for seg, generated in zip(segs, images_out):
            target_len = int(generated.shape[0])
            raw = load_timeline_segment(plan.raw, seg.start_frame, seg.end_frame)
            fitted = _fit_source_clip_to_plan(plan, raw)
            chunks.append(pad_or_trim_frames(fitted, target_len).cpu().float())
        return chunks

    target_len = int(images_out[0].shape[0]) if images_out else int(plan.total_frames or 0)
    raw = load_timeline_segment(plan.raw, 0, target_len)
    fitted = _fit_source_clip_to_plan(plan, raw)
    return [pad_or_trim_frames(fitted, target_len).cpu().float()]


def _empty_source_images_for(images_out: list[torch.Tensor]) -> list[torch.Tensor]:
    if not images_out:
        return [torch.full((1, 1, 1, 3), 0.5)]
    placeholders: list[torch.Tensor] = []
    for img in images_out:
        if isinstance(img, torch.Tensor) and img.ndim == 4:
            h, w, c = int(img.shape[1]), int(img.shape[2]), int(img.shape[3])
        else:
            h, w, c = 1, 1, 3
        placeholders.append(torch.full((1, h, w, c), 0.5))
    return placeholders


def _pad_even_hw_image(img: torch.Tensor) -> torch.Tensor:
    """yuv420p (CreateVideo → SaveVideo) needs even H/W; 1x1 is unplayable on Windows."""
    n, h, w, c = (int(img.shape[0]), int(img.shape[1]), int(img.shape[2]), int(img.shape[3]))
    eh = max(2, h + (h % 2))
    ew = max(2, w + (w % 2))
    if eh == h and ew == w:
        return img
    out = img.new_zeros((n, eh, ew, c))
    out[:, :h, :w].copy_(img)
    return out


def _ensure_nonempty_image_batches(images_out: list[torch.Tensor], *, label: str) -> list[torch.Tensor]:
    fixed: list[torch.Tensor] = []
    for i, img in enumerate(images_out):
        if not isinstance(img, torch.Tensor) or img.ndim != 4:
            raise ValueError(f"Director {label}[{i}] is not a valid IMAGE tensor.")
        if int(img.shape[0]) <= 0:
            h, w, c = int(img.shape[1]), int(img.shape[2]), int(img.shape[3])
            log.warning("Director %s[%d] has 0 frames; emitting 1-frame placeholder.", label, i)
            img = torch.full((1, max(2, h), max(2, w), max(1, c)), 0.5)
        fixed.append(_pad_even_hw_image(img))
    return fixed


def _layout_image_batches(
    plan,
    combined,
    segment_outputs,
    *,
    export_segments: bool,
    is_batch: bool,
    video_batch: bool,
) -> tuple[list[torch.Tensor], int]:
    if export_segments or (is_batch and not video_batch):
        images_out = segment_outputs
        frame_count = sum(int(s.shape[0]) for s in segment_outputs)
        return images_out, frame_count
    # 「保完整」segments are longer than the UI total; cropping here would
    # cut the kept remainder and desync concatenated audio.
    if getattr(plan, "continuity_enabled", False) and getattr(plan, "continuity_keep_tail", True):
        combined = combined.cpu().float()
    else:
        combined = pad_or_trim_frames(combined, plan.total_frames).cpu().float()
    return [combined], int(combined.shape[0])


def finalize_director_outputs(
    plan,
    combined,
    segment_outputs,
    report,
    *,
    export_source_images: bool = False,
    segment_audios: list | None = None,
    segment_frame_counts: list[int] | None = None,
    pre_refine_combined=None,
    pre_refine_segments: list | None = None,
    pre_face_combined=None,
    pre_face_segments: list | None = None,
    export_pre_face_refine: bool = False,
    block_final_images: bool = False,
):
    is_batch = is_prompt_batch_timeline(plan.raw, plan.global_task_key)
    export_segments = plan.export_mode == "segments"
    video_batch = is_video_batch_task_key(plan.global_task_key)
    split_layout = export_segments or (is_batch and not video_batch)

    images_out, frame_count = _layout_image_batches(
        plan,
        combined,
        segment_outputs,
        export_segments=export_segments,
        is_batch=is_batch,
        video_batch=video_batch,
    )
    if segment_frame_counts:
        frame_count = int(sum(int(n) for n in segment_frame_counts))
    released_slots: list[int] = []
    if export_segments and len(segment_outputs) > 1:
        released_slots = released_output_slots(segment_outputs, segment_frame_counts)
        mp4_dir = getattr(plan, "segment_mp4_run_dir", None)
        if released_slots:
            where = f" Full clips stay in {mp4_dir}." if mp4_dir else ""
            report = (
                report
                + f"\n\nExport mode: segments — {len(segment_outputs)} clip(s); "
                f"{len(released_slots)} released clip(s) omitted from images "
                "so CreateVideo → SaveVideo do not write stills."
                + where
            )
        else:
            report = (
                report
                + f"\n\nExport mode: segments — {len(segment_outputs)} clip(s) on images output."
            )
    if plan.run_indices is not None and split_layout:
        report = (
            report
            + f"\n\nPartial run: output contains {len(segment_outputs)} re-generated clip(s) only."
        )
    if not split_layout:
        if video_batch and is_batch and len(segment_outputs) > 1:
            report = report + f"\n\nExport mode: all — merged {frame_count} frame(s) on images output."
        if plan.run_indices is not None and video_batch:
            report = report + f"\n\nPartial run: re-generated {len(segment_outputs)} video group(s)."

    pre_segs = pre_refine_segments if pre_refine_segments else segment_outputs
    pre_comb = pre_refine_combined if pre_refine_combined is not None else combined
    share_pre = pre_comb is combined and (
        pre_segs is segment_outputs
        or (
            len(pre_segs) == len(segment_outputs)
            and all(a is b for a, b in zip(pre_segs, segment_outputs))
        )
    )
    if share_pre:
        pre_refine_out = images_out
    else:
        try:
            pre_refine_out, _ = _layout_image_batches(
                plan,
                pre_comb,
                pre_segs,
                export_segments=export_segments,
                is_batch=is_batch,
                video_batch=video_batch,
            )
        except Exception as exc:
            log.warning("images_pre_refine layout failed: %s", exc)
            pre_refine_out = images_out
            report = report + f"\n\nimages_pre_refine: fallback to images ({exc})."

    from ..director.face_refine.pack import face_refine_enabled

    emit_pre_face = (
        face_refine_enabled(plan)
        and not block_final_images
        and export_pre_face_refine
        and (pre_face_combined is not None or pre_face_segments)
    )
    if emit_pre_face:
        pre_face_segs = pre_face_segments if pre_face_segments else segment_outputs
        pre_face_comb = pre_face_combined if pre_face_combined is not None else combined
        share_face = pre_face_comb is combined and (
            pre_face_segs is segment_outputs
            or (
                len(pre_face_segs) == len(segment_outputs)
                and all(a is b for a, b in zip(pre_face_segs, segment_outputs))
            )
        )
        if share_face:
            pre_face_out = images_out
        else:
            try:
                pre_face_out, _ = _layout_image_batches(
                    plan,
                    pre_face_comb,
                    pre_face_segs,
                    export_segments=export_segments,
                    is_batch=is_batch,
                    video_batch=video_batch,
                )
            except Exception as exc:
                log.warning("images_pre_face_refine layout failed: %s", exc)
                pre_face_out = images_out
                report = report + f"\n\nimages_pre_face_refine: fallback to images ({exc})."
    else:
        pre_face_out = None

    pre_counts = segment_frame_counts
    if export_segments:
        released_slots = sorted(
            set(released_slots)
            | set(released_output_slots(pre_refine_out, pre_counts))
        )
    if released_slots:
        keep = [i for i in range(len(images_out)) if i not in set(released_slots)]
        if keep:
            images_out = [images_out[i] for i in keep]
            pre_refine_out = [
                pre_refine_out[i] for i in keep if i < len(pre_refine_out)
            ] or pre_refine_out[-1:]
            if pre_face_out is not None:
                pre_face_out = [
                    pre_face_out[i] for i in keep if i < len(pre_face_out)
                ] or pre_face_out[-1:]
            if segment_audios:
                segment_audios = [segment_audios[i] for i in keep if i < len(segment_audios)]
            if segment_frame_counts:
                segment_frame_counts = [
                    segment_frame_counts[i] for i in keep if i < len(segment_frame_counts)
                ]

    split_for_audio = split_layout
    audio_frame_end = frame_count if not split_for_audio else None
    audio_mode = resolve_audio_mode(plan)
    use_generated = audio_mode == AUDIO_MODE_GENERATE
    # Prefer caller-provided export lengths (post continuity trim); else match IMAGE batches.
    if segment_frame_counts is None and segment_audios and split_for_audio:
        segment_frame_counts = [int(s.shape[0]) for s in images_out]
    audio_out, source_fallback = build_director_audio_outputs(
        plan,
        images_out,
        export_segments=split_for_audio,
        output_frame_end=audio_frame_end,
        segment_audios=segment_audios if use_generated else None,
        segment_frame_counts=segment_frame_counts if use_generated else None,
        audio_mode=audio_mode,
    )
    report = report + source_audio_report_note(
        plan,
        audio_out,
        export_segments=split_for_audio,
        output_frame_end=audio_frame_end,
        used_generated_audio=bool(use_generated and segment_audios),
        audio_mode=audio_mode,
        source_fallback=source_fallback,
    )

    split_source_outputs = export_segments or (is_batch and not video_batch)
    if export_source_images:
        try:
            source_images_out = build_source_images_output(
                plan,
                images_out,
                split_outputs=split_source_outputs,
            )
            source_frames = sum(int(batch.shape[0]) for batch in source_images_out)
            report = report + (
                f"\n\nSource images: decoded {source_frames} timeline frame(s) "
                f"on {len(source_images_out)} source_images batch(es)."
            )
        except Exception as exc:
            log.warning("Source images output failed: %s", exc)
            # Never disguise generated frames as the source comparison. A neutral
            # placeholder makes the failure visible while preserving the expensive run.
            source_images_out = _empty_source_images_for(images_out)
            report = report + (
                "\n\nSource images: FAILED — emitted neutral placeholder(s), not generated "
                f"frames. Check the timeline source path/decode ({type(exc).__name__}: {exc})."
            )
    else:
        source_images_out = _empty_source_images_for(images_out)

    images_out = _ensure_nonempty_image_batches(images_out, label="images")
    source_images_out = _ensure_nonempty_image_batches(source_images_out, label="source_images")
    pre_refine_out = _ensure_nonempty_image_batches(pre_refine_out, label="images_pre_refine")

    if pre_face_out is None:
        # Off / unwired / first-pass hold: block the socket so Preview/Save
        # do not run on a grey still, and RAM is not kept for a dummy clip.
        pre_face_out = ExecutionBlocker(None)
        if face_refine_enabled(plan) and block_final_images:
            report = report + (
                "\n\nimages_pre_face_refine: blocked "
                "（本轮仅确认一采，脸部精修会在二采完成后执行）。"
            )
        elif face_refine_enabled(plan) and not export_pre_face_refine:
            report = report + (
                "\n\nimages_pre_face_refine: blocked "
                "（未勾选「输出修脸前」，该口无画面、下游不执行）。"
            )
        else:
            report = report + (
                "\n\nimages_pre_face_refine: blocked (FaceRefine node not connected)."
            )
    else:
        pre_face_out = _ensure_nonempty_image_batches(pre_face_out, label="images_pre_face_refine")
        report = report + (
            "\n\nimages_pre_face_refine: video immediately before face stitch "
            "(对比口；images 为修脸后)。"
        )

    refine_pack = getattr(plan, "refine", None)
    if isinstance(refine_pack, dict) and refine_pack.get("enabled"):
        report = report + (
            "\n\nimages_pre_refine: first-pass video (before second sample / upscale). "
            "Cached or passthrough slots reuse the stored final frames."
        )
    else:
        report = report + (
            "\n\nimages_pre_refine: same as images (Refine node not connected)."
        )

    fps_out = float(plan.frame_rate or 24.0)

    # 🎬 核心安全保障：導演台原生影音第一時間自動硬盤備份（流式寫入，0 額外內存）
    # 確保即使用戶後續跑 4 小時超分時崩潰或斷電，18 分鐘生成的全片也早已穩穩躺在 output 目錄！
    if not block_final_images:
        backup_path = _auto_save_raw_backup(images_out, audio_out, fps=fps_out)
        if backup_path:
            report = report + f"\n\n🎬 【原生影音安全備份】：已第一時間自動保存成片至 {backup_path} (無懼後續超分崩潰)。"

    report = report + "\n\n有問題聯繫作者：AI攪拌手  QQ交流羣：551482703"

    if block_final_images:
        report = report + (
            "\n\n本轮仅确认一采：images（最终/二采输出）已阻断，"
            "请从 images_pre_refine 查看或保存一采；再次 Queue 完成二采后 images 才会输出。"
        )
        images_out = ExecutionBlocker(None)

    # 視頻生成階段結束：主動卸載 MiniMax H3 巨大的 DiT/TE/VAE 權重 (釋放 35GB+ 系統 RAM)，
    # Leave system memory available while encoding long videos.
    try:
        import comfy.model_management as mm
        import gc
        if hasattr(mm, "free_registrations"):
            mm.free_registrations(1e32, evict_active=True)
        if hasattr(mm, "free_pins"):
            mm.free_pins(1e32, evict_active=True, loaded=True)
        mm.unload_all_models()
        while mm.current_loaded_models:
            cur_m = mm.current_loaded_models.pop()
            try:
                cur_m.model_unload(1e32)
            except Exception:
                pass
        mm.soft_empty_cache()
        gc.collect()
    except Exception:
        pass

    return images_out, audio_out, fps_out, frame_count, source_images_out, report, pre_refine_out, pre_face_out


def _auto_save_raw_backup(images_out, audio_out, fps: float = 24.0) -> str | None:
    """Safety direct-to-disk MP4 backup.
    Immediately streams the director's raw merged video to ComfyUI/output/
    so the full generation is never lost even if downstream nodes crash.
    """
    try:
        if not images_out or not isinstance(images_out[0], torch.Tensor) or images_out[0].ndim != 4:
            return None
        import os
        import shutil
        import subprocess
        import tempfile
        import time
        import wave
        import numpy as np
        import folder_paths

        frames_tensor = images_out[0]
        n_frames, h, w, c = frames_tensor.shape
        if n_frames < 2:
            return None

        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        out_dir = folder_paths.get_output_directory()
        os.makedirs(out_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_filename = f"Ultimate_Director_Raw_Backup_{timestamp}.mp4"
        final_mp4_path = os.path.join(out_dir, backup_filename)

        ew = w if w % 2 == 0 else w + 1
        eh = h if h % 2 == 0 else h + 1

        tmp_dir = tempfile.mkdtemp(prefix="ud_raw_backup_")
        tmp_mp4 = os.path.join(tmp_dir, "backup.mp4")
        wav_path = os.path.join(tmp_dir, "backup.wav")

        has_audio = False
        if audio_out and isinstance(audio_out, dict):
            wave_t = audio_out.get("waveform")
            sr = int(audio_out.get("sample_rate") or 0)
            if isinstance(wave_t, torch.Tensor) and wave_t.numel() > 0 and sr > 0:
                wt = wave_t.detach().cpu().float()
                if wt.ndim == 2:
                    wt = wt.unsqueeze(0)
                if wt.ndim == 3:
                    wt = wt[0].transpose(0, 1).contiguous()
                    channels = wt.shape[1]
                    if channels > 0:
                        pcm = (wt.clamp(-1.0, 1.0) * 32767.0).to(torch.int16).numpy()
                        with wave.open(wav_path, "wb") as wf:
                            wf.setnchannels(channels)
                            wf.setsampwidth(2)
                            wf.setframerate(sr)
                            wf.writeframes(pcm.tobytes())
                        has_audio = True

        cmd = [
            ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-pix_fmt", "rgb24", "-s", f"{ew}x{eh}",
            "-r", f"{fps:.6f}", "-i", "-",
        ]
        if has_audio:
            cmd += ["-i", wav_path]
        cmd += [
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "veryfast", "-crf", "20",
        ]
        if has_audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += ["-movflags", "+faststart", tmp_mp4]

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.stdin is None:
            proc.kill()
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

        for i in range(n_frames):
            frame_t = frames_tensor[i:i+1].detach().cpu().float().clamp(0.0, 1.0)
            frame_np = (frame_t * 255.0).numpy().astype(np.uint8)[0, :, :, :3]
            if eh != h or ew != w:
                padded = np.zeros((eh, ew, 3), dtype=np.uint8)
                padded[:h, :w, :] = frame_np
                frame_np = padded
            proc.stdin.write(frame_np.tobytes())
        proc.stdin.close()
        proc.wait(timeout=120)
        if proc.returncode == 0 and os.path.exists(tmp_mp4):
            shutil.move(tmp_mp4, final_mp4_path)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            log.info("🎬 [SAFETY BACKUP] 終極導演原生影音已第一時間安全備份至: %s", final_mp4_path)
            return final_mp4_path
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as exc:
        log.warning("Safety backup failed (non-fatal): %s", exc)
    return None
