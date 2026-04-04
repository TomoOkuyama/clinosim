# population — Catchment Area Population & Life Events

## Purpose
Generate and maintain the population of the hospital's catchment area as households and individuals. Simulate their life events (aging, disease onset, accidents) over time, and determine when and why each person seeks hospital care. This module is the origin of all hospital encounters — no patient arrives at the hospital without first existing in the population.

## Inputs
- `HealthcareSystemConfig`: Country-specific demographics, insurance distribution, screening programs
- `HospitalProfile`: Hospital scale (determines catchment population size)
- Simulation configuration: time range, catchment population size, random seed

## Outputs
- `PopulationRegistry`: Complete Layer 1 registry of all persons and households
- `PersonRecord`: Lightweight person record (Layer 1)
- `Household`: Household unit with member relationships
- `LifeEvent`: Events that occur in a person's life (disease onset, accident, chronic progression)
- `CareSeekingDecision`: Decision to visit hospital (or not), with reason, urgency, and pathway
- `ReferralContext`: Information from referring clinic (if applicable)
- `TransientVisitor`: Temporary person entering the catchment area

## Dependencies
- `healthcare_system` (demographic distributions, screening programs, insurance)
- `facility` (hospital scale → catchment area size estimation)
- `disease` (incidence rates, seasonal modifiers for life event generation)

## Confirmed Specifications

### Catchment area sizing

| Hospital scale | Estimated catchment population | Rationale |
|---|---|---|
| Small (community) | 10,000–30,000 | Serves a few neighborhoods/villages |
| Medium (regional) | 50,000–200,000 | Serves a city district or small city |
| Large (academic) | 200,000–500,000+ | Serves a region; referral center |

These are configurable. Actual hospital visit rate is ~1–5% of population per year for inpatient, ~30–50% for any outpatient contact.

### Household generation

Households are the unit of population generation, not individuals.

#### Household types (Japan)

| Type | Proportion | Composition |
|---|---|---|
| Single elderly (65+) | ~15% | 1 person |
| Elderly couple | ~12% | 2 persons, both 65+ |
| Single working adult | ~18% | 1 person, 20–64 |
| Couple (no children) | ~12% | 2 persons, 20–64 |
| Nuclear family | ~25% | 2 adults + 1–3 children |
| Three-generation | ~8% | Grandparents + parents + children |
| Single parent | ~7% | 1 adult + 1–2 children |
| Other | ~3% | Shared housing, institutions |

#### Household types (US)

| Type | Proportion | Composition |
|---|---|---|
| Single person | ~28% | 1 person (any age) |
| Married couple (no children) | ~25% | 2 persons |
| Nuclear family | ~20% | 2 adults + 1–3 children |
| Single parent | ~12% | 1 adult + 1–2 children |
| Multi-generational | ~6% | Various combinations |
| Roommates/other | ~9% | Non-family cohabitation |

#### Household attributes
- `household_id`: Unique identifier
- `address_region`: Geographic sub-area within catchment
- `household_type`: From table above
- `members`: List of PersonRecords with relationships
- `primary_care_clinic`: Assigned local clinic / GP (not fully simulated; used for referral context)
- `distance_to_hospital`: Affects care-seeking behavior and transport mode

#### Within-household correlations
- **Genetic**: Parents → children inherit risk factors (diabetes, hypertension, cancer predisposition)
- **Environmental**: Shared diet, smoking exposure, socioeconomic status
- **Infectious**: Influenza, gastroenteritis transmit within household
- **Behavioral**: Health literacy, care-seeking behavior cluster within families
- **Insurance**: Often shared (employer-provided covers family)

### Person record (Layer 1 — lightweight)

```python
@dataclass
class PersonRecord:
    person_id: str
    household_id: str

    # Demographics
    age: int
    sex: Literal["M", "F"]
    date_of_birth: date
    blood_type: Literal["A", "B", "O", "AB"]
    rh_factor: Literal["+", "-"]

    # Social
    employment_status: str
    insurance_type: str
    health_literacy: float

    # Health summary (not full clinical detail)
    chronic_conditions: list[str]          # ICD codes only (no severity/detail until Layer 2)
    is_alive: bool
    cause_of_death: str | None
    
    # Pregnancy state (females age 15–49)
    pregnancy_state: PregnancyState | None  # None if not pregnant

    # Healthcare engagement
    care_seeking_threshold: float          # 0.0–1.0
    checkup_compliance: float              # 0.0–1.0
    checkup_type: str | None
    primary_care_clinic_id: str | None
    visit_time_constraint: str             # "any" | "weekday_only" | "weekend_holiday_only" | "evening_only" | "saturday_am_only"

    # Hospital history
    has_visited_hospital: bool
    last_visit_date: date | None
    visit_count: int
    active_patient_record_id: str | None   # Link to Layer 2 if currently active
```

### Life event engine

The life event engine runs on the population registry and produces events that may trigger hospital visits.

#### Annual population update (every simulated year)

For every person in the registry:

| Event | Method | Example |
|---|---|---|
| Aging | Deterministic | Everyone +1 year |
| New chronic disease | Age/sex-specific incidence rate × individual risk factors | 62M, smoker → 2% chance of COPD onset this year |
| Chronic disease progression | Stage transition probabilities | CKD stage 3 → stage 4: 5%/year |
| Death (non-hospital) | Age/sex-specific mortality × comorbidity adjustment | |
| Employment change | Age-dependent transition rates | Age 60–65: retirement probability |
| Migration (move out) | ~2–3%/year | Person removed from registry |
| Migration (move in) | ~2–3%/year | New person added to registry |
| Birth | Fertility rates by mother's age | Added to existing household |

