# nursing — Nursing Process & Care Records

## Purpose
Generate nursing-specific clinical events and documentation: scheduled vital sign measurements, nursing assessments, medication administration records, care interventions, shift handoffs, and nursing notes. Nurses are the most frequent contributors to EHR data.

## Inputs
- `Encounter`: Current encounter type and state (determines assessment frequency)
- `PatientProfile`: Patient acuity, mobility, risk factors
- `PhysiologicalState`: Current clinical state (drives assessment findings)
- `TreatmentPlan`: Active medication orders (for administration records)
- `Order`: Orders requiring nursing execution (vital sign frequency, specimen collection)
- `StaffRoster`: Assigned nurses per shift
- `HealthcareSystemConfig`: Country-specific nursing documentation norms

## Outputs
- `NursingAssessment`: Structured assessment record (pain, skin, neuro, fall risk, etc.)
- `VitalSignRecord`: Vital sign measurement with nurse attribution and timestamp
- `MedicationAdministrationRecord` (MAR): Medication given/held/refused with reason
- `NursingNote`: Narrative nursing documentation
- `CareIntervention`: Nursing actions (wound care, repositioning, patient education, etc.)
- `ShiftHandoff`: Shift change summary (Mode 2: formal SBAR handoff record)

## Dependencies
- `encounter` (determines assessment schedule and documentation requirements)
- `physiology` (provides state for assessment findings)
- `treatment` (medication orders to administer)
- `order` (orders requiring nursing execution)
- `staff` (nurse assignment per shift)
- `patient` (risk factor assessment)

## Confirmed Specifications

### Vital sign measurement schedules

| Setting | Frequency | Parameters measured |
|---|---|---|
| General ward (stable) | q4h–q8h | Temp, HR, BP, RR, SpO2 |
| General ward (unstable) | q1h–q2h | Temp, HR, BP, RR, SpO2, urine output |
| ICU | q15min–q1h | All vitals + hemodynamic monitoring |
| Post-op (first 24h) | q1h–q2h | Temp, HR, BP, RR, SpO2, pain, drain output |
| ED | On arrival + q1h–q2h | All vitals |
| Outpatient | Once at check-in | Temp, HR, BP, weight |

### Nursing assessment domains

| Domain | Content | Frequency |
|---|---|---|
| Pain | Location, intensity (NRS 0–10), character | Every vital sign check |
| Neurological | GCS, pupil response, orientation | q4h–q8h (q1h if altered) |
| Respiratory | Breath sounds, O2 delivery, cough/sputum | q4h–q8h |
| Cardiovascular | Heart sounds, peripheral pulses, edema | q8h |
| Gastrointestinal | Bowel sounds, intake/output, nausea | q8h |
| Skin / wound | Integrity, pressure injury risk (Braden), wound status | Once per shift |
| Mobility / fall risk | Morse Fall Scale, activity level, assistive devices | Once per shift |
| Psychosocial | Anxiety, sleep, family involvement | Once per shift |
| Cognitive / delirium | CAM (Confusion Assessment Method), orientation check | q8h (q4h if at-risk: age 75+, dementia, ICU) |
| ADL assessment | Barthel Index or FIM (on admission, weekly, pre-discharge) | Admission + weekly |
| Fall risk scoring | Morse Fall Scale: history, secondary dx, ambulatory aid, IV, gait, mental status | Admission + daily |
| Alcohol withdrawal | CIWA-Ar scoring (if alcohol dependence history) | q4h–q1h while at risk (first 72h) |
| Suicide risk screening | PHQ-2/PHQ-9 (if depression or psychiatric history) | Admission |
| Nutritional screening | MUST score (JP) or SGA (US): BMI, weight loss, acute disease effect | Admission |
| Dietary intake recording | Meal intake percentage (100% / 75% / 50% / 25% / 0%) | Every meal |
| Infection control | Precaution type documented, PPE compliance, isolation signage | Admission + per shift if active |

### Nutritional management events

| Event | Trigger | Generated data |
|---|---|---|
| Nutritional screening | Admission | MUST/SGA score, risk category (low/medium/high) |
| Diet order | Admission, diet change | Order type: NPO, clear_liquid, soft, regular, diabetic, renal, low_salt, tube_feeding |
| Meal intake recording | Every meal (3x/day) | Percentage consumed, appetite assessment |
| Dietitian consultation | MUST score ≥ 2 (medium/high risk), or physician request | Nutritional assessment note, calorie/protein targets, recommendations |
| Diet advancement | Post-surgery, post-NPO | NPO → clear liquid → soft → regular (stepwise) |
| Tube feeding initiation | Unable to eat orally > 48h, or severe malnutrition | EN/TPN order, rate, formula |

