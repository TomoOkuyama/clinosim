# clinosim

> **Clinically Realistic Hospital Data Simulator**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![FHIR](https://img.shields.io/badge/output-HL7%20FHIR%20R4-orange)](https://hl7.org/fhir/)
[![Status](https://img.shields.io/badge/status-v0.1%20alpha-yellow)]()

**clinosim** generates synthetic hospital EHR data by simulating patients' clinical journeys — from symptom onset through diagnosis, hospitalization, treatment, and discharge. Instead of producing random data, it maintains a **hidden physiological state** for each patient and derives all observations from that state, ensuring that labs, vitals, and clinical decisions are internally consistent.

---

## Installation

```bash
git clone https://github.com/your-org/clinosim.git
cd clinosim
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

**Requirements:** Python 3.11+

---

## Quick Start

### CLI

```bash
# Population-driven simulation (default: US, 10k catchment population)
clinosim generate -o ./output --seed 42

# Japan mode with all output formats
clinosim generate -o ./output --country JP --format cif csv fhir

# Generate specific disease scenarios
clinosim test-disease bacterial_pneumonia -n 5 --format cif csv

# Force severity and archetype
clinosim test-disease sepsis --severity severe --archetype treatment_resistant

# Generate with LLM narratives (requires Ollama)
clinosim generate -o ./output --narrative --narrative-model qwen:7b

# Data quality validation
clinosim validate -p 5000 --country US

# List available diseases
clinosim list-diseases
```

### Python API

```python
from clinosim.simulator import run_beta, run_forced
from clinosim.types.config import SimulatorConfig, ForcedScenario

# Population-driven simulation
config = SimulatorConfig(
    catchment_population=10_000,
    random_seed=42,
    country="US",
)
dataset = run_beta(config)

# Or generate a specific disease scenario
scenario = ForcedScenario(
    disease_id="bacterial_pneumonia",
    count=3,
    severity="moderate",
    archetype="smooth_recovery",
)
dataset = run_forced(scenario, SimulatorConfig(random_seed=42))

# Access results
for record in dataset.patients:
    print(f"{record.patient.age}yo {record.patient.sex}")
    print(f"  Labs: {len(record.lab_results)}")
    print(f"  Vitals: {len(record.vital_signs)}")
    print(f"  Orders: {len(record.orders)}")
```

### Output Formats

| Format | Description |
|---|---|
| **CIF** (default) | Structural JSON — full simulation data, immutable intermediate format |
| **CSV** | 12 tables: patients, encounters, diagnoses, lab_results, vital_signs (with pain scores and nursing notes), orders (including diet), medication_administrations, procedures, rehab_sessions, intake_output, adl_assessments (Barthel Index), prescriptions |
| **FHIR R4** | HL7 FHIR R4 JSON bundles (Patient, Encounter, Observation, MedicationRequest, MedicationAdministration, Procedure, Practitioner) |

---

## How It Works

clinosim generates data through a forward simulation pipeline:

```
Population Registry       Disease definitions (YAML)
(demographics, households)    (protocols, drugs, archetypes)
        |                           |
        v                           v
   Disease Event Scheduler  -->  Patient Activation
        |                           |
        v                           v
   Encounter Creation  <---  Clinical Course Engine
        |                    (6 trajectory archetypes)
        |                           |
        v                           v
   Daily Simulation Loop      Physiology Engine
   (orders, labs, vitals,     (9 state variables,
    meds, procedures)          coupling rules)
        |                           |
        v                           v
   Diagnosis Engine           Observation Engine
   (Bayesian differential,    (3-layer variability:
    likelihood ratios)         biological + analytical)
        |                           |
        +----------- + ------------+
                     |
                     v
              CIF / CSV / FHIR Output
```

### Key Concepts

- **9 physiological state variables** (inflammation, renal, cardiac, hepatic, anemia, coagulation, volume, perfusion, pH) drive all observations via coupling rules
- **Bayesian diagnosis engine** — differential lists updated by test results using likelihood ratios from disease YAML
- **6 clinical course archetypes** — smooth_recovery, dip_then_recovery, plateau, treatment_resistant, gradual_deterioration, sudden_deterioration
- **3-layer lab variability** — biological CV (CVi) + pre-analytical + analytical CV (CVa), with context-dependent missingness (weekend, stable patient, specimen rejection, hemolysis artifacts)
- **Diagnosis-treatment feedback** — misdiagnosis slows recovery; diagnostic difficulty per disease drives treatment effectiveness
- **30-day readmission** — YAML benchmark-calibrated, with prior encounter linking and Layer 1 hospitalization history
- **16 chronic conditions** — home medications continued during hospitalization, condition-specific monitoring labs
- **Individual variation** — age-based trajectory speed, daily noise, treatment timing jitter, natural recovery
- **3 condition types** — known_disease (92%), mixed dual-pathology (4%), unknown presentation (3%)

---

## Supported Diseases

Diseases are defined entirely in YAML — no code changes needed to add new ones.

20 diseases covering ~75% of acute hospital admissions:

| Category | Diseases |
|---|---|
| **Respiratory** | Bacterial pneumonia, COPD exacerbation, Aspiration pneumonia |
| **Cardiovascular** | Heart failure exacerbation, Acute MI, Atrial fibrillation/RVR, Pulmonary embolism |
| **Infectious** | Sepsis, UTI/Pyelonephritis, Cellulitis |
| **GI/Hepatic** | GI bleeding, Acute pancreatitis, Acute cholecystitis (surgical), Ileus, Decompensated cirrhosis |
| **Metabolic** | Diabetic ketoacidosis |
| **Neurological** | Cerebral infarction (stroke) |
| **Renal** | Acute kidney injury |
| **Surgical** | Hip fracture (ORIF/hemiarthroplasty), Acute appendicitis |

Adding a new disease requires only a YAML file + epidemiology data in demographics.yaml — no code changes.

See `clinosim/modules/disease/README.md` for how to add new diseases.

---

## Multi-Country Support

Default output is US/English. Japan is available via `--country JP`.

| Item | US (default) | Japan (`--country JP`) |
|---|---|---|
| Lab codes | LOINC | JLAC10 |
| Diagnosis codes | ICD-10-CM | ICD-10 |
| Drug codes | (generic names) | (generic names) |
| Lab display names | English | Japanese |
| Patient names | English names | Japanese names (kanji + kana) |
| Date/unit formatting | US conventions | Japanese conventions |

Locale data lives in `clinosim/locale/{country}/`. Adding a new country = adding one folder with YAML files (names, terminology, code mapping, formatting) and a section in `shared/naming_rules.yaml`.

---

## Project Structure

```
clinosim/
  clinosim/
    simulator.py               # Main simulator (run_beta, run_forced, CLI)
    types/                     # Shared data types (config, patient, clinical, encounter, output)
    locale/                    # Country-specific data (names, terminology, codes, formatting)
    config/                    # YAML config files (country defaults, LLM settings)
    modules/
      physiology/              # 9 state variables, coupling rules, lab/vital derivation
      clinical_course/         # 6 trajectory archetypes, complication evaluation
      diagnosis/               # Bayesian differential diagnosis engine
      disease/                 # Disease loader + reference_data/*.yaml
      observation/             # 3-layer lab variability, H/L/critical flagging
      order/                   # YAML-driven admission/daily order protocols
      population/              # Household-based population generation
      patient/                 # Layer 1 -> Layer 2 patient activation
      procedure/               # Surgery workflows, rehab sessions
      staff/                   # Hospital staff roster and assignment
      output/                  # CIF writer, CSV adapter, FHIR R4 adapter, narrative generator
      treatment/               # Medication selection and modification
      encounter/               # Encounter workflow management
      healthcare_system/       # Country-specific system parameters
      llm_service/             # LLM integration (Ollama local + cloud API)
      ...
  tests/
    unit/                      # Per-module unit tests
    integration/               # Module chain tests
    e2e/                       # Full simulation golden tests
  pyproject.toml
```

---

## Running Tests

```bash
source .venv/bin/activate

# All tests
pytest

# By category
pytest -m unit
pytest -m integration
pytest -m e2e

# With coverage
pytest --cov=clinosim
```

---

## Development Guidelines

### Module Dependency Direction

```
    healthcare_system
    (config root: all modules depend on this)
    |
    +-------------+----------------------------+
    |             |                            |
    v             v                            v
  facility ---> staff                     population
    |                                         |
    |                                     patient
    |                                     (L1->L2)
    |                                         |
    +-------------------+---------------------+
                        |
                        v
  disease ---------> encounter
    |              (workflow driver)
    |                 |
    |       +---------+-----------+
    |       |         |           |
    |       v         v           v
    +-> diagnosis   order <--> nursing
    |       |         |           |
    |       v         v           |
    +-> treatment     |           |
    |       |         |           |
    |       v         v           v
    +-> clinical   physiology  observation
        _course       |           |
                      |    procedure
                      |           |
                      +-----+-----+
                            |
                            v
                        validator
                            |
                            v
                          output

  llm_service (cross-cutting service: used by all, no reverse dependency)
```

When modifying a module, check its downstream dependents for consistency. High-impact modules:

- **disease YAML** — affects diagnosis, treatment, orders, clinical course, discharge criteria
- **physiology derivation formulas** — affects all lab/vital values
- **healthcare_system** — affects all behavior via country parameters

Each module has its own `README.md` with role, interfaces, and data addition instructions.

---

## Design Philosophy

1. **State before observation** — Lab values are never generated independently. Every observation is derived from physiological state, ensuring cross-marker consistency.
2. **Process before outcome** — Diagnoses emerge from Bayesian reasoning over test results, not assigned upfront. Treatment changes are tied to observable clinical triggers.
3. **Institution shapes behavior** — The same disease produces different data depending on the healthcare system (reimbursement, discharge criteria, cultural norms).
4. **YAML-driven extensibility** — Adding a disease means adding a YAML file. No engine code changes required.

---

## LLM Integration (Optional)

clinosim can use LLMs for narrative generation (discharge summaries, progress notes). Default: Ollama with a local Llama model. Cloud APIs available as fallback.

```bash
# Start Ollama (must be installed separately)
ollama serve

# Generate with narrative layer
clinosim generate -o ./output --seed 42
```

LLM is **not required** for structural data generation. Without an LLM, template-based narratives are used.

---

## Disclaimer

clinosim generates entirely **synthetic** data. No real patient information is used or produced. Generated data is intended for software development, algorithm research, and system testing only. It should not be used for clinical decision-making.

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

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Citation

```bibtex
@software{clinosim,
  title  = {clinosim: Clinically Realistic Hospital Data Simulator},
  year   = {2025},
  url    = {https://github.com/your-org/clinosim}
}
```
