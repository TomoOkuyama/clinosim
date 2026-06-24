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

## 10 の状態変数

| 変数名 | 範囲 | 臨床的意味 | 主な影響先 |
|---|---|---|---|
| `inflammation_level` | 0–1 | 全身炎症 (cytokine burst) | CRP, WBC, PCT, Albumin, 発熱, 心拍 |
| `renal_function` | 0–1 | 腎機能 (糸球体濾過) | Cr, BUN, eGFR, K, pH |
| `cardiac_function` | 0–1 | 心ポンプ機能 | BNP, perfusion, BP |
| `hepatic_function` | 0–1 | 肝機能 | AST, ALT, T_Bil, PT-INR, Alb |
| `anemia_level` | 0–1 | 貧血の深度 | Hb, Hct, 代償性頻脈 |
| `coagulation_status` | 0–1 | 凝固障害 (DIC) | PT-INR, Plt |
| `volume_status` | -1 〜 +1 | 脱水 ↔ overload | BP, RR, Na, BUN/Cr比, BNP(壁ストレス) |
| `perfusion_status` | 0–1 | 組織灌流 | Lactate, BP, 腎血流 |
| `ph_status` | -1 〜 +1 | 酸塩基障害の大きさ (- = アシデミア) | pH, HCO3, pCO2, K |
| `respiratory_fraction` | 0 〜 1 | 障害軸 (0=代謝性→HCO3 / 1=呼吸性→pCO2) | pH, HCO3, pCO2 |
| `sodium_status` | -1 〜 +1 | Na バランス (- = 低 Na 血症 / + = 高 Na 血症) | Na (血清ナトリウム) |
| `glucose_status` | -1 〜 +1 | 急性血糖状態 (+ = DKA/HHS 高血糖 / - = 低血糖) | Glucose |
| `glycemic_control` | 0 〜 1 / None | 糖尿病の慢性血糖コントロール (1=良好 / 0=不良 / None=非糖尿病) | HbA1c, Glucose ベースライン |

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
| `I50` | 心不全 | `cardiac_function *= 1 - s*0.4`; s>0.3 で volume +s*0.3; **`sodium_status -= s*0.30`** (希釈性低 Na) |
| `K74` | 肝硬変 | `hepatic_function *= 1 - s*0.5`; coagulation +s*0.2; **`sodium_status -= s*0.40`** (希釈性低 Na) |
| `J44` | COPD | `ph_status -= s*0.05`; `respiratory_fraction = 1.0` (呼吸性軸) |
| `I25` | 虚血性心疾患 | `cardiac_function *= 1 - s*0.2` |
| `I48` | 心房細動 | `cardiac_function *= 1 - s*0.1` |
| `J45` | 喘息 | `ph_status -= s*0.02`; `respiratory_fraction = 1.0` (呼吸性軸) |
| `E11`/`E10` | 糖尿病 | `glycemic_control = condition.glycemic_control` (E11 activation 時にサンプル) → HbA1c / Glucose ベースラインを駆動 |

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
7. **Sodium (dehydration coupling)**: `volume_status < -0.35` (脱水) なら `sodium_status += (−volume_status − 0.35) * 1.2` — 自由水欠乏による高張性高 Na 血症を模擬

### `derive_lab_values(state, sex, age, has_diabetes=False, rng=None, hour=6, myocardial_injury=False) -> dict[str, float]`

Hidden state から検査値を計算する。 ノイズ無しの "真値" を返す (ノイズ付与は observation モジュール)。
HbA1c と Glucose ベースラインは `state.glycemic_control`(慢性血糖コントロール軸)から導出され、
互いに整合する(高 HbA1c ⇔ 高 Glucose)。`glycemic_control` は E11 慢性疾患から seed されるか、
DKA 等のシナリオ(`DiseaseProtocol.chronic_glycemic_control`)で上書きされる。

