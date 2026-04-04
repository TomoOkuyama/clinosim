"""Physiology engine — state variables, coupling rules, lab/vital derivation.

This is the core realism engine. All observable clinical data (lab values, vital signs)
are derived from the hidden physiological state, not generated independently.
"""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timedelta

import numpy as np

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
            state.renal_function *= 1.0 - s * 0.5
            if s > 0.5:
                state.anemia_level += 0.15
                state.ph_status -= s * 0.1
        elif code.startswith("I50"):  # Heart failure
            state.cardiac_function *= 1.0 - s * 0.4
            if s > 0.3:
                state.volume_status += s * 0.3
        elif code.startswith("K74"):  # Cirrhosis
            state.hepatic_function *= 1.0 - s * 0.5
            state.coagulation_status += s * 0.2
        elif code.startswith("J44"):  # COPD
            state.ph_status -= s * 0.05

    # Perfusion tracks cardiac
    state.perfusion_status = clamp(state.cardiac_function * 0.8 + 0.2, 0.0, 1.0)

    # Clamp all
    state.renal_function = clamp(state.renal_function, 0.05, 1.0)
    state.cardiac_function = clamp(state.cardiac_function, 0.05, 1.0)
    state.hepatic_function = clamp(state.hepatic_function, 0.05, 1.0)

    return state


def apply_disease_onset(
    state: PhysiologicalState,
    severity: str,
    initial_impact: dict[str, dict[str, float]],
) -> PhysiologicalState:
    """Apply the initial impact of a disease on physiological state."""
    impact = initial_impact.get(severity, {})
    for var, delta in impact.items():
        current = getattr(state, var, None)
        if current is not None:
            lo, hi = _variable_range(var)
            setattr(state, var, clamp(current + delta, lo, hi))
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
        current = getattr(state, variable, None)
        if current is not None:
            delta = daily_delta * scale
            lo, hi = _variable_range(variable)
            setattr(state, variable, clamp(current + delta, lo, hi))

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
    if state.volume_status < -0.5:
        volume_effect = state.volume_status * 0.3
    elif state.volume_status > 0.5 and state.cardiac_function < 0.5:
        volume_effect = -0.1
    state.perfusion_status = clamp(
        state.cardiac_function * 0.8 + 0.2 + volume_effect, 0.0, 1.0
    )

    # Renal depends on perfusion (pre-renal)
    if state.perfusion_status < 0.5:
        hit = (0.5 - state.perfusion_status) * 0.3
        state.renal_function = clamp(state.renal_function - hit, 0.05, 1.0)

    # pH depends on renal + perfusion
    renal_acid = 0.0
    if state.renal_function < 0.3:
        renal_acid = -(0.3 - state.renal_function) * 0.5
    lactic_acid = 0.0
    if state.perfusion_status < 0.4:
        lactic_acid = -(0.4 - state.perfusion_status) * 0.6
    state.ph_status = clamp(state.ph_status + (renal_acid + lactic_acid) * 0.1, -1.0, 1.0)

    # Coagulation worsens with severe inflammation (DIC)
    if state.inflammation_level > 0.7:
        dic = (state.inflammation_level - 0.7) * 0.15
        state.coagulation_status = clamp(state.coagulation_status + dic, 0.0, 1.0)

    # Hepatic dysfunction worsens coagulation
    if state.hepatic_function < 0.4:
        state.coagulation_status = clamp(
            state.coagulation_status + (0.4 - state.hepatic_function) * 0.1, 0.0, 1.0
        )

    # Chronic inflammation causes anemia (very slow)
    if state.inflammation_level > 0.5:
        state.anemia_level = clamp(
            state.anemia_level + (state.inflammation_level - 0.5) * 0.005, 0.0, 1.0
        )


# ---------------------------------------------------------------------------
# Lab value derivation (Layer 2)
# ---------------------------------------------------------------------------

