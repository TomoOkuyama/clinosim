# simulator — Main Orchestrator

## Purpose
Coordinate the execution of all modules in the correct order, manage data flow between them, and provide the top-level API for running simulations. Supports two simulation modes: Patient Record Generation (Mode 1) and Hospital Operations Simulation (Mode 2).

## Inputs
- User configuration: mode, number of patients, disease modules to activate, healthcare system selection, hospital scale, random seed, simulation time range
- All module instances

## Outputs
- Mode 1: `PatientRecordSet` — Collection of individually generated patient records
- Mode 2: `HospitalSimulationResult` — Full hospital timeline with concurrent patients, resource utilization, and operational data

## Dependencies
- All modules (orchestrates their execution)

## Confirmed Specifications

### Mode 1: Patient Record Generation pipeline

Population-driven but processes hospital visitors sequentially. Hospital resources assumed available.

```
=== World Setup (once) ===
1. healthcare_system  →  Load country-specific config
2. facility           →  Define hospital structure
3. staff              →  Generate staff roster
4. population         →  Generate catchment area (households + persons, Layer 1)

=== Time Simulation ===
5. population         →  Run life event engine over simulation period
   For each life event that triggers a hospital visit:
   a. patient         →  Activate Layer 1 → Layer 2 (or reactivate returning patient)
   b. encounter       →  Create encounter from CareSeekingDecision
   c. For each encounter:
      i.   encounter       →  Advance workflow state machine
      ii.  diagnosis       →  Update differential / confirm diagnosis
      iii. clinical_course →  Determine state trajectory, select archetype
      iv.  treatment       →  Determine treatment plan
      v.   order           →  Generate orders with timing
      vi.  For each time step within encounter:
           - physiology    →  Update state variables
           - observation   →  Generate labs/vitals per active orders
           - nursing       →  Generate nursing events (vitals, MAR, assessments)
           - procedure     →  Run procedural workflow (if applicable)
           - staff         →  Assign practitioners to each event
           - validator     →  Check consistency
      vii. encounter      →  Evaluate transitions (ward → ICU, discharge, etc.)
   d. patient          →  Deactivate Layer 2 → Layer 1 (update health status)
   e. output           →  Export patient record (FHIR / CSV)
```

### Mode 2: Hospital Operations Simulation pipeline

Population-driven with concurrent patients competing for resources.

```
=== World Setup (once) ===
1. healthcare_system  →  Load country-specific config
2. facility           →  Define hospital structure + initialize resource pools
3. staff              →  Generate staff roster + compute full shift schedules
4. population         →  Generate catchment area (households + persons, Layer 1)

=== Time Simulation (discrete-event) ===
5. population         →  Generate life events as simulation clock advances
   - Patient arrivals trigger encounter creation
   - Encounter workflows request resources (beds, OR, staff)
   - Resource contention introduces waits/queues
   - Order processing respects real-time lab/imaging capacity
   - Nursing workload affects vital sign timing accuracy
   - Staff shift changes trigger handoff events
   - Concurrent patient interactions (e.g., shared nurse delays)
6. output             →  Export all patient records + operational data
```

### Top-level API (target)

```python
from clinosim import Simulator
from clinosim.systems import JapanHealthcareSystem
from clinosim.diseases import BacterialPneumonia

# Mode 1: Patient Record Generation
sim = Simulator(
    mode="patient_record",
    healthcare_system=JapanHealthcareSystem(),
    hospital_scale="medium",
    disease_modules=[BacterialPneumonia()],
    catchment_population=50_000,
    random_seed=42,
    time_range=("2024-04-01", "2025-03-31"),
)
result = sim.run()
result.export_fhir(output_dir="./output/fhir/")

# Mode 2: Hospital Operations Simulation
sim = Simulator(
    mode="hospital_ops",
    healthcare_system=JapanHealthcareSystem(),
    hospital_scale="medium",
    disease_modules=[BacterialPneumonia()],
    random_seed=42,
    time_range=("2024-04-01", "2025-03-31"),
)
result = sim.run()
result.export_fhir(output_dir="./output/fhir/")
result.export_operational_report(output_dir="./output/ops/")
```

---

## Internal Design

### Mode 1 main loop

