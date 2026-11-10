# clinosim Implementation Rules — invariants every implementer must know

**Status:** Active.
**Audience:** every person or coding agent writing or modifying
clinosim code.
**Positioning:** the entry point for the coding rules. The rules
below apply without exception; each domain's detailed rules live in
a binding spec (table below), the shared helpers the rules refer to
are listed in [`shared-helpers-catalog.md`](shared-helpers-catalog.md),
and the module HOW-TO is `docs/CONTRIBUTING-modules.md`. When in
doubt, apply the four judgment axes: **data quality, clinical
coherence, maintainability (responsibility-decomposition points),
conceptual fit**.

### Where each rule lives

| Concern | Read |
|---|---|
| Rules that apply to every change (this page) | `implementation-rules.md` |
| Which shared helper to use for X | [`shared-helpers-catalog.md`](shared-helpers-catalog.md) |
| Documentation language, comments, constants placement, dead code | [`documentation-and-code-quality-policy.md`](documentation-and-code-quality-policy.md) |
| Code systems, display text, localization, fallback | [`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md) |
| Random draws, seeds, clocks | [`determinism-and-rng-spec.md`](determinism-and-rng-spec.md) |
| Reference-data YAML, age bands, constants | [`configuration-and-reference-data-spec.md`](configuration-and-reference-data-spec.md) |
| Medication orders, holds, administrations, discharge prescriptions | [`medication-lifecycle-spec.md`](medication-lifecycle-spec.md) |
| Lab values, orders, results | [`lab-orders-and-results-spec.md`](lab-orders-and-results-spec.md) |
| Document planning and narrative wording | [`narrative-and-document-generation-spec.md`](narrative-and-document-generation-spec.md) |
| Encounter setup, snapshot, FHIR finishing | [`encounter-lifecycle-and-export-spec.md`](encounter-lifecycle-and-export-spec.md) |
| FHIR completeness (C1 / C2 / C3) | [`data-model-and-completeness-conventions.md`](data-model-and-completeness-conventions.md) |
| Writing a FHIR builder | [`fhir-data-generation-logic.md`](fhir-data-generation-logic.md) |

---

## Grand design: code and data are separated

clinosim keeps **logic in code and every constant, variable and parameter
in data**. This is the governing rule above every other rule on this page.

- Anything that differs **by country, by age or age band, by sex**, or is a
  tunable clinical or statistical value — thresholds, cut-offs, rates,
  probabilities, distributions, durations and intervals, dose limits, codes,
  display text, formats, ordered lists — lives in YAML
  (`reference_data/`, `clinosim/locale/<country>/`, `clinosim/codes/data/`,
  `clinosim/config/`) with a cited source, and code reads it through a
  loader.
- Code does not **select a value** with a branch on country, age or sex
  (`if is_jp(country): x = ...`, `country == "JP"`, `if age < 18: dose = ...`,
  `if sex == "F": ...`). It looks the value up by country / age band / sex
  in a table. Adding a country, or changing an age band, edits YAML only.
- Country-specific **processing** — an algorithm only one country uses (a
  check-digit rule, an eGFR equation, the assembly of a JP Core element) —
  is code, but it is a named implementation registered in code, and **which
  one a country uses is chosen in YAML** (`locale/<country>/egfr_equation.yaml`
  names the equation; the code implements each one). The common flow calls
  the implementation the country's YAML names, not an `if is_jp(...)`
  branch, so a new country reuses existing implementations from YAML alone
  and adds code only for a genuinely new algorithm.

  | What differs | Where it lives |
  |---|---|
  | a value (code, text, threshold, age band, unit, table) | YAML |
  | an algorithm only some countries use | code, as a named implementation |
  | which algorithm or structure a country uses | YAML |

- Where no such registry exists yet, a country branch in code may only
  decide **whether** a profile-mandated structure is emitted (a JP Core /
  JP-CLINS element, slice or resource that US output does not have); the
  values inside it still come from YAML.
- The one place for numbers in Python is the documented formula-constant
  module of policy §5.1 (`_<topic>_thresholds.py` / `_<topic>_defaults.py`):
  the coefficients of one formula, RNG salts, YAML fallbacks, enums and keys.
- A change that adds hard-coded country, age or sex data is rejected in
  review; when you touch code that already has some, move it to YAML in the
  same PR if small, otherwise file an Issue.

Placement details: [documentation-and-code-quality-policy §5](documentation-and-code-quality-policy.md#5-constants-and-configuration)
and [configuration-and-reference-data-spec](configuration-and-reference-data-spec.md).

---

## 0. Workflow discipline (before you write any code)

1. **Workflow**: one GitHub Issue per PR → read the code and the
   binding spec → TDD implementation (test first) → verification on
   a generated cohort → PR → review (findings must be evidenced) →
   fix → whole suite green → merge. Larger designs get a design note
   first (`docs/history/specs-archive/`).
2. **Scope discipline**: no scope expansion after the spec is
   finalised. Findings outside scope are addressed only when they
   are "essential to data quality or clinical coherence"; otherwise
   they become **formal entries on the GitHub Issues board** (see
   `docs/roadmap.md`; the pre-Issues `TODO.md` ledger has been
   retired) with context, file:line, and a fix proposal.
3. **Pre-work status audit**: do not take TODO / doc claims at face
   value; **verify empirically before implementing** (count the
   behaviour in a generated cohort first — reported gaps are often
   already fixed).
4. **Do not narrate before observing**: never write "success" before
   you see the tool result. Show verification via execution output
   (test output, real-cohort grep, sha256).
5. **Commit conventions**: `<type>(<module>): <summary>` with type
   `feat` / `fix` / `refactor` / `docs` / `test` / `chore`, signed
   off (`git commit --signoff`, DCO). Push and open the PR after
   verification is green.

## 1. Coding standards

- Python 3.11+ / ruff (line length 120) / mypy (`mypy clinosim/`;
  CI blocks merge on ruff check, ruff format --check and mypy) / vulture
  (unused code; framework-read members go in `.vulture-whitelist.py`).
- **In-code comments and docstrings are English**, except the
  Japanese-spec categories listed in the documentation policy §4.
  Documentation is English in
  `*.md` with a Japanese counterpart in `*.ja.md`
  ([`documentation-and-code-quality-policy.md`](documentation-and-code-quality-policy.md) §1).
- **Types shared between modules, and the CIF types, live only in
  `clinosim/types/`** (YAML config = Pydantic BaseModel (AD-18);
  runtime = `@dataclass`). A module may define private types that
  never leave it: the Pydantic models that validate its own
  reference YAML (`_models.py` or next to the loader) and internal
  helper bundles. Once a second module needs the type, move it to
  `clinosim/types/`.
- **Public API = only what a module's `__init__.py` exports.**
- Comments describe only "constraints the code cannot show". Do not
  write change history or self-evident explanations.

## 2. Architectural invariants (data flow)

| Invariant | Content |
|---|---|
| AD-17 | **CIF is the sole simulation output.** Format adapters (FHIR / CSV) read only from CIF. |
| AD-30 | **CIF holds codes only; no display text.** Display is resolved at output time via `clinosim.codes.display(...)` with an explicit fallback. |
| AD-65 | **Two-file separation: structural / narrative.** Stage 1 emits only the `ClinicalDocument` stub (`narrative=None`); the post-simulation `NarrativePass` writes into `narratives/<version>/`. Mixing narrative inline is forbidden. |
| AD-31 | FHIR is Bulk Data NDJSON (resource id is globally unique within its type; references resolve within one export). |
| AD-32 | `--end` = snapshot date. No event generation past that date; honour the in-progress-encounter semantics. |
| AD-55 / AD-56 | Modules write into `CIFPatientRecord.extensions[<module>]` (new typed fields on core types are Base-only). Extension goes through three registries (`register_bundle_builder` / `register_output_adapter` / `register_enricher`); the dispatch body itself is never edited. |
| AD-11 | **LLM calls go through `llm_service` only.** From the narrative layer, `LLMService.complete_prompt()` is the sole seam. Directly importing a provider SDK is forbidden. |

## 3. Determinism (AD-16 / AD-59) — absolute rules

**Normative spec:** [`determinism-and-rng-spec.md`](determinism-and-rng-spec.md) defines the generator factory, seed derivation, RNG-neutral changes and clock rules, with their guards. Below is a summary.

- `random` and `numpy.random.default_rng` are forbidden. Every
  generator comes from `clinosim.determinism.default_rng(seed)` with
  a seed derived in `clinosim/seeding.py`
  (`derive_sub_seed(master_seed, module_offset, key)` + registration
  under `ENRICHER_SEED_OFFSETS` (16-bit hex-ASCII), or a named
  per-entity seed function such as `panel_specimen_seed` /
  `individual_lab_seed`). Never hash a seed at the call site.
- A draw that must not shift any other draw (an RNG-neutral change)
  uses the stream-free `sha_quantile` / `sha_bernoulli` /
  `sha_normal` / `sha_weighted_choice` from `clinosim.determinism`,
  never an inline `hashlib.sha256` formula.
- **`datetime.now()` / `date.today()` do not appear on the
  generation path.** The files allowed to read a clock are pinned
  in `tests/unit/test_determinism_spec_guards.py`; adding more is
  forbidden. Narrative
  timestamps use the `_deterministic_timestamp` family.
- **The return value of an `@lru_cache`d loader is a shared
  instance — never mutate it** (`load_disease_protocol` /
  `load_encounter_condition` / `load_healthcare_config` /
  `load_hospital_operations` / every other cached loader).
- Do not change enricher execution order (`stage` + `order`). Register
  a new enricher in `simulator/enrichers.py:register_builtin_enrichers`.
- The `NarrativePass` walk order (`(doc_type, language) → sorted
  patients`) is optimised for the prompt cache; **do not change it**.

## 4. Canonical single-source helpers (re-implementation and inlining absolutely forbidden)

The same logic in two or more places is a violation. Every shared
helper, with its path and the spec that governs it, is listed in
[`shared-helpers-catalog.md`](shared-helpers-catalog.md); look there
before writing any small utility. The rules that most often go wrong:

| Concern | Rule |
|---|---|
| Country decisions | `is_jp(country)` / `is_us(country)` (`clinosim/countries.py`) for country rules only. Hand-written `country == "JP"` comparisons are forbidden. The display language comes from `lang_for(country)`, never from `is_jp`. |
| Code system per country | `system_key_for(kind, country)` / `drug_system_key(code, country)` (`clinosim.codes`). Inline jlac10 / loinc or yj / rxnorm branching is forbidden. |
| System URI | `get_system_uri(key)` (`clinosim.codes`). Hard-coded code-system URIs are forbidden; a profile or identifier URI used in more than one file is one module-level constant. |
| code → display | `display(system, code, lang) or <explicit fallback>` (`clinosim.codes`); FHIR codings via `dual_slot_concept` / `system_coding`. `lookup(...)` is legacy and not used in new code; hard-coded display strings are forbidden. |
| Dict / dataclass dual read | `get_attr_or_key` (`modules/_shared.py`). New `isinstance(x, dict)` branches and local `_get` helpers are forbidden. **Applies to every read path — cache keys, comparisons, branching** (a `getattr` on a dict once made a whole cohort share one cache entry). |
| Dict / dataclass dual write | `set_attr_or_key(obj, name, value)` / `get_or_create_container(obj, name, factory)`. |
| Hash-based draws and seeds | `clinosim.determinism.sha_*` and named functions in `clinosim/seeding.py`; never `hashlib.sha256` + `int.from_bytes` at the call site (§3). |
| Age bands | `clinosim.age_bands` over a YAML table keyed by bands; hard-coded `if age < 18` cut-offs are forbidden. |
| Probability vectors | `normalize_probabilities(p, fallback="raise")` on every YAML-sourced `rng.choice(p=)`. |
| Scenario / medication flags | Merge `scenario_flags_from_protocol` + `medication_flags_from_context` and pass **`**flags`**. Adding named-arg parameters is forbidden (a flag read in only one venue silently disables it in the others). |
| Severity | `sample_severity` / `sample_severity_category` / `category_from_score` (`disease/severity.py`, AD-67). The disease YAML `severity.distribution × modifiers` is the only source; hard-coding the 0.3 / 0.7 boundaries is forbidden (`SEVERITY_SCORE_RANGES` is the single definition). |
| JP Core / JP-CLINS profile URIs | Quote the `fixedUri` from the spec's `StructureDefinition-*.json`; **do not guess**. Define it as a module-level constant and pin it with a unit test (`tests/unit/output/test_fhir_jp_core_p14_slices.py` is the model). A guessed URI makes validators silently ignore the slice. The same rule applies to JP-eCheckup / SS-MIX2 URIs. |
| Locale display tables | The cached loaders in `locale/loaders/` (re-exported by `locale/loader.py`). Opening raw YAML in Layer 4 is forbidden. |

If the same shared logic is needed in a second module, define it
once in `_shared.py` or the owner module, import it from both, and
add it to the catalog. **When a third consumer appears, import it —
do not redefine.**

## 5. Loader / reference-data conventions

- Canonical path constants: `_HERE = Path(__file__).resolve().parent`
  / `_REF_DIR = _HERE / "reference_data"` / `_LOCALE = _HERE.parents[1] / "locale"`.
  Fragile `.parent.parent.parent` is forbidden. Directly pathing
  into another module's `reference_data` is forbidden (create an
  accessor on the owner module — e.g.
  `observation.microbiology.antibiotic_loinc_lookup`).
- `@lru_cache`: no-param → `maxsize=1`; `(country)` → 2. Hand-rolled
  sentinel caches are forbidden.
- **Fail-loud validation at import / load time is mandatory**:
  every module reference YAML is loaded through
  `load_validated_yaml(path, Model)` (or validated by a Pydantic
  model at load). A YAML that references external IDs (SNOMED, LOINC,
  ICD, drug key), probability weights, or enum values
  (`generation_frequency`, `stage2_strategy`, etc.) must **raise at
  load time** on unknown keys or contradictions detected against
  the canonical set. Silent fall-through via `dict.get()` is
  forbidden.
- Put aggregate loaders (glob everything and load) **on the owner
  module** (do not glob other-module directories from the
  simulator).
- **YAML-loaded Pydantic models use `extra="forbid"`** (AD-69).
  `DiseaseProtocol` / `PatientProfile` already do. When you add a
  new top-level YAML key, **add the model field first** (skipping
  this causes a raise at load time = the author-time silent-drop
  defense). `DiseaseProtocol`'s raw-dict consumption path
  (`order/engine.py`) is outside `forbid`'s protection, so declare
  the keys it reads on the model too.
- **The three FHIR completeness invariants** (AD-67 / 68 / 69,
  `data-model-and-completeness-conventions.md`):
  (1) **C1**: do not ship YAML keys that are not read (`forbid` +
  wired consumer);
  (2) **C2**: an element you generate must have a downstream
  consumer — in particular, **graded-stage diseases
  (`_generate_stage`) must have an entry in `STAGE_SEVERITY`** (the
  I10-class no-op prevention, enforced by
  `test_completeness_invariants.py`);
  (3) **C3**: acute diseases author `course_archetypes` +
  `complications` (the fallback is tuned for infection and is
  clinically incoherent for trauma / cardiology). Regression
  guard: `tests/unit/test_completeness_invariants.py`.

## 6. codes / locale / multilingual

**Binding spec:** [`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md) defines the YAML formats, the resolution functions, localization and the fallback rules. Every code-related change follows it; the bullets below are a summary.

