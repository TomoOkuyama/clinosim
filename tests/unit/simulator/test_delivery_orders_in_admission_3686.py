"""A delivery admission starts before the delivery, in labor, so every order,
administration and the procedure lie inside the stay (Issue #3686)."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from clinosim.locale.loader import load_perinatal_config
from clinosim.modules.encounter.engine import create_inpatient_encounter
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.perinatal import simulate_delivery_encounter
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit
_DELIVERY = datetime(2025, 7, 15, 10, 0)
_VAGINAL, _CESAREAN = "POP-000001", "POP-000003"


def _deliver(pid: str, country: str):
    return simulate_delivery_encounter(
        patient=PatientProfile(patient_id=pid, sex="F", age=30),
        visit_date=_DELIVERY,
        roster=StaffRoster(),
        rng=np.random.default_rng(1),
        country=country,
        hospital_ops={},
    )


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize(("pid", "mode"), [(_VAGINAL, "vaginal"), (_CESAREAN, "cesarean")])
def test_everything_of_the_delivery_stay_is_inside_the_admission(pid: str, mode: str, country: str) -> None:
    mother, baby = _deliver(pid, country)
    assert mother.extensions["delivery"]["mode"] == mode
    enc = mother.encounters[0]
    labor = timedelta(hours=load_perinatal_config()["encounter"]["labor_hours_before_delivery"][mode])
    assert enc.admission_datetime == _DELIVERY - labor
    assert mother.orders
    for order in mother.orders:
        assert order.ordered_datetime >= enc.admission_datetime, order.order_id
    for mar in mother.medication_administrations:
        assert enc.admission_datetime <= mar.scheduled_datetime
    for vital in mother.vital_signs:
        assert vital.timestamp >= enc.admission_datetime
    proc = mother.procedures[0]
    assert proc.start_datetime == _DELIVERY and proc.start_datetime >= enc.admission_datetime
    # the newborn is admitted at the birth, and the mother's stay is the labor plus the length of stay
    assert baby.encounters[0].admission_datetime == _DELIVERY
    assert enc.discharge_datetime == baby.encounters[0].discharge_datetime


def test_the_encounter_id_does_not_depend_on_the_labor_hours() -> None:
    """Ids (and every sub-seed keyed on them) stay those of the delivery time."""
    mother, _ = _deliver(_VAGINAL, "US")
    reference = create_inpatient_encounter(
        "POP-000001",
        _DELIVERY,
        chief_complaint=mother.encounters[0].chief_complaint,
        department_id="obstetrics_gynecology",
        visit_number=0,
    )
    assert mother.encounters[0].encounter_id == reference.encounter_id
