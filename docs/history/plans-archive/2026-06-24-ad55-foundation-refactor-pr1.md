# AD-55 Module Foundation Refactor PR1 (G1 Structural DRY) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Single-module mechanical refactor — inline execution recommended.

**Goal:** Pure mechanical refactor (byte-identical output guaranteed) to consolidate three structural-DRY violations across the AD-55 enricher pattern: (1) `_get(obj, name, default)` shared utility extraction, (2) sub-seed offset central registry with 16-bit hex ASCII convention for new modules, (3) `care_level.load_rates(country: str)` signature unification.

**Architecture:** New file `clinosim/modules/_shared.py` (cross-module utilities). New `ENRICHER_SEED_OFFSETS` dict in `clinosim/simulator/seeding.py` (already houses `derive_sub_seed`). Three documentation surfaces updated: `CLAUDE.md`, `docs/CONTRIBUTING-modules.md`, and 5 module READMEs.

**Tech Stack:** Python 3.11+, pytest, ruff. No new external dependencies.

## Global Constraints

- Branch: `feat/ad55-foundation-refactor-pr1` (already created, spec commit `27a1a5b3`)
- Spec source: `docs/superpowers/specs/2026-06-24-ad55-foundation-refactor-pr1-design.md`
- Predecessor: PR #82 (Phase 2b), master HEAD `dcb47ccc`
- **byte-identical output gate**: all 11 NDJSON files sha256-IDENTICAL at US/JP p=2000 seed=42 vs master `dcb47ccc`. Any deviation = blocker.
- **Scope correction discovered during plan-write** (spec said 4 enricher / 5 module, actual scope is **5 enricher / 7 module**):
  - 5 enrichers with `_get` duplication: immunization, code_status, family_history, care_level, **observation/nursing_enricher.py** (missed in spec exploration)
  - 7 modules with sub-seed offset: identity (540_054 decimal), **microbiology (770_077 decimal)** (missed), immunization (0x494D), code_status (0x4353), family_history (0x4648), care_level (0x434C), **nursing (0x4E55)** (missed)
  - Both legacy decimals (identity, microbiology) grandfathered per spec convention
  - Optional bonus: `_fhir_family_history.py` also has identical `_get` definition — fold into Task 2 for consistency
- **`tests/unit/test_seeding.py` already imports `_IMM_SEED_OFFSET`, `_NURSING_SEED_OFFSET`, `_MICRO_SEED_OFFSET`** — these imports must be updated to use `ENRICHER_SEED_OFFSETS["..."]` after registry consolidation (Task 4)
- **`as _get` alias** preserves local symbol → call sites untouched in all enricher files
- **AD-16**: all sub-seed numerical values identical → `derive_sub_seed(master, offset, key)` outputs identical → per-person/encounter RNG draws identical → byte-identical output
- **Commit trailer (every commit)**:
  ```
  Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
  ```
- **English code + comments** (project convention)
- **Verification before assertion**: every commit follows a green pytest run; don't claim success without observed test output

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `clinosim/modules/_shared.py` | Create | `get_attr_or_key(obj, name, default)` — dict/dataclass dual access |
| `tests/unit/test_shared_utils.py` | Create | 4 unit tests for `get_attr_or_key` |
| `clinosim/modules/immunization/enricher.py:16-22` | Modify | Remove `_get` def + add `_shared` import alias |
| `clinosim/modules/code_status/enricher.py:13-19` | Modify | Same pattern |
| `clinosim/modules/family_history/enricher.py:13-19` | Modify | Same pattern |
| `clinosim/modules/care_level/enricher.py:12-18` | Modify | Same pattern |
| `clinosim/modules/observation/nursing_enricher.py:20-25` | Modify | Same pattern (newly discovered) |
| `clinosim/modules/output/_fhir_family_history.py:11-15` | Modify | Same pattern (FHIR builder consistency) |
| `clinosim/simulator/seeding.py` | Modify | Add `ENRICHER_SEED_OFFSETS` dict + duplicate-check assert at module level |
| `tests/unit/test_enricher_seed_offsets.py` | Create | 4 unit tests for registry properties |
| `clinosim/modules/identity/assign.py:19,33` | Modify | Remove `_IDENTITY_SEED_OFFSET` + import from registry |
| `clinosim/modules/observation/microbiology.py:22,55` | Modify | Remove `_MICRO_SEED_OFFSET` + import from registry |
| `clinosim/modules/observation/nursing_enricher.py:20,39` | Modify | Remove `_NURSING_SEED_OFFSET` + import (consolidate with Task 2 edit) |
| `clinosim/modules/immunization/enricher.py:16,46` | Modify | Remove `_IMM_SEED_OFFSET` + import (consolidate with Task 2 edit) |
| `clinosim/modules/code_status/enricher.py:13,44` | Modify | Same |
| `clinosim/modules/family_history/enricher.py:13,29` | Modify | Same |
| `clinosim/modules/care_level/enricher.py:12,27` | Modify | Same |
| `tests/unit/test_seeding.py:11-13` | Modify | Replace 3 module-internal imports with `ENRICHER_SEED_OFFSETS["..."]` lookups |
| `clinosim/modules/care_level/engine.py:21-23` | Modify | `load_rates(country: str = "JP")` + `@lru_cache` + non-JP early return |
| `CLAUDE.md` | Modify | Add "AD-55 enricher patterns" subsection under Architecture rules → EHR data enrichment |
| `docs/CONTRIBUTING-modules.md` | Modify | 3 edits — sub-seed registry section + `_shared.py` helper rule + locale signature regulation |
| `clinosim/modules/immunization/README.md:83-85` | Modify | Update example to import from registry |
| `clinosim/modules/code_status/README.md` | Modify | Same pattern |
| `clinosim/modules/family_history/README.md` | Modify | Same |
| `clinosim/modules/care_level/README.md` | Modify | Same + load_rates signature |
| `DESIGN.md` | Modify | AD-56 entry note: cross-reference to ENRICHER_SEED_OFFSETS convention |
| `TODO.md` | Modify | PR1 done + PR2-4 backlog explicit |
| `scratchpad/refactor_pr1_byte_diff/compare.py` | Create (scratch) | sha256 + line-count comparison (master vs branch) |
| `scratchpad/refactor_pr1_byte_diff_results.md` | Create (scratch) | byte-diff evidence (not committed) |

---

## Task 1: `clinosim/modules/_shared.py` + unit tests

**Files:**
- Create: `clinosim/modules/_shared.py`
- Create: `tests/unit/test_shared_utils.py`

