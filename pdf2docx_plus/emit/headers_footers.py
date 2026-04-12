"""Move paragraphs detected as headers/footers into section hdr/ftr parts.

python-docx exposes `section.header` and `section.footer` proxies that
wrap the underlying `w:hdr` / `w:ftr` parts. We:

1. Walk `doc.paragraphs` (body only).
2. For any paragraph whose normalised text matches the normalised text
   of a detected HeaderFooter, copy the paragraph's run content into the
   corresponding header/footer of `doc.sections[0]`, then unlink from
   the body.

Multi-section docs with distinct headers/footers per section are out of
scope for this MVP pass; we write to section[0] which applies to the
whole doc unless a caller has already split sections.
"""

from __future__ import annotations

import re
from typing import Any

from ..layout.hf_detect import HeaderFooter

_PAGE_NUM = re.compile(r"(?:page\s*)?\d+(?:\s*/\s*\d+)?", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", _PAGE_NUM.sub("#", text)).strip()


def extract_headers_footers(doc: Any, detected: list[HeaderFooter]) -> int:
    """Move matching body paragraphs into section hdr/ftr. Returns count moved.

    For each unique detected HeaderFooter we insert exactly ONE representative
    paragraph into the section's header/footer. All other matching body
    paragraphs are simply deleted. This is critical: python-docx section
    headers repeat on every page, so inserting N copies would render N copies
    on every rendered page.

    Paragraphs that are too short or purely numeric (typical page numbers)
    are NOT extracted — they're cheaper to leave in the body than to risk
    ghosting them across every page.
    """
    if not detected:
        return 0
    section = doc.sections[0]

    # keep only meaningful HF candidates
    headers = [h for h in detected if h.is_header and _is_meaningful(h.text)]
    footers = [h for h in detected if not h.is_header and _is_meaningful(h.text)]
    header_texts = {_norm(h.text) for h in headers}
    footer_texts = {_norm(h.text) for h in footers}

    moved = 0
    body = doc.element.body
    first_header: dict[str, Any] = {}
    first_footer: dict[str, Any] = {}

    for paragraph in list(doc.paragraphs):
        norm = _norm(paragraph.text)
        if not norm:
            continue
        if norm in header_texts:
            if norm not in first_header:
                first_header[norm] = paragraph
                _copy_paragraph_into(section.header, paragraph)
            body.remove(paragraph._p)
            moved += 1
        elif norm in footer_texts:
            if norm not in first_footer:
                first_footer[norm] = paragraph
                _copy_paragraph_into(section.footer, paragraph)
            body.remove(paragraph._p)
            moved += 1
    return moved


def _is_meaningful(text: str) -> bool:
    """Filter out headers/footers too short or numeric to safely extract.

    Anything < 8 chars after normalization is probably a page number or
    pagination artefact; leave it in the body where it at least renders
    once per page rather than being duplicated across every page by the
    section header.
    """
    norm = _norm(text)
    if len(norm) < 8:
        return False
    # reject pure numbers-and-punctuation
    return not all(c in "#/ .-:" for c in norm)


def _copy_paragraph_into(target: Any, paragraph: Any) -> None:
    """Append the paragraph's text (with run formatting) into a header/footer."""
    # target.paragraphs[0] exists by default but may be empty; reuse when empty
    dst_paragraphs = target.paragraphs
    dst = (
        dst_paragraphs[0]
        if dst_paragraphs and not dst_paragraphs[0].text.strip()
        else target.add_paragraph()
    )
    for run in paragraph.runs:
        new_run = dst.add_run(run.text)
        new_run.bold = run.bold
        new_run.italic = run.italic
        new_run.underline = run.underline
        if run.font.size is not None:
            new_run.font.size = run.font.size
        if run.font.name is not None:
            new_run.font.name = run.font.name
