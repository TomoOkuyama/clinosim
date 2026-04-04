# disease — Disease Definitions & Event Scheduling

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
├── schema/
│   └── disease_protocol.schema.yaml     ← YAML schema definition
├── protocols/
│   ├── bacterial_pneumonia.yaml          ← Phase 1
│   ├── heart_failure_exacerbation.yaml   ← Phase 1
│   ├── hip_fracture.yaml                 ← Phase 1
│   ├── pregnancy_complications/          ← Pregnancy-related conditions
│   │   ├── gestational_diabetes.yaml
│   │   ├── preeclampsia.yaml
│   │   ├── preterm_labor.yaml
│   │   ├── placenta_previa.yaml
│   │   ├── ectopic_pregnancy.yaml
│   │   └── postpartum_hemorrhage.yaml
│   ├── neonatal/                          ← Newborn conditions
│   │   ├── neonatal_jaundice.yaml
│   │   ├── respiratory_distress_syndrome.yaml
│   │   └── neonatal_sepsis.yaml
│   └── (future diseases)
├── complications/
│   └── hospital_complications.yaml       ← Cross-disease complications
└── (implementation files)
```

### YAML Protocol Schema

Every disease definition follows this schema:

```yaml
# === METADATA ===
disease_id: string                         # unique identifier
display_name:
  en: string
  ja: string
icd_codes:
  primary: string                          # most common ICD code
  variants: list[{code, name, probability}]  # alternative codes by specificity
category: enum[acute, chronic_exacerbation, surgical, emergency]

# === INCIDENCE MODEL ===
incidence:
  base_rate_per_100k_per_year:
    age_bands:                             # per 5-year age band
      "0-4": {M: float, F: float}
      "5-9": {M: float, F: float}
      ...
      "85+": {M: float, F: float}
  risk_multipliers:                        # applied to base rate
    - {condition: "diabetes", multiplier: 1.5}
    - {condition: "COPD", multiplier: 2.0}
    - {condition: "smoking_current", multiplier: 1.8}
    - ...
  seasonal_curve:                          # monthly multiplier (Jan=1, ..., Dec=12)
    1: 1.8    # January — peak
    2: 1.6
    3: 1.3
    4: 1.0
    5: 0.8
    6: 0.7    # summer trough
    7: 0.7
    8: 0.7
    9: 0.8
    10: 1.0
    11: 1.3
    12: 1.7
  time_of_day_distribution:                # hour → relative probability
    type: "uniform" | "peaked"
    peak_hours: [18, 19, 20, 21]           # if peaked
  day_of_week_modifier:
    monday: 1.2                            # delayed from weekend
    weekend: 0.8

# === SEVERITY MODEL ===
severity:
  distribution:
    mild: 0.30          # outpatient management possible
    moderate: 0.55      # requires hospitalization
    severe: 0.15        # requires ICU
  modifiers:
    - {condition: "age_over_75", severe_multiplier: 1.8}
    - {condition: "immunosuppressed", severe_multiplier: 2.5}
    - {condition: "COPD", moderate_multiplier: 1.3}

# === PRESENTING SYMPTOMS ===
presenting_symptoms:
  - {name: "fever", probability: 0.85, severity_range: [0.3, 0.9]}
  - {name: "cough", probability: 0.90, severity_range: [0.2, 0.8]}
  - {name: "dyspnea", probability: 0.60, severity_range: [0.2, 0.7]}
  - {name: "chest_pain", probability: 0.25, severity_range: [0.1, 0.5]}
  - {name: "sputum_production", probability: 0.70, severity_range: [0.2, 0.6]}
  - {name: "fatigue", probability: 0.75, severity_range: [0.3, 0.7]}

