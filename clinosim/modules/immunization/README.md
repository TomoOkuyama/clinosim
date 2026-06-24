# clinosim.modules.immunization — Immunization History Module

## 目的

患者の成人ワクチン接種歴を生成する **AD-55 Base enricher**。
常時有効 (always-on) で全患者に適用される。

- ワクチンコード (CVX) は `clinosim/codes/data/cvx.yaml` (CDC 照合済み)
- 接種スケジュールは `clinosim/locale/<country>/immunization_schedule.yaml` (locale 依存)
- 生成ロジックは `engine.py` の純粋関数。副作用なし

## 提供ワクチン

### US (ACIP adult schedule)

| ワクチン | CVX | 対象 | 接種頻度 | 提供開始 | 接種率出典 |
|---|---|---|---|---|---|
| Influenza | 150 | 18 歳以上 | 毎年 10 月 | 2000-01-01 | CDC FluVaxView |
| COVID-19 mRNA (Pfizer季節性) | 309 | 18 歳以上 | 1 回 | 2020-12-14 | CDC MMWR |
| PPSV23 肺炎球菌 | 33 | 65 歳以上 | 1 回 | 2000-01-01 | CDC MMWR |
| Tdap | 115 | 18 歳以上 | 10 年毎 | 2005-06-01 | CDC MMWR |
| 帯状疱疹 RZV (Shingrix) | 187 | 50 歳以上 | 1 回 | 2017-10-20 | CDC MMWR |

### JP (厚労省 定期接種 schedule)

| ワクチン | CVX | 対象 | 接種頻度 | 提供開始 | 接種率出典 |
|---|---|---|---|---|---|
| Influenza | 150 | 18 歳以上 | 毎年 11 月 | 2000-01-01 | MHLW 接種率統計 |
| COVID-19 mRNA (Pfizer季節性) | 309 | 18 歳以上 | 1 回 | 2021-02-17 | MHLW 接種率統計 |
| PPSV23 肺炎球菌 | 33 | 65 歳以上 | 1 回 | 2014-10-01 | MHLW 接種率統計 |

## データ駆動設計

### CVX コード (`clinosim/codes/data/cvx.yaml`)

CDC IIS (Immunization Information Systems) の公式 CVX リストを出典とする。
FHIR system URI: `http://hl7.org/fhir/sid/cvx`。

全 10 コード (150 / 33 / 133 / 215 / 216 / 115 / 113 / 187 / 309 / 312) を
2026-06 に CDC CVX ダウンロードリストで照合。`en` + `ja` 両エントリ付与済み。

### スケジュール YAML (`clinosim/locale/<country>/immunization_schedule.yaml`)

各ワクチンエントリのキー:

| キー | 説明 |
|---|---|
| `cvx` | CDC CVX コード (文字列) |
| `min_age` | 接種資格の最低年齢 |
| `frequency` | `"annual"` / `"once"` / `"every_n_years"` |
| `interval_years` | `every_n_years` 時のみ。接種間隔 (年) |
| `season_month` | `annual` 時のみ。接種月 (integer) |
| `available_from` | ワクチンプログラム提供開始日 (YYYY-MM-DD) |
| `coverage_by_age_sex` | 年齢帯×性別の接種率 (0–1)。例: `"18-49": {M: 0.32, F: 0.38}` |

`coverage_by_age_sex` は接種率のモデリングパラメータ。
接種率は `_coverage(cov, age, sex)` がバンドマッチで返す。

## Enricher 実行

### AD-56 post_records

`enricher.py` が `simulator/enrichers.py` の `register_builtin_enrichers()` に登録されており、
`POST_RECORDS` ステージ (order=30) で実行される。

```python
Enricher(
    name="immunization",
    stage=POST_RECORDS,
    order=30,
    enabled=lambda c: True,   # always-on (Base)
    run=enrich_immunizations,
)
```

### 決定論的サブシード (AD-16)

