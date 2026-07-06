# clinosim.modules.population — 集団生成・ライフイベントエンジン

## 目的

clinosim の **全入院経路の起点**。 病院の catchment area (医療圏) の住民集団を生成し、 そこから月次のライフイベント (疾患発症・慢性疾患増悪・外傷・ED受診・健診受診等) を発生させる。

重要原則: **患者は population から生まれる**。 どの患者も最初に `PersonRecord` として集団に所属し、 ライフイベント (`LifeEvent`) が care-seeking の閾値を超えたとき、 初めて hospital encounter へ変換される。

これにより:

- 疫学 (発症率、年齢分布、季節性) が人口レベルで正しくスケールする
- 同一患者の再入院・外来フォローを一貫した person_id で追跡できる
- 慢性疾患の既往が急性イベントのリスクに連動する
- 健診・ワクチン・検診といった "無症状時の受診" もモデル化できる (外来データを充実)

すべての疫学データ (年齢分布、 血液型、 慢性疾患有病率、 疾患 incidence、 季節性、 リスク倍率) は **locale YAML から読み込む** — コードには疫学値をハードコードしない。

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **Layer 1 = lightweight** | PersonRecord は shallow (名前・住所・慢性疾患等のみ)。 深層医療データは encounter 時に hydrate |
| 2 | **Household 単位の生成** | 世帯単位で住所・姓を共有 (国別 surname rule) |
| 3 | **データ駆動の疫学** | incidence rate は locale `demographics.yaml` の `disease_incidence` から |
| 4 | **Care-seeking threshold** | 個人ごとの受診閾値 `care_seeking_threshold` (normal(0.30, 0.12)) |
| 5 | **月次バッチ** | ライフイベントは年×月のループで生成、 timestamp は月内ランダム |
| 6 | **再入院追跡** | `hospitalization_history` に `HospitalizationSummary` を蓄積、 再発率を 1.5 倍に |
| 7 | **決定論的** | すべて `rng: np.random.Generator` 経由 |
| 8 | **重症度は疾患 YAML から** | 重症度は `disease` モジュール(`disease.severity.sample_severity`)経由で疾患 YAML の `severity.distribution` × `modifiers` から抽選(FP-SEV-MODEL, c2)。旧 locale `severity_beta`/`severity_minimum` は撤廃 |

## 依存関係

`types` / `codes` / `locale` に加え、**`disease`**(`disease.protocol.load_disease_protocol` + `disease.severity.sample_severity`)に依存する。ライフイベントの重症度を疾患 YAML の `severity` ブロックから導出するため(FP-SEV-MODEL, c2、2026-07-06)。

## API リファレンス

### `generate_population(size, country, rng, base_year=2024) -> PopulationRegistry`

指定サイズの住民集団を生成する。

```python
from clinosim.modules.population.engine import generate_population
import numpy as np

rng = np.random.default_rng(42)
registry = generate_population(size=10_000, country="JP", rng=rng, base_year=2024)
print(f"Generated {registry.total_persons} persons in {len(registry.households)} households")
```

**生成ステップ**:

1. Locale demographics から年齢分布・血液型分布・慢性疾患有病率を読み込み
2. `size / average_household_size` 世帯を作成
3. 各世帯で住所を生成 (都市・州・番地・アパート名)
4. 世帯電話 (有線は確率付き)、 世帯姓 (surname rule 依存)
5. 各世帯メンバーを生成:
   - 年齢 (年齢分布からサンプル)
   - 性別 (M:F = 49:51)
   - 血液型 (国別分布)
   - 姓 (shared / mostly_shared / not_shared rule)
   - 名 (性別依存の weighted sampling)
   - 慢性疾患 (年齢別有病率 rng で割り付け、 平均 16 種のうち該当分)
   - 携帯電話 (15 歳以上)
   - 職業 (`_sample_occupation()` — 年齢・国の労働統計ベース分布から割当、AD-45)
     - age < 15 → student, age >= 65 → retired, 15-21 → 70% student / 30% working
     - working_age: `demographics.yaml` の `occupation_distribution.working_age` から weighted choice
   - care_seeking_threshold = `clamp(normal(0.30, 0.12), 0.05, 0.90)`

### `generate_monthly_events(registry, year, month, rng, country="US") -> list[LifeEvent]`

