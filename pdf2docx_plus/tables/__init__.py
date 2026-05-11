"""Table post-processing.

* `stitch_cross_page_tables` merges continuation tables that span two or
  more pages.
* `demote_floating_images_in_cells` stops `ImageBlock`s that sit entirely
  inside a table cell from being promoted to the page-level blocks list
  (upstream #299).
* `recover_pathological_tables` re-extracts text blocks that upstream
  dropped when it incorrectly interpreted an outer page rectangle as a
  table.
"""

from __future__ import annotations

from .float_images import demote_floating_images_in_cells
from .recover_content import RecoveryReport, recover_pathological_tables
from .stitch import StitchReport, stitch_cross_page_tables

__all__ = [
    "RecoveryReport",
    "StitchReport",
    "demote_floating_images_in_cells",
    "recover_pathological_tables",
    "stitch_cross_page_tables",
]
