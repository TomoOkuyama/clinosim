"""Code displays and localized values normalize the language argument the
same way (code-mapping spec §5.1, Issue #2453)."""

from __future__ import annotations

import pytest

from clinosim.codes import display
from clinosim.countries import normalize_lang
from clinosim.locale.localized import localized

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("ja", "ja"),
        ("JA", "ja"),
        ("JP", "ja"),
        ("ja-JP", "ja"),
        ("en-US", "en"),
        ("US", "en"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_normalize_lang(given: str | None, expected: str) -> None:
    assert normalize_lang(given) == expected


@pytest.mark.parametrize("lang", ["ja", "JA", "JP", "ja-JP"])
def test_code_display_and_localized_agree(lang: str) -> None:
    ja = display("hl7-discharge-disposition", "home", "ja")
    assert ja and ja != display("hl7-discharge-disposition", "home", "en")
    assert display("hl7-discharge-disposition", "home", lang) == ja
    assert localized({"en": "Home", "ja": ja}, lang) == ja


def test_unknown_language_falls_back_to_english() -> None:
    assert display("hl7-discharge-disposition", "home", "fr-CA") == display("hl7-discharge-disposition", "home", "en")
