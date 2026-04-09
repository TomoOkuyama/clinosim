# Narrative-CIF Data Mapping

**Purpose**: Define which CIF data fields must be included in prompts for each narrative type to ensure clinical consistency.

**Principle**: All narratives must be clinically consistent with THREE data sources:
1. **CIF structured data** (actual measurements: vitals, labs, medications)
2. **Disease protocol** (disease pathophysiology, typical course, standard treatment)
3. **ED/Encounter scenario** (presentation severity, triage decision, initial management)

**Critical**: CIF contains structured data from BEFORE and AFTER the narrative event timepoint. Narratives must reflect ACTUAL outcomes recorded in CIF "after" data, not assumed outcomes.

**Examples of 3-way consistency**:
- **Discharge Summary** stating "CRP normalized on Day 7":
  - CIF: lab_results has CRP < 1.0 on Day 7 ✓
  - Disease protocol: bacterial_pneumonia.yaml shows typical CRP normalization by Day 5-10 ✓
  - Encounter: admission severity was "moderate", so 7-day course is expected ✓

- **Admission H&P** describing "moderate respiratory distress, SpO2 91%":
  - CIF: vital_signs has spo2=91 at admission ✓
  - Disease protocol: bacterial_pneumonia.yaml lists "dyspnea" as typical symptom ✓
  - Encounter: community_pneumonia.yaml severity="moderate" triggers admission ✓

- **Operative Note** stating "fracture line clear, good bone quality":
  - CIF: procedure record has findings="Fracture line clear, good bone quality" ✓
  - Disease protocol: femoral_neck_fracture.yaml describes typical fracture patterns ✓
  - Surgery decision: hip_fracture_orif protocol indicates surgical fixation for displaced fractures ✓

---

## Data Sources for Narrative Generation

### 1. CIF Structured Data (clinosim/types/output.py)
- **PatientProfile**: age, sex, medical_history, medications, allergies
- **Encounter**: admission/discharge datetime, chief_complaint, department
- **VitalSignRecord**: temp, HR, BP, RR, SpO2 (BEFORE/AFTER timepoints)
- **OrderResult**: lab values (BEFORE/AFTER timepoints)
- **ClinicalDiagnosis**: admission/discharge diagnosis codes
- **Procedures**: procedure details, intraop findings, EBL, complications
- **MedicationAdministration**: drugs given during stay
- **PrescriptionRecord**: discharge medications

### 2. Disease Protocol (clinosim/modules/disease/reference_data/*.yaml)
- **chief_complaint**: Typical presentation (multi-language)
- **icd_codes**: Diagnostic code variants with probabilities
- **initial_state_impact**: Severity-based physiological changes (mild/moderate/severe)
- **order_protocols**: 
  - admission_orders: Standard labs/imaging/supportive care
  - daily_monitoring: Frequency of vitals/labs
  - discharge_criteria: Clinical stability thresholds
- **course_archetypes**: Disease trajectory patterns
  - smooth_recovery: Day-by-day improvement trajectory
  - dip_then_recovery: Initial worsening with recovery
  - plateau_then_recovery: Delayed improvement
  - Each with: trajectory, order_modifications, treatment_modifications
- **treatment_protocols**: Standard antibiotics, dosing, escalation rules
- **complications**: Possible complications with probabilities

### 3. ED/Encounter Scenario (clinosim/modules/encounter/reference_data/*.yaml)
- **chief_complaint**: Typical ED/outpatient presentation
- **severity_distribution**: mild/moderate/severe proportions
- **workup**: Standard labs/imaging with probabilities
- **treatment**: ED/outpatient medications with probabilities
- **scenarios**: Presentation variants
  - benign_self_limiting
  - requires_imaging
  - concerning (may need admission)
- **discharge_instructions**: Standard patient education
- **discharge_prescriptions**: Typical outpatient medications

---

## Temporal Data Consistency

Each narrative type has a **timepoint** and requires data from **BEFORE** and/or **AFTER** that timepoint:

| Narrative Type | Timepoint | BEFORE Data | AFTER Data |
|---|---|---|---|
| **Admission H&P** | Admission datetime | PMH, home meds | Admission vitals, admission labs |
| **Discharge Summary** | Discharge datetime | Admission vitals/labs, hospital course | Discharge vitals/labs, outcomes |
| **Operative Note** | Surgery datetime | Preop diagnosis, preop vitals | Intraop findings, EBL, postop diagnosis |
| **Procedure Note** | Procedure datetime | Indication, pre-procedure vitals | Post-procedure vitals, findings |
| **Death Note** | Death datetime | Admission data, hospital course | Final vitals, cause of death |