# === CLINICAL COURSE ARCHETYPES ===
course_archetypes:
  smooth_recovery:
    probability: 0.55
    description: "Steady improvement from Day 1–2 after treatment initiation"
    state_trajectory:
      inflammation_level:
        day_0: "{severity_to_inflammation}"    # function of severity
        day_1: "+0.05"                         # initial rise (lag)
        day_2: "-0.08"                         # improvement begins
        day_3: "-0.10"
        day_5: "-0.10"
        day_7: "-0.08"
        day_10: "-0.05"
        day_14: "-0.03"
      # Other state variables follow similar curves

  dip_then_recovery:
    probability: 0.20
    description: "Worsening Day 1–3, then gradual improvement"
    state_trajectory:
      inflammation_level:
        day_0: "{severity_to_inflammation}"
        day_1: "+0.10"                         # worsening
        day_2: "+0.05"                         # nadir
        day_3: "-0.02"                         # turning point
        day_5: "-0.08"
        day_7: "-0.10"
        day_10: "-0.08"
        day_14: "-0.05"

  plateau_then_recovery:
    probability: 0.10
    description: "No change for 3–5 days, then improvement"
    state_trajectory:
      inflammation_level:
        day_0: "{severity_to_inflammation}"
        day_1: "+0.03"
        day_3: "+0.00"                         # plateau
        day_5: "+0.00"
        day_7: "-0.08"                         # delayed improvement
        day_10: "-0.10"
        day_14: "-0.05"

  treatment_resistant:
    probability: 0.08
    description: "No response to first-line treatment; requires change"
    state_trajectory:
      inflammation_level:
        day_0: "{severity_to_inflammation}"
        day_1: "+0.08"
        day_3: "+0.05"                         # no improvement
        day_5: "+0.02"                         # triggers treatment change
        # After treatment change (day 5–7): new trajectory
        day_7: "-0.05"
        day_10: "-0.10"
        day_14: "-0.08"
    triggers:
      day_3_no_improvement:
        condition: "inflammation_level still > 0.5"
        action: "treatment_change_recommended"

  gradual_deterioration:
    probability: 0.05
    description: "Slow worsening despite treatment → ICU"
    state_trajectory:
      inflammation_level:
        day_0: "{severity_to_inflammation}"
        day_1: "+0.10"
        day_3: "+0.08"
        day_5: "+0.05"                         # ICU transfer likely
      perfusion_status:
        day_3: "-0.10"
        day_5: "-0.15"                         # shock developing

  sudden_deterioration:
    probability: 0.02
    description: "Sudden critical worsening (sepsis, PE, etc.)"
    state_trajectory:
      inflammation_level:
        day_0: "{severity_to_inflammation}"
        day_1: "-0.02"                         # appeared to improve
        day_2: "+0.30"                         # sudden spike
      perfusion_status:
        day_2: "-0.30"                         # shock
    triggers:
      sudden_event:
        condition: "perfusion_status < 0.4"
        action: "icu_transfer_immediate"

# Archetype selection modifiers (patient-dependent)
archetype_modifiers:
  - condition: "immune_reactivity < 0.3"
    effect: {treatment_resistant: "+0.10", smooth_recovery: "-0.10"}
  - condition: "age >= 80"
    effect: {gradual_deterioration: "+0.05", smooth_recovery: "-0.05"}
  - condition: "treatment_sensitivity > 1.2"
    effect: {smooth_recovery: "+0.10", treatment_resistant: "-0.05"}

# === INITIAL PHYSIOLOGICAL STATE IMPACT ===
initial_state_impact:
  # How this disease changes physiological state at onset (added to patient baseline)
  mild:
    inflammation_level: +0.25
    volume_status: -0.10        # mild dehydration from fever
  moderate:
    inflammation_level: +0.50
    volume_status: -0.20
    perfusion_status: -0.05
    renal_function: -0.05       # pre-renal from dehydration
  severe:
    inflammation_level: +0.75
    volume_status: -0.30
    perfusion_status: -0.20
    renal_function: -0.15
    ph_status: -0.10            # metabolic acidosis

# === DIAGNOSTIC PROTOCOL ===
diagnostic:
  # Initial differential diagnosis (prior probabilities)
  differential:
    - {disease: "bacterial_pneumonia", prior: 0.45}
    - {disease: "viral_pneumonia", prior: 0.15}
    - {disease: "influenza", prior: 0.10}
    - {disease: "heart_failure_pulmonary_edema", prior: 0.10}
    - {disease: "pulmonary_embolism", prior: 0.05}
    - {disease: "lung_cancer_with_obstruction", prior: 0.03}
    - {disease: "tuberculosis", prior: 0.02}
    - {disease: "other", prior: 0.10}

  # Likelihood ratios for key findings
  likelihood_ratios:
    chest_xray_consolidation:
      bacterial_pneumonia: {positive_LR: 8.0, negative_LR: 0.3}
      heart_failure: {positive_LR: 0.5, negative_LR: 1.2}
    procalcitonin_above_0.5:
      bacterial_pneumonia: {positive_LR: 6.0, negative_LR: 0.2}
      viral_pneumonia: {positive_LR: 0.3, negative_LR: 2.0}
    crp_above_100:
      bacterial_pneumonia: {positive_LR: 3.0, negative_LR: 0.4}
    blood_culture_positive:
      bacterial_pneumonia: {positive_LR: 15.0, negative_LR: 0.8}  # high specificity, low sensitivity
    urinary_antigen_positive:
      bacterial_pneumonia: {positive_LR: 20.0, negative_LR: 0.7}  # for pneumococcus/legionella

  confirmation_threshold: 0.90   # probability at which diagnosis is "confirmed"

  # Diagnosis name evolution over time
  diagnosis_progression:
    - {stage: "initial", code: "J18.9", name: "Pneumonia, unspecified"}
    - {stage: "after_xray", code: "J18.1", name: "Lobar pneumonia, unspecified"}
    - {stage: "after_culture", code: "J13", name: "Pneumonia due to Streptococcus pneumoniae"}

