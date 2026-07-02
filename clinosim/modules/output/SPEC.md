# output — Intermediate Format & Format Adapters

## Purpose
Three-stage output architecture with separable narrative layer:

1. **Stage 1 (simulator → CIF structural)**: Simulation writes all structural data (labs, vitals, orders, timestamps, staff assignments, physiological states) to CIF. JUDGMENT LLM calls (diagnostic reasoning, treatment decisions) occur during simulation — their results are embedded in structural data. Deterministic with same seed + same JUDGMENT LLM.
2. **Stage 2 (CIF structural + LLM → CIF full)**: Narrative generation reads structural CIF and adds clinical text (H&P, progress notes, discharge summaries, etc.) as a separate narrative layer. **This step can be re-run with a different LLM without re-running the simulation.**
3. **Stage 3 (CIF full → target format)**: Format adapters read the combined CIF (structural + narrative) and produce target-format files.

```
Key properties:
  - Structural data is generated ONCE and never changes.
  - Narratives can be regenerated any number of times with different LLMs.
  - Format conversion reads the combined CIF — never runs simulation.
  - Each narrative generation is versioned and stored alongside structural data.
```

## Current Implementation Status

| SPEC section | Status | Notes |
|---|---|---|
| Stage 1: CIF Writer | ✅ IMPLEMENTED | `cif_writer.py`, structural only |
| Stage 2: Narrative Generation | ✅ IMPLEMENTED (AD-65) | `document/narrative/passes.py:TemplateNarrativePass` |
| Stage 3: Format Adapters | ✅ IMPLEMENTED | `fhir_r4_adapter.py` (via `cif_reader.py`), `csv_adapter.py` |
| Folder structure | ✅ MATCHES SPEC | `cif/{structural,narratives/{template,<v>}}` |
| CIFReader | ✅ IMPLEMENTED | AD-65: `cif_reader.py` new, `narrative_version="current"` selector |

## Inputs
- Stage 1: `SimulationResult` (from simulator — in-memory)
- Stage 2: CIF structural files on disk + LLM config
- Stage 3: CIF full files on disk + `HealthcareSystemConfig` (for code mapping)

## Outputs
- Stage 1: CIF structural files on disk
- Stage 2: CIF narrative files on disk (added alongside structural files)
- Stage 3: Target format files (FHIR bundles, CSV, HL7v2, SQL, etc.)

## Dependencies
- Stage 1: `simulator` (produces SimulationResult)
- Stage 2: `llm_service` (generates narratives from structural data)
- Stage 3: `healthcare_system` (code mapping), CIF files only

---

## Internal Design

### Architecture

```
  Simulation run (one-time, deterministic)
       |
       v
  SimulationResult (in-memory)
       |
       v
  +---------------------------+
  | Stage 1: CIF Writer       |   Write structural data only
  | (JUDGMENT LLM only)       |
  +---------------------------+
       |
       v
  CIF structural layer on disk
  (labs, vitals, orders, timestamps, states — complete and immutable)
       |
       v
  +---------------------------+
  | Stage 2: Narrative Gen    |   Read structural CIF, call LLM, write narratives
  | (LLM-A, or LLM-B, or     |   Can be re-run with different LLM
  |  template, or skip)       |
  +---------------------------+
       |
       v
  CIF narrative layer on disk
  (H&P, progress notes, discharge summaries, nursing notes, etc.)
       |
       v
  CIF full = structural + narrative (merged at read time)
       |
       +-----> FHIR R4 Adapter -----> *.json (FHIR Bundles)
       |
       +-----> CSV Adapter ----------> *.csv (flat tables)
       |
       +-----> HL7 V2 Adapter -------> *.hl7 (messages)
       |
       +-----> Custom Adapter -------> any format
```

### Folder structure

```
modules/output/
+-- SPEC.md
+-- cif/
|   +-- writer.py              <- SimulationResult -> CIF files
|   +-- reader.py              <- CIF files -> CIFDataset (in-memory for adapters)
|   +-- schema.py              <- CIF schema definition
|   +-- format/
|       +-- json.py            <- JSON serialization (human-readable, larger)
|       +-- msgpack.py         <- MessagePack (compact binary, faster)
|       +-- parquet.py         <- Parquet (columnar, good for analytics)
+-- adapters/
|   +-- base.py                <- FormatAdapter abstract class
|   +-- fhir_r4/
|   |   +-- adapter.py
|   |   +-- resource_builders/
|   |   +-- profiles/          <- JP Core / US Core
|   +-- csv/
|   |   +-- adapter.py
|   +-- hl7v2/
|   |   +-- adapter.py
|   +-- sql/
|   |   +-- adapter.py
|   +-- (future adapters)
+-- code_mapping/
    +-- mapper.py
    +-- mappings/
        +-- lab_jlac10.yaml
        +-- lab_loinc.yaml
        +-- drug_yj.yaml
        +-- drug_rxnorm.yaml
        +-- diagnosis_icd10.yaml
        +-- diagnosis_icd10cm.yaml
        +-- procedure_kcode.yaml
        +-- procedure_cpt.yaml
```

