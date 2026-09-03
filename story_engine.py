# -*- coding: utf-8 -*-
"""Story Engine: Local LLM generation via a scoped llama-server subprocess, for Ultimate Director.

Generates a rich Timeline JSON, Krea2 character & scene prompts, and YUAN-compatible assets
with nuanced human acting, micro-expressions, dialogue budgets, staging lock, and zero VRAM residue.
"""
from __future__ import annotations

import gc
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from typing import Optional, Tuple, Dict, Any, List

import folder_paths

try:
    import json_repair
except ImportError:
    json_repair = None

log = logging.getLogger("UltimateDirector.story_engine")

_DIRECTOR_SYSTEM_PROMPT = """你是一位享譽國際的頂級電影導演、分鏡大師與 AI 影視資產架構師。
你的任務是將使用者的故事創意，改寫並擴寫為【具備仿真人類真人群演級演技、細微動作、極致微表情、專業鏡頭語言、嚴格臺詞預算、左右防跳軸站位、寫實光影與音效設計】的專業影視分鏡劇本，並輸出為標準的結構化 JSON。

【核心導演與分鏡原則】
1. 文戲/武戲雙軌制（Dual-Track System）：
   - 文戲（情感、對白、日常、懸疑、對峙）：以臺詞微動作、視線交錯、環境光影、心理張力為重心。
   - 武戲（戰鬥、追逐、爆發、連擊、法陣）：以高密度動作鏈（每15秒需有10~14個切鏡、60+原子事件）、受力五要素（接觸點、形變、位移、損傷累積碎甲、場景破壞）為重心。

2. 【嚴格忠於使用者輸入主體數量，嚴禁腦補無關人物 (Anti-Hallucination & Exact Cast Extraction)】：
   - 劇本大腦必須 100% 嚴格忠於使用者輸入之故事主體數量，嚴禁憑空捏造無關人物！
   - 單人主題（Solo Action / Focus）：
     * 若使用者輸入只包含 1 位主角（例如：「將軍戰場騎馬殺敵」、「少女獨自看海」、「劍客月下練劍」）：
     * cast 角色名單只能包含該主角 1 人（以及故事中提到的坐騎/載具）！
     * 絕對嚴禁腦補女主角、副將、隨從、路人甲來湊數！
   - 雙人/群像主題（Duo / Multi-Character）：
     * 只有在使用者明確要求多人互動（如「男女主角告白」、「桃園三結義」、「雙雄對決」）時，才在 cast 中加入對應人物。

3. 【坐騎、神獸、載具作為獨立參考主體與外貌死鎖 (Mounts, Vehicles & Visual Lock)】：
   - 當故事包含騎乘物（戰馬、神獸）或核心載具（賽車、戰機）：
     * 必須在 cast 中將該坐騎/載具建立為獨立實體！
     * 【全域外觀與毛色死鎖 (Zero Color Mutation Lock)】：
       在 description 中明確鎖定毛色（純黑/雪白/棗紅）、品種、體型、馬鞍配件，6 個分鏡 100% 絕對一致！
     * 分鏡主體標註 (R2V Binding)：
       請根據下方使用者提示中的【多模態視覺主體指令】，將有傳入參考圖的實體綁定為對應的 <Picture N> 與 <Subject N>。
       若某主體沒有對應的參考圖，請直接用文字生動描述該主體，絕對不要捏造不存在的 <Picture N> 標籤！

4. 仿真人類演戲（Nuanced Human Acting & Micro-expressions）：
   - 眼神與眼部：視線落點轉移、下意識垂眸、瞳孔收縮、眼眶微紅、目光對峙。
   - 面部微表情：眉頭微蹙、後槽牙咬緊使下頜緊繃、嘴角牽動苦笑、喉結滾動、呼吸急促或屏息。
   - 肢體微動作：指節用力攥白、手指微顫、無意識摩挲衣角/飾品/武器、重心後移、過肩側身防備。
   - 對白情緒標註：角色說：「對白」（口音：...，語速：緩/快，情緒：克制/決絕/驚恐）。
   - 注意事項：JSON 字串內容中，對白與說明請一律使用中文引號「」與『』，或英文半形雙引號，並遵守 MiniMax H3 官方規範。

5. 嚴格鏡頭時長與臺詞字數控制（8GB 顯存安全規範與 Dialogue Budget）：
   - 單鏡頭時長嚴格限制為 5.0 ~ 6.0 秒（對應 124 ~ 141 幀，確保 8GB 顯卡二採放大時 0% 爆顯存）。
   - 5.0秒鏡頭臺詞：建議 10~14 字。
   - 6.0秒鏡頭臺詞：建議 12~18 字（20字為單鏡頭之絕對硬上限）。

6. 人物站位防跳軸鎖定與空間幾何鐵律（Strict Staging & Spatial Geometry Lock）：
   - 每個分鏡必須明確鎖定角色左右相對座標（例如：主角恆在畫面左側1/3，對手/搭檔恆在畫面右側1/3）。
   - 切換特寫、過肩鏡頭或景別時，左右相對螢幕方位絕對不可顛倒或鏡像翻轉，確保鏡頭銜接零跳軸。
   - 【實體隔斷與開放空間站位通用法則 (Universal Staging Rule)】：
     * 實體隔斷場景（如收銀台、會議桌、辦公桌、吧台、牢房鐵欄）：角色必須「隔著實體物體相向而立」，嚴禁角色無故穿過物體或並排擠在同一側工作區。
     * 開放自然場景（如戰場、桃園、公園、街道、森林）：明確劃分前景、中景與後景站位，並標註角色視線交互方向。
     * 騎乘/載具場景（如主角騎馬、駕駛開車）：明確標註乘員與載具/坐騎的依附關係（如 <Subject 1> 主角 騎乘在 <Subject 2> 坐騎 背上，單手控韁持槍衝鋒）。

7. 資產提示詞標準（高保真人物一致性、題材真實環境與電影級景別律動）：
   - 【題材環境真實性與防雜亂鐵律 (Genre Authenticity & Anti-Clutter)】：
     * 提示詞必須緊扣當前故事題材之標誌性光影與核心環境。
     * 嚴禁在提示詞中出現與當前故事環境不相符的無關雜物。
   - 【防雙胞胎克隆鐵律 (Strict Solo vs Multi-person Count)】：
     * 單人鏡頭或單人特寫鏡頭，必須在描述開頭明確強調 【單人鏡頭 (Strictly 1 single person, solo, absolutely NO clone, NO duplicate person, NO twin)】。
   - 【全域服裝、外貌與坐騎死鎖鐵律 (Strict Wardrobe, Identity & Mount Lock)】：
     * 同一場戲的所有 6 個分鏡中，所有角色的【髮型、五官、服裝材質、顏色、飾品、武器】以及【坐騎毛色、品種、鞍具】必須 100% 絕對一致！嚴禁在分鏡間突兀換裝或坐騎變色。
   - 【六分鏡電影級景別與動作節奏律動 (Dynamic Action Progression)】：
     * 嚴禁 6 個分鏡全都相同景別！動作戲必須展現極致張力：
       [分鏡1: 戰場環境全景與策馬入場 (Wide establishing & charge entry)]
       [分鏡2: 衝鋒陷陣中景破陣斬敵 (Mid-shot dynamic horse charge & slash)]
       [分鏡3: 主角專注眼神與面部極致微表情特寫 (Intense solo facial micro-expression close-up)]
       [分鏡4: 坐騎飛躍與兵刃交鋒高速特寫 (Mount leap & weapon clash impact close-up)]
       [分鏡5: 橫掃千軍高潮過肩與全景爆發 (Epic climax battle burst)]
       [分鏡6: 浴血定格勝利勒馬回眸近景 (Iconic ending horseback resolution)]

8. 招牌與品牌文字禁止規則（Signage & Brand Avoidance）：
   - 提示詞中嚴禁出現任何具體商業品牌名稱。

9. 聲效與高保真音質標準（Acoustic & Soundscape Clarity）：
   - 對白錄音：強制近麥克風清晰人聲錄音（crisp close-mic studio vocal presence, direct dialogue clarity, zero hollow reverb）。
   - 聲場分層：前景人聲/嘶吼清脆通透、中景生活擬音/兵刃撞擊/馬蹄踏地、後景環境氛圍（風聲、戰火雷鳴）層次分明。

【輸出格式 (嚴格 JSON)】
{
  "project_name": "專案名稱",
  "fps": 24,
  "overall_style": "8k uhd 電影寫實畫面，光影層次豐富，真實皮膚質感，細膩微表情捕捉，35mm電影鏡頭構圖",
  "krea2_character_sheet_prompt": "寫實真人電影照片，四欄橫向並列角色設定圖，同一人物四視圖（Same person consistent identity in all 4 views），35mm電影鏡頭拍攝，真實皮膚毛孔紋理（detailed skin texture, realistic pores），自然眼神光。畫面從左到右嚴格分為四欄：第一欄臉部極致近景特寫，第二欄正面全身站姿，第三欄單側90度側面全身站姿，第四欄背面全身站姿。[根據當前故事精確填寫主角五官長相、髮型、固定服飾材質色彩、武器與環境光影]，cinematic lighting, photorealistic, 8k resolution, raw photo, masterwork, sharp focus, absolutely no text no words no letters no numbers no captions no labels no writing no watermarks",
  "krea2_scene_prompt": "電影寫實劇照，3x2六格宮格分鏡故事板，8k真實畫質，頂級電影光影與大景深。全域角色服裝、外貌與坐騎毛色嚴格固定：[填寫所有登場主體與坐騎的固定外貌]，[統一的場景光影環境]。六格分別展現電影級景別與動作演進：[分鏡1: 登場建立 | 分鏡2: 核心動作展開 | 分鏡3: 主角微表情特寫 | 分鏡4: 關鍵動作/坐騎特寫 | 分鏡5: 劇情高潮激戰 | 分鏡6: 定格落幕近景]，cinematic lighting, photorealistic, 8k uhd, 35mm film photography, highly detailed, raw photo, absolutely no text no words no letters no numbers no captions no labels no writing no watermarks",
  "shots": [
    {
      "id": "shot_1",
      "type": "武戲",
      "title": "分鏡標題",
      "duration_seconds": 5.5,
      "staging": "人物站位：主角在左側(左1/3)，坐騎在正中，視線望向前方",
      "prompt": "subject_definition:\n<Picture 1> is the General, wearing dark steel heavy scale armor and crimson tunic, holding a dark steel spear with red tassel.\n<Picture 2> is the pure black Ferghana steed, glossy black muscular body with dark red leather saddle.\n<Subject 1> is bound to <Picture 1>.\n<Subject 2> is bound to <Picture 2>.\n\noverview:\n[reference generation] 0-5.5s, misty dusk battlefield, <Subject 1> the General riding atop <Subject 2> the pure black steed, charging forward into the smoky battlefield.\n\ndetailed_description:\n[Shot 1] The camera performs a fast tracking shot alongside the galloping steed as the warrior focuses ahead.\n\noverall_soundscape:\nDeep rhythmic hoofbeats pounding on the ground, steed snorting, fluttering battle banners in the wind, distant warrior shouts reverberating across the field.\n\nnon_diegetic_music:\nLow resonant war drums and heavy brass horns building an epic cinematic tension.",
      "dialogue_word_count": 0,
      "cast": ["將軍", "純黑汗血戰馬"],
      "camera_movement": "tracking_shot"
    }
  ],
  "cast": [
    {
      "id": "將軍",
      "name": "將軍",
      "trigger_word": "將軍",
      "description": "二十八歲成年男性，威嚴英挺俊朗面容，無鬍鬚，古裝束髮髻，身披暗銀玄鐵重型鎧甲與深紅戰袍，手握寒光長槍"
    },
    {
      "id": "戰馬",
      "name": "純黑汗血戰馬",
      "trigger_word": "純黑汗血戰馬",
      "description": "一匹通體純黑發亮的高大純種汗血戰馬，肌肉線條強健分明，配備深紅色真皮馬鞍與鐵製鐙韁"
    }
  ],
  "props": [
    "長槍：精鋼槍尖，紅纓飄拂"
  ],
  "scenes": [
    "古代古戰場：黃沙滾滾，硝煙四起，殘陽如血"
  ]
}
只輸出純 JSON，禁止包含任何非 JSON 前後說明！"""


