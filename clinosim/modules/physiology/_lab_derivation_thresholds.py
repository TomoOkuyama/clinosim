"""Lab-value derivation formula constants (Issue #637).

Extracts the previously-inline scalars from
:func:`clinosim.modules.physiology.engine.derive_lab_values` per
policy §5. Grown in phases across sub-PRs of C2:

* **C2a** — inflammation (CRP, WBC, PCT, Albumin) + renal
  (Creatinine, BUN, eGFR, K, Na).
* **C2b** — cardiac (BNP, Troponin, CK_MB) + hepatic (AST, ALT,
  T_Bil, PT_INR).
* **C2c** — anemia (Hb, Hct, Plt) + coagulation (APTT, PT,
  Fibrinogen, D-dimer) + perfusion (Lactate).
* **C2d** — blood gas (HCO3, pCO2, pH, pO2) + electrolytes (Cl, Ca)
  + glucose (base + hyperglycemia + hypoglycemia + stress +
  postprandial + clamp) + non-DM HbA1c age term + WBC circadian.

With C2d, the ``derive_lab_values`` extraction is complete.

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
    "CA_BASELINE_MG_DL",
    "CA_CLAMP_MAX",
    "CA_CLAMP_MIN",
    "CA_HEPATIC_SCALE",
    "CA_INFLAMMATION_SCALE",
    "CA_RENAL_SCALE",
    "CA_SODIUM_LIFT",
    "CL_BASELINE_MEQ_L",
    "CL_CLAMP_MAX",
    "CL_CLAMP_MIN",
    "CL_HCO3_DEFICIT_REFERENCE",
    "CL_NON_AG_FRACTION_MAX",
    "CL_SODIUM_LINKAGE_SCALE",
    "GLU_CLAMP_MAX",
    "GLU_CLAMP_MIN",
    "GLU_HYPERGLYCEMIA_SCALE",
    "GLU_HYPOGLYCEMIA_SCALE",
    "GLU_NONDM_BASELINE_MG_DL",
    "GLU_POSTPRANDIAL_BREAKFAST_HOUR_MAX",
    "GLU_POSTPRANDIAL_BREAKFAST_HOUR_MIN",
    "GLU_POSTPRANDIAL_BREAKFAST_LIFT",
    "GLU_POSTPRANDIAL_DINNER_HOUR_MAX",
    "GLU_POSTPRANDIAL_DINNER_HOUR_MIN",
    "GLU_POSTPRANDIAL_DINNER_LIFT",
    "GLU_POSTPRANDIAL_LUNCH_HOUR_MAX",
    "GLU_POSTPRANDIAL_LUNCH_HOUR_MIN",
    "GLU_POSTPRANDIAL_LUNCH_LIFT",
    "GLU_STRESS_INFLAMMATION_LIFT",
    "HBA1C_NONDM_AGE_MIN",
    "HBA1C_NONDM_AGE_SCALE_LAB",
    "HCO3_BASELINE_MEQ_L",
    "HCO3_CLAMP_MAX",
    "HCO3_CLAMP_MIN",
    "HCO3_METABOLIC_GAIN",
    "HCO3_RENAL_COMPENSATION_RATIO",
    "PCO2_BASELINE_MMHG",
    "PCO2_CLAMP_MAX",
    "PCO2_CLAMP_MIN",
    "PCO2_RESPIRATORY_GAIN",
    "PCO2_WINTERS_COMPENSATION_RATIO",
    "PCO2_WINTERS_HCO3_COEFF",
    "PCO2_WINTERS_INTERCEPT",
    "PH_CLAMP_MAX",
    "PH_CLAMP_MIN",
    "PH_HENDERSON_HASSELBALCH_CONSTANT",
    "PH_HENDERSON_PCO2_COEFF",
    "PO2_BASELINE_MMHG",
    "PO2_CLAMP_MAX",
    "PO2_CLAMP_MIN",
    "PO2_INFLAMMATION_SCALE",
    "WBC_CIRCADIAN_AMPLITUDE",
    "WBC_CIRCADIAN_HOUR_OFFSET",
    "WBC_CIRCADIAN_HOUR_PERIOD",
    "APTT_BASELINE_SEC",
    "APTT_COAGULATION_SCALE",
    "APTT_PHYSIOLOGIC_MAX_SEC",
    "APTT_PHYSIOLOGIC_MIN_SEC",
    "D_DIMER_AGE_ADJUST_MIN_AGE",
    "D_DIMER_AGE_ADJUST_SCALE",
    "D_DIMER_BASELINE",
    "D_DIMER_COAGULATION_SCALE",
    "D_DIMER_INFLAMMATION_SCALE",
    "D_DIMER_PHYSIOLOGIC_MAX",
    "D_DIMER_PHYSIOLOGIC_MIN",
    "D_DIMER_VTE_LIFT",
    "FIBRINOGEN_BASELINE_MG_DL",
    "FIBRINOGEN_COAGULATION_CONSUMPTION_SCALE",
    "FIBRINOGEN_INFLAMMATION_SCALE",
    "FIBRINOGEN_PHYSIOLOGIC_MAX",
    "FIBRINOGEN_PHYSIOLOGIC_MIN",
    "HB_ANEMIA_SCALE",
    "HB_BASELINE_FEMALE_G_DL",
    "HB_BASELINE_MALE_G_DL",
    "HB_FLOOR_G_DL",
    "HCT_HB_RATIO",
    "LACTATE_BASELINE_MMOL_L",
    "LACTATE_PERFUSION_SCALE",
    "PLT_BASELINE",
    "PLT_COAGULATION_SCALE",
    "PLT_FLOOR",
    "PT_ISI_FALLBACK_NORMAL_SEC",
    "PT_PHYSIOLOGIC_MAX_SEC",
    "PT_PHYSIOLOGIC_MIN_SEC",
    "ALT_BASELINE_U_L",
    "ALT_HEPATIC_SCALE",
    "AST_BASELINE_U_L",
    "AST_HEPATIC_SCALE",
    "BNP_BASELINE_PG_ML",
    "BNP_CARDIAC_EXP_SCALE",
    "BNP_VOLUME_CARDIAC_EXP_SCALE",
    "CK_MB_ACS_INJURY_SQ_SCALE",
    "CK_MB_BASELINE_NG_ML",
    "CK_MB_TYPE2_CAP",
    "CK_MB_TYPE2_INJURY_CUBE_SCALE",
    "PT_INR_BASELINE",
    "PT_INR_COAGULATION_SCALE",
    "PT_INR_HEPATIC_SCALE",
    "PT_INR_WARFARIN_BASE_GAIN",
    "PT_INR_WARFARIN_TARGET_CENTER",
    "TROPONIN_ACS_INJURY_SQ_SCALE",
    "TROPONIN_BASELINE_NG_ML",
    "TROPONIN_RENAL_LIFT_SCALE",
    "TROPONIN_TYPE2_CAP",
    "TROPONIN_TYPE2_INJURY_CUBE_SCALE",
    "T_BIL_BASELINE_MG_DL",
    "T_BIL_HEPATIC_SCALE",
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


# ---------------------------------------------------------------------------
# BNP — cardiac + volume-cardiac exponential model
# ---------------------------------------------------------------------------

BNP_BASELINE_PG_ML: float = 15.0
"""Baseline BNP (pg/mL) at ``cardiac_function == 1.0`` and no volume
overload.

