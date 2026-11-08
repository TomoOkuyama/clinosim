# disease — Disease Definitions & Event Scheduling

> **Status: design document.** Parts of this file are the original design
> and describe more than the code implements. The implemented API, files
> and consumers are in [`README.md`](README.md). The schema of a disease
> YAML is the `DiseaseProtocol` Pydantic model in `protocol.py`
> (`extra="forbid"`). Symbols named only here — `DiseaseEvent`,
> `ChronicManagementProtocol`, `SeasonalConditionProfile`,
> `ComplicationCascade`, `get_monthly_incidence` — do not exist.

## Purpose
Manage per-disease definitions as structured YAML data: incidence model, severity distribution, clinical course archetypes, lab/treatment protocols, complication rules, and discharge criteria. Provides protocol definitions consumed by encounter, diagnosis, treatment, order, observation, and clinical_course modules.

## Inputs
- `PatientProfile`: Patient attributes (age, comorbidities, risk factors, physiological profile)
- `HealthcareSystemConfig`: Country-specific parameters (lab frequency multiplier, target LOS, etc.)
- `LifeEvent`: The triggering event from the population module

## Outputs
- `DiseaseEvent`: Onset event with disease type, severity, archetype, presenting symptoms
- `DiseaseProtocol`: Complete protocol definition for the encounter duration
- `ChronicManagementProtocol`: Outpatient management protocol for chronic conditions (visit interval, routine labs, medication renewal rules)
- `SeasonalConditionProfile`: Seasonal symptom patterns for allergic/chronic conditions
- `ComplicationCascade`: Secondary event rules applicable during hospitalization

## Dependencies
- `patient` (risk factors adjust severity, archetype selection)
- `healthcare_system` (country-specific protocol parameters)
- `population` (incidence rates used by life event engine)

---

## Internal Design

### Folder structure

```
modules/disease/
├── SPEC.md
├── README.md / README.ja.md
├── __init__.py                          ← empty
├── protocol.py                          ← DiseaseProtocol Pydantic model (extra="forbid") + loaders + import-time validators
├── severity.py                          ← severity categories / score ranges / sampler / modifier vocabulary
├── acuity.py                            ← acuity-tier canonical disease sets
├── localization.py                      ← country → YAML key, chief complaint, department, target LOS
└── reference_data/
    └── <disease_id>.yaml                ← 36 flat files, one per disease (e.g. bacterial_pneumonia.yaml,
                                            heart_failure_exacerbation.yaml, hip_fracture.yaml)
```

There is no separate schema YAML: the schema is the `DiseaseProtocol`
Pydantic model in `protocol.py`. There are no `pregnancy_complications/`,
`neonatal/` or `complications/` sub-directories; the pregnancy and neonatal
protocol tables below are design targets that are not implemented as
disease YAMLs (perinatal delivery / newborn / abortion encounters are driven
by `clinosim/locale/shared/perinatal.yaml` instead).

### YAML Protocol Schema

The source of truth for a disease YAML is the `DiseaseProtocol` Pydantic
model in `protocol.py` (`extra="forbid"`: an unknown top-level key fails
the load). The loader drops the `metadata:` header block before
validation. Required keys are `disease_id`, `icd_codes`, `incidence` and
`severity`; every other block is optional. Below is a trimmed copy of
`reference_data/bacterial_pneumonia.yaml` (`…` marks removed entries):

