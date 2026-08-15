# OctoOCR-offline 模型下载（Windows PowerShell 版，一次性，约 2GB）
# 用法：在仓库目录里右键 → 在此处打开终端（或 PowerShell）→ 执行 .\scripts\download_models.ps1
# 首次执行若报「禁止运行脚本」：先执行  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned  再重试
$ErrorActionPreference = "Stop"
$endpoint = if ($env:HF_ENDPOINT) { $env:HF_ENDPOINT } else { "https://hf-mirror.com" }
New-Item -ItemType Directory -Force -Path models | Out-Null

function Download($url, $out) {
    Write-Host "下载 $out ..."
    Invoke-WebRequest -Uri $url -OutFile $out
}

$det = "$endpoint/PaddlePaddle/PP-OCRv5_mobile_det_onnx/resolve/main/inference.onnx"
Download $det "models\ppocrv5_mobile_det.onnx"
Download "$endpoint/PaddlePaddle/PP-OCRv5_mobile_det_onnx/resolve/main/inference.yml" "models\ppocrv5_det_inference.yml"

Download "$endpoint/PaddlePaddle/PP-OCRv5_mobile_rec_onnx/resolve/main/inference.onnx" "models\ppocrv5_mobile_rec.onnx"
Download "$endpoint/PaddlePaddle/PP-OCRv5_mobile_rec_onnx/resolve/main/inference.yml" "models\ppocrv5_rec_inference.yml"

# 方向分类（可选，失败不影响）
try { Download "$endpoint/PaddlePaddle/PP-OCRv4_mobile_cls_onnx/resolve/main/inference.onnx" "models\ppocrv4_mobile_cls.onnx" } catch { Write-Host "cls 模型跳过" }

# 标点模型（可选，失败不影响）
try { Download "$endpoint/ranger810/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8/resolve/main/model.int8.onnx" "models\ct_punc_zh.onnx" } catch { Write-Host "ct-punc 模型跳过" }

Write-Host "完成。模型已放入 models 目录。"