# clinosim.modules.physiology — 生理学エンジン

## 目的

clinosim の **リアリティの中核エンジン**。 9 つの隠れた生理学的状態変数 (`PhysiologicalState`) を管理し、 観察されるすべての臨床値 (検査値・バイタル) をそこから **derive** する。

重要原則: **lab や vital を独立に生成しない**。 すべては hidden state から決まる:

```
Hidden state (9 variables) ── derive ──→ Lab values (CRP, Cr, BNP, …)
                           └─ derive ──→ Vital signs (T, HR, BP, SpO2, RR)
```

これにより:

- 検査値とバイタルの **内部整合性** が自動的に担保される (例: CRP と WBC と発熱が連動)
- 慢性疾患 (CKD, HF, 肝硬変) が baseline state に反映され、 急性期にも影響
- 臓器連関 (例: perfusion ↓ → renal ↓ → 代謝性アシドーシス) が physiologically plausible
- clinical_course の directive は hidden state を動かすだけで、 観察値は自動追従

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **Hidden state は真実** | 観察値は derive の結果。 独立に生成してはならない |
| 2 | **Coupling rules は順序依存** | cardiac → perfusion → renal → pH の因果ツリー |
| 3 | **Clamping は必須** | すべての変数は `_variable_range()` で範囲内に保つ |
| 4 | **Directive は daily delta** | `update()` が time_step でスケール (1 hour なら × 1/24) |
| 5 | **慢性疾患は baseline に焼き込む** | `initialize_state()` で chronic condition の severity_score を反映 |
| 6 | **決定論的 (seed ベース)** | derive_* は RNG を使わない (noise は observation モジュール) |

## 9 つの状態変数

| 変数名 | 範囲 | 臨床的意味 | 主な影響先 |
|---|---|---|---|
| `inflammation_level` | 0–1 | 全身炎症 (cytokine burst) | CRP, WBC, PCT, Albumin, 発熱, 心拍 |
| `renal_function` | 0–1 | 腎機能 (糸球体濾過) | Cr, BUN, eGFR, K, pH |
| `cardiac_function` | 0–1 | 心ポンプ機能 | BNP, perfusion, BP |
| `hepatic_function` | 0–1 | 肝機能 | AST, ALT, T_Bil, PT-INR, Alb |
| `anemia_level` | 0–1 | 貧血の深度 | Hb, Hct, 代償性頻脈 |
| `coagulation_status` | 0–1 | 凝固障害 (DIC) | PT-INR, Plt |
| `volume_status` | -1 〜 +1 | 脱水 ↔ overload | BP, RR, Na, BUN/Cr比 |
| `perfusion_status` | 0–1 | 組織灌流 | Lactate, BP, 腎血流 |
| `ph_status` | -1 〜 +1 | 酸塩基平衡 (- = アシドーシス) | pH, HCO3, pCO2, K |

## Coupling 依存グラフ

```
cardiac_function ──→ perfusion_status ──→ renal_function ──→ ph_status
                          ↑                       ↓
                    volume_status              ph_status (metabolic acidosis)

inflammation_level ──→ coagulation_status (DIC at infl > 0.7)
                   └──→ anemia_level      (slow, at infl > 0.5)

hepatic_function   ──→ coagulation_status (liver failure → coagulopathy)
```

## API リファレンス

### `initialize_state(profile, conditions, patient_id="") -> PhysiologicalState`

患者 profile と慢性疾患から初期 state を作成する。

```python
from clinosim.modules.physiology.engine import initialize_state

state = initialize_state(
    profile=patient.physiological_profile,
    conditions=patient.chronic_conditions,
    patient_id=patient.id,
)
```

**慢性疾患の影響** (ICD code prefix で判定):

| ICD prefix | 疾患 | 影響 |
|---|---|---|
| `N18` | CKD | `renal_function *= 1 - s*0.5`; s>0.5 で anemia_level +0.15, ph -s*0.1 |
| `I50` | 心不全 | `cardiac_function *= 1 - s*0.4`; s>0.3 で volume +s*0.3 |
| `K74` | 肝硬変 | `hepatic_function *= 1 - s*0.5`; coagulation +s*0.2 |
| `J44` | COPD | `ph_status -= s*0.05` |
| `I25` | 虚血性心疾患 | `cardiac_function *= 1 - s*0.2` |
| `I48` | 心房細動 | `cardiac_function *= 1 - s*0.1` |
| `J45` | 喘息 | `ph_status -= s*0.02` |

`s` = `condition.severity_score` (0-1)。

### `apply_disease_onset(state, severity, initial_impact) -> PhysiologicalState`

疾患発症の急性 impact を適用する (入院時に 1 回呼ぶ)。

