# 实时翻译

本地语音识别 + AI 翻译的桌面实时字幕工具，适合视频会议、网课和直播。中英互译，自动判断方向。

- **识别在本机**：sherpa-onnx 流式模型边听边出字（0.5 秒内），一句话结束后用 SenseVoice 重新识别定稿。
- **翻译用 DeepSeek**：定稿分句流式翻译，带上下文和术语表；可配置备用接口（任何 OpenAI 兼容接口）。
- **悬浮字幕窗**：置顶、半透明、可拖动缩放，可选原文+译文 / 仅译文 / 仅原文。
- **文字记录**：每次会话自动保存 TXT 和 SRT 字幕文件到 `data/transcripts`。

## Windows 使用

1. 安装 Python 3.10 以上（推荐 3.12）。
2. 双击 `setup.bat` 安装依赖（只需一次）。
3. 双击 `start.bat` 启动。首次启动会让你填写 DeepSeek API Key，并自动下载识别模型（约 450 MB）。
4. 屏幕下方出现字幕条：拖动移动，右下角缩放，右键打开菜单（暂停、设置、记录文件夹、退出）。托盘里也有同样的菜单。

默认录制电脑正在播放的声音（WASAPI 回环，不需要虚拟声卡）。在「设置 → 音频」可以切换成麦克风：说中文会译成英文。

出问题时用 `debug.bat` 启动，可以看到报错信息。

## macOS 使用

macOS 录系统声音需要先安装 [BlackHole](https://github.com/ExistentialAudio/BlackHole) 并在「音频 MIDI 设置」里建一个包含 BlackHole 的多输出设备。之后双击 `start.command`。

## 设置项

| 页 | 内容 |
| --- | --- |
| 翻译 | API Key、接口地址、模型、备用接口、超时、参考上文句数 |
| 音频 | 系统声音 / 麦克风，选择设备 |
| 识别 | 档位（自动 / 高 / 低）、是否二次定稿、停顿多久算一句、线程数 |
| 显示 | 显示内容、字号、背景不透明度、显示句数、是否保存记录 |
| 术语表 | 每行 `原文=译文`，翻译时强制使用 |

所有设置保存在 `data/settings.json`，模型在 `data/models`。

## 开发

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
python tests/asr_smoke.py <wav>...       # 只测识别
python tests/pipeline_smoke.py <wav>...  # 识别 + 翻译 + 记录（读取 data/settings.json 里的 API Key）
```

代码结构：`rtt/audio.py` 采集，`rtt/asr.py` 双遍识别，`rtt/translate.py` 翻译，`rtt/pipeline.py` 串联，`rtt/ui/` 界面。
