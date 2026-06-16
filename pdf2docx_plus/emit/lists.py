"""Convert marker-prefixed paragraphs into real OOXML numbered/bulleted lists.

Requires a `w:numbering` part in the DOCX. python-docx ships no API for
adding numbering definitions, so we build one by hand the first time a
list is emitted and cache the `numId` for each list kind.

For simplicity, one abstractNum per `ListMarker.kind`:

    bullet       -> abstractNumId=100, symbol "•"
    decimal      -> abstractNumId=101, "1.", "2.", "3.", ...
    lower_alpha  -> abstractNumId=102, "a.", "b.", ...
    upper_alpha  -> abstractNumId=103, "A.", "B.", ...
    lower_roman  -> abstractNumId=104, "i.", "ii.", ...

Each distinct `kind` gets one `numId` that reuses the same abstractNum.
Contiguous paragraphs with the same kind keep counting; a kind switch
starts a fresh numId so Word restarts numbering.
"""

from __future__ import annotations

from typing import Any

from docx.oxml import OxmlElement  # type: ignore
from docx.oxml.ns import nsmap, qn  # type: ignore

from ..layout.lists import ListMarker, detect_list_block

_ABSTRACT_NUM_IDS = {
    "bullet": 100,
    "decimal": 101,
    "lower_alpha": 102,
    "upper_alpha": 103,
    "lower_roman": 104,
}

_NUM_FMT = {
    "bullet": "bullet",
    "decimal": "decimal",
    "lower_alpha": "lowerLetter",
    "upper_alpha": "upperLetter",
    "lower_roman": "lowerRoman",
}

_LVL_TEXT = {
    "bullet": "\u2022",
    "decimal": "%1.",
    "lower_alpha": "%1.",
    "upper_alpha": "%1.",
    "lower_roman": "%1.",
}


def apply_lists(doc: Any) -> int:
    """Promote marker-prefixed paragraphs in ``doc`` to real lists.

    Heuristic (sharper than upstream's naive per-paragraph check):

    * Detect markers on every body paragraph in a single pass.
    * Group consecutive same-kind markers into runs.
    * For ``bullet``/``lower_alpha``/``upper_alpha``/``lower_roman``,
      require a run of length >= 2 before promoting - one-shot bullets
      look like data more often than they look like lists.
    * For ``decimal``, accept a single marker only when its value is 1
      AND the next non-list paragraph indents farther than the marker
      paragraph (likely a numbered heading), but otherwise require
      length >= 2.
    * The first paragraph in a run carries ``start_at`` so Word
      restarts numbering when the source switched lists mid-document.

    Returns the number of paragraphs converted.
    """
    numbering = _ensure_numbering_part(doc)

    # Walk EVERY body paragraph, including those trapped inside table
    # cells (Issue B2b).  Upstream over-promotes flowing prose / bullet
    # lists into single-column pseudo-tables, so list items frequently
    # live in ``<w:tc>`` rather than at body level; ``doc.paragraphs``
    # only sees body-level paragraphs and would leave those bullets
    # unnumbered.  We also track each paragraph's container element so a
    # run of markers never bleeds across a cell boundary (which would
    # otherwise chain numbering across unrelated cells).
    paragraphs, parents = _all_body_paragraphs(doc)
    markers: list[ListMarker | None] = [detect_list_block(p.text) for p in paragraphs]

    # Walk the markers and accept only when a run satisfies the
    # threshold for its kind.  Track decimal counters so non-consecutive
    # but sequential numbering is still promoted.
    accept: list[bool] = [False] * len(markers)
    i = 0
    while i < len(markers):
        m = markers[i]
        if m is None:
            i += 1
            continue
        # extend the run while subsequent paragraphs share kind AND the
        # same container (do not chain a list across cell boundaries)
        run_end = i + 1
        while run_end < len(markers):
            n = markers[run_end]
            if n is None or n.kind != m.kind or parents[run_end] is not parents[i]:
                break
            run_end += 1
        run_len = run_end - i
        if _accept_run(m.kind, run_len, markers[i:run_end]):
            for k in range(i, run_end):
                accept[k] = True
        i = run_end

    kind_to_num_id: dict[str, int] = {}
    converted = 0
    prev_kind: str | None = None
    prev_parent: Any = None
    for paragraph, parent, marker, ok in zip(
        paragraphs, parents, markers, accept, strict=False
    ):
        if not (marker and ok):
            prev_kind = None
            prev_parent = None
            continue
        num_id = kind_to_num_id.get(marker.kind)
        # restart numbering when the kind changes OR the container
        # changes (a new cell starts a fresh list)
        if num_id is None or marker.kind != prev_kind or parent is not prev_parent:
            num_id = _allocate_num_id(
                numbering, marker.kind, start_at=marker.start_at or 1
            )
            kind_to_num_id[marker.kind] = num_id
        _apply_list_formatting(paragraph, marker, num_id)
        converted += 1
        prev_kind = marker.kind
        prev_parent = parent
    return converted


