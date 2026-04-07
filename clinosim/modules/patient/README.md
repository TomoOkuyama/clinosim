# clinosim.modules.patient — Patient Activator Module

## 目的

**Layer 1 (PersonRecord, 軽量人口レジストリ) → Layer 2 (PatientProfile, 臨床プロファイル)** への変換 (activation) を担当する。

clinosim では population モジュールが人口全体の軽量レジストリ (`PersonRecord`) を保持し、 実際に医療機関を受診した人のみが「活性化」されて詳細な臨床プロファイル (`PatientProfile`) に拡張される。 本モジュールはこの **Layer 1 → Layer 2 活性化関数** を提供する。

活性化時に生成される情報:

- 身体計測 (身長・体重・BMI) — 国・性別ベース
- 生理学的プロファイル (免疫反応性、薬物代謝、腎・心・肝予備能、等)
- 慢性疾患の臨床ステージ (NYHA / CKD G-stage / HbA1c / GOLD / CCS 等)
- ベースラインバイタル (体温、心拍、血圧、呼吸数、SpO2) — 慢性疾患の影響を反映
- アレルギー履歴
- 婚姻状態・雇用状態・保険・嗜好品履歴
- 連絡先情報・緊急連絡先
- 優先言語 (BCP-47)

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **決定論的** | `rng: numpy.random.Generator` を引数で受け取る。グローバル状態を使わない (AD-16) |
| 2 | **Layer 分離** | Layer 1 は人口全体に保持可能な軽量情報のみ。Layer 2 は受診時に活性化 |
| 3 | **国差対応** | 身長・BMI 分布・薬物代謝表現型頻度・名前表記順が country 依存 |
| 4 | **生理学的整合性** | age, chronic_conditions からベースラインバイタル・予備能が導かれる |
| 5 | **臨床ステージ自動割付** | ICD コードごとに妥当な staging を YAML でなく関数で生成 (分布は clinical guidelines 由来) |
| 6 | **テスト用 hardcoded patient** | `test_patient.py` は population を迂回する v0.1-alpha 用の固定患者 |

## ディレクトリ構造

```
clinosim/modules/patient/
├── __init__.py
├── activator.py         # activate_patient() — Layer 1 → Layer 2 変換本体
├── test_patient.py      # create_test_patient() — hardcoded test fixture
├── README.md
└── SPEC.md
```

## 権威ソース

