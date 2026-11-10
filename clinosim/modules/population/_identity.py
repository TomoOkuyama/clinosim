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

from clinosim.locale.patterns import draw_pattern
from clinosim.modules._shared import normalize_probabilities


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


# The developmental-stage labels a child below working age gets in place of an
# occupation (ages <= ``student_max_age``). They are not occupations: the
# FHIR occupation Observation is not emitted for them (Issue #2630).
DEVELOPMENTAL_STAGES: frozenset[str] = frozenset({"infant", "preschool", "elementary_student", "middle_school_student"})


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
    high_school_max = int(thresholds.get("high_school_max_age", 17))
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
        occupation = "student"
    else:
        keys = list(dist.keys())
        weights = normalize_probabilities([dist[k] for k in keys], fallback="raise")
        occupation = str(rng.choice(keys, p=weights))
    # Issue #2674: a 15-17-year-old is in upper secondary school. The draws
    # above still run so the stream is consumed exactly as before.
    if age <= high_school_max:
        return "high_school_student"
    return occupation


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

    # Issue #3141: the street-line and apartment shapes are country data
    # (addresses.yaml ``street_line`` / ``apartment_line``), drawn in the
    # same order the per-country code drew them.
    line = draw_pattern(addr_data["street_line"], addr_data, rng)
    if rng.random() < float(addr_data["apartment_probability"]):
        line += draw_pattern(addr_data["apartment_line"], addr_data, rng)

    return {"postal_code": postal_code, "state": state, "city": city, "line": line}


def _generate_phone(addr_data: dict, phone_type: str, rng: np.random.Generator) -> str:
    """Generate a phone number from locale phone patterns.

    ``phone_type`` (``mobile`` / ``landline``) names the pattern in
    addresses.yaml ``phone`` (Issue #3141; clinosim/locale/patterns.py).
    """
    phone_cfg = addr_data["phone"]
    return draw_pattern(phone_cfg[phone_type], phone_cfg, rng)
