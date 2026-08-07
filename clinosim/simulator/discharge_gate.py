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
    base_rate = benchmarks.get("thirty_day_readmission", 0.15)

    rate = base_rate
    modifier = 1.0

    if record.physiological_states:
        final_infl = record.physiological_states[-1].inflammation_level
        if final_infl > 0.15:
            modifier *= 1.15

    age = record.patient.age
    if age >= 80:
        modifier *= 1.1
    elif age >= 70:
        modifier *= 1.05

    n_chronic = len(record.patient.chronic_conditions)
    modifier += n_chronic * 0.01

    if record.clinical_diagnosis.missed_diagnoses:
        modifier *= 1.2

    rate = base_rate * modifier
    rate = min(rate, base_rate * 1.5)

    if rng.random() >= rate:
        return None

    # F1 (session 49): anchor to *this record's own* discharge, not
    # person.last_discharge_date — the latter is mutated in-place by
    # `_deactivate_to_layer1` after every admission and can silently attach a
    # readmission chain from an EARLIER admission to a LATER admission.
    enc = record.encounters[0] if record.encounters else None
    discharge_date = enc.discharge_datetime.date() if enc and enc.discharge_datetime else None
    if not discharge_date:
        return None

    readmit_days = int(rng.integers(2, 28))
    readmit_date = discharge_date + timedelta(days=readmit_days)

    original_severity = 0.5
    if record.physiological_states:
        original_severity = record.physiological_states[0].inflammation_level
    readmit_severity = min(1.0, original_severity + float(rng.uniform(0.05, 0.15)))

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
    anemia_ok = state.anemia_level < 0.60

    if country_key == "us":
        return (
            state.inflammation_level < 0.10
            and state.perfusion_status > 0.7
            and state.renal_function > 0.5
            and abs(state.volume_status) < 0.3
            and abs(state.ph_status) < 0.2
            and anemia_ok
        )
    return (
        state.inflammation_level < 0.05
        and state.perfusion_status > 0.8
        and state.renal_function > 0.6
        and abs(state.volume_status) < 0.2
        and abs(state.ph_status) < 0.15
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
        day_weight = 1.5 if 2 <= day <= 7 else (0.5 if day > 14 else 1.0)
        daily_base = disease_mortality_rate / max(target_los, 1) * day_weight
        age = patient.age if hasattr(patient, "age") else 70
        individual_mod = 1.0
        if age >= 85:
            individual_mod *= 1.2
        if state.perfusion_status < 0.3:
            individual_mod *= 1.3
        individual_mod = min(individual_mod, 1.8)
        return bool(rng.random() < daily_base * individual_mod)
    daily_base = {"severe": 0.003, "moderate": 0.0005}.get(severity, 0.0001)
    age = patient.age if hasattr(patient, "age") else 70
    age_mult = 1.5 if age >= 85 else (1.2 if age >= 80 else 1.0)
    return bool(rng.random() < daily_base * age_mult)
