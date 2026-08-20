# `clinosim.modules.sdoh` — SDOH 社会歴 reference data

## 概要

シミュレータが patient activation 時に `PatientProfile` に設定する SDOH
(social determinants of health = 社会的決定要因) 属性 — 現状
`smoking_status` (US Core LOINC 72166-2) と `alcohol_use`
(LOINC 11331-6) — の enum → SNOMED + LOINC 参照 mapping を提供する
AD-55 Base モジュール。下流の FHIR builder が本データを読み、
category `social-history` の `Observation` を出力する。

本モジュールは **data-only variant**
([`docs/CONTRIBUTING-modules.md`](../../../docs/CONTRIBUTING-modules.md)
「データ専用モジュール (variant)」節参照): `enricher.py` なし、
`assign_*` 関数なし、乱数使用なし。属性の割り当ては
`patient/activator.py` が `locale/{us,jp}/demographics.yaml` を読んで
行う。

## Scope

- **In scope**: smoking / alcohol の tier → SNOMED コード対応と、
  topic ごとの LOINC observation code を SDOH topic + enum 値で公開。
- **Out of scope**: `smoking_status` / `alcohol_use` の患者単位割り当て
  ([`clinosim.modules.patient`](../patient/README.md) activator +
  [`clinosim/locale/{us,jp}/demographics.yaml`](../../locale/))、
  FHIR `Observation` 出力
  ([`clinosim.modules.output.fhir_r4.demographics.smoking_alcohol`](../output/fhir_r4/demographics/smoking_alcohol.py))、
  SNOMED 表示テキスト
  ([`clinosim/codes/data/snomed-ct.yaml`](../../codes/data/snomed-ct.yaml))、
  未だ `PatientProfile` に無い SDOH topic (職業、教育、住居、食料
  insecurity 等、「拡張」節参照)。

## Public API

```python
from clinosim.modules.sdoh import load_social_history

data = load_social_history()
# data["smoking_status"]["loinc"]                    -> "72166-2"
# data["smoking_status"]["category"]                 -> "social-history"
# data["smoking_status"]["values"]["never"]["snomed"] -> "266919005"
```

`load_social_history` は `@lru_cache(maxsize=1)` 付きで反復呼び出し
コストゼロ。`__init__.py` が再 export する本モジュール唯一の公開 API。

## 依存

- `yaml` — reference file の YAML パーサ。
- `clinosim.codes` (間接、FHIR builder 経由) — 出力時の SNOMED 表示
  lookup。
- 他の `clinosim.modules.*` / locale / types への依存なし。

## 定数と設定

- [`reference_data/social_history.yaml`](reference_data/social_history.yaml)
  — country-neutral。現状 2 topic:
  - `smoking_status` — LOINC `72166-2`、category `social-history`、
    enum 3 値: `never` (SNOMED 266919005) / `former` (8517006) /
    `current` (449868002)。US Core profile
    `us-core-smokingstatus`。
  - `alcohol_use` — LOINC `11331-6`、category `social-history`、
    enum 3 値: `none` (SNOMED 105542008) / `social` (28127009) /
    `heavy` (86933000)。HL7 social-history pattern (US Core profile
    なし)。
- 6 SNOMED コードはすべて
  [`clinosim/codes/data/snomed-ct.yaml`](../../codes/data/snomed-ct.yaml)
  に登録済 (`en` + `ja` 両表示あり)。PR #68 の SNOMED CT authority
  crosswalk で照合済み。

## ディレクトリ構造

```
clinosim/modules/sdoh/
  __init__.py                     load_social_history を再 export
  engine.py                       load_social_history (loader 単一)
  reference_data/
    social_history.yaml           smoking + alcohol enum → SNOMED + LOINC
```

**`enricher.py` / `audit.py` は存在せず、`ENRICHER_SEED_OFFSETS`
にも seed 登録なし**。`register_builtin_enrichers` にも登録されていない。
検証は下記 unit + integration test で担保。

## 拡張

「出力時 lookup で解決するシンプル enum 属性」に該当する SDOH data は
本モジュールに追加する:

1. `PatientProfile` に該当属性が既にある (smoking_status パターン)
   → `reference_data/social_history.yaml` に topic を追加、または
   `reference_data/<topic>.yaml` を新規作成し、
   `clinosim/modules/output/fhir_r4/demographics/` に FHIR builder
   を追加。
2. 割り当てに計算が必要 (例: `food_insecurity` を住所 + 所得から
   導出) → `clinosim/modules/<theme>/` に独立モジュール
   (engine + enricher フル setup) を作る。**計算ロジックを sdoh に
   混入させない**。

要介護度 (care_level) の FHIR 出力は元々 `_fhir_sdoh.py` に同居
していたが、PR2 G2 (2026-06-24) で single-responsibility 分離のため
独立 module 化した — 複雑度の高い SDOH は同じく独立化するのが
定着パターン。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| FHIR `Observation` builder | [`clinosim/modules/output/fhir_r4/demographics/smoking_alcohol.py`](../output/fhir_r4/demographics/smoking_alcohol.py) | `load_social_history()` を読み、smoking + alcohol の social-history `Observation` を 2 件出力 (LOINC observation code + enum ごとの SNOMED `valueCodeableConcept`)。 |

SDOH 専用の CSV 列は無い。smoking / alcohol は患者 CSV 行内に格納される。

## テスト

```bash
pytest tests/unit -k sdoh -q          # loader + codes + csv
pytest tests/integration -k sdoh -q   # FHIR 出力
```

個別ファイル:

- [`tests/unit/test_sdoh_engine.py`](../../../tests/unit/test_sdoh_engine.py)
  — loader shape + caching。
- [`tests/unit/test_sdoh_codes.py`](../../../tests/unit/test_sdoh_codes.py)
  — SNOMED コードの authoritative + active concept 検証
  (PR #68 + PR2 update)。
- [`tests/unit/test_sdoh_csv.py`](../../../tests/unit/test_sdoh_csv.py)
  — 患者 CSV 行の smoking / alcohol カラム。
- [`tests/integration/test_fhir_sdoh.py`](../../../tests/integration/test_fhir_sdoh.py)
  — `Observation` 出力の end-to-end。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
