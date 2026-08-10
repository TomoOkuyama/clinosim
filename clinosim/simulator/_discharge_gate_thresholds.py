"""Discharge-gate thresholds (Issue #637).

``clinosim/simulator/discharge_gate.py`` implements three related
end-of-encounter decisions:

1. ``_evaluate_readmission`` — 30-day readmission risk, YAML benchmark
   ± modifiers with a clamp near the benchmark range.
2. ``_check_discharge_ready`` — daily state-based discharge-readiness
   check with US and JP threshold sets.
3. ``_evaluate_mortality`` — daily in-hospital mortality with
   day-of-stay weighting and age / perfusion modifiers.

Every scalar the three functions previously carried inline is lifted
here per policy §5, grouped by function for readability. The three
groups do not share constants — the mortality age thresholds and the
readmission age thresholds happen to overlap numerically (80 / 85) but
carry different clinical intent and are documented separately.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.random`` /
``rng.integers`` / ``rng.uniform`` all consume identical bytes whether
the arguments come from literals or module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "DISCHARGE_JP_ANEMIA_MAX",
    "DISCHARGE_JP_INFLAMMATION_MAX",
    "DISCHARGE_JP_PERFUSION_MIN",
    "DISCHARGE_JP_PH_ABS_MAX",
    "DISCHARGE_JP_RENAL_MIN",
    "DISCHARGE_JP_VOLUME_ABS_MAX",
    "DISCHARGE_US_INFLAMMATION_MAX",
    "DISCHARGE_US_PERFUSION_MIN",
    "DISCHARGE_US_PH_ABS_MAX",
    "DISCHARGE_US_RENAL_MIN",
    "DISCHARGE_US_VOLUME_ABS_MAX",
    "MORTALITY_AGE_OLDEST_MULTIPLIER",
    "MORTALITY_AGE_OLDEST_THRESHOLD",
    "MORTALITY_AGE_OLD_MULTIPLIER",
    "MORTALITY_AGE_OLD_THRESHOLD",
    "MORTALITY_DAILY_MODERATE_RATE",
    "MORTALITY_DAILY_RATE_FALLBACK",
    "MORTALITY_DAILY_SEVERE_RATE",
    "MORTALITY_DAY_EARLY_END",
    "MORTALITY_DAY_EARLY_START",
    "MORTALITY_DAY_EARLY_WEIGHT",
    "MORTALITY_DAY_LATE_START",
    "MORTALITY_DAY_LATE_WEIGHT",
    "MORTALITY_DAY_MID_WEIGHT",
    "MORTALITY_DEFAULT_AGE",
    "MORTALITY_INDIVIDUAL_MOD_CAP",
    "MORTALITY_LOW_PERFUSION_MULTIPLIER",
    "MORTALITY_LOW_PERFUSION_THRESHOLD",
    "MORTALITY_YAML_AGE85_MULTIPLIER",
    "READMISSION_AGE_OLDER_MULTIPLIER",
    "READMISSION_AGE_OLDER_THRESHOLD",
    "READMISSION_AGE_OLDEST_MULTIPLIER",
    "READMISSION_AGE_OLDEST_THRESHOLD",
    "READMISSION_BASE_RATE_DEFAULT",
    "READMISSION_CHRONIC_ADDITIONAL_PER_CONDITION",
    "READMISSION_DAYS_MAX_EXCLUSIVE",
    "READMISSION_DAYS_MIN",
    "READMISSION_FINAL_INFLAMMATION_MULTIPLIER",
    "READMISSION_FINAL_INFLAMMATION_THRESHOLD",
    "READMISSION_MISSED_DIAGNOSIS_MULTIPLIER",
    "READMISSION_ORIGINAL_SEVERITY_FALLBACK",
    "READMISSION_RATE_CAP_MULTIPLIER",
    "READMISSION_SEVERITY_LIFT_MAX",
    "READMISSION_SEVERITY_LIFT_MIN",
    "DISCHARGE_ANEMIA_MAX",
]


# ---------------------------------------------------------------------------
# _evaluate_readmission
# ---------------------------------------------------------------------------

READMISSION_BASE_RATE_DEFAULT: float = 0.15
"""Fallback 30-day readmission rate when the disease protocol's
``outcome_benchmarks[country_key].thirty_day_readmission`` is absent.