```python
from clinosim.modules.physiology.engine import apply_disease_onset

initial_impact = disease_yaml["initial_impact"]
# {"mild": {"inflammation_level": 0.3}, "severe": {"inflammation_level": 0.6, ...}}
state = apply_disease_onset(state, severity="moderate", initial_impact=initial_impact)
```

内部で `clamp()` + `apply_coupling_rules()` を呼ぶ。

### `update(state, directive, time_step) -> PhysiologicalState`

時間を進める中核関数。 `directive.changes` の daily delta を time_step 分スケールして適用し、 coupling rules を走らせ、 `state.timestamp` を進める。

```python
from datetime import timedelta
from clinosim.modules.physiology.engine import update

# 1 hour step
state = update(state, directive, time_step=timedelta(hours=1))
# → each delta is multiplied by 1/24
```

### `apply_coupling_rules(state) -> None`

臓器間の physiological coupling を順序付きで適用する。 **順序重要**:

1. **Perfusion**: `cardiac * 0.8 + 0.2 + volume_effect`
   - volume < -0.5 (脱水) → perfusion ↓
   - volume > 0.5 かつ cardiac < 0.5 (overload + poor pump) → perfusion ↓
2. **Renal (pre-renal)**: `perfusion < 0.5` なら renal が `(0.5 - perfusion) * 0.3` 低下
3. **pH**: renal < 0.3 で代謝性アシドーシス、 perfusion < 0.4 で乳酸アシドーシス
4. **Coagulation (DIC)**: `inflammation > 0.7` で `(infl - 0.7) * 0.15` 増加
5. **Coagulation (liver failure)**: `hepatic < 0.4` で追加悪化
6. **Anemia (chronic inflammation)**: `inflammation > 0.5` で slow 増加

### `derive_lab_values(state, sex, age, has_diabetes=False, diabetes_controlled=True, rng=None) -> dict[str, float]`

Hidden state から検査値を計算する。 ノイズ無しの "真値" を返す (ノイズ付与は observation モジュール)。

```python
from clinosim.modules.physiology.engine import derive_lab_values

labs = derive_lab_values(state, sex="M", age=72, has_diabetes=True, diabetes_controlled=False)
# labs = {"CRP": 138.2, "WBC": 15400, "Creatinine": 1.8, "BNP": 820, ...}
```

**主な derivation 式** (抜粋):

```python
CRP        = 0.3 + 400 * inflammation ** 3          # 非線形
WBC        = 7000 + inflammation * 12000            # ただし infl>0.8 で leukopenic shift
PCT        = 0.03 * exp(inflammation * 7)
Albumin    = 4.2 - infl*2.0 - (1-hepatic)*1.5
Creatinine = base_cr / renal (renal>0.5)
BUN        = 15 / max(renal, 0.1), volume<-0.3 でさらに補正
K          = 4.0 + (1-renal)*2.2 + max(0,-ph)*0.8
BNP        = 30 * exp((1-cardiac)*4)
AST        = 25 + (1-hepatic)*500
T_Bil      = 0.8 + (1-hepatic)*15
PT_INR     = 1.0 + (1-hepatic)*2.0 + coagulation*1.5
Hb         = base_hb * (1 - anemia*0.7)
Lactate    = 1.0 + (1-perfusion)*12
pH         = 7.40 + ph_status*0.20
HCO3       = 24 + ph_status*12
Glucose    = base + infl*50                         # stress hyperglycemia
```

### `derive_vital_signs(state, baseline, timestamp) -> dict[str, float]`

Baseline vitals + hidden state からその時刻のバイタルを計算する (circadian 変動込み)。

```python
from clinosim.modules.physiology.engine import derive_vital_signs
from datetime import datetime

vitals = derive_vital_signs(state, patient.baseline_vitals,
                             timestamp=datetime(2024, 6, 15, 14, 30))
# vitals = {"temperature": 38.4, "heart_rate": 108, "systolic_bp": 124, ...}
```

| Vital | 式 |
|---|---|
| temperature | `baseline + infl*3.0 + circadian(hour)`, clamp 35-42 |
| heart_rate | `baseline + temp_effect*10 + (1-perfusion)*40 + anemia*15` |
| systolic_bp | `baseline + volume*15 - (1-perfusion)*40` |
| diastolic_bp | `baseline + volume*8 - (1-perfusion)*20` |
| respiratory_rate | `baseline + max(0,-ph)*10 + infl*4 + overload_effect` |
| spo2 | `baseline - (infl-0.3)*10 - overload_effect` |

Circadian: `0.3 * sin((hour-4) * π / 12)` (朝4時付近が最低体温)。

## データ構造

### `PhysiologicalState` (clinosim.types.clinical)

