"""Issues #3231, #3250, #3272, #3273: the outpatient SOAP reports the visit's
abnormal labs and screening scores, reconciles the plan's medications with
today's prescription, judges LDL against the US risk-based threshold and
states chronic stages from the latest labs."""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
    build_outpatient_assessment,
    build_outpatient_objective,
    build_outpatient_plan,
)
from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
    build_past_medical_history,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

_WHEN = "2026-03-02T10:00:00"


def _lab(name: str, value: float, unit: str = "", flag: str | None = None, at: str = "2026-03-02T11:00:00") -> dict:
    return {"lab_name": name, "value": value, "unit": unit, "flag": flag, "result_datetime": at}


def _med(name: str, dose: str = "5mg", drug_id: str = "") -> dict:
    return {"drug_name": name, "dose": dose, "route": "PO", "frequency": "daily", "drug_id": drug_id or name.lower()}


def _ctx(
    country: str,
    chronic: list[dict],
    labs: list[dict] | None = None,
    *,
    meds: list[dict] | None = None,
    home: list[dict] | None = None,
    rx: list[dict] | None = None,
    prior: list[dict] | None = None,
    vitals: dict | None = None,
    dob: date = date(1955, 1, 1),
    doc: DocumentType = DocumentType.OUTPATIENT_SOAP,
):
    record = {
        "patient": {
            "patient_id": "POP-T-3231",
            "sex": "M",
            "age": 2026 - dob.year,
            "date_of_birth": dob.isoformat(),
            "chronic_conditions": chronic,
            "current_medications": meds or [],
        },
        "encounters": [
            {
                "encounter_id": "ENC-T-3231",
                "encounter_type": "outpatient" if doc == DocumentType.OUTPATIENT_SOAP else "inpatient",
                "admission_datetime": _WHEN,
                "discharge_datetime": _WHEN,
                "chief_complaint": "",
            }
        ],
        "vital_signs": [{"timestamp": _WHEN, **(vitals or {"heart_rate": 72, "systolic_bp": 120, "diastolic_bp": 76})}],
        "lab_results": labs or [],
        "condition_event": {"condition_type": "chronic_followup", "ground_truth_diseases": [], "visit_type": ""},
        "clinical_diagnosis": {},
        "home_medications_at_admission": home,
    }
    ctx = build_narrative_context(record, record["encounters"][0], doc, 0, country)
    ctx.prior_lab_results = prior or []
    ctx.discharge_medications = rx or []
    return ctx


def _soap(ctx) -> dict[str, str]:
    gen = TemplateNarrativeGenerator()
    return {
        "O": build_outpatient_objective(gen, ctx)[0],
        "A": build_outpatient_assessment(gen, ctx)[0],
        "P": build_outpatient_plan(gen, ctx)[0],
    }


# ── #3231 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("country", ["US", "JP"])
def test_abnormal_labs_outside_the_problem_list_are_reported(country):
    labs = [_lab("T_Bil", 5.3, "mg/dL", "H"), _lab("ALT", 162, "U/L", "H"), _lab("Na", 140, "mmol/L")]
    s = _soap(_ctx(country, [{"code": "I10"}], labs))
    for part in ("A", "O"):
        assert "5.3" in s[part] and "162" in s[part], s[part]
    assert "140" not in s["A"]
    assert s["P"].count("\n") >= 0 and ("Recheck the abnormal results" in s["P"] or "再検" in s["P"])


@pytest.mark.parametrize("country", ["US", "JP"])
def test_screening_scores_and_positive_cssrs(country):
    labs = [_lab("PHQ-9", 9, "{score}"), _lab("C-SSRS", 1, "{score}")]
    s = _soap(_ctx(country, [{"code": "F32.9"}], labs))
    assert "PHQ-9 9" in s["A"] and "C-SSRS 1" in s["A"] and "PHQ-9 9" in s["O"]
    assert ("safety plan" in s["P"]) or ("安全計画" in s["P"])
    negative = _soap(_ctx(country, [{"code": "F32.9"}], [_lab("C-SSRS", 0, "{score}")]))
    assert "safety plan" not in negative["P"] and "安全計画" not in negative["P"]


def test_doac_renal_review_needs_a_renal_result():
    doac = [_med("Apixaban", "5mg", "apixaban")]
    without = _soap(_ctx("US", [{"code": "I48.91"}], [_lab("PT_INR", 1.6)], meds=doac, home=doac))
    assert "renal function and bleeding reviewed" not in without["A"]
    assert "to be checked" in without["A"] and "creatinine" in without["P"]
    with_cr = _soap(_ctx("US", [{"code": "I48.91"}], [_lab("Creatinine", 1.0, "mg/dL")], meds=doac, home=doac))
    assert "renal function and bleeding reviewed" in with_cr["A"]


# ── #3250 ──────────────────────────────────────────────────────────────


