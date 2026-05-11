# Changelog

## Unreleased

### Fixed

- **Inline images forced into ``<wp:anchor>`` instead of ``<wp:inline>``.**
  ``pdf2docx_plus._vendored.pdf2docx.common.docx.add_image`` (the
  function that ``Image.make_docx`` calls for *every* inline image
  span) was rewriting the python-docx default ``<wp:inline>`` into
  ``<wp:anchor>`` with absolute page coordinates. The result was that
  every logo or icon that should flow inline with surrounding text
  instead became a floating overlay anchored to fixed (x, y), which:
  (a) breaks downstream layout since Word cannot reflow anchored
  images, (b) confuses the table detector when an inline image sits in
  a cell, and (c) loses the connection between the image and its
  caption paragraph. New fidelity patch
  ``pdf2docx_plus.fidelity.images`` replaces ``add_image`` with an
  inline implementation (``run.add_picture``) so every image emitted
  by ``Image.make_docx`` / ``ImageSpan.make_docx`` produces
  ``<wp:inline>``. Genuine float images still go through
  ``add_float_image`` and emit ``<wp:anchor>`` exactly as before.
- **Image alt-text (``/Alt``) dropped during extraction.** PDFs with
  accessibility-grade alt-text annotations on raster images saw that
  metadata silently lost - downstream consumers couldn't recover the
  semantic description of a logo or chart. New extractor patch in
  ``pdf2docx_plus.fidelity.images`` scans the page content stream for
  ``/Alt(...)`` markers and stashes the result on the raw image dict;
  ``Image.make_docx`` then propagates it onto ``<wp:docPr @descr>``.
- **Table fragmentation on documents with per-page header images.**
  The cross-page stitch heuristic in ``pdf2docx_plus.tables.stitch``
  used to require the last table to end within 30pt of the page
  bottom AND the first table on the next page to start within 30pt
  of the page top. Documents that stamp a header image (and / or a
  ``Last update`` footer) on every page never satisfied that
  constraint, so a Q&A list that visually spans 42 pages was emitted
  as 42 separate ``<w:tbl>`` blocks. The heuristic now considers an
  expanded definition of "page-edge": (1) image-only blocks are
  transparent, (2) text blocks matching footer / page-number patterns
  are transparent, (3) footnote-style blocks
  (``\d{1,3}\s+\S`` prefix) are transparent, (4) up to 300 chars of
  other ancillary text is tolerated before stitching is rejected.
  Combined with running ``detect_header_footer`` *before* the stitch
  pass and forwarding the detected text as a transparent set, the
  Old_FAQs Compliance document (42 pages) now collapses from 42
  separate tables down to 22 (20 stitched pairs).
- **Intra-table row continuation across page breaks.** When a single
  table row's content wrapped onto the next page, upstream emitted
  the wrap-over as a "mostly-empty row with text in one column" at
  the top of the next table. Previously consumers had to glue these
  back together themselves. ``stitch_cross_page_tables`` now detects
  continuation rows (sparse row B whose non-empty cells are a subset
  of row A's filled cells) and coalesces them by appending row B's
  text to row A's matching cells. ``ConversionResult`` reports
  ``continuation_rows_merged``.
- **Single-marker false-positive list promotion.** ``apply_lists``
  promoted any paragraph starting with ``1.``, ``a)``, or ``•`` even
  when it was a one-off (e.g. a stray reference or section-numbering
  artefact in the body). The pass now requires a run of >= 2
  consecutive same-kind markers AND, for decimal lists, monotonic
  numbering. List detection regex coverage extended to multi-level
  ``1.1.``, paren-style ``(1)`` and roman ``(i)`` markers.
- **Hyphenated compounds at line breaks getting de-hyphenated.**
  Upstream's ``Lines.adjust_last_word`` deletes a trailing ``-`` when
  the next line starts with a lowercase letter, which is correct for
  typesetting wraps (``"informa-"`` + ``"tion"``) but wrong for real
  compounds (``"Sub-Fund"`` -> ``"SubFund"``). New whitelist in
  ``pdf2docx_plus.fidelity.hyphens`` covers common financial / legal
  compounds (``Sub-Fund``, ``non-listed``, ``open-ended``, ...) so
  even users that opt into ``delete_end_line_hyphen=True`` keep
  these intact. The same whitelist also protects against the
  ``repair_wrap_spacing`` pass adding stray whitespace inside the
  hyphen.
