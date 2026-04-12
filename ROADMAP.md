# pdf2docx-plus — Roadmap to v1.0

Follow-up plan for everything *not* covered in the initial `0.6.0a1` fork.
Each milestone is sized so a single developer (or agent) can pick it up
without re-reading the original 21-week plan.

> **Entry state (now):** Phase 0 + most of Phase 1 done. 30 tests green, 76
> pages convert at ~2.9 pg/s on CPU, plugin surface + ML hooks stubbed,
> PyMuPDF (AGPL) still the parse backend. See `README.md` "What's NOT done
> yet" for the source-of-truth gap list.

> **Exit criteria (v1.0):** from `PDF2DOCX_FORK_PLAN.md` §8 —
> text F1 ≥ 0.98, TEDS ≥ 0.90, Kendall-tau ≥ 0.90, 0 crashes, ≥ 2 pg/s CPU,
> peak RSS < 2 GB on 500-page doc, opens in Word 365 + LibreOffice 7+.

---

## Milestone M1 — Benchmark corpus & ground truth (1–2 weeks)

Nothing else is measurable without this. Do this first.

1. **Collect 100 PDFs** across the categories named in the plan:
   academic papers (15), scanned books (10), magazines (10), contracts (10),
   financial reports / KFS (15), government forms (10), CJK docs (10),
   RTL docs (5), math-heavy (10), table-heavy (5).
2. **Annotate ground truth.** For each doc, store in
   `bench/corpus/<name>/`:
   - `input.pdf`
   - `expected_text.txt` — canonical text, either from the publisher's
     source or from a manual pass. Use `pdftotext -layout` as a first pass
     and hand-correct.
   - `expected_tables.json` — `list[list[list[str]]]`. Use the web tool
     `Tabula` for the initial extraction, hand-correct.
   - `expected_order.json` — block reading order as a list of block IDs
     (produce IDs by running the current pipeline once and dumping them).
3. **Replace the character-frequency F1** with a proper word-level F1 or
   edit-distance-based score (bag-of-chars is too lenient — see
   `first_sentier` scoring 1.000 in the current run).
4. **Wire the bench runner into CI** with the `--fail-on-regression 2`
   gate so every PR is scored against the previous main.

Deliverable: `bench/reports/baseline.json` with real metrics for the
current `0.6.0a1` release.

---

## Milestone M2 — Real table quality (2–3 weeks)

Plan §B.6–10.

1. **Wire Table Transformer into the page loop.** The hook already exists
   (`pdf2docx_plus.hooks.TableTransformerDetector`), but the core pipeline
   in `pdf2docx/page/RawPage.py` never asks it. Add a call site where
   table regions from registered detectors are merged with the ruling-line
   lattice output, with the voting heuristic: prefer ML when ruling count
   < 2 per 100 sq in.
2. **Structure recognition pass.** Extend the hook to run TATR's v1.1
   structure model on each detected region and emit cell bounding boxes,
   row/col counts, `vMerge` / `gridSpan` flags.
3. **Cross-page stitching.** New module `pdf2docx_plus/tables/stitch.py`.
   Detect continuation by: (a) same col count, (b) x-position overlap > 0.9,
   (c) last-row bottom within 30pt of page bottom, (d) optional repeated
   header row. Merge into a single `TableBlock` with spanning rows.
