# clinosim Development Guidelines

## Project overview

clinosim is a population-driven, physiology-based synthetic EHR data simulator.
See `README.md` (English) / `README.ja.md` (日本語) for user-facing overview, `DESIGN.md` for full architecture (ADRs), `TODO.md` for roadmap, and each `modules/<name>/README.md` for module-level reference.

## Language conventions

- **Code**: Python 3.11+
- **Code comments and docstrings**: English
- **README.md**: English (default, international audience)
- **README.ja.md**: Japanese translation of README.md
- **Module READMEs** (`modules/<name>/README.md`): Japanese with English technical terms
- **Other docs** (DESIGN.md, TODO.md, spec.md): English
- **Communication with user**: Japanese

## Code standards

- Formatter: ruff
- Type checking: mypy (strict mode)
- Line length: 100
- Types: Pydantic BaseModel for YAML-loaded configs (AD-18). `@dataclass` for runtime types.
- All types defined in `clinosim/types/` — never define data types inside module code.
- Public API surface: only what's exported in module `__init__.py`.

## Architecture rules

### Data flow & ownership

- **CIF is the only simulation output** (AD-17) — format adapters (FHIR, CSV) read CIF, never simulation internals.
- **CIF stores codes only, not display text** (AD-30) — `ClinicalDiagnosis.admission_diagnosis_code` + `_system`, no `_name`. Display is resolved at output time via `clinosim.codes`.
- **Code is the truth** — Internal test names (e.g., `"WBC"`) are mapped to standard codes (LOINC) via `locale/<country>/code_mapping_*.yaml`. Display text comes from `clinosim/codes/data/<system>.yaml`.

### Module independence

- Each module under `clinosim/modules/` can only depend on `clinosim/types/`, `clinosim/codes/`, `clinosim/locale/`, and other modules listed in its `README.md` Dependencies section.
- **LLM calls only via `llm_service`** (AD-11) — no other module may call Ollama or Anthropic APIs directly.
- **Deterministic with seed** (AD-16) — each module creates its own `numpy.random.Generator` from a sub-seed. Never use `random.random()` or shared global state.

### EHR data enrichment — Base vs Module (AD-55) + extensibility (AD-56)

- **Near-essential data → Base** (always-on, extend core: `types`/`population`/`observation`/`simulator`/`output`). **Specialized/optional data → opt-in module**, one theme per module (like `identity`), gated via `SimulatorConfig.modules` + `config.module_enabled(name)`.
- **Add a FHIR resource** by registering a builder via `register_bundle_builder()` (AD-56) — do NOT edit `_build_bundle()`. Builders return raw resources `(ctx) -> list[resource]`.
- **Add an output format** by registering an `OutputAdapter` via `register_output_adapter()` (AD-58) — do NOT edit the CLI `--format` dispatch. Adapters read CIF + `clinosim.codes` + `clinosim.locale` only.
- **Add a post-population / post-records pass** by registering an `Enricher` in `simulator/enrichers.py` (`register_builtin_enrichers`) — do NOT inline it into `run_beta`. Enrichers derive their own sub-seed; order is fixed (determinism).
- **Modules must NOT edit `CIFPatientRecord`** — write to `CIFPatientRecord.extensions[<module>]`. Only Base data adds typed fields to the core type.
- Refactors of these paths must preserve golden/e2e output and determinism.

### Code system module (`clinosim/codes/`)

- **English-first principle**: every code in `codes/data/*.yaml` MUST have an `en` field. Other languages (`ja`, etc.) are optional translation attributes.
- **Authoritative sources**: code values and English text follow official definitions from CMS (ICD-10-CM), NLM (RxNorm), Regenstrief (LOINC), AMA (CPT), WHO (ICD-10), JCCLS (JLAC10), MHLW (YJ codes, K codes).
- **Locale-independent**: `clinosim/codes/` is NOT under `locale/`. Code systems are international standards.
- **Single lookup API**: all code → display resolution goes through `clinosim.codes.lookup(system, code, lang)`.