---

### Clinosim Intermediate Format (CIF)

CIF is the **single source of truth** for all generated data. It contains everything — including data that some output formats cannot represent (hidden physiological states, LLM reasoning, simulation metadata).

#### CIF structure

```python
@dataclass
class CIFDataset:
    """Complete simulation output. Written to disk as CIF files."""
    
    # === Simulation metadata ===
    metadata: CIFMetadata
    
    # === Population (Layer 1 snapshot at simulation end) ===
    population_summary: PopulationSummary   # catchment area demographics, not all individual records
    
    # === Hospital context ===
    hospital: HospitalProfile
    staff_roster: list[StaffProfile]        # all staff who appear in records
    
    # === Patient records (the core output) ===
    patients: list[CIFPatientRecord]
    
    # === Validation results ===
    validation: ValidationReport

@dataclass
class CIFMetadata:
    clinosim_version: str
    generation_timestamp: datetime
    random_seed: int
    config: dict                           # full simulation config (reproducibility)
    country: str
    hospital_scale: str
    simulation_period: tuple[date, date]
    total_population: int
    total_patients_generated: int
    total_encounters: int
    llm_mode: str                          # "llm" | "template" | "none"
    llm_cost_report: dict | None           # token usage, cost

@dataclass
class CIFPatientRecord:
    """Complete patient record with ALL data layers."""
    
    # --- Patient identity & demographics ---
    patient: PatientProfile                # full Layer 2 profile
    household_context: HouseholdSummary    # family structure (anonymized)
    
    # --- Encounters ---
    encounters: list[Encounter]
    
    # --- Clinical events (chronological) ---
    events: list[ClinicalEvent]            # all events: vitals, labs, meds, notes, procedures
    
    # --- Orders ---
    orders: list[Order]                    # all orders with full lifecycle timestamps
    
    # --- Diagnosis evolution ---
    differential_history: list[DifferentialDiagnosis]  # probability snapshots over time
    
    # --- Staff assignments ---
    staff_assignments: list[StaffAssignment]
    
    # --- Device data ---
    device_readings: list[DeviceReading]   # auto-recorded device data (ICU monitors, POCT)
    
    # --- Prescriptions ---
    prescriptions: list[PrescriptionJP | PrescriptionUS]
    
    # --- Consent records ---
    consents: list[ConsentRecord]
    
    # --- Rehabilitation ---
    rehab_sessions: list[RehabSession]
    fim_scores: list[FIMScore]
    
    # --- Hidden state (not for clinical output, but for debugging/validation) ---
    physiological_states: list[PhysiologicalState]   # hidden state timeline
    disease_event: DiseaseEvent                       # original disease event with archetype
    
    # --- LLM provenance ---
    llm_calls: list[LLMCallRecord]         # what was asked, what was returned, from cache or fresh

@dataclass
class LLMCallRecord:
    """Provenance record for each LLM invocation."""
    task_type: str
    timestamp: datetime
    source: str                            # "llm" | "template" | "cache"
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_key: str | None
    # Input/output text NOT stored here (too large) — stored in LLM cache directory
```

#### CIF file layout on disk (two-layer)

```
output/cif/
+-- metadata.json                        <- CIFMetadata (simulation config, seed, version)
+-- hospital.json                        <- HospitalProfile + staff roster
+-- population_summary.json              <- PopulationSummary (aggregate stats)
+-- validation_report.json               <- ValidationReport (benchmarks, issues)
|
+-- structural/                          <- LAYER 1: Structural data (immutable after Stage 1)
|   +-- patients/
|       +-- P-000001.json               <- Structural CIFPatientRecord (no narratives)
|       +-- P-000002.json
|       +-- ...
|
+-- narratives/                          <- LAYER 2: Narrative data (re-generatable)
|   +-- current/                         <- Currently active narrative version
|   |   +-- manifest.json               <- {llm_model, generation_timestamp, version_id}
|   |   +-- patients/
|   |       +-- P-000001.json           <- Narrative records for this patient
|   |       +-- P-000002.json
|   |       +-- ...
|   +-- versions/                        <- Previous narrative versions (kept for comparison)
|       +-- v1_haiku_20240601/
|       |   +-- manifest.json
|       |   +-- patients/
|       +-- v2_sonnet_20240615/
|           +-- manifest.json
|           +-- patients/
```