def _all_body_paragraphs(doc: Any) -> tuple[list[Any], list[Any]]:
    """Return every body ``<w:p>`` as a python-docx ``Paragraph`` plus its
    immediate container element, in document order.

    Unlike ``doc.paragraphs`` (body-level only) this descends into table
    cells (and nested tables / SDTs) so list markers trapped in
    pseudo-tables are visible to ``apply_lists``.  The parallel
    ``parents`` list lets the caller avoid chaining a numbered list across
    container boundaries.
    """
    from docx.text.paragraph import Paragraph  # type: ignore

    paragraphs: list[Any] = []
    parents: list[Any] = []
    body = doc.element.body
    for p in body.iter(qn("w:p")):
        paragraphs.append(Paragraph(p, doc))
        parents.append(p.getparent())
    return paragraphs, parents


def _accept_run(kind: str, length: int, run: list[ListMarker | None]) -> bool:
    """Decide whether a run of consecutive same-kind markers should be
    promoted to a real list.

    Bullets and alpha/roman markers need a run of >= 2 to be a list.
    Decimals are stricter: require >= 2 paragraphs *and* the numbers
    have to be strictly increasing by 1 across the run (or start at 1
    and increase monotonically) so paragraph-leading dates or section
    numbers in tables aren't promoted.
    """
    if length < 1:
        return False
    if kind == "bullet":
        return length >= 2
    if kind in ("lower_alpha", "upper_alpha", "lower_roman"):
        return length >= 2
    if kind == "decimal":
        if length < 2:
            return False
        nums = [m.start_at for m in run if m is not None]
        # require monotonic-by-1 progression to filter out random
        # "1. Foo", "5. Bar" patterns that aren't real lists.
        from itertools import pairwise

        for a, b in pairwise(nums):
            if a is None or b is None:
                return False
            if b - a != 1:
                # tolerate occasional skips (1, 2, 4) if at least 3 of
                # the values are tight - upstream sometimes loses a
                # numbered paragraph to a page break
                if length >= 4 and 0 < b - a <= 2:
                    continue
                return False
        return True
    return False


# -- numbering part -------------------------------------------------------


def _ensure_numbering_part(doc: Any) -> Any:
    """Ensure /word/numbering.xml exists; return the numbering element."""
    part = doc.part
    try:
        numbering_part = part.numbering_part
    except (AttributeError, KeyError, Exception):
        numbering_part = None

    if numbering_part is None:
        # python-docx exposes numbering_part only if the template had one;
        # create a minimal one manually.
        numbering_part = _create_numbering_part(doc)
    return numbering_part.element


def _create_numbering_part(doc: Any) -> Any:
    from docx.opc.constants import CONTENT_TYPE, RELATIONSHIP_TYPE  # type: ignore
    from docx.oxml import parse_xml  # type: ignore
    from docx.parts.numbering import NumberingPart  # type: ignore

    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:numbering xmlns:w="{nsmap["w"]}"/>'
    )
    element = parse_xml(xml)
    partname = doc.part.package.next_partname("/word/numbering%d.xml")
    content_type = CONTENT_TYPE.WML_NUMBERING
    numbering_part = NumberingPart(partname, content_type, element, doc.part.package)
    doc.part.relate_to(numbering_part, RELATIONSHIP_TYPE.NUMBERING)
    return numbering_part


