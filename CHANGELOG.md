# Changelog

## Unreleased

### Added

- New post-emit pass `repair_wrap_spacing()` in
  `pdf2docx_plus.emit.word_spacing`. When upstream concatenates text
  spans from lines that wrapped in the source PDF, the trailing
  space at the line break is dropped, yielding word-glue like
  ``"confirms,having"`` and ``"Sub-Fund.The"``. The new pass walks
  every paragraph (including table cells), inspects adjacent
  ``<w:r>`` siblings, and inserts a single space when the left run
  ends with sentence-break punctuation (``,;:?!)`` or a word-ending
  period) and the right run begins with a letter. Single-letter
  initials (``U.S.``, ``e.g.``), mid-word hyphens, runs separated by
  explicit ``<w:br/>``/``<w:tab/>``, and runs already bracketed by
  whitespace are preserved. Gated by the new
  `repair_soft_wrap_spacing` flag on `convert()` (default True).
  `ConversionResult` now reports `wrap_spaces_repaired`. Measured
  impact on First Sentier PDFs (58- and 59-page funds): 27 real
  word-glue repairs, five period-glue and two comma-glue defects
  eliminated, zero ``U.S.`` / ``e.g.`` false positives.
- New post-emit pass `promote_page_numbers_to_footer()` in
  `pdf2docx_plus.emit.page_footer`. Detects per-page footer body text
  (``"N Last update: ..."``, bare page-number paragraphs, and
  repeated footer lines) and rewrites them into a real ``w:footer``
  with a right-aligned auto-updating ``PAGE`` field. Gated by the new
  `promote_page_footer` flag on `convert()` (default True).
  `ConversionResult` now reports `page_footer_lines_promoted`.
- New post-emit pass `flatten_per_page_sections()` in
  `pdf2docx_plus.emit.sections`. Converts upstream's per-source-page
  `nextPage` section breaks to `continuous` so Word repaginates
  naturally. Wired into the pipeline behind the new `flatten_sections`
  flag on `convert()` (**default `False`** — preserves source page
  boundaries; opt in for content packing). Skipped automatically when
  any section carries a `headerReference`/`footerReference` or when
  page sizes vary across sections (landscape/portrait mix).
  `ConversionResult` now reports `sections_flattened`.
- Post-emit passes `drop_empty_tables()` and `trim_empty_table_rows()`
  in `pdf2docx_plus.emit.tables_cleanup`. Run before
  `merge_consecutive_single_row_tables` / `unwrap_tiny_tables` when
  `cleanup_tiny_tables=True`. `ConversionResult` now reports
  `empty_tables_dropped` and `empty_table_rows_trimmed`.

### Changed

- `clamp_paragraph_spacing()` default `max_twips` lowered from 2400
  (~120pt) to 480 (~24pt = 2 lines). Upstream encodes inter-block
  vertical gaps measured in the source PDF as `w:before` / `w:after`;
  with font substitution these inflated values push content past
  per-page section boundaries, costing a full page each. The new cap
  preserves typical paragraph break spacing while cutting the
  pathological values that drive page-count overflow.

### Fixed

- **Page numbers appeared as static inline body text instead of in
  the footer.** Upstream emits the per-page footer line as a plain
  body paragraph on every source page, so ``"1"``, ``"2"``, ... never
  update when the DOCX repaginates, and ``"Last update: 2 October
  2024"`` is duplicated 67× in the body. The new
  `promote_page_numbers_to_footer` pass strips those body paragraphs
  and injects a proper footer with a right-aligned ``PAGE`` field.
- **Page-count inflation from per-page section breaks.** Upstream
  emits one `<w:sectPr>` per source PDF page with default `nextPage`
  break type. When font substitution shifts text by a few millimetres,
  content overflows its tight per-page section and the next section's
  hard page break still fires — costing a full page per overflow. The
  new `flatten_per_page_sections` pass downgrades these mid-document
  breaks to `continuous`, letting Word repaginate naturally so the
  rendered page count tracks actual content length.
- **Empty tables from detected checkbox grids and stroke artifacts.**
  pdf2docx's lattice detector correctly identifies drawn rectangles
  (empty checkbox columns, underline strokes, marginalia boxes) as
  bordered tables, but content extraction leaves every cell blank —
  producing mysterious empty bordered grids in the DOCX. The new
  `drop_empty_tables` pass removes tables where every cell has no
  text, image, or drawing; `trim_empty_table_rows` strips leading and
  trailing all-blank rows from sparse tables while preserving interior
  blank rows. Genuine data tables with sparse content are untouched.
- **Spurious tables on borderless pages.** The `fidelity` (default) and
  `fast` profiles no longer enable upstream's `parse_stream_table`
  detector, which inferred tables from text alignment alone and
  fabricated tables around multi-column layouts, aligned label/value
  blocks, and spec lists even when the source PDF had no visible
  borders or shading. Stream-table detection is now opt-in via the
  `semantic` profile or `extra_settings={"parse_stream_table": True}`.
  Lattice (bordered) table detection is unchanged. `extract_tables()`
  continues to run stream detection since that is its purpose.

## 0.6.0a3 (unreleased)

