# clinosim.modules.diagnosis — Bayesian 鑑別診断エンジン

## 目的

入院時に候補疾患リスト (differential) を生成し、 検査結果 (findings) が得られるたびに **likelihood ratio (LR)** を使って Bayesian update を行い、 確率分布を更新する。 また、 confidence に応じて ICD コードが「非特異 → 特異」へと段階的に進展する。

これにより:

- 誤診 (working diagnosis が ground truth と異なる) が確率的に発生し、 経過に反映される
- 診断コードが臨床の実際に即して時間的に変化する (admission → intermediate → discharge で精緻化)
- clinical_course モジュールの diagnosis feedback と連動し、 誤診が recovery 速度の dampening として現れる
- 臨床検査の効果が LR を通して定量的にモデル化される

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **Priors は疾患毎** | `DIFFERENTIALS[disease_id]` に 26 疾患の鑑別リストを定義 |
| 2 | **LR による Bayesian update** | 各 finding は `{"pos": LR+, "neg": LR-}` を持つ。 正規化で確率化 |
| 3 | **Confirmation threshold** | top 候補の確率が threshold (既定 0.90) を超えると confirmed |
| 4 | **Working vs confirmed** | top > 0.5 で working、 > threshold で confirmed |
| 5 | **段階的 ICD コード進展** | `DIAGNOSIS_PROGRESSION` で confidence 閾値ごとに code/display を変化 |
| 6 | **Protocol YAML 優先** | disease YAML の `diagnostic.differential` / `lr_table` / `diagnosis_progression` があればそれを使用 |

## API リファレンス

### `initialize_differential(disease_id="bacterial_pneumonia", age=70, protocol_diagnostic=None) -> DifferentialDiagnosis`

入院時の鑑別リストを生成する。

```python
from clinosim.modules.diagnosis.engine import initialize_differential

diff = initialize_differential(
    disease_id="bacterial_pneumonia",
    age=patient.age,
    protocol_diagnostic=disease_yaml.get("diagnostic"),
)
# diff.candidates = [
#     DiagnosisCandidate("bacterial_pneumonia", "J18.9", "Bacterial pneumonia", 0.45),
#     DiagnosisCandidate("viral_pneumonia", "J12.9", "Viral pneumonia", 0.15),
#     ...
# ]
```

**Age adjustment**: `age >= 75` の場合、 候補に `heart_failure` があれば prior ×1.5 (高齢者は HF overlap しやすい)。

**Working diagnosis の即時設定**: top candidate の確率が 0.5 を超えていれば即座に `working_diagnosis` に設定 (明確な典型症例)。

### `update_differential(diff, findings, confirmation_threshold=0.90, protocol_lr_table=None) -> DifferentialDiagnosis`

新しい検査結果を differential に反映する。

```python
from clinosim.modules.diagnosis.engine import update_differential

findings = [
    ("chest_xray_consolidation", True),   # 陽性
    ("procalcitonin_elevated", True),
    ("wbc_elevated", True),
]
diff = update_differential(diff, findings, confirmation_threshold=0.90)
```

**アルゴリズム**:

```
for each (finding, is_positive):
    lr_entry = LR_TABLE[finding]
    for each candidate:
        lr = lr_entry[candidate.disease_code]["pos" if is_positive else "neg"]
        candidate.probability *= lr
# Normalize to sum = 1.0
# Sort by probability desc
# If top.probability >= confirmation_threshold: diff.confirmed = True
# Elif top.probability >= 0.5: diff.working_diagnosis = top
```

`candidate.evidence` に `"chest_xray_consolidation: (+) LR=8.0"` のような履歴を追加していく。

### `get_current_diagnosis_code(diff, protocol_progression=None) -> tuple[str, str]`

現時点での confidence に対応する (ICD code, display name) を返す。

```python
from clinosim.modules.diagnosis.engine import get_current_diagnosis_code

code, name = get_current_diagnosis_code(diff, protocol_progression=disease_yaml.get("diagnostic", {}).get("diagnosis_progression"))
# confidence 0.45 → ("J18.9", "Pneumonia, unspecified")
# confidence 0.75 → ("J18.1", "Lobar pneumonia, unspecified")
# confidence 0.95 → ("J13",   "Pneumonia due to Streptococcus pneumoniae")
```

**Fallback chain**:
1. `working_diagnosis` が設定されていればそれを target にする
2. 無ければ top candidate の `disease_code`
3. `DIAGNOSIS_PROGRESSION[target]` を探して、 confidence が閾値を超えた最上位の code を返す
4. 何も無ければ top candidate の `icd_code`
5. 最終フォールバック: `("R69", "Illness, unspecified")`

