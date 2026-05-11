"""Tests for margin label detection."""

from __future__ import annotations

import pytest

from pdf2docx_plus.layout.margin_labels import MarginLabel


@pytest.mark.unit
def test_margin_label_record() -> None:
    label = MarginLabel(
        page_id=0,
        text="Confidential",
        bbox=(10.0, 100.0, 30.0, 700.0),
        edge="left",
    )
    assert label.page_id == 0
    assert label.text == "Confidential"
    assert label.edge == "left"


@pytest.mark.unit
def test_margin_label_is_frozen() -> None:
    label = MarginLabel(page_id=0, text="DRAFT", bbox=(0, 0, 1, 1), edge="right")
    with pytest.raises(Exception):
        label.text = "modified"  # type: ignore[misc]