def test_plan_has_one_reconciled_medication_list():
    home = [_med("Hydrochlorothiazide", "25mg"), _med("Metformin", "500mg")]
    rx = [_med("Hydrochlorothiazide", "25mg"), _med("Amlodipine", "5mg"), _med("Candesartan", "8mg")]
    p = _soap(_ctx("US", [{"code": "I10"}], meds=home, home=home, rx=rx))["P"]
    assert "Continue current medications" not in p
    assert "Today's prescription" in p
    assert "started Amlodipine; Candesartan" in p
    assert "not on today's prescription Metformin" in p


def test_plan_without_prescription_continues_the_visit_start_list():
    start = [_med("Hydrochlorothiazide", "25mg")]
    year_end = [_med("Hydrochlorothiazide", "25mg"), _med("Candesartan", "8mg")]
    p = _soap(_ctx("US", [{"code": "I10"}], meds=year_end, home=start))["P"]
    assert "Hydrochlorothiazide" in p and "Candesartan" not in p


def test_blood_pressure_above_target_has_a_plan_action_and_all_antihypertensives():
    meds = [_med("Amlodipine"), _med("Candesartan", "8mg")]
    ctx = _ctx("JP", [{"code": "I10"}], meds=meds, home=meds, vitals={"systolic_bp": 145, "diastolic_bp": 88})
    s = _soap(ctx)
    assert "アムロジピン" in s["A"] and "カンデサルタン" in s["A"]
    assert "降圧薬の調整" in s["P"]


# ── #3272 ──────────────────────────────────────────────────────────────


def test_us_ldl_of_an_ascvd_patient_is_judged_against_70():
    labs = [_lab("LDL", 118, "mg/dL")]
    a = _soap(_ctx("US", [{"code": "I25.10"}, {"code": "E78.5"}], labs))["A"]
    assert "at goal" not in a
    assert "70 mg/dL threshold for clinical ASCVD" in a and "above" in a


def test_us_ldl_without_ascvd_is_judged_against_the_severe_threshold():
    a = _soap(_ctx("US", [{"code": "E78.5"}], [_lab("LDL", 118, "mg/dL")]))["A"]
    assert "at goal" not in a and "elevated" not in a
    assert "below the 190 mg/dL threshold" in a
    high = _soap(_ctx("US", [{"code": "E78.5"}], [_lab("LDL", 195, "mg/dL")]))["A"]
    assert "above the 190 mg/dL threshold" in high


def test_jp_ldl_keeps_the_jas_target():
    a = _soap(_ctx("JP", [{"code": "E78.5"}], [_lab("LDL", 118, "mg/dL")]))["A"]
    assert "140" in a and "目標達成" in a


# ── #3273 ──────────────────────────────────────────────────────────────


def test_stage_comes_from_the_latest_prior_hba1c():
    prior = [
        _lab("HbA1c", 8.4, "%", at="2026-01-10T09:00:00"),
        _lab("HbA1c", 8.8, "%", "H", at="2026-02-28T09:00:00"),
        _lab("HbA1c", 6.1, "%", at="2026-04-01T09:00:00"),  # after the visit
    ]
    cond = [{"code": "E11.9", "stage": "HbA1c 8.5%"}]
    a = _soap(_ctx("US", cond, prior=prior))["A"]
    assert "HbA1c 8.8" in a and "2026-02-28" in a and "poorly controlled" in a
    assert "no acute change" not in a


def test_stored_hba1c_stage_above_target_is_not_no_acute_change():
    a = _soap(_ctx("US", [{"code": "E11.9", "stage": "HbA1c 8.5%"}]))["A"]
    assert "no acute change" not in a and "above target" in a


def test_ckd_stage_comes_from_the_latest_egfr():
    prior = [_lab("eGFR", 27.0, "mL/min/1.73m2", "L", at="2026-02-01T09:00:00")]
    a = _soap(_ctx("US", [{"code": "N18.30", "stage": "CKD G3a"}], prior=prior))["A"]
    assert "G4" in a and "G3a" not in a and "2026-02-01" in a


def test_past_medical_history_ckd_stage_reflects_the_latest_egfr():
    prior = [_lab("eGFR", 27.0, "mL/min/1.73m2", "L", at="2026-02-01T09:00:00")]
    ctx = _ctx("US", [{"code": "N18.30", "stage": "CKD G3a"}], prior=prior, doc=DocumentType.ADMISSION_HP)
    text = build_past_medical_history(TemplateNarrativeGenerator(), ctx)[0]
    assert "CKD G4" in text and "G3a" not in text


def test_prescription_without_drug_id_matches_the_home_list():
    home = [_med("Sodium bicarbonate", "500mg", "sodium_bicarbonate")]
    rx = [{"drug_name": "Sodium bicarbonate", "dose": "500mg"}]
    p = _soap(_ctx("US", [{"code": "I10"}], meds=home, home=home, rx=rx))["P"]
    assert "unchanged from the medications at the start of the visit" in p
    assert "started" not in p and "not on today's prescription" not in p


def test_diabetic_complication_does_not_borrow_the_hba1c_stage():
    cond = [{"code": "E11.9", "stage": "HbA1c 7.0%"}, {"code": "E11.21", "stage": "HbA1c 7.0%"}]
    a = _soap(_ctx("US", cond))["A"]
    assert "(HbA1c 7.0%)" in a.split("\n")[0]
    assert a.count("HbA1c 7.0%") == 1


