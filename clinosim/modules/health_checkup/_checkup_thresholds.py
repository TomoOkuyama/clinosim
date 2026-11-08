"""Japanese health-checkup (法定健診) value-derivation + interpretation thresholds (Issue #637).

Extracts the previously-inline scalars from
``clinosim/modules/health_checkup/engine.py`` per policy §5:

1. **Value derivation** — measurement noise SDs, per-patient fallback
   baselines, physiologic clamp bounds, and disease-status baseline
   modifiers used by ``_derive_checkup_values``.
2. The interpretation cutoffs (特定健診 保健指導判定値) live in
   ``locale/jp/reference_range_lab.yaml`` ``checkup_ranges`` (Issue #2300).

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.normal`` /
``np.clip`` produce identical results whether the arguments come from
literals or module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "BMI_MEASUREMENT_NOISE_SD",
    "BMI_PHYSIOLOGIC_MAX",
    "BMI_PHYSIOLOGIC_MIN",
    "BMI_PROFILE_FALLBACK",
    "CHECKUP_TYPE_REGIONAL_UNION_AGE_MIN",
    "CHECKUP_TYPE_SPECIFIC_AGE_MIN",
    "DBP_MEASUREMENT_NOISE_SD",
    "DBP_PHYSIOLOGIC_MAX",
    "DBP_PHYSIOLOGIC_MIN",
    "DBP_VITALS_FALLBACK",
    "HBA1C_DM_MEASUREMENT_NOISE_SD",
    "HBA1C_DM_PHYSIOLOGIC_MAX",
    "HBA1C_DM_PHYSIOLOGIC_MIN",
    "HBA1C_GC_FALLBACK",
    "HBA1C_NONDM_AGE_SCALE",
    "HBA1C_NONDM_MEASUREMENT_NOISE_SD",
    "HBA1C_NONDM_PHYSIOLOGIC_MAX",
    "HBA1C_NONDM_PHYSIOLOGIC_MIN",
    "LDL_MEASUREMENT_NOISE_SD",
    "LDL_PHYSIOLOGIC_MAX",
    "LDL_PHYSIOLOGIC_MIN",
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


# ---------------------------------------------------------------------------
# LDL cholesterol — measurement noise + clamps (the true value is the
# patient's lipid state, ``physiology.engine.patient_lipid_panel``, Issue #2941)
# ---------------------------------------------------------------------------

LDL_MEASUREMENT_NOISE_SD: float = 10.0
"""Measurement-day LDL noise SD (mg/dL) — reflects assay + biological
variability."""

LDL_PHYSIOLOGIC_MIN: float = 40.0
"""Physiologic LDL lower clamp (mg/dL) — matches severe familial
hypocholesterolemia floor / very-aggressive-statin achievable minimum."""

LDL_PHYSIOLOGIC_MAX: float = 300.0
"""Physiologic LDL upper clamp (mg/dL) — matches severe familial
hypercholesterolemia ceiling."""


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
