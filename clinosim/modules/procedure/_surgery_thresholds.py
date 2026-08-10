"""Surgical-procedure timing, duration, and state-impact thresholds
(Issue #637).

The ``simulate_surgery`` function in ``modules/procedure/engine.py``
composes each surgical procedure record from a set of previously-
inline scalars — country-specific time-to-surgery, per-procedure
duration + EBL defaults, ASA-class age/comorbidity ladder, intraop
complication rates, hip-fracture implant split, and post-op
physiologic state impacts.

Every scalar is lifted here per policy §5, grouped into six families
for readability:

1. **Time-to-surgery distributions** — JP vs US target intervals
   from admission to surgery start.
2. **Duration and EBL fallbacks** — defaults when the disease
   protocol does not carry ``typical_duration_minutes`` /
   ``estimated_blood_loss_ml`` blocks.
3. **Anesthesia mode** — spinal-vs-general probability when both are
   allowed.
4. **ASA classification ladder** — age / comorbidity thresholds and
   the corresponding ASA class jumps.
5. **Intraop complication rates** — excessive bleeding, anesthesia
   hypotension.
6. **Hip-fracture surgery split** — ORIF vs hemiarthroplasty and
   the ORIF implant sub-split.
7. **Post-op state-impact deltas** — anemia lift (per-mL), volume
   status, inflammation, and the perfusion penalty for major blood
   loss.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.normal`` /
``rng.random`` produce bit-identical draws whether their arguments
come from literals or module-scope floats.
"""

from __future__ import annotations

__all__ = [
    "ASA_AGE_HIGH_THRESHOLD",
    "ASA_AGE_LOW_THRESHOLD",
    "ASA_BASE_CLASS",
    "ASA_COMORBIDITY_HIGH_THRESHOLD",
    "ASA_COMORBIDITY_LOW_THRESHOLD",
    "ASA_HIGH_CLASS",
    "ASA_LOW_CLASS",
    "DEFAULT_EBL_MEAN_ML",
    "DEFAULT_EBL_STD_ML",
    "DEFAULT_SURGERY_DURATION_MEAN_MIN",
    "DEFAULT_SURGERY_DURATION_STD_MIN",
    "EBL_ANEMIA_LIFT_DIVISOR",
    "EBL_ANEMIA_LIFT_THRESHOLD_ML",
    "EBL_MAJOR_BLEED_PERFUSION_PENALTY",
    "EBL_MAJOR_BLEED_THRESHOLD_ML",
    "EBL_MIN_ML",
    "HIP_FRACTURE_ORIF_INTRAMEDULLARY_NAIL_PROBABILITY",
    "HIP_FRACTURE_ORIF_PROBABILITY",
    "INTRAOP_ANESTHESIA_HYPOTENSION_PROBABILITY",
    "INTRAOP_EBL_BLEEDING_MULTIPLIER",
    "INTRAOP_EXCESSIVE_BLEEDING_PROBABILITY",
    "JP_TIME_TO_SURGERY_FLOOR_HOURS",
    "JP_TIME_TO_SURGERY_MEAN_HOURS",
    "JP_TIME_TO_SURGERY_STD_HOURS",
    "SPINAL_ANESTHESIA_PROBABILITY_WHEN_ALLOWED",
    "SURGERY_DURATION_MIN_MIN",
    "SURGERY_INFLAMMATION_LIFT",
    "SURGERY_VOLUME_LIFT",
    "US_TIME_TO_SURGERY_FLOOR_HOURS",
    "US_TIME_TO_SURGERY_MEAN_HOURS",
    "US_TIME_TO_SURGERY_STD_HOURS",
]


# ---------------------------------------------------------------------------
# Family 1: time-to-surgery distributions (hours from admission)
# ---------------------------------------------------------------------------

JP_TIME_TO_SURGERY_MEAN_HOURS: float = 48.0
"""Mean hours from admission to surgery start for JP cohorts. JP acute-
care hospitals typically operate hip-fracture and other urgent
surgeries on day 1-2 (48 h target); tighter US "< 24 h" convention
is a separate constant below."""

