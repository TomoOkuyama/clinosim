"""Vitals / IO / ADL per-day generators (Issue #552 PR B).

Extracted verbatim from ``clinosim/simulator/inpatient.py`` — no logic
changes. Groups the 5 per-day physiological-observation producers plus
their supporting frozensets into a single topic-owned module.

The functions here consume the master RNG in a specific order (the
`_generate_vitals` inner `_emit` closure calls `_o2_for` and `_loc_for`
which draw from the same RNG). Extraction preserves the byte-neutral
contract: no reordering, no logic changes, only a name move.

Public per-day API (called from `inpatient.py::_run_daily_loop` and
from `unknown_condition.py::_simulate_unknown_condition`):

* ``_generate_vitals`` — the daily vitals producer (routine full sets +
  febrile rechecks + continuous monitor).
* ``_generate_daily_io`` — the intake/output record.
* ``_generate_adl_assessment`` — the Barthel-index ADL scoring
  (admission, weekly, discharge).

Internal helpers (kept private to this module):

* ``_make_raw`` — a thin wrapper around ``derive_observed_vitals``.
* ``_o2_for`` — the SpO2 → oxygen-therapy dispatcher.
* ``_loc_for`` — the AVPU consciousness-level inference.

Supporting sets:

* ``_RESPIRATORY_DISEASES`` — disease ids that trigger continuous SpO2
  monitoring on stable-severity patients. Different from
  ``clinosim.modules.disease.acuity.CRITICAL_MONITORING_DISEASES``
  (which is the priority-code / q1-2h set) — the two intentionally
  diverge (see Issue #563 for the aligned pair vs this respiratory set).
* ``_NEURO_DISEASES`` — the 6-disease perfusion-based LOC assessment set.
  Different from ``NEURO_LOC_MONITORING_DISEASES`` (2 diseases, days
  0-2 only — see the acuity module docstring).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from clinosim.modules.disease.acuity import (
    CRITICAL_MONITORING_DISEASES,
    NEURO_LOC_MONITORING_DISEASES,
)
from clinosim.modules.observation.fluid_balance import (
    AGGRESSIVE_IV_ML,
    AGGRESSIVE_IV_SD,
    ANURIA_FLOOR_ML,
    DEHYDRATION_IV_ML,
    DEHYDRATION_IV_SD,
    DEHYDRATION_IV_TRIGGER,
    MAINTENANCE_IV_ML,
    MAINTENANCE_IV_SD,
)
from clinosim.modules.observation.oxygenation import SPO2_HYPOXEMIA_TRIGGER, SPO2_SEVERE_HYPOXEMIA
from clinosim.modules.observation.vitals_thresholds import (
    FEBRILE_RECHECK_PROB,
    FEBRILE_RECHECK_WINDOW_MIN,
    FEVER_THRESHOLD_C,
    HIGH_FEVER_RECHECK_C,
)
from clinosim.modules.physiology.engine import derive_observed_vitals
from clinosim.simulator._adl_thresholds import (
    ADL_ASSESSMENT_INTERVAL_DAYS,
    ADL_BARTHEL_MAX,
    ADL_BARTHEL_MIN,
    ADL_BARTHEL_NOISE_SD,
    ADL_COMP_BATHING_MAX,
    ADL_COMP_BLADDER_MAX,
    ADL_COMP_BOWEL_MAX,
    ADL_COMP_DRESSING_MAX,
    ADL_COMP_FEEDING_MAX,
    ADL_COMP_GROOMING_MAX,
    ADL_COMP_MOBILITY_MAX,
    ADL_COMP_STAIRS_MAX,
    ADL_COMP_TOILET_MAX,
    ADL_COMP_TRANSFERS_MAX,
    ADL_DAY0_ACUTE_PENALTY,
    ADL_INFLAMMATION_PENALTY_SCALE,
    ADL_OLDER_AGE_PENALTY,
    ADL_OLDER_AGE_THRESHOLD,
    ADL_OLDEST_AGE_PENALTY,
    ADL_OLDEST_AGE_THRESHOLD,
    ADL_PERFUSION_PENALTY_SCALE,
    ADL_RATIO_OFFSET_BLADDER,
    ADL_RATIO_OFFSET_BOWEL,
    ADL_RATIO_OFFSET_FEEDING,
    ADL_RATIO_OFFSET_GROOMING,
    ADL_RATIO_OFFSET_STAIRS_DEFICIT,
    ADL_RECOVERY_MAX_TOTAL,
    ADL_RECOVERY_PER_DAY,
    ADL_RENAL_PENALTY_SCALE,
)
from clinosim.simulator._daily_io_thresholds import (
    IO_EARLY_DAY_THRESHOLD,
    IO_ORAL_DAY0_MEAN_ML,
    IO_ORAL_DAY0_STD_ML,
    IO_ORAL_POOR_APPETITE_MEAN_ML,
    IO_ORAL_POOR_APPETITE_STD_ML,
    IO_ORAL_RECOVERING_MEAN_ML,
    IO_ORAL_RECOVERING_STD_ML,
    IO_POOR_APPETITE_INFLAMMATION_THRESHOLD,
    IO_URINE_BASE_ML_PER_UNIT_RENAL,
    IO_URINE_SD_FLOOR_ML,
    IO_URINE_SD_RATIO,
)
from clinosim.simulator._loc_thresholds import (
    LOC_MODERATE_HYPOPERFUSION_THRESHOLD,
    LOC_MODERATE_V_OVER_P_PROBABILITY,
    LOC_NEURO_EARLY_DAY_MAX,
    LOC_NEURO_EARLY_WEIGHTS_AVP,
    LOC_NEURO_MILD_HYPOPERFUSION_THRESHOLD,
    LOC_NEURO_MILD_V_OVER_A_PROBABILITY,
    LOC_REFRACTORY_SHOCK_THRESHOLD,
    LOC_REFRACTORY_U_OVER_P_PROBABILITY,
)
from clinosim.simulator._oxygen_therapy_thresholds import (
    O2_MILD_FLOW_LPM_MAX,
    O2_MILD_FLOW_LPM_MIN,
    O2_MODERATE_FLOW_LPM_MAX,
    O2_MODERATE_FLOW_LPM_MIN,
    O2_NASAL_CANNULA_FLOW_MAX_LPM,
    O2_NON_REBREATHER_FLOW_MIN_LPM,
    O2_SEVERE_FLOW_LPM_MAX,
    O2_SEVERE_FLOW_LPM_MIN,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import (
    ADLAssessment,
    IntakeOutputRecord,
    VitalSignRecord,
)
from clinosim.types.patient import PatientProfile

_RESPIRATORY_DISEASES = {
    "bacterial_pneumonia",
    "aspiration_pneumonia",
    "copd_exacerbation",
    "asthma_exacerbation",
    "pulmonary_embolism",
}
_NEURO_DISEASES = {
    "cerebral_infarction",
    "hemorrhagic_stroke",
    "subdural_hematoma",
    "diabetic_ketoacidosis",
    "sepsis",
    "liver_cirrhosis_decompensated",
}


def _generate_adl_assessment(
    state: PhysiologicalState,
    patient: PatientProfile,
    day: int,
    admission_time: datetime,
    rng: np.random.Generator,
) -> ADLAssessment | None:
    """Generate ADL (Barthel Index) assessment. Done on admission, weekly, and discharge."""
    # ADL assessed on admission (day 0), weekly (day 7, 14...), and approaching discharge
    if day != 0 and day % ADL_ASSESSMENT_INTERVAL_DAYS != 0:
        return None

    # Base score depends on age and clinical state
    age = patient.age
    base = ADL_BARTHEL_MAX
    if age >= ADL_OLDEST_AGE_THRESHOLD:
        base -= ADL_OLDEST_AGE_PENALTY
    elif age >= ADL_OLDER_AGE_THRESHOLD:
        base -= ADL_OLDER_AGE_PENALTY

    # Acute illness reduces ADL
    infl_penalty = int(state.inflammation_level * ADL_INFLAMMATION_PENALTY_SCALE)
    perf_penalty = int((1.0 - state.perfusion_status) * ADL_PERFUSION_PENALTY_SCALE)
    renal_penalty = int((1.0 - state.renal_function) * ADL_RENAL_PENALTY_SCALE)

    # Day 0: worst ADL (acute admission)
    if day == 0:
        total = max(ADL_BARTHEL_MIN, base - infl_penalty - perf_penalty - renal_penalty - ADL_DAY0_ACUTE_PENALTY)
    else:
        # Gradual recovery
        recovery = min(day * ADL_RECOVERY_PER_DAY, ADL_RECOVERY_MAX_TOTAL)
        total = max(ADL_BARTHEL_MIN, min(ADL_BARTHEL_MAX, base - infl_penalty - perf_penalty + recovery))

    total = int(rng.normal(total, ADL_BARTHEL_NOISE_SD))
    total = max(ADL_BARTHEL_MIN, min(ADL_BARTHEL_MAX, total))

    # Distribute across components proportionally
    ratio = total / ADL_BARTHEL_MAX
    return ADLAssessment(
        date=(admission_time + timedelta(days=day)).date(),
        barthel_score=total,
        feeding=int(ADL_COMP_FEEDING_MAX * min(1, ratio + ADL_RATIO_OFFSET_FEEDING)),
        bathing=int(ADL_COMP_BATHING_MAX * ratio),
        grooming=int(ADL_COMP_GROOMING_MAX * min(1, ratio + ADL_RATIO_OFFSET_GROOMING)),
        dressing=int(ADL_COMP_DRESSING_MAX * ratio),
        bowel_control=int(ADL_COMP_BOWEL_MAX * min(1, ratio + ADL_RATIO_OFFSET_BOWEL)),
        bladder_control=int(ADL_COMP_BLADDER_MAX * min(1, ratio + ADL_RATIO_OFFSET_BLADDER)),
        toilet_use=int(ADL_COMP_TOILET_MAX * ratio),
        transfers=int(ADL_COMP_TRANSFERS_MAX * ratio),
        mobility=int(ADL_COMP_MOBILITY_MAX * ratio),
        stairs=int(ADL_COMP_STAIRS_MAX * max(0, ratio - ADL_RATIO_OFFSET_STAIRS_DEFICIT)),
    )


def _generate_daily_io(
    state: PhysiologicalState,
    patient: PatientProfile,
    day: int,
    admission_time: datetime,
    rng: np.random.Generator,
) -> IntakeOutputRecord:
    """Generate daily intake/output record."""
    # IV fluid: higher in early days, less as patient improves
    if day <= IO_EARLY_DAY_THRESHOLD:
        iv = int(rng.normal(AGGRESSIVE_IV_ML, AGGRESSIVE_IV_SD))  # aggressive hydration
    elif state.volume_status < DEHYDRATION_IV_TRIGGER:
        iv = int(rng.normal(DEHYDRATION_IV_ML, DEHYDRATION_IV_SD))  # dehydrated
    else:
        iv = int(rng.normal(MAINTENANCE_IV_ML, MAINTENANCE_IV_SD))  # maintenance

    # Oral intake: improves as patient recovers
    if day == 0:
        oral = int(rng.normal(IO_ORAL_DAY0_MEAN_ML, IO_ORAL_DAY0_STD_ML))  # NPO or minimal
    elif state.inflammation_level > IO_POOR_APPETITE_INFLAMMATION_THRESHOLD:
        oral = int(rng.normal(IO_ORAL_POOR_APPETITE_MEAN_ML, IO_ORAL_POOR_APPETITE_STD_ML))  # poor appetite
    else:
        oral = int(rng.normal(IO_ORAL_RECOVERING_MEAN_ML, IO_ORAL_RECOVERING_STD_ML))  # recovering

    # Urine output: correlates with renal function and hydration
    base_urine = IO_URINE_BASE_ML_PER_UNIT_RENAL * state.renal_function
    urine_sd = max(IO_URINE_SD_FLOOR_ML, base_urine * IO_URINE_SD_RATIO)  # SD proportional to base
    urine = int(max(ANURIA_FLOOR_ML, rng.normal(base_urine, urine_sd)))  # min 50ml (anuria threshold)

    # Drain (post-surgical only, simplified)
    drain = 0

    iv = max(0, iv)
    oral = max(0, oral)
    total_in = iv + oral
    total_out = urine + drain
    net = total_in - total_out

    io_date = (admission_time + timedelta(days=day)).date()
    return IntakeOutputRecord(
        date=io_date,
        intake_iv_ml=iv,
        intake_oral_ml=oral,
        output_urine_ml=urine,
        output_drain_ml=drain,
        net_balance_ml=net,
    )


def _make_raw(state, patient, vit_time, rng):
    return derive_observed_vitals(state, patient.baseline_vitals, vit_time, rng)


def _o2_for(spo2, disease_id, rng):
    """Return (on_o2, flow, device)."""
    needs = (
        spo2 < SPO2_HYPOXEMIA_TRIGGER
        or disease_id in _RESPIRATORY_DISEASES
        or disease_id == "heart_failure_exacerbation"
    )
    if not needs:
        return False, None, ""
    if spo2 < SPO2_SEVERE_HYPOXEMIA:
        flow = float(rng.uniform(O2_SEVERE_FLOW_LPM_MIN, O2_SEVERE_FLOW_LPM_MAX))
        device = "non-rebreather" if flow >= O2_NON_REBREATHER_FLOW_MIN_LPM else "simple_mask"
    elif spo2 < SPO2_HYPOXEMIA_TRIGGER:
        flow = float(rng.uniform(O2_MODERATE_FLOW_LPM_MIN, O2_MODERATE_FLOW_LPM_MAX))
        device = "nasal_cannula" if flow <= O2_NASAL_CANNULA_FLOW_MAX_LPM else "simple_mask"
    else:
        flow = float(rng.uniform(O2_MILD_FLOW_LPM_MIN, O2_MILD_FLOW_LPM_MAX))
        device = "nasal_cannula"
    return True, flow, device


def _loc_for(state, disease_id, day, rng):
    """Infer AVPU consciousness level."""
    if state.perfusion_status < LOC_REFRACTORY_SHOCK_THRESHOLD:
        # Refractory shock / severe neuro insult — matches the sepsis.yaml
        # severe-septic-shock complication threshold (perfusion_status < 0.2).
        return "U" if rng.random() < LOC_REFRACTORY_U_OVER_P_PROBABILITY else "P"
    if state.perfusion_status < LOC_MODERATE_HYPOPERFUSION_THRESHOLD:
        return "V" if rng.random() < LOC_MODERATE_V_OVER_P_PROBABILITY else "P"
    if state.perfusion_status < LOC_NEURO_MILD_HYPOPERFUSION_THRESHOLD and disease_id in _NEURO_DISEASES:
        return "V" if rng.random() < LOC_NEURO_MILD_V_OVER_A_PROBABILITY else "A"
    if disease_id in NEURO_LOC_MONITORING_DISEASES and day <= LOC_NEURO_EARLY_DAY_MAX:
        return str(rng.choice(["A", "V", "P"], p=LOC_NEURO_EARLY_WEIGHTS_AVP))
    return "A"


def _generate_vitals(
    state: PhysiologicalState,
    patient: PatientProfile,
    day: int,
    admission_time: datetime,
    rng: np.random.Generator,
    disease_id: str = "",
    nurse_id: str = "",
    country: str = "US",
) -> list[VitalSignRecord]:
    """Generate vital sign measurements for this day.

    Realistic patterns:
    - Routine full vitals (T/HR/BP/RR/SpO2) at scheduled rounds (acuity-based frequency)
    - Continuous bedside monitoring (HR/SpO2 only) for unstable / respiratory patients
    - Event-driven re-checks: febrile recheck (Temp only), low SpO2 recheck
    - Within-set time offsets (BP/HR same moment, Temp ±30s, RR ±60s)
    """
    vitals: list[VitalSignRecord] = []
    is_unstable = state.perfusion_status < 0.5 or state.inflammation_level > 0.5
    is_respiratory = disease_id in _RESPIRATORY_DISEASES or disease_id == "heart_failure_exacerbation"

    # Routine full-vitals schedule by acuity
    # Critically unstable (septic shock, acute MI, hemorrhagic stroke, subdural
    # hematoma, severe trauma): q1-2h. Set defined in
    # `clinosim.modules.disease.acuity.CRITICAL_MONITORING_DISEASES` — Issue
    # #563 added `subdural_hematoma` to close the drift with EMERGENCY_PRIORITY.
    is_critical = state.perfusion_status < 0.3 or disease_id in CRITICAL_MONITORING_DISEASES
    if is_critical and day <= 2:
        full_hours = list(range(0, 24, 2))  # q2h (12 sets/day)
    elif is_unstable:
        full_hours = [2, 6, 10, 14, 18, 22]  # q4h (6 sets/day)
    elif day <= 2:
        full_hours = [0, 6, 12, 18]  # q6h
    elif state.inflammation_level < 0.1 and day >= 7:
        full_hours = [6, 18]  # bid (stable, late stay)
    else:
        full_hours = [6, 14, 22]  # tid

    def _emit(time: datetime, *, fields: set[str], raw: dict, note: str = "") -> None:
        """Emit a VitalSignRecord with only the specified fields populated."""
        on_o2, o2_flow, o2_device = (False, None, "")
        if "spo2" in fields:
            on_o2, o2_flow, o2_device = _o2_for(raw["spo2"], disease_id, rng)
        loc = _loc_for(state, disease_id, day, rng) if "loc" in fields else ""
        # Pain only with full set
        pain = None
        if "pain" in fields:
            base_pain = state.inflammation_level * 4
            if day <= 2:
                base_pain += 2
            pain = int(max(0, min(10, rng.normal(base_pain, 1.5))))
        vitals.append(
            VitalSignRecord(
                timestamp=time,
                temperature_celsius=round(raw["temperature"], 1) if "temp" in fields else None,
                heart_rate=int(round(raw["heart_rate"])) if "hr" in fields else None,
                systolic_bp=int(round(raw["systolic_bp"])) if "bp" in fields else None,
                diastolic_bp=int(round(raw["diastolic_bp"])) if "bp" in fields else None,
                respiratory_rate=int(round(raw["respiratory_rate"])) if "rr" in fields else None,
                spo2=round(raw["spo2"], 1) if "spo2" in fields else None,
                pain_score=pain,
                consciousness_level=loc,
                on_supplemental_oxygen=on_o2,
                oxygen_flow_rate_lpm=round(o2_flow, 1) if o2_flow else None,
                oxygen_delivery_device=o2_device,
                nursing_note=note,
                measured_by=nurse_id,
                data_source="manual",
            )
        )

    # 1. Routine full vitals at scheduled rounds
    for hour in full_hours:
        vit_time = datetime(admission_time.year, admission_time.month, admission_time.day, hour, 0) + timedelta(
            days=day
        )  # noqa: E501
        if vit_time < admission_time:
            continue
        raw = _make_raw(state, patient, vit_time, rng)
        actual_time = vit_time + timedelta(minutes=float(rng.normal(0, 10)))

        # CIF stores English nursing notes (AD-30). JP translation at FHIR output.
        note_parts = []
        if raw["temperature"] >= FEVER_THRESHOLD_C:
            note_parts.append("febrile")
        if raw["spo2"] < 93:
            note_parts.append("SpO2 low, O2 adjusted")
        if state.inflammation_level < 0.1 and day >= 3:
            note_parts.append("improving, appetite good")
        if day == 0 and hour == full_hours[0]:
            note_parts.append("admission assessment completed")
        note = ". ".join(note_parts) + "." if note_parts else ""

        _emit(actual_time, fields={"temp", "hr", "bp", "rr", "spo2", "pain", "loc"}, raw=raw, note=note)

        # 1a. Febrile re-check: re-measure temperature 30-60 min later
        if raw["temperature"] >= HIGH_FEVER_RECHECK_C and rng.random() < FEBRILE_RECHECK_PROB:
            recheck_time = actual_time + timedelta(minutes=int(rng.uniform(*FEBRILE_RECHECK_WINDOW_MIN)))
            recheck_raw = _make_raw(state, patient, recheck_time, rng)
            _emit(
                recheck_time,
                fields={"temp"},
                raw=recheck_raw,
                note=f"febrile recheck after {recheck_time.minute - actual_time.minute} min",
            )

    # 2. Continuous bedside monitoring (HR + SpO2 only) every ~2h
    #    for unstable / respiratory / cardiac patients
    if is_unstable or is_respiratory:
        full_hour_set = set(full_hours)
        # Pick hours not already covered by full vitals
        monitor_hours = [h for h in range(1, 24, 2) if h not in full_hour_set]
        for hour in monitor_hours:
            mon_time = datetime(admission_time.year, admission_time.month, admission_time.day, hour, 0) + timedelta(
                days=day
            )  # noqa: E501
            if mon_time < admission_time:
                continue
            mon_time += timedelta(minutes=float(rng.normal(0, 5)))
            raw = _make_raw(state, patient, mon_time, rng)
            _emit(mon_time, fields={"hr", "spo2"}, raw=raw, note="continuous monitor")

    return vitals
