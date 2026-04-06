# encounter

Encounter management module. Handles all types of patient-hospital interactions: inpatient stays, outpatient visits, ED visits, screening, and procedures.

## Architecture

clinosim models three encounter categories, each driven by YAML protocols:

| Category | YAML Location | Protocol Count | Description |
|---|---|---|---|
| **Inpatient diseases** | `modules/disease/reference_data/*.yaml` | 20 | Multi-day hospital stays with daily simulation |
| **ED conditions** | `modules/encounter/reference_data/*.yaml` | 11 | Emergency visits, typically discharged same day |
| **Outpatient conditions** | `modules/encounter/reference_data/*.yaml` | 13 | Scheduled visits: screening, follow-up, procedures |

**Adding a new encounter condition = adding a YAML file.** No code changes required.

---

## Adding a new encounter condition

### Step 1: Create the YAML file

Create `modules/encounter/reference_data/{condition_id}.yaml`.

The `condition_id` must be a unique snake_case identifier (e.g., `skin_biopsy`, `cataract_evaluation`).

### Step 2: Define the YAML structure

Every encounter condition YAML must include these fields:

```yaml
# Required metadata
condition_id: skin_biopsy                   # unique snake_case ID
chief_complaint: "Suspicious skin lesion evaluation and biopsy"
encounter_type: outpatient                  # "outpatient" | "emergency"
department: dermatology                     # managing department
disposition: discharge_home                 # "discharge_home" | "observation" | "admit"

# Severity and duration
severity_distribution:
  mild: 0.70        # probability (must sum to ~1.0)
  moderate: 0.25
  severe: 0.05

ed_stay_hours:      # visit duration per severity
  mild: {mean: 0.5, sd: 0.2}
  moderate: {mean: 1.0, sd: 0.3}
  severe: {mean: 2.0, sd: 0.5}

# Clinical workup
workup:
  vitals: true      # measure vital signs? (true/false)
  labs:             # each lab test with ordering probability
    - {test: "WBC", probability: 0.3}
    - {test: "CRP", probability: 0.2}
  imaging:          # imaging studies with probability
    - {test: "Skin_ultrasound", probability: 0.2}

# Treatment given during visit
treatment:
  - {name: "Local anesthesia (lidocaine)", probability: 0.9, route: "local", intent: "anesthesia"}
  - {name: "Punch biopsy", probability: 0.8, route: "procedure", intent: "diagnostic biopsy"}
  - {name: "Wound closure (suture)", probability: 0.5, route: "procedure"}

# Patient instructions at discharge
discharge_instructions:
  - "Keep wound clean and dry for 48 hours"
  - "Biopsy results available in 5-7 business days"
  - "Return if signs of infection (redness, warmth, drainage)"

# Medications prescribed at discharge
discharge_prescriptions:
  - {drug: "Acetaminophen 500mg", route: "PO", frequency: "q6h PRN", duration_days: 3, probability: 0.5}

# Demographics (who gets this condition)
incidence_modifier: 1.0     # relative frequency vs other conditions
age_distribution: adults    # "all" | "adults" | "adults_40plus" | "elderly" | "pediatric"
sex_ratio_female: 1.0       # 1.0 = equal, >1 = more women, <1 = more men
seasonal:                   # monthly multiplier (1.0 = baseline)
  1: 1.0
  2: 1.0
  # ... all 12 months
  12: 1.0
```

### Step 3: Register in the healthcare calendar (if applicable)

For conditions that should be **automatically generated** for the population (not just available for manual testing), add generation rules in `modules/population/engine.py` → `generate_healthcare_calendar()`.

Example: to add annual skin cancer screening for age 50+:
```python
# In generate_healthcare_calendar()
if person.age >= 50 and rng.random() < 0.1:  # 10% screening rate
    events.append(LifeEvent(
        person_id=person.person_id,
        event_type="health_screening",
        timestamp=date(year, int(rng.integers(3, 10)), int(rng.integers(1, 28))),
        severity=0.0,
        condition_type="screening",
        disease_id="skin_biopsy",  # matches condition_id in YAML
        encounter_type="outpatient",
        protocol_source="encounter:skin_biopsy",
    ))
```

For ED conditions, add to `locale/{country}/demographics.yaml` → `ed_visit_not_admitted.conditions`:
```yaml
ed_visit_not_admitted:
  conditions:
    - {name: "skin_biopsy", probability: 0.03, chief_complaint: "Suspicious skin lesion"}
```

### Step 4: Test with debug output

```bash
# Test a single patient with your new condition (detailed debug output)
clinosim test-encounter skin_biopsy

# Test with specific patient demographics
clinosim test-encounter skin_biopsy --age 65 --sex F --seed 123

# Test multiple patients
clinosim test-encounter skin_biopsy -n 5

# For inpatient diseases, use test-disease instead:
clinosim test-disease bacterial_pneumonia -n 1 --severity severe

# Verify it appears in the condition list
clinosim list-diseases

# Run full quality validation
clinosim validate -p 3000
```

