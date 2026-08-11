# `clinosim.audit.axes` — per-axis check runners

## Purpose

`clinosim.audit.axes` holds the concrete check runners for each audit
axis declared by a [`ModuleAuditSpec`](../README.md). The parent
package ([`clinosim.audit`](../README.md)) owns the registry, cohort
reader, and CLI dispatcher; this subpackage owns the actual logic that
walks a cohort and returns an [`AxisResult`](../types.py).

Splitting axis logic here (rather than inline in `audit/engine.py`)
lets each axis evolve independently and keeps the engine layer
transport-only.

## Scope

- **In scope**: axis executor functions. Each file exposes a callable
  (or the constants it needs) that consumes a spec + cohort and returns
  `AxisResult`.
- **Out of scope**: registry management, cohort I/O, CLI, severity
  ladder definitions — those live in [`clinosim.audit`](../README.md).

## Axes

| File | Axis | Responsibility |
| --- | --- | --- |
| `structural.py` | Structural | FHIR resource integrity — 100% `referenceRange` + `interpretation` coverage, id uniqueness per NDJSON, `display != code` on every coding. |
| `clinical.py` | Clinical | Cohort baseline vs acceptance — for each `spec.clinical_acceptance` entry, split observations into cohort (via ICD-10 diagnosis) vs baseline, compare `cohort_p50 − baseline_p50` deltas against the spec thresholds. |
| `jp_language.py` | JP-language | Cohort-level localization integrity — per Issue #473, a JP-side violation is text containing a Latin word (`[A-Za-z]{2,}`) AND zero Japanese characters; a US-side leakage is any JP character. Skips `meta`/`identifier`/`extension`/URL slots and JP-CLINS-defined coding displays. |
| `silent_no_op.py` | silent-no-op | The gate that catches the PR-90 class of bug — three independently severable checks (canonical constants cross-check, lift-firing proof, module-declared invariants). Any drift → FAIL. |

## Adding a new axis

1. Add a new file under `clinosim/audit/axes/` that returns
   `AxisResult`. Follow the existing pattern: consume `(spec, cohort)`,
   iterate NDJSONs via the parent's `Cohort` reader, and build
   `AuditFinding` objects with the appropriate `Severity`.
2. Extend [`ModuleAuditSpec`](../registry.py) with any new spec fields
   the axis needs.
3. Wire the axis into `audit/engine.py::run_module_audits` so it is
   invoked during aggregation.
4. Update this table and the parent [`README.md`](../README.md).

## Cross-references

- Framework overview: [`clinosim.audit`](../README.md)
- Public per-module gate for downstream researchers:
  [`clinosim.eval`](../../eval/README.md) — the cohort-scoring
  counterpart. `audit` is internal PR gating; `eval` is external
  cohort grading.
- Runner: `clinosim audit run` (see repo-root docs).
