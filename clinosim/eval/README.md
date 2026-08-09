# `clinosim.eval` — public cohort evaluation framework

## Purpose

`clinosim.eval` scores an already-generated cohort against three axes —
**structural**, **clinical**, **locale** — and produces a numeric score
per axis plus a list of violations. Downstream researchers and ML
engineers use it to grade their synthetic data before consuming it.

Distinct from [`clinosim.audit`](../audit/README.md), which is the
internal per-module PR gate that only clinosim contributors invoke.
`clinosim.eval` is the public gate that anyone can run against any
cohort.

## Scope

- **In scope**: three-axis cohort scoring (structural / clinical /
  locale), machine-readable JSON output, human-readable Markdown output,
  the `clinosim eval` CLI subcommand, the extensible `EvalCheck`
  registry.
- **Out of scope**: individual module invariants (that's
  [`clinosim.audit`](../audit/README.md)), realism benchmarks against
  clinical priors (that's `clinosim.modules.validator`), early-warning
  baseline metrics (that's [`clinosim.benchmarks`](../benchmarks/README.md)).

## Public API

```python
from clinosim.eval import (
    EvalCheck,          # per-check dataclass (id, axis, description, callable)
    EvalAxisResult,     # roll-up per axis
    EvalReport,         # roll-up per whole run
    EvalEngine,         # orchestrator
    Outcome,            # PASS / WARN / FAIL
    Severity,           # BLOCKING / WARNING / INFO
    add_eval_subparser, # CLI wiring
    dispatch_eval,      # CLI handler
)
```

CLI usage:

```bash
clinosim eval --cohort ./my-cohort --axes structural clinical --format md
```

## Dependencies

- `clinosim.types` for cohort record shapes.
- No external evaluation library (all checks are hand-written).

## Constants and configuration

- Per-axis check registration is code-level; each axis file under
  `axes/` declares its checks as `EvalCheck(id="...", axis="...", ...)`.
- Severity ladder: `Severity.BLOCKING` / `Severity.WARNING` /
  `Severity.INFO`.
- CLI defaults documented in `clinosim eval --help`.
- Documented in [`docs/eval.md`](../../docs/eval.md) and
  [`docs/eval-rules.md`](../../docs/eval-rules.md).

## Directory contents

```
clinosim/eval/
  __init__.py           public API
  engine.py             EvalEngine, EvalReport, EvalAxisResult, EvalCheck
  cli.py                `clinosim eval` subcommand
  reporter.py           JSON + Markdown emitters
  registry.py           check registration
  axes/                 per-axis check registrations
    __init__.py
    structural.py       structural integrity checks
    clinical.py         clinical realism checks
    locale.py           locale-specific checks (e.g. JP names / addresses)
    <axis>.py
```

## Testing

```bash
pytest tests/unit -k eval -q
```

Approximately 6 test files reference `clinosim.eval`.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).