- `codes/data/*.yaml`: **`en` is required**; sources are
  authoritative (CMS / NLM / WHO / JCCLS / MHLW). **Absolutely no
  fabrication of codes** — verify a new code against the NLM API /
  WHO browser before registering.
- When adding a diagnosis code, follow the "Diagnosis code
  coverage" procedure (`AGENTS.md`) and confirm
  `pytest tests/unit/test_diagnosis_code_coverage.py` is green.
- **JP output: every display / text / name is Japanese; US output:
  zero Japanese characters.** (The known exception is
  `KNOWN_JA_ONLY_FALLBACK_SECTIONS`; do not widen it on your own.)
  Watch for locale-dependent expressions in emergency numbers, etc.
  (a real example: "Call 119" leaked into English text — a guard
  test now protects against it).
- Condition / Procedure carry dual coding (local primary +
  interop). Numeric Observation emits both `referenceRange` and
  `interpretation`, and they are recomputed at output time.

## 6.5 Cross-cutting-logic location map (4 axes)

A one-page lookup for anyone asking "where does X live and
what is the entry point?". Each cross-cutting axis has a **single
canonical entry point** and is not re-implemented at call sites
(the §4 principle applied).

| Cross-cutting axis | Canonical entry (owner) | Convention / data source |
|---|---|---|
| **Data reference** (YAML / reference-data load) | Each module's `load_X()` (`@lru_cache` + `_HERE / _REF_DIR / _LOCALE` path constants + a Pydantic model checked at load via `load_validated_yaml`). Reach other-module `reference_data` through the owner's accessor only (§5). | Layer 1 = `modules/*/reference_data/` / `locale/` / `config/`. A cached loader's return value is a shared read-only object (mutation forbidden). |
| **Data generation** (RNG / physiology / severity) | RNG = `determinism.default_rng` seeded by `derive_sub_seed` + `ENRICHER_SEED_OFFSETS` or a named `seeding.py` function (labs = `panel_specimen_seed` / `individual_lab_seed`); stream-free draws = `determinism.sha_*`. Severity = `disease.severity.sample_severity`. Course = `clinical_course.select_archetype`. Physiology = `physiology.engine` (`initialize_state` / `derive_lab_values`). | Every RNG is seed-derived and deterministic (AD-16). Clinical values are driven from disease / lab YAML — never hard-coded in Python. `rng.choice(p=)` goes through `normalize_probabilities(p, fallback="raise")`. |
| **Code mapping** (internal name → standard code → display) | Internal name → standard code = `locale/<country>/code_mapping_*.yaml`. Country → code system = `system_key_for(kind, country)`. code → display = `display(system, code, lang) or <fallback>`. System URI = `get_system_uri(key)`. | `codes/data/*.yaml` (`en` required, international standards, locale-independent). Hard-coding or fabricating display strings / URIs / codes is forbidden. CIF holds codes only (AD-30). |
| **Multilingual** (i18n) | Country decision = `is_jp` / `is_us`; display language = `countries.lang_for(country)`. Display resolution follows the [code mapping and localization spec](code-mapping-and-localization-spec.md): `display(...)` for codes, `dual_slot_concept` / `system_coding` for FHIR codings, `vocab_display` for vocabularies. | Conversion is language-neutral (AD-44): enrichment produces English structured data; the LLM handles translation. **JP output: every display Japanese; US output: zero Japanese** (enforced by the audit's jp_language axis). |

The judgment of "is this unified?" runs through
`data-model-and-completeness-conventions.md` (severity) + §4 of
this document (canonical helpers) + the audit's silent_no_op axis.
The end-to-end implementation picture is in
`data-generation-walkthrough.md`.

## 7. Narrative layer (Stage 2) conventions

- Generator contract = the `NarrativeGenerator` Protocol
  (`types/document.py`). Injection into `NarrativePass` is
  **constructor-based** (hard-coding is forbidden).
- LLM path: `LLMNarrativeGenerator` → `apply_replacement_strategy`
  → `LLMService.complete_prompt()`. Fallback is the generator's
  responsibility (`complete_prompt` raises).
- **Prompts live only in `llm_service/prompts/{en,ja}/*.yaml`**
  (AD-40). Assembling prompt strings inside Python is forbidden.
- `DocumentTypeSpec` is YAML (`document_type_specs.yaml`) + registry
  validation (`frequency` / `stage2_strategy` /
  `llm_enabled_sections ⊆ composition_sections`).
- **Partial-version guard**: a `--patient-filter` run does not
  update `current` by default; overwriting an existing version
  requires `--merge-into-version` opt-in. Passing a filter to
  `regenerate-goldens` is forbidden forever.
- The gate for real LLM output is `check-narratives` (a 5-axis
  semantic check). Byte-diff applies only to template / mock.

## 8. Golden / test / verification gates

- Test suites: `pytest tests/unit` (not `-m unit` — not every unit
  file carries the marker) / `pytest -m integration` / `-m e2e` /
  `pytest tests/regression -m regression` (opt-in; narrative goldens
  byte-diff for every canonical profile, template + llm-mock).
- **AD-66 Rule 1**: whenever profile YAML or generation logic
  changes, run `regenerate-goldens` and **commit the YAML and
  goldens together**.
- **AD-66 Rule 2 + clinical-content review**: golden diffs are
  reviewed not only by categorising "is this the expected kind of
  change?" but by **reading the content for clinical validity** (a
  real example: a golden for a deceased-discharge patient had ICU
  vasopressor drips baked in as discharge prescriptions).
