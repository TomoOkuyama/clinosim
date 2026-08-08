## 6.1 Code System Module (`clinosim/codes/`)

### Problem

Initially, terminology files (e.g., ICD code → display name) lived under
`clinosim/locale/jp/terminology_diagnosis.yaml` and similar paths. This created two
issues:

1. **Misclassification**: ICD-10-CM is an international standard, not a culture-specific
   data set. Putting it under `locale/jp/` implied locale-scoped ownership when actually
   it's the same code values, just translated.
2. **Translation duplication**: When supporting JP and US, the same ICD code had
   separate entries in two files. Updating one but not the other led to mismatches.
3. **CIF redundancy**: `ClinicalDiagnosis` stored both `discharge_diagnosis_code` and
   `discharge_diagnosis_name`. The name was a derivative of the code + locale, but
   stored separately, allowing them to drift.

### Decision (AD-30, AD-33, AD-35)

Create a new `clinosim/codes/` module that is **locale-independent** and serves as the
single source of truth for clinical code systems.

```
clinosim/codes/
├── __init__.py          # public API
├── loader.py            # lookup() with language fallback
├── README.md            # module documentation
└── data/
    ├── icd-10-cm.yaml   # 224 codes, all with EN, most with JA
    ├── icd-10.yaml      # WHO version (110 codes)
    ├── loinc.yaml       # 59 codes
    ├── jlac10.yaml      # 30 codes
    ├── rxnorm.yaml      # 68 codes
    ├── yj.yaml          # 39 codes
    ├── cpt.yaml         # 25 codes
    └── k-codes.yaml     # 2 codes
```

### Schema

```yaml
metadata:
  name: "ICD-10-CM"
  uri: "http://hl7.org/fhir/sid/icd-10-cm"   # FHIR canonical system URI
  version: "2024"
  description: "..."

codes:
  N10:
    en: "Acute tubulo-interstitial nephritis"   # REQUIRED
    ja: "急性腎盂腎炎"                          # optional
  J18.9:
    en: "Pneumonia, unspecified organism"
    ja: "肺炎，詳細不明"
```

### Principles

1. **English-first**: Every code MUST have an `en` field. Other languages are optional
   translation attributes. The loader falls back to English if a requested language
   is missing, then to the code itself.

2. **Authoritative sources**: Code values and English text follow official definitions
   from CMS (ICD-10-CM), NLM (RxNorm), Regenstrief (LOINC), AMA (CPT), WHO (ICD-10),
   JCCLS (JLAC10), MHLW (YJ codes, K codes).

3. **Locale-independent**: `codes/` is at the same level as `locale/`, NOT inside it.
   Code systems are international standards.

4. **Single lookup API**:
   ```python
   from clinosim.codes import lookup, get_system_uri
   lookup("icd-10-cm", "N10", "en")  # → "Acute tubulo-interstitial nephritis"
   lookup("icd-10-cm", "N10", "ja")  # → "急性腎盂腎炎"
   get_system_uri("loinc")           # → "http://loinc.org"
   ```

### Impact on CIF

`ClinicalDiagnosis` was simplified — `*_name` fields removed, `*_system` added:

```python
# Before
@dataclass
class ClinicalDiagnosis:
    admission_diagnosis_code: str
    admission_diagnosis_name: str          # ← removed
    discharge_diagnosis_code: str
    discharge_diagnosis_name: str          # ← removed

# After
@dataclass
class ClinicalDiagnosis:
    admission_diagnosis_code: str
    admission_diagnosis_system: str = "icd-10-cm"   # ← added
    discharge_diagnosis_code: str
    discharge_diagnosis_system: str = "icd-10-cm"   # ← added
```

`ChronicCondition.name` was similarly removed. Display text is now resolved by output
adapters (FHIR, CSV, narrative) calling `clinosim.codes.lookup()` at output time.

### Locale module after migration

`clinosim/locale/` now contains only **culture/country-dependent** data:

- `names.yaml` — person name generation (kanji + reading for JP, given/family for US)
- `addresses.yaml` — 47 prefectures / 50 states + ZIP code patterns
- `demographics.yaml` — population age distribution, disease incidence rates
- `formatting.yaml` — date and unit formatting rules
- `reference_range_lab.yaml` — JCCLS / Tietz lab reference ranges
- `code_mapping_*.yaml` — internal test name → standard code (kept here because the
  internal name "WBC" is a clinosim implementation detail, not a standard)

The old `terminology_*.yaml` files were removed.

---

## 6.2 FHIR Bulk Data Export NDJSON (AD-31)

### Problem

The original FHIR R4 adapter wrote one Bundle JSON file per encounter
(`ENC-POP-XXXXXX-NNNNNN.json`). This worked but had drawbacks:

1. **File explosion**: 153,530 files for a 60k catchment hospital
2. **Wrapping overhead**: each Bundle had `Bundle.entry[]` wrapping that was redundant
3. **Resource id duplication**: vital sign IDs collided across patient encounters
   (`vs-{patient_id}-0000-heart_rate` recurred per encounter)
4. **Not standard format**: real EHR vendors (Epic, Cerner) export via FHIR Bulk Data
   Access spec (NDJSON files per resource type), not as per-patient bundles

### Decision (AD-31)

Replace per-encounter Bundle output with HL7 FHIR Bulk Data Access compliant NDJSON:

```
output/fhir_r4/
├── manifest.json                           # Bulk Data manifest
├── _facility.json                          # Org + Location master Bundle
├── Patient.ndjson                          # 1 patient per line
├── Encounter.ndjson                        # 1 encounter per line
├── Observation.ndjson                      # labs + vitals (LOINC)
├── Condition.ndjson                        # ICD-10-CM
├── MedicationRequest.ndjson                # RxNorm
├── MedicationAdministration.ndjson         # MAR
├── Procedure.ndjson                        # CPT
├── AllergyIntolerance.ndjson               # patient-level
├── Practitioner.ndjson                     # staff master
├── PractitionerRole.ndjson                 # specialty + ward
├── Organization.ndjson                     # hospital + departments
└── Location.ndjson                         # wards + beds
```

### Resource id uniqueness

A critical FHIR R4 invariant: `Resource.id` MUST be unique within its resource type.
The old per-encounter Bundle approach hid violations because each Bundle was
self-contained. Once aggregated into NDJSON, collisions became visible.

Fixed by including `encounter_id` in resource ids:

- Lab obs: `lab-{encounter_id}-{seq}` instead of `lab-{patient_id}-{seq}`
- Vital obs: `vs-{encounter_id}-{seq}-{field}`
- MAR: `mar-{encounter_id}-{seq}`
- MedRequest: `{encounter_id}-{order_id}` (prefixed)
- Procedure: `{encounter_id}-{procedure_id}` (prefixed)
- Condition (encounter dx): `cond-{encounter_id}-primary`
- Condition (chronic): `cond-{encounter_id}-chronic-{idx}`

Patient-level resources (Patient, Practitioner, AllergyIntolerance) are deduplicated
in the NDJSON writer rather than re-emitted.

### Manifest format

