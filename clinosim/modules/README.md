# `clinosim.modules` — module index

## Purpose

`clinosim/modules/` is the aggregation directory for every generation
module in clinosim. Each subdirectory owns one slice of the synthesis
pipeline (patient generation, clinical state, care events, output
adapters, …) and ships its own `README.md` + `README.ja.md`, its own
YAML reference data (when applicable), and its own audit hooks (when
applicable).

This page is a **navigation index** — one line per module, grouped by
functional area, linking to each child's own README. Deep design
discussion lives inside the individual module docs; the wider
architecture view lives in [`AGENTS.md`](../../AGENTS.md) and
[`DESIGN.md`](../../DESIGN.md).

## Design conventions shared by all modules

Every module README follows the same **canonical 11-section
structure** (established in the s88k full-revision campaign):

1. Title — module path + one-line description
2. Purpose
3. Scope (In scope / Out of scope)
4. Public API
5. Determinism (`Not applicable — <reason>` when the module makes
   no random draws)
6. Dependencies
7. Constants and configuration
8. Directory contents
9. Enricher wiring (`Not applicable — <reason>` when the module is
   not registered with `register_builtin_enrichers`)
10. Output surfaces (consumers)
11. Testing
12. Ownership

Optional insertions: `Snapshot (AD-32)` (immunization),
`Extending` (data-only variant packages such as `sdoh`).

Cross-module invariants:

- **Boilerplate**: new modules copy from
  [`.github/TEMPLATE_MODULE_README.md`](../../.github/TEMPLATE_MODULE_README.md);
  the module-author workflow is documented in
  [`docs/CONTRIBUTING-modules.md`](../../docs/CONTRIBUTING-modules.md).
- **Deterministic**: modules that draw randomness use sub-seeded RNG
  streams so cohort output is byte-reproducible for a given
  `(country, population, seed, dates)` tuple (AD-16). Sub-seed
  offsets live in [`clinosim/seeding.py`](../seeding.py) via
  `ENRICHER_SEED_OFFSETS`.
