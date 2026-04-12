"""Typed, ergonomic facade around the vendored `pdf2docx` pipeline.

Differences vs upstream `pdf2docx.Converter`:

* Context-manager support (`with Converter(...) as cv:`) so the fitz document
  is always closed.
* `convert()` returns a `ConversionResult` dataclass instead of `None`, with
  per-page success/failure accounting.
* `timeout_s` enforces a wall-clock limit via a watchdog thread; raises
  `TimeoutExceeded` instead of hanging.
* Structured exceptions (`ParseError`, `MakeDocxError`, ...) instead of
  untyped `ConversionException`.
* All text written to the DOCX is sanitised of XML-invalid control characters
  (fixes upstream #324 NULL-byte corruption).
* Valid OOXML `<w:hyperlink>` emission (fixes upstream #369 / #371).
* Explicit `gc.collect()` between pages for large documents (fixes #301).
* Plugin hooks: `on_page_parsed`, `on_block_emitted`, `custom_table_detector`,
  `custom_layout_detector`.
"""

from __future__ import annotations

import gc
import os
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import IO, Any

from . import fidelity  # noqa: F401  (install monkey-patches on import)
from .consolidate import consolidate_runs
from .emit import apply_lists, extract_headers_footers
from .errors import (
    ConversionError,
    InputError,
    MakeDocxError,
    ParseError,
    PasswordRequired,
    TimeoutExceeded,
)
from .layout import detect_header_footer, detect_scanned_pages, normalise_list_blocks
from .logging import get_logger, silence_upstream
from .plugins import PluginRegistry
from .tables import demote_floating_images_in_cells, stitch_cross_page_tables

_log = get_logger("api")


@dataclass(frozen=True)
class PageResult:
    page_index: int
    ok: bool
    error: str | None = None
    elapsed_s: float = 0.0


