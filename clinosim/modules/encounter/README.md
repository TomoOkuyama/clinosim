# clinosim.modules.encounter — Encounter Module

## 目的

clinosim における **全ての患者 × 医療機関 接点 (encounter)** を管理する。 入院、救急外来、定期外来、スクリーニング、術前評価、処置来院、フォローアップ等、 あらゆる受診タイプを YAML プロトコル駆動で扱う。

本モジュールの責務は 2 つ:

1. **Encounter 型プロトコル (ED / 外来条件, 44 件)** の定義と YAML ロード
2. **入院 encounter の基礎的生成** (`create_inpatient_encounter`) と **日次サイクルタイムライン** の生成

疾患 (inpatient disease) 側は `clinosim.modules.disease` が担当し、本モジュールは 外来・救急など **同日退院型の医療接触** を中心にカバーする。

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **YAML is the truth** | 全 ED / 外来条件は YAML。エンジンに条件分岐を書かない |
| 2 | **Auto-discovery** | `reference_data/` にファイルを置けば即認識 (モジュールキャッシュ付き) |
| 3 | **Globally unique IDs** | Encounter ID と Episode ID はシミュレーション全体を通じて一意 |
| 4 | **Multi-language chief complaint** | `chief_complaint` は str または `{en, ja}` 辞書 → `resolve_text` で解決 |
| 5 | **Daily cycle は国ごとに標準化** | 入院病棟の日課 (06:00 vitals → 09:00 rounds → ...) を決定論的に発生 |
| 6 | **Condition vs Disease** | 外来/ED = encounter YAML, 入院疾患 = disease YAML |

## ディレクトリ構造

```
clinosim/modules/encounter/
├── __init__.py
├── engine.py               # create_inpatient_encounter(), generate_daily_cycle(), generate_encounter_timeline()
├── protocol.py             # load_encounter_condition(), load_all_encounter_conditions()
├── README.md
├── SPEC.md
└── reference_data/         # 44 条件 YAML (ED 27 + outpatient 17)
    ├── migraine.yaml
    ├── viral_uri.yaml
    ├── annual_health_screening.yaml
    ├── flu_vaccination.yaml
    ├── ...
```

## カテゴリ別 Encounter 数

| カテゴリ | YAML の場所 | 件数 | 説明 |
|---|---|---|---|
| **入院疾患** | `modules/disease/reference_data/*.yaml` | 28 | 複数日の入院。日次シミュレーション |
| **ED 条件** | `modules/encounter/reference_data/*.yaml` | 27 | 救急受診・同日退院が中心 |
| **外来条件** | `modules/encounter/reference_data/*.yaml` | 17 | スクリーニング・フォロー・ワクチン・術前等 |

ED と外来の合計 **44 件** が encounter モジュール配下にある。

### 代表的な ED 条件 (27 件の一部)

`migraine`, `viral_uri`, `chest_pain_noncardiac`, `minor_laceration`, `ankle_sprain`, `viral_gastroenteritis`, `allergic_reaction_mild`, `low_back_pain`, `uti_uncomplicated`, `food_poisoning`, `anxiety_panic_attack`, `renal_colic`, `syncope`, `vertigo`, `epistaxis`, `shoulder_dislocation`, `elderly_fall`, `rib_fracture`, `wrist_fracture`, `concussion`, `minor_burn`, `animal_bite`, `foreign_body_ingestion`, `urinary_retention`, `asthma_attack_mild`, `abdominal_pain_nonspecific`, `traffic_accident_minor`

### 代表的な外来条件 (17 件の一部)

`annual_health_screening`, `preoperative_assessment`, `colonoscopy_screening`, `upper_endoscopy_diagnostic`, `diabetic_retinopathy_screening`, `cardiac_rehabilitation`, `mammography_screening`, `flu_vaccination`, `wound_care_followup`, `orthopedic_injection`, `new_patient_referral`, `lab_result_consultation`, `prescription_renewal`, `rehabilitation_outpatient`, `smoking_cessation`, `mental_health_followup`, `dialysis_session`

