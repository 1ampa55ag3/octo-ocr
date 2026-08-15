"""导出：结构化 JSON（FR-2.7/6.2）——中间标准格式与最终导出格式。"""
from __future__ import annotations

import json
from pathlib import Path

from mdun.pipeline import Project


def project_to_dict(project: Project) -> dict:
    return {
        "schema": "mdun-project-v2",
        "source": project.source,
        "engine": project.engine_note,
        "pages": [
            {
                "index": p.index,
                "kind": p.kind,
                "width": p.width,
                "height": p.height,
                "text": p.text,
                "conf_avg": round(p.conf_avg, 4),
                "seconds": round(p.seconds, 3),
                "punc_edits": p.punc_edits,
                "removed": p.removed,
                "tables": p.tables,
                "formulas": p.formulas,
                "low_conf": getattr(p, "low_conf", []),
                "paras": [
                    {"kind": para.kind, "text": para.text, "box": [round(v, 1) for v in para.box]}
                    for para in p.paras
                ],
            }
            for p in project.pages
        ],
    }


def export_json(project: Project, out: str | Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(project_to_dict(project), ensure_ascii=False, indent=2), encoding="utf-8")
    return out
