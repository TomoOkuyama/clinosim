"""Healthcare-calendar screening visits run their own protocol (Issue #2870).

A screening mammogram is a radiology visit with a mammogram and its report;
a screening colonoscopy performs the colonoscopy under sedation, at most once
per 10-year cycle; an annual exam orders the protocol's tests plus the
USPSTF / 特定健診 screening labs for the person's age, sex and BMI.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from clinosim import determinism
from clinosim.modules.encounter.protocol import load_encounter_condition, screening_schedule
from clinosim.modules.population.engine import PersonRecord, _calendar_screening_offered
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.simulator.screening_visit import screening_lab_applies, screening_visit_spec
from clinosim.types.encounter import OrderType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _patient(age: int, sex: str, bmi: float = 22.0) -> PatientProfile:
    p = PatientProfile(patient_id=f"pt-2870-{age}-{sex}")
    p.age = age
    p.sex = sex
    p.bmi = bmi
    p.chronic_conditions = []
    p.current_medications = []
    return p


def _roster():
    from clinosim.modules.facility.hospital_state import load_hospital_operations
    from clinosim.modules.staff.engine import generate_roster

    return generate_roster("medium", "US", determinism.default_rng(7), load_hospital_operations())


def _visit(condition_id: str, patient: PatientProfile, country: str = "US"):
    from clinosim.simulator.enrichers import register_builtin_enrichers
    from clinosim.types.config import SimulatorConfig

    register_builtin_enrichers()
    spec = screening_visit_spec(condition_id, patient, country, determinism.default_rng(11))
    return _simulate_outpatient_visit(
        patient,
        "health_screening",
        datetime(2024, 5, 14, 10, 0),
        _roster(),
        determinism.default_rng(3),
        chronic_code=condition_id,
        followup_spec=spec,
        country=country,
        config=SimulatorConfig(random_seed=5, country=country),
        department_id=load_encounter_condition(condition_id)["department"],
    )


# --- mammography -------------------------------------------------------------


def test_mammogram_visit_orders_and_reads_a_mammogram_without_the_annual_labs() -> None:
    rec = _visit("mammography_screening", _patient(52, "F"))
    imaging = [o for o in rec.orders if o.order_type == OrderType.IMAGING]
    assert [o.display_name for o in imaging] == ["Bilateral_Mammography"]
    assert not [o for o in rec.orders if o.order_type == OrderType.LAB]
    assert rec.vital_signs == []  # the protocol takes no vitals
    assert rec.encounters[0].department_id == "radiology"
    studies = rec.extensions["imaging"]
    assert len(studies) == 1
    study = studies[0]
    assert (study.modality_code, study.body_site_snomed) == ("MG", "76752008")
    assert len(study.series) == 4
    assert "BI-RADS" in study.report.impression_text
    assert "_disease_id" not in rec.extensions


def test_mammogram_is_offered_to_women_40_to_74_only() -> None:
    schedule = screening_schedule("mammography_screening")
    assert (schedule.eligible_age, schedule.sex) == ("40-74", "F")
    years = range(2000, 2040)

    def offered(sex: str, age: int) -> int:
        person = PersonRecord(
            person_id=f"p-{sex}-{age}", household_id="h", age=age, sex=sex, date_of_birth=date(1970, 1, 1)
        )
        rng = determinism.default_rng(1)
        return sum(_calendar_screening_offered("mammography_screening", person, age, y, rng) for y in years)

    assert offered("M", 55) == 0
    assert offered("F", 39) == 0
    assert offered("F", 75) == 0
    assert offered("F", 55) > 0


# --- colonoscopy -------------------------------------------------------------


def test_colonoscopy_visit_performs_the_colonoscopy_under_sedation() -> None:
    rec = _visit("colonoscopy_screening", _patient(58, "M"))
    procs = rec.procedures
    assert [(p.procedure_code_us, p.procedure_type) for p in procs] == [("45378", "Colonoscopy")]
    assert (procs[0].end_datetime - procs[0].start_datetime).total_seconds() == 30 * 60
    assert procs[0].end_datetime <= rec.encounters[0].discharge_datetime
    assert rec.encounters[0].department_id == "gastroenterology"
    drugs = {m.drug_id for m in rec.medication_administrations}
    assert drugs and drugs <= {"midazolam", "fentanyl"}
    assert all(m.route == "IV" and m.status == "given" for m in rec.medication_administrations)
    sedation_orders = {o.order_id for o in rec.orders if o.order_type == OrderType.MEDICATION}
    assert {m.order_id for m in rec.medication_administrations} == sedation_orders


def test_colonoscopy_jp_keeps_the_cpt_code_when_no_jp_code_is_registered() -> None:
    rec = _visit("colonoscopy_screening", _patient(58, "M"), country="JP")
    assert [(p.procedure_code, p.procedure_code_jp) for p in rec.procedures] == [("45378", "")]


def test_colonoscopies_are_at_least_the_protocol_interval_apart() -> None:
    schedule = screening_schedule("colonoscopy_screening")
    assert (schedule.eligible_age, schedule.interval_years) == ("45-75", 10)
    rng = determinism.default_rng(2)
    for i in range(300):
        person = PersonRecord(person_id=f"pt-{i}", household_id="h", age=45, sex="M", date_of_birth=date(1960, 1, 1))
        years = [
            y
            for y in range(2000, 2040)
            if _calendar_screening_offered("colonoscopy_screening", person, y - 1960, y, rng)
        ]
        assert all(b - a >= 10 for a, b in zip(years, years[1:])), years
        assert all(45 <= y - 1960 <= 75 for y in years)


def test_colonoscopy_uptake_spreads_over_the_cycle() -> None:
    """About ``annual_uptake / interval_years`` of the eligible attend each year."""
    rng = determinism.default_rng(3)
    n = 4000
    hits = sum(
        _calendar_screening_offered(
            "colonoscopy_screening",
            PersonRecord(person_id=f"q-{i}", household_id="h", age=60, sex="F", date_of_birth=date(1964, 1, 1)),
            60,
            2024,
            rng,
        )
        for i in range(n)
    )
    assert 0.045 < hits / n < 0.085


# --- annual exam -------------------------------------------------------------


def test_us_annual_exam_adds_lipids_and_diabetes_screening_by_age_and_bmi() -> None:
    labs = screening_visit_spec(
        "annual_health_screening", _patient(50, "M", bmi=28.0), "US", determinism.default_rng(0)
    )["labs"]
    assert {"Lipid", "HbA1c", "Glucose"} <= set(labs)
    lean = screening_visit_spec(
        "annual_health_screening", _patient(50, "M", bmi=22.0), "US", determinism.default_rng(0)
    )
    assert "Lipid" in lean["labs"]
    old = screening_visit_spec("annual_health_screening", _patient(80, "M", bmi=28.0), "US", determinism.default_rng(0))
    assert "Lipid" not in old["labs"]


def test_us_annual_exam_has_no_screening_cxr_or_ecg_but_jp_checkup_can() -> None:
    for seed in range(20):
        us = screening_visit_spec("annual_health_screening", _patient(50, "F"), "US", determinism.default_rng(seed))
        assert us["imaging"] == []
    jp_tests = {
        i["test"]
        for seed in range(20)
        for i in screening_visit_spec(
            "annual_health_screening", _patient(50, "F"), "JP", determinism.default_rng(seed)
        )["imaging"]
    }
    assert jp_tests == {"Chest_Xray", "ECG"}


def test_annual_exam_draws_do_not_depend_on_the_country() -> None:
    """One draw per protocol entry whatever applies, so US and JP share the
    lab draws of a visit."""
    us = screening_visit_spec("annual_health_screening", _patient(30, "F"), "US", determinism.default_rng(4))
    jp = screening_visit_spec("annual_health_screening", _patient(30, "F"), "JP", determinism.default_rng(4))
    assert us["labs"] == jp["labs"]


def test_lipid_panel_is_ordered_as_its_components_under_the_panel() -> None:
    rec = _visit("annual_health_screening", _patient(50, "M", bmi=28.0))
    lipid = [o for o in rec.orders if o.panel_key == "Lipid"]
    assert {o.display_name for o in lipid} == {"TC", "LDL", "HDL", "TG"}
    assert all(o.result is not None for o in lipid)
    hba1c = [o for o in rec.orders if o.display_name == "HbA1c"]
    assert hba1c and hba1c[0].clinical_intent.startswith("Screening:")


def test_screening_lab_country_and_sex_filters() -> None:
    lab = {"test": "Lipid", "age": "40-75", "sex": "F", "countries": ["JP"]}
    assert screening_lab_applies(lab, _patient(50, "F"), "JP")
    assert not screening_lab_applies(lab, _patient(50, "F"), "US")
    assert not screening_lab_applies(lab, _patient(50, "M"), "JP")
    assert not screening_lab_applies(lab, _patient(39, "F"), "JP")
