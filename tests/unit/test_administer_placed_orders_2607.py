"""Issue #2607: orders placed outside the daily loop are administered."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.prophylaxis.enricher import enrich_prophylaxis
from clinosim.simulator.perinatal import simulate_delivery_encounter
from clinosim.types.encounter import EncounterStatus, EncounterType
from clinosim.types.patient import PatientProfile
from clinosim.types.staff import StaffMember, StaffRoster

pytestmark = pytest.mark.unit

_ADM = datetime(2025, 3, 1, 10, 0)
ROSTER = StaffRoster(
    members=[StaffMember(staff_id="NS-IM-001", name="n", role="nurse", department="internal_medicine", ward="4E")]
)


def _record(days: int) -> SimpleNamespace:
    enc = SimpleNamespace(
        encounter_id="ENC-1",
        encounter_type=EncounterType.INPATIENT,
        status=EncounterStatus.COMPLETED,
        admission_datetime=_ADM,
        discharge_datetime=_ADM + timedelta(days=days),
        attending_physician_id="DR-IM-001",
        ward_id="4E",
        department_id="internal_medicine",
    )
    patient = PatientProfile(patient_id="P1", sex="M", age=60)
    return SimpleNamespace(patient=patient, encounters=[enc], orders=[], medication_administrations=[])


def test_the_vte_prophylaxis_order_is_given_daily_until_discharge() -> None:
    rec = _record(days=4)
    enrich_prophylaxis(SimpleNamespace(records=[rec], roster=ROSTER))
    assert [o.display_name for o in rec.orders] == ["Enoxaparin"]
    mars = [m for m in rec.medication_administrations if m.order_id == rec.orders[0].order_id]
    times = [m.actual_datetime for m in mars]
    assert len(mars) == 4
    assert all(rec.orders[0].ordered_datetime <= t < rec.encounters[0].discharge_datetime for t in times)
    assert all(b - a == timedelta(days=1) for a, b in zip(times, times[1:]))
    assert {m.route for m in mars} == {"SC"} and {m.administered_by for m in mars} == {"NS-IM-001"}


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_delivery_order_is_administered(country: str) -> None:
    for seed in range(6):  # covers vaginal and cesarean deliveries
        mother = simulate_delivery_encounter(
            patient=PatientProfile(patient_id=f"POP-{seed:06d}", sex="F", age=30),
            visit_date=datetime(2025, 5, 1, 10, 0),
            roster=StaffRoster(),
            rng=np.random.default_rng(seed),
            country=country,
            hospital_ops={},
        )[0]
        given = {m.order_id for m in mother.medication_administrations}
        assert mother.orders and all(o.order_id in given for o in mother.orders)


def test_delivery_doses_fall_inside_the_stay() -> None:
    for seed in range(6):
        mother = simulate_delivery_encounter(
            patient=PatientProfile(patient_id=f"POP-{seed:06d}", sex="F", age=30),
            visit_date=datetime(2025, 5, 1, 10, 0),
            roster=StaffRoster(),
            rng=np.random.default_rng(seed),
            country="US",
            hospital_ops={},
        )[0]
        enc = mother.encounters[0]
        assert all(
            enc.admission_datetime <= m.actual_datetime <= enc.discharge_datetime
            for m in mother.medication_administrations
        )
