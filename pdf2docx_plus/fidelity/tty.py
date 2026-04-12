"""Silence ANSI escape codes when stderr is not a TTY.

Upstream hard-codes `\\033[1;36m...\\033[0m` in log messages. When logs are
captured to a file or journal, those escapes are noise. We replace the
`_color_output` staticmethod with one that emits plain text in non-TTY
contexts.
"""

from __future__ import annotations

import sys

import pdf2docx.converter as _upstream


def _color_output(msg: str) -> str:
    if sys.stderr.isatty():
        return f"\033[1;36m{msg}\033[0m"
    return msg


_upstream.Converter._color_output = staticmethod(_color_output)  # type: ignore[method-assign]
