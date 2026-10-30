"""Simulator dispatch + overlap-handling cluster.

Extracted verbatim from ``clinosim/simulator/engine.py`` as step C2b of
the full-review Phase C engine split (CRITICAL C2). Behavior is byte-
identical — ``engine.py`` re-exports these names via lazy imports so
every call site stays intact.

This module carries no RNG consumption of its own: ``_dispatch_hospital_events``
threads ``derive_phase_rng`` sub-seeds through to ``_simulate_patient``
and ``_simulate_unknown_condition``, both of which live in sibling
modules. Order is determined by the caller's event list, not by any
helper here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from clinosim.modules.order.engine import replay_order_to_state
from clinosim.modules.population.engine import LifeEvent
from clinosim.modules.population.vital_status import record_hospital_death
from clinosim.seeding import PHASE_INPATIENT_SIM, derive_phase_rng
from clinosim.simulator import log as sim_log
from clinosim.simulator.complications import build_complication
from clinosim.simulator.helpers import _deactivate_to_layer1, _select_secondary_disease
from clinosim.simulator.inpatient import _simulate_patient
from clinosim.simulator.unknown_condition import _simulate_unknown_condition
from clinosim.types.config import SimulatorConfig
from clinosim.types.encounter import EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile


def _find_active_inpatient_record(
    patient_records: list[CIFPatientRecord],
    person_id: str,
    event_time: datetime,
) -> CIFPatientRecord | None:
    """Return the patient's currently-active inpatient record at ``event_time``.

    Issue #848: the population life-event stream can fire a new disease
    event for a person who is still admitted for an earlier event
    (POP-000170 developed acute coronary syndrome on day 37 of a 46-day
    pancreatitis admission). Prior behavior: a wholly separate inpatient
    encounter got created for the new event, and the two admissions
    coexisted in the CIF (17 cross-department overlaps + 8 same-department
    overlaps in the JP p=10000 s500 sample) — physically impossible in
    a single 50-bed hospital.

    A record is "active" when its lead encounter is an inpatient stay,
    ``admission_datetime <= event_time``, and ``discharge_datetime`` is
    absent (still admitted at snapshot) or strictly after ``event_time``.
    Returns the most-recently-admitted such record if several match
    (typically only one for a given moment).
    """
    active: CIFPatientRecord | None = None
    best_admit: datetime | None = None
    for record in patient_records:
        if record.patient.patient_id != person_id:
            continue
        if not record.encounters:
            continue
        enc = record.encounters[0]
        if enc.encounter_type != EncounterType.INPATIENT:
            continue
        if enc.admission_datetime is None or enc.admission_datetime > event_time:
            continue
        if enc.discharge_datetime is not None and enc.discharge_datetime <= event_time:
            continue
        if best_admit is None or enc.admission_datetime > best_admit:
            best_admit = enc.admission_datetime
            active = record
    return active


def _find_overlapping_inpatient_record(
    patient_records: list[CIFPatientRecord],
    person_id: str,
    event_time: datetime,
    estimated_los_days: int = 30,
) -> CIFPatientRecord | None:
    """Return any patient inpatient record whose stay would overlap a new admission.

    Issue #848 fu: ``_find_active_inpatient_record`` is a point-in-time
    check — "is the patient admitted RIGHT NOW at event_time?" That is
    the correct gate for the main inpatient dispatch loop, which
    processes life events chronologically (no later admission exists in
    ``patient_records`` yet). The readmission dispatch runs AFTER the
    main loop, so ``patient_records`` at that point contains life-event
    admissions whose start is AFTER the readmission's scheduled admit
    time — the point-check misses the overlap because the later
    admission isn't "active" at event_time yet.

    This function checks period-overlap: if any existing inpatient
    encounter's ``[admission, discharge]`` intersects
    ``[event_time, event_time + estimated_los_days]``, return it. The
    30-day default LOS estimate is intentionally generous — median
    inpatient LOS in the sim is ~14 days, so the window covers the
    long-tail admissions without pulling in unrelated future
    encounters. Returns the earliest-admitting overlap so a
    complication merges into the earlier stay rather than a later one.
    """
    est_discharge = event_time + timedelta(days=estimated_los_days)
    best: CIFPatientRecord | None = None
    best_admit: datetime | None = None
    for record in patient_records:
        if record.patient.patient_id != person_id:
            continue
        if not record.encounters:
            continue
        enc = record.encounters[0]
        if enc.encounter_type != EncounterType.INPATIENT:
            continue
        if enc.admission_datetime is None:
            continue
        rec_end = enc.discharge_datetime
        if rec_end is not None and rec_end <= event_time:
            continue
        if enc.admission_datetime >= est_discharge:
            continue
        if best_admit is None or enc.admission_datetime < best_admit:
            best_admit = enc.admission_datetime
            best = record
    return best


def _verify_no_actual_overlap(
    patient_records: list[CIFPatientRecord],
    new_record: CIFPatientRecord,
) -> CIFPatientRecord | None:
    """Post-hoc overlap check using the just-simulated encounter's ACTUAL
    ``admission_datetime`` and ``discharge_datetime`` — not the
    ``date + noon`` sentinel that fed the pre-dispatch gate.

    Issue #1430: ``_find_active_inpatient_record`` (main loop) and
    ``_find_overlapping_inpatient_record`` (readmission loop) both key off
    ``event_time = datetime(year, month, day, 12, 0)`` because the
    life-event stream carries date-precision timestamps. The actual admit
    hour is not decided until ``_simulate_patient`` runs, so both gates
    can miss overlaps that manifest at the hour level:

    - Main loop: two same-day life events for one person. The first
      lands with ``admission_datetime = 18:03``. The second's noon gate
      sees a record whose ``admission_datetime (18:03) > event_time
      (12:00)``, so the record is skipped (``_find_active_inpatient_record``
      only counts records already active *at* event_time). The second
      then simulates and lands at ``19:46`` — a physically-concurrent
      stay the pre-dispatch gate never had the data to catch.

    - Readmission loop: a readmission fires the same day the prior stay
      is discharged. Prior discharge is ``10:37``, readmission's noon
      gate sees ``rec_end (10:37) <= event_time (12:00)``, so the record
      is skipped as already-ended. The readmission then simulates and
      lands at ``06:12`` — before the prior discharge (time-machine
      violation).

    Both cases share the same shape: the pre-dispatch gate is
    date-precision, the actual admission clock is hour-precision, so a
    post-hoc verifier is the right place to catch the residual overlap.
    Returns the earliest-admitting existing record whose period intersects
    the new record's actual period, if any. Callers merge the new
    disease into that record (mirroring the pre-dispatch merge path) and
    discard the concurrent stay.
    """
    if not new_record.encounters:
        return None
    new_enc = new_record.encounters[0]
    if new_enc.encounter_type != EncounterType.INPATIENT:
        return None
    new_admit = new_enc.admission_datetime
    if new_admit is None:
        return None
    new_dc = new_enc.discharge_datetime if new_enc.discharge_datetime is not None else datetime.max
    person_id = new_record.patient.patient_id
    best: CIFPatientRecord | None = None
    best_admit: datetime | None = None
    for record in patient_records:
        if record is new_record:
            continue
        if record.patient.patient_id != person_id:
            continue
        if not record.encounters:
            continue
        enc = record.encounters[0]
        if enc.encounter_type != EncounterType.INPATIENT:
            continue
        rec_start = enc.admission_datetime
        if rec_start is None:
            continue
        rec_end = enc.discharge_datetime if enc.discharge_datetime is not None else datetime.max
        if rec_start >= new_dc:
            continue
        if rec_end <= new_admit:
            continue
        if best_admit is None or rec_start < best_admit:
            best_admit = rec_start
            best = record
    return best


def _handle_overlap_via_merge(
    patient_records: list[CIFPatientRecord],
    new_record: CIFPatientRecord,
    disease_id: str,
    *,
    companions: list[CIFPatientRecord] | None = None,
) -> CIFPatientRecord | None:
    """Post-hoc overlap check + merge, with optional companion rewrite.

    Consolidates the ``_verify_no_actual_overlap`` + ``_merge_disease_into_active_encounter``
    pattern used at every inpatient-dispatch append site. When an overlap
    is detected, the new record's disease is merged into the earlier
    surviving stay (as an in-hospital complication), and any companion
    record's ``admit_source_encounter_id`` (FHIR ``Encounter.partOf``)
    pointing at ``new_record``'s encounter is repointed to the surviving
    encounter — so a mother-side delivery merged into an ongoing
    admission does not leave the newborn's ``partOf`` reference dangling.

    Issue #1436: the two-site wiring in #1430 (main + readmission loop)
    missed the perinatal / abortion / unknown_condition sibling
    dispatchers. This helper is what those sites call.
    """
    overlap = _verify_no_actual_overlap(patient_records, new_record)
    if overlap is None:
        return None
    admit_dt = new_record.encounters[0].admission_datetime
    _merge_disease_into_active_encounter(overlap, disease_id, admit_dt)
    if companions:
        new_enc_id = new_record.encounters[0].encounter_id
        target_enc_id = overlap.encounters[0].encounter_id
        for comp in companions:
            for enc in comp.encounters:
                if enc.admit_source_encounter_id == new_enc_id:
                    enc.admit_source_encounter_id = target_enc_id
    return overlap


def _merge_disease_into_active_encounter(
    active_record: CIFPatientRecord,
    disease_id: str,
    event_time: datetime,
) -> None:
    """Merge a new-disease life event into an already-admitted patient's record.

    Issue #848 full-C: rather than opening a second concurrent encounter
    (physically impossible in one hospital), a new-disease event that
    fires while the patient is admitted is recorded as an in-hospital
    complication on the existing encounter — this is what real EHR
    practice does (cardiology consult / CCU transfer on the same
    encounter). Data captured:

    - ``complications_occurred``: the new disease id is appended
      (idempotent — no duplicates).
    - ``condition_event.condition_type``: promoted to ``"mixed"`` when it
      was any of the single-condition types (``known_disease``,
      ``unknown``, ``ed_visit``); ``post_discharge_followup`` and
      ``chronic_followup`` are outpatient labels and are not overwritten
      here (defensive — the caller gates on inpatient records only).
    - ``condition_event.ground_truth_diseases``: appended (idempotent).
    - ``clinical_diagnosis.working_diagnoses``: a
      ``{disease_id, onset_day, onset_datetime}`` entry is appended so
      downstream FHIR emit can render the new diagnosis as a secondary
      Condition timestamped at the intra-admission onset (not the
      admission date).

    Order/lab/vital simulation for the complication is deliberately not
    invoked here — the simulator's per-disease protocol is designed
    around an isolated admission (discharge date, LOS pacing, etc.) and
    cannot be dropped into the middle of another admission's timeline
    without a substantial refactor of ``_simulate_patient``. Recording
    the complication as a diagnostic fact + a working-diagnosis entry
    preserves the clinical signal (this patient developed X on day N)
    without fabricating a treatment timeline that would not agree with
    the pre-simulated existing admission's flow. Full order/lab
    simulation for in-hospital complications is a future enhancement
    (tracked in the follow-up section of the #848 discussion).
    """
    if not active_record.encounters:
        return
    admit_dt = active_record.encounters[0].admission_datetime
    onset_day = (event_time.date() - admit_dt.date()).days if admit_dt else 0
    if onset_day < 0:
        onset_day = 0

    existing_names = {(e.get("name") if isinstance(e, dict) else str(e)) for e in active_record.complications_occurred}
    if disease_id not in existing_names:
        active_record.complications_occurred.append(
            build_complication(
                name=disease_id,
                onset_day=onset_day,
                onset_datetime=event_time.isoformat(),
                source="in_hospital_new_disease",
            )
        )

    ce = active_record.condition_event
    if ce is not None:
        if ce.condition_type in ("known_disease", "unknown", "ed_visit"):
            ce.condition_type = "mixed"
        if disease_id not in ce.ground_truth_diseases:
            ce.ground_truth_diseases.append(disease_id)

    cd = active_record.clinical_diagnosis
    if cd is not None and isinstance(cd.working_diagnoses, list):
        cd.working_diagnoses.append(
            {
                "disease_id": disease_id,
                "onset_day": onset_day,
                "onset_datetime": event_time.isoformat(),
                "source": "in_hospital_complication",
            }
        )


def _replay_cached_admission_queue(
    record: CIFPatientRecord | None,
    hospital_state: Any,
    hospital_ops: dict,
) -> None:
    """Apply a cache-hit admission's lab/imaging queue increments to hospital_state.

    Issue #761: on the cold path, each order in `_simulate_patient` calls
    `calculate_result_time_from_state` → `hospital_state.add_to_queue`,
    so later unrelated admissions see the accumulated congestion. A cache
    hit skips `_simulate_patient` entirely, dropping those increments —
    so `result_datetime` on later cold-simulated admissions drifts from
    the cold-path reference. Replaying the orders carried on the cached
    record re-applies the same `(resource_type, scheduled)` increments
    the cached record so the queue accumulates identically across cold
    and memo runs. No-op when the record is None or hospital_state is
    None (legacy path).
    """
    if record is None or hospital_state is None:
        return
    for order in record.orders:
        replay_order_to_state(order, hospital_state, hospital_ops)


@dataclass
class _DispatchState:
    """Mutable scalars rebound inside the inpatient dispatch loop.

    Promoted to a dataclass so the per-month dispatch helper can be a
    module-level function (not a closure with ``nonlocal`` rebinds).
    The three fields were the only names the pre-split closure
    rebound; everything else (``patient_records``, ``patient_cache``,
    ``hospital_state``, ``prev_admission_cache``, …) is a reference
    through which mutations propagate without rebinding.

    - ``concurrent_patients``: current count of patients physically
      inside the hospital (bumped on admit, decremented on same-day
      discharge replay / overlap merges / unknown-condition drop /
      post-hoc overlap merge).
    - ``active_discharges``: FIFO of ``(discharge_date, beds_freed)``
      tuples the loop replays on each event to free beds whose
      discharge dates have passed.
    - ``progress_cumul``: cumulative dispatched-event counter — the
      Issue #1596 Step 1 fix for per-chunk cadence; triggers the
      ``inpatient_progress`` sim_log event every 50 events plus at
      each chunk's terminal event (``== total``).
    """

    concurrent_patients: int = 0
    active_discharges: list[tuple] = field(default_factory=list)
    progress_cumul: int = 0


def _dispatch_hospital_events(
    *,
    events: list[LifeEvent],
    total: int,
    label: str,
    state: _DispatchState,
    patient_records: list[CIFPatientRecord],
    patient_cache: dict[tuple[str, int | None], PatientProfile],
    prev_admission_cache: dict[tuple[str, str, str], CIFPatientRecord],
    population: Any,
    hospital_state: Any,
    hospital_ops: dict[str, Any],
    beds_total: int,
    protocols: dict[str, Any],
    healthcare: Any,
    roster: Any,
    config: SimulatorConfig,
    master_seed: int,
    demo: dict[str, Any],
) -> None:
    """Dispatch a chunk of hospital-admit life events through the
    full inpatient / unknown-condition pipeline.

    Shared mutable scalars live on ``state`` (``_DispatchState``) so
    this helper is module-level — the pre-split version was a closure
    over ``run_beta`` with three ``nonlocal`` rebinds. All other
    shared state (``patient_records``, ``patient_cache``,
    ``prev_admission_cache``, ``hospital_state``) propagates through
    object references and dict / list mutation; nothing else is
    rebound.

    The per-chunk ``total`` argument carries the running cumulative
    hospital-event count for the progress-cadence log line (Issue
    #1596 Step 1); the helper itself does not re-derive it.
    """
    from clinosim.simulator.engine import _activate_cached_person

    for event in events:
        state.progress_cumul += 1
        if state.progress_cumul % 50 == 0 or state.progress_cumul == total:
            print(
                f"  Simulating {label} {state.progress_cumul}/{total} "
                f"(concurrent={state.concurrent_patients}, "
                f"bed_occ={hospital_state.bed_occupancy:.0%})...",
                flush=True,
            )
            sim_log.info(
                "engine",
                f"{label}_progress",
                processed=state.progress_cumul,
                target=total,
                concurrent=state.concurrent_patients,
                bed_occupancy=round(hospital_state.bed_occupancy, 3),
            )

        event_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day, 12, 0)
        hospital_state.update_for_time(event_time, hospital_ops)
        new_active = []
        for dc_date, beds in state.active_discharges:
            if dc_date <= event.timestamp:
                hospital_state.bed_occupancy = max(0, hospital_state.bed_occupancy - beds)
                state.concurrent_patients = max(0, state.concurrent_patients - 1)
            else:
                new_active.append((dc_date, beds))
        state.active_discharges = new_active

        hospital_state.bed_occupancy = min(0.99, hospital_state.bed_occupancy + 1.0 / beds_total)
        state.concurrent_patients += 1

        person = population.get_person(event.person_id)
        if person is None or not person.is_alive_at(event_time.date()):
            continue

        patient = _activate_cached_person(
            person,
            as_of_year=event_time.year,
            patient_cache=patient_cache,
            master_seed=master_seed,
            demo=demo,
        )
        disease_id = event.disease_id

        _active = _find_active_inpatient_record(patient_records, event.person_id, event_time)
        if _active is not None:
            _merge_disease_into_active_encounter(_active, disease_id, event_time)
            hospital_state.bed_occupancy = max(0.0, hospital_state.bed_occupancy - 1.0 / beds_total)
            state.concurrent_patients = max(0, state.concurrent_patients - 1)
            continue

        event_key = f"{event.person_id}|{event.timestamp.isoformat()}|{disease_id}"
        event_rng = derive_phase_rng(master_seed, PHASE_INPATIENT_SIM, event_key)
        cache_key = (event.person_id, event.timestamp.isoformat(), disease_id)

        if event.condition_type == "unknown" or disease_id.startswith("unknown_"):
            record: CIFPatientRecord | None
            if cache_key in prev_admission_cache:
                record = prev_admission_cache[cache_key]
                _replay_cached_admission_queue(record, hospital_state, hospital_ops)
            else:
                record = _simulate_unknown_condition(
                    patient,
                    event,
                    event_rng,
                    healthcare,
                    roster,
                    hospital_ops=hospital_ops,
                    config=config,
                )
            if record:
                _post_hoc_overlap = _handle_overlap_via_merge(patient_records, record, disease_id)
                if _post_hoc_overlap is not None:
                    hospital_state.bed_occupancy = max(0.0, hospital_state.bed_occupancy - 1.0 / beds_total)
                    state.concurrent_patients = max(0, state.concurrent_patients - 1)
                    continue
                patient_records.append(record)
                person.has_visited_hospital = True
                person.visit_count += 1
            continue

        protocol = protocols.get(disease_id)
        if protocol is None:
            continue

        secondary_protocol = None
        if event.condition_type == "mixed":
            secondary_protocol = _select_secondary_disease(
                patient,
                disease_id,
                protocols,
                event_rng,
            )

        if cache_key in prev_admission_cache:
            record = prev_admission_cache[cache_key]
            _replay_cached_admission_queue(record, hospital_state, hospital_ops)
        else:
            record = _simulate_patient(
                patient,
                event,
                disease_id,
                protocol,
                healthcare,
                roster,
                config,
                event_rng,
                secondary_protocol=secondary_protocol,
                is_readmission=event.is_readmission,
                prior_encounter_id=event.prior_encounter_id,
                readmission_number=event.readmission_number,
                hospital_state=hospital_state,
                hospital_ops=hospital_ops,
            )
        _post_hoc_overlap = _verify_no_actual_overlap(patient_records, record)
        if _post_hoc_overlap is not None:
            _merge_disease_into_active_encounter(_post_hoc_overlap, disease_id, record.encounters[0].admission_datetime)
            hospital_state.bed_occupancy = max(0.0, hospital_state.bed_occupancy - 1.0 / beds_total)
            state.concurrent_patients = max(0, state.concurrent_patients - 1)
            continue
        patient_records.append(record)
        _deactivate_to_layer1(person, record, disease_id, patient_cache=patient_cache)
        if record.encounters and record.encounters[0].discharge_datetime:
            dc_date = record.encounters[0].discharge_datetime.date()
            state.active_discharges.append((dc_date, 1.0 / beds_total))
        record_hospital_death(person, record)
