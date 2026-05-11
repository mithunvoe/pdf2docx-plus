"""Reject pathological lattice tables before they consume text blocks.

Some PDFs (regulatory / fund / prospectus templates - KFS, EM
documents) draw a single outer rectangle around the entire page
content.  Upstream's lattice-table detector groups that rectangle's
strokes into a "table" whose cells span huge vertical ranges and
contain only narrow margin strips.  Once
``Blocks.assign_to_tables`` runs, every text block on the page is
assigned to that bogus table; blocks that don't fit any cell with
``FACTOR_MAJOR`` containment are silently dropped.  Result: whole
sections of body content vanish from the DOCX output.

The fix here is structural: patch
``TablesConstructor.lattice_tables`` so the bogus table is filtered
*before* the block / shape assignment step.  We keep upstream's
behaviour for every legitimate lattice table; the only change is
rejecting tables whose geometry indicates upstream misread the
outer page border as a table.

Detection criteria (all required):

* the candidate table covers > ``area_threshold`` (default 70%) of
  the parent layout's bbox,
* the candidate has <= ``max_rows`` rows (default 6),
* within at least one row the tallest cell is >=
  ``cell_height_ratio`` (default 4x) of the shortest cell.

The first two conditions filter out genuine page-sized forms with
many uniformly-tall rows.  The third condition is the smoking gun: a
real table has uniform row heights, whereas the "outer-rectangle
mistaken for table" case produces a row whose interior cells are
small (the real content row at the top) but whose left/right margin
cells are huge (spanning the entire vertical range of the row).
"""

from __future__ import annotations

from typing import Any

import pdf2docx_plus._vendored.pdf2docx.table.TablesConstructor as _tc

from ..logging import get_logger

_log = get_logger("fidelity.pathological_tables")


def _is_pathological(
    table: Any,
    parent_bbox: Any,
    *,
    area_threshold: float = 0.70,
    max_rows: int = 6,
    cell_height_ratio: float = 4.0,
) -> bool:
    """Return True when ``table`` looks like a bogus mega-table."""
    try:
        px0, py0, px1, py1 = (float(parent_bbox[i]) for i in range(4))
    except (TypeError, ValueError, IndexError):
        return False
    parent_area = max((px1 - px0) * (py1 - py0), 1.0)

    bbox = getattr(table, "bbox", None)
    if bbox is None:
        return False
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return False
    table_area = max((x1 - x0) * (y1 - y0), 1.0)
    if table_area / parent_area < area_threshold:
        return False

    rows = getattr(table, "_rows", None)
    if rows is None:
        return False
    row_list = list(rows)
    if not row_list or len(row_list) > max_rows:
        return False

    for row in row_list:
        cells = [c for c in row if c is not None and getattr(c, "bbox", None) is not None]
        heights: list[float] = []
        for c in cells:
            cb = c.bbox
            try:
                heights.append(float(cb[3]) - float(cb[1]))
            except (TypeError, ValueError):
                continue
        if len(heights) < 2:
            continue
        nonzero = [h for h in heights if h > 0]
        if not nonzero:
            continue
        tallest = max(heights)
        shortest = min(nonzero)
        if shortest > 0 and tallest / shortest >= cell_height_ratio:
            return True
    return False


_orig_lattice_tables = _tc.TablesConstructor.lattice_tables


def _patched_lattice_tables(self, *args, **kwargs):  # type: ignore[no-untyped-def]
    """Wrap upstream so we can drop pathological tables after they are
    detected but before they steal text blocks from the page."""
    # We need to know what tables get appended. Run the original logic
    # but intercept at the point where it would assign blocks. The
    # simplest reliable hook is to override ``Blocks.assign_to_tables``
    # transiently so it filters the input.
    parent_bbox = getattr(self._parent, "bbox", None)
    if parent_bbox is None:
        return _orig_lattice_tables(self, *args, **kwargs)

    blocks_collection = self._blocks
    shapes_collection = self._shapes
    orig_blocks_assign = blocks_collection.assign_to_tables
    orig_shapes_assign = shapes_collection.assign_to_tables

    rejected: list[Any] = []

    def _filter(tables: list) -> list:
        kept: list = []
        for t in tables:
            if _is_pathological(t, parent_bbox):
                rejected.append(t)
                _log.debug(
                    "rejecting pathological lattice table bbox=%s rows=%d (parent=%s)",
                    getattr(t, "bbox", None),
                    len(getattr(t, "_rows", []) or []),
                    parent_bbox,
                )
                continue
            kept.append(t)
        return kept

    def _blocks_assign_filtered(tables: list):
        return orig_blocks_assign(_filter(tables))

    def _shapes_assign_filtered(tables: list):
        # Use the SAME filtered list; rejected has already been
        # populated by the blocks call. We refilter to be safe.
        filtered: list = [t for t in tables if not any(t is r for r in rejected)]
        return orig_shapes_assign(filtered)

    blocks_collection.assign_to_tables = _blocks_assign_filtered  # type: ignore[assignment]
    shapes_collection.assign_to_tables = _shapes_assign_filtered  # type: ignore[assignment]
    try:
        result = _orig_lattice_tables(self, *args, **kwargs)
    finally:
        blocks_collection.assign_to_tables = orig_blocks_assign  # type: ignore[assignment]
        shapes_collection.assign_to_tables = orig_shapes_assign  # type: ignore[assignment]

    # If we rejected pathological tables, fall back to stream-table
    # detection so the inner borderless tables on the same page still
    # get recovered. Without this fallback the page would render the
    # cells as bare paragraphs and the user would see the table
    # content but no table structure.
    if rejected:
        _retry_stream_tables(self)
    return result


def _retry_stream_tables(constructor: Any) -> None:
    """Attempt to detect stream tables on the parent layout after a
    pathological lattice rejection.

    Uses upstream's defaults for the three stream parameters that
    ``TablesConstructor.stream_tables`` expects.  If stream detection
    raises, we silently abandon - the text blocks remain in the body
    so at minimum no content is lost.
    """
    try:
        # Upstream defaults for stream-table parameters (see
        # converter.default_settings).
        min_border_clearance = 0.0
        max_border_width = 6.0
        line_separate_threshold = 5.0
        constructor.stream_tables(
            min_border_clearance,
            max_border_width,
            line_separate_threshold,
        )
    except Exception as e:
        _log.debug("stream-table fallback after pathological rejection failed: %s", e)


_tc.TablesConstructor.lattice_tables = _patched_lattice_tables  # type: ignore[assignment]
