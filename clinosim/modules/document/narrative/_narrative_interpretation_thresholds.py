"""Narrative-interpretation thresholds (Issue #637).

Lifts previously-inline clinical cutoffs from
:mod:`clinosim.modules.document.narrative.template_generator`. These
values are consumed by the narrative-generation helpers that translate
raw lab / vital numbers into human-readable Japanese / English
interpretations (「基準内」/「境界」/「高血圧」/「糖尿病型」/…).

All values are grounded in the JP 特定健診 / 高血圧治療ガイドライン
2019 / 動脈硬化性疾患予防ガイドライン 2022 / JDS DM diagnostic criteria
— documented in each constant's docstring. Not empirical simulator
tuning: these ARE the published clinical thresholds and must not be
adjusted without a matching guideline update.

Byte-diff verification: the narrative-generation code path is
deterministic given a fixed set of lab values; the constant
substitution preserves the branch decisions bit-identically.
"""

from __future__ import annotations

__all__ = [
    "NARRATIVE_BMI_NORMAL_MAX_EXCLUSIVE",
    "NARRATIVE_BMI_OBESITY_MILD_MAX_EXCLUSIVE",
    "NARRATIVE_BMI_UNDERWEIGHT_MAX_EXCLUSIVE",
    "NARRATIVE_BP_HIGH_NORMAL_DBP_THRESHOLD",
    "NARRATIVE_BP_HIGH_NORMAL_SBP_THRESHOLD",
    "NARRATIVE_BP_HYPERTENSION_DBP_THRESHOLD",
    "NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD",
    "NARRATIVE_HBA1C_BORDERLINE_THRESHOLD",
    "NARRATIVE_HBA1C_DIABETES_THRESHOLD",
    "NARRATIVE_LDL_BORDERLINE_THRESHOLD",
    "NARRATIVE_LDL_ELEVATED_THRESHOLD",
    "NARRATIVE_LDL_HIGH_THRESHOLD",
    "NUTRITION_ENERGY_KCAL_PER_KG_MIDPOINT",
    "NUTRITION_PROTEIN_G_PER_KG_MIDPOINT",
]


# ---------------------------------------------------------------------------
# BMI interpretation — JP 日本肥満学会 / WHO categories
# ---------------------------------------------------------------------------

NARRATIVE_BMI_UNDERWEIGHT_MAX_EXCLUSIVE: float = 18.5
"""BMI (kg/m²) below which the interpretation is 「低体重」
(underweight). Matches the WHO underweight cutoff (< 18.5).

Also used by `_build_ncp_nutrition_risk` as the "high malnutrition
risk" boundary — same clinical semantics."""

NARRATIVE_BMI_NORMAL_MAX_EXCLUSIVE: float = 25.0
"""BMI (kg/m²) at or above which the interpretation moves out of
「標準」 (normal). Matches the JP 日本肥満学会 obesity category-1
boundary and the WHO overweight boundary (both = 25.0).

Also used by `_build_ncp_nutrition_risk` as the "overnutrition
tendency" trigger — same clinical semantics."""

NARRATIVE_BMI_OBESITY_MILD_MAX_EXCLUSIVE: float = 30.0
"""BMI (kg/m²) at or above which the interpretation moves out of
「肥満 1 度」 into 「肥満 2 度以上」. Matches the JP 日本肥満学会
obesity category-2 boundary and the WHO obesity class-I upper
boundary (both = 30.0)."""


# ---------------------------------------------------------------------------
# Blood pressure interpretation — JP 高血圧治療ガイドライン 2019
# ---------------------------------------------------------------------------

NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD: int = 140
"""SBP (mmHg) at or above which the interpretation is 「高血圧」 (or
"hypertension"). Matches the JP 高血圧治療ガイドライン 2019 診察室
血圧 grade-I hypertension boundary (≥ 140 / ≥ 90)."""

NARRATIVE_BP_HYPERTENSION_DBP_THRESHOLD: int = 90
"""DBP (mmHg) at or above which the interpretation is 「高血圧」 —
paired with :data:`NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD` (either
SBP or DBP crossing fires the hypertension label)."""

NARRATIVE_BP_HIGH_NORMAL_SBP_THRESHOLD: int = 130
"""SBP (mmHg) at or above which the interpretation is 「高値注意」
(high-normal) — matches the JP 高血圧治療ガイドライン 2019 診察室
血圧 high-normal boundary (130-139 / 85-89)."""

NARRATIVE_BP_HIGH_NORMAL_DBP_THRESHOLD: int = 85
"""DBP (mmHg) at or above which the interpretation is 「高値注意」
— paired with :data:`NARRATIVE_BP_HIGH_NORMAL_SBP_THRESHOLD`."""


# ---------------------------------------------------------------------------
# HbA1c interpretation — JDS diabetes diagnostic criteria
# ---------------------------------------------------------------------------

NARRATIVE_HBA1C_DIABETES_THRESHOLD: float = 6.5
"""HbA1c (%) at or above which the interpretation is 「糖尿病型」
(diabetic-pattern). Matches the JDS + ADA diabetes diagnostic
threshold (HbA1c ≥ 6.5%)."""

NARRATIVE_HBA1C_BORDERLINE_THRESHOLD: float = 5.6
"""HbA1c (%) at or above which the interpretation is 「境界」
(borderline). Matches the JP 特定健診 prediabetes threshold
(HbA1c ≥ 5.6%, aligned to the ADA prediabetes range 5.7-6.4%)."""


# ---------------------------------------------------------------------------
# LDL interpretation — JAS 動脈硬化性疾患予防ガイドライン 2022
# ---------------------------------------------------------------------------

NARRATIVE_LDL_HIGH_THRESHOLD: int = 160
"""LDL (mg/dL) at or above which the interpretation is 「高 LDL
血症」 (severe hypercholesterolemia). Matches the JAS 動脈硬化性疾患
予防ガイドライン 2022 severe hyper-LDL cutoff (≥ 160)."""

NARRATIVE_LDL_BORDERLINE_THRESHOLD: int = 140
"""LDL (mg/dL) at or above which the interpretation is 「境界域」
(borderline). Matches the JAS 動脈硬化性疾患予防ガイドライン 2022
hyper-LDL cutoff (≥ 140)."""

NARRATIVE_LDL_ELEVATED_THRESHOLD: int = 120
"""LDL (mg/dL) at or above which the interpretation is 「高値注意」
(elevated). Matches the JAS 動脈硬化性疾患予防ガイドライン 2022
mild-elevation boundary (120-139)."""


# ---------------------------------------------------------------------------
# Nutrition care plan energy + protein estimation
# ---------------------------------------------------------------------------

NUTRITION_ENERGY_KCAL_PER_KG_MIDPOINT: float = 27.5
"""Energy (kcal/kg body-weight/day) midpoint used in the initial
nutrition-care-plan estimate. 25-30 kcal/kg/day is the standard
initial-planning range; 27.5 is the midpoint (design spec §3c)."""

NUTRITION_PROTEIN_G_PER_KG_MIDPOINT: float = 1.1
"""Protein (g/kg body-weight/day) midpoint used in the initial
nutrition-care-plan estimate. 1.0-1.2 g/kg/day is the standard
initial-planning range for a general adult inpatient; 1.1 is the
midpoint (design spec §3c)."""
