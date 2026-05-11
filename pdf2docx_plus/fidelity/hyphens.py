"""Protect well-known hyphenated compounds from upstream de-hyphenation.

Upstream's ``pdf2docx.text.Lines.adjust_last_word`` deletes the trailing
``-`` of a line when the next line starts with a lowercase letter and
``delete_end_line_hyphen=True``.  That heuristic was designed for the
classic typesetting case (``"informa-"`` / ``"tion"`` -> ``"information"``)
but is unsafe for genuine hyphenated compounds like ``"Sub-Fund"`` /
``"fund"`` -> ``"SubFund"``.  Documents that have such compounds break
in surprising ways when the user passes ``delete_end_line_hyphen=True``
to the upstream settings.

We don't change upstream's default (still ``False``); we just patch the
function so that, if the user *does* set ``delete_end_line_hyphen=True``,
the deletion is skipped for known compounds.  The whitelist is shared
with ``emit/word_spacing.py`` so the two passes agree on what's a real
hyphen.
"""

from __future__ import annotations

import string
from typing import Any

import pdf2docx_plus._vendored.pdf2docx.text.Lines as _lines_mod
from pdf2docx_plus._vendored.pdf2docx.text.TextSpan import TextSpan

from ..emit.word_spacing import _HYPHEN_WHITELIST


def _patched_adjust_last_word(self, delete_end_line_hyphen: bool) -> None:  # type: ignore[no-untyped-def]
    """Drop-in replacement for ``Lines.adjust_last_word``.

    Identical semantics to upstream except a hyphen at end of line is
    only deleted when:

      * ``delete_end_line_hyphen=True`` (caller opt-in), AND
      * the next line starts with a lowercase letter (existing rule),
      * AND the joined token (left tail + right head) is not in the
        protected whitelist (``Sub-Fund``, ``non-listed``, ...).
    """
    punc_ex_hyphen = "".join(c for c in string.punctuation if c != "-")

    def is_end_of_english_word(c: str) -> bool:
        return bool(c.encode().isalnum()) or (bool(c) and c in punc_ex_hyphen)

    instances = list(self._instances)
    for i, line in enumerate(instances[:-1]):
        end_span = line.spans[-1] if line.spans else None
        if not isinstance(end_span, TextSpan):
            continue
        end_chars = end_span.chars
        if not end_chars:
            continue
        end_char = end_chars[-1]

        start_span = instances[i + 1].spans[0] if instances[i + 1].spans else None
        if not isinstance(start_span, TextSpan):
            continue
        start_chars = start_span.chars
        if not start_chars:
            continue
        next_start_char = start_chars[0]

        if (
            delete_end_line_hyphen
            and end_char.c.endswith("-")
            and next_start_char.c.islower()
        ):
            left_tail = _line_tail_word(line)
            right_head = _line_head_word(instances[i + 1])
            joined = (left_tail + right_head).lower()
            if joined not in _HYPHEN_WHITELIST and not (
                joined.endswith("s") and joined[:-1] in _HYPHEN_WHITELIST
            ):
                end_char.c = ""  # delete hyphen in a tricky way

        if is_end_of_english_word(end_char.c) and is_end_of_english_word(next_start_char.c):
            end_char.c += " "


def _line_tail_word(line: Any) -> str:
    """Return the trailing word of ``line``, including the closing ``-``."""
    text = "".join(getattr(span, "text", "") or "" for span in line.spans)
    word = text.rstrip().split()[-1] if text.strip() else ""
    return word


def _line_head_word(line: Any) -> str:
    text = "".join(getattr(span, "text", "") or "" for span in line.spans)
    word = text.lstrip().split()[0] if text.strip() else ""
    return word


_lines_mod.Lines.adjust_last_word = _patched_adjust_last_word  # type: ignore[method-assign]
