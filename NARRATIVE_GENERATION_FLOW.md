# Narrative Generation Flow

**Purpose**: Define the complete flow for generating clinical narratives from CIF data and storing them back in CIF.

---

## Overview

```
CIF (Structured Data)
  ↓
1. Identify records needing narratives
  ↓
2. Extract relevant data for each narrative type
  ↓
3. Generate narrative with LLM
  ↓
4. Store narrative in CIF
  ↓
CIF (Structured Data + Narratives)
  ↓
FHIR Export (DocumentReference resources)
```

---

## Step 1: Identify Records Needing Narratives

**Function**: `identify_narratives_needed(cif_record: CIFPatientRecord) -> list[str]`

**Logic**:
```python
needed = []

for encounter in cif_record.encounters:
    if encounter.encounter_type == EncounterType.INPATIENT:
        # All inpatient encounters get Admission H&P
        needed.append("admission_hp")
        
        # Discharged patients get Discharge Summary
        if encounter.discharge_datetime:
            if cif_record.deceased and encounter.discharge_disposition == "exp":
                # Death discharge gets Death Note instead
                needed.append("death_note")
            else:
                needed.append("discharge_summary")
    
    elif encounter.encounter_type == EncounterType.EMERGENCY:
        # ED visits do not get narratives in v0.1
        # Future: ED note (LOINC 34111-5)
        pass
    
    elif encounter.encounter_type == EncounterType.OUTPATIENT:
        # Outpatient visits do not get narratives in v0.1
        # Future: Office visit note (LOINC 11506-3)
        pass

# Procedures generate Operative Note or Procedure Note
for procedure in cif_record.procedures:
    if is_surgical_procedure(procedure):
        needed.append("operative_note")
    elif is_invasive_bedside_procedure(procedure):
        needed.append("procedure_note")

return list(set(needed))  # Remove duplicates
```

**Output**: List of narrative types to generate, e.g., `["admission_hp", "discharge_summary"]`

---

## Step 2: Extract Relevant Data

**Function**: `extract_narrative_data(cif_record: CIFPatientRecord, narrative_type: str) -> dict`

**Module**: `clinosim/modules/narrative/cif_extractor.py`

**For each narrative type, extract**:

### Admission H&P
```python
{
    "patient": PatientProfile,
    "encounter": Encounter (INPATIENT),
    "admission_vitals": VitalSignRecord (first after admission),
    "admission_labs": list[OrderResult] (within 4h of admission),
    "admission_diagnosis": str (resolved from codes),
    "pmh": list[str] (patient medical history),
}
```

### Discharge Summary
```python
{
    "patient": PatientProfile,
    "encounter": Encounter (INPATIENT with discharge_datetime),
    "admission_vitals": VitalSignRecord,
    "admission_labs": list[OrderResult],
    "discharge_vitals": VitalSignRecord,
    "discharge_labs": list[OrderResult],
    "admission_diagnosis": str,
    "discharge_diagnosis": str,
    "los_days": int,
    "key_events": list[str] (e.g., "Day 3: Defervescence"),
    "discharge_medications": list[str],
}
```

### Operative Note
```python
{
    "patient": PatientProfile,
    "procedure": ProcedureRecord,
    "encounter": Encounter (containing procedure),
    "preop_diagnosis": str,
    "postop_diagnosis": str,
    "anesthesia_type": str,
    "duration_minutes": int,
    "ebl_ml": int,
    "findings": str,
    "complications": list[str],
}
```

### Procedure Note
```python
{
    "patient": PatientProfile,
    "procedure": ProcedureRecord,
    "encounter": Encounter,
    "indication": str,
    "technique": str,
    "complications": list[str],
    "pre_vitals": VitalSignRecord,
    "post_vitals": VitalSignRecord,
}
```

### Death Note
```python
{
    "patient": PatientProfile,
    "encounter": Encounter (with discharge_disposition="exp"),
    "death_datetime": datetime,
    "cause_of_death": str (resolved from diagnosis),
    "hospital_course_summary": str,
    "complications": list[str],
}
```

---

## Step 3: Generate Narrative with LLM

**Function**: `generate_narrative(narrative_type: str, extracted_data: dict, language: str) -> NarrativeDocument`

**Module**: `clinosim/modules/llm_service/engine.py`

**Process**:
```python
# 1. Build prompt from extracted data
system_prompt, user_prompt = build_prompt_from_extracted_data(
    narrative_type, 
    extracted_data, 
    language
)

# 2. Call LLM provider
response = llm_provider.complete(
    prompt=user_prompt,
    system_prompt=system_prompt,
    max_tokens=get_max_tokens(narrative_type),
)

# 3. Create NarrativeDocument
narrative = NarrativeDocument(
    narrative_id=f"narr-{extracted_data['encounter'].encounter_id}-{narrative_type}",
    narrative_type=narrative_type,
    loinc_code=NARRATIVE_LOINC_CODES[narrative_type],
    text=response.text,
    language=language,
    encounter_id=extracted_data['encounter'].encounter_id,
    model=response.model,
    source="llm",
    input_tokens=response.input_tokens,
    output_tokens=response.output_tokens,
)

return narrative
```

