"""Transliterate Wingdings / Symbol PUA codepoints to portable Unicode.

PDF authors often use the Wingdings, Webdings, or Symbol fonts for
bullets, arrows, and checkboxes. PyMuPDF returns the raw Private Use
Area codepoints (``U+F020`` - ``U+F0FF``) that those fonts map, e.g.
``\\uf0a8`` for "ballot box". When a DOCX consumer renders without
those fonts installed (LibreOffice on Linux, Word on macOS without
symbol fonts, headless converters, etc.) the glyph falls back to a
replacement square and the bullet/checkbox disappears from the page.

The mapping here follows the well-known character-by-character layouts
published by Microsoft for Wingdings and Adobe for Symbol. We keep a
conservative set: only codepoints that have an obviously equivalent
standard Unicode glyph (bullets, arrows, checkboxes, checks, crosses).
The rest of the PUA space is left untouched so we don't silently lose
information.

The patch also retargets the ``w:rFonts`` of the run so the replacement
glyph is rendered with a general-purpose font instead of the symbol
font. Without this, some consumers still substitute the symbol font
and fail to display the plain Unicode character.
"""

from __future__ import annotations

from typing import Dict, Tuple

from pdf2docx_plus._vendored.pdf2docx.text import TextSpan as _ts


# ---- Wingdings ------------------------------------------------------------
# Source: https://en.wikipedia.org/wiki/Wingdings
_WINGDINGS: Dict[str, str] = {
    # bullets / squares
    "\uf06c": "\u25cf",      # black circle (bullet)
    "\uf06d": "\u25a0",      # black square
    "\uf06e": "\u25fc",      # black medium square
    "\uf070": "\u25c6",      # black diamond
    "\uf071": "\u25c7",      # white diamond
    "\uf076": "\u25c6",      # black diamond variant
    "\uf0a7": "\u25aa",      # small black square
    "\uf0a8": "\u25a1",      # white square (renders reliably; many fonts lack U+2610)
    "\uf0a9": "\u25a1",      # white square
    "\uf0a6": "\u25cf",      # filled circle variant
    # checkmarks / crosses
    "\uf0fc": "\u2713",      # CHECK MARK
    "\uf0fd": "\u2717",      # BALLOT X
    "\uf0fe": "\u2612",      # BALLOT BOX WITH X
    "\uf0fb": "\u2611",      # BALLOT BOX WITH CHECK
    # arrows / arrowhead bullets (triangular)
    "\uf0d8": "\u25b8",      # Wingdings 0xD8 -> triangular right-pointing (➤ style bullet)
    "\uf0d7": "\u25c2",      # left-pointing triangle
    "\uf0d9": "\u25be",      # down-pointing triangle
    "\uf0da": "\u25b4",      # up-pointing triangle
    "\uf0e0": "\u2192",      # right arrow
    "\uf0e1": "\u2190",      # left arrow
    "\uf0e2": "\u2191",      # up arrow
    "\uf0e3": "\u2193",      # down arrow
    "\uf0f0": "\u21d2",      # right double arrow
    "\uf0f2": "\u21d0",      # left double arrow
    # stars
    "\uf0ab": "\u2605",      # black star
    "\uf0aa": "\u2606",      # white star
    # hand pointers (fall back to generic arrow)
    "\uf0e8": "\u261e",      # pointing right hand
    "\uf0e9": "\u261a",      # pointing left hand
    # misc geometric
    "\uf0f8": "\u25cf",      # large filled circle
    "\uf09e": "\u25a0",      # medium filled square
}

# ---- Symbol (Adobe) -------------------------------------------------------
# Source: https://unicode.org/Public/MAPPINGS/VENDORS/ADOBE/symbol.txt
_SYMBOL: Dict[str, str] = {
    "\uf0b7": "\u2022",      # BULLET
    "\uf0b0": "\u00b0",      # DEGREE SIGN
    "\uf0a8": "\u2022",      # round bullet (Symbol)
    "\uf0ae": "\u2192",      # right arrow
    "\uf0b3": "\u2265",      # greater-or-equal
    "\uf0b2": "\u00b2",      # superscript 2
    "\uf0b9": "\u2260",      # not equal
    "\uf0d7": "\u00d7",      # multiplication sign
    "\uf0d6": "\u2193",      # down arrow
    "\uf0d8": "\u27a2",      # three-d top-lighted rightwards arrowhead (>>)
    "\uf0e0": "\u2329",      # left angle bracket
    "\uf0f1": "\u232a",      # right angle bracket
    "\uf0f7": "\u00f7",      # division sign
}


