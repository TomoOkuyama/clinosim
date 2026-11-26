# clinosim datasets

プリセット合成 EHR データセット。各サブディレクトリは 1 つの **名前
付きプリセット** — 固定 clinosim バージョンでの出力を一意に決定する
小さな YAML spec (`spec.yaml`) + データセットカード (`README.md`)。

## 利用可能プリセット

| Preset | Country | Patients | Period | サイズ目安 (FHIR NDJSON) |
| --- | --- | --- | ---: | ---: |
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
強制 (トップレベル [Reproducibility セクション](../README.ja.md#reproducibility) 参照)。

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

## H100 で生成した大規模サンプルコホート (LLM 仕上げ)

一部のリリース (v0.6.1 以降) には、Sakura H100 (vLLM 上の
Qwen3.8-27B-FP8) で生成した、より大規模な LLM 仕上げのサンプル
コホートも添付される。これらは CLI でビルドできるプリセットでは
*ない* — seed は 42 以外で、
[`verify/EMPIRICAL_RESULTS.md`](../verify/EMPIRICAL_RESULTS.md) に記載の
H100 vLLM チューニング契約に従う — が、下流利用者が一括ダウンロード
やリリース間の差分をスクリプト化できるよう、**安定した命名規則**に
従う:

```
clinosim-v<VERSION>-<locale>-p<POP>-s<SEED>-<narrative-generator>.tar.gz
```

各フィールド:

- `<VERSION>`: リリース tag。例 `0.6.3`。
- `<locale>`: `jp` または `us` (小文字)。
- `<POP>`: 診療圏人口。例 `p10000`。
- `<SEED>`: `clinosim simulate` 実行時の `--seed` 値。例 `s3532`。
- `<narrative-generator>`: `template-narrative` (決定的、LLM なし)
  または `llm-polished-narrative` (LLM 生成の bundle narrative)。

内部構成は両 variant で同一:

```
cif/
  hospital.json
  metadata.json            (clinosim_version はリリース tag に固定)
  structural/
    patients/*.json
  narratives/
    current_version.txt    ("llm-polished" または "template" を指す)
    template/              (決定的 template narrative。常に存在)
    llm-polished/          (llm-polished-narrative アーカイブのみ)
fhir_r4/
  *.ndjson                 (全 FHIR R4 リソース)
  _generator_metadata.json (clinosim_version + cif_metadata の入れ子ミラー)
summary/
  cohort-summary.json      (患者数、疾患別患者数、年齢帯、encounter と在院日数の集計)
catalog/
  codes-used.ndjson        (データセットの FHIR リソースが使う全コード)
```

両 metadata ファイルは `clinosim_version` をリリース tag に固定する。
`_generator_metadata.json` には、コホート生成時の git commit と直近の
PR 履歴も記録される。

最近の例: `clinosim-v0.6.3-jp-p10000-s3532-llm-polished-narrative.tar.gz`
と `clinosim-v0.6.3-us-p10000-s3532-llm-polished-narrative.tar.gz`
(`v0.6.3` リリースページ参照)。

## 倫理と免責

同梱される全データセットは **完全に合成**。clinosim は実患者データ、
PHI、PII を取り込み・参照・再現しません。出力は **臨床用途を意図
していない**、いかなる診断・治療・ケア判断にも依拠してはならない。
詳細は
[プロジェクトレベル免責](../README.ja.md#clinosim) 参照。

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
