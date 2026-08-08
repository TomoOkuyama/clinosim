# BMP Cl/Ca physiology — design spec (PR #74/#75 follow-up, Phase 1)

**Date**: 2026-06-23
**Status**: DRAFT (awaiting user review)
**Author**: Claude (clinosim session)

## 1. Goal

`derive_lab_values` で **Cl (Chloride) と Ca (Calcium) を生成**し、`lab_panels.yaml` BMP canonical 8 を完成させる。これに伴い:

- `lab_panel_groups.yaml` の BMP `min_components` を 5→7 へ raise(canonical N − 1 rule、N=8)
- 既存の AD-57 acid-base 二軸モデル(metabolic HCO3 / respiratory pCO2)と直交する **`anion_gap_status` 軸**を `PhysiologicalState` に新設し、Cl の AG-aware coupling を実現
- 実病院 BMP record と整合する Cl/Ca 値域(DKA で AG > 20、下痢で hyperchloremic non-AG、normal AG 8–12 等)

## 2. リアリティの定義(ユーザー方針)

「リアリティがある = **実際の病院でも同様のデータが記録される**」。

- **BMP (LOINC 51990-0)** は US/JP の標準パネルで、Na/K/Cl/CO2/BUN/Cr/Glucose/Ca の **8 component** が一括 report される(Quest/LabCorp/NLM 公式定義)。実病院で BMP を order すると Cl と Ca は必ず result に含まれる。clinosim の `lab_panels.yaml` BMP は既にこの canonical 8 を宣言しているが、`derive_lab_values` が Cl/Ca を生成しないため Pass 2 で silently dropped されている(`lab_panel_groups.yaml` のコメント参照、emit-able N = 6)。
- 本 PR で Cl/Ca が出力されることで「BMP order = 8 component result」が実病院と一致する。
- AG 軸の設定は「**実病院で測定すると AG の有意な変動が記録される疾患**」のみに行う。AG が normal range のまま記録される疾患(骨折、UTI uncomplicated、COPD pure respiratory acidosis 等)は default 0 で実病院記録と整合。

## 3. Phase 分解(α/β/γ の β を採用)

| Phase | scope | timing |
|-------|-------|--------|
| **Phase 1(本 PR)** | Cl/Ca physiology 追加、`anion_gap_status` 軸新設、disease/encounter YAML 設定、BMP min_components 5→7 | 本セッション |
| Phase 2 (後続別 PR) | iCa (LOINC 1994-3) を ABG/別ラボとして追加、Cl の chloride_loss 軸(嘔吐 = hypochloremic alkalosis)、Ca 補正計算(albumin-corrected Ca)の text annotation 検討 | 別セッション |
| Phase 3 (将来) | UA panel 8 analyte、Coag panel(PT/APTT)起動等 | 別タスク |

## 4. 物理式設計

### 4.1 Cl (Chloride)

```python
# Cl は electroneutrality(Na 連動)+ HCO3 互恵(non-AG metabolic acidosis では
# HCO3 低下分を Cl が 1:1 補填して hyperchloremic に、high-AG では unmeasured
# anion=lactate/ketone/SO4/PO4 で補填され Cl 正常維持)。
base_cl = 103.0 + state.sodium_status * 9.0       # Na と平行(Na 130-150 で Cl 95-112)
hco3_deficit = max(0.0, 24.0 - labs["HCO3"])      # 既算出済 HCO3 を参照
non_ag_fraction = clamp(1.0 - state.anion_gap_status, 0.0, 1.5)
labs["Cl"] = clamp(base_cl + hco3_deficit * non_ag_fraction, 80.0, 125.0)
```

#### 値域検証(設計時 hand calc)

| 状態 | sodium_status | HCO3 | AG_axis | Cl 計算 | AG = Na − Cl − HCO3 | 臨床判定 |
|------|---------------|------|---------|---------|---------------------|---------|
| 健常 | 0 | 24 | 0 | 103 | 13 | normal AG ✓ |
| DKA (重症) | 0 | 10 | 1.0 | 103 | 27 | high-AG ✓ |
| 敗血症 | 0 | 18 | 0.7 | 105 | 17 | high-AG mixed ✓ |
| AKI/uremia | 0 | 18 | 0.5 | 106 | 16 | high-AG mixed ✓ |
| 下痢 GE | 0 | 15 | -0.5 | 117 (clamp 125 余地) | 8 | non-AG hyperchloremic ✓ |
| 脱水 | +0.3 | 22 | 0 | 108 | 10 | 軽度 hyperchloremic ✓ |
| HF (代償) | -0.2 (希釈性低 Na) | 24 | 0 | 101 | 13 | normal ✓ |
| COPD (CO2 retention) | 0 | 30 (代償 HCO3 ↑) | 0 | 103 (hco3_deficit=0) | 7 | respiratory alkalosis-shift ✓ |

