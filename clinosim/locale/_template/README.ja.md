# 国 scaffold テンプレート (`_template`)

このディレクトリは **schema-only scaffold** であり、実行可能な国では
ない。各 YAML ファイルにはプレースホルダ値 (`__TODO_...__` または
空リスト) と schema-shape コメントが入っている。フォルダを
`<xx>/` locale ディレクトリにコピーし、プレースホルダを権威
ソースからのデータで置き換える。

完全な walk-through は [`docs/add-your-country.md`](../../../docs/add-your-country.md)
参照。

## ファイル

| File | Required? | Purpose |
|---|---|---|
| `names.yaml` | ✓ | Given / family 名 + 頻度重み |
| `addresses.yaml` | ✓ | Region / 郵便番号 |
| `demographics.yaml` | ✓ | 年齢 / 血液型 / 慢性疾患 prevalence / 疾患 incidence |
| `formatting.yaml` | ✓ | 日付 / 時刻 / 数値フォーマット |
| `code_mapping_diagnosis.yaml` | ✓ | 内部疾患 id → 国別 diagnosis コード |
| `code_mapping_lab.yaml` | ✓ | 内部 lab 名 → 国別 lab コード |
| `code_mapping_drug.yaml` | ✓ | 内部薬剤名 → 国別薬剤コード |
| `code_mapping_procedure.yaml` | ✓ | 内部 procedure 名 → 国別 procedure コード |
| `reference_range_lab.yaml` | ✓ | 性別 / 年齢別 lab 参照範囲 |

## Non-runnable 警告

Scaffold は意図的に `_COUNTRY_DIR_MAP` で有効な国として自身を宣言
**しない**。`clinosim simulate --country _template` の実行は fail
する。これは「プレースホルダデータでの偶発実行」エラーを防止する。