**Interfaces:**
- Produces: `get_attr_or_key(obj: Any, name: str, default: Any = None) -> Any` — returns `obj.get(name, default)` if dict-like, else `getattr(obj, name, default)`, with explicit `None` guard for `obj`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_shared_utils.py`:

```python
"""Unit tests for `clinosim.modules._shared.get_attr_or_key` — dict/dataclass dual access."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from clinosim.modules._shared import get_attr_or_key


@pytest.mark.unit
def test_get_attr_or_key_from_dict():
    assert get_attr_or_key({"k": 1}, "k") == 1


@pytest.mark.unit
def test_get_attr_or_key_from_object():
    @dataclass
    class _S:
        x: int = 42
    assert get_attr_or_key(_S(), "x") == 42


@pytest.mark.unit
def test_get_attr_or_key_missing_returns_default():
    assert get_attr_or_key({"k": 1}, "missing", "fb") == "fb"

    @dataclass
    class _S:
        x: int = 42
    assert get_attr_or_key(_S(), "missing", "fb") == "fb"


@pytest.mark.unit
def test_get_attr_or_key_none_obj():
    assert get_attr_or_key(None, "k", "fb") == "fb"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_shared_utils.py -v 2>&1 | tail -15`
Expected: ImportError — `cannot import name 'get_attr_or_key' from 'clinosim.modules._shared'`

- [ ] **Step 3: Implement the helper**

Create `clinosim/modules/_shared.py`:

```python
"""Shared utilities for AD-55 enricher modules.

Helpers used across multiple modules under ``clinosim/modules/<name>/enricher.py``
that would otherwise be duplicated. Add new cross-module helpers here when
DRY violations appear (and only then — premature centralization is worse than
local duplication).
"""
from __future__ import annotations

from typing import Any


def get_attr_or_key(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from ``obj`` whether ``obj`` is a dict or has attributes.

    Used by enrichers that consume ``ctx`` / ``ctx.config`` / record objects
    that may arrive as either dataclass instances or dicts depending on
    upstream loaders. Returns ``default`` if the attribute / key is missing
    or if ``obj`` is ``None``.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_shared_utils.py -v 2>&1 | tail -10`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/_shared.py tests/unit/test_shared_utils.py
git commit -m "$(cat <<'EOF'
refactor(ad55): clinosim/modules/_shared.py — get_attr_or_key dict/dataclass dual access

New cross-module utility consolidating the _get(obj, name, default)
pattern currently duplicated across 6 sites (5 enrichers + 1 FHIR
builder). Adds explicit None guard for obj (defensive consolidation;
existing call sites already short-circuit before passing None).

4 unit tests (dict access / dataclass access / missing key default /
None obj returns default).

No call sites touched in this commit — migration in following commits
imports with `as _get` alias to keep call sites unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 2: Refactor 6 `_get` call sites to use shared helper

**Files:**
- Modify: `clinosim/modules/immunization/enricher.py:19-23`
- Modify: `clinosim/modules/code_status/enricher.py:16-20`
- Modify: `clinosim/modules/family_history/enricher.py:16-20`
- Modify: `clinosim/modules/care_level/enricher.py:15-19`
- Modify: `clinosim/modules/observation/nursing_enricher.py:27-32`
- Modify: `clinosim/modules/output/_fhir_family_history.py:11-15`

**Interfaces:**
- Consumes: `get_attr_or_key` from Task 1
- Produces: 6 files use `from clinosim.modules._shared import get_attr_or_key as _get` instead of local `_get` def

- [ ] **Step 1: Verify exact `_get` definitions are identical across all 6 files**

Run:
```
for f in clinosim/modules/{immunization,code_status,family_history,care_level}/enricher.py \
         clinosim/modules/observation/nursing_enricher.py \
         clinosim/modules/output/_fhir_family_history.py; do
  echo "=== $f ==="
  grep -A4 "^def _get" "$f"
done
```

Expected: 6 IDENTICAL function bodies (3 lines each: isinstance check + dict path + getattr path).
If any differs (e.g., nursing_enricher.py has a docstring), note it — the migration is still safe because output is identical.

- [ ] **Step 2: Refactor `immunization/enricher.py`**

In `clinosim/modules/immunization/enricher.py`:

- After line 14 (`from clinosim.simulator.seeding import derive_sub_seed`), add:
  ```python
  from clinosim.modules._shared import get_attr_or_key as _get
  ```
- Delete lines 19-23 (the local `def _get(obj, name, default=None):` block and its 3-line body)

- [ ] **Step 3: Refactor `code_status/enricher.py`**

Same pattern: add `from clinosim.modules._shared import get_attr_or_key as _get` near other imports, delete the `def _get(...)` block (lines 16-20).

- [ ] **Step 4: Refactor `family_history/enricher.py`**

Same pattern: add import, delete `def _get(...)` block (lines 16-20).

- [ ] **Step 5: Refactor `care_level/enricher.py`**

Same pattern: add import, delete `def _get(...)` block (lines 15-19).

- [ ] **Step 6: Refactor `observation/nursing_enricher.py`**

Same pattern: add import, delete `def _get(...)` block (lines 27-32; this one includes a one-line docstring `"""Read attr or dict key (records may be dataclasses)."""` — delete the docstring too since the imported helper has its own).

- [ ] **Step 7: Refactor `output/_fhir_family_history.py`**

Same pattern: add `from clinosim.modules._shared import get_attr_or_key as _get` near other imports, delete the `def _get(...)` block (lines 11-15).

- [ ] **Step 8: Run all existing unit + integration tests to confirm no regression**

Run: `pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -5`
Expected: 687+ passed (4 new + 683 existing baseline = at least 687).

- [ ] **Step 9: Commit**

```bash
git add clinosim/modules/immunization/enricher.py \
        clinosim/modules/code_status/enricher.py \
        clinosim/modules/family_history/enricher.py \
        clinosim/modules/care_level/enricher.py \
        clinosim/modules/observation/nursing_enricher.py \
        clinosim/modules/output/_fhir_family_history.py
git commit -m "$(cat <<'EOF'
refactor(ad55): 6 _get duplicates -> _shared.get_attr_or_key import alias

5 enricher modules + 1 FHIR builder previously each defined an identical
_get(obj, name, default) helper for dict/dataclass dual access (-30 lines
of duplicate definitions). Each now imports the shared helper with
`as _get` alias, keeping every call site untouched.

Files:
- clinosim/modules/immunization/enricher.py
- clinosim/modules/code_status/enricher.py
- clinosim/modules/family_history/enricher.py
- clinosim/modules/care_level/enricher.py
- clinosim/modules/observation/nursing_enricher.py
- clinosim/modules/output/_fhir_family_history.py

Behavior unchanged. byte-identical output expected (verified later in
byte-diff task).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 3: `ENRICHER_SEED_OFFSETS` central registry + unit tests

**Files:**
- Modify: `clinosim/simulator/seeding.py`
- Create: `tests/unit/test_enricher_seed_offsets.py`

**Interfaces:**
- Produces: `ENRICHER_SEED_OFFSETS: dict[str, int]` with 7 entries (identity, microbiology, immunization, code_status, family_history, care_level, nursing) + module-level `assert` that detects duplicates at import

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_enricher_seed_offsets.py`:

```python
"""Unit tests for ENRICHER_SEED_OFFSETS central registry (PR1 G1 refactor).