**Structural patient file** contains: labs, vitals, orders, timestamps, staff assignments, physiological states, encounter structure, diagnosis probabilities — everything EXCEPT free-text narratives.

**Narrative patient file** contains: H&P note, progress notes, discharge summary, nursing notes, consultation notes, operative notes, treatment rationale, diagnostic reasoning text — all free-text content.

When a format adapter reads CIF, it **merges** structural + current narrative at read time:

```python
class CIFReader:
    def __init__(self, cif_dir: str, narrative_version: str = "current"):
        self.structural_dir = os.path.join(cif_dir, "structural", "patients")
        self.narrative_dir = os.path.join(cif_dir, "narratives", narrative_version, "patients")
    
    def read_patient(self, patient_id: str) -> CIFPatientRecord:
        structural = load_json(os.path.join(self.structural_dir, f"{patient_id}.json"))
        narrative = load_json(os.path.join(self.narrative_dir, f"{patient_id}.json"))
        return merge_structural_narrative(structural, narrative)
```

#### CIF serialization formats

| Format | Extension | Size (100 patients) | Read speed | Use case |
|---|---|---|---|---|
| JSON | `.json` | ~50 MB | Moderate | Human-readable, debugging, small datasets |
| MessagePack | `.msgpack` | ~20 MB | Fast | Production, medium datasets |
| Parquet | `.parquet` | ~10 MB | Very fast (columnar) | Analytics, large datasets, direct query via DuckDB/pandas |

Default: JSON for development, MessagePack for production.

---

### Stage 1: CIF Writer

```python
class CIFWriter:
    def __init__(self, output_dir: str, format: str = "json"):
        self.output_dir = output_dir
        self.serializer = get_serializer(format)  # json | msgpack | parquet
    
    def write(self, result: SimulationResult):
        """Write complete simulation result to CIF files. Called once after simulation."""
        
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Metadata
        self.serializer.write(
            os.path.join(self.output_dir, "metadata"),
            result.metadata
        )
        
        # Hospital context
        self.serializer.write(
            os.path.join(self.output_dir, "hospital"),
            {"hospital": result.hospital, "staff": result.staff_roster}
        )
        
        # Patients (one file per patient for parallel processing)
        patients_dir = os.path.join(self.output_dir, "patients")
        os.makedirs(patients_dir, exist_ok=True)
        for patient_record in result.patients:
            self.serializer.write(
                os.path.join(patients_dir, patient_record.patient.patient_id),
                patient_record
            )
        
        # Validation
        self.serializer.write(
            os.path.join(self.output_dir, "validation_report"),
            result.validation
        )
        
```

### Stage 2: Narrative Generation

Reads structural CIF, generates narrative text for each patient, writes narrative layer.
Can be run multiple times with different LLMs. Structural data is never touched.

