# PDF → Redline Fidelity: pdf2docx-plus Fix Plan

**Created:** 2026-05-19
**Sibling document:** [`PDF_FIDELITY_COMPARIO_PLAN.md`](./PDF_FIDELITY_COMPARIO_PLAN.md)
**Scope:** Quality gaps in the **`pdf2docx-plus`** converter
(`/mnt/NewVolume2/Android Projects/makebell/voedocx/pdf2docx-plus/`)
that show up as visible defects in Compario's PDF-input redline,
benchmarked against the Litera-generated
`DV_KFS_Bosera USD Money Market ETF.docx` for the Bosera PDF pair.

> This document covers only what we need to change inside the
> third-party (forked) converter. Anything that can be patched
> downstream — in Compario's `pdf_normalizer.py` or in the comparison
> / report services — is tracked in the sibling Compario plan.
> A handful of items below are "either side" — they can be implemented
> in the converter (correct fix) or in `pdf_normalizer.py` (safe
> short-term sanitiser). Both options are listed where applicable.

## 1. Why these matter

The Compario pipeline runs:

```
PDF → pdf2docx-plus → DOCX → pdf_normalizer.py → DocxParser → comparison → redline
```

Every defect injected at the `pdf2docx-plus` stage propagates downstream
unless `pdf_normalizer.py` can scrub it. The four high-impact converter
defects below are responsible for roughly half the Litera-parity gap on
the Bosera corpus, and they affect every fund-document PDF we process,
not just Bosera.

