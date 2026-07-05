"""Unit tests for externalized population demographics."""

import numpy as np
import pytest
from datetime import date

from clinosim.modules.population.engine import PersonRecord, generate_population, generate_monthly_events, PopulationRegistry
from clinosim.types.patient import PatientProfile


def test_person_record_has_lifestyle_fields():
    """PersonRecord must carry bmi, smoking_status, alcohol_use for Layer-1 risk use."""
    p = PersonRecord(person_id="POP-001", household_id="HH-001", age=45, sex="M", date_of_birth=date(1979, 1, 1))
    assert hasattr(p, "bmi"), "bmi field missing from PersonRecord"
    assert hasattr(p, "smoking_status"), "smoking_status field missing"
    assert hasattr(p, "alcohol_use"), "alcohol_use field missing"
    assert isinstance(p.bmi, float)
    assert p.smoking_status in ("never", "former", "current")
    assert p.alcohol_use in ("none", "social", "heavy")


def test_patient_profile_has_race_ethnicity_fields():
    """PatientProfile must have race and ethnicity fields (empty string default)."""
    p = PatientProfile()
    assert hasattr(p, "race"), "race field missing from PatientProfile"
    assert hasattr(p, "ethnicity"), "ethnicity field missing from PatientProfile"
    assert p.race == ""
    assert p.ethnicity == ""


def _us_demo_minimal() -> dict:
    """Minimal demo dict with new sections for testing."""
    return {
        "average_household_size": 1.0,
        "age_distribution": {"0-99": 1.0},
        "blood_type": {"O": 1.0},
        "chronic_prevalence": {},
        "disease_incidence": {},
        "seasonal_modifiers": {},
        "disease_risk_multipliers": {},
        "unknown_conditions": {"min_age": 100, "base_rate": 0.0, "age_factor": 0.0, "patterns": []},
        "mixed_conditions": {"min_age": 100, "min_chronic_conditions": 99, "probability": 0.0},
        "ed_visit_not_admitted": {"rate_per_admitted": 0.0},
        "occupation_distribution": {
            "age_thresholds": {
                "student_max_age": 14,
                "young_adult_max_age": 21,
                "young_adult_student_prob": 0.70,
                "retirement_min_age": 65,
            },
            "working_age": {"office": 1.0},
        },
        "occupation_risk_multipliers": {},
        "sex_ratio": {"male": 0.50},
        "physiology": {
            "bmi": {"male": {"mean": 29.0, "std": 0.001}, "female": {"mean": 29.5, "std": 0.001}, "clamp": [15.0, 45.0]},
            "height_cm": {"male": {"mean": 175.5, "std": 0.001}, "female": {"mean": 162.0, "std": 0.001}, "shrinkage_per_decade_after_60": 0.5},
        },
        "lifestyle_distribution": {
            "smoking": {
                "male":   {"never": 0.0, "former": 0.0, "current": 1.0},
                "female": {"never": 1.0, "former": 0.0, "current": 0.0},
            },
            "alcohol": {
                "male":   {"none": 1.0, "social": 0.0, "heavy": 0.0},
                "female": {"none": 1.0, "social": 0.0, "heavy": 0.0},
            },
        },
        "lifestyle_risk_multipliers": {},
        "comorbidity_correlations": {},
        "insurance_distribution": [],
        "race_distribution": {},
        "ethnicity_distribution": {},
    }


def test_bmi_generated_from_physiology_yaml():
    """BMI must come from physiology section, not hardcoded values."""
    rng = np.random.default_rng(42)
    demo = _us_demo_minimal()
    # Force std≈0 so BMI is deterministic
    registry = generate_population(size=10, country="US", rng=rng, demo=demo)
    for p in registry.persons.values():
        if p.sex == "M":
            assert abs(p.bmi - 29.0) < 0.5, f"Male BMI {p.bmi} not near 29.0"
        else:
            assert abs(p.bmi - 29.5) < 0.5, f"Female BMI {p.bmi} not near 29.5"


