"""Registry + dispatch helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..logging import get_logger
from .base import FormulaRecognizer, LayoutDetector, OcrEngine, TableDetector

_log = get_logger("plugins")

PageCallback = Callable[[Any], None]


@dataclass
class PluginRegistry:
    table_detectors: list[TableDetector] = field(default_factory=list)
    layout_detectors: list[LayoutDetector] = field(default_factory=list)
    ocr_engines: list[OcrEngine] = field(default_factory=list)
    formula_recognizers: list[FormulaRecognizer] = field(default_factory=list)
    page_callbacks: list[PageCallback] = field(default_factory=list)

    def add_table_detector(self, d: TableDetector) -> None:
        self.table_detectors.append(d)

    def add_layout_detector(self, d: LayoutDetector) -> None:
        self.layout_detectors.append(d)

    def add_ocr_engine(self, e: OcrEngine) -> None:
        self.ocr_engines.append(e)

    def add_formula_recognizer(self, r: FormulaRecognizer) -> None:
        self.formula_recognizers.append(r)

    def on_page_parsed(self, cb: PageCallback) -> None:
        self.page_callbacks.append(cb)

    def dispatch_page_parsed(self, page: Any) -> None:
        for cb in self.page_callbacks:
            try:
                cb(page)
            except Exception:  # never let a plugin kill a conversion
                _log.warning("plugin page callback failed", exc_info=True)
