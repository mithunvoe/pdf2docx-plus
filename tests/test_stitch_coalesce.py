"""Regression tests for cross-page row coalescing (`_coalesce_row`).

Earlier ``_coalesce_row`` mutated ``last_span.text`` directly, which is a
silent no-op for spans backed by a populated ``chars`` list.  The fix
transfers whole text blocks via ``_transfer_cell_blocks``, preserving
the source content in full.

These tests cover the contract at the unit level (no PDF round-trip).
"""

from __future__ import annotations

import pytest

from pdf2docx_plus.tables.stitch import (
    _coalesce_row,
    _transfer_cell_blocks,
)


class _FakeBlocks:
    """Minimal stand-in for ``pdf2docx``'s ``Blocks`` collection."""

    def __init__(self, instances: list) -> None:
        self._instances = list(instances)

    def __iter__(self):
        return iter(self._instances)

    def __len__(self) -> int:
        return len(self._instances)


class _FakeChar:
    def __init__(self, c: str) -> None:
        self.c = c


class _FakeSpan:
    def __init__(self, text: str) -> None:
        self.chars = [_FakeChar(ch) for ch in text]
        self._text = ""

    @property
    def text(self) -> str:
        # Mirror upstream behaviour: derive from chars when populated.
        return "".join(c.c for c in self.chars) if self.chars else self._text

    @text.setter
    def text(self, value: str) -> None:
        # Setter only updates the fallback; the getter still trumps it.
        self._text = value


class _FakeLine:
    def __init__(self, spans: list) -> None:
        self.spans = spans


class _FakeTextBlock:
    def __init__(self, lines: list) -> None:
        self.lines = lines


class _FakeCell:
    def __init__(self, blocks: list) -> None:
        self.blocks = _FakeBlocks(blocks)


def _make_cell(text: str) -> _FakeCell:
    return _FakeCell([_FakeTextBlock([_FakeLine([_FakeSpan(text)])])])


def _cell_concatenated_text(cell: _FakeCell) -> str:
    parts: list[str] = []
    for block in cell.blocks._instances:
        for line in block.lines:
            for span in line.spans:
                parts.append(span.text)
    return "".join(parts)


@pytest.mark.unit
def test_transfer_cell_blocks_preserves_full_source_text() -> None:
    """Whole-block transfer must not lose any source characters.

    Earlier code path stringified the source cell and assigned the
    result to ``last_span.text`` on the destination, which is a silent
    no-op when the span carries ``chars``.  The replacement transfers
    text blocks directly into the destination's block list, so every
    character survives.
    """
    src_cell = _make_cell("A fund manager should critically assess the impact")
    dst_cell = _make_cell("Pursuant to the SFC Handbook... Issues to consider")

    _transfer_cell_blocks(dst_cell, src_cell)

    final_text = _cell_concatenated_text(dst_cell)
    assert "Pursuant to the SFC Handbook" in final_text
    assert "Issues to consider" in final_text
    assert "A fund manager should critically assess the impact" in final_text


@pytest.mark.unit
def test_transfer_cell_blocks_handles_long_continuation() -> None:
    """A realistic 1300-char continuation must arrive intact.

    Mirrors the FAQ_PostAuth Q3B answer wrap-over: when a fund-list
    Q&A row wraps from page N to page N+1, the second-page table's
    only row carries the entire mid-cell text, ~1300 chars including
    bullet glyphs and sub-lists.  Earlier behaviour dropped all but
    the first character of this text.
    """
    long_body = (
        "A fund manager should critically assess the potential impact of "
        "Market Suspension on SFC-authorized funds under its management "
        "and the investors of the funds, and should ensure that it has "
        "in place appropriate policies and procedures (including "
        "contingency plans) to address such impact in the event of "
        "Market Suspension.\n"
        "* how the net asset value of the fund(s) should be calculated;\n"
        "* if/how any fair valuation adjustments should be made;\n"
        "* how to ensure: a. strict compliance with the principle of "
        "forward pricing; b. all investors are treated fairly; c. the "
        "policies and procedures to be put in place are done in the "
        "best interests of the fund;\n"
        "* how the dealing and settlement arrangements will be affected, "
        "such as: a. whether the day on which Market Suspension occurs "
        "is still a dealing day for the fund; b. if so, whether the "
        "fund manager will suspend dealing on that day or make any "
        "changes to the cut-off time for accepting subscription and "
        "redemption orders; and if it is the latter case, i. whether "
        "the subscription and redemption orders received after the"
    )
    assert len(long_body) > 1000  # sanity: matches the real-world size

    src_cell = _make_cell(long_body)
    dst_cell = _make_cell("Pursuant to the SFC Handbook for Unit Trusts")

    _transfer_cell_blocks(dst_cell, src_cell)

    final_text = _cell_concatenated_text(dst_cell)
    # Spot-check three widely separated fragments to confirm nothing
    # was truncated mid-content.
    assert "A fund manager should critically assess" in final_text
    assert "how the dealing and settlement arrangements" in final_text
    assert (
        "whether the subscription and redemption orders received after the"
        in final_text
    )


@pytest.mark.unit
def test_coalesce_row_transfers_each_non_empty_cell() -> None:
    """Row-level coalesce must transfer every non-empty source cell."""
    src_row = [
        _make_cell(""),
        _make_cell("(“Market Suspension”)?"),
        _make_cell("A fund manager should critically assess"),
    ]
    dst_row = [
        _make_cell("3B."),
        _make_cell("What should the fund manager note"),
        _make_cell("Pursuant to the SFC Handbook"),
    ]

    _coalesce_row(dst_row, src_row)

    assert "3B." in _cell_concatenated_text(dst_row[0])
    assert "What should the fund manager note" in _cell_concatenated_text(dst_row[1])
    assert "(“Market Suspension”)?" in _cell_concatenated_text(dst_row[1])
    assert "Pursuant to the SFC Handbook" in _cell_concatenated_text(dst_row[2])
    assert "A fund manager should critically assess" in _cell_concatenated_text(dst_row[2])


@pytest.mark.unit
def test_coalesce_row_skips_empty_source_cells() -> None:
    """Empty source cells must not produce any destination mutation."""
    src_row = [_make_cell(""), _make_cell(""), _make_cell("")]
    dst_row = [
        _make_cell("3B."),
        _make_cell("Q text"),
        _make_cell("Pursuant"),
    ]

    _coalesce_row(dst_row, src_row)

    assert _cell_concatenated_text(dst_row[0]) == "3B."
    assert _cell_concatenated_text(dst_row[1]) == "Q text"
    assert _cell_concatenated_text(dst_row[2]) == "Pursuant"


@pytest.mark.unit
def test_transfer_cell_blocks_no_op_when_dst_blocks_missing() -> None:
    """Missing destination block container -> no exception, no mutation."""

    class _NoBlocksCell:
        blocks = None

    src_cell = _make_cell("ignored")
    dst_cell = _NoBlocksCell()
    _transfer_cell_blocks(dst_cell, src_cell)  # must not raise
