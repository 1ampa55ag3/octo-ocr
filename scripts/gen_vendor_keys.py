"""生成供应商 Ed25519 密钥对（离线授权签发用，FR-8.3）。

用法:
    .venv/bin/python scripts/gen_vendor_keys.py

输出:
    vendor_private.pem —— 私钥（仅存签发环境，绝不随产品分发！）
    vendor_public.pem  —— 公钥（将其内容嵌入 src/mdun/security/license.py 的 VENDOR_PUBLIC_KEY）

签发许可证:
    .venv/bin/python -m mdun.cli license issue --fingerprint <客户端指纹> \
        --features ocr,high --days 365 --private-key vendor_private.pem -o license.json
"""
from __future__ import annotations

from pathlib import Path

from Cryptodome.PublicKey import ECC


def main() -> None:
    key = ECC.generate(curve="Ed25519")
    priv = key.export_key(format="PEM")
    pub = key.public_key().export_key(format="PEM")
    Path("vendor_private.pem").write_text(priv, encoding="utf-8")
    Path("vendor_public.pem").write_text(pub, encoding="utf-8")
    print("已生成 vendor_private.pem / vendor_public.pem")
    print("1) 私钥只保留在签发环境，严禁随产品分发；")
    print("2) 将 vendor_public.pem 内容嵌入 license.py 的 VENDOR_PUBLIC_KEY（构建时注入）。")


if __name__ == "__main__":
    main()
