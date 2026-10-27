"""Context-dependent complication risk factors resolve from the stay (#2101)."""

from __future__ import annotations

import pytest

from clinosim.modules.clinical_course._complication_risk_conditions import CONTEXT_CONDITIONS, ComplicationContext
from clinosim.modules.clinical_course.engine import _evaluate_risk_condition, is_supported_risk_condition
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit


def _ev(cond: str, ctx: ComplicationContext | None, day: int = 5, patient: PatientProfile | None = None) -> bool:
    return _evaluate_risk_condition(cond, PhysiologicalState(), patient or PatientProfile(), day, "moderate", ctx)


def test_icu_and_ventilation_days() -> None:
    ctx = ComplicationContext(icu_day=1, intubated_day=2)
    assert _ev("icu_stay", ctx) and _ev("mechanical_ventilation", ctx) and _ev("intubation", ctx)
    assert not _ev("icu_stay_over_7_days", ctx) and _ev("icu_stay_over_7_days", ctx, day=9)
    assert not _ev("icu_stay", ComplicationContext())


def test_drug_exposure_from_active_orders_and_home_meds() -> None:
    ctx = ComplicationContext(
        medications={"MORPHINE", "ENOXAPARIN", "LEVOFLOXACIN"}, home_medications={"PREDNISOLONE", "APIXABAN"}
    )
    for cond in ("opioid_use", "anticoagulation", "fluoroquinolone_use", "chronic_steroid_use"):
        assert _ev(cond, ctx), cond
    assert not _ev("no_dvt_prophylaxis", ctx)
    assert _ev("no_dvt_prophylaxis", ComplicationContext(medications={"CEFTRIAXONE"}))
    assert not _ev("NSAID_use", ctx)


def test_devices_surgery_and_antibiotic_duration() -> None:
    ctx = ComplicationContext(
        procedure_types={"urinary_catheter", "central_line"}, surgery_day=1, antibiotic_start_day=0
    )
    assert _ev("urinary_catheter", ctx) and _ev("central_line_present", ctx)
    assert _ev("surgical_patient", ctx) and _ev("recent_surgery", ctx)
    assert not _ev("antibiotic_duration_over_7_days", ctx) and _ev("antibiotic_duration_over_7_days", ctx, day=8)


def test_immunosuppressed_from_problem_list() -> None:
    patient = PatientProfile(chronic_conditions=[ChronicCondition(code="Z94.0")])
    assert _ev("immunosuppressed", ComplicationContext(), patient=patient)


def test_resolved_conditions_left_the_context_list() -> None:
    for cond in ("icu_stay", "no_dvt_prophylaxis", "opioid_use", "immunosuppressed", "urinary_catheter"):
        assert is_supported_risk_condition(cond) and cond not in CONTEXT_CONDITIONS


def test_planned_prophylaxis_counts_as_dvt_prophylaxis() -> None:
    assert not _ev("no_dvt_prophylaxis", ComplicationContext(dvt_prophylaxis=True))
    assert _ev("no_dvt_prophylaxis", ComplicationContext(dvt_prophylaxis=False))


def test_prophylactic_heparin_is_not_therapeutic_anticoagulation() -> None:
    ctx = ComplicationContext(medications={"ENOXAPARIN"}, dvt_prophylaxis=True)
    assert not _ev("anticoagulation", ctx) and not _ev("no_dvt_prophylaxis", ctx)
