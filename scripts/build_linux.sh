#!/usr/bin/env bash
# Linux 版打包脚本（鸿蒙 PC 融合开发引擎路径的产物）。
# 产出 dist/mdun/ 自包含目录，可整体拷贝到鸿蒙 PC 的融合开发引擎
# （OpenEuler Linux 子系统）中运行。
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python

if ! $PY -c "import PyInstaller" 2>/dev/null; then
  echo "安装 PyInstaller（离线环境请预置 wheel）..."
  $PY -m pip install pyinstaller
fi

$PY -m PyInstaller --noconfirm --clean \
  --name mdun \
  --collect-all rapidocr_onnxruntime \
  --collect-all sherpa_onnx \
  --collect-data rapidocr_onnxruntime \
  --hidden-import gmssl \
  --hidden-import Cryptodome \
  --add-data "src/mdun/web/static:mdun/web/static" \
  src/mdun/cli.py

echo "打包完成: dist/mdun/"
echo "鸿蒙 PC 部署：将 dist/mdun 与 models/ 一并拷贝到融合开发引擎 Linux 环境，"
echo "运行: MDUN_HOME=<数据目录> ./mdun serve --port 8788"
