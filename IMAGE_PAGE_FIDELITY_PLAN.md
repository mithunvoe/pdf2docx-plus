# Image & Page-Chrome Fidelity Fix Plan

**Created:** 2026-05-22
**Scope:** `pdf2docx-plus` post-emit layer only (`pdf2docx_plus/emit/*`).
No changes to the vendored upstream parser. Do not push.

## 1. Symptoms (reported)

1. Output is "messy", and **messier when a page contains an image**.
2. Many pages contain **just one line of text and nothing else** (near-blank pages).

## 2. Evidence (reproduced)

Converted three representative source PDFs and rendered DOCX → PDF → PNG:

| Source PDF | PDF pages | DOCX pages | Phantom / broken pages |
|---|---|---|---|
| `New_FAQ_SFC Authorization of UCITS Funds` | 3 | 4 | DOCX p3 = SFC logo + lone "2", nothing else |
| `Old_AWHKEF` | 9 | 10 | DOCX p? = lone "– 2 –" |
| `New_UT_2_Eng_doc` | 69 | 77 | 8 extra; p2 logo **overlaps** body text, sparse |

Concrete defects observed in the rendered output:

- **Phantom chrome pages.** A section whose entire body is the repeating
  letterhead image + the page number renders as a near-blank page
  (logo top-left, page number, nothing else).
- **Logo/body overlap.** On content pages the inline letterhead image
  collides with the first body line (UT page 2).
- **Static, wrong page numbers.** "1" repeats on every page; decorated
  numbers like "– 2 –" are never recognised.

## 3. Root cause

In the default profile each source PDF page becomes one DOCX **section**
with a hard page break and its own margins (`flatten_sections=False`).
The repeating **page chrome** — the letterhead **image** at the top and
the **page number** at the bottom — is emitted as inline **body**
content because:

1. `layout/hf_detect.py` and `emit/headers_footers.py` only consider
   **text** blocks (`hasattr(block, "lines")` / `<w:t>`); a repeating
   letterhead **image** is never lifted into the section header.
2. `emit/page_footer.py` only promotes `"N Last update: …"` footers or a
   bare-digit sequence of length ≥ 5. Short documents and decorated
   numbers (`– 2 –`, `[2]`, `Page 2`, `2 of 10`) slip through.
3. `emit/sections.py::collapse_empty_sections` already collapses
   *logo-only* sections, but a stray page-number paragraph counts as
   "content", so the chrome section survives as a blank page.

Upstream deduplicates images, so a repeating letterhead is reliably
identifiable by `r:embed` reuse (UT `rId11` is referenced 55× — once per
page).

## 4. Fix design (all in the post-emit layer)

### Fix 1 — Promote repeating letterhead images to the section header
New module `emit/header_images.py`, `promote_header_images_to_section(doc)`:

- Partition the body into per-section buckets (paragraph carrying
  `<w:sectPr>` ends a bucket).
- Find **lone-image paragraphs**: a `<w:p>` with no non-whitespace
  `<w:t>` and exactly one `<w:drawing>`. Record `(bucket, para, embed_id,
  extent)`.
- A `embed_id` that recurs in `≥ max(2, 0.3 × n_sections)` buckets AND
  whose extent height ≤ 50% of page height is a **letterhead**.
- For each section carrying a letterhead, copy the image **once** into
  `section.header` (extract bytes via `doc.part.related_parts[embed_id]
  .blob`, size with `Emu(cx/cy)`, preserve paragraph alignment), linking
  consecutive identical sections via `is_linked_to_previous`. Remove the
  inline copies from the body.
- Gated by new `convert(..., promote_header_images=True)` flag.
  Reports `ConversionResult.header_images_promoted`.

This fixes the inline-logo overlap **and** empties chrome-only sections
so they collapse.

### Fix 2 — Broaden page-number footer promotion
Extend `emit/page_footer.py` with a per-section trailing-page-number path:

- Recognise decorated/word forms: `– 2 –`, `- 2 -`, `[2]`, `(2)`,
  `Page 2`, `2 of 10`, `2 / 10`, and bare `2`.
- Per section, inspect the **last** non-empty paragraph; if it matches a
  page-number form, record `(section_idx, value)`.
- When ≥ 2 sections carry one and the values increase monotonically
  (gap ≤ 3), strip them from the body and install a real `PAGE`-field
  footer (right/centre per source alignment). Validate page counts; fall
  back to strip-only if a footer measurably adds pages.

### Fix 3 — (only if needed) chrome-only collapse safety net
After Fix 1+2 the chrome sections are already empty and collapse via the
existing pass. Extend `_bucket_has_content` to ignore a lone
page-number-pattern paragraph only if validation shows residual blanks.

## 5. TDD

Unit tests (build `Document()` directly, mirror `test_page_footer.py` /
`test_inline_images.py`):

- `tests/test_header_images.py`
  - repeating lone-image across 3 sections → moved to header, body
    drawings removed, `header_images_promoted == 3`.
  - a one-off inline image on a single section → **left in body**
    (regression guard: real figures must not migrate).
  - non-image content untouched.
- `tests/test_page_footer.py` (extend)
  - `– 2 –`, `[3]`, `Page 4`, `5 of 10` recognised and stripped.
  - a bare "2" that is real table data (not trailing/standalone) is
    **kept** (regression guard).

Then full suite must stay green (`pytest -q`, baseline 242 passed).

## 6. End-to-end validation

Re-convert the three PDFs and assert:

- FAQ_SFC: 4 → 3 pages, no logo-only page.
- AWHKEF: 10 → 9 pages, no "– 2 –" page.
- UT: 77 → ≤ 70 pages, no logo/text overlap on page 2.
- Spot-render PNGs before/after.

## 7. Risks & mitigations

- **Real top-of-page figure misclassified as letterhead** → require
  cross-section repetition; one-offs stay inline (tested).
- **Footer install adds overflow pages** → measure; fall back to
  strip-only.
- **Header relationship breakage** → use python-docx `add_picture` on a
  header run (creates the rel in the header part), never move raw XML.
- **Don't regress** the existing 242 tests, especially
  `test_empty_sections`, `test_page_footer`, `test_inline_images`.

## 8. Results (implemented)

All three fixes shipped in the post-emit layer:

- `emit/header_images.py` — `promote_header_images_to_section` (new),
  wired into `api.py` behind `promote_header_images=True`, reports
  `ConversionResult.header_images_promoted`. Scales the header image to
  a band and reserves top-margin so it never overlaps the body.
- `emit/page_footer.py` — `_find_trailing_page_numbers` (new path 3):
  decorated/short trailing page numbers (`- 2 -`, `[3]`, `Page 4`,
  `5 of 10`, bare digits) stripped per-section.
- `emit/headers_footers.py` — defers `Last update` footer lines to the
  page-footer pass so the page number becomes a live `PAGE` field
  instead of a frozen "1".

Page-count and defect deltas (LibreOffice render):

| Doc | src | before | after | overlap | phantom pages |
|---|---|---|---|---|---|
| FAQ_SFC | 3 | 4 | **3** | n/a | gone |
| AWHKEF | 9 | 10 | **9** | n/a | gone ("- 2 -") |
| UT | 69 | 77 | **76** | **fixed** | reduced; footer page # fixed |
| FAQ Post-Auth | 42 | 34 | **32** | fixed | reduced |
| Bosera (P1-P6 target) | 10 | 13 | **13** | n/a | unchanged (no regression) |

Tests: 242 -> **252** passing (10 new). No new ruff/mypy findings.
Full 13-PDF corpus converts with 0 page failures.

Remaining (out of scope, noted): per-page sections + font
substitution still leave UT a few pages over source — the documented
`flatten_sections` trade-off, independent of page chrome.
