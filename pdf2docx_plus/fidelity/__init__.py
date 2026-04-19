"""Runtime fixes applied as monkey-patches to the vendored `pdf2docx` pipeline.

Importing this module has side-effects: it patches upstream functions in
place. This keeps the diff against upstream small and easy to audit while
still fixing the behaviour.

Patches applied:

* `pdf2docx.common.docx.add_hyperlink` -> emit OOXML-valid `<w:hyperlink>`
  at paragraph level, not nested inside a run (fixes upstream #369 / #371).
* Text sanitisation before every run is added to a paragraph: strips XML-1.0
  invalid control characters (fixes #324 NULL-byte corruption).
* `Converter._color_output` becomes a no-op in non-TTY environments so logs
  aren't polluted with ANSI escapes when captured to files.
"""

from __future__ import annotations

from . import crashguards as _crashguards  # noqa: F401
from . import hyperlink as _hyperlink  # noqa: F401
from . import styles as _styles  # noqa: F401
from . import symbols as _symbols  # noqa: F401
from . import text as _text  # noqa: F401
from . import tty as _tty  # noqa: F401

__all__: list[str] = []
