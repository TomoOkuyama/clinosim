# `clinosim.modules.allergy` — 患者アレルギー サンプリング

## 概要

POST_POPULATION パスで患者ごとにアレルギーを 1 件 (または 0 件) サンプリング
し、`PersonRecord.allergies` に `Allergy` レコードのリスト
(`AllergyReaction` を nested) として書き込む。下流の FHIR
`AllergyIntolerance` emission が同 field を読む。sampler は意図的に
2 段階 — 患者レベル 15 % 全体 gate + category-weighted 単一 allergen
draw — で、pre-refactor patient activator が出していた baseline
calibration (population level ~15.3 %) を保つ。

## Scope

- **In scope**: 患者レベル全体 gate
  (`OVERALL_ALLERGY_PREVALENCE = 0.15`)、category-weighted 単一
  allergen 選択 (`CATEGORY_WEIGHTS = {medication: 0.50,
  food: 0.25, environment: 0.25}`)、category 内で
  `allergens.yaml` から uniform 選択、per-allergy clinical /
  verification status サンプリング (「active + confirmed」多数派、
  「active + unconfirmed」~10 %、「resolved + confirmed」~5 % で
  food category 限定)。
- **In scope (validation)**: `allergens.yaml` に対する import 時
  6-layer validator。`allergen_code` および各 reaction の
  `manifestation_snomed` を `_code_in_data` 経由で
  [`clinosim/codes/data/snomed-ct.yaml`](../../codes/data/snomed-ct.yaml)
  membership に対して cross-check。
- **Out of scope**: 患者あたり複数アレルギー (現状 single-allergy、
  拡張は code コメントで記載)、drug-allergy と処方の相互作用
  ([`clinosim.modules.order`](../order/README.md))、FHIR serialization
  ([`clinosim.modules.output`](../output/README.md))、特定 encounter
  中の反応 event 生成、SNOMED 表示テキスト
  ([`clinosim/codes/`](../../codes/))。

## Public API

`__init__.py` は 2 つの dataclass を再 export するのみ。enricher /
loader entry は `engine` から直接 import:

```python
from clinosim.modules.allergy import Allergy, AllergyReaction
from clinosim.modules.allergy.engine import (
    allergy_enricher,                    # POST_POPULATION enricher entry
    load_allergens,                      # () -> {"medication": [...], "food": [...], "environment": [...]}
    SUPPORTED_ALLERGEN_CATEGORIES,       # frozenset {"medication", "food", "environment"}
    OVERALL_ALLERGY_PREVALENCE,          # 0.15
    CATEGORY_WEIGHTS,                    # {"medication": 0.50, "food": 0.25, "environment": 0.25}
    ALLERGY_FOOD_RESOLVED_MAX_EXCLUSIVE, # 0.05
    ALLERGY_UNCONFIRMED_MAX_EXCLUSIVE,   # 0.15
)
```

## 決定論

- サブ seed オフセット `0x414C` (`"AL"`)。
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["allergy"]` に登録済み。
- 患者単位 RNG:
  `derive_sub_seed(master_seed, offset, person_id)` — 同一患者は
  常に同じアレルギー (または無し) をサンプリングし、population
  主 RNG 列を消費しない (AD-16)。
- category weight は
  `normalize_probabilities(..., fallback="raise")` で正規化し、
  YAML 事前正規化 drift が silent bias にならず raise する。
- status draw (`clinical` / `verification`) は allergen 選択と同じ
  per-patient RNG stream から取るので、status 分布も患者ごとに決定論的。

## 依存

- `clinosim.modules._shared` — `normalize_probabilities`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.types.allergy` — `Allergy`, `AllergyReaction`。
- `clinosim.codes.loader._load_system` (`_code_in_data` 経由) —
  import 時 SNOMED 直接 membership check。
- `numpy` — `np.random.Generator`。
- `yaml` — YAML パーサ。
- 他の `clinosim.modules.*` には依存しない。

## 定数と設定

