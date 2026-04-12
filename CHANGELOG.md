# Changelog

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