Issue #430 calibration (down from prior 30.0): 15 pg/mL centers healthy
volunteers within the JP JCCLS reference range (M < 18.4, F < 22.9).
Prior 30.0 exceeded the healthy upper bound at cardiac=1.0, forcing
healthy patients into a systematically elevated BNP."""

BNP_CARDIAC_EXP_SCALE: float = 2.0
"""Exponent scale for cardiac-dysfunction contribution:
``BNP = base * exp((1 - cardiac) * scale + volume_term)``.

Empirical tuning for the synthetic simulator: 2.0 places uncomplicated
MI (cardiac ~0.19) at BNP ~75 pg/mL (below HF rule-out 100)."""

BNP_VOLUME_CARDIAC_EXP_SCALE: float = 5.0
"""Exponent scale for the volume-cardiac coupled term:
``+ max(0, volume) * (1 - cardiac) * scale``.

Empirical tuning for the synthetic simulator: 5.0 places HF
exacerbation (cardiac ~0.27, volume ~0.56) at BNP ~500 pg/mL
(moderate HF band). Non-cardiac fluid overload in a preserved heart
stays low because the term is gated by cardiac dysfunction."""


# ---------------------------------------------------------------------------
# Troponin_I — type-2 (mild) + ACS (primary necrosis) branches
# ---------------------------------------------------------------------------

TROPONIN_BASELINE_NG_ML: float = 0.01
"""Baseline serum troponin I (ng/mL) at zero cardiac injury — well
below the ACS rule-out (0.04 ng/mL) and matching healthy reference."""

TROPONIN_TYPE2_INJURY_CUBE_SCALE: float = 8.0
"""Cubic scale for type-2 (demand-ischemia) troponin elevation:
``tnt += min(injury**3 * 8.0, cap)``.