```python
class Simulator:
    def __init__(self, config: SimulatorConfig):
        # Seed management — deterministic sub-seeds for each module
        self.seed_manager = SeedManager(config.random_seed)
        
        # Initialize foundation modules (each receives its own sub-seed)
        self.healthcare = HealthcareSystemModule(config.country)
        self.facility = FacilityModule(self.healthcare, config.hospital_scale,
                                        seed=self.seed_manager.get_module_seed("facility"))
        self.staff_module = StaffModule(self.facility, self.healthcare, config.time_range,
                                         seed=self.seed_manager.get_module_seed("staff"))
        self.population_module = PopulationModule(self.healthcare, self.facility, config,
                                                    seed=self.seed_manager.get_module_seed("population"))
        self.disease_module = DiseaseModule(self.healthcare,
                                             seed=self.seed_manager.get_module_seed("disease"))
        self.llm = LLMService(config.llm_config)  # LLM: non-deterministic, uses cache for reproducibility
        self.output = OutputService()
        
        # Clinical modules (stateless — instantiated per use)
        self.patient_module = PatientModule(self.healthcare)
        self.encounter_module = EncounterModule(self.healthcare, self.facility)
        self.diagnosis_module = DiagnosisModule(self.disease_module, self.llm)
        self.treatment_module = TreatmentModule(self.disease_module, self.healthcare, self.llm)
        self.clinical_course_module = ClinicalCourseModule(self.disease_module)
        self.physiology_module = PhysiologyModule()
        self.order_module = OrderModule(self.facility, self.healthcare)
        self.nursing_module = NursingModule(self.physiology_module, self.llm)
        self.procedure_module = ProcedureModule(self.physiology_module)
        self.validator_module = ValidatorModule(self.llm)
    
    def run(self) -> SimulationResult:
        records = []
        
        # Generate population
        population = self.population_module.generate()
        
        # Run life event engine month by month
        for month in self.config.month_range():
            events = self.population_module.advance_month(population, month)
            
            for event in events:
                if event.care_seeking_decision and event.care_seeking_decision.decision != "no_action":
                    record = self._simulate_hospital_visit(event, population)
                    if record:
                        records.append(record)
            
            # Progress reporting
            self._report_progress(month, len(records))
        
        # Export
        result = SimulationResult(records=records, population=population)
        return result
    
    def _simulate_hospital_visit(self, event: LifeEvent, population) -> PatientRecord | None:
        person = population.get_person(event.person_id)
        household = population.get_household(person.household_id)
        
        # Layer 1 → Layer 2 activation
        patient = self.patient_module.activate(person, household, event)
        
        # Initialize physiological state
        state = self.physiology_module.initialize_state(
            patient.physiological_profile, patient.chronic_conditions, patient.pregnancy_state
        )
        
        # Apply disease initial impact
        disease_event = self.disease_module.create_event(patient, event)
        state = self.physiology_module.apply_disease_onset(state, disease_event)
        
        # Create encounter sequence
        encounters = self.encounter_module.create_encounter_chain(
            patient, disease_event, event.care_seeking_decision
        )
        
        all_events = []
        all_orders = []
        diagnoses = []
        state_history = [state]
        
        for encounter in encounters:
            # Initialize differential
            differential = self.diagnosis_module.initialize_differential(
                patient, disease_event, event.care_seeking_decision.referral_context
            )
            
            # Run encounter workflow
            time_step = encounter.time_resolution
            
            if time_step is None:
                # Snapshot encounter (outpatient, checkup)
                snapshot_events = self._run_snapshot_encounter(encounter, patient, state, differential)
                all_events.extend(snapshot_events)
            else:
                # Time-stepping encounter (inpatient, ED, ICU)
                enc_events, enc_orders = self._run_timed_encounter(
                    encounter, patient, state, disease_event, differential, state_history
                )
                all_events.extend(enc_events)
                all_orders.extend(enc_orders)
            
            diagnoses.append(differential)
        
        # Validate
        record = PatientRecord(
            patient=patient,
            encounters=encounters,
            events=sorted(all_events, key=lambda e: e.timestamp),
            orders=all_orders,
            staff_assignments=[a for e in all_events for a in e.staff_assignments],
            differential_diagnoses=diagnoses,
            physiological_states=state_history,
        )
        
        issues = self.validator_module.validate_pass1(record)
        if issues:
            record = self.validator_module.correct_issues(record, issues)
        
        # Optional LLM consistency review
        if self.llm.mode == "llm":
            review = self.validator_module.validate_pass2(record, issues)
            if review and review.issues:
                for issue in review.issues:
                    if issue.severity == "critical":
                        record = self.validator_module.correct_issues(record, [issue])
        
        # Deactivate patient (Layer 2 → Layer 1)
        self.patient_module.deactivate(patient, population)
        
        return record
    
    def _run_timed_encounter(self, encounter, patient, state, disease_event, 
                              differential, state_history):
        """Core simulation loop for time-stepping encounters."""
        events = []
        orders = []
        
        # Admission
        admission_events, admission_orders = self.encounter_module.process_admission(
            encounter, patient, state, disease_event, differential,
            self.diagnosis_module, self.order_module, self.nursing_module, self.staff_module
        )
        events.extend(admission_events)
        orders.extend(admission_orders)
        
        # Time-stepping loop
        current_time = encounter.admission_datetime + encounter.time_resolution
        
        while encounter.status == EncounterStatus.IN_PROGRESS:
            # Clinical course: compute state changes
            archetype = disease_event.course_archetype
            directive = self.clinical_course_module.evaluate(
                patient, state, archetype, differential, 
                self.treatment_module.get_active_plan(orders)
            )
            
            # Update physiology
            self.physiology_module.update(state, directive, encounter.time_resolution)
            state_history.append(copy(state))
            
            # Process scheduled events at this time
            step_events, step_orders = self.encounter_module.process_time_step(
                encounter, patient, state, current_time,
                self.diagnosis_module, self.treatment_module, self.order_module,
                self.nursing_module, self.procedure_module, self.staff_module,
                self.physiology_module, state_history
            )
            events.extend(step_events)
            orders.extend(step_orders)
            
            # Check transitions
            self.encounter_module.evaluate_transitions(encounter, patient, state)
            
            current_time += encounter.time_resolution
        
        return events, orders
```

