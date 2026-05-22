# Prompt — `pdf2docx-plus` fidelity fixes for the Compario PDF redline pipeline

You are working inside the **forked `pdf2docx-plus`** repository located at:

```
/mnt/NewVolume2/Android Projects/makebell/voedocx/pdf2docx-plus/
```

This converter is consumed by the Compario product to turn PDFs into
DOCX before a redline comparison runs against a second PDF. A
benchmark against a Litera-generated reference revealed defects in
this converter's output that propagate into the final redline as
phantom highlights, dropped table cells, over-merged tables, drifting
section counts, inconsistent checkbox glyphs, and spurious 1×1
pseudo-tables wrapping ordinary item-lists.

## Your single source of truth

Read and follow:

```
/mnt/NewVolume2/Android Projects/makebell/voedocx/pdf2docx-plus/PDF_FIDELITY_PDF2DOCX_PLAN.md
```

That file is the brief. It lists six issues (P1–P6), each with
symptom, root cause, file:line pointers into the vendored
`pdf2docx` tree, and a recommended upstream fix. The plan is split
into stages **P-1 through P-6**.

## Scope (upstream only)

Implement **only the upstream fixes** (the items the plan tags
**(upstream)** or **(downstream first, then upstream)**). Do **not**
touch the Compario codebase. Do **not** ship anything that belongs in
Compario's `pdf_normalizer.py`. The plan already separates those.

In sprint order:

1. **P-5 (upstream highlight detector)** — `_vendored/pdf2docx/shape/Shape.py` `_parse_semantic_type`.
2. **P-3 (table-split / refuse-to-merge)** — `_vendored/pdf2docx`'s `_merge_cross_page_tables` and add `_split_visually_separated_tables` to the page-layout pipeline.
3. **P-6 (pseudo-table promotion heuristic)** — `_vendored/pdf2docx/table/` and `_vendored/pdf2docx/page/Pages.py`.
4. **P-2 upstream half** — loosen `Cell.contains` in `_vendored/pdf2docx/table/Cell.py` (the empty-rightmost-cell drop). Compario already has a downstream PyMuPDF re-extract sanitiser planned; the upstream fix is to extract correctly in the first place.
5. **P-4 (deterministic `<w:sectPr>` emission)** — section emission based on logical layout changes only.
6. **P-1 (canonical Symbol-font / checkbox map)** — add to `_vendored/pdf2docx/common/` font fallback. Optional follow-up; ship after the higher-value items land.

You may reorder if you find a different sequence reduces risk, but
P-5 first is recommended because it's the lowest blast radius.

## Test reproducer (use this for every issue)

Convert and inspect:

```bash
cd /mnt/NewVolume2/Android Projects/makebell/voedocx/pdf2docx-plus
# Use whatever venv / harness this fork already uses for its own tests.
python -m pdf2docx_plus convert \
    "/mnt/NewVolume2/Android Projects/makebell/voedocx/Old_KFS_Bosera USD Money Market ETF.pdf" \
    /tmp/bosera_old_after.docx
python -m pdf2docx_plus convert \
    "/mnt/NewVolume2/Android Projects/makebell/voedocx/New_KFS_Bosera USD Money Market ETF.pdf" \
    /tmp/bosera_new_after.docx
```

Then run these diagnostics on each output:

- **P1/P5 highlights:** count `<w:highlight>` elements in
  `word/document.xml`. Baseline before fix: 99 (NEW) and similar (OLD).
  Target: 0 unless the PDF has a real highlighter colour.
- **P2 empty cells:** open the fee table (Litera reference `tbl[7]`,
  `tbl[10]`, `tbl[8]` of `DV_KFS_Bosera USD Money Market ETF.docx`).
  Every row's Class IF / Class Z columns should have text content,
  not empty `<w:tc>`.
