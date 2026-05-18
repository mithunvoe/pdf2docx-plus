"""Issue P-6: pseudo-table promotion heuristic.

The upstream stream-table promoter used to wrap any region whose
text-block layout aligned with a faint horizontal line in a 1x1
``<w:tbl>``.  On fund-prospectus documents this catches indent guides
and paragraph rules and converts ordinary item-lists like
"(ii) in the case of Government and other Public Securities…" into
a phantom one-cell table.  Downstream diff tools then see one side as
a table-delete + body-insert and the other side as the reverse, even
though the content is unchanged.

After P-6 the constructor refuses 1x1 stream tables that lack a strict
table signal: either a non-grey shading covering >=50% of the cell or
real stroked borders (>= 0.5 pt) on >= 3 of the 4 sides.
"""

from __future__ import annotations

import pytest

import fitz

from pdf2docx_plus._vendored.pdf2docx.table.TablesConstructor import (
    TablesConstructor,
)


class _FakeStroke:
    def __init__(self, x0, y0, x1, y1, width):
        self.bbox = fitz.Rect(x0, y0, x1, y1)
        self.width = width


class _FakeShading:
    def __init__(self, x0, y0, x1, y1, color):
        self.bbox = fitz.Rect(x0, y0, x1, y1)
        self.color = color


class _FakeCell:
    def __init__(self, bbox, bg_color=None):
        self.bbox = fitz.Rect(*bbox)
        self.bg_color = bg_color


class _FakeRow(list):
    pass


class _FakeTable:
    def __init__(self, cell):
        self.num_rows = 1
        self.num_cols = 1
        self._rows = [_FakeRow([cell])]

    def __bool__(self) -> bool:
        return True

    def __getitem__(self, idx):
        return self._rows[idx]


CELL = (100.0, 200.0, 400.0, 240.0)


@pytest.mark.unit
def test_strict_signal_when_borders_on_3_sides() -> None:
    table = _FakeTable(_FakeCell(CELL))
    strokes = [
        _FakeStroke(100.0, 200.0, 400.0, 200.0, 0.7),  # top
        _FakeStroke(100.0, 240.0, 400.0, 240.0, 0.7),  # bottom
        _FakeStroke(100.0, 200.0, 100.0, 240.0, 0.7),  # left
    ]
    assert TablesConstructor._has_strict_table_signal(table, strokes, [])


@pytest.mark.unit
def test_strict_signal_when_borders_on_all_4_sides() -> None:
    table = _FakeTable(_FakeCell(CELL))
    strokes = [
        _FakeStroke(100.0, 200.0, 400.0, 200.0, 0.7),
        _FakeStroke(100.0, 240.0, 400.0, 240.0, 0.7),
        _FakeStroke(100.0, 200.0, 100.0, 240.0, 0.7),
        _FakeStroke(400.0, 200.0, 400.0, 240.0, 0.7),
    ]
    assert TablesConstructor._has_strict_table_signal(table, strokes, [])


@pytest.mark.unit
def test_no_strict_signal_when_only_2_sides() -> None:
    """Two-sided borders (e.g. top and bottom rules around a paragraph)
    are a common indent-guide pattern — NOT a real table."""
    table = _FakeTable(_FakeCell(CELL))
    strokes = [
        _FakeStroke(100.0, 200.0, 400.0, 200.0, 0.7),
        _FakeStroke(100.0, 240.0, 400.0, 240.0, 0.7),
    ]
    assert not TablesConstructor._has_strict_table_signal(table, strokes, [])


@pytest.mark.unit
def test_no_strict_signal_when_borders_too_thin() -> None:
    """Strokes thinner than 0.5 pt are decorative — not real borders."""
    table = _FakeTable(_FakeCell(CELL))
    strokes = [
        _FakeStroke(100.0, 200.0, 400.0, 200.0, 0.2),
        _FakeStroke(100.0, 240.0, 400.0, 240.0, 0.2),
        _FakeStroke(100.0, 200.0, 100.0, 240.0, 0.2),
    ]
    assert not TablesConstructor._has_strict_table_signal(table, strokes, [])


@pytest.mark.unit
def test_no_strict_signal_when_stroke_too_short() -> None:
    """A short stroke that touches a side but only covers a fraction of
    its length isn't a real border (e.g. an indent tick)."""
    table = _FakeTable(_FakeCell(CELL))
    strokes = [
        _FakeStroke(100.0, 200.0, 150.0, 200.0, 0.7),  # only ~17% of width
        _FakeStroke(100.0, 240.0, 400.0, 240.0, 0.7),
        _FakeStroke(100.0, 200.0, 100.0, 240.0, 0.7),
    ]
    assert not TablesConstructor._has_strict_table_signal(table, strokes, [])


@pytest.mark.unit
def test_strict_signal_when_cell_bg_color_set() -> None:
    """A shaded callout box (cell.bg_color set) is a strict signal."""
    table = _FakeTable(_FakeCell(CELL, bg_color=0xFFCC00))
    assert TablesConstructor._has_strict_table_signal(table, [], [])


@pytest.mark.unit
def test_strict_signal_when_explicit_shading_covers_cell() -> None:
    """An explicit non-white shading covering >=50% of the cell is a
    strict signal."""
    table = _FakeTable(_FakeCell(CELL))
    shading = _FakeShading(100.0, 200.0, 400.0, 240.0, color=0xFFCC00)
    assert TablesConstructor._has_strict_table_signal(table, [], [shading])


@pytest.mark.unit
def test_no_strict_signal_when_shading_covers_only_corner() -> None:
    table = _FakeTable(_FakeCell(CELL))
    shading = _FakeShading(100.0, 200.0, 150.0, 210.0, color=0xFFCC00)
    assert not TablesConstructor._has_strict_table_signal(table, [], [shading])


@pytest.mark.unit
def test_no_strict_signal_when_shading_is_white() -> None:
    table = _FakeTable(_FakeCell(CELL))
    shading = _FakeShading(100.0, 200.0, 400.0, 240.0, color=0xFFFFFF)
    assert not TablesConstructor._has_strict_table_signal(table, [], [shading])


@pytest.mark.unit
def test_multi_cell_table_is_never_second_guessed() -> None:
    """The 1x1 guard does not apply to multi-cell tables — they go
    through the normal pipeline."""

    class _MultiTable:
        num_rows = 2
        num_cols = 3

        def __bool__(self):
            return True

    assert TablesConstructor._has_strict_table_signal(_MultiTable(), [], [])


@pytest.mark.unit
def test_falsy_table_keeps_promotion() -> None:
    """If the constructed table is falsy (degenerate), we don't block
    promotion at this stage; upstream handles that path."""

    class _Empty:
        num_rows = 0
        num_cols = 0

        def __bool__(self):
            return False

    assert TablesConstructor._has_strict_table_signal(_Empty(), [], [])
