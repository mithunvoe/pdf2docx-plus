"""Tests for list emission post-pass."""

from __future__ import annotations

import pytest
from docx import Document  # type: ignore

from pdf2docx_plus.emit.lists import apply_lists


@pytest.mark.unit
def test_converts_bullet_to_numPr() -> None:
    doc = Document()
    doc.add_paragraph("• first item")
    doc.add_paragraph("• second item")
    count = apply_lists(doc)
    assert count == 2
    # numPr must now be present on both paragraphs
    for p in doc.paragraphs:
        pPr = p._p.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pPr")
        assert pPr is not None, "pPr missing"
        numPr = pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr")
        assert numPr is not None, "numPr missing"


@pytest.mark.unit
def test_decimal_list_detected() -> None:
    doc = Document()
    doc.add_paragraph("1. first")
    doc.add_paragraph("2. second")
    doc.add_paragraph("3. third")
    count = apply_lists(doc)
    assert count == 3


@pytest.mark.unit
def test_mixed_content_only_converts_list_paragraphs() -> None:
    doc = Document()
    doc.add_paragraph("Introduction text.")
    doc.add_paragraph("• bullet")
    doc.add_paragraph("More prose.")
    doc.add_paragraph("1. numbered")
    count = apply_lists(doc)
    assert count == 2


@pytest.mark.unit
def test_strips_marker_from_text() -> None:
    doc = Document()
    doc.add_paragraph("• hello")
    apply_lists(doc)
    assert doc.paragraphs[0].text == "hello"


@pytest.mark.unit
def test_empty_document_safe() -> None:
    doc = Document()
    assert apply_lists(doc) == 0
