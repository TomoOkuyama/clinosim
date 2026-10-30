# 設定

実行時設定は `clinosim/config/*.yaml` からロードされます。以下の
テーブルは最も使用される CLI フラグと環境変数を列挙します。決定的な
machine-readable リストは `clinosim simulate --help` を実行。

## 主要 CLI フラグ (`clinosim simulate`)

| Flag | Default | 意味 |
| --- | --- | --- |
| `--country {US,JP}` | `US` | Locale — 氏名 / 住所 / 保険 / コードシステムを制御 |
| `--population N` | hospital config の catchment デフォルト | 集団サイズ (人) |
| `--seed N` | `42` | 決定的 seed (AD-16 不変条件) |
| `--start YYYY-MM-DD` / `--end YYYY-MM-DD` | 今日終了の過去 1 年 | シミュレーションウィンドウ |
| `--output PATH` | `./output` | 出力ディレクトリ |
| `--format {cif,fhir-r4,csv}` | `cif` | 1 つ以上の出力形式 (`fhir` は `fhir-r4` の alias)。形式ごとにサブディレクトリ (`cif/` / `fhir_r4/` / `csv/`) に出力 |
| `--hospital-config PATH` | `clinosim/config/hospital_operations.yaml` | 病院形状 override YAML |
| `--jp-insurance` / `--no-jp-insurance` | on | (JP のみ) 保険加入 / 被保険者番号を FHIR Coverage として出力 |
| `--allow-legacy` | off | (JP のみ) JP-CLINS パッケージ無しで続行し旧 5 桁 JLAC10 コードを出力 (指定しないとパッケージ無しの JP 実行はエラー終了) |
| `--cache-dir PATH` | 未設定 | F4 memoize: 以前のスナップショット出力ディレクトリをキャッシュとして再利用 |
| `--log-file PATH` | `<output>/simulator.log` | 構造化 JSONL シミュレータログ |

## 主要環境変数

| 変数 | Default | 意味 |
| --- | --- | --- |
| `CLINOSIM_JP_CLINS_PKG_DIR` | 未設定 | JP-CLINS パッケージの `package/` ディレクトリへのパス。最初に探索され、無ければ `fhir` CLI キャッシュ (`~/.fhir/packages/`) を使用。`--country JP` にはパッケージが必要 ([`jp-clins.ja.md`](../jp-clins.ja.md) 参照) |
| `CLINOSIM_LOG_LEVEL` | `INFO` | シミュレータの Python logging level (`DEBUG` / `INFO` / `WARNING` / `ERROR`) |
| `CLINOSIM_ALLOW_LEGACY_JP_CLINS_PKG` | 未設定 | `1` を設定すると `--allow-legacy` と等価 (JP 実行が JP-CLINS パッケージ無しで続行し、旧 5 桁 JLAC10 コードを出力) |
| `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | AWS デフォルトチェーン | AWS Bedrock narrative provider (`--provider bedrock`) にのみ必要 |

## 名前付きプリセットデータセット

プリセット config bundle 経由の再現可能リリース:

```bash
clinosim dataset list                           # 利用可能プリセット表示
clinosim dataset build jp-100 --output ./jp-100-out
```

## 病院設定 override

デフォルト病院形状 (ベッド数、ward mix、スタッフ roster) は
`clinosim/config/hospital_operations.yaml` からロード。
`hospital_small.yaml` (10 床) と `hospital_large.yaml` (200 床) も
同梱。カスタム形状を使うには `--hospital-config path/to/your.yaml` を
渡す。スキーマは
[`clinosim/config/README.ja.md`](https://github.com/TomoOkuyama/clinosim/blob/master/clinosim/config/README.ja.md)
参照。
