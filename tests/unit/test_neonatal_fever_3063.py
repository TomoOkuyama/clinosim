"""A febrile neonate gets the serious-bacterial-infection evaluation (Issue #3063)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim import determinism
from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.locale.loader import load_demographics
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.order.pediatric_dose import pediatric_order_name
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.emergency import _simulate_ed_visit, encounter_weight_kg
from clinosim.simulator.phases._ed_slot import neonatal_ed_onsets, neonate_excluded
from clinosim.types.encounter import OrderType

pytestmark = pytest.mark.unit

_T = datetime(2024, 6, 20, 3, 0)


def _visit(age_days: int, *, country: str = "US", severity: str = "moderate"):
    rng = determinism.default_rng(11)
    roster = generate_roster("medium", country, rng)
    person = PersonRecord(
        person_id="NN-1", household_id="H-1", age=0, sex="F", date_of_birth=(_T - timedelta(days=age_days)).date()
    )
    patient = activate_patient(person, rng, load_demographics(country))
    cond = load_encounter_condition("neonatal_fever")
    return _simulate_ed_visit(patient, cond, _T, roster, rng, country=country, force_severity=severity)


def _labs(record) -> set[str]:
    return {str(o.display_name) for o in record.orders if o.order_type == OrderType.LAB}


def _meds(record) -> list[str]:
    return [str(o.display_name) for o in record.orders if o.order_type == OrderType.MEDICATION]


def test_febrile_17_day_old_gets_the_neonatal_workup_and_is_transferred() -> None:
    record = _visit(17)
    assert {"Blood_culture", "Urinalysis", "Urine_culture", "WBC", "CRP", "Procalcitonin"} <= _labs(record)
    assert "lumbar_puncture" in {p.procedure_type for p in record.procedures}
    meds = _meds(record)
    assert any(m.startswith("Ampicillin") for m in meds) and any(m.startswith("Gentamicin") for m in meds)
    assert record.encounters[0].discharge_disposition == DischargeDisposition.OTHER_HCF


@pytest.mark.parametrize("age_days", [5, 25])
def test_lumbar_puncture_only_from_8_to_21_days(age_days: int) -> None:
    assert "lumbar_puncture" not in {p.procedure_type for p in _visit(age_days).procedures}


def test_neonatal_antibiotic_doses_are_weight_based() -> None:
    record = _visit(17)
    enc = record.encounters[0]
    weight = encounter_weight_kg(record.patient, enc.encounter_id, enc.admission_datetime, "US")
    assert weight and 2.0 < weight < 6.0
    doses = {m.split()[0]: float(re.search(r"(\d+(?:\.\d+)?)mg", m).group(1)) for m in _meds(record)}
    assert doses["Ampicillin"] == pytest.approx(50 * weight, abs=0.5)
    assert doses["Gentamicin"] == pytest.approx(4 * weight, abs=0.5)


def test_neonatal_dose_table_applies_up_to_28_days_only() -> None:
    assert pediatric_order_name("Gentamicin 120mg IV", 0, 3.5, "US", age_days=17) == "Gentamicin 14mg IV"
    # Past the neonatal period the child rule applies (gentamicin 2.5 mg/kg, Issue #3082).
    assert pediatric_order_name("Gentamicin 120mg IV", 1, 4.5, "US", age_days=35) == "Gentamicin 11mg IV"


def test_a_neonatal_dose_written_in_grams_gets_the_band() -> None:
    from clinosim.modules.order.pediatric_dose import pediatric_dose_text, redose_order_for_child
    from clinosim.types.encounter import Order, OrderStatus

    assert pediatric_dose_text("Cefotaxime", "1g IV q6h", 0, 3.5, "JP", age_days=5) == "175mg IV q6h"
    order = Order(
        order_id="O-G",
        encounter_id="ENC-G",
        patient_id="P-G",
        order_type=OrderType.MEDICATION,
        display_name="Ampicillin 2g IV q6h",
        ordered_datetime=datetime(2025, 3, 15, 9, 0),
        status=OrderStatus.PLACED,
        dose_quantity=2.0,
        dose_unit="g",
    )
    redose_order_for_child(order, 0, 3.5, "US", age_days=10)
    assert (order.dose_quantity, order.dose_unit, order.frequency) == (175.0, "mg", "q8h")
    assert order.display_name == "Ampicillin 175mg IV q8h"


def test_neonates_get_no_generic_ed_condition() -> None:
    person = SimpleNamespace(date_of_birth=date(2024, 6, 1))
    colic, nf = load_encounter_condition("renal_colic"), load_encounter_condition("neonatal_fever")
    conditions = [("renal_colic", colic), ("neonatal_fever", nf)]
    assert neonate_excluded(colic, person, datetime(2024, 6, 20), conditions)  # 19 days old
    assert neonate_excluded(colic, person, datetime(2024, 6, 29), conditions)  # 28 days old
    assert not neonate_excluded(colic, person, datetime(2024, 6, 30), conditions)  # 29 days old
    assert not neonate_excluded(nf, person, datetime(2024, 6, 20), conditions)


def _newborns(n: int, born: date) -> list:
    return [SimpleNamespace(person_id=f"P-{i}", date_of_birth=born) for i in range(n)]


def test_per_birth_onsets_follow_the_us_rate_within_the_neonatal_period() -> None:
    nf = load_encounter_condition("neonatal_fever")
    born = date(2024, 6, 10)
    people = _newborns(20000, born)
    onsets = [
        o for month in (6, 7) for o in neonatal_ed_onsets(nf, people, "US", master_seed=7, year=2024, month=month)
    ]
    assert len({pid for pid, _ in onsets}) == len(onsets)  # at most one per infant
    rate = float(nf["incidence_per_1000_births"]["US"]) / 1000
    assert abs(len(onsets) / 20000 - rate) < 4 * (rate / 20000) ** 0.5
    assert all(1 <= (when.date() - born).days <= 28 for _, when in onsets)
    again = [o for m in (6, 7) for o in neonatal_ed_onsets(nf, people, "US", master_seed=7, year=2024, month=m)]
    assert again == onsets


def test_no_per_birth_onsets_in_jp() -> None:
    nf = load_encounter_condition("neonatal_fever")
    people = _newborns(5000, date(2024, 6, 10))
    assert neonatal_ed_onsets(nf, people, "JP", master_seed=7, year=2024, month=6) == []


def test_a_hospital_with_a_pediatric_ward_admits_instead_of_ed_visits() -> None:
    from clinosim.simulator.phases._ed_slot import ed_severity_restriction

    nf = load_encounter_condition("neonatal_fever")
    assert ed_severity_restriction(nf, frozenset({"internal_medicine"})) == (None, 1.0)
    assert ed_severity_restriction(nf, frozenset({"pediatrics"}))[1] == 0.0


@pytest.mark.parametrize("severity", ["mild", "moderate", "severe"])
def test_every_febrile_neonate_charts_a_fever_at_triage(severity: str) -> None:
    band = load_encounter_condition("neonatal_fever")["triage_temperature_c"][severity]
    for age_days in (3, 10, 17, 26):
        temp = _visit(age_days, severity=severity).vital_signs[0].temperature_celsius
        assert 38.0 <= band[0] <= temp <= band[1]


def test_triage_temperature_is_hashed_from_the_encounter() -> None:
    from clinosim.simulator.emergency import presenting_temperature

    assert presenting_temperature([38.0, 38.5], "ENC-A") == presenting_temperature([38.0, 38.5], "ENC-A")
    assert 38.0 <= presenting_temperature([38.0, 38.5], "ENC-B") <= 38.5


def test_well_appearing_neonate_has_crp_below_the_aap_threshold() -> None:
    # AAP 2021: CRP above 20 mg/L is an abnormal inflammatory marker.
    crp = [
        next(float(o.result.value) for o in _visit(d, severity="mild").orders if o.display_name == "CRP")
        for d in (3, 10, 17, 26)
    ]
    assert all(c < 20 for c in crp)


def test_neonatal_dosing_intervals_follow_postnatal_age() -> None:
    from clinosim.modules.order.pediatric_dose import neonatal_interval_hours

    assert [neonatal_interval_hours("Cefotaxime", d) for d in (0, 7, 8, 28, 29)] == [12, 12, 8, 8, None]
    assert [neonatal_interval_hours("Ampicillin", d) for d in (3, 20)] == [8, 8]
    assert [neonatal_interval_hours("Gentamicin", d) for d in (3, 20)] == [24, 24]


def test_an_inpatient_neonatal_order_gets_the_band_dose_and_interval() -> None:
    from clinosim.simulator.medication_pipeline import child_dosing, dose_orders_for_child
    from clinosim.types.encounter import Order, OrderStatus
    from clinosim.types.patient import PatientProfile

    admit = datetime(2025, 3, 15, 9, 0)
    infant = PatientProfile(patient_id="POP-NN", sex="F", date_of_birth=date(2025, 3, 10), age=0, weight_kg=3.4)
    order = Order(
        order_id="O-1",
        encounter_id="ENC-NN",
        patient_id="POP-NN",
        order_type=OrderType.MEDICATION,
        display_name="Cefotaxime 2000mg IV q6h",
        ordered_datetime=admit,
        status=OrderStatus.PLACED,
    )
    child = child_dosing(infant, "ENC-NN", admit, "JP")
    assert child is not None and child.age_days == 5
    dose_orders_for_child([order], child)
    assert order.frequency == "q12h"
    assert order.dose_quantity == pytest.approx(50 * child.weight_kg, abs=0.5)


def test_jp_neonate_gets_cefotaxime_per_kg() -> None:
    record = _visit(17, country="JP")
    enc = record.encounters[0]
    weight = encounter_weight_kg(record.patient, enc.encounter_id, enc.admission_datetime, "JP")
    cef = next(m for m in _meds(record) if m.startswith("Cefotaxime"))
    assert float(re.search(r"(\d+(?:\.\d+)?)mg", cef).group(1)) == pytest.approx(50 * weight, abs=0.5)
