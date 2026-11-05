"""Issue #2606: inpatient medication orders are closed when the stay ends."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.order.supersede import close_orders_at_discharge
from clinosim.types.encounter import (
    EncounterStatus,
    EncounterType,
    MedicationAdministration,
    Order,
    OrderStatus,
    OrderType,
)

pytestmark = pytest.mark.unit

_ADM = datetime(2025, 10, 2, 9, 0)
_DIS = datetime(2025, 10, 5, 11, 0)


def _enc(status: EncounterStatus = EncounterStatus.COMPLETED) -> SimpleNamespace:
    return SimpleNamespace(
        encounter_id="ENC-1",
        encounter_type=EncounterType.INPATIENT,
        status=status,
        admission_datetime=_ADM,
        discharge_datetime=_DIS,
    )


def _order(oid: str, status: OrderStatus = OrderStatus.PLACED) -> Order:
    return Order(
        order_id=oid,
        encounter_id="ENC-1",
        patient_id="P1",
        order_type=OrderType.MEDICATION,
        display_name="Ceftriaxone 1 g IV daily",
        ordered_datetime=_ADM,
        status=status,
    )


def _mar(oid: str, at: datetime) -> MedicationAdministration:
    return MedicationAdministration(order_id=oid, drug_name="Ceftriaxone", scheduled_datetime=at, actual_datetime=at)


def test_an_order_running_to_discharge_ends_at_its_last_dose() -> None:
    order = _order("O1")
    last = _ADM + timedelta(days=2, hours=1)
    close_orders_at_discharge([_enc()], [order], [_mar("O1", _ADM + timedelta(hours=1)), _mar("O1", last)])
    assert order.end_datetime == last and order.status == OrderStatus.PLACED


def test_a_stopped_order_ends_at_its_last_dose() -> None:
    order = _order("O1", OrderStatus.STOPPED)
    close_orders_at_discharge([_enc()], [order], [_mar("O1", _ADM + timedelta(hours=1))])
    assert order.end_datetime == _ADM + timedelta(hours=1)


def test_an_order_never_given_ends_at_discharge() -> None:
    order = _order("O1")
    close_orders_at_discharge([_enc()], [order], [])
    assert order.end_datetime == _DIS


def test_an_ongoing_stay_keeps_its_orders_open() -> None:
    order = _order("O1")
    close_orders_at_discharge([_enc(EncounterStatus.IN_PROGRESS)], [order], [_mar("O1", _ADM)])
    assert order.end_datetime is None


def test_the_medication_request_is_completed_with_an_end() -> None:
    from clinosim.modules.output.fhir_r4.medications.medications import _apply_order_end

    resource = {"status": "active", "dosageInstruction": [{"timing": {"repeat": {"frequency": 1, "period": 1}}}]}
    _apply_order_end(resource, {"end_datetime": "2025-10-04T10:00:00"}, "2025-10-02T09:00:00Z")
    bounds = resource["dosageInstruction"][0]["timing"]["repeat"]["boundsPeriod"]
    assert bounds["end"].startswith("2025-10-04T10:00:00") and bounds["start"] == "2025-10-02T09:00:00Z"


def test_the_validity_period_end_is_a_fhir_datetime() -> None:
    from clinosim.modules.output.fhir_r4.medications.medications import _build_mr_dispense_request

    disp = _build_mr_dispense_request(
        {"end_datetime": "2025-10-04 10:00:00"}, "2025-10-02T09:00:00Z", False, "inpatient", "US"
    )
    end = disp["validityPeriod"]["end"]
    assert "T" in end and (end.endswith("Z") or "+" in end[10:] or "-" in end[10:])
