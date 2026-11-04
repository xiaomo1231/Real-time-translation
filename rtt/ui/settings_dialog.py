"""设置窗口。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from .. import apps, audio, models
from ..config import Settings
from ..scenes import SCENES, apply_scene
from ..translate import LANG_NAMES


def _combo(items: list[tuple[str, str]], current: str) -> QComboBox:
    c = QComboBox()
    for label, value in items:
        c.addItem(label, value)
    i = c.findData(current)
    c.setCurrentIndex(max(0, i))
    return c


class SettingsDialog(QDialog):
    def __init__(self, cfg: Settings, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("实时翻译 · 设置")
        self.setMinimumWidth(520)
        tabs = QTabWidget()

        # 翻译
        t = QWidget()
        f = QFormLayout(t)
        self.api_key = QLineEdit(cfg.api_key)
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("sk-…（在 platform.deepseek.com 创建）")
        self.base_url = QLineEdit(cfg.base_url)
        self.model = QLineEdit(cfg.model)
        self.backup_key = QLineEdit(cfg.backup_api_key)
        self.backup_key.setEchoMode(QLineEdit.Password)
        self.backup_url = QLineEdit(cfg.backup_base_url)
        self.backup_url.setPlaceholderText("可选，例如 https://api.openai.com/v1")
        self.backup_model = QLineEdit(cfg.backup_model)
        self.backup_model.setPlaceholderText("可选，例如 gpt-4.1-mini")
        self.timeout = QDoubleSpinBox(minimum=2, maximum=30, value=cfg.translate_timeout, suffix=" 秒")
        self.context = QSpinBox(minimum=0, maximum=10, value=cfg.context_pairs)
        f.addRow("DeepSeek API Key", self.api_key)
        f.addRow("接口地址", self.base_url)
        f.addRow("模型", self.model)
        f.addRow(QLabel("<b>备用接口</b>（DeepSeek 超时或出错时自动切换）"))
        f.addRow("备用 API Key", self.backup_key)
        f.addRow("备用接口地址", self.backup_url)
        f.addRow("备用模型", self.backup_model)
        f.addRow("超时", self.timeout)
        f.addRow("参考上文句数", self.context)
        tabs.addTab(t, "翻译")

        # 场景
        t = QWidget()
        f = QFormLayout(t)
        self.scene = _combo([(v, k) for k, v in SCENES.items()], cfg.scene)
        f.addRow("当前场景", self.scene)
        f.addRow(QLabel(
            "切换场景会自动调整下面几页的开关：\n"
            "· 会议：录全部系统声音，只显示字幕\n"
            "· 游戏：只录勾选的程序（Windows 11），按键说中文发英文语音，可识别聊天框\n"
            "· 跨语言通话：只录通话软件，按键说话\n"
            "· 面对面：用麦克风听双方，把中文译成英文从音箱念出来"
        ))
        self.scene.currentIndexChanged.connect(self._scene_changed)
        tabs.addTab(t, "场景")

        # 听
        t = QWidget()
        f = QFormLayout(t)
        sources = [("电脑系统声音（全部）", "system"), ("指定程序的声音（游戏、Discord 等）", "apps"), ("麦克风", "mic")]
        self.source = _combo(sources, cfg.source)
        self.device = QComboBox()
        self.source.currentIndexChanged.connect(self._fill_devices)
        f.addRow("听什么", self.source)
        f.addRow("设备", self.device)
        self.apps_edit = QLineEdit("、".join(cfg.listen_apps))
        self.apps_edit.setPlaceholderText("程序名，用顿号或逗号分隔，例如 Discord.exe、VALORANT-Win64-Shipping.exe")
        self.apps_pick = QComboBox()
        self.apps_pick.addItem("从正在发声的程序中添加…", "")
        for name in apps.list_audio_apps():
            self.apps_pick.addItem(name, name)
        self.apps_pick.activated.connect(self._add_app)
        f.addRow("录这些程序", self.apps_edit)
        f.addRow("", self.apps_pick)
        tip = "" if apps.supported() else "（本机不支持按程序录音，需要 Windows 11；会退回录全部系统声音）"
        f.addRow(QLabel("留空表示录除本程序以外的全部声音。" + tip))
        tabs.addTab(t, "听")
        self._fill_devices()

        # 说
        t = QWidget()
        f = QFormLayout(t)
        self.speak_on = QCheckBox("开启说话转译（说中文，对方听到英文语音）")
        self.speak_on.setChecked(cfg.speak_enabled)
        self.speak_mode = _combo([("按住快捷键说话（推荐）", "ptt"), ("自动断句（一直在听）", "auto")], cfg.speak_mode)
        self.ptt_key = QLineEdit(cfg.ptt_key)
        self.ptt_key.setPlaceholderText("f8、caps_lock、alt_r、v …")
        self.speak_mic = QComboBox()
        for name in audio.list_devices("mic"):
            self.speak_mic.addItem(name or "系统默认", name)
        self.speak_mic.setCurrentIndex(max(0, self.speak_mic.findData(cfg.speak_mic)))
        self.speak_out = QLineEdit(cfg.speak_output)
        self.speak_out.setPlaceholderText("输出设备名包含的文字，VB-CABLE 为 CABLE Input")
        self.monitor = QCheckBox("同时在耳机里播放（听自己发出的英文）")
        self.monitor.setChecked(cfg.speak_monitor)
        self.voice = _combo([("Piper 英文（快，推荐）", "piper"), ("Kokoro（更自然，需要强 CPU）", "kokoro")], cfg.tts_voice)
        self.tts_speed = QDoubleSpinBox(minimum=0.7, maximum=1.6, singleStep=0.05, value=cfg.tts_speed)
        self.speak_target = _combo([(v, k) for k, v in LANG_NAMES.items() if k != "zh"], cfg.speak_target)
        f.addRow(self.speak_on)
        f.addRow("方式", self.speak_mode)
        f.addRow("说话键", self.ptt_key)
        f.addRow("麦克风", self.speak_mic)
        f.addRow("翻译成", self.speak_target)
        f.addRow("输出到", self.speak_out)
        f.addRow(self.monitor)
        f.addRow("声音", self.voice)
        f.addRow("语速", self.tts_speed)
        f.addRow(QLabel(
            "使用前先安装免费的 VB-CABLE 虚拟声卡（vb-audio.com/Cable），\n"
            "然后在游戏 / Discord 里把麦克风设为「CABLE Output」。\n"
            "注意：Piper 只会说英文；翻译成其他语言时请改用 Kokoro，发音也可能不准。"
        ))
        tabs.addTab(t, "说")

        # 聊天框
        t = QWidget()
        f = QFormLayout(t)
        self.ocr_on = QCheckBox("识别游戏聊天框里的外文消息并翻译")
        self.ocr_on.setChecked(cfg.ocr_enabled)
        region = "未框选（在托盘菜单里点「框选聊天区域」）" if not cfg.ocr_region else "x=%d y=%d 宽=%d 高=%d" % tuple(cfg.ocr_region)
        self.ocr_interval = QDoubleSpinBox(minimum=0.3, maximum=5, singleStep=0.1, value=cfg.ocr_interval, suffix=" 秒")
        self.type_hotkey = QLineEdit(cfg.type_hotkey)
        f.addRow(self.ocr_on)
        f.addRow("聊天区域", QLabel(region))
        f.addRow("检查间隔", self.ocr_interval)
        f.addRow("打字翻译框快捷键", self.type_hotkey)
        f.addRow(QLabel("游戏需要设成「无边框窗口」，全屏独占模式下悬浮窗会被挡住。"))
        tabs.addTab(t, "游戏聊天")

        # 识别
        t = QWidget()
        f = QFormLayout(t)
        self.tier = _combo(
            [
                (f"自动（本机判断为：{'高' if models.resolve_tier('auto') == 'high' else '低'}）", "auto"),
                ("高：Paraformer 流式（更准）", "high"),
                ("低：Zipformer 流式（更省资源）", "low"),
            ],
            cfg.tier,
        )
        self.second_pass = QCheckBox("分句结束后用 SenseVoice 重新识别定稿（更准，略增 CPU 占用）")
        self.second_pass.setChecked(cfg.second_pass)
        self.pause = QDoubleSpinBox(minimum=0.3, maximum=2.0, singleStep=0.1, value=cfg.pause_seconds, suffix=" 秒")
        self.max_seg = QDoubleSpinBox(minimum=4, maximum=30, value=cfg.max_segment_seconds, suffix=" 秒")
        self.threads = QSpinBox(minimum=0, maximum=16, value=cfg.num_threads, specialValueText="自动")
        f.addRow("识别档位", self.tier)
        f.addRow(self.second_pass)
        f.addRow("停顿多久算一句结束", self.pause)
        f.addRow("单句最长", self.max_seg)
        f.addRow("CPU 线程数", self.threads)
        f.addRow(QLabel("首次使用会自动下载模型（每个约 200 MB），保存在程序目录的 data/models。"))
        tabs.addTab(t, "识别")

        # 显示
        t = QWidget()
        f = QFormLayout(t)
        self.mode = _combo([("原文 + 译文", "both"), ("仅译文", "translation"), ("仅原文（不翻译）", "source")], cfg.display_mode)
        self.font_size = QSpinBox(minimum=12, maximum=60, value=cfg.font_size, suffix=" px")
        self.opacity = QSlider(Qt.Horizontal, minimum=5, maximum=100, value=int(cfg.opacity * 100))
        self.lines = QSpinBox(minimum=1, maximum=6, value=cfg.max_lines)
        self.save_tx = QCheckBox("保存文字记录（TXT + SRT，在 data/transcripts）")
        self.save_tx.setChecked(cfg.save_transcript)
        f.addRow("显示内容", self.mode)
        f.addRow("字号", self.font_size)
        f.addRow("背景不透明度", self.opacity)
        f.addRow("显示句数", self.lines)
        f.addRow(self.save_tx)
        tabs.addTab(t, "显示")

        # 术语表
        t = QWidget()
        v = QVBoxLayout(t)
        v.addWidget(QLabel("每行一条，格式：原文=译文。例如：\nLLM=大语言模型\n张伟=Zhang Wei"))
        self.glossary = QPlainTextEdit(cfg.glossary)
        v.addWidget(self.glossary)
        tabs.addTab(t, "术语表")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    def _add_app(self, i: int) -> None:
        name = self.apps_pick.itemData(i)
        if name:
            names = self._apps()
            if name not in names:
                names.append(name)
            self.apps_edit.setText("、".join(names))
        self.apps_pick.setCurrentIndex(0)

    def _apps(self) -> list[str]:
        import re

        return [n.strip() for n in re.split(r"[、,，;；\s]+", self.apps_edit.text()) if n.strip()]

    def _scene_changed(self) -> None:
        """切换场景时把预设开关同步到界面上（保存时才真正生效）。"""
        from copy import deepcopy

        tmp = deepcopy(self.cfg)
        apply_scene(tmp, self.scene.currentData())
        self.source.setCurrentIndex(max(0, self.source.findData(tmp.source)))
        self.speak_on.setChecked(tmp.speak_enabled)
        self.speak_mode.setCurrentIndex(max(0, self.speak_mode.findData(tmp.speak_mode)))
        self.ocr_on.setChecked(tmp.ocr_enabled)
        self._read_aloud = tmp.read_aloud

    def _fill_devices(self) -> None:
        self.device.clear()
        kind = self.source.currentData()
        self.device.setEnabled(kind != "apps")
        if kind == "apps":
            return
        for name in audio.list_devices(kind):
            self.device.addItem(name or "系统默认", name)
        i = self.device.findData(self.cfg.device_name)
        self.device.setCurrentIndex(max(0, i))

    def apply(self) -> None:
        c = self.cfg
        c.api_key = self.api_key.text().strip()
        c.base_url = self.base_url.text().strip() or "https://api.deepseek.com"
        c.model = self.model.text().strip() or "deepseek-chat"
        c.backup_api_key = self.backup_key.text().strip()
        c.backup_base_url = self.backup_url.text().strip()
        c.backup_model = self.backup_model.text().strip()
        c.translate_timeout = self.timeout.value()
        c.context_pairs = self.context.value()
        c.scene = self.scene.currentData()
        c.read_aloud = getattr(self, "_read_aloud", c.read_aloud) if c.scene == "face" else False
        c.source = self.source.currentData()
        c.device_name = self.device.currentData() or ""
        c.listen_apps = self._apps()
        c.speak_enabled = self.speak_on.isChecked()
        c.speak_mode = self.speak_mode.currentData()
        c.ptt_key = self.ptt_key.text().strip().lower() or "f8"
        c.speak_mic = self.speak_mic.currentData() or ""
        c.speak_target = self.speak_target.currentData()
        c.speak_output = self.speak_out.text().strip()
        c.speak_monitor = self.monitor.isChecked()
        c.tts_voice = self.voice.currentData()
        c.tts_speed = round(self.tts_speed.value(), 2)
        c.ocr_enabled = self.ocr_on.isChecked() and bool(c.ocr_region)
        c.ocr_interval = round(self.ocr_interval.value(), 2)
        c.type_hotkey = self.type_hotkey.text().strip()
        c.tier = self.tier.currentData()
        c.second_pass = self.second_pass.isChecked()
        c.pause_seconds = round(self.pause.value(), 2)
        c.max_segment_seconds = self.max_seg.value()
        c.num_threads = self.threads.value()
        c.display_mode = self.mode.currentData()
        c.font_size = self.font_size.value()
        c.opacity = self.opacity.value() / 100
        c.max_lines = self.lines.value()
        c.save_transcript = self.save_tx.isChecked()
        c.glossary = self.glossary.toPlainText()
        c.save()
