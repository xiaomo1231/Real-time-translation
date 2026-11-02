"""文字记录：边识别边写 TXT，并同步生成 SRT 字幕文件。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .config import data_dir


def transcripts_dir() -> Path:
    d = data_dir() / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class Transcript:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.txt_path = transcripts_dir() / f"{stamp}.txt"
        self.srt_path = transcripts_dir() / f"{stamp}.srt"
        self.items: dict[int, dict] = {}

    def set_source(self, seg_id: int, text: str, start: float, end: float) -> None:
        self.items[seg_id] = {"src": text, "dst": "", "start": start, "end": end}

    def set_translation(self, seg_id: int, text: str) -> None:
        if seg_id in self.items:
            self.items[seg_id]["dst"] = text
            self._append_txt(seg_id)
            self._write_srt()

    def _append_txt(self, seg_id: int) -> None:
        if not self.enabled:
            return
        it = self.items[seg_id]
        if it.get("written"):
            return
        it["written"] = True
        ts = _srt_time(it["start"]).split(",")[0]
        with open(self.txt_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {it['src']}\n")
            if it["dst"]:
                f.write(f"           {it['dst']}\n")

    def _write_srt(self) -> None:
        if not self.enabled:
            return
        lines = []
        for n, (_, it) in enumerate(sorted(self.items.items()), 1):
            lines += [str(n), f"{_srt_time(it['start'])} --> {_srt_time(max(it['end'], it['start'] + 0.5))}", it["src"]]
            if it["dst"]:
                lines.append(it["dst"])
            lines.append("")
        self.srt_path.write_text("\n".join(lines), encoding="utf-8")

    def flush_untranslated(self) -> None:
        """还没拿到译文的分句也写进记录（会话结束时调用）。"""
        for seg_id, it in sorted(self.items.items()):
            self._append_txt(seg_id)
        self._write_srt()
