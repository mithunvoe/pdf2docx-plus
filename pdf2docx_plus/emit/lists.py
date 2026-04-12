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
    """Promote marker-prefixed paragraphs in `doc` to real lists.

    Returns the number of paragraphs converted.
    """
    numbering = _ensure_numbering_part(doc)

    kind_to_num_id: dict[str, int] = {}
    converted = 0
    prev_kind: str | None = None
    for paragraph in doc.paragraphs:
        text = paragraph.text
        marker = detect_list_block(text)
        if marker is None:
            prev_kind = None
            continue
        num_id = kind_to_num_id.get(marker.kind)
        if num_id is None or marker.kind != prev_kind:
            num_id = _allocate_num_id(numbering, marker.kind, start_at=marker.start_at or 1)
            kind_to_num_id[marker.kind] = num_id
        _apply_list_formatting(paragraph, marker, num_id)
        converted += 1
        prev_kind = marker.kind
    return converted


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
