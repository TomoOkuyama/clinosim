"""Per-stay clinical thresholds for the inpatient simulator (Issue #637).

Constants lifted from previously-inline literals in
``clinosim/simulator/inpatient.py`` per policy §5. Every value below
directly shapes a downstream FHIR resource (Encounter admission
timestamp, ClinicalImpression state after readmission, Observation
values post-transfusion, missed-diagnosis flag), so a rename or shift
here is a byte-diff change — extraction to named constants preserves
the numeric values exactly and makes the intent grep-able.

Grouping convention:

- **Admission-hour distributions** — realistic hour-of-day patterns for
  elective / emergency / urgent admissions. Consumed by the encounter
  scheduler when composing ``Encounter.period.start``.
- **Readmission state carry-over** — floors / ceilings applied to
  physiology state at readmission simulation start, modelling
  incomplete recovery from a prior stay.
- **Bedside procedure state effects** — pre-baked state deltas the
  inpatient loop applies when a bedside procedure fires (currently
  only blood transfusion, but the pattern is extensible per procedure
  type).
- **Diagnostic pathway** — probabilities the diagnostic-differential
  code uses at final-diagnosis time (e.g. missed-secondary-diagnosis
  rate in mixed cases).

All values are immutable floats / ints / tuples; no runtime state
lives here. Adding a new threshold requires adding it to this module,
the ``__all__`` block below, and the consuming import in
``inpatient.py``.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.choice`` and
``rng.normal`` behave identically whether their arguments come from a
literal or a module-scope tuple / float.
"""

from __future__ import annotations

__all__ = [
    # Admission-hour distributions
    "ELECTIVE_SURGERY_ADMISSION_HOURS",
    "ELECTIVE_SURGERY_ADMISSION_HOUR_WEIGHTS",
    "EMERGENCY_ADMISSION_HOUR_MAX_EXCLUSIVE",
    "EMERGENCY_ADMISSION_SEVERITY_THRESHOLD",
    "URGENT_ADMISSION_HOUR_MEAN",
    "URGENT_ADMISSION_HOUR_STD",
    "URGENT_ADMISSION_HOUR_MIN",
    "URGENT_ADMISSION_HOUR_MAX",
    # Ward capacity default
    "INPATIENT_WARD_CAPACITY_DEFAULT",
    # Discharge-hour distribution
    "PLANNED_DISCHARGE_HOUR_MAX",
    "PLANNED_DISCHARGE_HOUR_MEAN",
    "PLANNED_DISCHARGE_HOUR_MIN",
    "PLANNED_DISCHARGE_HOUR_STD",
    # Readmission state carry-over
    "READMISSION_INFLAMMATION_FLOOR",
    "READMISSION_RENAL_CEILING",
    # Bedside procedure state effects
    "TRANSFUSION_ANEMIA_LIFT",
    "TRANSFUSION_VOLUME_LIFT",
    # Diagnostic pathway
    "MIXED_CASE_MISSED_SECONDARY_DX_PROB",
]


# ---------------------------------------------------------------------------
# Admission-hour distributions
# ---------------------------------------------------------------------------

ELECTIVE_SURGERY_ADMISSION_HOURS: tuple[int, ...] = (8, 9, 10)
"""Candidate admission hours for elective-surgery encounters. Paired
with :data:`ELECTIVE_SURGERY_ADMISSION_HOUR_WEIGHTS` by position."""

ELECTIVE_SURGERY_ADMISSION_HOUR_WEIGHTS: tuple[float, ...] = (0.3, 0.5, 0.2)
"""Weights corresponding to :data:`ELECTIVE_SURGERY_ADMISSION_HOURS`.

Empirical tuning for the synthetic simulator: elective surgical
admissions concentrate mid-morning (9 AM is the modal admission time
in Japanese acute-care hospitals for scheduled procedures, with 8 AM
early cases and 10 AM later cases forming the tails). Sums to 1.0."""

EMERGENCY_ADMISSION_SEVERITY_THRESHOLD: float = 0.6
"""Severity-score cutoff above which an admission is scheduled as an
"emergency" (any hour, uniformly sampled). Below this the admission
is scheduled as "urgent" (daytime bias, see the ``URGENT_*``
constants). Chosen so that the top ~40 % of the severity distribution
routes through the emergency path — matches the intuitive "moderate
or worse" clinical trigger for ED-mediated admission."""

URGENT_ADMISSION_HOUR_MEAN: float = 14.0
"""Mean (hours since midnight) for the urgent-admission
``rng.normal(mean, std)`` sample. 2 PM centre reflects the afternoon
peak of primary-care referrals + walk-in escalations that route
through the ED for admission without meeting the emergency threshold."""

URGENT_ADMISSION_HOUR_STD: float = 3.0
"""Standard deviation for the urgent-admission ``rng.normal`` sample.
3 hours spreads the sampled hour across the 8 AM – 8 PM daytime
window without introducing implausible night arrivals (the clamp
below narrows that to 8 AM – 10 PM)."""

