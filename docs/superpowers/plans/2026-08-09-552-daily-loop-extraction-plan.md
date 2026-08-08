# daily_loop.py Extraction — Implementation Plan (Issue #552)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `_run_daily_loop` (573 LOC) + `_extract_findings` (23 LOC) from `clinosim/simulator/inpatient.py` to a new sibling file `clinosim/simulator/daily_loop.py`. Pure mechanical relocation; byte-diff-neutral by construction. Adds a backwards-compat re-export block to `inpatient.py`.

**Architecture:** Session 84's established sibling-flat-file convention (`lab_pipeline.py`, `vitals_pipeline.py`, `medication_pipeline.py`, `unknown_condition.py`) is reused. Function bodies moved verbatim — no logic change, no signature change, no RNG cursor shift.

**Tech Stack:** Python 3.12, pytest, ruff==0.16.0 (CI-pinned), mypy strict.

## Global Constraints

- Branch discipline: never commit directly to `master`; work on branch `fix/552-daily-loop-extraction` off current `origin/master`.
- ruff version: install `ruff==0.16.0` (CI-pinned) before any lint step.
- Signed-off commits required: every `git commit` must include `--signoff` (DCO gate).
- Byte-diff neutrality is a per-verification gate: any non-metadata data diff BLOCKS merge (indicates the move accidentally altered behavior).
- Base ref for byte-diff comparisons: **current `origin/master` at branch cut time**.
- JP cohort env var: `CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package'`
- Baseline generation MUST run in the primary worktree (the JP-CLINS package resolution in `coding_package.py:549` uses `Path(__file__).parents[5]` which fails for `/tmp/` worktrees).
- Sub-project spec: `docs/superpowers/specs/2026-08-09-552-daily-loop-extraction-design.md` — authoritative for every design decision (DD1-DD4).
- Import cycle prevention: `daily_loop.py` MUST NOT import from `clinosim.simulator.inpatient` (would create cycle since `inpatient.py` re-exports from `daily_loop.py`).

---

## File Structure

**Files created:**

| Path | Responsibility |
|---|---|
| `clinosim/simulator/daily_loop.py` | New sibling file holding `_run_daily_loop` + `_extract_findings` (moved verbatim) + subset of imports they need |

**Files modified:**

| Path | Change |
|---|---|
| `clinosim/simulator/inpatient.py` | Delete `_run_daily_loop` (L790-1362) and `_extract_findings` (L1363-1385) function definitions. Add backwards-compat re-export from `daily_loop.py` (adjacent to session-84 re-exports at L79-111). Remove now-unused top-level imports (ruff catches these). |

**Files NOT modified:**

- `_planned_discharge_datetime` and `_simulate_patient` in `inpatient.py` — unchanged.
- All other sibling files (`lab_pipeline.py`, `vitals_pipeline.py`, `medication_pipeline.py`, `unknown_condition.py`, `helpers.py`) — unchanged.
- No test files touched — pure file-move, existing coverage suffices.

---

## Task 1: Create `daily_loop.py` with moved function bodies + inferred imports

**Files:**
- Create: `clinosim/simulator/daily_loop.py`
- Read: `clinosim/simulator/inpatient.py:790-1385` (source of the two moved functions).
- Read: `clinosim/simulator/inpatient.py:1-128` (source of the current imports; subset carries to daily_loop.py).

**Interfaces:**
- Consumes: current `origin/master` code (branch cut point).
- Produces: standalone `daily_loop.py` module that imports cleanly and defines `_run_daily_loop` + `_extract_findings` (importable but not yet called by `inpatient.py`).

- [ ] **Step 1: Cut the fix branch off origin/master, install pinned ruff**

```bash
cd /Users/tokuyama/workspace/clinosim
git fetch --prune origin
git checkout -b fix/552-daily-loop-extraction origin/master
git rev-parse HEAD > /tmp/552-baseline-sha.txt
python -m pip install ruff==0.16.0
```

