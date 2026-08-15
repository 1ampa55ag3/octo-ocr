# OctoOCR 前端规范（v1.0）

> 本规范为 Web 工作台（\`src/mdun/web/static/\`）的**强制**实现标准。
> 任何 UI 变更必须通过 \`tests/ui_conformance.py\`（Playwright 自动检查）方可合入。

## 1. 设计原则

1. **离线优先**：零 CDN、零外链资源；第三方库（Quill、Lucide）本地化 vendoring，记录版本与许可；
2. **令牌驱动**：颜色/字号/间距/圆角一律经 CSS 变量（§4），禁止散落魔法值；
3. **主题自适应**：所有颜色必须同时定义 light/dark 两套；图标使用 \`currentColor\` 内联 SVG，禁止用 emoji/特殊符号字符充当图标；
4. **尺寸稳定**：交互控件在状态变化（文案/图标替换）前后尺寸不得突变；
5. **可验证**：规范条款能自动检查的，一律写入 conformance 脚本。

## 2. 组件规范

### 2.1 按钮（三级）

| 级 | 类 | 用途 | 规格 |
| --- | --- | --- | --- |
| 主按钮 | \`.btn.primary\` | 导入文件 | 高 28px，accent 底白字，圆角 4px，hover 提亮 8% |
| 次按钮 | \`.btn\` | 明暗切换等 | 高 28px，panel 底 border 描边，hover 提亮 |
| 工具按钮 | \`#toolbar .repair-group button\`、\`.export-bar button\`、\`.page-nav button\` | 修复/导出/翻页 | 高 28px，inline-flex 图标+文字，gap 6px，accent 描边透明底 |

通用规则：
- \`display:inline-flex; align-items:center; gap:6px; padding:0 10px;\`，**固定 height:28px**，\`line-height:1\`；
- 字号一律 \`var(--ctrl-font)=13px\`（全站自定义控件，禁止 12.5/14px 混用）；
- 图标按钮（仅图标无文字）\`padding:0; width:28px; justify-content:center;\`；
- 交互态：\`hover\` 亮度 +8%；\`active\` 亮度 -8%；\`focus-visible\` 显示 2px accent 轮廓；
- **JS 动态注入图标必须包 \`.icn\` 容器**（历史 bug：裸 SVG 以 24px 原始尺寸渲染撑大按钮）。

### 2.2 图标

- 来源：Lucide（ISC，vendored 至 \`vendor/icons/\`，注册表 \`icons.js\`）；
- 渲染：内联注入 \`<span class="icn" data-icon="x">\`（静态）或 \`'<span class="icn">' + ICONS.x + '</span>'\`（动态）；
- 尺寸：常规 15px（\`.icn\`），品牌 20px（\`.icn.lg\`）；SVG 内 \`width/height\` 属性必须被 CSS 覆盖（\`.icn svg{width/height:100%}\`）；
- 禁止：emoji、私用区符号、文本箭头（◀▶⇄✦¶↶）充当图标。

### 2.3 表单控件

- 下拉（\`select\`）：高 28px，input-bg 底、border 描边、13px；
- 单选/开关（页面划分等）：复用工具按钮规范。

### 2.4 文本层级

| 用途 | 字号 | 颜色变量 |
| --- | --- | --- |
| 品牌名 | 18px / 600 | \`--text\` |
| 面板标题 | 14px | \`--text-dim\` |
| 正文/编辑器 | 15px / 行高 1.8 | \`--text\` |
| 控件文字 | 13px | 随按钮 |
| 辅助文本（状态/提示/diff 原因） | 12px（\`--font-aux\`） | \`--text-dim\` |

### 2.5 工具区（toolbar / 动作条 / 导出）

- 第 1 行：Quill 格式工具栏（标题/加粗斜体下划线删除线/颜色/列表/缩进/对齐/清除格式）；
- 第 2 行：**分类动作条**（\`.export-bar\`，\`--toolbar-bg\`，不设 border-top）——组标签 + 1px 分隔线，按类别排列：**校对**（标点修复/选区标点修复/段落修复/撤销修复/拼写检查）｜**识别**（特殊格式识别）｜**检索**（查找/替换）｜**视图**（页面划分）｜右侧**导出**（唯一强调色主按钮）；
- **导出**：单按钮，点击弹出格式菜单（docx/txt/pdf/md/xlsx，各带用途说明），点选后保存编辑并导出，点击菜单外自动收起；
- 换行策略：\`flex-wrap:wrap\`、高度自适应，任何宽度下按钮不得裁剪或重叠（conformance 检查 800–1680px）。

### 2.6 反馈

- 加载：顶栏进度条（高 8px，圆角 4px，accent 填充）+ 文案「识别中… x / y 页」；
- 轻提示（toast）：**顶部居中**（`#toastBox` top:64px），3.2s 自动消失，左缘色条区分 ok/err；**侧边栏不再承担状态文案**，状态一律走 toast 或顶栏 jobStatus；
- 结果：diff 面板（绿增/红删/灰原因）；空态：面板居中 12px 灰文案；错误：红色 `#e74c3c`（两主题通用）。

