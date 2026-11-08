"""Children are judged against ranges for their age (Issue #2872).

Vital signs: Fleming et al. 2011 HR / RR centiles and PALS 2020 BP ranges
for the Observation referenceRange, interpretation and text; labs: Harriet
Lane intervals for the CIF flag and the referenceRange; NEWS2 is not scored
under 16; a child's baseline vitals and true lab values centre on the
values for their age. Adults keep the adult ranges.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.observation.engine import determine_flag
from clinosim.modules.observation.pediatric_ranges import (
    age_in_completed_months,
    pediatric_lab_range,
    pediatric_vital_range,
)
from clinosim.modules.output.fhir_r4.labs.observations import _build_vital_observations
from clinosim.modules.output.fhir_r4.lib.common import build_reference_range
from clinosim.modules.physiology.engine import derive_lab_values
from clinosim.types.clinical import PhysiologicalState

_TS = "2025-06-01T10:00:00"


def _vitals(hr: int, rr: int, sbp: int, dbp: int) -> dict:
    return {
        "timestamp": _TS,
        "heart_rate": hr,
        "respiratory_rate": rr,
        "systolic_bp": sbp,
        "diastolic_bp": dbp,
        "spo2": 98,
        "temperature_celsius": 36.8,
    }


def _by_loinc(entries: list[dict]) -> dict[str, dict]:
    return {e["resource"]["code"]["coding"][0]["code"]: e["resource"] for e in entries}


def _interp(resource: dict) -> str:
    return resource["interpretation"][0]["coding"][0]["code"]


@pytest.mark.parametrize(
    ("birth_date", "hr", "rr", "expect_text_en"),
    [
        ("2025-04-15", 130, 40, "Normal range for age 0–2 months"),  # newborn / young infant
        ("2023-11-01", 120, 32, "Normal range for age 18–23 months"),  # toddler
        ("2017-03-01", 85, 19, "Normal range for age 8–11 years"),  # school-age
        ("2010-01-01", 75, 16, "Normal range for age 15–17 years"),  # adolescent
    ],
)
def test_child_vitals_use_the_range_for_their_age(birth_date: str, hr: int, rr: int, expect_text_en: str) -> None:
    obs = _by_loinc(
        _build_vital_observations(_vitals(hr, rr, 100, 60), "p", 0, "US", "e", birth_date=birth_date, age_years=0)
    )
    for loinc in ("8867-4", "9279-1"):
        assert obs[loinc]["referenceRange"][0]["text"] == expect_text_en
        assert _interp(obs[loinc]) == "N"


def test_newborn_hr_130_rr_40_is_normal_not_critical() -> None:
    obs = _by_loinc(_build_vital_observations(_vitals(130, 40, 70, 42), "p", 0, "US", "e", birth_date="2025-05-28"))
    assert _interp(obs["8867-4"]) == "N"
    assert _interp(obs["9279-1"]) == "N"
    hr_range = obs["8867-4"]["referenceRange"]
    assert (hr_range[0]["low"]["value"], hr_range[0]["high"]["value"]) == (107, 181)
    bp = obs["85354-9"]["component"]
    assert [_interp(c) for c in bp] == ["N", "N"]
    assert bp[0]["referenceRange"][0]["text"] == "Normal range for age 0 months"


def test_infant_bradypnea_and_bradycardia_are_flagged() -> None:
    obs = _by_loinc(_build_vital_observations(_vitals(71, 8, 106, 61), "p", 0, "US", "e", birth_date="2025-01-01"))
    assert _interp(obs["8867-4"]) == "L"  # 5 months: 104-175
    assert _interp(obs["9279-1"]) == "LL"  # PALS: < 10 /min
    assert [_interp(c) for c in obs["85354-9"]["component"]] == ["H", "H"]  # infant 72-104 / 37-56


def test_jp_text_is_japanese() -> None:
    obs = _by_loinc(_build_vital_observations(_vitals(110, 28, 96, 52), "p", 0, "JP", "e", birth_date="2022-12-01"))
    assert obs["8867-4"]["referenceRange"][0]["text"] == "2歳の正常範囲"
    assert obs["85354-9"]["component"][0]["referenceRange"][0]["text"] == "1〜2歳の正常範囲"


def test_adult_vitals_are_unchanged() -> None:
    vs = _vitals(72, 16, 120, 75)
    with_age = _build_vital_observations(vs, "p", 0, "US", "e", birth_date="1980-01-01", age_years=45)
    without = _build_vital_observations(vs, "p", 0, "US", "e")
    assert with_age == without
    obs = _by_loinc(with_age)
    assert obs["8867-4"]["referenceRange"][0]["text"] == "Normal adult range"
    assert obs["8867-4"]["referenceRange"][1] == {
        "type": obs["8867-4"]["referenceRange"][1]["type"],
        "text": "Critical range",
        "low": {"value": 40, "unit": "/min", "system": "http://unitsofmeasure.org", "code": "/min"},
        "high": {"value": 130, "unit": "/min", "system": "http://unitsofmeasure.org", "code": "/min"},
    }


def test_age_in_completed_months() -> None:
    assert age_in_completed_months("2024-01-31", "2024-02-29") == 0
    assert age_in_completed_months("2024-01-15", datetime(2025, 3, 15, 10)) == 14
    assert age_in_completed_months(None, _TS) is None
    assert pediatric_vital_range("heart_rate", 18 * 12) is None


@pytest.mark.parametrize(
    ("lab", "value", "age", "sex", "child_flag", "adult_flag"),
    [
        ("Creatinine", 0.93, 1, "M", "H", None),  # 14 months: 0.3-0.7 (adult 0.74-1.35)
        ("Creatinine", 0.30, 1, "M", None, "L"),
        ("WBC", 10726, 2, "F", None, "H"),  # toddler: 6000-17000 (adult 3500-10500)
        ("Hb", 11.0, 4, "M", "L", "L"),
        ("Hb", 12.0, 4, "M", None, "L"),
        ("ALP", 250, 8, "F", None, "H"),  # 100-320 (adult 44-147)
        ("ALP", 250, 14, "M", None, "H"),  # 11-17 M: 100-390
    ],
)
def test_child_lab_flag_uses_pediatric_interval(
    lab: str, value: float, age: int, sex: str, child_flag: str | None, adult_flag: str | None
) -> None:
    assert determine_flag(lab, value, sex=sex, country="US", age=age) == child_flag
    assert determine_flag(lab, value, sex=sex, country="US", age=40) == adult_flag


@pytest.mark.parametrize("country", ["US", "JP"])
def test_child_lab_reference_range(country: str) -> None:
    rr = build_reference_range("Creatinine", "M", country, age=1)
    assert rr is not None and len(rr) == 1
    assert (rr[0]["low"]["value"], rr[0]["high"]["value"]) == (0.3, 0.7)
    expected = "Pediatric reference interval, age 1–12 years" if country == "US" else "小児基準範囲 (1〜12歳)"
    assert rr[0]["text"] == expected
    assert "appliesTo" not in rr[0]


def test_adult_lab_reference_range_unchanged() -> None:
    assert build_reference_range("Creatinine", "M", "US", age=40) == build_reference_range("Creatinine", "M", "US")
    assert build_reference_range("Creatinine", "M", "US", age=18) == build_reference_range("Creatinine", "M", "US")


def test_adolescent_sex_specific_interval() -> None:
    assert pediatric_lab_range("Hb", 15, "M")[:2] == (13.0, 16.0)
    assert pediatric_lab_range("Hb", 15, "F")[:2] == (12.0, 16.0)
    assert pediatric_lab_range("Hb", 18, "F") is None


def test_child_true_labs_centre_on_the_pediatric_interval() -> None:
    state = PhysiologicalState()
    child = derive_lab_values(state, "M", 1, rng=np.random.default_rng(0))
    adult = derive_lab_values(state, "M", 40, rng=np.random.default_rng(0))
    for lab in ("Creatinine", "Hb", "WBC", "ALP"):
        low, high, _, _ = pediatric_lab_range(lab, 1, "M")
        assert low <= child[lab] <= high, (lab, child[lab])
    assert child["Hct"] == pytest.approx(child["Hb"] * 3.0)
    # Labs without a pediatric interval and adults are untouched.
    assert child["Na"] == adult["Na"]
    assert adult == derive_lab_values(state, "M", 17 + 23, rng=np.random.default_rng(0))


def test_news2_is_not_scored_under_16() -> None:
    from clinosim.modules.observation.nursing_enricher import enrich_nursing
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.encounter import VitalSignRecord
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    def _record(age: int) -> CIFPatientRecord:
        vs = VitalSignRecord(respiratory_rate=40, spo2=97, temperature_celsius=36.8, systolic_bp=70, heart_rate=130)
        return CIFPatientRecord(patient=PatientProfile(patient_id=f"p{age}", age=age), vital_signs=[vs])

    records = [_record(0), _record(15), _record(16)]
    enrich_nursing(EnricherContext(config=None, master_seed=1, records=records))
    assert [r.vital_signs[0].news2_score for r in records][:2] == [None, None]
    assert records[2].vital_signs[0].news2_score is not None


def test_child_baseline_vitals_centre_on_age_medians() -> None:
    from clinosim.modules.patient.activator import _pediatric_median

    assert _pediatric_median("heart_rate", 6, 72) == 134  # 6-8 months
    assert _pediatric_median("respiratory_rate", 6, 16) == 39
    assert _pediatric_median("systolic_bp", 6, 110) == 88
    assert _pediatric_median("heart_rate", 30 * 12 + 6, 72) == 72  # adult keeps the adult base
    assert _pediatric_median("systolic_bp", 16 * 12 + 6, 110) == 110  # BP bands end at 15 years


@pytest.mark.parametrize(("country", "text"), [("US", "Normal range for all ages"), ("JP", "全年齢共通の正常範囲")])
def test_child_temperature_and_spo2_keep_bounds_without_adult_label(country: str, text: str) -> None:
    vs = _vitals(120, 30, 96, 52)
    child = _by_loinc(_build_vital_observations(vs, "p", 0, country, "e", birth_date="2022-01-01"))
    adult = _by_loinc(_build_vital_observations(_vitals(72, 16, 120, 75), "p", 0, country, "e"))
    for loinc in ("8310-5", "2708-6"):  # temperature, SpO2
        assert child[loinc]["referenceRange"][0]["text"] == text
        assert child[loinc]["referenceRange"][0]["low"] == adult[loinc]["referenceRange"][0]["low"]
        assert child[loinc]["referenceRange"][0]["high"] == adult[loinc]["referenceRange"][0]["high"]
