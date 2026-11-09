"""A minor's inpatient administrations and discharge prescription are dosed
by the weight charted at admission (Issue #3004)."""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.population.encounter_anthropometry import encounter_weight_kg
from clinosim.simulator.discharge_rx import build_discharge_rx
from clinosim.simulator.medication_pipeline import _generate_mar, child_dosing
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2025, 12, 10, 9, 0)
_ENC = "ENC-003004"


class _StubRoster:
    members: list = []

    def get_by_role(self, role: str, department: str | None = None) -> list:
        return []


def _child() -> PatientProfile:
    # 7 years old at admission; registered as a much smaller child.
    return PatientProfile(patient_id="POP-003004", sex="M", date_of_birth=date(2018, 6, 1), age=4, weight_kg=15.0)


def _order(order_id: str, name: str, **kw: object) -> Order:
    return Order(
        order_id=order_id,
        encounter_id=_ENC,
        patient_id="POP-003004",
        order_type=OrderType.MEDICATION,
        display_name=name,
        ordered_datetime=_ADMIT,
        status=OrderStatus.PLACED,
        **kw,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_child_dosing_uses_the_weight_charted_at_admission(country: str) -> None:
    child = child_dosing(_child(), _ENC, _ADMIT, country)
    assert child == (90, encounter_weight_kg(_child(), _ENC, _ADMIT, country), country)


def test_an_adult_has_no_child_dosing() -> None:
    adult = PatientProfile(patient_id="POP-A", date_of_birth=date(1980, 1, 1), age=45)
    assert child_dosing(adult, _ENC, _ADMIT, "US") is None


def test_the_inpatient_administrations_carry_the_childs_doses() -> None:
    patient = _child()
    child = child_dosing(patient, _ENC, _ADMIT, "JP")
    assert child is not None
    weight = child[1]
    oseltamivir = _order(
        "ORD-M01", "Oseltamivir", dose_quantity=75.0, dose_unit="mg", frequency="BID", frequency_per_day=2, route="PO"
    )
    fluid = _order("ORD-S00", "IV_fluid: NS 80-125 mL/h", route="IV")
    mars = _generate_mar(
        patient,
        [oseltamivir, fluid],
        day=0,
        admission_time=_ADMIT,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=np.random.default_rng(1),
        child=child,
    )
    assert oseltamivir.dose_quantity == round(2 * weight)
    assert fluid.dose_quantity < 80
    doses = {m.order_id: m.dose for m in mars}
    assert doses["ORD-M01"].startswith(f"{float(round(2 * weight))}mg")


def test_the_discharge_oseltamivir_is_weight_based() -> None:
    patient = _child()
    rx = build_discharge_rx(
        patient,
        "influenza",
        load_disease_protocol("influenza"),
        "PR-1",
        _ADMIT,
        encounter_id=_ENC,
        country_key="japan",
    )
    weight = encounter_weight_kg(patient, _ENC, _ADMIT, "JP")
    (item,) = [i for i in rx.items if "seltamivir" in i["drug_name"]]
    assert item["dose"].startswith(f"{round(2 * weight)}mg")
