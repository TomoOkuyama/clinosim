"""Patient-activator thresholds (Issue #637).

``clinosim/modules/patient/activator.py::activate_patient`` converts a
Layer 1 ``PersonRecord`` into a full ``PatientProfile`` with sampled
physiological reserves, baseline vitals, chronic-condition onset
dates, and per-condition vital-sign adjustments.

Every scalar the function previously carried inline is lifted here
per policy §5. Companion to the existing ``_severity_activation.py``
(which covers per-ICD-code stage weights and STAGE_SEVERITY lookup).

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.beta``,
``rng.normal``, ``rng.uniform``, ``rng.integers``, ``rng.choice``,
``rng.random`` all consume identical bytes whether their arguments
come from literals or module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "AGE_PENALTY_HEPATIC_RATIO",
    "AGE_PENALTY_MIN_AGE",
    "AGE_PENALTY_SCALE",
    "BASELINE_DBP_AGE_REFERENCE",
    "BASELINE_DBP_AGE_SCALE",
    "BASELINE_DBP_BASE",
    "BASELINE_DBP_SAMPLE_SD",
    "BASELINE_HR_BASE_FEMALE",
    "BASELINE_HR_BASE_MALE",
    "BASELINE_HR_SAMPLE_SD",
    "BASELINE_RR_MEAN",
    "BASELINE_RR_SD",
    "BASELINE_SBP_AGE_REFERENCE",
    "BASELINE_SBP_AGE_SCALE",
    "BASELINE_SBP_BASE",
    "BASELINE_SBP_SAMPLE_SD",
    "BASELINE_SPO2_CEILING",
    "BASELINE_SPO2_MEAN",
    "BASELINE_SPO2_SD",
    "BASELINE_TEMPERATURE_MEAN",
    "BASELINE_TEMPERATURE_SD",
    "CHRONIC_CONTROLLED_PROBABILITY",
    "CHRONIC_ONSET_DAY_MAX_EXCLUSIVE",
    "CHRONIC_ONSET_DAY_MIN",
    "CHRONIC_ONSET_MONTH_MAX_EXCLUSIVE",
    "CHRONIC_ONSET_MONTH_MIN",
    "CHRONIC_ONSET_YEAR_FLOOR",
    "CHRONIC_ONSET_YEAR_MAX_EXCLUSIVE",
    "CHRONIC_ONSET_YEAR_MIN",
    "CHRONIC_ONSET_YEAR_REFERENCE",
    "CHRONIC_SEVERITY_MILD_PROBABILITY",
    "DELIRIUM_BETA_PARAMS",
    "DELIRIUM_DEMENTIA_PREMIUM",
    "DELIRIUM_ELDERLY_AGE_THRESHOLD",
    "DELIRIUM_ELDERLY_PREMIUM",
    "DELIRIUM_PARKINSON_PREMIUM",
    "DRUG_METABOLISM_JP_PROBS",
    "DRUG_METABOLISM_LABELS",
    "DRUG_METABOLISM_US_PROBS",
    "DVT_BETA_PARAMS",
    "DVT_ELDERLY_AGE_THRESHOLD",
    "DVT_ELDERLY_PREMIUM",
    "E03_HR_REDUCTION_MAX_EXCLUSIVE",
    "E03_HR_REDUCTION_MIN",
    "GENERIC_SEVERITY_UNIFORM_MAX",
    "GENERIC_SEVERITY_UNIFORM_MIN",
    "I10_DBP_BASE_LIFT",
    "I10_DBP_SEVERITY_SCALE",
    "I10_DEFAULT_SEVERITY",
    "I10_SBP_BASE_LIFT",
    "I10_SBP_SEVERITY_SCALE",
    "I48_HR_LIFT_MAX_EXCLUSIVE",
    "I48_HR_LIFT_MIN",
    "IMMUNE_REACTIVITY_BETA_PARAMS",
    "J44_SPO2_LIMIT_MEAN",
    "J44_SPO2_LIMIT_SD",
    "J45_RR_LIFT_MAX_EXCLUSIVE",
    "J45_RR_LIFT_MIN",
    "RESERVE_FLOOR",
    "SYMPTOM_REPORTING_BIAS_MEAN",
    "SYMPTOM_REPORTING_BIAS_SD",
    "TREATMENT_SENSITIVITY_MEAN",
    "TREATMENT_SENSITIVITY_SD",
]


# ---------------------------------------------------------------------------
# Age-driven reserve penalty
# ---------------------------------------------------------------------------

AGE_PENALTY_MIN_AGE: int = 40
"""Minimum age at which the age-driven reserve penalty begins to
accumulate. Below this age the penalty is 0."""

AGE_PENALTY_SCALE: float = 0.005
"""Age-penalty scale (per year past :data:`AGE_PENALTY_MIN_AGE`).

