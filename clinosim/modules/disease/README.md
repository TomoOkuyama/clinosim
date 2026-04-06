# disease

Disease protocol definitions and loader. Each disease is a YAML file. Adding a new disease = adding one YAML file. No code changes needed.

## Public API

```python
from clinosim.modules.disease.protocol import load_disease_protocol, DiseaseProtocol

protocol = load_disease_protocol("bacterial_pneumonia")
```

## Protocol files

```
clinosim/modules/disease/reference_data/
  bacterial_pneumonia.yaml
  heart_failure_exacerbation.yaml
  hip_fracture.yaml
  urinary_tract_infection.yaml
  copd_exacerbation.yaml
```

## Dependencies

- `clinosim.types` (Pydantic models)

## Testing

```bash
source .venv/bin/activate && python -m pytest tests/unit/test_disease.py -v
```

---

## How to add a new disease

### Step 1: Create the YAML file

Create `clinosim/modules/disease/reference_data/{disease_id}.yaml`.

Use `bacterial_pneumonia.yaml` as a reference template. The disease_id must be unique and use snake_case.

**Required metadata fields** (top of YAML, controls simulator behavior without code changes):

```yaml
disease_id: urinary_tract_infection
chief_complaint: "Fever, dysuria, flank pain"     # displayed in encounter
department: internal_medicine                       # managing department
encounter_type: medical                             # "medical" | "surgical" | "trauma"
requires_surgery: false                             # triggers procedure engine
minimum_severity: null                              # force minimum (e.g., "moderate" for fractures)
readmission_eligible: true                          # false for surgical conditions
```

### Step 2: Fill in each section

A disease YAML has the following sections. Required sections are marked with `*`.

#### `disease_id` * and `icd_codes` *

```yaml
disease_id: urinary_tract_infection    # unique snake_case identifier

icd_codes:
  primary: "N39.0"                     # most common ICD-10 code
  variants:
    - {code: "N30.0", name: "Acute cystitis", probability: 0.60}
    - {code: "N10", name: "Acute pyelonephritis", probability: 0.30}
    - {code: "N39.0", name: "UTI, site not specified", probability: 0.10}
```

#### `incidence` *

Age/sex-specific incidence rates per 100,000 population per year. Used by the population life event engine to determine how often this disease occurs.

```yaml
incidence:
  japan:
    "0-14":  {M: 50, F: 200}
    "15-44": {M: 20, F: 500}
    "45-64": {M: 100, F: 300}
    "65-74": {M: 200, F: 600}
    "75+":   {M: 400, F: 1000}

  # Risk multipliers: comorbidities that increase incidence
  risk_multipliers:
    - {condition: "E11.9", multiplier: 2.0}     # diabetes
    - {condition: "N18", multiplier: 1.5}       # CKD

  # Monthly seasonal variation (1.0 = baseline, >1.0 = higher than average)
  seasonal_curve:
    1: 1.0    # no strong seasonality for UTI
    # ... all 12 months

  # Optional: requires a pre-existing condition
  # requires_prior_condition: "N40"   # e.g., BPH for male UTI

  # Optional: trigger type
  # trigger_type: "trauma"             # for injuries (hip fracture)
```

**Data sources**: Use national patient surveys, epidemiological studies. Cite sources in comments.

#### `severity` *

How severe the disease is when it occurs. Determines hospitalization need and LOS.

```yaml
severity:
  distribution:
    mild: 0.60        # outpatient manageable (not hospitalized)
    moderate: 0.30     # requires hospitalization
    severe: 0.10       # requires ICU
  modifiers:
    - {condition: "age_over_75", severe_multiplier: 1.5}
    - {condition: "immunosuppressed", severe_multiplier: 2.0}
```

#### `initial_state_impact` *

How this disease changes the patient's physiological state at onset. This is the starting point — further changes come from `course_archetypes`.

