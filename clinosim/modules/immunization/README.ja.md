# `clinosim.modules.immunization` — 成人ワクチン接種歴合成

## 概要

国別 (CVX ベース) の接種スケジュール (最低年齢、プログラム開始日、頻度、
月、EHR 保持期間、年齢 × 性別 coverage) を元に、患者ごとの成人接種歴を
生成し `CIFPatientRecord.immunizations` に格納する AD-55 Base
(always-on) モジュール。下流の FHIR + CSV adapter が `Immunization`
リソースと `immunizations.csv` を出力する。実 EHR 挙動に合わせ、
一部のスケジュール接種は明示的な拒否 (`status="not-done"`) として記録される。

## Scope

- **In scope**: schedule エントリごとの `annual` / `every_n_years` /
  `once` サンプリング、年齢 × 性別 coverage lookup、決定論的な接種日
  配置 (annual → `season_month`、every_n_years → `interval_years`
  step、once → 資格期間内で uniform)、`IMMUNIZATION_NOT_DONE_RECORDING_RATE`
  レートでの拒否記録、合成 lot number 生成 (構造 placeholder、
  正式 batch ではない)、閏日 (Feb 29) 生まれの非閏年 Feb 28 clamp、
  任意 `history_years` の EHR 保持期間 (flu → 10 y 等)。
- **Out of scope**: 小児接種歴の遡及モデリング、副反応 / 副作用生成、
  接種目的の encounter 生成 (現状 first-class encounter ではない)、
  FHIR / CSV serialization ([`clinosim.modules.output`](../output/README.md))、
  CVX の表示テキスト
  ([`clinosim/codes/data/cvx.yaml`](../../codes/data/cvx.yaml))。

## Public API

`__init__.py` は空。呼び出し側は engine + enricher から直接 import:

```python
from clinosim.modules.immunization.engine import (
    generate_immunizations,          # (patient, schedule, as_of, rng, nurse_ids=None)
                                     #   -> list[ImmunizationRecord] (接種日昇順)
    load_schedule,                   # (country) -> {vaccine_name: {cvx, min_age, frequency, ...}}
    IMMUNIZATION_NOT_DONE_RECORDING_RATE,  # 0.02
)
from clinosim.modules.immunization.enricher import enrich_immunizations
```

`load_schedule` は unsupported country に対して `{}` を返す
(2026-07-02 grand-design 契約)。enricher は空 map で no-op。

## 決定論

- サブ seed オフセット `0x494D` (`"IM"`)。
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["immunization"]` に登録済み。
- 患者単位 RNG:
  `derive_sub_seed(master_seed, offset, patient_id)`。患者主 RNG 列は
  消費しない。
- **Lot number は SHA-256 で決定論化 (Python builtin `hash()` は使わない)**。
  Python 標準の文字列ハッシュは interpreter 起動ごとに salt される
  (`PYTHONHASHSEED`) ため、同一 seed でも lot number が run 間で変わる
  drift があった。P1-7 が `reproduce.sh` の determinism gate で検出、
  `engine.py` の `_det_hash` が現在 lot number 生成を担当。
- 担当看護師 (`administered_by`) の割り当ては
  `nurse_ids[sum(ord(c) for c in patient_id) % len(nurse_ids)]` で
  決定論的に選出 (RM-3、実 JP practice に整合)。

## Snapshot (AD-32)

`as_of = ctx.config.snapshot_date` があればその日、なければレコード内
最終 encounter の入院日。`occurrence_date > as_of` は skip し、
in-progress snapshot でのバックデート出力を防ぐ。

## 依存

- `clinosim.modules._shared` — `is_us` / `is_jp`,
  `get_attr_or_key` / `set_attr_or_key`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.types.encounter` — `ImmunizationRecord`
  (`generate_immunizations` 内で遅延 import)。
- `clinosim.codes` (間接、FHIR builder 経由) — CVX 表示 lookup。
- `numpy` — coverage サンプリングの `np.random.Generator`。
- `hashlib.sha256` — `_det_hash` 経由、lot number 決定論化。

他の `clinosim.modules.*` には依存しない。

## 定数と設定

