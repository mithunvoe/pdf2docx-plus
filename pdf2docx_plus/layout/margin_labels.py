"""Detect and consolidate rotated margin labels.

PDFs often carry a rotated text frame in the page margin - a
``"Confidential"`` stamp on the left, a ``"DRAFT"`` watermark on the
right, a SFC document-control reference printed vertically along the
binding edge.  Upstream emits these as floating anchors with the text
wrapped in a text-frame element; downstream layout passes have to
guess at how to keep them attached to the surrounding content, and
the floating anchors don't survive normalisation passes that flatten
sections or align column boundaries.

This module identifies such blocks during the post-parse enrichment
step so callers can choose to:

  * drop them from the body (the cleanest output for diffing PDFs
    where the only changes are content, not margin chrome);
  * keep them but mark them so downstream tools know which paragraphs
    are decorative vs body content.

Detection heuristic (deliberately conservative):

  * vertical text direction (``is_vertical_text``), or
  * a normal-direction TextBlock whose bbox is narrow (width < 50pt)
    AND has aspect ratio > 4 (tall and thin),

  AND the bbox sits within ``margin_band_pt`` of the page's left or
  right edge,

  AND the block contains < 80 characters of text.

The detection result is a list of ``MarginLabel`` records; the caller
decides whether to remove or annotate them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MarginLabel:
    page_id: int
    text: str
    bbox: tuple[float, float, float, float]
    edge: str  # "left" | "right"


def detect_margin_labels(
    pages: list[Any],
    *,
    margin_band_pt: float = 50.0,
    min_aspect_ratio: float = 4.0,
    max_label_chars: int = 80,
    max_label_width: float = 50.0,
) -> list[MarginLabel]:
    """Walk parsed pages and return the candidates that look like margin labels.

    Args:
        pages: parsed pages in document order; only finalized pages
            contribute candidates.
        margin_band_pt: vertical band from the left/right edges (in
            points) within which a block is considered a margin
            candidate.
        min_aspect_ratio: minimum bbox height / width ratio for a
            tall-narrow block to be considered.
        max_label_chars: skip any block whose textual content is
            longer than this; long bodies are body content, not
            labels.
        max_label_width: skip blocks whose bbox width exceeds this
            (in points); a real margin label is always narrow.
    """
    results: list[MarginLabel] = []
    for page in pages:
        if not getattr(page, "finalized", False):
            continue
        page_bbox = getattr(page, "bbox", None)
        if page_bbox is None:
            continue
        left_edge = float(page_bbox[0])
        right_edge = float(page_bbox[2])
        for block in _iter_text_blocks(page):
            bbox = getattr(block, "bbox", None)
            if bbox is None:
                continue
            try:
                x0, y0, x1, y1 = (float(b) for b in bbox)
            except (TypeError, ValueError, IndexError):
                continue
            width = x1 - x0
            height = y1 - y0
            if width <= 0 or height <= 0:
                continue
            if width > max_label_width:
                continue
            aspect = height / max(width, 1e-3)
            is_vertical = bool(getattr(block, "is_vertical_text", False))
            if not is_vertical and aspect < min_aspect_ratio:
                continue
            text = _block_text(block).strip()
            if not text or len(text) > max_label_chars:
                continue
            edge: str
            if x0 - left_edge < margin_band_pt:
                edge = "left"
            elif right_edge - x1 < margin_band_pt:
                edge = "right"
            else:
                continue
            results.append(
                MarginLabel(
                    page_id=getattr(page, "id", -1),
                    text=text,
                    bbox=(x0, y0, x1, y1),
                    edge=edge,
                )
            )
    return results


def drop_margin_labels(pages: list[Any]) -> int:
    """Remove every margin-label block from the parsed page layout.

    Returns the number of blocks removed.
    """
    candidates = detect_margin_labels(pages)
    if not candidates:
        return 0
    candidate_lookup = {
        (lbl.page_id, lbl.bbox): True for lbl in candidates
    }
    removed = 0
    for page in pages:
        if not getattr(page, "finalized", False):
            continue
        page_id = getattr(page, "id", -1)
        for section in getattr(page, "sections", []) or []:
            for column in section:
                blocks = getattr(column, "blocks", None)
                instances = getattr(blocks, "_instances", None) if blocks else None
                if instances is None:
                    continue
                for block in list(instances):
                    bbox = getattr(block, "bbox", None)
                    if bbox is None:
                        continue
                    try:
                        key = (page_id, (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])))
                    except (TypeError, ValueError, IndexError):
                        continue
                    if key in candidate_lookup:
                        instances.remove(block)
                        removed += 1
    return removed


def _iter_text_blocks(page: Any) -> list[Any]:
    out: list[Any] = []
    for section in getattr(page, "sections", []) or []:
        for column in section:
            blocks = getattr(column, "blocks", None)
            if blocks is None:
                continue
            for block in blocks:
                if hasattr(block, "lines"):
                    out.append(block)
    return out


def _block_text(block: Any) -> str:
    lines = getattr(block, "lines", None)
    if lines is None:
        return ""
    parts: list[str] = []
    for line in lines:
        for span in getattr(line, "spans", None) or []:
            parts.append(getattr(span, "text", "") or "")
    return "".join(parts)
