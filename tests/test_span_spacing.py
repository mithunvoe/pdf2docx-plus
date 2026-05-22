"""Tests for the ``Spans.restore`` word-separator preservation patch.

PyMuPDF's ``rawdict`` extraction sometimes emits a whitespace run as its
own span (e.g. the heading ``"A. Introduction"`` arrives as the three
spans ``["A.", " ", "Introduction"]``). Upstream ``pdf2docx`` discards
every whitespace-only, style-less span, which glues the neighbours into
``"A.Introduction"``. The patch in ``pdf2docx_plus.fidelity.spans``
preserves whitespace spans that sit *between* visible content while still
dropping leading / trailing ones.
"""

from __future__ import annotations

import pytest

# importing the package installs the fidelity monkey-patches
import pdf2docx_plus  # noqa: F401
from pdf2docx_plus._vendored.pdf2docx.text.Spans import Spans


def _raw_span(text: str, x0: float, x1: float) -> dict:
    """Minimal PyMuPDF-style raw span dict with per-char bboxes."""
    chars = [
        {"c": ch, "bbox": (x0 + i, 0, x0 + i + 1, 10), "origin": (x0 + i, 8)}
        for i, ch in enumerate(text)
    ]
    return {
        "text": text,
        "chars": chars,
        "bbox": (x0, 0, x1, 10),
        "font": "F",
        "size": 10.0,
        "flags": 0,
        "color": 0,
        "style": [],
    }


def _texts(spans: Spans) -> list[str]:
    return [getattr(sp, "text", "") for sp in spans if sp is not None]


@pytest.mark.unit
def test_interior_whitespace_span_is_preserved() -> None:
    """A whitespace span flanked by text on both sides is the genuine
    word separator and must survive."""
    raws = [_raw_span("A.", 0, 5), _raw_span(" ", 5, 8), _raw_span("Introduction", 8, 40)]
    spans = Spans().restore(raws)
    assert "".join(_texts(spans)) == "A. Introduction"


@pytest.mark.unit
def test_leading_and_trailing_whitespace_spans_are_dropped() -> None:
    """Boundary whitespace spans are redundant indentation and keep the
    upstream behaviour of being removed."""
    raws = [_raw_span("  ", 0, 3), _raw_span("Hello", 3, 20), _raw_span("   ", 20, 24)]
    spans = Spans().restore(raws)
    assert _texts(spans) == ["Hello"]


@pytest.mark.unit
def test_numbered_marker_separator_is_preserved() -> None:
    """``"1." | " " | "Pursuant"`` must not collapse to ``"1.Pursuant"``."""
    raws = [_raw_span("1.", 0, 5), _raw_span(" ", 5, 8), _raw_span("Pursuant", 8, 40)]
    spans = Spans().restore(raws)
    assert "".join(_texts(spans)) == "1. Pursuant"


@pytest.mark.unit
def test_multiple_interior_separators_preserved() -> None:
    raws = [
        _raw_span("one", 0, 10),
        _raw_span(" ", 10, 13),
        _raw_span("two", 13, 23),
        _raw_span(" ", 23, 26),
        _raw_span("three", 26, 40),
    ]
    spans = Spans().restore(raws)
    assert "".join(_texts(spans)) == "one two three"


@pytest.mark.unit
def test_all_whitespace_line_is_emptied() -> None:
    """With no visible anchors at all, every whitespace span is dropped
    (there is no interior region to protect)."""
    raws = [_raw_span("  ", 0, 3), _raw_span("   ", 3, 7)]
    spans = Spans().restore(raws)
    assert _texts(spans) == []
