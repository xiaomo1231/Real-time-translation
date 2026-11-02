"""把采集、识别、翻译、记录串起来，在后台线程运行。"""

from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import models
from .asr import AsrEngine, Segment
from .audio import AudioSource
from .config import Settings
from .transcript import Transcript
from .translate import TranslationEvent, Translator


@dataclass
class Callbacks:
    partial: Callable[[Segment], None] = lambda s: None
    final: Callable[[Segment], None] = lambda s: None
    translation: Callable[[TranslationEvent], None] = lambda e: None
    status: Callable[[str], None] = lambda m: None
    error: Callable[[str], None] = lambda m: None


@dataclass
class Stats:
    translate_first_token_ms: list = field(default_factory=list)
    second_pass_ms: list = field(default_factory=list)


class Pipeline:
    def __init__(self, cfg: Settings, cb: Callbacks, source: AudioSource | None = None):
        self.cfg = cfg
        self.cb = cb
        self.source = source
        self.stats = Stats()
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.translator: Translator | None = None
        self.transcript: Transcript | None = None
        self.engine: AsrEngine | None = None

    def start(self) -> None:
        self._stop.clear()
        self.thread = threading.Thread(target=self._run, name="pipeline", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=5)

    # ---- 内部 ----
    def _on_final(self, seg: Segment) -> None:
        if self.engine:
            self.stats.second_pass_ms.append(self.engine.last_second_pass_ms)
        self.transcript.set_source(seg.id, seg.text, seg.start, seg.end)
        self.cb.final(seg)
        if self.translator and self.translator.enabled and self.cfg.display_mode != "source":
            self.translator.submit(seg.id, seg.text)
        else:
            self.transcript.set_translation(seg.id, "")

    def _on_translation(self, ev: TranslationEvent) -> None:
        if ev.done:
            if ev.first_token_ms:
                self.stats.translate_first_token_ms.append(ev.first_token_ms)
            self.transcript.set_translation(ev.seg_id, ev.text)
            if ev.error:
                self.cb.error(ev.error)
        self.cb.translation(ev)

    def _run(self) -> None:
        try:
            self.cb.status("正在加载模型…")
            for key in models.required_models(self.cfg.tier, self.cfg.second_pass):
                if not models.is_ready(key):
                    models.ensure_model(
                        key,
                        lambda label, done, total: self.cb.status(
                            f"下载 {label} {done / 1e6:.0f}/{total / 1e6:.0f} MB" if total else f"下载 {label} {done / 1e6:.0f} MB"
                        ),
                    )
            self.engine = AsrEngine(self.cfg, self.cb.partial, self._on_final)
            self.transcript = Transcript(self.cfg.save_transcript)
            self.translator = Translator(self.cfg, self._on_translation)
            if self.source is None:
                self.source = AudioSource(self.cfg.source, self.cfg.device_name)
            self.source.start()
            tip = "" if self.translator.enabled else "（未设置 API Key，只显示原文）"
            self.cb.status(f"正在收听 · {self.source.description}{tip}")
            silence_rate = self.source.sample_rate
            while not self._stop.is_set():
                got = self.source.read(timeout=0.2)
                if got is None:
                    # WASAPI 回环在没有声音时不回调：补静音，让分句能正常结束
                    self.engine.feed(np.zeros(int(0.2 * silence_rate), np.float32), silence_rate)
                    continue
                samples, rate = got
                silence_rate = rate
                self.engine.feed(samples, rate)
            self.engine.flush()
        except Exception as e:
            traceback.print_exc()
            self.cb.error(f"{type(e).__name__}: {e}")
        finally:
            if self.source:
                self.source.stop()
            if self.translator:
                time.sleep(0.1)
                self.translator.stop()
            if self.transcript:
                self.transcript.flush_untranslated()
            self.cb.status("已停止")