def find_llama_server_bin() -> str:
    """依常見安裝位置猜 llama-server 執行檔路徑，找不到就交給 PATH。"""
    candidates = [
        os.environ.get("LLAMA_SERVER_BIN", ""),
        "/home/sam/llama.cpp/build/bin/llama-server",
        "/usr/local/bin/llama-server",
        "/opt/llama.cpp/build/bin/llama-server",
        "llama-server",
    ]
    for c in candidates:
        if not c:
            continue
        if os.path.isabs(c) and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
        found = shutil.which(c)
        if found:
            return found
    return "llama-server"


def _is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _find_free_port(start: int = 8099, max_tries: int = 20) -> int:
    for p in range(start, start + max_tries):
        if not _is_port_in_use(p):
            return p
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class LlamaServerProcess:
    """Scoped llama-server process lifecycle manager."""

    def __init__(
        self,
        server_bin: str,
        model_path: str,
        n_ctx: int = 16384,
        n_gpu_layers: int = 999,
        cpu_moe_all: bool = True,
        n_cpu_moe: int = -1,
        threads: int = 16,
        port: int = 8099,
        host: str = "127.0.0.1",
        startup_timeout: float = 60.0,
        extra_args: Optional[list] = None,
    ):
        self.server_bin = server_bin
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.cpu_moe_all = cpu_moe_all
        self.n_cpu_moe = n_cpu_moe
        self.threads = threads
        self.port = _find_free_port(port)
        self.host = host
        self.startup_timeout = startup_timeout
        self.extra_args = extra_args or []
        self.proc: Optional[subprocess.Popen] = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self):
        if not os.path.isfile(self.model_path):
            raise FileNotFoundError(f"找不到 GGUF 模型檔案: {self.model_path}")

        cmd = [
            self.server_bin,
            "-m", self.model_path,
            "--host", self.host,
            "--port", str(self.port),
            "-ngl", str(self.n_gpu_layers),
            "-c", str(self.n_ctx),
            "-t", str(self.threads),
            "-fa", "on",
            "--jinja",
        ]
        if self.cpu_moe_all:
            cmd.append("--cpu-moe")
        elif self.n_cpu_moe >= 0:
            cmd.extend(["--n-cpu-moe", str(self.n_cpu_moe)])

        # Dynamic discovery of mmproj multimodal visual projector
        mmproj_search_dirs = []
        if os.path.dirname(self.model_path):
            mmproj_search_dirs.append(os.path.dirname(self.model_path))
        for folder_type in ("LLM", "text_encoders", "checkpoints"):
            try:
                for p in folder_paths.get_folder_paths(folder_type):
                    if p and p not in mmproj_search_dirs:
                        mmproj_search_dirs.append(p)
            except Exception:
                pass
        try:
            if folder_paths.base_path and folder_paths.base_path not in mmproj_search_dirs:
                mmproj_search_dirs.append(folder_paths.base_path)
        except Exception:
            pass

        for search_dir in mmproj_search_dirs:
            if os.path.isdir(search_dir):
                for f in os.listdir(search_dir):
                    if f.lower().startswith("mmproj") and f.lower().endswith(".gguf"):
                        mmproj_file = os.path.join(search_dir, f)
                        cmd.extend(["--mmproj", mmproj_file])
                        log.info("自動掛載視覺多模態投影器 (mmproj): %s", mmproj_file)
                        break
                else:
                    continue
                break

        if self.extra_args:
            cmd.extend(self.extra_args)

        log.info("啟動 llama-server: %s", " ".join(cmd))
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )
        self._wait_until_ready()

    def _wait_until_ready(self):
        health_url = f"{self.base_url}/health"
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                raise RuntimeError(
                    f"llama-server 異常退出 (code {self.proc.returncode})，請檢查模型檔案或 llama.cpp 版本。"
                )
            try:
                with urllib.request.urlopen(health_url, timeout=2) as resp:
                    if resp.status == 200:
                        log.info("llama-server 就緒: %s", self.base_url)
                        return
            except Exception:
                pass
            time.sleep(1.0)
        self.stop()
        raise TimeoutError(
            f"llama-server 在 {self.startup_timeout:.0f} 秒內未就緒，已強制關閉。"
        )

    def chat_completion(
        self,
        messages: list,
        max_tokens: int,
        temperature: float,
        top_p: float = 0.95,
        top_k: int = 40,
        timeout: int = 600,
        response_format: Optional[dict] = None,
    ) -> str:
        payload: dict[str, Any] = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "stream": False,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]

    def stop(self):
        """保證關閉子行程、釋放 VRAM。"""
        if self.proc is None:
            return
        if self.proc.poll() is None:
            log.info("關閉 llama-server，由 OS 回收 VRAM 與記憶體...")
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                log.warning("llama-server 未在 15 秒內正常關閉，強制 kill。")
                self.proc.kill()
                try:
                    self.proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pass
        self.proc = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def _clean_json_text(text: str) -> str:
    """提取並清洗 JSON 字串（去除 think 標籤與 markdown 代碼塊）。"""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if match:
        cleaned = match.group(1).strip()
    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        cleaned = cleaned[start_idx : end_idx + 1]
    return cleaned


