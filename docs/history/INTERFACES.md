# clinosim — Core Data Type Definitions

This document defines all data types that flow between modules. These are the contracts that modules agree on. Internal-only types belong in each module's SPEC.md, not here.

---

## 0. Population Types

### 0.1 Household

Produced by: `population`
Consumed by: `patient`, `disease` (household transmission), `encounter`

```python
@dataclass
class Household:
    household_id: str
    address_region: str
    household_type: str                    # "single_elderly" | "elderly_couple" | "nuclear_family" | ...
    members: list[PersonRecord]
    relationships: list[FamilyRelationship]
    primary_care_clinic_id: str | None
    distance_to_hospital_km: float
    socioeconomic_level: str               # "low" | "middle" | "high"

@dataclass
class FamilyRelationship:
    person_a_id: str
    person_b_id: str
    relationship: str                      # "spouse" | "parent_child" | "sibling" | "grandparent_grandchild"
```

### 0.2 PersonRecord (Layer 1)

Produced by: `population`
Consumed by: `patient` (activation trigger), `disease` (incidence check)

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

    # Health summary (lightweight — no clinical detail)
    chronic_conditions: list[str]          # ICD codes only
    mental_health_conditions: list[str]    # "depression" | "dementia" | "anxiety" | "schizophrenia" | "alcohol_dependence"
    is_alive: bool

    # Functional status
    adl_independence: float                # 0.0–1.0 (1.0 = fully independent, 0.0 = fully dependent)
    frailty_index: float                   # 0.0–1.0 (0.0 = robust, 1.0 = severely frail)
    mobility: str                          # "independent" | "cane" | "walker" | "wheelchair" | "bedbound"
    cognitive_status: str                  # "normal" | "MCI" | "mild_dementia" | "moderate_dementia" | "severe_dementia"

    # Healthcare engagement
    care_seeking_threshold: float          # 0.0–1.0
    checkup_compliance: float
    checkup_type: str | None
    visit_time_constraint: str             # "any" | "weekday_only" | "weekend_holiday_only" | "evening_only" | "saturday_am_only"

    # Medication adherence pattern
    adherence_pattern: str                 # "full_compliance" | "good_when_symptomatic" | "cost_skipping" | "side_effect_avoidance" | "forgetful" | "weekend_holiday" | "alternative_substitution"

    # Lifestyle compliance
    diet_compliance: float                 # 0.0–1.0 (adherence to dietary recommendations)
    exercise_compliance: float             # 0.0–1.0
    smoking_cessation_success: bool | None # None if never counseled; True/False if counseled

    # End-of-life preferences
    advance_directive: AdvanceDirective | None  # None if not documented

    # Vaccination
    vaccination_history: list[VaccinationRecord]

    # Caregiver
    primary_caregiver: CaregiverInfo | None  # None if self-caring

    # Pregnancy state (females age 15–49)
    pregnancy_state: PregnancyState | None

    # Hospital history
    has_visited_hospital: bool
    last_visit_date: date | None
    visit_count: int
    active_patient_record_id: str | None

@dataclass
class AdvanceDirective:
    has_document: bool                     # legal document exists?
    code_status: str                       # "full_code" | "DNR" | "DNR_DNI" | "comfort_only"
    healthcare_proxy_id: str | None        # person_id of designated decision-maker
    preferences: dict                      # {"ventilator": bool, "dialysis": bool, "tube_feeding": bool, "cpr": bool}
    # JP: often verbal family consensus rather than written document
    # US: formal legal document (Advance Directive / POLST)

@dataclass
class VaccinationRecord:
    vaccine: str                           # "influenza" | "pneumococcal" | "covid19" | "hepatitis_b" | ...
    date: date
    dose_number: int                       # 1, 2, 3... (for multi-dose vaccines)

@dataclass
class CaregiverInfo:
    caregiver_person_id: str | None        # person_id if household member; None if professional
    caregiver_type: str                    # "spouse" | "adult_child" | "professional_home_helper" | "facility_staff"
    availability: str                      # "full_time" | "daytime_only" | "limited"
    capability: float                      # 0.0–1.0 (ability to manage medications, monitor symptoms, assist ADL)
    burden_level: float                    # 0.0–1.0 (caregiver stress/burnout)
```

### 0.3 LifeEvent

Produced by: `population`
Consumed by: `patient` (activation reason), `encounter` (encounter trigger), `disease` (disease event)

```python
@dataclass
class LifeEvent:
    event_id: str
    person_id: str
    timestamp: datetime
    event_type: LifeEventType
    severity: float                        # 0.0–1.0
    details: dict                          # event-type-specific data
    symptoms: list[Symptom]
    requires_hospital: bool | None         # None = care-seeking decision not yet made

