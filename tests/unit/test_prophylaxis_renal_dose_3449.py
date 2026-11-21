"""Issue #3449: prophylactic enoxaparin is dosed by renal function and country.

US: Lovenox 40 mg SC once daily for medical patients, 30 mg once daily when the
Cockcroft-Gault creatinine clearance is below 30 mL/min. JP: enoxaparin is
labelled only for orthopedic / abdominal surgery and contraindicated below 30
mL/min, so a medical inpatient gets low-dose unfractionated heparin.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from clinosim.modules.prophylaxis.engine import build_dvt_prophylaxis_orders
from clinosim.modules.prophylaxis.enricher import enrich_prophylaxis
from clinosim.modules.prophylaxis.renal_dose import crcl_cockcroft_gault

ADM = datetime(2026, 3, 2, 9, 0)


def _cr(hours: float, value: float) -> SimpleNamespace:
    return SimpleNamespace(
        lab_name="Creatinine", value=value, unit="mg/dL", result_datetime=ADM + timedelta(hours=hours)
    )


def _record(creatinines: list[SimpleNamespace], *, sex: str = "M", age: int = 80, weight: float = 60.0) -> Any:
    patient = SimpleNamespace(
        patient_id="PT-1",
        sex=sex,
        age=age,
        date_of_birth=f"{2026 - age}-01-01",
        height_cm=165.0,
        weight_kg=weight,
        current_medications=[],
    )
    enc = SimpleNamespace(
        encounter_id="ENC-1",
        encounter_type="inpatient",
        admission_datetime=ADM,
        discharge_datetime=ADM + timedelta(days=7),
        attending_physician_id="DR-1",
        ward_id="",
        department_id="",
    )
    return SimpleNamespace(
        patient=patient,
        encounters=[enc],
        orders=[],
        lab_results=creatinines,
        clinical_diagnosis=SimpleNamespace(discharge_diagnosis_code="J18.9", admission_diagnosis_code="J18.9"),
        medication_administrations=[],
    )


def test_cockcroft_gault_numeric() -> None:
    # (140 - 70) * 80 / (72 * 1.0) = 77.78 mL/min
    assert crcl_cockcroft_gault(
        1.0, 70, 80.0, "M", age_offset=140, denominator=72, female_factor=0.85
    ) == pytest.approx(77.7778, abs=1e-3)
    # female: x 0.85
    assert crcl_cockcroft_gault(
        1.0, 70, 80.0, "F", age_offset=140, denominator=72, female_factor=0.85
    ) == pytest.approx(66.1111, abs=1e-3)


def test_us_normal_renal_function_gets_the_standard_dose() -> None:
    orders = build_dvt_prophylaxis_orders(record=_record([_cr(-1, 0.9)], age=60, weight=80.0), country="US")
    assert [(o.display_name, o.dose_quantity, o.dose_unit, o.frequency) for o in orders] == [
        ("Enoxaparin", 40.0, "mg", "daily")
    ]


def test_us_severe_renal_impairment_gets_the_reduced_dose() -> None:
    # 80 y, 60 kg, Cr 2.5: (140-80)*60/(72*2.5) = 20 mL/min
    orders = build_dvt_prophylaxis_orders(record=_record([_cr(-1, 2.5)]), country="US")
    assert [(o.display_name, o.dose_quantity, o.dose_unit, o.frequency) for o in orders] == [
        ("Enoxaparin", 30.0, "mg", "daily")
    ]


def test_us_no_creatinine_keeps_the_standard_dose() -> None:
    orders = build_dvt_prophylaxis_orders(record=_record([]), country="US")
    assert orders[0].dose_quantity == 40.0


def test_us_creatinine_rising_during_the_stay_splits_the_order() -> None:
    record = _record([_cr(-1, 0.9), _cr(50, 2.6)], age=80, weight=60.0)
    orders = build_dvt_prophylaxis_orders(record=record, country="US")
    assert [o.dose_quantity for o in orders] == [40.0, 30.0]
    first, second = orders
    assert second.prior_order_id == first.order_id
    assert second.ordered_datetime == ADM + timedelta(hours=50)
    assert first.end_datetime == second.ordered_datetime
    assert first.status.value == "stopped"


def test_us_the_dose_stays_reduced_when_the_creatinine_recovers() -> None:
    record = _record([_cr(-1, 2.6), _cr(60, 0.9)], age=80, weight=60.0)
    orders = build_dvt_prophylaxis_orders(record=record, country="US")
    assert [o.dose_quantity for o in orders] == [30.0]


def test_us_a_noisy_creatinine_makes_one_split_at_most() -> None:
    record = _record([_cr(-1, 0.9), _cr(30, 2.6), _cr(55, 1.0), _cr(80, 2.7)], age=80, weight=60.0)
    orders = build_dvt_prophylaxis_orders(record=record, country="US")
    assert [o.dose_quantity for o in orders] == [40.0, 30.0]
    assert orders[1].ordered_datetime == ADM + timedelta(hours=30)


def test_enricher_gives_each_dose_in_the_period_of_its_order() -> None:
    record = _record([_cr(-1, 0.9), _cr(50, 2.6)], age=80, weight=60.0)
    ctx = SimpleNamespace(records=[record], roster=None, config=SimpleNamespace(country="US"))
    enrich_prophylaxis(ctx)
    by_order: dict[str, list[Any]] = {}
    for mar in record.medication_administrations:
        by_order.setdefault(mar.order_id, []).append(mar)
    first, second = record.orders
    assert {m.dose for m in by_order[first.order_id]} == {"40.0mg daily"}
    assert {m.dose for m in by_order[second.order_id]} == {"30.0mg daily"}
    assert max(m.scheduled_datetime for m in by_order[first.order_id]) < second.ordered_datetime
    assert min(m.scheduled_datetime for m in by_order[second.order_id]) >= second.ordered_datetime


@pytest.mark.parametrize("creatinine", [0.9, 3.0])
def test_jp_medical_inpatient_gets_low_dose_unfractionated_heparin(creatinine: float) -> None:
    orders = build_dvt_prophylaxis_orders(record=_record([_cr(-1, creatinine)]), country="JP")
    assert [(o.display_name, o.dose_quantity, o.dose_unit, o.frequency, o.frequency_per_day) for o in orders] == [
        ("Heparin", 5000.0, "IU", "q12h", 2)
    ]


def test_jp_enricher_gives_two_doses_a_day() -> None:
    record = _record([_cr(-1, 0.9)])
    ctx = SimpleNamespace(records=[record], roster=None, config=SimpleNamespace(country="JP"))
    enrich_prophylaxis(ctx)
    # ordered 15:00 on day 0 -> 21:00 that day, then 09:00 and 21:00 on days 1-6 (discharge 09:00 on day 7)
    assert len(record.medication_administrations) == 13
    assert {m.scheduled_datetime.hour for m in record.medication_administrations} == {9, 21}


def test_unknown_country_uses_the_us_regimen() -> None:
    orders = build_dvt_prophylaxis_orders(record=_record([_cr(-1, 0.9)], age=60, weight=80.0), country="XX")
    assert orders[0].display_name == "Enoxaparin"
