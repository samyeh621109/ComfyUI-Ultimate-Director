"""The timeline document: what the editor edits and the compiler reads.

The whole director state is one JSON object stored in a single node widget.
Keeping it a plain document -- rather than state scattered across widgets --
means a timeline can be copied between graphs, diffed in review, and generated
by a script.

Frames, not seconds, are authoritative. Seconds are a presentation detail
derived at compile time, so a timeline never drifts by a rounding error.

Design credit: Architecture adapted from ComfyUI-MiniMaxDirector's timeline.py
and DirectorDeck's unified timeline schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Literal

from . import lattice
from .lattice import VideoModel


# -- Vocabulary (H3 Ref2VA prompt format) -----------------------------------

RefKind = Literal["picture", "audio", "video"]

ROLES: tuple[str, ...] = (
    "reference", "storyboard", "first frame", "keyframe",
    "last frame", "continue from", "edit",
)

ROLE_TASKS: dict[str, str] = {
    "reference": "reference generation",
    "storyboard": "reference generation",
    "first frame": "keyframe completion",
    "keyframe": "keyframe completion",
    "last frame": "keyframe completion",
    "continue from": "video continuation",
    "edit": "video editing",
}

ANCHOR_ROLES = ("first frame", "last frame")
FRAME_ROLES = ("first frame", "keyframe", "last frame")

RETENTIONS = ("fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference")
AUDIO_RETENTIONS = ("fully_copy", "partially_copy", "reference", "weak_reference")

RETENTION_ACROSS: dict[str, str] = {
    "fully_preserved": "fully_copy",
    "partially_preserved": "partially_copy",
    "attribute_transfer": "reference",
    "weak_reference": "weak_reference",
}

AMPLITUDES = ("small", "large")
SPEEDS = ("slow", "fast")

CAMERA_MOTION: dict[str, str] = {
    "static": "holds a static shot",
    "zoom_in": "zooms in",
    "zoom_out": "zooms out",
    "dolly_in": "pushes in",
    "dolly_out": "pulls out",
    "pan_left": "pans left",
    "pan_right": "pans right",
    "truck_left": "trucks left",
    "truck_right": "trucks right",
    "tilt_up": "tilts up",
    "tilt_down": "tilts down",
    "pedestal_up": "rises straight up",
    "pedestal_down": "lowers straight down",
    "orbit": "moves in an arc around the subject",
    "tracking": "follows the moving subject",
    "pov": "takes the subject's point of view",
    "roll_cw": "rolls clockwise",
    "roll_ccw": "rolls counterclockwise",
    "handheld": "shakes slightly",
    "shake_strongly": "shakes strongly",
    "crash_zoom": "zooms in",
}

TRANSITIONS: dict[str, str] = {
    "cut": "the camera cuts to",
    "dissolve": "the shot cross-dissolves to",
    "fade": "the shot fades to",
    "wipe": "the shot wipes to",
}

# -- Generation modes (from DirectorDeck) -----------------------------------

GENERATION_MODES = ("t2v", "i2v", "fl2v", "r2v", "v2v", "rv2v")

MODE_LABELS: dict[str, str] = {
    "t2v": "Text to Video",
    "i2v": "Image to Video (first frame)",
    "fl2v": "First-Last Frame to Video",
    "r2v": "Reference to Video",
    "v2v": "Video to Video",
    "rv2v": "Reference Video Edit",
}

# -- Style presets (from shuhao-skills-2) -----------------------------------

STYLE_PRESETS: dict[str, dict[str, str]] = {
    "realistic": {
        "label": "Semi-Realistic / Painterly",
        "render": "semi-realistic painterly rendering, soft volumetric lighting",
        "surface": "oil-paint texture with subtle brush strokes",
        "negative": "3D render, plastic, glossy, anime eyes, chibi",
    },
    "ghibli": {
        "label": "Studio Ghibli / Hand-Drawn Cel",
        "render": "hand-drawn cel animation, warm watercolor wash",
        "surface": "clean cel outlines with soft gradient fills",
        "negative": "photorealistic, 3D render, dark gritty",
    },
    "photorealistic": {
        "label": "Photorealistic / Live-Action",
        "render": "photorealistic live-action cinematography, 35mm film grain",
        "surface": "real skin texture, fabric detail, natural weathering",
        "negative": "cartoon, illustration, flat color, anime",
    },
    "comic": {
        "label": "American Comic / Bold Lines",
        "render": "American comic book style, bold ink outlines, dynamic angles",
        "surface": "halftone dots, strong color blocks",
        "negative": "photorealistic, soft focus, watercolor",
    },
    "ink": {
        "label": "Chinese Ink / Sumi-e",
        "render": "Chinese ink wash painting, sumi-e brushwork, misty atmosphere",
        "surface": "rice paper texture, flowing ink gradients",
        "negative": "3D render, neon colors, glossy, photorealistic",
    },
    "noir": {
        "label": "Film Noir / High Contrast",
        "render": "film noir cinematography, high contrast chiaroscuro, moody",
        "surface": "grain-heavy monochrome with selective color accents",
        "negative": "bright, colorful, cartoon, cheerful",
    },
    "pixar": {
        "label": "Pixar / 3D Animation",
        "render": "Pixar-style 3D animation, subsurface scattering, global illumination",
        "surface": "smooth plastic-like surfaces with subtle texture",
        "negative": "2D flat, hand-drawn, realistic skin, dark gritty",
    },
}


# -- Utility functions ------------------------------------------------------

def flat(text: Any) -> str:
    """Collapse all whitespace in `text` to single spaces (one line, always)."""
    return " ".join(str(text or "").split())


def camera_sentence(camera: str, amplitude: str = "", speed: str = "") -> str:
    """Build a camera-motion sentence following the H3 guide's word order."""
    key = str(camera or "").strip()
    motion = CAMERA_MOTION.get(key)
    if motion is None:
        return key
    parts = [f"The camera {motion}"]
    if key != "static":
        if amplitude in AMPLITUDES:
            parts.append(f"with {amplitude} amplitude")
        if speed in SPEEDS:
            parts.append(f"at {speed} speed")
    return " ".join(parts) + "."


