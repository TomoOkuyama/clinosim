# clinosim — TODO

## Open Design Questions

### High Priority

| # | Question | Relevant Module | Status |
|---|---|---|---|
| 1 | State variable granularity: organ-level or finer? | physiology | **Partially resolved**: organ-level works for Phase 1. May need subdivision for Phase 2 (AMI, sepsis) |
| 2 | Time step granularity: 1h standard, 15min for ICU? | physiology | **Resolved: variable per encounter type** (checkup/outpatient: snapshot, inpatient: 1h, ER: 30min, ICU: 15min, rehab: 1day) |
| 3 | Treatment effect model: binary or continuous curve? | clinical_course, treatment | **Resolved: continuous** (disease YAML defines daily state deltas, modulated by treatment_sensitivity) |
| 4 | Diagnostic confirmation threshold (per-disease?) | diagnosis | **Resolved**: 90% default, defined per disease YAML (`confirmation_threshold`). Pneumonia: 90%. |
| 5 | Age/comorbidity correlation with individual-difference params | patient | Open (v0.1-beta) |
| 6 | Hospital scale category definitions and department composition tables | facility | **Resolved**: Detailed tables in facility SPEC.md (JP small/medium/large, US medium/large). v0.1-alpha uses hardcoded medium. |
| 7 | Staff assignment model: detailed shift/on-call scheduling | staff | Open (v0.1-beta: placeholder IDs in alpha) |
| 8 | Encounter type detail level: full workflow or simplified for Mode 1? | encounter | **Resolved**: v0.1-alpha: linear inpatient only. v0.1-beta: full state machine. Both use same Encounter type. |

### Medium Priority

| # | Question | Relevant Module | Status |
|---|---|---|---|
| 9 | Patient count / time period scale targets | simulator | Open |
| 10 | Output format priority: FHIR-first or CSV-first? | output | **Resolved**: CIF first (AD-17). FHIR R4 + CSV adapters in v0.1-beta. |
| 11 | Outcome model details (death, transfer, home) | clinical_course | Open |
| 12 | Diagnostic evolution reflection in narrative records | diagnosis, output | Open |
| 13 | Likelihood ratio database construction method | diagnosis, disease | Open |
| 14 | Staff lifecycle rates and patterns per country | staff | Open |
| 15 | Name generation strategy (culturally appropriate) | staff, patient | Open |
| 16 | Order timing distributions per country/hospital scale | order | Open |
| 17 | Nursing documentation: structured data only or narrative text? | nursing | Open |
| 18 | Encounter numbering/linking strategy (episode-of-care) | encounter | Open |

### Low Priority (Phase 2+)

| # | Question | Relevant Module | Status |
|---|---|---|---|
| 19 | Medical cost / claims data generation (DPC/DRG codes) | healthcare_system, output | Open |
| 20 | End-of-life model (DNR/DNAR, terminal care process) | clinical_course | Open |
| 21 | Phase 2 disease priority order | disease | Open |
| 22 | Chronic disease long-term timeline + acute admission integration | disease, clinical_course | Open |
| 23 | Teaching hospital resident rotation model | staff, facility | Open |
| 24 | Outpatient clinic / ER modeling detail level | facility, encounter | Open |
| 25 | Mode 2 discrete-event simulation framework selection (SimPy vs. custom) | simulator | Open |
| 26 | Mode 2 operational report format | output | Open |
| 27 | Anesthesia record detail level | procedure | Open |
| 28 | Nursing diagnosis system (NANDA-I) inclusion | nursing | Open |
| 29 | Equipment throughput parameters: real-world validation per hospital scale | facility | Open |
| 30 | Seasonal incidence modifier curves per disease per country | disease | Open |
| 31 | Screening program participation rates by demographic | healthcare_system, patient | Open |
| 32 | Diurnal variation coefficients per lab analyte | observation | Open |
| 33 | Holiday calendar data sources per country | healthcare_system, facility | Open |

## Architecture Decisions

