"""Unit tests for `primary_condition_ref` — single source of truth for
resolving the Condition id representing an encounter's primary reason.

The chronic-primary suppression (session 88j) hinges on all downstream
emitters (Encounter.reasonReference, Encounter.diagnosis[0].condition,
Procedure.reasonReference, MedicationRequest.reasonReference,
Composition eDS diagnosesOnDischarge entry) agreeing on the same
Condition id. This test lock in the resolution rules so a regression
in the helper trips one place instead of many.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
    chronic_condition_id,
    encounter_primary_condition_id,
    is_chronic_primary,
    primary_condition_ref,
    primary_condition_ref_from_codes,
)

pytestmark = pytest.mark.unit


def _record(dx: str, chronic_codes: list[str] | None = None) -> dict:
    chronics = [{"code": c, "onset_date": "2020-01-01"} for c in (chronic_codes or [])]
    return {
        "clinical_diagnosis": {"discharge_diagnosis_code": dx},
        "patient": {"chronic_conditions": chronics},
    }


def test_chronic_primary_resolves_to_chronic_id() -> None:
    """Encounter dx `I10` matches chronic `I10` at index 0 → chronic id."""
    assert primary_condition_ref(_record("I10", ["I10", "E11"]), "PAT", "ENC-1") == chronic_condition_id("PAT", 0)
    # Chronic at index 1
    assert primary_condition_ref(_record("E11.9", ["I10", "E11"]), "PAT", "ENC-1") == chronic_condition_id("PAT", 1)


def test_specific_dx_matches_base_chronic() -> None:
    """Encounter dx `I50.9` matches chronic `I50` (base I50) → chronic id."""
    assert primary_condition_ref(_record("I50.9", ["I50"]), "PAT", "ENC-HF") == chronic_condition_id("PAT", 0)


def test_base_chronic_matches_specific_dx() -> None:
    """Encounter dx `I50` matches chronic `I50.9` (base I50) → chronic id."""
    assert primary_condition_ref(_record("I50", ["I50.9"]), "PAT", "ENC-HF") == chronic_condition_id("PAT", 0)


def test_no_chronic_match_returns_encounter_scoped_id() -> None:
    """Acute dx (Z00.0 screening) with unrelated chronics → cond-{enc}-primary."""
    assert primary_condition_ref(_record("Z00.0", ["I10"]), "PAT", "ENC-CHK") == encounter_primary_condition_id(
        "PAT", "ENC-CHK"
    )


def test_no_dx_returns_encounter_scoped_id() -> None:
    """No dx code (rare — usually a Z-code fills in) → still cond-{enc}-primary."""
    assert primary_condition_ref(_record(""), "PAT", "ENC-1") == encounter_primary_condition_id("PAT", "ENC-1")


def test_no_encounter_id_falls_back_to_patient_scope() -> None:
    """Defensive path — no encounter_id available at all."""
    assert primary_condition_ref(_record(""), "PAT", "") == encounter_primary_condition_id("PAT", "")


def test_admission_dx_fallback_when_discharge_missing() -> None:
    """Admission-only dx (e.g. still-inpatient snapshot) is treated the same."""
    record = {
        "clinical_diagnosis": {"admission_diagnosis_code": "E11.9"},
        "patient": {"chronic_conditions": [{"code": "E11"}]},
    }
    assert primary_condition_ref(record, "PAT", "ENC-1") == chronic_condition_id("PAT", 0)


def test_is_chronic_primary_bool_predicate() -> None:
    assert is_chronic_primary(_record("I10", ["I10"])) is True
    assert is_chronic_primary(_record("J06.9", ["I10"])) is False
    assert is_chronic_primary(_record("", ["I10"])) is False


def test_from_codes_variant_matches_full_record_variant() -> None:
    """The from_codes variant is a shortcut for callers who already have
    primary_dx_code + chronic_condition_codes extracted (encounter builder)."""
    rec = _record("I50.9", ["I50"])
    from_full = primary_condition_ref(rec, "PAT", "ENC-1")
    from_codes = primary_condition_ref_from_codes("I50.9", ["I50"], "PAT", "ENC-1")
    assert from_full == from_codes == chronic_condition_id("PAT", 0)


def test_from_codes_variant_handles_none_and_empty() -> None:
    assert primary_condition_ref_from_codes("Z00.0", None, "PAT", "ENC-1") == encounter_primary_condition_id(
        "PAT", "ENC-1"
    )
    assert primary_condition_ref_from_codes("Z00.0", [], "PAT", "ENC-1") == encounter_primary_condition_id(
        "PAT", "ENC-1"
    )
    assert primary_condition_ref_from_codes("", ["I10"], "PAT", "ENC-1") == encounter_primary_condition_id(
        "PAT", "ENC-1"
    )


def test_string_chronic_entry() -> None:
    """Chronic entries can be bare strings (legacy CIF path) instead of dicts."""
    record = {
        "clinical_diagnosis": {"discharge_diagnosis_code": "I10"},
        "patient": {"chronic_conditions": ["I10", "E11"]},
    }
    assert primary_condition_ref(record, "PAT", "ENC-1") == chronic_condition_id("PAT", 0)