def _sentences(parts: Iterable[str]) -> str:
    """Join text fragments into prose, adding full stops where missing."""
    out = ""
    for part in parts:
        piece = part.strip()
        if not piece:
            continue
        if not out:
            out = piece
            continue
        ended = out.endswith((".", "!", "?", ",", "</d>"))
        separator = " " if ended else ". "
        out = f"{out}{separator}{piece}"
    return out


# -- Data Classes -----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Reference:
    """A wired input: <Picture 1>, <Audio 2>, etc."""
    kind: RefKind
    index: int
    label: str = ""

    @property
    def token(self) -> str:
        return f"<{self.kind.capitalize()} {self.index}>"


@dataclass(frozen=True, slots=True)
class CastMember:
    """A character in the production with visual/audio identity.

    Merged concept from MiniMaxDirector's Speaker and shuhao's cast.json.
    """
    id: str
    name: str
    appearance: str = ""
    voice: str = ""
    style_tags: str = ""
    reference_image: str = ""

    def prompt_block(self) -> str:
        """Generate character description block for prompt injection."""
        parts = [self.name]
        if self.appearance:
            parts.append(self.appearance)
        if self.style_tags:
            parts.append(self.style_tags)
        return ", ".join(parts)


@dataclass(frozen=True, slots=True)
class Speaker:
    """One person who speaks in the clip."""
    id: int
    voice: str = ""
    name: str = ""
    uid: str = ""
    subject: int = 0
    voice_from: str = ""


@dataclass(frozen=True, slots=True)
class Line:
    """One spoken line in the H3 guide format."""
    text: str
    speaker: str = ""
    ids: str = "S1"
    delivery: str = "says"
    language: str = "English"
    offscreen: bool = False
    carries: bool = False

    @property
    def numbers(self) -> tuple[int, ...]:
        found = []
        for part in self.ids.split(","):
            digits = "".join(c for c in part if c.isdigit())
            if digits:
                found.append(int(digits))
        return tuple(found) or (1,)

    def render(self, voice: str = "", carried: bool = False, cutoff: bool = False) -> str:
        said = self.text.strip()
        if not said:
            return ""
        who = (voice or self.speaker).strip()
        label = f"({self.ids.strip() or 'S1'})"
        verb = self.delivery.strip() or "says"
        if self.offscreen:
            verb = f"{verb} in an off-screen voiceover"
        tag = self.language.strip() or "English"

        spoken = f"{f'{who} {label}' if who else label} {verb}: <d>[{tag}] {said}</d>"
        if self.offscreen:
            spoken += " while their lips remain completely closed."
        if carried:
            spoken = f"<scenetrans> {spoken}"
        if self.carries:
            spoken += (
                " <cutoff> The speech is truncated by the end of the video."
                if cutoff
                else " <scenetrans> The line continues seamlessly across the cut."
            )
        return spoken


