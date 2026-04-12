"""Tests for the backend protocol seam."""

from __future__ import annotations

import pytest

from pdf2docx_plus.backends import Backend, FitzBackend, get_backend, register_backend
from pdf2docx_plus.errors import ConversionError


@pytest.mark.unit
def test_default_is_fitz() -> None:
    assert get_backend().name == "fitz"


@pytest.mark.unit
def test_fitz_backend_satisfies_protocol() -> None:
    assert isinstance(FitzBackend(), Backend)


@pytest.mark.unit
def test_env_var_override(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyBackend:
        name = "dummy"

        def open(self, **_): ...
        def close(self, doc): ...
        def page_count(self, doc):
            return 0

        def page_rect(self, doc, i):
            return (0.0, 0.0, 0.0, 0.0)

        def page_rotation(self, doc, i):
            return 0

        def extract_raw_dict(self, doc, i):
            return {}

        def render_to_pixmap(self, doc, i, *, zoom=3.0): ...

    register_backend("dummy", DummyBackend())
    monkeypatch.setenv("PDF2DOCX_BACKEND", "dummy")
    assert get_backend().name == "dummy"


@pytest.mark.unit
def test_unknown_backend_raises() -> None:
    with pytest.raises(ConversionError):
        get_backend("definitely-not-a-real-backend")
