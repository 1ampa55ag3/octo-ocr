"""导出：Markdown / TXT（FR-6.2）。表格 → MD 表格语法；公式 → LaTeX 行。"""
from __future__ import annotations

from pathlib import Path

from mdun.export.docx import _ordered_items


def _render_md_items(page) -> list[str]:
    lines: list[str] = []
    for kind, item in _ordered_items(page):
        if kind == "para":
            text = item["text"]
            if item["kind"] == "heading":
                lines.append("## " + text)
            else:
                lines.append(text)
        elif kind == "table":
            rows = item["rows"]
            if not rows:
                continue
            n_cols = max(len(r) for r in rows)
            head = "| " + " | ".join(str(rows[0][i]) if i < len(rows[0]) else "" for i in range(n_cols)) + " |"
            sep = "|" + "---|" * n_cols
            lines.append(head)
            lines.append(sep)
            for r in rows[1:]:
                lines.append("| " + " | ".join(str(r[i]) if i < len(r) else "" for i in range(n_cols)) + " |")
        elif kind == "formula":
            lines.append("$$" + item["latex"] + "$$")
        lines.append("")
    return lines


def export_markdown(project, out: str | Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    buf: list[str] = []
    for page in project.pages:
        buf.extend(_render_md_items(page))
    out.write_text("\n".join(buf), encoding="utf-8")
    return out


def export_txt(project, out: str | Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    buf: list[str] = []
    for page in project.pages:
        for kind, item in _ordered_items(page):
            if kind == "para":
                if item["kind"] == "page-number":
                    continue
                buf.append(item["text"])
            elif kind == "table":
                for r in item["rows"]:
                    buf.append(" | ".join(r))
            elif kind == "formula":
                buf.append(item["latex"])
            buf.append("")
    out.write_text("\n".join(buf), encoding="utf-8")
    return out
