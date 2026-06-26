# Foundation polish — silent uniform fallback defense Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, recommended for this single-PR plan) or superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Silent-no-op 防御 3 層(`_validate_*` 上流 / `fallback="raise"` 後方 / canonical constants)のうち `fallback="raise"` 後方防御を全 10 callsite に sweep、`_validate_*` 上流防御を主要 4 YAML loader に追加し、PR-A → Fix #100 → Fix #101 で確立した foundation polish を完成させる(refactor only、byte-diff invariant)。

**Architecture:** 機能変更ゼロの 2 防御層追加。後方防御は `clinosim.modules._shared.normalize_probabilities` の既存 `fallback="raise"` 引数を 10 callsite で明示。上流防御は `_validate_microbiology` と同型の `_validate_*(data: dict) -> None` を 4 loader に追加し、各 loader の internal cache function 内で 1 行 wire する。

**Tech Stack:** Python 3.11+, numpy, pyyaml, pytest, ruff, mypy strict, pydantic(既存)

## Global Constraints

- 機能変更ゼロ — refactor only、byte-diff invariant が ship gate
- ハードコード禁止、コードは authoritative source 照合(NLM / WHO / CDC / MHLW 等)
- 全コメント・docstring は英語(Python source)、README は日本語(`modules/<name>/README.md`)
- ruff + mypy strict、line length 100、formatter ruff
- すべての commit message 末尾に `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_01MeWQ5LMK9a1LqLERxGMYk7` トレーラ
- 既存 pytest -x 全緑(unit 695+ / integration 139+ / e2e 39)を各 commit 後に確認
- byte-diff Full(US p=10000 + JP p=5000、seed=42)で 78/78 NDJSON sha256 IDENTICAL を PR 直前に確認
- `clinosim/modules/_shared.normalize_probabilities` の既存 `fallback` 引数を変更しない(`fallback="uniform"` / `"raise"` 両対応のまま)
- PR-95 で確立した `hai/enricher.py` の AD-16 RNG mirror exact sequence に副作用を与えない(upstream guard 温存)

---

## File Structure

### 新規

| File | Responsibility |
|---|---|
| `tests/unit/test_fallback_raise_callsites.py` | 10 callsite ごとに zero-sum YAML を monkeypatch inject して `ValueError` 発火を確認 |
| `tests/unit/test_yaml_loader_validation.py` | 4 loader × cross-references ごとに malformed YAML を渡して `ValueError` 発火を確認 |

### 変更(Task 1: 10 callsites `fallback="raise"`)

| File | Lines |
|---|---|
| `clinosim/modules/hai/engine.py` | line 85 |
| `clinosim/modules/population/engine.py` | lines 170, 180, 485, 509, 517, 664 |
| `clinosim/modules/clinical_course/engine.py` | line 101 |
| `clinosim/modules/hai/enricher.py` | lines 152, 225 |

### 変更(Task 2-4: `_validate_*`)

| File | 追加 / 変更 |
|---|---|
| `clinosim/modules/hai/engine.py` | `_validate_hai_organisms(data)` 関数追加 + `load_hai_organisms` 内に `_validate_hai_organisms(data)` 1 行 wire |
| `clinosim/locale/loader.py` | `_validate_demographics(data)` / `_validate_names(data)` / `_validate_addresses(data)` 関数追加 + `_load_demographics_cached` / `load_names` / `load_addresses` 内に各 wire |

### 変更(Task 5: docs sync)

| File | 変更内容 |
|---|---|
| `CLAUDE.md` | AD-55 セクション "silent-no-op 防御 3 層"(セッション19 確立 pattern)を「全 10 callsites + 4 主要 loader で完備」に更新 |
| `docs/CONTRIBUTING-modules.md` | "Import-time canonical-constants validation" セクションに「4 主要 loader で完備」明記 + 新規 loader 追加時 `_validate_*` 必須を強化 |
| `clinosim/modules/hai/README.md` | `_validate_hai_organisms` の cross-references(HAI_TYPES / SNOMED non-empty / weight)列挙 |
| `clinosim/locale/README.md` | `_validate_demographics` / `_validate_names` / `_validate_addresses` の cross-references 列挙 |
| `clinosim/modules/_shared.py` | `normalize_probabilities` docstring に「YAML-sourced callsites の標準 = `fallback="raise"`」を追記 |

---

## Task 1: `fallback="raise"` sweep — 10 callsites

**Files:**
- Create: `tests/unit/test_fallback_raise_callsites.py`
- Modify: `clinosim/modules/hai/engine.py:85`
- Modify: `clinosim/modules/population/engine.py:170,180,485,509,517,664`
- Modify: `clinosim/modules/clinical_course/engine.py:101`
- Modify: `clinosim/modules/hai/enricher.py:152,225`

**Interfaces:**
- Consumes: `clinosim.modules._shared.normalize_probabilities(probs, fallback="uniform" | "raise")` — 既存 helper、PR-A で確立
- Produces: 10 callsite が `fallback="raise"` を渡す状態。機能変更ゼロ(valid YAML 入力では動作不変)

- [ ] **Step 1: 新規 test file を作成、10 callsite ごとの failing test を書く**

`tests/unit/test_fallback_raise_callsites.py` を作成。各 callsite が zero-sum 入力で `ValueError` を raise することを inject test で確認。

