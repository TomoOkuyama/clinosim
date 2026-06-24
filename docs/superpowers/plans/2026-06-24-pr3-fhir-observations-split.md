# PR3 — `_fhir_observations.py` Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `clinosim/modules/output/_fhir_observations.py` (727 lines / 31 KB) into three new per-theme builder files while preserving FHIR output byte-for-byte.

**Architecture:** Pure mechanical refactor. Move `_bb_microbiology` (+ `_SUSCEPTIBILITY_DISPLAY` constant), `_build_nursing_observations`, and `_build_immunizations` verbatim into `_fhir_microbiology.py`, `_fhir_nursing.py`, `_fhir_immunization.py`. The residual `_fhir_observations.py` keeps the lab helper + vital builder (lab + vital = canonical numeric Observation use case). `fhir_r4_adapter.py` updates its import block (4 paths instead of 1). No new shared helpers needed in `_fhir_common.py` (PR2 already promoted what was required).

**Tech Stack:** Python 3.11+, ruff, mypy strict, pytest. No new dependencies.

## Global Constraints

- Branch: `refactor/pr3-fhir-observations-split` (already created from master `0ed65f86`)
- Determinism (AD-16): no behavior change permitted; output must be byte-identical to master.
- AD-56: builder registry order in `register_builtin_builders()` must remain unchanged.
- All new files start with `from __future__ import annotations`.
- File header docstring style matches existing `_fhir_*.py` files (one-line summary + 2-3 sentence detail, ending with "Extracted from _fhir_observations.py in PR3 (AD-55 Module Foundation Refactor final piece).").
- Each new file imports **only what it uses** — no superset imports.
- Down-stream caller surface preserved via `noqa: F401` re-exports in `fhir_r4_adapter.py` (same convention as PR1 / PR2 / FA-1).
- Verification gate: all 11 NDJSON sha256 IDENTICAL between master and branch for both US p=2000 and JP p=2000.
- No new unit tests authored — mechanical refactor; existing tests are the regression gate.
- All docs touched by this refactor are updated **in the same PR** (per `feedback_pr_merge_dqr_required`).

## File structure (decisions locked in)

**Files modified:**
- `clinosim/modules/output/_fhir_observations.py` — shrunk from 727 to ~573 lines (lines 1-127, 129-374 removed; lines 376-727 retained; module docstring trimmed)
- `clinosim/modules/output/fhir_r4_adapter.py` — import block at lines 80-86 expanded into 4 lines

**Files created:**
- `clinosim/modules/output/_fhir_microbiology.py` — ~115 lines (header + imports + `_SUSCEPTIBILITY_DISPLAY` + `_bb_microbiology`)
- `clinosim/modules/output/_fhir_nursing.py` — ~210 lines (header + imports + `_build_nursing_observations`)
- `clinosim/modules/output/_fhir_immunization.py` — ~70 lines (header + imports + `_build_immunizations`)

**Files unchanged:**
- `_fhir_common.py` (no new helper promotion needed)
- `_fhir_localization.py` (no API change)
- All other `_fhir_*.py` files
- All `tests/**/*.py` files (mechanical refactor; existing tests serve as gate)

## Verification commands (referenced from multiple tasks)

```bash
# Smoke regression
pytest -m "unit or integration" -q

# Byte-diff generation (master baseline)
git stash
git checkout 0ed65f86
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/pr3_byte_diff/master/us
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP --format fhir-r4 -o scratchpad/pr3_byte_diff/master/jp
git checkout refactor/pr3-fhir-observations-split
git stash pop  # if anything was stashed

# Byte-diff generation (branch)
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/pr3_byte_diff/branch/us
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP --format fhir-r4 -o scratchpad/pr3_byte_diff/branch/jp

# Compare (custom script; see Task 6)
python scratchpad/pr3_byte_diff/compare.py
```

---

### Task 1: Extract `_fhir_microbiology.py`

**Files:**
- Create: `clinosim/modules/output/_fhir_microbiology.py`
- Modify: `clinosim/modules/output/_fhir_observations.py:32-127` (delete `_SUSCEPTIBILITY_DISPLAY` + `_bb_microbiology` block)

**Interfaces:**
- Consumes: `BundleContext`, `_entry`, `_micro_coding` from `_fhir_common`; `_localize_display` from `_fhir_localization`; `code_lookup`, `get_system_uri` from `clinosim.codes`; `load_code_mapping` from `clinosim.locale.loader`
- Produces: `_bb_microbiology(ctx: BundleContext) -> list[dict]` (for adapter import); `_SUSCEPTIBILITY_DISPLAY` is file-private (no external use — grep-verified)

- [ ] **Step 1.1: Create `_fhir_microbiology.py` with verbatim content**

