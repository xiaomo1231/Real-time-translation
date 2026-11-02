"""音频采集：Windows 用 WASAPI 回环录系统声音；麦克风和 macOS 用 sounddevice。

回调里把音频转成单声道 float32，放进队列，由识别线程处理。
"""

from __future__ import annotations

import queue
import sys
from dataclasses import dataclass

import numpy as np

IS_WIN = sys.platform == "win32"


@dataclass
class DeviceInfo:
    name: str
    kind: str  # system | mic


def _to_mono_float(data: bytes | np.ndarray, channels: int, int16: bool) -> np.ndarray:
    if int16:
        a = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        a = np.asarray(data, dtype=np.float32).reshape(-1)
    if channels > 1:
        a = a.reshape(-1, channels).mean(axis=1)
    return a


def list_devices(kind: str) -> list[str]:
    """列出可选设备名，空字符串表示系统默认。"""
    names = [""]
    try:
        if kind == "system" and IS_WIN:
            import pyaudiowpatch as pyaudio

            p = pyaudio.PyAudio()
            try:
                for d in p.get_loopback_device_info_generator():
                    names.append(d["name"])
            finally:
                p.terminate()
        else:
            import sounddevice as sd

            for d in sd.query_devices():
                if d["max_input_channels"] > 0:
                    names.append(d["name"])
    except Exception:
        pass
    return names


class AudioSource:
    """start() 后，read() 返回 (samples, sample_rate)；超时返回 None。"""

    def __init__(self, kind: str, device_name: str = ""):
        self.kind = kind
        self.device_name = device_name
        self.q: queue.Queue = queue.Queue(maxsize=500)
        self.sample_rate = 16000
        self.description = ""
        self._closers = []

    def _push(self, a: np.ndarray) -> None:
        try:
            self.q.put_nowait(a)
        except queue.Full:  # 识别跟不上时丢最旧的块，保证实时
            try:
                self.q.get_nowait()
            except queue.Empty:
                pass
            self.q.put_nowait(a)

    def start(self) -> None:
        if self.kind == "system" and IS_WIN:
            self._start_wasapi_loopback()
        else:
            self._start_sounddevice()

    def _start_wasapi_loopback(self) -> None:
        import pyaudiowpatch as pyaudio

        p = pyaudio.PyAudio()
        dev = None
        if self.device_name:
            for d in p.get_loopback_device_info_generator():
                if d["name"] == self.device_name:
                    dev = d
                    break
        if dev is None:
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            speakers = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
            if speakers.get("isLoopbackDevice"):
                dev = speakers
            else:
                for d in p.get_loopback_device_info_generator():
                    if speakers["name"] in d["name"]:
                        dev = d
                        break
        if dev is None:
            p.terminate()
            raise RuntimeError("没有找到可录制的扬声器回环设备")
        channels = int(dev["maxInputChannels"]) or 2
        self.sample_rate = int(dev["defaultSampleRate"])
        self.description = f"系统声音：{dev['name']}"

        def cb(in_data, frame_count, time_info, status):
            self._push(_to_mono_float(in_data, channels, True))
            return (None, pyaudio.paContinue)

        stream = p.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=self.sample_rate,
            frames_per_buffer=int(self.sample_rate * 0.05),
            input=True,
            input_device_index=dev["index"],
            stream_callback=cb,
        )
        stream.start_stream()
        self._closers += [stream.stop_stream, stream.close, p.terminate]

    def _start_sounddevice(self) -> None:
        import sounddevice as sd

        device = None
        if self.device_name:
            device = self.device_name
        elif self.kind == "system":
            # macOS 没有原生回环：优先找 BlackHole 等虚拟声卡
            for d in sd.query_devices():
                if d["max_input_channels"] > 0 and any(k in d["name"] for k in ("BlackHole", "Loopback", "Soundflower")):
                    device = d["name"]
                    break
            if device is None:
                raise RuntimeError("macOS 录系统声音需要先安装 BlackHole 虚拟声卡，并把它设为输出设备的一部分")
        info = sd.query_devices(device, "input")
        self.sample_rate = int(info["default_samplerate"])
        channels = 1
        self.description = f"{'系统声音' if self.kind == 'system' else '麦克风'}：{info['name']}"

        def cb(indata, frames, time_info, status):
            self._push(indata[:, 0].copy())

        stream = sd.InputStream(
            device=device,
            channels=channels,
            samplerate=self.sample_rate,
            dtype="float32",
            blocksize=int(self.sample_rate * 0.05),
            callback=cb,
        )
        stream.start()
        self._closers += [stream.stop, stream.close]

    def read(self, timeout: float = 0.2):
        try:
            return self.q.get(timeout=timeout), self.sample_rate
        except queue.Empty:
            return None

    def stop(self) -> None:
        for fn in self._closers:
            try:
                fn()
            except Exception:
                pass
        self._closers = []
