# clinosim Development Guidelines

## Project overview

clinosim is a population-driven, physiology-based synthetic EHR data simulator.
See `README.md` (English) / `README.ja.md` (日本語) for user-facing overview, `DESIGN.md` for full architecture (ADRs), `TODO.md` for roadmap, and each `modules/<name>/README.md` for module-level reference.

## Quick navigation

| Looking for | Read |
|---|---|
| Module overview (22 modules at a glance) | [`MODULES.md`](MODULES.md) |
| Scenario / medication flags (`causes_X` / `on_warfarin`) | [`SCENARIO_FLAGS.md`](SCENARIO_FLAGS.md) |
| Architecture + ADR table (55+ entries) | [`DESIGN.md`](DESIGN.md) |
| Module author HOW-TO + PR verification guide | [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) |
| New module template (boilerplate) | [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md) |
| Roadmap | [`TODO.md`](TODO.md) |

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

### Two-pass CIF generation invariant(AD-65, 2026-07-02, session 28)

- **CIF は structural + narrative の 2 層 file 分離**:`cif/structural/patients/<enc>.json`
  (構造化データ、Stage 1 で immutable)と `cif/narratives/<version>/documents/<enc>/<doc>.json`
  (narrative、Stage 2 で version 化可能)を **必ず file-level 分離**。inline 混在禁止。
  session 25/26/27 で drift した過去実装から復元、SPEC.md `Stage 2: Narrative Generation`
  節が canonical。
- **`document_enricher`(POST_ENCOUNTER)は `ClinicalDocument` stub のみ生成**:metadata +
  author + encounter binding + `narrative=None`。narrative content(text / sections /
  facts_used)を populate 禁止。populate すると Stage 2 差替時 silent-no-op risk。
- **narrative は post-simulation two-pass で生成**:`TemplateNarrativePass.run(cif_dir,
  version_id)` は structural CIF を read → patient profile + labs + conditions +
  medications + scenario_spine を input として narrative を導出 →
  `narratives/<version>/documents/<enc>/<doc>.json` 書出。simulation loop 中の
  narrative content 生成禁止。α-min-1 Task 15 で SPEC.md 元設計から drift、
  AD-65(session 28)で復元。
- **`NarrativePass` walk 順序は (doc_type, language) group 単位**:同 prompt prefix を
  共有する batch 単位で patient を逐次処理 → Bedrock prompt cache(5 分 TTL)hit rate
  最大化。LLMNarrativePass(β-JP-1)は同 base class を継承 = drop-in で cache-friendly。
- **FHIR builders は `doc.narrative.sections` / `doc.narrative.text` 経由必須**:
  `ClinicalDocument` の flat field(`doc.text` / `doc.sections`)は AD-65 で削除、
  wrapper `ClinicalDocumentNarrative` に集約。`CIFReader(narrative_version="current")`
  が structural + narrative を merge して `doc.narrative` を fill、builders は
  wrapper 経由のみ。

### Module independence

