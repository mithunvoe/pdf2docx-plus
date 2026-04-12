"""Plugin protocols.

All types are `Protocol`s rather than ABCs, so any duck-typed object with the
right methods can register. This keeps the API friendly to simple functions
wrapped in a small shim as well as richer classes with state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TableRegion:
    """A detected table bounding box in PDF coords (points, origin top-left)."""

    page_index: int
    bbox: tuple[float, float, float, float]
    confidence: float = 1.0
    rows: int | None = None
    cols: int | None = None
    cells: tuple[tuple[float, float, float, float], ...] | None = None


@dataclass(frozen=True)
class LayoutBlock:
    page_index: int
    bbox: tuple[float, float, float, float]
    label: str  # "title" | "heading" | "paragraph" | "list" | "caption" | "figure" | "table" | "formula" | "footnote"
    reading_order: int = 0
    confidence: float = 1.0


@runtime_checkable
class TableDetector(Protocol):
    """Given a page image + raw text blocks, return candidate table regions."""

    def detect(
        self, page_image: Any, page_index: int, page_bbox: tuple[float, float, float, float]
    ) -> list[TableRegion]: ...


@runtime_checkable
class LayoutDetector(Protocol):
    """Given a page image, return reading-order-sorted layout blocks."""

    def detect(self, page_image: Any, page_index: int) -> list[LayoutBlock]: ...


@runtime_checkable
class OcrEngine(Protocol):
    """OCR an image region and return plain UTF-8 text."""

    def recognize(self, image: Any, *, lang: str | None = None) -> str: ...


@runtime_checkable
class FormulaRecognizer(Protocol):
    """Convert a formula image to an Office Math Markup (OMML) XML string."""

    def to_omml(self, image: Any) -> str: ...