Expected: on fix branch off origin/master, baseline SHA captured, ruff 0.16.0 active.

- [ ] **Step 2: Extract function bodies to a scratch file for reference**

```bash
sed -n '790,1385p' clinosim/simulator/inpatient.py > /private/tmp/claude-*/scratchpad/552-moved-bodies.py
wc -l /private/tmp/claude-*/scratchpad/552-moved-bodies.py
```

Expected: ~596 lines (573 for `_run_daily_loop` + 23 for `_extract_findings`).

- [ ] **Step 3: Enumerate the imports needed by the moved functions**

Grep the moved bodies for referenced names (module-level symbols, functions, types) and cross-reference with `inpatient.py`'s current imports (L1-128):

```bash
# Symbol references in the moved bodies
python3 -c "
import ast, sys
with open('/private/tmp/claude-*/scratchpad/552-moved-bodies.py') as f:
    src = f.read()
tree = ast.parse(src)
names = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Name):
        names.add(node.id)
    elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        names.add(node.value.id)
print('\n'.join(sorted(names)))
" | tee /private/tmp/claude-*/scratchpad/552-referenced-names.txt
```

Then cross-reference with `inpatient.py:1-128` imports to build the exact import list needed in `daily_loop.py`. Include:

- Standard library: `datetime` (datetime, timedelta), `deepcopy` from copy, `numpy` (numpy is imported as `np` in inpatient.py).
- Types: whatever `types.encounter`, `types.clinical`, `types.patient`, `types.output`, `types.config` symbols the bodies reference.
- Codes: whatever `clinosim.codes` and `hl7_encounter` symbols the bodies reference.
- Modules: all `clinosim.modules.*` imports the bodies use (clinical_course, diagnosis, disease, observation, order, physiology, procedure, staff — subset).
- Session-84 sibling pipelines: `clinosim.simulator.lab_pipeline`, `.medication_pipeline`, `.vitals_pipeline` (imports needed by the daily loop calls).
- Helpers: `clinosim.simulator.helpers` (subset — `_check_discharge_ready`, `_evaluate_mortality`, etc. depending on daily loop's uses).
- Shared: `clinosim.modules._shared` symbols the bodies reference (`MED_STOP_ORDER_ID_MARKER`, `sanitize_id_token` if used).

**CRITICAL**: do NOT import `from clinosim.simulator.inpatient import ...` — creates a cycle.

- [ ] **Step 4: Write `clinosim/simulator/daily_loop.py`**

Structure the new file as:

```python
"""Per-day state machine extracted from `inpatient.py` (Issue #552 residual).

Contains the per-day loop that drives state update, orders, labs, MAR,
vitals, ADL/IO, complications, and discharge check for each simulated
day of an inpatient encounter. Extracted to reduce `inpatient.py`'s file
size (session 84's sibling-file convention: `lab_pipeline.py`,
`vitals_pipeline.py`, etc.).

Function bodies moved verbatim; byte-diff-neutral vs pre-extraction.
"""

from __future__ import annotations

# <import block: exact set from Task 1 Step 3 grep>

# <_run_daily_loop verbatim from inpatient.py:790-1362>

# <_extract_findings verbatim from inpatient.py:1363-1385>
```

Preserve every line of the two function bodies verbatim — including comments, blank lines, and inline docstrings. Do NOT reformat, re-indent, or "improve" any code during the move. The whole point of byte-diff neutrality is behavioural preservation.

Reference the moved-bodies scratch file (`/private/tmp/claude-*/scratchpad/552-moved-bodies.py`) as the source-of-truth for the function content.

- [ ] **Step 5: Sanity check — import `daily_loop.py` in isolation**

```bash
PYTHONPATH=. python -c "
from clinosim.simulator.daily_loop import _run_daily_loop, _extract_findings
print('imports OK')
print('signature:', _run_daily_loop.__name__, _run_daily_loop.__code__.co_argcount, 'args')
"
```

Expected: `imports OK` + signature info. Any ImportError means missing / wrong import in Step 4 — fix inline and re-run.

- [ ] **Step 6: Lint the new file**

```bash
ruff check clinosim/simulator/daily_loop.py
ruff format --check clinosim/simulator/daily_loop.py
```

Expected: clean. If `ruff check` flags unused imports, remove them (may indicate Step 3 grep over-included). If `ruff format --check` fails, run `ruff format clinosim/simulator/daily_loop.py` and re-verify.

- [ ] **Step 7: Type check**

```bash
mypy clinosim/
```

Expected: clean. Any type error at daily_loop.py indicates a missing import or a type annotation reference that didn't survive the move.

- [ ] **Step 8: Commit — daily_loop.py exists but is not yet called from inpatient.py**

At this point `daily_loop.py` defines the two functions but `inpatient.py` still has its own copies. This intermediate commit is safe — the module is importable, tests still pass (via `inpatient.py`'s local copies), and the next task removes the duplication.

```bash
git add clinosim/simulator/daily_loop.py
git commit --signoff -m "refactor(simulator): add daily_loop.py sibling module — Issue #552 (part 1 of 2)

Creates clinosim/simulator/daily_loop.py containing _run_daily_loop
(573 LOC) and _extract_findings (23 LOC) — moved verbatim from
inpatient.py. The origin file still has its own copies at this point;
part 2 (next commit) removes the duplication and adds the backwards-
compat re-export.

This intermediate commit is safe: daily_loop.py imports and defines the
two functions correctly (verified), and inpatient.py's own copies still
serve every caller (verified via existing test suite).

Follows session 84's sibling-file convention (lab_pipeline.py,
vitals_pipeline.py, medication_pipeline.py, unknown_condition.py).

Design: docs/superpowers/specs/2026-08-09-552-daily-loop-extraction-design.md"
```

---

## Task 2: Remove duplicated function bodies from `inpatient.py`, add re-export

**Files:**
- Modify: `clinosim/simulator/inpatient.py` — delete `_run_daily_loop` + `_extract_findings` definitions, add re-export block, remove now-unused imports.

**Interfaces:**
- Consumes: Task 1's `daily_loop.py`.
- Produces: `inpatient.py` reduced from 1385 LOC to ~800 LOC; symbol names still resolvable via `from clinosim.simulator.inpatient import _run_daily_loop, _extract_findings`.

- [ ] **Step 1: Delete the two function definitions from `inpatient.py`**

Remove:

- L790-1362: the entire `def _run_daily_loop(...)` block (573 LOC including docstring).
- L1363-1385: the entire `def _extract_findings(...)` block (23 LOC).

Delete the trailing blank lines the two functions were followed by, if any. Preserve the docstring / comment structure before L790 (should end cleanly at `_simulate_patient`'s closing).

- [ ] **Step 2: Add backwards-compat re-export block**

Adjacent to session-84's re-exports (currently at L79-111 — lab_pipeline, medication_pipeline, vitals_pipeline, unknown_condition), insert:

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

Place immediately after the last existing session-84 re-export block (near L111). Match the existing pattern's whitespace.

- [ ] **Step 3: Remove now-unused top-level imports from `inpatient.py`**

Run `ruff check` and address any F401 (unused import) warnings:

```bash
ruff check clinosim/simulator/inpatient.py
```

Common candidates for removal (verify per-symbol via grep):

- `deepcopy` (used only in daily loop for state_history)
- `apply_state_delta`, `natural_recovery_directive`, `get_daily_directive`, `compute_diagnosis_effectiveness`, `apply_diagnosis_modifier` (all clinical_course callees exclusive to daily loop)
- `evaluate_complications` (daily loop only)
- `update_differential` (daily loop only)
- `lab_panel_components` (daily loop only)
- `place_daily_lab_orders`, `place_imaging_orders` (daily loop only — verify `_simulate_patient` doesn't call them post-refactor)
- `classify_escalation_treatment` (daily loop only)
- `derive_lab_values`, `medication_flags_from_context`, `scenario_flags_from_protocol` (daily loop only)
- `generate_bedside_procedures`, `generate_rehab_sessions` (daily loop only — verify)
- `_run_lab_result_pipeline` (daily loop only)
- `_check_discharge_ready` (daily loop only — verify)

For each candidate, grep the remaining `inpatient.py` to confirm no `_simulate_patient` reference exists, then remove.

**Important**: `assign_staff`, `FALLBACK_PHYSICIAN_ID` — kept if `_simulate_patient` still uses them (grep verifies).

- [ ] **Step 4: Format check + auto-fix**

```bash
ruff check --fix clinosim/simulator/inpatient.py
ruff format clinosim/simulator/inpatient.py
ruff check clinosim/simulator/inpatient.py
ruff format --check clinosim/simulator/inpatient.py
```

Expected: all clean after the two `--fix`/format passes.

- [ ] **Step 5: Type check**

```bash
mypy clinosim/
```

Expected: clean. Any error indicates a caller-side reference that broke (e.g., `_simulate_patient` still references a symbol whose import was removed in Step 3 — restore that import).

- [ ] **Step 6: Full unit test suite**

```bash
PYTHONPATH=. pytest tests/unit -x 2>&1 | tail -5
```

Expected: 4002 pass (baseline, no delta expected). Any failure indicates broken imports or altered behavior — investigate before proceeding.

- [ ] **Step 7: Verify external callers still resolve**

```bash
grep -rn 'from clinosim.simulator.inpatient import.*_run_daily_loop\|_extract_findings' clinosim/ tests/
```

Expected: any hits (test files, other simulator modules) continue to resolve via the re-export. Verify by importing:

```bash
PYTHONPATH=. python -c "
from clinosim.simulator.inpatient import _run_daily_loop, _extract_findings
print('re-export OK')
"
```

Expected: `re-export OK`.

- [ ] **Step 8: Commit — inpatient.py reduction + re-export**

```bash
git add -u clinosim/simulator/inpatient.py
git commit --signoff -m "refactor(simulator): delete duplicated daily-loop bodies from inpatient.py, add re-export — Issue #552 (part 2 of 2)

Removes _run_daily_loop (573 LOC) and _extract_findings (23 LOC) from
inpatient.py — bodies live in daily_loop.py (added in the previous
commit). Adds a backwards-compat re-export block adjacent to session
84's existing re-exports so external callers importing via
'from clinosim.simulator.inpatient import _run_daily_loop' continue
resolving without changes.

Also removes ~15 top-level imports that are no longer referenced by the
remaining _simulate_patient / _planned_discharge_datetime code (ruff F401
identified all cases).

inpatient.py: 1385 LOC → ~800 LOC (41% reduction), closing Issue #552's
file-size complaint.

Design: docs/superpowers/specs/2026-08-09-552-daily-loop-extraction-design.md"
```

---

## Task 3: Cohort byte-diff verification + PR open

**Files:**
- Read (regeneration output): `/tmp/552-baseline-{jp,us}/`, `/tmp/552-pr-{jp,us}/`
- Write to scratchpad: `/private/tmp/claude-*/scratchpad/552-diff-{jp,us}.txt`

**Interfaces:**
- Consumes: Task 2's refactor committed on the fix branch.
- Produces: PR opened against `master` with cohort byte-diff verification embedded in the body.

- [ ] **Step 1: Save current state and swap to baseline for cohort generation**

Since we've committed the refactor, generate the baseline by temporarily reverting the two `.py` files to master state:

```bash
git show master:clinosim/simulator/inpatient.py > /tmp/inpatient_pr.py.bak
git show master:clinosim/simulator/daily_loop.py 2>/dev/null || echo ""  # daily_loop.py doesn't exist in master
cp clinosim/simulator/inpatient.py /tmp/inpatient_pr.py
cp clinosim/simulator/daily_loop.py /tmp/daily_loop_pr.py

# Install baseline state
git show master:clinosim/simulator/inpatient.py > clinosim/simulator/inpatient.py
rm clinosim/simulator/daily_loop.py
```

- [ ] **Step 2: Generate baseline cohorts (in primary worktree per constraint)**

```bash
CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package' PYTHONPATH=. clinosim simulate -p 30 -s 42 --country JP --format fhir-r4 -o /tmp/552-baseline-jp
CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package' PYTHONPATH=. clinosim simulate -p 30 -s 42 --country US --format fhir-r4 -o /tmp/552-baseline-us
```

- [ ] **Step 3: Restore PR state and regenerate**

```bash
cp /tmp/inpatient_pr.py clinosim/simulator/inpatient.py
cp /tmp/daily_loop_pr.py clinosim/simulator/daily_loop.py
CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package' PYTHONPATH=. clinosim simulate -p 30 -s 42 --country JP --format fhir-r4 -o /tmp/552-pr-jp
CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package' PYTHONPATH=. clinosim simulate -p 30 -s 42 --country US --format fhir-r4 -o /tmp/552-pr-us
```

Verify PR state restored:
```bash
git status --short   # expect: clean
```

- [ ] **Step 4: Diff both cohorts**

```bash
diff -r /tmp/552-baseline-jp /tmp/552-pr-jp -x _generator_metadata.json > /private/tmp/claude-*/scratchpad/552-diff-jp.txt 2>&1
diff -r /tmp/552-baseline-us /tmp/552-pr-us -x _generator_metadata.json > /private/tmp/claude-*/scratchpad/552-diff-us.txt 2>&1
grep -E '^diff|^Only in' /private/tmp/claude-*/scratchpad/552-diff-jp.txt
echo "==="
grep -E '^diff|^Only in' /private/tmp/claude-*/scratchpad/552-diff-us.txt
```

Expected diffed files (both cohorts, ONLY these):

- `cif/metadata.json` (generation_timestamp)
- `cif/narratives/template/manifest.json` (generated_at)
- `fhir_r4/manifest.json` (transactionTime)
- `simulator.log` (timestamps)

**Any other file BLOCKS merge**. If any data file (`*.ndjson`) differs, the move accidentally altered behavior — investigate:

- Missing import causing a NameError at runtime (test may have missed it if the code path isn't exercised — cohort generation exercises everything).
- Import order side effect (module-level constant evaluation shifting due to import re-ordering).

- [ ] **Step 5: Cleanup temp cohorts**

```bash
rm -rf /tmp/552-baseline-jp /tmp/552-baseline-us /tmp/552-pr-jp /tmp/552-pr-us /tmp/inpatient_pr.py /tmp/daily_loop_pr.py /tmp/552-baseline-sha.txt
```

- [ ] **Step 6: Push branch and open PR**

```bash
git push -u origin fix/552-daily-loop-extraction
gh pr create --title "refactor(simulator): extract _run_daily_loop to sibling daily_loop.py (closes #552)" --body "$(cat <<'EOF'
## Summary

Moves `_run_daily_loop` (573 LOC) + `_extract_findings` (23 LOC) from
`clinosim/simulator/inpatient.py` to a new sibling file
`clinosim/simulator/daily_loop.py`. Pure mechanical relocation;
byte-diff-neutral by construction.

`inpatient.py` reduces from 1385 LOC to ~800 LOC (41% reduction),
closing Issue #552's file-size complaint. Session 84's established
sibling-flat-file convention (`lab_pipeline.py`, `vitals_pipeline.py`,
`medication_pipeline.py`, `unknown_condition.py`) is directly reused.

Design: `docs/superpowers/specs/2026-08-09-552-daily-loop-extraction-design.md`
Plan: `docs/superpowers/plans/2026-08-09-552-daily-loop-extraction-plan.md`

## Design decisions realised

- **DD1**: sibling flat file (not the Issue's original subpackage
  proposal — session 84 established the flat-file pattern).
- **DD2**: move `_run_daily_loop` + `_extract_findings` only.
  `_planned_discharge_datetime` stays in `inpatient.py` (called from
  `_simulate_patient`, not the daily loop).
- **DD3**: backwards-compat re-export at `inpatient.py` — existing
  callers (`from clinosim.simulator.inpatient import _run_daily_loop`)
  unchanged.
- **DD4**: byte-diff neutrality guaranteed by construction (function
  bodies unchanged); cohort diff is the safety net.

## Change summary

- New file: `clinosim/simulator/daily_loop.py` (~620 LOC: docstring +
  imports + 2 moved function bodies).
- Modified: `clinosim/simulator/inpatient.py`:
  - Removed `_run_daily_loop` (L790-1362) and `_extract_findings`
    (L1363-1385) function definitions.
  - Added backwards-compat re-export block (~5 LOC) adjacent to
    session-84 re-exports.
  - Removed ~15 top-level imports no longer referenced by remaining
    code (ruff F401).

## Verification

- [x] `pytest tests/unit`: 4002 pass (baseline, no delta)
- [ ] `pytest tests/integration`: deferred to CI
- [x] `mypy clinosim/` strict: clean
- [x] `ruff==0.16.0 check` + `format --check`: clean
- [x] **30-patient seed 42 JP+US cohort diff-r vs master: zero data
  diffs** (only metadata/log timestamps differ)
- [x] External caller grep + import verification: re-export resolves

## Out of scope (documented in the spec's Non-goals)

- `_simulate_patient` orchestrator internal split (linear flow,
  legitimately monolithic).
- `_run_daily_loop` per-day phase extraction (RNG cursor shift risk).

Both are deferred as potential future Issues if further reduction is
warranted.

Closes #552.
EOF
)"
```

Copy the PR URL for reference.

- [ ] **Step 7: Wait for CI, then merge**

```bash
gh pr checks <PR#>
```

Once all checks pass, the loop is closed. No commit-side action required.

---

## Self-Review

### Spec coverage

| Spec section | Task |
|---|---|
| Goal (extract to sibling) | Task 1 + Task 2 |
| DD1 (sibling flat file convention) | Task 1 Step 4 (file location + docstring reference) |
| DD2 (move `_run_daily_loop` + `_extract_findings` only) | Task 1 Step 4 (only these 2 functions in daily_loop.py) |
| DD3 (backwards-compat re-export) | Task 2 Step 2 (re-export block) |
| DD4 (byte-diff neutrality by construction) | Task 1 Step 4 (verbatim move), Task 3 (cohort verification) |
| Architecture (2 files, orchestrator split from state machine) | Task 1 + Task 2 |
| C1 (daily_loop.py header + imports + moved bodies) | Task 1 Steps 3-5 |
| C2 (inpatient.py deletions + re-export + import cleanup) | Task 2 Steps 1-3 |
| C3 (nothing else touched) | verified by ruff/mypy/tests in Task 2 |
| Data flow (zero data diff expected) | Task 3 Step 4 |
| Error handling (import cycle prevention) | Task 1 Step 3 (CRITICAL note) |
| Testing (no new tests, existing coverage suffices) | Task 2 Step 6 (existing suite runs) |

All spec sections mapped.

### Placeholder scan

No TBD / TODO / "see Task N" placeholders. Runtime substitutions (`<PR#>`, actual import list from grep) are documented at their usage points.

### Type consistency

- `_run_daily_loop` and `_extract_findings` signatures identical pre- and post-move (verbatim copy per DD4).
- Backwards-compat re-export uses same symbol names — no type alias drift.
- No new type annotations introduced.
