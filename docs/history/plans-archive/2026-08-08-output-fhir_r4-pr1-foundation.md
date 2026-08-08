# PR1: `fhir_r4/` foundation + `fhir_r4/lib/` shared library

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` — this is a mechanical refactor, not a TDD build. Each task ends with a defined green state (tests pass, verification clean). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `clinosim/modules/output/fhir_r4/` subpackage with `lib/` for shared FHIR helpers, move 6 shared library files, migrate 102+ callers, and rework the FHIR facade — all byte-neutral vs `master`.

**Architecture:** Subpackage restructure with two shim strategies: (a) `_fhir_common.py` continues as the Issue #545 deprecation shim (updated to point at the new home), (b) `fhir_r4_adapter.py` becomes a thin re-export shim so 100+ callers referencing `from clinosim.modules.output.fhir_r4_adapter import ...` keep working. `output/fhir_common.py` is deleted (canonical becomes `output/fhir_r4/lib/common.py`; the Issue #545 shim `_fhir_common.py` bridges legacy `_fhir_common` callers to the new location).

**Tech Stack:** Python 3.12, `git mv`, `ruff`, `mypy` strict, `pytest`.

## Global Constraints

Copied verbatim from the design spec (`docs/superpowers/specs/2026-08-08-output-fhir_r4-subpackage-design.md`):

- Byte-neutral output required. 30-patient seed 42 JP+US cohort `diff -r` must be **0 lines** vs `origin/master`.
- `pytest tests/unit` must remain at **3968 pass** (session 84 wrap baseline). Any regression is a blocker.
- `mypy clinosim/` under strict mode must remain clean.
- `ruff check clinosim tests` and `ruff format --check clinosim tests` must remain clean (pre-push hook will refuse otherwise).
- Internal symbol names (`_build_X`, `_bb_Y` etc.) are **unchanged**. Symbol renaming is Issue #545 Step 2, out of scope.
- Must not commit to `master` directly. All work happens on branch `refactor/555-fhir-r4-foundation-pr1`.
- Every commit uses `--signoff` (DCO check).
- `_fhir_common.py` shim behavior from Issue #545 (`DeprecationWarning` emission + explicit re-imports of `_UCUM_CODE_MAP`, `_append_tz_if_missing`, `_coding_with_display`, `_escape_html`, `_parse_dose_for_mar`, `_sha1_b64`, `_social_category`, `_to_ucum_code`, `_validate_route_maps`, `_value`) **must be preserved** — only its target of re-export changes.
- Any file that uses `Path(__file__).resolve().parents[N]` MUST have its `N` audited when moved. For PR1 files only `_fhir_generator_metadata.py` uses `Path(__file__)` and it walks up via `.git` detection (relocation-safe) — no fix needed. Files in PR2 scope (`_fhir_medications.py`, `lab_coding_package.py`) DO have hardcoded `parents[N]` that must be fixed in that PR; noted here for continuity.

---

## File Structure

Files created (new):

- `clinosim/modules/output/fhir_r4/__init__.py` — facade with `register_bundle_builder`, `available_builders`, and every top-level export currently in `fhir_r4_adapter.py`.
- `clinosim/modules/output/fhir_r4/lib/__init__.py` — package marker (empty except docstring).
- `clinosim/modules/output/fhir_r4/lib/common.py` — moved from `output/fhir_common.py` (unchanged content).
- `clinosim/modules/output/fhir_r4/lib/localization.py` — moved from `output/_fhir_localization.py` (unchanged content).
- `clinosim/modules/output/fhir_r4/lib/reference_data.py` — moved from `output/_fhir_reference_data.py` (unchanged content).
- `clinosim/modules/output/fhir_r4/lib/inline_bb.py` — moved from `output/_fhir_inline_bb.py` (unchanged content).
- `clinosim/modules/output/fhir_r4/lib/generator_metadata.py` — moved from `output/_fhir_generator_metadata.py` (unchanged content).
- `clinosim/modules/output/fhir_r4/lib/ids.py` — moved from `output/opaque_ids.py` (unchanged content).

Files modified (existing):

- `clinosim/modules/output/fhir_r4_adapter.py` — content reduced to thin re-export shim.
- `clinosim/modules/output/_fhir_common.py` — Issue #545 shim; only its re-export target changes (still emits `DeprecationWarning`, still re-imports private helpers).
- `clinosim/modules/output/__init__.py` — public re-exports may need re-anchoring to `fhir_r4/__init__.py`.
- ~83 caller files across `clinosim/` and `tests/` — import path substitutions only.

Files deleted:

- `clinosim/modules/output/fhir_common.py` — content moved to `fhir_r4/lib/common.py`. No shim needed here (`_fhir_common.py` from #545 bridges old callers).
- `clinosim/modules/output/_fhir_localization.py` — moved to `fhir_r4/lib/localization.py`. No shim (callers all migrated).
- `clinosim/modules/output/_fhir_reference_data.py` — moved. No shim.
- `clinosim/modules/output/_fhir_inline_bb.py` — moved. No shim.
- `clinosim/modules/output/_fhir_generator_metadata.py` — moved. No shim.
- `clinosim/modules/output/opaque_ids.py` — moved. No shim.

## Interface contract (produced by PR1)

Downstream PR2/PR3 will consume:

- `from clinosim.modules.output.fhir_r4.lib.common import <anything>` — canonical shared helper path.
- `from clinosim.modules.output.fhir_r4.lib.{localization,reference_data,inline_bb,generator_metadata,ids} import <anything>`.
- `from clinosim.modules.output.fhir_r4 import register_bundle_builder, available_builders` — facade.
- `from clinosim.modules.output.fhir_r4_adapter import <anything>` — still works via shim.
- `from clinosim.modules.output._fhir_common import <anything>` — still works via #545 shim (with `DeprecationWarning`).
- Remaining `_fhir_<resource>.py` builder files stay at `output/` root at end of PR1; PR2 moves them.

---

## Task 1: Branch + design doc commit + subpackage skeleton

**Files:**
- Create: `clinosim/modules/output/fhir_r4/__init__.py` (empty stub for now)
- Create: `clinosim/modules/output/fhir_r4/lib/__init__.py`
- Commit: `docs/superpowers/specs/2026-08-08-output-fhir_r4-subpackage-design.md`

**Interfaces:**
- Produces: `clinosim.modules.output.fhir_r4` importable as a package. `fhir_r4.lib` importable as a sub-package.

- [ ] **Step 1: Verify starting state.**

Run:
```bash
git branch --show-current  # expected: master
git rev-parse HEAD           # expected: c20f059b16
git status --short           # expected: (empty)
python -m pytest tests/unit --tb=no -q 2>&1 | tail -3
```
Expected last line: `3968 passed, 1 warning in <NNs>`.

If any check fails, STOP and reconcile before proceeding.

- [ ] **Step 2: Create branch.**

```bash
git checkout -b refactor/555-fhir-r4-foundation-pr1
```

- [ ] **Step 3: Create subpackage skeleton.**

```bash
mkdir -p clinosim/modules/output/fhir_r4/lib
```

Write `clinosim/modules/output/fhir_r4/__init__.py`:
```python
"""FHIR R4 output subsystem — Issue #555.

Public facade for FHIR R4 bundle generation. The concrete builder and
post-processing implementations live under `fhir_r4/<domain>/` (PR2) and
`fhir_r4/post_process/` (PR3). Shared helpers live under `fhir_r4/lib/` (PR1).

During PR1 this module is a placeholder; PR1 Task 4 promotes the current
`fhir_r4_adapter.py` facade content into this __init__.
"""

