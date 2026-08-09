# `clinosim.simulator` — main simulation engine and CLI

## Purpose

`clinosim.simulator` is the top-level entry point that turns a
population definition and a set of enabled modules into a complete
synthetic EHR cohort. It orchestrates population generation, day-by-day
patient trajectories, encounter simulation (inpatient, outpatient, ED),
enricher passes, output serialisation, and the `clinosim` CLI.

## Scope

- **In scope**: end-to-end simulation orchestration, CLI subcommands
  (`generate` / `test-disease` / `validate` / `list-diseases` /
  `dataset` / `eval`), disease-protocol loading, per-encounter DES-lite
  event scheduling, discharge-gate logic, and enricher orchestration.
- **Out of scope**: individual disease physiology (in
  [`clinosim/modules/physiology/`](../modules/physiology/README.md)),
  clinical-content authoring (in `clinosim/modules/*/reference_data/`),
  FHIR / CIF / CSV serialisation (in
  [`clinosim/modules/output/`](../modules/output/README.md)), audit
  gates (in [`clinosim/audit/`](../audit/README.md)), evaluation
  gates (in [`clinosim/eval/`](../eval/README.md)).

## Public API

```python
from clinosim.simulator import run_alpha, run_beta, run_forced, main

# Main population-driven simulation (recommended entry point).
result = run_beta(config)

# Deterministic single-scenario run for testing.
result = run_forced(scenario)

# Backward-compatible single-patient run.
result = run_alpha(config)

# CLI entry point wired to console_scripts (`clinosim`).
main()
```

`load_all_disease_protocols` and its deprecated alias
`_load_all_disease_protocols` (kept for one release, Issue #557) are
also exported for callers that need the loaded protocol registry
without a full run.

## Dependencies

- `numpy` (only via passed-in `numpy.random.Generator` — see AD-16
  determinism invariant).
- `pyyaml` for reference-data loading.
- `clinosim.types` for `SimulatorConfig`, `PatientProfile`,
  `Encounter`, etc.
- `clinosim.modules.*` for disease / observation / medication /
  encounter / output / … providers loaded through their public
  registries.
- `clinosim.locale` for country-specific data.

## Constants and configuration

- Runtime configuration is loaded from `clinosim/config/*.yaml` via
  [`SimulatorConfig`](../types/config.py). See
  [`clinosim/config/README.md`](../config/README.md) for the YAML
  schema.
- CLI flag defaults live inline in `cli.py` and are documented in the
  root [`README.md`](../../README.md) "Configuration" section.
- Determinism invariant (AD-16): every random draw must derive from a
  sub-seed of the passed-in `numpy.random.Generator`. Introducing
  `random.random()` or a globally-shared RNG is a review-blocker.

## Directory contents

```
clinosim/simulator/
  __init__.py            public API
  cli.py                 argparse entry, top-level subcommands
  engine.py              run_alpha / run_beta / run_forced
  inpatient.py           inpatient encounter simulator
  outpatient.py          outpatient encounter simulator
  emergency.py           ED encounter simulator
  daily_loop.py          per-day loop extracted from engine
  des_engine.py          (legacy discrete-event engine — pending removal)
  discharge_rx.py        discharge-time prescription builder
  discharge_gate.py      discharge-timing decision logic
  enrichers.py           post_records enricher pass
  medication_pipeline.py medication event pipeline
  helpers.py             shared helpers (RNG, protocol loading)
  memoize.py             patient-scoped memoisation
  log.py                 structured simulation log
  cli_narrate.py         narrative-generation CLI helpers
  cli_common.py          CLI shared utilities
  enumerate.py           patient / event enumeration helpers
```

## Testing

```bash
pytest tests/unit -k simulator -q                       # unit tests (~10 s)
pytest tests/integration -q                             # end-to-end
```

Approximately 77 test files reference `clinosim.simulator`.
Integration tests cover full-run byte-diff determinism at pinned seeds.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).
