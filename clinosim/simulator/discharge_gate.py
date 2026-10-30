"""Discharge gate — readmission risk, mortality evaluation, discharge-ready
criteria.

Extracted from ``simulator/helpers.py`` (Issue #544) so a maintainer working on
discharge logic finds all three concerns in one topic-owned file, rather than a
491-line grab-bag that also holds mortality, department routing, and locale
translation. Callers that historically imported these names from
``simulator/helpers`` continue to work — helpers.py re-exports them for one
deprecation cycle.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np

from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.modules.disease.severity import SEVERITY_SCORE_RANGES
from clinosim.modules.population.engine import LifeEvent
from clinosim.simulator._discharge_gate_thresholds import (
    DISCHARGE_ANEMIA_MAX,
    DISCHARGE_CONSCIOUSNESS_EXCESS_MAX,
    DISCHARGE_INFLAMMATION_SAFE_MAX,
    DISCHARGE_JP_INFLAMMATION_MAX,
    DISCHARGE_JP_PERFUSION_MIN,
    DISCHARGE_JP_PH_ABS_MAX,
    DISCHARGE_JP_RENAL_MIN,
    DISCHARGE_JP_VOLUME_ABS_MAX,
    DISCHARGE_OXYGENATION_EXCESS_MAX,
    DISCHARGE_PERFUSION_SAFE_MIN,
    DISCHARGE_SYMPATHETIC_MAX,
    DISCHARGE_US_INFLAMMATION_MAX,
    DISCHARGE_US_PERFUSION_MIN,
    DISCHARGE_US_PH_ABS_MAX,
    DISCHARGE_US_RENAL_MIN,
    DISCHARGE_US_VOLUME_ABS_MAX,
    MORTALITY_AGE_OLD_MULTIPLIER,
    MORTALITY_AGE_OLD_THRESHOLD,
    MORTALITY_AGE_OLDEST_MULTIPLIER,
    MORTALITY_AGE_OLDEST_THRESHOLD,
    MORTALITY_COMA_MULTIPLIER,
    MORTALITY_DAILY_MODERATE_RATE,
    MORTALITY_DAILY_RATE_FALLBACK,
    MORTALITY_DAILY_SEVERE_RATE,
    MORTALITY_DAY_EARLY_END,
    MORTALITY_DAY_EARLY_START,
    MORTALITY_DAY_EARLY_WEIGHT,
    MORTALITY_DAY_LATE_START,
    MORTALITY_DAY_LATE_WEIGHT,
    MORTALITY_DAY_MID_WEIGHT,
    MORTALITY_DEFAULT_AGE,
    MORTALITY_HYPOXEMIA_MULTIPLIER,
    MORTALITY_INDIVIDUAL_MOD_CAP,
    MORTALITY_LOW_PERFUSION_MULTIPLIER,
    MORTALITY_LOW_PERFUSION_THRESHOLD,
    MORTALITY_SEVERE_HYPOXEMIA_MULTIPLIER,
    MORTALITY_STUPOR_MULTIPLIER,
    MORTALITY_YAML_AGE85_MULTIPLIER,
    READMISSION_AGE_OLDER_MULTIPLIER,
    READMISSION_AGE_OLDER_THRESHOLD,
    READMISSION_AGE_OLDEST_MULTIPLIER,
    READMISSION_AGE_OLDEST_THRESHOLD,
    READMISSION_BASE_RATE_DEFAULT,
    READMISSION_CHRONIC_ADDITIONAL_PER_CONDITION,
    READMISSION_DAYS_MAX_EXCLUSIVE,
    READMISSION_DAYS_MIN,
    READMISSION_FINAL_INFLAMMATION_MULTIPLIER,
    READMISSION_FINAL_INFLAMMATION_THRESHOLD,
    READMISSION_MISSED_DIAGNOSIS_MULTIPLIER,
    READMISSION_ORIGINAL_SEVERITY_FALLBACK,
    READMISSION_RATE_CAP_MULTIPLIER,
    READMISSION_SEVERITY_LIFT_MAX,
    READMISSION_SEVERITY_LIFT_MIN,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.output import CIFPatientRecord


def _evaluate_readmission(
    record: CIFPatientRecord,
    person: Any,
    disease_id: str,
    protocol: DiseaseProtocol,
    country_key: str,
    rng: np.random.Generator,
) -> LifeEvent | None:
    """Evaluate 30-day readmission probability and generate event if triggered.

    Uses YAML benchmark rates as the TARGET rate. Risk modifiers adjust around
    the benchmark but the final rate is clamped near the benchmark range.
    """
    if not protocol.readmission_eligible:
        return None

    benchmarks = protocol.outcome_benchmarks.get(country_key, {})
    base_rate = benchmarks.get("thirty_day_readmission", READMISSION_BASE_RATE_DEFAULT)

    rate = base_rate
    modifier = 1.0

    if record.physiological_states:
        final_infl = record.physiological_states[-1].inflammation_level
        if final_infl > READMISSION_FINAL_INFLAMMATION_THRESHOLD:
            modifier *= READMISSION_FINAL_INFLAMMATION_MULTIPLIER

    age = record.patient.age
    if age >= READMISSION_AGE_OLDEST_THRESHOLD:
        modifier *= READMISSION_AGE_OLDEST_MULTIPLIER
    elif age >= READMISSION_AGE_OLDER_THRESHOLD:
        modifier *= READMISSION_AGE_OLDER_MULTIPLIER

    n_chronic = len(record.patient.chronic_conditions)
    modifier += n_chronic * READMISSION_CHRONIC_ADDITIONAL_PER_CONDITION

    if record.clinical_diagnosis.missed_diagnoses:
        modifier *= READMISSION_MISSED_DIAGNOSIS_MULTIPLIER

    rate = base_rate * modifier
    rate = min(rate, base_rate * READMISSION_RATE_CAP_MULTIPLIER)

    if rng.random() >= rate:
        return None

    # F1: anchor to *this record's own* discharge, not
    # person.last_discharge_date — the latter is mutated in-place by
    # `_deactivate_to_layer1` after every admission and can silently attach a
    # readmission chain from an EARLIER admission to a LATER admission.
    enc = record.encounters[0] if record.encounters else None
    discharge_date = enc.discharge_datetime.date() if enc and enc.discharge_datetime else None
    if not discharge_date:
        return None

    readmit_days = int(rng.integers(READMISSION_DAYS_MIN, READMISSION_DAYS_MAX_EXCLUSIVE))
    readmit_date = discharge_date + timedelta(days=readmit_days)

    original_severity = READMISSION_ORIGINAL_SEVERITY_FALLBACK
    if record.physiological_states:
        original_severity = record.physiological_states[0].inflammation_level
    readmit_severity = min(
        1.0, original_severity + float(rng.uniform(READMISSION_SEVERITY_LIFT_MIN, READMISSION_SEVERITY_LIFT_MAX))
    )
    # Issue #2132: the inflammation proxy is ~0 for non-inflammatory admissions
    # (depression, alcohol withdrawal); never below the disease's minimum.
    minimum = getattr(protocol, "minimum_severity", None)
    if minimum in SEVERITY_SCORE_RANGES:
        readmit_severity = max(readmit_severity, SEVERITY_SCORE_RANGES[minimum][0])

    return LifeEvent(
        person_id=person.person_id,
        event_type="readmission",
        timestamp=readmit_date,
        severity=readmit_severity,
        disease_id=disease_id,
        requires_hospital=True,
        condition_type="known_disease",
        is_readmission=True,
        prior_encounter_id=enc.encounter_id if enc else None,
        readmission_number=(record.readmission_number or 0) + 1,
    )


def unsafe_for_home(state: PhysiologicalState, symptom_floor: dict[str, float] | None) -> bool:
    """True while the patient cannot be sent home (Issues #2055, #2084, #2239):
    uncontrolled autonomic symptoms, hypoxemia or impaired consciousness beyond
    the chronic baseline, hypoperfusion, or uncontrolled systemic inflammation."""
    floor = symptom_floor or {}
    return (
        state.sympathetic_activation >= DISCHARGE_SYMPATHETIC_MAX
        or state.oxygenation_impairment - floor.get("oxygenation_impairment", 0.0) > DISCHARGE_OXYGENATION_EXCESS_MAX
        or state.consciousness_impairment - floor.get("consciousness_impairment", 0.0)
        >= DISCHARGE_CONSCIOUSNESS_EXCESS_MAX
        or state.perfusion_status < DISCHARGE_PERFUSION_SAFE_MIN
        or state.inflammation_level >= DISCHARGE_INFLAMMATION_SAFE_MAX
    )


def discharge_disposition_for(
    final_state: PhysiologicalState, symptom_floor: dict[str, float] | None, died: bool
) -> DischargeDisposition:
    """Expired, skilled nursing facility (still unsafe at the end of the stay),
    or home (Issue #2084)."""
    if died:
        return DischargeDisposition.EXP
    if unsafe_for_home(final_state, symptom_floor):
        return DischargeDisposition.SNF
    return DischargeDisposition.HOME


def _check_discharge_ready(
    state: PhysiologicalState,
    day: int,
    country_key: str,
    symptom_floor: dict[str, float] | None = None,
) -> bool:
    """Check if patient meets state-based discharge criteria.

    Common criteria across diseases: inflammation resolving (CRP proxy),
    hemodynamically stable (perfusion), no acute organ dysfunction.
    JP: stricter (lower inflammation threshold). US: earlier discharge once
    clinically stable.
    """
    # anemia_level < 0.60 ≈ Hgb > 7.0 g/dL for females and > 8.7 for males —
    # no patient should be discharged with Hgb below transfusion trigger.
    anemia_ok = state.anemia_level < DISCHARGE_ANEMIA_MAX
    # Autonomic symptoms, oxygenation, consciousness and perfusion safe for home.
    symptoms_ok = not unsafe_for_home(state, symptom_floor)

    if country_key == "us":
        return (
            state.inflammation_level < DISCHARGE_US_INFLAMMATION_MAX
            and state.perfusion_status > DISCHARGE_US_PERFUSION_MIN
            and state.renal_function > DISCHARGE_US_RENAL_MIN
            and abs(state.volume_status) < DISCHARGE_US_VOLUME_ABS_MAX
            and abs(state.ph_status) < DISCHARGE_US_PH_ABS_MAX
            and anemia_ok
            and symptoms_ok
        )
    return (
        state.inflammation_level < DISCHARGE_JP_INFLAMMATION_MAX
        and state.perfusion_status > DISCHARGE_JP_PERFUSION_MIN
        and state.renal_function > DISCHARGE_JP_RENAL_MIN
        and abs(state.volume_status) < DISCHARGE_JP_VOLUME_ABS_MAX
        and abs(state.ph_status) < DISCHARGE_JP_PH_ABS_MAX
        and anemia_ok
        and symptoms_ok
    )


def extend_stay_for_symptoms(
    state: PhysiologicalState,
    los_ceiling: int,
    max_los: int | None,
    symptom_floor: dict[str, float] | None = None,
) -> bool:
    """Whether to keep the patient one more day past the sampled stay.

    The sampled target LOS caps the daily loop; a patient whose autonomic
    symptoms are still uncontrolled at that point (e.g. alcohol withdrawal
    peaking on day 2-3) stays on, one day at a time, up to the protocol's
    maximum LOS. Conditions that never raise ``sympathetic_activation``
    never extend.
    """
    return max_los is not None and los_ceiling < max_los and unsafe_for_home(state, symptom_floor)


def _mortality_day_weight(day: int) -> float:
    if MORTALITY_DAY_EARLY_START <= day <= MORTALITY_DAY_EARLY_END:
        return MORTALITY_DAY_EARLY_WEIGHT
    if day > MORTALITY_DAY_LATE_START:
        return MORTALITY_DAY_LATE_WEIGHT
    return MORTALITY_DAY_MID_WEIGHT


def mortality_state_multiplier(peak_consciousness: float, peak_oxygenation: float) -> float:
    """Mortality multiplier from the worst consciousness / oxygenation of the
    stay so far (Issue #2098): coma (GCS <= 8 range) and refractory hypoxemia
    carry the risk even after partial recovery, like the ICH score's GCS."""
    mult = 1.0
    if peak_consciousness >= 0.75:
        mult *= MORTALITY_COMA_MULTIPLIER
    elif peak_consciousness >= 0.5:
        mult *= MORTALITY_STUPOR_MULTIPLIER
    if peak_oxygenation >= 0.7:
        mult *= MORTALITY_SEVERE_HYPOXEMIA_MULTIPLIER
    elif peak_oxygenation >= 0.5:
        mult *= MORTALITY_HYPOXEMIA_MULTIPLIER
    return mult


def expected_state_multiplier(protocol: Any) -> float:
    """Average multiplier over the disease's severity mix at presentation
    (``initial_state_impact``), used to renormalise so the disease's overall
    mortality stays at its benchmark while deaths shift to impaired patients."""
    dist = (getattr(protocol, "severity", None) or {}).get("distribution", {}) or {}
    impact = getattr(protocol, "initial_state_impact", None) or {}
    total = sum(float(w) for w in dist.values() if w)
    if total <= 0:
        return 1.0
    expected = 0.0
    for sev, w in dist.items():
        if not w:
            continue
        imp = impact.get(sev) or {}
        expected += (
            float(w)
            / total
            * mortality_state_multiplier(
                float(imp.get("consciousness_impairment", 0.0)), float(imp.get("oxygenation_impairment", 0.0))
            )
        )
    return expected or 1.0


def _evaluate_mortality(
    state: PhysiologicalState,
    patient: Any,
    severity: str,
    day: int,
    rng: np.random.Generator,
    disease_mortality_rate: float = 0.0,
    target_los: int = 14,
    state_relative_risk: float = 1.0,
) -> bool:
    """Daily mortality evaluation using disease-specific benchmark rates.

    If ``disease_mortality_rate`` is provided (from YAML outcome_benchmarks),
    it is the cumulative in-hospital mortality over a ``target_los`` stay,
    spread across days by the day weights.
    """
    if disease_mortality_rate > 0:
        # Normalise by the weight total over the planned stay so the summed
        # daily hazard over target_los equals the YAML cumulative rate.
        weight_total = sum(_mortality_day_weight(d) for d in range(max(target_los, 1)))
        daily_base = disease_mortality_rate * _mortality_day_weight(day) / weight_total
        age = patient.age if hasattr(patient, "age") else MORTALITY_DEFAULT_AGE
        individual_mod = 1.0
        if age >= MORTALITY_AGE_OLDEST_THRESHOLD:
            individual_mod *= MORTALITY_YAML_AGE85_MULTIPLIER
        if state.perfusion_status < MORTALITY_LOW_PERFUSION_THRESHOLD:
            individual_mod *= MORTALITY_LOW_PERFUSION_MULTIPLIER
        individual_mod *= state_relative_risk
        individual_mod = min(individual_mod, MORTALITY_INDIVIDUAL_MOD_CAP)
        return bool(rng.random() < daily_base * individual_mod)
    daily_base = {"severe": MORTALITY_DAILY_SEVERE_RATE, "moderate": MORTALITY_DAILY_MODERATE_RATE}.get(
        severity, MORTALITY_DAILY_RATE_FALLBACK
    )
    age = patient.age if hasattr(patient, "age") else MORTALITY_DEFAULT_AGE
    if age >= MORTALITY_AGE_OLDEST_THRESHOLD:
        age_mult = MORTALITY_AGE_OLDEST_MULTIPLIER
    elif age >= MORTALITY_AGE_OLD_THRESHOLD:
        age_mult = MORTALITY_AGE_OLD_MULTIPLIER
    else:
        age_mult = 1.0
    return bool(rng.random() < daily_base * age_mult)