4. **Floating images in cells** (upstream #299). Stop promoting
   `ImageBlock` to the page-level Blocks list when it's fully enclosed in a
   cell's bbox.
5. **Tables → CSV side output** — already wired in the CLI; just needs an
   integration test and a bench metric.

Exit: TEDS ≥ 0.85 on the annotated corpus (up from ~0.70 upstream).

---

## Milestone M3 — Layout & reading order (2 weeks)

Plan §C.11–16.

1. **Plumb `LayoutDetector` results into the Blocks reordering step** in
   `pdf2docx/layout/Blocks.py`. If a detector is registered, its block
   types win over the heuristic; the XY-cut still runs as fallback for
   pages the detector abstains on.
2. **Granite-Docling integration.** Flesh out
   `hooks/layout_detection.py::GraniteDoclingLayoutDetector.detect()`.
   Parse its DocTag output into `LayoutBlock` objects.
3. **Header / footer → `w:hdr` / `w:ftr`.** New module
   `pdf2docx_plus/hf_detect.py`. For each page in the doc, compute the
   repeat region (same bbox ± 3pt on ≥ 30% of pages). Assign to the
   section header/footer via `python-docx`.
4. **Lists & numbering.** Detect bullet patterns (`•`, `-`, `*`,
   `\d+\.`, `[a-z]\)`, ...) in `TextBlock` first-line spans. Emit with
   `w:numPr` + `w:abstractNum`. Helper: `pdf2docx_plus/lists.py`.
5. **Footnotes.** Superscript ref + bottom-of-page candidate block +
   matching body ref → emit as OOXML `w:footnote`. Helper:
   `pdf2docx_plus/footnotes.py`.
6. **Forced page breaks.** In the DOCX emitter, insert `w:br w:type="page"`
   only when the original PDF had an explicit page break, never
   mid-paragraph (fixes #321).

Exit: Kendall-tau ≥ 0.85, manual spot-check 5 multi-column papers.

---

## Milestone M4 — OCR & scanned PDFs (1–2 weeks)

Plan §G.25–26.

1. **Auto-detect scanned pages.** Heuristic: `len(page.get_text().strip())
   / page.get_pixmap().width` < 0.001 → scanned. Per-page, not per-doc.
2. **OCR routing.** When scanned AND a registered `OcrEngine` exists,
   feed the page pixmap through `engine.recognize(image)` and synthesise
   a `TextBlock` covering the page content box. Position-aware OCR (per
   word) is out of scope here — belongs in M5.
3. **PaddleOCR quality pass.** Add a small benchmark sub-corpus of 10
   scanned PDFs and assert text F1 ≥ 0.85 with `PaddleOcrEngine(lang="en")`.

Exit: pipeline no longer emits empty DOCX for scanned input.

---

## Milestone M5 — Math, fonts, CJK polish (2 weeks)

Plan §D.17–20, §F.24.

1. **Math region detection → OMML.** Trigger `FormulaRecognizer` when a
   `LayoutDetector` block is labelled `formula`. Replace the `TextBlock`
   with an `OmmlBlock` in the emitter; new module
   `pdf2docx_plus/math.py`. Keep the raw LaTeX as a comment.
2. **Font substitution.** Use `fontTools` to read embedded font metrics,
   fuzzy-match against a system-font index (built on first use, cached
   under `~/.cache/pdf2docx-plus/fonts.json`). Store as `theme1.xml`
   bindings.
3. **Run consolidation.** Collapse runs with identical formatting into
   `w:pStyle` / `w:rStyle` references. Target: editability metric > 0.6
   on the financial corpus.
4. **CJK tokenisation.** Character-level run splitting with Ruby
   passthrough (PDFs with `/ActualText` furigana).
5. **RTL.** Bidi run grouping for Arabic/Hebrew; emit `w:bidi` on
   paragraphs with majority-RTL content.

Exit: editability ≥ 0.6, math-heavy corpus produces rendered formulae
instead of dropped blocks.

---

## Milestone M6 — Output quality, style system (1 week)

Plan §H.27.

1. **styles.xml rewrite.** Emit a full styles part: `Normal`,
   `Heading 1-6`, `Title`, `Quote`, `Caption`, `List Paragraph`,
   `Hyperlink`. Map detected `LayoutBlock.label` → style.
2. **Alt-text from figure captions.** When a layout-detected `figure`
   block sits adjacent to a `caption`, copy the caption text into
   `wp:docPr @descr`.
3. **Track-changes / accessibility tagging** is marked "optional" in
   the plan; treat as stretch.

Exit: opens in Word 365 without "Compatibility Mode" warnings on the
entire corpus.

---

## Milestone M7 — Performance & memory (1 week)

Plan §I.30–33.

1. **Parallel per-page processing.** Already present in upstream via
   `multiprocessing=True`, but the `fitz.Document` can't be forked.
   Rewrite `_convert_with_multi_processing` to spawn fresh workers each
   opening the file themselves. Benchmark on 500-page PDF.
2. **Streaming mode.** `Converter.convert_streaming(output_path)` that
   emits the DOCX page-by-page and never holds all `Page` objects in
   memory. Requires python-docx `save` fix or direct OOXML writing.
3. **Bench metrics for perf.** Add `peak_rss_mb`, `pages_per_second` to
   the report; fail the bench gate on regressions.

Exit: 500-page PDF in < 250s and < 2 GB RSS.

---

## Milestone M8 — pypdfium2 backend (3–4 weeks) — biggest single lever

Plan §6 (the AGPL decision).

This is the one architectural change that unblocks commercial redistribution.
Do it last — after the heuristic improvements above so the test bed is
already rich enough to catch regressions.

1. **Introduce `pdf2docx_plus.backends.Backend` Protocol.** Method surface:
   `open`, `close`, `page_count`, `page_text_blocks`, `page_images`,
   `page_paths`, `page_rect`, `page_rotation`, `render_to_pixmap`.
2. **Port `pdf2docx/page/RawPageFitz.py` one method at a time** to
   `pypdfium2` + `pdfplumber`:
   - text blocks + spans → `pdfplumber.chars` grouped by line.
   - images → `pypdfium2.PdfPage.get_objects` filtered to `FPDF_PAGEOBJ_IMAGE`.
   - paths → `pdfplumber.edges` + `pypdfium2.PdfPath` walks.
   - rendering → `pypdfium2.PdfPage.render(scale=...)` to `PIL.Image`.
3. **Dual-backend CI.** Matrix: `PDF2DOCX_BACKEND=fitz` vs
   `PDF2DOCX_BACKEND=pdfium`. Assert both pass the same bench within 2%.
4. **Flip the default** to `pdfium` in `0.7.0`, ship a flag to revert.
5. **Remove PyMuPDF from core deps** (move to extra `backend-fitz`).
   Update `LICENSING.md` to strike the AGPL section.

Exit: `pip install pdf2docx-plus` is MIT-clean.

---

## Milestone M9 — Release (1 week)

Plan §5.

1. Cut `v1.0.0`. Tag + GitHub release with bench numbers vs upstream +
   Marker + LibreOffice.
2. Docs site (mkdocs-material) with API reference auto-generated from
   the `py.typed` marker.
3. Announcement post (HN / Reddit / r/Python).
4. Publish to PyPI.

---

## Ordering & parallelism

Sequential dependencies:

```
M1 (bench corpus) ── required by ── M2, M3, M4, M5, M6, M7, M8
M2 (tables) ───────────┐
M3 (layout) ───────────┤── all three independent; can run in parallel
M4 (OCR) ──────────────┘
M5 (math/fonts/CJK) ── needs M3 for layout labels
M6 (styles) ── needs M3 (layout labels → style mapping)
M7 (perf) ── independent
M8 (pypdfium2) ── do last; needs M2+M3 stable as a regression bed
M9 (release) ── last
```

Calendar estimate with one full-time dev: **~16 weeks** (vs the
original 21 — we cut dead weight by using existing plugin scaffolding).

---

## Definition of done per milestone

Each milestone is done when:

1. New code has ≥ 80 % test coverage (enforced by `pytest-cov`).
2. `bench/reports/latest.json` on the 100-doc corpus shows the stated
   metric target.
3. `ruff check` + `ruff format --check` + `mypy` are clean.
4. CHANGELOG.md updated.
5. At least one manual round-trip through Word 365 (not just LibreOffice).
