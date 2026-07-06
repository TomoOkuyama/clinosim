"""Severity sampling + the canonical category<->score boundary (FP-SEV-MODEL, c2).

The disease module owns the severity distribution (disease-YAML ``severity.distribution``
+ ``modifiers``), so it owns severity sampling. This module is the SINGLE definition of
the mild/moderate/severe category boundary and the continuous score each category maps
to (used by the population-time hospitalization gate).
"""

from __future__ import annotations

SEVERITY_CATEGORIES: tuple[str, str, str] = ("mild", "moderate", "severe")

# Half-open ranges (upper-inclusive on severe). category_from_score is exactly
# consistent with these so a uniform draw inside a range re-derives its category.
SEVERITY_SCORE_RANGES: dict[str, tuple[float, float]] = {
    "mild": (0.0, 0.3),
    "moderate": (0.3, 0.7),
    "severe": (0.7, 1.0),
}


def category_from_score(score: float) -> str:
    """Map a continuous severity score in [0, 1] to its category."""
    if score >= 0.7:
        return "severe"
    if score >= 0.3:
        return "moderate"
    return "mild"


# --- Modifier-condition vocabulary (enumerated from the 30 disease YAMLs) ---
# ICD-code prefixes used by evaluable comorbidity conditions.
_COND_ICD_PREFIXES: dict[str, tuple[str, ...]] = {
    "diabetes": ("E11", "E10"),
    "heart_failure": ("I50",),
    "CKD": ("N18",),
    "N18": ("N18",),
    "COPD": ("J44",),
    "liver_cirrhosis": ("K74",),
    "hypertension_uncontrolled": ("I10",),
    "atrial_fibrillation": ("I48",),
    "I48": ("I48",),
    "prior_MI": ("I25", "I21"),
    "prior_stroke_or_TIA": ("I63", "I64", "G45"),
    "peripheral_vascular_disease": ("I73",),
    "valvular_heart_disease": ("I34", "I35", "I05", "I06"),
    "hyperthyroidism": ("E05",),
    "dementia": ("F00", "F01", "F03", "G30"),
    "dementia_advanced": ("F00", "F01", "F03", "G30"),
    "osteoporosis": ("M80", "M81"),
    "active_cancer": ("C",),
    "malignancy": ("C",),
    "metastatic_cancer": ("C77", "C78", "C79", "C80"),
    "colorectal_cancer": ("C18", "C19", "C20"),
    "hepatocellular_carcinoma": ("C22",),
    "alcohol_dependence": ("F10",),
    "alcohol_dependence_active": ("F10",),
}

_AGE_OVER: dict[str, int] = {
    "age_over_65": 65,
    "age_over_75": 75,
    "age_over_80": 80,
    "age_over_85": 85,
}

# Conditions that map to a real PersonRecord attribute and are evaluated this chain.
EVALUABLE_CONDITIONS: frozenset[str] = frozenset(
    set(_COND_ICD_PREFIXES)
    | set(_AGE_OVER)
    | {"age_under_5", "obesity", "obesity_bmi_over_30", "smoking_current",
       "multiple_comorbidities"}
)

# Disease sub-type / scenario-specific conditions not derivable from PersonRecord.
# KNOWN (validation does not raise) but always evaluate False this chain. Reserved
# for the deferred scenario-flag mechanism (see TODO / registry FP-SEV-MODEL follow-up).
RESERVED_INTRINSIC_CONDITIONS: frozenset[str] = frozenset({
    "anterior_wall_MI", "saddle_embolus", "iliofemoral_location", "bilateral_dvt",
    "phlegmasia_signs", "intraventricular_hemorrhage", "acalculous", "gcs_below_8",
    "APACHE_II_above_8", "FEV1_below_30", "hypercapnia_baseline",
    "first_presentation_T1DM", "delayed_presentation", "coagulopathy",
    "multiple_levels", "neurological_deficit", "hernia_incarcerated", "WPW_syndrome",
    "sepsis", "prior_abdominal_surgery", "urinary_obstruction", "urinary_catheter",
    "symptom_duration_over_48h", "symptom_duration_over_72h", "immunosuppressed",
    "anticoagulant_use", "chronic_steroid_use", "home_oxygen_use", "pregnancy",
    "medication_noncompliance", "poor_functional_status", "prior_icu_admission",
    "prior_icu_for_asthma",
})

KNOWN_MODIFIER_CONDITIONS: frozenset[str] = (
    EVALUABLE_CONDITIONS | RESERVED_INTRINSIC_CONDITIONS
)


def _has_icd(person: object, prefixes: tuple[str, ...]) -> bool:
    codes = getattr(person, "chronic_conditions", []) or []
    return any(str(c).startswith(prefixes) for c in codes)


def _evaluate_condition(condition: str, person: object) -> bool:
    """True iff a modifier condition is active for this person.

    Reserved-intrinsic and unknown conditions return False (not fired this chain).
    """
    if condition in _AGE_OVER:
        return int(getattr(person, "age", 0)) >= _AGE_OVER[condition]
    if condition == "age_under_5":
        return int(getattr(person, "age", 999)) < 5
    if condition in ("obesity", "obesity_bmi_over_30"):
        return float(getattr(person, "bmi", 0.0)) >= 30.0
    if condition == "smoking_current":
        return getattr(person, "smoking_status", "never") == "current"
    if condition == "multiple_comorbidities":
        return len(getattr(person, "chronic_conditions", []) or []) >= 3
    if condition in _COND_ICD_PREFIXES:
        return _has_icd(person, _COND_ICD_PREFIXES[condition])
    return False


def _apply_modifiers(
    dist: dict[str, float], modifiers: list[dict], person: object
) -> dict[str, float]:
    """Multiply named-category probabilities for each active modifier condition."""
    out = dict(dist)
    for mod in modifiers or []:
        cond = mod.get("condition", "")
        if not _evaluate_condition(cond, person):
            continue
        for cat in SEVERITY_CATEGORIES:
            mult = mod.get(f"{cat}_multiplier")
            if mult is not None:
                out[cat] = out.get(cat, 0.0) * float(mult)
    return out
