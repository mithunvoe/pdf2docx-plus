"""Evaluation metrics for pdf2docx-plus benchmarks.

Implements the metric set described in PDF2DOCX_FORK_PLAN §4.K:

* `text_f1`   - word-level F1 (bag-of-words) against ground-truth text.
* `text_char_accuracy` - Levenshtein-based character accuracy (1 - edit/len).
* `teds`      - Tree-Edit-Distance Similarity for tables (via `apted`).
* `kendall_tau` - reading-order correlation between predicted block order and
                 ground-truth block order.
* `render_ssim`   - optional rendered visual similarity (needs LibreOffice +
                 scikit-image). Returns None if LibreOffice is unavailable.
* `editability`   - heuristic ratio of styled runs vs direct-formatted runs.

The old character-frequency F1 is retained as `text_char_f1` for
backwards compatibility but is intentionally NOT used in the main report —
bag-of-chars is too lenient (two strings with the same letter distribution
scored 1.0).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

_WS = re.compile(r"\s+")
_WORD = re.compile(r"\w+", re.UNICODE)


def _normalize(text: str) -> str:
    return _WS.sub(" ", text).strip()


def text_f1(predicted: str, expected: str) -> float:
    """Word-level F1 (bag-of-words) against ground truth.

    Strips punctuation, case-normalises, counts word frequencies, and
    computes 2PR/(P+R) over the multi-set intersection.
    """
    a = Counter(_WORD.findall(predicted.lower()))
    b = Counter(_WORD.findall(expected.lower()))
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    common = sum((a & b).values())
    if common == 0:
        return 0.0
    pred_tokens = sum(a.values())
    gt_tokens = sum(b.values())
    precision = common / pred_tokens
    recall = common / gt_tokens
    return 2 * precision * recall / (precision + recall)


def text_char_f1(predicted: str, expected: str) -> float:
    """Legacy character-frequency F1. Kept for back-compat only."""
    a = _normalize(predicted)
    b = _normalize(expected)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    ca = Counter(a)
    cb = Counter(b)
    common = sum((ca & cb).values())
    if common == 0:
        return 0.0
    precision = common / len(a)
    recall = common / len(b)
    return 2 * precision * recall / (precision + recall)


def text_char_accuracy(predicted: str, expected: str) -> float:
    """1 - Levenshtein(predicted, expected) / max(len)."""
    a = _normalize(predicted)
    b = _normalize(expected)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    # cap at 5000 chars per side to keep runtime bounded (O(n*m))
    a = a[:5000]
    b = b[:5000]
    n, m = len(a), len(b)
    # iterative DP
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        curr = [i] + [0] * m
        ai = a[i - 1]
        for j in range(1, m + 1):
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + (0 if ai == b[j - 1] else 1),
            )
        prev = curr
    return 1 - prev[m] / max(n, m)


def teds(predicted_table: list[list[str | None]], expected_table: list[list[str | None]]) -> float:
    """Tree-Edit-Distance Similarity: 1 - normalised edit distance on row/cell trees."""
    try:
        from apted import APTED, Config  # type: ignore
        from apted.helpers import Tree  # type: ignore
    except ImportError:  # pragma: no cover - bench extra required
        raise RuntimeError("teds requires 'pdf2docx-plus[bench]' (apted).")

    def to_tree(table: list[list[str | None]]) -> Any:
        rows = ["{row" + "".join("{cell{" + (c or "") + "}}" for c in row) + "}" for row in table]
        return Tree.from_text("{table" + "".join(rows) + "}")

    class _Cfg(Config):
        def rename(self, a, b):  # type: ignore[override]
            return 0 if a.name == b.name else 1

    t1 = to_tree(predicted_table)
    t2 = to_tree(expected_table)
    distance = APTED(t1, t2, _Cfg()).compute_edit_distance()
    denom = max(_node_count(t1), _node_count(t2), 1)
    return 1 - distance / denom


def _node_count(tree: Any) -> int:
    # apted's Tree exposes no public size; walk children.
    stack = [tree]
    n = 0
    while stack:
        t = stack.pop()
        n += 1
        stack.extend(getattr(t, "children", []) or [])
    return n


def kendall_tau(predicted_order: list[int], expected_order: list[int]) -> float:
    if len(predicted_order) < 2 or set(predicted_order) != set(expected_order):
        return 0.0
    rank = {v: i for i, v in enumerate(expected_order)}
    pairs = 0
    concordant = 0
    for i in range(len(predicted_order)):
        for j in range(i + 1, len(predicted_order)):
            a = rank[predicted_order[i]]
            b = rank[predicted_order[j]]
            pairs += 1
            if a < b:
                concordant += 1
    if pairs == 0:
        return 0.0
    return 2 * (concordant / pairs) - 1


def render_ssim(docx_path: Path, pdf_path: Path, dpi: int = 150) -> float | None:
    """Render both files and compute mean SSIM across page pairs.

    Returns None if LibreOffice (headless) is not installed.
    """
    if shutil.which("libreoffice") is None and shutil.which("soffice") is None:
        return None
    try:
        import numpy as np  # type: ignore
        from PIL import Image  # type: ignore
        from skimage.metrics import structural_similarity as ssim  # type: ignore
    except ImportError:
        return None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        docx_pdf = _soffice_to_pdf(docx_path, tmp_path)
        if docx_pdf is None:
            return None
        pdf_pngs = _pdf_to_pngs(pdf_path, tmp_path / "orig", dpi)
        docx_pngs = _pdf_to_pngs(docx_pdf, tmp_path / "conv", dpi)
        if not pdf_pngs or not docx_pngs:
            return None
        n = min(len(pdf_pngs), len(docx_pngs))
        scores: list[float] = []
        for i in range(n):
            a = np.asarray(Image.open(pdf_pngs[i]).convert("L"))
            b = np.asarray(Image.open(docx_pngs[i]).convert("L"))
            h = min(a.shape[0], b.shape[0])
            w = min(a.shape[1], b.shape[1])
            scores.append(float(ssim(a[:h, :w], b[:h, :w], data_range=255)))
        return sum(scores) / len(scores) if scores else None


def _soffice_to_pdf(docx: Path, out_dir: Path) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    binary = shutil.which("libreoffice") or shutil.which("soffice")
    if binary is None:
        return None
    try:
        subprocess.run(
            [binary, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(docx)],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    pdf = out_dir / (docx.stem + ".pdf")
    return pdf if pdf.exists() else None


def _pdf_to_pngs(pdf: Path, out_dir: Path, dpi: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        import fitz  # type: ignore
    except ImportError:
        return []
    pngs: list[Path] = []
    with fitz.open(pdf) as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            p = out_dir / f"p{i:03d}.png"
            pix.save(p)
            pngs.append(p)
    return pngs


def editability(docx_path: Path) -> float:
    """Composite editability score in [0, 1].

    Combines three signals:
    * fraction of runs inheriting a named character style (not Default)
    * fraction of paragraphs inheriting a non-Normal paragraph style
    * inverse run density (fewer runs per paragraph = easier to edit)
    """
    try:
        from docx import Document  # type: ignore
    except ImportError:  # pragma: no cover
        return 0.0
    doc = Document(str(docx_path))

    total_runs = 0
    styled_runs = 0
    total_paragraphs = 0
    styled_paragraphs = 0
    paragraph_run_counts: list[int] = []

    for p in doc.paragraphs:
        total_paragraphs += 1
        style_name = p.style.name if p.style else ""
        if style_name and style_name not in ("Normal", "Default Paragraph Font", ""):
            styled_paragraphs += 1
        run_count = 0
        for r in p.runs:
            total_runs += 1
            run_count += 1
            rs = r.style.name if r.style else ""
            if rs and rs not in ("Default Paragraph Font", ""):
                styled_runs += 1
        if run_count:
            paragraph_run_counts.append(run_count)

    if total_runs == 0:
        return 0.0

    run_style_score = styled_runs / total_runs
    para_style_score = styled_paragraphs / total_paragraphs if total_paragraphs else 0.0
    # run density: 1 run/paragraph = 1.0; 10 runs/paragraph = 0.1
    mean_runs = sum(paragraph_run_counts) / len(paragraph_run_counts) if paragraph_run_counts else 1
    density_score = min(1.0, 1.0 / max(mean_runs, 1))
    return 0.4 * run_style_score + 0.4 * para_style_score + 0.2 * density_score