### 4.2 Ca (Total Calcium)

```python
# Total Ca はラボ標準報告値(JCCLS 3H030 / LOINC 17861-6)。補正 Ca と iCa
# は実臨床で医師が手計算/別検体で扱うので、本 PR では生成しない(Phase 2)。
# 多軸 linear coupling: 敗血症 / CKD / 肝不全で低下、軽度脱水(高 Na 寄り)で上昇。
base_ca = 9.5
ca = base_ca \
     - state.inflammation_level * 0.8 \
     - (1.0 - state.renal_function) * 0.7 \
     - (1.0 - state.hepatic_function) * 0.4 \
     + state.sodium_status * 0.3
labs["Ca"] = clamp(ca, 5.5, 13.0)
```

#### 値域検証

| 状態 | infl | renal | hepatic | sodium_status | Ca 計算 | 臨床判定 |
|------|------|-------|---------|----------------|---------|---------|
| 健常 | 0.03 | 1.0 | 1.0 | 0 | 9.48 | normal (8.5–10.5) ✓ |
| 敗血症 | 0.85 | 0.7 | 0.9 | 0 | 8.66 | 軽度低 Ca ✓ |
| CKD stage4 | 0.05 | 0.3 | 1.0 | 0 | 8.97 | 軽度低 Ca ✓ |
| AKI 重症 | 0.10 | 0.2 | 0.9 | 0 | 8.78 | 軽度低 Ca ✓ |
| 肝硬変非代償 | 0.10 | 0.85 | 0.4 | -0.1 | 8.85 | 軽度低 Ca ✓ |
| 急性膵炎 | 0.65 | 0.85 | 1.0 | 0 | 8.87 | 軽度低 Ca ✓(膵炎で Ca↓ は実臨床所見) |
| DKA | 0.20 | 0.85 | 1.0 | 0 | 9.23 | 正常下限 ✓ |
| 脱水 | 0.05 | 0.85 | 1.0 | +0.3 | 9.45 | 正常範囲 ✓ |

## 5. PhysiologicalState 変更

`clinosim/types/clinical.py`:

```python
@dataclass
class PhysiologicalState:
    # ... 既存 fields ...
    respiratory_fraction: float = 0.0  # 0.0–1.0  (AD-57)
    # NEW: Anion gap axis. Distinct from ph_status (acid-base magnitude) and
    # respiratory_fraction (metabolic vs respiratory). Drives the Cl axis only —
    # does NOT mutate pH/HCO3/pCO2.
    # 0.0  = normal AG (8–12), Cl follows HCO3 1:1 if HCO3 dropped (default healthy)
    # +1.0 = high-AG metabolic acidosis (DKA/sepsis/uremia/lactic), Cl stays normal,
    #        unmeasured anion (ketone/lactate/SO4/PO4) absorbs the HCO3 deficit
    # -1.0 = non-AG (hyperchloremic) acidosis (diarrhea, RTA, saline-induced), Cl
    #        rises by HCO3 deficit × 1.0–1.5 to maintain electroneutrality
    anion_gap_status: float = 0.0  # -1.0–+1.0
    # ... 残り既存 fields ...
```

**注意**: 新軸の default は 0.0(健常 = normal AG)。`apply_coupling_rules` で他 state に波及させない(直交)。`initialize_state` で patient profile から設定する経路は無し(疾患シナリオ依存)。

## 6. disease/encounter YAML 設定対象

「**実病院で AG の有意な変動が記録される疾患**」のみ設定。値は教科書ベース(Harrison's, Nelson's, Lab Tests in Clinical Practice)。

> **注(2026-06-23 実装後修正)**: encounter 編集対象は当初 3 ファイル(viral_gastroenteritis / food_poisoning / chemical_exposure)で書いたが、`chemical_exposure.yaml` は `initial_state_impact` ブロック自体を持たないため Phase 1 scope 外として除外。実装は **2 ファイル**(viral_gastroenteritis / food_poisoning)。