| Decision | Date | Description |
|---|---|---|
| AD-1 | 2026-04-04 | Two simulation modes: Mode 1 (Patient Record) and Mode 2 (Hospital Operations). Mode 2 is a superset. Design for Mode 2, implement Mode 1 first. |
| AD-2 | 2026-04-04 | Modular folder structure: each module is a self-contained folder with SPEC.md. |
| AD-3 | 2026-04-04 | Population-driven forward simulation: generate catchment population first, simulate life events, hospital visits are consequences of population dynamics. |
| AD-4 | 2026-04-04 | Two-layer population model: Layer 1 (lightweight registry for all persons) and Layer 2 (detailed clinical profile, activated only on hospital visit). |
| AD-5 | 2026-04-04 | Household-based generation: people belong to households, enabling realistic family history, infection transmission, and shared attributes. |
| AD-6 | 2026-04-04 | Referring clinics as context (not simulation targets): generate referral letters and prior records without full GP simulation. |
| AD-7 | 2026-04-04 | LLM as selective amplifier: enhances narratives and clinical reasoning; all numerical/structural data remains rule-based. |
| AD-8 | 2026-04-04 | Three generation modes: `none` (structured only), `template` (rule-based text), `llm` (full LLM enhancement). System fully functional without LLM. |
| AD-9 | 2026-04-04 | Compact context pattern: pre-summarized `LLMClinicalContext` (~300 tokens) instead of full patient record for each LLM call. |
| AD-10 | 2026-04-04 | Batch + cache strategy: LLM called at key narrative points only (4–11 calls per patient), with pattern caching for common scenarios. |
| AD-11 | 2026-04-04 | All LLM calls go through `llm_service` module. No other module may call LLM directly. |
| AD-12 | 2026-04-04 | Primary LLM provider: EC2 Bedrock Gateway → AWS Bedrock (Claude). Provider abstraction enables future addition of other LLM providers. |
| AD-13 | 2026-04-04 | Two LLM task categories: JUDGMENT (always English) and NARRATIVE (target country language). English judgment = better quality + fewer tokens. |
| AD-14 | 2026-04-04 | Three-tier validation: Tier 1 statistical benchmarks (automated), Tier 2 clinical pattern validation (automated+expert), Tier 3 domain expert blind test (human). |
| AD-15 | 2026-04-04 | Output as pluggable adapter system: each format (FHIR R4, CSV, HL7v2, etc.) is a separate adapter implementing OutputAdapter interface. |
| AD-16 | 2026-04-04 | Reproducibility via hierarchical seed management. Each module gets deterministic sub-seed. LLM outputs cached to disk for reproducible runs. |
| AD-17 | 2026-04-04 | Three-stage output: (1) Sim + JUDGMENT LLM → CIF structural (immutable, ~10.6K tokens/patient) → (2) CIF + NARRATIVE LLM → narrative layer (replaceable, ~30K tokens/patient) → (3) structural + narrative → format adapters. |
| AD-18 | 2026-04-04 | Pydantic for YAML configs (schema validation at load). @dataclass for runtime types. |
| AD-19 | 2026-04-04 | Preset + override config: `SimulatorConfig.preset("japan_medium").override({...})` |
| AD-20 | 2026-04-04 | LLM graceful degradation: retry → template fallback → structured-only. Never halt. |
| AD-21 | 2026-04-04 | Vertical slice: v0.1-alpha (1 patient) → v0.1-beta (population) → v0.1 (full). |
| AD-22 | 2026-04-04 | Three-level testing: unit (<30s) → integration (<5min) → e2e golden file (<30min). |
| AD-23 | 2026-04-04 | Async LLM at patient level. Bounded concurrency. Sync fallback available. |
| AD-24 | 2026-04-04 | JUDGMENT and NARRATIVE use independently configurable LLM providers/models. Local + cloud mix supported. |
| AD-25 | 2026-04-04 | CIF is language-neutral. Person names are country-specific at generation time. All other localization at output/Stage 2. |
| AD-26 | 2026-04-04 | Clinical terminology uses official master data only (JLAC10, LOINC, etc.). Never LLM-translated. |
| AD-27 | 2026-04-04 | All locale data (names, terminology, code mapping, formatting) centralized in `src/clinosim/locale/`. Adding a country = adding YAML files. |

## Implementation Roadmap

### Implementation strategy: Vertical Slice

Build the thinnest possible end-to-end path first, then widen.

```
v0.1-alpha: 1 patient, 1 disease, happy path, no LLM, no population
v0.1-beta:  Population-driven, multiple archetypes, LLM template mode
v0.1:       Full v0.1 with LLM, validation, CIF export
```

### v0.1-alpha — "Hello World" (1 patient end-to-end)

Goal: Generate one pneumonia patient's 14-day inpatient record and write CIF.
Skip: population, staff personas, LLM, complex archetypes.

| # | Task | Module | Details |
|---|---|---|---|
| 1 | JP healthcare config (hardcoded defaults) | `healthcare_system` | Load japan.yaml with essential params only |
| 2 | Medium hospital (hardcoded template) | `facility` | Load japan_medium.yaml, no randomization |
| 3 | Test patient (hardcoded, no population) | `patient` | Directly create one PatientProfile: 72F, HT+DM, pneumonia |
| 4 | Pneumonia protocol (YAML) | `disease` | Load bacterial_pneumonia.yaml, smooth_recovery archetype only |
| 5 | Physiology engine (core 9 variables) | `physiology` | initialize_state + update + derive_lab_values + derive_vital_signs |
| 6 | Inpatient encounter (linear workflow) | `encounter` | Admission → daily cycle × 14 → discharge. No branching. |
| 7 | Lab/med orders (from protocol YAML) | `order` | place_from_protocol + timing. Lab collection triggers observation. |
| 8 | Observation (Layer 3 noise) | `observation` | apply_realistic_variability on physiology-derived values |
| 9 | Nursing (vitals + MAR only) | `nursing` | Vital sign events + medication administration records |
| 10 | Validator (Pass 1 only) | `validator` | Rate-of-change + mutual exclusion checks |
| 11 | CIF Writer (JSON) | `output` | Write CIFPatientRecord to JSON |
| 12 | Simulator loop (single patient) | `simulator` | Wire modules, run 1 patient, write CIF |

