"""Lab-value derivation formula constants — inflammation + renal panels (Issue #637).

Extracts the previously-inline scalars from
:func:`clinosim.modules.physiology.engine.derive_lab_values` per
policy §5. This file covers the **inflammation** (CRP, WBC, PCT,
Albumin) and **renal** (Creatinine, BUN, eGFR, K, Na) sections. The
remaining sections (cardiac, hepatic, anemia, coagulation, blood gas,
electrolytes, glucose) are deferred to sibling sub-PRs.

Every constant is a formula coefficient — clinically motivated (JCCLS
reference-range centers, KDIGO CKD staging, ADA hyperkalemia bands)
with the calibration derivations documented inline in ``engine.py``.
This file lifts the numeric values without changing the surrounding
comments.

Byte-diff verification: the lab-derivation formulas are deterministic
algebra (no RNG). Byte-identity at the pinned seed is guaranteed as
long as arithmetic order is preserved, which the constant substitution
does exactly.
"""

from __future__ import annotations

__all__ = [
    "ALBUMIN_BASELINE",
    "ALBUMIN_FLOOR",
    "ALBUMIN_HEPATIC_SCALE",
    "ALBUMIN_INFLAMMATION_SCALE",
    "BUN_BASE_MG_DL",
    "BUN_RENAL_FLOOR",
    "BUN_VOLUME_LIFT_SCALE",
    "CREATININE_BASE_FEMALE",
    "CREATININE_BASE_MALE",
    "CREATININE_LOW_RENAL_SLOPE",
    "CREATININE_LOW_RENAL_THRESHOLD",
    "CRP_BASE_MG_L",
    "CRP_INFLAMMATION_SCALE",
    "EGFR_RENAL_SCALE",
    "PCT_BASE_NG_ML",
    "PCT_INFLAMMATION_EXPONENT_SCALE",
    "POTASSIUM_ACIDOSIS_SCALE",
    "POTASSIUM_BASE_MEQ_L",
    "POTASSIUM_MAX_MEQ_L",
    "POTASSIUM_MIN_MEQ_L",
    "POTASSIUM_RENAL_SCALE",
    "SODIUM_BASE_MEQ_L",
    "SODIUM_MAX_MEQ_L",
    "SODIUM_MIN_MEQ_L",
    "SODIUM_RENAL_PENALTY",
    "SODIUM_STATUS_SCALE",
    "WBC_HIGH_INFLAMMATION_LEUKOPENIA_SCALE",
    "WBC_HIGH_INFLAMMATION_THRESHOLD",
    "WBC_LEUKOPENIA_FLOOR",
    "WBC_INFLAMMATION_SCALE",
    "WBC_BASE",
]


# ---------------------------------------------------------------------------
# CRP — cubic-inflammation model
# ---------------------------------------------------------------------------

CRP_BASE_MG_L: float = 0.3
"""Baseline CRP (mg/L) at zero inflammation — the healthy adult
reference lower bound (JCCLS < 0.30 mg/dL)."""

CRP_INFLAMMATION_SCALE: float = 400.0
"""Cubic-inflammation coefficient for CRP:
``CRP = base + 400 * effective_infl**3``.

Empirical tuning for the synthetic simulator: cubic scaling produces
``effective_infl`` 0→0.3, 0.4→26, 0.6→87, 0.75→169, 1.0→400 mg/L —
matches the clinical CRP distribution across mild-to-severe sepsis."""


# ---------------------------------------------------------------------------
# WBC — two-branch (linear rise, then leukopenia collapse)
# ---------------------------------------------------------------------------

WBC_BASE: int = 7000
"""Baseline WBC count (cells/μL) at zero inflammation — matches the
healthy adult mid-range (JCCLS 4000-9000)."""

WBC_INFLAMMATION_SCALE: int = 12000
"""Linear-inflammation scaling factor for the low-inflammation branch:
``WBC = 7000 + effective_infl * 12000``.

Empirical tuning for the synthetic simulator: at effective_infl = 0.8
(pre-leukopenia threshold), WBC = 7000 + 9600 = 16,600 — matches
sepsis-with-leukocytosis range."""

