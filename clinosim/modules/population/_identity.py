"""Identity-sampling cluster — name, occupation, address, phone.

Extracted verbatim from ``clinosim/modules/population/engine.py`` as
step C3c of the full-review Phase C engine split (CRITICAL C3).
Behavior is byte-identical — ``engine.py`` re-exports these names so
every call site stays intact.

All helpers thread an ``np.random.Generator`` through without reading
any shared global state.
"""

from __future__ import annotations

import numpy as np

from clinosim.modules._shared import is_jp, normalize_probabilities
from clinosim.modules.population._household_thresholds import (
    JP_ADDRESS_APARTMENT_PROBABILITY_DEFAULT,
    JP_ADDRESS_APARTMENT_ROOM_MAX_EXCLUSIVE,
    JP_ADDRESS_APARTMENT_ROOM_MIN,
    JP_ADDRESS_BANCHI_MAX_EXCLUSIVE,
    JP_ADDRESS_BANCHI_MIN,
    JP_ADDRESS_CHOME_MAX_EXCLUSIVE,
    JP_ADDRESS_CHOME_MIN,
    JP_ADDRESS_GO_MAX_EXCLUSIVE,
    JP_ADDRESS_GO_MIN,
    JP_PHONE_LANDLINE_NON_TOKYO_EXCHANGE_MAX_EXCLUSIVE,
    JP_PHONE_LANDLINE_NON_TOKYO_EXCHANGE_MIN,
    PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE,
    PHONE_4DIGIT_BLOCK_MIN,
    US_ADDRESS_APARTMENT_NUMBER_MAX_EXCLUSIVE,
    US_ADDRESS_APARTMENT_NUMBER_MIN,
    US_ADDRESS_APARTMENT_PROBABILITY_DEFAULT,
    US_ADDRESS_STREET_NUMBER_MAX_EXCLUSIVE,
    US_ADDRESS_STREET_NUMBER_MIN,
    US_PHONE_EXCHANGE_MAX_EXCLUSIVE,
    US_PHONE_EXCHANGE_MIN,
)


def _load_name_data(country: str) -> dict:
    """Load name data from locale module."""
    from clinosim.locale.loader import load_names

    return load_names(country)


def _sample_surname(name_data: dict, rng: np.random.Generator) -> dict:
    """Sample a surname using weighted probability."""
    surnames = name_data.get("surnames", [])
    weights = normalize_probabilities([s["weight"] for s in surnames], fallback="raise")
    idx = int(rng.choice(len(surnames), p=weights))
    return surnames[idx]


def _sample_occupation(demo: dict, age: int, sex: str, rng: np.random.Generator) -> str:
    """Sample occupation category from demographics occupation_distribution.

    Issue #360 G7 (iris4h-ai 2026-07-22): the pre-fix helper collapsed
    every age ≤ ``student_max_age`` (default 14) to the single label
    ``"student"``. A 2-year-old rendered as "学生 / student" on JP UI
    is clinically nonsensical — iris4h-ai's Clinical Cockpit flagged
    the ``POP-000004 (2歳)`` example as untrusted. Split by
    developmental stage so the emitted occupation reads correctly on
    both US and JP charts.

    Age brackets (Japanese 学制 & US convention aligned):
      < 3:      "infant"                (乳児)
      3-5:      "preschool"             (未就学児)
      6-11:     "elementary_student"    (小学生)
      12-14:    "middle_school_student" (中学生)
      15-17:    "high_school_student"   (高校生)
      18-21:    existing student/working split
      22-64:    existing working-age distribution
      65+:      "retired"
    """
    occ_cfg = demo.get("occupation_distribution") or {}
    thresholds = occ_cfg.get("age_thresholds") or {}
    student_max = int(thresholds.get("student_max_age", 14))
    young_max = int(thresholds.get("young_adult_max_age", 21))
    young_prob = float(thresholds.get("young_adult_student_prob", 0.70))
    retirement = int(thresholds.get("retirement_min_age", 65))

    if age <= student_max:
        if age < 3:
            return "infant"
        if age < 6:
            return "preschool"
        if age < 12:
            return "elementary_student"
        return "middle_school_student"
    if age >= retirement:
        return "retired"
    dist = occ_cfg.get("working_age") or {}
    if not dist:
        return "other"
    if age <= young_max and rng.random() < young_prob:
        return "student"
    keys = list(dist.keys())
    weights = normalize_probabilities([dist[k] for k in keys], fallback="raise")
    return str(rng.choice(keys, p=weights))


def _sample_given_name(name_data: dict, sex: str, rng: np.random.Generator) -> dict:
    """Sample a given name appropriate for sex."""
    key = "given_names_male" if sex == "M" else "given_names_female"
    names = name_data.get(key, [])
    weights = normalize_probabilities([n["weight"] for n in names], fallback="raise")
    idx = int(rng.choice(len(names), p=weights))
    return names[idx]


