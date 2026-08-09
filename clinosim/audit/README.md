# `clinosim.audit` — internal per-module PR verification gate

## Purpose

`clinosim.audit` is the shared framework that per-module audit hooks
plug into. Every module under `clinosim/modules/*` can register a
`ModuleAuditSpec` that runs against a generated cohort, verifying the
module's own invariants (structural, clinical, coding). The `clinosim
audit run` CLI aggregates all registered specs and produces a single
pass/fail verdict for the PR.

This is the **internal** PR gate used by module contributors. For the
**public** cohort evaluation framework used by downstream researchers,
see [`clinosim.eval`](../eval/README.md).

## Scope

- **In scope**: the audit registry, axis executor, cohort reader,
  severity ladder, aggregated result printer, and the CLI dispatcher
  invoked by `clinosim audit run`.
- **Out of scope**: individual per-module audit specs (each module owns
  its own `audit.py`), public-facing cohort scoring (that's
  [`clinosim.eval`](../eval/README.md)), CI wiring (see
  `.github/workflows/`).

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

## Dependencies

- `clinosim.types` for `Cohort`-adjacent data shapes.
- Individual `clinosim/modules/*/audit.py` files register into
  this framework — no reverse dependency (this package does not
  import any module).

## Constants and configuration

- Severity ladder (`Severity.BLOCKING`, `Severity.WARNING`,
  `Severity.INFO`) — see `types.py`.
- No YAML configuration. Registration is purely code-level.
- CLI flags (`--cohort`, `--axes`, `--fail-on-warning`) are documented
  by `clinosim audit run --help`.

## Directory contents

```
clinosim/audit/
  __init__.py           public API
  registry.py           module registration + spec lookup
  types.py              Cohort, Severity, AuditFinding, AxisResult, AuditResult
  executor.py           runs one axis, produces AxisResult
  cli.py                `clinosim audit run` subcommand
  reporter.py           human + JSON output
  axes/                 per-axis executors shared across modules
    __init__.py
    <axis>.py           each shared axis (structural / clinical / etc.)
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