```python
from clinosim.modules.physiology.engine import derive_lab_values

labs = derive_lab_values(state, sex="M", age=72, has_diabetes=True)
# state.glycemic_control=0.2 (不良) なら HbA1c ~10.8%, Glucose ベースライン高め
# labs = {"CRP": 138.2, "WBC": 15400, "HbA1c": 10.8, "Glucose": 200, ...}
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
BNP        = 30 * exp((1-cardiac)*2.0 + max(0,volume)*(1-cardiac)*5.0)  # 心室壁ストレス=容量負荷×心機能低下
AST        = 25 + (1-hepatic)*500
T_Bil      = 0.8 + (1-hepatic)*15
PT_INR     = 1.0 + (1-hepatic)*2.0 + coagulation*1.5
Hb         = base_hb * (1 - anemia*0.7)
Lactate    = 1.0 + (1-perfusion)*12
Glucose    = base + infl*50                         # stress hyperglycemia
Na         = clamp(140 + sodium_status*14 - (1-renal)*3, 120, 160)
             # 正常患者: 140 mEq/L; ±1.0 で ±14 mEq/L スケール;
             # 腎機能低下 (renal<1) で軽度 Na 保持補正; clamp [120, 160]

# 酸塩基 (二軸: 代謝性 HCO3 / 呼吸性 pCO2 + 代償, AD-57)
mf, rf     = 1-respiratory_fraction, respiratory_fraction
HCO3       = 24 + ph_status*mf*24                   # 代謝性 → 重炭酸
pCO2       = 40 - ph_status*rf*40                   # 呼吸性 → CO2 (アシドーシス=貯留)
# 代償: 代謝性アシドーシス → 呼吸代償 (Winter's, pCO2↓=Kussmaul);
#       呼吸性アシドーシス → 腎代償 (0.35 mEq/mmHg, HCO3↑)
pH         = 6.1 + log10(HCO3 / (0.03*pCO2))        # Henderson-Hasselbalch

# 電解質 (BMP canonical 8 完成、PR #78)
base_cl    = 103.0 + sodium_status * 9.0                          # 電気的中性 (Na 連動)
hco3_def   = max(0, 24 - HCO3)
non_ag_f   = clamp(1.0 - anion_gap_status, 0.0, 1.5)
Cl         = clamp(base_cl + hco3_def * non_ag_f, 80, 125)        # AG-aware reciprocity
Ca         = clamp(9.5 - infl*0.8 - (1-renal)*0.7
                   - (1-hepatic)*0.4 + sodium_status*0.3, 5.5, 13) # total Ca, 多軸結合

# 凝固パネル (Coag panel LOINC 24373-3 完成 + Fibrinogen adjunct、2026-06-24)
APTT       = clamp(30 + coagulation_status*55, 20, 150)           # 秒、健常~30 / DIC で延長
PT         = clamp(12 * PT_INR, 9, 90)                            # 秒、ISI=1.0 一貫不変
Fibrinogen = clamp(300 + infl*250 - coagulation_status*280, 50, 800)
             # mg/dL、biphasic: 急性期反応で ↑、DIC で消費 ↓

# D-dimer (Phase 2a 2026-06-24): VTE-spectrum 分析物
age_factor = max(0, age - 50) * 0.005
D_dimer    = clamp(0.3 + age_factor + infl*0.5 + coagulation_status*1.5
                   + (4.0 if causes_vte else 0), 0.15, 20.0)
             # ug/mL FEU; PE/DVT/塞栓性脳梗塞で causes_vte=True → 臨床的陽性
```

凝固パネル軸(AD-57 BNP-pattern surgical、新 state 変数なし):
- `APTT`: `coagulation_status` 単軸由来。DIC + 肝合成低下を集約した既存上流(`apply_coupling_rules`)が
  正確に駆動する
- `PT` (秒): `PT_INR` から数学的に導出。LOINC では別コード(5902-2 PT vs 6301-6 PT-INR)、JLAC10
  では同一分析物コード `2B030` を共有(秒/INR 区別は 17 桁フルコードの結果識別側で表現)
- `Fibrinogen`: `inflammation_level`(急性期 reactant ↑)と `coagulation_status`(DIC で消費 ↓)
  が独立軸として競合する**biphasic**な公式。健常 ~300、敗血症 acute-phase で ~512、敗血症 + DIC
  で ~289、重症 DIC で floor 50。Coag panel(LOINC 24373-3)外で個別 Observation として出力
  (LOINC panel 定義に Fibrinogen は含まれない)
- `D_dimer`: `coagulation_status` + `inflammation_level` + 年齢 + 新 scenario flag `causes_vte` から導出。
  PE / DVT / 塞栓性脳梗塞 (`causes_vte: true`) で p50 ≥ 4 ug/mL FEU の臨床的陽性、健常 ~0.3、敗血症
  VTE なし非特異 < 1。年齢補正 +0.005/yr (50 歳以上)。出血性脳卒中はフラグ対象外
  (頭蓋内 fibrinolysis = `coagulation_status` で表現、機序が異なる)

### シナリオフラグ (Phase 2a 2026-06-24): `scenario_flags_from_protocol(protocol)` ヘルパ

