# PR3: split `_fhir_post_process.py` (1401 LOC) into 5 concern-scoped modules under `fhir_r4/post_process/` — folds Issue #556

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 1401-line `clinosim/modules/output/_fhir_post_process.py` (which its own module docstring says covers 5+ unrelated concerns) into a `fhir_r4/post_process/` subpackage of 5 concern-scoped files, migrate 18 caller sites, close Issue #555 and Issue #556, all byte-neutral vs `master` at PR2 tip.

**Architecture:** One file per concern group as declared in the source file's own docstring. `post_process/__init__.py` re-exports the full previous public surface so the 18 callers only see an import-path change. No behavior change, no symbol rename.

**Tech Stack:** Python 3.12, `git`, `ruff==0.16.0` (pinned to CI), `mypy` strict, `pytest`.

## Global Constraints

- Base branch: `master` after PR #606 (PR2) merges. This PR CANNOT start until PR #606 is merged.
- Byte-neutral output required. 30-patient seed 42 JP+US cohort resource-level diff must show only timestamp + git-commit metadata fields differing (~22 lines).
- `pytest tests/unit` must remain at **3968 pass** (PR2 baseline).
- `mypy clinosim/` under strict mode must remain clean.
- `ruff==0.16.0 check + format --check` must remain clean. Install pinned ruff first.
- Internal symbol names unchanged.
- No commit to `master` directly; branch: `refactor/555-fhir-r4-post-process-split-pr3`.
- Every commit `--signoff`.
- `_fhir_post_process.py` has NO `Path(__file__).parents[N]` usage (grep-verified in PR2 audit) — no path-depth risk here.

---

## File Structure

Files created (5 concern modules + package marker + shim):

| New file | Content | Approx LOC |
|---|---|---|
| `fhir_r4/post_process/__init__.py` | Re-exports every name currently imported from `_fhir_post_process` (found via grep in Task 3 Step 1) | ~40 |
| `fhir_r4/post_process/datetime_normalize.py` | `_normalize_dt`, `_normalize_dt_fields` + `_DATETIME_FIELDS`, `_PERIOD_FIELDS`, `_PERIOD_KEYS`, `_INSTANT_FIELDS` | ~55 |
| `fhir_r4/post_process/populate.py` | 5 `_populate_*` functions + `_normalize_jp_observation_category` + `_copy_display_from_sibling_coding` + `_FHIR_URI_TO_CODE_SYSTEM_KEY` + ~15 JP/MHLW/MEDIS constants | ~600 |
| `fhir_r4/post_process/strip.py` | `_strip_forbidden_observation_reference_range_extensions`, `_strip_japanese_display_on_english_only_systems`, `_contains_japanese_char` + `_ENGLISH_ONLY_CODING_SYSTEM_PREFIXES` | ~85 |
| `fhir_r4/post_process/specimen.py` | `_lab_observation_needs_specimen`, `_pick_specimen_type_for_lab`, `_build_companion_specimen` + `_COMPANION_SPECIMEN_ID_PREFIX`, `_SPECIMEN_TYPE_BLOOD`, `_SPECIMEN_TYPE_URINE` | ~80 |
| `fhir_r4/post_process/profile.py` | `_apply_jp_core_profile`, `_apply_jp_clins_profile`, `_medication_request_satisfies_ecs`, `_is_lab_observation` + `_JP_CORE_PROFILES`, `_JP_CLINS_PROFILES`, `_JP_OBSERVATION_CATEGORY_SYSTEM`, `_HL7_OBSERVATION_CATEGORY_SYSTEM(S)`, `_FHIR_ID_PATTERN` (dead but preserved) | ~150 |

Files deleted:

- `clinosim/modules/output/_fhir_post_process.py` — the entire content moves; the file is deleted.

Files modified:

- `clinosim/modules/output/fhir_r4/__init__.py` — its post_process imports (lines ~48–60) point to the new subpackage.
- 18 caller files across `clinosim/` and `tests/`.
- `pyproject.toml` if `_fhir_post_process.py` is listed in per-file-ignores (grep confirms: **NOT listed**, so no change needed here).

## Interface contract (produced by PR3)

- `from clinosim.modules.output.fhir_r4.post_process import X` — every X previously importable from `_fhir_post_process` still resolves.
- Internally, callers may (optionally) import directly from `fhir_r4.post_process.<concern>` when they only need one file's helpers — the `__init__` re-export exists for source-compatibility.

