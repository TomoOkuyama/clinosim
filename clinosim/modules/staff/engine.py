"""Staff engine — v0.1-beta: basic roster generation and assignment.

Generates a minimal staff roster for a hospital and assigns staff to clinical events.
Uses locale name data for country-appropriate staff names.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from clinosim.locale.loader import load_names


@dataclass
class StaffMember:
    staff_id: str
    name: str
    role: str  # "physician" | "nurse" | "lab_technician" | "radiologist" | "pharmacist"
    department: str
    specialty: str = ""
    qualification_year: int = 2010


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


def generate_roster(
    hospital_scale: str,
    country: str,
    rng: np.random.Generator,
) -> StaffRoster:
    """Generate a basic staff roster for the hospital."""
    roster = StaffRoster()
    # Internal Medicine: 10 physicians, 30 nurses
    for i in range(10):
        name = _generate_name("M" if i % 3 != 0 else "F", country, rng)
        roster.members.append(StaffMember(
            staff_id=f"DR-IM-{i+1:03d}",
            name=name,
            role="physician",
            department="internal_medicine",
            specialty="general" if i < 5 else [
                "pulmonology", "cardiology", "gastro", "nephro", "endo"
            ][i - 5],
            qualification_year=int(rng.integers(1985, 2020)),
        ))

    for i in range(30):
        name = _generate_name("F" if i % 5 != 0 else "M", country, rng)
        roster.members.append(StaffMember(
            staff_id=f"NS-IM-{i+1:03d}",
            name=name,
            role="nurse",
            department="internal_medicine",
            qualification_year=int(rng.integers(1995, 2023)),
        ))

    # Lab technicians: 10
    for i in range(10):
        name = _generate_name("F" if i % 2 == 0 else "M", country, rng)
        roster.members.append(StaffMember(
            staff_id=f"TECH-LAB-{i+1:03d}",
            name=name,
            role="lab_technician",
            department="laboratory",
            qualification_year=int(rng.integers(2000, 2023)),
        ))

    # Radiologists: 4
    for i in range(4):
        name = _generate_name("M", country, rng)
        roster.members.append(StaffMember(
            staff_id=f"DR-RAD-{i+1:03d}",
            name=name,
            role="radiologist",
            department="radiology",
            qualification_year=int(rng.integers(1990, 2015)),
        ))

    # Pharmacists: 8
    for i in range(8):
        name = _generate_name("F" if i % 2 == 0 else "M", country, rng)
        roster.members.append(StaffMember(
            staff_id=f"PH-{i+1:03d}",
            name=name,
            role="pharmacist",
            department="pharmacy",
            qualification_year=int(rng.integers(2000, 2023)),
        ))

    return roster


def assign_staff(
    event_type: str,
    department: str,
    roster: StaffRoster,
    rng: np.random.Generator,
) -> dict[str, str]:
    """Assign staff to a clinical event. Returns {role_in_event: staff_id}."""
    assignments: dict[str, str] = {}

    match event_type:
        case "admission" | "rounds" | "discharge":
            physicians = roster.get_by_role("physician", department)
            if physicians:
                assignments["attending_physician"] = rng.choice(physicians).staff_id
            nurses = roster.get_by_role("nurse", department)
            if nurses:
                assignments["primary_nurse"] = rng.choice(nurses).staff_id

        case "lab_collection" | "lab_result":
            techs = roster.get_by_role("lab_technician")
            if techs:
                assignments["performing_technician"] = rng.choice(techs).staff_id

        case "imaging_interpretation":
            rads = roster.get_by_role("radiologist")
            if rads:
                assignments["interpreting_radiologist"] = rng.choice(rads).staff_id

        case "medication_administration":
            nurses = roster.get_by_role("nurse", department)
            if nurses:
                assignments["administering_nurse"] = rng.choice(nurses).staff_id

    return assignments


def _generate_name(sex: str, country: str, rng: np.random.Generator) -> str:
    """Generate a staff name using locale name data."""
    names_data = load_names(country)
    surnames = names_data.get("surnames", [])
    given_key = "given_names_male" if sex == "M" else "given_names_female"
    givens = names_data.get(given_key, [])

    if not surnames or not givens:
        return f"Staff-{rng.integers(1000, 9999)}"

    # Extract name strings (JP uses "kanji", US uses "name")
    surname_list = [s.get("kanji", s.get("name", "")) for s in surnames]
    given_list = [g.get("kanji", g.get("name", "")) for g in givens]

    surname = rng.choice(surname_list)
    given = rng.choice(given_list)

    if country == "JP":
        return f"{surname} {given}"
    return f"{given} {surname}"
