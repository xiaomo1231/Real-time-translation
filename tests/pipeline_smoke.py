"""不接声卡，用 WAV 文件跑完整流程（识别 + 翻译 + 记录）。

用法：python tests/pipeline_smoke.py <wav>...
没有 DEEPSEEK_API_KEY 时只验证识别和记录。
"""

import sys
import time
import wave

import numpy as np

sys.path.insert(0, ".")
from rtt.config import Settings  # noqa: E402
from rtt.pipeline import Callbacks, Pipeline  # noqa: E402


class WavSource:
    """模拟实时声卡：按真实速度吐出 50ms 的音频块。"""

    def __init__(self, paths):
        chunks = []
        for p in paths:
            with wave.open(p) as w:
                self.sample_rate = w.getframerate()
                a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
            chunks += [a, np.zeros(int(1.0 * self.sample_rate), np.float32)]
        self.data = np.concatenate(chunks)
        self.pos = 0
        self.description = "测试音频"
        self.t0 = None

    def start(self):
        self.t0 = time.perf_counter()

    def read(self, timeout=0.2):
        n = int(0.05 * self.sample_rate)
        due = self.t0 + self.pos / self.sample_rate
        if self.pos >= len(self.data):
            time.sleep(timeout)
            return None  # 播完后模拟回环无回调
        wait = due - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        a = self.data[self.pos : self.pos + n]
        self.pos += n
        return a, self.sample_rate

    def stop(self):
        pass


cfg = Settings.load()
cfg.save_transcript = True
done = []
cb = Callbacks(
    final=lambda s: print(f"定稿 #{s.id}: {s.text}"),
    translation=lambda e: e.done and (print(f"  译文 #{e.seg_id}: {e.text or e.error}  (首字 {e.first_token_ms:.0f}ms)"), done.append(e.seg_id)),
    status=lambda m: print("状态:", m),
    error=lambda m: print("错误:", m),
)
src = WavSource(sys.argv[1:])
pipe = Pipeline(cfg, cb, source=src)
pipe.start()
while src.t0 is None:
    time.sleep(0.1)
time.sleep(len(src.data) / src.sample_rate + 4)
pipe.stop()
print("记录文件:", pipe.transcript.txt_path)
print(open(pipe.transcript.srt_path, encoding="utf-8").read()[:600])