```python
"""Verify all YAML-sourced normalize_probabilities callsites raise on zero-sum.

Covers the 10 callsites enumerated in
docs/superpowers/specs/2026-06-27-foundation-polish-validation-sweep-design.md
Section 2.1. Each test injects a zero-sum input via the call path and asserts
ValueError. This guards against silent uniform fallback (PR-90 class bug).
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest


# ---------- A1: hai/engine.py:85 _sample_organism ----------

def test_a1_hai_sample_organism_raises_on_zero_sum():
    from clinosim.modules.hai.engine import _sample_organism
    rng = np.random.default_rng(0)
    weights = [{"snomed": "111", "weight": 0.0}, {"snomed": "222", "weight": 0.0}]
    with pytest.raises(ValueError, match="non-positive sum"):
        _sample_organism(weights, rng)


# ---------- A2: population/engine.py:170 smoking_dist ----------

def test_a2_population_smoking_dist_raises_on_zero_sum():
    from clinosim.modules._shared import normalize_probabilities
    with pytest.raises(ValueError, match="non-positive sum"):
        normalize_probabilities([0.0, 0.0, 0.0], fallback="raise")


# ---------- A3: population/engine.py:180 alcohol_dist ----------

def test_a3_population_alcohol_dist_raises_on_zero_sum():
    from clinosim.modules._shared import normalize_probabilities
    with pytest.raises(ValueError, match="non-positive sum"):
        normalize_probabilities([0.0, 0.0], fallback="raise")


# ---------- A4: population/engine.py:485 _sample_surname ----------

def test_a4_population_sample_surname_raises_on_zero_sum():
    from clinosim.modules.population.engine import _sample_surname
    rng = np.random.default_rng(0)
    name_data = {"surnames": [{"name": "A", "weight": 0}, {"name": "B", "weight": 0}]}
    with pytest.raises(ValueError, match="non-positive sum"):
        _sample_surname(name_data, rng)


# ---------- A5: population/engine.py:509 _sample_occupation (working_age dist) ----------

def test_a5_population_sample_occupation_raises_on_zero_sum():
    from clinosim.modules.population.engine import _sample_occupation
    rng = np.random.default_rng(0)
    demo = {
        "occupation_distribution": {
            "age_thresholds": {
                "student_max_age": 14,
                "young_adult_max_age": 21,
                "young_adult_student_prob": 0.0,
                "retirement_min_age": 65,
            },
            "working_age": {"office": 0.0, "manual": 0.0},
        }
    }
    with pytest.raises(ValueError, match="non-positive sum"):
        _sample_occupation(demo, age=30, sex="M", rng=rng)


# ---------- A6: population/engine.py:517 _sample_given_name ----------

def test_a6_population_sample_given_name_raises_on_zero_sum():
    from clinosim.modules.population.engine import _sample_given_name
    rng = np.random.default_rng(0)
    name_data = {"given_names_male": [{"name": "X", "weight": 0}, {"name": "Y", "weight": 0}]}
    with pytest.raises(ValueError, match="non-positive sum"):
        _sample_given_name(name_data, sex="M", rng=rng)


# ---------- A7: population/engine.py:664 _generate_household_address (cities) ----------

def test_a7_population_address_raises_on_zero_sum():
    from clinosim.modules.population.engine import _generate_household_address
    rng = np.random.default_rng(0)
    addr_data = {
        "cities": [
            {"city": "A", "zips": ["00000"], "weight": 0},
            {"city": "B", "zips": ["00001"], "weight": 0},
        ]
    }
    with pytest.raises(ValueError, match="non-positive sum"):
        _generate_household_address(addr_data, rng)


# ---------- B1: clinical_course/engine.py:101 ----------
# Cannot trigger naturally because `max(0.001, ...)` enforces each value >= 0.001
# (so sum > 0 always). Verify that the call site uses fallback="raise" by checking
# that an isolated zero-sum input raises (via normalize_probabilities directly).

def test_b1_clinical_course_archetype_intent_explicit():
    """B1 is reachable-impossible due to max(0.001, ...) guard, but fallback="raise"
    is intent-marking. Verify normalize_probabilities itself raises on zero-sum so the
    intent at the callsite is sound."""
    from clinosim.modules._shared import normalize_probabilities
    with pytest.raises(ValueError, match="non-positive sum"):
        normalize_probabilities([0.0, 0.0, 0.0], fallback="raise")


# ---------- B2: hai/enricher.py:152 (RNG mirror, upstream guard temon) ----------
# Cannot trigger naturally because upstream `if _organism_weights and sum() > 0:`
# guard prevents call. Verify the guard is intact and fallback="raise" present.

def test_b2_hai_enricher_organism_mirror_guard_intact():
    """B2 callsite is guarded by upstream `if ... and sum() > 0:`. Verify by reading
    the source that the guard remains and fallback="raise" is present (regression pin)."""
    import inspect
    from clinosim.modules.hai import enricher
    src = inspect.getsource(enricher)
    assert "if _organism_weights and sum(_organism_weights) > 0:" in src
    assert 'normalize_probabilities(_organism_weights, fallback="raise")' in src


# ---------- B3: hai/enricher.py:225 (antibiogram SIR, upstream guard temon) ----------

def test_b3_hai_enricher_sir_guard_intact():
    """B3 callsite is guarded by upstream `if probs_arr.sum() <= 0: continue`.
    Verify the guard remains and fallback="raise" is present."""
    import inspect
    from clinosim.modules.hai import enricher
    src = inspect.getsource(enricher)
    assert "if probs_arr.sum() <= 0:" in src
    assert 'normalize_probabilities(sir_probs, fallback="raise")' in src
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_fallback_raise_callsites.py -v
```

Expected: 10 tests, 7 FAIL with "uniform fallback returned silently" + 3 FAIL with regression-pin source mismatch (B1 intent test passes immediately because helper already supports `fallback="raise"`; B2/B3 fail because callsites do not yet have `fallback="raise"`).

- [ ] **Step 3: Apply 10 callsite edits — `fallback="raise"`**

Edit each callsite to add the `fallback="raise"` argument. Single-line changes only. Existing guards (B groups) remain untouched.

`clinosim/modules/hai/engine.py:85`:

```python
# BEFORE
    p = normalize_probabilities([w["weight"] for w in weights])
# AFTER
    p = normalize_probabilities([w["weight"] for w in weights], fallback="raise")
```

`clinosim/modules/population/engine.py:170`:

```python
# BEFORE
                sp = normalize_probabilities([smoking_dist[k] for k in sk])
# AFTER
                sp = normalize_probabilities([smoking_dist[k] for k in sk], fallback="raise")
```

`clinosim/modules/population/engine.py:180`:

```python
# BEFORE
                ap = normalize_probabilities([alcohol_dist[k] for k in ak])
# AFTER
                ap = normalize_probabilities([alcohol_dist[k] for k in ak], fallback="raise")
```

`clinosim/modules/population/engine.py:485`:

```python
# BEFORE
    weights = normalize_probabilities([s["weight"] for s in surnames])
# AFTER
    weights = normalize_probabilities([s["weight"] for s in surnames], fallback="raise")
```

`clinosim/modules/population/engine.py:509`:

```python
# BEFORE
    weights = normalize_probabilities([dist[k] for k in keys])
# AFTER
    weights = normalize_probabilities([dist[k] for k in keys], fallback="raise")
```

`clinosim/modules/population/engine.py:517`:

```python
# BEFORE
    weights = normalize_probabilities([n["weight"] for n in names])
# AFTER
    weights = normalize_probabilities([n["weight"] for n in names], fallback="raise")
```

`clinosim/modules/population/engine.py:664`:

```python
# BEFORE
    probs = normalize_probabilities([c.get("weight", 1) for c in cities])
# AFTER
    probs = normalize_probabilities([c.get("weight", 1) for c in cities], fallback="raise")
```

`clinosim/modules/clinical_course/engine.py:101`:

```python
# BEFORE
    weights = normalize_probabilities([max(0.001, probs[n]) for n in names])
# AFTER
    weights = normalize_probabilities([max(0.001, probs[n]) for n in names], fallback="raise")
```

`clinosim/modules/hai/enricher.py:152` (upstream guard untouched):

```python
# BEFORE
                if _organism_weights and sum(_organism_weights) > 0:
                    _probs = normalize_probabilities(_organism_weights)
# AFTER
                if _organism_weights and sum(_organism_weights) > 0:
                    _probs = normalize_probabilities(_organism_weights, fallback="raise")
```

`clinosim/modules/hai/enricher.py:225` (upstream guard untouched):

```python
# BEFORE
        if probs_arr.sum() <= 0:
            continue
        probs = normalize_probabilities(sir_probs)
# AFTER
        if probs_arr.sum() <= 0:
            continue
        probs = normalize_probabilities(sir_probs, fallback="raise")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_fallback_raise_callsites.py -v
```

