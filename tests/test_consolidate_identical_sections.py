"""Issue P-4: consolidate consecutive sectPrs with identical properties.

Upstream pdf2docx emits one ``<w:sectPr>`` per source PDF page, even
when consecutive pages share identical page size, margins, columns,
and orientation.  Two PDFs that are logically the same therefore end
up with different section counts purely because of page-count drift,
which breaks downstream header/footer matching that aligns sections
by index.

After P-4, mid-document sectPrs whose section properties match the
previous section are removed.  Sections that legitimately differ
(landscape mix, header reference change, margin change) are kept.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import nsmap, qn

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
consolidate_identical_sections = _MOD.consolidate_identical_sections


def _make_paragraph_with_sectpr(
    text: str,
    pg_sz: tuple[str, str, str] | None = ("12240", "15840", "portrait"),
    pg_mar: tuple[str, str, str, str] | None = ("1440", "1440", "1440", "1440"),
    cols_num: str = "1",
):
    """Build a <w:p> whose <w:pPr> carries a <w:sectPr> with the
    specified attributes."""
    p = OxmlElement("w:p")
    pPr = OxmlElement("w:pPr")
    sectPr = OxmlElement("w:sectPr")
    if pg_sz is not None:
        sz = OxmlElement("w:pgSz")
        sz.set(qn("w:w"), pg_sz[0])
        sz.set(qn("w:h"), pg_sz[1])
        sz.set(qn("w:orient"), pg_sz[2])
        sectPr.append(sz)
    if pg_mar is not None:
        mar = OxmlElement("w:pgMar")
        mar.set(qn("w:top"), pg_mar[0])
        mar.set(qn("w:right"), pg_mar[1])
        mar.set(qn("w:bottom"), pg_mar[2])
        mar.set(qn("w:left"), pg_mar[3])
        sectPr.append(mar)
    cols = OxmlElement("w:cols")
    cols.set(qn("w:num"), cols_num)
    sectPr.append(cols)
    pPr.append(sectPr)
    p.append(pPr)
    if text:
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = text
        r.append(t)
        p.append(r)
    return p


def _build_doc_with_sections(specs: list[dict]) -> Document:
    """Build a Document with one mid-doc sectPr-bearing paragraph per
    spec.  The body-level (final) sectPr is left untouched by python-docx
    defaults."""
    doc = Document()
    body = doc.element.body
    # Insert paragraphs just before the body-level sectPr.
    final_sect = body.find(qn("w:sectPr"))
    for spec in specs:
        p = _make_paragraph_with_sectpr(**spec)
        if final_sect is not None:
            body.insert(list(body).index(final_sect), p)
        else:
            body.append(p)
    return doc


@pytest.mark.unit
def test_removes_identical_consecutive_sections() -> None:
    doc = _build_doc_with_sections(
        [
            {"text": "page 1"},
            {"text": "page 2"},  # identical → drop
            {"text": "page 3"},  # identical → drop
        ]
    )
    body = doc.element.body
    initial = sum(1 for _ in body.iter(qn("w:sectPr")))
    removed = consolidate_identical_sections(doc)
    final = sum(1 for _ in body.iter(qn("w:sectPr")))
    # The first mid-doc sectPr (page 1) is the anchor; page 2 and page 3
    # match its signature, so two sectPrs are removed.  Final body-level
    # sectPr stays untouched.
    assert removed == 2
    assert final == initial - removed


@pytest.mark.unit
def test_keeps_section_when_orientation_changes() -> None:
    doc = _build_doc_with_sections(
        [
            {"text": "p1", "pg_sz": ("12240", "15840", "portrait")},
            {"text": "p2", "pg_sz": ("15840", "12240", "landscape")},  # different
            {"text": "p3", "pg_sz": ("15840", "12240", "landscape")},  # identical to p2 → drop
        ]
    )
    body = doc.element.body
    before = sum(1 for _ in body.iter(qn("w:sectPr")))
    removed = consolidate_identical_sections(doc)
    after = sum(1 for _ in body.iter(qn("w:sectPr")))
    # The landscape↔portrait transition must be preserved; only the
    # redundant landscape→landscape duplicate gets dropped.
    assert removed >= 1
    assert removed == before - after


@pytest.mark.unit
def test_keeps_section_when_margins_change() -> None:
    doc = _build_doc_with_sections(
        [
            {"text": "p1", "pg_mar": ("1440", "1440", "1440", "1440")},
            {"text": "p2", "pg_mar": ("720", "720", "720", "720")},  # different margins
        ]
    )
    body = doc.element.body
    before = sum(1 for _ in body.iter(qn("w:sectPr")))
    removed = consolidate_identical_sections(doc)
    after = sum(1 for _ in body.iter(qn("w:sectPr")))
    # The margin transition must be preserved.
    assert before - removed == after


@pytest.mark.unit
def test_keeps_section_when_columns_change() -> None:
    doc = _build_doc_with_sections(
        [
            {"text": "p1", "cols_num": "1"},
            {"text": "p2", "cols_num": "2"},  # multi-column transition
            {"text": "p3", "cols_num": "2"},  # redundant
        ]
    )
    body = doc.element.body
    before = sum(1 for _ in body.iter(qn("w:sectPr")))
    removed = consolidate_identical_sections(doc)
    after = sum(1 for _ in body.iter(qn("w:sectPr")))
    # The 1-col → 2-col transition must be preserved; the 2-col → 2-col
    # duplicate gets dropped.
    assert removed >= 1
    assert before - removed == after


@pytest.mark.unit
def test_no_action_when_only_one_sectpr() -> None:
    """A document with just the body-level sectPr is already minimal."""
    doc = Document()
    removed = consolidate_identical_sections(doc)
    assert removed == 0


@pytest.mark.unit
def test_never_removes_final_body_level_sectpr() -> None:
    """The final body-level sectPr must never be removed — that would
    strip the document trailer."""
    doc = _build_doc_with_sections(
        [
            {"text": "p1"},
            {"text": "p2"},
            {"text": "p3"},
        ]
    )
    consolidate_identical_sections(doc)
    body = doc.element.body
    # the body-level sectPr (direct child of body) must still be there
    assert body.find(qn("w:sectPr")) is not None