### Locale module (`clinosim/locale/`)

- Contains **only culture/country-dependent data**: names, addresses, demographics, formatting, lab reference ranges, code_mapping (internal name → standard code).
- Terminology files (`terminology_*.yaml`) have been migrated to `clinosim/codes/`. Do not recreate them in locale.

### FHIR R4 output

- **Bulk Data Access compliant** (AD-31) — one NDJSON per resource type + manifest.json. No per-encounter Bundle wrapping.
- **Resource.id uniqueness**: every resource id must be globally unique within its type. Use encounter-scoped ids (`vs-{encounter_id}-...`, `lab-{encounter_id}-...`) for observations and orders.
- **Reference integrity**: every `reference` must resolve to a resource in the same export.
- **`_facility.json`** contains Organization (hospital + departments) and Location (wards + beds) as a master Bundle.

### Snapshot semantics (AD-32)

- `--end` flag = **snapshot date**. No life events generated past this date.
- Inpatients whose discharge would fall after snapshot become `Encounter.status = "in-progress"` with no `discharge_datetime`.
- Partial data only (labs/vitals/orders/MAR up to snapshot day).
- Primary `Condition.clinicalStatus = "active"` for in-progress encounters.

## Testing

- `pytest -m unit` — per-module unit tests (<30s)
- `pytest -m integration` — module chain tests (<5min)
- `pytest -m e2e` — golden file comparison (<30min)
- `pytest -x` — full suite (234 tests; unit+integration ~2 min, e2e golden ~8 min)
- Always run unit tests before committing.

## When modifying a module

1. Read the module's `README.md` first
2. Make changes
3. Check the dependency graph in main `README.md` — verify downstream impact
4. Update the module's `README.md` if API/data structures changed
5. Update `clinosim/types/*.py` if shared data types changed
6. If adding a new code, add it to `clinosim/codes/data/<system>.yaml` with at least an `en` field
7. Run tests: `pytest -x -q`

## FHIR output rules (must follow for all resource builders)

- **Multilingual coding**: Condition and Procedure emit dual `coding[]` entries — primary language + interop language. Never emit `display == code`.
- **code.text**: Use clinical short names from `_CONDITION_SHORT_NAME` (e.g. "COPD" not "Other chronic obstructive pulmonary disease"). For Procedures, resolve via `code_lookup()`.
- **Medication text**: Strip protocol prefixes (DVT_prophylaxis:, antipyretic: etc.) via `_strip_protocol_prefix()`. `medicationCodeableConcept.text` = drug name only.
- **referenceRange + interpretation**: Both MUST be present for numerical observations and MUST be consistent (FHIR R5 Note 5). Lab interpretation recomputed from value vs referenceRange.
- **JP localization**: All `display`, `text`, `name` fields must use Japanese when `country="JP"`. Use `_localize_display()` for enum values. Drug/procedure names via `code_lookup()` or `_localize_drug_name()`.
- **US output**: Must be 100% English. No Japanese characters in any field.

## Enrichment architecture (narrative prompts)

- **Enrichment is language-neutral** (AD-44): extraction functions produce English structured data regardless of target language. LLM translates based on prompt language instruction.
- **Only 2 locale-specific operations in enrichment**:
  1. `code_lookup(system, code, language)` — returns official diagnosis short name in target language
  2. CRP unit conversion (mg/L → mg/dL for JP) — mathematical, not translation (AD-42)
- **Do NOT pre-translate** drug names, procedure names, complication labels, event descriptions. LLM handles this.
- **FHIR adapter localization is separate** — FHIR output path (not going through LLM) uses its own dictionaries (`drug_names_ja.yaml`, `_PROCEDURE_NAME_JA`, `_CONDITION_SHORT_NAME`, etc.)

## AD-30 (CIF is language-neutral) enforcement

