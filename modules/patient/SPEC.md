# patient — Layer 1→2 Activation & Clinical Detail

## Purpose
Activate a person from the population registry (Layer 1) into a full clinical patient profile (Layer 2) when they visit the hospital. Generates hidden physiological parameters, detailed medical history, baseline vitals, and all attributes needed for clinical simulation. Also handles reactivation of returning patients (preserving prior data).

## Inputs
- `PersonRecord`: Lightweight Layer 1 record from the population module
- `Household`: Household context (family medical history becomes real, not generated)
- `LifeEvent`: The event that triggered the hospital visit
- `ReferralContext`: If referred from a clinic, prior findings and medications
- `HealthcareSystemConfig`: Country-specific clinical norms
- Prior `PatientProfile` (if this person has visited before — reactivation)

## Outputs
- `PatientProfile`: Full clinical profile (Layer 2)

## Dependencies
- `population` (provides Layer 1 person record and household context)
- `healthcare_system` (country-specific clinical norms)

---

## Internal Design

### Activation Flow

```
PersonRecord (Layer 1)
  │
  ├── First visit? ──→ Full activation (generate everything)
  │
  └── Returning? ──→ Reactivation (load prior profile, update age-related changes)
```

### Full Activation Algorithm (first hospital visit)

```
Input: PersonRecord, Household, LifeEvent, ReferralContext?, HealthcareSystemConfig

=== Step 1: Carry over Layer 1 fields ===
Copy all demographic fields directly from PersonRecord:
  person_id, age, sex, date_of_birth, blood_type, rh_factor,
  employment_status, insurance_type, health_literacy,
  care_seeking_threshold, checkup_compliance, checkup_type

=== Step 2: Generate physical attributes ===
height_cm, weight_kg, bmi = generate_body_metrics(age, sex, country)
  # See body metrics model below

=== Step 3: Expand chronic conditions to clinical detail ===
For each ICD code in PersonRecord.chronic_conditions:
  expand to ChronicCondition:
    - onset_date: estimate based on age and typical onset age for disease
    - severity: sample from distribution (mild/moderate/severe), weighted by duration
    - controlled: probability based on health_literacy × medication_adherence
    - current_medications: assign guideline-based medications for condition + severity
    - latest_lab_values: generate plausible chronic-state lab values (e.g., HbA1c for DM)

=== Step 4: Generate allergy profile ===
allergy_count ~ Poisson(λ=0.3)  # most people have 0, some have 1–2
For each allergy:
  substance: weighted sample from common allergens (penicillin 30%, sulfa 15%, NSAIDs 10%, ...)
  reaction_type: weighted by substance
  severity: mild 60%, moderate 30%, severe 10%

=== Step 5: Build family history from household ===
For each household member with known chronic conditions:
  If relationship is parent, sibling, grandparent:
    add FamilyHistoryItem(condition, relationship, age_at_onset)
# This is REAL family history, not randomly generated — a key realism advantage

=== Step 6: Generate PatientPhysiologicalProfile ===
See "Physiological Profile Generation" below

=== Step 7: Derive baseline vitals ===
See "Baseline Vitals Derivation" below

=== Step 8: Incorporate referral data ===
If ReferralContext provided:
  - Import prior_findings as part of medical history
  - Import prior_medications into current_medications
  - Referral reason informs initial diagnostic context

=== Step 9: Generate prior hospital history (if seeded) ===
If PersonRecord.has_visited_hospital and historical records exist:
  - Load minimal records from population's historical seeding
  - These become the patient's "prior encounters" list

Output: PatientProfile
```

### Reactivation Algorithm (returning patient)

