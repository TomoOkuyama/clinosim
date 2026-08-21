# Data Generation Walkthrough — "how a patient record is born"

**Status:** Active (2026-07-06, established in session 38).
**Audience:** developers and implementation agents new to clinosim.
Traces **how the project assembles one patient record** end-to-end
with actual file names, function names, and data structures.
**Reading order:** `README.md` (index) →
`project-concept-and-design.md` (concept) → **this document** →
`implementation-rules.md` (invariants). Detailed HOW-TO lives in
`../CONTRIBUTING-modules.md`.

> In one sentence: **build a population → fire hospital-visit events
> from that population → simulate physiology, labs, procedures, and
> documents daily per visit into the intermediate representation
> CIF → build FHIR from CIF.**
> Every random draw is seed-derived and deterministic (same seed =
> identical output).

---

## 0. Three-stage CLI = three artefacts

Data generation splits into three independent CLI stages (AD-37).
Each stage reads only the previous stage's artefact.

```
clinosim simulate      →  CIF (structural)   cif/structural/patients/<enc>.json
        ↓                                    + cif/hospital.json / metadata.json
clinosim narrate       →  CIF (narrative)    cif/narratives/<version>/documents/<enc>/<doc>.json
        ↓
clinosim export-fhir   →  FHIR R4 NDJSON     fhir_r4/<ResourceType>.ndjson + manifest.json
```

- **Why three stages**: to make the narrative (natural-language
  interviews and progress notes) **swappable after the fact**. You
  can build narratives with the template first, later regenerate
  with `narrate --provider bedrock`, then rebuild FHIR with
  `export-fhir --narrative-version <id>` — each step runs
  independently (requirement 6).
- **CIF is the sole simulation output** (AD-17). FHIR / CSV adapters
  read only from CIF and never touch simulation internals.
- Other subcommands: `test-disease <id>` (single-disease debug
  generation with printed output) / `test-encounter` / `audit run`
  (4-axis verification) / `validate` / `regenerate-goldens` /
  `check-narratives` / `list-diseases`.
- `clinosim generate` remains as a deprecated alias for
  `clinosim simulate`.

---

## 1. Stage 1 = `simulate`: population → events → encounter simulation → CIF

Entry point: `clinosim/simulator/engine.py:run_beta()`. It advances
through the following steps.

### 1a. Population generation (Layer 1) — `modules/population`

`generate_population(size, country, rng)` (`population/engine.py`)
builds the **catchment area's residents** in household units. Each
`PersonRecord` (`types/population.py`) is lightweight: age, sex,
address, **chronic conditions (a list of ICD codes)**, BMI,
smoking / alcohol, care-seeking thresholds. The epidemiological data
(age distribution, chronic-condition prevalence, disease incidence
rate) is read from `locale/<country>/demographics.yaml` (no
epidemiology values hard-coded in code).

### 1b. Life-event firing — `generate_monthly_events`

`run_beta` cycles the `time_range` (default 1 year) through a
**year × month loop**, calling
`generate_monthly_events(registry, year, month, rng, country)`
each month. For each resident, it evaluates disease incidence (rate
× age × seasonality × lifestyle risk) and decides disease onset via
`rng.random() < rate`. On onset:

- **Severity** is decided by
  `disease.severity.sample_severity(load_disease_protocol(disease_id), person, rng)`
  (AD-67). The disease YAML's `severity.distribution × modifiers`
  (adjusted for age and comorbidity) yields a category and a
  continuous score. ← **The single source of severity is the
  disease YAML** (the old `severity_beta` has been removed).
- **Whether hospitalisation is required** is decided from the
  continuous score and the care-seeking threshold
  (`severity > care_seeking_threshold`).
- Emits a `LifeEvent` (`person_id` / `disease_id` / `timestamp` /
  `severity` / `requires_hospital`).

"Patients are born from the population" — every patient starts as a
resident and becomes a hospital encounter only when an event
crosses the threshold. This is what keeps epidemiology correctly
scaled at the population level.

### 1c. Patient hydration — `modules/patient`

Residents whose hospitalisation / visit fires are thickened by
`activate_patient(person, rng, demo)`
(`patient/activator.py`) from Layer 1 into Layer 2 `PatientProfile`:
height / weight, **chronic-condition staging** (`_generate_stage`:
CKD G3a, NYHA II, hypertension stage 2, …), **stage-derived
physiology parameters** (`STAGE_SEVERITY` maps stage → severity_score,
which drives baseline vitals and physiology — e.g. hypertension
stage 2 → high baseline blood pressure, FP-I10), routine
medications, allergies, baseline vitals.

### 1d. Encounter simulation (daily loop) — `simulator/inpatient.py` and siblings

Dispatch by visit type:
- **Inpatient**: `inpatient.py:_simulate_patient()` →
  `_run_daily_loop()`.
- **ED**: `emergency.py`. **Outpatient**: `outpatient.py`.

