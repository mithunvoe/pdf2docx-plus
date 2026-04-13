"""Unit tests for `promote_page_numbers_to_footer`.

Regression coverage for page numbers rendered as inline body text
instead of in the footer — upstream emits ``"N Last update: ..."`` as
a plain paragraph on every page, which leaves page numbers static when
the doc repaginates and repeats the footer line 67 times in the body.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

_SPEC = importlib.util.spec_from_file_location(
    "_page_footer_under_test",
    Path(__file__).resolve().parent.parent
    / "pdf2docx_plus"
    / "emit"
    / "page_footer.py",
)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
promote_page_numbers_to_footer = _MOD.promote_page_numbers_to_footer


def _add_body_paragraph(doc, text: str) -> None:
    doc.add_paragraph(text)


@pytest.mark.unit
def test_promotes_merged_page_number_and_last_update() -> None:
    doc = Document()
    for i in range(1, 4):
        _add_body_paragraph(doc, f"{i} Last update: 2 October 2024")
    promoted = promote_page_numbers_to_footer(doc)
    assert promoted == 3
    body_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Last update" not in body_text


@pytest.mark.unit
def test_promotes_bare_page_number_before_footer_line() -> None:
    doc = Document()
    _add_body_paragraph(doc, "real body content")
    _add_body_paragraph(doc, "5")
    _add_body_paragraph(doc, "Last update: 2 October 2024")
    promoted = promote_page_numbers_to_footer(doc)
    assert promoted == 2  # bare "5" + "Last update: ..."
    # body should retain "real body content"
    body_texts = [p.text for p in doc.paragraphs]
    assert "real body content" in body_texts
    assert "5" not in body_texts
    assert not any("Last update" in t for t in body_texts)


@pytest.mark.unit
def test_footer_has_page_field() -> None:
    doc = Document()
    _add_body_paragraph(doc, "1 Last update: 2 October 2024")
    promote_page_numbers_to_footer(doc)
    footer = doc.sections[0].footer
    ftr_xml = footer._element.xml  # type: ignore[attr-defined]
    assert "PAGE" in ftr_xml
    assert 'w:fldCharType="begin"' in ftr_xml
    assert 'w:fldCharType="end"' in ftr_xml
    assert "Last update: 2 October 2024" in ftr_xml


@pytest.mark.unit
def test_no_op_when_no_footer_pattern_present() -> None:
    doc = Document()
    _add_body_paragraph(doc, "just body text")
    _add_body_paragraph(doc, "42")  # isolated digit, no footer context
    promoted = promote_page_numbers_to_footer(doc)
    assert promoted == 0
    # digit paragraph stays because it doesn't sit next to a footer line
    assert any(p.text == "42" for p in doc.paragraphs)


@pytest.mark.unit
def test_idempotent() -> None:
    doc = Document()
    _add_body_paragraph(doc, "1 Last update: 2 October 2024")
    promote_page_numbers_to_footer(doc)
    second = promote_page_numbers_to_footer(doc)
    assert second == 0