## データ構造

### `DiagnosisCandidate`

```python
@dataclass
class DiagnosisCandidate:
    disease_code: str       # 内部キー "bacterial_pneumonia"
    icd_code: str           # ICD-10 "J18.9"
    display_name: str       # "Bacterial pneumonia"
    probability: float      # 0.0-1.0 (リスト全体で正規化)
    evidence: list[str]     # Bayesian update 履歴
```

### `DifferentialDiagnosis`

```python
@dataclass
class DifferentialDiagnosis:
    candidates: list[DiagnosisCandidate]  # probability desc でソート
    working_diagnosis: str | None = None  # top > 0.5 で設定される disease_code
    confirmed: bool = False               # top >= threshold で True
    timestamp: datetime

    @property
    def top_candidate(self) -> DiagnosisCandidate | None: ...
```

### `DIFFERENTIALS` (組み込み priors)

```python
DIFFERENTIALS: dict[str, list[dict]] = {
    "bacterial_pneumonia": [
        {"disease": "bacterial_pneumonia", "icd": "J18.9", "name": "Bacterial pneumonia", "prior": 0.45},
        {"disease": "viral_pneumonia",     "icd": "J12.9", "name": "Viral pneumonia", "prior": 0.15},
        {"disease": "influenza",           "icd": "J11.1", "name": "Influenza", "prior": 0.10},
        {"disease": "heart_failure",       "icd": "I50.9", "name": "Heart failure", "prior": 0.10},
        {"disease": "pulmonary_embolism",  "icd": "I26.9", "name": "Pulmonary embolism", "prior": 0.05},
        ...
    ],
    "heart_failure_exacerbation": [...],
    "hip_fracture": [...],
    "urinary_tract_infection": [...],
    "copd_exacerbation": [...],
    "sepsis": [...],
    # ... 26 疾患定義
}
```

カバーする疾患 (抜粋): bacterial_pneumonia, heart_failure_exacerbation, hip_fracture, urinary_tract_infection, copd_exacerbation, sepsis, cerebral_infarction, acute_mi, gi_bleeding, diabetic_ketoacidosis, ileus, acute_pancreatitis, acute_appendicitis, pulmonary_embolism, acute_cholecystitis, atrial_fibrillation_rvr, cellulitis, acute_kidney_injury, liver_cirrhosis_decompensated, aspiration_pneumonia, influenza, asthma_exacerbation, hemorrhagic_stroke, vertebral_compression_fracture, deep_vein_thrombosis, 外傷系 (traffic_accident_severe, wrist_fracture_surgical, subdural_hematoma)。

### `LR_TABLE` (組み込み likelihood ratios)

```python
LR_TABLE = {
    "chest_xray_consolidation": {
        "bacterial_pneumonia": {"pos": 8.0, "neg": 0.3},
        "viral_pneumonia":     {"pos": 2.0, "neg": 0.7},
        "heart_failure":       {"pos": 0.5, "neg": 1.1},
    },
    "procalcitonin_elevated": {
        "bacterial_pneumonia": {"pos": 6.0, "neg": 0.15},
        "viral_pneumonia":     {"pos": 0.3, "neg": 2.0},
    },
    "crp_above_100": {
        "bacterial_pneumonia": {"pos": 3.5, "neg": 0.4},
        "viral_pneumonia":     {"pos": 0.5, "neg": 1.5},
    },
    "wbc_elevated": {
        "bacterial_pneumonia": {"pos": 2.5, "neg": 0.6},
        "viral_pneumonia":     {"pos": 0.5, "neg": 1.3},
    },
}
```

Disease YAML の `diagnostic.lr_table` があればそれが優先。 フォーマットは同一 (`positive_LR` / `negative_LR` という長い別名もサポート)。

### `DIAGNOSIS_PROGRESSION`

`(threshold, icd_code, display_name)` のタプルリストを disease_code 毎に定義。

```python
DIAGNOSIS_PROGRESSION = {
    "bacterial_pneumonia": [
        (0.0, "J18.9", "Pneumonia, unspecified"),
        (0.7, "J18.1", "Lobar pneumonia, unspecified"),
        (0.9, "J13",   "Pneumonia due to Streptococcus pneumoniae"),
    ],
    "sepsis": [
        (0.0, "A41.9",  "Sepsis, unspecified organism"),
        (0.7, "R65.20", "Severe sepsis without septic shock"),
        (0.9, "R65.21", "Severe sepsis with septic shock"),
    ],
    ...
}
```

