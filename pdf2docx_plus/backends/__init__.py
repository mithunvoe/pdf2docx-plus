"""Pluggable PDF parse backend.

This is the seam that unblocks the pypdfium2 / MIT-licensed migration
(ROADMAP M8). The upstream `pdf2docx` pipeline is hard-wired to
PyMuPDF (AGPL); every call site that reaches `fitz.*` would need to be
ported to the new backend. The migration is a 3-4 week focused rewrite
(see `LICENSING.md`), and this file defines the interface the port has
to satisfy.

The default backend (`FitzBackend`) wraps PyMuPDF so all existing code
keeps working unchanged. Alternative backends (e.g. `PdfiumBackend`)
register by constructing the same `Backend` Protocol.

Usage:

    from pdf2docx_plus.backends import get_backend, register_backend

    backend = get_backend()  # default: fitz
    page_count = backend.page_count(pdf_bytes)

A caller can swap via env var:

    PDF2DOCX_BACKEND=pdfium pdf2docx-plus convert in.pdf out.docx
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

from ..errors import ConversionError


@runtime_checkable
class Backend(Protocol):
    """Minimal PDF-parse surface pdf2docx-plus needs.

    A complete port has to support every method on this Protocol. The
    default `FitzBackend` is canonical — mirror its behaviour on the new
    engine (return types, coordinate system = points with origin top-left,
    etc.).
    """

    name: str

    def open(self, *, path: str | None = None, stream: bytes | None = None) -> Any:
        """Open a PDF. Returns an opaque document handle."""
        ...

    def close(self, doc: Any) -> None: ...

    def page_count(self, doc: Any) -> int: ...

    def page_rect(self, doc: Any, index: int) -> tuple[float, float, float, float]:
        """Return (x0, y0, x1, y1) in points, top-left origin."""
        ...

    def page_rotation(self, doc: Any, index: int) -> int:
        """Return 0 / 90 / 180 / 270."""
        ...

    def extract_raw_dict(self, doc: Any, index: int) -> dict[str, Any]:
        """Return the raw-dict format consumed by the pipeline."""
        ...

    def render_to_pixmap(self, doc: Any, index: int, *, zoom: float = 3.0) -> Any:
        """Render a page at `zoom * 72dpi` and return a pixmap-like object."""
        ...


class FitzBackend:
    """Default backend. Wraps PyMuPDF directly."""

    name = "fitz"

    def open(self, *, path: str | None = None, stream: bytes | None = None) -> Any:
        import fitz  # type: ignore

        if stream is not None:
            return fitz.Document(stream=stream)
        if path is not None:
            return fitz.Document(path)
        raise ConversionError("open() requires path or stream")

    def close(self, doc: Any) -> None:
        doc.close()

    def page_count(self, doc: Any) -> int:
        return len(doc)

    def page_rect(self, doc: Any, index: int) -> tuple[float, float, float, float]:
        r = doc[index].rect
        return (float(r.x0), float(r.y0), float(r.x1), float(r.y1))

    def page_rotation(self, doc: Any, index: int) -> int:
        return int(doc[index].rotation)

    def extract_raw_dict(self, doc: Any, index: int) -> dict[str, Any]:
        return doc[index].get_text("rawdict")

    def render_to_pixmap(self, doc: Any, index: int, *, zoom: float = 3.0) -> Any:
        import fitz  # type: ignore

        matrix = fitz.Matrix(zoom, zoom)
        return doc[index].get_pixmap(matrix=matrix)


_REGISTRY: dict[str, Backend] = {"fitz": FitzBackend()}


def register_backend(name: str, backend: Backend) -> None:
    """Register an alternative backend under `name`."""
    _REGISTRY[name] = backend


def get_backend(name: str | None = None) -> Backend:
    """Return the backend by name. Defaults to $PDF2DOCX_BACKEND or 'fitz'."""
    resolved = name or os.environ.get("PDF2DOCX_BACKEND", "fitz")
    if resolved not in _REGISTRY:
        raise ConversionError(f"Unknown backend {resolved!r}. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[resolved]


__all__ = ["Backend", "FitzBackend", "get_backend", "register_backend"]
