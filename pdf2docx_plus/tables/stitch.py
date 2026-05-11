"""Cross-page table stitching + intra-table row continuation merging.

Upstream emits a continuation table as two independent
``TableBlock`` instances - one ending at the page break, one starting
after it.  That doubles headers, breaks TEDS scoring, and (in
documents where every page carries the same header image) fragments a
single Q&A list into one table per page.  Downstream tools then have
to glue the pieces back together; this module does it once, here.

What we merge:

1.  **Cross-page table stitching** (plan §B.7) - the *last* table on
    page N and the *first* table on page N+1 are merged when:

    * column count matches exactly,
    * the x-range of column boundaries overlaps by > 90%,
    * EITHER the last table ends within 30pt of the page-N bottom
      margin AND the next table starts within 30pt of the page-N+1 top
      margin, OR there's no non-image, non-header/footer body content
      between the table and the page edge (handles documents whose
      every page has a header/footer image - the page-image strip
      pushed the table away from the literal page edge but logically
      the table still occupies the full content area).
    * the second table's first row is dropped if it textually
      duplicates the first table's first row (repeated header).

2.  **Intra-table row continuation** (paragraph 12 in the user's pain
    list).  When a single table row's content wraps onto the next
    page, upstream emits two rows:

      Row A (page N, last row): the canonical row, all cells full.
      Row B (page N+1, first row of next table): one cell carries the
        wrapped tail; every other cell is empty.

    After stitching, the two rows sit next to each other in the same
    table; we coalesce them by appending Row B's non-empty cell text
    into the corresponding cell of Row A and dropping Row B.

The continuation merge runs only on table fragments we just stitched.
We do NOT touch tables that were already a single ``TableBlock`` -
those are upstream's natural rows and any "mostly-empty row" inside
them is signal, not noise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StitchReport:
    merged_pairs: list[tuple[int, int]] = field(default_factory=list)
    skipped_pairs: list[tuple[int, int, str]] = field(default_factory=list)
    continuation_rows_merged: int = 0


def stitch_cross_page_tables(
    pages: list[Any],
    *,
    bottom_margin_tolerance: float = 30.0,
    top_margin_tolerance: float = 30.0,
    x_overlap_threshold: float = 0.9,
    image_aware: bool = True,
    header_footer_texts: set[str] | None = None,
) -> StitchReport:
    """Merge continuation tables in place across a list of parsed pages.

    Args:
        pages: parsed pages in document order; only finalized pages are
            considered.
        bottom_margin_tolerance: literal-pt distance from page bottom
            below which the last table is considered "page-edge".
        top_margin_tolerance: literal-pt distance from page top within
            which the first table is considered "page-edge".
        x_overlap_threshold: per-column x-overlap ratio averaged across
            columns; we only stitch when this exceeds the threshold.
        image_aware: when True (default), treat ``ImageBlock`` content
            between the table and the page edge as transparent (a
            page-header image doesn't disqualify the table from being
            considered page-edge content).
        header_footer_texts: optional set of normalised text strings
            (lowercased) that we've already identified as repeating
            header/footer content. When supplied, any text block whose
            text matches one of these is treated as transparent during
            the page-edge proximity check.
    """
    report = StitchReport()
    hf_set = header_footer_texts or set()
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
            image_aware=image_aware,
            header_footer_texts=hf_set,
        )
        if reason is not None:
            report.skipped_pairs.append((a.id, b.id, reason))
            continue

        rows_merged = _merge_tables(last_a, first_b, pages=(a, b))
        report.merged_pairs.append((a.id, b.id))
        report.continuation_rows_merged += rows_merged
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
    # ``TableBlock`` exposes ``num_rows`` and the iterator protocol but
    # NOT a ``rows`` attribute (rows are stored under ``_rows``); the
    # most reliable duck-type is ``is_table_block`` from upstream's
    # ``common.Block``.
    if getattr(block, "is_table_block", False):
        return True
    return hasattr(block, "num_rows") and not hasattr(block, "lines")


def _rows_of(table: Any) -> list[Any]:
    """Return the table's rows as a concrete list.

    ``TableBlock`` is iterable but doesn't expose a ``rows`` attribute.
    Some places in this module previously called ``table.rows`` -
    that's not portable. This helper centralises the access.
    """
    rows = getattr(table, "_rows", None)
    if rows is not None:
        return list(rows)
    try:
        return list(iter(table))
    except TypeError:
        return []


import re as _re

_PAGE_FOOTER_PATTERNS = (
    "last update",
    "last updated",
    "page ",
    " / ",
)

# Footnote-style leading: digit + space, then content. We accept up to
# 3 digits so footnote numbering past 99 is still recognised.
_FOOTNOTE_PREFIX = _re.compile(r"^\d{1,3}\s+\S")


def _is_image_only_block(block: Any) -> bool:
    """A block that we should treat as transparent when checking page-edge proximity.

    Includes:

    * raw ``ImageBlock`` instances,
    * ``TextBlock`` whose every line contains only ``ImageSpan``
      (upstream wraps inline images in a TextBlock),
    * very short text blocks that match the page-header / page-footer
      patterns we know upstream emits inline; those will be removed
      later by ``extract_headers_footers`` or
      ``promote_page_numbers_to_footer`` but stitching needs to
      tolerate them right now.
    """
    if getattr(block, "is_table_block", False):
        return False
    if not hasattr(block, "lines") and hasattr(block, "image"):
        return True
    lines = getattr(block, "lines", None)
    if not lines:
        return False
    # all-image lines
    all_image = True
    for line in lines:
        for span in getattr(line, "spans", []) or []:
            if not hasattr(span, "image"):
                all_image = False
                break
        if not all_image:
            break
    if all_image:
        return True
    # short text that looks like header/footer chrome
    text = _block_plain_text(block).strip()
    if not text or len(text) > 80:
        return False
    low = text.lower()
    for pat in _PAGE_FOOTER_PATTERNS:
        if pat in low:
            return True
    # bare page numbers ("12", "12/42")
    if text.replace("/", "").replace(" ", "").isdigit():
        return True
    return False


def _block_plain_text(block: Any) -> str:
    lines = getattr(block, "lines", None)
    if not lines:
        return ""
    parts: list[str] = []
    for line in lines:
        for span in getattr(line, "spans", []) or []:
            parts.append(getattr(span, "text", "") or "")
    return "".join(parts)


def _last_table(page: Any) -> Any | None:
    tables = [b for b in _iter_column_blocks(page) if _is_table(b)]
    return tables[-1] if tables else None


def _first_table(page: Any) -> Any | None:
    tables = [b for b in _iter_column_blocks(page) if _is_table(b)]
    return tables[0] if tables else None


def _col_bounds(table: Any) -> list[tuple[float, float]]:
    """Column x-bounds taken from the canonical (first non-empty) row."""
    rows = _rows_of(table)
    if not rows:
        return []
    first_row = rows[0]
    bounds: list[tuple[float, float]] = []
    for cell in first_row:
        if cell is None:
            continue
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
    image_aware: bool,
    header_footer_texts: set[str] | None = None,
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

    bottom_dist = page_a_bbox[3] - last_bottom
    top_dist = first_top - page_b_bbox[1]
    edges_ok = (
        bottom_dist <= bottom_margin_tolerance
        and top_dist <= top_margin_tolerance
    )
    if not edges_ok and image_aware:
        # be lenient when the only thing between the table and the page edge
        # is an image OR a known header/footer block (typical for
        # documents that stamp a logo on every page).
        if _between_is_only_chrome(
            page_a, last_a, edge="bottom", hf_texts=header_footer_texts or set()
        ) and _between_is_only_chrome(
            page_b, first_b, edge="top", hf_texts=header_footer_texts or set()
        ):
            edges_ok = True
    if not edges_ok:
        return (
            f"page-edge distance not satisfied "
            f"(bottom={bottom_dist:.1f} top={top_dist:.1f})"
        )
    return None


def _between_is_only_chrome(
    page: Any, table: Any, *, edge: str, hf_texts: set[str],
    body_char_budget: int = 300,
) -> bool:
    """Return True when the blocks between ``table`` and the page edge are
    only "chrome": images, page-header / page-footer pattern text,
    detected repeating header/footer blocks, or a small amount of
    ancillary body text (e.g. footnotes).

    Rationale: when a logical table is rendered across N pages and each
    page also carries a footnote of its own at the bottom, the table
    fragments should still be stitched - footnote content occupying
    < ``body_char_budget`` characters per page-edge gap is treated as
    ancillary to the table flow. A larger gap (intro paragraph,
    section heading) DOES disqualify the stitch because the next
    table is then a different logical block.

    For ``edge='bottom'`` we look at blocks below ``table``; for
    ``edge='top'`` we look at blocks above ``table``.
    """
    table_bbox = getattr(table, "bbox", None)
    if table_bbox is None:
        return False
    table_top = float(table_bbox[1])
    table_bottom = float(table_bbox[3])
    body_text_chars = 0
    for block in _iter_column_blocks(page):
        if block is table:
            continue
        bb = getattr(block, "bbox", None)
        if bb is None:
            continue
        try:
            b_top = float(bb[1])
            b_bottom = float(bb[3])
        except (TypeError, IndexError):
            continue
        if edge == "bottom" and b_top < table_bottom:
            continue
        if edge == "top" and b_bottom > table_top:
            continue
        if _is_image_only_block(block):
            continue
        text_norm = _block_plain_text(block).strip().lower()
        if not text_norm:
            continue
        # known repeating header/footer text - treat as chrome
        if text_norm in hf_texts:
            continue
        # footnote-style block (digit prefix + content) is treated as
        # transparent regardless of length. Footnotes are page-level
        # decoration; the underlying table flow continues.
        if _FOOTNOTE_PREFIX.match(text_norm):
            continue
        # accumulate ancillary body text. Long content (a real
        # section header / intro paragraph) disqualifies the stitch.
        body_text_chars += len(text_norm)
        if body_text_chars > body_char_budget:
            return False
    return True


def _merge_tables(last_a: Any, first_b: Any, *, pages: tuple[Any, Any]) -> int:
    """Append first_b rows into last_a, then unlink first_b from page_b.

    Returns the number of intra-table continuation rows we coalesced
    while merging (the rows where second-table-row carries wrap-over
    content for a partially-empty first-table-row).
    """
    src_rows = _rows_of(first_b)
    dst_rows_collection = getattr(last_a, "_rows", None)
    if dst_rows_collection is None or not src_rows:
        return 0
    dst_rows = _rows_of(last_a)

    # If the first row of first_b equals the first row of last_a (header
    # repeat), skip it. Equality is per-cell text match.
    if _first_row_text(first_b) == _first_row_text(last_a):
        src_rows = src_rows[1:]

    continuation_merged = 0

    # Try continuation-row merge: if the LAST destination row's text
    # signature and the FIRST source row's text signature look like a
    # split (most cells empty in one, full in the other, and the
    # non-empty cell column overlaps), coalesce.
    if src_rows and dst_rows:
        last_dst = dst_rows[-1]
        if _looks_like_continuation(last_dst, src_rows[0]):
            _coalesce_row(last_dst, src_rows[0])
            src_rows = src_rows[1:]
            continuation_merged += 1

    # dst_rows_collection behaves like a Rows Collection with append
    for row in src_rows:
        dst_rows_collection.append(row)

    # remove first_b from the second page's blocks
    _, page_b = pages
    _remove_block(page_b, first_b)
    return continuation_merged


def _first_row_text(table: Any) -> tuple[str, ...]:
    rows = _rows_of(table)
    if not rows:
        return ()
    first_row = rows[0]
    out: list[str] = []
    for cell in first_row:
        if cell is None:
            out.append("")
            continue
        out.append(_cell_text(cell))
    return tuple(out)


def _cell_text(cell: Any) -> str:
    blocks = getattr(cell, "blocks", None)
    if blocks is None:
        return ""
    text = ""
    for block in blocks:
        lines = getattr(block, "lines", None)
        if lines is None:
            continue
        for line in lines:
            for span in getattr(line, "spans", []) or []:
                text += getattr(span, "text", "") or ""
    return text.strip()


def _last_iter(rows: Any) -> Any | None:
    try:
        items = list(rows)
    except Exception:
        return None
    return items[-1] if items else None


def _looks_like_continuation(row_a: Any, row_b: Any) -> bool:
    """Detect that row_b is the wrap-over of row_a.

    Heuristic: row_b has exactly one or two non-empty cells AND every
    non-empty cell in row_b corresponds to a non-empty cell in row_a
    (we're appending wrap text, not introducing a new column).
    """
    cells_a = list(row_a)
    cells_b = list(row_b)
    if not cells_a or len(cells_a) != len(cells_b):
        return False
    a_full = [bool(_cell_text(c)) if c is not None else False for c in cells_a]
    b_full = [bool(_cell_text(c)) if c is not None else False for c in cells_b]
    if all(b_full):
        return False  # row_b is a normal data row
    non_empty_b = sum(1 for f in b_full if f)
    if non_empty_b == 0 or non_empty_b > 2:
        return False
    # the non-empty cells of row_b must be a subset of row_a's
    for i, full in enumerate(b_full):
        if full and not a_full[i]:
            return False
    return True


def _coalesce_row(dst_row: Any, src_row: Any) -> None:
    """Append the non-empty cell content of src_row into matching cells of
    dst_row by transferring whole text blocks.

    Earlier implementations tried to mutate the last span's ``.text``
    attribute, which is silently a no-op when the span has ``chars``:
    ``TextSpan.text`` is a property whose getter returns
    ``''.join(c.c for c in self.chars)`` whenever ``self.chars`` is
    populated, ignoring the ``_text`` field that the setter writes.
    Every cell parsed from a real PDF has ``chars``, so mutating the
    final span's text dropped 100% of the appended content while
    silently reporting success.  See:
    ``pdf2docx_plus._vendored.pdf2docx.text.TextSpan.text``.

    Instead, we transfer the source cell's text blocks wholesale into
    the destination cell's block list.  This preserves the original
    line / span / char structure (including font, size, bbox metadata
    that downstream ``make_docx`` relies on) and avoids any property-
    setter surprises.
    """
    dst_cells = list(dst_row)
    src_cells = list(src_row)
    for i, src_cell in enumerate(src_cells):
        if src_cell is None or i >= len(dst_cells):
            continue
        if not _cell_text(src_cell):
            continue
        dst_cell = dst_cells[i]
        if dst_cell is None:
            continue
        _transfer_cell_blocks(dst_cell, src_cell)


def _transfer_cell_blocks(dst_cell: Any, src_cell: Any) -> None:
    """Move every text block from ``src_cell`` to the end of ``dst_cell``.

    Uses the ``Blocks._instances`` list directly so the blocks keep
    their full identity (chars, spans, bbox, font metadata) instead of
    being collapsed to a string.
    """
    src_blocks = getattr(src_cell, "blocks", None)
    dst_blocks = getattr(dst_cell, "blocks", None)
    if src_blocks is None or dst_blocks is None:
        return
    src_instances = getattr(src_blocks, "_instances", None)
    dst_instances = getattr(dst_blocks, "_instances", None)
    # Some Cell implementations expose a ``Blocks`` wrapper without
    # ``_instances``; fall back to iterating the wrapper directly.
    if src_instances is None:
        try:
            src_instances = list(src_blocks)
        except TypeError:
            return
    if dst_instances is None:
        # No append-target available — bail rather than silently losing
        # the source content.
        return
    for block in list(src_instances):
        dst_instances.append(block)


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
