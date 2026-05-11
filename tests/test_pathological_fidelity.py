"""Tests for the pathological-lattice-table fidelity patch."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pdf2docx_plus.fidelity.pathological_tables import _is_pathological


def _make_table(bbox, rows):
    """Build a minimal stand-in for a TableBlock with the given rows.

    Each row is a list of (x0, y0, x1, y1) cell bboxes.
    """
    t = MagicMock()
    t.bbox = bbox
    # _rows must behave like an iterable of rows; each row must be
    # iterable of cells; each cell exposes a bbox.
    row_objs = []
    for cell_bboxes in rows:
        cells = []
        for cb in cell_bboxes:
            c = MagicMock()
            c.bbox = cb
            cells.append(c)
        row = cells
        row_objs.append(row)
    t._rows = row_objs
    return t


@pytest.mark.unit
def test_pathological_small_table_passes() -> None:
    """A small table covering < 70% of the parent is never pathological."""
    parent = (0, 0, 595, 842)  # A4-ish
    # 100x100 table inside A4 = ~2% area
    t = _make_table((50, 50, 150, 150), [[(50, 50, 100, 150), (100, 50, 150, 150)]])
    assert not _is_pathological(t, parent)


@pytest.mark.unit
def test_pathological_uniform_rows_passes() -> None:
    """A page-sized table whose row heights are all uniform is NOT pathological."""
    parent = (0, 0, 595, 842)
    # Three rows each spanning ~277pt vertically; cells per row also uniform
    rows = []
    for y_start in (0, 280, 560):
        rows.append([
            (0, y_start, 297, y_start + 280),
            (297, y_start, 595, y_start + 280),
        ])
    t = _make_table((0, 0, 595, 840), rows)
    assert not _is_pathological(t, parent)


@pytest.mark.unit
def test_pathological_mismatched_row_caught() -> None:
    """A page-sized table whose first row has a tiny cell next to a tall cell
    IS pathological - signature of the outer-rectangle-mistaken-for-table bug.
    """
    parent = (0, 0, 595, 842)
    # Row 0 mixes a 20pt-tall middle cell with 322pt-tall side cells
    pathological_rows = [
        [
            (0, 0, 5, 322),       # narrow left margin, 322pt tall
            (5, 0, 280, 22),      # tiny middle cell, 22pt tall
            (280, 0, 590, 22),    # tiny middle cell, 22pt tall
            (590, 0, 595, 322),   # narrow right margin, 322pt tall
        ],
        [(0, 322, 595, 760)],
        [(0, 760, 595, 840)],
    ]
    t = _make_table((0, 0, 595, 840), pathological_rows)
    assert _is_pathological(t, parent)


@pytest.mark.unit
def test_pathological_too_many_rows_passes() -> None:
    """A page-sized table with > 6 rows is NOT pathological even with mixed
    heights - it's likely a legitimate form / list."""
    parent = (0, 0, 595, 842)
    rows = []
    for i in range(8):
        y = i * 100
        rows.append([(0, y, 297, y + 100), (297, y, 595, y + 100)])
    t = _make_table((0, 0, 595, 800), rows)
    assert not _is_pathological(t, parent)