The inpatient daily loop is the heart of the data. Roughly:

1. **Severity → course selection**: `event.severity` (continuous
   score) becomes mild / moderate / severe via `category_from_score`.
   `select_archetype(severity, profile, rng, protocol_archetypes=…,
   protocol_modifiers=…, patient=…)`
   (`clinical_course/engine.py`) draws **that patient's course
   archetype** (smooth_recovery / dip_then_recovery / … /
   sudden_deterioration) from the disease YAML's `course_archetypes`
   (probabilities over the 6 canonical archetypes + adjustments
   from `archetype_modifiers` based on patient risk factors,
   AD-68).
2. **Initial physiological state**: `apply_disease_onset(state,
   severity, protocol.initial_state_impact, …)` reflects the
   disease onset into the physiology state
   (`inflammation_level` / `volume_status` / `perfusion_status` /
   `renal_function` / `cardiac_function` / …).
3. **Advance state daily**: `get_daily_directive(archetype, day, …)`
   interpolates the archetype's `trajectory` (per-state-variable
   daily deltas) and updates the state.
4. **Complications**: `evaluate_complications(day, state, patient,
   protocol.complications, …, severity=…)` evaluates the disease
   YAML's `complications` (incidence, risk factors, state_impact,
   actions). A complication whose `actions` include
   `["icu_transfer"]` fires and triggers ICU transfer.
5. **Orders / labs / vitals / meds**: physiology state drives
   `derive_lab_values` (30+ analytes) for lab values, vitals, and
   `place_admission_orders` / `place_daily_lab_orders`
   (panel-aware) / imaging (`place_imaging_orders`) / MAR
   generation.
6. **Discharge / death**: decided by LOS (disease YAML
   `target_los`) and `outcome_benchmarks` (mortality). Past `--end`
   (snapshot) is treated as in-progress (AD-32).

Result: 1 patient = 1 `CIFPatientRecord`. **Scenario / severity /
course / complications / labs are all disease-YAML driven** — the
engine code hard-codes no clinical values.

### 1e. Enrichers (module extensions) — `simulator/enrichers.py`

Around the Base encounter simulation, **opt-in / always-on
modules** run in three stages:

- **POST_POPULATION** (after population generation, before
  simulation): e.g. `identity` (JP My Number / insurance).
- **POST_ENCOUNTER** (right after one visit's daily loop, inside
  the encounter simulator): the clinical cascade. Order is fixed:
  `device(70) → hai(80) → antibiotic(85) → imaging(90) →
  triage(93) → nursing_assignment(94) → document(95)`. Later
  stages read `extensions[X]` written by earlier ones (no HAI
  without a device, etc.).
- **POST_RECORDS** (after all patients are simulated): cross-record.
  `nursing flowsheet` / `immunization` / `family_history` /
  `code_status` / `care_level`.

Modules write only into `CIFPatientRecord.extensions[<module>]`
(new typed fields on core types are Base-only). Adding a module =
registering the enricher in the registry (the dispatch body is
never edited — AD-56).

### 1f. Writing CIF

Each patient's structural data is written immutably to
`cif/structural/patients/<encounter_id>.json`. At this point the
`document` module has emitted **only the `ClinicalDocument` stub**
(metadata + author + encounter binding, `narrative=None`). The
actual free text arrives in Stage 2 (AD-65).

---

## 2. Stage 2 = `narrate`: narrative generation (the swappable layer)

`narrate --provider template|mock|ollama|bedrock --version-id <id>`
writes `cif/narratives/<version>/documents/<enc>/<doc>.json`.

- `NarrativePass` (`document/narrative/passes.py`, an ABC) reads
  structural CIF and derives the narrative from patient profile /
  labs / conditions / medications / scenario spine as input.
- **Walk order = `(doc_type, language)` groups** — the same
  prompt-prefix batches are processed sequentially → LLM prompt-
  cache hit rate is maximised (do not change).
- Template and LLM share the **same base class**. The LLM path has
  `LLMService.complete_prompt()` as its sole LLM call site (AD-11);
  prompts live in `llm_service/prompts/{en,ja}/*.yaml`.
- Because it is versioned, you can create another version later and
  rebuild FHIR with it.

---

## 3. Stage 3 = `export-fhir`: CIF → FHIR R4

`export-fhir --narrative-version <id>` merges structural + narrative
via `CIFReader`, and the `_fhir_*` builders (`modules/output/`)
assemble FHIR resources.

- **Bulk Data Access** (AD-31): 1 NDJSON per resource type +
  `manifest.json`. Not wrapped in a Bundle.
- Builders **read CIF only**. Display is resolved via
  `code_lookup(system, code, lang)`; URIs via `get_system_uri`;
  country → code system via `system_key_for` (hard-coding
  forbidden).
- Adding a FHIR resource = register a builder with
  `register_bundle_builder` (AD-56 — do not edit the dispatch).
