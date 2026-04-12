"""Microsoft Table Transformer (TATR, MIT) as a `TableDetector`.

This is a thin wrapper around the HuggingFace `microsoft/table-transformer-*`
checkpoints. Heavy deps (`torch`, `transformers`, `timm`) are loaded lazily.

Model choice:
    * `microsoft/table-transformer-detection` -> table region detection
    * `microsoft/table-transformer-structure-recognition-v1.1-all` -> structure

Voting strategy (see plan §B.6): this detector runs alongside the built-in
ruling-line lattice detector. Callers pick a threshold: if the number of
detected ruling-lines is below it, they prefer TATR's output; otherwise keep
the ruling-line result.

Weights are Apache-2.0 / MIT compatible; safe for commercial use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..plugins.base import TableRegion


@dataclass
class TableTransformerDetector:
    detection_model: str = "microsoft/table-transformer-detection"
    structure_model: str = "microsoft/table-transformer-structure-recognition-v1.1-all"
    device: str = "cpu"
    detection_threshold: float = 0.85
    _pipelines: dict[str, Any] | None = None

    def _ensure_loaded(self) -> None:
        if self._pipelines is not None:
            return
        try:
            import torch  # type: ignore
            from transformers import (  # type: ignore
                AutoImageProcessor,
                TableTransformerForObjectDetection,
            )
        except ImportError as e:
            raise RuntimeError(
                "Table Transformer support requires the 'ml-tables' extra: "
                "pip install 'pdf2docx-plus[ml-tables]'"
            ) from e

        det_proc = AutoImageProcessor.from_pretrained(self.detection_model)
        det_model = TableTransformerForObjectDetection.from_pretrained(self.detection_model)
        det_model.to(self.device).eval()

        str_proc = AutoImageProcessor.from_pretrained(self.structure_model)
        str_model = TableTransformerForObjectDetection.from_pretrained(self.structure_model)
        str_model.to(self.device).eval()

        self._pipelines = {
            "det_proc": det_proc,
            "det_model": det_model,
            "str_proc": str_proc,
            "str_model": str_model,
            "torch": torch,
        }

    def detect(
        self,
        page_image: Any,
        page_index: int,
        page_bbox: tuple[float, float, float, float],
    ) -> list[TableRegion]:
        self._ensure_loaded()
        assert self._pipelines is not None
        torch = self._pipelines["torch"]
        det_proc = self._pipelines["det_proc"]
        det_model = self._pipelines["det_model"]

        inputs = det_proc(images=page_image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = det_model(**inputs)

        target_sizes = torch.tensor([page_image.size[::-1]])
        results = det_proc.post_process_object_detection(
            outputs, threshold=self.detection_threshold, target_sizes=target_sizes
        )[0]

        regions: list[TableRegion] = []
        page_w = page_bbox[2] - page_bbox[0]
        page_h = page_bbox[3] - page_bbox[1]
        img_w, img_h = page_image.size
        sx = page_w / img_w
        sy = page_h / img_h

        for score, box in zip(results["scores"].tolist(), results["boxes"].tolist(), strict=False):
            x0, y0, x1, y1 = box
            regions.append(
                TableRegion(
                    page_index=page_index,
                    bbox=(
                        page_bbox[0] + x0 * sx,
                        page_bbox[1] + y0 * sy,
                        page_bbox[0] + x1 * sx,
                        page_bbox[1] + y1 * sy,
                    ),
                    confidence=float(score),
                )
            )
        return regions
