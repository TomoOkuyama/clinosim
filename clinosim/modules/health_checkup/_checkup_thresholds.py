"""Japanese health-checkup (法定健診) value-derivation + interpretation thresholds (Issue #637).

Extracts the previously-inline scalars from
``clinosim/modules/health_checkup/engine.py`` per policy §5. Two groups:

1. **Value derivation** — measurement noise SDs, per-patient fallback
   baselines, physiologic clamp bounds, and disease-status baseline
   modifiers used by ``_derive_checkup_values``.
2. **Interpretation cutoffs** — per-analyte H (high) vs N (normal)
   threshold used by ``_interp_for``, aligned to JP 特定健診 /
   metabolic-syndrome criteria.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.normal`` /
``np.clip`` produce identical results whether the arguments come from
literals or module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "BMI_INTERPRET_HIGH_THRESHOLD",
    "BMI_INTERPRET_REFERENCE_RANGE",
    "BMI_MEASUREMENT_NOISE_SD",
    "BMI_PHYSIOLOGIC_MAX",
    "BMI_PHYSIOLOGIC_MIN",
    "BMI_PROFILE_FALLBACK",
    "CHECKUP_TYPE_REGIONAL_UNION_AGE_MIN",
    "CHECKUP_TYPE_SPECIFIC_AGE_MIN",
    "DBP_INTERPRET_HIGH_THRESHOLD",
    "DBP_INTERPRET_REFERENCE_RANGE",
    "DBP_MEASUREMENT_NOISE_SD",
    "DBP_PHYSIOLOGIC_MAX",
    "DBP_PHYSIOLOGIC_MIN",
    "DBP_VITALS_FALLBACK",
    "HBA1C_DM_MEASUREMENT_NOISE_SD",
    "HBA1C_DM_PHYSIOLOGIC_MAX",
    "HBA1C_DM_PHYSIOLOGIC_MIN",
    "HBA1C_GC_FALLBACK",
    "HBA1C_INTERPRET_HIGH_THRESHOLD",
    "HBA1C_INTERPRET_REFERENCE_RANGE",
    "HBA1C_NONDM_AGE_SCALE",
    "HBA1C_NONDM_MEASUREMENT_NOISE_SD",
    "HBA1C_NONDM_PHYSIOLOGIC_MAX",
    "HBA1C_NONDM_PHYSIOLOGIC_MIN",
    "LDL_AGE_SCALE_FEMALE",
    "LDL_AGE_SCALE_MALE",
    "LDL_BASE_FEMALE",
    "LDL_BASE_MALE",
    "LDL_DYSLIPIDEMIA_LIFT",
    "LDL_INTERPRET_HIGH_THRESHOLD",
    "LDL_INTERPRET_REFERENCE_RANGE",
    "LDL_MEASUREMENT_NOISE_SD",
    "LDL_PHYSIOLOGIC_MAX",
    "LDL_PHYSIOLOGIC_MIN",
    "LDL_STATIN_REDUCTION",
    "SBP_INTERPRET_HIGH_THRESHOLD",
    "SBP_INTERPRET_REFERENCE_RANGE",
    "SBP_MEASUREMENT_NOISE_SD",
    "SBP_PHYSIOLOGIC_MAX",
    "SBP_PHYSIOLOGIC_MIN",
    "SBP_VITALS_FALLBACK",
]


# ---------------------------------------------------------------------------
# BMI — measurement + interpretation
# ---------------------------------------------------------------------------

BMI_PROFILE_FALLBACK: float = 22.5
"""Fallback BMI (kg/m²) when ``patient.bmi`` is missing.