from __future__ import annotations
```

Write `clinosim/modules/output/fhir_r4/lib/__init__.py`:
```python
"""Shared FHIR helpers used by every domain-scoped builder (Issue #555).

- `common` — helpers previously at `output/fhir_common.py` (Issue #545 promotion).
- `localization` — locale-aware display resolution.
- `reference_data` — cross-resource lookup tables.
- `inline_bb` — inline bundle-builder helpers.
- `generator_metadata` — sim-params snapshot writer.
- `ids` — deterministic Resource.id derivation (Issue #349).
"""

from __future__ import annotations
```

- [ ] **Step 4: Verify the new packages import.**

```bash
python -c "import clinosim.modules.output.fhir_r4; import clinosim.modules.output.fhir_r4.lib"
```
Expected: no output, exit 0.

- [ ] **Step 5: Stage design doc.**

```bash
git add docs/superpowers/specs/2026-08-08-output-fhir_r4-subpackage-design.md \
        docs/superpowers/plans/2026-08-08-output-fhir_r4-pr1-foundation.md \
        clinosim/modules/output/fhir_r4/__init__.py \
        clinosim/modules/output/fhir_r4/lib/__init__.py
git status
```
Expected: only the 4 files above are staged.

- [ ] **Step 6: Commit skeleton.**

```bash
git commit --signoff -m "$(cat <<'EOF'
refactor(output): create fhir_r4 subpackage skeleton — Issue #555 PR1 setup

Add empty `fhir_r4/` and `fhir_r4/lib/` packages with descriptive
docstrings so subsequent PR1 tasks can `git mv` files into them.

Also commits the shared design spec and PR1 implementation plan so the
subpackage layout is documented in-tree for reviewers.

