# clinosim — AGENTS.md

> **AI coding agents**: this is the canonical instructions file for automated
> coding agents working on clinosim. It follows the [AGENTS.md convention](https://agentmd.dev)
> and applies to all agents (Claude Code, Codex, Cursor, Gemini CLI, Copilot,
> ...). Non-agent contributors: read [`CONTRIBUTING.md`](CONTRIBUTING.md).
>
> Claude Code users may still reference [`CLAUDE.md`](CLAUDE.md); it is a thin
> pointer to this file kept for backward compatibility.

This file holds agent operating instructions only. The coding rules live in
[`docs/design-guides/implementation-rules.md`](docs/design-guides/implementation-rules.md)
and the binding specs it links; this file links to them instead of restating
them, so the rules have one source.

## Project overview

clinosim is a population-driven, physiology-based synthetic EHR data simulator.
See `README.md` (English) / `README.ja.md` (日本語) for the user-facing overview,
[`docs/architecture/adr-history.md`](docs/architecture/adr-history.md) for the
architecture decision records (ADRs; `DESIGN.md` is a pointer to it),
[`docs/roadmap.md`](docs/roadmap.md) (points at the GitHub Issues board) for the
roadmap, and each `clinosim/modules/<name>/README.md` for module-level reference.

## Quick navigation

| Looking for | Read |
|---|---|
| ★ Coding rules (start here before writing code) | [`docs/design-guides/implementation-rules.md`](docs/design-guides/implementation-rules.md) |
| ★ Which shared helper to use for X | [`docs/design-guides/shared-helpers-catalog.md`](docs/design-guides/shared-helpers-catalog.md) |
| ★ Binding spec for the area you are changing (codes, determinism, configuration, medications, labs, narratives, encounters) | [`docs/design-guides/README.md`](docs/design-guides/README.md) |
| ★ Documentation + code-quality policy | [`docs/design-guides/documentation-and-code-quality-policy.md`](docs/design-guides/documentation-and-code-quality-policy.md) |
| Project concept + pipeline catch-up | [`docs/design-guides/project-concept-and-design.md`](docs/design-guides/project-concept-and-design.md) |
| How data is generated (end-to-end walkthrough) | [`docs/design-guides/data-generation-walkthrough.md`](docs/design-guides/data-generation-walkthrough.md) |
| Module overview, dependency graph and enricher order | [`MODULES.md`](MODULES.md) |
| Scenario / medication flags (`causes_X` / `on_warfarin`) | [`SCENARIO_FLAGS.md`](SCENARIO_FLAGS.md) |
| Architecture decision records | [`docs/architecture/adr-history.md`](docs/architecture/adr-history.md) |
| Module author HOW-TO + PR verification guide | [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) |
| New module template (boilerplate) | [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md) |
| Roadmap | [`docs/roadmap.md`](docs/roadmap.md) (GitHub Issues board) |
| Audit-cycle workflow + by-design exclusion registry | [`docs/audit-cycles/README.md`](docs/audit-cycles/README.md) + [`docs/audit-cycles/by-design-registry.md`](docs/audit-cycles/by-design-registry.md) |
| Hospital configuration reference | [`docs/reference/hospital-configuration.md`](docs/reference/hospital-configuration.md) |
| LLM integration reference | [`docs/reference/llm-integration.md`](docs/reference/llm-integration.md) |

## Language conventions

- **Code**: Python 3.11+
- **Documentation and comment language pairing**: follow
  [`docs/design-guides/documentation-and-code-quality-policy.md`](docs/design-guides/documentation-and-code-quality-policy.md)
  §1 (documentation-file language pairing) and §4 (source-code
  comments — English default; Japanese only for JP-Core / JP-CLINS
  profile invariants, JLAC10 / JJ1017 / MEDIS code-system specifics,
  and verbatim quotes from Japanese authoritative sources). That
  policy is the canonical rule for every contributor; AGENTS.md does
  not duplicate it.
- **Communication with user**: Japanese.

### Canonical vocabulary (Issue #565)

Recurring naming choices whose drift shows up in review. Pick the
canonical form; treat the anti-patterns as review comments to fix.

| Concept | Canonical | Anti-patterns |
|---|---|---|
| Pass-through context object (parameter) | `ctx` | `context` |
| Hospital-operations dict (parameter loaded from `clinosim/config/hospital_operations.yaml`) | `hospital_ops` | `hospital_config`, `ops_config`, `hospital_cfg` |
| Term for silent behaviour bug (prose) | `silent-no-op` (hyphenated) | `silent-no-op` (spaced) |
| Verb for a derived value (function prefix) | `derive_X` | `compute_`, `calculate_`, `determine_` (see Issue #564) |
| Bundle-builder (returns `list[dict]`, registered in `_BUNDLE_BUILDERS`) | `_bb_X` | `_build_X` when the return type is `list` (see Issue #558) |
| Single-resource / fragment builder (returns `dict`) | `_build_X` | (no anti-pattern; keep) |

Docstring style: **Google-style** (Args / Returns / Raises sections when a
signature is non-trivial). NumPy-style is not used; the 4 legacy NumPy
docstrings were migrated in the same PR that added this section. Bare
prose is fine when the signature is self-explanatory.

Some canonical parameter names (e.g. `hospital_config` → `hospital_ops`)
have residual drift because the corresponding dataclass field carries the
old name; those are being cleaned up module-by-module (see linked issues).

## Country / locale convention

- **Default country = US.** CLI subcommands and the programmatic API default to
  `country="US"` when no value is supplied. Any fallback in code MUST default
  to US — never to JP. Anti-pattern: `x.get(country_key) or x.get("japan", {})`
  or `x if is_us(country) else "JP"` (both invert the convention).
- **JP is opt-in** via explicit `--country JP` (CLI) or `country="JP"` (API).
  JP-specific modules — JP Core / JP-CLINS profile application, JCCLS
  reference ranges, JST (`+09:00`) timestamp appenders, MHLW ICD system
  routing, MEDIS code emission, 保険者番号 (insurer number) lookup, JP-specific display strings —
  MUST be gated behind `is_jp(country)` from `clinosim.countries` and
  MUST no-op on non-JP cohorts.
- **Future US-specific profile support** (US Core / USCDI) will be gated behind
  `is_us(country)` in the same manner. The default cohort (no `--country`)
  emits generic FHIR R4; explicit `--country US` will additionally apply US
  Core once implemented.
- **Fallback direction**: use `x if is_jp(country) else "us"`, not
  `x if is_us(country) else "jp"`. There is no automated pre-commit / CI
  grep for inverted `else "japan"` / `else "JP"` fallbacks — catch them in
  review.
- **Locale-gate tests**: there is no dedicated cohort-wide "no JP literals in
  US output" regression test. Locale gating is pinned per emit site by unit
  tests (e.g. `tests/unit/test_jp_clins_profile_emit.py::test_us_bundle_has_no_clins_profile`);
  add the same kind of US-side assertion when you add a JP-only emit path.

## Coding rules

Follow [`implementation-rules.md`](docs/design-guides/implementation-rules.md)
(Python 3.11+, ruff with line length 120, mypy, types in `clinosim/types/`,
public API = `__init__.py` exports, determinism, canonical helpers, loader
conventions, verification gates). Before writing any small utility, look it
up in the [shared-helpers catalog](docs/design-guides/shared-helpers-catalog.md).
Every change to codes, display text or localization follows
[`code-mapping-and-localization-spec.md`](docs/design-guides/code-mapping-and-localization-spec.md);
every change that draws a random number or derives a seed follows
[`determinism-and-rng-spec.md`](docs/design-guides/determinism-and-rng-spec.md).

## Architecture rules

The invariants an agent most often needs while editing; each links to its
normative source.

### Data flow & ownership

- **CIF is the only simulation output** (AD-17) — format adapters (FHIR, CSV) read CIF, never simulation internals.
- **CIF stores codes only, not display text** (AD-30) — e.g. `ClinicalDiagnosis.admission_diagnosis_code` + `_system`, no `_name`. Display is resolved at output time with `clinosim.codes.display(...)` and an explicit fallback. Drug names in `Order.display_name` / `MAR.drug_name` are English (a pragmatic exception).
- **Code is the truth** — internal test names (e.g. `"WBC"`) map to standard codes (LOINC) via `locale/<country>/code_mapping_*.yaml`; display text comes from `clinosim/codes/data/<system>.yaml`.
- **LLM calls only via `llm_service`** (AD-11) — narrative code calls `LLMService.complete_prompt()`; no other module calls a provider API.

### Two-pass CIF (AD-65)

Normative: [`narrative-and-document-generation-spec.md`](docs/design-guides/narrative-and-document-generation-spec.md) and `clinosim/modules/output/SPEC.md`.

- Structural CIF (`cif/structural/patients/<enc>.json`, immutable after Stage 1) and narratives (`cif/narratives/<version>/documents/<enc>/<doc>.json`, versioned in Stage 2) are always separate files. Never write narrative content inline.
- The `document` enricher (POST_ENCOUNTER) creates only a `ClinicalDocument` stub (metadata, author, encounter binding, `narrative=None`). Narrative text is generated after the simulation by `TemplateNarrativePass` / `LLMNarrativePass` (`clinosim narrate`).
- FHIR builders read narrative only through `doc.narrative.sections` / `doc.narrative.text` (`CIFReader(narrative_version="current")` merges the layers).
- The `NarrativePass` walk order (per `(doc_type, language)` group, sorted patients) is tuned for the prompt cache — do not change it.
- All template narrative rendering goes through `clinosim/modules/document/narrative/`. A `DocumentTypeSpec` restricted to some encounter types must list them in `encounter_types_supported` — an empty tuple means *all* types.

### Canonical patient profile goldens (AD-66)

- **Rule 1**: editing `tests/fixtures/patient_profiles/<name>.yaml` requires regenerating its goldens (`clinosim regenerate-goldens --profile <name>` and `--profile <name> --provider mock`) and committing both together.
- **Rule 2**: after an intentional template change, a golden diff in profiles you did not expect to change is a regression signal — investigate before committing. "I regenerated everything, so it is green" hides regressions.
- **Rule 3**: CI runs the regression suite on every PR (`Narrative regression (goldens)` job). Any change that moves template or mock-LLM narrative output — simulation, catalog and localization changes included — regenerates the affected goldens in the same PR and explains the diff in the PR description. PRs that move goldens are serialized (rebase, then regenerate).

### Module independence and extension points (AD-55 / AD-56 / AD-58)

- A module under `clinosim/modules/` depends only on `clinosim/types/`, `clinosim/codes/`, `clinosim/locale/`, the top-level helpers (`clinosim/determinism.py`, `seeding.py`, `datafiles.py`, `countries.py`, `age_bands.py`) and the modules listed in its README's Dependencies section.
- **Near-essential data → Base** (types / population / observation / simulator / output); **specialised data → a module**, one theme per module. Always-on modules are the near-essential clinical cascade (`device` → `hai` → `antibiotic`, `imaging`, `allergy`, `document`, `triage`, `nursing`), registered with `enabled=lambda c: True` and a no-op when their input is empty.
- Modules write to `CIFPatientRecord.extensions[<module>]`; only Base adds typed fields to core types.
- Extend through the registries, never by editing the dispatch body: `register_bundle_builder()` (a FHIR resource), `register_output_adapter()` (an output format), `register_enricher()` in `simulator/enrichers.py::register_builtin_enrichers` (a post-population / post-encounter / post-records pass).
- **Enricher stages**: `POST_POPULATION` (before simulation), `POST_ENCOUNTER` (per encounter, after the daily loop, inside the encounter simulator — for passes that depend on the clinical course and feed the same encounter) and `POST_RECORDS` (after all records — for passes that read patient-wide history). The registered stage and order of every enricher are listed in [`MODULES.md`](MODULES.md); `register_builtin_enrichers` is the source. Do not change existing orders; a new POST_ENCOUNTER module whose output `document` reads registers before `document` (order 95).
- New enrichers register a 16-bit hex-ASCII offset in `clinosim/seeding.py::ENRICHER_SEED_OFFSETS` (duplicates fail at import).
- Every order stored in `CIFPatientRecord.orders` has a non-empty `encounter_id` before the record is returned.
- New-feature verification gate: `clinosim audit run -d <cohort>` (AD-60; structural / clinical / jp_language / silent_no_op axes). Modules register their checks in `clinosim/modules/<name>/audit.py` via `register_audit_module(ModuleAuditSpec(...))`; closed-form `lift_firing_proof` checks prove a feature actually fires.

### Code systems and locale data

- `clinosim/codes/` holds international code systems (locale-independent): every code in `codes/data/*.yaml` has an `en` entry from an authoritative source (CMS, NLM, Regenstrief, AMA, WHO, JCCLS, MHLW). Never fabricate a code.
- `clinosim/locale/` holds only culture- or country-dependent data (names, addresses, demographics, formatting, reference ranges, internal-name → code mappings). Do not recreate terminology files there.

### FHIR R4 output

Normative: [`fhir-data-generation-logic.md`](docs/design-guides/fhir-data-generation-logic.md) (subordinate to the code-mapping spec on display rules) and [`encounter-lifecycle-and-export-spec.md`](docs/design-guides/encounter-lifecycle-and-export-spec.md).

- **Bulk Data** (AD-31): one NDJSON per resource type + `manifest.json`; resource ids unique within their type; every reference resolves within the export. Facility masters (Organization / Location / Device) are built once by `fhir_r4/encounters/facility.py` into the regular NDJSON files.
- **Codings** go through `dual_slot_concept` / `system_coding`: English-only systems (LOINC, SNOMED CT) keep the English `coding.display`, the local label goes in `.text`. Condition and Procedure carry dual coding (local primary + interop). Never emit `display == code`. `code.text` of a Condition uses the `condition-short-name` code system.
- **Medication text**: strip protocol prefixes with `strip_protocol_prefix()`; `medicationCodeableConcept.text` is the drug name only.
- **Numeric Observations** carry both `referenceRange` and `interpretation`, recomputed at output time and consistent.
- **Locale**: JP output has every `display` / `text` / `name` in Japanese except English-only codings; US output contains no Japanese characters.
- **JP Core / JP-CLINS / JP-eCheckup / SS-MIX2 URIs** are quoted from the spec's `fixedUri`, defined once as a constant and pinned by a unit test (`tests/unit/output/test_fhir_jp_core_p14_slices.py`). A guessed URI makes validators silently skip the slice.
- **Sex-locked ICD-10**: every Condition dispatch site calls `clinosim.simulator.sex_gating.is_sex_locked_for(code, patient_sex)` (table: `clinosim/simulator/reference_data/icd10_sex_restrictions.yaml`); when every candidate is locked, fall back to `UNRESOLVED_DIAGNOSIS_ICD` (R69). Never inline a sex-restriction dict.
- **Snapshot** (AD-32): `--end` is the snapshot date; no life event after it; inpatients still admitted have `Encounter.status = "in-progress"`, no discharge, data up to the snapshot day and an active primary Condition. Builders read `ctx.snapshot_date` (never re-parse `cif/metadata.json`) and sample dates at or before it; the bundle-finalize filter (`_drop_entries_after_snapshot`) is a safety net, not a substitute.
- **Allergy assertion**: every patient carries at least one `AllergyIntolerance` — a real allergen or SNOMED `716186003` "No known allergy". Tunables live in `clinosim/modules/allergy/reference_data/allergens.yaml`.
- **Anthropometrics**: height, weight, BMI (and head circumference up to age 3) at every encounter; pediatric medians from `clinosim/modules/population/reference_data/anthropometric_reference.yaml`; per-encounter noise from `clinosim.determinism.sha_normal` (never the master RNG). BMI is computed from the emitted height and weight.
- **JP long-term-care level** Observations emit only for patients meeting `care_level.yaml::eligibility_gates` (age ≥ 65, or 40–64 with a designated condition).

## Testing

- `pytest tests/unit` — unit tests (use the path, not `-m unit`: not every unit file carries the marker).
- `pytest -m integration` — module chain tests.
- `pytest -m e2e` — golden file comparison.
- `pytest tests/regression -m regression` — narrative golden byte-diff (opt-in locally; runs in CI).
- Before pushing: `ruff check`, `ruff format --check`, `mypy clinosim/` and the unit tests.

## Development workflow — Issue → PR → Merge

**Never push directly to master.** Fixes / features must always go through a PR/merge.
The full contributor workflow (fork + branch, DCO signoff, tests, CI
gates, merge policy) lives in
[`CONTRIBUTING.md`](CONTRIBUTING.md#workflow) — read that first.

AGENTS-specific additions on top of the contributor workflow:

- **Commit trailers**: use the DCO `Signed-off-by:` only. Per the
  2026-10-15 maintainer policy, agent-attribution trailers
  (`Co-Authored-By: Claude ...`, `Claude-Session: ...`) are
  **not** added to commits or PR / Issue bodies — the full git
  history has been rewritten to strip these lines, and new work
  must not re-introduce them.
- **Adversarial review** (recommended for large chains): run
  `/code-review` on the PR and add fix commits before merging.
- **scope-discipline**: 1 PR = 1 topic (split cross-cutting work such as a silent-drop fix /
  lint sweep into separate PRs). When advancing multiple chains, use a separate branch +
  separate PR per chain.

### ★ Don't stall waiting for CI — work on another Issue on another branch in parallel

CI takes 10-15 minutes when it includes the integration shards. **Never wait idle in the meantime.**
After opening a PR, return to `master` and **start the next Issue on a separate branch**.

```bash
# Issue A: implement → push → open PR (CI starts running here)
git switch -c fix/<A>-<slug> master
# ... implement ...
git commit --signoff -m "..." && git push -u origin fix/<A>-<slug>
gh pr create --base master ...

# Move on to Issue B without waiting for CI
git switch master && git pull --ff-only origin master
git switch -c fix/<B>-<slug>
# ... implement ...

# Once A's CI is green, merge it, update master, then continue with B
gh pr merge <A's PR number> --rebase --delete-branch
git switch master && git pull --ff-only origin master
```

**Conditions for Issues that may run in parallel**:

- **The files they touch must not overlap.** Before starting, grep the files and symbols
  each Issue touches and check for overlap. If they overlap, **do not parallelize; do them in order**
  (known dependencies are recorded in `docs/roadmap.md` → GitHub Issues board)
- **Never parallelize Issues that depend on each other.** Example: `#468` → `#466` both
  handle the discharge time in the same `inpatient.py`, so they must be done in order

**When master advances, rebase your working branch**:

```bash
git switch fix/<B>-<slug>
git rebase master          # a conflict means the overlap judgment was wrong
```

**Some moments do call for waiting**: the final check right before a merge, and **right before an
irreversible operation** (`gh issue delete` / force push). There, re-measure right before executing
that the state has not changed. Because parallel work may have moved the state, confirm that **the
HEAD at approval time and the HEAD at merge time are identical**.

### ★ Gate on CI with `scripts/wait-pr-ci.sh` before `gh pr merge`

On 2026-10-11, `gh pr checks <N> --watch --fail-fast` was observed **returning exit 0 for a
PR in FAILURE** on 4 consecutive PRs (root cause unconfirmed: one of gh CLI race /
polling miss / gate not run). On a repo without branch protection, `gh pr merge --auto --rebase`
merges immediately without waiting for CI, so auto-merging without a reliable CLI-side gate
leaves a risk of breaking master.

Therefore **you must always run the repo's deterministic polling gate before merging**:

```bash
# Open PR → wait for CI to finish → merge if the gate passes
scripts/wait-pr-ci.sh <PR>  # exit 0: all required checks SUCCESS, exit 1: at least one failed
gh pr merge <PR> --auto --rebase
```

`wait-pr-ci.sh` polls `statusCheckRollup` itself, excludes check names containing
`(?i)informational`, and exits 0 only after confirming that every required check is COMPLETED and
not FAILURE/CANCELLED. It does not depend on gh CLI streaming behavior.

**hotfix exception**: a production blocker (all CI failing / silent-drop detected) may be
pushed directly to master, but you must leave a post-hoc Issue + explanatory comment
within the same session.

## When modifying a module

1. Read the module's `README.md` first
2. Read the binding spec of the area you are changing ([`docs/design-guides/README.md`](docs/design-guides/README.md))
3. Make changes
4. Check the dependency tree in [`MODULES.md`](MODULES.md) — verify downstream impact
5. Update the module's `README.md` (and `README.ja.md`) if its API, files or data changed
6. Update `clinosim/types/*.py` if shared data types changed
7. If adding a new code, add it to `clinosim/codes/data/<system>.yaml` with at least an `en` field
8. Run tests: `pytest tests/unit -x -q`

## Key directories

```
clinosim/
  codes/           <- International code systems (locale-independent, EN-first)
    data/          <- icd-10-cm.yaml, loinc.yaml, rxnorm.yaml, ...
    loader.py      <- display() / get_system_uri() / system_key_for()
  locale/          <- Country/culture-specific data (names, addresses, ranges, code mappings)
    jp/, us/, shared/
  config/          <- Hospital config YAML (50-bed, 10-bed, 200-bed) + LLM config
  types/           <- Shared data type definitions (Pydantic / dataclass)
  determinism.py   <- Bit-reproducible generator + stream-free sha_* draws
  seeding.py       <- Sub-seed derivation + ENRICHER_SEED_OFFSETS
  datafiles.py     <- The one YAML reader (+ model validation)
  countries.py     <- is_jp / is_us / lang_for
  modules/         <- Functional modules (one package per module, each with README)
    output/        <- CIF -> format adapters; fhir_r4/ package with per-theme builder subpackages
  simulator/       <- Top-level orchestration (run_beta, run_forced, CLI)
    phases/        <- Forward month loop (_forward_loop.py) + per-phase schedule/dispatch
    enrichers.py   <- Enricher registry for Base / module passes (AD-56)
tests/             <- unit / integration / e2e / regression
```

## Hospital configuration

Each hospital is defined by a YAML in `clinosim/config/hospital_*.yaml`:

- `hospital_operations.yaml` — 50-bed community hospital (default)
- `hospital_small.yaml` — 10-bed clinic
- `hospital_large.yaml` — 200-bed regional hospital (full service)
- Custom configs supported via `--hospital-config PATH`

Required fields: `recommended_population`, `available_departments`, `department_rollup`, `wards`, `ward_capacity`, `resource_capacity`, `staffing`.

The `available_departments` list determines which physicians get generated. The `department_rollup` map resolves granular specialties (e.g., pulmonology) to available departments (e.g., internal_medicine) for hospitals that don't have all sub-specialties.

### Known limitation — bed capacity is advisory, not enforced (#1132)

`resource_capacity.inpatient_beds` is declared per hospital, but the
simulator's inpatient dispatch does not gate admissions on the current
concurrent-inpatient count. Life events are processed chronologically
and admitted regardless of remaining bed capacity — the concurrent
count can therefore exceed the declared bed count (a 5-year US
p=10k run peaked at 176 concurrent inpatients against 50 declared
beds).

The `bed_occ=NN%` line in the simulator log reports occupancy against
a smoothed telemetry denominator (not the raw declared count), so a
99 % `bed_occ` value coexists with concurrent > capacity.

**Impact on downstream analytics**: any bed-capacity-based
denominator (utilization %, HAI-per-bed-day, staffing-per-bed ratio)
should treat the sim's inpatient-day counts as if the hospital had
elastic capacity, not enforced 50 beds. Alternatively, treat concurrent
> capacity as an ED-boarding / transfer-out proxy.

Full queueing / transfer / diversion model is future work per issue
#1132 (see the follow-up META for scoping into decomposed sub-issues).

## LLM setup

An LLM is **not required** for structural data or template narratives.
For LLM narratives (`clinosim narrate --provider ...`), the default config is
local Ollama (`clinosim/config/llm_service.yaml`); AWS Bedrock and a remote
GPU over SSH have their own configs (`llm_service.bedrock.yaml`,
`llm_service.sakura.yaml`). Setup steps: [`docs/reference/llm-integration.md`](docs/reference/llm-integration.md),
[`docs/bedrock_setup.md`](docs/bedrock_setup.md).

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
`tests/unit/test_diagnosis_code_coverage.py`. Diagnosis codes reach FHIR Conditions from
**three sources** — all covered by the test: (1) disease `icd_codes` (primary + variants),
(2) encounter `icd10_code`, (3) the built-in differential/progression tables in
`modules/diagnosis/reference_data/builtin_differentials.yaml` (`differentials[*].icd` +
`diagnosis_progression` codes) (working/differential diagnoses). For each new/changed code
`C` in any of these, verify it vs an authoritative source (NLM ICD-10-CM API
`clinicaltables.nlm.nih.gov/api/icd10cm`, WHO ICD-10 browser `icd.who.int/browse10`) — **never
fabricate** — then:

- **US billable**: if `C` is a valid billable ICD-10-CM leaf, add it to `codes/data/icd-10-cm.yaml`
  (`en` + `ja`). If `C` is a non-billable category/header or WHO-only (e.g. `I21.2`, `I50.0`,
  `N30.9`), add a `locale/us/code_mapping_diagnosis.yaml` entry `C → <billable leaf>` and register the
  leaf in `icd-10-cm.yaml`.
- **JP (WHO)**: `locale/jp/code_mapping_diagnosis.yaml`'s mapping of `C` (else `C`) must be a **true WHO ICD-10 code
  (3-4 char)** present in `codes/data/icd-10.yaml`. If `C` is ICD-10-CM granularity (5-7 char,
  7th-char extension, `X` placeholder — e.g. `A41.01`, `S06.0X0A`), add a jp map entry folding
  it to its WHO parent (`A41.01 → A41.0`) and register the WHO code in `icd-10.yaml`. JP does NOT
  emit CM-granularity codes nor fall back to `icd-10-cm.yaml` (enforced by
  `test_jp_never_emits_cm_granular_code` + `test_icd10_who_file_has_no_cm_granular_codes`).

Run `pytest tests/unit/test_diagnosis_code_coverage.py` — green means coverage is complete.

## Encounter (ED/outpatient) protocol YAML files

Located at `clinosim/modules/encounter/reference_data/`. 51 conditions covering ED visits and outpatient encounters.

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

- ❌ **Never store display text in CIF.** CIF contains codes + system keys; display is resolved at output time.
- ❌ **Never hardcode FHIR system URIs.** Use `clinosim.codes.get_system_uri(system_key)`.
- ❌ **Never add a code without an `en` entry.** English is required.
- ❌ **Never use `random` or `numpy.random.default_rng`.** Use `clinosim.determinism.default_rng` with a seed from `clinosim/seeding.py`, or a stream-free `sha_*` draw.
- ❌ **Never re-implement a shared helper.** Look it up in the [shared-helpers catalog](docs/design-guides/shared-helpers-catalog.md).
- ❌ **Never call LLM APIs from outside `llm_service`.**
- ❌ **Never put a shared data type inside module code.** Types used by more than one module live in `clinosim/types/`.
- ❌ **Never duplicate locale-specific data and code-system data.** Code systems go to `codes/`, culture data goes to `locale/`.