#### Stochastic events (monthly or continuous)

| Event | Incidence model | Seasonal modifier |
|---|---|---|
| Acute infection (pneumonia, UTI, etc.) | Age/sex/comorbidity-specific rates | Winter ×1.5–2.0 |
| Influenza | Epidemic model (SIR within households) | Winter peak, varies by year |
| Trauma / falls | Age/activity-dependent | Winter ×1.3 (icy conditions) |
| Cardiac event (AMI, arrhythmia) | Age/sex/comorbidity, time-of-day | Winter ×1.2, morning peak |
| HF exacerbation | Prior HF + triggers (infection, non-compliance, fluid excess) | Winter + summer |
| COPD exacerbation | Prior COPD + cold air + infection | Winter ×1.5 |
| Allergic events | Sensitization status | Spring pollen season |

**Note**: Incidence rates and seasonal modifiers for each disease are sourced from the disease module's YAML protocol files via `disease.get_monthly_incidence(disease_id, person, month)`. The population module does not hardcode disease-specific rates — it queries the disease module for all registered diseases each time step.

#### Household-level events

| Event | Description |
|---|---|
| Infectious disease spread | Index case → 30–50% secondary attack rate for influenza within household |
| Caregiver burden | Elderly admission → family member stress, visit patterns |
| Shared food poisoning | Entire household affected simultaneously |

### Care-seeking decision model

When a life event produces symptoms, the care-seeking decision model determines what happens:

```
Life event → symptom severity score (0.0–1.0)
  │
  │  Modified by: symptom_reporting_bias (individual)
  │               health_literacy (individual)
  ↓
Perceived severity
  │
  ├── < self_care_threshold → Self-care (OTC medication, rest)
  │     └── Re-evaluate in 1–3 days (may escalate)
  │
  ├── < outpatient_threshold → Schedule outpatient visit
  │     ├── Primary care clinic first (with probability based on country)
  │     │     └── If beyond clinic capability → referral to this hospital
  │     └── Direct to this hospital outpatient (JP: more common)
  │
  ├── < emergency_threshold → Visit ER
  │     ├── Self-transport or taxi
  │     └── Ambulance (if very severe or patient/family decides)
  │
  └── ≥ emergency_threshold → Call ambulance → ER
```

Decision modifiers:
- **Time of day**: Night → higher ER use (clinics closed), or wait until morning
- **Day of week**: Weekend → ER or wait until Monday
- **Cost awareness** (US): Higher threshold if high deductible
- **Habitual visiting behavior** (JP, optional — see below)
- **Family influence** (JP): Family member insists on hospital visit
- **Prior experience**: Previous bad outcome → lower threshold
- **Distance**: Far from hospital → higher threshold for minor symptoms

### Habitual hospital visiting (Japan-specific, optional feature)

In Japan, particularly among the elderly, a significant proportion of outpatient visits are **habitual** — the patient has no significant new symptoms or only very minor complaints (mild fatigue, slight joint pain, "just checking"). This is a well-documented phenomenon driven by:

- Social isolation (hospital visit as social activity)
- Low co-payment for elderly (1割負担 = 10% copay for age 75+)
- Cultural comfort with frequent medical contact
- Chronic condition follow-up that becomes routine beyond medical necessity
- "念のため" (just in case) mindset

#### Modeling approach

```python
@dataclass
class HabitualVisitProfile:
    is_habitual_visitor: bool              # ~15–20% of elderly (75+) outpatients
    visit_frequency: str                   # "weekly" | "biweekly" | "monthly"
    preferred_day: int | None              # day of week (0=Mon, consistent for each person)
    preferred_department: str              # usually internal medicine
    typical_complaints: list[str]          # "fatigue" | "mild_pain" | "insomnia" | "BP_check"
```

Characteristics:
- **Age**: Predominantly 70+, increases with age
- **Living situation**: Higher rate among those living alone
- **Gender**: Slightly higher in women
- **Frequency**: Weekly to monthly; remarkably regular schedule
- **Clinical content**: Vitals check, brief consultation, repeat prescriptions; rarely new workup
- **Impact on data**: Generates high-volume, low-acuity outpatient records; consumes outpatient clinic time slots

This feature is **optional** (configurable on/off) because:
- It significantly increases outpatient record volume
- Not all simulation use cases need this level of realism
- US equivalent (frequent ED visitors) exists but is driven by different factors (uninsured, mental health)

When enabled, the `LifeEventType.HABITUAL_VISIT` events are generated on the person's regular schedule, producing outpatient encounters with minimal clinical content.

### Referral context generation

When a person is referred from a primary care clinic:

```python
@dataclass
class ReferralContext:
    referring_clinic_name: str
    referring_physician_name: str
    referral_date: date
    referral_reason: str                   # "Suspected pneumonia, not responding to oral antibiotics"
    prior_findings: list[str]              # Key findings from clinic workup
    prior_medications: list[str]           # Current medications prescribed by GP
    urgency: str                           # "routine" | "urgent" | "emergency"
```

### Transient visitors