### Top-level API (updated)

```python
from clinosim import Simulator, CIFWriter, NarrativeGenerator, OutputService, LLMService

# === Stage 1: Run simulation → structural CIF (once, no LLM) ===
sim = Simulator(SimulatorConfig.preset("japan_medium").override({
    "disease_modules": ["bacterial_pneumonia"],
    "random_seed": 42,
    "time_range": ("2024-04-01", "2025-03-31"),
}))
result = sim.run()

cif_writer = CIFWriter("./output/cif/", format="json")
cif_writer.write(result)
# Structural CIF on disk. Simulation can be discarded from memory.
# JUDGMENT LLM calls (diagnostic reasoning, treatment decisions) occurred during simulation.
# Their results are baked into structural data (diagnosis codes, drug selections, etc.)
# JUDGMENT costs: ~10,600 tokens/patient (English, small output).
# Deterministic with same seed + same JUDGMENT LLM + same cache.

# === Stage 2: Generate narratives (can be re-run with different LLMs) ===

# First attempt: fast and cheap (Haiku)
llm_fast = LLMService(LLMServiceConfig(mode="llm", provider="bedrock_gateway",
                                         model_map={"small": "haiku", "medium": "haiku", "large": "sonnet"}))
narrator = NarrativeGenerator(llm_fast)
narrator.generate("./output/cif/")
# -> narratives/haiku_20240601_120000/ created, set as "current"

# Review the narratives... quality not sufficient for H&P and discharge summaries?
# Re-generate with higher quality model. Structural data untouched.
llm_quality = LLMService(LLMServiceConfig(mode="llm", provider="bedrock_gateway",
                                            model_map={"small": "haiku", "medium": "sonnet", "large": "opus"}))
narrator2 = NarrativeGenerator(llm_quality)
narrator2.generate("./output/cif/")
# -> narratives/opus_20240601_140000/ created, set as "current"
# Previous haiku version still preserved for comparison

# === Stage 3: Convert to target formats (from CIF structural + current narratives) ===
output = OutputService()
jp_config = load_healthcare_config("JP")
output.convert("./output/cif/", ["fhir_r4", "csv"], "./output/", jp_config)

# Want to convert with a different narrative version?
output.convert("./output/cif/", ["fhir_r4"], "./output_haiku/", jp_config,
               narrative_version="haiku_20240601_120000")

# Want US coding from the same structural data?
us_config = load_healthcare_config("US")
output.convert("./output/cif/", ["fhir_r4"], "./output_us/", us_config)
```

## Open Questions
- [ ] Number of patients / time period scale targets (global open #8)
- [ ] Parallelization strategy: multiprocessing per patient (Mode 1), or SimPy (Mode 2)
- [ ] Progress reporting / logging level configuration
- [ ] Mode 2 discrete-event simulation framework selection

## Design Notes
- Mode 1 is the implementation priority; Mode 2 is designed for but built later
- The module interfaces are the same in both modes; Mode 2 adds resource-management middleware
- The simulator is the only place where modules are wired together — it acts as the dependency injection container
- Each patient visit is fully independent in Mode 1, enabling trivial parallelization
