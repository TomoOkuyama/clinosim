"""Surgeons and anesthesiologists come from the right departments (#2068)."""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.staff.engine import assign_staff, generate_roster, select_surgical_team
from clinosim.types.staff import StaffMember, StaffRoster

pytestmark = pytest.mark.unit

_HOSPITAL = {
    "available_departments": ["internal_medicine", "emergency_medicine", "general_surgery", "orthopedics"],
    "resource_capacity": {"inpatient_beds": 120, "operating_rooms": 3},
}


def _dept_of(roster: StaffRoster, staff_id: str) -> str:
    member = roster.get_by_id(staff_id)
    assert member is not None
    return member.department


def test_roster_adds_anesthesiologists_last() -> None:
    roster = generate_roster("medium", "US", np.random.default_rng(3), hospital_config=_HOSPITAL)
    anes = [i for i, m in enumerate(roster.members) if m.department == "anesthesiology"]
    assert len(anes) >= 2
    assert anes == list(range(len(roster.members) - len(anes), len(roster.members)))
    assert all(roster.members[i].staff_id.startswith("DR-AN-") for i in anes)


def test_roster_without_surgery_has_no_anesthesiologists() -> None:
    clinic = {"available_departments": ["internal_medicine", "primary_care"], "resource_capacity": {}}
    roster = generate_roster("small", "US", np.random.default_rng(3), hospital_config=clinic)
    assert not roster.get_by_role("physician", "anesthesiology")


def test_surgical_team_comes_from_owning_department_and_anesthesiology() -> None:
    roster = generate_roster("medium", "US", np.random.default_rng(3), hospital_config=_HOSPITAL)
    rng = np.random.default_rng(5)
    for _ in range(30):
        surgeon, anesthesiologist = select_surgical_team(roster, "orthopedics", rng)
        assert _dept_of(roster, surgeon) == "orthopedics"
        assert _dept_of(roster, anesthesiologist) == "anesthesiology"


def test_non_surgical_department_falls_back_to_general_surgery() -> None:
    roster = generate_roster("medium", "US", np.random.default_rng(3), hospital_config=_HOSPITAL)
    surgeon, _ = select_surgical_team(roster, "neurosurgery", np.random.default_rng(5))
    assert _dept_of(roster, surgeon) == "general_surgery"


def test_without_anesthesiology_the_anesthetist_is_not_the_surgeon() -> None:
    roster = StaffRoster(
        members=[
            StaffMember(staff_id="DR-GS-001", name="a", role="physician", department="general_surgery"),
            StaffMember(staff_id="DR-IM-001", name="b", role="physician", department="internal_medicine"),
        ]
    )
    surgeon, anesthesiologist = select_surgical_team(roster, "general_surgery", np.random.default_rng(1))
    assert surgeon == "DR-GS-001" and anesthesiologist == "DR-IM-001"


def test_anesthesiologists_are_never_fallback_attendings() -> None:
    roster = generate_roster("medium", "US", np.random.default_rng(3), hospital_config=_HOSPITAL)
    rng = np.random.default_rng(9)
    for _ in range(50):
        attending = assign_staff("admission", "dermatology", roster, rng)["attending_physician"]
        assert _dept_of(roster, attending) != "anesthesiology"


def test_facility_emits_an_organization_for_every_roster_department() -> None:
    from clinosim.modules.output.fhir_r4.encounters.facility import _build_facility_bundle

    bundle = _build_facility_bundle(_HOSPITAL, "US")
    org_ids = {e["resource"]["id"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Organization"}
    roster = generate_roster("medium", "US", np.random.default_rng(3), hospital_config=_HOSPITAL)
    for dept in {m.department for m in roster.members if m.role == "physician"}:
        assert f"dept-{dept.replace('_', '-')}" in org_ids