def test_smoking_status_sex_differentiated():
    """Smoking status must use sex-specific distribution from YAML."""
    rng = np.random.default_rng(42)
    demo = _us_demo_minimal()
    # males forced to current, females forced to never
    registry = generate_population(size=100, country="US", rng=rng, demo=demo)
    for p in registry.persons.values():
        if p.sex == "M":
            assert p.smoking_status == "current", f"Male should be current smoker per demo"
        else:
            assert p.smoking_status == "never", f"Female should be never-smoker per demo"


def test_comorbidity_correlation_raises_prevalence():
    """When I10 is present, E11.9 prevalence should be boosted by comorbidity_correlations."""
    # Force I10 to always trigger, E11.9 just below threshold without correlation
    demo = _us_demo_minimal()
    demo["chronic_prevalence"] = {
        "I10":   {"40-99": 1.0},   # always present for age 40+
        "E11.9": {"40-99": 0.01},  # too low to trigger without boost
    }
    demo["comorbidity_correlations"] = {"I10": {"E11.9": 200.0}}  # 200x boost → should always trigger
    rng = np.random.default_rng(42)
    registry = generate_population(size=200, country="US", rng=rng, demo=demo)
    adults = [p for p in registry.persons.values() if 40 <= p.age <= 99]
    assert len(adults) > 0
    # All adults have I10; with 200x boost, E11.9 should appear in almost all
    e11_count = sum(1 for p in adults if "E11.9" in p.chronic_conditions)
    assert e11_count / len(adults) > 0.95, \
        f"Expected >95% E11.9 with 200x boost, got {e11_count}/{len(adults)}"


def test_lifestyle_risk_multiplier_raises_chronic_prevalence():
    """Obese patients (BMI≥30) should have higher E11.9 prevalence than non-obese."""
    demo = _us_demo_minimal()
    demo["chronic_prevalence"] = {"E11.9": {"0-99": 0.10}}
    demo["lifestyle_risk_multipliers"] = {
        "bmi": {
            "thresholds": {"overweight": 25.0, "obese": 30.0},
            "obese": {"E11.9": 7.0},
            "overweight": {},
        },
        "smoking": {},
    }
    # Force all patients to be obese (BMI mean=35, std≈0)
    demo["physiology"]["bmi"]["male"]   = {"mean": 35.0, "std": 0.001}
    demo["physiology"]["bmi"]["female"] = {"mean": 35.0, "std": 0.001}

    rng_obese = np.random.default_rng(42)
    registry_obese = generate_population(size=500, country="US", rng=rng_obese, demo=demo)

    # Force all patients to be non-obese (BMI mean=22, std≈0)
    demo2 = _us_demo_minimal()
    demo2["chronic_prevalence"] = {"E11.9": {"0-99": 0.10}}
    demo2["lifestyle_risk_multipliers"] = demo["lifestyle_risk_multipliers"]
    demo2["physiology"]["bmi"]["male"]   = {"mean": 22.0, "std": 0.001}
    demo2["physiology"]["bmi"]["female"] = {"mean": 22.0, "std": 0.001}

    rng_thin = np.random.default_rng(42)
    registry_thin = generate_population(size=500, country="US", rng=rng_thin, demo=demo2)

    obese_rate = sum(1 for p in registry_obese.persons.values() if "E11.9" in p.chronic_conditions) / 500
    thin_rate  = sum(1 for p in registry_thin.persons.values() if "E11.9" in p.chronic_conditions) / 500
    assert obese_rate > thin_rate * 2, \
        f"Obese E11.9 rate {obese_rate:.2f} should be >2x thin rate {thin_rate:.2f}"


def _make_registry_with_person(age: int, sex: str, smoking: str, bmi: float) -> PopulationRegistry:
    r = PopulationRegistry()
    p = PersonRecord(
        person_id="POP-000001",
        household_id="HH-001",
        age=age,
        sex=sex,
        date_of_birth=date(2024 - age, 1, 1),
        smoking_status=smoking,
        bmi=bmi,
        chronic_conditions=[],
    )
    r.persons["POP-000001"] = p
    return r


