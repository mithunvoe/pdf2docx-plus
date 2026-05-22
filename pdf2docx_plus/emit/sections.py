"""Collapse multi-column sections that upstream emits for horizontal layouts.

Upstream `pdf2docx` tries to reproduce page-1 "logo-left / title-right"
headers by splitting the page into a 2-column section with a
`nextColumn` break between logo and title. LibreOffice (and older Word
versions) renders this as two separate vertical columns — the logo in
column 1, the title alone in column 2 — and then inserts a page break
when the column layout changes back to 1-col. The net result is a
nearly-blank first page with only the logo, all body content shoved
one page forward (11 rendered pages vs 9 in the source PDF).

The fix: normalize every `<w:cols w:num="N"/>` with N>1 to N=1, and
downgrade any accompanying `<w:type w:val="nextColumn"/>` to
`continuous`. The body content then flows naturally top-to-bottom: the
logo and title appear on the same page, followed by the body, with the
correct page count.

This is preferable to trying to keep the 2-column layout because:
  1. Columns in OOXML flow top-to-bottom-then-jump-to-next-column,
     not left-to-right. That's never the right semantic for a banner.
  2. A real horizontal banner wants a table or text-wrapping frames,
     which upstream doesn't emit.
  3. Falling back to vertical (single-column) flow loses zero content
     — only the visual horizontality of the banner — which is a
     vastly better trade than losing a whole page.

Applied by default because on the seed corpus it converted 11 -> 9
pages (kfs_bosera) and corrected first-page layout with zero content
loss.
"""

from __future__ import annotations

from typing import Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# python-docx's ``qn`` does not register the legacy VML namespace, so build
# the Clark-notation tag for ``<v:imagedata>`` directly.
_VML_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"


def normalize_multi_column_sections(document: Any) -> int:
    """Convert every `w:cols w:num` > 1 to 1. Returns count normalized."""
    body = document.element.body
    changed = 0
    for cols in body.iter(qn("w:cols")):
        num_attr = cols.get(qn("w:num"))
        try:
            num = int(num_attr) if num_attr else 1
        except ValueError:
            num = 1
        if num <= 1:
            continue
        cols.set(qn("w:num"), "1")
        # drop any per-column width definitions
        for child in list(cols):
            cols.remove(child)
        changed += 1
    # downgrade nextColumn break type to continuous; nextColumn only makes
    # sense inside a multi-column section.
    for t in body.iter(qn("w:type")):
        if t.get(qn("w:val")) == "nextColumn":
            t.set(qn("w:val"), "continuous")
    return changed


def fix_page_margins(document: Any) -> int:
    """Sanitize `<w:pgMar>` entries for cross-renderer consistency.

    Ensure `w:header` / `w:footer` reservations don't exceed `w:top` /
    `w:bottom` body margins. Upstream often emits `w:header="720"`
    (0.5") with `w:top="684"` (0.48") which pushes content down by
    the overflow.

    We do NOT enforce a minimum side margin because many upstream
    documents legitimately use edge-to-edge layouts.

    Returns the number of pgMar elements adjusted.
    """
    body = document.element.body
    fixed = 0
    for pg in body.iter(qn("w:pgMar")):
        top = _int(pg.get(qn("w:top")), 720)
        bottom = _int(pg.get(qn("w:bottom")), 720)
        header = _int(pg.get(qn("w:header")), 720)
        footer = _int(pg.get(qn("w:footer")), 720)
        changed = False
        if header > top - 20:
            pg.set(qn("w:header"), str(max(0, top - 20)))
            changed = True
        if footer > bottom - 20:
            pg.set(qn("w:footer"), str(max(0, bottom - 20)))
            changed = True
        if changed:
            fixed += 1
    return fixed


def _int(s: str | None, default: int) -> int:
    if not s:
        return default
    try:
        return int(s)
    except ValueError:
        return default


