"""Clamp table indent and column widths so tables fit the page.

Upstream ``pdf2docx`` carries column widths and table indents forward
in the source PDF's coordinate system. When the source layout places
the table close to the right-hand margin (a classic pattern is a
form where the left side holds item text and the right side holds a
``Yes`` / ``No`` checkbox grid), upstream emits the table with a
large ``<w:tblInd>`` so the table's left edge sits exactly where it
was in the PDF. If the DOCX section margins end up slightly wider
than the PDF's, the indent plus the column widths push the table's
right edge past the page's right margin, and the renderer
(LibreOffice, Word) simply **clips** the overflow.

Concrete signature seen in Old_2_UT page 14:

  * Section 12: ``pgSz w=11906 twips`` (A4), margins ``left=420
    right=902`` -> content width ``= 10584 twips``
  * Table 1: ``tblInd w=8662``, ``tblGrid`` of two ``5292`` cols
    (total 10584) -> table ends at ``420 + 8662 + 10584 = 19666``,
    which is ``7760`` twips past the page's ``11906`` right edge.

LibreOffice renders the visible slice only, so the right-hand
``Yes``/``No`` cells disappear and the item-text column looks
mysteriously narrow. The data is present in the XML but invisible.

This pass walks every ``<w:tbl>``, works out the enclosing section's
content width, and, when a table overflows:

  1. first **reduces ``tblInd``** so the table's right edge sits at
     the content area's right edge (preserving the source's
     right-alignment as far as possible without clipping);
  2. if the total column width alone still exceeds the content area,
     **scales every ``<w:gridCol>`` and ``<w:tcW>``** proportionally
     to fit.

Returns the number of tables adjusted.
"""

from __future__ import annotations

from typing import Any

from docx.oxml.ns import qn


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