Expected: 10 PASS.

- [ ] **Step 5: Run full test suite — confirm no regression**

```bash
pytest -x -q --tb=short
```

Expected: All collected (~973+) tests PASS. If a test relies on silent uniform fallback (unlikely but possible), inspect and fix the test, not the production code (the new behavior is intentional).

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_fallback_raise_callsites.py \
        clinosim/modules/hai/engine.py \
        clinosim/modules/population/engine.py \
        clinosim/modules/clinical_course/engine.py \
        clinosim/modules/hai/enricher.py
git commit -m "$(cat <<'EOF'
fix(validation): fallback="raise" sweep — 10 callsites

Apply normalize_probabilities(..., fallback="raise") to all remaining
YAML-sourced probability sampling callsites. Completes the F-A2 lesson
("same function → grep all callsites") from PR-A Fix #101 SIR sibling
incomplete fix.

Backward defense (3rd layer of silent-no-op defense triplet):

A1 hai/engine.py:85 — _sample_organism organism weights
A2 population/engine.py:170 — smoking_dist
A3 population/engine.py:180 — alcohol_dist
A4 population/engine.py:485 — surnames weights
A5 population/engine.py:509 — occupation working_age dist
A6 population/engine.py:517 — first_names weights
A7 population/engine.py:664 — cities weights
B1 clinical_course/engine.py:101 — archetype probs (intent marker)
B2 hai/enricher.py:152 — RNG mirror (intent marker, upstream guard kept)
B3 hai/enricher.py:225 — antibiogram SIR (intent marker, upstream guard kept)

No functional change — valid YAML inputs behave identically.
byte-diff invariant verified at PR-final gate.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MeWQ5LMK9a1LqLERxGMYk7
EOF
)"
```

---

## Task 2: `_validate_hai_organisms` + `load_hai_organisms` wiring

**Files:**
- Create: `tests/unit/test_yaml_loader_validation.py` (new file, will be appended in Tasks 3 + 4)
- Modify: `clinosim/modules/hai/engine.py` — add `_validate_hai_organisms` function + wire in `load_hai_organisms`

**Interfaces:**
- Consumes: `clinosim.modules.hai.HAI_TYPES` canonical tuple, `clinosim.codes.lookup` (for SNOMED non-empty contract)
- Produces: `_validate_hai_organisms(data: dict) -> None` raises `ValueError` on cross-reference violation. Public `load_hai_organisms()` signature unchanged.

- [ ] **Step 1: Create test file, write failing tests for `_validate_hai_organisms`**

`tests/unit/test_yaml_loader_validation.py`:

```python
"""Verify import-time YAML loader validation — _validate_* cross-references.

Mirrors clinosim/modules/observation/microbiology.py:_validate_microbiology
pattern. Each _validate_* raises ValueError on YAML editing accidents
(empty list / negative weight / unknown key / missing SNOMED etc.) so
the silent-no-op (PR-90 class bug) cannot slip through.
"""
from __future__ import annotations

import pytest


# =========================================================================
# Task 2: _validate_hai_organisms (hai/engine.py)
# =========================================================================

def test_validate_hai_organisms_passes_current_yaml():
    """Real production YAML must pass validation (positive baseline)."""
    from clinosim.modules.hai.engine import load_hai_organisms
    # Triggers _validate_hai_organisms on first call (via lru_cache loader).
    data = load_hai_organisms()
    assert "hai_organisms" in data


def test_validate_hai_organisms_rejects_non_dict():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    with pytest.raises(ValueError, match="must be a dict"):
        _validate_hai_organisms([])  # type: ignore[arg-type]


def test_validate_hai_organisms_rejects_unknown_hai_type():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": {"unknown_type": [{"snomed": "123", "weight": 0.5}]}}
    with pytest.raises(ValueError, match="unknown HAI type"):
        _validate_hai_organisms(bad)


def test_validate_hai_organisms_rejects_empty_organism_list():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": {"clabsi": []}}
    with pytest.raises(ValueError, match="empty organism list"):
        _validate_hai_organisms(bad)


def test_validate_hai_organisms_rejects_negative_weight():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": {"clabsi": [{"snomed": "123", "weight": -0.1}]}}
    with pytest.raises(ValueError, match="negative weight"):
        _validate_hai_organisms(bad)


def test_validate_hai_organisms_rejects_zero_sum_weights():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": {"clabsi": [{"snomed": "123", "weight": 0.0}]}}
    with pytest.raises(ValueError, match="zero-sum"):
        _validate_hai_organisms(bad)


def test_validate_hai_organisms_rejects_empty_snomed():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": {"clabsi": [{"snomed": "", "weight": 1.0}]}}
    with pytest.raises(ValueError, match="empty SNOMED"):
        _validate_hai_organisms(bad)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_yaml_loader_validation.py -v
```

Expected: 7 tests, 1 PASS (positive baseline — current YAML is already valid even without validator), 6 FAIL with `ImportError: cannot import _validate_hai_organisms`.

- [ ] **Step 3: Add `_validate_hai_organisms` to `clinosim/modules/hai/engine.py`**

Add the function just below `_load_yaml` (line ~27) and before the `@lru_cache` loaders. Then add a 1-line wire inside `load_hai_organisms`. Pattern mirrors `_validate_microbiology` in `clinosim/modules/observation/microbiology.py`.

```python
# AFTER the import block, before the @lru_cache loaders
# (insert at top-level of clinosim/modules/hai/engine.py)

from clinosim.modules.hai import HAI_TYPES  # add to imports if not present