class LifeEventType(str, Enum):
    ACUTE_DISEASE_ONSET = "acute_disease_onset"
    CHRONIC_EXACERBATION = "chronic_exacerbation"
    TRAUMA = "trauma"
    CHRONIC_DISEASE_NEW = "chronic_disease_new"
    CHRONIC_DISEASE_PROGRESSION = "chronic_disease_progression"
    CHRONIC_MANAGEMENT_VISIT = "chronic_management_visit"
    SEASONAL_ALLERGY_FLARE = "seasonal_allergy_flare"
    HEALTH_CHECKUP_SCHEDULED = "health_checkup_scheduled"
    HABITUAL_VISIT = "habitual_visit"
    FOLLOW_UP_DUE = "follow_up_due"
    SCREENING_ABNORMALITY = "screening_abnormality"
    # Pregnancy & reproduction
    PRENATAL_CHECKUP = "prenatal_checkup"
    PREGNANCY_LOSS = "pregnancy_loss"                      # miscarriage
    PREGNANCY_TERMINATION = "pregnancy_termination"        # induced abortion
    PRETERM_LABOR = "preterm_labor"
    DELIVERY = "delivery"                                  # term delivery
    NICU_ADMISSION = "nicu_admission"                      # newborn requiring NICU
    POSTPARTUM_CHECKUP = "postpartum_checkup"              # 1-month postpartum visit

@dataclass
class PregnancyState:
    conception_date: date
    estimated_due_date: date
    gestational_age_weeks: int
    pregnancy_risk: Literal["low", "moderate", "high"]
    planned: bool
    gravida: int                           # total number of pregnancies including current
    para: int                              # number of prior deliveries
    complications: list[str]               # active complications (gestational_diabetes, preeclampsia, etc.)
    delivery_mode: str | None              # None until delivery; "vaginal" | "cesarean_elective" | "cesarean_emergency"
```

### 0.4 CareSeekingDecision

Produced by: `population`
Consumed by: `encounter` (creates encounter), `patient` (triggers activation)

```python
@dataclass
class CareSeekingDecision:
    person_id: str
    life_event_id: str
    decision: Literal["no_action", "self_care", "primary_care", "hospital_outpatient", "hospital_er", "ambulance"]
    urgency: Literal["routine", "urgent", "emergency"]
    delay_hours: float                     # time between event and hospital arrival
    referral_context: ReferralContext | None
    is_transient_visitor: bool

@dataclass
class ReferralContext:
    referring_clinic_name: str
    referring_physician_name: str
    referral_date: date
    referral_reason: str
    prior_findings: list[str]
    prior_medications: list[str]
    urgency: str
```

---

## 1. Foundation Types

### 1.1 HealthcareSystemConfig

Produced by: `healthcare_system`
Consumed by: all modules

```python
@dataclass
class HealthcareSystemConfig:
    country: Literal["JP", "US"]

    # Insurance & access
    insurance_system: str                    # "NHI" | "private"
    gatekeeper: bool | str                   # False (JP) | "plan_dependent" (US)
    care_seeking_threshold: float            # 0.0–1.0 (lower = more willing to visit)

    # Clinical practice norms
    lab_frequency_multiplier: float          # 1.3 (JP), 0.8 (US)
    discharge_criteria: str                  # "lab_normalization" | "oral_tolerability"
    readmission_penalty: bool               # False (JP), True (US)
    target_los_multiplier: float            # 1.0 (JP), 0.35 (US) relative to disease baseline

    # Coding systems
    diagnosis_code_system: str              # "ICD-10" | "ICD-10-CM"
    drug_code_system: str                   # "YJ" | "RxNorm"
    lab_code_system: str                    # "JLAC10" | "LOINC"
    procedure_code_system: str             # "K-code" | "CPT"

    # Reimbursement
    reimbursement_system: str               # "DPC" | "DRG"

    # Demographics reference (for realistic population generation)
    population_age_sex_distribution: str    # reference to census data source
    blood_type_distribution: dict[str, float]  # e.g., {"A": 0.40, "O": 0.30, "B": 0.20, "AB": 0.10} (JP)
    comorbidity_prevalence: str             # reference to epidemiological data source
```

### 1.2 HospitalProfile

Produced by: `facility`
Consumed by: `staff`, `encounter`, `order`, `procedure`, `simulator`

```python
@dataclass
class HospitalProfile:
    hospital_id: str
    name: str
    scale: Literal["small", "medium", "large"]
    country: Literal["JP", "US"]

    departments: list[Department]
    total_bed_count: int
    equipment: list[Equipment]             # CT, MRI, cath_lab, etc.
    lab_capacity: LabCapacity              # laboratory processing capacity
    operating_rooms: int
    has_icu: bool
    has_emergency_dept: bool
    has_checkup_center: bool               # JP: 健診センター

    operating_hours: OperatingSchedule     # weekday/weekend/holiday patterns
    holiday_calendar: list[date]           # country-specific holidays

