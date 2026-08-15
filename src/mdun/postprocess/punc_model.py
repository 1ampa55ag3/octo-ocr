"""标点恢复模型层（FR-4.3）：ct-punc 中文标点模型，sherpa-onnx 运行时。

- 模型缺失时自动降级为规则层（punctuation.py），不阻断主流程；
- 模型为离线 ONNX，CPU 可跑（约 30MB，int8 量化版更小）。
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("mdun.punc")


class PuncRestorer:
    """ct-transformer 标点恢复（面向无标点文本段）。"""

    def __init__(self, model_path: str | Path, num_threads: int = 1):
        self.model_path = Path(model_path)
        self._op = None
        if self.model_path.exists():
            self._load()

    def _load(self) -> None:
        import sherpa_onnx

        cfg = sherpa_onnx.OfflinePunctuationConfig(
            model=sherpa_onnx.OfflinePunctuationModelConfig(
                ct_transformer=str(self.model_path), num_threads=1, debug=False, provider="cpu"
            )
        )
        self._op = sherpa_onnx.OfflinePunctuation(cfg)

    @property
    def available(self) -> bool:
        return self._op is not None

    def restore(self, text: str) -> str:
        """对缺失标点的文本补标点。无模型时原样返回。"""
        if not self.available or not text.strip():
            return text
        try:
            return self._op.add_punctuation(text)
        except Exception as e:  # noqa: BLE001
            log.warning("标点模型推理失败，降级规则层: %s", e)
            return text