**Key Rule**: If a narrative mentions a clinical outcome (e.g., "normalized", "improved", "stable"), that outcome MUST be evidenced by CIF data at the AFTER timepoint.

---

## 1. Admission H&P (LOINC 34117-2)

**Timing**: Generated at admission (first encounter)

**Required CIF Data**:

### From `PatientProfile`:
- `age`, `sex`
- `medical_history` (list of conditions with ICD codes)
- `current_medications` (if any)
- `allergies`
- `smoking_status`, `alcohol_use`

### From `Encounter`:
- `chief_complaint`
- `admission_datetime`
- `admit_source` (ED, GP referral, etc.)
- `priority` (EM/UR/R)

### From `VitalSignRecord` (admission vitals):
- First vital signs record (timestamp closest to admission_datetime)
- `temperature_celsius`, `heart_rate`, `systolic_bp`, `diastolic_bp`
- `respiratory_rate`, `spo2`, `on_supplemental_oxygen`
- `consciousness_level`, `pain_score`

### From `OrderResult` (admission labs):
- Labs ordered within first 4 hours of admission
- `lab_name`, `value`, `unit`, `flag` (H/L/critical)
- Common: CBC (WBC, Hgb, Plt), CMP (Na, K, Cr, glucose), CRP

### From `ClinicalDiagnosis`:
- `admission_diagnosis_code`, `admission_diagnosis_system`
- Resolve to English display name via `codes.lookup()`

### From Disease Protocol YAML:
- `chief_complaint`: Verify CIF chief_complaint matches typical presentation
- `order_protocols.admission_orders`: Verify CIF orders match standard workup
- `initial_state_impact[severity]`: Infer severity from CIF vitals/labs matching protocol thresholds

### From Encounter Scenario YAML (if ED/outpatient):
- `workup`: Verify CIF labs/imaging match scenario
- `treatment`: Verify initial medications match scenario
- `severity_distribution`: Infer presentation severity from vitals/labs

### Physical Exam (if available in CIF):
- Currently not in CIF structure → **template-based from disease protocol**
- Future: add `PhysicalExamFindings` to CIF

**Prompt Structure**:
```
Patient: {age}yo {sex}
Chief complaint: {chief_complaint}
PMH: {condition1}, {condition2}, ...
Medications: {med1}, {med2}, ...
Allergies: {allergies}

Admission Vitals:
- Temp: {temp}°C, HR: {hr}, BP: {sbp}/{dbp}, RR: {rr}, SpO2: {spo2}%{oxygen_status}

Admission Labs:
- WBC: {wbc_value} {unit} ({flag})
- CRP: {crp_value} {unit}
- ...

Admitting Diagnosis: {diagnosis_display_name}

Write a concise admission H&P.
```

---

## 2. Discharge Summary (LOINC 18842-5)

**Timing**: Generated at discharge

**Required CIF Data**:

### From `Encounter`:
- `admission_datetime`, `discharge_datetime` → calculate LOS
- `chief_complaint`
- `discharge_disposition` (home, SNF, died, etc.)

### From `ClinicalDiagnosis`:
- `admission_diagnosis_code`
- `discharge_diagnosis_code` (may differ from admission)
- `secondary_diagnoses` (list)
- Resolve all to English display names

### From `complications_occurred`:
- List of complication codes (if any)
- Resolve to display names

### From `procedures`:
- List of procedures performed during admission
- Each: `procedure_code`, `procedure_date`, `surgeon_id`

### Hospital Course Summary (BEFORE → AFTER comparison):
- **CRITICAL**: All statements about improvement/resolution MUST be backed by CIF data
- Key events by day (generated from vital_signs + lab_results trends)
- Day of defervescence: Find first day where temp < 37.5°C sustained (from vital_signs)
- Day of lab normalization: Find day where CRP/WBC returned to normal range (from lab_results)
- **Example**: "Day 7: CRP normalized" → MUST have lab_result with lab_name="CRP", value < 1.0 (normal), result_datetime on Day 7

### From Disease Protocol YAML:
- `course_archetypes[selected]`: Match CIF trajectory to expected course
  - If `smooth_recovery`: "Patient had uncomplicated recovery"
  - If `dip_then_recovery`: "Patient experienced temporary worsening on Day 2-3 before improvement"
  - If `plateau_then_recovery`: "Patient had delayed improvement starting Day 5"