@dataclass
class Department:
    department_id: str
    name: str                              # localized (e.g., "内科" / "Internal Medicine")
    specialty: str                         # standardized specialty code
    subspecialties: list[str]
    bed_count: int
    has_outpatient_clinic: bool
    equipment: list[str]                   # department-specific equipment

@dataclass
class Equipment:
    type: str                              # "CT", "MRI", "xray", "ultrasound", "cath_lab", "endoscopy"
    count: int
    available_hours: str                   # "24/7" | "business_hours" | "on_call"
    throughput_per_day: int                # max exams/procedures per unit per day
    maintenance_schedule: str | None       # e.g., "first_monday_monthly"

@dataclass
class LabCapacity:
    in_house_menu: list[str]               # lab tests available in-house
    outsourced_menu: list[str]             # lab tests sent to external lab
    stat_available_24h: bool               # can process STAT labs at any hour?
    routine_batch_times: list[int]         # hours when routine batches run (e.g., [6, 10, 14, 18])
    outsource_turnaround_days: float       # typical turnaround for outsourced tests

@dataclass
class OperatingSchedule:
    weekday_hours: tuple[int, int]         # (8, 17)
    weekend_coverage: str                  # "full" | "on_call" | "emergency_only"
    holiday_calendar: str                  # reference to country-specific holiday list
```

---

## 2. People Types

### 2.1 PatientProfile

Produced by: `patient`
Consumed by: `encounter`, `disease`, `diagnosis`, `physiology`, `treatment`, `nursing`, `procedure`, `output`

```python
@dataclass
class PatientProfile:
    patient_id: str
    
    # Demographics — must follow real-world distributions
    age: int
    sex: Literal["M", "F"]
    date_of_birth: date
    blood_type: Literal["A", "B", "O", "AB"]
    rh_factor: Literal["+", "-"]
    height_cm: float
    weight_kg: float
    bmi: float

    # Social context
    region: str                            # residential area
    employment_status: str                 # "employed" | "retired" | "unemployed" | "student"
    living_situation: str                  # "alone" | "with_spouse" | "with_family" | "facility"
    transportation_access: str             # "car" | "public_transit" | "limited"
    insurance_type: str                    # country-specific (JP: "NHI_employee" | "NHI_self" | "late_elderly"; US: "commercial_HMO" | "commercial_PPO" | "Medicare" | "Medicaid" | "uninsured")
    health_literacy: float                 # 0.0–1.0

    # Healthcare engagement behavior
    care_seeking_threshold: float          # 0.0–1.0 (lower = visits sooner)
    checkup_compliance: float              # 0.0–1.0 (probability of attending annual checkup)
    checkup_type: str | None               # JP: "corporate" | "municipal" | "ningen_dock" | None
    follow_up_compliance: float            # 0.0–1.0 (probability of attending scheduled follow-ups)
    adherence_pattern: MedicationAdherencePattern
    diet_compliance: float                 # 0.0–1.0
    exercise_compliance: float             # 0.0–1.0

    # Functional status (detailed, from Layer 1 + expansion)
    adl_score: ADLScore                    # detailed ADL assessment
    frailty_index: float                   # 0.0–1.0
    mobility: str
    cognitive_status: str
    fall_risk: str                         # "low" | "moderate" | "high" (derived from age, mobility, medications, cognition)

    # Mental health (expanded from Layer 1)
    mental_health_conditions: list[MentalHealthCondition]

    # End-of-life preferences
    advance_directive: AdvanceDirective | None

    # Vaccination history
    vaccination_history: list[VaccinationRecord]

    # Caregiver
    primary_caregiver: CaregiverInfo | None

    # Medical history
    chronic_conditions: list[ChronicCondition]
    surgical_history: list[PastSurgery]
    allergies: list[Allergy]
    family_history: list[FamilyHistoryItem]
    current_medications: list[Medication]
    smoking_status: str                    # "never" | "former" | "current"
    alcohol_use: str                       # "none" | "social" | "heavy"

    # Hidden physiological constitution (not directly observable)
    physiological_profile: PatientPhysiologicalProfile

    # Baseline vitals (healthy state for this individual)
    baseline_vitals: BaselineVitals

@dataclass
class PatientPhysiologicalProfile:
    """Determined once at patient creation. Governs all subsequent responses."""
    immune_reactivity: float               # Beta(5,5) → 0.0–1.0
    drug_metabolism_rate: Literal["poor", "normal", "rapid", "ultra_rapid"]
    renal_reserve: float                   # Beta(8,2) + age adjustment → 0.0–1.0
    cardiac_reserve: float                 # Beta(8,2) + age adjustment → 0.0–1.0
    hepatic_reserve: float                 # Beta(8,2) + age adjustment → 0.0–1.0
    treatment_sensitivity: float           # Normal(1.0, σ)
    symptom_reporting_bias: float          # Normal(1.0, 0.3)
    delirium_susceptibility: float         # Beta(2,8) → 0.0–1.0
    dvt_susceptibility: float              # Beta(2,8) → 0.0–1.0