```yaml
initial_state_impact:
  mild:
    inflammation_level: 0.15
  moderate:
    inflammation_level: 0.30
    renal_function: -0.05
    volume_status: -0.10
  severe:
    inflammation_level: 0.50
    renal_function: -0.15
    perfusion_status: -0.10
```

Available state variables: `inflammation_level`, `renal_function`, `cardiac_function`, `hepatic_function`, `anemia_level`, `coagulation_status`, `volume_status`, `perfusion_status`, `ph_status`. See physiology module for details.

#### `presenting_symptoms`

Symptoms the patient reports at presentation. Used by diagnosis module for differential.

```yaml
presenting_symptoms:
  - {name: "dysuria", probability: 0.90, severity_range: [0.3, 0.7]}
  - {name: "frequency", probability: 0.80, severity_range: [0.2, 0.6]}
  - {name: "fever", probability: 0.50, severity_range: [0.2, 0.6]}
```

#### `course_archetypes`

Day-by-day state variable changes for each clinical trajectory. This is the core of "how the disease progresses." The engine interpolates between defined days.

```yaml
course_archetypes:
  smooth_recovery:
    probability: 0.70
    description: "Responds well to antibiotics"
    trajectory:
      inflammation_level: {0: 0.03, 1: -0.05, 3: -0.08, 5: -0.05, 7: -0.03}
      renal_function: {0: 0.00, 2: 0.01, 5: 0.01}
    # Optional: triggers that fire on specific days
    triggers:
      - day: 3
        condition: "inflammation_level > 0.3"
        actions: ["switch_antibiotic", "order_urine_culture"]

  treatment_resistant:
    probability: 0.15
    description: "Resistant organism, requires antibiotic change"
    trajectory:
      inflammation_level: {0: 0.05, 1: 0.03, 3: 0.02, 5: -0.03, 7: -0.06, 10: -0.05}
    triggers:
      - day: 3
        condition: "inflammation_level > 0.3"
        actions: ["escalate_antibiotic"]
```

**Tips for trajectory design:**
- Day 0 is admission day. Positive values = worsening, negative = improving.
- CRP typically rises for 24-48h before declining (even with treatment).
- Define at least days 0, 1, 3, 7 — the engine interpolates between.
- Severe archetypes should show perfusion_status dropping, renal_function declining.
- Recovery archetypes should show inflammation declining, volume normalizing.

#### `complications`

Secondary events that can occur during hospitalization. Each has a daily probability, risk factors, and physiological impact.

```yaml
complications:
  - name: "c_diff_colitis"
    description: "C. difficile from antibiotic use"
    probability_per_day: 0.005
    onset_day_range: [5, 21]
    risk_factors:
      - {condition: "antibiotic_duration_over_7_days", multiplier: 2.0}
      - {condition: "age_over_65", multiplier: 1.5}
    state_impact:
      inflammation_level: 0.10
      volume_status: -0.10
    detection:
      test: "c_diff_toxin"
      finding: "positive"
    actions: ["stop_offending_antibiotic", "start_oral_vancomycin"]
    cascade: []          # list of complications this can trigger
```

Cascade example: DVT can trigger PE.
```yaml
  - name: "dvt"
    cascade: ["pulmonary_embolism"]
  - name: "pulmonary_embolism"
    parent_complication: "dvt"
    probability_given_parent: 0.10
```

#### `drugs`

Medications by country and role (first-line, alternative, escalation, discharge).

```yaml
drugs:
  first_line:
    japan:
      - {drug: "Levofloxacin", code_yj: "6241017", dose: "500mg IV daily"}
    us:
      - {drug: "Ciprofloxacin", code_rxnorm: "2551", dose: "400mg IV q12h"}
  alternative_penicillin_allergy:
    japan:
      - {drug: "Ceftriaxone", dose: "1g IV daily"}
  escalation:
    japan:
      - {drug: "Meropenem", dose: "1g IV q8h", indication: "resistant_organism"}
  discharge_oral:
    japan:
      - {drug: "Levofloxacin", dose: "500mg PO daily", duration_days: 7}
```

