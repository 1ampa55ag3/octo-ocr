"""导出：双层 PDF（可搜索，FR-6.1）。

- 文字层不可见（render_mode=3），版式保持原始图像；
- 支持"纯文字版"（无原图，仅文字）；
- 输入为源文件 + 项目文本（每页）。
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

CJK_FONT = "china-s"  # pymupdf 内置简体中文字体


def _insert_text_layer(page, text: str, visible: bool) -> None:
    if not text.strip():
        return
    rect = page.rect
    margin = 6
    rect = pymupdf.Rect(rect.x0 + margin, rect.y0 + margin, rect.x1 - margin, rect.y1 - margin)
    if visible:
        page.insert_textbox(rect, text, fontname=CJK_FONT, fontsize=11, color=(0, 0, 0))
    else:
        page.insert_textbox(rect, text, fontname=CJK_FONT, fontsize=4, render_mode=3, color=(1, 1, 1))


def _stamp_watermark(page, text: str, ts: str) -> None:
    """时间戳防伪水印：斜向平铺半透明文字 + 时间戳（morph 自由角度旋转）。"""
    stamp = f"{text} · {ts}"
    r = page.rect
    color = (0.55, 0.55, 0.55)
    mat = pymupdf.Matrix(1, 1).prerotate(30)
    for x in range(0, int(r.width), 340):
        for y in range(0, int(r.height), 220):
            pt = pymupdf.Point(x, y)
            page.insert_text(
                pt, stamp,
                fontsize=10, color=color, morph=(pt, mat), overlay=True,
                fontname="china-s",
            )


def export_searchable_pdf(
    source: str | Path,
    out: str | Path,
    page_texts: list[str],
    visible_text: bool = False,
    original_images: list[Path | str] | None = None,
    watermark_text: str | None = None,
) -> Path:
    """导出可搜索 PDF（可选时间戳防伪水印）。

    - source 为 PDF：保留原页面，叠加文字层；
    - source 为图片（或 original_images 提供）：新建 PDF，插图 + 文字层；
    - watermark_text：平铺水印文字（如"内部资料"），并附时间戳。
    """
    import time

    source = Path(source)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    if source.suffix.lower() == ".pdf":
        doc = pymupdf.open(str(source))
        try:
            for i, page in enumerate(doc):
                if i < len(page_texts):
                    _insert_text_layer(page, page_texts[i], visible_text)
                if watermark_text:
                    _stamp_watermark(page, watermark_text, ts)
            doc.save(str(out), garbage=3, deflate=True)
        finally:
            doc.close()
    else:
        imgs = original_images or [source]
        doc = pymupdf.open()
        try:
            for i, img in enumerate(imgs):
                page = doc.new_page(width=page_width(img), height=page_height(img))
                page.insert_image(page.rect, filename=str(img))
                if i < len(page_texts):
                    _insert_text_layer(page, page_texts[i], visible_text)
                if watermark_text:
                    _stamp_watermark(page, watermark_text, ts)
            doc.save(str(out), garbage=3, deflate=True)
        finally:
            doc.close()
    return out


def page_width(img: Path | str) -> float:
    import pymupdf as m

    d = m.open(str(img))
    try:
        return d[0].rect.width
    finally:
        d.close()


def page_height(img: Path | str) -> float:
    import pymupdf as m

    d = m.open(str(img))
    try:
        return d[0].rect.height
    finally:
        d.close()
