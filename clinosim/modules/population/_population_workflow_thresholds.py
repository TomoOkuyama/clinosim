"""Population life-event and healthcare-calendar workflow thresholds (Issue #637).

``clinosim/modules/population/engine.py`` runs two monthly loops per
person after ``generate_population`` has done the demographic sampling:

1. ``generate_monthly_events`` — samples disease incidence with prior-
   hospitalization + occupation + lifestyle modifiers, adds unknown-
   cause conditions, and post-processes some events into "mixed"
   presentations.
2. ``generate_healthcare_calendar`` — schedules non-acute care
   (chronic follow-ups, annual physicals, seasonal flu vaccination,
   age / sex-based cancer screening, diabetic retinopathy).

Both loops carried a set of inline scalars for date-of-month, jitter
ranges, participation rates, and eligibility ages — lifted here per
policy §5 as a companion file to ``_population_thresholds.py`` (which
covers the demographic-sampling defaults used earlier in the same
module).

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.integers``,
``rng.random``, ``rng.choice``, and ``rng.beta`` all consume identical
bytes whether their arguments come from literals or module-scope
constants.
"""

from __future__ import annotations

__all__ = [
    "CHRONIC_VISIT_INITIAL_MONTH_CAP_EXCLUSIVE",
    "CHRONIC_VISITS_MAX_PER_YEAR",
    "COLONOSCOPY_MIN_AGE",
    "COLONOSCOPY_PROBABILITY",
    "DIABETIC_RETINOPATHY_ICD10_CODE",
    "DIABETIC_RETINOPATHY_PROBABILITY",
    "EVENT_DAY_JITTER_END_EXCLUSIVE",
    "EVENT_DAY_JITTER_START",
    "EVENT_MID_OF_MONTH_DAY",
    "EVENT_RANDOM_DAY_MAX_EXCLUSIVE",
    "EVENT_RANDOM_DAY_MIN",
    "FLU_VAX_ADULT_AGE_THRESHOLD",
    "LEGAL_ADULT_AGE",
    "FLU_VAX_COMORBIDITY_MIN",
    "FLU_VAX_MONTHS",
    "FLU_VAX_PROBABILITY",
    "HEALTH_SCREENING_MIN_AGE",
    "HEALTH_SCREENING_MONTH_END_EXCLUSIVE",
    "HEALTH_SCREENING_MONTH_START",
    "MAMMOGRAPHY_MIN_AGE",
    "MAMMOGRAPHY_PROBABILITY",
    "MIXED_CONDITIONS_MIN_AGE_DEFAULT",
    "MIXED_CONDITIONS_MIN_CHRONIC_DEFAULT",
    "MIXED_CONDITIONS_PROBABILITY_DEFAULT",
    "OCCUPATION_MISMATCH_FALLBACK_MULTIPLIER",
    "PRIOR_HOSPITALIZATION_RECURRENCE_MULTIPLIER",
    "RANDOM_MONTH_MAX_EXCLUSIVE",
    "RANDOM_MONTH_MIN",
    "UNKNOWN_CONDITION_AGE_FACTOR_DEFAULT",
    "UNKNOWN_CONDITION_BASE_RATE_DEFAULT",
    "UNKNOWN_CONDITION_MIN_AGE_DEFAULT",
    "UNKNOWN_CONDITION_PATTERNS_FALLBACK",
    "UNKNOWN_CONDITION_SEVERITY_BETA_ALPHA",
    "UNKNOWN_CONDITION_SEVERITY_BETA_BETA",
]


# ---------------------------------------------------------------------------
# Monthly event scheduling
# ---------------------------------------------------------------------------

EVENT_MID_OF_MONTH_DAY: int = 15
"""Day-of-month used as the reference point for monthly event
generation.

Empirical tuning for the synthetic simulator: mid-month is a
convention that keeps ``event_date + rng.integers(0, 28)`` well inside
any month regardless of month length — the specific day within the
month is added by the jitter below."""

EVENT_DAY_JITTER_START: int = 0
"""Lower bound (inclusive) of ``rng.integers(start, end)`` used to add
day-level jitter to monthly events."""

EVENT_DAY_JITTER_END_EXCLUSIVE: int = 28
"""Upper bound (exclusive) of ``rng.integers(start, end)`` used to add
day-level jitter to monthly events.

Empirical tuning for the synthetic simulator: 28 keeps the timestamp
inside every calendar month (including February), so events are
uniformly distributed across the ~4-week window anchored at the
mid-month reference day."""