## API リファレンス

### `load_encounter_condition(condition_id: str) -> dict[str, Any]`

1 件の encounter 条件 YAML をロードして dict を返す (`protocol.py:15`)。

```python
from clinosim.modules.encounter.protocol import load_encounter_condition

data = load_encounter_condition("migraine")
data["icd10_code"]              # "G43.909"
data["encounter_type"]          # "emergency"
data["severity_distribution"]   # {"mild": 0.30, "moderate": 0.50, "severe": 0.20}
data["workup"]["labs"]          # [{"test": "WBC", "probability": 0.2}, ...]
```

**Raises**: `FileNotFoundError` — 該当 YAML が `reference_data/` に無い場合

### `load_all_encounter_conditions() -> dict[str, dict[str, Any]]`

`reference_data/*.yaml` を自動発見してロードし、`condition_id → YAML data` の辞書を返す。 モジュールレベルでキャッシュされるため 2 回目以降はファイル IO ゼロ (`protocol.py:24`)。

```python
from clinosim.modules.encounter.protocol import load_all_encounter_conditions

all_conditions = load_all_encounter_conditions()
print(f"Loaded {len(all_conditions)} conditions")
print(list(all_conditions.keys())[:5])
# ["abdominal_pain_nonspecific", "allergic_reaction_mild", ...]
```

YAML パースエラーは silent skip される (ログなし)。本番ではロード前に `pytest tests/unit/test_encounter_protocols.py` 実行を推奨。

### `create_inpatient_encounter(patient_id, admission_datetime, chief_complaint, department_id, visit_number) -> Encounter`

新しい入院 encounter を作成する (`engine.py:28`)。グローバルカウンタで一意 ID を発行する。

```python
from datetime import datetime
from clinosim.modules.encounter.engine import create_inpatient_encounter

enc = create_inpatient_encounter(
    patient_id="P-000001",
    admission_datetime=datetime(2024, 1, 15, 14, 30),
    chief_complaint="Fever, cough, dyspnea",
    department_id="internal_medicine",
)
enc.encounter_id    # "ENC-P-000001-000001"
enc.episode_id      # "EP-P-000001-000001"
enc.encounter_type  # EncounterType.INPATIENT
enc.status          # EncounterStatus.IN_PROGRESS
```

**グローバルカウンタ**: モジュールレベル `_encounter_counter` がシミュレーション実行中に単調増加し、 ID 衝突を防ぐ。 テスト間でリセットしたい場合は `encounter.engine._encounter_counter = 0` を明示的に設定する (AD: 通常テストでは別 seed で判別)。

### `generate_daily_cycle(encounter, day_number) -> list[DailyCycleEvent]`

入院 1 日分の **定型スケジュール** を生成する (`engine.py:54`)。日本の中規模病院の日課をモデル化:

| 時刻 | イベント |
|---|---|
| 06:00 | morning_vitals |
| 06:30 | morning_labs |
| 09:00 | rounds |
| 14:00 | afternoon_vitals |
| 18:00 | evening_vitals |
| 18:30 | evening_meds |
| 22:00 | night_check |

```python
from clinosim.modules.encounter.engine import generate_daily_cycle

events = generate_daily_cycle(enc, day_number=3)
for e in events:
    print(e.timestamp, e.event_type)
# 2024-01-18 06:00:00 morning_vitals
# 2024-01-18 06:30:00 morning_labs
# ...
```

### `generate_encounter_timeline(encounter, total_days) -> list[DailyCycleEvent]`

入院全期間の完全タイムラインを生成する (`engine.py:116`)。
- Day 0 に入院イベント 3 件 (`admission`, `admission_assessment`, `admission_orders`)
- 各日の daily cycle (Day 0 は入院時刻より前のイベントをスキップ)
- 退院日に `discharge_decision` (10:00) と `discharge` (14:00)
- 結果を chronological 順にソート

