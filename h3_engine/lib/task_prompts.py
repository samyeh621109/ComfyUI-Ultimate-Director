"""MiniMax H3 task_type labels and combo options (freeform Qwen prompts — no T5 system prefix)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskPromptSpec:
    key: str
    label: str
    system_prompt: str
    description_zh: str


TASK_PROMPT_SPECS: tuple[TaskPromptSpec, ...] = (
    TaskPromptSpec(
        "default",
        "默認通用",
        "",
        "MiniMax H3 使用 Qwen3-VL 自由提示詞，無需 T5 系統前綴。",
    ),
    TaskPromptSpec(
        "t2v",
        "文生視頻(Text to Video)",
        "",
        "文生音視頻；無首影格/參考圖。",
    ),
    TaskPromptSpec(
        "i2v",
        "圖生視頻(Image to Video)",
        "",
        "首影格圖生音視頻（ImageToVideo + first_frame）。",
    ),
    TaskPromptSpec(
        "fl2v",
        "首尾影格生視頻(First-Last Frame)",
        "",
        "首影格+尾影格約束（可不傳圖=文生；ImageToVideo 可選 first/last）。",
    ),
    TaskPromptSpec(
        "r2v",
        "參考主體生視頻(Reference to Video)",
        "",
        "分組參考改視頻（類似首尾影格分組）：每組可上傳圖片1–9、音頻1–3、視頻1–3；"
        "提示詞用 <Picture N> / <Video K> / <Audio J>。源視頻時間軸剪輯請用 v2v/rv2v。",
    ),
    TaskPromptSpec(
        "v2v",
        "視頻轉視頻(Video to Video)",
        "",
        "上傳源視頻後按時間軸分段編輯；每段源畫面作爲 <Video 1> 送入 ReferenceToVideo（無參考圖槽）。",
    ),
    TaskPromptSpec(
        "rv2v",
        "參考素材改視頻(Reference Video Edit)",
        "",
        "源視頻時間軸編輯，可選參考圖（圖片1–9）與參考音頻（音頻1–3）；"
        "每段源畫面爲 <Video 1>，參考圖用 <Picture N>，參考音頻用 <Audio J>；無參考素材時等同 v2v。",
    ),
)

TASK_PROMPT_BY_KEY = {spec.key: spec for spec in TASK_PROMPT_SPECS}
HIDDEN_TASK_TYPE_KEYS: frozenset[str] = frozenset()


def task_type_option_label(spec: TaskPromptSpec) -> str:
    return f"{spec.key} — {spec.label}"


def task_type_combo_options() -> tuple[list[str], dict]:
    options = [
        task_type_option_label(spec)
        for spec in TASK_PROMPT_SPECS
        if spec.key not in HIDDEN_TASK_TYPE_KEYS and spec.key != "default"
    ]
    default_spec = TASK_PROMPT_BY_KEY["t2v"]
    return options, {
        "default": task_type_option_label(default_spec),
        "tooltip": (
            "MiniMax H3 支持 t2v / i2v / fl2v / r2v / v2v / rv2v。"
            "提示詞直接送入 MiniMaxH3ImageToVideo 或 MiniMaxH3ReferenceToVideo（內部 tokenize）。"
            "r2v 用 <Picture 1>；v2v/rv2v 爲源視頻時間軸編輯（自動綁定 <Video 1>）；rv2v 另可掛參考圖。"
        ),
    }


def resolve_task_key(task_type_value: str) -> str:
    value = task_type_value.split(",[object Object]", 1)[0].strip()
    if " · " in value:
        value = value.split(" · ", 1)[0].strip()
    for sep in (" — ", " —— ", " - ", " – "):
        if sep in value:
            return value.split(sep, 1)[0].strip()
    return value


def get_task_prompt_spec(task_type_value: str) -> TaskPromptSpec:
    key = resolve_task_key(task_type_value)
    return TASK_PROMPT_BY_KEY.get(key, TASK_PROMPT_BY_KEY["default"])


def apply_task_system_prompt(task_type_value: str, positive_prompt: str) -> str:
    """H3 nodes tokenize raw user prompt — no system prefix injection."""
    del task_type_value
    return positive_prompt