- CIF stores **codes only**, not display text. Display resolved at output time via `clinosim.codes.lookup()`.
- `ProcedureRecord` has `procedure_code`, `procedure_code_jp`, `procedure_code_us` — no `procedure_name`.
- Drug names in `Order.display_name` and `MAR.drug_name` are English (pragmatic exception — RxNorm integration incomplete).
- Diagnosis display comes from `code_lookup()` at FHIR export / enrichment time.

## Current implementation phase

**v0.1-beta** — population-driven simulation with full FHIR R4 Bulk Data Export, multi-country (US/JP), 32 diseases, snapshot date support, and opt-in JP insurance enrollment (FHIR Coverage, AD-54).

See `TODO.md` for roadmap and remaining tasks.

## Key directories

```
clinosim/
  codes/           <- ★ International code systems (locale-independent, EN-first)
    data/          <- icd-10-cm.yaml, loinc.yaml, rxnorm.yaml, ...
    loader.py      <- lookup() API
  locale/          <- Country/culture-specific data (names, addresses, ranges)
    jp/, us/, shared/
  config/          <- Hospital config YAML (50-bed, 10-bed, etc.) + LLM config
  types/           <- All data type definitions (Pydantic / dataclass)
  modules/         <- Functional modules (one package per module, each with README)
    identity/      <- ★ Resident identifier & insurance numbering (JP, opt-in; AD-54)
  simulator/       <- Top-level orchestration (run_beta, run_forced, CLI)
    enrichers.py   <- ★ Enricher registry for opt-in module passes (AD-56)
tests/             <- Test code (unit / integration / e2e)
```

## Hospital configuration

Each hospital is defined by a YAML in `clinosim/config/hospital_*.yaml`:

- `hospital_operations.yaml` — 50-bed community hospital (default)
- `hospital_small.yaml` — 10-bed clinic
- `hospital_large.yaml` — 200-bed regional hospital (full service)
- Custom configs supported via `--hospital-config PATH`

Required fields: `recommended_population`, `available_departments`, `department_rollup`, `wards`, `ward_capacity`, `resource_capacity`, `staffing`.

The `available_departments` list determines which physicians get generated. The `department_rollup` map resolves granular specialties (e.g., pulmonology) to available departments (e.g., internal_medicine) for hospitals that don't have all sub-specialties.

## LLM setup

Default: local Ollama (no API key or cloud account needed).

```bash
# Install Ollama
brew install ollama    # macOS
# or: curl -fsSL https://ollama.com/install.sh | sh   # Linux

# Pull the default model
ollama pull qwen:7b

# (Optional) Higher quality model for narratives (requires ~40GB VRAM)
ollama pull llama3.1:70b
```

Config files:
- `clinosim/config/llm_service.yaml` — default (local Ollama)
- `clinosim/config/llm_service.bedrock.yaml` — AWS Bedrock (Claude Sonnet 4, EC2 with IAM role)
- `clinosim/config/llm_service.cloud.yaml` — cloud (Anthropic API, needs `ANTHROPIC_API_KEY`)

JUDGMENT and NARRATIVE can use different providers (AD-24). See `modules/llm_service/README.md` for details.

LLM is **not required** for structural data generation. Without an LLM, template-based narratives are used.

## Disease protocol YAML files

Located at `clinosim/modules/disease/reference_data/`. Validated by Pydantic models (`DiseaseProtocol`) at load time.

Adding a new disease:

1. Create `clinosim/modules/disease/reference_data/<disease_id>.yaml`
2. Reference an existing disease as template
3. Required: `disease_id`, `chief_complaint` (multi-language dict), `department`, `icd_codes`, `target_los`, `course_archetypes`, `outcome_benchmarks`
4. Add to incidence list in `clinosim/locale/<country>/demographics.yaml`
5. **Register every `icd_codes` value (primary AND variants) in the code data** — see
   "Diagnosis code coverage" below. Skipping this makes the FHIR Condition display fall
   back to approximate prefix-matched text instead of the authoritative entry.
