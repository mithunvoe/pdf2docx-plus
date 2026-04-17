"""Install pdf2docx-plus styles on every Document the upstream pipeline makes.

The upstream emitter does `docx_file = Document()` inside
`Converter.make_docx`, which produces a Document with only python-docx's
minimal built-in style set. We patch the `Document` constructor reference
inside `pdf2docx.converter` to return a Document with our full style
inventory installed.
"""

from __future__ import annotations

import pdf2docx_plus._vendored.pdf2docx.converter as _upstream

from ..styles import new_document


def _patched_document(*args, **kwargs):  # type: ignore[no-untyped-def]
    # The upstream call is `Document()` with no template path; we honour
    # any template the caller supplies but install our styles on top.
    if args or kwargs:
        from docx import Document as _Doc  # local to avoid cycles

        doc = _Doc(*args, **kwargs)
        from ..styles import install_styles

        install_styles(doc)
        return doc
    return new_document()


_upstream.Document = _patched_document  # type: ignore[attr-defined]
