"""Insert explicit page breaks between source pages.

Upstream #321: the emitter relies on sectPr boundaries plus accumulated
content height to reach page breaks. When LibreOffice / older Word
versions render DOCX, the cumulative content height can drift, causing
content from page N to spill across the boundary. An explicit
`<w:br w:type="page"/>` at the end of each source page pins the
boundary regardless of renderer drift.

We walk the body; each `<w:sectPr>` marks the end of a source page in
upstream's emission scheme. Immediately before the sectPr-bearing
paragraph, we inject a `<w:br w:type="page"/>` in its own paragraph —
but only if the previous paragraph is not already a page break, to
avoid doubling.
"""

from __future__ import annotations

from typing import Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def insert_page_breaks(document: Any) -> int:
    """Inject explicit page breaks at each source-page boundary."""
    body = document.element.body
    inserted = 0

    # find every <w:p> that contains a <w:sectPr> — those are the anchors
    anchors: list[Any] = []
    for p in list(body.findall(qn("w:p"))):
        if p.find(f"{qn('w:pPr')}/{qn('w:sectPr')}") is not None:
            anchors.append(p)

    # skip the last anchor (the final section properties don't terminate a page)
    for anchor in anchors[:-1]:
        # avoid injecting if there's already a page break immediately before
        prev = anchor.getprevious()
        if prev is not None and prev.tag == qn("w:p"):
            existing = prev.findall(f".//{qn('w:br')}")
            if any(b.get(qn("w:type")) == "page" for b in existing):
                continue
        p = _make_page_break_paragraph()
        anchor.addprevious(p)
        inserted += 1
    return inserted


def _make_page_break_paragraph() -> Any:
    p = OxmlElement("w:p")
    r = OxmlElement("w:r")
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    r.append(br)
    p.append(r)
    return p
