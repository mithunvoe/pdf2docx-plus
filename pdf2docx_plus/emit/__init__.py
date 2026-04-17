"""Post-emit DOCX transformations.

These passes walk the python-docx `Document` after the upstream emitter
has finished, and rewrite it to expose the semantics the layout-analysis
modules have discovered. We do this post-hoc (rather than patching the
upstream emitter per-block) so our code has a single, stable target
surface: the python-docx XML tree.

Passes:

* `apply_lists(doc)` - convert paragraphs whose first characters match a
  bullet/numbered marker into `List Paragraph` style with a `w:numPr`
  reference.
* `extract_headers_footers(doc, detected)` - move paragraphs matching the
  detected header/footer text into the section's `w:hdr` / `w:ftr` parts
  and remove them from the body.
"""

from __future__ import annotations

from .headers_footers import extract_headers_footers
from .lists import apply_lists
from .page_breaks import insert_page_breaks
from .page_footer import promote_page_numbers_to_footer
from .sections import (
    clamp_paragraph_spacing,
    collapse_empty_sections,
    fix_page_margins,
    flatten_per_page_sections,
    normalize_multi_column_sections,
)
from .table_fit import align_tblgrid_to_cells, fit_oversized_tables
from .tables_cleanup import (
    drop_empty_tables,
    merge_consecutive_single_row_tables,
    trim_empty_table_rows,
    unwrap_tiny_tables,
)
from .whitespace import collapse_empty_paragraphs
from .word_spacing import repair_wrap_spacing

__all__ = [
    "align_tblgrid_to_cells",
    "apply_lists",
    "clamp_paragraph_spacing",
    "collapse_empty_paragraphs",
    "collapse_empty_sections",
    "drop_empty_tables",
    "extract_headers_footers",
    "fit_oversized_tables",
    "fix_page_margins",
    "flatten_per_page_sections",
    "insert_page_breaks",
    "merge_consecutive_single_row_tables",
    "normalize_multi_column_sections",
    "promote_page_numbers_to_footer",
    "repair_wrap_spacing",
    "trim_empty_table_rows",
    "unwrap_tiny_tables",
]
