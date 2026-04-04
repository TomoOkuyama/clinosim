# encounter — Encounter Types & Workflow State Machines

## Purpose
Define the types of clinical encounters (outpatient, ED, inpatient, ICU, day surgery, rehab) and manage their workflow as state machines. Each encounter type determines the sequence of events, documentation requirements, and transitions to other encounter types.

## Inputs
- `PatientProfile`: Patient context (age, condition, insurance)
- `DiseaseEvent`: What brought the patient to the hospital
- `HealthcareSystemConfig`: Country-specific encounter patterns
- `HospitalProfile`: Available departments, beds, equipment (Mode 2: current availability)

## Outputs
- `Encounter`: A structured encounter record with type, timestamps, and current state
- `EncounterEvent`: Discrete events within the encounter (registration, triage, assessment, transfer, discharge)
- `EncounterTransition`: Transition from one encounter to another (ED → inpatient, ward → ICU)
- `DocumentationRequirement`: What records must be generated at each stage

## Dependencies
- `patient` (patient context)
- `disease` (reason for encounter)
- `facility` (department/bed availability)
- `healthcare_system` (encounter-type norms per country)
- `staff` (staff assignment at each workflow step)

## Confirmed Specifications

### Encounter types

| Type | Trigger | Typical duration | Key workflow steps |
|---|---|---|---|
| `outpatient` | Scheduled visit, follow-up | 30min–2h | Check-in → wait → consultation → orders → checkout |
| `emergency` | Acute symptoms, referral | 2–8h | Registration → triage → assessment → workup → disposition |
| `inpatient` | Admission (from ED or elective) | Days–weeks | Admission → daily rounds → treatment → discharge planning → discharge |
| `icu` | Severity escalation | Hours–days | Transfer-in → intensive monitoring → stabilization → step-down |
| `day_surgery` | Scheduled procedure | 4–12h | Pre-op check-in → procedure → recovery → same-day discharge |
| `rehab_inpatient` | Post-acute recovery | Weeks–months | Transfer from acute → rehab program → functional goals → discharge |
| `prenatal_visit` | Scheduled prenatal checkup | 30min–1h | Check-in → vitals/weight → urine → ultrasound(periodic) → consultation → checkout |
| `delivery` | Labor onset or scheduled C-section | Hours–days | Admission → labor/C-section → delivery → postpartum → discharge |
| `nicu` | Newborn requiring intensive care | Days–weeks | Admission → stabilization → monitoring → growth → discharge |
| `abortion_procedure` | Induced termination | 2–6h | Consent → procedure → recovery → discharge (day surgery or short stay) |

### Encounter workflow state machines

#### Outpatient
```
scheduled → checked_in → waiting → in_consultation → orders_pending → checkout → completed
                                        ↓
                                  referral_generated → new encounter (specialist/ED/admission)
```

#### Emergency Department
```
arrival → registered → triage → waiting → assessment → workup_in_progress
    → disposition_decision
        ├── discharge_from_ed → completed
        ├── admit_to_ward → triggers inpatient encounter
        ├── admit_to_icu → triggers ICU encounter
        └── transfer_to_other_facility → completed (with transfer record)
```

#### Inpatient
```
admission → initial_assessment → active_treatment
    → daily_cycle (rounds → orders → treatment → nursing_assessment → ...)
    → discharge_planning → discharge_ready → discharged → completed
        ↓ (if deterioration)
    → icu_transfer → triggers ICU encounter
        ↓ (if complication)
    → department_transfer → continues inpatient in new department
```

#### ICU
```
transfer_in → stabilization → intensive_monitoring
    → daily_cycle (frequent vitals → assessments → adjustments)
    → step_down_ready → ward_transfer → triggers inpatient encounter (continued)
        ↓ (if further deterioration)
    → end_of_life_care or continued ICU
```

#### Day Surgery
```
pre_op_checkin → pre_op_assessment → to_operating_room
    → procedure (handled by procedure module)
    → recovery_room → post_op_assessment → same_day_discharge → completed
        ↓ (if complication)
    → admit_to_ward → triggers inpatient encounter
```

### Encounter transitions

A single patient episode may span multiple encounter types:

```
Typical emergency pneumonia:
  outpatient (GP visit, referral) → emergency (ED workup) → inpatient (ward stay) → outpatient (follow-up)

Typical hip fracture:
  emergency (fall, ER) → inpatient (surgery + acute care) → rehab_inpatient → outpatient (follow-up)

Typical elective surgery:
  outpatient (pre-op assessment) → day_surgery or inpatient → outpatient (follow-up)

Deterioration:
  inpatient → icu → inpatient (step-down) → discharge
```

### Documentation generated per encounter type

| Encounter type | Required documentation |
|---|---|
| outpatient | Visit note, orders, prescriptions, referral letters |
| emergency | Triage record, ED physician note, disposition note |
| inpatient | Admission H&P, daily progress notes, discharge summary |
| icu | Hourly/q15min flow sheets, procedure notes, transfer summary |
| day_surgery | Pre-op checklist, anesthesia record, procedure note, recovery note |
| rehab_inpatient | Rehab plan, progress assessments, functional outcome scores |

### Mode 1 vs Mode 2 differences