@dataclass
class ChronicCondition:
    code: str                              # ICD-10 / ICD-10-CM
    name: str
    onset_date: date
    severity: str                          # "mild" | "moderate" | "severe"
    controlled: bool                       # currently well-managed?

@dataclass
class Allergy:
    substance: str
    reaction_type: str                     # "anaphylaxis" | "rash" | "GI" | "other"
    severity: str                          # "mild" | "moderate" | "severe"

@dataclass
class BaselineVitals:
    """This person's normal values when healthy."""
    temperature: float                     # °C, typically 36.0–36.8
    heart_rate: int                        # bpm
    systolic_bp: int                       # mmHg
    diastolic_bp: int                      # mmHg
    respiratory_rate: int                  # breaths/min
    spo2: float                            # %, typically 96–99
@dataclass
class MedicationAdherencePattern:
    pattern_type: str                      # "full_compliance" | "good_when_symptomatic" | "cost_skipping" | "side_effect_avoidance" | "forgetful" | "weekend_holiday" | "alternative_substitution"
    effective_adherence_rate: float         # 0.0–1.0 (net effect on medication effectiveness)
    description: str                       # human-readable for audit

    # Pattern-specific parameters
    skip_probability_per_dose: float       # for "forgetful": probability of missing each dose
    cost_threshold_monthly: float | None   # for "cost_skipping": $ amount above which skipping begins (US)
    symptom_driven: bool                   # for "good_when_symptomatic": stops when feeling better

@dataclass
class ADLScore:
    """Barthel Index-style ADL scoring (0–100)"""
    feeding: int                           # 0 (unable), 5 (needs help), 10 (independent)
    bathing: int                           # 0 or 5
    grooming: int                          # 0 or 5
    dressing: int                          # 0, 5, or 10
    bowel_control: int                     # 0, 5, or 10
    bladder_control: int                   # 0, 5, or 10
    toileting: int                         # 0, 5, or 10
    transfer: int                          # 0, 5, 10, or 15
    mobility: int                          # 0, 5, 10, or 15
    stairs: int                            # 0, 5, or 10
    total_score: int                       # 0–100 (100 = fully independent)

@dataclass
class MentalHealthCondition:
    condition: str                         # "depression" | "dementia" | "anxiety" | "schizophrenia" | "alcohol_dependence" | "insomnia"
    severity: str                          # "mild" | "moderate" | "severe"
    on_treatment: bool
    current_medications: list[str]         # psychiatric medications
    # Impact on medical behavior
    impacts: dict                          # {"adherence_modifier": 0.7, "care_seeking_modifier": 1.3, ...}
```

### 2.2 StaffProfile

Produced by: `staff`
Consumed by: `encounter`, `order`, `nursing`, `procedure`, `output`

```python
@dataclass
class StaffProfile:
    staff_id: str
    name: PersonName
    role: StaffRole
    department_id: str
    specialty: str
    subspecialties: list[str]
    qualification_year: int                # year of primary qualification
    credentials: list[str]                 # board certifications, licenses
    active_period: tuple[date, date | None]  # (start, end or None if current)

@dataclass
class PersonName:
    """Country-appropriate name representation."""
    family_name: str
    given_name: str
    display_name: str                      # formatted for display (JP: 姓名, US: Given Family)
    prefix: str | None                     # "Dr.", "Prof." etc.

class StaffRole(str, Enum):
    ATTENDING_PHYSICIAN = "attending_physician"
    FELLOW = "fellow"
    RESIDENT = "resident"
    NURSE_RN = "nurse_rn"
    NURSE_NP = "nurse_np"
    CHARGE_NURSE = "charge_nurse"
    LAB_TECHNICIAN = "lab_technician"
    RADIOLOGY_TECHNICIAN = "radiology_technician"
    RADIOLOGIST = "radiologist"
    PHARMACIST = "pharmacist"
    PHYSICAL_THERAPIST = "physical_therapist"
    OCCUPATIONAL_THERAPIST = "occupational_therapist"
    SPEECH_THERAPIST = "speech_therapist"
    SOCIAL_WORKER = "social_worker"
    DIETITIAN = "dietitian"
    ANESTHESIOLOGIST = "anesthesiologist"
    MIDWIFE = "midwife"
    NEONATOLOGIST = "neonatologist"
```

### 2.3 StaffAssignment

Produced by: `staff`
Consumed by: `output`, `validator`

```python
@dataclass
class StaffAssignment:
    """Links a staff member to a clinical event with a specific role."""
    event_id: str
    staff_id: str
    role_in_event: str                     # "ordering_physician" | "performing_nurse" | "interpreting_radiologist" | ...
    timestamp: datetime