### Infection control events

| Precaution type | Trigger conditions | PPE required | Room type |
|---|---|---|---|
| Standard | All patients (baseline) | Gloves for body fluids | Any |
| Contact | MRSA, VRE, C. diff, wound infection | Gown + gloves | Private preferred |
| Droplet | Influenza, pertussis, meningitis | Surgical mask | Private, door open OK |
| Airborne | TB (suspected/confirmed), measles, varicella | N95 + negative pressure room | Negative pressure isolation |

Records generated:
- Isolation order (placed by physician)
- Isolation signage (nursing documentation)
- PPE compliance check (per shift)
- Screening cultures (MRSA nasal swab on admission — some facilities do universal screening)
- Isolation discontinuation (when criteria met)

### Behavioral impact on nursing workload

| Patient attribute | Nursing impact |
|---|---|
| Dementia (moderate+) | Requires reorientation, may need 1:1 sitter, fall prevention measures, simplified communication |
| Delirium (active) | CIWA or CAM q1–4h, restraint monitoring if applied, family presence coordination |
| Low ADL | Assistance with feeding, bathing, toileting, repositioning → higher nurse time per patient |
| High fall risk | Bed alarm, low bed, non-skid socks, hourly rounding, fall risk signage |
| Alcohol withdrawal | CIWA monitoring, PRN benzodiazepines, potential rapid deterioration |
| DNR/comfort care | Shift to symptom management: pain control, comfort positioning, reduced monitoring |
| Poor health literacy | Extra time for patient education, pictorial instructions, teach-back method |

### Medication Administration Record (MAR)

For each scheduled medication dose:
```
medication_id → scheduled_time → actual_time → status → nurse_id → notes
```

| Status | Frequency | Notes |
|---|---|---|
| Given | 90–95% | Administered as ordered |
| Held | 3–5% | Clinical reason (e.g., low BP → hold antihypertensive) |
| Refused | 1–2% | Patient declined |
| Not available | <1% | Pharmacy delay |

### Nursing care interventions

| Intervention | Trigger | Documentation |
|---|---|---|
| Repositioning | q2h for immobile patients | Time, position, skin check |
| Wound care | Per order (daily–BID) | Wound description, dressing type |
| Patient education | Admission, discharge, new medication | Topic, method, patient understanding |
| Fall prevention | High fall risk score | Measures implemented |
| Restraint monitoring | If restraints applied | q1h–q2h checks, circulation, necessity |
| Intake/output recording | ICU, fluid management | Hourly totals, 24h balance |

### Shift handoff (Mode 2 emphasis)

At each shift change, the outgoing nurse generates a handoff record:
- Patient summary (diagnosis, current status, active issues)
- Pending orders and results
- Concerns and watch items
- Plan for next shift

In Mode 1, this is simplified to implicit nurse reassignment.
In Mode 2, handoff records are generated as SBAR-structured documents.

### Country-specific differences

| Aspect | Japan | US |
|---|---|---|
| Nursing model | Team nursing (common) | Primary nursing (common) |
| Nurse-to-patient ratio (ward) | 1:7 (7:1 配置) | 1:4–6 |
| Documentation style | Less narrative, more checklist-based | Extensive narrative charting (liability) |
| Medication administration | Nurse prepares and administers IV | Pharmacy prepares, nurse administers |
| Vital sign units | °C, mmHg | °F or °C (facility-dependent), mmHg |

### Mode 1 vs Mode 2 differences

| Aspect | Mode 1 | Mode 2 |
|---|---|---|
| Nurse assignment | One plausible nurse per event | Actual shift roster, workload-balanced |
| Vital sign timing | Exact schedule | May slip ±30min based on workload |
| Shift handoff | Not generated | Full SBAR record generated |
| Missed assessments | Not modeled | Possible under high workload |

### Temporal variation in nursing activities

Nursing workload and activities follow strong time-of-day patterns:

| Time period | Activities | Workload |
|---|---|---|
| 06:00–08:00 | Morning vital signs, morning lab draws, breakfast medications, bed baths | Peak |
| 08:00–10:00 | Physician rounds (nurse accompanies), morning assessments | High |
| 10:00–12:00 | Treatments, wound care, patient education, discharge prep | Moderate |
| 12:00–14:00 | Lunch medications, noon vitals (if q4h), lunch assist | Moderate |
| 14:00–16:00 | Afternoon assessments, admissions/discharges, family interactions | Moderate |
| 16:00–17:00 | Shift handoff preparation, documentation catch-up | High |
| 17:00–20:00 | Evening shift start, dinner medications, evening vitals | Moderate |
| 20:00–22:00 | Night medications, settling patients, sleep assessments | Lower |
| 22:00–06:00 | Minimal scheduled activity; PRN medications, night checks, emergency response | Low (but unpredictable) |

