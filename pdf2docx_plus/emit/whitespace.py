"""Collapse empty paragraphs left behind by upstream's page emitter.

When upstream `pdf2docx` fails to extract an image block (because PyMuPDF's
`get_image_rects` returned no bbox for an xobject-referenced image on
that page) it still allocates a paragraph in the body flow. The DOCX
ends up with long runs of empty `<w:p>` elements that render as tall
blank regions — the "unnecessary vertical space" users see.

This pass walks the body and collapses runs of consecutive empty
paragraphs down to at most `max_consecutive` (default 1). Paragraphs
that carry a page-break marker, a drawing / inline image, a section
property, or any other non-text structure are preserved.
"""

from __future__ import annotations

from typing import Any

from docx.oxml.ns import qn


def collapse_empty_paragraphs(document: Any, *, max_consecutive: int = 1) -> int:
    """Remove runs of empty <w:p>. Returns number of paragraphs deleted."""
    body = document.element.body
    removed = 0
    empties_in_row = 0
    for p in list(body.findall(qn("w:p"))):
        if _is_meaningful_paragraph(p):
            empties_in_row = 0
            continue
        empties_in_row += 1
        if empties_in_row > max_consecutive:
            body.remove(p)
            removed += 1
    return removed


def _is_meaningful_paragraph(p: Any) -> bool:
    """True if the paragraph carries visible content or layout semantics."""
    # any text
    for t in p.findall(f".//{qn('w:t')}"):
        if (t.text or "").strip():
            return True
    # any drawing (inline or floating image)
    if p.find(f".//{qn('w:drawing')}") is not None:
        return True
    # any page break
    for br in p.findall(f".//{qn('w:br')}"):
        if br.get(qn("w:type")) == "page":
            return True
    # any embedded object / shape
    if p.find(f".//{qn('w:object')}") is not None:
        return True
    # section break (tab / hyperlink with content is handled via w:t above)
    return p.find(f".//{qn('w:sectPr')}") is not None
