"""Ezetimibe is added on the measured, not the latent, LDL (Issue #2942).

The longitudinal ``lipid_escalate_ezetimibe_e78`` event used to add ezetimibe
whenever the untreated LDL latent was above 190 mg/dL, so patients at goal on
their statin were given it. It is retired (rate 0, kept so the engine's
per-year draw is unchanged); the add-on is made at the follow-up visit on the
measured lipid panel, after the statin is at its maximal dose
(``simulator/statin_monitoring.py``).
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_chronic_followup
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.longitudinal.patterns.event import step
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator import statin_monitoring as sm
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.allergy import Allergy
from clinosim.types.encounter import OrderResult
from clinosim.types.patient import ChronicCondition, HomeMedication, PatientProfile

pytestmark = pytest.mark.unit


def _patient(*codes: str, drug: str = "Atorvastatin", dose: str = "40mg") -> PatientProfile:
    patient = PatientProfile(patient_id="pt-2942", age=63, sex="M")
    patient.chronic_conditions = [ChronicCondition(code=c, system="icd-10-cm") for c in codes]
    patient.current_medications = [
        HomeMedication(drug_name="Amlodipine", dose="5mg", route="PO", frequency="daily"),
        HomeMedication(drug_name=drug, dose=dose, route="PO", frequency="daily"),
    ]
    return patient


def _panel(patient: PatientProfile, ldl: float, on: date = date(2023, 1, 10)) -> None:
    sm.note_lipid_panel(patient, on, [OrderResult(lab_name="LDL", value=ldl, unit="mg/dL")])


def _names(patient: PatientProfile) -> list[str]:
    return [m.drug_name for m in patient.current_medications]


def test_latent_ldl_event_never_fires_and_keeps_its_single_draw() -> None:
    load_attribute_specs.cache_clear()
    spec = load_attribute_specs()["lipid_escalate_ezetimibe_e78"].body
    for seed in range(50):
        rng = np.random.default_rng(seed)
        result = step(["E78"], [], rng, spec, context={"continuous": {"ldl": 280.0}})
        assert not result.fired and result.med_additions == []
        reference = np.random.default_rng(seed)
        reference.random()
        assert rng.random() == reference.random()


def test_rules_name_a_catalog_add_on_and_maximal_doses_per_country() -> None:
    rules = sm.statin_monitoring_rules()
    assert rules.add_on == "ezetimibe"
    assert rules.countries["US"].maximal_statin_mg == {"atorvastatin": 40, "rosuvastatin": 20}
    assert rules.countries["JP"].maximal_statin_mg == {"atorvastatin": 20, "rosuvastatin": 10}
    assert sm.add_on_ldl(_patient("E78"), "US") == 100
    assert sm.add_on_ldl(_patient("E78", "I25.10"), "US") == 70


@pytest.mark.parametrize(
    ("codes", "target"),
    [
        (("E78", "I25.10"), 100),  # coronary heart disease: secondary prevention
        (("E78", "I63.9"), 100),  # prior ischaemic stroke: secondary prevention
        (("E78", "I69.3"), 100),
        (("E78", "E11.9"), 120),  # high-risk primary prevention
        (("E78", "N18.3"), 120),
        (("E78", "I73.9"), 120),
        (("E78", "I10"), 140),  # moderate risk (low-risk tier not modelled)
        (("E78",), 140),
    ],
)
def test_jp_targets_follow_the_jas_2022_risk_tiers(codes: tuple[str, ...], target: int) -> None:
    patient = _patient(*codes)
    assert sm.add_on_ldl(patient, "JP") == target
    assert sm.step_up_ldl(patient, "JP") == target


def test_at_goal_on_high_intensity_is_not_given_ezetimibe() -> None:
    patient = _patient("E78", "I25.10", dose="80mg")
    _panel(patient, 62.0)
    assert sm.titrate_statin(patient, date(2023, 4, 10), "US") is None
    assert sm.add_lipid_add_on(patient, date(2023, 4, 10), "US") is None
    assert "Ezetimibe" not in _names(patient)


def test_above_threshold_on_high_intensity_is_given_ezetimibe_once() -> None:
    patient = _patient("E78", "I25.10", dose="80mg")
    _panel(patient, 88.0)
    assert sm.titrate_statin(patient, date(2023, 4, 10), "US") is None  # 80 mg is the top
    add_on = sm.add_lipid_add_on(patient, date(2023, 4, 10), "US")
    assert add_on is not None
    assert (add_on.drug_name, add_on.dose, add_on.route, add_on.frequency) == ("Ezetimibe", "10mg", "PO", "daily")
    assert add_on.drug_id == "ezetimibe"
    assert _names(patient) == ["Amlodipine", "Atorvastatin", "Ezetimibe"]
    assert patient.visit_ledger.lipid_add_on_on == date(2023, 4, 10)
    # Already taking it: never added twice.
    _panel(patient, 90.0, on=date(2023, 5, 10))
    assert sm.add_lipid_add_on(patient, date(2023, 7, 10), "US") is None
    assert _names(patient).count("Ezetimibe") == 1


def test_primary_prevention_on_high_intensity_uses_the_100_threshold() -> None:
    patient = _patient("E78")
    _panel(patient, 96.0)
    assert sm.add_lipid_add_on(patient, date(2023, 4, 10), "US") is None
    _panel(patient, 120.0)
    assert sm.add_lipid_add_on(patient, date(2023, 4, 10), "US") is not None


def test_above_goal_on_moderate_intensity_titrates_the_statin_first() -> None:
    patient = _patient("E78", dose="10mg")
    _panel(patient, 205.0)
    assert sm.add_lipid_add_on(patient, date(2023, 4, 10), "US") is None  # not maximal
    step_up = sm.titrate_statin(patient, date(2023, 4, 10), "US")
    assert step_up is not None and step_up.to_dose == "40mg"
    assert "Ezetimibe" not in _names(patient)
    # The old panel was on 10 mg: no add-on until a panel on the new dose.
    assert sm.add_lipid_add_on(patient, date(2023, 4, 10), "US") is None
    _panel(patient, 130.0, on=date(2023, 5, 10))
    assert sm.add_lipid_add_on(patient, date(2023, 7, 10), "US") is not None


def test_ascvd_on_atorvastatin_40_goes_to_80_before_ezetimibe() -> None:
    patient = _patient("E78", "I25.10", dose="40mg")
    _panel(patient, 92.0)
    patient_visit = _visit(patient, datetime(2023, 4, 10, 9))
    statin = sm.current_statin(patient)
    assert statin is not None and statin.dose == "80mg"
    assert "Ezetimibe" not in _names(patient)
    rx = patient_visit.discharge_prescription
    assert rx is not None and not any(i["drug_name"] == "Ezetimibe" for i in rx.items)


def test_jp_adds_ezetimibe_at_the_usual_maximum_above_the_target() -> None:
    at_max = _patient("E78", "E11.9", dose="20mg")
    _panel(at_max, 125.0)
    assert sm.titrate_statin(at_max, date(2023, 4, 10), "JP") is None
    assert sm.add_lipid_add_on(at_max, date(2023, 4, 10), "JP") is not None
    below_max = _patient("E78", "E11.9", dose="10mg")
    _panel(below_max, 125.0)
    assert sm.add_lipid_add_on(below_max, date(2023, 4, 10), "JP") is None
    moderate_risk = _patient("E78", dose="20mg")  # target < 140
    _panel(moderate_risk, 135.0)
    assert sm.add_lipid_add_on(moderate_risk, date(2023, 4, 10), "JP") is None
    _panel(moderate_risk, 145.0)
    assert sm.add_lipid_add_on(moderate_risk, date(2023, 4, 10), "JP") is not None


def test_a_recorded_allergy_rules_the_add_on_out(monkeypatch: pytest.MonkeyPatch) -> None:
    from clinosim.modules import drug_safety

    seen: list[tuple[str, list]] = []

    def _skip(candidate: str, allergies: list) -> object:
        seen.append((candidate, allergies))
        return object()

    monkeypatch.setattr(drug_safety, "allergy_skip_verdict", _skip)
    patient = _patient("E78", "I25.10", dose="80mg")
    patient.allergies = [Allergy(allergen_code="000000", category="medication")]
    _panel(patient, 110.0)
    assert sm.add_lipid_add_on(patient, date(2023, 4, 10), "US") is None
    assert seen == [("ezetimibe", patient.allergies)]
    assert "Ezetimibe" not in _names(patient)


def test_add_on_is_rechecked_and_carried_into_the_next_year_profile() -> None:
    patient = _patient("E78", "I25.10", dose="80mg")
    _panel(patient, 95.0)
    assert sm.add_lipid_add_on(patient, date(2023, 4, 10), "US") is not None
    assert not sm.lipid_panel_due(patient, date(2023, 4, 10))
    assert not sm.lipid_panel_due(patient, date(2023, 5, 1))  # < 4 weeks
    assert sm.lipid_panel_due(patient, date(2023, 5, 8))  # 4 weeks after the add-on
    next_year = _patient("E78", "I25.10", dose="80mg")
    next_year.visit_ledger = patient.visit_ledger
    sm.restore_lipid_add_on(next_year)
    sm.restore_lipid_add_on(next_year)
    assert _names(next_year) == ["Amlodipine", "Atorvastatin", "Ezetimibe"]


def _visit(patient: PatientProfile, when: datetime, country: str = "US"):
    return _simulate_outpatient_visit(
        patient,
        "chronic_followup",
        when,
        StaffRoster(),
        np.random.default_rng(0),
        chronic_code="E78",
        followup_spec=load_chronic_followup()["E78"],
        country=country,
    )


def test_the_visit_adds_ezetimibe_and_renews_it() -> None:
    patient = _patient("E78", "I25.10", dose="80mg")
    _panel(patient, 101.0)
    result = _visit(patient, datetime(2023, 4, 10, 9))
    rx = result.discharge_prescription
    assert rx is not None
    item = next(i for i in rx.items if i["drug_name"] == "Ezetimibe")
    assert item["dose"] == "10mg"


def _note_ctx(*codes: str, ldl: float, lang: str = "ja", locale: str | None = None):
    from types import SimpleNamespace

    from clinosim.types.document import DocumentType, NarrativeContext

    patient = PatientProfile(patient_id="pt-2942-note", age=66, sex="F")
    patient.chronic_conditions = [ChronicCondition(code=c, system="icd-10-cm") for c in codes]
    return NarrativeContext(
        patient=patient,
        encounter=SimpleNamespace(encounter_id="enc-2942", admission_datetime=datetime(2024, 5, 1, 10)),
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=[SimpleNamespace(lab_name="LDL", value=ldl, unit="mg/dL")],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang=lang,
        locale=locale or ("jp" if lang == "ja" else "us"),
    )


def _assessment(ctx) -> str:
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

    return TemplateNarrativeGenerator()._compose_chronic_assessment_integrated(ctx)


@pytest.mark.parametrize(
    ("codes", "tier_ja"),
    [
        (("E78", "I25.10"), "二次予防"),  # coronary heart disease
        (("E78", "E11.9"), "一次予防・高リスク"),  # diabetes
        (("E78",), "一次予防"),  # moderate risk
    ],
)
def test_jp_note_states_the_tier_target_the_titration_uses(codes: tuple[str, ...], tier_ja: str) -> None:
    patient = _patient(*codes)
    threshold = sm.step_up_ldl(patient, "JP")
    assert threshold is not None
    assert sm.ldl_target(patient, "JP") is not None and sm.ldl_target(patient, "JP")[0] == threshold
    text = _assessment(_note_ctx(*codes, ldl=threshold - 1))
    assert f"目標 {threshold:g} mg/dL 未満 ({tier_ja})" in text
    assert "目標達成" in text  # just below the target is at goal
    assert "目標達成" not in _assessment(_note_ctx(*codes, ldl=threshold))


def test_jp_english_note_names_the_tier() -> None:
    text = _assessment(_note_ctx("E78", "I63.9", ldl=95.0, lang="en", locale="jp"))
    assert "target < 100 mg/dL (secondary prevention)" in text


def test_us_note_states_no_ldl_target() -> None:
    assert sm.ldl_target(_patient("E78", "I25.10"), "US") is None
    assert "target <" not in _assessment(_note_ctx("E78", "I25.10", ldl=95.0, lang="en"))
