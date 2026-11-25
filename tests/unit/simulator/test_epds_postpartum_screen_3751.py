"""Issue #3751: a postpartum visit records an Edinburgh Postnatal Depression
Scale (EPDS) total score as an Observation; the SOAP states it and a positive
screen adds a plan line."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from clinosim import determinism
from clinosim.locale.loader import load_chronic_followup, load_demographics, load_perinatal_config
from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
    build_outpatient_assessment,
    build_outpatient_objective,
    build_outpatient_plan,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.output.fhir_r4.labs.observations import _build_lab_observation
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.simulator.perinatal import epds_screening_cutoff, sample_epds_score
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

_CFG = load_perinatal_config()["postpartum_depression_screen"]


def test_score_is_deterministic_and_within_the_scale() -> None:
    first = [sample_epds_score(f"ENC-{i}", "US") for i in range(300)]
    assert first == [sample_epds_score(f"ENC-{i}", "US") for i in range(300)]
    assert all(isinstance(s, int) and 0 <= s <= _CFG["max_score"] for s in first if s is not None)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_positive_rate_matches_the_configured_source_rate(country: str) -> None:
    n = 30000
    scores = [sample_epds_score(f"ENC-R-{i}", country) for i in range(n)]
    cutoff = epds_screening_cutoff(country)
    assert cutoff == _CFG[country.lower()]["cutoff"]
    rate = sum(1 for s in scores if s is not None and s >= cutoff) / n
    assert rate == pytest.approx(_CFG[country.lower()]["positive_rate"], abs=0.01)


def test_cutoffs_are_the_sourced_country_values() -> None:
    assert epds_screening_cutoff("US") == 10
    assert epds_screening_cutoff("JP") == 9


def test_a_country_without_a_screen_records_none() -> None:
    assert sample_epds_score("ENC-X", "ZZ") is None
    assert epds_screening_cutoff("ZZ") is None


def _postpartum_visit(country: str, encounter_hint: int):
    rng = determinism.default_rng(encounter_hint)
    person = PersonRecord(
        person_id=f"T-3751-{encounter_hint}", household_id="H-1", age=30, sex="F", date_of_birth=date(1996, 1, 1)
    )
    patient = activate_patient(person, rng, load_demographics(country))
    spec = dict(load_chronic_followup()["Z39"])
    return _simulate_outpatient_visit(
        patient,
        "chronic_followup",
        datetime(2026, 5, 1, 10, 0),
        StaffRoster(),
        determinism.default_rng(0),
        chronic_code="Z39",
        followup_spec=spec,
        country=country,
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_a_postpartum_visit_records_one_epds_score_and_band(country: str) -> None:
    record = _postpartum_visit(country, 1)
    epds = [r for r in record.lab_results if r.lab_name == "EPDS"]
    assert len(epds) == 1
    score = epds[0].value
    assert float(score).is_integer() and 0 <= score <= 30
    assert epds[0].unit == "{score}"
    assert epds[0].flag == ("H" if score >= epds_screening_cutoff(country) else None)


def _epds_obs(value: float, flag: str | None, country: str) -> dict:
    order = {"display_name": "EPDS", "ordered_datetime": "2026-05-12T10:00:00", "encounter_id": "ENC-001"}
    result = {
        "lab_name": "EPDS",
        "value": value,
        "unit": "{score}",
        "flag": flag,
        "result_datetime": "2026-05-12T10:30:00",
    }
    resource = _build_lab_observation(
        order, result, patient_id="POP-000002", index=1, country=country, patient_sex="F", encounter_id="ENC-001"
    )
    assert resource is not None
    return resource


@pytest.mark.parametrize("country", ["US", "JP"])
def test_fhir_observation_carries_the_epds_loinc_code(country: str) -> None:
    obs = _epds_obs(14.0, "H", country)
    loinc = [c for c in obs["code"]["coding"] if c["system"] == "http://loinc.org"]
    assert [(c["code"], c["display"]) for c in loinc] == [("99046-5", "Total score [EPDS]")]
    assert obs["category"][0]["coding"][0]["code"] == "survey"
    assert obs["valueQuantity"]["value"] == 14.0
    assert obs["interpretation"][0]["coding"][0]["code"] == "H"
    assert _epds_obs(4.0, None, country)["interpretation"][0]["coding"][0]["code"] == "N"


def _soap(country: str, value: float, flag: str | None) -> dict[str, str]:
    when = "2026-05-12T10:00:00"
    record = {
        "patient": {
            "patient_id": "POP-T-3751",
            "sex": "F",
            "age": 30,
            "date_of_birth": "1996-01-01",
            "chronic_conditions": [],
            "current_medications": [],
            "state_periods": [
                {
                    "state_type": "pregnancy",
                    "start_date": "2025-07-14",
                    "end_date": "2026-04-14",
                    "outcome": "delivered",
                    "metadata": {"lmp": "2025-07-14", "delivered_on": "2026-04-14", "complications": []},
                }
            ],
        },
        "encounters": [
            {
                "encounter_id": "ENC-T-3751",
                "encounter_type": "outpatient",
                "admission_datetime": when,
                "discharge_datetime": when,
                "chief_complaint": "",
            }
        ],
        "vital_signs": [{"timestamp": when, "heart_rate": 76, "systolic_bp": 112, "diastolic_bp": 70}],
        "lab_results": [
            {
                "lab_name": "EPDS",
                "value": value,
                "unit": "{score}",
                "flag": flag,
                "result_datetime": "2026-05-12T10:30:00",
            }
        ],
        "condition_event": {
            "condition_type": "chronic_followup",
            "ground_truth_diseases": ["Z39"],
            "visit_type": "chronic_followup",
            "visit_condition_id": "Z39",
        },
        "clinical_diagnosis": {"admission_diagnosis_code": "Z39", "discharge_diagnosis_code": "Z39"},
    }
    ctx = build_narrative_context(record, record["encounters"][0], DocumentType.OUTPATIENT_SOAP, 0, country)
    ctx.diagnoses = [record["clinical_diagnosis"]]
    gen = TemplateNarrativeGenerator()
    return {
        "O": build_outpatient_objective(gen, ctx)[0],
        "A": build_outpatient_assessment(gen, ctx)[0],
        "P": build_outpatient_plan(gen, ctx)[0],
    }


def test_soap_states_the_score_and_a_positive_screen_adds_a_plan_line_en() -> None:
    soap = _soap("US", 14, "H")
    assert "EPDS 14 (positive screen)" in soap["A"] + soap["O"]
    assert "Positive EPDS screen" in soap["P"] and "referral" in soap["P"]
    # a screening score is not also listed as an abnormal result to recheck
    assert "Abnormal results" not in soap["A"] and "Recheck the abnormal" not in soap["P"]


def test_soap_states_the_score_and_a_positive_screen_adds_a_plan_line_ja() -> None:
    soap = _soap("JP", 11, "H")
    assert "EPDS 11" in soap["A"] + soap["O"] and "陽性" in soap["A"] + soap["O"]
    assert "EPDS 陽性" in soap["P"] and "紹介" in soap["P"]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_a_negative_screen_states_the_score_without_a_plan_line(country: str) -> None:
    soap = _soap(country, 3, None)
    assert "EPDS 3" in soap["A"] + soap["O"]
    assert "positive" not in soap["P"].lower() and "陽性" not in soap["P"]