1 ヶ月分の急性疾患・外傷・未知症候のライフイベントを生成する。

```python
from clinosim.modules.population.engine import generate_monthly_events

events = generate_monthly_events(registry, year=2024, month=3, rng=rng, country="US")
print(f"March 2024: {len(events)} life events")
hospital_events = [e for e in events if e.requires_hospital]
```

**生成ロジック**:

1. `demographics.yaml` の `disease_incidence` を反復、 各疾患について:
   - 患者年齢で rate をルックアップ
   - 性別比で補正
   - 月次 rate = (年率 / 100,000) / 12 に換算
   - 季節性 modifier を乗算 (月ごと)
   - 慢性疾患のリスク倍率 (`disease_risk_multipliers`)
   - 既往歴: 同疾患の過去 hospitalization があれば ×1.5 (recurrence)
   - **職業リスク倍率** (`occupation_risk_multipliers`): 労災疾患に対し、本人の `occupation` でリスク増減
     - 例: crush_injury_hand × 6.0 (manufacturing), × 3.0 (construction), × 0.2 (default)
   - `prerequisite_condition` チェック (例: HF exacerbation は I50 必須)
2. `rng.random() < rate` なら発症
3. 重症度は beta 分布 (`severity_beta: [alpha, beta]`)、 最低値 `severity_minimum`
4. 入院判定:
   - `always_hospitalize: true` なら強制入院
   - そうでなければ `severity > person.care_seeking_threshold × age_modifier × flat_modifier`
5. **Unknown conditions** (非典型主訴): 40 歳以上で ~0.008%/月 × 年齢係数、 4 種の pattern (fever_unknown, weight_loss, malaise, elevated_markers)
6. **Mixed conditions** (dual pathology): 70 歳以上 & 慢性疾患 2 つ以上 & 入院必要 → 18% の確率で `condition_type = "mixed"` へ格上げ

### `generate_healthcare_calendar(registry, year, country, rng) -> list[LifeEvent]`

1 年分の **計画的受診** (慢性疾患フォロー、健診、ワクチン、検診) を生成する。 急性疾患とは別に発生する。

```python
from clinosim.modules.population.engine import generate_healthcare_calendar

calendar = generate_healthcare_calendar(registry, year=2024, country="JP", rng=rng)
# → 外来 (chronic_visit, health_screening) イベントが多数
```

**生成内容**:

| イベント | 対象 | 頻度 |
|---|---|---|
| 慢性疾患フォロー | 慢性疾患保有者 | 最短フォロー間隔 (例: 3 ヶ月毎)、最大 6 回/年 |
| 年次健診 | 40 歳以上 | 年 1 回 (4-10 月のいずれか) |
| インフルワクチン | 65 歳以上または慢性疾患 2 つ以上 | 50% 接種率、10-12 月 |
| 大腸内視鏡検診 | 50 歳以上 | 年 8% (≒10 年毎) |
| マンモグラフィ | 女性 40 歳以上 | 年 40% |
| 糖尿病網膜症検診 | E11.9 保有者 | 年 60% |

フォロー間隔は `locale/shared/chronic_followup.yaml` から読み込む (ICD code → `follow_up_interval_months`)。

## データ構造

### `PersonRecord` (Layer 1 個人記録)

```python
@dataclass
class PersonRecord:
    person_id: str              # "POP-000001"
    household_id: str           # "HH-000001"
    age: int
    sex: str                    # "M" | "F"
    date_of_birth: date
    family_name: str
    given_name: str
    phonetic: str | None        # JP 用 ふりがな
    blood_type: str             # "A" | "B" | "O" | "AB"
    # 住所・連絡 (世帯共通)
    postal_code: str
    state: str                  # prefecture (JP) / state (US)
    city: str
    address_line: str
    phone_home: str
    phone_mobile: str
    # 医療
    chronic_conditions: list[str]             # ICD-10 コード
    current_medications: list[str]
    # 職業 (AD-45) — 労災リスク倍率と FHIR Observation に使用
    occupation: str = "other"                 # "manufacturing" | "construction" | "office" | ... (12 categories)
    is_alive: bool = True
    care_seeking_threshold: float = 0.3
    has_visited_hospital: bool = False
    visit_count: int = 0
    last_discharge_date: date | None = None
    last_encounter_id: str | None = None
    last_disease_id: str | None = None
    hospitalization_history: list[HospitalizationSummary]
```