def _validate_hai_organisms(data: dict) -> None:
    """Validate hai_organisms.yaml at load time — fail loud on cross-ref violations.

    Cross-references (silent-no-op risks) covered:
    1. top-level key 'hai_organisms' must exist and be a dict
    2. each hai_type ⊆ HAI_TYPES canonical set
    3. each organism list non-empty
    4. each weight numeric and >= 0
    5. each weight sum > 0 (zero-sum is the precondition that
       normalize_probabilities(fallback="raise") raises at runtime)
    6. each organism's snomed non-empty string
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"hai_organisms.yaml: top-level must be a dict, got {type(data).__name__}"
        )
    organisms_map = data.get("hai_organisms")
    if not isinstance(organisms_map, dict):
        raise ValueError(
            "hai_organisms.yaml: 'hai_organisms' must be a dict of "
            f"{{hai_type: [organisms]}}, got {type(organisms_map).__name__}"
        )
    valid_types = set(HAI_TYPES)
    for hai_type, organism_list in organisms_map.items():
        if hai_type not in valid_types:
            raise ValueError(
                f"hai_organisms.yaml: unknown HAI type {hai_type!r}; "
                f"expected one of {sorted(valid_types)}"
            )
        if not isinstance(organism_list, list) or not organism_list:
            raise ValueError(
                f"hai_organisms.yaml: hai_type {hai_type!r} has empty organism list"
            )
        weights: list[float] = []
        for entry in organism_list:
            if not isinstance(entry, dict):
                raise ValueError(
                    f"hai_organisms.yaml: {hai_type!r} entry must be a dict, "
                    f"got {entry!r}"
                )
            snomed = entry.get("snomed")
            if not isinstance(snomed, str) or not snomed:
                raise ValueError(
                    f"hai_organisms.yaml: {hai_type!r} entry has empty SNOMED "
                    f"{snomed!r}"
                )
            try:
                w = float(entry.get("weight", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"hai_organisms.yaml: {hai_type!r}/{snomed!r} weight "
                    f"non-numeric: {entry.get('weight')!r}"
                ) from exc
            if w < 0:
                raise ValueError(
                    f"hai_organisms.yaml: {hai_type!r}/{snomed!r} has negative "
                    f"weight {w}"
                )
            weights.append(w)
        if sum(weights) <= 0:
            raise ValueError(
                f"hai_organisms.yaml: {hai_type!r} has zero-sum weights {weights}"
            )
```

Then wire into the existing `load_hai_organisms`:

```python
# BEFORE
@lru_cache(maxsize=1)
def load_hai_organisms() -> dict[str, Any]:
    return _load_yaml("hai_organisms.yaml")

# AFTER
@lru_cache(maxsize=1)
def load_hai_organisms() -> dict[str, Any]:
    data = _load_yaml("hai_organisms.yaml")
    _validate_hai_organisms(data)
    return data
```

**Note on circular import**: `from clinosim.modules.hai import HAI_TYPES` may cause circular import if `hai/__init__.py` imports from `engine.py`. Check `hai/__init__.py` first; if it imports `engine` symbols (it does per PR-94 reorganization), define `HAI_TYPES` locally as a redundant tuple in `engine.py`'s validator scope and add an assertion at module load time that the two definitions match. Alternative: import inside `_validate_hai_organisms` function body (lazy import).

Prefer lazy import inside the function:

```python
def _validate_hai_organisms(data: dict) -> None:
    from clinosim.modules.hai import HAI_TYPES  # lazy import to avoid cycle
    ...
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_yaml_loader_validation.py -v
```

Expected: 7 PASS.

- [ ] **Step 5: Run full test suite — confirm no regression**

```bash
pytest -x -q --tb=short
```

Expected: All collected tests PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_yaml_loader_validation.py clinosim/modules/hai/engine.py
git commit -m "$(cat <<'EOF'
fix(validation): _validate_hai_organisms — upstream defense for hai_organisms.yaml

Add import-time validator for hai_organisms.yaml (HAI organism sampling
weights). Mirrors observation/microbiology._validate_microbiology pattern.

Catches at load time (before simulation starts):
- top-level key 'hai_organisms' shape
- each hai_type ⊆ HAI_TYPES canonical set
- empty organism list / non-empty SNOMED / non-negative weight / zero-sum

Combined with Task 1 fallback="raise" backward defense, this gives
hai/engine.py:_sample_organism the full silent-no-op defense triplet
(canonical constants + upstream validate + backward raise).

No functional change for valid YAML.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MeWQ5LMK9a1LqLERxGMYk7
EOF
)"
```

---

## Task 3: `_validate_demographics` + `_load_demographics_cached` wiring

**Files:**
- Modify: `tests/unit/test_yaml_loader_validation.py` (append)
- Modify: `clinosim/locale/loader.py` — add `_validate_demographics` function + wire in `_load_demographics_cached`

**Interfaces:**
- Consumes: locale demographics YAML structure (lifestyle_distribution.smoking / .alcohol per sex_key)
- Produces: `_validate_demographics(data: dict) -> None` raises `ValueError`. `load_demographics(country)` signature unchanged.

- [ ] **Step 1: Append failing tests to `tests/unit/test_yaml_loader_validation.py`**

Append to the existing test file:

```python
# =========================================================================
# Task 3: _validate_demographics (locale/loader.py)
# =========================================================================

def test_validate_demographics_passes_current_us_yaml():
    """Real US demographics YAML must pass validation."""
    from clinosim.locale.loader import load_demographics
    data = load_demographics("US")
    assert "_country" in data


def test_validate_demographics_passes_current_jp_yaml():
    from clinosim.locale.loader import load_demographics
    data = load_demographics("JP")
    assert "_country" in data


def test_validate_demographics_rejects_non_dict():
    from clinosim.locale.loader import _validate_demographics
    with pytest.raises(ValueError, match="must be a dict"):
        _validate_demographics([])  # type: ignore[arg-type]


def test_validate_demographics_rejects_zero_sum_smoking_dist():
    from clinosim.locale.loader import _validate_demographics
    bad = {
        "lifestyle_distribution": {
            "smoking": {"M": {"never": 0.0, "current": 0.0}}
        }
    }
    with pytest.raises(ValueError, match="zero-sum"):
        _validate_demographics(bad)


def test_validate_demographics_rejects_negative_alcohol_weight():
    from clinosim.locale.loader import _validate_demographics
    bad = {
        "lifestyle_distribution": {
            "alcohol": {"F": {"none": 0.5, "heavy": -0.1}}
        }
    }
    with pytest.raises(ValueError, match="negative weight"):
        _validate_demographics(bad)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_yaml_loader_validation.py::test_validate_demographics_rejects_non_dict -v \
       tests/unit/test_yaml_loader_validation.py::test_validate_demographics_rejects_zero_sum_smoking_dist -v \
       tests/unit/test_yaml_loader_validation.py::test_validate_demographics_rejects_negative_alcohol_weight -v
```

Expected: 3 FAIL with `ImportError: cannot import _validate_demographics`.

- [ ] **Step 3: Add `_validate_demographics` to `clinosim/locale/loader.py`**

Add the function near the top of `clinosim/locale/loader.py` (after `_country_dir`, before `load_names`). Then wire into `_load_demographics_cached`. Validation is **partial**: only the optional `lifestyle_distribution` block is checked because the loader has a non-empty `_FALLBACK_DEMOGRAPHICS` that does not include lifestyle keys (validator must tolerate the fallback path).

```python
def _validate_demographics(data: dict) -> None:
    """Validate demographics.yaml at load time — fail loud on weight violations.

    Checks the OPTIONAL lifestyle_distribution block (smoking + alcohol per sex_key).
    The fallback {_FALLBACK_DEMOGRAPHICS} has no lifestyle block, so a missing
    block is a valid state (skip). When the block IS present, validate that
    each distribution has only non-negative weights with sum > 0 — these are the
    preconditions for normalize_probabilities(..., fallback="raise") at the
    population/engine.py callsites.
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"demographics.yaml: top-level must be a dict, got {type(data).__name__}"
        )
    lifestyle = data.get("lifestyle_distribution")
    if lifestyle is None:
        return  # OK: optional block absent
    if not isinstance(lifestyle, dict):
        raise ValueError(
            f"demographics.yaml: lifestyle_distribution must be a dict, "
            f"got {type(lifestyle).__name__}"
        )
    for behavior in ("smoking", "alcohol"):
        per_sex = lifestyle.get(behavior)
        if per_sex is None:
            continue  # OK: behavior absent
        if not isinstance(per_sex, dict):
            raise ValueError(
                f"demographics.yaml: lifestyle_distribution.{behavior} must be "
                f"a dict, got {type(per_sex).__name__}"
            )
        for sex_key, dist in per_sex.items():
            if not isinstance(dist, dict):
                raise ValueError(
                    f"demographics.yaml: lifestyle_distribution.{behavior}."
                    f"{sex_key!r} must be a dict, got {type(dist).__name__}"
                )
            weights: list[float] = []
            for level, w in dist.items():
                try:
                    w_f = float(w)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"demographics.yaml: lifestyle_distribution.{behavior}."
                        f"{sex_key!r}.{level!r} weight non-numeric: {w!r}"
                    ) from exc
                if w_f < 0:
                    raise ValueError(
                        f"demographics.yaml: lifestyle_distribution.{behavior}."
                        f"{sex_key!r}.{level!r} has negative weight {w_f}"
                    )
                weights.append(w_f)
            if weights and sum(weights) <= 0:
                raise ValueError(
                    f"demographics.yaml: lifestyle_distribution.{behavior}."
                    f"{sex_key!r} has zero-sum weights {weights}"
                )
