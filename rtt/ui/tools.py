"""框选屏幕区域、打字翻译框。"""

from __future__ import annotations

import threading

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from .overlay import UI_FONT


class RegionSelector(QWidget):
    """覆盖整个屏幕的半透明遮罩，拖出一个矩形。selected 发出物理像素坐标 [x, y, w, h]。"""

    selected = Signal(list)

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        screen = QGuiApplication.primaryScreen()
        self.dpr = screen.devicePixelRatio()
        self.setGeometry(screen.geometry())
        self.a: QPoint | None = None
        self.b: QPoint | None = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        p.setPen(QColor(255, 255, 255))
        f = p.font()
        f.setFamily(UI_FONT)
        f.setPixelSize(18)
        p.setFont(f)
        p.drawText(self.rect().adjusted(0, 40, 0, 0), Qt.AlignHCenter | Qt.AlignTop, "拖动框选游戏的聊天区域，按 Esc 取消")
        if self.a and self.b:
            r = QRect(self.a, self.b).normalized()
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(r, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QPen(QColor("#2f6fed"), 2))
            p.drawRect(r)

    def mousePressEvent(self, e):
        self.a = self.b = e.position().toPoint()
        self.update()

    def mouseMoveEvent(self, e):
        self.b = e.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, e):
        self.b = e.position().toPoint()
        r = QRect(self.a, self.b).normalized()
        self.close()
        if r.width() > 20 and r.height() > 20:
            g = self.geometry()
            d = self.dpr
            self.selected.emit([int((g.x() + r.x()) * d), int((g.y() + r.y()) * d), int(r.width() * d), int(r.height() * d)])

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()


class TypeBox(QWidget):
    """打字翻译框：输入中文回车 → 英文复制到剪贴板（可选同时念到虚拟麦克风）。"""

    done = Signal(str, str)  # (译文, 错误)

    def __init__(self, translate, speak, cfg):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.translate = translate  # 同步函数：中文 → 英文
        self.speak = speak  # 函数：念出英文；None 表示说话转译没开
        self.cfg = cfg
        self.setStyleSheet(
            "QWidget{background:#1d1f24;color:#fff;font-family:'%s';}"
            "QLineEdit{font-size:18px;padding:8px;border:1px solid #3a3f4a;border-radius:8px;background:#121418;}"
            "QLabel{font-size:14px;color:#cfd6e4;}" % UI_FONT
        )
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("输入中文，回车翻译成英文并复制（Esc 关闭）")
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.read = QCheckBox("同时念到虚拟麦克风")
        self.read.setChecked(cfg.type_speak)
        self.read.setEnabled(speak is not None)
        row = QHBoxLayout()
        row.addWidget(self.read)
        row.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.addWidget(self.edit)
        lay.addWidget(self.result)
        lay.addLayout(row)
        self.edit.returnPressed.connect(self.submit)
        self.done.connect(self.show_result)
        self.resize(560, 140)

    def popup(self) -> None:
        scr = QGuiApplication.primaryScreen().availableGeometry()
        self.move(scr.x() + (scr.width() - self.width()) // 2, scr.y() + int(scr.height() * 0.3))
        self.result.setText("")
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()
        self.edit.selectAll()

    def submit(self) -> None:
        text = self.edit.text().strip()
        if not text:
            return
        self.result.setText("翻译中…")

        def work():
            try:
                self.done.emit(self.translate(text), "")
            except Exception as e:
                self.done.emit("", str(e))

        threading.Thread(target=work, daemon=True).start()

    def show_result(self, text: str, err: str) -> None:
        if err:
            self.result.setText(f"翻译失败：{err}")
            return
        QGuiApplication.clipboard().setText(text)
        self.cfg.type_speak = self.read.isChecked()
        if self.read.isChecked() and self.speak:
            self.speak(text)
        self.result.setText(f"{text}\n（已复制，切回游戏 Ctrl+V 粘贴）")
        self.edit.clear()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)
