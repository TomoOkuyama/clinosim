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
| `clinical.py` | Clinical | Driven by `spec.clinical_acceptance`. For each HAI-type entry (a dict with `icd10_code`), split observations into cohort (via ICD-10 diagnosis) vs baseline and compare `cohort_p50 − baseline_p50` WBC / CRP deltas against the spec thresholds. Metadata keys switch on further gates: `basedon_coverage` (lab Observation `basedOn`), `imaging_basedon_coverage`, `care_team_per_encounter`, and the HAI resistance / empty-susceptibility / narrow-rate bands. |
| `jp_language.py` | JP-language | Cohort-level localization integrity — per Issue #473, a JP-side violation is text containing a Latin word (`[A-Za-z]{2,}`) AND zero Japanese characters; a US-side leakage is any JP character. Skips `meta`/`identifier`/`extension`/URL slots and JP-CLINS-defined coding displays. |
| `silent_no_op.py` | silent-no-op | The gate that catches the PR-90 class of bug — two independently severable checks run: canonical constants cross-check (`yaml_keys_to_validate` vs `canonical_constants`) and lift-firing proof (`lift_firing_proof`). A third check (fired counter) is described in the module docstring but not implemented. Any drift → FAIL. |

## Adding a new axis

1. Add a new file under `clinosim/audit/axes/` that returns
   `AxisResult`. Follow the existing pattern: consume `(spec, cohort)`,
   iterate NDJSONs via the parent's `Cohort` reader, and build
   `AuditFinding` objects with the appropriate `Severity`.
2. Extend [`ModuleAuditSpec`](../registry.py) with any new spec fields
   the axis needs.
3. Wire the axis into `audit/engine.py`: add its name to
   `_BUILTIN_AXES` and its runner to `_PER_MODULE_RUNNERS` (called per
   module with the spec) or `_COHORT_RUNNERS` (called once per cohort
   with `spec=None`).
4. Update this table and the parent [`README.md`](../README.md).

## Cross-references

- Framework overview: [`clinosim.audit`](../README.md)
- Public per-module gate for downstream researchers:
  [`clinosim.eval`](../../eval/README.md) — the cohort-scoring
  counterpart. `audit` is internal PR gating; `eval` is external
  cohort grading.
- Runner: `clinosim audit run` (see repo-root docs).