Empirical tuning for the synthetic simulator: cubic gain restricts
elevation to meaningful dysfunction only (~cardiac < 0.6 starts
lifting), matching type-2 MI clinical patterns."""

TROPONIN_TYPE2_CAP: float = 3.0
"""Cap on type-2 troponin elevation (ng/mL).

Empirical tuning for the synthetic simulator: 3.0 ng/mL is the upper
end of the "mild elevation" band typical of non-necrosis dysfunction
(sepsis, PE, AF, stroke). ACS elevations must go through the primary-
necrosis branch below."""

TROPONIN_RENAL_LIFT_SCALE: float = 0.10
"""Additional troponin (ng/mL per unit ``(1 - renal_function)``)
reflecting reduced renal clearance in CKD — chronic mild elevation
that clinicians recognize as a CKD confounder."""

TROPONIN_ACS_INJURY_SQ_SCALE: float = 120.0
"""Squared scale for ACS primary-necrosis troponin release, applied
only when the scenario flag ``myocardial_injury`` is set:
``tnt += injury**2 * 120.0``.

Empirical tuning for the synthetic simulator: 120 lands ACS troponin
in the clinical 10-100 ng/mL band for cardiac dysfunction in the
0.3-0.5 range."""


# ---------------------------------------------------------------------------
# CK_MB — mirrors the troponin pattern (type-2 + ACS)
# ---------------------------------------------------------------------------

CK_MB_BASELINE_NG_ML: float = 0.5
"""Baseline CK-MB (ng/mL) at zero cardiac injury — below the normal-
range upper bound (5 ng/mL)."""

CK_MB_TYPE2_INJURY_CUBE_SCALE: float = 5.0
"""Cubic scale for type-2 CK-MB elevation (matches
:data:`TROPONIN_TYPE2_INJURY_CUBE_SCALE` pattern with different
magnitude)."""

CK_MB_TYPE2_CAP: float = 3.0
"""Cap on type-2 CK-MB elevation (ng/mL)."""

CK_MB_ACS_INJURY_SQ_SCALE: float = 60.0
"""Squared scale for ACS primary-necrosis CK-MB release (matches
:data:`TROPONIN_ACS_INJURY_SQ_SCALE` pattern at half the magnitude —
consistent with the CK-MB-to-troponin ratio in acute MI)."""


# ---------------------------------------------------------------------------
# Hepatic panel — AST + ALT + T_Bil
# ---------------------------------------------------------------------------

AST_BASELINE_U_L: int = 25
"""Baseline AST (U/L) at full hepatic function — mid-range of the
JCCLS healthy adult reference (10-40)."""

AST_HEPATIC_SCALE: int = 500
"""AST elevation (U/L per unit ``(1 - hepatic_function)``) —
peak ~525 U/L at hepatic=0 matches the acute-hepatitis / severe-
liver-injury clinical range."""

ALT_BASELINE_U_L: int = 20
"""Baseline ALT (U/L) at full hepatic function — mid-range of the
JCCLS healthy adult reference (7-45)."""

ALT_HEPATIC_SCALE: int = 400
"""ALT elevation (U/L per unit ``(1 - hepatic_function)``) — slightly
lower ceiling than AST reflecting the observed AST:ALT ratio > 1 in
severe liver injury."""

T_BIL_BASELINE_MG_DL: float = 0.8
"""Baseline total bilirubin (mg/dL) at full hepatic function —
mid-range of the JCCLS healthy adult reference (0.3-1.2)."""

T_BIL_HEPATIC_SCALE: int = 15
"""Total bilirubin elevation (mg/dL per unit ``(1 - hepatic_function)``)
— peak ~15.8 mg/dL at hepatic=0 matches decompensated cirrhosis /
severe cholestasis."""


# ---------------------------------------------------------------------------
# PT_INR — hepatic + coagulation + warfarin therapeutic overlay
# ---------------------------------------------------------------------------

PT_INR_BASELINE: float = 1.0
"""Baseline PT-INR at full hepatic function and no coagulation
disturbance — matches the healthy reference."""

PT_INR_HEPATIC_SCALE: float = 2.0
"""INR elevation per unit ``(1 - hepatic_function)`` — reflects
depletion of vitamin-K-dependent clotting factors in cirrhosis /
acute liver failure."""

PT_INR_COAGULATION_SCALE: float = 1.5
"""INR elevation per unit ``coagulation_status`` — reflects DIC-driven
consumptive coagulopathy."""

PT_INR_WARFARIN_TARGET_CENTER: float = 2.5
"""Therapeutic INR target center for warfarin patients — mid-range of
the clinical 2.0-3.0 band for most indications (atrial fibrillation,
mechanical valve exceptions handled elsewhere)."""

PT_INR_WARFARIN_BASE_GAIN: float = 0.5
"""Gain factor applied to the base-INR perturbation for warfarin
patients: ``INR = 2.5 + (base_inr - 1.0) * 0.5``.