@dataclass(frozen=True, slots=True)
class Shot:
    """A contiguous run of frames with one description."""
    start: int
    length: int
    prompt: str
    camera: str = ""
    media: dict | None = None
    lines: tuple[Line, ...] = ()
    screen_text: str = ""
    transition: str = "cut"
    # Extended fields (from DirectorDeck / shuhao)
    generation_mode: str = ""
    first_image: str = ""
    last_image: str = ""
    reference_images: list[str] = field(default_factory=list)
    cast_ids: list[str] = field(default_factory=list)
    negative_prompt: str = ""
    # Visual direction block (from shuhao)
    direction: dict[str, str] = field(default_factory=dict)

    @property
    def end(self) -> int:
        return self.start + self.length

    def text(
        self,
        voices: dict[int, str] | None = None,
        carried: bool = False,
        cutoff: bool = False,
    ) -> str:
        prose = camera_sentence(self.camera).strip() if self.camera else ""
        parts = [self.prompt.strip(), self._signage(), prose]
        said = list(self.lines) if voices is not None else []
        for at, line in enumerate(said):
            described = " and ".join(
                filter(None, ((voices or {}).get(number, "") for number in line.numbers))
            )
            parts.append(line.render(
                described,
                carried=carried and at == 0,
                cutoff=cutoff and at == len(said) - 1,
            ))
        return _sentences(part for part in parts if part)

    def _signage(self) -> str:
        words = self.screen_text.strip()
        if not words:
            return ""
        if not (words.startswith('"') and words.endswith('"')):
            words = f'"{words}"'
        return f"The words {words} are visible on screen."

    def opener(self) -> str:
        return TRANSITIONS.get(self.transition.strip() or "cut", TRANSITIONS["cut"])

    def carries_over(self) -> bool:
        spoken = [line for line in self.lines if line.text.strip()]
        return bool(spoken) and spoken[-1].carries


@dataclass(frozen=True, slots=True)
class Cue:
    """A span on the audio track."""
    start: int
    length: int
    prompt: str
    media: dict | None = None

    @property
    def end(self) -> int:
        return self.start + self.length


@dataclass(frozen=True, slots=True)
class Move:
    """A span on the camera track (independent of shot boundaries)."""
    start: int
    length: int
    camera: str = ""
    prompt: str = ""
    amplitude: str = ""
    speed: str = ""

    @property
    def end(self) -> int:
        return self.start + self.length

    def text(self) -> str:
        prose = camera_sentence(self.camera, self.amplitude, self.speed).strip()
        body = self.prompt.strip()
        if prose and body:
            return f"{prose} {body}"
        return prose or body


# -- Main Timeline Document ------------------------------------------------

