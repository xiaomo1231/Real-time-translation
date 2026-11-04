"""悬浮窗：字幕条（听 + 说）和聊天框译文窗。置顶、半透明、可拖动、可缩放。"""

from __future__ import annotations

import html
import sys
from collections import OrderedDict

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QLabel, QMenu, QSizeGrip, QVBoxLayout, QWidget

from ..config import Settings

UI_FONT = "Microsoft YaHei UI" if sys.platform == "win32" else "PingFang SC"
SPEAK_COLOR = "#8fc7ff"


class Bridge(QObject):
    """后台线程 → 界面线程的信号桥。key 形如 L3（听到的第 3 句）、S2（自己说的第 2 句）、C5（聊天消息）。"""

    partial = Signal(str, str)
    final = Signal(str, str)
    translation = Signal(str, str, bool, str)
    status = Signal(str)
    error = Signal(str)
    talking = Signal(bool)
    combo = Signal()


class _Floating(QWidget):
    """可拖动、可缩放、半透明圆角的置顶窗口。"""

    moved = Signal()

    def __init__(self, cfg: Settings):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.cfg = cfg
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag: QPoint | None = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(18, 18, 22, int(255 * max(0.05, min(1.0, self.cfg.opacity)))))
        p.drawRoundedRect(self.rect(), 14, 14)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.moved.emit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.moved.emit()


class Overlay(_Floating):
    request_settings = Signal()
    request_toggle = Signal()
    request_open_folder = Signal()
    request_quit = Signal()

    def __init__(self, cfg: Settings):
        super().__init__(cfg)
        self.setWindowTitle("实时翻译")
        self.rows: OrderedDict[str, dict] = OrderedDict()
        self.partials: dict[str, str] = {}
        self.talking = False

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
        self.moved.connect(self.remember_geometry)

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

    def apply_settings(self) -> None:
        f = QFont(UI_FONT)
        f.setPixelSize(12)
        self.status_label.setFont(f)
        self.status_label.setStyleSheet("color: rgba(255,255,255,150);")
        self.render_text()
        self.update()

    # ---- 内容 ----
    def on_partial(self, key: str, text: str) -> None:
        self.partials[key[0]] = text
        self.render_text()

    def on_final(self, key: str, text: str) -> None:
        self.rows[key] = {"src": text, "dst": "", "err": ""}
        while len(self.rows) > 30:
            self.rows.popitem(last=False)
        self.partials.pop(key[0], None)
        self.render_text()

    def on_translation(self, key: str, text: str, done: bool, error: str) -> None:
        row = self.rows.get(key)
        if row is None:
            return
        row["dst"] = text
        row["err"] = error
        self.render_text()

    def on_talking(self, down: bool) -> None:
        self.talking = down
        self.render_text()

    def on_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.show()
        if text.startswith(("正在收听", "说话转译已就绪")):
            self._status_timer.start(5000)
        else:
            self._status_timer.stop()

    def render_text(self) -> None:
        size = self.cfg.font_size
        small = max(12, int(size * 0.68))
        mode = self.cfg.display_mode

        def block(src: str, dst: str, live: bool, err: str, mine: bool) -> str:
            src_e, dst_e = html.escape(src), html.escape(dst)
            if mine:
                # 自己说的话：中文小字 + 发出去的英文
                out = f'<div style="color:{SPEAK_COLOR};font-size:{small}px;">我：{src_e}</div>'
                if dst:
                    out += f'<div style="color:{SPEAK_COLOR};font-size:{size}px;font-weight:600;">→ {dst_e}</div>'
                elif err and not live:
                    out += f'<div style="color:#ff9b8a;font-size:{small}px;">{html.escape(err)}</div>'
                return out
            if mode == "source":
                return f'<div style="color:#fff;font-size:{size}px;font-weight:600;">{src_e}</div>'
            out = ""
            if mode == "both" or not dst:
                style = f"color:rgba(255,255,255,{150 if live else 175});font-size:{small}px;" if mode == "both" else f"color:rgba(255,255,255,160);font-size:{size}px;"
                out += f'<div style="{style}">{src_e}</div>'
            if dst:
                out += f'<div style="color:#ffffff;font-size:{size}px;font-weight:600;">{dst_e}</div>'
            elif err and not live:
                out += f'<div style="color:#ff9b8a;font-size:{small}px;">{html.escape(err)}</div>'
            return out

        parts = []
        for key, r in list(self.rows.items())[-self.cfg.max_lines - 1 :]:
            parts.append(block(r["src"], r["dst"], False, r["err"], key.startswith("S")))
        if self.partials.get("L"):
            parts.append(block(self.partials["L"], "", True, "", False))
        if self.partials.get("S"):
            parts.append(block(self.partials["S"], "", True, "", True))
        parts = parts[-max(1, self.cfg.max_lines) :]
        if self.talking:
            parts.append(f'<div style="color:{SPEAK_COLOR};font-size:{small}px;">● 正在听你说…</div>')
        sep = '<div style="font-size:6px;">&nbsp;</div>'
        self.text_label.setText(f'<div style="font-family:\'{UI_FONT}\';">' + sep.join(parts) + "</div>")

    def clear(self) -> None:
        self.rows.clear()
        self.partials.clear()
        self.render_text()

    def remember_geometry(self) -> None:
        g = self.geometry()
        self.cfg.window_geometry = [g.x(), g.y(), g.width(), g.height()]

    def contextMenuEvent(self, e):
        self.build_menu(QMenu(self)).exec(e.globalPos())

    def build_menu(self, m: QMenu) -> QMenu:
        m.addAction("暂停 / 继续", self.request_toggle.emit)
        m.addAction("设置…", self.request_settings.emit)
        m.addAction("打开记录文件夹", self.request_open_folder.emit)
        m.addAction("清空字幕", self.clear)
        m.addSeparator()
        m.addAction("退出", self.request_quit.emit)
        return m


