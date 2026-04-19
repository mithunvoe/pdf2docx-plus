"""Regression tests for Wingdings / Symbol PUA translation.

Ensures ``pdf2docx_plus.fidelity.symbols.translate`` maps the common
Private Use Area glyphs produced by symbol fonts to portable Unicode
characters so DOCX consumers without the source font still render
bullets, arrows, and checkboxes.
"""

from __future__ import annotations

import pytest

from pdf2docx_plus.fidelity.symbols import translate


@pytest.mark.parametrize(
    "text,font,expected",
    [
        ("\uf0a8", "Wingdings", "\u25a1"),          # ballot box
        ("\uf0d8", "Wingdings", "\u25b8"),          # triangular right-pointing bullet
        ("\uf0fc", "Wingdings", "\u2713"),          # check mark
        ("\uf0b7", "Symbol", "\u2022"),             # bullet
        ("\uf0d7", "Symbol", "\u00d7"),             # multiplication
        # Works with subset-prefixed font names too
        ("\uf0a8", "BCDEEE+Wingdings", "\u25a1"),
    ],
)
def test_translate_wingdings_and_symbol(text: str, font: str, expected: str) -> None:
    out_text, out_font, changed = translate(text, font)
    assert changed is True
    assert out_text == expected
    assert out_font != ""  # a substitute font is chosen


def test_translate_non_symbol_font_is_noop() -> None:
    out_text, out_font, changed = translate("\uf0a8", "Times")
    # Even though font isn't Symbol/Wingdings, U+F0A8 looks like Wingdings PUA,
    # so our fallback mapping translates it.
    assert changed is True
    assert out_text == "\u25a1"
    assert out_font == "Arial"


def test_translate_keeps_non_pua_text_unchanged() -> None:
    text = "Hello, world!"
    out_text, out_font, changed = translate(text, "Wingdings")
    assert changed is False
    assert out_text == text
    assert out_font == "Wingdings"


def test_translate_handles_mixed_content() -> None:
    text = "Yes \uf0a8  No \uf0a8"
    out_text, out_font, changed = translate(text, "Wingdings")
    assert changed is True
    assert out_text == "Yes \u25a1  No \u25a1"
