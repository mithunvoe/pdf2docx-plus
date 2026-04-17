"""OOXML-valid hyperlink emission.

Upstream's `add_hyperlink` does:

    r = paragraph.add_run()
    r._r.append(hyperlink)    # <w:r><w:hyperlink>...</w:hyperlink></w:r>

That nesting is invalid OOXML: `<w:hyperlink>` must be a sibling of runs at
the paragraph level, not a child of a run. The consequence is Word opening
the doc in "Compatibility Mode" and sometimes rendering two underlines (one
from the paragraph-level run style, one from the nested hyperlink run).

The fix: append `<w:hyperlink>` directly to the paragraph's XML element, and
return a `Run`-like proxy pointing at the inner `<w:r>` so the downstream
formatting calls (`_set_text_format`) keep working unchanged.
"""

from __future__ import annotations

from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.run import Run

import pdf2docx_plus._vendored.pdf2docx.common.docx as _upstream


def _add_hyperlink(paragraph, url: str, text: str) -> Run:
    """Drop-in replacement with valid OOXML structure."""
    part = paragraph.part
    r_id = part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    hyperlink.set(qn("w:history"), "1")

    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    rStyle = OxmlElement("w:rStyle")
    rStyle.set(qn("w:val"), "Hyperlink")
    rPr.append(rStyle)
    new_run.append(rPr)

    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    new_run.append(t)

    hyperlink.append(new_run)
    # append at paragraph level, not inside a run
    paragraph._p.append(hyperlink)

    return Run(new_run, paragraph)


_upstream.add_hyperlink = _add_hyperlink
