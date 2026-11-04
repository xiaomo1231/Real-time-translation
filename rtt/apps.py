"""按程序录音（Windows 11）：用 bin/rtt-capture.exe 录指定程序的声音，多个程序混成一路。"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

from .config import app_dir

RATE = 16000
CHUNK = RATE // 20  # 50ms，与 rtt-capture 输出一致
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def helper_path() -> Path:
    return app_dir() / "bin" / "rtt-capture.exe"


def supported() -> bool:
    """按进程回环需要 Windows 10 build 20348 以上。"""
    if sys.platform != "win32" or not helper_path().exists():
        return False
    return sys.getwindowsversion().build >= 20348


def list_audio_apps() -> list[str]:
    """正在发声（有音频会话）的程序名，用于设置里勾选。"""
    names: set[str] = set()
    try:
        from pycaw.pycaw import AudioUtilities

        for s in AudioUtilities.GetAllSessions():
            if s.Process is not None:
                names.add(s.Process.name())
    except Exception:
        pass
    return sorted(names, key=str.lower)


def find_root_pids(name: str) -> list[int]:
    """找到名为 name 的进程树的根进程（Discord、浏览器等会开很多子进程）。"""
    import psutil

    name_l = name.lower()
    procs = {}
    for p in psutil.process_iter(["pid", "name", "ppid"]):
        if (p.info["name"] or "").lower() == name_l:
            procs[p.info["pid"]] = p.info["ppid"]
    return [pid for pid, ppid in procs.items() if ppid not in procs]


class _Capture:
    def __init__(self, pid: int, mode: str, label: str):
        self.pid, self.label = pid, label
        self.q: queue.Queue = queue.Queue(maxsize=200)
        self.error = ""
        self.proc = subprocess.Popen(
            [str(helper_path()), str(pid), mode],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=NO_WINDOW,
        )
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def _read(self) -> None:
        nbytes = CHUNK * 4
        while True:
            b = self.proc.stdout.read(nbytes)
            if not b or len(b) < nbytes:
                return
            if self.q.full():
                try:
                    self.q.get_nowait()
                except queue.Empty:
                    pass
            self.q.put(np.frombuffer(b, dtype="<f4").copy())

    def _read_err(self) -> None:
        for line in self.proc.stderr:
            text = line.decode("utf-8", "replace").strip()
            if text.startswith("error"):
                self.error = text[5:].strip()

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self) -> None:
        try:
            self.proc.kill()
        except Exception:
            pass


class AppAudioSource:
    """接口与 audio.AudioSource 相同：start() / read() / stop()。

    names 为空时录「除本程序以外的全部声音」（这样自己念出的英文不会被再识别）。
    程序没开时每 3 秒重新找一次，游戏后启动也能接上。
    """

    def __init__(self, names: list[str]):
        self.names = [n for n in names if n.strip()]
        self.sample_rate = RATE
        self.description = ""
        self.caps: dict[int, _Capture] = {}
        self.out: queue.Queue = queue.Queue(maxsize=200)
        self._stop = threading.Event()
        self.last_error = ""

    def start(self) -> None:
        if not supported():
            raise RuntimeError("按程序录音需要 Windows 11（或 Windows 10 build 20348 以上）和 bin/rtt-capture.exe")
        self._scan()
        if self.names:
            self.description = "程序声音：" + "、".join(self.names)
        else:
            self.description = "除本程序外的全部声音"
        threading.Thread(target=self._mix, name="app-mixer", daemon=True).start()

    def _scan(self) -> None:
        if not self.names:
            if not self.caps:
                self.caps[os.getpid()] = _Capture(os.getpid(), "exclude", "全部")
            return
        for name in self.names:
            for pid in find_root_pids(name):
                if pid not in self.caps:
                    self.caps[pid] = _Capture(pid, "include", name)

    def _mix(self) -> None:
        tick = CHUNK / RATE
        next_t = time.monotonic()
        last_scan = time.monotonic()
        while not self._stop.is_set():
            next_t += tick
            delay = next_t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.monotonic()
            mixed = np.zeros(CHUNK, np.float32)
            for pid, cap in list(self.caps.items()):
                if not cap.alive:
                    if cap.error:
                        self.last_error = f"{cap.label}：{cap.error}"
                    del self.caps[pid]
                    continue
                # 积压太多时丢掉旧数据，保证实时
                while cap.q.qsize() > 6:
                    cap.q.get_nowait()
                try:
                    mixed += cap.q.get_nowait()
                except queue.Empty:
                    pass
            if time.monotonic() - last_scan > 3:
                last_scan = time.monotonic()
                try:
                    self._scan()
                except Exception:
                    pass
            np.clip(mixed, -1.0, 1.0, out=mixed)
            try:
                self.out.put_nowait(mixed)
            except queue.Full:
                pass

    def read(self, timeout: float = 0.2):
        try:
            return self.out.get(timeout=timeout), RATE
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._stop.set()
        for cap in self.caps.values():
            cap.stop()
        self.caps.clear()
