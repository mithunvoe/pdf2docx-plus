"""Bullet / numbered-list pattern detection.

Upstream `pdf2docx` emits list items as ordinary paragraphs with the marker
glyph ("•", "-", "1.", "a)") rendered inline as text. This loses:

* any `w:numPr` structure Word expects for editing,
* correct indent for continuation lines,
* the ability to renumber or restyle the list.

This module provides `detect_list_block(text)` to classify a TextBlock's
first-line marker and a `normalise_list_blocks()` pass that walks the
parsed blocks on a page and tags them with a synthetic attribute
`_pdf2docx_plus_list = ("bullet" | "decimal" | "lower_alpha" | ..., level)`
that the DOCX emitter can then translate to `w:numPr`.

We intentionally do NOT mutate upstream's class hierarchy — the tag is a
private attribute that only our fidelity patch in `fidelity/lists.py`
reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_BULLET_CHARS = set("•◦▪‣∙·●○◘◙■□")
_DECIMAL = re.compile(r"^\s*(\d+)[.\)]\s+")
_LOWER_ALPHA = re.compile(r"^\s*([a-z])[.\)]\s+")
_UPPER_ALPHA = re.compile(r"^\s*([A-Z])[.\)]\s+")
_LOWER_ROMAN = re.compile(r"^\s*(i{1,3}|iv|v|vi{1,3}|ix|x)[.\)]\s+", re.IGNORECASE)


@dataclass(frozen=True)
class ListMarker:
    kind: str  # "bullet" | "decimal" | "lower_alpha" | "upper_alpha" | "lower_roman"
    raw: str  # the matched marker token including trailing whitespace
    start_at: int | None = None


def detect_list_block(text: str) -> ListMarker | None:
    """Inspect the leading characters of a paragraph; return a ListMarker or None."""
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

    for pattern, kind in (
        (_DECIMAL, "decimal"),
        (_LOWER_ROMAN, "lower_roman"),
        (_LOWER_ALPHA, "lower_alpha"),
        (_UPPER_ALPHA, "upper_alpha"),
    ):
        m = pattern.match(text)
        if m:
            start = None
            if kind == "decimal":
                start = int(m.group(1))
            return ListMarker(kind=kind, raw=m.group(0), start_at=start)
    return None


def normalise_list_blocks(page: Any) -> int:
    """Walk a Page and tag text blocks that look like list items.

    Returns the number of blocks tagged. The tag is attached as
    `block._pdf2docx_plus_list`.
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