def _format_script_preview(data: dict) -> str:
    """格式化劇本預覽文字供畫布節點即時顯示。"""
    lines = []
    lines.append(f"🎬 【作品名稱】：{data.get("project_name", "未命名短劇")}")
    lines.append(f"🎨 【視覺風格】：{data.get("overall_style", "寫實電影質感")}")
    lines.append("-" * 50)
    
    shots = data.get("shots", [])
    lines.append(f"📜 【分鏡清單】（共 {len(shots)} 個鏡頭）：")
    for s in shots:
        sid = s.get("id", "shot")
        stype = s.get("type", "鏡頭")
        title = s.get("title", "")
        dur = s.get("duration_seconds", 5.0)
        staging = s.get("staging", "")
        prompt = s.get("prompt", "")
        wcount = s.get("dialogue_word_count", 0)
        lines.append(f"\n▶ [{sid}] 【{stype} · {dur}s】{title}")
        if staging:
            lines.append(f"  📍 {staging}")
        lines.append(f"  🎬 提示詞：{prompt}")
        if wcount > 0:
            lines.append(f"  ⏱️ 臺詞字數：{wcount} 字 (預算合格)")
            
    return "\n".join(lines)


def _tensor_to_base64_jpeg(image_tensor) -> str:
    import io
    import base64
    import numpy as np
    from PIL import Image
    if hasattr(image_tensor, "cpu"):
        image_tensor = image_tensor.cpu().numpy()
    if image_tensor.ndim == 4:
        image_tensor = image_tensor[0]
    img_np = (image_tensor * 255.0).clip(0, 255).astype(np.uint8)
    pil_img = Image.fromarray(img_np)
    pil_img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class StoryEngine:
    """Wrapper around llama-server subprocess to generate Timelines with 100% VRAM cleanup."""

    def __init__(
        self,
        model_path: str,
        server_bin: Optional[str] = None,
        n_ctx: int = 16384,
        n_gpu_layers: int = 999,
        cpu_moe_all: bool = True,
        n_cpu_moe: int = -1,
        threads: int = 16,
        port: int = 8099,
        extra_args: Optional[list] = None,
    ):
        self.model_path = model_path
        self.server_bin = server_bin or find_llama_server_bin()
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.cpu_moe_all = cpu_moe_all
        self.n_cpu_moe = n_cpu_moe
        self.threads = threads
        self.port = port
        self.extra_args = extra_args or []

    def generate_timeline(
        self,
        idea: str,
        genre: str = "古裝權謀",
        scene_count: int = 6,
        max_tokens: int = 8192,
        temperature: float = 0.6,
        timeout: int = 600,
        ref_images: Optional[list] = None,
        custom_skill_prompt: str = "",
    ) -> Tuple[dict, str, str, str, str]:
        """啟動 llama-server 子行程，生成分鏡 JSON，完成後關閉並釋放顯存。支援傳入多模態參考圖與自訂 Skills。"""
        user_prompt = f"""【創作需求】
題材類型：{genre}
期望分鏡數量：{scene_count} 個鏡頭
故事核心梗概：
{idea}

請嚴格遵循【文戲/武戲雙軌制】、【仿真人類演戲與微表情】、【嚴格臺詞字數預算(<40字)】與【人物左右站位鎖定(Staging Lock)】，直接輸出標準 JSON！"""

        has_images = False
        user_content_list = []
        vlm_guidelines = []
        
        if ref_images is not None:
            for idx, img in enumerate(ref_images):
                if img is None:
                    continue
                try:
                    b64 = _tensor_to_base64_jpeg(img)
                    user_content_list.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                    })
                    if idx == 0:
                        vlm_guidelines.append(
                            f"【多模態視覺主體 {idx+1} (Picture {idx+1} / Subject {idx+1} 最高指令)】：已傳入第 {idx+1} 張真實參考圖作為故事主角。"
                            f"必須建立綁定：<Subject {idx+1}> 鎖定為 <Picture {idx+1}> 中的主角。"
                            "【絕對嚴禁盲目硬編碼】！你必須睜大雙眼親自審視此圖：判定真實性別（女性/男性/少女/少年）、年齡面容、髮型髮長（長髮披肩/短髮）、五官氣質與神韻。"
                            "若圖中為女性/少女，必須以女主角/巾幗女將軍身份寫入劇本，保留其柔美面貌與長黑髮，絕對嚴禁寫成成年男性或古代男子束髮髻！"
                            f"在 subject_definitions 中必須精準如實提取並鎖定其真實相貌（fully preserving her/his recognized facial features, hairstyle, and authentic visual identity from <Picture {idx+1}>）！"
                        )
                    else:
                        vlm_guidelines.append(
                            f"【多模態視覺主體 {idx+1} (Picture {idx+1} / Subject {idx+1} 最高指令)】：已傳入第 {idx+1} 張真實參考圖（坐騎/載具/副角/核心道具）。"
                            f"必須建立綁定：<Subject {idx+1}> 鎖定為 <Picture {idx+1}> 中的主體。"
                            f"請親眼審視其真實物種、毛色品相、外型輪廓與裝備細節，並在劇本與 <Picture {idx+1}> 提示詞中如實提取鎖定！"
                        )
                    has_images = True
                except Exception as e:
                    log.warning(f"參考圖片 {idx+1} 轉 base64 失敗: %s", e)

        if has_images:
            full_user_text = user_prompt + "\n\n" + "\n".join(vlm_guidelines)
            user_content = [{"type": "text", "text": full_user_text}] + user_content_list
        else:
            user_content = user_prompt


        system_content = _DIRECTOR_SYSTEM_PROMPT
        if custom_skill_prompt and custom_skill_prompt.strip():
            system_content += f"\n\n【使用者自訂導演技能與創作心法 (Injected Director Skills)】：\n{custom_skill_prompt.strip()}\n請將上述技能心法深度貫徹到角色立繪提示詞 (krea2_character_sheet_prompt)、分鏡提示詞 (shots) 與視覺風格中！"

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        server = LlamaServerProcess(
            server_bin=self.server_bin,
            model_path=self.model_path,
            n_ctx=self.n_ctx,
            n_gpu_layers=self.n_gpu_layers,
            cpu_moe_all=self.cpu_moe_all,
            n_cpu_moe=self.n_cpu_moe,
            threads=self.threads,
            port=self.port,
            extra_args=self.extra_args,
        )

        with server:
            log.info("發送推理請求至 llama-server...")
            raw_text = server.chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                response_format={"type": "json_object"},
            )

        log.info("llama-server 子行程已終止，顯存已歸還作業系統。正在解析結構化資料...")

        cleaned_json = _clean_json_text(raw_text)
        data = None

        if json_repair is not None:
            try:
                repaired = json_repair.loads(cleaned_json)
                if isinstance(repaired, dict) and "shots" in repaired:
                    data = repaired
            except Exception as e:
                log.debug("json_repair 解析失敗: %s", e)

        if data is None:
            try:
                data = json.loads(cleaned_json)
            except Exception:
                pass

        if data is None:
            try:
                repaired_str = re.sub(r",\s*([\]}])", r"", cleaned_json)
                data = json.loads(repaired_str)
            except Exception:
                pass

        if not isinstance(data, dict):
            log.warning("JSON 解析完全失敗，啟用草稿降級保護。")
            data = {
                "project_name": "解析失敗草稿",
                "overall_style": "寫實電影風格",
                "krea2_character_sheet_prompt": "寫實畫面，四欄橫向並列角色設定圖...",
                "krea2_scene_prompt": "寫實畫面，3x2六格宮格故事板...",
                "shots": [{"id": "shot_1", "duration_seconds": 5.0, "prompt": raw_text[:300]}],
            }

        _no_text_suffix = ", absolutely no text, no words, no letters, no numbers, no captions, no labels, no writing, no watermarks, plain clean environment"
        krea_char = str(data.get("krea2_character_sheet_prompt") or "")
        if krea_char and "no text" not in krea_char.lower():
            krea_char += _no_text_suffix
        krea_scene = str(data.get("krea2_scene_prompt") or "")
        if krea_scene and "no text" not in krea_scene.lower():
            krea_scene += _no_text_suffix

        # Construct storyboard prompt dynamically aligned with the script shots
        shots = data.get("shots", [])
        if not krea_scene and isinstance(shots, list) and len(shots) >= 6:
            positions = [
                "第1排左格 (Top-Left Panel 1)",
                "第1排中格 (Top-Middle Panel 2)",
                "第1排右格 (Top-Right Panel 3)",
                "第2排左格 (Bottom-Left Panel 4)",
                "第2排中格 (Bottom-Middle Panel 5)",
                "第2排右格 (Bottom-Right Panel 6)",
            ]
            panel_prompts = []
            for i, shot in enumerate(shots[:6]):
                stitle = str(shot.get("title") or f"Shot {i+1}")
                sprompt = str(shot.get("prompt") or "")
                vis = re.split(r"對白|音效|台詞", sprompt)[0].strip()
                vis = re.sub(r"^\d+[\-\.]\d+s[，,\s]*", "", vis)
                panel_prompts.append(f"[{positions[i]}: {stitle} - {vis}]")

            _shot_flow = " | ".join(panel_prompts)
            _grid_header = "3x2 film storyboard, 6-shot cinematic contact sheet arranged in exactly 2 horizontal rows and 3 vertical columns (total 6 panels, strictly 2 rows of 3 images each, NOT 9 panels, NOT 3 rows)."
            style_desc = str(data.get("overall_style") or "cinematic lighting, photorealistic, 8k uhd, 35mm film photography")
            krea_scene = f"{_grid_header} [{style_desc}] {_shot_flow}, raw photo, masterwork, sharp focus{_no_text_suffix}"

        # Replace specific real-world commercial brand names with generic categories
        _brand_subs = [
            (r"7[\-\s]?(?:11|ELEVEN|eleven)", "convenience store"),
            (r"全家便利(?:商店)?|FamilyMart", "convenience store"),
            (r"星巴克|Starbucks", "coffee shop"),
            (r"麥當勞|McDonald\'?s?", "fast food restaurant"),
            (r"肯德基|KFC", "fried chicken restaurant"),
        ]
        for pattern, replacement in _brand_subs:
            krea_scene = re.sub(pattern, replacement, krea_scene, flags=re.IGNORECASE)
            krea_char = re.sub(pattern, replacement, krea_char, flags=re.IGNORECASE)

        # Ensure cast wardrobe lock is explicitly injected
        cast_list = data.get("cast", [])
        if isinstance(cast_list, list) and cast_list:
            cast_descs = []
            for c in cast_list:
                if isinstance(c, dict):
                    cid = str(c.get("id") or c.get("trigger_word") or "")
                    cdesc = str(c.get("description") or "")
                    if cid and cdesc:
                        cast_descs.append(f"{cid}（固定穿著：{cdesc}）")
            if cast_descs:
                lock_text = "【六宮格全域角色服裝與現代超商環境死鎖（EXACT SAME characters, wardrobe, and modern convenience store in all 6 panels）】： " + "，".join(cast_descs) + "。"
                if "全域角色服裝" not in krea_scene:
                    krea_scene = lock_text + " " + krea_scene

        # Clean any clerk necktie, business suit, or pharmacy hallucinations
        krea_scene = re.sub(r"領帶|necktie|西裝|suit and tie", "工作短袖襯衫 (short sleeve work uniform, no tie)", krea_scene, flags=re.IGNORECASE)
        krea_scene = re.sub(r"藥房|藥局|pharmacy|drugstore|medicine|pills|apothecary", "convenience store snacks and drinks", krea_scene, flags=re.IGNORECASE)

        yuan_json = json.dumps(data, ensure_ascii=False, indent=2)
        preview = _format_script_preview(data)

        return (data, krea_char, krea_scene, yuan_json, preview)

    def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.6,
        max_tokens: int = 2048,
        timeout: int = 300,
    ) -> str:
        """輕量單次呼叫 llama-server，完成後自動關閉並釋放顯存。"""
        server = LlamaServerProcess(
            server_bin=self.server_bin,
            model_path=self.model_path,
            n_ctx=self.n_ctx,
            n_gpu_layers=self.n_gpu_layers,
            cpu_moe_all=self.cpu_moe_all,
            n_cpu_moe=self.n_cpu_moe,
            threads=self.threads,
            port=self.port,
            extra_args=self.extra_args,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        with server:
            resp = server.chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
        return resp.strip()
