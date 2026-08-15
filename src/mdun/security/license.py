"""离线授权：机器指纹 + SM2 签名许可证（FR-8.3）。

- 客户端：\`mdun license fingerprint\` 生成机器指纹；
- 签发方（内网）：\`mdun license issue\` 用私钥对许可证载荷签名；
- 客户端校验：内置公钥验签 + 指纹/有效期/功能位检查；
- 公钥内置于构建，私钥永不出签发环境；无许可证时按 policy 处理（warn/strict）。
"""
from __future__ import annotations

import json
import platform
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from gmssl import sm3

# 构建时注入的供应商公钥（Ed25519 PEM；由 scripts/gen_vendor_keys.py 生成后替换）
VENDOR_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA2dCZf5dnWAIHdJNus/LJh1rEMqS4chuTKhBbsAqEXt8=
-----END PUBLIC KEY-----
"""


def machine_fingerprint() -> str:
    """机器指纹：网卡 MAC + 主机名 + 平台架构 → SM3 前 16 字节。"""
    raw = f"{uuid.getnode():x}|{platform.node()}|{platform.system()}|{platform.machine()}"
    return bytes.fromhex(sm3.sm3_hash([ord(c) for c in raw]))[:16].hex()


@dataclass
class License:
    fingerprint: str
    features: list[str] = field(default_factory=list)
    issued_at: int = 0
    expires_at: int = 0
    licensee: str = ""
    signature: str = ""

    def payload(self) -> dict:
        return {
            "fingerprint": self.fingerprint,
            "features": self.features,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "licensee": self.licensee,
        }

    def to_json(self) -> str:
        return json.dumps(self.payload(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, data: str | bytes) -> "License":
        d = json.loads(data)
        return cls(
            fingerprint=d.get("fingerprint", ""),
            features=d.get("features", []),
            issued_at=d.get("issued_at", 0),
            expires_at=d.get("expires_at", 0),
            licensee=d.get("licensee", ""),
            signature=d.get("signature", ""),
        )

    def sign(self, private_key_pem: str) -> str:
        """用供应商私钥（Ed25519 PEM 或密钥文件路径）签名。"""
        from Cryptodome.PublicKey import ECC
        from Cryptodome.Signature import eddsa

        key = ECC.import_key(private_key_pem)
        self.signature = eddsa.new(key, "rfc8032").sign(self.to_json().encode("utf-8")).hex()
        return self.signature

    def verify(self, public_key_hex: str | None = None) -> tuple[bool, str]:
        pub = public_key_hex or VENDOR_PUBLIC_KEY
        if not pub:
            return False, "未内置供应商公钥"
        if not self.signature:
            return False, "许可证缺少签名"
        from Cryptodome.PublicKey import ECC
        from Cryptodome.Signature import eddsa

        try:
            pubkey = ECC.import_key(pub)  # PEM 字符串
        except ValueError:
            return False, "供应商公钥格式错误"
        try:
            eddsa.new(pubkey, "rfc8032").verify(self.to_json().encode("utf-8"), bytes.fromhex(self.signature))
        except ValueError:
            return False, "签名校验失败（许可证被篡改）"
        if self.fingerprint != machine_fingerprint():
            return False, "机器指纹不匹配"
        if self.expires_at and time.time() > self.expires_at:
            return False, "许可证已过期"
        return True, "ok"

    def has_feature(self, name: str) -> bool:
        return name in self.features or "*" in self.features


def load_license(path: str | Path) -> License | None:
    p = Path(path)
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    lic = License.from_json(json.dumps(d.get("payload", d)))
    lic.signature = d.get("signature", lic.signature)
    return lic


def save_license(lic: License, path: str | Path) -> None:
    d = lic.payload()
    d["signature"] = lic.signature
    Path(path).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
