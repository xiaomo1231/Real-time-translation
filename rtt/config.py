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

    # 音频
    source: str = "system"  # system | mic
    device_name: str = ""  # 空 = 系统默认设备

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
