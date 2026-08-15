"""区域识别引擎：版面分析（PP-DocLayout）/ 表格结构（SLANet-plus）/ 公式（LaTeX-OCR）。

- 模型本地路径（models/ 目录），零网络；
- 表格与公式引擎懒加载（页内含对应区域才载入，内存友好）；
- 输出统一 Region/Table/Formula 结构，供 pipeline 路由。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger("mdun.region")

TABLE_CLASSES = {"table", "table_caption", "table_footnote"}
FORMULA_CLASSES = {"formula", "isolate_formula", "formula_caption", "formula_number", "equation"}


@dataclass
class Region:
    type: str                      # 版面类别名（title/text/table/formula/...）
    box: tuple[int, int, int, int]  # x0, y0, x1, y1（页面坐标）
    score: float


@dataclass
class TableResult:
    box: tuple[int, int, int, int]
    rows: list[list[str]] = field(default_factory=list)   # 单元格文本矩阵
    html: str = ""
    source: str = "slanet_plus"


@dataclass
class FormulaResult:
    box: tuple[int, int, int, int]
    latex: str
    score: float = 1.0
    source: str = "latexocr"


class LayoutEngine:
    """版面区域分类（PP-DocLayout v3，ONNX）。"""

    def __init__(self, model_path: str | Path, conf_thresh: float = 0.25, iou_thresh: float = 0.5):
        self.model_path = str(model_path)
        self.conf_thresh = conf_thresh
        self.iou_thresh = iou_thresh
        self._engine = None
        self._engine_low = None
        if Path(self.model_path).exists():
            self._load()

    def _load(self) -> None:
        from rapid_layout import RapidLayout, RapidLayoutInput

        self._engine = RapidLayout(RapidLayoutInput(
            model_dir_or_path=self.model_path,
            conf_thresh=self.conf_thresh,
            iou_thresh=self.iou_thresh,
        ))
        log.info("版面引擎已加载: %s", self.model_path)

    @property
    def available(self) -> bool:
        return self._engine is not None

    def _low_engine(self):
        """低阈值引擎（手动"特殊格式识别"用，捕获弱信号区域）。"""
        if self._engine_low is None:
            from rapid_layout import RapidLayout, RapidLayoutInput

            self._engine_low = RapidLayout(RapidLayoutInput(
                model_dir_or_path=self.model_path,
                conf_thresh=0.12,
                iou_thresh=self.iou_thresh,
            ))
        return self._engine_low

    def predict(self, image: np.ndarray, low: bool = False) -> list[Region]:
        if not self.available:
            return []
        engine = self._low_engine() if low else self._engine
        out = engine(image)
        regions: list[Region] = []
        for box, cls_name, score in zip(out.boxes, out.class_names, out.scores):
            regions.append(Region(type=cls_name, box=(int(box[0]), int(box[1]), int(box[2]), int(box[3])), score=float(score)))
        return regions


class TableEngine:
    """表格结构识别（SLANet-plus 主 + SLANet-zh 回退），输出 HTML 与单元格坐标。"""

    def __init__(self, model_path: str | Path, fallback_model_path: str | Path | None = None,
                 use_ocr: bool = False):
        self.model_path = str(model_path)
        self.fallback_model_path = str(fallback_model_path) if fallback_model_path else None
        self.use_ocr = use_ocr
        self._engine = None
        self._fallback = None
        if Path(self.model_path).exists():
            self._load()

    def _load(self) -> None:
        from rapid_table import RapidTable, RapidTableInput

        self._engine = RapidTable(RapidTableInput(
            model_type="slanet_plus",
            model_dir_or_path=self.model_path,
            use_ocr=self.use_ocr,
        ))
        if self.fallback_model_path and Path(self.fallback_model_path).exists():
            self._fallback = RapidTable(RapidTableInput(
                model_type="ppstructure_zh",
                model_dir_or_path=self.fallback_model_path,
                use_ocr=self.use_ocr,
            ))
            log.info("表格引擎已加载（主 slanet_plus + 回退 ppstructure_zh）")
        else:
            log.info("表格引擎已加载: %s", self.model_path)

    @property
    def available(self) -> bool:
        return self._engine is not None

    def _run(self, engine, crop: np.ndarray):
        return engine(crop)

    def _structure(self, crop: np.ndarray):
        """主引擎优先；结构明显异常（无单元格/列数越界）时回退备用引擎。"""
        out = self._engine(crop)
        cells = out.cell_bboxes[0] if len(out.cell_bboxes) > 0 else []
        points = out.logic_points[0] if len(out.logic_points) > 0 else []
        n_cols = max((int(p[3]) for p in points), default=0) + 1 if len(points) else 0
        if len(cells) == 0 or n_cols < 2 or n_cols > 60:
            if self._fallback is not None:
                out2 = self._fallback(crop)
                cells = out2.cell_bboxes[0] if len(out2.cell_bboxes) > 0 else []
                points = out2.logic_points[0] if len(out2.logic_points) > 0 else []
        return cells, points

    def recognize(self, crop: np.ndarray, box: tuple[int, int, int, int]) -> TableResult:
        """识别表格区域：返回结构矩阵（单元格文本由调用方 OCR 填入）。"""
        if not self.available:
            raise RuntimeError("表格引擎不可用（模型缺失）")
        cells, points = self._structure(crop)
        html = ""

        x0, y0, x1, y1 = box
        n_rows = max((p[0] for p in points), default=-1) + 1
        n_cols = max((p[1] for p in points), default=-1) + 1
        rows: list[list[str]] = [[""] * n_cols for _ in range(max(n_rows, 1))]
        return TableResult(box=box, rows=rows, html=html)

    def cell_crops(self, crop: np.ndarray) -> tuple[list[np.ndarray], list[tuple[int, int]]]:
        """返回单元格裁切列表与 (row, col) 索引。

        策略：bbox 在模型内部坐标系 → 按比例缩放到裁切图空间 → 用相邻列/行
        边界重建完整网格（全格裁剪，避免文本切边）→ 合并单元格（span>0）
        裁剪其并集矩形。
        """
        if not self.available:
            raise RuntimeError("表格引擎不可用")
        cells, points = self._structure(crop)
        if cells is None or len(cells) == 0:
            return [], []

        h, w = crop.shape[:2]
        max_x = max(max(float(v) for v in b[0::2]) for b in cells) or w
        max_y = max(max(float(v) for v in b[1::2]) for b in cells) or h
        sx = w / max_x
        sy = h / max_y

        # 缩放后的单元格矩形；网格归属用 (pt[0], pt[3])（起行/止列），
        # 合并单元格的跨列/跨行范围由 bbox 边界落入的分隔区间反推
        entries: list[tuple[int, int, float, float, float, float]] = []
        for bbox, pt in zip(cells, points):
            xs = [float(v) * sx for v in bbox[0::2]]
            ys = [float(v) * sy for v in bbox[1::2]]
            entries.append((int(pt[0]), int(pt[3]), min(xs), min(ys), max(xs), max(ys)))
        n_rows = max(e[0] for e in entries) + 1
        n_cols = max(e[1] for e in entries) + 1
        if n_cols < 2 or n_cols > 60 or n_rows > 200:
            return [], []

        # 列/行分隔线（相邻边界均值）；entries=(row, col, minx, miny, maxx, maxy)
        col_seps = [0.0]
        for c in range(n_cols - 1):
            rights = [e[4] for e in entries if e[1] == c]
            lefts = [e[2] for e in entries if e[1] == c + 1]
            col_seps.append((max(rights) + min(lefts)) / 2 if rights and lefts else (c + 1) * w / n_cols)
        col_seps.append(float(w))
        row_seps = [0.0]
        for r in range(n_rows - 1):
            bottoms = [e[5] for e in entries if e[0] == r]
            tops = [e[3] for e in entries if e[0] == r + 1]
            row_seps.append((max(bottoms) + min(tops)) / 2 if bottoms and tops else (r + 1) * h / n_rows)
        row_seps.append(float(h))

        def col_of(x: float) -> int:
            for c in range(n_cols):
                if col_seps[c] <= x < col_seps[c + 1]:
                    return c
            return n_cols - 1

        def row_of(y: float) -> int:
            for r in range(n_rows):
                if row_seps[r] <= y < row_seps[r + 1]:
                    return r
            return n_rows - 1

        pad = 2
        col_w = (col_seps[-1] - col_seps[0]) / n_cols
        row_h = (row_seps[-1] - row_seps[0]) / n_rows
        crops: list[np.ndarray] = []
        idx: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for (r0, c0, x0, y0, x1, y1) in entries:
            # 网格身份（pt[0], pt[3]）为主；仅当 bbox 明显跨格（合并单元格）时扩展范围
            c_first, c_last = c0, c0
            if (x1 - x0) > 1.6 * col_w:
                c_first, c_last = col_of(x0), col_of(x1)
            r_first, r_last = r0, r0
            if (y1 - y0) > 1.6 * row_h:
                r_first, r_last = row_of(y0), row_of(y1)
            key = (r_first, c_first)
            if key in seen:
                continue
            seen.add(key)
            cc = crop[max(0, int(row_seps[r_first]) - pad):int(row_seps[r_last + 1]) + pad,
                      max(0, int(col_seps[c_first]) - pad):int(col_seps[c_last + 1]) + pad]
            if cc.size:
                crops.append(cc)
                idx.append(key)
        return crops, idx


class FormulaEngine:
    """公式识别（LaTeX-OCR：ViT 编码 + ResNet 解码 → LaTeX）。"""

    def __init__(self, models_dir: str | Path):
        d = Path(models_dir)
        self.files = {
            "encoder": d / "latexocr_encoder.onnx",
            "decoder": d / "latexocr_decoder.onnx",
            "resizer": d / "latexocr_image_resizer.onnx",
            "tokenizer": d / "latexocr_tokenizer.json",
        }
        self._engine = None
        if all(p.exists() for p in self.files.values()):
            self._load()

    def _load(self) -> None:
        from rapid_latex_ocr import LaTeXOCR

        self._engine = LaTeXOCR(
            encoder_path=str(self.files["encoder"]),
            decoder_path=str(self.files["decoder"]),
            image_resizer_path=str(self.files["resizer"]),
            tokenizer_json=str(self.files["tokenizer"]),
        )
        self._patch_resizer(self._engine)
        log.info("公式引擎已加载")

    @staticmethod
    def _patch_resizer(engine) -> None:
        """修复 rapid_latex_ocr 在 numpy2 下 argmax 维度不兼容的问题。"""
        import types

        import numpy as np
        from PIL import Image

        def loop_image_resizer(self, img: np.ndarray) -> np.ndarray:
            pillow_img = Image.fromarray(img)
            pad_img = self.pre_pro.pad(pillow_img)
            input_image = self.pre_pro.minmax_size(pad_img).convert("RGB")
            r, w, h = 1, input_image.size[0], input_image.size[1]
            for _ in range(10):
                h = int(h * r)
                final_img, pad_img = self.pre_process(input_image, r, w, h)
                resizer_res = self.image_resizer([final_img.astype(np.float32)])[0]
                argmax_idx = int(np.argmax(resizer_res, axis=-1).reshape(-1)[0])
                w = (argmax_idx + 1) * 32
                if w == pad_img.size[0]:
                    break
                r = w / pad_img.size[0]
            return final_img

        engine.loop_image_resizer = types.MethodType(loop_image_resizer, engine)

    @property
    def available(self) -> bool:
        return self._engine is not None

    def recognize(self, crop: np.ndarray, box: tuple[int, int, int, int]) -> FormulaResult:
        if not self.available:
            raise RuntimeError("公式引擎不可用（模型缺失）")
        latex, score = self._engine(crop)
        return FormulaResult(box=box, latex=latex.strip(), score=float(score) if score else 1.0)