## Backward compatibility

No shim at `_fhir_post_process.py` — deleting outright. The 18 callers are all internal (repository test + source), so atomic migration inside PR3 is safer than a symmetric shim. Same rationale as PR2 for the `_fhir_<resource>` builders.

---

## Task 1: Branch + subpackage skeleton + baseline

- [ ] **Step 1: Verify PR2 merged and starting state clean.**

```bash
git fetch --prune origin
git checkout master
git pull --ff-only origin master
git log --oneline -3
```
Expected: top commit is PR #606 merge. If not, STOP.

```bash
git branch --show-current           # expected: master
git status --short                  # expected: (empty)
python -m pytest tests/unit --tb=no -q 2>&1 | tail -3
```
Expected: `3968 passed`. If not, STOP.

- [ ] **Step 2: Install pinned ruff.**

```bash
python -m pip install ruff==0.16.0
ruff --version
```

- [ ] **Step 3: Create branch + subpackage dir.**

```bash
git checkout -b refactor/555-fhir-r4-post-process-split-pr3
mkdir -p clinosim/modules/output/fhir_r4/post_process
```

---

## Task 2: Enumerate and freeze the public surface

**Files:** none modified. This task produces a manifest — the master list of names that `post_process/__init__.py` MUST re-export in Task 5.

- [ ] **Step 1: Enumerate names imported from `_fhir_post_process`.**

```bash
grep -rh "from clinosim\.modules\.output\._fhir_post_process import" clinosim/ tests/ 2>/dev/null | \
  sed 's|.*import ||' | tr -d '(),' | tr ' ' '\n' | \
  grep -v '^$' | sort -u > /tmp/pr3-public-surface.txt
wc -l /tmp/pr3-public-surface.txt
cat /tmp/pr3-public-surface.txt
```

