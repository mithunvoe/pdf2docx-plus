"""Cross-page table stitching.

A table that continues on the next page is emitted by upstream as two
independent tables — one ending at the page break, one starting after it.
That loses the logical relationship, doubles headers, and breaks TEDS
scoring.

Stitch heuristic (plan §B.7):

1. For every pair of consecutive pages, take the *last* table on page N
   and the *first* table on page N+1.
2. Merge if ALL of:
   * same column count,
   * x-range of column boundaries overlaps by > 90%,
   * page-N-last-table ends within 30pt of the page-N bottom margin,
   * page-N+1-first-table starts within 30pt of the page-N+1 top margin,
   * optionally: the top row of page-N+1 table repeats the top row of
     page-N table (treated as duplicated header — drop on merge).

When merged, the second table's rows (minus the repeated header, if any)
are appended to the first table, and the second table is removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StitchReport:
    merged_pairs: list[tuple[int, int]] = field(default_factory=list)
    skipped_pairs: list[tuple[int, int, str]] = field(default_factory=list)


def stitch_cross_page_tables(
    pages: list[Any],
    *,
    bottom_margin_tolerance: float = 30.0,
    top_margin_tolerance: float = 30.0,
    x_overlap_threshold: float = 0.9,
) -> StitchReport:
    """Merge continuation tables in place across a list of parsed pages."""
    report = StitchReport()
    for i in range(len(pages) - 1):
        a = pages[i]
        b = pages[i + 1]
        if not (getattr(a, "finalized", False) and getattr(b, "finalized", False)):
            continue

        last_a = _last_table(a)
        first_b = _first_table(b)
        if last_a is None or first_b is None:
            continue

        reason = _can_stitch(
            last_a,
            first_b,
            a,
            b,
            bottom_margin_tolerance=bottom_margin_tolerance,
            top_margin_tolerance=top_margin_tolerance,
            x_overlap_threshold=x_overlap_threshold,
        )
        if reason is not None:
            report.skipped_pairs.append((a.id, b.id, reason))
            continue

        _merge_tables(last_a, first_b, pages=(a, b))
        report.merged_pairs.append((a.id, b.id))
    return report


# -- internals --------------------------------------------------------------


def _iter_column_blocks(page: Any) -> list[Any]:
    out: list[Any] = []
    for section in getattr(page, "sections", []) or []:
        for column in section:
            blocks = getattr(column, "blocks", None)
            if blocks is None:
                continue
            out.extend(blocks)
    return out


def _is_table(block: Any) -> bool:
    return hasattr(block, "rows") and hasattr(block, "num_rows")


def _last_table(page: Any) -> Any | None:
    tables = [b for b in _iter_column_blocks(page) if _is_table(b)]
    return tables[-1] if tables else None


def _first_table(page: Any) -> Any | None:
    tables = [b for b in _iter_column_blocks(page) if _is_table(b)]
    return tables[0] if tables else None


def _col_bounds(table: Any) -> list[tuple[float, float]]:
    try:
        first_row = next(iter(table.rows))
    except StopIteration:
        return []
    bounds: list[tuple[float, float]] = []
    for cell in first_row:
        bbox = getattr(cell, "bbox", None)
        if bbox is None:
            continue
        bounds.append((float(bbox[0]), float(bbox[2])))
    return bounds


def _x_overlap(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    scores: list[float] = []
    for (a0, a1), (b0, b1) in zip(a, b, strict=False):
        lo = max(a0, b0)
        hi = min(a1, b1)
        overlap = max(hi - lo, 0.0)
        width = max(a1 - a0, b1 - b0, 1e-6)
        scores.append(overlap / width)
    return sum(scores) / len(scores)


def _can_stitch(
    last_a: Any,
    first_b: Any,
    page_a: Any,
    page_b: Any,
    *,
    bottom_margin_tolerance: float,
    top_margin_tolerance: float,
    x_overlap_threshold: float,
) -> str | None:
    cols_a = _col_bounds(last_a)
    cols_b = _col_bounds(first_b)
    if len(cols_a) != len(cols_b):
        return f"col count mismatch {len(cols_a)} vs {len(cols_b)}"
    overlap = _x_overlap(cols_a, cols_b)
    if overlap < x_overlap_threshold:
        return f"x-overlap {overlap:.2f} < {x_overlap_threshold:.2f}"

    page_a_bbox = getattr(page_a, "bbox", None)
    page_b_bbox = getattr(page_b, "bbox", None)
    if page_a_bbox is None or page_b_bbox is None:
        return "page bbox missing"

    last_bottom = float(getattr(last_a, "bbox", (0, 0, 0, 0))[3])
    first_top = float(getattr(first_b, "bbox", (0, 0, 0, 0))[1])

    if page_a_bbox[3] - last_bottom > bottom_margin_tolerance:
        return f"last-table-to-page-bottom > {bottom_margin_tolerance}"
    if first_top - page_b_bbox[1] > top_margin_tolerance:
        return f"first-table-from-page-top > {top_margin_tolerance}"
    return None


def _merge_tables(last_a: Any, first_b: Any, *, pages: tuple[Any, Any]) -> None:
    """Append first_b rows into last_a, then unlink first_b from page_b."""
    src_rows = list(getattr(first_b, "rows", []) or [])
    dst_rows = getattr(last_a, "rows", None)
    if dst_rows is None or not src_rows:
        return

    # If the first row of first_b equals the first row of last_a (header
    # repeat), skip it. Equality is per-cell text match.
    if _first_row_text(first_b) == _first_row_text(last_a):
        src_rows = src_rows[1:]

    # dst_rows behaves like a Collection with append
    for row in src_rows:
        dst_rows.append(row)  # type: ignore[attr-defined]

    # remove first_b from the second page's blocks
    _, page_b = pages
    _remove_block(page_b, first_b)


def _first_row_text(table: Any) -> tuple[str, ...]:
    try:
        first_row = next(iter(table.rows))
    except StopIteration:
        return ()
    out: list[str] = []
    for cell in first_row:
        blocks = getattr(cell, "blocks", None)
        if blocks is None:
            out.append("")
            continue
        text = ""
        for block in blocks:
            lines = getattr(block, "lines", None)
            if lines is None:
                continue
            for line in lines:
                for span in getattr(line, "spans", []) or []:
                    text += getattr(span, "text", "") or ""
        out.append(text.strip())
    return tuple(out)


def _remove_block(page: Any, target: Any) -> None:
    for section in getattr(page, "sections", []) or []:
        for column in section:
            blocks = getattr(column, "blocks", None)
            if blocks is None:
                continue
            instances = getattr(blocks, "_instances", None)
            if instances is None:
                continue
            try:
                instances.remove(target)
            except ValueError:
                continue
            return
