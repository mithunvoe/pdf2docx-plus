"""`pdf2docx-plus` CLI.

pdf2docx-plus convert IN.pdf [OUT.docx]
    [--start N] [--end N] [--pages 0,2,5]
    [--timeout 120] [--no-continue-on-error]
    [--multi-processing] [--profile fidelity|fast|semantic]
    [--password ...]
    [--tables-csv DIR]

pdf2docx-plus extract-tables IN.pdf [--out tables.json] [--csv DIR]
pdf2docx-plus serve [--host 0.0.0.0] [--port 8000]
pdf2docx-plus version
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from collections.abc import Iterable
from pathlib import Path

from .api import convert as _convert
from .api import extract_tables as _extract_tables
from .logging import configure
from .version import __version__


def _parse_pages(pages: str | None) -> list[int] | None:
    if not pages:
        return None
    return [int(x) for x in pages.split(",") if x.strip()]


def convert(
    input: str,
    output: str | None = None,
    *,
    start: int = 0,
    end: int | None = None,
    pages: str | None = None,
    timeout: float | None = None,
    continue_on_error: bool = True,
    multi_processing: bool = False,
    profile: str = "fidelity",
    password: str | None = None,
    tables_csv: str | None = None,
    log_level: str = "INFO",
) -> int:
    """Convert a PDF to DOCX. Returns process exit code."""
    configure(log_level.upper())
    result = _convert(
        input,
        output,
        password=password,
        pages=_parse_pages(pages),
        start=start,
        end=end,
        timeout_s=timeout,
        continue_on_error=continue_on_error,
        multi_processing=multi_processing,
        profile=profile,
    )

    if tables_csv:
        tables = _extract_tables(input, password=password, pages=_parse_pages(pages))
        _dump_tables_csv(tables, Path(tables_csv))

    logging.getLogger("pdf2docx_plus.cli").info(
        "done: %s -> %s  pages=%d ok=%d failed=%d  in %.2fs",
        result.input_path,
        result.output_path,
        result.pages_total,
        result.pages_ok,
        result.pages_failed,
        result.elapsed_s,
    )
    return 0 if result.success else 1


def extract_tables(
    input: str,
    *,
    out: str | None = None,
    csv_dir: str | None = None,
    password: str | None = None,
    pages: str | None = None,
    log_level: str = "INFO",
) -> int:
    configure(log_level.upper())
    tables = _extract_tables(input, password=password, pages=_parse_pages(pages))
    if out:
        Path(out).write_text(json.dumps(tables, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        json.dump(tables, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    if csv_dir:
        _dump_tables_csv(tables, Path(csv_dir))
    return 0


def _dump_tables_csv(tables: Iterable[Iterable[Iterable[str | None]]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, table in enumerate(tables, start=1):
        path = out_dir / f"table_{i:03d}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            for row in table:
                w.writerow(["" if c is None else c for c in row])


def serve(host: str = "127.0.0.1", port: int = 8000, *, log_level: str = "INFO") -> int:
    configure(log_level.upper())
    try:
        import uvicorn
    except ImportError as e:
        sys.stderr.write(
            "REST server requires the 'rest' extra: pip install 'pdf2docx-plus[rest]'\n"
        )
        raise SystemExit(1) from e
    uvicorn.run("pdf2docx_plus.server:app", host=host, port=port, log_level=log_level.lower())
    return 0


def version() -> int:
    sys.stdout.write(f"pdf2docx-plus {__version__}\n")
    return 0


def main() -> None:
    import fire

    fire.Fire(
        {
            "convert": convert,
            "extract-tables": extract_tables,
            "serve": serve,
            "version": version,
        }
    )


if __name__ == "__main__":
    main()
