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
    event_type: str  # "acute_disease_onset" | "chronic_exacerbation" | "trauma" | "unknown_condition"
    timestamp: date
    severity: float = 0.5  # 0.0-1.0
    condition_type: str = "known_disease"  # "known_disease" | "mixed" | "unknown" (AD-28)
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
    """Generate life events for one month across the population. All Phase 1 diseases."""
    events: list[LifeEvent] = []
    event_date = date(year, month, 15)

    for person in registry.persons.values():
        if not person.is_alive:
            continue

        # --- Bacterial Pneumonia ---
        pn_rate = _disease_monthly_rate(
            person, "bacterial_pneumonia", month,
            _pneumonia_incidence, _PNEUMONIA_SEASONAL, _PNEUMONIA_RISK,
        )
        if rng.random() < pn_rate:
            severity = float(rng.beta(2, 3))
            events.append(LifeEvent(
                person_id=person.person_id, event_type="acute_disease_onset",
                timestamp=event_date + timedelta(days=int(rng.integers(0, 28))),
                severity=severity, disease_id="bacterial_pneumonia",
                requires_hospital=severity > person.care_seeking_threshold,
                condition_type="known_disease",
            ))

        # --- Heart Failure Exacerbation (requires prior HF diagnosis) ---
        if "I50" in person.chronic_conditions:
            hf_rate = _disease_monthly_rate(
                person, "heart_failure_exacerbation", month,
                _hf_exacerbation_incidence, _HF_SEASONAL, _HF_RISK,
            )
            if rng.random() < hf_rate:
                severity = float(rng.beta(3, 3))  # more uniform severity
                events.append(LifeEvent(
                    person_id=person.person_id, event_type="chronic_exacerbation",
                    timestamp=event_date + timedelta(days=int(rng.integers(0, 28))),
                    severity=max(0.3, severity),  # HF exacerbation is at least moderate
                    disease_id="heart_failure_exacerbation",
                    requires_hospital=severity > person.care_seeking_threshold * 0.8,
                    condition_type="known_disease",
                ))

        # --- Hip Fracture (trauma, age-dependent) ---
        hf_rate = _disease_monthly_rate(
            person, "hip_fracture", month,
            _hip_fracture_incidence, _HIP_SEASONAL, _HIP_RISK,
        )
        if rng.random() < hf_rate:
            # Hip fracture always requires hospital
            events.append(LifeEvent(
                person_id=person.person_id, event_type="trauma",
                timestamp=event_date + timedelta(days=int(rng.integers(0, 28))),
                severity=0.7 + float(rng.random() * 0.3),  # always moderate-severe
                disease_id="hip_fracture",
                requires_hospital=True,  # always
                condition_type="known_disease",
            ))

        # --- Mixed-cause: Pneumonia + HF overlap (elderly with both conditions) ---
        if ("I50" in person.chronic_conditions and person.age >= 65):
            # Probability of presenting with overlapping symptoms
            mixed_rate = 0.001 * _PNEUMONIA_SEASONAL.get(month, 1.0)  # rare but realistic
            if rng.random() < mixed_rate:
                events.append(LifeEvent(
                    person_id=person.person_id,
                    event_type="acute_disease_onset",
                    timestamp=event_date + timedelta(days=int(rng.integers(0, 28))),
                    severity=float(rng.beta(3, 2)),  # tends toward moderate-severe
                    disease_id="bacterial_pneumonia",  # primary label, but both are active
                    requires_hospital=True,
                    condition_type="mixed",  # ground truth: pneumonia + HF exacerbation
                ))

        # --- Unknown-cause conditions ---
        # FUO (fever of unknown origin): ~5% of fever admissions
        # Unexplained symptoms in elderly
        if person.age >= 50:
            unknown_rate = 0.0002 * (1.0 + (person.age - 50) * 0.01)
            if rng.random() < unknown_rate:
                pattern = str(rng.choice([
                    "fever_unknown", "weight_loss_unexplained",
                    "malaise_fatigue", "elevated_inflammatory_markers",
                ]))
                unk_severity = float(rng.beta(2, 3))
                events.append(LifeEvent(
                    person_id=person.person_id,
                    event_type="unknown_condition",
                    timestamp=event_date + timedelta(days=int(rng.integers(0, 28))),
                    severity=unk_severity,
                    disease_id=f"unknown_{pattern}",
                    requires_hospital=unk_severity > person.care_seeking_threshold,
                    condition_type="unknown",
                ))

    return events


def _disease_monthly_rate(
    person: PersonRecord, disease_id: str, month: int,
    incidence_fn: Any, seasonal: dict[int, float], risk_multipliers: dict[str, float],
) -> float:
    base_annual = incidence_fn(person.age, person.sex) / 100_000
    seasonal_mod = seasonal.get(month, 1.0)
    monthly = base_annual * seasonal_mod / 12
    for code, mult in risk_multipliers.items():
        if code in person.chronic_conditions:
            monthly *= mult
    return monthly


# === Seasonal curves ===
_PNEUMONIA_SEASONAL = {1: 1.8, 2: 1.6, 3: 1.3, 4: 1.0, 5: 0.8, 6: 0.7,
                       7: 0.7, 8: 0.7, 9: 0.8, 10: 1.0, 11: 1.3, 12: 1.7}
_HF_SEASONAL = {1: 1.3, 2: 1.2, 3: 1.1, 4: 1.0, 5: 0.9, 6: 0.9,
                7: 1.1, 8: 1.2, 9: 1.0, 10: 1.0, 11: 1.1, 12: 1.3}
_HIP_SEASONAL = {1: 1.4, 2: 1.3, 3: 1.1, 4: 1.0, 5: 0.9, 6: 0.8,
                 7: 0.8, 8: 0.8, 9: 0.9, 10: 1.0, 11: 1.1, 12: 1.3}

# === Risk multipliers ===
_PNEUMONIA_RISK = {"J44": 3.0, "E11.9": 1.5, "I50": 2.0, "N18": 1.8}
_HF_RISK = {"I10": 1.5, "E11.9": 1.3, "N18": 2.0, "I48": 1.5}
_HIP_RISK = {"M81": 3.0, "F00": 2.5, "G20": 2.0, "E11.9": 1.3}


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


def _pneumonia_incidence(age: int, sex: str = "M") -> float:
    """Age-specific pneumonia incidence per 100,000/year (JP)."""
    base = {0: 700, 5: 130, 15: 50, 25: 60, 35: 80, 45: 120,
            55: 200, 65: 500, 75: 1200, 85: 2500}
    rate = 60.0
    for a, r in sorted(base.items()):
        if age >= a:
            rate = r
    return rate * (1.0 if sex == "M" else 0.75)


def _hf_exacerbation_incidence(age: int, sex: str = "M") -> float:
    """Age-specific HF exacerbation incidence per 100,000/year among HF patients.
    This is the exacerbation rate, not new HF incidence.
    HF patients have ~25% annual hospitalization rate.
    """
    if age < 45:
        return 5000   # 5% of HF patients (rare in young)
    if age < 65:
        return 15000  # 15%
    if age < 75:
        return 20000  # 20%
    if age < 85:
        return 25000  # 25%
    return 30000      # 30%


def _hip_fracture_incidence(age: int, sex: str = "M") -> float:
    """Age-specific hip fracture incidence per 100,000/year (JP)."""
    base = {0: 3, 45: 8, 55: 25, 65: 80, 75: 300, 85: 700}
    rate = 3.0
    for a, r in sorted(base.items()):
        if age >= a:
            rate = r
    # Female: 2-3x higher (osteoporosis)
    return rate * (1.0 if sex == "M" else 2.5)
