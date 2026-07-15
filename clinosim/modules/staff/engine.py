"""Staff engine — v0.1-beta: basic roster generation and assignment.

Generates a minimal staff roster for a hospital and assigns staff to clinical events.
Uses locale name data for country-appropriate staff names.
"""

from __future__ import annotations

import numpy as np

from clinosim.locale.loader import load_names
from clinosim.modules._shared import is_jp
from clinosim.types.staff import StaffMember, StaffRoster

__all__ = ["StaffMember", "StaffRoster", "generate_roster", "assign_staff"]


def _gen_phone(country: str, rng: np.random.Generator) -> str:
    """Generate a fake work phone number."""
    if is_jp(country):
        return f"03-{int(rng.integers(3000, 6000))}-{int(rng.integers(1000, 9999))}"
    return f"({int(rng.integers(200, 999))}) {int(rng.integers(200, 999))}-{int(rng.integers(1000, 9999))}"


def _gen_email(staff_id: str) -> str:
    """Generate a fake work email."""
    return f"{staff_id.lower()}@hospital.example.org"


# Department code prefix for staff IDs (for readability)
_DEPT_PREFIX: dict[str, str] = {
    "internal_medicine": "IM",
    "cardiology": "CA",
    "pulmonology": "PU",
    "gastroenterology": "GI",
    "nephrology": "NE",
    "endocrinology": "EN",
    "neurology": "NR",
    "general_surgery": "GS",
    "orthopedics": "OR",
    "neurosurgery": "NS",
    "trauma_surgery": "TS",
    "emergency_medicine": "EM",
    "primary_care": "PC",
    "obstetrics_gynecology": "OB",
    "pediatrics": "PD",
}