WBC_HIGH_INFLAMMATION_THRESHOLD: float = 0.8
"""``effective_infl`` at or above which the WBC formula switches from
linear rise to the leukopenia collapse branch (severe sepsis /
overwhelming infection)."""

WBC_HIGH_INFLAMMATION_LEUKOPENIA_SCALE: int = 30000
"""Cells/μL by which WBC drops per unit ``effective_infl`` past the
leukopenia threshold — models the septic-shock leukopenia collapse."""

WBC_LEUKOPENIA_FLOOR: int = 1500
"""Minimum WBC (cells/μL) even at maximum leukopenia — clinical
severe-neutropenia floor."""


# ---------------------------------------------------------------------------
# PCT (procalcitonin) — exponential inflammation model
# ---------------------------------------------------------------------------

PCT_BASE_NG_ML: float = 0.03
"""Baseline procalcitonin (ng/mL) at zero inflammation — well below
the sepsis rule-out (0.25 ng/mL) and matching healthy reference."""

PCT_INFLAMMATION_EXPONENT_SCALE: float = 7.0
"""Exponent scale for procalcitonin:
``PCT = 0.03 * exp(inflammation * 7)``.

Empirical tuning for the synthetic simulator: at inflammation = 1.0,
PCT = 0.03 * exp(7) = 32.9 ng/mL — matches the sepsis-with-shock band
(>10 ng/mL). The exponential form matches PCT's clinical behavior
(orders-of-magnitude rise in severe bacterial infection)."""


# ---------------------------------------------------------------------------
# Albumin — inflammation + hepatic depletion
# ---------------------------------------------------------------------------

ALBUMIN_BASELINE: float = 4.69375
"""Baseline serum albumin (g/dL) at zero inflammation and full hepatic
function.

Calibrated so the healthy-cohort median lands on the JCCLS reference-
range center (4.6 g/dL) after the E[reserve]-adjustment convention
introduced in Issue #416. See the derivation note in ``engine.py``
near ``base_cr``."""

ALBUMIN_INFLAMMATION_SCALE: float = 2.0
"""g/dL by which albumin drops per unit inflammation — matches the
negative-acute-phase-reactant behavior (~1-2 g/dL drop in severe
sepsis)."""

ALBUMIN_HEPATIC_SCALE: float = 1.5
"""g/dL by which albumin drops per unit ``(1 - hepatic_function)`` —
reflects the hepatic-synthesis contribution to serum albumin."""

ALBUMIN_FLOOR: float = 1.0
"""Physiological minimum serum albumin (g/dL) after all depletion
terms — matches severe-hypoalbuminemia clinical range."""


# ---------------------------------------------------------------------------
# Creatinine — sex-specific base + two-branch renal formula
# ---------------------------------------------------------------------------

CREATININE_BASE_MALE: float = 0.80625
"""Baseline serum creatinine (mg/dL) for males (see engine.py Issue
#416 calibration note): JCCLS Cre_M center 0.86 × E[reserve=beta(30,2)]
0.9375 = 0.80625."""

CREATININE_BASE_FEMALE: float = 0.5859375
"""Baseline serum creatinine (mg/dL) for females: JCCLS Cre_F center
0.625 × E[reserve] 0.9375 = 0.5859375."""

CREATININE_LOW_RENAL_THRESHOLD: float = 0.5
"""``renal_function`` at or below which the "low-renal slope"
creatinine branch fires."""

CREATININE_LOW_RENAL_SLOPE: float = 6.5
"""Slope of the creatinine-vs-renal function for renal < 0.5:
``Cr = base_cr / 0.5 + (0.5 - renal) * 6.5``.

BNP-pattern surgical calibration (2026-06-22): 6.5 lands severe AKI
(renal ≈ 0) at Cr ~5 and CKD3 (renal ≈ 0.3) at Cr ~3 — matches
KDIGO staging. The earlier coefficient of 15 mapped state.renal=0 to
Cr ~9 (ESRD/dialysis-level), inconsistent with typical AKI admission
values."""


