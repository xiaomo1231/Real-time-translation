"""调用 DeepSeek（或任意 OpenAI 兼容接口）按分句流式翻译。"""

from __future__ import annotations

import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from openai import OpenAI

from .config import Settings

_CJK = re.compile(r"[一-鿿]")
_LATIN = re.compile(r"[A-Za-z]")


def target_language(text: str) -> str:
    """中文为主则译成英文，否则译成中文。"""
    cjk = len(_CJK.findall(text))
    latin_words = len(re.findall(r"[A-Za-z]+", text))
    return "en" if cjk >= latin_words else "zh"


SYSTEM_PROMPT = """你是专业的同声传译，正在为视频会议、网课或直播实时翻译字幕。
规则：
1. 把用户发来的字幕片段翻译成{target}，只输出译文，不要解释、不要加引号。
2. 片段来自语音识别，可能有错别字、口语重复或句子不完整：按最可能的意思翻译，不完整的句子就译成不完整的句子，不要补全。
3. 专有名词、人名、产品名保留常见译法；中英夹杂时整体译成{target}。
4. 语气自然、简洁，符合字幕阅读习惯。{glossary}"""


@dataclass
class TranslationEvent:
    seg_id: int
    text: str
    done: bool
    error: str = ""
    first_token_ms: float = 0.0


class Translator:
    """后台线程按顺序翻译定稿分句，流式回调译文。"""

    def __init__(self, cfg: Settings, on_event: Callable[[TranslationEvent], None]):
        self.cfg = cfg
        self.on_event = on_event
        self.q: queue.Queue = queue.Queue()
        self.history: deque = deque(maxlen=max(0, cfg.context_pairs))
        self._stop = threading.Event()
        self.clients = []
        if cfg.api_key:
            self.clients.append((OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=cfg.translate_timeout, max_retries=0), cfg.model))
        if cfg.backup_api_key and cfg.backup_base_url and cfg.backup_model:
            self.clients.append((OpenAI(api_key=cfg.backup_api_key, base_url=cfg.backup_base_url, timeout=cfg.translate_timeout, max_retries=0), cfg.backup_model))
        self.thread = threading.Thread(target=self._run, name="translator", daemon=True)
        self.thread.start()

    @property
    def enabled(self) -> bool:
        return bool(self.clients)

    def submit(self, seg_id: int, text: str) -> None:
        self.q.put((seg_id, text))

    def stop(self) -> None:
        self._stop.set()
        self.q.put(None)

    def _messages(self, text: str) -> list[dict]:
        target = "英文" if target_language(text) == "en" else "简体中文"
        pairs = self.cfg.glossary_pairs()
        glossary = ""
        if pairs:
            glossary = "\n术语表（必须使用）：\n" + "\n".join(f"- {a} → {b}" for a, b in pairs)
        msgs = [{"role": "system", "content": SYSTEM_PROMPT.format(target=target, glossary=glossary)}]
        for src, dst in self.history:
            msgs.append({"role": "user", "content": src})
            msgs.append({"role": "assistant", "content": dst})
        msgs.append({"role": "user", "content": text})
        return msgs

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self.q.get()
            if item is None:
                return
            seg_id, text = item
            if not self.clients:
                self.on_event(TranslationEvent(seg_id, "", True, "未设置 API Key"))
                continue
            self._translate(seg_id, text)

    def _translate(self, seg_id: int, text: str) -> None:
        msgs = self._messages(text)
        last_error = ""
        for client, model in self.clients:
            t0 = time.perf_counter()
            first_ms = 0.0
            out = ""
            try:
                stream = client.chat.completions.create(
                    model=model, messages=msgs, stream=True, temperature=0.3, max_tokens=512
                )
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        if not first_ms:
                            first_ms = (time.perf_counter() - t0) * 1000
                        out += delta
                        self.on_event(TranslationEvent(seg_id, out.strip(), False, first_token_ms=first_ms))
                out = out.strip()
                self.history.append((text, out))
                self.on_event(TranslationEvent(seg_id, out, True, first_token_ms=first_ms))
                return
            except Exception as e:  # 网络、鉴权、限流等：换下一个接口
                last_error = f"{type(e).__name__}: {e}"[:200]
        self.on_event(TranslationEvent(seg_id, "", True, f"翻译失败：{last_error}"))