# === ORDER PROTOCOLS ===
order_protocols:
  admission_orders:
    labs:
      - {test: "CBC", code_loinc: "58410-2", code_jlac10: "2A010", urgency: "stat"}
      - {test: "CRP", code_loinc: "1988-5", code_jlac10: "5C070", urgency: "stat"}
      - {test: "Procalcitonin", code_loinc: "75241-0", urgency: "stat"}
      - {test: "BMP", code_loinc: "51990-0", urgency: "stat"}       # Na, K, Cl, CO2, BUN, Cr, Glucose
      - {test: "Blood_culture_x2", code_loinc: "600-7", urgency: "stat", note: "before antibiotics"}
      - {test: "Sputum_culture", code_loinc: "624-7", urgency: "routine"}
      - {test: "Urinary_antigen_pneumococcus", code_loinc: "31971-3", urgency: "stat"}
      - {test: "Urinary_antigen_legionella", code_loinc: "32167-7", urgency: "stat"}
    imaging:
      - {test: "Chest_Xray_PA_Lateral", code_cpt: "71046", urgency: "stat"}
    medications:
      first_line:
        japan: {drug: "ABPC/SBT", dose: "3g IV q6h", code_yj: "6131405", duration: "until_review_day3"}
        us: {drug: "Ceftriaxone + Azithromycin", dose: "1g IV daily + 500mg IV daily", duration: "until_review_day3"}
      alternative_penicillin_allergy:
        japan: {drug: "Levofloxacin", dose: "500mg IV daily"}
        us: {drug: "Levofloxacin", dose: "750mg IV daily"}
    supportive:
      - {type: "IV_fluid", detail: "NS or LR 80-125 mL/h, adjust for intake"}
      - {type: "O2", detail: "Nasal cannula to maintain SpO2 ≥ 94%"}
      - {type: "antipyretic", detail: "Acetaminophen 500mg PO q6h PRN for temp ≥ 38.5°C"}
      - {type: "DVT_prophylaxis", detail: "Enoxaparin 40mg SC daily (if no contraindication)"}
      - {type: "diet", detail: "Regular diet as tolerated; clear liquid if nauseous"}

  daily_monitoring:
    labs:
      - {test: "CRP", frequency: "daily", japan_modifier: 1.0, us_modifier: 0.5}  # US: every other day
      - {test: "CBC", frequency: "daily", japan_modifier: 1.0, us_modifier: 0.5}
      - {test: "BMP", frequency: "daily", japan_modifier: 1.0, us_modifier: 0.5}
    vitals:
      stable: "q4h"      # temp, HR, BP, RR, SpO2
      unstable: "q1h"
    imaging:
      - {test: "Chest_Xray", frequency: "day_3_and_prn", condition: "worsening or no improvement"}

  trigger_orders:
    no_defervescence_72h:
      condition: "max_temp ≥ 38.0°C on Day 3"
      actions:
        - {type: "lab", test: "Repeat_blood_culture_x2"}
        - {type: "imaging", test: "Chest_CT_with_contrast"}
        - {type: "medication_change", action: "escalate_antibiotic"}
        - {type: "consult", target: "infectious_disease"}
    spo2_below_90:
      condition: "SpO2 < 90% on supplemental O2"
      actions:
        - {type: "lab", test: "ABG"}
        - {type: "respiratory", action: "increase_O2_or_HFNC"}
        - {type: "evaluate", action: "consider_ICU_transfer"}
    renal_deterioration:
      condition: "Creatinine rise > 0.3 mg/dL from baseline"
      actions:
        - {type: "medication_change", action: "adjust_antibiotic_for_renal"}
        - {type: "fluid", action: "reassess_volume_status"}
    positive_culture:
      condition: "Blood culture returns positive (typically Day 2–3)"
      actions:
        - {type: "medication_change", action: "narrow_antibiotic_to_sensitivity"}

  discharge_protocol:
    criteria:
      japan:
        - "Afebrile (< 37.0°C) for 48 hours"
        - "CRP declining and < 50% of peak"
        - "Oral medication tolerated for 24 hours"
        - "Chest X-ray: no worsening (improvement not required)"
        - "SpO2 ≥ 95% on room air"
        - "ADL: independent or with available support"
      us:
        - "Afebrile (< 37.5°C) for 24 hours"
        - "Oral medication tolerated"
        - "Clinically stable (no escalation in 24h)"
        - "SpO2 ≥ 92% on room air (or baseline)"
        - "Discharge plan and follow-up arranged"
    discharge_medications:
      japan: {drug: "AMPC", dose: "250mg PO TID", duration: "5 days"}
      us: {drug: "Amoxicillin-Clavulanate", dose: "875/125mg PO BID", duration: "5 days"}
    follow_up:
      japan: {interval_days: 14, orders: ["Chest_Xray", "CRP", "CBC"]}
      us: {interval_days: 7, orders: ["Chest_Xray_if_indicated"]}

