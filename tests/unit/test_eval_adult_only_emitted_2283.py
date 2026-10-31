"""Eval's adult-only check uses each country's emitted codes (Issue #2283)."""

from __future__ import annotations

import pytest

from clinosim.eval.axes.clinical import _adult_only_emitted_prefixes

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("country", "code"), [("US", "F03.90"), ("JP", "F00")])
def test_dementia_is_adult_only_in_each_country(country: str, code: str) -> None:
    assert any(code.startswith(p) for p in _adult_only_emitted_prefixes(country))


@pytest.mark.parametrize("country", ["US", "JP"])
def test_other_adult_only_conditions_cover_their_emitted_codes(country: str) -> None:
    prefixes = _adult_only_emitted_prefixes(country)
    for code in ("I10", "I25.9", "I48.91", "I50.9", "E11.9", "N18.9", "N40"):
        assert any(code.startswith(p) for p in prefixes), (country, code)
