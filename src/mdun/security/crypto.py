"""临时数据加密 / 导出加密（国密 SM4-CBC + SM3 摘要，FR-6.3 / FR-8.2）。

- 密钥派生：SM3(password + salt) → 16 字节密钥；
- 输出格式：MDSM4v1 | salt(8B) | iv(16B) | ciphertext | sm3(plaintext)(32B)；
- 纯离线实现，依赖 gmssl（纯 Python）。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from gmssl import sm3, sm4

MAGIC = b"MDSM4v1"
_BLOCK = 16


def _sm3_digest(data: bytes) -> bytes:
    return bytes.fromhex(sm3.sm3_hash([b for b in data]))


def _pkcs7_pad(data: bytes) -> bytes:
    n = _BLOCK - len(data) % _BLOCK
    return data + bytes([n]) * n


def _pkcs7_unpad(data: bytes) -> bytes:
    n = data[-1]
    if n < 1 or n > _BLOCK:
        raise ValueError("SM4 解密失败：填充错误（密钥或数据损坏）")
    return data[:-n]


def derive_key(password: str, salt: bytes) -> bytes:
    return _sm3_digest(password.encode("utf-8") + salt)[:16]


def encrypt_bytes(data: bytes, password: str) -> bytes:
    salt = os.urandom(8)
    key = derive_key(password, salt)
    iv = os.urandom(16)
    c = sm4.CryptSM4()
    c.set_key(key, sm4.SM4_ENCRYPT)
    ct = c.crypt_cbc(iv, _pkcs7_pad(data))
    return MAGIC + salt + iv + ct + _sm3_digest(data)


def decrypt_bytes(blob: bytes, password: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("不是 OctoOCR 加密数据（MAGIC 校验失败）")
    body = blob[len(MAGIC):]
    salt, iv, rest = body[:8], body[8:24], body[24:]
    ct, digest = rest[:-32], rest[-32:]
    key = derive_key(password, salt)
    c = sm4.CryptSM4()
    c.set_key(key, sm4.SM4_DECRYPT)
    raw = c.crypt_cbc(iv, ct)
    if not raw:
        raise ValueError("SM4 解密失败（密码错误或数据损坏）")
    pt = _pkcs7_unpad(raw)
    if _sm3_digest(pt) != digest:
        raise ValueError("SM4 解密失败：摘要校验不通过（密码错误或数据被篡改）")
    return pt


def encrypt_file(src: str | Path, dst: str | Path, password: str) -> Path:
    data = Path(src).read_bytes()
    dst = Path(dst)
    dst.write_bytes(encrypt_bytes(data, password))
    return dst


def decrypt_file(src: str | Path, dst: str | Path, password: str) -> Path:
    data = decrypt_bytes(Path(src).read_bytes(), password)
    dst = Path(dst)
    dst.write_bytes(data)
    return dst


def hash_file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
