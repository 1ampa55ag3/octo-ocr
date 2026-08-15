#!/usr/bin/env bash
# OctoOCR 鸿蒙 PC 一键部署脚本（融合开发引擎 openEuler 环境）
# 前置：引擎网络模式 = NAT（能上网）；部署包已通过「文件共享」挂到 /mnt/linux_share
# 用法：bash /mnt/linux_share/deploy_harmony.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/octo-ocr"
HOME_APP="$HOME/octo-ocr"
cd "$HERE"

echo "== 0. 环境体检 =="
uname -m
cat /etc/os-release | head -2
nproc
free -h | head -2

# 共享目录文件是 root 属主：统一复制到主目录再干活
echo "== 1. 复制代码到主目录（约 290MB，几十秒）=="
rm -rf "$HOME_APP"
cp -r "$SRC" "$HOME_APP" || { echo "!! 复制失败，把报错发我"; exit 1; }
cp "$HERE"/*.pdf "$HOME_APP/" 2>/dev/null || true
cd "$HOME_APP"

# ---- 网络自检（NAT 模式）----
echo "== 2. 网络自检（需 NAT 模式）=="
NETOK=""
for m in https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.aliyun.com/pypi/simple https://pypi.org/simple; do
  if curl -s -m 8 -o /dev/null "$m/numpy/" 2>/dev/null; then MIRROR="$m"; NETOK=1; break; fi
done
if [ -z "$NETOK" ]; then
  echo "!! pip 镜像全部不可达。请先检查："
  echo "   1. 融合开发引擎界面 → 网络模式是否 NAT（host-only 连不了外网）"
  echo "   2. 鸿蒙电脑本身能否上网"
  echo "   3. /etc/resolv.conf 的 DNS 是否正常（可 ping 180.76.76.76）"
  echo "   4. env 里是否设了 http_proxy/https_proxy（有就先 unset 再重试）"
  echo "   改好后重跑本脚本。"
  exit 1
fi
echo "pip 镜像: $MIRROR"

# ---- 找 Python（>=3.10），没有就用 HarmonyBrew 装 ----
PY=""
for c in python3.11 python3.10 python3.12 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "-- 未找到 >=3.10 的 Python，尝试 HarmonyBrew 安装 --"
  if command -v brew >/dev/null 2>&1; then
    brew install python@3.11 2>/dev/null || brew install python3 2>/dev/null || true
    for c in python3.11 python3.10 python3; do
      if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
    done
  fi
  if [ -z "$PY" ]; then
    echo "!! 安装 Python 失败。请执行: brew search python 并按输出安装 python@3.11"
    exit 1
  fi
fi
echo "使用 Python: $($PY --version 2>&1)"

# ---- 虚拟环境 + 依赖 ----
echo "== 3. 创建虚拟环境并安装依赖（约 2~5 分钟）=="
"$PY" -m venv .venv 2>/dev/null || {
  "$PY" -m venv --without-pip .venv || { echo "!! venv 创建失败，把报错发我"; exit 1; }
  .venv/bin/python -m ensurepip --upgrade
}
.venv/bin/python -m pip install -q -i "$MIRROR" -r "$HERE/requirements-harmony.txt" || {
  echo "!! 依赖安装失败。把上面的报错发我。"
  exit 1
}
# rapid-latex-ocr 锁 numpy<2，与 rapid-layout 要求的 numpy>=2 冲突；
# 该限制实为多余（numpy2 下公式识别正常），单独无依赖安装
.venv/bin/python -m pip install -q -i "$MIRROR" --no-deps "rapid-latex-ocr==0.0.9" || {
  echo "!! rapid-latex-ocr 安装失败。把报错发我。"
  exit 1
}
# rapidocr 会连带装完整版 opencv-python（依赖 libxcb 等 X11 图形库）。
# 两个 opencv 包共享 cv2 文件，卸载任一都会误删文件；
# 因此不卸载，改为强制重装 headless 使其成为 cv2 的实际提供者（无需图形库）
.venv/bin/python -m pip install -q --force-reinstall --no-deps -i "$MIRROR" "opencv-python-headless>=4.8"

# ---- 模型 ----
echo "== 4. 模型检查 =="
MODEL_COUNT=$(ls models/*.onnx 2>/dev/null | wc -l | tr -d ' ')
if [ "$MODEL_COUNT" -lt 8 ]; then
  echo "-- 模型不完整（$MODEL_COUNT 个），联网补下 --"
  bash scripts/download_models.sh || { echo "!! 模型下载失败。把报错发我。"; exit 1; }
fi
echo "模型文件 $(ls models | wc -l | tr -d ' ') 个"

# ---- 验证 + 冒烟 ----
echo "== 5. 验证导入 =="
PYTHONPATH=src .venv/bin/python -c "import onnxruntime, rapidocr_onnxruntime, pymupdf, sherpa_onnx, cv2, PIL, yaml, openpyxl; print('ONNXRuntime', onnxruntime.__version__, '全部导入成功')" || {
  echo "!! 导入失败。若报 libxcb/libGL 缺失，执行: sudo dnf install -y mesa-libGL libxcb"
  echo "   若仍失败，把上面的报错发我。"
  exit 1
}

echo ""
echo "== 6. 冒烟识别（若包内有样例 PDF）=="
SAMPLE=$(ls *.pdf 2>/dev/null | head -1)
if [ -n "$SAMPLE" ]; then
  PYTHONPATH=src .venv/bin/python -m mdun.cli --data-dir . ocr "$SAMPLE" -o /tmp/octo-out --format txt || {
    echo "!! 识别失败。把上面的报错发我。"
    exit 1
  }
  head -c 300 /tmp/octo-out/*.txt | head -4
else
  echo "（未找到样例 PDF，跳过冒烟；可稍后自行测试）"
fi
echo ""

echo "=============================================="
echo "  部署完成！接下来："
echo "  1. 融合开发引擎网络模式切到 仅主机（host-only）"
echo "  2. ip addr 查虚拟机 IP（如 172.16.105.2）"
echo "  3. 启动服务:"
echo "     cd ~/octo-ocr && PYTHONPATH=src .venv/bin/python -m mdun.cli --data-dir . serve --host 0.0.0.0 --port 8788"
echo "  4. 鸿蒙浏览器访问 http://<虚拟机IP>:8788"
echo "=============================================="
