"""Helper functions for simulator — protocol loading, discharge checks, utilities."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np

from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.modules.disease.protocol import (  # noqa: F401 (re-export alias)
    load_all_disease_protocols as _load_all_disease_protocols,
)
from clinosim.modules.population.engine import HospitalizationSummary, LifeEvent
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

# ``_load_all_disease_protocols`` is a thin re-export alias of the canonical
# cached aggregate loader that now lives in ``modules/disease/protocol.py``
# (loader-commonization refactor). Sharing the same lru_cache object keeps the
# existing ``.cache_clear()`` / ``.cache_info()`` call sites and importers
# (simulator/__init__.py, engine.py, cli.py) working unchanged.


def _deactivate_to_layer1(
    person: Any,
    record: CIFPatientRecord,
    disease_id: str,
) -> None:
    """Feed hospital results back to Layer 1 PersonRecord after discharge.

    Updates chronic conditions, medications, and hospitalization history
    so future encounters can reference the patient's medical history.
    """
    person.has_visited_hospital = True
    person.visit_count += 1

    # Encounter tracking
    if record.encounters:
        enc = record.encounters[0]
        person.last_encounter_id = enc.encounter_id
        person.last_disease_id = disease_id
        if enc.discharge_datetime:
            person.last_discharge_date = enc.discharge_datetime.date()

    # Add new diagnoses to chronic conditions
    dx_code = record.clinical_diagnosis.discharge_diagnosis_code
    if dx_code:
        # Normalize to base code (e.g., "J44.1" → "J44") for chronic condition tracking
        base_code = dx_code.split(".")[0] if "." in dx_code else dx_code
        # Only add if it's a chronic/recurring condition and not already present
        chronic_prefixes = ("I", "E", "J44", "J45", "N18", "M", "G20", "F00", "K21", "N40")
        # Session 45 seed=400 verification finding: N40 (BPH) is anatomically
        # male-only; sibling with the sex-guard added to `inpatient.py`
        # `_IMPLIED_CHRONIC_BY_DISEASE`. Prevent discharge-Dx propagation from
        # attaching N40 (or any future sex-restricted ICD) to the wrong sex.
        _SEX_RESTRICTED_ICD = {"N40": "M"}
        _patient_sex = str(getattr(person, "sex", "") or "").upper()[:1]
        _sex_req = _SEX_RESTRICTED_ICD.get(base_code)
        if _sex_req and _patient_sex and _sex_req != _patient_sex:
            pass  # skip; wrong sex for this ICD
        elif any(base_code.startswith(p) for p in chronic_prefixes):
            # Check if base code already in chronic conditions
            existing_bases = {c.split(".")[0] for c in person.chronic_conditions}
            if base_code not in existing_bases:
                person.chronic_conditions.append(base_code)

    # Update medications: discharge prescriptions become current medications
    if record.discharge_prescription and record.discharge_prescription.items:
        person.current_medications = [
            drug_name
            for item in record.discharge_prescription.items
            if isinstance(item, dict)
            for drug_name in [item.get("drug_name", item.get("drug", item.get("name", "")))]
            if drug_name  # filter out empty strings
        ]

    # Residual physiological state at discharge
    residual_infl = 0.0
    residual_renal = 1.0
    if record.physiological_states:
        final = record.physiological_states[-1]
        residual_infl = final.inflammation_level
        residual_renal = final.renal_function

    # Build hospitalization summary
    admission_date = record.encounters[0].admission_datetime.date() if record.encounters else None
    discharge_date = person.last_discharge_date
    if admission_date and discharge_date:
        los = (discharge_date - admission_date).days
    else:
        los = len(record.physiological_states) - 1

    summary = HospitalizationSummary(
        encounter_id=person.last_encounter_id or "",
        disease_id=disease_id,
        admission_date=admission_date or discharge_date or record.encounters[0].admission_datetime.date(),
        discharge_date=discharge_date or admission_date or record.encounters[0].admission_datetime.date(),
        los_days=max(1, los),
        outcome="deceased" if record.deceased else "discharged",
        discharge_diagnoses=[dx_code] if dx_code else [disease_id],
        discharge_medications=person.current_medications.copy(),
        residual_inflammation=residual_infl,
        residual_renal=residual_renal,
        was_readmission=record.is_readmission,
    )
    person.hospitalization_history.append(summary)


def _select_secondary_disease(
    patient: PatientProfile,
    primary_disease_id: str,
    protocols: dict[str, DiseaseProtocol],
    rng: np.random.Generator,
) -> DiseaseProtocol | None:
    """Select a secondary disease for mixed conditions based on patient's chronic diseases.

    Priority: diseases whose prerequisite_condition matches patient's chronic conditions.
    Fallback: any non-surgical disease different from primary.
    """
    # Find candidate diseases (non-surgical, different from primary)
    matching = []
    for did, proto in protocols.items():
        if did == primary_disease_id or proto.requires_surgery:
            continue
        # Check demographics YAML prerequisite — read from incidence data isn't available here,
        # but we can check if the disease name implies a chronic condition match
        # Use a simpler approach: any medical disease the patient could plausibly have
        matching.append(proto)

    if not matching:
        return None

    # Prefer diseases related to patient's comorbidities
    # Pneumonia is common secondary for any hospitalized patient
    preferred = [p for p in matching if p.disease_id == "bacterial_pneumonia"]
    if preferred:
        return preferred[0]

    return rng.choice(matching)


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
    # Check if this disease type is eligible for same-disease readmission
    if not protocol.readmission_eligible:
        return None

    benchmarks = protocol.outcome_benchmarks.get(country_key, {})
    base_rate = benchmarks.get("thirty_day_readmission", 0.15)

    # Start from base rate, apply modest modifiers
    rate = base_rate

    # Risk modifiers — all modest, multiplicative effects compound
    modifier = 1.0

    # Residual inflammation at discharge (incomplete recovery)
    if record.physiological_states:
        final_infl = record.physiological_states[-1].inflammation_level
        if final_infl > 0.15:
            modifier *= 1.15

    # Age (elderly more likely to bounce back)
    age = record.patient.age
    if age >= 80:
        modifier *= 1.1
    elif age >= 70:
        modifier *= 1.05

    # Comorbidity burden (small additive)
    n_chronic = len(record.patient.chronic_conditions)
    modifier += n_chronic * 0.01

    # Diagnosis accuracy
    if record.clinical_diagnosis.missed_diagnoses:
        modifier *= 1.2

    rate = base_rate * modifier
    # Clamp: stay within 50% of benchmark
    rate = min(rate, base_rate * 1.5)

    if rng.random() >= rate:
        return None

    discharge_date = person.last_discharge_date
    if not discharge_date:
        return None

    readmit_days = int(rng.integers(2, 28))
    readmit_date = discharge_date + timedelta(days=readmit_days)

    # Readmission severity: slightly higher than original
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
        prior_encounter_id=person.last_encounter_id,
        readmission_number=(record.readmission_number or 0) + 1,
    )


def _country_to_yaml_key(country: str) -> str:
    """Convert country code to disease YAML key."""
    return {"JP": "japan", "US": "us"}.get(country, "us")


def _disease_chief_complaint(protocol: DiseaseProtocol, country: str = "US") -> str:
    """Get chief complaint from disease protocol YAML (multi-language support)."""
    from clinosim.locale.text import resolve_text
    # CIF stores English always (AD-30). JP chief complaint resolved at FHIR output time.
    return resolve_text(protocol.chief_complaint, language="en") or "General malaise"


def _disease_to_department(protocol: DiseaseProtocol) -> str:
    """Get the granular department from disease protocol YAML."""
    return protocol.department or "internal_medicine"


def resolve_department(
    granular_dept: str,
    hospital_ops: dict | None,
) -> str:
    """Resolve a granular specialty to an available department at this hospital.

    Uses hospital_ops.department_rollup to map specialties (e.g., pulmonology)
    to one of hospital_ops.available_departments (e.g., internal_medicine).
    Falls back to internal_medicine if neither matches.
    """
    if not hospital_ops:
        return granular_dept or "internal_medicine"

    available = set(hospital_ops.get("available_departments", []))
    rollup = hospital_ops.get("department_rollup", {}) or {}

    # If the granular department is directly available, use it
    if granular_dept in available:
        return granular_dept

    # Otherwise, look up rollup
    rolled = rollup.get(granular_dept)
    if rolled and rolled in available:
        return rolled

    # Fallbacks: internal_medicine → first available → granular as-is
    if "internal_medicine" in available:
        return "internal_medicine"
    if available:
        return next(iter(available))
    return granular_dept or "internal_medicine"


def pick_ward(department: str, hospital_ops: dict | None, rng: Any) -> str:
    """Pick a ward_id for the given department from hospital config."""
    if hospital_ops:
        wards_map = hospital_ops.get("wards", {}) or {}
        options = wards_map.get(department, [])
        if options:
            return str(rng.choice(options)) if len(options) > 1 else options[0]
    # Fallback
    return "4E"


def _determine_route(drug_name: str, clinical_intent: str) -> str:
    """Determine medication administration route."""
    combined = (drug_name + " " + clinical_intent).upper()
    if "IV" in combined or "DRIP" in combined:
        return "IV"
    if "SC" in combined or "SUBCUTANEOUS" in combined or "ENOXAPARIN" in combined.upper():
        return "SC"
    if "IM" in combined:
        return "IM"
    # Known IV drugs
    iv_drugs = ["AMPICILLIN", "SULBACTAM", "CEFTRIAXONE", "MEROPENEM",
                "FUROSEMIDE", "NITROGLYCERIN", "VANCOMYCIN", "LEVOFLOXACIN"]
    for d in iv_drugs:
        if d in drug_name.upper():
            return "IV"
    return "PO"


def _check_discharge_ready(
    state: PhysiologicalState,
    day: int,
    country_key: str,
) -> bool:
    """Check if patient meets state-based discharge criteria.

    Common criteria across diseases:
    - Inflammation resolving (CRP proxy)
    - Hemodynamically stable (perfusion)
    - No acute organ dysfunction
    JP: stricter (lower inflammation threshold, longer afebrile requirement)
    US: earlier discharge once clinically stable
    """
    # anemia_level < 0.60 ≈ Hgb > 7.0 g/dL for females (13 * (1-0.6*0.7) = 7.5)
    # and Hgb > 8.7 for males (15 * (1-0.6*0.7) = 8.7)
    # No patient should be discharged with Hgb below transfusion trigger
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
    else:  # japan — stricter criteria
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

    If disease_mortality_rate is provided (from YAML outcome_benchmarks),
    it is used as the total in-hospital mortality rate and spread across the LOS.
    """
    if disease_mortality_rate > 0:
        # Spread total mortality across hospital stay, weighted by day
        day_weight = 1.5 if 2 <= day <= 7 else (0.5 if day > 14 else 1.0)
        daily_base = disease_mortality_rate / max(target_los, 1) * day_weight
        # When benchmark is used, apply only mild individual modifiers
        # The benchmark already accounts for average patient demographics
        age = patient.age if hasattr(patient, "age") else 70
        individual_mod = 1.0
        if age >= 85:
            individual_mod *= 1.2
        if state.perfusion_status < 0.3:
            individual_mod *= 1.3
        individual_mod = min(individual_mod, 1.8)
        return bool(rng.random() < daily_base * individual_mod)
    else:
        daily_base = {"severe": 0.003, "moderate": 0.0005}.get(severity, 0.0001)
        age = patient.age if hasattr(patient, "age") else 70
        age_mult = 1.5 if age >= 85 else (1.2 if age >= 80 else 1.0)
        return bool(rng.random() < daily_base * age_mult)
