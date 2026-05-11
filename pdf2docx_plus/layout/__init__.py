"""Post-parse layout enrichments.

These modules run *after* the upstream pipeline finishes parsing each page
but *before* DOCX emission, so they can reason about the full document at
once (e.g. which blocks repeat across pages → header/footer).
"""

from __future__ import annotations

from .hf_detect import detect_header_footer
from .lists import detect_list_block, normalise_list_blocks
from .margin_labels import MarginLabel, detect_margin_labels, drop_margin_labels
from .scanned import ScannedPageReport, detect_scanned_pages

__all__ = [
    "MarginLabel",
    "ScannedPageReport",
    "detect_header_footer",
    "detect_list_block",
    "detect_margin_labels",
    "detect_scanned_pages",
    "drop_margin_labels",
    "normalise_list_blocks",
]
