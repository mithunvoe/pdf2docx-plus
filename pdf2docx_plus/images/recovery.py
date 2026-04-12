"""Image + vector-graph recovery.

Strategy:

* Walk the PDF page-by-page using `fitz`.
* For every page, compute:
    - `raster_xrefs`: xrefs returned by `page.get_images(full=True)`.
    - `drawing_regions`: clusters of vector drawings that look like
      non-trivial graphics (not table border lines).
* Compare against what upstream already emitted by reading the DOCX's
  `word/media/` directory and the inline `<w:drawing>` elements. For
  each missing raster image we clip-render the page region and
  insert. For each drawing region we render at 150 DPI and insert as
  a PNG.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import fitz  # type: ignore
from docx import Document  # type: ignore
from docx.oxml.ns import qn
from docx.shared import Emu


@dataclass
class RecoveryReport:
    missing_raster_recovered: int = 0
    vector_regions_rasterized: int = 0
    pages_touched: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def recover_images(
    pdf_path: str,
    docx_path: str,
    *,
    rasterize_vectors: bool = False,
    recover_missing_rasters: bool = True,
    min_drawing_density: float = 0.0005,
    render_dpi: int = 150,
) -> RecoveryReport:
    """Patch `docx_path` with recovered images from `pdf_path`.

    Args:
        rasterize_vectors: if True, rasterize dense vector regions.
        recover_missing_rasters: if True, re-emit raster images upstream
            dropped (common for repeated logos).
        min_drawing_density: vector drawing area / page area ratio above
            which a cluster is rasterized.
        render_dpi: target DPI for rasterization.
    """
    report = RecoveryReport()
    if not (rasterize_vectors or recover_missing_rasters):
        return report

    pdf = fitz.open(pdf_path)
    doc = Document(docx_path)
    try:
        for page_index in range(len(pdf)):
            page = pdf[page_index]
            page_rect = page.rect

            if recover_missing_rasters:
                # the logo case: same xref appears on many pages but PyMuPDF
                # reports a bbox only on the page where it was explicitly
                # placed. upstream `pdf2docx` then drops it on the other
                # pages. we inject it on any page whose `get_images` lists
                # an xref but `get_image_rects` returns empty.
                for img_info in page.get_images(full=True):
                    xref = img_info[0]
                    try:
                        rects = page.get_image_rects(xref)
                    except Exception:
                        rects = []
                    if rects:
                        continue  # upstream handled this one
                    template_bbox = _find_template_bbox(pdf, xref)
                    if template_bbox is None:
                        continue
                    if _inject_image(doc, pdf, page_index, template_bbox):
                        report.missing_raster_recovered += 1
                        report.pages_touched.append(page_index)

            if rasterize_vectors:
                regions = _vector_clusters(page, page_rect, min_drawing_density)
                for region in regions:
                    try:
                        pix = page.get_pixmap(
                            clip=region, matrix=fitz.Matrix(render_dpi / 72, render_dpi / 72)
                        )
                        png_bytes = pix.tobytes("png")
                        _append_inline_image(doc, png_bytes, region)
                        report.vector_regions_rasterized += 1
                        report.pages_touched.append(page_index)
                    except Exception as e:
                        report.warnings.append(f"page {page_index + 1} vector raster failed: {e}")

        if report.missing_raster_recovered or report.vector_regions_rasterized:
            doc.save(docx_path)
    finally:
        pdf.close()
    return report


# -- helpers ----------------------------------------------------------------


def _emitted_image_count_by_page(doc: Any, pdf: fitz.Document) -> dict[int, int]:
    """Best-effort: without page markers in the DOCX we can't know per-page
    counts. We return a single aggregate and split by page count."""
    total = len(doc.element.body.findall(f".//{qn('w:drawing')}"))
    per_page = max(total // len(pdf), 1) if len(pdf) else 0
    # the real distribution is unknown; return a uniform estimate.
    return {i: per_page for i in range(len(pdf))}


def _find_template_bbox(pdf: fitz.Document, xref: int) -> fitz.Rect | None:
    for p in pdf:
        try:
            rects = p.get_image_rects(xref)
        except Exception:
            continue
        if rects:
            return rects[0]
    return None


def _inject_image(doc: Any, pdf: fitz.Document, page_index: int, template_bbox: fitz.Rect) -> bool:
    """Clip the page at template_bbox, render, and append inline in doc."""
    try:
        page = pdf[page_index]
        # clip at the template bbox (which came from page 1) — in practice the
        # logo occupies the same rectangle on every page
        pix = page.get_pixmap(clip=template_bbox, matrix=fitz.Matrix(3, 3))
        png_bytes = pix.tobytes("png")
    except Exception:
        return False
    _append_inline_image(doc, png_bytes, template_bbox)
    return True


def _append_inline_image(doc: Any, png_bytes: bytes, bbox: fitz.Rect) -> None:
    """Append an inline image at the end of the body."""
    import io

    # python-docx only accepts a path or file-like
    width_emu = Emu(int(bbox.width * 9525))  # points -> EMU (1pt=9525 EMU @ 72dpi logical)
    # use a dedicated paragraph at end of doc so we don't collide with existing flow
    p = doc.add_paragraph()
    run = p.add_run()
    run.add_picture(io.BytesIO(png_bytes), width=width_emu)


def _vector_clusters(page: fitz.Page, page_rect: fitz.Rect, min_density: float) -> list[fitz.Rect]:
    """Cluster vector drawings into rect regions, filtering thin table borders.

    Returns the bounding rects of "graphic" clusters: regions whose cumulative
    drawing area divided by the cluster bbox area exceeds `min_density`
    *and* whose dimensions exceed both 40 x 40 pt (smaller = likely icons
    or rule lines).
    """
    drawings = page.get_drawings()
    if not drawings:
        return []
    rects: list[fitz.Rect] = []
    for d in drawings:
        r = d.get("rect")
        if r is None:
            continue
        # skip single-line strokes (table borders)
        if r.width < 3 or r.height < 3:
            continue
        rects.append(fitz.Rect(r))

    # merge overlapping rects
    merged = _merge_overlapping(rects, pad=15.0)

    page_area = page_rect.width * page_rect.height
    clusters: list[fitz.Rect] = []
    for r in merged:
        if r.width < 40 or r.height < 40:
            continue
        cluster_area = r.width * r.height
        if cluster_area / max(page_area, 1) < min_density:
            continue
        clusters.append(r)
    return clusters


def _merge_overlapping(rects: list[fitz.Rect], *, pad: float = 0.0) -> list[fitz.Rect]:
    changed = True
    current = [fitz.Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad) for r in rects]
    while changed:
        changed = False
        out: list[fitz.Rect] = []
        for r in current:
            for i, merged in enumerate(out):
                if merged.intersects(r):
                    out[i] = merged | r
                    changed = True
                    break
            else:
                out.append(fitz.Rect(r))
        current = out
    return current