def test_lifestyle_risk_multiplier_increases_monthly_event_rate():
    """Current smoker should have higher acute_mi event rate than never-smoker."""
    demo = _us_demo_minimal()
    demo["disease_incidence"] = {
        "acute_mi": {
            "age_rates": {0: 0, 45: 500000},  # very high base rate so events appear in small sample
            "sex_ratio_female": 0.55,
            "event_type": "acute_disease_onset",
            "severity_beta": [3, 3],
            "severity_minimum": 0.3,
            "always_hospitalize": True,
        }
    }
    demo["lifestyle_risk_multipliers"] = {
        "smoking": {"current": {"acute_mi": 10.0}, "former": {}},
        "bmi": {"thresholds": {"overweight": 25.0, "obese": 30.0}, "overweight": {}, "obese": {}},
    }

    smoker_events = 0
    nonsmoker_events = 0
    trials = 50

    for seed in range(trials):
        reg_s = _make_registry_with_person(55, "M", "current", 24.0)
        events_s = generate_monthly_events(reg_s, 2024, 1, np.random.default_rng(seed), demo=demo)
        smoker_events += len(events_s)

        reg_n = _make_registry_with_person(55, "M", "never", 24.0)
        events_n = generate_monthly_events(reg_n, 2024, 1, np.random.default_rng(seed), demo=demo)
        nonsmoker_events += len(events_n)

    assert smoker_events > nonsmoker_events, \
        f"Smoker events {smoker_events} should exceed non-smoker {nonsmoker_events}"


def test_occupation_age_thresholds_from_yaml():
    """Occupation thresholds must be read from occupation_distribution.age_thresholds."""
    rng = np.random.default_rng(42)
    demo = _us_demo_minimal()
    # Set retirement at 60 instead of default 65
    demo["occupation_distribution"]["age_thresholds"]["retirement_min_age"] = 60
    registry = generate_population(size=200, country="US", rng=rng, demo=demo)
    for p in registry.persons.values():
        if p.age >= 60:
            assert p.occupation == "retired", f"Age {p.age} should be retired (threshold=60)"


# ---------------------------------------------------------------------------
# Task 7: activate_patient() tests
# ---------------------------------------------------------------------------

from clinosim.modules.patient.activator import activate_patient


def _make_person(age: int = 45, sex: str = "M", bmi: float = 28.0,
                 smoking: str = "never", alcohol: str = "none") -> PersonRecord:
    return PersonRecord(
        person_id="POP-TEST",
        household_id="HH-TEST",
        age=age,
        sex=sex,
        date_of_birth=date(2024 - age, 1, 1),
        bmi=bmi,
        smoking_status=smoking,
        alcohol_use=alcohol,
    )


def _minimal_demo_for_activate(country_hint: str = "US") -> dict:
    return {
        "_country": country_hint,
        "physiology": {
            "bmi": {"male": {"mean": 29.0, "std": 6.0}, "female": {"mean": 29.5, "std": 6.0}, "clamp": [15.0, 45.0]},
            "height_cm": {"male": {"mean": 175.5, "std": 7.0}, "female": {"mean": 162.0, "std": 7.0}, "shrinkage_per_decade_after_60": 0.5},
        },
        "insurance_distribution": [
            {"age_range": "0-64", "weights": {"private": 1.0}},
            {"age_range": "65-99", "weights": {"medicare": 1.0}},
        ],
        "race_distribution": {"white": 0.6, "black": 0.4},
        "ethnicity_distribution": {"hispanic": 0.2, "not_hispanic": 0.8},
    }


def test_activate_patient_uses_person_bmi_not_regenerate():
    """BMI in PatientProfile must equal person.bmi, not be regenerated."""
    person = _make_person(bmi=33.7)
    rng = np.random.default_rng(0)
    demo = _minimal_demo_for_activate()
    profile = activate_patient(person, rng, demo)
    assert abs(profile.bmi - 33.7) < 0.01, \
        f"PatientProfile.bmi {profile.bmi} should match PersonRecord.bmi 33.7"


