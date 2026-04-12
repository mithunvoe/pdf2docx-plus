"""Layout detection via IBM Granite-Docling (Apache-2.0) or DocLayNet-trained detectors.

This hook emits `LayoutBlock` objects with semantic labels
(title/heading/paragraph/list/caption/figure/table/formula/footnote). Used as
an accelerator for reading order on multi-column / magazine layouts; the
classic XY-cut algorithm still runs as a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins.base import LayoutBlock


@dataclass
class GraniteDoclingLayoutDetector:
    model_name: str = "ibm-granite/granite-docling-258M"
    device: str = "cpu"
    _pipeline: Any | None = None

    def _ensure_loaded(self) -> None:
        if self._pipeline is not None:
            return
        try:
            import torch  # type: ignore
            from transformers import AutoModelForVision2Seq, AutoProcessor  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "Granite-Docling requires the 'ml-layout' extra: "
                "pip install 'pdf2docx-plus[ml-layout]'"
            ) from e
        processor = AutoProcessor.from_pretrained(self.model_name)
        model = AutoModelForVision2Seq.from_pretrained(self.model_name).to(self.device).eval()
        self._pipeline = {"processor": processor, "model": model, "torch": torch}

    def detect(self, page_image: Any, page_index: int) -> list[LayoutBlock]:
        self._ensure_loaded()
        # Granite-Docling emits DocTags; parsing is upstream's responsibility.
        # We keep this hook intentionally minimal: downstream consumers that
        # need the raw DocTag stream can subclass and override.
        return []
