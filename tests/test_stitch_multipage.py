"""Regression test for Issue B3: a table spanning 3+ pages must chain.

Before the fix the stitcher only merged adjacent page PAIRS and never
re-anchored: after merging (page0,page1) it emptied page1's blocks, so
``_last_table(page1)`` returned None and the (page1->page2) transition was
skipped entirely. The FAQ_SFC table (Q1..Q9 across 3 pages) was therefore
emitted as two tables with a fabricated duplicate header.
"""
from __future__ import annotations

import pytest

from pdf2docx_plus.tables.stitch import stitch_cross_page_tables


class _Span:
    def __init__(self, text: str) -> None:
        self.text = text


class _Line:
    def __init__(self, text: str) -> None:
        self.spans = [_Span(text)]


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.lines = [_Line(text)]


class _Blocks:
    def __init__(self, items: list) -> None:
        self._instances = list(items)

    def __iter__(self):
        return iter(self._instances)

    def __len__(self) -> int:
        return len(self._instances)


class _Cell:
    def __init__(self, text: str, bbox: tuple) -> None:
        self.blocks = _Blocks([_TextBlock(text)] if text else [])
        self.bbox = bbox


def _row(c0: str, c1: str) -> list:
    return [_Cell(c0, (50, 0, 300, 10)), _Cell(c1, (300, 0, 550, 10))]


class _Rows:
    def __init__(self, rows: list) -> None:
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def append(self, row) -> None:
        self._rows.append(row)


class _Table:
    is_table_block = True

    def __init__(self, rows: list, bbox: tuple) -> None:
        self._rows = _Rows(rows)
        self.bbox = bbox

    @property
    def num_rows(self) -> int:
        return len(list(self._rows))


class _Column:
    def __init__(self, blocks: list) -> None:
        self.blocks = _Blocks(blocks)

    def __iter__(self):
        return iter([self])  # a column is its own single iterable element


class _Section:
    def __init__(self, column: _Column) -> None:
        self._column = column

    def __iter__(self):
        return iter([self._column])


class _Page:
    def __init__(self, pid: int, table: _Table, bbox: tuple) -> None:
        self.id = pid
        self.finalized = True
        self.bbox = bbox
        self.sections = [_Section(_Column([table]))]


def _make_table(rows_text: list[tuple[str, str]], bbox: tuple) -> _Table:
    return _Table([_row(a, b) for a, b in rows_text], bbox)


PAGE_BBOX = (0, 0, 600, 800)
HEADER = ("Question", "Answer")


def test_three_page_table_chains_into_one():
    # page0 table at the bottom; page1 & page2 tables at the top, same header
    t0 = _make_table([HEADER, ("Q1", "A1"), ("Q2", "A2")], (50, 700, 550, 790))
    t1 = _make_table([HEADER, ("Q3", "A3"), ("Q4", "A4")], (50, 10, 550, 400))
    t2 = _make_table([HEADER, ("Q5", "A5"), ("Q6", "A6")], (50, 10, 550, 400))
    pages = [
        _Page(0, t0, PAGE_BBOX),
        _Page(1, t1, PAGE_BBOX),
        _Page(2, t2, PAGE_BBOX),
    ]
    report = stitch_cross_page_tables(pages)

    assert report.merged_pairs == [(0, 1), (1, 2)], report.merged_pairs
    # t0 now holds: header + Q1,Q2 + Q3,Q4 + Q5,Q6 = 7 rows (headers de-duped)
    assert t0.num_rows == 7, t0.num_rows
    # pages 1 and 2 no longer carry their own table
    assert all(
        not any(getattr(b, "is_table_block", False) for b in col.blocks)
        for p in pages[1:]
        for sec in p.sections
        for col in sec
    )
