# clinosim Module Map

A single-page overview of clinosim's **33 modules** (counting rule:
top-level packages under `clinosim/modules/`; non-package files like
`_shared.py` excluded, and `nursing_assignment` shares
`clinosim/modules/nursing/` with the observation-layer nursing
flowsheet enricher). Read this first if you are new to the project.

**Per-module deep dives**: every module ships its own `README.md` +
`README.ja.md` following the canonical 11-section structure
(Purpose / Scope / Public API / Determinism / Dependencies /
Constants and configuration / Directory contents / Enricher wiring /
Output surfaces / Testing / Ownership) — see the module index at
[`clinosim/modules/README.md`](clinosim/modules/README.md).

## このドキュメントの読み方

| Goal | Read |
|---|---|
| 初めて見る | top to bottom |
| 特定モジュールを探す | "Module inventory" table |
| 既存コードを変更する | "Typical change impact" |
| 新モジュールを足す | [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) + [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md) |
| PR の検証手段を選ぶ | [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) 「PR 検証ガイド」 |

## TL;DR

clinosim is a population-driven, physiology-based synthetic EHR data
simulator, organized into **33 themed modules** (packages under
`clinosim/modules/`) across four layers:

1. **Foundation** — `clinosim/codes/` + `clinosim/locale/` +
   `clinosim/types/` (no clinosim cross-dependencies).
2. **Simulation** — physiology → observation → order →
   clinical_course → encounter / patient activation.
3. **Enrichment** — POST_POPULATION / POST_ENCOUNTER / POST_RECORDS
   passes registered in `clinosim/simulator/enrichers.py`.
4. **Output** — `clinosim/modules/output/` adapters consume CIF and
   emit FHIR R4 Bulk Data NDJSON, CIF-JSON, or CSV.

Data flow: `population → patient activation → encounter loop →
enrichers → CIF (canonical intermediate format) → output adapter`.

**Project goal**: convert CIF data into **FHIR R4 + JP Core compliant**
output while preserving clinical realism and JP localisation quality.
The AD-60 audit framework (six per-module plug-ins today: `hai`,
`antibiotic`, `order`, `imaging`, `document`, `triage`) is the
load-bearing verification gate that protects this goal.

## Layered architecture

```
┌─ Foundation (no clinosim deps) ──────────────────────────┐
│  clinosim/codes/       international code systems        │
│  clinosim/locale/      country-specific data             │
│  clinosim/types/       shared data types                 │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Simulation (physiology-driven) ─────────────────────────┐
│  physiology   patient state + lab/vital derivation       │
│  observation  result generation (panels, microbiology,   │
│               nursing scores)                            │
│  order        lab/medication/imaging order placement     │
│  clinical_course  daily evolution + complications        │
│  diagnosis    Bayesian differential diagnosis            │
│  procedure    surgical + bedside procedures + rehab      │
│  encounter    inpatient/ED/outpatient YAML protocols     │
│  disease      32 disease YAML protocols                  │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Population & activation ────────────────────────────────┐
│  population   demographics + life events                 │
│  patient      Layer 1 → Layer 2 activation               │
│  identity     JP insurance + national ID (opt-in)        │
│  pediatric    pediatric encounter emission (Issue #760)  │
│  staff        roster + practitioner assignment           │
│  facility     hospital operational state + queueing      │
│  healthcare_system  country-scoped operational params    │
│  family_history  first-degree relative disease history   │
│  sdoh         smoking + alcohol reference (data-only)    │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Enrichment ─────────────────────────────────────────────┐
│  POST_POPULATION stage (per-patient, post-demographics): │
│  allergy(10)      15% overall + category-weighted allergen│
│  identity(10)     JP insurance + national ID (JP-gated)  │
│                                                          │
│  POST_ENCOUNTER stage (per-encounter, post-loop):        │
│  device(70)       CVC / catheter / ventilator placement  │
│  hai(80)          CLABSI / CAUTI / VAP + Phase 3a WBC/CRP│
│  antibiotic(85)   HAI empirical + narrow de-escalation   │
│  imaging(90)      ImagingStudy metadata chain (AD-62)    │
│  triage(93)       JTAS/ESI level + arrival_mode (ED-only)│
│  nursing_assignment(94)   primary nurse                  │
│  document(95)     ClinicalDocument stubs + ClinicalImpression│
│                                                          │
│  POST_RECORDS stage (cross-record, post-all):            │
│  nursing(20)      NEWS2 / GCS / Braden / Morse           │
│                   (this is observation-layer nursing_flowsheets,│
│                   NOT nursing_assignment)                │
│  immunization(30) CVX vaccine history                    │
│  family_history(40) first-degree relative history        │
│  code_status(50)  DNR / Full Code resuscitation status   │
│  care_level(60)   JP 要介護度 (JP only)                  │
│  medication_monitoring(65) chronic-med → labs (Issue #757)│
│  health_checkup(70) JP 事業者健診 (JP only, opt-in)      │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Output ─────────────────────────────────────────────────┐
│  output       CIF → FHIR R4 NDJSON / CSV adapters        │
│  llm_service  optional narrative generation (Stage 2)    │
│  validator    realism benchmarks + consistency checks    │
└──────────────────────────────────────────────────────────┘
```