6. Test: `clinosim test-disease <disease_id>` and `pytest tests/unit/test_diagnosis_code_coverage.py`

No engine code changes required.

### Diagnosis code coverage (REQUIRED when adding/editing any disease or encounter)

`codes/data/*.yaml` is an intentional **subset** (only codes clinosim emits). The invariant
**every emittable diagnosis code resolves to an authoritative entry** is enforced by
`tests/unit/test_diagnosis_code_coverage.py`. For each new/changed `icd_codes` value or
encounter `icd10_code` `C`, verify the code vs an authoritative source (NLM ICD-10-CM API
`clinicaltables.nlm.nih.gov/api/icd10cm`, WHO browser) — **never fabricate** — then:

- **US billable**: if `C` is a valid billable ICD-10-CM leaf, add it to `codes/data/icd-10-cm.yaml`
  (`en` + `ja`). If `C` is a non-billable category/header or WHO-only (e.g. `I21.2`, `I50.0`,
  `N30.9`), add a `code_mapping_diagnosis/us.yaml` entry `C → <billable leaf>` and register the
  leaf in `icd-10-cm.yaml`.
- **JP (WHO)**: ensure `code_mapping_diagnosis/jp.yaml.get(C, C)` resolves in `codes/data/icd-10.yaml`
  (WHO) or, by the adapter's documented cross-fallback, in `icd-10-cm.yaml`.

Run `pytest tests/unit/test_diagnosis_code_coverage.py` — green means coverage is complete.

## Encounter (ED/outpatient) protocol YAML files

Located at `clinosim/modules/encounter/reference_data/`. 46 conditions covering ED visits and outpatient encounters.

Adding a new encounter type:

1. Create `<condition_id>.yaml` with: `condition_id`, `icd10_code`, `icd10_display`, `chief_complaint` (multi-language dict), `encounter_type`, `department`, `severity_distribution`, `workup`, `treatment`, `discharge_instructions`
2. **Register `icd10_code` in the code data** per "Diagnosis code coverage" above (US billable in `icd-10-cm.yaml` / map; JP in `icd-10.yaml`).
3. Test: `clinosim test-encounter <condition_id>` and `pytest tests/unit/test_diagnosis_code_coverage.py`

## Adding a new code

To add a new ICD/LOINC/RxNorm/etc. code:

1. Edit `clinosim/codes/data/<system>.yaml`
2. Required: `en` field with the official English description
3. Optional: `ja` field with translation
4. Source must be authoritative (CMS, NLM, AMA, WHO, JCCLS, MHLW)

```yaml
codes:
  N10:
    en: "Acute tubulo-interstitial nephritis"   # ← required
    ja: "急性腎盂腎炎"                         # ← optional
```

## Adding a new language

Add the new language key to entries in `clinosim/codes/data/*.yaml`:

```yaml
N10:
  en: "Acute tubulo-interstitial nephritis"
  ja: "急性腎盂腎炎"
  de: "Akute tubulointerstitielle Nephritis"   # ← new language
```

The loader falls back to English if a requested language is missing.

## Common pitfalls

- ❌ **Never store display text in CIF.** CIF should only contain codes + system keys. Display is resolved at output time.
- ❌ **Never hardcode FHIR system URIs.** Use `clinosim.codes.get_system_uri(system_key)`.
- ❌ **Never add a code without an `en` entry.** English is required.
- ❌ **Never use `random.random()`.** Always use a seeded `numpy.random.Generator` passed in via parameter.
- ❌ **Never call LLM APIs from outside `llm_service`.**
- ❌ **Never define data types inside module code.** All shared types live in `clinosim/types/`.
- ❌ **Never duplicate locale-specific data and code-system data.** Code systems go to `codes/`, culture data goes to `locale/`.
