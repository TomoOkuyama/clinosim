"""Emergency-department workflow-timing and clinical-assessment thresholds
(Issue #637).

The ED simulator in ``clinosim/simulator/emergency.py`` shapes each
visit's workflow via three families of previously-inline scalars —
lifted here per policy §5:

Family 1 — **Default workup fallback**. When a scenario protocol
carries no ``workup.labs`` list, the ED still orders a basic
"triage lab" panel with probability
:data:`DEFAULT_TRIAGE_LAB_PROBABILITY` (WBC + CRP + Creatinine).

Family 2 — **Order and result timing distributions**. Every ED order
type (lab-place / lab-result / imaging / treatment) has a
``rng.normal(mean, std)`` offset from ``visit_time`` matching what
you'd see in a real ED workflow: labs go out fast (~10 min from
triage) and result late-hour (~50 min); imaging orders trail (~20
min); therapies follow diagnosis (~30 min). Vitals capture happens at
a fixed 5-minute offset (no variance — the triage nurse always
records vitals immediately).

Family 3 — **Pain-score model**. ED presentations are acute → pain
skews higher than baseline. The score is
``clamp(0, 10, rng.normal(inflammation * scale + baseline, noise))``
where the three coefficients are the ones in this module.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.normal(mean,
std)`` produces bit-identical draws whether the arguments come from
literals or module-scope floats.
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_TRIAGE_LAB_PANEL",
    "DEFAULT_TRIAGE_LAB_PROBABILITY",
    "ED_IMAGING_ORDER_OFFSET_MEAN_MIN",
    "ED_IMAGING_ORDER_OFFSET_STD_MIN",
    "ED_LAB_ORDER_OFFSET_MEAN_MIN",
    "ED_LAB_ORDER_OFFSET_STD_MIN",
    "ED_LAB_RESULT_OFFSET_MEAN_MIN",
    "ED_LAB_RESULT_OFFSET_STD_MIN",
    "ED_PAIN_INFLAMMATION_SCALE",
    "ED_PAIN_MAX",
    "ED_PAIN_MIN",
    "ED_PAIN_NOISE_STD",
    "ED_PAIN_BASELINE",
    "ED_TREATMENT_ORDER_OFFSET_MEAN_MIN",
    "ED_TREATMENT_ORDER_OFFSET_STD_MIN",
    "ED_VITALS_OFFSET_MIN",
]


# ---------------------------------------------------------------------------
# Family 1: Default workup fallback (no protocol case)
# ---------------------------------------------------------------------------

DEFAULT_TRIAGE_LAB_PROBABILITY: float = 0.6
"""Probability that an ED visit without a protocol-defined workup
still gets the basic triage-lab panel ordered.

Empirical tuning for the synthetic simulator: 60 % of no-protocol
"walk-in" ED visits (viral URI / minor trauma / vague complaint) get
basic labs; the other 40 % are triaged-and-discharged without lab
draw. Matches the ED-throughput audit's expected lab-order rate for
low-acuity presentations."""

DEFAULT_TRIAGE_LAB_PANEL: tuple[dict[str, str | float], ...] = (
    {"test": "WBC", "probability": 1.0},
    {"test": "CRP", "probability": 1.0},
    {"test": "Creatinine", "probability": 1.0},
)
"""Basic triage-lab panel ordered when :data:`DEFAULT_TRIAGE_LAB_PROBABILITY`
fires and no protocol-defined workup exists.

WBC + CRP screen for infection / inflammation (the two most common
ED workup drivers); Creatinine catches acute renal issues + informs
contrast-safe imaging decisions. Probability 1.0 per analyte means
once the panel is ordered, every component is drawn (matches how a
CBC + BMP tube is processed as one specimen in practice)."""


# ---------------------------------------------------------------------------
# Family 2: Order and result timing distributions (minutes from visit_time)
# ---------------------------------------------------------------------------

ED_LAB_ORDER_OFFSET_MEAN_MIN: float = 10.0
"""Mean minutes from ``visit_time`` at which an ED lab order is placed.

10 min matches the ED-workflow convention "triage → provider first
assessment → lab order" for a typical acute presentation."""

ED_LAB_ORDER_OFFSET_STD_MIN: float = 5.0
"""Standard deviation for the ED lab-order timing draw. 5 min captures
the practical spread — some patients get labs drawn during triage
(faster), others wait for the attending's decision (slower)."""

ED_LAB_RESULT_OFFSET_MEAN_MIN: float = 50.0
"""Mean minutes from ``visit_time`` at which an ED lab result is
available. 50 min matches the standard "STAT chemistry / hematology"
processing time in a hospital core lab."""

ED_LAB_RESULT_OFFSET_STD_MIN: float = 15.0
"""Standard deviation for the ED lab-result timing draw. 15 min
captures the practical spread of core-lab throughput at different
times of day (staffing / instrument queue)."""

ED_IMAGING_ORDER_OFFSET_MEAN_MIN: float = 20.0
"""Mean minutes from ``visit_time`` at which an ED imaging order is
placed. Imaging trails labs because most ED imaging is second-line —
CT / X-ray only after the initial history / exam / basic labs suggest
the need."""

ED_IMAGING_ORDER_OFFSET_STD_MIN: float = 8.0
"""Standard deviation for the ED imaging-order timing draw."""

ED_TREATMENT_ORDER_OFFSET_MEAN_MIN: float = 30.0
"""Mean minutes from ``visit_time`` at which an ED treatment order is
placed. Treatment follows diagnosis, so ~30 min matches the workflow
"triage → labs → provisional dx → treatment order"."""

ED_TREATMENT_ORDER_OFFSET_STD_MIN: float = 10.0
"""Standard deviation for the ED treatment-order timing draw."""

ED_VITALS_OFFSET_MIN: int = 5
"""Fixed minutes from ``visit_time`` at which ED vitals are captured.

No variance — the triage nurse always records vital signs immediately
upon patient rooming, so a fixed 5-minute offset from visit_time is
the deterministic pattern."""


# ---------------------------------------------------------------------------
# Family 3: Pain-score model
# ---------------------------------------------------------------------------

ED_PAIN_MIN: int = 0
"""Lower bound of the 0-10 pain scale. Values below 0 (rare via the
noise draw) are clamped up to 0."""

ED_PAIN_MAX: int = 10
"""Upper bound of the 0-10 pain scale (standard 0-10 NRS). Values
above 10 (also rare) are clamped down to 10."""

ED_PAIN_INFLAMMATION_SCALE: float = 4.0
"""Multiplier applied to ``inflammation_level`` in the ED pain-score
model.

``pain ≈ inflammation_level * ED_PAIN_INFLAMMATION_SCALE + ED_PAIN_BASELINE
+ noise``. With inflammation ranging 0-1, this contributes 0-4 points
to the pain score — enough to push severe inflammation to
mid-scale-high pain (7-8) once the baseline and noise are added."""

ED_PAIN_BASELINE: float = 2.0
"""Baseline pain score for an ED presentation (no inflammation, no
noise). 2/10 reflects the empirical observation that even
inflammation-negative ED presentations (e.g. isolated trauma, minor
injury) carry some discomfort — pure 0/10 pain is rare in an ED
population."""

ED_PAIN_NOISE_STD: float = 1.5
"""Standard deviation of the pain-score noise draw. 1.5 points reflects
the subjectivity of self-reported NRS pain — the same clinical
substrate can be scored 1-2 points apart depending on patient
demographics, reporting bias, and time of day."""
