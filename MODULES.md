# clinosim Module Map

A single-page overview of clinosim's 30 modules (counting rule: packages
under `clinosim/modules/`; non-package files like `_shared.py` excluded):
what each one does, what it depends on, who depends on it, and how data
flows through the simulator end-to-end. **Read this first** if you're new
to the project.

## このドキュメントの読み方

| Goal | Read |
|---|---|
| 初めて見る | top to bottom |
| 特定モジュールを探す | "Module Inventory" table |
| 既存コードを変更する | "Typical Change Impact" |
| 新モジュールを足す | [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) + [.github/TEMPLATE_MODULE_README.md](.github/TEMPLATE_MODULE_README.md) |
| PR の検証手段を選ぶ | [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) "PR 検証ガイド" |

## TL;DR

clinosim is a population-driven, physiology-based synthetic EHR data simulator,
organized into 30 themed modules (packages under `clinosim/modules/`) across
3 layers:

1. **Foundation** — `clinosim/codes/` + `clinosim/locale/` + `clinosim/types/`
   (no clinosim cross-dependencies)
2. **Simulation** — physiology → observation → order → clinical_course →
   encounter / patient activation
3. **Output** — `clinosim/modules/output/` adapters consume CIF, emit
   FHIR R4 (Bulk Data Access) / CSV

Data flow: `population → patient activation → encounter loop →
CIF (canonical intermediate format) → output adapter`

**The true project goal** is converting CIF data into **FHIR R4 + JP Core
compliant** output while preserving clinical realism and JP localization
quality. See [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md)
"PR 検証ガイド" for the verification gates that protect this goal.

## レイヤー構造

```
┌─ Foundation (no clinosim deps) ──────────────────────────┐
│  clinosim/codes/       international code systems        │
│  clinosim/locale/      country-specific data             │
│  clinosim/types/       shared data types                 │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Simulation (physiology-driven) ─────────────────────────┐
│  physiology   patient state + lab/vital derivation       │
│  observation  result generation (panels, microbiology, …)│
│  order        lab/medication/imaging order placement     │
│  clinical_course  daily evolution + complications        │
│  diagnosis    Bayesian-ish working diagnosis             │
│  procedure    surgical + bedside procedures              │
│  encounter    inpatient/ED/outpatient YAML protocols     │
│  disease      30+ disease YAML protocols                 │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Population & Activation ────────────────────────────────┐
│  population   demographics + life events                 │
│  patient      Layer 1 → Layer 2 activation               │
│  identity     JP insurance + national ID (opt-in)        │
│  staff        roster + practitioner assignment           │
│  facility     hospital state + bed/ward management       │
│  healthcare_system  country-scoped operational params    │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Enrichment ─────────────────────────────────────────────┐
│  POST_POPULATION stage (per-patient, post-demographics): │
│  allergy          AllergyIntolerance SNOMED upgrade (10) │
│                                                          │
│  POST_ENCOUNTER stage (per-encounter, post-loop):        │
│  device           ICU device placement (CVC/catheter/vent)│
│  hai              CLABSI / CAUTI / VAP (Phase 3a WBC+CRP) │
│  antibiotic       HAI empirical + narrow de-escalation   │
│  imaging          ImagingStudy metadata chain (AD-62)    │
│  triage           JTAS/ESI triage level + arrival_mode   │
│                   (ED-only, AD-64, order=93)             │
│  nursing_assign   primary nurse assignment (order=94)    │
│                   (inpatient; do NOT confuse w/ POST_RECORDS│
│                   nursing which handles NEWS2/GCS/Braden)│
│  document         Stage 1 clinical documents (95)        │
│                   DR + Composition + ClinicalImpression  │
│                   + 6 α-min-2 nursing/outpatient/ED types│
│                                                          │
│  POST_RECORDS stage (cross-record, post-all):            │
│  nursing          NEWS2 / GCS / Braden / Morse           │
│  immunization     CVX vaccine history                    │
│  family_history   first-degree relative disease history  │
│  code_status      DNR/Full Code resuscitation status     │
│  care_level       JP 要介護度 (JP only)                  │
│  sdoh             smoking + alcohol reference data       │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Output ─────────────────────────────────────────────────┐
│  output       CIF → FHIR R4 NDJSON / CSV adapters        │
│  llm_service  optional narrative generation              │
│  validator    data quality checks                        │
└──────────────────────────────────────────────────────────┘
```