JP_TIME_TO_SURGERY_STD_HOURS: float = 24.0
"""Standard deviation of the JP time-to-surgery draw."""

JP_TIME_TO_SURGERY_FLOOR_HOURS: float = 12.0
"""Minimum time-to-surgery floor for JP cohorts. Anything faster than
12 h is unrealistic — pre-op workup + informed consent + OR
scheduling cannot compress below this."""

US_TIME_TO_SURGERY_MEAN_HOURS: float = 24.0
"""Mean hours from admission to surgery start for US cohorts. Matches
the AAOS hip-fracture "surgery within 24 h" quality benchmark."""

US_TIME_TO_SURGERY_STD_HOURS: float = 12.0
"""Standard deviation of the US time-to-surgery draw."""

US_TIME_TO_SURGERY_FLOOR_HOURS: float = 6.0
"""Minimum time-to-surgery floor for US cohorts."""


# ---------------------------------------------------------------------------
# Family 2: duration and EBL fallbacks
# ---------------------------------------------------------------------------

DEFAULT_SURGERY_DURATION_MEAN_MIN: int = 90
"""Fallback mean surgery duration (minutes) when the disease protocol
does not carry a ``typical_duration_minutes`` block. 90 min matches
typical hip-fracture ORIF / hemiarthroplasty duration and is a
reasonable centre for the general-surgery fallback."""

DEFAULT_SURGERY_DURATION_STD_MIN: int = 30
"""Fallback standard deviation for the surgery-duration draw."""

SURGERY_DURATION_MIN_MIN: int = 30
"""Minimum surgery duration floor. Anything shorter than 30 min is
implausible for an inpatient procedure — includes prep + anesthesia
induction + closure."""

DEFAULT_EBL_MEAN_ML: int = 300
"""Fallback mean estimated blood loss (mL) when the disease protocol
does not carry an ``estimated_blood_loss_ml`` block. 300 mL is a
reasonable centre for hip surgery + general orthopedic /
gastrointestinal procedures."""

DEFAULT_EBL_STD_ML: int = 150
"""Fallback standard deviation for the EBL draw."""

EBL_MIN_ML: int = 50
"""Minimum EBL floor. Even a "dry" procedure has some capillary
bleeding — pinning to 0 mL creates unrealistic post-op labs."""


# ---------------------------------------------------------------------------
# Family 3: anesthesia mode
# ---------------------------------------------------------------------------

SPINAL_ANESTHESIA_PROBABILITY_WHEN_ALLOWED: float = 0.6
"""Probability of choosing spinal (vs general) anesthesia when the
protocol's ``anesthesia`` field allows both. 60 % matches the
observed preference for spinal in hip-fracture surgery at Japanese
acute-care centres (reduced post-op delirium, better hemodynamic
control in elderly patients)."""


# ---------------------------------------------------------------------------
# Family 4: ASA classification ladder
# ---------------------------------------------------------------------------

ASA_BASE_CLASS: int = 2
"""Baseline ASA physical status class for a synthetic inpatient
surgery candidate. ASA 2 ("mild systemic disease") is the modal
class for the population that reaches an OR — younger / healthier
patients (ASA 1) rarely need inpatient surgery, so this is the
starting point before the comorbidity / age ladder promotes."""

ASA_LOW_CLASS: int = 3
"""ASA class assigned when the patient hits the low-threshold
(2+ comorbidities OR age >= 80). ASA 3 = "severe systemic disease"."""

ASA_HIGH_CLASS: int = 4
"""ASA class assigned when the patient hits the high-threshold
(3+ comorbidities AND age >= 85). ASA 4 = "severe systemic disease
that is a constant threat to life"."""

ASA_COMORBIDITY_LOW_THRESHOLD: int = 2
"""Chronic-condition count at or above which ASA class jumps from
:data:`ASA_BASE_CLASS` to :data:`ASA_LOW_CLASS` (paired with
:data:`ASA_AGE_LOW_THRESHOLD` via OR)."""

ASA_AGE_LOW_THRESHOLD: int = 80
"""Age (years) at or above which ASA class jumps from
:data:`ASA_BASE_CLASS` to :data:`ASA_LOW_CLASS` (paired with
:data:`ASA_COMORBIDITY_LOW_THRESHOLD` via OR)."""

