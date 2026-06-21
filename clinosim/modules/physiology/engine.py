"""Physiology engine — state variables, coupling rules, lab/vital derivation.

This is the core realism engine. All observable clinical data (lab values, vital signs)
are derived from the hidden physiological state, not generated independently.
"""

from __future__ import annotations

import math
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
            state.sodium_status -= s * 0.30   # dilutional hyponatremia
        elif code.startswith("K74"):  # Cirrhosis
            state.hepatic_function *= 1.0 - s * 0.5
            state.coagulation_status += s * 0.2
            state.sodium_status -= s * 0.40   # dilutional hyponatremia
        elif code.startswith("J44"):  # COPD
            state.ph_status -= s * 0.05
            state.respiratory_fraction = 1.0  # chronic CO2 retention → respiratory axis
        elif code.startswith("I25"):  # Ischemic heart disease
            state.cardiac_function *= 1.0 - s * 0.2
        elif code.startswith("I48"):  # Atrial fibrillation
            state.cardiac_function *= 1.0 - s * 0.1
        elif code.startswith("E03"):  # Hypothyroidism
            # Mild baseline bradycardia effect (reflected in vitals)
            pass
        elif code.startswith("J45"):  # Asthma
            state.ph_status -= s * 0.02  # mild respiratory effect
            state.respiratory_fraction = 1.0  # bronchospasm → respiratory axis
        elif code.startswith(("E11", "E10")):  # Diabetes — chronic glycemic control axis
            gc = getattr(c, "glycemic_control", None)
            if gc is not None:
                state.glycemic_control = gc

    # Perfusion tracks cardiac
    state.perfusion_status = clamp(state.cardiac_function * 0.8 + 0.2, 0.0, 1.0)

    # Clamp all
    state.renal_function = clamp(state.renal_function, 0.05, 1.0)
    state.cardiac_function = clamp(state.cardiac_function, 0.05, 1.0)
    state.hepatic_function = clamp(state.hepatic_function, 0.05, 1.0)
    state.sodium_status = clamp(state.sodium_status, -1.0, 1.0)

    return state


# HbA1c model (chronic glycemic control). Coefficients fixed by generation audit.
HBA1C_NONDM_BASE = 5.1     # %, non-diabetic baseline (mild age term added at use site)
HBA1C_BEST = 6.0           # %, diabetic at perfect control (glycemic_control = 1.0)
HBA1C_SPAN = 6.0           # %, added at glycemic_control = 0.0  -> 12.0% worst case
# Diabetic fasting Glucose baseline as a function of glycemic control.
GLU_DM_BEST = 120.0        # mg/dL at glycemic_control = 1.0
GLU_DM_SPAN = 100.0        # mg/dL added at glycemic_control = 0.0 -> 220 worst
GLYCEMIC_CONTROL_DEFAULT = 0.5   # fallback when has_diabetes but axis unset (e.g. new-onset)


def hba1c_from_glycemic_control(glycemic_control: float) -> float:
    """Typical (noise-free) HbA1c % for a diabetic at this chronic control level.

    glycemic_control: 1.0 = excellent, 0.0 = very poor. Coefficients audit-tuned.
    """
    gc = clamp(glycemic_control, 0.0, 1.0)
    return HBA1C_BEST + (1.0 - gc) * HBA1C_SPAN


_ACID_BASE_RESPIRATORY_FRACTION = {"metabolic": 0.0, "mixed": 0.5, "respiratory": 1.0}


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
        current = getattr(state, var, None)
        if current is not None:
            lo, hi = _variable_range(var)
            setattr(state, var, clamp(current + delta, lo, hi))
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
    # Resolving inflammation allows anemia to recover (bone marrow de-suppression)
    elif state.inflammation_level < 0.2 and state.anemia_level > 0.05:
        state.anemia_level = clamp(
            state.anemia_level - 0.005, 0.0, 1.0
        )

    # Dehydration (free-water deficit) concentrates serum sodium -> hypernatremia.
    if state.volume_status < -0.35:
        state.sodium_status = clamp(
            state.sodium_status + (abs(state.volume_status) - 0.35) * 1.2, -1.0, 1.0
        )


# ---------------------------------------------------------------------------
# Lab value derivation (Layer 2)
# ---------------------------------------------------------------------------

