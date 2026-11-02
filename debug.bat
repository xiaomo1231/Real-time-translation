@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 带控制台窗口启动，出错时可以看到报错信息
.venv\Scripts\python.exe main.py
pause
