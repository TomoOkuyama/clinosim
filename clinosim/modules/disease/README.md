# clinosim.modules.disease — Disease Protocol Module

## 目的

clinosim における **入院プロトコルの単一情報源** を提供する。 各プロトコルは 1 本の YAML ファイルとして `reference_data/` に置かれ、 Pydantic モデル (`DiseaseProtocol`) によってロード時に検証される。

**注意**: モジュール名は "disease" だが、実態は **入院プロトコル全般** を格納する。 内因性疾患（肺炎、心不全等）に加え、 外傷（交通事故、骨折）、 労災（手部挫滅、高所墜落、感電、工業熱傷）なども同じ仕組みでモデル化している。 外来/ED 向けの短期プロトコルは `encounter/reference_data/` 側に分離している。

**新しいプロトコルを追加する = 新しい YAML を追加する** — エンジンコード変更なし。

1 つの疾患 YAML が定義するもの:

- 疾患疫学 (年齢・性別別罹患率、季節性、併存症リスク倍率)
- 重症度分布 (mild / moderate / severe)
- 提示症状と主訴
- 病態生理学的初期インパクト (inflammation, renal, cardiac ...)
- 日次の臨床経過アーキタイプ (smooth recovery / treatment resistant 等)
- 合併症 (発生率、カスケード、対応アクション)
- 検査・画像・処方オーダープロトコル
- 鑑別・尤度比・コード進展
- 薬剤プロトコル (country × 役割: 初期治療、代替、エスカレーション、退院処方)
- 期待在院日数 (target LOS) と 退院時アウトカムベンチマーク

