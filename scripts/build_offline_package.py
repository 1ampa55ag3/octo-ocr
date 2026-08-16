# -*- coding: utf-8 -*-
"""构建鸿蒙 PC 离线部署包（在任意可联网电脑上运行）。

产物：
  <out>/wheels/                 全部依赖轮子（cp311 manylinux aarch64）
  <out>/python-runtime.tar.gz   python-build-standalone 3.11 aarch64 运行时（含 pip）
说明：
  - 模型不在此脚本范围：请用 scripts/download_models.sh 或直接拷贝现成 models/
  - 代码不在此脚本范围：部署包内直接放 src/ 与 models/（见 docs/harmony-pc-deploy.md）

用法:  python3 build_offline_package.py <输出目录>
"""
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

PLATFORMS = [
    "manylinux_2_28_aarch64",
    "manylinux_2_27_aarch64",
    "manylinux2014_aarch64",
    "manylinux_2_17_aarch64",
    "manylinux_2_34_aarch64",
]
PY_VER = "311"
PBS_TAG = "20260814"
PBS_FILE = f"cpython-3.11.16+{PBS_TAG}-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz"

# 顶层依赖：与 scripts/requirements-harmony.txt 一致（rapid-latex-ocr 单独处理）
TOP = [
    "numpy>=1.24", "opencv-python-headless>=4.8", "pillow>=10",
    "rapidocr-onnxruntime==1.4.4", "rapid-table==3.0.2", "rapid-layout==1.2.1",
    "pymupdf>=1.24", "python-docx>=1.1", "gmssl>=3.2",
    "sherpa-onnx>=1.10", "tokenizers>=0.20", "omegaconf>=2.3", "colorlog>=6.0",
    "openpyxl>=3.1", "opencc-python-reimplemented>=0.1.7", "symspellpy>=6.9",
    "chardet", "requests", "tqdm",
]
# omegaconf 锁 antlr4-python3-runtime==4.9.*，而 4.9.3 只有 sdist 无轮子，
# 解析会失败：omega 从 TOP 中移除、手工加入闭包；antlr4 用本地 sdist 打通用轮子
TOP = [x for x in TOP if not x.startswith("omegaconf")]


def sh(args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("\n".join((r.stderr or r.stdout).strip().splitlines()[-6:]))


def main() -> int:
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path("offline-package")
    out.mkdir(parents=True, exist_ok=True)
    pip = "pip3" if shutil.which("pip3") else sys.executable + " -m pip"

    # 1) 闭包解析（本机平台，rapid-latex-ocr 除外——其 numpy<2 锁与 rapid-layout 冲突）
    macpool = Path("/tmp/mdun-macpool")
    shutil.rmtree(macpool, ignore_errors=True)
    macpool.mkdir()
    topf = Path("/tmp/mdun-top.txt")
    topf.write_text("\n".join(TOP) + "\n", encoding="utf-8")
    sh(pip.split() + ["download", "-r", str(topf), "-d", str(macpool),
                      "--only-binary=:all:", "--python-version", "311"])
    closure = set()
    for f in macpool.glob("*.whl"):
        m = re.match(r"^(.+?)-(\d[^-]*)-", f.name)
        if m:
            closure.add((m.group(1).replace("_", "-").lower(), m.group(2)))
    closure.add(("rapid-latex-ocr", "0.0.9"))
    closure.add(("omegaconf", "2.3.1"))
    print("闭包 %d 个包" % len(closure))

    # 2) 逐包下载 cp311 aarch64 轮子（多平台标签兜底）
    wdir = out / "wheels"
    shutil.rmtree(wdir, ignore_errors=True)
    wdir.mkdir()
    missing = []
    for name, ver in sorted(closure):
        got = False
        for spec in (f"{name}=={ver}", name):
            for plat in PLATFORMS:
                r = subprocess.run(
                    pip.split() + ["download", spec, "--no-deps", "-d", str(wdir),
                                   "--only-binary=:all:", "--python-version", PY_VER,
                                   "--platform", plat],
                    capture_output=True, text=True)
                if r.returncode == 0:
                    got = True
                    break
            if got:
                break
        if not got:
            missing.append(f"{name}=={ver}")
    for spec in ("pip", "setuptools"):
        sh(pip.split() + ["download", spec, "--no-deps", "-d", str(wdir),
                          "--only-binary=:all:", "--python-version", PY_VER,
                          "--platform", "manylinux2014_aarch64"])
    # antlr4-python3-runtime 4.9.3 只有 sdist：本地打成通用轮子放进池
    sh(pip.split() + ["wheel", "antlr4-python3-runtime==4.9.3", "--no-deps", "-w", str(wdir)])
    print("轮子 %d 个 -> %s" % (len(list(wdir.glob("*.whl"))), wdir))
    for m in missing:
        print("  MISSING:", m)

    # 3) 自带 Python 运行时（python-build-standalone，含 pip）
    rt = out / "python-runtime.tar.gz"
    if not rt.exists():
        url = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_TAG}/{PBS_FILE}"
        print("下载运行时:", url)
        with urllib.request.urlopen(url, timeout=3600) as resp, open(rt, "wb") as f:
            f.write(resp.read())
    print("运行时:", rt)
    print("OFFLINE-PACKAGE DONE ->", out)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