```
Input: PersonRecord (updated), prior PatientProfile, LifeEvent

1. Load prior PatientProfile
2. Update age (may have changed since last visit)
3. Update chronic_conditions:
   - Check if population module added new conditions since last visit
   - Progress existing conditions if population flagged progression
   - Update medication list accordingly
4. Update employment_status, insurance_type (may change with age/events)
5. Recalculate age-dependent physiological parameters:
   - renal_reserve, cardiac_reserve, hepatic_reserve: decay with age
   - delirium_susceptibility: increases with age
6. Keep physiological_profile base values stable (constitution doesn't change)
7. Keep allergy profile (allergies are permanent)
8. Append prior encounters to history

Output: Updated PatientProfile (same person_id, accumulated history)
```

---

### Physiological Profile Generation

The `PatientPhysiologicalProfile` represents a person's hidden constitution. Generated once at first activation, stable across visits (except age-related decay).

```python
def generate_physiological_profile(age, sex, chronic_conditions, household):

    # Base distributions
    immune_reactivity = Beta(5, 5).sample()  # centered at 0.5
    
    # Adjust for conditions: autoimmune → higher, immunosuppressed → lower
    if has_condition("rheumatoid_arthritis") or has_condition("lupus"):
        immune_reactivity = clamp(immune_reactivity + 0.15, 0, 1)
    if has_condition("HIV") or on_immunosuppressants:
        immune_reactivity = clamp(immune_reactivity - 0.2, 0, 1)

    # Drug metabolism — discrete categories with ethnic variation
    # JP: poor 15%, normal 65%, rapid 15%, ultra_rapid 5% (CYP2C19 different from Caucasian)
    # US Caucasian: poor 7%, normal 70%, rapid 15%, ultra_rapid 8%
    drug_metabolism_rate = weighted_choice(country_specific_distribution)

    # Organ reserves — decline with age
    # Base: Beta(8, 2) → mean 0.8, right-skewed (most people have good reserve)
    # Age adjustment: -0.005 per year over 40
    age_penalty = max(0, (age - 40) * 0.005)
    
    renal_reserve = clamp(Beta(8, 2).sample() - age_penalty, 0.1, 1.0)
    cardiac_reserve = clamp(Beta(8, 2).sample() - age_penalty, 0.1, 1.0)
    hepatic_reserve = clamp(Beta(8, 2).sample() - age_penalty * 0.7, 0.1, 1.0)  # liver more resilient

    # Condition-specific adjustments
    if has_condition("CKD"):
        renal_reserve *= 0.6  # already impaired
    if has_condition("heart_failure"):
        cardiac_reserve *= 0.5
    if has_condition("cirrhosis"):
        hepatic_reserve *= 0.4

    # Treatment sensitivity
    treatment_sensitivity = Normal(1.0, 0.15).sample()  # most people respond normally

    # Symptom reporting bias — correlates with health_literacy and sex
    base_bias = Normal(1.0, 0.25).sample()
    if sex == "F":
        base_bias *= 1.05  # slight tendency to report more (literature-supported)
    if health_literacy < 0.3:
        base_bias *= Normal(1.0, 0.15).sample()  # more variable, not systematically higher/lower
    symptom_reporting_bias = base_bias

    # Complication susceptibilities — increase with age and specific risk factors
    delirium_base = Beta(2, 8).sample()  # mean 0.2, most people low risk
    if age >= 75: delirium_base = clamp(delirium_base + 0.15, 0, 1)
    if age >= 85: delirium_base = clamp(delirium_base + 0.15, 0, 1)
    if has_condition("dementia"): delirium_base = clamp(delirium_base + 0.3, 0, 1)
    delirium_susceptibility = delirium_base

    dvt_base = Beta(2, 8).sample()
    if age >= 70: dvt_base = clamp(dvt_base + 0.1, 0, 1)
    if has_condition("prior_DVT"): dvt_base = clamp(dvt_base + 0.3, 0, 1)
    if bmi >= 30: dvt_base = clamp(dvt_base + 0.1, 0, 1)
    dvt_susceptibility = dvt_base

    return PatientPhysiologicalProfile(...)
```

### Body Metrics Model

Height and weight are correlated with age, sex, and country:

```python
def generate_body_metrics(age, sex, country):
    if country == "JP":
        if sex == "M":
            height = Normal(170.0, 5.5).sample()    # cm, adult mean
            bmi = Normal(23.5, 3.5).sample()         # JP male mean BMI
        else:
            height = Normal(157.5, 5.0).sample()
            bmi = Normal(22.0, 3.5).sample()
        # Elderly height loss: -0.5cm per decade after 60
        if age > 60:
            height -= (age - 60) / 10 * 0.5
    elif country == "US":
        if sex == "M":
            height = Normal(175.5, 7.0).sample()
            bmi = Normal(29.0, 6.0).sample()         # US male mean BMI (higher)
        else:
            height = Normal(162.0, 6.5).sample()
            bmi = Normal(29.5, 7.0).sample()
        if age > 60:
            height -= (age - 60) / 10 * 0.5

    bmi = clamp(bmi, 15.0, 50.0)
    weight = bmi * (height / 100) ** 2
    return height, weight, bmi
```

### Baseline Vitals Derivation

A person's "healthy normal" vital signs. Disease-state vitals are generated by the physiology module; these are the values this person would have when well.

```python
def derive_baseline_vitals(age, sex, bmi, chronic_conditions):
    
    # Temperature: remarkably stable across demographics
    temperature = Normal(36.4, 0.2).sample()  # °C
    if age >= 75:
        temperature -= 0.2  # elderly run slightly cooler
    
    # Heart rate
    hr_base = 72 if sex == "M" else 78  # women slightly higher
    hr = Normal(hr_base, 8).sample()
    if has_condition("atrial_fibrillation"):
        hr = Normal(85, 15).sample()  # higher, more variable
    if on_beta_blocker:
        hr -= 10
    
    # Blood pressure — strongly age and condition dependent
    sbp_base = 110 + (age - 30) * 0.5 if age > 30 else 110
    dbp_base = 70 + (age - 30) * 0.2 if age > 30 else 70
    sbp = Normal(sbp_base, 10).sample()
    dbp = Normal(dbp_base, 7).sample()
    if has_condition("hypertension"):
        if condition_controlled("hypertension"):
            sbp += 5   # controlled but slightly above normal
            dbp += 3
        else:
            sbp += 20  # uncontrolled
            dbp += 10
    
    # Respiratory rate: very stable
    rr = Normal(16, 2).sample()
    if has_condition("COPD"):
        rr = Normal(20, 3).sample()
    
    # SpO2
    spo2 = Normal(97.5, 1.0).sample()
    spo2 = clamp(spo2, 93, 100)
    if has_condition("COPD"):
        spo2 = Normal(94, 2.0).sample()
        spo2 = clamp(spo2, 88, 99)
    if age >= 80:
        spo2 -= 0.5  # slight age-related decrease
    
    return BaselineVitals(temperature, hr, sbp, dbp, rr, spo2)
```

### Pregnancy Physiological Adjustments

When a pregnant woman is activated to Layer 2, her baseline values and physiological profile must reflect pregnancy-related changes. These are gestational-age-dependent:

```python
def apply_pregnancy_adjustments(baseline: BaselineVitals, profile: PatientPhysiologicalProfile,
                                 pregnancy: PregnancyState):
    ga = pregnancy.gestational_age_weeks
    
    # Cardiovascular: increased cardiac output, lower BP in 2nd trimester
    if 14 <= ga <= 28:
        baseline.systolic_bp -= 5    # nadir in 2nd trimester
        baseline.diastolic_bp -= 10
    elif ga > 28:
        baseline.systolic_bp += 0    # returns toward baseline
        baseline.diastolic_bp += 0
    baseline.heart_rate += int(ga * 0.4)  # gradual increase, ~+15 bpm at term
    
    # Hematological: physiological anemia of pregnancy
    # Hb drops from ~13 to ~11 g/dL (hemodilution)
    profile._pregnancy_anemia_offset = min(ga / 40 * 0.15, 0.15)  # anemia_level adjustment
    
    # Renal: increased GFR (~50% increase), lower creatinine
    profile._pregnancy_renal_boost = min(ga / 28 * 0.1, 0.1)  # renal_function adjustment
    
    # Respiratory: progesterone-driven hyperventilation, slightly lower PaCO2
    baseline.respiratory_rate += 2  # mild tachypnea
    
    # Lab value implications (handled by observation module):
    # - WBC: mildly elevated (10,000–15,000 is normal in pregnancy)
    # - Albumin: lower (hemodilution)
    # - Alkaline phosphatase: elevated (placental origin)
    # - D-dimer: elevated (cannot use for PE diagnosis in pregnancy)
    # - TSH: lower in 1st trimester (hCG effect)
```