@dataclass(slots=True)
class Timeline:
    """The whole director document.

    Supports H3, LTX, and Bernini models via the `model` field.
    """
    # Core content
    global_prompt: str = ""
    shots: list[Shot] = field(default_factory=list)
    cues: list[Cue] = field(default_factory=list)
    moves: list[Move] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)

    # Speech / cast
    speakers: list[Speaker] = field(default_factory=list)
    speech: bool = True
    music: str = ""

    # Model configuration
    model: VideoModel = VideoModel.H3
    fps: int = lattice.H3_FPS
    duration: int = 0
    width: int = 1280
    height: int = 720

    # Extended: Cast system (from shuhao)
    cast: list[CastMember] = field(default_factory=list)
    style: str = "realistic"

    # Extended: Generation recipe (from DirectorDeck)
    default_mode: str = "t2v"

    # -- derived -----------------------------------------------------------

    @property
    def span(self) -> int:
        ends = [item.end for item in (*self.shots, *self.cues, *self.moves)]
        return max(ends, default=0)

    @property
    def length(self) -> int:
        return lattice.snap_up(self.duration or self.span, self.model)

    @property
    def total_seconds(self) -> float:
        return lattice.to_seconds(self.length, self.model)

    def ordered_shots(self) -> list[Shot]:
        return sorted(self.shots, key=lambda s: (s.start, s.length))

    def ordered_cues(self) -> list[Cue]:
        return sorted(self.cues, key=lambda c: (c.start, c.length))

    def ordered_moves(self) -> list[Move]:
        return sorted(self.moves, key=lambda m: (m.start, m.length))

    def refs_of(self, kind: RefKind) -> list[Reference]:
        return sorted(
            (ref for ref in self.references if ref.kind == kind),
            key=lambda ref: ref.index,
        )

    def voices(self) -> dict[int, str] | None:
        if not self.speech:
            return None
        return {
            speaker.id: speaker.voice.strip()
            for speaker in self.speakers
            if speaker.voice.strip()
        }

    def get_cast_member(self, cast_id: str) -> CastMember | None:
        for member in self.cast:
            if member.id == cast_id:
                return member
        return None

    def get_style_preset(self) -> dict[str, str]:
        return STYLE_PRESETS.get(self.style, STYLE_PRESETS["realistic"])

    # -- segment planning (from DirectorDeck) ------------------------------

    def plan_segments(self) -> list[dict[str, Any]]:
        """Split timeline into renderable segments respecting model limits.

        Each segment is a dict with: start, length, shots, mode, prompt.
        """
        spec = lattice.MODEL_SPECS[self.model]
        max_frames = spec.max_frames
        ordered = self.ordered_shots()
        if not ordered:
            return [{"start": 0, "length": self.length, "shots": [], "mode": self.default_mode}]

        segments: list[dict[str, Any]] = []
        current_start = 0

        for shot in ordered:
            shot_len = lattice.snap_up(shot.length or lattice.from_seconds(3.0, self.model), self.model)
            if shot_len > max_frames:
                # Split oversized shot into multiple segments
                remaining = shot_len
                offset = shot.start
                while remaining > 0:
                    chunk = min(remaining, max_frames)
                    chunk = lattice.snap_down(chunk, self.model) if chunk < remaining else lattice.snap_up(chunk, self.model)
                    if chunk > max_frames:
                        chunk = lattice.snap_down(max_frames, self.model)
                    segments.append({
                        "start": offset,
                        "length": chunk,
                        "shots": [shot],
                        "mode": shot.generation_mode or self.default_mode,
                    })
                    offset += chunk
                    remaining -= chunk
            else:
                segments.append({
                    "start": shot.start,
                    "length": shot_len,
                    "shots": [shot],
                    "mode": shot.generation_mode or self.default_mode,
                })

        return segments

    # -- serialisation -----------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Timeline":
        model_str = data.get("model", "minimax_h3")
        try:
            model = VideoModel(model_str)
        except ValueError:
            model = VideoModel.H3

        return cls(
            global_prompt=flat(data.get("global_prompt", "")),
            music=flat(data.get("music", "")),
            model=model,
            fps=int(data.get("fps", lattice.MODEL_SPECS[model].fps)),
            duration=int(data.get("duration", 0)),
            width=int(data.get("width", 1280)),
            height=int(data.get("height", 720)),
            style=str(data.get("style", "realistic")),
            default_mode=str(data.get("default_mode", "t2v")),
            speech=data.get("speech", True) is not False,
            shots=[
                Shot(
                    start=int(item.get("start", 0)),
                    length=int(item.get("length", 0)),
                    prompt=flat(item.get("prompt", "")),
                    camera=str(item.get("camera", "")),
                    media=item.get("media"),
                    screen_text=flat(item.get("screen_text", "")),
                    transition=str(item.get("transition", "") or "cut"),
                    generation_mode=str(item.get("generation_mode", "")),
                    first_image=str(item.get("first_image", "")),
                    last_image=str(item.get("last_image", "")),
                    reference_images=list(item.get("reference_images", [])),
                    cast_ids=list(item.get("cast_ids", [])),
                    negative_prompt=flat(item.get("negative_prompt", "")),
                    direction=dict(item.get("direction", {})),
                    lines=tuple(
                        Line(
                            text=flat(ln.get("text", "")),
                            speaker=flat(ln.get("speaker", "")),
                            ids=str(ln.get("ids", "S1")),
                            delivery=str(ln.get("delivery", "says")),
                            language=str(ln.get("language", "English")),
                            offscreen=ln.get("offscreen") is True,
                            carries=ln.get("carries") is True,
                        )
                        for ln in (item.get("lines") or [])
                        if isinstance(ln, dict)
                    ),
                )
                for item in data.get("shots", [])
            ],
            cues=[
                Cue(
                    start=int(item.get("start", 0)),
                    length=int(item.get("length", 0)),
                    prompt=flat(item.get("prompt", "")),
                    media=item.get("media"),
                )
                for item in data.get("cues", [])
            ],
            moves=[
                Move(
                    start=int(item.get("start", 0)),
                    length=int(item.get("length", 0)),
                    camera=str(item.get("camera", "")),
                    prompt=flat(item.get("prompt", "")),
                    amplitude=str(item.get("amplitude", "")),
                    speed=str(item.get("speed", "")),
                )
                for item in data.get("moves", [])
            ],
            references=[
                Reference(
                    kind=str(item.get("kind", "picture")),
                    index=int(item.get("index", 1)),
                    label=flat(item.get("label", "")),
                )
                for item in data.get("references", [])
            ],
            speakers=[
                Speaker(
                    id=int(item.get("id", 0)),
                    voice=flat(item.get("voice", "")),
                    name=flat(item.get("name", "")),
                    uid=str(item.get("uid", "")),
                    subject=int(item.get("subject", 0)),
                    voice_from=str(item.get("voice_from", "")),
                )
                for item in data.get("speakers", [])
                if isinstance(item, dict)
            ],
            cast=[
                CastMember(
                    id=str(item.get("id", "")),
                    name=flat(item.get("name", "")),
                    appearance=flat(item.get("appearance", "")),
                    voice=flat(item.get("voice", "")),
                    style_tags=flat(item.get("style_tags", "")),
                    reference_image=str(item.get("reference_image", "")),
                )
                for item in data.get("cast", [])
                if isinstance(item, dict)
            ],
            sources=[item for item in data.get("sources", []) if isinstance(item, dict)],
        )

    @classmethod
    def from_json(cls, text: str) -> "Timeline":
        text = (text or "").strip()
        if not text:
            return cls()
        return cls.from_dict(json.loads(text))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "model": self.model.value,
            "fps": self.fps,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "style": self.style,
            "default_mode": self.default_mode,
            "global_prompt": self.global_prompt,
            "music": self.music,
            "speech": self.speech,
            "speakers": [
                {"id": s.id, "voice": s.voice, "name": s.name,
                 "uid": s.uid, "subject": s.subject,
                 **({} if not s.voice_from else {"voice_from": s.voice_from})}
                for s in self.speakers
            ],
            "cast": [
                {"id": c.id, "name": c.name, "appearance": c.appearance,
                 "voice": c.voice, "style_tags": c.style_tags,
                 "reference_image": c.reference_image}
                for c in self.cast
            ],
            "shots": [
                {
                    "start": shot.start,
                    "length": shot.length,
                    "prompt": shot.prompt,
                    "camera": shot.camera,
                    "transition": shot.transition,
                    "generation_mode": shot.generation_mode,
                    "first_image": shot.first_image,
                    "last_image": shot.last_image,
                    "reference_images": shot.reference_images,
                    "cast_ids": shot.cast_ids,
                    "negative_prompt": shot.negative_prompt,
                    "direction": shot.direction,
                    **({} if not shot.screen_text else {"screen_text": shot.screen_text}),
                    **({} if not shot.media else {"media": shot.media}),
                    **({} if not shot.lines else {"lines": [
                        {"text": ln.text, "speaker": ln.speaker, "ids": ln.ids,
                         "delivery": ln.delivery, "language": ln.language,
                         **({} if not ln.offscreen else {"offscreen": True}),
                         **({} if not ln.carries else {"carries": True})}
                        for ln in shot.lines
                    ]}),
                }
                for shot in self.shots
            ],
            "cues": [
                {"start": c.start, "length": c.length, "prompt": c.prompt,
                 **({} if not c.media else {"media": c.media})}
                for c in self.cues
            ],
            "moves": [
                {"start": m.start, "length": m.length, "camera": m.camera,
                 "prompt": m.prompt, "amplitude": m.amplitude, "speed": m.speed}
                for m in self.moves
            ],
            "references": [
                {"kind": r.kind, "index": r.index, "label": r.label}
                for r in self.references
            ],
            **({} if not self.sources else {"sources": list(self.sources)}),
        }

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def with_references(self, references: list[Reference]) -> "Timeline":
        return replace(self, references=list(references))