| データ項目 | ソース |
|---|---|
| **婚姻状態コード** | [HL7 v3 MaritalStatus](http://terminology.hl7.org/CodeSystem/v3-MaritalStatus) (`S`, `M`, `D`, `W`) |
| **優先言語** | [BCP-47 language tags](https://www.rfc-editor.org/info/bcp47) (`ja-JP`, `en-US`) |
| **NYHA 心不全分類** | New York Heart Association Functional Classification (I–IV) |
| **CKD G-stage** | [KDIGO 2012 CKD Guideline](https://kdigo.org/guidelines/ckd-evaluation-and-management/) (G1–G5) |
| **GOLD COPD ステージ** | [GOLD Report](https://goldcopd.org/) (1–4) |
| **CCS 狭心症分類** | Canadian Cardiovascular Society Classification (I–IV) |
| **HbA1c 目標** | 日本糖尿病学会 / ADA Standards of Care |
| **身長分布 (JP)** | 厚生労働省 国民健康・栄養調査 |
| **身長分布 (US)** | CDC NHANES |
| **薬物代謝表現型頻度** | CYP2D6 allele frequencies by ethnicity (PharmGKB) |

## API リファレンス

### `activate_patient(person, rng, country="JP") -> PatientProfile`

Layer 1 `PersonRecord` を Layer 2 `PatientProfile` に変換する中核関数。

**Signature** (`activator.py:110`):

```python
def activate_patient(
    person: PersonRecord,
    rng: np.random.Generator,
    country: str = "JP",
) -> PatientProfile:
```

**Args**:

- `person` — population モジュールが生成した `PersonRecord` (age, sex, chronic_conditions (ICD-10 コードリスト), family_name, given_name, postal_code, blood_type 等を持つ)
- `rng` — 決定論的に使用する `numpy.random.Generator` (シミュレータの patient サブシードから派生)
- `country` — `"JP"` | `"US"` (身長・BMI 分布や名前表記順に影響)

**Returns**: 完全に埋められた `PatientProfile`

**生成ロジック概要**:

1. **身長・体重・BMI** — 国・性別で平均を切替え (JP 男性 170cm/BMI 23.5, US 男性 175.5cm/BMI 29.0 など)。 60 歳以上は年間 0.5cm / 10yr の萎縮を適用。BMI は [15, 45] にクリップ (`activator.py:120-129`)
2. **生理学的プロファイル** — `beta(8, 2)` から腎/心/肝予備能をサンプリングし `(age-40) × 0.005` のペナルティ減算。 薬物代謝表現型 (`poor` / `normal` / `rapid` / `ultra_rapid`) は country 依存の分布 (`activator.py:131-148`)
3. **慢性疾患の staging** — 各 ICD コードに対し `_generate_stage()` が臨床的に妥当なステージ文字列を生成
4. **アレルギー** — 約 15% に mild rash アレルギー (Penicillin / Sulfonamide / NSAIDs / Cephalosporin)
5. **ベースラインバイタル** — 年齢補正 (SBP は +0.5/yr over 30) + 慢性疾患調整:
   - `I10` (HT) → SBP +10, DBP +5
   - `I48` (AFib) → HR +5〜20 の irregular
   - `J44` (COPD) → SpO2 を 94 付近に制限
   - `J45` (Asthma) → 呼吸数 +0〜3
   - `E03` (甲状腺機能低下) → HR -3〜8
6. **名前表記** — JP は `family given`, US は `given family` の順で `display_name` を構築
7. **婚姻状態** — 年齢帯別の分布 (HL7 v3 `S` / `M` / `D` / `W`) (`activator.py:257-267`)
8. **優先言語** — country から BCP-47 タグに変換 (`JP → ja-JP`, `US → en-US`)
9. **保険区分** — 75 歳以上は `late_elderly` (後期高齢者医療)、未満は `NHI_employee`
10. **嗜好品** — 喫煙 55/30/15 (never/former/current)、飲酒 60/30/10 (none/social/heavy)

### `_generate_stage(code, severity, rng) -> str`

ICD コードから臨床ステージ文字列を生成する内部ヘルパー (`activator.py:23-56`)。 ICD ベースコード (`I50` ← `I50.9`) でスイッチする。

| ICD base | 出力例 | 分布 |
|---|---|---|
| `N18` (CKD) | `"CKD G3a"` | G1:5 / G2:30 / G3a:30 / G3b:20 / G4:10 / G5:5 |
| `I50` (HF) | `"NYHA II"` | severity=mild: I:30/II:50/III:15/IV:5; moderate: I:10/II:30/III:40/IV:20 |
| `E11` / `E10` (DM) | `"HbA1c 7.3%"` | mild: Uniform(6.5, 7.5); moderate: Uniform(7.5, 9.5) |
| `J44` (COPD) | `"GOLD 2"` | 1:20 / 2:40 / 3:30 / 4:10 |
| `J45` (Asthma) | `"Mild persistent"` | Mild int.:30 / Mild pers.:35 / Moderate pers.:25 / Severe pers.:10 |
| `I10` (HT) | `"Stage 1"` | 1:60 / 2:40 |
| `I25` (IHD) | `"CCS I"` | I:40 / II:40 / III:20 |
| その他 | `""` |  |

### `create_test_patient() -> PatientProfile`

`test_patient.py` の v0.1-alpha 用固定フィクスチャ。 72 歳女性、日本、HT + T2DM 既往、身長 152cm / 体重 54kg / BMI 23.4。 Population モジュールを経ずに PatientProfile を直接構築する (AD-12 テスト用 backdoor)。

```python
from clinosim.modules.patient.test_patient import create_test_patient

patient = create_test_patient()
assert patient.patient_id == "P-ALPHA-001"
assert patient.age == 72 and patient.sex == "F"
```

### `CONDITION_NAMES: dict[str, str]`

ICD コード → 英語病名の参照辞書 (`activator.py:59-107`)。 現在 47 エントリ。Layer 2 活性化時の人間可読表示に使われ、また他モジュールからインポート参照も可能。

## 使用例

### シミュレータの標準フロー

```python
import numpy as np
from clinosim.modules.population.engine import generate_person
from clinosim.modules.patient.activator import activate_patient

# Simulator のシードから patient サブ rng を作成
master_rng = np.random.default_rng(seed=42)
pt_rng = np.random.default_rng(master_rng.integers(0, 2**32))

# Layer 1
person = generate_person(master_rng, country="JP")

# Layer 2 活性化 (ED 来院時)
patient = activate_patient(person, pt_rng, country="JP")

print(patient.name.display_name)        # "佐藤 花子"
print(patient.age, patient.sex)          # 72 F
print(patient.baseline_vitals.systolic_bp)  # 慢性疾患補正入り
print([c.code + " " + c.stage for c in patient.chronic_conditions])
# ["I10 Stage 1", "N18 CKD G3a", ...]
```

### Country 切替

```python
patient_jp = activate_patient(person, rng_jp, country="JP")
assert patient_jp.preferred_language == "ja-JP"
assert patient_jp.name.name_script == "ja"

patient_us = activate_patient(person, rng_us, country="US")
assert patient_us.preferred_language == "en-US"
# US 分布は BMI が高く出る (平均 29)
```

## データ構造

全ての型定義は `clinosim/types/patient.py` にある (AD: 型はモジュール内に定義しない)。

```python
@dataclass
class PatientProfile:
    patient_id: str
    name: PersonName
    age: int
    sex: str
    date_of_birth: date
    blood_type: str
    rh_factor: str                          # "+" or "-"
    height_cm: float
    weight_kg: float
    bmi: float
    address: Address
    contact: ContactInfo
    marital_status: str                     # HL7 v3: S/M/D/W
    preferred_language: str                 # BCP-47: "ja-JP"
    employment_status: str                  # "employed" | "retired"
    insurance_type: str                     # "late_elderly" | "NHI_employee" | ...
    health_literacy: float                  # 0.0–1.0
    chronic_conditions: list[ChronicCondition]
    allergies: list[Allergy]
    current_medications: list[...]
    smoking_status: str                     # "never" | "former" | "current"
    alcohol_use: str                        # "none" | "social" | "heavy"
    physiological_profile: PatientPhysiologicalProfile
    baseline_vitals: BaselineVitals
```

```python
@dataclass
class PatientPhysiologicalProfile:
    immune_reactivity: float         # 0–1, beta(5,5)
    drug_metabolism_rate: str        # "poor" | "normal" | "rapid" | "ultra_rapid"
    renal_reserve: float             # 0.1–1.0, beta(8,2) - age penalty
    cardiac_reserve: float
    hepatic_reserve: float
    treatment_sensitivity: float     # normal(1.0, 0.15)
    symptom_reporting_bias: float    # normal(1.0, 0.25)
    delirium_susceptibility: float   # beta(2,8) + age/dementia/Parkinson boost
    dvt_susceptibility: float        # beta(2,8) + age boost
```

```python
@dataclass
class ChronicCondition:
    code: str                   # ICD-10
    system: str = "icd-10-cm"
    onset_date: date
    severity: str               # "mild" | "moderate"
    controlled: bool
    severity_score: float       # 0.0–1.0
    stage: str                  # "CKD G3a" / "NYHA II" / "HbA1c 7.3%" etc.
```

## 拡張方法

### 新しい慢性疾患の staging を追加する

`_generate_stage()` に新しい ICD ベースコードの分岐を追加する:

```python
# activator.py:_generate_stage
if base == "K74":  # Cirrhosis
    classes = ["Child-Pugh A", "Child-Pugh B", "Child-Pugh C"]
    weights = [0.50, 0.35, 0.15]
    return str(rng.choice(classes, p=weights))
```

分布は臨床ガイドラインやレジストリデータ (日本消化器学会等) を参照する。

### 新しいバイタル補正ルールを追加する

`activate_patient` 末尾の "chronic condition adjustments" ブロックに 1 行追加:

```python
if "I27" in person.chronic_conditions:  # 肺高血圧症
    vitals.spo2 = round(min(vitals.spo2, float(rng.normal(92, 2.0))), 1)
```

### 新しい国を追加する

身長・BMI 分布と薬物代謝表現型分布を追加:

```python
if country == "JP":
    ...
elif country == "US":
    ...
elif country == "KR":  # 新規
    height = float(rng.normal(173.0 if sex == "M" else 160.0, 5.8))
    bmi = float(rng.normal(24.0 if sex == "M" else 23.0, 3.5))
```

あわせて `clinosim/locale/kr/` フォルダ一式を追加 (locale モジュールの README 参照)。

## 依存関係

本モジュールが依存するもの:

| 依存先 | 用途 |
|---|---|
| `clinosim.types.patient` | `PatientProfile`, `ChronicCondition`, `BaselineVitals`, `PatientPhysiologicalProfile`, `PersonName`, `Address`, `ContactInfo`, `Allergy` |
| `clinosim.modules.population.engine` | 入力型 `PersonRecord` |
| `numpy` | `Generator` |

**依存しないもの**: locale/codes/disease/observation 等。本モジュールは純粋な Layer 変換関数に留まり、 臨床用語の解決は呼び出し側 (simulator / output adapter) が行う。

本モジュールに依存する側:

- `clinosim.simulator` (入院開始時に `activate_patient` を呼ぶ)
- 各種 e2e テスト (test_patient.py を直接インポート)

## テスト

```bash
# 単体テスト
pytest tests/unit/test_patient.py -v

# 活性化後のバイタルが境界内にあること、慢性疾患補正が適用されていることを検証
# (test_patient.py に hardcoded fixture、統合テストで activate_patient を呼ぶ)
```

テスト観点:

- `create_test_patient()` は決定論的に同じ値を返すこと
- `activate_patient()` は同じ seed で同じ結果を返すこと (AD-16)
- BMI が [15, 45] に収まること
- 慢性疾患 `J44` 患者の SpO2 が ≤95 であること
- `marital_status` が HL7 v3 の有効コードであること
