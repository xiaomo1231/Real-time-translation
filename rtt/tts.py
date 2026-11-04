"""本地语音合成（sherpa-onnx：Piper / Kokoro）和音频输出。

Speaker 在后台线程里按顺序合成并播放句子，可以同时输出到虚拟麦克风和耳机。
"""

from __future__ import annotations

import queue
import re
import threading
import time
from typing import Callable

import numpy as np
import sherpa_onnx

from . import models
from .config import Settings


def build_tts(voice: str, threads: int = 2) -> sherpa_onnx.OfflineTts:
    if voice == "kokoro":
        p = models.model_path("kokoro")
        kokoro = sherpa_onnx.OfflineTtsKokoroModelConfig(
            model=str(p / "model.int8.onnx"),
            voices=str(p / "voices.bin"),
            tokens=str(p / "tokens.txt"),
            data_dir=str(p / "espeak-ng-data"),
            lexicon=f"{p / 'lexicon-us-en.txt'},{p / 'lexicon-zh.txt'}",
        )
        model = sherpa_onnx.OfflineTtsModelConfig(kokoro=kokoro, num_threads=threads, provider="cpu")
    else:
        p = models.model_path("piper")
        vits = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(p / "en_US-lessac-medium.onnx"),
            tokens=str(p / "tokens.txt"),
            data_dir=str(p / "espeak-ng-data"),
        )
        model = sherpa_onnx.OfflineTtsModelConfig(vits=vits, num_threads=threads, provider="cpu")
    return sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=model, max_num_sentences=1))


def tts_model_key(voice: str) -> str:
    return "kokoro" if voice == "kokoro" else "piper"


def split_ready(text: str) -> tuple[str, str]:
    """把流式译文切成「已完整的句子」和「剩余部分」。"""
    last = 0
    for m in re.finditer(r"[.!?;。！？；](\s+|$)", text):
        last = m.end()
    return text[:last].strip(), text[last:]


def _resample(a: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or len(a) == 0:
        return a
    n = int(round(len(a) * dst / src))
    x = np.linspace(0, len(a) - 1, n)
    return np.interp(x, np.arange(len(a)), a).astype(np.float32)


class AudioOut:
    """按设备名打开 sounddevice 输出流；找不到设备时 ok=False。"""

    def __init__(self, name_contains: str):
        import sounddevice as sd

        self.sd = sd
        self.device = None
        self.name = ""
        if name_contains == "":
            info = sd.query_devices(kind="output")
            self.device, self.name = None, info["name"]
        else:
            # 优先选 MME / WASAPI 以外也行，名称匹配即可；多个同名时取第一个
            for i, d in enumerate(sd.query_devices()):
                if d["max_output_channels"] > 0 and name_contains.lower() in d["name"].lower():
                    self.device, self.name = i, d["name"]
                    break
            if self.device is None:
                raise RuntimeError(f"找不到输出设备「{name_contains}」。说话转译需要先安装 VB-CABLE 虚拟声卡")
        info = sd.query_devices(self.device, "output")
        self.rate = int(info["default_samplerate"])
        self.stream = sd.OutputStream(device=self.device, samplerate=self.rate, channels=1, dtype="float32")
        self.stream.start()

    def play(self, samples: np.ndarray, rate: int) -> None:
        a = _resample(np.asarray(samples, np.float32), rate, self.rate)
        self.stream.write(a.reshape(-1, 1))

    def close(self) -> None:
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass


class Speaker:
    """后台合成 + 播放。say() 立即返回；on_state(True/False) 报告是否正在出声。"""

    def __init__(
        self,
        cfg: Settings,
        outputs: list[str],
        on_state: Callable[[bool], None] = lambda b: None,
        on_error: Callable[[str], None] = lambda m: None,
        out_factory=AudioOut,
    ):
        self.cfg = cfg
        self.on_state = on_state
        self.on_error = on_error
        self.q: queue.Queue = queue.Queue()
        self.outs = []
        for name in outputs:
            try:
                self.outs.append(out_factory(name))
            except Exception as e:
                on_error(str(e))
        models.ensure_model(tts_model_key(cfg.tts_voice))
        self.tts = build_tts(cfg.tts_voice)
        self.busy_until = 0.0
        self.thread = threading.Thread(target=self._run, name="speaker", daemon=True)
        self.thread.start()

    @property
    def output_names(self) -> list[str]:
        return [o.name for o in self.outs]

    @property
    def speaking(self) -> bool:
        return time.monotonic() < self.busy_until or not self.q.empty()

    def say(self, text: str) -> None:
        text = text.strip()
        if text:
            self.q.put(text)

    def stop(self) -> None:
        self.q.put(None)
        self.thread.join(timeout=3)
        for o in self.outs:
            o.close()

    def _run(self) -> None:
        while True:
            text = self.q.get()
            if text is None:
                return
            try:
                audio = self.tts.generate(text, sid=0, speed=self.cfg.tts_speed)
                samples = np.asarray(audio.samples, np.float32)
                if len(samples) == 0:
                    continue
                self.busy_until = time.monotonic() + len(samples) / audio.sample_rate + 0.3
                self.on_state(True)
                threads = [threading.Thread(target=o.play, args=(samples, audio.sample_rate)) for o in self.outs]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            except Exception as e:
                self.on_error(f"语音合成失败：{e}")
            finally:
                if self.q.empty():
                    self.on_state(False)