```

---

## 3. Clinical State Types

### 3.1 PhysiologicalState

Produced by: `physiology`
Consumed by: `observation`, `nursing`, `clinical_course`, `treatment`, `validator`

```python
@dataclass
class PhysiologicalState:
    """Snapshot of all hidden state variables at a point in time."""
    timestamp: datetime
    patient_id: str

    inflammation_level: float              # 0.0–1.0
    renal_function: float                  # 0.0–1.0
    cardiac_function: float                # 0.0–1.0
    hepatic_function: float                # 0.0–1.0
    anemia_level: float                    # 0.0–1.0
    coagulation_status: float              # 0.0–1.0
    volume_status: float                   # -1.0–+1.0
    perfusion_status: float                # 0.0–1.0
    ph_status: float                       # -1.0–+1.0  (acid-base disturbance magnitude)
    respiratory_fraction: float            # 0.0–1.0    (0=metabolic/HCO3, 1=respiratory/pCO2)
```

### 3.2 StateChangeDirective

Produced by: `clinical_course`
Consumed by: `physiology`

```python
@dataclass
class StateChangeDirective:
    """Instruction to update physiological state variables."""
    timestamp: datetime
    patient_id: str
    source: str                            # "disease_progression" | "treatment_effect" | "complication" | "procedure"
    changes: dict[str, float]              # variable_name → delta (e.g., {"inflammation_level": -0.05})
    reason: str                            # human-readable reason for audit trail
```

---

## 4. Disease & Diagnosis Types

### 4.1 DiseaseEvent

Produced by: `disease`
Consumed by: `encounter`, `diagnosis`, `clinical_course`

```python
@dataclass
class DiseaseEvent:
    event_id: str
    patient_id: str
    disease_code: str                      # disease module identifier (e.g., "bacterial_pneumonia")
    icd_code: str                          # ICD-10 code
    severity: Literal["mild", "moderate", "severe"]
    onset_datetime: datetime
    trigger: str                           # "primary" | "complication" | "acute_on_chronic"
    presenting_symptoms: list[Symptom]
    course_archetype: str                  # selected clinical course archetype

@dataclass
class Symptom:
    name: str                              # "fever", "cough", "dyspnea", etc.
    severity: float                        # 0.0–1.0
    onset_datetime: datetime
```

### 4.2 DifferentialDiagnosis

Produced by: `diagnosis`
Consumed by: `treatment`, `order`, `output`

```python
@dataclass
class DifferentialDiagnosis:
    """Probability distribution over candidate diagnoses at a point in time."""
    timestamp: datetime
    patient_id: str
    encounter_id: str
    candidates: list[DiagnosisCandidate]
    working_diagnosis: str | None          # current best guess (may be None early on)
    confirmed: bool                        # has the diagnosis been confirmed?

@dataclass
class DiagnosisCandidate:
    disease_code: str
    icd_code: str
    display_name: str
    probability: float                     # 0.0–1.0, all candidates sum to 1.0
    evidence: list[str]                    # reasons supporting this diagnosis
```

---

## 5. Encounter & Workflow Types

### 5.1 Encounter

Produced by: `encounter`
Consumed by: `order`, `nursing`, `procedure`, `diagnosis`, `treatment`, `output`

```python
@dataclass
class Encounter:
    encounter_id: str
    patient_id: str
    episode_id: str                        # links related encounters (ED → inpatient → follow-up)
    encounter_type: EncounterType
    status: EncounterStatus
    department_id: str
    attending_physician_id: str
    admission_datetime: datetime
    discharge_datetime: datetime | None
    bed_id: str | None                     # None for outpatient
    chief_complaint: str
    
    # Simulation resolution
    time_resolution: timedelta | None      # None = snapshot (outpatient/checkup); 15min (ICU), 30min (ED), 1h (inpatient), 1day (rehab)
    
    # Linked disease event
    disease_event_id: str
    
    # Transitions
    previous_encounter_id: str | None      # e.g., ED encounter before inpatient
    next_encounter_id: str | None

class EncounterType(str, Enum):
    OUTPATIENT = "outpatient"
    EMERGENCY = "emergency"
    INPATIENT = "inpatient"
    ICU = "icu"
    DAY_SURGERY = "day_surgery"
    REHAB_INPATIENT = "rehab_inpatient"
    PRENATAL_VISIT = "prenatal_visit"
    DELIVERY = "delivery"
    NICU = "nicu"
    ABORTION_PROCEDURE = "abortion_procedure"

class EncounterStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
```

### 5.2 Order

Produced by: `order` (triggered by `diagnosis`, `treatment`, `nursing`)
Consumed by: `observation`, `nursing`, `procedure`, `staff`, `output`

```python
@dataclass
class Order:
    order_id: str
    encounter_id: str
    patient_id: str
    
    order_type: OrderType
    order_code: str                        # LOINC/JLAC10 for labs, CPT/K-code for procedures, RxNorm/YJ for meds
    display_name: str
    urgency: Literal["stat", "urgent", "routine"]
    clinical_intent: str                   # why this was ordered (traceable reasoning)
    
    # Lifecycle timestamps
    ordered_datetime: datetime
    ordered_by: str                        # staff_id
    accepted_datetime: datetime | None
    executed_datetime: datetime | None
    resulted_datetime: datetime | None
    reviewed_datetime: datetime | None
    reviewed_by: str | None                # staff_id
    
    status: OrderStatus
    
    # For medication orders
    medication_details: MedicationOrderDetail | None
    
    # Result (populated when resulted)
    result: OrderResult | None

class OrderType(str, Enum):
    LAB = "lab"
    IMAGING = "imaging"
    MEDICATION = "medication"
    PROCEDURE = "procedure"
    CONSULTATION = "consultation"
    DIET = "diet"
    THERAPY = "therapy"                    # PT, OT, ST

class OrderStatus(str, Enum):
    DRAFT = "draft"
    PLACED = "placed"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    RESULTED = "resulted"
    REVIEWED = "reviewed"
    CANCELLED = "cancelled"

@dataclass
class OrderTimeline:
    """Calculated timestamps for order lifecycle transitions."""
    collection_time: datetime              # specimen collected / imaging performed / med administered
    result_time: datetime | None           # lab result available / imaging report ready (None for meds)
    review_time: datetime | None           # physician review time
    outsourced: bool = False
    deferred_reason: str | None = None     # "night_routine_deferred" etc.

@dataclass
class InterventionEffect:
    """Immediate physiological effect of a treatment intervention (used by physiology module)."""
    type: str                              # "iv_fluid_bolus" | "blood_transfusion" | "vasopressor_start" | "diuretic_dose" | "intubation" | ...
    timestamp: datetime
    details: dict                          # intervention-specific parameters (volume, dose, etc.)

@dataclass
class MedicationOrderDetail:
    drug_code: str                         # RxNorm / YJ code
    drug_name: str
    dose: float
    dose_unit: str
    route: str                             # "IV" | "PO" | "IM" | "SC" | ...
    frequency: str                         # "q6h" | "q8h" | "once" | "PRN" | ...
    duration: str | None                   # "5 days" | "until_discharge" | None (ongoing)

@dataclass
class OrderResult:
    result_datetime: datetime
    performed_by: str                      # staff_id
    value: str | float | None              # lab value, or None for non-quantitative
    unit: str | None
    reference_range: str | None            # "0.0–0.3 mg/dL"
    flag: str | None                       # "H" | "L" | "critical" | None
    interpretation: str | None             # for imaging/pathology: narrative finding
    specimen_note: str | None              # "hemolyzed", "lipemic", etc.
```

---

## 6. Clinical Event Types

### 6.1 ClinicalEvent

A generic wrapper for any event that occurs during an encounter. Specific event types embed their details.

Produced by: various modules
Consumed by: `validator`, `output`

```python
@dataclass
class ClinicalEvent:
    event_id: str
    encounter_id: str
    patient_id: str
    event_type: ClinicalEventType
    timestamp: datetime
    staff_assignments: list[StaffAssignment]
    
    # Exactly one of these is populated, depending on event_type
    vital_signs: VitalSignRecord | None
    lab_result: OrderResult | None
    medication_administration: MedicationAdministration | None
    nursing_assessment: NursingAssessment | None
    procedure_record: ProcedureRecord | None
    encounter_transition: EncounterTransition | None
    note: ClinicalNote | None

class ClinicalEventType(str, Enum):
    VITAL_SIGNS = "vital_signs"
    LAB_RESULT = "lab_result"
    IMAGING_RESULT = "imaging_result"
    MEDICATION_ADMINISTRATION = "medication_administration"
    NURSING_ASSESSMENT = "nursing_assessment"
    PROCEDURE = "procedure"
    ENCOUNTER_TRANSITION = "encounter_transition"     # admission, transfer, discharge
    CONSULTATION = "consultation"
    NOTE = "note"                                     # progress note, discharge summary, etc.
```

### 6.2 VitalSignRecord

Produced by: `nursing`
Consumed by: `clinical_course`, `diagnosis`, `validator`, `output`

```python
@dataclass
class VitalSignRecord:
    temperature_celsius: float | None
    heart_rate: int | None
    systolic_bp: int | None
    diastolic_bp: int | None
    respiratory_rate: int | None
    spo2: float | None
    pain_score: int | None                 # NRS 0–10
    consciousness: str | None              # GCS or AVPU
    urine_output_ml: float | None          # per hour, if monitored
    
    measurement_site: str | None           # "axillary" | "oral" | "tympanic" (for temp)
    o2_delivery: str | None                # "room_air" | "nasal_2L" | "mask_5L" | ...
    
    # Data origin metadata
    data_source: Literal["manual", "device_auto"]  # how this data was captured
    device_id: str | None                  # device identifier (if device_auto)
    recorded_by: str | None                # nurse staff_id (manual) or verifier (device_auto)
    artifact: bool                         # True if device artifact (motion, disconnect)
    precision_level: Literal["standard", "high"]  # manual: rounded; device: precise

