"""Simulator engine — run_beta, run_forced, run_alpha entry points."""

from __future__ import annotations

import calendar
import time
from datetime import date, datetime
from pathlib import Path

from clinosim import __version__ as _clinosim_version
from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.modules._shared import is_jp
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.healthcare_system.loader import load_healthcare_config
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import (
    LifeEvent,
    PersonRecord,
    generate_monthly_events,
    generate_population,
)
from clinosim.modules.population.vital_status import death_counts_by_place, sync_profile_death_dates
from clinosim.modules.staff.engine import generate_roster
from clinosim.seeding import (
    PHASE_LIFE_EVENT,
    derive_phase_rng,
)
from clinosim.simulator import log as sim_log
from clinosim.simulator._dispatch import (
    _dispatch_hospital_events as _dispatch_hospital_events,
)
from clinosim.simulator._dispatch import (
    _DispatchState as _DispatchState,
)
from clinosim.simulator._dispatch import (
    _find_active_inpatient_record as _find_active_inpatient_record,
)
from clinosim.simulator._dispatch import (
    _find_overlapping_inpatient_record as _find_overlapping_inpatient_record,
)
from clinosim.simulator._dispatch import (
    _handle_overlap_via_merge as _handle_overlap_via_merge,
)
from clinosim.simulator._dispatch import (
    _merge_disease_into_active_encounter as _merge_disease_into_active_encounter,
)
from clinosim.simulator._dispatch import (
    _replay_cached_admission_queue as _replay_cached_admission_queue,
)
from clinosim.simulator._dispatch import (
    _verify_no_actual_overlap as _verify_no_actual_overlap,
)
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
from clinosim.simulator._setup import (
    _HEALTH_SCREENING_VISIT_REASON as _HEALTH_SCREENING_VISIT_REASON,
)
from clinosim.simulator._setup import (
    _HEALTH_SCREENING_VISIT_REASON_FALLBACK as _HEALTH_SCREENING_VISIT_REASON_FALLBACK,
)
from clinosim.simulator._setup import (
    _activate_cached_person as _activate_cached_person,
)
from clinosim.simulator._setup import (
    _derive_time_range_bounds as _derive_time_range_bounds,
)
from clinosim.simulator._setup import (
    _load_hospital_ops as _load_hospital_ops,
)
from clinosim.simulator._setup import (
    _load_prev_admission_cache as _load_prev_admission_cache,
)
from clinosim.simulator._setup import (
    _parse_time_range_bound as _parse_time_range_bound,
)
from clinosim.simulator._setup import (
    _pediatric_visit_reason as _pediatric_visit_reason,
)
from clinosim.simulator._setup import (
    _resolve_pop_size as _resolve_pop_size,
)
from clinosim.simulator._setup import (
    _TimeRangeBounds as _TimeRangeBounds,
)
from clinosim.simulator.complications import build_complication
from clinosim.simulator.enrichers import (
    POST_POPULATION,
    POST_RECORDS,
    EnricherContext,
    register_builtin_enrichers,
    run_stage,
)
from clinosim.simulator.helpers import (
    _country_to_yaml_key,
    load_all_disease_protocols,
)
from clinosim.simulator.inpatient import _simulate_patient
from clinosim.simulator.phases._ed_slot import (
    _run_ed_slot_phase as _run_ed_slot_phase,
)
from clinosim.simulator.phases._healthcare_calendar import (
    _run_healthcare_calendar_phase as _run_healthcare_calendar_phase,
)
from clinosim.simulator.phases._post_discharge import (
    _run_post_discharge_phase as _run_post_discharge_phase,
)
from clinosim.simulator.phases._readmission import (
    _run_readmission_phase as _run_readmission_phase,
)
from clinosim.types.config import ForcedScenario, SimulatorConfig
from clinosim.types.encounter import EncounterType
from clinosim.types.output import CIFDataset, CIFMetadata, CIFPatientRecord
from clinosim.types.patient import PatientProfile

