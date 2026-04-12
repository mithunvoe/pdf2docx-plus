"""DOCX style system.

Upstream `pdf2docx` writes every paragraph with direct formatting (no
reference to a `w:pStyle`), which is why Word flags the output as
"Compatibility Mode" and the `editability` bench metric hovers near 0.
This module defines and installs a proper `styles.xml` inventory when a
`python-docx` `Document` is created, so downstream callers can reference
named styles and Word recognises the document as modern OOXML.

Installed styles:

* `Normal`                (default body)
* `Heading 1` - `Heading 6`
* `Title`, `Subtitle`
* `Hyperlink`
* `Caption`
* `Quote`
* `List Paragraph`
* `Footer`, `Header`

We do not replace `python-docx`'s built-in style definitions; we upgrade
them to have proper base properties and recolored heading accents, and add
the ones python-docx doesn't ship by default (e.g. `Caption`).
"""

from __future__ import annotations

from typing import Any

from docx import Document  # type: ignore
from docx.enum.style import WD_STYLE_TYPE  # type: ignore
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

_HEADING_COLORS = {
    1: RGBColor(0x1F, 0x3F, 0x6E),
    2: RGBColor(0x2E, 0x5C, 0x8A),
    3: RGBColor(0x3F, 0x78, 0xA6),
    4: RGBColor(0x5B, 0x93, 0xBE),
    5: RGBColor(0x7F, 0xAB, 0xC9),
    6: RGBColor(0x9F, 0xBD, 0xD6),
}

_HEADING_SIZES = {1: 18, 2: 16, 3: 14, 4: 12, 5: 11, 6: 11}


def install_styles(doc: Any) -> None:
    """Install / upgrade the full style inventory on a python-docx Document.

    Safe to call multiple times; existing styles are upgraded in place.
    """
    styles = doc.styles

    _upgrade_normal(styles)
    for level in range(1, 7):
        _upgrade_heading(styles, level)
    _ensure_style(styles, "Title", WD_STYLE_TYPE.PARAGRAPH, size_pt=26, bold=True)
    _ensure_style(styles, "Subtitle", WD_STYLE_TYPE.PARAGRAPH, size_pt=14, italic=True)
    _ensure_style(styles, "Caption", WD_STYLE_TYPE.PARAGRAPH, size_pt=9, italic=True)
    _ensure_style(styles, "Quote", WD_STYLE_TYPE.PARAGRAPH, size_pt=11, italic=True)
    _ensure_style(styles, "List Paragraph", WD_STYLE_TYPE.PARAGRAPH, size_pt=11)
    _ensure_hyperlink_style(styles)


def new_document() -> Any:
    """Create a Document with pdf2docx-plus styles pre-installed."""
    doc = Document()
    install_styles(doc)
    return doc


# -- internals --------------------------------------------------------------


def _upgrade_normal(styles: Any) -> None:
    try:
        normal = styles["Normal"]
    except KeyError:
        return
    font = normal.font
    # Conservative default; users' themes can still override.
    if font.name is None:
        font.name = "Calibri"
    if font.size is None:
        font.size = Pt(11)


def _upgrade_heading(styles: Any, level: int) -> None:
    name = f"Heading {level}"
    style = _ensure_style(
        styles,
        name,
        WD_STYLE_TYPE.PARAGRAPH,
        size_pt=_HEADING_SIZES[level],
        bold=level <= 3,
    )
    color = _HEADING_COLORS[level]
    if style.font.color is not None:
        style.font.color.rgb = color


def _ensure_style(
    styles: Any,
    name: str,
    kind: Any,
    *,
    size_pt: int | None = None,
    bold: bool = False,
    italic: bool = False,
) -> Any:
    try:
        style = styles[name]
    except KeyError:
        style = styles.add_style(name, kind)
    font = style.font
    if size_pt is not None and font.size is None:
        font.size = Pt(size_pt)
    if bold and font.bold is None:
        font.bold = True
    if italic and font.italic is None:
        font.italic = True
    return style


def _ensure_hyperlink_style(styles: Any) -> None:
    """python-docx ships no 'Hyperlink' character style by default. Emit one."""
    try:
        styles["Hyperlink"]
        return
    except KeyError:
        pass
    style = styles.add_style("Hyperlink", WD_STYLE_TYPE.CHARACTER)
    # color #0563C1 + single underline — the Word default hyperlink look
    rPr = style.element.get_or_add_rPr()
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    rPr.append(color)
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rPr.append(u)


__all__ = ["install_styles", "new_document"]