Roadmap milestones M1, M2 (partial), M3 (partial), M4 (detection), M5
(partial), M6, M7 executed. Exit targets (TEDS ≥ 0.85, Kendall-tau ≥ 0.85)
still require the annotated corpus from M1 to be populated; the
infrastructure is now in place.

### Added

- `pdf2docx_plus/styles/` installs a full style inventory (Normal,
  Heading 1-6, Title, Subtitle, Caption, Quote, List Paragraph, Hyperlink)
  on every emitted Document. Output no longer opens in Word
  "Compatibility Mode".
- `pdf2docx_plus/layout/hf_detect.py`: repeated-region detection that
  flags header/footer TextBlocks across the document.
- `pdf2docx_plus/layout/lists.py`: bullet / decimal / alpha / roman list
  marker detection (`detect_list_block`, `normalise_list_blocks`). Tags
  blocks for downstream `w:numPr` emission.
- `pdf2docx_plus/layout/scanned.py`: text-density + image-area
  heuristic that flags scanned pages. `ConversionResult.scanned_pages`
  carries the flagged indices and adds a warning when no OCR engine is
  registered.
- `pdf2docx_plus/tables/stitch.py`: cross-page table continuation
  stitcher (col-count + x-overlap + page-edge tolerance + repeated-header
  detection).
- `pdf2docx_plus/tables/float_images.py`: suppresses `ImageBlock`
  promotion to page level when fully contained in a table cell
  (upstream #299).
- `pdf2docx_plus/consolidate.py`: post-emit pass that merges adjacent
  `<w:r>` elements with identical `rPr`. Cut 2182 runs across the seed
  corpus in the smoke run (typical: -20% runs per paragraph).
- `ConversionResult` now reports: `scanned_pages`,
  `stitched_table_pairs`, `runs_merged`, `demoted_floating_images`,
  `lists_detected`, `headers_footers_detected`, `peak_rss_mb`,
  `pages_per_second`.

### Changed

- `bench.metrics.text_f1` is now **word-level** (bag-of-words with
  case-folding + punctuation strip). The old character-frequency F1
  lives on as `text_char_f1` for back-compat.
- Added `bench.metrics.text_char_accuracy` (Levenshtein-based, bounded
  input 5000 chars).
- `editability` is a composite (run style + paragraph style + run
  density).
- Bench summary table now emits pages/s, peak RSS, runs_merged, lists
  detected, headers/footers detected, stitched table pairs.

### Fixed

- `_resolve_output` handles directory / `.` / trailing-slash outputs
  by deriving the filename from the input PDF stem (fixed in prior
  patch release; consolidated here).

## 0.6.0a1 (unreleased)

Initial fork from upstream `pdf2docx` 0.5.12.

### Added

- `pdf2docx_plus` public package with typed API (`Converter`, `convert`,
  `extract_tables`, `ConversionResult`, `PageResult`).
- Structured exception hierarchy: `ConversionError` / `InputError` /
  `ParseError` / `MakeDocxError` / `PasswordRequired` / `TimeoutExceeded` /
  `PluginError`.
- Context-manager `Converter` that always closes the fitz document.
- `timeout_s=` watchdog on `Converter.convert`.
- `continue_on_error=` flag with per-page accounting in `ConversionResult`.
- Profiles: `fast`, `fidelity` (default), `semantic`.
- Plugin architecture (`pdf2docx_plus.plugins`) with `TableDetector`,
  `LayoutDetector`, `OcrEngine`, `FormulaRecognizer` protocols.
- Optional ML hooks (`pdf2docx_plus.hooks`): Table Transformer,
  Granite-Docling, PaddleOCR, pix2tex, UniMERNet stub.
- FastAPI REST server at `pdf2docx_plus.server` (extra: `rest`).
- Modern CLI via Fire: `convert`, `extract-tables`, `serve`, `version`.
- Benchmark harness under `bench/` with text F1, TEDS, Kendall-tau, SSIM,
  editability metrics and regression-gate runner.
- `pyproject.toml` (hatchling), Python 3.11 / 3.12 / 3.13 classifiers.
- `py.typed` marker for downstream type-checking.
- `ruff`, `mypy`, `pytest`, `pre-commit`, GitHub Actions CI workflow.
- `LICENSING.md` documenting the AGPL (PyMuPDF) path and future
  `pypdfium2` migration.

### Fixed (vs upstream)

- `add_hyperlink`: emit OOXML-valid `<w:hyperlink>` at paragraph level
  instead of nesting inside `<w:r>` (upstream #369 / #371). Eliminates
  Word "Compatibility Mode" warnings and spurious double-underlines.
- XML-1.0 invalid control chars (including NUL) stripped before text reaches
  `<w:t>` nodes, preventing corrupt DOCX output (upstream #324).
- ANSI escape codes suppressed in log messages when stderr is not a TTY
  (cleaner CI / journal output).
- Explicit `gc.collect()` between pages reduces peak RSS on large docs
  (mitigates #301).

### Not yet addressed

See README "What's NOT done yet". Phase 2 (ML tables + layout), Phase 3
(math + OCR), Phase 4 (style system + full REST), Phase 5 (release) remain.
