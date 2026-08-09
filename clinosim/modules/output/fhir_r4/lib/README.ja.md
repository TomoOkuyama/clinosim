# `fhir_r4/lib/` — FHIR-R4 builder 共有ヘルパー

## 目的

[`fhir_r4/`](../README.ja.md) 配下のすべての builder サブパッケージが
共有する共通ユーティリティ: reference-data ローディング、locale 別
localisation dispatch、ID プレフィックス定数、inline building-block
ヘルパー、generator-metadata Extension 発行、`common` 名前空間の低レベル
primitives。

## スコープ

- **In scope**: 2 つ以上の builder サブパッケージから import される
  共有ヘルパー。ドメイン固有 builder は含まない。
- **Out of scope**: FHIR リソース固有の builder ロジック — それらは
  兄弟の臨床ドメインサブパッケージに属する。

## 公開 API

```python
from clinosim.modules.output.fhir_r4.lib import (
    common,                      # 低レベル Coding / CodeableConcept ヘルパー
    localization,                # en / ja text localisation dispatch
    reference_data,              # profile URI / canonical URL / code-system URL
    inline_bb,                   # inline-building-block ヘルパー
    generator_metadata,          # 生成メタデータ Extension emitter
    ids,                         # リソース ID プレフィックス定数
)
```

## 依存

- `clinosim.types` — FHIR 隣接の共有 dataclass。
- `clinosim.codes` — code system lookup。
- `pyyaml` — reference-data 読込み。

## 定数と設定

- リソース ID プレフィックス (例 `DOC_REFERENCE_ID_PREFIX = "doc-"`)
  は `ids.py` に定義され、builder から import される。
- JP-Core / JP-CLINS プロファイル URI と canonical URL は
  `reference_data/*.yaml` に集約 — `meta.profile` を打刻する全 builder
  が参照する single source of truth。

## ディレクトリ構成

```
clinosim/modules/output/fhir_r4/lib/
  __init__.py               公開 API 再エクスポート
  common.py                 Coding / CodeableConcept / Reference ヘルパー
  localization.py           en / ja text dispatch
  reference_data.py         profile URI + canonical URL ローダー
  inline_bb.py              inline building-block ヘルパー
  generator_metadata.py     生成メタデータ Extension emitter
  ids.py                    リソース ID プレフィックス定数
```

## テスト

```bash
pytest tests/unit -k fhir_r4_lib -q
```

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
