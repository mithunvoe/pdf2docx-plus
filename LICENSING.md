# Licensing

`pdf2docx-plus` is MIT-licensed (see `LICENSE`). **However, it depends on PyMuPDF,
which is AGPL-3.0.** This section documents the practical consequences.

## Dependency license matrix

| Package | License | Shipped with | Note |
|---|---|---|---|
| pdf2docx-plus (this project) | MIT | core | |
| pdf2docx (vendored patched upstream) | MIT | core | Artifex / dothinking |
| PyMuPDF (fitz) | **AGPL-3.0** | core | **See AGPL section below** |
| python-docx | MIT | core | |
| fonttools | MIT | core | |
| numpy | BSD-3-Clause | core | |
| opencv-python-headless | Apache-2.0 | core | |
| fire | Apache-2.0 | core | |
| fastapi / uvicorn | MIT / BSD-3 | `rest` extra | |
| apted | MIT | `bench` extra | |
| scikit-image | BSD-3-Clause | `bench` extra | |
| Table Transformer weights | MIT | `ml-tables` extra | |
| pix2tex / LaTeX-OCR | MIT | `ml-formula` extra | |
| PaddleOCR | Apache-2.0 | `ml-ocr` extra | |
| UniMERNet | Apache-2.0 | (optional, manual) | |

## AGPL implications (PyMuPDF)

PyMuPDF is distributed under **AGPL-3.0**. When `pdf2docx-plus` is redistributed
or offered as a network service, the AGPL copyleft reaches through to the
consumer of that service:

- If you **ship pdf2docx-plus inside a closed-source product**, you need a
  commercial PyMuPDF license from Artifex.
- If you **offer pdf2docx-plus as a SaaS/network service** to third parties,
  the AGPL requires you to make the corresponding source (including your app)
  available to those users.
- **Internal use** inside a single organisation is typically fine under AGPL.

## Migrating away from PyMuPDF (future work)

The parse layer is isolated behind the `pdf2docx_plus.backends` abstraction so
the fitz dependency can be swapped for an Apache-2.0 / MIT alternative:

- **`pypdfium2`** (Apache-2.0): Google PDFium bindings. Exposes text with
  positioning and page rendering but does *not* provide the rich
  block/line/span extraction or path extraction that the current pipeline
  relies on. A swap requires re-implementing ~3-4 weeks of extraction logic
  using `pypdfium2` + `pdfplumber` (MIT) for ruling-line tables.
- **`pdfminer.six`** (MIT): slower but full text/layout extraction. Could be
  a drop-in for many text paths.

The `pdf2docx_plus.backends.Backend` Protocol is the seam. When a permissive
backend is implemented, the same high-level API keeps working and AGPL falls
away from the default distribution.

## OCR / ML model weights

Some ML integrations downloaded by the optional extras carry **non-commercial
or research-only** weights:

- **LayoutLMv3 weights**: CC-BY-NC-SA-4.0 — **not safe for commercial use**.
  `pdf2docx-plus` does NOT ship or auto-download these.
- **Nougat (Meta) weights**: CC-BY-NC-4.0 — **not safe for commercial use**.
- **Surya / Marker weights**: OpenRAIL-M with a revenue cap. Safe up to the
  cap; verify before relying on them in production.

The default `ml-*` extras pin only permissively-licensed models
(Table Transformer, pix2tex, PaddleOCR, UniMERNet). Users who wire in their
own detectors via the plugin API are responsible for their own weight
licensing.
