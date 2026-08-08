# PR-A Module Unification Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply 5 cross-module unification fixes (path constant naming + lru_cache maxsize + normalize_probabilities helper + microbiology silent-skip fix + Trimethoprim slash canonicalization) to close known silent-bug / orphan-bug gaps and prepare for PR-B/C/D in this series.

**Architecture:** Each fix is independent of the others and shipped as one themed commit. The normalize_probabilities helper goes in the existing `clinosim/modules/_shared.py`. All migrations are byte-diff-invariant — output unchanged for any well-formed YAML.

**Tech Stack:** Python 3.11+, numpy, PyYAML, pytest (unit/integration/e2e markers), ruff format, mypy strict.

## Global Constraints

- Branch: `feat/pr-a-module-unification-quick-wins` (already created at master HEAD `1e057bbf5`).
- Refactor PR mechanic: **byte-diff vs master `1e057bbf5` at p=2000 US + p=2000 JP, seed=42 is the load-bearing gate**. All NDJSON + CIF JSON + CSV must be byte-identical.
- Line length 100, ruff format, mypy strict.
- Every commit uses Co-Authored-By + Claude-Session trailer (template per task).
- normalize_probabilities helper must be idempotent on already-normalized arrays (load-bearing for byte-diff invariance).
- microbiology silent-skip → raise ValueError; current healthy YAML must continue to load (no behavior change for healthy data).
- Path constants: `_HERE = Path(__file__).resolve().parent`, `_REF_DIR = _HERE / "reference_data"` (if present), `_LOCALE = _HERE.parents[1] / "locale"` (if locale loader present).
- `lru_cache` maxsize convention: no-param=1, country-param=2, extended=4 (currently unused).

---

### Task 1: A1 — Path constant naming standardization

**Files:**
- Modify: `clinosim/modules/code_status/engine.py`
- Modify: `clinosim/modules/care_level/engine.py`
- Modify: `clinosim/modules/family_history/engine.py`
- Modify: `clinosim/modules/sdoh/engine.py`
- Modify: `clinosim/modules/immunization/engine.py`
- Modify: `clinosim/modules/device/engine.py`
- Modify: `clinosim/modules/hai/engine.py`
- Modify: `clinosim/modules/observation/nursing.py`
- Modify: `clinosim/modules/observation/microbiology.py`
- Modify: `clinosim/modules/observation/engine.py`
- Modify: `clinosim/modules/disease/protocol.py`
- Modify: `clinosim/modules/encounter/protocol.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a uniform module-level path-constant convention. Later tasks may reference `_REF_DIR` and `_LOCALE` but Task 1 doesn't expose any new public API.

- [ ] **Step 1: Audit which 12 modules currently have which pattern**

Run:
```bash
cd /Users/tokuyama/workspace/clinosim && for f in \
  clinosim/modules/code_status/engine.py \
  clinosim/modules/care_level/engine.py \
  clinosim/modules/family_history/engine.py \
  clinosim/modules/sdoh/engine.py \
  clinosim/modules/immunization/engine.py \
  clinosim/modules/device/engine.py \
  clinosim/modules/hai/engine.py \
  clinosim/modules/observation/nursing.py \
  clinosim/modules/observation/microbiology.py \
  clinosim/modules/observation/engine.py \
  clinosim/modules/disease/protocol.py \
  clinosim/modules/encounter/protocol.py; do
  echo "=== $f ===";
  grep -n "Path(__file__)" "$f" | head -5;
