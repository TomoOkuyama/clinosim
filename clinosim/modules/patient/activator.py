"""Patient activator — Layer 1 → Layer 2 conversion.

Converts a lightweight PersonRecord (population registry) into a full PatientProfile
with physiological parameters, baseline vitals, and detailed medical history.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from clinosim.modules.population.engine import PersonRecord
from clinosim.types.patient import (
    Allergy,
    BaselineVitals,
    ChronicCondition,
    PatientPhysiologicalProfile,
    PersonName,
    PatientProfile,
)

CONDITION_NAMES = {
    "I10": "Essential hypertension",
    "E11.9": "Type 2 diabetes mellitus",
    "E78": "Dyslipidemia",
    "J44": "COPD",
    "N18": "Chronic kidney disease",
    "I50": "Heart failure",
    "I48": "Atrial fibrillation",
    "I25": "Ischemic heart disease",
    "M81": "Osteoporosis",
    "F00": "Dementia",
    "G20": "Parkinson's disease",
    "E03": "Hypothyroidism",
    "K21": "GERD",
    "J45": "Asthma",
    "N40": "Benign prostatic hyperplasia",
    "M17": "Osteoarthritis",
    "I63": "Cerebral infarction",
    "I21": "Acute myocardial infarction",
    "K92": "Gastrointestinal hemorrhage",
    "K25": "Gastric ulcer",
    "K26": "Duodenal ulcer",
    "E10": "Type 1 diabetes mellitus",
    "R65": "Sepsis/SIRS",
    "A41": "Sepsis",
    "K56": "Intestinal obstruction",
    "K85": "Acute pancreatitis",
    "K35": "Acute appendicitis",
    "I26": "Pulmonary embolism",
    "K81": "Acute cholecystitis",
    "K80": "Cholelithiasis",
    "L03": "Cellulitis",
    "N17": "Acute kidney injury",
    "K74": "Cirrhosis of liver",
    "K70": "Alcoholic liver disease",
    "J69": "Aspiration pneumonia",
    "J10": "Influenza",
    "J11": "Influenza",
    "J45": "Asthma",
    "I61": "Intracerebral hemorrhage",
    "M80": "Osteoporotic fracture",
    "M48": "Vertebral collapse",
    "I80": "Deep vein thrombosis",
    "I82": "Venous thromboembolism",
    "T07": "Multiple injuries",
    "S52": "Forearm fracture",
    "S06": "Intracranial injury",
    "S22": "Rib fracture",
}


def activate_patient(
    person: PersonRecord,
    rng: np.random.Generator,
    country: str = "JP",
) -> PatientProfile:
    """Convert Layer 1 PersonRecord to Layer 2 PatientProfile."""
    age = person.age
    sex = person.sex

    # Body metrics
    if country == "JP":
        height = float(rng.normal(170.0 if sex == "M" else 157.5, 5.5))
        bmi = float(rng.normal(23.5 if sex == "M" else 22.0, 3.5))
    else:
        height = float(rng.normal(175.5 if sex == "M" else 162.0, 7.0))
        bmi = float(rng.normal(29.0 if sex == "M" else 29.5, 6.0))
    if age > 60:
        height -= (age - 60) / 10 * 0.5
    bmi = max(15.0, min(45.0, bmi))
    weight = bmi * (height / 100) ** 2

    # Physiological profile
    age_penalty = max(0, (age - 40) * 0.005)
    profile = PatientPhysiologicalProfile(
        immune_reactivity=float(rng.beta(5, 5)),
        drug_metabolism_rate=str(rng.choice(
            ["poor", "normal", "rapid", "ultra_rapid"],
            p=[0.15, 0.65, 0.15, 0.05] if country == "JP" else [0.07, 0.70, 0.15, 0.08],
        )),
        renal_reserve=max(0.1, float(rng.beta(8, 2)) - age_penalty),
        cardiac_reserve=max(0.1, float(rng.beta(8, 2)) - age_penalty),
        hepatic_reserve=max(0.1, float(rng.beta(8, 2)) - age_penalty * 0.7),
        treatment_sensitivity=float(rng.normal(1.0, 0.15)),
        symptom_reporting_bias=float(rng.normal(1.0, 0.25)),
        delirium_susceptibility=float(rng.beta(2, 8)) + (0.15 if age >= 75 else 0)
            + (0.25 if "F00" in person.chronic_conditions else 0)
            + (0.10 if "G20" in person.chronic_conditions else 0),
        dvt_susceptibility=float(rng.beta(2, 8)) + (0.10 if age >= 70 else 0),
    )

    # Chronic conditions (expand from ICD codes)
    conditions = []
    for code in person.chronic_conditions:
        conditions.append(ChronicCondition(
            code=code,
            name=CONDITION_NAMES.get(code, code),
            onset_date=date(max(1950, 2024 - int(rng.integers(1, 15))), 1, 1),
            severity="mild" if rng.random() < 0.6 else "moderate",
            controlled=rng.random() < 0.7,
            severity_score=float(rng.uniform(0.1, 0.4)),
        ))

    # Allergies (~15% have at least one)
    allergies = []
    if rng.random() < 0.15:
        allergies.append(Allergy(
            substance=str(rng.choice(["Penicillin", "Sulfonamide", "NSAIDs", "Cephalosporin"])),
            reaction_type="rash",
            severity="mild",
        ))

    # Baseline vitals
    hr_base = 72 if sex == "M" else 78
    sbp_base = 110 + max(0, (age - 30)) * 0.5
    vitals = BaselineVitals(
        temperature=round(float(rng.normal(36.4, 0.2)), 1),
        heart_rate=int(rng.normal(hr_base, 8)),
        systolic_bp=int(rng.normal(sbp_base, 10)),
        diastolic_bp=int(rng.normal(70 + max(0, (age - 30)) * 0.2, 7)),
        respiratory_rate=int(rng.normal(16, 2)),
        spo2=round(float(min(99, rng.normal(97.5, 1.0))), 1),
    )

    # Chronic condition adjustments to baseline vitals
    if "I10" in person.chronic_conditions:
        vitals.systolic_bp += 10
        vitals.diastolic_bp += 5
    if "I48" in person.chronic_conditions:
        vitals.heart_rate += int(rng.integers(5, 20))  # irregularly irregular
    if "J44" in person.chronic_conditions:
        vitals.spo2 = round(min(vitals.spo2, float(rng.normal(94, 1.5))), 1)
    if "J45" in person.chronic_conditions:
        vitals.respiratory_rate += int(rng.integers(0, 3))
    if "E03" in person.chronic_conditions:
        vitals.heart_rate -= int(rng.integers(3, 8))  # bradycardia tendency

    # Build PersonName from Layer 1 data
    if country == "JP":
        display = f"{person.family_name} {person.given_name}"
    else:
        display = f"{person.given_name} {person.family_name}"

    name = PersonName(
        family_name=person.family_name,
        given_name=person.given_name,
        display_name=display,
        name_script="ja" if country == "JP" else "en",
        phonetic=person.phonetic,
    )

    # Current medications from Layer 1 (discharge prescriptions from prior visits)
    current_meds = list(person.current_medications) if hasattr(person, "current_medications") else []

    # Address and contact from Layer 1
    from clinosim.types.patient import Address, ContactInfo
    address = Address(
        postal_code=getattr(person, "postal_code", ""),
        state=getattr(person, "state", ""),
        city=getattr(person, "city", ""),
        line1=getattr(person, "address_line", ""),
        country=country,
    )
    phone_mobile = getattr(person, "phone_mobile", "")
    phone_home = getattr(person, "phone_home", "")
    contact = ContactInfo(
        phone_home=phone_home,
        phone_mobile=phone_mobile,
        phone_primary=phone_mobile if phone_mobile else phone_home,
    )

    return PatientProfile(
        patient_id=person.person_id,
        name=name,
        age=age,
        sex=sex,
        date_of_birth=person.date_of_birth,
        blood_type=person.blood_type,
        rh_factor="+",
        height_cm=round(height, 1),
        weight_kg=round(weight, 1),
        bmi=round(bmi, 1),
        address=address,
        contact=contact,
        employment_status="retired" if age >= 65 else "employed",
        insurance_type="late_elderly" if age >= 75 else "NHI_employee",
        health_literacy=round(float(rng.normal(0.6, 0.15)), 2),
        chronic_conditions=conditions,
        allergies=allergies,
        current_medications=current_meds,
        smoking_status=str(rng.choice(["never", "former", "current"], p=[0.55, 0.30, 0.15])),
        alcohol_use=str(rng.choice(["none", "social", "heavy"], p=[0.60, 0.30, 0.10])),
        physiological_profile=profile,
        baseline_vitals=vitals,
    )