@dataclass
class DeviceReading:
    """Auto-generated reading from a medical device (ICU, telemetry, POCT)."""
    device_type: str                       # "bedside_monitor" | "infusion_pump" | "glucometer" | "ventilator"
    device_id: str
    patient_id: str
    timestamp: datetime                    # precise (device clock)
    parameters: dict[str, float]           # {"HR": 78, "SpO2": 96.2}
    alarm_status: str | None               # "high_HR" | "low_SpO2" | None
    verified_by: str | None                # nurse staff_id
    artifact: bool

@dataclass
class POCTResult:
    """Point-of-care test result (glucometer, blood gas analyzer, etc.)."""
    device_type: str
    device_id: str
    operator_id: str                       # nurse/RT who ran the test
    patient_id: str
    patient_id_method: str                 # "barcode_scan" | "manual_entry"
    timestamp: datetime
    turnaround_minutes: float              # typically 1–5 min
    analyte: str
    value: float
    unit: str
    qc_passed: bool
```

### 6.3 MedicationAdministration

Produced by: `nursing`
Consumed by: `treatment`, `output`

```python
@dataclass
class MedicationAdministration:
    order_id: str                          # links to the medication order
    scheduled_datetime: datetime
    actual_datetime: datetime | None
    status: Literal["given", "held", "refused", "not_available"]
    dose_given: float | None
    route: str
    administered_by: str                   # staff_id (nurse)
    hold_reason: str | None                # if held: "low_BP", "NPO", etc.
    refusal_reason: str | None             # if refused: patient declined
    notes: str | None
```

### 6.4 NursingAssessment

Produced by: `nursing`
Consumed by: `output`

```python
@dataclass
class NursingAssessment:
    assessment_type: str                   # "shift_assessment" | "focused" | "admission" | "discharge"
    pain: PainAssessment | None
    neurological: str | None               # GCS, orientation
    respiratory: str | None                # breath sounds, O2 status
    cardiovascular: str | None             # heart sounds, edema, pulses
    gastrointestinal: str | None           # bowel sounds, intake/output
    skin: str | None                       # integrity, wounds, Braden score
    mobility: str | None                   # fall risk (Morse), activity level
    psychosocial: str | None               # anxiety, sleep, family

@dataclass
class PainAssessment:
    score: int                             # NRS 0–10
    location: str | None
    character: str | None                  # "sharp" | "dull" | "aching" | ...
    intervention: str | None               # what was done about it
```

### 6.5 ProcedureRecord

Produced by: `procedure`
Consumed by: `output`

```python
@dataclass
class ProcedureRecord:
    procedure_code: str                    # Primary CPT (US) / K-code (JP)
    procedure_code_jp: str                 # K-code (always populated if available)
    procedure_code_us: str                 # CPT (always populated if available)
    # NOTE: Per AD-30, display name is NOT stored. Resolve via
    # code_lookup("k-codes"|"cpt", code, lang) at output time.
    category: str                          # "major_surgery" | "minor" | "endoscopy" | "bedside"
    
    # Timing
    start_datetime: datetime
    end_datetime: datetime
    anesthesia_type: str | None            # "general" | "spinal" | "local" | "sedation"
    
    # Team
    primary_surgeon_id: str
    assistant_ids: list[str]
    anesthesiologist_id: str | None
    
    # Findings
    findings: str                          # structured or narrative
    estimated_blood_loss_ml: int | None
    specimens_sent: list[str]              # pathology specimens
    implants_used: list[str] | None
    complications: list[str]               # intraoperative complications
    
    # Pre-op
    asa_class: int                         # 1–5
    informed_consent_datetime: datetime
```

### 6.6 EncounterTransition

Produced by: `encounter`
Consumed by: `output`

```python
@dataclass
class EncounterTransition:
    transition_type: Literal["admission", "transfer", "discharge", "death"]
    from_location: str | None              # department/bed, or None for new admission
    to_location: str | None                # department/bed, or None for discharge
    reason: str                            # "ED disposition: admit" | "ICU step-down" | "discharge home" | ...
    discharge_disposition: str | None      # "home" | "SNF" | "rehab" | "transfer" | "expired" (discharge only)
    discharge_instructions: str | None
    follow_up_plan: str | None             # "outpatient in 2 weeks" etc.
```

### 6.7 ClinicalNote

Produced by: various modules
Consumed by: `output`

```python
@dataclass
class ClinicalNote:
    note_type: NoteType
    author_id: str                         # staff_id
    content: str                           # structured or semi-structured text
    
