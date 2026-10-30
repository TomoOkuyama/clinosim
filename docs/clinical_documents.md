# Clinical documents in clinosim

clinosim simulates **clinically structured narrative documents** as part of the
simulation pipeline. Every document is written twice: once as a CIF intermediate
JSON (the *narrative CIF*) and once as a FHIR R4 `DocumentReference` resource in
the Bulk Data NDJSON export.

This guide covers:

- [Emitted document types and when each is generated](#document-scope)
- [LOINC mapping and FHIR fields](#fhir-mapping)
- [End-to-end workflow](#workflow)
- [Writing and editing prompt templates](#prompts)
- [Provenance and reproducibility](#provenance)
- [Adding a new document type](#adding-a-new-document-type)
- [Adding a new language](#adding-a-new-language)

---

## Document scope

clinosim's per-country document registry
(`clinosim/modules/document/narrative/registry.py::specs_for_country()`)
wires **13 document types for US** and **18 for JP** end-to-end
through a country/encounter-type gate → per-doc builder → bundled
`narrative_seed_bundle.yaml` LLM strategy → DocumentReference emit
path. The 5 additional JP-only types (admission_care_plan,
nutrition_care_plan, rehabilitation_plan, referral_note,
health_checkup_report) reflect JP-CLINS eReferral / clinical-workflow
requirements. Progress Note (LOINC 11506-3) — previously deferred as
Tier C in earlier releases — is emitted end-to-end as of v0.6.x.

### Physician inpatient documentation (US + JP)

| Document | LOINC | Generated when | Per-encounter count |
|---|---|---|---|
| Admission H&P | `34117-2` | Every inpatient / ICU / rehab-inpatient encounter | 1 |
| Progress Note | `11506-3` | Daily during inpatient stay | 1 per hospital day |
| Discharge Summary | `18842-5` | Every finished inpatient encounter (non-deceased) | 1 |
| Operative Note | `11504-8` | `ProcedureRecord.category_code = 387713003` (surgical) | 1 per surgery |
| Procedure Note | `28570-0` | Invasive bedside procedure from a fixed allowlist | 0..N |
| Death Discharge Summary | `18842-5` (specialized) | `record.deceased = true` — replaces the standard Discharge Summary on deceased encounters | 1 |
| Death Certificate | `64297-5` | `record.deceased = true` — 医師法第 20 条 mandate | 1 |

### Nursing documentation (US + JP)

| Document | LOINC | Generated when | Per-encounter count |
|---|---|---|---|
| Admission Nursing Assessment | `78390-2` | Every inpatient admission | 1 |
| Nursing Shift Note | `34746-8` | Every nursing shift (day / evening / night) | 3 per hospital day |
| Nursing Discharge Summary | `34745-0` | Every finished inpatient encounter | 1 |

### Outpatient / Emergency (US + JP)

| Document | LOINC | Generated when | Per-encounter count |
|---|---|---|---|
| Outpatient SOAP | `34131-3` | Every outpatient encounter | 1 |
| ED Note | `34878-9` | Every emergency encounter | 1 |
| ED Triage Note | `54094-8` | Every emergency encounter | 1 |

### JP-only (JP-CLINS / clinical workflow)

| Document | LOINC | Generated when | Per-encounter count |
|---|---|---|---|
| Admission Care Plan | `18776-5` | Every JP inpatient admission | 1 |
| Nutrition Care Plan | `80791-7` | JP inpatient admission with LOS > 7 days | 1 |
| Rehabilitation Plan | `34823-5` | JP inpatient with rehab sessions ordered | 1 |
| Referral Note | `57133-1` | Deterministic 20% subset of JP discharge encounters (JP-CLINS eReferral) | 1 |
| Health Checkup Report | `53576-5` | Every JP `checkup` encounter | 1 |

### Procedure Note allowlist

Only **eight invasive bedside procedures** produce a formal Procedure Note,
matching real-world documentation practice:

| `procedure_type` | Rationale |
|---|---|
| `central_line` | Insertion site, vessel, confirmation required |
| `lumbar_puncture` | Opening pressure, CSF appearance, tube collection |
| `thoracentesis` | Fluid volume and character, post-procedure imaging |
| `paracentesis` | Fluid volume and character, indication |
| `chest_tube` | Insertion site, initial drainage, confirmation |
| `intubation` | Cormack-Lehane grade, tube size, ETCO₂ confirmation |
| `bronchoscopy` | Findings, BAL results, biopsy specimens |
| `cardioversion` | Energy delivered, success, rhythm before/after |

Procedures not on this list (urinary catheter, NG tube, echocardiography,
blood transfusion, dialysis, arterial line, wound debridement) are folded into
nursing records or ancillary reports and do not produce a separate
DocumentReference.

### What is **not** generated (by design)

| Document | LOINC | Why excluded |
|---|---|---|
| Consultation Note | `11488-4` | Requires consult workflow (not modeled). |
| Radiology Report | `11526-1` | Radiology is represented as Procedure + ServiceRequest + `DiagnosticReport`, not a free-text report document. |
| Pathology Report | `11526-1` (pathology variant) | No specimen pathology modeling. |

---

## FHIR mapping

Each `ClinicalDocument` in the narrative CIF becomes one FHIR R4
`DocumentReference` resource:

```
DocumentReference.id          = <document_id>
  .status                     = "current"
  .docStatus                  = "final" | "preliminary"
  .type.coding[0]             = { system: http://loinc.org, code: <loinc>, display: <lookup> }
  .category[0].coding[0]      = { system: us-core-documentreference-category, code: clinical-note }
  .subject                    = Patient/<patient_id>
  .date                       = <authored_datetime>
  .author[0]                  = Practitioner/<author_practitioner_id>
  .content[0].attachment
      .contentType            = "text/plain; charset=utf-8"
      .language               = "en" | "ja"
      .data                   = base64(text)
      .title                  = <loinc display>
      .size                   = byte length of text
      .hash                   = base64(sha1(text))
  .context.encounter[0]       = Encounter/<encounter_id>
  .context.period             = { start: <period_start>, end: <period_end> }
  .context.related[0]         = Procedure/<related_procedure_id>  (op/procedure notes only)
```

**docStatus semantics:**
- `"final"` — text came from an LLM call (`text_source = "llm" | "cache"`)
- `"preliminary"` — text came from the deterministic fallback template
  (`text_source = "template"`). A downstream consumer that requires finalized
  documentation can filter these out.

**Empty stubs are not emitted.** If Stage 2 was never run, `narrate` was skipped,
or a document stub has no text, no DocumentReference is produced. This matches
FHIR R4 profile expectations (an attachment with empty `data` is semantically
useless).

**Reference integrity.** Every `subject`, `encounter`, `author`, and
`context.related[*]` reference resolves to a resource present in the same
Bulk Data export. The `export-fhir` Stage 3 does not emit a DocumentReference
pointing to a Patient or Encounter that would not appear in the corresponding
NDJSON files.

---

## Workflow

### Three stages

```
clinosim simulate   →   cif/structural/patients/*.json       (Stage 1)
clinosim narrate    →   cif/narratives/<ver>/documents/*.json (Stage 2)
clinosim export-fhir →  fhir_r4/*.ndjson (incl. DocumentReference.ndjson)  (Stage 3)
```

See the [CLI reference](reference/cli.md) for the full option list.

### Template mode (no LLM)

```bash
clinosim narrate --cif-dir ./output/cif --version-id template_v1
```

Template mode uses a deterministic Python fallback and does not call any LLM.
Useful for:
- CI pipelines where LLM calls are prohibited
- Reproducibility tests
- Smoke-testing the narrative CIF → FHIR DocumentReference path
- Establishing a baseline document count before an expensive LLM run

### Local Ollama mode

```bash
ollama pull llama3.1:8b
clinosim narrate --cif-dir ./output/cif \
    --provider ollama --llm-config clinosim/config/llm_service.yaml \
    --version-id ollama_en_v1
```

### AWS Bedrock (EC2)

See [bedrock_setup.md](bedrock_setup.md) for the full EC2 + IAM setup.

```bash
clinosim narrate --cif-dir ./cif \
    --provider bedrock --llm-config clinosim/config/llm_service.bedrock.yaml \
    --version-id bedrock_sonnet_en_v1
```

### Generating only a subset

```bash
# Only discharge, death and operative documents
# (values are registry type_key names)
clinosim narrate --cif-dir ./output/cif \
    --tasks discharge_summary,death_discharge_summary,death_certificate,operative_note
```

### Multiple narrative versions from the same structural CIF

```bash
clinosim narrate --cif-dir ./cif --version-id template_v1
clinosim narrate --cif-dir ./cif --version-id ollama_en_v1 --provider ollama --llm-config clinosim/config/llm_service.yaml
clinosim narrate --cif-dir ./cif --version-id bedrock_en_v1 --provider bedrock --llm-config clinosim/config/llm_service.bedrock.yaml

# Export FHIR with each version separately
clinosim export-fhir --cif-dir ./cif --narrative-version template_v1 -o ./fhir_template
clinosim export-fhir --cif-dir ./cif --narrative-version ollama_en_v1 -o ./fhir_ollama
clinosim export-fhir --cif-dir ./cif --narrative-version bedrock_en_v1 -o ./fhir_bedrock
```

The version-id string is chosen by the caller. In the published
GitHub Release tarballs (see `clinosim-vX.Y.Z-*-*-narrative.tar.gz`
assets), the shipped convention is:

- **template tarball**: `cif/narratives/template/`, `current_version.txt = "template"`.
- **llm-polished tarball**: `cif/narratives/{template,llm-polished}/`
  (both directories present), `current_version.txt = "llm-polished"`.

Local runs are free to use any label; only the release-asset
convention is fixed.

---

## Prompts

Prompt templates live under
`clinosim/modules/llm_service/prompts/<language>/<task_type>.yaml`.
Each language directory contains ~17 prompts covering the individual
narrative tasks plus the `narrative_seed_bundle.yaml` strategy prompt
that drives the multi-document bundle path used at runtime:

```
clinosim/modules/llm_service/prompts/
└── en/
    ├── narrative_seed_bundle.yaml      # bundle strategy (multi-doc call)
    ├── admission_hp.yaml
    ├── discharge_summary.yaml
    ├── operative_note.yaml
    ├── procedure_note.yaml
    ├── death_certificate_*.yaml
    ├── death_discharge_summary_*.yaml  # per-section prompts
    ├── death_summary.yaml
    ├── narrative_seed.yaml
    └── referral_note.yaml
```

Each file has this structure:

```yaml
task_type: discharge_summary
version: 1                # bumped when the template changes
max_tokens: 2000
temperature: 0.4
description: |            # optional human-readable purpose
  FHIR DocumentReference with LOINC 18842-5 (Discharge summary note).
  Required by CMS §482.24 for every inpatient admission.

system: |                 # system prompt (natural language, may contain ${...})
  You are an attending physician writing a comprehensive discharge summary ...

user_template: |          # user prompt with ${variable} placeholders
  Patient: ${age}yo ${sex}
  Admission date: ${admission_date}
  Discharge date: ${discharge_date}
  ...
```

### Variable rendering

- `system` is rendered with `string.Template.safe_substitute()` — unknown
  `${...}` sequences are left as-is to avoid breaking natural-language content.
- `user_template` is rendered with `string.Template.substitute()` — missing
  variables raise `KeyError`, failing loudly rather than shipping a malformed
  prompt.

### Variable formatting

The prompt registry normalizes variables before substitution:

| Python type | Renders as |
|---|---|
| `str` | As-is |
| `int`, `float` | `str(value)` |
| `None` | Empty string |
| `list[str]` (non-empty) | Newline-joined bullet list (`- item`) |
| `list[str]` (empty) | `(none)` |
| `list[dict]` | Recursively stringified |
| `dict` | `key: value` per line |

This means a discharge summary prompt can pass
`"discharge_medications": ["Amoxicillin 500mg PO BID x 7 days"]` and the
template will render it as a bullet list automatically.

### Available variables per task

Variable names are declared in the prompt yaml's `variables:` block
(`clinosim/modules/llm_service/prompts/<lang>/<task>.yaml`) and the
matching input builder in the narrative pipeline
(`clinosim/modules/document/narrative/` — the per-section builders
under `renderers/section_builders/` plus the composition dispatcher).
The complete lists per task (as of the current master; see each prompt
yaml for the live declaration):

**discharge_summary**:
`age, sex, admission_date, discharge_date, los_days, disposition,
attending_physician, chief_complaint, past_medical_history, admission_diagnosis,
discharge_diagnoses, hospital_course_bullets, procedures_performed,
discharge_medications`

**death_summary**:
`age, sex, admission_date, death_datetime, los_days, attending_physician,
admission_diagnosis, primary_diagnosis, past_medical_history,
hospital_course_bullets, terminal_findings, complications`

**operative_note**:
`surgery_date, procedure_name, procedure_code, preop_diagnosis,
postop_diagnosis, surgeon, assistants, anesthesiologist, anesthesia_type,
asa_class, duration_minutes, estimated_blood_loss_ml, body_site, approach,
implants_used, specimens_sent, intraop_complications, outcome`

**admission_hp**:
`age, sex, admission_datetime, admitting_physician, department,
chief_complaint, hpi_summary, past_medical_history, home_medications,
allergies, admission_vitals, initial_labs, admission_diagnosis`

**procedure_note**:
`procedure_date, procedure_name, procedure_code, operator, indication,
body_site, anesthesia_type, duration_minutes, findings, specimens_obtained,
complications, outcome`

### Editing prompts

When you improve a prompt template:

1. **Bump the `version:` field.** The version number is recorded on every
   generated document (`ClinicalDocument.prompt_version`) so you can audit
   which version produced each note.
2. **Do not rename variables** without updating the matching input
   builder in `clinosim/modules/document/narrative/` + the
   `variables:` block in the prompt yaml. The generator raises
   `KeyError` if a template references a variable the code does
   not provide.
3. **Test in template mode first** to verify rendering without spending LLM
   tokens:
   ```bash
   clinosim narrate --cif-dir ./output/cif --version-id prompt_v2_test
   ```

---

## Provenance

Every `ClinicalDocument` JSON file records full provenance:

```json
{
  "document_id": "doc-ENC-POP-000005-0001-discharge_summary",
  "task_type": "discharge_summary",
  "loinc_code": "18842-5",
  "patient_id": "POP-000005",
  "encounter_id": "ENC-POP-000005-0001",
  "author_practitioner_id": "DR-IM-003",
  "authored_datetime": "2026-03-15T14:30:00",
  "period_start": "2026-03-01T09:00:00",
  "period_end": "2026-03-15T14:30:00",
  "language": "en",
  "text": "DISCHARGE SUMMARY\n...",
  "text_source": "llm",
  "llm_model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
  "llm_provider": "bedrock",
  "llm_input_tokens": 1250,
  "llm_output_tokens": 480,
  "prompt_version": 1,
  "cache_hit": false,
  "generated_at": "2026-04-09T12:34:56",
  "fallback_reason": ""
}
```

- **`text_source`** is the definitive statement of how the text was produced:
  - `"llm"` — fresh LLM call
  - `"cache"` — served from SHA256 prompt cache (same model, system, and user prompt)
  - `"template"` — deterministic Python fallback (after LLM failure or in template mode)
  - `"none"` — LLMService was in `none` mode; the document has empty text
- **`cache_hit`** is redundant with `text_source = "cache"` but kept for easier
  aggregation in cost reports.
- **`fallback_reason`** is populated when the LLM call failed and the service
  fell back to the template. Format: `provider_error:<ExceptionType>: <message>`
  (truncated to 200 chars).

The narrative version's `manifest.json` aggregates these into:

```json
{
  "version_id": "bedrock_sonnet_en_v1",
  "generated_at": "2026-04-09T13:00:00",
  "language": "en",
  "llm_mode": "llm",
  "patient_count": 171,
  "document_counts_by_type": {
    "admission_hp": 171,
    "discharge_summary": 171,
    "operative_note": 11,
    "procedure_note": 19,
    "death_discharge_summary": 2
  },
  "total_documents": 374,
  "llm_cost_report": {
    "total_calls": 374,
    "total_input_tokens": 412389,
    "total_output_tokens": 58041,
    "fallback_count": 0,
    "cache_hit_count": 0,
    "cache_stats": {"hits": 0, "misses": 374, "writes": 374, "enabled": 1}
  }
}
```

---

## Adding a new document type

**Scope note:** if you are adding a document with high per-encounter
multiplicity (e.g. Consultation Note, additional per-shift notes),
confirm the scope decision first — such doc types can multiply the
per-encounter document count by 5–10× and materially inflate the
FHIR export.

1. **Pick a LOINC code** from the [Regenstrief LOINC browser](https://loinc.org/)
   and add it to `clinosim/codes/data/loinc.yaml` with at least the `en` field:
   ```yaml
   11488-4:
     en: Consultation note
     ja: 診療依頼書
   ```

2. **Add the task type to the enum** in
   `clinosim/modules/llm_service/engine.py` (`TASK_CATEGORY` and
   `DOCUMENT_LOINC` are built from the yaml files in step 3):
   ```python
   class LLMTaskType(StrEnum):
       ...
       CONSULTATION_NOTE = "consultation_note"  # LOINC 11488-4
   ```

3. **Register task_loincs.yaml + task_categories.yaml**
   (`clinosim/modules/llm_service/reference_data/`). The engine
   validates full coverage at import — a new `LLMTaskType` value
   with no row in `task_loincs.yaml` fails loud.

4. **Register the `DocumentTypeSpec`** in
   `clinosim/modules/document/reference_data/document_type_specs.yaml`:
   ```yaml
   consultation_note:
     loinc_code: "11488-4"
     format_type: free_text              # or `composition`
     countries_supported: [us, jp]
     encounter_types_supported: [outpatient]
     generation_frequency: per_encounter # or `admission_once` / `daily` / ...
     composition_sections:               # only when format_type: composition
       - reason_for_consult
       - findings
       - recommendation
     stage2_strategy: template_seed_bundle
     llm_enabled_sections: [recommendation]
   ```
   `format_type: composition` lands the doc on `Composition` with
   named `section[]` entries; `free_text` lands on
   `DocumentReference` with the full body in `content.attachment.data`.

5. **Create the English prompt YAML**
   `clinosim/modules/llm_service/prompts/en/consultation_note.yaml`
   following the template above. Declare every variable the prompt
   references in the yaml's `variables:` block.

6. **Implement the section builder(s)** under
   `clinosim/modules/document/narrative/renderers/section_builders/<section>.py`
   as free functions `build_<section>(generator, ctx)` returning the
   rendered section text. The post-C1a-s split places all per-section
   logic here; `template_generator.py` is a thin façade that re-exports
   the builders. For `format_type: free_text` tasks, implement a
   single body builder; for `composition`, one builder per entry in
   `composition_sections`. Wire the dispatcher in
   `clinosim/modules/document/narrative/renderers/composition_sections.py`.

7. **Add unit tests** under `tests/unit/modules/document/narrative/` (per-section
   builder tests) and `tests/unit/test_clinical_documents.py`
   (end-to-end emit).

8. **Update this doc** (`docs/clinical_documents.md`), `README.md`,
   and the matching `.ja.md` siblings.

---

## Adding a new language

1. Ensure every LOINC code used by clinical documents has a display translation
   in the new language inside `clinosim/codes/data/loinc.yaml`:
   ```yaml
   18842-5:
     en: Discharge summary note
     ja: 退院時サマリー
     de: Arztbrief / Entlassungsbrief
   ```

2. Create the per-task prompt YAML files under
   `clinosim/modules/llm_service/prompts/<lang>/`. A clinician who is a native
   speaker of the target language should review each template.

3. Test the new prompts with `clinosim narrate --cif-dir <cif> --country <XX>`.
   `narrate` has no `--language` flag: the document language follows
   the country (`--country`, auto-detected from `cif/metadata.json`).

4. The prompt registry automatically falls back to English if a specific prompt
   file is missing, so partial translations are safe.

---

## See also

- [README.md](../README.md) — main user guide
- [bedrock_setup.md](bedrock_setup.md) — EC2 + AWS Bedrock deployment
- [../DESIGN.md](../DESIGN.md) Section 7 — architecture decisions for clinical documents (AD-36 to AD-41)
- `clinosim/modules/llm_service/README.md` — LLM service module reference
- `clinosim/modules/output/README.md` — output adapter module reference