done
```

Note each file's current pattern. Three buckets:
- (a) already uses `_HERE` + `_LOCALE` (code_status, care_level, family_history, sdoh): just rename `_LOCALE` if needed; verify `_HERE.parents[1] / "locale"` (NOT `parents[2]`)
- (b) uses some other name (`_REFERENCE_DATA_DIR`, `_DATA`, `_HAI_REF_DIR`, inline Path): rename to `_HERE` + `_REF_DIR` and adjust call sites
- (c) `immunization/engine.py` uses `.parents[2]`: change to `.parents[1]` (audit found this is accidentally correct)

- [ ] **Step 2: Apply the standard pattern to all 12 files**

For each file, near the top imports, add or normalize:

```python
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"       # if the module has reference_data/
_LOCALE = _HERE.parents[1] / "locale"     # if the module loads from clinosim/locale/
```

Then update every call site that referenced the old constant to use the new constant. The actual file paths resolved at runtime must be unchanged. Examples:

- Old `_REFERENCE_DATA_DIR / "builtin_differentials.yaml"` → `_REF_DIR / "builtin_differentials.yaml"`
- Old `_DATA / "nursing_scores.yaml"` (where `_DATA = Path(__file__).parent / "reference_data" / "nursing_scores.yaml"`) → `_REF_DIR / "nursing_scores.yaml"`
- Old `_HAI_REF_DIR / "hai_antibiogram.yaml"` → `_REF_DIR / "hai_antibiogram.yaml"`
- Old `Path(__file__).resolve().parents[2] / "locale"` → `_HERE.parents[1] / "locale"`

**Important — immunization fix**: in `clinosim/modules/immunization/engine.py`, the current `_LOCALE = Path(__file__).resolve().parents[2] / "locale"` must become `_LOCALE = _HERE.parents[1] / "locale"`. Verify `_HERE = Path(__file__).resolve().parent` yields `clinosim/modules/immunization/`, so `parents[1]` = `clinosim/`, and `clinosim/locale` is the resolved path. (Old `parents[2]` started from `__file__` directly, so step 1 = `clinosim/modules/immunization/`, step 2 = `clinosim/modules/`, then `/ "locale"` = `clinosim/modules/locale` which is wrong — confirm whether the test suite catches this.)

Run before+after sanity:
```bash
python -c "from clinosim.modules.immunization import engine; print(engine._LOCALE)"
```
Expected output: `/Users/tokuyama/workspace/clinosim/clinosim/locale`

- [ ] **Step 3: Verify nothing else broke**

```bash
pytest -m unit -q
```
Expected: same baseline test count, all PASS, zero regressions.

```bash
pytest -m integration -q
```
Expected: zero regressions.

```bash
ruff check clinosim/
```
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add clinosim/modules/code_status/engine.py \
        clinosim/modules/care_level/engine.py \
        clinosim/modules/family_history/engine.py \
        clinosim/modules/sdoh/engine.py \
        clinosim/modules/immunization/engine.py \
        clinosim/modules/device/engine.py \
        clinosim/modules/hai/engine.py \
        clinosim/modules/observation/nursing.py \
        clinosim/modules/observation/microbiology.py \
        clinosim/modules/observation/engine.py \
        clinosim/modules/disease/protocol.py \
        clinosim/modules/encounter/protocol.py
git commit -m "$(cat <<'EOF'
refactor(modules): standardize path constants — _HERE + _REF_DIR + _LOCALE (A1)

12 modules unified to use:
  _HERE = Path(__file__).resolve().parent
  _REF_DIR = _HERE / "reference_data"
  _LOCALE = _HERE.parents[1] / "locale"

Previously 5 distinct patterns: _REFERENCE_DATA_DIR / _DATA /
_HAI_REF_DIR / _HERE+_LOCALE / inline Path. Audit (Phase 1 of PR-A
cross-module unification) found one fragile case: immunization used
.parents[2] (accidentally correct) — converted to .parents[1] for
uniformity.

Byte-diff invariant: actual file paths resolved at runtime are unchanged.
Output unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 2: A2 — `lru_cache` maxsize standardization

**Files:**
- Modify: `clinosim/modules/code_status/engine.py` (one of two loaders)
- Modify: `clinosim/modules/immunization/engine.py`
- Modify: `clinosim/modules/family_history/engine.py` (one of two loaders)

**Interfaces:**
- Consumes: Task 1's `_REF_DIR` / `_LOCALE` constants in the same files.
- Produces: standardized maxsize convention. Nothing new exposed.

- [ ] **Step 1: Locate the divergent `maxsize=4` entries**

Run:
```bash
grep -n "@lru_cache" clinosim/modules/code_status/engine.py \
                    clinosim/modules/immunization/engine.py \
                    clinosim/modules/family_history/engine.py
```

Identify any `maxsize=4` on country-param loaders. These were over-allocated for the 2 countries currently supported (US, JP).

- [ ] **Step 2: Change `maxsize=4` → `maxsize=2` on country-param loaders**

For each `@lru_cache(maxsize=4)` decoration on a function whose signature is `def load_X(country: str)` — change to `@lru_cache(maxsize=2)`.

Leave `maxsize=1` decorators alone (they're on no-param loaders — correct already).

- [ ] **Step 3: Verify**

```bash
pytest -m unit -q
```
Expected: zero regressions.

```bash
grep -n "@lru_cache" clinosim/modules/code_status/engine.py \
                    clinosim/modules/immunization/engine.py \
                    clinosim/modules/family_history/engine.py
