"""Quality gate: lint the timeline before it reaches the sampler.

Catches structural issues, format errors, and continuity problems that
would silently degrade output quality.

Design credit: Lint concept from ComfyUI-MiniMaxDirector, quality gate
validation from shuhao-skills-2's novel-storyboard validate command.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import lattice
from .lattice import VideoModel
from .timeline import (
    CAMERA_MOTION,
    RETENTIONS,
    AUDIO_RETENTIONS,
    ROLES,
    TRANSITIONS,
    Timeline,
    Shot,
)


@dataclass(frozen=True, slots=True)
class LintIssue:
    """One problem found in the timeline."""
    severity: str  # "error", "warning", "info"
    code: str
    message: str
    location: str = ""

    def __str__(self) -> str:
        prefix = f"[{self.severity.upper()}] "
        loc = f"({self.location}) " if self.location else ""
        return f"{prefix}{loc}{self.code}: {self.message}"


def lint(timeline: Timeline) -> list[LintIssue]:
    """Run all lint checks on a timeline. Returns issues sorted by severity."""
    issues: list[LintIssue] = []

    _check_empty(timeline, issues)
    _check_frame_alignment(timeline, issues)
    _check_shot_overlaps(timeline, issues)
    _check_shot_prompts(timeline, issues)
    _check_camera_vocabulary(timeline, issues)
    _check_transitions(timeline, issues)
    _check_media_roles(timeline, issues)
    _check_continuity(timeline, issues)
    _check_cast_references(timeline, issues)
    _check_duration_limits(timeline, issues)

    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: severity_order.get(i.severity, 9))
    return issues


def lint_report(timeline: Timeline) -> str:
    """Human-readable lint report."""
    issues = lint(timeline)
    if not issues:
        return "No issues found."

    lines = []
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warning")
    lines.append(f"Found {len(issues)} issue(s): {errors} error(s), {warnings} warning(s)")
    lines.append("")
    for issue in issues:
        lines.append(str(issue))
    return "\n".join(lines)


def _check_empty(timeline: Timeline, issues: list[LintIssue]) -> None:
    if not timeline.shots and not timeline.global_prompt.strip():
        issues.append(LintIssue(
            severity="warning",
            code="EMPTY_TIMELINE",
            message="Timeline has no shots and no global prompt.",
        ))


def _check_frame_alignment(timeline: Timeline, issues: list[LintIssue]) -> None:
    for idx, shot in enumerate(timeline.shots):
        if shot.length > 0 and not lattice.is_valid(shot.length, timeline.model):
            aligned = lattice.snap_up(shot.length, timeline.model)
            issues.append(LintIssue(
                severity="info",
                code="FRAME_MISALIGN",
                message=f"Shot length {shot.length} will be aligned to {aligned}.",
                location=f"Shot {idx + 1}",
            ))


def _check_shot_overlaps(timeline: Timeline, issues: list[LintIssue]) -> None:
    ordered = timeline.ordered_shots()
    for i in range(len(ordered) - 1):
        current = ordered[i]
        next_shot = ordered[i + 1]
        if current.end > next_shot.start:
            issues.append(LintIssue(
                severity="error",
                code="SHOT_OVERLAP",
                message=(
                    f"Shot {i + 1} (frames {current.start}-{current.end}) "
                    f"overlaps with Shot {i + 2} (starts at frame {next_shot.start})."
                ),
                location=f"Shots {i + 1}-{i + 2}",
            ))


def _check_shot_prompts(timeline: Timeline, issues: list[LintIssue]) -> None:
    for idx, shot in enumerate(timeline.shots):
        if not shot.prompt.strip() and not timeline.global_prompt.strip():
            issues.append(LintIssue(
                severity="warning",
                code="EMPTY_PROMPT",
                message="Shot has no prompt and no global prompt to fall back on.",
                location=f"Shot {idx + 1}",
            ))
        if len(shot.prompt) > 2000:
            issues.append(LintIssue(
                severity="warning",
                code="LONG_PROMPT",
                message=f"Shot prompt is {len(shot.prompt)} chars (recommend < 2000).",
                location=f"Shot {idx + 1}",
            ))


def _check_camera_vocabulary(timeline: Timeline, issues: list[LintIssue]) -> None:
    for idx, move in enumerate(timeline.moves):
        if move.camera and move.camera not in CAMERA_MOTION:
            issues.append(LintIssue(
                severity="info",
                code="UNKNOWN_CAMERA",
                message=f"Camera motion '{move.camera}' is not in the standard vocabulary.",
                location=f"Move {idx + 1}",
            ))


def _check_transitions(timeline: Timeline, issues: list[LintIssue]) -> None:
    for idx, shot in enumerate(timeline.shots):
        if idx > 0 and shot.transition and shot.transition not in TRANSITIONS:
            issues.append(LintIssue(
                severity="info",
                code="UNKNOWN_TRANSITION",
                message=f"Transition '{shot.transition}' is not in the standard vocabulary.",
                location=f"Shot {idx + 1}",
            ))


def _check_media_roles(timeline: Timeline, issues: list[LintIssue]) -> None:
    for idx, shot in enumerate(timeline.shots):
        if shot.media:
            role = str(shot.media.get("role", ""))
            if role and role not in ROLES:
                issues.append(LintIssue(
                    severity="warning",
                    code="UNKNOWN_ROLE",
                    message=f"Media role '{role}' is not recognized.",
                    location=f"Shot {idx + 1}",
                ))
            retention = str(shot.media.get("retention", ""))
            kind = str(shot.media.get("kind", "image"))
            valid_retentions = AUDIO_RETENTIONS if kind == "audio" else RETENTIONS
            if retention and retention not in valid_retentions:
                issues.append(LintIssue(
                    severity="warning",
                    code="UNKNOWN_RETENTION",
                    message=f"Retention '{retention}' is not valid for {kind} media.",
                    location=f"Shot {idx + 1}",
                ))


def _check_continuity(timeline: Timeline, issues: list[LintIssue]) -> None:
    """Check cross-shot continuity (cast wardrobe, lighting, props)."""
    ordered = timeline.ordered_shots()
    if len(ordered) < 2:
        return

    for i in range(len(ordered) - 1):
        current = ordered[i]
        next_shot = ordered[i + 1]

        # Check if cast members appear in consecutive shots with conflicting directions
        current_cast = set(current.cast_ids)
        next_cast = set(next_shot.cast_ids)
        shared = current_cast & next_cast

        for cast_id in shared:
            cur_dir = current.direction
            next_dir = next_shot.direction
            # Check lighting continuity within same scene
            if cur_dir.get("lighting") and next_dir.get("lighting"):
                if cur_dir["lighting"] != next_dir["lighting"]:
                    issues.append(LintIssue(
                        severity="warning",
                        code="LIGHTING_JUMP",
                        message=(
                            f"Lighting changes from '{cur_dir['lighting']}' to "
                            f"'{next_dir['lighting']}' between consecutive shots."
                        ),
                        location=f"Shots {i + 1}-{i + 2}",
                    ))


def _check_cast_references(timeline: Timeline, issues: list[LintIssue]) -> None:
    """Check that all referenced cast IDs exist."""
    known_ids = {c.id for c in timeline.cast}
    for idx, shot in enumerate(timeline.shots):
        for cast_id in (shot.cast_ids or []):
            if cast_id and cast_id not in known_ids:
                issues.append(LintIssue(
                    severity="warning",
                    code="UNKNOWN_CAST",
                    message=f"Cast member '{cast_id}' referenced but not defined.",
                    location=f"Shot {idx + 1}",
                ))


def _check_duration_limits(timeline: Timeline, issues: list[LintIssue]) -> None:
    """Check total duration is within reasonable limits."""
    spec = lattice.MODEL_SPECS[timeline.model]
    total = timeline.length
    max_single = spec.max_frames

    if total > max_single:
        num_segments = -(-total // max_single)  # ceiling division
        issues.append(LintIssue(
            severity="info",
            code="MULTI_SEGMENT",
            message=(
                f"Timeline ({total} frames, {lattice.to_seconds(total, timeline.model):.1f}s) "
                f"exceeds single-segment limit ({max_single} frames). "
                f"Will be split into ~{num_segments} segments."
            ),
        ))

    for idx, shot in enumerate(timeline.shots):
        if shot.length > max_single:
            issues.append(LintIssue(
                severity="error",
                code="SHOT_TOO_LONG",
                message=(
                    f"Shot length {shot.length} frames exceeds model limit of {max_single}."
                ),
                location=f"Shot {idx + 1}",
            ))
