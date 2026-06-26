# PR-A: Module unification quick wins — design spec

**Date**: 2026-06-26 (session 19)
**Scope**: First of 4 PR series addressing post-PR3b-2 cross-module audit findings.
**Status**: design approved, awaiting plan
**Base**: master HEAD `1e057bbf5` (post PR #96/#97/#98)

---

## 1. Goal & scope

Four parallel `Explore` agents audited all 27 modules under `clinosim/modules/`
for unified patterns along 4 axes:

- Data reference (YAML loaders, path constants, cache, locale signatures)
- Data generation (enricher pattern, RNG sub-seed, sampling primitives, output destination)
- Code mapping (`clinosim.codes` API adherence, locale code mapping, source citations)
- Multilingual display (CIF AD-30, JP dictionaries, FHIR localization, US English enforcement)

PR-A addresses the 5 findings with the highest impact-to-difficulty ratio
that are independent enough to ship in a single atomic PR:

1. **A1** — Path constant naming standardization (12 modules)
2. **A2** — `lru_cache` `maxsize` convention (12 modules)
3. **A3** — Shared `normalize_probabilities()` helper + migrate all `rng.choice(p=)` callsites (load-bearing silent-bug defense)
4. **A4** — `observation/microbiology.py` silent skip → `ValueError` + import-time
   validation (orphan-bug defense)
5. **A5** — `Trimethoprim` naming canonicalization (slash form across all data)

The remaining 12+ findings (global `_cache` → `@lru_cache`, 15 empty `__init__.py`,
enricher `enabled` gate, Pydantic validation, coverage tests, cosmetic) are
deferred to PR-B/C/D in this series.

## 2. Non-goals (explicit)

- No semantic behavior change for in-scope modules (refactor mechanics).
- No new module added, no module renamed.
- No FHIR output format change.
- No Pydantic schema introduction (PR-C).
- No `__init__.py` `__all__` export changes (PR-B).
- No design-guide refinement (PR-D).
- No NHSN PDF source verification (long-standing TODO).

## 3. Each fix in detail

### 3.1 A1 — Path constant naming standardization

**Current state** (audit-confirmed, 5 distinct naming patterns):

| Pattern | Modules using it |
|---|---|
| `_REFERENCE_DATA_DIR = Path(__file__).parent / "reference_data"` | `disease/protocol.py:12`, `encounter/protocol.py:11` |
| `_HERE = Path(__file__).resolve().parent` + `_LOCALE = _HERE.parents[1] / "locale"` | `code_status`, `care_level`, `family_history`, `sdoh` |
| `_DATA = Path(__file__).parent / "reference_data" / "X.yaml"` (file path) | `hai/engine.py:20`, `observation/nursing.py:14` |
| `_HAI_REF_DIR`, `_DEVICES_YAML`, `_HAI_ANTIBIOGRAM_PATH` (explicit per-file) | `hai/__init__.py`, `device/engine.py`, etc. |
| Inline `Path(__file__).parent / "reference_data" / "X.yaml"` (no constant) | `observation/engine.py:15-16`, others |

**Target state**:

```python
# Module top, after imports:
_HERE = Path(__file__).resolve().parent

# If module has reference_data/:
_REF_DIR = _HERE / "reference_data"

# If module loads from clinosim/locale/:
_LOCALE = _HERE.parents[1] / "locale"
```

**File-specific paths** stay literal at the load site:

```python
@lru_cache(maxsize=1)
def load_X() -> dict:
    with open(_REF_DIR / "x.yaml") as f:
        return yaml.safe_load(f) or {}
```

**Special fix**: `immunization/engine.py` uses `.parents[2]` (accidentally
correct due to symmetry). Convert to `_HERE.parents[1] / "locale"` for
uniformity.

**Modules affected** (12): `code_status`, `care_level`, `family_history`,
`sdoh`, `immunization`, `device`, `hai`, `observation/nursing.py`,
`observation/microbiology.py`, `observation/engine.py`, `disease/protocol.py`,
`encounter/protocol.py`.

**Byte-diff invariant**: pure refactor of how paths are computed. The
actual file paths resolved at runtime are unchanged. Output unchanged.

### 3.2 A2 — `lru_cache` `maxsize` standardization

**Convention** (codified in design guide as part of PR-D, applied as code change here):

| Loader signature | `maxsize` |
|---|---|
| `load_X() -> dict` (no parameters) | `1` |
| `load_X(country: str) -> dict` | `2` (US + JP — the only countries currently supported) |
| `load_X(country: str, language: str = "en")` | `4` (if/when multilingual loaders arrive — currently NONE) |

**Current divergence**:

- `code_status/engine.py` second loader uses `maxsize=4` — drop to `2`.
- `immunization/engine.py` uses `maxsize=4` — drop to `2`.
- `family_history/engine.py` second loader uses `maxsize=4` — drop to `2`.
- All `maxsize=1` and `maxsize=2` already-aligned loaders unchanged.

**Modules affected** (3 sub-loaders).

**Byte-diff invariant**: `maxsize` only affects cache eviction policy. With
JP-only or US-only test runs, only 1 entry ever enters the cache, so reducing
`maxsize` from 4 to 2 is invisible. Output unchanged.

### 3.3 A3 — `normalize_probabilities()` shared helper + migrate `rng.choice(p=)` callsites

**The silent bug** (audit-confirmed):

`clinosim/modules/code_status/engine.py:48` calls `rng.choice(len(tiers), p=weights)`
without normalizing `weights`. `numpy.random.Generator.choice()` does NOT
auto-normalize; it raises `ValueError` if `p` doesn't sum to ~1.0
(tolerance ~`1e-8`). The call currently works because the YAML
`code_status_rates.yaml` is hand-normalized to sum to exactly 1.0. A YAML
edit that breaks the sum is a silent failure waiting to happen.

**Audit-found normalization patterns** (5 different forms):

| Pattern | Modules |
|---|---|
| `probs / probs.sum()` (numpy) | `care_level`, `observation/microbiology`, `hai` |
| `[w/total for w in weights]` (list comp) | `population`, `clinical_course` |
| `if sum > 0: probs /= sum` (conditional) | `care_level`, `hai` |
| **No normalization** | **`code_status`** (silent-bug) |
| `total = sum(...); [x/total for x in ...]` | `clinical_course`, `diagnosis` |

**New helper** in `clinosim/modules/_shared.py`:

```python
import numpy as np

def normalize_probabilities(
    probs: list[float] | np.ndarray,
    fallback: str = "uniform",
) -> np.ndarray:
    """Normalize probabilities to sum to 1.0 with safety checks.

    Args:
        probs: array or list of non-negative weights.
        fallback: "uniform" → equal weight on non-positive sum; "raise" → ValueError.

    Returns:
        np.ndarray of dtype float64 summing to 1.0.

    Idempotency: if the input already sums to 1.0 (within float tolerance),
    the output is byte-identical to `np.asarray(probs, dtype=float)`.
    This makes migrating from no-op normalization to this helper safe
    at byte-diff time for any data that was previously hand-normalized.
    """
    arr = np.asarray(probs, dtype=float)
    if (arr < 0).any():
        raise ValueError(f"normalize_probabilities: negative weight in {probs}")
    total = arr.sum()
    if total <= 0:
        if fallback == "uniform":
            n = max(len(arr), 1)
            return np.ones(n) / n
        raise ValueError(f"normalize_probabilities: non-positive sum in {probs}")
    return arr / total
```

**Migration**: every `rng.choice(..., p=X)` callsite wrapped by
`normalize_probabilities(X)` UNLESS `X` is provably already normalized AND
the migration would change byte-output. Spec rule: when in doubt, wrap; the
helper is idempotent on already-normalized input.

**Specific callsites to update**:

- `modules/code_status/engine.py:48` (silent bug → defended)
- `modules/care_level/engine.py:50` (already `probs/probs.sum()`, replace for uniformity)
- `modules/family_history/engine.py:~80` (audit-mentioned)
- `modules/observation/microbiology.py:92-94` (replace with helper)
- `modules/hai/engine.py:~84` (replace with helper)
- `modules/hai/enricher.py:218-220` (susceptibility sampling, replace)
- `modules/antibiotic/audit.py:_antibiogram_firing_proof_checks` (cefazolin probe — already normalized)
- `modules/population/engine.py` (multiple `[w/total for w]` patterns)
- `modules/clinical_course/engine.py` (multiple)
- `modules/diagnosis/engine.py` (differentials sampling)

**Byte-diff invariant**: helper is idempotent on already-normalized arrays.
All current YAML data is hand-normalized (verified during audit). Therefore
migration is byte-clean.

### 3.4 A4 — `observation/microbiology.py` silent skip → `ValueError` + import-time validation

**Current bug** (audit-confirmed at `modules/observation/microbiology.py:88-98`):

```python
for abx_key, sir in (org.get("antibiogram") or {}).items():
    loinc = antibiotics.get(abx_key)
    if not loinc:
        continue  # ← SILENT SKIP — no error, no log
```

**Risk**: a typo in an organism's `antibiogram` entry (e.g., `vancomicin`
instead of `vancomycin`) makes the susceptibility silently vanish at runtime.
No test catches it. Same class as PR-90 silent no-op.

