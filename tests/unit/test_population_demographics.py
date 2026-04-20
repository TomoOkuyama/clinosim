"""Unit tests for externalized population demographics."""

import numpy as np
import pytest
from datetime import date

from clinosim.modules.population.engine import PersonRecord, generate_population
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
