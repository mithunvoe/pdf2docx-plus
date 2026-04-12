"""Regression tests for `_resolve_output` directory handling."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from pdf2docx_plus.api import _resolve_output
from pdf2docx_plus.errors import InputError


@pytest.mark.unit
def test_file_path_passthrough(tmp_path: Path) -> None:
    out = tmp_path / "out.docx"
    assert _resolve_output(out, "in.pdf") == str(out)


@pytest.mark.unit
def test_none_derives_from_input(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    assert _resolve_output(None, str(pdf)) == str(tmp_path / "doc.docx")


@pytest.mark.unit
def test_none_with_stream_raises() -> None:
    with pytest.raises(InputError):
        _resolve_output(None, None)


@pytest.mark.unit
def test_existing_directory_derives_name(tmp_path: Path) -> None:
    result = _resolve_output(tmp_path, "/abs/path/report.pdf")
    assert result == str(tmp_path / "report.docx")


@pytest.mark.unit
def test_dot_is_current_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = _resolve_output(".", "/abs/path/report.pdf")
    assert Path(result).name == "report.docx"


@pytest.mark.unit
def test_trailing_slash_creates_dir(tmp_path: Path) -> None:
    new_dir = tmp_path / "new_sub"
    result = _resolve_output(str(new_dir) + "/", "in.pdf")
    assert new_dir.is_dir()
    assert result == str(new_dir / "in.docx")


@pytest.mark.unit
def test_stream_passthrough() -> None:
    sink = io.BytesIO()
    assert _resolve_output(sink, "in.pdf") is sink


@pytest.mark.unit
def test_directory_with_stream_input_raises(tmp_path: Path) -> None:
    with pytest.raises(InputError):
        _resolve_output(tmp_path, None)
