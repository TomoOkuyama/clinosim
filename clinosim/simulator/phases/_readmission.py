"""Readmission phase runner.

Extracted verbatim from ``clinosim/simulator/engine.py`` as step C2e of
the full-review Phase C engine split (CRITICAL C2). Behavior is byte-
identical — ``engine.py`` re-exports the symbol via a lazy import so
every ``run_beta`` call site stays intact.

RNG consumption is composed of
``derive_phase_rng(master_seed, PHASE_READMISSION, re_key)`` + per-event
``derive_phase_rng(master_seed, PHASE_INPATIENT_SIM, re_sim_key)``
sub-seeds; no shared global generator is read.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from clinosim.modules.population.engine import LifeEvent
from clinosim.seeding import PHASE_INPATIENT_SIM, PHASE_READMISSION, derive_phase_rng
from clinosim.simulator._setup import _activate_cached_person
from clinosim.simulator.helpers import _deactivate_to_layer1, _evaluate_readmission
from clinosim.simulator.inpatient import _simulate_patient
from clinosim.types.config import SimulatorConfig
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile


def _run_readmission_phase(
    *,
    patient_records: list[CIFPatientRecord],
    population: Any,
    protocols: dict[str, Any],
    snapshot_dt: datetime | None,
    master_seed: int,
    country_key: str,
    healthcare: Any,
    roster: Any,
    config: SimulatorConfig,
    hospital_state: Any,
    hospital_ops: dict[str, Any],
    patient_cache: dict[tuple[str, int | None], PatientProfile],
    demo: dict[str, Any],
) -> int:
    """Run the post-loop readmission evaluation + simulation pass.

    Walks each eligible ``CIFPatientRecord`` already in
    ``patient_records``, derives a per-record readmission RNG, calls
    ``_evaluate_readmission`` to decide whether (and when) a readmit
    fires, sorts the firing events chronologically, then dispatches
    each through ``_simulate_patient`` with ``is_readmission=True``.

    Overlap handling mirrors the main inpatient loop (Issue #848 +
    Issue #1430 post-hoc check). The readmission dispatch uses
    period-overlap (not point-in-time) because ``patient_records``
    already contains later life-event admissions whose start is after
    the readmission's scheduled admit time but whose period overlaps.

    Returns the number of readmission events evaluated (post snapshot
    filter) for the caller's progress log.
    """
    from clinosim.simulator.engine import (
        _find_overlapping_inpatient_record,
        _merge_disease_into_active_encounter,
        _verify_no_actual_overlap,
    )

    readmission_events: list[LifeEvent] = []
    for record in patient_records:
        if record.deceased or record.is_readmission:
            continue
        person = population.get_person(record.patient.patient_id)
        _readmit_gate_date = snapshot_dt.date() if snapshot_dt else date.max
        if not person or not person.is_alive or not person.is_alive_at(_readmit_gate_date):
            continue
        readmit_disease_id = (
            record.condition_event.ground_truth_diseases[0] if record.condition_event.ground_truth_diseases else None
        )
        if not readmit_disease_id:
            continue
        protocol = protocols.get(readmit_disease_id)
        if not protocol:
            continue
        re_key = f"{record.patient.patient_id}|{record.encounters[0].encounter_id}"
        re_rng = derive_phase_rng(master_seed, PHASE_READMISSION, re_key)
        re_event = _evaluate_readmission(
            record,
            person,
            readmit_disease_id,
            protocol,
            country_key,
            re_rng,
        )
        if re_event:
            readmission_events.append(re_event)

    if snapshot_dt:
        readmission_events = [
            e
            for e in readmission_events
            if not e.timestamp or datetime.combine(e.timestamp, datetime.min.time()) <= snapshot_dt
        ]

    readmission_events.sort(key=lambda e: e.timestamp)
    for re_event in readmission_events:
        person = population.get_person(re_event.person_id)
        if not person or not person.is_alive or not person.is_alive_at(re_event.timestamp):
            continue
        protocol = protocols.get(re_event.disease_id)
        if not protocol:
            continue
        _re_event_time = datetime(re_event.timestamp.year, re_event.timestamp.month, re_event.timestamp.day, 12, 0)
        _re_overlap = _find_overlapping_inpatient_record(patient_records, re_event.person_id, _re_event_time)
        if _re_overlap is not None:
            _merge_disease_into_active_encounter(_re_overlap, re_event.disease_id, _re_event_time)
            continue
        patient = _activate_cached_person(
            person,
            as_of_year=_re_event_time.year,
            patient_cache=patient_cache,
            master_seed=master_seed,
            demo=demo,
        )
        re_sim_key = f"{re_event.person_id}|{re_event.timestamp.isoformat()}|readmission"
        re_sim_rng = derive_phase_rng(master_seed, PHASE_INPATIENT_SIM, re_sim_key)
        record = _simulate_patient(
            patient,
            re_event,
            re_event.disease_id,
            protocol,
            healthcare,
            roster,
            config,
            re_sim_rng,
            is_readmission=True,
            prior_encounter_id=re_event.prior_encounter_id,
            readmission_number=re_event.readmission_number,
            hospital_state=hospital_state,
            hospital_ops=hospital_ops,
        )
        _post_hoc_overlap = _verify_no_actual_overlap(patient_records, record)
        if _post_hoc_overlap is not None:
            _merge_disease_into_active_encounter(
                _post_hoc_overlap, re_event.disease_id, record.encounters[0].admission_datetime
            )
            continue
        patient_records.append(record)
        _deactivate_to_layer1(person, record, re_event.disease_id, patient_cache=patient_cache)
        if record.deceased:
            person.is_alive = False

    return len(readmission_events)
