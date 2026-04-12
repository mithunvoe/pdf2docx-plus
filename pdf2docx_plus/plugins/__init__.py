"""Plugin / extension surface.

The pipeline exposes four extension points so downstream apps can swap
behaviour without forking the package:

* `TableDetector`   -> override/augment table region detection
* `LayoutDetector`  -> override reading-order / block-type classification
* `OcrEngine`       -> run OCR on pages lacking a text layer
* `FormulaRecognizer` -> convert formula image regions to OMML

Consumers register implementations on a `PluginRegistry` and pass it to
`Converter(plugins=...)`. The defaults are the classic heuristic path, so the
registry is always safe to leave empty.
"""

from __future__ import annotations

from .base import (
    FormulaRecognizer,
    LayoutBlock,
    LayoutDetector,
    OcrEngine,
    TableDetector,
    TableRegion,
)
from .registry import PluginRegistry

__all__ = [
    "FormulaRecognizer",
    "LayoutBlock",
    "LayoutDetector",
    "OcrEngine",
    "PluginRegistry",
    "TableDetector",
    "TableRegion",
]