```

Wire into `_load_demographics_cached`:

```python
# BEFORE
@lru_cache(maxsize=8)
def _load_demographics_cached(country: str) -> dict[str, Any]:
    """Internal cached loader for raw demographics YAML (no mutation)."""
    return _load_yaml(_country_dir(country) / "demographics.yaml", fallback=_FALLBACK_DEMOGRAPHICS)

# AFTER
@lru_cache(maxsize=8)
def _load_demographics_cached(country: str) -> dict[str, Any]:
    """Internal cached loader for raw demographics YAML (no mutation)."""
    data = _load_yaml(_country_dir(country) / "demographics.yaml", fallback=_FALLBACK_DEMOGRAPHICS)
    _validate_demographics(data)
    return data
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_yaml_loader_validation.py -v
```

Expected: All tests PASS (Task 2's 7 + Task 3's 5 = 12 PASS).

- [ ] **Step 5: Run full test suite — confirm no regression**

```bash
pytest -x -q --tb=short
```

Expected: All collected tests PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_yaml_loader_validation.py clinosim/locale/loader.py
git commit -m "$(cat <<'EOF'
fix(validation): _validate_demographics — upstream defense for demographics.yaml

Add import-time validator for the optional lifestyle_distribution block
(smoking + alcohol per sex_key) in locale/{country}/demographics.yaml.
These are the source YAMLs for population/engine.py:170 and :180.

Catches at load time:
- shape of lifestyle_distribution.{smoking, alcohol}.<sex>
- non-negative weights
- non-zero-sum (precondition for fallback="raise")

The validator tolerates an absent lifestyle block (the _FALLBACK_DEMOGRAPHICS
has none) — only validates if the block is present.

No functional change for valid YAML.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MeWQ5LMK9a1LqLERxGMYk7
EOF
)"
```

---

## Task 4: `_validate_names` + `_validate_addresses` (batch)

**Files:**
- Modify: `tests/unit/test_yaml_loader_validation.py` (append)
- Modify: `clinosim/locale/loader.py` — add `_validate_names` and `_validate_addresses` functions + wire in `load_names` and `load_addresses`

**Interfaces:**
- Consumes: locale names YAML (surnames / given_names_male / given_names_female lists), locale addresses YAML (cities list)
- Produces: `_validate_names(data)` + `_validate_addresses(data)` both raise `ValueError`. Public `load_names` / `load_addresses` signatures unchanged.

- [ ] **Step 1: Append failing tests to `tests/unit/test_yaml_loader_validation.py`**

```python
# =========================================================================
# Task 4: _validate_names + _validate_addresses (locale/loader.py)
# =========================================================================

def test_validate_names_passes_current_us_yaml():
    from clinosim.locale.loader import load_names
    data = load_names("US")
    assert "surnames" in data


def test_validate_names_passes_current_jp_yaml():
    from clinosim.locale.loader import load_names
    data = load_names("JP")
    assert "surnames" in data


def test_validate_names_rejects_non_dict():
    from clinosim.locale.loader import _validate_names
    with pytest.raises(ValueError, match="must be a dict"):
        _validate_names([])  # type: ignore[arg-type]


def test_validate_names_rejects_zero_sum_surname_weights():
    from clinosim.locale.loader import _validate_names
    bad = {"surnames": [{"name": "A", "weight": 0}, {"name": "B", "weight": 0}]}
    with pytest.raises(ValueError, match="zero-sum"):
        _validate_names(bad)


def test_validate_names_rejects_negative_given_name_weight():
    from clinosim.locale.loader import _validate_names
    bad = {
        "surnames": [{"name": "OK", "weight": 1}],
        "given_names_male": [{"name": "Bad", "weight": -1}],
    }
    with pytest.raises(ValueError, match="negative weight"):
        _validate_names(bad)


def test_validate_addresses_passes_current_us_yaml():
    from clinosim.locale.loader import load_addresses
    data = load_addresses("US")
    assert "cities" in data


def test_validate_addresses_rejects_non_dict():
    from clinosim.locale.loader import _validate_addresses
    with pytest.raises(ValueError, match="must be a dict"):
        _validate_addresses([])  # type: ignore[arg-type]


def test_validate_addresses_rejects_zero_sum_city_weights():
    from clinosim.locale.loader import _validate_addresses
    bad = {"cities": [{"city": "A", "weight": 0}, {"city": "B", "weight": 0}]}
    with pytest.raises(ValueError, match="zero-sum"):
        _validate_addresses(bad)


def test_validate_addresses_rejects_negative_city_weight():
    from clinosim.locale.loader import _validate_addresses
    bad = {"cities": [{"city": "Bad", "weight": -1}]}
    with pytest.raises(ValueError, match="negative weight"):
        _validate_addresses(bad)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_yaml_loader_validation.py -v
```

Expected: Tasks 2 + 3 tests PASS, new Task 4 tests FAIL with `ImportError`.

- [ ] **Step 3: Add `_validate_names` and `_validate_addresses` to `clinosim/locale/loader.py`**

Place both functions next to `_validate_demographics` (top-level, before `load_*` definitions).