- module レベル定数 (`engine.py`):
  - `IMMUNIZATION_NOT_DONE_RECORDING_RATE = 0.02` — coverage draw
    失敗時に `status="not-done"` を明示記録する per-scheduled-dose
    確率。silent no-show と区別された、記録された拒否 / 延期を表す。
    3 つの frequency ブランチすべてで同一値を適用。
- Locale schedule (本 module に `reference_data/` は無い):
  - [`clinosim/locale/us/immunization_schedule.yaml`](../../locale/us/immunization_schedule.yaml)
    — CDC ACIP adult schedule。現状 5 ワクチン (Influenza,
    COVID-19 mRNA, PPSV23, Tdap, RZV Shingrix)。
  - [`clinosim/locale/jp/immunization_schedule.yaml`](../../locale/jp/immunization_schedule.yaml)
    — MHLW 定期接種 schedule。現状 3 ワクチン (Influenza,
    COVID-19 mRNA, PPSV23)。
- Schedule エントリ shape:
  | キー | 意味 |
  |---|---|
  | `cvx` | CDC CVX コード (文字列)。 |
  | `min_age` | 接種資格の最低年齢。 |
  | `frequency` | `"annual"` / `"once"` / `"every_n_years"`。 |
  | `interval_years` | `every_n_years` 時のみ。年間隔。 |
  | `season_month` | `annual` 時のみ。接種月 (integer)。 |
  | `available_from` | プログラム開始日 (`YYYY-MM-DD`)。 |
  | `history_years` | 任意。EHR 保持期間 (flu → 10 y 等)。 |
  | `coverage_by_age_sex` | `{"age_band": {sex: rate}}` (0-1)。 |
- CVX コード表:
  [`clinosim/codes/data/cvx.yaml`](../../codes/data/cvx.yaml)
  — CDC IIS CVX リスト (2026-06) と 10 コード照合済み。
  FHIR system URI: `http://hl7.org/fhir/sid/cvx`。

## ディレクトリ構造

```
clinosim/modules/immunization/
  __init__.py                     空 (Public API 節参照)
  engine.py                       generate_immunizations + load_schedule + helpers
  enricher.py                     POST_RECORDS enrichment (患者単位サブ RNG)
```

**`reference_data/` ディレクトリと `audit.py` は存在しない** — 国別
データは `clinosim/locale/` 配下にあり、`ModuleAuditSpec` は登録して
いない。検証は下記 test で担保。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) の
`register_builtin_enrichers` で登録:

- `name="immunization"`, `stage=POST_RECORDS`, `order=30`,
  `enabled=lambda c: True`。
- `nursing` (order 20) の後、`family_history` (order 40) の前に実行。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| CSV adapter | [`clinosim/modules/output/csv_adapter.py`](../output/csv_adapter.py) (`L327` 付近, `L417` 付近) | `record["immunizations"]` から `immunizations.csv` を書き出し。 |
| FHIR `Immunization` builder | [`clinosim/modules/output/fhir_r4/procedures/immunization.py`](../output/fhir_r4/procedures/immunization.py) | 記録ごとに FHIR R4 `Immunization` を 1 件出力。id `imm-{patient_id}-{index}`、`vaccineCode` = CVX + locale 表示、`occurrenceDateTime` = 接種日、`primarySource = true`、`administered_by` が非空なら `performer` に反映、`_synthetic_lot` を `lotNumber` に emit。 |
| Enricher registry | [`clinosim/simulator/enrichers.py:162`](../../simulator/enrichers.py) | POST_RECORDS 登録。 |

## テスト

```bash
pytest tests/unit -k immunization -q         # engine
pytest tests/integration -k immunization -q  # enricher + FHIR 出力
```

個別ファイル:

- [`tests/unit/test_immunization.py`](../../../tests/unit/test_immunization.py)
  — engine サンプリング / lot-number 決定論。
- [`tests/integration/test_immunization_enricher.py`](../../../tests/integration/test_immunization_enricher.py)
  — enricher 決定論 + 看護師 roster 割り当て。
- [`tests/integration/test_fhir_immunization.py`](../../../tests/integration/test_fhir_immunization.py)
  — `Immunization` 出力の end-to-end。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
