"""用模型自带的测试音频验证识别流程：python tests/asr_smoke.py <wav>..."""

import sys
import time
import wave

import numpy as np

sys.path.insert(0, ".")
from rtt import models  # noqa: E402
from rtt.asr import AsrEngine  # noqa: E402
from rtt.config import Settings  # noqa: E402


def read_wav(path):
    with wave.open(path) as w:
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return data, rate


for tier in ("high", "low"):
    cfg = Settings(tier=tier)
    for k in models.required_models(tier, True):
        models.ensure_model(k)
    first_partial = {}
    t_start = [0.0]

    def on_partial(seg):
        first_partial.setdefault(seg.id, time.perf_counter() - t_start[0])

    def on_final(seg):
        print(f"  [{tier}] 定稿 #{seg.id} {seg.start:.1f}-{seg.end:.1f}s: {seg.text}")

    eng = AsrEngine(cfg, on_partial, on_final)
    for path in sys.argv[1:]:
        data, rate = read_wav(path)
        # 两段音频之间插 1.5 秒静音，模拟停顿
        data = np.concatenate([data, np.zeros(int(1.5 * rate), np.float32)])
        chunk = int(0.1 * rate)
        t0 = time.perf_counter()
        t_start[0] = t0
        for i in range(0, len(data), chunk):
            eng.feed(data[i : i + chunk], rate)
        dt = time.perf_counter() - t0
        print(f"  [{tier}] {path}: 音频 {len(data)/rate:.1f}s，处理 {dt:.2f}s，RTF {dt/(len(data)/rate):.3f}，定稿耗时 {eng.last_second_pass_ms:.0f}ms")
    eng.flush()
