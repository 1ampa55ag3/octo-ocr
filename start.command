#!/bin/bash
# OctoOCR-offline 一键启动（macOS）
# 双击运行：自动装依赖（首次）→ 启动服务 → 打开浏览器；已在运行则直接打开浏览器
cd "$(dirname "$0")" || exit 1
URL="http://127.0.0.1:8788"
open_browser() { [ -n "${OCTO_NO_BROWSER:-}" ] || open "$URL"; }

# 已在运行 → 直接打开浏览器
if curl -s -m 2 -o /dev/null "$URL"; then
  echo "服务已在运行，直接打开浏览器: $URL"
  open_browser
  exit 0
fi

# 首次运行：自动创建虚拟环境并安装依赖
if [ ! -x .venv/bin/python ]; then
  echo "首次运行：创建虚拟环境并安装依赖（约 2~5 分钟，请保持网络）…"
  PY="$(command -v python3)"
  if [ -z "$PY" ]; then
    echo "!! 未找到 python3。请先安装 Python 3.10+（brew install python@3.11）"
    read -r -p "按回车退出…"
    exit 1
  fi
  "$PY" -m venv .venv || { echo "!! 虚拟环境创建失败"; read -r -p "按回车退出…"; exit 1; }
  .venv/bin/python -m pip install -q -e . || { echo "!! 依赖安装失败"; read -r -p "按回车退出…"; exit 1; }
fi

# 模型缺失 → 自动下载
if [ "$(ls models/*.onnx 2>/dev/null | wc -l | tr -d ' ')" -lt 8 ]; then
  echo "模型缺失，自动下载（约 286MB，仅首次）…"
  bash scripts/download_models.sh || echo "（模型下载失败，可稍后手动重跑 scripts/download_models.sh）"
fi

echo "启动 OctoOCR-offline…（停止：按 Ctrl+C 或关闭本窗口）"
PYTHONPATH=src .venv/bin/python -m mdun.cli --data-dir . serve --port 8788 &
SERVER_PID=$!

# 等服务就绪后自动打开浏览器
for _ in $(seq 1 60); do
  curl -s -m 1 -o /dev/null "$URL" && break
  sleep 0.5
done
open_browser
echo "浏览器已打开: $URL"

wait "$SERVER_PID"
