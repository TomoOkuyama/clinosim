"""Post-discharge follow-up phase runner.

Extracted verbatim from ``clinosim/simulator/engine.py`` as step C2d of
the full-review Phase C engine split (CRITICAL C2). Behavior is byte-
identical — ``engine.py`` re-exports the symbol via a lazy import so
every ``run_beta`` call site stays intact.

RNG consumption is derive_phase_rng(master_seed, PHASE_OUTPATIENT_CAL,
opd_key) sub-seeds; no shared global generator is read.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from clinosim.seeding import PHASE_OUTPATIENT_CAL, derive_phase_rng
from clinosim.simulator._setup import _activate_cached_person
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.simulator.outpatient_dept import resolve_outpatient_department
from clinosim.types.config import SimulatorConfig
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile


def _run_post_discharge_phase(
    *,
    inpatient_records: list[CIFPatientRecord],
    patient_records: list[CIFPatientRecord],
    population: Any,
    followup_data: dict[str, Any],
    snapshot_dt: datetime | None,
    master_seed: int,
    patient_cache: dict[tuple[str, int | None], PatientProfile],
    demo: dict[str, Any],
    roster: Any,
    config: SimulatorConfig,
    hospital_ops: dict[str, Any],
) -> int:
    """Emit the post-discharge follow-up outpatient visit for each
    inpatient stay.

    For every surviving inpatient record with a discharge datetime,
    schedule a follow-up visit at ``discharge + first_visit_days``
    (defaults to 14 d, overridable via ``_post_discharge`` yaml),
    gate by snapshot_dt + natural death, and dispatch via
    ``_simulate_outpatient_visit`` with the same service line
    (resolved via ``resolve_outpatient_department(post_discharge, …)``)
    as the inpatient encounter — continuity of care.

    Returns the number of post-discharge records appended.
    """
    post_dc_spec = followup_data.get("_post_discharge", {})
    post_dc_days = post_dc_spec.get("first_visit_days", 14)

    n_before = len(patient_records)
    for record in inpatient_records:
        pid = record.patient.patient_id
        person = population.get_person(pid)
        if not person:
            continue
        enc = record.encounters[0]
        if not enc.discharge_datetime:
            continue
        disease_id = (
            record.condition_event.ground_truth_diseases[0] if record.condition_event.ground_truth_diseases else ""
        )
        disease_fu = followup_data.get("_post_discharge_by_disease", {}).get(disease_id, {})
        merged_spec = dict(post_dc_spec)
        if disease_fu.get("labs"):
            merged_spec["labs"] = disease_fu["labs"]
        followup_date = enc.discharge_datetime + timedelta(days=post_dc_days)
        if snapshot_dt and followup_date > snapshot_dt:
            continue
        if not person.is_alive_at(followup_date.date()):
            continue
        opd_key = f"{pid}|post_discharge|{followup_date.isoformat()}"
        opd_rng = derive_phase_rng(master_seed, PHASE_OUTPATIENT_CAL, opd_key)
        opd_dept = resolve_outpatient_department("post_discharge", disease_id, enc.department_id, hospital_ops)
        opd_record = _simulate_outpatient_visit(
            _activate_cached_person(
                person,
                as_of_year=followup_date.year,
                patient_cache=patient_cache,
                master_seed=master_seed,
                demo=demo,
            ),
            "post_discharge",
            followup_date,
            roster,
            opd_rng,
            followup_spec=merged_spec,
            post_discharge_disease=disease_id,
            country=config.country,
            config=config,
            department_id=opd_dept,
        )
        patient_records.append(opd_record)
    return len(patient_records) - n_before
