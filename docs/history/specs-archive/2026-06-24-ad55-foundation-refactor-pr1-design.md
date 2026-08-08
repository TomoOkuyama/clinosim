# AD-55 Module Foundation Refactor — PR1 (G1 Structural DRY)

**Date**: 2026-06-24
**Author**: Tomo Okuyama (with Claude Opus 4.7)
**Status**: APPROVED — ready for plan
**Series context**: 1 of 4 refactor PRs preparing clean foundation for device + HAI modules (the chosen first AD-55 Module from brainstorming session 13).
**Successors**: PR2 (G2 SDOH integrity) → PR3 (G3 _fhir_observations split) → PR4 (G4 doctrine docs) → then device + HAI feature PRs.

---

## 1. Motivation

The 7 completed AD-55 Base modules (identity / immunization / family_history / code_status / care_level + microbiology + nursing) established a strong shared pattern (`engine.py` + `enricher.py` + `reference_data/` + AD-56 enricher registration + per-person sub-seed). But repeated additions surfaced **8 structural-quality issues** that should be cleared before adding device + HAI (which will further multiply enricher count and cross-module composition).

The 8 issues group naturally:

| Group | Items | This PR |
|---|---|---|
| **G1 structural DRY** | (1) `_get()` 4-way duplication / (2) sub-seed offset convention + decentralization / (4) `care_level.load_rates()` locale signature inconsistency | **YES** |
| G2 SDOH integrity | (3) SDOH SNOMED hardcoded / (5) smoking + alcohol + care_level mixed in _fhir_sdoh.py | PR2 |
| G3 builder file scale | (7) _fhir_observations.py 31KB (immunization-inlined) | PR3 |
| G4 doctrine docs | (6) identity enabled gate complexity / (8) typed-field vs extensions decision tree | PR4 |

**G1 is the foundation set** — it touches every enricher module's local plumbing and locks in conventions that PR2-4 and later device + HAI will follow. Doing G1 first means PR2-4 (and beyond) inherit the cleaner pattern with no rework.

### Hard guarantee

**byte-identical output** (all 11 NDJSON files sha256-identical at US/JP p=2000 seed=42 vs master `dcb47ccc`). G1 is pure mechanical refactor with no behavior change.

---

## 2. Architecture

```
                  AD-55 enricher modules (4)
       immunization / code_status / family_history / care_level
                              ↓
        (currently: each module defines _get() locally,
         each module hardcodes its sub-seed offset locally,
         care_level alone hardcodes "jp" path literal)
                              ↓
                         G1 refactor
                              ↓
    +----------------------------------------------------+
    | clinosim/modules/_shared.py                        |
    |   get_attr_or_key(obj, name, default)              |  (4 modules import)
    +----------------------------------------------------+
    | clinosim/simulator/seeding.py                      |
    |   ENRICHER_SEED_OFFSETS = {                        |
    |     "identity":       540_054,  # grandfathered    |
    |     "immunization":   0x494D,                       |
    |     "code_status":    0x4353,                       |
    |     "family_history": 0x4648,                       |
    |     "care_level":     0x434C,                       |
    |   }                                                |  (5 modules import)
    +----------------------------------------------------+
    | clinosim/modules/care_level/engine.py              |
    |   load_rates(country: str = "JP")                  |  (signature unified)
    +----------------------------------------------------+
```

**Invariants**:
- **Behavior unchanged**: same `_get` semantics (`as _get` alias preserves local symbol), same seed values (numerical identity), same care_level output for both US (no-op) and JP (load JP YAML).
- **AD-16 preserved**: all sub-seed values identical → same `derive_sub_seed(master, offset, key)` outputs → same per-person/encounter RNG draws.
- **AD-56 preserved**: enricher registry order, sub-seed pattern, post_records hook all unchanged.

---

## 3. Component 1: `clinosim/modules/_shared.py`

New file:

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
    or if ``obj`` is None.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