```python
@dataclass
class TransientVisitor:
    person_id: str
    reason_in_area: str                    # "tourism" | "business" | "transit"
    home_region: str                       # where they normally live
    # Limited history:
    age: int
    sex: Literal["M", "F"]
    known_conditions: list[str]            # self-reported or medication-inferred
    known_allergies: list[str]
    current_medications: list[str]
    # No prior records at this hospital
    # No physiological profile (must be estimated)
```

Generation rate: configurable per facility, default ~5–10% of ER volume.

### Health checkup scheduling

The population module schedules health checkups based on:
- Person's `checkup_type` and `checkup_compliance`
- Calendar (corporate checkups cluster in Apr–Sep; municipal in May–Oct)
- Random variation: even regular attendees don't come on the exact same date each year

```
For each person with checkup_compliance > 0:
  roll = random()
  if roll < checkup_compliance:
    schedule checkup in appropriate season
    → generates outpatient encounter of type "health_checkup"
    → results may trigger clinical encounter (5–10% abnormal finding rate)
```

### Population statistics targets (realism validation)

Generated population must match published statistics:

| Metric | Japan source | US source |
|---|---|---|
| Age/sex distribution | e-Stat (国勢調査) | US Census Bureau |
| Household composition | 国民生活基礎調査 | American Community Survey |
| Blood type distribution | Japanese Red Cross data | AABB data |
| Chronic disease prevalence by age | 患者調査, NDB | NHANES, BRFSS |
| Annual hospital admission rate | 病院報告 | HCUP NIS |
| Health checkup participation rate | 特定健診実施状況 | BRFSS |
| Mortality rate by age | 人口動態統計 | CDC WONDER |

---

## Internal Design

### Generation Algorithm

The population is generated in 4 phases:

#### Phase 1: Household shell generation

```
Input: catchment_population_size, household_type_distribution (from healthcare_system)

1. Calculate target household count:
   avg_household_size = weighted_avg(household_type → member_count)
   target_households = catchment_population_size / avg_household_size

2. For each household:
   a. Sample household_type from distribution
   b. Assign address_region (geographic sub-area, affects distance to hospital)
   c. Assign socioeconomic_level (correlates with region)
   d. Assign primary_care_clinic_id (from pool of local clinics)
   e. Calculate distance_to_hospital
```

#### Phase 2: Person generation within households

```
For each household:
  Based on household_type:
    - Determine number and roles of members (head, spouse, child, grandparent)
    - For each member:
      a. Age: constrained by role (parent: 25–55, child: 0–18, elderly: 65–95)
      b. Sex: constrained by role, otherwise 50/50
      c. date_of_birth: derived from age + random month/day
      d. blood_type: inherited from parents (if parents exist) or sampled from national distribution
      e. employment_status: derived from age + household_type
      f. insurance_type: derived from employment_status + age (using healthcare_system rules)
      g. health_literacy: correlated with socioeconomic_level, Normal(μ, σ) by level
      h. care_seeking_threshold: from healthcare_system base + individual variation
      i. checkup_compliance: from healthcare_system base + employment + age adjustment
      j. checkup_type: derived from employment_status (employed → corporate, self-employed → municipal, etc.)
      k. visit_time_constraint: derived from employment_status and work pattern (see below)
      l. adl_independence: age-dependent (1.0 for <65; gradual decline with age; sharper decline >80)
      m. frailty_index: age-dependent (0.0 for young; increases with age + chronic disease count)
      n. mobility: derived from adl_independence + orthopedic conditions
      o. cognitive_status: "normal" unless dementia assigned in chronic conditions
      p. mental_health_conditions: assigned by age/sex-specific prevalence (see below)
      q. adherence_pattern: sampled from distribution (correlates with health_literacy, age, insurance)
      r. diet_compliance: correlated with health_literacy and condition-specific counseling history
      s. exercise_compliance: correlated with age, mobility, health_literacy
      t. advance_directive: probability increases with age; JP: rare formal documents; US: more common age 65+
      u. vaccination_history: generate based on age, country, checkup history
      v. primary_caregiver: assigned for persons with adl_independence < 0.7 or cognitive_status != "normal"
```

**Visit time constraint assignment:**
```
employment_status → visit_time_constraint:
  "employed_fulltime_weekday"  → "saturday_am_only" (60%) or "evening_only" (20%) or "any_with_leave" (20%)
  "employed_fulltime_shift"    → "any" (shift workers have variable days off)
  "employed_parttime"          → "weekday_only" (can arrange around work)
  "self_employed"              → "any" (flexible schedule)
  "retired"                    → "any" (full flexibility, prefers weekday mornings)
  "unemployed"                 → "any"
  "student"                    → "weekend_holiday_only" (50%) or "any" (school allows absence for medical, 50%)
  "homemaker"                  → "weekday_only" (prefers while children at school)
```

