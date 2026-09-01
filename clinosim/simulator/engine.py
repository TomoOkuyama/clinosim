"""Simulator engine — run_beta, run_forced, run_alpha entry points."""

from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from clinosim import __version__ as _clinosim_version
from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.modules._shared import is_jp
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.healthcare_system.loader import load_healthcare_config
from clinosim.modules.order.engine import replay_order_to_state
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import (
    LifeEvent,
    PersonRecord,
    generate_healthcare_calendar,
    generate_monthly_events,
    generate_population,
)
from clinosim.modules.staff.engine import generate_roster
from clinosim.seeding import (
    PHASE_ED_VISIT,
    PHASE_INPATIENT_SIM,
    PHASE_LIFE_EVENT,
    PHASE_OUTPATIENT_CAL,
    PHASE_READMISSION,
    derive_phase_rng,
)
from clinosim.simulator import log as sim_log
from clinosim.simulator._forced_scenario_thresholds import (
    FORCED_SCENARIO_AGE_MAX_EXCLUSIVE,
    FORCED_SCENARIO_AGE_MIN,
    FORCED_SCENARIO_DEFAULT_AGE,
    FORCED_SCENARIO_DEFAULT_SEVERITY,
    FORCED_SCENARIO_DEFAULT_SEX,
    FORCED_SCENARIO_EVENT_DATE,
    FORCED_SCENARIO_REFERENCE_YEAR,
    FORCED_SCENARIO_SEVERITY_FRACTION_FALLBACK,
    FORCED_SCENARIO_SEVERITY_FRACTIONS,
)
from clinosim.simulator._scheduling_thresholds import (
    ED_DAY_MAX_EXCLUSIVE,
    ED_DAY_MIN,
    ED_FAVORED_HOURS,
    ED_MINUTE_JITTER_MAX_EXCLUSIVE,
    ED_MINUTE_JITTER_MIN,
    ED_OCCUPATION_MISMATCH_FALLBACK,
    ED_RATE_PER_ADMITTED_DEFAULT,
    OUTPATIENT_CALENDAR_VISIT_HOUR,
    OUTPATIENT_LABS_ANNUAL_PROBABILITY,
    OUTPATIENT_LABS_QUARTERLY_PROBABILITY,
    OUTPATIENT_MINUTE_JITTER_MAX_EXCLUSIVE,
    OUTPATIENT_MINUTE_JITTER_MIN,
)
from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.simulator.enrichers import (
    POST_POPULATION,
    POST_RECORDS,
    EnricherContext,
    register_builtin_enrichers,
    run_stage,
)
from clinosim.simulator.helpers import (
    _country_to_yaml_key,
    _deactivate_to_layer1,
    _evaluate_readmission,
    _select_secondary_disease,
    load_all_disease_protocols,
)
from clinosim.simulator.inpatient import _simulate_patient
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.simulator.outpatient_dept import resolve_outpatient_department
from clinosim.simulator.unknown_condition import _simulate_unknown_condition
from clinosim.types.config import ForcedScenario, SimulatorConfig
from clinosim.types.encounter import EncounterType
from clinosim.types.output import CIFDataset, CIFMetadata, CIFPatientRecord
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
            continue  # existing ended strictly before our start
        if enc.admission_datetime >= est_discharge:
            continue  # existing starts at or after our estimated end
        if best_admit is None or enc.admission_datetime < best_admit:
            best_admit = enc.admission_datetime
            best = record
    return best


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
    # Clamp: when the readmission dispatch's period-overlap gate merges an
    # earlier-scheduled readmission (event_time) into a later-admitting
    # life-event encounter (admit_dt), event_time is BEFORE admit_dt →
    # onset_day would be negative. Semantically this maps to "this
    # disease was already active at admission" (the readmission would
    # have been the actual admit trigger absent the merge), so record
    # onset as day-0 rather than a nonsensical negative day.
    if onset_day < 0:
        onset_day = 0

    if disease_id not in active_record.complications_occurred:
        active_record.complications_occurred.append(disease_id)

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
    the cold-only run. This helper replays the two state mutations
    (`update_for_time` + `add_to_queue`) for every lab/imaging order in
    the cached record so the queue accumulates identically across cold
    and memo runs. No-op when the record is None or hospital_state is
    None (legacy path).
    """
    if record is None or hospital_state is None:
        return
    for order in record.orders:
        replay_order_to_state(order, hospital_state, hospital_ops)


# F1: `generate_healthcare_calendar` emits several distinct
# screening kinds under the same `event_type == "health_screening"` (see the
# ev_key comment in the P4 calendar loop below). Each needs its own visit
# reason text so two screenings landing on the same calendar date don't
# collapse into indistinguishable encounters.
_HEALTH_SCREENING_VISIT_REASON = {
    "annual_health_screening": "Annual health screening",
    "colonoscopy_screening": "Colonoscopy screening",
    "mammography_screening": "Mammography screening",
}


def _pediatric_visit_reason(disease_id: str) -> str | dict[str, str]:
    """Look up the visit_reason for a `pediatric_visit` LifeEvent from the schedule YAML.

    The schedule is keyed by encounter-key (e.g., ``well_child_infant``,
    ``pediatric_uri_young``); multiple encounter-keys may share the same
    ``disease_id`` (for example, ``pediatric_uri_young`` / ``pediatric_uri_school``
    / ``pediatric_uri_adolescent`` are three age-band-specific
    frequencies for the same clinical concept ``pediatric_uri``). Look
    up by direct key match first, then by ``disease_id`` scan across all
    entries so both shapes resolve. Falls back to a generic label if the
    id is in neither position (e.g., LifeEvent authored by an out-of-tree
    tool). Issue #760 pass 2 introduced this helper; pass 4 extended the
    lookup to handle multi-band entries.

    Returns the raw yaml value — either a plain string or a bilingual
    ``{en, ja}`` dict — and lets the outpatient emit-site call
    ``clinosim.locale.text.resolve_text`` with the correct locale (Session
    90 narrative-review fix: pediatric_schedule.yaml was single-string
    English, causing JP cohorts to leak English into chief_complaint and
    into the template narrative fallback SOAP).
    """
    from clinosim.modules.pediatric.calendar import load_pediatric_schedule

    schedule = load_pediatric_schedule()
    entry = schedule.get(disease_id)
    if entry and entry.get("visit_reason"):
        return entry["visit_reason"]  # may be str or {"en": ..., "ja": ...}
    # Fallback: multiple entries can share the same disease_id; return
    # the first match found (age-band-specific visit_reason wording is
    # a stylistic choice; the underlying clinical concept is the same).
    for candidate_entry in schedule.values():
        if candidate_entry.get("disease_id") == disease_id and candidate_entry.get("visit_reason"):
            return candidate_entry["visit_reason"]
    return f"Pediatric visit: {disease_id}"


# ============================================================
# Main entry point
# ============================================================


def _parse_time_range_bound(bound: str) -> datetime:
    """Parse a `config.time_range` bound string into a datetime.

    Accepts both ``YYYY-MM-DD`` (CLI-populated) and ``YYYY-MM`` (test
    fixtures / month-precision callers). A month-only string resolves to
    day 1 (00:00) of that month — the natural lower bound for the month.
    """
    try:
        return datetime.strptime(bound, "%Y-%m-%d")
    except ValueError:
        return datetime.strptime(bound, "%Y-%m")


def run_beta(
    config: SimulatorConfig | None = None,
    hospital_config_path: str | None = None,
    cache_dir: Path | str | None = None,
) -> CIFDataset:
    """Run population-driven simulation.

    Args:
        hospital_config_path: Path to hospital operations YAML.
            If None, uses default config/hospital_operations.yaml.
        cache_dir: Optional previous-snapshot output directory (F4, session
            49). If it holds a valid ``_cache_manifest.json`` matching this
            config's seed/config_hash/country, patients whose every
            encounter was already discharged by the cache's cursor date are
            loaded from the previous CIF instead of re-simulated. Any other
            patient (new events, still-open encounters) is simulated as
            normal. ``None`` (default) disables memoization entirely —
            existing callers are unaffected.
    """
    if config is None:
        config = SimulatorConfig()

    rng = determinism.default_rng(config.random_seed)
    # F1: P1/P2/P3/P4/P4' below derive per-key sub-seeds from
    # master_seed instead of consuming the shared `rng` stream, so that
    # cursor movement (snapshot_date change) cannot shift RNG state for
    # entities that are unaffected by the cursor (cross-cursor determinism).
    master_seed = config.random_seed

    # Load modules
    healthcare = load_healthcare_config(config.country)
    protocols = load_all_disease_protocols()
    demo = load_demographics(config.country)

    # Hospital operational state (YAML-configurable per hospital)
    from clinosim.modules.facility.hospital_state import HospitalState, load_hospital_operations

    if hospital_config_path:
        import yaml

        with open(Path(hospital_config_path)) as f:
            hospital_ops = yaml.safe_load(f) or {}
    else:
        hospital_ops = load_hospital_operations()

    # Staff roster scaled to hospital config (ward-aware, dept-aware).
    # C5-25 (Chain 3, 2026-07-11): use a dedicated sub-RNG so roster
    # changes (e.g., adding allied-health roles) don't shift downstream
    # RNG state (population / life events). Mirrors the AD-16 sub-seed
    # pattern used by module enrichers.
    _roster_rng = determinism.default_rng(config.random_seed ^ 0x524F5354)  # "ROST"
    roster = generate_roster(config.hospital_scale, config.country, _roster_rng, hospital_config=hospital_ops)
    hospital_state = HospitalState()

    # Population: use hospital's recommended_population only when the user did not
    # supply an explicit value (Bug D fix — retires the old `== 10_000` sentinel,
    # which silently discarded any explicit CLI -p value equal to the former
    # argparse default). config.catchment_population is None unless the user (or a
    # preset) set it explicitly.
    pop_size: int
    recommended_raw = hospital_ops.get("recommended_population")
    if recommended_raw:
        if isinstance(recommended_raw, dict):
            # Country-specific: {US: 40000, JP: 5000, default: 40000}
            recommended = int(recommended_raw.get(config.country) or recommended_raw.get("default", 40000))
        else:
            recommended = int(recommended_raw)
        if config.catchment_population is None:
            pop_size = recommended
        else:
            pop_size = config.catchment_population
            if config.catchment_population != recommended:
                print(
                    f"⚠️  User-specified -p {config.catchment_population} used as-is "
                    f"(hospital recommended: {recommended} for {config.country})",
                    file=sys.stderr,
                )
    else:
        pop_size = config.catchment_population or 40000
    beds = hospital_ops.get("resource_capacity", {}).get("inpatient_beds", 50)
    print(f"  Hospital: {beds} beds", flush=True)
    sim_log.info("engine", "hospital_loaded", beds=beds, country=config.country)

    population = generate_population(pop_size, config.country, rng)
    print(f"  Population: {population.total_persons} persons")
    sim_log.info(
        "engine",
        "population_generated",
        persons=population.total_persons,
        catchment=pop_size,
    )

    # Post-population enrichers (AD-56 registry) — e.g. resident identifier / insurance
    # numbering (AD-54). Each enricher uses its own sub-seed; the main random stream
    # (and golden files) is untouched (AD-16).
    register_builtin_enrichers()
    run_stage(
        POST_POPULATION,
        EnricherContext(
            config=config,
            master_seed=config.random_seed,
            population=population,
        ),
    )

    # Run life events
    start_y, start_m = int(config.time_range[0][:4]), int(config.time_range[0][5:7])
    end_y, end_m = int(config.time_range[1][:4]), int(config.time_range[1][5:7])
    # F1: keep the *uncapped* end alongside the snapshot-capped one.
    # `end_y, end_m` below get capped by snapshot_date and are correctly used as
    # the P1 month-loop bound (fewer months generated for an earlier cursor is
    # intended snapshot semantics). But the P4' ED slot phase uses `end_y, end_m`
    # only to size a random draw range (`total_months`, below) — sizing that
    # range off the cursor-capped end would make the draw itself cursor-
    # dependent (same slot_rng stream, different range → different sampled
    # month) even though slot_rng is otherwise cursor-independent. raw_end_y/m
    # preserve the config's own (cursor-independent) time_range for that use.
    raw_end_y, raw_end_m = end_y, end_m

    # Cap end date by snapshot_date (no life events past "today")
    snapshot_dt = None
    if config.snapshot_date:
        snapshot_dt = datetime.strptime(config.snapshot_date, "%Y-%m-%d")
        snap_y, snap_m = snapshot_dt.year, snapshot_dt.month
        if (snap_y, snap_m) < (end_y, end_m):
            end_y, end_m = snap_y, snap_m

    all_events: list[LifeEvent] = []
    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        month_key = f"{y:04d}-{m:02d}"
        month_rng = derive_phase_rng(master_seed, PHASE_LIFE_EVENT, month_key)
        all_events.extend(generate_monthly_events(population, y, m, month_rng, country=config.country))
        m += 1
        if m > 12:
            m, y = 1, y + 1

    # Filter out events after snapshot date
    if snapshot_dt:
        all_events = [
            e
            for e in all_events
            if not e.timestamp or datetime.combine(e.timestamp, datetime.min.time()) <= snapshot_dt
        ]

    # Issue #1039: also clamp on the lower bound. `generate_monthly_events`
    # runs at month precision starting from ``start_m``; an event scheduled
    # in the first month can land on any day 1..31, including days before
    # ``--start`` (e.g. ``--start 2025-08-31`` still fires August 1-30
    # events). The month-loop bound alone does not enforce the day-level
    # ``--start`` cursor. RNG-neutral post-generation filter.
    _start_dt_lb = _parse_time_range_bound(config.time_range[0])
    all_events = [
        e for e in all_events if not e.timestamp or datetime.combine(e.timestamp, datetime.min.time()) >= _start_dt_lb
    ]

    hospital_events = sorted(
        [e for e in all_events if e.requires_hospital],
        key=lambda e: e.timestamp,  # chronological order
    )
    print(f"  Life events: {len(all_events)} total, {len(hospital_events)} requiring hospital")
    sim_log.info(
        "engine",
        "life_events_generated",
        total=len(all_events),
        hospital=len(hospital_events),
    )

    # F4: load a previous-snapshot cache, if given and valid. Only
    # the primary admission loop below (known_disease/mixed via `_simulate_patient`
    # and unknown-condition via `_simulate_unknown_condition`) consults this cache —
    # it is the single most expensive per-event computation (full daily-loop
    # physiology simulation). F1's per-event sub-seed determinism guarantees the
    # cache-hit admission's OWN record is byte-identical to what a fresh
    # simulation of that same event would produce. This does NOT extend to every
    # downstream side effect of skipping `_simulate_patient`, however — see
    # `clinosim/simulator/memoize.py` module docstring ("known limitations") for two
    # confirmed classes of shared-mutable-state divergence a cache hit can cause
    # for OTHER admissions processed later in the same run (implied-chronic
    # accretion on the shared activated `PatientProfile`, and `HospitalState`
    # resource-queue congestion affecting unrelated admissions' result_datetime).
    # Both require touching `inpatient.py` / `order/engine.py` / `hospital_state.py`
    # to fix properly — out of this task's file scope; documented as follow-up.
    prev_cursor_date: date | None = None
    prev_admission_cache: dict[tuple[str, str, str], CIFPatientRecord] = {}
    if cache_dir is not None:
        from clinosim.simulator.memoize import (
            _all_pids_from_cif,
            eligible_patient_ids,
            is_cache_valid,
            load_patient_records_from_cif,
            read_cache_manifest,
        )

        cache_dir_p = Path(cache_dir)
        valid, reason = is_cache_valid(cache_dir_p, config)
        if not valid:
            print(f"  ⚠️  cache invalidated ({reason}); recomputing from scratch", flush=True)
        else:
            manifest = read_cache_manifest(cache_dir_p)
            assert manifest is not None  # is_cache_valid already confirmed it exists
            prev_cursor_date = datetime.strptime(manifest.snapshot_date, "%Y-%m-%d").date()
            prev_cif_dir = cache_dir_p / "cif"
            all_prev_pids = _all_pids_from_cif(prev_cif_dir)
            prev_all = load_patient_records_from_cif(prev_cif_dir, all_prev_pids)
            flat_prev_records = [r for records in prev_all.values() for r in records]
            eligible = eligible_patient_ids(flat_prev_records, prev_cursor_date)
            # Index eligible patients' *admission-loop* records by the same
            # (person_id, event date, disease_id) triple used to derive
            # `event_key` below — content-derived (not RNG-derived), so it can
            # be recomputed identically from a `LifeEvent` without having
            # simulated anything yet. Only INPATIENT, non-readmission records
            # are indexed: those are exactly the records `_simulate_patient` /
            # `_simulate_unknown_condition` produce in the loop below (the
            # readmission / post-discharge / calendar / ED loops build
            # OUTPATIENT/EMERGENCY-type or is_readmission=True records, which
            # this cache intentionally does not substitute — see module
            # docstring above).
            for pid, records in prev_all.items():
                if pid not in eligible:
                    continue
                for r in records:
                    if not r.encounters:
                        continue
                    if r.encounters[0].encounter_type != EncounterType.INPATIENT:
                        continue
                    if r.is_readmission:
                        continue
                    enc = r.encounters[0]
                    ce_disease_id = (
                        r.condition_event.ground_truth_diseases[0]
                        if r.condition_event.ground_truth_diseases
                        else r.condition_event.symptom_pattern
                    )
                    if not ce_disease_id:
                        continue
                    admission_date_iso = enc.admission_datetime.date().isoformat()
                    prev_admission_cache[(pid, admission_date_iso, ce_disease_id)] = r
            print(
                f"  Cache: {len(eligible)} eligible patients, "
                f"{len(prev_admission_cache)} admission-loop records reusable",
                flush=True,
            )

    # Simulate each patient in chronological order (DES-aware)
    # Hospital state is shared — concurrent patients affect delays
    patient_records: list[CIFPatientRecord] = []
    concurrent_patients: int = 0
    active_discharges: list[tuple] = []  # (discharge_date, beds_freed)
    beds_total = hospital_ops.get("resource_capacity", {}).get("inpatient_beds", 200)

    # Activate each person at most once (stable identity). A person who appears across
    # multiple phases (admission, readmission, post-discharge, calendar, ED) must share a
    # single PatientProfile so their chronic-condition onset/stage, physiological profile,
    # and baseline vitals are consistent across all their encounters. activate_patient
    # re-samples those attributes, so calling it per encounter desynchronizes a patient's
    # own history.
    patient_cache: dict[str, PatientProfile] = {}

    def _activate_cached(p: PersonRecord) -> PatientProfile:
        if p.person_id not in patient_cache:
            # Patient activation is fully determined by patient_id, independent of
            # cursor (snapshot_date) — derive from a per-patient sub-seed rather
            # than the shared master rng so it doesn't shift with cursor movement.
            act_rng = derive_phase_rng(master_seed, PHASE_INPATIENT_SIM, f"activate|{p.person_id}")
            patient_cache[p.person_id] = activate_patient(p, act_rng, demo)
        return patient_cache[p.person_id]

    n_hosp = len(hospital_events)
    # Issue #174: bracket the inpatient loop with `sim_log.phase` so a
    # `tail -f simulator.log` sees `inpatient_loop_start` immediately (not
    # only the paired `_end` when the whole loop finishes) and the total
    # `elapsed_s` is attributable. The 50-record cadence progress line
    # below gets a matching `inpatient_progress` sim_log event so a p=10000
    # run's ~10-minute loop is no longer a JSONL blind window.
    sim_log.info("engine", "inpatient_loop_start", target=n_hosp)
    _t0_inp = time.perf_counter()
    for idx, event in enumerate(hospital_events):
        if (idx + 1) % 50 == 0 or idx == n_hosp - 1:
            print(
                f"  Simulating inpatient {idx + 1}/{n_hosp} "
                f"(concurrent={concurrent_patients}, "
                f"bed_occ={hospital_state.bed_occupancy:.0%})...",
                flush=True,
            )
            sim_log.info(
                "engine",
                "inpatient_progress",
                processed=idx + 1,
                target=n_hosp,
                concurrent=concurrent_patients,
                bed_occupancy=round(hospital_state.bed_occupancy, 3),
            )

        # Advance hospital time — discharge patients who have left
        event_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day, 12, 0)
        hospital_state.update_for_time(event_time, hospital_ops)
        new_active = []
        for dc_date, beds in active_discharges:
            if dc_date <= event.timestamp:
                hospital_state.bed_occupancy = max(0, hospital_state.bed_occupancy - beds)
                concurrent_patients = max(0, concurrent_patients - 1)
            else:
                new_active.append((dc_date, beds))
        active_discharges = new_active

        # Admit: increase bed occupancy
        hospital_state.bed_occupancy = min(0.99, hospital_state.bed_occupancy + 1.0 / beds_total)
        concurrent_patients += 1

        person = population.get_person(event.person_id)
        if person is None or not person.is_alive:
            continue

        patient = _activate_cached(person)
        disease_id = event.disease_id

        # Issue #848: if the patient is currently admitted for an earlier
        # event, this new life event fired *inside* the ongoing
        # hospitalization. Rather than opening a physically-impossible
        # second concurrent encounter, merge the disease into the active
        # record as an in-hospital complication (mirror of what real EHR
        # practice does — cardiology consult / CCU transfer on the same
        # encounter). Skips subsequent per-event scaffolding (rng derive,
        # bed increment, cache lookup, _simulate_patient) because no new
        # encounter is created for this event.
        _active = _find_active_inpatient_record(patient_records, event.person_id, event_time)
        if _active is not None:
            _merge_disease_into_active_encounter(_active, disease_id, event_time)
            # Undo the bed_occupancy / concurrent_patients increments this
            # loop iteration applied above — no new admission was created.
            hospital_state.bed_occupancy = max(0.0, hospital_state.bed_occupancy - 1.0 / beds_total)
            concurrent_patients = max(0, concurrent_patients - 1)
            continue

        event_key = f"{event.person_id}|{event.timestamp.isoformat()}|{disease_id}"
        event_rng = derive_phase_rng(master_seed, PHASE_INPATIENT_SIM, event_key)
        # F4: content-derived cache key — identical shape to `event_key` above,
        # reconstructable from a cached record without having simulated it.
        cache_key = (event.person_id, event.timestamp.isoformat(), disease_id)

        # Unknown condition
        if event.condition_type == "unknown" or disease_id.startswith("unknown_"):
            record: CIFPatientRecord | None
            if cache_key in prev_admission_cache:
                record = prev_admission_cache[cache_key]
                # Issue #761: replay lab/imaging queue increments so later
                # unrelated admissions see the same congestion state as they
                # would on the cold path (the cache-hit admission never
                # entered `calculate_result_time_from_state`).
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
                patient_records.append(record)
                person.has_visited_hospital = True
                person.visit_count += 1
            continue

        protocol = protocols.get(disease_id)
        if protocol is None:
            continue

        # Mixed condition: determine secondary disease from patient's chronic conditions
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
            # Issue #761: replay lab/imaging queue increments so later
            # unrelated admissions see the same congestion state as they
            # would on the cold path (the cache-hit admission never
            # entered `calculate_result_time_from_state`).
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
        patient_records.append(record)
        _deactivate_to_layer1(person, record, disease_id, patient_cache=patient_cache)
        # Track discharge for bed occupancy management
        if record.encounters and record.encounters[0].discharge_datetime:
            dc_date = record.encounters[0].discharge_datetime.date()
            active_discharges.append((dc_date, 1.0 / beds_total))
        if record.deceased:
            person.is_alive = False

    print(f"  Inpatient done: {len(patient_records)} records (peak concurrent: {concurrent_patients})", flush=True)
    sim_log.info(
        "engine",
        "inpatient_loop_done",
        records=len(patient_records),
        peak_concurrent=concurrent_patients,
        elapsed_s=round(time.perf_counter() - _t0_inp, 3),
    )

    # === Readmission evaluation (post-loop pass) ===
    country_key = _country_to_yaml_key(config.country)
    readmission_events: list[LifeEvent] = []
    for record in patient_records:
        if record.deceased or record.is_readmission:
            continue
        person = population.get_person(record.patient.patient_id)
        if not person or not person.is_alive:
            continue
        readmit_disease_id = (
            record.condition_event.ground_truth_diseases[0] if record.condition_event.ground_truth_diseases else None
        )
        if not readmit_disease_id:
            continue
        disease_id = readmit_disease_id
        protocol = protocols.get(disease_id)
        if not protocol:
            continue
        re_key = f"{record.patient.patient_id}|{record.encounters[0].encounter_id}"
        re_rng = derive_phase_rng(master_seed, PHASE_READMISSION, re_key)
        re_event = _evaluate_readmission(
            record,
            person,
            disease_id,
            protocol,
            country_key,
            re_rng,
        )
        if re_event:
            readmission_events.append(re_event)

    # Filter out readmissions past snapshot date
    if snapshot_dt:
        readmission_events = [
            e
            for e in readmission_events
            if not e.timestamp or datetime.combine(e.timestamp, datetime.min.time()) <= snapshot_dt
        ]

    # Simulate readmissions (max 1 chain per patient for now)
    readmission_events.sort(key=lambda e: e.timestamp)
    for re_event in readmission_events:
        person = population.get_person(re_event.person_id)
        if not person or not person.is_alive:
            continue
        protocol = protocols.get(re_event.disease_id)
        if not protocol:
            continue
        # Issue #848: same-patient overlap can also arise when a
        # readmission fires while the patient is still admitted from
        # the previous stay (e.g. a heart-failure exacerbation
        # readmission scheduled 8 days after discharge, but the initial
        # admission had not actually discharged yet in the cursor
        # window). Route through the in-hospital complication merge
        # here too so the readmission dispatch cannot open a physically
        # concurrent second encounter.
        _re_event_time = datetime(re_event.timestamp.year, re_event.timestamp.month, re_event.timestamp.day, 12, 0)
        # Readmission dispatch uses period-overlap (not point-in-time)
        # because it runs AFTER the main inpatient loop — patient_records
        # already contains later life-event admissions whose start is
        # after the readmission's scheduled admit time but whose period
        # overlaps ours. See ``_find_overlapping_inpatient_record`` for
        # rationale.
        _re_overlap = _find_overlapping_inpatient_record(patient_records, re_event.person_id, _re_event_time)
        if _re_overlap is not None:
            _merge_disease_into_active_encounter(_re_overlap, re_event.disease_id, _re_event_time)
            continue
        patient = _activate_cached(person)
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
        patient_records.append(record)
        _deactivate_to_layer1(person, record, re_event.disease_id, patient_cache=patient_cache)
        if record.deceased:
            person.is_alive = False

    print(f"  Readmissions done: {len(readmission_events)} evaluated", flush=True)
    sim_log.info("engine", "readmissions_done", evaluated=len(readmission_events))

    # === Outpatient encounters (healthcare calendar for ALL population) ===
    from clinosim.locale.loader import load_chronic_followup

    followup_data = load_chronic_followup()

    # Post-discharge follow-up for inpatient records
    inpatient_records = [
        r
        for r in patient_records
        if not r.deceased and r.encounters and r.encounters[0].encounter_type == EncounterType.INPATIENT
    ]
    post_dc_spec = followup_data.get("_post_discharge", {})
    post_dc_days = post_dc_spec.get("first_visit_days", 14)

    for record in inpatient_records:
        pid = record.patient.patient_id
        person = population.get_person(pid)
        if not person or not person.is_alive:
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
        # Skip post-discharge visits scheduled after the snapshot date
        if snapshot_dt and followup_date > snapshot_dt:
            continue
        opd_key = f"{pid}|post_discharge|{followup_date.isoformat()}"
        opd_rng = derive_phase_rng(master_seed, PHASE_OUTPATIENT_CAL, opd_key)
        # Continuity of care: the post-discharge follow-up attaches to the
        # same service line as the inpatient stay (a trauma / surgical /
        # cardiology / GI patient is followed up by the same specialty,
        # not general internal medicine).
        opd_dept = resolve_outpatient_department("post_discharge", disease_id, enc.department_id, hospital_ops)
        opd_record = _simulate_outpatient_visit(
            _activate_cached(person),
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

    n_post_dc = len(patient_records) - len(inpatient_records) - len(readmission_events)

    # Healthcare calendar: chronic visits + screening for ALL population
    calendar_key = f"{config.country}|{start_y:04d}|calendar"
    calendar_rng = derive_phase_rng(master_seed, PHASE_OUTPATIENT_CAL, calendar_key)
    calendar_events = generate_healthcare_calendar(population, start_y, config.country, calendar_rng)
    # Filter out events past snapshot date
    if snapshot_dt:
        calendar_events = [
            e
            for e in calendar_events
            if not e.timestamp or datetime.combine(e.timestamp, datetime.min.time()) <= snapshot_dt
        ]
    # Issue #1039: also clamp on the lower bound. `generate_healthcare_calendar`
    # iterates a full calendar year (months 1..12) starting from ``start_y``, so
    # a `--start YYYY-MM-DD` mid-year produces events back to Jan 1 of that
    # year. Filter them out to make the ``[--start, --end]`` window strict
    # (mirror of the snapshot_dt upper clamp above). RNG-neutral: post-
    # generation filter, no rng call count change → no cascade.
    start_dt = _parse_time_range_bound(config.time_range[0])
    calendar_events = [
        e for e in calendar_events if not e.timestamp or datetime.combine(e.timestamp, datetime.min.time()) >= start_dt
    ]
    print(f"  Healthcare calendar: {len(calendar_events)} events for population", flush=True)
    sim_log.info("engine", "healthcare_calendar_generated", events=len(calendar_events))

    n_calendar = 0
    for event in calendar_events:
        person = population.get_person(event.person_id)
        if not person or not person.is_alive:
            continue
        patient = _activate_cached(person)

        # F1: fold disease_id into the key. `generate_healthcare_calendar`
        # can schedule more than one "health_screening"-type event for the same
        # person (annual_health_screening / colonoscopy_screening /
        # mammography_screening all share event_type="health_screening") — if two
        # of them land on the same calendar date, a key without disease_id would
        # give them the identical ev_rng stream (same randomized visit minute) and,
        # combined with the health_screening dispatch below previously hardcoding
        # the same chief_complaint text for all of them, produced two CIFPatientRecords
        # with byte-identical (patient, time, complaint) — a true encounter_id
        # collision (confirmed empirically at p=500: two same-day screenings hashed
        # to one id, silently aliasing two distinct encounters).
        ev_key = f"{event.person_id}|{event.timestamp.isoformat()}|{event.event_type}|{event.disease_id}"
        ev_rng = derive_phase_rng(master_seed, PHASE_OUTPATIENT_CAL, ev_key)

        visit_time = datetime(
            event.timestamp.year,
            event.timestamp.month,
            event.timestamp.day,
            OUTPATIENT_CALENDAR_VISIT_HOUR,
            int(ev_rng.integers(OUTPATIENT_MINUTE_JITTER_MIN, OUTPATIENT_MINUTE_JITTER_MAX_EXCLUSIVE)),
        )

        if event.event_type == "chronic_visit":
            spec = followup_data.get(event.disease_id, {})
            # Merge optional labs: quarterly (25% each visit) and annual (8% each visit)
            visit_labs = list(spec.get("labs", []))
            for lab in spec.get("labs_quarterly", []):
                if ev_rng.random() < OUTPATIENT_LABS_QUARTERLY_PROBABILITY and lab not in visit_labs:
                    visit_labs.append(lab)
            for lab in spec.get("labs_annual", []):
                if ev_rng.random() < OUTPATIENT_LABS_ANNUAL_PROBABILITY and lab not in visit_labs:
                    visit_labs.append(lab)
            # Issue #757: medication-driven monitoring labs. Follows the
            # patient regardless of the visit's primary reason — a
            # warfarin-treated DVT patient whose only chronic follow-up
            # is for hypertension still gets INR checks here. Data-driven
            # via ``med_lab_mapping.yaml``; sub-scope of the monitoring
            # pipeline META. Closes #736 (US warfarin PT_INR 0-obs gap).
            from clinosim.modules.monitoring import monitoring_labs_for_patient

            for lab in monitoring_labs_for_patient(patient.current_medications, ev_rng):
                if lab not in visit_labs:
                    visit_labs.append(lab)
            merged_spec = dict(spec)
            merged_spec["labs"] = visit_labs
            chronic_dept = resolve_outpatient_department("chronic_followup", event.disease_id, None, hospital_ops)
            opd_record = _simulate_outpatient_visit(
                patient,
                "chronic_followup",
                visit_time,
                roster,
                ev_rng,
                chronic_code=event.disease_id,
                followup_spec=merged_spec,
                country=config.country,
                config=config,
                department_id=chronic_dept,
            )
        elif event.event_type == "pediatric_visit":
            # Issue #760 pass 2: well-child visit dispatch. No labs (pediatric
            # well-visits focus on growth-chart vitals + development screen +
            # vaccinations rather than lab draws before school age).
            # `_simulate_outpatient_visit` uses visit_type to select the
            # vitals-set (temp / hr / weight for pediatric, no labs), and the
            # visit_reason is looked up from `pediatric_schedule.yaml`.
            pedi_dept = resolve_outpatient_department("pediatric_visit", event.disease_id, None, hospital_ops)
            opd_record = _simulate_outpatient_visit(
                patient,
                "pediatric_visit",
                visit_time,
                roster,
                ev_rng,
                chronic_code=event.disease_id or "pediatric_visit",
                followup_spec={
                    "labs": [],
                    "visit_reason": _pediatric_visit_reason(event.disease_id),
                },
                country=config.country,
                config=config,
                department_id=pedi_dept,
            )
        elif event.event_type == "abortion":
            # Issue #957 Tier-3-B slice 3: pregnancy termination event
            # (spontaneous O03.9 or induced O04.5). Age-gated abortion
            # outcome resolution runs in the scheduler
            # (``resolve_pregnancy_outcome``); dispatch here just emits
            # the outpatient day-surgery encounter with the pre-decided
            # discharge dx.
            from clinosim.simulator.perinatal import simulate_abortion_encounter

            abortion_records = simulate_abortion_encounter(
                patient=patient,
                visit_date=visit_time,
                discharge_dx=event.disease_id,
                roster=roster,
                rng=ev_rng,
                country=config.country,
                config=config,
                hospital_ops=hospital_ops,
            )
            patient_records.extend(abortion_records)
            n_calendar += 1
            continue
        elif event.event_type == "delivery":
            # Issue #957 Tier-3-B: mother-side perinatal delivery encounter
            # + newborn Patient + Encounter chain (Slice 2). Emits one
            # inpatient encounter for the mother (admission dx O80
            # spontaneous delivery, discharge dx Z37.0 single liveborn,
            # delivery Procedure) AND one for the newborn (admitSource=born,
            # partOf → mother's delivery encounter, discharge dx Z38.0).
            # Prenatal + postpartum AMB visits fire separately as
            # chronic_visit-style events (see
            # ``_pregnancy_lifecycle_events`` in population/engine.py,
            # which owns the full pregnancy lifecycle since META #957
            # Incr 1).
            from clinosim.simulator.perinatal import simulate_delivery_encounter

            delivery_records = simulate_delivery_encounter(
                patient=patient,
                visit_date=visit_time,
                roster=roster,
                rng=ev_rng,
                country=config.country,
                config=config,
                hospital_ops=hospital_ops,
            )
            # Both mother and newborn records land on ``patient_records``;
            # skip the shared single-record append at the bottom of this
            # branch (delivery is the only dispatch that produces >1 record).
            patient_records.extend(delivery_records)
            n_calendar += 1
            continue
        elif event.event_type == "chemo_visit":
            # Issue #957 Tier-3-A: chemo cycle visit dispatch. Uses the
            # existing outpatient visit builder with a chemo-specific
            # followup_spec so the encounter emits with the regimen's
            # visit_reason + department + a Procedure record for the
            # chemotherapy administration. Per-cycle drug MedicationRequest
            # / MedicationAdministration is a follow-up slice.
            regimen_name = event.protocol_source.split(":", 1)[1] if ":" in event.protocol_source else ""
            from clinosim.locale.loader import load_chemo_regimens

            chemo_data = load_chemo_regimens()
            regimen = (chemo_data.get("regimens") or {}).get(regimen_name) or {}
            chemo_spec: dict = {
                "labs": [],  # cycle labs are captured on the sibling chronic_visit; keep chemo_visit lean
                "visit_reason": (chemo_data.get("encounter") or {}).get("visit_reason") or "Chemotherapy infusion",
                "chemo_regimen_name": regimen_name,
                "chemo_regimen": regimen,
                "chemo_procedure": chemo_data.get("procedure") or {},
            }
            chemo_dept = resolve_outpatient_department("chemo_visit", event.disease_id, None, hospital_ops)
            opd_record = _simulate_outpatient_visit(
                patient,
                "chemo_visit",
                visit_time,
                roster,
                ev_rng,
                chronic_code=event.disease_id,
                followup_spec=chemo_spec,
                country=config.country,
                config=config,
                department_id=chemo_dept,
            )
        elif event.event_type == "health_screening":
            # F1: visit_reason must vary by disease_id — see the
            # ev_key comment above. Previously every health_screening dispatch
            # (annual / colonoscopy / mammography) got the identical hardcoded
            # "Annual health screening" text regardless of which screening
            # actually fired, which (combined with a same-day RNG-stream
            # collision) could produce two indistinguishable encounters for a
            # single patient's mammography + annual checkup landing on the
            # same date.
            screening_reason = _HEALTH_SCREENING_VISIT_REASON.get(event.disease_id, "Annual health screening")
            screening_dept = resolve_outpatient_department(
                "health_screening", event.disease_id or "annual_health_screening", None, hospital_ops
            )
            opd_record = _simulate_outpatient_visit(
                patient,
                "health_screening",
                visit_time,
                roster,
                ev_rng,
                chronic_code=event.disease_id or "annual_health_screening",
                followup_spec={
                    "labs": ["WBC", "Hb", "Glucose", "Creatinine", "AST", "ALT"],
                    "visit_reason": screening_reason,
                },
                country=config.country,
                config=config,
                department_id=screening_dept,
            )
        else:
            continue

        patient_records.append(opd_record)
        n_calendar += 1

    print(f"  Outpatient done: {n_post_dc} post-discharge + {n_calendar} calendar", flush=True)
    sim_log.info("engine", "outpatient_done", post_discharge=n_post_dc, calendar=n_calendar)

    # === ED visits (not admitted — auto-discovered from encounter YAMLs) ===
    from clinosim.modules.encounter.protocol import load_all_encounter_conditions

    all_enc_conditions = load_all_encounter_conditions()
    ed_conditions = [
        (name, spec) for name, spec in all_enc_conditions.items() if spec.get("encounter_type") == "emergency"
    ]
    ed_demo = demo.get("ed_visit_not_admitted", {})
    ed_rate = ed_demo.get("rate_per_admitted", ED_RATE_PER_ADMITTED_DEFAULT)
    n_ed = int(len(inpatient_records) * ed_rate)
    if ed_conditions and n_ed > 0:
        for slot in range(n_ed):
            slot_key = f"{config.country}|ed-slot-{slot:06d}"
            slot_rng = derive_phase_rng(master_seed, PHASE_ED_VISIT, slot_key)

            # Apply seasonal modifiers to probabilities for this visit's month.
            # F1: use the uncapped raw_end_y/m (see above) so the draw range —
            # and therefore the sampled value for a given slot — is stable
            # across cursors; the snapshot filter below still enforces cutoff.
            total_months = (raw_end_y - start_y) * 12 + (raw_end_m - start_m) + 1
            month_offset = int(slot_rng.integers(0, total_months))
            visit_month = ((start_m - 1 + month_offset) % 12) + 1

            # Select person first (uniform), then filter conditions by their occupation
            person_id = slot_rng.choice(list(population.persons.keys()))
            person = population.get_person(person_id)
            if not person or not person.is_alive:
                continue
            patient = _activate_cached(person)

            # Build condition probabilities weighted by occupation risk
            occupation = getattr(person, "occupation", "other")
            occ_mult_table = demo.get("occupation_risk_multipliers", {})
            ed_probs = []
            for name, spec in ed_conditions:
                base_p = spec.get("probability", 0.05)
                seasonal = spec.get("seasonal", {})
                seasonal_mod = float(seasonal.get(visit_month, seasonal.get(str(visit_month), 1.0)))
                occ_mults = occ_mult_table.get(name, {})
                if occ_mults:
                    # Work-related condition — use 0.05 default for non-matching occupations
                    occ_mod = occ_mults.get(occupation, ED_OCCUPATION_MISMATCH_FALLBACK)
                else:
                    occ_mod = 1.0
                ed_probs.append(base_p * seasonal_mod * occ_mod)
            total_p = sum(ed_probs)
            if total_p <= 0:
                continue
            ed_probs = [p / total_p for p in ed_probs]
            cond_idx = int(slot_rng.choice(len(ed_conditions), p=ed_probs))
            cond_name, cond = ed_conditions[cond_idx]
            # Use the same month that seasonal modifiers were calculated for
            ed_year = start_y + (start_m - 1 + month_offset) // 12
            ed_day = int(slot_rng.integers(ED_DAY_MIN, ED_DAY_MAX_EXCLUSIVE))
            ed_hour = int(slot_rng.choice(ED_FAVORED_HOURS))
            ed_time = datetime(
                ed_year,
                visit_month,
                ed_day,
                ed_hour,
                int(slot_rng.integers(ED_MINUTE_JITTER_MIN, ED_MINUTE_JITTER_MAX_EXCLUSIVE)),
            )
            # Skip ED visits past snapshot date
            if snapshot_dt and ed_time > snapshot_dt:
                continue

            ed_record = _simulate_ed_visit(
                patient,
                cond,
                ed_time,
                roster,
                slot_rng,
                country=config.country,
                config=config,
            )
            patient_records.append(ed_record)
        print(f"  ED visits (not admitted): {n_ed} generated", flush=True)
        sim_log.info("engine", "ed_visits_generated", ed_visits=n_ed)

    # Post-records enrichers (AD-56) — opt-in modules that read/extend finished records
    # (e.g. billing, devices, care-coordination write to CIFPatientRecord.extensions).
    # RM-3: pass roster so immunization enricher can populate
    # ImmunizationRecord.administered_by from the nurse pool.
    run_stage(
        POST_RECORDS,
        EnricherContext(
            config=config,
            master_seed=config.random_seed,
            population=population,
            records=patient_records,
            roster=roster,
        ),
    )

    metadata = CIFMetadata(
        clinosim_version=_clinosim_version,
        random_seed=config.random_seed,
        country=config.country,
        hospital_scale=config.hospital_scale,
        snapshot_date=config.snapshot_date,
        total_patients_generated=len(patient_records),
        llm_mode=config.llm.judgment.mode,
    )
    # L2 profile: emit one summary line per (stage, enricher) with total
    # wall-clock and call count, then clear the accumulator for the next run.
    sim_log.flush_stage_totals()
    sim_log.info(
        "engine",
        "run_beta_done",
        patients=len(patient_records),
        country=config.country,
        seed=config.random_seed,
    )
    return CIFDataset(
        metadata=metadata,
        patients=patient_records,
        hospital_roster=list(roster.members),
        hospital_config=hospital_ops or {},
    )


def run_forced(scenario: ForcedScenario, config: SimulatorConfig | None = None) -> CIFDataset:
    """Generate data for a specific forced scenario only. No population needed.

    Usage:
        from clinosim.types.config import ForcedScenario, SimulatorConfig
        scenario = ForcedScenario(disease_id="bacterial_pneumonia", count=5, archetype="treatment_resistant")
        dataset = run_forced(scenario)
    """
    if config is None:
        config = SimulatorConfig()

    # AD-60 / PR-90 class silent-no-op gate: ensure force_hai_event-carrying
    # scenarios reach enrich_hai, which reads from ctx.config.forced_scenarios
    # (not from the run_forced scenario argument). Without this injection,
    # force_hai_event is silently ignored.
    if scenario.force_hai_event is not None and scenario not in config.forced_scenarios:
        config = config.model_copy(update={"forced_scenarios": [*config.forced_scenarios, scenario]})

    rng = determinism.default_rng(config.random_seed)
    healthcare = load_healthcare_config(config.country)
    roster = generate_roster(config.hospital_scale, config.country, rng)
    _demo = load_demographics(config.country)

    protocol = load_disease_protocol(scenario.disease_id)

    # Register built-in enrichers so the POST_ENCOUNTER stage that
    # ``_simulate_patient`` invokes (device + hai + Phase 3a lab lift) has
    # something to dispatch. Without this, ``clinosim test-disease`` /
    # forced-scenario QA paths silently produce records with no device,
    # no HAI events, and no lab lift even though the inpatient simulator
    # explicitly runs the POST_ENCOUNTER hook.
    register_builtin_enrichers()

    patient_records: list[CIFPatientRecord] = []

    for i in range(scenario.count):
        # Create patient (from overrides or random)
        if scenario.patient_overrides:
            age = scenario.patient_overrides.get("age", FORCED_SCENARIO_DEFAULT_AGE)
            sex = scenario.patient_overrides.get("sex", FORCED_SCENARIO_DEFAULT_SEX)
        else:
            age = int(rng.integers(FORCED_SCENARIO_AGE_MIN, FORCED_SCENARIO_AGE_MAX_EXCLUSIVE))
            sex = str(rng.choice(["M", "F"]))

        # Create a minimal PersonRecord for activation
        person = PersonRecord(
            person_id=f"FORCED-{i + 1:04d}",
            household_id=f"HH-FORCED-{i + 1:04d}",
            age=age,
            sex=sex,
            date_of_birth=date(FORCED_SCENARIO_REFERENCE_YEAR - age, 1, 1),
            family_name="テスト" if is_jp(config.country) else "Test",
            given_name=f"患者{i + 1}" if is_jp(config.country) else f"Patient{i + 1}",
            chronic_conditions=scenario.patient_overrides.get("chronic_conditions", []),
        )
        patient = activate_patient(person, rng, _demo)

        # Force severity and archetype
        severity = scenario.severity or FORCED_SCENARIO_DEFAULT_SEVERITY

        # Create life event
        event = LifeEvent(
            person_id=patient.patient_id,
            event_type="forced",
            timestamp=FORCED_SCENARIO_EVENT_DATE,
            severity=FORCED_SCENARIO_SEVERITY_FRACTIONS.get(severity, FORCED_SCENARIO_SEVERITY_FRACTION_FALLBACK),
            disease_id=scenario.disease_id,
            requires_hospital=True,
            condition_type="known_disease",
        )

        record = _simulate_patient(
            patient,
            event,
            scenario.disease_id,
            protocol,
            healthcare,
            roster,
            config,
            rng,
            forced_severity=scenario.severity,
            forced_archetype=scenario.archetype,
        )

        # Force specific complications if requested
        if scenario.complications:
            record.complications_occurred.extend(scenario.complications)

        patient_records.append(record)

    metadata = CIFMetadata(
        clinosim_version=_clinosim_version,
        random_seed=config.random_seed,
        country=config.country,
        hospital_scale=config.hospital_scale,
        snapshot_date=config.snapshot_date,
        total_patients_generated=len(patient_records),
        llm_mode="none",
    )
    return CIFDataset(
        metadata=metadata, patients=patient_records, hospital_roster=list(roster.members), hospital_config={}
    )


def run_alpha(config: SimulatorConfig | None = None) -> CIFDataset:
    """Backward-compatible alpha: 1 pneumonia patient via ForcedScenario."""
    scenario = ForcedScenario(
        disease_id="bacterial_pneumonia",
        count=1,
        severity="moderate",
        archetype="smooth_recovery",
        patient_overrides={"age": 72, "sex": "F"},
    )
    return run_forced(scenario, config)