### `LifeEvent`

```python
@dataclass
class LifeEvent:
    person_id: str
    event_type: str         # "acute_disease_onset" | "chronic_exacerbation" | "trauma" |
                            # "unknown_condition" | "chronic_visit" | "health_screening" |
                            # "ed_visit" | "followup"
    timestamp: date
    severity: float = 0.5
    condition_type: str = "known_disease"
                            # "known_disease" | "mixed" | "unknown" |
                            # "chronic_followup" | "screening" | "ed_visit"
    disease_id: str = ""
    encounter_type: str = "inpatient"  # "inpatient" | "outpatient" | "emergency"
    requires_hospital: bool = False
    is_readmission: bool = False
    prior_encounter_id: str | None = None
    readmission_number: int = 0
    protocol_source: str = ""      # このイベントの protocol YAML 参照
```

### `HospitalizationSummary` (再入院追跡)

```python
@dataclass
class HospitalizationSummary:
    encounter_id: str
    disease_id: str
    admission_date: date
    discharge_date: date
    los_days: int
    outcome: str                        # "discharged" | "deceased" | "transferred"
    discharge_diagnoses: list[str]      # ICD codes
    discharge_medications: list[str]
    residual_inflammation: float = 0.0  # state at discharge
    residual_renal: float = 1.0
    was_readmission: bool = False
```

### `Household` / `PopulationRegistry`

```python
@dataclass
class Household:
    household_id: str
    members: list[PersonRecord]
    region: str = "urban"

@dataclass
class PopulationRegistry:
    households: list[Household]
    persons: dict[str, PersonRecord]

    def get_person(self, person_id: str) -> PersonRecord | None: ...
    @property
    def total_persons(self) -> int: ...
```

## 使用例: 1 年分のシミュレーション

```python
from clinosim.modules.population.engine import (
    generate_population, generate_monthly_events, generate_healthcare_calendar,
)
import numpy as np

rng = np.random.default_rng(seed=20240101)

# 1. Population creation (once at simulation start)
registry = generate_population(size=50_000, country="JP", rng=rng, base_year=2024)

# 2. Yearly planned healthcare calendar
calendar = generate_healthcare_calendar(registry, year=2024, country="JP", rng=rng)

# 3. Monthly acute events
all_events = list(calendar)
for month in range(1, 13):
    events = generate_monthly_events(registry, year=2024, month=month, rng=rng, country="JP")
    all_events.extend(events)

# 4. Route to encounter module
for event in sorted(all_events, key=lambda e: e.timestamp):
    if event.requires_hospital:
        encounter = create_inpatient_encounter(registry.get_person(event.person_id), event)
    elif event.encounter_type == "outpatient":
        encounter = create_outpatient_encounter(...)
```

## 新しい国を追加する

1. `locale/<country>/demographics.yaml` を作成:
   - `average_household_size`
   - `age_distribution` (例: `"0-14": 0.12`)
   - `blood_type`
   - `chronic_prevalence` (ICD → 年齢帯 → 有病率)
   - `disease_incidence` (per disease: `age_rates`, `sex_ratio_female`, `severity_beta`, ...)
   - `seasonal_modifiers` (月次)
   - `disease_risk_multipliers` (chronic code → 倍率)
   - `unknown_conditions`, `mixed_conditions` 設定
2. `locale/<country>/names.yaml` (weighted 姓・名)
3. `locale/<country>/addresses.yaml` (都市・通り・アパート名)
4. `locale/shared/naming_rules.yaml` に surname rule を追加
5. `locale/loader.py` の `_COUNTRY_DIR_MAP` に追加
6. **コード変更不要** — すべて YAML 駆動

## 新しい疾患をライフイベント生成に追加する

