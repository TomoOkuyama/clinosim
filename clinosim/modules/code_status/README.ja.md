# `clinosim.modules.code_status` — 蘇生方針 (コードステータス) 付与

## 概要

重篤な encounter に対し 4 段階の蘇生方針 tier
(Full Code / DNR / DNR + DNI / Comfort care) を **encounter 単位で決定的に**
サンプリングし、`CIFPatientRecord.code_status` (SNOMED code の文字列、
非該当時は空文字列) として書き込む AD-55 Base (always-on) モジュール。
下流の FHIR + CSV adapter が同 field を読み、survey カテゴリの
`Observation` と `code_status.csv` を出力する。

## Scope

- **In scope**: 国別 (context × 年齢帯) の weight テーブルから 1 tier を
  サンプリング。encounter 単位のサブ RNG を用い、主シミュレーション乱数列は
  乱さない (AD-16)。
- **付与ゲート** (`enricher._qualifies`):
  - `encounter_type == "inpatient"` → 常に付与。
  - `encounter_type == "emergency"` → `deceased` または `icu_transferred`
    のときのみ付与 (実 EHR では多くの ED encounter で明示的な
    code-status 記録がないことを反映)。
  - それ以外の encounter → 付与なし (`code_status = ""`)。
- **context 決定**: 死亡 → `terminal`、ICU 転棟あり → `icu`、それ以外 →
  `routine`。年齢帯が高く重症 context ほど DNR / Comfort に偏る。
- **Out of scope**: DNR による治療計画の変化 (該当時は
  [`clinosim.modules.clinical_course`](../clinical_course/README.md))、
  FHIR `Consent` serialization や multi-slot な事前指示書ドキュメント
  ([`clinosim.modules.output`](../output/README.md))。

## Public API

`__init__.py` は意図的に空。呼び出し側は engine + enricher から直接 import する:

```python
from clinosim.modules.code_status.engine import (
    assign_code_status,   # (age, context, country, rng) -> SNOMED code str
    load_reference,       # -> {observable_snomed, age_bands, tiers}
    load_rates,           # (country) -> {context: {age_band: [w_full, w_dnr, w_dnr_dni, w_comfort]}}
)
from clinosim.modules.code_status.enricher import enrich_code_status
```

`assign_code_status` は与えられた `rng` に対し決定的。enricher は下記の
ゲート + サブ seed 導出でこれをラップする。

## 決定論

- サブ seed オフセット `0x4353` (`"CS"`)。
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["code_status"]` に登録済み。
- encounter 単位 RNG: `derive_sub_seed(master_seed, offset, encounter_id)`。
  同 encounter は常に同一 tier をサンプリングし、患者主 RNG 列を消費しない。

## 依存

- `clinosim.modules._shared` — `is_us` / `is_jp` (国別 dispatch)、
  `normalize_probabilities` (weight 正規化、`fallback="raise"`)、
  `get_attr_or_key` / `set_attr_or_key` (enricher で dict / dataclass
  両対応アクセス)。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.codes` (間接、FHIR builder 経由) — 出力する `Observation.code`
  および `valueCodeableConcept` の SNOMED 表示 lookup。
- 他の `clinosim.modules.*` には依存しない。

## 定数と設定

- [`reference_data/code_status.yaml`](reference_data/code_status.yaml)
  — country-neutral。以下を定義:
  - `observable_snomed: "304251008"` — SNOMED CT observable
    「Resuscitation status」。
  - `age_bands: ["0-49", "50-69", "70-84", "85-120"]`。
  - 4 つの `tiers` (`{key, snomed, en, ja}`):
    - `full_code` — 304252001 (「蘇生処置を行う」)
    - `dnr` — 304253006 (「蘇生処置を行わない」/ DNAR)
    - `dnr_dni` — **同じく 304253006**。SNOMED CT International には
      DNR + DNI 組合せに対する独立 active concept が存在しないため、
      tier ラベル側で DNI を区別しコードは共用する。
    - `comfort` — 103735009 (「緩和ケア (コンフォート)」)。将来 SNOMED
      release に対する再確認待ちで `TODO: verify` が付いている。
  - observable + 蘇生関連コードは 2026-06-22 に `tx.fhir.org` の $lookup
    で active を確認済み (詳細手順は YAML 冒頭コメント)。
- [`clinosim/locale/us/code_status_rates.yaml`](../../locale/us/code_status_rates.yaml)
  および
  [`clinosim/locale/jp/code_status_rates.yaml`](../../locale/jp/code_status_rates.yaml)
  — 国別 `weights[context][age_band] = [full, dnr, dnr_dni, comfort]`。
  合計 1 になる確率分布。`load_rates` は unsupported country に対して
  `{}` を返し、enricher は空 map を「付与なし」として扱うため、新規国が
  黙って US レートを継承することはない (2026-07-02 grand-design review
  で確定した契約)。

## ディレクトリ構造

```
clinosim/modules/code_status/
  __init__.py                   空 (Public API 節参照)
  engine.py                     load_reference / load_rates / assign_code_status
  enricher.py                   POST_RECORDS enrichment (ゲート + サブ RNG)
  reference_data/
    code_status.yaml            country-neutral observable + tiers + 年齢帯
```

**`audit.py` は存在しない** — `ModuleAuditSpec` は現時点で登録していない。
検証は下記 unit + integration test で担保する。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) の
`register_builtin_enrichers` で登録:

- `name="code_status"`, `stage=POST_RECORDS`, `order=50`,
  `enabled=lambda c: True`。
- 実行順は `family_history` (order 40) の後、JP 限定の
  `care_level` (order 60) の前。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| CSV adapter | [`clinosim/modules/output/csv_adapter.py`](../output/csv_adapter.py) (`L358` 付近, `L419` 付近) | `record["code_status"]` から `code_status.csv` を書き出し。 |
| FHIR `Observation` builder | [`clinosim/modules/output/fhir_r4/conditions/code_status.py`](../output/fhir_r4/conditions/code_status.py) (`_bb_code_status`) | survey カテゴリの `Observation`、id `codestatus-{enc_id}`、`code` = observable 304251008、`valueCodeableConcept` = tier SNOMED、`effectiveDateTime` = 入院日時。JP encounter は追加で `meta.profile = JP_Observation_Common` を付与。 |
| Enricher registry | [`clinosim/simulator/enrichers.py:188`](../../simulator/enrichers.py) | POST_RECORDS 登録。 |

## テスト

```bash
pytest tests/unit -k code_status -q         # engine + data + codes + csv
pytest tests/integration -k code_status -q  # enricher + FHIR 出力
```

個別ファイル:

- [`tests/unit/test_code_status_engine.py`](../../../tests/unit/test_code_status_engine.py)
  — サンプリング + 年齢帯選択。
- [`tests/unit/test_code_status_data.py`](../../../tests/unit/test_code_status_data.py)
  — YAML shape。
- [`tests/unit/test_code_status_codes.py`](../../../tests/unit/test_code_status_codes.py)
  — SNOMED code の authoritative + active concept 検証 (PR #68)。
- [`tests/unit/test_code_status_csv.py`](../../../tests/unit/test_code_status_csv.py)
  — CSV 行出力。
- [`tests/integration/test_code_status_enricher.py`](../../../tests/integration/test_code_status_enricher.py)
  — enricher ゲート + サブ seed 決定論。
- [`tests/integration/test_fhir_code_status.py`](../../../tests/integration/test_fhir_code_status.py)
  — Observation 出力の end-to-end。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
