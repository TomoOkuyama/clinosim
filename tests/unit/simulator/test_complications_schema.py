"""Tests for the Phase 1a complications_occurred schema helpers
(``clinosim.simulator.complications``)."""

from __future__ import annotations

import pytest

from clinosim.simulator.complications import (
    SOURCES,
    _normalize_complication,
    build_complication,
    complication_names,
)


class TestNormalizeComplication:
    def test_bare_string_becomes_legacy_dict(self):
        """A pre-Phase-1 bare-string entry projects to a legacy-tagged dict
        so on-disk v0.6.x CIF JSON round-trips unchanged."""
        result = _normalize_complication("aspiration_pneumonia")
        assert result == {
            "name": "aspiration_pneumonia",
            "onset_day": None,
            "onset_datetime": None,
            "source": "legacy",
        }

    def test_dict_passthrough_preserves_all_fields(self):
        """A well-formed dict entry round-trips with every field intact."""
        entry = {
            "name": "acute_kidney_injury",
            "onset_day": 5,
            "onset_datetime": "2026-04-01T12:00:00",
            "source": "daily_loop",
        }
        assert _normalize_complication(entry) == entry

    def test_dict_missing_fields_gets_defaults(self):
        """Partially-formed dicts get None / 'unknown' defaults rather than
        raising — resilient to future producer variants."""
        result = _normalize_complication({"name": "delirium"})
        assert result["name"] == "delirium"
        assert result["onset_day"] is None
        assert result["onset_datetime"] is None
        assert result["source"] == "unknown"

    def test_dict_unknown_source_is_normalized_to_unknown(self):
        """A source value outside the allowlist becomes ``unknown`` (fail-
        soft rather than raise; producer-side validation catches this)."""
        result = _normalize_complication({"name": "x", "source": "bogus"})
        assert result["source"] == "unknown"

    def test_onset_day_non_integer_becomes_none(self):
        """Malformed onset_day (str / float / etc.) becomes None rather than
        propagating an int-parse failure."""
        result = _normalize_complication({"name": "x", "onset_day": "day3"})
        assert result["onset_day"] is None
        result = _normalize_complication({"name": "x", "onset_day": 3.7})
        assert result["onset_day"] == 3

    def test_non_dict_non_str_stringifies(self):
        """Defensive path — any other type gets str()-coerced to a name."""
        result = _normalize_complication(42)
        assert result["name"] == "42"
        assert result["source"] == "unknown"


class TestComplicationNames:
    def test_projection_preserves_order(self):
        entries = [
            "pneumothorax",
            {"name": "seizure", "onset_day": 2},
            {"name": "aki", "onset_day": 5},
        ]
        assert complication_names(entries) == ["pneumothorax", "seizure", "aki"]

    def test_empty_input_returns_empty(self):
        assert complication_names(None) == []
        assert complication_names([]) == []

    def test_empty_name_entries_dropped(self):
        """An empty name would poison set-membership checks (e.g. metformin
        contraindication) so it is dropped from the projection."""
        entries = [{"name": ""}, {"name": "aki"}]
        assert complication_names(entries) == ["aki"]


class TestBuildComplication:
    def test_returns_canonical_shape(self):
        result = build_complication(
            name="aki",
            onset_day=3,
            onset_datetime="2026-04-01T12:00:00",
            source="daily_loop",
        )
        assert result == {
            "name": "aki",
            "onset_day": 3,
            "onset_datetime": "2026-04-01T12:00:00",
            "source": "daily_loop",
        }

    def test_rejects_unknown_source(self):
        """Producer-side allowlist — a typo like 'daily_looop' fails fast
        rather than landing in the CIF where consumers would silently
        classify it as ``unknown`` on read."""
        with pytest.raises(ValueError, match="Unknown complication source"):
            build_complication(
                name="aki",
                onset_day=1,
                onset_datetime=None,
                source="daily_looop",
            )

    def test_none_onset_day_permitted(self):
        """Scenario-forced complications carry no timing; ``None`` is a
        legitimate value that consumers filter accordingly."""
        result = build_complication(
            name="forced",
            onset_day=None,
            onset_datetime=None,
            source="scenario_forced",
        )
        assert result["onset_day"] is None
        assert result["onset_datetime"] is None

    def test_all_documented_sources_accepted(self):
        """Every source token in SOURCES must be usable at construction."""
        for src in SOURCES:
            result = build_complication(name="x", onset_day=None, onset_datetime=None, source=src)
            assert result["source"] == src
