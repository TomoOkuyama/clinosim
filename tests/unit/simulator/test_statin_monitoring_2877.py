"""Lipid monitoring and statin titration at chronic follow-up visits (Issue #2877)."""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_chronic_followup
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator import statin_monitoring as sm
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.encounter import OrderResult
from clinosim.types.patient import ChronicCondition, HomeMedication, PatientProfile

pytestmark = pytest.mark.unit

_PANEL = ["TC", "LDL", "HDL", "TG"]


def _patient(*codes: str, dose: str = "10mg", drug: str = "Atorvastatin") -> PatientProfile:
    patient = PatientProfile(patient_id="pt-statin", age=60, sex="M")
    patient.chronic_conditions = [ChronicCondition(code=c, system="icd-10-cm") for c in codes]
    patient.current_medications = [
        HomeMedication(drug_name="Amlodipine", dose="5mg", route="PO", frequency="daily"),
        HomeMedication(drug_name=drug, dose=dose, route="PO", frequency="daily"),
    ]
    return patient


def _ldl(value: float) -> list[OrderResult]:
    return [OrderResult(lab_name="LDL", value=value, unit="mg/dL")]


def _visit(patient: PatientProfile, when: datetime, country: str = "US", code: str = "E78"):
    return _simulate_outpatient_visit(
        patient,
        "chronic_followup",
        when,
        StaffRoster(),
        np.random.default_rng(0),
        chronic_code=code,
        followup_spec=load_chronic_followup()[code],
        country=country,
    )


def test_rules_load_and_cover_both_countries() -> None:
    rules = sm.statin_monitoring_rules()
    assert rules.lipid_panel == _PANEL
    assert set(rules.countries) == {"US", "JP"}
    # The E78 follow-up no longer draws lipid analytes one by one.
    e78 = load_chronic_followup()["E78"]
    assert not set(_PANEL) & set(e78.get("labs_annual", []) + e78.get("labs_quarterly", []) + e78["labs"])


def test_only_renewal_visits_of_dyslipidemia_patients_on_a_statin_are_monitored() -> None:
    spec = {"prescriptions_renewed": True}
    assert sm.is_statin_monitoring_visit(_patient("I10", "E78"), "chronic_followup", spec)
    assert not sm.is_statin_monitoring_visit(_patient("I10"), "chronic_followup", spec)
    assert not sm.is_statin_monitoring_visit(_patient("E78"), "chronic_followup", {})
    assert not sm.is_statin_monitoring_visit(_patient("E78"), "post_discharge", spec)
    no_statin = _patient("E78")
    no_statin.current_medications = no_statin.current_medications[:1]
    assert not sm.is_statin_monitoring_visit(no_statin, "chronic_followup", spec)


def test_panel_cadence_first_visit_recheck_after_change_and_maintenance() -> None:
    patient = _patient("E78")
    assert sm.lipid_panel_due(patient, date(2023, 1, 10))  # nothing on record
    sm.note_lipid_panel(patient, date(2023, 1, 10), _ldl(150))
    assert not sm.lipid_panel_due(patient, date(2023, 4, 10))  # 90 days
    assert sm.lipid_panel_due(patient, date(2023, 7, 10))  # 181 days

    sm.note_lipid_panel(patient, date(2023, 7, 10), _ldl(195))
    assert sm.titrate_statin(patient, date(2023, 10, 10), "US") is not None
    assert not sm.lipid_panel_due(patient, date(2023, 10, 10))  # titrated today
    assert not sm.lipid_panel_due(patient, date(2023, 10, 30))  # < 4 weeks
    assert sm.lipid_panel_due(patient, date(2023, 11, 7))  # 4 weeks after the change


def test_a_change_made_elsewhere_is_rechecked_at_once() -> None:
    patient = _patient("E78")
    sm.note_lipid_panel(patient, date(2023, 1, 10), _ldl(150))
    patient.current_medications[1] = HomeMedication(drug_name="Rosuvastatin", dose="20mg", route="PO")
    assert sm.lipid_panel_due(patient, date(2023, 2, 1))


def test_us_ldl_190_steps_moderate_to_high_intensity() -> None:
    patient = _patient("E78")
    sm.note_lipid_panel(patient, date(2023, 1, 10), _ldl(196))
    step = sm.titrate_statin(patient, datetime(2023, 4, 10, 9), "US")
    assert step == sm.StatinTitration("Atorvastatin", "10mg", "40mg", 196.0, date(2023, 1, 10))
    statin = sm.current_statin(patient)
    assert statin is not None and statin.dose == "40mg"
    assert [m.drug_name for m in patient.current_medications] == ["Amlodipine", "Atorvastatin"]
    # The next panel is on the new dose; the old LDL no longer titrates.
    assert sm.titrate_statin(patient, date(2023, 7, 10), "US") is None


def test_us_primary_prevention_below_190_is_not_titrated() -> None:
    patient = _patient("E78")
    sm.note_lipid_panel(patient, date(2023, 1, 10), _ldl(185))
    assert sm.titrate_statin(patient, date(2023, 4, 10), "US") is None