15% is a broad national-average baseline for adult medical
admissions (CMS HRRP baseline range 12-17% depending on cohort);
locale-specific benchmark YAMLs override it for individual diseases."""


READMISSION_FINAL_INFLAMMATION_THRESHOLD: float = 0.15
"""End-of-stay ``inflammation_level`` strictly above which the
readmission-risk multiplier fires.

Empirical tuning for the synthetic simulator: 0.15 is above the JP
discharge-ready ceiling (0.05) and just above the US ceiling (0.10),
so it flags patients who technically met discharge criteria but
whose inflammation was still elevated — a plausible readmission
risk factor."""

READMISSION_FINAL_INFLAMMATION_MULTIPLIER: float = 1.15
"""Multiplier applied to the readmission-rate modifier when the
end-of-stay inflammation is above the elevated threshold.

Empirical tuning for the synthetic simulator: +15% risk lift matches
the modest per-marker adjustment used elsewhere in the modifier
(elderly age brackets are 5-10%)."""

READMISSION_AGE_OLDEST_THRESHOLD: int = 80
"""Patient age (years) at or above which the "oldest" readmission-risk
multiplier fires.

Empirical tuning for the synthetic simulator: 80 marks the transition
into the frail-elderly cohort where post-discharge care and readmission
risk both rise steeply."""

READMISSION_AGE_OLDEST_MULTIPLIER: float = 1.1
"""Multiplier applied to the readmission-rate modifier for age ≥ 80.

Empirical tuning for the synthetic simulator: +10% risk lift reflects
the frail-elderly readmission-risk premium documented in HRRP data."""

READMISSION_AGE_OLDER_THRESHOLD: int = 70
"""Patient age (years) at or above (but below the oldest threshold)
which the "older" readmission-risk multiplier fires."""

READMISSION_AGE_OLDER_MULTIPLIER: float = 1.05
"""Multiplier applied to the readmission-rate modifier for age
70 ≤ age < 80.

Empirical tuning for the synthetic simulator: +5% risk lift
approximates the gentler age-related risk gradient before the
frail-elderly bracket."""

READMISSION_CHRONIC_ADDITIONAL_PER_CONDITION: float = 0.01
"""Additive contribution to the readmission-rate modifier per chronic
condition in ``patient.chronic_conditions``.

Empirical tuning for the synthetic simulator: +1% per condition scales
gently with comorbidity burden (a 5-condition patient gets +5%, roughly
matching per-comorbidity readmission-risk gradients in the literature)."""

READMISSION_MISSED_DIAGNOSIS_MULTIPLIER: float = 1.2
"""Multiplier applied to the readmission-rate modifier when the
encounter's ``clinical_diagnosis.missed_diagnoses`` is non-empty.

Empirical tuning for the synthetic simulator: +20% risk lift for
missed-diagnosis encounters reflects the higher probability of
early return with unresolved symptoms."""

READMISSION_RATE_CAP_MULTIPLIER: float = 1.5
"""Ceiling multiplier applied to the readmission rate: after all
modifiers, the final rate is clamped to ``base_rate * cap`` so no
single encounter's modifier stack can drive the rate above 1.5× the
YAML benchmark."""

READMISSION_DAYS_MIN: int = 2
"""Minimum days after discharge at which a readmission event may fire
(inclusive lower bound of ``rng.integers(min, max)``)."""

READMISSION_DAYS_MAX_EXCLUSIVE: int = 28
"""Maximum days after discharge at which a readmission event may fire
(exclusive upper bound of ``rng.integers(min, max)``).

30-day readmission convention with a 2-day floor + 28-day ceiling
excludes same-day / next-day returns (which are typically handled as
the same encounter) and matches the 30-day window minus the 2-day
floor."""

READMISSION_ORIGINAL_SEVERITY_FALLBACK: float = 0.5
"""Fallback severity used for the readmission event when the original
encounter has no recorded ``physiological_states``.

Empirical tuning for the synthetic simulator: 0.5 is the mid-point of
the [0, 1] severity scale — a moderate baseline that avoids either
extreme when the source data is missing."""

READMISSION_SEVERITY_LIFT_MIN: float = 0.05
"""Minimum incremental severity (inclusive lower bound of ``rng.uniform``)
added to the original inflammation level when constructing the
readmission event."""

READMISSION_SEVERITY_LIFT_MAX: float = 0.15
"""Maximum incremental severity (exclusive upper bound of ``rng.uniform``)
added to the original inflammation level when constructing the
readmission event.