```python
timeline = generate_encounter_timeline(enc, total_days=7)
# returns ~50 events sorted by timestamp
```

### `DailyCycleEvent` (dataclass)

```python
@dataclass
class DailyCycleEvent:
    timestamp: datetime
    event_type: str     # "morning_vitals" | "admission" | "discharge" | ...
    data: dict[str, Any] = field(default_factory=dict)
```

## YAML スキーマ

### Required metadata

```yaml
condition_id: migraine
icd10_code: "G43.909"
icd10_display: "Migraine, unspecified, not intractable, without status migrainosus"
chief_complaint:
  en: "Severe headache, nausea, photophobia"
  ja: "激しい頭痛・嘔気・光過敏"
encounter_type: emergency            # "emergency" | "outpatient"
department: emergency_medicine
disposition: discharge_home          # "discharge_home" | "observation" | "admit"
```

### Severity & duration

```yaml
severity_distribution:
  mild:     0.30
  moderate: 0.50
  severe:   0.20

ed_stay_hours:
  mild:     {mean: 2.0, sd: 0.5}
  moderate: {mean: 3.5, sd: 1.0}
  severe:   {mean: 5.0, sd: 1.5}
```

### Workup (vitals/labs/imaging)

```yaml
workup:
  vitals: true
  labs:
    - {test: "WBC", probability: 0.3}
    - {test: "CRP", probability: 0.2}
    - {test: "Troponin", probability: 0.4, serial: true, interval_hours: 3}
  imaging:
    - {test: "CT_Head", probability: 0.3}
```

Available lab names: `WBC`, `CRP`, `Creatinine`, `Na`, `K`, `Glucose`, `Hb`, `Plt`, `AST`, `ALT`, `BUN`, `Troponin`, `BNP`, `PT_INR`, `HbA1c`, `Lactate`, `Albumin`, `TSH`, `Ca`, `eGFR`, `PCT`, `LDH`, `GGT`, `T_Bil`, `pH`, `HCO3`, `pCO2`

### Treatment

```yaml
treatment:
  - {name: "Ketorolac 30mg",     probability: 0.7, route: "IV",  intent: "analgesic"}
  - {name: "Metoclopramide 10mg", probability: 0.6, route: "IV",  intent: "antiemetic"}
  - {name: "IV normal saline 1000mL", probability: 0.5, route: "IV", intent: "rehydration"}
  - {name: "Dark room rest",      probability: 0.8, route: "non-pharmacologic"}
```

`route` は `IV` / `PO` / `IM` / `SC` / `SL` / `topical` / `INH` / `procedure` / `non-pharmacologic` のいずれか。

### Discharge

```yaml
discharge_instructions:
  - "Keep hydrated, rest in dark quiet room"
  - "Return if neurologic symptoms, worst headache of life, fever"

discharge_prescriptions:
  - {drug: "Sumatriptan 50mg", route: "PO", frequency: "PRN", duration_days: 30, probability: 0.3}
```

### Demographics (オプション)

```yaml
incidence_modifier: 1.0           # 相対頻度
age_distribution: adults          # "all" | "adults" | "adults_40plus" | "elderly" | "pediatric"
sex_ratio_female: 1.5             # 1.0=equal, >1=女性多
seasonal:
  1: 1.0
  # ... all 12 months
```

## 使用例

### 1 件の ED 条件でシミュレート

```python
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.locale.text import resolve_text

cond = load_encounter_condition("migraine")
print(resolve_text(cond["chief_complaint"], country="JP"))
# → "激しい頭痛・嘔気・光過敏"

# Severity sampling
sev = rng.choice(list(cond["severity_distribution"].keys()),
                 p=list(cond["severity_distribution"].values()))

# Stay duration
h = cond["ed_stay_hours"][sev]
stay_hours = float(rng.normal(h["mean"], h["sd"]))
```