# ---------------------------------------------------------------------------
# Disease-incidence modifiers
# ---------------------------------------------------------------------------

PRIOR_HOSPITALIZATION_RECURRENCE_MULTIPLIER: float = 1.5
"""Multiplier applied to a person's monthly disease rate when they have
a prior hospitalization for the same disease.

Empirical tuning for the synthetic simulator: 50% higher recurrence
risk after a prior episode approximates the well-documented rehospi-
talization risk premium for chronic-relapsing conditions (heart-failure
readmission, COPD exacerbation, etc.)."""

OCCUPATION_MISMATCH_FALLBACK_MULTIPLIER: float = 0.2
"""Occupation-risk multiplier applied when the disease has an
occupation-risk table but the person's occupation is not in it.

Empirical tuning for the synthetic simulator: 20% baseline residual
risk covers plausible domestic accidents, occasional exposure outside
one's primary occupation (e.g. an office worker helping in a
warehouse), etc. — without dropping non-matching occupations to zero
risk (which would over-concentrate work-related disease into the
listed occupations)."""


# ---------------------------------------------------------------------------
# Unknown-cause conditions (YAML-overridable defaults)
# ---------------------------------------------------------------------------

UNKNOWN_CONDITION_MIN_AGE_DEFAULT: int = 40
"""Minimum age at which an "unknown condition" event may be sampled
when demographics YAML does not provide ``unknown_conditions.min_age``.

Empirical tuning for the synthetic simulator: 40 matches the typical
onset age for the vague / non-specific presentations modeled here
(unexplained fever, weight loss, malaise, elevated inflammatory
markers) — these become clinically relevant primarily in middle-aged
and older adults."""

UNKNOWN_CONDITION_BASE_RATE_DEFAULT: float = 0.00008
"""Base monthly probability of an "unknown condition" event when
demographics YAML does not provide ``unknown_conditions.base_rate``.

Empirical tuning for the synthetic simulator: 0.008% monthly ≈ ~0.1%
annually for a 40-year-old — a rare but non-negligible occurrence
that ensures the simulator emits some unknown / undifferentiated
encounters (a realistic ~5% of ED / OP visits)."""

UNKNOWN_CONDITION_AGE_FACTOR_DEFAULT: float = 0.005
"""Per-year age-linear rate lift for unknown-condition events when
demographics YAML does not provide ``unknown_conditions.age_factor``.

Empirical tuning for the synthetic simulator: 0.5% additive per year
past ``UNKNOWN_CONDITION_MIN_AGE_DEFAULT`` — an 80-year-old sees
1 + 40 · 0.005 = 3× the 40-year-old baseline."""

UNKNOWN_CONDITION_PATTERNS_FALLBACK: tuple[str, ...] = (
    "fever_unknown",
    "weight_loss_unexplained",
    "malaise_fatigue",
    "elevated_inflammatory_markers",
)
"""Fallback pattern labels sampled uniformly when demographics YAML
does not provide ``unknown_conditions.patterns``.

These four patterns cover the common "vague / undifferentiated"
presentations that trigger clinical workups without an immediate
disease anchor — matches typical ED chief-complaint categories."""

UNKNOWN_CONDITION_SEVERITY_BETA_ALPHA: float = 2.0
"""``alpha`` shape parameter for ``rng.beta(alpha, beta)`` sampling of
unknown-condition severity.

Empirical tuning for the synthetic simulator: alpha=2, beta=3 produces
a right-skewed distribution with mean ~0.4 and mode ~0.33 — most
unknown-condition events are mild-to-moderate with a long tail toward
severe presentations."""

UNKNOWN_CONDITION_SEVERITY_BETA_BETA: float = 3.0
"""``beta`` shape parameter for ``rng.beta(alpha, beta)`` sampling of
unknown-condition severity — see
:data:`UNKNOWN_CONDITION_SEVERITY_BETA_ALPHA` for the joint rationale."""


# ---------------------------------------------------------------------------
# Mixed-condition post-processing (YAML-overridable defaults)
# ---------------------------------------------------------------------------

