"""Error hierarchy tests."""

from __future__ import annotations

import pytest

from pdf2docx_plus.errors import (
    ConversionError,
    InputError,
    MakeDocxError,
    ParseError,
    PasswordRequired,
    PluginError,
    TimeoutExceeded,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "cls",
    [InputError, ParseError, MakeDocxError, PasswordRequired, TimeoutExceeded, PluginError],
)
def test_all_subclass_conversion_error(cls: type[Exception]) -> None:
    assert issubclass(cls, ConversionError)


@pytest.mark.unit
def test_password_required_is_input_error() -> None:
    assert issubclass(PasswordRequired, InputError)


@pytest.mark.unit
def test_error_carries_page() -> None:
    e = ParseError("bad", page=4)
    assert e.page == 4
    assert "bad" in str(e)