def derive_lab_values(
    state: PhysiologicalState,
    sex: str,
    age: int,
    has_diabetes: bool = False,
    diabetes_controlled: bool = True,
    rng: np.random.Generator | None = None,
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
    labs["CRP"] = 0.1 * math.exp(infl * 5.8)
    if infl < 0.8:
        labs["WBC"] = 7000 + infl * 12000
    else:
        labs["WBC"] = max(1500, 7000 + 0.8 * 12000 - (infl - 0.8) * 30000)
    labs["PCT"] = 0.03 * math.exp(infl * 7)
    labs["Albumin"] = max(1.0, 4.2 - infl * 2.0 - (1 - hepatic) * 1.5)

    # --- Renal ---
    base_cr = 0.9 if sex == "M" else 0.7
    if renal > 0.5:
        labs["Creatinine"] = base_cr / renal
    else:
        labs["Creatinine"] = base_cr / 0.5 + (0.5 - renal) * 15
    labs["BUN"] = 15.0 / max(renal, 0.1)
    if state.volume_status < -0.3:
        labs["BUN"] *= 1.0 + abs(state.volume_status) * 0.5
    labs["eGFR"] = renal * 120
    labs["K"] = clamp(4.0 + (1 - renal) * 3.0 + max(0, -ph) * 1.0, 2.5, 8.0)
    labs["Na"] = 140.0 - (1 - renal) * 5 + state.volume_status * (-3)
    labs["Na"] = clamp(labs["Na"], 120, 160)

    # --- Cardiac ---
    labs["BNP"] = 30 * math.exp((1 - cardiac) * 4)

    # --- Hepatic ---
    labs["AST"] = 25 + (1 - hepatic) * 500
    labs["ALT"] = 20 + (1 - hepatic) * 400
    labs["T_Bil"] = 0.8 + (1 - hepatic) * 15
    labs["PT_INR"] = 1.0 + (1 - hepatic) * 2.0 + state.coagulation_status * 1.5

    # --- Anemia ---
    base_hb = 15.0 if sex == "M" else 13.0
    labs["Hb"] = max(3.0, base_hb * (1 - anemia * 0.7))
    labs["Hct"] = labs["Hb"] * 3.0
    labs["Plt"] = max(20, 250 - state.coagulation_status * 200)

    # --- Perfusion ---
    labs["Lactate"] = 1.0 + (1 - perfusion) * 12

    # --- pH / Blood gas ---
    labs["pH"] = 7.40 + ph * 0.20
    labs["HCO3"] = 24 + ph * 12
    labs["pCO2"] = 40 - ph * 10  # respiratory compensation

    # --- Glucose ---
    if has_diabetes:
        mean_glu = 130.0 if diabetes_controlled else 200.0
        labs["Glucose"] = mean_glu
    else:
        labs["Glucose"] = 95.0
    labs["Glucose"] += infl * 50  # stress hyperglycemia

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
    circadian = 0.3 * math.sin((hour - 4) * math.pi / 12)
    temperature = baseline.temperature + infl * 3.0 + circadian
    temperature = clamp(temperature, 35.0, 42.0)

    # Heart rate
    temp_effect = max(0, (temperature - 37.0)) * 10
    perfusion_effect = max(0, (1.0 - perf)) * 40
    anemia_effect = state.anemia_level * 15
    hr = baseline.heart_rate + temp_effect + perfusion_effect + anemia_effect
    hr = clamp(hr, 40, 180)

    # Blood pressure
    sbp = baseline.systolic_bp + vol * 15 - (1 - perf) * 40
    sbp = clamp(sbp, 60, 220)
    dbp = baseline.diastolic_bp + vol * 8 - (1 - perf) * 20
    dbp = clamp(dbp, 30, 130)

    # Respiratory rate
    rr = baseline.respiratory_rate
    rr += max(0, -state.ph_status) * 10
    rr += infl * 4
    if vol > 0.5:
        rr += (vol - 0.5) * 8
    rr = clamp(rr, 8, 45)

    # SpO2
    spo2 = baseline.spo2
    if infl > 0.3:
        spo2 -= (infl - 0.3) * 10
    if vol > 0.3:
        spo2 -= (vol - 0.3) * 5
    spo2 = clamp(spo2, 60, 100)

    return {
        "temperature": round(temperature, 1),
        "heart_rate": int(hr),
        "systolic_bp": int(sbp),
        "diastolic_bp": int(dbp),
        "respiratory_rate": int(rr),
        "spo2": round(spo2, 1),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _variable_range(var: str) -> tuple[float, float]:
    ranges = {
        "inflammation_level": (0.0, 1.0),
        "renal_function": (0.0, 1.0),
        "cardiac_function": (0.0, 1.0),
        "hepatic_function": (0.0, 1.0),
        "anemia_level": (0.0, 1.0),
        "coagulation_status": (0.0, 1.0),
        "volume_status": (-1.0, 1.0),
        "perfusion_status": (0.0, 1.0),
        "ph_status": (-1.0, 1.0),
    }
    return ranges.get(var, (0.0, 1.0))
