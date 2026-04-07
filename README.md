# clinosim

> **Clinically Realistic Hospital Data Simulator** — Generate FHIR R4 EHR data from a virtual hospital

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![FHIR](https://img.shields.io/badge/output-HL7%20FHIR%20R4%20Bulk-orange)](https://hl7.org/fhir/uv/bulkdata/)
[![Status](https://img.shields.io/badge/status-v0.1%20beta-yellow)]()

🇯🇵 **日本語版**: [README.ja.md](README.ja.md)

**clinosim** generates synthetic EHR data through **forward simulation** starting from a population. Rather than producing random values, every patient carries a hidden **9-variable physiological state**, and all observations (labs, vitals, medications, diagnoses) are derived from that state — ensuring **clinically coherent** data.

Primary use cases:
- Training data for medical AI/ML models
- EHR system testing and QA
- Clinical research simulation
- Educational case datasets

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Output Formats](#output-formats)
- [Data Flow](#data-flow)
- [Module Architecture](#module-architecture)
- [Code Systems & Authoritative Sources](#code-systems--authoritative-sources)
- [Supported Diseases](#supported-diseases)
- [Multi-Country Support](#multi-country-support)
- [Hospital Configuration](#hospital-configuration)
- [Design Philosophy](#design-philosophy)
- [Testing](#testing)
- [Extension Guide](#extension-guide)
- [License](#license)

---

## Features

- **HL7 FHIR Bulk Data Access** compliant NDJSON output (Patient.ndjson, Encounter.ndjson, ...)
- **9-variable physiology model** ensures labs/vitals are physiologically and clinically coherent
- **Bayesian differential diagnosis** with likelihood ratios; 6 disease trajectory archetypes
- **Authoritative code systems** (ICD-10-CM, LOINC, RxNorm, JLAC10, YJ codes, CPT) with multilingual display
- **28 diseases + 44 ED/outpatient conditions** defined in YAML (no code changes to add new ones)
- **JCCLS reference ranges 2022** for Japanese labs; Tietz/Mayo for US
- **NEWS2-compatible vitals** including AVPU consciousness level and supplemental oxygen
- **Ward + bed Location hierarchy** with PractitionerRole.location assignment
- **Snapshot date** support — includes "currently admitted" patients (in-progress encounters)
- **30-day readmission chains** with `prior_encounter_id` linking
- **Multi-country**: US (English) and JP (Japanese) parallel output
- **Fully deterministic** with seed
- **English-first with language fallback** in code systems

---

## Installation

```bash
git clone https://github.com/your-org/clinosim.git
cd clinosim
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

**Requirements**:
- Python 3.11+
- Main dependencies: numpy, pyyaml, pydantic
- (Optional) Ollama for local LLM narrative generation

---

## Quick Start

### CLI

```bash
# Default: US, past 1 year ending today, 60,000 catchment, 50-bed hospital
clinosim generate -o ./output

# Custom period (--end is the snapshot date)
clinosim generate -o ./output --start 2024-01-01 --end 2024-12-31

# Japan 10-bed clinic
clinosim generate -o ./output \
  --country JP \
  --hospital-config clinosim/config/hospital_small.yaml \
  -p 12000

# Forced disease scenario (debugging)
clinosim test-disease bacterial_pneumonia -n 5 --severity moderate

# Encounter unit test
clinosim test-encounter chest_pain_noncardiac --age 65 --sex M

# List available diseases and encounters
clinosim list-diseases
```

### Python API

```python
from clinosim.simulator import run_beta
from clinosim.types.config import SimulatorConfig

config = SimulatorConfig(
    catchment_population=60_000,
    country="US",
    random_seed=42,
    snapshot_date="2026-04-08",   # EHR snapshot at this point in time
)
dataset = run_beta(config)

# Access results
for record in dataset.patients:
    enc = record.encounters[0]
    print(f"{record.patient.name.family_name}: {enc.encounter_type} → {enc.status}")
    print(f"  labs={len(record.lab_results)}, vitals={len(record.vital_signs)}")
```

### Code System Lookup

```python
from clinosim.codes import lookup, get_system_uri

lookup("icd-10-cm", "N10", "en")
# → "Acute tubulo-interstitial nephritis"

lookup("icd-10-cm", "N10", "ja")
# → "急性腎盂腎炎"

get_system_uri("loinc")
# → "http://loinc.org"
```

---

## CLI Reference

### `clinosim generate`

Population-driven simulation (primary use case).

| Option | Default | Description |
|---|---|---|
| `-o, --output DIR` | `./output` | Output directory |
| `-p, --population N` | hospital config's `recommended_population` | Catchment population |
| `--country CODE` | `US` | `US` or `JP` |
| `--start YYYY-MM-DD` | `--end` minus 1 year | Simulation start date |
| `--end YYYY-MM-DD` | today | Simulation end date = snapshot date |
| `--hospital-config PATH` | `clinosim/config/hospital_operations.yaml` (50-bed) | Hospital config YAML |
| `--format ...` | `cif fhir` | `cif`, `csv`, `fhir`, `narrative` |
| `-s, --seed N` | `42` | Random seed |
| `--narrative` | off | LLM narrative generation (requires Ollama) |
| `--narrative-model NAME` | `qwen:7b` | Ollama model name |

### `clinosim test-disease DISEASE_ID`

Generate forced scenario for a specific disease (debugging / golden tests).

```bash
clinosim test-disease heart_failure_exacerbation \
  --severity severe --archetype treatment_resistant -n 3
```

### `clinosim test-encounter CONDITION_ID`

ED / outpatient encounter unit test.

```bash
clinosim test-encounter migraine --age 35 --sex F
```

### `clinosim validate`

Quality check generated data against published benchmarks.

### `clinosim list-diseases`

Show all 28 diseases + 44 encounter conditions.

---

## Output Formats

### CIF (Clinosim Intermediate Format)

```
output/cif/
├── metadata.json                  # Generation info, snapshot_date, etc.
├── hospital.json                  # Staff roster + hospital config
└── structural/patients/
    └── ENC-POP-XXXXXX-NNNNNN.json # One file per encounter
```

CIF is the **immutable intermediate format** of the simulation. All output adapters derive from this.

### FHIR R4 — Bulk Data Export NDJSON Format

Compliant with [HL7 FHIR Bulk Data Access](https://hl7.org/fhir/uv/bulkdata/):

```
output/fhir_r4/
├── manifest.json                   # Bulk Data manifest (transactionTime, output[])
├── _facility.json                  # Organization + Location master (Bundle)
├── Patient.ndjson                  # 1 patient per line
├── Encounter.ndjson                # 1 encounter per line
├── Observation.ndjson              # labs + vitals + AVPU + O2 (LOINC)
├── Condition.ndjson                # Encounter dx + chronic conditions (ICD-10-CM)
├── MedicationRequest.ndjson        # Prescriptions (RxNorm)
├── MedicationAdministration.ndjson # MAR records
├── Procedure.ndjson                # Surgery + bedside procedures (CPT)
├── AllergyIntolerance.ndjson       # Patient-level (deduplicated)
├── Practitioner.ndjson             # Doctors, nurses, technicians
├── PractitionerRole.ndjson         # Specialty + organization + ward location
├── Organization.ndjson             # Hospital + departments
└── Location.ndjson                 # Wards + beds
```

Each line = 1 FHIR resource. `Resource.id` is unique across all 12 resource types. Reference integrity is maintained.

### Included FHIR R4 Fields (key resources)

| Resource | Fields |
|---|---|
| Patient | identifier (MRN, type=MR), name (with kanji+kana extension for JP), gender, birthDate, address, telecom, maritalStatus, communication (BCP-47), contact (emergency) |
| Encounter | class, type (SNOMED), serviceType, priority, period, length, participant (ATND/ADM/DIS), diagnosis ref, hospitalization (admitSource, dischargeDisposition), location (bed → ward via partOf), serviceProvider (department Org) |
| Observation | code (LOINC), valueQuantity (UCUM units + system + code), referenceRange (low/high/text/source extension for JP Core), interpretation (N/H/L/HH/LL), encounter, performer |
| Condition | code (ICD-10-CM with display), category (encounter-diagnosis / problem-list-item), severity (SNOMED), stage (NYHA, CKD G, GOLD, etc.), clinicalStatus (active/resolved), onsetDateTime, recordedDate, encounter |
| MedicationRequest | medicationCodeableConcept (RxNorm), dosageInstruction (text + doseAndRate + timing repeat + route SNOMED), encounter, requester, reasonReference |
| MedicationAdministration | dosage (dose SimpleQuantity + route + rateQuantity for continuous), context, performer, reasonReference |
| Procedure | code (CPT), encounter, performedDateTime / performedPeriod, performer |
| Practitioner | name (with prefix), gender, telecom, qualification |
| PractitionerRole | practitioner, organization (dept), location (ward), specialty (SNOMED) |
| Location | physicalType (wa=ward, bd=bed, area), partOf (bed→ward), managingOrganization |
| Organization | hospital-main + dept-{specialty} (partOf hierarchy) |

### CSV

```
output/csv/
├── patients.csv
├── encounters.csv
├── conditions.csv
├── lab_results.csv
├── vital_signs.csv
├── orders.csv
├── medication_administrations.csv
├── procedures.csv
└── ...
```

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│  population engine                                          │
│  ・Generate catchment (household-based)                     │
│  ・PersonRecord (Layer 1: lightweight registry)             │
│  ・Monthly LifeEvent (incidence × seasonality × risk mod)   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  patient activator                                          │
│  ・PersonRecord (L1) → PatientProfile (L2)                  │
│  ・Anthropometrics, organ reserves, chronic staging         │
│  ・Address, emergency contact, preferred language           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  encounter creation                                         │
│  ・disease YAML → department (resolved via hospital_config) │
│  ・staff_id assignment, ward + bed_number assignment        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  daily simulation loop (per inpatient day)                  │
│                                                              │
│   ┌──────────────────────────────┐                          │
│   │ clinical_course              │                          │
│   │  ・archetype trajectory      │                          │
│   │  ・diagnosis effectiveness   │                          │
│   │  ・natural recovery          │                          │
│   │  ・complications             │                          │
│   └──────────────────────────────┘                          │
│              │                                              │
│              ▼                                              │
│   ┌──────────────────────────────┐                          │
│   │ physiology engine            │                          │
│   │  ・9-state update            │                          │
│   │  ・derive_lab_values()       │                          │
│   │  ・derive_vital_signs()      │                          │
│   └──────────────────────────────┘                          │
│              │                                              │
│              ▼                                              │
│   ┌──────────────────────────────┐                          │
│   │ orders + observation         │                          │
│   │  ・place_daily_lab_orders()  │                          │
│   │  ・3-layer noise (CVi+CVa)   │                          │
│   │  ・H/L/critical flagging     │                          │
│   │  ・interp + reference range  │                          │
│   └──────────────────────────────┘                          │
│              │                                              │
│              ▼                                              │
│   ┌──────────────────────────────┐                          │
│   │ diagnosis engine             │                          │
│   │  ・Bayesian update (LR)      │                          │
│   │  ・working_diagnosis update  │                          │
│   └──────────────────────────────┘                          │
│              │                                              │
│              ▼                                              │
│   ┌──────────────────────────────┐                          │
│   │ procedure + MAR              │                          │
│   │  ・bedside procedures        │                          │
│   │  ・MAR (with hold logic)     │                          │
│   └──────────────────────────────┘                          │
│              │                                              │
│              ▼                                              │
│   ┌──────────────────────────────┐                          │
│   │ discharge readiness?         │                          │
│   │  YES → encounter complete    │                          │
│   │  NO  → next day              │                          │
│   └──────────────────────────────┘                          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  CIF dataset (immutable intermediate format)                │
└─────────────────────────────────────────────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
      ┌──────────┐  ┌──────────┐  ┌──────────┐
      │ CIF JSON │  │ FHIR R4  │  │   CSV    │
      │ writer   │  │ NDJSON   │  │ adapter  │
      └──────────┘  │ Bulk Data│  └──────────┘
                    └──────────┘
                         │
                         ▼
           clinosim.codes (lookup display text)
```

### Snapshot Semantics

- Simulation period: `--start` ~ `--end`
- `--end` = **snapshot date**
- No life events generated past the snapshot date (no future admissions)
- Inpatients whose `discharge_datetime` would fall after the snapshot date:
  - `discharge_datetime = None`
  - `Encounter.status = "in-progress"`
  - Partial data only (labs/vitals/orders/MAR up to snapshot day)
  - Primary `Condition.clinicalStatus = "active"` (not resolved)
- This produces a realistic EHR snapshot **including currently admitted patients** (e.g., 50-bed × 60% occupancy ≈ 30 in-progress encounters)

---

## Module Architecture

```
clinosim/
├── codes/                    # ★ International code systems + multilingual display (locale-independent)
│   ├── data/
│   │   ├── icd-10-cm.yaml    # 224 codes
│   │   ├── icd-10.yaml       # 110 (WHO ICD-10, JP)
│   │   ├── loinc.yaml        # 59
│   │   ├── jlac10.yaml       # 30
│   │   ├── rxnorm.yaml       # 68
│   │   ├── yj.yaml           # 39
│   │   ├── cpt.yaml          # 25
│   │   └── k-codes.yaml      # 2
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
│   ├── llm_service.yaml          # LLM (local Ollama default)
│   └── llm_service.cloud.yaml    # Anthropic API
│
├── types/                    # Data type definitions (Pydantic / dataclass)
│   ├── config.py             # SimulatorConfig
│   ├── patient.py            # PatientProfile, ChronicCondition
│   ├── clinical.py           # PhysiologicalState, ClinicalDiagnosis
│   ├── encounter.py          # Encounter, Order, VitalSignRecord, MAR
│   └── output.py             # CIFDataset, CIFPatientRecord, CIFMetadata
│
├── modules/                  # Functional modules (each with README)
│   ├── disease/              # 28 disease YAML protocols
│   ├── encounter/            # 44 ED/outpatient condition YAMLs
│   ├── physiology/           # 9-state model + lab/vital derivation
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
│   ├── output/               # CIF / FHIR R4 / CSV / narrative
│   ├── llm_service/          # Ollama + Anthropic integration
│   └── validator/            # Comparison against published benchmarks
│
├── simulator/                # Top-level orchestration
│   ├── engine.py             # run_beta, run_forced
│   ├── inpatient.py          # Inpatient simulation
│   ├── emergency.py          # ED visit
│   ├── outpatient.py         # Outpatient visit
│   ├── helpers.py            # Ward/department resolver, mortality, etc.
│   └── cli.py                # CLI entry point
│
└── tests/
    ├── unit/                 # Module unit tests (140 tests)
    ├── integration/          # Cross-module integration tests
    └── e2e/                  # E2E + golden file tests
```

Each module has its own **README.md** documenting purpose, design principles, API, data structures, and extension procedures.

---

## Code Systems & Authoritative Sources

`clinosim/codes/` centralizes international standard code systems. Total **8 systems, 577 codes**, all with English display (Japanese is optional).

| Key | Name | Use | Authoritative Source |
|---|---|---|---|
| `icd-10-cm` | ICD-10-CM | US diagnoses | [CMS](https://www.cms.gov/medicare/coding-billing/icd-10-codes) |
| `icd-10` | WHO ICD-10 | JP diagnoses | [WHO](https://icd.who.int/browse10/) |
| `loinc` | LOINC | Lab tests, vitals | [Regenstrief](https://loinc.org/) |
| `jlac10` | JLAC10 | JP lab codes | [JCCLS](https://www.jccls.org/) |
| `rxnorm` | RxNorm | US drugs | [NLM](https://www.nlm.nih.gov/research/umls/rxnorm/) |
| `yj` | YJ codes | JP drugs | MHLW Drug Price Standards |
| `cpt` | CPT | US procedures | [AMA](https://www.ama-assn.org/practice-management/cpt) |
| `k-codes` | K codes | JP reimbursement procedures | MHLW Medical Fee Schedule |

### Using Code Systems (FHIR Observation example)

```python
from clinosim.codes import lookup, get_system_uri

# CIF data is code-only
crp_code = "1988-5"  # LOINC

# Build FHIR Observation
obs = {
    "resourceType": "Observation",
    "code": {
        "coding": [{
            "system": get_system_uri("loinc"),
            "code": crp_code,
            "display": lookup("loinc", crp_code, "en"),
        }],
    },
    "valueQuantity": {"value": 38.2, "unit": "mg/L"},
}
```

See `clinosim/codes/README.md` for details.

---

## Supported Diseases

28 diseases defined in YAML, covering ~80% of acute hospital admissions:

| Category | Diseases |
|---|---|
| **Respiratory** | Bacterial pneumonia, Aspiration pneumonia, COPD exacerbation, Asthma exacerbation, Influenza, Pulmonary embolism |
| **Cardiovascular** | Heart failure exacerbation, Acute MI, Atrial fibrillation/RVR |
| **Neurological** | Cerebral infarction, Hemorrhagic stroke, Subdural hematoma |
| **GI/Hepatic** | GI bleeding, Acute pancreatitis, Ileus, Decompensated cirrhosis |
| **General Surgery** | Acute appendicitis, Acute cholecystitis |
| **Orthopedic** | Hip fracture, Vertebral compression fracture, Wrist fracture |
| **Trauma** | Severe traffic accident |
| **Metabolic** | Diabetic ketoacidosis |
| **Renal** | Acute kidney injury |
| **Infectious** | Sepsis, Urinary tract infection, Cellulitis |
| **Vascular** | Deep vein thrombosis |

Plus **44 ED/outpatient conditions** (chest pain, viral gastroenteritis, ankle sprain, annual screening, flu vaccination, dialysis session, etc.) — see `clinosim/modules/encounter/reference_data/`.

Adding new diseases requires **only adding a YAML file** (no code changes). See `clinosim/modules/disease/README.md`.

---

## Multi-Country Support

| Item | US (default) | JP (`--country JP`) |
|---|---|---|
| Diagnosis codes | ICD-10-CM | ICD-10 (WHO) |
| Lab codes | LOINC | JLAC10 |
| Drug codes | RxNorm | YJ codes |
| Procedure codes | CPT | K codes |
| Display language | English | Japanese (English fallback) |
| Patient names | English | Kanji + kana extension |
| Addresses | 50 US states | 47 Japanese prefectures (JIS X 0401) |
| Lab reference ranges | Tietz/Mayo | JCCLS Reference Intervals 2022 |
| Marital status | HL7 v3 (S/M/D/W) | Same |
| Language | en-US | ja-JP |

---

## Hospital Configuration

`clinosim/config/hospital_*.yaml` defines hospital physical layout and operational parameters:

```yaml
recommended_population: 60000

available_departments:           # Available specialties
  - internal_medicine
  - cardiology
  - gastroenterology
  - general_surgery
  - orthopedics
  - emergency_medicine
  - primary_care

department_rollup:              # Sub-specialty → available department
  pulmonology: internal_medicine
  neurology: internal_medicine
  neurosurgery: general_surgery

wards:                          # Wards per department
  internal_medicine: ["4E", "4W"]
  cardiology: ["5E"]
  general_surgery: ["3E"]
  orthopedics: ["3W"]
  emergency_medicine: ["ER"]
  primary_care: ["OPD"]

ward_capacity:                  # Bed count per ward
  "4E": 10
  "4W": 10
  "5E": 8
  "3E": 8
  "3W": 6

resource_capacity:              # Lab/imaging capacity
  lab_analyzers: 2
  ct_scanners: 1
  mri_scanners: 0
  inpatient_beds: 50

staffing:                       # Staffing ratio per shift
  day:    {hours: [8, 16],  lab_staff: 1.0, nursing_staff: 1.0}
  evening:{hours: [16, 0],  lab_staff: 0.5, nursing_staff: 0.7}
  night:  {hours: [0, 8],   lab_staff: 0.2, nursing_staff: 0.5}
```

This enables:
- Automatic disease → department → ward → bed routing
- M/M/1 queueing model with dynamic test result delays
- Nurses assigned per ward (PractitionerRole.location)
- Switchable hospital templates (large / mid-size / clinic)

See `clinosim/modules/facility/README.md`.

---

## Design Philosophy

1. **State before observation** — Lab values are never generated independently. All observations derive from physiological state.
2. **Process before outcome** — Diagnoses emerge from Bayesian reasoning over test results. Treatment changes are tied to observable clinical triggers.
3. **Institution shapes behavior** — The same disease produces different data depending on healthcare system (insurance, discharge criteria, culture).
4. **Code is the truth** — CIF stores only codes; display text is resolved at output time via the codes module.
5. **YAML-driven extensibility** — Adding a disease = adding a YAML file. No engine code changes.
6. **English-first** — All codes must have English display; other languages are translation attributes.
7. **Authoritative sources** — Code values and English text follow official definitions from CMS/NLM/AMA/WHO/etc.
8. **Single source of truth** — No duplicate data (e.g., CIF doesn't store display, codes module is the only source).

---

## Testing

```bash
source .venv/bin/activate

# All tests (140 tests, ~2 minutes)
pytest -x

# By category
pytest -m unit                   # Unit tests
pytest -m integration            # Cross-module
pytest -m e2e                    # E2E + golden tests

# Coverage
pytest --cov=clinosim
```

---

## Extension Guide

### Add a new disease

1. Create `clinosim/modules/disease/reference_data/<disease_id>.yaml` (use existing disease as template)
2. Add to incidence list in `clinosim/locale/<country>/demographics.yaml`
3. Add necessary ICD codes to `clinosim/codes/data/icd-10-cm.yaml` (if not present)
4. Test: `clinosim test-disease <disease_id>`

Details: `clinosim/modules/disease/README.md`

### Add a new encounter type (ED/outpatient)

1. Create `clinosim/modules/encounter/reference_data/<condition_id>.yaml`
2. Include `icd10_code` and `icd10_display`
3. Test: `clinosim test-encounter <condition_id>`

### Add a new country

1. Create `clinosim/locale/<country_code>/` folder
2. Add `names.yaml`, `addresses.yaml`, `demographics.yaml`, `reference_range_lab.yaml`, `formatting.yaml`
3. Add entry in `clinosim/locale/shared/naming_rules.yaml`
4. (Optional) Add country-specific code system to `codes/data/`

### Add a new language

Add a new language key to each entry in `clinosim/codes/data/*.yaml`:

```yaml
N10:
  en: "Acute tubulo-interstitial nephritis"
  ja: "急性腎盂腎炎"
  de: "Akute tubulointerstitielle Nephritis"   # New language
```

Details: `clinosim/codes/README.md`

---

## Module Dependency Graph

```
                     ┌──────────┐
                     │  codes   │  (international code systems)
                     └──────────┘
                          ▲
                          │ lookup
                          │
   ┌──────────┐      ┌──────────┐
   │  locale  │ ──── │  output  │ (FHIR/CIF/CSV)
   │(country) │      └──────────┘
   └──────────┘           ▲
        │                 │
        ▼                 │
   ┌──────────┐           │
   │  patient │           │
   │ activator│           │
   └──────────┘           │
        │                 │
        ▼                 │
   ┌──────────┐           │
   │encounter │           │
   └──────────┘           │
        │                 │
        ▼                 │
  ┌──────────────────────────────┐
  │  daily simulation loop       │
  │                              │
  │  clinical_course             │
  │       ↓                      │
  │  physiology  ←  diagnosis    │
  │       ↓             ↑        │
  │  observation    order        │
  │       ↓             ↓        │
  │  procedure       MAR         │
  └──────────────────────────────┘
        ▲                  ▲
        │                  │
   ┌──────────┐      ┌──────────┐
   │  disease │      │ facility │
   │  (YAML)  │      │ (queue)  │
   └──────────┘      └──────────┘
        │                  │
        └─────────┬────────┘
                  │
            ┌──────────┐
            │population│
            └──────────┘
                  │
                  ▼
          ┌──────────┐
          │  staff   │
          └──────────┘
                  ▲
                  │
            ┌──────────┐
            │healthcare│
            │ _system  │
            └──────────┘
```

`llm_service` and `validator` are cross-cutting (used in dedicated phases).

See each module's `clinosim/modules/<module>/README.md` for details.

---

## LLM Integration (Optional)

clinosim can use LLMs for narrative generation (discharge summaries, progress notes). Default: local Ollama.

```bash
# Install Ollama (separate)
brew install ollama
ollama serve
ollama pull qwen:7b

# Generate with narrative
clinosim generate --narrative --narrative-model qwen:7b
```

LLM is **not required** for structural data generation. Without an LLM, template-based narratives are used.

Details: `clinosim/modules/llm_service/README.md`

---

## Data Quality Validation

```bash
# Compare against published benchmarks (LOS, mortality, complication rates)
clinosim validate -p 5000 --country US
```

Public sources:
- JAMA, NEJM clinical guidelines
- AHRQ Healthcare Cost and Utilization Project (HCUP)
- MHLW Patient Survey (Japan)
- OECD Health Data

Details: `clinosim/modules/validator/README.md`

---

## Disclaimer

clinosim generates entirely **synthetic** data. No real patient information is used or produced. Generated data is intended for software development, algorithm research, and system testing only. **It must not be used for clinical decision-making**.

---

## Contributing

Contributions are welcome, especially from clinicians who can review the realism of disease modules and physiological mappings.

```bash
git clone https://github.com/your-org/clinosim.git
cd clinosim
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Each module's README has extension guidelines.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

Code system data follows the original registry's license:
- ICD-10-CM, RxNorm: Public domain
- LOINC: LOINC License (free for commercial use)
- WHO ICD-10: WHO Terms of Use
- CPT: AMA Copyright (educational/research subset only)
- JLAC10, YJ, K-codes: MHLW / JCCLS public data

---

## Citation

```bibtex
@software{clinosim,
  title  = {clinosim: Clinically Realistic Hospital Data Simulator},
  year   = {2026},
  url    = {https://github.com/your-org/clinosim}
}
```

---

## Related Documentation

- [README.ja.md](README.ja.md) — 日本語版 README
- [DESIGN.md](DESIGN.md) — Detailed design document (architecture decisions, ADRs)
- [TODO.md](TODO.md) — Development roadmap
- [CLAUDE.md](CLAUDE.md) — Claude Code development guidelines
- Each module's `README.md` — Module-level API reference
