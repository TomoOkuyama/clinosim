<!-- Extracted from `README.md` (Issue #568 PR A). Update the pointer in README when this file's heading changes. -->

# Module Architecture

> **Note:** the folder map below sketches the conceptual layout; specific
> code counts and file lists are point-in-time snapshots. Refer to the
> canonical module list and count in
> [`../../MODULES.md`](../../MODULES.md) and current per-system code counts
> in [`../../clinosim/codes/README.md`](../../clinosim/codes/README.md).

```
clinosim/
├── codes/                    # ★ International code systems + multilingual display (locale-independent)
│   ├── data/                 # 32 YAML (icd-10-cm / icd-10 / loinc / jlac10 /
│   │                         #          rxnorm / yj / cpt / k-codes / snomed-ct /
│   │                         #          hot7 / cvx / HL7 terminology / JP-CLINS eCS ...)
│   └── loader.py             # lookup(system, code, lang) API
│
├── locale/                   # Country/culture-specific data
│   ├── jp/, us/
│   │   ├── names.yaml        # Person names (family + given + reading)
│   │   ├── addresses.yaml    # 47 prefectures / 50 states + ZIP
│   │   ├── demographics.yaml # Age dist, incidence rates
│   │   ├── formatting.yaml   # Date/unit formatting
│   │   ├── reference_range_lab.yaml  # JCCLS / Tietz reference ranges
│   │   └── code_mapping_*.yaml  # Internal test name → standard code
│   └── shared/
│       ├── chronic_followup.yaml      # Outpatient patterns by chronic dx
│       ├── chronic_medications.yaml   # Home meds + monitoring
│       └── naming_rules.yaml          # Name generation rules
│
├── config/                   # Hospital configuration YAMLs
│   ├── hospital_operations.yaml  # 50-bed community hospital (default)
│   ├── hospital_small.yaml       # 10-bed clinic
│   ├── hospital_large.yaml       # 200-bed regional hospital
│   ├── llm_service.yaml          # LLM (local Ollama default)
│   ├── llm_service.bedrock.yaml  # AWS Bedrock
│   ├── llm_service.cloud.yaml    # Anthropic API
│   └── llm_service.sakura.yaml   # Sakura Cloud Ollama
│
├── types/                    # Data type definitions (Pydantic / dataclass)
│   ├── config.py             # SimulatorConfig
│   ├── patient.py            # PatientProfile, ChronicCondition
│   ├── clinical.py           # PhysiologicalState (14 variables), ClinicalDiagnosis
│   ├── encounter.py          # Encounter, Order, VitalSignRecord, MAR
│   ├── identity.py           # NationalIdentity, InsuranceEnrollment, IdentityTimeline
│   └── output.py             # CIFDataset, CIFPatientRecord, CIFMetadata
│
├── modules/                  # Functional modules (33 packages, each with README)
│   ├── disease/              # disease YAML protocols
│   ├── encounter/            # 46 ED/outpatient condition YAMLs
│   ├── physiology/           # 14-state model + lab/vital derivation
│   ├── clinical_course/      # 6 archetypes + complications + diagnosis feedback
│   ├── diagnosis/            # Bayesian differential (LR table)
│   ├── observation/          # 3-layer lab noise + flagging
│   ├── order/                # Lab/medication/imaging orders + result delays
│   ├── procedure/            # Surgery + bedside procedures + rehabilitation
│   ├── population/           # Population/household generation + life events
│   ├── patient/              # Layer1 → Layer2 activator
│   ├── staff/                # Hospital staff roster + assignment
│   ├── facility/             # Hospital state + M/M/1 queueing
│   ├── healthcare_system/    # Country-specific parameters (JP / US)
│   ├── identity/             # Resident identifier & insurance numbering (JP, opt-in)
│   ├── output/               # CIF / FHIR R4 / CSV + clinical documents
│   │   ├── cif_writer.py              # CIF structural writer
│   │   ├── fhir_r4_adapter.py         # FHIR R4 Bulk NDJSON (incl. DocumentReference)
│   │   ├── csv_adapter.py             # CSV tables
│   │   └── hospital_course_extractor.py  # ★ deterministic event extraction
│   ├── llm_service/          # All LLM access (AD-11)
│   │   ├── engine.py                  # LLMService, LLMTaskType, PatientSummary
│   │   ├── factory.py                 # YAML → LLMService
│   │   ├── prompt_registry.py         # ★ YAML-based prompt templates
│   │   ├── cache.py                   # ★ SHA256 disk cache
│   │   ├── providers/                 # ★ Pluggable provider subpackage
│   │   │   ├── base.py                # LLMProvider Protocol + ProviderResponse
│   │   │   ├── ollama.py              # Local Ollama
│   │   │   ├── bedrock.py             # AWS Bedrock (boto3 lazy import)
│   │   │   └── mock.py                # Deterministic test provider
│   │   └── prompts/                   # ★ Prompt template YAML tree
│   │       └── en/                    # English prompts (5 Tier A+B types)
│   │           ├── admission_hp.yaml
│   │           ├── discharge_summary.yaml
│   │           ├── death_summary.yaml
│   │           ├── operative_note.yaml
│   │           └── procedure_note.yaml
│   └── validator/            # Comparison against published benchmarks
│
├── simulator/                # Top-level orchestration
│   ├── engine.py             # run_beta, run_forced
│   ├── inpatient.py          # Inpatient simulation
│   ├── emergency.py          # ED visit
│   ├── outpatient.py         # Outpatient visit
│   ├── helpers.py            # Ward/department resolver, mortality, etc.
│   └── cli.py                # CLI entry point (simulate/generate, narrate, export-fhir, ...)
│
└── tests/
    ├── unit/                 # Module unit tests
    ├── integration/          # Cross-module integration tests
    └── e2e/                  # E2E + golden file tests
```

Each module has its own **README.md** documenting purpose, design principles, API, data structures, and extension procedures.

---
