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

__all__ = ["apply_lists", "extract_headers_footers"]
