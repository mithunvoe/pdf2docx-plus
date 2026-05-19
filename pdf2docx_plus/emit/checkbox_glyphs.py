"""Canonicalise cross-font empty-checkbox glyph variants.

Issue P-1 from PDF_FIDELITY_PDF2DOCX_PLAN.md.

Different Symbol-mapped fonts in a single PDF can render the same
visual "empty checkbox" with different Unicode codepoints — e.g.
``U+2610`` (BALLOT BOX), ``U+25A1`` (WHITE SQUARE), ``U+25FB`` (WHITE
MEDIUM SQUARE), or ``U+25A3`` (WHITE SQUARE CONTAINING BLACK SMALL
SQUARE — visually rendered as an empty box with a dot in some
typefaces).  When the same form is rendered with a slightly different
Symbol-mapped subset on the OLD vs NEW PDF, the diff tool sees
character-level differences for what the user intended as a uniform
"empty checkbox".

This pass walks every ``<w:t>`` element in the body, headers, and
footers and rewrites all empty-checkbox variants to a single canonical
codepoint (``U+25A1`` WHITE SQUARE, rendered as ``□`` in most fonts).

Critically, this pass does NOT collapse:

* ``U+2611`` BALLOT BOX WITH CHECK (``☑``),
* ``U+2612`` BALLOT BOX WITH X (``☒``),
* ``U+25A0`` BLACK SQUARE / filled box,

into the empty form, because those carry distinct semantic content
(the box is checked / crossed / filled).  Only purely-empty variants
collapse.
"""

from __future__ import annotations

from typing import Any

from docx.oxml.ns import qn


CANONICAL_EMPTY_CHECKBOX = "□"  # WHITE SQUARE — most-portable rendering.

# Visually-empty checkbox variants that should normalise to the canonical
# form.  Variants that carry a tick / cross / fill (U+2611, U+2612, U+25A0,
# etc.) are deliberately NOT included — they encode user intent.
EMPTY_CHECKBOX_VARIANTS: tuple[str, ...] = (
    "☐",   # BALLOT BOX
    "◻",   # WHITE MEDIUM SQUARE
    "◽",   # WHITE MEDIUM SMALL SQUARE
    "▣",   # WHITE SQUARE CONTAINING BLACK SMALL SQUARE — rendered as
                # a slightly-decorated empty box in many fonts used by fund
                # documents; canonicalise for diff stability.
    "▫",   # WHITE SMALL SQUARE
    "❍",   # SHADOWED WHITE CIRCLE — rare, but appears in some
                # Symbol-font subsets as an alternate empty-checkbox glyph.
)

_TRANSLATION = {ord(c): CANONICAL_EMPTY_CHECKBOX for c in EMPTY_CHECKBOX_VARIANTS}


def canonicalise_checkbox_glyphs(document: Any) -> int:
    """Rewrite empty-checkbox variants to the canonical ``□``.

    Returns the number of ``<w:t>`` elements whose text was modified.
    """
    changed = 0
    targets = _iter_text_containers(document)
    for tree in targets:
        for t in tree.iter(qn("w:t")):
            original = t.text or ""
            if not original:
                continue
            new = original.translate(_TRANSLATION)
            if new != original:
                t.text = new
                changed += 1
    return changed


def _iter_text_containers(document: Any) -> list[Any]:
    """Yield every XML root that may carry ``<w:t>`` content.

    Body, plus every header / footer part of every section.
    """
    out: list[Any] = [document.element.body]
    for section in document.sections:
        for collection in (section.header, section.footer):
            try:
                part = collection.part
            except Exception:
                continue
            try:
                out.append(part.element)
            except Exception:
                continue
    return out
