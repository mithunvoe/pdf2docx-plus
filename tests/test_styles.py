"""Tests for the style system."""

from __future__ import annotations

import pytest
from docx import Document  # type: ignore

from pdf2docx_plus.styles import install_styles, new_document


@pytest.mark.unit
def test_new_document_has_heading_styles() -> None:
    doc = new_document()
    style_names = [s.name for s in doc.styles]
    for level in range(1, 7):
        assert f"Heading {level}" in style_names


@pytest.mark.unit
def test_new_document_has_hyperlink_style() -> None:
    doc = new_document()
    style_names = [s.name for s in doc.styles]
    assert "Hyperlink" in style_names


@pytest.mark.unit
def test_new_document_has_caption_style() -> None:
    doc = new_document()
    style_names = [s.name for s in doc.styles]
    assert "Caption" in style_names


@pytest.mark.unit
def test_install_styles_idempotent() -> None:
    doc = Document()
    install_styles(doc)
    install_styles(doc)  # second call must not crash
    assert "Heading 1" in [s.name for s in doc.styles]
