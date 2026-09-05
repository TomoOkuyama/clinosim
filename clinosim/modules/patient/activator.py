"""Patient activator — Layer 1 → Layer 2 conversion.

Converts a lightweight PersonRecord (population registry) into a full PatientProfile
with physiological parameters, baseline vitals, and detailed medical history.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from clinosim.locale.loader import load_names
from clinosim.modules._shared import is_jp, normalize_probabilities, resolve_lang
from clinosim.modules.patient._patient_activator_thresholds import (
    AGE_PENALTY_HEPATIC_RATIO,
    AGE_PENALTY_MIN_AGE,
    AGE_PENALTY_SCALE,
    BASELINE_DBP_AGE_REFERENCE,
    BASELINE_DBP_AGE_SCALE,
    BASELINE_DBP_BASE,
    BASELINE_DBP_SAMPLE_SD,
    BASELINE_HR_BASE_FEMALE,
    BASELINE_HR_BASE_MALE,
    BASELINE_HR_SAMPLE_SD,
    BASELINE_RR_MEAN,
    BASELINE_RR_SD,
    BASELINE_SBP_AGE_REFERENCE,
    BASELINE_SBP_AGE_SCALE,
    BASELINE_SBP_BASE,
    BASELINE_SBP_SAMPLE_SD,
    BASELINE_SPO2_CEILING,
    BASELINE_SPO2_MEAN,
    BASELINE_SPO2_SD,
    BASELINE_TEMPERATURE_MEAN,
    BASELINE_TEMPERATURE_SD,
    CHRONIC_CONTROLLED_PROBABILITY,
    CHRONIC_ONSET_DAY_MAX_EXCLUSIVE,
    CHRONIC_ONSET_DAY_MIN,
    CHRONIC_ONSET_MONTH_MAX_EXCLUSIVE,
    CHRONIC_ONSET_MONTH_MIN,
    CHRONIC_ONSET_YEAR_FLOOR,
    CHRONIC_ONSET_YEAR_MAX_EXCLUSIVE,
    CHRONIC_ONSET_YEAR_MIN,
    CHRONIC_ONSET_YEAR_REFERENCE,
    CHRONIC_SEVERITY_MILD_PROBABILITY,
    DELIRIUM_BETA_PARAMS,
    DELIRIUM_DEMENTIA_PREMIUM,
    DELIRIUM_ELDERLY_AGE_THRESHOLD,
    DELIRIUM_ELDERLY_PREMIUM,
    DELIRIUM_PARKINSON_PREMIUM,
    DRUG_METABOLISM_JP_PROBS,
    DRUG_METABOLISM_LABELS,
    DRUG_METABOLISM_US_PROBS,
    DVT_BETA_PARAMS,
    DVT_ELDERLY_AGE_THRESHOLD,
    DVT_ELDERLY_PREMIUM,
    E03_HR_REDUCTION_MAX_EXCLUSIVE,
    E03_HR_REDUCTION_MIN,
    EMERGENCY_CONTACT_ELDERLY_AGE_MIN,
    EMERGENCY_CONTACT_RELATIONS_ADULT,
    EMERGENCY_CONTACT_RELATIONS_ELDERLY,
    EMERGENCY_CONTACT_WEIGHTS_ADULT,
    EMERGENCY_CONTACT_WEIGHTS_ELDERLY,
    EMPLOYMENT_RETIREMENT_AGE_MIN,
    GENERIC_SEVERITY_UNIFORM_MAX,
    GENERIC_SEVERITY_UNIFORM_MIN,
    HEALTH_LITERACY_MEAN,
    HEALTH_LITERACY_ROUND_DIGITS,
    HEALTH_LITERACY_SD,
    I10_DBP_BASE_LIFT,
    I10_DBP_SEVERITY_SCALE,
    I10_DEFAULT_SEVERITY,
    I10_SBP_BASE_LIFT,
    I10_SBP_SEVERITY_SCALE,
    I48_HR_LIFT_MAX_EXCLUSIVE,
    I48_HR_LIFT_MIN,
    IMMUNE_REACTIVITY_BETA_PARAMS,
    J44_SPO2_LIMIT_MEAN,
    J44_SPO2_LIMIT_SD,
    J45_RR_LIFT_MAX_EXCLUSIVE,
    J45_RR_LIFT_MIN,
    MARITAL_STATUS_ADULT_AGE_MIN,
    MARITAL_STATUS_ELDERLY_CODES,
    MARITAL_STATUS_ELDERLY_WEIGHTS,
    MARITAL_STATUS_LATE_ADULT_AGE_MAX_EXCLUSIVE,
    MARITAL_STATUS_LATE_ADULT_CODES,
    MARITAL_STATUS_LATE_ADULT_WEIGHTS,
    MARITAL_STATUS_MID_ADULT_AGE_MAX_EXCLUSIVE,
    MARITAL_STATUS_MID_ADULT_CODES,
    MARITAL_STATUS_MID_ADULT_WEIGHTS,
    MARITAL_STATUS_MINOR_CODE,
    MARITAL_STATUS_YOUNG_ADULT_AGE_MAX_EXCLUSIVE,
    MARITAL_STATUS_YOUNG_ADULT_CODES,
    MARITAL_STATUS_YOUNG_ADULT_WEIGHTS,
    RESERVE_FLOOR,
    SYMPTOM_REPORTING_BIAS_MEAN,
    SYMPTOM_REPORTING_BIAS_SD,
    TREATMENT_SENSITIVITY_MEAN,
    TREATMENT_SENSITIVITY_SD,
)
from clinosim.modules.patient._severity_activation import (
    I10_STAGE_WEIGHTS,
    I10_STAGES,
    I25_STAGE_WEIGHTS,
    I25_STAGES,
    I50_STAGE_WEIGHTS_DEFAULT,
    I50_STAGE_WEIGHTS_MILD,
    I50_STAGES,
    J44_STAGE_WEIGHTS,
    J44_STAGES,
    J45_STAGE_WEIGHTS,
    J45_STAGES,
    N18_STAGE_WEIGHTS,
    N18_STAGES,
    STAGE_SEVERITY,
)
from clinosim.modules.physiology.engine import hba1c_from_glycemic_control
from clinosim.modules.population.engine import PersonRecord, _sample_given_name
from clinosim.types.patient import (
    BaselineVitals,
    ChronicCondition,
    HomeMedication,
    PatientPhysiologicalProfile,
    PatientProfile,
    PersonName,
)

# Physiological-reserve distribution shared by renal / cardiac / hepatic reserves.
# Issue #416: the legacy (8, 2) placed the healthy-cohort median at ~0.826, which
# combined with the derive_lab_values math pushed healthy young Cre / K / Alb /
# Troponin_I outside JP reference bands. (30, 2) shifts the median to ~0.92,
# lands ≥95% of healthy young inside the bands (measured in
# tests/unit/test_reserve_distribution_healthy_band.py), and is RNG-cursor-
# neutral vs (8, 2) — numpy's Cheng BB algorithm consumes the same number of
# uniforms per beta call for any (a > 1, b = 2). Kept module-level so the unit
# test can pin it and future tweaks stay in one place.
_RESERVE_BETA_PARAMS: tuple[float, float] = (30, 2)


def _generate_stage(code: str, severity: str, rng: np.random.Generator) -> str:
    """Generate clinical staging text for a chronic condition by ICD code.

    Stage lists and selection weights live in
    ``clinosim.modules.patient._severity_activation`` (per Issue #637
    PR-D); this function only owns the per-code branching + display-string
    formatting. The severity-score table ``STAGE_SEVERITY`` used
    downstream is imported and re-exported from the same module.
    """
    base = code.split(".")[0]
    if base == "N18":  # CKD (KDIGO G1-G5)
        return f"CKD {str(rng.choice(N18_STAGES, p=N18_STAGE_WEIGHTS))}"
    if base == "I50":  # Heart failure (NYHA I-IV)
        weights = I50_STAGE_WEIGHTS_MILD if severity == "mild" else I50_STAGE_WEIGHTS_DEFAULT
        return f"NYHA {str(rng.choice(I50_STAGES, p=weights))}"
    if base == "J44":  # COPD (GOLD 1-4)
        return str(rng.choice(J44_STAGES, p=J44_STAGE_WEIGHTS))
    if base == "J45":  # Asthma (NAEPP EPR-3)
        return str(rng.choice(J45_STAGES, p=J45_STAGE_WEIGHTS))
    if base == "I10":  # Hypertension (ACC-AHA 2017 / JNC-8)
        return f"Stage {str(rng.choice(I10_STAGES, p=I10_STAGE_WEIGHTS))}"
    if base == "I25":  # Ischemic heart disease (CCS class)
        return f"CCS {str(rng.choice(I25_STAGES, p=I25_STAGE_WEIGHTS))}"
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
    # lint: "J45": "Asthma" was duplicated (declared earlier in this dict); dropped.
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


_CHRONIC_ONSET_MIN_AGE_PATH = Path(__file__).resolve().parents[2] / "locale" / "shared" / "chronic_onset_min_age.yaml"


@lru_cache(maxsize=1)
def _chronic_onset_min_age_table() -> tuple[dict[str, int], int]:
    """Return (codes_dict, default_min_years) from the shared yaml (Issue #968)."""
    with open(_CHRONIC_ONSET_MIN_AGE_PATH) as f:
        data = yaml.safe_load(f) or {}
    codes = {str(k): int(v) for k, v in (data.get("codes") or {}).items()}
    default = int(data.get("default_min_years", 0))
    return codes, default


def _clamp_chronic_onset(sampled: date, dob: date | None, code: str) -> date:
    """Clamp a sampled chronic-condition onset date so it never precedes
    ``dob + min_onset_years[code]`` (Issue #968).

    - When ``dob`` is unknown, returns ``sampled`` unchanged (activator
      caller guarantees dob is populated for real patients).
    - The floor for a code without a yaml entry is ``dob + 1 day`` (so the
      condition can never share a day with birth itself).
    - Sampled dates after the floor pass through unmodified — the clamp is
      a floor, not a redistribution, to preserve the RNG cascade (adult
      distributions are unchanged; only pediatric edge cases move).
    """
    if dob is None:
        return sampled
    codes, default_years = _chronic_onset_min_age_table()
    min_years = codes.get(code.split(".")[0], default_years)
    # Approximate min_years by 365 * min_years days plus a 1-day floor for
    # the default=0 case so no Condition shares its subject's birth date.
    floor_days = max(1, int(min_years) * 365)
    floor = date.fromordinal(dob.toordinal() + floor_days)
    return floor if sampled < floor else sampled


def _sample_insurance(demo: dict, age: int, rng: np.random.Generator) -> str:
    """Sample insurance type from insurance_distribution age bands."""
    bands = demo.get("insurance_distribution") or []
    for band in bands:
        lo_str, hi_str = str(band.get("age_range", "0-99")).split("-")
        if int(lo_str) <= age <= int(hi_str):
            weights_dict = band.get("weights") or {}
            if weights_dict:
                keys = list(weights_dict.keys())
                probs = normalize_probabilities([weights_dict[k] for k in keys], fallback="raise")
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
    ht_std = (ht_cfg.get(sex_key) or {}).get("std", 5.5)
    shrink = ht_cfg.get("shrinkage_per_decade_after_60", 0.5)
    height = float(rng.normal(ht_mean, ht_std))
    if age > 60:
        height -= (age - 60) / 10 * shrink
    bmi = person.bmi
    weight = bmi * (height / 100) ** 2

    # Derive country from demo (for name formatting, language, etc.)
    # Issue #570 convention: default US when demo lacks _country.
    country = demo.get("_country", "US") if isinstance(demo, dict) else "US"

    # Physiological profile
    age_penalty = max(0, (age - AGE_PENALTY_MIN_AGE) * AGE_PENALTY_SCALE)
    profile = PatientPhysiologicalProfile(
        immune_reactivity=float(rng.beta(*IMMUNE_REACTIVITY_BETA_PARAMS)),
        drug_metabolism_rate=str(
            rng.choice(
                DRUG_METABOLISM_LABELS,
                p=DRUG_METABOLISM_JP_PROBS if is_jp(country) else DRUG_METABOLISM_US_PROBS,
            )
        ),
        renal_reserve=max(RESERVE_FLOOR, float(rng.beta(*_RESERVE_BETA_PARAMS)) - age_penalty),
        cardiac_reserve=max(RESERVE_FLOOR, float(rng.beta(*_RESERVE_BETA_PARAMS)) - age_penalty),
        hepatic_reserve=max(
            RESERVE_FLOOR, float(rng.beta(*_RESERVE_BETA_PARAMS)) - age_penalty * AGE_PENALTY_HEPATIC_RATIO
        ),
        treatment_sensitivity=float(rng.normal(TREATMENT_SENSITIVITY_MEAN, TREATMENT_SENSITIVITY_SD)),
        symptom_reporting_bias=float(rng.normal(SYMPTOM_REPORTING_BIAS_MEAN, SYMPTOM_REPORTING_BIAS_SD)),
        delirium_susceptibility=float(rng.beta(*DELIRIUM_BETA_PARAMS))
        + (DELIRIUM_ELDERLY_PREMIUM if age >= DELIRIUM_ELDERLY_AGE_THRESHOLD else 0)
        + (DELIRIUM_DEMENTIA_PREMIUM if "F00" in person.chronic_conditions else 0)
        + (DELIRIUM_PARKINSON_PREMIUM if "G20" in person.chronic_conditions else 0),
        dvt_susceptibility=float(rng.beta(*DVT_BETA_PARAMS))
        + (DVT_ELDERLY_PREMIUM if age >= DVT_ELDERLY_AGE_THRESHOLD else 0),
    )

    # Chronic conditions (expand from ICD codes)
    conditions = []
    for code in person.chronic_conditions:
        # Random onset year (1-15 yrs ago) and random month/day
        onset_year = max(
            CHRONIC_ONSET_YEAR_FLOOR,
            CHRONIC_ONSET_YEAR_REFERENCE - int(rng.integers(CHRONIC_ONSET_YEAR_MIN, CHRONIC_ONSET_YEAR_MAX_EXCLUSIVE)),
        )
        onset_month = int(rng.integers(CHRONIC_ONSET_MONTH_MIN, CHRONIC_ONSET_MONTH_MAX_EXCLUSIVE))
        onset_day = int(rng.integers(CHRONIC_ONSET_DAY_MIN, CHRONIC_ONSET_DAY_MAX_EXCLUSIVE))
        sev = "mild" if rng.random() < CHRONIC_SEVERITY_MILD_PROBABILITY else "moderate"
        # Stage by ICD code. For diabetes (E11/E10) the stage HbA1c, the lab HbA1c, and the
        # Glucose baseline all derive from one continuous glycemic_control axis. We reuse the
        # single float draw that _generate_stage's E11 branch used to consume (now reinterpreted
        # here) so the main RNG stream is unperturbed (AD-16).
        code_base = code.split(".")[0]
        if code_base in ("E11", "E10"):
            gc_draw = float(rng.random())  # replaces the removed E11 stage uniform (1 draw)
            # Cube skews control toward "good" (most diabetics are reasonably controlled):
            # HbA1c median ~6.8%, ~55% < 7%, with a poorly-controlled tail to ~12%.
            glycemic_control = 1.0 - gc_draw**3
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
        controlled_flag = rng.random() < CHRONIC_CONTROLLED_PROBABILITY
        generic_severity_score = float(rng.uniform(GENERIC_SEVERITY_UNIFORM_MIN, GENERIC_SEVERITY_UNIFORM_MAX))
        # Graded-stage conditions derive severity_score from the sampled
        # stage instead of the generic uniform(0.1, 0.4) shared by other
        # chronic conditions. N18's stage text carries a "CKD " display
        # prefix not part of the KDIGO stage code itself, so it's the one
        # code needing the prefix stripped before the STAGE_SEVERITY lookup.
        severity_score = generic_severity_score
        if code_base in STAGE_SEVERITY:
            lookup_key = stage.removeprefix("CKD ") if code_base == "N18" else stage
            severity_score = STAGE_SEVERITY[code_base][lookup_key]
        # Issue #968: clamp the sampled onset so it never precedes the
        # patient's date_of_birth + per-disease minimum onset age. Prior
        # to this fix pediatric patients could receive chronic conditions
        # (notably J45 asthma) with onset dates years before they were
        # born because the sampler picks an adult-typical "diagnosed
        # 1-15 years ago" window with no birthDate guard.
        _sampled_onset = date(onset_year, onset_month, onset_day)
        _dob = getattr(person, "date_of_birth", None)
        _clamped = _clamp_chronic_onset(_sampled_onset, _dob, code)
        # Cap at the reference year so a very-young patient does not get
        # an onset date far in the future. If the cap would push onset
        # below dob (patient born after ref_year), keep the birthDate
        # floor instead — never regress into pre-birth territory.
        _ref_ceiling = date(CHRONIC_ONSET_YEAR_REFERENCE, 12, 31)
        if _clamped > _ref_ceiling and _dob is not None and _ref_ceiling >= _dob:
            _clamped = _ref_ceiling
        conditions.append(
            ChronicCondition(
                code=code,
                system="icd-10-cm",
                onset_date=_clamped,
                severity=sev,
                controlled=controlled_flag,
                severity_score=severity_score,
                stage=stage,
                glycemic_control=glycemic_control,
            )
        )

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
    hr_base = BASELINE_HR_BASE_MALE if sex == "M" else BASELINE_HR_BASE_FEMALE
    sbp_base = BASELINE_SBP_BASE + max(0, (age - BASELINE_SBP_AGE_REFERENCE)) * BASELINE_SBP_AGE_SCALE
    dbp_base = BASELINE_DBP_BASE + max(0, (age - BASELINE_DBP_AGE_REFERENCE)) * BASELINE_DBP_AGE_SCALE
    vitals = BaselineVitals(
        temperature=round(float(rng.normal(BASELINE_TEMPERATURE_MEAN, BASELINE_TEMPERATURE_SD)), 1),
        heart_rate=int(rng.normal(hr_base, BASELINE_HR_SAMPLE_SD)),
        systolic_bp=int(rng.normal(sbp_base, BASELINE_SBP_SAMPLE_SD)),
        diastolic_bp=int(rng.normal(dbp_base, BASELINE_DBP_SAMPLE_SD)),
        respiratory_rate=int(rng.normal(BASELINE_RR_MEAN, BASELINE_RR_SD)),
        spo2=round(float(min(BASELINE_SPO2_CEILING, rng.normal(BASELINE_SPO2_MEAN, BASELINE_SPO2_SD))), 1),
    )

    # Chronic condition adjustments to baseline vitals
    # I10 (hypertension): stage-scaled elevation (FP-I10). severity_score is 0.30
    # (Stage 1) / 0.60 (Stage 2), so Stage 2 raises BP more than Stage 1 — the stage is
    # now a real physiological consumer rather than a no-op. No new rng draw.
    _severity_by_code = {c.code: c.severity_score for c in conditions}
    if "I10" in person.chronic_conditions:
        _i10_sev = _severity_by_code.get("I10", I10_DEFAULT_SEVERITY)
        vitals.systolic_bp += int(round(I10_SBP_BASE_LIFT + _i10_sev * I10_SBP_SEVERITY_SCALE))
        vitals.diastolic_bp += int(round(I10_DBP_BASE_LIFT + _i10_sev * I10_DBP_SEVERITY_SCALE))
    if "I48" in person.chronic_conditions:
        vitals.heart_rate += int(rng.integers(I48_HR_LIFT_MIN, I48_HR_LIFT_MAX_EXCLUSIVE))  # irregularly irregular
    if "J44" in person.chronic_conditions:
        vitals.spo2 = round(min(vitals.spo2, float(rng.normal(J44_SPO2_LIMIT_MEAN, J44_SPO2_LIMIT_SD))), 1)
    if "J45" in person.chronic_conditions:
        vitals.respiratory_rate += int(rng.integers(J45_RR_LIFT_MIN, J45_RR_LIFT_MAX_EXCLUSIVE))
    if "E03" in person.chronic_conditions:
        vitals.heart_rate -= int(rng.integers(E03_HR_REDUCTION_MIN, E03_HR_REDUCTION_MAX_EXCLUSIVE))

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

    # Current medications: from Layer 1 (prior visit discharge) + chronic conditions.
    # Issue #452 PR 3: `person.current_medications` is `list[HomeMedication]`; filter
    # on `.drug_name` (an empty drug_name means the entry has no clinical meaning).
    _layer1_meds = person.current_medications if hasattr(person, "current_medications") else []
    current_meds = [m for m in _layer1_meds if m and m.drug_name]
    if not current_meds:
        # Derive home medications from chronic conditions via chronic_medications.yaml
        # CIF stores English drug names (AD-30). JP names resolved at FHIR output.
        #
        # META #957 Incr 1: pregnancy prenatal supplements (folic acid,
        # iron — indexed under the Z34 key in chronic_medications.yaml)
        # were previously attached because Z34 was in chronic_conditions.
        # Post-Incr-1 Z34 lives in `state_periods` instead; when the
        # person has EVER conceived in this sim (state_history non-empty)
        # we synthesize a virtual Z34 ChronicCondition for the med-
        # derivation input ONLY so the supplement regimen still emits
        # as a home medication. The problem-list Condition emit iterates
        # the real `conditions` list (without this virtual entry) so no
        # Z34 problem-list-item leaks back in.
        #
        # ARCHITECTURAL NOTE: this activator hook attaches supplements
        # to the patient's persistent current_medications, which slightly
        # over-emits (supplements persist past the pregnancy). Proper
        # per-encounter MedicationRequest emission scoped to prenatal
        # visits is Incr 1.5. Under-emit vs the pre-Incr-1 flow (which
        # attached from Day 0 to any Z34-carrying woman, regardless of
        # actual pregnancy timing) is a net data-quality gain.
        _meds_input = conditions
        _has_pregnancy_history = bool(
            [p for p in getattr(person, "state_periods", []) or [] if getattr(p, "state_type", "") == "pregnancy"]
        )
        if _has_pregnancy_history:
            _meds_input = list(conditions) + [ChronicCondition(code="Z34", system="icd-10-cm")]
        _home_med_skip_log: list = []
        current_meds = _derive_home_medications(
            _meds_input,
            patient_id=person.person_id,
            country="US",
            skip_log_out=_home_med_skip_log,
        )

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
    if age >= MARITAL_STATUS_ADULT_AGE_MIN:
        # Reuse home phone as a household contact for spouse/family
        emergency_phone = phone_home or phone_mobile
        if age >= EMERGENCY_CONTACT_ELDERLY_AGE_MIN:
            emergency_rel = str(rng.choice(EMERGENCY_CONTACT_RELATIONS_ELDERLY, p=EMERGENCY_CONTACT_WEIGHTS_ELDERLY))
        else:
            emergency_rel = str(rng.choice(EMERGENCY_CONTACT_RELATIONS_ADULT, p=EMERGENCY_CONTACT_WEIGHTS_ADULT))
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
    if age < MARITAL_STATUS_ADULT_AGE_MIN:
        marital_status = MARITAL_STATUS_MINOR_CODE  # Never married
    elif age < MARITAL_STATUS_YOUNG_ADULT_AGE_MAX_EXCLUSIVE:
        marital_status = str(rng.choice(MARITAL_STATUS_YOUNG_ADULT_CODES, p=MARITAL_STATUS_YOUNG_ADULT_WEIGHTS))
    elif age < MARITAL_STATUS_MID_ADULT_AGE_MAX_EXCLUSIVE:
        marital_status = str(rng.choice(MARITAL_STATUS_MID_ADULT_CODES, p=MARITAL_STATUS_MID_ADULT_WEIGHTS))
    elif age < MARITAL_STATUS_LATE_ADULT_AGE_MAX_EXCLUSIVE:
        marital_status = str(rng.choice(MARITAL_STATUS_LATE_ADULT_CODES, p=MARITAL_STATUS_LATE_ADULT_WEIGHTS))
    else:
        marital_status = str(rng.choice(MARITAL_STATUS_ELDERLY_CODES, p=MARITAL_STATUS_ELDERLY_WEIGHTS))

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
        rh_factor=person.rh_factor,
        height_cm=round(height, 1),
        weight_kg=round(weight, 1),
        bmi=round(bmi, 1),
        address=address,
        contact=contact,
        marital_status=marital_status,
        preferred_language=preferred_language,
        employment_status="retired" if age >= EMPLOYMENT_RETIREMENT_AGE_MIN else "employed",
        occupation=getattr(person, "occupation", "other"),
        insurance_type=insurance_type,
        health_literacy=round(
            float(rng.normal(HEALTH_LITERACY_MEAN, HEALTH_LITERACY_SD)), HEALTH_LITERACY_ROUND_DIGITS
        ),
        chronic_conditions=conditions,
        allergies=allergies,
        current_medications=current_meds,
        # Issue #433 C1: immutable snapshot for renal-hold restart logic.
        # Shallow copy — subsequent encounters mutate current_medications but
        # baseline preserves the activation-time chronic regimen.
        baseline_chronic_medications=list(current_meds),
        # Issue #1066: drug_safety skip log collected during home-med
        # derivation is copied into the profile so downstream narrative /
        # audit paths can surface it.
        safety_skip_log=list(_home_med_skip_log),
        smoking_status=person.smoking_status,
        alcohol_use=person.alcohol_use,
        physiological_profile=profile,
        baseline_vitals=vitals,
        race=race,
        ethnicity=ethnicity,
        # META #957 Incr 1: forward the person's temporal-state periods
        # (pregnancy for now) so the FHIR emit adapter can derive the
        # Z37 past-birth problem-list-item Condition from delivered
        # pregnancies via ``state_history("pregnancy")``. Shallow copy —
        # PatientProfile does not mutate periods.
        state_periods=list(getattr(person, "state_periods", []) or []),
        # Issue #1114 C11g-4: forward the natural-death date sampled by
        # the ``natural_death`` POST_POPULATION enricher so downstream
        # FHIR emit (``_build_patient``) surfaces it as
        # ``Patient.deceasedDateTime``. In-hospital deaths still flow
        # through the ``record.deceased`` → discharge_datetime path
        # (see ``fhir_r4/__init__.py:521``) — the two paths converge in
        # the FHIR builder's ``p.get("date_of_death")`` read.
        date_of_death=getattr(person, "date_of_death", None),
    )