```python
class NarrativeGenerator:
    def __init__(self, llm_service: LLMService):
        self.llm = llm_service
    
    def generate(self, cif_dir: str, version_id: str | None = None):
        """Generate narratives for all patients in a structural CIF."""
        
        structural_dir = os.path.join(cif_dir, "structural", "patients")
        
        # Create versioned narrative directory
        if version_id is None:
            version_id = f"{self.llm.model_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        narrative_dir = os.path.join(cif_dir, "narratives", version_id, "patients")
        os.makedirs(narrative_dir, exist_ok=True)
        
        # Write manifest
        manifest = {
            "version_id": version_id,
            "llm_provider": self.llm.provider_name,
            "llm_model_map": self.llm.model_map,
            "generation_mode": self.llm.mode,  # "llm" | "template"
            "generation_timestamp": datetime.now().isoformat(),
            "patient_count": 0,
        }
        
        # Generate narratives per patient
        for patient_file in sorted(os.listdir(structural_dir)):
            patient_id = patient_file.replace(".json", "")
            structural = load_json(os.path.join(structural_dir, patient_file))
            
            narratives = self._generate_patient_narratives(structural)
            
            write_json(narratives, os.path.join(narrative_dir, patient_file))
            manifest["patient_count"] += 1
        
        # Write manifest
        write_json(manifest, os.path.join(cif_dir, "narratives", version_id, "manifest.json"))
        
        # Set as current
        current_link = os.path.join(cif_dir, "narratives", "current")
        if os.path.exists(current_link):
            os.remove(current_link)
        os.symlink(version_id, current_link)
    
    def _generate_patient_narratives(self, structural: dict) -> dict:
        """Generate all narrative texts for one patient from structural data."""
        
        patient_summary = build_patient_summary(structural)
        narratives = {"patient_id": structural["patient"]["patient_id"], "notes": []}
        
        for encounter in structural["encounters"]:
            # Admission H&P
            if encounter["encounter_type"] == "inpatient":
                hp = self.llm.generate(
                    LLMTaskType.ADMISSION_HP,
                    ClinicalEventData(
                        patient_summary=patient_summary,
                        event_data=extract_admission_data(structural, encounter),
                        language=get_language(structural),
                    )
                )
                narratives["notes"].append({
                    "encounter_id": encounter["encounter_id"],
                    "note_type": "admission_hp",
                    "timestamp": encounter["admission_datetime"],
                    "text": hp.text,
                    "source": hp.source,
                })
            
            # Progress notes (key days)
            for day_event in extract_key_days(structural, encounter):
                note = self.llm.generate(
                    LLMTaskType.PROGRESS_NOTE,
                    ClinicalEventData(
                        patient_summary=patient_summary,
                        event_data=day_event,
                        language=get_language(structural),
                    )
                )
                narratives["notes"].append({
                    "encounter_id": encounter["encounter_id"],
                    "note_type": "progress_note",
                    "timestamp": day_event["date"],
                    "text": note.text,
                    "source": note.source,
                })
            
            # Discharge summary
            if encounter.get("discharge_datetime"):
                ds = self.llm.generate(
                    LLMTaskType.DISCHARGE_SUMMARY,
                    ClinicalEventData(
                        patient_summary=patient_summary,
                        event_data=extract_discharge_data(structural, encounter),
                        language=get_language(structural),
                    )
                )
                narratives["notes"].append({
                    "encounter_id": encounter["encounter_id"],
                    "note_type": "discharge_summary",
                    "timestamp": encounter["discharge_datetime"],
                    "text": ds.text,
                    "source": ds.source,
                })
        
        return narratives
```

#### Re-generating narratives with a different LLM

```python
# Original generation with Haiku (fast, cheap)
llm_haiku = LLMService(LLMServiceConfig(mode="llm", model_map={"small": "haiku", "medium": "haiku", "large": "haiku"}))
generator = NarrativeGenerator(llm_haiku)
generator.generate("./output/cif/")
# -> narratives/haiku_20240601_120000/

# Review... not satisfied with quality. Re-generate with Sonnet.
llm_sonnet = LLMService(LLMServiceConfig(mode="llm", model_map={"small": "haiku", "medium": "sonnet", "large": "sonnet"}))
generator2 = NarrativeGenerator(llm_sonnet)
generator2.generate("./output/cif/")
# -> narratives/sonnet_20240601_130000/ (set as current)

# Previous version still exists for comparison
# Structural data untouched throughout
```

#### Narrative-only re-generation: what changes, what doesn't

| Data | Structural (immutable) | Narrative (re-generatable) |
|---|---|---|
| Lab values (numeric) | YES | |
| Vital signs (numeric) | YES | |
| Order timestamps | YES | |
| Medication orders | YES | |
| Staff assignments | YES | |
| Diagnosis codes (ICD) | YES | |
| Diagnosis probabilities | YES | |
| Physiological states | YES | |
| Encounter structure | YES | |
| Admission H&P text | | YES |
| Daily progress notes | | YES |
| Discharge summary text | | YES |
| Nursing notes (narrative) | | YES |
| Consultation notes | | YES |
| Operative notes | | YES |
| Treatment rationale text | | YES |
| Diagnostic reasoning text | | YES |

### Stage 3: Format Adapters

Adapters read CIF (structural + current narrative merged), NOT simulation internals. They are completely decoupled from the simulation engine.