Read the exact byte range to copy:

Run: `sed -n '32,127p' clinosim/modules/output/_fhir_observations.py` (mental check — do NOT execute)

Write the new file with this exact content:

```python
"""FHIR R4 microbiology builder (Specimen + Observation + DiagnosticReport).

Cultures, growth, and antibiotic susceptibilities (AD-55 microbiology
theme). Extracted from _fhir_observations.py in PR3 (AD-55 Module
Foundation Refactor final piece). The ctx-taking builder imports the
shared BundleContext from _fhir_common, so this module never imports back
through the adapter (no cycle).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping
from clinosim.modules.output._fhir_common import (
    BundleContext,
    _entry,
    _micro_coding,
)
from clinosim.modules.output._fhir_localization import _localize_display

_SUSCEPTIBILITY_DISPLAY = {
    "S": {"en": "Susceptible", "ja": "感性"},
    "I": {"en": "Intermediate", "ja": "中間"},
    "R": {"en": "Resistant", "ja": "耐性"},
}


def _bb_microbiology(ctx: BundleContext) -> list[dict]:
    # ... PASTE LINES 39-126 FROM _fhir_observations.py VERBATIM ...
```

**How to actually create:** use `Read` on `_fhir_observations.py` with `offset=32, limit=96` to get lines 32-127, then `Write` the new file by concatenating the header above with the function body. Do NOT retype the function — copy it character-for-character.

- [ ] **Step 1.2: Run pytest smoke to ensure new file imports cleanly**

Run: `python -c "from clinosim.modules.output._fhir_microbiology import _bb_microbiology; print(_bb_microbiology.__name__)"`
Expected output: `_bb_microbiology`

- [ ] **Step 1.3: Delete the moved block from `_fhir_observations.py`**

Delete lines 32-127 (the `_SUSCEPTIBILITY_DISPLAY` constant and the entire `_bb_microbiology` function, including the trailing blank line before `_build_nursing_observations`).

Use `Edit` with `old_string` = the full 32-127 block as it currently appears (read it first with `Read`), `new_string` = empty string (or two blank lines if needed to preserve the canonical "two blank lines before next def" PEP-8 convention — the next def is `_build_nursing_observations` at line 129, so after the delete it should sit directly after the imports/localization import).

Also update the module docstring at line 1-8 to drop "microbiology (Specimen + Observation + DiagnosticReport)" — keep mentions of nursing, immunization, lab, vital for now; the docstring will be re-edited in Task 3 once nursing + immunization also move out.

- [ ] **Step 1.4: Smoke run (file-level)**

Run: `python -c "from clinosim.modules.output._fhir_observations import _build_lab_observation, _build_vital_observations, _build_nursing_observations, _build_immunizations; print('observations imports OK')"`
Expected: `observations imports OK` (nursing + immunization still in observations.py at this point).

Run: `python -c "from clinosim.modules.output._fhir_microbiology import _bb_microbiology; print('micro import OK')"`
Expected: `micro import OK`

- [ ] **Step 1.5: Run unit suite for adapter (no failures expected — adapter still imports `_bb_microbiology` from `_fhir_observations` for now, which will fail)**

Actually: adapter still imports `_bb_microbiology` from `_fhir_observations` — that import would now fail. The unit suite will catch it.

Run: `pytest -m unit -q 2>&1 | tail -30`
Expected: `ImportError: cannot import name '_bb_microbiology' from 'clinosim.modules.output._fhir_observations'` — many failures.

This is **expected at this checkpoint** because Task 4 fixes the adapter import. Tasks 1-4 form a single conceptual unit; the smoke check between them is just to verify the file moved cleanly. Skip pytest at this intermediate checkpoint and rely on Step 1.4 + final Task 5 sweep.

- [ ] **Step 1.6: Commit**

