"""Simulator engine — run_beta, run_forced, run_alpha entry points."""

from __future__ import annotations

import calendar
from datetime import date
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
    generate_population,
)
from clinosim.modules.population.vital_status import death_counts_by_place, sync_profile_death_dates
from clinosim.modules.staff.engine import generate_roster
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
from clinosim.simulator.phases._forward_loop import ForwardContext, run_forward_loop
from clinosim.types.config import ForcedScenario, SimulatorConfig
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

    # Resolve month-loop bounds + snapshot cap.
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

    # F4: previous-snapshot admission-loop cache. Only the inpatient
    # dispatch consults this cache — it is the single most expensive
    # per-event computation (full daily-loop physiology simulation).
    prev_admission_cache = _load_prev_admission_cache(cache_dir, config)

    # Activate each person at most once per (person_id, as_of_year) so a
    # person who appears across admission, readmission, post-discharge,
    # calendar and ED encounters shares one PatientProfile (consistent
    # chronic-condition onset/stage, physiology and baseline vitals).
    patient_cache: dict[tuple[str, int | None], PatientProfile] = {}
    patient_records: list[CIFPatientRecord] = []

    from clinosim.locale.loader import load_chronic_followup

    # Issue #2169: every phase — aging and mortality, life events,
    # admissions, readmissions, post-discharge follow-up, the healthcare
    # calendar (deliveries included) and ED visits — advances in one
    # month-by-month forward loop. See ``phases/_forward_loop.py``.
    ctx = ForwardContext(
        config=config,
        master_seed=master_seed,
        population=population,
        patient_records=patient_records,
        patient_cache=patient_cache,
        prev_admission_cache=prev_admission_cache,
        hospital_state=hospital_state,
        hospital_ops=hospital_ops,
        beds_total=hospital_ops.get("resource_capacity", {}).get("inpatient_beds", 200),
        inpatient_departments=_inpatient_depts,
        protocols=protocols,
        healthcare=healthcare,
        roster=roster,
        demo=demo,
        followup_data=load_chronic_followup(),
        country_key=_country_to_yaml_key(config.country),
        window=_window,
        cutoff=snapshot_dt.date() if snapshot_dt else _raw_end,
    )
    months: list[tuple[int, int]] = []
    _dy, _dm = start_y, start_m
    while (_dy, _dm) <= (end_y, end_m):
        months.append((_dy, _dm))
        _dy, _dm = (_dy + 1, 1) if _dm == 12 else (_dy, _dm + 1)

    sim_log.info("engine", "forward_loop_start", months=len(months))
    run_forward_loop(ctx, months)
    print(
        f"  Forward loop done: {len(patient_records)} records, {ctx.n_hospital_events} hospital events "
        f"(peak concurrent: {ctx.dispatch_state.concurrent_patients})",
        flush=True,
    )

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
        simulation_period_start=_window[0],
        simulation_period_end=_window[1],
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
