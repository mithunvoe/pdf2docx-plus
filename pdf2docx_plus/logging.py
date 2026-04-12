"""Structured logging helpers.

The upstream pdf2docx package uses `logging.basicConfig` at import time, which
hijacks the root logger of downstream apps. We scope everything here to the
`pdf2docx_plus` namespace and expose `configure()` for callers that explicitly
opt in.
"""

from __future__ import annotations

import logging
import sys

_LOGGER_NAME = "pdf2docx_plus"


def get_logger(name: str | None = None) -> logging.Logger:
    if name is None:
        return logging.getLogger(_LOGGER_NAME)
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")


def configure(level: int | str = logging.INFO, *, stream=None) -> None:
    """Opt-in console logging for scripts / CLI.

    Libraries embedding pdf2docx-plus should NOT call this; instead, configure
    their own root logger.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def silence_upstream() -> None:
    """Neuter the aggressive basicConfig side-effect in upstream `pdf2docx`."""
    for name in ("pdf2docx", "root"):
        logger = logging.getLogger(name)
        logger.handlers = []