| Bosera benchmark slice (after Compario fixes) | Without converter fixes | With converter fixes |
|---|---|---|
| Missed deletions (Litera says delete, we don't) | ~12 | ~2 |
| OLD-text Jaccard | 0.968 | ≥ 0.99 (target) |
| NEW-text Jaccard | 0.971 | ≥ 0.99 (target) |
| Table count drift (OLD ref=10 vs our=4) | -6 | ≤ -1 |
| Phantom `<w:highlight>` runs in NEW | 99 / 1014 | 0 |

---

## 2. pdf2docx-plus Issue Inventory

Severity: H (high), M (medium), L (low).

### Issue P1 — Spurious green/yellow highlights polluting output **[H]**

**Symptom.** 99 of 1014 runs in the converted Bosera-NEW DOCX carry
`<w:highlight w:val="green"/>` (3 carry `yellow`). The PDF has no actual
highlights. These survive into Compario's final redline and look like
"highlighted edits" that are unrelated to the change set.

**Root cause.**

- `pdf2docx_plus/_vendored/pdf2docx/shape/Shape.py` and
  `shape/Shapes.py` heuristics — `_parse_semantic_type` treats Fill
  shapes whose vertical span does not exceed a single text line as
  "text highlight".
- `_vendored/pdf2docx/common/docx.py` `set_char_shading_color` maps
  unknown RGB values into the 16-colour highlight palette (defaulting
  to `green` / `yellow` for common drifts).

Many of the green-highlight runs in Bosera correspond to text adjacent
to table grid lines or to PDF guides used by InDesign for paragraph
rules.

**Fix (preferred — in pdf2docx-plus).** Tighten the shape detector:
require the inferred fill area to overlap ≥ X % of the text bbox AND
have a saturation > T (i.e., real yellow/green highlighter ink) before
being promoted to text highlight.

**Fix (safe short-term — in Compario `pdf_normalizer.py`).** Add
`_strip_phantom_highlights(root)` that removes every `<w:highlight>`
element produced by the converter, with a counter logged. Highlights
are nearly never legitimate in the fund-document corpus this product
serves; the rare exception can be restored manually.

Recommended order:

1. Land the Compario-side stripper first (fast, zero-risk).
2. Tighten the converter heuristic separately so other consumers of
   `pdf2docx-plus` benefit and so the legitimate highlight case can
   be re-enabled selectively.

---

### Issue P2 — Fee-table cells dropped for rightmost columns **[H]**

**Symptom.** In the Bosera fee table (Litera reference `tbl[7]`,
`tbl[10]`, `tbl[8]`):

- Litera-source OLD DOCX, row 2:
  `Up to 6% | Not applicable | Up to 3% | Not applicable | Not applicable | Not applicable | Not applicable`.
- Our pdf2docx-converted OLD DOCX, same row:
  `Up to 6% | Not applicable | Up to 3% | Not applicable | "" | "" | ""`.

Compario can't diff cells whose old text is empty; the column-wise
deletions Litera correctly captures ("Not applicable", "Included in
Other Fees", "Up to 0.05 %") therefore go missing in our redline.

**Root cause.** `pdf2docx-plus` table extraction aggregates cell text
based on text-block bbox containment. When a row contains visually
empty cells in the rightmost columns (or cells whose text is centred
outside the inferred cell bbox by ≥ 2 pt), the extractor returns an
empty cell.

**Fix (preferred — in pdf2docx-plus).** Loosen `Cell.contains` in
`_vendored/pdf2docx/table/Cell.py` to use the cell's grid bbox
expanded by `+1 pt` on each side AND treat text-clusters whose centre
is inside the cell as cell content, even if glyph runs cross the
boundary.

**Fix (safe short-term — in Compario `pdf_normalizer.py`).** Add a
`_recover_empty_table_cells` post-conversion pass that re-opens the
PDF via `pymupdf`, looks up the cell grid bbox per
`pdf2docx-plus`-emitted metadata, and re-extracts glyphs within the
cell bbox + 1 pt margin. Insert the recovered text as a single run
with the surrounding style snapshot.

Recommended order:

1. Land the Compario-side recovery first (works regardless of
   converter version).
2. Push the converter-side fix later as a permanent improvement.

---

### Issue P3 — Logical tables consolidated into mega-tables **[H]**

**Symptom.** Reference Old DOCX (manual source for Litera) has 10
tables. Our `pdf2docx-plus` output has 4 tables for OLD, 3 for NEW.
The 4-vs-3 imbalance alone makes `_diff_tables` align tables with the
wrong counterparts; even after the per-cell diff runs, the result is
noise.

**Root cause.** `pdf2docx-plus`'s `_merge_cross_page_tables` and the
"pseudo-table" promoter in `_vendored/pdf2docx/page/Pages.py`
aggressively merge logically distinct tables that share a column grid
on adjacent pages (or even within a single page). The fund-prospectus
layout has multiple fee tables stacked vertically with identical
column grids — these get merged into one mega-table.

**Fix (preferred — in pdf2docx-plus).**

1. In `_merge_cross_page_tables`, require the **first row** of the
   second table to be a clear continuation (i.e., **not** a header-row
   signature like `["Fee", "What you pay"]`). Detect headers by
   checking whether the row's contents repeat the previous table's
   header row.
2. Add a new pass `_split_visually_separated_tables` that scans
   adjacent rows in a table for a > 24 pt vertical gap or an
   intervening page-break / heading-paragraph reference, and
   re-splits the table at that boundary.

**Fix (safe short-term — in Compario `pdf_normalizer.py`).** The same
two passes can be added downstream, working on the emitted DOCX:

- Detect header-row repetition inside a single `<w:tbl>` and split.
- Detect rows where the cell-paragraph indent jumps by > 24 pt
  (proxy for vertical gap) and split.

**Risk.** Splitting can regress prior fixes for FAQ / SFT / TRS where
correct *merging* was the goal. Mitigate with regression fixtures
(see §4).

---

### Issue P4 — Section count divergence (14 OLD vs 17 NEW) **[L]**

**Symptom.** Bosera OLD / NEW normalizer logs report `sections=14` and
`sections=17`. The post-conversion `flatten_sections` step doesn't
fully equalise. This contributes to header / footer matching drift in
downstream Compario chrome handling.

**Root cause.** `pdf2docx-plus` emits `<w:sectPr>` boundaries based on
visual cues (multi-column areas, orientation changes). Identical
logical layouts produce different `<w:sectPr>` counts when the PDFs
differ slightly in page count or column wrapping.

**Fix (preferred — in pdf2docx-plus).** Make section emission
deterministic on logical structure only: one section per
"multi-column block" change AND one per page-orientation change. Drop
the per-page section emission when no layout property changes.

**Fix (safe short-term — in Compario `pdf_normalizer.py`).** Tighten
the existing section flattening so OLD and NEW land on the same
section count when they have the same logical sections (collapse
empty single-page sections).

---

### Issue P5 — Spurious checkbox-glyph drift across pages **[L]**

**Symptom.** UT PDF uses `□` / `☐` / `▣` for checkboxes. `pdf2docx-plus`
maps them to different Unicode characters depending on which Symbol-
mapped font face the glyph was sourced from. The diff sees
character-level differences when the user intent was a uniform "empty
checkbox".

**Root cause.** Font-to-Unicode mapping fallback in
`pdf2docx-plus`'s text-extraction layer.

**Fix.** Either:

- **In pdf2docx-plus.** Add a canonical Symbol-font normalisation
  table mapping all `\uF0XX` private-use glyphs that visually render
  as checkboxes to `□` (`□`).
- **In Compario `pdf_normalizer.py`.** Same mapping applied after
  conversion. Same effect; simpler to ship.

Recommended: ship it Compario-side and submit the canonical table to
pdf2docx-plus as a follow-up.

---

### Issue P6 — Item-lists promoted to spurious single-cell tables (joint with Compario C2) **[H]**

**Symptom.** A bullet-style item-list in the OLD Bosera PDF — the
"(ii) in the case of Government and other Public Securities…" run —
arrives in the converted DOCX as a **1-row × 1-column table** with the
entire list text inside one `<w:tc>`. In the NEW PDF the same text is
emitted as a body paragraph. Downstream this looks like a wholesale
delete on the OLD side + a wholesale insert on the NEW side, even
though the text is unchanged. Litera correctly classifies it as equal.

**Root cause.** `pdf2docx-plus`'s pseudo-table promoter (see
`_vendored/pdf2docx/page/Pages.py`, `_vendored/pdf2docx/table/`) is
willing to wrap a single text-block region in a 1×1 table when it
detects what looks like a border or indent guide. On many fund
prospectuses these "borders" are non-printing PDF guides (indent
markers, paragraph rules) rather than real table borders. Same
content + different PDF rendering on OLD vs NEW => one side gets the
phantom table, the other doesn't.

**Joint context.** Compario plan **Issue C2** patches the comparison
side so it can recover even when the converter produces this
asymmetry. P6 is the upstream proper fix — if the converter doesn't
promote in the first place, there's nothing to recover from.

**Fix (preferred — in pdf2docx-plus).** Tighten the pseudo-table
promotion heuristic:

1. Refuse to promote a region to a table when it has exactly one cell
   AND that cell's content is plain flowing text (no internal
   tab-stops, no internal column structure).
