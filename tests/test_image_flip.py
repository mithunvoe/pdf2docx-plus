"""Regression tests for image-matrix flip detection.

PDF raster images are commonly placed with a vertical Y-flip so the
pixel origin aligns with PDF's y-down coordinate system. When we
re-insert the raw pixmap into DOCX we must apply the same flip,
otherwise logos render upside-down (observed on the SFC Authorization
of UCITS Funds document).
"""

from __future__ import annotations

from pdf2docx_plus._vendored.pdf2docx.image.ImagesExtractor import ImagesExtractor


class _Matrix:
    """Lightweight stand-in for ``fitz.Matrix`` exposing a/b/c/d."""

    def __init__(self, a: float, b: float, c: float, d: float) -> None:
        self.a = a
        self.b = b
        self.c = c
        self.d = d


def test_flip_detected_when_determinant_negative() -> None:
    # SFC logo matrix: a=243.8, b=0, c=0, d=-82.5 → det < 0
    m = _Matrix(243.76, 0.0, 0.0, -82.5)
    assert ImagesExtractor._has_image_flip(m) is True


def test_no_flip_for_identity_like_matrix() -> None:
    m = _Matrix(100.0, 0.0, 0.0, 100.0)
    assert ImagesExtractor._has_image_flip(m) is False


def test_no_flip_for_pure_rotation_matrix() -> None:
    # 90 deg CW rotation with uniform scale
    m = _Matrix(0.0, 100.0, -100.0, 0.0)
    assert ImagesExtractor._has_image_flip(m) is False


def test_rotation_with_flip_is_detected() -> None:
    # 90 deg rotation combined with Y-flip → det = a*d - b*c
    m = _Matrix(0.0, 100.0, 100.0, 0.0)  # det = 0 - 100*100 = -10000
    assert ImagesExtractor._has_image_flip(m) is True


def test_flip_normalises_rotation_measure() -> None:
    # A Y-flip combined with "identity" scale should still be classified
    # as rotation=0 (the flip is handled separately in extract_images).
    m = _Matrix(100.0, 0.0, 0.0, -100.0)
    assert ImagesExtractor._get_image_rotation(m) == 0