```python
class FormatAdapter(ABC):
    """Base class for all format adapters. Reads CIF, writes target format."""
    
    @abstractmethod
    def convert(self, cif_dir: str, output_dir: str, config: HealthcareSystemConfig) -> None:
        """Convert CIF dataset to target format."""
        pass
    
    @abstractmethod
    def format_id(self) -> str:
        pass

class OutputService:
    def __init__(self):
        self.adapters: dict[str, FormatAdapter] = {}
        self._register_builtin()
    
    def _register_builtin(self):
        self.adapters["fhir_r4"] = FHIRR4Adapter()
        self.adapters["csv"] = CSVAdapter()
    
    def register(self, adapter: FormatAdapter):
        self.adapters[adapter.format_id()] = adapter
    
    def convert(self, cif_dir: str, formats: list[str], output_dir: str, 
                config: HealthcareSystemConfig):
        """Convert CIF to one or more output formats."""
        for fmt in formats:
            adapter = self.adapters[fmt]
            fmt_dir = os.path.join(output_dir, fmt)
            adapter.convert(cif_dir, fmt_dir, config)
```

#### FHIR R4 Adapter (reads CIF)

```python
class FHIRR4Adapter(FormatAdapter):
    def convert(self, cif_dir: str, output_dir: str, config: HealthcareSystemConfig):
        reader = CIFReader(cif_dir)
        mapper = CodeMapper(config)
        
        for patient_record in reader.iter_patients():
            bundle = self._build_bundle(patient_record, mapper, config)
            write_json(bundle, os.path.join(output_dir, f"{patient_record.patient.patient_id}.json"))
    
    def _build_bundle(self, record: CIFPatientRecord, mapper: CodeMapper, config) -> dict:
        bundle = {"resourceType": "Bundle", "type": "collection", "entry": []}
        
        # Patient resource
        bundle["entry"].append(build_patient(record.patient, mapper))
        
        # Select and transform relevant data from CIF
        # CIF has everything; FHIR adapter picks what FHIR can represent
        for event in record.events:
            match event.event_type:
                case "vital_signs":
                    bundle["entry"].append(build_observation_vitals(event, mapper))
                case "lab_result":
                    bundle["entry"].append(build_observation_lab(event, mapper))
                case "medication_administration":
                    bundle["entry"].append(build_medication_admin(event, mapper))
                case "note":
                    bundle["entry"].append(build_document_reference(event, mapper))
                # ... etc
        
        # Note: CIF fields like physiological_states, disease_event (hidden),
        # llm_calls (provenance) are NOT included in FHIR output — they don't
        # map to FHIR resources. They remain in CIF for debugging/validation.
        
        return bundle
    
    def format_id(self) -> str:
        return "fhir_r4"
```

#### CSV Adapter (reads CIF)

```python
class CSVAdapter(FormatAdapter):
    def convert(self, cif_dir: str, output_dir: str, config: HealthcareSystemConfig):
        reader = CIFReader(cif_dir)
        mapper = CodeMapper(config)
        
        # Collect all records, flatten into tables
        patients_rows = []
        encounters_rows = []
        labs_rows = []
        vitals_rows = []
        meds_rows = []
        notes_rows = []
        
        for record in reader.iter_patients():
            patients_rows.append(flatten_patient(record.patient, mapper))
            for enc in record.encounters:
                encounters_rows.append(flatten_encounter(enc, mapper))
            for event in record.events:
                match event.event_type:
                    case "lab_result":
                        labs_rows.append(flatten_lab(event, mapper))
                    case "vital_signs":
                        vitals_rows.append(flatten_vitals(event))
                    case "medication_administration":
                        meds_rows.append(flatten_med(event, mapper))
                    case "note":
                        notes_rows.append(flatten_note(event))
        
        write_csv(output_dir, "patients.csv", patients_rows)
        write_csv(output_dir, "encounters.csv", encounters_rows)
        write_csv(output_dir, "lab_results.csv", labs_rows)
        write_csv(output_dir, "vital_signs.csv", vitals_rows)
        write_csv(output_dir, "medications.csv", meds_rows)
        write_csv(output_dir, "clinical_notes.csv", notes_rows)
    
    def format_id(self) -> str:
        return "csv"
```

---

### Code mapping (shared by all adapters)

