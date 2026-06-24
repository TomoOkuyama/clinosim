# clinosim/modules/sdoh

AD-55 Base SDOH (social determinants of health = 社会的決定要因) モジュール。

データ専用モジュール (variant) — generation / assignment logic を持たず、
**reference データ + loader のみ** を提供する軽量モジュール (PR2 2026-06-24
で確立)。`clinosim/codes/` が同パターンの先例。

## 役割

PatientProfile activation 時に決定される social-history 属性 (smoking_status,
alcohol_use) を FHIR Observation として出力するための **enum→SNOMED + LOINC
マッピング** を YAML で提供。

| 属性 | LOINC | US Core profile |
|---|---|---|
| smoking_status | 72166-2 | us-core-smokingstatus |
| alcohol_use | 11331-6 | (HL7 social history) |

SNOMED display は `clinosim.codes.lookup("snomed-ct", code, lang)` で
解決 (本モジュールには重複させない)。6 SNOMED コードは全て
`codes/data/snomed-ct.yaml` に登録済 (PR #68 で照合)。

## Public API

```python
from clinosim.modules.sdoh import load_social_history

data = load_social_history()
# data["smoking_status"]["loinc"]  → "72166-2"
# data["smoking_status"]["values"]["never"]["snomed"]  → "266919005"
```

`@lru_cache(maxsize=1)` 付きなので反復呼び出し OK。

## ファイル構成

```
clinosim/modules/sdoh/
  __init__.py            # load_social_history を export
  engine.py              # loader (assignment 関数なし)
  reference_data/
    social_history.yaml  # smoking_status + alcohol_use 定義
  README.md
```

## Dependencies

- `clinosim/codes/` — 表示文字列の解決 (`code_lookup("snomed-ct", ...)`)
- なし (他モジュール / locale / types への依存なし)

## Consumers

このモジュールに依存するもの:

| Caller | How | Impact |
|---|---|---|
| `modules/output/_fhir_smoking_alcohol.py` | `load_social_history()` で SNOMED + LOINC mapping を取得して FHIR Observation 化 (smoking + alcohol) | medium (FHIR builder) |
| `tests/unit/test_sdoh_engine.py` | loader unit tests (7 件、PR2 で作成) | guard |
| `tests/unit/test_sdoh_codes.py` | SNOMED コード authority + active concept 検証 (PR #68 + PR2 update) | guard |
| (将来) `modules/output/_fhir_occupation.py` 等 | 将来 SDOH 拡張時の同型 builder | optional |

## 将来の SDOH 拡張

新しい SDOH 属性 (occupation, education, housing, food insecurity 等) を
追加する場合:

1. **PatientProfile に simple enum 属性として既に存在** (smoking/alcohol 同型)
   → `reference_data/social_history.yaml` に topic を追加 or
   `reference_data/<topic>.yaml` を新規 (LOINC ありの社会歴 Observation
   ファミリ)
2. **assignment / 計算ロジックが必要** (例: food_insecurity が住所 + 所得
   から導出) → 独立モジュール `clinosim/modules/<theme>/` を作る
   (engine.py + enricher.py のフル setup)

つまり本モジュールは AD-55 Base "シンプル属性" のデータ集約場所であり、
複雑な計算が必要なものは独立モジュール化する。

## 関連

- AD-55 Base (PR #65 で smoking/alcohol/care_level 追加)
- PR2 2026-06-24 (本モジュール作成、`_fhir_sdoh.py` から分離)
- CONTRIBUTING-modules.md「データ専用モジュール (variant)」