Byte-neutral: no runtime code moved yet.
EOF
)"
```

---

## Task 2: Move 6 shared library files atomically with all caller updates

**Files:**
- Move: 6 files listed in "Files created (new)" section above via `git mv`.
- Modify: 83 caller files across `clinosim/` and `tests/`.
- Modify: `clinosim/modules/output/__init__.py` if it imports any of the moved names directly.
- Delete: none yet (`_fhir_common.py` shim update is Task 4).

**Interfaces:**
- Consumes: subpackage skeleton from Task 1.
- Produces: 6 shared library files at `output/fhir_r4/lib/`, all callers pointing at new paths, tests green.

- [ ] **Step 1: Move common.py.**

```bash
git mv clinosim/modules/output/fhir_common.py clinosim/modules/output/fhir_r4/lib/common.py
```

- [ ] **Step 2: Move localization / reference_data / inline_bb / generator_metadata / ids.**

```bash
git mv clinosim/modules/output/_fhir_localization.py     clinosim/modules/output/fhir_r4/lib/localization.py
git mv clinosim/modules/output/_fhir_reference_data.py   clinosim/modules/output/fhir_r4/lib/reference_data.py
git mv clinosim/modules/output/_fhir_inline_bb.py        clinosim/modules/output/fhir_r4/lib/inline_bb.py
git mv clinosim/modules/output/_fhir_generator_metadata.py clinosim/modules/output/fhir_r4/lib/generator_metadata.py
git mv clinosim/modules/output/opaque_ids.py             clinosim/modules/output/fhir_r4/lib/ids.py
```

- [ ] **Step 3: Verify moves.**

```bash
git status --short
ls clinosim/modules/output/fhir_r4/lib/
```
Expected: 6 R (rename) entries in status; `lib/` shows `__init__.py`, `common.py`, `localization.py`, `reference_data.py`, `inline_bb.py`, `generator_metadata.py`, `ids.py`.

- [ ] **Step 4: Audit `__file__` usage in the moved files.**

```bash
grep -n "__file__\|Path(__file__)" clinosim/modules/output/fhir_r4/lib/*.py
```

Expected output (only one match, in `generator_metadata.py`):
```
clinosim/modules/output/fhir_r4/lib/generator_metadata.py:143:    here = Path(__file__).resolve()
clinosim/modules/output/fhir_r4/lib/generator_metadata.py:144:    for parent in (here, *here.parents):
```

The `generator_metadata.py` pattern walks ancestors looking for `.git` — relocation-safe. **No fix required for PR1**. If any other `__file__` match appears (which would indicate the codebase changed since this plan was written), STOP and audit before proceeding.

- [ ] **Step 5: Update internal cross-references among the moved files.**

Some `fhir_r4/lib/*.py` files import each other. Update their internal imports to the new subpackage paths. Run:

```bash
grep -n "from clinosim.modules.output" clinosim/modules/output/fhir_r4/lib/*.py
```

For each match that references one of the 6 old paths (`fhir_common`, `_fhir_localization`, `_fhir_reference_data`, `_fhir_inline_bb`, `_fhir_generator_metadata`, `opaque_ids`), rewrite to the new `fhir_r4.lib.<name>` path. Substitution map:

| Old | New |
|---|---|
| `from clinosim.modules.output.fhir_common import` | `from clinosim.modules.output.fhir_r4.lib.common import` |
| `from clinosim.modules.output._fhir_localization import` | `from clinosim.modules.output.fhir_r4.lib.localization import` |
| `from clinosim.modules.output._fhir_reference_data import` | `from clinosim.modules.output.fhir_r4.lib.reference_data import` |
| `from clinosim.modules.output._fhir_inline_bb import` | `from clinosim.modules.output.fhir_r4.lib.inline_bb import` |
| `from clinosim.modules.output._fhir_generator_metadata import` | `from clinosim.modules.output.fhir_r4.lib.generator_metadata import` |
| `from clinosim.modules.output.opaque_ids import` | `from clinosim.modules.output.fhir_r4.lib.ids import` |

Use ripgrep + sed for mechanical rewrite:

```bash
for f in clinosim/modules/output/fhir_r4/lib/*.py; do
  sed -i '' \
    -e 's|from clinosim.modules.output.fhir_common import|from clinosim.modules.output.fhir_r4.lib.common import|g' \
    -e 's|from clinosim.modules.output._fhir_localization import|from clinosim.modules.output.fhir_r4.lib.localization import|g' \
    -e 's|from clinosim.modules.output._fhir_reference_data import|from clinosim.modules.output.fhir_r4.lib.reference_data import|g' \
    -e 's|from clinosim.modules.output._fhir_inline_bb import|from clinosim.modules.output.fhir_r4.lib.inline_bb import|g' \
    -e 's|from clinosim.modules.output._fhir_generator_metadata import|from clinosim.modules.output.fhir_r4.lib.generator_metadata import|g' \
    -e 's|from clinosim.modules.output.opaque_ids import|from clinosim.modules.output.fhir_r4.lib.ids import|g' \
    "$f"
done
```

Verify no residual references to the old paths in the moved files:
```bash
grep -n "output.fhir_common\|output._fhir_localization\|output._fhir_reference_data\|output._fhir_inline_bb\|output._fhir_generator_metadata\|output.opaque_ids" clinosim/modules/output/fhir_r4/lib/*.py
```
Expected: no output.

- [ ] **Step 6: Update all external callers (83 files).**

Apply the same substitution across the whole tree (excluding the moved files themselves which Step 5 already handled, and excluding the shim `_fhir_common.py` which Task 4 handles):

```bash
# Get the set of caller files (excluding shim + moved files themselves)
mapfile -t callers < <(grep -rl \
  -e "from clinosim.modules.output.fhir_common" \
  -e "from clinosim.modules.output._fhir_localization" \
  -e "from clinosim.modules.output._fhir_reference_data" \
  -e "from clinosim.modules.output._fhir_inline_bb" \
  -e "from clinosim.modules.output._fhir_generator_metadata" \
  -e "from clinosim.modules.output.opaque_ids" \
  clinosim/ tests/ 2>/dev/null | grep -v "clinosim/modules/output/_fhir_common.py" | grep -v "clinosim/modules/output/fhir_r4/lib/")

echo "Caller files to update: ${#callers[@]}"

for f in "${callers[@]}"; do
  sed -i '' \
    -e 's|from clinosim.modules.output.fhir_common import|from clinosim.modules.output.fhir_r4.lib.common import|g' \
    -e 's|from clinosim.modules.output._fhir_localization import|from clinosim.modules.output.fhir_r4.lib.localization import|g' \
    -e 's|from clinosim.modules.output._fhir_reference_data import|from clinosim.modules.output.fhir_r4.lib.reference_data import|g' \
    -e 's|from clinosim.modules.output._fhir_inline_bb import|from clinosim.modules.output.fhir_r4.lib.inline_bb import|g' \
    -e 's|from clinosim.modules.output._fhir_generator_metadata import|from clinosim.modules.output.fhir_r4.lib.generator_metadata import|g' \
    -e 's|from clinosim.modules.output.opaque_ids import|from clinosim.modules.output.fhir_r4.lib.ids import|g' \
    "$f"
done
```

Note: `_fhir_common.py` (the #545 shim) is EXCLUDED because it deliberately re-imports from the old public `fhir_common` name for its `DeprecationWarning`+re-export contract. Task 4 rewrites the shim to target `fhir_r4.lib.common`.

Note: the exclusion also skips `clinosim/modules/output/*.py` files that already point at `fhir_r4/lib/` after Step 5.

- [ ] **Step 7: Verify no residual old-path references anywhere except the shim.**

```bash
grep -rn "output.fhir_common\|output._fhir_localization\|output._fhir_reference_data\|output._fhir_inline_bb\|output._fhir_generator_metadata\|output.opaque_ids" clinosim/ tests/ 2>/dev/null | grep -v "clinosim/modules/output/_fhir_common.py"
```
Expected: no output.

If any lines remain, they may be non-standard import forms (e.g. multi-line `from X import (\n Y,\n Z,\n)`). Rewrite them by hand.

- [ ] **Step 8: Run unit tests as a sanity check (facade updates come next).**

```bash
python -m pytest tests/unit --tb=short -q 2>&1 | tail -20
```

Expected: some failures related to `fhir_r4_adapter` still importing from old paths (Task 3 fixes) and `_fhir_common.py` shim broken (Task 4 fixes). Note the failure count. **Do NOT proceed to Task 3 if tests fail for reasons unrelated to those two categories** — investigate first.

---

## Task 3: Rework `fhir_r4_adapter.py` — content into `fhir_r4/__init__.py`, leave thin shim

**Files:**
- Modify: `clinosim/modules/output/fhir_r4/__init__.py` — becomes the real facade (absorbs content of `fhir_r4_adapter.py`).
- Modify: `clinosim/modules/output/fhir_r4_adapter.py` — reduced to thin re-export shim.
- Modify: `clinosim/modules/output/__init__.py` — verify `register_bundle_builder`, `available_builders` re-exports still resolve (may not need change if we keep the shim).

**Interfaces:**
- Consumes: `fhir_r4/lib/` from Task 2.
- Produces: `from clinosim.modules.output.fhir_r4 import register_bundle_builder, available_builders` works. `from clinosim.modules.output.fhir_r4_adapter import <same>` still works via shim.

- [ ] **Step 1: Move `fhir_r4_adapter.py` content into `fhir_r4/__init__.py`.**

```bash
# Preserve git history via rename detection: use a helper commit sequence
# rather than plain overwrite.
git mv clinosim/modules/output/fhir_r4_adapter.py clinosim/modules/output/fhir_r4/__init__.py
```

Wait — this would overwrite the placeholder `__init__.py` and confuse rename detection. Instead:

```bash
# Delete the placeholder __init__.py first so rename detection picks the mv up cleanly.
git rm clinosim/modules/output/fhir_r4/__init__.py
git mv clinosim/modules/output/fhir_r4_adapter.py clinosim/modules/output/fhir_r4/__init__.py
```

- [ ] **Step 2: Update the new `__init__.py`'s imports to reference `fhir_r4.lib`.**

The former `fhir_r4_adapter.py` imports many `_fhir_*` names. After the mv it still does. Update its internal imports to point at `fhir_r4/lib/*` for the 6 moved files (other `_fhir_<resource>` remain untouched — PR2 handles them):

```bash
sed -i '' \
  -e 's|from clinosim.modules.output.fhir_common import|from clinosim.modules.output.fhir_r4.lib.common import|g' \
  -e 's|from clinosim.modules.output._fhir_localization import|from clinosim.modules.output.fhir_r4.lib.localization import|g' \
  -e 's|from clinosim.modules.output._fhir_reference_data import|from clinosim.modules.output.fhir_r4.lib.reference_data import|g' \
  -e 's|from clinosim.modules.output._fhir_inline_bb import|from clinosim.modules.output.fhir_r4.lib.inline_bb import|g' \
  -e 's|from clinosim.modules.output._fhir_generator_metadata import|from clinosim.modules.output.fhir_r4.lib.generator_metadata import|g' \
  -e 's|from clinosim.modules.output.opaque_ids import|from clinosim.modules.output.fhir_r4.lib.ids import|g' \
  clinosim/modules/output/fhir_r4/__init__.py
```

- [ ] **Step 3: Prepend the subpackage docstring.**

Read the current top of the file:
```bash
head -3 clinosim/modules/output/fhir_r4/__init__.py
```

If the docstring starts with `"""FHIR R4 adapter — Stage 3: ...`, that's the original facade docstring. Leave it — it accurately describes the module's role. If you want a note that this was promoted from `fhir_r4_adapter.py`, add ONE comment above the docstring:

```python
# Promoted from `fhir_r4_adapter.py` (Issue #555 PR1). A thin shim remains at
# `fhir_r4_adapter.py` for backward-compat with pre-migration import paths.
```

- [ ] **Step 4: Create the `fhir_r4_adapter.py` thin shim.**

Write `clinosim/modules/output/fhir_r4_adapter.py`:

```python
"""Backwards-compat shim for `fhir_r4_adapter` — Issue #555 PR1.

The FHIR R4 facade was promoted to `clinosim.modules.output.fhir_r4`
(the subpackage's `__init__`). Callers may continue to import from
`fhir_r4_adapter` for one release cycle; new code should use the
subpackage path directly.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4 import *  # noqa: E402, F401, F403
```

Note: unlike the `_fhir_common.py` shim, this shim does NOT emit a `DeprecationWarning` because `fhir_r4_adapter` was never "deprecated" — it is being promoted to a cleaner subpackage location as part of an OSS-hygiene restructure. If callers should be warned in a follow-up, that's a separate decision (out of PR1 scope).

Verify the shim's `*` import surface covers all names 128 callers use:
```bash
grep -rh "from clinosim.modules.output.fhir_r4_adapter import" clinosim/ tests/ 2>/dev/null | \
  sed 's|.*import ||' | tr ',' '\n' | sed 's/[()]//g' | tr -d ' ' | sort -u
```

Then check each name is in `fhir_r4/__init__.py`'s public surface (either in `__all__` if defined, or as a module-level def not starting with `_`). If any name is missing (private-underscore imports would be the common failure), add explicit re-imports to the shim:

```python
# Non-`__all__` names historically imported from `fhir_r4_adapter`:
from clinosim.modules.output.fhir_r4 import (  # noqa: E402, F401
    _some_private_helper,
    # ...
)
```

- [ ] **Step 5: Sanity-check that `fhir_r4/__init__.py` can still be imported.**

```bash
python -c "from clinosim.modules.output.fhir_r4 import register_bundle_builder, available_builders; print('OK')"
python -c "from clinosim.modules.output.fhir_r4_adapter import register_bundle_builder, available_builders; print('OK')"
```
Expected: both print `OK`.

If a name error surfaces, add the missing re-import to the shim per Step 4.

---

## Task 4: Update `_fhir_common.py` shim to point at new home

**Files:**
- Modify: `clinosim/modules/output/_fhir_common.py`

**Interfaces:**
- Consumes: `fhir_r4/lib/common.py` from Task 2.
- Produces: `from clinosim.modules.output._fhir_common import <anything>` continues to emit `DeprecationWarning` and re-exports the same public + private helper surface as before, now sourced from `fhir_r4/lib/common`.

- [ ] **Step 1: Read current shim state.**

```bash
cat clinosim/modules/output/_fhir_common.py
```

Expected: shim from Issue #545 with `DeprecationWarning` referring to `fhir_common`. It imports from `clinosim.modules.output.fhir_common`.

- [ ] **Step 2: Rewrite the shim to point at `fhir_r4.lib.common`.**

Write `clinosim/modules/output/_fhir_common.py`:

```python
"""Deprecated compatibility shim (Issue #545 → Issue #555).

`_fhir_common` was originally promoted to `fhir_common` because 69
external importers across `clinosim/` and `tests/` already treated it
as public (Issue #545). Issue #555 then moved it to
`clinosim.modules.output.fhir_r4.lib.common` as part of the FHIR
subpackage restructure.

This shim remains for one release cycle to keep pre-migration imports
working. Migrate to::

    from clinosim.modules.output.fhir_r4.lib.common import ...

`from clinosim.modules.output._fhir_common import ...` continues to
resolve but emits ``DeprecationWarning`` on first import per Python
interpreter session.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "`clinosim.modules.output._fhir_common` is a deprecated compatibility "
    "shim; import from `clinosim.modules.output.fhir_r4.lib.common` instead. "
    "See Issues #545 and #555 for the migration guide.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export the entire public API so `from _fhir_common import X` keeps
# working for X in `fhir_r4.lib.common.__all__` AND for the underscore-prefixed
# helpers that are not part of `__all__` but that callers historically
# imported by name.
from clinosim.modules.output.fhir_r4.lib.common import *  # noqa: E402, F401, F403

# The `*` import only imports names listed in `__all__`. Re-import
# non-`__all__` helpers explicitly so `from _fhir_common import
# _parse_dose_for_mar` (etc) still resolves under the shim.
from clinosim.modules.output.fhir_r4.lib.common import (  # noqa: E402, F401
    _UCUM_CODE_MAP,
    _append_tz_if_missing,
    _coding_with_display,
    _escape_html,
    _parse_dose_for_mar,
    _sha1_b64,
    _social_category,
    _to_ucum_code,
    _validate_route_maps,
    _value,
)
```

Rationale: mirrors the Issue #545 shim's structure verbatim (including the explicit private-name re-imports) — only the source module and the docstring change. This preserves 100% of the shim's behavior: `DeprecationWarning` on first import + explicit re-export of every previously-accessible name.

- [ ] **Step 3: Verify shim behavior.**

```bash
python -c "
import warnings
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter('always')
    from clinosim.modules.output._fhir_common import _parse_dose_for_mar, BundleContext
    dw = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(dw) == 1, f'expected 1 DeprecationWarning, got {len(dw)}'
    assert '_fhir_common' in str(dw[0].message)
    print('OK: shim emits DeprecationWarning and re-exports both public + private helpers')
"
```
Expected: `OK: shim emits DeprecationWarning ...`.

---

## Task 5: Verification (real, not proxy)

**Files:** none modified. This task is pure verification per memory rules `feedback_measure_with_the_real_operation.md` and `feedback_verify_beyond_unit_tests.md`.

**Interfaces:**
- Consumes: state at end of Task 4.
- Produces: verified proof that PR1 is byte-neutral, passing, and clean.

- [ ] **Step 1: Run `ruff` gates.**

```bash
ruff check clinosim tests
ruff format --check clinosim tests
```
Expected: both clean. If format complains, run `ruff format clinosim tests` and re-check.

- [ ] **Step 2: Run `mypy` under strict mode.**

```bash
mypy clinosim/
```
Expected: no new errors (baseline is clean at session 84 wrap). If new errors appear, investigate before proceeding.

- [ ] **Step 3: Full unit test suite.**

```bash
python -m pytest tests/unit 2>&1 | tee /tmp/pr1-unit.log | tail -3
```
Expected last line: `3968 passed, 1 warning in <NNs>` (matches master baseline). **Anything less is a blocker** — do not push a PR with regressions.

If any test fails, examine `/tmp/pr1-unit.log` for the failure category:
- Import errors → a caller was missed by Task 2 Step 6, or the shim in Task 3/4 is missing a re-export
- Assertion failures on data → surface an unaccounted-for `__file__` regression or side-effect (should not happen in PR1 scope)

- [ ] **Step 4: Direct probe of the top regression vector.**

Explicitly verify the pattern PR #604 broke (memory: `feedback_verify_effect_not_intent.md`):

```bash
python -c "
from clinosim.modules.output.fhir_r4.lib.common import BundleContext
print('common import OK')
"

python -c "
from clinosim.modules.output.fhir_r4.lib.generator_metadata import _find_repo_root
root = _find_repo_root()
assert root is not None and (root / '.git').exists(), f'repo root broken: {root}'
print(f'generator_metadata _find_repo_root OK: {root}')
"
```
Expected: both print OK-messages. If `_find_repo_root` returns None or a wrong dir, the `Path(__file__)` walk broke.

- [ ] **Step 5: Byte-neutral 30-patient JP+US cohort diff.**

```bash
SCRATCH=/private/tmp/claude-818441110/-Users-tokuyama-workspace-clinosim/60788cf6-b37b-4bd0-8b7d-f75d17351ae9/scratchpad
mkdir -p "$SCRATCH/pr1-baseline" "$SCRATCH/pr1-branch"

# Baseline from master
git stash --keep-index --include-untracked  # save nothing (there is nothing) but reset just-in-case
CURRENT=$(git branch --show-current)
git checkout master
clinosim generate -p 30 -s 42 --country US --format fhir-r4 --out "$SCRATCH/pr1-baseline/us"
export CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package'
clinosim generate -p 30 -s 42 --country JP --format fhir-r4 --out "$SCRATCH/pr1-baseline/jp"
git checkout "$CURRENT"

# Branch cohort
clinosim generate -p 30 -s 42 --country US --format fhir-r4 --out "$SCRATCH/pr1-branch/us"
clinosim generate -p 30 -s 42 --country JP --format fhir-r4 --out "$SCRATCH/pr1-branch/jp"

# Compare
diff -r "$SCRATCH/pr1-baseline/us" "$SCRATCH/pr1-branch/us" > "$SCRATCH/pr1-us.diff"
diff -r "$SCRATCH/pr1-baseline/jp" "$SCRATCH/pr1-branch/jp" > "$SCRATCH/pr1-jp.diff"
wc -l "$SCRATCH/pr1-us.diff" "$SCRATCH/pr1-jp.diff"
```
Expected: both diff files are **0 lines**. If either has any content, PR1 is NOT byte-neutral — surface the divergence and root-cause before pushing.

Common failure modes to check first when diff is non-zero:
- Any file in `fhir_r4/lib/` accidentally lost `__all__` entries during the mv
- The `fhir_r4_adapter.py` shim missing a re-import that changes builder dispatch behavior
- A caller file's import got mangled by sed (multi-line `from X import (\n Y,\n Z,\n)` patterns are the usual culprit)

---

## Task 6: Commit + push + PR

**Files:** none modified beyond the working-tree state at the end of Task 5.

**Interfaces:**
- Consumes: green verification state from Task 5.
- Produces: PR opened against `master`, ready for review.

- [ ] **Step 1: Stage all changes.**

```bash
git status
git add -A
git status  # confirm no unexpected files
```

Expected: staged changes = 6 renames + `fhir_r4/__init__.py` (from adapter rename) + `_fhir_common.py` (modified shim) + `fhir_r4_adapter.py` (new shim) + `fhir_r4/lib/__init__.py` + ~83 modified caller files.

**Guard**: if any file outside `clinosim/modules/output/`, `clinosim/**/*.py`, `tests/**/*.py`, or `docs/superpowers/{specs,plans}/` shows in status, stop and audit.

- [ ] **Step 2: Commit.**

```bash
git commit --signoff -m "$(cat <<'EOF'
refactor(output): create fhir_r4/lib/ shared library — Issue #555 PR1

