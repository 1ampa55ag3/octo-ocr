@echo off
rem OctoOCR-offline 一键启动（Windows）
rem 双击运行：自动装依赖（首次）→ 启动服务 → 打开浏览器；已在运行则直接打开浏览器
chcp 65001 >nul
cd /d "%~dp0"
set "URL=http://127.0.0.1:8788"

rem 已在运行 → 直接打开浏览器
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri '%URL%' -UseBasicParsing -TimeoutSec 2) | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
  echo 服务已在运行，直接打开浏览器。
  if not defined OCTO_NO_BROWSER start "" "%URL%"
  exit /b 0
)

rem 首次运行：自动创建虚拟环境并安装依赖
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo 首次运行：创建虚拟环境并安装依赖（约 2~5 分钟，请保持网络）…
  python -m venv .venv
  if errorlevel 1 (
    echo !! 未找到 Python 或虚拟环境创建失败。请先安装 Python 3.10+ 并勾选 Add to PATH。
    pause
    exit /b 1
  )
  "%PY%" -m pip install -q -e .
  if errorlevel 1 (
    echo !! 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
  )
)

rem 模型缺失 → 自动下载
set /a MODEL_COUNT=0
for %%f in (models\*.onnx) do set /a MODEL_COUNT+=1
if %MODEL_COUNT% LSS 8 (
  echo 模型缺失，自动下载（约 286MB，仅首次）…
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\download_models.ps1
)

echo 启动 OctoOCR-offline…（停止：按 Ctrl+C 或关闭本窗口）
set "PYTHONPATH=src"
rem 3 秒后自动打开浏览器（服务启动极快，首次模型加载不影响端口就绪）
if not defined OCTO_NO_BROWSER start "" cmd /c "timeout /t 3 /nobreak >nul & start "" "%URL%""
"%PY%" -m mdun.cli --data-dir . serve --port 8788
pause
