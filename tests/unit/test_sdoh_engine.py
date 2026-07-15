"""Unit tests for clinosim.modules.sdoh.engine.load_social_history."""

from __future__ import annotations

import pytest

from clinosim.modules.sdoh import load_social_history


@pytest.mark.unit
def test_load_social_history_has_topics():
    data = load_social_history()
    assert "smoking_status" in data
    assert "alcohol_use" in data


@pytest.mark.unit
def test_smoking_status_loinc():
    data = load_social_history()
    assert data["smoking_status"]["loinc"] == "72166-2"


@pytest.mark.unit
def test_alcohol_use_loinc():
    data = load_social_history()
    assert data["alcohol_use"]["loinc"] == "11331-6"


@pytest.mark.unit
def test_smoking_status_3_tiers():
    data = load_social_history()
    assert set(data["smoking_status"]["values"].keys()) == {"never", "former", "current"}


@pytest.mark.unit
def test_alcohol_use_3_tiers():
    data = load_social_history()
    assert set(data["alcohol_use"]["values"].keys()) == {"none", "social", "heavy"}


@pytest.mark.unit
def test_snomed_codes_match_pre_refactor():
    """Pin the 6 SNOMED codes from the pre-PR2 _fhir_sdoh.py hardcoded dicts.

    Regression guard — if anyone "improves" the YAML and changes a code,
    this test catches it BEFORE byte-diff would (which is a slower
    feedback loop)."""
    data = load_social_history()
    assert data["smoking_status"]["values"]["never"]["snomed"] == "266919005"
    assert data["smoking_status"]["values"]["former"]["snomed"] == "8517006"
    assert data["smoking_status"]["values"]["current"]["snomed"] == "449868002"
    assert data["alcohol_use"]["values"]["none"]["snomed"] == "105542008"
    assert data["alcohol_use"]["values"]["social"]["snomed"] == "28127009"
    assert data["alcohol_use"]["values"]["heavy"]["snomed"] == "86933000"


@pytest.mark.unit
def test_lru_cache_returns_same_object():
    """load_social_history is @lru_cache decorated so repeat calls return
    the same dict instance (avoids repeated YAML reads)."""
    a = load_social_history()
    b = load_social_history()
    assert a is b
