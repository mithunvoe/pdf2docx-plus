"""Issue P-2: loosened Cell.contains.

The base ``Element.contains`` uses a strict bbox-intersection ratio.
Real fund-prospectus PDFs centre narrow rightmost-column text slightly
outside the inferred cell grid bbox; strict containment dropped the
text and surfaced in the converted DOCX as an empty ``<w:tc>`` (with
the corresponding deletion missed in the downstream redline).

``Cell.contains`` now expands the cell bbox by 1 pt on each side and
falls back to a centre-containment test when the strict area check
just barely fails.  Blocks clearly sitting in another column are still
rejected.
"""

from __future__ import annotations

import pytest

import fitz

from pdf2docx_plus._vendored.pdf2docx.table.Cell import Cell


class _FakeElement:
    def __init__(self, bbox: tuple[float, float, float, float]) -> None:
        self.bbox = fitz.Rect(*bbox)


def _cell_at(bbox: tuple[float, float, float, float]) -> Cell:
    c = Cell({"bbox": bbox})
    return c


@pytest.mark.unit
def test_contains_strictly_inside() -> None:
    cell = _cell_at((100.0, 200.0, 300.0, 240.0))
    block = _FakeElement((110.0, 210.0, 290.0, 230.0))
    assert cell.contains(block, threshold=1.0)


@pytest.mark.unit
def test_contains_block_crossing_by_half_point() -> None:
    """The exact regression case: narrow centred glyph run sits 0.5 pt
    outside the inferred cell bbox.  Strict Element.contains rejects it
    and the rightmost-column cell ends up empty in the DOCX.  Cell.contains
    must now accept it."""
    cell = _cell_at((100.0, 200.0, 300.0, 240.0))
    # block extends 0.5 pt past the right edge of the cell
    block = _FakeElement((250.0, 215.0, 300.5, 225.0))
    assert cell.contains(block, threshold=1.0)


@pytest.mark.unit
def test_contains_block_crossing_by_under_a_point() -> None:
    cell = _cell_at((100.0, 200.0, 300.0, 240.0))
    # block extends 0.9 pt past the right edge of the cell
    block = _FakeElement((250.0, 215.0, 300.9, 225.0))
    assert cell.contains(block, threshold=1.0)


@pytest.mark.unit
def test_contains_block_clearly_in_neighbour_cell_is_rejected() -> None:
    """Blocks whose centre is comfortably inside another cell must still
    be rejected even after the +1 pt expansion."""
    cell = _cell_at((100.0, 200.0, 300.0, 240.0))
    # block sits in the neighbouring column (centre at 350)
    block = _FakeElement((310.0, 215.0, 390.0, 225.0))
    assert not cell.contains(block, threshold=1.0)


@pytest.mark.unit
def test_contains_handles_empty_element() -> None:
    cell = _cell_at((100.0, 200.0, 300.0, 240.0))

    class _E:
        bbox = fitz.Rect()  # degenerate

    assert not cell.contains(_E(), threshold=1.0)


@pytest.mark.unit
def test_contains_falls_back_to_centre_when_block_is_taller() -> None:
    """A block whose bbox extends vertically past the cell (multi-line
    text wrap) should still attach to the cell when its centre is
    inside the cell."""
    cell = _cell_at((100.0, 200.0, 300.0, 240.0))
    block = _FakeElement((110.0, 195.0, 290.0, 245.0))  # straddles top+bottom
    # centre at (200, 220) — comfortably inside
    assert cell.contains(block, threshold=1.0)


@pytest.mark.unit
def test_contains_rejects_block_centred_outside_with_huge_size() -> None:
    """A huge block whose centre is far from the cell is rejected even
    though the bbox technically overlaps a corner of the cell."""
    cell = _cell_at((100.0, 200.0, 300.0, 240.0))
    block = _FakeElement((290.0, 230.0, 600.0, 500.0))
    # centre is at (445, 365) — well outside any reasonable expansion
    assert not cell.contains(block, threshold=1.0)
