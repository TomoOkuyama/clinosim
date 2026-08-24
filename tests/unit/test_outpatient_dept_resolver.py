"""Unit tests for the outpatient follow-up department resolver."""

from __future__ import annotations

import pytest

from clinosim.simulator.outpatient_dept import resolve_outpatient_department


@pytest.fixture
def hospital_ops():
    """Community-hospital shaped config with rollup for OPD specialties."""
    return {
        "available_departments": [
            "internal_medicine",
            "cardiology",
            "gastroenterology",
            "general_surgery",
            "orthopedics",
            "emergency_medicine",
            "primary_care",
        ],
        "department_rollup": {
            "pulmonology": "internal_medicine",
            "nephrology": "internal_medicine",
            "endocrinology": "internal_medicine",
            "neurology": "internal_medicine",
            "neurosurgery": "general_surgery",
            "trauma_surgery": "general_surgery",
            "pediatrics": "primary_care",
            "obgyn": "primary_care",
            "dermatology": "primary_care",
        },
    }


@pytest.fixture
def tiny_clinic():
    """No specialties available beyond internal_medicine / ER / OPD."""
    return {
        "available_departments": ["internal_medicine", "emergency_medicine", "primary_care"],
        "department_rollup": {
            "cardiology": "internal_medicine",
            "gastroenterology": "internal_medicine",
            "orthopedics": "internal_medicine",
            "pediatrics": "primary_care",
            "obgyn": "primary_care",
        },
    }


def test_post_discharge_inherits_prior_department(hospital_ops):
    """Trauma inpatient in general_surgery must be followed up in general_surgery."""
    dept = resolve_outpatient_department("post_discharge", "T07", "general_surgery", hospital_ops)
    assert dept == "general_surgery"


def test_post_discharge_from_cardiology_stays_in_cardiology(hospital_ops):
    dept = resolve_outpatient_department("post_discharge", "I50", "cardiology", hospital_ops)
    assert dept == "cardiology"


def test_post_discharge_from_orthopedics(hospital_ops):
    dept = resolve_outpatient_department("post_discharge", "S72", "orthopedics", hospital_ops)
    assert dept == "orthopedics"


def test_post_discharge_from_gastroenterology(hospital_ops):
    dept = resolve_outpatient_department("post_discharge", "K57", "gastroenterology", hospital_ops)
    assert dept == "gastroenterology"


def test_post_discharge_without_prior_dept_falls_back(hospital_ops):
    """Defensive: if prior dept is unknown, use specialty inference."""
    dept = resolve_outpatient_department("post_discharge", "T07", None, hospital_ops)
    # No prior + T07 not in chronic map → internal_medicine fallback
    assert dept == "internal_medicine"


def test_chronic_ihd_routes_to_cardiology(hospital_ops):
    dept = resolve_outpatient_department("chronic_followup", "I25", None, hospital_ops)
    assert dept == "cardiology"


def test_chronic_afib_routes_to_cardiology(hospital_ops):
    dept = resolve_outpatient_department("chronic_followup", "I48", None, hospital_ops)
    assert dept == "cardiology"


def test_chronic_heart_failure_routes_to_cardiology(hospital_ops):
    dept = resolve_outpatient_department("chronic_followup", "I50", None, hospital_ops)
    assert dept == "cardiology"


def test_chronic_htn_stays_in_internal_medicine(hospital_ops):
    """I10 uncomplicated HTN is 内科 in Japanese primary care reality."""
    dept = resolve_outpatient_department("chronic_followup", "I10", None, hospital_ops)
    assert dept == "internal_medicine"


def test_chronic_dm_stays_in_internal_medicine(hospital_ops):
    """E11 DM: endocrinology → rollup → internal_medicine."""
    dept = resolve_outpatient_department("chronic_followup", "E11.9", None, hospital_ops)
    assert dept == "internal_medicine"


def test_chronic_copd_rolls_up_to_internal_medicine(hospital_ops):
    """J44 not in chronic-map (falls through), but internal_medicine is
    the correct dept because pulmonology rolls up to internal_medicine."""
    dept = resolve_outpatient_department("chronic_followup", "J44", None, hospital_ops)
    assert dept == "internal_medicine"


def test_chronic_osteoporosis_routes_to_orthopedics(hospital_ops):
    dept = resolve_outpatient_department("chronic_followup", "M81", None, hospital_ops)
    assert dept == "orthopedics"


def test_chronic_gastro_routes_to_gastroenterology(hospital_ops):
    dept = resolve_outpatient_department("chronic_followup", "K21", None, hospital_ops)
    assert dept == "gastroenterology"


def test_screening_colonoscopy_routes_to_gastroenterology(hospital_ops):
    dept = resolve_outpatient_department("health_screening", "colonoscopy_screening", None, hospital_ops)
    assert dept == "gastroenterology"


def test_screening_annual_routes_to_primary_care(hospital_ops):
    dept = resolve_outpatient_department("health_screening", "annual_health_screening", None, hospital_ops)
    assert dept == "primary_care"


def test_screening_mammography_falls_back_to_primary_care(hospital_ops):
    """obgyn is not staffed here → rollup → primary_care."""
    dept = resolve_outpatient_department("health_screening", "mammography_screening", None, hospital_ops)
    assert dept == "primary_care"


def test_pediatric_visit_falls_back_to_primary_care(hospital_ops):
    """pediatrics is not staffed at this community hospital → primary_care."""
    dept = resolve_outpatient_department("pediatric_visit", "well_child_infant", None, hospital_ops)
    assert dept == "primary_care"


def test_tiny_clinic_falls_back_everywhere_to_internal_medicine(tiny_clinic):
    """Tiny clinic rollup collapses cardiology / gastro / ortho → 内科."""
    assert resolve_outpatient_department("chronic_followup", "I25", None, tiny_clinic) == "internal_medicine"
    assert resolve_outpatient_department("chronic_followup", "M81", None, tiny_clinic) == "internal_medicine"
    # colonoscopy → gastroenterology → rollup → internal_medicine
    assert (
        resolve_outpatient_department("health_screening", "colonoscopy_screening", None, tiny_clinic)
        == "internal_medicine"
    )


def test_tiny_clinic_pediatric_to_primary_care(tiny_clinic):
    dept = resolve_outpatient_department("pediatric_visit", "well_child_infant", None, tiny_clinic)
    assert dept == "primary_care"


def test_null_hospital_ops_returns_specialty_or_fallback():
    """With no hospital_ops given, resolver returns the specialty verbatim
    (or internal_medicine for unmapped chronic codes)."""
    assert resolve_outpatient_department("post_discharge", "", "general_surgery", None) == "general_surgery"
    assert resolve_outpatient_department("chronic_followup", "I25", None, None) == "cardiology"
    assert resolve_outpatient_department("chronic_followup", "I10", None, None) == "internal_medicine"


def test_unknown_visit_type_defaults_to_internal_medicine(hospital_ops):
    dept = resolve_outpatient_department("something_new", "I25", None, hospital_ops)
    assert dept == "internal_medicine"


def test_empty_chronic_code_falls_back(hospital_ops):
    dept = resolve_outpatient_department("chronic_followup", "", None, hospital_ops)
    assert dept == "internal_medicine"
