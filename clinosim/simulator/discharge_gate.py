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

from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.modules.population.engine import LifeEvent
from clinosim.simulator._discharge_gate_thresholds import (
    DISCHARGE_ANEMIA_MAX,
    DISCHARGE_JP_INFLAMMATION_MAX,
    DISCHARGE_JP_PERFUSION_MIN,
    DISCHARGE_JP_PH_ABS_MAX,
    DISCHARGE_JP_RENAL_MIN,
    DISCHARGE_JP_VOLUME_ABS_MAX,
    DISCHARGE_US_INFLAMMATION_MAX,
    DISCHARGE_US_PERFUSION_MIN,
    DISCHARGE_US_PH_ABS_MAX,
    DISCHARGE_US_RENAL_MIN,
    DISCHARGE_US_VOLUME_ABS_MAX,
    MORTALITY_AGE_OLD_MULTIPLIER,
    MORTALITY_AGE_OLD_THRESHOLD,
    MORTALITY_AGE_OLDEST_MULTIPLIER,
    MORTALITY_AGE_OLDEST_THRESHOLD,
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
    MORTALITY_INDIVIDUAL_MOD_CAP,
    MORTALITY_LOW_PERFUSION_MULTIPLIER,
    MORTALITY_LOW_PERFUSION_THRESHOLD,
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


def _check_discharge_ready(
    state: PhysiologicalState,
    day: int,
    country_key: str,
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

    if country_key == "us":
        return (
            state.inflammation_level < DISCHARGE_US_INFLAMMATION_MAX
            and state.perfusion_status > DISCHARGE_US_PERFUSION_MIN
            and state.renal_function > DISCHARGE_US_RENAL_MIN
            and abs(state.volume_status) < DISCHARGE_US_VOLUME_ABS_MAX
            and abs(state.ph_status) < DISCHARGE_US_PH_ABS_MAX
            and anemia_ok
        )
    return (
        state.inflammation_level < DISCHARGE_JP_INFLAMMATION_MAX
        and state.perfusion_status > DISCHARGE_JP_PERFUSION_MIN
        and state.renal_function > DISCHARGE_JP_RENAL_MIN
        and abs(state.volume_status) < DISCHARGE_JP_VOLUME_ABS_MAX
        and abs(state.ph_status) < DISCHARGE_JP_PH_ABS_MAX
        and anemia_ok
    )


def _evaluate_mortality(
    state: PhysiologicalState,
    patient: Any,
    severity: str,
    day: int,
    rng: np.random.Generator,
    disease_mortality_rate: float = 0.0,
    target_los: int = 14,
) -> bool:
    """Daily mortality evaluation using disease-specific benchmark rates.

    If ``disease_mortality_rate`` is provided (from YAML outcome_benchmarks),
    it is used as the total in-hospital mortality rate and spread across LOS.
    """
    if disease_mortality_rate > 0:
        if MORTALITY_DAY_EARLY_START <= day <= MORTALITY_DAY_EARLY_END:
            day_weight = MORTALITY_DAY_EARLY_WEIGHT
        elif day > MORTALITY_DAY_LATE_START:
            day_weight = MORTALITY_DAY_LATE_WEIGHT
        else:
            day_weight = MORTALITY_DAY_MID_WEIGHT
        daily_base = disease_mortality_rate / max(target_los, 1) * day_weight
        age = patient.age if hasattr(patient, "age") else MORTALITY_DEFAULT_AGE
        individual_mod = 1.0
        if age >= MORTALITY_AGE_OLDEST_THRESHOLD:
            individual_mod *= MORTALITY_YAML_AGE85_MULTIPLIER
        if state.perfusion_status < MORTALITY_LOW_PERFUSION_THRESHOLD:
            individual_mod *= MORTALITY_LOW_PERFUSION_MULTIPLIER
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
