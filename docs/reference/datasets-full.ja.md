<!-- README.md から抽出 (Issue #568 PR A2)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# データセット

4 つの名前付きデータセットプリセットが
[`datasets/`](datasets/) 配下に配置 — smoke テストとデモ用の小規模
(US/JP × 100)、ML 開発用の中規模 (US/JP × 1000)。全 seed 42 で
CLI から再現可能にビルド可能:

```bash
clinosim dataset list                                    # プリセット一覧
clinosim dataset build jp-100 --output ./jp-100          # プリセット 1 件をビルド
```

| Preset | Country | Patients | Period | サイズ目安 |
|---|---|---:|---:|---:|
| [`us-100`](datasets/us-100/)   | US | 100  | 3 ヶ月 | ~2 MB   |
| [`us-1000`](datasets/us-1000/) | US | 1000 | 6 ヶ月 | ~30 MB  |
| [`jp-100`](datasets/jp-100/)   | JP | 100  | 3 ヶ月 | ~2 MB   |
| [`jp-1000`](datasets/jp-1000/) | JP | 1000 | 6 ヶ月 | ~30 MB  |

各プリセットは HuggingFace 形式のデータセットカード
(`datasets/<name>/README.md`) を同梱し、メタデータ手直しなしで HF
Hub に push 可能。Zenodo integration (`.zenodo.json` at repo root)
は tag された各 release で DOI を発行するので、データ構築に使用した
正確な clinosim バージョンの DOI を引用してください。

**次のリリースサイクル** 以降、release ワークフローは全 4 プリセット
をビルドし GitHub Release アセットとして attach。現行 v0.2.0
release はインフラのみを同梱 — ローカル再現には
`clinosim dataset build` を使用。

FHIR サーバ (HAPI FHIR 等) にデータセットをロードするには
[`../fhir-server-ingestion.ja.md`](../fhir-server-ingestion.ja.md)
参照。

---
