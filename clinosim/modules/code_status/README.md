# code_status モジュール

重篤な encounter に **コードステータス(蘇生方針 / resuscitation status)** を付与し、
FHIR `Observation` + CSV `code_status.csv` として出力する AD-55 Base(always-on)モジュール。

## 概要

入院 encounter には常に、ED encounter には重篤例のみ、4段階のコードステータスを
**年齢 × acuity context × locale レート**で確率的に割り当てる。

- 値(4段階): Full Code / DNR / DNR+DNI / Comfort care。SNOMED コードで保持(AD-30)。
- 付与ゲート: `encounter_type=="inpatient"` は全例 / `=="emergency"` は `deceased` または
  `icu_transferred` のみ / 外来は付与なし(実 EHR の記録実態に整合)。
- context: `terminal`(死亡)> `icu`(ICU)> `routine`。高齢・重症・終末ほど DNR/Comfort に傾く。

## データファイル

- `reference_data/code_status.yaml` — **country-neutral**: resuscitation-status observable、
  4段階 tier → SNOMED コード + 表示、年齢帯。
- `clinosim/locale/{us,jp}/code_status_rates.yaml` — **国別** 4段階 weights
  (context × 年齢帯)。日本は Full Code 既定が高め(DNAR 文化)。

> **コード照合**: SNOMED は環境から Snowstorm/browser API に到達できず、ドメイン知識ベースの
> 候補に `# TODO: verify` を付与(304251008 observable / 304252001 For resuscitation /
> 304253006 Not for resuscitation・DNAR / 103735009 Palliative care)。リリース前に要確認。
> DNR+DNI は単一の clean な SNOMED 概念がなく 304253006 を共用(DNI 粒度は要検討)。

## API

```python
assign_code_status(age: int, context: str, country: str,
                   rng: np.random.Generator) -> str  # SNOMED コードを返す
```
決定的。`context` は `"routine"|"icu"|"terminal"`。

## 配線

- **Enricher**(`simulator/enrichers.py`、stage=`post_records`、order=50、always-on):
  `enrich_code_status`。**encounter_id 由来の独立サブシード**
  (`derive_sub_seed(master, 0x4353, encounter_id)`)で encounter 内安定 & 主乱数列不変(AD-16)。
  付与ゲートを適用し `CIFPatientRecord.code_status`(SNOMED コード、非該当は空)に格納。
- **FHIR**: `modules/output/_fhir_code_status.py` の `_build_code_status` を
  `_BUNDLE_BUILDERS` 登録(AD-56)。survey カテゴリの Observation、code=observable、
  valueCodeableConcept=段階 SNOMED、encounter 参照、effectiveDateTime=入院日時。id `codestatus-{enc}`。
- **CSV**: `csv_adapter.py` が `code_status.csv` を出力。

## 依存

`types/output`(`code_status` フィールド)、`codes`(SNOMED 表示)、`locale`(レート)、
`simulator/seeding`(`derive_sub_seed`)。

## Consumers

このモジュールに依存するもの:

| Caller | How | Impact |
|---|---|---|
| `simulator/enrichers.py` | `register_builtin_enrichers()` で post_records enricher 登録 | core (enricher registry) |
| `modules/code_status/enricher.py` | 同 module 内の enricher 実装 | core |
| `modules/output/_fhir_code_status.py` | SNOMED 304251008 系の survey Observation を生成 | medium (FHIR builder) |
| `tests/integration/test_code_status_enricher.py` | enricher integration test | guard |
| `tests/unit/test_code_status_engine.py` | engine unit tests | guard |
| `tests/unit/test_code_status_codes.py` | SNOMED コード authority + active concept 検証 (PR #68) | guard |

## 検証

- 決定論: 同一 seed US 生成で **byte-diff は新規 codestatus-* Observation のみ**
  (369件追加・削除0・既存 Observation 変化0)=主乱数列不変。
- 監査(US 3000、入院 n=369): Full Code 86% / DNR 13% / Comfort 1.4%、外来0、ED 重篤ゲート機能。
