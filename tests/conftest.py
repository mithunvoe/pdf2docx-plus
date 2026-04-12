"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "bench" / "corpus"


@pytest.fixture(scope="session")
def kfs_pdf() -> Path:
    p = CORPUS / "kfs_bosera" / "input.pdf"
    if not p.exists():
        pytest.skip("bench corpus not populated")
    return p


@pytest.fixture(scope="session")
def awhkef_pdf() -> Path:
    p = CORPUS / "awhkef" / "input.pdf"
    if not p.exists():
        pytest.skip("bench corpus not populated")
    return p