def generate_roster(
    hospital_scale: str,
    country: str,
    rng: np.random.Generator,
    hospital_config: dict | None = None,
) -> StaffRoster:
    """Generate a staff roster scaled to hospital config.

    Uses hospital_config.available_departments and wards to distribute staff
    appropriately across departments. Each ward gets dedicated nursing staff.
    """
    roster = StaffRoster()
    hospital_config = hospital_config or {}
    available = hospital_config.get("available_departments", []) or ["internal_medicine"]
    wards_map = hospital_config.get("wards", {}) or {}
    beds_total = hospital_config.get("resource_capacity", {}).get("inpatient_beds", 50)

    def _add_physician(dept: str, idx: int, specialty: str = "") -> None:
        prefix = _DEPT_PREFIX.get(dept, dept[:2].upper())
        sex = "M" if rng.random() < 0.65 else "F"
        name, name_kana = _generate_name_pair(sex, country, rng)
        sid = f"DR-{prefix}-{idx:03d}"
        roster.members.append(
            StaffMember(
                staff_id=sid,
                name=name,
                role="physician",
                department=dept,
                specialty=specialty or dept,
                qualification_year=int(rng.integers(1985, 2020)),
                sex=sex,
                phone=_gen_phone(country, rng),
                email=_gen_email(sid),
                name_phonetic=name_kana,
            )
        )

    def _add_nurse(dept: str, idx: int, ward: str) -> None:
        prefix = _DEPT_PREFIX.get(dept, dept[:2].upper())
        sex = "F" if rng.random() < 0.85 else "M"
        name, name_kana = _generate_name_pair(sex, country, rng)
        sid = f"NS-{prefix}-{idx:03d}"
        roster.members.append(
            StaffMember(
                staff_id=sid,
                name=name,
                role="nurse",
                department=dept,
                specialty=dept,
                ward=ward,
                qualification_year=int(rng.integers(1995, 2023)),
                sex=sex,
                phone=_gen_phone(country, rng),
                email=_gen_email(sid),
                name_phonetic=name_kana,
            )
        )

    # Physicians per department (scaled with hospital size)
    # Formula: ~1 doctor per 5 beds minimum, more for internal medicine
    doctors_per_dept = {
        "internal_medicine": max(4, beds_total // 8),
        "cardiology": 2,
        "pulmonology": 2,
        "gastroenterology": 2,
        "nephrology": 1,
        "endocrinology": 1,
        "neurology": 2,
        "general_surgery": max(3, beds_total // 10),
        "orthopedics": 2,
        "neurosurgery": 2,
        "trauma_surgery": 2,
        "emergency_medicine": max(3, beds_total // 12),
        "primary_care": 2,
    }

    physician_counters: dict[str, int] = {}
    for dept in available:
        count = doctors_per_dept.get(dept, 2)
        physician_counters[dept] = 0
        for i in range(count):
            physician_counters[dept] += 1
            _add_physician(dept, physician_counters[dept])

    # Nurses per ward (scale: ~1 nurse per 2 beds, 6 nurses min per ward)
    # Assume beds evenly split across inpatient wards
    inpatient_wards: list[tuple[str, str]] = []
    for dept, ward_list in wards_map.items():
        if dept in ("emergency_medicine", "primary_care"):
            continue
        if dept not in available:
            continue
        for w in ward_list:
            if w not in ("ER", "OPD"):
                inpatient_wards.append((dept, w))

    nurse_counters: dict[str, int] = {}
    beds_per_ward = max(6, beds_total // max(1, len(inpatient_wards))) if inpatient_wards else 10
    nurses_per_ward = max(6, beds_per_ward // 2 + 3)  # ~1:2 ratio + buffer
    for dept, ward in inpatient_wards:
        nurse_counters.setdefault(dept, 0)
        for _ in range(nurses_per_ward):
            nurse_counters[dept] += 1
            _add_nurse(dept, nurse_counters[dept], ward)

    # ED / OPD nurses (shared across those areas)
    for area_dept in ("emergency_medicine", "primary_care"):
        if area_dept in available:
            ward = wards_map.get(area_dept, [area_dept[:3].upper()])[0]
            for _ in range(5):
                nurse_counters.setdefault(area_dept, 0)
                nurse_counters[area_dept] += 1
                _add_nurse(area_dept, nurse_counters[area_dept], ward)

    # Lab technicians (shared service)
    for i in range(10):
        sex = "F" if i % 2 == 0 else "M"
        name, name_kana = _generate_name_pair(sex, country, rng)
        sid = f"TECH-LAB-{i + 1:03d}"
        roster.members.append(
            StaffMember(
                staff_id=sid,
                name=name,
                role="lab_technician",
                department="laboratory",
                qualification_year=int(rng.integers(2000, 2023)),
                sex=sex,
                phone=_gen_phone(country, rng),
                email=_gen_email(sid),
                name_phonetic=name_kana,
            )
        )

    # Radiologists
    for i in range(4):
        sex = "M" if i % 2 == 0 else "F"
        name, name_kana = _generate_name_pair(sex, country, rng)
        sid = f"DR-RAD-{i + 1:03d}"
        roster.members.append(
            StaffMember(
                staff_id=sid,
                name=name,
                role="radiologist",
                department="radiology",
                qualification_year=int(rng.integers(1990, 2015)),
                sex=sex,
                phone=_gen_phone(country, rng),
                email=_gen_email(sid),
                name_phonetic=name_kana,
            )
        )

    # Pharmacists
    for i in range(8):
        sex = "F" if i % 2 == 0 else "M"
        name, name_kana = _generate_name_pair(sex, country, rng)
        sid = f"PH-{i + 1:03d}"
        roster.members.append(
            StaffMember(
                staff_id=sid,
                name=name,
                role="pharmacist",
                department="pharmacy",
                qualification_year=int(rng.integers(2000, 2023)),
                sex=sex,
                phone=_gen_phone(country, rng),
                email=_gen_email(sid),
                name_phonetic=name_kana,
            )
        )

    # C5-25 (Chain 3): roster expansion — multi-disciplinary staff types
    # typically present in a JP community hospital of this size. Counts
    # scaled to a 50-bed inpatient hospital and biased female per JP
    # allied-health workforce norms (PT/OT/ST/RD ~65% female; MSW ~70%).
    # Enables β-JP-1 multi-disciplinary CareTeam expansion and
    # nutrition-order emit paths downstream.
    _extra_roles: list[tuple[str, str, str, int, float]] = [
        # (role, id_prefix, department, count, female_ratio)
        ("physical_therapist", "PT", "rehabilitation", 4, 0.55),
        ("occupational_therapist", "OT", "rehabilitation", 2, 0.65),
        ("speech_therapist", "ST", "rehabilitation", 2, 0.75),
        ("medical_social_worker", "MSW", "medical_social_work", 2, 0.70),
        ("dietitian", "RD", "nutrition", 3, 0.90),
    ]
    for role, prefix, dept, count, female_ratio in _extra_roles:
        for i in range(count):
            sex = "F" if rng.random() < female_ratio else "M"
            name, name_kana = _generate_name_pair(sex, country, rng)
            sid = f"{prefix}-{i + 1:03d}"
            roster.members.append(
                StaffMember(
                    staff_id=sid,
                    name=name,
                    role=role,
                    department=dept,
                    qualification_year=int(rng.integers(2005, 2023)),
                    sex=sex,
                    phone=_gen_phone(country, rng),
                    email=_gen_email(sid),
                    name_phonetic=name_kana,
                )
            )

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
            # Try specialty-specific match first, then specialty match, then any physician
            physicians = roster.get_by_role("physician", department)
            if not physicians:
                # Match by specialty (e.g., cardiology → physician with specialty=cardiology)
                physicians = [
                    m
                    for m in roster.members
                    if m.role == "physician" and (m.specialty == department or department in m.specialty)
                ]
            if not physicians:
                # Fall back to any physician
                physicians = roster.get_by_role("physician")
            if physicians:
                assignments["attending_physician"] = rng.choice(physicians).staff_id
            nurses = roster.get_by_role("nurse", department)
            if not nurses:
                nurses = roster.get_by_role("nurse")
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
    """Generate a staff name using locale name data. Kanji-only string; see
    ``_generate_name_pair`` for the (kanji, kana) tuple used by JP rosters."""
    kanji, _kana = _generate_name_pair(sex, country, rng)
    return kanji


def _generate_name_pair(sex: str, country: str, rng: np.random.Generator) -> tuple[str, str]:
    """Generate (kanji, kana) name pair for staff.

    C2-19 continuation (session 43 cycle 5): JP roster gen now returns the
    kana reading alongside the kanji so ``StaffMember.name_phonetic`` can be
    populated and downstream FHIR emit adds the SYL (syllabic) HumanName
    entry required by JP Core Practitioner. Non-JP rosters return kana="".
    """
    names_data = load_names(country)
    surnames = names_data.get("surnames", [])
    given_key = "given_names_male" if sex == "M" else "given_names_female"
    givens = names_data.get(given_key, [])

    if not surnames or not givens:
        return f"Staff-{rng.integers(1000, 9999)}", ""

    # Preserve existing RNG stream ordering: rng.choice on the kanji list
    # (as before), then look up the kana column via the same index. Keeping
    # the same rng call preserves byte-diff for existing goldens.
    surname_list = [s.get("kanji", s.get("name", "")) for s in surnames]
    given_list = [g.get("kanji", g.get("name", "")) for g in givens]
    surname_kanji = str(rng.choice(surname_list))
    given_kanji = str(rng.choice(given_list))
    surname_kana = ""
    given_kana = ""
    for s in surnames:
        if s.get("kanji", s.get("name", "")) == surname_kanji:
            surname_kana = s.get("kana", "")
            break
    for g in givens:
        if g.get("kanji", g.get("name", "")) == given_kanji:
            given_kana = g.get("kana", "")
            break

    if is_jp(country):
        kanji = f"{surname_kanji} {given_kanji}"
        kana = f"{surname_kana} {given_kana}" if (surname_kana and given_kana) else ""
        return kanji, kana
    return f"{given_kanji} {surname_kanji}", ""
