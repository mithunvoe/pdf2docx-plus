"""Bullet / numbered-list pattern detection.

Upstream `pdf2docx` emits list items as ordinary paragraphs with the marker
glyph ("•", "-", "1.", "a)") rendered inline as text. This loses:

* any `w:numPr` structure Word expects for editing,
* correct indent for continuation lines,
* the ability to renumber or restyle the list.

This module provides `detect_list_block(text)` to classify a TextBlock's
first-line marker and a `normalise_list_blocks()` pass that walks the
parsed blocks on a page and tags them with a synthetic attribute
`_pdf2docx_plus_list = ListMarker(kind=..., raw=..., start_at=...)`
that the DOCX emitter can then translate to `w:numPr`.

We intentionally do NOT mutate upstream's class hierarchy — the tag is a
private attribute that only our fidelity patch in `emit/lists.py`
reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# bullet glyphs commonly used in PDFs - kept conservative; if a
# character is ambiguous (e.g. a hyphen) we require contextual signal
# to treat it as a bullet.
_BULLET_CHARS = set("•◦▪‣∙·●○◘◙■□◆▶▷▸▹")
# A separator after the number/letter marker.  Upstream sometimes emits
# the marker and the body in the *same* run with a single space, but
# also sometimes with a tab.  We accept both, and tolerate zero
# trailing whitespace when the marker is followed by an opening
# quote / left paren / em-dash (common in indices).
_NUM_SEP = r"(?:[ \t]+|(?=[“‘(—–]))"

_DECIMAL = re.compile(rf"^\s*(\d+)[.\)]{_NUM_SEP}")
# Multi-level "1.1.", "1.1.1" etc - treat as decimal but capture level
_MULTILEVEL = re.compile(rf"^\s*(\d+(?:\.\d+){{1,3}})\.?{_NUM_SEP}")
# (1), [1] paren-style markers
_PAREN_DECIMAL = re.compile(rf"^\s*[(\[](\d+)[)\]]{_NUM_SEP}")
_LOWER_ALPHA = re.compile(rf"^\s*([a-z])[.\)]{_NUM_SEP}")
_UPPER_ALPHA = re.compile(rf"^\s*([A-Z])[.\)]{_NUM_SEP}")
# Roman numerals up to xx; case-insensitive but mapped to lowercase kind
_LOWER_ROMAN = re.compile(
    rf"^\s*(i{{1,3}}|iv|v|vi{{1,3}}|ix|x|xi{{1,3}}|xiv|xv|xvi{{1,3}}|xix|xx)[.\)]{_NUM_SEP}",
    re.IGNORECASE,
)
_PAREN_ALPHA = re.compile(rf"^\s*[(\[]([a-zA-Z])[)\]]{_NUM_SEP}")
_PAREN_ROMAN = re.compile(
    rf"^\s*[(\[](i{{1,3}}|iv|v|vi{{1,3}}|ix|x)[)\]]{_NUM_SEP}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ListMarker:
    """Classification of the leading marker of a paragraph.

    ``kind`` is one of:
        bullet | decimal | lower_alpha | upper_alpha | lower_roman.
    ``raw`` is the matched marker token *including* trailing whitespace,
    so the emitter can strip it cleanly.  ``start_at`` is the numeric
    starting point for ordered lists (when known).
    ``level`` is 0 for top-level lists; for ``1.1`` style multi-level
    lists this captures the implicit nesting depth (0-indexed).
    """

    kind: str
    raw: str
    start_at: int | None = None
    level: int = 0


def detect_list_block(text: str) -> ListMarker | None:
    """Inspect the leading characters of a paragraph; return a ``ListMarker`` or None.

    The regexes are tried longest-first so multi-level "1.1.1." beats
    plain "1." and paren-style "(1)" beats unparenthesised "1".

    Reject very short paragraphs that consist of only the marker (e.g.
    a bare "1." paragraph): those are almost always a numbered legend
    item or a stray digit; treating them as a list creates a one-item
    list with no body which Word renders poorly.
    """
    if not text:
        return None
    stripped = text.lstrip()
    if not stripped:
        return None

    first = stripped[0]
    if first in _BULLET_CHARS:
        # include leading whitespace, the bullet glyph, and any whitespace after it
        lead = len(text) - len(stripped)
        rest = stripped[1:]
        after = len(rest) - len(rest.lstrip())
        return ListMarker(kind="bullet", raw=text[: lead + 1 + after])

    # multi-level decimals (must be tried first so "1.1." doesn't match "1.")
    m = _MULTILEVEL.match(text)
    if m:
        depth = m.group(1).count(".")
        head = int(m.group(1).split(".")[0])
        return ListMarker(kind="decimal", raw=m.group(0), start_at=head, level=depth)

    for pattern, kind in (
        (_PAREN_DECIMAL, "decimal"),
        (_DECIMAL, "decimal"),
        (_PAREN_ROMAN, "lower_roman"),
        (_LOWER_ROMAN, "lower_roman"),
        (_PAREN_ALPHA, "lower_alpha"),
        (_LOWER_ALPHA, "lower_alpha"),
        (_UPPER_ALPHA, "upper_alpha"),
    ):
        m = pattern.match(text)
        if m:
            start: int | None = None
            value = m.group(1)
            if kind == "decimal":
                try:
                    start = int(value)
                except ValueError:
                    start = None
            # Reject when the entire stripped text equals the marker
            # token (a bare "1." with no body).  We add a 2-char
            # threshold for the body to avoid promoting bullets that
            # carry only a footnote glyph.
            after = text[m.end():].strip()
            if len(after) < 2:
                continue
            if kind == "lower_alpha" and value.lower() != value:
                # _LOWER_ALPHA can match if the regex was relaxed; sanity check
                continue
            if kind == "upper_alpha" and value.upper() != value:
                continue
            return ListMarker(kind=kind, raw=m.group(0), start_at=start)
    return None


def normalise_list_blocks(page: Any) -> int:
    """Walk a Page and tag text blocks that look like list items.

    Tagging is best-effort - the post-emit ``apply_lists`` pass also
    re-runs the detection on the saved DOCX, which is the actual
    source of truth.  We keep this pass alive so ``ConversionResult``
    can report how many list candidates the parser saw.

    Returns the number of blocks tagged.
    """
    tagged = 0
    for section in getattr(page, "sections", []) or []:
        for column in section:
            blocks = getattr(column, "blocks", None)
            if blocks is None:
                continue
            for block in blocks:
                if not hasattr(block, "lines"):
                    continue
                first_text = _first_line_text(block)
                marker = detect_list_block(first_text)
                if marker is None:
                    continue
                block._pdf2docx_plus_list = marker  # type: ignore[attr-defined]
                tagged += 1
    return tagged


def _first_line_text(block: Any) -> str:
    lines = getattr(block, "lines", None)
    if lines is None:
        return ""
    first_line = next(iter(lines), None)
    if first_line is None:
        return ""
    return "".join(getattr(s, "text", "") or "" for s in getattr(first_line, "spans", []) or [])
