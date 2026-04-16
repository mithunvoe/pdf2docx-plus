"""Repair word-glue where adjacent runs concatenate without whitespace.

Upstream ``pdf2docx`` rebuilds paragraph text by concatenating the
``TextSpan`` objects that the layout analyser found on each PDF line.
When a sentence wraps across lines in the source PDF, the trailing
space of the preceding line is represented by the line-break itself,
not by a space character inside the span.  Upstream's emitter drops
the line break and emits the two spans as adjacent ``<w:r>`` runs,
producing outputs like ``"confirms,having"`` and ``"Sub-Fund.The"``
where the source clearly read ``"confirms, having"`` and
``"Sub-Fund. The"``.

The post-emit pass here scans every paragraph, looks at adjacent
``<w:r>`` siblings, and inserts a single space between them when the
left run ends with a punctuation character that forces a word break
in the source (comma, semicolon, colon, question mark, exclamation,
closing paren) or with a word-ending period, and the right run
starts with a letter.  Single-letter initials (``U.S.``, ``e.g.``)
and mid-word hyphens are left untouched.
"""

from __future__ import annotations

import re
from typing import Any

from docx.oxml.ns import qn  # type: ignore

# punctuation that unambiguously closes a word when followed by a letter
_HARD_BREAK = frozenset(",;:?!)")

# left-context regex for a word-ending period: at least two lowercase
# letters before the period, or a lowercase-then-capital pattern such
# as ``"Sub-Fund."``.  This excludes single-letter initials (``U.``,
# ``S.``) and common single-letter abbreviations while still covering
# ``"e.g."``, ``"i.e."`` and genuine sentence endings.
_WORD_END_PERIOD = re.compile(r"[a-z]{2}\.$|[a-z][A-Z][a-z]+\.$|[a-z]-[A-Za-z]+\.$")

# right-context: any run starting with a letter is a candidate; the
# left-context test below guarantees we do not break initials.
_RIGHT_STARTS_LETTER = re.compile(r"^[A-Za-z]")


def repair_wrap_spacing(document: Any) -> int:
    """Insert missing spaces between adjacent runs that were joined
    across a PDF soft line break.

    Returns the number of insertions performed.
    """
    fixed = 0
    for paragraph in document.paragraphs:
        fixed += _repair_paragraph(paragraph._p)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    fixed += _repair_paragraph(paragraph._p)
    return fixed


def _repair_paragraph(p_elem: Any) -> int:
    runs = p_elem.findall(qn("w:r"))
    if len(runs) < 2:
        return 0
    fixed = 0
    for i in range(len(runs) - 1):
        a, b = runs[i], runs[i + 1]
        if a.getnext() is not b:
            # something between the two runs (hyperlink, bookmark, br)
            continue
        if _contains_line_break(a) or _contains_line_break(b):
            continue
        left_text = _last_t_text(a)
        right_text = _first_t_text(b)
        if not left_text or not right_text:
            continue
        if left_text.endswith(" ") or right_text.startswith(" "):
            continue
        if not _RIGHT_STARTS_LETTER.match(right_text):
            continue
        last_char = left_text[-1]
        if last_char in _HARD_BREAK:
            _append_space_to_last_t(a)
            fixed += 1
            continue
        if last_char == "." and _WORD_END_PERIOD.search(left_text):
            _append_space_to_last_t(a)
            fixed += 1
            continue
    return fixed


def _contains_line_break(run: Any) -> bool:
    return run.find(qn("w:br")) is not None or run.find(qn("w:tab")) is not None


def _last_t_text(run: Any) -> str:
    ts = run.findall(qn("w:t"))
    if not ts:
        return ""
    t = ts[-1]
    return t.text or ""


def _first_t_text(run: Any) -> str:
    ts = run.findall(qn("w:t"))
    if not ts:
        return ""
    t = ts[0]
    return t.text or ""


def _append_space_to_last_t(run: Any) -> None:
    ts = run.findall(qn("w:t"))
    if not ts:
        return
    t = ts[-1]
    t.text = (t.text or "") + " "
    t.set(qn("xml:space"), "preserve")