def test_us_ascvd_steps_up_from_ldl_70_until_the_top_of_the_ladder() -> None:
    patient = _patient("E78", "I25.10", dose="40mg")
    sm.note_lipid_panel(patient, date(2023, 1, 10), _ldl(110))
    step = sm.titrate_statin(patient, date(2023, 4, 10), "US")
    assert step is not None and step.to_dose == "80mg"
    sm.note_lipid_panel(patient, date(2023, 7, 10), _ldl(110))
    assert sm.titrate_statin(patient, date(2023, 10, 10), "US") is None  # 80 mg is the top


def test_jp_target_based_ladder_stays_within_the_usual_maximum() -> None:
    patient = _patient("E78")
    sm.note_lipid_panel(patient, date(2023, 1, 10), _ldl(150))
    step = sm.titrate_statin(patient, date(2023, 4, 10), "JP")
    assert step is not None and (step.from_dose, step.to_dose) == ("10mg", "20mg")
    sm.note_lipid_panel(patient, date(2023, 7, 10), _ldl(150))
    assert sm.titrate_statin(patient, date(2023, 10, 10), "JP") is None
    at_target = _patient("E78")
    sm.note_lipid_panel(at_target, date(2023, 1, 10), _ldl(115))
    assert sm.titrate_statin(at_target, date(2023, 4, 10), "JP") is None
    secondary = _patient("E78", "I25.10")
    assert sm.step_up_ldl(secondary, "JP") == 100
    rosu = _patient("E78", drug="Rosuvastatin", dose="2.5mg")
    sm.note_lipid_panel(rosu, date(2023, 1, 10), _ldl(150))
    step = sm.titrate_statin(rosu, date(2023, 4, 10), "JP")
    assert step is not None and step.to_dose == "5mg"


def test_titrated_dose_is_carried_into_the_next_year_profile() -> None:
    patient = _patient("E78")
    sm.note_lipid_panel(patient, date(2023, 1, 10), _ldl(200))
    sm.titrate_statin(patient, date(2023, 4, 10), "US")
    next_year = _patient("E78")
    next_year.visit_ledger = patient.visit_ledger
    sm.restore_titrated_statin(next_year)
    statin = sm.current_statin(next_year)
    assert statin is not None and statin.dose == "40mg"
    # A later switch to another statin is left alone.
    switched = _patient("E78", drug="Rosuvastatin", dose="20mg")
    switched.visit_ledger = patient.visit_ledger
    sm.restore_titrated_statin(switched)
    statin = sm.current_statin(switched)
    assert statin is not None and (statin.drug_name, statin.dose) == ("Rosuvastatin", "20mg")


def test_visits_order_the_full_panel_then_titrate_and_renew_the_new_dose() -> None:
    patient = _patient("I10", "E78")
    first = _visit(patient, datetime(2023, 1, 10, 9), code="I10")
    assert {r.lab_name for r in first.lab_results} >= set(_PANEL)
    assert patient.visit_ledger.lipid_panel_on == date(2023, 1, 10)

    patient.visit_ledger.lipid_panel_ldl = 201.0  # the panel's LDL, above 190
    second = _visit(patient, datetime(2023, 4, 12, 9))
    assert not {r.lab_name for r in second.lab_results} & set(_PANEL)
    rx = second.discharge_prescription
    assert rx is not None
    statin = next(i for i in rx.items if i["drug_name"] == "Atorvastatin")
    assert statin["dose"] == "40mg"
    assert statin["titrated_from_dose"] == "10mg" and statin["titration_ldl"] == 201.0

    third = _visit(patient, datetime(2023, 7, 11, 9))
    assert {r.lab_name for r in third.lab_results} >= set(_PANEL)  # recheck after the change


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("en", "Atorvastatin increased from 10mg to 40mg (LDL 201 mg/dL on 2023-01-10)."),
        ("ja", "アトルバスタチン を 10mg から 40mg に増量 (LDL 201 mg/dL、2023-01-10)。"),
    ],
)
def test_the_plan_states_the_titration(lang: str, expected: str) -> None:
    from types import SimpleNamespace

    from clinosim.modules.document.narrative.passes import NarrativePass
    from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
        _compose_statin_titration_line,
    )

    rx = {
        "items": [
            {"drug_name": "Amlodipine", "dose": "5mg"},
            {
                "drug_name": "Atorvastatin",
                "dose": "40mg",
                "titrated_from_dose": "10mg",
                "titration_ldl": 201.0,
                "titration_panel_on": "2023-01-10",
            },
        ]
    }
    meds = NarrativePass._collect_discharge_medications({"discharge_prescription": rx})
    ctx = SimpleNamespace(discharge_medications=meds, target_lang=lang)
    assert _compose_statin_titration_line(ctx) == expected  # type: ignore[arg-type]
    ctx.discharge_medications = meds[:1]
    assert _compose_statin_titration_line(ctx) == ""  # type: ignore[arg-type]
