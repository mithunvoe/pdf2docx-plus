"""pdf2docx-plus: hardened PDF -> DOCX converter.

Public API:

    from pdf2docx_plus import Converter, convert, ConversionResult

    result = convert("in.pdf", "out.docx", timeout_s=60)
    print(result.pages_ok, result.pages_failed, result.elapsed_s)

Lower-level facade:

    with Converter("in.pdf") as cv:
        cv.convert("out.docx", pages=[0, 1, 2])
"""

from __future__ import annotations

from .api import ConversionResult, Converter, convert, extract_tables
from .errors import (
    ConversionError,
    InputError,
    MakeDocxError,
    ParseError,
    PasswordRequired,
    TimeoutExceeded,
)
from .version import __version__

__all__ = [
    "ConversionError",
    "ConversionResult",
    "Converter",
    "InputError",
    "MakeDocxError",
    "ParseError",
    "PasswordRequired",
    "TimeoutExceeded",
    "__version__",
    "convert",
    "extract_tables",
]