**Skip in alpha**: population, staff (use placeholder IDs), LLM, diagnosis (fix working dx), treatment changes, procedure, multiple archetypes, CIF→FHIR/CSV adapters.

**Success criteria**: CIF JSON contains a complete 14-day pneumonia record with ~50 lab results, ~80 vital signs, medication orders, and timestamps that pass validator Pass 1.

### v0.1-beta — Population + archetypes + template mode

| # | Task | Module |
|---|---|---|
| 1 | Population generation (households, Layer 1) | `population` |
| 2 | Life event engine (monthly loop, disease onset) | `population` |
| 3 | Care-seeking decision model | `population` |
| 4 | Layer 1→2 activation / deactivation | `patient` |
| 5 | Staff roster + assignment | `staff` |
| 6 | All 6 archetypes (not just smooth_recovery) | `disease`, `clinical_course` |
| 7 | Treatment selection + change logic | `treatment` |
| 8 | Bayesian differential diagnosis (basic) | `diagnosis` |
| 9 | LLM service — template mode only | `llm_service` |
| 10 | Diet orders, infection control | `order`, `nursing` |
| 11 | CIF → FHIR R4 adapter | `output` |
| 12 | CIF → CSV adapter | `output` |
| 13 | Statistical benchmarks (Tier 1) | `validator` |
| 14 | Multiple patients (10–100) | `simulator` |

### v0.1 — Full foundation release

| # | Task | Module |
|---|---|---|
| 1 | LLM mode (Bedrock Gateway) | `llm_service` |
| 2 | LLM narrative generation (H&P, progress notes, discharge summary) | `llm_service` |
| 3 | LLM judgment (diagnostic reasoning, treatment rationale) | `llm_service` |
| 4 | Consent records | `encounter` |
| 5 | Prescription model (JP 院外処方) | `treatment` |
| 6 | Documentation noise (delayed entry, templates) | `nursing` |
| 7 | Device auto-recording (ICU monitors, POCT) | `observation`, `nursing` |
| 8 | 3-layer variability model (CVi + pre-analytical + CVa) | `observation` |
| 9 | Health checkup encounters | `encounter`, `population` |
| 10 | Outpatient chronic disease management | `encounter`, `population` |
| 11 | Validator Pass 2 (LLM consistency review) | `validator` |
| 12 | Reproducibility (seed management, LLM cache) | `simulator` |
| 13 | Configuration preset + override API | `simulator` |
| 14 | Full validation report (Tier 1 + Tier 2) | `validator` |
| 15 | Scale: 100–1,000 patients | `simulator` |

### v0.2 — Core expansion

- [ ] Heart failure exacerbation + hip fracture disease modules
- [ ] Surgical/procedural workflow (`procedure`)
- [ ] Rehabilitation (FIM, PT/OT/ST sessions)
- [ ] ED + day surgery encounter workflows
- [ ] US healthcare system
- [ ] Staff lifecycle (hiring, retirement, rotation)
- [ ] Encounter workflow YAML-ization (AD for v0.2)
- [ ] Pregnancy/delivery/NICU encounters
- [ ] Multi-department outpatient patterns

### v0.3 — Diagnostic reasoning + realism

- [ ] Advanced Bayesian diagnosis (therapeutic trials, diagnostic drift)
- [ ] Complication cascade
- [ ] Context-dependent missingness
- [ ] Explainable anomaly patterns
- [ ] 30-day readmission model
- [ ] Consultation workflow
- [ ] Pediatric disease modules

### v0.4 — Scale + polish

- [ ] Small/large hospital templates
- [ ] Mental health encounters (psychiatric admission)
- [ ] End-of-life / palliative care pathway
- [ ] CIF → HL7v2, SQL adapters
- [ ] Tier 3 expert blind test
- [ ] Performance optimization (async LLM, parallel patients)

### v1.0 — Hospital Operations (Mode 2)

- [ ] Discrete-event simulation engine
- [ ] Resource contention (bed, OR, staff workload)
- [ ] Concurrent patient interactions
- [ ] Operational report generation

### Future design improvements (tracked, not scheduled)

| # | Item | Priority | Notes |
|---|---|---|---|
| F-1 | encounter YAML-ization (workflow as data) | Medium | v0.2: currently hardcoded state machines |
| F-2 | clinical_course absorption into physiology | Medium | Evaluate after v0.1: may be natural thin adapter |
| F-3 | DI/Registry pattern for module wiring | Low | Hand-wiring is fine until module count becomes unmanageable |
