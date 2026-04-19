"""Regression tests for the fill-in-line synthesis heuristic.

The synthesiser in ``RawPageFitz._synthesize_fillin_lines`` turns
orphan horizontal vector strokes into underscore text so Word shows a
"blank to be filled in" underneath form labels (e.g. "Name: ______").
False positives must be avoided because synthesised text runs get
injected into the raw extraction and then interfere with table /
layout parsing.

These tests exercise the public contract of the synthesiser via a
minimal stub ``page`` object: it must *not* emit anything when strokes
sit inside a table grid, and it *must* emit exactly one underscore run
per isolated horizontal stroke that follows a label-like text line.
"""

from __future__ import annotations

from typing import Any

import fitz

from pdf2docx_plus._vendored.pdf2docx.page.RawPageFitz import RawPageFitz


class _StubPage:
    def __init__(self, width: float, height: float, drawings: list[dict[str, Any]]):
        self.rect = fitz.Rect(0, 0, width, height)
        self.rotation = 0
        self.rotation_matrix = fitz.Matrix(1, 0, 0, 1, 0, 0)
        self._drawings = drawings
        self.number = 0

    def get_cdrawings(self) -> list[dict[str, Any]]:
        return self._drawings


def _make_instance(page: _StubPage) -> RawPageFitz:
    obj = RawPageFitz.__new__(RawPageFitz)
    obj.page_engine = page
    return obj


def _text_block(x0: float, y0: float, x1: float, y1: float, text: str) -> dict[str, Any]:
    chars = [
        {"c": ch, "origin": (x0 + i, y1), "bbox": (x0 + i, y0, x0 + i + 1, y1)}
        for i, ch in enumerate(text)
    ]
    return {
        "type": 0,
        "bbox": (x0, y0, x1, y1),
        "lines": [{
            "bbox": (x0, y0, x1, y1),
            "dir": (1.0, 0.0),
            "spans": [{
                "bbox": (x0, y0, x1, y1),
                "chars": chars,
                "text": text,
                "font": "Times",
                "size": 11.0,
            }],
        }],
    }


def test_emits_single_run_for_isolated_fillin_line() -> None:
    # Label "Name:" at ~x=50..100, y=95..105. Stroke x=110..400, y=105..106.
    page = _StubPage(
        width=612,
        height=792,
        drawings=[{
            "type": "fs",
            "rect": (110.0, 105.0, 400.0, 106.0),
            "items": [("re", (110.0, 105.0, 400.0, 106.0), 1)],
        }],
    )
    text_blocks = [_text_block(50, 95, 100, 105, "Name:")]

    synth = _make_instance(page)._synthesize_fillin_lines(text_blocks)

    assert len(synth) == 1
    span = synth[0]["lines"][0]["spans"][0]
    assert set(span["text"]) == {"_"}
    assert len(span["text"]) >= 20  # roughly proportional to 290pt


def test_skips_stroke_inside_table_grid() -> None:
    # Horizontal stroke bordered by vertical strokes on each side:
    # classic table cell top-edge pattern.
    page = _StubPage(
        width=612,
        height=792,
        drawings=[
            # cell top border
            {"type": "f", "rect": (100.0, 200.0, 500.0, 200.5),
             "items": [("re", (100.0, 200.0, 500.0, 200.5), 1)]},
            # left vertical
            {"type": "f", "rect": (100.0, 200.0, 100.5, 260.0),
             "items": [("re", (100.0, 200.0, 100.5, 260.0), 1)]},
            # right vertical
            {"type": "f", "rect": (499.5, 200.0, 500.0, 260.0),
             "items": [("re", (499.5, 200.0, 500.0, 260.0), 1)]},
            # cell bottom border
            {"type": "f", "rect": (100.0, 260.0, 500.0, 260.5),
             "items": [("re", (100.0, 260.0, 500.0, 260.5), 1)]},
        ],
    )
    text_blocks = [_text_block(110, 210, 160, 220, "Name:")]

    synth = _make_instance(page)._synthesize_fillin_lines(text_blocks)
    assert synth == []


def test_skips_underline_of_text() -> None:
    # Stroke is the underline of "Signature" (same horizontal extent).
    page = _StubPage(
        width=612,
        height=792,
        drawings=[{
            "type": "fs",
            "rect": (100.0, 105.0, 300.0, 106.0),
            "items": [("re", (100.0, 105.0, 300.0, 106.0), 1)],
        }],
    )
    # text sits directly above and 80% overlaps the stroke
    text_blocks = [_text_block(100, 95, 300, 105, "Signature")]

    synth = _make_instance(page)._synthesize_fillin_lines(text_blocks)
    assert synth == []


def test_skips_stroke_without_label_cue() -> None:
    # Stroke is isolated but no text to its left — we refuse to
    # fabricate a fill-in field without a "label:" cue.
    page = _StubPage(
        width=612,
        height=792,
        drawings=[{
            "type": "fs",
            "rect": (110.0, 105.0, 400.0, 106.0),
            "items": [("re", (110.0, 105.0, 400.0, 106.0), 1)],
        }],
    )

    synth = _make_instance(page)._synthesize_fillin_lines(text_blocks=[])
    assert synth == []


def test_short_stroke_is_ignored() -> None:
    # 50pt wide stroke — below the 100pt minimum width threshold.
    page = _StubPage(
        width=612,
        height=792,
        drawings=[{
            "type": "fs",
            "rect": (110.0, 105.0, 160.0, 106.0),
            "items": [("re", (110.0, 105.0, 160.0, 106.0), 1)],
        }],
    )
    text_blocks = [_text_block(50, 95, 100, 105, "Name:")]

    synth = _make_instance(page)._synthesize_fillin_lines(text_blocks)
    assert synth == []
