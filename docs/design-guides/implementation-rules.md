# clinosim Implementation Rules — invariants every implementer must know

**Status:** Active (2026-07-03, established in session 32).
**Audience:** every implementer or implementation agent (Opus 4.7,
etc.) writing or modifying clinosim code.
**Positioning:** the **distilled version** of CLAUDE.md (full text)
and `docs/CONTRIBUTING-modules.md` (detailed HOW-TO). The rules
below apply without exception. Details, rationale, and precise
procedures live in the linked documents. When in doubt, apply the
four judgment axes: **data quality, clinical coherence,
maintainability (responsibility-decomposition points), conceptual
fit**.

---

## 0. Workflow discipline (before you write any code)

1. **Chain workflow (established, do not deviate)**: recon → design
   spec commit (`docs/history/specs-archive/`) → TDD implementation
   (test first) → independent verification → PR → compact
   adversarial review (5-lens, findings must be evidenced) → fix →
   whole suite green → merge.
2. **Scope discipline (★★★)**: no scope expansion after the spec is
   finalised. Findings outside scope are addressed only when they
   are "essential to data quality or clinical coherence"; otherwise
   they become **formal entries in `TODO.md`** (with context, file:
   line, and a fix proposal).
3. **Pre-work status audit**: do not take TODO / doc claims at face
   value; **verify empirically before implementing** (a concrete
   example: the α-min-3 "CRITICAL wiring gap" turned out to have
   been resolved two generations back. Counting the cohort output
   avoided a whole PR of wasted work).
4. **Do not narrate before observing**: never write "success" before
   you see the tool result. Show verification via execution output
   (test output, real-cohort grep, sha256).
5. **Commit conventions**: `feat(<chain>): ...` / `fix(<chain>
   adv-1): ...` / `refactor: ...` / `docs: ...`. Commit per task.
   Push and open the PR after verification is green.

## 1. Coding standards

- Python 3.11+ / ruff / mypy strict / line length 100.
- **In-code comments and docstrings are English.** User-facing docs
  follow each file's declared language (CONTRIBUTING and
  design-guides mix Japanese with English technical terms).
- **Types live only in `clinosim/types/`.** Defining a new dataclass
  or BaseModel inside module code is forbidden (YAML config =
  Pydantic BaseModel (AD-18); runtime = `@dataclass`).
- **Public API = only what a module's `__init__.py` exports.**
- Comments describe only "constraints the code cannot show". Do not
  write change history or self-evident explanations.

## 2. Architectural invariants (data flow)

| Invariant | Content |
|---|---|
| AD-17 | **CIF is the sole simulation output.** Format adapters (FHIR / CSV) read only from CIF. |
| AD-30 | **CIF holds codes only; no display text.** Display is resolved at output time via `clinosim.codes.lookup()`. |
| AD-65 | **Two-file separation: structural / narrative.** Stage 1 emits only the `ClinicalDocument` stub (`narrative=None`); the post-simulation `NarrativePass` writes into `narratives/<version>/`. Mixing narrative inline is forbidden. |
| AD-31 | FHIR is Bulk Data NDJSON (resource id is globally unique within its type; references resolve within one export). |
| AD-32 | `--end` = snapshot date. No event generation past that date; honour the in-progress-encounter semantics. |
| AD-55 / AD-56 | Modules write into `CIFPatientRecord.extensions[<module>]` (new typed fields on core types are Base-only). Extension goes through three registries (`register_bundle_builder` / `register_output_adapter` / `register_enricher`); the dispatch body itself is never edited. |
| AD-11 | **LLM calls go through `llm_service` only.** From the narrative layer, `LLMService.complete_prompt()` is the sole seam. Directly importing a provider SDK is forbidden. |

## 3. Determinism (AD-16 / AD-59) — absolute rules

- `random.random()` is forbidden. The RNG must always derive from a
  sub-seed of `numpy.random.Generator` (`simulator/seeding.py`:
  `derive_sub_seed` + registration under `ENRICHER_SEED_OFFSETS`;
  labs use `panel_specimen_seed` / `individual_lab_seed`).
- **`datetime.now()` / `date.today()` do not appear on the
  generation path.** (The remaining occurrences are TODOs in the
  determinism chain — adding more is forbidden.) Narrative
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

The same logic in two or more places is a violation. Always import
and use the helpers below:

