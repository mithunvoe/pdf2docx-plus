"""Tests for the layout enrichment passes."""

from __future__ import annotations

import pytest

from pdf2docx_plus.layout.lists import detect_list_block


@pytest.mark.unit
def test_detect_bullet() -> None:
    m = detect_list_block("• first item")
    assert m is not None
    assert m.kind == "bullet"


@pytest.mark.unit
def test_detect_decimal() -> None:
    m = detect_list_block("1. first point")
    assert m is not None
    assert m.kind == "decimal"
    assert m.start_at == 1


@pytest.mark.unit
def test_detect_decimal_paren() -> None:
    m = detect_list_block("42) something")
    assert m is not None
    assert m.kind == "decimal"
    assert m.start_at == 42


@pytest.mark.unit
def test_detect_lower_alpha() -> None:
    m = detect_list_block("a) aardvark")
    assert m is not None
    assert m.kind == "lower_alpha"


@pytest.mark.unit
def test_detect_upper_alpha() -> None:
    m = detect_list_block("A. Algebra")
    assert m is not None
    # roman matches before upper_alpha for 'i', 'v', 'x' letters; 'A' falls through
    assert m.kind == "upper_alpha"


@pytest.mark.unit
def test_no_match_for_plain_text() -> None:
    assert detect_list_block("hello world") is None


@pytest.mark.unit
def test_no_match_for_empty() -> None:
    assert detect_list_block("") is None