```yaml
metadata: {kind: protocol, name: bacterial_pneumonia, source: clinosim}

disease_id: bacterial_pneumonia
chief_complaint: {en: "Fever, cough, dyspnea", ja: "発熱・咳嗽・呼吸困難"}
department: pulmonology
encounter_type: medical          # "medical" | "surgical" | "trauma"
requires_surgery: false
readmission_eligible: true

icd_codes:
  primary: "J18.9"
  variants:
    - {code: "J13", name: "Pneumonia due to Streptococcus pneumoniae", probability: 0.25}
    - …

# Incidence per 100,000 per year, by locale → age band → sex
incidence:
  japan:
    "0-4":   {M: 800, F: 600}
    …
    "85+":   {M: 2500, F: 2000}
  us:
    "0-4":   {M: 900, F: 700}
    …
  risk_multipliers:
    - {condition: "COPD", multiplier: 3.0}
    - …
  seasonal_curve: {1: 1.8, 2: 1.6, 3: 1.3, 4: 1.0, 5: 0.8, 6: 0.7, 7: 0.7, 8: 0.7, 9: 0.8, 10: 1.0, 11: 1.3, 12: 1.7}
  vaccine_protection:
    pneumococcal: {effectiveness: 0.45, duration_days: 1825}
    …

severity:
  distribution: {mild: 0.30, moderate: 0.55, severe: 0.15}
  modifiers:                       # condition names must be in KNOWN_MODIFIER_CONDITIONS
    - {condition: "age_over_75", mild_multiplier: 0.6, severe_multiplier: 1.8}
    - …

initial_state_impact:              # state deltas at onset, per severity (canonical state vars only)
  moderate:
    oxygenation_impairment: 0.16
    inflammation_level: 0.50
    volume_status: -0.20
    …

order_protocols:
  admission_orders:
    labs:       [{test: CRP, urgency: stat}, …]
    imaging:    [{test: Chest_Xray_PA_Lateral, urgency: stat}]
    supportive: [{type: IV_fluid, detail: "NS 80-125 mL/h"}, …]
  daily_monitoring:
    labs:   [{test: CRP, frequency: daily}, …]
    vitals: {stable: q4h, unstable: q1h}
  trigger_orders:
    spo2_below_90:
      condition: "SpO2 < 90% on supplemental O2"
      actions: [{type: lab, test: ABG}, …]
  discharge_criteria:
    japan: ["Afebrile (< 37.0C) for 48 hours", …]
    us: […]

likelihood_ratios:                 # some YAMLs nest this under `diagnostic:` instead
  chest_xray_consolidation:
    bacterial_pneumonia: {positive_LR: 8.0, negative_LR: 0.3}
    …

expected_lab_distributions:
  admission:
    CRP: {unit: mg/L, median: 80, iqr: [30, 150], range: [5, 400]}
    …

drugs:                             # blocks per role, then per locale
  first_line:
    japan:
      - drug_id: ampicillin_sulbactam
        dose: "3g IV q6h"
        route: IV
        renal_adjustment: {eGFR_30_60: "1.5g IV q6h", eGFR_below_30: "1.5g IV q12h"}
        pregnancy_safe: true
    us: […]
  alternative_penicillin_allergy: {_indication_tag: antimicrobial_penicillin_class, japan: […], us: […]}
  escalation: {…}
  discharge_oral: {…}

target_los:
  japan: {mild: {mean: …}, moderate: {mean: 14, sd: 4, min: 8, max: 25}, severe: {…}}
  us:    {mild: {…}, moderate: {mean: 5, sd: 2, min: 3, max: 8}, severe: {…}}

imaging_orders:                    # ImagingOrderSpec
  - {modality: CR, body_site: chest, views: [PA], urgency: routine, clinical_indication: "…", day: 0}

outcome_benchmarks:
  japan: {median_los: 14, los_iqr: [10, 18], in_hospital_mortality: 0.07, thirty_day_readmission: 0.17, …}
  us: {…}

course_archetypes:                 # archetype → probability + per-day state deltas
  smooth_recovery:
    probability: 0.61
    description: "Steady improvement from Day 1-2 after treatment initiation"
    trajectory:                    # state var → {day: delta}
      inflammation_level: {0: 0.05, 1: -0.02, 2: -0.08, 3: -0.08, 5: -0.06, 7: -0.06, 10: -0.04, 14: -0.02}
      …
    order_modifications: {}
    treatment_modifications: {}
    daily_trajectory:              # DailyTrajectoryEntry per day (SOAP seeds)
      day_0: {subjective: "…", objective: "…", assessment: "…", plan: "…"}
  dip_then_recovery: {…}
  # also: plateau_then_recovery, treatment_resistant, gradual_deterioration, sudden_deterioration

archetype_modifiers:
  - {condition: "immune_reactivity < 0.3", effect: {treatment_resistant: …, smooth_recovery: …}}

complications:
  - name: parapneumonic_effusion
    probability_per_day: 0.008
    onset_day_range: [2, 7]
    risk_factors: [{condition: severity_severe, multiplier: 3.0}, …]
    state_impact: {volume_status: 0.05, inflammation_level: 0.03}
    detection: {test: chest_xray, finding: pleural_effusion}
    actions: [order_chest_xray, consider_thoracentesis]
    cascade: [empyema]

narrative:                         # NarrativeSpec
  hpi_template: {onset_pattern: {mild: "…", moderate: "…", severe: "…"}, trigger_options: […]}
  physical_exam_findings: {smooth_recovery: {day_0: …, day_3: …}}
  discharge_instructions: {follow_up: {en: "…", ja: "…"}, …}

implied_chronic_codes: ["J44"]
drug_interactions:
  - {drug_a: Levofloxacin, drug_b: Warfarin, severity: major, effect: "…", action: "…"}
```