| Aspect | Mode 1 | Mode 2 |
|---|---|---|
| Bed assignment | Always available | Constrained by occupancy |
| ED wait time | Nominal (based on triage level) | Depends on current ED volume |
| OR scheduling | Immediate for simulation | Competes with other patients |
| Department transfer | Instant | May wait for bed availability |
| Concurrent encounters | Not modeled | Multiple patients interact |

### Temporal variation in encounter patterns

Encounter volume and mix fluctuate with time. The encounter module must model these patterns:

#### Seasonal encounter volume
- **Winter**: Higher total admissions (respiratory infections, cardiac events); higher bed occupancy
- **Summer**: Higher ED trauma, heatstroke; lower elective admissions; vacation-driven discharge push
- **Year-end/New Year (JP)**: Minimal elective activity Dec 29–Jan 3; ED-only
- **Golden Week (JP, late April–early May)**: Similar to year-end
- **Fiscal year start (JP, April)**: New resident doctors; longer encounter times; higher error rates

#### Day-of-week patterns
- **Weekday**: Full outpatient clinics + elective admissions + scheduled procedures
- **Saturday AM (JP)**: Saturday morning outpatient clinics (08:30–12:30). Major access point for working adults. Reduced staff, no elective procedures. High outpatient volume relative to weekday (concentrated in half-day).
- **Saturday AM (US)**: Some urgent care / walk-in clinics. Not typical for hospital outpatient.
- **Weekend (rest)**: ED-only new encounters; inpatient care continues with reduced staffing
- **Monday**: Surge in outpatient and ED (deferred weekend symptoms)
- **Friday**: Discharge push
- **National holidays**: Treated as weekend (see `healthcare_system` holiday calendar). Extended holidays (年末年始, GW) are emergency-only.
- **Pre-holiday**: Slight increase in outpatient (patients want to be seen before closure)

#### Time-of-day patterns
- Outpatient clinics: 08:30–12:00 and 13:00–17:00 (JP); 08:00–17:00 (US)
- ED: 24/7 but volume peaks 18:00–22:00
- Admissions from ED: often happen 20:00–02:00 (after workup complete)
- Discharges: typically 10:00–14:00

### Health checkup encounters (Japan-specific)

Annual health checkups (健康診断) are a major encounter type in Japanese hospitals:

| Type | Target population | Frequency | Typical timing |
|---|---|---|---|
| 特定健診 (Specific health checkup) | Age 40–74, NHI insured | Annual | May–October peak |
| 企業健診 (Corporate checkup) | Employed workers | Annual (mandatory) | Varies by company, often Apr–Sep |
| 人間ドック (Comprehensive checkup) | Self-selected (often age 50+) | Annual or less | Year-round, booking 1–3 months ahead |
| 後期高齢者健診 | Age 75+ | Annual | Year-round |
| がん検診 (Cancer screening) | Age/sex-dependent | Annual or biennial | Municipal schedule |

#### Health checkup workflow
```
booking → check_in → measurements (height, weight, BP, vision, hearing)
  → blood draw → urinalysis → chest X-ray → ECG (age-dependent)
  → physician consultation (brief) → checkout
  → results mailed in 2–4 weeks
  → abnormal findings → recommendation letter → clinical encounter
```

#### Checkup compliance patterns (realism)
Not all eligible individuals attend every year:
- **Regular attendees** (~60%): Come every year as scheduled
- **Occasional attendees** (~25%): Come every 2–3 years, skip sometimes
- **Non-attendees** (~15%): Rarely or never come

Compliance correlates with:
- Employment status (employed → higher, mandatory corporate checkup)
- Age (middle-aged → higher; very elderly → lower mobility)
- Health literacy (higher → more likely to attend)
- Prior abnormal findings (some become more diligent, others avoid)

#### Impact on simulation
- Health checkups consume lab and imaging capacity (especially morning blood draws)
- Abnormal findings generate follow-up clinical encounters (typically 5–10% of checkups)
- Checkup data provides longitudinal "healthy baseline" records for patients who later develop disease
- Seasonal checkup volume creates resource contention with clinical care

---

## Internal Design

### Core Concept: Encounter as Timeline Driver

The encounter module generates a **timeline of events** by walking a state machine. At each state, it calls other modules to generate clinical content. This is the central orchestration logic within a single patient's hospital visit.

```
Encounter state machine (determines WHEN)
  ↓ at each state transition
Calls other modules (determine WHAT):
  - diagnosis: update differential
  - order: place orders
  - treatment: adjust medications
  - nursing: schedule assessments, vitals
  - procedure: run surgical workflow
  - staff: assign practitioners
```

### Simulation Time Resolution per Encounter Type

The same `PatientProfile` + `PhysiologicalState` data structure is used for all encounter types. What differs is how frequently the state is updated and how much clinical detail is generated. This avoids unnecessary layer complexity while reflecting real-world differences.

