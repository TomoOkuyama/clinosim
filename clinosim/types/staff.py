"""Staff types — roster members and the roster container (AD-18).

Runtime dataclasses shared across the staff, simulator, order, and procedure paths.
Defined here per the "all shared types live in clinosim/types/" rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["StaffMember", "StaffRoster"]


@dataclass
class StaffMember:
    staff_id: str
    name: str
    role: str  # "physician" | "nurse" | "lab_technician" | "radiologist" | "pharmacist"
    department: str
    specialty: str = ""
    qualification_year: int = 2010
    sex: str = ""           # "M" | "F"
    phone: str = ""         # work phone
    email: str = ""         # work email
    ward: str = ""          # primary ward assignment (for nurses)


@dataclass
class StaffRoster:
    members: list[StaffMember] = field(default_factory=list)

    def get_by_role(self, role: str, department: str = "") -> list[StaffMember]:
        return [
            m for m in self.members
            if m.role == role and (not department or m.department == department)
        ]

    def get_by_id(self, staff_id: str) -> StaffMember | None:
        for m in self.members:
            if m.staff_id == staff_id:
                return m
        return None