Foundation PR of the 3-PR restructure (spec: docs/superpowers/specs/
2026-08-08-output-fhir_r4-subpackage-design.md). PR1 lays the subpackage
skeleton and moves the 6 shared FHIR library modules; PR2 moves the
25+ resource builders into clinical-domain subdirs; PR3 splits the
1370-LOC _fhir_post_process.py by concern (folding Issue #556).

Scope of this PR (byte-neutral):
  - Create clinosim/modules/output/fhir_r4/ + fhir_r4/lib/ subpackages.
  - git mv 6 shared library files into fhir_r4/lib/:
      fhir_common.py           → fhir_r4/lib/common.py
      _fhir_localization.py    → fhir_r4/lib/localization.py
      _fhir_reference_data.py  → fhir_r4/lib/reference_data.py
      _fhir_inline_bb.py       → fhir_r4/lib/inline_bb.py
      _fhir_generator_metadata.py → fhir_r4/lib/generator_metadata.py
      opaque_ids.py            → fhir_r4/lib/ids.py
  - Promote fhir_r4_adapter.py content into fhir_r4/__init__.py so
    `from clinosim.modules.output.fhir_r4 import ...` becomes the
    canonical facade path.
  - Leave fhir_r4_adapter.py as a thin re-export shim (128 caller sites
    keep working with no source changes).
  - Update _fhir_common.py deprecation shim (from Issue #545) to
    re-export from fhir_r4/lib/common while preserving its
    DeprecationWarning emission and explicit private-helper re-imports.
  - Migrate 83 caller sites across clinosim/ and tests/ to the new
    fhir_r4.lib.<name> import paths.

Verification (per memory rules feedback_measure_with_the_real_operation
+ feedback_verify_beyond_unit_tests):
  - pytest tests/unit: 3968 passed (matches master baseline exactly)
  - mypy clinosim/ strict: clean
  - ruff check + format --check: clean
  - 30-patient seed 42 JP+US FHIR cohort diff -r vs master: 0 lines
  - Direct probe of _find_repo_root() and BundleContext import: OK

No functional change. No FHIR output change. No public API name change.
Internal symbol names (_build_X, _bb_Y) unchanged — those are Issue #545
Step 2 and remain out of scope here.

Related: closes-partial #555 (PR1 of 3). PR2 moves builders into
demographics/, encounters/, medications/, labs/, procedures/,
conditions/, documents/. PR3 splits _fhir_post_process.py and closes
#556.
EOF
)"
```

- [ ] **Step 3: Push branch.**

```bash
git push -u origin refactor/555-fhir-r4-foundation-pr1
```

If the pre-push hook (`ruff format --check`) refuses, run `ruff format clinosim tests` and amend the commit — do NOT `--no-verify`.

- [ ] **Step 4: Create the PR.**

```bash
gh pr create \
  --base master \
  --head refactor/555-fhir-r4-foundation-pr1 \
  --title "refactor(output): create fhir_r4/lib/ shared library — Issue #555 PR1 of 3" \
  --body "$(cat <<'EOF'
## Summary

Foundation PR of the 3-PR restructure for Issue #555. This PR creates the `clinosim/modules/output/fhir_r4/` subpackage with a `fhir_r4/lib/` shared library, moves the 6 shared FHIR helper modules into it, and reworks the FHIR facade so the subpackage's `__init__.py` becomes the canonical entry point.

## Design context

Full spec: [`docs/superpowers/specs/2026-08-08-output-fhir_r4-subpackage-design.md`](../blob/refactor/555-fhir-r4-foundation-pr1/docs/superpowers/specs/2026-08-08-output-fhir_r4-subpackage-design.md).

Layout is clinical-domain (Option B), not role-based (Option A that the closed PR #604 attempted). Reasons: sibling drift becomes visible in the same directory listing (data-quality concern), maintainers reason by domain not by FHIR resource type (clinical-alignment concern), and per-directory file counts stay small (readability concern).

## Scope

- **Moves** (git mv, byte-neutral content):
  - `output/fhir_common.py` → `output/fhir_r4/lib/common.py`
  - `output/_fhir_localization.py` → `output/fhir_r4/lib/localization.py`
  - `output/_fhir_reference_data.py` → `output/fhir_r4/lib/reference_data.py`
  - `output/_fhir_inline_bb.py` → `output/fhir_r4/lib/inline_bb.py`
  - `output/_fhir_generator_metadata.py` → `output/fhir_r4/lib/generator_metadata.py`
  - `output/opaque_ids.py` → `output/fhir_r4/lib/ids.py`
- **Facade** — `fhir_r4_adapter.py` content promoted into `fhir_r4/__init__.py`. `fhir_r4_adapter.py` becomes a thin re-export shim so 128 caller sites don't break.
- **Deprecation shim** — `_fhir_common.py` (Issue #545) updated to point at `fhir_r4.lib.common`; `DeprecationWarning` emission and explicit private-helper re-imports preserved verbatim.
- **Callers** — 83 files across `clinosim/` and `tests/` migrated to the new `fhir_r4.lib.<name>` import paths.

## Out of scope

- **PR2** (next): moves 25+ builder files into `fhir_r4/{demographics, encounters, medications, labs, procedures, conditions, documents}/`.
- **PR3**: splits `_fhir_post_process.py` (1370 LOC) into 5 concern-scoped modules under `fhir_r4/post_process/`; also closes Issue #556.
- **Issue #545 Step 2** (symbol renaming `_build_X` → `build_X`) — file-name rename in this PR only touches file paths, not internal symbol names.

## Verification

Per memory rules `feedback_measure_with_the_real_operation.md` and `feedback_verify_beyond_unit_tests.md` — reject silent regressions, measure the real operation.

- `pytest tests/unit`: **3968 passed** (matches master baseline exactly; PR #604 had 3963 pass + 5 introduced-then-mislabeled failures).
- `mypy clinosim/` strict: clean.
- `ruff check + format --check`: clean.
- 30-patient seed 42 JP+US FHIR cohort `diff -r` vs `origin/master`: **0 lines** for both locales.
- Direct probe of `_find_repo_root()` (`generator_metadata.py`) and `BundleContext` import (`common.py`): both OK. No `Path(__file__).parents[N]` regression (the pattern that broke PR #604).

## Related

- Foundation for: #555.
- Supersedes closed PR #604 (see [detailed regression analysis](https://github.com/TomoOkuyama/clinosim/pull/604#issuecomment-5224346643) explaining why that attempt was rejected).
- Depends on: #545 (already merged — `fhir_common.py` was the promoted public name from that Issue; this PR moves it to its final home).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01PCD9UxAv9Rpz2HVt2hGE75
EOF
)"
```

- [ ] **Step 5: Verify PR opened.**

```bash
gh pr view --json url,state -q '{state, url}'
```
Expected: `{"state": "OPEN", "url": "https://github.com/TomoOkuyama/clinosim/pull/<N>"}`.

Return the PR URL to the user.

---

## Rollback plan

If verification fails at Task 5 and root-causing isn't quick:

```bash
git checkout master
git branch -D refactor/555-fhir-r4-foundation-pr1  # local delete
# (if pushed): gh pr close <N> && git push origin --delete refactor/555-fhir-r4-foundation-pr1
```

`master` is untouched throughout — rollback is complete branch delete.

## Post-merge follow-up (not part of PR1)

- PR2 planning: enumerate the 25+ builder files and pre-compute their target domain subdir. Audit `_fhir_medications.py:296` (`parents[2]` → will need `parents[4]` after deeper move) and `lab_coding_package.py:545` (`parents[3]` → will need `parents[5]`) BEFORE moving, and fix in the same commit.
- PR3 planning: read the 5 concern groupings declared in `_fhir_post_process.py`'s own module docstring; each becomes one target file.

## Self-review notes

1. **Placeholder scan**: no TBD/TODO in the plan body. All code shown is executable.
2. **Type consistency**: import paths substitution map is consistent across Tasks 2, 3, 4 (identical sed replacements). Facade shim uses `import *` for public + explicit tuple for private helpers, matching the Issue #545 pattern.
3. **Spec coverage**: PR1 scope in spec (§ "PR sequence → PR1") is fully covered by Tasks 1–6. Backward-compat contract in spec (`fhir_r4_adapter` shim, `_fhir_common` shim, symbol names unchanged) is honored by Task 3 (facade shim) and Task 4 (deprecation shim).
4. **Ambiguity check**: the "move `fhir_r4_adapter.py` into `fhir_r4/__init__.py`" step could be interpreted as "just copy content over". Task 3 Step 1 makes it explicit: `git rm` the placeholder first, then `git mv` — this preserves rename history for `git log --follow`.
