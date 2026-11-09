"""Issue #3082: inpatient children's antibiotics are dosed by weight.

The antibiotic entries of ``pediatric_dosing.yaml`` (Harriet Lane / AAP Red
Book mg/kg per dose, capped at the adult dose) apply to inpatient orders
written in grams as well as milligrams, and to the regimens the antibiotic
enricher adds after the stay; children get no routine pharmacologic VTE
prophylaxis.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.order.engine import enrich_medication_order
from clinosim.modules.order.pediatric_dose import pediatric_dose_text, redose_order_for_child
from clinosim.types.encounter import Order, OrderType

pytestmark = pytest.mark.unit

_SIX_YEARS = 6 * 12


@pytest.mark.parametrize(
    ("drug", "written", "child"),
    [
        ("ceftriaxone", "1g", "1g"),  # 50 mg/kg x 20 kg = the adult 1 g
        ("ceftriaxone", "2g", "1000mg"),
        ("meropenem", "1g", "400mg"),  # 20 mg/kg
        ("piperacillin_tazobactam", "3.375g", "2250mg"),  # 100 mg/kg piperacillin = 112.5 mg/kg combined
        ("cefepime", "1g", "1g"),  # 50 mg/kg x 20 kg = the adult 1 g
        ("vancomycin", "1g", "300mg"),  # 15 mg/kg
    ],
)
def test_a_20_kg_childs_antibiotics_are_weight_based_and_capped(drug: str, written: str, child: str) -> None:
    assert pediatric_dose_text(drug, written, _SIX_YEARS, 20.0) == child


def test_an_adult_keeps_the_written_dose() -> None:
    assert pediatric_dose_text("meropenem", "1g", 30 * 12, 70.0) == "1g"


def test_an_inpatient_order_written_in_grams_is_redosed() -> None:
    o = Order(order_id="ORD-1", order_type=OrderType.MEDICATION, display_name="Meropenem", drug_id="meropenem")
    enrich_medication_order(o, dose_str="1g IV q8h")
    redose_order_for_child(o, _SIX_YEARS, 20.0)
    assert (o.dose_quantity, o.dose_unit) == (400.0, "mg")


def _child_record() -> SimpleNamespace:
    from clinosim.types.hai import HAIEvent
    from clinosim.types.patient import PatientProfile

    patient = PatientProfile(patient_id="POP-KID", sex="F", age=3, date_of_birth=date(2022, 6, 1))
    ev = HAIEvent(
        hai_id="h1",
        encounter_id="enc-1",
        hai_type="cauti",
        source_device_id="d1",
        icd10_code="",
        snomed_code="",
        onset_date="2026-01-10",
        organism_snomed="",
        culture_specimen_id="",
    )
    return SimpleNamespace(
        patient=patient,
        encounters=[
            {
                "encounter_id": "enc-1",
                "admission_datetime": datetime(2026, 1, 6, 10),
                "ward_id": "W1",
                "department_id": "pediatrics",
            }
        ],
        orders=[],
        medication_administrations=[],
        microbiology=[],
        extensions={"hai": [ev]},
    )


def test_the_post_stay_antibiotic_regimen_of_a_child_is_weight_based() -> None:
    from clinosim.modules.antibiotic.enricher import enrich_antibiotic
    from clinosim.simulator.medication_pipeline import child_dosing

    rec = _child_record()
    cfg = SimpleNamespace(country="US", snapshot_date=None, time_range=("2026-01-01", "2026-12-31"))
    enrich_antibiotic(SimpleNamespace(config=cfg, master_seed=42, records=[rec], roster=None))
    child = child_dosing(rec.patient, "enc-1", datetime(2026, 1, 6, 10), "US")
    assert child is not None
    order = rec.orders[0]  # ceftriaxone 1 g q24h for an adult (CAUTI)
    expected = pediatric_dose_text("ceftriaxone", "1g", child.age_months, child.weight_kg)
    assert expected != "1g"
    assert f"{order.dose_quantity:g}{order.dose_unit}" == expected
    assert {m.dose for m in rec.medication_administrations} == {expected}


def test_no_routine_enoxaparin_prophylaxis_for_a_child_without_risk_factors() -> None:
    from clinosim.modules.prophylaxis.engine import should_skip_dvt_prophylaxis

    encounter = SimpleNamespace(admission_datetime=datetime(2026, 1, 6), discharge_datetime=datetime(2026, 1, 12))
    for age in (6, 11, 16, 17):
        patient = SimpleNamespace(age=age, current_medications=[])
        skip, reason = should_skip_dvt_prophylaxis(patient=patient, encounter=encounter, admission_dx_code="J18.9")
        assert skip and reason == "pediatric_age_gate", age
