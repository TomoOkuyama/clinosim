# `clinosim.simulator` — main simulation engine and CLI

## Purpose

`clinosim.simulator` is the top-level entry point that turns a
population definition and a set of enabled modules into a complete
synthetic EHR cohort. It orchestrates population generation,
day-by-day patient trajectories, encounter simulation (inpatient,
outpatient, ED), pipeline steps for labs / vitals / medications,
discharge-gate logic, enricher passes, output serialisation, and the
`clinosim` CLI subcommands: `simulate` (canonical; `generate` remains
as a deprecation alias), `test-disease`, `test-encounter`, `validate`,
`list-diseases`, `narrate`, `export-fhir`, `enumerate`, `diff`,
`regenerate-goldens`, `check-narratives`, plus the delegated
subparsers `audit`, `dataset`, `eval`, and `benchmark` wired in from
their respective packages.

## Scope

- **In scope**: end-to-end simulation orchestration, CLI subcommands,
  disease-protocol loading, per-encounter DES-lite event scheduling,
  inpatient / outpatient / emergency simulators, discharge-gate
  logic, enricher orchestration, per-behavior threshold constants,
  RNG seeding + memoisation, structured simulation log, unknown-
  condition handling.
- **Out of scope**: individual disease physiology (in
  [`clinosim/modules/physiology/`](../modules/physiology/README.md)),
  clinical-content authoring (in `clinosim/modules/*/reference_data/`),
  FHIR / CIF / CSV serialisation (in
  [`clinosim/modules/output/`](../modules/output/README.md)), audit
  gates (in [`clinosim/audit/`](../audit/README.md)), evaluation
  gates (in [`clinosim/eval/`](../eval/README.md)), preset dataset
  building (in [`clinosim/dataset/`](../dataset/README.md)).

## Public API

```python
from clinosim.simulator import (
    run_beta,                     # main population-driven entry
    run_forced,                   # deterministic single-scenario run
    run_alpha,                    # backward-compat single-patient run
    main,                         # CLI entry (`clinosim` console_scripts)
    load_all_disease_protocols,   # protocol registry loader
)
```

Typical use:

```python
from clinosim.types.config import SimulatorConfig
from clinosim.simulator import run_beta

config = SimulatorConfig(country="JP", population=1000, seed=42, ...)
result = run_beta(config)
```

CLI use:

```bash
clinosim simulate -p 10000 -o ./output --format cif csv fhir
clinosim test-disease bacterial_pneumonia --archetype treatment_resistant -n 5
```

## Determinism

**AD-16 invariant — this is the load-bearing determinism guarantee
for the entire project.** Every random draw inside `clinosim.simulator`
must derive from a sub-seed of the passed-in `numpy.random.Generator`.
Introducing `random.random()`, `numpy.random.default_rng()` at call
sites, wall-clock reads, or a globally-shared RNG is a review-blocker.

Concrete consequences:

- Given the same `SimulatorConfig` (country, population, seed, date
  range) and the same enabled-modules registry, `run_beta` produces a
  byte-identical CIF cohort on every run and on every platform that
  agrees on IEEE-754 semantics.
- `seeding.py` is where the top-level RNG is constructed and split
  into per-domain sub-RNGs; `memoize.py` provides patient-scoped
  memoisation (see `feedback_rng_shift_patient_cache_cascade.md` and
  `feedback_rng_neutral_additive_field.md` in maintainer memory for
  the sub-RNG discipline rules).
- Integration tests under `tests/integration/` pin byte-diff
  determinism at fixed seeds for representative populations.

## Dependencies

- `numpy` — only via passed-in `numpy.random.Generator` (see AD-16).
- `pyyaml` — reference-data loading.
- `clinosim.types` — `SimulatorConfig`, `PatientProfile`, `Encounter`,
  and every other CIF shape.
- `clinosim.modules.*` — disease / observation / medication /
  encounter / output / … providers loaded through their public
  registries.
