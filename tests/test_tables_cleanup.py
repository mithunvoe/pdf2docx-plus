"""Unit tests for post-emit table cleanup passes.

Regression coverage for "tables out of nowhere" — upstream's lattice
detector faithfully finds bordered rectangles in the PDF (e.g. empty
checkbox grids, stroke artifacts) but content extraction leaves every
cell blank, so they surface in the DOCX as mysterious empty grids.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from docx import Document

# Import the module directly to avoid the pdf2docx_plus package __init__,
# which pulls in `fitz` (not needed for these pure-XML cleanup passes).
_SPEC = importlib.util.spec_from_file_location(
    "_tables_cleanup_under_test",
    Path(__file__).resolve().parent.parent
    / "pdf2docx_plus"
    / "emit"
    / "tables_cleanup.py",
)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
drop_empty_tables = _MOD.drop_empty_tables
trim_empty_table_rows = _MOD.trim_empty_table_rows


def _make_doc_with_tables(specs: list[list[list[str]]]):
    """Build a Document with one table per spec. spec = [row[cell_text]]."""
    doc = Document()
    for spec in specs:
        rows = len(spec)
        cols = max(len(r) for r in spec) if spec else 0
        tbl = doc.add_table(rows=rows, cols=cols)
        for ri, row in enumerate(spec):
            for ci, text in enumerate(row):
                tbl.cell(ri, ci).text = text
    return doc


@pytest.mark.unit
def test_drop_empty_tables_removes_all_blank() -> None:
    doc = _make_doc_with_tables(
        [
            [["", ""], ["", ""]],  # all blank → drop
            [["hello", ""], ["", ""]],  # one cell has content → keep
        ]
    )
    assert len(doc.tables) == 2
    removed = drop_empty_tables(doc)
    assert removed == 1
    assert len(doc.tables) == 1
    assert doc.tables[0].cell(0, 0).text == "hello"


@pytest.mark.unit
def test_drop_empty_tables_whitespace_is_empty() -> None:
    doc = _make_doc_with_tables([[["   ", "\t"], ["", "\n "]]])
    removed = drop_empty_tables(doc)
    assert removed == 1


@pytest.mark.unit
def test_drop_empty_tables_leaves_populated_sparse_tables() -> None:
    # sparse but not empty — genuine data table with mostly blank cells
    doc = _make_doc_with_tables([[["A", "", ""], ["", "", ""], ["", "", "Z"]]])
    removed = drop_empty_tables(doc)
    assert removed == 0
    assert len(doc.tables) == 1


@pytest.mark.unit
def test_trim_empty_table_rows_strips_leading_and_trailing() -> None:
    doc = _make_doc_with_tables(
        [[["", ""], ["x", "y"], ["", ""], ["z", "w"], ["", ""], ["", ""]]]
    )
    tbl = doc.tables[0]
    assert len(tbl.rows) == 6
    trimmed = trim_empty_table_rows(doc)
    assert trimmed == 3  # one leading + two trailing
    rows_after = [[c.text for c in r.cells] for r in doc.tables[0].rows]
    assert rows_after == [["x", "y"], ["", ""], ["z", "w"]]


@pytest.mark.unit
def test_trim_empty_table_rows_preserves_single_row() -> None:
    doc = _make_doc_with_tables([[["", ""]]])
    trimmed = trim_empty_table_rows(doc)
    assert trimmed == 0
    assert len(doc.tables[0].rows) == 1
