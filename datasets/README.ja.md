# clinosim datasets

プリセット合成 EHR データセット。各サブディレクトリは 1 つの **名前
付きプリセット** — 固定 clinosim バージョンでの出力を一意に決定する
小さな YAML spec (`spec.yaml`) + データセットカード (`README.md`)。

## 利用可能プリセット

| Preset | Country | Patients | Period | サイズ目安 (FHIR NDJSON) |
|---|---|---|---:|---:|
| [`us-100`](us-100/)   | US | 100  | 3 ヶ月 | ~2 MB   |
| [`us-1000`](us-1000/) | US | 1000 | 6 ヶ月 | ~30 MB  |
| [`jp-100`](jp-100/)   | JP | 100  | 3 ヶ月 | ~2 MB   |
| [`jp-1000`](jp-1000/) | JP | 1000 | 6 ヶ月 | ~30 MB  |

全 4 プリセットは seed 42 で `--format fhir` を使用 (HL7 FHIR R4
Bulk Data Access NDJSON、ResourceType ごとに 1 ファイル)。

## ローカルでデータセットをビルド

各プリセットは単一コマンドでビルド:

```bash
clinosim dataset list                          # 利用可能プリセット一覧
clinosim dataset build jp-100 --output ./jp-100-out
```

これは `clinosim simulate` の薄いラッパー — 等価なロングフォームは:

```bash
clinosim simulate \
    --country JP --population 100 --seed 42 \
    --start 2026-01-01 --end 2026-03-31 \
    --output ./jp-100-out --format fhir
```

同 clinosim バージョンでリリース build とバイト単位で一致。これが
SemVer 決定性契約; `reproducibility` CI ジョブが全 push でこれを
強制 (トップレベル [Reproducibility セクション](../README.md#reproducibility) 参照)。

## Pre-built データセットのダウンロード

次のリリースサイクルから、tag された release は自動的に pre-built
データセット tarball を GitHub Release ページに attach します:

```bash
# v0.2.0 は データセット attachment なしで出荷 (インフラは
# post-release でランド)。v0.3.0 以降:
gh release download v0.3.0 --pattern "clinosim-dataset-jp-100-*.tar.gz"
tar -xzf clinosim-dataset-jp-100-v0.3.0.tar.gz
```

リリース間は `clinosim dataset build` をローカルで使用 — 出力は
バイト同一保証。

## 倫理と免責

同梱される全データセットは **完全に合成**。clinosim は実患者データ、
PHI、PII を取り込み・参照・再現しません。出力は **臨床用途を意図
していない**、いかなる診断・治療・ケア判断にも依拠してはならない。
詳細は
[プロジェクトレベル免責](../README.md#clinosim) 参照。

## 引用

データセットが研究で使用される場合、リポジトリルートの
[`CITATION.cff`](../CITATION.cff) 経由で基礎となる clinosim release
を引用してください。Zenodo integration (`.zenodo.json`) は tag された
各 release で DOI を発行、データセットビルドバージョンごとに安定な
識別子を提供。

## 新規プリセット追加

1. `datasets/<name>/spec.yaml` を `name` / `country` / `population`
   / `seed` / `start` / `end` で作成。
2. `datasets/<name>/README.md` データセットカード (HuggingFace
   frontmatter + 本文) を追加。
3. `clinosim dataset build <name>` — 成功必須。
4. `bash scripts/reproduce.sh` — green 維持必須。

以上。CLI にコード変更不要 — spec は実行時に読み込まれる。