- **Data-driven**: clinical parameters live in `reference_data/*.yaml`
  next to the engine (or in
  [`clinosim/locale/<country>/`](../locale/) for locale-scoped data)
  — never in Python literals. [Issue #637](https://github.com/TomoOkuyama/clinosim/issues/637)
  is the sweep that removed the last inline thresholds.
- **Locale-aware output, locale-independent core**: engines produce
  neutral CIF; the [`output/`](output/README.md) adapters render it
  per country. Code systems come from
  [`clinosim.codes`](../codes/data/).

## Module index (33 modules)

### Patient generation

| Module | Purpose |
| --- | --- |
| [`population/`](population/README.md) | Sample the patient cohort — demographics, monthly acute events, annual healthcare calendar. |
| [`patient/`](patient/README.md) | Layer-1 → Layer-2 activation — attach physiology reserves, baseline vitals, chronic conditions, home medications. |
| [`identity/`](identity/README.md) | Country-pluggable patient identifiers + insurance records (AD-54, `providers/*.py`). |
| [`sdoh/`](sdoh/README.md) | Social-determinants reference data (smoking / alcohol SNOMED + LOINC — data-only variant). |
| [`family_history/`](family_history/README.md) | First-degree relative history synthesis. |
| [`pediatric/`](pediatric/README.md) | Pediatric encounter emission (well-child / immunization / acute / behavioural — Issue #760). |

### Clinical state

| Module | Purpose |
| --- | --- |
| [`physiology/`](physiology/README.md) | Physiology state engine — every lab / vital / medication response derives from it. |
| [`clinical_course/`](clinical_course/README.md) | Trajectory archetype + daily `StateChangeDirective` engine. |
| [`disease/`](disease/README.md) | Disease-protocol registry (32 YAMLs) + severity + acuity + drug-vocabulary. |

### Care events

| Module | Purpose |
| --- | --- |
| [`encounter/`](encounter/README.md) | Encounter-condition registry (46 YAMLs) + inpatient daily-cycle timeline. |
| [`triage/`](triage/README.md) | ED triage sampling (JTAS / ESI, POST_ENCOUNTER order=93). |
| [`diagnosis/`](diagnosis/README.md) | Bayesian differential-diagnosis engine + Issue #551 non-specific codes. |
| [`order/`](order/README.md) | Order placement + panel grouping + treatment classifier + AD-60 audit. |
| [`procedure/`](procedure/README.md) | Surgical + bedside procedure + rehab session generation. |
| [`imaging/`](imaging/README.md) | Imaging study + series + radiology report (Tier 1 #2 chain, AD-60 audit). |
| [`device/`](device/README.md) | ICU device placement (CVC / catheter / ventilator, POST_ENCOUNTER order=70). |

### Observations & therapy

| Module | Purpose |
| --- | --- |
| [`observation/`](observation/README.md) | Lab-value engine + nursing flowsheet (NEWS2 / GCS / Braden / Morse) + microbiology. |
| [`nursing/`](nursing/README.md) | Primary-nurse assignment (POST_ENCOUNTER order=94) — distinct from `observation`'s nursing_flowsheets. |
| [`antibiotic/`](antibiotic/README.md) | HAI empirical + narrow-ladder regimens + AD-60 audit. |
| [`allergy/`](allergy/README.md) | Patient allergy sampling (POST_POPULATION order=10). |
| [`immunization/`](immunization/README.md) | Adult vaccine history from CVX schedule. |
| [`health_checkup/`](health_checkup/README.md) | JP employer-provided health checkup (opt-in, POST_RECORDS order=70). |
| [`monitoring/`](monitoring/README.md) | Chronic-medication → monitoring-lab injection (Issue #757). |

### Care operations

| Module | Purpose |
| --- | --- |
| [`facility/`](facility/README.md) | Hospital operational state + queueing-delay model. |
| [`healthcare_system/`](healthcare_system/README.md) | Country-config loader (leaf). |
| [`staff/`](staff/README.md) | Staff roster + per-event `assign_staff` dispatch. |
| [`care_level/`](care_level/README.md) | JP 要介護度 assignment (POST_RECORDS order=60, JP-only). |
| [`code_status/`](code_status/README.md) | Resuscitation-status tier assignment (POST_RECORDS order=50). |
| [`hai/`](hai/README.md) | HAI onset sampling (CLABSI / CAUTI / VAP) + Phase 3a lift + AD-60 audit. |

### Documents

| Module | Purpose |
| --- | --- |
| [`document/`](document/README.md) | Document-stub emission (POST_ENCOUNTER order=95) + AD-60 audit + canonical FHIR ID prefixes. |
| [`llm_service/`](llm_service/README.md) | Single LLM gateway (AD-11) — Bedrock / Ollama / vLLM / Anthropic / mock via `providers/`. |

### Output & validation

| Module | Purpose |
| --- | --- |
| [`output/`](output/README.md) | Output adapter entry point (FHIR R4 NDJSON, CIF-JSON, CSV) + FHIR R4 subpackage. |
| [`validator/`](validator/README.md) | Realism benchmarks + consistency checks (`clinosim validate` CLI). |

## Cross-references

- **Framework docs**:
  - [`clinosim.audit`](../audit/) — internal per-module PR verification (AD-60 plug-ins registered by `hai`, `antibiotic`, `order`, `imaging`, `document`, `triage`).
  - [`clinosim.codes`](../codes/data/) — clinical code systems (LOINC / ICD / RxNorm / SNOMED / …).
  - [`clinosim.seeding`](../seeding.py) — canonical `ENRICHER_SEED_OFFSETS` table.
- **Contribution guides**:
  - [`docs/CONTRIBUTING-modules.md`](../../docs/CONTRIBUTING-modules.md) — how to add a new module.
  - [`docs/add-your-country.md`](../../docs/add-your-country.md) — how to add a new country (locale + identity provider + healthcare-system config).
- **Architecture**:
  - [`AGENTS.md`](../../AGENTS.md) — AI-agent-facing instructions + data-flow + ADR pointers.
  - [`DESIGN.md`](../../DESIGN.md) — ADR table.
  - [`MODULES.md`](../../MODULES.md) — module overview cheat sheet.

Japanese counterpart: [`README.ja.md`](README.ja.md).