Empirical tuning for the synthetic simulator: 0.005/year lands an
80-year-old at 0.20 reserve deduction — enough to be clinically
meaningful without dominating the beta-distribution draw."""

AGE_PENALTY_HEPATIC_RATIO: float = 0.7
"""Ratio of the hepatic-reserve age penalty relative to the renal and
cardiac penalty.

Empirical tuning for the synthetic simulator: 0.7× reflects that
hepatic reserve declines more slowly with age than renal / cardiac
reserve in healthy aging."""


# ---------------------------------------------------------------------------
# Reserve beta-distribution floor
# ---------------------------------------------------------------------------

RESERVE_FLOOR: float = 0.1
"""Minimum ``renal_reserve`` / ``cardiac_reserve`` / ``hepatic_reserve``
value after age penalty is subtracted from the beta draw.

Empirical tuning for the synthetic simulator: 0.1 (10%) prevents
elderly patients from starting the simulation at pathologically-low
reserve — matches the observation that even severe age-related
decline preserves some baseline organ function."""


# ---------------------------------------------------------------------------
# Physiologic-profile beta / normal distributions
# ---------------------------------------------------------------------------

IMMUNE_REACTIVITY_BETA_PARAMS: tuple[int, int] = (5, 5)
"""Beta-distribution parameters for ``immune_reactivity``.

(5, 5) gives a symmetric distribution centered on 0.5 — matches the
population range of immune-response variability without skewing
either direction."""

TREATMENT_SENSITIVITY_MEAN: float = 1.0
"""Mean of the treatment-sensitivity normal draw. 1.0 = "average
response" — the sensitivity multiplier is applied to recovery deltas
downstream, so 1.0 is the identity."""

TREATMENT_SENSITIVITY_SD: float = 0.15
"""Standard deviation of the treatment-sensitivity normal draw.

Empirical tuning for the synthetic simulator: 0.15 gives ~68% of
patients within ±15% of the mean sensitivity — captures the observed
population-scale variability in drug response."""

SYMPTOM_REPORTING_BIAS_MEAN: float = 1.0
"""Mean of the symptom-reporting-bias normal draw. 1.0 = "reports
symptoms accurately", higher = tends to over-report, lower =
under-report."""

SYMPTOM_REPORTING_BIAS_SD: float = 0.25
"""Standard deviation of the symptom-reporting-bias draw.

Larger than the treatment-sensitivity SD because self-reported
symptom severity varies more than pharmacokinetic response —
matches the observed patient-to-patient reporting variability."""


# ---------------------------------------------------------------------------
# Delirium and DVT susceptibility (beta + age-based premiums)
# ---------------------------------------------------------------------------

DELIRIUM_BETA_PARAMS: tuple[int, int] = (2, 8)
"""Beta-distribution parameters for baseline delirium susceptibility.

(2, 8) is right-skewed toward zero — most patients have low baseline
delirium risk; the tail captures naturally-susceptible individuals."""

DELIRIUM_ELDERLY_AGE_THRESHOLD: int = 75
"""Age at or above which the elderly delirium premium adds to the
baseline beta draw."""

DELIRIUM_ELDERLY_PREMIUM: float = 0.15
"""Additive delirium-susceptibility premium for age ≥ 75.

Empirical tuning for the synthetic simulator: +0.15 reflects the
documented elderly-inpatient delirium prevalence (~20% baseline vs
5% in younger cohorts)."""

DELIRIUM_DEMENTIA_PREMIUM: float = 0.25
"""Additive delirium-susceptibility premium when the patient has
dementia (F00 ICD-10 code).

Empirical tuning for the synthetic simulator: +0.25 reflects the
strong dementia-delirium comorbidity association documented in
geriatric literature."""

DELIRIUM_PARKINSON_PREMIUM: float = 0.10
"""Additive delirium-susceptibility premium when the patient has
Parkinson's disease (G20 ICD-10 code)."""

DVT_BETA_PARAMS: tuple[int, int] = (2, 8)
"""Beta-distribution parameters for baseline DVT susceptibility.

Same shape as delirium — right-skewed toward zero baseline risk,
with a tail for genetically-predisposed individuals."""

DVT_ELDERLY_AGE_THRESHOLD: int = 70
"""Age at or above which the elderly DVT premium adds to the
baseline beta draw. Note: earlier than the delirium age threshold —
DVT risk rises more gradually across age."""

DVT_ELDERLY_PREMIUM: float = 0.10
"""Additive DVT-susceptibility premium for age ≥ 70."""


# ---------------------------------------------------------------------------
# Drug-metabolism-rate categorical distributions
# ---------------------------------------------------------------------------

