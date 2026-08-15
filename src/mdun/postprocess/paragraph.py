"""段落快捷修复：行合并、段落拆分、阅读顺序、页眉页脚删除、版式统一。

输入为识别出的文本行（带坐标与置信度），输出段落结构与编辑建议。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------- 数据结构 ----------

@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float = 1.0
    block_id: int = 0

    @property
    def height(self) -> float:
        return max(self.y1 - self.y0, 0.01)

    @property
    def width(self) -> float:
        return max(self.x1 - self.x0, 0.01)

    @property
    def indent(self) -> float:
        return self.x0


@dataclass
class Para:
    lines: list[Line] = field(default_factory=list)

    @property
    def text(self) -> str:
        return merge_text([ln.text for ln in self.lines])

    @property
    def box(self) -> tuple[float, float, float, float]:
        if not self.lines:
            return (0, 0, 0, 0)
        return (
            min(l.x0 for l in self.lines),
            min(l.y0 for l in self.lines),
            max(l.x1 for l in self.lines),
            max(l.y1 for l in self.lines),
        )


@dataclass
class PageResult:
    page_index: int
    paras: list[Para]
    removed: list[tuple[str, str]] = field(default_factory=list)  # (text, reason)


TERMINAL = set("。！？…”』」；：—…")
HEADING_RE = re.compile(
    r"^(第[一二三四五六七八九十百千0-9]+[章节条款部篇]|"
    r"[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|"
    r"\d+(?:\.\d+)*[、.．]?\s*[^，。；：]{0,20}$)"
)
PAGE_NO_RE = re.compile(r"^\s*(?:-\s*)?\d{1,4}(?:\s*-)?\s*$|^第\s*\d+\s*页(?:\s*共\s*\d+\s*页)?$|^\d+\s*/\s*\d+$")
DATE_RE = re.compile(r"^\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*$")


def merge_text(line_texts: list[str]) -> str:
    """行合并：CJK 直接拼接；拉丁词之间补空格；行尾连字符合并。"""
    out: list[str] = []
    for t in line_texts:
        t = t.strip()
        if not t:
            continue
        if not out:
            out.append(t)
            continue
        prev = out[-1]
        if prev.endswith("-") and t[0].isascii():
            out[-1] = prev[:-1] + t
        elif prev and t and (prev[-1].isascii() and t[0].isascii()):
            out[-1] = prev + " " + t
        else:
            out[-1] = prev + t
    return "".join(out)


def _is_heading(line: Line, block_w: float) -> bool:
    if line.width < block_w * 0.72 and line.conf > 0.8:
        if HEADING_RE.match(line.text.strip()):
            return True
    return False


def merge_lines(lines: list[Line], block_width: float | None = None) -> list[Para]:
    """行 → 段落（布局感知版）。

    两步策略：
    1. 同行悬字拼接：OCR 检测常把行尾单字/标点切成独立小框（与前一行 y 重叠、
       x 紧接前一行右缘）——直接拼回上一行，杜绝"单字掉在单独一行"；
    2. 段落信号（满足其一换段）：
       - 前一行以句末标点结束 + 当前行有缩进（段首缩进）；
       - 行间垂直间距显著大于行高（空行）；
       - 当前行是标题样式；
       - 左移回行（x0 显著小于上一行起点 → 新栏/新行起始）；
       - 短而完整的独立行（上一行句末结束 + 当前行短且句末结束）。
       不再把"块边界"当作换段信号——同一段落被版面分块拆散时仍能正确合并。
    """
    if not lines:
        return []
    ls = sorted(lines, key=lambda l: (l.y0, l.x0))
    bw = block_width or max(l.x1 for l in ls)
    heights = sorted(l.height for l in ls)
    median_h = heights[len(heights) // 2] if heights else 10.0

    paras: list[Para] = [Para(lines=[ls[0]])]
    for cur in ls[1:]:
        prev = paras[-1].lines[-1]

        # ① 同行悬字：y 与前一行重叠，x 紧接其右缘且自身很短
        same_row = (
            (cur.y0 - prev.y0) < median_h * 0.6
            and cur.x0 < prev.x1 + median_h * 0.8
            and cur.x0 >= prev.x1 - median_h * 0.2
            and cur.width < median_h * 3
        )
        if same_row:
            merged = Line(
                text=prev.text + cur.text,
                x0=prev.x0, y0=prev.y0,
                x1=max(prev.x1, cur.x1), y1=max(prev.y1, cur.y1),
                conf=min(prev.conf, cur.conf), block_id=prev.block_id,
            )
            paras[-1].lines[-1] = merged
            continue

        # ② 段落信号
        prev_ends = prev.text.rstrip()[-1:] in TERMINAL if prev.text.strip() else False
        has_indent = (
            (cur.x0 - paras[-1].lines[0].x0) > bw * 0.03
            or cur.text.startswith(("　", "  "))
        )
        big_gap = (cur.y0 - prev.y1) > median_h * 1.35
        heading = _is_heading(cur, bw)
        col_return = cur.x0 < prev.x0 - median_h and (cur.y0 - prev.y1) < median_h * 1.35
        short_standalone = (
            prev_ends
            and not heading
            and cur.width < bw * 0.85
            and cur.text.rstrip()[-1:] in TERMINAL
            and (cur.y0 - prev.y1) > median_h * 1.05
        )
        if heading or big_gap or (prev_ends and has_indent) or col_return or short_standalone:
            paras.append(Para(lines=[cur]))
        else:
            paras[-1].lines.append(cur)
    return paras


def split_paragraphs(text: str) -> tuple[str, list[tuple[int, str]]]:
    """大块文本 → 按标题/缩进模式智能分段。返回 (新文本, [(位置, 标题), ...])。"""
    lines = text.split("\n")
    out: list[str] = []
    titles: list[tuple[int, str]] = []
    for ln in lines:
        s = ln.strip()
        if s and HEADING_RE.match(s) and len(s) <= 24:
            titles.append((len("\n".join(out)) + (1 if out else 0), s))
            if out and out[-1] != "":
                out.append("")
            out.append(s)
            out.append("")
        else:
            out.append(ln)
    return "\n".join(out), titles


def remove_headers_footers(pages: list[list[str]], scan_lines: int = 2) -> tuple[list[list[str]], list[dict]]:
    """跨页页眉/页脚/页码批量删除。

    策略：
    - 每页顶部/底部 scan_lines 行内命中页码/日期模式 → 删除；
    - 多页重复出现的相同短文本（出现率 ≥ 80%）→ 视为页眉/页脚删除。
    """
    from collections import Counter

    n = len(pages)
    cleaned: list[list[str]] = []
    removals: list[dict] = []

    # 1) 模式删除（页码/日期）
    for pi, lines in enumerate(pages):
        kept = list(lines)
        removed: list[tuple[str, str]] = []
        for idx in list(range(min(scan_lines, len(kept)))) + list(
            range(max(scan_lines, len(kept) - scan_lines), len(kept))
        ):
            if idx >= len(kept):
                continue
            t = kept[idx].strip()
            if t and (PAGE_NO_RE.match(t) or DATE_RE.match(t)):
                removed.append((t, "pattern"))
                kept[idx] = ""
        cleaned.append(kept)
        for t, r in removed:
            removals.append({"page": pi, "text": t, "reason": r})

    # 2) 跨页重复文本（页眉页脚）：位置带（顶部/底部）须一致，防止正文误删
    counter: Counter[tuple[str, str]] = Counter()
    for lines in cleaned:
        top = lines[:scan_lines]
        bottom = lines[-scan_lines:] if len(lines) > scan_lines else []
        seen_top: set[str] = set()
        for t in top:
            t = t.strip()
            if t and len(t) <= 40 and t not in seen_top:
                counter[(t, "top")] += 1
                seen_top.add(t)
        seen_bot: set[str] = set()
        for t in bottom:
            t = t.strip()
            if t and len(t) <= 40 and t not in seen_bot:
                counter[(t, "bottom")] += 1
                seen_bot.add(t)
    threshold = max(2, int(n * 0.8))
    for (t, band), cnt in counter.items():
        if cnt >= threshold:
            for pi, lines in enumerate(cleaned):
                cleaned[pi] = ["" if ln.strip() == t else ln for ln in lines]
            removals.append({"page": -1, "text": t, "reason": f"repeated-{band}-x{cnt}"})
    return cleaned, removals


def normalize_layout(text: str, indent_paras: bool = True) -> str:
    """版式统一：去行尾空格、压缩连续空行、可选段首全角缩进。"""
    lines = [ln.rstrip() for ln in text.split("\n")]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if not ln:
            blank += 1
            if blank <= 1:
                out.append("")
            continue
        blank = 0
        is_heading_like = HEADING_RE.match(ln.strip()) is not None or len(ln) <= 12
        do_indent = (
            indent_paras
            and len(ln) >= 16
            and not ln.startswith(("　", " ", "#", "-", "1", "（"))
            and not is_heading_like
        )
        out.append(("　　" + ln) if do_indent else ln)
    return "\n".join(out).strip() + "\n"


def reading_order(blocks: list[tuple[float, float, float, float, int]], page_w: float) -> list[int]:
    """多栏阅读顺序：按列聚类 → 列内自上而下。返回块索引顺序。"""
    # blocks: (x0, y0, x1, y1, idx)
    xs = sorted(b[0] for b in blocks)
    if not xs:
        return []
    # 简单版：按 x0 排序后，用 x 重叠判定是否同栏
    order: list[int] = []
    used: set[int] = set()
    col_clusters: list[list[tuple[float, float, float, float, int]]] = []
    for b in sorted(blocks, key=lambda b: (b[0], b[1])):
        placed = False
        for col in col_clusters:
            c = col[0]
            overlap_x = min(b[2], c[2]) - max(b[0], c[0])
            if overlap_x > 0.3 * min(b[2] - b[0], c[2] - c[0]):
                col.append(b)
                placed = True
                break
        if not placed:
            col_clusters.append([b])
    for col in sorted(col_clusters, key=lambda c: c[0][0]):
        for b in sorted(col, key=lambda b: b[1]):
            order.append(b[4])
    return order
