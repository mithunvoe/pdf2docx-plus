"""Post-emit table cleanup.

Upstream `pdf2docx` aggressively treats any aligned text as a "stream
table". On text-heavy PDFs this produces a sprawl of 1-row tables for
label-value pairs (e.g. "Trustee  |  Standard Chartered") — one for
every line in the glossary. Each such 1-row table adds cell padding
and disrupts the natural text flow, which:

  * inflates page count,
  * breaks selection / copy-paste,
  * makes the document look fragmented rather than prose-like.

Two passes:

1. `merge_consecutive_single_row_tables(doc)` — runs of 1-row tables
   with the same column count and similar column widths are merged
   into a single multi-row table. Preserves the logical glossary
   structure but collapses the fragmentation.

2. `unwrap_tiny_tables(doc, max_rows=1)` — any still-isolated single-
   row table with short content is unwrapped back to tab-separated
   paragraphs. "Short content" is configurable; by default any cell
   with < 120 characters is treated as short. Multi-row tables are
   left alone because they're usually genuine.

Running these in order keeps genuine multi-cell tables intact while
removing the label-value sprawl that upstream generates.
"""

from __future__ import annotations

from typing import Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def merge_consecutive_single_row_tables(document: Any, *, col_tolerance_pct: float = 10.0) -> int:
    """Merge adjacent <w:tbl> elements with matching column structure.

    Returns the number of tables absorbed into their predecessors.
    """
    body = document.element.body
    absorbed = 0
    children = list(body)
    i = 0
    while i < len(children):
        tbl = children[i]
        if tbl.tag != qn("w:tbl"):
            i += 1
            continue
        # only consider 1-row tables as merge candidates
        rows = tbl.findall(qn("w:tr"))
        if len(rows) != 1:
            i += 1
            continue
        widths_a = _col_widths(tbl)
        # look ahead: next sibling must be another 1-row tbl with matching widths
        j = i + 1
        while j < len(children):
            sib = children[j]
            if sib.tag == qn("w:tbl"):
                sib_rows = sib.findall(qn("w:tr"))
                if len(sib_rows) == 1 and _widths_match(
                    widths_a, _col_widths(sib), tol_pct=col_tolerance_pct
                ):
                    # absorb sib's row into tbl
                    tbl.append(sib_rows[0])
                    body.remove(sib)
                    children = list(body)
                    absorbed += 1
                    continue
                break
            # skip over blank paragraphs between tables — they are artifacts
            if sib.tag == qn("w:p") and _is_empty_paragraph(sib):
                body.remove(sib)
                children = list(body)
                continue
            break
        i += 1
    return absorbed


def unwrap_tiny_tables(
    document: Any,
    *,
    max_rows: int = 1,
    max_cell_chars: int = 120,
    min_cols_to_unwrap: int = 1,
) -> int:
    """Convert tiny tables into tab-separated paragraphs.

    Tables are unwrapped when:
      * rows <= max_rows, AND
      * every cell has <= max_cell_chars, AND
      * number of columns >= min_cols_to_unwrap.
    """
    body = document.element.body
    unwrapped = 0
    for tbl in list(body.findall(qn("w:tbl"))):
        rows = tbl.findall(qn("w:tr"))
        if len(rows) > max_rows:
            continue
        cells = rows[0].findall(qn("w:tc")) if rows else []
        if len(cells) < min_cols_to_unwrap:
            continue
        if any(len(_cell_plain_text(c)) > max_cell_chars for c in cells):
            continue
        parent = tbl.getparent()
        if parent is None:
            continue
        # for each row, emit one paragraph with tab-separated cell text
        replacement: list[Any] = []
        for row in rows:
            row_cells = row.findall(qn("w:tc"))
            p = OxmlElement("w:p")
            pPr = OxmlElement("w:pPr")
            tabs = OxmlElement("w:tabs")
            # one tab stop per cell boundary
            running = 0
            for c in row_cells[:-1]:
                w = _cell_width(c) or 2880
                running += w
                tab = OxmlElement("w:tab")
                tab.set(qn("w:val"), "left")
                tab.set(qn("w:pos"), str(running))
                tabs.append(tab)
            if len(tabs):
                pPr.append(tabs)
                p.append(pPr)
            first = True
            for c in row_cells:
                text = _cell_plain_text(c)
                if not first:
                    r = OxmlElement("w:r")
                    tab = OxmlElement("w:tab")
                    r.append(tab)
                    p.append(r)
                if text:
                    r = OxmlElement("w:r")
                    t = OxmlElement("w:t")
                    t.text = text
                    t.set(qn("xml:space"), "preserve")
                    r.append(t)
                    p.append(r)
                first = False
            replacement.append(p)
        # splice replacement in place of tbl
        idx = list(parent).index(tbl)
        parent.remove(tbl)
        for p in reversed(replacement):
            parent.insert(idx, p)
        unwrapped += 1
    return unwrapped