- **Byte-diff usage**: refactor PR = byte-identical required (FHIR
  NDJSON + narratives sha256 match. CIF structural allows only the
  known 2 wall-clock fields). New-feature PR = byte-diff
  intentionally broken; the gate becomes audit + goldens + real-
  output verification.
- **Include real-output grep in verification**: wiring / context
  changes must be verified by grepping a downstream renderer's real
  output over a real cohort (to catch broken sentences, placeholder
  residue, locale leakage). Green tests are not enough.
- `clinosim audit run -d <cohort>` (AD-60, the 4-axis audit) is the
  primary gate for new-feature PRs.

## 9. Silent-no-op defense checklist

Structurally prove that a new feature or fix "actually fires":

1. **Canonical constants** are defined once and imported by both
   writer and reader (ID prefixes, URIs, `HAI_TYPES`, etc.).
2. **Cross-validation at import / load time** turns typos and
   omissions into fail-loud errors.
3. Add equality_checks (firing proofs) to the audit's
   `lift_firing_proof`.
4. **"Fired" counters / observability**: fallbacks and skips are
   surfaced via counters + `manifest` / stderr (e.g.
   `generator_fallback_docs`; WARN when `eligible > 0` and `fired
   == 0`).
5. **No aspirational scaffolding**: registered-but-unconsumed code
   (a seed offset, a config field, a strategy value) must be
   **wired or removed**. Do not ship it "for later".