# F1: `generate_healthcare_calendar` emits several distinct
# screening kinds under the same `event_type == "health_screening"` (see the
# ev_key comment in the P4 calendar loop below). Each needs its own visit
# reason text so two screenings landing on the same calendar date don't
# collapse into indistinguishable encounters.
# Visit-reason display per screening sub-kind — authoritative yaml at
# `clinosim/locale/shared/health_screening_visit_reason.yaml`
# (hardcoded-review Phase A7). Loader-backed module-level aliases so
# every call site and the pin test (tests/unit/simulator/
# test_chief_complaint_localization.py) stays unchanged.
# ============================================================
# Main entry point
# ============================================================


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

    # Issue #1736 — the newborn baseline-screen dedup tracker (hearing +
    # metabolic once-per-newborn Procedures) is module-level state in
    # ``clinosim.modules.newborn.engine``; clear it at the top of every
    # ``run_beta`` call so a second ``simulate()`` within the same Python
    # process starts from a clean slate.
    from clinosim.modules.newborn import reset_perinatal_baseline_tracker as _reset_perinatal

    _reset_perinatal()

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
    from clinosim.modules.facility.hospital_state import HospitalState

    hospital_ops = _load_hospital_ops(hospital_config_path)

    # Staff roster scaled to hospital config (ward-aware, dept-aware).
    # C5-25 (Chain 3, 2026-07-11): use a dedicated sub-RNG so roster
    # changes (e.g., adding allied-health roles) don't shift downstream
    # RNG state (population / life events). Mirrors the AD-16 sub-seed
    # pattern used by module enrichers.
    _roster_rng = determinism.default_rng(config.random_seed ^ 0x524F5354)  # "ROST"
    # Issue #2128: the hospital config names its own scale.
    hospital_scale = str(hospital_ops.get("hospital_scale") or config.hospital_scale)
    from clinosim.simulator.hospital_ops import inpatient_departments

    _inpatient_depts = inpatient_departments(hospital_ops)
    roster = generate_roster(hospital_scale, config.country, _roster_rng, hospital_config=hospital_ops)
    hospital_state = HospitalState()

    pop_size = _resolve_pop_size(hospital_ops, config)
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

    # Run life events — resolve month-loop bounds + snapshot cap.
    # See _derive_time_range_bounds / _TimeRangeBounds for the F1 raw-vs-
    # capped end rationale and the Issue #1039 start_dt_lb filter.
    bounds = _derive_time_range_bounds(config)
    start_y, start_m = bounds.start_y, bounds.start_m
    end_y, end_m = bounds.end_y, bounds.end_m
    snapshot_dt = bounds.snapshot_dt
    _start_dt_lb = bounds.start_dt_lb
    # Simulation window as dates (Issue #2167: the annual mortality draw
    # covers only the part of each year inside it). A month-precision end
    # bound ("YYYY-MM") covers the whole month.
    _raw_end = _parse_time_range_bound(config.time_range[1]).date()
    if len(str(config.time_range[1])) == 7:
        _raw_end = date(_raw_end.year, _raw_end.month, calendar.monthrange(_raw_end.year, _raw_end.month)[1])
    _window = (_start_dt_lb.date(), _raw_end)

    # Issue #1596 Step 2 — generation now runs INSIDE the combined
    # per-month loop below (after F4 cache load + patient state init
    # + ``_dispatch_hospital_events`` definition), not here as a
    # separate pre-dispatch pass. The per-year ``advance_population``
    # hook is imported here but called inside that same loop so the
    # primary + newborn paths are symmetrical.
    from clinosim.modules.population.aging import advance_population

    # F4: previous-snapshot admission-loop cache. Only the primary
    # admission loop below (known_disease/mixed via ``_simulate_patient``
    # and unknown-condition via ``_simulate_unknown_condition``)
    # consults this cache — it is the single most expensive per-event
    # computation (full daily-loop physiology simulation).
    prev_admission_cache = _load_prev_admission_cache(cache_dir, config)

    # Simulate each patient in chronological order (DES-aware).
    # Hospital state is shared — concurrent patients affect delays.
    patient_records: list[CIFPatientRecord] = []
    dispatch_state = _DispatchState()
    beds_total = hospital_ops.get("resource_capacity", {}).get("inpatient_beds", 200)

    # Activate each person at most once (stable identity). A person who appears across
    # multiple phases (admission, readmission, post-discharge, calendar, ED) must share a
    # single PatientProfile so their chronic-condition onset/stage, physiological profile,
    # and baseline vitals are consistent across all their encounters. activate_patient
    # re-samples those attributes, so calling it per encounter desynchronizes a patient's
    # own history.
    # Issue #1581 — the cache key is now (person_id, as_of_year) so an
    # encounter in sim year 1 can see a Layer-2 PatientProfile whose
    # chronic_conditions[*].stage reflects the year-1 stage from
    # person.disease_stage_history, rather than always the end-of-sim
    # snapshot. ``as_of_year=None`` preserves the pre-#1581 behaviour
    # (single cached profile per person, latest-only stage).
    patient_cache: dict[tuple[str, int | None], PatientProfile] = {}

    # Issue #174: bracket the inpatient loop with ``sim_log.phase`` so
    # a ``tail -f simulator.log`` sees ``inpatient_loop_start``
    # immediately (not only the paired ``_end`` when the whole loop
    # finishes) and the total ``elapsed_s`` is attributable.
    sim_log.info("engine", "inpatient_loop_start")
    _t0_inp = time.perf_counter()

    # Issue #1596 Step 2 — combined per-month generation + dispatch.
    # Replaces (a) the pre-#1596 pre-generation loop + global filter
    # /sort pass and (b) the Step-1 per-month dispatch of a globally
    # sorted ``hospital_events`` list. Running generation INSIDE this
    # loop means newborns registered during month m's dispatch
    # (perinatal delivery handler) become visible to month m+1's
    # ``generate_monthly_events`` naturally — no secondary monthly
    # events pass needed.
    #
    # Byte-identity for no-births cohorts: preserved (same seeds, same
    # populations seen by each month's ``generate_monthly_events``,
    # same per-month filter + sort). For with-births cohorts byte-
    # identity intentionally breaks: newborn events previously came
    # from a secondary-pass RNG keyed by ``f"newborn|{y}-{m}"`` and
    # now come from the primary RNG keyed by ``f"{y}-{m}"`` — the
    # cohort's clinical content is equivalent but byte sequences
    # differ. MINOR version appropriate (CIF drift, cf.
    # feedback_versioning_policy).
    #
    # ``total_hospital`` is the running cumulative count of dispatched
    # hospital events. The dispatch function's progress trigger
    # ``_progress_cumul == total`` fires at each chunk's final event
    # when we pass the running total — matches the pre-#1596 cadence
    # for at-least-one-progress-event-per-chunk.
    all_events: list[LifeEvent] = []
    total_hospital = 0

    _dy, _dm = start_y, start_m
    while (_dy, _dm) <= (end_y, end_m):
        # Issue #1564 Phase 2: run the aging hook at the first month
        # of each calendar year (January) and at the very first
        # iteration of the sim window (even if the window starts
        # mid-year).
        if _dm == 1 or (_dy, _dm) == (start_y, start_m):
            advance_population(population, _dy, config.country, window=_window)
        _month_key = f"{_dy:04d}-{_dm:02d}"
        _month_rng = derive_phase_rng(master_seed, PHASE_LIFE_EVENT, _month_key)
        _monthly = generate_monthly_events(
            population,
            _dy,
            _dm,
            _month_rng,
            country=config.country,
            master_seed=master_seed,
            inpatient_departments=_inpatient_depts,
        )
        # Per-month equivalents of the pre-#1596 global snapshot_dt +
        # ``_start_dt_lb`` filters. Equivalent because the global
        # filters were RNG-neutral and purely date-based.
        if snapshot_dt:
            _monthly = [
                e
                for e in _monthly
                if not e.timestamp or datetime.combine(e.timestamp, datetime.min.time()) <= snapshot_dt
            ]
        _monthly = [
            e for e in _monthly if not e.timestamp or datetime.combine(e.timestamp, datetime.min.time()) >= _start_dt_lb
        ]
        all_events.extend(_monthly)
        _hospital_chunk = sorted(
            [e for e in _monthly if e.requires_hospital],
            key=lambda e: e.timestamp,
        )
        total_hospital += len(_hospital_chunk)
        if _hospital_chunk:
            _dispatch_hospital_events(
                events=_hospital_chunk,
                total=total_hospital,
                label="inpatient",
                state=dispatch_state,
                patient_records=patient_records,
                patient_cache=patient_cache,
                prev_admission_cache=prev_admission_cache,
                population=population,
                hospital_state=hospital_state,
                hospital_ops=hospital_ops,
                beds_total=beds_total,
                protocols=protocols,
                healthcare=healthcare,
                roster=roster,
                config=config,
                master_seed=master_seed,
                demo=demo,
            )
        _dm += 1
        if _dm > 12:
            _dm, _dy = 1, _dy + 1

    print(f"  Life events: {len(all_events)} total, {total_hospital} requiring hospital")
    sim_log.info(
        "engine",
        "life_events_generated",
        total=len(all_events),
        hospital=total_hospital,
    )
    print(
        f"  Inpatient done: {len(patient_records)} records (peak concurrent: {dispatch_state.concurrent_patients})",
        flush=True,
    )
    sim_log.info(
        "engine",
        "inpatient_loop_done",
        records=len(patient_records),
        peak_concurrent=dispatch_state.concurrent_patients,
        elapsed_s=round(time.perf_counter() - _t0_inp, 3),
    )

    # Issue #1596 Steps 3/4 — the newborn aging catch-up pass and the
    # ``advance_population(... person_filter=...)`` kwarg that
    # supported it are gone. Under Step 2's combined gen+dispatch
    # loop newborns registered during year y's dispatch are already
    # in ``population.persons`` by the (y+1, 1) iteration, so the
    # primary ``advance_population(y+1)`` picks them up naturally.

    # === Readmission evaluation (post-loop pass) ===
    country_key = _country_to_yaml_key(config.country)
    n_readmit = _run_readmission_phase(
        patient_records=patient_records,
        population=population,
        protocols=protocols,
        snapshot_dt=snapshot_dt,
        master_seed=master_seed,
        country_key=country_key,
        healthcare=healthcare,
        roster=roster,
        config=config,
        hospital_state=hospital_state,
        hospital_ops=hospital_ops,
        patient_cache=patient_cache,
        demo=demo,
    )
    print(f"  Readmissions done: {n_readmit} evaluated", flush=True)
    sim_log.info("engine", "readmissions_done", evaluated=n_readmit)

    # === Outpatient encounters (healthcare calendar for ALL population) ===
    from clinosim.locale.loader import load_chronic_followup

    followup_data = load_chronic_followup()

    # Post-discharge follow-up for inpatient records
    inpatient_records = [
        r
        for r in patient_records
        if not r.deceased and r.encounters and r.encounters[0].encounter_type == EncounterType.INPATIENT
    ]
    n_post_dc = _run_post_discharge_phase(
        inpatient_records=inpatient_records,
        patient_records=patient_records,
        population=population,
        followup_data=followup_data,
        snapshot_dt=snapshot_dt,
        master_seed=master_seed,
        patient_cache=patient_cache,
        demo=demo,
        roster=roster,
        config=config,
        hospital_ops=hospital_ops,
    )

    # Healthcare calendar: chronic visits + screening for ALL population.
    # Issue #1129 (2026-09-05): per-year loop over [start_y, end_y]
    # so a multi-year sim emits every year's chronic-follow-up /
    # screening events (pre-fix: only start_y, giving ~23 % of the
    # expected AMB rate at 5-year sim).
    n_cal_events, n_calendar = _run_healthcare_calendar_phase(
        patient_records=patient_records,
        population=population,
        bounds=bounds,
        master_seed=master_seed,
        patient_cache=patient_cache,
        demo=demo,
        followup_data=followup_data,
        roster=roster,
        config=config,
        hospital_ops=hospital_ops,
    )
    print(f"  Healthcare calendar: {n_cal_events} events for population", flush=True)
    sim_log.info("engine", "healthcare_calendar_generated", events=n_cal_events)

    print(f"  Outpatient done: {n_post_dc} post-discharge + {n_calendar} calendar", flush=True)
    sim_log.info("engine", "outpatient_done", post_discharge=n_post_dc, calendar=n_calendar)

    # === ED visits (not admitted — auto-discovered from encounter YAMLs) ===
    n_ed = _run_ed_slot_phase(
        inpatient_records=inpatient_records,
        patient_records=patient_records,
        population=population,
        demo=demo,
        roster=roster,
        config=config,
        bounds=bounds,
        master_seed=master_seed,
        patient_cache=patient_cache,
        hospital_ops=hospital_ops,
    )
    if n_ed > 0:
        print(f"  ED visits (not admitted): {n_ed} generated", flush=True)
        sim_log.info("engine", "ed_visits_generated", ed_visits=n_ed)

    # Issue #2166: every profile of a person carries the person's one death
    # date (as known at the snapshot or window end), including profiles that
    # were activated for visits before the death.
    _vital_as_of = snapshot_dt.date() if snapshot_dt else _raw_end
    sync_profile_death_dates(patient_records, population, as_of=_vital_as_of)
    sim_log.info(
        "engine",
        "deaths_by_place",
        **death_counts_by_place(population, _start_dt_lb.date(), _vital_as_of),
    )

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
        hospital_scale=hospital_scale,
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
            # Phase 1a: wrap forced-scenario complications in the canonical
            # dict shape. Enumeration / forced-scenario paths do not carry
            # per-complication onset info (they inject test-scoped adverse
            # events wholesale) — leave onset_day / onset_datetime None
            # and tag source="scenario_forced" so downstream consumers can
            # distinguish these from real simulation output.
            for _c in scenario.complications:
                record.complications_occurred.append(
                    build_complication(
                        name=str(_c),
                        onset_day=None,
                        onset_datetime=None,
                        source="scenario_forced",
                    )
                )

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