Empirical tuning for the synthetic simulator: a readmission is
typically a modest escalation from the discharge baseline (patients
return with worsening but not catastrophic symptoms). The 0.05-0.15
range plus a 1.0 ceiling captures this trajectory."""


# ---------------------------------------------------------------------------
# _check_discharge_ready — shared anemia cutoff
# ---------------------------------------------------------------------------

DISCHARGE_ANEMIA_MAX: float = 0.60
"""Maximum ``anemia_level`` (strictly less than) at which discharge is
allowed, applied to both US and JP.

anemia_level < 0.60 corresponds to Hgb > ~7.0 g/dL for females and
> ~8.7 g/dL for males — no patient should be discharged with Hgb
below the transfusion trigger. This is a clinical hard-floor, not a
locale variant."""


# ---------------------------------------------------------------------------
# _check_discharge_ready — US thresholds
# ---------------------------------------------------------------------------

DISCHARGE_US_INFLAMMATION_MAX: float = 0.10
"""US discharge criterion: ``inflammation_level`` must be strictly less
than 0.10 (CRP proxy).

Empirical tuning for the synthetic simulator: US practice permits
earlier discharge once clinically stable; the 0.10 ceiling is above
JP's 0.05 to reflect this discharge-earlier convention."""

DISCHARGE_US_PERFUSION_MIN: float = 0.7
"""US discharge criterion: ``perfusion_status`` must be strictly greater
than 0.7 (hemodynamic stability proxy)."""

DISCHARGE_US_RENAL_MIN: float = 0.5
"""US discharge criterion: ``renal_function`` must be strictly greater
than 0.5 (no acute organ dysfunction)."""

DISCHARGE_US_VOLUME_ABS_MAX: float = 0.3
"""US discharge criterion: ``abs(volume_status)`` must be strictly less
than 0.3 (near-euvolemic)."""

DISCHARGE_US_PH_ABS_MAX: float = 0.2
"""US discharge criterion: ``abs(ph_status)`` must be strictly less
than 0.2 (no significant acid-base disturbance)."""


# ---------------------------------------------------------------------------
# _check_discharge_ready — JP thresholds (all stricter than US)
# ---------------------------------------------------------------------------

DISCHARGE_JP_INFLAMMATION_MAX: float = 0.05
"""JP discharge criterion: ``inflammation_level`` must be strictly less
than 0.05 (stricter than US 0.10).

Empirical tuning for the synthetic simulator: JP conservative-discharge
convention holds patients until inflammation resolves further —
matches longer JP LOS observed in the audit data."""

DISCHARGE_JP_PERFUSION_MIN: float = 0.8
"""JP discharge criterion: ``perfusion_status`` must be strictly greater
than 0.8 (stricter than US 0.7)."""

DISCHARGE_JP_RENAL_MIN: float = 0.6
"""JP discharge criterion: ``renal_function`` must be strictly greater
than 0.6 (stricter than US 0.5)."""

DISCHARGE_JP_VOLUME_ABS_MAX: float = 0.2
"""JP discharge criterion: ``abs(volume_status)`` must be strictly less
than 0.2 (stricter than US 0.3)."""

DISCHARGE_JP_PH_ABS_MAX: float = 0.15
"""JP discharge criterion: ``abs(ph_status)`` must be strictly less
than 0.15 (stricter than US 0.2)."""

DISCHARGE_JP_ANEMIA_MAX: float = DISCHARGE_ANEMIA_MAX
"""JP discharge anemia cutoff — same as US
(``DISCHARGE_ANEMIA_MAX``). Named separately here so future work can
introduce a JP-specific transfusion trigger without touching US
callers."""


# ---------------------------------------------------------------------------
# _evaluate_mortality — day-of-stay weighting
# ---------------------------------------------------------------------------

MORTALITY_DAY_EARLY_START: int = 2
"""First day of the elevated-early-mortality window (inclusive)."""

MORTALITY_DAY_EARLY_END: int = 7
"""Last day of the elevated-early-mortality window (inclusive)."""

