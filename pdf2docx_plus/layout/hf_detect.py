"""Header / footer detection by repeated-region analysis.

Heuristic (matches the "repeat-region" strategy in the plan §C.13):

For every parsed page, look at the topmost and bottommost `TextBlock`
within the page margins. A block is marked as *header* / *footer* when:

1. Its bounding box (rounded to 2pt) appears at the same relative y-offset
   on at least `ratio` of all pages.
2. The normalised text (digits and page-numbering tokens removed) matches
   across those pages.

Blocks flagged as header/footer are stripped from the body layout and
returned as a separate record. They can then be emitted into the DOCX
section's `w:hdr` / `w:ftr` parts (caller's responsibility — python-docx
sections already exist; this module just identifies the blocks).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

_PAGE_NUM = re.compile(r"(?:page\s*)?\d+(?:\s*/\s*\d+)?", re.IGNORECASE)
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class HeaderFooter:
    text: str
    bbox: tuple[float, float, float, float]
    is_header: bool
    page_ids: tuple[int, ...]


def _norm(text: str) -> str:
    # collapse whitespace, strip page numbers so "Page 3 / 10" matches "Page 4 / 10"
    t = _PAGE_NUM.sub("#", text)
    return _WS.sub(" ", t).strip()


def detect_header_footer(
    pages: list[Any], *, ratio: float = 0.3, band_pt: float = 72.0
) -> list[HeaderFooter]:
    """Return the header/footer blocks across a parsed `pages` list.

    Args:
        pages: a list of `pdf2docx.page.Page` objects after `parse()`.
        ratio: minimum fraction of pages a block must repeat on to count.
        band_pt: vertical band (in points) from the top/bottom within which
            a block is considered for header/footer classification.
    """
    if len(pages) < max(3, int(1 / ratio) + 1):
        return []

    top_candidates: Counter[tuple[str, int]] = Counter()
    bottom_candidates: Counter[tuple[str, int]] = Counter()
    top_examples: dict[tuple[str, int], HeaderFooter] = {}
    bottom_examples: dict[tuple[str, int], HeaderFooter] = {}
    top_pages: dict[tuple[str, int], list[int]] = {}
    bottom_pages: dict[tuple[str, int], list[int]] = {}

    for page in pages:
        if not getattr(page, "finalized", False):
            continue
        text_blocks = _iter_text_blocks(page)
        page_bbox = _page_bbox(page)
        if page_bbox is None:
            continue
        page_top = page_bbox[1]
        page_bottom = page_bbox[3]

        for block in text_blocks:
            bbox = tuple(getattr(block, "bbox", (0, 0, 0, 0)))
            if len(bbox) != 4:
                continue
            y_center = (bbox[1] + bbox[3]) / 2
            text = _norm(_block_text(block))
            if not text:
                continue
            bucket = (text, round(bbox[1]))
            if y_center - page_top <= band_pt:
                top_candidates[bucket] += 1
                top_pages.setdefault(bucket, []).append(page.id)
                top_examples.setdefault(
                    bucket,
                    HeaderFooter(text=text, bbox=bbox, is_header=True, page_ids=()),
                )
            elif page_bottom - y_center <= band_pt:
                bottom_candidates[bucket] += 1
                bottom_pages.setdefault(bucket, []).append(page.id)
                bottom_examples.setdefault(
                    bucket,
                    HeaderFooter(text=text, bbox=bbox, is_header=False, page_ids=()),
                )

    threshold = max(2, int(len(pages) * ratio))
    results: list[HeaderFooter] = []
    for bucket, count in top_candidates.items():
        if count >= threshold:
            ex = top_examples[bucket]
            results.append(
                HeaderFooter(
                    text=ex.text,
                    bbox=ex.bbox,
                    is_header=True,
                    page_ids=tuple(top_pages[bucket]),
                )
            )
    for bucket, count in bottom_candidates.items():
        if count >= threshold:
            ex = bottom_examples[bucket]
            results.append(
                HeaderFooter(
                    text=ex.text,
                    bbox=ex.bbox,
                    is_header=False,
                    page_ids=tuple(bottom_pages[bucket]),
                )
            )
    return results


def _iter_text_blocks(page: Any) -> list[Any]:
    """Walk page -> sections -> columns -> blocks and yield text-like blocks."""
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


def _page_bbox(page: Any) -> tuple[float, float, float, float] | None:
    bbox = getattr(page, "bbox", None)
    if bbox is None:
        return None
    try:
        return (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    except (TypeError, IndexError):
        return None