---

## Step 4: Store Narrative in CIF

**Function**: `add_narrative_to_cif(cif_record: CIFPatientRecord, narrative: NarrativeDocument)`

**Process**:
```python
# Simply append to narratives list
cif_record.narratives.append(narrative)
```

**Validation** (optional):
- Check narrative-CIF consistency
- Verify no duplicate narratives for same encounter+type
- Validate LOINC code matches type

---

## Complete Flow Example

```python
from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig
from clinosim.modules.narrative import (
    identify_narratives_needed,
    extract_narrative_data,
    generate_narrative,
    add_narrative_to_cif,
)

# Step 0: Generate CIF
config = SimulatorConfig(catchment_population=100, country="US")
cif_dataset = run_beta(config)

# Process each patient
for cif_record in cif_dataset.patients:
    # Step 1: Identify needed narratives
    needed = identify_narratives_needed(cif_record)
    
    for narrative_type in needed:
        # Step 2: Extract relevant data
        extracted_data = extract_narrative_data(cif_record, narrative_type)
        
        if extracted_data is None:
            continue  # Insufficient data
        
        # Step 3: Generate narrative
        narrative = generate_narrative(
            narrative_type=narrative_type,
            extracted_data=extracted_data,
            language="en",
        )
        
        # Step 4: Store in CIF
        add_narrative_to_cif(cif_record, narrative)

# Now cif_dataset contains both structured data AND narratives
# Export to FHIR (includes DocumentReference resources)
export_fhir(cif_dataset)
```

---

## FHIR Export

**Module**: `clinosim/modules/output/fhir_adapter.py`

**For each `NarrativeDocument` in `cif_record.narratives`**:

Create a FHIR DocumentReference resource:
```json
{
  "resourceType": "DocumentReference",
  "id": "narr-ENC123-admission-hp",
  "status": "current",
  "type": {
    "coding": [{
      "system": "http://loinc.org",
      "code": "34117-2",
      "display": "History and physical note"
    }]
  },
  "subject": {"reference": "Patient/PAT123"},
  "date": "2025-02-05T10:30:00Z",
  "context": {
    "encounter": [{"reference": "Encounter/ENC123"}]
  },
  "content": [{
    "attachment": {
      "contentType": "text/plain",
      "language": "en",
      "data": "<base64 encoded narrative.text>"
    }
  }]
}
```

Output to: `output/fhir_r4/DocumentReference.ndjson`

---

## Integration Points

### simulator/engine.py
```python
def run_beta(config):
    # ... existing simulation ...
    cif_dataset = generate_structural_data(...)
    
    # NEW: Narrative generation stage
    if config.llm_config and config.llm_config.get("narrative", {}).get("mode") == "llm":
        generate_all_narratives(cif_dataset, config.llm_config)
    
    # Export (now includes narratives)
    export_fhir(cif_dataset)
```

### modules/narrative/engine.py (NEW)
```python
def generate_all_narratives(cif_dataset: CIFDataset, llm_config: dict):
    """Generate narratives for all patients in dataset."""
    llm_service = create_llm_service(llm_config)
    
    for cif_record in cif_dataset.patients:
        # Step 1-4 as above
        ...
```

---

## Error Handling

### If LLM fails:
- Fall back to template-based narrative
- Mark `source="template"` in NarrativeDocument
- Log failure for review

### If extraction fails:
- Log warning
- Skip narrative generation for that type
- Continue with other narratives

### If validation fails:
- Log inconsistency
- Include narrative anyway (with warning flag)
- Report in cost_report()

---

## Cost Tracking

Track at dataset level:
```python
cif_dataset.metadata.narrative_stats = {
    "total_narratives_generated": 374,
    "llm_generated": 370,
    "template_fallback": 4,
    "total_input_tokens": 45000,
    "total_output_tokens": 120000,
    "estimated_cost_usd": 6.75,
}
```

---

## Testing

### Unit Tests
- `test_identify_narratives_needed()`: Various encounter types
- `test_extract_narrative_data()`: Each narrative type
- `test_generate_narrative()`: Mock LLM responses
- `test_add_narrative_to_cif()`: Duplicate detection

### Integration Tests
- Generate 1 patient, verify all narratives present
- Verify FHIR DocumentReference export
- Verify CIF round-trip (save → load → narratives intact)

### E2E Tests
- 100 patients, verify narrative count matches expected
- Verify no hallucinated data (validator check)
- Verify cost tracking

---

## Next Steps

1. ✅ Define NarrativeDocument type (types/narrative.py)
2. ✅ Add narratives field to CIFPatientRecord (types/output.py)
3. ⏳ Implement clinosim/modules/narrative/ module:
   - `__init__.py`
   - `cif_extractor.py` (Step 2)
   - `engine.py` (Steps 1, 3, 4)
   - `validator.py` (consistency checks)
4. ⏳ Update llm_service/engine.py to use extracted data
5. ⏳ Add FHIR DocumentReference export
6. ⏳ Integrate into simulator/engine.py

---

**Last Updated**: 2026-04-09