### 入院フルタイムライン

```python
from datetime import datetime
from clinosim.modules.encounter.engine import (
    create_inpatient_encounter, generate_encounter_timeline,
)

enc = create_inpatient_encounter(
    patient_id="P-000001",
    admission_datetime=datetime(2024, 1, 15, 14, 30),
    chief_complaint="Fever, cough, dyspnea",
    department_id="internal_medicine",
)
events = generate_encounter_timeline(enc, total_days=7)
for e in events[:5]:
    print(f"{e.timestamp:%Y-%m-%d %H:%M} {e.event_type}")
```

### CLI デバッグ

```bash
# 単一 encounter 条件で 1 患者生成 + 詳細出力
clinosim test-encounter migraine

# 年齢・性別・シード指定
clinosim test-encounter migraine --age 65 --sex F --seed 123

# 複数患者
clinosim test-encounter flu_vaccination -n 5

# 全条件一覧
clinosim list-diseases   # encounter + disease を合わせて表示
```

## 拡張方法

### 新しい encounter 条件を追加する

1. `reference_data/<condition_id>.yaml` を作成 (既存 YAML をテンプレートに)
2. Required metadata (condition_id, icd10_code, icd10_display, chief_complaint, encounter_type, department, disposition) を埋める
3. `severity_distribution`, `ed_stay_hours`, `workup` を定義
4. 必要に応じて `treatment`, `discharge_instructions`, `discharge_prescriptions` を追加
5. 自動的に population に生成させたい場合:
   - **ED 条件**: `locale/{country}/demographics.yaml > ed_visit_not_admitted.conditions` にエントリを追加
   - **外来条件**: `modules/population/engine.py > generate_healthcare_calendar()` に生成ルールを追加
6. `clinosim test-encounter <condition_id>` で動作確認
7. `pytest tests/unit/test_encounter_protocols.py` を実行

### ICD コードの多言語表示を追加する

本モジュールは `icd10_code` と `icd10_display` のみ YAML に持つが、 最終的な display 解決は **`clinosim.codes` モジュール** に委譲することを推奨:

```python
from clinosim.codes import lookup

display_ja = lookup("icd-10-cm", cond["icd10_code"], "ja")
```

### 新しい daily cycle パターン (国別)

`generate_daily_cycle()` を country 引数で分岐させる (現状は日本の中規模病院モデル固定)。 例: 米国病院は rounds が 07:00-09:00、evening meds が 20:00、など。

## 依存関係

本モジュールが依存するもの:

| 依存先 | 用途 |
|---|---|
| `clinosim.types.encounter` | `Encounter`, `EncounterStatus`, `EncounterType` |
| `pyyaml` | YAML パース |

本モジュールに依存する側:

| 依存側 | 用途 |
|---|---|
| `clinosim.simulator` | 入院 encounter 作成とタイムライン生成 |
| `clinosim.modules.order` | Encounter × 条件プロトコルから検査・薬剤オーダーを生成 |
| `clinosim.modules.observation` | Daily cycle の `morning_labs` / `morning_vitals` をトリガ |
| `clinosim.modules.clinical_course` | Day 単位の進行を駆動 |

## テスト

```bash
# 単体テスト (YAML ロード, Encounter 生成, 日次サイクル)
pytest tests/unit/test_encounter.py -v

# 全 encounter YAML の構造検証
pytest tests/unit/test_encounter_protocols.py -v

# CLI 動作確認
clinosim test-encounter migraine -n 1 --seed 42
```

テスト観点:

- `load_all_encounter_conditions()` が 44 件以上返すこと
- 各 YAML に必須フィールドが揃っていること
- `severity_distribution` の合計が ≈ 1.0
- `create_inpatient_encounter()` の ID がグローバルに一意であること
- `generate_encounter_timeline()` が入院時刻前のイベントを除外し、chronological 順であること