def flatten_per_page_sections(document: Any) -> int:
    """Convert per-page `nextPage` section breaks to `continuous`.

    Upstream emits one `<w:sectPr>` per source PDF page, each with its
    own page margins and a default (`nextPage`) break type — i.e. a
    forced page break at every section boundary. When Word renders the
    text with a substituted font, content can overflow its section's
    tight margin by a few millimetres; the overflow lands on a new
    page, but the next section's `nextPage` break still fires, costing
    a full page per overflow. A 67-page PDF can balloon to 73 DOCX
    pages from this alone.

    Converting mid-document break types to `continuous` lets Word
    repaginate naturally — content flows section-to-section without
    forced breaks, and the rendered page count tracks actual content
    length.

    Skipped (returns 0) when:
      * any sectPr declares a per-section `headerReference` or
        `footerReference` — collapsing breaks would cause those parts
        to be applied to the wrong content;
      * page sizes (`pgSz`) vary across sections — different page
        sizes legitimately need page breaks (landscape/portrait mix).

    Returns the number of section breaks converted.
    """
    body = document.element.body
    sect_prs = list(body.iter(qn("w:sectPr")))
    if len(sect_prs) <= 1:
        return 0
    for sp in sect_prs:
        if sp.find(qn("w:headerReference")) is not None:
            return 0
        if sp.find(qn("w:footerReference")) is not None:
            return 0
    pg_sizes = set()
    for sp in sect_prs:
        sz = sp.find(qn("w:pgSz"))
        if sz is not None:
            pg_sizes.add((sz.get(qn("w:w")), sz.get(qn("w:h")), sz.get(qn("w:orient"))))
    if len(pg_sizes) > 1:
        return 0
    converted = 0
    for sp in sect_prs:
        # final sectPr is body's direct child; mid-doc are inside w:pPr
        parent = sp.getparent()
        if parent is None or parent.tag != qn("w:pPr"):
            continue
        type_el = sp.find(qn("w:type"))
        if type_el is None:
            type_el = OxmlElement("w:type")
            sp.insert(0, type_el)
        if type_el.get(qn("w:val")) != "continuous":
            type_el.set(qn("w:val"), "continuous")
            converted += 1
    return converted


def collapse_empty_sections(document: Any) -> int:
    """Remove sections whose body contains no visible content.

    Upstream occasionally emits `<w:sectPr>` boundaries between empty
    placeholder paragraphs — e.g. a header-detection stub or a spurious
    page-break sentinel that holds no text, image, or drawing. Each
    empty section with a default (``nextPage``) break type still forces
    a page break, so the reader sees a blank page for every orphan
    section.

    Also collapses **logo-only sections**: a section whose entire body
    consists of a single small drawing (typically the page-header
    image that upstream re-emits on every source-PDF page) and no
    text, table, or other visual content.  Those sections render as
    near-blank pages in the DOCX because the only thing on the page
    is the logo and the real body content has been merged into a
    neighbouring section by stitching or content recovery.

    This pass walks the body paragraphs in order, groups them into
    per-section buckets (each bucket ending at a paragraph whose
    ``<w:pPr>`` carries a ``<w:sectPr>``), and removes every bucket
    that has no meaningful content. The final section - which uses
    the body-level ``<w:sectPr>`` rather than a paragraph-level one -
    is never removed; stripping it would orphan the whole document.

    "Meaningful content" means: any ``<w:t>`` with non-whitespace
    text, any ``<w:tbl>``, OR more than one drawing / pict / object
    embedding.  A single drawing is collapsed **only when its image
    survives elsewhere** - in a header/footer or in another retained
    section - or when it carries no resolvable image at all (an empty
    or broken drawing that renders nothing).  A lone drawing that is
    the only remaining copy of a real image is kept: dropping it would
    delete the picture entirely, which is what happened to cover-page
    logos (e.g. KFS) that were never promoted to a header.

    Returns the number of empty sections collapsed.
    """
    body = document.element.body
    collapsed = 0
    # scan the body's direct children; tables and paragraphs are siblings
    children = list(body)
    buckets: list[list[Any]] = [[]]
    for child in children:
        buckets[-1].append(child)
        if child.tag == qn("w:p") and child.find(qn("w:pPr") + "/" + qn("w:sectPr")) is not None:
            buckets.append([])
    # final bucket uses body-level sectPr - leave it alone
    if buckets and not buckets[-1]:
        buckets.pop()
    if len(buckets) <= 1:
        return 0

    try:
        body_rels = document.part.rels
    except Exception:
        body_rels = {}
    # Images we are allowed to drop a copy of, because the picture survives
    # somewhere else: any header/footer image, plus any image inside a
    # bucket that has real content and is therefore never collapsed.
    preserved = _header_footer_image_targets(document)
    for bucket in buckets:
        if _bucket_has_content(bucket):
            preserved |= _bucket_image_targets(bucket, body_rels)

    kept_single: set[str] = set()
    for bucket in buckets[:-1]:
        if _bucket_has_content(bucket):
            continue
        targets = _bucket_image_targets(bucket, body_rels)
        # Keep a lone drawing only when it is the sole surviving copy of a
        # real image (not in a header and not in any retained section, and
        # not already kept once). Everything else - decorative repeats,
        # empty/broken drawings, truly blank stubs - is collapsed.
        if targets and not targets <= (preserved | kept_single):
            kept_single |= targets
            continue
        for el in bucket:
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
        collapsed += 1
    return collapsed