The `test-encounter` command shows:
- Patient demographics and chronic conditions
- Encounter type, timing, duration
- All orders (labs, imaging, medications) with results
- Vital signs with pain score and nursing notes
- Diagnosis codes
- Discharge prescriptions

---

## YAML field reference

### Required fields

| Field | Type | Description |
|---|---|---|
| `condition_id` | string | Unique snake_case identifier |
| `chief_complaint` | string | What brings the patient (displayed in encounter) |
| `encounter_type` | string | `"outpatient"` or `"emergency"` |
| `department` | string | Managing department |
| `disposition` | string | `"discharge_home"`, `"observation"`, or `"admit"` |
| `severity_distribution` | dict | `{mild: 0.x, moderate: 0.x, severe: 0.x}` |
| `ed_stay_hours` | dict | Duration per severity `{mean: x, sd: y}` |
| `workup` | dict | Clinical workup (see below) |

### workup structure

```yaml
workup:
  vitals: true/false
  labs:
    - {test: "TestName", probability: 0.0-1.0}
    - {test: "TestName", probability: 0.0-1.0, serial: true, interval_hours: 3}  # for serial tests
  imaging:
    - {test: "ImagingName", probability: 0.0-1.0}
```

Available lab test names: WBC, CRP, Creatinine, Na, K, Glucose, Hb, Plt, AST, ALT, BUN, Troponin, BNP, PT_INR, HbA1c, Lactate, Albumin, TSH, Ca, eGFR, PCT, LDH, GGT, T_Bil, pH, HCO3, pCO2

### treatment structure

```yaml
treatment:
  - name: "Drug/procedure name"
    probability: 0.0-1.0      # chance of being administered
    route: "IV" | "PO" | "IM" | "SC" | "SL" | "topical" | "INH" | "procedure" | "non-pharmacologic"
    intent: "description"      # optional: clinical rationale
```

### Optional fields

| Field | Type | Default | Description |
|---|---|---|---|
| `discharge_instructions` | list[str] | `[]` | Patient education at discharge |
| `discharge_prescriptions` | list[dict] | `[]` | Take-home medications |
| `incidence_modifier` | float | `1.0` | Relative frequency |
| `age_distribution` | string | `"all"` | Target population |
| `sex_ratio_female` | float | `1.0` | Sex distribution |
| `seasonal` | dict | all 1.0 | Monthly incidence multiplier |

---

## How the simulator uses encounter YAMLs

1. **Auto-discovery**: `encounter/protocol.py` → `load_all_encounter_conditions()` scans `reference_data/*.yaml`
2. **ED visits**: demographics.yaml condition names are matched to YAML `condition_id`. If matched, the full protocol (labs, imaging, treatment) is used. If not matched, a basic simulation runs.
3. **Outpatient visits**: `generate_healthcare_calendar()` creates events. The simulator calls `_simulate_outpatient_visit()` which reads the YAML for visit reason and labs.
4. **Output**: All encounter types produce the same `CIFPatientRecord` structure → same CSV/FHIR output.

---

## Current encounter conditions

### ED conditions (11)
| Condition | Chief Complaint |
|---|---|
| viral_gastroenteritis | Nausea, vomiting, diarrhea |
| chest_pain_noncardiac | Chest pain, rule out ACS |
| minor_laceration | Laceration requiring sutures |
| ankle_sprain | Ankle injury after fall |
| viral_uri | Fever, sore throat, cough |
| migraine | Severe headache, nausea |
| allergic_reaction_mild | Urticaria, angioedema |
| low_back_pain | Acute low back pain |
| uti_uncomplicated | Dysuria, frequency |
| food_poisoning | Abdominal pain after meal |
| anxiety_panic_attack | Palpitations, anxiety |

### Outpatient conditions (13)
| Condition | Chief Complaint |
|---|---|
| annual_health_screening | Annual preventive checkup |
| preoperative_assessment | Pre-surgical evaluation |
| colonoscopy_screening | Colorectal cancer screening |
| upper_endoscopy_diagnostic | EGD for dyspepsia |
| diabetic_retinopathy_screening | Fundoscopy for DM |
| cardiac_rehabilitation | Post-MI supervised exercise |
| mammography_screening | Breast cancer screening |
| flu_vaccination | Influenza vaccination |
| wound_care_followup | Suture removal, wound check |
| orthopedic_injection | Joint injection for OA |
| new_patient_referral | New patient evaluation |
| lab_result_consultation | Test result review |
| prescription_renewal | Medication refill only |

---

## Implementation status
- [x] Inpatient encounter creation with ward/bed
- [x] YAML-driven ED visit simulation (11 conditions)
- [x] YAML-driven outpatient visit simulation (13 conditions)
- [x] Auto-discovery of encounter condition YAMLs
- [x] Healthcare calendar (chronic visits, screening, vaccination)
- [x] Post-discharge follow-up (20 disease-specific protocols)
- [x] Encounter linking (readmission prior_encounter_id)
- [ ] ICU workflow (15-min resolution)
- [ ] Encounter transitions (ward → ICU → ward)
- [ ] Pre-natal/delivery workflows