```bash
git add clinosim/modules/output/_fhir_microbiology.py clinosim/modules/output/_fhir_observations.py
git commit -m "$(cat <<'EOF'
refactor(output): extract _fhir_microbiology.py from _fhir_observations.py

Step 1/3 of the _fhir_observations.py theme-by-theme split. Moves
_SUSCEPTIBILITY_DISPLAY constant and _bb_microbiology builder verbatim
into the new per-theme file. Adapter import update deferred to Task 4
(intermediate state will not pass tests; fixed at end of split).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 2: Extract `_fhir_nursing.py`

**Files:**
- Create: `clinosim/modules/output/_fhir_nursing.py`
- Modify: `clinosim/modules/output/_fhir_observations.py` (delete the `_build_nursing_observations` block — originally lines 129-322; line numbers shift after Task 1)

**Interfaces:**
- Consumes: `BundleContext`, `_entry`, `_loinc_coding`, `_survey_category` from `_fhir_common`; `_CATEGORY_DISPLAY_JA`, `_INTERPRETATION_DISPLAY_JA`, `_localize_display`, `_localize_interp` from `_fhir_localization`; `code_lookup`, `get_system_uri` from `clinosim.codes`
- Produces: `_build_nursing_observations(ctx: BundleContext) -> list[dict]`

- [ ] **Step 2.1: Read the nursing block from current `_fhir_observations.py`**

After Task 1, the nursing function has shifted. Locate it via:

Run: `grep -n "^def _build_nursing_observations\|^def _build_immunizations" clinosim/modules/output/_fhir_observations.py`

Note the start and end line numbers of `_build_nursing_observations` (start at the `def` line, end at the blank line before `_build_immunizations`).

Read that range.

- [ ] **Step 2.2: Determine actual imports used by `_build_nursing_observations`**

Scan the nursing function body for these symbol references (every one of these is potentially needed):
- `BundleContext` (in signature)
- `_entry` (for resource wrapping)
- `_loinc_coding` (for LOINC-coded observations like GCS/Braden)
- `_survey_category` (for category=survey)
- `_CATEGORY_DISPLAY_JA` (JP localization)
- `_INTERPRETATION_DISPLAY_JA` (JP localization)
- `_localize_display` (display string localization)
- `_localize_interp` (interpretation localization)
- `code_lookup` (for code → display resolution)
- `get_system_uri` (for system URI resolution)

For each, search the function body. Include only those actually referenced.

- [ ] **Step 2.3: Create `_fhir_nursing.py`**

```python
"""FHIR R4 nursing flowsheet builders (category=survey Observations).

NEWS2, GCS, Braden, Morse, ADL, intake/output. Extracted from
_fhir_observations.py in PR3 (AD-55 Module Foundation Refactor final
piece). The ctx-taking builder imports the shared BundleContext from
_fhir_common, so this module never imports back through the adapter
(no cycle).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules.output._fhir_common import (
    BundleContext,
    _entry,
    _loinc_coding,
    _survey_category,
)
from clinosim.modules.output._fhir_localization import (
    _CATEGORY_DISPLAY_JA,
    _INTERPRETATION_DISPLAY_JA,
    _localize_display,
    _localize_interp,
)


def _build_nursing_observations(ctx: BundleContext) -> list[dict]:
    # ... PASTE FUNCTION BODY VERBATIM ...
```

If Step 2.2 found that some symbols above are NOT referenced in the function body, REMOVE them from the import block (keep "only what is used").

- [ ] **Step 2.4: Smoke import check**

Run: `python -c "from clinosim.modules.output._fhir_nursing import _build_nursing_observations; print('nursing import OK')"`
Expected: `nursing import OK`

If `NameError` on any symbol inside the function body, that symbol was missed in Step 2.2 — add the import and retry.

- [ ] **Step 2.5: Delete the moved block from `_fhir_observations.py`**

Use `Edit` to remove the `_build_nursing_observations` function (everything from `def _build_nursing_observations` through and including the two-blank-lines separator before `_build_immunizations`).

- [ ] **Step 2.6: Verify file state**

Run: `grep -n "^def \|^_SUSCEPTIBILITY" clinosim/modules/output/_fhir_observations.py`
Expected output (after Task 1 + Task 2): only `_build_immunizations`, `_build_lab_observation`, `_build_vital_observations` remain.

- [ ] **Step 2.7: Commit**

```bash
git add clinosim/modules/output/_fhir_nursing.py clinosim/modules/output/_fhir_observations.py
git commit -m "$(cat <<'EOF'
refactor(output): extract _fhir_nursing.py from _fhir_observations.py

Step 2/3 of the _fhir_observations.py theme-by-theme split. Moves
_build_nursing_observations (NEWS2/GCS/Braden/Morse/ADL/I&O) verbatim
into the new per-theme file. Adapter import update deferred to Task 4.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 3: Extract `_fhir_immunization.py`

**Files:**
- Create: `clinosim/modules/output/_fhir_immunization.py`
- Modify: `clinosim/modules/output/_fhir_observations.py` (delete `_build_immunizations` block; also trim module docstring to reflect final scope)

**Interfaces:**
- Consumes: `BundleContext`, `_entry` from `_fhir_common`; `code_lookup`, `get_system_uri` from `clinosim.codes` (plus any `_localize_display` / `_fhir_localization` symbols used in the body — verify)
- Produces: `_build_immunizations(ctx: BundleContext) -> list[dict]`

- [ ] **Step 3.1: Locate the immunization block**

Run: `grep -n "^def _build_immunizations\|^def _build_lab_observation" clinosim/modules/output/_fhir_observations.py`

Note start and end of `_build_immunizations`.

Read the function body.

- [ ] **Step 3.2: Determine actual imports used by `_build_immunizations`**

Scan body for: `BundleContext`, `_entry`, `code_lookup`, `get_system_uri`, `_localize_display`. Include only those actually referenced.

- [ ] **Step 3.3: Create `_fhir_immunization.py`**

```python
"""FHIR R4 Immunization builder (CVX-coded adult vaccine history).

