# `clinosim.modules.allergy` — 患者アレルギー サンプリング

## 概要

POST_POPULATION パスで患者ごとのアレルギー list をサンプリングし、
`PersonRecord.allergies` に `Allergy` レコードのリスト
(`AllergyReaction` を nested) として書き込む。下流の FHIR
`AllergyIntolerance` emission が同 field を読む。患者レベル 15 % 全体
gate で実 allergen の有無を決め (pre-refactor patient activator の
baseline ~15.3 % に一致)、gate 不成立の患者には「既知のアレルギーなし」
(NKA, SNOMED `716186003`) の肯定記録を 1 件置くので list は空にならない。
アレルギーありの患者は category-weighted の primary allergen に加え、
年齢条件付き polyallergy gate で最大 3 件の追加 allergen を持つ。

## Scope

- **In scope**: 患者レベル全体 gate
  (`OVERALL_ALLERGY_PREVALENCE = 0.15`)、gate 不成立患者への NKA 記録
  (`allergy_id="nka"`、`is_nka=True`、status は `allergens.yaml:nka`)、
  category-weighted primary allergen 選択 (`CATEGORY_WEIGHTS =
  {medication: 0.50, food: 0.25, environment: 0.25}`、category 内は
  `allergens.yaml` から uniform)、polyallergy gate
  (`polyallergy.probability_given_any_allergy` child 0.10 / adult
  0.25 / elderly 0.55、`chronic_ill_conditions` prefix 該当で
  `chronic_ill_bonus` 0.15 加算、上限 0.85) による追加 allergen 1–3 件
  (`additional_count_weights` 0.60 / 0.30 / 0.10、非復元抽出)、
  `cross_reactivity` の category weight boost (penicillin →
  medication +0.20)、per-allergy clinical /
  verification status サンプリング (「active + confirmed」多数派、
  「active + unconfirmed」~10 %、「resolved + confirmed」~5 % で
  food category 限定)。
- **In scope (validation)**: `allergens.yaml` に対する load 時
  6-layer validator。`allergen_code` および各 reaction の
  `manifestation_snomed` を `_code_in_data` 経由で
  [`clinosim/codes/data/snomed-ct.yaml`](../../codes/data/snomed-ct.yaml)
  membership に対して cross-check。`nka` / `polyallergy` /
  `cross_reactivity` block は `_validate_nka_and_polyallergy` で検証。
- **データのみ (他 module が消費)**: `allergens.yaml` の `aging:` block
  (小児食物アレルギー寛解、成人発症の薬剤過敏) は
  `clinosim.modules.population.aging._allergy_drift` が読む。
- **Out of scope**: drug-allergy と処方の相互作用
  ([`clinosim.modules.order`](../order/README.ja.md))、FHIR serialization
  ([`clinosim.modules.output`](../output/README.ja.md))、特定 encounter
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
    load_allergen_config,                # () -> yaml 全体 (allergens + nka + polyallergy + cross_reactivity + aging)
    SUPPORTED_ALLERGEN_CATEGORIES,       # frozenset {"medication", "food", "environment"}
    OVERALL_ALLERGY_PREVALENCE,          # 0.15
    CATEGORY_WEIGHTS,                    # {"medication": 0.50, "food": 0.25, "environment": 0.25}
    ALLERGY_FOOD_RESOLVED_MAX_EXCLUSIVE, # 0.05
    ALLERGY_UNCONFIRMED_MAX_EXCLUSIVE,   # 0.15
)
```

## Scope: AllergyIntolerance ≠ 「何らかのアレルギー疾患」

15% overall gate は **FHIR `AllergyIntolerance` として臨床的に文書化される
患者比率** をモデル化している — medication (Penicillin / Aspirin / Sulfa
等)、重症 food (peanut / shellfish / egg / milk)、environmental
(latex)。実世界 benchmark:

| Reference | Rate | Scope |
| --- | --- | --- |
| MHLW アレルギー疾患実態調査 2011 | 30-40% | 花粉症 (J30) や食物不耐 (K90.4) を含む「何らかのアレルギー疾患」 |
| 薬物アレルギー documented alone | 5-10% | Medication-only、実 EHR |
| 臨床的に文書化された `AllergyIntolerance` 合算 | 10-20% | 実病院 EHR の典型値 |

**emit rate を 30-40% の「何らかのアレルギー疾患」統計と比較しない
こと** — scope 誤りになる。花粉症は `Condition` (ICD-10 `J30`) として、
食物不耐は `Condition` (`K90.4`) として emit される。
`AllergyIntolerance` は「clinician が反応と共にアレルギー欄に記録した」
という狭い surface。

15% は実 `AllergyIntolerance` documentation の 10-20% 帯域の中央付近の
defensible 値で、pre-refactor patient activator baseline (~15.3%) に
一致させて cohort determinism を保つ選択。

正しい audit metric は
[`scripts/audit_realworld_stats_jp.py`](../../../scripts/audit_realworld_stats_jp.py)
を参照 (この benchmark note は audit script 側からも cross-reference される)。

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
- status draw (`clinical` / `verification`)、polyallergy gate、追加
  allergen draw は primary allergen 選択と同じ per-patient RNG stream
  から取るので、list 全体が患者ごとに決定論的。

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
  1 entry (現状 3 / 2 / 2 件)。entry 必須 field: `allergen_code`
  (SNOMED CT。表示は emit 時に `snomed-ct.yaml` から解決)、
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
- 同 yaml の兄弟 block: `nka` (`allergen_code`、`clinical_status`、
  `verification_status`)、`polyallergy`、`cross_reactivity`、`aging`
  (Scope 参照)。

## ディレクトリ構造

```
clinosim/modules/allergy/
  __init__.py                     Allergy + AllergyReaction を再 export
  engine.py                       validator 群 / load_allergens / load_allergen_config / allergy_enricher
  reference_data/
    allergens.yaml                3-category allergen カタログ + 反応、nka、polyallergy、cross_reactivity、aging
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
| --- | --- | --- |
| FHIR `AllergyIntolerance` builder | [`clinosim/modules/output/fhir_r4/conditions/allergy_intolerance.py`](../output/fhir_r4/conditions/allergy_intolerance.py) | `record.allergies` を読み、entry ごとに `AllergyIntolerance` 1 件を emit。id は structural key `{patient_id}-{allergy_id}` から導出した opaque な `allergy-<12hex>`。engine は実アレルギーに `"1"`, `"2"`, … を、NKA に `"nka"` を振る。 |
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
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