**Two-part fix**:

**Part A**: replace silent skip with explicit `ValueError`:

```python
loinc = antibiotics.get(abx_key)
if not loinc:
    raise ValueError(
        f"microbiology.yaml: organism {org_id!r} antibiogram references "
        f"unknown antibiotic key {abx_key!r}; expected one of "
        f"{sorted(antibiotics.keys())}"
    )
```

**Part B**: hoist validation to import time. Add a `_validate_microbiology()`
function called from `_load()` that walks all `(disease, culture, organism)`
triples and verifies every `antibiogram` key exists in `antibiotics`. Same
pattern as `load_hai_antibiogram()`.

**New test**: `tests/unit/observation/test_microbiology_validation.py` adds
a `monkeypatch`-driven test that injects a typo'd antibiogram and asserts
`ValueError` is raised at load time.

**Byte-diff invariant**: current `microbiology.yaml` has no typos (audit
verified). Loud-fail behavior only triggers on broken YAML. Output
unchanged for healthy YAML.

### 3.5 A5 — `Trimethoprim` naming canonicalization

**Current inconsistency** (audit-confirmed):

| Location | Form |
|---|---|
| `disease/urinary_tract_infection.yaml` | `Trimethoprim/Sulfamethoxazole` (slash) |
| `disease/cellulitis.yaml` | `Trimethoprim/Sulfamethoxazole` (slash) |
| `antibiotic/__init__.py:ANTIBIOTIC_DRUGS` | `Trimethoprim/Sulfamethoxazole` (slash) |
| **`encounter/uti_uncomplicated.yaml`** | `Trimethoprim-sulfamethoxazole` (hyphen) — **outlier** |
| `locale/shared/drug_names_ja.yaml` | BOTH forms mapped (hyphen as legacy alias) |