DRUG_METABOLISM_LABELS: tuple[str, str, str, str] = ("poor", "normal", "rapid", "ultra_rapid")
"""CYP450 phenotype labels sampled by ``rng.choice`` from
:data:`DRUG_METABOLISM_JP_PROBS` or ``_US_PROBS``."""

DRUG_METABOLISM_JP_PROBS: tuple[float, float, float, float] = (0.15, 0.65, 0.15, 0.05)
"""JP CYP450 phenotype probability distribution (poor / normal /
rapid / ultra_rapid).

Empirical tuning for the synthetic simulator: 15% poor-metabolizer
reflects the higher CYP2C19 poor-metabolizer prevalence documented
in East Asian populations."""

DRUG_METABOLISM_US_PROBS: tuple[float, float, float, float] = (0.07, 0.70, 0.15, 0.08)
"""US CYP450 phenotype probability distribution.

Empirical tuning for the synthetic simulator: 7% poor-metabolizer +
8% ultra-rapid reflects the mixed-population CYP2C19 / CYP2D6
distribution documented in US pharmacogenomic studies."""


# ---------------------------------------------------------------------------
# Chronic-condition onset date sampling
# ---------------------------------------------------------------------------

CHRONIC_ONSET_YEAR_FLOOR: int = 1950
"""Absolute floor for chronic-condition onset year — no patient's
condition onset can be dated before this year regardless of the
random offset."""

CHRONIC_ONSET_YEAR_REFERENCE: int = 2024
"""Reference year from which the random offset is subtracted to
produce the onset year.

Note: this is a hardcoded "current year" that should ideally track
the simulation date. Kept as-is here for byte-diff equivalence with
the pre-extraction behavior."""

CHRONIC_ONSET_YEAR_MIN: int = 1
"""Inclusive lower bound of the random years-ago offset."""

CHRONIC_ONSET_YEAR_MAX_EXCLUSIVE: int = 15
"""Exclusive upper bound of the random years-ago offset (samples
1-14 years ago).

Empirical tuning for the synthetic simulator: 1-14 years ago covers
the typical chronic-condition onset timespan for currently-active
diseases (older onsets are unusual for still-active management)."""

CHRONIC_ONSET_MONTH_MIN: int = 1
"""Inclusive lower bound of the onset month (January)."""

CHRONIC_ONSET_MONTH_MAX_EXCLUSIVE: int = 13
"""Exclusive upper bound of the onset month (samples 1-12)."""

CHRONIC_ONSET_DAY_MIN: int = 1
"""Inclusive lower bound of the onset day."""

CHRONIC_ONSET_DAY_MAX_EXCLUSIVE: int = 29
"""Exclusive upper bound of the onset day (samples 1-28, February-
safe cap same convention as other event-date sampling in the
simulator)."""


# ---------------------------------------------------------------------------
# Chronic-condition severity + control sampling
# ---------------------------------------------------------------------------

CHRONIC_SEVERITY_MILD_PROBABILITY: float = 0.6
"""Probability that a chronic-condition sample lands as ``"mild"``
(vs ``"moderate"``).

Empirical tuning for the synthetic simulator: 60% mild / 40% moderate
matches the typical outpatient-managed chronic-condition severity
distribution — severe cases tend to be already hospitalized elsewhere
in the model."""

CHRONIC_CONTROLLED_PROBABILITY: float = 0.7
"""Probability that a chronic condition is flagged as ``controlled``
(medication + lifestyle-adherent, well-managed)."""

GENERIC_SEVERITY_UNIFORM_MIN: float = 0.1
"""Inclusive lower bound of the generic severity uniform sample used
for chronic conditions without stage-mapped severity."""

GENERIC_SEVERITY_UNIFORM_MAX: float = 0.4
"""Exclusive upper bound of the generic severity uniform sample."""


# ---------------------------------------------------------------------------
# Baseline vital-sign generation
# ---------------------------------------------------------------------------

BASELINE_TEMPERATURE_MEAN: float = 36.4
"""Mean baseline body temperature (°C) at rest.

36.4 °C is the healthy adult resting temperature (below the classic
37 °C to reflect the observed downward drift documented in modern
temperature studies)."""

BASELINE_TEMPERATURE_SD: float = 0.2
"""Standard deviation of the baseline temperature draw (°C)."""

BASELINE_HR_BASE_MALE: int = 72
"""Baseline heart rate (bpm) for adult males — matches the healthy
resting adult reference."""

BASELINE_HR_BASE_FEMALE: int = 78
"""Baseline heart rate (bpm) for adult females — slightly higher than
male baseline, matches the observed sex difference in resting HR."""

BASELINE_HR_SAMPLE_SD: int = 8
"""Standard deviation (bpm) of the baseline HR draw around the sex-
specific mean."""