def split_visually_separated_tables(
    document: Any,
    *,
    header_repeat_threshold: int = 2,
) -> int:
    """Split a `<w:tbl>` into multiple tables when the upstream layout
    parser fused logically-distinct tables into a single mega-table.

    Issue P-3 from PDF_FIDELITY_PDF2DOCX_PLAN.md: fund-prospectus
    layouts contain multiple fee tables stacked vertically with
    identical column grids on the same page.  `pdf2docx-plus`'s stream
    table promoter aggregates them into one `TableBlock` (and therefore
    one `<w:tbl>` in the output), which collapses the natural table
    boundaries and confuses any downstream diff that aligns tables by
    index.

    Heuristic: walk every `<w:tbl>` and identify row indices where a
    header row repeats inside the table.  Header detection uses the
    text signature of row 0: any later row whose cell-text tuple equals
    row 0's signature is treated as the start of a new logical table.
    Split at those boundaries.

    Importantly, this is safe vs. the existing cross-page stitch logic
    (``pdf2docx_plus.tables.stitch``).  That stitcher already drops the
    second table's header row when stitching genuine page-spanning
    continuations (FAQ / SFT / TRS pattern), so a correctly-stitched
    FAQ table never contains an internal header repeat and is therefore
    untouched by this pass.

    Args:
        document: python-docx ``Document``-like instance.
        header_repeat_threshold: minimum number of non-empty cells the
            row 0 signature must have for a later equal row to count as
            a header repeat.  A single-column or near-empty row 0 is
            too weak a signature.

    Returns:
        Number of new tables introduced (= total splits performed).
    """
    body = document.element.body
    splits = 0
    for tbl in list(body.findall(qn("w:tbl"))):
        rows = tbl.findall(qn("w:tr"))
        if len(rows) < 3:
            continue
        header_sig = _row_text_signature(rows[0])
        non_empty = sum(1 for cell in header_sig if cell)
        if non_empty < header_repeat_threshold:
            continue
        # collect indices (1-based: never split before row 0) where a row
        # repeats the header signature.
        split_indices: list[int] = []
        for idx in range(1, len(rows)):
            if _row_text_signature(rows[idx]) == header_sig:
                split_indices.append(idx)
        if not split_indices:
            continue
        splits += _split_table_at_indices(tbl, rows, split_indices, body)
    return splits


def drop_empty_tables(document: Any, *, max_cells: int = 9) -> int:
    """Remove small tables whose every cell is empty.

    Upstream's lattice detector faithfully finds bordered rectangles in
    the source PDF. When a small rectangle encloses nothing - an
    underline stroke, a decorative margin box, a single detection
    artifact - the resulting table is pure noise and should be dropped.

    Larger empty tables, however, are usually **legitimate form
    grids** (e.g. the checkbox continuation rows on a multi-page
    application form). Dropping those destroys the form: the user
    loses the place where their ticks are supposed to go.

    Heuristic: only drop fully-empty tables with at most ``max_cells``
    total cells (default 9 - a 3x3 grid). Anything larger is kept
    even when empty.

    Returns the number of tables removed.
    """
    body = document.element.body
    removed = 0
    for tbl in list(body.findall(qn("w:tbl"))):
        if not _table_is_fully_empty(tbl):
            continue
        rows = tbl.findall(qn("w:tr"))
        n_cells = sum(len(r.findall(qn("w:tc"))) for r in rows)
        if n_cells > max_cells:
            continue
        parent = tbl.getparent()
        if parent is not None:
            parent.remove(tbl)
            removed += 1
    return removed


def trim_empty_table_rows(document: Any) -> int:
    """Strip empty rows from tables that look like lattice detection
    artifacts.

    Previous behaviour was to strip every leading and trailing empty
    row, which destroyed legitimate form/checkbox tables (e.g. the
    SFC Information Checklist's ``Applicable? (please tick)`` grids)
    where rows 2..N are empty by design.

    This version only trims when the table is **small and sparse** -
    at most four rows with exactly one non-empty row - which is the
    lattice-artifact signature (a single piece of text surrounded by
    detected-but-empty border rectangles). Multi-row forms whose data
    rows are intentionally blank are now preserved verbatim.

    Returns the number of rows removed.
    """
    removed = 0
    for tbl in document.element.body.findall(qn("w:tbl")):
        rows = tbl.findall(qn("w:tr"))
        # Need at least one empty row to trim and at least one content row to keep.
        if len(rows) < 2 or len(rows) > 4:
            continue
        non_empty = [r for r in rows if not _row_is_empty(r)]
        if len(non_empty) != 1:
            continue
        for r in rows:
            if _row_is_empty(r):
                tbl.remove(r)
                removed += 1
    return removed


