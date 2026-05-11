"""Tests for pathological lattice-table content recovery."""

from __future__ import annotations

import pytest

from pdf2docx_plus.tables.recover_content import (
    RecoveryReport,
    _bbox_contained,
    _bbox_intersects_any,
)


@pytest.mark.unit
def test_recovery_report_default_empty() -> None:
    r = RecoveryReport()
    assert r.pathological_tables == []
    assert r.blocks_recovered == 0


@pytest.mark.unit
def test_bbox_contained_basic() -> None:
    outer = (0.0, 0.0, 100.0, 100.0)
    inner = (10.0, 10.0, 90.0, 90.0)
    assert _bbox_contained(inner, outer)


@pytest.mark.unit
def test_bbox_contained_with_pad() -> None:
    outer = (0.0, 0.0, 100.0, 100.0)
    inner = (-2.0, -2.0, 102.0, 102.0)
    assert not _bbox_contained(inner, outer)
    assert _bbox_contained(inner, outer, pad=3.0)


@pytest.mark.unit
def test_bbox_intersects_any_above_threshold() -> None:
    candidate = (0.0, 0.0, 100.0, 100.0)
    others = [(50.0, 50.0, 150.0, 150.0)]
    # 25% overlap area
    assert not _bbox_intersects_any(candidate, others, threshold=0.5)
    assert _bbox_intersects_any(candidate, others, threshold=0.2)


@pytest.mark.unit
def test_bbox_intersects_any_no_overlap() -> None:
    candidate = (0.0, 0.0, 50.0, 50.0)
    others = [(100.0, 100.0, 200.0, 200.0)]
    assert not _bbox_intersects_any(candidate, others, threshold=0.0)
