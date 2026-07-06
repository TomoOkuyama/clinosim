# clinosim.modules.clinical_course — 臨床経過エンジン

## 目的

入院から退院 (または死亡) までの **疾患の時間的進展 (trajectory)** をモデリングする。

physiology モジュールが「現在の状態」を保持するのに対し、 clinical_course は「次の1日に状態をどう動かすか」 (`StateChangeDirective`) を生成する。 これにより:

- 同じ疾患でも患者ごとに異なる経過 (smooth recovery / treatment resistant / sudden deterioration)
- 年齢・免疫反応性・治療感受性などの個人差が時間軸に反映される
- 診断の正誤が治療効果に反映され、誤診が CRP の遷延等の足跡として残る
- 合併症 (DVT、AKI、譫妄等) が確率的に発生し、カスケードする
- 治療と独立した自然回復 (innate immune response) も組み込まれる

## 設計原則

| # | 原則 | 説明 |
|---|---|---|
| 1 | **YAML 駆動 + フォールバック** | 各疾患の trajectory は disease YAML の `course_archetypes` に定義。未定義時は組み込み fallback を使用 |
| 2 | **6 アーキタイプ** | smooth_recovery / dip_then_recovery / plateau_then_recovery / treatment_resistant / gradual_deterioration / sudden_deterioration |
| 3 | **個人差の3経路** | (a) Amplitude: immune_reactivity, (b) Speed: 年齢×treatment_sensitivity, (c) Timing: effective day shift, (d) 日次ノイズ |
| 4 | **State directive のみ生成** | physiology の状態を直接書き換えず、 `StateChangeDirective` を返す。実際の適用は physiology.update() |
| 5 | **診断フィードバック** | 誤診時は recovery delta が dampening される (apply_diagnosis_modifier) |
| 6 | **線形補間** | trajectory は離散的な day point の dict。 中間日は線形補間で計算 |

## アーキタイプ一覧

| Name | 既定 prob | パターン |
|---|---|---|
| `smooth_recovery` | 55% | Day 1-2 から着実な改善 |
| `dip_then_recovery` | 20% | Day 1-3 に悪化、その後 gradual 改善 |
| `plateau_then_recovery` | 10% | 3-5 日変化なし、 その後改善 |
| `treatment_resistant` | 8% | 一次治療無効、 Day 3-5 で変更必要 |
| `gradual_deterioration` | 5% | 緩徐な悪化 → ICU |
| `sudden_deterioration` | 2% | Day 2 に sepsis/PE などで急変 |

確率は disease YAML の `course_archetypes.<name>.probability` で上書き可能。 **すべての確率はランタイムで正規化されるため合計 1.0 である必要はない**。

## API リファレンス

### `select_archetype(severity, profile, rng, protocol_archetypes=None) -> str`

患者ごとに 1 つのアーキタイプを選択する。 入院時に1度だけ呼ぶ。

```python
from clinosim.modules.clinical_course.engine import select_archetype
import numpy as np

rng = np.random.default_rng(42)
archetype = select_archetype(
    severity="moderate",
    profile=patient.physiological_profile,
    rng=rng,
    protocol_archetypes=disease_yaml["course_archetypes"],
)
# → "smooth_recovery"
```

**Severity modifier**:
- `severe`: gradual/sudden_deterioration ×2.0、smooth_recovery ×0.6
- `mild`: smooth_recovery ×1.3、deterioration 系 ×0.3

**Profile modifier**:
- `immune_reactivity < 0.3` (免疫低下): treatment_resistant +0.10
- `treatment_sensitivity > 1.2`: smooth_recovery +0.10

### `get_daily_directive(archetype_name, day, profile, protocol_archetypes=None, age=70, rng=None) -> StateChangeDirective`

指定日における state 変化指示を返す。 シミュレーションループから日次で呼ばれる。

```python
from clinosim.modules.clinical_course.engine import get_daily_directive

directive = get_daily_directive(
    archetype_name="smooth_recovery",
    day=3,
    profile=patient.physiological_profile,
    protocol_archetypes=disease_yaml["course_archetypes"],
    age=patient.age,
    rng=rng,
)
# directive.changes = {
#     "inflammation_level": -0.08,
#     "volume_status":      0.02,
#     ...
# }
```

**個人差変調 (4 つの軸)**:

1. **Amplitude (振幅)** — `immune_reactivity / 0.5` で `inflammation_level` の delta をスケール
2. **Speed (速度)** — 年齢ベースの `speed_factor`:
   - age < 50: 1.2x、age 50-70: 1.0x、age 70-80: 0.85x、age 80-90: 0.7x、age 90+: 0.55x
3. **Timing (時間軸 stretch)** — `effective_day = day * speed_factor`
4. **Noise (生物学的揺らぎ)** — 比例ノイズ + 約 10% の確率で "bump day" (CRP の Day 4 上振れ等を再現)

