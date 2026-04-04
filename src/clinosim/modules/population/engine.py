"""Population engine — v0.1-beta: catchment area generation + life events.

Generates a lightweight population registry (Layer 1), runs monthly life events,
and produces care-seeking decisions that trigger hospital encounters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np


@dataclass
class PersonRecord:
    """Layer 1 person record — lightweight."""
    person_id: str
    household_id: str
    age: int
    sex: str
    date_of_birth: date
    family_name: str = ""
    given_name: str = ""
    phonetic: str | None = None  # JP: katakana reading
    blood_type: str = "A"
    chronic_conditions: list[str] = field(default_factory=list)
    is_alive: bool = True
    care_seeking_threshold: float = 0.3
    has_visited_hospital: bool = False
    visit_count: int = 0


@dataclass
class Household:
    household_id: str
    members: list[PersonRecord] = field(default_factory=list)
    region: str = "urban"


@dataclass
class LifeEvent:
    person_id: str
    event_type: str  # "acute_disease_onset" | "chronic_exacerbation" | "trauma"
    timestamp: date
    severity: float = 0.5  # 0.0-1.0
    disease_id: str = ""
    requires_hospital: bool = False


@dataclass
class PopulationRegistry:
    households: list[Household] = field(default_factory=list)
    persons: dict[str, PersonRecord] = field(default_factory=dict)

    def get_person(self, person_id: str) -> PersonRecord | None:
        return self.persons.get(person_id)

    @property
    def total_persons(self) -> int:
        return len(self.persons)


# Age distribution for Japan (simplified, per 1000)
JP_AGE_DISTRIBUTION = {
    (0, 14): 0.12, (15, 24): 0.09, (25, 34): 0.10, (35, 44): 0.12,
    (45, 54): 0.14, (55, 64): 0.13, (65, 74): 0.15, (75, 84): 0.10, (85, 99): 0.05,
}

JP_CHRONIC_PREVALENCE = {
    "I10": {(40, 99): 0.35},       # Hypertension
    "E11.9": {(40, 99): 0.10},     # Type 2 DM
    "E78": {(40, 99): 0.20},       # Dyslipidemia
    "J44": {(40, 99): 0.05},       # COPD
    "N18": {(60, 99): 0.08},       # CKD
    "I50": {(65, 99): 0.03},       # Heart failure
}

JP_BLOOD_TYPE = {"A": 0.40, "O": 0.30, "B": 0.20, "AB": 0.10}


def generate_population(
    size: int,
    country: str,
    rng: np.random.Generator,
    base_year: int = 2024,
) -> PopulationRegistry:
    """Generate a catchment area population with households."""
    registry = PopulationRegistry()
    avg_household_size = 2.3  # JP average
    n_households = int(size / avg_household_size)

    # Load name data and naming rules
    name_data = _load_name_data(country)
    from clinosim.locale.loader import load_naming_rules
    naming_rules = load_naming_rules(country)
    surname_rule = naming_rules.get("household_surname_rule", "shared")

    person_count = 0
    for h_idx in range(n_households):
        hh_id = f"HH-{h_idx+1:06d}"
        hh = Household(household_id=hh_id)

        # Household family name — rule depends on country
        # "shared": all members share one surname (JP, CN traditional)
        # "mostly_shared": most share, but wife may keep maiden (~20% US)
        # "not_shared": each person has own surname (KR, ES)
        household_surname = _sample_surname(name_data, rng)

        # Household size: 1-4 (weighted)
        hh_size = int(rng.choice([1, 2, 2, 3, 3, 4]))

        for m_idx in range(hh_size):
            if person_count >= size:
                break

            person_count += 1
            pid = f"POP-{person_count:06d}"

            # Age from distribution
            age_band = _sample_age_band(rng)
            age = int(rng.integers(age_band[0], age_band[1] + 1))

            sex = "M" if rng.random() < 0.49 else "F"
            dob = date(base_year - age, int(rng.integers(1, 13)), int(rng.integers(1, 29)))
            blood_type = str(rng.choice(list(JP_BLOOD_TYPE.keys()), p=list(JP_BLOOD_TYPE.values())))

            # Given name (sex-appropriate)
            given = _sample_given_name(name_data, sex, rng)

            # Family name — apply household surname rule
            if surname_rule == "shared":
                # All members share household surname (JP)
                member_surname = household_surname
            elif surname_rule == "mostly_shared":
                # First member sets surname; spouse may keep maiden with some probability
                maiden_prob = naming_rules.get("wife_keeps_maiden_probability", 0.20)
                if m_idx == 0:
                    member_surname = household_surname
                elif m_idx == 1 and sex == "F" and rng.random() < maiden_prob:
                    # Spouse keeps maiden name
                    member_surname = _sample_surname(name_data, rng)
                else:
                    member_surname = household_surname
            elif surname_rule == "not_shared":
                # Each person has own surname (KR, ES)
                if m_idx == 0:
                    member_surname = household_surname
                else:
                    member_surname = _sample_surname(name_data, rng)
            else:
                member_surname = household_surname

            # Chronic conditions
            conditions: list[str] = []
            for code, age_ranges in JP_CHRONIC_PREVALENCE.items():
                for (lo, hi), prev in age_ranges.items():
                    if lo <= age <= hi and rng.random() < prev:
                        conditions.append(code)

            # Care seeking threshold (JP: lower = more willing)
            threshold = float(rng.normal(0.30, 0.12))
            threshold = max(0.05, min(0.90, threshold))

            person = PersonRecord(
                person_id=pid,
                household_id=hh_id,
                age=age,
                sex=sex,
                date_of_birth=dob,
                family_name=member_surname.get("kanji", member_surname.get("name", "")),
                given_name=given.get("kanji", given.get("name", "")),
                phonetic=f"{member_surname.get('kana', '')} {given.get('kana', '')}".strip() or None,
                blood_type=blood_type,
                chronic_conditions=conditions,
                care_seeking_threshold=threshold,
            )
            hh.members.append(person)
            registry.persons[pid] = person

        registry.households.append(hh)

    return registry


def generate_monthly_events(
    registry: PopulationRegistry,
    year: int,
    month: int,
    rng: np.random.Generator,
) -> list[LifeEvent]:
    """Generate life events for one month across the population."""
    events: list[LifeEvent] = []
    event_date = date(year, month, 15)  # mid-month

    # Seasonal modifier for pneumonia
    seasonal = {1: 1.8, 2: 1.6, 3: 1.3, 4: 1.0, 5: 0.8, 6: 0.7,
                7: 0.7, 8: 0.7, 9: 0.8, 10: 1.0, 11: 1.3, 12: 1.7}
    season_mod = seasonal.get(month, 1.0)

    for person in registry.persons.values():
        if not person.is_alive:
            continue

        # Pneumonia incidence (simplified: age-dependent base rate)
        base_rate_annual = _pneumonia_incidence(person.age) / 100_000
        monthly_rate = base_rate_annual * season_mod / 12

        # Risk multipliers from chronic conditions
        if "J44" in person.chronic_conditions:  # COPD
            monthly_rate *= 3.0
        if "E11.9" in person.chronic_conditions:  # DM
            monthly_rate *= 1.5
        if "I50" in person.chronic_conditions:  # HF
            monthly_rate *= 2.0

        if rng.random() < monthly_rate:
            severity = float(rng.beta(2, 3))  # skewed toward mild
            # Care-seeking decision
            requires = severity > person.care_seeking_threshold
            events.append(LifeEvent(
                person_id=person.person_id,
                event_type="acute_disease_onset",
                timestamp=event_date + timedelta(days=int(rng.integers(0, 28))),
                severity=severity,
                disease_id="bacterial_pneumonia",
                requires_hospital=requires,
            ))

    return events


def _sample_age_band(rng: np.random.Generator) -> tuple[int, int]:
    bands = list(JP_AGE_DISTRIBUTION.keys())
    probs = list(JP_AGE_DISTRIBUTION.values())
    idx = int(rng.choice(len(bands), p=probs))
    return bands[idx]


def _load_name_data(country: str) -> dict:
    """Load name data from locale module."""
    from clinosim.locale.loader import load_names
    return load_names(country)


def _sample_surname(name_data: dict, rng: np.random.Generator) -> dict:
    """Sample a surname using weighted probability."""
    surnames = name_data.get("surnames", [])
    weights = np.array([s["weight"] for s in surnames], dtype=float)
    weights /= weights.sum()
    idx = int(rng.choice(len(surnames), p=weights))
    return surnames[idx]


def _sample_given_name(name_data: dict, sex: str, rng: np.random.Generator) -> dict:
    """Sample a given name appropriate for sex."""
    key = "given_names_male" if sex == "M" else "given_names_female"
    names = name_data.get(key, [])
    weights = np.array([n["weight"] for n in names], dtype=float)
    weights /= weights.sum()
    idx = int(rng.choice(len(names), p=weights))
    return names[idx]


def _pneumonia_incidence(age: int) -> float:
    """Age-specific pneumonia incidence per 100,000/year (JP, approximate)."""
    if age < 5:
        return 700
    if age < 15:
        return 130
    if age < 45:
        return 60
    if age < 65:
        return 150
    if age < 75:
        return 400
    if age < 85:
        return 1000
    return 2000