MIXED_CONDITIONS_MIN_AGE_DEFAULT: int = 70
"""Minimum age at which a known_disease event may be upgraded to
``mixed`` when demographics YAML does not provide
``mixed_conditions.min_age``.

Empirical tuning for the synthetic simulator: 70 marks the transition
to the multi-morbid elderly cohort where a single acute presentation
frequently overlaps with baseline chronic-condition decompensation."""

MIXED_CONDITIONS_MIN_CHRONIC_DEFAULT: int = 2
"""Minimum number of chronic conditions a person must have for a
known_disease event to be upgradable to ``mixed`` when demographics
YAML does not provide ``mixed_conditions.min_chronic_conditions``.

Empirical tuning for the synthetic simulator: ≥2 chronic conditions
approximates the standard "multi-morbid" cutoff used in geriatric
literature."""

MIXED_CONDITIONS_PROBABILITY_DEFAULT: float = 0.18
"""Probability of upgrading an eligible known_disease event to
``mixed`` when demographics YAML does not provide
``mixed_conditions.probability``.

Empirical tuning for the synthetic simulator: 18% approximates the
observed fraction of elderly-multi-morbid admissions where the acute
presentation is genuinely mixed rather than cleanly attributable to
one disease."""


# ---------------------------------------------------------------------------
# Healthcare calendar — chronic visits + annual screening
# ---------------------------------------------------------------------------

CHRONIC_VISITS_MAX_PER_YEAR: int = 6
"""Maximum number of chronic-management visits a person may accumulate
in a calendar year, regardless of the follow-up interval.

Empirical tuning for the synthetic simulator: 6 (≈ bi-monthly) is the
practical upper bound for outpatient chronic-disease follow-up in
routine care — more frequent visits would fall into acute or
specialist categories not modeled by this loop."""

HEALTH_SCREENING_MIN_AGE: int = 40
"""Minimum age at which an annual health screening event fires.

40 matches the standard US and JP annual-physical eligibility age;
the JP 特定健診 program also uses 40 as its enrollment floor."""

HEALTH_SCREENING_MONTH_START: int = 4
"""Earliest month (inclusive) of the year in which the annual health
screening is scheduled.

Empirical tuning for the synthetic simulator: April aligns with the
JP fiscal-year start (which drives 健診 scheduling); US-based
scheduling is more spread out but the April-October window still
captures the typical annual-physical clustering."""

HEALTH_SCREENING_MONTH_END_EXCLUSIVE: int = 11
"""Latest month (exclusive) of the year in which the annual health
screening is scheduled — passed as the upper bound of
``rng.integers(start, end)`` so it produces months in [start, end-1]."""


# ---------------------------------------------------------------------------
# Healthcare calendar — flu vaccination
# ---------------------------------------------------------------------------

FLU_VAX_ADULT_AGE_THRESHOLD: int = 65
"""Age at or above which a person is eligible for flu vaccination
based on age alone (younger adults must also carry chronic
conditions — see :data:`FLU_VAX_COMORBIDITY_MIN`).

65 matches the CDC and JP MHLW routine-flu-vaccination age floor."""


LEGAL_ADULT_AGE: int = 20
"""Age at or above which lifestyle sampling for smoking/alcohol
becomes clinically meaningful. Below this the population enricher
overrides `smoking_status = "never"` / `alcohol_use = "none"` even
if the demographics distribution would otherwise sample "current" /
"social" — a 10-year-old marked as an occasional drinker is
clinically implausible and consumer-visible.

The RNG draw is still consumed (result is discarded after the
override) so the F4 memoize test (`test_engine_memoize.py::
test_memoize_hit_bit_identical`) stays byte-identical across
cold vs cache-hit runs — the sub-RNG cursor is unshifted.

Value 20 aligns with the JP MHLW legal drinking + smoking age
and matches the `occupation` gate used elsewhere in the population
enricher (adolescents get `"high_school_student"` occupation, not
adult occupations)."""

FLU_VAX_COMORBIDITY_MIN: int = 2
"""Minimum number of chronic conditions at which a person below the
adult age threshold becomes eligible for flu vaccination.

Empirical tuning for the synthetic simulator: ≥2 chronic conditions
matches the "high-risk" cohort targeted by public-health vaccination
campaigns."""

FLU_VAX_PROBABILITY: float = 0.5
"""Per-eligible-person probability that a flu vaccination is actually
administered in the eligible year.

Empirical tuning for the synthetic simulator: ~50% approximates
combined US / JP adult flu-vaccination uptake rates (CDC reports
~50%, JP MHLW reports 45-55% for the ≥65 cohort)."""