### `evaluate_complications(day, state, patient, complications, active_complications, rng) -> list[dict]`

合併症の発症判定を行う。 disease YAML の `complications` リストを反復し、 確率的に発症した合併症を返す。

```python
from clinosim.modules.clinical_course.engine import evaluate_complications

triggered = evaluate_complications(
    day=hospital_day,
    state=current_state,
    patient=patient,
    complications=disease_yaml["complications"],
    active_complications=active_set,  # mutated
    rng=rng,
)
# triggered = [{"name": "AKI", "state_impact": {...}, "actions": [...]}, ...]
```

**判定フロー**:

1. 既に active なら skip
2. `onset_day_range: [start, end]` 内でなければ skip
3. **カスケード合併症**: `parent_complication` が active でなければ skip
4. 確率: `probability_per_day` (独立) または `probability_given_parent` (カスケード)
5. **risk factor 評価**: 各 condition (例 `"age_over_75"`, `"renal_function < 0.4"`) が真なら multiplier を乗算
6. `rng.random() < prob` なら発症、 `active_complications` に追加

サポートする risk factor 文字列:
- `age_over_<N>` — 患者年齢
- `renal_function < <X>` / `volume_status < <X>` / `perfusion_status < <X>`
- `delirium_susceptibility > <X>`
- `immobility_days > <N>`

### `compute_diagnosis_effectiveness(working_diagnosis, ground_truth_disease, diagnosis_confidence, day, diagnostic_difficulty=0.3) -> float`

診断の正確さに基づく治療効果スコア (0.0-1.0) を返す。

```python
from clinosim.modules.clinical_course.engine import compute_diagnosis_effectiveness

eff = compute_diagnosis_effectiveness(
    working_diagnosis="bacterial_pneumonia",
    ground_truth_disease="bacterial_pneumonia",
    diagnosis_confidence=0.85,
    day=2,
    diagnostic_difficulty=0.30,  # 肺炎は中程度
)
# → 0.94 (correct dx + high confidence)
```

| 状況 | 戻り値 |
|---|---|
| 診断未定 (empiric therapy) | `0.4 - difficulty * 0.2` (0.15 〜 0.4) |
| 正診 + confidence ≥ threshold | `0.6 + confidence * 0.4` (最大 1.0) |
| 正診 + confidence 低 | `0.4 + confidence * 0.5` |
| 誤診 | `0.2 - difficulty * 0.1` (0.05 〜 0.2) |

`diagnostic_difficulty` は disease YAML の `diagnostic` セクションから読み込む:
- 0.05: 大腿骨頸部骨折 (X-ray で即確定)
- 0.25: UTI (尿検査 + 培養)
- 0.30: 肺炎 (CXR + 培養)
- 0.35: 心不全増悪 (BNP は有用だが肺炎と重複)
- 0.40: COPD 増悪 (肺炎・心不全と重複)

### `apply_diagnosis_modifier(directive, effectiveness, current_volume=0.0, current_ph=0.0) -> StateChangeDirective`

`compute_diagnosis_effectiveness` の結果を directive に適用する。 **改善方向 (recovery) の delta のみ** ダンプし、 deterioration 方向はそのまま。

```python
from clinosim.modules.clinical_course.engine import apply_diagnosis_modifier

modified = apply_diagnosis_modifier(directive, effectiveness=0.3,
                                    current_volume=state.volume_status)
# 誤診の場合、 inflammation_level の負の delta (CRP 低下) が 0.3 倍に dampening
```

改善方向の判定 (`_is_improvement`):
- **負の delta が改善**: `inflammation_level`, `anemia_level`, `coagulation_status`
- **正の delta が改善**: `renal_function`, `cardiac_function`, `hepatic_function`, `perfusion_status`
- **0 に近づくのが改善**: `volume_status`, `ph_status` (current の符号で判定)

### `natural_recovery_directive(day, disease_id, severity, profile) -> StateChangeDirective`

治療と独立した自然治癒 (innate immune response、 homeostasis) を表現する小さな directive。

```python
from clinosim.modules.clinical_course.engine import natural_recovery_directive

natural = natural_recovery_directive(
    day=5, disease_id="bacterial_pneumonia",
    severity="moderate", profile=patient.physiological_profile,
)
# → StateChangeDirective(source="natural_recovery", changes={
#     "inflammation_level": -0.005, "volume_status": -0.005})
```

- 基準値: `0.01 * immune_reactivity * severity_scale`
- severity_scale: mild=1.2, moderate=1.0, severe=0.6
- Day 7 以降 ×0.7、 Day 14 以降 ×0.5 (acute phase response が薄れる)

## データ構造

### YAML スキーマ (`course_archetypes`)