def test_pass_reads_the_labs_of_the_patients_other_records(tmp_path):
    import json

    from clinosim.modules.document.narrative.passes import TemplateNarrativePass

    for stem, labs in (
        ("ENC-POP-000001-aaa", [{"lab_name": "eGFR", "value": 41.0, "unit": "mL/min/1.73m2"}]),
        ("ENC-POP-000001-bbb", [{"lab_name": "HbA1c", "value": 7.1, "unit": "%"}]),
        ("ENC-POP-000002-ccc", [{"lab_name": "HbA1c", "value": 9.9, "unit": "%"}]),
    ):
        (tmp_path / f"{stem}.json").write_text(json.dumps({"lab_results": labs}))
    p = TemplateNarrativePass(cif_dir=str(tmp_path), country="US")
    got = p._patient_prior_labs(str(tmp_path), "ENC-POP-000001-bbb.json")
    assert [lab["lab_name"] for lab in got] == ["eGFR"]


# ── #3250: safety holds of an earlier admission ───────────────────────


def _hold(drug: str, held_on: str, reason: str = "acute kidney injury") -> dict:
    return {"drug": drug, "drug_ja": "", "reason": reason, "reason_ja": "", "held_on": held_on}


def test_drug_held_in_the_last_admission_is_resumed_with_its_reason():
    home = [_med("Hydrochlorothiazide", "25mg")]
    rx = [_med("Hydrochlorothiazide", "25mg"), _med("Candesartan", "8mg")]
    ctx = _ctx("US", [{"code": "I10"}], meds=home, home=home, rx=rx)
    ctx.prior_safety_holds = [_hold("Candesartan", "2026-02-20")]
    p = build_outpatient_plan(TemplateNarrativeGenerator(), ctx)[0]
    assert "Candesartan: held on 2026-02-20 for acute kidney injury, resumed on today's prescription." in p


def test_drug_still_held_is_stated_and_an_old_hold_is_not():
    home = [_med("Hydrochlorothiazide", "25mg")]
    ctx = _ctx("US", [{"code": "I10"}], meds=home, home=home, rx=[_med("Hydrochlorothiazide", "25mg")])
    ctx.prior_safety_holds = [_hold("Candesartan", "2026-02-20"), _hold("Metformin", "2025-06-01")]
    p = build_outpatient_plan(TemplateNarrativeGenerator(), ctx)[0]
    assert "Candesartan: held on 2026-02-20 for acute kidney injury, hold continued today." in p
    assert "Metformin" not in p


# ── #3273: stage refresh from labs ────────────────────────────────────


def test_stage_refresh_restates_ckd_and_hba1c_from_the_latest_labs():
    from types import SimpleNamespace

    from clinosim.modules.longitudinal.stage_refresh import ckd_stage_label, refresh_stages_from_labs
    from clinosim.types.patient import ChronicCondition, PatientProfile

    def rec(enc, when, labs, stage_ckd="CKD G3a"):
        patient = PatientProfile(
            patient_id="P1",
            chronic_conditions=[
                ChronicCondition(code="N18.30", stage=stage_ckd),
                ChronicCondition(code="E11.9", stage="HbA1c 8.5%"),
            ],
        )
        return SimpleNamespace(
            patient=patient,
            encounters=[{"encounter_id": enc, "admission_datetime": when, "discharge_datetime": when}],
            lab_results=labs,
        )

    r1 = rec("E1", "2026-01-01T09:00:00", [_lab("eGFR", 27.0, at="2026-01-01T10:00:00")])
    r2 = rec("E2", "2026-02-01T09:00:00", [_lab("HbA1c", 8.8, at="2026-02-01T10:00:00")])
    r0 = rec("E0", "2025-12-01T09:00:00", [])
    refresh_stages_from_labs(SimpleNamespace(records=[r2, r1, r0]))
    assert [c.stage for c in r0.patient.chronic_conditions] == ["CKD G3a", "HbA1c 8.5%"]  # no lab known yet
    assert [c.stage for c in r1.patient.chronic_conditions] == ["CKD G4", "HbA1c 8.5%"]
    assert [c.stage for c in r2.patient.chronic_conditions] == ["CKD G4", "HbA1c 8.8%"]
    assert ckd_stage_label(44.9) == "CKD G3b" and ckd_stage_label(14.0) == "CKD G5"


# ── #3249: retinopathy screening visit ────────────────────────────────


def test_retinopathy_screening_visit_states_the_fundus_examination():
    ctx = _ctx("US", [{"code": "E11.9"}])
    ctx.visit_type, ctx.visit_condition_id = "chronic_followup", "diabetic_retinopathy_screening"
    s = _soap(ctx)
    assert "fundus" in s["A"] and "no diabetic retinopathy on the problem list" in s["A"]
    ctx2 = _ctx("US", [{"code": "E11.9"}, {"code": "E11.311"}])
    ctx2.visit_type, ctx2.visit_condition_id = "chronic_followup", "diabetic_retinopathy_screening"
    assert "diabetic retinopathy is on the problem list" in _soap(ctx2)["A"]
