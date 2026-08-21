# 設定

実行時設定は `clinosim/config/*.yaml` からロードされます。以下の
テーブルは最も使用される CLI フラグと環境変数を列挙します。決定的な
machine-readable リストは `clinosim simulate --help` を実行。

## 主要 CLI フラグ (`clinosim simulate`)

| Flag | Default | 意味 |
|---|---|---|
| `--country {US,JP}` | `US` | Locale — 氏名 / 住所 / 保険 / コードシステムを制御 |
| `--population N` | hospital config の catchment デフォルト | 集団サイズ (人) |
| `--seed N` | `42` | 決定的 seed (AD-16 不変条件) |
| `--start YYYY-MM-DD` / `--end YYYY-MM-DD` | 今日終了の過去 1 年 | シミュレーションウィンドウ |
| `--output PATH` | `./output` | 出力ディレクトリ |
| `--format {cif,fhir-r4,csv}` | `cif` | 1 つ以上の出力形式 |
| `--hospital-config PATH` | `hospital_operations.yaml` | 病院形状 override YAML |

## 主要環境変数

| 変数 | Default | 意味 |
|---|---|---|
| `CLINOSIM_JP_CLINS_PKG_DIR` | 未設定 | JP-CLINS パッケージディレクトリへのパス (JP-CLINS lab-compliance gate 必須; [`jp-clins.ja.md`](../jp-clins.ja.md) 参照) |
| `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | AWS デフォルトチェーン | AWS Bedrock narrative provider (`--provider bedrock`) にのみ必要 |

## 名前付きプリセットデータセット

プリセット config bundle 経由の再現可能リリース:

```bash
clinosim dataset list                           # 利用可能プリセット表示
clinosim dataset build jp-100 --output ./jp-100-out
```

## 病院設定 override

デフォルト病院形状 (ベッド数、ward mix、スタッフ roster) は
`hospital_operations.yaml` からロード。カスタム形状を使うには
`--hospital-config path/to/your.yaml` を渡す。スキーマは
[`../architecture/module-architecture.md`](../architecture/module-architecture.md)
参照。
