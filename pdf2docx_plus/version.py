"""Package version.

Single source of truth is the distribution metadata recorded by the build
backend at install time (from ``pyproject.toml``). This file never needs
to be edited manually, and it can't drift from what's on PyPI.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pdf2docx-plus")
except PackageNotFoundError:
    # Editable / uninstalled checkout (e.g. running tests straight from src)
    __version__ = "0.0.0+unknown"
