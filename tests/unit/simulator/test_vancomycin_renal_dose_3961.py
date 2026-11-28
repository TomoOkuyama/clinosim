"""Issue #3961: US intravenous vancomycin is dosed for the Cockcroft-Gault
creatinine clearance from the label's dosage table (mg per 24 h), the first
dose staying 15 mg/kg."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from clinosim.modules.order.engine import enrich_medication_order, protocol_medication_orders
from clinosim.simulator.medication_pipeline import _generate_mar
from clinosim.simulator.renal_antibiotic_dose import (
    RenalAntibioticDosing,
    RenalDoseContext,
    _rules,
    apply_renal_dose,
)
from clinosim.types.encounter import Order, OrderResult
from clinosim.types.staff import StaffRoster

pytestmark = pytest.mark.unit

_ADM = datetime(2026, 3, 28, 15, 0)
# openFDA "Vancomycin Hydrochloride", Dosage and Administration, "Dosage table
# for vancomycin in patients with impaired renal function": CrCl -> mg/24 h.
_LABEL_TABLE = {10: 155, 20: 310, 30: 465, 40: 620, 50: 770, 60: 925, 70: 1080, 80: 1235, 90: 1390, 100: 1545}


def _patient(age: int = 70, sex: str = "M", weight: float = 70.0) -> SimpleNamespace:
    return SimpleNamespace(
        patient_id="P1",
        age=age,
        sex=sex,
        date_of_birth=date(2026 - age, 3, 28),
        weight_kg=weight,
        height_cm=170.0,
        current_medications=[],
        baseline_vitals=None,
    )


def _creatinine(value: float) -> OrderResult:
    return OrderResult(
        result_datetime=_ADM + timedelta(minutes=30),
        performed_by="T",
        lab_name="Creatinine",
        value=value,
        unit="mg/dL",
        flag="",
    )


def _order(dose: str = "15mg/kg IV q8-12h", country: str = "US") -> Order:
    (order,) = protocol_medication_orders(
        {"drug_id": "vancomycin", "dose": dose},
        order_id="ORD-E1-ADM-M02",
        encounter_id="E1",
        patient_id="P1",
        country=country,
        ordered_datetime=_ADM + timedelta(hours=1),
        ordered_by="DR",
    )
    order.display_name = "Vancomycin 15 mg/kg IV Q8-12H"
    enrich_medication_order(order)
    return order


@pytest.fixture(autouse=True)
def _charted_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "clinosim.modules.population.encounter_anthropometry.encounter_weight_kg",
        lambda patient, *args, **kwargs: patient.weight_kg,
    )


def _adjust(order: Order, creatinine: float, country: str = "US", patient: SimpleNamespace | None = None) -> Order:
    ctx = RenalDoseContext([_creatinine(creatinine)], country)
    apply_renal_dose(order, patient or _patient(), _ADM, _ADM + timedelta(hours=1), ctx)
    return order


def test_label_table_is_loaded_as_written() -> None:
    bands = _rules().drugs["vancomycin"]["US"].bands
    assert {b.max_crcl: b.daily_dose_mg for b in bands} == _LABEL_TABLE
    assert all(b.interval_hours == 24 for b in bands)


def test_crcl_12_gets_the_label_daily_dose_once_a_day() -> None:
    order = _adjust(_order(), 5.67)  # 70 y, 70 kg: CrCl 12.0
    assert order.renal_crcl_ml_min == pytest.approx(12.0, abs=0.1)
    assert (order.dose_quantity, order.dose_unit, order.frequency, order.frequency_per_day) == (310.0, "mg", "DAILY", 1)
    assert order.renal_dose_adjusted
    assert order.display_name == "Vancomycin 310mg IV daily"
    assert "CrCl 12" in order.clinical_intent


@pytest.mark.parametrize(("creatinine", "daily_mg"), [(0.91, 1235), (0.72, 1545), (3.4, 310), (6.8, 155), (20.0, 155)])
def test_bands_follow_the_label_rows(creatinine: float, daily_mg: float) -> None:
    order = _adjust(_order(), creatinine)
    assert (order.dose_quantity, order.dose_unit) == (daily_mg, "mg")


def test_clearance_above_100_leaves_the_order_unchanged() -> None:
    order = _adjust(_order(), 0.6)  # CrCl about 113
    assert order.renal_crcl_ml_min is not None and order.renal_crcl_ml_min > 100
    assert (order.dose_quantity, order.dose_unit, order.frequency, order.renal_dose_adjusted) == (
        15.0,
        "mg/kg",
        "Q8-12H",
        False,
    )


def test_a_regimen_already_below_the_label_dose_is_not_raised() -> None:
    order = _order("10mg/kg IV q24h")
    order.display_name = "Vancomycin 10 mg/kg IV Q24H"
    _adjust(order, 0.91, patient=_patient(weight=40.0))  # 400 mg/day against 1,235
    assert (order.dose_quantity, order.dose_unit, order.renal_dose_adjusted) == (10.0, "mg/kg", False)


def test_oral_vancomycin_is_not_renally_adjusted() -> None:
    """Oral vancomycin (C. difficile) is not absorbed: the table is for the injection."""
    order = _order("125mg PO QID x10 days")
    assert order.route == "PO"
    _adjust(order, 5.67)
    assert (order.dose_quantity, order.dose_unit, order.renal_dose_adjusted) == (125.0, "mg", False)


def test_jp_is_unchanged_the_insert_gives_no_readable_clearance_numbers() -> None:
    order = _adjust(_order("15-20mg/kg IV q12h", "JP"), 5.67, "JP")
    assert not order.renal_dose_adjusted and order.dose_unit == "mg/kg"


def test_the_first_dose_is_15_mg_per_kg_then_the_label_dose_daily() -> None:
    order = _order()
    ctx = RenalDoseContext([_creatinine(5.67)], "US")
    given = []
    for day in range(3):
        given += _generate_mar(
            _patient(), [order], day, _ADM, roster=StaffRoster(), rng=np.random.default_rng(day), renal=ctx
        )
    given.sort(key=lambda m: m.scheduled_datetime)
    assert order.renal_dose_adjusted
    first, rest = given[0], given[1:]
    assert first.dose.startswith("1050mg")  # 15 mg/kg x 70 kg
    assert first.drug_name.startswith("Vancomycin 15 mg/kg")
    assert rest and all(float(m.dose.split("mg")[0]) == 310 for m in rest)
    assert all(m.drug_name == "Vancomycin 310mg IV daily" for m in rest)
    # one dose a calendar day: the maintenance does not double the first dose
    days = [m.scheduled_datetime.date() for m in given]
    assert len(days) == len(set(days))


def test_a_band_needs_exactly_one_of_dose_factor_and_daily_dose() -> None:
    base = {"cockcroft_gault": _rules().cockcroft_gault.model_dump()}
    with pytest.raises(ValidationError):
        RenalAntibioticDosing.model_validate(
            {**base, "drugs": {"x": {"US": {"bands": [{"max_crcl": 10, "interval_hours": 24}]}}}}
        )
    with pytest.raises(ValidationError):
        RenalAntibioticDosing.model_validate(
            {
                **base,
                "drugs": {
                    "x": {
                        "US": {
                            "bands": [{"max_crcl": 10, "interval_hours": 24, "dose_factor": 0.5, "daily_dose_mg": 100}]
                        }
                    }
                },
            }
        )