# -- helpers --------------------------------------------------------------


def _table_is_fully_empty(tbl: Any) -> bool:
    for tc in tbl.iter(qn("w:tc")):
        if _cell_has_content(tc):
            return False
    return True


def _row_is_empty(tr: Any) -> bool:
    for tc in tr.findall(qn("w:tc")):
        if _cell_has_content(tc):
            return False
    return True


def _cell_has_content(tc: Any) -> bool:
    if _cell_plain_text(tc):
        return True
    # images / shapes / embedded objects count as content
    for tag in ("w:drawing", "w:pict", "w:object"):
        if tc.find(f".//{qn(tag)}") is not None:
            return True
    return False


def _col_widths(tbl: Any) -> list[int]:
    grid = tbl.find(qn("w:tblGrid"))
    if grid is None:
        return []
    out: list[int] = []
    for gc in grid.findall(qn("w:gridCol")):
        w = gc.get(qn("w:w"))
        if w and w.isdigit():
            out.append(int(w))
    return out


def _widths_match(a: list[int], b: list[int], *, tol_pct: float) -> bool:
    if len(a) != len(b) or not a:
        return False
    for wa, wb in zip(a, b, strict=False):
        if wa == 0 and wb == 0:
            continue
        base = max(wa, wb)
        if base == 0:
            continue
        if abs(wa - wb) / base * 100 > tol_pct:
            return False
    return True


def _cell_plain_text(tc: Any) -> str:
    parts: list[str] = []
    for t in tc.iter(qn("w:t")):
        parts.append(t.text or "")
    return "".join(parts).strip()


def _cell_width(tc: Any) -> int | None:
    tcPr = tc.find(qn("w:tcPr"))
    if tcPr is None:
        return None
    tcW = tcPr.find(qn("w:tcW"))
    if tcW is None:
        return None
    w = tcW.get(qn("w:w"))
    if w and w.lstrip("-").isdigit():
        return int(w)
    return None


def _is_empty_paragraph(p: Any) -> bool:
    for t in p.iter(qn("w:t")):
        if (t.text or "").strip():
            return False
    return p.find(f".//{qn('w:drawing')}") is None


def _row_text_signature(tr: Any) -> tuple[str, ...]:
    """Cell-text signature of a row, used for header-repeat detection.

    Per-cell text is stripped and case-folded; empty cells become empty
    strings so signature comparison is order-sensitive and column-count-
    sensitive without being whitespace- or case-fragile.
    """
    sig: list[str] = []
    for tc in tr.findall(qn("w:tc")):
        sig.append(_cell_plain_text(tc).casefold())
    return tuple(sig)


def _split_table_at_indices(
    tbl: Any,
    rows: list[Any],
    split_indices: list[int],
    body: Any,
) -> int:
    """Split ``tbl`` into sub-tables at the given row indices.

    All XML around the table (``<w:tblPr>``, ``<w:tblGrid>``, etc.) is
    deep-copied into each clone so the resulting sub-tables render
    identically to slices of the original.

    Returns the number of NEW tables introduced (i.e., ``len(split_indices)``).
    """
    from copy import deepcopy

    # bracket the rows into segments: rows[0:split[0]], rows[split[0]:split[1]], ..., rows[split[-1]:]
    boundaries = [0, *split_indices, len(rows)]
    segments: list[list[Any]] = []
    for i in range(len(boundaries) - 1):
        seg = rows[boundaries[i]:boundaries[i + 1]]
        if seg:
            segments.append(seg)
    if len(segments) <= 1:
        return 0

    # capture the original tbl's structural prelude (anything that isn't <w:tr>)
    prelude: list[Any] = []
    for child in list(tbl):
        if child.tag == qn("w:tr"):
            continue
        prelude.append(child)

    parent = tbl.getparent()
    if parent is None:
        return 0
    insertion_index = list(parent).index(tbl)

    # remove the original tbl from the parent so we can splice clones in
    parent.remove(tbl)

    introduced = 0
    for seg_i, seg in enumerate(segments):
        clone = OxmlElement("w:tbl")
        for pre in prelude:
            clone.append(deepcopy(pre))
        for row in seg:
            clone.append(deepcopy(row))
        parent.insert(insertion_index + seg_i, clone)
        if seg_i > 0:
            introduced += 1
    return introduced