- module レベル定数 (`engine.py` 内すべて):
  - `SUPPORTED_ALLERGEN_CATEGORIES` — 3 canonical category の
    frozenset。`allergens.yaml` キーと完全一致必須。
  - `OVERALL_ALLERGY_PREVALENCE = 0.15` — Step-4 calibrated gate
    rate。
  - `CATEGORY_WEIGHTS` — gate 成立後の medication / food /
    environment 分布 (相対 weight、sample 時に正規化)。
  - `ALLERGY_FOOD_RESOLVED_MAX_EXCLUSIVE = 0.05` — food 限定バケット
    (`clinical="resolved" + verification="confirmed"`)。小児期の
    食物アレルギー寛解モデル。
  - `ALLERGY_UNCONFIRMED_MAX_EXCLUSIVE = 0.15` — `active +
    unconfirmed` 累積 cutoff。残 ~85 % が `active + confirmed`。
- [`reference_data/allergens.yaml`](reference_data/allergens.yaml)
  — `allergens.{medication, food, environment}` 配下に allergen ごとに
  1 entry。entry 必須 field: `allergen_code` (SNOMED CT)、
  `allergen_display_en`、`allergen_display_ja`、
  `prevalence.adult` (0..1 — category level 参考レートの
  documentation であり、実際の gate ではない)、`criticality`、
  `common_reactions[]` (各要素は `manifestation_snomed` と
  `severity`)。`allergen_code` および各 `common_reactions[].manifestation_snomed`
  は import 時に
  [`clinosim/codes/data/snomed-ct.yaml`](../../codes/data/snomed-ct.yaml)
  に存在するか cross-check し、未知コードは空表示に fall-through させず
  raise する (AD-30 chain、`hai/engine.py:_code_in_data` の兄弟 pattern)。
- 6-layer validator (`_validate_allergens`) は以下を reject:
  (1) 空 top-level、(2) `allergens` 欠落 / 非 dict、
  (3) `SUPPORTED_ALLERGEN_CATEGORIES` との双方向キー drift、
  (4) per-category list が空、(5) 必須 entry field 欠落、
  (6) `prevalence.adult` 範囲違反 または SNOMED cross-check 失敗。

## ディレクトリ構造

```
clinosim/modules/allergy/
  __init__.py                     Allergy + AllergyReaction を再 export
  engine.py                       validator / load_allergens / allergy_enricher
  reference_data/
    allergens.yaml                3-category allergen カタログ + 反応
```

**`enricher.py` / `audit.py` / 独立 `assign_*` 関数は存在しない** —
enricher entry は `engine.py` の `allergy_enricher`。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`L119-134` 付近) の `register_builtin_enrichers` で登録:

- `name="allergy"`, `stage=POST_POPULATION`, `order=10`,
  `enabled=lambda c: True`。
- POST_POPULATION order 10 (identity と同 order)。以降の全 enricher /
  simulation stage に対して allergy が利用可能な状態を保つ。
  identity は JP-only gate があり、両者の実行は実質 disjoint。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| FHIR `AllergyIntolerance` builder | [`clinosim/modules/output/fhir_r4/conditions/allergy_intolerance.py`](../output/fhir_r4/conditions/allergy_intolerance.py) | `record.allergies` を読み、entry ごとに `AllergyIntolerance` 1 件を emit。id は builder 所有の canonical `allergy-{patient_id}-{idx}` (I-4 fix — engine は placeholder `allergy_id="1"` を置く)。 |
| Enricher registry | [`clinosim/simulator/enrichers.py:127`](../../simulator/enrichers.py) | POST_POPULATION order=10 登録。 |

## テスト

```bash
pytest tests/unit -k allergy -q         # loader + validator + engine + types
pytest tests/unit -k fhir_allergy -q    # AllergyIntolerance 出力
```

個別ファイル:

- [`tests/unit/test_types_allergy.py`](../../../tests/unit/test_types_allergy.py)
  — `Allergy` / `AllergyReaction` dataclass shape。
- [`tests/unit/modules/allergy/test_engine.py`](../../../tests/unit/modules/allergy/test_engine.py)
  — enricher 決定論、gate 率、category 分布、status 分布。
- [`tests/unit/modules/allergy/test_allergens_yaml.py`](../../../tests/unit/modules/allergy/test_allergens_yaml.py)
  — 6-layer validator coverage。
- [`tests/unit/output/test_fhir_allergy_intolerance.py`](../../../tests/unit/output/test_fhir_allergy_intolerance.py)
  — `AllergyIntolerance` 出力 end-to-end。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
