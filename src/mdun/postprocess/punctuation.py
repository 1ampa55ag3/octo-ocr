"""标点修复 · 规则层（纯本地、毫秒级、可配置、可逐条回退）。

设计原则：
- 每条修复产生一个 Edit（含原因标签），供 UI diff 预览与逐处接受/拒绝；
- 数字、URL、版本号等区域默认保护，防止误伤；
- 规则层只做"高置信"修复，语境级修复交给模型层（punc_model.py）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Edit:
    start: int          # 原文偏移
    end: int
    old: str
    new: str
    reason: str         # 规则 ID，UI 据此展示与批量撤销


@dataclass
class RuleConfig:
    unify_width: bool = True        # 全半角统一（中文语境全角）
    fix_pairs: bool = True          # 引号/括号配对修复
    fix_confusions: bool = True     # OCR 常见标点误识修正
    fix_ends: bool = False          # 段落末句标点补全（默认关闭：修复本义是西文标点，不擅自加句号）
    fix_sixpoint: bool = True       # 公文六角括号规范：〔年份〕语境（文号）统一为 〔〕
    protect_urls: bool = True       # 保护 URL/邮箱
    protect_numbers: bool = True    # 保护数字/小数/版本号


# ---------- 基础表 ----------

ASCII_TO_FULLWIDTH = str.maketrans({
    ",": "，", ".": "。", ":": "：", ";": "；", "?": "？", "!": "！",
    "(": "（", ")": "）", "[": "【", "]": "】", "<": "《", ">": "》",
})

OPEN_PUNCT = "（【《〈〔｛“"
CLOSE_PUNCT = "）】》〉〕｝”"
PAIR_MAP = {"（": "）", "【": "】", "《": "》", "〈": "〉", "〔": "〕", "｛": "｝", "“": "”"}
SENTENCE_END = set("。！？；")
LIST_MARKS = ("-", "*", "·", "•", "一、", "（一）", "1.", "1、", "①", "②", "③", "第")

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
URL_RE = re.compile(r"(https?://|www\.)[^\s\u4e00-\u9fff，。！？；：（）【】《》]+")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
NUM_RE = re.compile(r"\d+(?:[.,]\d+)*(?:%|％|万|亿|元|米|kg|KB|MB|GB)?")


def is_cjk(ch: str) -> bool:
    return bool(ch and CJK_RE.match(ch))


# ---------- 保护段 ----------

@dataclass
class _Protected:
    text: str
    spans: list[tuple[int, int, str]]  # (start, end, original)


def _protect(text: str, cfg: RuleConfig) -> _Protected:
    """把 URL/邮箱/数字段替换为私用区占位符，修复后还原。"""
    spans: list[tuple[int, int, str]] = []
    if cfg.protect_urls:
        for m in URL_RE.finditer(text):
            spans.append((m.start(), m.end(), m.group()))
        for m in EMAIL_RE.finditer(text):
            spans.append((m.start(), m.end(), m.group()))
    if cfg.protect_numbers:
        for m in NUM_RE.finditer(text):
            spans.append((m.start(), m.end(), m.group()))
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept: list[tuple[int, int, str]] = []
    last_end = -1
    for s, e, orig in spans:
        if s < last_end:
            continue
        kept.append((s, e, orig))
        last_end = e
    # 拼接式替换（避免原地替换导致后续索引漂移）
    parts: list[str] = []
    last = 0
    for i, (s, e, _) in enumerate(kept):
        parts.append(text[last:s])
        parts.append(chr(0xE000 + i))
        last = e
    parts.append(text[last:])
    return _Protected("".join(parts), kept)


def _restore(text: str, prot: _Protected) -> str:
    for i, (_, _, orig) in enumerate(prot.spans):
        text = text.replace(chr(0xE000 + i), orig)
    return text


def _protected_pos_map(prot: _Protected) -> tuple[list[int], int]:
    """构建 保护文本下标 → 原文下标 的映射（用于把编辑偏移还原到原坐标系）。"""
    mapping: list[int] = []
    j = 0
    for ch in prot.text:
        code = ord(ch)
        if 0xE000 <= code <= 0xE0FF and code - 0xE000 < len(prot.spans):
            s, e, _ = prot.spans[code - 0xE000]
            mapping.append(s)
            j = e
        else:
            mapping.append(j)
            j += 1
    return mapping, j


def _remap_edits(edits: list[Edit], prot: _Protected, original_len: int) -> list[Edit]:
    """把编辑从保护文本坐标重映射到原文坐标。"""
    mapping, total = _protected_pos_map(prot)
    out: list[Edit] = []
    for e in edits:
        s = mapping[e.start] if e.start < len(mapping) else total
        if e.end > e.start:
            end = mapping[e.end - 1] + 1 if 0 < e.end <= len(mapping) else s + 1
        else:
            end = s
        # 插入位置若落在占位符后（段落末尾），修正为占位符对应原文段尾
        out.append(Edit(s, end, e.old, e.new, e.reason))
    return out


# ---------- 规则实现 ----------

def _fix_width(text: str) -> tuple[str, list[Edit]]:
    """中文语境下 ASCII 标点转全角；数字/英文语境保持半角。"""
    edits: list[Edit] = []
    out: list[str] = []
    for i, ch in enumerate(text):
        if ch in ASCII_TO_FULLWIDTH:
            prev = text[i - 1] if i > 0 else ""
            nxt = text[i + 1] if i + 1 < len(text) else ""
            prev_cjk = is_cjk(prev) or prev in "）】》”"
            nxt_cjk = is_cjk(nxt) or nxt in "（【《“"
            is_digit_ctx = (prev.isdigit() or nxt.isdigit()) and ch in ",.:"
            if (prev_cjk or nxt_cjk) and not is_digit_ctx:
                full = chr(ASCII_TO_FULLWIDTH[ch])
                edits.append(Edit(i, i + 1, ch, full, "width:ascii2full"))
                out.append(full)
                continue
        out.append(ch)
    return "".join(out), edits


def _fix_sixpoint(text: str) -> tuple[str, list[Edit]]:
    """公文六角括号规范：〔年份〕/〔文号〕语境。

    OCR 常把 〔〕 误识为 [ ] / 【 】 或混搭（如「战略[2026】5号」），
    凡括号内容含 19xx/20xx 年份即统一为 〔〕；不含年份的括号不动（【强调】不受影响）。
    """
    edits: list[Edit] = []
    for m in re.finditer(r"([\[【〔])(.{1,20}?)([\]】〕])", text):
        content = m.group(2)
        if not re.search(r"(?:19|20)\d{2}", content):
            continue
        if m.group(1) != "〔":
            edits.append(Edit(m.start(1), m.start(1) + 1, m.group(1), "〔", "sixpoint:open"))
        if m.group(3) != "〕":
            edits.append(Edit(m.start(3), m.start(3) + 1, m.group(3), "〕", "sixpoint:close"))
    out = text
    for e in sorted(edits, key=lambda e: e.start, reverse=True):
        out = out[: e.start] + e.new + out[e.end :]
    return out, edits


def _fix_confusions(text: str) -> tuple[str, list[Edit]]:
    """OCR 高频标点误识修正（仅 CJK 之间）。"""
    edits: list[Edit] = []
    for half, full, rid in ((",", "，", "conf:cjk-comma"), (".", "。", "conf:cjk-period"),
                            (":", "：", "conf:cjk-colon"), (";", "；", "conf:cjk-semicolon")):
        pat = re.compile(rf"(?<=[\u4e00-\u9fff]){re.escape(half)}(?=[\u4e00-\u9fff])")
        for m in list(pat.finditer(text)):
            edits.append(Edit(m.start(), m.end(), half, full, rid))
    # 行尾的 ASCII 句点（中文之后）→ 全角句号
    pat_end = re.compile(r"(?<=[\u4e00-\u9fff])\.(?=$|[\s\n])")
    for m in list(pat_end.finditer(text)):
        edits.append(Edit(m.start(), m.end(), ".", "。", "conf:cjk-period-end"))
    for doubled in ("，，", "。。", "！！", "？？", "；；", "：："):
        pat = re.compile(re.escape(doubled))
        for m in list(pat.finditer(text)):
            edits.append(Edit(m.start(), m.end(), doubled, doubled[0], "conf:dedup"))
    out = text
    for e in sorted(edits, key=lambda e: e.start, reverse=True):
        out = out[: e.start] + e.new + out[e.end :]
    return out, edits


def _fix_pairs(text: str) -> tuple[str, list[Edit]]:
    """引号/括号配对修复：直引号按语境换开/闭，缺配对的句末闭合。"""
    edits: list[Edit] = []
    out: list[str] = []
    quote_open = False   # 段内开闭状态机
    squote_open = False
    for i, ch in enumerate(text):
        if ch == '"':
            prev = text[i - 1] if i > 0 else ""
            # 上下文强信号：句首/开括号/标点后 → 左引号；「说/道」后 → 左引号；否则按状态翻转
            if prev == "" or prev in "\n（【《〈，。！？；：、":
                repl, quote_open = "“", True
            elif prev in "说道":
                repl, quote_open = "“", True
            elif quote_open:
                repl, quote_open = "”", False
            else:
                repl, quote_open = "“", True
            edits.append(Edit(i, i + 1, ch, repl, "pair:quote"))
            out.append(repl)
        elif ch == "'":
            prev = text[i - 1] if i > 0 else ""
            if prev == "" or prev in "\n（【《〈，。！？；：":
                repl, squote_open = "‘", True
            elif squote_open:
                repl, squote_open = "’", False
            else:
                repl, squote_open = "‘", True
            edits.append(Edit(i, i + 1, ch, repl, "pair:squote"))
            out.append(repl)
        else:
            if ch in "。！？\n":
                quote_open = False
                squote_open = False
            out.append(ch)
    text2 = "".join(out)

    # 括号配对：栈式校验，不匹配或句末未闭合则修复
    stack: list[str] = []
    close_edits: list[Edit] = []
    for i, ch in enumerate(text2):
        if ch in PAIR_MAP:
            stack.append(PAIR_MAP[ch])
        elif ch in CLOSE_PUNCT:
            if stack and stack[-1] == ch:
                stack.pop()
            elif stack:
                close_edits.append(Edit(i, i + 1, ch, stack[-1], "pair:mismatch"))
                stack.pop()
        elif ch in "。！？":
            # 仅在后续不存在任何闭括号时才在此补闭，
            # 否则会与后面的真实闭括号重复（多次点击括号不断累加）
            rest = text2[i + 1:]
            if not any(c in CLOSE_PUNCT for c in rest):
                while stack:
                    close_edits.append(Edit(i + 1, i + 1, "", stack.pop(), "pair:close-at-end"))
    for e in sorted(close_edits, key=lambda e: e.start, reverse=True):
        text2 = text2[: e.start] + e.new + text2[e.end :]
    return text2, edits + close_edits


def _fix_ends(text: str) -> tuple[str, list[Edit]]:
    """段落末句标点补全：段落以 CJK 字符结束且无句末标点时补「。」。"""
    edits: list[Edit] = []
    paras = re.split(r"\n\s*\n", text)
    out_paras: list[str] = []
    offset = 0
    for para in paras:
        p = para.rstrip()
        if not p:
            out_paras.append(para)
            offset += len(para) + 2
            continue
        last = p[-1]
        if is_cjk(last) and last not in "。！？；：…”』」——…—":
            pos = offset + len(p)
            edits.append(Edit(pos, pos, "", "。", "end:add-period"))
            p += "。"
        out_paras.append(p)
        offset += len(para) + 2
    return "\n\n".join(out_paras), edits


def _apply_edits(text: str, edits: list[Edit]) -> str:
    for e in sorted(edits, key=lambda e: e.start, reverse=True):
        text = text[: e.start] + e.new + text[e.end :]
    return text


def repair(text: str, cfg: RuleConfig | None = None) -> tuple[str, list[Edit]]:
    """规则层标点修复。返回 (修复后文本, 编辑列表)。"""
    cfg = cfg or RuleConfig()
    cur = text
    all_edits: list[Edit] = []
    if cfg.fix_sixpoint:
        cur, e = _fix_sixpoint(cur)
        all_edits += e
    prot = _protect(cur, cfg)
    cur = prot.text
    if cfg.unify_width:
        cur, e = _fix_width(cur)
        all_edits += e
    if cfg.fix_confusions:
        cur, e = _fix_confusions(cur)
        all_edits += e
    if cfg.fix_pairs:
        cur, e = _fix_pairs(cur)
        all_edits += e
    if cfg.fix_ends:
        cur, e = _fix_ends(cur)
        all_edits += e
    result = _restore(cur, prot)
    # 编辑偏移还原到原文坐标系（占位符替换会改变文本长度）
    edits_final = _remap_edits(all_edits, prot, len(text))
    return result, sorted(edits_final, key=lambda e: e.start)


def apply_edits(text: str, edits: list[Edit]) -> str:
    return _apply_edits(text, edits)