### 6.1 Disease(20 ファイル)

| ファイル | severity 区分 | 設定値 | 根拠 |
|----------|--------------|--------|------|
| `diabetic_ketoacidosis.yaml` | mild / moderate / severe | 0.7 / 1.0 / 1.0 | ケトン体駆動の典型 high-AG(AG 20–35) |
| `sepsis.yaml` | mild / moderate / severe / septic_shock | 0.3 / 0.6 / 0.8 / 1.0 | 乳酸 acidosis、severity-graded(Surviving Sepsis Campaign) |
| `acute_kidney_injury.yaml` | mild / moderate / severe | 0.2 / 0.4 / 0.6 | uremic acidosis(BUN/Cr/PO4/SO4 蓄積、AG 上昇) |
| `acute_mi.yaml` | mild / moderate / severe / cardiogenic_shock | 0 / 0.1 / 0.3 / 0.6 | shock で乳酸上昇、軽症は AG normal |
| `acute_pancreatitis.yaml` | mild / moderate / severe | 0.1 / 0.3 / 0.5 | SIRS / 重症膵炎で乳酸 |
| `industrial_burn_severe.yaml` | (severity 既設定なら mirror) | 0.4–0.5 | 重症熱傷で組織灌流低下+乳酸 |
| `electrical_injury.yaml` | | 0.3 | 横紋筋融解 + AKI |
| `crush_injury_hand.yaml` | | 0.3 | 横紋筋融解 |
| `traffic_accident_severe.yaml` | | 0.3 | 外傷性 shock |
| `fall_from_height.yaml` | | 0.2 | 外傷性 shock(軽め) |
| `aspiration_pneumonia.yaml` | mild / moderate / severe | 0 / 0.2 / 0.5 | sepsis 様で乳酸 |
| `bacterial_pneumonia.yaml` | mild / moderate / severe | 0 / 0.2 / 0.4 | 同上 |
| `gi_bleeding.yaml` | mild / moderate / severe | 0 / 0.1 / 0.3 | hypovolemic shock で乳酸 |
| `liver_cirrhosis_decompensated.yaml` | | 0.3 | 乳酸 clearance 低下 + sepsis 寄り |
| `hemorrhagic_stroke.yaml` | | 0.2 | 大規模脳出血で perfusion 低下 |
| `cerebral_infarction.yaml` | | 0.1 | 軽度(大梗塞のみ AG ↑) |
| `pulmonary_embolism.yaml` | | 0.2 | 重症 PE で shock |
| `ileus.yaml` | | 0.2 | 腸壊死/穿孔リスクで乳酸 |
| `acute_appendicitis.yaml` | | 0.1 | 穿孔/腹膜炎で sepsis 様 |
| `acute_cholecystitis.yaml` | | 0.2 | cholangitis sepsis 様 |

### 6.2 Encounter(2 ファイル、実装後修正)

| ファイル | 設定値 | 根拠 |
|----------|--------|------|
| `viral_gastroenteritis.yaml` | mild=-0.3, moderate=-0.5, severe=-0.6 | 下痢主体 = HCO3 stool loss = non-AG hyperchloremic acidosis(教科書典型) |
| `food_poisoning.yaml` | mild=-0.2, moderate=-0.4, severe=-0.5 | 嘔吐/下痢の混在、下痢駆動の non-AG が支配的、純粋 GE よりやや軽め |

> **scope 外:** `chemical_exposure.yaml` は `initial_state_impact` ブロックを持たず、AG 動態も物質依存(methanol = AG↑、アルカリ曝露 = AG↓ 等)。default 0 で運用、物質特化 encounter が追加されたら別 PR で再検討。

### 6.3 設定しないもの(default 0 = normal AG が実病院記録と整合)

- 呼吸器系 pure(`copd_exacerbation`, `asthma_exacerbation`) — 呼吸性、AG normal
- 軽度感染(`urinary_tract_infection`, `cellulitis`, `influenza`) — AG normal
- 心律動異常(`atrial_fibrillation_rvr`) — AG normal
- 心不全代償(`heart_failure_exacerbation`) — AG normal(shock 帯のみ動くが ph_status で表現済)
- 骨折系(`hip_fracture`, `wrist_fracture_surgical`, `vertebral_compression_fracture`) — AG normal
- 神経系(`subdural_hematoma`, `deep_vein_thrombosis`) — AG normal
- すべての外来 routine encounter(`annual_health_screening`, `prescription_renewal`, `preoperative_assessment` 等) — AG normal

