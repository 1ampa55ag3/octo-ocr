"""全局配置与路径管理。

所有状态一律落在用户可控目录（默认 ~/.mdun 与项目工作目录），
绝不隐式写入其他位置，保证可审计、可清理。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR_NAME = "mdun"


def default_data_dir() -> Path:
    """默认数据目录：优先环境变量 MDUN_HOME，其次用户目录。"""
    env = os.environ.get("MDUN_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / (".mdun" if os.name != "nt" else "mdun")


@dataclass
class Settings:
    data_dir: Path = field(default_factory=default_data_dir)
    model_dir: Path | None = None          # 模型目录（默认为 data_dir/models）
    lang: str = "ch"                       # 识别语言：ch / en / ch_en
    precision: str = "standard"            # fast / standard / high
    num_threads: int = 0                   # 0 = 自动
    offline_enforce: bool = True           # 强制离线（阻断一切 socket 出网）
    temp_encrypt: bool = True              # 临时数据加密
    audit_enable: bool = True              # 审计日志

    @property
    def models_dir(self) -> Path:
        return self.model_dir or (self.data_dir / "models")

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.models_dir, self.temp_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_settings(data_dir: str | None = None) -> Settings:
    """加载设置；data_dir/config.json 可覆盖部分字段（如 num_threads）。

    示例 config.json（限制识别线程数以降低 CPU 占用/风扇噪音）：
        {"num_threads": 4}
    """
    s = Settings()
    if data_dir:
        s.data_dir = Path(data_dir).expanduser()
    cfg = s.data_dir / "config.json"
    if cfg.exists():
        try:
            import json

            d = json.loads(cfg.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                if "num_threads" in d:
                    s.num_threads = max(0, int(d["num_threads"]))
        except Exception:  # noqa: BLE001 配置损坏时回退默认，不影响启动
            pass
    s.ensure_dirs()
    return s
