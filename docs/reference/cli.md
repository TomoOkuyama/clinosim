<!-- Extracted from `README.md` (Issue #568 PR A). Update the pointer in README when this file's heading changes. -->

# CLI Reference

clinosim is organized as three independent stages. `clinosim simulate` runs Stage 1; Stages 2 and 3 can be composed with it via `--narrative` and `--format fhir`, or run separately for reproducibility, remote execution (e.g. Bedrock on EC2), or iterative narrative experiments. `clinosim generate` remains as a deprecated alias for `simulate`.

```
┌────────────────┐  ┌────────────────┐  ┌──────────────────┐
│ simulate       │→ │ narrate        │→ │ export-fhir      │
│ (Stage 1)      │  │ (Stage 2)      │  │ (Stage 3)        │
│ structured CIF │  │ narrative CIF  │  │ FHIR R4 NDJSON   │
└────────────────┘  └────────────────┘  └──────────────────┘
```

### `clinosim simulate` — Stage 1 (structural simulation)

Population-driven simulation. Produces the structural CIF and optionally runs Stage 2/3 in one command.

| Option | Default | Description |
|---|---|---|
| `-o, --output DIR` | `./output` | Output directory |
| `-p, --population N` | hospital config's `recommended_population` | Catchment population |
| `--country CODE` | `US` | `US` or `JP` |
| `--start YYYY-MM-DD` | `--end` minus 1 year | Simulation start date |
| `--end YYYY-MM-DD` | today | Simulation end date = snapshot date |
| `--hospital-config PATH` | `clinosim/config/hospital_operations.yaml` (50-bed) | Hospital config YAML |
| `--format ...` | `cif fhir` | `cif`, `csv`, `fhir` |
| `-s, --seed N` | `42` | Random seed |
| `--narrative` | off | Run Stage 2 (clinical documents) after Stage 1 |
| `--llm-config PATH` | (unset) | LLM service YAML used when `--narrative` is set |
| `--narrative-version ID` | auto | Narrative version id used when exporting FHIR |
| `--narrative-model NAME` | `qwen:7b` | Legacy Ollama model name (ignored if `--llm-config` is set) |

### `clinosim narrate` — Stage 2 (clinical documents)

> **Note**: template-mode DocumentReferences are also emitted automatically
> during Stage 1 by the `document_enricher` module, so `clinosim simulate
> --format fhir-r4` produces a valid FHIR bundle with `docStatus="preliminary"`
> documents even without a separate `narrate` step. Running `narrate` afterwards
> upgrades those to `docStatus="final"` with LLM-generated text (or leaves them
> as `preliminary` in template mode).

Reads an existing CIF directory and generates clinical documents via the LLM service. Writes a new narrative version to `<cif>/narratives/<version_id>/`.

| Option | Default | Description |
|---|---|---|
| `--cif-dir DIR` | **required** | Path to an existing CIF directory |
| `--llm-config PATH` | (template mode) | LLM service YAML (`clinosim/config/llm_service*.yaml`) |
| `--version-id ID` | auto-timestamped | Narrative version directory name |
| `--language LANG` | `en` | Document language (`en` \| `ja`) |
| `--tasks LIST` | all Tier A+B | Comma-separated subset: `discharge_summary,death_summary,operative_note,admission_hp,procedure_note` |

**Tier A+B document scope** (default):

| Document | LOINC | Generated when | Frequency |
|---|---|---|---|
| Discharge Summary | `18842-5` | Every inpatient discharge | 1 per encounter |
| Death Note | `69730-0` | Deceased inpatient | 1 per death |
| Operative Note | `11504-8` | Surgical procedure (SNOMED 387713003) | 1 per surgery |
| Admission H&P | `34117-2` | Every inpatient admission | 1 per encounter |
| Procedure Note | `28570-0` | Invasive bedside (central line, LP, thoracentesis, paracentesis, chest tube, intubation, bronchoscopy, cardioversion) | 1 per procedure |

See [../clinical_documents.md](../clinical_documents.md) for details.

### `clinosim export-fhir` — Stage 3 (FHIR R4 NDJSON)

Reads an existing CIF directory and writes FHIR R4 Bulk Data NDJSON files.
DocumentReference resources are emitted from `record.documents` (Stage 1 enricher output).

| Option | Default | Description |
|---|---|---|
| `--cif-dir DIR` | **required** | Path to an existing CIF directory |
| `-o, --output DIR` | `<cif>/../fhir_r4` | Output directory |
| `--country CODE` | `US` | Country code (display language) |

### `clinosim test-disease DISEASE_ID`

Generate forced scenario for a specific disease (debugging / golden tests).

```bash
clinosim test-disease heart_failure_exacerbation \
  --severity severe --archetype treatment_resistant -n 3
```

### `clinosim test-encounter CONDITION_ID`

ED / outpatient encounter unit test.

```bash
clinosim test-encounter migraine --age 35 --sex F
```

### `clinosim validate`

Quality check generated data against published benchmarks.

### `clinosim list-diseases`

Show all 32 diseases (`clinosim/modules/disease/reference_data/*.yaml`) + 46 encounter conditions (`clinosim/modules/encounter/reference_data/*.yaml`).

### Typical workflows

**Local template-only run (no LLM, deterministic):**
```bash
clinosim simulate -o ./output -p 5000 --country US
clinosim narrate --cif-dir ./output/cif --version-id template_v1
clinosim export-fhir --cif-dir ./output/cif --narrative-version template_v1
```

**Local LLM (Ollama):**
```bash
clinosim simulate -o ./output -p 5000 --country US
clinosim narrate --cif-dir ./output/cif \
    --llm-config clinosim/config/llm_service.yaml \
    --version-id ollama_en_v1
clinosim export-fhir --cif-dir ./output/cif --narrative-version ollama_en_v1
```

**Split: local Stage 1, EC2 Stage 2 (Bedrock), back to local Stage 3:**
```bash
# On local machine
clinosim simulate -o ./output -p 5000 --country US --format cif
scp -r ./output/cif ec2-user@ec2-host:/home/ec2-user/

# On EC2 (IAM role with bedrock:Converse)
clinosim narrate --cif-dir /home/ec2-user/cif \
    --llm-config clinosim/config/llm_service.bedrock.yaml \
    --version-id bedrock_sonnet_en_v1

# Pull result back, then
clinosim export-fhir --cif-dir ./output/cif \
    --narrative-version bedrock_sonnet_en_v1
```

See [../bedrock_setup.md](../bedrock_setup.md) for the EC2 + Bedrock setup guide.

---
