#!/usr/bin/env bash
# OctoOCR 鸿蒙 PC 完全离线安装脚本（host-only 断网可用）
# 不联网、不装系统包、不用 venv：自带 Python 运行时 + 全部依赖轮子 + 模型
# 用法（融合开发引擎 Linux 终端，host-only 模式下即可）：
#   bash /mnt/linux_share/install_offline.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/octo-ocr"
HOME_APP="$HOME/octo-ocr"
cd "$HERE"

echo "== 0. 环境体检 =="
uname -m
nproc
free -h | head -2

if [ "$(uname -m)" != "aarch64" ]; then
  echo "!! 本离线包仅支持 aarch64 平台（麒麟 X90 等），当前平台: $(uname -m)"
  exit 1
fi

echo "== 1. 复制代码与模型到主目录（约 290MB，几十秒）=="
rm -rf "$HOME_APP"
cp -r "$SRC" "$HOME_APP" || { echo "!! 复制失败"; exit 1; }
cp "$HERE"/*.pdf "$HOME_APP/" 2>/dev/null || true
cd "$HOME_APP"

echo "== 2. 解压自带 Python 运行时（3.11，aarch64）=="
if [ ! -x python/bin/python3 ]; then
  tar -xzf "$HERE/python-runtime.tar.gz" || { echo "!! 解压失败"; exit 1; }
fi
PY="$HOME_APP/python/bin/python3"
echo "运行时版本: $($PY --version 2>&1)"

echo "== 3. 离线安装全部依赖（约 2~5 分钟，无需网络）=="
"$PY" -m pip install --no-index --find-links "$HERE/wheels" -r "$HERE/requirements-harmony.txt" || {
  echo "!! 依赖安装失败。把上面的报错发我。"
  exit 1
}
# rapid-latex-ocr 锁 numpy<2 与 rapid-layout 冲突（实测多余），单独无依赖安装
"$PY" -m pip install --no-index --find-links "$HERE/wheels" --no-deps "rapid-latex-ocr==0.0.9" || {
  echo "!! rapid-latex-ocr 安装失败。把报错发我。"
  exit 1
}
# 两个 opencv 包共享 cv2 文件：强制重装 headless 使其成为 cv2 实际提供者（无需图形库）
"$PY" -m pip install --no-index --find-links "$HERE/wheels" --force-reinstall --no-deps "opencv-python-headless>=4.8"

echo "== 4. 模型检查 =="
MODEL_COUNT=$(ls models/*.onnx 2>/dev/null | wc -l | tr -d ' ')
echo "模型文件 $(ls models 2>/dev/null | wc -l | tr -d ' ') 个（onnx $MODEL_COUNT 个）"
if [ "$MODEL_COUNT" -lt 8 ]; then
  echo "!! 模型不完整，请重新拷贝部署包。"
  exit 1
fi

echo "== 5. 验证导入 =="
PYTHONPATH=src "$PY" -c "import onnxruntime, rapidocr_onnxruntime, pymupdf, sherpa_onnx, cv2, PIL, yaml, openpyxl; print('ONNXRuntime', onnxruntime.__version__, '全部导入成功')" || {
  echo "!! 导入失败。把上面的报错发我。"
  exit 1
}

echo ""
echo "== 6. 冒烟识别（若包内有样例 PDF）=="
SAMPLE=$(ls *.pdf 2>/dev/null | head -1)
if [ -n "$SAMPLE" ]; then
  PYTHONPATH=src "$PY" -m mdun.cli --data-dir . ocr "$SAMPLE" -o /tmp/octo-out --format txt || {
    echo "!! 识别失败。把上面的报错发我。"
    exit 1
  }
  head -c 300 /tmp/octo-out/*.txt | head -4
else
  echo "（未找到样例 PDF，跳过冒烟）"
fi
echo ""

echo "=============================================="
echo "  离线安装全部成功！以后都用自带运行时启动："
echo "    cd ~/octo-ocr"
echo "    PYTHONPATH=src python/bin/python3 -m mdun.cli --data-dir . serve --host 0.0.0.0 --port 8788"
echo "  然后 ip addr 查 IP，鸿蒙浏览器访问 http://<IP>:8788"
echo "  限速降噪（可选）: echo '{"num_threads": 3}' > ~/octo-ocr/config.json 后重启服务"
echo "=============================================="
