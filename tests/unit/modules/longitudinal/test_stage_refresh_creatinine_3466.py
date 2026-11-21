"""CKD stage from the creatinine-derived eGFR when no eGFR result exists (Issue #3466)."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from clinosim.modules.document.narrative._outpatient_results import latest_lab_stage
from clinosim.modules.longitudinal.stage_refresh import (
    ckd_g_category,
    creatinine_egfr,
    refresh_stages_from_labs,
)
from clinosim.modules.physiology.egfr import egfr_equations
from clinosim.types.patient import ChronicCondition, PatientProfile


def _patient(country="JP", sex="M", dob=date(1949, 1, 1), height=165.0):
    p = PatientProfile(
        patient_id="P1",
        sex=sex,
        date_of_birth=dob,
        height_cm=height,
        chronic_conditions=[ChronicCondition(code="N18.30", stage="CKD G2")],
    )
    p.address.country = country
    return p


def _lab(name, value, at, unit="mg/dL"):
    return {"lab_name": name, "value": value, "unit": unit, "result_datetime": at}


def _record(patient, labs, when="2026-05-02T09:00:00"):
    return SimpleNamespace(
        patient=patient,
        encounters=[{"encounter_id": "E1", "admission_datetime": when, "discharge_datetime": when}],
        lab_results=labs,
    )


def _stage(record):
    return record.patient.chronic_conditions[0].stage


def test_jp_creatinine_gives_g3b_from_the_jsn_equation():
    eq = egfr_equations("JP")["adult"]
    expected = eq["coefficient"] * 1.63 ** eq["creatinine_exponent"] * 77 ** eq["age_exponent"]
    assert 30 <= expected < 45
    got = creatinine_egfr(_patient(), 1.63, datetime(2026, 5, 2, 10, 0))
    assert abs(got - expected) < 0.1
    rec = _record(_patient(), [_lab("Creatinine", 1.63, "2026-05-02T10:00:00")])
    refresh_stages_from_labs(SimpleNamespace(records=[rec]))
    assert _stage(rec) == "CKD G3b"


def test_us_creatinine_uses_ckd_epi_2021():
    eq = egfr_equations("US")["adult"]
    ratio = 1.63 / eq["kappa"]["M"]
    expected = eq["coefficient"] * ratio ** eq["upper_exponent"] * eq["age_base"] ** 77
    got = creatinine_egfr(_patient("US"), 1.63, datetime(2026, 5, 2, 10, 0))
    assert abs(got - expected) < 0.1
    assert ckd_g_category(got) in {"G3b", "G4"}


def test_later_creatinine_beats_an_earlier_egfr_and_same_time_egfr_wins():
    rec = _record(
        _patient(),
        [_lab("eGFR", 70.0, "2026-01-01T10:00:00", "mL/min/1.73m2"), _lab("Creatinine", 1.63, "2026-05-02T10:00:00")],
    )
    refresh_stages_from_labs(SimpleNamespace(records=[rec]))
    assert _stage(rec) == "CKD G3b"
    same = _record(
        _patient(),
        [_lab("eGFR", 70.0, "2026-05-02T10:00:00", "mL/min/1.73m2"), _lab("Creatinine", 1.63, "2026-05-02T10:00:00")],
    )
    refresh_stages_from_labs(SimpleNamespace(records=[same]))
    assert _stage(same) == "CKD G2"


def test_pediatric_needs_a_height_and_a_foreign_unit_is_skipped():
    child = date(2020, 1, 1)
    assert creatinine_egfr(_patient("US", dob=child, height=0), 0.5, datetime(2026, 5, 2)) is None
    assert creatinine_egfr(_patient("US", dob=child, height=110.0), 0.5, datetime(2026, 5, 2)) is not None
    assert creatinine_egfr(_patient(), 144.0, datetime(2026, 5, 2), "umol/L") is None


def test_narrative_latest_lab_stage_derives_egfr_from_creatinine():
    labs = {"creatinine": (1.63, "mg/dL", "2026-05-02")}
    text = latest_lab_stage("N18.30", "CKD G2", labs, _patient())
    assert text.startswith("CKD G3b, eGFR 3") and text.endswith("(2026-05-02)")
    assert latest_lab_stage("N18.30", "CKD G2", labs) == ""
    newer_egfr = {**labs, "egfr": (88.0, None, "2026-06-01")}
    assert latest_lab_stage("N18.30", "CKD G2", newer_egfr, _patient()).startswith("CKD G2, eGFR 88")
    older_egfr = {**labs, "egfr": (88.0, None, "2026-01-01")}
    assert latest_lab_stage("N18.30", "CKD G2", older_egfr, _patient()).startswith("CKD G3b")