def derive_lab_values(
    state: PhysiologicalState,
    sex: str,
    age: int,
    has_diabetes: bool = False,
    rng: np.random.Generator | None = None,
    hour: int = 6,
    myocardial_injury: bool = False,
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
    # CRP: infl 0→0.3, 0.3→11, 0.5→50, 0.7→138, 1.0→400 mg/L
    labs["CRP"] = 0.3 + 400 * infl ** 3
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
    # K: renal failure causes hyperkalemia, but not as aggressively as before
    # renal 1.0→K 4.0, renal 0.3→K 5.4, renal 0.1→K 6.0, acidosis adds
    labs["K"] = clamp(4.0 + (1 - renal) * 2.2 + max(0, -ph) * 0.8, 2.5, 8.0)
    # Na driven by the dysnatremia axis (chronic HF/cirrhosis hypo, dehydration hyper, SIADH).
    # The old volume term is subsumed by the volume->sodium coupling (apply_coupling_rules).
    labs["Na"] = 140.0 + state.sodium_status * 14.0 - (1 - renal) * 3.0
    labs["Na"] = clamp(labs["Na"], 120, 160)

    # --- Cardiac ---
    # BNP reflects ventricular wall stress = volume/pressure load ON a stressed ventricle.
    # The volume term is gated by cardiac dysfunction (coupling), so volume overload only
    # elevates BNP when the heart is failing: HF (low cardiac x high volume) rises sharply,
    # uncomplicated MI (low cardiac, normal volume) stays moderate, and non-cardiac fluid
    # overload in a preserved heart (cirrhosis ascites, AKI) stays low. Deterministic
    # (state -> lab, no rng). Coefficients tuned by generation audit: with the states the
    # simulator actually produces (HF exacerbation cardiac~0.27/volume~0.56, acute MI
    # cardiac~0.19/volume~0), these give HF exacerbation BNP ~800-1500, MI ~150-300, and
    # non-cardiac < 100 pg/mL.
    labs["BNP"] = 30.0 * math.exp(
        (1 - cardiac) * 2.0 + max(0.0, state.volume_status) * (1 - cardiac) * 5.0
    )
    # Cardiac injury markers. Normal heart (cardiac≈1.0) stays negative so troponin
    # rule-outs in non-cardiac disease read normal; acute injury (MI: cardiac 0.3–0.5)
    # elevates strongly. Steep (^4) so only meaningful dysfunction lifts troponin.
    injury = 1 - cardiac
    # Troponin specificity: ANY cardiac dysfunction (sepsis, PE, AF, stroke) gives only a
    # MILD, capped type-2/demand elevation; only true myocardial necrosis (ACS, flagged by
    # the disease scenario) releases MI-level troponin. Renal impairment reduces clearance →
    # chronic mild elevation (CKD confounder). Keeps non-cardiac labs clinically coherent.
    renal_tnt = (1 - renal) * 0.10
    tnt = 0.01 + min(injury**3 * 8.0, 3.0) + renal_tnt   # type-2 (mild, ≲3 ng/mL)
    ckmb = 0.5 + min(injury**3 * 5.0, 3.0)
    if myocardial_injury:                                # ACS → primary necrosis
        tnt += injury**2 * 120.0
        ckmb += injury**2 * 60.0
    labs["Troponin_I"] = tnt   # ng/mL (normal < 0.04; ACS ~10–100)
    labs["CK_MB"] = ckmb       # ng/mL (normal < 5)

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

    # --- pH / Blood gas (two-axis: metabolic HCO3 + respiratory pCO2, AD-57) ---
    # `ph` is the acid-base disturbance magnitude (neg = acidemia); respiratory_fraction
    # routes it between the metabolic (bicarbonate) and respiratory (CO2) axes. pH then
    # follows Henderson-Hasselbalch on the resulting HCO3/pCO2, with partial compensation
    # by the opposing system — so DKA shows Kussmaul (low pCO2) and chronic COPD shows a
    # raised, compensating HCO3 rather than both moving the same way off one axis.
    rf = clamp(state.respiratory_fraction, 0.0, 1.0)
    mf = 1.0 - rf
    hco3 = 24.0 + ph * mf * 24.0   # metabolic load drives bicarbonate
    pco2 = 40.0 - ph * rf * 40.0   # respiratory load drives CO2 (acidosis → retention)
    if mf > 0.0 and ph != 0.0:
        # Respiratory compensation for a metabolic disturbance (Winter's formula, ~80%).
        winters_pco2 = 1.5 * hco3 + 8.0
        pco2 += 0.8 * (winters_pco2 - 40.0)
    if rf > 0.0 and ph != 0.0:
        # Renal (metabolic) compensation for a respiratory disturbance (~0.35 mEq/mmHg).
        hco3 += 0.35 * (pco2 - 40.0)
    pco2 = clamp(pco2, 15.0, 90.0)
    hco3 = clamp(hco3, 5.0, 45.0)
    labs["HCO3"] = hco3
    labs["pCO2"] = pco2
    labs["pH"] = clamp(6.1 + math.log10(hco3 / (0.03 * pco2)), 6.80, 7.70)
    # pO2: reduced by pulmonary involvement (inflammation as a lung-injury proxy until a
    # dedicated respiratory/oxygenation state variable exists — AD-57 follow-up).
    labs["pO2"] = clamp(95.0 - infl * 45.0, 45.0, 105.0)  # mm[Hg]

    # --- Glucose (chronic diabetes baseline + acute glycemic state + diurnal variation) ---
    is_diabetic = has_diabetes or state.glycemic_control is not None
    gc = state.glycemic_control if state.glycemic_control is not None else GLYCEMIC_CONTROL_DEFAULT
    if is_diabetic:
        base_glu = GLU_DM_BEST + (1.0 - clamp(gc, 0.0, 1.0)) * GLU_DM_SPAN
    else:
        base_glu = 95.0
    # Acute glycemic drive (DKA/HHS push glucose_status up; insulin therapy lowers it).
    gs = state.glucose_status
    if gs >= 0:
        base_glu += gs * 500.0   # hyperglycemia: gs 0.6 ≈ +300 (DKA 300–500 range)
    else:
        base_glu += gs * 55.0    # hypoglycemia: gs -0.5 ≈ -27
    labs["Glucose"] = base_glu
    labs["Glucose"] += infl * 50  # stress hyperglycemia
    # Postprandial rise: meals ~8h, 12h, 18h → peak 1-2h after
    # Fasting (early morning 04-07): lowest
    postprandial = 0.0
    if 9 <= hour <= 10:    # post-breakfast
        postprandial = 25.0
    elif 13 <= hour <= 14:  # post-lunch
        postprandial = 20.0
    elif 19 <= hour <= 20:  # post-dinner
        postprandial = 20.0
    labs["Glucose"] += postprandial
    labs["Glucose"] = clamp(labs["Glucose"], 40.0, 1200.0)  # physiological bounds

    # --- HbA1c (chronic glycemic control; ~3-month average, control-driven) ---
    if is_diabetic:
        labs["HbA1c"] = hba1c_from_glycemic_control(gc)
    else:
        labs["HbA1c"] = HBA1C_NONDM_BASE + max(0, age - 40) * 0.003  # mild age term

    # --- WBC diurnal variation (±10%, afternoon slightly higher) ---
    # Nadir ~04:00, peak ~16:00
    wbc_circadian = 1.0 + 0.10 * math.sin((hour - 4) * math.pi / 12)
    labs["WBC"] *= wbc_circadian

    return labs


# ---------------------------------------------------------------------------
# Vital signs derivation
# ---------------------------------------------------------------------------

# Distributive (vasodilatory) shock hypotension, applied at vitals-derivation only
# (does not mutate perfusion_status). Inflammation above the threshold lowers SBP
# linearly (mmHg per unit inflammation above threshold); DBP drops at 0.6x.
# Coefficient fixed by generation audit (sepsis SBP<90 target ~15-25%).
DISTRIBUTIVE_THRESHOLD = 0.7
DISTRIBUTIVE_SBP_COEFF = 60.0


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
    # Distributive (vasodilatory) hypotension: severe systemic inflammation lowers
    # BP — the mechanism of septic shock. Applied here, at the displayed vital, so
    # it does NOT mutate perfusion_status (which feeds the clinical-course /
    # complication / LOS / mortality RNG); that keeps the master stream stable while
    # still producing hypotension coherent with the already-elevated sepsis labs.
    distributive_drop = max(0.0, infl - DISTRIBUTIVE_THRESHOLD) * DISTRIBUTIVE_SBP_COEFF
    sbp = baseline.systolic_bp + vol * 15 - (1 - perf) * 40 - distributive_drop
    sbp = clamp(sbp, 60, 220)
    dbp = baseline.diastolic_bp + vol * 8 - (1 - perf) * 20 - distributive_drop * 0.6
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
        raw[key] += float(rng.normal(0, 0.5 if key == "temperature" else 2))
        if key == "spo2":
            raw[key] = min(100.0, max(60.0, raw[key]))
    return raw


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
        "respiratory_fraction": (0.0, 1.0),
        "glucose_status": (-1.0, 1.0),
        "sodium_status": (-1.0, 1.0),
    }
    return ranges.get(var, (0.0, 1.0))