```python
@dataclass
class PhysiologicalState:
    patient_id: str = ""
    timestamp: datetime = ...
    inflammation_level: float = 0.0
    renal_function: float = 1.0
    cardiac_function: float = 1.0
    hepatic_function: float = 1.0
    anemia_level: float = 0.0
    coagulation_status: float = 0.0
    volume_status: float = 0.0
    perfusion_status: float = 1.0
    ph_status: float = 0.0
```

### `StateChangeDirective`

clinical_course や intervention モジュールが返す。 physiology は **これを適用するだけ**:

```python
@dataclass
class StateChangeDirective:
    source: str              # "disease_progression" | "natural_recovery" | "intervention"
    changes: dict[str, float]  # 変数名 → daily delta
    reason: str
```

## 使用例: 肺炎患者の 1 日

```python
from clinosim.modules.physiology.engine import (
    initialize_state, apply_disease_onset, update,
    derive_lab_values, derive_vital_signs,
)
from clinosim.types.clinical import StateChangeDirective
from datetime import datetime, timedelta

# 1. Baseline state from profile + chronic conditions
state = initialize_state(profile, patient.chronic_conditions, patient.id)

# 2. Apply disease onset (day 0)
state = apply_disease_onset(state, severity="moderate",
                             initial_impact={"moderate": {"inflammation_level": 0.5}})

# 3. Check derived values
labs = derive_lab_values(state, sex="M", age=72)
print(f"CRP on admission: {labs['CRP']:.1f} mg/L")  # → 50.3

# 4. Advance 1 day with a recovery directive
directive = StateChangeDirective(
    source="disease_progression",
    changes={"inflammation_level": -0.08, "volume_status": 0.02},
    reason="smooth_recovery day 3",
)
state = update(state, directive, time_step=timedelta(days=1))

# 5. Check new values
labs = derive_lab_values(state, sex="M", age=72)
vitals = derive_vital_signs(state, patient.baseline_vitals,
                             timestamp=datetime(2024, 6, 18, 9, 0))
print(f"CRP day 3: {labs['CRP']:.1f}, Temp: {vitals['temperature']}")
```

## 新しい変数・検査項目を追加する

### 新しい state 変数

1. `PhysiologicalState` (`clinosim/types/clinical.py`) にフィールドを追加
2. `_variable_range()` に range を登録
3. 必要なら `initialize_state()` で baseline 計算
4. `apply_coupling_rules()` に連関ロジック
5. `derive_lab_values()` / `derive_vital_signs()` に変換式
6. `clinical_course.get_daily_directive()` の `for var_name in [...]` リストに追加

### 新しい検査項目

1. `derive_lab_values()` 内に `labs["NewAnalyte"] = ...` を追加
2. observation モジュールの `BIOLOGICAL_CV`, `ANALYTICAL_CV`, `PRECISION` dict に登録
3. `determine_flag()` に reference range を登録 (H/L/critical flagging 用)
4. 関連疾患 YAML の期待分布 (benchmark 用) を更新

## 依存関係

- `clinosim.types.clinical` — `PhysiologicalState`, `StateChangeDirective`
- `clinosim.types.patient` — `PatientPhysiologicalProfile`, `BaselineVitals`, `ChronicCondition`
- `numpy` — lab derivation の一部 (optional rng)

**他モジュールへの依存なし** (physiology は leaf module)。

## 修正ガイド

### よくある修正シナリオ

| やりたいこと | 修正場所 | 影響範囲 |
|---|---|---|
| 新しい state 変数を追加 | `PhysiologicalState` (types/clinical.py) + 上記「新しい state 変数」手順 | clinical_course, observation, hospital_course_extractor |
| 新しいラボ項目を derive | `derive_lab_values()` + observation モジュール | FHIR Observation 出力、referenceRange |
| バイタル変換式を調整 | `derive_vital_signs()` | FHIR Observation、ナラティブ |
| coupling rule を変更 | `apply_coupling_rules()` | 全疾患の経過パターンに影響 |
| CRP変換ロジックの変更 | ここでは変更しない — output モジュールの `_JA_CONVERSION` (AD-42) | |

### 下流への影響マップ

```
physiology.derive_lab_values()
  ↓ used by
observation.generate_lab_result()  →  CIF OrderResult  →  FHIR Observation
  ↓ also used by
hospital_course_extractor.extract_lab_trends()  →  Narrative enrichment
```

### テスト

```bash
source .venv/bin/activate && python -m pytest tests/unit/test_physiology.py -v
```

変更後は `pytest -x -q` で全体回帰テストも実行すること。

カバー範囲: 初期化、疾患発症、時間更新、coupling rules (perfusion→renal→pH)、検査値 derivation (20+ 項目)、バイタル derivation with circadian。
