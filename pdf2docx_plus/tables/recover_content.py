"""Recover content lost to pathological lattice-table parsing.

Some PDFs draw a single outer rectangle around the entire page content
(common in regulatory / fund-document templates: KFS, prospectuses).
Upstream's lattice-table detector treats that rectangle as a table
boundary, producing a "page-sized table" with rows spanning huge
vertical ranges.  Text blocks inside that mega-table that straddle
the detected cell boundaries get silently dropped during cell
assignment: ``Layout._assign_block`` requires a ``FACTOR_MAJOR`` (~70%)
overlap to add a block to a cell, and a block that crosses the
detected cell boundary fits no cell well enough.  Result: whole
sections of page content vanish from the DOCX output.

Observed example: ``New_KFS_Bosera USD Money Market ETF.pdf`` page 8.
The page has a decorative outer rectangle ``(28, 36, 529, 787)`` and
an inner fee table at ``(33, 116, 516, 258)``.  The detector latches
onto the outer rectangle and produces a 3-row mega-table whose cells
are tiny in y (Row 0 cells are 22pt tall) but the row itself is
322pt tall.  All text blocks at y=62-358 - the entire "Ongoing fees
payable by the Sub-Fund" section, with its own embedded table - get
dropped because they don't fit any of the 4 narrow cells.

Fix strategy:

1. After parsing each page, identify pathological tables -
   tables whose bbox covers > 70% of the page area AND that have <= 6
   rows but at least one row whose tallest cell is >= 4x the
   shortest cell.  Those signatures identify the malformed
   "outer-rectangle-as-table" case while leaving genuine page-sized
   tables (typed forms with uniform row heights) untouched.

2. For each pathological table, re-extract the raw text blocks from
   the underlying fitz page that fall inside the table bbox but are
   not already captured in any cell.  Convert them to ``TextBlock``
   instances and add them to the column's block list.  The table
   itself is preserved because dropping it would also discard the
   cells that DID capture content correctly (the "Redemption fee |
   Nil" row in the KFS example).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecoveryReport:
    pathological_tables: list[tuple[int, tuple[float, float, float, float]]] = field(default_factory=list)
    blocks_recovered: int = 0


def recover_pathological_tables(
    pages: list[Any],
    fitz_doc: Any,
    *,
    page_area_threshold: float = 0.70,
    max_rows: int = 6,
    cell_height_ratio: float = 4.0,
) -> RecoveryReport:
    """Detect pathological lattice tables in ``pages`` and recover lost text.

    Args:
        pages: parsed pages in document order; only finalized pages
            with bbox metadata contribute.
        fitz_doc: the underlying ``fitz.Document`` so we can re-read
            raw text blocks where upstream's cell assignment dropped
            them.
        page_area_threshold: a table whose bbox covers more than this
            fraction of the page area is a candidate for the
            "pathological" check.
        max_rows: candidates must have at most this many rows.
        cell_height_ratio: within at least one row, the tallest cell
            must be >= ``cell_height_ratio`` times the shortest cell
            for the row to count as malformed.
    """
    report = RecoveryReport()
    text_block_cls = _find_textblock_class()
    line_cls = _find_line_class()
    span_cls = _find_textspan_class()
    if text_block_cls is None or line_cls is None or span_cls is None:
        return report

    for page in pages:
        if not getattr(page, "finalized", False):
            continue
        page_bbox = getattr(page, "bbox", None)
        if page_bbox is None:
            continue
        page_w = float(page_bbox[2]) - float(page_bbox[0])
        page_h = float(page_bbox[3]) - float(page_bbox[1])
        page_area = max(page_w * page_h, 1.0)

        for section in getattr(page, "sections", []) or []:
            for column in section:
                blocks_collection = getattr(column, "blocks", None)
                instances = getattr(blocks_collection, "_instances", None)
                if instances is None:
                    continue
                for block in list(instances):
                    if not getattr(block, "is_table_block", False):
                        continue
                    if not _is_pathological(
                        block, page_area, page_area_threshold, max_rows, cell_height_ratio
                    ):
                        continue
                    page_id = getattr(page, "id", -1)
                    bb = block.bbox
                    report.pathological_tables.append(
                        (
                            page_id,
                            (float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])),
                        )
                    )
                    added = _recover_missing_blocks(
                        page=page,
                        fitz_doc=fitz_doc,
                        table=block,
                        instances=instances,
                        text_block_cls=text_block_cls,
                        line_cls=line_cls,
                        span_cls=span_cls,
                    )
                    report.blocks_recovered += added
    return report


def _is_pathological(
    table: Any,
    page_area: float,
    page_area_threshold: float,
    max_rows: int,
    cell_height_ratio: float,
) -> bool:
    """Return True when the table fits the pathological-lattice pattern."""
    bbox = getattr(table, "bbox", None)
    if bbox is None:
        return False
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return False
    table_area = max((x1 - x0) * (y1 - y0), 1.0)
    if table_area / page_area < page_area_threshold:
        return False

    rows = getattr(table, "_rows", None)
    if rows is None:
        return False
    row_list = list(rows)
    if not row_list or len(row_list) > max_rows:
        return False

    for row in row_list:
        cells = [c for c in row if c is not None and getattr(c, "bbox", None) is not None]
        heights: list[float] = []
        for c in cells:
            cb = c.bbox
            try:
                heights.append(float(cb[3]) - float(cb[1]))
            except (TypeError, ValueError):
                continue
        if len(heights) < 2:
            continue
        tallest = max(heights)
        nonzero = [h for h in heights if h > 0]
        if not nonzero:
            continue
        shortest = min(nonzero)
        if shortest > 0 and tallest / shortest >= cell_height_ratio:
            return True
    return False


def _recover_missing_blocks(
    *,
    page: Any,
    fitz_doc: Any,
    table: Any,
    instances: list,
    text_block_cls: Any,
    line_cls: Any,
    span_cls: Any,
) -> int:
    """Add raw text blocks under ``table``'s bbox that aren't already captured.

    Returns the number of blocks added.  The recovered TextBlock is
    inserted into ``instances`` (the column's _instances list) at the
    position that keeps document reading order roughly correct.
    """
    page_id = getattr(page, "id", -1)
    if page_id < 0 or page_id >= len(fitz_doc):
        return 0
    fitz_page = fitz_doc[page_id]
    raw = fitz_page.get_text("dict")
    raw_blocks = [b for b in raw.get("blocks", []) if b.get("type") == 0]

    table_bbox = table.bbox
    captured_bboxes = _captured_text_bboxes(table)

    new_blocks: list[Any] = []
    for raw_block in raw_blocks:
        bb = raw_block.get("bbox")
        if not bb:
            continue
        if not _bbox_contained(bb, table_bbox, pad=2.0):
            continue
        if _bbox_intersects_any(bb, captured_bboxes, threshold=0.3):
            continue
        new_block = _raw_to_text_block(
            raw_block,
            text_block_cls=text_block_cls,
            line_cls=line_cls,
            span_cls=span_cls,
        )
        if new_block is None:
            continue
        new_blocks.append(new_block)

    if not new_blocks:
        return 0

    # Insert in y-order; place each new block just before the table
    # (the table represents the entire page area, so inserting before
    # keeps reading order close to natural top-to-bottom).
    try:
        idx = instances.index(table)
    except ValueError:
        idx = len(instances)
    new_blocks.sort(key=lambda b: (b.bbox.y0, b.bbox.x0))
    for i, b in enumerate(new_blocks):
        instances.insert(idx + i, b)
    return len(new_blocks)


def _captured_text_bboxes(table: Any) -> list[tuple[float, float, float, float]]:
    """Return the bbox of every block currently sitting inside a cell."""
    out: list[tuple[float, float, float, float]] = []
    rows = getattr(table, "_rows", None)
    if rows is None:
        return out
    for row in rows:
        for cell in row:
            if cell is None:
                continue
            blocks = getattr(cell, "blocks", None)
            if blocks is None:
                continue
            for b in blocks:
                bb = getattr(b, "bbox", None)
                if bb is None:
                    continue
                try:
                    out.append(
                        (float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3]))
                    )
                except (TypeError, ValueError):
                    continue
    return out


def _bbox_contained(
    inner: Any,
    outer: Any,
    pad: float = 0.0,
) -> bool:
    try:
        ox0, oy0, ox1, oy1 = (float(outer[i]) for i in range(4))
        ix0, iy0, ix1, iy1 = (float(inner[i]) for i in range(4))
    except (TypeError, ValueError, IndexError):
        return False
    return (
        ix0 >= ox0 - pad
        and iy0 >= oy0 - pad
        and ix1 <= ox1 + pad
        and iy1 <= oy1 + pad
    )


def _bbox_intersects_any(
    candidate: Any,
    others: list[tuple[float, float, float, float]],
    *,
    threshold: float,
) -> bool:
    try:
        cx0, cy0, cx1, cy1 = (float(candidate[i]) for i in range(4))
    except (TypeError, ValueError, IndexError):
        return False
    cw = max(cx1 - cx0, 1e-3)
    ch = max(cy1 - cy0, 1e-3)
    c_area = cw * ch
    for o in others:
        ox0, oy0, ox1, oy1 = o
        ix0 = max(cx0, ox0)
        iy0 = max(cy0, oy0)
        ix1 = min(cx1, ox1)
        iy1 = min(cy1, oy1)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        i_area = (ix1 - ix0) * (iy1 - iy0)
        if i_area / c_area >= threshold:
            return True
    return False


def _raw_to_text_block(
    raw_block: dict,
    *,
    text_block_cls: Any,
    line_cls: Any,
    span_cls: Any,
) -> Any:
    """Convert a fitz raw text block dict to an upstream ``TextBlock``."""
    try:
        block = text_block_cls()
        bb = raw_block.get("bbox")
        if bb is None:
            return None
        block.update_bbox(tuple(float(v) for v in bb))
        for raw_line in raw_block.get("lines", []) or []:
            line = line_cls()
            lb = raw_line.get("bbox")
            if lb is None:
                continue
            line.update_bbox(tuple(float(v) for v in lb))
            spans = raw_line.get("spans", []) or []
            for raw_span in spans:
                span = span_cls(raw_span)
                line.add(span)
            block.add(line)
        return block
    except Exception:  # pragma: no cover - defensive
        return None


def _find_textblock_class():
    try:
        from pdf2docx_plus._vendored.pdf2docx.text.TextBlock import TextBlock

        return TextBlock
    except ImportError:
        return None


def _find_line_class():
    try:
        from pdf2docx_plus._vendored.pdf2docx.text.Line import Line

        return Line
    except ImportError:
        return None


def _find_textspan_class():
    try:
        from pdf2docx_plus._vendored.pdf2docx.text.TextSpan import TextSpan

        return TextSpan
    except ImportError:
        return None
