"""Issue F1: PostScript / subset font names normalized to Word families."""
from __future__ import annotations

from pdf2docx_plus._vendored.pdf2docx.font.Fonts import Fonts, Font


def test_arialmt_normalized():
    assert Fonts._normalized_font_name("ArialMT") == "Arial"


def test_times_psmt_normalized():
    assert Fonts._normalized_font_name("TimesNewRomanPSMT") == "Times New Roman"


def test_subset_prefix_and_dash_still_stripped():
    assert Fonts._normalized_font_name("BCDGEE+Calibri-Bold") == "Calibri"


def test_courier_ps_normalized():
    assert Fonts._normalized_font_name("CourierNewPSMT") == "Courier New"


def test_plain_family_unchanged():
    assert Fonts._normalized_font_name("Calibri") == "Calibri"
    assert Fonts._normalized_font_name("Liberation Sans") == "Liberation Sans"


def test_get_skips_empty_descriptor():
    # a font with an empty descriptor must not match every lookup via the
    # 3rd-priority substring rule ("" in target is always True)
    fonts = Fonts([Font(descriptor="", name="", line_height=None)])
    assert fonts.get("ArialMT") is None
