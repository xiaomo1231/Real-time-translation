"""本地识别模型：清单、硬件分档与按需下载。"""

from __future__ import annotations

import os
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import data_dir

HF = "https://huggingface.co/csukuangfj/{repo}/resolve/main/{file}"
GH = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{repo}.tar.bz2"


@dataclass(frozen=True)
class ModelSpec:
    key: str
    repo: str
    files: tuple[str, ...]
    size_mb: int
    title: str


MODELS = {
    "paraformer": ModelSpec(
        "paraformer",
        "sherpa-onnx-streaming-paraformer-bilingual-zh-en",
        ("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt"),
        227,
        "流式 Paraformer 中英双语",
    ),
    "zipformer": ModelSpec(
        "zipformer",
        "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20",
        (
            "encoder-epoch-99-avg-1.int8.onnx",
            "decoder-epoch-99-avg-1.int8.onnx",
            "joiner-epoch-99-avg-1.int8.onnx",
            "tokens.txt",
        ),
        189,
        "流式 Zipformer 中英双语（轻量）",
    ),
    "sensevoice": ModelSpec(
        "sensevoice",
        "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
        ("model.int8.onnx", "tokens.txt"),
        229,
        "SenseVoice 定稿模型",
    ),
}


def models_dir() -> Path:
    d = data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def model_path(key: str) -> Path:
    return models_dir() / MODELS[key].repo


def is_ready(key: str) -> bool:
    p = model_path(key)
    return all((p / f).exists() for f in MODELS[key].files)


def resolve_tier(tier: str) -> str:
    """auto 时按 CPU 核数选择：8 核及以上用 high，否则 low。"""
    if tier in ("high", "low"):
        return tier
    return "high" if (os.cpu_count() or 4) >= 8 else "low"


def required_models(tier: str, second_pass: bool) -> list[str]:
    tier = resolve_tier(tier)
    keys = ["paraformer" if tier == "high" else "zipformer"]
    if second_pass:
        keys.append("sensevoice")
    return keys


def default_threads(tier: str) -> int:
    cores = os.cpu_count() or 4
    return max(1, min(4, cores // 2)) if resolve_tier(tier) == "high" else max(1, min(2, cores // 2))


Progress = Callable[[str, int, int], None]  # (说明, 已下载字节, 总字节)


def _download(url: str, dest: Path, label: str, progress: Progress | None) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "rtt/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(label, done, total)
    tmp.replace(dest)


def ensure_model(key: str, progress: Progress | None = None) -> Path:
    """确保模型已下载。先逐个文件从 Hugging Face 下载，失败则下载 GitHub 整包并只解压需要的文件。"""
    spec = MODELS[key]
    target = model_path(key)
    if is_ready(key):
        return target
    target.mkdir(parents=True, exist_ok=True)
    try:
        for name in spec.files:
            dest = target / name
            if not dest.exists():
                _download(HF.format(repo=spec.repo, file=name), dest, f"{spec.title}：{name}", progress)
    except Exception:
        _download_tarball(spec, target, progress)
    if not is_ready(key):
        raise RuntimeError(f"模型下载不完整：{spec.title}")
    return target


def _download_tarball(spec: ModelSpec, target: Path, progress: Progress | None) -> None:
    url = GH.format(repo=spec.repo)
    req = urllib.request.Request(url, headers={"User-Agent": "rtt/0.1"})
    wanted = {f"{spec.repo}/{f}": f for f in spec.files}
    with urllib.request.urlopen(req, timeout=30) as r:
        total = int(r.headers.get("Content-Length") or 0)

        class Counter:
            def __init__(self, raw):
                self.raw, self.done = raw, 0

            def read(self, n=-1):
                b = self.raw.read(n)
                self.done += len(b)
                if progress:
                    progress(f"{spec.title}（整包）", self.done, total)
                return b

        with tarfile.open(fileobj=Counter(r), mode="r|bz2") as tar:
            for member in tar:
                name = wanted.get(member.name)
                if name and member.isfile():
                    src = tar.extractfile(member)
                    with open(target / name, "wb") as out:
                        while chunk := src.read(1 << 20):
                            out.write(chunk)