## 7. 配線変更

### 7.1 `lab_panel_groups.yaml`

```yaml
  BMP:
    loinc: "51990-0"
    display: "Basic metabolic 2000 panel - Serum or Plasma"
    components: [Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]
    # canonical N − 1 rule: BMP has 8 listed components and after Phase 1
    # (PR #N), derive_lab_values produces all 8. Validated by
    # scratchpad/cbc_bmp_panel_audit.py: the 5th-percentile bucket of
    # "panel-order-placed" days is ≥ 7, so 7 accepts every real BMP.
    min_components: 7
```

### 7.2 `derive_lab_values` 配置

Cl は HCO3 算出済(`labs["HCO3"]`)を参照する必要があるため、blood gas セクションの **後** に追加。Ca は inflammation/renal/hepatic/sodium に依存するので、blood gas 後・Glucose 前のどこでも可。順序例:

```python
# --- pH / Blood gas (既存) ---
labs["HCO3"] = hco3
labs["pCO2"] = pco2
labs["pH"] = ...
labs["pO2"] = ...

# --- Electrolytes (NEW): Cl/Ca complete the BMP canonical 8 ---
# Cl: electroneutrality (Na-linked) + AG-aware HCO3 compensation
base_cl = 103.0 + state.sodium_status * 9.0
hco3_deficit = max(0.0, 24.0 - labs["HCO3"])
non_ag_fraction = clamp(1.0 - state.anion_gap_status, 0.0, 1.5)
labs["Cl"] = clamp(base_cl + hco3_deficit * non_ag_fraction, 80.0, 125.0)
# Ca: total calcium (lab-standard report). Corrected Ca / iCa are Phase 2.
ca = 9.5 \
     - state.inflammation_level * 0.8 \
     - (1.0 - state.renal_function) * 0.7 \
     - (1.0 - state.hepatic_function) * 0.4 \
     + state.sodium_status * 0.3
labs["Ca"] = clamp(ca, 5.5, 13.0)

# --- Glucose / HbA1c (既存) ---
...
```

## 8. データ flow と AD-16

- `derive_lab_values` は **純粋関数**(rng なし)。Cl/Ca 追加で **RNG 消費ゼロ**。AD-16 自動準拠
- `anion_gap_status` 軸の coupling 経路は **Cl 式の中のみ**。`apply_coupling_rules` で他 state に波及させない
- PR #74 で確立した per-parent `panel_specimen_seed` → Cl/Ca も BMP panel の child として同じ sub-rng で specimen-rejection/hemolysis 引かれる → AD-16 維持(各 BMP order は 1 specimen の 8 component として一括 reject/accept)
- 既存出力経路は変更なし:`inpatient.py:644` のコメント「BMP Cl/Ca until derive_lab_values produces them」が解消される(silently dropped → emit-able)

## 9. test 戦略

### 9.1 unit test (`tests/unit/test_physiology.py`)

新規 acceptance test:
- `test_cl_normal_healthy_state` — 健常 state で Cl = 103 ± 2
- `test_cl_high_ag_dka_keeps_normal` — DKA state(ph=-0.5, AG=1.0)で Cl が normal range 維持(< 108)
- `test_cl_non_ag_diarrhea_hyperchloremic` — 下痢 state(ph=-0.3, AG=-0.5)で Cl > 110(hyperchloremic)
- `test_cl_anion_gap_calculation` — 各 state で `Na - Cl - HCO3` を計算し DKA で AG > 20、健常で AG 8-14
- `test_ca_normal_healthy_state` — 健常で Ca = 9.5 ± 0.3
- `test_ca_sepsis_low_calcium` — 敗血症 state(inflammation=0.85)で Ca < 9.0
- `test_ca_ckd_low_calcium` — CKD state(renal=0.3)で Ca < 9.2
- `test_ca_dehydration_normal_or_slight_high` — 脱水(sodium=+0.3)で Ca が normal range 上限維持
- `test_anion_gap_status_does_not_mutate_state` — `apply_coupling_rules` 後に他 state(ph_status/HCO3/pCO2 等)が AG 軸の影響を受けない

