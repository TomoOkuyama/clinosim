"""Simulator engine — run_beta, run_forced, run_alpha entry points."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np

from clinosim.locale.loader import load_demographics
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
from clinosim.types.config import ForcedScenario, SimulatorConfig
from clinosim.types.encounter import EncounterType
from clinosim.types.output import CIFDataset, CIFMetadata, CIFPatientRecord
from clinosim.types.patient import PatientProfile

from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.simulator.helpers import (
    _country_to_yaml_key,
    _deactivate_to_layer1,
    _evaluate_readmission,
    _load_all_disease_protocols,
    _select_secondary_disease,
)
from clinosim.simulator.inpatient import _simulate_patient, _simulate_unknown_condition
from clinosim.simulator.outpatient import _simulate_outpatient_visit


# ============================================================
# Main entry point
# ============================================================

def run_beta(
    config: SimulatorConfig | None = None,
    hospital_config_path: str | None = None,
) -> CIFDataset:
    """Run population-driven simulation.

    Args:
        hospital_config_path: Path to hospital operations YAML.
            If None, uses default config/hospital_operations.yaml.
    """
    if config is None:
        config = SimulatorConfig()

    rng = np.random.default_rng(config.random_seed)

    # Load modules
    healthcare = load_healthcare_config(config.country)
    protocols = _load_all_disease_protocols()
    demo = load_demographics(config.country)

    # Hospital operational state (YAML-configurable per hospital)
    from clinosim.modules.facility.hospital_state import HospitalState, load_hospital_operations
    if hospital_config_path:
        import yaml
        from pathlib import Path
        with open(Path(hospital_config_path)) as f:
            hospital_ops = yaml.safe_load(f) or {}
    else:
        hospital_ops = load_hospital_operations()

    # Staff roster scaled to hospital config (ward-aware, dept-aware)
    roster = generate_roster(config.hospital_scale, config.country, rng, hospital_config=hospital_ops)
    hospital_state = HospitalState()

    # Population: use hospital's recommended_population unless overridden by CLI
    pop_size = config.catchment_population
    recommended_raw = hospital_ops.get("recommended_population")
    if recommended_raw:
        if isinstance(recommended_raw, dict):
            # Country-specific: {US: 40000, JP: 5000, default: 40000}
            recommended = recommended_raw.get(config.country) or recommended_raw.get("default", 40000)
        else:
            recommended = int(recommended_raw)
        if config.catchment_population == 10_000:  # CLI default unchanged → use hospital config
            pop_size = recommended
    beds = hospital_ops.get("resource_capacity", {}).get("inpatient_beds", 50)
    print(f"  Hospital: {beds} beds", flush=True)

    population = generate_population(pop_size, config.country, rng)
    print(f"  Population: {population.total_persons} persons")

    # Run life events
    start_y, start_m = int(config.time_range[0][:4]), int(config.time_range[0][5:7])
    end_y, end_m = int(config.time_range[1][:4]), int(config.time_range[1][5:7])

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
        all_events.extend(generate_monthly_events(population, y, m, rng, country=config.country))
        m += 1
        if m > 12:
            m, y = 1, y + 1

    # Filter out events after snapshot date
    if snapshot_dt:
        all_events = [
            e for e in all_events
            if not e.timestamp or datetime.combine(e.timestamp, datetime.min.time()) <= snapshot_dt
        ]

    hospital_events = sorted(
        [e for e in all_events if e.requires_hospital],
        key=lambda e: e.timestamp,  # chronological order
    )
    print(f"  Life events: {len(all_events)} total, {len(hospital_events)} requiring hospital")

    # Simulate each patient in chronological order (DES-aware)
    # Hospital state is shared — concurrent patients affect delays
    patient_records: list[CIFPatientRecord] = []
    concurrent_patients: int = 0
    active_discharges: list[tuple] = []  # (discharge_date, beds_freed)
    beds_total = hospital_ops.get("resource_capacity", {}).get("inpatient_beds", 200)

    n_hosp = len(hospital_events)
    for idx, event in enumerate(hospital_events):
        if (idx + 1) % 50 == 0 or idx == n_hosp - 1:
            print(f"  Simulating inpatient {idx+1}/{n_hosp} "
                  f"(concurrent={concurrent_patients}, "
                  f"bed_occ={hospital_state.bed_occupancy:.0%})...", flush=True)

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

        patient = activate_patient(person, rng, demo)
        disease_id = event.disease_id

        # Unknown condition
        if event.condition_type == "unknown" or disease_id.startswith("unknown_"):
            record = _simulate_unknown_condition(patient, event, rng, healthcare, roster, hospital_ops=hospital_ops)
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
                patient, disease_id, protocols, rng,
            )

        record = _simulate_patient(
            patient, event, disease_id, protocol, healthcare, roster, config, rng,
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

    print(f"  Inpatient done: {len(patient_records)} records "
          f"(peak concurrent: {concurrent_patients})", flush=True)

    # === Readmission evaluation (post-loop pass) ===
    country_key = _country_to_yaml_key(config.country)
    readmission_events: list[LifeEvent] = []
    for record in patient_records:
        if record.deceased or record.is_readmission:
            continue
        person = population.get_person(record.patient.patient_id)
        if not person or not person.is_alive:
            continue
        disease_id = (
            record.condition_event.ground_truth_diseases[0]
            if record.condition_event.ground_truth_diseases else None
        )
        if not disease_id:
            continue
        protocol = protocols.get(disease_id)
        if not protocol:
            continue
        re_event = _evaluate_readmission(
            record, person, disease_id, protocol, country_key, rng,
        )
        if re_event:
            readmission_events.append(re_event)

    # Filter out readmissions past snapshot date
    if snapshot_dt:
        readmission_events = [
            e for e in readmission_events
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
        patient = activate_patient(person, rng, demo)
        record = _simulate_patient(
            patient, re_event, re_event.disease_id, protocol,
            healthcare, roster, config, rng,
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

    # === Outpatient encounters (healthcare calendar for ALL population) ===
    from clinosim.locale.loader import load_chronic_followup
    followup_data = load_chronic_followup()

    # Post-discharge follow-up for inpatient records
    inpatient_records = [
        r for r in patient_records
        if not r.deceased and r.encounters
        and r.encounters[0].encounter_type == EncounterType.INPATIENT
    ]
    post_dc_spec = followup_data.get("_post_discharge", {})
    post_dc_days = post_dc_spec.get("first_visit_days", 14)
    patient_cache: dict[str, PatientProfile] = {}

    for record in inpatient_records:
        pid = record.patient.patient_id
        person = population.get_person(pid)
        if not person or not person.is_alive:
            continue
        enc = record.encounters[0]
        if not enc.discharge_datetime:
            continue
        if pid not in patient_cache:
            patient_cache[pid] = activate_patient(person, rng, demo)
        disease_id = (record.condition_event.ground_truth_diseases[0]
                      if record.condition_event.ground_truth_diseases else "")
        disease_fu = followup_data.get("_post_discharge_by_disease", {}).get(disease_id, {})
        merged_spec = dict(post_dc_spec)
        if disease_fu.get("labs"):
            merged_spec["labs"] = disease_fu["labs"]
        followup_date = enc.discharge_datetime + timedelta(days=post_dc_days)
        # Skip post-discharge visits scheduled after the snapshot date
        if snapshot_dt and followup_date > snapshot_dt:
            continue
        opd_record = _simulate_outpatient_visit(
            patient_cache[pid], "post_discharge", followup_date, roster, rng,
            followup_spec=merged_spec, post_discharge_disease=disease_id,
            country=config.country,
        )
        patient_records.append(opd_record)

    n_post_dc = len(patient_records) - len(inpatient_records) - len(readmission_events)

    # Healthcare calendar: chronic visits + screening for ALL population
    calendar_events = generate_healthcare_calendar(population, start_y, config.country, rng)
    # Filter out events past snapshot date
    if snapshot_dt:
        calendar_events = [
            e for e in calendar_events
            if not e.timestamp or datetime.combine(e.timestamp, datetime.min.time()) <= snapshot_dt
        ]
    print(f"  Healthcare calendar: {len(calendar_events)} events for population", flush=True)

    n_calendar = 0
    for event in calendar_events:
        person = population.get_person(event.person_id)
        if not person or not person.is_alive:
            continue
        if event.person_id not in patient_cache:
            patient_cache[event.person_id] = activate_patient(person, rng, demo)
        patient = patient_cache[event.person_id]

        visit_time = datetime(event.timestamp.year, event.timestamp.month,
                              event.timestamp.day, 10, int(rng.integers(0, 45)))

        if event.event_type == "chronic_visit":
            spec = followup_data.get(event.disease_id, {})
            # Merge optional labs: quarterly (25% each visit) and annual (8% each visit)
            visit_labs = list(spec.get("labs", []))
            for lab in spec.get("labs_quarterly", []):
                if rng.random() < 0.25 and lab not in visit_labs:
                    visit_labs.append(lab)
            for lab in spec.get("labs_annual", []):
                if rng.random() < 0.08 and lab not in visit_labs:
                    visit_labs.append(lab)
            merged_spec = dict(spec)
            merged_spec["labs"] = visit_labs
            opd_record = _simulate_outpatient_visit(
                patient, "chronic_followup", visit_time, roster, rng,
                chronic_code=event.disease_id, followup_spec=merged_spec,
                country=config.country,
            )
        elif event.event_type == "health_screening":
            opd_record = _simulate_outpatient_visit(
                patient, "health_screening", visit_time, roster, rng,
                chronic_code="annual_health_screening",
                followup_spec={"labs": ["WBC", "Hb", "Glucose", "Creatinine", "AST", "ALT"],
                               "visit_reason": "Annual health screening"},
                country=config.country,
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
        (name, spec) for name, spec in all_enc_conditions.items()
        if spec.get("encounter_type") == "emergency"
    ]
    ed_demo = demo.get("ed_visit_not_admitted", {})
    ed_rate = ed_demo.get("rate_per_admitted", 3.0)
    n_ed = int(len(inpatient_records) * ed_rate)
    if ed_conditions and n_ed > 0:
        for _ in range(n_ed):
            # Apply seasonal modifiers to probabilities for this visit's month
            total_months = (end_y - start_y) * 12 + (end_m - start_m) + 1
            month_offset = int(rng.integers(0, total_months))
            visit_month = ((start_m - 1 + month_offset) % 12) + 1

            # Select person first (uniform), then filter conditions by their occupation
            person_id = rng.choice(list(population.persons.keys()))
            person = population.get_person(person_id)
            if not person or not person.is_alive:
                continue
            patient = activate_patient(person, rng, demo)

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
            cond_idx = int(rng.choice(len(ed_conditions), p=ed_probs))
            cond_name, cond = ed_conditions[cond_idx]
            # Use the same month that seasonal modifiers were calculated for
            ed_year = start_y + (start_m - 1 + month_offset) // 12
            ed_day = int(rng.integers(1, 28))
            ed_hour = int(rng.choice([9, 10, 14, 15, 19, 20, 21, 22]))
            ed_time = datetime(ed_year, visit_month, ed_day, ed_hour, int(rng.integers(0, 60)))
            # Skip ED visits past snapshot date
            if snapshot_dt and ed_time > snapshot_dt:
                continue

            ed_record = _simulate_ed_visit(
                patient, cond, ed_time, roster, rng, country=config.country,
            )
            patient_records.append(ed_record)
        print(f"  ED visits (not admitted): {n_ed} generated", flush=True)

    metadata = CIFMetadata(
        clinosim_version="0.1.0",
        random_seed=config.random_seed,
        country=config.country,
        hospital_scale=config.hospital_scale,
        snapshot_date=config.snapshot_date,
        total_patients_generated=len(patient_records),
        llm_mode=config.llm.judgment.mode,
    )
    return CIFDataset(metadata=metadata, patients=patient_records,
                      hospital_roster=list(roster.members),
                      hospital_config=hospital_ops or {})


def run_forced(scenario: ForcedScenario, config: SimulatorConfig | None = None) -> CIFDataset:
    """Generate data for a specific forced scenario only. No population needed.

    Usage:
        from clinosim.types.config import ForcedScenario, SimulatorConfig
        scenario = ForcedScenario(disease_id="bacterial_pneumonia", count=5, archetype="treatment_resistant")
        dataset = run_forced(scenario)
    """
    if config is None:
        config = SimulatorConfig()

    rng = np.random.default_rng(config.random_seed)
    healthcare = load_healthcare_config(config.country)
    roster = generate_roster(config.hospital_scale, config.country, rng)
    _demo = load_demographics(config.country)

    protocol = load_disease_protocol(scenario.disease_id)

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
            person_id=f"FORCED-{i+1:04d}",
            household_id=f"HH-FORCED-{i+1:04d}",
            age=age,
            sex=sex,
            date_of_birth=date(2024 - age, 1, 1),
            family_name="テスト" if config.country == "JP" else "Test",
            given_name=f"患者{i+1}" if config.country == "JP" else f"Patient{i+1}",
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
            patient, event, scenario.disease_id, protocol,
            healthcare, roster, config, rng,
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
    return CIFDataset(metadata=metadata, patients=patient_records,
                      hospital_roster=list(roster.members),
                      hospital_config={})


def run_alpha(config: SimulatorConfig | None = None) -> CIFDataset:
    """Backward-compatible alpha: 1 pneumonia patient via ForcedScenario."""
    scenario = ForcedScenario(
        disease_id="bacterial_pneumonia", count=1,
        severity="moderate", archetype="smooth_recovery",
        patient_overrides={"age": 72, "sex": "F"},
    )
    return run_forced(scenario, config)
