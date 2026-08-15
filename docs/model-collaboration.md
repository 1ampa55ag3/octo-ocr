# 模型协作架构设计（v1.0）

> 解决「多个本地模型如何在同一管线中分工、路由、仲裁与融合」的问题。
> 适用范围：PP-OCRv5（文字）、PP-DocLayout（版面）、SLANet/RapidTable（表格结构）、
> PP-FormulaNet（公式）、ct-punc（标点）。

## 1. 总体协作视图

```
页面输入
  │
  ▼
[0 路由] 电子文字层? ──是──▶ 直取文字（跳过全部识别模型）
  │ 否
  ▼
[1 版面分析] PP-DocLayout-YOLO ──▶ 区域列表 {type, box, conf}
  │                              type ∈ text | table | formula | figure |
  │                                      header-footer | page-number
  ▼
[2 区域路由] 按类型分派（每区域一个处理者，互不阻塞）
  ├─ text  ──────────▶ [2a] PP-OCRv5 det → rec（共享会话）
  ├─ table ──────────▶ [2b] SLANet 结构 → 网格 → 单元格裁切
  │                      └─▶ PP-OCRv5 rec（批量，同一会话复用）→ Table{rows}
  ├─ formula ────────▶ [2c] PP-FormulaNet → LaTeX → Formula{latex, box}
  ├─ figure ─────────▶ 占位（不识别）
  └─ header/footer ──▶ [2a] 低优先级识别（供跨页删除）
  │
  ▼
[3 阅读顺序] 版面模型顺序 + 栏聚类 → 异构块统一排序（text/table/formula 平等参与）
  │
  ▼
[4 后处理协作]
  ├─ 段落聚合：text 行合并成段；table 单元格文本按格保留；formula 不参与合并
  ├─ 标点修复：规则层 + ct-punc 只作用于 text 段落与表格单元格文本；
  │            formula 的 LaTeX 为保护区（白名单跳过，规则引擎已支持保护段）
  ├─ 页眉页脚/页码删除：跨页模式匹配
  └─ 错字快修：text/单元格文本；LaTeX 跳过
  │
  ▼
[5 高精仲裁（可选，桌面）]
  │  版面置信低 / 区域分类不确定 / 表格结构置信低 / 公式置信低
  │        ↓ 命中任一
  │        ↓
  │  结果按 §4 融合策略并入
  ▼
[6 导出] 双层PDF（文字层）/ DOCX（原生表格）/ XLSX / MD（表格语法）/ JSON（全结构）
```

## 2. 模型角色与资源预算

| 模型 | 角色 | 体积 | 加载策略 | 运行位置 |
| --- | --- | --- | --- | --- |
| PP-OCRv5 det/rec | 文字识别（基础） | ~21MB | 启动常驻 | 全平台（CPU/GPU/NPU） |
| PP-DocLayout | 版面区域分类 | ~10MB | 启动常驻 | 全平台 |
| SLANet（RapidTable） | 表格结构 | ~7MB | **懒加载**（页内含表格才载入） | 全平台 |
| PP-FormulaNet-S | 公式→LaTeX | ~5MB | **懒加载**（页内含公式才载入） | 全平台 |
| ct-punc | 无标点段补标点 | ~75MB | 可选包，加载一次 | 全平台 |

**内存控制**：基础四模型常驻约 <200MB（ORT arena 另计）；懒加载模型用后保留
（LRU 淘汰）；VLM 子进程用完即退（可配置常驻）。

## 3. 路由与仲裁规则（阈值可配置）

| 条件 | 决策 |
| --- | --- |
| 区域分类 conf < 0.6 | 该区域标记"不确定"，桌面端转 VLM 兜底；否则按 text 处理 |
| SLANet 结构置信 < 0.7 或行/列数异常（0 行或 >100 列） | 表格降级为普通文本块 + 标记；桌面转 VLM 表格输出（HTML 解析回填） |
| FormulaNet 置信 < 0.5 或输出非法 LaTeX（括号不配对） | 降级为图像占位 + 原文 rec 文本；桌面转 VLM LaTeX |
| 页内所有区域均低置信 | 整页 VLM 重识别（结果替换，记录 diff） |
| VLM 不可用（未装高精包/显存不足） | 全部回退基础管线（功能完整，精度按基础档） |

## 4. 融合策略（多模型输出如何合并）

1. **不破坏坐标映射**：任何融合都产出统一 \`Block\`（text/table/formula）带 box 与来源标签
   （\`source: ppocrv5 | slanet | formulanet | vlm\`），UI 可显示来源徽标；
2. **区域级替换**：VLM 只替换命中区域（而非整页），其余区域保留基础管线结果；
3. **单元格级回填**：VLM 表格 HTML 与 SLANet 网格按行列对齐后，仅回填置信低的单元格；
4. **可解释 diff**：每次融合记录 {region, base→merged, reason}，UI diff 面板可查看、可回退；
5. **确定性优先**：同一输入+同一模型集，输出一致（VLM 关闭采样）。

## 5. 会话与调度

- 同一进程内共享 ORT 会话：rec 会话被 text/表格单元格复用，批推理（batch=6）；
- 页级并行：页间并行（线程池，每线程独立推理上下文），页内串行（依赖版面→区域）；
- VLM 例外：llama.cpp 子进程 + 本地 HTTP（\`LlamaCppVlmEngine\` 接口已预留），
  与主进程零耦合、崩溃不影响基础管线；
- 断点续跑：区域结果落盘缓存（加密），重跑跳过已完成区域。

## 6. 端侧裁剪（桌面）

- 可用：PP-OCRv5 + PP-DocLayout + SLANet + FormulaNet（合计 ~43MB，HiAI NPU 或 CPU）；
- 不可用：VLM 档（显存/内存不足）——高精场景由桌面端承担，项目包（.mdproj）可跨端；
- 路由规则同 §3，VLM 分支恒回退基础管线。

## 7. 与现有代码的衔接点

| 现有 | 变更 |
| --- | --- |
| \`ocr/layout.py: Block(kind)\` | kind 增加 \`table\`/\`formula\`/\`figure\`，附 rows/latex 字段 |
| \`ocr/engine.py: OcrEngine\` | 拆出 \`RegionRouter\`：按版面类型分派识别器 |
| \`pipeline.py: Pipeline._process_page\` | 插入阶段 [1][2][5]，保持 \`on_progress/cancel\` 契约 |
| \`postprocess\` | 标点/段落修复增加 LaTeX 保护段与单元格上下文 |
| \`export/\` | docx 原生表格（python-docx add_table）、xlsx（openpyxl）、MD 表格 |
| \`web/server.py\` | 项目 JSON schema 增加 table/formula 块（v2），前端表格卡片/公式双显 |
| \`scripts/download_models.sh\` | 新增版面/表格/公式模型下载与基础包/可选包分层 |