```python
class CodeMapper:
    """Maps internal clinosim identifiers to standard code systems."""
    
    def __init__(self, config: HealthcareSystemConfig):
        self.lab_system = config.lab_code_system      # "JLAC10" | "LOINC"
        self.dx_system = config.diagnosis_code_system  # "ICD-10" | "ICD-10-CM"
        self.drug_system = config.drug_code_system     # "YJ" | "RxNorm"
        self.proc_system = config.procedure_code_system # "K-code" | "CPT"
        
        self.lab_map = load_yaml(f"code_mapping/mappings/lab_{self.lab_system.lower()}.yaml")
        self.drug_map = load_yaml(f"code_mapping/mappings/drug_{self.drug_system.lower()}.yaml")
        # ... etc
    
    def map_lab(self, internal_name: str) -> CodedValue:
        return self.lab_map[internal_name]  # {"code": "5C070", "display": "CRP", "system": "JLAC10"}
    
    def map_drug(self, internal_name: str) -> CodedValue:
        return self.drug_map[internal_name]
    
    def map_diagnosis(self, internal_code: str) -> CodedValue:
        return self.dx_map.get(internal_code, {"code": internal_code, "display": "Unknown"})
```

---

### Top-level API (updated)

```python
# Run simulation (once)
sim = Simulator(config)
result = sim.run()

# Write CIF (once) — contains ALL data
cif_writer = CIFWriter("./output/cif/", format="json")
cif_writer.write(result)

# Convert to any format, any time, any number of times (from CIF)
output_service = OutputService()

# Generate FHIR R4
output_service.convert("./output/cif/", ["fhir_r4"], "./output/", config.healthcare)

# Later, also want CSV? No re-simulation needed.
output_service.convert("./output/cif/", ["csv"], "./output/", config.healthcare)

# Want both FHIR and CSV at once?
output_service.convert("./output/cif/", ["fhir_r4", "csv"], "./output/", config.healthcare)

# Want to convert the same CIF with US coding instead of JP?
us_config = HealthcareSystemConfig(country="US", ...)
output_service.convert("./output/cif/", ["fhir_r4"], "./output_us/", us_config)
```

### CIF as shareable artifact

CIF files can be:
- **Archived**: Store simulation results for later format conversion
- **Shared**: Send CIF to collaborators who can generate their own format
- **Versioned**: Track how simulation outputs change across code versions
- **Queried directly**: Parquet format enables SQL queries via DuckDB without conversion
- **Validated independently**: Run validation benchmarks against CIF without re-simulation

---

## Open Questions
- [ ] CIF schema versioning: how to handle CIF format changes across clinosim versions
- [ ] Large dataset handling: streaming CIF write for 10,000+ patients (memory)
- [ ] CIF compression: gzip per-file or archive-level
- [ ] Parquet schema design: which fields become columns vs. nested JSON
- [ ] CIF → CIF transformation (e.g., anonymization, subsetting) as a special adapter

## Design Notes
- **CIF is the product of simulation. Format files are the product of conversion.** This separation is fundamental.
- Adapters NEVER import simulation modules. They only read CIF files and use CodeMapper.
- Hidden state data (PhysiologicalState, DiseaseEvent archetype) is preserved in CIF for validation and debugging, but adapters for clinical formats (FHIR, HL7v2) ignore these fields.
- LLM provenance (which calls were made, cache hit/miss) is in CIF for audit but not in clinical outputs.
- The same CIF can be converted to different country coding systems — useful for cross-border research scenarios.

## Change Log

### AD-65 (2026-07-02): Two-Pass CIF Generation Architecture Restoration

**Context**: SPEC.md defined a three-stage pipeline with structural/narrative file separation. α-min-1 Task 15 consolidated narrative generation into `document_enricher` (Stage 1) for immediate implementation, but this introduced coupling that made Stage 2 narrative regeneration infeasible. Session 27 revealed three critical narrative bugs with full-cohort re-simulation as the only recovery path.

**Changes**:
- Restored file-level separation: `cif/structural/patients/<enc>.json` (immutable) and `cif/narratives/<version>/documents/<enc>/<doc>.json` (re-generatable)
- Introduced `ClinicalDocumentNarrative` wrapper type for narrative layer
- `document_enricher` now emits stub documents (`narrative=None`) only
- New `TemplateNarrativePass` module for post-simulation narrative generation
- New `CIFReader` for merging structural + narrative versions at read time
- Added `clinosim narrate` verb for standalone narrative generation
- Bedrock prompt cache-friendly walk order contract: `(doc_type, language)` group serial

**Impact**: Narrative bug verification cycle reduced from 50 min (full cohort re-sim) to 30 sec (re-narrate only). Stage 2 LLM swap enabled without simulation re-run.