| Purpose | Helper (definition site) |
|---|---|
| JP / US decision / display language | `is_jp(country)` / `is_us(country)` / `resolve_lang(country)` (`modules/_shared.py`). Hand-written `country == "JP"` comparisons are forbidden. |
| Country → code-system selection | `system_key_for(kind, country)` (`clinosim.codes`). Inline jlac10 / loinc branching is forbidden. |
| System URI | `get_system_uri(key)` (`clinosim.codes`). Hard-coding URI strings is forbidden. |
| code → display | `code_lookup(system, code, lang)`. Hard-coding display strings is forbidden. |
| Dict / dataclass dual read | `get_attr_or_key` (`_shared.py`) / `_o()` in FHIR builders. Adding new `isinstance(x, dict)` branches is forbidden. **Applies to every read path — cache keys, comparisons, branching** (lesson from C-1: `getattr` was used on a dict, so the whole cohort shared a single cache entry). |
| Dict / dataclass dual write | `set_attr_or_key(obj, name, value)` (single-field assignment) / `get_or_create_container(obj, name, factory)` (obtain-or-create a nested container and mutate directly). Adding new `isinstance(rec, dict): rec["x"]=v else: rec.x=v` branches is forbidden (session 37 dual-access sweep). |
| Probability vectors | `normalize_probabilities(p, fallback="raise")` (`_shared.py`) on every YAML-sourced `rng.choice(p=)`. |
| Lab-order classification | `classify_lab_specs` (`order/panel_grouping.py`). |
| Scenario / medication flags | Merge `scenario_flags_from_protocol` + `medication_flags_from_context` and pass **`**flags`**. Adding named-arg parameters is forbidden (J5 lesson). |
| **Severity sampling** | `sample_severity(protocol, person, rng)` / `sample_severity_category(...)` / `category_from_score(score)` (`disease/severity.py`, AD-67). Severity's canonical source is disease-YAML `severity.distribution × modifiers`. The locale-side `severity_beta` / `severity_minimum` have been removed — do not resurrect. Hard-coding the 0.3 / 0.7 category-↔-score boundaries at call sites is forbidden (`SEVERITY_SCORE_RANGES` is the single definition). |
| **JP Core / JP-CLINS profile URIs** (lesson from session 50 adv-1) | Quote the `Element.system.fixedUri` / `Element.fixedUri` in the spec's `StructureDefinition-*.json` directly. **Do not guess.** In session 50 we set `_JP_OBSERVATION_CATEGORY_SYSTEM = "http://jpfhir.jp/fhir/observation-category"` (a guess); the real spec is `http://jpfhir.jp/fhir/core/CodeSystem/JP_SimpleObservationCategory_CS`, so the URIs mismatched → the HAPI validator silent-no-op'd, invalidating a profile-slice-compliance fix over 2.47M records completely. Procedure: (1) `grep -A2 fixedUri` the relevant `StructureDefinition-*.json` under `iris4h-ai/jp_core/package/` (or a jpfhir.jp fetch) to find the slice's system URI, (2) define it as a module-level constant, (3) **always add a unit test that pins the URI, as in `tests/unit/output/test_fhir_jp_core_p14_slices.py`** (the guess-URI regression guard). The same rule applies to JP-eCheckup / SS-MIX2 profile URIs. |
| Imaging orders | `place_imaging_orders` (`order/engine.py`). |
| Drug protocol prefix stripping | `strip_protocol_prefix` (`_shared.py`; shared between FHIR and narrative). |
| LOS computation | `document/engine._compute_los_days` (including the in-progress proxy). |
| Locale display tables | The cached loaders in `locale/loader.py` (`load_med_terms_ja`, etc.). Opening raw YAML in Layer 4 is forbidden. |

If the same shared logic is needed in a second module, define it
once in `_shared.py` or the owner module and import from both.
**When a third consumer appears, import it — do not redefine.**

## 5. Loader / reference-data conventions

- Canonical path constants: `_HERE = Path(__file__).resolve().parent`
  / `_REF_DIR = _HERE / "reference_data"` / `_LOCALE = _HERE.parents[1] / "locale"`.
  Fragile `.parent.parent.parent` is forbidden. Directly pathing
  into another module's `reference_data` is forbidden (create an
  accessor on the owner module — e.g.
  `observation.microbiology.antibiotic_loinc_lookup`).
- `@lru_cache`: no-param → `maxsize=1`; `(country)` → 2. Hand-rolled
  sentinel caches are forbidden.