def test_activate_patient_uses_person_smoking():
    """smoking_status in PatientProfile must come from PersonRecord."""
    person = _make_person(smoking="current")
    rng = np.random.default_rng(0)
    demo = _minimal_demo_for_activate()
    profile = activate_patient(person, rng, demo)
    assert profile.smoking_status == "current"


def test_activate_patient_insurance_from_yaml():
    """Insurance type should come from insurance_distribution in demo."""
    person_young = _make_person(age=30)
    person_old   = _make_person(age=70)
    rng = np.random.default_rng(0)
    demo = _minimal_demo_for_activate()
    profile_young = activate_patient(person_young, rng, demo)
    profile_old   = activate_patient(person_old,   rng, demo)
    assert profile_young.insurance_type == "private"
    assert profile_old.insurance_type   == "medicare"


def test_activate_patient_race_from_yaml():
    """race and ethnicity must be sampled from demo when race_distribution present."""
    person = _make_person()
    rng = np.random.default_rng(0)
    demo = _minimal_demo_for_activate()
    profile = activate_patient(person, rng, demo)
    assert profile.race in ("white", "black"), f"Unexpected race: {profile.race}"
    assert profile.ethnicity in ("hispanic", "not_hispanic")


def test_activate_patient_no_race_when_missing_from_demo():
    """race and ethnicity should be empty string when race_distribution absent (JP)."""
    person = _make_person()
    rng = np.random.default_rng(0)
    demo = {}  # no race_distribution
    profile = activate_patient(person, rng, demo)
    assert profile.race == ""
    assert profile.ethnicity == ""


# ---------------------------------------------------------------------------
# Task 9: integration smoke test using real us/demographics.yaml
# ---------------------------------------------------------------------------

from clinosim.locale.loader import load_demographics as _load_demo


def test_us_population_bmi_distribution_matches_yaml():
    """End-to-end: generated US population BMI must be within 2 std of YAML mean."""
    demo = _load_demo("US")
    rng = np.random.default_rng(42)
    registry = generate_population(size=500, country="US", rng=rng, demo=demo)
    males   = [p.bmi for p in registry.persons.values() if p.sex == "M"]
    females = [p.bmi for p in registry.persons.values() if p.sex == "F"]
    assert males,   "No male persons generated"
    assert females, "No female persons generated"
    m_cfg = demo["physiology"]["bmi"]["male"]
    f_cfg = demo["physiology"]["bmi"]["female"]
    assert abs(np.mean(males)   - m_cfg["mean"]) < m_cfg["std"] * 2, \
        f"Male BMI mean {np.mean(males):.1f} not within 2 std of {m_cfg['mean']}"
    assert abs(np.mean(females) - f_cfg["mean"]) < f_cfg["std"] * 2, \
        f"Female BMI mean {np.mean(females):.1f} not within 2 std of {f_cfg['mean']}"


# ---------------------------------------------------------------------------
# Glycemic control axis (DET-6): E11 stage HbA1c must match glycemic_control,
# and sampling must be deterministic + stream-preserving.
# ---------------------------------------------------------------------------

def _make_diabetic_person(age: int = 60) -> PersonRecord:
    p = _make_person(age=age)
    p.chronic_conditions = ["E11.9"]
    return p


def test_e11_stage_hba1c_matches_glycemic_control():
    from clinosim.modules.physiology.engine import hba1c_from_glycemic_control
    person = _make_diabetic_person()
    profile = activate_patient(person, np.random.default_rng(7), _minimal_demo_for_activate())
    dm = next(c for c in profile.chronic_conditions if c.code.startswith("E11"))
    assert dm.glycemic_control is not None
    assert 0.0 <= dm.glycemic_control <= 1.0
    expected = f"HbA1c {hba1c_from_glycemic_control(dm.glycemic_control):.1f}%"
    assert dm.stage == expected


def test_glycemic_control_deterministic_same_seed():
    person1 = _make_diabetic_person()
    person2 = _make_diabetic_person()
    demo = _minimal_demo_for_activate()
    p1 = activate_patient(person1, np.random.default_rng(123), demo)
    p2 = activate_patient(person2, np.random.default_rng(123), demo)
    gc1 = next(c for c in p1.chronic_conditions if c.code.startswith("E11")).glycemic_control
    gc2 = next(c for c in p2.chronic_conditions if c.code.startswith("E11")).glycemic_control
    assert gc1 == gc2


