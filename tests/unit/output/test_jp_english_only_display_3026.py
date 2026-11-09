"""JP codings of English-only code systems keep the English display (Issue #3026)."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.labs.observations import _build_vital_observations

pytestmark = pytest.mark.unit


def test_a_jp_heart_rate_observation_has_the_english_loinc_display_and_japanese_text() -> None:
    entries = _build_vital_observations({"heart_rate": 80, "timestamp": "2026-01-01T10:00:00"}, "P1", 0, "JP", "E1")
    obs = next(e["resource"] for e in entries if e["resource"]["code"]["coding"][0]["code"] == "8867-4")
    assert obs["code"]["coding"][0]["display"] == "Heart rate"
    assert obs["code"]["text"] == "脈拍"