- **Fail-loud validation at import / load time (`_validate_*`) is
  mandatory.** A YAML that references external IDs (SNOMED, LOINC,
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

- `codes/data/*.yaml`: **`en` is required**; sources are
  authoritative (CMS / NLM / WHO / JCCLS / MHLW). **Absolutely no
  fabrication of codes** — verify a new code against the NLM API /
  WHO browser before registering.
- When adding a diagnosis code, follow the "Diagnosis code
  coverage" procedure (CLAUDE.md) and confirm
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

A one-page lookup for a new session asking "where does X live and
what is the entry point?". Each cross-cutting axis has a **single
canonical entry point** and is not re-implemented at call sites
(the §4 principle applied).

| Cross-cutting axis | Canonical entry (owner) | Convention / data source |
|---|---|---|
| **Data reference** (YAML / reference-data load) | Each module's `load_X()` (`@lru_cache` + `_HERE / _REF_DIR / _LOCALE` path constants + `_validate_X` at import). Reach other-module `reference_data` through the owner's accessor only (§5). | Layer 1 = `modules/*/reference_data/` / `locale/` / `config/`. A cached loader's return value is a shared read-only object (mutation forbidden). |
| **Data generation** (RNG / physiology / severity) | RNG = `derive_sub_seed` + `ENRICHER_SEED_OFFSETS` (labs = `panel_specimen_seed` / `individual_lab_seed`). Severity = `disease.severity.sample_severity`. Course = `clinical_course.select_archetype`. Physiology = `physiology.engine` (`initialize_state` / `derive_lab_values`). | Every RNG is seed-derived and deterministic (AD-16). Clinical values are driven from disease / lab YAML — never hard-coded in Python. `rng.choice(p=)` goes through `normalize_probabilities(p, fallback="raise")`. |
| **Code mapping** (internal name → standard code → display) | Internal name → standard code = `locale/<country>/code_mapping_*.yaml`. Country → code system = `system_key_for(kind, country)`. code → display = `code_lookup(system, code, lang)`. System URI = `get_system_uri(key)`. | `codes/data/*.yaml` (`en` required, international standards, locale-independent). Hard-coding or fabricating display strings / URIs / codes is forbidden. CIF holds codes only (AD-30). |
| **Multilingual** (i18n) | Country decision = `is_jp` / `is_us`; display language = `resolve_lang(country)`. Display resolution = `code_lookup(..., lang)` / `_localize_display`. JP fixed labels: `_fhir_localization` dictionary. | Conversion is language-neutral (AD-44): enrichment produces English structured data; the LLM handles translation. **JP output: every display Japanese; US output: zero Japanese** (enforced by the audit's jp_language axis). |

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

- Markers: `pytest -m unit` (~15 s) / `integration` (~12 min) /
  `e2e` (~4 min) / `regression` (opt-in; goldens byte-diff —
  template ×6 + llm-mock ×6).
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

## 9. Silent-no-op defense (the PR-90 class) checklist

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
6. Named precedents (mnemonic phrases to prevent recurrence):
   **J5** (a flag read in one venue only) / **PR-90** (a case-
   sensitivity mismatch on a YAML key silently no-op'd the whole
   lift) / **C-1** (`getattr` on a dict → degenerate cache key) /
   **Call 119 / ICU drip** (clinical errors baked into a golden) /
   **stale TODO** (starting work without measuring).

## 10. FHIR builder (Layer 4) headlines

Detail: [`fhir-data-generation-logic.md`](fhir-data-generation-logic.md).
Bare minimum: CIF is read-only; display / URI / ID prefixes come
from a canonical source; builder registration goes through the
registry; both dict and dataclass paths must be tested; reference
integrity must hold (no dangling references).

---

## Reading order (for a new implementation agent)

1. This document (invariants).
2. [`README.md`](README.md) (reading path) → `MODULES.md` (project
   map).
3. `docs/CONTRIBUTING-modules.md` (Layers 1-3 detailed HOW-TO).
4. `fhir-data-generation-logic.md` (Layer 4, when writing a
   builder).
5. `clinosim/modules/output/SPEC.md` (two-pass narrative — when you
   touch Stage 2).
6. The most recent chain context: `.session-resume-prompt.md` +
   each `deferred` section of `TODO.md`.

Japanese counterpart: [`implementation-rules.ja.md`](implementation-rules.ja.md).
