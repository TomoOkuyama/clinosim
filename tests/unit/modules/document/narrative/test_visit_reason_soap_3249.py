"""Issues #3249, #3251, #3252: the outpatient SOAP is organised around the
reason for the visit, records findings rather than instructions, and records
the vaccines, growth and development of vaccination and well-child visits.

Before the fix the outpatient SOAP fell back to the template of the patient's
first chronic condition (JP) or the chronic follow-up engine (US) whatever the
visit was for: a chemotherapy visit read as a hypertension check, a
post-pneumonia visit as a COPD visit with smoking-cessation advice, a URI as
"Follow-up of chronic conditions: Asthma" with "evaluate for infection source"
and a 60-day return; vaccination and well-child visits named no vaccine,
growth or development.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
    build_outpatient_assessment,
    build_outpatient_objective,
    build_outpatient_plan,
    build_outpatient_subjective,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

_ENC = "ENC-T-3249"
_REF = Path(__file__).resolve().parents[5] / "clinosim" / "modules" / "document" / "reference_data"


def _record(
    *,
    country: str,
    visit_type: str,
    condition: str,
    dx: str,
    chronic: list[str],
    age_dob: date = date(1955, 1, 1),
    vitals: dict | None = None,
    labs: list[dict] | None = None,
    mars: list[dict] | None = None,
    immunizations: list[dict] | None = None,
    medications: list[dict] | None = None,
    smoking: str = "never",
    when: str = "2026-03-02T10:00:00",
) -> dict:
    return {
        "patient": {
            "patient_id": "POP-T-3249",
            "sex": "F",
            "age": 2026 - age_dob.year,
            "date_of_birth": age_dob.isoformat(),
            "height_cm": 160.0,
            "weight_kg": 55.0,
            "smoking_status": smoking,
            "chronic_conditions": [{"code": c} for c in chronic],
            "current_medications": medications or [],
        },
        "encounters": [
            {
                "encounter_id": _ENC,
                "encounter_type": "outpatient",
                "admission_datetime": when,
                "discharge_datetime": when,
                "chief_complaint": "",
            }
        ],
        "vital_signs": [{"timestamp": when, **(vitals or {"heart_rate": 80, "systolic_bp": 128, "diastolic_bp": 76})}],
        "lab_results": labs or [],
        "medication_administrations": mars or [],
        "immunizations": immunizations or [],
        "condition_event": {
            "condition_type": "chronic_followup",
            "ground_truth_diseases": [dx],
            "visit_type": visit_type,
            "visit_condition_id": condition,
        },
        "clinical_diagnosis": {"admission_diagnosis_code": dx, "discharge_diagnosis_code": dx},
    }


def _soap(record: dict, country: str) -> dict[str, str]:
    ctx = build_narrative_context(record, record["encounters"][0], DocumentType.OUTPATIENT_SOAP, 0, country)
    ctx.diagnoses = [record["clinical_diagnosis"]]
    gen = TemplateNarrativeGenerator()
    return {
        "S": build_outpatient_subjective(gen, ctx)[0],
        "O": build_outpatient_objective(gen, ctx)[0],
        "A": build_outpatient_assessment(gen, ctx)[0],
        "P": build_outpatient_plan(gen, ctx)[0],
    }


# ── #3249: the visit reason organises the note ────────────────────────


def test_chemotherapy_visit_records_chemotherapy_not_a_blood_pressure_check() -> None:
    record = _record(
        country="JP",
        visit_type="chemo_visit",
        condition="C16",
        dx="C16",
        chronic=["I10", "C16"],
        mars=[
            {"order_id": "o1", "drug_name": "Oxaliplatin", "dose": "123mg", "status": "given"},
            {"order_id": "o2", "drug_name": "Leucovorin", "dose": "580mg", "status": "given"},
            {"order_id": "o3", "drug_name": "Fluorouracil", "dose": "580mg", "status": "given"},
        ],
    )
    soap = _soap(record, "JP")
    text = "\n".join(soap.values())
    assert "化学療法" in soap["A"].splitlines()[0]
    assert "オキサリプラチン" in soap["A"]
    assert "血圧手帳" not in text and "家庭血圧" not in text
    assert "14日後" in soap["P"]
    assert "2か月後" not in soap["P"]


def test_post_pneumonia_visit_reviews_the_pneumonia_not_copd() -> None:
    record = _record(
        country="JP",
        visit_type="post_discharge",
        condition="bacterial_pneumonia",
        dx="Z09",
        chronic=["J44", "I10"],
        labs=[
            {"lab_name": "CRP", "value": 0.4, "unit": "mg/dL", "flag": "", "result_datetime": "2026-03-02T10:30:00"},
        ],
    )
    soap = _soap(record, "JP")
    text = "\n".join(soap.values())
    assert "肺炎" in soap["S"] and "肺炎" in soap["A"].splitlines()[0]
    assert "CRP" in soap["O"]
    assert "禁煙" not in text
    assert "LABA" not in text and "LAMA" not in text
    assert "を聴取" not in text


def test_uri_visit_states_the_diagnosis_and_return_precautions() -> None:
    record = _record(
        country="US",
        visit_type="pediatric_visit",
        condition="pediatric_uri",
        dx="J06.9",
        chronic=["J45"],
        age_dob=date(2023, 1, 1),
        vitals={"heart_rate": 107, "temperature_celsius": 39.1, "respiratory_rate": 29, "spo2": 98.7},
    )
    soap = _soap(record, "US")
    assert "Follow-up of chronic conditions" not in soap["S"]
    assert "Known conditions: Asthma" in soap["S"]
    first = soap["A"].splitlines()[0]
    assert first.startswith("1. ") and "upper respiratory infection" in first.lower()
    assert "evaluate for infection source" not in soap["A"]
    assert re.search(r"Fever: T 39\.1°C, attributable to .*upper respiratory infection", soap["A"], re.I)
    assert "return if fever lasts more than 3 days" in soap["P"]
    assert "60 days" not in soap["P"] and "Next visit" not in soap["P"]


def test_a_chronic_template_is_the_one_of_the_visit_diagnosis() -> None:
    record = _record(country="JP", visit_type="chronic_followup", condition="E11", dx="E11", chronic=["I10", "E11"])
    soap = _soap(record, "JP")
    assert "血圧手帳" not in soap["S"]
    assert "2 型糖尿病" in soap["A"] or "2型糖尿病" in soap["A"]


# ── #3251: findings, not instructions; each vital finding has a plan ──


def test_fever_without_known_infection_has_a_plan_line() -> None:
    record = _record(
        country="JP",
        visit_type="post_discharge",
        condition="hip_fracture",
        dx="Z09",
        chronic=["I10"],
        vitals={"heart_rate": 88, "temperature_celsius": 38.3, "systolic_bp": 130, "diastolic_bp": 80},
    )
    soap = _soap(record, "JP")
    assert "感染源精査要" not in soap["A"]
    assert "発熱: T 38.3°C、診察上明らかな感染巣なし" in soap["A"]
    assert "発熱: 2-3日後に体温を再検" in soap["P"]
    assert "創部" in soap["O"] and "歩行" in soap["O"]


def test_tachycardia_in_known_af_is_rate_control_with_a_plan() -> None:
    record = _record(
        country="US",
        visit_type="chronic_followup",
        condition="I48",
        dx="I48",
        chronic=["I48", "I10"],
        vitals={"heart_rate": 117, "systolic_bp": 128, "diastolic_bp": 76},
    )
    soap = _soap(record, "US")
    assert "assess volume + arrhythmia" not in soap["A"]
    assert "known atrial fibrillation" in soap["A"]
    assert "rate-control therapy to be stepped up" in soap["P"]


_INSTRUCTION = re.compile(r"を確認。|を聴取。|評価要|精査要|\bassess\b|evaluate for|review needed")


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


@pytest.mark.parametrize("name", ["chronic_soap_templates.yaml", "visit_reason_soap.yaml"])
def test_soap_template_text_has_no_instruction_phrases(name: str) -> None:
    data = yaml.safe_load((_REF / name).read_text(encoding="utf-8"))
    data.pop("metadata", None)
    offenders = [s for s in _strings(data) if _INSTRUCTION.search(s)]
    assert offenders == []


# ── #3252: vaccines, growth and development ────────────────────────────


def _imm(cvx: str, dose: int | None, lot: str) -> dict:
    return {
        "vaccine_cvx": cvx,
        "occurrence_date": "2026-09-25",
        "status": "completed",
        "dose_number": dose,
        "lot_number": lot,
        "encounter_id": _ENC,
    }


def test_vaccination_visit_records_each_vaccine_with_lot() -> None:
    record = _record(
        country="US",
        visit_type="pediatric_visit",
        condition="immunization_kindergarten",
        dx="Z23",
        chronic=["J45"],
        age_dob=date(2022, 9, 25),
        when="2026-09-25T10:23:00",
        immunizations=[
            _imm("10", 4, "L322-202609-578"),
            _imm("03", 2, "L867-202609-697"),
            _imm("21", 2, "L861-202609-666"),
            {**_imm("10", 1, "L-OLD"), "encounter_id": "ENC-OTHER", "occurrence_date": "2022-11-25"},
        ],
    )
    soap = _soap(record, "US")
    assert "Immunization:" in soap["A"].splitlines()[0]
    for lot in ("L322-202609-578", "L867-202609-697", "L861-202609-666"):
        assert lot in soap["P"]
    assert "L-OLD" not in soap["P"]
    assert "IPV dose 4, lot L322-202609-578, IM (left upper arm)" in soap["P"]
    assert "MMR dose 2" in soap["P"] and "varicella" in soap["P"].lower()
    assert "Vaccine Information Statements" in soap["P"]


def test_adult_influenza_vaccination_names_the_vaccine_and_lot() -> None:
    imm = {**_imm("140", None, "L976-202511-427"), "occurrence_date": "2025-11-29"}
    record = _record(
        country="US",
        visit_type="chronic_followup",
        condition="flu_vaccination",
        dx="Z23",
        chronic=["I10"],
        when="2025-11-29T10:34:00",
        immunizations=[imm],
    )
    soap = _soap(record, "US")
    assert "Influenza" in soap["A"] and "L976-202511-427" in soap["P"]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_well_child_visit_records_growth_and_development(country: str) -> None:
    record = _record(
        country=country,
        visit_type="pediatric_visit",
        condition="well_child_early",
        dx="Z00.129" if country == "US" else "Z00.1",
        chronic=[],
        age_dob=date(2022, 9, 25),
        when="2026-03-23T10:07:00",
        vitals={"heart_rate": 93, "temperature_celsius": 36.4},
    )
    soap = _soap(record, country)
    if country == "US":
        assert re.search(r"Body weight [\d.]+ kg \(\d+th percentile\)", soap["O"])
        assert "Body height" in soap["O"]
        assert "uses a fork" in soap["A"]
        assert "Anticipatory guidance" in soap["P"]
        assert "Next visit: in 8 months" in soap["P"]
    else:
        assert "体重" in soap["O"] and "パーセンタイル" in soap["O"]
        assert "フォークを使う" in soap["A"]
        assert "保健指導" in soap["P"]


# ── CIF: the simulator records the visit kind ──────────────────────────


def test_outpatient_visit_records_the_visit_type_and_condition() -> None:
    rng = determinism.default_rng(3)
    person = PersonRecord(person_id="T-3249", household_id="H-1", age=60, sex="M", date_of_birth=date(1966, 1, 1))
    patient = activate_patient(person, rng, load_demographics("US"))
    record = _simulate_outpatient_visit(
        patient,
        "post_discharge",
        datetime(2026, 5, 1, 10, 0),
        StaffRoster(),
        determinism.default_rng(0),
        post_discharge_disease="bacterial_pneumonia",
        country="US",
    )
    assert record.condition_event.visit_type == "post_discharge"
    assert record.condition_event.visit_condition_id == "bacterial_pneumonia"


def test_an_appended_encounter_has_no_visit_kind() -> None:
    from clinosim.modules.document.narrative.context import visit_reason_fields

    record = _record(country="US", visit_type="chemo_visit", condition="C18", dx="C18", chronic=["C18"])
    other = SimpleNamespace(encounter_id="ENC-VAX-1")
    assert visit_reason_fields(record, other)["visit_type"] == ""
    assert visit_reason_fields(record, record["encounters"][0])["visit_type"] == "chemo_visit"


def test_a_chronic_visit_with_a_vaccine_keeps_its_problem_and_records_the_vaccine() -> None:
    imm = {**_imm("150", None, "L976-202602-644"), "occurrence_date": "2026-03-02"}
    record = _record(
        country="JP",
        visit_type="chronic_followup",
        condition="I10",
        dx="I10",
        chronic=["I10", "E79"],
        immunizations=[imm],
    )
    soap = _soap(record, "JP")
    assert "予防接種" in soap["A"] and "高血圧: BP" in soap["A"]
    assert "家庭血圧" not in soap["S"]
    assert "L976-202602-644" in soap["P"] and "降圧薬継続" in soap["P"]


def test_a_screening_names_the_procedure_done() -> None:
    record = _record(
        country="US", visit_type="health_screening", condition="colonoscopy_screening", dx="Z12.11", chronic=[]
    )
    record["procedures"] = [
        {"encounter_id": _ENC, "procedure_type": "Colonoscopy", "procedure_code": "45378", "procedure_code_us": "45378"}
    ]
    soap = _soap(record, "US")
    assert "Screening tests today: " in soap["O"] and "olonoscopy" in soap["O"]


def test_androgen_deprivation_is_hormone_therapy_without_neutropenia_advice() -> None:
    record = _record(
        country="US",
        visit_type="chemo_visit",
        condition="C61",
        dx="C61",
        chronic=["C61"],
        mars=[{"order_id": "o1", "drug_name": "Leuprolide", "dose": "3.75mg", "status": "given"}],
    )
    soap = _soap(record, "US")
    assert "hormone therapy given today" in soap["A"]
    assert "neutropenia" not in soap["P"] and "mouth sores" not in soap["S"]
    assert "Next dose: in 28 days." in soap["P"]
