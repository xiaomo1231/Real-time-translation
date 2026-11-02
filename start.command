#!/bin/bash
# macOS：双击运行。首次会创建虚拟环境并安装依赖。
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || { echo "安装失败"; read; exit 1; }
fi
exec .venv/bin/python main.py