def _normalise_font(raw: str | None) -> str:
    if not raw:
        return ""
    # PyMuPDF often returns subset-prefixed names like "BCDEEE+Wingdings"
    s = raw.split("+")[-1].lower()
    return s


def _get_mapping(font: str) -> Tuple[Dict[str, str], str] | None:
    """Return (mapping, substitute font) or None.

    The substitute font must be one that's widely available on Windows,
    macOS, and Linux and has the ``U+25xx``/``U+27xx`` glyphs we target.
    ``Arial Unicode MS`` exists on Word/macOS; generic ``Arial`` covers
    Windows/Linux (LibreOffice maps it to Liberation Sans / DejaVu Sans
    which both carry the shapes we substitute to).
    """
    norm = _normalise_font(font)
    if "wingdings" in norm:
        return _WINGDINGS, "Arial"
    if "symbol" in norm:
        # beware: "MSymbol", "MS Gothic" etc. should not match "symbol" alone,
        # but Adobe "Symbol" is a distinct font and we want to translate.
        # We guard against substrings by checking equality / word boundary.
        if norm == "symbol" or norm.endswith(" symbol") or norm.startswith("symbol"):
            return _SYMBOL, "Arial"
    if "webdings" in norm:
        return _WINGDINGS, "Arial"
    return None


# Union table used as a fall-back when the run's font name is empty or
# has been wiped by upstream's ``Fonts.get`` edge case (where an empty
# descriptor matches every target and overwrites ``span.font`` with an
# empty string). Codepoints in the Wingdings/Symbol PUA ranges have no
# semantics outside those fonts, so translating them to Unicode is
# always an improvement even when we can't positively identify the
# source font.
_FALLBACK: Dict[str, str] = {}
_FALLBACK.update(_WINGDINGS)
for _k, _v in _SYMBOL.items():
    _FALLBACK.setdefault(_k, _v)


def translate(text: str, font: str) -> Tuple[str, str, bool]:
    """Return (translated_text, replacement_font, changed).

    When no mapping applies we return the inputs unchanged with
    ``changed=False``. When any codepoint was translated we also return
    the substitute font so callers can update the run's ``rFonts``.
    """
    mapping_info = _get_mapping(font)
    if mapping_info is None:
        # Fall back to the union when the codepoints themselves look like
        # Wingdings/Symbol PUA. This handles the case where an upstream
        # edge case blanks ``span.font`` before emit time.
        if not any(ch in _FALLBACK for ch in text):
            return text, font, False
        mapping, substitute = _FALLBACK, "Arial"
    else:
        mapping, substitute = mapping_info
    out = []
    changed = False
    for ch in text:
        if ch in mapping:
            out.append(mapping[ch])
            changed = True
        else:
            out.append(ch)
    if not changed:
        return text, font, False
    return "".join(out), substitute, True


# ----------------------------------------------------------------------
# Monkey-patch TextSpan.make_docx so the replacement happens just before
# python-docx writes the run. We only swap text + font when the span
# carries a translatable codepoint; untouched spans go through upstream
# behaviour unchanged.
# ----------------------------------------------------------------------
_TextSpan = _ts.TextSpan
_orig_make_docx = _TextSpan.make_docx


def _patched_make_docx(self, paragraph):  # type: ignore[no-untyped-def]
    new_text, new_font, changed = translate(self.text, getattr(self, "font", ""))
    if not changed:
        return _orig_make_docx(self, paragraph)

    # Swap text + font for the duration of emit, then restore. Using
    # attribute save/restore keeps the span object unchanged for any
    # downstream consumers that inspect it after emit.
    orig_text = self._text
    orig_chars = self.chars
    orig_font = self.font
    try:
        self._text = new_text
        self.chars = []  # force text getter to use _text instead of per-char
        self.font = new_font
        return _orig_make_docx(self, paragraph)
    finally:
        self._text = orig_text
        self.chars = orig_chars
        self.font = orig_font


_TextSpan.make_docx = _patched_make_docx  # type: ignore[method-assign]