`derive_lab_values` のシナリオフラグ引数(`myocardial_injury` / `causes_vte` / 将来追加)は、disease YAML protocol
(dict / Pydantic / None)から `scenario_flags_from_protocol()` ヘルパで一括抽出し、`**flags` でスプレッド渡しする。
コールサイト(inpatient Pass-1 + lagged + emergency + outpatient)はすべてヘルパ経由で配線され、新フラグ追加時の
配線忘れ(J5: emergency.py が `causes_myocardial_injury` を渡さず ED MI patient のトロポニン上昇が消えていた問題)を構造的に防ぐ。

### 医薬品フラグ (Phase 2b 2026-06-24): `medication_flags_from_context(patient, medication_orders, admission_date, current_day)` ヘルパ

シナリオフラグの **シブリングヘルパ**。`derive_lab_values` の医薬品駆動フラグ(`on_warfarin` / 将来追加)を
患者+エンカウンタコンテキストから検出する。Phase 2b は `{"on_warfarin": bool}` のみ返却。

**検出ルール**:
1. **慢性 warfarin**:`patient.current_medications` に warfarin 文字列(case-insensitive substring: `"warfarin"` / `"ワルファリン"` / `"coumadin"`)が含まれる
2. **院内 warfarin**:`medication_orders` に warfarin オーダーがあり、かつ `current_day - (ordered_date - admission_date).days >= 3`(ローディング 3 日ルール)

```python
from clinosim.modules.physiology.engine import (
    derive_lab_values, scenario_flags_from_protocol, medication_flags_from_context,
)

# inpatient Pass-1
flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(
        patient, medication_orders=[o for o in all_orders if o.order_type.value == "medication"],
        admission_date=admission_time.date(), current_day=day,
    ),
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, **flags)

# ED / outpatient = 慢性のみ(MAR/day なし)
flags = {**scenario_flags_from_protocol(protocol), **medication_flags_from_context(patient)}
```

**DOAC(apixaban / rivaroxaban / edoxaban / dabigatran)は意図的に検出しない** — DOAC では INR を臨床的に
モニターしない実態に忠実(rivaroxaban に PT 微影響あるが治療目標監視には使わない)。

将来の医薬品-検査値カップリング(ステロイド → glucose、利尿薬 → K、抗生剤 → CRP 等)は本ヘルパの
返却 dict を拡張するだけで全コールサイトに到達する。`derive_lab_values` に直接 `flag=value` 名前付き引数
を渡してはいけない(J5 同型 wiring defect 防止)。

`respiratory_fraction` は疾患シナリオの `acid_base_type`(既定 `metabolic`、COPD/喘息は
`respiratory`) または慢性 J44/J45 から設定される(エンジンにハードコードせずデータ駆動)。

`anion_gap_status` 軸(AD-57 二軸と直交、pH/HCO3/pCO2 に影響しない):
- `+1.0` = 高 AG アシドーシス(DKA / 敗血症 / 尿毒症): 未測定 anion (ケトン体/乳酸/SO4/PO4) が HCO3 欠損を埋めるので Cl は正常付近
- `0.0` = 通常 AG(健常 / AG が動かない疾患の default)
- `-1.0` = non-AG hyperchloremic アシドーシス(下痢 / RTA): Cl が HCO3 欠損を 1:1 で補填
- disease YAML の `initial_state_impact.anion_gap_status` で疾患シナリオから設定(20 疾患 + 2 encounter)、`apply_coupling_rules` で他 state に波及しない

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

### `derive_observed_vitals(state, baseline, timestamp, rng) -> dict[str, float]`

`derive_vital_signs` に測定ノイズ (device/observer variation) を加えた **観測値**。
inpatient / ED / outpatient が共有する単一バイタル生成パス (AD-57)。各 vital に
`rng.normal(0, σ)` (temperature は σ=0.5、他は σ=2) を加算し、SpO2 を [60, 100] に再 clamp。

```python
from clinosim.modules.physiology.engine import derive_observed_vitals

raw = derive_observed_vitals(state, patient.baseline_vitals, ts, rng)
# raw = {"temperature": 38.6, "heart_rate": 110, ...}  # ノイズ込みの観測値
```

## `sodium_status` 軸

### 概要

`sodium_status` は血清 Na バランスを表す隠れ状態変数 (範囲 -1.0 〜 +1.0) で、生成監査で
発見された「Na が 131-144 mEq/L の狭帯域に張り付く」ギャップを是正するために追加された。

| 値 | 臨床的意味 | 代表的 Na 値 |
|---|---|---|
| -1.0 | 重篤な低 Na 血症 (hyponatremia) | ≈ 126 mEq/L |
| 0.0 | 正常 | ≈ 140 mEq/L |
| +1.0 | 高 Na 血症 (hypernatremia) | ≈ 154 mEq/L |

### 3 つのドライバ

#### (a) 慢性ベースライン — `initialize_state()`