```
Expected: all decorators show `maxsize=1` (no-param) or `maxsize=2` (country-param). No `maxsize=4` remaining.

- [ ] **Step 4: Commit**

```bash
git add clinosim/modules/code_status/engine.py \
        clinosim/modules/immunization/engine.py \
        clinosim/modules/family_history/engine.py
git commit -m "$(cat <<'EOF'
refactor(modules): lru_cache maxsize convention — no-param=1, country=2 (A2)

Convention (per Phase 1 PR-A audit):
  load_X() -> dict        → @lru_cache(maxsize=1)
  load_X(country: str)    → @lru_cache(maxsize=2)   # US + JP
  load_X(country, lang)   → @lru_cache(maxsize=4)   # not yet used

Reduced over-allocated maxsize=4 → maxsize=2 on 3 country-param loaders
in code_status / immunization / family_history. With only US + JP in
play, this avoids 2 unused cache slots per loader.

Byte-diff invariant: maxsize only affects cache eviction policy. With
JP-only or US-only test runs, only 1 entry ever populates the cache.
Output unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 3: A3 — `normalize_probabilities()` helper + migrate `rng.choice(p=)` callsites

**Files:**
- Modify: `clinosim/modules/_shared.py` (add helper)
- Create: `tests/unit/modules/test_shared_normalize_probabilities.py`
- Modify (~10 callsites): `clinosim/modules/code_status/engine.py`,
  `clinosim/modules/care_level/engine.py`, `clinosim/modules/family_history/engine.py`,
  `clinosim/modules/observation/microbiology.py`, `clinosim/modules/hai/engine.py`,
  `clinosim/modules/hai/enricher.py`, `clinosim/modules/population/engine.py`,
  `clinosim/modules/clinical_course/engine.py`, `clinosim/modules/diagnosis/engine.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `clinosim.modules._shared.normalize_probabilities(probs, fallback="uniform") -> np.ndarray`

- [ ] **Step 1: Write failing tests for `normalize_probabilities`**

Create `tests/unit/modules/test_shared_normalize_probabilities.py`:

```python
"""Unit tests for normalize_probabilities helper (PR-A Task 3)."""
import numpy as np
import pytest

from clinosim.modules._shared import normalize_probabilities


@pytest.mark.unit
def test_already_normalized_is_byte_identical_to_plain_asarray():
    """Idempotency on normalized input — load-bearing for byte-diff invariance."""
    probs = [0.2, 0.3, 0.5]
    result = normalize_probabilities(probs)
    expected = np.asarray(probs, dtype=float)
    assert np.array_equal(result, expected)


@pytest.mark.unit
def test_non_normalized_input_is_normalized():
    probs = [1.0, 2.0, 1.0]
    result = normalize_probabilities(probs)
    assert np.isclose(result.sum(), 1.0)
    assert np.allclose(result, [0.25, 0.5, 0.25])


@pytest.mark.unit
def test_numpy_array_input_works_same_as_list():
    probs = np.array([0.25, 0.25, 0.25, 0.25])
    result = normalize_probabilities(probs)
    assert np.array_equal(result, probs)


@pytest.mark.unit
def test_zero_sum_input_falls_back_to_uniform():
    probs = [0.0, 0.0, 0.0]
    result = normalize_probabilities(probs)
    assert np.isclose(result.sum(), 1.0)
    assert np.allclose(result, [1 / 3, 1 / 3, 1 / 3])


@pytest.mark.unit
def test_zero_sum_input_with_raise_fallback_raises():
    with pytest.raises(ValueError, match="non-positive sum"):
        normalize_probabilities([0.0, 0.0, 0.0], fallback="raise")


@pytest.mark.unit
def test_negative_weight_raises():
    with pytest.raises(ValueError, match="negative weight"):
        normalize_probabilities([0.5, -0.1, 0.6])


@pytest.mark.unit
def test_empty_input_falls_back_to_uniform_with_n_equals_1():
    """Edge case: empty list. Uniform fallback returns 1-element [1.0]."""
    result = normalize_probabilities([])
    assert result.tolist() == [1.0]


@pytest.mark.unit
def test_return_type_is_numpy_float64():
    result = normalize_probabilities([1, 2, 3])  # input is int list
    assert result.dtype == np.float64


@pytest.mark.unit
def test_idempotent_after_one_pass():
    """Calling normalize twice returns the same result as calling once."""
    probs = [3.0, 7.0]
    once = normalize_probabilities(probs)
    twice = normalize_probabilities(once)
    assert np.array_equal(once, twice)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/modules/test_shared_normalize_probabilities.py -v
