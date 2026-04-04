"""Staff engine — v0.1-beta: basic roster generation and assignment.

Generates a minimal staff roster for a hospital and assigns staff to clinical events.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Japanese surname frequency data (top 30)
JP_SURNAMES = [
    "佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤",
    "吉田", "山田", "佐々木", "松本", "井上", "木村", "林", "斎藤", "清水", "山口",
    "森", "池田", "橋本", "阿部", "石川", "山崎", "中島", "前田", "藤田", "小川",
]
JP_GIVEN_M = ["太郎", "一郎", "健", "誠", "翔太", "大輔", "直樹", "雄一", "浩二", "和也"]
JP_GIVEN_F = ["花子", "美咲", "陽子", "裕子", "恵子", "真由美", "智子", "由美", "幸子", "明美"]


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

    if hospital_scale == "medium" and country == "JP":
        # Internal Medicine: 10 physicians, 30 nurses
        for i in range(10):
            name = _generate_jp_name("M" if i % 3 != 0 else "F", rng)
            roster.members.append(StaffMember(
                staff_id=f"DR-IM-{i+1:03d}",
                name=name,
                role="physician",
                department="internal_medicine",
                specialty="general" if i < 5 else ["pulmonology", "cardiology", "gastro", "nephro", "endo"][i-5],
                qualification_year=int(rng.integers(1985, 2020)),
            ))

        for i in range(30):
            name = _generate_jp_name("F" if i % 5 != 0 else "M", rng)
            roster.members.append(StaffMember(
                staff_id=f"NS-IM-{i+1:03d}",
                name=name,
                role="nurse",
                department="internal_medicine",
                qualification_year=int(rng.integers(1995, 2023)),
            ))

        # Lab technicians: 10
        for i in range(10):
            name = _generate_jp_name("F" if i % 2 == 0 else "M", rng)
            roster.members.append(StaffMember(
                staff_id=f"TECH-LAB-{i+1:03d}",
                name=name,
                role="lab_technician",
                department="laboratory",
                qualification_year=int(rng.integers(2000, 2023)),
            ))

        # Radiologists: 4
        for i in range(4):
            name = _generate_jp_name("M", rng)
            roster.members.append(StaffMember(
                staff_id=f"DR-RAD-{i+1:03d}",
                name=name,
                role="radiologist",
                department="radiology",
                qualification_year=int(rng.integers(1990, 2015)),
            ))

        # Pharmacists: 8
        for i in range(8):
            name = _generate_jp_name("F" if i % 2 == 0 else "M", rng)
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


def _generate_jp_name(sex: str, rng: np.random.Generator) -> str:
    surname = rng.choice(JP_SURNAMES)
    given = rng.choice(JP_GIVEN_M if sex == "M" else JP_GIVEN_F)
    return f"{surname} {given}"
