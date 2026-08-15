#!/usr/bin/env bash
# 离线模型下载脚本（PP-OCRv5 det/rec + 方向分类 + ct-punc 标点模型）
# 默认使用 hf-mirror.com；可设 HF_ENDPOINT 覆盖（如内网镜像）。
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p models
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for cand in .venv/bin/python .venv/Scripts/python.exe; do
    [ -x "$cand" ] && PY="$cand" && break
  done
fi
PY="${PY:-python3}"
ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

echo "== PP-OCRv5 检测模型 =="
curl -sL --retry 3 -o models/ppocrv5_mobile_det.onnx \
  "$ENDPOINT/PaddlePaddle/PP-OCRv5_mobile_det_onnx/resolve/main/inference.onnx"
curl -sL --retry 3 -o models/ppocrv5_det_inference.yml \
  "$ENDPOINT/PaddlePaddle/PP-OCRv5_mobile_det_onnx/resolve/main/inference.yml"

echo "== PP-OCRv5 识别模型 =="
curl -sL --retry 3 -o models/ppocrv5_mobile_rec.onnx \
  "$ENDPOINT/PaddlePaddle/PP-OCRv5_mobile_rec_onnx/resolve/main/inference.onnx"
curl -sL --retry 3 -o models/ppocrv5_rec_inference.yml \
  "$ENDPOINT/PaddlePaddle/PP-OCRv5_mobile_rec_onnx/resolve/main/inference.yml"

echo "== 方向分类模型（可选，缺省用 rapidocr 内置）=="
curl -sL --retry 3 -o models/ppocrv4_mobile_cls.onnx \
  "$ENDPOINT/PaddlePaddle/PP-OCRv4_mobile_cls_onnx/resolve/main/inference.onnx" || echo "cls 跳过"

echo "== ct-punc 中文标点模型 =="
REPO="ranger810/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8"
F=$($PY -c "import json,urllib.request; d=json.load(urllib.request.urlopen('$ENDPOINT/api/models/$REPO')); print([s['rfilename'] for s in d.get('siblings',[]) if s['rfilename'].endswith('.onnx')][0])")
curl -sL --retry 3 -o models/ct_punc_zh.onnx "$ENDPOINT/$REPO/resolve/main/$F"

echo "== 生成 v5 字典 =="
$PY -c "
import yaml
d = yaml.safe_load(open('models/ppocrv5_rec_inference.yml'))
chars = d['PostProcess']['character_dict']
open('models/ppocrv5_keys.txt','w',encoding='utf-8').write('\n'.join(chars))
print('keys written:', len(chars))
"


echo "== 版面分析（PP-DocLayout / layout_yolo，CDLA 10类）=="
curl -sL --retry 3 -o models/layout_cdla.onnx \
  "https://modelscope.cn/models/RapidAI/RapidLayout/resolve/v1.2.0/onnx/pp_layout/layout_cdla.onnx"

echo "== 表格结构（SLANet-plus）=="
curl -sL --retry 3 -o models/slanet_plus.onnx \
  "https://modelscope.cn/models/RapidAI/RapidTable/resolve/v2.0.0/slanet-plus.onnx"

echo "== 公式识别（LaTeX-OCR 四件套，github 较慢可断点续传）=="
LATEX_BASE="https://github.com/RapidAI/RapidLaTeXOCR/releases/download/v0.0.0"
for f in encoder.onnx decoder.onnx image_resizer.onnx tokenizer.json; do
  curl -sL --retry 3 --retry-all-errors --max-time 1500 -C - -o models/latexocr_$f "$LATEX_BASE/$f" || echo "latexocr_$f FAILED"
done

echo "模型下载完成（基础包约 65MB：det/rec/cls + 版面 + 表格 + 公式）"
ls -la models/
echo "模型下载完成:"
ls -la models/