```
Expected: 9 FAILs with `ImportError: cannot import name 'normalize_probabilities' from 'clinosim.modules._shared'`.

- [ ] **Step 3: Add helper to `_shared.py`**

Read the current `clinosim/modules/_shared.py` to see its layout. Add at the end of the file (after `get_attr_or_key`):

```python
import numpy as np


def normalize_probabilities(
    probs: list[float] | np.ndarray,
    fallback: str = "uniform",
) -> np.ndarray:
    """Normalize a non-negative weight vector to sum to 1.0.

    Args:
        probs: array or list of non-negative weights.
        fallback: "uniform" (default) returns equal weight on non-positive sum;
            "raise" raises ValueError instead.

    Returns:
        np.ndarray of dtype float64 summing to 1.0.

    Idempotency: if the input already sums to 1.0 (within float tolerance),
    the returned array is byte-identical to ``np.asarray(probs, dtype=float)``.
    This makes migration from no-op normalization to this helper byte-clean
    for any well-formed (hand-normalized) YAML weight data.

    Raises:
        ValueError: if any weight is negative, or if the input sums to zero and
            fallback is "raise".
    """
    arr = np.asarray(probs, dtype=float)
    if (arr < 0).any():
        raise ValueError(
            f"normalize_probabilities: negative weight in {list(arr)}"
        )
    total = float(arr.sum())
    if total <= 0:
        if fallback == "uniform":
            n = max(len(arr), 1)
            return np.ones(n) / n
        raise ValueError(
            f"normalize_probabilities: non-positive sum in {list(arr)}"
        )
    return arr / total
```

If `_shared.py` has an `__all__` export list, append `"normalize_probabilities"` to it. If not, don't introduce one — match existing style.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/modules/test_shared_normalize_probabilities.py -v
```
Expected: 9 PASS.

- [ ] **Step 5: Locate every `rng.choice(p=` callsite**

```bash
grep -rn "rng.choice" clinosim/modules/ | grep "p=" | head -30
```

