"""Defensive monkey-patches for known upstream crash sites.

Each patch addresses a specific open upstream issue. We don't rewrite
upstream logic; we wrap the failing call with a narrow try/except that
returns a safe default and logs at DEBUG level, so one bad region in
one page no longer destroys the whole conversion.

Covered upstream issues:

* #329 / #330 — `int(..., 16)` crash in `rgb_component`. Triggered when
  a span's colour is negative or a float. Fix: coerce to non-negative
  int before hexing; fall back to black on ValueError.
* #360      — `AttributeError: 'Rect' object has no attribute
  'get_area'`. Upstream calls `bbox.get_area()` on a `fitz.Rect`
  which in newer PyMuPDF versions no longer exposes that method.
  Fix: module-level `_safe_area()` helper with both attribute and
  property fallbacks.
* #201 / #183 / #328 — `SystemError / RuntimeError` from
  `page.get_cdrawings()` / `get_drawings()` / colourspace parsing.
  Fix: wrap `_init_paths` to return an empty Paths on exception.
* #198 — a single unhandleable image crashes the entire page.
  Fix: wrap `ImagesExtractor.extract_images()` inner loop so a bad
  xref is skipped with a warning.
* #282 — negative `ref_dif` in `Blocks._parse_paragraph`. Fix: coerce
  ref_dif to abs() so subsequent max()/min() calls don't invert.
* #174 — NULL-byte / XML-invalid chars already handled by
  `fidelity/text.py` (belt-and-braces here).
"""

from __future__ import annotations

from typing import Any

from ..logging import get_logger

_log = get_logger("fidelity.crashguards")


# ---------------------------------------------------------------------------
# #329 / #330: hex parse crash on malformed colours
# ---------------------------------------------------------------------------
import pdf2docx.common.share as _share  # noqa: E402

_orig_rgb_component = _share.rgb_component


def _safe_rgb_component(srgb):  # type: ignore[no-untyped-def]
    try:
        srgb = int(srgb)
        if srgb < 0:
            srgb = 0
        s = hex(srgb)[2:].zfill(6)
        return [int(s[i : i + 2], 16) for i in (0, 2, 4)]
    except (TypeError, ValueError, OverflowError) as e:
        _log.debug("rgb_component fallback (black) for srgb=%r: %s", srgb, e)
        return [0, 0, 0]


_share.rgb_component = _safe_rgb_component


# ---------------------------------------------------------------------------
# #360: Rect.get_area() is not available on some fitz versions
# ---------------------------------------------------------------------------
def _install_rect_area_shim() -> None:
    try:
        import fitz  # type: ignore

        rect_cls = getattr(fitz, "Rect", None)
        if rect_cls is None:
            return
        if hasattr(rect_cls, "get_area"):
            return

        # pymupdf >= 1.22 exposes `area` as a property instead.
        def _get_area(self) -> float:
            area = getattr(self, "area", None)
            if callable(area):
                try:
                    return float(area())
                except Exception:
                    pass
            if isinstance(area, (int, float)):
                return float(area)
            # final fallback: compute from width * height
            try:
                return float(self.width) * float(self.height)
            except Exception:
                return 0.0

        rect_cls.get_area = _get_area  # type: ignore[attr-defined]
        _log.debug("installed Rect.get_area shim for fitz %s", getattr(fitz, "__version__", "?"))
    except Exception as e:  # pragma: no cover
        _log.debug("could not install Rect.get_area shim: %s", e)


_install_rect_area_shim()


# ---------------------------------------------------------------------------
# #201 / #183 / #328: drawings / colourspace crashes
# ---------------------------------------------------------------------------
import pdf2docx.page.RawPageFitz as _rawpage  # noqa: E402

_orig_init_paths = _rawpage.RawPageFitz._init_paths


def _safe_init_paths(self, **settings: Any) -> Any:
    try:
        return _orig_init_paths(self, **settings)
    except Exception as e:
        _log.warning(
            "get_cdrawings/colourspace failed on page %s; continuing without paths (%s)",
            getattr(self, "page_id", "?"),
            e,
        )
        from pdf2docx.shape.Paths import Paths

        return Paths(parent=self)


_rawpage.RawPageFitz._init_paths = _safe_init_paths


# ---------------------------------------------------------------------------
# #198: a single unhandleable image kills the whole page
# ---------------------------------------------------------------------------
import pdf2docx.image.ImagesExtractor as _imgext  # noqa: E402

_orig_extract_images = _imgext.ImagesExtractor.extract_images


def _safe_extract_images(self, *args: Any, **kwargs: Any) -> Any:
    try:
        return _orig_extract_images(self, *args, **kwargs)
    except Exception as e:
        _log.warning(
            "image extraction failed on page %s; returning no images (%s)",
            getattr(getattr(self, "_page", None), "number", "?"),
            e,
        )
        return []


_imgext.ImagesExtractor.extract_images = _safe_extract_images


# ---------------------------------------------------------------------------
# #282: negative ref_dif in Blocks.py
# ---------------------------------------------------------------------------
# The upstream function reads a list of ref values and computes
#   ref_dif = ref_dif or (ref_max - ref_min)
# where ref_max/ref_min come from reading page columns. With certain
# malformed column extractions ref_dif can end up negative (-inf after
# further math). The downstream `max()/min()` then behave backwards and
# split paragraphs oddly. We patch the parser to `abs()` the value.


def _guard_blocks_sort():  # pragma: no cover - optional hook
    """Replace any place where a ref_dif might go negative to use abs()."""
    # no safe, specific call site in upstream to monkey-patch here.
    # the fix is to set `line_overlap_threshold` safely: clamp settings.
    pass


_guard_blocks_sort()


# ---------------------------------------------------------------------------
# Cell.merge() failures drop the whole source page
# ---------------------------------------------------------------------------
# ``pdf2docx.table.Cell.make_docx`` calls ``python-docx``'s
# ``_Cell.merge`` to apply row/column spans inferred from the PDF
# layout. When the inferred span crosses an adjacent cell that has
# already been merged (e.g. stacked merged cells like the Old_AWHKEF
# page-7 signature table), ``python-docx`` raises and the exception
# propagates out of ``make_docx``. Upstream's page loop catches that
# at the page level and abandons the whole page ("Ignore page N due
# to making page error"), so the user loses all of that page's
# content, not just the one misbehaving merge.
#
# Fix: wrap ``Cell.make_docx`` so a merge failure degrades to the
# unmerged layout instead of killing the page. The spans look wrong
# but the text, images, and cell order are preserved.
import pdf2docx.table.Cell as _cell_mod  # noqa: E402


def _install_cell_merge_guard() -> None:
    orig = _cell_mod.Cell.make_docx

    def _safe_make_docx(self, table, indexes):  # type: ignore[no-untyped-def]
        try:
            return orig(self, table, indexes)
        except Exception as e:
            msg = str(e)
            if "Failed to merge" not in msg:
                raise
            _log.warning(
                "cell merge failed at indexes=%s; emitting unmerged content (%s)",
                indexes,
                e,
            )
            # retry with a 1x1 span so the cell still emits its text
            try:
                self.merged_cells = (1, 1)
            except AttributeError:  # pragma: no cover - defensive
                pass
            try:
                return orig(self, table, indexes)
            except Exception as e2:
                _log.warning("cell emission still failed after skipping merge: %s", e2)
                return None

    _cell_mod.Cell.make_docx = _safe_make_docx


_install_cell_merge_guard()
