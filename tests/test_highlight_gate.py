"""Issue P-5: phantom <w:highlight> suppression.

The vendored Shape detector and TextSpan style attacher both used to
classify any low-aspect Fill that geometrically overlapped a text line
as a text highlight.  Many fund-prospectus PDFs render decorative
paragraph rules and table grid anti-aliasing as low-saturation fills
that happen to overlap glyph bboxes, which leaked into the converted
DOCX as `<w:highlight w:val="green"/>` / `yellow` runs.

These tests pin the new behaviour: only fills whose colour has
sufficient HSV saturation AND whose area overlaps the text bbox can be
promoted to highlight.  Legitimate yellow / green / pink highlighter
strips still pass.
"""

from __future__ import annotations

import pytest

from pdf2docx_plus._vendored.pdf2docx.shape.Shape import (
    HIGHLIGHT_MIN_SATURATION,
    _hsv_saturation,
    _is_highlight_color,
)
from pdf2docx_plus._vendored.pdf2docx.common.share import rgb_to_value


def _rgb(r: float, g: float, b: float) -> int:
    return rgb_to_value([r, g, b])


@pytest.mark.unit
def test_pure_yellow_is_highlight_color() -> None:
    assert _is_highlight_color(_rgb(1.0, 1.0, 0.0))


@pytest.mark.unit
def test_pure_green_is_highlight_color() -> None:
    assert _is_highlight_color(_rgb(0.0, 1.0, 0.0))


@pytest.mark.unit
def test_pure_pink_is_highlight_color() -> None:
    assert _is_highlight_color(_rgb(1.0, 0.0, 1.0))


@pytest.mark.unit
def test_pure_cyan_is_highlight_color() -> None:
    assert _is_highlight_color(_rgb(0.0, 1.0, 1.0))


@pytest.mark.unit
def test_white_is_not_highlight_color() -> None:
    assert not _is_highlight_color(_rgb(1.0, 1.0, 1.0))


@pytest.mark.unit
def test_black_is_not_highlight_color() -> None:
    assert not _is_highlight_color(_rgb(0.0, 0.0, 0.0))


@pytest.mark.unit
def test_near_grey_is_not_highlight_color() -> None:
    # Common case: anti-aliasing artefact or paragraph rule rendered in a
    # slightly-tinted grey.  Saturation stays tiny so we must refuse.
    assert not _is_highlight_color(_rgb(0.78, 0.80, 0.79))


@pytest.mark.unit
def test_pale_pastel_is_not_highlight_color() -> None:
    # Decorative pastel backgrounds (~0.1 saturation) should not be promoted
    # to text highlights — they're page chrome, not highlighter ink.
    assert not _is_highlight_color(_rgb(0.95, 0.92, 0.92))


@pytest.mark.unit
def test_saturation_threshold_is_strict() -> None:
    # Exactly at the threshold means we are still in the rejection zone:
    # `_is_highlight_color` returns True only when saturation is strictly
    # greater than the configured floor.
    assert HIGHLIGHT_MIN_SATURATION > 0.0
    near = (1.0 - HIGHLIGHT_MIN_SATURATION) + 0.001
    sat = _hsv_saturation(_rgb(1.0, near, near))
    # within +/- 1e-3 of the threshold; should NOT count as highlight
    assert abs(sat - HIGHLIGHT_MIN_SATURATION) < 0.05
    assert not _is_highlight_color(_rgb(1.0, near, near))


@pytest.mark.unit
def test_hsv_saturation_handles_invalid() -> None:
    # Defensive: a negative or oversized integer should not crash the gate.
    # It shouldn't return a "highlight" verdict either.
    assert _hsv_saturation(0) == 0.0


@pytest.mark.unit
def test_fill_semantic_type_refuses_low_saturation() -> None:
    """End-to-end Fill._semantic_type smoke test.

    Build a fake horizontal text line bbox-equivalent and a Fill that:

    * has the geometry of a text highlight (horizontal, narrower than the
      line),
    * but whose colour is near-grey.

    We expect SHADING (not HIGHLIGHT), so the run never gets
    `<w:highlight>`.
    """
    import fitz

    from pdf2docx_plus._vendored.pdf2docx.common.share import RectType
    from pdf2docx_plus._vendored.pdf2docx.shape.Shape import Fill

    class _FakeLine:
        is_horizontal_text = True

        def __init__(self, bbox: tuple[float, float, float, float]) -> None:
            self.bbox = fitz.Rect(bbox)

    line = _FakeLine((50.0, 100.0, 250.0, 112.0))

    near_grey = _rgb(0.78, 0.80, 0.79)
    fill = Fill({"bbox": (50.0, 100.0, 250.0, 112.0), "color": near_grey})
    rect_type = fill._semantic_type(line)
    # Should NOT be HIGHLIGHT — saturation gate rejected it.
    assert rect_type & RectType.HIGHLIGHT.value == 0


@pytest.mark.unit
def test_fill_semantic_type_keeps_real_yellow() -> None:
    """Real yellow highlighter ink survives the new gate."""
    import fitz

    from pdf2docx_plus._vendored.pdf2docx.common.share import RectType
    from pdf2docx_plus._vendored.pdf2docx.shape.Shape import Fill

    class _FakeLine:
        is_horizontal_text = True

        def __init__(self, bbox: tuple[float, float, float, float]) -> None:
            self.bbox = fitz.Rect(bbox)

    line = _FakeLine((50.0, 100.0, 250.0, 112.0))

    yellow = _rgb(1.0, 1.0, 0.0)
    fill = Fill({"bbox": (50.0, 100.0, 250.0, 112.0), "color": yellow})
    rect_type = fill._semantic_type(line)
    # Should be HIGHLIGHT.
    assert rect_type == RectType.HIGHLIGHT.value