Drug contraindications in pregnancy are handled by the treatment module:
- Pregnancy category checks (many drugs contraindicated: ACE-I, warfarin, statins, methotrexate)
- Dose adjustments for increased GFR
- Anesthesia considerations for cesarean section

### Pediatric patient activation

When a child (age < 18) is activated to Layer 2:
- `baseline_vitals`: Use age-appropriate ranges from `physiology.get_baseline_vitals_pediatric(age, sex)`
- `body_metrics`: Use pediatric growth charts (JP: 乳幼児身体発育曲線; US: CDC growth charts)
- `physiological_profile`: Organ reserves are typically 1.0 (children have high reserves)
- `allergy_profile`: Drug allergies less common; food allergies more common (egg, milk, wheat, peanut)
- `medications`: Weight-based dosing (mg/kg), formulation preference (liquid < 6y, tablet/capsule > 8y)
- `guardian_required`: True — all decisions through parent/caregiver from household
- `vaccination_history`: Critical — JP/US vaccination schedules generate many outpatient encounters in first 2 years

### Newborn Profile Generation

When a delivery occurs, a newborn `PersonRecord` is created and added to the household:

```python
def create_newborn(mother: PatientProfile, father_record: PersonRecord | None,
                    household: Household, delivery_event: LifeEvent) -> PersonRecord:
    newborn = PersonRecord()
    newborn.person_id = generate_id()
    newborn.household_id = household.household_id
    newborn.age = 0
    newborn.date_of_birth = delivery_event.timestamp.date()
    newborn.sex = weighted_choice({"M": 0.513, "F": 0.487})  # slight male excess at birth
    
    # Blood type: Mendelian inheritance from parents
    newborn.blood_type = inherit_blood_type(mother.blood_type, father_blood_type)
    newborn.rh_factor = inherit_rh(mother.rh_factor, father_rh)
    
    # Birth metrics (from delivery record)
    gestational_age = delivery_event.details["gestational_age_weeks"]
    if gestational_age >= 37:
        newborn.birth_weight_g = Normal(3000, 400).sample()  # JP mean; US: slightly higher
    elif gestational_age >= 32:
        newborn.birth_weight_g = Normal(1800, 400).sample()
    else:
        newborn.birth_weight_g = Normal(1200, 350).sample()
    
    # Apgar scores
    if normal_delivery and no_complications:
        apgar_1min = weighted_choice({7: 0.1, 8: 0.3, 9: 0.5, 10: 0.1})
        apgar_5min = weighted_choice({8: 0.1, 9: 0.4, 10: 0.5})
    # Lower scores for complicated deliveries
    
    # NICU determination
    needs_nicu = (gestational_age < 37 or newborn.birth_weight_g < 2500
                  or apgar_5min < 7 or delivery_complications)
    
    # Insurance: same as mother (JP: 乳幼児医療費助成 = near-zero copay for children)
    newborn.insurance_type = mother.insurance_type
    
    return newborn
```

### Allergy Distribution

