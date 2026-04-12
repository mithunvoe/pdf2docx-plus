"""Detect scanned / text-less PDF pages.

Heuristic: a born-digital page of A4 has on the order of 1-5 chars per
point² of text area. A scanned page stored as a single image has ~0
characters but a large image area.

We compute, per page, `char_density = len(text.strip()) / page_area_pt2`.
Pages with density < `threshold` AND at least one large image are
classified as scanned.

The detector is intentionally conservative — false negatives (missing a
scanned page) are worse than false positives (running OCR on a page that
didn't need it).
"""

from __future__ import annotations

from dataclasses import dataclass

import fitz  # type: ignore


@dataclass(frozen=True)
class ScannedPageReport:
    page_index: int
    is_scanned: bool
    char_count: int
    image_area_ratio: float
    density_per_1000pt2: float


def detect_scanned_pages(
    doc: fitz.Document,
    *,
    density_threshold: float = 0.05,
    image_area_ratio: float = 0.5,
) -> list[ScannedPageReport]:
    """Return a per-page report for `doc`.

    Args:
        density_threshold: char density (per 1000 pt²) below which a page
            is a scan candidate.
        image_area_ratio: fraction of page area covered by images above
            which a candidate is confirmed as scanned.
    """
    reports: list[ScannedPageReport] = []
    for i, page in enumerate(doc):
        rect = page.rect
        page_area = max(rect.width * rect.height, 1.0)
        text = page.get_text().strip()
        char_count = len(text)

        image_area = 0.0
        for block in page.get_text("dict").get("blocks", []) or []:
            if block.get("type") != 1:  # type 1 = image
                continue
            b = block.get("bbox")
            if b is None:
                continue
            w = max(b[2] - b[0], 0.0)
            h = max(b[3] - b[1], 0.0)
            image_area += w * h

        ratio = image_area / page_area
        density = char_count / page_area * 1000
        is_scanned = density < density_threshold and ratio >= image_area_ratio
        reports.append(
            ScannedPageReport(
                page_index=i,
                is_scanned=is_scanned,
                char_count=char_count,
                image_area_ratio=ratio,
                density_per_1000pt2=density,
            )
        )
    return reports
