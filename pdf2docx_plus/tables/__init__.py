"""Table post-processing.

* `stitch_cross_page_tables` merges continuation tables that span two or
  more pages.
* `demote_floating_images_in_cells` stops `ImageBlock`s that sit entirely
  inside a table cell from being promoted to the page-level blocks list
  (upstream #299).
"""

from __future__ import annotations

from .float_images import demote_floating_images_in_cells
from .stitch import StitchReport, stitch_cross_page_tables

__all__ = [
    "StitchReport",
    "demote_floating_images_in_cells",
    "stitch_cross_page_tables",
]
