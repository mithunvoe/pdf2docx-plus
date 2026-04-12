"""Public API surface tests."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from pdf2docx_plus import (
    ConversionResult,
    Converter,
    InputError,
    __version__,
    convert,
)


@pytest.mark.unit
def test_version_is_string() -> None:
    assert isinstance(__version__, str)
    assert __version__.count(".") >= 2


@pytest.mark.unit
def test_converter_requires_input() -> None:
    with pytest.raises(InputError):
        Converter()


@pytest.mark.unit
def test_converter_missing_file() -> None:
    with pytest.raises(InputError):
        Converter("/tmp/does_not_exist_9873.pdf")


@pytest.mark.integration
def test_convert_small_pdf_to_path(tmp_path: Path, kfs_pdf: Path) -> None:
    out = tmp_path / "out.docx"
    result = convert(kfs_pdf, out, timeout_s=60)
    assert isinstance(result, ConversionResult)
    assert result.success
    assert result.pages_ok == result.pages_total > 0
    assert out.exists()
    assert out.stat().st_size > 10_000


@pytest.mark.integration
def test_convert_to_bytesio(kfs_pdf: Path) -> None:
    sink = io.BytesIO()
    with Converter(kfs_pdf) as cv:
        result = cv.convert(sink, timeout_s=60)
    assert result.success
    sink.seek(0)
    head = sink.read(4)
    assert head == b"PK\x03\x04", "DOCX must be a ZIP (OOXML)"


@pytest.mark.integration
def test_page_results_populated(tmp_path: Path, kfs_pdf: Path) -> None:
    out = tmp_path / "out.docx"
    with Converter(kfs_pdf) as cv:
        result = cv.convert(out, timeout_s=60)
    assert len(result.page_results) == result.pages_total
    assert all(p.ok for p in result.page_results)


@pytest.mark.integration
def test_profile_fast_vs_fidelity(tmp_path: Path, kfs_pdf: Path) -> None:
    out_fast = tmp_path / "fast.docx"
    out_fid = tmp_path / "fid.docx"
    with Converter(kfs_pdf) as cv:
        r1 = cv.convert(out_fast, profile="fast", timeout_s=60)
    with Converter(kfs_pdf) as cv:
        r2 = cv.convert(out_fid, profile="fidelity", timeout_s=60)
    assert r1.success and r2.success