- **P3 / P6 table counts:** the reference clean source (Litera's
  pre-redline input) has 10 tables on OLD and a similar count on NEW.
  Current converter output: 4 (OLD), 3 (NEW). Target after P-3 + P-6:
  ≥ 8 tables on OLD and an OLD/NEW table count that aligns row-by-row
  with the reference.
- **P4 section counts:** check `<w:sectPr>` count in OLD vs NEW.
  Baseline: 14 vs 17. Target: equal when the PDFs have the same
  logical sections.
- **P6 item-list pseudo-table:** search the OLD converted DOCX for the
  string "(ii) in the case of Government and other Public Securities".
  Baseline: it lives inside a 1-row × 1-column `<w:tbl>`. Target:
  it's a body paragraph (or a sequence of body paragraphs).

## Required regression coverage

The plan calls for these new fixtures inside this repo. Add them as
part of the work:

- `tests/fixtures/prospectus_no_highlights.pdf` — produces zero
  `<w:highlight>`. (P5)
- `tests/fixtures/real_yellow_highlight.pdf` — preserves the
  legitimate highlight. **Required** so P-5 doesn't regress real
  highlights. (P5)
- `tests/fixtures/stacked_fee_tables.pdf` — separate tables, not
  merged. (P3)
- `tests/fixtures/indented_item_list.pdf` — zero tables for an
  indented item-list with non-printing guide rules. (P6)
- `tests/fixtures/borderless_real_table.pdf` — still emits a
  `<w:tbl>` for a borderless ≥ 2-cell table. **Required** so P-6
  doesn't kill legitimate borderless tables. (P6)
- Plus the existing FAQ cross-page merge fixture (already in the
  Compario corpus) must still produce a merged table. The Compario
  memory log calls this out as a high-leverage invariant; if your
  P-3 split heuristic ever splits the FAQ table, revert and rethink.

Write the tests **before** the implementation when feasible. Existing
`pdf2docx-plus` test conventions (pytest under `tests/`) apply.

## Verification loop (run after every issue, not just at the end)

1. Implement the fix for one issue at a time.
2. Run the targeted new fixture test(s) for that issue.
3. Run the full repo test suite. **Nothing previously green may go red.**
4. Re-run the Bosera reproducer above and check the relevant
   diagnostic above. Record the before/after numbers.
5. Repeat for the next issue.

Do not move on to the next issue until the previous one's diagnostic
hits the target AND the full test suite is green.

## What to deliver

For each issue:

- A focused commit (or commit series) in the local branch with the
  fix and its fixture(s).
- A short note in the commit body listing the diagnostic
  before/after numbers (e.g., "highlight runs in Bosera NEW:
  99 → 0").
- At the end, a final summary message that states, per issue:
  - Status (done / partial / skipped + reason)
  - Files touched
  - Diagnostic delta on the Bosera reproducer
  - Any new fixture file paths
  - Any deviations from the plan and why

## Important constraints

- **Do not push.** Work on a local branch (create one off the
  current `HEAD`, e.g., `fidelity/p1-through-p6`). No
  `git push`, no PR creation, no remote interaction at all. The
  user will review locally and push themselves.
- **Do not skip hooks.** No `--no-verify`. If a pre-commit fails,
  fix the underlying issue.
- **Do not amend pushed commits.** Always create new commits.
- **No upstream interaction.** This is a fork. Do not try to file
  PRs against the original `pdf2docx`. Changes stay in the fork.
- **No Compario edits.** If you spot a Compario-side problem,
  mention it in the final summary; do not patch it from this repo.
- **Stay inside the issue scope.** Do not refactor unrelated areas
  of `pdf2docx-plus`, do not bump dependencies, do not "tidy" code
  in passing.

## If a fix is harder than the plan suggests

If after a reasonable attempt an upstream fix turns out to be
much riskier than the plan estimates:

1. Stop work on that issue.
2. Leave the existing behaviour intact.
3. Note it in the final summary with: what you tried, what broke,
   what an alternative path looks like (could be "punt to the
   downstream Compario sanitiser permanently").

Better to ship 4 solid issues than 6 shaky ones.
