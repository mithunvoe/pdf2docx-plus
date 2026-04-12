"""Plugin registry behaviour."""

from __future__ import annotations

import pytest

from pdf2docx_plus.plugins import PluginRegistry


@pytest.mark.unit
def test_registry_starts_empty() -> None:
    reg = PluginRegistry()
    assert reg.table_detectors == []
    assert reg.layout_detectors == []
    assert reg.ocr_engines == []
    assert reg.formula_recognizers == []


@pytest.mark.unit
def test_page_callbacks_are_isolated() -> None:
    reg = PluginRegistry()
    seen: list[str] = []
    reg.on_page_parsed(lambda p: seen.append("a"))
    reg.on_page_parsed(lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    reg.on_page_parsed(lambda p: seen.append("c"))
    reg.dispatch_page_parsed(None)
    assert seen == ["a", "c"]  # 'b' raised but didn't break subsequent callbacks


@pytest.mark.unit
def test_add_detector_appends() -> None:
    reg = PluginRegistry()

    class DummyTable:
        def detect(self, img, idx, bbox):
            return []

    d = DummyTable()
    reg.add_table_detector(d)
    assert reg.table_detectors == [d]
