"""Keep table grids consistent with cell widths, and keep both
inside the page's content area.

Two issues are fixed here:

1. **Mismatched ``<w:tblGrid>`` vs ``<w:tcW>``.** Upstream sometimes
   emits ``<w:tblGrid>`` with evenly-divided columns even when the
   individual cells have specific, non-uniform widths (e.g. a 3-column
   Q&A table whose cells are 1494 / 4644 / 8002 twips but whose grid
   declares 4723 / 4723 / 4723). With ``tblLayout="fixed"`` LibreOffice
   honours ``<w:tblGrid>``, rendering the table with equal columns -
   the long "Answer" column ends up narrow and its paragraphs wrap
   much tighter than in the source PDF. ``align_tblgrid_to_cells()``
   rewrites the grid from the authoritative cell widths of the
   widest non-span row.

2. **Table extends past the page's right edge.** Upstream carries
   ``<w:tblInd>`` and column widths forward in source-PDF coordinates.
   When the resulting position plus total column width exceeds the
   DOCX section's content area, LibreOffice / Word silently clip the
   overflow. ``fit_oversized_tables()`` reduces the indent first and
   then proportionally scales grid and cell widths.

Both passes are pure post-emit XML rewrites with no dependency on
``fitz``.
"""

from __future__ import annotations

from typing import Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def align_tblgrid_to_cells(document: Any) -> int:
    """Rewrite each table's ``<w:tblGrid>`` to match the actual cell
    widths emitted on a non-span row.

    Selects the canonical row as the row with the largest number of
    cells whose ``<w:gridSpan>`` is 1 (or missing) *and* that exposes
    a valid ``<w:tcW w:type="dxa">`` on every cell. This is the
    natural source of truth: upstream wrote the cell widths from the
    source PDF's layout but then emitted a uniform grid, and the
    renderer honours the grid.

    Returns the number of tables whose grid was rewritten. No-ops for
    tables where no canonical row can be found (e.g. every row has
    merged cells or missing ``<w:tcW>``).
    """
    body = document.element.body
    rewritten = 0
    for tbl in body.iter(qn("w:tbl")):
        if _rewrite_grid_from_cells(tbl):
            rewritten += 1
    return rewritten


def _rewrite_grid_from_cells(tbl: Any) -> bool:
    grid = tbl.find(qn("w:tblGrid"))
    if grid is None:
        return False
    grid_cols = grid.findall(qn("w:gridCol"))
    grid_widths = [_int_or_none(gc.get(qn("w:w"))) for gc in grid_cols]
    if not grid_widths or any(w is None for w in grid_widths):
        return False

    canonical: list[int] | None = None
    for tr in tbl.findall(qn("w:tr")):
        row_widths = _unspanned_row_widths(tr)
        if row_widths is None:
            continue
        if len(row_widths) != len(grid_widths):
            continue
        if canonical is None or sum(row_widths) > sum(canonical):
            canonical = row_widths

    if canonical is None:
        return False

    # only rewrite when the grid distribution differs meaningfully.
    # Matching totals with a different per-column split is the
    # signature we want to correct.
    if _distribution_matches(grid_widths, canonical):
        return False

    for gc, w in zip(grid_cols, canonical):
        gc.set(qn("w:w"), str(w))
    return True


def _unspanned_row_widths(tr: Any) -> list[int] | None:
    """Return the cell widths for a row whose every cell is a single
    grid column (no ``<w:gridSpan>`` > 1). Returns ``None`` if any
    cell has a span or lacks a ``dxa`` width."""
    cells = tr.findall(qn("w:tc"))
    widths: list[int] = []
    for tc in cells:
        tcPr = tc.find(qn("w:tcPr"))
        if tcPr is None:
            return None
        span = tcPr.find(qn("w:gridSpan"))
        if span is not None:
            try:
                if int(span.get(qn("w:val")) or 1) > 1:
                    return None
            except ValueError:
                return None
        tcW = tcPr.find(qn("w:tcW"))
        if tcW is None:
            return None
        if tcW.get(qn("w:type")) != "dxa":
            return None
        w = _int_or_none(tcW.get(qn("w:w")))
        if w is None or w <= 0:
            return None
        widths.append(w)
    return widths or None