```python
def _validate_names(data: dict) -> None:
    """Validate names.yaml — surnames + given_names lists with non-negative weights.

    Tolerates the _FALLBACK_NAMES dict (which has small but valid weights).
    For each list present (surnames / given_names_male / given_names_female),
    requires each weight to be non-negative and the sum to be > 0 (precondition
    for normalize_probabilities(..., fallback="raise") in population/engine.py
    callsites 485 + 517).
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"names.yaml: top-level must be a dict, got {type(data).__name__}"
        )
    for key in ("surnames", "given_names_male", "given_names_female"):
        items = data.get(key)
        if items is None:
            continue  # OK: optional list absent (validator does not require all three)
        if not isinstance(items, list):
            raise ValueError(
                f"names.yaml: {key!r} must be a list, got {type(items).__name__}"
            )
        if not items:
            # Empty list is silently skipped at upstream (no zero-sum risk since
            # normalize_probabilities raises on empty array anyway). Accept here.
            continue
        weights: list[float] = []
        for entry in items:
            if not isinstance(entry, dict):
                raise ValueError(
                    f"names.yaml: {key!r} entry must be a dict, got {entry!r}"
                )
            try:
                w = float(entry.get("weight", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"names.yaml: {key!r}.{entry.get('name')!r} weight non-numeric: "
                    f"{entry.get('weight')!r}"
                ) from exc
            if w < 0:
                raise ValueError(
                    f"names.yaml: {key!r}.{entry.get('name')!r} has negative "
                    f"weight {w}"
                )
            weights.append(w)
        if weights and sum(weights) <= 0:
            raise ValueError(
                f"names.yaml: {key!r} has zero-sum weights"
            )


def _validate_addresses(data: dict) -> None:
    """Validate addresses.yaml — cities list with non-negative weights.

    Tolerates missing / empty cities (upstream `_generate_household_address`
    has a `if not cities: return` guard). When cities are present, requires
    non-negative weights with sum > 0 (precondition for
    normalize_probabilities(..., fallback="raise") at population/engine.py:664).
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"addresses.yaml: top-level must be a dict, got {type(data).__name__}"
        )
    cities = data.get("cities")
    if cities is None:
        return  # OK: empty fallback ({}) takes this path
    if not isinstance(cities, list):
        raise ValueError(
            f"addresses.yaml: 'cities' must be a list, got {type(cities).__name__}"
        )
    if not cities:
        return  # OK: empty list (upstream guards against use)
    weights: list[float] = []
    for entry in cities:
        if not isinstance(entry, dict):
            raise ValueError(
                f"addresses.yaml: cities entry must be a dict, got {entry!r}"
            )
        try:
            w = float(entry.get("weight", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"addresses.yaml: cities entry {entry.get('city')!r} weight "
                f"non-numeric: {entry.get('weight')!r}"
            ) from exc
        if w < 0:
            raise ValueError(
                f"addresses.yaml: cities entry {entry.get('city')!r} has negative "
                f"weight {w}"
            )
        weights.append(w)
    if sum(weights) <= 0:
        raise ValueError(
            f"addresses.yaml: cities has zero-sum weights"
        )
```

Wire into `load_names` and `load_addresses`:

```python
# BEFORE
@lru_cache(maxsize=16)
def load_names(country: str) -> dict[str, Any]:
    """Load person name data for a country."""
    return _load_yaml(_country_dir(country) / "names.yaml", fallback=_FALLBACK_NAMES)

# AFTER
@lru_cache(maxsize=16)
def load_names(country: str) -> dict[str, Any]:
    """Load person name data for a country."""
    data = _load_yaml(_country_dir(country) / "names.yaml", fallback=_FALLBACK_NAMES)
    _validate_names(data)
    return data


# BEFORE
@lru_cache(maxsize=8)
def load_addresses(country: str) -> dict[str, Any]:
    """Load address/phone data for a country."""
    return _load_yaml(_country_dir(country) / "addresses.yaml", fallback={})

# AFTER
@lru_cache(maxsize=8)
def load_addresses(country: str) -> dict[str, Any]:
    """Load address/phone data for a country."""
    data = _load_yaml(_country_dir(country) / "addresses.yaml", fallback={})
    _validate_addresses(data)
    return data
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_yaml_loader_validation.py -v
```

Expected: All tests PASS (~20 PASS total across Tasks 2 + 3 + 4).

- [ ] **Step 5: Run full test suite — confirm no regression**

```bash
pytest -x -q --tb=short
```

Expected: All collected tests PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_yaml_loader_validation.py clinosim/locale/loader.py
git commit -m "$(cat <<'EOF'
fix(validation): _validate_names + _validate_addresses — locale loader sweep

Add import-time validators for names.yaml and addresses.yaml. Both are
structurally similar (weighted entry lists), batched into a single commit.

names.yaml validation:
- surnames + given_names_male + given_names_female (each optional)
- non-negative weights, sum > 0 (precondition for population/engine.py:485, :517)
- tolerates _FALLBACK_NAMES

addresses.yaml validation:
- cities list (optional, has upstream guard)
- non-negative weights, sum > 0 (precondition for population/engine.py:664)
- tolerates empty fallback ({})

Completes the locale loader silent-no-op defense triplet.

No functional change for valid YAML.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MeWQ5LMK9a1LqLERxGMYk7
EOF
)"
```

---

## Task 5: Docs sync

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/CONTRIBUTING-modules.md`
- Modify: `clinosim/modules/hai/README.md`
- Modify: `clinosim/locale/README.md`
- Modify: `clinosim/modules/_shared.py` (docstring only)

**Interfaces:**
- Consumes: nothing
- Produces: docs encode the new 4-loader validator coverage + 10-callsite `fallback="raise"` completion

- [ ] **Step 1: Locate and update `CLAUDE.md` AD-55 silent-no-op defense section**

Open `CLAUDE.md` and find the "silent-no-op 防御 3 層" passage in the AD-55 enricher patterns section. Update to encode the new coverage:

Search for the line: `**★ silent-no-op 防御 3 層**(セッション19 = PR-A + Fix #100/#101 確立)`

Update the description (or the surrounding text) to add a new line noting 4-loader + 10-callsite completion. Suggested addition (verify exact context via Read first):

```
- **★ silent-no-op 防御 3 層**(セッション19 = PR-A + Fix #100/#101 + 本 PR 確立):(1) `_validate_X(data)` で YAML 全 cross-reference を import 時 raise(microbiology 7 checks + hai_organisms / demographics / names / addresses 4 loaders 完備)、(2) `normalize_probabilities(weights, fallback="raise")` で YAML-sourced 確率の zero-sum 検出(全 10 YAML-sourced callsites 完備)、(3) TEMPLATE `_validate` stub は `raise NotImplementedError` で copy-paste 時に必ず実装強制
```

- [ ] **Step 2: Update `docs/CONTRIBUTING-modules.md`**

Find the "Import-time canonical-constants validation" section. Add a line stating that 4 main YAML loaders now have `_validate_*` coverage. Verify exact location via Read first.

Suggested update text (verify location):

```
- **Import-time canonical-constants validation**(PR-A 2026-06-26、本 PR 2026-06-27 拡張)
  — any YAML data referencing external IDs (SNOMED / LOINC / antibiotic key / probability
  weights) MUST validate against the canonical set at load time and raise `ValueError`
  on unknown keys / zero-sum weights. Silent `dict.get(key)` fall-through is a PR-90 class
  silent-no-op risk. Precedents: `modules/hai/load_hai_antibiogram` (3-way validation),
  `modules/observation/microbiology._validate_microbiology` (PR-A added, 7 cross-refs),
  `modules/antibiotic/audit._validate_nhsn_resistance_bands`, **本 PR で
  `modules/hai/engine._validate_hai_organisms` + `locale/loader._validate_demographics`
  + `_validate_names` + `_validate_addresses` の 4 主要 loader を完備**。
```