| Encounter type | State update interval | Vitals frequency | Lab generation | Clinical detail level |
|---|---|---|---|---|
| `health_checkup` | None (single snapshot) | Once (check-in) | One-time panel | Minimal — measurements + results only |
| `outpatient` | None (single snapshot) | Once (check-in) | If ordered | Low — consultation note + orders |
| `inpatient` | 1 hour | q4h–q8h (nursing) | Per protocol (daily/EOD) | Full — daily cycle, all modules active |
| `emergency` | 30 minutes | q30min–q1h | STAT on arrival + as needed | High — rapid workup, disposition |
| `icu` | 15 minutes | q15min–q1h (continuous monitor) | q4h–q6h + STAT as needed | Maximum — minute-level med titration, continuous monitoring |
| `day_surgery` | 5 min (intra-op), 30 min (pre/post) | Continuous (intra-op), q15min (PACU) | Pre-op panel + intra-op if needed | High during procedure, moderate otherwise |
| `rehab_inpatient` | 1 day (slower progression) | q8h | Weekly or per protocol | Moderate — rehab focus, less acute monitoring |

#### How this works in the simulation loop

```python
def simulate_encounter(encounter: Encounter, patient: PatientProfile, state: PhysiologicalState):
    time_step = TIME_RESOLUTION[encounter.encounter_type]
    
    if time_step is None:
        # Snapshot mode (outpatient, health checkup)
        # No time loop — generate one-time events and return
        generate_snapshot_events(encounter, patient, state)
        return
    
    current_time = encounter.admission_datetime
    while encounter.status == IN_PROGRESS:
        # Update physiological state at this resolution
        physiology.update(state, time_step)
        
        # Generate events appropriate for this time
        if should_measure_vitals(current_time, encounter.encounter_type):
            nursing.record_vitals(patient, state, current_time)
        if should_check_labs(current_time, encounter):
            observation.generate_lab_results(patient, state, current_time)
        if should_do_rounds(current_time, encounter):
            do_daily_rounds(encounter, patient, state)  # full clinical evaluation
        
        # Check for state transitions (discharge, ICU transfer, etc.)
        evaluate_transitions(encounter, patient, state)
        
        current_time += time_step
```

#### Transition between resolutions

When a patient transfers between encounter types, the time resolution changes seamlessly:
- **Ward → ICU**: Resolution increases from 1h to 15min. PhysiologicalState is the same object; just updated more frequently.
- **ICU → Ward (step-down)**: Resolution decreases from 15min to 1h. Less frequent updates.
- **ED → Inpatient**: Resolution changes from 30min to 1h. Shift from rapid workup to daily cycle.

No data migration is needed. The state variables are continuous; only the update frequency changes.

### Episode of Care

An `episode_id` links all encounters for a single clinical problem:

```
Episode: "E-2024-001234"
  ├── Encounter 1: ED visit (2024-06-15 18:00 – 2024-06-15 22:30)
  ├── Encounter 2: Inpatient stay (2024-06-15 22:30 – 2024-06-29 11:00)
  ├── Encounter 3: Outpatient follow-up (2024-07-12 10:00 – 10:45)
  └── Encounter 4: Outpatient follow-up (2024-08-09 10:00 – 10:30)
```

The episode_id is generated when the first encounter starts and carried through all subsequent related encounters.

### Inpatient Encounter — Detailed State Machine with Module Calls

This is the most complex and most important encounter type. The others are simplified versions.

```
State: ADMISSION (t = admission_datetime)
  ├── staff.assign_attending(department, patient) → attending_physician
  ├── staff.assign_nurse(ward, shift) → primary_nurse
  ├── nursing.admission_assessment(patient) → NursingAssessment
  ├── diagnosis.initialize_differential(patient, disease_event, referral) → DifferentialDiagnosis
  ├── order.place_admission_orders(disease_protocol, patient) → list[Order]
  │     (labs, imaging, medications, diet, activity, VTE prophylaxis)
  ├── order.place_diet_order(patient) → diet order (NPO / clear liquid / regular / diabetic / renal / low-salt)
  ├── order.place_infection_control_order(patient, diagnosis) → isolation precautions if indicated
  │     (standard / contact / droplet / airborne, based on diagnosis and risk factors)
  ├── nursing.nutritional_screening(patient) → NutritionalAssessment (MUST score or SGA)
  ├── Generate: Admission consent records (see Consent model below)
  ├── Generate: Admission H&P note
  └── → transition to ACTIVE_TREATMENT

State: ACTIVE_TREATMENT (t = admission + hours/days)
  └── Repeating daily cycle:

      === Morning (06:00–08:00) ===
      nursing.morning_vitals(patient) → VitalSignRecord
      nursing.morning_labs(active_lab_orders) → specimen collection events
      order.process_morning_batch() → lab results become available

      === Rounds (08:00–11:00) ===
      clinical_course.evaluate(patient, current_state) → StateChangeDirective
      physiology.update(state, directive) → new PhysiologicalState
      diagnosis.update(patient, new_results) → updated DifferentialDiagnosis
      treatment.evaluate_response(patient, state) → TreatmentDecision
        ├── continue current treatment
        ├── modify (dose change, drug switch)
        └── add new treatment
      order.place_daily_orders(treatment_decision, protocol) → new Orders
      Generate: Daily progress note (by attending)

      === Afternoon (13:00–17:00) ===
      nursing.afternoon_assessment(patient) → NursingAssessment
      order.process_results() → new results arrive
      If procedure_scheduled_today:
        procedure.execute(patient, order) → ProcedureRecord

      === Evening (17:00–22:00) ===
      nursing.evening_vitals(patient) → VitalSignRecord
      nursing.evening_medications(active_med_orders) → MedicationAdministration

      === Night (22:00–06:00) ===
      nursing.night_check(patient) → minimal assessment
      If deterioration detected:
        → evaluate ICU transfer (see below)

      === End of daily cycle ===
      Check discharge criteria:
        If met → transition to DISCHARGE_PLANNING
        If deterioration → transition to ICU_TRANSFER
        If stable but not met → continue ACTIVE_TREATMENT

State: DISCHARGE_PLANNING (t = when discharge criteria met)
  ├── treatment.generate_discharge_medications(patient) → discharge prescriptions
  ├── nursing.discharge_education(patient) → education record
  ├── Generate: Discharge summary
  ├── encounter.schedule_follow_up(patient, disease_protocol) → future outpatient encounter
  └── → transition to DISCHARGED

State: DISCHARGED (t = discharge_datetime)
  ├── All orders marked as completed or discontinued
  ├── patient.deactivate() → Layer 2 → Layer 1 (after follow-up sequence completes)
  └── encounter.status = COMPLETED

State: ICU_TRANSFER (triggered by deterioration)
  ├── Create new ICU encounter linked to same episode_id
  ├── staff.assign_icu_team(patient) → ICU attending, ICU nurse
  ├── Generate: Transfer note
  └── Current inpatient encounter paused; ICU encounter takes over
```

