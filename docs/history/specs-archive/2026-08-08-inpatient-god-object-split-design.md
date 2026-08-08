# Design: `simulator/inpatient.py` god-object split (Issue #552)

**Date**: 2026-08-08 (session 84)
**Author**: Claude Opus 4.7
**Status**: approved (user), implementation ships as 4 sequential PRs

## Problem

`clinosim/simulator/inpatient.py` is 2369 LOC after the Session 83 (Issue #544)
`helpers.py` split. It carries encounter finalization, discharge decision, LOS
calc, vitals generation, LOC/AVPU inference, a 2-pass lab result pipeline,
medication administrations, procedure orchestration, and the unknown-condition
branch. New contributors cannot hold the file in context; reviewers cannot
reason about state transitions locally.

Issue #552 lists a Verification section that mandates **byte-diff neutral**
output — any refactor must not shift the CIF cohort a single line.

## Function inventory (baseline: 2369 LOC)

| Function                              | LOC  | Shape       |
|---------------------------------------|------|-------------|
| `_simulate_patient`                   |  638 | god A       |
| `_run_daily_loop`                     |  660 | god B       |
| `_simulate_unknown_condition`         |  265 | standalone  |
| `_generate_vitals`                    |  135 | standalone  |
| `_generate_home_medication_orders`    |  122 | standalone  |
| `_generate_mar`                       |  118 | standalone  |
| `_place_chronic_monitoring_orders`    |  107 | standalone  |
| `_generate_daily_io`                  |   67 | standalone  |
| `_generate_adl_assessment`            |   55 | standalone  |
| `_planned_discharge_datetime`         |   15 | leaf helper |
| `_make_raw` / `_o2_for` / `_loc_for`  |   33 | leaf helpers |
| `_extract_findings`                   |   29 | leaf helper |

2 god functions occupy 55% of the file (1298 LOC). The other 12 functions
are already reasonably scoped (100–265 LOC each). **Moving standalone
functions to a new module is byte-neutral by construction** — no arg-lift,
no RNG order shift, just a name rebind.

## Extract order (4 sequential PRs)

| PR | Target module | Extracted symbols | LOC ↓ | Risk |
|----|---------------|-------------------|-------|------|
| **D** | `simulator/unknown_condition.py` | `_simulate_unknown_condition` | 265 | LOWEST — single standalone function, byte-neutral by construction |
| **B** | `simulator/vitals_pipeline.py` | `_generate_vitals`, `_generate_daily_io`, `_generate_adl_assessment`, `_make_raw`, `_o2_for`, `_loc_for` + `_NEURO_DISEASES` / `_RESPIRATORY_DISEASES` frozensets | 290 | LOW — 6 standalone functions grouped by topic |
| **C** | `simulator/medication_pipeline.py` | `_generate_home_medication_orders`, `_place_chronic_monitoring_orders`, `_generate_mar` | 347 | LOW-MEDIUM — 3 standalone functions, medication write-back is a well-bounded concern |
| **A** | `simulator/lab_pipeline.py` | `_run_daily_loop` inner lab loop (~200 LOC) extracted as helper | ~200 | HIGH — mid-function cut, must preserve RNG order verbatim; ships after B/C so file surface is smaller |

**Post-4-PR result**: `inpatient.py` = 2369 → **~1267 LOC (47% reduction)**.
The two god functions (`_simulate_patient` + `_run_daily_loop`) still hold
the remaining 1298 LOC; their full decomposition is out of scope here and
will get its own brainstorming pass in a future session.

## Per-PR pattern

Every PR follows the Session 84 safe-subset ship-and-iterate discipline:

1. `git mv` (functionally: move function definitions verbatim into the new
   module; do not touch bodies).
2. Add re-import at the top of `inpatient.py` so existing
   `from clinosim.simulator.inpatient import _generate_vitals` keeps
   resolving:
   ```python
   from clinosim.simulator.vitals_pipeline import (  # noqa: F401 — backwards compat
       _generate_vitals,
       _generate_daily_io,
       ...
   )
   ```
   (Deprecation warning intentionally omitted — these are private
   underscore names; external callers don't rely on them.)
3. `pytest tests/unit` — must remain green.
4. Byte-diff verify: `clinosim generate -p 30 -s 42 --country US
   --format fhir-r4 --out $SCRATCH/current`; compare CIF structural JSON
   vs `origin/master` cohort. Requirement: **0-line diff**.
5. Ship the PR. CI green → merge → next PR.

## Interface & isolation

Each new module owns:
- Its function definitions (verbatim copy).
- Any module-scope constants that ONLY that module consumes (e.g. the
  neuro/respiratory frozensets migrated with the vitals module).
- A one-line module docstring naming the concern and citing Issue #552.

Each new module depends on:
- `clinosim/types/`, `clinosim/modules/*`, `clinosim.locale` — same as
  today.
- **NOT** `clinosim.simulator.inpatient` (no back-import; the extracted
  functions were leaf callees, so this is naturally satisfied).

## Verification (each PR)

- `pytest tests/unit` — baseline 3948 pass (post-#600 branch). Numbers
  may drift as later PRs add tests, but no regression.
- CIF structural JSON `diff -r` — 0 line diff.
- `ruff check clinosim tests` clean.

## Deferred (out of scope, tracked in Issue #552 comment)

- **`_simulate_patient` internal split** (638 LOC).
- **`_run_daily_loop` internal split** (660 LOC) beyond the lab-pipeline
  helper extract of PR A.
- Both need their own brainstorming pass — state-flow analysis is
  required to identify sub-simulator boundaries within these two
  functions.

## Rejected alternatives

- **Big-bang single PR**: extract all 4 concerns at once. Rejected
  because 900+ LoC in one review window compounds the "did I miss an
  RNG-order shift?" question across 4 axes. Sequential PRs isolate the
  regression search space.
- **Lab pipeline first**: user's original candidate. Rejected because
  it's the highest-risk extract (mid-function cut into a 660-LOC
  callsite). Doing B and C first shrinks the surface before attacking A.