URGENT_ADMISSION_HOUR_MIN: int = 8
"""Lower clamp on the urgent-admission sampled hour (after the
``rng.normal`` draw). 8 AM matches the earliest inpatient bed-turn on
a general ward."""

URGENT_ADMISSION_HOUR_MAX: int = 22
"""Upper clamp on the urgent-admission sampled hour. 10 PM is the
practical cutoff before night-shift handover; later arrivals in real
data typically route through the emergency path instead."""


# ---------------------------------------------------------------------------
# Readmission state carry-over
# ---------------------------------------------------------------------------

READMISSION_INFLAMMATION_FLOOR: float = 0.05
"""Minimum ``inflammation_level`` at readmission simulation start.

Readmitted patients carry a residual inflammatory tone from their
prior stay — the floor prevents a fully-recovered baseline that would
distort the acute-on-chronic dynamics of the readmission encounter.
Empirical tuning for the synthetic simulator."""

READMISSION_RENAL_CEILING: float = 0.9
"""Maximum ``renal_function`` at readmission simulation start.

Readmitted patients have some residual renal impairment from the
prior stay's acute events (contrast dye, ischemic hits, medication
holds). Capping the reserve at 0.9 (vs the healthy 1.0 ceiling)
models the cumulative nephron loss that shows up as elevated baseline
creatinine on the readmission labs. Empirical tuning."""


# ---------------------------------------------------------------------------
# Bedside procedure state effects
# ---------------------------------------------------------------------------

TRANSFUSION_ANEMIA_LIFT: float = 0.15
"""Fixed reduction in ``anemia_level`` applied when a blood-transfusion
bedside procedure fires.

Represents ~2 units of packed RBCs (each unit raises Hb ~1 g/dL; the
anemia_level scale is inverted, so ``-0.15`` corresponds roughly to
2 g/dL Hb rise on the observed CBC). Empirical tuning; the model
assumes 1-2 units per transfusion event without tracking exact unit
counts."""

TRANSFUSION_VOLUME_LIFT: float = 0.05
"""Fixed increase in ``volume_status`` applied post-transfusion.

Each RBC unit adds ~250 mL to circulating volume, so a 1-2 unit
transfusion nudges volume status modestly positive. Empirical tuning;
too large a value would trigger downstream heart-failure lifts
(``HF_SEVERE_THRESHOLD = 0.3``) inappropriately."""


# ---------------------------------------------------------------------------
# Diagnostic pathway
# ---------------------------------------------------------------------------

MIXED_CASE_MISSED_SECONDARY_DX_PROB: float = 0.30
"""Probability that the secondary diagnosis is missed at final-diagnosis
time in a mixed-condition inpatient case.

Reflects the real clinical reality that clinicians frequently anchor
on the primary presentation and under-diagnose comorbid acute issues
(the ~30 % missed-diagnosis rate is consistent with published
inpatient diagnostic-accuracy audits for secondary conditions).
Empirical tuning for the synthetic simulator."""


# ---------------------------------------------------------------------------
# Emergency-admission uniform hour draw
# ---------------------------------------------------------------------------

EMERGENCY_ADMISSION_HOUR_MAX_EXCLUSIVE: int = 24
"""Exclusive upper bound of the emergency-admission hour draw
(``rng.choice(24)`` = uniform 0-23). Represents "any hour of day" —
emergency admissions can occur around the clock. Named explicitly so
the intent ("all 24 hours are eligible") is readable at the call
site."""


# ---------------------------------------------------------------------------
# Ward capacity default
# ---------------------------------------------------------------------------

INPATIENT_WARD_CAPACITY_DEFAULT: int = 10
"""Fallback ward capacity used only for bed-number generation when
``hospital_ops.ward_capacity`` does not list the assigned ward. Does
not affect the actual bed allocation, only the printed bed number's
digit range. Matches the same fallback used in
:mod:`clinosim.simulator._unknown_condition_thresholds`."""


# ---------------------------------------------------------------------------
# Planned-discharge hour distribution (daytime business hours)
# ---------------------------------------------------------------------------

PLANNED_DISCHARGE_HOUR_MEAN: float = 11.0
"""Mean hour of the planned-discharge draw (``rng.normal``). 11 AM
matches typical post-morning-rounds discharge planning — orders
finalized, family notified, transportation arranged."""

PLANNED_DISCHARGE_HOUR_STD: float = 1.5
"""Standard deviation of the planned-discharge hour draw. 1.5 hours
keeps most discharges within ±2 hours of the 11 AM mean."""

PLANNED_DISCHARGE_HOUR_MIN: int = 9
"""Inclusive lower clamp for the planned-discharge hour. Discharges
before 9 AM are clinically atypical (rounds haven't finished)."""

PLANNED_DISCHARGE_HOUR_MAX: int = 16
"""Inclusive upper clamp for the planned-discharge hour. Discharges
after 4 PM shift into evening / next-day territory that this
day-shift pattern does not model."""