#### Impact on data realism
- Vital sign timestamps cluster around scheduled times (not uniformly distributed)
- Morning lab draw times cluster between 06:00–07:30
- Medication administration times show slight delays from scheduled times (±15–30 min)
- Night shift documentation is sparser — fewer notes, less detail
- Weekend: same nursing care but fewer physician orders to execute

### Documentation noise patterns (realistic EHR artifacts)

Real EHR data is not pristine. The following patterns should be reproduced:

#### Delayed batch entry
Nurses often record multiple events at once (e.g., end of shift):
```python
def apply_documentation_delay(events: list[ClinicalEvent], encounter_type: str):
    """Some events are documented later than they occurred."""
    for event in events:
        if random() < 0.15:  # ~15% of records have documentation delay
            # Actual event time stays. Record entry time is later.
            event.recorded_datetime = event.timestamp + timedelta(minutes=Normal(60, 30).sample())
            # Night shift: batch entry at end of shift is very common
            if event.timestamp.hour >= 22 or event.timestamp.hour < 6:
                if random() < 0.40:
                    # Batch at 06:00–06:30 (shift end)
                    event.recorded_datetime = event.timestamp.replace(hour=6, minute=randint(0, 30))
```

#### Template/repetitive documentation
Stable patients generate nearly identical notes day after day:
```
Day 5 note: "Vital signs stable. Afebrile. Appetite improving. No complaints. Continue current plan."
Day 6 note: "Vital signs stable. Afebrile. Good appetite. No complaints. Continue current plan."
Day 7 note: "Vital signs stable. Afebrile. Diet tolerated well. No new complaints. Discharge planning."
```
The LLM (NARRATIVE mode) should generate notes with this natural repetitiveness for stable patients, rather than inventing new clinical content each day.

For `template` mode (no LLM), use a small set of stock phrases that rotate with minor variation:
```python
STABLE_PHRASES = [
    "Vital signs stable within normal limits.",
    "No acute distress. Afebrile.",
    "Patient resting comfortably.",
    "Tolerating diet well. No nausea/vomiting.",
    "No new complaints.",
    "Continue current management plan.",
]
```

#### Sparse night documentation
Night shift (22:00–06:00) records are minimal:
- Vital signs: recorded but fewer (q4-8h instead of q4h)
- Notes: very brief or absent ("Patient sleeping. No acute events.")
- Medication: scheduled meds given, no new orders unless emergency
- Record volume: ~25% of daytime volume

### Nursing activity by encounter type (time resolution alignment)

The nursing module generates different volumes and types of data depending on the encounter type. This aligns with the encounter module's time resolution:

| Encounter type | Vitals generation | MAR | Assessments | Approximate records/day |
|---|---|---|---|---|
| `health_checkup` | 1 measurement (check-in) | None | None | 1 |
| `outpatient` | 1 measurement (check-in) | None (pharmacy dispenses) | None | 1 |
| `inpatient` (stable) | q4h–q8h (3–6/day) | Per scheduled medications (4–8/day) | Once per shift (2–3/day) | 15–25 |
| `inpatient` (unstable) | q1h–q2h (12–24/day) | Per medications + PRN | q4h focused assessments | 30–50 |
| `emergency` | On arrival + q30min–q1h | Per ED medications | Triage + reassessments | 5–10 (short encounter) |
| `icu` | q15min–q1h (continuous monitor logged q1h) | Per medications (frequent IV drips) | q1h–q2h focused | 60–100 |
| `day_surgery` | Pre-op + intra-op continuous + PACU q15min | Anesthesia meds (procedure module) | Pre-op + PACU | 15–30 |
| `rehab_inpatient` | q8h (stable patients) | Per medications | Daily rehab progress | 8–12 |

**Key realism point**: A patient who moves from ICU → ward should show a dramatic reduction in vital sign frequency in the records. This is a natural consequence of the encounter type's time resolution — no special logic needed.

#### Temporal jitter model

The jitter model differs based on whether data comes from manual nursing entry or automatic device recording:

