"""Issue #2824: newborn prophylaxis doses name the giving nurse of the birth
encounter's ward, picked stably by the order (no RNG)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.newborn import enrich_newborn
from clinosim.types.clinical import ConditionEvent
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile
from clinosim.types.staff import StaffMember, StaffRoster

pytestmark = pytest.mark.unit


def _record() -> CIFPatientRecord:
    admit = datetime(2026, 6, 1, 10, 0)
    enc = Encounter(
        encounter_id="ENC-BABY-1",
        patient_id="POP-000001-BABY",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=admit,
        discharge_datetime=admit + timedelta(days=3),
        ward_id="NICU-W",
        department_id="pediatrics",
    )
    return CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-000001-BABY", sex="M", age=0),
        encounters=[enc],
        condition_event=ConditionEvent(
            condition_id="COND-POP-000001-BABY-BIRTH",
            condition_type="newborn_birth",
            ground_truth_diseases=["Z38.0"],
        ),
    )


def _roster() -> StaffRoster:
    def nurse(i: str, ward: str) -> StaffMember:
        return StaffMember(staff_id=f"NS-{i}", name=i, role="nurse", department="pediatrics", ward=ward)

    return StaffRoster(members=[nurse("A1", "NICU-W"), nurse("A2", "NICU-W"), nurse("B1", "OTHER")])


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_newborn_dose_names_a_nurse_of_the_birth_ward(country: str) -> None:
    rec = _record()
    ctx = SimpleNamespace(records=[rec], config=SimpleNamespace(country=country), roster=_roster())
    enrich_newborn(ctx)
    mars = rec.medication_administrations
    assert mars, "vitamin K / eye prophylaxis expected"
    assert {m.administered_by for m in mars} <= {"NS-A1", "NS-A2"}
