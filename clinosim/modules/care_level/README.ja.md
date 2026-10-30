# `clinosim.modules.care_level` — JP 要介護度 (介護保険 認定区分) 付与

## 概要

JP コホートの全患者に対して介護保険の認定区分
(自立 `independent` / 要支援 `support1`・`support2` / 要介護
`care1`…`care5`) を **患者単位で決定的に**サンプリングし、
`CIFPatientRecord.care_level` (自立・介護保険非適格・非 JP のときは空文字列) に
書き込む AD-55 Base モジュール。下流の FHIR + CSV adapter が同 field
を読み、social-history の `Observation` および `care_level.csv` を出力する。

本モジュールは **JP 限定**。US その他の国では enricher は登録段階で
無効化され (`assign_care_level` 自体も非 JP では `""` を返す)、
`care_level` は既定の `""` のままなので、`Observation` は出ず CSV の
当該列は空になる。

## Scope

- **In scope**: `weights[age_band]` の weight テーブルから 1 tier を
  年齢駆動でサンプリング。患者単位のサブ RNG を使用し、主シミュレーション
  乱数列は乱さない (AD-16)。
- **重み付き draw の入力は年齢のみ**: 認定率は 65 歳未満で ~2 %、65-74 で ~10 %、
  75-84 で ~30 %、85+ で ~60 % に上昇するよう調整 (MHLW の介護保険
  人口統計に整合)。機能評価スコアは参照しない。
- **介護保険 適格 gate** (Issue #940。per-patient RNG の形を変えない
  よう enricher が draw の *後* に適用): 65 歳以上 (第1号被保険者) は
  draw 結果を維持、40 歳未満は常に `""`、40-64 歳 (第2号被保険者) は
  慢性疾患が `secondary_designated_condition_codes` の prefix
  (相当疾病。例: `F00`, `G30`, `G20`, `J44`, `I63`, `G12.2`) に該当
  する場合のみ維持。
- **自立 = 空**: `independent` tier は空文字列にマップされ、
  `Observation` も CSV 行も出力されない。実 EHR で未認定患者の
  認定区分レコードが存在しないのと同じ挙動。
- **Out of scope**: ADL / Barthel / 機能評価スコア
  ([`clinosim.modules.nursing`](../nursing/README.ja.md))、FHIR
  serialization ([`clinosim.modules.output`](../output/README.ja.md))、
  code system の日本語表示テキスト
  ([`clinosim/codes/data/jp-care-level.yaml`](../../codes/data/jp-care-level.yaml))。

## Public API

`__init__.py` は空。呼び出し側は engine + enricher から直接 import:

```python
from clinosim.modules.care_level.engine import (
    assign_care_level,   # (age, country, rng) -> "" | care-level code
    load_reference,      # -> {levels, age_bands, eligibility_gates}
    load_rates,          # (country="JP") -> {age_band: [w0..w7]} (非 JP は {})
    patient_qualifies_for_secondary_ltci,  # (chronic_condition_codes) -> bool
)
from clinosim.modules.care_level.enricher import enrich_care_level
```

`assign_care_level` は `country` が JP でない場合、またはサンプリングされた
tier が `independent` の場合に `""` を返す。それ以外は `jp-care-level`
コード (例: `"support1"` / `"care3"`) を返す。

## 決定論

- サブ seed オフセット `0x434C` (`"CL"`)。
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["care_level"]` に登録済み。
- 患者単位 RNG:
  `derive_sub_seed(master_seed, offset, patient_id)` — 同一患者は
  すべての encounter で同じ tier をサンプリングし、患者主 RNG 列を
  消費しない。
- `code_status` (encounter 単位) と対照的で、care_level は
  encounter 属性ではなく患者属性なので person 単位。

## 依存

- `clinosim.modules._shared` — `is_jp` (国別ゲート)、
  `normalize_probabilities` (`fallback="raise"`)、
  `get_attr_or_key` / `set_attr_or_key`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.codes` (間接、FHIR builder 経由) — LOINC と
  `jp-care-level` の表示 lookup。
- 他の `clinosim.modules.*` には依存しない。