```

**Note added vs current 4 duplicate definitions**: explicit `None` handling. All 4 current call sites already guard with chained `_get(_get(ctx, "config"), ...)` patterns that depend on the inner call returning `None` cleanly when `ctx.config` is `None`. The added `None` guard makes this implicit-but-essential property explicit (defensive consolidation; behavior at runtime is identical because callers already short-circuit before passing `None` to the inner `getattr`).

### Migration in 4 modules

```python
# immunization/enricher.py, code_status/enricher.py,
# family_history/enricher.py, care_level/enricher.py

# REMOVE
def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)

# ADD (top of file, with other imports)
from clinosim.modules._shared import get_attr_or_key as _get
```

The `as _get` alias keeps every call site unchanged. The diff is purely: 4× `def _get` removed (5 lines each = 20 lines) + 4× one import line added (4 lines) = **-16 lines net**.

---

## 4. Component 2: `ENRICHER_SEED_OFFSETS` central registry

Edit `clinosim/simulator/seeding.py` — add at module level (after existing helpers):

```python
# AD-55 Module enricher sub-seed offsets.
#
# Convention (PR1 2026-06-24): new modules MUST use a 16-bit hex ASCII
# offset (2 letters), e.g. 0x4944 = "ID". Identity (540_054) is
# grandfathered at its legacy decimal value to preserve byte-identical
# JP identity / Coverage output. Future device + HAI modules will follow
# the hex-ASCII convention (e.g., device = 0x4456 "DV", hai = 0x4841 "HA").
#
# All values must be unique — duplicates would silently collide two
# modules' RNG streams. The assert below catches accidental clashes at
# import time.
ENRICHER_SEED_OFFSETS = {
    "identity":       540_054,    # legacy decimal (grandfathered)
    "immunization":   0x494D,     # "IM"
    "code_status":    0x4353,     # "CS"
    "family_history": 0x4648,     # "FH"
    "care_level":     0x434C,     # "CL"
}

assert len(set(ENRICHER_SEED_OFFSETS.values())) == len(ENRICHER_SEED_OFFSETS), \
    f"ENRICHER_SEED_OFFSETS contains duplicate values: {ENRICHER_SEED_OFFSETS!r}"
```

### Migration in 5 modules

For each of `identity/assign.py`, `immunization/enricher.py`, `code_status/enricher.py`, `family_history/enricher.py`, `care_level/enricher.py`:

```python
# REMOVE
_XXX_SEED_OFFSET = <value>

# ADD (top of file)
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS

# Each existing use:  derive_sub_seed(master_seed, _XXX_SEED_OFFSET, ...)
# becomes:           derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["xxx"], ...)
```

Identity's `master_seed + _IDENTITY_SEED_OFFSET` (it doesn't use `derive_sub_seed`) becomes `master_seed + ENRICHER_SEED_OFFSETS["identity"]` — same numerical addition, byte-identical output.

---

## 5. Component 3: `care_level.load_rates(country)` signature

Edit `clinosim/modules/care_level/engine.py`:

```python
# BEFORE
def load_rates() -> dict:
    with open(_LOCALE / "jp" / "care_level_rates.yaml") as f:
        return yaml.safe_load(f)

# AFTER
from functools import lru_cache

@lru_cache(maxsize=None)
def load_rates(country: str = "JP") -> dict:
    """Load care-level rates for ``country``. Returns ``{}`` for non-JP
    (no-op path) — care_level is currently JP-only, but the signature
    matches immunization/family_history/code_status so future locale
    additions slot in without API churn."""
    if str(country).upper() != "JP":
        return {}
    with open(_LOCALE / "jp" / "care_level_rates.yaml") as f:
        return yaml.safe_load(f)
```

The single existing caller (`assign_care_level`) already short-circuits on non-JP (line 36 `if str(country).upper() != "JP": return ""`), so `load_rates` is only invoked with `country == "JP"` in practice. The signature change + non-JP early-return adds capability without changing existing behavior.

The default `"JP"` keeps any unexpected call site (e.g., tests calling `load_rates()` with no args) behaving as before.

The `@lru_cache(maxsize=None)` brings care_level in line with immunization / family_history / code_status (which all cache locale loads). Tiny perf improvement; primary motive is consistency.

---

## 6. Component 4a: CLAUDE.md convention documentation

Add new sub-section under "Architecture rules" → "EHR data enrichment" (as standalone "AD-55 enricher patterns" subsection):

```markdown
### AD-55 enricher patterns (PR1 foundation refactor, 2026-06-24)

