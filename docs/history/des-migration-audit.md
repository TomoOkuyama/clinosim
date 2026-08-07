# DES Migration — Pre-Migration Audit

> **Status (historical planning document):** The pre-migration cleanup described
> below is largely complete. `simulator.py` has been split into
> `simulator/{engine,inpatient,outpatient,emergency,helpers,cli}.py`, and a
> discrete-event engine now exists at `simulator/des_engine.py`. Counts in this
> document predate later growth — the project now ships **32 disease YAMLs** and
> **46 encounter YAMLs** (not the 20/24 referenced below). Retained for design
> rationale; see `DESIGN.md` and `TODO.md` for current state.

## 1. Current Architecture Issues

### simulator.py is a monolith (2,686 lines, 30+ functions)
Must be split before DES migration:
- `run_beta()` + event processing → `simulator/engine.py`
- `_simulate_patient()` + daily loop → `simulator/inpatient.py`
- `_simulate_outpatient_visit()` → `simulator/outpatient.py`
- `_simulate_ed_visit()` → `simulator/emergency.py`
- Helper functions → `simulator/utils.py`
- CLI → `cli.py` (separate from simulation logic)

### Redundant delay logic
Three delay calculation functions in `order/engine.py`:
1. `calculate_lab_result_time()` — legacy, hardcoded delays
2. `calculate_imaging_result_time()` — legacy, hardcoded delays
3. `calculate_result_time_from_state()` — HospitalState version

**Action**: Remove (1) and (2) after DES. In DES, all delays come from HospitalState.

### Empty modules
- `nursing/` — only SPEC.md, no engine. Nursing logic is in simulator.py.
- `treatment/` — only SPEC.md, no engine. Treatment logic is in simulator.py.

**Action**: Either implement or remove these empty module shells.

## 2. YAML Data Issues

### ED conditions: dual registration required
Currently, ED conditions must be registered in TWO places:
1. `encounter/reference_data/*.yaml` — clinical protocol
2. `demographics.yaml` → `ed_visit_not_admitted.conditions` — probability/frequency

13 outpatient encounter YAMLs exist but are NOT in demographics.yaml.
They only fire through `generate_healthcare_calendar()`, not through demographics ED rates.

**Action in DES**: Single source — encounter YAML should include frequency data.
Demographics.yaml `ed_visit_not_admitted` section becomes redundant.

### Chronic follow-up: split across two files
- `locale/shared/chronic_followup.yaml` — visit schedule + reasons
- `locale/shared/chronic_medications.yaml` — home meds + monitoring

These define the same thing (chronic disease management) but are separate.

**Action**: Consider merging, or at minimum ensure consistent condition_id keys.

### Hospital operations config
`config/hospital_operations.yaml` defines capacity and staffing.
BUT `order/engine.py` also has hardcoded delays that partially overlap.

**Action in DES**: hospital_operations.yaml is the SOLE source for all operational parameters.

## 3. Module Impact Analysis for DES

### Must change
| Module | Current Role | DES Role |
|---|---|---|
| **simulator.py** | Monolith orchestrator | Split into DES engine + encounter simulators |
| **order/engine.py** | Order placement + delay calc | Order placement only; delays from HospitalState |
| **facility/hospital_state.py** | Passive state tracking | **Core DES component**: shared resource manager |
| **population/engine.py** | Event generation | Generates initial events for DES queue |

### Minor changes
| Module | Change |
|---|---|
| **physiology/engine.py** | No change (state update stays per-patient) |
| **clinical_course/engine.py** | No change (archetype trajectories stay) |
| **diagnosis/engine.py** | No change (Bayesian update stays) |
| **observation/engine.py** | No change (lab variability stays) |
| **patient/activator.py** | No change (Layer 1→2 stays) |

### No change
| Module | Reason |
|---|---|
| **disease/protocol.py** | YAML loading, unchanged |
| **encounter/protocol.py** | YAML loading, unchanged |
| **output/** (cif, csv, fhir) | Consumes CIFPatientRecord, unchanged |
| **staff/engine.py** | Roster generation, unchanged |
| **locale/** | Data files, unchanged |

## 4. Data Flow: Current → DES

### Current
```
Population → monthly events → for each patient: simulate_entire_stay()
                                → independent daily loop
                                → independent lab/vital/MAR generation
                             → add outpatient events (post-hoc)
                             → add ED events (post-hoc)
```

### DES
```
Population → generate ALL events (acute + chronic + screening + ED)
          → sort by timestamp
          → EventQueue
          → while queue not empty:
              event = queue.pop_earliest()
              hospital.advance_time(event.time)
              new_events = process(event, hospital_state)
              queue.push(new_events)
          → collect records per patient
```

## 5. Pre-Migration Cleanup Tasks

- [ ] Split simulator.py into modules
- [ ] Remove legacy delay functions (after DES replaces them)
- [ ] Merge ED condition registration (eliminate demographics.yaml duplication)
- [ ] Remove empty nursing/ and treatment/ modules (or implement)
- [ ] Verify all 20 disease YAMLs load without errors
- [ ] Verify all 24 encounter YAMLs load without errors
- [ ] Ensure all tests pass with current code
- [ ] Document the SimEvent interface for DES
