"""Timeline -> the prompt string(s) that video models actually read.

This module compiles a Timeline document into model-specific prompt formats:

- H3 Base (no attachments): integrated_multimodal_description + overall_soundscape + non_diegetic_music
- H3 Reference (with attachments): subject_definitions + summary + retention_analysis + detailed_description + overall_soundscape + non_diegetic_music
- LTX: per-segment text prompts with temporal mask indices

Design credit: Core logic from ComfyUI-MiniMaxDirector's compile.py,
extended with DirectorDeck's recipe derivation and shuhao's style injection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import lattice
from .lattice import VideoModel
from .timeline import (
    ANCHOR_ROLES,
    FRAME_ROLES,
    RETENTIONS,
    AUDIO_RETENTIONS,
    RETENTION_ACROSS,
    ROLE_TASKS,
    Move,
    Shot,
    Timeline,
    _sentences,
    camera_sentence,
)


@dataclass(frozen=True, slots=True)
class CompiledPrompt:
    """What the node hands to the sampler, plus what it shows the author."""
    prompt: str
    length: int
    duration: float
    model: VideoModel
    report: str = ""

    def __str__(self) -> str:
        return self.prompt


@dataclass(frozen=True, slots=True)
class CompiledSegment:
    """A single renderable segment within a longer timeline."""
    index: int
    prompt: str
    length: int
    duration: float
    mode: str
    shot_prompts: list[str]
    prev_tail_frames: int = 0


def compile_timeline(
    timeline: Timeline,
    first_frame: bool = False,
    last_frame: bool = False,
) -> CompiledPrompt:
    """Compile a timeline into a single prompt for the target model."""
    if timeline.model == VideoModel.H3:
        return _compile_h3(timeline, first_frame, last_frame)
    elif timeline.model == VideoModel.LTX:
        return _compile_ltx(timeline)
    elif timeline.model == VideoModel.BERNINI:
        return _compile_bernini(timeline)
    else:
        return _compile_h3(timeline, first_frame, last_frame)


def compile_segments(timeline: Timeline) -> list[CompiledSegment]:
    """Compile a timeline into multiple renderable segments.

    This is the core function for long-video production:
    it splits the timeline at model frame limits and compiles
    each segment with proper context for continuity.
    """
    segments = timeline.plan_segments()
    compiled: list[CompiledSegment] = []

    for idx, seg in enumerate(segments):
        shots = seg.get("shots", [])
        mode = seg.get("mode", timeline.default_mode)
        length = seg.get("length", 0)

        # Build per-shot prompts
        shot_prompts = []
        for shot in shots:
            style_preset = timeline.get_style_preset()
            cast_descriptions = []
            for cast_id in (shot.cast_ids or []):
                member = timeline.get_cast_member(cast_id)
                if member:
                    cast_descriptions.append(member.prompt_block())

            parts = []
            if timeline.global_prompt:
                parts.append(timeline.global_prompt)
            if style_preset.get("render"):
                parts.append(style_preset["render"])
            if cast_descriptions:
                parts.append(", ".join(cast_descriptions))
            parts.append(shot.prompt)
            shot_prompts.append(_sentences(p for p in parts if p))

        # Compile segment prompt based on model
        if timeline.model == VideoModel.H3:
            prompt = _compile_h3_segment(timeline, shots, shot_prompts)
        else:
            prompt = "\n\n".join(shot_prompts) if shot_prompts else timeline.global_prompt

        compiled.append(CompiledSegment(
            index=idx,
            prompt=prompt,
            length=length,
            duration=lattice.to_seconds(length, timeline.model),
            mode=mode,
            shot_prompts=shot_prompts,
            prev_tail_frames=9 if idx > 0 else 0,  # SCAIL overlap (from Bernini Director)
        ))

    return compiled


# -- H3 compilation --------------------------------------------------------

def _compile_h3(
    timeline: Timeline,
    first_frame: bool = False,
    last_frame: bool = False,
) -> CompiledPrompt:
    """Compile a timeline for MiniMax H3."""
    length = timeline.length
    has_refs = _has_references(timeline)
    renderer = _render_h3_reference if has_refs else _render_h3_official

    body = renderer(timeline)
    instruction = _h3_alignment(timeline, length, first_frame, last_frame, has_refs)
    prompt = f"{instruction}\n\n{body}" if instruction else body

    report_lines = [
        f"Model: MiniMax H3",
        f"Format: {'Reference (6-section)' if has_refs else 'Official (3-field)'}",
        f"Frames: {length} ({lattice.to_seconds(length, VideoModel.H3):.2f}s)",
        f"Shots: {len(timeline.shots)}",
    ]

    return CompiledPrompt(
        prompt=prompt,
        length=length,
        duration=lattice.to_seconds(length, VideoModel.H3),
        model=VideoModel.H3,
        report="\n".join(report_lines),
    )


def _has_references(timeline: Timeline) -> bool:
    """Check if timeline has any attached media references."""
    for shot in timeline.shots:
        if shot.media:
            role = str(shot.media.get("role", "")).strip()
            if role not in ANCHOR_ROLES:
                return True
    for source in timeline.sources:
        if source:
            return True
    return False


def _h3_alignment(
    timeline: Timeline,
    length: int,
    first: bool,
    last: bool,
    has_refs: bool,
) -> str:
    """Generate the keyframe-alignment sentence H3 requires."""
    if has_refs and not (first or last):
        return ""
    if not (first or last):
        return ""

    shots = len(timeline.ordered_shots()) or 1
    seconds = f"{lattice.to_seconds(length, VideoModel.H3):.2f}"

    if first and not last:
        return (
            "For the target video, at 0.00 seconds into the target video, "
            "<Picture 1> (from [Shot 1]) is fully referenced."
        )
    if last and not first:
        return (
            "How the reference pictures align with the target video — "
            f"<Picture 1> (from [Shot {shots}]) aligns with the {seconds}-second "
            "mark of the target video."
        )
    return (
        "How the reference pictures align with the target video — "
        "Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target "
        f"video; Picture 2 (from Shot {shots}) aligns with the {seconds}-second "
        "mark of the target video."
    )


def _render_h3_official(timeline: Timeline) -> str:
    """H3 3-field format (no references)."""
    fields = [f"integrated_multimodal_description: {_h3_description(timeline)}"]
    fields.append(f"overall_soundscape: {_h3_soundscape(timeline) or 'N/A'}")
    fields.append(f"non_diegetic_music: {timeline.music.strip() or 'N/A'}")
    return "\n\n".join(fields)


def _render_h3_reference(timeline: Timeline) -> str:
    """H3 6-section reference format."""
    fields = [
        f"subject_definitions:\n{_h3_subject_definitions(timeline)}",
        f"summary:\n{_h3_summary(timeline)}",
        f"retention_analysis:\n{_h3_retention_analysis(timeline)}",
        f"detailed_description:\n{_h3_description(timeline)}",
        f"overall_soundscape:\n{_h3_soundscape(timeline) or 'N/A'}",
        f"non_diegetic_music:\n{timeline.music.strip() or 'N/A'}",
    ]
    return "\n\n".join(fields)


def _h3_description(timeline: Timeline) -> str:
    """Build the integrated multimodal description."""
    shots = timeline.ordered_shots()
    if not shots:
        return timeline.global_prompt.strip() or "A video clip."

    voices = timeline.voices()
    moves = timeline.ordered_moves()
    parts: list[str] = []

    # Global prompt as scene-setting
    if timeline.global_prompt.strip():
        parts.append(timeline.global_prompt.strip())

    prev_carried = False
    for idx, shot in enumerate(shots):
        is_last = idx == len(shots) - 1
        shot_text = shot.text(voices, carried=prev_carried, cutoff=is_last)

        if idx == 0:
            # First shot: no timestamp
            line = f"[Shot 1] {shot_text}"
        else:
            # Later shots: timestamp + transition
            time = lattice.to_seconds(shot.start, timeline.model)
            timestamp = lattice.format_timestamp(time)
            line = f"[Shot {idx + 1}] At {timestamp}, {shot.opener()} {shot_text}"

        # Inject camera moves that overlap this shot
        for move in moves:
            if move.start >= shot.start and move.start < shot.end:
                move_text = move.text()
                if move_text:
                    line += f" {move_text}"

        parts.append(line)
        prev_carried = shot.carries_over()

    return " ".join(parts)


def _h3_soundscape(timeline: Timeline) -> str:
    """Build the overall_soundscape from audio cues."""
    cues = timeline.ordered_cues()
    if not cues:
        return ""

    parts = []
    for cue in cues:
        if cue.prompt.strip():
            time = lattice.to_seconds(cue.start, timeline.model)
            if time == 0:
                parts.append(cue.prompt.strip())
            else:
                timestamp = lattice.format_timestamp(time)
                parts.append(f"At {timestamp}, {cue.prompt.strip()}")
    return " ".join(parts)


def _h3_subject_definitions(timeline: Timeline) -> str:
    """Build subject_definitions for Ref2VA format."""
    lines = []
    pic_idx = 1
    for shot in timeline.ordered_shots():
        if not shot.media:
            continue
        desc = str(shot.media.get("description", "")).strip()
        if desc:
            lines.append(f"<Picture {pic_idx}>: {desc}")
            pic_idx += 1
    for source in timeline.sources:
        desc = str(source.get("description", "")).strip()
        if desc:
            lines.append(f"<Picture {pic_idx}>: {desc}")
            pic_idx += 1
    return "\n".join(lines) if lines else "N/A"


def _h3_summary(timeline: Timeline) -> str:
    """Build summary for Ref2VA format."""
    shots = timeline.ordered_shots()
    mode_parts = set()
    for shot in shots:
        if shot.media:
            role = str(shot.media.get("role", "reference"))
            task = ROLE_TASKS.get(role, "reference generation")
            mode_parts.add(task)
    if not mode_parts:
        mode_parts.add("reference generation")
    return " + ".join(sorted(mode_parts))


def _h3_retention_analysis(timeline: Timeline) -> str:
    """Build retention_analysis for Ref2VA format."""
    lines = []
    pic_idx = 1
    for shot_idx, shot in enumerate(timeline.ordered_shots()):
        if not shot.media:
            continue
        role = str(shot.media.get("role", "reference"))
        retention = str(shot.media.get("retention", "fully_preserved"))
        role_label = f" {role}" if role in FRAME_ROLES else ""
        desc = str(shot.media.get("description", "")).strip() or "the subject"
        lines.append(
            f"<Picture {pic_idx}> ([Shot {shot_idx + 1}]{role_label}): "
            f"{retention} - {desc}"
        )
        pic_idx += 1
    return "\n".join(lines) if lines else "N/A"


def _compile_h3_segment(
    timeline: Timeline,
    shots: list[Shot],
    shot_prompts: list[str],
) -> str:
    """Compile a single H3 segment's prompt."""
    if not shot_prompts:
        prompt_body = timeline.global_prompt or "A video clip."
    elif len(shot_prompts) == 1:
        prompt_body = shot_prompts[0]
    else:
        parts = []
        for idx, (shot, prompt) in enumerate(zip(shots, shot_prompts)):
            if idx == 0:
                parts.append(f"[Shot 1] {prompt}")
            else:
                time = lattice.to_seconds(shot.start - shots[0].start, timeline.model)
                timestamp = lattice.format_timestamp(time)
                parts.append(f"[Shot {idx + 1}] At {timestamp}, {shot.opener()} {prompt}")
        prompt_body = " ".join(parts)

    fields = [f"integrated_multimodal_description: {prompt_body}"]
    soundscape = _h3_soundscape(timeline)
    fields.append(f"overall_soundscape: {soundscape or 'N/A'}")
    fields.append(f"non_diegetic_music: {timeline.music.strip() or 'N/A'}")
    return "\n\n".join(fields)