22.5 is the JP adult BMI midpoint (WHO healthy range 18.5-24.9)."""

BMI_MEASUREMENT_NOISE_SD: float = 0.3
"""Measurement-day BMI noise SD (kg/m²) applied on top of the profile
baseline — reflects intra-day weight variation without crossing
category boundaries."""

BMI_PHYSIOLOGIC_MIN: float = 10.0
"""Physiologic BMI lower clamp (kg/m²) — extreme cachexia floor."""

BMI_PHYSIOLOGIC_MAX: float = 60.0
"""Physiologic BMI upper clamp (kg/m²) — class-IV obesity ceiling."""

BMI_INTERPRET_HIGH_THRESHOLD: float = 25.0
"""BMI (kg/m²) at or above which the interpretation is "H" (high) —
matches JP 特定保健指導 肥満 cutoff (WHO overweight boundary)."""

BMI_INTERPRET_REFERENCE_RANGE: str = "18.5-24.9 kg/m2"
"""Display string for BMI reference range — WHO healthy weight band."""


# ---------------------------------------------------------------------------
# Blood pressure — SBP + DBP
# ---------------------------------------------------------------------------

SBP_VITALS_FALLBACK: int = 120
"""Fallback systolic BP (mmHg) when ``patient.baseline_vitals`` is
missing — healthy-adult resting SBP."""

SBP_MEASUREMENT_NOISE_SD: float = 5.0
"""Measurement-day SBP noise SD (mmHg) applied on top of the vitals
baseline — reflects visit-to-visit BP variability."""

SBP_PHYSIOLOGIC_MIN: float = 80.0
"""Physiologic SBP lower clamp (mmHg) — hypotension floor."""

SBP_PHYSIOLOGIC_MAX: float = 220.0
"""Physiologic SBP upper clamp (mmHg) — severe hypertensive urgency
ceiling."""

SBP_INTERPRET_HIGH_THRESHOLD: float = 130.0
"""SBP (mmHg) at or above which interpretation is "H" — matches JP
高血圧治療ガイドライン 2019 診察室血圧 130 mmHg cutoff (aligned to
US ACC/AHA 2017 stage 1 threshold)."""

SBP_INTERPRET_REFERENCE_RANGE: str = "<130 mmHg"
"""Display string for SBP reference range."""

DBP_VITALS_FALLBACK: int = 75
"""Fallback diastolic BP (mmHg) when ``patient.baseline_vitals`` is
missing."""

DBP_MEASUREMENT_NOISE_SD: float = 3.5
"""Measurement-day DBP noise SD (mmHg) — smaller than SBP because
DBP is more stable across measurements."""

DBP_PHYSIOLOGIC_MIN: float = 40.0
"""Physiologic DBP lower clamp (mmHg)."""

DBP_PHYSIOLOGIC_MAX: float = 140.0
"""Physiologic DBP upper clamp (mmHg)."""

DBP_INTERPRET_HIGH_THRESHOLD: float = 85.0
"""DBP (mmHg) at or above which interpretation is "H" — matches JP
高血圧治療ガイドライン 2019 診察室血圧 85 mmHg cutoff."""

DBP_INTERPRET_REFERENCE_RANGE: str = "<85 mmHg"
"""Display string for DBP reference range."""


# ---------------------------------------------------------------------------
# HbA1c — two-branch (diabetic vs non-diabetic)
# ---------------------------------------------------------------------------

HBA1C_GC_FALLBACK: float = 0.5
"""Fallback glycemic_control value when a diabetic patient's chronic
condition record has no ``glycemic_control`` field — mid-scale value
(0.0 = very poor, 1.0 = excellent)."""

HBA1C_DM_MEASUREMENT_NOISE_SD: float = 0.15
"""Measurement-day HbA1c noise SD (%) for diabetic patients — reflects
observed within-patient HbA1c variability."""

HBA1C_DM_PHYSIOLOGIC_MIN: float = 4.0
"""Physiologic HbA1c lower clamp (%) for diabetic patients."""

HBA1C_DM_PHYSIOLOGIC_MAX: float = 15.0
"""Physiologic HbA1c upper clamp (%) for diabetic patients — matches
the top of the poorly-controlled diabetes clinical range."""

HBA1C_NONDM_AGE_SCALE: float = 0.003
"""Age-dependent HbA1c lift (% per year above 40) for non-diabetic
patients — matches the mild age-related HbA1c drift documented in
population studies (~0.03 %/decade)."""

HBA1C_NONDM_MEASUREMENT_NOISE_SD: float = 0.12
"""Measurement-day HbA1c noise SD (%) for non-diabetic patients —
smaller than the DM branch because non-DM HbA1c is more stable."""

HBA1C_NONDM_PHYSIOLOGIC_MIN: float = 4.0
"""Physiologic HbA1c lower clamp (%) for non-diabetic patients."""

HBA1C_NONDM_PHYSIOLOGIC_MAX: float = 7.0
"""Physiologic HbA1c upper clamp (%) for non-diabetic patients — a
non-DM patient with HbA1c > 7 should be re-classified as diabetic;
the clamp prevents narrative inconsistency."""

HBA1C_INTERPRET_HIGH_THRESHOLD: float = 5.6
"""HbA1c (%) at or above which interpretation is "H" — matches JP
特定健診 prediabetes 5.6% cutoff (ADA 5.7% is broadly aligned)."""

HBA1C_INTERPRET_REFERENCE_RANGE: str = "<5.6 %"
"""Display string for HbA1c reference range."""


# ---------------------------------------------------------------------------
# LDL cholesterol — sex-specific base + age scale + disease/med modifiers
# ---------------------------------------------------------------------------

LDL_BASE_FEMALE: float = 105.0
"""Female LDL baseline (mg/dL) at age 40 — Framingham / JP 特定健診
mid-range."""

LDL_AGE_SCALE_FEMALE: float = 0.7
"""Female LDL age-scaling (mg/dL per year past 40) — stronger age
gradient reflects the post-menopausal LDL rise."""

LDL_BASE_MALE: float = 115.0
"""Male LDL baseline (mg/dL) at age 40 — Framingham / JP 特定健診
mid-range."""

LDL_AGE_SCALE_MALE: float = 0.3
"""Male LDL age-scaling (mg/dL per year past 40) — gentler gradient
than female (male LDL rises less steeply with age)."""

LDL_DYSLIPIDEMIA_LIFT: float = 40.0
"""LDL lift (mg/dL) applied to untreated dyslipidemia (E78 codes) —
matches the observed relative elevation in undiagnosed / untreated
dyslipidemia patients."""

LDL_STATIN_REDUCTION: float = 30.0
"""LDL reduction (mg/dL) applied when the patient is on a statin
(drug name ending in "-statin") — approximates the average LDL
reduction from moderate-intensity statin therapy (~30-35%)."""

LDL_MEASUREMENT_NOISE_SD: float = 10.0
"""Measurement-day LDL noise SD (mg/dL) — reflects assay + biological
variability."""

LDL_PHYSIOLOGIC_MIN: float = 40.0
"""Physiologic LDL lower clamp (mg/dL) — matches severe familial
hypocholesterolemia floor / very-aggressive-statin achievable minimum."""

LDL_PHYSIOLOGIC_MAX: float = 300.0
"""Physiologic LDL upper clamp (mg/dL) — matches severe familial
hypercholesterolemia ceiling."""

LDL_INTERPRET_HIGH_THRESHOLD: float = 120.0
"""LDL (mg/dL) at or above which interpretation is "H" — matches JP
動脈硬化性疾患予防ガイドライン 一次予防 120 mg/dL target for
primary-prevention low-risk cohort."""

LDL_INTERPRET_REFERENCE_RANGE: str = "<120 mg/dL"
"""Display string for LDL reference range."""


# ---------------------------------------------------------------------------
# Checkup-type dispatch — JP legal 健診 age boundaries
# ---------------------------------------------------------------------------

CHECKUP_TYPE_REGIONAL_UNION_AGE_MIN: int = 75
"""Age at or above which the checkup type is 広域連合健診
(regional_union) — 後期高齢者医療制度 (JP Late-Elderly Health Care
System, established 2008 with the 75+ eligibility gate)."""

CHECKUP_TYPE_SPECIFIC_AGE_MIN: int = 65
"""Age at or above which the checkup type is 特定健診 (specific) —
metabolic-syndrome-focused checkup mandated by the JP national
health-insurance system for the 40-74 population. The 65 cutoff
here is a simplification: MVP dispatch uses age-band-only mapping
(occupational for 40-64, specific for 65-74, regional_union for
75+) rather than the more precise "insurance status + occupation"
lookup. Future PR may refine this to consult the insurance-type
enrollment field on the patient identity."""