- Each module under `clinosim/modules/` can only depend on `clinosim/types/`, `clinosim/codes/`, `clinosim/locale/`, and other modules listed in its `README.md` Dependencies section.
- **LLM calls only via `llm_service`** (AD-11) — no other module may call Ollama or Anthropic APIs directly.
- **Deterministic with seed** (AD-16) — each module creates its own `numpy.random.Generator` from a sub-seed. Never use `random.random()` or shared global state.
- **Per-order lab RNG isolation** (AD-59) — every lab order (panel children AND individual scalar orders) draws specimen-rejection / hemolysis / technician / noise from a per-order sub-rng (`simulator/seeding.py:panel_specimen_seed` / `individual_lab_seed`), NOT the patient-scoped master RNG. When extending `derive_lab_values` with a new analyte or adding a `{test:"X"}` order to a disease/encounter YAML, route any per-lab RNG draw through these helpers so YAML edits cannot shift unrelated patients' cohorts. Guard: `tests/integration/test_individual_lab_isolation.py`.
- **`derive_lab_values` scenario flags** — disease YAMLs declare `causes_X: true` flags (e.g. `causes_myocardial_injury`, `causes_vte`) that lift specific labs at the lab-derive step (no state mutation; AD-57 BNP-pattern surgical). Always read flags via `physiology.engine.scenario_flags_from_protocol(protocol)` and pass with `**flags` to `derive_lab_values`. Never add a fourth `flag=value` named-argument at a call site — the helper is the single edit point so adding a new flag automatically reaches inpatient / emergency / outpatient. The J5 wiring defect (PR Phase 2a, 2026-06-24) showed what happens when this rule is violated: `causes_myocardial_injury` was only read in `inpatient.py` Pass-1, so ED-route MI patients silently produced type-2 troponin only.
- **`derive_lab_values` medication flags** (Phase 2b, 2026-06-24) — medication-driven lab couplings (e.g. `on_warfarin` → therapeutic PT_INR) are detected via the sibling helper `physiology.engine.medication_flags_from_context(patient, medication_orders, admission_date, current_day)`. Call sites merge BOTH dicts: `flags = {**scenario_flags_from_protocol(protocol), **medication_flags_from_context(...)}` and splat as `**flags` to `derive_lab_values`. Same J5-prevention rationale — adding a new medication coupling (steroid → glucose, diuretic → K, antibiotic → CRP) extends the helper once and reaches inpatient / emergency / outpatient / inpatient-unknown-condition through the merge pattern. ED / outpatient pass `medication_orders=None / current_day=None`; only the chronic-meds detection runs. DOAC (apixaban / rivaroxaban / edoxaban / dabigatran) is intentionally NOT detected for INR — clinical practice does not monitor INR for DOAC, and modeling DOAC INR lift would be clinically misleading.
- **`classify_lab_specs` helper** (PR1, 2026-06-29) — lab order generation in `place_admission_orders` and `place_daily_lab_orders` MUST go through `clinosim.modules.order.panel_grouping.classify_lab_specs` so panel members share a single `ordered_datetime` + `panel_key`. Never inline a panel-detection if/elif at the call site; the helper is the single edit point so adding a new panel to `lab_panel_groups.yaml` automatically reaches all ordering sites. Companion to `scenario_flags_from_protocol` and `medication_flags_from_context` sibling pattern (AD-61).
- **`_o(order, name, default)` dual-access** (PR1, 2026-06-29) — FHIR builders reading Order objects MUST use the `_o()` helper (wrapping `clinosim.modules._shared.get_attr_or_key`) to support BOTH dict (production JSON-deserialized CIF) AND Order dataclass (test fixtures). The 4-6 line `isinstance(order, Order) ... elif isinstance(order, dict) ...` branching pattern is a PR-90 silent-no-op risk. New FHIR builder reading CIF Orders MUST exercise BOTH paths in unit tests + add a subprocess integration smoke test exercising the production dict path.
- **Imaging chain DRY rule** (Tier 1 #2, AD-62, 2026-06-30) — multi-view → multi-series expansion logic lives in `clinosim/modules/imaging/engine._expand_views_to_series`. Disease YAML `imaging_orders[].views` carries view labels; the enricher reads `modalities.yaml:default_views_by_body_site` for empty-views fallback. New imaging order calls MUST go through `clinosim.modules.order.engine.place_imaging_orders(protocol, patient_id, encounter_id, admission_time, rng)` — never set `imaging_modality` / `imaging_body_site_code` / `imaging_views` directly at a call site. Sibling to `scenario_flags_from_protocol` / `medication_flags_from_context` / `classify_lab_specs` — single edit point for adding modality / view kinds or body site display text. **Encounter_id invariant**: ALL orders stored in `CIFPatientRecord.orders` MUST have `encounter_id` non-empty before the record is returned. The `_simulate_unknown_condition` bug (2026-06-30) showed that omitting the `encounter_id` back-fill loop causes `_fhir_service_request._build_sr_skeleton` to `AssertionError` at FHIR export time on any cohort with unknown-condition patients.
- **Narrative generation DRY rule** (Tier 1 #3, AD-63, 2026-07-01) — all template-based narrative rendering for clinical documents MUST go through `clinosim/modules/document/narrative/` (`TemplateNarrativeGenerator`). No other module may render narrative templates directly (J5-pattern prevention: a single edit point ensures a new document type or section template reaches all encounter venues and document format types). New Stage 1 template work uses `clinosim/modules/document/` only. (Legacy `narrative_generator.py` + `document_generator.py` were deleted in Task 15; the Stage 2 LLM narrative path is deferred to β-JP-1.)
- **`ClinicalDocument.sections` + `format_type` field invariant** (Task 8 fix, Tier 1 #3, 2026-07-01) — `ClinicalDocument` MUST carry both `sections: dict[str, str]` (section name → text) and `format_type: str` (dispatch key: `"free_text"` or `"composition"`) at every emission site in `clinosim/modules/document/engine.py`. The CIF→FHIR no-drop invariant (spec §3.4) requires that Composition.section[] can be reconstructed from CIF without re-parsing `raw_text`. Omitting `sections` is a silent no-op: `_fhir_composition.py` builder would emit `"section": []` (FHIR R4 cardinality violation) with no error. Omitting `format_type` causes the builder dispatch to silently default to free_text, emitting DocumentReference instead of Composition with no error. Rule: sections is authoritative for COMPOSITION builders; raw_text (joined sections) is for FREE_TEXT / DocumentReference only.
- **`document` module always-on Module** (Tier 1 #3, AD-63, 2026-07-01) — `clinosim/modules/document/` is the 6th always-on Module (`enabled=lambda c: True`, POST_ENCOUNTER order=95). It produces `ClinicalDocument` records in `record.documents` (typed field on `CIFPatientRecord`) and `ClinicalImpressionRecord` records in `extensions["clinical_impressions"]` for all inpatient/ICU/rehab encounters. No-op for outpatient/ED encounters and for non-inpatient patients. The sibling `allergy` module (POST_POPULATION order=10) enriches `PersonRecord.allergies` and is a prerequisite for correct AllergyIntolerance FHIR emission but is NOT a direct input to the `document` enricher (both read CIF independently).
- **`nursing_assignment` naming convention** (Tier 1 #3 α-min-2, AD-64, 2026-07-01) — `clinosim/modules/nursing/` contains TWO distinct enrichers registered in DIFFERENT stages: (1) `nursing_enricher` (POST_ENCOUNTER order=94) = primary nurse assignment to inpatient/ICU/rehab encounters, writes `EncounterRecord.primary_nurse_id`, consumed by `_fhir_care_team.py`. (2) The observation-layer nursing flowsheet enricher (POST_RECORDS order=20) = NEWS2/GCS/Braden/Morse scores. When referencing this module in code comments, use `nursing_assignment` for (1) and `nursing_flowsheets` for (2) to prevent confusion. The `nursing` entry in `MODULES.md` POST_ENCOUNTER section refers to (1); the POST_RECORDS section refers to (2).
- **`DocumentTypeSpec.encounter_types_supported` invariant** (Tier 1 #3 α-min-2, AD-64, 2026-07-01) — every `DocumentTypeSpec` that should be restricted to specific encounter types MUST declare an explicit `encounter_types_supported` allowlist. An EMPTY tuple means "matches ALL encounter types" (backwards-compat default), NOT "disabled". α-min-1 specs (ADMISSION_HP / PROGRESS_NOTE / DISCHARGE_SUMMARY) had empty tuples originally, which would have leaked inpatient documents into outpatient/ED encounters if outpatient.py and emergency.py called POST_ENCOUNTER enrichers. Task 10 fix (α-min-2): all α-min-1 specs now carry explicit `[inpatient, icu, rehab_inpatient]` allowlists. Any new document spec that applies to only one encounter type MUST declare it explicitly — never rely on the empty-tuple fallback for inpatient-only specs.
- **CareTeam 2-name scope invariant** (Tier 1 #3 α-min-2, AD-64, 2026-07-01) — `clinosim/modules/output/_fhir_care_team.py` emits ONLY attending physician + primary nurse (at most 2 participants). β-JP-1 will expand to 6-name multi-disciplinary team. Do NOT add more participants to CareTeam without a spec decision. The attending physician (participant[0]) is ALWAYS emitted even when `attending_physician_id` is empty (uses `"UNKNOWN"` placeholder rather than omitting participant[]). The nurse (participant[1]) is emitted ONLY when `primary_nurse_id` is non-empty. This ensures CareTeam.participant[] is never `[]` (FHIR R4 cardinality: 0..*; participant is optional but when present must have member).
- **`triage` + `nursing_assignment` modules as 7th/8th always-on Modules** (Tier 1 #3 α-min-2, AD-64, 2026-07-01) — `clinosim/modules/triage/` (POST_ENCOUNTER order=93) and the nursing_assignment enricher in `clinosim/modules/nursing/` (POST_ENCOUNTER order=94) are the 7th and 8th always-on Modules. Both have `enabled=lambda c: True`. Triage is ED-only (no-op for non-emergency encounters). Nursing_assignment is inpatient/ICU/rehab-only (no-op for outpatient/ED). New POST_ENCOUNTER Modules MUST be registered BEFORE `document` (order=95) if they produce CIF data that `document_enricher` needs to read. Current POST_ENCOUNTER order: device(70) → hai(80) → antibiotic(85) → imaging(90) → triage(93) → nursing_assignment(94) → document(95).

### EHR data enrichment — Base vs Module (AD-55) + extensibility (AD-56)

- **Near-essential data → Base** (always-on, extend core: `types`/`population`/`observation`/`simulator`/`output`). **Specialized/optional data → opt-in module**, one theme per module (like `identity`), gated via `SimulatorConfig.modules` + `config.module_enabled(name)`. **Always-on Module = near-essential clinical cascade** (AD-55 PR3b-1 supplement, 2026-06-25): for modules where omission would produce a clinically incoherent state (HAI without antibiotic, device without HAI). Registered with `enabled=lambda c: True` and no-op only when the upstream `extensions[X]` slot is empty. Examples: `device` (PR-A), `hai` (PR-B), `antibiotic` (PR3b-1), `imaging` (Tier 1 #2, AD-62), `allergy` (Tier 1 #3, AD-63), `document` (Tier 1 #3, AD-63), `triage` (Tier 1 #3 α-min-2, AD-64), `nursing_assignment` (Tier 1 #3 α-min-2, AD-64).
- **Add a FHIR resource** by registering a builder via `register_bundle_builder()` (AD-56) — do NOT edit `_build_bundle()`. Builders return raw resources `(ctx) -> list[resource]`.
- **Add an output format** by registering an `OutputAdapter` via `register_output_adapter()` (AD-58) — do NOT edit the CLI `--format` dispatch. Adapters read CIF + `clinosim.codes` + `clinosim.locale` only.
- **Add a post-population / post-records pass** by registering an `Enricher` in `simulator/enrichers.py` (`register_builtin_enrichers`) — do NOT inline it into `run_beta`. Enrichers derive their own sub-seed; order is fixed (determinism).
- **Modules must NOT edit `CIFPatientRecord`** — write to `CIFPatientRecord.extensions[<module>]`. Only Base data adds typed fields to the core type.
- Refactors of these paths must preserve golden/e2e output and determinism.

### AD-55 enricher patterns (PR1 foundation refactor, 2026-06-24)

- **Sub-seed offset convention** — new enricher modules MUST register their sub-seed in `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS` with a 16-bit hex-ASCII offset (e.g. `0x494D` = "IM", `0x4445` = "DE", `0x4841` = "HA"). Identity (decimal 540_054) and microbiology (decimal 770_077) are grandfathered to preserve byte-identical output. The dict has a module-level assert that catches accidental duplicates at import. Modules import via `from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS` and use `derive_sub_seed(master, ENRICHER_SEED_OFFSETS["my_module"], key)`.
- **DRY helpers** — cross-module utilities used by 2+ enrichers live in `clinosim/modules/_shared.py`. Don't redefine inline; import from `_shared`. Current: `get_attr_or_key(obj, name, default)` for dict / dataclass dual access; `normalize_probabilities(probs, fallback="uniform")` for any `rng.choice(p=)` argument (PR-A 2026-06-26 — `numpy.random.Generator.choice` does NOT auto-normalize; YAML pre-normalization is fragile, helper is idempotent on already-normalized arrays so migration is byte-clean).
- **Locale loader signature** — modules with locale-specific data MUST accept a `country: str` parameter and return `{}` for unsupported countries (no-op early return). Hardcoded country literals in path joins (e.g., `_LOCALE / "jp" / "..."` without country gating) are a consistency bug.
- **Path constant canonical form (PR-A 2026-06-26)** — every module that loads data uses `_HERE = Path(__file__).resolve().parent`, `_REF_DIR = _HERE / "reference_data"` (if applicable), `_LOCALE = _HERE.parents[1] / "locale"` (if applicable). Old naming (`_REFERENCE_DATA_DIR`, `_DATA`, `_HAI_REF_DIR`, fragile `.parents[2]`) was unified across 18 modules (PR-A initial 12 + Fix PR #100 6 more). New modules MUST follow the canonical form; see boilerplate in `.github/TEMPLATE_MODULE_README.md`.
- **`lru_cache` maxsize convention (PR-A 2026-06-26, PR-B1 2026-06-27 + Fix 拡張)** — `load_X()` no-param → `maxsize=1`; `load_X(country: str)` → `maxsize=2` (US + JP); `load_X(country, language)` → `maxsize=4` (future multilingual, currently unused). `maxsize=4` on country-only loader is a smell. **PR-B1 (+ adversarial fix) で残存する global mutable `_X: ... | None = None` sentinel pattern を 6 loader(`clinosim/modules/encounter/protocol.py:load_all_encounter_conditions` / `clinosim/simulator/helpers.py:_load_all_disease_protocols` / `clinosim/modules/output/_fhir_diagnostic_report.py:load_panel_groups` / `clinosim/modules/output/_fhir_localization.py` の `_load_med_terms_ja` + `_load_drug_names_ja` + `_load_department_display`)で撤廃し全て `@lru_cache(maxsize=1)` 統一済**。新規 module で hand-rolled cache を書かないこと(同 pattern は test `cache_clear()` pattern も阻害する)。同 PR で `clinosim/simulator/helpers.py:_load_all_disease_protocols` の `try/except pass` silent skip も削除済。
- **Import-time canonical-constants validation (PR-A 2026-06-26, PR #102 2026-06-27 拡張)** — any YAML data referencing external IDs (SNOMED / LOINC / antibiotic key / probability weights) MUST validate against the canonical set at load time and raise `ValueError` on unknown keys / zero-sum weights. Silent `dict.get(key)` fall-through is a PR-90 class silent-no-op risk. Precedents: `modules/hai/load_hai_antibiogram` (3-way validation), `modules/observation/microbiology._validate_microbiology` (PR-A added, 7 cross-refs), `modules/antibiotic/audit._validate_nhsn_resistance_bands`, **`modules/hai/engine._validate_hai_organisms` + `locale/loader._validate_demographics` / `_validate_names` / `_validate_addresses` (PR #102、主要 4 YAML loader の上流防御を完備)**. Combined with `clinosim/modules/_shared.normalize_probabilities(..., fallback="raise")` の後方防御(**全 15 YAML-sourced callsites 完備** = PR #102 で 10 callsites 追加 + pre-PR 5 件 = `code_status:51` / `family_history:90` / `care_level:53` / `observation/microbiology:167+206` が PR-A Fix #100/#101 期間に migrated 済、配置先 7 modules: code_status / population / clinical_course / hai / family_history / observation / care_level)で **silent-no-op 防御 3 層完成**(canonical constants + upstream `_validate_*` + backward `fallback="raise"`)。
- **Enricher stages (Phase 3a, 2026-06-25)** — three stages now exist in `clinosim/simulator/enrichers.py`:
  - `POST_POPULATION` — runs after population generation, before simulation. JP insurance numbering (`identity`) etc.
  - `POST_ENCOUNTER` — runs **per encounter, immediately after the daily loop completes** but **inside** the encounter simulator. Use for "encounter-bound" Modules whose sampling depends on full clinical course (`icu_transferred`, GCS, perfusion) and whose output is consumed by physiology / observation layers later in the same encounter. Currently: `device` (order 70) + `hai` (order 80).
  - `POST_RECORDS` — runs after **all** patient records are simulated. Use for "cross-record" Modules that read patient-wide history. Currently: `nursing` (20), `immunization` (30), `family_history` (40), `code_status` (50), `care_level` (60).
  - **Module classification**: when adding a new opt-in Module, decide first which stage it belongs in. "encounter-bound" vs "cross-record" is a critical design axis — encounter-bound Modules can interact with the same-encounter physiology (e.g. lift WBC + CRP for HAI), while cross-record Modules cannot reach back into the loop.
- **Phase 3b-1 HAI empirical antibiotic** (2026-06-25, PR #93) — `modules/antibiotic/` is the second always-on Module of the HAI cascade. Consumes `extensions["hai"]` at POST_ENCOUNTER order=85 (after `hai=80`), emits IDSA 2009/2016 empirical regimens (Vancomycin / Piperacillin-Tazobactam / Ceftriaxone) as `Order(MEDICATION)` + `MedicationAdministration` via the existing `_fhir_medications.py` builder (zero new builder), plus `extensions["antibiotic"] = list[AntibioticRegimen]` for cross-PR consumption by PR3b-2/3/4. AD-32 defensive future-onset HAI skip prevents orphan Order/MAR when `inpatient.py:464-490` truncates HAI events post-POST_ENCOUNTER. `ForcedScenario.force_hai_event` added for deterministic HAI testing (PR-90 教訓 completion). `modules/antibiotic/audit.py` = AD-60 framework second per-Module plug-in with closed-form `lift_firing_proof`.
- **Phase 3b-2 HAI culture S/I/R susceptibility chain** (2026-06-26, PR #96 + adversarial fix PRs #97/#98) — `modules/hai/_append_hai_culture()` extended with antibiogram-driven S/I/R sampling. Source of truth: `modules/hai/reference_data/hai_antibiogram.yaml` (CDC NHSN AR 2018-2020), nested format `{hai_type: {organism_snomed: {antibiotic_key: [S_rate, I_rate, R_rate]}}}`. Import-time 3-way cross-validation applies the PR-90 / PR3b-1 canonical-constants lesson: YAML keys are validated against `HAI_TYPES` (lowercase) + `hai_organisms.yaml` (valid SNOMED set) + `ANTIBIOTIC_LOINC_LOOKUP` (valid antibiotic keys) at `load_hai_antibiogram()` import, so a case-mismatch or orphan drug key raises `ImportError` before any simulation runs. **`MicrobiologyResult.hai_event_id` backref convention**: HAI-derived cultures set `hai_event_id = HAIEvent.hai_id`; community microbiology paths leave it `""` and are unchanged. **`ANTIBIOTIC_DRUGS` tuple → dict refactor**: key = lowercase snake_case drug key, value = `{"name", "rxnorm", "yj"}`; `ANTIBIOTIC_LOINC_LOOKUP` is a new companion `dict[str, str]` loaded from `microbiology.yaml`. **Forward-compat reserves**: `AntibioticRegimen.discontinuation_datetime = None` (PR3b-3 de-escalation) + `run_forced` now injects `force_hai_event`-carrying scenarios into `config.forced_scenarios` (silent-no-op gap closed; load-bearing `test_run_forced_auto_injects_force_hai_event_into_config` in PR #97 verifies the fix actually fires via monkeypatched enricher — closing the PR-90 class fix-PR-itself-silently-regresses gap). **Audit**: `antibiogram_firing_proof` in `modules/antibiotic/audit.py` uses PR-94 `equality_checks` format with a non-degenerate cefazolin sentinel (PR #98 LOW-1, exposes YAML key-order swaps that the always-S vancomycin sentinel cannot); `_build_combined_proof` sub-proof exception isolation (PR #98 MED-3); `_NHSN_RESISTANCE_BANDS` import-time validation against `HAI_TYPES` + `ANTIBIOTIC_DRUGS` + `hai_organisms.yaml` (PR #98 MED-4); `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE` denominator clarified to panel-eligible HAI cultures only (excluding E.faecalis 78065002 + C.albicans 53326005; PR #97 F-MAJ-1 — without this, CLABSI 28% / CAUTI 34% no-panel weight would force PR3b-3 gate to always-FAIL). `_NHSN_RESISTANCE_BANDS` + `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE` active enforcement was added in PR3b-3 (2026-06-27) and finalized with per-organism R-rate filter + panel-eligible empty-rate denominator in PR3b-3 D1+D2 (PR #112+#113, 2026-06-29). **AD-16 hardening**: `_CapturingRNG.choice` logs the `p=` array (PR #98 MED-1, exposes YAML key reorders); YAML key-order pin tests for clabsi/cauti/vap pinned organisms (PR #98 MED-1); YAML header carries a "KEY ORDER LOAD-BEARING" comment (PR #98 MED-2). **Type annotation correctness**: `ModuleAuditSpec.clinical_acceptance` is `dict[str, Any]` since PR3b-2 stores mixed types (per-HAI dict, list of bands, float threshold) — PR #97 F-CRIT-1 mypy strict 11 errors closed.
- **Phase 3b-3 HAI culture S/I/R-driven narrow / de-escalation chain** (2026-06-27, PR #107 + adv-1 #108 + adv-2 #109 + adv-3 #110 = 4-stage adversarial chain converged, matches PR-A / PR #102 / PR-B1 pattern) — `modules/antibiotic/enricher.py` extended with **same-enricher Pass 2** (POST_ENCOUNTER order=85 unchanged). Pass 2 walks `extensions["antibiotic"]` empirical regimens, looks up the culture via `MicrobiologyResult.hai_event_id` backref, picks the narrow target via new per-(hai_type, organism_snomed) ladder YAML (`reference_data/narrow_ladder.yaml`, 3-way import-time validation against `HAI_TYPES` + `hai_antibiogram.yaml` + `ANTIBIOTIC_DRUGS` — silent-no-op defense 3rd layer). Walk algo: S only accept, I/R skip. Three dispatched outcomes per `NarrowOutcome` enum: **(i) SWITCH** = all empirical get `discontinuation_datetime=reported_datetime`, new `AntibioticRegimen(intent="narrowed")` + Order + MAR added; **(ii) ELIMINATION** = non-target empirical discontinued, target kept unchanged, no new regimen; **(iii) NO_CHANGE** = empirical continues unchanged. `narrowing by elimination` data model avoids same-drug duplication (MRSA CLABSI → vancomycin continues as single regimen, not vanc-twice). **FHIR `MedicationRequest.status` wiring**: new `OrderStatus.STOPPED` + `_map_order_status_to_fhir` in `_fhir_medications.py` → discontinued empirical emits `status="stopped"`. **Audit clinical axis active enforcement** (closes PR3b-2 TODO): `_NHSN_RESISTANCE_BANDS` R-rate gate + `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE` empty rate gate + new `_NARROW_RATE_BANDS` narrow rate gate, each `n<30` → WARN else PASS/FAIL with per-cohort observed in `result.info`. **lift_firing_proof extended**: 8 PR3b-1 + 3 PR3b-2 + 6 PR3b-3 = **17 equality_checks** total. **Determinism (AD-16)**: no new RNG (select_narrow_target is pure over already-determined susceptibilities), enricher cascade order unchanged. **AD-32**: `snapshot < reported_datetime` → narrow skipped. byte-diff intentionally broken (new-feature PR, audit run is primary gate).

  **PR3b-3 chain CLOSED — D1+D2 complete (2026-06-29, PR #112 + adv-1 #113 + adv-2 #114 + adv-3 #115 = 4-stage adversarial chain converged)** — the clinical-axis R-rate gate now filters cohort encounters per-(hai_type, organism, antibiotic) via `_organism_per_encounter` (single `Observation.ndjson` walk on `mb-org-*` resources, builds `{enc_id: {organism_snomed,...}}`); the empty-rate gate restricts the denominator to panel-eligible HAI cohort encounters via `_panel_eligible_organisms` (derived from `load_hai_antibiogram()` keys, no hard-coded no-panel exclusion — E.faecalis 78065002 / C.albicans 53326005 auto-excluded). Both TODO markers removed (`clinosim/audit/axes/clinical.py:175-191` R-rate block + `clinosim/modules/antibiotic/audit.py:111-128` empty-rate block). 10 new unit tests + 4 new integration tests pin filter behavior. n<30 WARN guards retained for rare-event safety. **Silent-no-op defense layers**: (1) canonical SNOMED URI equality vs substring (`_SNOMED_URI`), (2) shared id-prefix constants between writers/readers (`MB_ORG_ID_PREFIX` in `_fhir_microbiology.py`, `ABX_REGIMEN_ID_PREFIX` + `ABX_ORDER_REQ_PREFIX` + `ABX_ORDER_ID_PREFIX` + `ABX_NARROW_SUFFIX` in `antibiotic/engine.py`), (3) `load_hai_antibiogram()` raises on empty top-level + empty per-hai_type bucket, (4) `_validate_nhsn_resistance_bands` reverse-coverage (forward + staleness) with `_NHSN_REVERSE_COVERAGE_EXEMPT` for organisms NHSN doesn't band, (5) all validators run BEFORE `register_audit_module` so band-shape failure prevents stale spec from registering, (6) `_validate_narrow_rate_bands` symmetric forward-coverage = every HAI_TYPE has a narrow rate band (adv-3 finding, applies the sibling layer-4 pattern to `_NARROW_RATE_BANDS`), (7) `HAI_EVENT_ID_SYSTEM` canonical URI shared between writer (`_fhir_microbiology.py`) and reader (`audit/axes/clinical.py`) — PR3b-5 emit pattern same as MB_ORG_ID_PREFIX + ABX_ORDER_ID_PREFIX.

  **★ 区切り達成宣言 (2026-06-29)** — PR3b-3 D1+D2 chain (#112-#116) + PR3b-5 attribution refinement chain (#117-#120) + HAI YAML sibling sweep chain (#121-#122) **全 3 chain CLOSED**。データ品質 / 臨床整合性 / メンテ性 / コンセプト適切性 4 軸で:
  - **データ品質**: PR3b-5 で encounter-level attribution approximation = RESOLVED、approximation 0
  - **臨床整合性**: D1 R-rate gate semantics correct at any cohort scale(per-(hai_type, organism, antibiotic))、D2 panel-eligible denominator NHSN definition 一致、6-of-6 hai_*.yaml loaders fully validated
  - **メンテ性**: 7-layer system-level silent-no-op defense(canonical URIs + ID prefixes + validator ordering + reverse-coverage forward+staleness + HAI_EVENT_ID_SYSTEM) + per-validator 6-layer pattern(empty + per-bucket + forward-coverage + range + authoritative cross-validation)を全 HAI YAML に適用、責任分解点 clear
  - **コンセプト適切性**: silent-no-op 防御 4 層 pattern(canonical constants + YAML loader cross-validation + normalize_probabilities + reverse-coverage)が確立 + 5 例目 4-stage adversarial chain pattern converged(PR-A / PR #102 / PR-B1 / PR3b-3-original / PR3b-3-D1+D2 / PR3b-5 / sibling sweep)= **7 例の安定 chain pattern**

  残 backlog はすべて TODO.md formal entries(PR3b-4 WBC/CRP decay / audit registry `_reset_for_test` ordering / Phase 2 per-event observed-vs-theoretical / NHSN clinical-accuracy band verification / I1 WARN UX / MB_*_PREFIX cleanup / DESIGN.md AD-55+AD-60 extended ADR / `_code_in_data` public API promote)。半端な状態ゼロ、各 deferred item は文脈完備で書面化済。

  **HAI YAML sibling sweep CLOSED (2026-06-29, PR #121 + adv-1 #122 = 2-stage adversarial chain converged)** — the **per-validator 6-layer defense pattern** (empty top + per-bucket guards + unknown-hai_type rejection + HAI_TYPES forward-coverage + range/type checks + authoritative cross-validation) is now applied to **all 6 HAI YAML loaders**: `hai_antibiogram` + `hai_organisms` (existing, PR3b-3) + new `hai_lab_lift` + `hai_rates` + `hai_codes` + `hai_specimens` (sibling sweep). Each `_validate_hai_<name>` performs the pattern with authoritative loader lookups (`_code_in_data()` for ICD/SNOMED/LOINC, `load_devices_config()["devices"]` for device_type). Note: the system-level 7-layer silent-no-op defense established by PR3b-3 / PR3b-5 chains (canonical URIs + ID prefixes + validator ordering + reverse-coverage etc.) is unchanged by sibling sweep — the new validators are pattern applications, not new defense layers. YAML data unchanged; byte-diff verified zero NDJSON at p=1000 seed=42 (only manifest.json transactionTime differs).

  **PR3b-5 attribution refinement CLOSED (2026-06-29, PR #117 + adv-1 #118 + adv-2 #119 = 3-stage adversarial chain converged)** — D1 R-rate gate now joins susceptibilities to specimens (via `Observation.specimen.reference`) and filters to HAI-derived specimens (via the new `HAI_EVENT_ID_SYSTEM` canonical URI identifier, `urn:clinosim:identifier:hai-event-id` matching the existing `urn:clinosim:staff` internal convention). C1 (multi-organism encounter double-count) and C2 (community + HAI culture co-occurrence) attribution defects are mechanically excluded. **D1 gate semantics are correct at any cohort scale; production-scale firing requires either p≥1M (NHSN-band per-(hai_type, organism, abx) cohort sizes scale ~linearly with HAI rate × population) or `ForcedScenario.force_hai_event` injection at smaller p — both currently in the n<30 WARN regime, mechanically verified by integration tests.** New helpers: `_organism_per_specimen`, `_hai_specimens` (inline in `clinosim/audit/axes/clinical.py`). FHIR identifier emission added to `clinosim/modules/output/_fhir_microbiology.py` on Specimen + mb-org-* / mb-sus-* Observation + DiagnosticReport when `MicrobiologyResult.hai_event_id` is non-empty (community cultures byte-identical). PR3b-3 DQR §"Known approximation" carries a RESOLVED cross-link to `docs/reviews/2026-06-29-pr3b-5-attribution-refinement-dqr.md`. **PR3b-3-related deferred TODOs = 0** (PR3b-5 closes the only remaining documented approximation). DQR: `docs/reviews/2026-06-29-pr3b-3-clinical-axis-completion-dqr.md`. **PR3b-3 original-spec deferred TODOs = 0** (both clinical.py + audit.py TODO markers removed). Out-of-scope deferred (separate backlog, not folded in to preserve closure integrity): (a) PR3b-5 **specimen-organism susceptibility attribution refinement** (adv-1 finding C1+C2: current per-organism filter joins susc → organism via encounter ref alone; a HAI encounter with both S.aureus + S.epidermidis cultures double-counts susc rows; the clean fix joins via `Observation.specimen.reference`. New finding spawned by PR3b-3 adv review, not part of original PR3b-3 backlog), (b) YAML loader reverse-coverage sibling sweep (hai_lab_lift / hai_rates / hai_codes / hai_specimens / hai_organisms), (c) audit registry `_reset_for_test` ordering, (d) FHIR `hai_event_id` identifier emission.
- **Phase 3a HAI WBC + CRP lift** — `modules/hai/lab_lift.apply_hai_lab_lift` walks `record.extensions["hai"]` after the daily loop completes (POST_ENCOUNTER stage fires before this) and adds a **closed-form forward delta** to the existing WBC + CRP `obs.value`, preserving original noise + circadian. The closed-form `_hai_lift_delta` mirrors `derive_lab_values`' CRP + WBC blocks exactly without invoking the 30+ analyte pipeline twice. State snapshot comes from `state_history[day_index + 1]` (post-day-N state — index 0 is admission). After lift, `round_to_precision` + `determine_flag` are re-applied so CSV / CIF consumers see consistent flag/value pairs. The earlier 3-helper `hai_flags_from_record` primitive was removed as dead code in the post-PR-90 xhigh review. Phase 3b/c will reuse the same forward-delta pattern for antibiotic decay and Lactate / Plt / Temp / SBP sepsis cascade extensions.
- **Canonical hai_type strings** — use the constants in `clinosim/modules/hai/__init__.HAI_TYPES = ("clabsi", "cauti", "vap")` everywhere a `HAIEvent.hai_type` appears (enricher, tests, YAML keys). The PR-90 xhigh review caught a case-mismatch (UPPERCASE YAML keys vs lowercase enricher writes) that silently no-op'd the entire Phase 3a lift in production; `load_hai_lab_lift_config` now validates YAML keys against `HAI_TYPES` at import time. Any test that constructs `HAIEvent` with a literal string that bypasses `HAI_TYPES` is a smell — wire it through the enricher path or import the constant.
- **Verification gate is `clinosim audit run`** — the unified new-feature gate (structural / clinical / jp_language / silent_no_op axes; AD-60). Modules co-locate their audit checks in `clinosim/modules/<name>/audit.py` via `register_audit_module(ModuleAuditSpec(...))`. byte-diff stays as a separate refactor-PR mechanic. The `silent_no_op` axis runs canonical-constants cross-check + lift-firing proof — this is the load-bearing verification that catches PR-90's silent-no-op class of bug at audit time (a green DQR with HAI cohort delta vs non-HAI baseline can be confounded by underlying disease state — UTI → naturally elevated WBC + CRP — masking a no-op lift code; the lift_firing_proof closes that gap).

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

**v0.2** — population-driven simulation with full FHIR R4 Bulk Data Export, multi-country (US/JP), 32 diseases + 46 ED/outpatient conditions, snapshot date support, opt-in JP insurance enrollment (FHIR Coverage, AD-54), and the complete **AD-55 Base data-enrichment set**: microbiology, cardiac markers, nursing flowsheets, immunization, family history, code status, and extended SDOH (smoking/alcohol/JP 要介護度). The FHIR adapter is split into per-theme `_fhir_*` builder modules (FA-1).

**Silent-no-op defense triplet** is fully wired across the codebase (PR #102 / #103 2026-06-27): (1) canonical constants(例 `HAI_TYPES`)を module-level に定義、(2) `_validate_*(data) -> None` を 5 主要 YAML loader(`_validate_microbiology` PR-A 7 cross-refs + `_validate_hai_organisms` + `_validate_demographics` + `_validate_names` + `_validate_addresses`)に wire(import 時 fail-loud)、(3) `normalize_probabilities(..., fallback="raise")` を全 **15 YAML-sourced callsites** に適用(7 modules: code_status / population / clinical_course / hai / family_history / observation / care_level)。test 補強 + 4-stage adversarial chain converged で検証済(unit / integration / e2e: 1020 passed, 4 skipped)。

**Foundation polish complete** — PR-B1 chain (PR #104 / #105 / #106 2026-06-27): hand-rolled `global X; if X is None: ... else return X` sentinel pattern を **全 6 loader**(`clinosim/modules/encounter/protocol.py:load_all_encounter_conditions` / `clinosim/simulator/helpers.py:_load_all_disease_protocols` / `clinosim/modules/output/_fhir_diagnostic_report.py:load_panel_groups` / `clinosim/modules/output/_fhir_localization.py` の `_load_med_terms_ja` + `_load_drug_names_ja` + `_load_department_display`)で撤廃し `@lru_cache(maxsize=1)` 統一済。同時に `_load_all_disease_protocols` の `try/except pass` silent skip を削除(silent-no-op 防御強化、PR #102 triplet との整合)。byte-diff invariant 保持(37/37 NDJSON sha256 IDENTICAL)+ 4-stage adversarial chain converged で検証済(1031 passed, 4 skipped)。残 PR-B2 = 16 module の `__init__.py` に `__all__` + re-export (MOD-1 柔軟解釈、callers 不変)。

**PR3b-3 HAI culture S/I/R-driven narrow / de-escalation chain complete** — PR #107 (original) + #108 (adv-1 = 5 CRITICAL + 5 IMPORTANT) + #109 (adv-2 = 1 CRITICAL + 5 IMPORTANT) + #110 (adv-3 = stage-3-introduced regression fix) = **4-stage adversarial chain CONVERGED** (2026-06-27, matches PR-A / PR #102 / PR-B1 4-stage pattern): same antibiotic enricher Pass 2 walks `extensions["antibiotic"]` empirical regimens, looks up culture via `MicrobiologyResult.hai_event_id` backref, picks narrow target via per-(hai_type, organism) `narrow_ladder.yaml` (4-way validation: HAI_TYPES + antibiogram + ANTIBIOTIC_DRUGS + reverse-coverage), dispatches 3 outcomes (SWITCH = new `intent="narrowed"` regimen / ELIMINATION = non-target empirical discontinued / NO_CHANGE). FHIR `MedicationRequest.status="stopped"` via new `OrderStatus.STOPPED` + exhaustive `_map_order_status_to_fhir`. Audit clinical axis active enforcement (per-hai_type narrow rate + NHSN R-rate + empty rate, all `n<30 → WARN` guards). lift_firing_proof extended to **17 equality_checks** (8+3+6). silent-no-op defense triplet 4th layer = `_validate_narrow_ladder` 4-way (forward+reverse coverage+empty container) + `_validate_narrow_rate_bands` typo + empty list gates + `_validate_hai_empirical` reverse-coverage (sibling sweep from adv-1)。

**Tier 1 #2 Imaging chain α-min complete** (2026-06-30, AD-62) — `modules/imaging/` always-on POST_ENCOUNTER Module (order=90) emits `ImagingStudyRecord` into `extensions["imaging"]`. 4 FHIR resources per imaging encounter: `ImagingStudy` (urn:dicom:uid, DCM modality, multi-series), `Endpoint` (WADO-RS placeholder), radiology `DiagnosticReport` (findings + impression in `text.div` + `conclusion`), `ServiceRequest` (imaging category). Polymorphic `_fhir_service_request` dispatches LAB + IMAGING. 15-check `lift_firing_proof` (AD-60). Disease YAMLs: `bacterial_pneumonia.yaml` (CR CXR) + `hemorrhagic_stroke.yaml` (CT head). JP locale: 100% ja displays (modality/bodySite/DR.code/conclusion). Production cohort: US p=10k + JP p=5k. Bug found+fixed: `_simulate_unknown_condition` was not setting `encounter_id` on orders before returning `CIFPatientRecord` — added encounter_id backfill loop (mirrors `simulate_inpatient:361-363`).

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
    immunization/  <- Adult vaccine history (AD-55 Base; AD-56 enricher)
    family_history/<- First-degree-relative disease history (AD-55 Base)
    code_status/   <- Resuscitation status on serious encounters (AD-55 Base)
    care_level/    <- JP 要介護度 / long-term-care need level (AD-55 Base, JP only)
    device/        <- ★ ICU device placement (CVC/catheter/ventilator, AD-55 Module, PR-A)
    hai/           <- ★ CDC NHSN HAI sampling (CLABSI/CAUTI/VAP, AD-55 Module, PR-B; consumes extensions["device"])
    output/        <- CIF → format adapters; fhir_r4_adapter + per-theme _fhir_* builders (FA-1)
  simulator/       <- Top-level orchestration (run_beta, run_forced, CLI)
    enrichers.py   <- ★ Enricher registry for Base/opt-in module passes (AD-56)
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
  `N30.9`), add a `code_mapping_diagnosis/us.yaml` entry `C → <billable leaf>` and register the
  leaf in `icd-10-cm.yaml`.
- **JP (WHO)**: `code_mapping_diagnosis/jp.yaml.get(C, C)` must be a **true WHO ICD-10 code
  (3-4 char)** present in `codes/data/icd-10.yaml`. If `C` is ICD-10-CM granularity (5-7 char,
  7th-char extension, `X` placeholder — e.g. `A41.01`, `S06.0X0A`), add a jp map entry folding
  it to its WHO parent (`A41.01 → A41.0`) and register the WHO code in `icd-10.yaml`. JP does NOT
  emit CM-granularity codes nor fall back to `icd-10-cm.yaml` (enforced by
  `test_jp_never_emits_cm_granular_code` + `test_icd10_who_file_has_no_cm_granular_codes`).

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