- **``promote_page_footer`` overwriting the wrong section's footer in
  multi-section documents.** The previous implementation installed
  the most-frequent "Last update" suffix as the footer for *every*
  section, even sections whose body never carried the pattern. The
  pass is now section-aware: it groups footer paragraphs by section
  bucket, writes per-section footer text, and links consecutive
  sections via ``is_linked_to_previous`` when they share content.
- **``extract_headers_footers_to_section`` only working for
  single-section documents.** The default is now True; the extractor
  walks per-section body buckets, lifts ONE representative paragraph
  per section, and ``is_linked_to_previous``-chains consecutive
  sections that share the same chrome.
- **``fit_wide_tables`` shifting floating-image positions.** The
  column-fit and grid-realignment passes used to rewrite cell widths
  even for tables containing ``<wp:anchor>``-positioned images, which
  knocked the picture off its source location. Both passes now
  detect floating images in the table and degrade gracefully:
  ``align_tblgrid_to_cells`` skips the table entirely;
  ``fit_oversized_tables`` clamps the ``<w:tblInd>`` (to stop the
  table from running past the right margin) but leaves grid and cell
  widths alone.
- **Margin labels emitted as floating text frames.** Rotated
  ``"Confidential"`` / ``"DRAFT"`` style margin labels were emitted
  as anchored text frames that fragmented diffs and confused
  downstream normalisation. New
  ``pdf2docx_plus.layout.margin_labels`` module detects rotated /
  tall-and-narrow text blocks in the page margin and removes them by
  default (``drop_margin_labels_in_body=True``).
- **Run-to-run non-determinism in embedded PNG bytes.** OpenCV's
  ``imencode(".png", ...)`` lets libpng pick the compression level
  and filter strategy adaptively, so the same source image could
  serialise to different bytes across runs (and across CPUs).
  ``pdf2docx_plus.fidelity.determinism`` monkey-patches
  ``cv2.imencode`` to always pass
  ``IMWRITE_PNG_COMPRESSION=6`` and
  ``IMWRITE_PNG_STRATEGY_DEFAULT``. End-to-end check: two
  independent conversions of the same 9-page PDF now produce
  byte-identical DOCX archives across all internal files.
- **Columns rendered at equal widths despite the cells carrying
  non-uniform widths.** Upstream sometimes emits ``<w:tblGrid>``
  with evenly-divided columns even when the underlying cells
  declare correct, non-uniform widths via ``<w:tcW w:type="dxa">``.
  With ``tblLayout="fixed"`` LibreOffice honours the grid over the
  cells, so a 3-column Q&A table whose cells are
  ``[1494, 4644, 8002]`` twips ends up rendered at
  ``[4722, 4722, 4722]``. The narrow row-number column gets
  over-wide and the wide "Answer" column shrinks - long answers
  wrap many more times than in the source and eventually clip.
  New pass ``align_tblgrid_to_cells()`` in
  ``pdf2docx_plus.emit.table_fit``: selects the widest row whose
  cells are all unspanned and have valid ``dxa`` widths, and
  rewrites ``<w:tblGrid>`` from those widths. Skipped when grid
  distribution already matches the canonical row, when no suitable
  canonical row exists, or when the row's cell count differs from
  the grid's column count. Gated by the same ``fit_wide_tables``
  flag as ``fit_oversized_tables`` (default True).
  ``ConversionResult`` now reports ``tblgrids_aligned``. Measured
  impact: 42 tables rewritten on the 42-page New_FAQ document so
  every Q&A row renders with the source's narrow / medium / wide
  column proportions; answer-column text now wraps at the same
  width as the source PDF.
- **Tables clipped off the right edge of the page.** Upstream carries
  ``<w:tblInd>`` and column widths forward in source-PDF coordinates.
  When the source places a table near the right margin - a classic
  pattern is a form whose ``Yes``/``No`` checkbox grid lives on the
  right of each item row - the indent plus the column widths often
  push the table's right edge past the DOCX page margin. LibreOffice
  and Word render only the visible slice and silently clip the
  overflow, so the rightmost cells simply disappear. Observed on
  Old_2_UT page 14: a ``6x2`` ``Applicable? (please tick)`` table at
  ``tblInd=8662 twips`` and ``10584 twips`` wide on a section whose
  content area is only ``10584 twips`` - the table's right edge
  landed ``7760 twips`` past the page's right edge, and the entire
  ``Yes``/``No`` column rendered blank. New post-emit pass
  ``fit_oversized_tables()`` in ``pdf2docx_plus.emit.table_fit``: for
  each ``<w:tbl>``, computes the enclosing section's content width,
  reduces ``<w:tblInd>`` first (preserving the source's
  right-alignment up to the point where the table would clip), and
  proportionally scales every ``<w:gridCol>`` and ``<w:tcW>`` when
  the table is still wider than the content area. Gated by the new
  ``fit_wide_tables`` flag on ``convert()`` (default True).
  ``ConversionResult`` now reports ``oversized_tables_fit``. Measured
  impact: 31 tables adjusted on Old_2_UT (67 pages), 46 on New_UT_2
  (69 pages); the ``Applicable?`` checkbox grids now render fully
  within the page bounds with no content loss.
