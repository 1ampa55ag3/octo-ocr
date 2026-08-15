# 架构说明

## 总体数据流

```
输入(PDF/图片)
  → load_pages: 扫描页渲染(200dpi) / 电子页文字层直取（FR-1.5 分流）
  → OcrEngine.recognize: RapidOCR 运行时 + PP-OCRv5 ONNX
       det(长边960/ImageNet归一化/box_thresh0.6/unclip1.5, 官方参数)
       → 超高框投影分割重识别（防紧邻两行被合并）
       → rec(动态宽48×H, 18385 类 CTC, v5 字典经 rec_keys_path 注入)
  → layout.group_lines_to_blocks: 栏聚类(列重叠) + 垂直间隙分块 + 块类别判定
  → paragraph.merge_lines: 行→段（句末标点/缩进/间隙/标题四信号）
  → pipeline 标点修复: [模型层(仅无标点段+结构校验)] → 规则层 → 偏移重映射 → 非正文段过滤
  → pipeline 段落修复: 页眉页脚/页码删除(位置带一致) → 版式统一(≥16字正文缩进)
  → export: 双层PDF(pymupdf, render_mode=3 隐形文字层) / DOCX / MD / TXT / JSON
```

## 模块图

```
mdun/
├── cli.py        子命令: ocr / repair / export / serve / license / audit
├── pipeline.py   Pipeline(settings, audit).process(path, dpi)
├── ocr/
│   ├── document.py    load_pages（PDF 分流 / 图片直读）
│   ├── engine.py      OcrEngine（v5 参数与字典注入、投影分割）；
│   └── layout.py      几何版面分析（块/栏/阅读顺序）；DocLayoutEngine（P1 接口）
├── postprocess/
│   ├── punctuation.py 规则层（宽度统一/配对/误识/句末补全 + 数字URL保护 + 偏移重映射）
│   ├── punc_model.py  PuncRestorer（ct-punc, sherpa-onnx）
│   ├── paragraph.py   行合并/拆分/页眉页脚/版式/阅读顺序
│   └── correction.py  形近字表 + ernie-csc 接口
├── export/         pdf / docx / markdown / json
├── security/
│   ├── audit.py       OfflineGuard（socket 封锁，仅回环）+ audit_source 静态审计
│   ├── crypto.py      SM4-CBC + SM3（gmssl 纯 Python）
│   ├── license.py     Ed25519 签名许可证（pycryptodomex）+ SM3 机器指纹
│   └── auditlog.py    JSONL 审计日志（文件锁）
└── web/            server.py（127.0.0.1 HTTP）+ static/（无外部资源三栏工作台）
```

## 关键设计决策

| 决策 | 原因 |
| --- | --- |
| PP-OCRv5 官方预处理参数（resize_long=960 / ImageNet 归一化 / box_thresh=0.6） | 与 PaddleX inference.yml 对齐，检测框质量显著优于默认值 |
| v5 字典经 `rec_keys_path` 注入 rapidocr | v5 rec 输出 18385 类（v4 仅 6623），字典不一致会全盘错字 |
| 超高检测框投影分割重识别 | 紧邻两行被 det 合并时兜底（经验证有效） |
| ct-punc 仅用于"完全无标点"段落 + 结构校验（数字守恒/CJK 长度±15%） | ct-punc 面向 ASR 语料，对已有标点文本会过度插入甚至扰动数字 |
| 规则层编辑在"保护占位符坐标系"计算，返回前重映射到原文坐标系 | 数字/URL 保护用私用区占位符，不重映射会错位 |
| 页眉页脚删除要求位置带（顶/底）一致 | 防止正文中重复短句被误删 |
| Ed25519（pycryptodomex）替代 SM2 | gmssl 不提供密钥生成；Ed25519 纯 Python 可跑、离线签发 |
| 桌面 GUI = 本地 Web 工作台（127.0.0.1）而非 Tauri | 零构建依赖、纯离线资源；后续可原样封装进 Tauri 桌面壳 |
| 移动端移除（PRD v1.0） | 用户明确要求，平台收敛为桌面 |

## 性能基线（本机实测，Apple Silicon / CPU）

| 项 | 数值 |
| --- | --- |
| 单页识别（1600×1200，8 行文本） | ≈0.25–0.4s |
| 完整管线（识别+修复+4 种导出） | ≈0.5–0.9s/页 |
| 模型体积 | det 4.8MB + rec 16.5MB + ct-punc 75MB(int8) |
