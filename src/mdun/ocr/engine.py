"""识别引擎（完全离线）。

- 标准档：PP-OCRv5（优先）或内置 PP-OCRv4（RapidOCR 运行时）；
- 模型从本地目录加载，无任何网络请求。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np

from mdun.postprocess.paragraph import Line

# 模型文件名约定（scripts/download_models.sh 下载到 data_dir/models/）
MODEL_FILES = {
    "fast_det": "ppocrv5_mobile_det.onnx",
    "fast_rec": "ppocrv5_mobile_rec.onnx",
    "cls": "ppocrv4_mobile_cls.onnx",
    "punc": "ct_punc_zh.onnx",
}


@dataclass
class PageOcrResult:
    index: int
    lines: list[Line] = field(default_factory=list)
    text: str = ""
    engine: str = "ppocrv5"
    seconds: float = 0.0
    conf_avg: float = 0.0
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "engine": self.engine,
            "seconds": round(self.seconds, 3),
            "conf_avg": round(self.conf_avg, 4),
            "lines": [
                {"text": l.text, "box": [round(v, 1) for v in (l.x0, l.y0, l.x1, l.y1)], "conf": round(l.conf, 4), "block": l.block_id}
                for l in self.lines
            ],
            "note": self.note,
        }


class OcrEngine:
    """主识别引擎：RapidOCR 运行时 + PP-OCRv5/v4 模型。"""

    def __init__(self, models_dir: str | Path, num_threads: int = 0, prefer_v5: bool = True):
        self.models_dir = Path(models_dir)
        self.num_threads = num_threads
        self._engine = None
        self._model_note = ""
        self._load_rapidocr()

    def _has(self, key: str) -> Path | None:
        p = self.models_dir / MODEL_FILES[key]
        return p if p.exists() else None

    def _ensure_v5_keys(self) -> Path | None:
        """从 PaddleX inference.yml 提取 PP-OCRv5 字典，写入 keys 文件。"""
        import yaml

        yml = self.models_dir / "ppocrv5_rec_inference.yml"
        keys_file = self.models_dir / "ppocrv5_keys.txt"
        if keys_file.exists():
            return keys_file
        if not yml.exists():
            return None
        d = yaml.safe_load(yml.read_text(encoding="utf-8"))
        chars = d.get("PostProcess", {}).get("character_dict")
        if not chars:
            return None
        keys_file.write_text("\n".join(chars), encoding="utf-8")
        return keys_file

    def _load_rapidocr(self) -> None:
        from rapidocr_onnxruntime import RapidOCR

        kwargs: dict = {}
        det = self._has("fast_det")
        rec = self._has("fast_rec")
        cls = self._has("cls")
        if det:
            kwargs["det_model_path"] = str(det)
            # PP-OCRv5 det 官方预处理/后处理参数（PaddleX inference.yml）
            kwargs.update(
                det_limit_side_len=960,
                det_limit_type="max",
                det_mean=[0.485, 0.456, 0.406],
                det_std=[0.229, 0.224, 0.225],
                det_box_thresh=0.6,
                det_unclip_ratio=1.5,
                det_donot_use_dilation=True,
            )
        if rec:
            kwargs["rec_model_path"] = str(rec)
            keys = self._ensure_v5_keys()
            if keys:
                # rapidocr 参数映射：rec_ 前缀不做拆分，直接传 rec_keys_path
                kwargs["rec_keys_path"] = str(keys)
        if cls:
            kwargs["cls_model_path"] = str(cls)
        if self.num_threads > 0:
            kwargs.update(
                det_intra_op_num_threads=self.num_threads,
                det_inter_op_num_threads=self.num_threads,
                rec_intra_op_num_threads=self.num_threads,
                rec_inter_op_num_threads=self.num_threads,
                cls_intra_op_num_threads=self.num_threads,
                cls_inter_op_num_threads=self.num_threads,
            )
        self._engine = RapidOCR(**kwargs)
        self._model_note = "PP-OCRv5(ONNX)" if (det and rec) else "PP-OCRv4(内置)"

    @property
    def model_note(self) -> str:
        return self._model_note

    @staticmethod
    def _split_rows(image: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int, int, int]]:
        """对超高检测框做水平投影分割（检测模型偶尔把紧邻两行合成一框）。"""
        import cv2

        crop = image[max(0, y0):y1, max(0, x0):x1]
        if crop.size == 0 or crop.shape[0] < 20:
            return []
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY) if crop.ndim == 3 else crop
        profile = gray.mean(axis=1)
        thr = profile.mean() * 0.92
        text_rows = profile < thr
        # 找文本带
        bands: list[tuple[int, int]] = []
        in_band = False
        for i, is_text in enumerate(text_rows):
            if is_text and not in_band:
                start, in_band = i, True
            elif not is_text and in_band:
                bands.append((start, i))
                in_band = False
        if in_band:
            bands.append((start, len(profile)))
        bands = [(a, b) for a, b in bands if b - a >= 8]
        if len(bands) < 2:
            return []
        # 相邻文本带间必须有明显空隙
        gaps = [bands[i + 1][0] - bands[i][1] for i in range(len(bands) - 1)]
        if max(gaps) < 6:
            return []
        subs = [(x0, y0 + a - 2, x1, y0 + b + 2) for a, b in bands]
        return [s for s in subs if s[3] - s[1] >= 12]

    def recognize(self, image: np.ndarray, use_cls: bool = True) -> tuple[list[Line], str]:
        """识别单页图像。返回 (文本行列表, 整页文本)。

        对检测出的"超高行"（高 > 1.9 倍行高中位数）做投影分割并逐行重识别，
        修复紧邻两行被检测模型合并的问题。
        """
        t0 = time.time()
        result, _elapse = self._engine(image, use_cls=use_cls)
        raw: list[tuple[list, str, float]] = []
        if result:
            for item in result:
                box, text, score = item[0], item[1], float(item[2])
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                raw.append((box, text, score))

        heights = sorted((max(p[1] for p in b) - min(p[1] for p in b)) for b, _, _ in raw)
        median_h = heights[len(heights) // 2] if heights else 20.0

        lines: list[Line] = []
        for box, text, score in raw:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            if y1 - y0 > median_h * 1.9:
                subs = self._split_rows(image, int(x0), int(y0), int(x1), int(y1))
                if len(subs) >= 2:
                    for sx0, sy0, sx1, sy1 in subs:
                        crop = image[sy0:sy1, sx0:sx1]
                        rec_res, _ = self._engine.text_rec([crop])
                        if rec_res and rec_res[0][0].strip():
                            t, s = rec_res[0]
                            lines.append(Line(text=t, x0=sx0, y0=sy0, x1=sx1, y1=sy1, conf=float(s)))
                    continue
            lines.append(Line(text=text, x0=x0, y0=y0, x1=x1, y1=y1, conf=score))
        lines.sort(key=lambda l: (l.y0, l.x0))
        return lines, "\n".join(l.text for l in lines)

    def recognize_crops(self, crops: list[np.ndarray]) -> list[str]:
        """批量识别裁切小图（表格单元格等），复用同一 rec 会话。"""
        if not crops:
            return []
        texts: list[str] = []
        for i in range(0, len(crops), 6):
            batch = crops[i:i + 6]
            rec_res, _ = self._engine.text_rec(batch)
            for item in rec_res:
                texts.append(item[0] if item else "")
        return texts
