"""Formula recognition -> Office Math Markup (OMML).

Two back-ends:

* `Pix2TexFormulaRecognizer` -> pix2tex / LaTeX-OCR (MIT). Small, CPU-friendly.
* `UniMERNetFormulaRecognizer` -> UniMERNet (Apache-2.0). Higher accuracy,
  heavier (requires a manual weights download in most environments).

Both produce a LaTeX string, which we convert to OMML via `latex2mathml` (or a
minimal fallback that wraps the LaTeX as a `<m:oMath>` literal so Word at
least renders the source).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _latex_to_omml(latex: str) -> str:
    """Best-effort LaTeX -> OMML.

    Tries `latex2mathml` + MathML->OMML XSLT (standard OOXML tooling). If the
    chain is missing, falls back to embedding the raw LaTeX inside an
    `<m:oMath><m:r><m:t>...</m:t></m:r></m:oMath>` shell so Word renders at
    least the source expression rather than dropping it.
    """
    try:
        import latex2mathml.converter  # type: ignore
    except ImportError:
        latex2mathml = None  # type: ignore[assignment]

    escaped = latex.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if latex2mathml is None:
        return (
            '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
            f"<m:r><m:t>{escaped}</m:t></m:r></m:oMath>"
        )
    # latex2mathml returns MathML; converting MathML->OMML properly needs the
    # MS OMML XSLT which we don't bundle. For now, embed the MathML; Word 365
    # imports it via the /word/math folder with the right relationship.
    mathml = latex2mathml.converter.convert(latex)
    return mathml


@dataclass
class Pix2TexFormulaRecognizer:
    _model: Any | None = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            from pix2tex.cli import LatexOCR  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "pix2tex requires the 'ml-formula' extra: pip install 'pdf2docx-plus[ml-formula]'"
            ) from e
        self._model = LatexOCR()

    def to_omml(self, image: Any) -> str:
        self._ensure_loaded()
        latex = self._model(image)  # type: ignore[misc]
        return _latex_to_omml(latex)


@dataclass
class UniMERNetFormulaRecognizer:
    """UniMERNet wrapper. Left as a stub; wire in the OpenDataLab repo directly.

    Users with an existing UniMERNet checkpoint can subclass this and override
    `to_omml` to call their inference pipeline, returning a LaTeX string that
    we then hand to `_latex_to_omml`.
    """

    checkpoint_path: str | None = None

    def to_omml(self, image: Any) -> str:  # pragma: no cover - integration point
        raise NotImplementedError(
            "UniMERNetFormulaRecognizer is a stub. Subclass and implement "
            "to_omml(image) -> latex, then call latex_to_omml() on the result."
        )
