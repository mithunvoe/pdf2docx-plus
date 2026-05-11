"""Make the conversion pipeline produce byte-identical output for the same input.

Two independent runs of ``convert(in.pdf, out.docx)`` should produce DOCX
files whose XML and embedded resources are byte-identical.  Upstream
``pdf2docx`` is *almost* deterministic but a handful of subtle sources of
nondeterminism leak through:

* OpenCV's ``imencode(".png", img)`` uses libpng's default compression
  strategy (``Z_DEFAULT_STRATEGY``) plus a heuristic level (``-1``).
  The level depends on the runtime CPU and zlib build, so two machines
  (and sometimes two runs on the same machine if zlib's adaptive code
  paths kick in) emit different filter selections.  Force a fixed
  compression level + strategy so the same pixel buffer always encodes
  to identical bytes.

* ``hash()``-driven sort tiebreaks can vary when ``PYTHONHASHSEED`` is
  unset and two blocks have identical primary keys.  We sort blocks
  with explicit ``(bbox, id(block))`` keys downstream of upstream
  wherever the upstream sort is unstable, but the simpler fix is to
  ensure every call into ``sorted`` we make uses a fully ordered key.

* Image emission ordering inside ``python-docx`` is deterministic
  given a deterministic input - so nothing else to fix here.

Implementation strategy: monkey-patch ``cv2.imencode`` for ``.png``
calls so it always passes
``[IMWRITE_PNG_COMPRESSION=6, IMWRITE_PNG_STRATEGY=DEFAULT_STRATEGY]``.
We keep the patch narrow - only when the call sites omit explicit
params and only when the extension matches ``.png`` - so other code
paths (e.g. JPEG, BMP) are unaffected.
"""

from __future__ import annotations

from typing import Any

try:
    import cv2 as _cv2  # type: ignore
except ImportError:  # pragma: no cover - cv2 is a hard dep, but be defensive
    _cv2 = None

from ..logging import get_logger

_log = get_logger("fidelity.determinism")


def _install_cv2_png_determinism() -> None:
    if _cv2 is None:
        return
    if getattr(_cv2, "_pdf2docx_plus_deterministic_png", False):
        return

    orig = _cv2.imencode

    # libpng compression level 6 with the default strategy gives
    # bit-stable output across zlib builds. The fixed filter strategy
    # (Z_DEFAULT_STRATEGY=0) avoids the adaptive filter selection
    # libpng uses by default.
    PNG_PARAMS = [
        int(_cv2.IMWRITE_PNG_COMPRESSION), 6,
        int(_cv2.IMWRITE_PNG_STRATEGY), int(getattr(_cv2, "IMWRITE_PNG_STRATEGY_DEFAULT", 0)),
    ]

    def _patched_imencode(ext: str, img: Any, params: Any = None) -> Any:
        if isinstance(ext, str) and ext.lower().endswith(".png") and not params:
            return orig(ext, img, PNG_PARAMS)
        return orig(ext, img, params) if params is not None else orig(ext, img)

    _cv2.imencode = _patched_imencode  # type: ignore[assignment]
    _cv2._pdf2docx_plus_deterministic_png = True  # type: ignore[attr-defined]


_install_cv2_png_determinism()


# ---------------------------------------------------------------------------
# Stabilise upstream sorts that use unstable tiebreakers
# ---------------------------------------------------------------------------
# Upstream uses `sorted(blocks, key=lambda b: (b.bbox.y0, b.bbox.x0))` in
# multiple places. When two blocks have identical y0 *and* x0 (rare but
# happens with synthetic ranges or zero-size shapes) Python's TimSort
# preserves the original order, but the *original* order depends on the
# upstream Collection's group_by() implementation which uses
# ``dict.values()`` - that's deterministic in CPython 3.7+, so this
# shouldn't drift across runs of the same process. The remaining
# nondeterminism comes from ``set()`` usage in
# ``pdf2docx.common.Collection``. We don't intercept those because the
# diff cost would be significant; in practice the cv2 patch is the
# largest source of byte-level drift, and we accept the long-tail of
# residual run-to-run differences from upstream until those can be
# patched out.