1. `demographics.yaml` の `disease_incidence` に追加:
   ```yaml
   disease_incidence:
     my_new_disease:
       age_rates: {0: 10, 45: 50, 65: 200}    # per 100k/year (年齢閾値 → 年率)
       sex_ratio_female: 0.8                    # 女性は男性の0.8倍
       severity_beta: [2, 3]                    # Beta(α,β) — 重症度分布
       severity_minimum: null                   # 省略可。設定すると重症度が下回らない
       event_type: "acute_disease_onset"        # | "trauma" | "chronic_exacerbation"
       always_hospitalize: false                # true → severity に関係なく全入院
       prerequisite_condition: null             # ICD コード (例: "I50" — HF 既往が必要)
       hospitalization_threshold_modifier_by_age:
         65: 0.8                                # 65歳以上で閾値 ×0.8 (入院しやすい)
         80: 0.6
   ```

   **全フィールド解説**:
   - `age_rates`: 年齢の閾値をキーとし、値は10万人年あたりの発症率。エンジンは年齢が閾値以上の最大キーの率を使用
   - `sex_ratio_female`: 女性の発症率 = 男性 × この値。1.0 = 同率
   - `severity_beta`: Beta分布のパラメータ [α, β]。α<β で軽症寄り、α>β で重症寄り
   - `event_type`: LifeEvent.event_type に設定される文字列
   - `prerequisite_condition`: 設定すると、この慢性疾患を持つ人のみ発症 (例: HF exacerbation は I50 保有者限定)

2. `seasonal_modifiers` に月別倍率を追加:
   ```yaml
   seasonal_modifiers:
     my_new_disease: {1: 1.2, 2: 1.1, ..., 12: 1.3}  # 月 → 発症率倍率
   ```
3. `disease_risk_multipliers` に慢性疾患リスク倍率を追加:
   ```yaml
   disease_risk_multipliers:
     my_new_disease: {E11.9: 2.0, N18: 1.5}  # ICD → 倍率
   ```
4. 労災疾患なら `occupation_risk_multipliers` も追加:
   ```yaml
   occupation_risk_multipliers:
     my_new_disease:
       manufacturing: 5.0     # 製造業: 5倍
       construction: 3.0
       # 未記載の職業: デフォルト 0.2 倍
   ```
5. 対応する `clinosim/modules/disease/reference_data/<disease>.yaml` を作成 (disease モジュール README 参照)

## 依存関係

- `clinosim.locale.loader` — demographics / names / addresses / chronic_followup
- `clinosim.modules._shared` — `is_jp`, `normalize_probabilities`
- `numpy` — RNG と weighted choice
- **他の domain module への依存なし** (出力 `LifeEvent` を encounter モジュールが consume。
  `_shared` は infra ヘルパーであり domain module ではない)

## Consumers

このモジュールに依存するもの:

| Caller | How | Impact |
|---|---|---|
| `simulator/engine.py` | run_beta で `load_population()` → 全 person 生成 | core (Layer 1 entry) |
| `simulator/cli.py` | CLI 起動時の population orchestration | core |
| `simulator/inpatient.py` | inpatient encounter で PersonRecord 参照 | core |
| `simulator/helpers.py` | `_activate_cached()` で patient activation の前段 | core |
| `modules/patient/activator.py` | Layer 1 (PersonRecord) → Layer 2 (PatientProfile) 変換の入力 | core |
| `tests/unit/test_population_demographics.py` | demographics + chronic_conditions tests | guard |
| `tests/unit/test_population_types.py` | PersonRecord / LifeEvent type tests | guard |
| `tests/unit/test_identity.py` | identity assignment が PersonRecord に格納される確認 | guard |

## テスト

```bash
source .venv/bin/activate && python -m pytest tests/unit/test_population.py -v
```

カバー範囲: 世帯生成、 慢性疾患割り付け、 疫学率計算、 季節性、 surname rule、 再入院倍率、 ヘルスケアカレンダー。

## 権威ソース

- **日本 (JP)**:
  - 厚生労働省「患者調査」 (疾病別受療率) — https://www.mhlw.go.jp/toukei/list/10-20.html
  - 総務省「国勢調査」 (年齢分布・世帯サイズ)
  - 厚生労働省「特定健診・特定保健指導」 (40 歳以上健診の根拠)
- **米国 (US)**:
  - CDC NHIS (National Health Interview Survey) — chronic prevalence
  - CDC WISQARS (injury incidence)
  - HCUP (hospitalization rates)
  - USPSTF 推奨 (screening 年齢・頻度)
- **共通**:
  - GBD (Global Burden of Disease) study — 疾患負荷比較
