<!-- Extracted from `README.md` (Issue #568 PR A). Update the pointer in README when this file's heading changes. -->

# Output Formats

### CIF (Clinosim Intermediate Format)

```
output/cif/
├── metadata.json                             # Generation info, snapshot_date, etc.
├── hospital.json                             # Staff roster + hospital config
├── structural/                               # Stage 1 output (immutable)
│   └── patients/
│       └── ENC-POP-XXXXXX-NNNNNN.json        # One file per encounter
└── narratives/                               # Stage 2 output (re-runnable)
    ├── current_version.txt                   # Pointer to the latest version id
    ├── <version_id>/
    │   ├── manifest.json                     # LLM config, model, cost report, counts
    │   └── documents/
    │       └── ENC-POP-XXXXXX-NNNNNN/
    │           ├── admission_hp.json
    │           ├── discharge_summary.json
    │           ├── death_summary.json        # only if deceased
    │           ├── operative_note_001.json   # per surgery
    │           └── procedure_note_<type>.json
    └── <another_version_id>/                 # multiple versions coexist
        └── ...
```

- `structural/` is the **immutable intermediate format** of the simulation. All structural FHIR/CSV resources derive from this.
- `narratives/<version>/documents/` is the **narrative layer** — one JSON per clinical document, conforming to the `ClinicalDocument` type in `clinosim/types/clinical.py`. Each file contains the LOINC code, plain-text content, references, and provenance (LLM model, tokens, cache hit, prompt version, generated_at).
- Multiple narrative versions can coexist: e.g. `template_v1`, `ollama_en_v1`, `bedrock_sonnet_en_v1` — all generated from the same structural CIF.

### FHIR R4 — Bulk Data Export NDJSON Format

Compliant with [HL7 FHIR Bulk Data Access](https://hl7.org/fhir/uv/bulkdata/):

```
output/fhir_r4/
├── manifest.json                    # Bulk Data manifest (transactionTime, output[])
├── Patient.ndjson                   # 1 patient per line
├── Encounter.ndjson                 # 1 encounter per line
├── Observation.ndjson               # labs + vitals + AVPU + O2 + microbiology + nursing scores
│                                    #   (NEWS2/GCS/Braden/Morse) + social history (occupation,
│                                    #   smoking, alcohol, JP 要介護度) + code status (LOINC/SNOMED)
├── ServiceRequest.ndjson            # Lab orders (panel-aware: 1 SR per CBC/BMP/LFT/etc; stand-alone orders 1 SR each) [AD-61]
│                                    # + Imaging orders (1 SR per imaging Order, SNOMED 363679005 + v2-0074 RAD) [AD-62]
├── ImagingStudy.ndjson              # Radiology studies (urn:dicom:uid, DCM modality, multi-series) [AD-62]
├── Endpoint.ndjson                  # WADO-RS URL placeholder per ImagingStudy (future PACS / image-gen AI integration) [AD-62]
├── DiagnosticReport.ndjson          # Lab panel reports (CBC/BMP/LFT/Lipid/Coag/UA/ABG, LOINC) + microbiology culture reports (+ Specimen)
│                                    # + Radiology reports (findings + impression in text.div + conclusion) [AD-62]
├── Specimen.ndjson                  # Culture specimens (blood/urine/sputum/wound)
├── Condition.ndjson                 # Encounter dx + chronic conditions + HAI (CLABSI/CAUTI/VAP) (ICD-10-CM / ICD-10 / SNOMED dual)
├── FamilyMemberHistory.ndjson       # First-degree-relative disease history (v3-RoleCode + ICD)
├── Immunization.ndjson              # Adult vaccine history (CVX; US/JP schedules)
├── Device.ndjson                    # ICU device records (CVC / indwelling catheter / ventilator; SNOMED CT)
├── DeviceUseStatement.ndjson        # Device usage periods (placement → removal; per ICU inpatient encounter)
├── MedicationRequest.ndjson         # Prescriptions (RxNorm / YJ)
├── MedicationAdministration.ndjson  # MAR records
├── Procedure.ndjson                 # Surgery + bedside procedures (CPT / K-code + SNOMED CT metadata)
├── DocumentReference.ndjson         # Clinical documents (only when a narrative version is provided)
├── AllergyIntolerance.ndjson        # Patient-level (deduplicated)
├── Coverage.ndjson                  # Insurance enrollment (JP only; JP Core 被保険者番号/記号/番号/枝番)
├── Practitioner.ndjson              # Doctors, nurses, technicians
├── PractitionerRole.ndjson          # Specialty + organization + ward location
├── Organization.ndjson              # Hospital + departments + insurers (保険者, JP)
└── Location.ndjson                  # Wards + beds + operating rooms
```

Each line = 1 FHIR resource. `Resource.id` is unique across all resource types. Reference integrity is maintained.

`DocumentReference.ndjson` is emitted whenever `--narrative-version`
resolves to a version directory (default: `current`, backed by the
`current_version.txt` pointer that Stage 1's `TemplateNarrativePass`
maintains). Without any narrative version present the remaining
resource types are produced normally. `Coverage.ndjson` (+ insurer
`Organization`) is emitted only for JP with insurance enabled
(`--jp-insurance`, default on).

### Longitudinal service-line emit (v0.5 → v0.6.0)

Both service lines emit through the standard resource files above —
no new resource types were introduced; the service-line schema is
described in
[`oncology-obstetric-service-lines.md`](oncology-obstetric-service-lines.md).

- **Oncology** (10 sites: C15 / C16 / C18 / C22 / C25 / C34 / C50 /
  C61 / C67 / C71, including male breast at ~1 % of C50):
  - Cancer chronic marker → `Condition` (ICD-10).
  - `chemo_visit` LifeEvents (config: `locale/shared/chemo_regimens.yaml`
    — FOLFOX q14d, CarboPem q21d, Trastuzumab q3w, LHRH q28d) →
    outpatient `Encounter` + per-cycle `MedicationRequest` +
    `MedicationAdministration` per drug on the regimen.
  - Radiation therapy → `Procedure`.
  - Tumor-marker labs (CEA / CA19-9 / AFP / PIVKA-II / CA15-3 / PSA)
    → `Observation` (LOINC laboratory).
- **Obstetrics** (config: `locale/shared/perinatal.yaml`):
  - Z34 pregnancy chronic marker → per-mother delivery schedule.
  - Mother-side delivery `Encounter` (IMP admission, admit dx Z34,
    discharge dx Z37.0, delivery `Procedure` — JP K894 / US CPT
    59400).
  - Postpartum encounters × 2 at ~1 wk and ~4 wk with disease id
    `Z39` (config: `locale/shared/chronic_followup.yaml`).
  - Abortion outcome (age-gated 15-19 → 35-44) — outpatient
    day-surgery `Encounter` with O03.9 (spontaneous) or O04.5
    (induced). If fired, delivery + newborn chain are skipped.
  - Newborn `Patient` (id `<mother>-BABY`) generated per delivery,
    household + birthDate inherited, sex sampled via per-mother
    sub-RNG. Newborn `Encounter` links back via
    `admit_source = born` (new `AdmitSource.BORN` enum member) and
    `Encounter.partOf → Encounter/<mother-delivery-encounter>`, with
    discharge dx `Z38.0`.
  - Newborn perinatal `Condition`s: P59.9 jaundice ~20 %,
    P07.3 preterm ~7 % (→ conditional P22.0 RDS at ~35 %), L22
    diaper dermatitis ~30 %, L20.9 atopic dermatitis ~15 %.

### Included FHIR R4 Fields (key resources)

| Resource | Fields |
|---|---|
| Patient | identifier (MRN, type=MR), name (with kanji+kana extension for JP), gender, birthDate, address, telecom, maritalStatus, communication (BCP-47), contact (emergency) |
| Encounter | class, type (SNOMED), serviceType, priority, period, length, participant (ATND/ADM/DIS), diagnosis ref, hospitalization (admitSource, dischargeDisposition), location (bed → ward via partOf), serviceProvider (department Org) |
| Observation | code (LOINC), valueQuantity (UCUM units + system + code), referenceRange (low/high/text/source extension for JP Core), interpretation (N/H/L/HH/LL), encounter, performer |
| Condition | code (ICD-10-CM with display), category (encounter-diagnosis / problem-list-item), severity (SNOMED), stage (NYHA, CKD G, GOLD, etc.), clinicalStatus (active/resolved), onsetDateTime, recordedDate, encounter |
| MedicationRequest | medicationCodeableConcept (RxNorm), dosageInstruction (text + doseAndRate + timing repeat + route SNOMED), encounter, requester, reasonReference |
| MedicationAdministration | dosage (dose SimpleQuantity + route + rateQuantity for continuous), context, performer, reasonReference |
| Procedure | code (CPT / K-code), category (SNOMED: surgical/diagnostic/therapeutic), encounter, performedPeriod, performer[] with function (surgeon/anaesthetist), recorder, reasonReference, bodySite (SNOMED), location (operating room), outcome (SNOMED), complication (SNOMED) |
| DocumentReference | type (LOINC: 18842-5 / 69730-0 / 11504-8 / 34117-2 / 28570-0), category (clinical-note), subject, date, author, content.attachment (base64 text/plain, size, sha1 hash), context (encounter period, related Procedure) |
| Practitioner | name (with prefix), gender, telecom, qualification |
| PractitionerRole | practitioner, organization (dept), location (ward), specialty (SNOMED) |
| Location | physicalType (wa=ward, bd=bed, area, ro=operating room), partOf (bed→ward), managingOrganization |
| Organization | hospital-main + dept-{specialty} (partOf hierarchy) |

### CSV

```
output/csv/
├── patients.csv
├── encounters.csv
├── conditions.csv
├── lab_results.csv
├── vital_signs.csv
├── orders.csv
├── medication_administrations.csv
├── procedures.csv
└── ...
```

---