def test_nondiabetic_condition_has_no_glycemic_control():
    person = _make_person(age=60)
    person.chronic_conditions = ["I10"]
    profile = activate_patient(person, np.random.default_rng(7), _minimal_demo_for_activate())
    ht = next(c for c in profile.chronic_conditions if c.code.startswith("I10"))
    assert ht.glycemic_control is None


# ---------------------------------------------------------------------------
# gi_bleeding always_hospitalize: the gi_bleeding disease protocol assumes
# universal admission (NPO + endoscopy workup), so its incidence config must
# gate every incident case into the hospitalized cohort like the other acute
# disease-onset conditions (acute_mi, cerebral_infarction, sepsis, ...).
# Without this flag, population/engine.py:373 only hospitalizes cases whose
# sampled severity exceeds the person's care-seeking threshold — silently
# dropping ~35% of incident GI bleeds from the generated catchment.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("country", ["US", "JP"])
def test_gi_bleeding_always_hospitalizes(country):
    demo = _load_demo(country)
    assert demo["disease_incidence"]["gi_bleeding"].get("always_hospitalize") is True, (
        f"{country} gi_bleeding incidence config missing always_hospitalize: true"
    )


# influenza.yaml and asthma_exacerbation.yaml both state their incidence rates
# are "Hospitalized [cases] only" (not all infections/exacerbations) — the
# same disconnect class as gi_bleeding: the rate is pre-filtered to the
# hospitalized population, but the config lacked the flag that actually
# routes every sampled event into the hospitalized cohort.
@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("disease", ["influenza", "asthma_exacerbation"])
def test_hospitalized_only_diseases_always_hospitalize(country, disease):
    demo = _load_demo(country)
    assert demo["disease_incidence"][disease].get("always_hospitalize") is True, (
        f"{country} {disease} incidence config missing always_hospitalize: true"
    )


# ---------------------------------------------------------------------------
# CKD severity_score must track the sampled G1-G5 stage (same "reuse the
# existing draw, reinterpret" pattern as the diabetes glycemic_control axis
# above), not the flat uniform(0.1, 0.4) draw shared by other chronic
# conditions. Otherwise physiology/engine.py's severity>0.5 anemia/acidosis
# branch is dead code and CKD creatinine never spreads past G3-equivalent
# (2026-06-20 realism audit finding).
# ---------------------------------------------------------------------------

from clinosim.modules.patient.activator import CKD_STAGE_SEVERITY


def _make_ckd_person(age: int = 65) -> PersonRecord:
    p = _make_person(age=age)
    p.chronic_conditions = ["N18.3"]
    return p


def test_ckd_severity_score_tracks_sampled_stage():
    demo = _minimal_demo_for_activate()
    seen_severe = False
    for seed in range(100):
        person = _make_ckd_person()
        profile = activate_patient(person, np.random.default_rng(seed), demo)
        ckd = next(c for c in profile.chronic_conditions if c.code.startswith("N18"))
        stage_suffix = ckd.stage.replace("CKD ", "")
        assert stage_suffix in CKD_STAGE_SEVERITY, f"unexpected CKD stage text: {ckd.stage!r}"
        assert ckd.severity_score == CKD_STAGE_SEVERITY[stage_suffix]
        if stage_suffix in ("G4", "G5"):
            seen_severe = True
    assert seen_severe, "no G4/G5 CKD patient sampled in 100 seeds — check stage weights"


def test_ckd_severity_score_deterministic_same_seed():
    demo = _minimal_demo_for_activate()
    p1 = activate_patient(_make_ckd_person(), np.random.default_rng(55), demo)
    p2 = activate_patient(_make_ckd_person(), np.random.default_rng(55), demo)
    s1 = next(c for c in p1.chronic_conditions if c.code.startswith("N18")).severity_score
    s2 = next(c for c in p2.chronic_conditions if c.code.startswith("N18")).severity_score
    assert s1 == s2
