"""程序入口：托盘图标 + 悬浮字幕窗 + 后台识别翻译流程。"""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .config import Settings
from .pipeline import Callbacks, Pipeline
from .transcript import transcripts_dir
from .ui.overlay import UI_FONT, Bridge, Overlay
from .ui.settings_dialog import SettingsDialog


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#2f6fed"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    f = QFont(UI_FONT)
    f.setPixelSize(38)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(pm.rect(), Qt.AlignCenter, "译")
    p.end()
    return QIcon(pm)


class App:
    def __init__(self):
        self.qt = QApplication(sys.argv)
        self.qt.setQuitOnLastWindowClosed(False)
        self.qt.setApplicationName("实时翻译")
        self.cfg = Settings.load()
        self.icon = make_icon()
        self.qt.setWindowIcon(self.icon)

        self.bridge = Bridge()
        self.overlay = Overlay(self.cfg)
        b, o = self.bridge, self.overlay
        b.partial.connect(o.on_partial)
        b.final.connect(o.on_final)
        b.translation.connect(o.on_translation)
        b.status.connect(o.on_status)
        b.status.connect(lambda m: self.tray.setToolTip(f"实时翻译 · {m}"))
        b.error.connect(self.on_error)
        o.request_settings.connect(self.open_settings)
        o.request_toggle.connect(self.toggle)
        o.request_open_folder.connect(self.open_folder)
        o.request_quit.connect(self.quit)

        self.tray = QSystemTrayIcon(self.icon)
        menu = QMenu()
        menu.addAction("显示 / 隐藏字幕", self.toggle_overlay)
        self.overlay.build_menu(menu)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.toggle_overlay() if r == QSystemTrayIcon.Trigger else None
        )
        self.tray.show()
        self.pipeline: Pipeline | None = None
        self.last_error = ""

    def callbacks(self) -> Callbacks:
        b = self.bridge
        return Callbacks(
            partial=lambda s: b.partial.emit(s.id, s.text),
            final=lambda s: b.final.emit(s.id, s.text),
            translation=lambda e: b.translation.emit(e.seg_id, e.text, e.done, e.error),
            status=b.status.emit,
            error=b.error.emit,
        )

    def start(self) -> None:
        if self.pipeline is None:
            self.overlay.clear()
            self.pipeline = Pipeline(self.cfg, self.callbacks())
            self.pipeline.start()

    def stop(self) -> None:
        if self.pipeline is not None:
            self.pipeline.stop()
            self.pipeline = None

    def toggle(self) -> None:
        if self.pipeline is None:
            self.start()
        else:
            self.stop()
            self.overlay.on_status("已暂停（右键或托盘菜单可继续）")

    def toggle_overlay(self) -> None:
        self.overlay.setVisible(not self.overlay.isVisible())

    def on_error(self, msg: str) -> None:
        self.overlay.on_status(f"出错：{msg}")
        if msg != self.last_error and not msg.startswith("翻译失败"):
            self.tray.showMessage("实时翻译", msg, QSystemTrayIcon.Warning, 5000)
        self.last_error = msg

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg)
        dlg.setWindowIcon(self.icon)
        if dlg.exec():
            dlg.apply()
            self.overlay.apply_settings()
            was_running = self.pipeline is not None
            self.stop()
            if was_running:
                self.start()

    def open_folder(self) -> None:
        path = str(transcripts_dir())
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def quit(self) -> None:
        self.stop()
        self.overlay.remember_geometry()
        self.cfg.save()
        self.tray.hide()
        self.qt.quit()

    def run(self) -> int:
        self.overlay.show()
        if not self.cfg.api_key:
            QMessageBox.information(
                None,
                "实时翻译",
                "欢迎使用！请先填写 DeepSeek API Key（设置 → 翻译）。\n不填也可以使用，只显示识别出的原文。",
            )
            self.open_settings()
        self.start()
        return self.qt.exec()


def main() -> int:
    return App().run()
