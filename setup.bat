@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/3] 查找 Python...
set PY=
for %%v in (3.12 3.13 3.11 3.10) do (
  if not defined PY (
    py -%%v -c "import sys" >nul 2>&1 && set PY=py -%%v
  )
)
if not defined PY (
  python -c "import sys; assert sys.version_info>=(3,10)" >nul 2>&1 && set PY=python
)
if not defined PY (
  echo 没有找到 Python 3.10 以上版本。请先安装 Python 3.12：https://www.python.org/downloads/
  echo 或在命令行运行：winget install Python.Python.3.12
  pause
  exit /b 1
)
echo 使用 %PY%
echo [2/3] 创建虚拟环境 .venv ...
if not exist .venv %PY% -m venv .venv
echo [3/3] 安装依赖（首次约需几分钟）...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo 依赖安装失败，请把上面的报错发给我。
  pause
  exit /b 1
)
echo.
echo 安装完成！双击 start.bat 开始使用。
pause