Follows the [HL7 FHIR Bulk Data Access spec](https://hl7.org/fhir/uv/bulkdata/):

```json
{
  "transactionTime": "2026-04-08T17:30:00",
  "request": "clinosim generate (country=US)",
  "requiresAccessToken": false,
  "output": [
    {"type": "Patient", "url": "Patient.ndjson"},
    {"type": "Encounter", "url": "Encounter.ndjson"},
    ...
  ],
  "error": []
}
```

This format is consumable by any FHIR client expecting Bulk Data export, including
Epic and Cerner integration tools.

### Size impact

For US 50-bed hospital, catchment 30k, 1 year:
- Old format: 153,530 files, 5.7 GB total
- New format: 13 files, 1.3 GB total (-77% size reduction from JSON wrapping removal)

---

## 6.3 Snapshot Date Semantics (AD-32)

### Problem

The simulator generated all encounters that fell within the simulation period to
completion (every encounter had `discharge_datetime` set). This produced "all patients
discharged" datasets, which don't reflect a real EHR snapshot where some patients are
currently admitted.

For visualization tools and AI models trained on EHR snapshots (e.g., NEWS2 alert
systems for currently admitted patients), this was a significant gap.

### Decision (AD-32)

Introduce **snapshot date** semantics:

- `--end YYYY-MM-DD` flag = the snapshot date (defaults to today)
- `--start YYYY-MM-DD` defaults to `--end - 1 year`
- No life events generated past the snapshot date
- Inpatients whose `discharge_datetime` would fall after the snapshot date are
  truncated:
  - `Encounter.status = "in-progress"`
  - `discharge_datetime = None`
  - `discharge_disposition = ""`
  - `discharging_physician_id = ""`
  - Lab/vital/order/MAR records filtered to ≤ snapshot day
  - Discharge prescription not issued
- Primary `Condition.clinicalStatus = "active"` for in-progress encounters (vs
  `resolved` for completed ones)
- Death is exempt from this rule (deceased patients are always "completed" with
  `dischargeDisposition = "exp"`)

### Result

A typical 50-bed hospital with avg LOS 5 days and ~3 admissions/day produces ~15
in-progress encounters at any point in time (~30% occupancy). With higher catchment
and longer LOS, this approaches realistic 80% bed occupancy.

This enables generating realistic EHR snapshots for:
- NEWS2 / early warning alert systems
- Bed management dashboards
- Real-time clinical decision support training data

---

## 6.4 Hospital Configuration-Driven Layout (AD-34)

### Problem

Hospital physical layout (which departments exist, which wards belong to which
specialty, how many beds per ward) was hardcoded or randomly assigned. This created:

1. **Inconsistent FHIR data**: encounters claimed to be in non-existent wards
2. **Staffing mismatches**: PractitionerRole specialties didn't match Encounter
   serviceType
3. **No bed capacity model**: no way to enforce occupancy limits

### Decision (AD-34)

Hospital configuration YAML defines the complete physical and organizational layout:

```yaml
# clinosim/config/hospital_operations.yaml (50-bed hospital)
recommended_population: 60000

available_departments:           # specialties this hospital supports
  - internal_medicine
  - cardiology
  - gastroenterology
  - general_surgery
  - orthopedics
  - emergency_medicine
  - primary_care

department_rollup:               # specialty → available department mapping
  pulmonology: internal_medicine    # disease YAML says pulmonology, hospital says IM
  neurology: internal_medicine
  neurosurgery: general_surgery
  trauma_surgery: general_surgery

wards:                           # which wards each department uses
  internal_medicine: ["4E", "4W"]
  cardiology: ["5E"]
  gastroenterology: ["5W"]
  general_surgery: ["3E"]
  orthopedics: ["3W"]
  emergency_medicine: ["ER"]
  primary_care: ["OPD"]

ward_capacity:                   # bed count per ward
  "4E": 10
  "4W": 10
  "5E": 8
  "5W": 8
  "3E": 8
  "3W": 6
```

### Cascading effects

1. **Disease → department resolution**: `disease.department` (granular) is rolled up
   via `department_rollup` to one of `available_departments`. So a `pulmonology` disease
   in a hospital that doesn't have pulmonology gets routed to `internal_medicine`.

2. **Staff generation**: `generate_roster()` creates physicians ONLY for
   `available_departments`. Nurses are distributed across `wards` (each ward gets
   ~6 nurses, scaled by `ward_capacity`).

3. **Bed assignment**: When an encounter is created, `bed_number` is sampled from
   `1..ward_capacity[ward_id]`. No more random "601-3" bed numbers.

4. **FHIR Location resources**: `_facility.json` contains one `Location` per ward
   (physicalType=wa) and one per bed (physicalType=bd, partOf the ward). Encounter
   references the bed Location, which references the ward via `partOf`.

5. **PractitionerRole.location**: nurses are assigned to a ward in their roster entry,
   which is reflected in PractitionerRole.location reference.

This means hospital templates (`hospital_operations.yaml` for 50-bed,
`hospital_small.yaml` for 10-bed) are now genuinely different hospitals, not just
size labels.

---

## 6.5 Updated module list

The current module count has grown beyond v0.1-alpha:

```
clinosim/
├── codes/                  ★ NEW (AD-30, AD-33, AD-35)
├── locale/
├── config/
├── types/
├── modules/
│   ├── disease/            (32 disease YAMLs)
│   ├── encounter/          (46 ED/outpatient YAMLs)
│   ├── physiology/
│   ├── clinical_course/
│   ├── diagnosis/
│   ├── observation/
│   ├── order/
│   ├── procedure/          ★ NEW (was empty, now 15 bedside procedures)
│   ├── population/
│   ├── patient/
│   ├── staff/              (ward-aware after AD-34)
│   ├── facility/           ★ NEW README (M/M/1 queueing)
│   ├── healthcare_system/
│   ├── output/             (Bulk Data NDJSON after AD-31)
│   ├── llm_service/
│   └── validator/
└── simulator/              (orchestration: engine, inpatient, emergency, outpatient)
```

Each module has its own README.md with API reference and design notes.

---

## 6.6 Realistic vital sign measurement patterns

### Problem

Initial implementation generated all 6 vital signs (T, HR, BP, RR, SpO2) at every
measurement time, with the same timestamp. This was unrealistic:

- Outpatient HTN visit: only BP and HR are measured (not all 6)
- Continuous monitoring: HR and SpO2 every 1-2h, but full vitals only q6h
- Same timestamp for all 6 fields is implausible (BP cuff and thermometer aren't
  simultaneous)

### Decision

1. **Inpatient**: separate routine full vitals (q4h–q8h based on acuity) from
   continuous monitoring (HR + SpO2 only every 2h for unstable/respiratory patients)
   plus event-driven recheck (T-only re-measurement after fever).

2. **Outpatient**: vital subset by visit type and chronic condition:
   - HTN/DM/IHD followup: BP + HR
   - HF: BP + HR + weight + SpO2
   - COPD: BP + HR + SpO2 + RR
   - Annual physical: full set

3. **Per-field timestamp offset** (in FHIR adapter):
   - HR / BP simultaneous (same device cycle)
   - SpO2: +5s
   - Temperature: +30s
   - RR: +60s

This produces NEWS2-compatible vital data while remaining clinically plausible.

---

## 6.7 NEWS2 / early warning vital data

To support NEWS2 (National Early Warning Score 2) alert systems, vitals now include:

- **AVPU consciousness level** (Alert / Voice / Pain / Unresponsive)
  - LOINC code 80288-4
  - SNOMED concept value (248234008 for Alert, etc.)
  - Inferred from `state.perfusion_status` and disease type

- **Supplemental oxygen flow rate** (L/min)
  - LOINC code 3151-8
  - Includes oxygen delivery device (nasal_cannula, simple_mask, non-rebreather)
  - Activated based on SpO2 < 92 or respiratory disease

These two additional Observation types are emitted alongside standard vitals when
applicable. NEWS2 score can be computed from any in-progress encounter's latest
observations.

---

## 6.8 Updated ADR list (Part 6 additions)

| ADR | Date | Title |
|---|---|---|
| AD-28 | 2026-04-06 | Diagnosis vs ground truth separation (ConditionEvent vs ClinicalDiagnosis) |
| AD-29 | 2026-04-06 | Diagnostic accuracy via likelihood ratios (Bayesian update) |
| AD-30 | 2026-04-08 | Code is the truth: CIF stores codes only, no display text |
| AD-31 | 2026-04-08 | FHIR Bulk Data Export NDJSON (replacing per-encounter Bundle) |
| AD-32 | 2026-04-08 | Snapshot date semantics with in-progress encounters |
| AD-33 | 2026-04-08 | English-first principle for code systems |
| AD-34 | 2026-04-08 | Hospital config-driven physical layout (departments, wards, beds) |
| AD-35 | 2026-04-08 | codes module separated from locale (international standards) |
| AD-36 | 2026-04-09 | FHIR Procedure structural fields via SNOMED CT (category, performer.function, bodySite, outcome, complication) |
| AD-37 | 2026-04-09 | Three explicit CLI stages: generate → narrate → export-fhir |
| AD-38 | 2026-04-09 | Clinical documents as FHIR DocumentReference (Tier A+B scope, LOINC-coded) |
| AD-39 | 2026-04-09 | LLM provider plugin registry + YAML-driven factory |
| AD-40 | 2026-04-09 | Prompt templates externalized as per-language YAML files |
| AD-41 | 2026-04-09 | SHA256 disk cache for LLM responses (reproducibility + cost control) |
| AD-42 | 2026-04-13 | Code-side unit conversion for Japanese locale (CRP mg/L → mg/dL in extractor/generator, not LLM prompt) |
| AD-43 | 2026-04-13 | Japanese narrative prompt quality rules (「医師」 suffix, 【】 section headers, no markdown) |
| AD-44 | 2026-04-15 | Enrichment is language-neutral (English structured data; LLM translates at output time) |
| AD-45 | 2026-04-15 | Occupation field on Patient/PersonRecord (12 categories; drives work-related injury incidence) |
| AD-46 | 2026-04-16 | Multilingual FHIR coding (Condition/Procedure emit dual coding: primary + interop language) |
| AD-47 | 2026-04-16 | FHIR Observation referenceRange + interpretation consistency (FHIR R5 Note 5) |
| AD-48 | 2026-04-16 | procedure_name removed from CIF (display resolved at output via code_lookup, AD-30 strict) |
| AD-49 | 2026-04-18 | Condition code.text with clinical abbreviations (_CONDITION_SHORT_NAME: COPD, CHF, CKD, DM, AF; coding[].display keeps official ICD name) |
| AD-50 | 2026-04-18 | Medication protocol prefix stripping (_strip_protocol_prefix removes DVT_prophylaxis:, antipyretic: from medicationCodeableConcept.text) |
| AD-51 | 2026-04-10 | YAML-driven medication_holds in disease protocols (replaces hardcoded disease_id lists in simulator) |
| AD-52 | 2026-04-10 | Country-specific recommended_population in hospital config (US: 40K, JP: 10K for 50-bed) |
| AD-53 | 2026-04-10 | Staff name resolution in narrative prompts (hospital.json roster → display names) |
| AD-54 | 2026-06-15 | Country-pluggable resident identifier & insurance numbering module (`modules/identity/`) |
| AD-55 | 2026-06-15 | EHR data enrichment split: near-essential data in Base (always-on, extends core), specialized/optional data in opt-in modules. **2026-06-25 PR3b-1 supplement** — third category formally added: **always-on Module = near-essential clinical cascade**. Modules where omission would produce a clinically incoherent state (e.g. `HAI present without antibiotic treatment`) violating CLAUDE.md clinical-coherence principle. Such modules register with `enabled=lambda c: True` and are no-ops only when the upstream `extensions[X]` slot they consume is empty. Examples: `device` (PR-A), `hai` (PR-B), `antibiotic` (PR3b-1). Distinguished from the **opt-in pattern** reserved for truly optional data (e.g. JP `identity` — only relevant if JP insurance numbering is desired) and from the original **Base** pattern that uses typed fields on the core record type. Selection rule when adding a new module: if its data would always be expected given upstream cascade, choose always-on; if it depends on a configuration flag at the simulator level (country, region, business arrangement), choose opt-in; if it extends a near-universally-emitted FHIR resource type, prefer Base typed-field. **2026-06-26 PR3b-2 = HAI culture S/I/R susceptibility chain**: second increment of the Phase 3b series. `modules/hai/_append_hai_culture()` extended with antibiogram-driven susceptibility sampling using `load_hai_antibiogram()` (new export in `modules/hai/__init__`). Data source: `reference_data/hai_antibiogram.yaml` (CDC NHSN AR 2018-2020), format `{hai_type: {organism_snomed: {antibiotic_key: [S, I, R]}}}`, import-time validated against `HAI_TYPES` + `hai_organisms.yaml` + `ANTIBIOTIC_LOINC_LOOKUP`. RNG uses existing HAI per-patient sub-rng (no new RNG stream; AD-16 preserved). Forward-compat: `MicrobiologyResult.hai_event_id` backref (links culture back to HAIEvent for PR3b-3 cross-reference) and `AntibioticRegimen.discontinuation_datetime` (reserve for PR3b-3 de-escalation) both added as typed fields. `ANTIBIOTIC_DRUGS` refactored tuple → `dict[str, dict[str, str]]` with `ANTIBIOTIC_LOINC_LOOKUP` as a new LOINC-lookup companion. LOINC orphan fix: `ciprofloxacin: "18879-7"` in `microbiology.yaml` was actually Cefepime → corrected to `18906-8` (NLM verified); `loinc.yaml` companion fix adds Ciprofloxacin `18879-7` with correct label + Cefepime `18906-8`. `run_forced` in `simulator/engine.py` now injects `scenario` into `config.forced_scenarios` when `force_hai_event is not None`, closing the silent-no-op gap discovered during Task 6. DQR: `docs/reviews/2026-06-26-phase-3b-2-hai-susceptibility-data-quality-review.md`. |
| AD-56 | 2026-06-15 | Extensibility foundation (Phase 0): FHIR resource-builder registry, simulator enricher registry, CIF extensions slot for modules, config module-enablement map. **PR1 2026-06-24 foundation refactor** added `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS` central registry for all enricher sub-seed offsets (7 modules: identity + microbiology grandfathered as decimals; immunization / code_status / family_history / care_level / nursing use 16-bit hex ASCII convention). Module-level assert catches accidental duplicate offsets at import. New enrichers register here and import via `ENRICHER_SEED_OFFSETS["my_module"]`. See CLAUDE.md "AD-55 enricher patterns" subsection + `docs/CONTRIBUTING-modules.md` for the contributor playbook. **PR2 2026-06-24 G2 SDOH integrity refactor** further established the "データ専用モジュール (variant)" pattern (`modules/sdoh/` — reference data + loader only, no enricher / no ENRICHER_SEED_OFFSETS entry — `clinosim/codes/` is the preexisting precedent); also split `_fhir_sdoh.py` into `_fhir_smoking_alcohol.py` + `_fhir_care_level.py` for single-responsibility separation, and promoted `_social_category` / `_value` helpers to `_fhir_common.py` for future SDOH builder reuse. **PR_docs 2026-06-24 comprehensive documentation update** added `MODULES.md` (top-level module map with 22-module inventory + dependency tree + typical call chains), `SCENARIO_FLAGS.md` (central reference for scenario + medication flags routed through `derive_lab_values`), `.github/TEMPLATE_MODULE_README.md` (standardized module README template), and "Consumers" sections to all 22 module READMEs for reverse-dependency visibility. Also extended `docs/CONTRIBUTING-modules.md` with PR verification guide (byte-diff vs 3-axis DQR decision matrix; the project's TRUE goal is FHIR R4 + JP Core compliance + 臨床整合性 + JP language quality, byte-diff is a refactor-PR mechanic only) and absorbed original G4 typed-field-vs-extensions decision tree. **PR3 2026-06-24 G3 Observation-family split** (final structural piece of the foundation refactor series) extracted the four unrelated builders inside `_fhir_observations.py` (727 lines / 31 KB) into three new per-theme files matching PR2's precedent: `_fhir_microbiology.py` (Specimen + Observation + DiagnosticReport), `_fhir_nursing.py` (NEWS2/GCS/Braden/Morse/Barthel/I&O survey Observations), `_fhir_immunization.py` (CVX Immunization). The residual `_fhir_observations.py` (~380 lines) is now the canonical numeric Observation builder (lab helper + vital builder). Pure mechanical refactor — all 33 NDJSON files (US 16 + JP 17) byte-identical to master for US p=2000 + JP p=2000, seed=42. Clears the runway for device + HAI feature builders to land in clean per-theme files (`_fhir_device.py` / `_fhir_hai.py`) without inheriting a multi-theme blob. **PR-A device module 2026-06-24** added Phase 1 of the device + HAI 4-PR series: `modules/device/` (AD-55 Module post_records enricher emitting CVC + indwelling catheter + mechanical ventilator on inpatient ICU encounters with state-based placement criteria), `_fhir_device.py` builder file (Device + DeviceUseStatement), `clinosim/types/device.py` (`DeviceRecord` dataclass under `extensions["device"]`), and `ENRICHER_SEED_OFFSETS["device"] = 0x4445`. SNOMED CT codes (`52124006` CVC / `23973005` Indwelling urinary catheter / `706172005` Ventilator) verified via tx.fhir.org `$expand` text-search; spec's tentative `467021000` replaced with the verified `23973005` (PR #80 LOINC `2B010` fabrication precedent applied). 3-axis DQR PASS at US p=10000 + JP p=5000: 353 + 20 devices respectively, all structural checks 100%, line-days within plausible bands. byte-diff supplement confirms zero regression on pre-existing NDJSON (AD-16 invariant). Phase 2 PR-B (`modules/hai`) will consume `extensions["device"]` for CLABSI/CAUTI/VAP onset sampling. **PR-B hai module 2026-06-24** added Phase 2 of the device + HAI 4-PR series: `modules/hai/` (AD-55 Module post_records enricher at order=80, consumes PR-A `extensions["device"]` line-days and samples CLABSI/CAUTI/VAP onsets via CDC NHSN baseline per-line-day risk rates 0.0010/0.0014/0.0015), `_fhir_hai.py` builder (HAI Condition only — cultures emit through the existing `_fhir_microbiology.py` builder via `record.microbiology.append(...)` with zero new wiring), `clinosim/types/hai.py` (`HAIEvent` dataclass under `extensions["hai"]`), and `ENRICHER_SEED_OFFSETS["hai"] = 0x4841`. Codes verified: 3 ICD-10-CM (T80.211A / T83.511A / J95.851) via NLM API; 3 WHO ICD-10 (T80.2 / T83.5 / J95.8); 3 HAI SNOMED (736442006 CLABSI / 68566005 UTI generic / 429271009 VAP — spec's tentative 433142000 + 425500004 not in SNOMED CT International, $expand verified replacements). 3-axis DQR PASS at US p=10000 + JP p=5000: US 4 HAI (3 CAUTI + 1 VAP) within Poisson 2σ of expected ~3.2; JP 0 HAI acceptable rare-event. First clean example of the cross-module enricher consumption pattern. **Phase 3a 2026-06-25 POST_ENCOUNTER stage** introduced a third enricher stage to `clinosim/simulator/enrichers.py` (alongside `POST_POPULATION` and `POST_RECORDS`): runs **per-encounter, immediately after the daily loop completes** but **inside** the encounter simulator. Migrated `device` (order=70) and `hai` (order=80) from `POST_RECORDS` to `POST_ENCOUNTER` because their sampling depends on full clinical course outcomes (`record.icu_transferred`, GCS, perfusion) that are only known after the daily loop — and their output (HAI events) needs to be visible to same-encounter post-processing. AD-55 Module classification now distinguishes **"encounter-bound Module"** (device/hai — POST_ENCOUNTER) from **"cross-record Module"** (nursing/immunization/family_history/code_status/care_level/sdoh — POST_RECORDS). Phase 3a then added `clinosim/modules/hai/lab_lift.apply_hai_lab_lift` which walks `extensions["hai"]` after the daily loop and adds a forward-delta lift to existing WBC + CRP `obs.value` using per-day state_history snapshots; this preserves the original noise + circadian while injecting the deterministic HAI inflammatory effect. byte-diff PASS: all 37 NDJSON files byte-identical at US p=2000 + JP p=2000 (HAI is Poisson rare-event at this size); the lift fires at p=10000 DQR with the expected clinical relative-delta. The forward-delta pattern is reusable for Phase 3b (antibiotic-day decay) and Phase 3c (Lactate / Plt / Temp / SBP sepsis cascade). |
| AD-57 | 2026-06-16 | Unify lab/vital generation across venues (inpatient/ED/outpatient) into one physiology-driven service (planned); replaces hardcoded ED/outpatient baselines. **Phase 3a 2026-06-25 forward-delta extension** — `modules/hai/lab_lift.apply_hai_lab_lift` adds the 4th example of the BNP-pattern surgical formula approach (after BNP wall-stress, D-dimer Phase 2a, PT_INR Phase 2b): instead of mutating `state` or re-running `derive_lab_values` for affected days, the post-encounter step computes `delta = derive(state_snap, lift>0) - derive(state_snap, lift=0)` on the per-day state_history snapshot and adds the delta to existing `obs.value`, preserving original noise + circadian. Future-proof for Phase 3b/c sepsis cascade (Lactate / Plt / Temp / SBP) and antibiotic-day decay using the same forward-delta pattern. |
| AD-58 | 2026-06-17 | **Output-format adapter registry.** CIF→format adapters self-register via `register_output_adapter` (`clinosim/modules/output/adapter.py`); the CLI is registry-driven (`available_formats()` / `get_adapter()`). Adding a format (SS-MIX, FHIR R3, HL7 v2) = add one `OutputAdapter` (`format_id`/`description`/`subdir`/`convert`) — no CLI or core edits. Built-in CSV/FHIR-R4 are thin wrappers (output unchanged). Adapters depend only on CIF + `clinosim.codes` + `clinosim.locale` (AD-17/AD-25). Evolution path: setuptools entry-point discovery for external plugin packages. |
| AD-59 | 2026-06-23 | **Per-order lab RNG isolation.** Every lab order — panel children and individual scalar orders alike — draws its specimen-rejection / hemolysis / technician-assignment / observation-noise RNG from a per-order sub-stream, not from the patient-scoped master RNG. Panel children use `panel_specimen_seed(parent_order_id)` (modeling "one specimen per parent order"); individual non-panel orders use `individual_lab_seed(order_id)` (one specimen per order). Both live in `clinosim/simulator/seeding.py`. The structural property this preserves: editing a `{test:"X"}` line in a disease/encounter YAML, or extending `derive_lab_values` to produce a new analyte, **cannot** shift unrelated patients' cohorts via the master stream — completing what AD-16 requires across all lab paths in `inpatient.py` Pass 1, `emergency.py`, and `outpatient.py`. Established progressively: PR #74 introduced `panel_specimen_seed` for panel children; PR #78 added `individual_lab_seed` for the remaining individual lab paths; the Coag panel PR (2026-06-24) is the first follow-up to add new analytes (APTT / PT / Fibrinogen) through this isolation — byte-diff vs master @ p=2000 seed=42 confirms zero shift in unrelated NDJSONs on both US and JP. Phase 2a (2026-06-24, D-dimer + `causes_vte`) is the second follow-up: byte-diff again confirms zero shift in the 9 unrelated NDJSONs, plus the same PR introduces a `scenario_flags_from_protocol(protocol)` helper that centralizes every `derive_lab_values` scenario-flag read so future flags reach all `derive_lab_values` call sites (inpatient Pass-1 + lagged + emergency + outpatient) through one helper edit. Phase 2b (2026-06-24, `on_warfarin` PT_INR therapeutic-band override) extends the flag-helper pattern with a sibling `medication_flags_from_context(patient, medication_orders, admission_date, current_day)` that detects chronic + in-hospital warfarin use without any RNG draw — preserving AD-59 isolation while adding medication → lab coupling as a reusable pattern (future: steroid → glucose, diuretic → K, antibiotic → CRP). Call sites merge both helper dicts via `{**scenario_flags, **medication_flags}` to keep flag additions one-edit-safe (J5-prevention extended). Byte-diff vs master @ p=2000 seed=42 confirms 8 of 9 NDJSONs sha256-identical; only Observation changes (same-count, PT_INR/PT value shift for warfarin-detected patients only). Integration guards: `tests/integration/test_individual_lab_isolation.py` (analyte) + `tests/integration/test_medication_flags_isolation.py` (medication flag). |
| AD-60 | 2026-06-25 | **clinosim audit framework.** Unified verification gate built as a `clinosim/audit/` package + CLI subcommand (`clinosim audit run/smoke/list`). Absorbs the previous 3-axis DQR scratchpad scripts and adds a fourth **silent_no_op** axis (canonical-constants cross-check + lift-firing proof) specifically designed to catch the PR-90 class of bug (case-mismatch silent no-op that left the entire Phase 3a HAI lift no-op'd in production while test green + byte-diff PASS + DQR cohort PASS still held). Architecture: `clinosim/audit/registry.py` (ModuleAuditSpec dataclass + register_audit_module + discover) + `clinosim/audit/engine.py` (AuditEngine orchestrates module × axis matrix) + `clinosim/audit/axes/` (4 axes: structural / clinical / jp_language / silent_no_op) + `clinosim/audit/reporter.py` (Markdown). Per-Module checks live in `clinosim/modules/<name>/audit.py` and side-effect-import register_audit_module(spec) at discovery; new Modules get all 4 axes for free by declaring `structural_obs_codes`, `clinical_acceptance`, `canonical_constants` + `yaml_keys_to_validate`, and `lift_firing_proof`. Phase 1 ships only `modules/hai/audit.py` (the absorption point for scratchpad/phase3a_lift_fired_proof.py). byte-diff vs master @ p=2000 seed=42 confirms 37/37 NDJSON byte-IDENTICAL — the audit framework is a pure read-only consumer of generated output, no simulation-path imports leaked, AD-16 preserved. First self-audit baseline report: `docs/reviews/2026-06-25-clinosim-audit-baseline.md`. byte-diff stays separate as a refactor-PR mechanic; the audit framework is for new-feature / realism PRs. See `docs/CONTRIBUTING-modules.md` "PR 検証ガイド" for the decision matrix. **2026-06-25 PR3b-1 = second per-Module plug-in**: `modules/antibiotic/audit.py` adds the second concrete plug-in after `hai`. Its `lift_firing_proof` drives the actual enricher path (`enrich_antibiotic`) against a synthetic CAUTI HAIEvent and asserts the closed-form Ceftriaxone q24h × 7d delta (1 regimen, 1 MedicationRequest, 7 MARs, first/last at exact expected datetimes). `clinosim audit list` now reports 2 modules with the same 4-axis matrix, confirming the framework's repeatability. **2026-06-26 PR3b-2 audit framework expansion**: `modules/antibiotic/audit.py` extended with (1) `_ABX_LOINCS` frozenset of 8 susceptibility LOINCs for structural axis Observation.code coverage; (2) `_NHSN_RESISTANCE_BANDS` metadata (CLABSI MRSA 40-55%, CAUTI ESBL 12-22%, VAP MRSA 30-45%) and `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE = 0.05` — wired to clinical axis active enforcement in PR3b-3 (2026-06-27, per-(hai_type, antibiotic) R-rate gate + per-HAI cohort empty-rate gate + per-hai_type narrow-rate gate, each `n<30 → WARN` for rare-event safety); **PR3b-3 D1+D2 (2026-06-29, PR #112) completed the chain** by adding `_organism_per_encounter` (per-(hai_type, organism, antibiotic) R-rate filter) and `_panel_eligible_organisms` (panel-eligible empty-rate denominator via `load_hai_antibiogram()` keys — auto-excludes E.faecalis / C.albicans), removing both `# TODO(post-PR3b-3)` markers; (3) `antibiogram_firing_proof` using PR-94 `equality_checks` format — drives `_append_hai_culture()` against a synthetic CLABSI S. aureus record and asserts Vancomycin susceptibility = S via `ANTIBIOTIC_LOINC_LOOKUP["vancomycin"]` (not hardcoded LOINC), closing the same silent-no-op class of bug for the susceptibility chain. |
| AD-62 | 2026-06-30 | **Imaging metadata-only chain with WADO-RS placeholder.** |
| AD-63 | 2026-07-01 | **Document narrative + structured event density foundation. Two new always-on Modules (allergy = POST_POPULATION order=10 / document = POST_ENCOUNTER order=95), 3 FHIR builders (DocumentReference / Composition / ClinicalImpression), 17-check lift_firing_proof. Closes Stage 1 document-density gap (DR 0→23,760, Comp 0→9,275, CI 0→23,760 US p=10k).** |

*Numbering gaps AD-1, AD-2, AD-12, AD-14, AD-15, AD-27 are reserved/withdrawn — never assigned to a shipped decision. AD-61/AD-64/AD-65/AD-66/AD-67/AD-68/AD-69 are documented in their own `### AD-6N` sections below rather than in this compact table. AD-67 (severity single source of truth), AD-68 (archetype_modifiers wiring), AD-69 (DiseaseProtocol extra="forbid") are the 2026-07-06 FHIR-completeness chain — see `docs/design-notes/2026-07-06-fix-point-registry.md`.*

---

## 6.9 Resident identifier & insurance numbering (AD-54)

### Problem

Layer-1 residents and Layer-2 patients carried no payer identity beyond an
internal MRN. Realistic EHR/claims data requires the patient's **insurance
enrollment** (被保険者番号 / member id, 保険者番号 / insurer number, 記号 / group
symbol, 枝番 / branch number) and — for Japan — the My-Number card / マイナ保険証
state. These are **country-specific**, **household-correlated**, and
**time-varying**, so they cannot be hardcoded.

### Key domain facts (drove the design)

- The 12-digit My Number (個人番号) is **not** stored in clinical EHRs by law
  (number use is limited to social-security/tax/disaster). Even when a マイナ保険証
  is presented, the provider receives the **insurance qualification**, never the
  raw 個人番号. → My Number is a Layer-1 simulation attribute only; clinical
  outputs (FHIR/CSV) must **not** emit it.
- The EHR/claims identifier is the **被保険者番号 + 保険者番号**, represented in FHIR
  as a **`Coverage`** resource (`subscriberId`, `payor` → insurer Organization),
  not as a `Patient.identifier` slice (consistent with JP Core's design).
  - **JP Core Coverage mapping (verified against jpfhir.jp/fhir/core):**
    記号/番号/枝番 → `JP_Coverage_InsuredPersonSymbol` / `…InsuredPersonNumber` /
    `…InsuredPersonSubNumber` extensions (valueString); `subscriberId` = `記号:番号`;
    `dependent` = 枝番; `identifier.value` = `保険者番号:記号:番号:枝番`
    (system `JP_Insurance_memberID`); `payor` → Organization with
    `jp-insurer-number-namingsystem` identifier (= 保険者番号). Mandatory: `status`,
    `beneficiary` (1..1), `payor` (1..*). Canonical URIs stored in
    `locale/jp/identity.yaml:fhir_coverage`.
  - **FHIR conformance details:** payor Organization carries `type` coding
    `organization-type#pay` and a real insurer **name** resolved from
    `locale/jp/identity.yaml:payers` (number → name at output; AD-30 — display text
    never stored in CIF). `Coverage.relationship` = `self` (subscriber) / `other`
    (被扶養者). `Coverage.type` is a text-only CodeableConcept (Japanese scheme label;
    no fabricated codes). Representative payers carry valid 検証番号 / check digits.
    US export emits **no** `Coverage` (no JP insurance leakage).
- 記号 sharing granularity differs by scheme: 社保 (employee) shares 記号 at the
  **employer (事業所)** level; 国保 shares at the **household** level; 後期高齢者
  (75+) is **per-individual**.
- "My-Number assignment" for a long-standing patient changes the **qualification
  verification method** (紙 → online) but **not** the 被保険者番号. The data that
  actually changes over time is the **payer** (転職/退職, and the deterministic
  **75-yr → 後期高齢者** transition). Hence insurance is modeled as a
  **period-bounded enrollment history**, and each encounter references the
  enrollment valid on its date (`Coverage.period`).

### Decision

A new leaf-ish module `clinosim/modules/identity/` owns numbering:

- `base.py` — `IdentityProvider` Protocol (country-pluggable seam; interface only)
- `registry.py` — `country → provider` resolution (mirrors `healthcare_system`)
- `generators.py` — check-digit number generators (国共通 pure functions)
- `providers/jp.py` — JP rules (employer-level 記号, 社保/国保/後期高齢, 枝番,
  card/保険証 dated flags, 75-yr transition)
- `providers/us.py` — thin (existing `_sample_insurance` behavior preserved)

Adding a country = new `providers/<cc>.py` + `locale/<cc>/identity.yaml`; no engine
changes (same philosophy as disease/encounter YAMLs).

**Determinism (AD-16):** numbering runs as a **separate pass after population
generation**, using a **dedicated sub-seed Generator** so the existing random
stream (and golden files) are untouched.

**Privacy chokepoint:** `national_id` may live in CIF/`PersonRecord` for future
マイナ-workflow extensibility, but output adapters carry a **sensitive-field
default-exclude** policy — FHIR/CSV never emit `national_id` unless explicitly
opted in.

### Defaults (locale/jp/identity.yaml — researched, `# TODO: verify` where provisional)

- マイナンバーカード保有率 (age-banded): 0–14 ≈0.70, 15–49 ≈0.77, 50s ≈0.82,
  60s ≈0.90, 70s ≈0.91 (peak), 80+ ≈0.72 (総務省/デジタル庁 2025)
- マイナ保険証 登録率: lower, same age shape (peak 60–70s)
- 世帯内相関は `household_icc` (Gaussian-copula preserving marginal card rates)
- **被用者保険 vs 国保 は occupation-driven**: the household's most-likely-employed
  working-age member becomes the 被保険者 (others 被扶養者) via
  `employee_probability_by_occupation`. Calibrated so the emergent <75 split is
  ≈ 73:27 (MHLW 医療保険 基礎資料), with `insurance_category_distribution` as fallback.
- **マイナ保険証 marginal**: registration is conditional on card holding at rate
  `ins_rate/card_rate`, so the population linked marginal = configured `ins_rate`.
- **`insurance_type` unified**: for JP, `PatientProfile.insurance_type` is set from the
  enrollment `category` (single source of truth → consistent CSV/Coverage; was empty before).

### Phasing

1. Module skeleton + JP numbering + snapshot single enrollment + Coverage + payor Org
2. Period-bounded enrollment history + 75-yr transition + `Coverage.period`
3. Employment transitions (light probabilistic) + card/保険証 dates + verification method
4. US compat tests + docs/ADR finalize

---

## 6.10 EHR data enrichment split — Base vs Module (AD-55)

### Principle

When adding EHR data classes (benchmarked against Synthea / USCDI v5 / MIMIC-IV):

- **Base** — data that a realistic EHR essentially *always* carries (and that is cheaply
  derivable from the existing physiology / clinical-course state). Generated on **every
  run** by extending the **existing core** (`types/`, `population`, `observation`,
  `simulator/*`, `output`). No new opt-in module, no flag.
- **Module** — specialized or optional data. Implemented as an **opt-in, pluggable
  module under `clinosim/modules/`** (same pattern as `identity`: own README +
  Dependencies, types in `types/`, FHIR built in the `output` module reading CIF,
  dedicated sub-seed, gated by a CLI flag / config). **One module per theme**
  (e.g. billing, devices, care-coordination) — never a catch-all "extras" module,
  consistent with the existing one-theme-per-module layout.

Avoid over-modularizing: small near-universal *attributes* (family history, code status,
extended SDOH) live in Base as patient/encounter fields, not as their own modules.

### Scope guard (carried from the enrichment research)

Imaging / modality-dependent data is **out of scope** (CT/MRI/X-ray/US, echo, ECG
tracings, endoscopy findings, spirometry, pathology). Lab/bedside/administrative data is
in scope (clinosim already derives labs from physiology, so the same applies to
microbiology, blood gas, cardiac markers, nursing flowsheets).

### Classification

| Tier | Data | Lives in |
|---|---|---|
| Base | Microbiology + susceptibility; lactate / ABG / cardiac markers; `DiagnosticReport` grouping; nursing flowsheets (I/O, NEWS2, pain, GCS, Braden); immunization history; family history; code status / advance directive; extended SDOH (incl. JP 要介護度) | core: `types`, `population`, `observation`, `simulator`, `output` |
| Module | Billing (`modules/billing/` — JP DPC / US Claim+EOB); Devices + HAI (`modules/device/` — CLABSI/CAUTI/VAP); Care coordination (`modules/care_coordination/` — CarePlan/CareTeam/Goal) | one opt-in module per theme |

See [`docs/roadmap.md`](docs/roadmap.md) — which points at the GitHub Issues board — for the phased implementation plan.

---

## 6.11 Extensibility foundation — Phase 0 (AD-56)

### Problem

Adding a new FHIR resource type or opt-in module currently requires editing several
central hot spots, so the AD-55 roadmap (8 Base items + 3 modules) would touch the same
monoliths repeatedly:

- `output/fhir_r4_adapter.py` `_build_bundle()` (~3,000-line file) — every new resource
  is hand-appended into one function, plus the dedup set.
- `simulator/engine.py` `run_beta()` — every post-population pass is inlined (e.g.
  `if config.jp_insurance_numbers: assign_identities(...)`), order-sensitive.
- `types/output.py` `CIFPatientRecord` — fixed dataclass; every new data class adds a field.
- `types/config.py` `SimulatorConfig` — one boolean per opt-in module.

### Decision — do these enabling refactors *before* the AD-55 enrichment work

1. **FHIR resource-builder registry.** A registry of builders `(record, ctx) -> list[resource]`;
   the core loop iterates and emits. Each builder declares its dedup behaviour
   (patient-level vs per-encounter). New resource = register a builder (co-located with its
   domain) — no edit to `_build_bundle`.
2. **Simulator enricher registry.** Post-population passes register with
   `name` / `order` / `enabled(config)` / `run(...)`; `run_beta` iterates in declared order.
   New module = register an enricher — no edit to `run_beta`. **Order is explicit and fixed
   to preserve determinism (AD-16).**
3. **CIF extensions slot.** Add `CIFPatientRecord.extensions: dict[str, Any]`. **Base** data
   keeps typed fields (Base *is* core); **Modules** write to `extensions[<module>]` and never
   edit the core type — module independence enforced at the type level (aligns with AD-55).
4. **Config module-enablement map.** `SimulatorConfig.modules: dict[str, bool]` +
   `module_enabled(name)` helper; `jp_insurance_numbers` kept as a back-compat alias.
   Per-module structured config (e.g. billing country options) lives in its own block.

Secondary: externalize the `observation` lab catalog (CV / precision / units) to YAML
(done alongside the microbiology Base item). CSV adapter registry is **deferred** (low
leverage — a new table is ~3 lines).

### Constraint

These refactor working code. Regression is gated by the existing golden / e2e suites and
determinism (AD-16): any change in resource emission order or RNG draw order must be proven
equivalent, not a true regression.

---

## 7. Clinical documents via FHIR DocumentReference

### Problem

Before Milestone 1 (early 2026-04-09), clinosim had no way to produce narrative clinical
documents as first-class FHIR resources. The legacy `narrative_generator` wrote loose
JSON files under `cif/narratives/<version>/patients/*.json`, but these never made it into
the FHIR Bulk Data export. Downstream consumers had patient, encounter, observation, and
procedure resources but no discharge summary, no operative note, no admission H&P — the
exact documents clinicians use to read and review a patient's story.

This gap was blocking:
- Readmission prediction and outcome research (discharge summary is the primary data source)
- Mortality review (death note is a legal document for every inpatient death)
- Surgical quality analysis (operative note is CMS §482.51-mandated)
- NLP/LLM training pipelines that expect clinical notes as DocumentReference resources

### Decision (AD-36, AD-37, AD-38)

**AD-36 — FHIR Procedure gets structural fields via SNOMED CT.**
Every `Procedure.ndjson` entry now includes:
- `category` — SNOMED 387713003 (surgical) / 103693007 (diagnostic) / 277132007 (therapeutic)
- `performer[].function` — SNOMED 304292004 (surgeon) / 158967008 (anaesthetist)
- `recorder` — Practitioner reference (defaults to surgeon)
- `reasonReference` — link to the encounter's primary Condition
- `bodySite` — SNOMED anatomy code
- `location` — Operating room Location reference (surgeries only)
- `outcome` — SNOMED 385669000 (successful) / 385670004 (partial) / 385671000 (unsuccessful)
- `complication` — SNOMED codes mapped from `ProcedureRecord.intraop_complications`

`clinosim/codes/data/snomed-ct.yaml` contains the minimal SNOMED subset required for
these fields, following the English-first principle (AD-33).

**AD-37 — Three explicit CLI stages: `generate` → `narrate` → `export-fhir`.**
Stage 1 (`generate`) produces the structural CIF. Stage 2 (`narrate`) generates clinical
documents from an existing CIF and writes them to `cif/narratives/<version>/documents/`.
Stage 3 (`export-fhir`) reads the CIF (and optionally a narrative version) and emits the
FHIR NDJSON files, including `DocumentReference.ndjson` when a narrative version is
provided.

Rationale:
- **Reproducibility (AD-16)** — Stage 1 is deterministic from seed. Stage 2 has
  reproducibility via prompt cache (AD-41). Stage 3 is a pure function of CIF.
- **Cost isolation** — Stage 2 is the only stage that may call a paid LLM API. On a
  host without network access to the LLM (e.g. a laptop that cannot reach Bedrock), the
  CIF directory can be shipped to an EC2 instance for Stage 2 only, then pulled back for
  Stage 3.
- **Experimentation** — multiple narrative versions from the same structural CIF can
  coexist and be compared (template vs Ollama vs Bedrock, English vs Japanese, prompt
  version 1 vs 2).
- **CIF stays the single source of truth (AD-17, AD-30)** — structural/ is immutable,
  narratives/ is a replaceable layer.

**AD-38 — Clinical documents as FHIR DocumentReference (Tier A+B scope).**
clinosim produces these documents out of the box:

| Tier | Document | LOINC | Per-encounter count | Justification |
|---|---|---|---|---|
| A | Discharge Summary | 18842-5 | 1 per inpatient | CMS §482.24 mandated for every discharge |
| A | Death Note | 69730-0 | 1 per death | Legal document; M&M review |
| A | Operative Note | 11504-8 | 1 per surgical procedure | CMS §482.51 mandated |
| B | Admission H&P | 34117-2 | 1 per inpatient | Standard US admission documentation |
| B | Procedure Note | 28570-0 | 0..N per inpatient | Only for invasive bedside procedures with clinical significance |

Procedure Note scope is restricted to **eight invasive bedside procedures** that require
a formal note: `central_line`, `lumbar_puncture`, `thoracentesis`, `paracentesis`,
`chest_tube`, `intubation`, `bronchoscopy`, `cardioversion`. Lower-complexity bedside
procedures (urinary catheter, NG tube, echocardiography, blood transfusion, dialysis,
arterial line, wound debridement) are documented in nursing or ancillary records and do
not produce a separate DocumentReference.

Progress Note (LOINC 11506-3) is **reserved for a future Tier C scope** because real-world
progress notes are ~80% redundant with structured vitals/labs/MAR data and generating them
at every hospital day would inflate token cost by an order of magnitude for minimal
incremental research value.

### Storage format: narrative CIF

A new type `ClinicalDocument` (in `clinosim/types/clinical.py`) represents one clinical
document. It is written as one JSON file per document under:

```
cif/narratives/<version_id>/documents/<encounter_id>/<task_type>[_suffix].json
```

Each file contains:
- **Identity** — document_id, task_type, LOINC code
- **References** — patient_id, encounter_id, author_practitioner_id, related_procedure_id
- **Timing** — authored_datetime, period_start, period_end
- **Content** — language, content_type, text
- **Provenance** — text_source (llm/template/cache/none), llm_model, llm_provider,
  input/output tokens, prompt_version, cache_hit, generated_at, fallback_reason

The document_generator extracts a deterministic list of facts (via
`hospital_course_extractor`) for each encounter and passes them as `${variables}` to the
LLM prompt. This keeps the LLM honest: it narrates facts rather than inventing them.

### FHIR DocumentReference mapping

```
DocumentReference.id          = <document_id>
  .status                     = "current"
  .docStatus                  = "final" (or "preliminary" for template fallback)
  .type.coding                = LOINC code + display (resolved via clinosim.codes)
  .category                   = us-core-documentreference-category: clinical-note
  .subject                    = Patient/<patient_id>
  .date                       = authored_datetime
  .author                     = Practitioner/<author_practitioner_id>
  .content[0].attachment
      .contentType            = text/plain; charset=utf-8
      .language               = en | ja
      .data                   = base64(text)
      .size                   = byte length
      .hash                   = base64(sha1(text))
  .context.encounter          = Encounter/<encounter_id>
  .context.period             = { start, end }
  .context.related            = Procedure/<related_procedure_id>  (operative/procedure)
```

Empty documents (Stage 1 stubs with no Stage 2 text) are **not emitted** — a
DocumentReference with empty attachment data is useless to downstream consumers and
would violate the FHIR profile implied by attaching a `clinical-note` category.

---

## 8. LLM service architecture: pluggable providers + YAML prompts

### Problem

The Milestone 0 `llm_service` supported only local Ollama and had all prompts hardcoded
in `engine._build_prompt()`. Adding a new provider required editing `engine.py`, adding
a new language required editing Python code, and adding a new document type required
both. Bedrock was not implemented at all. There was no response cache, so re-running
Stage 2 always re-invoked the LLM.

### Decision (AD-39, AD-40, AD-41)

**AD-39 — LLM provider plugin registry.**
Providers live in `clinosim/modules/llm_service/providers/` as a subpackage. Every
provider implements the `LLMProvider` Protocol (structural typing, no inheritance):

```python
class LLMProvider(Protocol):
    def complete(self, prompt, model, max_tokens, system_prompt,
                 temperature=0.4, stop_sequences=None) -> ProviderResponse: ...
    def health_check(self) -> bool: ...
```

A registry in `providers/__init__.py` maps provider keys (`ollama`, `bedrock`, `mock`,
`local`) to builder callables. Third-party code can extend the registry via
`register_provider(name, builder)` without touching clinosim source.

A new `factory.build_from_config_file(path)` reads `llm_service.yaml`, builds the
appropriate providers for the `judgment:` and `narrative:` sections, and returns a fully
wired `LLMService`. The Bedrock provider lazy-imports `boto3`, so users who never touch
Bedrock do not need to install it.

**AD-40 — Prompt templates as per-language YAML files.**
Prompts live under `clinosim/modules/llm_service/prompts/<language>/<task_type>.yaml`:

```yaml
task_type: discharge_summary
version: 1
max_tokens: 2000
temperature: 0.4
system: |
  You are an attending physician writing a comprehensive discharge summary ...
user_template: |
  Patient: ${age}yo ${sex}
  Admission date: ${admission_date}
  ...
```

`PromptRegistry.get(task_type, language)` loads and caches specs lazily. Rendering uses
Python's standard-library `string.Template` (zero external dependencies) with
`substitute()` on the user template (raises on missing keys — fail loud) and
`safe_substitute()` on the system prompt (natural-language content may contain
accidental `${...}` sequences).

Language fallback mirrors the codes module behavior: if `ja/<task>.yaml` is missing, the
registry falls back to `en/<task>.yaml` and logs via the PromptSpec's `language` field.

Rationale:
- **Clinician-editable** — non-programmers can improve prompt quality without touching
  Python code.
- **Language addition is a folder, not a PR review** — adding German means creating
  `prompts/de/*.yaml`, no engine changes.
- **Versioning + A/B testing** — the `version:` field is recorded on each generated
  document, enabling reproducibility and controlled rollouts.
- **JUDGMENT English-only invariant (AD-13)** is enforced at the yaml-tree level: only
  put English prompts under judgment tasks.

**AD-41 — SHA256 disk cache for LLM responses.**
`PromptCache` in `clinosim/modules/llm_service/cache.py` stores one JSON file per cached
response, keyed by `SHA256(system || user || model)`. Entries are written by
`LLMService._llm_generate` after a successful provider call and read before every
provider call when the cache is enabled.

Rationale:
- **Reproducibility (AD-16)** — re-running Stage 2 with the same inputs and same seed
  produces byte-identical output.
- **Cost control** — Bedrock Claude Sonnet runs on 5,000-patient datasets cost on the
  order of $1–5 per run; cache hits make re-runs free.
- **Partial re-run recovery** — if Stage 2 is interrupted mid-run, resuming only
  re-invokes the LLM for documents that were not yet cached.

Cache location defaults to `<cif>/narratives/<version>/cache/` or an explicit
`cache.directory` in the YAML config. Cache is disabled for template and mock modes.

### Data model: LLMService.generate

`LLMService.generate(task_type, event, variables=None)` is the single entry point for
all modules. `variables` is the new parameter that routes to PromptRegistry; when None,
the legacy `_build_prompt` hardcoded path is used (kept for backward compatibility with
admission H&P / discharge summary template code).

The returned `LLMResponse` now carries:
- `source` — `llm` | `template` | `cache` | `none`
- `input_tokens` / `output_tokens`
- `prompt_version` — from the PromptSpec
- `cache_hit` — True when served from `PromptCache`
- `fallback_reason` — populated on template fallback with a short error tag
- `provider` — the configured provider key (e.g. `bedrock`) for provenance

All of these are recorded on the `ClinicalDocument.generation` block and propagate into
the narrative CIF manifest, enabling per-document cost analysis and audit.

---

