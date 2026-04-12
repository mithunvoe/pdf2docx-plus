#!/usr/bin/env bash
# pdf2docx-plus test & validation harness.
#
# Usage:
#   scripts/test.sh                     # run everything (install, lint, tests, bench, round-trip)
#   scripts/test.sh install             # create venv + install editable with dev+bench extras
#   scripts/test.sh lint                # ruff + ruff format --check
#   scripts/test.sh unit                # pytest -m unit
#   scripts/test.sh integration         # pytest -m integration
#   scripts/test.sh tests               # pytest (all markers)
#   scripts/test.sh bench               # run benchmark on bench/corpus
#   scripts/test.sh convert <pdf> [out] # convert a PDF via the new API
#   scripts/test.sh roundtrip <pdf>     # convert then re-render through LibreOffice
#   scripts/test.sh serve               # start REST server (requires [rest] extra)
#   scripts/test.sh clean               # remove venv, caches, bench outputs
#
# Pass --help to any subcommand for a reminder of the flags.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

_need_venv() {
    if [[ ! -x "$PY" ]]; then
        echo "venv not found — running install first"
        cmd_install
    fi
}

cmd_install() {
    if [[ ! -d "$VENV" ]]; then
        python3 -m venv "$VENV"
    fi
    "$PIP" install --upgrade pip wheel setuptools >/dev/null
    "$PIP" install -e ".[dev,bench]"
    echo "OK installed in $VENV"
}

cmd_lint() {
    _need_venv
    "$VENV/bin/ruff" check pdf2docx_plus bench tests
    "$VENV/bin/ruff" format --check pdf2docx_plus bench tests
    echo "OK lint clean"
}

cmd_unit() {
    _need_venv
    "$VENV/bin/pytest" -q -m unit --timeout=60 "$@"
}

cmd_integration() {
    _need_venv
    "$VENV/bin/pytest" -q -m integration --timeout=180 "$@"
}

cmd_tests() {
    _need_venv
    "$VENV/bin/pytest" -q --timeout=180 --cov=pdf2docx_plus --cov-report=term-missing "$@"
}

cmd_bench() {
    _need_venv
    local no_ssim=""
    if ! command -v libreoffice >/dev/null 2>&1 && ! command -v soffice >/dev/null 2>&1; then
        no_ssim="--no-ssim"
        echo "note: LibreOffice not found — skipping SSIM metric"
    fi
    mkdir -p bench/reports
    "$PY" -m bench.run --corpus bench/corpus --out bench/reports/latest.json $no_ssim "$@"
    echo
    echo "report written to bench/reports/latest.json"
}

cmd_convert() {
    _need_venv
    if [[ $# -lt 1 ]]; then
        echo "usage: test.sh convert <pdf> [out.docx]" >&2
        return 2
    fi
    local input="$1"
    local output="${2:-${input%.pdf}.docx}"
    "$PY" -c "
from pdf2docx_plus import convert
r = convert(r'''$input''', r'''$output''', timeout_s=240, continue_on_error=True)
print(f'input       : {r.input_path}')
print(f'output      : {r.output_path}')
print(f'pages       : total={r.pages_total} ok={r.pages_ok} failed={r.pages_failed}')
print(f'elapsed     : {r.elapsed_s:.2f}s  ({r.pages_total / max(r.elapsed_s, 1e-6):.2f} pg/s)')
if r.pages_failed:
    for p in r.page_results:
        if not p.ok: print(f'  page {p.page_index+1}: {p.error}')
"
}

cmd_roundtrip() {
    _need_venv
    if [[ $# -lt 1 ]]; then
        echo "usage: test.sh roundtrip <pdf>" >&2
        return 2
    fi
    local input="$1"
    local stem
    stem="$(basename "$input" .pdf)"
    local tmp
    tmp="$(mktemp -d)"
    local docx="$tmp/$stem.docx"
    echo "=> convert $input  ->  $docx"
    cmd_convert "$input" "$docx"

    local binary
    binary="$(command -v libreoffice || command -v soffice || true)"
    if [[ -z "$binary" ]]; then
        echo "LibreOffice not installed — cannot validate round-trip. Open $docx in Word manually."
        echo "docx kept at: $docx"
        return 0
    fi
    echo "=> re-render docx through LibreOffice"
    "$binary" --headless --convert-to pdf --outdir "$tmp" "$docx" >/dev/null 2>&1
    if [[ -f "$tmp/$stem.pdf" ]]; then
        echo "OK round-trip passed"
        echo "  original input: $input"
        echo "  produced docx : $docx"
        echo "  re-rendered   : $tmp/$stem.pdf"
    else
        echo "FAIL round-trip: LibreOffice could not open the DOCX"
        return 1
    fi
}

cmd_serve() {
    _need_venv
    if ! "$PY" -c "import fastapi" 2>/dev/null; then
        echo "installing [rest] extra..."
        "$PIP" install -e ".[rest]"
    fi
    "$VENV/bin/pdf2docx-plus" serve "$@"
}

cmd_all() {
    cmd_install
    cmd_lint
    cmd_tests
    cmd_bench
    # round-trip the seed corpus
    for pdf in bench/corpus/*/input.pdf; do
        [[ -f "$pdf" ]] || continue
        cmd_roundtrip "$pdf"
        echo
    done
    echo
    echo "=========================================="
    echo "  All checks passed."
    echo "=========================================="
}

cmd_clean() {
    rm -rf "$VENV" .mypy_cache .ruff_cache .pytest_cache bench/reports
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    echo "OK cleaned"
}

main() {
    local sub="${1:-all}"
    shift || true
    case "$sub" in
        all)         cmd_all "$@" ;;
        install)     cmd_install "$@" ;;
        lint)        cmd_lint "$@" ;;
        unit)        cmd_unit "$@" ;;
        integration) cmd_integration "$@" ;;
        tests|test)  cmd_tests "$@" ;;
        bench)       cmd_bench "$@" ;;
        convert)     cmd_convert "$@" ;;
        roundtrip)   cmd_roundtrip "$@" ;;
        serve)       cmd_serve "$@" ;;
        clean)       cmd_clean "$@" ;;
        -h|--help|help)
            sed -n '1,30p' "$0"
            ;;
        *)
            echo "unknown subcommand: $sub" >&2
            echo "run '$0 --help' for usage" >&2
            return 2
            ;;
    esac
}

main "$@"