### 9.2 integration test (`tests/unit/test_diagnostic_report_panels.py`)

- BMP DR の `result[]` が 7+ component を持つよう更新(現状の 5+ から閾値 raise)
- 既存 CBC/LFT/Lipid/ABG/Coag/UA DR の threshold は変更なし

### 9.3 byte-diff invariant (master vs branch、seed=42)

`scratchpad/bmp_cl_ca_byte_diff.py`(新規)で:
- US p=2000、JP p=2000 を master ブランチと feature ブランチで生成
- **全 NDJSON / CSV / manifest** を hashlib SHA-256 で比較
  - `Patient.ndjson` / `Encounter.ndjson` / `MedicationAdministration.ndjson` / `Condition.ndjson` 等 = byte-identical(cohort drift ゼロ)
  - `Observation.ndjson` のみ差分(Cl/Ca 追加分 + AG 軸を設定した疾患の Cl/Ca 値が現実的範囲に)
  - 既存 BMP 構成要素(Na/K/HCO3/BUN/Cr/Glucose)も byte-identical(physiology 式は不変)
  - 患者数完全一致(US 1274/1274 等)

**gate**: 上記 invariant が満たされない場合 → state 経路 cascade を疑い、再設計

### 9.4 clinical coherence audit (`scratchpad/bmp_cl_ca_audit.py` 新規)

- US p=4000、JP p=2000 で疾患別 Cl/Ca/AG の median と percentile 算出
- 期待値(設計時 hand-calc 一致):
  - DKA: Cl 100-105、Ca 9.0-9.4、AG 20-30
  - 敗血症: Cl 100-104、Ca 8.5-9.0、AG 15-20
  - 下痢 GE: Cl 108-115、Ca 9.0-9.5、AG 6-10
  - CKD: Cl 100-105、Ca 8.8-9.2、AG 12-18
  - 健常 (annual_health_screening): Cl 99-106、Ca 9.0-10.0、AG 8-14
- 期待値から ±2 を超える乖離があれば formula 再調整

### 9.5 panel min_components audit (`scratchpad/cbc_bmp_panel_audit.py` 更新)

- `LOINC_TO_COMPONENT` に `"2075-0": "Cl"`, `"17861-6": "Ca"` 追加
- `BMP_COMPONENTS` set に `"Cl"`, `"Ca"` 追加
- `canonical["BMP"] = 8`、`plan["BMP"] = 7` に更新
- US p=4000 で BMP 7-component floor(5th percentile)が ≥ 7 を確認

## 10. workflow gates(順序)

1. PhysiologicalState に `anion_gap_status` 追加 + 既存 test 緑(state 不変、AG 軸 default 0)
2. derive_lab_values に Cl/Ca 追加 + unit test 緑(値域・状態別)
3. disease YAML 編集(20 ファイル)+ integration test 緑
4. encounter YAML 編集(3 ファイル)+ integration test 緑
5. `lab_panel_groups.yaml` BMP min_components 5→7 + integration test 更新
6. `cbc_bmp_panel_audit.py` 更新 + US p=4000 audit 通過
7. `bmp_cl_ca_byte_diff.py` 新規 + US/JP p=2000 byte-diff invariant 通過(Observation.ndjson 以外 IDENTICAL)
8. `bmp_cl_ca_audit.py` 新規 + clinical coherence 期待値確認
9. e2e 全テスト緑(unit/integration/e2e)
10. spec/plan/audit doc commit
11. PR 起票、message に audit 数値含める

## 11. 後続 phase(本 PR scope 外)

- **Phase 2 (PR4 別セッション)**: iCa (LOINC 1994-3) を ABG セクション or 別ラボとして追加、Cl hypochloremic alkalosis 軸(嘔吐主体の `viral_gastroenteritis` severe / `food_poisoning` 等で `chloride_loss_status` を新軸 or 既存 AG 軸 < -0.5 で表現)
- **Phase 3 (PR5+)**: UA panel 8 analyte 起動、Coag panel(PT/APTT)起動。derive_lab_values 拡張 + reference range YAML + disease YAML

## 12. Rollback 戦略

PR 単位で revert 可能:
- `anion_gap_status` 軸を default 0 のまま使えば、disease YAML 設定の影響だけ無効化される
- derive_lab_values の Cl/Ca block を削除すれば lab_panel_groups の BMP min_components を 5 に戻す(or N=6 になる)だけで完全 rollback 可能

