# Design: Extract `_run_daily_loop` to sibling `daily_loop.py`

Issue: [#552](https://github.com/TomoOkuyama/clinosim/issues/552)
Date: 2026-08-09
Status: Design approved, ready for implementation-plan phase.

## Goal

Move `_run_daily_loop` (573 LOC) and its exclusive helper
`_extract_findings` (23 LOC) from `clinosim/simulator/inpatient.py` to a
new sibling file `clinosim/simulator/daily_loop.py`. Pure mechanical
relocation; function bodies unchanged. `inpatient.py` re-exports the
symbols for backwards compatibility with existing callers.

Reduces `inpatient.py` from 1385 LOC to ~800 LOC, matching session 84's
established sibling-flat-file extraction convention
(`lab_pipeline.py`, `vitals_pipeline.py`, `medication_pipeline.py`,
`unknown_condition.py`).

## Non-goals (out of scope)

Issue #552's original proposal (subpackage `inpatient/` with 7 files
including per-day phase modules `mar.py`, `vitals.py`, `adl_io.py`,
etc.) was already **substantively addressed by session 84** via the
sibling-file convention. This PR handles the last remaining god-object
concern (file size) at minimum risk.

Explicitly out of scope:

- **`_simulate_patient` internal split** (639 LOC orchestrator): its
  linear setup → simulate → post-process flow is legitimately
  monolithic and does not decompose cleanly into helpers without adding
  indirection cost.
- **`_run_daily_loop` per-day phase extraction** (~10 phases: state
  update, orders, labs, meds, vitals, ADL/IO, complications, discharge
  check, etc.): would introduce RNG cursor shift risk (memory rule
  `feedback_rng_shift_patient_cache_cascade.md`) with no offsetting
  byte-diff-neutral guarantee. If future cognitive-load reduction is
  needed, file a follow-up Issue at that time.
- **Sub-simulator unit-test scaffolding**: session 84's sibling-file
  extractions already exposed lab / vitals / med pipelines for direct
  import in tests; the pattern is established and the tests exist.

## Design decisions

### DD1: Sibling flat file, not subpackage

Session 84 (`lab_pipeline.py`, `vitals_pipeline.py`,
`medication_pipeline.py`, `unknown_condition.py`) established the
convention: extract each cohesive concern to a sibling flat file at
`clinosim/simulator/` top level, with the origin file re-exporting for
backwards compatibility. This PR follows that convention rather than the
Issue's original subpackage proposal.

### DD2: Move only `_run_daily_loop` and `_extract_findings`

- `_run_daily_loop` is the identified 573-LOC state machine.
- `_extract_findings` (23 LOC) is called from `_run_daily_loop` only
  (grep-verified); moving it with the daily loop keeps the pair
  cohesive. If it were called from elsewhere in `inpatient.py`, it
  would stay behind, but it isn't.
- `_planned_discharge_datetime` stays in `inpatient.py`: it's called
  from `_simulate_patient` (not from the daily loop), so extracting it
  to `daily_loop.py` would create a wrong-direction import.

### DD3: Backwards-compat re-export at `inpatient.py` top-level

Session 84's pattern (see `inpatient.py:79-111` re-exporting from
lab/vitals/medication pipelines) is directly reused:

```python
# Backwards-compat re-export (Issue #552 residual). The daily-loop state
# machine (~570 LOC) moved to `clinosim/simulator/daily_loop.py`.
from clinosim.simulator.daily_loop import (  # noqa: E402, F401
    _extract_findings,
    _run_daily_loop,
)
```

Existing test / caller imports (`from clinosim.simulator.inpatient
import _run_daily_loop`) continue to resolve. No caller-side changes
required.

### DD4: Byte-diff neutrality by construction

Pure file-move with unchanged function bodies preserves:

- Every RNG consumption sequence (state.rng cursor unaffected).
- Every downstream side effect (order emission order, MAR generation,
  vital sampling, etc.).
- Every return value shape.

Cohort byte-diff verification (30-patient seed 42 JP+US) is the safety
net rather than a discovery tool: any non-metadata diff indicates the
refactor accidentally changed function behavior and blocks merge.

