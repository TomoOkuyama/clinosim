# `clinosim.modules.population` — 集患エリアサンプリング + 医療 life event

## 概要

初期集患エリア population (世帯 + 人物: demographics / 住所 / 電話 /
体格 / lifestyle / 慢性疾患) を生成し、その上で 年 scale の医療
calendar (月次 acute-disease event、慢性フォロー visit、screening、
[`clinosim.modules.pediatric`](../pediatric/README.md) と merge した
小児 visit) を回す。本モジュールはシミュレーション pipeline の頭。
下流全モジュールが返却の `PopulationRegistry` を消費する。

## Scope

- **In scope**: 国別 age × sex サンプリングを伴う世帯 + 人物構築、
  慢性疾患 prevalence (`sex: M`/`F` の任意 filter 付)、
  `clinosim.locale` 経由の氏名 / 住所 / 電話 生成、体格
  (BMI、`HEIGHT_SHRINKAGE_AGE_THRESHOLD` 越えでの年齢別 shrinkage
  付き身長)、lifestyle 属性 (喫煙 / 飲酒 / care-seeking threshold)、
  per-person Rh factor の決定論的導出
  (`_derive_rh_factor` は person_id + country の SHA-256 hash、
  RNG 非消費)、季節 / lifestyle / 職業リスク乗数付きの月次 acute
  event サンプリング、年次 healthcare calendar 生成 (慢性フォロー、
  mammography / colonoscopy / diabetic retinopathy / flu ワクチン
  screening、小児 visit)。
- **Out of scope**: 姓名 / 住所 / 電話 raw data
  ([`clinosim/locale/<country>/`](../../locale/))、疾患プロトコル定義
  ([`clinosim.modules.disease`](../disease/README.md))、患者の
  encounter 発生
  ([`clinosim.modules.patient.activator`](../patient/README.md))、
  identity / 保険番号
  ([`clinosim.modules.identity`](../identity/README.md))、encounter
  simulator 本体 ([`clinosim.simulator`](../../simulator/))、
  小児 visit emit (本モジュールは
  [`clinosim.modules.pediatric.calendar.generate_pediatric_events`](../pediatric/README.md)
  に委譲)。

## Public API

```python
from clinosim.modules.population import (
    PersonRecord,                       # dataclass (types.population)
    HospitalizationSummary,             # dataclass (types.population)
    LifeEvent,                          # dataclass (types.population)
    generate_population,                # (size, country, rng, base_year=2024, demo=None) -> PopulationRegistry
    generate_monthly_events,            # (registry, year, month, rng, country="US", demo=None) -> list[LifeEvent]
    generate_healthcare_calendar,       # (registry, year, country, rng) -> list[LifeEvent]
)
```

再 export されない内部 helper (把握しておく価値のあるもの):
`engine.py` の `Household` + `PopulationRegistry` dataclass、
慢性 prevalence 解析用の frozen `ChronicConditionSpec`、Rh factor
SHA-256 導出 `_derive_rh_factor(person_id, country)` (Issue #795
pattern)、多数の `_sample_*` helper (`_sample_age_band`,
`_sex_ratio_male_probability`, `_sample_blood_type`,
`_sample_surname`, `_sample_given_name`, `_sample_occupation`)。

## Cohort skew vs sampled population

`demographics.yaml → age_distribution` は **合成 general population の入力
サンプリング target** であり、各国の Census (US Census Bureau 2020 / 総務省
統計局 2020 国勢調査) に一致させている。**emit される患者コホートの target
ではない**。

パイプラインは 2 段階で「受診しなかった人」を drop する:

1. **`care_seeking` 閾値**: person 単位 random draw (高齢ほど受診しやすい) —
   window 内で医療機関に触れなかった person を除外
2. **Encounter emission gate**: window 内で encounter 数 0 の person は
   Patient.ndjson から除外

複合効果として、emit される患者は高齢に偏る。JP p=1000 s=42 では 65+ 比率
実測 ~48% vs サンプリング母集団 30%。これは MHLW 患者調査 2020 (65+ ≈ 56%)
に近く、国勢調査 (65+ ≈ 30%) とは意図的に離れている。

**`age_distribution` を出力コホート合わせに書き換えないこと。** 一般人口
サンプリング contract は寿命 / comorbidity 相関 / 季節性発症リスク等の
demographics 条件付き計算が Census 形状の入力を前提としているため、下流で
壊れる。コホート skew を audit するなら 患者調査 (病院受診者統計) と比較
すべきで、国勢調査 (一般人口) ではない。

比較 metric は
[`scripts/audit_realworld_stats_jp.py`](../../../scripts/audit_realworld_stats_jp.py)
を参照。

## Marginal-preserving prevalence (B-3)

各 locale の `demographics.yaml` の `chronic_prevalence[code][band]` は
**sampled synthetic population (パイプライン入力) における target
marginal prevalence** の意味を持つ。per-patient conditional probability
ではない。EMIT される患者コホート (下流 care-seeking + encounter emission
filter 後) は sampled population より sicker 側に skew する — これは意図
された挙動で、上の "Cohort skew vs sampled population" 節を参照。

