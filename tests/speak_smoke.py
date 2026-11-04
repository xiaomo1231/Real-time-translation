"""说话转译离线测试：用 WAV 当麦克风，模拟按键，把合成的英文语音写到 WAV 文件。

用法：python tests/speak_smoke.py <中文wav> [输出wav]
需要 data/settings.json 里有 API Key（或接一个 OpenAI 兼容的模拟接口）。
"""

import sys
import time
import wave

import numpy as np

sys.path.insert(0, ".")
from rtt.config import Settings  # noqa: E402
from rtt.speak import SpeakCallbacks, SpeakPipeline  # noqa: E402
from rtt.tts import Speaker  # noqa: E402

src_code = open("tests/pipeline_smoke.py", encoding="utf-8").read().split("cfg = Settings.load()")[0]
ns: dict = {}
exec(src_code, ns)
WavSource = ns["WavSource"]


class FakeOut:
    chunks: list = []
    rate = 48000

    def __init__(self, name):
        self.name = f"假设备({name or '默认'})"

    def play(self, samples, rate):
        from rtt.tts import _resample

        a = _resample(samples, rate, self.rate)
        FakeOut.chunks.append(a)
        time.sleep(len(a) / self.rate)

    def close(self):
        pass


cfg = Settings.load()
cfg.speak_mode = "ptt"
t0 = time.perf_counter()
marks = {}
cb = SpeakCallbacks(
    final=lambda s: (marks.setdefault("final", time.perf_counter()), print(f"定稿: {s.text}")),
    translation=lambda e: e.done and print(f"译文: {e.text or e.error}  (首字 {e.first_token_ms:.0f}ms)"),
    playing=lambda b: b and marks.setdefault("play", time.perf_counter()),
    status=lambda m: print("状态:", m),
    error=lambda m: print("错误:", m),
)
speaker = Speaker(cfg, ["CABLE Input"], on_state=cb.playing, on_error=cb.error, out_factory=FakeOut)
src = WavSource(sys.argv[1:2])
pipe = SpeakPipeline(cfg, cb, source=src, speaker=speaker)
pipe.start()
pipe.ready.wait(60)
dur = len(src.data) / src.sample_rate
pipe.ptt(True)
time.sleep(dur - 0.9)  # 说完（去掉末尾 1 秒静音）后松开
pipe.ptt(False)
release = time.perf_counter()
time.sleep(8)
pipe.stop()
if "play" in marks:
    print(f"松开按键 → 开始出英文语音：{marks['play'] - release:.2f}s")
out = sys.argv[2] if len(sys.argv) > 2 else "speak_out.wav"
if FakeOut.chunks:
    a = np.concatenate(FakeOut.chunks)
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FakeOut.rate)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())
    print(f"英文语音 {len(a) / FakeOut.rate:.1f}s 已写入 {out}")
