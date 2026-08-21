# `clinosim.modules.family_history` — 第 1 度近親の家族歴合成

## 概要

患者ごとに第 1 度近親 (母 / 父 / 兄弟姉妹 0-2 人) を合成し、
`base_prevalence(疾患, 近親性別, 近親年齢帯) × heritability(疾患)`
(本人が同じ ICD ベースコードを持つ場合) で疾患を割り当てる AD-55 Base
(always-on) モジュール。結果を `CIFPatientRecord.family_history`
(typed field) に格納し、下流の FHIR + CSV adapter が
`FamilyMemberHistory` リソースと `family_history.csv` を出力する。

## Scope

- **In scope**: 母 + 父 + 兄弟姉妹 0-2 人。近親年齢は本人年齢から導出
  (親は設定可能なオフセット加算、兄弟姉妹は ± オフセット)、親の死亡は
  年齢に応じ確率上昇。疾患ごとに locale prevalence × heritability boost。
- **モデル対象疾患**: 心血管代謝系 (`E11` 糖尿病、`I10` 高血圧、
  `I25` 虚血性心疾患、`I63`/`I64` 脳卒中、`E78` 脂質異常症) + 主要がん
  (`C50` 乳、`C18` 大腸、`C34` 肺、`C61` 前立腺)。ICD-10 base コードのみ
  保持し、表示は下流で lookup 解決 (AD-30)。
- **性別制限**: 前立腺は男性近親のみ、乳がんは女性近親のみ
  (reference YAML の per-condition `sex` フィールドで強制)。
- **Out of scope**: 家族歴を本人の疾患サンプリングに逆流させる処理
  (Phase 2+ で
  [`clinosim.modules.population`](../population/README.md) の
  risk-factor logic 想定)、FHIR / CSV serialization
  ([`clinosim.modules.output`](../output/README.md))、ICD-10 や
  HL7 v3-RoleCode の表示テキスト ([`clinosim/codes/`](../../codes/))。

## Public API

`__init__.py` は空。呼び出し側は engine + enricher から直接 import:

```python
from clinosim.modules.family_history.engine import (
    generate_family_history,     # (patient_age, patient_conditions, country, rng)
                                 #   -> list[FamilyMemberHistoryRecord]
    load_reference,              # -> 生物学 (relationships / heritability / offsets)
    load_prevalence,             # (country) -> {icd_code: {age_band: {sex: rate}}}
    SIBLING_COUNT_OPTIONS,       # (0, 1, 2)
    SIBLING_SEX_MALE_PROBABILITY, # 0.5
)
from clinosim.modules.family_history.enricher import enrich_family_history
```

`generate_family_history` は `patient_conditions` として `str` /
`dict` (`{"code": ...}`) / オブジェクト (`.code`) を受容。engine が
uppercase + `.` 分割で ICD ベースを抽出する。与えられた `rng` に対し決定的。

## 決定論

- サブ seed オフセット `0x4648` (`"FH"`)。
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["family_history"]` に登録済み。
- 患者単位 RNG:
  `derive_sub_seed(master_seed, offset, patient_id)` — 同一患者は
  すべての encounter で同じ家族を合成し、患者主 RNG 列を消費しない。

## 依存

- `clinosim.modules._shared` — `is_us` / `is_jp`、
  `normalize_probabilities` (`fallback="raise"`)、
  `get_attr_or_key` / `set_attr_or_key`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.types.family_history` — `FamilyMemberHistoryRecord`。
- `clinosim.codes` (間接、FHIR builder 経由) — ICD-10 と
  HL7 v3-RoleCode の表示 lookup。
- 他の `clinosim.modules.*` には依存しない。

## 定数と設定