| Substance | Prevalence (of those with allergies) | Common reaction |
|---|---|---|
| Penicillin / Amoxicillin | 30% | Rash (70%), anaphylaxis (5%) |
| Cephalosporin | 10% | Rash; 10% cross-react with penicillin allergy |
| Sulfonamide | 12% | Rash, GI |
| NSAIDs | 10% | GI, rash, bronchospasm |
| Contrast dye | 8% | Rash, anaphylactoid |
| Latex | 5% | Contact dermatitis, anaphylaxis |
| Opioids (codeine) | 5% | Nausea (often intolerance, not true allergy) |
| Fluoroquinolone | 5% | Rash, tendon issues |
| Other | 15% | Various |

Overall: ~15% of adults report at least 1 drug allergy. True allergy rate is lower (~5%), but EHR records what the patient reports.

### Current Medications Assignment

When expanding chronic conditions, assign standard medications per condition:

| Condition | Typical medications (JP) | Typical medications (US) |
|---|---|---|
| Hypertension | ARB (olmesartan, telmisartan), Ca blocker (amlodipine) | ACE-I (lisinopril), ARB (losartan), thiazide |
| Diabetes (T2) | Metformin, DPP-4i (sitagliptin), SGLT2i | Metformin, SGLT2i (empagliflozin), GLP-1 RA |
| Dyslipidemia | Statin (rosuvastatin), ezetimibe | Statin (atorvastatin), ezetimibe |
| Atrial fibrillation | DOAC (edoxaban, apixaban), rate control | DOAC (apixaban, rivaroxaban), rate control |
| COPD | LAMA (tiotropium), ICS/LABA | LAMA, ICS/LABA (budesonide/formoterol) |
| Heart failure | ACE-I/ARB, β-blocker, MRA, SGLT2i | Same + sacubitril/valsartan |
| Osteoporosis | Bisphosphonate (alendronate), VitD | Bisphosphonate, denosumab |
| CKD | ARB, SGLT2i (if eGFR allows), ESA (if advanced) | Same |

Medication assignment considers:
- Allergy check (no penicillin if penicillin-allergic, etc.)
- Drug interactions (no contraindicated combinations)
- Renal function (dose adjustment or avoidance for CKD)
- `drug_metabolism_rate` (CYP2C19 poor metabolizers need dose adjustment for some drugs)
- Country-specific formulary preferences (JP: DPP-4i popular; US: GLP-1RA popular)

---

## Cross-Module Impact Notes

### → physiology
The `PatientPhysiologicalProfile` generated here is the INPUT to the physiology module's baseline state calculation. The physiology module uses `renal_reserve`, `cardiac_reserve`, etc. to set initial `PhysiologicalState` values:
```
renal_function_baseline = renal_reserve × (1 - CKD_severity_adjustment)
cardiac_function_baseline = cardiac_reserve × (1 - HF_severity_adjustment)
```

### → encounter
`care_seeking_threshold` and `follow_up_compliance` (already on PersonRecord, carried through) determine how the patient enters and exits the encounter system.

### → treatment
`drug_metabolism_rate`, `treatment_sensitivity`, `allergies`, and `current_medications` directly constrain the treatment module's drug selection.

### → nursing
`delirium_susceptibility`, `dvt_susceptibility`, and `bmi` drive nursing risk assessments (Morse Fall Scale, Braden Score, delirium screening).

### → observation
`baseline_vitals` are the reference for interpreting disease-state changes. The observation module needs to know "what's normal for this patient" to generate realistic disease-state values.

---

## Open Questions
- [ ] CYP2C19 polymorphism distribution for other ethnicities (if US population is multi-ethnic)
- [ ] Medication adherence over time: simple rate or more complex model (honeymoon period, fatigue)?
- [ ] How to handle "allergy vs. intolerance" distinction in records
- [ ] Elderly polypharmacy: average medication count by age band (for realism validation)

## Design Notes
- First activation is the expensive operation; reactivation is a cheap update
- The physiological profile is the patient's "DNA" — it never changes (except age-related decay on reactivation)
- Current medications must be consistent with conditions + allergies + drug interactions. This is a constraint satisfaction problem, not independent sampling.
- Family history from household is a major realism advantage over other synthetic data generators