## Architecture

**Current**:

```
clinosim/simulator/inpatient.py (1385 LOC)
├─ _planned_discharge_datetime (14 LOC, helper)
├─ _simulate_patient (639 LOC, orchestrator)
├─ _run_daily_loop (573 LOC, per-day state machine) ← extract
└─ _extract_findings (23 LOC, helper for daily loop) ← extract
```

**After**:

```
clinosim/simulator/inpatient.py (~800 LOC)
├─ _planned_discharge_datetime (unchanged)
├─ _simulate_patient (unchanged, calls _run_daily_loop via re-export)
└─ Backwards-compat re-export from daily_loop

clinosim/simulator/daily_loop.py (NEW, ~620 LOC)
├─ Module docstring
├─ Imports (subset of inpatient.py's imports needed by daily loop)
├─ _run_daily_loop (moved verbatim)
└─ _extract_findings (moved verbatim)
```

Responsibility split:

- `inpatient.py`: single-encounter orchestrator (severity/archetype
  selection, encounter creation, admission orders, delegation to the
  daily loop, post-loop CIF record assembly).
- `daily_loop.py`: per-day state machine that runs inside the
  orchestrator's simulation phase.

## Components

### C1 — new file `clinosim/simulator/daily_loop.py`

Header:

```python
"""Per-day state machine extracted from `inpatient.py` (Issue #552 residual).

Contains the per-day loop that drives state update, orders, labs, MAR,
vitals, ADL/IO, complications, and discharge check for each simulated
day of an inpatient encounter. Extracted to reduce `inpatient.py`'s file
size (session 84's sibling-file convention: `lab_pipeline.py`,
`vitals_pipeline.py`, etc.).

Function bodies moved verbatim; byte-diff-neutral vs pre-extraction.
"""
```

Import block: derived by grep-inspection of `_run_daily_loop` +
`_extract_findings`. Includes at least:

- `datetime`, `timedelta`, `deepcopy`, `numpy` (RNG typing).
- `clinosim.codes.hl7_encounter` (ActPriority, DischargeDisposition,
  AdmitSource).
- `clinosim.modules.clinical_course.engine` (apply_diagnosis_modifier,
  compute_diagnosis_effectiveness, evaluate_complications,
  get_daily_directive, natural_recovery_directive).
- `clinosim.modules.diagnosis.engine` (update_differential,
  get_current_diagnosis_code).
- `clinosim.modules.observation.engine` (lab_panel_components).
- `clinosim.modules.order.engine` (place_daily_lab_orders,
  place_imaging_orders).
- `clinosim.modules.order.treatment_classifier`
  (classify_escalation_treatment).
- `clinosim.modules.physiology.engine` (apply_state_delta,
  derive_lab_values, medication_flags_from_context,
  scenario_flags_from_protocol, update).
- `clinosim.modules.procedure.engine` (generate_bedside_procedures,
  generate_rehab_sessions).
- `clinosim.modules.staff.engine` (assign_staff, FALLBACK_*).
- `clinosim.simulator.lab_pipeline` (_run_lab_result_pipeline).
- `clinosim.simulator.medication_pipeline`
  (_generate_home_medication_orders, _generate_mar,
  _place_chronic_monitoring_orders).
- `clinosim.simulator.vitals_pipeline` (_generate_adl_assessment,
  _generate_daily_io, _generate_vitals).
- `clinosim.simulator.helpers` (_check_discharge_ready,
  _evaluate_mortality, etc. — subset used by daily loop).
- `clinosim.types.clinical` / `.encounter` / `.patient` (types
  referenced in function signatures + bodies).

Exact import list produced by the implementation-plan step (grep-driven,
not hand-authored — avoids drift).

### C2 — modified `clinosim/simulator/inpatient.py`

Deletions:

- Function definitions of `_run_daily_loop` (L790-1362) and
  `_extract_findings` (L1363-1385).
- Any top-level import that is used **only** by the deleted functions.
  `ruff check` catches unused imports post-deletion.

Additions:

- Backwards-compat re-export block adjacent to existing session-84
  re-exports (currently at L79-111):