Empirical tuning for the synthetic simulator: 0.5 halves the
comorbidity-driven perturbation on top of the therapeutic center —
reflects that anticoagulation is titrated to keep INR in the
therapeutic range even in patients with concurrent hepatic /
coagulation issues, but not perfectly."""


# ---------------------------------------------------------------------------
# Anemia panel — Hb + Hct + Plt
# ---------------------------------------------------------------------------

HB_BASELINE_MALE_G_DL: float = 15.0
"""Baseline hemoglobin (g/dL) for adult males — mid-range of the
WHO / JCCLS healthy adult reference (13-17)."""

HB_BASELINE_FEMALE_G_DL: float = 13.0
"""Baseline hemoglobin (g/dL) for adult females — mid-range of the
WHO / JCCLS healthy adult reference (12-15)."""

HB_ANEMIA_SCALE: float = 0.7
"""Multiplicative scale on ``(1 - anemia_level * 0.7)`` — at
``anemia_level = 1.0``, Hb drops to 30% of baseline (~4.5 g/dL M /
~3.9 g/dL F), matching severe anemia clinical ranges."""

HB_FLOOR_G_DL: float = 3.0
"""Physiologic minimum hemoglobin (g/dL) — matches the transfusion-
imminent clinical floor."""

HCT_HB_RATIO: float = 3.0
"""Hematocrit-to-hemoglobin ratio (Hct % = Hb g/dL × 3.0).

Empirical clinical rule (roughly Hb × 3 ≈ Hct % over the normal
physiologic range) — matches the bedside-conversion convention used
by clinicians."""

PLT_BASELINE: int = 250
"""Baseline platelet count (×10³/μL) — mid-range of the JCCLS
healthy adult reference (150-350)."""

PLT_COAGULATION_SCALE: int = 200
"""Platelet consumption per unit ``coagulation_status``.

Empirical tuning for the synthetic simulator: at coagulation_status
= 1.0 (full DIC), Plt drops to ~50 (severe thrombocytopenia), matching
the DIC clinical range."""

PLT_FLOOR: int = 20
"""Physiologic minimum platelet count (×10³/μL) — critical
thrombocytopenia floor requiring urgent transfusion."""


# ---------------------------------------------------------------------------
# Coagulation panel — APTT + PT + Fibrinogen + D-dimer
# ---------------------------------------------------------------------------

APTT_BASELINE_SEC: float = 30.0
"""Baseline APTT (seconds) at zero coagulation disturbance — mid-range
of the healthy adult reference (25-35 sec)."""

APTT_COAGULATION_SCALE: float = 55.0
"""APTT prolongation (seconds) per unit ``coagulation_status``.