6. Precedents to remember: a flag read in only one venue; a
   case mismatch on a YAML key that silently disabled a whole
   feature; `getattr` on a dict producing one shared cache key;
   clinical errors baked into a golden ("Call 119" in English text,
   ICU drips as discharge prescriptions); starting work from a stale
   TODO without measuring.

## 10. FHIR builder (Layer 4) headlines

Detail: [`fhir-data-generation-logic.md`](fhir-data-generation-logic.md).
Bare minimum: CIF is read-only; display / URI / ID prefixes come
from a canonical source; builder registration goes through the
registry; both dict and dataclass paths must be tested; reference
integrity must hold (no dangling references).

---

## Reading order (for a new implementer)

1. This document (rules) and [`shared-helpers-catalog.md`](shared-helpers-catalog.md) (where the helpers are).
2. [`README.md`](README.md) (reading path) → `MODULES.md` (project map).
3. The binding spec of the domain you are changing (table at the top).
4. `docs/CONTRIBUTING-modules.md` (module HOW-TO).
5. `fhir-data-generation-logic.md` when writing a FHIR builder; `clinosim/modules/output/SPEC.md` when touching Stage 2 narratives.
6. The GitHub Issues board (see `docs/roadmap.md`) for open work.

Japanese counterpart: [`implementation-rules.ja.md`](implementation-rules.ja.md).