**Fix**: change `encounter/uti_uncomplicated.yaml` to `Trimethoprim/Sulfamethoxazole`.
Leave `drug_names_ja.yaml` hyphen alias as harmless redundancy (a separate
PR can clean it up alongside other JP-name housekeeping).

**Byte-diff invariant**: JP output already resolves both forms to the same
display via dual-key mapping in `drug_names_ja.yaml`. Slash form is the
canonical form per existing module code. Output unchanged.

## 4. Verification gates

Refactor PR mechanic per memory `feedback_pr_merge_dqr_required`:

1. `pytest -m unit -m integration -m e2e` all green
2. `mypy clinosim/` strict clean
3. `ruff check clinosim/ tests/` clean
4. **Byte-diff vs master `1e057bbf5`** at `p=2000` US + `p=2000` JP, `seed=42`:
   - **ALL NDJSON byte-identical**
   - CIF JSON byte-identical
   - CSV byte-identical
   - This is the load-bearing gate for A3 (helper idempotency proof).
   - If any output differs, that is a bug to fix before merge.
5. `clinosim audit run -p 2000 --seed 42` → 4 axes PASS
6. New unit test for `normalize_probabilities()` covers:
   - Already-normalized input is byte-identical to plain `np.asarray`
   - Non-normalized input is normalized
   - Zero-sum input → uniform fallback
   - Zero-sum input + `fallback="raise"` → `ValueError`
   - Negative weight → `ValueError`
7. New unit test for `observation/microbiology.py` import-time validation:
   - Healthy YAML loads
   - Typo'd antibiogram entry raises `ValueError`

## 5. Commit strategy

5 themed commits for clean attribution:

1. **commit 1** — A1: path constant standardization (12 modules)
2. **commit 2** — A2: `lru_cache` `maxsize` standardization (3 sub-loaders)
3. **commit 3** — A3: `normalize_probabilities()` helper + migrate ~10
   `rng.choice(p=)` callsites
4. **commit 4** — A4: `observation/microbiology.py` `ValueError` + import-time
   validation + new test
5. **commit 5** — A5: `Trimethoprim` slash normalization in
   `encounter/uti_uncomplicated.yaml`

Each commit applies the Co-Authored-By + Claude-Session trailer.

## 6. Forward-compat

PR-A intentionally lays groundwork for PR-B/C/D in this series:

- A1 path-constant convention will be encoded as a rule in PR-D's design guide
  refinement.
- A3 helper will be the recommended pattern for any future RNG-sampling
  module documented in PR-D.
- A4 validation pattern (import-time loud-fail) will be promoted to a
  contributor-guide rule in PR-D.

## 7. Risks

- **Byte-diff invariant breach risk on A3**: if any YAML is *not* already
  hand-normalized, the helper's normalization will change the output. Verify
  byte-diff at p=2000 before merging. If a violation surfaces, isolate the
  module (revert that callsite migration) and document the gap as a
  PR-3rd-deliverable.
- **`microbiology.yaml` validation tightening**: if the YAML currently has
  a silent typo we never noticed, A4 will make import fail. Run the loader
  once locally before committing A4 to confirm.

## 8. Memory anchors applied

- `feedback_xhigh_review_lessons` — A3 helper + A4 import-time validation
  close two PR-90-class silent-no-op gaps.
- `feedback_propose_improvements_to_existing` — observation/microbiology
  silent skip discovered during audit, folded in here (same orphan-fix
  pattern as PR-93 Vancomycin RxNorm 11124 / PR #96 Cipro LOINC 18879-7).
- `feedback_pr_merge_dqr_required` — refactor PR mechanic: byte-diff as the
  primary verification gate.
- `feedback_iterative_adversarial_review` — PR-A will get post-merge
  adversarial review fan-out (scope ~3-5 agents matching the 5 themed
  commits).
