# ナトリウム (dysnatremia) 生理軸 — AD-57 系

- **Date**: 2026-06-20
- **Scope**: 疾患駆動の低/高 Na 血症(慢性 HF/肝硬変の低 Na、脱水の高 Na、SIADH/増悪の低 Na)
- **Type**: 生理モデル拡充(検査値の臨床整合)。既存ラボ軸(glucose_status/acid_base_type/anemia_level)と同型。
- **Status**: 設計承認済

## 背景と目的

2026-06-20 のデータ生成監査(US catchment 20k)で **Na 実測範囲が 131–144** と判明し、
低 Na 血症(<130)も高 Na 血症(>150)も一切生成されていなかった。原因は
`physiology/engine.py:231` の `Na = 140 - (1-renal)*5 + volume_status*(-3)` が微調整のみで、
疾患シナリオに連動した dysnatremia 軸が無いこと。

clinosim の中核原則(検査値は基礎疾患・患者プロファイル・疾患シナリオと整合)に従い、
既存の疾患駆動ラボ軸(`causes_myocardial_injury`/`glucose_status`/`acid_base_type`)と
**同型のパターン**で Na 軸を追加する。

## 設計

### 1. 状態軸 (`PhysiologicalState`)

`clinosim/types/clinical.py` の `PhysiologicalState` に追加:
```python
    sodium_status: float = 0.0  # -1.0–+1.0  (neg = hyponatremia, pos = hypernatremia)
```
`physiology/engine.py` の `_variable_range` の ranges dict に追加:
```python
        "sodium_status": (-1.0, 1.0),
```
(これにより `apply_disease_onset` が YAML `initial_state_impact` の `sodium_status` キーを
汎用適用・clamp できる。)

### 2. 慢性ベースライン (`initialize_state`)

`initialize_state` の慢性疾患ループ(既存の I50/K74 分岐)に低 Na ベースラインを追加:
- **慢性 HF (I50)**: 希釈性低 Na。`state.sodium_status -= s * 0.30`(s = severity_score)。
  既存の `volume_status += s*0.3`(体液過剰)と共存=総体液増+Na 濃度低下で生理的に正しい。
- **肝硬変 (K74)**: 希釈性低 Na。`state.sodium_status -= s * 0.40`。

### 3. 急性ドライバ

- **脱水 → 高 Na(coupling で汎用化)**: `apply_coupling_rules` に volume→sodium 結合を追加:
  ```python
  # Dehydration (free-water deficit) concentrates sodium → hypernatremia
  if state.volume_status < -0.4:
      state.sodium_status = clamp(
          state.sodium_status + (abs(state.volume_status) - 0.4) * 0.9, -1.0, 1.0
      )
  ```
  既存の脱水シナリオ(`viral_gastroenteritis`/`food_poisoning` 等が `initial_state_impact` で
  `volume_status` を下げる)が **YAML 編集なし**で高 Na 血症になる。HF は volume_status が正の
  ため発火せず、慢性低 Na のまま(矛盾なし)。
- **SIADH / 増悪 → 低 Na(YAML データ駆動)**: 任意で疾患/encounter の `initial_state_impact` に
  `sodium_status` を追加。本スコープでは **`heart_failure_exacerbation`(急性増悪の低 Na 強調)** と
  **`bacterial_pneumonia`/`aspiration_pneumonia`(SIADH)** に軽度負値を追加(severity 別)。

### 4. ラボ写像 (`derive_lab_values`)

`engine.py:231` の Na 行を置換:
```python
    labs["Na"] = 140.0 + state.sodium_status * 14.0 - (1 - renal) * 3.0
    labs["Na"] = clamp(labs["Na"], 120, 160)
```
旧 `volume_status*(-3)` 項は coupling(volume→sodium_status→Na)に統合(二重計上回避)。
測定ノイズ・観測クランプは既存経路のまま。

### 目標分布(臨床整合)
- 正常患者(sodium_status≈0, renal≈1): Na ≈ 137–140(**従来と同等、破綻なし**)。
- 慢性 HF / 肝硬変: Na 中央値 ≈ 131–135(低 Na)。
- 脱水(胃腸炎/食中毒, volume_status≈-0.6): Na ≈ 146–152(高 Na)。
- sodium_status -1 → Na ≈ 126、+1 → Na ≈ 151(clamp 120–160 内)。

## 決定論・出力

- Na 写像は state から決定論的。新軸は **rng/主乱数列を一切使わない**(coupling/baseline も決定論)。
- **Na 値は意図的に変化**(リアリティ修正)。これは feature による生理の改善であり、既存の
  他ラボ(troponin/glucose/Hb/K/CRP 等)・vitals・診断は数式上不変。e2e はプロパティ/決定論
  ベース(保存 golden ファイルではない)で Na 範囲(120–160)と決定論を検証 → 通過見込み。
- 生成監査で Na 分布が疾患群で分離(低 Na in HF/cirrhosis、高 Na in 脱水)・正常患者は不変域を確認。

## テスト

- **unit** (`physiology` テスト): sodium_status→Na 写像の境界(0→140、-1→~126、+1→~151)、
  volume→sodium 結合(volume_status -0.6 → sodium_status 正 → Na 上昇)、慢性 HF/肝硬変
  ベースラインで sodium_status 負・Na 低下、正常患者で Na≈140 不変。決定論(同入力→同出力)。
- **integration**: 脱水 encounter(gastroenteritis/food_poisoning)で Na 高値、HF/肝硬変で Na 低値。
- **e2e + 生成監査**: catchment ~8k 再生成で Na 分布が疾患追従に拡大(低 Na/高 Na が出現)、
  正常域患者の Na は ~138–140、全 Na が 120–160 内。CPU 競合で稀に途中 exit → 再実行で確認。

## スコープ外

- 偽性低 Na(高血糖/高脂血症補正)、Na 補正速度・治療反応(過補正/ODS)。本スコープは
  onset/baseline の静的反映のみ(既存軸と同レベル)。
- BNP 特異性(別の監査 Important 指摘)は別 PR。

## 受け入れ基準

1. `sodium_status` 軸が `PhysiologicalState` に追加され、慢性 HF/肝硬変でベースライン低 Na、
   脱水で高 Na(coupling)、増悪/SIADH で低 Na(YAML)を駆動する。
2. Na 写像が `sodium_status` を反映し、疾患群で Na 分布が分離する(監査で確認)。
3. 正常患者の Na は ~138–140 で従来同等(破綻なし)、全 Na が 120–160 内。
4. 決定論・主乱数列不変。他ラボ/vitals/診断は数式上不変。
5. unit/integration/e2e 全緑。`physiology/README.md` 更新。
