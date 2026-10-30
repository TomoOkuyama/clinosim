"""Readmissions — scheduled at the index discharge, dispatched on their date.

The forward loop (``_forward_loop.py``, Issue #2169) calls
:func:`schedule_readmission` right after an index inpatient stay is
dispatched and queues the returned event; :func:`dispatch_readmission`
runs when the loop reaches its date, so a readmission (and a death in it)
happens in time order with every other event.

RNG consumption is composed of
``derive_phase_rng(master_seed, PHASE_READMISSION, re_key)`` + per-event
``derive_phase_rng(master_seed, PHASE_INPATIENT_SIM, re_sim_key)``
sub-seeds; no shared global generator is read.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from clinosim.modules.population.engine import LifeEvent
from clinosim.modules.population.vital_status import record_hospital_death
from clinosim.seeding import PHASE_INPATIENT_SIM, PHASE_READMISSION, derive_phase_rng
from clinosim.simulator._setup import _activate_cached_person
from clinosim.simulator.helpers import _deactivate_to_layer1, _evaluate_readmission
from clinosim.simulator.inpatient import _simulate_patient
from clinosim.types.output import CIFPatientRecord

if TYPE_CHECKING:
    from clinosim.simulator.phases._forward_loop import ForwardContext


def schedule_readmission(record: CIFPatientRecord, ctx: ForwardContext) -> LifeEvent | None:
    """Decide, at the index stay's discharge, whether and when a readmission fires.

    Called by the forward loop once per index inpatient record, right after
    it is dispatched (Issue #2169). The per-record RNG is keyed on the
    patient and index encounter, so the decision does not depend on what
    else the loop has dispatched.
    """
    if record.deceased or record.is_readmission:
        return None
    person = ctx.population.get_person(record.patient.patient_id)
    if person is None:
        return None
    diseases = record.condition_event.ground_truth_diseases
    readmit_disease_id = diseases[0] if diseases else None
    if not readmit_disease_id:
        return None
    protocol = ctx.protocols.get(readmit_disease_id)
    if not protocol:
        return None
    re_key = f"{record.patient.patient_id}|{record.encounters[0].encounter_id}"
    re_rng = derive_phase_rng(ctx.master_seed, PHASE_READMISSION, re_key)
    return _evaluate_readmission(record, person, readmit_disease_id, protocol, ctx.country_key, re_rng)


def dispatch_readmission(re_event: LifeEvent, ctx: ForwardContext) -> CIFPatientRecord | None:
    """Simulate one readmission on its date; returns the appended record, if any.

    Overlap handling mirrors the main inpatient loop (Issue #848 + Issue
    #1430 post-hoc check): an admission already covering the readmission
    date absorbs it as a merged disease instead.
    """
    from clinosim.simulator.engine import (
        _find_overlapping_inpatient_record,
        _merge_disease_into_active_encounter,
        _verify_no_actual_overlap,
    )

    person = ctx.population.get_person(re_event.person_id)
    if not person or not person.in_population_at(re_event.timestamp):
        return None
    protocol = ctx.protocols.get(re_event.disease_id)
    if not protocol:
        return None
    re_time = datetime(re_event.timestamp.year, re_event.timestamp.month, re_event.timestamp.day, 12, 0)
    overlap = _find_overlapping_inpatient_record(ctx.patient_records, re_event.person_id, re_time)
    if overlap is not None:
        _merge_disease_into_active_encounter(overlap, re_event.disease_id, re_time)
        return None
    patient = _activate_cached_person(
        person,
        as_of_year=re_time.year,
        patient_cache=ctx.patient_cache,
        master_seed=ctx.master_seed,
        demo=ctx.demo,
    )
    re_sim_key = f"{re_event.person_id}|{re_event.timestamp.isoformat()}|readmission"
    re_sim_rng = derive_phase_rng(ctx.master_seed, PHASE_INPATIENT_SIM, re_sim_key)
    record = _simulate_patient(
        patient,
        re_event,
        re_event.disease_id,
        protocol,
        ctx.healthcare,
        ctx.roster,
        ctx.config,
        re_sim_rng,
        is_readmission=True,
        prior_encounter_id=re_event.prior_encounter_id,
        readmission_number=re_event.readmission_number,
        hospital_state=ctx.hospital_state,
        hospital_ops=ctx.hospital_ops,
    )
    post_hoc = _verify_no_actual_overlap(ctx.patient_records, record)
    if post_hoc is not None:
        _merge_disease_into_active_encounter(post_hoc, re_event.disease_id, record.encounters[0].admission_datetime)
        return None
    ctx.patient_records.append(record)
    _deactivate_to_layer1(person, record, re_event.disease_id, patient_cache=ctx.patient_cache)
    record_hospital_death(person, record)
    return record
