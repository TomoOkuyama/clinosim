"""Tests for document module reference data loaders (Task 5).

Tests cover:
- physical_exam_findings.yaml: smoke load, baseline key presence, validator errors, cache
- discharge_instructions.yaml: smoke load, baseline key presence, validator errors, cache
"""

from __future__ import annotations

import pytest

import clinosim.modules.document.reference_data_loaders as rdl

# ─────────────────────────────────────────────────────────────────
# physical_exam_findings
# ─────────────────────────────────────────────────────────────────


def test_physical_exam_findings_loads() -> None:
    """Smoke test: loader returns a non-empty dict."""
    data = rdl.load_physical_exam_findings()
    assert isinstance(data, dict)
    assert data


def test_physical_exam_findings_has_baseline() -> None:
    """Top-level 'baseline' key must be present."""
    data = rdl.load_physical_exam_findings()
    assert "baseline" in data


def test_physical_exam_findings_baseline_has_uncomplicated_improvement() -> None:
    """baseline.uncomplicated_improvement must exist with day_0."""
    data = rdl.load_physical_exam_findings()
    baseline = data["baseline"]
    assert "uncomplicated_improvement" in baseline
    arch = baseline["uncomplicated_improvement"]
    assert "day_0" in arch


def test_physical_exam_findings_baseline_day_0_has_body_system() -> None:
    """baseline.uncomplicated_improvement.day_0 must have at least one body system."""
    data = rdl.load_physical_exam_findings()
    day_0 = data["baseline"]["uncomplicated_improvement"]["day_0"]
    body_systems = {"general", "cardiovascular", "respiratory", "abdominal", "neurological"}
    assert any(s in day_0 for s in body_systems)


def test_physical_exam_findings_has_findings_section() -> None:
    """Top-level 'findings' key for per-disease overrides must be present."""
    data = rdl.load_physical_exam_findings()
    assert "findings" in data


def test_physical_exam_findings_bacterial_pneumonia_override() -> None:
    """bacterial_pneumonia per-disease override must be present in findings."""
    data = rdl.load_physical_exam_findings()
    assert "bacterial_pneumonia" in data["findings"]
    bp = data["findings"]["bacterial_pneumonia"]
    assert "uncomplicated_improvement" in bp
    assert "day_0" in bp["uncomplicated_improvement"]


def test_physical_exam_findings_validator_raises_on_empty() -> None:
    """Layer 3: validator raises ValueError on empty top-level dict."""
    with pytest.raises(ValueError, match="empty top-level"):
        rdl._validate_physical_exam_findings({})


def test_physical_exam_findings_validator_raises_on_missing_baseline() -> None:
    """Layer 3: validator raises ValueError when 'baseline' key absent."""
    with pytest.raises(ValueError, match="missing 'baseline'"):
        rdl._validate_physical_exam_findings({"findings": {}})


def test_physical_exam_findings_validator_raises_on_missing_required_field() -> None:
    """Layer 6: validator raises ValueError when baseline.uncomplicated_improvement absent."""
    bad = {
        "baseline": {"other_archetype": {"day_0": {"general": {"all": "ok"}}}},
        "findings": {},
    }
    with pytest.raises(ValueError, match="uncomplicated_improvement"):
        rdl._validate_physical_exam_findings(bad)


def test_physical_exam_findings_validator_raises_on_missing_day_0() -> None:
    """Layer 4: archetype without day_0 raises ValueError."""
    bad = {
        "baseline": {"uncomplicated_improvement": {"day_3": {"general": "ok"}}},
        "findings": {},
    }
    with pytest.raises(ValueError, match="day_0"):
        rdl._validate_physical_exam_findings(bad)


def test_physical_exam_findings_validator_raises_on_no_body_system() -> None:
    """Layer 5: day_0 with no recognised body-system key raises ValueError."""
    bad = {
        "baseline": {"uncomplicated_improvement": {"day_0": {"unknown_sys": "ok"}}},
        "findings": {},
    }
    with pytest.raises(ValueError, match="body-system"):
        rdl._validate_physical_exam_findings(bad)


def test_physical_exam_findings_validator_raises_on_missing_findings_key() -> None:
    """Layer 6: top-level findings key missing raises ValueError."""
    bad = {"baseline": {"uncomplicated_improvement": {"day_0": {"general": "ok"}}}}
    with pytest.raises(ValueError, match="findings"):
        rdl._validate_physical_exam_findings(bad)


