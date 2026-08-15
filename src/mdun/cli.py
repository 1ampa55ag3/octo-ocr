"""OctoOCR 命令行入口（mdun）。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from mdun import __version__, __product__
from mdun.config import load_settings
from mdun.pipeline import Pipeline
from mdun.security import AuditLog, OfflineGuard, audit_source
from mdun.security.license import License, machine_fingerprint


def _settings(args) -> object:
    return load_settings(args.data_dir)


def cmd_ocr(args) -> int:
    s = load_settings(args.data_dir)
    guard = OfflineGuard().enable()
    audit = AuditLog(s.data_dir / "audit.jsonl", hash_names=args.hash_names)
    try:
        pipe = Pipeline(s, audit)
        t0 = time.time()
        project = pipe.process(args.input, dpi=args.dpi, use_punc_model=not args.no_punc_model,
                               repair_punc=not args.no_repair, repair_para=not args.no_repair)
        out = Path(args.output)
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(args.input).stem
        from mdun.export import export_json, export_txt, export_searchable_pdf, export_docx, export_markdown

        for fmt in args.format.split(","):
            fmt = fmt.strip()
            if fmt == "json":
                export_json(project, out / f"{stem}.mdun.json")
            elif fmt == "txt":
                export_txt(project, out / f"{stem}.txt")
            elif fmt == "md":
                export_markdown(project, out / f"{stem}.md")
            elif fmt == "docx":
                export_docx(project, out / f"{stem}.docx")
            elif fmt == "pdf":
                export_searchable_pdf(args.input, out / f"{stem}.searchable.pdf", [p.text for p in project.pages])
            elif fmt == "xlsx":
                from mdun.export import export_xlsx

                export_xlsx(project, out / (stem + ".xlsx"))
            else:
                print(f"未知导出格式: {fmt}", file=sys.stderr)
        print(f"完成: {project.page_count} 页, 引擎 {project.engine_note}, 耗时 {time.time()-t0:.1f}s")
        punc_n = sum(len(p.punc_edits) for p in project.pages)
        rm_n = sum(len(p.removed) for p in project.pages)
        print(f"标点修复 {punc_n} 处, 页眉页脚删除 {rm_n} 处; 输出目录: {out}")
        return 0
    finally:
        guard.disable()


def cmd_repair(args) -> int:
    from mdun.postprocess import repair_punctuation, normalize_layout
    from mdun.postprocess.punc_model import PuncRestorer
    from mdun.config import load_settings

    text = Path(args.input).read_text(encoding="utf-8")
    s = load_settings(None)
    rest = PuncRestorer(s.models_dir / "ct_punc_zh.onnx")
    if args.punc_model and rest.available:
        paras = text.split("\n\n")
        text = "\n\n".join(rest.restore(p) for p in paras)
    new_text, edits = repair_punctuation(text)
    if args.paragraph:
        new_text = normalize_layout(new_text)
    out = Path(args.output or (Path(args.input).stem + ".repaired.txt"))
    out.write_text(new_text, encoding="utf-8")
    print(f"修复 {len(edits)} 处 → {out}")
    if args.diff:
        for e in edits:
            print(f"  [{e.reason}] {e.old!r} → {e.new!r} @ {e.start}")
    return 0


def cmd_export(args) -> int:
    from mdun.export import export_searchable_pdf

    proj = json.loads(Path(args.input).read_text(encoding="utf-8"))
    texts = [p["text"] for p in proj["pages"]]
    out = export_searchable_pdf(proj["source"], args.output, texts, visible_text=args.visible_text)
    print(f"双层 PDF 已导出: {out}")
    return 0


def cmd_serve(args) -> int:
    from mdun.web.server import run

    run(host=args.host, port=args.port, data_dir=args.data_dir)
    return 0


def cmd_license(args) -> int:
    if args.action == "fingerprint":
        print(machine_fingerprint())
        return 0
    if args.action == "issue":
        import time as _t

        lic = License(
            fingerprint=args.fingerprint,
            features=args.features.split(","),
            issued_at=int(_t.time()),
            expires_at=int(_t.time()) + args.days * 86400 if args.days else 0,
            licensee=args.licensee,
        )
        priv = Path(args.private_key).read_text(encoding="utf-8").strip()
        lic.sign(priv)
        from mdun.security.license import save_license

        save_license(lic, args.output)
        print(f"许可证已签发: {args.output}（指纹 {args.fingerprint}，功能 {args.features}，有效期 {args.days or '永久'} 天）")
        return 0
    if args.action == "verify":
        from mdun.security.license import load_license, VENDOR_PUBLIC_KEY

        lic = load_license(args.license_file)
        if lic is None:
            print("FAIL: 未找到许可证文件", file=sys.stderr)
            return 1
        ok, msg = lic.verify(args.public_key or VENDOR_PUBLIC_KEY or None)
        print(f"{'PASS' if ok else 'FAIL'}: {msg}")
        return 0 if ok else 1
    return 1


def cmd_audit(args) -> int:
    from pathlib import Path as P

    root = P(__file__).resolve().parent
    report = audit_source(root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["violations"] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mdun", description=f"{__product__} v{__version__} —— 完全离线 OCR 工作站")
    p.add_argument("--version", action="version", version=f"mdun {__version__}")
    p.add_argument("--data-dir", default=None, help="数据目录（模型/审计/临时），默认 ~/.mdun")
    sub = p.add_subparsers(dest="command", required=True)

    o = sub.add_parser("ocr", help="识别 PDF/图片并修复导出")
    o.add_argument("input")
    o.add_argument("-o", "--output", default=".")
    o.add_argument("--dpi", type=int, default=200)
    o.add_argument("--format", default="json,txt,pdf", help="json,txt,md,docx,pdf 逗号分隔")
    o.add_argument("--no-repair", action="store_true")
    o.add_argument("--no-punc-model", action="store_true")
    o.add_argument("--hash-names", action="store_true", help="审计日志中哈希化文件名")
    o.set_defaults(func=cmd_ocr)

    r = sub.add_parser("repair", help="对纯文本执行标点修复")
    r.add_argument("input")
    r.add_argument("-o", "--output", default=None)
    r.add_argument("--punc-model", action="store_true")
    r.add_argument("--paragraph", action="store_true")
    r.add_argument("--diff", action="store_true")
    r.set_defaults(func=cmd_repair)

    e = sub.add_parser("export", help="由 mdun.json 项目导出双层 PDF")
    e.add_argument("input")
    e.add_argument("-o", "--output", required=True)
    e.add_argument("--visible-text", action="store_true")
    e.set_defaults(func=cmd_export)

    s = sub.add_parser("serve", help="启动本地离线校对工作台")
    s.add_argument("--port", type=int, default=8788)
    s.add_argument("--host", default="127.0.0.1", help="监听地址（局域网访问填 0.0.0.0）")
    s.set_defaults(func=cmd_serve)

    l = sub.add_parser("license", help="离线授权管理")
    l.add_argument("action", choices=["fingerprint", "issue", "verify"])
    l.add_argument("--fingerprint", default=None)
    l.add_argument("--features", default="ocr")
    l.add_argument("--days", type=int, default=0)
    l.add_argument("--licensee", default="")
    l.add_argument("--private-key", default="vendor_private.key")
    l.add_argument("--public-key", default=None)
    l.add_argument("--license-file", default="license.json")
    l.add_argument("-o", "--output", default="license.json")
    l.set_defaults(func=cmd_license)

    a = sub.add_parser("audit", help="输出零网络审计报告")
    a.set_defaults(func=cmd_audit)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
