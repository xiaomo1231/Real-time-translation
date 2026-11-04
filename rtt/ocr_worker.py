"""聊天框文字识别子进程：定时截取屏幕区域，画面变化时做 OCR，每次输出一行 JSON。

单独开进程是为了避免 RapidOCR 的 onnxruntime 和 sherpa-onnx 自带的版本冲突。
用法：python -m rtt.ocr_worker <x> <y> <w> <h> <间隔秒>
"""

from __future__ import annotations

import json
import sys
import time

import numpy as np


def main() -> int:
    x, y, w, h = (int(v) for v in sys.argv[1:5])
    interval = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
    import mss
    from rapidocr_onnxruntime import RapidOCR

    ocr = RapidOCR()
    prev = None
    print(json.dumps({"ready": True}), flush=True)
    with mss.mss() as sct:
        while True:
            t0 = time.monotonic()
            shot = np.asarray(sct.grab({"left": x, "top": y, "width": w, "height": h}))[:, :, :3]
            small = shot[::4, ::4].astype(np.int16)
            if prev is None or np.abs(small - prev).mean() > 1.5:
                prev = small
                result, _ = ocr(np.ascontiguousarray(shot))  # mss 截图去掉 alpha 后就是 BGR
                lines = []
                for box, text, score in result or []:
                    if float(score) >= 0.6 and text.strip():
                        lines.append({"y": float(min(p[1] for p in box)), "x": float(min(p[0] for p in box)), "text": text.strip()})
                lines.sort(key=lambda d: (round(d["y"] / 8), d["x"]))
                print(json.dumps({"lines": [d["text"] for d in _merge_rows(lines)]}, ensure_ascii=False), flush=True)
            time.sleep(max(0.05, interval - (time.monotonic() - t0)))


def _merge_rows(items: list[dict]) -> list[dict]:
    """同一行被切成几段时合并起来。"""
    rows: list[dict] = []
    for it in items:
        if rows and abs(rows[-1]["y"] - it["y"]) < 8:
            rows[-1]["text"] += " " + it["text"]
        else:
            rows.append(dict(it))
    return rows


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BrokenPipeError, KeyboardInterrupt):
        sys.exit(0)
