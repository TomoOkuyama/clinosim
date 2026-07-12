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

### Added

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
