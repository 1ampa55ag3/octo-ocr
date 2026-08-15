"""文档输入：PDF/图片加载、电子文字层分流（FR-1.1/1.2/1.5）。

- 扫描 PDF（图像型）→ 渲染为图像走识别管线；
- 电子 PDF（含文字层）→ 直取文字，跳过识别，仅做修复；
- 混合 PDF → 按页自动分流。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".heic"}

MIN_TEXT_LAYER_CHARS = 20  # 每页文字层字符数阈值，低于则视为扫描页
MAX_IMAGE_COVER_FOR_TEXT = 0.25  # 页内嵌图片覆盖面积阈值：超过则整页走 OCR（混合页不丢图片文字）


@dataclass
class PageInput:
    index: int
    kind: str                      # "image" | "text"
    image: np.ndarray | None = None
    text: str | None = None
    width: float = 0
    height: float = 0
    source: str = ""

    @property
    def is_digital(self) -> bool:
        return self.kind == "text"


def _page_image_coverage(page) -> float:
    """页面内嵌图片（扫描图/大图）覆盖面积占比，用于混合页分流。"""
    try:
        rect = page.rect
        area = max(float(rect.width * rect.height), 1.0)
        covered = 0.0
        for img in page.get_images(full=True):
            try:
                for r in page.get_image_rects(img[0]):
                    covered += float(r.width * r.height)
            except Exception:  # noqa: BLE001
                continue
        return min(covered / area, 1.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _render_pdf_page(page, dpi: int = 200) -> np.ndarray:
    import pymupdf  # fitz 兼容

    zoom = dpi / 72.0
    mat = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if img.shape[2] == 4:
        img = img[:, :, :3]
    return img.copy()


def iter_pages(path: str | Path, dpi: int = 200):
    """逐页加载（生成器）：大文件内存有界——每页图像用完即弃。

    - PDF：逐页渲染（扫描页）或直取文字层（电子页）；
    - 图片：单页。
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".pdf":
        import pymupdf

        doc = pymupdf.open(str(path))
        try:
            for i, page in enumerate(doc):
                txt = page.get_text("text").strip()
                r = page.rect
                # 电子页判定：有文字层 且 页内无大面积嵌图（混合页整页走 OCR，图片文字不丢失）
                if len(txt) >= MIN_TEXT_LAYER_CHARS and _page_image_coverage(page) < MAX_IMAGE_COVER_FOR_TEXT:
                    yield PageInput(i, "text", text=txt, width=r.width, height=r.height, source=str(path))
                else:
                    yield PageInput(i, "image", image=_render_pdf_page(page, dpi), width=r.width, height=r.height, source=str(path))
        finally:
            doc.close()
    elif ext in IMAGE_EXTS:
        from PIL import Image

        with Image.open(path) as im:
            arr = np.asarray(im.convert("RGB"))
        yield PageInput(0, "image", image=arr, width=arr.shape[1], height=arr.shape[0], source=str(path))
    else:
        raise ValueError(f"不支持的输入格式: {ext}（支持 PDF/JPG/PNG/TIFF/BMP/WebP/HEIC）")


def load_pages(path: str | Path, dpi: int = 200) -> list[PageInput]:
    """加载全部页（小文件/测试用）。大文件请用 iter_pages 流式处理。"""
    return list(iter_pages(path, dpi=dpi))

def render_single_page(path: str | Path, page_index: int, dpi: int = 200) -> np.ndarray | None:
    """渲染单页为 RGB ndarray（数字页的表格/公式区域识别用）。"""
    import pymupdf

    if not str(path).lower().endswith(".pdf"):
        return None
    doc = pymupdf.open(str(path))
    try:
        if page_index >= len(doc):
            return None
        page = doc[page_index]
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        return img[:, :, :3].copy()
    finally:
        doc.close()


def extract_text_lines(path: str | Path, page_index: int) -> list[tuple[str, float, float, float, float]]:
    """提取 PDF 文字层行（含坐标），用于剔除表格区域内的文字层文本。"""
    import pymupdf

    if not str(path).lower().endswith(".pdf"):
        return []
    doc = pymupdf.open(str(path))
    try:
        if page_index >= len(doc):
            return []
        out: list[tuple[str, float, float, float, float]] = []
        d = doc[page_index].get_text("dict")
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                if not text:
                    continue
                b = line["bbox"]
                out.append((text, b[0], b[1], b[2], b[3]))
        return out
    finally:
        doc.close()