### ED Encounter — Detailed State Machine

```
State: ARRIVAL (t = arrival_datetime)
  ├── Generate: Registration event
  └── → TRIAGE

State: TRIAGE (t = arrival + 5–15 min)
  ├── nursing.triage_assessment(patient) → TriageRecord
  │     Triage level:
  │       Level 1 (Resuscitation): immediate — see physician now
  │       Level 2 (Emergency): < 10 min wait
  │       Level 3 (Urgent): 30–60 min wait
  │       Level 4 (Semi-urgent): 60–120 min wait
  │       Level 5 (Non-urgent): 120+ min wait
  └── → WAITING (duration based on triage level)

State: WAITING (t = triage + wait_time)
  # Mode 1: wait_time = nominal for triage level
  # Mode 2: wait_time = f(current ED volume, triage level)
  └── → ASSESSMENT

State: ASSESSMENT (t = after waiting)
  ├── staff.assign_ed_physician(patient, triage_level) → ED physician
  ├── diagnosis.initialize_differential(patient, symptoms) → DifferentialDiagnosis
  ├── order.place_ed_orders(differential, urgency="urgent") → stat labs, imaging
  └── → WORKUP_IN_PROGRESS

State: WORKUP_IN_PROGRESS (t = assessment + 1–4 hours)
  ├── order.await_results() → results arrive over time
  ├── diagnosis.update(patient, results) → updated differential
  ├── treatment.initiate_if_indicated(patient, working_dx) → initial treatment
  │     (e.g., IV antibiotics for suspected pneumonia started in ED)
  ├── nursing.ed_monitoring(patient) → vitals q1h, reassessments
  └── → DISPOSITION (when enough information to decide)

State: DISPOSITION (t = after workup)
  ├── Evaluate severity and diagnosis confidence:
  │   If mild + clear diagnosis → DISCHARGE_FROM_ED
  │   If moderate/severe or uncertain → ADMIT_TO_WARD
  │   If critical → ADMIT_TO_ICU
  │   If beyond facility capability → TRANSFER_OUT
  └── Generate: ED physician note with disposition rationale

State: ADMIT_TO_WARD
  ├── order.admission_order_set(patient, working_dx)
  ├── Create new Inpatient encounter, same episode_id
  ├── ED encounter status = COMPLETED
  └── Handoff to inpatient workflow

State: DISCHARGE_FROM_ED
  ├── treatment.prescribe_discharge_medications(patient)
  ├── encounter.schedule_follow_up(patient)
  ├── Generate: ED discharge instructions
  └── ED encounter status = COMPLETED
```

### Outpatient Encounter — State Machine

```
State: CHECK_IN (t = appointment_datetime - 15 min)
  ├── nursing.check_in_vitals(patient) → weight, BP, temp
  └── → WAITING (5–45 min, depends on clinic load)

State: CONSULTATION (t = after wait)
  ├── staff.assign_outpatient_physician(patient, department)
  │   (usually the same physician if follow-up)
  ├── If follow-up:
  │     diagnosis.review_status(patient) → current diagnosis state
  │     treatment.review_response(patient, latest_labs) → medication adjustment?
  │     order.place_follow_up_orders(patient) → labs for next visit, imaging if needed
  ├── If new visit:
  │     diagnosis.initialize_differential(patient, symptoms)
  │     order.place_initial_workup_orders(patient)
  ├── Generate: Visit note
  └── → CHECKOUT

State: CHECKOUT
  ├── Schedule next appointment (if needed)
  ├── Dispense prescriptions
  └── encounter.status = COMPLETED
```

### Outpatient Subtypes: Chronic Disease Management & Seasonal Symptoms

The outpatient state machine above handles all outpatient visits, but the **content** varies significantly by visit reason:

#### Chronic disease management visit
Triggered by `CHRONIC_MANAGEMENT_VISIT` life event. The most common outpatient encounter type by volume.