# -- LTX compilation -------------------------------------------------------

def _compile_ltx(timeline: Timeline) -> CompiledPrompt:
    """Compile a timeline for LTX 2.5."""
    length = timeline.length
    shots = timeline.ordered_shots()

    if not shots:
        prompt = timeline.global_prompt.strip() or "A video clip."
    else:
        parts = []
        if timeline.global_prompt.strip():
            parts.append(timeline.global_prompt.strip())
        for shot in shots:
            parts.append(shot.prompt.strip())
        prompt = " ".join(p for p in parts if p)

    return CompiledPrompt(
        prompt=prompt,
        length=length,
        duration=lattice.to_seconds(length, VideoModel.LTX),
        model=VideoModel.LTX,
        report=f"Model: LTX 2.5\nFrames: {length}\nShots: {len(shots)}",
    )


# -- Bernini compilation ---------------------------------------------------

def _compile_bernini(timeline: Timeline) -> CompiledPrompt:
    """Compile a timeline for Bernini."""
    length = timeline.length
    shots = timeline.ordered_shots()

    if not shots:
        prompt = timeline.global_prompt.strip() or "A video clip."
    else:
        parts = []
        if timeline.global_prompt.strip():
            parts.append(timeline.global_prompt.strip())
        for shot in shots:
            parts.append(shot.prompt.strip())
        prompt = " ".join(p for p in parts if p)

    return CompiledPrompt(
        prompt=prompt,
        length=length,
        duration=lattice.to_seconds(length, VideoModel.BERNINI),
        model=VideoModel.BERNINI,
        report=f"Model: Bernini\nFrames: {length}\nShots: {len(shots)}",
    )
