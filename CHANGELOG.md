# Changelog

All notable changes to **clinosim** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

- **MAJOR** — incompatible API / CIF / FHIR schema changes.
- **MINOR** — backward-compatible feature additions (new modules, new resource
  types, additional locale support).
- **PATCH** — backward-compatible bug fixes, data-quality corrections that do
  not change the CIF/FHIR schema.

Determinism guarantee: for a given `(seed, hospital_config, country,
start, end, population)` tuple, output NDJSON must be byte-identical across
PATCH-only releases within the same MINOR line. MINOR releases may change
byte output but must document the change here.

## [Unreleased]

_Nothing yet — next changes land here._

## [0.3.0] - 2026-08-22

### Added (session 88k)

- **MHLW `MedicationUsage_ePrescription` heuristic** at FHIR emit time (PRs #836/#837/#838/#840/#841). `_populate_jp_medication_dosage_ecs_fields` now calls `_resolve_mhlw_usage_code(drug_text, freq, period, period_unit, route_text)` which dispatches through a 5-path resolver: **(1)** route filter — non-oral routes (`_NON_ORAL_ROUTE_MARKERS` = 静注/皮下注/筋注/吸入/舌下/貼付/塗布/点眼/直腸/経腸/etc.) return None so the walker falls to the JP-CLINS dummy uncoded code (spec-legit; MHLW oral CS has no injection/inhalation/etc. code family); **(2)** PRN condition codes via `_DRUG_PRN_MHLW_CODE` (アセトアミノフェン→発熱時、サルブタモール→喘息発作時); **(3)** fixed-interval Q3H via `_HOURLY_CADENCE_MHLW_CODE` (`1028…`); **(4)** daily-cadence meal-context via `_FREQ_CONTEXT_TO_MHLW_CODE` (9 canonical codes) driven by the drug-class → meal-context tables `_DRUG_{QD,BID,TID}_MEAL_CONTEXT` (~50 drugs across statins/PPIs/bisphosphonates/diuretics/antihypertensives/anticoagulants/antibiotics/etc.); **(5)** drug-implied freq when `timing.repeat` is missing entirely via `_DRUG_IMPLIED_FREQ_{QD,BID,TID}` sets. Semantic invariant: MHLW oral code is emitted **only** when `route.text == "経口"`. JP p=10000 s500 sample coverage: **99,252 / 115,599 dosages (85.86%) with a real MHLW code, all clinically correct**; residual 14.14% dummy is MHLW-CS-unmappable routes.
- **`comp-{encounter_id}-imgrpt-{n}` id pattern for imgrpt Composition** (PR #835, Issue #818 fu). Prior `comp-imgrpt-…` prefix sorted after every `comp-ENC-…` id so consumer alphabetic-`id` pagination (e.g. `_count=500`) missed all 4,823 imgrpt records. New pattern interleaves them among the same-encounter documents — a first-500 sample now includes ~37 imgrpt.
- **Non-stub ImagingStudy description + canonical dedup** (PR #834, Issue #822 fu). Non-stub ImagingStudy path now sets `description = order.display_name`; the emit fallback that used to leave `description=""` is closed. Dedup extracted to top of the per-order loop, applied to both stub and non-stub via `_canonicalize_display(name)` (lowercase + `_`/`-`→space + drops `and`/`of`/`with`/`for`) so cosmetic variants like `Chest_Xray_PA_Lateral` and `Chest X-ray PA and Lateral` no longer double-emit.
- **`_resolve_staff_name(staff_id, roster_map, is_ja)` template helper** (PR #831, Issue #819 fu). New `NarrativeContext.roster_map` field, populated by `NarrativePass._load_roster()` from `hospital.json`, threaded through `context.py::build_narrative_context`. 4 template call-sites (nursing shift note / progress-note nurse line / ACP other-staff / NCP ward+physician) now emit resolved names (`加瀬 幸男 医師`) before the LLM sees them — no more raw `DR-CA-002` id leak into narrative text. The FHIR-emit-time `_localize_practitioner_ids_in_text` walker (PR #828) is retained as defence-in-depth.
- **Documentation** (PRs #839, #842): narrative module README (EN + JA) documents the roster/template staff-name resolution + JA token localization + relationship to the composition.py walker; fhir_r4/post_process README (EN + JA) documents the full MHLW usage-code heuristic dispatch chain including the route filter and updated coverage numbers.

### Fixed (session 88k)

- **JA localization of `severity` / `oxygen_device` / `fall_risk_level` enum tokens** in narrative templates (PRs #832, #833). Three admission_hp HPI fallback branches used to embed raw `moderate` / `mild` / `severe` in JA text; `_build_nursing_shift_status` used to embed `酸素投与: nasal_cannula` and `転倒リスク high、` verbatim. All now route through the existing `_localize_severity_ja` / `_localize_oxygen_device_ja` / inline fall-level maps.

### Changed (session 88k)

- **iris4h-ai deploy** (`~/workspace/iris4h-ai/fhir_r4/`) regenerated from patched CIF via `clinosim export-fhir`. Post-regen quality on the JP p=10000 s500 cohort: staff_id / severity / o2_device / fall_lvl narrative leaks all 0.00 % on DocumentReference + Composition; imgrpt Composition present in first-500 alphabetically sorted; ImagingStudy empty description = 0, 3-tuple dup = 0; MedRequest MHLW oral code = 85.86 % (all 経口 route, 100 % clinically correct).

### Refactored (session 83)

- **Test import migration to canonical modules + re-export facade removal** (PR #540, PR #541):
  All test suites migrated to import directly from extracted `_fhir_*` sibling modules instead of the backward-compat re-export facade in `fhir_r4_adapter.py`. This allows deletion of the re-export block and further shrinkage of `fhir_r4_adapter.py`.
  - **PR #540**: 3 test files migrate `_build_discharge_rx` imports from `clinosim.simulator.inpatient._build_discharge_rx` (back-compat alias, deprecated in PR #532) to canonical `clinosim.simulator.discharge_rx.build_discharge_rx`. Back-compat alias removed from both `inpatient.py` and `discharge_rx.py`.
  - **PR #541**: 32 test files migrate 104 symbol references from `clinosim.modules.output.fhir_r4_adapter` facade to canonical modules (`_fhir_common`, `_fhir_inline_bb`, `_fhir_post_process`, etc.). The re-export block (109 symbols with `# noqa: F401`) is removed, and `fhir_r4_adapter.py` shrinks 689 → 543 lines (-146 lines). Module boundary now explicit: adapter holds only orchestration (`convert_cif_to_fhir` + `_build_bundle` + registry), leaf symbols live in canonical modules.
  - Verification: both PRs byte-diff neutral (session 82 protocol: unit + E2E + byte-diff), all CI checks green.

### Added (session 82)

- **New `AGENTS.md`** at repo root (agentmd.dev convention). AI coding
  agents (Claude Code, Codex, Cursor, Gemini CLI, Copilot, …) all
  discover repo-level instructions from a single, tool-agnostic
  filename. `CLAUDE.md` remains as a thin pointer for backward
  compatibility with older sessions. PR #527.
- **Coverage reporting in CI** (unit tests, PR #533): `pytest --cov=clinosim`
  now runs on every PR with `--cov-report=xml`, XML uploaded as a
  workflow artifact (30-day retention), soft floor `--cov-fail-under=80`
  (regression visible in log, doesn't block merge). Codecov integration
  scaffolded (commented) — enable via `CODECOV_TOKEN` secret. Baseline
  coverage: **84%** across `clinosim/`.
- **`docs/development/publishing-to-pypi.md`** — step-by-step runbook
  for both PyPI publishing paths (Trusted Publisher / API token). The
  `release.yml` workflow already builds sdist + wheel + dataset presets
  on tag push; PyPI upload is commented out until a maintainer
  completes one of the paths in the runbook. PR #533.
- **Nightly cron workflow** (`.github/workflows/nightly.yml`, PR #530):
  runs the reproducibility gate (`scripts/reproduce.sh`, byte-diffs the
  output for a fixed seed) and Python 3.11 unit tests once a day. Moves
  these rate-of-change gates off the PR path.
- **Escalation `type: "procedure"` signal** (Issue #460, PR #521): disease
  YAML `drugs.escalation[*]` now accepts an explicit `type` field
  (`"procedure"` or `"medication"`). A new 3-stage classifier
  (`classify_escalation_treatment`) routes each escalation on explicit
  type first, keyword fallback second, default MEDICATION third. Six
  latent misclassify entries (Hemodialysis / Vertebroplasty / Kyphoplasty
  / Catheter-directed thrombolysis) now emit as FHIR `Procedure` instead
  of `MedicationRequest`. Import-time validator raises on legacy
  `code_*: "procedure"|"N/A"` markers and on `type: "procedure"` +
  `route:` co-occurrence.
- **Chronic-medication + discharge-prescription sub-RNG isolation**
  (Issue #439, PR #522): new `chronic_medication_seed(patient_id)` and
  `discharge_prescription_seed(patient_id, encounter_id)` helpers in
  `clinosim/simulator/seeding.py` (AD-16 pattern, sibling of
  `panel_specimen_seed` / `individual_lab_seed`). YAML edits to
  `chronic_medications.yaml` or `drugs.discharge_oral` no longer shift
  unrelated patients' cohorts.
- **`baseline_chronic_medications` immutable field** on `PatientProfile`
  (Issue #433, PR #523): activation-time snapshot of the chronic
  regimen. The discharge chronic loop iterates `baseline ∪
  current_medications`, so a drug held during an AKI admission is
  re-emitted at the next admission when renal function recovers — the
  "chronic drug permanently lost after renal-hold" defect is fixed.
- **`drug_name_ja` threading** through `discharge_prescription.items[]`
  (Issue #440, commit c7f0c31071): 3 writer sites (inpatient / outpatient
  / chronic transcribe) now emit `drug_name_ja` so `_deactivate_to_layer1`
  preserves the JP display on round-trip.
- **Module README coverage gate** (PR #531): 31/31 real modules now ship
  a `README.md`, and a durable unit test
  (`tests/unit/test_module_readme_coverage.py`) will fail any future
  module added under `clinosim/modules/` without one.

### Changed (session 82)

- **CI PR-gate simplification** (PR #530): PR-level check count reduced
  from 13 to 9. Drops the empty `integration_serial` job, drops Python
  3.11 from the unit matrix (moved to nightly), combines `lint` +
  `typecheck` into a single `quality` job, moves `reproducibility` to
  nightly, and adds a `paths` filter to the JP-CLINS gate so docs-only
  PRs skip the JP cohort run.
- **`_build_discharge_rx` extracted** into
  `clinosim/simulator/discharge_rx.py` (PR #532). `inpatient.py`
  shrinks 2560 → 2338 lines. Backward-compat alias
  `_build_discharge_rx = build_discharge_rx` remains for existing test
  imports.
- **`cli.py` split by subcommand family** (PR #534): 1845 → 780 lines.
  Each `_run_*` handler moves to a dedicated sibling module
  (`cli_test_encounter` / `cli_test_disease` / `cli_regenerate` /
  `cli_narrate` / `cli_enumerate` / `cli_export_fhir`), shared print /
  export / debug helpers to `cli_common.py`. Back-compat re-exports
  keep existing test imports working.
- **`fhir_r4_adapter.py` inline `_bb_*` builders extracted** into
  `clinosim/modules/output/_fhir_inline_bb.py` (PR #535): 2382 → 1808
  lines. 11 bundle builders + `_build_order_in_rp_map` moved. The
  `_BUNDLE_BUILDERS` registry stays with `_build_bundle` in the
  adapter.

### Fixed (session 82 — subsumed under Added / Changed above)

Detailed defect-fix notes for the three Issue tickets (#460 / #439 / #433)
are recorded in the corresponding PR bodies (#521 / #522 / #523). All
three preserve deterministic output for pre-existing cohorts — byte-diff
verified on US + JP p=3000 seed=42 (Observation.ndjson identical, no
regression).

### Repo hygiene (session 82)

- `.tar.gz` maintainer artifacts (3 files) untracked, `.gitignore`
  unified (PR #524).
- 13 `docs/session-*.md` snapshots archived under
  `docs/history/session-prompts/` (PR #525); 30 `scratchpad/` audit
  artifacts under `docs/history/scratchpad-archive/` (PR #526); the
  root `scratchpad/` directory is now gitignored.
- Historical `spec.md` (2026-04) + `DES_MIGRATION.md` moved under
  `docs/history/` with an index README (PR #528).
- `test_data/` (5392 files / 200 MB of accumulated LLM narrative eval
  outputs) untracked; `.gitignore` prevents re-add (PR #529).

### Added

- **Synthea comparison adapter** (P1-10):
  [`clinosim eval`](docs/eval.md) can now score a
  [Synthea](https://synthetichealth.github.io/synthea/) `fhir/`
  output directory directly. Point `-d` at the Synthea directory;
  the new `clinosim/eval/synthea_adapter.py` auto-detects the
  per-patient Bundle layout and fans it into per-`ResourceType`
  NDJSON under `<cohort>/../synthea-normalized/` (or the
  `--synthea-normalize` override). Deterministic conversion so scores
  are reproducible. Synthea is an **optional** dependency — nothing
  in clinosim imports it at runtime. Full comparison walk-through at
  `docs/synthea-comparison.md`; 7 unit tests cover the adapter.
- **Clinical contradiction checks** (P1-9): two new checks on the
  `clinical` axis of `clinosim eval` — `condition_lab_coherence`
  (aggregate over 8 canonical pairings: sepsis-lactate, DKA-HCO₃,
  MI-troponin, CKD-creatinine, T2DM-HbA1c, pneumonia-WBC, anemia-Hgb,
  CHF-BNP) and `medication_lab_coherence_warfarin` (PT-INR therapeutic
  band on warfarin patients). Each pairing draws laboratory
  observations within ±7 days of the Condition onset and scores the
  overall violation rate against thresholds PASS ≤ 5% / WARN ≤ 25% /
  FAIL > 25% with per-pairing detail on the report. Full rule catalog
  with clinical rationale + literature source lives at
  `docs/eval-rules.md`; `docs/eval.md` clinical-axis table updated;
  new page wired into the docs site nav under Reference. 5 new unit
  tests. Clinical axis check count 5 → 7.
- **FHIR server ingestion guide** (P1-12):
  [`docs/fhir-server-ingestion.md`](docs/fhir-server-ingestion.md)
  walks through loading a generated cohort into a FHIR R4 server via
  the Bulk Data Access `$import` operation, using HAPI FHIR (Docker)
  as the concrete OSS example and listing InterSystems IRIS for Health,
  Microsoft FHIR Server, and Google Cloud Healthcare API as
  vendor-neutral alternatives. Covers per-file POST for small cohorts,
  `$import` for larger ones, dependency-ordered loading to avoid
  reference-integrity errors, JP Core profile validation notes, and a
  round-trip determinism check. Wired into the docs site nav under
  Guides. Vendor-neutral by design: no code path depends on any
  specific FHIR server product.
- **MkDocs documentation site** (P1-11): `mkdocs.yml` at repo root
  configures a Material-themed site at
  [tomookuyama.github.io/clinosim](https://tomookuyama.github.io/clinosim/)
  organized into Home / Getting started / Concepts / Reference / Guides
  / Development / Governance tabs. Existing `docs/` markdown and
  transcluded root files (`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `MODULES.md`, `DESIGN.md`, ...) are referenced via
  `mkdocs-include-markdown-plugin` so there is no duplication or drift.
  Internal-only subtrees (`audit-cycles/`, `reviews/`, `design-notes/`,
  `superpowers/`) are excluded from the published site; contributors
  read them directly on GitHub. New `docs` optional dependency group in
  `pyproject.toml` (`pip install -e ".[docs]"`) installs the build
  toolchain. New `.github/workflows/docs.yml` builds on every PR and
  deploys to `gh-pages` on master push. README documentation badge +
  link added. GitHub Pages must be enabled manually once at
  Settings → Pages → "Deploy from a branch: gh-pages / (root)".
- **`clinosim eval` public evaluation framework** (P1-8): new package
  `clinosim/eval/` scoring any generated cohort on three axes
  (**structural** / **clinical** / **locale**). 15 checks total
  (5 per axis, severity-weighted). Auto-detects US vs JP from cohort
  content when the layout is flat. Emits JSON (machine-readable) +
  Markdown (human) via `--json` / `--md`; `--strict` exits 1 on any
  FAIL. Distinct from `clinosim audit run` (internal per-Module PR
  gate) — `eval` targets external researchers grading synthetic
  cohorts before use. 16 unit tests + 2 end-to-end tests
  (us-100 + jp-100 presets). Full reference at `docs/eval.md`. First
  real bug the tool caught (US Composition CJK leak from
  hpi_template.onset_pattern) filed as `good first issue` #149.
- **Dataset presets** (P1-6): `datasets/` directory with four named
  presets — `us-100`, `us-1000`, `jp-100`, `jp-1000` — each carrying a
  `spec.yaml` (params) and a dataset card in HuggingFace format. New
  CLI `clinosim dataset list` / `clinosim dataset build <name> -o <dir>`
  subcommand under `clinosim/dataset/` reads the spec and delegates to
  `clinosim generate` so no logic is duplicated. Zenodo integration
  (`.zenodo.json` at repo root) mints a DOI on every tagged release.
  Release workflow extended to build all four presets and attach them
  to the GitHub Release as `clinosim-dataset-<name>-vX.Y.Z.tar.gz`
  starting v0.3.0 onward. 13 unit tests
  (`tests/unit/test_dataset_cli.py`) cover preset discovery, spec
  validation, and CLI wiring; end-to-end smoke tested via
  `clinosim dataset build jp-100`.
- **End-to-end reproducibility gate** (P1-7): `scripts/reproduce.sh`
  runs `clinosim generate` twice per locale (US + JP by default) at
  the same seed and byte-diffs every NDJSON + CIF JSON. Excludes
  wall-clock metadata (`manifest.json` files + `cif/metadata.json`).
  `tests/integration/test_full_reproducibility.py` invokes the script
  as an integration test. New CI `reproducibility` job runs it as a
  hard gate on every push and PR — the SemVer determinism promise now
  has a machine-enforced guarantee. README `Testing → Reproducibility`
  subsection documents the script + environment variable overrides.

### Changed

- **Antibiotic regimen intent metadata moved to FHIR `meta.tag[]`** (Issue #349 Phase 2):
  regimen intent (`empirical` vs `narrowed`) was previously encoded in
  `MedicationRequest.id` suffix (e.g. `...cft-n` for narrowed). This violates
  FHIR R4's specification that `Resource.id` is an opaque identifier, and
  creates a 64-character bottleneck whenever id components grow. Refactored to
  emit intent in proper FHIR fields: `meta.tag[]` with
  `system="urn:clinosim:regimen-intent"` and `code="empirical"|"narrowed"`.
  CIF output (Order.medication_intent) is unchanged; FHIR only. `ABX_NARROW_SUFFIX`
  constant retired; audit gates updated to read `meta.tag[]` instead of id
  patterns. **This is the first phase of a three-phase architectural refactor to
  eliminate compound-key id encoding across all resource types.**

### Fixed

- **Immunization `lot_number` was non-deterministic across runs.**
  `clinosim/modules/immunization/engine.py` used Python's builtin
  `hash()` on strings to synthesize lot numbers; that hash is salted
  per-interpreter (`PYTHONHASHSEED`), so two runs at the same seed
  produced different values like `L591-201506-172` vs `L253-201506-427`.
  Replaced with a `hashlib.sha256`-based helper (`_det_hash`). Uncovered
  by the P1-7 `scripts/reproduce.sh` gate; the byte-diff cascaded from
  FHIR `Immunization.ndjson` into the CIF patient records that store
  the same field, so ~65% of CIF patient files also differed. Both are
  byte-identical now.

### Documentation

- **README positioning** (P0-5): new "Why clinosim?" section up-front
  with three concrete differentiators (physiology-driven coherence /
  JP + US native / YAML-driven extension), a Synthea comparison table
  (nine dimensions + "when to use which"), a sample FHIR Observation
  showing a physiology-derived PT-INR for a warfarin-anticoagulated
  patient, and placeholders for the demo GIF and architecture diagram
  (tracked as good-first-issue backlog).
- Table of Contents updated to include the new sections.
- `README.ja.md` translation of the new sections is intentionally
  deferred to a separate PR (scope discipline).

## [0.2.0] - 2026-07-12

Initial public v0.2 baseline release. Bundles the physiology-driven
generator (session-16-through-46 development) with the packaging /
distribution work that makes it installable.

### Changed

- **Version bumped 0.1.0 → 0.2.0** to align the version string with the
  codebase reality — `CLAUDE.md`, README `[![Status](...v0.2...)]` badge,
  and the "release: v0.2.0" example in the README's Versioning section
  had all been describing v0.2 while `pyproject.toml` still declared
  `0.1.0`. The v0.2 label was the truth; the version string was stale.
- **Removed `requirements.txt`.** It carried a `pip freeze` snapshot
  including a hard-coded `-e /Users/tokuyama/workspace/clinosim` local
  path, which broke `pip install -r requirements.txt` for anyone else.
  Runtime + development dependencies are now single-sourced from
  `pyproject.toml` `[project.dependencies]` and
  `[project.optional-dependencies]` (`dev` / `llm` / `parquet` / `all`).
  Migration: `pip install -e ".[dev]"` (developers) or
  `pip install clinosim` (users, once on PyPI).

### Packaging & Distribution

- `pyproject.toml`: switch to `dynamic = ["version"]` sourced from
  `clinosim/__init__.py::__version__` (single source of truth).
- Add PyPI-facing metadata: `keywords`, `classifiers`, `project.urls`
  (Homepage / Documentation / Source / Issues / Changelog).
- Explicit `[tool.hatch.build.targets.sdist]` manifest so YAML reference
  data and codes / locale files ship in the source tarball.
- README: pip-install instructions (users vs developers) + Versioning &
  Releases section + two prominent disclaimers (personal project /
  synthetic data only).
- New `CHANGELOG.md` (this file), Keep a Changelog format.
- New `tests/unit/test_packaging.py` — asserts version single-source-of-truth
  and console entry point registration.
- New `LICENSE` file at repo root (prior state: `pyproject.toml` declared
  MIT but no LICENSE text shipped).

### Added

- Population-driven, physiology-based synthetic EHR data simulation
  (13-variable hidden physiological state per patient).
- FHIR R4 Bulk Data Export (one NDJSON per resource type + manifest).
- Multi-country: US and JP locale packs (names, addresses, demographics,
  code mappings, insurance).
- 32 inpatient diseases + 46 ED / outpatient conditions.
- Snapshot date support (`--end` flag): partial data for in-progress
  encounters (AD-32).
- Complete AD-55 base data-enrichment set: microbiology, cardiac markers,
  nursing flowsheets, immunization, family history, code status, extended
  SDOH (smoking / alcohol / JP 要介護度).
- Always-on modules: device, HAI, antibiotic, imaging, allergy, document,
  triage, nursing.
- Opt-in JP insurance enrollment (FHIR Coverage, AD-54).
- Session 46: JP Core meta.profile emission for 16 primary resource types
  (100% emission rate).
- Session 46: drug_names_ja +54 entries + 17 silent-code-substitution
  fixes against MHLW YJ Excel authoritative master.
- Two-pass CIF generation (AD-65): structural + narrative separation.
- Canonical patient profile fixture library (AD-66) + `regenerate-goldens`
  CLI + `pytest -m regression` suite.
- Audit-cycle workflow (`docs/audit-cycles/`) + by-design registry
  (22 entries).

### Determinism guarantees

- Every module derives a sub-seed from a master seed (AD-16); no
  `random.random()` or global state.
- Per-order lab RNG isolation (AD-59): specimen rejection / hemolysis /
  technician / noise are per-order sub-RNGs, so a YAML edit cannot shift
  unrelated patients' cohorts.
- Verified across seed=42/100/200/300/400 in session 45's 5-seed chain.

### CI / Automation

- **GitHub Actions CI** (`.github/workflows/ci.yml`) — runs on every
  push to `master` and every PR. Hard gates: unit tests on Python 3.11
  + 3.12, integration tests on 3.12, and `python -m build` +
  `twine check` packaging smoke. Informational (non-blocking) jobs:
  `ruff check` / `ruff format --check`, `mypy clinosim/`. Concurrency
  cancels in-flight runs on newer pushes to the same branch.
  Integration timeout set to 60 min after empirical measurement showed
  CI runners run integration ~2.5x slower than the local baseline.
- README CI status badge pointing at the workflow.
- `Makefile` `lint` / `typecheck` / `format` targets pointed at a
  nonexistent `src/` prefix and failed immediately; corrected to the
  real `clinosim/` layout so the CI jobs (and local `make`) work.
- Add `types-PyYAML>=6.0` and `build>=1.0` to the `dev` extras so
  `mypy clinosim/` gets its yaml stubs and CI can build sdist + wheel
  without extra installs.
- **Release automation** (`.github/workflows/release.yml`) — tag push
  (`v*.*.*`) triggers `python -m build` + `twine check` + GitHub
  Release creation with wheel + sdist attached and release notes
  extracted from `CHANGELOG.md`. PyPI upload step is present but
  commented out until `PYPI_API_TOKEN` / trusted publishing is
  configured on the repository.

### Repository hygiene

- `CONTRIBUTING.md` — entry point covering setup, workflow, DCO
  signoff, and quality expectations. Links to
  `docs/CONTRIBUTING-modules.md` for module-level how-to.
- `CODE_OF_CONDUCT.md` — Contributor Covenant 2.1
  (contact: tomo.okuyama@gmail.com).
- `SECURITY.md` — GitHub Security Advisories as the disclosure
  channel; 90-day coordinated-disclosure target.
- `CITATION.cff` — machine-readable citation metadata (CFF 1.2.0)
  that GitHub renders as the "Cite this repository" button.
- `.github/ISSUE_TEMPLATE/{bug_report,feature_request}.yml` +
  `config.yml` disabling blank issues and routing questions to
  Discussions, security to Advisories, and module how-to to
  `docs/CONTRIBUTING-modules.md`.
- `.github/PULL_REQUEST_TEMPLATE.md` — PR checklist with a mandatory
  determinism-impact statement and DCO reminder.
- `.github/workflows/dco.yml` — hard-gate DCO check: every PR commit
  must carry a `Signed-off-by:` trailer (see `CONTRIBUTING.md#dco`
  for how to sign / retro-sign a branch).
- README `Governance & Community` section indexing all of the above.
