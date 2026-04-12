"""Image recovery & vector-graphic rasterization.

Two problems upstream `pdf2docx` doesn't solve:

1. **Lost per-page xobject images.** PyMuPDF's `get_image_rects()` only
   reports a bbox when the image is placed directly on the page. When
   the same image xobject is reused on many pages (a logo referenced
   through a form xobject), rects come back empty for pages 2..N and
   upstream silently drops the image on those pages. The user sees
   "a blank rectangle where the logo should be".

2. **Vector graphs are not rendered.** A PDF chart made of vector
   strokes (no raster image) has no `get_images()` entry at all.
   Upstream translates every path into table borders or drops them,
   so the graph disappears.

`recover_images(pdf_path, docx_path)` opens both and patches the DOCX
in place:

* For each page, it compares the raster images upstream emitted on
  that page to the ones `fitz` knows exist. Missing ones are rendered
  by clipping the source PDF page at the image bbox (or at a
  fallback position derived from page 1) and inserted inline at the
  page's content anchor.

* For each page, it rasterizes regions with a high vector-drawing
  density (minus the regions already emitted as tables, which are
  usually just ruled borders) and inserts them as inline PNGs.

Both passes are OPT-IN; the default `Converter.convert` keeps the
upstream behaviour so nobody's output changes unexpectedly. Enable
with `rasterize_vector_graphics=True` and/or
`recover_missing_images=True`.
"""

from __future__ import annotations

from .recovery import RecoveryReport, recover_images

__all__ = ["RecoveryReport", "recover_images"]
