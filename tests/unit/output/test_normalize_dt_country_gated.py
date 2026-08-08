"""Regression test for Issue #570 locale gate: the post-emit walker rewrites
JST timestamps to the country's canonical TZ suffix.

Builders unconditionally emit ``+09:00`` via ``to_fhir_datetime`` /
``to_fhir_instant`` in :mod:`clinosim.modules.output.fhir_common`. The walker
:func:`clinosim.modules.output._fhir_post_process._normalize_dt_fields` then
rewrites the suffix per country: JP keeps ``+09:00``; other cohorts (US
default) get ``Z`` (UTC neutral default). Other pre-existing TZ suffixes
(e.g. ``-05:00``) are preserved.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.post_process import (
    _normalize_dt,
    _normalize_dt_fields,
)
from clinosim.modules.output.fhir_r4.common import tz_suffix_for_country

pytestmark = pytest.mark.unit


class TestTzSuffixForCountry:
    def test_jp_returns_jst(self):
        assert tz_suffix_for_country("JP") == "+09:00"
        assert tz_suffix_for_country("jp") == "+09:00"
        assert tz_suffix_for_country(" JP ") == "+09:00"

    def test_us_returns_utc(self):
        assert tz_suffix_for_country("US") == "Z"
        assert tz_suffix_for_country("us") == "Z"

    def test_empty_or_unknown_returns_utc(self):
        assert tz_suffix_for_country("") == "Z"
        assert tz_suffix_for_country("FR") == "Z"


class TestNormalizeDtRewrite:
    def test_jp_keeps_jst_suffix(self):
        result = _normalize_dt("2026-01-01T12:34:56+09:00", country="JP")
        assert result == "2026-01-01T12:34:56+09:00"

    def test_us_rewrites_jst_to_utc(self):
        result = _normalize_dt("2026-01-01T12:34:56+09:00", country="US")
        assert result == "2026-01-01T12:34:56Z"

    def test_empty_country_defaults_to_utc(self):
        result = _normalize_dt("2026-01-01T12:34:56+09:00")
        assert result == "2026-01-01T12:34:56Z"

    def test_us_appends_tz_when_missing(self):
        result = _normalize_dt("2026-01-01T12:34:56", country="US")
        assert result == "2026-01-01T12:34:56Z"

    def test_jp_appends_jst_when_missing(self):
        result = _normalize_dt("2026-01-01T12:34:56", country="JP")
        assert result == "2026-01-01T12:34:56+09:00"

    def test_existing_non_jst_tz_preserved(self):
        # `-05:00` came from a specific source; don't rewrite it.
        result = _normalize_dt("2026-01-01T12:34:56-05:00", country="US")
        assert result == "2026-01-01T12:34:56-05:00"
        # UTC `Z` also preserved on JP path.
        assert _normalize_dt("2026-01-01T12:34:56Z", country="JP") == "2026-01-01T12:34:56Z"

    def test_date_only_us_instant_appends_utc(self):
        result = _normalize_dt("2026-01-01", country="US", want_instant=True)
        assert result == "2026-01-01T00:00:00Z"

    def test_date_only_jp_instant_appends_jst(self):
        result = _normalize_dt("2026-01-01", country="JP", want_instant=True)
        assert result == "2026-01-01T00:00:00+09:00"


class TestNormalizeDtFieldsUsCohortNoJst:
    """`_normalize_dt_fields` must not leave any `+09:00` on a US resource walk."""

    def test_us_resource_walk_rewrites_all_jst(self):
        resource = {
            "resourceType": "Observation",
            "effectiveDateTime": "2026-01-01T12:34:56+09:00",
            "issued": "2026-01-01T12:34:56.789+09:00",
            "period": {
                "start": "2026-01-01T00:00:00+09:00",
                "end": "2026-01-02T00:00:00+09:00",
            },
            "meta": {"lastUpdated": "2026-01-01T12:34:56.789+09:00"},
        }
        _normalize_dt_fields(resource, country="US")
        _assert_no_jst_in(resource)

    def test_jp_resource_walk_keeps_jst(self):
        resource = {
            "resourceType": "Observation",
            "effectiveDateTime": "2026-01-01T12:34:56+09:00",
            "issued": "2026-01-01T12:34:56.789+09:00",
        }
        _normalize_dt_fields(resource, country="JP")
        assert resource["effectiveDateTime"].endswith("+09:00")
        assert resource["issued"].endswith("+09:00")


def _assert_no_jst_in(node) -> None:
    """Walk the resource dict/list and fail if any string contains `+09:00`."""
    if isinstance(node, dict):
        for v in node.values():
            _assert_no_jst_in(v)
    elif isinstance(node, list):
        for item in node:
            _assert_no_jst_in(item)
    elif isinstance(node, str):
        assert "+09:00" not in node, f"Found JST leak on US resource: {node!r}"