## 定数と設定

- [`reference_data/care_level.yaml`](reference_data/care_level.yaml)
  — country-neutral。
  - `levels: ["independent", "support1", "support2", "care1", "care2", "care3", "care4", "care5"]`
    (順序は locale rate table の weight vector 順に一致)。
  - `age_bands: ["0-64", "65-74", "75-84", "85-120"]`。
  - `eligibility_gates`: `primary_insured_min_age: 65`、
    `secondary_insured_min_age: 40`、および ICD-10 prefix list
    `secondary_designated_condition_codes` (10 件)。
- [`clinosim/locale/jp/care_level_rates.yaml`](../../locale/jp/care_level_rates.yaml)
  — JP 限定。年齢帯ごとの 8-level 相対 weight。engine が正規化する。
  weight が唯一の国別入力なので、新規 locale を追加する場合は
  `clinosim/locale/<country>/` に YAML を追加し `load_rates` を拡張する。
- カスタムコード体系:
  [`clinosim/codes/data/jp-care-level.yaml`](../../codes/data/jp-care-level.yaml)
  (source: MHLW 介護保険 区分)。要介護度に対応する国際標準コードが
  無いため、`jp-care-level` は emission 時にのみ使うローカル codeset。

## ディレクトリ構造

```
clinosim/modules/care_level/
  __init__.py                   空 (Public API 節参照)
  engine.py                     load_reference / load_rates / assign_care_level / patient_qualifies_for_secondary_ltci
  enricher.py                   POST_RECORDS enrichment (患者単位サブ RNG)
  reference_data/
    care_level.yaml             levels + 年齢帯 (country-neutral)
```

**`audit.py` は存在しない** — `ModuleAuditSpec` は登録していない。
検証は下記 unit + integration test で担保。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) の
`register_builtin_enrichers` で登録:

- `name="care_level"`, `stage=POST_RECORDS`, `order=60`,
  `enabled=lambda c: is_jp(getattr(c, "country", "US"))` — 登録段階で
  JP gate。
- `code_status` (order 50) の後、`medication_monitoring` (order 65)
  と JP 限定の `health_checkup` (order 70) の前に実行。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| CSV adapter | [`clinosim/modules/output/csv_adapter.py`](../output/csv_adapter.py) (`L371` 付近, `L420` 付近) | `record["care_level"]` から `care_level.csv` を書き出し。 |
| FHIR `Observation` builder | [`clinosim/modules/output/fhir_r4/encounters/care_level.py`](../output/fhir_r4/encounters/care_level.py) (`_bb_care_level`) | social-history `Observation`、id は patient id から導出した opaque な `carelevel-<hash>` (identifier に元 key を保持)、`code` = LOINC 80391-6 (JP では `text = "要介護度"`)、`valueCodeableConcept` = `jp-care-level` コード。`effectiveDateTime` は SDOH パターン (最初の encounter 入院時刻) を踏襲。JP encounter は `meta.profile = JP_Observation_Common` を付与。PR2 G2 (2026-06-24) で旧 `_fhir_sdoh.py` から single-responsibility 分離。 |
| Enricher registry | [`clinosim/simulator/enrichers.py:280`](../../simulator/enrichers.py) | POST_RECORDS 登録。 |

## テスト

```bash
pytest tests/unit -k care_level -q         # engine
pytest tests/integration -k care_level -q  # enricher + FHIR 出力
```

個別ファイル:

- [`tests/unit/test_care_level_engine.py`](../../../tests/unit/test_care_level_engine.py)
  — サンプリング + 年齢帯選択 + JP-only gate。
- [`tests/integration/test_care_level_enricher.py`](../../../tests/integration/test_care_level_enricher.py)
  — enricher の person-scope 決定論、非 JP で空。
- [`tests/integration/test_fhir_care_level.py`](../../../tests/integration/test_fhir_care_level.py)
  — `Observation` 出力の end-to-end。
- [`tests/unit/test_pediatric_social_history_and_ltci_gates.py`](../../../tests/unit/test_pediatric_social_history_and_ltci_gates.py)
  — 介護保険 適格 gate (Issue #940)。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