- `clinosim.locale` — country-specific data.
- `clinosim.codes` — code lookup at emit time.

## Constants and configuration

- **Runtime configuration** loaded from `clinosim/config/*.yaml` via
  [`SimulatorConfig`](../types/config.py). See
  [`clinosim/config/README.md`](../config/README.md) for the YAML
  schema.
- **CLI flag defaults** live in `cli.py` and each `cli_*.py`
  subcommand handler; documented via `clinosim <subcommand> --help`
  and in the root [`README.md`](../../README.md) "Configuration"
  section.
- **Per-behavior thresholds** — every operational threshold (ADL
  scoring, MAR administration windows, daily loop timings, discharge
  gates, ED triage, forced-scenario gates, LOC transitions, oxygen
  therapy triggers, scheduling, LOS shape, unknown-condition
  behavior, vitals cadence) is extracted into a dedicated
  `_<area>_thresholds.py` module (14 files, listed under Directory
  contents). This pattern lets a single constants-audit sweep find
  every operational tunable without walking simulation logic.

## Directory contents

Simulation orchestration (12 files):

```
clinosim/simulator/
  __init__.py            public API (5 exports)
  cli.py                 argparse entry, top-level subcommand dispatch
  engine.py              run_alpha / run_beta / run_forced
  daily_loop.py          per-day loop extracted from engine
  hospital_ops.py        hospital operations orchestration
  inpatient.py           inpatient encounter simulator
  outpatient.py          outpatient encounter simulator
  emergency.py           ED encounter simulator
  discharge_gate.py      discharge-timing decision logic
  discharge_rx.py        discharge-time prescription builder
  enrichers.py           post-records enricher pass
  unknown_condition.py   handling for chronic conditions without a
                         disease protocol
```

Pipelines (3 files):

```
  lab_pipeline.py        lab order → sample → result pipeline
  vitals_pipeline.py     vitals cadence + capture pipeline
  medication_pipeline.py medication order → administration pipeline
```

Determinism and instrumentation (4 files):

```
  seeding.py             top-level RNG construction + sub-seed split
  memoize.py             patient-scoped memoisation
  log.py                 structured simulation log
  diff.py                CIF diff helpers for test byte-diff comparisons
```

Helpers (2 files):

```
  helpers.py             shared helpers, incl. load_all_disease_protocols
  enumerate.py           patient / event enumeration helpers
```

CLI subcommand handlers (7 files):

```
  cli_common.py          shared CLI utilities
  cli_enumerate.py       `clinosim enumerate` subcommand
  cli_export_fhir.py     `clinosim export-fhir` subcommand
  cli_narrate.py         `clinosim narrate` subcommand
  cli_regenerate.py      `clinosim regenerate-goldens` subcommand
  cli_test_disease.py    `clinosim test-disease` subcommand
  cli_test_encounter.py  `clinosim test-encounter` subcommand
```

Extracted threshold constants (14 files, `_<area>_thresholds.py`):

```
  _adl_thresholds.py
  _daily_io_thresholds.py
  _daily_loop_thresholds.py
  _discharge_gate_thresholds.py
  _ed_thresholds.py
  _forced_scenario_thresholds.py
  _loc_thresholds.py
  _mar_thresholds.py
  _outpatient_thresholds.py
  _oxygen_therapy_thresholds.py
  _scheduling_thresholds.py
  _stay_thresholds.py
  _unknown_condition_thresholds.py
  _vitals_schedule_thresholds.py
```

## Testing

```bash
pytest tests/unit -k simulator -q          # unit tests
pytest tests/integration -q                # end-to-end + byte-diff
```

Approximately 85 test files reference `clinosim.simulator`.
Integration tests cover full-run byte-diff determinism at pinned
seeds; unit tests focus on individual pipeline stages, discharge-gate
edge cases, and threshold-constant behavior.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