def _bucket_has_content(bucket: list[Any]) -> bool:
    has_text = False
    has_table = False
    drawing_count = 0
    for el in bucket:
        if el.tag == qn("w:tbl"):
            has_table = True
            break
        for t in el.iter(qn("w:t")):
            if (t.text or "").strip():
                has_text = True
                break
        if has_text:
            break
        for tag in ("w:drawing", "w:pict", "w:object"):
            for _ in el.iter(qn(tag)):
                drawing_count += 1
                if drawing_count > 1:
                    return True
    # Exactly one drawing (or none) and nothing else is not "real" content;
    # the caller decides whether to collapse based on image identity.
    return has_table or has_text


def _bucket_image_targets(bucket: list[Any], rels: Any) -> set[str]:
    """Resolvable media partnames for every image referenced in the bucket."""
    targets: set[str] = set()
    for el in bucket:
        targets |= _drawing_targets(el, rels)
    return targets


def _drawing_targets(element: Any, rels: Any) -> set[str]:
    """Media partnames referenced by DrawingML / VML images in ``element``.

    Only relationships that resolve to an internal image part are
    returned; external links and dangling ids are ignored.
    """
    targets: set[str] = set()
    for blip in element.iter(qn("a:blip")):
        for attr in (qn("r:embed"), qn("r:link")):
            t = _rid_to_partname(rels, blip.get(attr))
            if t:
                targets.add(t)
    for img in element.iter(_VML_IMAGEDATA):
        t = _rid_to_partname(rels, img.get(qn("r:id")))
        if t:
            targets.add(t)
    return targets


def _rid_to_partname(rels: Any, rid: str | None) -> str | None:
    if not rid:
        return None
    try:
        rel = rels[rid]
        if rel.is_external:
            return None
        return str(rel.target_part.partname)
    except Exception:
        return None


def _header_footer_image_targets(document: Any) -> set[str]:
    """Media partnames referenced by every header / footer part."""
    targets: set[str] = set()
    try:
        rels = document.part.rels
    except Exception:
        return targets
    for rel in list(rels.values()):
        try:
            if rel.is_external:
                continue
            reltype = rel.reltype or ""
            if not (reltype.endswith("/header") or reltype.endswith("/footer")):
                continue
            part = rel.target_part
            targets |= _drawing_targets(part.element, part.rels)
        except Exception:
            continue
    return targets


