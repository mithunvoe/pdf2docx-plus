"""Tests for advanced cross-page table stitching."""

from __future__ import annotations

import pytest

from pdf2docx_plus.tables.stitch import (
    _FOOTNOTE_PREFIX,
    _PAGE_FOOTER_PATTERNS,
    StitchReport,
)


@pytest.mark.unit
def test_footnote_prefix_regex_matches_typical() -> None:
    assert _FOOTNOTE_PREFIX.match("1 Please refer to the circular entitled")
    assert _FOOTNOTE_PREFIX.match("12 This is footnote twelve")
    assert _FOOTNOTE_PREFIX.match("100 Three-digit footnote")


@pytest.mark.unit
def test_footnote_prefix_rejects_non_footnotes() -> None:
    assert _FOOTNOTE_PREFIX.match("1234 too many digits") is None
    assert _FOOTNOTE_PREFIX.match("a regular paragraph") is None
    assert _FOOTNOTE_PREFIX.match("1.0 starts with decimal number") is None


@pytest.mark.unit
def test_page_footer_patterns_present() -> None:
    assert "last update" in _PAGE_FOOTER_PATTERNS
    assert "page " in _PAGE_FOOTER_PATTERNS


@pytest.mark.unit
def test_stitch_report_default() -> None:
    r = StitchReport()
    assert r.merged_pairs == []
    assert r.skipped_pairs == []
    assert r.continuation_rows_merged == 0