def _generate_household_address(addr_data: dict, rng: np.random.Generator) -> dict:
    """Generate a household address from locale address data."""
    cities = addr_data.get("cities", [])
    if not cities:
        return {"postal_code": "", "state": "", "city": "", "line": ""}

    probs = normalize_probabilities([c.get("weight", 1) for c in cities], fallback="raise")
    city_data = cities[int(rng.choice(len(cities), p=probs))]

    city = city_data.get("city", "")
    state = city_data.get("prefecture", addr_data.get("state", ""))
    zips = city_data.get("zips", ["00000"])
    postal_code = str(rng.choice(zips))

    country = addr_data.get("country", "US")
    if is_jp(country):
        towns = addr_data.get("towns", ["本町"])
        town = str(rng.choice(towns))
        chome = int(rng.integers(JP_ADDRESS_CHOME_MIN, JP_ADDRESS_CHOME_MAX_EXCLUSIVE))
        banchi = int(rng.integers(JP_ADDRESS_BANCHI_MIN, JP_ADDRESS_BANCHI_MAX_EXCLUSIVE))
        go = int(rng.integers(JP_ADDRESS_GO_MIN, JP_ADDRESS_GO_MAX_EXCLUSIVE))
        line = f"{town}{chome}丁目{banchi}-{go}"
        if rng.random() < addr_data.get("apartment_probability", JP_ADDRESS_APARTMENT_PROBABILITY_DEFAULT):
            apt_names = addr_data.get("apartment_names", ["マンション"])
            apt = str(rng.choice(apt_names))
            room = int(rng.integers(JP_ADDRESS_APARTMENT_ROOM_MIN, JP_ADDRESS_APARTMENT_ROOM_MAX_EXCLUSIVE))
            line += f" {apt}{room}"
    else:
        streets = addr_data.get("street_names", ["Main St"])
        street = str(rng.choice(streets))
        num = int(rng.integers(US_ADDRESS_STREET_NUMBER_MIN, US_ADDRESS_STREET_NUMBER_MAX_EXCLUSIVE))
        line = f"{num} {street}"
        if rng.random() < addr_data.get("apartment_probability", US_ADDRESS_APARTMENT_PROBABILITY_DEFAULT):
            apt_num = int(rng.integers(US_ADDRESS_APARTMENT_NUMBER_MIN, US_ADDRESS_APARTMENT_NUMBER_MAX_EXCLUSIVE))
            line += f", Apt {apt_num}"

    return {"postal_code": postal_code, "state": state, "city": city, "line": line}


def _generate_phone(addr_data: dict, phone_type: str, rng: np.random.Generator) -> str:
    """Generate a phone number from locale phone patterns."""
    phone_cfg = addr_data.get("phone", {})
    country = addr_data.get("country", "US")

    if is_jp(country):
        if phone_type == "mobile":
            prefixes = phone_cfg.get("mobile_prefix", ["090"])
            prefix = str(rng.choice(prefixes))
            mid = f"{int(rng.integers(PHONE_4DIGIT_BLOCK_MIN, PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE)):04d}"
            last = f"{int(rng.integers(PHONE_4DIGIT_BLOCK_MIN, PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE)):04d}"
            return f"{prefix}-{mid}-{last}"
        else:
            areas = phone_cfg.get("area_codes_landline", ["03"])
            area = str(rng.choice(areas))
            if area == "03":
                exchange = f"{int(rng.integers(PHONE_4DIGIT_BLOCK_MIN, PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE)):04d}"
                number = f"{int(rng.integers(PHONE_4DIGIT_BLOCK_MIN, PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE)):04d}"
                return f"{area}-{exchange}-{number}"
            else:
                exchange_int = int(
                    rng.integers(
                        JP_PHONE_LANDLINE_NON_TOKYO_EXCHANGE_MIN,
                        JP_PHONE_LANDLINE_NON_TOKYO_EXCHANGE_MAX_EXCLUSIVE,
                    )
                )
                exchange = f"{exchange_int:03d}"
                number = f"{int(rng.integers(PHONE_4DIGIT_BLOCK_MIN, PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE)):04d}"
                return f"{area}-{exchange}-{number}"
    else:
        if phone_type == "mobile":
            areas = phone_cfg.get("mobile_prefix", ["617"])
        else:
            areas = phone_cfg.get("area_codes", ["617"])
        area = str(rng.choice(areas))
        exchange = f"{int(rng.integers(US_PHONE_EXCHANGE_MIN, US_PHONE_EXCHANGE_MAX_EXCLUSIVE)):03d}"
        number = f"{int(rng.integers(PHONE_4DIGIT_BLOCK_MIN, PHONE_4DIGIT_BLOCK_MAX_EXCLUSIVE)):04d}"
        return f"({area}) {exchange}-{number}"
