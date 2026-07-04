"""Hardcoded test patient for v0.1-alpha. Bypasses population module."""

from __future__ import annotations

from datetime import date

from clinosim.types.allergy import Allergy, AllergyReaction
from clinosim.types.patient import (
    BaselineVitals,
    ChronicCondition,
    PatientPhysiologicalProfile,
    PatientProfile,
)


def create_test_patient() -> PatientProfile:
    """Create a 72-year-old Japanese female with HT + DM, presenting with pneumonia.

    This is a realistic 'typical' pneumonia patient in Japan:
    - Elderly female (pneumonia incidence peaks in this demographic)
    - Hypertension + Type 2 diabetes (common comorbidities)
    - On amlodipine + metformin (standard medications)
    - Moderate renal and cardiac reserve (age-adjusted)
    """
    return PatientProfile(
        patient_id="P-ALPHA-001",
        age=72,
        sex="F",
        date_of_birth=date(1952, 3, 15),
        blood_type="A",
        rh_factor="+",
        height_cm=152.0,
        weight_kg=54.0,
        bmi=23.4,
        employment_status="retired",
        insurance_type="late_elderly",  # Japan's late-stage elderly healthcare
        health_literacy=0.6,
        chronic_conditions=[
            ChronicCondition(
                code="I10",
                onset_date=date(2010, 6, 1),
                severity="mild",
                controlled=True,
                severity_score=0.2,
            ),
            ChronicCondition(
                code="E11.9",
                onset_date=date(2015, 9, 1),
                severity="mild",
                controlled=True,
                severity_score=0.2,
            ),
        ],
        allergies=[
            Allergy(
                allergy_id="al-P-ALPHA-001-1",
                allergen_code="303408005",
                category="medication",
                criticality="low",
                verification_status="confirmed",
                reactions=[AllergyReaction(
                    manifestation_snomed="247472004",
                    severity="mild",
                )],
            ),
        ],
        current_medications=["Amlodipine 5mg", "Metformin 500mg BID"],
        smoking_status="never",
        alcohol_use="none",
        physiological_profile=PatientPhysiologicalProfile(
            immune_reactivity=0.55,
            drug_metabolism_rate="normal",
            renal_reserve=0.70,  # age-adjusted: Beta(8,2) - age_penalty
            cardiac_reserve=0.72,
            hepatic_reserve=0.80,
            treatment_sensitivity=1.05,
            symptom_reporting_bias=1.0,
            delirium_susceptibility=0.25,  # elevated for age 72
            dvt_susceptibility=0.20,
        ),
        baseline_vitals=BaselineVitals(
            temperature=36.4,
            heart_rate=76,
            systolic_bp=132,  # controlled HT — slightly above normal
            diastolic_bp=78,
            respiratory_rate=16,
            spo2=97.0,
        ),
    )