Builds FHIR Immunization resources (not Observation; resource type
distinct) from CIF ImmunizationRecord entries. Extracted from
_fhir_observations.py in PR3 (AD-55 Module Foundation Refactor final
piece). The ctx-taking builder imports the shared BundleContext from
_fhir_common, so this module never imports back through the adapter
(no cycle).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules.output._fhir_common import BundleContext, _entry


def _build_immunizations(ctx: BundleContext) -> list[dict]:
    # ... PASTE FUNCTION BODY VERBATIM ...
```

Adjust imports based on Step 3.2 (drop unused, add any missed).

- [ ] **Step 3.4: Smoke import check**

Run: `python -c "from clinosim.modules.output._fhir_immunization import _build_immunizations; print('immunization import OK')"`
Expected: `immunization import OK`

- [ ] **Step 3.5: Delete the moved block from `_fhir_observations.py` + trim module docstring**

Use `Edit` to remove the `_build_immunizations` function.

Then update the module docstring at the top of `_fhir_observations.py` (originally lines 1-8) from:

```python
"""FHIR R4 Observation-family resource builders (FA-1 Phase 13).

Laboratory + vital-sign Observations, nursing-flowsheet Observations
(NEWS2/GCS/Braden/Morse/ADL/I&O), microbiology (Specimen + Observation +
DiagnosticReport), and Immunization. Extracted verbatim from ``fhir_r4_adapter``;
the ctx-taking builders import the shared BundleContext from _fhir_common, so
this module never imports back through the adapter (no cycle).
"""
```

to:

```python
"""FHIR R4 lab + vital-sign Observation builders (FA-1 Phase 13).

Canonical numeric Observation resources: per-order lab values (via
_build_lab_observation helper) and per-encounter vital signs. Microbiology,
nursing flowsheets, and Immunization were split out in PR3 into
_fhir_microbiology.py / _fhir_nursing.py / _fhir_immunization.py
respectively. The ctx-taking builder imports the shared BundleContext
from _fhir_common, so this module never imports back through the adapter
(no cycle).
"""
```

Also remove any imports from `_fhir_observations.py` that are no longer used after micro / nursing / immunization moved out. Likely candidates to remove if unused by lab + vital:
- `load_code_mapping` (was used by micro only)
- `_micro_coding`
- `_CATEGORY_DISPLAY_JA` (was nursing)
- Some `_localize_*` symbols

Verify by `grep` after each removal: `grep -n "load_code_mapping\|_micro_coding\|_CATEGORY_DISPLAY_JA" clinosim/modules/output/_fhir_observations.py`. If 0 occurrences after deletion, the import can be removed.

- [ ] **Step 3.6: Verify file state**

Run: `grep -n "^def \|^_SUSCEPTIBILITY" clinosim/modules/output/_fhir_observations.py`
Expected: only `_build_lab_observation`, `_build_vital_observations` remain. No `_SUSCEPTIBILITY_DISPLAY` constant.

Run: `wc -l clinosim/modules/output/_fhir_observations.py`
Expected: ~570-580 lines (down from 727).

- [ ] **Step 3.7: Commit**

```bash
git add clinosim/modules/output/_fhir_immunization.py clinosim/modules/output/_fhir_observations.py
git commit -m "$(cat <<'EOF'
refactor(output): extract _fhir_immunization.py from _fhir_observations.py

Step 3/3 of the _fhir_observations.py theme-by-theme split. Moves
_build_immunizations verbatim into the new per-theme file. Also trims
_fhir_observations.py module docstring to reflect its final scope
(lab + vital), and prunes imports no longer used after the micro /
nursing / immunization moves. Adapter import update in Task 4.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 4: Update `fhir_r4_adapter.py` import block

**Files:**
- Modify: `clinosim/modules/output/fhir_r4_adapter.py:80-86` (the current 5-symbol import block from `_fhir_observations`)

**Interfaces:**
- Consumes: the four new module paths produced by Tasks 1-3 + the remaining `_fhir_observations` symbols
- Produces: identical re-export surface — every name (`_bb_microbiology`, `_build_immunizations`, `_build_lab_observation`, `_build_nursing_observations`, `_build_vital_observations`) is still importable from `fhir_r4_adapter` via `noqa: F401`

- [ ] **Step 4.1: Locate the current import block**

Run: `grep -n "from clinosim.modules.output._fhir_observations" clinosim/modules/output/fhir_r4_adapter.py`

