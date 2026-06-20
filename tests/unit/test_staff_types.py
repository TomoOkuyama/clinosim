"""Regression: staff types are defined in clinosim/types/ (MOD-4).

StaffMember and StaffRoster used to be declared inside the staff engine module,
violating "all shared types live in clinosim/types/". They now live in
clinosim.types.staff and are re-exported from the staff module/package and the
top-level types package — every legacy import path must resolve to the SAME object.
"""

from __future__ import annotations

import pytest

from clinosim.modules.staff import StaffMember, StaffRoster
from clinosim.modules.staff.engine import StaffMember as EngineMember
from clinosim.modules.staff.engine import StaffRoster as EngineRoster
from clinosim.types import StaffMember as TypesPkgMember
from clinosim.types import StaffRoster as TypesPkgRoster
from clinosim.types.staff import StaffMember as CanonicalMember
from clinosim.types.staff import StaffRoster as CanonicalRoster


@pytest.mark.unit
def test_staff_types_canonical_location_is_clinosim_types_staff() -> None:
    """The canonical definition lives in clinosim.types.staff, not the engine."""
    assert CanonicalMember.__module__ == "clinosim.types.staff"
    assert CanonicalRoster.__module__ == "clinosim.types.staff"


@pytest.mark.unit
def test_all_import_paths_resolve_to_same_object() -> None:
    """Every legacy + new import path must be the identical class object."""
    assert EngineMember is CanonicalMember
    assert StaffMember is CanonicalMember
    assert TypesPkgMember is CanonicalMember

    assert EngineRoster is CanonicalRoster
    assert StaffRoster is CanonicalRoster
    assert TypesPkgRoster is CanonicalRoster


@pytest.mark.unit
def test_staff_types_fields_unchanged() -> None:
    """Dataclass fields/defaults are preserved by the move (golden-safe)."""
    m = StaffMember(staff_id="DR-IM-001", name="Test", role="physician", department="im")
    assert m.specialty == ""
    assert m.qualification_year == 2010
    assert m.ward == ""

    roster = StaffRoster()
    assert roster.members == []
    roster.members.append(m)
    assert roster.get_by_role("physician") == [m]
    assert roster.get_by_id("DR-IM-001") is m
    assert roster.get_by_id("missing") is None