Threshold に `confidence >= threshold` を満たす **最上位** の行が採用される。

## 使用例: 肺炎患者の診断進展

```python
from clinosim.modules.diagnosis.engine import (
    initialize_differential, update_differential, get_current_diagnosis_code,
)

# Day 0: 入院時
diff = initialize_differential("bacterial_pneumonia", age=72)
code_0, name_0 = get_current_diagnosis_code(diff)
# → ("J18.9", "Pneumonia, unspecified") — 典型例なので既に working
print(f"Admission: {code_0} — confidence={diff.candidates[0].probability:.2f}")

# Day 0: CXR 結果到着
diff = update_differential(diff, [("chest_xray_consolidation", True)])
code_1, _ = get_current_diagnosis_code(diff)
# confidence ≈ 0.78 → ("J18.1", "Lobar pneumonia")

# Day 1: PCT と WBC 結果
diff = update_differential(diff, [
    ("procalcitonin_elevated", True),
    ("wbc_elevated", True),
])
code_2, name_2 = get_current_diagnosis_code(diff)
# confidence ≈ 0.96 → diff.confirmed = True → ("J13", "Pneumonia due to S. pneumoniae")
print(f"Day 1: {code_2} — confirmed={diff.confirmed}")

# Day 5: 退院診断として clinical_diagnosis に格納
ClinicalDiagnosis(
    admission_diagnosis_code=code_0,   # J18.9
    discharge_diagnosis_code=code_2,   # J13
)
```

## Disease YAML との連携

各 disease YAML は optional に `diagnostic` セクションを持てる:

```yaml
diagnostic:
  difficulty: 0.30                    # clinical_course が使う
  differential:
    - {disease: bacterial_pneumonia, icd: J18.9, name: Bacterial pneumonia, prior: 0.50}
    - {disease: heart_failure, icd: I50.9, name: Heart failure, prior: 0.15}
    ...
  lr_table:
    chest_xray_consolidation:
      bacterial_pneumonia: {pos: 10.0, neg: 0.2}
    ...
  diagnosis_progression:
    bacterial_pneumonia:
      - [0.0, "J18.9", "Pneumonia, unspecified"]
      - [0.7, "J18.1", "Lobar pneumonia"]
      - [0.9, "J13",   "Streptococcal pneumonia"]
```

Protocol が提供されればそれが優先、 無ければ built-in を使う (loader は `protocol_diagnostic`, `protocol_lr_table`, `protocol_progression` 引数で注入)。

## 依存関係

- 標準ライブラリのみ (`dataclasses`, `datetime`)
- **他モジュールへの依存なし** — standalone な数値処理

## テスト

```bash
source .venv/bin/activate && python -m pytest tests/unit/test_diagnosis.py -v
```

カバー範囲: 初期化、 Bayesian update、 confirmation、 negative findings、 code progression、 正規化、 age adjustment。

## 権威ソース

- LR 値の典型レンジは下記の文献を参照:
  - Metlay JP et al., JAMA 1997 (pneumonia physical exam LR)
  - Schuetz P et al., Cochrane Database 2017 (procalcitonin for bacterial infection)
  - McGee S, *Evidence-Based Physical Diagnosis*, 4th ed (clinical finding LRs)
- ICD-10-CM コードは CMS 公式 (`clinosim.codes` モジュール参照)

## 修正ガイド

### 新しい疾患の診断ロジックを追加する

1. disease YAML の `diagnostic` セクションに `differential`, `likelihood_ratios`, `confirmation_threshold` を記述
2. コード変更不要（YAML 駆動）

### 関連モジュール

| モジュール | 関係 |
|---|---|
| `disease` | 鑑別診断リスト・LR テーブルのソース (YAML) |
| `clinical_course` | 診断フィードバック (`diagnosis_correct` → treatment_sensitivity) |
| `output` | `clinical_diagnosis.admission_diagnosis_code` → FHIR Condition (code_lookup で表示名解決) |
| `codes` | ICD-10-CM/ICD-10 コード辞書 — 新コード追加時は `codes/data/icd-10-cm.yaml` + `icd-10.yaml` の両方に EN/JA で追加 |

### ICD コード追加時の注意

- `icd-10-cm.yaml` (US 主体) と `icd-10.yaml` (JP 主体) の **両方** に追加すること
- 各エントリに `en` (必須) + `ja` (JP 出力用) フィールド
- `_CONDITION_SHORT_NAME` (fhir_r4_adapter.py) に臨床略語があれば追加 (COPD, CHF 等)