- [ ] **Step 3: Update `clinosim/modules/hai/README.md`**

Add a section (or update the existing API section) noting `_validate_hai_organisms` cross-references:

```markdown
### `_validate_hai_organisms(data)` (本 PR 追加)

`load_hai_organisms()` の import 時 validation。`hai_organisms.yaml` の以下を catch:

- top-level key `hai_organisms` が dict
- 各 hai_type が `HAI_TYPES = ("clabsi", "cauti", "vap")` に属する
- 各 hai_type の organism list non-empty
- 各 entry の `snomed` が non-empty string
- 各 entry の `weight` が numeric かつ >= 0
- 各 hai_type の weight sum > 0(= `_sample_organism` の `normalize_probabilities(..., fallback="raise")` 前提条件)

silent-no-op 防御 3 層の上流(import-time)層。
```

- [ ] **Step 4: Update `clinosim/locale/README.md`**

Add a section noting the 3 new validators:

```markdown
### Import-time validators(本 PR 追加)

`locale/loader.py` の 3 loader に `_validate_*` を追加:

- **`_validate_demographics(data)`**: `lifestyle_distribution.{smoking, alcohol}.<sex>` の optional block を検証(本 block が存在する場合、各 weight が非負 + sum > 0)。`_FALLBACK_DEMOGRAPHICS` は lifestyle block を持たないため fallback path も valid。
- **`_validate_names(data)`**: optional `surnames` / `given_names_male` / `given_names_female` list の各 entry の `weight` が非負 + sum > 0(`_FALLBACK_NAMES` も valid)。
- **`_validate_addresses(data)`**: optional `cities` list の各 entry の `weight` が非負 + sum > 0(空 fallback `{}` も valid、上流 caller が空 list を guard)。

silent-no-op 防御 3 層の上流(import-time)層。後方層 = `population/engine.py` の `normalize_probabilities(..., fallback="raise")` (10 callsite)。
```

- [ ] **Step 5: Update `clinosim/modules/_shared.py` docstring**

Strengthen `normalize_probabilities` docstring to mark `fallback="raise"` as the standard for YAML-sourced callsites:

```python
def normalize_probabilities(
    probs: list[float] | np.ndarray,
    fallback: str = "uniform",
) -> np.ndarray:
    """Normalize a non-negative weight vector to sum to 1.0.

    Args:
        probs: array or list of non-negative weights.
        fallback: "uniform" (default) returns equal weight on non-positive sum;
            "raise" raises ValueError instead.

    **Conventions** (PR-A / Fix #100 / 本 PR 確立):
    - **YAML-sourced callsites MUST use `fallback="raise"`** so a YAML edit accident
      (e.g. all weights set to 0) is caught loudly at runtime instead of silently
      defaulting to uniform sampling (= PR-90 class silent-no-op). All 10 YAML-sourced
      callsites have been migrated as of 2026-06-27.
    - **Inline literal weight callsites MAY use `fallback="uniform"`** (the default)
      since literal weight lists cannot zero out via YAML editing.
    - Upstream validators (`_validate_microbiology`, `_validate_hai_organisms`,
      `_validate_demographics`, `_validate_names`, `_validate_addresses`) catch
      zero-sum at import time as an additional layer of defense.

    Returns:
        np.ndarray of dtype float64 summing to 1.0.

    Byte-clean migration property: for the typical pre-A3 pattern
    ``arr = np.asarray(probs, dtype=float); arr / arr.sum()`` (numpy
    float64 sum) this helper produces a byte-identical output, because
    ``float(np.float64)`` is bit-preserving for finite values, so the
    divisor bit pattern matches and the resulting float64 array matches.

    NOTE: this is NOT pure idempotency. An input that sums to ``0.9999...``
    in float64 (e.g. ``[0.27, 0.18, 0.16, 0.13, 0.10, 0.06, 0.10]``) is
    NOT returned unchanged; it is divided by ``0.9999...`` and gets a small
    perturbation (~1e-17 per element). The byte-clean property is symmetry
    with the pre-existing code, not identity on already-normalized arrays.

    Raises:
        ValueError: if the input is empty, if any weight is negative, or if the
            input sums to zero and ``fallback="raise"``.
    """
```

- [ ] **Step 6: Run full test suite — confirm no regression**

```bash
pytest -x -q --tb=short
```

Expected: All collected tests PASS (docs-only changes do not affect tests).

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md docs/CONTRIBUTING-modules.md \
        clinosim/modules/hai/README.md clinosim/locale/README.md \
        clinosim/modules/_shared.py
git commit -m "$(cat <<'EOF'
docs(validation): encode silent-no-op defense triplet completion

Document the 4-loader _validate_* + 10-callsite fallback="raise"
completion across:

- CLAUDE.md: AD-55 silent-no-op 3-layer triplet now references all loaders
- CONTRIBUTING-modules.md: Import-time canonical-constants validation expanded
- modules/hai/README.md: _validate_hai_organisms cross-references
- locale/README.md: _validate_demographics / _validate_names / _validate_addresses
- modules/_shared.py: normalize_probabilities docstring marks fallback="raise"
  as standard for YAML-sourced callsites

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MeWQ5LMK9a1LqLERxGMYk7
EOF
)"
```

---

## Task 6: Byte-diff Full gate + PR

**Files:**
- Scratchpad: `scratchpad/foundation_polish_byte_diff/{master,branch}/{us,jp}/`

**Interfaces:**
- Consumes: nothing
- Produces: 78/78 NDJSON sha256 IDENTICAL evidence + PR opened

- [ ] **Step 1: Generate master baseline data**

```bash
mkdir -p scratchpad/foundation_polish_byte_diff/{master,branch}/{us,jp}
git worktree add /tmp/clinosim-master-foundation-polish master
cd /tmp/clinosim-master-foundation-polish
python -m clinosim generate --country US --population 10000 --seed 42 \
       --output-dir /Users/tokuyama/workspace/clinosim/scratchpad/foundation_polish_byte_diff/master/us \
       --format fhir
python -m clinosim generate --country JP --population 5000 --seed 42 \
       --output-dir /Users/tokuyama/workspace/clinosim/scratchpad/foundation_polish_byte_diff/master/jp \
       --format fhir
cd /Users/tokuyama/workspace/clinosim
git worktree remove /tmp/clinosim-master-foundation-polish
```

If `--format fhir` or `--output-dir` are not the exact CLI flags, run `python -m clinosim generate --help` and adjust. Expected runtime: ~10-20 min per country.

- [ ] **Step 2: Generate branch data (current branch)**

```bash
python -m clinosim generate --country US --population 10000 --seed 42 \
       --output-dir scratchpad/foundation_polish_byte_diff/branch/us \
       --format fhir