- **Multi-row form/checkbox tables chopped down to the header.**
  ``trim_empty_table_rows()`` used to strip every leading and
  trailing all-empty row from every table, which destroyed
  legitimate forms whose empty rows are the form - e.g. the SFC
  Information Checklist's ``Applicable? (please tick)`` grids (6x2
  / 8x2 / 9x2 in the source PDF collapsed to 2x2 in the DOCX,
  leaving only the header and throwing away every row where the
  applicant is expected to tick ``Yes`` / ``No``). The pass now
  only trims when the table looks like a lattice detection
  artifact: at most four rows with exactly one non-empty row. Form
  tables with multiple legitimate empty rows are preserved
  verbatim. Measured impact: Old_UT preserved 8x2, 9x2 and 14x2
  checkbox grids that previously rendered as 2x2 stubs; rendered
  page count stays within +6 of the 67-page source while restoring
  the full structure of every checklist form.
- **Large empty form-continuation tables dropped.**
  ``drop_empty_tables()`` used to remove every table whose cells
  are all empty, regardless of size. That cleared the checkbox
  continuation grids that wrap a form's checklist items across
  pages (e.g. a 14x2 empty grid on page 14 of the UT checklist was
  the right-hand column of items 15-25 where the applicant ticks
  ``Yes`` / ``No``). The pass now only drops fully-empty tables
  with at most nine total cells (a 3x3 grid), which is still
  enough to clean up underline-stroke and decorative-box lattice
  artifacts. Tunable via the new ``max_cells`` keyword argument.

### Added

- New post-emit pass `collapse_empty_sections()` in
  `pdf2docx_plus.emit.sections`. Walks body-level paragraphs,
  groups them per section boundary, and removes sections whose
  content is empty (no ``<w:t>`` text, ``<w:drawing>``, ``<w:pict>``,
  ``<w:object>``, or ``<w:tbl>``). The final section - which uses
  the body-level ``<w:sectPr>`` - is always preserved. Gated by
  the new `collapse_empty_sects` flag on `convert()`
  (default True). `ConversionResult` now reports
  `empty_sections_collapsed`. Measured impact: New_KFS 10-page
  PDF dropped from 11 rendered pages to 10 (eliminated an orphan
  blank page 2 caused by two consecutive empty sections).
- Cell-merge crashguard for ``pdf2docx.table.Cell.make_docx``.
  When the inferred span crosses an already-merged cell,
  ``python-docx._Cell.merge()`` raises and upstream's page loop
  abandons the whole source page ("Ignore page N due to making
  page error"), dropping every block on that page. The guard
  catches only the ``"Failed to merge"`` exception, logs at
  WARNING, clears the span to 1x1 and retries so text, images,
  and cell order survive. Measured impact: Old_AWHKEF page 7
  (performance chart with stacked merged cells) now emits
  content where it previously rendered blank; rendered page
  count 8 -> 9, matching source.
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
  `pdf2docx_plus.emit.page_footer`. Two detection paths:
  ``"N Last update: ..."`` footer lines (KFS-style - installs a
  canonical right-aligned ``w:footer`` with ``Last update: ...``
  text and an auto-updating ``PAGE`` field); and bare monotonic
  page-number sequences that upstream emits as plain body
  paragraphs (``"1", "2", ..., "N"`` scattered one-per-source-page
  as in Explanatory Memoranda - strips the orphan digits from the
  body without installing a new footer, since per-page sections
  have tight margins and adding footer text re-inflates the page
  count). Gated by the new `promote_page_footer` flag on
  `convert()` (default True). `ConversionResult` now reports
  `page_footer_lines_promoted`. Measured impact on First Sentier
  PDFs: 56/50 body paragraphs promoted, eliminating 7-8
  near-blank pages that previously held only the static page
  number.
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