ASA_COMORBIDITY_HIGH_THRESHOLD: int = 3
"""Chronic-condition count at or above which ASA class jumps to
:data:`ASA_HIGH_CLASS` (paired with :data:`ASA_AGE_HIGH_THRESHOLD`
via AND)."""

ASA_AGE_HIGH_THRESHOLD: int = 85
"""Age (years) at or above which ASA class jumps to
:data:`ASA_HIGH_CLASS` (paired with
:data:`ASA_COMORBIDITY_HIGH_THRESHOLD` via AND)."""


# ---------------------------------------------------------------------------
# Family 5: intraop complication rates
# ---------------------------------------------------------------------------

INTRAOP_EXCESSIVE_BLEEDING_PROBABILITY: float = 0.03
"""Probability of an "excessive bleeding" intraop complication.
3 % matches published rates for orthopedic + general-surgery
excessive-bleeding events (any single-modality > 2× expected EBL)."""

INTRAOP_EBL_BLEEDING_MULTIPLIER: int = 2
"""EBL multiplier applied when the excessive-bleeding complication
fires. Doubles the sampled EBL to reflect the extra intraop blood
loss beyond the base distribution."""

INTRAOP_ANESTHESIA_HYPOTENSION_PROBABILITY: float = 0.01
"""Probability of an "anesthesia-induced hypotension" intraop
complication. 1 % matches published rates for BP < 80/45 during
induction in the surgical-inpatient population."""


# ---------------------------------------------------------------------------
# Family 6: hip-fracture surgery split
# ---------------------------------------------------------------------------

HIP_FRACTURE_ORIF_PROBABILITY: float = 0.55
"""Probability of ORIF (vs hemiarthroplasty) for a hip-fracture case.
55 % ORIF reflects the split between intertrochanteric fractures
(ORIF-treated) and femoral-neck fractures (hemiarthroplasty-treated)
in a mixed hip-fracture cohort."""

HIP_FRACTURE_ORIF_INTRAMEDULLARY_NAIL_PROBABILITY: float = 0.5
"""Probability of intramedullary nail (vs compression hip screw) for
an ORIF hip-fracture case. 50 / 50 reflects institutional variability
— both implants are standard-of-care for intertrochanteric fracture
fixation."""


# ---------------------------------------------------------------------------
# Family 7: post-op state-impact deltas
# ---------------------------------------------------------------------------

EBL_ANEMIA_LIFT_THRESHOLD_ML: int = 200
"""EBL (mL) threshold at or above which the anemia-level lift fires.
Below 200 mL of loss the CBC drop is negligible and the lift is
skipped."""

EBL_ANEMIA_LIFT_DIVISOR: int = 5000
"""Divisor applied to EBL to compute the anemia-level lift delta.
``anemia_level += ebl / EBL_ANEMIA_LIFT_DIVISOR`` — 500 mL loss
produces ~0.1 anemia_level increase, matching the ~1 g/dL Hb drop
per 500 mL blood loss (250-mL RBC content per unit convention)."""

EBL_MAJOR_BLEED_THRESHOLD_ML: int = 800
"""EBL (mL) threshold at or above which the perfusion-status penalty
fires. 800 mL corresponds to ~15 % of the average adult blood
volume, which is the class-II hemorrhage threshold in ATLS
classification."""

EBL_MAJOR_BLEED_PERFUSION_PENALTY: float = -0.10
"""Perfusion-status delta applied when EBL exceeds
:data:`EBL_MAJOR_BLEED_THRESHOLD_ML`. -0.10 reflects the small but
measurable drop in tissue perfusion post major intraop blood loss."""

SURGERY_VOLUME_LIFT: float = 0.10
"""Fixed volume_status delta applied post-surgery to reflect the
intraop IV-fluid administration (crystalloid + blood-product
replacement). Applied to every surgery regardless of EBL."""

SURGERY_INFLAMMATION_LIFT: float = 0.10
"""Fixed inflammation_level delta applied post-surgery to reflect
the acute inflammatory response to tissue trauma. Applied to every
surgery regardless of EBL / duration."""
