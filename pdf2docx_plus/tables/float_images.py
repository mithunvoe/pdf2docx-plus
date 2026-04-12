"""Suppress page-level floating images that sit entirely inside a table cell.

Upstream #299: when a table cell contains an image, `pdf2docx` extracts
the image as a page-level `ImageBlock` AND keeps a copy inside the cell.
Word then renders the image twice — once floating, once in the cell.

This pass walks the parsed page, collects every table cell's bounding box,
and drops any non-cell `ImageBlock` whose bbox is fully contained within a
cell bbox.
"""

from __future__ import annotations

from typing import Any


def _cell_bboxes(page: Any) -> list[tuple[float, float, float, float]]:
    out: list[tuple[float, float, float, float]] = []
    for block in _iter_blocks(page):
        if not hasattr(block, "rows"):
            continue
        for row in block.rows:
            for cell in row:
                bbox = getattr(cell, "bbox", None)
                if bbox is None:
                    continue
                try:
                    out.append((float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])))
                except (TypeError, IndexError):
                    continue
    return out


def _iter_blocks(page: Any) -> list[Any]:
    out: list[Any] = []
    for section in getattr(page, "sections", []) or []:
        for column in section:
            blocks = getattr(column, "blocks", None)
            if blocks is None:
                continue
            out.extend(blocks)
    return out


def _is_image_block(block: Any) -> bool:
    # Duck-type: ImageBlock has `image` attribute but no `lines` and no `rows`.
    return hasattr(block, "image") and not hasattr(block, "lines") and not hasattr(block, "rows")


def _contained(
    inner: tuple[float, float, float, float],
    outer: tuple[float, float, float, float],
    pad: float = 1.0,
) -> bool:
    return (
        inner[0] >= outer[0] - pad
        and inner[1] >= outer[1] - pad
        and inner[2] <= outer[2] + pad
        and inner[3] <= outer[3] + pad
    )


def demote_floating_images_in_cells(page: Any) -> int:
    """Remove page-level ImageBlocks fully enclosed by a table cell bbox.

    Returns the number of removed blocks.
    """
    cells = _cell_bboxes(page)
    if not cells:
        return 0

    removed = 0
    for section in getattr(page, "sections", []) or []:
        for column in section:
            blocks = getattr(column, "blocks", None)
            instances = getattr(blocks, "_instances", None) if blocks else None
            if instances is None:
                continue
            for block in list(instances):
                if not _is_image_block(block):
                    continue
                bbox = getattr(block, "bbox", None)
                if bbox is None:
                    continue
                try:
                    b = (
                        float(bbox[0]),
                        float(bbox[1]),
                        float(bbox[2]),
                        float(bbox[3]),
                    )
                except (TypeError, IndexError):
                    continue
                if any(_contained(b, cell) for cell in cells):
                    instances.remove(block)
                    removed += 1
    return removed
