# `fhir_r4/documents/` — 臨床文書 FHIR R4 builder

## 目的

臨床文書用の FHIR R4 リソース発行: `Composition` (構造化臨床文書)、
`DocumentReference` (ナラティブテキストへのメタデータポインタ)。

## スコープ

- **In scope**: `Composition` builder (section 単位組立て、JP 用の
  JP-CLINS Composition プロファイル準拠)、`DocumentReference` builder
  (メタデータ + content-attached-text 発行)。
- **Out of scope**: document type レジストリ
  ([`clinosim.modules.document/`](../../../document/README.ja.md))、
  ナラティブテキスト生成
  ([`clinosim.modules.document.narrative/`](../../../document/narrative/README.ja.md))、
  ナラティブ version tracking (CIF-writer 管理、
  [`clinosim.modules.output/`](../../README.ja.md) 参照)。

## 公開 API

Builder は親 facade (`register_bundle_builder`) 経由で dispatch され、
外部から直接呼び出されない。

## 定数と設定

- Composition の section ID と LOINC document-type コードは
  [`clinosim.modules.document/`](../../../document/README.ja.md) の
  `DocumentTypeSpec` レジストリ由来。
- リソース ID プレフィックス:
  - `DOC_REFERENCE_ID_PREFIX = "doc-"`
  - `COMPOSITION_ID_PREFIX = "comp-"`
  ([`lib/ids.py`](../lib/README.ja.md) 定義)。
- eCS 文書タイプ用の JP-CLINS Composition プロファイル URI は
  [`lib/reference_data/`](../lib/README.ja.md) 由来。

## 依存

- `clinosim.types.clinical` — `ClinicalDocument`。
- `clinosim.types.document` — `DocumentType` / `DocumentTypeSpec`。
- 兄弟 `lib/` — 共有ヘルパー。

## ディレクトリ構成

```
clinosim/modules/output/fhir_r4/documents/
  __init__.py               サブパッケージ facade
  composition.py            Composition builder
  document_reference.py     DocumentReference builder
```

## テスト

```bash
pytest tests/unit -k documents -q
pytest tests/integration -k composition -q
```

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