Confirm there is exactly one occurrence, around line 80.

- [ ] **Step 4.2: Replace the block**

Use `Edit`:

`old_string`:
```python
from clinosim.modules.output._fhir_observations import (  # noqa: F401
    _bb_microbiology,
    _build_immunizations,
    _build_lab_observation,
    _build_nursing_observations,
    _build_vital_observations,
)
```

`new_string`:
```python
from clinosim.modules.output._fhir_immunization import _build_immunizations  # noqa: F401
from clinosim.modules.output._fhir_microbiology import _bb_microbiology  # noqa: F401
from clinosim.modules.output._fhir_nursing import _build_nursing_observations  # noqa: F401
from clinosim.modules.output._fhir_observations import (  # noqa: F401
    _build_lab_observation,
    _build_vital_observations,
)
```

Alphabetical ordering across the new lines matches the surrounding adapter import style.

- [ ] **Step 4.3: Smoke import check (full adapter surface)**

Run:
```bash
python -c "from clinosim.modules.output.fhir_r4_adapter import _bb_microbiology, _build_immunizations, _build_lab_observation, _build_nursing_observations, _build_vital_observations; print('all 5 symbols re-exported OK')"
```
Expected: `all 5 symbols re-exported OK`

- [ ] **Step 4.4: Verify builder registration order preserved**

Run: `grep -n "_BUNDLE_BUILDERS\|register_builtin_builders\|_bb_microbiology\|_build_immunizations\|_build_nursing_observations" clinosim/modules/output/fhir_r4_adapter.py | head -40`

Confirm the order of registration calls is bit-identical to master. If `_BUNDLE_BUILDERS = [...]` or `register_builtin_builders()` was not edited, this is guaranteed.

- [ ] **Step 4.5: Commit**

