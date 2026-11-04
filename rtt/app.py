"""程序入口：托盘图标 + 悬浮窗 + 听 / 说 / 聊天框三条后台流程。"""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .config import Settings
from .pipeline import Callbacks, Pipeline
from .scenes import SCENES, apply_scene
from .speak import SpeakCallbacks, SpeakPipeline
from .transcript import transcripts_dir
from .translate import Translator
from .ui.overlay import UI_FONT, Bridge, ChatOverlay, Overlay
from .ui.settings_dialog import SettingsDialog
from .ui.tools import RegionSelector, TypeBox


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
        self.chat_bridge = Bridge()
        self.overlay = Overlay(self.cfg)
        self.chat_overlay = ChatOverlay(self.cfg)
        b, o = self.bridge, self.overlay
        b.partial.connect(o.on_partial)
        b.final.connect(o.on_final)
        b.translation.connect(o.on_translation)
        b.status.connect(o.on_status)
        b.status.connect(lambda m: self.tray.setToolTip(f"实时翻译 · {m}"))
        b.error.connect(self.on_error)
        b.talking.connect(o.on_talking)
        b.combo.connect(self.open_typebox)
        cb = self.chat_bridge
        cb.final.connect(self.chat_overlay.on_message)
        cb.translation.connect(self.chat_overlay.on_translation)
        cb.error.connect(self.on_error)
        o.request_settings.connect(self.open_settings)
        o.request_toggle.connect(self.toggle)
        o.request_open_folder.connect(self.open_folder)
        o.request_quit.connect(self.quit)

        self.tray = QSystemTrayIcon(self.icon)
        self.tray.setContextMenu(self.build_tray_menu())
        self.tray.activated.connect(lambda r: self.toggle_overlay() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

        self.pipeline: Pipeline | None = None
        self.speak: SpeakPipeline | None = None
        self.chat = None
        self.hotkeys = None
        self.typebox: TypeBox | None = None
        self.selector: RegionSelector | None = None
        self.last_error = ""

    # ---- 菜单 ----
    def build_tray_menu(self) -> QMenu:
        menu = QMenu()
        menu.addAction("显示 / 隐藏字幕", self.toggle_overlay)
        scenes = menu.addMenu("场景")
        group = QActionGroup(scenes)
        self.scene_actions = {}
        for key, label in SCENES.items():
            act = QAction(label, scenes, checkable=True)
            act.setChecked(key == self.cfg.scene)
            act.triggered.connect(lambda _=False, k=key: self.switch_scene(k))
            group.addAction(act)
            scenes.addAction(act)
            self.scene_actions[key] = act
        menu.addAction("框选聊天区域…", self.select_region)
        menu.addAction("打字翻译…", self.open_typebox)
        menu.addSeparator()
        self.overlay.build_menu(menu)
        return menu

    # ---- 后台流程 ----
    def start(self) -> None:
        if self.pipeline is not None:
            return
        self.overlay.clear()
        b = self.bridge
        self.pipeline = Pipeline(
            self.cfg,
            Callbacks(
                partial=lambda s: b.partial.emit(f"L{s.id}", s.text),
                final=lambda s: b.final.emit(f"L{s.id}", s.text),
                translation=lambda e: b.translation.emit(f"L{e.seg_id}", e.text, e.done, e.error),
                status=b.status.emit,
                error=b.error.emit,
            ),
        )
        self.pipeline.start()
        if self.cfg.speak_enabled:
            self.speak = SpeakPipeline(
                self.cfg,
                SpeakCallbacks(
                    partial=lambda s: b.partial.emit(f"S{s.id}", s.text),
                    final=lambda s: b.final.emit(f"S{s.id}", s.text),
                    translation=lambda e: b.translation.emit(f"S{e.seg_id}", e.text, e.done, e.error),
                    talking=b.talking.emit,
                    status=b.status.emit,
                    error=b.error.emit,
                ),
            )
            self.speak.start()
        if self.cfg.ocr_enabled and self.cfg.ocr_region:
            from .chat import ChatWatcher

            c = self.chat_bridge
            self.chat = ChatWatcher(
                self.cfg,
                on_message=lambda i, t: c.final.emit(f"C{i}", t),
                on_translation=lambda e: c.translation.emit(f"C{e.seg_id}", e.text, e.done, e.error),
                on_error=c.error.emit,
            )
            self.chat.start()
            self.chat_overlay.place_near(self.cfg.ocr_region, self.qt.primaryScreen().devicePixelRatio())
            self.chat_overlay.show()
        else:
            self.chat_overlay.hide()
        self.start_hotkeys()

    def start_hotkeys(self) -> None:
        try:
            from .hotkeys import Hotkeys

            ptt = self.cfg.ptt_key if (self.speak and self.cfg.speak_mode == "ptt") else None
            self.hotkeys = Hotkeys(ptt, lambda down: self.speak and self.speak.ptt(down), self.cfg.type_hotkey or None, self.bridge.combo.emit)
            self.hotkeys.start()
        except Exception as e:
            self.on_error(f"快捷键不可用：{e}")

    def stop(self) -> None:
        if self.hotkeys:
            self.hotkeys.stop()
            self.hotkeys = None
        for attr in ("pipeline", "speak", "chat"):
            obj = getattr(self, attr)
            if obj is not None:
                obj.stop()
                setattr(self, attr, None)

    def restart(self) -> None:
        was_running = self.pipeline is not None
        self.stop()
        if was_running:
            self.start()

    def toggle(self) -> None:
        if self.pipeline is None:
            self.start()
        else:
            self.stop()
            self.overlay.on_status("已暂停（右键或托盘菜单可继续）")

    def switch_scene(self, scene: str) -> None:
        apply_scene(self.cfg, scene)
        self.cfg.save()
        self.overlay.on_status(f"已切换到「{SCENES[scene]}」场景")
        self.restart()

    # ---- 界面 ----
    def toggle_overlay(self) -> None:
        self.overlay.setVisible(not self.overlay.isVisible())

    def on_error(self, msg: str) -> None:
        self.overlay.on_status(f"出错：{msg}")
        if msg != self.last_error and not msg.startswith("翻译失败"):
            self.tray.showMessage("实时翻译", msg, QSystemTrayIcon.Warning, 5000)
        self.last_error = msg

    def select_region(self) -> None:
        self.selector = RegionSelector()
        self.selector.selected.connect(self.on_region)
        self.selector.show()
        self.selector.activateWindow()

    def on_region(self, region: list) -> None:
        self.cfg.ocr_region = region
        self.cfg.ocr_enabled = True
        self.cfg.save()
        self.overlay.on_status("已设置聊天区域，开始识别聊天消息")
        self.restart() if self.pipeline else self.start()

    def open_typebox(self) -> None:
        if self.typebox is None:
            tr = Translator(self.cfg, lambda e: None, target=self.cfg.speak_target, spoken=True)
            speak = (lambda text: self.speak and self.speak.say_text(text)) if self.cfg.speak_enabled else None
            self.typebox = TypeBox(tr.translate_now, speak, self.cfg)
            self.typebox.setWindowIcon(self.icon)
        self.typebox.popup()

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg)
        dlg.setWindowIcon(self.icon)
        if dlg.exec():
            dlg.apply()
            for k, act in self.scene_actions.items():
                act.setChecked(k == self.cfg.scene)
            self.overlay.apply_settings()
            self.typebox = None  # 设置可能改了 API Key 或目标语言
            self.restart()

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