Empirical tuning for the synthetic simulator: at coagulation_status
= 1.0 (full DIC), APTT rises to 85 sec (severe intrinsic-pathway
disturbance), matching the DIC 60-100+ sec clinical range."""

APTT_PHYSIOLOGIC_MIN_SEC: float = 20.0
"""Physiologic minimum APTT (seconds) — matches the hypercoagulability
floor observed in some inflammatory states."""

APTT_PHYSIOLOGIC_MAX_SEC: float = 150.0
"""Physiologic maximum APTT (seconds) — beyond this, samples are
typically reported as "unclottable" clinically."""

PT_ISI_FALLBACK_NORMAL_SEC: float = 12.0
"""Reference normal-PT (seconds) with ISI ≈ 1.0.

PT is derived from PT_INR via ``PT ≈ 12 * PT_INR`` — the standard
laboratory relationship (INR = (PT / normal_PT)^ISI). Chosen for
consistency: PT and PT_INR then never numerically disagree."""

PT_PHYSIOLOGIC_MIN_SEC: float = 9.0
"""Physiologic minimum PT (seconds) — matches the hypercoagulability
floor and healthy adult reference lower bound."""

PT_PHYSIOLOGIC_MAX_SEC: float = 90.0
"""Physiologic maximum PT (seconds) — samples beyond this are
typically reported as "unclottable" clinically."""

FIBRINOGEN_BASELINE_MG_DL: float = 300.0
"""Baseline fibrinogen (mg/dL) at zero inflammation and no DIC
consumption — mid-range of the healthy adult reference (200-400)."""

FIBRINOGEN_INFLAMMATION_SCALE: float = 250.0
"""Fibrinogen acute-phase lift per unit inflammation.

Empirical tuning for the synthetic simulator: at inflammation = 1.0,
fibrinogen rises to ~550 mg/dL — matches the sepsis-without-DIC
acute-phase clinical pattern."""

FIBRINOGEN_COAGULATION_CONSUMPTION_SCALE: float = 280.0
"""Fibrinogen consumption per unit ``coagulation_status`` (DIC).

Empirical tuning for the synthetic simulator: at full inflammation
(+250) AND full DIC (-280), net = 270 mg/dL (below the
DIC-trending 350 mg/dL clinical alarm), matching the clinical
"fibrinogen falling despite acute-phase surge" DIC signal."""

FIBRINOGEN_PHYSIOLOGIC_MIN: float = 50.0
"""Physiologic minimum fibrinogen (mg/dL) — laboratory detection
floor; clinically < 100 indicates severe consumptive coagulopathy."""

FIBRINOGEN_PHYSIOLOGIC_MAX: float = 800.0
"""Physiologic maximum fibrinogen (mg/dL) — beyond acute-phase
expectations in severe inflammation."""

D_DIMER_BASELINE: float = 0.3
"""Baseline D-dimer (ug/mL FEU) at zero contributing factors — matches
the healthy young-adult reference lower bound."""

D_DIMER_AGE_ADJUST_MIN_AGE: int = 50
"""Minimum patient age at which the age-adjusted D-dimer term begins
contributing.

The age-adjusted formula ``+0.005/year above 50`` is a well-documented
D-dimer aging convention (baseline drifts upward ~0.05 ug/mL per
decade past 50)."""

D_DIMER_AGE_ADJUST_SCALE: float = 0.005
"""Age-scaling of the D-dimer age-adjust term (ug/mL per year past
:data:`D_DIMER_AGE_ADJUST_MIN_AGE`)."""

D_DIMER_INFLAMMATION_SCALE: float = 0.5
"""D-dimer inflammation contribution (ug/mL per unit inflammation) —
modest, non-VTE-specific lift matching sepsis / non-VTE inflammation
patterns."""

D_DIMER_COAGULATION_SCALE: float = 1.5
"""D-dimer contribution per unit ``coagulation_status`` (DIC /
fibrinolysis) — larger than the inflammation contribution."""

D_DIMER_VTE_LIFT: float = 4.0
"""D-dimer lift (ug/mL) applied when ``causes_vte`` scenario flag is
set (PE / DVT / embolic stroke).

