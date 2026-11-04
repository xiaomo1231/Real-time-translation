"""游戏聊天框翻译：读 OCR 子进程的结果，去重后把新消息译成中文。"""

from __future__ import annotations

import difflib
import json
import subprocess
import sys
import threading
from collections import deque
from typing import Callable

from .config import Settings
from .translate import TranslationEvent, Translator, target_language

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _norm(s: str) -> str:
    return "".join(ch.lower() for ch in s if ch.isalnum())


class ChatWatcher:
    def __init__(
        self,
        cfg: Settings,
        on_message: Callable[[int, str], None],
        on_translation: Callable[[TranslationEvent], None],
        on_error: Callable[[str], None],
    ):
        self.cfg = cfg
        self.on_message = on_message
        self.on_error = on_error
        self.seen: deque[str] = deque(maxlen=300)
        self.next_id = 0
        self.translator = Translator(cfg, on_translation, target="zh")
        self.proc: subprocess.Popen | None = None

    def is_new(self, line: str) -> bool:
        n = _norm(line)
        if len(n) < 2:
            return False
        for old in self.seen:
            if n == old or (len(n) > 6 and difflib.SequenceMatcher(None, n, old).ratio() > 0.85):
                return False
        self.seen.append(n)
        return True

    def handle_lines(self, lines: list[str], first: bool) -> None:
        for line in lines:
            if not self.is_new(line) or first:
                continue
            # 中文消息不用翻译
            if target_language(line) == "en":
                continue
            seg_id = self.next_id
            self.next_id += 1
            self.on_message(seg_id, line)
            self.translator.submit(seg_id, line)

    def start(self) -> None:
        x, y, w, h = self.cfg.ocr_region
        cmd = [sys.executable, "-m", "rtt.ocr_worker", str(x), str(y), str(w), str(h), str(self.cfg.ocr_interval)]
        from .config import app_dir

        self.proc = subprocess.Popen(
            cmd, cwd=str(app_dir()), stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW, text=True, encoding="utf-8"
        )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        first = True
        for raw in self.proc.stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if "lines" in msg:
                # 第一次截图里已有的旧消息只记下不翻译
                self.handle_lines(msg["lines"], first)
                first = False
        if self.proc.poll() not in (None, 0):
            err = (self.proc.stderr.read() or "").strip().splitlines()
            self.on_error("聊天框识别出错：" + (err[-1] if err else "子进程退出"))

    def stop(self) -> None:
        if self.proc:
            self.proc.kill()
        self.translator.stop()
