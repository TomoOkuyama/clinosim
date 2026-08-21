# `clinosim.audit` — internal per-module PR verification gate

## Purpose

`clinosim.audit` is the shared framework that per-module audit hooks
plug into. Every module under `clinosim/modules/*` may register a
`ModuleAuditSpec` that runs against a generated cohort, verifying the
module's own invariants (structural, clinical, coding, silent-no-op).
The `clinosim audit run` CLI walks the module registry and produces a
single pass/fail verdict for the PR.

This is the **internal** PR gate used by module contributors. For the
**public** cohort evaluation framework used by downstream researchers,
see [`clinosim.eval`](../eval/README.md).

## Scope

- **In scope**: the audit registry, the built-in axes (structural,
  clinical, jp_language, silent_no_op), the `AuditEngine` orchestrator,
  the Cohort NDJSON reader, the severity ladder, the aggregated result
  reporter, and the `clinosim audit run` CLI dispatcher.
- **Out of scope**: individual per-module audit specs (each module
  owns its own `audit.py`), public-facing cohort scoring (that's
  [`clinosim.eval`](../eval/README.md)), CI wiring (see
  `.github/workflows/`), the discovery of *what* to audit (each module
  declares its own axes via `ModuleAuditSpec`).

## Public API

```python
from clinosim.audit import (
    ModuleAuditSpec,        # per-module contract
    register_audit_module,  # called from modules/<name>/audit.py
    Severity,               # BLOCKING / WARNING / INFO
    AuditFinding,           # single row of the audit report
    AxisResult,             # roll-up per axis
    AuditResult,            # roll-up for the whole run
    Cohort,                 # lazy NDJSON cohort reader
)
```

Modules register their audit specs at import time:

```python
# clinosim/modules/<name>/audit.py
from clinosim.audit import register_audit_module, ModuleAuditSpec, Severity

register_audit_module(ModuleAuditSpec(
    name="<name>",
    axes=[...],
    severity_default=Severity.BLOCKING,
))
```

The engine (`clinosim/audit/engine.py::AuditEngine`) is not exported
at package level — it is a private orchestrator called only from
`cli.py`. Callers who want to run audits programmatically use the CLI
entry point through `subprocess`, or import from `clinosim.audit.engine`
directly with the expectation that the module signature may change.

## Determinism

Not applicable — audit is a read-only pass over an already-generated
cohort. No random draws, no wall-clock reads. The engine iterates the
`(module × axis)` matrix in a stable order derived from
`sorted(get_registered().keys())`, so the same cohort + the same
registered modules always produce byte-identical `AuditResult` output.

## Dependencies

- `clinosim.types` — `Cohort`-adjacent data shapes.
- `clinosim.audit.axes.*` — the four built-in axes.
- **No reverse dependency**: `clinosim.audit` never imports from
  `clinosim.modules.*`. Modules register into the framework by side
  effect at their own `audit.py` import time; the framework discovers
  them via `discover()` walking `clinosim/modules/*/audit.py`.

## Constants and configuration

- **Severity ladder** — `Severity.BLOCKING`, `Severity.WARNING`,
  `Severity.INFO` (see `types.py`). Only `BLOCKING` findings fail the
  CLI exit code by default; `--fail-on-warning` promotes `WARNING` to
  fail as well.
- **Built-in axes** — `("structural", "jp_language", "clinical",
  "silent_no_op")` (see `engine.py::_BUILTIN_AXES`). Modules that
  register axes outside this set must supply their own runner.
- **Per-module vs cohort-level runners** — `engine.py` distinguishes
  `_PER_MODULE_RUNNERS` (called once per `(module × axis)`) from
  `_COHORT_RUNNERS` (called once per cohort, attached to a synthetic
  `_cohort_` module row so the reporter grid stays rectangular).
- **No YAML configuration.** Registration is purely code-level.
- CLI flags (`--cohort`, `--axes`, `--fail-on-warning`, output-format
  selectors) are documented by `clinosim audit run --help`.

## Directory contents

```
clinosim/audit/
  __init__.py           public API (7 exports: ModuleAuditSpec,
                        register_audit_module, Severity, AuditFinding,
                        AxisResult, AuditResult, Cohort)
  registry.py           ModuleAuditSpec dataclass, register / discover /
                        get_registered
  types.py              Severity enum, AuditFinding, AxisResult,
                        AuditResult, Cohort dataclasses
  engine.py             AuditEngine — (module × axis) matrix orchestrator
  cli.py                `clinosim audit run` subcommand
  reporter.py           human + JSON output
  axes/                 built-in axis runners
    __init__.py
    structural.py       structural integrity checks
    clinical.py         clinical realism checks
    jp_language.py      JP-language coverage checks
    silent_no_op.py     silent-no-op detection (empty enricher output)
```

## Testing

```bash
pytest tests/unit -k audit -q
```

Approximately 19 test files reference `clinosim.audit`. See
[`docs/CONTRIBUTING-modules.md`](../../docs/CONTRIBUTING-modules.md)
"PR verification guide" for the workflow module authors follow.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