engine は各 chronic code を次のように sampling する:

```
scaled_base = base_prev / E[compound multiplier over (age, sex)]
final_prev  = min(1, scaled_base * corr_mult(patient) * life_mult(patient))
```

`E[compound]` は当該 (age × sex) 集団で code に対する fresh draw が体験する
comorbidity correlation multiplier と lifestyle (BMI + smoking) multiplier
の population-average 積。BMI × smoking × prior-code sampling の独立性から
`E[corr_mult(patient) * life_mult(patient)] ≈ E[compound]` が成立するため、
population marginal は `base_prev` に収束し、multiplier は「どの患者が
その condition を得るか」の shape 決定にのみ働く。

Helper 関数 (すべて pure、新規 tunable 定数なし。yaml 側の
`chronic_prevalence` / `comorbidity_correlations` /
`lifestyle_risk_multipliers` / `physiology.bmi` /
`lifestyle_distribution.smoking` からのみ導出):

- `_target_prev_at_age(spec, age)` — `age` を含む band を返す、無ければ 0。
- `_bmi_category_probabilities(demo, sex_key)` — `(mean, std)` の解析的
  Normal CDF を `overweight` / `obese` 閾値に当てる。
- `_smoking_status_probabilities(demo, sex_key, age)` — yaml 分布を正規化。
  `LEGAL_ADULT_AGE` 未満は `{never:1.0}` に固定。
- `_expected_lifestyle_multiplier(demo, code, sex_key, age)` —
  `E[bmi_mult] * E[smoking_mult]`。
- `_expected_comorbidity_multiplier(chronic_data, code, age, sex,
  comorbidity_cfg)` — `chronic_data` iteration 順の先行 code に対して
  `Π (1 + P_prior * (m_prior→code - 1))`。

これは以前の「Issue #739 で base_prev を multiplier 圧縮のために逆比例縮小
する」対症療法 workaround を置き換える。既存の #739 downscale は新エンジン
下では過補償になるため、follow-up 再校正 PR で revert される (B-3 phase 2)。

## 決定論

- **`ENRICHER_SEED_OFFSETS` にサブ seed 未登録**。本モジュールは
  pipeline の頭。CLI が master seed を供給し、下流の enricher
  各々が master に対して自身のサブ seed を導出する (AD-16)。population
  サンプリングは master `rng` を直接使う。
- **RNG-neutral な additive 導出**: 新規の per-person field
  (`rh_factor`、および今後同 pattern に従う生物学属性) は
  `sha256(person_id + salt)` から計算し master RNG を消費しない。
  これにより RNG-neutral field 追加時に memoize snapshot が
  byte-identical に保たれる (Issue #795 pattern、age / sex 依存で
  RNG サンプリングが必須の属性とは対照的)。
- 月次 event / calendar は決定論的 person / 疾患 / 順序で `rng` を
  逐次消費する — YAML 編集で incidence を追加 / 並替えると下流 stream
  位置が shift しうる。これは想定挙動で、caller 境界で明示する。

## 依存

- `clinosim.modules._shared` — `is_jp`, `normalize_probabilities`
  (全 callsite で `fallback="raise"`)。
- `clinosim.modules.disease.protocol` — acute event dispatch 用の
  `load_disease_protocol`。
- `clinosim.modules.disease.severity` — 入院判断時の
  `sample_severity`。
- `clinosim.modules.population._household_thresholds` — 世帯サイズ
  分布、住所 / 電話桁範囲、apartment 確率、旧姓保持確率、
  血液型 default 分布。
- `clinosim.modules.population._population_thresholds` — BMI /
  身長 default + clamp、care-seeking threshold default、喫煙 /
  飲酒 fallback ラベル + probs、携帯電話最低年齢。
- `clinosim.modules.population._population_workflow_thresholds` —
  screening 確率 + 最低年齢 (mammography / colonoscopy /
  diabetic retinopathy / flu)、慢性 visit 月 cap、event 日 jitter
  範囲、unknown-condition rate parameter、mixed-conditions 確率、
  prior-hospitalization recurrence 乗数。
- `clinosim.locale.loader` — `load_demographics`, `load_names`,
  `load_addresses`, `load_naming_rules`, `load_chronic_followup`。
- `clinosim.modules.pediatric.calendar` — `generate_healthcare_calendar`
  内で遅延 import される `generate_pediatric_events`。
- `clinosim.types.population` — `PersonRecord`,
  `HospitalizationSummary`, `LifeEvent`。
- `hashlib.sha256` — RNG-neutral な per-person 導出。
- `numpy` — `np.random.Generator`。

## 定数と設定