#### `target_los`

Expected length of stay by severity and country.

```yaml
target_los:
  japan:
    mild: null                # not hospitalized
    moderate: {mean: 7, sd: 2, min: 4, max: 14}
    severe: {mean: 14, sd: 4, min: 7, max: 28}
  us:
    moderate: {mean: 3, sd: 1, min: 2, max: 7}
    severe: {mean: 6, sd: 2, min: 3, max: 14}
```

#### `outcome_benchmarks`

Real-world statistics for validation. Generated data should match these.

```yaml
outcome_benchmarks:
  japan:
    median_los: 7
    in_hospital_mortality: 0.02
    thirty_day_readmission: 0.10
    mean_age_admitted: 68
    female_ratio: 0.65
```

### Step 3: Add epidemiology data to demographics.yaml

Add your disease to `clinosim/locale/{us,jp}/demographics.yaml` under `disease_incidence`:

```yaml
disease_incidence:
  your_disease_id:
    age_rates: {0: 10, 45: 50, 65: 200, 75: 600}
    sex_ratio_female: 1.5
    event_type: acute_disease_onset    # or chronic_exacerbation, trauma
    severity_beta: [2, 3]              # beta distribution params
    # Optional:
    prerequisite_condition: I50        # requires prior chronic condition
    always_hospitalize: true           # e.g., fractures
    hospitalization_threshold_modifier: 0.7
```

Also add seasonal modifiers and risk multipliers in the same file.
The population engine auto-discovers all diseases in `disease_incidence` — **no code changes needed**.

### Step 4: Test with debug output

```bash
# Quick test: simulate 1 patient with detailed debug output
clinosim test-disease your_disease_id -n 1 --severity moderate

# Test specific archetype
clinosim test-disease your_disease_id -n 1 --severity severe --archetype treatment_resistant

# Test with JP settings
clinosim test-disease your_disease_id -n 3 --country JP

# Verify it appears in the disease list
clinosim list-diseases

# Run full quality validation
clinosim validate -p 3000
```

The `test-disease` command shows detailed output for each patient:
- Demographics, chronic conditions
- Ward/bed, LOS, deceased status
- All orders (labs/imaging/medication/diet) with counts
- Lab results with values, units, flags
- Vitals with pain score and nursing notes
- Medication administration records
- Complications, ADL trajectory, I/O balance

### Step 5: Generate multi-patient data for analysis

```python
source .venv/bin/activate && python -c "
from clinosim.simulator import run_forced
from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.output.csv_adapter import convert_cif_to_csv
from clinosim.types.config import ForcedScenario

# Generate 5 patients with your disease, specific archetype
scenario = ForcedScenario(
    disease_id='your_disease_id',
    count=5,
    severity='moderate',            # or 'mild', 'severe'
    archetype='smooth_recovery',    # or any archetype you defined
)
dataset = run_forced(scenario)
write_cif(dataset, './output/test_disease')
convert_cif_to_csv('./output/test_disease', './output/test_disease_csv')

# Inspect results
for r in dataset.patients:
    enc = r.encounters[0]
    los = (enc.discharge_datetime - enc.admission_datetime).days
    print(f'{r.patient.patient_id}: LOS={los}d, Labs={len(r.lab_results)}, '
          f'Dx={r.clinical_diagnosis.discharge_diagnosis_code}, '
          f'Complications={r.complications_occurred or \"None\"}')
"
```

### Step 6: Verify each archetype produces correct clinical actions

Test each archetype separately to verify order/treatment modifications fire correctly:

