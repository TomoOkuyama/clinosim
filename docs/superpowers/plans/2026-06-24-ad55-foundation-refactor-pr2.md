# AD-55 Module Foundation Refactor PR2 (G2 SDOH Integrity) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Single-module mechanical refactor — inline execution recommended.

**Goal:** Pure mechanical refactor (byte-identical output guaranteed) to consolidate SDOH integrity: (1) move 6 SNOMED enum→code mappings from Python dict hardcode to YAML in a new lightweight `modules/sdoh/` module, (2) split the 88-line `_fhir_sdoh.py` (3 mixed responsibilities) into `_fhir_smoking_alcohol.py` + `_fhir_care_level.py`, (3) promote 2 generic FHIR helpers (`_social_category`, `_value`) to `_fhir_common.py` for future SDOH builder reuse.

**Architecture:** New module `clinosim/modules/sdoh/` with `engine.py` (loader only — "data-only module variant" pattern, no enricher). Existing `_fhir_common.py` extended with 2 promoted helpers. Two new builder files consume sdoh module + common helpers. `_fhir_sdoh.py` deleted after all responsibilities migrate.

**Tech Stack:** Python 3.11+, pytest, ruff. PyYAML for the new reference data load.

## Global Constraints

- Branch: `feat/ad55-foundation-refactor-pr2` (already created, spec commit `22da9e23`)
- Spec source: `docs/superpowers/specs/2026-06-24-ad55-foundation-refactor-pr2-design.md`
- Predecessor: PR #83 (PR1), master HEAD `36ac9afd`
- **byte-identical output gate**: all 11 NDJSON files sha256-IDENTICAL at US/JP p=2000 seed=42 vs master `36ac9afd`. Any deviation = blocker.
- **Pre-PR2 verification confirms byte-safety**:
  - `_fhir_sdoh.py` already calls `code_lookup("snomed-ct", code, lang)` at `_value()` line 29 — display source is `codes/data/snomed-ct.yaml` (unchanged)
  - Hardcoded dict `_SMOKING_SNOMED` / `_ALCOHOL_SNOMED` are **enum→code mapping only** (not display source) — moving to YAML preserves byte output as long as same enum→code pairs are emitted
  - All 6 SNOMED codes verified in `codes/data/snomed-ct.yaml` with `en` + `ja` displays (PR #68)
- **Additional side-effect targets discovered during plan-write**:
  - `tests/unit/test_sdoh_codes.py:23` imports `_ALCOHOL_SNOMED` from `_fhir_sdoh.py` — must update to consume new YAML via `load_social_history()`
  - `clinosim/modules/care_level/README.md:34` references `modules/output/_fhir_sdoh.py:_build_care_level` — must update to `_fhir_care_level.py`
  - `_fhir_common.py:54-60` already has `_micro_coding(system_key, code, lang)` returning **bare coding dict** — distinct from spec's `_value()` which **wraps in CodeableConcept** `{"coding": [...], "text": ...}`. Promoted `_value` keeps its existing name (verbatim move, scope-minimal) with docstring clarifying the distinction from `_micro_coding`
- **AD-16**: no RNG draws added or changed; pure mechanical refactor
- **AD-56**: `_BUNDLE_BUILDERS` registration order preserved (same 3 entries, just from new import paths)
- **Commit trailer (every commit)**:
  ```
  Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
  ```
- **English code + comments**; **Japanese in module READMEs** (project convention)
- **Verification before assertion**: every commit follows a green pytest run

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `clinosim/modules/sdoh/__init__.py` | Create | Public API export: `load_social_history` |
| `clinosim/modules/sdoh/engine.py` | Create | `@lru_cache` loader for SDOH reference data (no assignment logic) |
| `clinosim/modules/sdoh/reference_data/social_history.yaml` | Create | smoking_status + alcohol_use: LOINC + category + enum→SNOMED |
| `clinosim/modules/sdoh/README.md` | Create | Module documentation (data-only variant, future SDOH expansion notes) |
| `tests/unit/test_sdoh_engine.py` | Create | 7 unit tests pinning loader output |
| `clinosim/modules/output/_fhir_common.py` | Modify | Add 2 promoted helpers: `_social_category(country)`, `_value(system_key, code, lang)` |
| `clinosim/modules/output/_fhir_smoking_alcohol.py` | Create | `_build_smoking_status` + `_build_alcohol_use` (consume sdoh + common) |
| `clinosim/modules/output/_fhir_care_level.py` | Create | `_build_care_level` (verbatim move) |
| `clinosim/modules/output/_fhir_sdoh.py` | **Delete** | All 3 responsibilities migrated |
| `clinosim/modules/output/fhir_r4_adapter.py:118-122` | Modify | Update import paths (3 builders from 2 new files) |
| `tests/unit/test_sdoh_codes.py:19-28` | Modify | Update `_ALCOHOL_SNOMED` import to consume new YAML via `load_social_history()` |
| `clinosim/modules/care_level/README.md:34` | Modify | Update `_fhir_sdoh.py` → `_fhir_care_level.py` cross-reference |
| `docs/CONTRIBUTING-modules.md` | Modify | Add "データ専用モジュール (variant)" sub-section |
| `DESIGN.md` | Modify | AD-56 entry cross-reference to data-only variant pattern |
| `TODO.md` | Modify | PR2 done + PR3-4 backlog |
| `scratchpad/refactor_pr2_byte_diff/compare.py` | Create (scratch) | sha256 comparison script |
| `scratchpad/refactor_pr2_byte_diff_results.md` | Create | byte-diff evidence (committed) |

---

## Task 1: `clinosim/modules/sdoh/` full module setup + 7 unit tests

**Files:**
- Create: `clinosim/modules/sdoh/__init__.py`
- Create: `clinosim/modules/sdoh/engine.py`
- Create: `clinosim/modules/sdoh/reference_data/social_history.yaml`
- Create: `clinosim/modules/sdoh/README.md`
- Create: `tests/unit/test_sdoh_engine.py`

**Interfaces:**
- Produces: `clinosim.modules.sdoh.load_social_history() -> dict` returning `{smoking_status: {loinc, category, values}, alcohol_use: {loinc, category, values}}`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_sdoh_engine.py`:

```python
"""Unit tests for clinosim.modules.sdoh.engine.load_social_history."""
from __future__ import annotations

import pytest

from clinosim.modules.sdoh import load_social_history


@pytest.mark.unit
def test_load_social_history_has_topics():
    data = load_social_history()
    assert "smoking_status" in data
    assert "alcohol_use" in data


@pytest.mark.unit
def test_smoking_status_loinc():
    data = load_social_history()
    assert data["smoking_status"]["loinc"] == "72166-2"


@pytest.mark.unit
def test_alcohol_use_loinc():
    data = load_social_history()
    assert data["alcohol_use"]["loinc"] == "11331-6"


@pytest.mark.unit
def test_smoking_status_3_tiers():
    data = load_social_history()
    assert set(data["smoking_status"]["values"].keys()) == {"never", "former", "current"}


@pytest.mark.unit
def test_alcohol_use_3_tiers():
    data = load_social_history()
    assert set(data["alcohol_use"]["values"].keys()) == {"none", "social", "heavy"}


@pytest.mark.unit
def test_snomed_codes_match_pre_refactor():
    """Pin the 6 SNOMED codes from the pre-PR2 _fhir_sdoh.py hardcoded dicts.

    Regression guard — if anyone "improves" the YAML and changes a code,
    this test catches it BEFORE byte-diff would (which is a slower
    feedback loop)."""
    data = load_social_history()
    assert data["smoking_status"]["values"]["never"]["snomed"] == "266919005"
    assert data["smoking_status"]["values"]["former"]["snomed"] == "8517006"
    assert data["smoking_status"]["values"]["current"]["snomed"] == "449868002"
    assert data["alcohol_use"]["values"]["none"]["snomed"] == "105542008"
    assert data["alcohol_use"]["values"]["social"]["snomed"] == "28127009"
    assert data["alcohol_use"]["values"]["heavy"]["snomed"] == "86933000"


@pytest.mark.unit
def test_lru_cache_returns_same_object():
    """load_social_history is @lru_cache decorated so repeat calls return
    the same dict instance (avoids repeated YAML reads)."""
    a = load_social_history()
    b = load_social_history()
    assert a is b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sdoh_engine.py -v 2>&1 | tail -10`
Expected: `ModuleNotFoundError: No module named 'clinosim.modules.sdoh'`

- [ ] **Step 3: Create `clinosim/modules/sdoh/__init__.py`**

```python
"""SDOH (social determinants of health) module — AD-55 Base.

Currently scopes social-history attributes that the simulator populates
on PatientProfile during activation: smoking_status (US Core LOINC
72166-2 + SNOMED) and alcohol_use (LOINC 11331-6 + SNOMED).

Data-only module variant (see CONTRIBUTING-modules.md): engine.py
provides a loader for reference data; assignment logic lives in the
patient activator (smoking/alcohol are demographics-driven attributes,
not post-records enrichment).

Future SDOH expansions (occupation, education, housing status, food
insecurity, etc.) should slot in here — add a topic to
reference_data/social_history.yaml or a new reference_data/<topic>.yaml
file. Builders that consume the data live in clinosim/modules/output/.
"""
from clinosim.modules.sdoh.engine import load_social_history

__all__ = ["load_social_history"]
```

- [ ] **Step 4: Create `clinosim/modules/sdoh/engine.py`**

```python
"""SDOH reference data loader (AD-55 Base, data-only module variant).

No assignment / generation logic — smoking_status and alcohol_use are
demographics-driven attributes set on PatientProfile during activation
(see patient/activator.py + locale/{us,jp}/demographics.yaml). This
module only provides the enum→SNOMED + LOINC reference data needed by
FHIR builders.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def load_social_history() -> dict:
    """Load SDOH social-history reference data.

    Returns a dict keyed by SDOH topic (currently ``smoking_status`` and
    ``alcohol_use``). Each topic value is a dict with:

      - ``loinc`` (str): US Core LOINC code for the Observation
      - ``category`` (str): FHIR Observation.category code (typically
        ``"social-history"``)
      - ``values`` (dict): enum key → ``{"snomed": "<code>"}`` mapping

    Display strings are NOT in this YAML — resolved at FHIR output time
    via ``clinosim.codes.lookup("snomed-ct", code, lang)``.
    """
    with open(_HERE / "reference_data" / "social_history.yaml") as f:
        return yaml.safe_load(f) or {}
```

- [ ] **Step 5: Create `clinosim/modules/sdoh/reference_data/social_history.yaml`**

```yaml
# AD-55 Base SDOH social-history reference (PR2 2026-06-24).
#
# US Core profiles:
#   - Smoking Status: http://hl7.org/fhir/us/core/StructureDefinition/us-core-smokingstatus
#     LOINC 72166-2 "Tobacco smoking status NHIS"
#     SNOMED CT values per US Core IG (3 simplified tiers)
#   - Alcohol use: LOINC 11331-6 "History of Alcohol use"
#     SNOMED CT values per HL7 social history (3 simplified tiers)
#
# Display strings for SNOMED codes are resolved at FHIR output time via
# clinosim.codes.lookup("snomed-ct", code, lang) — NOT duplicated here.
# All 6 SNOMED codes are registered in codes/data/snomed-ct.yaml with
# `en` + `ja` displays (verified by PR #68 SNOMED CT authority crosswalk).

smoking_status:
  loinc: "72166-2"
  category: "social-history"
  values:
    never:   {snomed: "266919005"}  # Never smoked tobacco
    former:  {snomed: "8517006"}    # Ex-smoker
    current: {snomed: "449868002"}  # Current every day smoker

alcohol_use:
  loinc: "11331-6"
  category: "social-history"
  values:
    none:   {snomed: "105542008"}   # Current non-drinker of alcohol
    social: {snomed: "28127009"}    # Social drinker
    heavy:  {snomed: "86933000"}    # Heavy drinker
```

- [ ] **Step 6: Create `clinosim/modules/sdoh/README.md`**

```markdown
# clinosim/modules/sdoh

AD-55 Base SDOH (social determinants of health) module.

データ専用モジュール (variant) — generation / assignment logic を持たず、
**reference データ + loader のみ** を提供する軽量モジュール (PR2 2026-06-24
で確立)。`clinosim/codes/` が同パターンの先例。

## 役割

PatientProfile activation 時に決定される social-history 属性 (smoking_status,
alcohol_use) を FHIR Observation として出力するための **enum→SNOMED + LOINC
マッピング** を YAML で提供。

| 属性 | LOINC | US Core profile |
|---|---|---|
| smoking_status | 72166-2 | us-core-smokingstatus |
| alcohol_use | 11331-6 | (HL7 social history) |

SNOMED display は `clinosim.codes.lookup("snomed-ct", code, lang)` で
解決 (本モジュールには重複させない)。6 SNOMED コードは全て
`codes/data/snomed-ct.yaml` に登録済 (PR #68 で照合)。

## Public API

```python
from clinosim.modules.sdoh import load_social_history

data = load_social_history()
# data["smoking_status"]["loinc"]  → "72166-2"
# data["smoking_status"]["values"]["never"]["snomed"]  → "266919005"
```

`@lru_cache(maxsize=1)` 付きなので反復呼び出し OK。

## ファイル構成

```
clinosim/modules/sdoh/
  __init__.py            # load_social_history を export
  engine.py              # loader (assignment 関数なし)
  reference_data/
    social_history.yaml  # smoking_status + alcohol_use 定義
  README.md
```

## Dependencies

- `clinosim/codes/` — 表示文字列の解決 (`code_lookup("snomed-ct", ...)`)
- なし (他モジュール / locale / types への依存なし)

## Consumers

- `clinosim/modules/output/_fhir_smoking_alcohol.py` — smoking + alcohol
  FHIR Observation builder
- (将来) `clinosim/modules/output/_fhir_occupation.py` 等

## 将来の SDOH 拡張

新しい SDOH 属性 (occupation, education, housing, food insecurity 等) を
追加する場合:

1. **PatientProfile に simple enum 属性として既に存在** (smoking/alcohol 同型)
   → `reference_data/social_history.yaml` に topic を追加 or
   `reference_data/<topic>.yaml` を新規 (LOINC ありの社会歴 Observation
   ファミリ)
2. **assignment / 計算ロジックが必要** (例: food_insecurity が住所 + 所得
   から導出) → 独立モジュール `clinosim/modules/<theme>/` を作る
   (engine.py + enricher.py のフル setup)

つまり本モジュールは AD-55 Base "シンプル属性" のデータ集約場所であり、
複雑な計算が必要なものは独立モジュール化する。

## 関連

- AD-55 Base (PR #65 で smoking/alcohol/care_level 追加)
- PR2 2026-06-24 (本モジュール作成、`_fhir_sdoh.py` から分離)
- CONTRIBUTING-modules.md「データ専用モジュール (variant)」
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/unit/test_sdoh_engine.py -v 2>&1 | tail -12`
Expected: 7 PASS

- [ ] **Step 8: Commit**

```bash
git add clinosim/modules/sdoh/ tests/unit/test_sdoh_engine.py
git commit -m "$(cat <<'EOF'
feat(sdoh): clinosim/modules/sdoh/ — data-only module + social_history.yaml

New lightweight AD-55 Base module for SDOH reference data. Data-only
variant pattern (no enricher, no ENRICHER_SEED_OFFSETS entry):
clinosim/codes/ is the preexisting precedent for module-with-loader-
only-no-generation-logic.

Initial scope: smoking_status (US Core LOINC 72166-2 + SNOMED 3 tiers)
+ alcohol_use (LOINC 11331-6 + SNOMED 3 tiers). All 6 SNOMED codes
moved from pre-PR2 _fhir_sdoh.py hardcoded Python dicts to
reference_data/social_history.yaml. Display strings stay in
codes/data/snomed-ct.yaml (no duplication).

7 unit tests pin: topics present / LOINC values / 3-tier enum values /
6 SNOMED codes match pre-refactor / lru_cache identity.

Future SDOH expansions (occupation/education/housing/food insecurity)
slot in here per README guidance: simple enum -> add to YAML; needs
assignment logic -> create independent module.

No FHIR builder edits in this commit — those follow.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 2: Promote `_social_category` + `_value` to `_fhir_common.py`

**Files:**
- Modify: `clinosim/modules/output/_fhir_common.py` (add 2 helpers + 2 imports)

**Interfaces:**
- Consumes: `_localize_display` + `_CATEGORY_DISPLAY_JA` from `clinosim.modules.output._fhir_localization`
- Produces: `_social_category(country: str) -> list[dict]` + `_value(system_key: str, code: str, lang: str) -> dict[str, Any]`

- [ ] **Step 1: Add `_localize_display` + `_CATEGORY_DISPLAY_JA` to `_fhir_common.py` imports**

In `clinosim/modules/output/_fhir_common.py`, locate the existing imports from `_fhir_localization`:

```python
from clinosim.modules.output._fhir_localization import (
    _FREQ_JA,
    _ROUTE_JA,
    _SEVERITY_DISPLAY_JA,
    _localize_dosage_terms,
    _localize_drug_name,
)
```

Add `_CATEGORY_DISPLAY_JA` and `_localize_display` to this import list (alphabetized):

```python
from clinosim.modules.output._fhir_localization import (
    _CATEGORY_DISPLAY_JA,
    _FREQ_JA,
    _ROUTE_JA,
    _SEVERITY_DISPLAY_JA,
    _localize_display,
    _localize_dosage_terms,
    _localize_drug_name,
)
```

- [ ] **Step 2: Add `_social_category` helper after `_survey_category`**

In `_fhir_common.py`, after the existing `_survey_category()` function (line 63-75), append:

```python


def _social_category(country: str) -> list[dict]:
    """FHIR Observation.category for social-history (US Core SDOH).

    Returns the standard hl7-observation-category coding with localized
    display + text — used by every social-history Observation builder
    (smoking, alcohol, occupation, education, housing, ...). Promoted
    from _fhir_sdoh.py in PR2 (G2 SDOH integrity refactor, 2026-06-24).
    """
    return [{
        "coding": [{
            "system": get_system_uri("hl7-observation-category"),
            "code": "social-history",
            "display": _localize_display("Social History", country, _CATEGORY_DISPLAY_JA),
        }],
        "text": "社会歴" if country == "JP" else "Social History",
    }]
```

- [ ] **Step 3: Add `_value` helper after `_loinc_coding`**

In `_fhir_common.py`, after the existing `_loinc_coding()` function (line 78-84), append:

```python


def _value(system_key: str, code: str, lang: str) -> dict[str, Any]:
    """Build a FHIR valueCodeableConcept with localized display.

    Generic helper for any coded value whose display lives in
    clinosim.codes. Returns a CodeableConcept fragment
    {"coding": [{"system": ..., "code": ..., "display": ...}], "text": ...}
    — distinct from _micro_coding() in this module which returns the
    bare coding dict (no CodeableConcept wrapping). Used by SDOH
    builders (smoking_status / alcohol_use / care_level) and any future
    builder emitting a coded valueCodeableConcept.

    Promoted from _fhir_sdoh.py in PR2 (G2 SDOH integrity refactor,
    2026-06-24).
    """
    coding: dict[str, Any] = {"system": get_system_uri(system_key), "code": code}
    disp = code_lookup(system_key, code, lang)
    if disp and disp != code:
        coding["display"] = disp
    return {"coding": [coding], "text": disp or code}
```

- [ ] **Step 4: Run all existing tests to confirm no regression**

Run: `pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -5`
Expected: 704+ passed (697 baseline + 7 new sdoh_engine). The two new helpers in `_fhir_common.py` aren't yet consumed but should not break anything.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/output/_fhir_common.py
git commit -m "$(cat <<'EOF'
refactor(fhir-common): promote _social_category + _value helpers

Two generic helpers promoted from _fhir_sdoh.py for future reuse:

- _social_category(country): FHIR Observation.category list for
  social-history observations (will be used by smoking/alcohol/
  care_level after split, plus future occupation/education/housing)
- _value(system_key, code, lang): FHIR valueCodeableConcept builder
  with display resolved via code_lookup. Distinct from existing
  _micro_coding() which returns the bare coding dict (no CodeableConcept
  wrapping); docstring clarifies the distinction.

Adds _CATEGORY_DISPLAY_JA + _localize_display imports from
_fhir_localization (alphabetized).

No call sites consume these yet — Tasks 3-4 (new builder files) will.
Pure additive change; existing _fhir_sdoh.py call sites unaffected.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 3: Create `clinosim/modules/output/_fhir_smoking_alcohol.py`

**Files:**
- Create: `clinosim/modules/output/_fhir_smoking_alcohol.py`

**Interfaces:**
- Consumes: `load_social_history` from Task 1, `_social_category` + `_value` from Task 2
- Produces: `_build_smoking_status(ctx) -> list[dict]` + `_build_alcohol_use(ctx) -> list[dict]`

- [ ] **Step 1: Create the file**

Create `clinosim/modules/output/_fhir_smoking_alcohol.py`:

```python
"""FHIR smoking_status + alcohol_use social-history Observation builders.

AD-55 Base. Reads enum→SNOMED + LOINC reference data from
clinosim/modules/sdoh/reference_data/social_history.yaml via
load_social_history(). Display strings resolved via
clinosim.codes.lookup("snomed-ct", code, lang) (the _value helper in
_fhir_common does this).

Split out of the former _fhir_sdoh.py (PR2 G2 SDOH integrity refactor,
2026-06-24) so that each SDOH topic family has its own builder file —
care_level (JP-only) is in _fhir_care_level.py; future SDOH topics
(occupation/education/housing) get their own files following this pattern.
"""
from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules.output._fhir_common import (
    BundleContext,
    _social_category,
    _value,
)
from clinosim.modules.sdoh import load_social_history


def _obs(obs_id: str, country: str, loinc: str, loinc_text: str,
         value_system: str, value_code: str) -> dict[str, Any]:
    """LOINC-keyed social-history Observation skeleton.

    Local helper (not promoted to _fhir_common) because the LOINC-keyed
    pattern is specific to standardized SDOH observations like smoking
    and alcohol — care_level uses a custom JP code system and has a
    different shape, so promoting this would be premature.
    """
    lang = "ja" if country == "JP" else "en"
    return {
        "resourceType": "Observation",
        "id": obs_id,
        "status": "final",
        "category": _social_category(country),
        "code": {"coding": [{"system": get_system_uri("loinc"), "code": loinc,
                             "display": code_lookup("loinc", loinc, "en")}],
                 "text": loinc_text},
        "valueCodeableConcept": _value(value_system, value_code, lang),
    }


def _build_smoking_status(ctx: BundleContext) -> list[dict]:
    data = load_social_history()["smoking_status"]
    status = (ctx.patient_data or {}).get("smoking_status", "")
    entry = data["values"].get(status)
    if not entry:
        return []
    text = "喫煙状況" if ctx.country == "JP" else "Tobacco smoking status"
    o = _obs(f"smoking-{ctx.patient_id}", ctx.country, data["loinc"], text,
             "snomed-ct", entry["snomed"])
    o["subject"] = {"reference": f"Patient/{ctx.patient_id}"}
    return [o]


def _build_alcohol_use(ctx: BundleContext) -> list[dict]:
    data = load_social_history()["alcohol_use"]
    use = (ctx.patient_data or {}).get("alcohol_use", "")
    entry = data["values"].get(use)
    if not entry:
        return []
    text = "飲酒歴" if ctx.country == "JP" else "History of alcohol use"
    o = _obs(f"alcohol-{ctx.patient_id}", ctx.country, data["loinc"], text,
             "snomed-ct", entry["snomed"])
    o["subject"] = {"reference": f"Patient/{ctx.patient_id}"}
    return [o]
```

- [ ] **Step 2: Verify the file imports correctly (smoke test)**

Run: `python -c "from clinosim.modules.output._fhir_smoking_alcohol import _build_smoking_status, _build_alcohol_use; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add clinosim/modules/output/_fhir_smoking_alcohol.py
git commit -m "$(cat <<'EOF'
feat(fhir): _fhir_smoking_alcohol.py — split out of _fhir_sdoh.py

New builder file for smoking_status + alcohol_use social-history
Observations. Reads enum->SNOMED + LOINC from modules/sdoh YAML via
load_social_history(); display via code_lookup. Uses promoted
_social_category + _value from _fhir_common.

Output byte-identical to pre-PR2 _fhir_sdoh.py (verified later in
byte-diff task): same LOINC, same SNOMED, same i18n text strings,
same id pattern (smoking-{patient_id} / alcohol-{patient_id}), same
subject reference, same fall-through behavior (return [] when status
or use is empty/unknown).

Local _obs() helper kept here (LOINC-keyed Observation skeleton); not
promoted to _fhir_common because care_level uses a custom JP code
system with different shape.

Not yet wired into _BUNDLE_BUILDERS — Task 5 will switch the imports.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 4: Create `clinosim/modules/output/_fhir_care_level.py`

**Files:**
- Create: `clinosim/modules/output/_fhir_care_level.py`

**Interfaces:**
- Consumes: `_social_category` + `_value` from Task 2
- Produces: `_build_care_level(ctx) -> list[dict]`

- [ ] **Step 1: Create the file**

Create `clinosim/modules/output/_fhir_care_level.py`:

```python
"""FHIR JP 要介護度 (long-term-care need level) social-history Observation
builder (AD-55 Base, JP only).

Extracted from the former _fhir_sdoh.py (PR2 G2 SDOH integrity refactor,
2026-06-24) for single-responsibility separation. care_level uses a
custom JP code system (jp-care-level, MHLW 介護保険 区分) and has a
different shape from the LOINC-keyed smoking/alcohol observations, so
it deserves its own file.

Data source: ctx.record.care_level (set by clinosim/modules/care_level/
enricher during post-records pass for JP patients only).
"""
from __future__ import annotations

from typing import Any

from clinosim.modules.output._fhir_common import (
    BundleContext,
    _social_category,
    _value,
)


def _build_care_level(ctx: BundleContext) -> list[dict]:
    """JP 要介護度 (long-term-care need level) social-history Observation."""
    code = ctx.record.get("care_level") or ""
    if not code:
        return []
    lang = "ja" if ctx.country == "JP" else "en"
    text = "要介護度" if ctx.country == "JP" else "Long-term care need level"
    o: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"carelevel-{ctx.patient_id}",
        "status": "final",
        "category": _social_category(ctx.country),
        "code": {"text": text},
        "subject": {"reference": f"Patient/{ctx.patient_id}"},
        "valueCodeableConcept": _value("jp-care-level", code, lang),
    }
    return [o]
```

- [ ] **Step 2: Verify the file imports correctly (smoke test)**

Run: `python -c "from clinosim.modules.output._fhir_care_level import _build_care_level; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add clinosim/modules/output/_fhir_care_level.py
git commit -m "$(cat <<'EOF'
feat(fhir): _fhir_care_level.py — split out of _fhir_sdoh.py

New builder file for JP 要介護度 (long-term-care need level)
social-history Observation. Verbatim move of _build_care_level from
the former _fhir_sdoh.py (lines 72-88). Custom JP code system
(jp-care-level, MHLW 介護保険 区分) has a different shape from
LOINC-keyed SDOH observations, so single-file separation gives clearer
ownership.

Consumes _social_category + _value from _fhir_common (promoted in
Task 2).

Output byte-identical to pre-PR2 _fhir_sdoh.py (verified later in
byte-diff task).

Not yet wired into _BUNDLE_BUILDERS — Task 5 will switch the imports.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 5: Update `fhir_r4_adapter.py` import paths + delete `_fhir_sdoh.py`

**Files:**
- Modify: `clinosim/modules/output/fhir_r4_adapter.py:118-122`
- Delete: `clinosim/modules/output/_fhir_sdoh.py`

**Interfaces:**
- Consumes: builders from Tasks 3 & 4 (`_build_smoking_status`, `_build_alcohol_use` from `_fhir_smoking_alcohol`; `_build_care_level` from `_fhir_care_level`)
- Produces: `_BUNDLE_BUILDERS` list entries reference the new files

- [ ] **Step 1: Update imports in `fhir_r4_adapter.py`**

Locate the existing import block at `clinosim/modules/output/fhir_r4_adapter.py:118-122`:

```python
from clinosim.modules.output._fhir_sdoh import (  # noqa: F401
    _build_alcohol_use,
    _build_care_level,
    _build_smoking_status,
)
```

Replace with two import lines:

```python
from clinosim.modules.output._fhir_care_level import _build_care_level  # noqa: F401
from clinosim.modules.output._fhir_smoking_alcohol import (  # noqa: F401
    _build_alcohol_use,
    _build_smoking_status,
)
```

The `_BUNDLE_BUILDERS` list at line 419-421 (3 entries: smoking / alcohol / care_level in that order) is **unchanged** — same symbols, just from different import paths.

- [ ] **Step 2: Confirm no other file imports from `_fhir_sdoh.py`**

Run: `grep -rn "from clinosim.modules.output._fhir_sdoh\|import _fhir_sdoh" clinosim/ 2>&1 | grep -v ".pyc"`

Expected output: empty (no production code references). If anything appears, halt and re-evaluate.

Test files: `tests/unit/test_sdoh_codes.py:23` imports `_ALCOHOL_SNOMED` — handled in Task 7 (regression task).

- [ ] **Step 3: Delete `_fhir_sdoh.py`**

```bash
rm clinosim/modules/output/_fhir_sdoh.py
```

- [ ] **Step 4: Run full unit + integration regression**

Run: `pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -8`

Expected: `tests/unit/test_sdoh_codes.py::test_alcohol_social_uses_active_concept` will FAIL with `ImportError: cannot import name '_ALCOHOL_SNOMED'`. All other tests should pass (704+ except for this one). This is expected — Task 7 fixes the test.

If anything ELSE fails, halt and investigate. Most likely cause: a stray import we missed.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/output/fhir_r4_adapter.py
git rm clinosim/modules/output/_fhir_sdoh.py
git commit -m "$(cat <<'EOF'
refactor(fhir): delete _fhir_sdoh.py — responsibilities migrated to 2 files

_fhir_sdoh.py (88 lines, 3 mixed responsibilities) split in PR2:
- smoking + alcohol -> _fhir_smoking_alcohol.py (Task 3)
- care_level -> _fhir_care_level.py (Task 4)
- _social_category + _value helpers promoted to _fhir_common.py (Task 2)
- _SMOKING_SNOMED + _ALCOHOL_SNOMED enum->code mappings moved to
  modules/sdoh/reference_data/social_history.yaml (Task 1)

fhir_r4_adapter.py import paths updated (3 builders now imported from
2 new files). _BUNDLE_BUILDERS list entries unchanged (same symbols,
same order — registration is identical).

Known test failure after this commit: tests/unit/test_sdoh_codes.py
imports _ALCOHOL_SNOMED which no longer exists; Task 7 updates that
test to consume the new YAML via load_social_history().

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 6: Update `test_sdoh_codes.py` to consume new YAML

**Files:**
- Modify: `tests/unit/test_sdoh_codes.py:19-28`

**Interfaces:**
- Consumes: `load_social_history` from Task 1

- [ ] **Step 1: Update the test that imports `_ALCOHOL_SNOMED`**

In `tests/unit/test_sdoh_codes.py`, locate the existing test:

```python
def test_alcohol_social_uses_active_concept():
    # 160573003 is the INACTIVE observable "Alcohol intake (observable entity)",
    # not a drinking-pattern finding — verified inactive via tx.fhir.org (SNOMED
    # CT International). The "social" tier must use active 28127009 Social drinker.
    from clinosim.modules.output._fhir_sdoh import _ALCOHOL_SNOMED

    assert _ALCOHOL_SNOMED["social"] == "28127009"
    assert "160573003" not in _ALCOHOL_SNOMED.values()
    for code in _ALCOHOL_SNOMED.values():
        assert lookup("snomed-ct", code, "en") not in ("", code)
```

Replace with:

```python
def test_alcohol_social_uses_active_concept():
    # 160573003 is the INACTIVE observable "Alcohol intake (observable entity)",
    # not a drinking-pattern finding — verified inactive via tx.fhir.org (SNOMED
    # CT International). The "social" tier must use active 28127009 Social drinker.
    from clinosim.modules.sdoh import load_social_history

    alcohol = load_social_history()["alcohol_use"]["values"]
    codes = {tier: entry["snomed"] for tier, entry in alcohol.items()}

    assert codes["social"] == "28127009"
    assert "160573003" not in codes.values()
    for code in codes.values():
        assert lookup("snomed-ct", code, "en") not in ("", code)
```

- [ ] **Step 2: Run the updated test + full regression**

Run: `pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -5`
Expected: 704+ green (697 baseline + 7 new sdoh_engine). The previously-failing `test_alcohol_social_uses_active_concept` now PASSES via the new YAML path.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_sdoh_codes.py
git commit -m "$(cat <<'EOF'
test(sdoh): update test_alcohol_social_uses_active_concept to use new YAML

After PR2's deletion of _fhir_sdoh.py, the _ALCOHOL_SNOMED import is
gone. Test now consumes the same data via load_social_history() from
modules/sdoh — same SNOMED codes, same assertions (160573003 not in
values, 28127009 = active "Social drinker"), now backed by YAML.

Regression: 704+ unit + integration green.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 7: byte-diff verification (US/JP p=2000 seed=42 vs master `36ac9afd`)

**Files:**
- Create (scratch, NOT committed): `scratchpad/refactor_pr2_byte_diff/`
- Create: `scratchpad/refactor_pr2_byte_diff_results.md` (committed)

**Goal:** Confirm all 11 NDJSON files sha256-IDENTICAL between master and branch. Any deviation = blocker.

- [ ] **Step 1: Generate branch output (US p=2000 + JP p=2000, seed=42)**

```bash
mkdir -p scratchpad/refactor_pr2_byte_diff/branch/us scratchpad/refactor_pr2_byte_diff/branch/jp
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/refactor_pr2_byte_diff/branch/us
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP --format fhir-r4 -o scratchpad/refactor_pr2_byte_diff/branch/jp
```

(Both can be parallel with `run_in_background=true`.)

- [ ] **Step 2: Generate master output (switch to `36ac9afd`, generate, switch back)**

```bash
git checkout 36ac9afd
mkdir -p scratchpad/refactor_pr2_byte_diff/master/us scratchpad/refactor_pr2_byte_diff/master/jp
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/refactor_pr2_byte_diff/master/us
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP --format fhir-r4 -o scratchpad/refactor_pr2_byte_diff/master/jp
git checkout feat/ad55-foundation-refactor-pr2
```

- [ ] **Step 3: Create comparison script**

Create `scratchpad/refactor_pr2_byte_diff/compare.py`:

```python
"""Byte-diff comparison: master 36ac9afd vs ad55-refactor-pr2 branch.

PR2 is a pure mechanical refactor — all 11 NDJSON files MUST be sha256-IDENTICAL.
Any deviation = blocker.
"""
from __future__ import annotations

import hashlib
import sys
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
        m = find_fhir_dir(Path(f"scratchpad/refactor_pr2_byte_diff/master/{country}"))
        b = find_fhir_dir(Path(f"scratchpad/refactor_pr2_byte_diff/branch/{country}"))
        print(f"\n=== {country.upper()} ===")
        print(f"  master dir: {m}")
        print(f"  branch dir: {b}")
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
        sys.exit(0)
    else:
        print("✗ BLOCKER — at least one NDJSON differs; PR2 refactor introduced a behavior change")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

Run: `python scratchpad/refactor_pr2_byte_diff/compare.py | tee scratchpad/refactor_pr2_byte_diff/comparison.txt`

- [ ] **Step 4: Verify result**

Expected: every line ends with `IDENTICAL` (or `ABSENT both` for ImagingStudy). Script ends with `✓ ALL NDJSON files sha256-IDENTICAL`.

If any `DIFF` appears: **STOP**. PR2 broke output equivalence. Likely cause: YAML SNOMED value mistyped in Task 1 (would have been caught by `test_snomed_codes_match_pre_refactor`), or `_obs()` reconstruction in Task 3 missed an attribute. Re-verify against the spec §5/§6 verbatim comparison.

Most likely first failure point if it happens: `Observation.ndjson` (the 3 SDOH builders are the only output changed).

- [ ] **Step 5: Write byte-diff evidence document**

Create `scratchpad/refactor_pr2_byte_diff_results.md`:

```markdown
# PR2 (AD-55 Foundation Refactor G2 SDOH Integrity) byte-diff results

**Setup**: US/JP p=2000 seed=42, format=fhir-r4 vs master `36ac9afd`.

## Result: ALL 11 NDJSON IDENTICAL ✓

Pure mechanical refactor preserved byte-identical output as required.

[paste compare.py output here]

## What this confirms

- 6 SNOMED enum->code mappings in YAML produce numerically identical
  output to pre-PR2 hardcoded Python dicts
- _social_category() + _value() promoted to _fhir_common produce
  bit-identical fragments to former _fhir_sdoh.py local versions
- _BUNDLE_BUILDERS order unchanged → no reordering of Observation
  serialization
- LOINC display lookup (code_lookup("loinc", "72166-2", "en")) and
  SNOMED display lookup unchanged — output text fragments identical
- i18n text strings ("喫煙状況" / "Tobacco smoking status" etc.) preserved
  as Python literals in new builder files
```

- [ ] **Step 6: Commit byte-diff evidence**

```bash
git add scratchpad/refactor_pr2_byte_diff_results.md
git commit -m "$(cat <<'EOF'
test(byte-diff): PR2 AD-55 G2 SDOH refactor — all 11 NDJSON IDENTICAL

US/JP p=2000 seed=42 vs master 36ac9afd. Pure mechanical refactor
preserved byte-identical output as required:
- All 11 NDJSON files sha256 IDENTICAL (Patient/Encounter/Condition/
  MedicationRequest/MedicationAdministration/Procedure/Immunization/
  FamilyMemberHistory/Observation/DiagnosticReport)
- ImagingStudy ABSENT in both (not generated at this scale)

Critically, Observation.ndjson is byte-identical despite the SDOH
builder rewrite — confirms:
- 6 SNOMED codes in YAML match hardcoded dicts numerically
- Promoted _social_category + _value produce identical fragments
- _BUNDLE_BUILDERS registration order preserved
- All i18n text strings preserved

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 8: docs sync (CONTRIBUTING + DESIGN + TODO + care_level README)

**Files:**
- Modify: `docs/CONTRIBUTING-modules.md` (add "データ専用モジュール (variant)" sub-section)
- Modify: `clinosim/modules/care_level/README.md:34` (update cross-reference)
- Modify: `DESIGN.md` (AD-56 entry extension)
- Modify: `TODO.md` (PR2 done + PR3-4 backlog)

- [ ] **Step 1: Add "データ専用モジュール (variant)" sub-section to CONTRIBUTING-modules.md**

Find the existing "## モジュールの構造" section in `docs/CONTRIBUTING-modules.md`. Inside it, locate the "### 共有ヘルパは `clinosim/modules/_shared.py` に集約する" sub-section (added in PR1, around line 67-77). Insert a new sub-section right AFTER it:

```markdown
### データ専用モジュール (variant)

`modules/sdoh/` のように、**reference データ + loader のみ** を持ち、generation / assignment logic を持たないモジュール variant も認められます (PR2 2026-06-24 で確立)。`clinosim/codes/` が同パターンの先例です。

判定基準:
- データは存在するが、generation / assignment は別の場所 (patient activator / FHIR output builder / 他モジュール enricher) で行われる
- 複数の consumer から参照される共通参照データを集約したい
- 将来同テーマのデータ拡張余地が高い

レイアウト:

```
clinosim/modules/<name>/
  __init__.py            <- public API (loader 関数を export)
  engine.py              <- @lru_cache 付き loader のみ (assignment 関数なし OK)
  reference_data/*.yaml  <- データ駆動の定義
  README.md              <- 他モジュールと同型
```

enricher.py は **不要** (post_records enricher の登録なし)。`ENRICHER_SEED_OFFSETS` への登録も **不要** (RNG draw なし)。
```

- [ ] **Step 2: Update `care_level/README.md:34` cross-reference**

In `clinosim/modules/care_level/README.md`, find the existing reference:

```markdown
- **FHIR**: `modules/output/_fhir_sdoh.py` の `_build_care_level` を `_BUNDLE_BUILDERS`
```

Replace with:

```markdown
- **FHIR**: `modules/output/_fhir_care_level.py` の `_build_care_level` を `_BUNDLE_BUILDERS`
```

- [ ] **Step 3: Update DESIGN.md AD-56 entry with PR2 cross-reference**

Find the AD-56 entry in DESIGN.md (the line starting with `| AD-56 | 2026-06-15 | Extensibility foundation`). It was extended in PR1; extend it again with a PR2 note. Find:

```
... See CLAUDE.md "AD-55 enricher patterns" subsection + `docs/CONTRIBUTING-modules.md` for the contributor playbook. |
```

Replace with:

```
... See CLAUDE.md "AD-55 enricher patterns" subsection + `docs/CONTRIBUTING-modules.md` for the contributor playbook. **PR2 2026-06-24 G2 SDOH integrity refactor** further established the "データ専用モジュール (variant)" pattern (`modules/sdoh/` — reference data + loader only, no enricher / no ENRICHER_SEED_OFFSETS entry — `clinosim/codes/` is the preexisting precedent); also split `_fhir_sdoh.py` into `_fhir_smoking_alcohol.py` + `_fhir_care_level.py` for single-responsibility separation, and promoted `_social_category` / `_value` helpers to `_fhir_common.py` for future SDOH builder reuse. |
```

- [ ] **Step 4: Update TODO.md with PR2 done entry**

Find the existing PR1 entry (added at the end of the TODO.md in PR1 docs sync). After PR1's entry and before "## Future design improvements", insert:

```markdown

**AD-55 Module Foundation Refactor PR2 (G2 SDOH integrity) — 2026-06-24:**
Mechanical SDOH integrity refactor preparing for future SDOH expansion
(occupation / education / housing / food insecurity). Three items:

1. 6 SNOMED enum->code mappings (3 smoking + 3 alcohol) moved from
   Python dict hardcode in _fhir_sdoh.py to YAML in new lightweight
   `clinosim/modules/sdoh/` module ("data-only module variant" —
   reference data + loader only, no enricher / no ENRICHER_SEED_OFFSETS;
   `clinosim/codes/` is the preexisting precedent).
2. `_fhir_sdoh.py` 88-line file split into `_fhir_smoking_alcohol.py`
   (LOINC-keyed pattern) + `_fhir_care_level.py` (JP-only, custom code
   system). _fhir_sdoh.py deleted.
3. `_social_category` + `_value` helpers promoted to `_fhir_common.py`
   for future SDOH builder reuse (occupation / education / housing /
   food insecurity will inherit).

CONTRIBUTING-modules.md gains "データ専用モジュール (variant)" sub-section
documenting the new module shape. DESIGN.md AD-56 entry extended.

Byte-diff vs master `36ac9afd` @ p=2000 seed=42: all 11 NDJSON
sha256-IDENTICAL for both US and JP (pure mechanical refactor;
numerical identity preserved through YAML). See
`scratchpad/refactor_pr2_byte_diff_results.md`.

Series context: PR2 of 4 (G2 done) -> PR3 (G3 _fhir_observations.py
31KB split, immunization extraction) -> PR4 (G4 doctrine docs:
identity enabled gate registry + typed field vs extensions decision
tree) -> then device + HAI feature work.
```

- [ ] **Step 5: Run final regression**

Run: `pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -5`
Expected: 704+ green.

- [ ] **Step 6: Commit docs sync**

```bash
git add docs/CONTRIBUTING-modules.md clinosim/modules/care_level/README.md DESIGN.md TODO.md
git commit -m "$(cat <<'EOF'
docs(sync): PR2 AD-55 G2 SDOH refactor — CONTRIBUTING + DESIGN + TODO

CONTRIBUTING-modules.md: new "データ専用モジュール (variant)" sub-section
under "## モジュールの構造" documents the data-only module pattern
established by modules/sdoh/ (reference data + loader only, no
enricher; clinosim/codes/ is the preexisting precedent).

care_level/README.md: cross-reference updated from _fhir_sdoh.py
(deleted) to _fhir_care_level.py.

DESIGN.md AD-56 entry: extended with PR2 cross-reference (data-only
variant + _fhir_sdoh.py split + _fhir_common helper promotion).

TODO.md: PR2 done entry with full summary + PR3-4 backlog explicit.

Regression: 704+ unit + integration green.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Final: Push + PR

After all 8 tasks complete and working tree is clean:

```bash
git push -u origin feat/ad55-foundation-refactor-pr2
gh pr create --title "refactor: AD-55 Module Foundation PR2 — SDOH integrity (G2)" --body "$(cat <<'EOF'
## Summary

**PR2 of 4 refactor PRs** preparing clean foundation for the device + HAI feature modules.

**Pure mechanical refactor — byte-identical output guaranteed and verified.**

Three SDOH integrity items consolidated:

1. **6 SNOMED enum→code mappings → YAML** (new lightweight `clinosim/modules/sdoh/` module)
   - "Data-only module variant" pattern (no enricher / no ENRICHER_SEED_OFFSETS entry)
   - `clinosim/codes/` is the preexisting precedent
   - Establishes home for future SDOH expansion (occupation / education / housing / food insecurity)

2. **`_fhir_sdoh.py` 88-line file split** into 2 single-responsibility files
   - `_fhir_smoking_alcohol.py` (LOINC-keyed SDOH pattern)
   - `_fhir_care_level.py` (JP-only, custom code system)
   - `_fhir_sdoh.py` deleted

3. **`_social_category` + `_value` helpers promoted to `_fhir_common.py`**
   - For future SDOH builder reuse (occupation already exists, education / housing / food insecurity will follow)
   - Distinguished from existing `_micro_coding` (bare coding vs CodeableConcept-wrapped) — docstring clarifies

## Convention docs (今後のモジュール追加 統一性)

- `docs/CONTRIBUTING-modules.md` new "データ専用モジュール (variant)" sub-section
- `DESIGN.md` AD-56 entry extended with PR2 cross-reference
- `clinosim/modules/sdoh/README.md` documents future SDOH expansion guidance (simple enum → YAML; complex assignment → independent module)

## Evidence

**byte-diff (US/JP p=2000 seed=42 vs master `36ac9afd`)**: **all 11 NDJSON files sha256-IDENTICAL** for both US and JP. See `scratchpad/refactor_pr2_byte_diff_results.md`.

## Tests

- 7 new unit tests in `test_sdoh_engine.py` (loader + LOINC + 3-tier values + 6 SNOMED pin + lru_cache)
- `test_sdoh_codes.py::test_alcohol_social_uses_active_concept` updated to consume new YAML (same assertions, new data source)
- **704+ unit + integration tests green** (697 baseline + 7 new)

## Series context

- PR1 (G1, merged): structural DRY ✓
- **PR2 (G2, this PR)**: SDOH integrity ✓
- PR3 (G3): `_fhir_observations.py` 31KB split (immunization extraction)
- PR4 (G4): doctrine docs (identity enabled gate registry + typed field vs extensions decision tree)
- Then: device + HAI feature work (2 modules with cross-module enricher consumption)

## Spec / Plan

- spec: `docs/superpowers/specs/2026-06-24-ad55-foundation-refactor-pr2-design.md`
- plan: `docs/superpowers/plans/2026-06-24-ad55-foundation-refactor-pr2.md`

## Test plan

- [x] Unit tests (test_sdoh_engine 7 new + test_sdoh_codes 1 updated)
- [x] byte-diff p=2000 US/JP vs master 36ac9afd — all 11 NDJSON IDENTICAL
- [x] Full regression (unit + integration) — 704+ green

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Self-Review Notes

**Spec coverage check (against spec §1-§11)**:
- §1 motivation / byte-safety pre-verification → captured in Global Constraints
- §2 architecture diagram → Tasks 1-5
- §3 modules/sdoh/ full setup → Task 1
- §4 _fhir_common.py extension → Task 2
- §5 _fhir_smoking_alcohol.py → Task 3
- §6 _fhir_care_level.py → Task 4
- §7 fhir_r4_adapter.py import update + delete _fhir_sdoh.py → Task 5
- §8 byte-diff + tests → Task 1 (unit) + Task 7 (byte-diff)
- §9 CONTRIBUTING-modules.md addition → Task 8
- §10 plan task breakdown → matches the 8 tasks here (consolidated regression into Task 7 byte-diff + final commit in Task 8)
- §11 deferred PR3-4 → captured in PR body Series context

**Placeholder scan**: All steps have concrete code or commands. No "TBD/TODO/implement later".

**Type consistency**: `load_social_history() -> dict` signature consistent across Tasks 1, 3, 6. `_social_category(country: str) -> list[dict]` + `_value(system_key: str, code: str, lang: str) -> dict[str, Any]` consistent across Tasks 2, 3, 4. `_build_smoking_status` / `_build_alcohol_use` / `_build_care_level` names match spec verbatim.

**Verification commands**: every code-modifying step ends with a verification command (pytest or smoke import test). byte-diff is a complete equivalent of PR1's pattern.

**Scope-additional items discovered during plan-write** (vs spec):
- test_sdoh_codes.py update (Task 6, new task)
- care_level/README.md cross-reference update (folded into Task 8 docs sync)
- _fhir_common.py existing `_micro_coding` distinction documented in promoted `_value` docstring (Task 2)

All items in spec §10's 9-task list mapped to plan's 8 tasks (consolidating §10's "Run regression" + "byte-diff" into a single Task 7 for cleaner inline execution).

**Inline-recommended over subagent-driven**: pure mechanical refactor with single-module tightly-coupled tasks. Phase 2a/2b/PR1 pattern (inline executing-plans) is the right fit.
