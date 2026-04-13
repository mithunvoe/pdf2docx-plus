"""Collapse multi-column sections that upstream emits for horizontal layouts.

Upstream `pdf2docx` tries to reproduce page-1 "logo-left / title-right"
headers by splitting the page into a 2-column section with a
`nextColumn` break between logo and title. LibreOffice (and older Word
versions) renders this as two separate vertical columns — the logo in
column 1, the title alone in column 2 — and then inserts a page break
when the column layout changes back to 1-col. The net result is a
nearly-blank first page with only the logo, all body content shoved
one page forward (11 rendered pages vs 9 in the source PDF).

The fix: normalize every `<w:cols w:num="N"/>` with N>1 to N=1, and
downgrade any accompanying `<w:type w:val="nextColumn"/>` to
`continuous`. The body content then flows naturally top-to-bottom: the
logo and title appear on the same page, followed by the body, with the
correct page count.

This is preferable to trying to keep the 2-column layout because:
  1. Columns in OOXML flow top-to-bottom-then-jump-to-next-column,
     not left-to-right. That's never the right semantic for a banner.
  2. A real horizontal banner wants a table or text-wrapping frames,
     which upstream doesn't emit.
  3. Falling back to vertical (single-column) flow loses zero content
     — only the visual horizontality of the banner — which is a
     vastly better trade than losing a whole page.

Applied by default because on the seed corpus it converted 11 -> 9
pages (kfs_bosera) and corrected first-page layout with zero content
loss.
"""

from __future__ import annotations

from typing import Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def normalize_multi_column_sections(document: Any) -> int:
    """Convert every `w:cols w:num` > 1 to 1. Returns count normalized."""
    body = document.element.body
    changed = 0
    for cols in body.iter(qn("w:cols")):
        num_attr = cols.get(qn("w:num"))
        try:
            num = int(num_attr) if num_attr else 1
        except ValueError:
            num = 1
        if num <= 1:
            continue
        cols.set(qn("w:num"), "1")
        # drop any per-column width definitions
        for child in list(cols):
            cols.remove(child)
        changed += 1
    # downgrade nextColumn break type to continuous; nextColumn only makes
    # sense inside a multi-column section.
    for t in body.iter(qn("w:type")):
        if t.get(qn("w:val")) == "nextColumn":
            t.set(qn("w:val"), "continuous")
    return changed


def fix_page_margins(document: Any) -> int:
    """Sanitize `<w:pgMar>` entries for cross-renderer consistency.

    Ensure `w:header` / `w:footer` reservations don't exceed `w:top` /
    `w:bottom` body margins. Upstream often emits `w:header="720"`
    (0.5") with `w:top="684"` (0.48") which pushes content down by
    the overflow.

    We do NOT enforce a minimum side margin because many upstream
    documents legitimately use edge-to-edge layouts.

    Returns the number of pgMar elements adjusted.
    """
    body = document.element.body
    fixed = 0
    for pg in body.iter(qn("w:pgMar")):
        top = _int(pg.get(qn("w:top")), 720)
        bottom = _int(pg.get(qn("w:bottom")), 720)
        header = _int(pg.get(qn("w:header")), 720)
        footer = _int(pg.get(qn("w:footer")), 720)
        changed = False
        if header > top - 20:
            pg.set(qn("w:header"), str(max(0, top - 20)))
            changed = True
        if footer > bottom - 20:
            pg.set(qn("w:footer"), str(max(0, bottom - 20)))
            changed = True
        if changed:
            fixed += 1
    return fixed


def _int(s: str | None, default: int) -> int:
    if not s:
        return default
    try:
        return int(s)
    except ValueError:
        return default


def flatten_per_page_sections(document: Any) -> int:
    """Convert per-page `nextPage` section breaks to `continuous`.

    Upstream emits one `<w:sectPr>` per source PDF page, each with its
    own page margins and a default (`nextPage`) break type — i.e. a
    forced page break at every section boundary. When Word renders the
    text with a substituted font, content can overflow its section's
    tight margin by a few millimetres; the overflow lands on a new
    page, but the next section's `nextPage` break still fires, costing
    a full page per overflow. A 67-page PDF can balloon to 73 DOCX
    pages from this alone.

    Converting mid-document break types to `continuous` lets Word
    repaginate naturally — content flows section-to-section without
    forced breaks, and the rendered page count tracks actual content
    length.

    Skipped (returns 0) when:
      * any sectPr declares a per-section `headerReference` or
        `footerReference` — collapsing breaks would cause those parts
        to be applied to the wrong content;
      * page sizes (`pgSz`) vary across sections — different page
        sizes legitimately need page breaks (landscape/portrait mix).

    Returns the number of section breaks converted.
    """
    body = document.element.body
    sect_prs = list(body.iter(qn("w:sectPr")))
    if len(sect_prs) <= 1:
        return 0
    for sp in sect_prs:
        if sp.find(qn("w:headerReference")) is not None:
            return 0
        if sp.find(qn("w:footerReference")) is not None:
            return 0
    pg_sizes = set()
    for sp in sect_prs:
        sz = sp.find(qn("w:pgSz"))
        if sz is not None:
            pg_sizes.add(
                (sz.get(qn("w:w")), sz.get(qn("w:h")), sz.get(qn("w:orient")))
            )
    if len(pg_sizes) > 1:
        return 0
    converted = 0
    for sp in sect_prs:
        # final sectPr is body's direct child; mid-doc are inside w:pPr
        parent = sp.getparent()
        if parent is None or parent.tag != qn("w:pPr"):
            continue
        type_el = sp.find(qn("w:type"))
        if type_el is None:
            type_el = OxmlElement("w:type")
            sp.insert(0, type_el)
        if type_el.get(qn("w:val")) != "continuous":
            type_el.set(qn("w:val"), "continuous")
            converted += 1
    return converted


def clamp_paragraph_spacing(document: Any, *, max_twips: int = 480) -> int:
    """Cap `w:spacing w:before` / `w:after` at `max_twips`.

    Upstream emits paragraph spacing values that encode the inter-block
    vertical gap measured in the source PDF. With the default font
    substitution (Liberation Sans) text takes more vertical space than
    the original, and an inflated `w:before` / `w:after` then pushes
    content past the per-page section boundary, costing a full page
    each time. Clamping at 480 twips (~24pt = 2 lines) preserves
    typical paragraph break spacing while cutting the inflated values
    that drive page-count overflow.

    Returns the number of attributes clamped.
    """
    body = document.element.body
    clamped = 0
    for sp in body.iter(qn("w:spacing")):
        for attr in (qn("w:before"), qn("w:after")):
            v = sp.get(attr)
            if not v or not v.isdigit():
                continue
            if int(v) > max_twips:
                sp.set(attr, str(max_twips))
                clamped += 1
    return clamped
