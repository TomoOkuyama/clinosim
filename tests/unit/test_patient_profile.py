"""AD-66 α-min-2c: PatientProfile Pydantic type + loader tests."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.types.config import (
    ForcedScenario,
    PatientProfile,
    load_patient_profile,
)

# --- Basic construction ---

def test_patient_profile_minimal_construction():
    """PatientProfile with only required fields works."""
    profile = PatientProfile(
        profile_id="test_minimal",
        disease_id="bacterial_pneumonia",
    )
    assert profile.profile_id == "test_minimal"
    assert profile.disease_id == "bacterial_pneumonia"
    assert profile.country == "US"  # default
    assert profile.severity is None
    assert profile.archetype is None
    assert profile.count == 1
    assert profile.random_seed == 42
    assert profile.hospital_scale == "medium"
    assert profile.patient_overrides == {}
    assert profile.force_hai_event is None
    assert profile.chronic_medications == []


def test_patient_profile_full_construction():
    """PatientProfile with all fields."""
    profile = PatientProfile(
        profile_id="full_test",
        disease_id="sepsis",
        country="JP",
        severity="severe",
        archetype="dip_then_recovery",
        count=1,
        random_seed=42,
        hospital_scale="large",
        patient_overrides={"age": 72, "sex": "M"},
        force_hai_event={
            "hai_type": "clabsi",
            "onset_offset_days": 3,
            "organism_snomed": "3092008",
        },
        chronic_medications=["6809"],  # metformin RxNorm code
        description="Full test profile",
        clinical_notes="Multi-line\nclinical notes",
    )
    assert profile.country == "JP"
    assert profile.force_hai_event["hai_type"] == "clabsi"
    assert profile.chronic_medications == ["6809"]


# --- Validation: extras forbidden ---

def test_patient_profile_rejects_unknown_keys():
    """Pydantic model_config = {'extra': 'forbid'} rejects typo'd YAML keys."""
    with pytest.raises(Exception) as exc_info:
        PatientProfile(
            profile_id="typo_test",
            disease_id="bacterial_pneumonia",
            typo_field="oops",  # unknown key
        )
    # Pydantic v2 raises ValidationError; be liberal on match
    assert "typo_field" in str(exc_info.value) or "extra" in str(exc_info.value).lower()


# --- Validation: country enum ---

def test_patient_profile_rejects_unknown_country():
    """Only US and JP are accepted."""
    with pytest.raises(Exception):
        PatientProfile(
            profile_id="bad_country",
            disease_id="bacterial_pneumonia",
            country="FR",
        )


# --- Validation: severity enum ---

def test_patient_profile_severity_none_is_valid():
    profile = PatientProfile(
        profile_id="sev_none",
        disease_id="bacterial_pneumonia",
        severity=None,
    )
    assert profile.severity is None


def test_patient_profile_severity_mild_moderate_severe():
    for sev in ("mild", "moderate", "severe"):
        profile = PatientProfile(
            profile_id=f"sev_{sev}",
            disease_id="bacterial_pneumonia",
            severity=sev,
        )
        assert profile.severity == sev


def test_patient_profile_rejects_unknown_severity():
    with pytest.raises(Exception):
        PatientProfile(
            profile_id="bad_sev",
            disease_id="bacterial_pneumonia",
            severity="critical",  # not in enum
        )


# --- to_forced_scenario transform ---

def test_to_forced_scenario_round_trips_relevant_fields():
    """PatientProfile.to_forced_scenario() preserves all ForcedScenario-relevant fields."""
    profile = PatientProfile(
        profile_id="fs_transform",
        disease_id="sepsis",
        severity="severe",
        archetype="dip_then_recovery",
        count=1,
        patient_overrides={"age": 65},
        force_hai_event={
            "hai_type": "clabsi",
            "onset_offset_days": 3,
            "organism_snomed": "3092008",
        },
    )
    scenario = profile.to_forced_scenario()
    assert isinstance(scenario, ForcedScenario)
    assert scenario.disease_id == "sepsis"
    assert scenario.severity == "severe"
    assert scenario.archetype == "dip_then_recovery"
    assert scenario.count == 1
    assert scenario.patient_overrides == {"age": 65}
    assert scenario.force_hai_event["hai_type"] == "clabsi"


# --- Loader: by name (default fixture dir) ---

def test_load_patient_profile_by_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """load_patient_profile('name') resolves via fixtures directory."""
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    yaml_path = fixture_dir / "test_by_name.yaml"
    yaml_path.write_text(yaml.safe_dump({
        "profile_id": "test_by_name",
        "disease_id": "bacterial_pneumonia",
        "country": "JP",
        "severity": "moderate",
    }))

    # Override the fixture dir lookup for this test
    from clinosim.types import config as config_module
    monkeypatch.setattr(config_module, "_PATIENT_PROFILE_DIR", fixture_dir)

    profile = load_patient_profile("test_by_name")
    assert profile.profile_id == "test_by_name"
    assert profile.country == "JP"


# --- Loader: by absolute path ---

def test_load_patient_profile_by_path(tmp_path: Path):
    """load_patient_profile('/abs/path.yaml') loads the file directly."""
    yaml_path = tmp_path / "custom_location.yaml"
    yaml_path.write_text(yaml.safe_dump({
        "profile_id": "custom_location",
        "disease_id": "sepsis",
    }))

    profile = load_patient_profile(str(yaml_path))
    assert profile.profile_id == "custom_location"
    assert profile.disease_id == "sepsis"


# --- Loader: profile_id / filename mismatch = raise ---

def test_load_patient_profile_id_filename_mismatch_raises(tmp_path: Path):
    """profile_id in YAML must match filename stem (silent-no-op defense)."""
    yaml_path = tmp_path / "actual_name.yaml"
    yaml_path.write_text(yaml.safe_dump({
        "profile_id": "different_name",  # mismatch
        "disease_id": "bacterial_pneumonia",
    }))

    with pytest.raises(ValueError, match="profile_id"):
        load_patient_profile(str(yaml_path))


# --- Loader: file not found ---

def test_load_patient_profile_missing_file_raises():
    """load_patient_profile with unknown name raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_patient_profile("nonexistent_profile_id_12345")