def test_physical_exam_findings_cached_lru() -> None:
    """@lru_cache(maxsize=1): two calls return the same object."""
    rdl.load_physical_exam_findings.cache_clear()
    first = rdl.load_physical_exam_findings()
    second = rdl.load_physical_exam_findings()
    assert first is second


# ─────────────────────────────────────────────────────────────────
# discharge_instructions
# ─────────────────────────────────────────────────────────────────


def test_discharge_instructions_loads() -> None:
    """Smoke test: loader returns a non-empty dict."""
    data = rdl.load_discharge_instructions()
    assert isinstance(data, dict)
    assert data


def test_discharge_instructions_has_baseline() -> None:
    """Top-level 'baseline' key must be present."""
    data = rdl.load_discharge_instructions()
    assert "baseline" in data


def test_discharge_instructions_baseline_has_required_keys() -> None:
    """baseline must contain at minimum: hydrate, rest, follow_up."""
    data = rdl.load_discharge_instructions()
    baseline = data["baseline"]
    for key in ("hydrate", "rest", "follow_up"):
        assert key in baseline, f"baseline missing key: {key}"


def test_discharge_instructions_baseline_entries_have_en_ja() -> None:
    """Each baseline entry must have both 'en' and 'ja' fields."""
    data = rdl.load_discharge_instructions()
    for key, entry in data["baseline"].items():
        assert "en" in entry, f"baseline[{key}] missing 'en'"
        assert "ja" in entry, f"baseline[{key}] missing 'ja'"


def test_discharge_instructions_has_disease_specific_section() -> None:
    """Top-level 'disease_specific' key must be present."""
    data = rdl.load_discharge_instructions()
    assert "disease_specific" in data


def test_discharge_instructions_bacterial_pneumonia_override() -> None:
    """bacterial_pneumonia per-disease override must be present."""
    data = rdl.load_discharge_instructions()
    assert "bacterial_pneumonia" in data["disease_specific"]


def test_discharge_instructions_validator_raises_on_empty() -> None:
    """Layer 3: validator raises ValueError on empty top-level dict."""
    with pytest.raises(ValueError, match="empty top-level"):
        rdl._validate_discharge_instructions({})


def test_discharge_instructions_validator_raises_on_missing_baseline() -> None:
    """Layer 3: validator raises ValueError when 'baseline' key absent."""
    with pytest.raises(ValueError, match="missing 'baseline'"):
        rdl._validate_discharge_instructions({"disease_specific": {}})


def test_discharge_instructions_validator_raises_on_missing_required_field() -> None:
    """Layer 6: validator raises ValueError when baseline missing required key."""
    bad = {
        "baseline": {
            "hydrate": {"en": "Drink fluids.", "ja": "水分摂取。"},
            # rest missing
            "follow_up": {"en": "Follow up.", "ja": "外来受診。"},
        },
        "disease_specific": {},
    }
    with pytest.raises(ValueError, match="rest"):
        rdl._validate_discharge_instructions(bad)


def test_discharge_instructions_validator_raises_on_missing_en_field() -> None:
    """Layer 6: validator raises ValueError when baseline entry missing 'en'."""
    bad = {
        "baseline": {
            "hydrate": {"ja": "水分摂取。"},  # 'en' missing
            "rest": {"en": "Rest.", "ja": "休息。"},
            "follow_up": {"en": "Follow up.", "ja": "外来受診。"},
        },
        "disease_specific": {},
    }
    with pytest.raises(ValueError, match="missing 'en'"):
        rdl._validate_discharge_instructions(bad)


def test_discharge_instructions_validator_raises_on_disease_specific_missing_ja() -> None:
    """disease_specific entry missing 'ja' key raises ValueError."""
    bad = {
        "baseline": {
            "hydrate": {"en": "Drink fluids.", "ja": "水分を取りましょう。"},
            "rest": {"en": "Rest.", "ja": "休息を。"},
            "follow_up": {"en": "Follow up.", "ja": "受診を。"},
        },
        "disease_specific": {
            "bacterial_pneumonia": {
                "follow_up": {"en": "Follow up with PCP."},  # missing ja
            },
        },
    }
    with pytest.raises(ValueError, match="ja"):
        rdl._validate_discharge_instructions(bad)


def test_discharge_instructions_cached_lru() -> None:
    """@lru_cache(maxsize=1): two calls return the same object."""
    rdl.load_discharge_instructions.cache_clear()
    first = rdl.load_discharge_instructions()
    second = rdl.load_discharge_instructions()
    assert first is second