class ChatOverlay(_Floating):
    """聊天框译文窗：显示最近几条外文聊天消息的中文译文。"""

    def __init__(self, cfg: Settings):
        super().__init__(cfg)
        self.setWindowTitle("聊天翻译")
        self.rows: OrderedDict[str, dict] = OrderedDict()
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.RichText)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.addWidget(self.label, 1)
        grip = QSizeGrip(self)
        grip.setStyleSheet("background: transparent;")
        lay.addWidget(grip, 0, Qt.AlignBottom | Qt.AlignRight)
        self.setMinimumSize(220, 80)
        self.render()

    def place_near(self, region: list[int], dpr: float) -> None:
        x, y, w, h = (int(v / dpr) for v in region)
        scr = self.screen().availableGeometry()
        width = max(260, min(420, w))
        left = x + w + 8 if x + w + 8 + width < scr.right() else max(scr.left(), x - width - 8)
        self.setGeometry(left, y, width, max(120, h))

    def on_message(self, key: str, text: str) -> None:
        self.rows[key] = {"src": text, "dst": ""}
        while len(self.rows) > 8:
            self.rows.popitem(last=False)
        self.render()

    def on_translation(self, key: str, text: str, done: bool, error: str) -> None:
        if key in self.rows:
            self.rows[key]["dst"] = text or (error if done else "")
            self.render()

    def render(self) -> None:
        size = max(13, int(self.cfg.font_size * 0.7))
        parts = []
        for r in list(self.rows.values())[-6:]:
            parts.append(
                f'<div style="color:rgba(255,255,255,140);font-size:{size - 2}px;">{html.escape(r["src"])}</div>'
                f'<div style="color:#fff;font-size:{size}px;">{html.escape(r["dst"]) or "…"}</div>'
            )
        if not parts:
            parts.append(f'<div style="color:rgba(255,255,255,140);font-size:{size}px;">聊天框里有新外文消息时，译文会显示在这里</div>')
        self.label.setText(f'<div style="font-family:\'{UI_FONT}\';">' + "<br/>".join(parts) + "</div>")
