"""Structured exception hierarchy for pdf2docx-plus.

All user-visible failures inherit from `ConversionError` so callers can catch
a single type. Sub-classes distinguish phase (input / parse / make-docx) so
callers can branch on recoverable vs terminal conditions.
"""

from __future__ import annotations


class ConversionError(Exception):
    """Base class for every pdf2docx-plus error."""

    page: int | None = None

    def __init__(self, message: str, *, page: int | None = None) -> None:
        super().__init__(message)
        self.page = page


class InputError(ConversionError):
    """PDF cannot be opened (missing, not a PDF, corrupted header)."""


class PasswordRequired(InputError):
    """PDF is encrypted and the supplied password was missing or wrong."""


class ParseError(ConversionError):
    """A specific page could not be parsed."""


class MakeDocxError(ConversionError):
    """Parsed layout could not be emitted to DOCX."""


class TimeoutExceeded(ConversionError):
    """User-supplied timeout expired before conversion finished."""


class PluginError(ConversionError):
    """A registered plugin raised or returned an invalid value."""


__all__ = [
    "ConversionError",
    "InputError",
    "MakeDocxError",
    "ParseError",
    "PasswordRequired",
    "PluginError",
    "TimeoutExceeded",
]
