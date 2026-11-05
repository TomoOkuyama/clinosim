"""Issue #2700: nurses are drawn from the patient's ward / department / clinic."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim import determinism
from clinosim.modules.nursing.engine import assign_primary_nurse
from clinosim.modules.staff.engine import scoped_nurses
from clinosim.types.staff import StaffMember, StaffRoster

pytestmark = pytest.mark.unit


def _nurse(sid: str, dept: str, ward: str) -> StaffMember:
    return StaffMember(staff_id=sid, name=sid, role="nurse", department=dept, ward=ward)


ROSTER = StaffRoster(
    members=[
        _nurse("NS-IM-001", "internal_medicine", "4E"),
        _nurse("NS-IM-002", "internal_medicine", "4W"),
        _nurse("NS-IM-003", "internal_medicine", "4W"),
        _nurse("NS-GS-001", "general_surgery", "3E"),
        _nurse("NS-OB-001", "obstetrics_gynecology", "2E"),
        _nurse("NS-PC-001", "primary_care", "OPD"),
    ]
)


@pytest.mark.parametrize("seed", range(20))
def test_the_primary_nurse_works_on_the_encounter_ward(seed: int) -> None:
    enc = SimpleNamespace(ward_id="4W", department_id="internal_medicine")
    assert assign_primary_nurse(enc, ROSTER, determinism.default_rng(seed)) in {"NS-IM-002", "NS-IM-003"}


def test_scoping_falls_back_to_the_department_then_everyone() -> None:
    assert [m.staff_id for m in scoped_nurses(ROSTER, ward="9Z", department="general_surgery")] == ["NS-GS-001"]
    assert len(scoped_nurses(ROSTER, ward="9Z", department="cardiology")) == len(ROSTER.members)


def test_adding_a_ward_does_not_move_other_patients() -> None:
    enc = SimpleNamespace(ward_id="4W", department_id="internal_medicine")
    bigger = StaffRoster(members=[*ROSTER.members, _nurse("NS-OB-002", "obstetrics_gynecology", "NBN")])
    for seed in range(20):
        assert assign_primary_nurse(enc, ROSTER, determinism.default_rng(seed)) == assign_primary_nurse(
            enc, bigger, determinism.default_rng(seed)
        )


def test_a_dose_given_during_a_stay_is_given_by_that_ward_nurse() -> None:
    from clinosim.modules.immunization.enricher import _give_stay_doses_by_ward_nurse

    nbn = _nurse("NS-OB-009", "obstetrics_gynecology", "NBN")
    roster = StaffRoster(members=[*ROSTER.members, nbn])
    stay = SimpleNamespace(
        encounter_id="E1", encounter_type="inpatient", ward_id="NBN", department_id="obstetrics_gynecology"
    )
    clinic = SimpleNamespace(encounter_id="E2", encounter_type="outpatient", ward_id="", department_id="primary_care")
    birth = SimpleNamespace(encounter_id="E1", administered_by="NS-PC-001")
    later = SimpleNamespace(encounter_id="E2", administered_by="NS-PC-001")
    _give_stay_doses_by_ward_nurse([birth, later], [stay, clinic], roster, "POP-1")
    assert birth.administered_by == "NS-OB-009" and later.administered_by == "NS-PC-001"