Empirical tuning for the synthetic simulator: 4.0 ug/mL pushes
D-dimer to the clinically-positive 5-20 ug/mL band for VTE cases
after inflammation + coagulation contributions."""

D_DIMER_PHYSIOLOGIC_MIN: float = 0.15
"""Physiologic minimum D-dimer (ug/mL) — laboratory detection floor."""

D_DIMER_PHYSIOLOGIC_MAX: float = 20.0
"""Physiologic maximum D-dimer (ug/mL) — assay upper limit; values
higher are typically reported as ">20"."""


# ---------------------------------------------------------------------------
# Perfusion — Lactate
# ---------------------------------------------------------------------------

LACTATE_BASELINE_MMOL_L: float = 1.0
"""Baseline lactate (mmol/L) at full perfusion — matches the healthy
adult reference upper bound (< 2.0)."""

LACTATE_PERFUSION_SCALE: int = 12
"""Lactate lift (mmol/L per unit ``(1 - perfusion_status)``).

Empirical tuning for the synthetic simulator: at perfusion_status
= 0, lactate rises to 13 mmol/L (extreme lactic acidosis / shock),
matching the septic-shock / cardiogenic-shock clinical range."""


# ---------------------------------------------------------------------------
# Blood gas — HCO3 + pCO2 + pH + pO2 (two-axis Henderson-Hasselbalch)
# ---------------------------------------------------------------------------

HCO3_BASELINE_MEQ_L: float = 24.0
"""Baseline serum HCO3 (mEq/L) at zero acid-base disturbance — matches
the healthy reference (22-26)."""

HCO3_METABOLIC_GAIN: float = 31.0
"""Metabolic-axis gain: HCO3 = 24 + ph_status * metabolic_fraction * 31.

BNP-pattern surgical calibration (2026-06-22): 31 lands moderate DKA
(ph_status=-0.35) at HCO3 ~13 (ADA moderate mid-band) and severe DKA
at <10; CKD chronic (ph_status~-0.10) drops only from 21.6 to 20.9.
Prior gain 24 left DKA-moderate at HCO3 ~15.6, outside the ADA band."""

HCO3_CLAMP_MIN: float = 5.0
"""Physiologic minimum HCO3 (mEq/L) — matches severe DKA / uremic
acidosis floor."""

HCO3_CLAMP_MAX: float = 45.0
"""Physiologic maximum HCO3 (mEq/L) — matches severe chronic-respiratory
compensation ceiling (COPD retainer)."""

PCO2_BASELINE_MMHG: float = 40.0
"""Baseline arterial pCO2 (mmHg) at zero acid-base disturbance —
matches the healthy reference (35-45)."""

PCO2_RESPIRATORY_GAIN: float = 40.0
"""Respiratory-axis gain: pCO2 = 40 - ph_status * respiratory_fraction * 40.

Empirical tuning for the synthetic simulator: at ph_status=-1.0 (extreme
respiratory acidosis) on the respiratory axis, pCO2 = 40 + 40 = 80
mmHg (severe CO2 retention)."""

PCO2_WINTERS_HCO3_COEFF: float = 1.5
"""Winter's formula HCO3 coefficient: expected pCO2 = 1.5 * HCO3 + 8.

Standard clinical formula for calculating the expected respiratory
compensation to metabolic acidosis."""

PCO2_WINTERS_INTERCEPT: float = 8.0
"""Winter's formula intercept (see :data:`PCO2_WINTERS_HCO3_COEFF`)."""

PCO2_WINTERS_COMPENSATION_RATIO: float = 0.8
"""Ratio of the ~full Winters' compensation actually applied to pCO2.

Empirical tuning for the synthetic simulator: 0.8 (~80% of ideal
compensation) reflects that real-world compensation is imperfect,
so the model doesn't produce textbook-perfect Winters formula results."""

HCO3_RENAL_COMPENSATION_RATIO: float = 0.35
"""Renal (metabolic) compensation ratio for a respiratory disturbance:
HCO3 += 0.35 * (pCO2 - 40).

Standard clinical value (~0.35 mEq/mmHg for chronic respiratory
disturbance)."""

PCO2_CLAMP_MIN: float = 15.0
"""Physiologic minimum pCO2 (mmHg) — matches severe hyperventilation
floor (compensated metabolic acidosis)."""

PCO2_CLAMP_MAX: float = 90.0
"""Physiologic maximum pCO2 (mmHg) — matches severe hypoventilation
ceiling."""

PH_HENDERSON_HASSELBALCH_CONSTANT: float = 6.1
"""Henderson-Hasselbalch pKa constant for the bicarbonate buffer
system: pH = 6.1 + log10(HCO3 / (0.03 * pCO2))."""

