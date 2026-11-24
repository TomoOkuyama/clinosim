"""Issue #3638: meropenem (US, JP) and piperacillin / tazobactam (US) are
dosed for the Cockcroft-Gault creatinine clearance, from the label bands of
``renal_antibiotic_dosing.yaml``."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.order.engine import enrich_medication_order, protocol_medication_orders
from clinosim.simulator.medication_pipeline import _generate_mar
from clinosim.simulator.renal_antibiotic_dose import (
    RenalDoseContext,
    apply_renal_dose,
    cockcroft_gault_ml_min,
)
from clinosim.types.encounter import Order, OrderResult
from clinosim.types.staff import StaffRoster

pytestmark = pytest.mark.unit

_ADM = datetime(2026, 3, 28, 15, 0)


def _patient(age: int = 70, sex: str = "M", weight: float = 66.7) -> SimpleNamespace:
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


def _creatinine(value: float, at: datetime = _ADM + timedelta(minutes=30)) -> OrderResult:
    return OrderResult(result_datetime=at, performed_by="T", lab_name="Creatinine", value=value, unit="mg/dL", flag="")


def _order(drug: str, dose: str, country: str) -> Order:
    (order,) = protocol_medication_orders(
        {"drug_id": drug, "dose": dose},
        order_id="ORD-E1-ADM-M01",
        encounter_id="E1",
        patient_id="P1",
        country=country,
        ordered_datetime=_ADM + timedelta(hours=1),
        ordered_by="DR",
    )
    return order


@pytest.fixture(autouse=True)
def _charted_weight(monkeypatch: pytest.MonkeyPatch) -> None:
    """The weight charted on the encounter is the test patient's weight."""
    monkeypatch.setattr(
        "clinosim.modules.population.encounter_anthropometry.encounter_weight_kg",
        lambda patient, *args, **kwargs: patient.weight_kg,
    )


def _adjust(order: Order, creatinine: float, country: str, patient: SimpleNamespace | None = None) -> Order:
    ctx = RenalDoseContext([_creatinine(creatinine)], country)
    apply_renal_dose(order, patient or _patient(), _ADM, _ADM + timedelta(hours=1), ctx)
    return order


def test_cockcroft_gault_matches_the_issue_example() -> None:
    # 70-year-old man, 66.7 kg, creatinine 3.96: about 16 mL/min.
    assert cockcroft_gault_ml_min(70, 66.7, 3.96, "M") == pytest.approx(16.4, abs=0.1)
    assert cockcroft_gault_ml_min(70, 66.7, 3.96, "F") == pytest.approx(16.4 * 0.85, abs=0.1)
    assert cockcroft_gault_ml_min(70, 0, 3.96, "M") is None


def test_jp_meropenem_1g_q8h_at_crcl_16_becomes_500mg_q12h() -> None:
    order = _adjust(_order("meropenem", "1g IV q8h", "JP"), 3.96, "JP")
    assert (order.dose_quantity, order.dose_unit, order.frequency, order.frequency_per_day) == (500.0, "mg", "Q12H", 2)
    assert order.renal_dose_adjusted and order.renal_crcl_ml_min == pytest.approx(16.4, abs=0.1)
    assert "CrCl 16" in order.clinical_intent and "CCr 16" in order.clinical_intent_ja


def test_us_meropenem_2g_q8h_at_crcl_11_becomes_1g_q12h() -> None:
    order = _adjust(_order("meropenem", "2g IV q8h", "US"), 5.33, "US", _patient(98, "M", 99.8))
    assert (order.dose_quantity, order.dose_unit, order.frequency) == (1.0, "g", "Q12H")


@pytest.mark.parametrize(
    ("creatinine", "dose", "unit", "frequency"),
    [
        (0.9, 1.0, "g", "Q8H"),  # CrCl > 50: unchanged
        (1.5, 1.0, "g", "Q12H"),  # 26-50: the dose, every 12 hours
        (3.0, 500.0, "mg", "Q12H"),  # 10-25: half dose, every 12 hours
        (7.5, 500.0, "mg", "DAILY"),  # < 10: half dose, every 24 hours
    ],
)
def test_meropenem_label_bands(creatinine: float, dose: float, unit: str, frequency: str) -> None:
    order = _adjust(_order("meropenem", "1g IV q8h", "US"), creatinine, "US")
    assert (order.dose_quantity, order.dose_unit, order.frequency) == (dose, unit, frequency)


def test_normal_renal_function_keeps_the_standard_dose_and_is_decided_once() -> None:
    order = _adjust(_order("meropenem", "1g IV q8h", "JP"), 0.8, "JP")
    assert (order.dose_quantity, order.frequency, order.renal_dose_adjusted) == (1.0, "Q8H", False)
    assert order.renal_crcl_ml_min is not None
    # A later, worse creatinine does not re-dose the decided order.
    _adjust(order, 5.0, "JP")
    assert (order.dose_quantity, order.frequency) == (1.0, "Q8H")


def test_us_piperacillin_tazobactam_bands_follow_the_nosocomial_pneumonia_column() -> None:
    mid = _adjust(_order("piperacillin_tazobactam", "4.5g IV q6h", "US"), 2.0, "US")  # CrCl about 31
    assert (mid.dose_quantity, mid.dose_unit, mid.frequency) == (3.375, "g", "Q6H")
    low = _adjust(_order("piperacillin_tazobactam", "4.5g IV q6h", "US"), 4.0, "US")  # about 16
    assert (low.dose_quantity, low.frequency) == (2.25, "Q6H")


def test_other_dose_of_pip_tazo_is_not_adjusted() -> None:
    order = _adjust(_order("piperacillin_tazobactam", "3.375g IV q6h", "US"), 4.0, "US")
    assert (order.dose_quantity, order.renal_dose_adjusted) == (3.375, False)


def test_unlisted_country_drug_or_a_child_is_unchanged() -> None:
    jp_pip = _adjust(_order("piperacillin_tazobactam", "4.5g IV q8h", "JP"), 4.0, "JP")
    assert not jp_pip.renal_dose_adjusted and jp_pip.renal_crcl_ml_min is None
    ceftriaxone = _adjust(_order("ceftriaxone", "1g IV daily", "US"), 4.0, "US")
    assert not ceftriaxone.renal_dose_adjusted
    child = _adjust(_order("meropenem", "1g IV q8h", "US"), 4.0, "US", _patient(age=9, weight=28.0))
    assert not child.renal_dose_adjusted


def test_no_creatinine_means_no_adjustment() -> None:
    order = _order("meropenem", "1g IV q8h", "US")
    apply_renal_dose(order, _patient(), _ADM, _ADM, RenalDoseContext([], "US"))
    assert not order.renal_dose_adjusted


def test_the_mar_gives_the_adjusted_interval_not_the_catalog_q8h() -> None:
    order = _order("meropenem", "1g IV q8h", "JP")
    enrich_medication_order(order)
    patient = _patient()
    ctx = RenalDoseContext([_creatinine(3.96)], "JP")
    given = []
    for day in range(3):
        given += _generate_mar(
            patient, [order], day, _ADM, roster=StaffRoster(), rng=np.random.default_rng(day), renal=ctx
        )
    assert order.renal_dose_adjusted
    per_day: dict[int, int] = {}
    for m in given:
        per_day[m.scheduled_datetime.day] = per_day.get(m.scheduled_datetime.day, 0) + 1
    assert max(per_day.values()) <= 2
    assert all(m.dose.startswith("500.0mg") or m.dose.startswith("500mg") for m in given)