- `order_protocols.discharge_criteria`: Verify CIF AFTER data meets discharge criteria
  - Japan: Afebrile 48h, CRP < 50% peak, SpO2 ≥ 95% on RA
  - US: Afebrile 24h, oral meds tolerated, SpO2 ≥ 92% on RA
- `treatment_protocols`: Verify medications administered match protocol
- `complications`: List any complications that occurred (from CIF.complications_occurred)

### From `medication_administrations`:
- Summary of key medications given (especially antibiotics)
- Route, frequency during stay

### From `discharge_prescription`:
- `items` list: {drug_name, dose, frequency, route, days_supply}

### From `vital_signs` (discharge vitals):
- Last vital signs before discharge
- Demonstrate stability

### From `lab_results` (discharge labs):
- Last labs before discharge (if done)
- Show improvement/resolution

**Prompt Structure**:
```
Patient: {age}yo {sex}
Admission Date: {admission_date}
Discharge Date: {discharge_date}
Length of Stay: {los_days} days

Admission Diagnosis: {admission_dx}
Discharge Diagnoses:
1. {primary_discharge_dx}
2. {secondary_dx_1}
3. {secondary_dx_2}

Complications: {complications_list or "None"}

Procedures Performed:
- {procedure_1} on Day {day}
- {procedure_2} on Day {day}

Hospital Course:
- Day 1: Admitted with {chief_complaint}. Vitals: {admission_vitals}. Labs: {admission_labs}. Started on {meds}.
- Day 3: {key_event_1} (e.g., defervescence, labs improving)
- Day 7: {key_event_2} (e.g., CRP normalized)
- Day {los}: Discharge vitals stable: {discharge_vitals}. Labs: {discharge_labs}.

Discharge Medications:
- {drug1}: {dose} {route} {frequency} x {days} days
- {drug2}: {dose} {route} {frequency} PRN

Discharge Disposition: {disposition}

Write a concise discharge summary.
```

---

## 3. Operative Note (LOINC 11504-8)

**Timing**: Generated immediately post-surgery

**Required CIF Data**:

### From `procedures` (specific procedure record):
- `procedure_code`, `procedure_system`
- `procedure_datetime`
- `surgeon_id`, `assistant_ids`, `anesthesiologist_id`
- `anesthesia_type` (general, spinal, local)
- `duration_minutes`
- `estimated_blood_loss_ml`
- `findings` (operative findings description)
- `specimens_sent` (if any)
- `complications_intraop` (list)
- `preop_diagnosis_code`, `postop_diagnosis_code`

### From `VitalSignRecord` (intraop vitals):
- Vitals during surgery (if recorded)
- Stability or any intraop events

### From `medication_administrations` (intraop):
- Antibiotics given (surgical prophylaxis)
- Anesthesia medications

**Prompt Structure**:
```
Patient: {age}yo {sex}

Preoperative Diagnosis: {preop_dx}
Postoperative Diagnosis: {postop_dx}

Procedure Performed: {procedure_name}
Surgeon: {surgeon_name}
Anesthesia: {anesthesia_type}
Duration: {duration} minutes

Indications: {indication_text}

Findings: {intraop_findings}

Technique:
[Brief description - can be partially templated based on procedure_code]

Estimated Blood Loss: {ebl} mL

Specimens: {specimens or "None"}

Complications: {complications or "None"}

Write a concise operative note.
```

---

## 4. Procedure Note (LOINC 28570-0)

**Timing**: Generated after bedside invasive procedure

**Required CIF Data**:

### From `procedures` (specific procedure record):
- `procedure_code`, `procedure_datetime`
- `performer_id` (physician)
- `indication` (reason for procedure)
- `technique_summary` (brief description)
- `complications_intraprocedure` (list)
- `consent_obtained_from` (patient/surrogate)

### From `VitalSignRecord` (peri-procedure):
- Vitals before and after procedure
- Patient tolerance

**Prompt Structure**:
```
Patient: {age}yo {sex}

Procedure: {procedure_name}
Date/Time: {procedure_datetime}
Performer: {performer_name}

Indication: {indication_text}

Consent: Informed consent obtained from {consent_from}.

Technique: {technique_summary}

Findings: {findings}

Complications: {complications or "None"}

Patient Toleration: {vitals_stability_description}

Write a concise procedure note.
```

---

## 5. Death Note (LOINC 69730-0)

**Timing**: Generated at time of death

**Required CIF Data**:

### From `Encounter`:
- `discharge_datetime` (= time of death if discharge_disposition = "exp")
- `discharge_disposition` = "exp" (expired)

### From `PatientProfile`:
- `age`, `sex`