メインランダムストリームを汚染しないよう、`hashlib.sha256` ベースの専用サブシードを使用する。

```python
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed

rng = np.random.default_rng(
    derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["immunization"], patient_id)
)
```

オフセット定数(`0x494D` = "IM")は `ENRICHER_SEED_OFFSETS` 中央 registry で管理(PR1 2026-06-24 foundation refactor)。重複は import 時 assert で検出。

患者 ID をキーとして患者ごとに独立した `numpy.random.Generator` を生成するため、
既存の labs / vitals / 診断 / 看護データは byte 不変。

### Snapshot セマンティクス (AD-32)

`as_of` = `config.snapshot_date` があればその日、なければ最新入院日。
`occurrence_date <= as_of` となる接種のみ生成する。

## API

### `load_schedule(country: str) -> dict`

`clinosim/locale/<country>/immunization_schedule.yaml` を読み込み `vaccines` dict を返す。
`@lru_cache(maxsize=4)` でキャッシュ済み (I/O 最小化)。`country` は `"US"` / `"JP"` 等。

```python
from clinosim.modules.immunization.engine import load_schedule
schedule = load_schedule("JP")
# {"influenza": {"cvx": "150", "min_age": 18, ...}, ...}
```

### `generate_immunizations(patient, schedule, as_of, rng) -> list[ImmunizationRecord]`

純粋関数。患者の生年月日・年齢・性別と schedule から `ImmunizationRecord` のリストを返す。
接種日昇順にソート済み。Feb-29 生まれは非閏年で Feb-28 に安全にクランプ。

```python
from clinosim.modules.immunization.engine import generate_immunizations
import numpy as np
from datetime import date

records = generate_immunizations(patient, schedule, date(2025, 1, 1), np.random.default_rng(42))
# [ImmunizationRecord(vaccine_cvx="150", occurrence_date=date(2020, 10, 1), ...),
#  ImmunizationRecord(vaccine_cvx="309", occurrence_date=date(2021, 5, 12), ...)]
```

### `enrich_immunizations(ctx) -> None`

Enricher エントリポイント。`ctx.records` の各患者に `immunizations` リストをセットする。

## CIF 表現

`CIFPatientRecord.immunizations: list[ImmunizationRecord]` に格納される。

**`ImmunizationRecord`** (`clinosim/types/encounter.py`):

```python
@dataclass
class ImmunizationRecord:
    vaccine_cvx:     str        # CVX コード (例: "150")
    occurrence_date: date       # 接種日
    status:          str = "completed"
    primary_source:  bool = True
    dose_number:     int | None = None
```

CIF はコードのみ保持 (AD-30)。display text は出力時に `clinosim.codes.lookup("cvx", code, lang)` で解決する。

## FHIR 出力

`_build_immunizations(ctx)` が `_BUNDLE_BUILDERS` に登録されており、
FHIR R4 `Immunization` リソースを生成する。

| フィールド | 値 |
|---|---|
| `resourceType` | `"Immunization"` |
| `id` | `imm-{patient_id}-{index}` |
| `status` | `"completed"` |
| `vaccineCode.coding[0].system` | `http://hl7.org/fhir/sid/cvx` |
| `vaccineCode.coding[0].code` | CVX コード (例: `"150"`) |
| `vaccineCode.coding[0].display` | 言語別 display (`lookup("cvx", code, "ja"|"en")`) |
| `vaccineCode.text` | 同上 |
| `patient.reference` | `Patient/{patient_id}` |
| `occurrenceDateTime` | ISO 8601 日付 (YYYY-MM-DD) |
| `primarySource` | `true` |

US 出力は英語のみ (Japanese 文字列なし)。JP 出力は `ja` display を使用。

## CSV 出力

`immunizations.csv` に出力。

| カラム | 説明 |
|---|---|
| `patient_id` | 患者 ID |
| `vaccine_cvx` | CVX コード |
| `occurrence_date` | 接種日 (YYYY-MM-DD) |
| `status` | `"completed"` 固定 |
| `dose_number` | 接種回数 (現在 null) |

