"""Issue #3409: the maintenance IV-fluid order ends once the patient eats."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim import determinism
from clinosim.simulator.maintenance_iv_fluid import (
    is_maintenance_iv_fluid,
    maintenance_iv_fluid_rules,
    maintenance_iv_fluid_stopped,
    stop_maintenance_iv_fluid,
)
from clinosim.simulator.vitals_pipeline import _generate_daily_io
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit

ADMIT = datetime(2025, 3, 1, 9, 0)


def _order(detail: str = "NS 125 mL/h", order_type: OrderType = OrderType.MEDICATION) -> Order:
    return Order(
        order_id="ORD-E1-ADM-S00",
        encounter_id="E1",
        patient_id="P1",
        order_type=order_type,
        display_name=f"IV_fluid: {detail}",
        ordered_datetime=ADMIT,
        status=OrderStatus.PLACED,
    )


def _day_start(day: int) -> datetime:
    return datetime(2025, 3, 1 + day)


def test_stops_after_grace_once_the_diet_is_oral() -> None:
    o = _order()
    grace = maintenance_iv_fluid_rules().grace_days
    assert stop_maintenance_iv_fluid([o], 3, 3 - grace + 1, _day_start(3)) == []
    assert o.status == OrderStatus.PLACED
    assert stop_maintenance_iv_fluid([o], 3, 3 - grace, _day_start(3)) == [o]
    assert o.status == OrderStatus.STOPPED
    assert o.end_datetime == _day_start(3)


def test_not_stopped_without_oral_diet_before_the_cap() -> None:
    o = _order()
    assert stop_maintenance_iv_fluid([o], 3, None, _day_start(3)) == []
    assert o.status == OrderStatus.PLACED


def test_cap_stops_without_oral_diet() -> None:
    o = _order()
    day = maintenance_iv_fluid_rules().max_days
    assert stop_maintenance_iv_fluid([o], day, None, _day_start(day)) == [o]
    assert o.status == OrderStatus.STOPPED


@pytest.mark.parametrize(
    "detail",
    [
        "NS or LR 500-1000mL bolus, then 125-250mL/h",
        "NS or LR wide open, titrate to MAP > 65",
        "Parkland formula: LR 4mL × kg × %TBSA over 24h",
        "Lactated Ringer's 75-100 mL/h until oral intake",
        "Lactated Ringer 30 mL/kg bolus within 3 hours",
    ],
)
def test_bolus_and_titrated_fluids_are_not_maintenance(detail: str) -> None:
    o = _order(detail)
    assert not is_maintenance_iv_fluid(o)
    assert stop_maintenance_iv_fluid([o], 30, 1, _day_start(30)) == []
    assert o.status == OrderStatus.PLACED


def test_other_orders_are_untouched() -> None:
    other = _order("NS 125 mL/h")
    other.display_name = "Ceftriaxone 2 g IV daily"
    assert not is_maintenance_iv_fluid(other)
    assert stop_maintenance_iv_fluid([other], 30, 1, _day_start(30)) == []


def test_stopped_query_follows_end_time() -> None:
    o = _order()
    assert not maintenance_iv_fluid_stopped([o], _day_start(5))
    stop_maintenance_iv_fluid([o], 3, 1, _day_start(3))
    assert not maintenance_iv_fluid_stopped([o], _day_start(2))
    assert maintenance_iv_fluid_stopped([o], _day_start(3))


def _state():
    return SimpleNamespace(
        volume_status=0.0, inflammation_level=0.1, renal_function=1.0, cardiac_function=1.0, perfusion_status=1.0
    )


def test_io_has_no_iv_after_the_stop_and_keeps_the_draw_count() -> None:
    patient = SimpleNamespace(patient_id="POP-000777", weight_kg=70.0)
    rng_a, rng_b = determinism.default_rng(3), determinism.default_rng(3)
    running = [_generate_daily_io(_state(), patient, d, ADMIT, rng_a) for d in range(8)]
    stopped = [_generate_daily_io(_state(), patient, d, ADMIT, rng_b, maintenance_iv_stopped=d >= 4) for d in range(8)]
    assert all(r.intake_iv_ml > 0 for r in running[4:])
    assert all(r.intake_iv_ml == 0 for r in stopped[4:])
    assert [r.intake_iv_ml for r in stopped[:4]] == [r.intake_iv_ml for r in running[:4]]
    assert [r.intake_oral_ml for r in stopped[:4]] == [r.intake_oral_ml for r in running[:4]]
    # the patient drinks to cover the stopped IV volume
    assert min(r.intake_oral_ml for r in stopped[4:]) > 800
    assert rng_a.random() == rng_b.random()