## 13. リスクと緩和

| リスク | 緩和 |
|--------|------|
| disease YAML 編集が他テストを壊す | byte-diff invariant gate(physiology state 変数の cascade 検知)→ **実装中に発火**、§13.1 参照 |
| Cl 式の non_ag_fraction clamp(1.5)で hyperchloremia が過剰 | hand-calc 値域検証 + audit で per-disease median 確認 |
| Ca 多軸 coupling が肝硬変等で過小 | reference range 8.5–10.5 をベースに各疾患 hand-calc 後 audit |
| AG 軸が `apply_coupling_rules` で副作用 | rule に AG → other state の path を一切書かない(本 spec で禁止)+ `test_anion_gap_status_does_not_mutate_other_labs` で守る |
| `inpatient.py:644` の silently dropped path が他 panel に影響 | 該当箇所は panel-child が true_labs に無い場合 PLACED 維持で skip するだけ。Cl/Ca が生成されれば skip 不要、他 panel(LFT/Lipid 等)に変更なし |

### 13.1 実装中に発火したリスク + 構造修正(post-spec)

byte-diff invariant gate を Task 7 で実行したところ、master vs branch で全 NDJSON / CSV が byte-mismatch・Patient count drift(US 1280→1310)。Probe で **Task 2(`derive_lab_values` への Cl/Ca block 追加だけ)** でも cascade することを確認。

**root cause**: `inpatient.py` Pass 1 / `emergency.py` / `outpatient.py` の lab loop が、specimen-rejection / hemolysis / technician assignment / 観測ノイズの draws を **patient-scoped master RNG** で行っていた。`{test:"Cl"}` 等の個別 order を持つ disease YAML で、derive_lab_values が Cl を生成するようになると `if canon in true_labs` の skip 条件が反転 → master rng が余分に draw → 後続 patient の cohort が変わる。PR #74 が panel children についてだけ `panel_specimen_seed` で sub-rng 化していたが、**個別 lab order(panel child でない)については未対応**で残っていた AD-16 violation。

**構造修正**: `simulator/seeding.py` に `individual_lab_seed(order_id)` を新設し、Pass 1 / emergency / outpatient の lab loop を per-order sub-rng で処理。具体的には `clinosim/simulator/seeding.py:individual_lab_seed`(`panel_specimen_seed` と同型)を導入し、3 つの lab loop で `lab_rng = np.random.default_rng(individual_lab_seed(order_id))` に置換。Cl/Ca の specimen rejection / hemolysis / noise はもとより、ABG プロベや個別 K order などすべての非 panel-child lab order が AD-16 準拠に。

**この修正の代償**: master stream の draw 数が減るため、master の cohort と branch の cohort は **意図的に**乖離する。Cl/Ca 物理 calibration の byte-diff invariant gate(spec §9.3 で目論んでいた)は **構造修正の代償として不成立**。代わりの invariant property:
- `test_simulator_deterministic_across_repeated_runs`: 同 seed で 2 回 run = byte-identical(構造修正後の決定論性)
- `test_dka_individual_cl_order_now_resulted`: DKA 個別 Cl order が RESULTED + 値域内(Pass 1 sub-rng の end-to-end 動作)

これは結果的に **将来の analyte 追加全般に safe な恒久的 pattern**(PR #74 の panel-child sub-rng pattern を 残り全 lab order に展開)。今後 PT/APTT / UA panel 追加でも同じ cascade は起きない。

---

## 参考

- AD-16: 各モジュール独立 sub-rng
- AD-57: acid-base 二軸モデル(本 PR で AG 軸を直交追加して 3 軸目に)
- PR #74 spec: `2026-06-23-cbc-bmp-panel-expansion-design.md`(per-parent panel_specimen_seed pattern 確立)
- PR #75 spec: `2026-06-23-cbc-bmp-pr2-min-components-design.md`(canonical N − 1 rule)
- PR #76 review: `docs/reviews/2026-06-23-pr75-data-quality-review.md`(post-PR #75 全体品質確認)
- 参考臨床文献: Harrison's Internal Medicine 21e Ch. 51(acid-base disorders)、Nelson's Pediatrics(electrolyte disturbances)、Tietz Clinical Guide to Laboratory Tests 4e(reference intervals)