```
Typical flow (10–15 min consultation):
  CHECK_IN → vitals (weight, BP) → CONSULTATION:
    - Review recent labs (ordered at previous visit, results now available)
    - Brief symptom check ("Any changes?")
    - Medication review:
      ├── Stable → renew same prescriptions (most common: 80%)
      ├── Suboptimal control → dose adjustment or add medication (15%)
      └── Side effects → switch medication (5%)
    - Order labs for next visit (blood draw today, results reviewed next time)
    - Schedule next appointment (JP: 4 weeks; US: 12 weeks)
  → CHECKOUT → dispense prescriptions (JP: 院外処方箋 for external pharmacy)
```

Country differences:
- **Japan**: Monthly visits common. Prescription limited to 30–90 days (chronic meds). Labs every 1–3 months. Same physician continuity high.
- **US**: Every 3 months. Prescription for 90 days with refills. Labs every 3–6 months. May see different provider in group practice.

Data generated per visit:
- 1 vital sign record (weight, BP)
- 0–3 lab orders (for next visit)
- 0–3 lab results (from previous visit's orders)
- 1 medication order (renewal) per active medication
- 1 visit note (brief)

#### Seasonal allergy visit
Triggered by `SEASONAL_ALLERGY_FLARE` life event. Common in Japan during cedar pollen season (Feb–May).

```
Typical flow (5–10 min consultation):
  CHECK_IN → CONSULTATION:
    - Symptom severity assessment (nasal, ocular, respiratory)
    - If first visit of season: prescribe standard allergy medications
      JP: 2nd-gen antihistamine (fexofenadine/bilastine) + nasal steroid
      US: similar, but many are OTC (patient may not visit)
    - If ongoing: renew prescriptions, adjust if needed
    - If asthma component: assess peak flow, adjust inhaler
  → CHECKOUT
```

Data generated: minimal (1 visit note, 1–3 prescriptions, no labs typically).

#### Chronic condition list driving outpatient volume

| Condition | Typical visit interval (JP) | Typical visit interval (US) | Annual outpatient visits (JP) | Annual outpatient visits (US) |
|---|---|---|---|---|
| Hypertension | 4 weeks | 12 weeks | 12 | 4 |
| Diabetes | 4–8 weeks | 12 weeks | 8–12 | 4 |
| Dyslipidemia | 4–8 weeks | 12–24 weeks | 6–12 | 2–4 |
| COPD | 4–8 weeks | 8–12 weeks | 6–12 | 4–6 |
| Heart failure | 4 weeks | 4–8 weeks | 12 | 6–12 |
| Atrial fibrillation (on anticoagulant) | 4 weeks | 8–12 weeks | 12 | 4–6 |
| CKD (stage 3–4) | 4–8 weeks | 8–12 weeks | 6–12 | 4–6 |
| Allergic rhinitis (seasonal) | 4 weeks during season | OTC (few visits) | 3–4 | 0–1 |
| Osteoporosis | 4–8 weeks | 12–24 weeks | 6–12 | 2–4 |

**Realism note**: A single patient with hypertension + diabetes + dyslipidemia may visit the same hospital outpatient 12–15 times/year in Japan. This creates a large volume of low-complexity records that dominate outpatient data. In the US, the same patient visits 4–6 times/year.

### Health Checkup Encounter — State Machine (Japan)

```
State: CHECK_IN (t = checkup_datetime, typically 08:00–09:00)
  ├── Registration, insurance verification
  └── → MEASUREMENTS

State: MEASUREMENTS (t + 15 min)
  ├── Height, weight, waist circumference, BMI calculation
  ├── Vision test, hearing test
  ├── Blood pressure (seated, resting)
  └── → LAB_COLLECTION

State: LAB_COLLECTION (t + 30 min)
  ├── Blood draw (fasting): CBC, chemistry, lipids, glucose, HbA1c, liver function, renal function
  ├── Urinalysis
  └── → IMAGING

State: IMAGING (t + 45 min)
  ├── Chest X-ray (all)
  ├── ECG (age 40+ or as indicated)
  ├── Abdominal ultrasound (人間ドック only)
  ├── Upper GI series or endoscopy (age 50+, 人間ドック)
  └── → PHYSICIAN_CONSULTATION

State: PHYSICIAN_CONSULTATION (t + 90 min)
  ├── Brief interview (5–10 min): lifestyle, symptoms, family changes
  ├── Physical exam (brief: heart, lungs, abdomen)
  ├── Immediate findings discussed (BP, weight trend)
  └── → CHECKOUT

State: CHECKOUT (t + 120 min)
  ├── Schedule next year's checkup (if regular attendee)
  └── encounter.status = COMPLETED

State: RESULTS_MAILED (t + 14–28 days)
  ├── All lab and imaging results compiled into checkup report
  ├── Findings categorized:
  │     A: No abnormality
  │     B: Mild abnormality, no follow-up needed
  │     C: Requires follow-up at outpatient
  │     D: Requires detailed examination / treatment
  ├── If C or D:
  │     Generate referral recommendation → CareSeekingDecision(SCREENING_ABNORMALITY)
  │     → may trigger clinical outpatient encounter
  └── encounter.status = RESULTS_DELIVERED
```

### Prenatal Visit Encounter — State Machine

Triggered by `PRENATAL_CHECKUP` life event. JP: ~14 visits; US: ~12 visits across pregnancy.

```
State: CHECK_IN
  ├── nursing.check_in_vitals → weight, BP, urine dipstick (protein, glucose)
  └── → CONSULTATION

State: CONSULTATION
  ├── staff.assign_obstetrician (same physician throughout pregnancy for continuity)
  ├── Fundal height measurement, fetal heart rate (Doppler)
  ├── If scheduled ultrasound visit (weeks 12, 20, 28, 36):
  │     order.place(obstetric_ultrasound) → fetal growth, anomaly screening
  ├── If scheduled lab visit (weeks 8–12, 24–28, 36):
  │     order.place(prenatal_labs) → CBC, blood type, infections, glucose tolerance test (week 24–28)
  ├── Review: weight gain trajectory, BP trend, symptoms
  ├── Screen for complications:
  │     If BP ≥ 140/90 → evaluate for preeclampsia
  │     If glucose tolerance abnormal → gestational diabetes management
  │     If cervical length short → evaluate for preterm risk
  ├── Generate: Prenatal visit note (母子健康手帳 record in JP)
  └── → CHECKOUT

State: CHECKOUT
  ├── Schedule next prenatal visit
  ├── Provide patient education (fetal movement counting, warning signs)
  └── encounter.status = COMPLETED
```

Visit schedule (JP, standard low-risk):
- Weeks 4–23: every 4 weeks (5 visits)
- Weeks 24–35: every 2 weeks (6 visits)
- Weeks 36–40: every week (4 visits)
- Total: ~14–15 visits

Visit schedule (US, standard low-risk):
- Weeks 4–28: every 4 weeks (6 visits)
- Weeks 28–36: every 2 weeks (4 visits)
- Weeks 36–40: every week (4 visits)
- Total: ~12–14 visits

### Delivery Encounter — State Machine

```
State: ADMISSION (labor onset or scheduled cesarean)
  ├── staff.assign_obstetrician + midwife/L&D_nurse
  ├── nursing.admission_assessment → maternal vitals, fetal heart monitoring (CTG)
  ├── If spontaneous labor:
  │     Evaluate: cervical dilation, contraction pattern, membrane status
  │     → LABOR
  ├── If scheduled cesarean:
  │     → PRE_OP (see procedure module)
  └── If preterm or complicated: consult neonatology, alert NICU

State: LABOR
  ├── Continuous fetal monitoring (CTG)
  ├── nursing.labor_monitoring → vitals q15–30min, cervical checks q2–4h
  ├── Pain management decision:
  │     JP: less epidural use (~10–20%), more natural birth preference
  │     US: epidural common (~70%)
  ├── Duration: primiparous 12–18h, multiparous 6–12h (wide variation)
  ├── If prolonged labor, fetal distress, or failure to progress:
  │     → EMERGENCY_CESAREAN
  └── If normal progress → DELIVERY

State: DELIVERY (vaginal)
  ├── staff: obstetrician (or midwife in JP) + delivery nurse + neonatology (standby)
  ├── Duration: 15–60 min (second stage)
  ├── Newborn: Apgar score at 1 min and 5 min
  ├── Complications check: perineal laceration, hemorrhage
  ├── Generate: Delivery record (mode, duration, Apgar, complications, blood loss)
  └── → POSTPARTUM

State: EMERGENCY_CESAREAN
  ├── procedure module: cesarean section workflow
  ├── Decision-to-incision time: target < 30 min
  └── → POSTPARTUM (post-cesarean recovery is longer)

State: POSTPARTUM
  ├── Mother: vitals q15min × 2h, then q1h × 4h, then q4h
  ├── Newborn: initial exam, weight, measurements, vitamin K injection
  ├── Breastfeeding initiation support (nursing)
  ├── Daily: maternal recovery assessment, wound check (if cesarean), newborn exam
  ├── LOS:
  │     JP vaginal: 5–7 days (longer than US — cultural norm)
  │     JP cesarean: 7–10 days
  │     US vaginal: 1–2 days
  │     US cesarean: 2–4 days
  └── → DISCHARGE (when criteria met)

State: DISCHARGE
  ├── Newborn screening tests (先天性代謝異常検査 / state newborn screening)
  ├── Mother: postpartum instructions, contraception counseling
  ├── Schedule: 1-month postpartum checkup (母), 1-month newborn checkup
  ├── Birth certificate documentation
  └── encounter.status = COMPLETED
```

### NICU Encounter — State Machine (newborn)

Triggered when newborn requires intensive care (preterm < 37 weeks, low birth weight, respiratory distress, etc.)

```
State: ADMISSION
  ├── staff.assign_neonatologist + NICU_nurse (1:1 or 1:2 ratio)
  ├── Initial stabilization: airway, temperature regulation, IV access
  ├── Labs: blood gas, glucose, CBC, blood culture
  └── → INTENSIVE_MONITORING

State: INTENSIVE_MONITORING (time_resolution: 15 min)
  ├── Continuous monitoring: HR, SpO2, respiratory rate, temperature
  ├── Respiratory support: CPAP, ventilator if needed
  ├── Nutrition: IV fluids → TPN → gradual enteral feeding
  ├── Daily: weight, head circumference, labs (blood gas, bilirubin, electrolytes)
  └── → GROWING_AND_FEEDING (when stable)

State: GROWING_AND_FEEDING (time_resolution: 1 hour)
  ├── Gradual transition to full enteral feeding
  ├── Weight gain monitoring (target: 15–20 g/day)
  ├── Kangaroo care / parent involvement
  ├── Screen: retinopathy of prematurity, hearing
  └── → DISCHARGE_READY

State: DISCHARGE_READY
  ├── Criteria: stable temperature in open crib, full enteral feeding, weight ≥ 2000–2200g
  │     JP: may keep longer for weight gain (conservative)
  │     US: discharge earlier if feeding established
  ├── Parent education: feeding, warning signs, follow-up schedule
  └── encounter.status = COMPLETED
```

### Pregnancy statistics for realism validation

| Metric | Japan | US | Source |
|---|---|---|---|
| Total fertility rate | 1.20 (2023) | 1.62 (2023) | JP: 厚生労働省; US: CDC |
| Cesarean section rate | 20–25% | 32% | WHO, national statistics |
| Epidural use rate | 10–20% | 70%+ | Published surveys |
| Preterm birth rate (< 37 weeks) | 5.7% | 10.5% | JP: 人口動態統計; US: CDC |
| Low birth weight (< 2500g) | 9.4% | 8.3% | Same |
| NICU admission rate | 6–8% of births | 8–10% of births | National databases |
| Postpartum LOS (vaginal) | 5–7 days | 1–2 days | Clinical norms |
| Induced abortion rate | 6.3 per 1000 women (age 15–49) | 11.4 per 1000 | JP: 衛生行政報告例; US: Guttmacher |
| Maternal age at first birth (mean) | 30.9 | 27.3 | National statistics |
| Miscarriage rate (recognized pregnancies) | ~15% | ~15% | Literature |

### Timing Model

Every state transition has a duration drawn from a distribution:

```python
@dataclass
class StateTransitionTiming:
    state_from: str
    state_to: str
    duration_distribution: str             # "normal" | "lognormal" | "fixed"
    mean_minutes: float
    sd_minutes: float
    min_minutes: float                     # hard floor
    max_minutes: float                     # hard ceiling
    modifiers: dict[str, float]            # {"night": 1.5, "weekend": 1.3, "holiday": 1.5}
```

Example timing table (inpatient, Japan, medium hospital):

| Transition | Mean | SD | Night modifier | Weekend modifier |
|---|---|---|---|---|
| admission → first_assessment | 60 min | 30 min | ×1.3 | ×1.2 |
| morning_labs_ordered → results | 120 min | 45 min | N/A (morning only) | ×1.5 |
| rounds_start → rounds_end | 15 min/patient | 5 min | N/A | N/A |
| discharge_decision → actual_discharge | 180 min | 60 min | Deferred to morning | Deferred to Monday (JP trend) |
| deterioration_detected → ICU_transfer | 30 min | 15 min | same | same |

### Discharge Criteria Evaluation

Checked daily during morning rounds:

```python
def evaluate_discharge_criteria(patient, state, country, disease_protocol):
    if country == "JP":
        # Japan: lab normalization + clinical stability
        criteria = {
            "fever_resolved": state.temperature < 37.0 for 48h,
            "crp_trending_down": state.latest_crp < previous_crp * 0.5,
            "oral_intake_adequate": state.oral_intake > 1000 mL/day,
            "no_iv_medications": all medications converted to oral,
            "adl_independent_or_supported": mobility_assessment passed,
        }
        # All must be true. Social and functional factors may delay further:
        if all(criteria.values()):
            # ADL/functional assessment for discharge safety
            if patient.adl_score.total_score < 60 and patient.primary_caregiver is None:
                return "social_delay"  # needs discharge destination arrangement
            if patient.living_situation == "alone" and patient.age >= 80:
                return "social_delay"
            if patient.cognitive_status in ["moderate_dementia", "severe_dementia"] and patient.primary_caregiver is None:
                return "social_delay"
            return "ready"
    
    elif country == "US":
        # US: functional recovery + oral tolerability (earlier discharge)
        criteria = {
            "fever_resolved_24h": state.temperature < 37.5 for 24h,
            "oral_medication_tolerated": can take oral meds,
            "clinical_stability": no escalation in 24h,
            "discharge_plan_in_place": follow_up scheduled + prescriptions written,
        }
        # CRP normalization NOT required (key JP/US difference)
        if all(criteria.values()):
            return "ready"
    
    return "not_ready"
```

### Cross-Module Interaction Summary

| Encounter state | Modules called | Purpose |
|---|---|---|
| Admission | staff, nursing, diagnosis, order | Set up care team, initial assessment, admission orders |
| Daily cycle - morning | nursing, order, physiology | Vitals, labs, state update |
| Daily cycle - rounds | clinical_course, diagnosis, treatment, order | Clinical decision-making |
| Daily cycle - afternoon | nursing, procedure, order | Care delivery, procedures |
| Deterioration | encounter (self), staff | ICU transfer decision, new care team |
| Discharge | treatment, nursing, encounter | Discharge meds, education, follow-up scheduling |
| Outpatient follow-up | diagnosis, treatment, order | Review, medication adjustment |
| Health checkup | nursing, order, observation | Measurements, labs, imaging |

---

## Open Questions
- [ ] Pre-hospital phase: ambulance transit time, EMS handoff documentation
- [ ] Encounter numbering scheme: sequential per facility per year? UUID?
- [ ] Rehabilitation encounter daily schedule detail (PT/OT/ST sessions)
- [ ] How to model "observation" status (US: < 2 midnights, not formal admission)
- [ ] Concurrent encounters: patient in inpatient ward visiting radiology department

### Consent and documentation model

Every hospital encounter involves consent records. These are required EHR artifacts.

```python
@dataclass
class ConsentRecord:
    consent_type: str              # see table below
    patient_id: str
    consent_given_by: str          # "patient" | "family_spouse" | "family_child" | "guardian"
    explaining_physician_id: str
    witness_id: str | None         # staff_id of witness (US: required; JP: optional)
    timestamp: datetime
    signed: bool                   # True for most; False if verbal consent documented
    document_type: str             # "written" | "verbal" | "electronic"
```

| Consent type | When generated | JP specifics | US specifics |
|---|---|---|---|
| `admission_general` | Admission | Includes general treatment agreement, data use consent | Conditions of admission, financial responsibility |
| `informed_consent_procedure` | Before any invasive procedure | Family co-signs frequently. Separate consent per procedure | Patient-centered. Risks/benefits/alternatives documented |
| `blood_transfusion` | Before transfusion | **Separate consent required** (JP legal requirement) | Usually part of surgical consent |
| `anesthesia` | Before surgery | Anesthesiologist explains; family co-signs | Anesthesiologist explains; patient signs |
| `research_participation` | If enrolled in study | Written + IRB-approved document | Same + HIPAA authorization |
| `advance_directive_acknowledgment` | Admission (if AD exists) | Verbal confirmation; rarely formal document | Copy placed in chart; confirmed at admission |
| `restraint_consent` | If physical restraint applied | Family consent required in most JP hospitals | Physician order + nursing assessment; patient/family informed |
| `imaging_contrast` | Before contrast CT/MRI | Risk explanation for contrast reaction | Same |

Consent timing:
- `admission_general`: Within first 2 hours of admission
- `informed_consent_procedure`: At least 24h before elective surgery (JP), day-of for emergency
- `blood_transfusion`: Before first unit

JP cultural note: In Japan, the family (especially 配偶者 or 長男/長女) frequently co-signs or signs on behalf of the patient, particularly for elderly patients. The "explaining physician" (説明医) is often the attending, not a resident.

US note: Informed consent must document that the patient understood risks, benefits, and alternatives. Witness signature is standard. Electronic consent increasingly common.

## Design Notes
- The encounter module is the primary "clock driver" — it determines when things happen
- Other modules generate content within the encounter framework's time structure
- The daily cycle in inpatient is the core simulation loop; everything else is variations on this pattern
- Discharge criteria differences between JP and US are one of the strongest drivers of LOS difference
- Health checkup encounters share equipment with clinical encounters, creating realistic resource contention

### Behavioral attribute impact on encounters
- **ADL/Frailty**: Low ADL score → longer LOS, higher probability of rehab transfer, social work consultation triggered, discharge destination assessment required
- **Cognitive status**: Dementia patients → delirium screening on admission, simplified consent process (family proxy), longer LOS, higher complication rate
- **Mental health**: Depression → longer LOS (×1.2), lower engagement with rehab. Alcohol dependence → withdrawal monitoring protocol on admission (CIWA scoring). Anxiety → more frequent nurse calls, more PRN medication use
- **Advance directive/DNR**: Changes treatment intensity. DNR patients do not receive CPR, intubation. Comfort-only patients → palliative care pathway, minimal lab monitoring, symptom management focus
- **Caregiver availability**: No caregiver + low ADL → social admission, discharge coordinator involvement, SNF/rehab placement process (adds 3–14 days in JP, 1–3 days in US)
- **Adherence pattern**: Affects post-discharge readmission risk. "good_when_symptomatic" pattern → high readmission for HF/COPD. "cost_skipping" → medication-related readmission

### LLM integration points
All LLM calls below are made via `llm_service.request()`. See `llm_service/SPEC.md` for the centralized LLM interface.
- **Admission H&P note** (model: large): Generates the initial History & Physical document from structured patient data. The LLM receives `LLMClinicalContext` + presenting symptoms + referral data and produces a realistic narrative in the style of the assigned physician's country/department.
- **Daily progress notes (key days only)** (model: medium): LLM generates notes for clinically significant days (admission, treatment change, major result, discharge). Intermediate stable days use template-based notes with deliberate repetitiveness — real physicians write nearly identical notes for unchanged patients ("Day 8: Stable. CRP improving. Continue current antibiotics. Plan: observe."). This repetitiveness is a realism feature, not a bug.
- **Discharge summary** (model: large): Generates a comprehensive discharge summary from the full encounter timeline. This is the highest-value LLM call — discharge summaries are the most-read clinical documents.
- **Consultation notes** (model: medium): When a consultation is requested, the LLM generates the specialist's response note with appropriate specialty-specific language.
- **Template mode fallback**: All notes are generated using structured SOAP templates with rule-based slot filling.
