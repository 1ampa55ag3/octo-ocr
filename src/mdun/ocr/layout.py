"""几何版面分析（快速/标准档）：块分组、多栏聚类、阅读顺序、行类别判定。

标准档可选接入 PP-DocLayout 模型（P1，接口见 DocLayoutEngine），
当前默认实现为几何启发式，零额外依赖、全平台可用。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from mdun.postprocess.paragraph import Line

PAGE_NO_RE = re.compile(r"^\s*(?:-\s*)?\d{1,4}(?:\s*-)?\s*$|^第\s*\d+\s*页(?:\s*共\s*\d+\s*页)?$")
HEADING_RE = re.compile(r"^(第[一二三四五六七八九十百千0-9]+[章节条款部篇]|[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）)")


@dataclass
class Block:
    kind: str                     # text | heading | page-number | header-footer | table(预留)
    box: tuple[float, float, float, float]
    lines: list[Line] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(l.text for l in self.lines)


def _cluster_columns(lines: list[Line], page_w: float) -> list[list[Line]]:
    """按 x 重叠把行聚为栏（列）。"""
    cols: list[list[Line]] = []
    for ln in sorted(lines, key=lambda l: (l.x0, l.y0)):
        placed = False
        for col in cols:
            c = col[0]
            ow = min(ln.x1, c.x1) - max(ln.x0, c.x0)
            if ow > 0.35 * min(ln.width, c.width):
                col.append(ln)
                placed = True
                break
        if not placed:
            cols.append([ln])
    return [sorted(c, key=lambda l: l.y0) for c in cols]


def group_lines_to_blocks(lines: list[Line], page_w: float, page_h: float) -> list[Block]:
    """行 → 块（阅读顺序：栏自左向右、栏内自上而下）。"""
    if not lines:
        return []
    cols = _cluster_columns(lines, page_w)
    blocks: list[Block] = []
    for col in sorted(cols, key=lambda c: c[0].x0):
        cur: list[Line] = [col[0]]
        heights = sorted(l.height for l in col)
        median_h = heights[len(heights) // 2] if heights else 10.0
        for prev, ln in zip(col, col[1:]):
            gap = ln.y0 - prev.y1
            # 大间隙 → 新块；缩进行回行不视为新块（栏聚类已处理多栏）
            if gap > median_h * 1.8:
                blocks.append(_make_block(cur, page_w, page_h))
                cur = [ln]
            else:
                cur.append(ln)
        blocks.append(_make_block(cur, page_w, page_h))
    return blocks


def _make_block(lines: list[Line], page_w: float, page_h: float) -> Block:
    box = (
        min(l.x0 for l in lines),
        min(l.y0 for l in lines),
        max(l.x1 for l in lines),
        max(l.y1 for l in lines),
    )
    text = "".join(l.text for l in lines).strip()
    w = box[2] - box[0]
    if text and PAGE_NO_RE.match(text):
        kind = "page-number"
    elif text and (box[1] < page_h * 0.045 or box[3] > page_h * 0.955):
        kind = "header-footer"
    elif w < page_w * 0.72 and HEADING_RE.match(text) and len(text) <= 28:
        kind = "heading"
    else:
        kind = "text"
    return Block(kind=kind, box=box, lines=lines)


def blocks_to_ordered_lines(blocks: list[Block]) -> list[Line]:
    """块按阅读顺序展开为行序列（供段落聚合）。"""
    out: list[Line] = []
    for i, b in enumerate(blocks):
        for ln in b.lines:
            ln.block_id = i
            out.append(ln)
    return out


class DocLayoutEngine:
    """PP-DocLayout 版面分析接口（P1）。

    接入方式（发布时随高精包提供）：
        pip install rapid-layout 或 paddlex --pipeline=layout_parsing
    输出转为 mdun Block 结构后接入 group_lines_to_blocks 之前的管线。
    """
    def predict(self, image) -> list[Block]:
        raise NotImplementedError("PP-DocLayout 引擎未安装（P1 特性，几何启发式已可用）")