### 2.7 安全水印与标注

- **预览防截图水印**：预览页整页平铺斜纹水印（口号 + 时间戳 + 页码，**浅灰** 30% 透明），随翻页/30s 刷新；**导出水印功能已删除**，导出无任何附加水印；
- 跑马安全横幅：红字（`--danger`）加粗、浅红底；
- **标注**：进入标注模式后在预览上方展开内嵌工具条（逻辑顺序：标题 → 策略分段「跳过选区/仅识别选区」（分段控件不挤压、文字不换行）→ 应用到全部页 → 实时提示（已画 N 个框）→ 动作「应用/清除/完成」）；拖拽框选，**点击已画框即删除**；**局部识别（表格/公式）不在面板里**，而是挂在最后一个框右上角的浮钮「识别该区域」上——识别动作跟着对象走；
- 预览缩放：**真实宽度缩放**（改 `img.style.width`，禁用 transform——transform 不改布局尺寸会导致视觉错位、空白滚动区与标注错位）；适应屏幕 = 可视区宽高取最小比（图片未就绪时挂起待 onload 应用）；缩放按钮纯「−」「+」定宽符号，无图标；
- 任务栏：纯文字卡片（文件名 + 页数 + 悬停删除），**不使用文件图标**；无任务时显示导入空态提示。

## 3. 布局与响应式

- 三栏：左 190px 任务栏（可**收纳**——标题栏按钮收起为 0，左缘把手展开，宽度记忆持久化）、中预览、右自适应编辑器；**导入按钮位于任务栏顶部**（顶栏只留品牌/进度/主题）；
- 任务卡：文件名 + 页数 + 悬停操作（**重新识别** / 删除），无文件图标；
- 断点行为：动作条允许换行（按钮不缩放、不裁剪）；预览栏/任务栏均可折叠；
- 所有栏内容 overflow 策略：\`auto\` 滚动，禁止横向溢出；**全局滚动条定制**（细圆角、主题色、悬停加深）。

## 4. 设计令牌（CSS 变量）

\`\`\`css
:root { /* light 默认 */
  --bg / --panel / --border / --text / --text-dim / --accent / --ok / --warn
  --editor-bg / --toolbar-bg / --input-bg / --proj-bg / --diff-bg / --shadow
  --ctrl-font:13px; --font-aux:12px; --ctrl-h:28px;
  --radius-s:4px; --radius-m:6px;
  --space-1:4px; --space-2:8px; --space-3:12px; --space-4:16px;
}
body[data-theme="dark"] { /* 同名覆盖 */ }
\`\`\`

对比度门槛：正文 ≥ 7:1（WCAG AAA），辅助文本 ≥ 4.5:1（AA）。

## 5. Quill 定制（已知陷阱清单）

1. snow 主题会把工具栏内**所有 \`button\`** 强制 28×24 图标尺寸 → 自定义按钮必须用
   \`#toolbar .repair-group button { width/height:auto !important }\` 级选择器覆盖；
2. 工具栏内 \`<select>\` 会被 Quill 接管成 picker → 自定义下拉必须放在工具栏容器之外；
3. Quill 2 \`getLines()\` 返回 **Line 对象数组**（offset 经 \`line.offset()\`），不是 \`[line, offset]\` 对；
4. 自定义 Block Embed 注册必须用 class 语法 + \`Quill.register({"formats/<name>": Blot}, true)\`；
5. 编辑器颜色经 \`--editor-bg/--text\` 适配主题，picker 选项面板用 \`--panel\`。

## 6. 资源与许可登记

| 资源 | 版本 | 许可 | 位置 |
| --- | --- | --- | --- |
| Quill | 2.0.3 | BSD-3-Clause | \`vendor/quill.js\`、\`vendor/quill.snow.css\` |
| Lucide icons | 1.31.0 | ISC | \`vendor/icons/*.svg\` → \`icons.js\` |
| 新增第三方资源 | — | 必须登记于此并本地化 | \`vendor/\` |

## 7. 质量门槛（conformance 自动检查）

- [ ] 800/1000/1200/1366/1680px 五档宽度下：所有交互控件两两无几何重叠，工具栏与导出栏垂直不相交；
- [ ] 全部自定义控件 computed \`font-size\` == 13px，\`height\` == 28px；
- [ ] 全部 \`.icn\` 内 SVG 尺寸 == 15px（lg == 20px），\`stroke="currentColor"\`；
- [ ] 界面文本/按钮无 emoji 与符号字符（正则断言）；
- [ ] 点击「页面划分」「明暗切换」前后按钮几何尺寸变化 < 2px（尺寸稳定性）；
- [ ] 明暗两主题下抽查关键色对比度 ≥ 4.5:1；
- [ ] 全部既有回归（UI 全流程 / 五项验收 / pytest）通过。

## 8. 变更流程

1. 改 UI → 本地起服务（\`mdun serve\`）→ 跑 \`tests/ui_conformance.py\`；
2. 不满足条款 → 修 CSS/结构直至通过；
3. 涉及新第三方资源 → 先完成 §6 登记；
4. 提交时附 conformance 输出。