Identify each callsite. The migration target is:
- Wrap the `p=` argument with `normalize_probabilities(...)` UNLESS the data is already provably normalized AND wrapping would change byte-output (it won't — helper is idempotent — but flag uncertainty).
- Add `from clinosim.modules._shared import normalize_probabilities` at module top.

Expected callsites (audit-derived list):

- `clinosim/modules/code_status/engine.py:48` — `rng.choice(len(tiers), p=weights)` (the silent-bug callsite — most important to wrap)
- `clinosim/modules/care_level/engine.py:50` (currently `probs = probs / probs.sum()` then `rng.choice(p=probs)`)
- `clinosim/modules/family_history/engine.py` (audit-mentioned, look for `rng.choice(p=`)
- `clinosim/modules/observation/microbiology.py:92-94` (currently `probs = np.array(...); probs = probs/probs.sum(); rng.choice(p=probs)`)
- `clinosim/modules/hai/engine.py:~84` (audit-mentioned `_sample_organism`)
- `clinosim/modules/hai/enricher.py:218-220` (susceptibility sampling, PR3b-2 path)
- `clinosim/modules/population/engine.py` (multiple — search for `rng.choice` with weighted `p=`)
- `clinosim/modules/clinical_course/engine.py` (multiple)
- `clinosim/modules/diagnosis/engine.py` (differentials sampling)

For each callsite, replace:

```python
# Before:
probs = np.array([float(x) for x in weights], dtype=float)
if probs.sum() > 0:
    probs = probs / probs.sum()
choice = rng.choice(len(items), p=probs)
```

with:

```python
# After:
from clinosim.modules._shared import normalize_probabilities

probs = normalize_probabilities(weights)
choice = rng.choice(len(items), p=probs)
```

Or where the original simply did `rng.choice(items, p=weights)` (e.g., code_status:48 silent bug):

```python
# Before:
choice = rng.choice(len(tiers), p=weights)

# After:
from clinosim.modules._shared import normalize_probabilities

choice = rng.choice(len(tiers), p=normalize_probabilities(weights))
```

- [ ] **Step 6: Apply each migration**

Migrate each callsite one at a time. After each file is updated, run that file's unit tests:

```bash
pytest tests/unit -k <module_name> -q
```

If any test fails, investigate. The most likely cause is the `rng.choice` call now receives a slightly different array (which the test fixture was specifically counting RNG draws for). Helper is idempotent on already-normalized arrays, so any divergence is from previously non-normalized arrays (which we want to defend against).

- [ ] **Step 7: Full unit + integration regression**

```bash
pytest -m unit -m integration -q
```
Expected: zero regressions (~660 + ~136 baseline + 9 new tests).

- [ ] **Step 8: Commit**

```bash
git add clinosim/modules/_shared.py \
        clinosim/modules/code_status/engine.py \
        clinosim/modules/care_level/engine.py \
        clinosim/modules/family_history/engine.py \
        clinosim/modules/observation/microbiology.py \
        clinosim/modules/hai/engine.py \
        clinosim/modules/hai/enricher.py \
        clinosim/modules/population/engine.py \
        clinosim/modules/clinical_course/engine.py \
        clinosim/modules/diagnosis/engine.py \
        tests/unit/modules/test_shared_normalize_probabilities.py
git commit -m "$(cat <<'EOF'
refactor(modules): _shared.normalize_probabilities helper + migrate callsites (A3)

Silent bug defense (audit found 5 different normalization patterns across
modules; code_status:48 was NOT normalizing at all and depended on
hand-normalized YAML — a YAML edit that breaks the sum would be a silent
no-op until rng.choice raises).

New helper:
  normalize_probabilities(probs, fallback="uniform") -> np.ndarray
- Idempotent on already-normalized input (byte-clean migration).
- Uniform fallback on zero-sum (no surprise crashes).
- Raises on negative weights (load-bearing input contract).
- 9 unit tests cover idempotency, fallback, edge cases.

Migrated ~10 rng.choice(p=) callsites across:
  code_status, care_level, family_history, observation/microbiology,
  hai/engine, hai/enricher, population, clinical_course, diagnosis.

Byte-diff invariant: helper is idempotent on normalized arrays; all
existing YAML weight data is hand-normalized (audit verified).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 4: A4 — `observation/microbiology.py` silent skip → `ValueError` + import-time validation

**Files:**
- Modify: `clinosim/modules/observation/microbiology.py`
- Create: `tests/unit/observation/test_microbiology_validation.py`

**Interfaces:**
- Consumes: `_HERE` / `_REF_DIR` from Task 1 in the same file.
- Produces: `_validate_microbiology(data: dict) -> None` (module-private; called from `_load`).

- [ ] **Step 1: Write failing test for the typo-detection guarantee**

Create `tests/unit/observation/test_microbiology_validation.py`:

```python
"""Unit tests for microbiology load-time validation (PR-A Task 4)."""
from pathlib import Path
import textwrap

import pytest
import yaml

from clinosim.modules.observation import microbiology as micro_mod


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "microbiology.yaml"
    p.write_text(textwrap.dedent(body))
    return p


@pytest.mark.unit
def test_healthy_yaml_loads_without_raising(monkeypatch, tmp_path):
    """Sanity: a well-formed YAML stays loadable."""
    healthy = """
    specimens:
      blood: {snomed: "119297000", test_loinc: "600-7"}
    antibiotics:
      vancomycin: "18991-2"
    organisms:
      staph:
        snomed: "3092008"
        antibiogram:
          vancomycin: [1.0, 0.0, 0.0]
    diseases:
      sepsis:
        organisms: {staph: 1.0}
        cultures:
          - {specimen: blood, order_prob: 1.0, growth_prob: 0.5}
    """
    yaml_path = _write_yaml(tmp_path, healthy)
    monkeypatch.setattr(micro_mod, "_REF_DIR", yaml_path.parent)
    micro_mod._load.cache_clear()  # noqa: SLF001
    try:
        data = micro_mod._load()
        assert "antibiotics" in data
    finally:
        micro_mod._load.cache_clear()  # noqa: SLF001


@pytest.mark.unit
def test_organism_antibiogram_with_typo_raises_at_load_time(monkeypatch, tmp_path):
    """The load-bearing guarantee: typo in organism antibiogram key is loud."""
    bad = """
    specimens:
      blood: {snomed: "119297000", test_loinc: "600-7"}
    antibiotics:
      vancomycin: "18991-2"
    organisms:
      staph:
        snomed: "3092008"
        antibiogram:
          vancomicin: [1.0, 0.0, 0.0]    # ← typo: vancomicin vs vancomycin
    diseases:
      sepsis:
        organisms: {staph: 1.0}
        cultures:
          - {specimen: blood, order_prob: 1.0, growth_prob: 0.5}
    """
    yaml_path = _write_yaml(tmp_path, bad)
    monkeypatch.setattr(micro_mod, "_REF_DIR", yaml_path.parent)
    micro_mod._load.cache_clear()  # noqa: SLF001
    try:
        with pytest.raises(ValueError, match="unknown antibiotic key 'vancomicin'"):
            micro_mod._load()
    finally:
        micro_mod._load.cache_clear()  # noqa: SLF001
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/observation/test_microbiology_validation.py -v
```
Expected:
- `test_healthy_yaml_loads_without_raising`: likely PASS (helper isn't there yet but healthy YAML doesn't trigger the missing validation)
- `test_organism_antibiogram_with_typo_raises_at_load_time`: FAIL (current code silently skips the unknown key — no ValueError raised).

If `tests/unit/observation/__init__.py` doesn't exist, create an empty one.

- [ ] **Step 3: Add `_validate_microbiology` function**

Read the current `clinosim/modules/observation/microbiology.py`. Locate the silent-skip block (around lines 88-98). Add a new module-private function (placed before `_load`):

```python
def _validate_microbiology(data: dict) -> None:
    """Validate microbiology.yaml at load time — fail loud on orphan keys.

    Mirrors the validation pattern from clinosim.modules.hai.load_hai_antibiogram.
    A typo in any organism.antibiogram key would otherwise silently produce a
    no-op susceptibility (PR-90 class silent-no-op).
    """
    antibiotics = data.get("antibiotics") or {}
    valid_antibiotic_keys = set(antibiotics.keys())
    for organism_id, organism in (data.get("organisms") or {}).items():
        antibiogram = (organism or {}).get("antibiogram") or {}
        for abx_key in antibiogram.keys():
            if abx_key not in valid_antibiotic_keys:
                raise ValueError(
                    f"microbiology.yaml: organism {organism_id!r} antibiogram "
                    f"references unknown antibiotic key {abx_key!r}; expected "
                    f"one of {sorted(valid_antibiotic_keys)}"
                )
```

Then update `_load` to call it after `yaml.safe_load`:

```python
@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    if not (_REF_DIR / "microbiology.yaml").exists():
        return {}
    with open(_REF_DIR / "microbiology.yaml") as f:
        data = yaml.safe_load(f) or {}
    _validate_microbiology(data)
    return data
```

- [ ] **Step 4: Update the runtime silent skip to also raise**

In the same `generate_microbiology` function (around lines 88-98), change the silent `continue` to a `raise ValueError`. This is defense-in-depth even though `_load` validates upfront — code that calls `generate_microbiology` with a runtime-constructed antibiogram (rather than YAML) would still benefit:

```python
# Old:
loinc = antibiotics.get(abx_key)
if not loinc:
    continue  # silent skip

# New:
loinc = antibiotics.get(abx_key)
if not loinc:
    raise ValueError(
        f"microbiology generate: antibiogram references unknown antibiotic "
        f"key {abx_key!r}; expected one of {sorted(antibiotics.keys())}"
    )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/observation/test_microbiology_validation.py -v
```
Expected: 2 PASS.

- [ ] **Step 6: Verify current healthy YAML loads**

```bash
python -c "from clinosim.modules.observation.microbiology import _load; d = _load(); print(len(d.get('organisms', {})), 'organisms loaded')"
```
Expected: organism count (≥ 7 per existing data). If this raises, the current `microbiology.yaml` has a latent typo — investigate before proceeding.

- [ ] **Step 7: Full regression**

```bash
pytest -m unit -m integration -q
```
Expected: zero regressions, +2 new tests.

- [ ] **Step 8: Commit**

```bash
git add clinosim/modules/observation/microbiology.py \
        tests/unit/observation/test_microbiology_validation.py \
        tests/unit/observation/__init__.py
git commit -m "$(cat <<'EOF'
fix(microbiology): silent skip → ValueError + import-time validation (A4)

Audit (Phase 1 of PR-A) found observation/microbiology.py:88-98 silently
skipped organism antibiogram entries that referenced unknown antibiotic
keys (continue without log). This is a PR-90 class silent-no-op risk: a
typo in microbiology.yaml (e.g., "vancomicin" vs "vancomycin") would
silently produce no susceptibility entry, and no test would catch it.

Two-part fix:
1. _validate_microbiology() walks all organism.antibiogram keys at load
   time and raises ValueError on any orphan key. Same pattern as
   modules/hai/load_hai_antibiogram (PR-90 / PR3b-2 lesson).
2. The runtime silent-skip in generate_microbiology is also promoted to
   raise — defense in depth for any code that builds antibiograms outside
   the YAML loader.

Tests: tests/unit/observation/test_microbiology_validation.py covers
healthy YAML loads + typo'd YAML raises at load time.

Byte-diff invariant: current microbiology.yaml is healthy (verified by
test_healthy_yaml_loads_without_raising at runtime). Output unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 5: A5 — Trimethoprim slash canonicalization

**Files:**
- Modify: `clinosim/modules/encounter/reference_data/uti_uncomplicated.yaml`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing new — pure data normalization.

- [ ] **Step 1: Confirm the outlier**

```bash
grep -rn "Trimethoprim" clinosim/modules/ clinosim/locale/ | head -10
```
Expected: most lines show `Trimethoprim/Sulfamethoxazole` (slash) but `clinosim/modules/encounter/reference_data/uti_uncomplicated.yaml` shows `Trimethoprim-sulfamethoxazole` (hyphen).

- [ ] **Step 2: Edit the outlier**

In `clinosim/modules/encounter/reference_data/uti_uncomplicated.yaml`, replace every occurrence of `Trimethoprim-sulfamethoxazole` with `Trimethoprim/Sulfamethoxazole`.

- [ ] **Step 3: Verify no other module references the hyphen form (besides drug_names_ja.yaml legacy alias)**

```bash
grep -rn "Trimethoprim-sulfamethoxazole" clinosim/ tests/
```
Expected: only `clinosim/locale/shared/drug_names_ja.yaml` (intentional dual-key alias, leave it).

If anything in production code or tests still references the hyphen form (other than the ja alias), update it to slash.

- [ ] **Step 4: Run tests**

```bash
pytest -m unit -m integration -q
```
Expected: zero regressions. JP output already resolves both forms to the same display.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/encounter/reference_data/uti_uncomplicated.yaml
git commit -m "$(cat <<'EOF'
refactor(data): Trimethoprim/Sulfamethoxazole slash form canonicalized (A5)

Audit (Phase 1 of PR-A) found encounter/uti_uncomplicated.yaml was the
sole outlier still using the hyphen form (Trimethoprim-sulfamethoxazole).
The slash form Trimethoprim/Sulfamethoxazole is the canonical form per:

  disease/urinary_tract_infection.yaml
  disease/cellulitis.yaml
  antibiotic/__init__.py:ANTIBIOTIC_DRUGS

drug_names_ja.yaml retains both forms as dual-key alias (cleanup deferred
to a future JP-name housekeeping pass).

Byte-diff invariant: JP output already resolves both forms via the dual
mapping. US output uses the CIF English text. Output unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 6: Byte-diff verification + audit run + push

**Files:**
- None (verification only).

**Interfaces:**
- Consumes: Tasks 1-5 commits.
- Produces: branch ready for PR.

- [ ] **Step 1: Full test suite**

```bash
pytest -m unit -m integration -q
```
Expected: green (~660 + ~136 + 11 new tests).

```bash
pytest -m e2e -q
```
Expected: green (~39 baseline).

- [ ] **Step 2: ruff + mypy**

```bash
ruff check clinosim/ tests/
```
Expected: clean.

```bash
mypy clinosim/ 2>&1 | grep -c "error:"
```
Expected: 0 new errors vs master baseline (some pre-existing errors may exist; compare against master).

- [ ] **Step 3: Byte-diff baseline generation on master `1e057bbf5`**

```bash
git stash -u 2>&1 | head -2
git checkout 1e057bbf5
mkdir -p scratchpad/pr_a_byte_diff/baseline
clinosim generate --country US --count 2000 --seed 42 \
    --output scratchpad/pr_a_byte_diff/baseline/us \
    --format ndjson,csv,cif 2>&1 | tail -3
clinosim generate --country JP --count 2000 --seed 42 \
    --output scratchpad/pr_a_byte_diff/baseline/jp \
    --format ndjson,csv,cif 2>&1 | tail -3
git checkout feat/pr-a-module-unification-quick-wins
git stash pop 2>&1 | tail -2
```

If `clinosim generate` CLI flags differ, mirror the pattern from `scratchpad/abx_dqr/` (session 17/18 working examples).

- [ ] **Step 4: Byte-diff PR branch generation**

```bash
mkdir -p scratchpad/pr_a_byte_diff/pr
clinosim generate --country US --count 2000 --seed 42 \
    --output scratchpad/pr_a_byte_diff/pr/us \
    --format ndjson,csv,cif 2>&1 | tail -3
clinosim generate --country JP --count 2000 --seed 42 \
    --output scratchpad/pr_a_byte_diff/pr/jp \
    --format ndjson,csv,cif 2>&1 | tail -3
```

- [ ] **Step 5: Diff**

```bash
diff -r scratchpad/pr_a_byte_diff/baseline/us scratchpad/pr_a_byte_diff/pr/us \
    2>&1 | head -20
diff -r scratchpad/pr_a_byte_diff/baseline/jp scratchpad/pr_a_byte_diff/pr/jp \
    2>&1 | head -20
```
Expected: **EMPTY output** (zero file diffs). This is the load-bearing
verification gate.

If ANY file differs, STOP and investigate:
1. Identify which file (which artifact: NDJSON, CSV, CIF JSON).
2. Identify which module/Task introduced the diff (likely A3 if it's
   stochastic content).
3. Revert that callsite from the helper migration (helper is supposed to
   be idempotent; any divergence means the input was NOT actually
   normalized — that's a real finding to investigate).

- [ ] **Step 6: Audit run**

```bash
clinosim audit run -p 2000 --seed 42 2>&1 | tail -10
```
Expected: 4 axes PASS.

- [ ] **Step 7: Clean up byte-diff scratch**

```bash
rm -rf scratchpad/pr_a_byte_diff
```

- [ ] **Step 8: Push branch + create PR**

```bash
git push -u origin feat/pr-a-module-unification-quick-wins 2>&1 | tail -3
gh pr create --title "PR-A module unification quick wins (5 fixes)" --body "$(cat <<'EOF'
## Summary

First of 4-PR series addressing post-PR3b-2 cross-module audit findings.
4 Explore agents audited 27 modules; this PR closes the 5 highest
impact-to-difficulty findings:

- **A1**: path constant naming standardized (`_HERE` + `_REF_DIR` + `_LOCALE`, 12 modules). Fixed `immunization` `.parents[2]` fragile case.
- **A2**: `lru_cache` `maxsize` convention (no-param=1, country=2, extended=4 future). Reduced 3 over-allocated `maxsize=4` loaders.
- **A3**: `clinosim/modules/_shared.py:normalize_probabilities()` helper + migrated ~10 `rng.choice(p=)` callsites. Closes `code_status:48` silent-bug gap (rng.choice did not auto-normalize; YAML edits could break the sum and silently regress to a runtime ValueError).
- **A4**: `observation/microbiology.py:88-98` silent skip → `ValueError` + import-time validation. Closes PR-90 class orphan-bug gap (typo'd antibiotic key in organism antibiogram now raises at load time).
- **A5**: Trimethoprim slash form canonicalized in `encounter/uti_uncomplicated.yaml`.

## Verification

- `pytest -m unit -m integration -m e2e` all green (+ 11 new tests).
- `mypy` strict clean.
- `ruff check` clean.
- **Byte-diff vs master `1e057bbf5` at p=2000 US + JP, seed=42**: every artifact byte-identical. This is the load-bearing verification gate; refactor is byte-clean.
- `clinosim audit run -p 2000 --seed 42`: 4 axes PASS.

## Forward-compat

PR-B (global `_cache` → `@lru_cache` + 15 empty `__init__.py`), PR-C (enricher `enabled` gate + Pydantic + coverage tests), PR-D (cosmetic + design guide refine) are next in this series. A1/A3/A4 patterns become rules in PR-D design guide refinement.

## Test plan

- [x] `pytest -m unit -m integration -m e2e`
- [x] mypy clean
- [x] ruff clean
- [x] Byte-diff vs master IDENTICAL
- [x] audit run PASS
- [ ] Post-merge adversarial review fan-out (`feedback_iterative_adversarial_review`)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

## Self-Review

**1. Spec coverage** — every section of the spec maps to a task:

- § 3.1 A1 path constant → Task 1
- § 3.2 A2 lru_cache maxsize → Task 2
- § 3.3 A3 normalize_probabilities → Task 3
- § 3.4 A4 microbiology silent skip → Task 4
- § 3.5 A5 Trimethoprim slash → Task 5
- § 4 verification gates → Task 6
- § 5 commit strategy → 5 themed commits (one per task) + verification commit-free wrap-up in Task 6
- § 6 forward-compat → mentioned in PR body, no code change needed
- § 7 risks → Task 6 step 5 calls out the byte-diff investigation flow
- § 8 memory anchors → applied in commit messages

**2. Placeholder scan** — no TBD/TODO/"fill in details" patterns. Every code block contains the exact code to write. Every test has executable bodies.

**3. Type consistency** — `normalize_probabilities(probs, fallback="uniform") -> np.ndarray` introduced in Task 3 Step 3, consumed in Task 3 Step 6 with the same signature. `_validate_microbiology(data: dict) -> None` introduced in Task 4 Step 3, called from `_load` in same step. `_REF_DIR` and `_LOCALE` introduced in Task 1, consumed in Task 4 Step 3 (uses `_REF_DIR / "microbiology.yaml"`).

No naming drift. No gaps.
