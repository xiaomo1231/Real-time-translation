"""悬浮字幕窗：置顶、半透明、可拖动、可缩放。"""

from __future__ import annotations

import html
import sys
from collections import OrderedDict

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QLabel, QMenu, QSizeGrip, QVBoxLayout, QWidget

from ..config import Settings

UI_FONT = "Microsoft YaHei UI" if sys.platform == "win32" else "PingFang SC"


class Bridge(QObject):
    """后台线程 → 界面线程的信号桥。"""

    partial = Signal(int, str)
    final = Signal(int, str)
    translation = Signal(int, str, bool, str)
    status = Signal(str)
    error = Signal(str)


class Overlay(QWidget):
    request_settings = Signal()
    request_toggle = Signal()
    request_open_folder = Signal()
    request_quit = Signal()

    def __init__(self, cfg: Settings):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.cfg = cfg
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("实时翻译")
        self.rows: OrderedDict[int, dict] = OrderedDict()
        self.partial_id = -1
        self.partial_text = ""
        self.status_text = ""
        self._drag: QPoint | None = None

        self.status_label = QLabel(self)
        self.text_label = QLabel(self)
        self.text_label.setWordWrap(True)
        self.text_label.setTextFormat(Qt.RichText)
        self.text_label.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 10, 18, 14)
        lay.setSpacing(4)
        lay.addWidget(self.status_label)
        lay.addWidget(self.text_label, 1)
        grip = QSizeGrip(self)
        grip.setStyleSheet("background: transparent;")
        lay.addWidget(grip, 0, Qt.AlignBottom | Qt.AlignRight)

        self._status_timer = QTimer(self, singleShot=True, timeout=lambda: self.status_label.hide())
        self.apply_settings()
        g = cfg.window_geometry
        if len(g) == 4:
            self.setGeometry(QRect(*g))
        else:
            scr = self.screen().availableGeometry()
            w, h = int(scr.width() * 0.6), 170
            self.setGeometry(scr.x() + (scr.width() - w) // 2, scr.y() + scr.height() - h - 60, w, h)
        self.setMinimumSize(320, 90)

    # ---- 外观 ----
    def apply_settings(self) -> None:
        f = QFont(UI_FONT)
        f.setPixelSize(12)
        self.status_label.setFont(f)
        self.status_label.setStyleSheet("color: rgba(255,255,255,150);")
        self.render_text()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(18, 18, 22, int(255 * max(0.05, min(1.0, self.cfg.opacity)))))
        p.drawRoundedRect(self.rect(), 14, 14)

    # ---- 内容 ----
    def on_partial(self, seg_id: int, text: str) -> None:
        self.partial_id, self.partial_text = seg_id, text
        self.render_text()

    def on_final(self, seg_id: int, text: str) -> None:
        self.rows[seg_id] = {"src": text, "dst": "", "err": ""}
        while len(self.rows) > 20:
            self.rows.popitem(last=False)
        if self.partial_id == seg_id:
            self.partial_text = ""
        self.render_text()

    def on_translation(self, seg_id: int, text: str, done: bool, error: str) -> None:
        row = self.rows.get(seg_id)
        if row is None:
            return
        row["dst"] = text
        row["err"] = error
        self.render_text()

    def on_status(self, text: str) -> None:
        self.status_text = text
        self.status_label.setText(text)
        self.status_label.show()
        if text.startswith("正在收听"):
            self._status_timer.start(4000)
        else:
            self._status_timer.stop()

    def render_text(self) -> None:
        size = self.cfg.font_size
        small = max(12, int(size * 0.68))
        mode = self.cfg.display_mode
        parts = []

        def block(src: str, dst: str, live: bool, err: str = "") -> str:
            src_e, dst_e = html.escape(src), html.escape(dst)
            src_style = f"color:rgba(255,255,255,{150 if live else 175});font-size:{small}px;"
            dst_style = f"color:#ffffff;font-size:{size}px;font-weight:600;"
            if mode == "source":
                return f'<div style="color:#fff;font-size:{size}px;font-weight:600;">{src_e}</div>'
            out = ""
            if mode == "both" or not dst:
                style = src_style if mode == "both" else f"color:rgba(255,255,255,160);font-size:{size}px;"
                out += f'<div style="{style}">{src_e}</div>'
            if dst:
                out += f'<div style="{dst_style}">{dst_e}</div>'
            elif err and not live:
                out += f'<div style="color:#ff9b8a;font-size:{small}px;">{html.escape(err)}</div>'
            return out

        rows = list(self.rows.values())[-self.cfg.max_lines :]
        for r in rows:
            parts.append(block(r["src"], r["dst"], False, r["err"]))
        if self.partial_text:
            parts.append(block(self.partial_text, "", True))
            if len(parts) > self.cfg.max_lines:
                parts = parts[-self.cfg.max_lines :]
        sep = '<div style="font-size:6px;">&nbsp;</div>'
        self.text_label.setText(f'<div style="font-family:\'{UI_FONT}\';">' + sep.join(parts) + "</div>")

    def clear(self) -> None:
        self.rows.clear()
        self.partial_text = ""
        self.render_text()

    # ---- 交互 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.remember_geometry()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.remember_geometry()

    def remember_geometry(self) -> None:
        g = self.geometry()
        self.cfg.window_geometry = [g.x(), g.y(), g.width(), g.height()]

    def contextMenuEvent(self, e):
        self.build_menu(QMenu(self)).exec(e.globalPos())

    def build_menu(self, m: QMenu, running: bool | None = None) -> QMenu:
        m.addAction("暂停 / 继续", self.request_toggle.emit)
        m.addAction("设置…", self.request_settings.emit)
        m.addAction("打开记录文件夹", self.request_open_folder.emit)
        m.addAction("清空字幕", self.clear)
        m.addSeparator()
        m.addAction("退出", self.request_quit.emit)
        return m