```python
def generate_vital_sign_event(scheduled_time: datetime, encounter_type: str,
                                hospital_scale: str, parameter: str) -> VitalSignEvent:
    
    data_origin = facility.determine_data_origin(encounter_type, parameter, hospital_scale)
    
    if data_origin == "device_auto":
        # Device-generated: precise timestamp, no jitter, but may have artifacts
        actual_time = scheduled_time  # exact (device clock)
        precision = "high"            # e.g., SpO2 = 96.3, not 96
        artifact_prob = DEVICE_ARTIFACT_RATES.get(parameter, 0.01)
        has_artifact = random() < artifact_prob
        source = "device"
    else:
        # Manual nursing entry: jitter, rounded values, no artifacts (nurse filters)
        if encounter_type == "icu":
            jitter = Normal(0, 3).sample()
        elif encounter_type == "inpatient":
            jitter = Normal(0, 15).sample()
        elif encounter_type == "emergency":
            jitter = Normal(5, 10).sample()
        else:
            jitter = Normal(0, 5).sample()
        
        actual_time = scheduled_time + timedelta(minutes=jitter)
        precision = "standard"        # e.g., SpO2 = 96, BP = 120/80
        has_artifact = False           # nurse wouldn't record artifact values
        source = "manual"
    
    return VitalSignEvent(
        timestamp=actual_time,
        source=source,
        precision=precision,
        has_artifact=has_artifact,
    )
```

#### ICU continuous monitoring data

ICU patients on bedside monitors generate a massive volume of device-auto data:

| Parameter | Recording interval | Data points/day | Notes |
|---|---|---|---|
| HR | q1min (continuous) → charted q15min–q1h | 24–96 charted | Nurse validates hourly, auto-charted q15min |
| SpO2 | Continuous → charted q15min–q1h | 24–96 charted | Motion artifact common (~5%) |
| BP (arterial line) | Continuous → charted q15min | 96 charted | Most accurate BP source |
| BP (cuff, automated) | q15min–q1h | 24–96 | Used when no arterial line |
| RR | Continuous (impedance) → charted q1h | 24 charted | Often inaccurate (impedance-based) |
| ECG rhythm | Continuous → events only | Variable | Normal sinus: no events. Arrhythmia: alarm event |
| Ventilator params | q15min–q1h | 24–96 | Tidal volume, rate, FiO2, PEEP, peak pressure |
| Urine output | q1h (nurse measures) | 24 | Manual measurement from Foley catheter |

**Data volume comparison**: A 14-day ward stay generates ~100–200 vital sign data points. A 3-day ICU stay generates ~500–1,500. This difference is an important realism signal — EHR systems for ICU patients have dramatically denser time-series data.

#### POCT (Point-of-Care Testing) data characteristics

POCT results (glucometer, blood gas) have distinct EHR data patterns:

```python
@dataclass  
class POCTResult:
    """Point-of-care test result — different from central lab result."""
    device_type: str                       # "glucometer" | "blood_gas_analyzer" | "i-STAT"
    device_id: str                         # specific device serial number
    operator_id: str                       # nurse or RT who ran the test (scanned badge)
    patient_id_method: str                 # "barcode_scan" | "manual_entry"
    timestamp: datetime                    # precise (device clock synced)
    turnaround_minutes: float              # 1–5 min (vs. central lab 30–180 min)
    
    # Result
    analyte: str                           # "glucose" | "pH" | "pCO2" | "lactate" | ...
    value: float
    unit: str
    
    # QC
    qc_passed: bool                        # device runs internal QC
    lot_number: str                        # reagent lot (for traceability)
```

Key differences from central lab:
- **Turnaround**: 1–5 minutes (vs. 30–180 for central lab)
- **Operator**: nurse or respiratory therapist (not lab technician)
- **Precision**: Generally lower than central lab (higher CVa)
- **Patient ID**: Barcode scan required (patient safety feature)
- **Volume**: Glucometer checks may be q1h–q6h for diabetic patients = significant data volume

---

## Internal Design

### Vital sign event generation

```python
def generate_vital_signs(encounter: Encounter, patient: PatientProfile,
                          state: PhysiologicalState, scheduled_time: datetime,
                          staff_schedule: ShiftSchedule) -> ClinicalEvent:
    """Generate a vital sign measurement event."""
    
    # Apply temporal jitter
    actual_time = actual_measurement_time(scheduled_time, encounter.encounter_type)
    
    # Derive vitals from physiological state
    vitals = physiology.derive_vital_signs(state, patient, patient.baseline_vitals, actual_time)
    
    # Assign nurse
    nurse = staff.assign_staff("medication_administration", encounter, actual_time,
                                roster, staff_schedule)[0]
    
    return ClinicalEvent(
        event_type=ClinicalEventType.VITAL_SIGNS,
        timestamp=actual_time,
        vital_signs=vitals,
        staff_assignments=[nurse],
    )
```

