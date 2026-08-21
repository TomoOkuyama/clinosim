# `clinosim.eval` — public cohort evaluation framework

## Purpose

`clinosim.eval` scores an already-generated cohort against three axes
— **structural**, **clinical**, **locale** — plus optional
country-specific axes (currently `jp_clins_lab_compliance` for JP).
It produces a per-axis numeric score plus a list of violations.
Downstream researchers and ML engineers use it to grade their
synthetic data before consuming it.

Distinct from [`clinosim.audit`](../audit/README.md), which is the
internal per-module PR gate that only clinosim contributors invoke.
`clinosim.eval` is the public gate that anyone can run against any
cohort — including cohorts produced by third-party generators such as
Synthea (via the built-in `synthea_adapter`).

## Scope

- **In scope**: three-axis cohort scoring (structural / clinical /
  locale) with weighted PASS / WARN / FAIL outcomes, JSON + Markdown
  report renderers, the `clinosim eval` CLI subcommand, the Synthea
  → clinosim NDJSON adapter, per-country optional axes.
- **Out of scope**: individual module invariants (that's
  [`clinosim.audit`](../audit/README.md)), realism benchmarks against
  clinical priors (that's `clinosim.modules.validator`), early-warning
  baseline metrics (that's
  [`clinosim.benchmarks`](../benchmarks/README.md)), running the
  simulator itself (that's [`clinosim.simulator`](../simulator/README.md)).

## Public API

```python
from clinosim.eval import (
    EvalCheck,          # per-check dataclass (id, axis, outcome, weight, ...)
    EvalAxisResult,     # roll-up per axis (checks list + score)
    EvalReport,         # roll-up per whole run (axis results + overall score)
    EvalEngine,         # orchestrator
    Outcome,            # PASS / WARN / FAIL (StrEnum)
    Severity,           # BLOCKING / WARNING / INFO
    add_eval_subparser, # CLI wiring
    dispatch_eval,      # CLI handler (returns process exit code)
)
```

CLI usage:

```bash
clinosim eval --cohort ./my-cohort --format md
```

Each axis under `axes/` exposes a plain function:

```python
def run(cohort: Cohort, country: str) -> list[EvalCheck]
```

The engine then computes axis score = `100 × Σ(passing weight) /
Σ(total weight)` where a WARN counts as 0.5 of a pass; the overall
score is the arithmetic mean of the axis scores. Both cohort layouts
`<root>/<country>/fhir_r4/` (multi-country) and `<root>/fhir_r4/`
(single-country flat) are consumable directly.

## Determinism

Not applicable — evaluation is a read-only pass over an
already-generated cohort. No random draws, no wall-clock reads other
than an `EvalReport.generated_at` timestamp stamped into the report
metadata. Given the same cohort input, per-axis check sets and their
outcomes are byte-identical across runs; the only run-to-run diff in
report output is the timestamp itself.

## Dependencies

- `clinosim.audit.types.Cohort` — reused as the NDJSON cohort reader
  (both packages share the same lazy-reader implementation).
- Standard library only otherwise (`json`, `pathlib`, `datetime`,
  `enum`, `dataclasses`).

## Constants and configuration

- **Outcome ladder** — `Outcome.PASS`, `Outcome.WARN`, `Outcome.FAIL`
  (StrEnum). Scoring: PASS = weight, WARN = 0.5 × weight, FAIL = 0.
- **Severity ladder** — `Severity.BLOCKING`, `Severity.WARNING`,
  `Severity.INFO`. Attached to `EvalCheck` for CI gating logic.
- **Axis discovery** — the engine imports the four built-in axis
  modules (`structural`, `clinical`, `locale`, and the JP-specific
  `jp_clins_lab_compliance`) directly; new axes are added by writing
  a new `axes/<name>.py` and wiring it in `engine.py`.
- **Per-country activation** — `jp_clins_lab_compliance` runs only
  when `country == "JP"`.
- CLI defaults documented in `clinosim eval --help`. See also
  [`docs/eval.md`](../../docs/eval.md) and
  [`docs/eval-rules.md`](../../docs/eval-rules.md).

## Directory contents

```
clinosim/eval/
  __init__.py                     public API (8 exports)
  engine.py                       Outcome, Severity, EvalCheck,
                                  EvalAxisResult, EvalReport, EvalEngine
  cli.py                          `clinosim eval` subcommand
                                  (add_eval_subparser / dispatch_eval)
  report.py                       JSON + Markdown emitters
  synthea_adapter.py              Synthea Bundle-per-patient → clinosim
                                  NDJSON layout translator (P1-10)
  axes/                           per-axis check runners
    __init__.py
    structural.py                 structural integrity checks
    clinical.py                   clinical realism checks
    locale.py                     locale-specific checks (JP names /
                                  addresses / coding, US equivalents)
    jp_clins_lab_compliance.py    JP-CLINS lab-compliance axis
                                  (activated only for country=JP)
```

## Testing

```bash
pytest tests/unit -k eval -q
```

Six test files reference `clinosim.eval`, covering axis scoring,
Synthea adapter round-trips, and CLI dispatch.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