```python
# Backwards-compat re-export (Issue #552 residual). The daily-loop state
# machine (~570 LOC) moved to `clinosim/simulator/daily_loop.py`.
# Existing call sites in `_simulate_patient` (and external test callers)
# resolve via this re-import; new call sites should import directly from
# `daily_loop`.
from clinosim.simulator.daily_loop import (  # noqa: E402, F401
    _extract_findings,
    _run_daily_loop,
)
```

### C3 — components NOT touched

- `_planned_discharge_datetime`, `_simulate_patient` — unchanged.
- All other sibling files (`lab_pipeline.py`, `vitals_pipeline.py`,
  `medication_pipeline.py`, `unknown_condition.py`, `helpers.py`) —
  unchanged.
- No new tests required — pure file-move preserves function identity;
  existing integration test coverage suffices.

## Data flow — byte-diff surface

**Expected: zero data diff**. Verification runs 30-patient seed 42
cohorts on both master baseline and PR branch, then `diff -r` with
`-x _generator_metadata.json`. Only diffed files should be:

- `cif/metadata.json` (timestamp)
- `cif/narratives/template/manifest.json` (timestamp)
- `fhir_r4/manifest.json` (timestamp)
- `simulator.log` (timestamps)

**Any non-metadata diff BLOCKS merge** — indicates the move accidentally
altered function behavior (e.g. import order changing module-load side
effects, missing import causing NameError at runtime not caught by
tests, etc.).

## Error handling & edge cases

- **Import cycle**: `daily_loop.py` MUST NOT import from
  `clinosim.simulator.inpatient` (would create cycle since `inpatient.py`
  re-exports from `daily_loop.py`). All symbols `daily_loop.py` needs
  are directly available in leaf modules or in session-84's sibling
  pipeline files.
- **Missing import in daily_loop.py**: caught at import time (Python's
  eager import). First `pytest tests/unit` run surfaces any oversight.
- **Unused import in inpatient.py**: caught by `ruff check` post-move.
- **External caller impact**: grep for `from clinosim.simulator.inpatient
  import.*(_run_daily_loop\|_extract_findings)` — all such imports
  resolve via the backwards-compat re-export.
- **Direct `daily_loop.py` import in future callers**: allowed, encouraged
  (matches session 84's forward-migration pattern).

## Testing

**No new tests required**. Existing coverage:

- Integration tests (`tests/integration/`) exercise `_run_daily_loop`
  via `_simulate_patient` → daily loop. Pass = function behavior
  preserved.
- Unit tests on daily loop's callees (lab/vitals/med pipeline sibling
  files) are unaffected — same callees.

Verification checklist:

- [ ] `pytest tests/unit`: 4002 pass (baseline, no delta)
- [ ] `pytest tests/integration`: deferred to CI
- [ ] `mypy clinosim/` strict: clean
- [ ] `ruff check` + `format --check`: clean (post-move, may need
  `--fix I` for import sort)
- [ ] Grep for external callers of `_run_daily_loop` / `_extract_findings`:
  all resolve via re-export
- [ ] 30-patient seed 42 JP+US cohort diff-r vs master: **zero data
  diffs**, only metadata/log timestamps differ

## Effort estimate

- Implementation deletions: ~600 LOC removed from `inpatient.py`
  (function definitions).
- Implementation additions: ~620 LOC added to `daily_loop.py` (function
  bodies + module docstring + imports) + ~5 LOC re-export block in
  `inpatient.py`.
- Verification: ~20 min (cohort diff-r + import grep + full test run).
- Net implementation LOC: ~+25 (import block + docstring in new file);
  file-count +1; cognitive complexity: `inpatient.py` file size drops
  40% (1385 → ~800 LOC).

## Severity / priority

`high` per Issue #552 severity, but the substantive risk is largely
addressed by session 84. This PR is the residual clean-up that closes
the Issue with a mechanical, byte-diff-neutral move.

## Follow-up

If future cognitive-load reduction of the 573-LOC `_run_daily_loop` is
warranted (e.g. per-day phase extraction to make each phase
independently testable), file a NEW Issue at that time. Its byte-diff
risk profile is different (RNG cursor sensitive) and warrants a fresh
spec.
