"""说话转译：麦克风说中文 → 本地识别 → DeepSeek 译成英文 → 本地合成语音 → 虚拟麦克风。"""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import models
from .asr import AsrEngine, Segment
from .audio import AudioSource
from .config import Settings
from .translate import TranslationEvent, Translator
from .tts import Speaker, split_ready, tts_model_key


@dataclass
class SpeakCallbacks:
    partial: Callable[[Segment], None] = lambda s: None
    final: Callable[[Segment], None] = lambda s: None
    translation: Callable[[TranslationEvent], None] = lambda e: None
    talking: Callable[[bool], None] = lambda b: None  # 按键按下/松开
    playing: Callable[[bool], None] = lambda b: None  # 英文语音正在播放
    status: Callable[[str], None] = lambda m: None
    error: Callable[[str], None] = lambda m: None


class SpeakPipeline:
    def __init__(self, cfg: Settings, cb: SpeakCallbacks, source=None, speaker=None):
        self.cfg = cfg
        self.cb = cb
        self.source = source
        self.speaker: Speaker | None = speaker
        self.translator: Translator | None = None
        self.engine: AsrEngine | None = None
        self._down = threading.Event()
        self._release = threading.Event()
        self._stop = threading.Event()
        self.sent: dict[int, int] = {}  # 每句译文已经送去合成的字符数
        self.thread: threading.Thread | None = None
        self.ready = threading.Event()

    # ---- 按键 ----
    def ptt(self, down: bool) -> None:
        if down and not self._down.is_set():
            self._down.set()
            self.cb.talking(True)
        elif not down and self._down.is_set():
            self._down.clear()
            self._release.set()
            self.cb.talking(False)

    def say_text(self, text: str) -> None:
        """打字翻译框：直接念一段英文。"""
        if self.speaker:
            self.speaker.say(text)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="speak", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=5)

    # ---- 内部 ----
    def _on_final(self, seg: Segment) -> None:
        self.cb.final(seg)
        self.translator.submit(seg.id, seg.text)

    def _on_translation(self, ev: TranslationEvent) -> None:
        self.cb.translation(ev)
        if ev.error or self.speaker is None:
            return
        sent = self.sent.get(ev.seg_id, 0)
        if ev.done:
            rest = ev.text[sent:]
            self.sent.pop(ev.seg_id, None)
            self.speaker.say(rest)
            return
        ready, _ = split_ready(ev.text)
        if len(ready) > sent:
            self.speaker.say(ready[sent:])
            self.sent[ev.seg_id] = len(ready)

    def _run(self) -> None:
        try:
            self.cb.status("说话转译：正在加载模型…")
            keys = models.required_models(self.cfg.tier, self.cfg.second_pass) + [tts_model_key(self.cfg.tts_voice)]
            for key in keys:
                if not models.is_ready(key):
                    models.ensure_model(
                        key,
                        lambda label, done, total: self.cb.status(f"下载 {label} {done / 1e6:.0f}/{total / 1e6:.0f} MB"),
                    )
            self.engine = AsrEngine(self.cfg, self.cb.partial, self._on_final)
            self.translator = Translator(self.cfg, self._on_translation, target=self.cfg.speak_target, spoken=True)
            if not self.translator.enabled:
                self.cb.error("说话转译需要先在设置里填写 DeepSeek API Key")
            if self.speaker is None:
                outs = [self.cfg.speak_output] + ([""] if self.cfg.speak_monitor else [])
                self.speaker = Speaker(self.cfg, outs, on_state=self.cb.playing, on_error=self.cb.error)
            if self.source is None:
                self.source = AudioSource("mic", self.cfg.speak_mic)
            self.source.start()
            self.ready.set()
            mode = f"按住 {self.cfg.ptt_key.upper()} 说话" if self.cfg.speak_mode == "ptt" else "自动断句"
            outs = "、".join(self.speaker.output_names) or "无可用输出设备"
            self.cb.status(f"说话转译已就绪 · {mode} · 输出到 {outs}")
            rate = self.source.sample_rate
            while not self._stop.is_set():
                got = self.source.read(timeout=0.1)
                if self._release.is_set():
                    self._release.clear()
                    if got is not None:
                        self.engine.feed(got[0], got[1])
                    self.engine.end_utterance()
                    continue
                active = self.cfg.speak_mode == "auto" or self._down.is_set()
                if got is None:
                    if self.cfg.speak_mode == "auto":
                        self.engine.feed(np.zeros(int(0.1 * rate), np.float32), rate)
                    continue
                samples, rate = got
                if active:
                    if self.cfg.speak_mode == "auto" and self.cfg.speak_monitor and self.speaker.speaking:
                        samples = np.zeros_like(samples)  # 耳机外放时避免录到自己的英文
                    self.engine.feed(samples, rate)
        except Exception as e:
            traceback.print_exc()
            self.cb.error(f"说话转译出错：{type(e).__name__}: {e}")
        finally:
            if self.source:
                self.source.stop()
            if self.translator:
                self.translator.stop()
            if self.speaker:
                self.speaker.stop()
