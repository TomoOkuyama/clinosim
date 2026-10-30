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
    Severity,               # FAIL / WARN / INFO
    AuditFinding,           # single row of the audit report
    AxisResult,             # roll-up per axis
    AuditResult,            # roll-up for the whole run
    Cohort,                 # lazy NDJSON cohort reader
)
```

Modules register their audit specs at import time (every
`ModuleAuditSpec` field except `name` is optional; a module fills in
only the axes it opts into):

```python
# clinosim/modules/<name>/audit.py
from clinosim.audit import register_audit_module, ModuleAuditSpec

register_audit_module(ModuleAuditSpec(
    name="<name>",
    canonical_constants={...},     # silent_no_op: allowed key sets
    yaml_keys_to_validate={...},   # silent_no_op: yaml -> key path
    lift_firing_proof=...,         # silent_no_op: zero-arg proof factory
    structural_obs_codes={...},    # structural: codes to check
    clinical_acceptance={...},     # clinical: acceptance thresholds
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
`(module × axis)` matrix in registration order, which follows
`discover()`'s sorted walk of `clinosim/modules/*/audit.py`, so the
same cohort + the same registered modules always produce the same
`AuditResult`.

## Dependencies

- `pyyaml` — `silent_no_op` loads the YAMLs named in
  `yaml_keys_to_validate`.
- `clinosim.audit.axes.*` — the four built-in axes.
- Registration is by side effect: modules register into the framework
  at their own `audit.py` import time; the framework discovers them via
  `discover()` walking `clinosim/modules/*/audit.py`. The framework
  core (`registry.py`, `types.py`, `engine.py`) does not import
  `clinosim.modules.*`, but `axes/clinical.py` does (`clinosim.codes`,
  `clinosim.modules.antibiotic`, `clinosim.modules.hai`, and
  `clinosim.modules.output.fhir_r4` constants).

## Constants and configuration

- **Severity ladder** — `Severity.FAIL`, `Severity.WARN`,
  `Severity.INFO` (see `types.py`). An `AxisResult` is `FAIL` / `WARN`
  / `PASS` by its worst finding (`N/A` when it has neither findings nor
  info). `clinosim audit run` and `smoke` exit 1 only when the overall
  status is `FAIL`; `WARN` does not fail the exit code.
- **Built-in axes** — `("structural", "jp_language", "clinical",
  "silent_no_op")` (see `engine.py::_BUILTIN_AXES`). These are the only
  axes the engine can run; `--axis` selects a subset.
- **Per-module vs cohort-level runners** — `engine.py` distinguishes
  `_PER_MODULE_RUNNERS` (`structural`, `clinical`, `silent_no_op`;
  called once per `(module × axis)`) from `_COHORT_RUNNERS`
  (`jp_language`; called once per cohort, attached to a synthetic
  `_cohort_` module row so the reporter grid stays rectangular).
- **No YAML configuration.** Registration is purely code-level.
- CLI: `clinosim audit run -d/--cohort-dir DIR [--module NAME]...
  [--axis AXIS]... [--report PATH]` (Markdown to stdout, and to
  `--report` when given); `clinosim audit smoke -d DIR` runs
  `silent_no_op` only; `clinosim audit list` prints the registered
  modules and their checks.

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
  cli.py                `clinosim audit run` / `smoke` / `list` subcommands
  reporter.py           Markdown report (render_markdown / write_markdown)
  axes/                 built-in axis runners
    __init__.py
    structural.py       structural integrity checks
    clinical.py         clinical realism checks
    jp_language.py      JP-language coverage checks
    silent_no_op.py     silent-no-op detection (canonical-constants
                        cross-check + lift-firing proof)
```

## Testing

```bash
pytest tests/unit -k audit -q
```

Approximately 20 test files reference `clinosim.audit`. See
[`docs/CONTRIBUTING-modules.md`](../../docs/CONTRIBUTING-modules.md)
"PR verification guide" for the workflow module authors follow.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
