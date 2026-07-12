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