## Module inventory

33 modules total (top-level packages under `clinosim/modules/`; the
table below additionally lists the `codes` / `locale` foundation
packages). Every entry links to the per-module README (which follows
the canonical 11-section structure).

| Module | Role | Layer | Sub-seed | Enricher stage / order |
|---|---|---|---|---|
| [codes](clinosim/codes/) | international code lookup (LOINC/SNOMED/ICD/RxNorm/JLAC10/CVX/JJ1017 K-code) | foundation | — | — |
| [locale](clinosim/locale/) | country-specific data (names / addresses / reference ranges / code_mapping) | foundation | — | — |
| [physiology](clinosim/modules/physiology/README.md) | 14-variable physiology state + lab/vital derivation | simulation | — (uses caller RNG) | — |
| [observation](clinosim/modules/observation/README.md) | lab / vital / microbiology + nursing flowsheet (NEWS2/GCS/Braden/Morse) | simulation | nursing `0x4E55` (shared) | POST_RECORDS 20 (`nursing`) |
| [order](clinosim/modules/order/README.md) | lab / medication / imaging order placement + AD-60 audit | simulation | — (per-order via AD-59) | — (audit registered) |
| [clinical_course](clinosim/modules/clinical_course/README.md) | trajectory archetype + daily `StateChangeDirective` | simulation | — (uses caller RNG) | — |
| [diagnosis](clinosim/modules/diagnosis/README.md) | Bayesian differential + Issue #551 non-specific codes | simulation | — | — |
| [procedure](clinosim/modules/procedure/README.md) | surgery + bedside + rehab generation | simulation | — (uses caller RNG) | — |
| [encounter](clinosim/modules/encounter/README.md) | encounter registry (46 YAML) + inpatient daily-cycle timeline | simulation | — | — |
| [disease](clinosim/modules/disease/README.md) | disease registry (32 YAML) + severity + acuity + drug-vocabulary | simulation | — | — |
| [population](clinosim/modules/population/README.md) | demographics + life events (Layer 1) | population | — (pipeline head) | — |
| [patient](clinosim/modules/patient/README.md) | Layer 1 → Layer 2 activation + chronic meds | population | — (caller-owned cache) | — |
| [identity](clinosim/modules/identity/README.md) | JP insurance + national ID (opt-in) | population | `540054` (decimal, grandfathered) | POST_POPULATION 10 (JP-gated) |
| [pediatric](clinosim/modules/pediatric/README.md) | pediatric encounter emission (Issue #760) | population | — (population calendar hook) | — |
| [staff](clinosim/modules/staff/README.md) | roster + `assign_staff` per-event dispatch | population | — (uses caller RNG) | — |
| [facility](clinosim/modules/facility/README.md) | hospital operational state + M/M/1-style queueing | population | — | — |
| [healthcare_system](clinosim/modules/healthcare_system/README.md) | country-config loader (leaf) | population | — | — |
| [family_history](clinosim/modules/family_history/README.md) | first-degree relative disease history | enrichment | `0x4648` ("FH") | POST_RECORDS 40 |
| [sdoh](clinosim/modules/sdoh/README.md) | smoking + alcohol SNOMED reference (data-only) | enrichment | — | — |
| [allergy](clinosim/modules/allergy/README.md) | SNOMED-coded allergy sampling (15% overall gate) | enrichment | `0x414C` ("AL") | POST_POPULATION 10 |
| [device](clinosim/modules/device/README.md) | ICU device placement | enrichment | `0x4445` ("DE") | POST_ENCOUNTER 70 |
| [hai](clinosim/modules/hai/README.md) | CLABSI / CAUTI / VAP + Phase 3a WBC/CRP lift + AD-60 audit | enrichment | `0x4841` ("HA") | POST_ENCOUNTER 80 |
| [antibiotic](clinosim/modules/antibiotic/README.md) | HAI empirical + narrow ladder + AD-60 audit | enrichment | `0x4142` ("AB") | POST_ENCOUNTER 85 |
| [imaging](clinosim/modules/imaging/README.md) | ImagingStudy metadata chain + AD-60 audit (AD-62) | enrichment | `0x4947` ("IG") | POST_ENCOUNTER 90 |
| [triage](clinosim/modules/triage/README.md) | JTAS / ESI triage sampling + AD-60 audit (ED-only, AD-64) | enrichment | `0x5452` ("TR") | POST_ENCOUNTER 93 |
| [nursing](clinosim/modules/nursing/README.md) (`nursing_assignment`) | primary nurse assignment (inpatient/ICU/rehab; AD-64) | enrichment | `0x4E55` ("NU") | POST_ENCOUNTER 94 |
| [document](clinosim/modules/document/README.md) | stub emission + AD-60 audit + Stage 2 narrative subpackage | enrichment | `0x444F` ("DO") | POST_ENCOUNTER 95 |
| [immunization](clinosim/modules/immunization/README.md) | CVX adult vaccine history | enrichment | `0x494D` ("IM") | POST_RECORDS 30 |
| [code_status](clinosim/modules/code_status/README.md) | DNR / Full Code SNOMED resuscitation status | enrichment | `0x4353` ("CS") | POST_RECORDS 50 |
| [care_level](clinosim/modules/care_level/README.md) | JP 要介護度 (JP only) | enrichment | `0x434C` ("CL") | POST_RECORDS 60 (JP-gated) |
| [monitoring](clinosim/modules/monitoring/README.md) | chronic-med → monitoring labs (Issue #757) | enrichment | `0x4D4D` ("MM") | POST_RECORDS 65 |
| [health_checkup](clinosim/modules/health_checkup/README.md) | JP 事業者健診 (JP-only opt-in) | enrichment | `0x4843` ("HC") | POST_RECORDS 70 |
| [output](clinosim/modules/output/README.md) | CIF → FHIR R4 NDJSON / CSV adapter registry | output | — | — |
| [llm_service](clinosim/modules/llm_service/README.md) | single LLM gateway (AD-11) for narrative Stage 2 | output | — | — |
| [validator](clinosim/modules/validator/README.md) | realism benchmarks + consistency checks | output | — | — |

Sub-seed offsets are the values in
[`clinosim/seeding.py`](clinosim/seeding.py) `ENRICHER_SEED_OFFSETS`.

## Dependency tree

```
codes/  (no deps)
locale/  └── codes/
types/  (no deps)

physiology/  └── types/
observation/  ├── physiology/
              ├── codes/
              └── locale/
order/        └── observation/, codes/
clinical_course/  └── types/, _shared/  (no physiology import; decoupled via StateChangeDirective)
diagnosis/    └── codes/
procedure/    └── codes/, locale/, types/, disease/acuity
encounter/    └── codes/, locale/
disease/      └── (self-contained Pydantic models, not types/)

population/   └── locale/, disease.severity, disease.protocol, pediatric.calendar
patient/      ├── population/, codes/, locale/, physiology.engine (hba1c_from_glycemic_control)
identity/     └── locale/, types/
pediatric/    └── (population.LifeEvent, lazy-imported inside generate_pediatric_events)
staff/        └── types/, locale.names
facility/     └── types/
healthcare_system/  └── types.HealthcareSystemConfig
family_history/ ├── types/, codes/, locale/
sdoh/           └── codes/  (data-only variant, no enricher)

allergy/        ├── types/, codes/
device/         ├── types/, codes/
hai/            ├── types/, codes/, modules/device, modules/antibiotic (ANTIBIOTIC_LOINC_LOOKUP), physiology.engine (Phase 3a lift)
antibiotic/     ├── types/, codes/, modules/observation (antibiotic_loinc_lookup)
imaging/        ├── types/, codes/, locale/, modules/order
triage/         ├── types/, codes/, locale/
nursing/        ├── types.staff/, seeding/  (Assignment side; nursing_flowsheets lives in observation)
document/       ├── types/, codes/, locale/, modules/allergy, modules/triage
immunization/   ├── types.encounter (lazy import), codes/, locale/
code_status/    ├── codes/, locale/
care_level/     ├── codes/, locale/
monitoring/    ├── modules/observation.engine (generate_lab_result etc.)
health_checkup/ ├── types.clinical + types.encounter, codes/

output/         └── every module  (via _BUNDLE_BUILDERS + registry)
llm_service/    └── codes/  (leaf; providers/ optionally boto3/httpx)
validator/      └── types/  (stdlib only for benchmarks)

simulator/  (top-level orchestration)
  ├── population/       (Layer 1)
  ├── patient/          (Layer 2 activation)
  ├── encounter/        (ED/outpatient YAML)
  ├── disease/          (inpatient YAML)
  ├── physiology/       (state + directive application)
  ├── observation/      (labs / vitals)
  ├── order/            (orders / MAR + panel_grouping)
  ├── clinical_course/  (daily evolution)
  ├── diagnosis/        (working dx)
  ├── procedure/        (surgical / bedside / rehab)
  ├── staff/            (assignment)
  ├── facility/         (beds / wards / queueing)
  ├── enrichers.py      (POST_POPULATION + POST_ENCOUNTER + POST_RECORDS registrations)
  └── output/           (CIF → FHIR / CSV)
```

## Typical call chains

### Chain 1: Population + patient activation

```
simulator/engine.py: run_beta()
  ↓ load_population()          ─ population/engine.py (generate_population)
  ↓ generate_monthly_events()  ─ population/engine.py (per year × month)
  ↓ generate_healthcare_calendar()  ─ population/engine.py (per year)
  ↓ assign_identities()        ─ identity/assign.py  (POST_POPULATION order=10, JP-gated)
  ↓ allergy_enricher()         ─ allergy/engine.py   (POST_POPULATION order=10)
  ↓ activate_patient()         ─ patient/activator.py  (per person, exactly-once via cache)
      ├── _derive_home_medications()  ─ locale/shared/chronic_medications.yaml
      └── PatientProfile populated (chronic_conditions, smoking_status, alcohol_use, …)
```

### Chain 2: Lab derivation (most-touched code path)

```
simulator/inpatient.py: _run_daily_loop()
  ↓ scenario_flags_from_protocol(protocol)             ─ physiology/engine.py
  ↓ medication_flags_from_context(patient, all_orders, admission_date, day)
                                                        ─ physiology/engine.py
  ↓ flags = {**scenario_flags, **medication_flags}
  ↓ derive_lab_values(state, sex, age, **flags)         ─ physiology/engine.py
  ↓ per-order sub-RNG via individual_lab_seed()         ─ clinosim/seeding.py (AD-59)
  ↓ OrderResult populated → patient_record.lab_results
```

### Chain 3: FHIR export

```
CLI: clinosim export-fhir --format fhir-r4
  ↓ output/fhir_r4/__init__.py: convert_cif_to_fhir()
  ↓ for each CIF patient:
    ↓ build BundleContext (record + country + roster + narrative merge)
    ↓ for each builder in _BUNDLE_BUILDERS:
        builder(ctx) → list[dict]  (FHIR resources)
    ↓ post_process pipeline (datetime → specimen → profile → populate → strip)
    ↓ write each resource to <ResourceType>.ndjson + sort by id
  ↓ manifest.json + _facility.json + _generator_metadata.json emitted
```

Adding a FHIR resource: register a new builder via
`register_bundle_builder()` (AD-56) — never edit `_BUNDLE_BUILDERS`
directly. See
[`clinosim/modules/output/fhir_r4/README.md`](clinosim/modules/output/fhir_r4/README.md).

## Typical change impact

| Change | Affects | Notes |
|---|---|---|
| Add scenario flag (`causes_X`) | `physiology.engine` + 4 `derive_lab_values` call sites | Helper-mediated via `scenario_flags_from_protocol`; see [`SCENARIO_FLAGS.md`](SCENARIO_FLAGS.md) |
| Add medication-driven lab effect | `physiology.engine` + 4 sites | Helper-mediated via `medication_flags_from_context`; see [`SCENARIO_FLAGS.md`](SCENARIO_FLAGS.md) |
| Add new code (LOINC/SNOMED/ICD/…) | `codes/data/<system>.yaml` (`en` + optional `ja`) | See [`clinosim/codes/README.md`](clinosim/codes/README.md) |
| Add new FHIR resource type | New builder file under `output/fhir_r4/<domain>/` + `register_bundle_builder()` | See [`clinosim/modules/output/fhir_r4/README.md`](clinosim/modules/output/fhir_r4/README.md) |
| Add new disease | New disease YAML + register in `locale/<country>/demographics.yaml` | See [`clinosim/modules/disease/README.md`](clinosim/modules/disease/README.md) |
| Add new module | Copy [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md); register per [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) | Follow the canonical 11-section README structure |

> **Project goal: FHIR R4 / JP Core compliance + clinical coherence + JP
> language quality.** PR verification (byte-diff vs 3-axis DQR vs
> `clinosim audit run`) is documented in
> [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md)
> 「PR 検証ガイド」.

## Adding a new module (5-step quick start)

1. **Decide Base vs opt-in Module** →
   [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md)
   「判断: Base か Module か」.
2. **Copy template** →
   [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md)
   to `clinosim/modules/<name>/README.md`; add `README.ja.md` mirror.
3. **Create files per canonical layout** → `__init__.py` +
   `engine.py` + `reference_data/*.yaml` +
   `_<name>_thresholds.py` when the module has any numeric scalar
   (Issue #637 lift rule) + `audit.py` when the module ships an
   AD-60 audit plug-in.
4. **If enricher**: register the sub-seed offset in
   [`clinosim/seeding.py`](clinosim/seeding.py)
   `ENRICHER_SEED_OFFSETS` (16-bit hex-ASCII convention, e.g.
   `0x4142 = "AB"`) and add the `register_enricher(...)` call in
   `clinosim/simulator/enrichers.py`.
5. **Update this `MODULES.md`** inventory table with the new row.

## Where to read next

| Doc | Purpose |
|---|---|
| [`README.md`](README.md) / [`README.ja.md`](README.ja.md) | User-facing overview |
| [`AGENTS.md`](AGENTS.md) | AI-agent rules + project conventions (`CLAUDE.md` is a thin pointer to this file) |
| [`DESIGN.md`](DESIGN.md) | Landing pointer → `docs/architecture/` (design principles / architecture notes / ADR history) |
| [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) | Module-author playbook + PR verification guide |
| [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md) | Boilerplate for new module READMEs |
| [`SCENARIO_FLAGS.md`](SCENARIO_FLAGS.md) | Scenario / medication flag central reference |
| [`docs/roadmap.md`](docs/roadmap.md) | Roadmap (GitHub Issues board) |
| [`clinosim/modules/README.md`](clinosim/modules/README.md) | Module index (this file's per-module counterpart) |

Japanese counterpart: [`MODULES.ja.md`](MODULES.ja.md).