2. Require at least one of: (a) ≥ 2 cells in either axis, (b) a real
   stroked border (line width ≥ 0.5 pt, opaque colour) on at least
   three sides, (c) explicit `/Table` structure tag in the PDF's
   structure tree.
3. When refused, emit the content as ordinary body paragraphs with
   appropriate indent/spacing preserved.

**Fix (safe short-term — in Compario, already in plan as C2).** Demote
1×1 pseudo-tables containing > 80 chars of flowing text back to body
paragraphs before diffing, and drop the `_TBL_MIN_ROWS = 2` floor in
`_cross_match_paragraphs_and_tables`.

**Verification.** After the upstream fix, the Bosera OLD converted
DOCX should have the "(ii) in the case of Government…" content as a
body paragraph (or paragraphs), not a `<w:tbl>`. Bosera's
`extra_deletes` and `extra_inserts` lists in
`/tmp/compario_analysis/bosera_diff.json` should drop the
"(ii) in the case of Government…", "assets", "Sub-Fund.", "Class T",
"12.7", "17.5" entries even with C2 unfixed.

---

## 3. Fix Plan (Sprint-Ordered)

> Stages are independent. Each is shippable on its own and can be
> deferred. Items marked **(downstream)** ship as a Compario-side
> sanitiser in `pdf_normalizer.py` — easiest first step. Items marked
> **(upstream)** are the proper fix inside the `pdf2docx-plus` fork.

### Stage P-1 — Downstream sanitisers (Issues P1, P5) **(downstream)**

**Days:** 0.5
**Risk:** Very low — additive normalizer passes that we can audit
before shipping.

1. Add `_strip_phantom_highlights(root)` to `pdf_normalizer.py`. Strip
   every `<w:highlight>` element. Count to log.