def _derive_home_medications(
    chronic_conditions: list,
    rng: np.random.Generator | None = None,
    country: str = "US",
    *,
    patient_id: str = "",
    skip_log_out: list | None = None,
) -> list[HomeMedication]:
    """Derive home medications from chronic conditions via chronic_medications.yaml.

    Per-ICD block ``exclusive_classes`` (Issue #432) lists ``drug_class``
    tags whose drugs must be selected via a mutually-exclusive categorical
    draw (at most one drug from the class). Drugs without a ``drug_class``,
    or whose class is not in the exclusive list, follow the original
    independent-Bernoulli path so clinically-valid concurrent regimens
    (e.g. I50 HF triad, I25 DAPT) stay intact.

    Categorical semantics: probabilities within an exclusive class MUST
    sum to <= 1.0. Residual mass (1 - sum) becomes the "no drug from this
    class" branch. Sum > 1.0 is a YAML author error (fail-loud).

    Returns a list of `HomeMedication` (Issue #452 PR 1). Before that PR
    this returned `list[str]`, dropping `route` / `frequency` from the
    YAML at exactly this point — the root of #442 / #445 cascade.
    Structured fields flow through to Layer 2 unchanged.
    """
    from clinosim.locale.loader import load_chronic_medications

    data = load_chronic_medications()

    # Issue #439 P1: per-patient sub-RNG for chronic-medication selection so
    # YAML edits to chronic_medications.yaml do NOT shift unrelated patients'
    # cohorts. Sibling of AD-59 panel_specimen_seed / individual_lab_seed.
    # Tests may inject an explicit rng; production callers pass patient_id
    # (rng=None) and the helper derives the sub-RNG internally.
    if rng is None:
        from clinosim.seeding import chronic_medication_seed

        if not patient_id:
            raise ValueError(
                "_derive_home_medications: either `rng` or `patient_id` must "
                "be provided (patient_id required for stable sub-RNG derivation)."
            )
        rng = np.random.default_rng(chronic_medication_seed(patient_id))

    meds: list[HomeMedication] = []
    seen: set[str] = set()
    for condition in chronic_conditions:
        code = condition.code if hasattr(condition, "code") else ""
        if not code:
            continue
        # Try exact match, then base code (e.g., E11.9 → E11, N18.3 → N18)
        spec = data.get(code) or data.get(code.split(".")[0])
        if not spec:
            continue

        exclusive_classes = set(spec.get("exclusive_classes") or ())
        medications = spec.get("medications", [])

        # Single-mechanism selection: exclusive_classes categorical + non-exclusive
        # independent Bernoulli. Shared with `_build_discharge_rx` — see
        # `select_with_exclusive_classes` in clinosim.modules._shared.
        from clinosim.modules._shared import select_with_exclusive_classes

        for picked in select_with_exclusive_classes(
            medications,
            exclusive_classes,
            rng,
            independent_mode="bernoulli",
            context=f"chronic_medications ICD {code}",
        ):
            drug_en = picked.get("drug", "")
            drug_ja = picked.get("drug_ja", "")
            # CIF stores English drug names (AD-30). JP display picks up drug_ja
            # at output time. Selection key uses the string that reaches the
            # display side so JP and US dedup identically.
            name_for_display = drug_ja if is_jp(country) else drug_en
            if not name_for_display or name_for_display in seen:
                continue

            # Issue #1066: drug_safety CPOE-style gate for chronic co-prescriptions.
            # The activator is the point where warfarin+aspirin (both chronic)
            # pairs form — check each candidate against already-accepted home
            # meds and skip on major/contraindicated severity. Substitution
            # for chronic meds is out of scope for MVP; a skipped chronic
            # candidate is simply dropped (Warfarin already covers the AF
            # anticoagulation indication, so the Aspirin skip does not leave
            # a therapy gap).
            from clinosim.modules import drug_safety
            from clinosim.modules.drug_safety.verdict import (
                SEVERITY_RANK,
                SafetySkipEntry,
            )

            candidate_drug = drug_en if drug_en else name_for_display
            active_drug_names = [m.drug_name for m in meds if m.drug_name]
            verdicts = drug_safety.check_candidate_against_active(candidate_drug, active_drug_names)
            worst = max(
                (v for v in verdicts if not v.is_allowed),
                key=lambda v: SEVERITY_RANK[v.severity],
                default=None,
            )
            if worst is not None and worst.default_action == "skip":
                if skip_log_out is not None:
                    skip_log_out.append(
                        SafetySkipEntry(
                            encounter_id="__home_med_derivation__",
                            candidate_drug=candidate_drug,
                            candidate_drug_ja=(
                                drug_safety.japanese_display(candidate_drug) or drug_ja or candidate_drug
                            ),
                            active_conflict=worst.matched_active_drug or "",
                            active_conflict_ja=(
                                drug_safety.japanese_display(worst.matched_active_drug or "")
                                or (worst.matched_active_drug or "")
                            ),
                            verdict=worst,
                            substituted_with=None,
                            substituted_with_ja=None,
                            context_hint="home_med_derivation",
                            timestamp="",
                        )
                    )
                continue  # drop the contraindicated chronic candidate

            seen.add(name_for_display)
            meds.append(
                HomeMedication(
                    drug_name=candidate_drug,
                    drug_name_ja=drug_ja,
                    route=str(picked.get("route", "") or ""),
                    dose=str(picked.get("dose", "") or ""),
                    frequency=str(picked.get("frequency", "") or ""),
                )
            )
    return meds