python -m clinosim generate --country JP --population 5000 --seed 42 \
       --output-dir scratchpad/foundation_polish_byte_diff/branch/jp \
       --format fhir
```

- [ ] **Step 3: Compute sha256 and compare**

```bash
python <<'EOF'
import hashlib
import pathlib
import sys

base = pathlib.Path("scratchpad/foundation_polish_byte_diff")
master_us = base / "master" / "us"
branch_us = base / "branch" / "us"
master_jp = base / "master" / "jp"
branch_jp = base / "branch" / "jp"

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

total = 0
mismatched = []
for m_dir, b_dir in [(master_us, branch_us), (master_jp, branch_jp)]:
    for f in sorted(m_dir.rglob("*.ndjson")):
        rel = f.relative_to(m_dir)
        b_file = b_dir / rel
        if not b_file.exists():
            mismatched.append(f"MISSING in branch: {rel}")
            continue
        total += 1
        if sha(f) != sha(b_file):
            mismatched.append(f"DIFFER: {m_dir.name}/{rel}")

print(f"Compared: {total} NDJSON files")
print(f"Mismatched: {len(mismatched)}")
for m in mismatched:
    print(f"  {m}")
sys.exit(0 if not mismatched else 1)
EOF
```

Expected: `Compared: 78 NDJSON files / Mismatched: 0`. If any mismatch, **STOP**: the refactor has introduced a behavioral change. Investigate the diff and fix before continuing.

- [ ] **Step 4: Save byte-diff evidence**

```bash
cat > scratchpad/foundation_polish_byte_diff/RESULT.md <<'EOF'
# Foundation polish byte-diff invariant — RESULT

Generated 2026-06-27.
Seed: 42
Population: US 10000 + JP 5000
NDJSON files compared: 78
Mismatched: 0

All 39 US + 39 JP NDJSON files are sha256-identical between master and
`feat/foundation-polish-validation-sweep` branch.

byte-diff invariant CONFIRMED — refactor is functionally inert.
EOF
```

- [ ] **Step 5: Push branch + open PR**

```bash
git push -u origin feat/foundation-polish-validation-sweep
gh pr create --title 'fix(validation): fallback="raise" sweep + 4 YAML loader _validate_*' \
  --body "$(cat <<'EOF'
## Summary

Foundation polish 完成 PR(その 1)。PR-A → Fix #100 → Fix #101 で確立した
**silent-no-op 防御 3 層**(`_validate_*` 上流 / `fallback="raise"` 後方 /
canonical constants)を hai / population / locale で全面完成。

### 後方防御(commit 1)
10 callsites を `fallback="raise"` 化:

- A1: `hai/engine.py:85` `_sample_organism`
- A2-A7: `population/engine.py:170, 180, 485, 509, 517, 664`
- B1: `clinical_course/engine.py:101`(意図明示)
- B2-B3: `hai/enricher.py:152, 225`(意図明示、PR-95 RNG mirror upstream guard 温存)

### 上流防御(commits 2-4)
4 主要 YAML loader に `_validate_*` を追加:

- `_validate_hai_organisms`(`hai/engine.py`)
- `_validate_demographics`(`locale/loader.py`)
- `_validate_names`(`locale/loader.py`)
- `_validate_addresses`(`locale/loader.py`)

`_validate_microbiology`(PR-A Fix #100/#101 で確立)と同型 pattern。

### Docs sync(commit 5)
CLAUDE.md / CONTRIBUTING-modules.md / hai/README / locale/README /
_shared.py docstring に新 coverage を反映。

## Test plan

- [x] `tests/unit/test_fallback_raise_callsites.py` (新規、10 件) PASS
- [x] `tests/unit/test_yaml_loader_validation.py` (新規、~20 件) PASS
- [x] `pytest -x` 既存全緑(unit 695+ / integration 139+ / e2e 39)
- [x] byte-diff Full(US p=10000 + JP p=5000、seed=42) **78/78 NDJSON sha256 IDENTICAL**

byte-diff evidence: `scratchpad/foundation_polish_byte_diff/RESULT.md`

## Adversarial review 戦略(merge 後)

memory `feedback_iterative_adversarial_review` に従い 4-agent fan-out:
- (a) 同関数内 sibling callsite 漏れ(F-A2 incomplete 教訓)
- (b) test coverage gap(positive / negative 対称性)
- (c) PR-95 RNG mirror sequence 副作用
- (d) docs accuracy

Stopping criteria: Critical/Important 0 + finding converging + 残 cosmetic only + 次段 expected size tiny。

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MeWQ5LMK9a1LqLERxGMYk7
EOF
)"
```

- [ ] **Step 6: Cleanup scratchpad after PR opened**

```bash
rm -rf scratchpad/foundation_polish_byte_diff
```

---

## Acceptance criteria

- [ ] 10 callsites all carry `fallback="raise"`
- [ ] 4 loaders all wire `_validate_*`
- [ ] `tests/unit/test_fallback_raise_callsites.py` — 10 ValueError-triggering tests pass
- [ ] `tests/unit/test_yaml_loader_validation.py` — 4 loaders × ~5 negative tests + positive baseline tests pass
- [ ] `pytest -x` — all collected tests pass (~975+)
- [ ] byte-diff Full (US p=10000 + JP p=5000, seed=42) — 78/78 NDJSON sha256 IDENTICAL
- [ ] docs sync — 5 files updated
- [ ] PR opened with body containing byte-diff result + adversarial fan-out strategy

---

## Notes for execution

- **Circular import risk(Task 2 Step 3)**: `_validate_hai_organisms` uses lazy import of `HAI_TYPES` inside the function body (`from clinosim.modules.hai import HAI_TYPES`). If module load order makes even lazy import fail, define `_HAI_TYPES_LOCAL = ("clabsi", "cauti", "vap")` at module top of `engine.py` and add an assertion `assert set(_HAI_TYPES_LOCAL) == set(HAI_TYPES)` inside the validator after the lazy import.
- **B1 fallback="raise" is intent-marking only**: `clinical_course/engine.py:101` uses `max(0.001, ...)` so the precondition for raise is unreachable. The change is for "grep-uniformity" with other callsites and to encode intent for future readers.
- **B2/B3 upstream guard temon**: do NOT delete the upstream `if ... sum() > 0:` / `if probs_arr.sum() <= 0: continue` guards. They are load-bearing for PR-95 AD-16 RNG mirror exact sequence; the new `fallback="raise"` is purely additive intent-marking.
- **`_validate_demographics` tolerates missing block**: `_FALLBACK_DEMOGRAPHICS` has no `lifestyle_distribution`, so the validator must skip when the block is absent. Same for `_validate_addresses` (fallback `{}`).
- **byte-diff exact CLI flags**: verify `python -m clinosim generate --help` for the exact `--output-dir` / `--format` / `--population` flag names. The plan uses likely names but the project may use slightly different ones.
- **Each commit is independently byte-diff-clean**: after Task 1, Task 2, Task 3, Task 4 commits, a quick `pytest -x` is sufficient. The final Full byte-diff at Task 6 is the load-bearing gate.