## 権威出典

| データ | 出典 |
|---|---|
| **CVX コード** | [CDC IIS CVX list](https://www2.cdc.gov/vaccines/iis/iisstandards/vaccines.asp?rpt=cvx) — 2026-06 照合 |
| **US 接種率** | CDC FluVaxView / MMWR (概数モデリングパラメータ) |
| **JP 接種率** | MHLW 接種率統計 (概数モデリングパラメータ) |
| **US スケジュール** | CDC ACIP adult immunization schedule |
| **JP スケジュール** | 厚労省 定期接種スケジュール (MHLW) |
| **FHIR system URI** | HL7 FHIR R4 `http://hl7.org/fhir/sid/cvx` |

## ディレクトリ構造

```
clinosim/modules/immunization/
├── __init__.py
├── engine.py       # 純粋関数 (load_schedule / generate_immunizations)
├── enricher.py     # AD-56 post_records enricher + 専用サブシード
└── README.md
```

関連ファイル:

```
clinosim/codes/data/cvx.yaml                    # CVX コード定義 (10 コード)
clinosim/locale/us/immunization_schedule.yaml   # US スケジュール (5 ワクチン)
clinosim/locale/jp/immunization_schedule.yaml   # JP スケジュール (3 ワクチン)
clinosim/types/encounter.py                     # ImmunizationRecord dataclass
clinosim/simulator/enrichers.py                 # enricher 登録
clinosim/modules/output/fhir_r4_adapter.py      # _build_immunizations
clinosim/modules/output/csv_adapter.py          # immunizations.csv
```

## 依存関係

本モジュールが依存するもの:

| 依存先 | 用途 |
|---|---|
| `clinosim/types/encounter.py` | `ImmunizationRecord` dataclass |
| `clinosim/codes/` | CVX コード lookup / system URI |
| `clinosim/locale/<country>/immunization_schedule.yaml` | 国別スケジュール |
| `numpy` | `random.Generator` によるカバレッジサンプリング |
| `hashlib` | 決定論的サブシード生成 |

## Consumers

このモジュールに依存するもの:

| Caller | How | Impact |
|---|---|---|
| `simulator/enrichers.py` | `POST_RECORDS` 段階での enricher 登録 | core (enricher registry) |
| `modules/immunization/enricher.py` | 同 module 内の enricher 実装 | core |
| `modules/output/_fhir_observations.py` (or future `_fhir_immunization.py` after PR3 split) | `_build_immunizations` で FHIR Immunization 生成 | medium (FHIR builder) |
| `modules/output/csv_adapter.py` (cross-ref) | `immunizations.csv` 書き出し | medium |
| `tests/integration/test_immunization_enricher.py` | enricher integration test | guard |
| `tests/unit/test_immunization.py` | engine unit tests | guard |

## テスト

```bash
# unit テスト
pytest tests/unit/test_immunization.py -v
```

## 実装状況

- [x] CVX コード (10 コード、CDC 照合済み)
- [x] US adult schedule (5 ワクチン、available_from + coverage_by_age_sex)
- [x] JP adult schedule (3 ワクチン、available_from + coverage_by_age_sex)
- [x] 生成ロジック (`annual` / `once` / `every_n_years`、Feb-29 DOB 対応)
- [x] AD-56 Base enricher (POST_RECORDS order=30、dedicated hashlib sub-seed)
- [x] AD-32 snapshot (occurrence_date ≤ as_of)
- [x] CIF: `ImmunizationRecord` (vaccine_cvx / occurrence_date / status / primary_source)
- [x] FHIR R4 Immunization (CVX vaccineCode、US/JP 多言語 display)
- [x] CSV: `immunizations.csv`
- [ ] dose_number (series tracking: Shingrix 2-dose, mRNA primary series)
- [ ] 小児接種歴の遡及モデリング