- **Sub-seed offset convention** — new enricher modules MUST register
  their sub-seed in `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS`
  with a 16-bit hex-ASCII offset (e.g. `0x4944` = "ID", `0x4841` = "HA").
  Identity (decimal 540_054) is grandfathered to preserve byte-identical
  JP identifier output. The dict has a sanity assert that catches accidental
  duplicates at import. Modules import via
  `from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS` and use
  `derive_sub_seed(master, ENRICHER_SEED_OFFSETS["my_module"], key)`.
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

## 6b. Component 4b: `docs/CONTRIBUTING-modules.md` logic design guide extension

The existing `docs/CONTRIBUTING-modules.md` (311 lines) is the project's authoritative module-author playbook. PR1 extends it with the same three conventions so future contributors (and future-Claude sessions) follow them by default.

### Edit 1: extend "sub-seed 導出ルール" section (around line 123)

Add after the existing pattern explanation:

```markdown
**新モジュールのオフセット登録**: モジュール作成時、sub-seed の数値オフセットを **`clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS`** に登録します。convention は **16-bit hex ASCII (2 文字)** — モジュール名から覚えやすい 2 文字を選ぶ:

\```python
ENRICHER_SEED_OFFSETS = {
    "identity":       540_054,    # 例外: legacy decimal (grandfathered)
    "immunization":   0x494D,     # "IM"
    "code_status":    0x4353,     # "CS"
    "family_history": 0x4648,     # "FH"
    "care_level":     0x434C,     # "CL"
    # 新モジュール例: "device" = 0x4456 ("DV"), "hai" = 0x4841 ("HA")
}
\```

モジュール側はローカル定数を持たず、registry から import します:

\```python
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
seed = derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["my_module"], person_id)
\```

dict 末尾の `assert len(set(...values())) == len(...)` が重複オフセットを import 時に検出します(誤って既存モジュールの RNG ストリームを汚染するのを構造的に防ぐ)。
```

### Edit 2: extend "モジュールの構造 / canonical レイアウト" section (around line 56)

Add after the layout listing:

```markdown
### 共有ヘルパは `clinosim/modules/_shared.py` に集約する

複数 enricher で同じ helper を持つ場合(例: `get_attr_or_key(obj, name, default)` で dict / dataclass 両対応の属性アクセス)、各モジュールに local 定義を書かず **`clinosim/modules/_shared.py`** に置きます。新規モジュールも以下のように import します:

\```python
from clinosim.modules._shared import get_attr_or_key as _get
\```

`as _get` alias で短い local 名を維持し、call site の可読性も保ちます。新しい cross-module helper を追加する場合は **2 モジュール以上で実需が生じたタイミング**で `_shared.py` に昇格させます(YAGNI — 1 モジュールしか使わないなら local 定義のまま)。
```

### Edit 3: extend "判断: Base か Module か" section (around line 15)

Add a new sub-section:

```markdown
### locale 依存の signature 規約

locale 別データ(国別 prevalence、reference range、code mapping 等)をロードする関数は、**`country: str` パラメータを必ず受け取り**、対象外の国では `{}` / `""` 等の no-op 値を早期 return します:

\```python
@lru_cache(maxsize=None)
def load_rates(country: str = "JP") -> dict:
    """Load rates for ``country``. Returns {} for unsupported countries."""
    if str(country).upper() != "JP":
        return {}
    with open(_LOCALE / "jp" / "..." ) as f:
        return yaml.safe_load(f)
\```

理由 — モジュールが現状 1 国対応(例: care_level は JP 専用)であっても、signature を統一しておけば将来 US 対応を追加する際に caller の API を変えずに済みます。`_LOCALE / "jp" / ...` のように country 引数なしでハードコードするのは consistency bug です。

`@lru_cache(maxsize=None)` を併用して反復ロードを避ける(他モジュール — immunization / family_history / code_status — もこのパターン)。
```


---

## 7. byte-diff strategy + test strategy

