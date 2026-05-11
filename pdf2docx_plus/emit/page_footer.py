"""Promote per-page footer text to a real ``w:footer`` with a ``PAGE`` field.

Upstream emits the per-page footer (``"N Last update: 2 October 2024"``)
and stray page-number lines as plain body paragraphs — one copy per
source page. This is wrong two ways:

  * the page numbers are static text, so ``"1"``, ``"2"``, ... stay in
    place even when the DOCX repaginates to a different page count;
  * the footer line repeats inline at every section boundary, so the
    user sees 67 copies of ``"Last update: 2 October 2024"`` in the
    body instead of one rendered by Word at the bottom of every page.

This pass:

  1. Detects body paragraphs that match the per-page footer pattern
     ``(\\d+\\s+)?Last update:\\s*.+`` and standalone digit-only
     paragraphs adjacent to them (bare page numbers).
  2. Removes them from the body.
  3. Groups the matched paragraphs by section and writes a section
     ``w:footer`` only for the sections that actually carried the
     pattern.  Consecutive sections that share the same footer text
     are collapsed via ``is_linked_to_previous``.  Sections that had
     no matching footer paragraph keep their existing footer
     untouched (previously the function installed the canonical
     footer for *every* section, which was wrong for multi-section
     documents whose section boundaries didn't line up with the
     source pages).

The pass is idempotent: a second invocation finds nothing to move.
Invoked only when the caller opts in via the ``promote_page_footer``
flag so we never corrupt documents whose footers upstream already got
right.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

_FOOTER_LINE = re.compile(r"^\s*(?:(\d+)\s+)?Last update:\s*(.+?)\s*$")
_DIGIT_ONLY = re.compile(r"^\s*\d{1,4}\s*$")


def promote_page_numbers_to_footer(document: Any) -> int:
    """Move inline footer/page-number body text into real ``w:footer`` parts.

    Two detection paths are tried in order:

    1. ``"N Last update: <date>"`` footer lines (upstream's typical
       KFS-style footer). For each section that contains the
       pattern, write a real footer with the most-frequent
       ``Last update: <date>`` text seen in that section.  Sections
       without the pattern are untouched.
    2. Bare-digit-only paragraphs that form a monotonically
       increasing step-1 sequence of length >= 3 (e.g. ``"1", "2",
       ..., "58"`` scattered one-per-source-page as in the
       First Sentier explanatory memos). When detected, the pass
       removes the orphan page numbers from the body but does NOT
       install a new footer (upstream per-page sections typically
       have very tight bottom margins; installing our own footer
       there measurably pushes content past the section boundary).

    Returns the number of body paragraphs absorbed. Returns 0 and
    makes no changes when neither pattern matches.
    """
    body = document.element.body
    # Walk the body's direct children so we can attribute each
    # paragraph to its section (the paragraph carrying ``<w:sectPr>``
    # is the LAST paragraph of its section).
    section_buckets: list[list[Any]] = [[]]
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            section_buckets[-1].append(child)
            if child.find(qn("w:pPr") + "/" + qn("w:sectPr")) is not None:
                section_buckets.append([])
    if section_buckets and not section_buckets[-1]:
        section_buckets.pop()

    sections = list(document.sections)
    while len(section_buckets) < len(sections):
        section_buckets.append([])

    # Path 1: per-section "Last update" detection.
    section_footer_text: dict[int, str] = {}
    matched_footer_paragraphs: list[Any] = []
    matched_digit_paragraphs: list[Any] = []
    for idx, bucket in enumerate(section_buckets):
        if idx >= len(sections):
            break
        suffix_counts: Counter[str] = Counter()
        footer_paras_in_section: list[Any] = []
        for p in bucket:
            text = _plain_text(p)
            m = _FOOTER_LINE.match(text)
            if m:
                suffix_counts[m.group(2).strip()] += 1
                footer_paras_in_section.append(p)
        if not footer_paras_in_section:
            continue
        canonical_suffix = suffix_counts.most_common(1)[0][0]
        section_footer_text[idx] = f"Last update: {canonical_suffix}"
        matched_footer_paragraphs.extend(footer_paras_in_section)
        # find adjacent bare-digit page numbers in the same section
        bucket_positions = {id(p): i for i, p in enumerate(bucket)}
        for p in footer_paras_in_section:
            pos = bucket_positions.get(id(p))
            if pos is None:
                continue
            j = pos - 1
            while j >= 0 and not _plain_text(bucket[j]):
                j -= 1
            if j >= 0 and id(bucket[j]) not in bucket_positions and False:
                continue
            if j >= 0 and _DIGIT_ONLY.match(_plain_text(bucket[j])):
                matched_digit_paragraphs.append(bucket[j])

    bare_sequence: list[Any] = []
    if not section_footer_text:
        # Path 2: detect a global bare-digit page-number sequence.
        all_paragraphs = [p for bucket in section_buckets for p in bucket]
        bare_sequence = _find_bare_page_number_sequence(all_paragraphs)
        if not bare_sequence:
            return 0

    removed = 0
    # remove footer + digit paragraphs from the body
    to_remove = list(matched_footer_paragraphs) + list(matched_digit_paragraphs) + list(bare_sequence)
    seen: set[int] = set()
    for p in to_remove:
        if id(p) in seen:
            continue
        seen.add(id(p))
        parent = p.getparent()
        if parent is None:
            continue
        # paragraphs that sit inside a pPr/sectPr carrier are actual
        # section-break paragraphs; removing them loses the break.
        # Strip runs only in that case.
        sect = p.find(qn("w:pPr") + "/" + qn("w:sectPr"))
        if sect is not None:
            for r in list(p.findall(qn("w:r"))):
                p.remove(r)
            removed += 1
            continue
        parent.remove(p)
        removed += 1

    # install footers section-by-section
    if section_footer_text:
        prev_text: str | None = None
        for idx, section in enumerate(sections):
            text = section_footer_text.get(idx)
            if text is None:
                continue
            if text == prev_text:
                try:
                    section.footer.is_linked_to_previous = True
                except Exception:
                    _write_footer(section, text)
            else:
                _write_footer(section, text)
                prev_text = text

    return removed


def _find_bare_page_number_sequence(paragraphs: list[Any]) -> list[Any]:
    """Return paragraphs whose numeric values form a page-number run.

    Accepts the bare-digit paragraphs as a page-number sequence when
    all of these hold:

      * at least five bare-digit paragraphs are present,
      * their values are strictly increasing in document order
        (upstream emits page numbers on every page),
      * the first value is 1, 2, or 3 (anchors to a sequence that
        starts near the beginning of the document),
      * the gap between consecutive values is at most 3 (upstream
        occasionally drops a page-number line, so small gaps are
        tolerated, but not arbitrary jumps),
      * the maximum value is at most twice the count (filters out
        ``[1, 2, 3, 75, 100]``-style tables that happen to start
        with a short ascending run of small numbers).

    The returned list is in document order. Returns an empty list
    when the bare digits look like data values rather than page
    numbers.
    """
    bare: list[tuple[Any, int]] = []
    for p in paragraphs:
        text = _plain_text(p)
        if _DIGIT_ONLY.match(text):
            try:
                bare.append((p, int(text)))
            except ValueError:  # pragma: no cover - regex guarantees int
                pass
    if len(bare) < 5:
        return []

    values = [v for _, v in bare]
    if values[0] > 3:
        return []
    for a, b in zip(values, values[1:]):
        if b <= a:
            return []
        if b - a > 3:
            return []
    if values[-1] > len(values) * 2:
        return []
    return [p for p, _ in bare]


# -- helpers --------------------------------------------------------------


def _plain_text(p: Any) -> str:
    return "".join(
        (t.text or "") for t in p.iter(qn("w:t"))
    ).strip()


def _write_footer(section: Any, left_text: str) -> None:
    """Replace the section's default footer.

    When ``left_text`` is non-empty, the footer is
    ``<left_text>\\t<PAGE-field>``. When empty, only the
    right-aligned ``PAGE`` field is written.
    """
    footer = section.footer
    footer.is_linked_to_previous = False
    # wipe any existing content
    ftr_el = footer._element  # type: ignore[attr-defined]
    for child in list(ftr_el):
        ftr_el.remove(child)

    p = OxmlElement("w:p")
    pPr = OxmlElement("w:pPr")
    tabs = OxmlElement("w:tabs")
    # right-aligned tab near the page's right margin
    right_tab = OxmlElement("w:tab")
    right_tab.set(qn("w:val"), "right")
    right_tab.set(qn("w:pos"), str(_right_tab_pos(section)))
    tabs.append(right_tab)
    pPr.append(tabs)
    p.append(pPr)

    # static left text (omit when empty so the PAGE field hugs the right tab)
    if left_text:
        r_left = OxmlElement("w:r")
        t_left = OxmlElement("w:t")
        t_left.text = left_text
        t_left.set(qn("xml:space"), "preserve")
        r_left.append(t_left)
        p.append(r_left)

    # tab to push the page field to the right-aligned stop
    r_tab = OxmlElement("w:r")
    r_tab.append(OxmlElement("w:tab"))
    p.append(r_tab)

    # PAGE field: begin / instrText "PAGE" / end
    for r in _page_field_runs():
        p.append(r)

    ftr_el.append(p)


def _right_tab_pos(section: Any) -> int:
    """Return the twentieths-of-a-point position of the right margin."""
    page_width = int(section.page_width) if section.page_width else 12240
    left = int(section.left_margin) if section.left_margin else 1440
    right = int(section.right_margin) if section.right_margin else 1440
    # python-docx Length is EMU; 1 point = 12700 EMU, 1 twip = 635 EMU.
    return max(0, (page_width - left - right) // 635)


def _page_field_runs() -> list[Any]:
    runs: list[Any] = []
    for field_char_type, instr in (
        ("begin", None),
        (None, "PAGE"),
        ("end", None),
    ):
        r = OxmlElement("w:r")
        if field_char_type:
            fc = OxmlElement("w:fldChar")
            fc.set(qn("w:fldCharType"), field_char_type)
            r.append(fc)
        else:
            it = OxmlElement("w:instrText")
            it.text = instr
            it.set(qn("xml:space"), "preserve")
            r.append(it)
        runs.append(r)
    return runs
