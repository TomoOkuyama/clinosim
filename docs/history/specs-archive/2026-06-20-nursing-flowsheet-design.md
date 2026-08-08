# 看護フローシート (Nursing Flowsheet) — AD-55 Base

- **Date**: 2026-06-20
- **Scope**: フル一式 (NEWS2 / GCS / Braden / 転倒リスク + 既存 I/O・ADL の FHIR 配線)
- **Type**: AD-55 Base データ拡充 (always-on)。新規データ追加 (既存出力は不変)。
- **Status**: 設計承認済 (実装場所を Enricher に精緻化)

## 背景と目的

実 EHR で最も量の多いデータ種の一つが看護アセスメントである。clinosim は既に
NEWS2 構成要素 (RR/SpO2/O2/temp/SBP/HR/AVPU consciousness/pain) を `VitalSignRecord`
に、I/O 水分出納 (`IntakeOutputRecord`)・ADL (`ADLAssessment` = Barthel Index) を CIF に
持つ。しかし以下が欠けている:

1. **NEWS2 集計スコア** (構成要素はあるが集計値が無い)
2. **GCS** (Glasgow Coma Scale 3-15。意識は AVPU のみ)
3. **Braden scale** (褥瘡リスク 6-23)
4. **転倒リスク** (Morse Fall Scale)
5. これら看護アセスメントの **FHIR Observation 出力** (I/O・ADL は CIF/CSV にあるが
   FHIR 未出力。`csv_adapter` のみ ADL を出力)

本機能はこれらを physiology から決定論的に導出して CIF に追加し、FHIR `Observation` +
CSV に出力する。TODO.md line 429 の "Nursing flowsheets" 項目、推奨順序 (line 441) で
microbiology+markers の次に位置する。

## 設計

### アーキテクチャ概要

- **計算ロジック**: 新規 `clinosim/modules/observation/nursing.py` — 純粋関数群
  (`compute_news2`, `compute_gcs`, `compute_braden`, `compute_morse_fall_risk`)。
  単体テスト容易。`observation` モジュールは `types` / `codes` のみに依存。
- **スコア閾値**: `clinosim/modules/observation/reference_data/nursing_scores.yaml`
  (NEWS2 集計表 / Braden サブスケール対応 / Morse 重み = データ駆動、ハードコード禁止)。
- **実行場所**: AD-56 の **Enricher** として `simulator/enrichers.py` の
  `register_builtin_enrichers()` に登録 (`name="nursing"`, `stage=POST_RECORDS`,
  `order` は identity より後の固定値, `enabled=lambda c: True` = Base always-on)。
  主シミュレーションループには手を入れない。
- **既存 I/O・ADL**: インライン生成 (`inpatient.py` の `_generate_daily_io` /
  `_generate_adl_assessment`) はそのまま維持 (移動はスコープ外)。FHIR 配線のみ追加。

### スコアと導出 (権威 = 公表された標準器)

| スコア | 範囲 | 導出元 (CIF 内データ) | rng |
|---|---|---|---|
| **NEWS2** | 0-20 | `VitalSignRecord` の RR/SpO2/on_supplemental_oxygen/temp/SBP/HR/consciousness を `nursing_scores.yaml` の集計表で合算 | 不要 (決定論) |
| **GCS** | 3-15 | consciousness (AVPU) を基点に perfusion/inflammation 由来の脳症補正 | 軽微 |
| **Braden** | 6-23 | ADL (可動性/活動/栄養代理) + consciousness (知覚) + volume (湿潤) サブスケール合算 | 軽微 |
| **転倒リスク** | Morse 0-125 + risk_level | 年齢 + ADL transfers/mobility + 意識 + IV ライン有無 | 軽微 |

NEWS2 集計の標準: RCP *National Early Warning Score 2* (2017)。GCS / Braden / Morse は
公表された標準器。閾値・重みは `nursing_scores.yaml` に出典コメント付きで保持。

### CIF 表現 (AD-55: Base はコア型に typed field を追加可)

- **NEWS2 + GCS** → `VitalSignRecord` (`types/encounter.py`) に
  `news2_score: int | None = None` / `gcs_score: int | None = None` を追加。AVPU/pain と
  同居し、バイタルセット毎に enricher が算出して埋める。