@dataclass
class ConversionResult:
    input_path: str
    output_path: str | None
    pages_total: int
    pages_ok: int
    pages_failed: int
    elapsed_s: float
    page_results: list[PageResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scanned_pages: list[int] = field(default_factory=list)
    stitched_table_pairs: list[tuple[int, int]] = field(default_factory=list)
    runs_merged: int = 0
    demoted_floating_images: int = 0
    lists_detected: int = 0
    lists_emitted: int = 0
    headers_footers_detected: int = 0
    headers_footers_extracted: int = 0
    peak_rss_mb: float | None = None

    @property
    def success(self) -> bool:
        return self.pages_failed == 0 and self.output_path is not None

    @property
    def pages_per_second(self) -> float:
        return self.pages_total / self.elapsed_s if self.elapsed_s > 0 else 0.0


class Converter:
    """Public typed facade.

    Example:
        >>> with Converter("in.pdf") as cv:
        ...     result = cv.convert("out.docx", timeout_s=120)
        ...     assert result.success
    """

    def __init__(
        self,
        pdf_file: str | os.PathLike[str] | None = None,
        *,
        password: str | None = None,
        stream: bytes | None = None,
        plugins: PluginRegistry | None = None,
    ) -> None:
        if pdf_file is None and stream is None:
            raise InputError("Either pdf_file or stream must be provided.")
        if pdf_file is not None:
            pdf_file = os.fspath(pdf_file)
            if not Path(pdf_file).is_file():
                raise InputError(f"PDF not found: {pdf_file}")

        silence_upstream()
        from pdf2docx.converter import Converter as _UpstreamConverter

        try:
            self._inner = _UpstreamConverter(pdf_file=pdf_file, password=password, stream=stream)
        except Exception as e:  # fitz may raise RuntimeError/FileDataError
            raise InputError(f"Cannot open PDF: {e}") from e

        self._input = pdf_file
        self._plugins = plugins or PluginRegistry()

    # -- context manager ------------------------------------------------

    def __enter__(self) -> Converter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._inner.close()
        except Exception:
            _log.debug("swallowed error during close", exc_info=True)

    # -- properties ------------------------------------------------------

    @property
    def page_count(self) -> int:
        return len(self._inner.fitz_doc)

    @property
    def plugins(self) -> PluginRegistry:
        return self._plugins

    # -- main API --------------------------------------------------------

    def convert(
        self,
        output: str | os.PathLike[str] | IO[bytes] | None = None,
        *,
        pages: Iterable[int] | None = None,
        start: int = 0,
        end: int | None = None,
        timeout_s: float | None = None,
        continue_on_error: bool = True,
        multi_processing: bool = False,
        cpu_count: int = 0,
        profile: str = "fidelity",
        extra_settings: dict[str, Any] | None = None,
        apply_list_formatting: bool = True,
        extract_headers_footers_to_section: bool = False,
        consolidate_adjacent_runs: bool = True,
    ) -> ConversionResult:
        """Convert PDF to DOCX.

        Args:
            output: path or file-like object to write. If None, replaces `.pdf`
                with `.docx` next to the input.
            pages: explicit page indices (overrides start/end). 0-based.
            start, end: half-open page slice. 0-based.
            timeout_s: wall-clock watchdog; raises `TimeoutExceeded` on trip.
            continue_on_error: if True, per-page failures are recorded but do
                not abort the whole job; if False, the first error raises.
            multi_processing: parallel page parse via upstream worker pool.
            profile: "fast" | "fidelity" | "semantic" -> tuned setting preset.
            apply_list_formatting: detect bullet / numbered lists and emit
                real OOXML `w:numPr` lists. Default True.
            extract_headers_footers_to_section: move detected repeating
                top/bottom blocks from the body into `section.header` /
                `section.footer`. **Default False** — this remaps content
                aggressively and only works cleanly on single-section
                documents. Enable when you're converting a short, uniform
                document (contract, KFS sheet) and want pagination chrome
                moved out of the body.
            consolidate_adjacent_runs: merge adjacent `<w:r>` elements
                with identical run-properties. Default True — safe,
                improves editability.

        Returns:
            ConversionResult describing the outcome.
        """
        settings = dict(self._inner.default_settings)
        settings.update(_profile_settings(profile))
        if extra_settings:
            settings.update(extra_settings)
        settings.update(
            {
                "ignore_page_error": continue_on_error,
                "raw_exceptions": False,
                "multi_processing": multi_processing,
                "cpu_count": cpu_count,
            }
        )

        output_path = _resolve_output(output, self._input)

        result = ConversionResult(
            input_path=str(self._input) if self._input else "<stream>",
            output_path=(str(output_path) if isinstance(output_path, (str, Path)) else "<stream>"),
            pages_total=self.page_count,
            pages_ok=0,
            pages_failed=0,
            elapsed_s=0.0,
        )

        # stash post-process flags for _run_pipeline
        self._pp_flags = {
            "apply_lists": apply_list_formatting,
            "extract_hf": extract_headers_footers_to_section,
            "consolidate": consolidate_adjacent_runs,
        }

        t0 = time.perf_counter()
        done = threading.Event()
        exc: list[BaseException] = []

        def _work() -> None:
            try:
                page_list = list(pages) if pages is not None else None
                # run the three upstream stages, instrumenting each page
                self._run_pipeline(
                    output_path,
                    page_list,
                    start,
                    end,
                    settings,
                    result,
                    continue_on_error,
                )
            except BaseException as e:
                exc.append(e)
            finally:
                done.set()

        worker = threading.Thread(target=_work, name="pdf2docx-plus", daemon=True)
        worker.start()
        finished = done.wait(timeout=timeout_s) if timeout_s else done.wait()
        if not finished:
            # cannot hard-kill a CPython thread; best effort: mark timeout, let it reap
            raise TimeoutExceeded(
                f"Conversion exceeded {timeout_s}s. Thread still running; "
                "process will release resources on interpreter exit."
            )
        if exc:
            e = exc[0]
            if isinstance(e, ConversionError):
                raise e
            raise ConversionError(str(e)) from e

        result.elapsed_s = time.perf_counter() - t0
        gc.collect()
        return result

    def extract_tables(
        self,
        *,
        pages: Iterable[int] | None = None,
        start: int = 0,
        end: int | None = None,
    ) -> list[list[list[str | None]]]:
        settings = dict(self._inner.default_settings)
        settings.update(_profile_settings("fidelity"))
        page_list = list(pages) if pages is not None else None
        try:
            return self._inner.extract_tables(start=start, end=end, pages=page_list, **settings)
        except Exception as e:
            raise ParseError(f"extract_tables failed: {e}") from e

    # -- internals -------------------------------------------------------

    def _run_pipeline(
        self,
        output_path: Any,
        pages: list[int] | None,
        start: int,
        end: int | None,
        settings: dict[str, Any],
        result: ConversionResult,
        continue_on_error: bool,
    ) -> None:
        inner = self._inner
        fitz_doc = inner.fitz_doc
        if fitz_doc.needs_pass:
            if not inner.password:
                raise PasswordRequired("PDF is encrypted; supply `password`.")
            if not fitz_doc.authenticate(inner.password):
                raise PasswordRequired("Incorrect password.")

        # Step 0: scanned-page report (does not abort; just annotates result)
        try:
            scanned_reports = detect_scanned_pages(inner.fitz_doc)
            for r in scanned_reports:
                if r.is_scanned:
                    result.scanned_pages.append(r.page_index)
            if result.scanned_pages and not self._plugins.ocr_engines:
                result.warnings.append(
                    f"{len(result.scanned_pages)} scanned page(s) detected; no OCR "
                    "engine registered. Output will be mostly empty for those pages. "
                    "Pass a PaddleOcrEngine via PluginRegistry.add_ocr_engine()."
                )
        except Exception as e:
            _log.debug("scanned-page detection failed: %s", e)

        # Step 1/2: load & analyze
        inner.load_pages(start, end, pages).parse_document(**settings)

        # Step 3: parse pages with per-page accounting + gc
        pages_to_parse = [p for p in inner.pages if not p.skip_parsing]
        for page in pages_to_parse:
            pid = page.id
            t_page = time.perf_counter()
            try:
                page.parse(**settings)
                self._plugins.dispatch_page_parsed(page)
                result.page_results.append(
                    PageResult(page_index=pid, ok=True, elapsed_s=time.perf_counter() - t_page)
                )
                result.pages_ok += 1
            except Exception as e:
                result.page_results.append(
                    PageResult(
                        page_index=pid,
                        ok=False,
                        error=f"{type(e).__name__}: {e}",
                        elapsed_s=time.perf_counter() - t_page,
                    )
                )
                result.pages_failed += 1
                if not continue_on_error:
                    raise ParseError(f"Page {pid + 1}: {e}", page=pid) from e
                _log.warning("page %d parse failed: %s", pid + 1, e)
            finally:
                # drop per-page scratch; aggressively release image buffers
                gc.collect()

        # Step 3.5: post-parse layout/table enrichments
        finalized_pages = [p for p in inner.pages if getattr(p, "finalized", False)]
        try:
            for page in finalized_pages:
                result.demoted_floating_images += demote_floating_images_in_cells(page)
                result.lists_detected += normalise_list_blocks(page)
            stitch_report = stitch_cross_page_tables(finalized_pages)
            result.stitched_table_pairs.extend(stitch_report.merged_pairs)
            hf = detect_header_footer(finalized_pages)
            result.headers_footers_detected = len(hf)
            # stash for post-emit extraction
            self._detected_hf = hf
        except Exception as e:
            _log.warning("post-parse enrichment failed: %s", e)
            result.warnings.append(f"post-parse enrichment failed: {e}")

        # Step 4: make docx
        try:
            inner.make_docx(output_path, **settings)
        except Exception as e:
            raise MakeDocxError(f"make_docx failed: {e}") from e

        # Step 4.5: post-emit transforms — lists, headers/footers, consolidate.
        pp = getattr(self, "_pp_flags", {})
        if isinstance(output_path, str) and any(pp.values()):
            try:
                from docx import Document as _Doc

                doc = _Doc(output_path)
                dirty = False
                if pp.get("apply_lists"):
                    try:
                        result.lists_emitted = apply_lists(doc)
                        if result.lists_emitted:
                            dirty = True
                    except Exception as e:
                        _log.debug("apply_lists skipped: %s", e)
                if pp.get("extract_hf"):
                    try:
                        result.headers_footers_extracted = extract_headers_footers(
                            doc, getattr(self, "_detected_hf", [])
                        )
                        if result.headers_footers_extracted:
                            dirty = True
                    except Exception as e:
                        _log.debug("extract_headers_footers skipped: %s", e)
                if pp.get("consolidate"):
                    try:
                        merged = consolidate_runs(doc)
                        if merged:
                            dirty = True
                            result.runs_merged = merged
                    except Exception as e:
                        _log.debug("run consolidation skipped: %s", e)
                if dirty:
                    doc.save(output_path)
            except Exception as e:
                _log.debug("post-emit transforms skipped: %s", e)

        # peak RSS (best-effort; Unix only)
        try:
            import resource

            rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # Linux: ru_maxrss is KB; macOS: bytes. Heuristic: if > 1 GB expressed
            # in the unit, assume bytes.
            result.peak_rss_mb = rss_kb / (1024 * 1024) if rss_kb > 10_000_000 else rss_kb / 1024
        except (ImportError, AttributeError):
            pass


# -- module-level helpers --------------------------------------------------


def convert(
    input_pdf: str | os.PathLike[str],
    output_docx: str | os.PathLike[str] | None = None,
    *,
    password: str | None = None,
    pages: Iterable[int] | None = None,
    start: int = 0,
    end: int | None = None,
    timeout_s: float | None = None,
    continue_on_error: bool = True,
    multi_processing: bool = False,
    profile: str = "fidelity",
) -> ConversionResult:
    """One-shot convenience wrapper. Opens, converts, closes."""
    with Converter(input_pdf, password=password) as cv:
        return cv.convert(
            output_docx,
            pages=pages,
            start=start,
            end=end,
            timeout_s=timeout_s,
            continue_on_error=continue_on_error,
            multi_processing=multi_processing,
            profile=profile,
        )


def extract_tables(
    input_pdf: str | os.PathLike[str],
    *,
    password: str | None = None,
    pages: Iterable[int] | None = None,
) -> list[list[list[str | None]]]:
    with Converter(input_pdf, password=password) as cv:
        return cv.extract_tables(pages=pages)


# -- internal utilities -----------------------------------------------------


def _resolve_output(
    output: str | os.PathLike[str] | IO[bytes] | None, input_path: str | None
) -> Any:
    if output is None:
        if input_path is None:
            raise InputError("output must be supplied when input is a stream.")
        return str(Path(input_path).with_suffix(".docx"))
    if hasattr(output, "write"):
        return output
    raw = os.fspath(output)
    looks_like_dir = raw.endswith((os.sep, "/"))
    out = Path(raw)
    # If caller passed an existing directory (or a path ending in a separator),
    # derive the filename from the input PDF stem.
    if looks_like_dir or out.is_dir():
        if input_path is None:
            raise InputError(
                "output is a directory; cannot derive filename when input is a stream."
            )
        out.mkdir(parents=True, exist_ok=True)
        return str(out / (Path(input_path).stem + ".docx"))
    return str(out)


def _profile_settings(profile: str) -> dict[str, Any]:
    if profile == "fast":
        return {
            "debug": False,
            "parse_lattice_table": True,
            "parse_stream_table": False,
            "extract_stream_table": False,
            "clip_image_res_ratio": 2.0,
        }
    if profile == "semantic":
        return {
            "debug": False,
            "parse_lattice_table": True,
            "parse_stream_table": True,
            "extract_stream_table": True,
            "clip_image_res_ratio": 4.0,
        }
    # default: fidelity
    return {
        "debug": False,
        "parse_lattice_table": True,
        "parse_stream_table": True,
        "extract_stream_table": False,
        "clip_image_res_ratio": 4.0,
    }