class NoteType(str, Enum):
    ADMISSION_HP = "admission_hp"          # History & Physical
    PROGRESS_NOTE = "progress_note"        # Daily physician note
    CONSULTATION = "consultation"          # Specialist consultation
    DISCHARGE_SUMMARY = "discharge_summary"
    OPERATIVE_NOTE = "operative_note"
    NURSING_NOTE = "nursing_note"
    SHIFT_HANDOFF = "shift_handoff"
```

---

## 7. LLM Integration Types

All LLM interaction goes through `llm_service.generate()`. Modules pass structured data only — they never write prompts or choose models.

### 7.1 ClinicalEventData (what modules pass to llm_service)

Produced by: any module at an LLM invocation point
Consumed by: `llm_service` (and only llm_service)

```python
@dataclass
class ClinicalEventData:
    """Structured event data. Modules pass WHAT happened; llm_service decides HOW to describe it."""
    patient_summary: PatientSummary
    event_data: dict                       # task-type-specific structured data (schema defined in prompt YAML)
    language: str                          # "ja" | "en" (determined by country)

@dataclass
class PatientSummary:
    """Compact patient representation (~150 tokens). Built once per encounter, reused."""
    age: int
    sex: str
    country: str
    chief_complaint: str
    relevant_conditions: list[str]
    relevant_medications: list[str]
    allergies: list[str]
    current_diagnosis: str
    diagnosis_confidence: float
    hospital_day: int
    department: str
    hospital_type: str
```

### 7.2 LLMTaskType (what kinds of generation are available)

```python
class LLMTaskCategory(str, Enum):
    JUDGMENT = "judgment"      # Always English. Structured decisions. Language-independent.
    NARRATIVE = "narrative"    # Output in target country language. Clinical documents for EHR.

class LLMTaskType(str, Enum):
    # JUDGMENT tasks (always English, structured response)
    DIAGNOSTIC_REASONING = "diagnostic_reasoning"
    TREATMENT_DECISION = "treatment_decision"
    CLINICAL_JUDGMENT = "clinical_judgment"
    CONSISTENCY_REVIEW = "consistency_review"
    CARE_SEEKING_JUDGMENT = "care_seeking_judgment"
    # NARRATIVE tasks (output in target language: ja / en)
    CHIEF_COMPLAINT = "chief_complaint"
    ADMISSION_HP = "admission_hp"
    PROGRESS_NOTE = "progress_note"
    DISCHARGE_SUMMARY = "discharge_summary"
    CONSULTATION_NOTE = "consultation_note"
    OPERATIVE_NOTE = "operative_note"
    NURSING_NOTE = "nursing_note"
    REFERRAL_LETTER = "referral_letter"
    MEDICATION_INSTRUCTION = "medication_instruction"
```

### 7.3 LLMResponse (what modules get back)

```python
@dataclass
class LLMResponse:
    text: str | None                       # None if mode="none"
    source: Literal["llm", "template", "cache", "none"]
    model: str | None
    # For judgment tasks (populated by llm_service's response parser)
    chosen_option: str | None
    reasoning: str | None
    confidence: float | None
    additional_actions: list[str] | None
    # For consistency review
    issues: list[ConsistencyIssue] | None
    # Cost (tracked by llm_service)
    input_tokens: int | None
    output_tokens: int | None

@dataclass
class ConsistencyIssue:
    severity: Literal["critical", "minor", "cosmetic"]
    description: str
    affected_events: list[str]
    suggestion: str
```

Note: `LLMRequest`, prompt templates, model tier selection, `NarrativeRequest`, `ClinicalJudgmentRequest`, `ConsistencyReviewRequest` are all **internal to llm_service** — other modules never see them. The only public interface is `llm_service.generate(task_type, event_data) → LLMResponse`.

---

## 8. Output Types

### 7.1 PatientRecord

Produced by: `simulator` (aggregated from all modules)
Consumed by: `output`

```python
@dataclass
class CIFPatientRecord:
    """Complete patient record for CIF (Clinosim Intermediate Format).
    Contains ALL data including hidden state, LLM provenance, and metadata.
    Format adapters select the subset relevant to their target format."""
    
    # Clinical data
    patient: PatientProfile
    encounters: list[Encounter]
    events: list[ClinicalEvent]            # all events, chronologically ordered
    orders: list[Order]
    staff_assignments: list[StaffAssignment]
    differential_history: list[DifferentialDiagnosis]
    device_readings: list[DeviceReading]
    prescriptions: list                    # PrescriptionJP | PrescriptionUS
    consents: list[ConsentRecord]
    rehab_sessions: list                   # RehabSession (if applicable)
    
    # Hidden / debug data (preserved in CIF, not exported to clinical formats)
    physiological_states: list[PhysiologicalState]
    disease_event: DiseaseEvent
    llm_calls: list[dict]                  # provenance: task_type, source, model, tokens
```