2. Add `_canonicalise_checkbox_glyphs(root)` that maps
   `▣ ☑ ☒ ◻ ☐` and similar to `□` so they compare cleanly.

### Stage P-2 — Empty-cell recovery (Issue P2) **(downstream)**

**Days:** 1.5
**Risk:** Medium — depends on `pdf2docx-plus` exposing cell bbox
metadata reliably. If it doesn't, fall back to a PyMuPDF re-extract.

1. Add `_recover_empty_table_cells(root, source_pdf_bytes)` to
   `pdf_normalizer.py`. For each table:
   - Locate the corresponding table region in the source PDF via the
     page/row layout metadata pdf2docx-plus exposes
     (`Table.page_idx`, `Cell.bbox`). If those aren't surfaced,
     re-open the PDF via `pymupdf` and reconstruct the grid.
   - For each empty cell, re-extract glyphs within the cell bbox
     + 1 pt margin. Insert the recovered text as a single run with
     the surrounding style snapshot.

### Stage P-3 — Table splitting (Issue P3) **(downstream first, then upstream)**

**Days:** 2
**Risk:** Medium — risks regressing FAQ / SFT / TRS table handling.

1. **Downstream first.** Add `_split_visually_separated_tables(root)`
   to `pdf_normalizer.py`:
   - Scan each `<w:tbl>` for header-row repetition. Split at the
     repeated header.
   - Scan for cell-paragraph indent jumps > 24 pt (proxy for
     vertical gap) and split.
2. **Upstream proper fix.** In `pdf2docx-plus`'s
   `_merge_cross_page_tables`, refuse to merge when the second table's
   first row matches the first table's header signature. Add
   `_split_visually_separated_tables` as a new step in the page-layout
   pipeline.

Land the downstream pass first; submit the upstream PR after the
regression fixtures (see §4) are green.

### Stage P-4 — Section equalisation (Issue P4) **(downstream)**

**Days:** 0.5
**Risk:** Low — affects only header/footer reporting.

1. Tighten `pdf_normalizer.py`'s section flattening to collapse
   empty single-page sections so OLD and NEW land on the same
   section count when their logical sections are the same.

### Stage P-5 — Upstream highlight detector (Issue P1, follow-up) **(upstream)**

**Days:** 1
**Risk:** Medium — touches widely-used `pdf2docx-plus` heuristics.

1. In `_vendored/pdf2docx/shape/Shape.py` `_parse_semantic_type`,
   require fill-area-to-text-bbox overlap ≥ 70 % AND HSV saturation
   > 0.4 to classify as highlight. Otherwise treat as decorative.
2. Add a fixture-based unit test in `pdf2docx-plus` covering a fund
   prospectus with no highlights and confirming zero
   `<w:highlight>` runs in the output.

This stage is optional from Compario's perspective once Stage P-1
ships, but it's the "correct fix" and pays back the next time
someone in the ecosystem reuses `pdf2docx-plus`.

### Stage P-6 — Pseudo-table promotion heuristic (Issue P6) **(upstream)**

**Days:** 1.5
**Risk:** Medium — touches the table-detection heuristic that also
governs legitimate borderless tables.

1. In the pseudo-table promotion path (`_vendored/pdf2docx/table/`,
   `_vendored/pdf2docx/page/Pages.py`), refuse to wrap a single-cell
   region in a `<w:tbl>` when its content is plain flowing text and
   none of the strict-table signals are present:
   - ≥ 2 cells in either axis, OR
   - real stroked border (line width ≥ 0.5 pt) on ≥ 3 sides, OR
   - explicit `/Table` structure tag in the PDF's structure tree.
2. When refused, emit as ordinary body paragraphs preserving indent
   and spacing.
3. Add a fixture: a PDF page containing an indented item-list with
   non-printing guide rules; output must have zero tables.

This stage is the upstream complement to Compario plan **Issue C2**.
Either fix alone closes the gap; both fix it permanently.

---

## 4. Regression Strategy ("Don't Break What Works")

### 4.1 Compario-side fixtures (for downstream sanitisers)

Add to `Backend/tests/fixtures/conversion/`:

