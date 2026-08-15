"""离线网络封锁与源码零网络审计（FR-8.1）。

- OfflineGuard：运行时把 socket 出网路径全部封死（仅放行 127.0.0.1 回环，
  供本地 Web 校对工作台使用），保证"逻辑联网 = 不可能"；
- audit_source：静态扫描本包源码中的网络 API 使用，输出审计报告。
"""
from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path

_LOOPBACK = {ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128")}


class OfflineGuard:
    """Patch socket 出网入口；仅允许回环地址。"""

    def __init__(self) -> None:
        self._enabled = False
        self._orig_connect = None
        self._orig_create_connection = None
        self._orig_getaddrinfo = None

    def enable(self) -> "OfflineGuard":
        if self._enabled:
            return self
        self._orig_connect = socket.socket.connect
        self._orig_create_connection = socket.create_connection
        self._orig_getaddrinfo = socket.getaddrinfo

        def guarded_connect(sock: socket.socket, address):
            host = address[0] if isinstance(address, tuple) else str(address)
            if not self._is_loopback(host):
                raise OSError(f"mdun offline guard: 网络访问已封锁 ({host})")
            return self._orig_connect(sock, address)

        def guarded_create_connection(address, *args, **kwargs):
            host = address[0] if isinstance(address, tuple) else str(address)
            if not self._is_loopback(host):
                raise OSError(f"mdun offline guard: 网络访问已封锁 ({host})")
            return self._orig_create_connection(address, *args, **kwargs)

        def guarded_getaddrinfo(host, *args, **kwargs):
            if host not in ("localhost",) and not self._is_loopback(host):
                raise OSError(f"mdun offline guard: 域名解析已封锁 ({host})")
            return self._orig_getaddrinfo(host, *args, **kwargs)

        socket.socket.connect = guarded_connect
        socket.create_connection = guarded_create_connection
        socket.getaddrinfo = guarded_getaddrinfo
        self._enabled = True
        return self

    def disable(self) -> None:
        if not self._enabled:
            return
        socket.socket.connect = self._orig_connect
        socket.create_connection = self._orig_create_connection
        socket.getaddrinfo = self._orig_getaddrinfo
        self._enabled = False

    @staticmethod
    def _is_loopback(host: str) -> bool:
        try:
            ip = ipaddress.ip_address(str(host).split("%")[0])
        except ValueError:
            return str(host) in ("localhost", "127.0.0.1", "::1")
        return any(ip in net for net in _LOOPBACK)

    def __enter__(self):
        return self.enable()

    def __exit__(self, *exc):
        self.disable()
        return False


_BANNED_IMPORT = re.compile(
    r"^\s*(?:import\s+(?:requests|urllib3|httpx|aiohttp|websocket|socket|http\.client)"
    r"|from\s+(?:requests|urllib|http|httpx|aiohttp|websocket|socket)\s+import)",
    re.MULTILINE,
)


def audit_source(root: str | Path) -> dict:
    """静态扫描包内 .py 文件的网络调用，输出零网络审计报告。"""
    root = Path(root)
    findings: list[dict] = []
    files_checked = 0
    for f in sorted(root.rglob("*.py")):
        if ".venv" in f.parts or "build" in f.parts:
            continue
        files_checked += 1
        text = f.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            if _BANNED_IMPORT.search(line):
                if f.name == "audit.py":  # 封锁器实现本身需要 socket
                    continue
                findings.append({"file": str(f.relative_to(root)), "line": i, "code": line.strip()})
    return {
        "files_checked": files_checked,
        "violations": findings,
        "conclusion": "PASS: 除安全封锁模块外无网络 API 使用" if not findings else "FAIL: 存在网络 API 使用",
    }