def consolidate_identical_sections(document: Any) -> int:
    """Issue P-4: drop mid-document `<w:sectPr>` boundaries that don't
    change any logical layout property.

    Upstream `pdf2docx` emits one `<w:sectPr>` per source PDF page even
    when consecutive pages share identical page size, margins, columns,
    and orientation.  Two PDFs that are logically the same therefore
    end up with different section counts purely because of page-count
    drift (e.g. Bosera OLD=14 vs NEW=17), which then breaks downstream
    header/footer matching that aligns sections by index.

    This pass keeps the first sectPr and the final body-level sectPr,
    and removes every mid-document sectPr whose section properties
    match the previously-retained section.  "Match" compares the
    structural attributes that actually affect rendering:

    * page size (``w:pgSz`` width / height / orientation),
    * page margins (``w:pgMar``),
    * number of columns and column spacing (``w:cols``),
    * header / footer references (``w:headerReference`` /
      ``w:footerReference``),
    * page numbering format (``w:pgNumType``).

    Sections that differ in any of those are kept — they encode a real
    layout transition the document depends on.

    Returns the number of redundant section breaks removed.
    """
    body = document.element.body
    sect_prs = list(body.iter(qn("w:sectPr")))
    if len(sect_prs) <= 1:
        return 0

    # The final sectPr is body-level (not wrapped in a paragraph's pPr).
    # Mid-document sectPrs are inside <w:pPr>.  We only consolidate
    # mid-document ones — stripping the body-level sectPr would orphan
    # the document trailer.
    mid_doc = [
        sp for sp in sect_prs if sp.getparent() is not None and sp.getparent().tag == qn("w:pPr")
    ]
    if not mid_doc:
        return 0

    removed = 0
    last_sig = _section_signature(sect_prs[0])
    keep_first = sect_prs[0]
    for sp in sect_prs[1:]:
        if sp is keep_first:
            continue
        # only consider removing mid-doc sectPrs
        parent = sp.getparent()
        if parent is None or parent.tag != qn("w:pPr"):
            # body-level (final) sectPr — always keep
            last_sig = _section_signature(sp)
            continue
        sig = _section_signature(sp)
        if sig == last_sig:
            # redundant: remove the sectPr from the pPr, and drop the
            # pPr-only paragraph if it becomes empty (a section-marker
            # paragraph with nothing else is just chrome).
            parent.remove(sp)
            # also remove the parent <w:pPr> if it now has no children
            if len(parent) == 0:
                pPr_parent = parent.getparent()
                if pPr_parent is not None:
                    pPr_parent.remove(parent)
            removed += 1
        else:
            last_sig = sig
    return removed


def _section_signature(sect_pr: Any) -> tuple:
    """Capture the structural attributes of a `<w:sectPr>` that affect
    rendering.  Two sectPrs with equal signatures are functionally
    interchangeable.
    """

    def _attrs(tag_name: str, attr_names: tuple[str, ...]) -> tuple:
        el = sect_pr.find(qn(tag_name))
        if el is None:
            return ()
        return tuple(el.get(qn(a)) for a in attr_names)

    pg_sz = _attrs("w:pgSz", ("w:w", "w:h", "w:orient"))
    pg_mar = _attrs(
        "w:pgMar",
        ("w:top", "w:right", "w:bottom", "w:left", "w:header", "w:footer", "w:gutter"),
    )
    cols = _attrs("w:cols", ("w:num", "w:space", "w:equalWidth"))
    pg_num = _attrs("w:pgNumType", ("w:fmt", "w:start"))
    # header/footer references collapse to a sorted tuple of (type, id) pairs
    refs: list[tuple[str, str]] = []
    for tag in ("w:headerReference", "w:footerReference"):
        for r in sect_pr.findall(qn(tag)):
            refs.append((tag, r.get(qn("w:type")) or "", r.get(qn("r:id")) or ""))
    return (pg_sz, pg_mar, cols, pg_num, tuple(sorted(refs)))


def clamp_paragraph_spacing(document: Any, *, max_twips: int = 480) -> int:
    """Cap `w:spacing w:before` / `w:after` at `max_twips`.

    Upstream emits paragraph spacing values that encode the inter-block
    vertical gap measured in the source PDF. With the default font
    substitution (Liberation Sans) text takes more vertical space than
    the original, and an inflated `w:before` / `w:after` then pushes
    content past the per-page section boundary, costing a full page
    each time. Clamping at 480 twips (~24pt = 2 lines) preserves
    typical paragraph break spacing while cutting the inflated values
    that drive page-count overflow.

    Returns the number of attributes clamped.
    """
    body = document.element.body
    clamped = 0
    for sp in body.iter(qn("w:spacing")):
        for attr in (qn("w:before"), qn("w:after")):
            v = sp.get(attr)
            if not v or not v.isdigit():
                continue
            if int(v) > max_twips:
                sp.set(attr, str(max_twips))
                clamped += 1
    return clamped
