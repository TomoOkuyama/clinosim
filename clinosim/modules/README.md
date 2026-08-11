# `clinosim.modules` — module index

## Purpose

`clinosim/modules/` is the aggregation directory for every generation
module in clinosim. Each subdirectory owns one slice of the synthesis
pipeline (patient generation, clinical state, care events, output
adapters, …) and ships its own `README.md` + `README.ja.md`, its own
YAML reference data, and its own audit hooks.

This page is a **navigation index** — one line per module, grouped by
functional area, linking to each child's own README. Deep design
discussion lives inside the individual module docs; a wider view of
how the modules interact lives in
[`docs/architecture/`](../../docs/architecture/README.md).

## Design conventions shared by all modules

- **Boilerplate**: each module follows the canonical layout documented
  in [`docs/CONTRIBUTING-modules.md`](../../docs/CONTRIBUTING-modules.md)
  and the [`TEMPLATE_MODULE_README.md`](../../.github/TEMPLATE_MODULE_README.md).
- **Deterministic**: modules that draw randomness use sub-seeded RNG
  streams so cohort output is byte-reproducible for a given
  `(country, population, seed, dates)` tuple (AD-16).
- **Data-driven**: clinical parameters live in `reference_data/*.yaml`
  next to the engine, not in Python literals — see [Issue #637](https://github.com/TomoOkuyama/clinosim/issues/637)
  for the campaign that removed the last of the inline thresholds.
- **Locale-aware output, locale-independent core**: engines produce
  neutral CIF; the [`output/`](output/README.md) adapters render it
  per country. Code systems come from
  [`clinosim.codes`](../codes/README.md).

## Module index

### Patient generation

| Module | Purpose |
| --- | --- |
| [`population/`](population/README.md) | Sample the patient cohort — demographics, life events, cohort-scale determinism. |
| [`patient/`](patient/README.md) | Activate the sampled patient — attach identity, chronic conditions, current medications. |
| [`identity/`](identity/README.md) | Country-pluggable patient identifiers and insurance records (`providers/*.py`). |
| [`sdoh/`](sdoh/README.md) | Social determinants of health — housing, employment, education, insurance. |
| [`family_history/`](family_history/README.md) | Family-history record generation. |

### Clinical state

| Module | Purpose |
| --- | --- |
| [`physiology/`](physiology/README.md) | 13-variable physiological state engine — the load-bearing core that makes labs / vitals coherent by construction. |
| [`clinical_course/`](clinical_course/README.md) | Clinical trajectory engine — drives disease severity and recovery over time. |
| [`disease/`](disease/README.md) | Disease protocol registry — 32 inpatient diseases + 46 ED/outpatient conditions as YAML. |

### Care events

| Module | Purpose |
| --- | --- |
| [`encounter/`](encounter/README.md) | Encounter protocol registry — inpatient / ED / outpatient shape. |
| [`triage/`](triage/README.md) | ED triage assignment. |
| [`diagnosis/`](diagnosis/README.md) | Bayesian differential-diagnosis engine — admission → confirmed diagnosis chain. |
| [`order/`](order/README.md) | Order engine — labs, imaging, medications, procedures placed on the encounter. |
| [`procedure/`](procedure/README.md) | Surgical + therapeutic procedure generation. |
| [`imaging/`](imaging/README.md) | Imaging metadata chain (order → result). |
| [`device/`](device/README.md) | ICU device placement (CVC / bladder catheter / ventilator). |

### Observations & therapy

| Module | Purpose |
| --- | --- |
| [`observation/`](observation/README.md) | Laboratory + vital-sign generation driven off the physiology state. |
| [`nursing/`](nursing/README.md) | Nursing assessments and workflow (NEWS2, GCS, Braden, Morse, …). |
| [`antibiotic/`](antibiotic/README.md) | Empirical antibiotic selection + dosing. |
| [`allergy/`](allergy/README.md) | Patient allergy generation. |
| [`immunization/`](immunization/README.md) | Immunization history. |
| [`health_checkup/`](health_checkup/README.md) | JP employer-provided health checkup (opt-in). |

### Care operations

| Module | Purpose |
| --- | --- |
| [`facility/`](facility/README.md) | Facility / department definitions and hospital operational state. |
| [`healthcare_system/`](healthcare_system/README.md) | Country-level healthcare-system model. |
| [`staff/`](staff/README.md) | Practitioner roster generation + assignment. |
| [`care_level/`](care_level/README.md) | Care-level / activity-of-daily-living scoring. |
| [`code_status/`](code_status/README.md) | Advance-directive / code-status assignment. |
| [`hai/`](hai/README.md) | Healthcare-associated infection sampling (CLABSI / CAUTI / VAP). |

### Documents

| Module | Purpose |
| --- | --- |
| [`document/`](document/README.md) | Clinical document assembly (discharge summary, progress notes, …). |
| [`llm_service/`](llm_service/README.md) | LLM provider integration for narrative generation (Bedrock / Ollama / mock, plug-in registration under `llm_service/providers/`). |

### Output & validation

| Module | Purpose |
| --- | --- |
| [`output/`](output/README.md) | Output adapter entry point (FHIR R4 NDJSON, HL7 v2, CDA, CSV). |
| [`validator/`](validator/README.md) | Realism benchmarks and consistency checks against clinical priors. |

## Cross-references

- **Framework docs**:
  - [`clinosim.audit`](../audit/README.md) — internal per-module PR verification gate.
  - [`clinosim.eval`](../eval/README.md) — public cohort evaluation.
  - [`clinosim.codes`](../codes/README.md) — clinical code systems (LOINC / ICD / RxNorm / …).
  - [`clinosim.benchmarks`](../benchmarks/README.md) — early-warning baseline metrics.
- **Contribution guides**:
  - [`docs/CONTRIBUTING-modules.md`](../../docs/CONTRIBUTING-modules.md) — how to add a new module.
  - [`docs/add-your-country.md`](../../docs/add-your-country.md) — how to add a new country (locale + identity provider + healthcare system).
- **Architecture**:
  - [`docs/architecture/`](../../docs/architecture/README.md) — data-flow, module dependency graph, design principles, ADR history.
