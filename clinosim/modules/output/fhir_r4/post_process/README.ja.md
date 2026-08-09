# `fhir_r4/post_process/` — bundle-level 後処理パイプライン

## 目的

NDJSON 発行直前に組み立て済み FHIR bundle 全体に対して最終 pass を実行:
参照解決、コード値正規化、manifest メタデータ付与、JP-Core プロファイル
assertion、単一 per-resource builder では実施できない cross-resource
整合性 fix-up。

## スコープ

- **In scope**: 全リソースを一度に見る bundle レベル変換、cross-resource
  参照解決、manifest / provenance メタデータ付与。
- **Out of scope**: per-resource 構築 (兄弟の臨床ドメイン builder
  サブパッケージ)、NDJSON シリアライズ本体
  (`fhir_r4/__init__.py` の emit path)。

## 公開 API

パイプラインエントリは親 facade (`register_bundle_builder`) 経由で
dispatch され、外部から直接呼び出されない。

## 依存

- 兄弟 `lib/` — 共有ヘルパー。
- `clinosim.types.output` — bundle レベル manifest 型。
- 個別のドメイン builder サブパッケージへの依存なし。本パイプラインは
  全 builder のリソース発行 *後* に実行される。

## 定数と設定

- 後処理パイプラインで使用する閾値 / 期待値マップは `post_process/`
  内部に置かれ、定義箇所でドキュメント化される。

## ディレクトリ構成

```
clinosim/modules/output/fhir_r4/post_process/
  __init__.py               サブパッケージ facade
  (per-transform .py files、後処理 pass ごとに 1 ファイル)
```

## テスト

```bash
pytest tests/unit -k post_process -q
```

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