Other optional `DiseaseProtocol` fields used by some YAMLs:
`presenting_symptoms`, `diagnostic` (`differential`, `likelihood_ratios`,
`diagnosis_progression`, `confirmation_threshold`, `diagnostic_difficulty`),
`expected_vital_distributions`, `sequela_code`, `minimum_severity`,
`state_based_discharge`, `admission_route` (`emergency` | `elective`),
`procedure`, `medication_holds`, `causes_myocardial_injury`, `causes_vte`,
`acid_base_type`, `chronic_glycemic_control`. There are no `display_name`,
`category`, `reimbursement` (DPC / DRG) or `readmission` blocks;
readmission is driven by `readmission_eligible` and the simulator.

---

### Severity Determination Algorithm

Design pseudocode. Implemented by `severity.py::sample_severity` /
`sample_severity_category` (adds a `minimum_severity` clamp and the
fail-loud modifier vocabulary `KNOWN_MODIFIER_CONDITIONS`).

```python
def determine_severity(patient: PatientProfile, disease_protocol: dict) -> str:
    base_dist = disease_protocol["severity"]["distribution"]  # {mild: 0.30, moderate: 0.55, severe: 0.15}
    
    # Apply patient-specific modifiers
    adjusted = base_dist.copy()
    for modifier in disease_protocol["severity"]["modifiers"]:
        if evaluate_condition(modifier["condition"], patient):
            for key in ["mild_multiplier", "moderate_multiplier", "severe_multiplier"]:
                if key in modifier:
                    level = key.split("_")[0]
                    adjusted[level] *= modifier[key]
    
    # Normalize
    total = sum(adjusted.values())
    adjusted = {k: v / total for k, v in adjusted.items()}
    
    return weighted_choice(adjusted)
```

### Archetype Selection Algorithm

Design pseudocode. Implemented by
`clinosim/modules/clinical_course/engine.py::select_archetype`, which
also adjusts `mild` severity and reads its multipliers from named
constants rather than the literals shown here.

```python
def select_archetype(patient: PatientProfile, severity: str, disease_protocol: dict) -> str:
    base_probs = {a["name"]: a["probability"] for a in disease_protocol["course_archetypes"]}
    
    # Apply patient-specific modifiers
    for modifier in disease_protocol["archetype_modifiers"]:
        if evaluate_condition(modifier["condition"], patient):
            for archetype, delta in modifier["effect"].items():
                base_probs[archetype] = max(0, base_probs[archetype] + delta)
    
    # Severity adjustment: severe patients more likely to deteriorate
    if severity == "severe":
        base_probs["gradual_deterioration"] *= 2.0
        base_probs["sudden_deterioration"] *= 2.0
        base_probs["smooth_recovery"] *= 0.6
    
    # Normalize and select
    total = sum(base_probs.values())
    base_probs = {k: v / total for k, v in base_probs.items()}
    return weighted_choice(base_probs)
```

### State Trajectory Interpolation

Design pseudocode. Implemented by
`clinosim/modules/clinical_course/engine.py::_interpolate`.

The archetype defines state changes at specific day markers. Between markers, values are interpolated:

```python
def interpolate_state_trajectory(archetype_trajectory: dict, current_day: float, 
                                  patient_profile: PatientPhysiologicalProfile) -> dict:
    """
    Returns state variable deltas for the current day.
    Archetype provides daily deltas at key days; interpolate for in-between days.
    Patient profile modulates amplitude.
    """
    deltas = {}
    for variable, day_map in archetype_trajectory.items():
        # Find surrounding key days
        days = sorted(day_map.keys())
        before = max(d for d in days if d <= current_day)
        after = min((d for d in days if d > current_day), default=before)
        
        if before == after:
            delta = day_map[before]
        else:
            # Linear interpolation
            frac = (current_day - before) / (after - before)
            delta = day_map[before] * (1 - frac) + day_map[after] * frac
        
        # Patient modulation
        if variable == "inflammation_level":
            delta *= patient_profile.immune_reactivity  # high reactivity → bigger swings
        if "function" in variable:
            delta *= (1 / patient_profile.treatment_sensitivity)  # high sensitivity → faster recovery
        
        deltas[variable] = delta
    
    return deltas
```

### Incidence Rate Interface with Population Module

Design pseudocode — there is no `get_monthly_incidence` function. The
population module derives monthly disease rates itself from locale
epidemiology data
(`clinosim/modules/population/_demographics.py::_disease_monthly_rate_from_locale`).

The disease module provides incidence data to the population module's life event engine:

```python
def get_monthly_incidence(disease_id: str, person: PersonRecord, month: int) -> float:
    protocol = load_protocol(disease_id)
    
    # Base rate for age/sex band
    age_band = get_age_band(person.age)
    base_rate = protocol["incidence"]["base_rate_per_100k_per_year"][age_band][person.sex]
    
    # Risk multipliers from comorbidities
    for multiplier in protocol["incidence"]["risk_multipliers"]:
        if multiplier["condition"] in person.chronic_conditions:
            base_rate *= multiplier["multiplier"]
    
    # Vaccination protection
    for vax in person.vaccination_history:
        if vax.vaccine in protocol.get("vaccine_protection", {}):
            protection = protocol["vaccine_protection"][vax.vaccine]
            days_since = (current_date - vax.date).days
            if days_since < protection["duration_days"]:
                base_rate *= (1 - protection["effectiveness"])  # e.g., ×0.4 for 60% effective vaccine
    
    # Mental health modifiers
    if "alcohol_dependence" in person.mental_health_conditions:
        base_rate *= 1.5  # increased infection risk
    if "depression" in person.mental_health_conditions:
        base_rate *= 1.2  # immune suppression, delayed care seeking
    
    # Lifestyle compliance effect on chronic exacerbation
    if disease_id in chronic_exacerbation_diseases:
        diet_factor = 1.0 + (1.0 - person.diet_compliance) * 0.3   # poor diet → more exacerbations
        adherence_factor = 1.0 + (1.0 - person.adherence_effective_rate) * 0.5  # poor adherence → more exacerbations
        base_rate *= diet_factor * adherence_factor
    
    # Frailty modifier (frail patients get sicker more easily)
    if person.frailty_index > 0.3:
        base_rate *= 1.0 + person.frailty_index  # e.g., frailty 0.5 → ×1.5
    
    # Seasonal modifier
    seasonal = protocol["incidence"]["seasonal_curve"][month]
    
    # Convert annual rate to monthly
    monthly_rate = (base_rate / 100_000) * seasonal / 12
    
    return monthly_rate
```

---

### Cross-Module Impact Notes

### → encounter
The disease protocol's `order_protocols` define what the encounter module orders at each stage:
- `admission_orders` → placed when encounter enters ADMISSION state
- `daily_monitoring` → drives the daily cycle's morning labs and vitals frequency
- `trigger_orders` → evaluated during morning rounds; if condition met, orders are placed
- `discharge_criteria` → provides discharge criteria for encounter's discharge evaluation

### → diagnosis
- `diagnostic.differential` → initial prior probabilities for Bayesian engine
- `diagnostic.likelihood_ratios` → LR table consumed by diagnosis module
- `diagnostic.diagnosis_progression` → how the diagnosis code evolves over time

### → clinical_course
- `course_archetypes` with `trajectory` → drives the `StateChangeDirective` generation
- `archetype_modifiers` → modified by patient's physiological profile
- `trigger_orders` conditions → may trigger treatment changes during daily evaluation

### → treatment
- `drugs.first_line` / `drugs.alternative_*` → first-line and alternative drugs
- `drugs.escalation` → escalation / de-escalation drugs
- `drugs.discharge_oral` → oral switch for discharge