- **Braden + 転倒リスク** → 新 dataclass `NursingRiskAssessment` を `types/encounter.py` に
  定義:
  ```python
  @dataclass
  class NursingRiskAssessment:
      date: date
      braden_total: int          # 6-23 (低いほど高リスク)
      braden_sensory: int        # 1-4
      braden_moisture: int       # 1-4
      braden_activity: int       # 1-4
      braden_mobility: int       # 1-4
      braden_nutrition: int      # 1-4
      braden_friction: int       # 1-3
      morse_total: int           # 0-125
      fall_risk_level: str       # "low" | "moderate" | "high"
  ```
  日次生成し、`CIFPatientRecord` (`types/output.py`) に
  `nursing_risk_assessments: list = field(default_factory=list)  # NursingRiskAssessment`
  を追加 (既存 `intake_output_records` / `adl_assessments` / `microbiology` と並置)。

### 決定論 (AD-16、厳守)

- enricher は `ctx.master_seed` から **専用サブシード** を導出する。`microbiology.py` の
  `_encounter_seed(master_seed, encounter_id)` (hashlib ベース、PYTHONHASHSEED 非依存) と
  同型のヘルパーを用い、主乱数列を一切乱さない。
- NEWS2 / GCS は VitalSignRecord から純粋計算 (rng 不要)。
- 帰結: 既存 golden の **labs / vitals 数値 / 診断 / I/O / ADL は byte 不変**。新規の
  `news2_score` / `gcs_score` フィールドと `nursing_risk_assessments` のみが追加される。

### FHIR 出力 (AD-56)

- `register_bundle_builder()` で `_build_nursing_observations(ctx)` を登録
  (`_build_bundle` は編集しない)。FHIR `Observation` (`category` = `survey`) を emit:
  - NEWS2 / GCS → 各 `VitalSignRecord` から (encounter-scoped id: `news2-{enc}-{i}` 等)
  - Braden / 転倒リスク / Barthel(ADL) / I/O 水分出納 → 各日次レコードから
- **LOINC は NLM Clinical Tables (`loinc_items`) で権威照合・捏造禁止**。候補 (実装時に確認):
  GCS total `9269-2`、Braden total `38228-4`、Morse fall risk、Barthel index、NEWS、
  fluid intake/output。確証できないコードは登録せず `# TODO: verify` とせず、照合できた
  もののみ採用する。新規 LOINC は `codes/data/loinc.yaml` に `en` (+ `ja`) で追加。
- display は `codes.lookup` 解決 (AD-30)。`country="JP"` 時は日本語、US は 100% 英語。
- referenceRange/interpretation はスコア系では必須でない (survey スコア)。数値 Observation
  として `valueQuantity` または `valueInteger`、解釈レベル (high/moderate/low) は
  `interpretation` に載せられる範囲で。

### CSV 出力

- `csv_adapter` に追加: `nursing_risk.csv` (Braden サブスケール + Morse)、
  `intake_output.csv` (I/O、現状 FHIR/CSV 未出力)。`vitals` 行に `news2_score` /
  `gcs_score` 列を追加。既存 `adl_assessments.csv` は維持。

## テスト

- **unit** (`tests/unit/test_nursing.py`): 各スコア関数の境界値。
  - NEWS2: RCP の既知症例 (例: 正常バイタル→0、低酸素+頻呼吸+発熱の既知合算→既知点)。
  - GCS: AVPU A/V/P/U → 妥当な GCS 帯。範囲 3-15 を逸脱しない。
  - Braden: サブスケール合算が 6-23、低 ADL→低スコア (高リスク)。
  - Morse: 範囲と risk_level 閾値。
  - 決定論: 同一サブシードで同一出力。
- **unit** (`test_codes_integrity.py` 既存): 新規 LOINC が重複キー無しで追加されている。
- **integration**: enricher 実行後、看護データが CIF に存在し FHIR/CSV に流れる。
- **e2e**: golden 再生成。**既存フィールドが byte 不変**であること (決定論サブシードで担保)
  を確認し、新フィールド/リソースのみ差分。CPU 競合で稀に途中 exit → 再実行で確認。

## スコープ外

- 既存 `_generate_daily_io` / `_generate_adl_assessment` の `observation/` への移設
  (動作しており、移動は別リファクタ)。
- 看護記録の自由文ナラティブ (LLM)。
- 既存 vitals/labs の値変更 (決定論で byte 不変を保証)。

## 受け入れ基準

1. NEWS2 / GCS / Braden / 転倒リスクが physiology から決定論的に算出され CIF に格納される。
2. 既存 I/O・ADL を含む看護データが FHIR `Observation` + CSV に出力される。
3. 全 LOINC が NLM 照合済 (捏造ゼロ)、`en` フィールド必須。
4. 既存 golden の labs/vitals/診断が byte 不変、新フィールド/リソースのみ追加。
5. unit/integration/e2e 全緑。
6. README (observation モジュール) + TODO.md が更新されている。