BASELINE_SBP_BASE: int = 110
"""Baseline systolic BP (mmHg) at age 30 — matches the young-adult
resting BP reference."""

BASELINE_SBP_AGE_REFERENCE: int = 30
"""Age at which the baseline SBP formula applies without the age-
scaling lift."""

BASELINE_SBP_AGE_SCALE: float = 0.5
"""SBP age scale (mmHg per year past
:data:`BASELINE_SBP_AGE_REFERENCE`).

Empirical tuning for the synthetic simulator: matches the observed
population-scale SBP age gradient (~5 mmHg per decade past age 30)."""

BASELINE_SBP_SAMPLE_SD: int = 10
"""Standard deviation (mmHg) of the baseline SBP draw."""

BASELINE_DBP_BASE: int = 70
"""Baseline diastolic BP (mmHg) at age 30."""

BASELINE_DBP_AGE_REFERENCE: int = 30
"""Age at which the baseline DBP formula applies without the age-
scaling lift."""

BASELINE_DBP_AGE_SCALE: float = 0.2
"""DBP age scale (mmHg per year past
:data:`BASELINE_DBP_AGE_REFERENCE`).

Smaller than SBP scale — matches the observed gentler DBP age
gradient (DBP tends to plateau or decline after middle age, so the
sample uses a gentler slope than SBP)."""

BASELINE_DBP_SAMPLE_SD: int = 7
"""Standard deviation (mmHg) of the baseline DBP draw."""

BASELINE_RR_MEAN: int = 16
"""Baseline respiratory rate (breaths/min) — matches the healthy
adult resting reference."""

BASELINE_RR_SD: int = 2
"""Standard deviation (breaths/min) of the baseline RR draw."""

BASELINE_SPO2_MEAN: float = 97.5
"""Baseline SpO2 (%) — matches the healthy adult resting reference."""

BASELINE_SPO2_SD: float = 1.0
"""Standard deviation (%) of the baseline SpO2 draw."""

BASELINE_SPO2_CEILING: int = 99
"""Ceiling on the sampled baseline SpO2 — prevents the normal
distribution's right tail from producing implausible 100+ % values
(SpO2 is physiologically capped at 100 %)."""


# ---------------------------------------------------------------------------
# Chronic-condition vital-sign adjustments
# ---------------------------------------------------------------------------

I10_DEFAULT_SEVERITY: float = 0.30
"""Fallback I10 severity_score if the condition record lacks one.

Matches the Stage-1 hypertension severity (from
``_severity_activation.py::STAGE_SEVERITY``)."""

I10_SBP_BASE_LIFT: int = 8
"""Base SBP lift (mmHg) applied when the patient has hypertension
(I10), before the severity-scaled additional lift."""

I10_SBP_SEVERITY_SCALE: int = 20
"""SBP lift scale (mmHg per unit I10 severity_score).

Empirical tuning for the synthetic simulator: Stage 1 (severity 0.30)
= +8 + 6 = +14 mmHg; Stage 2 (severity 0.60) = +8 + 12 = +20 mmHg —
matches the JNC-8 / ACC-AHA staged BP elevation."""

I10_DBP_BASE_LIFT: int = 4
"""Base DBP lift (mmHg) applied when the patient has hypertension."""

I10_DBP_SEVERITY_SCALE: int = 10
"""DBP lift scale (mmHg per unit I10 severity_score) — half the SBP
scale, matching the observed narrower DBP staging."""

I48_HR_LIFT_MIN: int = 5
"""Inclusive lower bound of the HR lift for atrial fibrillation
(I48) patients — "irregularly irregular" tachycardia."""

I48_HR_LIFT_MAX_EXCLUSIVE: int = 20
"""Exclusive upper bound of the HR lift for I48 patients."""

J44_SPO2_LIMIT_MEAN: float = 94.0
"""Mean SpO2 limit (%) applied to COPD (J44) patients — chronic
hypoxemia baseline lower than the healthy 97.5% baseline."""

J44_SPO2_LIMIT_SD: float = 1.5
"""Standard deviation (%) of the J44 SpO2 limit draw."""

J45_RR_LIFT_MIN: int = 0
"""Inclusive lower bound of the RR lift for asthma (J45) patients."""

J45_RR_LIFT_MAX_EXCLUSIVE: int = 3
"""Exclusive upper bound of the RR lift for J45 patients (0-2 breaths/
min extra baseline RR)."""

E03_HR_REDUCTION_MIN: int = 3
"""Inclusive lower bound of the HR reduction for hypothyroidism (E03)
patients — bradycardia tendency."""

E03_HR_REDUCTION_MAX_EXCLUSIVE: int = 8
"""Exclusive upper bound of the HR reduction for E03 patients."""
