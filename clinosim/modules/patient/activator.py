"""Patient activator — Layer 1 → Layer 2 conversion.

Converts a lightweight PersonRecord (population registry) into a full PatientProfile
with physiological parameters, baseline vitals, and detailed medical history.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from clinosim.modules.population.engine import PersonRecord, _sample_given_name
from clinosim.locale.loader import load_names
from clinosim.types.patient import (
    Allergy,
    BaselineVitals,
    ChronicCondition,
    PatientPhysiologicalProfile,
    PersonName,
    PatientProfile,
)

def _generate_stage(code: str, severity: str, rng: np.random.Generator) -> str:
    """Generate clinical staging text for a chronic condition by ICD code."""
    base = code.split(".")[0]
    if base == "N18":  # CKD
        # Distribute G1-G5 with most patients in G2-G3
        stages = ["G1", "G2", "G3a", "G3b", "G4", "G5"]
        weights = [0.05, 0.30, 0.30, 0.20, 0.10, 0.05]
        return f"CKD {str(rng.choice(stages, p=weights))}"
    if base == "I50":  # Heart failure
        nyha = ["I", "II", "III", "IV"]
        if severity == "mild":
            weights = [0.30, 0.50, 0.15, 0.05]
        else:
            weights = [0.10, 0.30, 0.40, 0.20]
        return f"NYHA {str(rng.choice(nyha, p=weights))}"
    if base in ("E11", "E10"):  # Diabetes
        if severity == "mild":
            hba1c = float(rng.uniform(6.5, 7.5))
        else:
            hba1c = float(rng.uniform(7.5, 9.5))
        return f"HbA1c {hba1c:.1f}%"
    if base == "J44":  # COPD (GOLD)
        gold = ["GOLD 1", "GOLD 2", "GOLD 3", "GOLD 4"]
        weights = [0.20, 0.40, 0.30, 0.10]
        return str(rng.choice(gold, p=weights))
    if base == "J45":  # Asthma
        levels = ["Mild intermittent", "Mild persistent", "Moderate persistent", "Severe persistent"]
        weights = [0.30, 0.35, 0.25, 0.10]
        return str(rng.choice(levels, p=weights))
    if base == "I10":  # Hypertension
        return f"Stage {str(rng.choice(['1', '2'], p=[0.6, 0.4]))}"
    if base == "I25":  # Ischemic heart disease (CCS class)
        return f"CCS {str(rng.choice(['I', 'II', 'III'], p=[0.4, 0.4, 0.2]))}"
    return ""


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


def _sample_insurance(demo: dict, age: int, rng: np.random.Generator) -> str:
    """Sample insurance type from insurance_distribution age bands."""
    bands = demo.get("insurance_distribution") or []
    for band in bands:
        lo_str, hi_str = str(band.get("age_range", "0-99")).split("-")
        if int(lo_str) <= age <= int(hi_str):
            weights_dict = band.get("weights") or {}
            if weights_dict:
                keys = list(weights_dict.keys())
                probs = np.array([weights_dict[k] for k in keys], dtype=float)
                probs /= probs.sum()
                return str(rng.choice(keys, p=probs))
    # Fallback: no matching band
    return ""


def activate_patient(
    person: PersonRecord,
    rng: np.random.Generator,
    demo: dict,
) -> PatientProfile:
    """Convert Layer 1 PersonRecord to Layer 2 PatientProfile."""
    age = person.age
    sex = person.sex

    # Height from physiology section; BMI already set in Layer 1
    phys = demo.get("physiology") or {}
    ht_cfg = phys.get("height_cm") or {}
    sex_key = "male" if sex == "M" else "female"
    ht_mean = (ht_cfg.get(sex_key) or {}).get("mean", 170.0 if sex == "M" else 157.5)
    ht_std  = (ht_cfg.get(sex_key) or {}).get("std", 5.5)
    shrink  = ht_cfg.get("shrinkage_per_decade_after_60", 0.5)
    height  = float(rng.normal(ht_mean, ht_std))
    if age > 60:
        height -= (age - 60) / 10 * shrink
    bmi    = person.bmi
    weight = bmi * (height / 100) ** 2

    # Derive country from demo (for name formatting, language, etc.)
    country = demo.get("_country", "JP") if isinstance(demo, dict) else "JP"

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
        # Random onset year (1-15 yrs ago) and random month/day
        onset_year = max(1950, 2024 - int(rng.integers(1, 15)))
        onset_month = int(rng.integers(1, 13))
        onset_day = int(rng.integers(1, 29))
        sev = "mild" if rng.random() < 0.6 else "moderate"
        # Stage by ICD code
        stage = _generate_stage(code, sev, rng)
        conditions.append(ChronicCondition(
            code=code,
            system="icd-10-cm",
            onset_date=date(onset_year, onset_month, onset_day),
            severity=sev,
            controlled=rng.random() < 0.7,
            severity_score=float(rng.uniform(0.1, 0.4)),
            stage=stage,
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

    # Current medications: from Layer 1 (prior visit discharge) + chronic conditions
    current_meds = [m for m in (person.current_medications if hasattr(person, "current_medications") else []) if m]
    if not current_meds:
        # Derive home medications from chronic conditions via chronic_medications.yaml
        # CIF stores English drug names (AD-30). JP names resolved at FHIR output.
        current_meds = _derive_home_medications(conditions, rng, country="US")

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

    # Emergency contact: typically spouse for married, or child/sibling for elderly
    emergency_name = ""
    emergency_phone = ""
    emergency_rel = ""
    if age >= 18:
        # Reuse home phone as a household contact for spouse/family
        emergency_phone = phone_home or phone_mobile
        if age >= 75:
            emergency_rel = str(rng.choice(["child", "spouse", "sibling"], p=[0.6, 0.25, 0.15]))
        else:
            emergency_rel = str(rng.choice(["spouse", "parent", "sibling", "child"],
                                            p=[0.55, 0.20, 0.15, 0.10]))
        # Generate a realistic person name for the emergency contact.
        # Spouse/sibling/parent/child typically shares family name (Japan);
        # opposite sex for spouse, random for others.
        try:
            name_data = load_names(country)
            if emergency_rel == "spouse":
                contact_sex = "F" if person.sex == "M" else "M"
            else:
                contact_sex = str(rng.choice(["M", "F"]))
            given = _sample_given_name(name_data, contact_sex, rng)
            # JP uses 'kanji' key, US uses 'name' key
            given_name = given.get("kanji") or given.get("name", "")
            if not given_name:
                raise ValueError("empty given name")
            if country == "JP":
                emergency_name = f"{name.family_name} {given_name}"
            else:
                emergency_name = f"{given_name} {name.family_name}"
        except Exception:
            # Fallback if name data unavailable
            emergency_name = f"{name.family_name} family" if country == "US" else f"{name.family_name}家"

    contact = ContactInfo(
        phone_home=phone_home,
        phone_mobile=phone_mobile,
        phone_primary=phone_mobile if phone_mobile else phone_home,
        emergency_contact_name=emergency_name,
        emergency_contact_phone=emergency_phone,
        emergency_contact_relationship=emergency_rel,
    )

    # Marital status (HL7 v3-MaritalStatus codes)
    if age < 18:
        marital_status = "S"  # Never married
    elif age < 30:
        marital_status = str(rng.choice(["S", "M"], p=[0.65, 0.35]))
    elif age < 50:
        marital_status = str(rng.choice(["S", "M", "D"], p=[0.20, 0.70, 0.10]))
    elif age < 70:
        marital_status = str(rng.choice(["M", "D", "W", "S"], p=[0.65, 0.15, 0.10, 0.10]))
    else:
        marital_status = str(rng.choice(["M", "W", "D", "S"], p=[0.50, 0.35, 0.10, 0.05]))

    # Preferred language (BCP-47)
    preferred_language = "ja-JP" if country == "JP" else "en-US"

    # Insurance type from YAML age bands
    insurance_type = _sample_insurance(demo, age, rng)
    # JP (AD-54): unify the legacy insurance_type with the identity enrollment category
    # (single source of truth), so CSV/insurance_type and FHIR Coverage stay consistent.
    if person.identity is not None:
        enrollment = person.identity.current_enrollment()
        if enrollment is not None and enrollment.category:
            insurance_type = enrollment.category

    # Race and ethnicity (US only; empty string if race_distribution absent)
    race_dist = demo.get("race_distribution") or {}
    if race_dist:
        rk = list(race_dist.keys())
        rp = np.array([race_dist[k] for k in rk], dtype=float)
        rp /= rp.sum()
        race = str(rng.choice(rk, p=rp))
        eth_dist = demo.get("ethnicity_distribution") or {}
        if eth_dist:
            ek = list(eth_dist.keys())
            ep = np.array([eth_dist[k] for k in ek], dtype=float)
            ep /= ep.sum()
            ethnicity = str(rng.choice(ek, p=ep))
        else:
            ethnicity = ""
    else:
        race = ""
        ethnicity = ""

    return PatientProfile(
        patient_id=person.person_id,
        household_id=person.household_id,
        identity=getattr(person, "identity", None),
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
        marital_status=marital_status,
        preferred_language=preferred_language,
        employment_status="retired" if age >= 65 else "employed",
        occupation=getattr(person, "occupation", "other"),
        insurance_type=insurance_type,
        health_literacy=round(float(rng.normal(0.6, 0.15)), 2),
        chronic_conditions=conditions,
        allergies=allergies,
        current_medications=current_meds,
        smoking_status=person.smoking_status,
        alcohol_use=person.alcohol_use,
        physiological_profile=profile,
        baseline_vitals=vitals,
        race=race,
        ethnicity=ethnicity,
    )


def _derive_home_medications(
    chronic_conditions: list, rng: np.random.Generator, country: str = "US"
) -> list[str]:
    """Derive home medications from chronic conditions via chronic_medications.yaml.

    Returns a list of drug name strings. JP uses drug_ja if available.
    """
    from pathlib import Path
    import yaml

    yaml_path = Path(__file__).resolve().parent.parent.parent / "locale" / "shared" / "chronic_medications.yaml"
    if not yaml_path.exists():
        return []
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}

    meds: list[str] = []
    seen: set[str] = set()
    for condition in chronic_conditions:
        code = condition.code if hasattr(condition, "code") else ""
        if not code:
            continue
        # Try exact match, then base code (e.g., E11.9 → E11, N18.3 → N18)
        spec = data.get(code) or data.get(code.split(".")[0])
        if not spec:
            continue
        for drug_spec in spec.get("medications", []):
            name = drug_spec.get("drug", "")
            if country == "JP":
                name = drug_spec.get("drug_ja", name)
            if not name or name in seen:
                continue
            # Respect probability (some drugs are not universally prescribed)
            prob = drug_spec.get("probability", 1.0)
            if prob < 1.0 and rng.random() >= prob:
                continue
            seen.add(name)
            meds.append(name)
    return meds
