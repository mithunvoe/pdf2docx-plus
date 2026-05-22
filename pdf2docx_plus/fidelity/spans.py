"""Preserve word-separator spaces that upstream drops at span restore.

PyMuPDF's ``rawdict`` extraction sometimes splits a single visual line
into several spans where a run of whitespace becomes its own span -
e.g. the heading ``"A. Introduction"`` arrives as three spans
``["A.", " ", "Introduction"]`` and a label/value row arrives as
``["1.", " ", "Pursuant ..."]``.

Upstream ``pdf2docx.text.Spans.restore`` discards every span whose text
is whitespace-only and which carries no style::

    span = TextSpan(raw_span)
    if not span.text.strip() and not span.style:
        span = None

That rule is correct for *leading* and *trailing* whitespace spans -
they are redundant indentation that the layout engine reconstructs from
geometry.  But an **interior** whitespace span sitting between two spans
that do carry text is the genuine word separator.  Dropping it glues the
neighbours together, producing ``"A.Introduction"``, ``"1.Pursuant"``,
``"scheme.This"`` and similar word-glue in the emitted DOCX.

This patch keeps the upstream behaviour for boundary whitespace spans and
*only* preserves whitespace spans that are flanked by visible content on
both sides.  It never invents a space: a space is preserved only when it
already existed as a span in the source PDF, so the pass cannot introduce
spurious gaps inside ``"U.S."``, decimals, URLs, or run-on identifiers.

The kept space span carries a single ``" "`` char; downstream span
merging folds it into an adjacent same-format run with
``xml:space="preserve"``, so it renders as one ordinary word break.
"""

from __future__ import annotations

from typing import Any

import pdf2docx_plus._vendored.pdf2docx.text.Spans as _spans_mod
from pdf2docx_plus._vendored.pdf2docx.image.ImageSpan import ImageSpan
from pdf2docx_plus._vendored.pdf2docx.text.TextSpan import TextSpan


def _patched_restore(self: Any, raws: list) -> Any:
    """Drop-in replacement for ``Spans.restore``.

    Identical to upstream except a whitespace-only / style-less text span
    is preserved when it has visible content on both sides (an interior
    word separator) instead of being unconditionally removed.
    """
    # Build every span once, recording which carry visible content.
    # An "anchor" is any image span, or a text span with non-whitespace
    # text, or a styled text span - i.e. exactly the spans upstream would
    # never drop.
    built: list[tuple[Any, bool]] = []
    for raw_span in raws:
        if "image" in raw_span:
            built.append((ImageSpan(raw_span), True))
        else:
            span = TextSpan(raw_span)
            anchor = bool(span.text.strip()) or bool(span.style)
            built.append((span, anchor))

    anchor_positions = [i for i, (_, anchor) in enumerate(built) if anchor]
    first_anchor = anchor_positions[0] if anchor_positions else None
    last_anchor = anchor_positions[-1] if anchor_positions else None

    for i, (span, anchor) in enumerate(built):
        emit: Any = span
        if isinstance(span, TextSpan) and not anchor:
            # whitespace-only, style-less span: keep it only when it is a
            # genuine interior separator (visible content on both sides).
            interior = (
                first_anchor is not None
                and last_anchor is not None
                and first_anchor < i < last_anchor
            )
            if not interior:
                emit = None
        self.append(emit)
    return self


_spans_mod.Spans.restore = _patched_restore  # type: ignore[method-assign]