PH_HENDERSON_PCO2_COEFF: float = 0.03
"""Henderson-Hasselbalch pCO2 coefficient (converts pCO2 mmHg to
carbonic acid mEq/L via the CO2 solubility factor)."""

PH_CLAMP_MIN: float = 6.80
"""Physiologic minimum pH — matches severe acidemia lower bound."""

PH_CLAMP_MAX: float = 7.70
"""Physiologic maximum pH — matches severe alkalemia upper bound."""

PO2_BASELINE_MMHG: float = 95.0
"""Baseline arterial pO2 (mmHg) at zero pulmonary involvement —
matches healthy young-adult resting sea-level."""

PO2_INFLAMMATION_SCALE: float = 45.0
"""pO2 drop (mmHg per unit inflammation) — reflects pulmonary
involvement (inflammation as a lung-injury proxy until a dedicated
respiratory/oxygenation state variable exists)."""

PO2_CLAMP_MIN: float = 45.0
"""Physiologic minimum pO2 (mmHg) — matches severe hypoxemia floor
before mechanical ventilation is initiated."""

PO2_CLAMP_MAX: float = 105.0
"""Physiologic maximum pO2 (mmHg) — matches supplemental-O2-boosted
ceiling in ambient conditions."""


# ---------------------------------------------------------------------------
# Electrolytes — Cl (BMP anion gap) + Ca (total)
# ---------------------------------------------------------------------------

CL_BASELINE_MEQ_L: float = 103.0
"""Baseline serum chloride (mEq/L) — matches healthy reference (98-107)."""

CL_SODIUM_LINKAGE_SCALE: float = 9.0
"""Cl shift per unit ``sodium_status`` — electroneutrality linkage
between Na and Cl."""

CL_HCO3_DEFICIT_REFERENCE: float = 24.0
"""HCO3 reference used to compute the deficit term:
``hco3_deficit = max(0, 24 - labs["HCO3"])`` — matches
:data:`HCO3_BASELINE_MEQ_L`."""

CL_NON_AG_FRACTION_MAX: float = 1.5
"""Maximum non-anion-gap fraction clamp: ``clamp(1 - anion_gap_status,
0, 1.5)``.

The 1.5 upper bound allows the non-AG absorption to slightly exceed
the ideal 1:1 for cases where the axis dips below zero (hypochloremic
alkalosis compensation)."""

CL_CLAMP_MIN: float = 80.0
"""Physiologic minimum serum Cl (mEq/L)."""

CL_CLAMP_MAX: float = 125.0
"""Physiologic maximum serum Cl (mEq/L) — hyperchloremic acidosis
ceiling."""

CA_BASELINE_MG_DL: float = 9.5
"""Baseline total serum calcium (mg/dL) — mid-range of healthy adult
reference (8.5-10.5)."""

CA_INFLAMMATION_SCALE: float = 0.8
"""Ca drop (mg/dL per unit inflammation) — reflects sepsis-associated
hypocalcemia."""

CA_RENAL_SCALE: float = 0.7
"""Ca drop (mg/dL per unit ``(1 - renal_function)``) — reflects CKD-
associated hypocalcemia (impaired 1,25-D synthesis)."""

CA_HEPATIC_SCALE: float = 0.4
"""Ca drop (mg/dL per unit ``(1 - hepatic_function)``) — reflects
liver-failure hypocalcemia (impaired albumin synthesis → reduced
protein-bound Ca fraction)."""

CA_SODIUM_LIFT: float = 0.3
"""Ca lift (mg/dL per unit ``sodium_status``) — mild dehydration
concentrates serum Ca."""

CA_CLAMP_MIN: float = 5.5
"""Physiologic minimum serum Ca (mg/dL) — matches severe symptomatic
hypocalcemia floor (tetany, seizures)."""

CA_CLAMP_MAX: float = 13.0
"""Physiologic maximum serum Ca (mg/dL) — matches severe hypercalcemia
ceiling."""


# ---------------------------------------------------------------------------
# Glucose (inline scalars — module-level GLU_DM_* / GLYCEMIC_CONTROL_DEFAULT
# stay in engine.py because they are consumed by other modules via re-import)
# ---------------------------------------------------------------------------

