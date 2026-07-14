"""Patient activator — Layer 1 → Layer 2 conversion.

Converts a lightweight PersonRecord (population registry) into a full PatientProfile
with physiological parameters, baseline vitals, and detailed medical history.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from clinosim.locale.loader import load_names
from clinosim.modules._shared import is_jp, normalize_probabilities, resolve_lang
from clinosim.modules.physiology.engine import hba1c_from_glycemic_control
from clinosim.modules.population.engine import PersonRecord, _sample_given_name
from clinosim.types.patient import (
    BaselineVitals,
    ChronicCondition,
    PatientPhysiologicalProfile,
    PatientProfile,
    PersonName,
)

# Graded chronic-condition stage text (as returned by _generate_stage) ->
# ChronicCondition.severity_score, keyed by ICD-10-CM category. Consumed by
# physiology/engine.py's per-code branches so a sampled clinical stage (KDIGO
# CKD, NYHA heart failure, GOLD COPD, asthma severity, CCS ischemic heart
# disease) actually drives physiologic severity instead of every condition
# sharing the generic uniform(0.1, 0.4) draw below. Ranges chosen so
# severity-gated branches (CKD's s>0.5, heart failure's s>0.3) trigger only
# for the clinically severe stages (2026-06-20 realism audit finding, CKD;
# extended this session to the other graded-stage conditions with the same
# disconnect).
STAGE_SEVERITY: dict[str, dict[str, float]] = {
    "N18": {"G1": 0.05, "G2": 0.15, "G3a": 0.35, "G3b": 0.50, "G4": 0.70, "G5": 0.90},
    "I50": {"NYHA I": 0.10, "NYHA II": 0.25, "NYHA III": 0.45, "NYHA IV": 0.70},
    "J44": {"GOLD 1": 0.10, "GOLD 2": 0.25, "GOLD 3": 0.45, "GOLD 4": 0.70},
    "J45": {"Mild intermittent": 0.05, "Mild persistent": 0.15,
            "Moderate persistent": 0.35, "Severe persistent": 0.60},
    "I25": {"CCS I": 0.10, "CCS II": 0.25, "CCS III": 0.50},
    # Hypertension: Stage 1 (130-139/80-89) vs Stage 2 (>=140/90). Consumed by the
    # stage-scaled baseline-BP elevation below (FP-I10), making the stage non-degenerate.
    "I10": {"Stage 1": 0.30, "Stage 2": 0.60},
}


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
                probs = normalize_probabilities(
                    [weights_dict[k] for k in keys], fallback="raise"
                )
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
            p=[0.15, 0.65, 0.15, 0.05] if is_jp(country) else [0.07, 0.70, 0.15, 0.08],
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
        # Stage by ICD code. For diabetes (E11/E10) the stage HbA1c, the lab HbA1c, and the
        # Glucose baseline all derive from one continuous glycemic_control axis. We reuse the
        # single float draw that _generate_stage's E11 branch used to consume (now reinterpreted
        # here) so the main RNG stream is unperturbed (AD-16).
        code_base = code.split(".")[0]
        if code_base in ("E11", "E10"):
            gc_draw = float(rng.random())          # replaces the removed E11 stage uniform (1 draw)
            # Cube skews control toward "good" (most diabetics are reasonably controlled):
            # HbA1c median ~6.8%, ~55% < 7%, with a poorly-controlled tail to ~12%.
            glycemic_control = 1.0 - gc_draw ** 3
            stage = f"HbA1c {hba1c_from_glycemic_control(glycemic_control):.1f}%"
        else:
            glycemic_control = None
            stage = _generate_stage(code, sev, rng)
        # Draw both values in the exact same order/position as before this fix
        # (controlled, then the generic severity uniform), then substitute the
        # CKD-stage-derived score for N18 afterward — the uniform draw is
        # still consumed (value discarded) so the RNG stream position for
        # every other condition/patient is unperturbed (AD-16), matching the
        # diabetes gc_draw precedent above.
        controlled_flag = rng.random() < 0.7
        generic_severity_score = float(rng.uniform(0.1, 0.4))
        # Graded-stage conditions derive severity_score from the sampled
        # stage instead of the generic uniform(0.1, 0.4) shared by other
        # chronic conditions. N18's stage text carries a "CKD " display
        # prefix not part of the KDIGO stage code itself, so it's the one
        # code needing the prefix stripped before the STAGE_SEVERITY lookup.
        severity_score = generic_severity_score
        if code_base in STAGE_SEVERITY:
            lookup_key = stage.removeprefix("CKD ") if code_base == "N18" else stage
            severity_score = STAGE_SEVERITY[code_base][lookup_key]
        conditions.append(ChronicCondition(
            code=code,
            system="icd-10-cm",
            onset_date=date(onset_year, onset_month, onset_day),
            severity=sev,
            controlled=controlled_flag,
            severity_score=severity_score,
            stage=stage,
            glycemic_control=glycemic_control,
        ))

    # Allergies — allergy_enricher (POST_POPULATION, order=10) populates person.allergies
    # before activate_patient is called in production (engine.py run_stage then _activate_cached).
    # For the debug test-encounter CLI path (no enricher), default to empty list.
    person_allergies = getattr(person, "allergies", None)
    if person_allergies is not None:
        allergies = list(person_allergies)  # enricher path — use as-is (incl. empty list)
    else:
        # Enricher did not run (debug test-encounter path); no legacy sampling needed.
        allergies = []

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
    # I10 (hypertension): stage-scaled elevation (FP-I10). severity_score is 0.30
    # (Stage 1) / 0.60 (Stage 2), so Stage 2 raises BP more than Stage 1 — the stage is
    # now a real physiological consumer rather than a no-op. No new rng draw.
    _severity_by_code = {c.code: c.severity_score for c in conditions}
    if "I10" in person.chronic_conditions:
        _i10_sev = _severity_by_code.get("I10", 0.30)
        vitals.systolic_bp += int(round(8 + _i10_sev * 20))
        vitals.diastolic_bp += int(round(4 + _i10_sev * 10))
    if "I48" in person.chronic_conditions:
        vitals.heart_rate += int(rng.integers(5, 20))  # irregularly irregular
    if "J44" in person.chronic_conditions:
        vitals.spo2 = round(min(vitals.spo2, float(rng.normal(94, 1.5))), 1)
    if "J45" in person.chronic_conditions:
        vitals.respiratory_rate += int(rng.integers(0, 3))
    if "E03" in person.chronic_conditions:
        vitals.heart_rate -= int(rng.integers(3, 8))  # bradycardia tendency

    # Build PersonName from Layer 1 data
    if is_jp(country):
        display = f"{person.family_name} {person.given_name}"
    else:
        display = f"{person.given_name} {person.family_name}"

    name = PersonName(
        family_name=person.family_name,
        given_name=person.given_name,
        display_name=display,
        name_script=resolve_lang(country),
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
            if is_jp(country):
                emergency_name = f"{name.family_name} {given_name}"
            else:
                emergency_name = f"{given_name} {name.family_name}"
        except Exception:
            # Fallback if name data unavailable. Gate on is_jp (matching the main
            # path above) — a raw country == "US" would give a lowercase "us"
            # patient the Japanese "家" suffix (FP-UNIFY-4 sibling class).
            emergency_name = f"{name.family_name}家" if is_jp(country) else f"{name.family_name} family"

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
    preferred_language = "ja-JP" if is_jp(country) else "en-US"

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
        rp = normalize_probabilities([race_dist[k] for k in rk], fallback="raise")
        race = str(rng.choice(rk, p=rp))
        eth_dist = demo.get("ethnicity_distribution") or {}
        if eth_dist:
            ek = list(eth_dist.keys())
            ep = normalize_probabilities([eth_dist[k] for k in ek], fallback="raise")
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
    from clinosim.locale.loader import load_chronic_medications

    data = load_chronic_medications()

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
            if is_jp(country):
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