- Adding an output format = `register_output_adapter` (CSV is the
  reference implementation).

Currently 25+ resource types (Patient / Encounter / Condition /
Observation / MedicationRequest / MedicationAdministration /
Procedure / DiagnosticReport / ServiceRequest / ImagingStudy /
DocumentReference / Composition / ClinicalImpression / CareTeam /
AllergyIntolerance / Immunization / FamilyMemberHistory / Coverage
/ Device / Specimen / Organization / Location / Practitioner /
PractitionerRole / Endpoint / …).

---

## 4. Trace one inpatient (concrete example)

```
run_beta(config)                                   # simulator/engine.py
 └ generate_population(40000, "US", rng)            # 40k people in a catchment
     → PersonRecord(age=78, chronic=["I10","N18"])  # a 78-year-old with hypertension + CKD
 └ generate_monthly_events(...) each month          # population/engine.py
     → incidence evaluation → acute_mi onset
     → sample_severity(acute_mi protocol, person)   # disease YAML distribution × modifiers (elderly → skew to severe)
        = ("severe", 0.82)
     → requires_hospital = 0.82 > threshold = True
     → LifeEvent(acute_mi, severe, requires_hospital)
 └ activate_patient(person)                          # patient/activator.py
     → PatientProfile(stage: "CKD G3a" / "HT Stage 2", baseline BP ↑ by stage)
 └ _simulate_patient(event)                          # inpatient.py
     → category_from_score(0.82) = "severe"
     → select_archetype("severe", …, acute_mi.course_archetypes, .archetype_modifiers)
        = "dip_then_recovery"
     → apply_disease_onset(state, "severe", acute_mi.initial_state_impact)
     └ _run_daily_loop(...)  per day                 # state → labs / vitals / orders / MAR daily
         → derive_lab_values(...)  troponin ↑ CK-MB ↑ Cr ↑ (CKD baseline)
         → evaluate_complications(...)               # acute_mi.complications
         → POST_ENCOUNTER enrichers: device → hai → antibiotic → imaging → triage → nursing → document
     → CIFPatientRecord(orders, labs, vitals, mar, documents(stub), extensions{...})
 └ write cif/structural/patients/ENC-....json
--- narrate ---
 └ TemplateNarrativePass  → cif/narratives/template/documents/ENC-.../hp.json (H&P body)
--- export-fhir ---
 └ _fhir_conditions → Condition(acute_mi I21, stage "CKD G3a" …)
    _fhir_observations → Observation(troponin, Cr, …)
    _fhir_medications → MedicationRequest / Administration
    … → fhir_r4/*.ndjson
```

---

## 5. Where to enter when adding / fixing data

| What you want to do | Where to touch |
|---|---|
| New disease | Add `modules/disease/reference_data/<id>.yaml` (use an existing disease as template) + incidence entry in locale + register diagnosis codes in `codes/data/`. No engine code change. See `CONTRIBUTING-modules.md`. |
| New ED / outpatient condition | `modules/encounter/reference_data/<id>.yaml` |
| New lab-value analyte | `derive_lab_values` (observation) + code_mapping + `codes/data/loinc.yaml` |
| New FHIR resource | `_fhir_<topic>.py` builder + `register_bundle_builder` (§3) |
| New output format | `OutputAdapter` + `register_output_adapter` |
| New data kind (module) | `modules/<name>/` + enricher registration (§1e) + write into `extensions[<name>]` |
| Code → display name | `codes/data/<system>.yaml` (`en` required, `ja` optional). Resolve via `code_lookup`. |

**Invariants you must obey** (see `implementation-rules.md` for
detail): determinism (every RNG is seed-derived) / CIF holds codes
only (display resolved at output time) / unknown keys in disease
YAML raise at load time via `extra="forbid"` / severity, course,
complications are disease-YAML driven / silent-no-op defense
(canonical constants + `_validate_*` + completeness-invariant
tests).

---

## 6. Why this shape (the design spine)

- **Population-driven**: to scale epidemiology correctly at the
  population level and to track readmissions / outpatient follow-up
  under the same `person_id`.
- **YAML-driven**: instead of embedding clinical values in Python,
  disease / lab / locale / code definitions live in YAML so that
  "just add a module or a disease" produces new data (requirements
  4 and 8).
- **CIF two layers + three-stage CLI**: narrative quality can be
  improved independently after the fact (template → LLM), fulfilling
  requirements 5 and 6.
- **Determinism**: same seed = byte-identical output. Refactor
  byte-diff verification and regression goldens depend on it.
- **Silent-no-op defense**: "it looks like it ran but actually did
  not fire" (PR-90 / J5 / C-1) is the biggest enemy of this
  project. Multi-layer protection through canonical constants,
  fail-loud validation, firing counters, and completeness-
  invariant tests (`implementation-rules.md` §9).

Japanese counterpart: [`data-generation-walkthrough.ja.md`](data-generation-walkthrough.ja.md).
