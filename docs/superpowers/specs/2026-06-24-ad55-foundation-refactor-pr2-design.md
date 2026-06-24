# AD-55 Module Foundation Refactor — PR2 (G2 SDOH Integrity)

**Date**: 2026-06-24
**Author**: Tomo Okuyama (with Claude Opus 4.7)
**Status**: APPROVED — ready for plan
**Series context**: 2 of 4 refactor PRs preparing clean foundation for device + HAI feature modules.
**Predecessor**: PR1 (G1 structural DRY, master `36ac9afd` merged)
**Successors**: PR3 (G3 `_fhir_observations.py` 31KB split) → PR4 (G4 doctrine docs) → device + HAI feature work

---

## 1. Motivation

PR1 consolidated structural-DRY violations (`_get`, sub-seed offsets, locale signature). PR2 addresses **SDOH integrity** — the next layer of the 8 improvements identified in brainstorming session 14:

- `clinosim/modules/output/_fhir_sdoh.py` hardcodes 6 SNOMED codes for smoking_status (3) and alcohol_use (3) as Python dicts (`_SMOKING_SNOMED`, `_ALCOHOL_SNOMED`), violating the **`code_status` module's data-driven pattern** (which puts enum→SNOMED mapping in `reference_data/code_status.yaml`).
- Same file mixes 3 SDOH builder responsibilities — smoking, alcohol, and **JP-only** care_level — in a single 88-line file, violating single-responsibility for the modular FHIR builder pattern that subsequent SDOH expansions (occupation, education, housing, food insecurity) will inherit.

### Pre-PR2 verification of byte-safety

