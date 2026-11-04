"""场景预设：一键切换「听什么、要不要说、要不要看聊天框」。"""

from __future__ import annotations

from .config import Settings

SCENES = {
    "meeting": "会议 / 网课 / 直播",
    "game": "游戏",
    "call": "跨语言通话",
    "face": "面对面",
}


def apply_scene(cfg: Settings, scene: str) -> None:
    from . import apps

    cfg.scene = scene
    per_app = apps.supported()
    if scene == "meeting":
        cfg.source = "system"
        cfg.speak_enabled = False
        cfg.ocr_enabled = False
        cfg.read_aloud = False
    elif scene == "game":
        cfg.source = "apps" if per_app else "system"
        cfg.speak_enabled = True
        cfg.speak_mode = "ptt"
        cfg.ocr_enabled = bool(cfg.ocr_region)
        cfg.read_aloud = False
    elif scene == "call":
        cfg.source = "apps" if per_app else "system"
        cfg.speak_enabled = True
        cfg.ocr_enabled = False
        cfg.read_aloud = False
    elif scene == "face":
        cfg.source = "mic"
        cfg.device_name = cfg.speak_mic
        cfg.speak_enabled = False
        cfg.ocr_enabled = False
        cfg.read_aloud = True