```yaml
course_archetypes:
  smooth_recovery:
    probability: 0.55
    trajectory:
      inflammation_level: {0: 0.05, 1: -0.02, 3: -0.08, 7: -0.06, 14: -0.02}
      volume_status:      {0: 0.02, 3: 0.02, 7: 0.01}
      renal_function:     {0: 0.00, 5: 0.01}
  sudden_deterioration:
    probability: 0.02
    trajectory:
      inflammation_level: {0: 0.05, 2: 0.30, 5: -0.05}
      perfusion_status:   {0: 0.00, 2: -0.30, 5: 0.05}
```

各 trajectory key は **その日の daily delta** (state は physiology.update() で 1 日分積算される)。 定義されていない日は線形補間。

### 合併症 YAML スキーマ

```yaml
complications:
  - name: "AKI"
    onset_day_range: [1, 7]
    probability_per_day: 0.03
    risk_factors:
      - condition: "age_over_75"
        multiplier: 2.0
      - condition: "perfusion_status < 0.5"
        multiplier: 3.0
    state_impact:
      renal_function: -0.15
    actions: ["nephrology_consult", "iv_fluids"]
  - name: "septic_shock"
    parent_complication: "AKI"     # cascade
    probability_given_parent: 0.10
    onset_day_range: [2, 10]
```

## 使用例: 1 日のシミュレーションループ

```python
from clinosim.modules.clinical_course.engine import (
    select_archetype, get_daily_directive,
    compute_diagnosis_effectiveness, apply_diagnosis_modifier,
    natural_recovery_directive, evaluate_complications,
)
from clinosim.modules.physiology.engine import update

# Once per admission
archetype = select_archetype(severity, patient.profile, rng, disease_yaml["course_archetypes"])

# Daily loop
for day in range(0, los_days):
    # 1. Disease progression directive
    directive = get_daily_directive(archetype, day, patient.profile,
                                     disease_yaml["course_archetypes"],
                                     age=patient.age, rng=rng)

    # 2. Apply diagnosis-treatment feedback
    eff = compute_diagnosis_effectiveness(
        diff.working_diagnosis, ground_truth_disease,
        diff.candidates[0].probability, day,
        diagnostic_difficulty=disease_yaml["diagnostic"]["difficulty"],
    )
    directive = apply_diagnosis_modifier(directive, eff,
                                          current_volume=state.volume_status)

    # 3. Add natural recovery
    natural = natural_recovery_directive(day, disease_id, severity, patient.profile)
    for var, delta in natural.changes.items():
        directive.changes[var] = directive.changes.get(var, 0.0) + delta

    # 4. Apply to physiological state
    state = update(state, directive, time_step=timedelta(days=1))

    # 5. Evaluate complications
    triggered = evaluate_complications(day, state, patient,
                                        disease_yaml["complications"],
                                        active_complications, rng)
    for comp in triggered:
        # apply state_impact, queue actions
        ...
```

## 依存関係

- `clinosim.types.clinical` — `StateChangeDirective`
- `clinosim.types.patient` — `PatientPhysiologicalProfile`
- `clinosim.modules._shared` — `normalize_probabilities`
- `numpy` — 確率的選択

**他の domain module への依存なし** (physiology の状態を直接読み書きしない、 directive ベースで疎結合。`_shared` は infra ヘルパーであり domain module ではない)。

## Consumers

このモジュールに依存するもの:

| Caller | How | Impact |
|---|---|---|
| `simulator/inpatient.py` | daily cycle で archetype 駆動の状態進行を `update_state()` 経由で適用 | core (主 simulation loop) |
| `tests/integration/test_clinical_pipeline.py` | 臨床 pipeline integration test | guard |
| `tests/unit/test_clinical_course.py` | archetype + directive logic unit tests | guard |
| `tests/unit/test_diagnosis_feedback.py` | diagnosis feedback loop test | guard |

## 修正ガイド

### よくある修正シナリオ

| やりたいこと | 修正場所 | 影響範囲 |
|---|---|---|
| 新しいアーキタイプを追加 | `select_archetype()` の case 追加 + 対応 trajectory 関数 | 全新疾患がこのアーキタイプを選択可能に |
| 合併症の発火条件を変更 | `evaluate_complications()` | physiology state 推移、LOS に影響 |
| 自然回復速度を調整 | `natural_recovery_directive()` | 退院タイミングに影響 |
| 治療効果を変更 | `treatment_response_directive()` | 検査値推移に影響 |
| 新しい state 変数への対応 | `for var_name in [...]` リストに追加 | physiology モジュール変更と同時に行う |

### 関連モジュール

```
disease YAML (course_archetypes)
  ↓ archetype → trajectory
clinical_course.get_daily_directive()
  ↓ StateChangeDirective
physiology.update(state, directive)
  ↓ updated PhysiologicalState
observation / order → CIF → FHIR
```

### テスト

```bash
source .venv/bin/activate && python -m pytest tests/unit/test_clinical_course.py -v
```

カバー範囲: archetype 選択、 daily directive、 線形補間、 severity/profile modifier、 診断フィードバック、 自然回復、 合併症カスケード。
