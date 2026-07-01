"""Unit tests for nursing engine (Tier 1 #3 α-min-2 Task 4)."""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.nursing.engine import (
    INPATIENT_ENCOUNTER_TYPES,
    SUPPORTED_ADL_CATEGORIES,
    SUPPORTED_RISK_ASSESSMENTS,
    assign_primary_nurse,
    load_nursing_assessment,
)
from clinosim.types.staff import StaffMember, StaffRoster


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_supported_adl_categories_contains_required():
    assert SUPPORTED_ADL_CATEGORIES == frozenset(
        {"eating", "bathing", "dressing", "toileting", "mobility"}
    )


def test_supported_risk_assessments_contains_required():
    assert SUPPORTED_RISK_ASSESSMENTS == frozenset(
        {"fall_risk", "pressure_ulcer_risk", "aspiration_risk"}
    )


def test_inpatient_encounter_types():
    assert INPATIENT_ENCOUNTER_TYPES == frozenset({"inpatient", "icu", "rehab_inpatient"})


# ---------------------------------------------------------------------------
# load_nursing_assessment
# ---------------------------------------------------------------------------


def test_load_nursing_assessment_returns_valid_structure():
    a = load_nursing_assessment()
    assert "adl_categories" in a
    assert "risk_assessments" in a
    assert "disease_specific_nursing_focus" in a
    assert "baseline" in a


def test_load_nursing_assessment_cached():
    """@lru_cache(maxsize=1) — same object on repeated calls."""
    assert load_nursing_assessment() is load_nursing_assessment()


def test_nursing_assessment_adl_keys():
    a = load_nursing_assessment()
    adl = a["adl_categories"]
    assert set(adl.keys()) == SUPPORTED_ADL_CATEGORIES


def test_nursing_assessment_risk_keys():
    a = load_nursing_assessment()
    risk = a["risk_assessments"]
    assert set(risk.keys()) == SUPPORTED_RISK_ASSESSMENTS


def test_nursing_assessment_baseline_has_required_fields():
    a = load_nursing_assessment()
    baseline = a["baseline"]
    assert "focus" in baseline
    assert "interventions_ja" in baseline
    assert isinstance(baseline["interventions_ja"], list)


def test_nursing_assessment_disease_entries_have_required_fields():
    a = load_nursing_assessment()
    disease_focus = a["disease_specific_nursing_focus"]
    for disease_id, entry in disease_focus.items():
        assert "focus" in entry, f"disease {disease_id!r} missing 'focus'"
        assert "interventions_ja" in entry, f"disease {disease_id!r} missing 'interventions_ja'"
        assert isinstance(entry["interventions_ja"], list), (
            f"disease {disease_id!r}: interventions_ja must be a list"
        )


def test_nursing_assessment_required_diseases_present():
    """Spec §4.2: at minimum these 5 disease entries must be present."""
    a = load_nursing_assessment()
    disease_focus = a["disease_specific_nursing_focus"]
    required = {
        "bacterial_pneumonia",
        "aspiration_pneumonia",
        "hemorrhagic_stroke",
        "acute_mi",
        "heart_failure_exacerbation",
    }
    missing = required - set(disease_focus.keys())
    assert not missing, f"Missing required disease entries: {sorted(missing)}"


# ---------------------------------------------------------------------------
# assign_primary_nurse
# ---------------------------------------------------------------------------


def _make_roster_with_nurses() -> StaffRoster:
    return StaffRoster(
        members=[
            StaffMember(
                staff_id="NS-001", name="Nurse A", role="nurse", department="internal_medicine"
            ),
            StaffMember(
                staff_id="NS-002", name="Nurse B", role="nurse", department="internal_medicine"
            ),
            StaffMember(
                staff_id="MD-001", name="Doctor A", role="physician", department="internal_medicine"
            ),
        ]
    )


def _make_empty_roster() -> StaffRoster:
    return StaffRoster(members=[])


def test_assign_primary_nurse_returns_from_roster():
    from types import SimpleNamespace

    roster = _make_roster_with_nurses()
    enc = SimpleNamespace(encounter_id="e1", encounter_type="inpatient")
    rng = np.random.default_rng(42)
    nurse_id = assign_primary_nurse(enc, roster, rng)
    assert nurse_id in {"NS-001", "NS-002"}


def test_assign_primary_nurse_excludes_physicians():
    """Only nurses should be assigned, not physicians."""
    from types import SimpleNamespace

    roster = _make_roster_with_nurses()
    enc = SimpleNamespace(encounter_id="e1", encounter_type="inpatient")
    rng = np.random.default_rng(42)
    for _ in range(50):
        nurse_id = assign_primary_nurse(enc, roster, rng)
        assert nurse_id != "MD-001", "Physician should not be selected as primary nurse"


def test_assign_primary_nurse_empty_roster_returns_empty_string():
    from types import SimpleNamespace

    roster = _make_empty_roster()
    enc = SimpleNamespace(encounter_id="e1", encounter_type="inpatient")
    rng = np.random.default_rng(42)
    result = assign_primary_nurse(enc, roster, rng)
    assert result == ""


def test_assign_primary_nurse_deterministic():
    from types import SimpleNamespace

    roster = _make_roster_with_nurses()
    enc = SimpleNamespace(encounter_id="e1", encounter_type="inpatient")
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(42)
    result1 = assign_primary_nurse(enc, roster, rng1)
    result2 = assign_primary_nurse(enc, roster, rng2)
    assert result1 == result2


def test_assign_primary_nurse_returns_str():
    from types import SimpleNamespace

    roster = _make_roster_with_nurses()
    enc = SimpleNamespace(encounter_id="e1", encounter_type="inpatient")
    rng = np.random.default_rng(42)
    result = assign_primary_nurse(enc, roster, rng)
    assert isinstance(result, str)
