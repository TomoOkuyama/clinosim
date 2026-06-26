"""Population engine — v0.1-beta: catchment area generation + life events.

Generates a lightweight population registry (Layer 1), runs monthly life events,
and produces care-seeking decisions that trigger hospital encounters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from clinosim.modules._shared import normalize_probabilities
from clinosim.types.population import HospitalizationSummary, LifeEvent, PersonRecord

__all__ = ["HospitalizationSummary", "PersonRecord", "LifeEvent"]


@dataclass
class Household:
    household_id: str
    members: list[PersonRecord] = field(default_factory=list)
    region: str = "urban"


@dataclass
class PopulationRegistry:
    households: list[Household] = field(default_factory=list)
    persons: dict[str, PersonRecord] = field(default_factory=dict)

    def get_person(self, person_id: str) -> PersonRecord | None:
        return self.persons.get(person_id)

    @property
    def total_persons(self) -> int:
        return len(self.persons)


def _load_demographics(country: str) -> dict:
    """Load demographic data from locale."""
    from clinosim.locale.loader import load_demographics
    return load_demographics(country)


def _parse_age_distribution(demo: dict) -> tuple[list[tuple[int, int]], list[float]]:
    """Parse age_distribution from demographics YAML into bands and probs."""
    raw = demo.get("age_distribution", {})
    bands: list[tuple[int, int]] = []
    probs: list[float] = []
    for key, val in raw.items():
        lo, hi = key.split("-")
        bands.append((int(lo), int(hi)))
        probs.append(float(val))
    return bands, probs


@dataclass(frozen=True)
class ChronicConditionSpec:
    age_ranges: dict[tuple[int, int], float]
    sex: str  # "M", "F", or "" (any)


def _parse_chronic_prevalence(demo: dict) -> dict[str, ChronicConditionSpec]:
    """Parse chronic_prevalence from demographics YAML into structured dict.

    Supports optional ``sex: M`` or ``sex: F`` field to restrict conditions
    to a specific sex (e.g., BPH is male-only).
    """
    raw = demo.get("chronic_prevalence", {})
    result: dict[str, ChronicConditionSpec] = {}
    for code, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        sex_filter = str(entry.get("sex", ""))
        age_ranges: dict[tuple[int, int], float] = {}
        for key, prev in entry.items():
            if key == "sex":
                continue
            try:
                lo, hi = str(key).split("-")
                age_ranges[(int(lo), int(hi))] = float(prev)
            except (ValueError, TypeError):
                continue
        result[code] = ChronicConditionSpec(age_ranges=age_ranges, sex=sex_filter)
    return result


def generate_population(
    size: int,
    country: str,
    rng: np.random.Generator,
    base_year: int = 2024,
    demo: dict | None = None,
) -> PopulationRegistry:
    """Generate a catchment area population with households."""
    registry = PopulationRegistry()
    if demo is None:
        demo = _load_demographics(country)
    avg_household_size = demo.get("average_household_size", 2.5)
    n_households = int(size / avg_household_size)

    # Load name data and naming rules
    name_data = _load_name_data(country)
    from clinosim.locale.loader import load_naming_rules, load_addresses
    naming_rules = load_naming_rules(country)
    surname_rule = naming_rules.get("household_surname_rule", "shared")
    addr_data = load_addresses(country)

    person_count = 0
    for h_idx in range(n_households):
        hh_id = f"HH-{h_idx+1:06d}"
        hh = Household(household_id=hh_id)

        # Generate household address (shared by all members)
        hh_addr = _generate_household_address(addr_data, rng)
        hh_phone_home = _generate_phone(addr_data, "landline", rng)
        has_landline = rng.random() < addr_data.get("contact_rules", {}).get("household_has_landline_probability", 0.5)

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
            age_band = _sample_age_band(demo, rng)
            age = int(rng.integers(age_band[0], age_band[1] + 1))

            # Sex ratio from YAML (default 0.49 male)
            male_prob = (demo.get("sex_ratio") or {}).get("male", 0.49)
            sex = "M" if rng.random() < male_prob else "F"
            dob = date(base_year - age, int(rng.integers(1, 13)), int(rng.integers(1, 29)))
            bt = demo.get("blood_type", {"O": 0.44, "A": 0.42, "B": 0.10, "AB": 0.04})
            blood_type = str(rng.choice(list(bt.keys()), p=list(bt.values())))

            # BMI and height from physiology section
            phys = demo.get("physiology") or {}
            bmi_cfg = phys.get("bmi") or {}
            ht_cfg = phys.get("height_cm") or {}
            sex_key = "male" if sex == "M" else "female"

            bmi_mean = (bmi_cfg.get(sex_key) or {}).get("mean", 23.5 if sex == "M" else 22.0)
            bmi_std  = (bmi_cfg.get(sex_key) or {}).get("std", 3.5)
            bmi_clamp = bmi_cfg.get("clamp", [15.0, 45.0])
            bmi = float(np.clip(rng.normal(bmi_mean, bmi_std), bmi_clamp[0], bmi_clamp[1]))

            ht_mean = (ht_cfg.get(sex_key) or {}).get("mean", 170.0 if sex == "M" else 157.5)
            ht_std  = (ht_cfg.get(sex_key) or {}).get("std", 5.5)
            shrink  = ht_cfg.get("shrinkage_per_decade_after_60", 0.5)
            height  = float(rng.normal(ht_mean, ht_std))
            if age > 60:
                height -= (age - 60) / 10 * shrink

            # Lifestyle: smoking and alcohol (sex-specific distributions)
            lifestyle = demo.get("lifestyle_distribution") or {}
            smoking_dist = (lifestyle.get("smoking") or {}).get(sex_key, {})
            if smoking_dist:
                sk = list(smoking_dist.keys())
                sp = normalize_probabilities([smoking_dist[k] for k in sk])
                smoking_status = str(rng.choice(sk, p=sp))
            else:
                smoking_status = str(rng.choice(
                    ["never", "former", "current"], p=[0.55, 0.30, 0.15]
                ))

            alcohol_dist = (lifestyle.get("alcohol") or {}).get(sex_key, {})
            if alcohol_dist:
                ak = list(alcohol_dist.keys())
                ap = normalize_probabilities([alcohol_dist[k] for k in ak])
                alcohol_use = str(rng.choice(ak, p=ap))
            else:
                alcohol_use = str(rng.choice(
                    ["none", "social", "heavy"], p=[0.60, 0.30, 0.10]
                ))

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

            # Build accumulated multipliers from comorbidity correlations and lifestyle
            comorbidity_cfg = demo.get("comorbidity_correlations") or {}
            lifestyle_mults = demo.get("lifestyle_risk_multipliers") or {}
            bmi_cfg_lm = lifestyle_mults.get("bmi") or {}
            bmi_thresholds = bmi_cfg_lm.get("thresholds") or {"overweight": 25.0, "obese": 30.0}
            smoking_cfg_lm = lifestyle_mults.get("smoking") or {}

            bmi_cat: str | None = None
            if bmi >= bmi_thresholds.get("obese", 30.0):
                bmi_cat = "obese"
            elif bmi >= bmi_thresholds.get("overweight", 25.0):
                bmi_cat = "overweight"

            conditions: list[str] = []
            chronic_data = _parse_chronic_prevalence(demo)
            for code, spec in chronic_data.items():
                if spec.sex and spec.sex != sex:
                    continue  # e.g., BPH (N40) is male-only
                for (lo, hi), base_prev in spec.age_ranges.items():
                    if not (lo <= age <= hi):
                        continue
                    # Comorbidity correlation multiplier (from already-sampled conditions)
                    corr_mult = 1.0
                    for existing_code in conditions:
                        corr_mult *= (comorbidity_cfg.get(existing_code) or {}).get(code, 1.0)
                    # Lifestyle multipliers
                    life_mult = 1.0
                    if bmi_cat:
                        life_mult *= (bmi_cfg_lm.get(bmi_cat) or {}).get(code, 1.0)
                    life_mult *= (smoking_cfg_lm.get(smoking_status) or {}).get(code, 1.0)
                    # Cap combined prevalence at 1.0
                    final_prev = min(1.0, base_prev * corr_mult * life_mult)
                    if rng.random() < final_prev:
                        conditions.append(code)

            # Care seeking threshold (JP: lower = more willing)
            threshold = float(rng.normal(0.30, 0.12))
            threshold = max(0.05, min(0.90, threshold))

            # Phone: generate mobile for adults
            mobile = _generate_phone(addr_data, "mobile", rng) if age >= 15 else ""

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
                postal_code=hh_addr.get("postal_code", ""),
                state=hh_addr.get("state", ""),
                city=hh_addr.get("city", ""),
                address_line=hh_addr.get("line", ""),
                phone_home=hh_phone_home if has_landline else "",
                phone_mobile=mobile if age >= 15 else "",
                chronic_conditions=conditions,
                occupation=_sample_occupation(demo, age, sex, rng),
                bmi=bmi,
                smoking_status=smoking_status,
                alcohol_use=alcohol_use,
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
    country: str = "US",
    demo: dict | None = None,
) -> list[LifeEvent]:
    """Generate life events for one month across the population. All Phase 1 diseases."""
    events: list[LifeEvent] = []
    event_date = date(year, month, 15)

    # Load country-specific epidemiology from locale
    if demo is None:
        demo = _load_demographics(country)
    incidence = demo.get("disease_incidence", {})
    seasonal = demo.get("seasonal_modifiers", {})
    risk_mults = demo.get("disease_risk_multipliers", {})

    for person in registry.persons.values():
        if not person.is_alive:
            continue

        # Lifestyle risk multiplier prep — computed once per person, outside per-disease loop
        lifestyle_lm = demo.get("lifestyle_risk_multipliers") or {}
        smoking_lm = lifestyle_lm.get("smoking") or {}
        bmi_lm_cfg = lifestyle_lm.get("bmi") or {}
        bmi_thresh_lm = bmi_lm_cfg.get("thresholds") or {"overweight": 25.0, "obese": 30.0}

        bmi_cat_lm: str | None = None
        if person.bmi >= float(bmi_thresh_lm.get("obese", 30.0)):
            bmi_cat_lm = "obese"
        elif person.bmi >= float(bmi_thresh_lm.get("overweight", 25.0)):
            bmi_cat_lm = "overweight"

        # --- Data-driven disease event generation ---
        for disease_id, disease_spec in incidence.items():
            age_rates = disease_spec.get("age_rates", disease_spec.get("age_rates_among_hf", {}))
            if not age_rates:
                continue

            # Prerequisite check (e.g., HF exacerbation requires I50)
            prereq = disease_spec.get("prerequisite_condition")
            if prereq and prereq not in person.chronic_conditions:
                continue

            sex_ratio = disease_spec.get("sex_ratio_female", 1.0)
            disease_seasonal = seasonal.get(disease_id, {})
            disease_risk = risk_mults.get(disease_id, {})

            rate = _disease_monthly_rate_from_locale(
                person, month, age_rates, sex_ratio, disease_seasonal, disease_risk,
            )

            # Prior hospitalization for the same disease increases recurrence risk
            if hasattr(person, "hospitalization_history"):
                prior_same = [
                    h for h in person.hospitalization_history
                    if h.disease_id == disease_id
                ]
                if prior_same:
                    rate *= 1.5  # 50% higher recurrence after prior episode

            # Occupation-based risk multiplier (work-related injuries etc.)
            occ_mults = demo.get("occupation_risk_multipliers", {}).get(disease_id, {})
            if occ_mults and hasattr(person, "occupation"):
                # Default 0.2 for non-matching occupations: some residual risk
                # (e.g., office worker helping in warehouse, domestic accident)
                occ_mult = occ_mults.get(person.occupation, 0.2)
                rate *= float(occ_mult)

            # Lifestyle risk multipliers (smoking + BMI) — per-disease application
            smoking_mult_lm = float((smoking_lm.get(person.smoking_status) or {}).get(disease_id, 1.0))
            bmi_mult_lm = float((bmi_lm_cfg.get(bmi_cat_lm) or {}).get(disease_id, 1.0)) if bmi_cat_lm else 1.0
            rate *= smoking_mult_lm * bmi_mult_lm

            if rng.random() >= rate:
                continue

            # Severity from beta distribution
            beta_params = disease_spec.get("severity_beta", [2, 3])
            severity = float(rng.beta(beta_params[0], beta_params[1]))
            sev_min = disease_spec.get("severity_minimum")
            if sev_min is not None:
                severity = max(float(sev_min), severity)

            # Hospitalization decision
            event_type = disease_spec.get("event_type", "acute_disease_onset")
            if disease_spec.get("always_hospitalize"):
                requires_hospital = True
            else:
                threshold = person.care_seeking_threshold
                # Age-based threshold modifier
                age_mods = disease_spec.get("hospitalization_threshold_modifier_by_age", {})
                if age_mods:
                    for age_str in sorted(age_mods.keys(), key=int, reverse=True):
                        if person.age >= int(age_str):
                            threshold *= float(age_mods[age_str])
                            break
                # Flat modifier
                flat_mod = disease_spec.get("hospitalization_threshold_modifier")
                if flat_mod is not None:
                    threshold *= float(flat_mod)
                requires_hospital = severity > threshold

            events.append(LifeEvent(
                person_id=person.person_id,
                event_type=event_type,
                timestamp=event_date + timedelta(days=int(rng.integers(0, 28))),
                severity=severity,
                disease_id=disease_id,
                requires_hospital=requires_hospital,
                condition_type="known_disease",
            ))

        # --- Unknown-cause conditions ---
        unknown_cfg = demo.get("unknown_conditions", {})
        unknown_min_age = unknown_cfg.get("min_age", 40)
        unknown_base_rate = unknown_cfg.get("base_rate", 0.00008)
        unknown_age_factor = unknown_cfg.get("age_factor", 0.005)
        unknown_patterns = unknown_cfg.get("patterns", [
            "fever_unknown", "weight_loss_unexplained",
            "malaise_fatigue", "elevated_inflammatory_markers",
        ])
        if person.age >= unknown_min_age:
            unknown_rate = unknown_base_rate * (1.0 + (person.age - unknown_min_age) * unknown_age_factor)
            if rng.random() < unknown_rate:
                pattern = str(rng.choice(unknown_patterns))
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

    # --- Post-processing: upgrade some known_disease events to mixed ---
    mixed_cfg = demo.get("mixed_conditions", {})
    mixed_min_age = mixed_cfg.get("min_age", 70)
    mixed_min_chronic = mixed_cfg.get("min_chronic_conditions", 2)
    mixed_probability = mixed_cfg.get("probability", 0.18)
    for event in events:
        if event.condition_type == "known_disease" and event.requires_hospital:
            person = registry.persons.get(event.person_id)
            if (person and person.age >= mixed_min_age
                    and len(person.chronic_conditions) >= mixed_min_chronic):
                if rng.random() < mixed_probability:
                    event.condition_type = "mixed"

    return events


def _disease_monthly_rate_from_locale(
    person: PersonRecord,
    month: int,
    age_rates: dict,
    sex_ratio_female: float,
    seasonal: dict,
    risk_multipliers: dict,
) -> float:
    """Calculate monthly disease rate from locale epidemiology data."""
    # Find age-appropriate incidence rate
    rate = 0.0
    for age_str, r in sorted(age_rates.items(), key=lambda x: int(x[0])):
        if person.age >= int(age_str):
            rate = float(r)
    # Sex adjustment
    if person.sex == "F":
        rate *= sex_ratio_female
    # Annual to monthly
    monthly = (rate / 100_000) / 12
    # Seasonal
    seasonal_mod = seasonal.get(month, seasonal.get(str(month), 1.0))
    monthly *= float(seasonal_mod)
    # Risk multipliers from chronic conditions
    for code, mult in risk_multipliers.items():
        if code in person.chronic_conditions:
            monthly *= float(mult)
    return monthly


def _sample_age_band(demo: dict, rng: np.random.Generator) -> tuple[int, int]:
    bands, probs = _parse_age_distribution(demo)
    idx = int(rng.choice(len(bands), p=probs))
    return bands[idx]


def _load_name_data(country: str) -> dict:
    """Load name data from locale module."""
    from clinosim.locale.loader import load_names
    return load_names(country)


def _sample_surname(name_data: dict, rng: np.random.Generator) -> dict:
    """Sample a surname using weighted probability."""
    surnames = name_data.get("surnames", [])
    weights = normalize_probabilities([s["weight"] for s in surnames])
    idx = int(rng.choice(len(surnames), p=weights))
    return surnames[idx]


def _sample_occupation(demo: dict, age: int, sex: str, rng: np.random.Generator) -> str:
    """Sample occupation category from demographics occupation_distribution."""
    occ_cfg = demo.get("occupation_distribution") or {}
    thresholds = occ_cfg.get("age_thresholds") or {}
    student_max   = int(thresholds.get("student_max_age", 14))
    young_max     = int(thresholds.get("young_adult_max_age", 21))
    young_prob    = float(thresholds.get("young_adult_student_prob", 0.70))
    retirement    = int(thresholds.get("retirement_min_age", 65))

    if age <= student_max:
        return "student"
    if age >= retirement:
        return "retired"
    dist = occ_cfg.get("working_age") or {}
    if not dist:
        return "other"
    if age <= young_max and rng.random() < young_prob:
        return "student"
    keys = list(dist.keys())
    weights = normalize_probabilities([dist[k] for k in keys])
    return str(rng.choice(keys, p=weights))


def _sample_given_name(name_data: dict, sex: str, rng: np.random.Generator) -> dict:
    """Sample a given name appropriate for sex."""
    key = "given_names_male" if sex == "M" else "given_names_female"
    names = name_data.get(key, [])
    weights = normalize_probabilities([n["weight"] for n in names])
    idx = int(rng.choice(len(names), p=weights))
    return names[idx]




def generate_healthcare_calendar(
    registry: PopulationRegistry,
    year: int,
    country: str,
    rng: np.random.Generator,
) -> list[LifeEvent]:
    """Generate a year's healthcare calendar for ALL population members.

    This includes:
    - Chronic disease management visits (for everyone with chronic conditions)
    - Annual health screening (age 40+)
    - ED visits (non-admitted, from demographics config)

    Acute disease events are generated separately by generate_monthly_events().
    """
    events: list[LifeEvent] = []

    # Load follow-up schedules
    from clinosim.locale.loader import load_chronic_followup
    followup_data = load_chronic_followup()

    for person in registry.persons.values():
        if not person.is_alive:
            continue

        # --- Chronic disease visits ---
        # Group conditions into combined visits (real patients see one doctor
        # for multiple conditions in a single visit)
        conditions_with_spec = [
            (code, followup_data.get(code))
            for code in person.chronic_conditions
            if followup_data.get(code)
        ]
        if not conditions_with_spec:
            continue

        # Use shortest interval as visit frequency (covers all conditions)
        shortest_interval = min(
            spec.get("follow_up_interval_months", 3)
            for _, spec in conditions_with_spec
        )
        # Cap: max 6 visits/year for chronic management
        max_visits = min(12 // shortest_interval, 6)
        primary_code = conditions_with_spec[0][0]  # main condition for the visit

        month = int(rng.integers(1, min(shortest_interval + 1, 4)))
        visit_count = 0
        while month <= 12 and visit_count < max_visits:
            visit_date = date(year, month, int(rng.integers(1, 28)))
            events.append(LifeEvent(
                person_id=person.person_id,
                event_type="chronic_visit",
                timestamp=visit_date,
                severity=0.0,
                condition_type="chronic_followup",
                disease_id=primary_code,
                encounter_type="outpatient",
                protocol_source=f"chronic_followup:{primary_code}",
            ))
            month += shortest_interval
            visit_count += 1

        # --- Annual health screening (age 40+) ---
        if person.age >= 40:
            screening_month = int(rng.integers(4, 11))
            screening_date = date(year, screening_month, int(rng.integers(1, 28)))
            events.append(LifeEvent(
                person_id=person.person_id,
                event_type="health_screening",
                timestamp=screening_date,
                severity=0.0,
                condition_type="screening",
                disease_id="annual_health_screening",
                encounter_type="outpatient",
                protocol_source="screening:annual",
            ))

        # --- Flu vaccination (age 65+ or chronic conditions, Oct-Dec) ---
        if person.age >= 65 or len(person.chronic_conditions) >= 2:
            if rng.random() < 0.5:  # ~50% vaccination rate
                vax_month = int(rng.choice([10, 11, 12]))
                events.append(LifeEvent(
                    person_id=person.person_id,
                    event_type="chronic_visit",
                    timestamp=date(year, vax_month, int(rng.integers(1, 28))),
                    severity=0.0,
                    condition_type="screening",
                    disease_id="flu_vaccination",
                    encounter_type="outpatient",
                    protocol_source="encounter:flu_vaccination",
                ))

        # --- Colonoscopy screening (age 50+, every 10 years → ~10% per year) ---
        if person.age >= 50 and rng.random() < 0.08:
            events.append(LifeEvent(
                person_id=person.person_id,
                event_type="health_screening",
                timestamp=date(year, int(rng.integers(1, 13)), int(rng.integers(1, 28))),
                severity=0.0,
                condition_type="screening",
                disease_id="colonoscopy_screening",
                encounter_type="outpatient",
                protocol_source="encounter:colonoscopy_screening",
            ))

        # --- Mammography screening (women 40+, annual → ~60% participation) ---
        if person.sex == "F" and person.age >= 40 and rng.random() < 0.4:
            events.append(LifeEvent(
                person_id=person.person_id,
                event_type="health_screening",
                timestamp=date(year, int(rng.integers(1, 13)), int(rng.integers(1, 28))),
                severity=0.0,
                condition_type="screening",
                disease_id="mammography_screening",
                encounter_type="outpatient",
                protocol_source="encounter:mammography_screening",
            ))

        # --- Diabetic retinopathy screening (DM patients, annual) ---
        if "E11.9" in person.chronic_conditions and rng.random() < 0.6:
            events.append(LifeEvent(
                person_id=person.person_id,
                event_type="chronic_visit",
                timestamp=date(year, int(rng.integers(1, 13)), int(rng.integers(1, 28))),
                severity=0.0,
                condition_type="screening",
                disease_id="diabetic_retinopathy_screening",
                encounter_type="outpatient",
                protocol_source="encounter:diabetic_retinopathy_screening",
            ))

    return events


def _generate_household_address(addr_data: dict, rng: np.random.Generator) -> dict:
    """Generate a household address from locale address data."""
    cities = addr_data.get("cities", [])
    if not cities:
        return {"postal_code": "", "state": "", "city": "", "line": ""}

    probs = normalize_probabilities([c.get("weight", 1) for c in cities])
    city_data = cities[int(rng.choice(len(cities), p=probs))]

    city = city_data.get("city", "")
    state = city_data.get("prefecture", addr_data.get("state", ""))
    zips = city_data.get("zips", ["00000"])
    postal_code = str(rng.choice(zips))

    country = addr_data.get("country", "US")
    if country == "JP":
        towns = addr_data.get("towns", ["本町"])
        town = str(rng.choice(towns))
        chome = int(rng.integers(1, 6))
        banchi = int(rng.integers(1, 30))
        go = int(rng.integers(1, 15))
        line = f"{town}{chome}丁目{banchi}-{go}"
        if rng.random() < addr_data.get("apartment_probability", 0.6):
            apt_names = addr_data.get("apartment_names", ["マンション"])
            apt = str(rng.choice(apt_names))
            room = int(rng.integers(101, 1205))
            line += f" {apt}{room}"
    else:
        streets = addr_data.get("street_names", ["Main St"])
        street = str(rng.choice(streets))
        num = int(rng.integers(1, 500))
        line = f"{num} {street}"
        if rng.random() < addr_data.get("apartment_probability", 0.35):
            apt_num = int(rng.integers(1, 13))
            line += f", Apt {apt_num}"

    return {"postal_code": postal_code, "state": state, "city": city, "line": line}


def _generate_phone(addr_data: dict, phone_type: str, rng: np.random.Generator) -> str:
    """Generate a phone number from locale phone patterns."""
    phone_cfg = addr_data.get("phone", {})
    country = addr_data.get("country", "US")

    if country == "JP":
        if phone_type == "mobile":
            prefixes = phone_cfg.get("mobile_prefix", ["090"])
            prefix = str(rng.choice(prefixes))
            mid = f"{int(rng.integers(1000, 9999)):04d}"
            last = f"{int(rng.integers(1000, 9999)):04d}"
            return f"{prefix}-{mid}-{last}"
        else:
            areas = phone_cfg.get("area_codes_landline", ["03"])
            area = str(rng.choice(areas))
            if area == "03":
                exchange = f"{int(rng.integers(1000, 9999)):04d}"
                number = f"{int(rng.integers(1000, 9999)):04d}"
                return f"{area}-{exchange}-{number}"
            else:
                exchange = f"{int(rng.integers(100, 999)):03d}"
                number = f"{int(rng.integers(1000, 9999)):04d}"
                return f"{area}-{exchange}-{number}"
    else:
        if phone_type == "mobile":
            areas = phone_cfg.get("mobile_prefix", ["617"])
        else:
            areas = phone_cfg.get("area_codes", ["617"])
        area = str(rng.choice(areas))
        exchange = f"{int(rng.integers(200, 999)):03d}"
        number = f"{int(rng.integers(1000, 9999)):04d}"
        return f"({area}) {exchange}-{number}"
