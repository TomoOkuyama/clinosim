"""Physiology engine — state variables, coupling rules, lab/vital derivation.

This is the core realism engine. All observable clinical data (lab values, vital signs)
are derived from the hidden physiological state, not generated independently.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np

from clinosim.modules.physiology._coupling_coefficients import (
    AFIB_CARDIAC_COUPLING,
    ASTHMA_PH_COUPLING,
    CIRRHOSIS_COAGULATION_COUPLING,
    CIRRHOSIS_HEPATIC_COUPLING,
    CIRRHOSIS_SODIUM_COUPLING,
    CKD_RENAL_COUPLING,
    CKD_SEVERE_ANEMIA_BUMP,
    CKD_SEVERE_PH_COUPLING,
    CKD_SEVERE_THRESHOLD,
    COPD_PH_COUPLING,
    HF_CARDIAC_COUPLING,
    HF_SEVERE_THRESHOLD,
    HF_SEVERE_VOLUME_COUPLING,
    HF_SODIUM_COUPLING,
    IHD_CARDIAC_COUPLING,
)
from clinosim.modules.physiology._lab_derivation_thresholds import (
    ALBUMIN_BASELINE,
    ALBUMIN_FLOOR,
    ALBUMIN_HEPATIC_SCALE,
    ALBUMIN_INFLAMMATION_SCALE,
    ALT_BASELINE_U_L,
    ALT_HEPATIC_SCALE,
    APTT_BASELINE_SEC,
    APTT_COAGULATION_SCALE,
    APTT_PHYSIOLOGIC_MAX_SEC,
    APTT_PHYSIOLOGIC_MIN_SEC,
    AST_BASELINE_U_L,
    AST_HEPATIC_SCALE,
    BNP_BASELINE_PG_ML,
    BNP_CARDIAC_EXP_SCALE,
    BNP_VOLUME_CARDIAC_EXP_SCALE,
    BUN_BASE_MG_DL,
    BUN_RENAL_FLOOR,
    BUN_VOLUME_LIFT_SCALE,
    CA_BASELINE_MG_DL,
    CA_CLAMP_MAX,
    CA_CLAMP_MIN,
    CA_HEPATIC_SCALE,
    CA_INFLAMMATION_SCALE,
    CA_RENAL_SCALE,
    CA_SODIUM_LIFT,
    CK_MB_ACS_INJURY_SQ_SCALE,
    CK_MB_BASELINE_NG_ML,
    CK_MB_TYPE2_CAP,
    CK_MB_TYPE2_INJURY_CUBE_SCALE,
    CL_BASELINE_MEQ_L,
    CL_CLAMP_MAX,
    CL_CLAMP_MIN,
    CL_HCO3_DEFICIT_REFERENCE,
    CL_NON_AG_FRACTION_MAX,
    CL_SODIUM_LINKAGE_SCALE,
    CREATININE_BASE_FEMALE,
    CREATININE_BASE_MALE,
    CREATININE_LOW_RENAL_SLOPE,
    CREATININE_LOW_RENAL_THRESHOLD,
    CRP_BASE_MG_L,
    CRP_INFLAMMATION_SCALE,
    D_DIMER_AGE_ADJUST_MIN_AGE,
    D_DIMER_AGE_ADJUST_SCALE,
    D_DIMER_BASELINE,
    D_DIMER_COAGULATION_SCALE,
    D_DIMER_INFLAMMATION_SCALE,
    D_DIMER_PHYSIOLOGIC_MAX,
    D_DIMER_PHYSIOLOGIC_MIN,
    D_DIMER_VTE_LIFT,
    EGFR_RENAL_SCALE,
    FIBRINOGEN_BASELINE_MG_DL,
    FIBRINOGEN_COAGULATION_CONSUMPTION_SCALE,
    FIBRINOGEN_INFLAMMATION_SCALE,
    FIBRINOGEN_PHYSIOLOGIC_MAX,
    FIBRINOGEN_PHYSIOLOGIC_MIN,
    GLU_CLAMP_MAX,
    GLU_CLAMP_MIN,
    GLU_HYPERGLYCEMIA_SCALE,
    GLU_HYPOGLYCEMIA_SCALE,
    GLU_NONDM_BASELINE_MG_DL,
    GLU_POSTPRANDIAL_BREAKFAST_HOUR_MAX,
    GLU_POSTPRANDIAL_BREAKFAST_HOUR_MIN,
    GLU_POSTPRANDIAL_BREAKFAST_LIFT,
    GLU_POSTPRANDIAL_DINNER_HOUR_MAX,
    GLU_POSTPRANDIAL_DINNER_HOUR_MIN,
    GLU_POSTPRANDIAL_DINNER_LIFT,
    GLU_POSTPRANDIAL_LUNCH_HOUR_MAX,
    GLU_POSTPRANDIAL_LUNCH_HOUR_MIN,
    GLU_POSTPRANDIAL_LUNCH_LIFT,
    GLU_STRESS_INFLAMMATION_LIFT,
    HB_ANEMIA_SCALE,
    HB_BASELINE_FEMALE_G_DL,
    HB_BASELINE_MALE_G_DL,
    HB_FLOOR_G_DL,
    HBA1C_NONDM_AGE_MIN,
    HBA1C_NONDM_AGE_SCALE_LAB,
    HCO3_BASELINE_MEQ_L,
    HCO3_CLAMP_MAX,
    HCO3_CLAMP_MIN,
    HCO3_METABOLIC_GAIN,
    HCO3_RENAL_COMPENSATION_RATIO,
    HCT_HB_RATIO,
    LACTATE_BASELINE_MMOL_L,
    LACTATE_PERFUSION_SCALE,
    PCO2_BASELINE_MMHG,
    PCO2_CLAMP_MAX,
    PCO2_CLAMP_MIN,
    PCO2_RESPIRATORY_GAIN,
    PCO2_WINTERS_COMPENSATION_RATIO,
    PCO2_WINTERS_HCO3_COEFF,
    PCO2_WINTERS_INTERCEPT,
    PCT_BASE_NG_ML,
    PCT_INFLAMMATION_EXPONENT_SCALE,
    PH_CLAMP_MAX,
    PH_CLAMP_MIN,
    PH_HENDERSON_HASSELBALCH_CONSTANT,
    PH_HENDERSON_PCO2_COEFF,
    PLT_BASELINE,
    PLT_COAGULATION_SCALE,
    PLT_FLOOR,
    PO2_BASELINE_MMHG,
    PO2_CLAMP_MAX,
    PO2_CLAMP_MIN,
    PO2_INFLAMMATION_SCALE,
    POTASSIUM_ACIDOSIS_SCALE,
    POTASSIUM_BASE_MEQ_L,
    POTASSIUM_MAX_MEQ_L,
    POTASSIUM_MIN_MEQ_L,
    POTASSIUM_RENAL_SCALE,
    PT_INR_BASELINE,
    PT_INR_COAGULATION_SCALE,
    PT_INR_HEPATIC_SCALE,
    PT_INR_WARFARIN_BASE_GAIN,
    PT_INR_WARFARIN_TARGET_CENTER,
    PT_ISI_FALLBACK_NORMAL_SEC,
    PT_PHYSIOLOGIC_MAX_SEC,
    PT_PHYSIOLOGIC_MIN_SEC,
    SODIUM_BASE_MEQ_L,
    SODIUM_MAX_MEQ_L,
    SODIUM_MIN_MEQ_L,
    SODIUM_RENAL_PENALTY,
    SODIUM_STATUS_SCALE,
    T_BIL_BASELINE_MG_DL,
    T_BIL_HEPATIC_SCALE,
    TROPONIN_ACS_INJURY_SQ_SCALE,
    TROPONIN_BASELINE_NG_ML,
    TROPONIN_RENAL_LIFT_SCALE,
    TROPONIN_TYPE2_CAP,
    TROPONIN_TYPE2_INJURY_CUBE_SCALE,
    WBC_BASE,
    WBC_CIRCADIAN_AMPLITUDE,
    WBC_CIRCADIAN_HOUR_OFFSET,
    WBC_CIRCADIAN_HOUR_PERIOD,
    WBC_HIGH_INFLAMMATION_LEUKOPENIA_SCALE,
    WBC_HIGH_INFLAMMATION_THRESHOLD,
    WBC_INFLAMMATION_SCALE,
    WBC_LEUKOPENIA_FLOOR,
)
from clinosim.modules.physiology._state_coupling_thresholds import (
    CARDIAC_FUNCTION_FLOOR,
    COAG_DIC_INFLAMMATION_SCALE,
    COAG_DIC_INFLAMMATION_THRESHOLD,
    COAG_HEPATIC_DYSFUNCTION_SCALE,
    COAG_HEPATIC_DYSFUNCTION_THRESHOLD,
    COUPLING_ANEMIA_ACTIVE_MIN,
    COUPLING_ANEMIA_INFLAMMATION_RESOLVING_THRESHOLD,
    COUPLING_ANEMIA_INFLAMMATION_SCALE,
    COUPLING_ANEMIA_INFLAMMATION_THRESHOLD,
    COUPLING_ANEMIA_RECOVERY_RATE,
    HEPATIC_FUNCTION_FLOOR,
    HYPERNATREMIA_SODIUM_SCALE,
    PERFUSION_CARDIAC_BASE_OFFSET,
    PERFUSION_CARDIAC_SCALE,
    PH_COMBINED_ACID_SCALE,
    PH_LACTIC_ACID_PERFUSION_SCALE,
    PH_LACTIC_ACID_PERFUSION_THRESHOLD,
    PH_RENAL_ACID_RENAL_SCALE,
    PH_RENAL_ACID_RENAL_THRESHOLD,
    PRERENAL_HIT_PERFUSION_SCALE,
    PRERENAL_HIT_PERFUSION_THRESHOLD,
    RENAL_FUNCTION_FLOOR,
    VOLUME_HYPERVOLEMIA_CARDIAC_DYSFUNCTION_THRESHOLD,
    VOLUME_HYPERVOLEMIA_PERFUSION_PENALTY,
    VOLUME_HYPERVOLEMIA_THRESHOLD,
    VOLUME_HYPOVOLEMIA_PERFUSION_SCALE,
    VOLUME_HYPOVOLEMIA_THRESHOLD,
)
from clinosim.modules.physiology._vital_signs_thresholds import (
    BP_DBP_CLAMP_MAX,
    BP_DBP_CLAMP_MIN,
    BP_DBP_DISTRIBUTIVE_RATIO,
    BP_DBP_PERFUSION_SCALE,
    BP_DBP_VOLUME_SCALE,
    BP_SBP_CLAMP_MAX,
    BP_SBP_CLAMP_MIN,
    BP_SBP_PERFUSION_SCALE,
    BP_SBP_VOLUME_SCALE,
    DISTRIBUTIVE_SBP_COEFF,
    DISTRIBUTIVE_THRESHOLD,
    HR_ANEMIA_SCALE,
    HR_CLAMP_MAX,
    HR_CLAMP_MIN,
    HR_FEVER_REFERENCE_TEMP_C,
    HR_PERFUSION_SCALE,
    HR_TEMPERATURE_SCALE,
    OBSERVED_SPO2_CLAMP_MAX,
    OBSERVED_SPO2_CLAMP_MIN,
    OBSERVED_TEMPERATURE_NOISE_SD,
    OBSERVED_VITALS_NOISE_SD_DEFAULT,
    RR_CLAMP_MAX,
    RR_CLAMP_MIN,
    RR_INFLAMMATION_SCALE,
    RR_PH_ACIDOSIS_SCALE,
    RR_VOLUME_OVERLOAD_SCALE,
    RR_VOLUME_OVERLOAD_THRESHOLD,
    SPO2_CLAMP_MAX,
    SPO2_CLAMP_MIN,
    SPO2_INFLAMMATION_SCALE,
    SPO2_INFLAMMATION_THRESHOLD,
    SPO2_VOLUME_OVERLOAD_SCALE,
    SPO2_VOLUME_OVERLOAD_THRESHOLD,
    TEMPERATURE_CIRCADIAN_HOUR_OFFSET,
    TEMPERATURE_CIRCADIAN_HOUR_PERIOD,
    TEMPERATURE_CIRCADIAN_SCALE,
    TEMPERATURE_CLAMP_MAX,
    TEMPERATURE_CLAMP_MIN,
    TEMPERATURE_INFLAMMATION_SCALE,
)
from clinosim.modules.physiology.dehydration_thresholds import (
    BUN_ELEVATION_THRESHOLD,
    HYPERNATREMIA_THRESHOLD,
)
from clinosim.types.clinical import PhysiologicalState, StateChangeDirective
from clinosim.types.patient import BaselineVitals, ChronicCondition, PatientPhysiologicalProfile


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def initialize_state(
    profile: PatientPhysiologicalProfile,
    conditions: list[ChronicCondition],
    patient_id: str = "",
) -> PhysiologicalState:
    """Create initial physiological state from patient profile + chronic conditions."""
    state = PhysiologicalState(patient_id=patient_id)

    # Start from organ reserves
    state.renal_function = profile.renal_reserve
    state.cardiac_function = profile.cardiac_reserve
    state.hepatic_function = profile.hepatic_reserve

    # Chronic condition adjustments (multiplicative)
    for c in conditions:
        s = c.severity_score
        code = c.code.upper()
        if code.startswith("N18"):  # CKD
            state.renal_function *= 1.0 - s * CKD_RENAL_COUPLING
            if s > CKD_SEVERE_THRESHOLD:
                state.anemia_level += CKD_SEVERE_ANEMIA_BUMP
                state.ph_status -= s * CKD_SEVERE_PH_COUPLING
        elif code.startswith("I50"):  # Heart failure
            state.cardiac_function *= 1.0 - s * HF_CARDIAC_COUPLING
            if s > HF_SEVERE_THRESHOLD:
                state.volume_status += s * HF_SEVERE_VOLUME_COUPLING
            state.sodium_status -= s * HF_SODIUM_COUPLING  # dilutional hyponatremia
        elif code.startswith("K74"):  # Cirrhosis
            state.hepatic_function *= 1.0 - s * CIRRHOSIS_HEPATIC_COUPLING
            state.coagulation_status += s * CIRRHOSIS_COAGULATION_COUPLING
            state.sodium_status -= s * CIRRHOSIS_SODIUM_COUPLING  # dilutional hyponatremia
        elif code.startswith("J44"):  # COPD
            state.ph_status -= s * COPD_PH_COUPLING
            state.respiratory_fraction = 1.0  # chronic CO2 retention → respiratory axis
        elif code.startswith("I25"):  # Ischemic heart disease
            state.cardiac_function *= 1.0 - s * IHD_CARDIAC_COUPLING
        elif code.startswith("I48"):  # Atrial fibrillation
            state.cardiac_function *= 1.0 - s * AFIB_CARDIAC_COUPLING
        elif code.startswith("E03"):  # Hypothyroidism
            # Mild baseline bradycardia effect (reflected in vitals)
            pass
        elif code.startswith("J45"):  # Asthma
            state.ph_status -= s * ASTHMA_PH_COUPLING  # mild respiratory effect
            state.respiratory_fraction = 1.0  # bronchospasm → respiratory axis
        elif code.startswith(("E11", "E10")):  # Diabetes — chronic glycemic control axis
            gc = getattr(c, "glycemic_control", None)
            if gc is not None:
                state.glycemic_control = gc

    # Perfusion tracks cardiac
    state.perfusion_status = clamp(
        state.cardiac_function * PERFUSION_CARDIAC_SCALE + PERFUSION_CARDIAC_BASE_OFFSET, 0.0, 1.0
    )

    # Clamp all
    state.renal_function = clamp(state.renal_function, RENAL_FUNCTION_FLOOR, 1.0)
    state.cardiac_function = clamp(state.cardiac_function, CARDIAC_FUNCTION_FLOOR, 1.0)
    state.hepatic_function = clamp(state.hepatic_function, HEPATIC_FUNCTION_FLOOR, 1.0)
    state.sodium_status = clamp(state.sodium_status, -1.0, 1.0)

    return state


# HbA1c model (chronic glycemic control). Coefficients fixed by generation audit.
HBA1C_NONDM_BASE = 5.1  # %, non-diabetic baseline (mild age term added at use site)
HBA1C_BEST = 6.0  # %, diabetic at perfect control (glycemic_control = 1.0)
HBA1C_SPAN = 6.0  # %, added at glycemic_control = 0.0  -> 12.0% worst case
# Diabetic fasting Glucose baseline as a function of glycemic control.
GLU_DM_BEST = 120.0  # mg/dL at glycemic_control = 1.0
GLU_DM_SPAN = 100.0  # mg/dL added at glycemic_control = 0.0 -> 220 worst
GLYCEMIC_CONTROL_DEFAULT = 0.5  # fallback when has_diabetes but axis unset (e.g. new-onset)


def hba1c_from_glycemic_control(glycemic_control: float) -> float:
    """Typical (noise-free) HbA1c % for a diabetic at this chronic control level.

    glycemic_control: 1.0 = excellent, 0.0 = very poor. Coefficients audit-tuned.
    """
    gc = clamp(glycemic_control, 0.0, 1.0)
    return HBA1C_BEST + (1.0 - gc) * HBA1C_SPAN


_ACID_BASE_RESPIRATORY_FRACTION = {"metabolic": 0.0, "mixed": 0.5, "respiratory": 1.0}


def apply_state_delta(state: PhysiologicalState, var: str, delta: float) -> None:
    """Add ``delta`` to ``state.<var>`` in place, clamped to the variable's
    CANONICAL range from ``_variable_range``.

    Single edit point for delta application. Every site that folds a YAML-driven
    impact into physiological state (disease onset, daily update, surgery impacts,
    complication state_impact) MUST route through here — a hardcoded ``max(-1.0,
    min(1.0, ...))`` clamp lets a 0..1 axis (inflammation/renal/cardiac/perfusion/
    hepatic/anemia/coagulation) go negative, which is physiologically invalid and
    distorts downstream lab/coupling derivation. No-op when the attribute is absent.
    """
    current = getattr(state, var, None)
    if current is not None:
        lo, hi = _variable_range(var)
        setattr(state, var, clamp(current + delta, lo, hi))


def apply_disease_onset(
    state: PhysiologicalState,
    severity: str,
    initial_impact: dict[str, dict[str, float]],
    acid_base_type: str = "metabolic",
) -> PhysiologicalState:
    """Apply the initial impact of a disease on physiological state.

    `acid_base_type` (from the disease scenario) routes the scenario's ph_status onto the
    metabolic vs respiratory axis so blood gas / compensation are coherent. The acute
    disturbance dominates the encounter, so it overrides any chronic-condition default.
    """
    impact = initial_impact.get(severity, {})
    for var, delta in impact.items():
        apply_state_delta(state, var, delta)
    if acid_base_type in _ACID_BASE_RESPIRATORY_FRACTION:
        state.respiratory_fraction = _ACID_BASE_RESPIRATORY_FRACTION[acid_base_type]
    apply_coupling_rules(state)
    return state


# ---------------------------------------------------------------------------
# State update (time-stepping)
# ---------------------------------------------------------------------------


def update(
    state: PhysiologicalState,
    directive: StateChangeDirective,
    time_step: timedelta,
) -> PhysiologicalState:
    """Apply state changes proportional to time_step, then coupling rules."""
    scale = time_step.total_seconds() / 86400.0  # fraction of a day

    for variable, daily_delta in directive.changes.items():
        apply_state_delta(state, variable, daily_delta * scale)

    apply_coupling_rules(state)
    state.timestamp += time_step
    return state


# ---------------------------------------------------------------------------
# Coupling rules
# ---------------------------------------------------------------------------


def apply_coupling_rules(state: PhysiologicalState) -> None:
    """Apply physiological coupling between state variables. Order matters."""
    # Perfusion depends on cardiac + volume
    volume_effect = 0.0
    if state.volume_status < VOLUME_HYPOVOLEMIA_THRESHOLD:
        volume_effect = state.volume_status * VOLUME_HYPOVOLEMIA_PERFUSION_SCALE
    elif (
        state.volume_status > VOLUME_HYPERVOLEMIA_THRESHOLD
        and state.cardiac_function < VOLUME_HYPERVOLEMIA_CARDIAC_DYSFUNCTION_THRESHOLD
    ):
        volume_effect = VOLUME_HYPERVOLEMIA_PERFUSION_PENALTY
    state.perfusion_status = clamp(
        state.cardiac_function * PERFUSION_CARDIAC_SCALE + PERFUSION_CARDIAC_BASE_OFFSET + volume_effect, 0.0, 1.0
    )

    # Renal depends on perfusion (pre-renal)
    if state.perfusion_status < PRERENAL_HIT_PERFUSION_THRESHOLD:
        hit = (PRERENAL_HIT_PERFUSION_THRESHOLD - state.perfusion_status) * PRERENAL_HIT_PERFUSION_SCALE
        state.renal_function = clamp(state.renal_function - hit, RENAL_FUNCTION_FLOOR, 1.0)

    # pH depends on renal + perfusion
    renal_acid = 0.0
    if state.renal_function < PH_RENAL_ACID_RENAL_THRESHOLD:
        renal_acid = -(PH_RENAL_ACID_RENAL_THRESHOLD - state.renal_function) * PH_RENAL_ACID_RENAL_SCALE
    lactic_acid = 0.0
    if state.perfusion_status < PH_LACTIC_ACID_PERFUSION_THRESHOLD:
        lactic_acid = -(PH_LACTIC_ACID_PERFUSION_THRESHOLD - state.perfusion_status) * PH_LACTIC_ACID_PERFUSION_SCALE
    state.ph_status = clamp(state.ph_status + (renal_acid + lactic_acid) * PH_COMBINED_ACID_SCALE, -1.0, 1.0)

    # Coagulation worsens with severe inflammation (DIC)
    if state.inflammation_level > COAG_DIC_INFLAMMATION_THRESHOLD:
        dic = (state.inflammation_level - COAG_DIC_INFLAMMATION_THRESHOLD) * COAG_DIC_INFLAMMATION_SCALE
        state.coagulation_status = clamp(state.coagulation_status + dic, 0.0, 1.0)

    # Hepatic dysfunction worsens coagulation
    if state.hepatic_function < COAG_HEPATIC_DYSFUNCTION_THRESHOLD:
        state.coagulation_status = clamp(
            state.coagulation_status
            + (COAG_HEPATIC_DYSFUNCTION_THRESHOLD - state.hepatic_function) * COAG_HEPATIC_DYSFUNCTION_SCALE,
            0.0,
            1.0,
        )

    # Chronic inflammation causes anemia (very slow)
    if state.inflammation_level > COUPLING_ANEMIA_INFLAMMATION_THRESHOLD:
        state.anemia_level = clamp(
            state.anemia_level
            + (state.inflammation_level - COUPLING_ANEMIA_INFLAMMATION_THRESHOLD) * COUPLING_ANEMIA_INFLAMMATION_SCALE,
            0.0,
            1.0,
        )
    # Resolving inflammation allows anemia to recover (bone marrow de-suppression)
    elif (
        state.inflammation_level < COUPLING_ANEMIA_INFLAMMATION_RESOLVING_THRESHOLD
        and state.anemia_level > COUPLING_ANEMIA_ACTIVE_MIN
    ):
        state.anemia_level = clamp(state.anemia_level - COUPLING_ANEMIA_RECOVERY_RATE, 0.0, 1.0)

    # Dehydration (free-water deficit) concentrates serum sodium -> hypernatremia.
    if state.volume_status < HYPERNATREMIA_THRESHOLD:
        state.sodium_status = clamp(
            state.sodium_status
            + (abs(state.volume_status) - abs(HYPERNATREMIA_THRESHOLD)) * HYPERNATREMIA_SODIUM_SCALE,
            -1.0,
            1.0,
        )


# ---------------------------------------------------------------------------
# Lab value derivation (Layer 2)
# ---------------------------------------------------------------------------


def scenario_flags_from_protocol(protocol) -> dict[str, bool]:
    """Extract every `derive_lab_values` scenario flag from a disease YAML
    protocol (dict, Pydantic object, or None).

    Centralizes the `getattr(protocol, "causes_X", False)` / `protocol.get(...)`
    reads so a new flag added to `derive_lab_values` only needs wiring in
    ONE place — not at every call site across inpatient/emergency/outpatient.
    Dict keys match `derive_lab_values` parameter names so callers can spread
    with `**flags`.

    Phase 2a (2026-06-24) introduces this helper to fix J5: pre-helper, only
    inpatient.py:559-560 (Pass-1) read `causes_myocardial_injury`; the second
    inpatient lab path, emergency.py, and outpatient.py passed nothing, so
    MI patients in the ED had no troponin upshift. Same gap would have
    occurred for any newly added scenario flag.
    """
    if protocol is None:
        return {"myocardial_injury": False, "causes_vte": False}

    def _read(name: str) -> bool:
        if isinstance(protocol, dict):
            return bool(protocol.get(name, False))
        return bool(getattr(protocol, name, False))

    return {
        "myocardial_injury": _read("causes_myocardial_injury"),
        "causes_vte": _read("causes_vte"),
    }


def medication_flags_from_context(
    patient,
    medication_orders=None,
    admission_date=None,
    current_day: int | None = None,
) -> dict[str, bool]:
    """Detect medication-driven lab effects from patient + encounter context.

    Centralizes the medication → lab coupling reads so a new coupling added to
    `derive_lab_values` only needs wiring in ONE place — same J5-prevention
    rationale as `scenario_flags_from_protocol`. Dict keys match
    `derive_lab_values` parameter names so callers can spread with `**flags`.

    Phase 2b: returns `{"on_warfarin": bool}` only. Extend the dict for future
    couplings (steroid → glucose, diuretic → K, antibiotic → CRP).

    Detection rules:
      (1) Chronic warfarin: ``patient.current_medications`` contains a
          warfarin string (case-insensitive substring of "warfarin",
          "ワルファリン", "coumadin").
      (2) In-hospital warfarin: ``medication_orders`` contains a warfarin
          order AND ``current_day - (order_date - admission_date).days >= 3``
          (loading-dose 3-day rule).

    DOAC (apixaban / rivaroxaban / edoxaban / dabigatran) is intentionally
    NOT detected — INR is not clinically monitored for DOAC; modeling DOAC
    INR lift would be clinically misleading.

    All inputs are optional / defensive: ``None`` patient or missing
    ``current_medications`` returns ``{"on_warfarin": False}``. ED and
    outpatient call sites pass medication_orders=None / current_day=None;
    only the chronic path runs.
    """
    _WARFARIN_NAMES = ("warfarin", "ワルファリン", "coumadin")

    if patient is None:
        return {"on_warfarin": False}

    on_warfarin = False

    # (1) Chronic warfarin from home meds.
    # Issue #452 PR 3: read `med.drug_name` directly.
    for med in getattr(patient, "current_medications", None) or []:
        med_lower = med.drug_name.lower()
        if any(name in med_lower for name in _WARFARIN_NAMES):
            on_warfarin = True
            break

    # (2) In-hospital warfarin ordered ≥ 3 days ago
    if (
        not on_warfarin
        and medication_orders
        and admission_date is not None
        and current_day is not None
        and current_day >= 3
    ):
        for o in medication_orders:
            display = getattr(o, "display_name", "") or ""
            if not any(name in display.lower() for name in _WARFARIN_NAMES):
                continue
            ordered_dt = getattr(o, "ordered_datetime", None)
            ordered_date = ordered_dt.date() if ordered_dt is not None and hasattr(ordered_dt, "date") else None
            if ordered_date is None:
                continue
            days_since_order = current_day - (ordered_date - admission_date).days
            if days_since_order >= 3:
                on_warfarin = True
                break

    return {"on_warfarin": on_warfarin}


def derive_lab_values(
    state: PhysiologicalState,
    sex: str,
    age: int,
    has_diabetes: bool = False,
    rng: np.random.Generator | None = None,
    hour: int = 6,
    myocardial_injury: bool = False,
    causes_vte: bool = False,
    on_warfarin: bool = False,
    hai_inflammation_lift: float = 0.0,
) -> dict[str, float]:
    """Derive lab values from physiological state. Returns 'true' values before noise."""
    labs: dict[str, float] = {}
    infl = state.inflammation_level
    renal = state.renal_function
    cardiac = state.cardiac_function
    hepatic = state.hepatic_function
    anemia = state.anemia_level
    perfusion = state.perfusion_status
    ph = state.ph_status

    # --- Inflammation ---
    # Phase 3a: HAI WBC + CRP lift via effective_infl. Other inflammation-driven
    # analytes (PCT, Albumin, Fibrinogen, pO2, Ca, Temp, SBP/DBP) continue to
    # read state.inflammation_level directly; they will be revisited in Phase 3c
    # as part of the sepsis-cascade extension.
    effective_infl = min(1.0, infl + hai_inflammation_lift)
    # CRP: effective_infl 0→0.3, 0.4→26, 0.6→87, 0.75→169, 1.0→400 mg/L
    labs["CRP"] = CRP_BASE_MG_L + CRP_INFLAMMATION_SCALE * effective_infl**3
    if effective_infl < WBC_HIGH_INFLAMMATION_THRESHOLD:
        labs["WBC"] = WBC_BASE + effective_infl * WBC_INFLAMMATION_SCALE
    else:
        labs["WBC"] = max(
            WBC_LEUKOPENIA_FLOOR,
            WBC_BASE
            + WBC_HIGH_INFLAMMATION_THRESHOLD * WBC_INFLAMMATION_SCALE
            - (effective_infl - WBC_HIGH_INFLAMMATION_THRESHOLD) * WBC_HIGH_INFLAMMATION_LEUKOPENIA_SCALE,
        )
    labs["PCT"] = PCT_BASE_NG_ML * math.exp(infl * PCT_INFLAMMATION_EXPONENT_SCALE)
    # Alb baseline calibrated so the healthy-cohort median lands on the JCCLS
    # reference-range center (4.6 g/dL). See the calibration note at
    # base_cr below for the derivation and design implications. Issue #416.
    labs["Albumin"] = max(
        ALBUMIN_FLOOR,
        ALBUMIN_BASELINE - infl * ALBUMIN_INFLAMMATION_SCALE - (1 - hepatic) * ALBUMIN_HEPATIC_SCALE,
    )

    # --- Renal ---
    # base_cr calibration (Issue #416):
    #   base = JCCLS ref center × E[reserve],  E[beta(30, 2)] = 30/32 = 0.9375
    #     Cre_M:  0.86  × 0.9375 = 0.80625
    #     Cre_F:  0.625 × 0.9375 = 0.5859375
    #
    # Authoritative-vs-derived distinction:
    #   JCCLS 共用基準範囲 2022 bands are authoritative:
    #     Cre_M [0.65, 1.07]  Cre_F [0.46, 0.79]
    #   Their centers (0.86, 0.625) are NOT authoritative — they are our
    #   calibration targets. The base coefficients here are then reverse-
    #   derived so the E[reserve] < 1 offset does not push the cohort median
    #   off the center.
    #
    # Design implication:
    #   ``reserve = 1.0`` no longer means "textbook typical" — it now means
    #   "slightly better than typical." The bases are chosen so the population
    #   MEDIAN lands on the ref center, not so an idealized reserve=1.0
    #   patient does. Anyone touching this must understand that the two
    #   readings diverge.
    #
    # Scope of this calibration:
    #   Applied only to analytes whose healthy-young in-band ratio fell below
    #   95% on the legacy math (Cre / Alb here; K was 99.07% and needs no
    #   change). Not a blanket refactor.
    base_cr = CREATININE_BASE_MALE if sex == "M" else CREATININE_BASE_FEMALE
    if renal > CREATININE_LOW_RENAL_THRESHOLD:
        labs["Creatinine"] = base_cr / renal
    else:
        # Low-renal slope, BNP-pattern surgical calibration (2026-06-22). The
        # earlier coefficient of 15 mapped state.renal_function=0 to Cr ~9
        # (ESRD/dialysis), inconsistent with KDIGO 3 admit Cr (~5-6) and CKD3
        # (renal~0.3) admit Cr (~2.5-3). 6.5 lands severe AKI at Cr ~5 and
        # CKD3 at Cr ~3, leaving state and clinical_course untouched (avoids
        # the master-RNG cascade documented in spec 2026-06-22-aki-dka-...).
        labs["Creatinine"] = (
            base_cr / CREATININE_LOW_RENAL_THRESHOLD
            + (CREATININE_LOW_RENAL_THRESHOLD - renal) * CREATININE_LOW_RENAL_SLOPE
        )
    labs["BUN"] = BUN_BASE_MG_DL / max(renal, BUN_RENAL_FLOOR)
    if state.volume_status < BUN_ELEVATION_THRESHOLD:
        labs["BUN"] *= 1.0 + abs(state.volume_status) * BUN_VOLUME_LIFT_SCALE
    labs["eGFR"] = renal * EGFR_RENAL_SCALE
    # K: renal failure causes hyperkalemia, but not as aggressively as before
    # renal 1.0→K 4.0, renal 0.3→K 5.4, renal 0.1→K 6.0, acidosis adds
    labs["K"] = clamp(
        POTASSIUM_BASE_MEQ_L + (1 - renal) * POTASSIUM_RENAL_SCALE + max(0, -ph) * POTASSIUM_ACIDOSIS_SCALE,
        POTASSIUM_MIN_MEQ_L,
        POTASSIUM_MAX_MEQ_L,
    )
    # Na driven by the dysnatremia axis (chronic HF/cirrhosis hypo, dehydration hyper, SIADH).
    # The old volume term is subsumed by the volume->sodium coupling (apply_coupling_rules).
    labs["Na"] = SODIUM_BASE_MEQ_L + state.sodium_status * SODIUM_STATUS_SCALE - (1 - renal) * SODIUM_RENAL_PENALTY
    labs["Na"] = clamp(labs["Na"], SODIUM_MIN_MEQ_L, SODIUM_MAX_MEQ_L)

    # --- Cardiac ---
    # BNP reflects ventricular wall stress = volume/pressure load ON a stressed ventricle.
    # The volume term is gated by cardiac dysfunction (coupling), so volume overload only
    # elevates BNP when the heart is failing: HF (low cardiac x high volume) rises sharply,
    # uncomplicated MI (low cardiac, normal volume) stays moderate, and non-cardiac fluid
    # overload in a preserved heart (cirrhosis ascites, AKI) stays low. Deterministic
    # (state -> lab, no rng).
    #
    # Base 15.0 (Issue #430, from prior 30.0): healthy cardiac=1.0 gives
    # BNP = 15 pg/mL, centering healthy volunteers within the JP JCCLS reference
    # (M < 18.4, F < 22.9). Base 30.0 exceeded the JP healthy upper bound at
    # cardiac=1.0 and forced healthy patients into a systematically elevated BNP,
    # the 4th baseline-off-center after Alb / Cre F / Troponin_I (all closed in
    # PR #427). With base 15.0, HF exacerbation (cardiac~0.27 / volume~0.56)
    # lands BNP ~500 pg/mL (moderate HF band), acute MI (cardiac~0.19 / volume~0)
    # ~75 pg/mL (below HF rule-out 100, clinically appropriate for uncomplicated
    # MI), and non-cardiac cohorts stay clearly under the 100 pg/mL rule-out
    # cutoff. Trade-off vs prior calibration: HF cohort BNP median halves — the
    # prior 800-1500 range was above typical HF-exacerbation clinical values;
    # ~500 is more representative of the moderate HF band.
    labs["BNP"] = BNP_BASELINE_PG_ML * math.exp(
        (1 - cardiac) * BNP_CARDIAC_EXP_SCALE
        + max(0.0, state.volume_status) * (1 - cardiac) * BNP_VOLUME_CARDIAC_EXP_SCALE
    )
    # Cardiac injury markers. Normal heart (cardiac≈1.0) stays negative so troponin
    # rule-outs in non-cardiac disease read normal; acute injury (MI: cardiac 0.3–0.5)
    # elevates strongly. Steep (^4) so only meaningful dysfunction lifts troponin.
    injury = 1 - cardiac
    # Troponin specificity: ANY cardiac dysfunction (sepsis, PE, AF, stroke) gives only a
    # MILD, capped type-2/demand elevation; only true myocardial necrosis (ACS, flagged by
    # the disease scenario) releases MI-level troponin. Renal impairment reduces clearance →
    # chronic mild elevation (CKD confounder). Keeps non-cardiac labs clinically coherent.
    renal_tnt = (1 - renal) * TROPONIN_RENAL_LIFT_SCALE
    tnt = (
        TROPONIN_BASELINE_NG_ML + min(injury**3 * TROPONIN_TYPE2_INJURY_CUBE_SCALE, TROPONIN_TYPE2_CAP) + renal_tnt
    )  # type-2 (mild, ≲3 ng/mL)
    ckmb = CK_MB_BASELINE_NG_ML + min(injury**3 * CK_MB_TYPE2_INJURY_CUBE_SCALE, CK_MB_TYPE2_CAP)
    if myocardial_injury:  # ACS → primary necrosis
        tnt += injury**2 * TROPONIN_ACS_INJURY_SQ_SCALE
        ckmb += injury**2 * CK_MB_ACS_INJURY_SQ_SCALE
    labs["Troponin_I"] = tnt  # ng/mL (normal < 0.04; ACS ~10–100)
    labs["CK_MB"] = ckmb  # ng/mL (normal < 5)

    # --- Hepatic ---
    labs["AST"] = AST_BASELINE_U_L + (1 - hepatic) * AST_HEPATIC_SCALE
    labs["ALT"] = ALT_BASELINE_U_L + (1 - hepatic) * ALT_HEPATIC_SCALE
    labs["T_Bil"] = T_BIL_BASELINE_MG_DL + (1 - hepatic) * T_BIL_HEPATIC_SCALE
    # PT_INR: hepatic (cirrhosis factor depletion) + coagulation_status (DIC
    # consumption) drive baseline; therapeutic warfarin overrides to target
    # the 2.0-3.0 clinical band. AC + comorbidity (DIC, cirrhosis) compounds
    # bleeding risk in real practice, so base perturbation is added on top of
    # the therapeutic center at reduced gain (x0.5).
    # BNP-pattern surgical (AD-57): state untouched, formula-only change.
    # Phase 2b (2026-06-24): on_warfarin sourced from
    # medication_flags_from_context (sibling of scenario_flags_from_protocol).
    base_inr = (
        PT_INR_BASELINE + (1 - hepatic) * PT_INR_HEPATIC_SCALE + state.coagulation_status * PT_INR_COAGULATION_SCALE
    )
    if on_warfarin:
        labs["PT_INR"] = PT_INR_WARFARIN_TARGET_CENTER + (base_inr - PT_INR_BASELINE) * PT_INR_WARFARIN_BASE_GAIN
    else:
        labs["PT_INR"] = base_inr

    # --- Anemia ---
    base_hb = HB_BASELINE_MALE_G_DL if sex == "M" else HB_BASELINE_FEMALE_G_DL
    labs["Hb"] = max(HB_FLOOR_G_DL, base_hb * (1 - anemia * HB_ANEMIA_SCALE))
    labs["Hct"] = labs["Hb"] * HCT_HB_RATIO
    labs["Plt"] = max(PLT_FLOOR, PLT_BASELINE - state.coagulation_status * PLT_COAGULATION_SCALE)

    # --- Coagulation panel (LOINC 24373-3 components + Fibrinogen adjunct) ---
    # APTT (activated partial thromboplastin time, seconds). Normal 25-35;
    # DIC 60-100+. Intrinsic-pathway sensitive; coagulation_status proxies
    # DIC + hepatic factor depletion already aggregated upstream by
    # apply_coupling_rules. State-unchanged formula per AD-57 BNP-pattern
    # surgical; no new PhysiologicalState field.
    labs["APTT"] = clamp(
        APTT_BASELINE_SEC + state.coagulation_status * APTT_COAGULATION_SCALE,
        APTT_PHYSIOLOGIC_MIN_SEC,
        APTT_PHYSIOLOGIC_MAX_SEC,
    )

    # PT (prothrombin time, seconds). Mathematically tied to PT_INR via
    # INR = (PT / normal_PT)^ISI; with ISI ≈ 1.0 and normal_PT ≈ 12 s,
    # PT ≈ 12 * PT_INR. Derived FROM PT_INR (not in parallel) so the two
    # never numerically disagree.
    labs["PT"] = clamp(PT_ISI_FALLBACK_NORMAL_SEC * labs["PT_INR"], PT_PHYSIOLOGIC_MIN_SEC, PT_PHYSIOLOGIC_MAX_SEC)

    # Fibrinogen (mg/dL). Biphasic: acute-phase reactant (inflammation ↑↑)
    # AND consumed in DIC (coagulation_status ↑↑). Healthy baseline 200-400.
    # Sepsis without DIC: rises to ~510 (acute-phase). Sepsis WITH DIC:
    # consumption outpaces acute-phase and Fibrinogen falls below 350 (the
    # DIC-trending signal clinicians look for). Floor 50 mg/dL (laboratory
    # detection floor; clinically <100 indicates severe consumptive coagulopathy).
    # Panel-external: LOINC 24373-3 Coag panel covers PT/PT_INR/APTT only;
    # Fibrinogen 3255-7 emits as an individual Observation.
    labs["Fibrinogen"] = clamp(
        FIBRINOGEN_BASELINE_MG_DL
        + infl * FIBRINOGEN_INFLAMMATION_SCALE
        - state.coagulation_status * FIBRINOGEN_COAGULATION_CONSUMPTION_SCALE,
        FIBRINOGEN_PHYSIOLOGIC_MIN,
        FIBRINOGEN_PHYSIOLOGIC_MAX,
    )

    # D-dimer (ug/mL FEU). Baseline 0.3 + age-adjustment (well-documented
    # +0.005 / year above 50) + inflammation contribution (sepsis lifts
    # modestly, non-VTE-specific) + coagulation_status (DIC/fibrinolysis
    # lifts further). The decisive signal is `causes_vte`: PE/DVT/embolic
    # stroke push D-dimer to clinically positive 5-20 ug/mL territory.
    # Clamp floor 0.15 (laboratory detection floor), ceiling 20 (assay
    # upper limit). AD-57 BNP-pattern surgical: scenario flag is the
    # input, no state mutation, no master-RNG draw.
    age_factor = max(0.0, age - D_DIMER_AGE_ADJUST_MIN_AGE) * D_DIMER_AGE_ADJUST_SCALE
    d_dimer = (
        D_DIMER_BASELINE
        + age_factor
        + infl * D_DIMER_INFLAMMATION_SCALE
        + state.coagulation_status * D_DIMER_COAGULATION_SCALE
        + (D_DIMER_VTE_LIFT if causes_vte else 0.0)
    )
    labs["D_dimer"] = clamp(d_dimer, D_DIMER_PHYSIOLOGIC_MIN, D_DIMER_PHYSIOLOGIC_MAX)

    # --- Perfusion ---
    labs["Lactate"] = LACTATE_BASELINE_MMOL_L + (1 - perfusion) * LACTATE_PERFUSION_SCALE

    # --- pH / Blood gas (two-axis: metabolic HCO3 + respiratory pCO2, AD-57) ---
    # `ph` is the acid-base disturbance magnitude (neg = acidemia); respiratory_fraction
    # routes it between the metabolic (bicarbonate) and respiratory (CO2) axes. pH then
    # follows Henderson-Hasselbalch on the resulting HCO3/pCO2, with partial compensation
    # by the opposing system — so DKA shows Kussmaul (low pCO2) and chronic COPD shows a
    # raised, compensating HCO3 rather than both moving the same way off one axis.
    rf = clamp(state.respiratory_fraction, 0.0, 1.0)
    mf = 1.0 - rf
    # Metabolic-axis gain, BNP-pattern surgical calibration (2026-06-22). 24 left
    # DKA moderate (ph_status=-0.35) at HCO3 ~15.6, outside the ADA moderate band
    # (10-15). 31 lands moderate DKA at HCO3 ~13 (mid-band) and severe DKA at <10,
    # while CKD chronic (ph_status~-0.10) drops only from 21.6 to 20.9. state is
    # unchanged. Spec: docs/history/specs-archive/2026-06-22-aki-dka-surgical-calibration-design.md
    hco3 = HCO3_BASELINE_MEQ_L + ph * mf * HCO3_METABOLIC_GAIN  # metabolic load drives bicarbonate
    pco2 = PCO2_BASELINE_MMHG - ph * rf * PCO2_RESPIRATORY_GAIN  # respiratory load drives CO2 (acidosis → retention)
    if mf > 0.0 and ph != 0.0:
        # Respiratory compensation for a metabolic disturbance (Winter's formula, ~80%).
        winters_pco2 = PCO2_WINTERS_HCO3_COEFF * hco3 + PCO2_WINTERS_INTERCEPT
        pco2 += PCO2_WINTERS_COMPENSATION_RATIO * (winters_pco2 - PCO2_BASELINE_MMHG)
    if rf > 0.0 and ph != 0.0:
        # Renal (metabolic) compensation for a respiratory disturbance (~0.35 mEq/mmHg).
        hco3 += HCO3_RENAL_COMPENSATION_RATIO * (pco2 - PCO2_BASELINE_MMHG)
    pco2 = clamp(pco2, PCO2_CLAMP_MIN, PCO2_CLAMP_MAX)
    hco3 = clamp(hco3, HCO3_CLAMP_MIN, HCO3_CLAMP_MAX)
    labs["HCO3"] = hco3
    labs["pCO2"] = pco2
    labs["pH"] = clamp(
        PH_HENDERSON_HASSELBALCH_CONSTANT + math.log10(hco3 / (PH_HENDERSON_PCO2_COEFF * pco2)),
        PH_CLAMP_MIN,
        PH_CLAMP_MAX,
    )
    # pO2: reduced by pulmonary involvement (inflammation as a lung-injury proxy until a
    # dedicated respiratory/oxygenation state variable exists — AD-57 follow-up).
    labs["pO2"] = clamp(PO2_BASELINE_MMHG - infl * PO2_INFLAMMATION_SCALE, PO2_CLAMP_MIN, PO2_CLAMP_MAX)  # mm[Hg]

    # --- Electrolytes: Cl and Ca complete BMP canonical 8 ---
    # Cl reflects (a) Na linkage (electroneutrality) and (b) HCO3 reciprocity:
    # in non-AG metabolic acidosis (diarrhea, RTA) Cl absorbs the HCO3 deficit
    # 1:1 (hyperchloremic), while in high-AG acidosis (DKA, sepsis, uremia) the
    # unmeasured anion (ketone/lactate/SO4/PO4) absorbs it and Cl stays near
    # normal. The anion_gap_status axis routes between the two regimes. The
    # axis does NOT mutate ph/HCO3/pCO2 or feed back into any state variable.
    base_cl = CL_BASELINE_MEQ_L + state.sodium_status * CL_SODIUM_LINKAGE_SCALE
    hco3_deficit = max(0.0, CL_HCO3_DEFICIT_REFERENCE - labs["HCO3"])
    non_ag_fraction = clamp(1.0 - state.anion_gap_status, 0.0, CL_NON_AG_FRACTION_MAX)
    labs["Cl"] = clamp(base_cl + hco3_deficit * non_ag_fraction, CL_CLAMP_MIN, CL_CLAMP_MAX)
    # Total Ca — the lab-standard report (JCCLS 3H030 / LOINC 17861-6).
    # Corrected Ca and ionized Ca (iCa) are physician-side computations from a
    # second sample and out of scope here (Phase 2). Multi-axis linear coupling:
    # sepsis (inflammation), CKD (renal), liver failure (hepatic) drop Ca;
    # mild dehydration (high Na) lifts it slightly.
    ca = (
        CA_BASELINE_MG_DL
        - state.inflammation_level * CA_INFLAMMATION_SCALE
        - (1.0 - state.renal_function) * CA_RENAL_SCALE
        - (1.0 - state.hepatic_function) * CA_HEPATIC_SCALE
        + state.sodium_status * CA_SODIUM_LIFT
    )
    labs["Ca"] = clamp(ca, CA_CLAMP_MIN, CA_CLAMP_MAX)

    # --- Glucose (chronic diabetes baseline + acute glycemic state + diurnal variation) ---
    is_diabetic = has_diabetes or state.glycemic_control is not None
    gc = state.glycemic_control if state.glycemic_control is not None else GLYCEMIC_CONTROL_DEFAULT
    if is_diabetic:
        base_glu = GLU_DM_BEST + (1.0 - clamp(gc, 0.0, 1.0)) * GLU_DM_SPAN
    else:
        base_glu = GLU_NONDM_BASELINE_MG_DL
    # Acute glycemic drive (DKA/HHS push glucose_status up; insulin therapy lowers it).
    gs = state.glucose_status
    if gs >= 0:
        base_glu += gs * GLU_HYPERGLYCEMIA_SCALE  # hyperglycemia: gs 0.6 ≈ +300 (DKA 300-500 range)
    else:
        base_glu += gs * GLU_HYPOGLYCEMIA_SCALE  # hypoglycemia: gs -0.5 ≈ -27
    labs["Glucose"] = base_glu
    labs["Glucose"] += infl * GLU_STRESS_INFLAMMATION_LIFT  # stress hyperglycemia
    # Postprandial rise: meals ~8h, 12h, 18h → peak 1-2h after
    # Fasting (early morning 04-07): lowest
    postprandial = 0.0
    if GLU_POSTPRANDIAL_BREAKFAST_HOUR_MIN <= hour <= GLU_POSTPRANDIAL_BREAKFAST_HOUR_MAX:  # post-breakfast
        postprandial = GLU_POSTPRANDIAL_BREAKFAST_LIFT
    elif GLU_POSTPRANDIAL_LUNCH_HOUR_MIN <= hour <= GLU_POSTPRANDIAL_LUNCH_HOUR_MAX:  # post-lunch
        postprandial = GLU_POSTPRANDIAL_LUNCH_LIFT
    elif GLU_POSTPRANDIAL_DINNER_HOUR_MIN <= hour <= GLU_POSTPRANDIAL_DINNER_HOUR_MAX:  # post-dinner
        postprandial = GLU_POSTPRANDIAL_DINNER_LIFT
    labs["Glucose"] += postprandial
    labs["Glucose"] = clamp(labs["Glucose"], GLU_CLAMP_MIN, GLU_CLAMP_MAX)  # physiological bounds

    # --- HbA1c (chronic glycemic control; ~3-month average, control-driven) ---
    if is_diabetic:
        labs["HbA1c"] = hba1c_from_glycemic_control(gc)
    else:
        labs["HbA1c"] = HBA1C_NONDM_BASE + max(0, age - HBA1C_NONDM_AGE_MIN) * HBA1C_NONDM_AGE_SCALE_LAB

    # --- WBC diurnal variation (±10%, afternoon slightly higher) ---
    # Nadir ~04:00, peak ~16:00
    wbc_circadian = 1.0 + WBC_CIRCADIAN_AMPLITUDE * (
        -math.cos((hour - WBC_CIRCADIAN_HOUR_OFFSET) * math.pi / WBC_CIRCADIAN_HOUR_PERIOD)
    )
    labs["WBC"] *= wbc_circadian

    return labs


# ---------------------------------------------------------------------------
# Vital signs derivation
# ---------------------------------------------------------------------------


def derive_vital_signs(
    state: PhysiologicalState,
    baseline: BaselineVitals,
    timestamp: datetime,
) -> dict[str, float]:
    """Derive vital signs from physiological state + baseline."""
    infl = state.inflammation_level
    perf = state.perfusion_status
    vol = state.volume_status

    # Temperature: inflammation + circadian
    hour = timestamp.hour
    circadian = TEMPERATURE_CIRCADIAN_SCALE * (
        -math.cos((hour - TEMPERATURE_CIRCADIAN_HOUR_OFFSET) * math.pi / TEMPERATURE_CIRCADIAN_HOUR_PERIOD)
    )
    temperature = baseline.temperature + infl * TEMPERATURE_INFLAMMATION_SCALE + circadian
    temperature = clamp(temperature, TEMPERATURE_CLAMP_MIN, TEMPERATURE_CLAMP_MAX)

    # Heart rate
    temp_effect = max(0, (temperature - HR_FEVER_REFERENCE_TEMP_C)) * HR_TEMPERATURE_SCALE
    perfusion_effect = max(0, (1.0 - perf)) * HR_PERFUSION_SCALE
    anemia_effect = state.anemia_level * HR_ANEMIA_SCALE
    hr = baseline.heart_rate + temp_effect + perfusion_effect + anemia_effect
    hr = clamp(hr, HR_CLAMP_MIN, HR_CLAMP_MAX)

    # Blood pressure
    # Distributive (vasodilatory) hypotension: severe systemic inflammation lowers
    # BP — the mechanism of septic shock. Applied here, at the displayed vital, so
    # it does NOT mutate perfusion_status (which feeds the clinical-course /
    # complication / LOS / mortality RNG); that keeps the master stream stable while
    # still producing hypotension coherent with the already-elevated sepsis labs.
    distributive_drop = max(0.0, infl - DISTRIBUTIVE_THRESHOLD) * DISTRIBUTIVE_SBP_COEFF
    sbp: float = (
        baseline.systolic_bp + vol * BP_SBP_VOLUME_SCALE - (1 - perf) * BP_SBP_PERFUSION_SCALE - distributive_drop
    )
    sbp = clamp(sbp, BP_SBP_CLAMP_MIN, BP_SBP_CLAMP_MAX)
    dbp: float = (
        baseline.diastolic_bp
        + vol * BP_DBP_VOLUME_SCALE
        - (1 - perf) * BP_DBP_PERFUSION_SCALE
        - distributive_drop * BP_DBP_DISTRIBUTIVE_RATIO
    )
    dbp = clamp(dbp, BP_DBP_CLAMP_MIN, BP_DBP_CLAMP_MAX)

    # Respiratory rate
    rr: float = baseline.respiratory_rate
    rr += max(0, -state.ph_status) * RR_PH_ACIDOSIS_SCALE
    rr += infl * RR_INFLAMMATION_SCALE
    if vol > RR_VOLUME_OVERLOAD_THRESHOLD:
        rr += (vol - RR_VOLUME_OVERLOAD_THRESHOLD) * RR_VOLUME_OVERLOAD_SCALE
    rr = clamp(rr, RR_CLAMP_MIN, RR_CLAMP_MAX)

    # SpO2
    spo2 = baseline.spo2
    if infl > SPO2_INFLAMMATION_THRESHOLD:
        spo2 -= (infl - SPO2_INFLAMMATION_THRESHOLD) * SPO2_INFLAMMATION_SCALE
    if vol > SPO2_VOLUME_OVERLOAD_THRESHOLD:
        spo2 -= (vol - SPO2_VOLUME_OVERLOAD_THRESHOLD) * SPO2_VOLUME_OVERLOAD_SCALE
    spo2 = clamp(spo2, SPO2_CLAMP_MIN, SPO2_CLAMP_MAX)

    return {
        "temperature": round(temperature, 1),
        "heart_rate": int(hr),
        "systolic_bp": int(sbp),
        "diastolic_bp": int(dbp),
        "respiratory_rate": int(rr),
        "spo2": round(spo2, 1),
    }


def derive_observed_vitals(
    state: PhysiologicalState,
    baseline: BaselineVitals,
    timestamp: datetime,
    rng: np.random.Generator,
) -> dict[str, float]:
    """Physiology-derived vitals + realistic measurement noise.

    Single derivation path shared by inpatient, ED, and outpatient (AD-57): the true
    vitals come from the hidden physiological state, then per-measurement Gaussian noise
    models device/observer variation. SpO2 is re-clamped to a physiological range.
    """
    raw = derive_vital_signs(state, baseline, timestamp)
    for key in raw:
        noise_sd = OBSERVED_TEMPERATURE_NOISE_SD if key == "temperature" else OBSERVED_VITALS_NOISE_SD_DEFAULT
        raw[key] += float(rng.normal(0, noise_sd))
        if key == "spo2":
            raw[key] = min(OBSERVED_SPO2_CLAMP_MAX, max(OBSERVED_SPO2_CLAMP_MIN, raw[key]))
    return raw


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Single source of truth for canonical delta-driven state-var ranges.
# Anion gap axis: negative = non-AG (hyperchloremic, GI loss), positive =
# high-AG (ketone/lactate/uremia). Missing here previously meant the
# (0.0, 1.0) default silently clamped every GI condition's negative axis
# to 0.0 in apply_disease_onset (degenerate hyperchloremia).
_VARIABLE_RANGES: dict[str, tuple[float, float]] = {
    "inflammation_level": (0.0, 1.0),
    "renal_function": (0.0, 1.0),
    "cardiac_function": (0.0, 1.0),
    "hepatic_function": (0.0, 1.0),
    "anemia_level": (0.0, 1.0),
    "coagulation_status": (0.0, 1.0),
    "volume_status": (-1.0, 1.0),
    "perfusion_status": (0.0, 1.0),
    "ph_status": (-1.0, 1.0),
    "respiratory_fraction": (0.0, 1.0),
    "glucose_status": (-1.0, 1.0),
    "sodium_status": (-1.0, 1.0),
    "anion_gap_status": (-1.0, 1.0),
}


def _variable_range(var: str) -> tuple[float, float]:
    return _VARIABLE_RANGES.get(var, (0.0, 1.0))


def canonical_state_vars() -> frozenset[str]:
    """Return the canonical set of delta-driven physiological state vars.

    Consumed by :func:`_validate_initial_state_impact` to reject typo'd /
    unmodeled state-var keys in disease YAMLs at author time
    (FP-DELTA-VALIDATE). The set is the keys of the internal
    ``_VARIABLE_RANGES`` map, which is the canonical clamp-range source
    consumed by :func:`apply_state_delta`.
    """
    return frozenset(_VARIABLE_RANGES.keys())


def _validate_complications_state_impact(
    disease_id: str,
    complications: list[dict],
) -> None:
    """Fail-loud gate for ``complications[].state_impact`` state-var keys.

    Sibling of :func:`_validate_initial_state_impact` — complication state
    deltas route through the same :func:`apply_state_delta` sink, so an
    unmodeled var here also silently no-ops (FP-DELTA-VALIDATE cross-module
    sweep).
    """
    if not complications:
        return
    canonical = canonical_state_vars()
    offenders: list[tuple[str, str]] = []
    for comp in complications or []:
        if not isinstance(comp, dict):
            continue
        name = comp.get("name") or comp.get("id") or "<unnamed>"
        state_impact = comp.get("state_impact") or {}
        if not isinstance(state_impact, dict):
            continue
        for var in state_impact:
            if var not in canonical:
                offenders.append((name, var))
    if offenders:
        details = ", ".join(f"{n!r}: {v!r}" for n, v in offenders)
        raise ValueError(
            f"Disease {disease_id!r} complications[].state_impact declares deltas "
            f"on non-canonical state var(s) [{details}] — these would silently "
            f"no-op in apply_state_delta. Canonical vars: {sorted(canonical)}. "
            f"Either fix the YAML key (typo) or expand the physiological model."
        )


def _validate_initial_state_impact(
    disease_id: str,
    initial_state_impact: dict[str, dict[str, float]],
) -> None:
    """Fail-loud gate for ``initial_state_impact`` state-var keys.

    Raises ``ValueError`` if any severity block references a state var that is
    not in :func:`canonical_state_vars` — such keys would silently no-op in
    :func:`apply_state_delta` (via ``getattr(state, var, None)``) and lose the
    author's clinical intent (FP-DELTA-VALIDATE). Error message
    lists the disease id, offending severity, offending var(s), and the
    canonical set.
    """
    if not initial_state_impact:
        return
    canonical = canonical_state_vars()
    offenders: list[tuple[str, str]] = []
    for severity, deltas in initial_state_impact.items():
        if not isinstance(deltas, dict):
            continue
        for var in deltas:
            if var not in canonical:
                offenders.append((severity, var))
    if offenders:
        details = ", ".join(f"{sev!r}: {var!r}" for sev, var in offenders)
        raise ValueError(
            f"Disease {disease_id!r} initial_state_impact declares deltas on "
            f"non-canonical state var(s) [{details}] — these would silently "
            f"no-op in apply_state_delta. Canonical vars: "
            f"{sorted(canonical)}. Either fix the YAML key (typo) or expand "
            f"the physiological model (add the state var to PhysiologicalState "
            f"+ _VARIABLE_RANGES + downstream lab / coupling wiring)."
        )