| Stage | New fixture | What it asserts |
|---|---|---|
| P-1 | `pdf_with_phantom_highlights.pdf` | Output DOCX has zero `<w:highlight>`. |
| P-1 | `pdf_with_checkboxes.pdf` | All checkbox glyphs canonicalise to `□`. |
| P-2 | `bosera_fee_table_old.pdf` | After conversion + normaliser, no empty cells in fee-row text columns. |
| P-3 | `bosera_split_tables.pdf` | Tables remain split (≥ 8 tables in OLD). |
| P-3 | `faq_merged_table_preserved.pdf` | Existing cross-page FAQ merge still works (regression guard). |
| P-4 | `bosera_section_count_match.pdf` | OLD and NEW land on the same section count. |

### 4.2 Upstream fixtures (for pdf2docx-plus PRs)

Add to `pdf2docx-plus/tests/`:

| Stage | New fixture | What it asserts |
|---|---|---|
| P-3 | `tests/fixtures/stacked_fee_tables.pdf` | Output has separate tables, not merged. |
| P-5 | `tests/fixtures/prospectus_no_highlights.pdf` | Output has zero `<w:highlight>`. |
| P-5 | `tests/fixtures/real_yellow_highlight.pdf` | Output preserves the legitimate highlight (proves the heuristic still works). |
| P-6 | `tests/fixtures/indented_item_list.pdf` | Output has zero tables for the indented item-list region. |
| P-6 | `tests/fixtures/borderless_real_table.pdf` | Output still emits a `<w:tbl>` for a borderless ≥ 2-cell table (regression guard for the heuristic). |

### 4.3 Memory-tracked invariants

The Compario `MEMORY.md` records a high-leverage fix:

- **PDF FAQ cross-page table merge** — `pdf_normalizer.py`'s
  `_merge_cross_page_tables` must continue to reunify the FAQ tables
  that pdf2docx emits per-page. Stage P-3's splitting heuristics must
  NOT regress this. The regression fixture
  `faq_merged_table_preserved.pdf` is the guard.

Before merge of P-3, also re-run:

```bash
cd Backend
.venv/bin/pytest tests/ -x -k 'table or merge or pdf'
```

---

## 5. Validation Workflow

For each stage:

1. Re-run `python /tmp/compario_analysis/run_bosera.py` and
   `python /tmp/compario_analysis/run_ut.py`.
2. Inspect the converted DOCX intermediates at
   `/tmp/compario_analysis/bosera_{old,new}_converted.docx` to
   confirm the converter's output now matches the expected scaffold.
3. Re-run `python /tmp/compario_analysis/sidebyside.py
   --litera /tmp/compario_analysis/litera_bosera.json
   --compario /tmp/compario_analysis/compario_bosera.json
   --out /tmp/compario_analysis/bosera_diff.json`.
4. Compare new metrics to the table at the top of this document.
5. Spot-check redline DOCXs at
   `/tmp/compario_analysis/{bosera,ut}_compario_redline.docx`.

---

## 6. Out of Scope (Tracked, Not Planned)

- Re-architecting `pdf2docx-plus`'s table extraction (column inference
  algorithm replacement). The fixes above are local heuristic tuning.
- OCR-quality improvements for image-only pages (handled separately
  by Compario's `pdf_ocr_fallback.py`).
- Vector-graphic to drawing conversion for charts (covered by the
  existing `pdf_image_diff` flow, which is Compario-side).
- Compario-side issues — see [`PDF_FIDELITY_COMPARIO_PLAN.md`](./PDF_FIDELITY_COMPARIO_PLAN.md).

---

## 7. Appendix — Reproducer artefacts

All artefacts from the analysis live in `/tmp/compario_analysis/`:

| File | Purpose |
|---|---|
| `run_bosera.py` | End-to-end Bosera PDF → redline. |
| `bosera_old_converted.docx`, `bosera_new_converted.docx` | `pdf2docx-plus` output (the surface this plan targets). |
| `extract_redline.py` | Extract per-paragraph inserts/deletes from any DOCX. |
| `sidebyside.py` | Compute matched / missing / extra fragment counts and full-doc Jaccard. |
| `litera_bosera.json`, `compario_bosera.json` | Per-paragraph segment data. |
| `bosera_diff.json` | Side-by-side metrics + missing/extra lists. |
| `ut_old_converted.docx`, `ut_new_converted.docx` | UT pipeline conversion outputs. |