- **Threshold 表** は 3 兄弟 `_*_thresholds.py` に存在
  (Issue #637 sweep)。以前 inline だった scalar を全て lift し
  用途 + 出典 docstring を付与:
  - `_household_thresholds.py`: 世帯 + 住所 + 電話 shape (US + JP)、
    命名規則、血液型 default 分布。
  - `_population_thresholds.py`: BMI / 身長 / care-seeking default、
    喫煙 + 飲酒 fallback 分布、`MOBILE_PHONE_MIN_AGE`、
    `HEIGHT_SHRINKAGE_AGE_THRESHOLD`。
  - `_population_workflow_thresholds.py`: 月次 event 日 jitter、
    慢性 visit + screening スケジュール、`LEGAL_ADULT_AGE`、
    unknown-condition サンプリング、`PRIOR_HOSPITALIZATION_RECURRENCE_MULTIPLIER`。
- **locale-driven data** (本モジュールには `reference_data/` 無し —
  データ相当は全て `clinosim/locale/` 下):
  - `demographics.yaml` — 年齢分布、性比、慢性 prevalence (任意
    `sex` filter)、疾患 incidence、季節 modifier、疾患リスク乗数、
    lifestyle リスク乗数、unknown-condition pattern。
  - `names.yaml`, `addresses.yaml`, `naming_rules.yaml` — 人物 /
    世帯の姓名 + 住所 pool。
  - `chronic_followup.yaml` (locale-shared) — 疾患ごとの慢性 visit
    follow-up cadence。

## ディレクトリ構造

```
clinosim/modules/population/
  __init__.py                          Person/Life/Hospitalization + 3 generator を再 export
  engine.py                            registry 構築 + 月次 event + calendar
  _household_thresholds.py             世帯 / 住所 / 電話 / 命名 default
  _population_thresholds.py            体格 + lifestyle + care-seeking default
  _population_workflow_thresholds.py   screening / 慢性 visit / event 日 スケジュール
  SPEC.md                              拡張設計参考 (runtime data ではない)
```

**`reference_data/` / `enricher.py` / `audit.py` は存在しない** —
data source は locale YAML、pipeline 頭は
`register_builtin_enrichers` ではなく simulator が直接呼ぶ。

## Enricher 配線

該当なし — 本モジュールはシミュレーション pipeline の頭であり
enricher ではない。`register_builtin_enrichers` に登録なく、
`ENRICHER_SEED_OFFSETS` にも seed 未登録。simulator boot が
CLI master RNG で `generate_population`, `generate_monthly_events`,
`generate_healthcare_calendar` を直接呼び出す。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Simulator boot | [`clinosim/simulator/engine.py`](../../simulator/engine.py) | `generate_population` を 1 回、次に年ごとに `generate_monthly_events` + `generate_healthcare_calendar` を呼び出す。 |
| Inpatient / discharge encounter | [`clinosim/simulator/{inpatient,discharge_gate,unknown_condition}.py`](../../simulator/) | `PersonRecord` + `HospitalizationSummary` の field (慢性疾患、既往入院、care-seeking threshold、lifestyle) を read。 |
| Enumeration | [`clinosim/simulator/enumerate.py`](../../simulator/enumerate.py) | `PopulationRegistry` を walk して per-person iterator を構築。 |
| CLI single-encounter driver | [`clinosim/simulator/cli_test_encounter.py`](../../simulator/cli_test_encounter.py) | smoke run で `generate_population(1, …)` を使用。 |
| Pediatric 統合 | [`clinosim/modules/pediatric/calendar.py`](../pediatric/calendar.py) | `generate_healthcare_calendar` から (person, year) ごとに呼ばれて小児 visit を追加。 |

## テスト

```bash
pytest tests/unit -k population -q
pytest tests/integration -k population -q
```

個別ファイル:

- [`tests/unit/test_population_types.py`](../../../tests/unit/test_population_types.py)
  — dataclass shape。
- [`tests/unit/test_population_demographics.py`](../../../tests/unit/test_population_demographics.py)
  — demographic sampler 不変量。
- [`tests/unit/test_population_engine_sampling.py`](../../../tests/unit/test_population_engine_sampling.py)
  — 慢性 prevalence + baseline vitals サンプリング。
- [`tests/unit/test_population_minor_smoking_alcohol_gate.py`](../../../tests/unit/test_population_minor_smoking_alcohol_gate.py)
  — `LEGAL_ADULT_AGE` gate の喫煙 / 飲酒 サンプリング。
- [`tests/unit/test_population_occupation_age_gate.py`](../../../tests/unit/test_population_occupation_age_gate.py)
  — 職業サンプリングが `MIXED_CONDITIONS_MIN_AGE_DEFAULT` +
  OCCUPATION_MISMATCH fallback を守る。
- [`tests/unit/test_cli_population_no_sentinel.py`](../../../tests/unit/test_cli_population_no_sentinel.py)
  — CLI が sentinel leak を出さない。
- [`tests/integration/test_population_severity_source.py`](../../../tests/integration/test_population_severity_source.py)
  — 重症度が `clinosim.modules.disease.severity` 経由で取得され、
  ここに hard-code されていない。
- [`tests/integration/test_bug_d_explicit_population.py`](../../../tests/integration/test_bug_d_explicit_population.py)
  — explicit-population regression guard。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
