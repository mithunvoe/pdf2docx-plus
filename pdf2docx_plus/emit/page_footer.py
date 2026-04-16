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
  3. Writes a single ``w:footer`` containing the static left-side text
     and a right-aligned ``PAGE`` field, and attaches a
     ``<w:footerReference>`` to every section so the footer renders on
     every page.

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
    """Move inline footer/page-number body text into a real ``w:footer``.

    Two detection paths are tried in order:

    1. ``"N Last update: <date>"`` footer lines (upstream's typical
       KFS-style footer). When found, the ``"Last update: <date>"``
       suffix becomes the canonical left-side footer text and any
       bare-digit paragraph sitting immediately before each footer
       line is absorbed as a page number.
    2. Bare-digit-only paragraphs that form a monotonically
       increasing step-1 sequence of length >= 3 (e.g. ``"1", "2",
       ..., "58"`` scattered one-per-source-page as in the
       First Sentier explanatory memos). When detected, the pass
       installs a plain page-field footer with no left-side text.

    Returns the number of body paragraphs absorbed. Returns 0 and
    makes no changes when neither pattern matches.
    """
    body = document.element.body
    paragraphs = list(body.iter(qn("w:p")))

    footer_suffixes: Counter[str] = Counter()
    footer_paras: list[Any] = []
    for p in paragraphs:
        text = _plain_text(p)
        m = _FOOTER_LINE.match(text)
        if m:
            footer_suffixes[m.group(2).strip()] += 1
            footer_paras.append(p)

    page_number_paras: list[Any] = []
    canonical_left = ""
    install_footer = False

    if footer_suffixes:
        # Path 1: explicit "Last update: ..." footer lines.
        footer_set = set(id(p) for p in footer_paras)
        for i, p in enumerate(paragraphs):
            if id(p) not in footer_set:
                continue
            j = i - 1
            # walk back over empty paragraphs to find the previous visible one
            while j >= 0 and not _plain_text(paragraphs[j]):
                j -= 1
            if j >= 0:
                prev = paragraphs[j]
                if id(prev) not in footer_set and _DIGIT_ONLY.match(_plain_text(prev)):
                    page_number_paras.append(prev)
        canonical_suffix = footer_suffixes.most_common(1)[0][0]
        canonical_left = f"Last update: {canonical_suffix}"
        install_footer = True
    else:
        # Path 2: detect a bare-digit page-number sequence.
        page_number_paras = _find_bare_page_number_sequence(paragraphs)
        if not page_number_paras:
            return 0
        # Upstream per-page sections typically have very tight bottom
        # margins; installing our own footer there measurably pushes
        # content past the section boundary and re-inflates the page
        # count. The bare-digit path therefore leaves upstream's
        # footer references alone and only strips the orphan page
        # numbers from the body.

    removed = 0
    for p in footer_paras + page_number_paras:
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

    if install_footer:
        for section in document.sections:
            _write_footer(section, canonical_left)

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