### From `ClinicalDiagnosis`:
- `discharge_diagnosis_code` (cause of death)
- `secondary_diagnoses` (contributing causes)

### From `deceased`, `death_day`:
- Confirmation of death
- Hospital day of death

### From `complications_occurred`:
- Complications leading to death

### Hospital Course (brief):
- Key events from admission to death
- Interventions attempted (from orders, procedures)

### Family Notification:
- Timestamp of family notification
- Next of kin contact (if in PatientProfile)

**Prompt Structure**:
```
Patient: {age}yo {sex}

Time of Death: {death_datetime}

Cause of Death:
- Immediate: {immediate_cause}
- Underlying: {underlying_cause}

Hospital Course Summary:
Patient admitted on {admission_date} with {admission_dx}. Despite aggressive treatment including {interventions_list}, patient's condition deteriorated. Complications included {complications}. Patient expired on {death_date} at {death_time}.

Family Notification: Next of kin notified at {notification_time}.

Write a respectful and concise death note.
```

---

## Implementation Strategy

### Phase 1: Minimal Data (Current)
- Age, sex, diagnosis only
- **Status**: Implemented in test scripts
- **Problem**: Narratives contain hallucinated data (not CIF-consistent)

### Phase 2: Core Clinical Data (Next)
- Add vital signs (admission/discharge) with BEFORE/AFTER timestamps
- Add lab results (admission/discharge) with BEFORE/AFTER timestamps
- Add medications (key treatments)
- **Validation**: Check that narrative statements match CIF AFTER data
- **Status**: TODO - requires CIF data extraction

### Phase 3: Temporal Consistency Validation (Important)
- Implement validator: `validate_narrative_cif_consistency(narrative_text, cif_record)`
- Parse narrative for outcome statements ("normalized", "improved", "stable")
- Verify each statement against CIF AFTER data
- Flag inconsistencies for review
- **Status**: TODO - critical for production use

### Phase 4: Complete Data (Future)
- Add procedures with full details
- Add complications tracking
- Add daily hospital course events with trend analysis
- **Status**: TODO - may require CIF schema additions

---

## Data Extraction Module

**New module needed**: `clinosim/modules/narrative/cif_extractor.py`

### Example 1: Admission H&P (AFTER data only)

```python
def extract_admission_hp_data(cif_record: CIFPatientRecord) -> dict:
    """Extract data from CIF for Admission H&P narrative."""
    encounter = cif_record.encounters[0]  # first encounter
    
    # Get admission vitals (first vital sign record AFTER admission)
    admission_vitals = None
    if cif_record.vital_signs:
        admission_vitals = min(
            cif_record.vital_signs,
            key=lambda v: abs((v.timestamp - encounter.admission_datetime).total_seconds())
        )
    
    # Get admission labs (within first 4 hours AFTER admission)
    admission_cutoff = encounter.admission_datetime + timedelta(hours=4)
    admission_labs = [
        lab for lab in cif_record.lab_results
        if lab.result_datetime <= admission_cutoff
    ]
    
    return {
        "age": cif_record.patient.age,
        "sex": cif_record.patient.sex,
        "chief_complaint": encounter.chief_complaint,
        "pmh": cif_record.patient.medical_history,  # BEFORE admission
        "medications": cif_record.patient.current_medications,  # BEFORE admission
        "allergies": cif_record.patient.allergies,
        "admission_vitals": {  # AFTER admission (measured at ED/admission)
            "temp": admission_vitals.temperature_celsius,
            "hr": admission_vitals.heart_rate,
            "bp": f"{admission_vitals.systolic_bp}/{admission_vitals.diastolic_bp}",
            "rr": admission_vitals.respiratory_rate,
            "spo2": admission_vitals.spo2,
        } if admission_vitals else None,
        "admission_labs": [  # AFTER admission (ordered at admission)
            {
                "name": lab.lab_name,
                "value": lab.value,
                "unit": lab.unit,
                "flag": lab.flag,
            }
            for lab in admission_labs
        ],
        "admission_diagnosis": codes.lookup(
            cif_record.clinical_diagnosis.admission_diagnosis_system,
            cif_record.clinical_diagnosis.admission_diagnosis_code,
            "en"
        ),
    }
```

### Example 2: Discharge Summary (BEFORE vs AFTER comparison)