## Module Inventory

30 modules total (packages under `clinosim/modules/`; the table below additionally
lists the `codes` / `locale` foundation packages, and `nursing_assignment` shares the
`clinosim/modules/nursing/` package with the flowsheet enricher). Click the `Module`
link for the per-module README.

| Module | 役割 | Layer | 主 Dependencies | 主 Consumers | Tier |
|---|---|---|---|---|---|
| [codes](clinosim/codes/README.md) | 国際コード体系 (LOINC/SNOMED/ICD/RxNorm/JLAC10/CVX) lookup | foundation | (none) | 全 module | foundational |
| [locale](clinosim/locale/README.md) | 国別文化データ (names/addresses/reference ranges/code_mapping) | foundation | codes | patient/observation/output/identity | foundational |
| [physiology](clinosim/modules/physiology/README.md) | 患者生理学状態 + lab/vital derivation (15+ state axes) | simulation | types | observation, simulator/* (4 sites) | core |
| [observation](clinosim/modules/observation/README.md) | lab/vital result generation (panels, microbiology, nursing) | simulation | physiology/codes/locale | simulator/*, output | core |
| [order](clinosim/modules/order/README.md) | lab/medication/imaging order placement; panel-aware lab Order generation (PR1 ServiceRequest foundation) | simulation | observation/codes | simulator/*, output (_fhir_service_request.py) | core |
| [clinical_course](clinosim/modules/clinical_course/README.md) | archetype rule-based daily evolution + complications | simulation | types/_shared (no `physiology` import — decoupled via `StateChangeDirective`) | simulator/inpatient.py | core |
| [diagnosis](clinosim/modules/diagnosis/README.md) | working/discharge diagnosis with Bayesian likelihood ratios | simulation | codes | simulator/inpatient.py | core |
| [procedure](clinosim/modules/procedure/README.md) | surgical + bedside procedures + rehab | simulation | codes/locale/types | simulator/inpatient.py | core |
| [encounter](clinosim/modules/encounter/README.md) | 46 ED/outpatient condition YAML protocols | simulation | codes/locale | simulator/emergency.py, simulator/outpatient.py | core |
| [disease](clinosim/modules/disease/README.md) | 30+ disease YAML protocols (Pydantic-validated) | simulation | (self-contained — `protocol.py` defines its own Pydantic models, does not import `clinosim/types/`; a defensible historical exception since no other module imports these classes directly) | simulator/inpatient.py | core |
| [population](clinosim/modules/population/README.md) | demographics + life events (Layer 1) | population | locale | simulator/__init__.py | core |
| [patient](clinosim/modules/patient/README.md) | Layer 1 → Layer 2 activation (chronic conditions + home meds) | population | population/codes/locale/sdoh | simulator/* | core |
| [identity](clinosim/modules/identity/README.md) | JP insurance + national ID assignment (AD-54, opt-in) | population | locale/types | output (FHIR Coverage) | optional (JP) |
| [staff](clinosim/modules/staff/README.md) | hospital roster + practitioner role assignment | population | types | simulator/*, output (Practitioner) | core |
| [facility](clinosim/modules/facility/README.md) | hospital state + bed/ward management + M/M/1 queueing | population | types | simulator/inpatient.py, output (Location) | core |
| [healthcare_system](clinosim/modules/healthcare_system/README.md) | country-scoped operational parameters | population | locale | simulator/*, observation | infrastructure |
| [immunization](clinosim/modules/immunization/README.md) | CVX adult vaccine history (post_records enricher) | enrichment | types/codes/locale | simulator/enrichers.py, output | optional |
| [family_history](clinosim/modules/family_history/README.md) | first-degree relative disease history (enricher) | enrichment | types/codes/locale | simulator/enrichers.py, output | optional |
| [code_status](clinosim/modules/code_status/README.md) | DNR/Full Code SNOMED resuscitation status (enricher) | enrichment | types/codes | simulator/enrichers.py, output | optional |
| [care_level](clinosim/modules/care_level/README.md) | JP 要介護度 long-term-care need level (JP-only enricher) | enrichment | types/codes/locale | simulator/enrichers.py, output | optional (JP) |
| [sdoh](clinosim/modules/sdoh/README.md) | smoking + alcohol enum→SNOMED reference (data-only variant) | enrichment | codes | output (_fhir_smoking_alcohol.py) | foundational |
| [device](clinosim/modules/device/README.md) | ICU device placement (CVC / indwelling catheter / ventilator) | enrichment | types/codes | simulator/enrichers.py (POST_ENCOUNTER), output (_fhir_device.py), modules/hai | optional |
| [hai](clinosim/modules/hai/README.md) | Hospital-acquired infection (CLABSI / CAUTI / VAP) via CDC NHSN baseline + Phase 3a WBC + CRP forward-delta lift + Phase 3b-2 antibiogram-driven S/I/R susceptibility population (`hai_antibiogram.yaml`); `MicrobiologyResult.hai_event_id` backref is **load-bearing for Phase 3b-3 antibiotic Pass 2 narrow / de-escalation consumer** | enrichment | types/codes + modules/device + modules/antibiotic (ANTIBIOTIC_LOINC_LOOKUP) + physiology.engine (Phase 3a) | simulator/enrichers.py (POST_ENCOUNTER), simulator/inpatient.py (apply_hai_lab_lift), output (_fhir_hai.py + reuses _fhir_microbiology.py), **modules/antibiotic enricher Pass 2 (Phase 3b-3)** | optional |
| [antibiotic](clinosim/modules/antibiotic/README.md) | HAI empirical antibiotic regimen (IDSA 2009/2016) — emits MedicationRequest + MAR (Phase 3b-1, always-on); `ANTIBIOTIC_LOINC_LOOKUP` (Phase 3b-2) provides antibiotic key → LOINC for susceptibility Observations; **Phase 3b-3 narrow / de-escalation chain** (same enricher Pass 2, `narrow_ladder.yaml`, 3 outcomes SWITCH/ELIMINATION/NO_CHANGE, FHIR `MedicationRequest.status="stopped"`, audit clinical axis active enforcement of NHSN R-rate + empty rate + narrow rate) | enrichment | types/codes + modules/hai | simulator/enrichers.py (POST_ENCOUNTER order=85), output (reuses _fhir_medications.py), audit/axes/clinical.py | optional |
| [imaging](clinosim/modules/imaging/README.md) | Imaging metadata-only chain (ImagingStudy + Endpoint + radiology DR + imaging SR dispatch); Tier 1 #2 always-on Module [AD-62] | enrichment | types/codes/locale + order | simulator/enrichers.py (POST_ENCOUNTER order=90), output (_fhir_imaging_study.py + _fhir_endpoint.py + _fhir_diagnostic_report.py radiology variant + _fhir_service_request.py imaging dispatch) | optional |
| [allergy](clinosim/modules/allergy/README.md) | AllergyIntolerance 8-field SNOMED-coded enricher (allergen SNOMED + reaction + category + criticality + clinical/verification status); POST_POPULATION order=10, 15% prevalence, replaces activator.py inline sampling (Tier 1 #3 α-min-1) | enrichment | types/codes + patient | simulator/enrichers.py (POST_POPULATION order=10), output (_fhir_allergy_intolerance.py) | always-on |
| [triage](clinosim/modules/triage/README.md) | ED triage level (JTAS/JP / ESI/US) + arrival_mode + acuity_score; POST_ENCOUNTER order=93 (ED-only); always-on Module (AD-64). Writes `EncounterRecord.triage_data`; consumed by document_enricher for ED_TRIAGE_NOTE generation. | enrichment | types/codes/locale | simulator/enrichers.py (POST_ENCOUNTER order=93), document_enricher | always-on |
| [nursing_assignment](clinosim/modules/nursing/README.md) | Primary nurse assignment for inpatient/ICU/rehab encounters; POST_ENCOUNTER order=94; always-on Module (AD-64). Writes `EncounterRecord.primary_nurse_id`; consumed by CareTeam builder (`_fhir_care_team.py`). **Do NOT confuse** with the POST_RECORDS `nursing` module (NEWS2/GCS/Braden/Morse flowsheets) — same directory, different enricher function. | enrichment | types + staff | simulator/enrichers.py (POST_ENCOUNTER order=94), output (_fhir_care_team.py) | always-on |
| [document](clinosim/modules/document/README.md) | Two-role Module (AD-65): **Stage 1 enricher** — ClinicalDocument stub generation (metadata + author + narrative=None) for 9 DocumentType specs (α-min-1 3 + α-min-2 6); encounter_type gating via `DocumentTypeSpec.encounter_types_supported`; POST_ENCOUNTER order=95; always-on Module (AD-63, AD-64). **Stage 2 narrative pass** (`clinosim/modules/document/narrative/` sub-package) — loads structural CIF, populates `ClinicalDocumentNarrative` via `NarrativePass` base class (TemplateNarrativePass default, LLMNarrativePass deferred to β-JP-1); writes versioned narrative dir `cif/narratives/<version>/documents/`; two-pass CIF architecture invariant. See `document/README.md` AD-65 section for the full Stage 1 / Stage 2 boundary. | enrichment | types/codes/locale + allergy + triage | simulator/enrichers.py (POST_ENCOUNTER order=95), output (_fhir_documents.py + _fhir_composition.py + _fhir_clinical_impression.py), CLI (`narrate` verb) | always-on |
| [output](clinosim/modules/output/README.md) | CIF → FHIR R4 NDJSON / CSV adapters (registry-based) | output | 全 module (via builders) | CLI (clinosim generate) | core |
| [llm_service](clinosim/modules/llm_service/README.md) | optional narrative generation (Ollama/Bedrock/Anthropic) | output | codes | output (narrative path), simulator | optional |
| [validator](clinosim/modules/validator/README.md) | data quality tier framework | output | types | CLI (clinosim validate) | optional |
| [audit](clinosim/audit/) | clinosim audit framework — 4 軸 (structural / clinical / jp_language / silent_no_op) verification gate; per-Module audit.py plug-ins | verification | clinosim/codes/, all modules with audit.py | CLI (clinosim audit) | guard |

**Tier 凡例**:
- `foundational` — used by almost everything; changes ripple widely
- `core` — main simulation loop; changes affect every generated patient
- `optional` — opt-in feature; can be disabled without breaking core flow
- `infrastructure` — operational parameters; rare changes

## Dependency Tree

```
codes/  (no deps)
locale/  └── codes/
types/  (no deps)

physiology/  └── types/
observation/  ├── physiology/
              ├── codes/
              └── locale/
order/        └── observation/, codes/
clinical_course/  └── types/, _shared/ (no physiology dependency — decoupled via StateChangeDirective)
diagnosis/    └── codes/
procedure/    └── codes/, locale/, types/
encounter/    └── codes/, locale/
disease/      └── (self-contained Pydantic models, not types/)

population/   └── locale/
patient/      ├── population/
              ├── codes/
              ├── locale/
              └── sdoh/
identity/     └── locale/, types/
staff/        └── types/
facility/     └── types/
healthcare_system/  └── locale/

immunization/   ├── types/, codes/, locale/
family_history/ ├── types/, codes/, locale/
code_status/    ├── types/, codes/
care_level/     ├── types/, codes/, locale/
sdoh/           └── codes/  (data-only variant, no enricher)
device/         ├── types/, codes/
hai/            ├── types/, codes/, modules/device, modules/antibiotic (ANTIBIOTIC_LOINC_LOOKUP)
antibiotic/     ├── types/, codes/, modules/hai
imaging/        ├── types/, codes/, locale/, modules/order
allergy/        ├── types/, codes/, modules/patient
document/       ├── types/, codes/, locale/, modules/allergy

output/         └── 全 module  (via _BUNDLE_BUILDERS + registry)
llm_service/    └── codes/
validator/      └── types/

simulator/  (top-level orchestration)
  ├── population/      (Layer 1)
  ├── patient/         (Layer 2)
  ├── encounter/       (ED/outpatient YAML)
  ├── disease/         (inpatient YAML)
  ├── physiology/      (state)
  ├── observation/     (labs/vitals)
  ├── order/           (orders/MAR)
  ├── clinical_course/ (daily evolution)
  ├── diagnosis/       (working dx)
  ├── procedure/       (surgical/bedside)
  ├── staff/           (assignment)
  ├── facility/        (beds/wards)
  ├── enrichers.py     (post_population: allergy; post_encounter: device/hai/antibiotic/imaging/triage/nursing_assignment/document; post_records: nursing/immunization/family_history/code_status/care_level)
  └── output/          (CIF → FHIR/CSV)
```

## Typical Call Chains

### Chain 1: Population generation

```
simulator/run_beta()
  ↓ load_population()          ─ population/engine.py
  ↓ assign_identities()        ─ identity/assign.py (if --jp-insurance)
  ↓ activate_patient()         ─ patient/activator.py
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
  ↓ per-order sub-rng via individual_lab_seed()         ─ simulator/seeding.py
  ↓ OrderResult populated → patient_record.lab_results
```

### Chain 3: FHIR export

```
CLI: clinosim generate --format fhir-r4
  ↓ output/fhir_r4_adapter.py: convert_cif_to_fhir()
  ↓ for each CIF patient:
    ↓ build BundleContext (record + country + roster + …)
    ↓ for each builder in _BUNDLE_BUILDERS:
        builder(ctx) → list[dict]  (FHIR resources)
    ↓ write() each resource to <ResourceType>.ndjson
```

Adding a FHIR resource: register a new builder via
`register_bundle_builder()` (AD-56) — never edit `_BUNDLE_BUILDERS` list
directly. See [clinosim/modules/output/README.md](clinosim/modules/output/README.md)
"拡張方法 (Extensibility)".

## Typical Change Impact

| Change | Affects | Notes |
|---|---|---|
| Add scenario flag (e.g. `causes_X`) | `physiology.engine` + 4 derive_lab_values call sites | Helper-mediated via `scenario_flags_from_protocol`; see [SCENARIO_FLAGS.md](SCENARIO_FLAGS.md) |
| Add medication-driven lab effect | `physiology.engine` + 4 sites | Helper-mediated via `medication_flags_from_context`; see [SCENARIO_FLAGS.md](SCENARIO_FLAGS.md) |
| Add new code (LOINC/SNOMED/ICD/…) | `codes/data/<system>.yaml` (en + optional ja) | See [clinosim/codes/README.md](clinosim/codes/README.md) |
| Add new FHIR resource type | New `_fhir_<X>.py` + `register_bundle_builder()` | See [clinosim/modules/output/README.md](clinosim/modules/output/README.md) "Extensibility" |
| Add new disease | New disease YAML + register in `locale/<country>/demographics.yaml` | See [clinosim/modules/disease/README.md](clinosim/modules/disease/README.md) |
| Add new module | Copy [.github/TEMPLATE_MODULE_README.md](.github/TEMPLATE_MODULE_README.md); register in [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) | |

> **The true goal is FHIR R4 / JP Core compliance + clinical coherence + JP language quality.**
> PR の検証手段(byte-diff vs 3-axis DQR)については
> [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) 「PR 検証ガイド」を参照。

## Adding a New Module (5-step quick-start)

1. **Decide Base vs opt-in Module** → [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) 「判断: Base か Module か」
2. **Copy template** → [.github/TEMPLATE_MODULE_README.md](.github/TEMPLATE_MODULE_README.md) to `clinosim/modules/<name>/README.md`
3. **Create files per template** → `__init__.py` + `engine.py` + `reference_data/*.yaml` + `README.md`
4. **If enricher**: register sub-seed offset in `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS` (16-bit hex ASCII convention)
5. **Update this `MODULES.md`** inventory table with new row

## Where to Read Next

| Doc | Purpose |
|---|---|
| [README.md](README.md) / [README.ja.md](README.ja.md) | User-facing overview |
| [DESIGN.md](DESIGN.md) | Architecture + ADR table (55+ entries) |
| [CLAUDE.md](CLAUDE.md) | AI agent rules + project conventions |
| [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) | Module-author playbook + PR verification guide |
| [.github/TEMPLATE_MODULE_README.md](.github/TEMPLATE_MODULE_README.md) | Boilerplate for new module READMEs |
| [SCENARIO_FLAGS.md](SCENARIO_FLAGS.md) | Scenario / medication flag central reference |
| [TODO.md](TODO.md) | Roadmap |
| Per-module `README.md` | API + Dependencies + Consumers |
