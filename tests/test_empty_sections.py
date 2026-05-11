"""Tests for the post-emit ``collapse_empty_sections`` pass.

Upstream occasionally emits ``<w:sectPr>`` boundaries between empty
placeholder paragraphs (header-detection stubs, decorative breaks).
Each orphan section forces a page break, so the reader sees a blank
page for every stub. The pass under test removes sections whose body
has no visible content, merging them into the next section.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from docx import Document  # type: ignore
from docx.oxml import OxmlElement  # type: ignore
from docx.oxml.ns import qn  # type: ignore

_SPEC = importlib.util.spec_from_file_location(
    "_sections_under_test",
    Path(__file__).resolve().parent.parent
    / "pdf2docx_plus"
    / "emit"
    / "sections.py",
)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
collapse_empty_sections = _MOD.collapse_empty_sections


def _append_sect_break(doc) -> None:
    """Insert an empty paragraph that carries a ``<w:sectPr>`` stub,
    placed before the final body-level ``<w:sectPr>``."""
    body = doc.element.body
    final_sect = body.find(qn("w:sectPr"))
    p = OxmlElement("w:p")
    pPr = OxmlElement("w:pPr")
    sectPr = OxmlElement("w:sectPr")
    pPr.append(sectPr)
    p.append(pPr)
    if final_sect is not None:
        final_sect.addprevious(p)
    else:
        body.append(p)


def _section_count(doc) -> int:
    body = doc.element.body
    return sum(1 for _ in body.iter(qn("w:sectPr")))


@pytest.mark.unit
def test_collapses_empty_leading_section() -> None:
    """A section containing only an empty placeholder paragraph is
    removed; the following section takes its place."""
    doc = Document()
    _append_sect_break(doc)  # empty section 1
    doc.add_paragraph("real content")
    before = _section_count(doc)
    collapsed = collapse_empty_sections(doc)
    assert collapsed == 1
    assert _section_count(doc) == before - 1
    assert any(p.text == "real content" for p in doc.paragraphs)


@pytest.mark.unit
def test_collapses_multiple_consecutive_empty_sections() -> None:
    doc = Document()
    for _ in range(3):
        _append_sect_break(doc)
    doc.add_paragraph("body A")
    _append_sect_break(doc)
    doc.add_paragraph("body B")
    collapsed = collapse_empty_sections(doc)
    assert collapsed == 3
    texts = [p.text for p in doc.paragraphs]
    assert "body A" in texts
    assert "body B" in texts


@pytest.mark.unit
def test_preserves_section_with_text() -> None:
    """A section containing a real paragraph must not be collapsed."""
    doc = Document()
    doc.add_paragraph("section-1 content")
    _append_sect_break(doc)
    doc.add_paragraph("section-2 content")
    collapsed = collapse_empty_sections(doc)
    assert collapsed == 0


@pytest.mark.unit
def test_preserves_section_containing_table() -> None:
    """A section whose only visible content is a table must not be collapsed."""
    doc = Document()
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "cell text"
    _append_sect_break(doc)
    doc.add_paragraph("after")
    collapsed = collapse_empty_sections(doc)
    assert collapsed == 0


@pytest.mark.unit
def test_never_removes_final_section() -> None:
    """The final section uses the body-level ``sectPr`` and must be
    preserved even when its content is whitespace only."""
    doc = Document()
    # default new Document has one empty paragraph + body-level sectPr
    collapsed = collapse_empty_sections(doc)
    assert collapsed == 0
    assert _section_count(doc) >= 1


@pytest.mark.unit
def test_idempotent() -> None:
    doc = Document()
    for _ in range(2):
        _append_sect_break(doc)
    doc.add_paragraph("only real content")
    first = collapse_empty_sections(doc)
    second = collapse_empty_sections(doc)
    assert first == 2
    assert second == 0


def _append_drawing_only_section(doc) -> None:
    """Insert a section containing ONLY a single drawing element followed
    by a section break. This mimics the per-page logo image that
    upstream emits before the section's real body content is merged
    elsewhere by stitching."""
    body = doc.element.body
    final_sect = body.find(qn("w:sectPr"))

    # paragraph that hosts the drawing
    p_draw = OxmlElement("w:p")
    r = OxmlElement("w:r")
    drawing = OxmlElement("w:drawing")
    r.append(drawing)
    p_draw.append(r)

    # paragraph that carries the section break
    p_sect = OxmlElement("w:p")
    pPr = OxmlElement("w:pPr")
    sectPr = OxmlElement("w:sectPr")
    pPr.append(sectPr)
    p_sect.append(pPr)

    if final_sect is not None:
        final_sect.addprevious(p_draw)
        final_sect.addprevious(p_sect)
    else:
        body.append(p_draw)
        body.append(p_sect)


@pytest.mark.unit
def test_collapses_drawing_only_section() -> None:
    """A section whose only content is a single decorative drawing
    (typically the per-page header logo) is collapsed."""
    doc = Document()
    _append_drawing_only_section(doc)
    doc.add_paragraph("real content")
    collapsed = collapse_empty_sections(doc)
    assert collapsed == 1
    assert any(p.text == "real content" for p in doc.paragraphs)


@pytest.mark.unit
def test_preserves_section_with_drawing_plus_text() -> None:
    """A section containing both a drawing AND meaningful text is NOT
    collapsed - the logo + text combination is real content."""
    doc = Document()
    body = doc.element.body
    final_sect = body.find(qn("w:sectPr"))
    # paragraph with drawing
    p_draw = OxmlElement("w:p")
    r = OxmlElement("w:r")
    drawing = OxmlElement("w:drawing")
    r.append(drawing)
    p_draw.append(r)
    # paragraph with text + sectPr
    p_text = OxmlElement("w:p")
    pPr = OxmlElement("w:pPr")
    sectPr = OxmlElement("w:sectPr")
    pPr.append(sectPr)
    p_text.append(pPr)
    r2 = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "Section text"
    r2.append(t)
    p_text.append(r2)
    if final_sect is not None:
        final_sect.addprevious(p_draw)
        final_sect.addprevious(p_text)
    doc.add_paragraph("trailing")
    collapsed = collapse_empty_sections(doc)
    assert collapsed == 0


@pytest.mark.unit
def test_preserves_section_with_multiple_drawings() -> None:
    """A section with two or more drawings is genuine visual content
    (e.g. a slide-deck-style image gallery) and must be preserved."""
    doc = Document()
    body = doc.element.body
    final_sect = body.find(qn("w:sectPr"))
    # paragraph with two drawings inside two runs
    p_draw = OxmlElement("w:p")
    for _ in range(2):
        r = OxmlElement("w:r")
        drawing = OxmlElement("w:drawing")
        r.append(drawing)
        p_draw.append(r)
    # section-break paragraph
    p_sect = OxmlElement("w:p")
    pPr = OxmlElement("w:pPr")
    sectPr = OxmlElement("w:sectPr")
    pPr.append(sectPr)
    p_sect.append(pPr)
    if final_sect is not None:
        final_sect.addprevious(p_draw)
        final_sect.addprevious(p_sect)
    doc.add_paragraph("body")
    collapsed = collapse_empty_sections(doc)
    assert collapsed == 0
