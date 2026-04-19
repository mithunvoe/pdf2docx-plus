"""Regression tests for rotated-page handling.

PyMuPDF >= 1.18 returns ``page.get_cdrawings()`` in the un-rotated mediabox,
and per-image transforms/page rotation stack in specific CW/CCW conventions.
These tests lock in the transforms applied by pdf2docx-plus so that shapes,
hyperlinks, and images line up with rotated text blocks.
"""

from __future__ import annotations

import math

import fitz
import pytest

from pdf2docx_plus._vendored.pdf2docx.image.ImagesExtractor import ImagesExtractor
from pdf2docx_plus._vendored.pdf2docx.page.RawPageFitz import _rotate_raw_drawings


def test_rotate_raw_drawings_applies_matrix_to_rect_and_items() -> None:
    page_rotation_matrix = fitz.Matrix(0.0, 1.0, -1.0, 0.0, 842.0, 0.0)
    raw = [
        {
            "type": "fs",
            "rect": (34.9, 151.8, 114.8, 779.6),
            "items": [("re", (34.9, 151.8, 114.8, 779.6), 1)],
        }
    ]

    rotated = _rotate_raw_drawings(raw, page_rotation_matrix)

    rect = rotated[0]["rect"]
    assert rect[0] == pytest.approx(62.4, abs=1e-2)
    assert rect[1] == pytest.approx(34.9, abs=1e-2)
    assert rect[2] == pytest.approx(690.2, abs=1e-2)
    assert rect[3] == pytest.approx(114.8, abs=1e-2)

    op, rotated_rect, orient = rotated[0]["items"][0]
    assert op == "re"
    assert orient == 1
    assert rotated_rect[0] == pytest.approx(rect[0], abs=1e-2)
    assert rotated_rect[2] == pytest.approx(rect[2], abs=1e-2)


def test_rotate_raw_drawings_transforms_line_and_curve_points() -> None:
    matrix = fitz.Matrix(0.0, 1.0, -1.0, 0.0, 842.0, 0.0)
    raw = [
        {
            "type": "s",
            "rect": (10.0, 20.0, 30.0, 40.0),
            "items": [
                ("l", (10.0, 20.0), (30.0, 40.0)),
                ("c", (10.0, 20.0), (15.0, 25.0), (25.0, 35.0), (30.0, 40.0)),
            ],
        }
    ]

    rotated = _rotate_raw_drawings(raw, matrix)

    line = rotated[0]["items"][0]
    # (10, 20) * M = (842 - 20, 10) = (822, 10)
    assert line[1] == (pytest.approx(822.0), pytest.approx(10.0))
    assert line[2] == (pytest.approx(802.0), pytest.approx(30.0))

    curve = rotated[0]["items"][1]
    assert curve[1] == (pytest.approx(822.0), pytest.approx(10.0))
    assert curve[4] == (pytest.approx(802.0), pytest.approx(30.0))


def test_rotate_raw_drawings_handles_empty_input() -> None:
    assert _rotate_raw_drawings([], fitz.Matrix(0, 1, -1, 0, 0, 0)) == []
    assert _rotate_raw_drawings(None, fitz.Matrix(0, 1, -1, 0, 0, 0)) is None


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (1.0, 0.0, 0),       # identity
        (0.0, 1.0, 90),      # 90 CW
        (-1.0, 0.0, 180),    # 180
        (0.0, -1.0, 270),    # 90 CCW (= 270 CW)
    ],
)
def test_get_image_rotation_is_cw_degrees(a: float, b: float, expected: int) -> None:
    class _Matrix:
        def __init__(self, a: float, b: float) -> None:
            self.a = a
            self.b = b
            self.c = -b
            self.d = a

    assert ImagesExtractor._get_image_rotation(_Matrix(a, b)) == expected
