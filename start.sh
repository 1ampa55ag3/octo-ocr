#!/usr/bin/env bash
# OctoOCR 启动脚本（鸿蒙融合开发引擎环境；安装完成后每次使用运行本脚本即可）
# 用法：cd ~/octo-ocr && bash start.sh
# 行为：服务已在运行 → 直接打印访问地址；否则启动服务并打印地址
set -u
cd "$(dirname "$0")" || exit 1
PORT="${OCTO_PORT:-8788}"
URL="http://127.0.0.1:$PORT"

# 选择解释器：离线包自带运行时 > venv > 系统 python3
PY=""
[ -x python/bin/python3 ] && PY="python/bin/python3"
[ -z "$PY" ] && [ -x .venv/bin/python ] && PY=".venv/bin/python"
[ -z "$PY" ] && command -v python3 >/dev/null 2>&1 && PY="python3"
if [ -z "$PY" ]; then
  echo "!! 未找到 Python 运行时。请先运行安装脚本（install_offline.sh 或 deploy_harmony.sh）"
  exit 1
fi

STARTED=0
if curl -s -m 2 -o /dev/null "$URL"; then
  echo "服务已在运行。"
else
  echo "启动 OctoOCR…（停止：按 Ctrl+C 或关闭本窗口）"
  PYTHONPATH=src "$PY" -m mdun.cli --data-dir . serve --host 0.0.0.0 --port "$PORT" &
  SRV=$!
  STARTED=1
  for _ in $(seq 1 60); do
    curl -s -m 1 -o /dev/null "$URL" && break
    sleep 0.5
  done
fi

# 自动识别当前虚拟机 IP 并打印鸿蒙浏览器访问地址
IP=$(ip -4 addr show 2>/dev/null | grep -oE 'inet (172\.|192\.168\.|10\.)[0-9.]+' | awk '{print $2}' | head -1)
echo ""
echo "=============================================="
if [ -n "$IP" ]; then
  echo "  请在鸿蒙浏览器打开:"
  echo "      http://$IP:$PORT"
else
  echo "  请在鸿蒙浏览器打开: http://<虚拟机IP>:$PORT"
  echo "  （虚拟机 IP 用 ip addr 查看）"
fi
echo "=============================================="

if [ "$STARTED" = "1" ]; then
  wait "$SRV"
fi
