"""Staff module — roster generation and clinical-event staff assignment."""

from clinosim.modules.staff.engine import (
    StaffMember,
    StaffRoster,
    assign_staff,
    generate_roster,
)

__all__ = ["StaffMember", "StaffRoster", "assign_staff", "generate_roster"]
