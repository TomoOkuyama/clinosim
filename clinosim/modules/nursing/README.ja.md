# nursing モジュール

**Tier 1 #3 α-min-2 新規 Module（AD-64）**

## 概要

入院・ICU・リハビリ入院 encounter に対して、以下を提供する：

1. **primary_nurse 割り当て** (`assign_primary_nurse`) — StaffRoster から看護師を uniform sampling
2. **看護アセスメント scaffolding** (`load_nursing_assessment`) — ADL / リスクアセスメント / 疾患別 nursing focus の YAML 読込み + 6-layer validation

nursing_enricher（POST_ENCOUNTER order=94）は α-min-2 で実装済み。

## Dependencies

- `clinosim/types/staff.py` — `StaffRoster`, `StaffMember`
- `clinosim/modules/nursing/reference_data/nursing_assessment.yaml` — ADL/risk/disease focus data

## Public API

```python
from clinosim.modules.nursing import (
    SUPPORTED_ADL_CATEGORIES,       # frozenset[str] — 5 ADL categories
    SUPPORTED_RISK_ASSESSMENTS,     # frozenset[str] — 3 risk assessment types
    INPATIENT_ENCOUNTER_TYPES,      # frozenset[str] — "inpatient"|"icu"|"rehab_inpatient"
    load_nursing_assessment,        # () -> dict  @lru_cache(maxsize=1)
    assign_primary_nurse,           # (encounter, roster, rng) -> str
)
```

## nursing_assessment.yaml 構造

```yaml
adl_categories:
  eating: [independent, partial_assist, full_assist]
  ...                        # SUPPORTED_ADL_CATEGORIES と 1:1 対応
risk_assessments:
  fall_risk: [low, moderate, high]
  ...                        # SUPPORTED_RISK_ASSESSMENTS と 1:1 対応
disease_specific_nursing_focus:
  bacterial_pneumonia:
    focus: "..."             # 日本語 focus 説明文
    interventions_ja: [...]  # 介入リスト
  ...
baseline:
  focus: "..."
  interventions_ja: [...]
```

## 6-layer validator (_validate_nursing_assessment)

| Layer | チェック内容 |
|---|---|
| 1 | empty top-level check |
| 2 | required top-level keys（adl_categories / risk_assessments / disease_specific_nursing_focus / baseline）None チェック |
| 3 | baseline required fields（focus + interventions_ja）|
| 4 | adl_categories ↔ SUPPORTED_ADL_CATEGORIES forward+reverse coverage |
| 4b | risk_assessments ↔ SUPPORTED_RISK_ASSESSMENTS forward+reverse coverage |
| 5 | disease_specific_nursing_focus 各エントリ required fields（focus + interventions_ja）|
| 6 | type checks（interventions_ja は list）|

## assign_primary_nurse

```python
def assign_primary_nurse(encounter, roster: StaffRoster, rng: np.random.Generator) -> str:
    """roster.get_by_role("nurse") から uniform sampling。看護師がいない場合 "" を返す。"""
```

- RNG の seeding 責任は **呼び出し元**（nursing_enricher）が持つ
- `derive_sub_seed(master, ENRICHER_SEED_OFFSETS["nursing"], encounter_id)` パターンを Task 5 で適用

## Enricher 登録（α-min-2 完了）

```python
# clinosim/simulator/enrichers.py に登録済み
register_enricher(EnricherStage.POST_ENCOUNTER, nursing_enricher, order=94, name="nursing_assignment")
```

## Seeding

`ENRICHER_SEED_OFFSETS["nursing"] = 0x4E55`（"NU"）— `clinosim/simulator/seeding.py` 登録済み。

## テスト

```bash
pytest tests/unit/modules/nursing/ -v
```

27 tests: constants / load / validator 6-layer / assign_primary_nurse determinism
