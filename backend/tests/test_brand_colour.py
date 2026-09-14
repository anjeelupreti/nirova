"""The organization's own colour, as a preference.

What these hold: the palette can be Custom; the colour is a six-digit hex or
nothing, normalised to upper case; and anything the ramp cannot be computed
from is refused rather than stored.
"""

import pytest


def test_the_palette_may_be_custom_and_azure_is_the_default():
    from apps.identity.preferences import BY_KEY, DEFAULTS, coerce

    assert DEFAULTS["palette"] == "azure"
    assert coerce("palette", "custom") == "custom"
    assert "brand_color" in BY_KEY


def test_a_colour_is_a_hex_or_nothing():
    from apps.identity.preferences import coerce

    assert coerce("brand_color", "#2563eb") == "#2563EB"
    assert coerce("brand_color", "") == ""
    for bad in ("blue", "#2563E", "rgba(0,0,0,1)", "#GGGGGG", "2563EB"):
        with pytest.raises(ValueError):
            coerce("brand_color", bad)
