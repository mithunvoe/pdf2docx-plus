"""Optional ML-backed plugins.

Each module lazily imports its heavy dependency inside the class constructor,
so simply importing `pdf2docx_plus.hooks` does NOT require torch / paddle /
transformers. Users opt in by installing the appropriate extra:

    pip install "pdf2docx-plus[ml-tables]"   # Table Transformer
    pip install "pdf2docx-plus[ml-layout]"   # DocLayNet / Granite-Docling
    pip install "pdf2docx-plus[ml-formula]"  # pix2tex / UniMERNet
    pip install "pdf2docx-plus[ml-ocr]"      # PaddleOCR

All four hooks are wired by returning an object implementing the matching
Protocol in `pdf2docx_plus.plugins.base`.
"""

from __future__ import annotations

from .formula_ocr import Pix2TexFormulaRecognizer, UniMERNetFormulaRecognizer
from .layout_detection import GraniteDoclingLayoutDetector
from .ocr import PaddleOcrEngine
from .table_transformer import TableTransformerDetector

__all__ = [
    "GraniteDoclingLayoutDetector",
    "PaddleOcrEngine",
    "Pix2TexFormulaRecognizer",
    "TableTransformerDetector",
    "UniMERNetFormulaRecognizer",
]
