# 实时翻译

本地语音识别 + AI 翻译的桌面实时翻译工具。适合视频会议、网课、直播、外服游戏和跨语言通话。

- **听**：录系统声音或指定程序（游戏、Discord）的声音，sherpa-onnx 本地识别，DeepSeek 翻译，悬浮字幕显示。
- **说**：按住快捷键说中文，松开后约 1–2.5 秒，英文语音从虚拟麦克风发给游戏 / Discord / Zoom。
- **看聊天框**：框选游戏聊天区域，本地 OCR 识别新的外文消息并翻译。
- **打字翻译**：快捷键弹出输入框，中文回车 → 英文复制到剪贴板（可选同时念出来）。
- **场景**：托盘菜单一键切换「会议 / 游戏 / 跨语言通话 / 面对面」。
- **文字记录**：每次会话自动保存 TXT 和 SRT 到 `data/transcripts`。

## Windows 使用

1. 安装 Python 3.10–3.13（推荐 3.12）。
2. 双击 `setup.bat` 安装依赖（更新代码后也要再运行一次）。
3. 双击 `start.bat` 启动。首次启动填写 DeepSeek API Key，并自动下载模型（识别约 450 MB，语音约 80 MB）。
4. 屏幕下方出现字幕条：拖动移动，右下角缩放，右键或托盘菜单里切换场景、打开设置。

出问题时用 `debug.bat` 启动，可以看到报错信息。

### 说话转译（说中文，对方听到英文）

1. 安装免费的 [VB-CABLE](https://vb-audio.com/Cable/) 虚拟声卡，装完重启电脑。
2. 在游戏 / Discord 的语音设置里，把**输入设备（麦克风）**设为 `CABLE Output`。
3. 托盘菜单 → 场景 → 游戏（或「设置 → 说」里勾选开启）。
4. 按住 **F8** 说中文，松开后对方会听到英文。字幕条上蓝色的「我：」是你说的话和发出去的英文。

说话键、麦克风、语速、是否在耳机里监听都可以在「设置 → 说」里改。

### 只听游戏和 Discord 的声音（Windows 11）

「设置 → 听」选「指定程序的声音」，从下拉框里添加正在发声的程序（如 `Discord.exe`、游戏的 exe）。留空则录除本程序外的全部声音。这个功能用 `bin/rtt-capture.exe`（源码在 `native/rtt-capture`），需要 Windows 11。

### 游戏聊天框

托盘菜单 →「框选聊天区域…」，拖出聊天框的范围。之后新出现的外文消息会翻译显示在旁边的小窗里。游戏需要设成**无边框窗口**，全屏独占模式下悬浮窗会被挡住。

回复：按 **Ctrl+Alt+T** 打开打字翻译框，输入中文回车，英文自动复制，切回游戏 Ctrl+V。

### 注意

- 游戏如果以管理员身份运行，本程序也要用管理员身份运行，否则收不到 F8 等快捷键。
- 本程序只截图和录音，不注入游戏进程、不自动打字。

## macOS

录系统声音、虚拟麦克风都用 [BlackHole](https://github.com/ExistentialAudio/BlackHole)：「设置 → 说 → 输出到」填 `BlackHole`。按程序录音只支持 Windows。双击 `start.command` 启动。

## 开发

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
python tests/asr_smoke.py <wav>...        # 只测识别
python tests/pipeline_smoke.py <wav>...   # 听：识别 + 翻译 + 记录
python tests/speak_smoke.py <中文wav>     # 说：识别 + 翻译 + 语音合成（写到 WAV）
native/build.sh                           # 交叉编译 rtt-capture.exe
```

代码结构：`rtt/audio.py` 采集，`rtt/apps.py` 按程序录音，`rtt/asr.py` 双遍识别，`rtt/translate.py` 翻译，`rtt/tts.py` 语音合成，`rtt/pipeline.py` 听，`rtt/speak.py` 说，`rtt/chat.py` + `rtt/ocr_worker.py` 聊天框，`rtt/scenes.py` 场景，`rtt/ui/` 界面。