# ---------------------------------------------------------------------------
# BUN — inverse renal + volume-lift
# ---------------------------------------------------------------------------

BUN_BASE_MG_DL: float = 15.0
"""Numerator for BUN inverse formula:
``BUN = 15.0 / max(renal, 0.1)``.

15 mg/dL is the healthy adult BUN mid-range (JCCLS 8-20)."""

BUN_RENAL_FLOOR: float = 0.1
"""Minimum ``renal_function`` in the BUN divisor — prevents division-
by-zero and caps BUN at ~150 mg/dL (severe uremia)."""

BUN_VOLUME_LIFT_SCALE: float = 0.5
"""Scale for the dehydration-driven BUN lift:
``BUN *= 1.0 + |volume_status| * 0.5`` when volume is below the
:data:`BUN_ELEVATION_THRESHOLD` from ``dehydration_thresholds.py``.

Empirical tuning for the synthetic simulator: 50% BUN elevation per
unit dehydration matches the classic BUN:Cr ratio > 20:1 pattern
of prerenal AKI."""


# ---------------------------------------------------------------------------
# eGFR — linear from renal
# ---------------------------------------------------------------------------

EGFR_RENAL_SCALE: int = 120
"""eGFR (mL/min/1.73m²) at ``renal_function = 1.0`` — matches the
healthy adult eGFR ceiling (KDIGO stage 1 boundary)."""


# ---------------------------------------------------------------------------
# Potassium — renal + acidosis
# ---------------------------------------------------------------------------

POTASSIUM_BASE_MEQ_L: float = 4.0
"""Baseline serum potassium (mEq/L) at full renal function and
neutral pH — mid-range of the JCCLS 3.5-5.0 reference band."""

POTASSIUM_RENAL_SCALE: float = 2.2
"""mEq/L rise in potassium per unit ``(1 - renal_function)``.

Empirical tuning for the synthetic simulator: renal 1.0 → K 4.0;
renal 0.3 → K 5.4 (moderate hyperkalemia); renal 0.1 → K 6.0
(severe hyperkalemia requiring urgent treatment) — matches the
clinical CKD → hyperkalemia gradient."""

POTASSIUM_ACIDOSIS_SCALE: float = 0.8
"""mEq/L rise in potassium per unit acidosis (negative ph_status):
``K += max(0, -ph) * 0.8``.

Empirical tuning for the synthetic simulator: 0.8 mEq/L per unit
acidosis matches the H+/K+ transcellular shift documented in DKA."""

POTASSIUM_MIN_MEQ_L: float = 2.5
"""Physiological minimum serum potassium (mEq/L) — matches severe
hypokalemia clinical range."""

POTASSIUM_MAX_MEQ_L: float = 8.0
"""Physiological maximum serum potassium (mEq/L) — beyond this,
cardiac arrhythmia dominates and the simulator clamps rather than
modeling the terminal cascade."""


# ---------------------------------------------------------------------------
# Sodium — sodium_status axis + renal penalty
# ---------------------------------------------------------------------------

SODIUM_BASE_MEQ_L: float = 140.0
"""Baseline serum sodium (mEq/L) — mid-range of the 135-145 healthy
reference band."""

SODIUM_STATUS_SCALE: float = 14.0
"""mEq/L shift in sodium per unit ``sodium_status`` (dysnatremia
axis: negative → hyponatremia, positive → hypernatremia).

Empirical tuning for the synthetic simulator: sodium_status of +1.0
lifts Na to 154 (severe hypernatremia); -1.0 drops Na to 126
(severe hyponatremia) — before the additional renal penalty."""

SODIUM_RENAL_PENALTY: float = 3.0
"""mEq/L reduction in sodium per unit ``(1 - renal_function)`` —
reflects the mild dilutional hyponatremia observed in advanced CKD."""

SODIUM_MIN_MEQ_L: float = 120.0
"""Physiological minimum serum sodium (mEq/L) — matches severe
symptomatic hyponatremia clinical floor."""

SODIUM_MAX_MEQ_L: float = 160.0
"""Physiological maximum serum sodium (mEq/L) — matches severe
symptomatic hypernatremia clinical ceiling."""
