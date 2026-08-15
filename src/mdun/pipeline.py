"""识别-修复-导出编排管线。

流程：load_pages → （电子页直取 / 扫描页 OCR）→ 版面分块 → 段落聚合
     → 标点修复（规则 + 模型）→ 段落快捷修复（页眉页脚删除、版式统一）→ Project。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from mdun.config import Settings
from mdun.ocr import OcrEngine, PageOcrResult, group_lines_to_blocks, blocks_to_ordered_lines, iter_pages
from mdun.postprocess import (
    Line,
    Para,
    merge_lines,
    remove_headers_footers,
    normalize_layout,
    repair_punctuation,
)
from mdun.postprocess.punc_model import PuncRestorer
from mdun.postprocess.punctuation import RuleConfig
from mdun.ocr.region import TABLE_CLASSES, FORMULA_CLASSES
from mdun.security.auditlog import AuditLog
import logging

log = logging.getLogger("mdun.pipeline")


@dataclass
class ParaOut:
    kind: str
    text: str
    box: tuple[float, float, float, float] = (0, 0, 0, 0)


@dataclass
class PageData:
    index: int
    kind: str                 # image | text
    text: str = ""
    paras: list[ParaOut] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)     # 表格块 {box, rows, html, source}
    formulas: list[dict] = field(default_factory=list)   # 公式块 {box, latex, score, source}
    punc_edits: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    conf_avg: float = 0.0
    seconds: float = 0.0
    width: float = 0.0      # 页面坐标宽（数字页=PDF点；扫描页=渲染像素）
    height: float = 0.0
    ignore_regions: list[dict] = field(default_factory=list)  # 归一化忽略区域 [{x0,y0,x1,y1}]
    low_conf: list[dict] = field(default_factory=list)        # 低置信行 [{text, box, conf}]
    seals: list[dict] = field(default_factory=list)           # 检出的印章区域 [{box, conf}]


@dataclass
class Project:
    source: str
    engine_note: str
    pages: list[PageData] = field(default_factory=list)
    created_at: str = ""

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)


class Pipeline:
    def __init__(self, settings: Settings, audit: AuditLog | None = None):
        self.settings = settings
        self.audit = audit
        self.engine = OcrEngine(settings.models_dir, num_threads=settings.num_threads)
        self.restorer = PuncRestorer(settings.models_dir / "ct_punc_zh.onnx")
        # 区域引擎（模型存在则可用；表格/公式按需加载）
        from mdun.ocr.region import LayoutEngine, TableEngine, FormulaEngine

        self._coarse = False
        self.layout_engine = LayoutEngine(settings.models_dir / "layout_cdla.onnx")
        self.table_engine = TableEngine(settings.models_dir / "slanet_plus.onnx",
                                         fallback_model_path=settings.models_dir / "slanet_zh.onnx")
        self.formula_engine = FormulaEngine(settings.models_dir)

    def process(self, path: str | Path, dpi: int = 200, use_punc_model: bool = True,
                repair_punc: bool = True, repair_para: bool = True,
                on_progress=None, cancel=None, coarse: bool = False) -> Project:
        """流式处理：逐页渲染→识别→释放，内存有界。

        - on_progress(done, total, page_index, kind)：进度回调；
        - cancel() -> bool：返回 True 时抛 ProcessingCancelled。
        """
        path = str(path)
        name = Path(path).name
        if coarse:
            dpi = 150
            use_punc_model = False
            repair_punc = False
            repair_para = False
        if self.audit:
            self.audit.import_file(name)
        t0 = time.time()
        self._coarse = coarse
        project = Project(source=path, engine_note=self.engine.model_note,
                          created_at=time.strftime("%Y-%m-%dT%H:%M:%S"))

        # 流式逐页：每页图像处理完即释放（大文件内存有界）
        total = _count_pages(path)
        done = 0
        for pin in iter_pages(path, dpi=dpi):
            if cancel is not None and cancel():
                project.pages.clear()
                raise ProcessingCancelled(f"处理已取消（第 {done}/{total} 页）")
            pd = self._process_page(pin)
            project.pages.append(pd)
            done += 1
            if on_progress:
                on_progress(done, total, pd.index, pin.kind)
            if pin.image is not None:
                del pin.image  # 显式释放大数组

        if repair_punc:
            self._repair_punctuation(project, use_punc_model)
        if repair_para:
            self._repair_paragraphs(project)

        for p in project.pages:
            p.seconds = round((time.time() - t0) / max(len(project.pages), 1), 3)
        if self.audit:
            self.audit.ocr_done(name, len(project.pages), time.time() - t0)
        return project

    LOW_CONF_THRESHOLD = 0.55  # 行置信度低于此值标记为「可能认错」

    @staticmethod
    def _remove_seals(img):
        """红色圆形印章检测：检出的印章区域涂白，OCR 不再读取（红头文字条状、低圆度，不受影响）。"""
        import cv2

        h, w = img.shape[:2]
        b = img[..., 0].astype(int)
        g = img[..., 1].astype(int)
        r = img[..., 2].astype(int)   # OpenCV BGR：红色在第 2 通道
        red = ((r - np.maximum(g, b)) > 50) & (r > 110)
        mask = (red.astype(np.uint8)) * 255
        if int(mask.sum()) == 0:
            return img, []
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        seals = []
        for c in contours:
            x, y, cw, ch = cv2.boundingRect(c)
            area = float(cv2.contourArea(c))
            if not (300 <= area <= 500_000):
                continue
            if cw < 16 or ch < 16:
                continue
            if max(cw, ch) / max(1, min(cw, ch)) > 1.6:   # 条状红字（红头标题/文号）排除
                continue
            per = cv2.arcLength(c, True)
            circ = 4 * 3.14159 * area / max(1.0, per * per)   # 圆度
            fill = float(cv2.countNonZero(mask[y:y + ch, x:x + cw])) / max(1.0, float(cw * ch))
            if circ < 0.40 or fill < 0.30:
                continue
            seals.append({"box": [int(x), int(y), int(x + cw), int(y + ch)], "conf": round(min(1.0, circ), 3)})
            img[y:y + ch, x:x + cw] = 255
        return img, seals

    def _process_page(self, pin) -> PageData:
        """处理单页（流式管线的最小单元，可被并行调度复用）。"""
        pd = PageData(index=pin.index, kind=pin.kind, width=pin.width, height=pin.height)
        if pin.is_digital:
            pd.text = pin.text or ""
            pd.paras = self._paras_from_text(pd.text)
        else:
            if pin.image is not None:
                pin.image, pd.seals = self._remove_seals(pin.image)
            lines, _ = self.engine.recognize(pin.image)
            if lines:
                blocks = group_lines_to_blocks(lines, pin.width, pin.height)
                ordered = blocks_to_ordered_lines(blocks)
                paras = merge_lines(ordered, block_width=pin.width)
                pd.conf_avg = sum(l.conf for l in lines) / len(lines)
                pd.text = "\n\n".join(p.text for p in paras)
                pd.paras = [self._para_out(p, blocks) for p in paras]
                pd.low_conf = [
                    {"text": l.text, "box": [round(l.x0, 1), round(l.y0, 1), round(l.x1, 1), round(l.y1, 1)], "conf": round(l.conf, 3)}
                    for l in lines if l.conf < self.LOW_CONF_THRESHOLD and l.text.strip()
                ]
        if not self._coarse:
            self._process_regions(pd, pin)
        return pd

    # ---- 区域路由：表格 / 公式（模型协作架构 §2）----

    @staticmethod
    def _inside(box: tuple, lx: float, ly: float) -> bool:
        x0, y0, x1, y1 = box
        return x0 <= lx <= x1 and y0 <= ly <= y1

    def _process_regions(self, pd: PageData, pin) -> None:
        """版面分析 → 表格结构识别 + 单元格 OCR；公式识别；剔除区域内的散行。

        数字版 PDF（有文字层）同样渲染图像执行区域识别——否则表格完全漏检。
        """
        if not self.layout_engine.available:
            return
        if pin.image is None:
            from mdun.ocr.document import render_single_page

            pin.image = render_single_page(pin.source, pin.index, dpi=300)
            if pin.image is None:
                return
            pin.width = pin.image.shape[1]
            pin.height = pin.image.shape[0]
        regions = self.layout_engine.predict(pin.image)
        if not regions:
            return
        # 类别阈值：低置信/超大区域（覆盖 >85% 页面）视为版面误报，不进入特殊管线
        page_area = pin.width * pin.height
        trial_formulas: set = set()
        table_regions = [
            r for r in regions
            if r.type in TABLE_CLASSES and r.score >= 0.4
            and (r.box[2] - r.box[0]) * (r.box[3] - r.box[1]) < page_area * 0.85
        ]
        formula_regions = [
            r for r in regions
            if r.type in FORMULA_CLASSES and r.score >= 0.5
            and (r.box[2] - r.box[0]) * (r.box[3] - r.box[1]) < page_area * 0.85
        ]
        # 孤立 figure 区域（版面模型把独立公式判为 figure）→ 试识别 + 输出自校验
        for r in regions:
            if r.type != "figure" or r.score < 0.6:
                continue
            formula_regions.append(r)
            trial_formulas.add(tuple(r.box))
        if not table_regions and not formula_regions:
            return

        # 表格：结构 → 单元格裁切 → 批量识别 → 行列矩阵
        if table_regions and self.table_engine.available:
            for r in table_regions:
                x0, y0, x1, y1 = r.box
                crop = pin.image[max(0, y0):y1, max(0, x0):x1]
                if crop.size == 0:
                    continue
                try:
                    crops, idx = self.table_engine.cell_crops(crop)
                    texts = self.engine.recognize_crops(crops)
                    n_rows = max((i for i, _ in idx), default=-1) + 1
                    n_cols = max((j for _, j in idx), default=-1) + 1
                    rows = [[""] * n_cols for _ in range(max(n_rows, 1))]
                    for (ri, ci), t in zip(idx, texts):
                        if 0 <= ri < len(rows) and 0 <= ci < n_cols:
                            rows[ri][ci] = (rows[ri][ci] + " " + t).strip()
                    if n_cols <= 1:
                        continue  # 单列结构多半是版面误报（整段文本被当表格）
                    if n_rows == 1 and n_cols >= 3 and max(len(c) for c in rows[0]) <= 3:
                        continue  # 单行且各列极短 → 标题行被切碎的伪表格
                    if sum(len(c) for r in rows for c in r) < 20:
                        continue  # 总字符过少 → 伪表格（标题/短行被误判）
                    pd.tables.append({
                        "box": [int(v) for v in r.box], "rows": rows,
                        "html": "", "source": "slanet_plus", "score": round(r.score, 3),
                    })
                except Exception as e:  # noqa: BLE001
                    log.warning("表格识别失败 %s: %s", r.box, e)

        # 公式：区域裁切 → LaTeX
        if formula_regions and self.formula_engine.available:
            for r in formula_regions:
                x0, y0, x1, y1 = r.box
                crop = pin.image[max(0, y0):y1, max(0, x0):x1]
                if crop.size == 0:
                    continue
                try:
                    f = self.formula_engine.recognize(crop, r.box)
                    if tuple(r.box) in trial_formulas and not _sane_latex(f.latex):
                        continue  # 试识别不合法 → 视为普通图片，丢弃
                    pd.formulas.append({
                        "box": [int(v) for v in r.box], "latex": f.latex,
                        "score": round(f.score, 3), "source": f.source,
                    })
                except Exception as e:  # noqa: BLE001
                    log.warning("公式识别失败 %s: %s", r.box, e)

        # 剔除落入表格/公式区域的正文散行，避免重复内容
        skip_boxes = [tuple(t["box"]) for t in pd.tables] + [tuple(f["box"]) for f in pd.formulas]
        if skip_boxes:
            if pd.kind == "text":
                # 数字页：用文字层行坐标精确剔除表格/公式覆盖区域
                from mdun.ocr.document import extract_text_lines

                lines = extract_text_lines(pin.source, pin.index)
                sx = pin.width / max(pin.width, 1)
                kept_lines = []
                for text, x0, y0, x1, y1 in lines:
                    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                    # 文字层坐标为 PDF 点（72dpi），渲染图为 200dpi → 等比缩放
                    kx = pin.width / 612 if pin.width else 1
                    ky = pin.height / 792 if pin.height else 1
                    if any(self._inside((b[0] * kx, b[1] * ky, b[2] * kx, b[3] * ky), cx * kx, cy * ky) for b in skip_boxes):
                        continue
                    kept_lines.append(text)
                # 按相邻行聚合为段落
                paras = []
                buf = []
                for ln in kept_lines:
                    buf.append(ln)
                if kept_lines:
                    pd.paras = [ParaOut(kind="text", text="\n".join(kept_lines))]
                    pd.text = "\n".join(kept_lines)
                # 空则回退原文，避免整页内容丢失
            else:
                kept = []
                for para in pd.paras:
                    cx = (para.box[0] + para.box[2]) / 2
                    cy = (para.box[1] + para.box[3]) / 2
                    if any(self._inside(b, cx, cy) for b in skip_boxes):
                        continue
                    kept.append(para)
                pd.paras = kept
                pd.text = "\n\n".join(p.text for p in kept)

    # ---- 内部 ----

    @staticmethod
    def _paras_from_text(text: str) -> list[ParaOut]:
        paras: list[ParaOut] = []
        for chunk in text.split("\n"):
            c = chunk.strip()
            if c:
                paras.append(ParaOut(kind="text", text=c))
        return paras

    def _para_out(self, para: Para, blocks) -> ParaOut:
        text = para.text.strip()
        kind = "text"
        for b in blocks:
            if b.text.strip() == text:
                kind = b.kind
                break
        return ParaOut(kind=kind, text=text, box=para.box)

    def _repair_punctuation(self, project: Project, use_model: bool) -> None:
        for p in project.pages:
            text = p.text
            if use_model and self.restorer.available:
                # 模型层：仅对"完全无标点"的正文段补标点（ct-punc 为 ASR 模型，需严格限用）
                fixed = []
                for para in p.paras:
                    t = para.text
                    if (
                        para.kind == "text"
                        and len(t) > 8
                        and not any(c in t for c in "，。！？；：、,.!?;:")
                    ):
                        try:
                            out_t = self.restorer.restore(t)
                            if self._model_output_ok(t, out_t):
                                t = self._clean_model_output(out_t)
                        except Exception:  # noqa: BLE001
                            pass
                    fixed.append(t)
                text = "\n\n".join(fixed)
            # 段落跨度基于最终文本计算（模型层可能改变文本长度）
            para_spans: list[tuple[str, int, int]] = []
            pos = 0
            for para in p.paras:
                t = para.text.strip()
                if t:
                    i = text.find(t, pos)
                    if i >= 0:
                        para_spans.append((para.kind, i, i + len(t)))
                        pos = i + len(t)
            new_text, edits = repair_punctuation(text)  # fix_ends 默认关闭：不擅自补句号
            # 过滤非正文段内的编辑（页眉页脚/页码/标题不自动补标点）
            kept_edits = []
            for e in edits:
                in_body = True
                for kind, s, end in para_spans:
                    # 覆盖段落末尾的插入（start==end 的边界插入）
                    if s <= e.start < end or (e.start == e.end and e.start == end):
                        in_body = kind == "text"
                        break
                if in_body or e.new != "。":
                    kept_edits.append(e)
            # 仅应用保留的编辑（非正文段的"补句号"等编辑同时从文本与报告中剔除）
            from mdun.postprocess.punctuation import apply_edits

            final_text = apply_edits(text, kept_edits)
            p.punc_edits = [
                {"start": e.start, "end": e.end, "old": e.old, "new": e.new, "reason": e.reason}
                for e in kept_edits
            ]
            p.text = final_text
            if kept_edits and self.audit:
                self.audit.repair(Path(project.source).name, "punctuation", len(kept_edits))

    @staticmethod
    def _model_output_ok(src: str, out: str) -> bool:
        """ct-punc 输出结构校验：数字不得丢失、CJK 字数变化 ≤ 15%。"""
        src_digits = [c for c in src if c.isdigit()]
        out_digits = [c for c in out if c.isdigit()]
        for d in set(src_digits):
            if src_digits.count(d) > out_digits.count(d):
                return False
        src_cjk = sum(1 for c in src if "\u4e00" <= c <= "\u9fff")
        out_cjk = sum(1 for c in out if "\u4e00" <= c <= "\u9fff")
        return src_cjk > 0 and abs(out_cjk - src_cjk) / src_cjk <= 0.15

    @staticmethod
    def _clean_model_output(text: str) -> str:
        """清理 ct-punc 输出中的标点两侧空格与多余空白。"""
        import re

        text = re.sub(r"\s*([，。！？；：、])\s*", r"\1", text)
        return text.strip()

    def _repair_paragraphs(self, project: Project) -> None:
        pages_texts = [p.text for p in project.pages]
        cleaned, removals = remove_headers_footers([t.split("\n") for t in pages_texts])
        for i, p in enumerate(project.pages):
            p.removed = [{"text": r["text"], "reason": r["reason"]} for r in removals if r["page"] in (i, -1)]
            joined = "\n".join(cleaned[i]) if i < len(cleaned) else p.text
            p.text = normalize_layout(joined)
            # 重建段落时保留原坐标（供忽略区域/表格按坐标过滤）
            old_by_text: dict[str, tuple] = {}
            for para in p.paras:
                t = para.text.strip()
                if t and t not in old_by_text:
                    old_by_text[t] = para.box
            new_paras: list[ParaOut] = []
            for chunk in p.text.split("\n"):
                c = chunk.strip()
                if not c:
                    continue
                box: tuple = (0, 0, 0, 0)
                for t, b in old_by_text.items():
                    if t and t in c:
                        box = b
                        break
                new_paras.append(ParaOut(kind="text", text=c, box=box))
            p.paras = new_paras

class ProcessingCancelled(Exception):
    """处理被用户取消。"""


def _count_pages(path: str) -> int:
    import pymupdf

    if path.lower().endswith(".pdf"):
        doc = pymupdf.open(path)
        try:
            return len(doc)
        finally:
            doc.close()
    return 1


def _sane_latex(text: str) -> bool:
    """LaTeX 输出合法性校验：含数学符号、长度合理、无中文、无非法字符。"""
    import re

    if not text or len(text) < 2 or len(text) > 300:
        return False
    if re.search(r"[\u4e00-\u9fff]", text):
        return False
    if not re.search(r"[a-zA-Z0-9\^\{\}=+*/_\-]", text):
        return False
    if re.search(r"[<>&]", text):
        return False
    return True