def _distribution_matches(a: list[int], b: list[int], *, tol: float = 0.02) -> bool:
    """Two width vectors match when each pair is within ``tol`` of
    the larger value (default 2%)."""
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        base = max(x, y)
        if base == 0:
            continue
        if abs(x - y) / base > tol:
            return False
    return True


def _int_or_none(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def fit_oversized_tables(document: Any) -> int:
    body = document.element.body
    section_widths = _section_content_widths(document, body)
    if not section_widths:
        return 0
    # Fallback when the body still has paragraphs after the final
    # section-break paragraph (python-docx's default new Document is
    # like this) - use the smallest section's content width.
    default_w = min(section_widths)
    adjusted = 0
    sect_idx = 0
    for child in body:
        if child.tag == qn("w:tbl"):
            content_w = section_widths[sect_idx] if sect_idx < len(section_widths) else default_w
            if _fit_one_table(child, content_w):
                adjusted += 1
        elif child.tag == qn("w:p"):
            if child.find(qn("w:pPr") + "/" + qn("w:sectPr")) is not None:
                sect_idx += 1
    return adjusted


def _fit_one_table(tbl: Any, content_w: int) -> bool:
    grid = tbl.find(qn("w:tblGrid"))
    if grid is None:
        return False
    cols = grid.findall(qn("w:gridCol"))
    widths: list[int] = []
    for gc in cols:
        try:
            widths.append(int(gc.get(qn("w:w")) or 0))
        except ValueError:
            widths.append(0)
    total = sum(widths)
    if total <= 0:
        return False

    tblPr = tbl.find(qn("w:tblPr"))
    tbl_ind_el = tblPr.find(qn("w:tblInd")) if tblPr is not None else None
    ind = _read_int_attr(tbl_ind_el, qn("w:w")) if tbl_ind_el is not None else 0

    if ind + total <= content_w:
        return False

    changed = False

    # Step 1: reduce indent so the table ends at the content-area edge.
    target_ind = max(0, content_w - total)
    if tbl_ind_el is not None and target_ind != ind:
        tbl_ind_el.set(qn("w:w"), str(target_ind))
        ind = target_ind
        changed = True

    # Step 2: if the table is still wider than the content area, scale
    # every grid and cell width proportionally.
    if total > content_w:
        ratio = content_w / total
        new_total = 0
        for i, gc in enumerate(cols):
            new_w = max(1, int(widths[i] * ratio))
            gc.set(qn("w:w"), str(new_w))
            widths[i] = new_w
            new_total += new_w
        # update every cell's tcW in the same proportion
        for tc in tbl.iter(qn("w:tc")):
            tcPr = tc.find(qn("w:tcPr"))
            if tcPr is None:
                continue
            tcW = tcPr.find(qn("w:tcW"))
            if tcW is None:
                continue
            try:
                old = int(tcW.get(qn("w:w")) or 0)
            except ValueError:
                continue
            if old <= 0:
                continue
            new_w = max(1, int(old * ratio))
            tcW.set(qn("w:w"), str(new_w))
        changed = True

    return changed


def _section_content_widths(document: Any, body: Any) -> list[int]:
    """Return content width in twips for every section in the
    document, in document order."""
    out: list[int] = []
    # python-docx exposes sections in the same order they appear as
    # sectPrs in the body. 1 twip = 635 EMU.
    for s in document.sections:
        try:
            page_w = int(s.page_width)
            left = int(s.left_margin)
            right = int(s.right_margin)
        except (TypeError, ValueError):
            continue
        twips = (page_w - left - right) / 635
        out.append(int(twips))
    return out


def _read_int_attr(el: Any, attr: str) -> int:
    val = el.get(attr)
    if val is None:
        return 0
    # upstream sometimes writes "8662.0" (float-stringified dxa)
    try:
        return int(float(val))
    except ValueError:
        return 0