現在 **32 疾患** が実装されている（内因性疾患 + 外傷 + 労災）。

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **YAML is the truth** | 疾患定義はすべて YAML。ロジック分岐を Python に書かない |
| 2 | **Auto-discovery** | `reference_data/` にファイルを置けば即使える。レジストリ不要 |
| 3 | **Pydantic validated** | ロード時に型検証。スキーマ崩れは即失敗 |
| 4 | **Country-scoped sections** | 罹患率・薬剤・LOS・ベンチマークは `japan:` / `us:` でスコープ |
| 5 | **Cite sources** | YAML 冒頭コメントにガイドライン出典 (UpToDate, Harrison's, JAMA, NEJM, 厚労省) |
| 6 | **Multi-language complaint** | `chief_complaint` は文字列 または `{en, ja}` 辞書 |
| 7 | **Condition types (AD-28)** | `known_disease` / `mixed` / `unknown` — 診断フィードバックを許容 |

## ディレクトリ構造

```
clinosim/modules/disease/
├── __init__.py
├── protocol.py          # DiseaseProtocol (Pydantic) + load_disease_protocol()
├── README.md
├── SPEC.md
└── reference_data/      # 疾患 YAML 32本
    ├── bacterial_pneumonia.yaml
    ├── crush_injury_hand.yaml     # 労災 (AD-45)
    ├── hip_fracture.yaml
    ├── sepsis.yaml
    ├── ... (計 32 ファイル)
```

### 実装済み疾患 (32)

Infectious: `bacterial_pneumonia`, `aspiration_pneumonia`, `urinary_tract_infection`, `cellulitis`, `sepsis`, `influenza`
Cardiac: `heart_failure_exacerbation`, `acute_mi`, `atrial_fibrillation_rvr`
Pulmonary: `copd_exacerbation`, `asthma_exacerbation`, `pulmonary_embolism`
Neurologic: `cerebral_infarction`, `hemorrhagic_stroke`, `subdural_hematoma`
GI/Hepatic: `gi_bleeding`, `acute_pancreatitis`, `acute_cholecystitis`, `acute_appendicitis`, `ileus`, `liver_cirrhosis_decompensated`
Renal/Metabolic: `acute_kidney_injury`, `diabetic_ketoacidosis`
Trauma/Ortho: `hip_fracture`, `vertebral_compression_fracture`, `wrist_fracture_surgical`, `traffic_accident_severe`
Vascular: `deep_vein_thrombosis`
**Occupational (労災, AD-45)**: `crush_injury_hand`, `industrial_burn_severe`, `fall_from_height`, `electrical_injury`

労災疾患は `demographics.yaml` の `occupation_risk_multipliers` と連動し、製造業・建設業で発生率が増加する。対応する ED 疾患 (`eye_foreign_body`, `chemical_exposure`) は `encounter/reference_data/` に格納。

## 権威ソース

各 YAML の罹患率・ベンチマーク・薬剤選択は以下の臨床ガイドラインやエビデンスに基づく:

| 領域 | 主ソース |
|---|---|
| **一般臨床** | [UpToDate](https://www.uptodate.com/), Harrison's Principles of Internal Medicine |
| **NEJM / JAMA** | 主要エビデンス論文 |
| **呼吸器感染症** | IDSA/ATS Guidelines for CAP, GOLD Report (COPD) |
| **循環器** | ACC/AHA Guidelines, ESC Guidelines, [日本循環器学会 JCS ガイドライン](https://www.j-circ.or.jp/) |
| **脳血管** | AHA/ASA Stroke Guidelines, 日本脳卒中学会 ガイドライン |
| **感染症** | IDSA Guidelines, 日本感染症学会 |
| **糖尿病** | ADA Standards of Care, 日本糖尿病学会 |
| **腎臓病** | KDIGO Guidelines |
| **外科** | [日本外科学会 ガイドライン](https://www.jssoc.or.jp/) |
| **疫学** | 厚生労働省 患者調査 / NDB, CDC WONDER, [US HCUP NRD](https://www.hcup-us.ahrq.gov/) |

各 YAML ファイル冒頭コメントに該当疾患の出典を明記することを推奨。

## API リファレンス

### `DiseaseProtocol` (Pydantic BaseModel)

`protocol.py:15` に定義される。YAML ロード後のランタイム型。

```python
class DiseaseProtocol(BaseModel):
    disease_id: str                                  # snake_case ID
    icd_codes: dict[str, Any]                        # {primary, variants[]}
    incidence: dict[str, Any]                        # {japan, us, risk_multipliers, seasonal_curve, ...}
    severity: dict[str, Any]                         # {distribution, modifiers}
    presenting_symptoms: list[dict[str, Any]] = []
    course_archetypes: dict[str, Any] = {}           # {archetype_name: {probability, trajectory, triggers}}
    initial_state_impact: dict[str, dict[str, float]] = {}  # {severity: {state_var: delta}}
    diagnostic: dict[str, Any] = {}
    order_protocols: dict[str, Any] = {}
    target_los: dict[str, Any] = {}
    complications: list[dict[str, Any]] = []
    readmission: dict[str, Any] = {}
    likelihood_ratios: dict[str, Any] = {}
    expected_lab_distributions: dict[str, Any] = {}
    expected_vital_distributions: dict[str, Any] = {}
    drugs: dict[str, Any] = {}
    drug_interactions: list[dict[str, Any]] = []
    reference_ranges: dict[str, Any] = {}
    outcome_benchmarks: dict[str, Any] = {}

    # Metadata (eliminates hardcoding in simulator)
    chief_complaint: str | dict[str, str] = ""       # "..." or {en, ja}
    department: str = "internal_medicine"
    encounter_type: str = "medical"                  # "medical" | "surgical" | "trauma"
    requires_surgery: bool = False
    minimum_severity: str | None = None              # e.g. "moderate" for fractures
    readmission_eligible: bool = True                # False for surgical
```

### `load_disease_protocol(disease_id: str) -> DiseaseProtocol`

指定された疾患 ID から YAML をロードして Pydantic 検証済みのプロトコルを返す。

```python
from clinosim.modules.disease.protocol import load_disease_protocol

protocol = load_disease_protocol("bacterial_pneumonia")
protocol.disease_id                       # "bacterial_pneumonia"
protocol.icd_codes["primary"]             # "J18.9"
protocol.severity["distribution"]         # {"mild": 0.6, ...}
protocol.course_archetypes["smooth_recovery"]["probability"]  # 0.70
protocol.outcome_benchmarks["japan"]["median_los"]            # 7
```

**Raises**: `FileNotFoundError` — `reference_data/<disease_id>.yaml` が存在しない場合
**Raises**: `pydantic.ValidationError` — YAML スキーマが `DiseaseProtocol` に一致しない場合

## YAML スキーマ概要

1 本の疾患 YAML は以下のセクションから構成される。詳細は `bacterial_pneumonia.yaml` を参照。

### Metadata セクション (必須)

```yaml
disease_id: urinary_tract_infection
chief_complaint:
  en: "Fever, dysuria, flank pain"
  ja: "発熱、排尿時痛、側腹部痛"
department: internal_medicine
encounter_type: medical                 # medical | surgical | trauma
requires_surgery: false
minimum_severity: null                  # or "moderate" to force hospitalization
readmission_eligible: true
```

### `icd_codes` (必須)

```yaml
icd_codes:
  primary: "N39.0"
  variants:
    - {code: "N30.0", name: "Acute cystitis",       probability: 0.60}
    - {code: "N10",   name: "Acute pyelonephritis", probability: 0.30}
    - {code: "N39.0", name: "UTI, unspecified",     probability: 0.10}
```

### `incidence` (必須)

10万人年あたり発症率。age × sex 別、国別。

```yaml
incidence:
  japan:
    "0-14":  {M:  50, F:  200}
    "15-44": {M:  20, F:  500}
    "45-64": {M: 100, F:  300}
    "65-74": {M: 200, F:  600}
    "75+":   {M: 400, F: 1000}
  us:
    # ... 同じ構造
  risk_multipliers:
    - {condition: "E11.9", multiplier: 2.0}    # 糖尿病
    - {condition: "N18",   multiplier: 1.5}    # CKD
  seasonal_curve:
    1: 1.0  # month → multiplier
    # ... 12 months
```

### `severity` (必須)

```yaml
severity:
  distribution: {mild: 0.60, moderate: 0.30, severe: 0.10}
  modifiers:
    - {condition: "age_over_75", severe_multiplier: 1.5}
    - {condition: "immunosuppressed", severe_multiplier: 2.0}
```

### `initial_state_impact` (必須)

発症時の病態生理学的変化量。physiology モジュールが内部状態を更新する際の出発点。

```yaml
initial_state_impact:
  mild:     {inflammation_level: 0.15}
  moderate: {inflammation_level: 0.30, renal_function: -0.05, volume_status: -0.10}
  severe:   {inflammation_level: 0.50, renal_function: -0.15, perfusion_status: -0.10}
```

利用可能な state 変数: `inflammation_level`, `renal_function`, `cardiac_function`, `hepatic_function`, `anemia_level`, `coagulation_status`, `volume_status`, `perfusion_status`, `ph_status`。

### `course_archetypes`

日次経過アーキタイプ。 確率つきの複数シナリオを持ち、simulator はそのうち 1 つをサンプリングして患者に適用する。

```yaml
course_archetypes:
  smooth_recovery:
    probability: 0.70
    description: "Responds well to antibiotics"
    trajectory:
      inflammation_level: {0: 0.03, 1: -0.05, 3: -0.08, 5: -0.05, 7: -0.03}
      renal_function:     {0: 0.00, 2:  0.01, 5:  0.01}
    triggers:
      - day: 3
        condition: "inflammation_level > 0.3"
        actions: ["switch_antibiotic", "order_urine_culture"]

  treatment_resistant:
    probability: 0.15
    trajectory: { ... }
    triggers: [ ... ]
```

エンジンは定義された日の間を線形補間する。 Day 0 は入院日。Positive = worsening, Negative = improving。

### `complications`

```yaml
complications:
  - name: "c_diff_colitis"
    probability_per_day: 0.005
    onset_day_range: [5, 21]
    risk_factors:
      - {condition: "antibiotic_duration_over_7_days", multiplier: 2.0}
    state_impact:
      inflammation_level: 0.10
      volume_status: -0.10
    detection: {test: "c_diff_toxin", finding: "positive"}
    actions: ["stop_offending_antibiotic", "start_oral_vancomycin"]
    cascade: []   # このイベントが誘発し得る子合併症
  - name: "dvt"
    cascade: ["pulmonary_embolism"]
  - name: "pulmonary_embolism"
    parent_complication: "dvt"
    probability_given_parent: 0.10
```

### `drugs`

Country × 役割でネスト。

```yaml
drugs:
  first_line:
    japan:
      - {drug: "Levofloxacin", code_yj: "6241017", dose: "500mg IV daily"}
    us:
      - {drug: "Ciprofloxacin", code_rxnorm: "2551", dose: "400mg IV q12h"}
  alternative_penicillin_allergy:
    japan:
      - {drug: "Ceftriaxone", dose: "1g IV daily"}
  escalation:
    japan:
      - {drug: "Meropenem", dose: "1g IV q8h", indication: "resistant_organism"}
  discharge_oral:
    japan:
      - {drug: "Levofloxacin", dose: "500mg PO daily", duration_days: 7}
```

### `target_los` と `outcome_benchmarks`

```yaml
target_los:
  japan:
    mild: null
    moderate: {mean:  7, sd: 2, min: 4, max: 14}
    severe:   {mean: 14, sd: 4, min: 7, max: 28}
  us:
    moderate: {mean: 3, sd: 1, min: 2, max:  7}
    severe:   {mean: 6, sd: 2, min: 3, max: 14}

outcome_benchmarks:
  japan:
    median_los: 7
    in_hospital_mortality: 0.02
    thirty_day_readmission: 0.10
    mean_age_admitted: 68
    female_ratio: 0.65
```

`outcome_benchmarks` は validator モジュール (`clinosim.modules.validator.benchmarks`) が参照し、 大規模生成データのリアリティ検証に使う。

## 使用例

### プロトコル読み込みと検査

```python
from clinosim.modules.disease.protocol import load_disease_protocol

p = load_disease_protocol("heart_failure_exacerbation")
print(f"Primary ICD: {p.icd_codes['primary']}")
print(f"Archetypes: {list(p.course_archetypes.keys())}")
print(f"Expected LOS (JP moderate): "
      f"{p.target_los['japan']['moderate']['mean']} days")
```

### Simulator 内での使い方

```python
# simulator.py の中
protocol = load_disease_protocol(condition.disease_id)

# 重症度サンプリング
sev = rng.choice(
    list(protocol.severity["distribution"].keys()),
    p=list(protocol.severity["distribution"].values()),
)

# 初期 physiology インパクト適用
for state_var, delta in protocol.initial_state_impact[sev].items():
    patient_state[state_var] += delta

# アーキタイプ選択
arche_name = rng.choice(
    list(protocol.course_archetypes.keys()),
    p=[a["probability"] for a in protocol.course_archetypes.values()],
)

# 薬剤選択 (country + allergy に応じて)
drug_list = protocol.drugs["first_line"][country.lower()]
```

### Forced scenario (CI / dev 用)

```python
from clinosim.simulator import run_forced
from clinosim.types.config import ForcedScenario

scenario = ForcedScenario(
    disease_id="bacterial_pneumonia",
    count=5,
    severity="severe",
    archetype="treatment_resistant",
)
dataset = run_forced(scenario)
```

### CLI デバッグ

```bash
# 1 患者を詳細出力で生成
clinosim test-disease urinary_tract_infection -n 1 --severity moderate

# アーキタイプ指定
clinosim test-disease bacterial_pneumonia -n 1 --archetype treatment_resistant

# 全疾患一覧
clinosim list-diseases

# ベンチマーク検証
clinosim validate -p 3000
```

## Condition types (AD-28)

全ての受診が単一の identifiable disease に起因するわけではない:

| Type | Ground truth | Clinical diagnosis | 例 |
|---|---|---|---|
| `known_disease` | 単一疾患 YAML | 検査で同定 (通常) | Pneumonia → J13 |
| `mixed` | 複数疾患が重複 | 一方を見落とすことあり | Pneumonia + HF → J18.9 + I50.9 or only J18.9 |
| `unknown` | 疾患 YAML 無 | 検査非特異 | FUO → R50.9 |

Mixed / unknown のサポートにより、 診断フィードバックループ (real workup → plausible miss) を表現できる。

## 拡張方法

### 新しい疾患を追加する (概略)

1. `reference_data/<disease_id>.yaml` を作成 (既存ファイルをテンプレートに)
2. `disease_id`, `icd_codes`, `incidence`, `severity`, `initial_state_impact` の必須 5 セクションを埋める
3. `course_archetypes` を最低 1 つ定義
4. `clinosim/locale/{jp,us}/demographics.yaml > disease_incidence` に該当エントリを追加 (population エンジンが自動発見)
5. `clinosim test-disease <id> -n 1` でデバッグ出力を確認
6. `clinosim validate` でベンチマーク逸脱がないか確認

詳細な step-by-step は以前の README 版 (git log 参照) または `bacterial_pneumonia.yaml` のコメントを参考にすること。

### 新しいアーキタイプを追加する

既存疾患の `course_archetypes:` セクションに 1 エントリ追加するだけ。 `trajectory`, `triggers`, `probability` を定義する。 全アーキタイプの probability は合計 1.0 になるよう調整。

### 新しい合併症を追加する

`complications:` リストに 1 辞書追加。 カスケードが必要なら親合併症側に `cascade: [<child_name>]`, 子側に `parent_complication: <name>` と `probability_given_parent`。

## 依存関係

本モジュールが依存するもの:

| 依存先 | 用途 |
|---|---|
| `pydantic` | `DiseaseProtocol` 検証 |
| `pyyaml` | YAML パース |

**clinosim の他モジュールには依存しない** (純粋データローダー)。

本モジュールに依存する側:

| モジュール | 用途 |
|---|---|
| `clinosim.simulator` | 全シミュレーションの中核 |
| `clinosim.modules.physiology` | `initial_state_impact`, `course_archetypes` 適用 |
| `clinosim.modules.order` | `order_protocols`, `drugs` からオーダー生成 |
| `clinosim.modules.diagnosis` | `likelihood_ratios`, `diagnostic` を使った differential |
| `clinosim.modules.clinical_course` | `course_archetypes`, `complications` 駆動 |
| `clinosim.modules.validator.benchmarks` | `outcome_benchmarks` 検証 |
| `clinosim.modules.population` | `incidence`, `risk_multipliers` 使用 |

## テスト

```bash
# 単体テスト (YAML ロード + Pydantic 検証)
pytest tests/unit/test_disease.py -v

# 全疾患 YAML の構造検証
pytest tests/unit/test_disease_protocols.py -v

# Forced scenario e2e
pytest tests/e2e/test_forced_scenario.py -v

# ベンチマーク検証 (1000 〜 3000 patients)
clinosim validate -p 3000
```

新しい疾患を追加したら:

1. `load_disease_protocol("<new_id>")` が成功すること
2. `clinosim test-disease <new_id> -n 5` で全アーキタイプが動くこと
3. `clinosim validate` で該当 outcome_benchmarks が PASS すること