### byte-diff (US/JP p=2000 seed=42 vs master `dcb47ccc`)

**Expected** — all 11 NDJSON files sha256-IDENTICAL:

| File | Expected status |
|---|---|
| Patient.ndjson | IDENTICAL |
| Encounter.ndjson | IDENTICAL |
| Condition.ndjson | IDENTICAL |
| MedicationRequest.ndjson | IDENTICAL |
| MedicationAdministration.ndjson | IDENTICAL |
| Procedure.ndjson | IDENTICAL |
| ImagingStudy.ndjson | IDENTICAL |
| Immunization.ndjson | IDENTICAL |
| FamilyMemberHistory.ndjson | IDENTICAL |
| Observation.ndjson | IDENTICAL |
| DiagnosticReport.ndjson | IDENTICAL |

Any deviation = bug. The refactor is purely mechanical (function moves, alias renames, numerical identity in offsets); no value changes are possible.

### Unit tests added

`tests/unit/test_shared_utils.py` (new):

- `test_get_attr_or_key_from_dict` — `get_attr_or_key({"k": 1}, "k") == 1`
- `test_get_attr_or_key_from_object` — dataclass attribute access
- `test_get_attr_or_key_missing_returns_default` — both dict and object paths
- `test_get_attr_or_key_none_obj` — `get_attr_or_key(None, "k", "fb") == "fb"` (the new defensive guard)

`tests/unit/test_enricher_seed_offsets.py` (new):

- `test_no_duplicate_offsets` — set-cardinality vs dict-length
- `test_all_modules_registered` — every key {"identity", "immunization", "code_status", "family_history", "care_level"} present
- `test_grandfathered_identity_value` — `ENRICHER_SEED_OFFSETS["identity"] == 540_054` (pin to prevent accidental "harmonization" that would shift identity output)
- `test_hex_ascii_convention_new_modules` — for keys other than "identity", value < 0x10000 (16-bit range)

### Regression

`pytest tests/unit/ tests/integration/ -x -q` must remain green (687 baseline + new shared/seeding tests). e2e (golden) untouched because no data generation paths change.

---

## 8. Plan task breakdown (for writing-plans)

1. **Create `clinosim/modules/_shared.py` + 4 unit tests** (TDD)
2. **Refactor 4 enricher.py to use shared helper** (immunization / code_status / family_history / care_level) — pure mechanical, alias preserves call sites
3. **Create `ENRICHER_SEED_OFFSETS` in seeding.py + 4 unit tests** (registry, duplicate-detection assert, grandfathered pin, hex-range)
4. **Refactor 5 modules to import seed offset from registry** (identity + 4 enrichers) — replace local constant with `ENRICHER_SEED_OFFSETS["name"]`
5. **Refactor `care_level/engine.py` `load_rates(country)` signature + `lru_cache`** — non-JP early return, single existing caller unchanged
6. **CLAUDE.md "AD-55 enricher patterns" subsection added**
6b. **`docs/CONTRIBUTING-modules.md` 3 edits** — sub-seed offset registry section (after line 123), `_shared.py` helper convention sub-section under "モジュールの構造", and locale signature sub-section under "判断: Base か Module か"
7. **byte-diff verification (US/JP p=2000 seed=42 vs master `dcb47ccc`)** — all 11 NDJSON sha256-identical
8. **docs sync** — 4 module READMEs (note shared helper + seed registry import) + DESIGN.md (cross-link from AD-56 enricher entry to ENRICHER_SEED_OFFSETS convention) + TODO.md (PR1 done + PR2-4 backlog)

---

## 9. Deferred to PR2-4

- **PR2 (G2)**: smoking/alcohol SNOMED hardcode → `reference_data.yaml` move + _fhir_sdoh.py split into _fhir_smoking_alcohol.py + _fhir_care_level.py
- **PR3 (G3)**: _fhir_observations.py 31KB → extract immunization into _fhir_immunization.py (mirrors code_status / family_history extraction)
- **PR4 (G4)**: identity enabled gate logic registry simplification + CLAUDE.md "typed field vs extensions decision tree" doctrine

Then the device + HAI 2-module feature work, with PR1-4 conventions inherited.