### Medication administration record (MAR) generation

```python
def generate_mar_event(med_event: MedicationEvent, patient: PatientProfile,
                        state: PhysiologicalState, encounter: Encounter) -> MedicationAdministration:
    """Generate a single medication administration record."""
    
    # Determine status: given, held, refused
    status, reason = determine_administration_status(med_event, patient, state)
    
    # Apply temporal jitter
    actual_time = med_event.scheduled_time + timedelta(minutes=Normal(5, 10).sample())
    
    return MedicationAdministration(
        order_id=med_event.order_id,
        scheduled_datetime=med_event.scheduled_time,
        actual_datetime=actual_time if status == "given" else None,
        status=status,
        dose_given=med_event.dose if status == "given" else None,
        route=med_event.route,
        hold_reason=reason if status == "held" else None,
        refusal_reason=reason if status == "refused" else None,
    )

def determine_administration_status(med_event, patient, state) -> tuple[str, str | None]:
    """Decide if medication is given, held, or refused."""
    
    # Hold conditions (clinical reasons)
    drug = med_event.drug
    if drug_category(drug) == "antihypertensive" and state.systolic_bp < 90:
        return "held", "SBP < 90 mmHg"
    if drug_category(drug) == "beta_blocker" and state.heart_rate < 55:
        return "held", "HR < 55 bpm"
    if drug_category(drug) == "anticoagulant" and state.coagulation_status > 0.5:
        return "held", "active bleeding risk"
    if drug_category(drug) == "oral" and patient_is_npo(state):
        return "held", "NPO status"
    
    # Patient refusal (1-2%)
    if random() < 0.015:
        return "refused", "patient declined"
    
    # Pharmacy delay (<1%)
    if random() < 0.005:
        return "not_available", "pharmacy delay"
    
    return "given", None
```

### Nursing assessment generation

```python
def generate_shift_assessment(patient: PatientProfile, state: PhysiologicalState,
                                encounter: Encounter, timestamp: datetime) -> NursingAssessment:
    """Generate a structured nursing assessment at shift start."""
    
    vitals = physiology.derive_vital_signs(state, patient, patient.baseline_vitals, timestamp)
    
    # Pain assessment
    pain = generate_pain_assessment(patient, state, encounter)
    
    # Fall risk (Morse Fall Scale)
    morse_score = calculate_morse_score(patient, state, encounter)
    
    # Skin/Braden
    braden_score = calculate_braden_score(patient, state)
    
    return NursingAssessment(
        assessment_type="shift_assessment",
        pain=pain,
        neurological=assess_neuro(patient, state),
        respiratory=assess_respiratory(state),
        cardiovascular=assess_cardiovascular(state),
        skin=f"Braden score: {braden_score}. {'Pressure injury prevention protocol active.' if braden_score < 18 else 'Skin intact.'}",
        mobility=f"Morse Fall Scale: {morse_score}. {'High fall risk.' if morse_score >= 45 else 'Standard precautions.'}",
    )

def calculate_morse_score(patient, state, encounter):
    score = 0
    if patient.has_visited_hospital and patient.visit_count > 1: score += 25  # history of falling
    if len(patient.chronic_conditions) > 1: score += 15  # secondary diagnosis
    if patient.mobility in ["walker", "cane"]: score += 15  # ambulatory aid
    if any(o.order_type == OrderType.MEDICATION and "IV" in o.medication_details.route 
           for o in encounter.active_orders): score += 20  # IV/heparin lock
    if state.perfusion_status < 0.7 or patient.cognitive_status != "normal": score += 15  # impaired gait
    if patient.cognitive_status != "normal": score += 15  # mental status
    return score
```

## Open Questions
- [ ] Nursing note narrative: LLM generates from structured assessment data (via llm_service NARRATIVE task)
- [ ] NANDA-I nursing diagnosis: defer to Phase 2+
- [ ] PRN medication trigger logic detail (pain score > 4 → offer analgesic)

## Design Notes
- Nursing generates the highest volume of EHR data (vital signs alone can be 4–6 entries per shift per patient)
- The nursing module acts as the "executor" of many orders — it performs specimen collection, medication administration, and vital sign measurement
- Clear interface needed with the `order` module: order says "measure vitals q4h", nursing generates the actual measurement events
- Temporal patterns in nursing activities are one of the strongest realism signals in EHR data — uniform timestamps are a giveaway of synthetic data
- Record volume scales with encounter type: ICU generates ~60–100 records/day vs. outpatient ~1 record. This matches real EHR data volume patterns.