```python
source .venv/bin/activate && python -c "
from clinosim.simulator import run_forced
from clinosim.types.config import ForcedScenario

for archetype in ['smooth_recovery', 'dip_then_recovery', 'treatment_resistant',
                  'gradual_deterioration', 'sudden_deterioration']:
    scenario = ForcedScenario(
        disease_id='your_disease_id',
        count=1,
        severity='moderate',
        archetype=archetype,
    )
    dataset = run_forced(scenario)
    r = dataset.patients[0]

    # Check archetype-specific orders
    mod_orders = [o for o in r.orders if 'MOD-D' in o.order_id or 'STOP' in o.order_id or 'START' in o.order_id]
    print(f'{archetype:25s}: LOS={len(r.physiological_states)-1}d, '
          f'mods={len(mod_orders)}, deceased={r.deceased}')
    for o in mod_orders:
        print(f'  {o.display_name}')
"
```

Expected output example (pneumonia):
```
smooth_recovery          : LOS=13d, mods=0, deceased=False
dip_then_recovery        : LOS=14d, mods=3, deceased=False    # Day 2: Lactate, blood culture, CXR
treatment_resistant      : LOS=13d, mods=6, deceased=False    # Day 3: STOP ABPC/SBT, START Meropenem, CT, cultures
gradual_deterioration    : LOS=16d, mods=8, deceased=False    # Day 3+5: escalation, vasopressor, ICU
sudden_deterioration     : LOS=5d,  mods=7, deceased=True     # Day 2: emergency escalation, ICU
```

### Step 7: Validate against benchmarks

Run a full population simulation and check your disease's outcome benchmarks:

```bash
source .venv/bin/activate && python -c "
from clinosim.simulator import run_beta
from clinosim.modules.validator.benchmarks import run_benchmarks
from clinosim.types.config import SimulatorConfig

dataset = run_beta(SimulatorConfig(catchment_population=20000, random_seed=42))
report = run_benchmarks(dataset, 'JP')
print(report.summary())
for r in report.results:
    print(f'  [{r.status}] {r.name}: {r.generated_value:.1f} (expected {r.expected_value})')
"
```

### Step 8: Generate with specific patient characteristics

Use `patient_overrides` in ForcedScenario to test edge cases:

```python
# Elderly patient with multiple comorbidities
scenario = ForcedScenario(
    disease_id='your_disease_id',
    count=3,
    severity='severe',
    archetype='gradual_deterioration',
    patient_overrides={
        'age': 88,
        'sex': 'F',
        'chronic_conditions': ['I10', 'E11.9', 'N18', 'I48'],  # HT + DM + CKD + AF
    },
)
```

---

## Condition types (AD-28)

Not all hospital visits are driven by a single identifiable disease:

| Type | Ground truth | Clinical diagnosis | Example |
|---|---|---|---|
| `known_disease` | Single disease YAML | Workup identifies it (usually) | Pneumonia → J13 |
| `mixed` | Multiple diseases overlap | May miss one | Pneumonia + HF → J18.9 + I50.9 (or just J18.9) |
| `unknown` | No disease YAML | Workup inconclusive | FUO → R50.9 |

## Implementation status

- [x] Protocol loader with Pydantic validation
- [x] Bacterial pneumonia (full: incidence, severity, archetypes with clinical scenarios, complications, drugs, orders, benchmarks)
- [x] Heart failure exacerbation (full)
- [x] Hip fracture (full, including procedure, rehab, order protocols)
- [x] YAML-driven clinical course archetypes with order/treatment modifications per scenario
- [x] Complication engine with cascade support
- [x] Condition-first model (known/mixed/unknown)
- [x] ForcedScenario: generate specific disease + archetype + severity without population
- [x] Disease-specific order protocols (admission, daily monitoring, discharge criteria)
- [x] Disease-specific diagnostic data (differential, LR table, code progression)
- [x] UTI + COPD exacerbation (data-driven, no code changes)
- [x] Disease metadata YAML-driven (chief_complaint, department, surgery, readmission)
- [x] Auto-discovery: adding YAML = adding disease
- [ ] More diseases (stroke, AMI, sepsis, DKA)
- [ ] Pediatric disease protocols