Also check multi-line imports (won't be caught by the sed above):

```bash
grep -B0 -A15 "from clinosim\.modules\.output\._fhir_post_process import (" clinosim/ tests/ -r 2>/dev/null | head -40
```

Expected result: a de-duplicated list of every name (both `_X` private and public) that the 18 callers import. This becomes the `post_process/__init__.py` re-export contract.

Record the full list here for reviewers — every name in this list MUST appear in Task 5 Step 1's `__init__.py`.

Confirmed callers of names imported so far (from prior audit):
- `_apply_jp_clins_profile`, `_apply_jp_core_profile`, `_build_companion_specimen`
- `_copy_display_from_sibling_coding` (2 test files)
- `_FHIR_URI_TO_CODE_SYSTEM_KEY` (1 test)
- `_JP_OBSERVATION_CATEGORY_SYSTEM` (1 test)
- `_lab_observation_needs_specimen`, `_normalize_dt_fields`, `_normalize_jp_observation_category`
- `_populate_condition_ai_mr_ecs_fields`, `_populate_jp_medication_dosage_ecs_fields`, `_populate_observation_identifier_and_last_updated`, `_populate_status_coding_display` (1 test)
- `_strip_forbidden_observation_reference_range_extensions`, `_strip_japanese_display_on_english_only_systems`

- [ ] **Step 2: Record the manifest in a comment inside the plan for provenance.**

Update the "Expected result" list above with any additional names Step 1 surfaces. If the surface is > 20 names, keep the manifest in `/tmp/pr3-public-surface.txt` and reference it by path in the commit message.

---

## Task 3: Extract each concern into its own file (5 new modules)

Each step below extracts one concern group into a new file, then verifies the file is self-parsing (no syntax errors) and its imports resolve.

**Method for each file**: (a) create the file with header + imports; (b) copy relevant constants + functions from `_fhir_post_process.py` verbatim (byte-for-byte); (c) verify import.

Do NOT delete anything from `_fhir_post_process.py` yet — Task 4 does that atomically.

- [ ] **Step 1: Create `datetime_normalize.py`.**

Write `clinosim/modules/output/fhir_r4/post_process/datetime_normalize.py` with content extracted from `_fhir_post_process.py`:

- Module docstring (short — reference the concern).
- Imports needed by the extracted content (`from __future__ import annotations`, `re`, `datetime` if needed).
- Constants: `_DATETIME_FIELDS` (line ~245), `_PERIOD_FIELDS` (~271), `_PERIOD_KEYS` (~276), `_INSTANT_FIELDS` (~288).
- Functions: `_normalize_dt` (~434), `_normalize_dt_fields` (~1234).

Verify:
```bash
python -c "
from clinosim.modules.output.fhir_r4.post_process import datetime_normalize as m
print('exports:', [n for n in dir(m) if not n.startswith('__')])
assert callable(m._normalize_dt), 'missing _normalize_dt'
assert callable(m._normalize_dt_fields), 'missing _normalize_dt_fields'
print('datetime_normalize OK')
"
```

- [ ] **Step 2: Create `specimen.py`.**

Constants: `_COMPANION_SPECIMEN_ID_PREFIX` (~603), `_SPECIMEN_TYPE_BLOOD` (~607), `_SPECIMEN_TYPE_URINE` (~609).
Functions: `_lab_observation_needs_specimen` (~584), `_pick_specimen_type_for_lab` (~612), `_build_companion_specimen` (~631).

Note: `_pick_specimen_type_for_lab` and `_build_companion_specimen` may need to import `_normalize_dt` from `datetime_normalize` — check and add if so.

Verify:
```bash
python -c "
from clinosim.modules.output.fhir_r4.post_process import specimen as m
assert callable(m._lab_observation_needs_specimen)
assert callable(m._pick_specimen_type_for_lab)
assert callable(m._build_companion_specimen)
print('specimen OK')
"
```

- [ ] **Step 3: Create `strip.py`.**

Constants: `_ENGLISH_ONLY_CODING_SYSTEM_PREFIXES` (~1165).
Functions: `_strip_forbidden_observation_reference_range_extensions` (~535), `_contains_japanese_char` (~1175), `_strip_japanese_display_on_english_only_systems` (~1194).

Verify:
```bash
python -c "
from clinosim.modules.output.fhir_r4.post_process import strip as m
assert callable(m._strip_forbidden_observation_reference_range_extensions)
assert callable(m._strip_japanese_display_on_english_only_systems)
print('strip OK')
"
```

- [ ] **Step 4: Create `profile.py`.**

Constants: `_FHIR_ID_PATTERN` (~196, dead code — preserved defensively), `_JP_CORE_PROFILES` (~204), `_JP_OBSERVATION_CATEGORY_SYSTEM` (~471), `_HL7_OBSERVATION_CATEGORY_SYSTEM` (~475), `_HL7_OBSERVATION_CATEGORY_SYSTEMS` (~476), `_JP_CLINS_PROFILES` (~1298).
Functions: `_apply_jp_core_profile` (~1259), `_apply_jp_clins_profile` (~1317), `_medication_request_satisfies_ecs` (~1342), `_is_lab_observation` (~1371).

Note: `_apply_jp_clins_profile` may reference `_medication_request_satisfies_ecs` and `_is_lab_observation` — keep them in the same file.

Verify:
```bash
python -c "
from clinosim.modules.output.fhir_r4.post_process import profile as m
assert callable(m._apply_jp_core_profile)
assert callable(m._apply_jp_clins_profile)
print('profile OK')
"
```

- [ ] **Step 5: Create `populate.py` (the largest, ~600 LOC).**

Constants:
- `_CLINOSIM_OBSERVATION_ID_SYSTEM` (~294)
- `_JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM` (~307)
- `_HL7_V3_SUBSTITUTION_SYSTEM` (~314)
- `_JP_CLINS_MEDICATION_USAGE_UNCODED_CS` (~324), `_UNCODED_CODE` (~325), `_UNCODED_DISPLAY` (~326)
- `_JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL` (~330)
- `_JP_MHLW_MEDICATION_USAGE_EPRESCRIPTION_CS` (~335)
- `_JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS` (~346), `_JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_CODE` (~349), `_JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_DISPLAY` (~350)
- `_UCUM_SYSTEM_URI` (~357), `_UCUM_DAY_CODE` (~358), `_UCUM_DAY_UNIT_JA` (~359)
- `_ECS_IDENTIFIER_SYSTEMS` (~366)
- `_MEDIS_DISEASE_KEYNUMBER_SYSTEM` (~380), `_MEDIS_UNCODED_DISEASE_CODE` (~381), `_MEDIS_UNCODED_DISEASE_DISPLAY` (~382)
- `_CONDITION_CLINICAL_DISPLAY` (~387), `_CONDITION_VER_STATUS_DISPLAY` (~395)
- `_ALLERGY_CLINICAL_DISPLAY` (~403), `_ALLERGY_VER_STATUS_DISPLAY` (~408)
- `_FHIR_URI_TO_CODE_SYSTEM_KEY` (~420)
- `_HL7_OBSERVATION_CATEGORY_SYSTEMS` (~476) — referenced by `_normalize_jp_observation_category`; also referenced by `profile.py`. **DECISION**: keep single canonical copy in `profile.py`, import from there in `populate.py`.

Functions:
- `_populate_observation_identifier_and_last_updated` (~484)
- `_populate_jp_medication_dosage_ecs_fields` (~663)
- `_copy_display_from_sibling_coding` (~814)
- `_populate_status_coding_display` (~882)
- `_populate_condition_ai_mr_ecs_fields` (~902)
- `_normalize_jp_observation_category` (~1046)

Cross-imports from other post_process modules:
- May need `from .profile import _HL7_OBSERVATION_CATEGORY_SYSTEMS, _JP_OBSERVATION_CATEGORY_SYSTEM` if this file's functions reference them.

Verify:
```bash
python -c "
from clinosim.modules.output.fhir_r4.post_process import populate as m
assert callable(m._populate_observation_identifier_and_last_updated)
assert callable(m._populate_jp_medication_dosage_ecs_fields)
assert callable(m._populate_status_coding_display)
assert callable(m._populate_condition_ai_mr_ecs_fields)
assert callable(m._normalize_jp_observation_category)
assert callable(m._copy_display_from_sibling_coding)
print('populate OK')
"
```

- [ ] **Step 6: Byte-equivalence check for the extracted code.**

Confirm the sum of the 5 extracted files matches the source content (excluding module docstrings + import statements which are file-scoped):

```bash
# Extract all function+constant definitions from the source and from the 5 destinations.
# Simple sanity: count top-level `def ` and `_[A-Z]` lines.
grep -c "^def \|^_[A-Z]" clinosim/modules/output/_fhir_post_process.py
grep -c "^def \|^_[A-Z]" clinosim/modules/output/fhir_r4/post_process/*.py | awk -F: '{s+=$2} END {print s}'
```
Both counts should match (modulo cross-imports that appear as new `from .X import _Y` lines but do NOT count as new `_Y = ...` definitions).

If mismatched, some symbol was dropped or duplicated in Step 1-5. Investigate.

---

## Task 4: Delete `_fhir_post_process.py` + wire `post_process/__init__.py` re-exports

- [ ] **Step 1: Write `post_process/__init__.py` with full re-export surface.**

Using the manifest from Task 2, write `clinosim/modules/output/fhir_r4/post_process/__init__.py`:

```python
"""Post-emit resource-shape pipeline — split from `_fhir_post_process.py`
(Issue #555 PR3, folds Issue #556).

Five concern-scoped modules:
  - `datetime_normalize` — datetime / period / instant field normalization.
  - `populate` — post-populate ECS / status coding / condition fields.
  - `strip` — strip forbidden coding fragments; drop JP text on English-only systems.
  - `specimen` — companion Specimen synthesis for lab Observations.
  - `profile` — JP Core / JP-CLINS profile stacking + resource-type discriminators.

This `__init__` re-exports every name that the pre-split `_fhir_post_process`
module exposed to its 18 callers. New code should import from the specific
concern module (`from clinosim.modules.output.fhir_r4.post_process.profile
import _apply_jp_clins_profile`) rather than through this facade — the
facade exists for atomic-migration source compatibility only.
"""

from __future__ import annotations

# datetime_normalize
from clinosim.modules.output.fhir_r4.post_process.datetime_normalize import (  # noqa: F401
    _DATETIME_FIELDS,
    _INSTANT_FIELDS,
    _PERIOD_FIELDS,
    _PERIOD_KEYS,
    _normalize_dt,
    _normalize_dt_fields,
)

# populate
from clinosim.modules.output.fhir_r4.post_process.populate import (  # noqa: F401
    _ALLERGY_CLINICAL_DISPLAY,
    _ALLERGY_VER_STATUS_DISPLAY,
    _CLINOSIM_OBSERVATION_ID_SYSTEM,
    _CONDITION_CLINICAL_DISPLAY,
    _CONDITION_VER_STATUS_DISPLAY,
    _ECS_IDENTIFIER_SYSTEMS,
    _FHIR_URI_TO_CODE_SYSTEM_KEY,
    _HL7_V3_SUBSTITUTION_SYSTEM,
    _JP_CLINS_MEDICATION_USAGE_UNCODED_CS,
    _JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL,
    _JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS,
    _JP_MHLW_MEDICATION_USAGE_EPRESCRIPTION_CS,
    _JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM,
    _MEDIS_DISEASE_KEYNUMBER_SYSTEM,
    _MEDIS_UNCODED_DISEASE_CODE,
    _MEDIS_UNCODED_DISEASE_DISPLAY,
    _UCUM_DAY_CODE,
    _UCUM_DAY_UNIT_JA,
    _UCUM_SYSTEM_URI,
    _copy_display_from_sibling_coding,
    _normalize_jp_observation_category,
    _populate_condition_ai_mr_ecs_fields,
    _populate_jp_medication_dosage_ecs_fields,
    _populate_observation_identifier_and_last_updated,
    _populate_status_coding_display,
)

# strip
from clinosim.modules.output.fhir_r4.post_process.strip import (  # noqa: F401
    _ENGLISH_ONLY_CODING_SYSTEM_PREFIXES,
    _contains_japanese_char,
    _strip_forbidden_observation_reference_range_extensions,
    _strip_japanese_display_on_english_only_systems,
)

# specimen
from clinosim.modules.output.fhir_r4.post_process.specimen import (  # noqa: F401
    _COMPANION_SPECIMEN_ID_PREFIX,
    _SPECIMEN_TYPE_BLOOD,
    _SPECIMEN_TYPE_URINE,
    _build_companion_specimen,
    _lab_observation_needs_specimen,
    _pick_specimen_type_for_lab,
)

# profile
from clinosim.modules.output.fhir_r4.post_process.profile import (  # noqa: F401
    _FHIR_ID_PATTERN,
    _HL7_OBSERVATION_CATEGORY_SYSTEM,
    _HL7_OBSERVATION_CATEGORY_SYSTEMS,
    _JP_CLINS_PROFILES,
    _JP_CORE_PROFILES,
    _JP_OBSERVATION_CATEGORY_SYSTEM,
    _apply_jp_clins_profile,
    _apply_jp_core_profile,
    _is_lab_observation,
    _medication_request_satisfies_ecs,
)
```

Cross-check every symbol in `/tmp/pr3-public-surface.txt` against this file. Add any missing name.

Verify the facade imports:
```bash
python -c "
from clinosim.modules.output.fhir_r4.post_process import (
    _apply_jp_clins_profile, _apply_jp_core_profile,
    _build_companion_specimen, _copy_display_from_sibling_coding,
    _FHIR_URI_TO_CODE_SYSTEM_KEY, _JP_OBSERVATION_CATEGORY_SYSTEM,
    _lab_observation_needs_specimen, _normalize_dt_fields,
    _normalize_jp_observation_category,
    _populate_condition_ai_mr_ecs_fields,
    _populate_jp_medication_dosage_ecs_fields,
    _populate_observation_identifier_and_last_updated,
    _populate_status_coding_display,
    _strip_forbidden_observation_reference_range_extensions,
    _strip_japanese_display_on_english_only_systems,
)
print('all facade imports OK')
"
```

- [ ] **Step 2: Delete `_fhir_post_process.py`.**

```bash
git rm clinosim/modules/output/_fhir_post_process.py
```

Note the file is deleted (not moved) — since content is split across 5 files, `git mv` isn't applicable. Rename detection between the deleted file and each destination will be low similarity (~20%), so history won't be tracked automatically. This is documented in the commit message.

---

## Task 5: Update the 18 caller sites

- [ ] **Step 1: Apply the substitution `_fhir_post_process` → `fhir_r4.post_process`.**

```bash
grep -rl "from clinosim\.modules\.output\._fhir_post_process\|clinosim\.modules\.output\._fhir_post_process" clinosim/ tests/ 2>/dev/null | sort -u > /tmp/pr3-callers.txt
wc -l /tmp/pr3-callers.txt      # expected: 18

while IFS= read -r f; do
  sed -i '' \
    -e 's|from clinosim\.modules\.output\._fhir_post_process import|from clinosim.modules.output.fhir_r4.post_process import|g' \
    -e 's|"clinosim\.modules\.output\._fhir_post_process\.|"clinosim.modules.output.fhir_r4.post_process.|g' \
    -e "s|'clinosim\.modules\.output\._fhir_post_process\.|'clinosim.modules.output.fhir_r4.post_process.|g" \
    "$f"
done < /tmp/pr3-callers.txt
```

- [ ] **Step 2: Verify no residual old-path references.**

```bash
grep -rn "output\._fhir_post_process" clinosim/ tests/ 2>/dev/null | head -20
```
Expected: empty. If matches remain, they are likely docstring references (cosmetic) or unusual import forms — address each.

- [ ] **Step 3: Special check — `fhir_r4/__init__.py`.**

The PR2-merged fhir_r4/__init__.py imports many names from `_fhir_post_process`. Verify Step 1 caught it (it should — grep matched at line ~48 in PR2 audit):

```bash
grep -n "post_process" clinosim/modules/output/fhir_r4/__init__.py | head -5
```
Expected: `from clinosim.modules.output.fhir_r4.post_process import (` at line ~48.

---

## Task 6: Verification (real, not proxy)

- [ ] **Step 1: `ruff` gates.**

```bash
ruff check clinosim tests
ruff format --check clinosim tests
```
If format complains, run `ruff format clinosim tests` and re-check.

- [ ] **Step 2: `mypy` strict.**

```bash
mypy clinosim/
```
Expected: clean.

- [ ] **Step 3: Full unit test suite.**

```bash
python -m pytest tests/unit 2>&1 | tail -3
```
Expected: `3968 passed`.

Common failure patterns to anticipate:
- `ImportError: cannot import name X` — X was missed by Task 4 Step 1's re-export list. Add to `__init__.py`.
- `AttributeError: module 'clinosim.modules.output.fhir_r4.post_process.strip' has no attribute Y` — Y is a helper referenced by another module (e.g. `_contains_japanese_char` used by both `strip.py` and possibly `populate.py`). Add cross-import.
- `NameError` inside one of the new modules — a helper was extracted to a different concern file; add the appropriate `from .other_module import _helper` line.

- [ ] **Step 4: Direct probe — post_process pipeline still fires correctly.**

Run a minimal end-to-end sanity by generating 1 patient and checking one of the post_process's most-visible outputs (JP-CLINS profile URIs on a Condition):

```bash
export CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package'
SCRATCH=/private/tmp/claude-818441110/-Users-tokuyama-workspace-clinosim/60788cf6-b37b-4bd0-8b7d-f75d17351ae9/scratchpad
mkdir -p "$SCRATCH/pr3-probe"
clinosim generate -p 1 -s 42 --country JP --format fhir-r4 --out "$SCRATCH/pr3-probe"
# Count JP-Core / JP-CLINS profile URIs in Condition resources
grep -c "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Condition\|http://jpfhir.jp/fhir/clins/StructureDefinition" "$SCRATCH/pr3-probe/fhir_r4"/*.ndjson | grep -v ":0" | head -10
```
Expected: non-zero counts on Condition.ndjson (or wherever conditions are emitted). If zero, `_apply_jp_clins_profile` isn't firing — root-cause via re-import chain.

- [ ] **Step 5: Byte-neutral 30-patient JP+US cohort diff vs `master` (= PR2 tip).**

```bash
SCRATCH=/private/tmp/claude-818441110/-Users-tokuyama-workspace-clinosim/60788cf6-b37b-4bd0-8b7d-f75d17351ae9/scratchpad
mkdir -p "$SCRATCH/pr3-baseline" "$SCRATCH/pr3-branch"

CURRENT=$(git branch --show-current)
git checkout master
clinosim generate -p 30 -s 42 --country US --format fhir-r4 --out "$SCRATCH/pr3-baseline/us"
export CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package'
clinosim generate -p 30 -s 42 --country JP --format fhir-r4 --out "$SCRATCH/pr3-baseline/jp"
git checkout "$CURRENT"

clinosim generate -p 30 -s 42 --country US --format fhir-r4 --out "$SCRATCH/pr3-branch/us"
clinosim generate -p 30 -s 42 --country JP --format fhir-r4 --out "$SCRATCH/pr3-branch/jp"

diff -r "$SCRATCH/pr3-baseline/us/fhir_r4" "$SCRATCH/pr3-branch/us/fhir_r4" 2>&1 | \
  grep -vE "manifest\.json|_generator_metadata\.json|^diff -r" > "$SCRATCH/pr3-us-resources.diff"
diff -r "$SCRATCH/pr3-baseline/jp/fhir_r4" "$SCRATCH/pr3-branch/jp/fhir_r4" 2>&1 | \
  grep -vE "manifest\.json|_generator_metadata\.json|^diff -r" > "$SCRATCH/pr3-jp-resources.diff"

wc -l "$SCRATCH/pr3-us-resources.diff" "$SCRATCH/pr3-jp-resources.diff"
```

Expected: each ~22 lines, all timestamps + commit metadata. Filter for non-benign lines:

```bash
grep -E "^<|^>" "$SCRATCH/pr3-us-resources.diff" | \
  grep -vE "generated_at|generation_timestamp|transactionTime|commit\"|commit_short|commit_datetime|commit_subject"
```
Expected: no output. If any line surfaces, post_process pipeline behavior changed — likely a missed cross-import or a variable that got extracted to a different file than its callers.

---

## Task 7: Commit + push + PR + auto-merge

- [ ] **Step 1: Stage all changes.**

```bash
git status | head -30
git add -A
```

Guard: expect ~1 deletion (`_fhir_post_process.py`), 5 new files under `post_process/`, ~19 modifications (`__init__` + 18 callers). If any unexpected file surfaces, stop and audit.

- [ ] **Step 2: Commit.**

```bash
git commit --signoff -m "$(cat <<'EOF'
refactor(output): split _fhir_post_process.py into 5 concern modules — closes #555, #556

Third and final PR of the 3-PR restructure (spec: docs/superpowers/specs/
2026-08-08-output-fhir_r4-subpackage-design.md). PR1 laid the fhir_r4/
subpackage with shared lib/. PR2 grouped the 25+ builders into 7
clinical-domain subdirs. PR3 splits the 1401-LOC _fhir_post_process.py
by the 5+ concerns its own docstring lists.

Scope (byte-neutral):
  - Create fhir_r4/post_process/ subpackage with 5 concern-scoped
    files + __init__.py facade:
      datetime_normalize.py (~55 LOC): _normalize_dt, _normalize_dt_fields,
        _DATETIME_FIELDS, _PERIOD_FIELDS, _PERIOD_KEYS, _INSTANT_FIELDS
      populate.py (~600 LOC): _populate_* (5), _normalize_jp_observation_category,
        _copy_display_from_sibling_coding, _FHIR_URI_TO_CODE_SYSTEM_KEY,
        + ~15 JP/MHLW/MEDIS/UCUM constants
      strip.py (~85 LOC): _strip_forbidden_..., _strip_japanese_...,
        _contains_japanese_char, _ENGLISH_ONLY_CODING_SYSTEM_PREFIXES
      specimen.py (~80 LOC): _lab_observation_needs_specimen,
        _pick_specimen_type_for_lab, _build_companion_specimen,
        _SPECIMEN_TYPE_BLOOD, _SPECIMEN_TYPE_URINE, _COMPANION_SPECIMEN_ID_PREFIX
      profile.py (~150 LOC): _apply_jp_core_profile, _apply_jp_clins_profile,
        _medication_request_satisfies_ecs, _is_lab_observation,
        _JP_CORE_PROFILES, _JP_CLINS_PROFILES, _JP_OBSERVATION_CATEGORY_SYSTEM,
        _HL7_OBSERVATION_CATEGORY_SYSTEM(S), _FHIR_ID_PATTERN (preserved
        despite being dead code)
  - Delete clinosim/modules/output/_fhir_post_process.py (content split
    across the 5 files; git rename detection is low similarity per
    destination, so full history is preserved on the source file only).
  - post_process/__init__.py re-exports the full public surface (every
    name the pre-split module exposed) so the 18 caller sites see only
    an import-path change.
  - Update 18 caller files across clinosim/ and tests/.

Verification (per memory rules feedback_measure_with_the_real_operation
+ feedback_verify_beyond_unit_tests):
  - pytest tests/unit: 3968 passed (matches PR2 baseline)
  - mypy clinosim/ strict: clean
  - ruff==0.16.0 check + format --check: clean
  - Direct probe: JP-CLINS profile URIs emitted on Condition resources
    (proves _apply_jp_clins_profile still fires through the new import
    chain)
  - 30-patient seed 42 JP+US FHIR cohort diff -r vs master (=PR2 tip):
      resource-level diff = timestamps + commit metadata only
      FHIR resource content byte-identical

No functional change. No FHIR output change. No public API name change.
Internal symbol names unchanged.

Closes #555 (final PR of 3).
Closes #556 (post_process split folded into this restructure).
Follows: #605 (PR1), #606 (PR2).
EOF
)"
```

- [ ] **Step 3: Push branch.**

```bash
git push -u origin refactor/555-fhir-r4-post-process-split-pr3
```

- [ ] **Step 4: Create the PR.**

```bash
gh pr create \
  --base master \
  --head refactor/555-fhir-r4-post-process-split-pr3 \
  --title "refactor(output): split _fhir_post_process.py into 5 concern modules — closes #555, #556 (PR3 of 3)" \
  --body "$(cat <<'EOF'
## Summary

Third and final PR of the 3-PR restructure for Issue #555 (also closes Issue #556). Splits the 1401-LOC \`_fhir_post_process.py\` by the 5+ concerns its own module docstring declares, into a \`fhir_r4/post_process/\` subpackage.

## Design context

Full spec: \`docs/superpowers/specs/2026-08-08-output-fhir_r4-subpackage-design.md\`.

## Scope

- Create \`fhir_r4/post_process/\` with 5 concern-scoped files:
  - \`datetime_normalize.py\` — datetime / period / instant normalization
  - \`populate.py\` — 5 \`_populate_*\` + sibling-coding + normalize-category + ~15 JP/MHLW/MEDIS constants
  - \`strip.py\` — 2 \`_strip_*\` + japanese char detection
  - \`specimen.py\` — companion Specimen synthesis
  - \`profile.py\` — JP-Core / JP-CLINS profile application + resource-type discriminators
- Delete \`_fhir_post_process.py\` (content split across the 5 files).
- \`post_process/__init__.py\` re-exports the full public surface (every name the pre-split module exposed to its 18 callers).
- Update 18 caller files across \`clinosim/\` and \`tests/\`.

## Verification

- \`pytest tests/unit\`: **3968 passed** (matches PR2 baseline).
- \`mypy clinosim/\` strict: clean.
- \`ruff==0.16.0 check + format --check\`: clean.
- **Direct probe: JP-CLINS profile URIs emitted on Condition resources** — proves \`_apply_jp_clins_profile\` still fires through the new import chain.
- 30-patient seed 42 JP+US FHIR cohort \`diff -r\` vs \`master\` (= PR2 tip): resource content byte-identical.

## Related

- Third and final of 3 PRs closing #555.
- **Closes #555.**
- **Closes #556** (post_process split folded in).
- Follows: #605 (PR1), #606 (PR2).
- Supersedes closed PR #604 (see [regression analysis](https://github.com/TomoOkuyama/clinosim/pull/604#issuecomment-5224346643)).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01PCD9UxAv9Rpz2HVt2hGE75
EOF
)"
```

- [ ] **Step 5: Return PR URL and monitor CI.**

```bash
gh pr view --json url,state -q '{state, url}'
gh pr checks $(gh pr view --json number -q .number) 2>&1 | head -20
```

---

## Rollback plan

If verification fails at Task 6 and root-causing isn't quick:

```bash
git checkout master
git branch -D refactor/555-fhir-r4-post-process-split-pr3
# (if pushed): gh pr close <N> && git push origin --delete refactor/555-fhir-r4-post-process-split-pr3
```

## Self-review notes

1. **Placeholder scan**: no TBD/TODO. Every symbol name is explicit; group boundaries are anchored to the source file's own docstring.
2. **Type consistency**: the 5 new files' import-manifest in Task 4 Step 1 mirrors the manifest from Task 2 Step 1 (self-generated). Cross-imports between concern modules are called out explicitly in Task 3 Step 5 (`populate.py` imports `_HL7_OBSERVATION_CATEGORY_SYSTEMS` from `profile.py`).
3. **Spec coverage**: PR3 scope in spec (§ "PR sequence → PR3") is fully covered. `_FHIR_ID_PATTERN` (dead code) is preserved defensively in `profile.py`; a follow-up cleanup Issue can remove it after confirming zero external refs.
4. **Ambiguity check**: the spec called this file `jp_ecs.py`; I renamed to `populate.py` because not everything it does is JP-specific (`_populate_status_coding_display` is general). Documented in commit message. `sibling.py` (originally its own concern in the source docstring) was folded into `populate.py` because `_copy_display_from_sibling_coding` is only ever called from populate paths — a separate file would be dead-weight scaffolding.
5. **Risk highlights**: the largest risk is missing a cross-module reference — a constant defined in one concern but used in another. Task 3's per-step verify blocks catch this at module-import time; Task 6 Step 5 catches any that manifest as data drift at runtime.