- [`reference_data/family_history.yaml`](reference_data/family_history.yaml)
  — country-neutral な生物学:
  - `relationships` — `MTH` / `FTH` / `NSIB` の v3-RoleCode エントリと
    per-code の EN + JA 表示。**JA 正規表示はコード個別**
    (MTH は `"母"`、FTH は `"父"`、NSIB は `"natural sibling"` /
    `"実兄弟姉妹"`) であり、**兄弟コードから推測してはならない**
    — file 冒頭コメント (Issue #369、v23 regression) が PR #372 の
    drift を詳述している。
  - `conditions` — ICD ごとの `{sex, heritability}`。
  - `sibling_count_weights` — `SIBLING_COUNT_OPTIONS = (0, 1, 2)` に
    対応する 3 要素 weight。
  - `parent_age_offset` / `sibling_age_offset` — `{min, max}` 範囲
    (`rng.integers` に渡す)。
  - `parent_deceased_base_age` / `parent_deceased_span` /
    `parent_deceased_max` — 親の死亡確率式。
- [`clinosim/locale/us/family_history_prevalence.yaml`](../../locale/us/family_history_prevalence.yaml)
  および
  [`clinosim/locale/jp/family_history_prevalence.yaml`](../../locale/jp/family_history_prevalence.yaml)
  — `{icd_code: {age_band: {female: rate, male: rate}}}`。
  `load_prevalence` は unsupported country に対し `{}` を返し
  (2026-07-02 grand-design 契約)、engine は空 map を「全員 unaffected」
  として扱う。
- module レベル定数 (`engine.py`):
  - `SIBLING_COUNT_OPTIONS = (0, 1, 2)` — OECD 2020 の平均
    children-per-household (US + JP) 分布に整合。
  - `SIBLING_SEX_MALE_PROBABILITY = 0.5` — 出生時 sex ratio に
    小数第 2 位まで一致。

## ディレクトリ構造

```
clinosim/modules/family_history/
  __init__.py                     空 (Public API 節参照)
  engine.py                       generate_family_history + サンプリング helper
  enricher.py                     POST_RECORDS enrichment (患者単位サブ RNG)
  reference_data/
    family_history.yaml           country-neutral な生物学
```

**`audit.py` は存在しない** — `ModuleAuditSpec` は登録していない。
検証は下記 unit + integration test で担保。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) の
`register_builtin_enrichers` で登録:

- `name="family_history"`, `stage=POST_RECORDS`, `order=40`,
  `enabled=lambda c: True`。
- `immunization` (order 30) の後、`code_status` (order 50) の前に実行。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| CSV adapter | [`clinosim/modules/output/csv_adapter.py`](../output/csv_adapter.py) (`L341` 付近, `L418` 付近) | `record["family_history"]` から `family_history.csv` を書き出し (患者単位)。 |
| FHIR `FamilyMemberHistory` builder | [`clinosim/modules/output/fhir_r4/demographics/family_history.py`](../output/fhir_r4/demographics/family_history.py) | 近親ごとに `FamilyMemberHistory` を 1 件出力。id は `fmh-{patient_id}-NN` で write 時 de-dup。 |
| Enricher registry | [`clinosim/simulator/enrichers.py:175`](../../simulator/enrichers.py) | POST_RECORDS 登録。 |

## テスト

```bash
pytest tests/unit -k family_history -q         # engine, data, codes, csv, relationship
pytest tests/integration -k family_history -q  # enricher + FHIR 出力
```

個別ファイル:

- [`tests/unit/test_family_history_engine.py`](../../../tests/unit/test_family_history_engine.py)
  — サンプリング決定論 + 性別 / 年齢 filter。
- [`tests/unit/test_family_history_data.py`](../../../tests/unit/test_family_history_data.py)
  — reference YAML shape。
- [`tests/unit/test_family_history_codes.py`](../../../tests/unit/test_family_history_codes.py)
  — ICD-10 + v3-RoleCode の authoritative 検証。
- [`tests/unit/test_family_history_csv.py`](../../../tests/unit/test_family_history_csv.py)
  — CSV 行出力。
- [`tests/unit/test_fhir_family_history_code_resolution.py`](../../../tests/unit/test_fhir_family_history_code_resolution.py)
  — FHIR builder のコード → 表示解決。
- [`tests/unit/output/test_fhir_family_history_relationship.py`](../../../tests/unit/output/test_fhir_family_history_relationship.py)
  — per-code EN / JA 表示 integrity (Issue #369 の guard)。
- [`tests/integration/test_family_history_enricher.py`](../../../tests/integration/test_family_history_enricher.py)
  — enricher 決定論 + heritability boost。
- [`tests/integration/test_fhir_family_history.py`](../../../tests/integration/test_fhir_family_history.py)
  — `FamilyMemberHistory` 出力の end-to-end。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