MORTALITY_DAY_EARLY_WEIGHT: float = 1.5
"""Day-weight multiplier applied when the encounter day is within the
early-mortality window (typically PODs 2-7).

Empirical tuning for the synthetic simulator: 1.5× reflects the
observation that most in-hospital deaths cluster in the first week
post-admission after the initial stabilization phase."""

MORTALITY_DAY_LATE_START: int = 14
"""Day at or above (strictly) which the reduced-late-mortality weight
applies."""

MORTALITY_DAY_LATE_WEIGHT: float = 0.5
"""Day-weight multiplier applied when the encounter day is strictly
past the late-mortality boundary (typically POD > 14).

Empirical tuning for the synthetic simulator: 0.5× reflects the
lower daily mortality risk for patients who have survived the first
two weeks — the surviving cohort is medically stable."""

MORTALITY_DAY_MID_WEIGHT: float = 1.0
"""Day-weight multiplier applied for days between the early and late
windows (identity)."""

MORTALITY_DEFAULT_AGE: int = 70
"""Fallback age used when ``patient`` has no ``age`` attribute.

70 is a reasonable inpatient-cohort default that keeps the age
multiplier at ~1.0 for missing-data cases."""

MORTALITY_YAML_AGE85_MULTIPLIER: float = 1.2
"""Individual-modifier multiplier applied when the YAML-benchmark
mortality path fires and patient age ≥ 85.

Distinct from the non-YAML age multipliers below because the YAML
path applies it AFTER a benchmark-derived daily rate rather than
substituting for a hardcoded severity rate."""

MORTALITY_LOW_PERFUSION_THRESHOLD: float = 0.3
"""``perfusion_status`` strictly below which the low-perfusion
mortality multiplier fires (YAML-benchmark path only)."""

MORTALITY_LOW_PERFUSION_MULTIPLIER: float = 1.3
"""Individual-modifier multiplier applied when perfusion drops below
the low-perfusion threshold.

Empirical tuning for the synthetic simulator: +30% mortality risk
matches the well-documented hemodynamic-instability mortality
association."""

MORTALITY_INDIVIDUAL_MOD_CAP: float = 1.8
"""Ceiling on the combined individual mortality modifier (age ×
perfusion, YAML-benchmark path).

Empirical tuning for the synthetic simulator: 1.8× keeps the effective
daily rate from doubling even when multiple risk factors are present —
prevents pathological cases where an old patient with low perfusion
would exceed the benchmark expectation by too much."""

MORTALITY_DAILY_SEVERE_RATE: float = 0.003
"""Fallback daily mortality rate applied to ``severity == "severe"``
when the disease protocol lacks a YAML mortality benchmark.

Empirical tuning for the synthetic simulator: 0.3% daily × ~14-day
LOS ≈ 4% cumulative — a plausible in-hospital mortality for severe
non-critical-care admissions."""

MORTALITY_DAILY_MODERATE_RATE: float = 0.0005
"""Fallback daily mortality rate applied to ``severity == "moderate"``
when the disease protocol lacks a YAML mortality benchmark.

Empirical tuning for the synthetic simulator: 0.05% daily × ~7-day
LOS ≈ 0.35% cumulative — a plausible baseline for moderate general
admissions."""

MORTALITY_DAILY_RATE_FALLBACK: float = 0.0001
"""Fallback daily mortality rate applied to unrecognized severities
(also serves as the mild-severity rate).

Very low: mild admissions typically survive without incident."""

MORTALITY_AGE_OLDEST_THRESHOLD: int = 85
"""Patient age (years) at or above which the "oldest" mortality
multiplier fires (non-YAML path)."""

MORTALITY_AGE_OLDEST_MULTIPLIER: float = 1.5
"""Multiplier applied to the daily mortality rate for age ≥ 85
(non-YAML path).

Empirical tuning for the synthetic simulator: 1.5× lift for the
oldest-old cohort matches age-stratified inpatient mortality gradients."""

MORTALITY_AGE_OLD_THRESHOLD: int = 80
"""Patient age (years) at or above (but below the oldest threshold)
which the "old" mortality multiplier fires (non-YAML path)."""

MORTALITY_AGE_OLD_MULTIPLIER: float = 1.2
"""Multiplier applied to the daily mortality rate for
80 ≤ age < 85 (non-YAML path).

Empirical tuning for the synthetic simulator: 1.2× lift for the
80-84 bracket — gentler than the ≥85 bracket."""