# === TARGET LENGTH OF STAY ===
target_los:
  japan:
    mild: null        # outpatient, no admission
    moderate: {mean: 14, sd: 4, min: 7, max: 28}
    severe: {mean: 21, sd: 7, min: 10, max: 45}    # includes ICU time
  us:
    mild: null
    moderate: {mean: 4.5, sd: 1.5, min: 2, max: 10}
    severe: {mean: 8, sd: 3, min: 4, max: 21}

# === DPC / DRG PARAMETERS ===
reimbursement:
  japan_dpc:
    dpc_code: "040080"     # 肺炎
    period_I_days: 4
    period_II_days: 11
    period_III_days: 30
  us_drg:
    drg_code: "193"        # Simple pneumonia with MCC
    geometric_mean_los: 4.8
    outlier_threshold_days: 14

# === COMPLICATION RULES ===
complications:
  - name: "parapneumonic_effusion"
    probability_per_day: 0.02
    risk_factors: [{condition: "severity_severe", multiplier: 3.0}]
    onset_day_range: [2, 7]
    detection: {test: "Chest_Xray", finding: "pleural_effusion"}
    action: "consider_thoracentesis"

  - name: "empyema"
    probability_given_effusion: 0.15
    onset_day_range: [3, 10]
    action: "chest_tube_drainage"

  - name: "c_diff_colitis"
    probability_per_day: 0.005
    risk_factors:
      - {condition: "antibiotic_duration_over_7_days", multiplier: 2.0}
      - {condition: "age_over_65", multiplier: 1.5}
    onset_day_range: [5, 21]
    detection: {test: "C_diff_toxin", finding: "positive"}
    action: "start_metronidazole_or_vancomycin_oral"

# === READMISSION MODEL ===
readmission:
  thirty_day_rate: 0.17   # 15–20%
  risk_factors:
    - {factor: "age_over_75", additional_risk: 0.05}
    - {factor: "COPD", additional_risk: 0.08}
    - {factor: "heart_failure", additional_risk: 0.06}
    - {factor: "early_discharge_us", additional_risk: 0.04}
    - {factor: "low_health_literacy", additional_risk: 0.03}
  readmission_reasons:
    - {reason: "recurrent_pneumonia", probability: 0.40}
    - {reason: "different_infection", probability: 0.20}
    - {reason: "heart_failure_exacerbation", probability: 0.15}
    - {reason: "adverse_drug_reaction", probability: 0.10}
    - {reason: "other", probability: 0.15}
```

---

### Severity Determination Algorithm

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
- `discharge_protocol` → provides discharge criteria for encounter's discharge evaluation

### → diagnosis
- `diagnostic.differential` → initial prior probabilities for Bayesian engine
- `diagnostic.likelihood_ratios` → LR table consumed by diagnosis module
- `diagnostic.diagnosis_progression` → how the diagnosis code evolves over time

### → clinical_course
- `course_archetypes` with `state_trajectory` → drives the `StateChangeDirective` generation
- `archetype_modifiers` → modified by patient's physiological profile
- `trigger_orders` conditions → may trigger treatment changes during daily evaluation

### → treatment
- `order_protocols.admission_orders.medications` → first-line and alternative drugs
- `trigger_orders.medication_change` → escalation/de-escalation logic
- `discharge_protocol.discharge_medications` → oral switch for discharge

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
