"""用户设置，保存在程序目录下的 data/settings.json。"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


def app_dir() -> Path:
    """程序所在目录（源码运行时为仓库根目录，打包后为 exe 所在目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    d = Path(os.environ.get("RTT_DATA_DIR", app_dir() / "data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Settings:
    # 翻译（OpenAI 兼容接口，默认 DeepSeek）
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    backup_api_key: str = ""
    backup_base_url: str = ""
    backup_model: str = ""
    translate_timeout: float = 8.0
    context_pairs: int = 3
    glossary: str = ""  # 每行一条：原文=译文

    # 场景：meeting | game | call | face（见 rtt/scenes.py）
    scene: str = "meeting"

    # 听：音频来源
    source: str = "system"  # system | apps | mic
    device_name: str = ""  # 空 = 系统默认设备
    listen_apps: list[str] = field(default_factory=lambda: ["Discord.exe"])  # source=apps 时录这些程序

    # 说：按键说中文，合成英文语音输出到虚拟麦克风
    speak_enabled: bool = False
    speak_mode: str = "ptt"  # ptt（按住说话）| auto（自动断句）
    ptt_key: str = "f8"
    speak_mic: str = ""  # 空 = 默认麦克风
    speak_target: str = "en"
    speak_output: str = "CABLE Input"  # 输出设备名包含这段文字即可
    speak_monitor: bool = False  # 同时在耳机里播放
    tts_voice: str = "piper"  # piper | kokoro
    tts_speed: float = 1.05
    read_aloud: bool = False  # 面对面：把听到的中文译成英文后从音箱念出来

    # 打字翻译框
    type_hotkey: str = "<ctrl>+<alt>+t"
    type_speak: bool = False  # 译文同时念到虚拟麦克风

    # 聊天框文字识别
    ocr_enabled: bool = False
    ocr_region: list[int] = field(default_factory=list)  # [x, y, w, h]，屏幕像素
    ocr_interval: float = 1.0

    # 识别
    tier: str = "auto"  # auto | high | low
    second_pass: bool = True
    num_threads: int = 0  # 0 = 自动
    pause_seconds: float = 0.6  # 静音多久算一个分句结束
    max_segment_seconds: float = 12.0

    # 显示
    display_mode: str = "both"  # both | translation | source
    font_size: int = 22
    opacity: float = 0.75
    max_lines: int = 2
    window_geometry: list[int] = field(default_factory=list)

    # 记录
    save_transcript: bool = True

    @classmethod
    def load(cls) -> "Settings":
        path = data_dir() / "settings.json"
        s = cls()
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
            except (OSError, ValueError):
                pass
        if not s.api_key:
            s.api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        return s

    def save(self) -> None:
        path = data_dir() / "settings.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    def glossary_pairs(self) -> list[tuple[str, str]]:
        pairs = []
        for line in self.glossary.splitlines():
            if "=" in line:
                a, b = line.split("=", 1)
                if a.strip() and b.strip():
                    pairs.append((a.strip(), b.strip()))
        return pairs
