"""Post-parse layout enrichments.

These modules run *after* the upstream pipeline finishes parsing each page
but *before* DOCX emission, so they can reason about the full document at
once (e.g. which blocks repeat across pages → header/footer).
"""

from __future__ import annotations

from .hf_detect import detect_header_footer
from .lists import detect_list_block, normalise_list_blocks
from .scanned import ScannedPageReport, detect_scanned_pages

__all__ = [
    "ScannedPageReport",
    "detect_header_footer",
    "detect_list_block",
    "detect_scanned_pages",
    "normalise_list_blocks",
]