### → observation
- The state trajectory defines how state variables change → observation module converts these to lab values
- Lab ordering frequency affects how many data points are generated

### → population
- `incidence` model → consumed by population's life event engine
- `readmission` model → after discharge, readmission event may be generated

---

### → patient (pregnancy)
- Pregnancy physiological adjustments (increased HR, lower BP in 2nd trimester, physiological anemia) are applied by the patient module at Layer 2 activation
- Drug contraindications in pregnancy are enforced by the treatment module using pregnancy state

### Pregnancy Complication Protocols

Pregnancy complications follow the same YAML protocol schema but are **triggered by pregnancy state** rather than by population-level incidence:

| Complication | Incidence | Risk factors | Gestational age | Hospital encounter |
|---|---|---|---|---|
| Gestational diabetes (GDM) | 5–10% of pregnancies | Obesity, age > 35, family hx DM, prior GDM | Screened at 24–28 weeks | Outpatient management; diet → metformin → insulin if needed |
| Preeclampsia | 3–5% | Primipara, age > 35, chronic HT, obesity, multiple pregnancy | > 20 weeks | Admission if severe; delivery if > 37 weeks |
| Preterm labor | 5–10% | Prior preterm, cervical insufficiency, infection, multiple pregnancy | 22–37 weeks | Emergency admission; tocolytics, steroids (< 34 weeks) |
| Placenta previa | 0.3–0.5% | Prior cesarean, prior previa, multiple pregnancy | Detected at 20-week US | Admission if bleeding; planned cesarean at 36–37 weeks |
| Ectopic pregnancy | 1–2% of pregnancies | Prior ectopic, PID, IUD, tubal surgery | 4–10 weeks | Emergency; surgical or medical (methotrexate) |
| Postpartum hemorrhage | 3–5% of deliveries | Uterine atony, retained placenta, coagulopathy | Delivery/postpartum | Emergency; uterotonics, transfusion, surgery |
| Hyperemesis gravidarum | 0.3–2% | First pregnancy, multiple, molar pregnancy | 6–20 weeks | Admission for dehydration if severe |

Each complication is checked monthly during the population module's pregnancy event processing. If triggered, it generates the appropriate encounter type.

### Neonatal Condition Protocols

| Condition | Incidence | Risk factors | Timing | Encounter |
|---|---|---|---|---|
| Neonatal jaundice | 60% of neonates (visible), 5–10% requiring treatment | Preterm, ABO incompatibility, breastfeeding | Day 2–5 | Phototherapy; readmission if post-discharge |
| Respiratory distress syndrome | 1% of all; 30% of < 34 weeks | Preterm, no antenatal steroids | Birth–24h | NICU; surfactant therapy |
| Neonatal sepsis | 1–5 per 1000 live births | Preterm, maternal GBS+, prolonged rupture of membranes | Day 0–28 | NICU; IV antibiotics |
| Neonatal abstinence syndrome | Rare in JP; 7 per 1000 US | Maternal opioid use | Day 1–5 | NICU; symptom management |

## Open Questions
- [ ] Phase 2 disease priority order (global open #21)
- [ ] Epidemic/outbreak modeling (influenza year-to-year variability)
- [ ] How to express archetype state trajectories for diseases with fundamentally different patterns (e.g., surgical: pre-op stable → surgery → acute post-op → recovery)
- [ ] Multi-pathogen pneumonia: how to handle pathogen-specific trajectories (S. pneumoniae vs. Legionella vs. atypical)
- [ ] Heart failure and hip fracture protocols: need same level of detail as pneumonia
- [ ] Pregnancy complication protocols: need full YAML detail level (same as pneumonia)
- [ ] Neonatal physiology model: separate from adult model (different vital sign ranges, different lab normals)

## Design Notes
- Adding a new disease = creating a new YAML protocol file. No code changes required if the schema is followed.
- The pneumonia protocol above is the reference implementation. Heart failure and hip fracture will follow the same schema with disease-specific content.
- State trajectory deltas are additive to the current state, not absolute values. This allows the patient's baseline (from chronic conditions) to be preserved.
- The trigger system allows clinical decision points to be data-driven: "Day 3 no improvement → change antibiotic" is defined in YAML, not hardcoded.