FLU_VAX_MONTHS: tuple[int, int, int] = (10, 11, 12)
"""Months in which flu vaccination may be scheduled.

October-December aligns with both US and JP flu-vaccination campaign
windows (US: mid-September onward, JP: October-December MHLW push)."""


# ---------------------------------------------------------------------------
# Healthcare calendar — cancer screening
# ---------------------------------------------------------------------------

COLONOSCOPY_MIN_AGE: int = 50
"""Age at or above which colonoscopy screening is offered.

50 is the historical USPSTF colorectal-cancer screening age. (More
recent USPSTF guidance lowered this to 45; the simulator sticks with
50 as the median long-established target.)"""

COLONOSCOPY_PROBABILITY: float = 0.08
"""Per-year probability of receiving a colonoscopy screening among
eligible persons.

Empirical tuning for the synthetic simulator: 8% approximates the
"once every ~10-12 years" recommended screening interval spread as a
per-year Bernoulli."""

MAMMOGRAPHY_MIN_AGE: int = 40
"""Age at or above which mammography screening is offered to female
patients.

40 covers both the USPSTF (40-74) and JP MHLW (40+) mammography
recommendation windows."""

MAMMOGRAPHY_PROBABILITY: float = 0.4
"""Per-year probability of receiving a mammography screening among
eligible women.

Empirical tuning for the synthetic simulator: 40% approximates
observed 2-year screening uptake (~60%) spread as an annualized
Bernoulli — reflecting the ~2-year screening interval used by both
US and JP programs."""


# ---------------------------------------------------------------------------
# Healthcare calendar — diabetic retinopathy screening
# ---------------------------------------------------------------------------

DIABETIC_RETINOPATHY_ICD10_CODE: str = "E11.9"
"""ICD-10 code for Type 2 diabetes mellitus without complications —
the chronic-condition code used to identify diabetic patients eligible
for annual retinopathy screening.

This is a specific ICD-10 code, not a threshold — extracted here
because the retinopathy-screening loop hardcodes a string comparison
against the person's chronic-conditions list."""

DIABETIC_RETINOPATHY_PROBABILITY: float = 0.6
"""Per-year probability of receiving a diabetic retinopathy screening
among diabetic (:data:`DIABETIC_RETINOPATHY_ICD10_CODE`) patients.

Empirical tuning for the synthetic simulator: 60% approximates the
observed annual ophthalmology-screening uptake among diabetic patients
(ADA / JDS both recommend annual screening; real-world adherence is
around 50-70%)."""


# ---------------------------------------------------------------------------
# Random calendar-date generation (used across chronic-visit + screening
# + vaccination + DOB paths)
# ---------------------------------------------------------------------------

RANDOM_MONTH_MIN: int = 1
"""Inclusive lower bound of the random-month draw
(``rng.integers(RANDOM_MONTH_MIN, RANDOM_MONTH_MAX_EXCLUSIVE)``).
Also used by :func:`clinosim.modules.population.engine.generate_population`
to sample a random birth-month for each synthetic person."""

RANDOM_MONTH_MAX_EXCLUSIVE: int = 13
"""Exclusive upper bound of the random-month draw. Combined with
:data:`RANDOM_MONTH_MIN` yields months 1-12."""

EVENT_RANDOM_DAY_MIN: int = 1
"""Inclusive lower bound of the random day-of-month draw for scheduled
calendar events (screenings, vaccinations, chronic follow-ups)."""

EVENT_RANDOM_DAY_MAX_EXCLUSIVE: int = 28
"""Exclusive upper bound of the random day-of-month draw. Combined
with :data:`EVENT_RANDOM_DAY_MIN` yields days 1-27 — deliberately
conservative to keep event dates away from the month-end + Feb-29
boundary (avoids ``ValueError: day is out of range for month`` when
sampling in February)."""

CHRONIC_VISIT_INITIAL_MONTH_CAP_EXCLUSIVE: int = 4
"""Exclusive upper bound of the initial-visit month draw for chronic
follow-ups. When the follow-up interval is 3+ months, the first
visit lands in months 1-3 (Jan-Mar) — later visits stride by
``shortest_interval`` from there.

Empirical tuning for the synthetic simulator: capping the first
visit at Q1 gives every chronic patient at least 3-4 visits per
year regardless of the shortest configured interval."""
