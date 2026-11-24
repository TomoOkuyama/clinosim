"""English ordinal suffixes for growth percentiles (Issue #3701)."""

from __future__ import annotations

import pytest

from clinosim.locale.ordinal import ordinal_suffix
from clinosim.modules.document.narrative._visit_reason import _phrase


@pytest.mark.parametrize(
    ("n", "suffix"),
    [
        (1, "st"),
        (2, "nd"),
        (3, "rd"),
        (4, "th"),
        (11, "th"),
        (12, "th"),
        (13, "th"),
        (21, "st"),
        (22, "nd"),
        (23, "rd"),
        (71, "st"),
        (72, "nd"),
        (93, "rd"),
        (100, "th"),
        (111, "th"),
    ],
)
def test_english_ordinal_suffix(n: int, suffix: str) -> None:
    assert ordinal_suffix(n, "en") == suffix


def test_other_languages_have_no_suffix() -> None:
    assert ordinal_suffix(71, "ja") == ""


@pytest.mark.parametrize("pct", [1, 2, 3, 11, 22, 71, 93, 50])
def test_percentile_phrase_en(pct: int) -> None:
    text = _phrase("percentile", "en", pct=pct, suffix=ordinal_suffix(pct, "en"))
    assert text == f"({pct}{ordinal_suffix(pct, 'en')} percentile)"


def test_percentile_phrase_ja_unchanged() -> None:
    assert _phrase("percentile", "ja", pct=71, suffix=ordinal_suffix(71, "ja")) == "(71 パーセンタイル)"
