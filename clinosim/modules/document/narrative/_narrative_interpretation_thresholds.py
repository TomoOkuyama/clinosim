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

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.countries import country_slot
from clinosim.datafiles import load_validated_yaml

__all__ = [
    "ChronicControlTargets",
    "chronic_control_targets",
    "BmiBand",
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
    "NARRATIVE_ADULT_TACHYCARDIA_HR",
    "NUTRITION_ENERGY_KCAL_PER_KG_MIDPOINT",
    "NUTRITION_PROTEIN_G_PER_KG_MIDPOINT",
    "bmi_band",
]


# ---------------------------------------------------------------------------
# BMI interpretation — JP 日本肥満学会 / WHO categories
# ---------------------------------------------------------------------------

NARRATIVE_BMI_UNDERWEIGHT_MAX_EXCLUSIVE: float = 18.5
"""BMI (kg/m²) below which the interpretation is 「低体重」
(underweight). Matches the WHO underweight cutoff (< 18.5).

Also used by `build_ncp_nutrition_risk` as the "high malnutrition
risk" boundary — same clinical semantics."""

NARRATIVE_BMI_NORMAL_MAX_EXCLUSIVE: float = 25.0
"""BMI (kg/m²) at or above which the interpretation moves out of
「標準」 (normal). Matches the JP 日本肥満学会 obesity category-1
boundary and the WHO overweight boundary (both = 25.0).

Also used by `build_ncp_nutrition_risk` as the "overnutrition
tendency" trigger — same clinical semantics."""

NARRATIVE_BMI_OBESITY_MILD_MAX_EXCLUSIVE: float = 30.0
"""BMI (kg/m²) at or above which the interpretation moves out of
「肥満 1 度」 into 「肥満 2 度以上」. Matches the JP 日本肥満学会
obesity category-2 boundary and the WHO obesity class-I upper
boundary (both = 30.0)."""


BmiBand = Literal["underweight", "normal", "overweight", "obese"]


def bmi_band(bmi: float) -> BmiBand:
    """WHO / 日本肥満学会 band of ``bmi`` (kg/m²), each boundary inclusive on
    its upper band: 18.5 is normal, 25.0 overweight (肥満 1 度), 30.0 obese
    (Issue #2528). Callers classify the value they display (rounded to one
    decimal) so the printed number and its band agree."""
    if bmi < NARRATIVE_BMI_UNDERWEIGHT_MAX_EXCLUSIVE:
        return "underweight"
    if bmi < NARRATIVE_BMI_NORMAL_MAX_EXCLUSIVE:
        return "normal"
    if bmi < NARRATIVE_BMI_OBESITY_MILD_MAX_EXCLUSIVE:
        return "overweight"
    return "obese"


# ---------------------------------------------------------------------------
# Blood pressure interpretation — JP 高血圧治療ガイドライン 2019
# ---------------------------------------------------------------------------


class _BpTargets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypertension: tuple[int, int]
    high_normal: tuple[int, int]
    target: tuple[int, int]


class _LdlTargets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    high: int = Field(gt=0)
    borderline: int = Field(gt=0)
    elevated: int = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> _LdlTargets:
        if not self.elevated < self.borderline < self.high:
            raise ValueError("ldl thresholds must satisfy elevated < borderline < high")
        return self


class ChronicControlTargets(BaseModel):
    """One country's BP and LDL bands and stated targets (Issue #2860)."""

    model_config = ConfigDict(extra="forbid")
    bp: _BpTargets
    ldl: _LdlTargets


class _ChronicControlTargetsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    countries: dict[Literal["jp", "us"], ChronicControlTargets]


_TARGETS_YAML = Path(__file__).resolve().parents[1] / "reference_data" / "chronic_control_targets.yaml"


@lru_cache(maxsize=1)
def _targets_by_country() -> dict[str, ChronicControlTargets]:
    data = load_validated_yaml(_TARGETS_YAML, _ChronicControlTargetsFile)
    return {k: ChronicControlTargets.model_validate(v) for k, v in data["countries"].items()}


def chronic_control_targets(country: str) -> ChronicControlTargets:
    """The BP / LDL bands and targets of ``country`` (``chronic_control_targets.yaml``)."""
    return _targets_by_country()[country_slot(country)]


_JP_TARGETS = chronic_control_targets("JP")

NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD: int = _JP_TARGETS.bp.hypertension[0]
"""SBP (mmHg) at or above which the JP interpretation is 「高血圧」 —
JSH 2019 office grade-I hypertension (≥ 140 / ≥ 90)."""

NARRATIVE_BP_HYPERTENSION_DBP_THRESHOLD: int = _JP_TARGETS.bp.hypertension[1]
"""DBP (mmHg) paired with :data:`NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD`."""

NARRATIVE_BP_HIGH_NORMAL_SBP_THRESHOLD: int = _JP_TARGETS.bp.high_normal[0]
"""SBP (mmHg) at or above which the JP interpretation is 「高値注意」
(JSH 2019 high-normal, 130-139 / 85-89)."""

NARRATIVE_BP_HIGH_NORMAL_DBP_THRESHOLD: int = _JP_TARGETS.bp.high_normal[1]
"""DBP (mmHg) paired with :data:`NARRATIVE_BP_HIGH_NORMAL_SBP_THRESHOLD`."""


BpBand = Literal["hypertension", "high_normal", "normal"]


def bp_band(sbp: float, dbp: float, country: str) -> BpBand:
    """Office band of a blood pressure for ``country`` (Issue #2751; per
    country since #2860 — JSH 2019 for JP, 2017 ACC/AHA for the US):
    hypertension when either reading reaches its hypertension threshold,
    high-normal when either reaches its high-normal threshold, else normal."""
    bp = chronic_control_targets(country).bp
    if sbp >= bp.hypertension[0] or dbp >= bp.hypertension[1]:
        return "hypertension"
    if sbp >= bp.high_normal[0] or dbp >= bp.high_normal[1]:
        return "high_normal"
    return "normal"


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

NARRATIVE_LDL_HIGH_THRESHOLD: int = _JP_TARGETS.ldl.high
"""LDL (mg/dL) at or above which the interpretation is 「高 LDL
血症」 (severe hypercholesterolemia). Matches the JAS 動脈硬化性疾患
予防ガイドライン 2022 severe hyper-LDL cutoff (≥ 160)."""

NARRATIVE_LDL_BORDERLINE_THRESHOLD: int = _JP_TARGETS.ldl.borderline
"""LDL (mg/dL) at or above which the interpretation is 「境界域」
(borderline). Matches the JAS 動脈硬化性疾患予防ガイドライン 2022
hyper-LDL cutoff (≥ 140)."""

NARRATIVE_LDL_ELEVATED_THRESHOLD: int = _JP_TARGETS.ldl.elevated
"""LDL (mg/dL) at or above which the interpretation is 「高値注意」
(elevated). Matches the JAS 動脈硬化性疾患予防ガイドライン 2022
mild-elevation boundary (120-139)."""


# ---------------------------------------------------------------------------
# Heart rate interpretation
# ---------------------------------------------------------------------------

NARRATIVE_ADULT_TACHYCARDIA_HR: int = 100
"""Heart rate (/min) at or above which an adult's SOAP Assessment notes
tachycardia (the conventional adult definition, > 100 /min resting;
AHA/ACC). A child's limit is the upper end of the normal range for the
age in ``observation.pediatric_ranges`` (Issue #2986)."""


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
