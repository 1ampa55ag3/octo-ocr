"""本地审计日志（FR-8.4）：JSONL + 文件锁，可哈希化文件名，可导出。"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from gmssl import sm3

if os.name == "nt":
    import msvcrt

    def _lock(f):
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock(f):
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _lock(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

    def _unlock(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class AuditLog:
    """线程/进程安全的追加式审计日志。"""

    def __init__(self, path: str | Path, hash_names: bool = False):
        self.path = Path(path)
        self.hash_names = hash_names

    def _record(self, event: str, file_name: str | None, detail: dict | None) -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event": event,
            "file": self._name(file_name) if file_name else None,
            "detail": detail or {},
        }
        with open(self.path, "a", encoding="utf-8") as f:
            _lock(f)
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            _unlock(f)

    def _name(self, name: str) -> str:
        if not self.hash_names:
            return name
        return bytes.fromhex(sm3.sm3_hash([ord(c) for c in name]))[:16].hex()

    def import_file(self, name: str, pages: int | None = None) -> None:
        self._record("import", name, {"pages": pages})

    def ocr_done(self, name: str, pages: int, seconds: float) -> None:
        self._record("ocr_done", name, {"pages": pages, "seconds": round(seconds, 2)})

    def repair(self, name: str, kind: str, count: int) -> None:
        self._record("repair", name, {"kind": kind, "edits": count})

    def export(self, name: str, fmt: str, encrypted: bool) -> None:
        self._record("export", name, {"format": fmt, "encrypted": encrypted})

    def export_log(self, dst: str | Path) -> Path:
        dst = Path(dst)
        dst.write_bytes(self.path.read_bytes())
        return dst