This affects:
- When outpatient follow-up appointments are scheduled (encounter module must respect patient's availability)
- Whether a patient delays non-urgent care to their available day (may wait days if only Saturday works)
- Health checkup scheduling (corporate checkups may be on a company-designated day, overriding personal preference)
- **ER visits and emergency admissions are NOT affected** — emergencies override time constraints

**Blood type inheritance model:**
```
Parent A × Parent B → Child (Mendelian genetics)
  AA × AO → A (50%) or A (50%)    [simplified]
  AO × BO → AB (25%), A (25%), B (25%), O (25%)
  ...
When parents unknown (single person household): sample from national distribution
```

#### Phase 3: Chronic condition assignment

```
For each person:
  Based on age, sex, smoking status, BMI, family history:
    For each chronic disease in prevalence table:
      base_rate = age_sex_specific_prevalence(disease, age, sex)
      adjusted_rate = base_rate × comorbidity_multiplier × risk_factor_adjustment
      if random() < adjusted_rate:
        assign condition with:
          - onset_date: estimated (age-dependent, typically years before simulation start)
          - ICD code

  Comorbidity chain (applied after initial assignment):
    If has hypertension → recheck diabetes (×2.0 multiplier)
    If has diabetes → recheck CKD (×2.5 multiplier)
    If has CKD → recheck HF (×3.0 multiplier)
    ...etc (from healthcare_system comorbidity_multipliers)
```

**Family history propagation:**
```
For each parent-child pair:
  If parent has {hypertension, diabetes, cancer_type, cardiac_disease}:
    child.family_history.append(condition)
    child's disease risk for that condition: ×1.5–3.0 (condition-dependent)
```

#### Phase 3b: Behavioral & functional attribute generation

Applied after chronic conditions are assigned, because many behavioral attributes depend on conditions.

**Functional status (ADL / Frailty):**
```python
def generate_functional_status(age, chronic_conditions, sex):
    # ADL independence: high for young, declines with age and conditions
    if age < 65:
        adl = 1.0
    elif age < 75:
        adl = Normal(0.95, 0.05).sample()
    elif age < 85:
        adl = Normal(0.85, 0.10).sample()
    else:
        adl = Normal(0.70, 0.15).sample()
    
    # Condition adjustments
    if "stroke" in conditions: adl -= 0.2
    if "hip_fracture_history" in conditions: adl -= 0.15
    if "dementia" in conditions: adl -= severity_adjustment(dementia_severity)
    if "heart_failure" in conditions and severity == "severe": adl -= 0.1
    adl = clamp(adl, 0.0, 1.0)
    
    # Frailty: composite of age, conditions, ADL
    frailty = clamp(0.03 * max(0, age - 60) + 0.05 * len(chronic_conditions) + (1 - adl) * 0.3, 0, 1)
    
    # Mobility
    if adl >= 0.9: mobility = "independent"
    elif adl >= 0.7: mobility = weighted_choice({"independent": 0.3, "cane": 0.5, "walker": 0.2})
    elif adl >= 0.4: mobility = weighted_choice({"walker": 0.4, "wheelchair": 0.5, "bedbound": 0.1})
    else: mobility = weighted_choice({"wheelchair": 0.4, "bedbound": 0.6})
    
    return adl, frailty, mobility
```

**Mental health conditions:**

| Condition | Prevalence | Age pattern | Sex ratio (F:M) | Source |
|---|---|---|---|---|
| Depression | 5–8% (JP), 8–10% (US) | Higher in elderly | 2:1 | JP: 患者調査; US: NHANES |
| Dementia | 1% (65–69), 5% (75–79), 15% (80–84), 30% (85+) | Sharply age-dependent | 1.5:1 | Alzheimer's Association |
| Anxiety disorder | 3–5% (JP), 18% (US) | Peaks 25–44 | 2:1 | Epidemiological surveys |
| Alcohol dependence | 3% M, 0.5% F (JP); 6% M, 3% F (US) | Peaks 40–59 | 3–6:1 | National surveys |
| Schizophrenia | 0.7% | Onset 18–35 | 1:1 | WHO |
| Insomnia (chronic) | 10–15% | Increases with age | 1.5:1 | Literature |

Mental health impact on behavior:
```python
mental_health_behavior_modifiers = {
    "depression": {
        "care_seeking_modifier": 0.7,       # less likely to seek care (apathy)
        "adherence_modifier": 0.6,          # poor medication compliance
        "follow_up_modifier": 0.5,          # high no-show rate
        "pain_reporting_modifier": 1.3,     # increased pain sensitivity
        "los_modifier": 1.2,               # longer hospital stays
    },
    "dementia": {
        "care_seeking_modifier": None,      # depends entirely on caregiver
        "adherence_modifier": 0.3,          # cannot self-manage medications
        "requires_caregiver": True,
        "delirium_risk_modifier": 3.0,
        "los_modifier": 1.5,
    },
    "anxiety": {
        "care_seeking_modifier": 1.5,       # MORE likely to seek care (health anxiety)
        "adherence_modifier": 0.8,          # may skip due to medication fears
        "follow_up_modifier": 1.2,          # attends more than scheduled
    },
    "alcohol_dependence": {
        "care_seeking_modifier": 0.5,       # avoids healthcare
        "adherence_modifier": 0.4,          # poor compliance
        "withdrawal_risk": True,            # delirium tremens risk on admission
        "hepatic_function_modifier": 0.7,
    },
}
```

**Medication adherence pattern distribution:**

| Pattern | JP prevalence | US prevalence | Typical conditions |
|---|---|---|---|
| full_compliance | 35% | 25% | — |
| good_when_symptomatic | 20% | 15% | HT (asymptomatic → stops when feeling fine) |
| cost_skipping | 2% | 20% | US uninsured/underinsured; all chronic meds |
| side_effect_avoidance | 10% | 10% | Statins (myalgia), ACE-I (cough) |
| forgetful | 20% | 15% | Elderly, polypharmacy |
| weekend_holiday | 5% | 5% | Working adults; blood thinners (fear of bleeding on active days) |
| alternative_substitution | 8% | 5% | JP: replace with kampo (漢方); US: supplements |

**End-of-life preferences:**

| Parameter | Japan | US |
|---|---|---|
| Formal advance directive rate (age 65+) | 5–10% (very low; verbal family consensus dominant) | 30–40% |
| DNR rate at hospital admission (age 80+) | 15–20% (often decided during hospitalization) | 40–50% |
| Healthcare proxy designated | Rare as formal document | 20–30% (age 65+) |
| Palliative care referral rate (terminal illness) | 20–30% | 50–60% |

```python
def generate_advance_directive(age, country, chronic_conditions):
    if country == "JP":
        if age < 70: return None  # almost never
        probability = 0.03 + (age - 70) * 0.01  # slowly increases with age
        if "cancer" in conditions: probability += 0.10
    elif country == "US":
        if age < 65: return AdvanceDirective(has_document=False, code_status="full_code", ...)
        probability = 0.15 + (age - 65) * 0.015
        if "cancer" in conditions: probability += 0.15
        if "heart_failure" in conditions and severity == "severe": probability += 0.10
    
    if random() < probability:
        code_status = weighted_choice({"full_code": 0.3, "DNR": 0.5, "DNR_DNI": 0.15, "comfort_only": 0.05})
        return AdvanceDirective(has_document=(country=="US"), code_status=code_status, ...)
    return None
```

**Vaccination history generation:**

| Vaccine | Target | JP coverage | US coverage |
|---|---|---|---|
| Influenza (annual) | Age 65+ (subsidized) | 55% | 65% |
| Influenza (annual) | Age 18–64 | 30% | 40% |
| Pneumococcal (PCV13/PPSV23) | Age 65+ | 40% (JP: 定期接種化) | 70% |
| COVID-19 (primary series) | All adults | 80% | 70% |
| COVID-19 (latest booster) | All adults | 40% | 20% |
| Hepatitis B | Healthcare workers, at-risk | 30% (targeted) | 70% (universal childhood since 2016) |
| Shingles (Shingrix) | Age 50+ | 5% (自費, expensive) | 30% |

Vaccination affects disease incidence:
- Influenza vaccine → influenza incidence ×0.4 (vaccine effectiveness ~60%)
- Pneumococcal vaccine → pneumococcal pneumonia incidence ×0.5
- COVID vaccine → severe COVID incidence ×0.1 (primary series)

**Caregiver assignment:**
```python
def assign_caregiver(person, household):
    if person.adl_independence >= 0.7 and person.cognitive_status == "normal":
        return None  # no caregiver needed
    
    # Look for household member who can serve as caregiver
    potential_caregivers = [m for m in household.members 
                           if m.person_id != person.person_id 
                           and m.age >= 18 and m.adl_independence >= 0.8]
    
    if potential_caregivers:
        cg = select_best_caregiver(potential_caregivers)  # prefer spouse, then adult child
        return CaregiverInfo(
            caregiver_person_id=cg.person_id,
            caregiver_type=relationship_to(person, cg),
            availability="full_time" if cg.employment_status in ["retired", "homemaker"] else "limited",
            capability=Normal(0.7, 0.15).sample(),
            burden_level=0.3 if person.adl_independence > 0.5 else 0.6,
        )
    else:
        # No household caregiver available → professional care
        if country == "JP":
            # 介護保険制度: home helper assigned based on care level
            return CaregiverInfo(caregiver_type="professional_home_helper", availability="daytime_only", ...)
        elif country == "US":
            return CaregiverInfo(caregiver_type="home_health_aide", availability="limited", ...)
```

**Lifestyle compliance:**
```python
def generate_lifestyle_compliance(person):
    base = person.health_literacy * 0.5 + 0.2  # literacy is biggest predictor
    
    # Depression reduces compliance
    if "depression" in person.mental_health_conditions:
        base *= 0.6
    
    # Recent health scare increases compliance temporarily
    # (modeled in life event engine, not here)
    
    diet_compliance = clamp(Normal(base, 0.15).sample(), 0, 1)
    exercise_compliance = clamp(Normal(base * 0.8, 0.2).sample(), 0, 1)  # exercise harder to maintain
    
    # Age effect: elderly may have less capacity for exercise regardless of willingness
    if person.age > 75:
        exercise_compliance *= 0.7
    
    return diet_compliance, exercise_compliance
```

#### Phase 4: Historical record seeding (optional)

For simulation realism, the population at t=0 should not be "new" — some people should have prior hospital history.

```
For each person who would plausibly have visited this hospital before:
  Based on age, chronic_conditions, distance_to_hospital:
    estimate number of prior visits (Poisson, mean depends on conditions)
    For each prior visit:
      generate minimal record: {date, encounter_type, primary_diagnosis}
      mark: has_visited_hospital = true, last_visit_date = date
      
  For persons with checkup_type:
    generate prior checkup dates (based on checkup_compliance, going back 3–5 years)
    generate minimal checkup results: {date, key_findings}
```

### Life Event Engine Algorithm

The life event engine runs on a configurable time step (default: monthly) for the entire population.

```
For each time step (month):

  === Deterministic events ===
  If January:
    For all persons: age += 1 (on their birth month, actually)
    Check retirement transitions: age 60–65 → employment_status change
    Apply annual population churn:
      migration_out: remove ~0.2%/month of population (random)
      migration_in: add ~0.2%/month new persons (generated fresh)

  === Stochastic events (per person) ===
  For each person where is_alive:
    
    # Chronic disease new onset
    For each disease not already present:
      monthly_incidence = annual_incidence(disease, age, sex, risk_factors) / 12
      if random() < monthly_incidence:
        emit LifeEvent(CHRONIC_DISEASE_NEW, ...)
        add to person's chronic_conditions
        # Does NOT trigger hospital visit (most chronic onset is gradual)
        # Exception: if discovered via checkup → SCREENING_ABNORMALITY

    # Chronic disease progression
    For each existing chronic condition:
      if eligible for progression:
        monthly_progression_rate = annual_rate / 12
        if random() < monthly_progression_rate:
          emit LifeEvent(CHRONIC_DISEASE_PROGRESSION, ...)

    # Acute events (season-dependent)
    seasonal_modifier = get_seasonal_modifier(month, disease)
    For each acute event type:
      monthly_rate = base_rate(age, sex, comorbidities) × seasonal_modifier / 12
      if random() < monthly_rate:
        emit LifeEvent(ACUTE_DISEASE_ONSET or TRAUMA, ...)
        → evaluate care_seeking_decision()

    # Chronic exacerbation
    For each chronic condition that can exacerbate:
      monthly_exacerbation_rate = base_rate × triggers(season, adherence, infection)
      if random() < monthly_exacerbation_rate:
        emit LifeEvent(CHRONIC_EXACERBATION, ...)
        → evaluate care_seeking_decision()

    # Death (non-hospital)
    monthly_mortality = annual_mortality(age, sex, comorbidities) / 12
    if random() < monthly_mortality:
      person.is_alive = false
      remove from active simulation

  === Pregnancy & reproduction events ===
  For each female person where is_alive and age 15–49 and not currently_pregnant:
    monthly_conception_rate = fertility_rate(age, country, marital_status) / 12
    if random() < monthly_conception_rate:
      person.pregnancy_state = PregnancyState(
        conception_date = current_date,
        estimated_due_date = current_date + 280 days,
        gestational_age_weeks = 0,
        pregnancy_risk = assess_pregnancy_risk(person),  # low / moderate / high
        planned = weighted_choice({"planned": 0.55, "unplanned": 0.45}),  # JP; US: 0.55 unplanned
      )
      # First prenatal visit typically at 8–12 weeks gestation
      schedule prenatal_first_visit at conception_date + 8–12 weeks

  For each female person where currently_pregnant:
    advance gestational_age_weeks += ~4 (monthly)

    # Pregnancy outcomes (evaluated at appropriate gestational age)
    if gestational_age_weeks < 12:
      # Spontaneous miscarriage: ~15% of recognized pregnancies
      if random() < 0.04:  # ~15% total, spread across first 12 weeks
        emit LifeEvent(PREGNANCY_LOSS, type="miscarriage")
        person.pregnancy_state = None
        → may or may not trigger hospital visit (depends on severity)

      # Induced abortion
      # JP: ~7 per 1000 women age 15–49/year; US: ~11 per 1000
      if pregnancy is unplanned and decision_to_terminate:
        emit LifeEvent(PREGNANCY_TERMINATION, type="induced_abortion")
        → generates day_surgery or outpatient encounter
        person.pregnancy_state = None

    if gestational_age_weeks in [8, 12, 16, 20, 24, 28, 30, 32, 34, 36, 37, 38, 39, 40]:
      # Prenatal checkup schedule (JP: 14 visits standard; US: ~12 visits)
      emit LifeEvent(PRENATAL_CHECKUP, gestational_age=gestational_age_weeks)
      → outpatient encounter (see encounter module for prenatal workflow)

    if gestational_age_weeks >= 22 and gestational_age_weeks < 37:
      # Preterm labor risk
      preterm_monthly_rate = preterm_risk(person, gestational_age_weeks)
      if random() < preterm_monthly_rate:
        emit LifeEvent(PRETERM_LABOR, gestational_age=gestational_age_weeks)
        → emergency/inpatient encounter

    if gestational_age_weeks >= 37 and gestational_age_weeks <= 42:
      # Term delivery
      if gestational_age_weeks == 40 or (random() < delivery_probability(gestational_age_weeks)):
        delivery_mode = determine_delivery_mode(person)  # vaginal 80% / cesarean 20% (varies)
        emit LifeEvent(DELIVERY, mode=delivery_mode)
        → inpatient encounter (see encounter module for delivery workflow)
        
        # Newborn creation
        newborn = create_newborn(person, household)
        add newborn to household and population registry
        if delivery complications or preterm:
          emit LifeEvent(NICU_ADMISSION, newborn_id=newborn.person_id)

    # Pregnancy complications (checked each month during pregnancy)
    # See disease module for: gestational diabetes, preeclampsia, placenta previa, etc.

  === Household-level events ===
  For each household with an infectious case:
    For each other member:
      if random() < household_attack_rate(disease):
        emit LifeEvent(ACUTE_DISEASE_ONSET, ...) for that member

  === Chronic disease management visits ===
  For each person with chronic_conditions:
    For each condition requiring regular outpatient management:
      visit_interval = chronic_management_interval(condition, country)
        # HT/DM/Dyslipidemia: monthly (JP), every 3 months (US)
        # HF: every 1–2 months (both)
        # CKD: every 1–3 months depending on stage
        # COPD: every 2–3 months
        # Atrial fibrillation (on anticoagulant): monthly (JP), every 3 months (US)
      if this month is a scheduled visit month:
        if random() < person.follow_up_compliance:
          emit LifeEvent(CHRONIC_MANAGEMENT_VISIT, condition=condition, department=managing_department(condition))
          → generates outpatient encounter (prescription renewal, lab check)

  # Multi-department outpatient pattern:
  # A single patient may visit multiple departments regularly.
  # Example: 75yo with HT (internal medicine monthly) + knee OA (orthopedics bimonthly) + glaucoma (ophthalmology quarterly)
  # These are SEPARATE encounters with SEPARATE physicians, often on DIFFERENT days.
  # Some patients try to consolidate visits on the same day (JP: common to schedule 2 departments on same day)
  # Consolidation probability: ~30% in JP (patient requests same-day appointments), ~10% in US
  #
  # Each condition maps to a department:
  #   HT, DM, dyslipidemia, COPD, HF → Internal Medicine
  #   CKD → Nephrology or Internal Medicine
  #   OA, back pain → Orthopedics
  #   Glaucoma, cataracts → Ophthalmology
  #   BPH, urological → Urology
  #   Depression, anxiety → Psychiatry (low visit rate: stigma in JP)
  #   Allergic rhinitis → ENT or Allergology
  #
  # Physician continuity: same physician at each visit for the same condition (~90%)

  === Seasonal / allergic symptoms ===
  For each person with allergy sensitization or seasonal condition:
    # Allergic rhinitis (cedar pollen, JP: Feb–May)
    if person has "allergic_rhinitis_cedar" and month in [2, 3, 4, 5]:
      if random() < 0.8:  # most sensitized people have symptoms
        # Usually managed by local clinic, but some visit hospital
        if person visits this hospital for allergy:
          emit LifeEvent(SEASONAL_ALLERGY_FLARE, ...)
          → outpatient encounter (prescription renewal, symptom management)
    
    # Asthma exacerbation (seasonal triggers)
    if person has "asthma" and month in seasonal_trigger_months:
      exacerbation_prob = base_rate × seasonal_modifier
      if random() < exacerbation_prob:
        emit LifeEvent(CHRONIC_EXACERBATION, condition="asthma")

    # Eczema / atopic dermatitis (winter dry skin, summer sweat)
    # Gout flares (summer dehydration, year-end alcohol)
    # Migraine (weather changes, seasonal patterns)

  === Scheduled events ===
  # Health checkups
  If month is in checkup season:
    For each person with scheduled checkup this month:
      emit LifeEvent(HEALTH_CHECKUP_SCHEDULED, ...)
      → generates outpatient encounter

  # Habitual visits (JP, optional)
  For each habitual_visitor:
    if this is their scheduled visit week/month:
      emit LifeEvent(HABITUAL_VISIT, ...)

  # Follow-up visits (post-discharge, distinct from chronic management)
  For each person with pending post-discharge follow-up:
    if follow-up date is in this month:
      emit LifeEvent(FOLLOW_UP_DUE, ...)

  === Transient visitors ===
  monthly_transient_count = facility_er_volume × transient_rate / 12
  For i in range(Poisson(monthly_transient_count)):
    generate TransientVisitor
    emit LifeEvent for transient (trauma or acute event)
```

### Care-Seeking Decision Algorithm

```python
def care_seeking_decision(person: PersonRecord, event: LifeEvent) -> CareSeekingDecision:
    
    # 1. Calculate perceived severity
    objective_severity = event.severity  # 0.0–1.0
    perceived = objective_severity * person.symptom_reporting_bias
    perceived = clamp(perceived + noise(σ=0.05), 0, 1)
    
    # 2. Apply individual threshold
    threshold = person.care_seeking_threshold
    
    # 3. Modify by context
    hour = event.timestamp.hour
    is_weekend = event.timestamp.weekday() >= 5
    is_holiday = is_holiday_date(event.timestamp)
    is_night = hour < 6 or hour >= 22
    
    # Night/weekend raises threshold for non-emergency (wait until morning/Monday)
    if is_night and perceived < 0.7:
        threshold += 0.15
    if is_weekend and perceived < 0.6:
        threshold += 0.10
    
    # Japan elderly: lower threshold (more willing to visit)
    if country == "JP" and person.age >= 75:
        threshold *= 0.7
    
    # US uninsured: higher threshold (cost barrier)
    if country == "US" and person.insurance_type == "uninsured":
        threshold += 0.20
    
    # Family influence (JP)
    if country == "JP" and not person.living_alone:
        if perceived > threshold * 0.8:  # family notices and encourages visit
            threshold *= 0.85
    
    # 4. Decision
    if perceived < threshold * 0.5:
        return CareSeekingDecision(decision="no_action", ...)
    
    elif perceived < threshold:
        return CareSeekingDecision(decision="self_care", ...)
        # Re-evaluate in 1–3 days; may escalate if not improving
    
    elif perceived < 0.7:
        # Outpatient level
        # Apply visit time constraint (non-emergency only)
        delay = calculate_visit_delay(event.timestamp, person.visit_time_constraint)
        
        if random() < referral_pathway_probability(country, hospital_scale):
            return CareSeekingDecision(decision="primary_care", delay_hours=delay,
                                       referral_context=generate_referral(), ...)
        else:
            return CareSeekingDecision(decision="hospital_outpatient", delay_hours=delay, ...)
    
    elif perceived < 0.85:
        # ER level — visit_time_constraint does NOT apply (emergency overrides)
        delay = calculate_delay(hour, is_weekend, person)
        return CareSeekingDecision(decision="hospital_er", delay_hours=delay, ...)
    
    else:
        # Emergency — ambulance — no constraint
        return CareSeekingDecision(decision="ambulance", delay_hours=0.25, ...)
```

### Visit Time Constraint Delay

For non-emergency outpatient visits, the patient may have to wait for their available time slot:

```python
def calculate_visit_delay(event_time: datetime, constraint: str, calendar: HolidayCalendar) -> float:
    """Returns delay in hours until the patient can visit the hospital."""
    
    if constraint == "any":
        return 0  # can go anytime during business hours
    
    if constraint == "saturday_am_only":
        # Find next Saturday
        days_until_saturday = (5 - event_time.weekday()) % 7
        if days_until_saturday == 0 and event_time.hour < 12:
            return 0  # it's already Saturday morning
        if days_until_saturday == 0:
            days_until_saturday = 7  # next Saturday
        return days_until_saturday * 24
    
    if constraint == "weekend_holiday_only":
        # Find next weekend or holiday
        for days_ahead in range(7):
            candidate = event_time + timedelta(days=days_ahead)
            if candidate.weekday() >= 5 or calendar.is_holiday(candidate.date()):
                return days_ahead * 24
        return 5 * 24  # worst case: wait until next weekend
    
    if constraint == "evening_only":
        # Next evening (17:00–19:00) — JP hospitals with evening clinics
        if event_time.hour < 17:
            return 17 - event_time.hour
        return 24 + (17 - event_time.hour)  # tomorrow evening
    
    if constraint == "weekday_only":
        # Already available on weekdays
        if event_time.weekday() < 5 and not calendar.is_holiday(event_time.date()):
            return 0
        # Find next weekday
        for days_ahead in range(1, 4):
            candidate = event_time + timedelta(days=days_ahead)
            if candidate.weekday() < 5 and not calendar.is_holiday(candidate.date()):
                return days_ahead * 24
        return 24  # fallback
    
    return 0
```

**Realism impact**: A full-time office worker with moderate symptoms may wait 3–5 days for Saturday morning clinic. This creates realistic delay patterns between symptom onset and first hospital contact, and explains why Saturday outpatient clinics in Japan are heavily utilized.

**Japan-specific note**: Many Japanese hospitals offer Saturday morning outpatient clinics (土曜午前外来). This is a major access point for working-age adults. The `facility` module should include Saturday AM clinic availability.

### Referral Pathway Probability

Probability that a hospital visit comes via referral (not direct):

| Path | Japan (medium hospital) | US (medium hospital) |
|---|---|---|
| Direct to hospital outpatient | 40% | 20% |
| Via GP/PCP with referral letter | 35% | 50% |
| Via ER (self-transport) | 15% | 15% |
| Via ambulance | 10% | 15% |

For Japan large/university hospitals, referral rate is higher (~60%) due to 紹介状 culture.
For small hospitals, referral rate is lower (~20%) — they are the local first-contact point.

### Self-Care Escalation Model

When a person chooses self-care, they re-evaluate after a delay:

```
Day 0: self_care chosen
Day 1–3: re-evaluate
  - If symptoms improving (50–60% probability for mild events): no further action
  - If symptoms stable: extend self-care 2 more days, then re-evaluate
  - If symptoms worsening (10–20%): escalate to outpatient or ER
  - After 7 days of no improvement: almost always seek care (threshold drops to 0.1)
```

This creates realistic delays between symptom onset and hospital presentation, varying by individual.

### Memory & Performance Estimates

| Population size | Layer 1 memory | Persons visiting hospital/year | Layer 2 active at any time |
|---|---|---|---|
| 10,000 | ~1 MB | ~500–1,000 | ~30–50 |
| 50,000 | ~5 MB | ~2,500–5,000 | ~150–250 |
| 100,000 | ~10 MB | ~5,000–10,000 | ~300–500 |
| 500,000 | ~50 MB | ~25,000–50,000 | ~1,500–2,500 |

Layer 2 activation is the expensive part. At any given time, only ~0.3–0.5% of the population is an active Layer 2 patient.

---

## Open Questions
- [ ] Exact catchment population size formula per hospital scale (current values are estimates)
- [ ] Chronic disease incidence rate data: need tabulated rates per 5-year age band × sex × country
- [ ] Infectious disease household transmission model: simplified attack rate vs. SIR dynamics
- [ ] Historical record seeding: how many years back, how much detail?
- [ ] Population churn (migration) model: uniform or correlated with demographics?
- [ ] Self-care escalation model: probability curves need clinical validation

## Design Notes
- The population module is the most fundamental change from traditional synthetic data generators
- It ensures that hospital data is a _consequence_ of population dynamics, not an arbitrary construction
- Layer 1 must be very lightweight — the full population is kept in memory
- Layer 2 activation is triggered by care-seeking decision; deactivation by discharge + follow-up completion
- The population module owns the "world clock" — it advances simulated time and distributes events to other modules
- The care-seeking decision algorithm is the critical realism component — it determines who comes to the hospital, when, and why. Getting this wrong makes everything downstream unrealistic.
