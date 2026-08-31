<!-- Extracted from `README.md` (Issue #568 PR A). Update the pointer in README when this file's heading changes. -->

# CLI Reference

`clinosim` is organized as three independent stages plus a set of
debug / audit / dataset / eval / benchmark subcommands. Stage 1
(`simulate`) generates the structural CIF; Stages 2 (`narrate`) and
3 (`export-fhir`) run on the CIF and can be composed with Stage 1 or
run separately for reproducibility, remote LLM execution, or
iterative narrative experiments. `clinosim generate` remains as a
deprecated alias for `simulate`.

```
┌────────────────┐  ┌────────────────┐  ┌──────────────────┐
│ simulate       │→ │ narrate        │→ │ export-fhir      │
│ (Stage 1)      │  │ (Stage 2)      │  │ (Stage 3)        │
│ structured CIF │  │ narrative CIF  │  │ FHIR R4 NDJSON   │
└────────────────┘  └────────────────┘  └──────────────────┘
```

The full authoritative source is
[`clinosim/simulator/cli.py`](https://github.com/TomoOkuyama/clinosim/blob/master/clinosim/simulator/cli.py);
run `clinosim <subcommand> --help` for the up-to-date option list.

## `clinosim simulate` — Stage 1 (structural simulation)

Population-driven simulation. Produces the structural CIF; the
template Stage 2 narrative pass runs automatically at the end so a
plain `clinosim simulate --format fhir-r4` produces an emit-ready
FHIR bundle. `clinosim generate` accepts the same options.

| Option | Default | Description |
|---|---|---|
| `-o, --output DIR` | `./output` | Output directory |
| `-p, --population N` | hospital config's `recommended_population` | Catchment population |
| `--country CODE` | `US` | `US` or `JP` |
| `--start YYYY-MM-DD` | `--end` minus 1 year | Simulation start date |
| `--end YYYY-MM-DD` | today | Simulation end date = snapshot date |
| `--hospital-config PATH` | `clinosim/config/hospital_operations.yaml` (50-bed) | Hospital config YAML |
| `--format ...` | `cif` | One or more of `cif`, `csv`, `fhir-r4` (alias: `fhir`). Add more by registering an `OutputAdapter` (AD-58). |
| `-s, --seed N` | `42` | Random seed |
| `--jp-insurance / --no-jp-insurance` | on (JP only) | Include Japanese insurance enrollment / 被保険者番号 (emitted as FHIR `Coverage`). Ignored for non-JP. |
| `--cache-dir DIR` | (unset) | F4 memoize: reuse patients whose encounters completed before the prior snapshot's cursor. Enables daily-cron append (p=500k advance drops from ~13 h to ~minutes). |
| `--log-file PATH` | `<output>/simulator.log` | Structured JSONL simulator log (Issue #172). Use `tail -f` to watch a run live. Level via `CLINOSIM_LOG_LEVEL` (default `INFO`). |
| `--allow-legacy` | off | (JP only) Permit legacy 5-digit JLAC10 OID output when the JP-CLINS package is not installed. Default is fail-loud (Issue #418) — `--country JP` requires the JP-CLINS package to emit eCS-compliant output. |

## `clinosim narrate` — Stage 2 (clinical documents)

> **Note**: template-mode DocumentReferences are already produced
> automatically during Stage 1 by `TemplateNarrativePass`, so
> `clinosim simulate --format fhir-r4` yields a valid FHIR bundle
> with `docStatus="preliminary"` documents even without a separate
> `narrate` step. Running `narrate` afterwards writes a new
> narrative version and (by default for the template provider)
> updates `current_version.txt` to point at it.

Reads an existing CIF directory and generates clinical documents.
Writes a new narrative version to `<cif>/narratives/<version_id>/`.

| Option | Default | Description |
|---|---|---|
| `--cif-dir DIR` | **required** | Path to an existing CIF directory |
| `--provider NAME` | `template` | Narrative generator: `template` (deterministic), or an LLM provider: `bedrock`, `ollama`, `mock`, `vllm` (OpenAI-compatible `/v1/chat/completions`; also covers SGLang and any other OpenAI-compatible server), `openai_compatible` (alias for `vllm`). |
| `--llm-config PATH` | provider-specific default | LLM service YAML (`clinosim/config/llm_service*.yaml`). Default: `bedrock` → `llm_service.bedrock.yaml`, `ollama` → `llm_service.yaml`, `mock` → in-code `MockProvider`. |
| `--version-id ID` | provider name | Narrative version directory name |
| `--tasks LIST` | all Tier A+B | Comma-separated `LLMTaskType` filter (`discharge_summary,death_summary,operative_note,admission_hp,procedure_note`) |
| `--country CODE` | `US` | Country code (display language) |
| `--set-current / --no-set-current` | provider-dependent | Update `current_version.txt`. Default: yes for `--provider template`, no for LLM providers (M-3 / N-chain guard: a trial run cannot silently repoint production exports), and always no when `--patient-filter` is set (chain 1b adv-1 I-1). Explicit `--set-current` / `--no-set-current` always wins. |
| `--seed N` | `42` | RNG seed for determinism |
| `--patient-filter REGEX` | (unset) | Regex over patient filename stem / `patient_id` — narrate only matching patients (remote per-patient iteration, chain 1b T3). The version manifest records the filter. |
| `--merge-into-version` | off | With `--patient-filter`: allow writing into an existing version directory that already contains documents (iterate-one-patient loop). Without this, a filtered write into a non-empty version is refused. |
| `--concurrency N` | `1` | Number of narrate worker threads. Higher values let a batching LLM backend (vLLM continuous batching, etc.) absorb N in-flight `generate()` calls — set to match the server's `--max-num-seqs` or a fraction of it. Requires thread-safe provider (Ollama, vLLM, Mock are). |

**Tier A+B document scope** (default):

| Document | LOINC | Generated when | Frequency |
|---|---|---|---|
| Discharge Summary | `18842-5` | Every inpatient discharge | 1 per encounter |
| Death Note | `69730-0` | Deceased inpatient | 1 per death |
| Operative Note | `11504-8` | Surgical procedure (SNOMED 387713003) | 1 per surgery |
| Admission H&P | `34117-2` | Every inpatient admission | 1 per encounter |
| Procedure Note | `28570-0` | Invasive bedside (central line, LP, thoracentesis, paracentesis, chest tube, intubation, bronchoscopy, cardioversion) | 1 per procedure |

See [../clinical_documents.md](../clinical_documents.md) for details.

## `clinosim export-fhir` — Stage 3 (FHIR R4 NDJSON)

Reads an existing CIF directory and writes FHIR R4 Bulk Data NDJSON
files. `DocumentReference` resources are emitted from
`record.documents` (populated by Stage 1's `document_enricher` and
promoted to `final` docStatus by the selected narrative version).

| Option | Default | Description |
|---|---|---|
| `--cif-dir DIR` | **required** | Path to an existing CIF directory |
| `-o, --output DIR` | `<cif>/../fhir_r4` | Output directory |
| `--country CODE` | `US` | `US` or `JP` |
| `--narrative-version ID` | `current` | Narrative version id (default reads the `current_version.txt` pointer) |

## `clinosim test-disease [DISEASE_ID]`

Generate a forced scenario for a specific inpatient disease (debug /
golden fixtures / AD-66 patient-profile bootstraps). `DISEASE_ID` is
optional when `--patient-profile` is set.

| Option | Default | Description |
|---|---|---|
| `--patient-profile NAME` | (unset) | Patient profile fixture name or path (AD-66); CLI args override profile fields with a stderr `WARN` |
| `-n, --count N` | 3 (or profile count) | Number of patients |
| `--severity LEVEL` | (from YAML) | Force severity: `mild` / `moderate` / `severe` |
| `--archetype NAME` | (from YAML) | Force archetype name |
| `-s, --seed N` | 42 (or profile `random_seed`) | Random seed |
| `--country CODE` | US (or profile country) | Country code |
| `--format ...` | (stdout debug) | One or more of `cif`, `fhir-r4`, `csv`, `all`. Requires `-o`. |
| `-o, --output DIR` | (unset) | Output directory (required when `--format` is set). When set, the full 3-stage pipeline (structural CIF + template narrative + FHIR / CSV) runs for the disease-specific mini-cohort. |

```bash
clinosim test-disease heart_failure_exacerbation \
  --severity severe --archetype treatment_resistant -n 3
```

## `clinosim test-encounter CONDITION_ID`

Simulate one (or more) patients through a single ED / outpatient
encounter YAML.

| Option | Default | Description |
|---|---|---|
| `-n, --count N` | 1 | Number of patients |
| `-s, --seed N` | 42 | Random seed |
| `--country CODE` | US | Country code |
| `--age N` | (sampled) | Force patient age |
| `--sex M/F` | (sampled) | Force patient sex |
| `--format ...` | (stdout debug) | Same as `test-disease` |
| `-o, --output DIR` | (unset) | Output directory (required when `--format` is set) |

```bash
clinosim test-encounter migraine --age 35 --sex F
```

## `clinosim validate`

Quality check generated data against published benchmarks.

| Option | Default | Description |
|---|---|---|
| `-p, --population N` | 5000 | Population size |
| `-s, --seed N` | 42 | Random seed |
| `--country CODE` | US | Country code |

## `clinosim list-diseases`

Show all 32 inpatient disease protocols
(`clinosim/modules/disease/reference_data/*.yaml`) + 46 ED /
outpatient encounter conditions
(`clinosim/modules/encounter/reference_data/*.yaml`).

## `clinosim enumerate` — exhaustive debug (Issue #345)

Generates exactly one patient per (disease × severity ×
course_archetype) plus per (encounter × severity). Population-driven
sampling can leave rare patterns unfired even at large `-p`;
`enumerate` deterministically covers every combination.

| Option | Default | Description |
|---|---|---|
| `-o, --output DIR` | **required** | Writes `cif/`, `cif/narratives/template/`, `fhir_r4/`, `enumeration_manifest.json` |
| `--level LEVEL` | `full` | `basic` (1 per scenario), `severity` (1 per scenario × severity), `full` (1 per disease × severity × course_archetype) |
| `--country CODE` | `US` | `US` or `JP` |
| `--include-both-countries` | off | Emit both JP and US patients in one run (approximately doubles the case count) |
| `--seed N` | 42 | Base seed for sub-seed derivation |
| `--yes-large` | off | Bypass the coverage-explosion guard (threshold: 2000 patients) |
| `--format ...` | `cif fhir-r4` | `cif`, `fhir-r4`, `csv`, `all` |
| `--dry-run` | off | Plan only — print discovered scenarios and case count, do not simulate |

## `clinosim diff` — snapshot diff → Bundle transaction

Turn two successive snapshots into a FHIR Bundle transaction (F3;
day-N vs day-M append). Runs on already-exported FHIR directories.

| Option | Default | Description |
|---|---|---|
| `--old DIR` | **required** | Previous snapshot's FHIR output directory |
| `--new DIR` | **required** | Current snapshot's FHIR output directory |
| `--output-bundle PATH` | **required** | Output path for the Bundle transaction JSON |
| `--output-summary PATH` | stdout | Output path for the summary text |
| `--old-cursor DATE` | old dir name | Previous cursor date (for the summary) |
| `--new-cursor DATE` | new dir name | Current cursor date (for the summary) |

## `clinosim regenerate-goldens`

AD-66 α-min-2c golden narrative bootstrap. Regenerates goldens for
canonical patient profiles under
`tests/fixtures/patient_profiles/`.

| Option | Default | Description |
|---|---|---|
| `--profile NAME` \| `--all` | (one required) | Single profile by name, or every profile |
| `--provider NAME` | `template` | `template` (writes `<name>.golden.json`), or `mock` / `bedrock` / `ollama` (writes `<name>.llm-<tag>.golden.json`) |
| `--llm-config PATH` | (default per provider) | LLM service YAML passed through to `narrate` |
| `--model-tag TAG` | provider name | Filename tag for LLM goldens |

## `clinosim check-narratives` — semantic narrative-CIF gate

β-JP-1 chain 1b T2 semantic check: the LLM-output gate where
byte-diff does not apply. Exit 0 = pass, 1 = findings.

| Option | Default | Description |
|---|---|---|
| `--cif-dir DIR` | **required** | Path to a CIF directory |
| `--version ID` | **required** | Narrative version id to check (e.g. `llm-mock`, `ollama`) |
| `--profile NAME` | (unset) | Patient profile — resolves expectations to `tests/fixtures/patient_profiles/<name>.llm-expectations.yaml` |
| `--expectations PATH` | (unset) | Explicit expectations YAML path (overrides `--profile`) |
| `--report PATH` | (unset) | Write the full `SemanticCheckReport` as JSON |

## `clinosim audit` — per-Module PR gate

AD-60 audit framework — six per-module plug-ins today (`hai`,
`antibiotic`, `order`, `imaging`, `document`, `triage`). See
`clinosim/audit/README.md` and [`../audit-cycles/`](../audit-cycles/README.md)
for the workflow.

## `clinosim dataset` — named-preset dataset builder

Build the four named presets (`us-100`, `us-1000`, `jp-100`,
`jp-1000`) or list available presets. See
[`datasets-full.md`](datasets-full.md).

```bash
clinosim dataset list
clinosim dataset build jp-100 --output ./jp-100
```

## `clinosim eval` — public 3-axis evaluation

Score any generated cohort on structural / clinical / locale axes.
See [`../eval.md`](../eval.md) and [`../eval-rules.md`](../eval-rules.md).

## `clinosim benchmark` — P2-15 prediction benchmark harness

Downstream ML prediction benchmarks (AKI, sepsis). See
[`../benchmarks.md`](../benchmarks.md) and
`clinosim/benchmarks/README.md`.

## Typical workflows

**Local template-only run (no LLM, deterministic):**
```bash
clinosim simulate -o ./output -p 5000 --country US --format fhir-r4
# Stage 2 template narrative + Stage 3 FHIR NDJSON both land under ./output.
```

**Local LLM (Ollama):**
```bash
clinosim simulate -o ./output -p 5000 --country US --format cif
clinosim narrate --cif-dir ./output/cif \
    --provider ollama --version-id ollama_en_v1
clinosim export-fhir --cif-dir ./output/cif --narrative-version ollama_en_v1
```

**Split: local Stage 1, EC2 Stage 2 (Bedrock), back to local Stage 3:**
```bash
# On local machine
clinosim simulate -o ./output -p 5000 --country US --format cif
scp -r ./output/cif ec2-user@ec2-host:/home/ec2-user/

# On EC2 (IAM role with bedrock:Converse)
clinosim narrate --cif-dir /home/ec2-user/cif \
    --provider bedrock --version-id bedrock_sonnet_en_v1

# Pull the narrative back, then export FHIR locally
clinosim export-fhir --cif-dir ./output/cif \
    --narrative-version bedrock_sonnet_en_v1
```

See [../bedrock_setup.md](../bedrock_setup.md) for the EC2 + Bedrock
setup guide.

---
