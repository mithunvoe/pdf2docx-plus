# pdf2docx-plus

Hardened fork of [pdf2docx](https://github.com/ArtifexSoftware/pdf2docx) — a
Python PDF → DOCX converter that actually writes editable Word documents
(not Markdown, not HTML).

**What's different from upstream**

| | upstream `pdf2docx` | `pdf2docx-plus` |
|---|---|---|
| Python support | 3.10+ | **3.11 / 3.12 / 3.13** |
| Hyperlink OOXML | nested inside `<w:r>` (invalid) | paragraph-level `<w:hyperlink>` (valid) |
| NULL-byte / control chars | sometimes leaks into `<w:t>`, corrupts DOCX | stripped at run insertion |
| Errors | single `ConversionException` | `InputError` / `ParseError` / `MakeDocxError` / `PasswordRequired` / `TimeoutExceeded` |
| Typed API | no | `py.typed`, dataclasses, `Protocol`-based plugins |
| Return value | `None` | `ConversionResult` with per-page accounting |
| Timeout | none (can hang forever) | `timeout_s=` watchdog |
| Plugin architecture | no | swap table / layout / OCR / formula backends |
| REST server | no | `pdf2docx-plus serve` (FastAPI, optional) |
| ML hooks (opt-in) | no | Table Transformer, Granite-Docling, PaddleOCR, pix2tex |
| Tables → CSV | no | `--tables-csv DIR` |
| Structured logging | hijacks root logger | scoped `pdf2docx_plus` logger |

## Install

```bash
pip install pdf2docx-plus            # core
pip install 'pdf2docx-plus[rest]'    # + FastAPI server
pip install 'pdf2docx-plus[bench]'   # + evaluation harness
pip install 'pdf2docx-plus[ml-tables]' # + Table Transformer (torch)
pip install 'pdf2docx-plus[ml-ocr]'  # + PaddleOCR
```

## Quick start

```python
from pdf2docx_plus import convert

result = convert("in.pdf", "out.docx", timeout_s=120)
print(result.pages_ok, "/", result.pages_total, "pages in", result.elapsed_s, "s")
```

Or with more control:

```python
from pdf2docx_plus import Converter, PluginRegistry
from pdf2docx_plus.hooks import TableTransformerDetector

plugins = PluginRegistry()
plugins.add_table_detector(TableTransformerDetector(device="cuda"))

with Converter("in.pdf", password="s3cret") as cv:
    result = cv.convert(
        "out.docx",
        pages=[0, 1, 2],
        profile="fidelity",     # "fast" | "fidelity" | "semantic"
        timeout_s=60,
        continue_on_error=True,
    )
    for p in result.page_results:
        if not p.ok:
            print(f"page {p.page_index}: {p.error}")
```

## CLI

```
pdf2docx-plus convert in.pdf out.docx --timeout 120 --profile fidelity
pdf2docx-plus convert in.pdf --pages 0,2,5 --tables-csv tables/
pdf2docx-plus extract-tables in.pdf --out tables.json
pdf2docx-plus serve --host 0.0.0.0 --port 8000
pdf2docx-plus version
```

## REST server

```bash
pip install 'pdf2docx-plus[rest]'
pdf2docx-plus serve --port 8000
# in another shell:
curl -F file=@in.pdf -F profile=fidelity http://localhost:8000/convert -o out.docx
```

Endpoints:

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/convert` | multipart `file`, optional `password`, `profile`, `timeout_s` | DOCX bytes + `X-Pages-Ok` / `X-Pages-Failed` / `X-Elapsed-Seconds` headers |
| POST | `/extract-tables` | multipart `file`, optional `password` | JSON `{"tables": [...]}` |
| GET  | `/healthz` | — | `{"status": "ok"}` |
| GET  | `/version` | — | `{"version": "..."}` |

## Plugin architecture

Four extension points, all `Protocol`-based:

```python
from pdf2docx_plus.plugins import (
    TableDetector, LayoutDetector, OcrEngine, FormulaRecognizer
)
```

Register any implementation on `PluginRegistry` and pass it to `Converter`.
Plugins never kill a conversion — exceptions raised inside a plugin are
logged and skipped.

Built-in ML hooks (opt-in extras):

| Hook | Backend | Extra | Weights license |
|---|---|---|---|
| `TableTransformerDetector` | HuggingFace `microsoft/table-transformer-*` | `ml-tables` | MIT |
| `GraniteDoclingLayoutDetector` | `ibm-granite/granite-docling-258M` | `ml-layout` | Apache-2.0 |
| `PaddleOcrEngine` | PaddleOCR | `ml-ocr` | Apache-2.0 |
| `Pix2TexFormulaRecognizer` | pix2tex | `ml-formula` | MIT |
| `UniMERNetFormulaRecognizer` | UniMERNet (bring weights) | manual | Apache-2.0 |

## Benchmark

```bash
pip install 'pdf2docx-plus[bench]'
python -m bench.run --corpus bench/corpus --out bench/reports/latest.json
```

Metrics implemented: text F1, TEDS (`apted`), reading-order Kendall-tau,
rendered SSIM (via LibreOffice + scikit-image), and editability ratio.

Seed corpus in this repo: 3 financial fund PDFs (born-digital). Drop more
under `bench/corpus/<name>/input.pdf` and, optionally, `expected_text.txt`,
`expected_tables.json`, `expected_order.json` for scoring.

Current baseline on the seed corpus (76 pages, CPU):

```
awhkef                  9 pages   0 failed    7.1 s   74 KB
first_sentier          58 pages   0 failed   15.8 s  155 KB
kfs_bosera              9 pages   0 failed    4.3 s   87 KB
TOTAL                  76 pages   0 failed   27.7 s  2.75 pg/s
```

## Licensing

`pdf2docx-plus` is MIT, but **depends on PyMuPDF (AGPL-3.0)** — this
propagates to you if you redistribute or expose as a network service. See
[LICENSING.md](LICENSING.md) for the full dependency matrix, AGPL
implications, and the future pypdfium2 migration path.

## What's NOT done yet (roadmap)

This fork covers **Phase 0** (foundation) and most of **Phase 1** (stability
+ typed API) from the original 21-week
[`PDF2DOCX_FORK_PLAN.md`](../PDF2DOCX_FORK_PLAN.md). Phases 2–5 are scaffolded
via the plugin architecture but the ML-backed hooks need real integration
work to reach the v1.0 success criteria in the plan (TEDS ≥ 0.90, text F1 ≥
0.98, reading-order Kendall-tau ≥ 0.90).

Specifically, still open:

- Train / evaluate Table Transformer + Granite-Docling against an annotated
  corpus (plan §K).
- Cross-page table stitching heuristic (§B.7).
- Header/footer → `w:hdr` / `w:ftr` emission (§C.13).
- Math recognition pipeline wiring (§F.24).
- Scanned-PDF OCR routing + auto-detect (§G.25).
- `styles.xml` rewrite (§H.27) — currently we still use python-docx defaults.
- pypdfium2 backend for permissive licensing (§6).

## Credits

Forked from [ArtifexSoftware/pdf2docx](https://github.com/ArtifexSoftware/pdf2docx)
(originally by [@dothinking](https://github.com/dothinking)). MIT.
