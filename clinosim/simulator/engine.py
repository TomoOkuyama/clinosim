"""Simulator engine — run_beta, run_forced, run_alpha entry points."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from clinosim.locale.loader import load_demographics
from clinosim.modules._shared import is_jp
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.healthcare_system.loader import load_healthcare_config
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import (
    LifeEvent,
    PersonRecord,
    generate_healthcare_calendar,
    generate_monthly_events,
    generate_population,
)
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator import log as sim_log
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
    _load_all_disease_protocols,
    _select_secondary_disease,
)
from clinosim.simulator.inpatient import _simulate_patient, _simulate_unknown_condition
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.simulator.seeding import (
    PHASE_ED_VISIT,
    PHASE_INPATIENT_SIM,
    PHASE_LIFE_EVENT,
    PHASE_OUTPATIENT_CAL,
    PHASE_READMISSION,
    derive_phase_rng,
)
from clinosim.types.config import ForcedScenario, SimulatorConfig
from clinosim.types.encounter import EncounterType
from clinosim.types.output import CIFDataset, CIFMetadata, CIFPatientRecord
from clinosim.types.patient import PatientProfile

# F1 (session 49): `generate_healthcare_calendar` emits several distinct
# screening kinds under the same `event_type == "health_screening"` (see the
# ev_key comment in the P4 calendar loop below). Each needs its own visit
# reason text so two screenings landing on the same calendar date don't
# collapse into indistinguishable encounters.
_HEALTH_SCREENING_VISIT_REASON = {
    "annual_health_screening": "Annual health screening",
    "colonoscopy_screening": "Colonoscopy screening",
    "mammography_screening": "Mammography screening",
}


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

    rng = np.random.default_rng(config.random_seed)
    # F1 (session 49): P1/P2/P3/P4/P4' below derive per-key sub-seeds from
    # master_seed instead of consuming the shared `rng` stream, so that
    # cursor movement (snapshot_date change) cannot shift RNG state for
    # entities that are unaffected by the cursor (cross-cursor determinism).
    master_seed = config.random_seed

    # Load modules
    healthcare = load_healthcare_config(config.country)
    protocols = _load_all_disease_protocols()
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
    _roster_rng = np.random.default_rng(config.random_seed ^ 0x524F5354)  # "ROST"
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
    # F1 (session 49): keep the *uncapped* end alongside the snapshot-capped one.
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

    # F4 (session 49): load a previous-snapshot cache, if given and valid. Only
    # the primary admission loop below (known_disease/mixed via `_simulate_patient`
    # and unknown-condition via `_simulate_unknown_condition`) consults this cache —
    # it is the single most expensive per-event computation (full daily-loop
    # physiology simulation). F1's per-event sub-seed determinism guarantees the
    # cache-hit admission's OWN record is byte-identical to what a fresh
    # simulation of that same event would produce. This does NOT extend to every
    # downstream side effect of skipping `_simulate_patient`, however — see
    # `clinosim/simulator/memoize.py` module docstring ("既知の限界 2 件") for two
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
    for idx, event in enumerate(hospital_events):
        if (idx + 1) % 50 == 0 or idx == n_hosp - 1:
            print(
                f"  Simulating inpatient {idx + 1}/{n_hosp} "
                f"(concurrent={concurrent_patients}, "
                f"bed_occ={hospital_state.bed_occupancy:.0%})...",
                flush=True,
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
        _deactivate_to_layer1(person, record, disease_id)
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
        _deactivate_to_layer1(person, record, re_event.disease_id)
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
    print(f"  Healthcare calendar: {len(calendar_events)} events for population", flush=True)
    sim_log.info("engine", "healthcare_calendar_generated", events=len(calendar_events))

    n_calendar = 0
    for event in calendar_events:
        person = population.get_person(event.person_id)
        if not person or not person.is_alive:
            continue
        patient = _activate_cached(person)

        # F1 (session 49): fold disease_id into the key. `generate_healthcare_calendar`
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
            event.timestamp.year, event.timestamp.month, event.timestamp.day, 10, int(ev_rng.integers(0, 45))
        )

        if event.event_type == "chronic_visit":
            spec = followup_data.get(event.disease_id, {})
            # Merge optional labs: quarterly (25% each visit) and annual (8% each visit)
            visit_labs = list(spec.get("labs", []))
            for lab in spec.get("labs_quarterly", []):
                if ev_rng.random() < 0.25 and lab not in visit_labs:
                    visit_labs.append(lab)
            for lab in spec.get("labs_annual", []):
                if ev_rng.random() < 0.08 and lab not in visit_labs:
                    visit_labs.append(lab)
            merged_spec = dict(spec)
            merged_spec["labs"] = visit_labs
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
            )
        elif event.event_type == "health_screening":
            # F1 (session 49): visit_reason must vary by disease_id — see the
            # ev_key comment above. Previously every health_screening dispatch
            # (annual / colonoscopy / mammography) got the identical hardcoded
            # "Annual health screening" text regardless of which screening
            # actually fired, which (combined with a same-day RNG-stream
            # collision) could produce two indistinguishable encounters for a
            # single patient's mammography + annual checkup landing on the
            # same date.
            screening_reason = _HEALTH_SCREENING_VISIT_REASON.get(event.disease_id, "Annual health screening")
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
            )
        else:
            continue

        patient_records.append(opd_record)
        n_calendar += 1

    print(f"  Outpatient done: {n_post_dc} post-discharge + {n_calendar} calendar", flush=True)

    # === ED visits (not admitted — auto-discovered from encounter YAMLs) ===
    from clinosim.modules.encounter.protocol import load_all_encounter_conditions

    all_enc_conditions = load_all_encounter_conditions()
    ed_conditions = [
        (name, spec) for name, spec in all_enc_conditions.items() if spec.get("encounter_type") == "emergency"
    ]
    ed_demo = demo.get("ed_visit_not_admitted", {})
    ed_rate = ed_demo.get("rate_per_admitted", 3.0)
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
                    occ_mod = occ_mults.get(occupation, 0.05)
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
            ed_day = int(slot_rng.integers(1, 28))
            ed_hour = int(slot_rng.choice([9, 10, 14, 15, 19, 20, 21, 22]))
            ed_time = datetime(ed_year, visit_month, ed_day, ed_hour, int(slot_rng.integers(0, 60)))
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
    # RM-3 (session 42): pass roster so immunization enricher can populate
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
        clinosim_version="0.1.0",
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

    rng = np.random.default_rng(config.random_seed)
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
            age = scenario.patient_overrides.get("age", 72)
            sex = scenario.patient_overrides.get("sex", "F")
        else:
            age = int(rng.integers(55, 95))
            sex = str(rng.choice(["M", "F"]))

        # Create a minimal PersonRecord for activation
        person = PersonRecord(
            person_id=f"FORCED-{i + 1:04d}",
            household_id=f"HH-FORCED-{i + 1:04d}",
            age=age,
            sex=sex,
            date_of_birth=date(2024 - age, 1, 1),
            family_name="テスト" if is_jp(config.country) else "Test",
            given_name=f"患者{i + 1}" if is_jp(config.country) else f"Patient{i + 1}",
            chronic_conditions=scenario.patient_overrides.get("chronic_conditions", []),
        )
        patient = activate_patient(person, rng, _demo)

        # Force severity and archetype
        severity = scenario.severity or "moderate"

        # Create life event
        event = LifeEvent(
            person_id=patient.patient_id,
            event_type="forced",
            timestamp=date(2024, 6, 15),
            severity={"mild": 0.2, "moderate": 0.5, "severe": 0.8}.get(severity, 0.5),
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
        clinosim_version="0.1.0",
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
