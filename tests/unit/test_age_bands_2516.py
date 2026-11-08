"""Shared age-band parsing and lookup (Issue #2516)."""

from __future__ import annotations

import pytest

from clinosim.age_bands import (
    age_band_covers,
    find_age_band,
    find_age_band_or_last,
    lookup_age_band,
    parse_age_band,
    parse_closed_age_band,
)


def test_parse_closed_and_open_bands() -> None:
    assert parse_age_band("18-49") == (18, 49)
    assert parse_age_band(" 85+ ") == (85, None)


@pytest.mark.parametrize("key", ["", "18", "18-", "a-b", "1-2-3"])
def test_parse_rejects_malformed_keys(key: str) -> None:
    with pytest.raises(ValueError):
        parse_age_band(key)


def test_closed_band_required_where_tables_need_both_ends() -> None:
    with pytest.raises(ValueError):
        parse_closed_age_band("85+")


def test_bands_are_inclusive_at_both_ends() -> None:
    assert age_band_covers("18-49", 18) and age_band_covers("18-49", 49)
    assert not age_band_covers("18-49", 50)
    assert age_band_covers("85+", 85) and age_band_covers("85+", 120)


def test_first_matching_band_wins() -> None:
    assert find_age_band(["0-17", "10-20", "18-64"], 15) == "0-17"


def test_lookup_returns_the_callers_default_when_no_band_matches() -> None:
    table = {"0-17": 0.1, "18-64": 0.2}
    assert lookup_age_band(table, 30, 0.0) == 0.2
    assert lookup_age_band(table, 70, 0.0) == 0.0
    assert lookup_age_band(None, 30, "none") == "none"


def test_malformed_keys_raise_unless_skipped() -> None:
    table = {"adult": 9.0, "18-64": 0.2}
    with pytest.raises(ValueError):
        lookup_age_band(table, 30, 0.0)
    assert lookup_age_band(table, 30, 0.0, skip_malformed=True) == 0.2


def test_find_age_band_or_last_falls_back_to_last_band() -> None:
    bands = ["0-17", "18-64", "65-120"]
    assert find_age_band_or_last(bands, 30) == "18-64"
    assert find_age_band_or_last(bands, 0) == "0-17"
    assert find_age_band_or_last(bands, 130) == "65-120"
    assert find_age_band_or_last(["18-64", "65+"], 5) == "65+"