```python
def extract_discharge_summary_data(cif_record: CIFPatientRecord) -> dict:
    """Extract BEFORE and AFTER data for Discharge Summary."""
    encounter = cif_record.encounters[0]
    
    # BEFORE: Admission vitals and labs
    admission_vitals = get_vitals_near_datetime(
        cif_record.vital_signs, 
        encounter.admission_datetime, 
        window_hours=4
    )
    admission_labs = get_labs_near_datetime(
        cif_record.lab_results,
        encounter.admission_datetime,
        window_hours=4
    )
    
    # AFTER: Discharge vitals and labs
    discharge_vitals = get_vitals_near_datetime(
        cif_record.vital_signs,
        encounter.discharge_datetime,
        window_hours=4
    )
    discharge_labs = get_labs_near_datetime(
        cif_record.lab_results,
        encounter.discharge_datetime,
        window_hours=4
    )
    
    # Detect clinical events (e.g., defervescence, lab normalization)
    defervescence_day = find_defervescence_day(
        cif_record.vital_signs,
        encounter.admission_datetime
    )
    crp_normal_day = find_lab_normalization_day(
        cif_record.lab_results,
        lab_name="CRP",
        normal_threshold=1.0,
        admission_datetime=encounter.admission_datetime
    )
    
    return {
        "los_days": (encounter.discharge_datetime - encounter.admission_datetime).days,
        "admission_diagnosis": codes.lookup(...),  # BEFORE
        "discharge_diagnosis": codes.lookup(...),  # AFTER
        "admission_vitals": format_vitals(admission_vitals),  # BEFORE
        "discharge_vitals": format_vitals(discharge_vitals),  # AFTER
        "admission_labs": format_labs(admission_labs),  # BEFORE
        "discharge_labs": format_labs(discharge_labs),  # AFTER
        "key_events": [  # AFTER (outcomes)
            f"Day {defervescence_day}: Defervescence achieved" if defervescence_day else None,
            f"Day {crp_normal_day}: CRP normalized" if crp_normal_day else None,
        ],
        "complications": [  # AFTER
            codes.lookup(comp_system, comp_code, "en")
            for comp_code in cif_record.complications_occurred
        ],
        "discharge_medications": [  # AFTER
            format_medication(item)
            for item in cif_record.discharge_prescription.items
        ] if cif_record.discharge_prescription else [],
    }
```

---

## Implementation Phases

### Phase 1: Document Mapping ✅
- [x] Document CIF-Narrative mapping (this file)
- [x] Identify required fields from CIF, Disease Protocol, Encounter Scenario

### Phase 2: Data Extraction Module ⏳
Create `clinosim/modules/narrative/cif_extractor.py`:
- `extract_admission_hp_data(cif_record, disease_protocol, encounter_scenario=None)`
- `extract_discharge_summary_data(cif_record, disease_protocol)`
- `extract_operative_note_data(cif_record, procedure_record)`
- `extract_procedure_note_data(cif_record, procedure_record)`
- `extract_death_note_data(cif_record, disease_protocol)`

Each extractor:
1. Extracts CIF structured data (vitals, labs, meds)
2. Loads disease protocol YAML (via `disease_id`)
3. Loads encounter scenario YAML (if applicable, via `condition_id`)
4. Resolves codes to English display names via `codes.lookup()`
5. Returns dict with all data needed for prompt

### Phase 3: Prompt Builder Update ⏳
Update `clinosim/modules/llm_service/engine.py`:
- Modify `_build_prompt()` to accept extracted data dict (not just PatientSummary)
- Build detailed prompts with:
  - CIF vitals/labs (actual values)
  - Disease protocol context (typical course, standard treatment)
  - Encounter scenario context (severity, standard workup)

### Phase 4: Consistency Validation ⏳
Create `clinosim/modules/narrative/validator.py`:
- `validate_narrative_consistency(narrative_text, cif_record, disease_protocol)`
- Parse narrative for outcome statements ("normalized", "improved", "stable")
- Verify each against CIF AFTER data
- Check discharge criteria met (from disease protocol)
- Flag any hallucinated data or inconsistencies

### Phase 5: Integration Testing ⏳
- Test with real CIF data from full simulation
- Verify narratives match CIF+Protocol+Scenario
- Measure narrative quality with medical expert review
- Update prompts based on consistency validation results

## Next Steps

1. ✅ Document 3-way consistency (CIF + Disease Protocol + Encounter Scenario)
2. ⏳ Create `cif_extractor.py` module with all 5 extractors
3. ⏳ Update `_build_prompt()` in `engine.py` to use extracted data
4. ⏳ Create `validator.py` for consistency checking
5. ⏳ Add integration tests with real CIF+Protocol data
6. ⏳ Update `NEXT_STEPS.md` with implementation tasks

---

**Last Updated**: 2026-04-09
