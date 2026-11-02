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

from .. import audio, models
from ..config import Settings


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

        # 音频
        t = QWidget()
        f = QFormLayout(t)
        self.source = _combo([("电脑系统声音（会议、网课、直播）", "system"), ("麦克风", "mic")], cfg.source)
        self.device = QComboBox()
        self.source.currentIndexChanged.connect(self._fill_devices)
        f.addRow("声音来源", self.source)
        f.addRow("设备", self.device)
        f.addRow(QLabel("麦克风说中文会自动译成英文，说英文会译成中文。"))
        tabs.addTab(t, "音频")
        self._fill_devices()

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

    def _fill_devices(self) -> None:
        self.device.clear()
        for name in audio.list_devices(self.source.currentData()):
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
        c.source = self.source.currentData()
        c.device_name = self.device.currentData() or ""
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
