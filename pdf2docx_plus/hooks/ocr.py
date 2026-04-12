"""PaddleOCR (Apache-2.0) engine for scanned / image-only PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PaddleOcrEngine:
    lang: str = "en"
    use_angle_cls: bool = True
    _ocr: Any | None = None

    def _ensure_loaded(self) -> None:
        if self._ocr is not None:
            return
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "PaddleOCR requires the 'ml-ocr' extra: pip install 'pdf2docx-plus[ml-ocr]'"
            ) from e
        self._ocr = PaddleOCR(use_angle_cls=self.use_angle_cls, lang=self.lang, show_log=False)

    def recognize(self, image: Any, *, lang: str | None = None) -> str:
        self._ensure_loaded()
        assert self._ocr is not None
        import numpy as np  # type: ignore

        arr = np.asarray(image)
        raw = self._ocr.ocr(arr, cls=self.use_angle_cls)
        lines: list[str] = []
        for block in raw or []:
            for entry in block or []:
                if len(entry) >= 2 and isinstance(entry[1], (tuple, list)):
                    lines.append(str(entry[1][0]))
        return "\n".join(lines)
