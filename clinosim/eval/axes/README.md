# `clinosim.eval.axes` — per-axis eval check runners

## Purpose

`clinosim.eval.axes` holds the concrete check runners for each of the
four axes evaluated by [`clinosim.eval`](../README.md). The parent
package owns the `EvalCheck` dataclass, the `Cohort` reader, the
scoring engine, and the `clinosim eval` CLI; this subpackage owns the
per-axis logic that produces the `list[EvalCheck]` the engine
aggregates.

Splitting axis logic here keeps the engine layer transport-only and
lets each axis evolve independently as new checks are added.

## Scope

- **In scope**: axis runner functions. Each file exposes
  `run(cohort, country) -> list[EvalCheck]` — the contract the engine
  calls at scoring time.
- **Out of scope**: `EvalCheck` dataclass, scoring aggregation, CLI,
  Markdown/JSON output formatters — those live in
  [`clinosim.eval`](../README.md).

## Axes

| File | Axis | Checks | Notes |
| --- | --- | :-: | --- |
| `structural.py` | Structural | 5 (MVP) | FHIR compliance — id uniqueness, reference integrity, required fields, `meta.profile` declared, `resourceType` consistency. |
| `clinical.py` | Clinical | 7 (5 MVP + 2 P1-9) | Coherence checks — physiology-to-lab consistency, medication-lab coherence (warfarin), contradiction detection. |
| `locale.py` | Locale | 5 (MVP) | Language + code-system compliance — JP labs on JLAC10 / LOINC, medication systems, name/address locale. |
| `jp_clins_lab_compliance.py` | JP-CLINS | 3 ratios | JP-CLINS `JP_Observation_LabResult_eCS` self-measurement — CS 使用率 / display 一致率 / dual-slot 充足率. Deliberately validator-independent because eCS uses Open slicing (unknown codings are silently accepted). |

## Adding a new axis

1. Add a new file under `clinosim/eval/axes/` exposing
   `run(cohort, country) -> list[EvalCheck]`. Follow the existing
   pattern: iterate the cohort's NDJSONs via
   [`clinosim.audit.types.Cohort`](../../audit/types.py), build one
   `EvalCheck` per check with `(id, axis, description, outcome,
   severity, evidence)`.
2. Wire the axis into `eval/engine.py::score_cohort` so the runner is
   invoked during aggregation.
3. Update the parent [`README.md`](../README.md) axis list and this
   table.

## Why measure `jp_clins_lab_compliance` in-repo?

External FHIR validators cannot serve as the JP-CLINS quality metric
because `JP_Observation_LabResult_eCS` uses **Open slicing** on
`Observation.code.coding` with `discriminator = system + display` — a
coding whose display does not match a fixed slice is silently accepted
as "an unknown extra coding" (surfacing only as an `information`
OperationOutcome issue). Whole classes of coding drift are therefore
invisible to pass/fail gating. The axis walks NDJSON directly and
computes three per-resource ratios (denominator = Observations, never
codings — per-coding counting biases against resources that carry many
codings). See the module docstring for the full rationale.

## Cross-references

- Framework overview: [`clinosim.eval`](../README.md)
- Internal per-module PR gate: [`clinosim.audit`](../../audit/README.md)
  and its own [axes/](../../audit/axes/README.md)
- Runner: `clinosim eval` (see repo-root docs).