Inspection of `_fhir_sdoh.py` confirmed that:
- `_value()` helper at line 27-32 **already calls** `code_lookup("snomed-ct", code, lang)` for display strings — display source is `codes/data/snomed-ct.yaml` (already populated and authoritative per PR #68).
- 6 SNOMED codes used in hardcoded dicts (266919005, 8517006, 449868002, 105542008, 28127009, 86933000) are registered in `codes/data/snomed-ct.yaml` with `en` + `ja` displays.
- The Python dict is **only an enum→code mapping**, NOT a display source. Moving the mapping to YAML preserves byte output as long as the same enum→code pairs are produced.

→ **byte-identical output guaranteed** for pure mechanical refactor.

### Hard guarantee

All 11 NDJSON files sha256-IDENTICAL at US/JP p=2000 seed=42 vs master `36ac9afd`. Any deviation = blocker.

---

## 2. Architecture

```
                    Before PR2
                    ──────────
   clinosim/modules/output/_fhir_sdoh.py  (88 lines, 3 SDOH responsibilities)
     ├─ _SMOKING_SNOMED  (Python dict, hardcoded)
     ├─ _ALCOHOL_SNOMED  (Python dict, hardcoded)
     ├─ _social_category() / _value() / _obs()  (local helpers)
     ├─ _build_smoking_status()
     ├─ _build_alcohol_use()
     └─ _build_care_level()  (JP-only, different output shape)

                    After PR2
                    ─────────
   clinosim/modules/sdoh/   (new lightweight module, data-only variant)
     ├─ __init__.py            (public API: load_social_history)
     ├─ engine.py              (@lru_cache loader, no assignment logic)
     ├─ reference_data/
     │   └─ social_history.yaml  (enum→SNOMED + LOINC + category, YAML)
     └─ README.md

   clinosim/modules/output/_fhir_common.py  (extended)
     ├─ _social_category(country)   ← promoted (future occupation/education will use)
     └─ _value(system_key, code, lang)  ← promoted (generic SNOMED coding helper)

   clinosim/modules/output/_fhir_smoking_alcohol.py  (new, 2 builders)
     ├─ imports load_social_history from sdoh module
     ├─ _obs() local helper (LOINC-keyed Observation structure)
     ├─ _build_smoking_status()
     └─ _build_alcohol_use()

   clinosim/modules/output/_fhir_care_level.py  (new, 1 builder)
     └─ _build_care_level()  (JP-only, custom code system — independent shape)

   clinosim/modules/output/_fhir_sdoh.py  ← DELETED
```

**Invariants preserved**:
- Same SNOMED codes emitted for same patient input (enum→code mapping numerically identical)
- Same display strings (still resolved via `code_lookup("snomed-ct", ...)`)
- Same FHIR Observation structure (id / category / subject / code / valueCodeableConcept)
- Same i18n text strings ("喫煙状況" / "Tobacco smoking status" preserved as Python constants in new builder)
- `_BUNDLE_BUILDERS` registration order unchanged (only import paths change)

---

## 3. Component 1: `clinosim/modules/sdoh/` — new lightweight module

### Directory layout (full setup per user decision in brainstorming)

```
clinosim/modules/sdoh/
  __init__.py
  engine.py
  reference_data/
    social_history.yaml
  README.md
```

### `__init__.py`

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

### `engine.py`

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

### `reference_data/social_history.yaml`

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

### `README.md`

Module-level documentation mirroring care_level / family_history README structure: overview, dependencies, public API, future expansion notes, authority sources.

---

## 4. Component 2: `_fhir_common.py` extension (helper promotion)

Two helpers currently local to `_fhir_sdoh.py` are promoted to `_fhir_common.py` because they are **generic** (not SDOH-specific) and will be reused by future builders (occupation already exists, education / housing will follow):

### `_social_category(country)` — moved verbatim

```python
def _social_category(country: str) -> list[dict]:
    """FHIR Observation.category for social-history (US Core SDOH).

    Returns the standard hl7-observation-category coding with localized
    display + text — used by every social-history Observation builder
    (smoking, alcohol, occupation, education, housing, ...).
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

### `_value(system_key, code, lang)` — moved verbatim

```python
def _value(system_key: str, code: str, lang: str) -> dict[str, Any]:
    """Build a FHIR valueCodeableConcept with localized display.

    Generic helper for any coded value whose display lives in
    clinosim.codes (avoids hardcoding display strings in builders).
    Used by smoking_status / alcohol_use / care_level / future
    SDOH builders.
    """
    coding: dict[str, Any] = {"system": get_system_uri(system_key), "code": code}
    disp = code_lookup(system_key, code, lang)
    if disp and disp != code:
        coding["display"] = disp
    return {"coding": [coding], "text": disp or code}
```

Import-side adjustments are added to `_fhir_common.py` (it already imports `get_system_uri` and `code_lookup` for other helpers).

---

## 5. Component 3: `_fhir_smoking_alcohol.py` (new builder file)

```python
"""FHIR smoking_status + alcohol_use social-history Observation builders.

AD-55 Base. Reads enum→SNOMED + LOINC reference data from
clinosim/modules/sdoh/reference_data/social_history.yaml via
load_social_history(). Display strings resolved via
clinosim.codes.lookup("snomed-ct", code, lang).

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
    BundleContext, _social_category, _value,
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

**Behavioral identity check**:
- LOINC `data["loinc"]` = `"72166-2"` / `"11331-6"` (same as hardcoded)
- SNOMED `entry["snomed"]` = same code as `_SMOKING_SNOMED.get(status)` / `_ALCOHOL_SNOMED.get(use)` for any input
- Same fall-through `return []` when status/use is empty or unknown
- Same `text` i18n strings (preserved as Python literals)
- Same `subject.reference` format
- Same id pattern (`smoking-{patient_id}` / `alcohol-{patient_id}`)

→ byte-identical to current `_fhir_sdoh.py` output.

---

## 6. Component 4: `_fhir_care_level.py` (new builder file)

```python
"""FHIR JP 要介護度 (long-term-care need level) social-history Observation
builder (AD-55 Base, JP only).

Extracted from the former _fhir_sdoh.py (PR2 G2 SDOH integrity refactor,
2026-06-24) for single-responsibility separation. care_level uses a
custom JP code system (jp-care-level, MHLW 介護保険 区分) and has a
different shape from the LOINC-keyed smoking/alcohol observations, so
it deserves its own file.
"""
from __future__ import annotations

from typing import Any

from clinosim.modules.output._fhir_common import (
    BundleContext, _social_category, _value,
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

Verbatim move of `_build_care_level` from `_fhir_sdoh.py:72-88` with imports adjusted to consume `_social_category` / `_value` from `_fhir_common`.

---

## 7. Component 5: `fhir_r4_adapter.py` import path update

The `_BUNDLE_BUILDERS` list itself is unchanged (same 3 entries in same order); only the import paths change:

```python
# Before
from clinosim.modules.output._fhir_sdoh import (
    _build_alcohol_use,
    _build_care_level,
    _build_smoking_status,
)

# After
from clinosim.modules.output._fhir_care_level import _build_care_level
from clinosim.modules.output._fhir_smoking_alcohol import (
    _build_alcohol_use,
    _build_smoking_status,
)
```

Then **delete `clinosim/modules/output/_fhir_sdoh.py`** (all 3 responsibilities migrated).

---

## 8. byte-diff strategy + test strategy

### byte-diff (US/JP p=2000 seed=42 vs master `36ac9afd`)

**Expected** — all 11 NDJSON files sha256-IDENTICAL. The refactor is pure mechanical (function moves, alias renames, YAML-loaded values numerically identical to hardcoded dict values). Any deviation = blocker.

| File | Expected status |
|---|---|
| All 11 NDJSON (Patient/Encounter/Condition/Med*/Procedure/Imaging/Immunization/FamilyHistory/Observation/DR) | IDENTICAL |

### Unit tests added

`tests/unit/test_sdoh_engine.py` (new):

- `test_load_social_history_has_topics` — returns dict with `smoking_status` + `alcohol_use` keys
- `test_smoking_status_loinc` — `data["smoking_status"]["loinc"] == "72166-2"`
- `test_alcohol_use_loinc` — `data["alcohol_use"]["loinc"] == "11331-6"`
- `test_smoking_status_3_tiers` — values has exactly `never`/`former`/`current`
- `test_alcohol_use_3_tiers` — values has exactly `none`/`social`/`heavy`
- `test_snomed_codes_match_pre_refactor` — pin the 6 SNOMED codes (regression guard; if anyone "improves" the YAML and changes a code, this test catches it before byte-diff would)
- `test_lru_cache_returns_same_object` — second call returns same dict instance

### Regression

`pytest tests/unit/ tests/integration/ -x -q` must remain green (697 + 7 new sdoh_engine = 704+).

---

## 9. CONTRIBUTING-modules.md addition: "data-only module variant"

A short sub-section addition to capture the new pattern PR2 introduces:

```markdown
### データ専用モジュール (variant)

`modules/sdoh/` のように、**reference データ + loader のみ** を持ち、generation / assignment logic を持たないモジュール variant も認められます (PR2 2026-06-24 で確立)。`clinosim/codes/` が同パターンの先例です。

判定基準:
- データは存在するが、generation / assignment は別の場所(patient activator / FHIR output builder / 他モジュール enricher)で行われる
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

enricher.py は **不要**(post_records enricher の登録なし)。`ENRICHER_SEED_OFFSETS` への登録も **不要**(RNG draw なし)。
```

---

## 10. Plan task breakdown

1. **Create `clinosim/modules/sdoh/` full setup** (`__init__.py` + `engine.py` + `reference_data/social_history.yaml` + `README.md`) + 7 unit tests in `tests/unit/test_sdoh_engine.py` (TDD)
2. **Promote `_social_category` + `_value` to `_fhir_common.py`** (verbatim move, ensure imports work)
3. **Create `clinosim/modules/output/_fhir_smoking_alcohol.py`** (smoking + alcohol builders consuming sdoh module + common helpers)
4. **Create `clinosim/modules/output/_fhir_care_level.py`** (verbatim move of `_build_care_level`)
5. **Update `clinosim/modules/output/fhir_r4_adapter.py`** import paths
6. **Delete `clinosim/modules/output/_fhir_sdoh.py`**
7. **Run full unit + integration regression** (697 + 7 = 704+ green)
8. **byte-diff verification** (US/JP p=2000 seed=42 vs master `36ac9afd`, all 11 NDJSON IDENTICAL) + commit evidence doc
9. **docs sync** — `CONTRIBUTING-modules.md` data-only module variant subsection + `TODO.md` PR2 done + PR3-4 backlog + `DESIGN.md` AD-56 entry cross-reference

---

## 11. Deferred to PR3-4

- **PR3 (G3)**: `_fhir_observations.py` 31KB split — extract immunization out (mirrors `_fhir_code_status.py` / `_fhir_family_history.py` extractions)
- **PR4 (G4)**: identity enabled gate registry simplification + CLAUDE.md "typed field vs extensions decision tree" doctrine

Then: device + HAI 2-module feature work with the cleaned foundation.