def _allocate_num_id(numbering: Any, kind: str, *, start_at: int = 1) -> int:
    """Append <w:abstractNum> + <w:num> definitions; return the numId."""
    abstract_id = _ensure_abstract_num(numbering, kind)
    # pick a new numId by walking existing <w:num> elements
    existing = numbering.findall(qn("w:num"))
    used = {int(n.get(qn("w:numId"))) for n in existing if n.get(qn("w:numId"))}
    num_id = 1
    while num_id in used:
        num_id += 1

    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    abs_ref = OxmlElement("w:abstractNumId")
    abs_ref.set(qn("w:val"), str(abstract_id))
    num.append(abs_ref)
    if start_at > 1:
        lvl_override = OxmlElement("w:lvlOverride")
        lvl_override.set(qn("w:ilvl"), "0")
        start_override = OxmlElement("w:startOverride")
        start_override.set(qn("w:val"), str(start_at))
        lvl_override.append(start_override)
        num.append(lvl_override)
    numbering.append(num)
    return num_id


def _ensure_abstract_num(numbering: Any, kind: str) -> int:
    target_id = _ABSTRACT_NUM_IDS[kind]
    for an in numbering.findall(qn("w:abstractNum")):
        if an.get(qn("w:abstractNumId")) == str(target_id):
            return target_id

    an = OxmlElement("w:abstractNum")
    an.set(qn("w:abstractNumId"), str(target_id))
    lvl = OxmlElement("w:lvl")
    lvl.set(qn("w:ilvl"), "0")
    for tag, val in (
        ("w:start", "1"),
        ("w:numFmt", _NUM_FMT[kind]),
        ("w:lvlText", _LVL_TEXT[kind]),
        ("w:lvlJc", "left"),
    ):
        el = OxmlElement(tag)
        el.set(qn("w:val"), val)
        lvl.append(el)
    # Indentation
    pPr = OxmlElement("w:pPr")
    ind = OxmlElement("w:ind")
    ind.set(qn("w:left"), "720")
    ind.set(qn("w:hanging"), "360")
    pPr.append(ind)
    lvl.append(pPr)
    an.append(lvl)
    # insert BEFORE any <w:num> nodes
    first_num = numbering.find(qn("w:num"))
    if first_num is not None:
        first_num.addprevious(an)
    else:
        numbering.append(an)
    return target_id


# -- paragraph transformation --------------------------------------------


def _apply_list_formatting(paragraph: Any, marker: ListMarker, num_id: int) -> None:
    # 1. strip the marker prefix from the paragraph text
    _strip_marker_prefix(paragraph, marker)
    # 2. attach List Paragraph style
    import contextlib

    with contextlib.suppress(KeyError, AttributeError):
        paragraph.style = paragraph.part.document.styles["List Paragraph"]
    # 3. set numPr
    pPr = paragraph._p.get_or_add_pPr()
    for existing in pPr.findall(qn("w:numPr")):
        pPr.remove(existing)
    numPr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    numPr.append(ilvl)
    n = OxmlElement("w:numId")
    n.set(qn("w:val"), str(num_id))
    numPr.append(n)
    pPr.append(numPr)


def _strip_marker_prefix(paragraph: Any, marker: ListMarker) -> None:
    """Remove the marker (e.g. '• ', '1. ') from the first run's text."""
    runs = paragraph.runs
    if not runs:
        return
    prefix = marker.raw
    remaining = prefix
    for run in runs:
        if not remaining:
            break
        text = run.text
        if not text:
            continue
        if text.startswith(remaining):
            run.text = text[len(remaining) :]
            return
        # the marker spans multiple runs; consume what we can
        common = _common_prefix(text, remaining)
        if common:
            run.text = text[len(common) :]
            remaining = remaining[len(common) :]


def _common_prefix(a: str, b: str) -> str:
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    return a[:i]
