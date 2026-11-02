"""本地双遍识别：流式模型实时出字，分句结束后用 SenseVoice 定稿。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np
import sherpa_onnx

from . import models
from .config import Settings


@dataclass
class Segment:
    id: int
    text: str
    start: float  # 相对会话开始的秒数
    end: float
    final: bool


PartialCb = Callable[[Segment], None]
FinalCb = Callable[[Segment], None]


def _build_online(tier: str, threads: int, cfg: Settings) -> sherpa_onnx.OnlineRecognizer:
    common = dict(
        num_threads=threads,
        sample_rate=16000,
        feature_dim=80,
        decoding_method="greedy_search",
        enable_endpoint_detection=True,
        rule1_min_trailing_silence=2.4,
        rule2_min_trailing_silence=cfg.pause_seconds,
        rule3_min_utterance_length=cfg.max_segment_seconds,
        provider="cpu",
    )
    if models.resolve_tier(tier) == "high":
        p = models.model_path("paraformer")
        return sherpa_onnx.OnlineRecognizer.from_paraformer(
            tokens=str(p / "tokens.txt"),
            encoder=str(p / "encoder.int8.onnx"),
            decoder=str(p / "decoder.int8.onnx"),
            **common,
        )
    p = models.model_path("zipformer")
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(p / "tokens.txt"),
        encoder=str(p / "encoder-epoch-99-avg-1.int8.onnx"),
        decoder=str(p / "decoder-epoch-99-avg-1.int8.onnx"),
        joiner=str(p / "joiner-epoch-99-avg-1.int8.onnx"),
        **common,
    )


def _build_offline(threads: int) -> sherpa_onnx.OfflineRecognizer:
    p = models.model_path("sensevoice")
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(p / "model.int8.onnx"),
        tokens=str(p / "tokens.txt"),
        num_threads=threads,
        use_itn=True,
        language="auto",
    )


_MEANINGFUL = re.compile(r"[0-9A-Za-z\u4e00-\u9fff]")
_FOREIGN = re.compile(r"[\u3040-\u30ff\uac00-\ud7af]")


def _tidy(text: str) -> str:
    """流式模型输出的英文是全大写，转成句首大写，便于阅读和翻译。"""
    text = text.strip()
    letters = [c for c in text if c.isascii() and c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        text = text.lower()
        text = text[:1].upper() + text[1:]
        text = text.replace(" i ", " I ")
    return text


class AsrEngine:
    """非线程安全：只在一个工作线程里调用 feed()。"""

    def __init__(self, cfg: Settings, on_partial: PartialCb, on_final: FinalCb):
        self.cfg = cfg
        self.on_partial = on_partial
        self.on_final = on_final
        threads = cfg.num_threads or models.default_threads(cfg.tier)
        self.online = _build_online(cfg.tier, threads, cfg)
        self.offline = _build_offline(threads) if cfg.second_pass else None
        self.stream = self.online.create_stream()
        self.seg_id = 0
        self.seg_audio: list[np.ndarray] = []
        self.seg_rate = 16000
        self.samples_total = 0  # 16k 等效样本数，用于时间戳
        self.seg_start = 0.0
        self.last_text = ""
        self.last_second_pass_ms = 0.0

    @property
    def now(self) -> float:
        return self.samples_total / 16000

    def feed(self, samples: np.ndarray, sample_rate: int) -> None:
        samples = np.ascontiguousarray(samples, dtype=np.float32)
        if not self.seg_audio:
            self.seg_start = self.now
        self.seg_audio.append(samples)
        self.seg_rate = sample_rate
        self.samples_total += int(len(samples) * 16000 / sample_rate)
        self.stream.accept_waveform(sample_rate, samples)
        while self.online.is_ready(self.stream):
            self.online.decode_stream(self.stream)
        text = _tidy(self.online.get_result(self.stream))
        if text and text != self.last_text:
            self.last_text = text
            self.on_partial(Segment(self.seg_id, text, self.seg_start, self.now, False))
        if self.online.is_endpoint(self.stream):
            self._finalize()

    def flush(self) -> None:
        """会话结束时把最后一段定稿。"""
        tail = np.zeros(int(0.8 * self.seg_rate), dtype=np.float32)
        self.stream.accept_waveform(self.seg_rate, tail)
        self.stream.input_finished()
        while self.online.is_ready(self.stream):
            self.online.decode_stream(self.stream)
        self.last_text = _tidy(self.online.get_result(self.stream)) or self.last_text
        self._finalize()

    def _finalize(self) -> None:
        text = self.last_text
        if text and self.offline is not None and self.seg_audio:
            audio = np.concatenate(self.seg_audio)
            t0 = time.perf_counter()
            s = self.offline.create_stream()
            s.accept_waveform(self.seg_rate, audio)
            self.offline.decode_stream(s)
            refined = s.result.text.strip()
            self.last_second_pass_ms = (time.perf_counter() - t0) * 1000
            # 只做中英互译：定稿结果若混入日文假名或韩文，说明判错语种，保留流式结果
            if refined and not _FOREIGN.search(refined):
                text = refined
        if _MEANINGFUL.search(text):
            self.on_final(Segment(self.seg_id, text, self.seg_start, self.now, True))
            self.seg_id += 1
        self.online.reset(self.stream)
        self.seg_audio = []
        self.last_text = ""