慢性疾患 severity_score `s` から初期値を設定する (希釈性低 Na 血症):

| ICD prefix | 疾患 | 影響 |
|---|---|---|
| `I50` | 心不全 (HF) | `sodium_status -= s * 0.30` (浮腫・RAA 系亢進による希釈) |
| `K74` | 肝硬変 | `sodium_status -= s * 0.40` (腹水・アルブミン低下による希釈) |

肝硬変は HF より係数が大きい (腹水貯留による希釈が顕著)。

#### (b) 脱水 coupling — `apply_coupling_rules()`

```
volume_status < -0.35 (脱水) のとき:
    sodium_status += (-volume_status - 0.35) * 1.2
```

自由水欠乏により細胞外液 Na 濃度が上昇する高張性高 Na 血症を模擬。閾値 -0.35 は
軽度脱水では coupling が起きず、中等度以上の脱水で緩やかに高 Na 方向へ押し上げる
設定になっている。

#### (c) 疾患 YAML による急性 impact — `apply_disease_onset()`

疾患 YAML の `initial_state_impact.sodium_status` を直接適用する (SIADH / 増悪)。
現在適用される疾患:

| 疾患 YAML | 想定メカニズム | `sodium_status` の典型値 |
|---|---|---|
| `heart_failure_exacerbation` | SIADH 様 / 希釈 | 負方向 |
| `bacterial_pneumonia` | SIADH (炎症性 ADH 分泌亢進) | 負方向 |
| `aspiration_pneumonia` | SIADH (炎症性 ADH 分泌亢進) | 負方向 |

### Na 写像式

```python
Na = clamp(140 + sodium_status * 14 - (1 - renal_function) * 3, 120, 160)
```

- **スケール係数 14**: `sodium_status = ±1.0` で Na が ±14 mEq/L 変動 (126 〜 154 mEq/L)
- **腎補正項 `(1-renal)*3`**: 腎機能低下時に Na 保持が増加する傾向を軽微に補正
- **clamp [120, 160]**: 生理的限界を超えないよう強制

### 決定論性

`sodium_status` の全操作 (初期化・coupling・disease onset) は RNG を使用しない。
同一 seed で同一 Na 値が再現されることが保証される。`derive_lab_values()` も決定論的
(ノイズは observation モジュール側で付与)。

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
    sodium_status: float = 0.0      # -1.0 = hyponatremia / +1.0 = hypernatremia
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

## Consumers

このモジュールに依存するもの (`derive_lab_values` / `derive_vital_signs` / `scenario_flags_from_protocol` / `medication_flags_from_context` 等):

| Caller | How | Impact |
|---|---|---|
| `simulator/inpatient.py:563-571` | Pass-1 lab loop で `derive_lab_values(state, ..., **flags)` 呼出 | core (主 simulation loop) |
| `simulator/inpatient.py:~1701` | unknown-condition encounter での `derive_lab_values` 呼出 (chronic-only flags) | core |
| `simulator/emergency.py:126-130` | ED admit lab derivation | core |
| `simulator/outpatient.py:152-160` | outpatient chronic followup lab derivation | core |
| `modules/patient/activator.py` | `PatientPhysiologicalProfile` 初期化で physiology types を参照 | core |
| `modules/clinical_course/` (README cross-ref) | daily state evolution が `StateChangeDirective` 経由で physiology に作用 | core |
| `tests/integration/test_clinical_pipeline.py` | 臨床 pipeline integration | guard |
| `tests/integration/test_glycemic_scenario.py` | glycemic / DKA scenario | guard |
| `tests/integration/test_sodium_axis.py` | dysnatremia integration | guard |
| `tests/integration/test_phase2b_anticoagulation_scenarios.py` | warfarin INR scenarios (Phase 2b) | guard |
| `tests/unit/test_physiology.py` | 全 derive_lab_values / state / coupling tests (72+) | guard |
| `tests/unit/test_medication_flags.py` | medication_flags_from_context helper tests (PR Phase 2b) | guard |
| `tests/unit/test_scenario_flags.py` | scenario_flags_from_protocol helper tests (PR Phase 2a) | guard |
| `tests/unit/test_blood_markers.py` | 血液 marker derive tests | guard |
| `tests/unit/test_distributive_shock.py` | distributive shock physiology tests | guard |
| `tests/unit/test_encounter_features.py` | encounter feature が physiology を消費 | guard |
| `tests/unit/test_population_demographics.py` | demographics + physiology baseline tests | guard |

> 新 scenario / medication flag を追加する際の helper 経由配線は
> [SCENARIO_FLAGS.md](../../../SCENARIO_FLAGS.md) を参照(J5 wiring defect 防止)。

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