```bash
git add clinosim/modules/output/fhir_r4_adapter.py
git commit -m "$(cat <<'EOF'
refactor(output): rewire adapter imports for _fhir_observations split

Final wiring for PR3 mechanical split. Adapter now imports
_bb_microbiology / _build_nursing_observations / _build_immunizations
from their new per-theme files, and only _build_lab_observation +
_build_vital_observations from _fhir_observations. Down-stream re-export
surface preserved via noqa: F401 — every existing
`from ...fhir_r4_adapter import X` keeps working.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

---

### Task 5: Regression — `pytest -m "unit or integration"`

**Files:** none modified

**Interfaces:** none

- [ ] **Step 5.1: Run unit + integration suite**

Run: `pytest -m "unit or integration" -q 2>&1 | tail -10`
Expected: `704 passed` (matches master baseline).

If failures: read each one. Likely causes if any fail:
- A symbol was renamed accidentally (unlikely — verbatim moves)
- An import was missed (catch via `NameError` at test discovery)
- Builder registration order broke (catch via golden test if there's one — actually golden tests run as e2e)

Fix and re-commit before proceeding.

- [ ] **Step 5.2: Run lint / type checks** (only if these are part of the project's pre-commit / CI)

Run: `ruff check clinosim/modules/output/`
Expected: no errors

Run: `mypy clinosim/modules/output/ 2>&1 | tail -20`
Expected: pre-existing mypy noise only; no new errors introduced (mypy "strict" mode but the repo has ~241 pre-existing items per memory).

If new mypy errors specifically about the new files, fix and re-commit.

- [ ] **Step 5.3: No commit needed if tests pass cleanly**

(Bug fixes only get committed if regressions surfaced.)

---

### Task 6: Byte-diff verification (US + JP p=2000)

**Files:**
- Create: `scratchpad/pr3_byte_diff/compare.py`
- Create: `scratchpad/pr3_byte_diff_results.md`
- Generates (scratch — not committed): `scratchpad/pr3_byte_diff/master/{us,jp}/*.ndjson` and `scratchpad/pr3_byte_diff/branch/{us,jp}/*.ndjson`

**Interfaces:** none

- [ ] **Step 6.1: Generate master baseline**

Stash any uncommitted changes (there should be none after Task 5):

Run: `git status -s`
Expected: clean (only `.session-resume-prompt.md` from before).

Check out master commit (do NOT `git checkout master` to avoid moving the branch ref):

```bash
git checkout 0ed65f86
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/pr3_byte_diff/master/us
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP --format fhir-r4 -o scratchpad/pr3_byte_diff/master/jp
git checkout refactor/pr3-fhir-observations-split
```

Expected: each generate command produces NDJSON files under the target directory and exits 0. (~1-3 min per country, depending on machine.)

- [ ] **Step 6.2: Generate branch output**

```bash
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/pr3_byte_diff/branch/us
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP --format fhir-r4 -o scratchpad/pr3_byte_diff/branch/jp
```

- [ ] **Step 6.3: Write the compare script**

Write `scratchpad/pr3_byte_diff/compare.py`:

```python
"""PR3 byte-diff verification: sha256 compare all NDJSON between master and branch."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).parent
COUNTRIES = ["us", "jp"]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    overall_ok = True
    for country in COUNTRIES:
        master_dir = ROOT / "master" / country
        branch_dir = ROOT / "branch" / country
        if not master_dir.exists() or not branch_dir.exists():
            print(f"[{country}] SKIP — missing dir")
            continue
        master_files = sorted(p.name for p in master_dir.glob("*.ndjson"))
        branch_files = sorted(p.name for p in branch_dir.glob("*.ndjson"))
        if master_files != branch_files:
            print(f"[{country}] FAIL — file set differs")
            print(f"  master: {master_files}")
            print(f"  branch: {branch_files}")
            overall_ok = False
            continue
        print(f"[{country}] {len(master_files)} NDJSON files to compare:")
        for name in master_files:
            mh = sha256_of(master_dir / name)
            bh = sha256_of(branch_dir / name)
            status = "IDENTICAL" if mh == bh else "DIFFER"
            print(f"  {name:40s} {status}")
            if mh != bh:
                overall_ok = False
    print()
    print("OVERALL:", "PASS" if overall_ok else "FAIL")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6.4: Run compare**

Run: `python scratchpad/pr3_byte_diff/compare.py`
Expected output: every NDJSON labeled `IDENTICAL`; final line `OVERALL: PASS`.

If any DIFFER: stop. Read the diff (`diff master/us/Observation.ndjson branch/us/Observation.ndjson | head -50`) and root-cause. Likely causes:
- Import order differs in such a way that helper-side caches differ (very unlikely for pure moves)
- A typo in the verbatim copy
- An accidentally edited line in `_fhir_observations.py`

Fix and re-run.

- [ ] **Step 6.5: Write results doc**

Write `scratchpad/pr3_byte_diff_results.md`:

```markdown
# PR3 byte-diff verification results

**Date**: 2026-06-24
**Master baseline**: 0ed65f86
**Branch HEAD**: <fill in after final commit>
**Cohort**: US p=2000 seed=42, JP p=2000 seed=42
**Format**: fhir-r4 (Bulk Data NDJSON)

## Result: OVERALL PASS / FAIL

(paste full output of `python scratchpad/pr3_byte_diff/compare.py`)

## Per-NDJSON status

| File | US | JP |
|---|---|---|
| Patient.ndjson | IDENTICAL | IDENTICAL |
| Encounter.ndjson | IDENTICAL | IDENTICAL |
| Condition.ndjson | IDENTICAL | IDENTICAL |
| MedicationRequest.ndjson | IDENTICAL | IDENTICAL |
| MedicationAdministration.ndjson | IDENTICAL | IDENTICAL |
| Procedure.ndjson | IDENTICAL | IDENTICAL |
| Observation.ndjson | IDENTICAL | IDENTICAL |
| DiagnosticReport.ndjson | IDENTICAL | IDENTICAL |
| Immunization.ndjson | IDENTICAL | IDENTICAL |
| FamilyMemberHistory.ndjson | IDENTICAL | IDENTICAL |
| Coverage.ndjson | n/a | IDENTICAL |

(update the table after the actual compare run — show actual results)

## Conclusion

PR3 is a pure mechanical refactor with no functional change. All NDJSON
files in both US and JP exports are byte-identical to master.
```

- [ ] **Step 6.6: Commit results doc only (not the scratch NDJSON output)**

The NDJSON output and `compare.py` live under `scratchpad/` which is gitignored. Only the results markdown is part of the PR evidence:

```bash
git add scratchpad/pr3_byte_diff_results.md
git commit -m "$(cat <<'EOF'
docs(pr3): byte-diff verification results — all 11 NDJSON IDENTICAL

US p=2000 seed=42 and JP p=2000 seed=42, master 0ed65f86 vs branch HEAD.
All NDJSON files (Patient/Encounter/Condition/MedicationRequest/
MedicationAdministration/Procedure/Observation/DiagnosticReport/
Immunization/FamilyMemberHistory + JP Coverage) match by sha256.
Confirms PR3 is a pure mechanical refactor with zero output delta.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

Note: if `scratchpad/` is gitignored, `git add scratchpad/pr3_byte_diff_results.md` requires `-f` (force):

Run: `git check-ignore scratchpad/pr3_byte_diff_results.md`
- If output: file is ignored → use `git add -f scratchpad/pr3_byte_diff_results.md`
- If no output: not ignored → plain `git add` works

If `scratchpad/` is fully ignored and force-adding feels wrong, move the results file to `docs/reviews/2026-06-24-pr3-byte-diff-results.md` instead.

- [ ] **Step 6.7: Clean up scratch output to free disk**

```bash
rm -rf scratchpad/pr3_byte_diff/master scratchpad/pr3_byte_diff/branch
```

(`compare.py` may stay for re-runs; or remove it too.)

---

### Task 7: Documentation sync

**Files:**
- Modify: `CLAUDE.md` (output sub-section under "Key directories")
- Modify: `clinosim/modules/output/README.md` ("拡張方法 (Extensibility) 総合ガイド" section)
- Modify: `DESIGN.md` (FA-1 entry continuation)
- Modify: `MODULES.md` (`output/` row description nudge)
- Modify: `TODO.md` (mark PR3 complete)
- No change: `docs/CONTRIBUTING-modules.md`, `README.md`, `README.ja.md`

**Interfaces:** none

- [ ] **Step 7.1: `CLAUDE.md` — Key directories**

Find the `output/` line under `## Key directories`:

Run: `grep -n "output/.*CIF\|output/.*fhir_r4_adapter" CLAUDE.md`

Currently reads (approximately):
```
output/        <- CIF → format adapters; fhir_r4_adapter + per-theme _fhir_* builders (FA-1)
```

No change needed (the description already says "per-theme `_fhir_*` builders") — the PR3 split increases the count of per-theme files but does not change the description's truthfulness. **Skip this file unless the description is more specific.**

(Confirm by reading the line; only edit if it lists specific files like "lab/vital/micro/nursing/imm".)

- [ ] **Step 7.2: `clinosim/modules/output/README.md` — Extensibility section**

Open `clinosim/modules/output/README.md`. Find the "拡張方法 (Extensibility) 総合ガイド" section.

Look for any place that lists current per-theme `_fhir_*.py` files (e.g. a code block or table). Add three new files to the list:
- `_fhir_microbiology.py` — Specimen + Observation + DiagnosticReport
- `_fhir_nursing.py` — survey Observations (NEWS2/GCS/Braden/Morse/ADL/I&O)
- `_fhir_immunization.py` — Immunization (CVX)

Also update any mention of "_fhir_observations.py contains lab/vital/nursing/immunization/microbiology" to "_fhir_observations.py contains lab + vital".

If the README does not have such an enumeration, add a small subsection or a sentence noting the PR3 split for orientation.

- [ ] **Step 7.3: `DESIGN.md` — FA-1 entry continuation**

Open `DESIGN.md`. Find the FA-1 entry (search for `FA-1`).

Append a short note at the end of the FA-1 narrative: "PR3 (2026-06-24) split `_fhir_observations.py` further by extracting microbiology, nursing, and immunization into per-theme files (`_fhir_microbiology.py`, `_fhir_nursing.py`, `_fhir_immunization.py`); the residual `_fhir_observations.py` is the canonical lab + vital Observation builder."

- [ ] **Step 7.4: `MODULES.md` — `output/` row nudge**

Open `MODULES.md`. Find the table row for the `output` module.

Currently the description is something like "CIF → FHIR R4 NDJSON / CSV adapters (registry-based)". No change needed if the description does not enumerate per-theme files (module count is unchanged).

Confirm by `grep -n "_fhir_observations\|_fhir_microbiology" MODULES.md`. If 0 occurrences, no edit needed for the inventory.

If there is any mention of the per-theme split, append/update to reflect the new three files.

- [ ] **Step 7.5: `TODO.md` — mark PR3 complete**

Open `TODO.md`. Find the entry referring to PR3 / G3 / `_fhir_observations.py` split.

Mark it complete (matches existing style — likely a checkbox toggle or a bullet move to "Completed" section).

Add a short note: "PR3 (2026-06-24, `0ed65f86` ← branch HEAD) — `_fhir_observations.py` theme-by-theme split, byte-identical."

- [ ] **Step 7.6: Smoke check no docs broke**

Run: `grep -rn "_fhir_observations.py" CLAUDE.md DESIGN.md MODULES.md TODO.md clinosim/modules/output/README.md`

Eyeball each occurrence — they should still make sense post-split (i.e. describing the residual lab + vital scope or noting the split). Fix any stale claim.

- [ ] **Step 7.7: Commit docs sync**

```bash
git add CLAUDE.md DESIGN.md MODULES.md TODO.md clinosim/modules/output/README.md
git commit -m "$(cat <<'EOF'
docs(pr3): sync FA-1 + output / module inventory for theme split

Updates output/README.md Extensibility section to enumerate the three
new per-theme files, appends a continuation note to DESIGN.md FA-1
entry, marks PR3 complete in TODO.md, and nudges MODULES.md /
CLAUDE.md descriptions where they referenced the per-theme builder
collection. README EN/JP and CONTRIBUTING are intentionally not
touched — user-facing interface and module-author pattern unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

(If Steps 7.1 / 7.4 found no edit needed, `git add` only the files actually edited; commit message text still describes the overall sync intent.)

---

### Task 8: Push branch + create PR

**Files:** none

**Interfaces:** none

- [ ] **Step 8.1: Final state check**

Run: `git status -s`
Expected: clean (or only `.session-resume-prompt.md` from before).

Run: `git log --oneline 0ed65f86..HEAD`
Expected: ~7-8 commits — spec, micro extract, nursing extract, immunization extract, adapter rewire, byte-diff results, docs sync (no Task 5 commit since no regression occurred).

- [ ] **Step 8.2: Push branch**

```bash
git push -u origin refactor/pr3-fhir-observations-split
```

- [ ] **Step 8.3: Create PR**

```bash
gh pr create --title "refactor(output): theme-by-theme split of _fhir_observations.py (PR3 / G3)" --body "$(cat <<'EOF'
## Summary

Final structural piece of the AD-55 Module Foundation Refactor series
(PR1 #83 → PR2 #84 → **PR3 this**). Splits the 727-line / 31 KB
`_fhir_observations.py` into three new per-theme files matching the
AD-55 Base enricher themes:

- `_fhir_microbiology.py` (~115 lines) — Specimen + Observation + DiagnosticReport
- `_fhir_nursing.py` (~210 lines) — survey Observations (NEWS2/GCS/Braden/Morse/ADL/I&O)
- `_fhir_immunization.py` (~70 lines) — Immunization (CVX)

The residual `_fhir_observations.py` (~570 lines) keeps the canonical
numeric Observation use case: lab helper + vital builder.

## Verification — byte-diff

All 11 NDJSON sha256 IDENTICAL between master `0ed65f86` and branch HEAD
for both US p=2000 seed=42 and JP p=2000 seed=42. Pure mechanical
refactor with zero output delta.

See `scratchpad/pr3_byte_diff_results.md` for per-file table.

## Test plan

- [x] `pytest -m "unit or integration" -q` → 704 passed
- [x] byte-diff US p=2000 → all 10 NDJSON IDENTICAL
- [x] byte-diff JP p=2000 → all 11 NDJSON IDENTICAL (includes Coverage)
- [x] adapter import surface unchanged (`from ...fhir_r4_adapter import _bb_microbiology` etc. still works via `noqa: F401` re-export)

## Docs sync (in this PR)

- `CLAUDE.md` / `MODULES.md` — output description nudges
- `DESIGN.md` — FA-1 entry continuation
- `clinosim/modules/output/README.md` — Extensibility section updated
- `TODO.md` — PR3 / G3 marked complete
- README EN/JP, CONTRIBUTING-modules.md — intentionally **not** touched (user-facing surface + module-author pattern unchanged)

## Why this lands before device + HAI

device + HAI feature work will add new builders (DeviceUseStatement,
CLABSI/CAUTI/VAP). Landing those in an already-multi-theme blob would
multiply the split cost. PR3 clears the runway for `_fhir_device.py` /
`_fhir_hai.py` to follow the established per-theme convention.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01FXMF1gn2c13esGz7mv9XC5
EOF
)"
```

- [ ] **Step 8.4: Report PR URL**

Capture and print the PR URL returned by `gh pr create`. Done.

---

## Self-Review

**Spec coverage check:**
- Goal §1 (decompose into per-theme files): Tasks 1-3 ✓
- Goal §2 (byte-identical preservation): Task 6 ✓
- Goal §3 (down-stream caller surface preserved): Task 4 + smoke check in Step 4.3 ✓
- Goal §4 (no new `_fhir_common.py` promotion): not implemented (no-op verifies itself) ✓
- Non-goal §1 (no further lab+vital split): Task 3 trims docstring to reflect this, no further split happens ✓
- Non-goal §2 (no rename): not touched ✓
- Non-goal §3 (`_BUNDLE_BUILDERS` order): explicit verify in Step 4.4 ✓
- Verification: Tasks 5 + 6 ✓
- Docs sync: Task 7 ✓

**Placeholder scan:** none. Every step has either a concrete code block or a precise command + expected output.

**Type consistency:** function signatures `_bb_microbiology(ctx: BundleContext) -> list[dict]`, `_build_nursing_observations(ctx: BundleContext) -> list[dict]`, `_build_immunizations(ctx: BundleContext) -> list[dict]` consistent across spec, plan, and adapter import. `_build_lab_observation(...)` retains its multi-arg signature (not touched). `_build_vital_observations(ctx)` retains its single-ctx signature.

Plan is complete and ready for inline execution.