The registry is the single source of truth for AD-55 enricher sub-seed
offsets. These tests pin three properties:
1. No duplicate offsets (would silently merge two modules' RNG streams)
2. All current modules registered (regression guard against accidental removal)
3. Grandfathered legacy decimals preserved (preserving byte-identical
   identity / microbiology output for the 2026-06-24 master)
4. New entries follow 16-bit hex ASCII convention (range < 0x10000)
"""
from __future__ import annotations

import pytest

from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS


@pytest.mark.unit
def test_no_duplicate_offsets():
    """Two modules with the same offset would collide on the same RNG
    sub-stream — silent determinism bug. The module-level assert in
    seeding.py also guards this at import time; this test pins the
    contract at unit-test layer."""
    values = list(ENRICHER_SEED_OFFSETS.values())
    assert len(set(values)) == len(values), \
        f"duplicate ENRICHER_SEED_OFFSETS: {ENRICHER_SEED_OFFSETS!r}"


@pytest.mark.unit
def test_all_modules_registered():
    expected = {"identity", "microbiology", "immunization", "code_status",
                "family_history", "care_level", "nursing"}
    assert set(ENRICHER_SEED_OFFSETS.keys()) >= expected, \
        f"missing keys: {expected - set(ENRICHER_SEED_OFFSETS.keys())}"


@pytest.mark.unit
def test_grandfathered_identity_value():
    """Identity offset is grandfathered at its legacy decimal to preserve
    byte-identical JP identity / Coverage output. Changing this value
    shifts every JP patient's identifier numbers."""
    assert ENRICHER_SEED_OFFSETS["identity"] == 540_054


@pytest.mark.unit
def test_grandfathered_microbiology_value():
    """Microbiology offset is similarly grandfathered."""
    assert ENRICHER_SEED_OFFSETS["microbiology"] == 770_077


@pytest.mark.unit
def test_hex_ascii_convention_new_modules():
    """All non-grandfathered modules follow 16-bit hex ASCII convention
    (offset < 0x10000). This pins the convention for future contributors
    (CLAUDE.md + CONTRIBUTING-modules.md docs)."""
    grandfathered = {"identity", "microbiology"}
    for name, offset in ENRICHER_SEED_OFFSETS.items():
        if name in grandfathered:
            continue
        assert offset < 0x10000, \
            f"{name} offset {offset:#x} exceeds 16-bit hex ASCII range"


@pytest.mark.unit
def test_hex_ascii_values_match_module_names():
    """The hex-ASCII offsets should spell sensible 2-letter abbreviations
    of their module names — readable convention for future additions."""
    expected_ascii = {
        "immunization":   0x494D,  # "IM"
        "code_status":    0x4353,  # "CS"
        "family_history": 0x4648,  # "FH"
        "care_level":     0x434C,  # "CL"
        "nursing":        0x4E55,  # "NU"
    }
    for name, expected in expected_ascii.items():
        assert ENRICHER_SEED_OFFSETS[name] == expected, \
            f"{name}: {ENRICHER_SEED_OFFSETS[name]:#x} != {expected:#x}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_enricher_seed_offsets.py -v 2>&1 | tail -15`
Expected: ImportError — `cannot import name 'ENRICHER_SEED_OFFSETS' from 'clinosim.simulator.seeding'`

- [ ] **Step 3: Add registry to `seeding.py`**

Append to `clinosim/simulator/seeding.py` (after existing `individual_lab_seed` function or at end-of-file):

```python


# AD-55 Module enricher sub-seed offsets.
#
# Convention (PR1 2026-06-24): new modules MUST use a 16-bit hex ASCII
# offset (2 letters), e.g. 0x4944 = "ID". Identity (540_054) and
# microbiology (770_077) are grandfathered at their legacy decimal values
# to preserve byte-identical output for the 2026-06-24 master. Future
# device + HAI modules will follow the hex-ASCII convention (e.g.,
# device = 0x4456 "DV", hai = 0x4841 "HA").
#
# All values must be unique — duplicates would silently collide two
# modules' RNG streams. The assert below catches accidental clashes at
# import time. See docs/CONTRIBUTING-modules.md for the contributor
# rules and CLAUDE.md "AD-55 enricher patterns" for the architectural
# rule.
ENRICHER_SEED_OFFSETS = {
    "identity":       540_054,    # legacy decimal (grandfathered)
    "microbiology":   770_077,    # legacy decimal (grandfathered)
    "immunization":   0x494D,     # "IM"
    "code_status":    0x4353,     # "CS"
    "family_history": 0x4648,     # "FH"
    "care_level":     0x434C,     # "CL"
    "nursing":        0x4E55,     # "NU"
}

assert len(set(ENRICHER_SEED_OFFSETS.values())) == len(ENRICHER_SEED_OFFSETS), \
    f"ENRICHER_SEED_OFFSETS contains duplicate values: {ENRICHER_SEED_OFFSETS!r}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_enricher_seed_offsets.py -v 2>&1 | tail -15`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add clinosim/simulator/seeding.py tests/unit/test_enricher_seed_offsets.py
git commit -m "$(cat <<'EOF'
feat(seeding): ENRICHER_SEED_OFFSETS central registry — 7 modules

Single source of truth for AD-55 enricher sub-seed offsets. Convention:
new modules use 16-bit hex ASCII (2 letters from module name). identity
(540_054) + microbiology (770_077) grandfathered as legacy decimals to
preserve byte-identical JP identifier / microbiology Observation output.

Module-level assert catches duplicate offsets at import time (would
otherwise silently merge two modules' RNG streams = determinism bug).

6 unit tests pin: no duplicates / all modules registered / grandfathered
values pinned (identity 540_054, microbiology 770_077) / hex-ASCII
convention for new modules / 2-letter ASCII values match module names.

Modules will migrate to import from this registry in the next commit
(byte-identical guaranteed since numerical values are preserved).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 4: Migrate 7 modules to import offset from registry

**Files:**
- Modify: `clinosim/modules/identity/assign.py:19,33`
- Modify: `clinosim/modules/observation/microbiology.py:22,55`
- Modify: `clinosim/modules/immunization/enricher.py:16,46`
- Modify: `clinosim/modules/code_status/enricher.py:13,44`
- Modify: `clinosim/modules/family_history/enricher.py:13,29`
- Modify: `clinosim/modules/care_level/enricher.py:12,27`
- Modify: `clinosim/modules/observation/nursing_enricher.py:20,39`
- Modify: `tests/unit/test_seeding.py:11-13`

**Interfaces:**
- Consumes: `ENRICHER_SEED_OFFSETS` from Task 3
- Produces: all 7 modules' local `_XXX_SEED_OFFSET` constants removed; usages replaced with `ENRICHER_SEED_OFFSETS["xxx"]` lookups

- [ ] **Step 1: Migrate `identity/assign.py`**

Edit `clinosim/modules/identity/assign.py`:

- After the existing import block, add:
  ```python
  from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS
  ```
- Delete line 19 (`_IDENTITY_SEED_OFFSET = 540_054`)
- Change line 33 from:
  ```python
      rng = np.random.default_rng(master_seed + _IDENTITY_SEED_OFFSET)
  ```
  to:
  ```python
      rng = np.random.default_rng(master_seed + ENRICHER_SEED_OFFSETS["identity"])
  ```

- [ ] **Step 2: Migrate `observation/microbiology.py`**

Edit `clinosim/modules/observation/microbiology.py`:

- Ensure `from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed` is imported (combine with existing `derive_sub_seed` import line).
- Delete line 22 (`_MICRO_SEED_OFFSET = 770_077`)
- Change line 55 from:
  ```python
      rng = np.random.default_rng(derive_sub_seed(master_seed, _MICRO_SEED_OFFSET, encounter_id))
  ```
  to:
  ```python
      rng = np.random.default_rng(derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["microbiology"], encounter_id))
  ```

- [ ] **Step 3: Migrate the 5 enrichers (same pattern × 5)**

For each of `immunization/enricher.py`, `code_status/enricher.py`, `family_history/enricher.py`, `care_level/enricher.py`, `observation/nursing_enricher.py`:

- Add `ENRICHER_SEED_OFFSETS` to existing `from clinosim.simulator.seeding import ...` line
- Delete `_XXX_SEED_OFFSET = ...` line
- Replace `derive_sub_seed(ctx.master_seed, _XXX_SEED_OFFSET, ...)` with `derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["xxx"], ...)`

Mapping (old constant name → registry key):
| File | Old constant | Registry key |
|---|---|---|
| immunization/enricher.py | `_IMM_SEED_OFFSET` | `"immunization"` |
| code_status/enricher.py | `_CS_SEED_OFFSET` | `"code_status"` |
| family_history/enricher.py | `_FH_SEED_OFFSET` | `"family_history"` |
| care_level/enricher.py | `_CL_SEED_OFFSET` | `"care_level"` |
| observation/nursing_enricher.py | `_NURSING_SEED_OFFSET` | `"nursing"` |

- [ ] **Step 4: Update `tests/unit/test_seeding.py` imports**

In `tests/unit/test_seeding.py`, replace lines 11-13:

```python
from clinosim.modules.immunization.enricher import _IMM_SEED_OFFSET
from clinosim.modules.observation.microbiology import _MICRO_SEED_OFFSET
from clinosim.modules.observation.nursing_enricher import _NURSING_SEED_OFFSET
from clinosim.simulator.seeding import derive_sub_seed, panel_specimen_seed
```

with:

```python
from clinosim.simulator.seeding import (
    ENRICHER_SEED_OFFSETS,
    derive_sub_seed,
    panel_specimen_seed,
)

_IMM_SEED_OFFSET = ENRICHER_SEED_OFFSETS["immunization"]
_MICRO_SEED_OFFSET = ENRICHER_SEED_OFFSETS["microbiology"]
_NURSING_SEED_OFFSET = ENRICHER_SEED_OFFSETS["nursing"]
```

The local aliases preserve the existing test body unchanged (numerical values identical).

- [ ] **Step 5: Run all tests including the precomputed-literal pins**

Run: `pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -10`

Expected: All previously-green tests pass. Critically:
- `test_seeding.py::test_formula_is_pinned` — precomputed literals 914786652 / 914785364 / 2694613518 must still match (proves numerical identity is preserved)
- `test_seeding.py::test_module_offsets_are_distinct` — must still pass

If any "precomputed literal" test fails, the registry value for that module is wrong — STOP and verify against pre-refactor code.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/identity/assign.py \
        clinosim/modules/observation/microbiology.py \
        clinosim/modules/immunization/enricher.py \
        clinosim/modules/code_status/enricher.py \
        clinosim/modules/family_history/enricher.py \
        clinosim/modules/care_level/enricher.py \
        clinosim/modules/observation/nursing_enricher.py \
        tests/unit/test_seeding.py
git commit -m "$(cat <<'EOF'
refactor(ad55): 7 modules import sub-seed offset from ENRICHER_SEED_OFFSETS registry

All AD-55 module sub-seed offsets now come from the central registry
(clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS). Local _XXX_SEED_OFFSET
constants removed from:
- identity/assign.py (540_054 grandfathered decimal)
- observation/microbiology.py (770_077 grandfathered decimal)
- immunization/enricher.py (0x494D "IM")
- code_status/enricher.py (0x4353 "CS")
- family_history/enricher.py (0x4648 "FH")
- care_level/enricher.py (0x434C "CL")
- observation/nursing_enricher.py (0x4E55 "NU")

tests/unit/test_seeding.py imports updated to read from registry +
re-establish local aliases (so the pre-existing precomputed-literal
pins 914786652 / 914785364 / 2694613518 continue to hold — numerical
values are identical, byte-identical output preserved).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 5: `care_level.load_rates(country)` signature unification

**Files:**
- Modify: `clinosim/modules/care_level/engine.py:21-23`

**Interfaces:**
- Consumes: nothing new
- Produces: `load_rates(country: str = "JP") -> dict` — returns `{}` for non-JP; cached via `@lru_cache`

- [ ] **Step 1: Verify the existing caller and confirm behavior preservation**

Run: `grep -n "load_rates" clinosim/modules/care_level/*.py`
Expected: 2 occurrences — definition (engine.py:21) + caller (engine.py inside `assign_care_level`).
Caller already short-circuits on non-JP (verified during plan-write at engine.py:36). So adding non-JP early return inside `load_rates` is behaviorally identical for the only existing caller.

- [ ] **Step 2: Edit the signature**

In `clinosim/modules/care_level/engine.py`, find the existing block:

```python
def load_rates() -> dict:
    with open(_LOCALE / "jp" / "care_level_rates.yaml") as f:
        return yaml.safe_load(f)
```

Replace with:

```python
@lru_cache(maxsize=None)
def load_rates(country: str = "JP") -> dict:
    """Load care-level rates for ``country``. Returns ``{}`` for non-JP
    (no-op path) — care_level is currently JP-only, but the signature
    matches immunization / family_history / code_status so future locale
    additions slot in without API churn."""
    if str(country).upper() != "JP":
        return {}
    with open(_LOCALE / "jp" / "care_level_rates.yaml") as f:
        return yaml.safe_load(f)
```

- [ ] **Step 3: Ensure `lru_cache` is imported**

In the same file, check that `from functools import lru_cache` is at the top. If absent, add it. If `functools` is imported differently (e.g., `import functools` then `@functools.lru_cache`), match the existing style.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -5`
Expected: All previously-green tests pass.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/care_level/engine.py
git commit -m "$(cat <<'EOF'
refactor(care_level): load_rates(country: str) signature + @lru_cache

Unifies care_level's locale-loader signature with immunization /
family_history / code_status (all of which take a `country` parameter).
care_level is currently JP-only, so the new non-JP early return is a
no-op (single existing caller `assign_care_level` already short-circuits
on non-JP). Adds @lru_cache(maxsize=None) for consistency — eliminates
repeated YAML reads.

Behavior unchanged for both JP (load JP YAML as before) and non-JP
(early return as before, but now from load_rates not just the caller).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 6: CLAUDE.md "AD-55 enricher patterns" subsection

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Locate the existing "EHR data enrichment" section**

Run: `grep -n "EHR data enrichment\|AD-55\|AD-56" CLAUDE.md | head -10`
Expected: a section header at a specific line. Insert the new subsection after the existing AD-55/AD-56 content but before the next major section (likely "Code system module").

- [ ] **Step 2: Add the subsection**

Find the "EHR data enrichment — Base vs Module (AD-55) + extensibility (AD-56)" section. After its existing bullet list, add a new subsection:

```markdown
### AD-55 enricher patterns (PR1 foundation refactor, 2026-06-24)

- **Sub-seed offset convention** — new enricher modules MUST register
  their sub-seed in `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS`
  with a 16-bit hex-ASCII offset (e.g. `0x4944` = "ID", `0x4841` = "HA").
  Identity (decimal 540_054) and microbiology (decimal 770_077) are
  grandfathered to preserve byte-identical output. The dict has a
  module-level assert that catches accidental duplicates at import.
  Modules import via `from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS`
  and use `derive_sub_seed(master, ENRICHER_SEED_OFFSETS["my_module"], key)`.
- **DRY helpers** — cross-module utilities used by 2+ enrichers live in
  `clinosim/modules/_shared.py`. Don't redefine inline; import from
  `_shared`. Current: `get_attr_or_key(obj, name, default)` for dict /
  dataclass dual access.
- **Locale loader signature** — modules with locale-specific data MUST
  accept a `country: str` parameter and return `{}` for unsupported
  countries (no-op early return). Hardcoded country literals in path
  joins (e.g., `_LOCALE / "jp" / "..."` without country gating) are a
  consistency bug.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(claude): AD-55 enricher patterns subsection

3 architectural rules pinned for future enricher modules:
1. Sub-seed offset registry (ENRICHER_SEED_OFFSETS, 16-bit hex ASCII)
2. DRY helper consolidation (clinosim/modules/_shared.py)
3. Locale loader country: str signature requirement

Matches the foundation laid by the PR1 refactor of identity /
immunization / microbiology / code_status / family_history / care_level /
nursing modules. Detailed contributor playbook is in
docs/CONTRIBUTING-modules.md (separate edits in the next commit).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 7: `docs/CONTRIBUTING-modules.md` 3 edits

**Files:**
- Modify: `docs/CONTRIBUTING-modules.md`

**Interfaces:**
- Consumes: existing module-author playbook structure (sections "判断: Base か Module か", "モジュールの構造 / canonical レイアウト", "sub-seed 導出ルール")

- [ ] **Step 1: Edit 1 — extend "sub-seed 導出ルール" section**

Find the existing "### sub-seed 導出ルール" section (around line 123).
After the existing pattern explanation block, add (note: backticks doubled to escape inside heredoc):

```markdown
**新モジュールのオフセット登録**: モジュール作成時、sub-seed の数値オフセットを **`clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS`** に登録します。convention は **16-bit hex ASCII (2 文字)** — モジュール名から覚えやすい 2 文字を選ぶ:

```python
ENRICHER_SEED_OFFSETS = {
    "identity":       540_054,    # 例外: legacy decimal (grandfathered)
    "microbiology":   770_077,    # 例外: legacy decimal (grandfathered)
    "immunization":   0x494D,     # "IM"
    "code_status":    0x4353,     # "CS"
    "family_history": 0x4648,     # "FH"
    "care_level":     0x434C,     # "CL"
    "nursing":        0x4E55,     # "NU"
    # 新モジュール例: "device" = 0x4456 ("DV"), "hai" = 0x4841 ("HA")
}
```

モジュール側はローカル定数を持たず、registry から import します:

```python
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
seed = derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["my_module"], person_id)
```

dict 末尾の `assert len(set(...values())) == len(...)` が重複オフセットを import 時に検出します(誤って既存モジュールの RNG ストリームを汚染するのを構造的に防ぐ)。
```

- [ ] **Step 2: Edit 2 — add "共有ヘルパ" sub-section under "モジュールの構造"**

Find the existing "## モジュールの構造" / "### 正準レイアウト" section (around line 52-56). After the canonical layout listing but before "### canonical な「pure-function engine」", add:

```markdown
### 共有ヘルパは `clinosim/modules/_shared.py` に集約する

複数 enricher で同じ helper を持つ場合(例: `get_attr_or_key(obj, name, default)` で dict / dataclass 両対応の属性アクセス)、各モジュールに local 定義を書かず **`clinosim/modules/_shared.py`** に置きます。新規モジュールも以下のように import します:

```python
from clinosim.modules._shared import get_attr_or_key as _get
```

`as _get` alias で短い local 名を維持し、call site の可読性も保ちます。新しい cross-module helper を追加する場合は **2 モジュール以上で実需が生じたタイミング**で `_shared.py` に昇格させます(YAGNI — 1 モジュールしか使わないなら local 定義のまま)。

```

- [ ] **Step 3: Edit 3 — add "locale 依存の signature 規約" sub-section under "判断: Base か Module か"**

Find the existing "## 判断: Base か Module か" section (around line 15-50). Add a new sub-section after the "### ゲートの実装" section:

```markdown
### locale 依存の signature 規約

locale 別データ(国別 prevalence、reference range、code mapping 等)をロードする関数は、**`country: str` パラメータを必ず受け取り**、対象外の国では `{}` / `""` 等の no-op 値を早期 return します:

```python
@lru_cache(maxsize=None)
def load_rates(country: str = "JP") -> dict:
    """Load rates for ``country``. Returns {} for unsupported countries."""
    if str(country).upper() != "JP":
        return {}
    with open(_LOCALE / "jp" / "...") as f:
        return yaml.safe_load(f)
```

理由 — モジュールが現状 1 国対応(例: care_level は JP 専用)であっても、signature を統一しておけば将来 US 対応を追加する際に caller の API を変えずに済みます。`_LOCALE / "jp" / ...` のように country 引数なしでハードコードするのは consistency bug です。

`@lru_cache(maxsize=None)` を併用して反復ロードを避ける(他モジュール — immunization / family_history / code_status — もこのパターン)。
```

- [ ] **Step 4: Verify the file still renders cleanly**

Run: `wc -l docs/CONTRIBUTING-modules.md`
Expected: file grew from 311 lines to ~380-400 lines.

- [ ] **Step 5: Commit**

```bash
git add docs/CONTRIBUTING-modules.md
git commit -m "$(cat <<'EOF'
docs(contributing): 3 enricher pattern playbook extensions

CONTRIBUTING-modules.md is the project's module-author playbook. PR1
extends it with three rules locked in by the PR1 refactor:

1. Sub-seed offset registry section — new modules register in
   ENRICHER_SEED_OFFSETS with 16-bit hex ASCII (identity + microbiology
   grandfathered as decimals)
2. `clinosim/modules/_shared.py` shared helper rule — DRY for utilities
   used by 2+ enrichers; import with `as _get` alias to preserve call
   sites
3. Locale loader signature regulation — `country: str` parameter
   mandatory; non-supported countries early-return; @lru_cache pattern

These rules ensure future AD-55 Module work (device, HAI, billing,
care_coordination) inherits the same structure without rework.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 8: byte-diff verification (US/JP p=2000 seed=42 vs master `dcb47ccc`)

**Files:**
- Create (scratch, NOT committed): `scratchpad/refactor_pr1_byte_diff/`
- Create: `scratchpad/refactor_pr1_byte_diff_results.md` (committed)

**Goal:** Confirm all 11 NDJSON files sha256-IDENTICAL between master and branch. Any deviation = blocker (would mean numerical identity broke somewhere).

- [ ] **Step 1: Generate branch output (US p=2000 + JP p=2000, seed=42)**

```bash
mkdir -p scratchpad/refactor_pr1_byte_diff/branch/us scratchpad/refactor_pr1_byte_diff/branch/jp
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/refactor_pr1_byte_diff/branch/us
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP --format fhir-r4 -o scratchpad/refactor_pr1_byte_diff/branch/jp
```

(Both can be parallel with `run_in_background=true`.)

- [ ] **Step 2: Generate master output (switch to `dcb47ccc`, generate, switch back)**

```bash
git checkout dcb47ccc
mkdir -p scratchpad/refactor_pr1_byte_diff/master/us scratchpad/refactor_pr1_byte_diff/master/jp
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/refactor_pr1_byte_diff/master/us
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP --format fhir-r4 -o scratchpad/refactor_pr1_byte_diff/master/jp
git checkout feat/ad55-foundation-refactor-pr1
```

- [ ] **Step 3: Create comparison script**

Create `scratchpad/refactor_pr1_byte_diff/compare.py`:

```python
"""Byte-diff comparison: master dcb47ccc vs ad55-refactor-pr1 branch.

PR1 is a pure mechanical refactor — all 11 NDJSON files MUST be sha256-IDENTICAL.
Any deviation = blocker.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

FILES = [
    "Patient.ndjson", "Encounter.ndjson", "Condition.ndjson",
    "MedicationRequest.ndjson", "MedicationAdministration.ndjson",
    "Procedure.ndjson", "ImagingStudy.ndjson", "Immunization.ndjson",
    "FamilyMemberHistory.ndjson",
    "Observation.ndjson", "DiagnosticReport.ndjson",
]

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def line_count(path: Path) -> int:
    with path.open() as f:
        return sum(1 for _ in f)

def find_fhir_dir(base: Path) -> Path:
    for candidate in (base / "fhir_r4", base / "fhir", base):
        if (candidate / "Patient.ndjson").exists():
            return candidate
    raise FileNotFoundError(f"No Patient.ndjson under {base}")

def main():
    overall_pass = True
    for country in ("us", "jp"):
        m = find_fhir_dir(Path(f"scratchpad/refactor_pr1_byte_diff/master/{country}"))
        b = find_fhir_dir(Path(f"scratchpad/refactor_pr1_byte_diff/branch/{country}"))
        print(f"\n=== {country.upper()} ===")
        for f in FILES:
            mp, bp = m / f, b / f
            if not mp.exists() or not bp.exists():
                if not mp.exists() and not bp.exists():
                    print(f"  {f:35s}  ABSENT both")
                else:
                    print(f"  {f:35s}  MISSING m={mp.exists()} b={bp.exists()}")
                    overall_pass = False
                continue
            mh, bh = sha256(mp), sha256(bp)
            ml, bl = line_count(mp), line_count(bp)
            if mh == bh:
                print(f"  {f:35s}  IDENTICAL   master={ml:7d}")
            else:
                print(f"  {f:35s}  DIFF        master={ml:7d} branch={bl:7d}")
                overall_pass = False
    print()
    if overall_pass:
        print("✓ ALL NDJSON files sha256-IDENTICAL — byte-identity preserved")
    else:
        print("✗ BLOCKER — at least one NDJSON differs; PR1 refactor introduced a behavior change")

if __name__ == "__main__":
    main()
```

Run: `python scratchpad/refactor_pr1_byte_diff/compare.py | tee scratchpad/refactor_pr1_byte_diff/comparison.txt`

- [ ] **Step 4: Verify result**

Expected: every line ends with `IDENTICAL` or `ABSENT both`. The script ends with `✓ ALL NDJSON files sha256-IDENTICAL`.

If any `DIFF` appears: **STOP**. The refactor broke numerical identity somewhere. Likely cause: a registry value mistyped in Task 3 (e.g., `0x494E` instead of `0x494D`). Re-verify each ENRICHER_SEED_OFFSETS entry against the values listed in this plan.

- [ ] **Step 5: Write byte-diff evidence document**

Create `scratchpad/refactor_pr1_byte_diff_results.md`:

```markdown
# PR1 (AD-55 Foundation Refactor G1) byte-diff results

**Setup**: US/JP p=2000 seed=42, format=fhir-r4 vs master `dcb47ccc`.

## Result: ALL 11 NDJSON IDENTICAL ✓

Pure mechanical refactor preserved byte-identical output as required:

```
[paste comparison.txt content here]
```

This confirms:
- AD-16 master RNG stream unaffected
- All 7 module sub-seed values numerically identical (registry preserves the existing constants)
- _get → get_attr_or_key alias behaves identically
- care_level.load_rates(country="JP") behaves identically to load_rates() for the only existing caller path
```

- [ ] **Step 6: Commit byte-diff evidence**

```bash
git add scratchpad/refactor_pr1_byte_diff_results.md
git commit -m "$(cat <<'EOF'
test(byte-diff): PR1 AD-55 foundation refactor — all 11 NDJSON IDENTICAL

US/JP p=2000 seed=42 vs master dcb47ccc. Pure mechanical refactor
preserved byte-identical output as required:
- Patient / Encounter / Condition / MedicationRequest /
  MedicationAdministration / Procedure / Immunization /
  FamilyMemberHistory / Observation / DiagnosticReport: sha256 IDENTICAL
- ImagingStudy: ABSENT in both (not generated at this scale)

Invariants: AD-16 master RNG stream unaffected; all 7 module sub-seed
values numerically identical via central registry; _get -> get_attr_or_key
alias behaves identically; care_level load_rates(country="JP") unchanged
for sole existing JP-gated caller.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 9: docs sync (module READMEs + DESIGN.md + TODO.md)

**Files:**
- Modify: `clinosim/modules/immunization/README.md` (around line 83-85 — `_IMM_SEED_OFFSET` example)
- Modify: `clinosim/modules/code_status/README.md` (if it has a similar example)
- Modify: `clinosim/modules/family_history/README.md` (if it has a similar example)
- Modify: `clinosim/modules/care_level/README.md` (if it has a similar example)
- Modify: `clinosim/modules/observation/README.md` or relevant README (if microbiology / nursing references appear)
- Modify: `DESIGN.md` (AD-56 entry cross-reference)
- Modify: `TODO.md` (PR1 done + PR2-4 backlog)

**Interfaces:**
- Consumes: established conventions from Tasks 3-7
- Produces: cross-referenced documentation

- [ ] **Step 1: Locate `_IMM_SEED_OFFSET` reference in immunization README**

Run: `grep -rn "_IMM_SEED_OFFSET\|_CS_SEED_OFFSET\|_FH_SEED_OFFSET\|_CL_SEED_OFFSET\|_NURSING_SEED_OFFSET\|_MICRO_SEED_OFFSET\|_IDENTITY_SEED_OFFSET" clinosim/modules/*/README.md 2>/dev/null`

For each match, update the example code block to import from the registry. Example for `immunization/README.md:83-85`:

**Before:**
```markdown
_IMM_SEED_OFFSET = 0x494D  # "IM" — keep unique across modules (test_seeding guards this)
...
rng = np.random.default_rng(derive_sub_seed(ctx.master_seed, _IMM_SEED_OFFSET, patient_id))
```

**After:**
```markdown
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
...
rng = np.random.default_rng(derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["immunization"], patient_id))
```

Update similarly in all other module READMEs that mention their `_XXX_SEED_OFFSET`.

- [ ] **Step 2: Update `care_level/README.md` to mention new `load_rates(country)` signature**

If `clinosim/modules/care_level/README.md` mentions `load_rates()` (no args), update to `load_rates(country: str = "JP")` with the non-JP early-return note.

- [ ] **Step 3: Cross-reference in DESIGN.md AD-56 entry**

Run: `grep -n "AD-56" DESIGN.md | head -5`

In the AD-56 entry (enricher registry / extensibility), add a note (one sentence) referencing the new convention:

> Sub-seed offsets for all enricher modules are registered in `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS` (PR1 2026-06-24 foundation refactor); new modules add an entry there using the 16-bit hex ASCII convention documented in `CLAUDE.md` and `docs/CONTRIBUTING-modules.md`.

- [ ] **Step 4: Update TODO.md**

Find the AD-55 / Phase 2 entries. After Phase 2b, add a new entry:

```markdown
**AD-55 Module Foundation Refactor PR1 (G1 structural DRY) — 2026-06-24:**
Mechanical refactor preparing clean foundation for device + HAI feature
modules. Three structural-DRY items consolidated:

- `_get(obj, name, default)` 6-way duplication -> `clinosim/modules/_shared.py:get_attr_or_key`
  (5 enrichers + 1 FHIR builder import with `as _get` alias)
- 7-module sub-seed offsets -> `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS`
  central registry (identity + microbiology grandfathered as decimals; new
  modules use 16-bit hex ASCII)
- `care_level.load_rates(country: str)` signature unified with immunization /
  family_history / code_status + @lru_cache

Convention docs locked in: CLAUDE.md "AD-55 enricher patterns" subsection +
docs/CONTRIBUTING-modules.md 3 sub-section edits (sub-seed registry, shared
helper, locale signature regulation).

Byte-diff vs master `dcb47ccc` @ p=2000 seed=42: all 11 NDJSON sha256-IDENTICAL
(pure mechanical refactor). See `scratchpad/refactor_pr1_byte_diff_results.md`.

Series context: PR1 of 4 (G1 done) → PR2 (G2 SDOH integrity) → PR3 (G3
_fhir_observations.py 31KB split) → PR4 (G4 doctrine docs) → then device + HAI
feature work.
```

- [ ] **Step 5: Run final regression**

Run: `pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -5`
Expected: All green (≈ 697+ — baseline 687 + 4 shared_utils + 6 enricher_seed_offsets).

- [ ] **Step 6: Commit docs sync**

```bash
git add clinosim/modules/*/README.md DESIGN.md TODO.md
git commit -m "$(cat <<'EOF'
docs(sync): PR1 AD-55 foundation refactor — module READMEs + DESIGN + TODO

Module READMEs (immunization / code_status / family_history / care_level /
observation): sub-seed examples updated to import from
ENRICHER_SEED_OFFSETS registry. care_level README also reflects new
load_rates(country: str) signature.

DESIGN.md AD-56 entry: cross-reference to ENRICHER_SEED_OFFSETS
convention (PR1 2026-06-24).

TODO.md: PR1 done entry with full refactor summary + PR2-4 backlog
explicit (G2 SDOH integrity / G3 _fhir_observations split / G4 doctrine
docs) -> then device + HAI feature work.

Regression: 697+ unit + integration green.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Final: Push + PR

After all 9 tasks complete and working tree is clean:

```bash
git push -u origin feat/ad55-foundation-refactor-pr1
gh pr create --title "refactor: AD-55 Module Foundation PR1 — structural DRY (G1)" --body "$(cat <<'EOF'
## Summary

PR1 of 4 refactor PRs preparing clean foundation for the device + HAI
feature modules (chosen first AD-55 Module from brainstorming session 13).

**Pure mechanical refactor — byte-identical output guaranteed.**

Three structural-DRY items consolidated:

1. **`_get(obj, name, default)` 6-way DRY** → `clinosim/modules/_shared.py:get_attr_or_key`
   - 5 enrichers + 1 FHIR builder import with `as _get` alias (call sites untouched)
   - −30 lines duplicate code

2. **`ENRICHER_SEED_OFFSETS` central registry** in `clinosim/simulator/seeding.py`
   - 7 modules: identity (540_054 grandfathered) / microbiology (770_077 grandfathered) / immunization (0x494D "IM") / code_status (0x4353 "CS") / family_history (0x4648 "FH") / care_level (0x434C "CL") / nursing (0x4E55 "NU")
   - Convention: new modules use 16-bit hex ASCII; module-level assert catches duplicates at import
   - Numerical values preserved → byte-identical output

3. **`care_level.load_rates(country: str = "JP")` signature unification**
   - Matches immunization / family_history / code_status pattern
   - Added `@lru_cache(maxsize=None)` for consistency
   - Non-JP early return (behavior unchanged for sole existing caller)

## Convention docs locked in

- **CLAUDE.md** — new "AD-55 enricher patterns" subsection (3 rules)
- **docs/CONTRIBUTING-modules.md** — 3 sub-section edits (sub-seed registry / `_shared.py` helper / locale signature)

These ensure future device + HAI work (and any subsequent enricher modules) inherits the consistent structure.

## Evidence

**byte-diff (US/JP p=2000 seed=42 vs master `dcb47ccc`)**: all 11 NDJSON files sha256-IDENTICAL. See `scratchpad/refactor_pr1_byte_diff_results.md`.

## Tests

- 4 new unit tests in `test_shared_utils.py`
- 6 new unit tests in `test_enricher_seed_offsets.py`
- `test_seeding.py` precomputed-literal pins (914786652 / 914785364 / 2694613518) still hold — proves numerical identity preserved
- **697+ unit + integration tests green** (687 baseline + 10 new)

## Series context

- PR1 (G1, this PR): structural DRY ✓
- PR2 (G2): SDOH integrity (SNOMED reference_data move + _fhir_sdoh.py split)
- PR3 (G3): _fhir_observations.py 31KB split (immunization extraction)
- PR4 (G4): doctrine docs (identity enabled gate registry + typed field vs extensions decision tree)
- Then: device + HAI feature work (2 modules with cross-module enricher consumption)

## Spec / Plan

- spec: `docs/superpowers/specs/2026-06-24-ad55-foundation-refactor-pr1-design.md`
- plan: `docs/superpowers/plans/2026-06-24-ad55-foundation-refactor-pr1.md`

## Test plan

- [x] Unit tests (test_shared_utils + test_enricher_seed_offsets)
- [x] Pre-existing test_seeding.py precomputed-literal pins continue to hold
- [x] byte-diff p=2000 US/JP vs master dcb47ccc — all 11 NDJSON IDENTICAL
- [x] Full regression (unit + integration)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Self-Review Notes

**Spec coverage check (against spec §1-§9)**:
- §1 Motivation / scope → Tasks 1-9
- §2 Architecture → all tasks
- §3 _shared.py + 4 module migration → Tasks 1, 2 (extended to 6 sites)
- §4 ENRICHER_SEED_OFFSETS registry → Tasks 3, 4 (extended to 7 modules including nursing/microbiology)
- §5 care_level.load_rates signature → Task 5
- §6 CLAUDE.md convention → Task 6
- §6b CONTRIBUTING-modules.md 3 edits → Task 7
- §7 byte-diff strategy → Task 8
- §8 plan task breakdown → matches 9 tasks here (spec had 8 + I split docs sync to ensure module READMEs receive their own subtask attention)
- §9 deferred PR2-4 → captured in PR body Series context

**Placeholder scan**: All steps have concrete code or commands. The one "if it has a similar example" note in Task 9 Step 1 is documented as a conditional check (`grep -rn` first, edit only matches found). Not a placeholder — it's a discovery-then-edit step.

**Type consistency**: `get_attr_or_key(obj: Any, name: str, default: Any = None) -> Any` signature consistent across Tasks 1, 2, 7 (docs). `ENRICHER_SEED_OFFSETS: dict[str, int]` keys consistent (always lowercase module names) across Tasks 3, 4, 6, 7, 9. `load_rates(country: str = "JP")` signature consistent across Tasks 5, 7 (CONTRIBUTING).

**Scope correction noted explicitly** in Global Constraints — spec said 4 enricher / 5 module, plan handles 5 enricher / 7 module (nursing + microbiology added during plan-write code verification). Spec's principle is unchanged.

**Inline-recommended over subagent-driven**: tightly-coupled mechanical refactor across a small set of files. Phase 2a / 2b pattern (inline executing-plans) is the right fit.
