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


# -- helpers --------------------------------------------------------------


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