GLU_NONDM_BASELINE_MG_DL: float = 95.0
"""Non-diabetic fasting glucose baseline (mg/dL) — mid-range of healthy
adult fasting reference (70-99, ADA prediabetes cutoff 100)."""

GLU_HYPERGLYCEMIA_SCALE: float = 500.0
"""Glucose lift per unit positive ``glucose_status``.

Empirical tuning for the synthetic simulator: glucose_status = 0.6
gives +300 mg/dL, matching the DKA 300-500 mg/dL clinical range."""

GLU_HYPOGLYCEMIA_SCALE: float = 55.0
"""Glucose drop per unit negative ``glucose_status``.

Empirical tuning for the synthetic simulator: glucose_status = -0.5
gives -27 mg/dL, matching insulin-therapy-induced hypoglycemia."""

GLU_STRESS_INFLAMMATION_LIFT: int = 50
"""Glucose lift (mg/dL per unit inflammation) — stress-hyperglycemia
from cortisol / catecholamine surge."""

GLU_POSTPRANDIAL_BREAKFAST_LIFT: float = 25.0
"""Post-breakfast glucose lift (mg/dL, ~1-2 h post-meal peak)."""

GLU_POSTPRANDIAL_LUNCH_LIFT: float = 20.0
"""Post-lunch glucose lift (mg/dL)."""

GLU_POSTPRANDIAL_DINNER_LIFT: float = 20.0
"""Post-dinner glucose lift (mg/dL) — same magnitude as lunch."""

GLU_POSTPRANDIAL_BREAKFAST_HOUR_MIN: int = 9
"""First hour of the post-breakfast peak window (inclusive)."""

GLU_POSTPRANDIAL_BREAKFAST_HOUR_MAX: int = 10
"""Last hour of the post-breakfast peak window (inclusive)."""

GLU_POSTPRANDIAL_LUNCH_HOUR_MIN: int = 13
"""First hour of the post-lunch peak window (inclusive)."""

GLU_POSTPRANDIAL_LUNCH_HOUR_MAX: int = 14
"""Last hour of the post-lunch peak window (inclusive)."""

GLU_POSTPRANDIAL_DINNER_HOUR_MIN: int = 19
"""First hour of the post-dinner peak window (inclusive)."""

GLU_POSTPRANDIAL_DINNER_HOUR_MAX: int = 20
"""Last hour of the post-dinner peak window (inclusive)."""

GLU_CLAMP_MIN: float = 40.0
"""Physiologic minimum serum glucose (mg/dL) — matches severe
hypoglycemia floor requiring urgent D50 infusion."""

GLU_CLAMP_MAX: float = 1200.0
"""Physiologic maximum serum glucose (mg/dL) — matches severe HHS /
DKA ceiling before hyperosmolar coma."""


# ---------------------------------------------------------------------------
# HbA1c non-diabetic age term
# ---------------------------------------------------------------------------

HBA1C_NONDM_AGE_MIN: int = 40
"""Age (years) above which the age-dependent non-DM HbA1c drift
begins."""

HBA1C_NONDM_AGE_SCALE_LAB: float = 0.003
"""HbA1c drift (%/year) past :data:`HBA1C_NONDM_AGE_MIN` for
non-diabetic patients.

Consistent with the age-dependent HbA1c drift documented in
population studies (~0.03 %/decade). Named ``_LAB`` to disambiguate
from the ``HBA1C_NONDM_AGE_SCALE`` in ``health_checkup/_checkup_thresholds.py``
(same numeric value, distinct semantic scope)."""


# ---------------------------------------------------------------------------
# WBC diurnal variation
# ---------------------------------------------------------------------------

WBC_CIRCADIAN_AMPLITUDE: float = 0.10
"""Amplitude of the diurnal WBC variation (fractional multiplier).

Empirical tuning for the synthetic simulator: ±10% around the mean
matches the observed WBC circadian pattern (nadir ~04:00, peak
~16:00)."""

WBC_CIRCADIAN_HOUR_OFFSET: int = 4
"""Hour of the day used as the cosine offset — places WBC nadir at
04:00."""

WBC_CIRCADIAN_HOUR_PERIOD: int = 12
"""Hour period used as the divisor in the circadian cosine (12-hour
period matches the diurnal cycle)."""
